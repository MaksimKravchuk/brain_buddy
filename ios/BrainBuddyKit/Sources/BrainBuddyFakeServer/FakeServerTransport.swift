import BrainBuddyAPI
import Foundation
import Synchronization

/// One device's connection to a `FakeBrainBuddyServer`: an `HTTPTransport`
/// that answers from the shared server, logs every request, and fails on
/// demand the ways a real network and server fail.
public final class FakeServerTransport: HTTPTransport {
    public enum Fault: Hashable, Sendable {
        /// No connection: the request never left the device and nothing was applied.
        case offline
        /// A timeout before the server saw the request: nothing was applied, but
        /// the client cannot tell (`requestMayHaveBeenSent`).
        case timeout
        /// The server applied the request, then the response was lost (an
        /// uncertain outcome the client must retry with the same key).
        case dropResponse
        /// An HTTP error with the backend's envelope; nothing was applied.
        /// 401 does not end the session on the server (the client drops its token).
        case status(Int)
    }

    /// Matches requests a fault applies to.
    public typealias Matcher = @Sendable (HTTPRequest) -> Bool

    private struct PendingFault {
        var fault: Fault
        var remaining: Int
        var matches: Matcher
    }

    /// One request and what the device got back.
    public struct Exchange: Sendable {
        public var request: HTTPRequest
        /// The response the device received; nil when none arrived.
        public var response: HTTPResponse?
        /// The injected fault, if any.
        public var fault: Fault?
        /// The server's answer to a request whose response was then dropped.
        public var droppedResponse: HTTPResponse?

        public var statusCode: Int? { response?.statusCode }

        /// The error envelope's `message`, for a non-2xx response.
        public var errorMessage: String? {
            guard let response, !(200..<300).contains(response.statusCode),
                let envelope = try? JSONDecoder().decode(JSONValue.self, from: response.body)
            else { return nil }
            return envelope["message"]?.stringValue
        }
    }

    private struct State {
        var faults: [PendingFault] = []
        var exchanges: [Exchange] = []
    }

    public let server: FakeBrainBuddyServer
    private let state = Mutex(State())

    init(server: FakeBrainBuddyServer) { self.server = server }

    /// Fails the next `times` requests that `matching` accepts with `fault`.
    /// Faults are consumed in the order they were injected.
    public func inject(_ fault: Fault, times: Int = 1, matching: @escaping Matcher = { _ in true }) {
        state.withLock { $0.faults.append(PendingFault(fault: fault, remaining: times, matches: matching)) }
    }

    /// Forgets faults not yet consumed.
    public func clearFaults() { state.withLock { $0.faults.removeAll() } }

    /// Every request this device sent, faulted or not, oldest first.
    public var requests: [HTTPRequest] { exchanges.map(\.request) }

    /// Every request with its outcome, oldest first.
    public var exchanges: [Exchange] { state.withLock { $0.exchanges } }

    public func clearLog() { state.withLock { $0.exchanges.removeAll() } }

    /// Requests that change data (POST, PATCH, DELETE) outside `/auth`.
    public static let isMutation: Matcher = { request in
        request.method != .get && !request.url.path.contains("/auth/")
    }

    /// Requests whose path (after `/api`) starts with `prefix`, for example `"tasks"`.
    public static func path(_ prefix: String, method: HTTPMethod? = nil) -> Matcher {
        { request in
            let path = ServerState.segments(of: request.url).joined(separator: "/")
            return path.hasPrefix(prefix) && (method == nil || request.method == method)
        }
    }

    public func send(_ request: HTTPRequest) async throws -> HTTPResponse {
        let fault = state.withLock { state -> Fault? in
            guard let index = state.faults.firstIndex(where: { $0.matches(request) }) else { return nil }
            let fault = state.faults[index].fault
            state.faults[index].remaining -= 1
            if state.faults[index].remaining <= 0 { state.faults.remove(at: index) }
            return fault
        }
        var exchange = Exchange(request: request, fault: fault)
        defer { state.withLock { [exchange] in $0.exchanges.append(exchange) } }
        switch fault {
        case nil:
            let response = server.respond(to: request)
            exchange.response = response
            return response
        case .offline?:
            throw TransportError(description: "The Internet connection appears to be offline.", requestMayHaveBeenSent: false)
        case .timeout?:
            throw TransportError(description: "The request timed out.", requestMayHaveBeenSent: true)
        case .dropResponse?:
            exchange.droppedResponse = server.respond(to: request)
            throw TransportError(description: "The network connection was lost.", requestMayHaveBeenSent: true)
        case .status(let code)?:
            let response = Self.errorResponse(code, request: request)
            exchange.response = response
            return response
        }
    }

    static func errorResponse(_ status: Int, request: HTTPRequest) -> HTTPResponse {
        let message: String =
            switch status {
            case 401: "Authentication required."
            case 422: "Request validation failed."
            case 429: "Too many requests. Try again in a few minutes."
            case 503: "Storage is temporarily unavailable; please retry."
            default: "Internal Server Error"
            }
        let reference = request.header("X-Correlation-ID") ?? "fault"
        let envelope: JSONValue = .object([
            "message": .string(message), "detail": .null, "reference_id": .string(reference),
        ])
        let body = (try? JSONEncoder().encode(envelope)) ?? Data()
        var headers = ["content-type": "application/json", "x-correlation-id": reference]
        if status == 429 || status == 503 { headers["retry-after"] = "1" }
        return HTTPResponse(statusCode: status, headers: headers, body: body)
    }
}
