import Foundation

#if canImport(FoundationNetworking)
    import FoundationNetworking
#endif

/// One request the stub saw, as plain values (the body is read from the request's stream).
public struct StubRequest: Sendable, Equatable {
    public let method: String
    public let url: URL
    public let headers: [String: String]
    public let body: Data

    public func header(_ name: String) -> String? {
        headers.first { $0.key.lowercased() == name.lowercased() }?.value
    }
}

/// What the stub answers a request with.
public enum StubReply: Sendable {
    case response(status: Int, headers: [String: String] = [:], body: Data = Data())
    /// Headers now, then whatever the test feeds the `StubStream`.
    case stream(status: Int, headers: [String: String] = [:], StubStream)
    /// Never answers; the request ends only when the client gives up.
    case hang
    case fail(URLError.Code)
}

/// The body of a streaming reply, fed by the test.
public final class StubStream: @unchecked Sendable {
    // Safe because the protocol instance is only touched while holding `lock`.
    private let lock = NSLock()
    private var target: (any StubDelivery)?
    private var queued: [Event] = []

    private enum Event {
        case data(Data)
        case finish
        case fail(URLError.Code)
    }

    public init() {}

    public func send(_ data: Data) { deliver(.data(data)) }
    public func send(_ text: String) { send(Data(text.utf8)) }
    /// The server closes the stream cleanly.
    public func finish() { deliver(.finish) }
    public func fail(_ code: URLError.Code) { deliver(.fail(code)) }

    fileprivate func attach(_ target: any StubDelivery) {
        lock.lock()
        self.target = target
        let pending = queued
        queued = []
        lock.unlock()
        pending.forEach { play($0, on: target) }
    }

    private func deliver(_ event: Event) {
        lock.lock()
        guard let target else {
            queued.append(event)
            lock.unlock()
            return
        }
        lock.unlock()
        play(event, on: target)
    }

    private func play(_ event: Event, on target: any StubDelivery) {
        switch event {
        case .data(let data): target.deliver(data)
        case .finish: target.finish()
        case .fail(let code): target.fail(code)
        }
    }
}

fileprivate protocol StubDelivery: Sendable {
    func deliver(_ data: Data)
    func finish()
    func fail(_ code: URLError.Code)
}

/// A stub HTTP server reached through `URLProtocol`, one per test: it owns a unique host, so tests
/// that run in parallel never see each other's requests. Hand `sessionConfiguration` to the code
/// under test.
public final class StubServer: Sendable {
    public typealias Responder = @Sendable (StubRequest) -> StubReply

    struct State {
        var requests: [StubRequest] = []
        var stopped = 0
        var responder: Responder = { _ in .response(status: 404) }
    }

    public let host = "stub-\(UUID().uuidString.lowercased()).test"
    private let condition = NSCondition()
    // Guarded by `condition`.
    nonisolated(unsafe) private var state = State()

    public init() { StubRegistry.register(self, host: host) }

    deinit { StubRegistry.unregister(host: host) }

    /// `http://stub-….test`: the origin the code under test is pointed at.
    public var origin: URL { URL(string: "http://\(host)")! }

    /// The `/api` base the app's server address has.
    public var serverURL: URL { URL(string: "http://\(host)/api")! }

    /// The same server as an `https` address, which sign-in accepts for any host.
    public var secureServerURL: URL { URL(string: "https://\(host)/api")! }

    public var sessionConfiguration: URLSessionConfiguration {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StubURLProtocol.self]
        configuration.httpCookieStorage = nil
        configuration.httpShouldSetCookies = false
        configuration.urlCache = nil
        return configuration
    }

    public func respond(_ responder: @escaping Responder) {
        condition.lock()
        state.responder = responder
        condition.unlock()
    }

    public var requests: [StubRequest] {
        condition.lock()
        defer { condition.unlock() }
        return state.requests
    }

    /// Requests the client abandoned (cancelled or timed out) before the stub finished answering.
    public var stopped: Int {
        condition.lock()
        defer { condition.unlock() }
        return state.stopped
    }

    /// Blocks until `predicate` holds for the stub's record, or `timeout` passes.
    @discardableResult
    public func wait(timeout: TimeInterval = 10, until predicate: @Sendable (_ requests: [StubRequest], _ stopped: Int) -> Bool)
        -> Bool
    {
        let deadline = Date().addingTimeInterval(timeout)
        condition.lock()
        defer { condition.unlock() }
        while !predicate(state.requests, state.stopped) {
            if !condition.wait(until: deadline) { return predicate(state.requests, state.stopped) }
        }
        return true
    }

    fileprivate func received(_ request: StubRequest) -> StubReply {
        condition.lock()
        state.requests.append(request)
        let responder = state.responder
        condition.broadcast()
        condition.unlock()
        return responder(request)
    }

    fileprivate func abandoned() {
        condition.lock()
        state.stopped += 1
        condition.broadcast()
        condition.unlock()
    }
}

private enum StubRegistry {
    private static let lock = NSLock()
    // Guarded by `lock`.
    nonisolated(unsafe) private static var servers: [String: Weak] = [:]

    private struct Weak { weak var server: StubServer? }

    static func register(_ server: StubServer, host: String) {
        lock.lock()
        servers[host] = Weak(server: server)
        lock.unlock()
    }

    static func unregister(host: String) {
        lock.lock()
        servers[host] = nil
        lock.unlock()
    }

    static func server(for host: String?) -> StubServer? {
        lock.lock()
        defer { lock.unlock() }
        return host.flatMap { servers[$0]?.server }
    }
}

public final class StubURLProtocol: URLProtocol, @unchecked Sendable {
    // Safe because `finished` is only touched while holding `lock`; the rest is set at creation.
    private let lock = NSLock()
    private var finished = false
    private var server: StubServer?

    public override class func canInit(with request: URLRequest) -> Bool {
        StubRegistry.server(for: request.url?.host) != nil
    }

    public override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    public override func startLoading() {
        guard let url = request.url, let server = StubRegistry.server(for: url.host) else {
            client?.urlProtocol(self, didFailWithError: URLError(.cannotFindHost))
            return
        }
        self.server = server
        let stub = StubRequest(
            method: request.httpMethod ?? "GET", url: url, headers: request.allHTTPHeaderFields ?? [:],
            body: Self.body(of: request))
        switch server.received(stub) {
        case .response(let status, let headers, let body):
            respond(url: url, status: status, headers: headers)
            if !body.isEmpty { client?.urlProtocol(self, didLoad: body) }
            end()
            client?.urlProtocolDidFinishLoading(self)
        case .stream(let status, var headers, let stream):
            // Without a content type URLSession holds the headers back until the first bytes.
            if headers.keys.allSatisfy({ $0.lowercased() != "content-type" }) {
                headers["Content-Type"] = "text/event-stream"
            }
            respond(url: url, status: status, headers: headers)
            stream.attach(Delivery(owner: self))
        case .hang:
            break
        case .fail(let code):
            end()
            client?.urlProtocol(self, didFailWithError: URLError(code))
        }
    }

    public override func stopLoading() {
        lock.lock()
        let wasOpen = !finished
        finished = true
        lock.unlock()
        if wasOpen { server?.abandoned() }
    }

    private func respond(url: URL, status: Int, headers: [String: String]) {
        let response = HTTPURLResponse(url: url, statusCode: status, httpVersion: "HTTP/1.1", headerFields: headers)!
        if (300..<400).contains(status), let location = headers["Location"], let target = URL(string: location) {
            var next = URLRequest(url: target)
            next.httpMethod = "GET"
            client?.urlProtocol(self, wasRedirectedTo: next, redirectResponse: response)
            // Like the HTTP protocol: a client that refuses the redirect gets the 3xx as the answer.
        }
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
    }

    /// True the first time: the request is over for the stub, and it is not "abandoned".
    private func end() {
        lock.lock()
        finished = true
        lock.unlock()
    }

    fileprivate func push(_ data: Data) {
        lock.lock()
        let open = !finished
        lock.unlock()
        if open { client?.urlProtocol(self, didLoad: data) }
    }

    fileprivate func close(failure: URLError.Code?) {
        lock.lock()
        let open = !finished
        finished = true
        lock.unlock()
        guard open else { return }
        if let failure { client?.urlProtocol(self, didFailWithError: URLError(failure)) }
        else { client?.urlProtocolDidFinishLoading(self) }
    }

    private static func body(of request: URLRequest) -> Data {
        if let body = request.httpBody { return body }
        guard let stream = request.httpBodyStream else { return Data() }
        stream.open()
        defer { stream.close() }
        var data = Data()
        var buffer = [UInt8](repeating: 0, count: 4096)
        while stream.hasBytesAvailable {
            let count = stream.read(&buffer, maxLength: buffer.count)
            if count <= 0 { break }
            data.append(contentsOf: buffer[..<count])
        }
        return data
    }

    private final class Delivery: StubDelivery, @unchecked Sendable {
        // The protocol instance is retained until it finishes; `push`/`close` lock internally.
        private let owner: StubURLProtocol
        init(owner: StubURLProtocol) { self.owner = owner }
        func deliver(_ data: Data) { owner.push(data) }
        func finish() { owner.close(failure: nil) }
        func fail(_ code: URLError.Code) { owner.close(failure: code) }
    }
}
