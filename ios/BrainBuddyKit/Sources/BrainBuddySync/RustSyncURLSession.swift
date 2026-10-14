import BrainBuddyAPI
import BrainBuddyCore
import Foundation
import Synchronization

#if canImport(FoundationNetworking)
    import FoundationNetworking
#endif

/// The `URLSession` the Rust sync transport and hint stream use: ephemeral, no cookie jar, no cache
/// (the session cookie is added by `SessionCookieCredential`, never by the system), and no redirects
/// (following one would resend the `Cookie` header to wherever `Location` points).
public enum RustSyncURLSession {
    public static var defaultConfiguration: URLSessionConfiguration {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpShouldSetCookies = false
        configuration.httpCookieStorage = nil
        configuration.httpCookieAcceptPolicy = .never
        configuration.urlCache = nil
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        return configuration
    }

    /// The API origin the core's origin-relative paths (`/api/sync/v1/…`) are resolved against:
    /// the server address without its trailing `/api`.
    public static func origin(of serverURL: URL) -> URL {
        var text = serverURL.absoluteString
        while text.hasSuffix("/") { text.removeLast() }
        if text.lowercased().hasSuffix("/api") { text.removeLast(4) }
        return URL(string: text) ?? serverURL
    }

    static func url(origin: URL, path: String) -> URL? {
        var text = origin.absoluteString
        while text.hasSuffix("/") { text.removeLast() }
        return URL(string: text + path)
    }

    static func headers(_ request: inout URLRequest, accept: String, identity: ClientIdentity) {
        request.setValue(accept, forHTTPHeaderField: "Accept")
        request.setValue("\(identity.name)/\(identity.version)", forHTTPHeaderField: "X-Client")
        request.setValue(UUID().uuidString.lowercased(), forHTTPHeaderField: "X-Correlation-ID")
    }

    /// `Retry-After` as seconds: a number, or an HTTP date (RFC 9110).
    static func retryAfter(_ header: String?, now: Date = Date()) -> TimeInterval? {
        guard let header = header?.trimmingCharacters(in: .whitespaces), !header.isEmpty else { return nil }
        if let seconds = TimeInterval(header), seconds >= 0 { return seconds }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(identifier: "GMT")
        formatter.dateFormat = "EEE, dd MMM yyyy HH:mm:ss zzz"
        guard let date = formatter.date(from: header) else { return nil }
        return max(0, date.timeIntervalSince(now))
    }

    static func make(_ configuration: URLSessionConfiguration, delegate: (any URLSessionDelegate)? = nil) -> URLSession {
        URLSession(configuration: configuration, delegate: delegate ?? RefuseRedirects(), delegateQueue: nil)
    }
}

/// Answers every redirect with "don't follow": the 3xx comes back as the answer.
final class RefuseRedirects: NSObject, URLSessionTaskDelegate, Sendable {
    func urlSession(
        _ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
        newRequest request: URLRequest, completionHandler: @escaping @Sendable (URLRequest?) -> Void
    ) {
        completionHandler(nil)
    }
}

// MARK: - Request/response transport

/// `RustSyncTransport` over `URLSession`. The core calls `send` from its own sync worker thread,
/// which blocks here until the answer arrives (never the main thread, never the cooperative pool);
/// the cancellation token is polled while it waits and aborts the task.
public final class URLSessionRustSyncTransport: RustSyncTransport {
    private let origin: URL
    private let credential: SessionCookieCredential
    private let identity: ClientIdentity
    private let session: URLSession
    private let failureCorrelationID = Mutex<String?>(nil)

    /// The `X-Correlation-ID` of the most recent non-2xx answer (nil when that answer carried none or
    /// a malformed one), taken by the caller: reading it clears it. A later 2xx does not clear it, so
    /// a round that failed and then retried successfully hands over the failed request's ID only
    /// until the host reads it at the end of each round. Content-free: the ID only, never a body.
    public func takeLastFailureCorrelationID() -> String? {
        failureCorrelationID.withLock { value in
            defer { value = nil }
            return value
        }
    }

    /// True for the opaque IDs the server mints (UUIDs); anything else is not shown to people.
    static func isPlainCorrelationID(_ value: String) -> Bool {
        (1...64).contains(value.count)
            && value.unicodeScalars.allSatisfy { ($0.isASCII && ($0.properties.isAlphabetic || ("0"..."9").contains($0))) || $0 == "-" || $0 == "_" }
    }

    public init(
        serverURL: URL, tokenStore: any SessionTokenStore, identity: ClientIdentity = .iOS,
        configuration: URLSessionConfiguration = RustSyncURLSession.defaultConfiguration
    ) {
        origin = RustSyncURLSession.origin(of: serverURL)
        credential = SessionCookieCredential(serverURL: serverURL, tokenStore: tokenStore)
        self.identity = identity
        session = RustSyncURLSession.make(configuration)
    }

    deinit { session.finishTasksAndInvalidate() }

    private struct Outcome {
        var data: Data?
        var response: URLResponse?
        var error: (any Error)?
    }

    public func send(
        _ request: RustSyncRequest, cancel: RustSyncCancellation
    ) throws(RustSyncTransportFailure) -> RustSyncResponse {
        if cancel.isCancelled { throw .cancelled }
        guard let url = RustSyncURLSession.url(origin: origin, path: request.path) else { throw .connection }
        var urlRequest = URLRequest(
            url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: request.timeout)
        urlRequest.httpMethod = request.method == .get ? "GET" : "POST"
        RustSyncURLSession.headers(&urlRequest, accept: "application/json", identity: identity)
        if let body = request.body {
            urlRequest.httpBody = body
            urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        var sentToken: String?
        switch credential.authorize(&urlRequest) {
        case .attached(let token): sentToken = token
        case .anonymous: break
        // Nothing may be sent: the person has to sign in again, which is what a 401 says.
        case .denied: return RustSyncResponse(status: 401, retryAfter: nil, body: Data("{}".utf8))
        case .unavailable: throw .connection
        }

        let outcome = Mutex(Outcome?.none)
        let done = DispatchSemaphore(value: 0)
        let task = session.dataTask(with: urlRequest) { data, response, error in
            outcome.withLock { $0 = Outcome(data: data, response: response, error: error) }
            done.signal()
        }
        task.resume()
        // The whole answer within `timeout`: URLSession's own timeout is per idle interval.
        let deadline = Date().addingTimeInterval(request.timeout)
        var timedOut = false
        while done.wait(timeout: .now() + .milliseconds(25)) == .timedOut {
            if cancel.isCancelled || Date() >= deadline {
                timedOut = !cancel.isCancelled
                task.cancel()
                done.wait()
                break
            }
        }
        guard let result = outcome.withLock({ $0 }) else { throw .connection }
        if let error = result.error {
            if timedOut { throw .timeout }
            if cancel.isCancelled { throw .cancelled }
            switch (error as? URLError)?.code {
            case .some(.timedOut): throw .timeout
            case .some(.cancelled): throw .cancelled
            default: throw .connection
            }
        }
        guard let http = result.response as? HTTPURLResponse else { throw .connection }
        credential.observe(
            statusCode: http.statusCode, setCookie: Self.header(http, "Set-Cookie"), sentToken: sentToken)
        if !(200..<300).contains(http.statusCode) {
            let id = Self.header(http, "X-Correlation-ID")?.trimmingCharacters(in: .whitespaces)
            failureCorrelationID.withLock { $0 = id.flatMap { Self.isPlainCorrelationID($0) ? $0 : nil } }
        }
        return RustSyncResponse(
            status: http.statusCode, retryAfter: RustSyncURLSession.retryAfter(Self.header(http, "Retry-After")),
            body: result.data ?? Data())
    }

    static func header(_ response: HTTPURLResponse, _ name: String) -> String? {
        for (key, value) in response.allHeaderFields where (key as? String)?.lowercased() == name.lowercased() {
            return value as? String ?? String(describing: value)
        }
        return nil
    }
}

// MARK: - Hint stream

/// `RustSyncHintStream` over `URLSession`: `GET /api/sync/v1/hints` with `Accept: text/event-stream`,
/// the session cookie, no `Last-Event-ID`. Chunks are handed to the reader as they arrive; a stream
/// silent for the idle timeout is dead (the server sends a heartbeat at least every 15 s).
public final class URLSessionRustSyncHintStream: RustSyncHintStream {
    private let origin: URL
    private let credential: SessionCookieCredential
    private let identity: ClientIdentity
    private let configuration: URLSessionConfiguration

    public init(
        serverURL: URL, tokenStore: any SessionTokenStore, identity: ClientIdentity = .iOS,
        configuration: URLSessionConfiguration = RustSyncURLSession.defaultConfiguration
    ) {
        origin = RustSyncURLSession.origin(of: serverURL)
        credential = SessionCookieCredential(serverURL: serverURL, tokenStore: tokenStore)
        self.identity = identity
        self.configuration = configuration
    }

    public func open(
        path: String, idleTimeout: TimeInterval, cancel: RustSyncCancellation
    ) throws(RustSyncStreamFailure) -> any RustSyncHintReader {
        if cancel.isCancelled { throw .cancelled }
        guard let url = RustSyncURLSession.url(origin: origin, path: path) else { throw .connection }
        // The stream may stay quiet for `idleTimeout`; URLSession's own limits must not cut it first.
        var urlRequest = URLRequest(
            url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: max(idleTimeout, 1) + 5)
        urlRequest.httpMethod = "GET"
        RustSyncURLSession.headers(&urlRequest, accept: "text/event-stream", identity: identity)
        urlRequest.setValue("no-cache", forHTTPHeaderField: "Cache-Control")
        var sentToken: String?
        switch credential.authorize(&urlRequest) {
        case .attached(let token): sentToken = token
        case .anonymous: break
        case .denied: throw .status(401)
        case .unavailable: throw .connection
        }
        let pump = HintPump()
        let session = RustSyncURLSession.make(configuration, delegate: pump)
        let task = session.dataTask(with: urlRequest)
        let reader = HintStreamReader(pump: pump, session: session, task: task, idleTimeout: idleTimeout)
        task.resume()
        do {
            try pump.awaitResponse(idleTimeout: idleTimeout, cancel: cancel)
        } catch {
            if case .status(401) = error {
                credential.observe(statusCode: 401, setCookie: nil, sentToken: sentToken)
            }
            reader.close()
            throw error
        }
        return reader
    }
}

/// Receives the stream on `URLSession`'s queue and hands it to the reader's thread.
final class HintPump: NSObject, URLSessionDataDelegate, @unchecked Sendable {
    // Safe because every field is read and written only while holding `condition`.
    private let condition = NSCondition()
    private var status: Int?
    private var buffer = Data()
    private var finished = false
    private var failure: URLError.Code?

    func urlSession(
        _ session: URLSession, dataTask: URLSessionDataTask, didReceive response: URLResponse,
        completionHandler: @escaping @Sendable (URLSession.ResponseDisposition) -> Void
    ) {
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        condition.lock()
        status = code
        condition.broadcast()
        condition.unlock()
        // Only a 200 is a stream; anything else is reported by status and the body is dropped.
        completionHandler(code == 200 ? .allow : .cancel)
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        condition.lock()
        buffer.append(data)
        condition.broadcast()
        condition.unlock()
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: (any Error)?) {
        condition.lock()
        finished = true
        failure = (error as? URLError)?.code ?? (error == nil ? nil : .unknown)
        condition.broadcast()
        condition.unlock()
    }

    func urlSession(
        _ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
        newRequest request: URLRequest, completionHandler: @escaping @Sendable (URLRequest?) -> Void
    ) {
        completionHandler(nil)
    }

    /// Waits for the status line.
    func awaitResponse(idleTimeout: TimeInterval, cancel: RustSyncCancellation) throws(RustSyncStreamFailure) {
        let deadline = Date().addingTimeInterval(idleTimeout)
        condition.lock()
        defer { condition.unlock() }
        while status == nil {
            if cancel.isCancelled { throw .cancelled }
            if finished { throw Self.failure(failure) }
            if Date() >= deadline { throw .timeout }
            _ = condition.wait(until: min(deadline, Date().addingTimeInterval(0.05)))
        }
        if let status, status != 200 { throw .status(status) }
    }

    /// Up to `maxLength` bytes; empty when the server closed the stream.
    func read(
        maxLength: Int, idleTimeout: TimeInterval, cancel: RustSyncCancellation
    ) throws(RustSyncStreamFailure) -> Data {
        let deadline = Date().addingTimeInterval(idleTimeout)
        condition.lock()
        defer { condition.unlock() }
        while buffer.isEmpty {
            if cancel.isCancelled { throw .cancelled }
            if finished {
                if let failure { throw Self.failure(failure) }
                return Data()
            }
            if Date() >= deadline { throw .timeout }
            _ = condition.wait(until: min(deadline, Date().addingTimeInterval(0.05)))
        }
        let chunk = buffer.prefix(maxLength)
        buffer.removeFirst(chunk.count)
        return Data(chunk)
    }

    private static func failure(_ code: URLError.Code?) -> RustSyncStreamFailure {
        switch code {
        case .some(.timedOut): .timeout
        case .some(.cancelled): .cancelled
        default: .connection
        }
    }
}

/// An open stream. Letting go of it (the core drops the reader when the stream ends) cancels the task.
final class HintStreamReader: RustSyncHintReader {
    private let pump: HintPump
    private let session: URLSession
    private let task: URLSessionDataTask
    private let idleTimeout: TimeInterval

    init(pump: HintPump, session: URLSession, task: URLSessionDataTask, idleTimeout: TimeInterval) {
        self.pump = pump
        self.session = session
        self.task = task
        self.idleTimeout = idleTimeout
    }

    func read(maxLength: Int, cancel: RustSyncCancellation) throws(RustSyncStreamFailure) -> Data {
        try pump.read(maxLength: maxLength, idleTimeout: idleTimeout, cancel: cancel)
    }

    func close() {
        task.cancel()
        session.invalidateAndCancel()
    }

    deinit { close() }
}
