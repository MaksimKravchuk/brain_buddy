import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyWorkspace
import Foundation
import Observation

/// The two reads All runs makes (030-FR-005). `BrainBuddyAPIClient` is the production remote.
public protocol AgentRunsRemote: Sendable {
    func agentRunSummaries(taskIDs: [String]) async throws(APIError) -> [String: AgentRunSummaryDTO]
    func agentRun(id: String) async throws(APIError) -> AgentRunDTO
}

extension BrainBuddyAPIClient: AgentRunsRemote {}

/// An open step the store lists runs for. Only steps with a server id can have a run (030-FR-013).
public struct AgentOpenStep: Equatable, Sendable {
    public var title: String
    public var serverID: String

    public init(title: String, serverID: String) { (self.title, self.serverID) = (title, serverID) }

    /// The open steps (clarification (c): not completed, not cancelled) the server knows, read-only.
    /// A Rust-selected workspace does not put the server id on its task records, so it lists none
    /// here; see the 030 PR-04 notes for the kit accessor that closes that gap.
    @MainActor
    public static func open(in workspace: Workspace) -> [AgentOpenStep] {
        workspace.state.tasks.values.filter(\.isOpen).compactMap { task in
            task.serverID.map { AgentOpenStep(title: task.title, serverID: $0) }
        }
    }
}

public enum AgentRunsPhase: Equatable, Sendable { case loading, loaded, stale, failed(reference: String?) }

public struct AgentRunSection: Equatable, Sendable {
    public var group: AgentRunGroup
    public var items: [AgentRunItem]

    public init(group: AgentRunGroup, items: [AgentRunItem]) { (self.group, self.items) = (group, items) }
}

/// A run held in the memory cache; it expires with its content (030-FR-027).
private struct CachedRun: AgentCacheExpiring {
    let run: AgentRunDTO
    var contentExpiresAt: Date? { run.contentExpiresAt }
}

/// The latest run of every open step, grouped for All runs and Waiting for (030-FR-005, 030-FR-006),
/// kept fresh by polling (030-FR-024). Memory only, for one account: a read that finishes after the
/// account changed is dropped (030-FR-026). Polling is a pull: the host calls `run()`, which calls
/// `pollDue()` once a second, so a test drives it by moving its clock and calling `pollDue()`.
@MainActor
@Observable
public final class AgentRunsStore {
    public static let summaryInterval: TimeInterval = 60
    public static let runReadConcurrency = 8

    public private(set) var sections: [AgentRunSection] = []
    public private(set) var items: [AgentRunItem] = []
    /// Listed runs per agent connection id, for the sidebar rows.
    public private(set) var perAgentCounts: [String: Int] = [:]
    public private(set) var lastUpdated: Date?
    public private(set) var phase = AgentRunsPhase.loading
    /// The main window is visible; polling pauses while it is not.
    public var isWindowVisible = true
    /// The Mac is online; polling pauses while it is not (030-FR-025).
    public var isOnline = true

    /// Waiting for's Agents rows: every listed run, in group order.
    public var waitingForRows: [AgentRunItem] { items }

    @ObservationIgnored private let remote: any AgentRunsRemote
    @ObservationIgnored private let steps: @MainActor () -> [AgentOpenStep]
    @ObservationIgnored private let availability: AgentAvailability
    @ObservationIgnored private let cache: AgentMemoryCache
    @ObservationIgnored private let now: @MainActor () -> Date
    @ObservationIgnored private let log: any AgentLogSink
    @ObservationIgnored private var latest: [String: String] = [:]
    @ObservationIgnored private var nextSummaryAt: Date?
    @ObservationIgnored private var nextRunAt: [String: Date] = [:]
    @ObservationIgnored private var loading = false
    @ObservationIgnored private var reloadRequested = false

    public init(
        remote: any AgentRunsRemote, steps: @escaping @MainActor () -> [AgentOpenStep],
        availability: AgentAvailability, cache: AgentMemoryCache, now: @escaping @MainActor () -> Date = { Date() },
        log: any AgentLogSink = SystemAgentLog()
    ) {
        (self.remote, self.steps, self.availability) = (remote, steps, availability)
        (self.cache, self.now, self.log) = (cache, now, log)
    }

    /// The last-read run of an open step, for an inspector opened while the run read fails (030-FR-025).
    /// Nil when nothing was read or its content has expired (030-FR-027).
    public func cachedRun(taskServerID: String) -> AgentRunDTO? {
        guard let runID = latest[taskServerID],
            case .hit(let cached) = cache.get(CachedRun.self, id: runID, bucket: .run, now: now())
        else { return nil }
        return cached.run
    }

    /// Sign-out, session end or account change: everything listed is dropped.
    public func reset() {
        (latest, nextRunAt, nextSummaryAt, lastUpdated) = ([:], [:], nil as Date?, nil as Date?)
        (sections, items, perAgentCounts, phase) = ([], [], [:], .loading)
    }

    /// First load, Sync now (⌘R) and the refresh after a hand-off, reply or stop: summaries, then every listed run.
    public func refresh() async { await load(readAllRuns: true) }

    /// The open steps changed (a step was marked done or added): list again from what is already read.
    public func stepsChanged() { rebuild() }

    /// One poll step at the injected clock: summaries every 60 s, each non-ended run at its own interval.
    /// Nothing runs while hidden or offline.
    public func pollDue() async {
        guard isWindowVisible, isOnline, availability.ownerID != nil else { return }
        guard let nextSummaryAt else { return await refresh() }
        if now() >= nextSummaryAt { await load(readAllRuns: false) }
        let due = items.filter { !$0.state.isEnded && (nextRunAt[$0.runID] ?? .distantPast) <= now() }.map(\.runID)
        guard !due.isEmpty, let owner = availability.ownerID else { return rebuild() }
        _ = await readRuns(due, owner: owner)
        rebuild()
    }

    /// The host's polling loop; cancel its task to stop it.
    public func run(tick: Duration = .seconds(1)) async {
        while !Task.isCancelled {
            await pollDue()
            try? await Task.sleep(for: tick)
        }
    }

    private func load(readAllRuns: Bool) async {
        if loading {
            reloadRequested = true
            return
        }
        loading = true
        defer { loading = false }
        repeat {
            reloadRequested = false
            await loadOnce(readAllRuns: readAllRuns)
        } while reloadRequested
    }

    private func loadOnce(readAllRuns: Bool) async {
        guard let owner = availability.ownerID else { return }
        cache.bind(owner: owner)
        let ids = Set(steps().map(\.serverID)).sorted()
        let result = await Self.readSummaries(remote, ids)
        guard owner == availability.ownerID else { return record("discarded", steps: ids.count) }
        switch result {
        case .failure(let error):
            phase = items.isEmpty ? .failed(reference: error.referenceID) : .stale
            record("stale", steps: ids.count)
        case .success(let map):
            latest = map.mapValues(\.id)
            for (task, summary) in map { cache.put(summary, id: task, bucket: .summary, owner: owner) }
            let wanted = map.values.filter { summary in
                if readAllRuns { return true }
                switch cache.get(CachedRun.self, id: summary.id, bucket: .run, now: now()) {
                case .hit(let cached): return cached.run.primaryState != summary.primaryState
                case .expired: return false
                case .miss: return true
                }
            }
            let complete = await readRuns(wanted.map(\.id), owner: owner)
            guard owner == availability.ownerID else { return record("discarded", steps: ids.count) }
            nextSummaryAt = now().addingTimeInterval(Self.summaryInterval)
            lastUpdated = now()
            phase = complete ? .loaded : .stale
            record(complete ? "loaded" : "stale", steps: ids.count)
        }
        rebuild()
    }

    /// Reads the runs a few at a time; false when any read failed (the last-read run stays).
    private func readRuns(_ ids: [String], owner: String) async -> Bool {
        var complete = true
        for start in stride(from: 0, to: ids.count, by: Self.runReadConcurrency) {
            let chunk = ids[start..<min(start + Self.runReadConcurrency, ids.count)]
            let remote = remote
            let results = await withTaskGroup(
                of: (String, Result<AgentRunDTO, APIError>).self, returning: [(String, Result<AgentRunDTO, APIError>)].self
            ) { group in
                for id in chunk { group.addTask { (id, await Self.readRun(remote, id)) } }
                var all: [(String, Result<AgentRunDTO, APIError>)] = []
                for await pair in group { all.append(pair) }
                return all
            }
            guard owner == availability.ownerID else { return false }
            for (id, result) in results {
                switch result {
                case .success(let run):
                    cache.put(CachedRun(run: run), id: run.id, bucket: .run, owner: owner)
                    nextRunAt[run.id] = now().addingTimeInterval(TimeInterval(max(1, run.observationIntervalSeconds)))
                case .failure:
                    complete = false
                    nextRunAt[id] = now().addingTimeInterval(Self.summaryInterval)
                }
            }
        }
        return complete
    }

    /// Items from the cache for the steps that are open now, so a marked-done step drops out (clarification (c))
    /// and content past its expiry is replaced by the expired label (030-FR-027).
    private func rebuild() {
        let at = now()
        var built: [AgentRunItem] = []
        for step in steps() {
            guard let runID = latest[step.serverID],
                case .hit(let summary) = cache.get(AgentRunSummaryDTO.self, id: step.serverID, bucket: .summary, now: at)
            else { continue }
            var item = AgentRunItem(
                stepTitle: step.title, taskServerID: step.serverID, runID: runID, agentName: summary.agentName,
                state: summary.primaryState, lastContactAt: summary.lastContactAt)
            switch cache.get(CachedRun.self, id: runID, bucket: .run, now: at) {
            case .hit(let cached):
                let run = cached.run
                item.connectionID = run.connectionID
                item.agentName = run.agentName
                item.state = run.primaryState
                item.questionText = run.questionText
                item.sentAt = run.createdAt
                item.lastContactAt = run.lastContactAt ?? summary.lastContactAt
            case .expired: item.state = .contentExpired
            case .miss: break
            }
            built.append(item)
        }
        built.sort { ($0.stepTitle, $0.runID) < ($1.stepTitle, $1.runID) }
        let grouped = AgentRunGroup.allCases.compactMap { group -> AgentRunSection? in
            let rows = built.filter { $0.group == group }
            return rows.isEmpty ? nil : AgentRunSection(group: group, items: rows)
        }
        let ordered = grouped.flatMap(\.items)
        let counts = Dictionary(ordered.compactMap(\.connectionID).map { ($0, 1) }, uniquingKeysWith: +)
        if grouped != sections { sections = grouped }
        if ordered != items { items = ordered }
        if counts != perAgentCounts { perAgentCounts = counts }
    }

    /// Counts and stage only (030-FR-039): never a title, agent name or run content.
    private func record(_ outcome: String, steps: Int) {
        log.log("agent-runs stage=refresh outcome=\(outcome) steps=\(steps) runs=\(latest.count)")
    }

    private nonisolated static func readSummaries(
        _ remote: any AgentRunsRemote, _ ids: [String]
    ) async -> Result<[String: AgentRunSummaryDTO], APIError> {
        do throws(APIError) { return .success(try await remote.agentRunSummaries(taskIDs: ids)) } catch { return .failure(error) }
    }

    private nonisolated static func readRun(_ remote: any AgentRunsRemote, _ id: String) async -> Result<AgentRunDTO, APIError> {
        do throws(APIError) { return .success(try await remote.agentRun(id: id)) } catch { return .failure(error) }
    }
}
