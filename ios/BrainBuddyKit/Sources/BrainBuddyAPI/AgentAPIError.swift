import Foundation

/// How the external agent relay's failures read (spec 030). `APIError.from` is unchanged: a 403 or
/// 404 means something else on every other route, so only agent calls ask `agentFailure`.
public enum AgentFailure: Hashable, Sendable {
    /// 404 with the relay's own message: the flag is off. Refresh availability.
    case relayUnavailable
    /// 403 on a password-bearing call (`ReauthFailedError`): keep the form, clear the password.
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
