import Foundation

// External agent runs (spec 030): `backend/app/api/agents.py`, `backend/app/schemas/agents.py`.
// A hand-off names the reviewed manifest token; a reply, a delivery check and a stop name the
// revision the person saw. Request bodies that may carry a password are encode-only and print
// nothing of it. The primary label reads an unknown value as `.unknown`, so a newer label shows verbatim.

/// The run's primary label, rendered verbatim (`AgentPrimaryStateLabel`, 030-FR-014).
public enum AgentPrimaryState: Hashable, Sendable, Decodable {
    case notSent, queued, sent, deliveryUnconfirmed, accepted, running, needsYou
    case cancellationRequested, agentReportedComplete, failed, cancelled, stoppedReporting
    case agentNoLongerReportsThisRun, connectionDisconnected, contentExpired
    case unknown(String)

    public init(wireValue: String) {
        let known: [String: Self] = [
            "Not sent": .notSent, "Queued": .queued, "Sent": .sent, "Delivery unconfirmed": .deliveryUnconfirmed,
            "Accepted": .accepted, "Running": .running, "Needs you": .needsYou,
            "Cancellation requested": .cancellationRequested, "Agent reported complete": .agentReportedComplete,
            "Failed": .failed, "Cancelled": .cancelled, "Stopped reporting": .stoppedReporting,
            "Agent no longer reports this run": .agentNoLongerReportsThisRun,
            "Connection disconnected": .connectionDisconnected,
            "Content expired under retention policy": .contentExpired,
        ]
        self = known[wireValue] ?? .unknown(wireValue)
    }

    public init(from decoder: any Decoder) throws {
        self.init(wireValue: try decoder.singleValueContainer().decode(String.self))
    }
}

/// One supporting item the owner chose to include (`AgentContextItemRequest`, `AgentContextItemResponse`).
public struct AgentContextItemDTO: Hashable, Sendable, Codable {
    public let label: String
    public let body: String

    public init(label: String, body: String) {
        self.label = label
        self.body = body
    }
}

/// `AgentManifestResponse`: exactly what will leave BrainBuddy, for the person to review (030-FR-005).
/// Its token is the single-use reservation the send names. Its description is redacted.
public struct AgentManifestDTO: Hashable, Sendable, Decodable, CustomStringConvertible {
    public let token: String
    public let runID: String
    public let taskID: String
    public let connectionID: String
    public let agentName: String
    public let title: String
    public let details: String?
    public let supportingItems: [AgentContextItemDTO]
    public let guaranteeTier: AgentGuaranteeTier
    public let tierDisclosure: String
    public let cancellationDisclosure: String
    public let externalCopyNotice: String
    public let acknowledgementRequired: Bool
    public let reauthenticationRequired: Bool

    public var description: String { "Hand-off manifest (redacted)" }

    enum CodingKeys: String, CodingKey {
        case token, title, details
        case runID = "run_id"
        case taskID = "task_id"
        case connectionID = "connection_id"
        case agentName = "agent_name"
        case supportingItems = "supporting_items"
        case guaranteeTier = "guarantee_tier"
        case tierDisclosure = "tier_disclosure"
        case cancellationDisclosure = "cancellation_disclosure"
        case externalCopyNotice = "external_copy_notice"
        case acknowledgementRequired = "acknowledgement_required"
        case reauthenticationRequired = "reauthentication_required"
    }
}

/// One row of a run's timeline (`AgentRunEventResponse`). `kind` is `observation` or `task_succession`;
/// a succession row names the agent's previous and new task.
public struct AgentRunEventDTO: Hashable, Sendable, Decodable {
    public let id: String
    public let type: String
    public let runVersion: Int
    public let receivedAt: Date
    public let summary: String?
    public let trigger: String
    public let kind: String
    public let previousAgentTaskID: String?
    public let newAgentTaskID: String?

    enum CodingKeys: String, CodingKey {
        case id, type, summary, trigger, kind
        case runVersion = "run_version"
        case receivedAt = "received_at"
        case previousAgentTaskID = "previous_agent_task_id"
        case newAgentTaskID = "new_agent_task_id"
    }
}

/// A message or stop BrainBuddy sent to the agent (`AgentRunCommandResponse`).
public struct AgentRunCommandDTO: Hashable, Sendable, Decodable {
    public let id: String
    public let kind: String
    public let body: String?
    public let delivery: String
    public let outcomeCode: String?
    public let createdAt: Date
    public let confirmedAt: Date?

    enum CodingKeys: String, CodingKey {
        case id, kind, body, delivery
        case outcomeCode = "outcome_code"
        case createdAt = "created_at"
        case confirmedAt = "confirmed_at"
    }
}

/// The owner-facing projection of one run (`AgentRunResponse`). Connector-reported facts, derived
/// conditions and pending commands stay separate fields, as on the server. `controls` is the
/// server's `capabilities`: the controls still offered on this run.
public struct AgentRunDTO: Hashable, Sendable, Decodable {
    public let id: String
    public let taskID: String
    public let connectionID: String
    public let agentName: String
    public let primaryState: AgentPrimaryState
    public let needsUser: Bool
    public let stoppedReporting: Bool
    public let connectionDisconnected: Bool
    public let replyPending: Bool
    public let cancelRequested: Bool
    public let progressText: String?
    public let questionText: String?
    public let resultText: String?
    public let resultLink: String?
    public let resultLinkInteractive: Bool
    public let failureReason: String?
    public let contentExpired: Bool
    public let contentExpiresAt: Date
    public let lastContactAt: Date?
    public let observationIntervalSeconds: Int
    public let controls: AgentControlsDTO
    public let guaranteeTier: AgentGuaranteeTier?
    public let exchangeState: String
    public let cancelOutcome: String
    public let resultAvailability: String?
    public let events: [AgentRunEventDTO]
    public let commands: [AgentRunCommandDTO]
    public let createdAt: Date
    public let revision: Int

    enum CodingKeys: String, CodingKey {
        case id, events, commands, revision
        case taskID = "task_id"
        case connectionID = "connection_id"
        case agentName = "agent_name"
        case primaryState = "primary_state_label"
        case needsUser = "needs_user"
        case stoppedReporting = "stopped_reporting"
        case connectionDisconnected = "connection_disconnected"
        case replyPending = "reply_pending"
        case cancelRequested = "cancel_requested"
        case progressText = "progress_text"
        case questionText = "question_text"
        case resultText = "result_text"
        case resultLink = "result_link"
        case resultLinkInteractive = "result_link_interactive"
        case failureReason = "failure_reason"
        case contentExpired = "content_expired"
        case contentExpiresAt = "content_expires_at"
        case lastContactAt = "last_contact_at"
        case observationIntervalSeconds = "observation_interval_seconds"
        case controls = "capabilities"
        case guaranteeTier = "guarantee_tier"
        case exchangeState = "exchange_state"
        case cancelOutcome = "cancel_outcome"
        case resultAvailability = "result_availability"
        case createdAt = "created_at"
    }
}

/// The compact row for the Task surface: the latest run of one step, no timeline (`AgentRunSummaryResponse`).
public struct AgentRunSummaryDTO: Hashable, Sendable, Decodable {
    public let id: String
    public let taskID: String
    public let agentName: String
    public let primaryState: AgentPrimaryState
    public let needsUser: Bool
    public let stoppedReporting: Bool
    public let lastContactAt: Date?
    public let guaranteeTier: AgentGuaranteeTier?
    public let cancelOutcome: String
    public let agentTaskMissing: Bool

    enum CodingKeys: String, CodingKey {
        case id
        case taskID = "task_id"
        case agentName = "agent_name"
        case primaryState = "primary_state_label"
        case needsUser = "needs_user"
        case stoppedReporting = "stopped_reporting"
        case lastContactAt = "last_contact_at"
        case guaranteeTier = "guarantee_tier"
        case cancelOutcome = "cancel_outcome"
        case agentTaskMissing = "agent_task_missing"
    }
}

// MARK: - Request bodies

/// `AgentHandoffPreviewRequest`. Carries no secret.
struct AgentHandoffPreviewBody: Encodable {
    let connectionID: String
    let includeDetails: Bool
    let supportingItems: [AgentContextItemDTO]

    enum CodingKeys: String, CodingKey {
        case connectionID = "connection_id"
        case includeDetails = "include_details"
        case supportingItems = "supporting_items"
    }
}

/// `AgentHandoffConfirmRequest`: the preview's inputs plus the reviewed token. The password is present
/// only when the server asked for it, so this body is redacted.
struct AgentHandoffConfirmBody: RedactedRequestBody {
    let connectionID: String
    let includeDetails: Bool
    let supportingItems: [AgentContextItemDTO]
    let manifestToken: String
    let currentPassword: String?
    let acknowledgeDuplicateRisk: Bool

    enum CodingKeys: String, CodingKey {
        case connectionID = "connection_id"
        case includeDetails = "include_details"
        case supportingItems = "supporting_items"
        case manifestToken = "manifest_token"
        case currentPassword = "current_password"
        case acknowledgeDuplicateRisk = "acknowledge_duplicate_risk"
    }
}

struct AgentReplyBody: Encodable {
    let message: String
    let expectedRevision: Int

    enum CodingKeys: String, CodingKey {
        case message
        case expectedRevision = "expected_revision"
    }
}

/// `AgentCheckDeliveryRequest`. The password is sent only when the server needs it for the resend.
struct AgentCheckDeliveryBody: RedactedRequestBody {
    let currentPassword: String?
    let expectedRevision: Int

    enum CodingKeys: String, CodingKey {
        case currentPassword = "current_password"
        case expectedRevision = "expected_revision"
    }
}

/// The most task ids one `GET /agent-run-summaries` names: the server bounds its `task_id` list at 200.
private let agentRunSummaryBatchSize = 200

// MARK: - Calls

extension BrainBuddyAPIClient {
    /// `POST /tasks/{id}/agent-runs/preview`: the manifest to review. It changes nothing, so it has no key.
    public func previewAgentHandoff(
        taskID: String, connectionID: String, includeDetails: Bool = true,
        supportingItems: [AgentContextItemDTO] = []
    ) async throws(APIError) -> AgentManifestDTO {
        let body = AgentHandoffPreviewBody(
            connectionID: connectionID, includeDetails: includeDetails, supportingItems: supportingItems)
        let endpoint = Endpoint(.post, ["tasks", taskID, "agent-runs", "preview"], body: try encode(body))
        return try decode(try await exchange(endpoint))
    }

    /// `POST /tasks/{id}/agent-runs` → 201. Pass the `includeDetails` and `supportingItems` the reviewed
    /// preview used: the manifest token covers them. A stale or used token is a 400 that
    /// `needsManifestReview` names; this call never resends it.
    public func sendAgentHandoff(
        taskID: String, connectionID: String, includeDetails: Bool = true,
        supportingItems: [AgentContextItemDTO] = [], manifestToken: String, currentPassword: String? = nil,
        acknowledgeDuplicateRisk: Bool = false, idempotencyKey: UUID
    ) async throws(APIError) -> AgentRunDTO {
        let body = AgentHandoffConfirmBody(
            connectionID: connectionID, includeDetails: includeDetails, supportingItems: supportingItems,
            manifestToken: manifestToken, currentPassword: currentPassword,
            acknowledgeDuplicateRisk: acknowledgeDuplicateRisk)
        return try await mutate(.post, ["tasks", taskID, "agent-runs"], body, key: idempotencyKey)
    }

    /// `GET /tasks/{id}/agent-runs`: every run of one step, newest first as the server orders them.
    public func agentRuns(taskID: String) async throws(APIError) -> [AgentRunDTO] {
        try await get(["tasks", taskID, "agent-runs"])
    }

    /// The latest run of each listed step. Sends one request per 200 ids, in order, and merges the sparse
    /// maps. An empty list sends nothing. The first failing batch throws and later batches are not sent.
    public func agentRunSummaries(taskIDs: [String]) async throws(APIError) -> [String: AgentRunSummaryDTO] {
        var summaries: [String: AgentRunSummaryDTO] = [:]
        for start in stride(from: 0, to: taskIDs.count, by: agentRunSummaryBatchSize) {
            let batch = taskIDs[start..<min(start + agentRunSummaryBatchSize, taskIDs.count)]
            let query = batch.map { (name: "task_id", value: $0) }
            let page: [String: AgentRunSummaryDTO] = try await get(["agent-run-summaries"], query: query)
            summaries.merge(page) { _, new in new }
        }
        return summaries
    }

    public func agentRun(id: String) async throws(APIError) -> AgentRunDTO {
        try await get(["agent-runs", id])
    }

    /// `POST /agent-runs/{id}/reply`, with the revision the person saw.
    public func replyToAgentRun(
        id: String, message: String, expectedRevision: Int, idempotencyKey: UUID
    ) async throws(APIError) -> AgentRunDTO {
        let body = AgentReplyBody(message: message, expectedRevision: expectedRevision)
        return try await mutate(.post, ["agent-runs", id, "reply"], body, key: idempotencyKey)
    }

    /// `POST /agent-runs/{id}/check-delivery`: looks the run up at the agent and resends only what the rules allow.
    public func checkAgentRunDelivery(
        id: String, currentPassword: String?, expectedRevision: Int, idempotencyKey: UUID
    ) async throws(APIError) -> AgentRunDTO {
        let body = AgentCheckDeliveryBody(currentPassword: currentPassword, expectedRevision: expectedRevision)
        return try await mutate(.post, ["agent-runs", id, "check-delivery"], body, key: idempotencyKey)
    }

    /// `POST /agent-runs/{id}/cancel` (no body).
    public func cancelAgentRun(id: String, idempotencyKey: UUID) async throws(APIError) -> AgentRunDTO {
        let endpoint = Endpoint(.post, ["agent-runs", id, "cancel"], idempotencyKey: idempotencyKey)
        return try decode(try await exchange(endpoint))
    }
}

extension APIError {
    /// True when the server refused a hand-off's manifest token as stale or used (400 with
    /// `detail.reason` `manifest_not_reserved` or `manifest_token_mismatch`). The person re-reviews the
    /// preview; the token is never resent. Read the same way as the web's `needsReReview`.
    public var needsManifestReview: Bool {
        statusCode == 400 && (reason == "manifest_not_reserved" || reason == "manifest_token_mismatch")
    }
}
