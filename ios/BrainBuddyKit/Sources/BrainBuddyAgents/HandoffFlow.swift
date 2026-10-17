import BrainBuddyAPI
import Foundation
import Observation

/// The calls a hand-off makes (030-FR-014, 030-FR-015, 030-FR-017). `BrainBuddyAPIClient` is the production
/// remote. Opening the sheet tests each listed-ready agent again, so a stopped agent is not offered.
public protocol HandoffRemote: Sendable {
    func agentConnections() async throws(APIError) -> [AgentConnectionDTO]
    func testAgentConnection(id: String, idempotencyKey: UUID) async throws(APIError) -> AgentConnectionDTO
    func previewAgentHandoff(
        taskID: String, connectionID: String, includeDetails: Bool, supportingItems: [AgentContextItemDTO]
    ) async throws(APIError) -> AgentManifestDTO
    func sendAgentHandoff(
        taskID: String, connectionID: String, includeDetails: Bool, supportingItems: [AgentContextItemDTO],
        manifestToken: String, currentPassword: String?, acknowledgeDuplicateRisk: Bool, idempotencyKey: UUID
    ) async throws(APIError) -> AgentRunDTO
}

extension BrainBuddyAPIClient: HandoffRemote {}

/// One ready agent row of the sheet: name, skills joined by ", ", " · ", the start guarantee (030-FR-014).
public struct HandoffAgent: Equatable, Identifiable, Sendable {
    public let id: String
    public let name: String
    public let detail: String

    public init(_ connection: AgentConnectionDTO) {
        id = connection.id
        name = connection.name
        let skills = (connection.card?.skills ?? []).compactMap(\.name).joined(separator: ", ")
        let tier = connection.guaranteeTier == .guaranteed ? AgentsCopy.guaranteed : AgentsCopy.bestEffort
        detail = (skills.isEmpty ? [tier] : [skills, tier]).joined(separator: " · ")
    }
}

public enum HandoffPhase: Equatable, Sendable {
    case loadingAgents, noReadyAgent, previewing, ready, sending
    case failed(AgentActionFailure)
    case sent(runID: String)
}

/// The "Hand to an agent" sheet's state (030-FR-013 – 030-FR-018). Memory only. Hand-off issues no step
/// command (030-FR-012). The password is cleared after every outcome, so a failed Send needs it typed again.
@MainActor
@Observable
public final class HandoffFlow {
    public private(set) var phase = HandoffPhase.loadingAgents
    public private(set) var agents: [HandoffAgent] = []
    public private(set) var selectedID: String?
    public private(set) var manifest: AgentManifestDTO?
    public var password = ""
    public var acknowledged = false

    @ObservationIgnored private let taskID: String
    @ObservationIgnored private let items: [AgentContextItemDTO]
    @ObservationIgnored private let remote: any HandoffRemote
    @ObservationIgnored private let availability: AgentAvailability
    @ObservationIgnored private let onSent: @MainActor (AgentRunDTO) async -> Void
    @ObservationIgnored private var key: UUID?
    @ObservationIgnored private var generation = 0

    /// `onSent` puts the run into the listed runs at once (030-FR-017); PR-07 wires it to the runs store.
    public init(
        taskServerID: String, projectName: String?, remote: any HandoffRemote, availability: AgentAvailability,
        onSent: @escaping @MainActor (AgentRunDTO) async -> Void = { _ in }
    ) {
        taskID = taskServerID
        items = projectName.map { [AgentContextItemDTO(label: "Project", body: $0)] } ?? []
        (self.remote, self.availability, self.onSent) = (remote, availability, onSent)
    }

    public var needsPassword: Bool { manifest?.reauthenticationRequired == true }
    public var needsAcknowledgement: Bool { manifest?.acknowledgementRequired == true }

    /// Send is enabled once each shown field is satisfied (030-FR-016).
    public var canSend: Bool {
        guard manifest != nil, phase == .ready || isFailed else { return false }
        return (!needsPassword || !password.isEmpty) && (!needsAcknowledgement || acknowledged)
    }

    private var isFailed: Bool {
        if case .failed = phase { return true }
        return false
    }

    /// The sheet opened: agents listed ready are tested again, and only those still ready are offered, the
    /// first selected and previewed. A stored "ready" can outlive the agent's process (manual check A-17).
    public func start() async {
        phase = .loadingAgents
        guard await availability.confirmOnline() else { return phase = .failed(.offline) }
        let owner = availability.ownerID
        do throws(APIError) {
            let listed = try await remote.agentConnections().filter(\.readyForHandoff)
            guard owner == availability.ownerID else { return }
            let tested = await Self.retest(listed, remote)
            guard owner == availability.ownerID else { return }
            let failures = tested.compactMap { result -> APIError? in
                if case .failure(let error) = result { return error }
                return nil
            }
            // Every test failed for want of a connection: say offline rather than "no ready agent".
            if !tested.isEmpty, failures.count == tested.count, failures.allSatisfy(\.isNetwork) {
                return phase = .failed(.offline)
            }
            // A test that fails otherwise means the agent cannot be reached: it is not offered.
            let ready = tested.compactMap { result -> HandoffAgent? in
                guard case .success(let connection) = result, connection.readyForHandoff else { return nil }
                return HandoffAgent(connection)
            }
            agents = ready
            guard let first = ready.first else { return phase = .noReadyAgent }
            await select(first.id)
        } catch {
            await fail(error, owner: owner)
        }
    }

    /// Tests every agent at once, each with its own key; the answers keep the list's order.
    private nonisolated static func retest(
        _ connections: [AgentConnectionDTO], _ remote: any HandoffRemote
    ) async -> [Result<AgentConnectionDTO, APIError>] {
        await withTaskGroup(
            of: (Int, Result<AgentConnectionDTO, APIError>).self,
            returning: [Result<AgentConnectionDTO, APIError>].self
        ) { group in
            for (index, connection) in connections.enumerated() {
                let id = connection.id
                group.addTask {
                    let answer = await HandoffFlow.test(id, remote)
                    return (index, answer)
                }
            }
            var answers: [(Int, Result<AgentConnectionDTO, APIError>)] = []
            for await answer in group { answers.append(answer) }
            return answers.sorted { $0.0 < $1.0 }.map(\.1)
        }
    }

    private nonisolated static func test(
        _ id: String, _ remote: any HandoffRemote
    ) async -> Result<AgentConnectionDTO, APIError> {
        do throws(APIError) {
            return .success(try await remote.testAgentConnection(id: id, idempotencyKey: UUID()))
        } catch {
            return .failure(error)
        }
    }

    public func select(_ id: String) async {
        guard agents.contains(where: { $0.id == id }) else { return }
        selectedID = id
        await preview()
    }

    /// The agent `steps` rows from the selected one (-1 up, +1 down), clamped at both ends (030-FR-040).
    package func agentID(movingBy steps: Int) -> String? {
        guard !agents.isEmpty else { return nil }
        let current = agents.firstIndex { $0.id == selectedID } ?? 0
        return agents[min(max(current + steps, 0), agents.count - 1)].id
    }

    /// ↑/↓ in the agent list: selects the neighbouring agent; a no-op at either end or while sending.
    package func moveSelection(by steps: Int) async {
        guard phase != .sending, let id = agentID(movingBy: steps), id != selectedID else { return }
        await select(id)
    }

    /// Try again: sends the same reviewed manifest with the same key, or previews again when there is none.
    public func tryAgain() async {
        if manifest != nil { await send() } else if selectedID != nil { await preview() } else { await start() }
    }

    public func send() async {
        guard canSend, let manifest, let agent = selectedID else { return }
        phase = .sending
        guard await availability.confirmOnline() else { return phase = .failed(.offline) }
        let owner = availability.ownerID
        let secret = needsPassword ? password : nil
        let acknowledge = needsAcknowledgement && acknowledged
        let sendKey = key ?? UUID()
        key = sendKey
        defer { (password, acknowledged) = ("", false) }
        do throws(APIError) {
            let run = try await remote.sendAgentHandoff(
                taskID: taskID, connectionID: agent, includeDetails: true, supportingItems: items,
                manifestToken: manifest.token, currentPassword: secret, acknowledgeDuplicateRisk: acknowledge,
                idempotencyKey: sendKey)
            guard owner == availability.ownerID else { return }
            key = nil
            phase = .sent(runID: run.id)
            await onSent(run)
        } catch {
            // A stale or used manifest is read again and never resent (030-FR-017).
            if error.needsManifestReview { return await preview() }
            if !error.isUncertainOutcome { key = nil }
            await fail(error, owner: owner)
        }
    }

    private func preview() async {
        guard let agent = selectedID else { return }
        guard await availability.confirmOnline() else { return phase = .failed(.offline) }
        generation += 1
        let ticket = generation
        (manifest, key, phase) = (nil, nil, .previewing)
        (password, acknowledged) = ("", false)
        let owner = availability.ownerID
        do throws(APIError) {
            let reviewed = try await remote.previewAgentHandoff(
                taskID: taskID, connectionID: agent, includeDetails: true, supportingItems: items)
            guard ticket == generation, owner == availability.ownerID else { return }
            (manifest, phase) = (reviewed, .ready)
        } catch {
            guard ticket == generation else { return }
            await fail(error, owner: owner)
        }
    }

    private func fail(_ error: APIError, owner: String?) async {
        guard owner == availability.ownerID else { return }
        let failure = AgentActionFailure(error)
        phase = .failed(failure)
        if failure == .unavailable { await availability.relayUnavailable() }
    }
}
