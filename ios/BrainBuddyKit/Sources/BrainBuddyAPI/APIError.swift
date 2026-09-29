import Foundation

/// Every failure `BrainBuddyAPIClient` reports. `kind` is what the sync engine
/// switches on; `message` is the server's own words (or a calm fallback) and
/// `referenceID` is what the user quotes to support.
///
/// The server has no machine-readable error codes, so 409s are told apart by
/// their `detail` and message text (`backend/app/modules/tasks/service.py`):
///
/// | Server raises | `kind` |
/// |---|---|
/// | `"<R> '<id>' has newer changes; reload before saving."`, detail `{resource, id}` | `.staleRevision` |
/// | idempotency replay mismatch, detail `{"resource": "Idempotency-Key", …}` | `.idempotencyConflict` |
/// | `"Project '<name>' already exists."` / `"Tag '<name>' already exists."` | `.duplicateName` |
/// | anything else (for example signup's "An account with that email already exists.") | `.rejected` |
public struct APIError: Error, Hashable, Sendable, CustomStringConvertible, LocalizedError {
    public enum Kind: Hashable, Sendable {
        /// No HTTP response: offline, DNS, TLS, timeout, dropped connection;
        /// also HTTP 408. See `requestMayHaveBeenSent`.
        case network(String)
        /// The calling task was cancelled while the request was in flight.
        case cancelled
        /// The session token could not be read or written on this device
        /// (for example the Keychain before first unlock). Nothing was sent.
        case tokenStorage(String)
        /// 401: no session, or it expired or was revoked. On `login` this is
        /// wrong credentials ("Invalid email or password.").
        case unauthorized
        /// 429.
        case rateLimited
        /// 409: `expected_revision` did not match. `resource` is the server's
        /// name: `Task`, `Project`, `Tag`, `Subtask` or `Comment`.
        case staleRevision(resource: String, id: String)
        /// 409: this `Idempotency-Key` was already used for a different request.
        case idempotencyConflict
        /// 409: an active project or tag with this normalized name exists.
        /// `resource` is `Project` or `Tag`; `name` is the name the server compared.
        case duplicateName(resource: String, name: String)
        /// 404. `resource`/`id` come from the detail (`Task`, `Project`, `Tag`,
        /// `Task subtask`, `Task comment`) and may name a *referenced* record,
        /// for example the project of a task being created. Nil when the 404
        /// has no structured detail (an unknown route or a proxy).
        case notFound(resource: String?, id: String?)
        /// 400 (domain rule, missing `Idempotency-Key`), 422 (request
        /// validation; `detail` holds pydantic's error list), and other 4xx.
        case rejected
        /// 5xx, including 503 "Storage is temporarily unavailable; please retry."
        case server
        /// A 2xx response (or the error body) could not be decoded.
        case decoding(String)
    }

    public var kind: Kind
    public var message: String
    /// The server's `reference_id`, else its `X-Correlation-ID` header, else
    /// (when no response arrived) the correlation id this client sent.
    public var referenceID: String?
    /// Nil when no HTTP response arrived.
    public var statusCode: Int?
    /// The envelope's structured `detail`, when present.
    public var detail: JSONValue?
    /// Seconds from a `Retry-After` header.
    public var retryAfter: TimeInterval?
    /// False only when the request provably never reached the server.
    public var requestMayHaveBeenSent: Bool

    public init(
        kind: Kind, message: String, referenceID: String? = nil, statusCode: Int? = nil,
        detail: JSONValue? = nil, retryAfter: TimeInterval? = nil, requestMayHaveBeenSent: Bool = true
    ) {
        self.kind = kind
        self.message = message
        self.referenceID = referenceID
        self.statusCode = statusCode
        self.detail = detail
        self.retryAfter = retryAfter
        self.requestMayHaveBeenSent = requestMayHaveBeenSent
    }

    /// Worth retrying later with the *same* `Idempotency-Key`: network
    /// failures, cancellation, 408, 429, 5xx/503, and local token storage.
    public var isRetryable: Bool {
        switch kind {
        case .network, .cancelled, .tokenStorage, .rateLimited, .server: true
        case .unauthorized, .staleRevision, .idempotencyConflict, .duplicateName, .notFound, .rejected, .decoding: false
        }
    }

    /// The server may have applied the request even though no usable answer
    /// came back, so the operation must keep its `Idempotency-Key` (a retry
    /// with the same key replays instead of applying twice). True for network
    /// failures after the request may have left, cancellation in flight, 408,
    /// 429, 5xx, and a 2xx whose body could not be decoded.
    public var isUncertainOutcome: Bool {
        switch kind {
        case .network, .cancelled: requestMayHaveBeenSent
        case .rateLimited, .server: true
        case .decoding: statusCode.map { (200..<300).contains($0) } ?? false
        case .tokenStorage, .unauthorized, .staleRevision, .idempotencyConflict, .duplicateName, .notFound, .rejected:
            false
        }
    }

    public var description: String {
        var text = "APIError(\(kind)"
        if let statusCode { text += ", HTTP \(statusCode)" }
        text += "): \(message)"
        if let referenceID { text += " [ref \(referenceID)]" }
        return text
    }

    public var errorDescription: String? {
        guard let referenceID, !referenceID.isEmpty else { return message }
        return "\(message) Reference ID: \(referenceID)."
    }
}

extension APIError {
    /// The error envelope every backend error uses: `{message, detail, reference_id}`.
    struct Envelope: Decodable {
        var message: String?
        var detail: JSONValue?
        var referenceID: String?

        enum CodingKeys: String, CodingKey {
            case message, detail
            case referenceID = "reference_id"
        }
    }

    /// Maps a non-2xx response. `sentCorrelationID` is the fallback reference.
    static func from(response: HTTPResponse, sentCorrelationID: String?) -> APIError {
        let status = response.statusCode
        let envelope = try? JSONDecoder().decode(Envelope.self, from: response.body)
        let detail = envelope?.detail.flatMap { $0 == .null ? nil : $0 }
        let referenceID =
            nonEmpty(envelope?.referenceID) ?? nonEmpty(response.header("X-Correlation-ID")) ?? sentCorrelationID
        let serverMessage = nonEmpty(envelope?.message)
        let retryAfter = response.header("Retry-After").flatMap {
            TimeInterval($0.trimmingCharacters(in: .whitespaces))
        }

        func make(_ kind: Kind, _ fallback: String) -> APIError {
            APIError(
                kind: kind, message: serverMessage ?? fallback, referenceID: referenceID, statusCode: status,
                detail: detail, retryAfter: retryAfter
            )
        }

        switch status {
        case 401:
            return make(.unauthorized, "Sign in again to continue.")
        case 404:
            return make(
                .notFound(resource: detail?["resource"]?.stringValue, id: detail?["id"]?.stringValue),
                "This item no longer exists."
            )
        case 408:
            return make(.network("HTTP 408"), "The request timed out.")
        case 409:
            return make(conflictKind(message: serverMessage, detail: detail), "This change conflicts with the server.")
        case 429:
            return make(.rateLimited, "Too many requests. Try again in a few minutes.")
        case 500...599:
            return make(.server, "The server had a problem (HTTP \(status)). Try again later.")
        default:
            return make(.rejected, "The server rejected the request (HTTP \(status)).")
        }
    }

    static func conflictKind(message: String?, detail: JSONValue?) -> Kind {
        let resource = detail?["resource"]?.stringValue
        let identifier = detail?["id"]?.stringValue
        let reason = detail?["reason"]?.stringValue
        let text = message ?? ""

        if resource == "Idempotency-Key" || reason?.hasPrefix("idempotency_") == true {
            return .idempotencyConflict
        }
        if text.hasSuffix("has newer changes; reload before saving.") || reason == "stale_revision" {
            return .staleRevision(resource: resource ?? "", id: identifier ?? detail?["tree_id"]?.stringValue ?? "")
        }
        if let resource, resource == "Project" || resource == "Tag", let identifier,
            text.hasSuffix(" already exists.")
        {
            return .duplicateName(resource: resource, name: identifier)
        }
        return .rejected
    }

    static func transport(_ error: TransportError, sentCorrelationID: String?) -> APIError {
        APIError(
            kind: error.isCancellation ? .cancelled : .network(error.description),
            message: error.isCancellation
                ? "The request was cancelled."
                : "Can't reach Brain Buddy. Check your connection and try again.",
            referenceID: sentCorrelationID,
            requestMayHaveBeenSent: error.requestMayHaveBeenSent
        )
    }

    static func tokenStorage(_ error: any Error) -> APIError {
        APIError(
            kind: .tokenStorage(String(describing: error)),
            message: "Brain Buddy couldn't read your sign-in from this device. Unlock the device and try again.",
            requestMayHaveBeenSent: false
        )
    }

    static func decoding(_ error: any Error, response: HTTPResponse, sentCorrelationID: String?) -> APIError {
        APIError(
            kind: .decoding(String(describing: error)),
            message: "Brain Buddy received a response it couldn't read.",
            referenceID: nonEmpty(response.header("X-Correlation-ID")) ?? sentCorrelationID,
            statusCode: response.statusCode
        )
    }

    private static func nonEmpty(_ value: String?) -> String? {
        guard let value, !value.isEmpty else { return nil }
        return value
    }
}
