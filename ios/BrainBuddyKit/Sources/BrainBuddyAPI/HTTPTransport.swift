import Foundation

#if canImport(FoundationNetworking)
    import FoundationNetworking
#endif

public enum HTTPMethod: String, Hashable, Sendable {
    case get = "GET"
    case post = "POST"
    case patch = "PATCH"
    case delete = "DELETE"
}

/// One HTTP request as plain values, so transports are trivial to fake.
public struct HTTPRequest: Hashable, Sendable {
    public var method: HTTPMethod
    public var url: URL
    public var headers: [String: String]
    public var body: Data?

    public init(method: HTTPMethod, url: URL, headers: [String: String] = [:], body: Data? = nil) {
        self.method = method
        self.url = url
        self.headers = headers
        self.body = body
    }

    /// Case-insensitive header lookup.
    public func header(_ name: String) -> String? { headers.caseInsensitiveValue(for: name) }
}

/// One HTTP response as plain values. Several `Set-Cookie` headers may arrive
/// joined into one comma-separated value (as `HTTPURLResponse` reports them).
public struct HTTPResponse: Hashable, Sendable {
    public var statusCode: Int
    public var headers: [String: String]
    public var body: Data

    public init(statusCode: Int, headers: [String: String] = [:], body: Data = Data()) {
        self.statusCode = statusCode
        self.headers = headers
        self.body = body
    }

    /// Case-insensitive header lookup.
    public func header(_ name: String) -> String? { headers.caseInsensitiveValue(for: name) }
}

/// Sends one request. Implementations throw `TransportError` when no HTTP
/// response was received; any HTTP status (including 4xx/5xx) is a response.
public protocol HTTPTransport: Sendable {
    func send(_ request: HTTPRequest) async throws -> HTTPResponse
}

/// No HTTP response was received.
public struct TransportError: Error, Hashable, Sendable, CustomStringConvertible {
    public var description: String
    /// False only when the request provably never left the device (no
    /// connection, DNS or TLS failure). A timeout or dropped connection may
    /// have delivered the request, so its outcome is unknown.
    public var requestMayHaveBeenSent: Bool
    public var isCancellation: Bool

    public init(description: String, requestMayHaveBeenSent: Bool, isCancellation: Bool = false) {
        self.description = description
        self.requestMayHaveBeenSent = requestMayHaveBeenSent
        self.isCancellation = isCancellation
    }
}

/// `URLSession` transport: ephemeral configuration, no cookie jar and no
/// cache (the client sends the session cookie itself), 30 s timeout.
public final class URLSessionTransport: HTTPTransport, @unchecked Sendable {
    // `URLSession` is thread-safe; it is only `@unchecked` because
    // swift-corelibs-foundation does not mark it `Sendable`.
    private let session: URLSession
    private let timeout: TimeInterval

    public init(timeout: TimeInterval = 30) {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpShouldSetCookies = false
        configuration.httpCookieStorage = nil
        configuration.httpCookieAcceptPolicy = .never
        configuration.urlCache = nil
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.timeoutIntervalForRequest = timeout
        self.session = URLSession(configuration: configuration)
        self.timeout = timeout
    }

    deinit { session.finishTasksAndInvalidate() }

    public func send(_ request: HTTPRequest) async throws -> HTTPResponse {
        var urlRequest = URLRequest(
            url: request.url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: timeout
        )
        urlRequest.httpMethod = request.method.rawValue
        urlRequest.httpShouldHandleCookies = false
        for (name, value) in request.headers { urlRequest.setValue(value, forHTTPHeaderField: name) }
        urlRequest.httpBody = request.body

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: urlRequest)
        } catch let error as URLError {
            throw Self.transportError(for: error)
        } catch is CancellationError {
            throw TransportError(
                description: "The request was cancelled.", requestMayHaveBeenSent: true, isCancellation: true
            )
        } catch {
            throw TransportError(description: String(describing: error), requestMayHaveBeenSent: true)
        }
        guard let http = response as? HTTPURLResponse else {
            throw TransportError(
                description: "The server did not return an HTTP response.", requestMayHaveBeenSent: true
            )
        }
        var headers: [String: String] = [:]
        for (key, value) in http.allHeaderFields {
            guard let name = key as? String else { continue }
            let text = value as? String ?? String(describing: value)
            if let existing = headers[name] { headers[name] = existing + ", " + text } else { headers[name] = text }
        }
        return HTTPResponse(statusCode: http.statusCode, headers: headers, body: data)
    }

    static func transportError(for error: URLError) -> TransportError {
        let neverSent: Set<URLError.Code> = [
            .badURL, .unsupportedURL, .cannotFindHost, .dnsLookupFailed, .cannotConnectToHost,
            .notConnectedToInternet, .internationalRoamingOff, .callIsActive, .dataNotAllowed,
            .secureConnectionFailed, .serverCertificateHasBadDate, .serverCertificateUntrusted,
            .serverCertificateHasUnknownRoot, .serverCertificateNotYetValid, .clientCertificateRejected,
            .clientCertificateRequired, .appTransportSecurityRequiresSecureConnection,
        ]
        return TransportError(
            description: error.localizedDescription,
            requestMayHaveBeenSent: !neverSent.contains(error.code),
            isCancellation: error.code == .cancelled
        )
    }
}

extension Dictionary where Key == String, Value == String {
    func caseInsensitiveValue(for name: String) -> String? {
        if let exact = self[name] { return exact }
        let lowered = name.lowercased()
        return first { $0.key.lowercased() == lowered }?.value
    }
}
