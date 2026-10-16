import Foundation

/// How the external agent relay's failures read (spec 030, FR-002, FR-018, FR-034).
///
/// `APIError.from` is not changed: a 403 or 404 means something else on every other route, so
/// only the agent calls ask `agentFailure`. The relay answers 403 only when a password-bearing
/// call's `current_password` is wrong (`ReauthFailedError`), and 404 "External agent relay is not
/// available." when the `external_agent_relay` flag is off for the account.
public enum AgentFailure: Hashable, Sendable {
    /// 404 with the relay's own message: the flag is off. Refresh availability.
    case relayUnavailable
    /// 403 on a password-bearing call: the Current password is wrong. Keep the form, clear the field.
    case wrongPassword
    /// 409: `expected_revision` is behind. Read again, then let the person decide.
    case staleRevision
    /// 429, including the sensitive-action limiter. Never retried automatically.
    case rateLimited
    /// No HTTP response arrived.
    case offline
    /// Anything else: show `APIError.message` and its reference.
    case other
}

extension APIError {
    /// The message of the relay's flag-off 404 (`require_external_agent_relay_enabled`).
    public static let agentRelayUnavailableMessage = "External agent relay is not available."

    static let agentChangedElsewhereSuffix = " changed elsewhere; reload and try again."

    /// The relay-specific reading of this failure. Only meaningful for an agent call.
    public var agentFailure: AgentFailure {
        switch kind {
        case .notFound where statusCode == 404 && message == Self.agentRelayUnavailableMessage:
            .relayUnavailable
        case .rejected where statusCode == 403:
            .wrongPassword
        case .staleRevision:
            .staleRevision
        case .rejected where statusCode == 409 && message.hasSuffix(Self.agentChangedElsewhereSuffix):
            // The relay words its own stale `expected_revision` ("This agent|run changed elsewhere; …").
            .staleRevision
        case .rateLimited:
            .rateLimited
        case .network:
            .offline
        default:
            .other
        }
    }
}
