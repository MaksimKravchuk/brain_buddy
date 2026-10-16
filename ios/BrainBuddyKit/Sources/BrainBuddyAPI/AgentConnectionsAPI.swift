import Foundation

// External agent connections (spec 030): `backend/app/api/agents.py`, `backend/app/schemas/agents.py`.
// A saved credential is never a response field; request bodies that carry one or a password are
// encode-only and print nothing of them. Enums read an unknown value as `.unknown`.

/// How BrainBuddy presents a credential to the agent.
public enum AgentAuthScheme: Hashable, Sendable, Codable {
    case bearer, apiKey
    case unknown(String)

    public var wireValue: String {
        switch self {
        case .bearer: "bearer"
        case .apiKey: "api_key"
        case .unknown(let value): value
        }
    }

    public init(wireValue: String) {
        self = ["bearer": Self.bearer, "api_key": .apiKey][wireValue] ?? .unknown(wireValue)
    }

    public init(from decoder: any Decoder) throws {
        self.init(wireValue: try decoder.singleValueContainer().decode(String.self))
    }

    public func encode(to encoder: any Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(wireValue)
    }
}

public enum AgentConnectionStatus: Hashable, Sendable, Decodable {
    case untested, ready, invalidCredentials, unreachable, unsupported, disconnected
    case unknown(String)

    public init(from decoder: any Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        let known: [String: Self] = [
            "untested": .untested, "ready": .ready, "invalid_credentials": .invalidCredentials,
            "unreachable": .unreachable, "unsupported": .unsupported, "disconnected": .disconnected,
        ]
        self = known[raw] ?? .unknown(raw)
    }
}

public enum AgentGuaranteeTier: Hashable, Sendable, Decodable {
    case guaranteed, bestEffort
    case unknown(String)

    public init(from decoder: any Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = ["guaranteed": Self.guaranteed, "best_effort": .bestEffort][raw] ?? .unknown(raw)
    }
}

/// What the agent's card declared (the agent's statements, not BrainBuddy's).
public struct AgentCapabilitiesDTO: Hashable, Sendable, Decodable {
    public let streaming: Bool
    public let pushNotifications: Bool

    enum CodingKeys: String, CodingKey {
        case streaming
        case pushNotifications = "push_notifications"
    }

    public init(streaming: Bool = false, pushNotifications: Bool = false) {
        self.streaming = streaming
        self.pushNotifications = pushNotifications
    }
}

/// The controls BrainBuddy offers on this connection's runs.
public struct AgentControlsDTO: Hashable, Sendable, Decodable {
    public let reply: Bool
    public let cancel: Bool

    public init(reply: Bool = false, cancel: Bool = false) {
        self.reply = reply
        self.cancel = cancel
    }
}

/// The bounded discovery result. Every string is untrusted agent text: show it as plain text.
public struct AgentCardDTO: Hashable, Sendable, Decodable {
    public struct Skill: Hashable, Sendable, Decodable {
        public let id: String?
        public let name: String?
        public let description: String?
    }

    public let name: String?
    public let version: String?
    public let description: String?
    public let protocolVersion: String?
    public let interfaceURL: String?
    public let skills: [Skill]

    enum CodingKeys: String, CodingKey {
        case name, version, description, skills
        case protocolVersion = "protocol_version"
        case interfaceURL = "interface_url"
    }
}

/// `AgentConnectionResponse`. The description is redacted: it would hold the agent's name and address.
public struct AgentConnectionDTO: Hashable, Sendable, Decodable, CustomStringConvertible {
    public let id: String
    public let name: String
    public let agentAddress: String
    public let authScheme: AgentAuthScheme
    public let authHeaderName: String?
    public let status: AgentConnectionStatus
    /// No contact within `staleAfterSeconds`.
    public let stale: Bool
    public let staleAfterSeconds: Int
    public let readyForHandoff: Bool
    public let capabilities: AgentCapabilitiesDTO
    public let controlsOffered: AgentControlsDTO
    public let card: AgentCardDTO?
    public let guaranteeTier: AgentGuaranteeTier?
    public let tierDisclosure: String?
    public let cancellationDisclosure: String?
    public let agentChanged: Bool
    public let lastTestErrorCode: String?
    public let lastContactAt: Date?
    public let lastTestedAt: Date?
    public let createdAt: Date
    public let revision: Int

    public var description: String { "Agent connection (redacted)" }

    enum CodingKeys: String, CodingKey {
        case id, name, status, stale, capabilities, card, revision
        case agentAddress = "agent_address"
        case authScheme = "auth_scheme"
        case authHeaderName = "auth_header_name"
        case staleAfterSeconds = "stale_after_seconds"
        case readyForHandoff = "ready_for_handoff"
        case controlsOffered = "controls_offered"
        case guaranteeTier = "guarantee_tier"
        case tierDisclosure = "tier_disclosure"
        case cancellationDisclosure = "cancellation_disclosure"
        case agentChanged = "agent_changed"
        case lastTestErrorCode = "last_test_error_code"
        case lastContactAt = "last_contact_at"
        case lastTestedAt = "last_tested_at"
        case createdAt = "created_at"
    }
}

// MARK: - Request bodies (encode-only, redacted)

/// A body that may carry a credential or password: it prints, reflects and dumps as nothing.
protocol RedactedRequestBody: Encodable, CustomStringConvertible, CustomDebugStringConvertible, CustomReflectable {}

extension RedactedRequestBody {
    var description: String { "\(Self.self) (redacted)" }
    var debugDescription: String { description }
    var customMirror: Mirror { Mirror(self, children: []) }
}

struct AgentConnectionCreateBody: RedactedRequestBody {
    let name: String
    let agentAddress: String
    let authScheme: AgentAuthScheme
    let credential: String
    let currentPassword: String

    enum CodingKeys: String, CodingKey {
        case name, credential
        case agentAddress = "agent_address"
        case authScheme = "auth_scheme"
        case currentPassword = "current_password"
    }
}

/// `current_password` is sent only when the caller gives one (an address or scheme change).
struct AgentConnectionUpdateBody: RedactedRequestBody {
    let name: String?
    let agentAddress: String?
    let authScheme: AgentAuthScheme?
    let currentPassword: String?
    let expectedRevision: Int

    enum CodingKeys: String, CodingKey {
        case name
        case agentAddress = "agent_address"
        case authScheme = "auth_scheme"
        case currentPassword = "current_password"
        case expectedRevision = "expected_revision"
    }
}

struct AgentCredentialBody: RedactedRequestBody {
    let credential: String
    let currentPassword: String
    let expectedRevision: Int

    enum CodingKeys: String, CodingKey {
        case credential
        case currentPassword = "current_password"
        case expectedRevision = "expected_revision"
    }
}

struct AgentDisconnectBody: RedactedRequestBody {
    let currentPassword: String
    let expectedRevision: Int

    enum CodingKeys: String, CodingKey {
        case currentPassword = "current_password"
        case expectedRevision = "expected_revision"
    }
}

// MARK: - Calls

extension BrainBuddyAPIClient {
    /// `GET /agent-connections`, disconnected ones included. A 404 with the relay's message
    /// (`agentFailure == .relayUnavailable`) means the flag is off for this account.
    public func agentConnections() async throws(APIError) -> [AgentConnectionDTO] {
        try await get(["agent-connections"])
    }

    public func agentConnection(id: String) async throws(APIError) -> AgentConnectionDTO {
        try await get(["agent-connections", id])
    }

    /// `POST /agent-connections` → 201. A wrong `currentPassword` is 403 (`.wrongPassword`).
    public func createAgentConnection(
        name: String, address: String, scheme: AgentAuthScheme, credential: String, currentPassword: String,
        idempotencyKey: UUID
    ) async throws(APIError) -> AgentConnectionDTO {
        let body = AgentConnectionCreateBody(
            name: name, agentAddress: address, authScheme: scheme, credential: credential,
            currentPassword: currentPassword)
        return try await mutate(.post, ["agent-connections"], body, key: idempotencyKey)
    }

    /// `PUT /agent-connections/{id}`. Nil fields are omitted; `currentPassword` is needed only when
    /// the address or scheme changes.
    public func updateAgentConnection(
        id: String, name: String?, address: String?, scheme: AgentAuthScheme?, currentPassword: String?,
        expectedRevision: Int, idempotencyKey: UUID
    ) async throws(APIError) -> AgentConnectionDTO {
        let body = AgentConnectionUpdateBody(
            name: name, agentAddress: address, authScheme: scheme, currentPassword: currentPassword,
            expectedRevision: expectedRevision)
        return try await mutate(.put, ["agent-connections", id], body, key: idempotencyKey)
    }

    /// `POST /agent-connections/{id}/test` (no body) → the connection with its new status.
    public func testAgentConnection(id: String, idempotencyKey: UUID) async throws(APIError) -> AgentConnectionDTO {
        let endpoint = Endpoint(.post, ["agent-connections", id, "test"], idempotencyKey: idempotencyKey)
        return try decode(try await exchange(endpoint))
    }

    public func replaceAgentCredential(
        id: String, credential: String, currentPassword: String, expectedRevision: Int, idempotencyKey: UUID
    ) async throws(APIError) -> AgentConnectionDTO {
        let body = AgentCredentialBody(
            credential: credential, currentPassword: currentPassword, expectedRevision: expectedRevision)
        return try await mutate(.post, ["agent-connections", id, "credential"], body, key: idempotencyKey)
    }

    /// `POST /agent-connections/{id}/disconnect`. Works with the flag off.
    public func disconnectAgentConnection(
        id: String, currentPassword: String, expectedRevision: Int, idempotencyKey: UUID
    ) async throws(APIError) -> AgentConnectionDTO {
        let body = AgentDisconnectBody(currentPassword: currentPassword, expectedRevision: expectedRevision)
        return try await mutate(.post, ["agent-connections", id, "disconnect"], body, key: idempotencyKey)
    }
}
