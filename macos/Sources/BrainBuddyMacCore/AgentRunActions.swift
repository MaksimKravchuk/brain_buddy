import BrainBuddyAPI
import Foundation
import Observation

/// The run calls the inspector makes (030-FR-020, 030-FR-023). `BrainBuddyAPIClient` is the production remote.
package protocol AgentRunActionsRemote: Sendable {
    func replyToAgentRun(id: String, message: String, expectedRevision: Int, idempotencyKey: UUID) async throws(APIError) -> AgentRunDTO
    func checkAgentRunDelivery(id: String, currentPassword: String?, expectedRevision: Int, idempotencyKey: UUID) async throws(APIError) -> AgentRunDTO
    func cancelAgentRun(id: String, idempotencyKey: UUID) async throws(APIError) -> AgentRunDTO
}

extension BrainBuddyAPIClient: AgentRunActionsRemote {}

/// The only two step commands the agent feature may call (030-FR-012), over the workspace's existing
/// complete and create commands. Nothing but `AgentRunActions.markStepDone` holds one.
@MainActor
package protocol StepCommands {
    func completeStep(serverID: String) async throws
    /// Creates a step in Next actions, in the project when one is given.
    func createNextAction(title: String, projectID: String?) async throws
}

/// How a hand-off or run action failed, in the words of 030-FR-018. Nothing is retried automatically.
package enum AgentActionFailure: Equatable, Sendable {
    case wrongPassword, rateLimited, offline, unavailable, staleRevision, controlWithdrawn, tooLong
    case other(reference: String?)

    package init(_ error: APIError) {
        switch error.agentFailure {
        case .relayUnavailable: self = .unavailable
        case .wrongPassword: self = .wrongPassword
        case .staleRevision: self = .staleRevision
        case .rateLimited: self = .rateLimited
        case .offline: self = .offline
        case .other: self = .other(reference: error.referenceID)
        }
    }

    package func text(offline: String = AgentsCopy.needsConnection) -> String {
        switch self {
        case .wrongPassword: AgentsCopy.wrongPassword
        case .rateLimited: AgentsCopy.rateLimited
        case .offline: offline
        case .staleRevision: AgentsCopy.staleRevision
        case .controlWithdrawn: "The agent no longer offers this."
        case .tooLong: "A reply can have at most 4,000 characters."
        case .unavailable, .other: AgentsCopy.handOffUnavailable
        }
    }

    package var reference: String? {
        if case .other(let id) = self, let id { return AgentsCopy.reference(id) }
        return nil
    }
}

package enum AgentActionPhase: Equatable, Sendable { case idle, working, done, failed(AgentActionFailure) }

/// Reply, Stop run, Check again, Mark step done and Make the next step (030-FR-020 – 030-FR-023). Offline
/// each refuses and nothing is queued (030-FR-025). One Idempotency-Key per attempt, reused only when the
/// same attempt is retried after an uncertain outcome. The password is never held here.
@MainActor
@Observable
package final class AgentRunActions {
    package nonisolated static let replyLimit = 4_000

    package private(set) var phase = AgentActionPhase.idle
    /// The run the server returned for the last action, e.g. with `replyPending` set.
    package private(set) var updated: AgentRunDTO?
    @ObservationIgnored private let remote: any AgentRunActionsRemote
    @ObservationIgnored private let availability: AgentAvailability
    @ObservationIgnored private let steps: any StepCommands
    @ObservationIgnored private let refresh: @MainActor () async -> Void
    @ObservationIgnored private var pending: (payload: String, key: UUID)?

    /// `refresh` re-reads the runs right after a reply, stop or check (030-FR-024).
    package init(
        remote: any AgentRunActionsRemote, availability: AgentAvailability, steps: any StepCommands,
        refresh: @escaping @MainActor () async -> Void = {}
    ) {
        (self.remote, self.availability, self.steps, self.refresh) = (remote, availability, steps, refresh)
    }

    package func reply(to run: AgentRunDTO, message: String) async {
        let text = message.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        guard run.controls.reply else { return phase = .failed(.controlWithdrawn) }
        guard text.count <= Self.replyLimit else { return phase = .failed(.tooLong) }
        let remote = remote
        await perform("reply|\(run.id)|\(run.revision)|\(text)") { (key) async throws(APIError) -> AgentRunDTO in
            try await remote.replyToAgentRun(id: run.id, message: text, expectedRevision: run.revision, idempotencyKey: key)
        }
    }

    package func stop(_ run: AgentRunDTO) async {
        guard run.controls.cancel else { return phase = .failed(.controlWithdrawn) }
        let remote = remote
        await perform("stop|\(run.id)") { (key) async throws(APIError) -> AgentRunDTO in
            try await remote.cancelAgentRun(id: run.id, idempotencyKey: key)
        }
    }

    /// The password goes only when the person typed one, which the field allows only when the server needs it.
    package func checkAgain(_ run: AgentRunDTO, password: String = "") async {
        let secret = password.isEmpty ? nil : password
        let remote = remote
        await perform("check|\(run.id)|\(run.revision)|\(secret != nil)") { (key) async throws(APIError) -> AgentRunDTO in
            try await remote.checkAgentRunDelivery(
                id: run.id, currentPassword: secret, expectedRevision: run.revision, idempotencyKey: key)
        }
    }

    /// Completes the step and, when "Make the next step" has text, creates it in the same project in Next actions
    /// (030-FR-022). The agent never reaches this; only the person's explicit action does (030-FR-012).
    package func markStepDone(taskServerID: String, projectID: String?, nextStep: String) async {
        guard phase != .working else { return }
        phase = .working
        let title = nextStep.trimmingCharacters(in: .whitespacesAndNewlines)
        do {
            try await steps.completeStep(serverID: taskServerID)
            if !title.isEmpty { try await steps.createNextAction(title: title, projectID: projectID) }
            phase = .done
        } catch {
            phase = .failed(.other(reference: nil))
        }
    }

    private func perform(_ payload: String, _ call: (UUID) async throws(APIError) -> AgentRunDTO) async {
        guard phase != .working else { return }
        guard availability.isOnline else { return phase = .failed(.offline) }
        phase = .working
        let owner = availability.ownerID
        let key = pending.flatMap { $0.payload == payload ? $0.key : nil } ?? UUID()
        pending = (payload, key)
        do throws(APIError) {
            let run = try await call(key)
            guard owner == availability.ownerID else { return phase = .idle }
            (pending, updated, phase) = (nil, run, .done)
            await refresh()
        } catch {
            guard owner == availability.ownerID else { return phase = .idle }
            if !error.isUncertainOutcome { pending = nil }
            let failure = AgentActionFailure(error)
            phase = .failed(failure)
            if failure == .unavailable { await availability.relayUnavailable() }
            if failure == .staleRevision { await refresh() }
        }
    }
}
