import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyWorkspace
import Foundation
import Observation

/// One open step the runs are listed for: its local id (to open its card), its server id and its title.
public struct AgentStepRef: Equatable, Sendable {
    public var taskID: TaskID
    public var serverID: String
    public var title: String

    public init(taskID: TaskID, serverID: String, title: String) {
        (self.taskID, self.serverID, self.title) = (taskID, serverID, title)
    }

    /// The open steps the server knows, with their titles, read through the kit (it is async on a
    /// Rust workspace, where unrendered steps are prepared 200 at a time). Nil when the read failed.
    @MainActor
    public static func open(in workspace: Workspace) async -> [AgentStepRef]? {
        guard let ids = try? await workspace.openStepServerIDs() else { return nil }
        let unshown = ids.filter { workspace.task($0.taskID) == nil }.map(\.taskID)
        var titles: [TaskID: String] = [:]
        for start in stride(from: 0, to: unshown.count, by: 200) {
            // A failed batch fails the whole read, so the caller keeps its last list instead of
            // dropping the steps that batch would have titled.
            guard let batch = try? await workspace.prepareTaskViews(Array(unshown[start..<min(start + 200, unshown.count)]))
            else { return nil }
            for task in batch {
                titles[task.id] = task.title
            }
        }
        return ids.compactMap { step in
            guard let server = step.serverID, let title = workspace.task(step.taskID)?.title ?? titles[step.taskID] else {
                return nil
            }
            return AgentStepRef(taskID: step.taskID, serverID: server, title: title)
        }
    }
}

/// The agent surfaces of one app window (034-FR-002, 034-FR-003): availability, the memory-only run cache
/// and the listed runs of the signed-in account, over the open steps. The Mac's `BrainBuddyModel` does the
/// same wiring for its sidebar; the iPhone binds its Waiting for list, task card and settings to this.
/// Memory only. Everything is dropped when the account changes or signs out (030-FR-026).
@MainActor
@Observable
public final class AgentsSession {
    public let availability: AgentAvailability
    public let runs: AgentRunsStore
    @ObservationIgnored public let cache: AgentMemoryCache
    @ObservationIgnored private let account: @MainActor () -> LinkedAccount?
    @ObservationIgnored private let loadSteps: @MainActor () async -> [AgentStepRef]?
    @ObservationIgnored private let box: StepsBox

    /// `account` is read at every call; `steps` reads the open steps (nil when the read failed).
    public init(
        account: @escaping @MainActor () -> LinkedAccount?,
        steps: @escaping @MainActor () async -> [AgentStepRef]?,
        availabilityRemote: @escaping @MainActor (LinkedAccount) -> any AgentAvailabilityRemote,
        runsRemote: any AgentRunsRemote,
        now: @escaping @MainActor () -> Date = { Date() },
        log: any AgentLogSink = SystemAgentLog()
    ) {
        let box = StepsBox()
        let cache = AgentMemoryCache()
        let availability = AgentAvailability(account: account(), remote: availabilityRemote, now: now, log: log)
        self.availability = availability
        self.cache = cache
        self.box = box
        self.account = account
        loadSteps = steps
        runs = AgentRunsStore(
            remote: runsRemote, steps: { box.steps.map { AgentOpenStep(title: $0.title, serverID: $0.serverID) } },
            availability: availability, cache: cache, now: now, log: log)
    }

    // MARK: what the screens show

    /// Hand off… on a step's card and Hand off again (030-FR-002, 030-FR-013).
    public var canHandOff: Bool { availability.ownerID != nil && availability.relayEnabled }

    /// Add new agent, + and Test again (030-FR-002, 030-FR-036).
    public var canAddAgent: Bool { canHandOff && availability.passwordState != .none }

    /// Settings shows its Agents section for a signed-in account (030-FR-001).
    public var showsSettings: Bool { availability.ownerID != nil }

    /// Waiting for's Agents rows, in group order; none while signed out (030-FR-009, 030-FR-010).
    public var waitingRows: [AgentRunItem] { availability.ownerID == nil ? [] : runs.items }

    /// "2 people, 1 agent" under Waiting for when runs are listed, else nil (board 22).
    public func waitingHeader(people: Int) -> String? {
        let agents = waitingRows.count
        return agents == 0 ? nil : AgentsCopy.waitingHeader(people: people, agents: agents)
    }

    /// The listed run of a step, for its card.
    public func item(forStep serverID: String?) -> AgentRunItem? {
        guard let serverID else { return nil }
        return waitingRows.first { $0.taskServerID == serverID }
    }

    /// The local step a listed run belongs to, to open its card.
    public func stepID(forServerID id: String) -> TaskID? { box.taskIDs[id] }

    // MARK: lifecycle

    /// The workspace's account may have changed (sign-in, sign-out, another account).
    public func syncAccount() {
        let before = availability.ownerID
        availability.update(account: account())
        if availability.ownerID != before { drop() }
    }

    /// Sign-in and the app coming to the foreground: flag, password state (throttled), steps, runs.
    public func refresh() async {
        syncAccount()
        guard availability.ownerID != nil else { return }
        await availability.activate()
        await refreshSteps()
        await runs.refresh()
    }

    /// A step was added, completed or renamed: list again from what is already read.
    public func refreshSteps() async {
        guard availability.ownerID != nil, let steps = await loadSteps() else { return }
        box.steps = steps
        box.taskIDs = Dictionary(steps.map { ($0.serverID, $0.taskID) }) { first, _ in first }
        runs.stepsChanged()
    }

    /// Polling runs only in the foreground and online (030-FR-024, 030-FR-025).
    public func setForeground(_ foreground: Bool) { runs.isWindowVisible = foreground }

    public func setOnline(_ online: Bool) { runs.isOnline = online }

    private func drop() {
        cache.clear()
        runs.reset()
        box.steps = []
        box.taskIDs = [:]
    }
}

/// The open steps, kept outside observation because the store reads them synchronously.
@MainActor
private final class StepsBox {
    var steps: [AgentStepRef] = []
    var taskIDs: [String: TaskID] = [:]
}

/// The only two step commands an agent surface issues (030-FR-012, 030-FR-022), over the workspace.
@MainActor
public struct WorkspaceStepCommands: StepCommands {
    public let workspace: Workspace
    public let taskID: TaskID

    public init(workspace: Workspace, taskID: TaskID) { (self.workspace, self.taskID) = (workspace, taskID) }

    public func completeStep(serverID: String) async throws {
        try await workspace.completeTask(taskID, editorID: UUID().uuidString)
    }

    public func createNextAction(title: String, projectID: String?) async throws {
        let project = projectID.map { ProjectID($0) }
        let command: GTDCommand = .createTask(.init(taskID: .random(), title: title, list: .next, projectID: project))
        try await workspace.apply([command], editorID: UUID().uuidString)
    }
}
