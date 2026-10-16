import Foundation

// External agent connections (spec 030, specs 007/014): `backend/app/api/agents.py` and
// `backend/app/schemas/agents.py`. Platform-neutral so the iPhone can reuse it. A saved
// credential is never a response field; request bodies that carry one are encode-only and
// print nothing of it.

/// How BrainBuddy presents a credential to the agent. An unknown scheme from a newer server reads
/// as `.unknown` and is shown verbatim.
public enum AgentAuthScheme: Hashable, Sendable, Codable {
    case bearer
    case apiKey
    case unknown(String)

    public var wireValue: String {
        switch self {
        case .bearer: "bearer"
        case .apiKey: "api_key"
        case .unknown(let value): value
        }
    }

    public init(wireValue: String) {
        switch wireValue {
        case "bearer": self = .bearer
        case "api_key": self = .apiKey
        default: self = .unknown(wireValue)
        }
    }

    public init(from decoder: any Decoder) throws {
        self.init(wireValue: try decoder.singleValueContainer().decode(String.self))
    }

    public func encode(to encoder: any Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(wireValue)
    }
}

/// `AgentConnectionStatus`. Unknown values read as `.unknown`.
public enum AgentConnectionStatus: Hashable, Sendable, Decodable {
    case untested, ready, invalidCredentials, unreachable, unsupported, disconnected
    case unknown(String)

    public init(from decoder: any Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        switch raw {
        case "untested": self = .untested
        case "ready": self = .ready
        case "invalid_credentials": self = .invalidCredentials
        case "unreachable": self = .unreachable
        case "unsupported": self = .unsupported
        case "disconnected": self = .disconnected
        default: self = .unknown(raw)
        }
    }
}

/// `AgentGuaranteeTier`. Unknown values read as `.unknown`.
public enum AgentGuaranteeTier: Hashable, Sendable, Decodable {
    case guaranteed, bestEffort
    case unknown(String)

    public init(from decoder: any Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        switch raw {
        case "guaranteed": self = .guaranteed
        case "best_effort": self = .bestEffort
        default: self = .unknown(raw)
        }
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

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        streaming = try container.decodeIfPresent(Bool.self, forKey: .streaming) ?? false
        pushNotifications = try container.decodeIfPresent(Bool.self, forKey: .pushNotifications) ?? false
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

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        reply = try container.decodeIfPresent(Bool.self, forKey: .reply) ?? false
        cancel = try container.decodeIfPresent(Bool.self, forKey: .cancel) ?? false
    }

    enum CodingKeys: String, CodingKey { case reply, cancel }
}

/// The bounded discovery result. Every string is untrusted agent text: show it as plain text.
public struct AgentCardDTO: Hashable, Sendable, Decodable {
    public struct Skill: Hashable, Sendable, Decodable {
        public let id: String?
        public let name: String?
        public let description: String?
    }

    public struct SchemeOffer: Hashable, Sendable, Decodable {
        public let name: String
        public let kind: String
        public let headerName: String?

        enum CodingKeys: String, CodingKey {
            case name, kind
            case headerName = "header_name"
        }
    }

    public let name: String?
    public let version: String?
    public let description: String?
    public let protocolVersion: String?
    public let interfaceURL: String?
    public let skills: [Skill]
    public let authSchemesOffered: [SchemeOffer]

    enum CodingKeys: String, CodingKey {
        case name, version, description, skills
        case protocolVersion = "protocol_version"
        case interfaceURL = "interface_url"
        case authSchemesOffered = "auth_schemes_offered"
    }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        name = try container.decodeIfPresent(String.self, forKey: .name)
        version = try container.decodeIfPresent(String.self, forKey: .version)
        description = try container.decodeIfPresent(String.self, forKey: .description)
        protocolVersion = try container.decodeIfPresent(String.self, forKey: .protocolVersion)
        interfaceURL = try container.decodeIfPresent(String.self, forKey: .interfaceURL)
        skills = try container.decodeLossyList(Skill.self, forKey: .skills)
        authSchemesOffered = try container.decodeLossyList(SchemeOffer.self, forKey: .authSchemesOffered)
    }
}

/// `AgentConnectionResponse`. The description is redacted: it would hold the agent's name and address.
public struct AgentConnectionDTO: Hashable, Sendable, Decodable, CustomStringConvertible {
    public let id: String
    public let name: String
    public let agentAddress: String
    public let authScheme: AgentAuthScheme
    /// The header an `api_key` credential is sent in.
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

    public init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = try c.decode(String.self, forKey: .name)
        agentAddress = try c.decode(String.self, forKey: .agentAddress)
        authScheme = try c.decode(AgentAuthScheme.self, forKey: .authScheme)
        authHeaderName = try c.decodeIfPresent(String.self, forKey: .authHeaderName)
        status = try c.decode(AgentConnectionStatus.self, forKey: .status)
        stale = try c.decode(Bool.self, forKey: .stale)
        staleAfterSeconds = try c.decode(Int.self, forKey: .staleAfterSeconds)
        readyForHandoff = try c.decode(Bool.self, forKey: .readyForHandoff)
        capabilities = try c.decodeIfPresent(AgentCapabilitiesDTO.self, forKey: .capabilities) ?? .init()
        controlsOffered = try c.decodeIfPresent(AgentControlsDTO.self, forKey: .controlsOffered) ?? .init()
        card = c.decodeLossy(AgentCardDTO.self, forKey: .card)
        guaranteeTier = try c.decodeIfPresent(AgentGuaranteeTier.self, forKey: .guaranteeTier)
        tierDisclosure = try c.decodeIfPresent(String.self, forKey: .tierDisclosure)
        cancellationDisclosure = try c.decodeIfPresent(String.self, forKey: .cancellationDisclosure)
        agentChanged = try c.decodeIfPresent(Bool.self, forKey: .agentChanged) ?? false
        lastTestErrorCode = try c.decodeIfPresent(String.self, forKey: .lastTestErrorCode)
        lastContactAt = try c.decodeIfPresent(Date.self, forKey: .lastContactAt)
        lastTestedAt = try c.decodeIfPresent(Date.self, forKey: .lastTestedAt)
        createdAt = try c.decode(Date.self, forKey: .createdAt)
        revision = try c.decode(Int.self, forKey: .revision)
    }
}

// MARK: - Request bodies (encode-only, redacted)

/// A request body that may carry a credential or password: it prints, reflects and dumps as nothing.
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
    /// `GET /agent-connections` → every connection, disconnected ones included. A 404 with the relay's
    /// message (`agentFailure == .relayUnavailable`) means the flag is off for this account.
    public func agentConnections() async throws(APIError) -> [AgentConnectionDTO] {
        try await get(["agent-connections"])
    }

    /// `GET /agent-connections/{id}`.
    public func agentConnection(id: String) async throws(APIError) -> AgentConnectionDTO {
        try await get(["agent-connections", id])
    }

    /// `POST /agent-connections` → 201. The server checks `currentPassword` (403 `.wrongPassword`).
    public func createAgentConnection(
        name: String, address: String, scheme: AgentAuthScheme, credential: String, currentPassword: String,
        idempotencyKey: UUID
    ) async throws(APIError) -> AgentConnectionDTO {
        let body = AgentConnectionCreateBody(
            name: name, agentAddress: address, authScheme: scheme, credential: credential,
            currentPassword: currentPassword)
        return try await mutate(.post, ["agent-connections"], body, key: idempotencyKey)
    }

    /// `PUT /agent-connections/{id}`. Nil fields are omitted; `currentPassword` is needed only when the
    /// address or scheme changes.
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

    /// `POST /agent-connections/{id}/credential`.
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
