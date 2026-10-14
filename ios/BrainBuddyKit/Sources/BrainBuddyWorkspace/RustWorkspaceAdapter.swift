import BrainBuddyCore
import Foundation
import Observation

public enum WorkspaceQueryReadiness: Equatable, Sendable {
    case notRequested
    case loading
    case ready
    /// A stable code, never authored content.
    case failed(String)
}

/// Navigation belongs to one currently ready canonical page.
public struct WorkspaceQueryPageState: Equatable, Sendable {
    public let readiness: WorkspaceQueryReadiness
    public let hasPrevious: Bool
    public let hasNext: Bool
    public let projectionGeneration: UInt64?

    public init(readiness: WorkspaceQueryReadiness, hasPrevious: Bool = false, hasNext: Bool = false,
                projectionGeneration: UInt64? = nil) {
        self.readiness = readiness
        self.hasPrevious = hasPrevious
        self.hasNext = hasNext
        self.projectionGeneration = projectionGeneration
    }
}

/// Cache of owned canonical answers, not another read model. Each query holds
/// one visible page. The inputs are frozen for that page's cursor lifetime.
@MainActor
@Observable
final class RustWorkspaceAdapter {
    struct Entry {
        var page: RustWorkspacePage?
        var readiness = WorkspaceQueryReadiness.notRequested
        var cursor: String?
        var history: [String?] = []
        var inputs: Data
        var dirtyVersion: UInt64 = 0
        var requestID: UInt64 = 0
        /// The page predates the latest invalidation and no refresh has run for it yet. It is still
        /// shown (stale-while-revalidate); the next access starts the refresh.
        var stale = false
        /// A per-keystroke answer (the live capture preview): never refreshed after a save.
        var ephemeral = false
    }

    /// How many of the most recently used queries a save refreshes at once. The screens on show
    /// (a tab's list, a pushed detail, a sheet) are the latest used; older entries are marked stale
    /// and refresh when next read.
    static let liveQueryLimit = 8
    /// A refresh starts once invalidations have been quiet this long, and never later than
    /// `longestRefreshDelay` after the first of a run. A reader waiting for fresh data
    /// (`prepare`, `settle`) does not wait for either.
    static let quietPeriod = Duration.milliseconds(60)
    static let longestRefreshDelay = Duration.milliseconds(400)

    private(set) var entries: [Data: Entry] = [:]
    private(set) var generationFloor: UInt64 = 0
    @ObservationIgnored private var inputs: Data
    @ObservationIgnored private var epoch: UInt64 = 0
    @ObservationIgnored private var clock: UInt64 = 0
    @ObservationIgnored private var accessed: [Data: UInt64] = [:]
    @ObservationIgnored private var tasks: [Data: Task<Void, Never>] = [:]
    /// Queries an invalidation marked for a refresh that has not started: the store has one
    /// connection, so a refresh that began between two quick writes would hold up the second.
    @ObservationIgnored private var pendingRefresh: Set<Data> = []
    @ObservationIgnored private var pendingTask: Task<Void, Never>?
    @ObservationIgnored private var pendingSince: ContinuousClock.Instant?
    @ObservationIgnored private let query: @Sendable (Data, Data, String?) async throws -> RustWorkspaceAnswer
    @ObservationIgnored private let didPublish: @MainActor (Data, RustWorkspacePage) throws -> Void
    @ObservationIgnored private let didRefuse: @MainActor (Data, RustRefusal) -> Void
    @ObservationIgnored private let decoding: Decoding?

    /// Turning an answer into records off the main actor. `context` copies what decoding reads,
    /// `revision` says whether it is still current, `publish` adopts the decoded page.
    struct Decoding {
        let context: @MainActor () -> RustDecodeContext?
        let revision: @MainActor () -> UInt64
        let publish: @MainActor (Data, RustWorkspacePage, RustPreparedPage) throws -> Void
    }

    init(inputs: Data,
         query: @escaping @Sendable (Data, Data, String?) async throws -> RustWorkspaceAnswer,
         didPublish: @escaping @MainActor (Data, RustWorkspacePage) throws -> Void,
         decoding: Decoding? = nil,
         didRefuse: @escaping @MainActor (Data, RustRefusal) -> Void = { _, _ in }) {
        self.inputs = inputs
        self.query = query
        self.didPublish = didPublish
        self.decoding = decoding
        self.didRefuse = didRefuse
    }

    func page(for query: Data) -> RustWorkspacePage? {
        register(query)
        guard entries[query]?.readiness == .ready else { return nil }
        revalidateOnRead(query)
        return entries[query]?.page
    }

    func readiness(for query: Data) -> WorkspaceQueryReadiness {
        entries[query]?.readiness ?? .notRequested
    }

    func pageState(for query: Data) -> WorkspaceQueryPageState {
        guard let entry = entries[query] else { return WorkspaceQueryPageState(readiness: .notRequested) }
        guard entry.readiness == .ready, let page = entry.page else {
            return WorkspaceQueryPageState(readiness: entry.readiness)
        }
        return WorkspaceQueryPageState(readiness: .ready, hasPrevious: !entry.history.isEmpty,
                                       hasNext: Self.nextCursor(page) != nil,
                                       projectionGeneration: UInt64(page.projectionGeneration))
    }

    func recordFailure(_ query: Data, code: String) {
        register(query, start: false)
        tasks.removeValue(forKey: query)?.cancel()
        guard var entry = entries[query] else { return }
        clock &+= 1
        entry.requestID = clock
        entry.readiness = .failed(code)
        entry.page = nil
        entries[query] = entry
    }

    func prepare(_ query: Data) async {
        register(query)
        if let readiness = entries[query]?.readiness, case .failed = readiness { refresh(query) }
        while true {
            // A page an invalidation left behind is brought up to date before this returns.
            if entries[query]?.stale == true, tasks[query] == nil { refresh(query, keepingPage: true) }
            guard let task = tasks[query] else { return }
            await task.value
            if Task.isCancelled { return }
        }
    }

    func nextPage(_ query: Data) async {
        await prepare(query)
        guard var entry = entries[query], let page = entry.page,
              let next = Self.nextCursor(page) else { return }
        entry.history.append(entry.cursor)
        entry.cursor = next
        entry.page = nil
        entries[query] = entry
        refresh(query)
        await prepare(query)
    }

    func previousPage(_ query: Data) async {
        guard var entry = entries[query], let previous = entry.history.popLast() else { return }
        entry.cursor = previous
        entry.page = nil
        entries[query] = entry
        refresh(query)
        await prepare(query)
    }

    /// Projection changes invalidate queries; status/issues call their own
    /// consumers even when this number did not move.
    func invalidate(generation: UInt64, inputs replacement: Data? = nil) {
        generationFloor = max(generationFloor, generation)
        if let replacement { inputs = replacement }
        let live = liveKeys()
        for key in Array(entries.keys) {
            guard var entry = entries[key] else { continue }
            // A page past the first has its cursor dropped, so the page shown no longer matches
            // its navigation state: that one reloads from the start instead of staying on screen.
            let onFirstPage = entry.cursor == nil
            entry.dirtyVersion &+= 1
            entry.inputs = inputs
            entry.cursor = nil
            entry.history = []
            entry.stale = true
            if !onFirstPage { entry.page = nil; entry.readiness = .loading }
            entries[key] = entry
            if !onFirstPage { refresh(key) }
            else if live.contains(key) { pendingRefresh.insert(key) }
        }
        scheduleRefresh()
    }

    private func scheduleRefresh() {
        guard !pendingRefresh.isEmpty else { return }
        let now = ContinuousClock.now
        let since = pendingSince ?? now
        pendingSince = since
        let wait = min(Self.quietPeriod, max(.zero, Self.longestRefreshDelay - (now - since)))
        pendingTask?.cancel()
        pendingTask = Task { [weak self] in
            try? await Task.sleep(for: wait)
            guard !Task.isCancelled else { return }
            self?.flushPending()
        }
    }

    /// Starts the refreshes that are waiting out their quiet period.
    private func flushPending() {
        pendingTask?.cancel()
        pendingTask = nil
        pendingSince = nil
        let keys = pendingRefresh
        pendingRefresh = []
        for key in keys where entries[key]?.stale == true { refresh(key, keepingPage: true) }
    }

    /// Removes the cached answers of per-keystroke queries (the capture preview): on submit and
    /// dismiss, so they neither fill the cache nor get re-run after saves.
    func evictEphemeral() {
        for key in ephemeralKeys { evict(key) }
    }

    var ephemeralKeys: [Data] { entries.compactMap { $0.value.ephemeral ? $0.key : nil } }

    func evict(_ key: Data) {
        pendingRefresh.remove(key)
        tasks.removeValue(forKey: key)?.cancel()
        entries.removeValue(forKey: key)
        accessed.removeValue(forKey: key)
    }

    /// Waits until every refresh in flight (and any the waiting itself uncovers) has finished.
    func settle() async {
        flushPending()
        // A finished refresh can start another (an overtaken answer); a few rounds reach quiet.
        for _ in 0..<8 where !tasks.isEmpty {
            for task in Array(tasks.values) { await task.value }
            if Task.isCancelled { return }
        }
    }

    func close() {
        pendingTask?.cancel()
        pendingTask = nil
        pendingSince = nil
        pendingRefresh = []
        epoch &+= 1
        for task in tasks.values { task.cancel() }
        tasks = [:]
        entries = [:]
        accessed = [:]
    }

    private func register(_ key: Data, start: Bool = true) {
        clock &+= 1
        accessed[key] = clock
        if entries[key] != nil { return }
        if entries.count >= 64, let oldest = entries.keys.min(by: { (accessed[$0] ?? 0) < (accessed[$1] ?? 0) }) {
            tasks.removeValue(forKey: oldest)?.cancel()
            entries.removeValue(forKey: oldest)
            accessed.removeValue(forKey: oldest)
        }
        var entry = Entry(inputs: inputs)
        entry.ephemeral = Self.isEphemeral(key)
        entries[key] = entry
        if start { refresh(key) }
    }

    private static func isEphemeral(_ key: Data) -> Bool {
        key.range(of: Data("\"kind\":\"capture_preview\"".utf8)) != nil
    }

    /// The most recently used queries a save refreshes right away.
    private func liveKeys() -> Set<Data> {
        let recent = entries.keys.filter { entries[$0]?.ephemeral != true }
            .sorted { (accessed[$0] ?? 0) > (accessed[$1] ?? 0) }
        return Set(recent.prefix(Self.liveQueryLimit))
    }

    /// A stale page that is read again is shown as it is and refreshed behind the read.
    private func revalidateOnRead(_ key: Data) {
        guard entries[key]?.stale == true, tasks[key] == nil, !pendingRefresh.contains(key) else { return }
        // Not inside the reading view's update pass.
        Task { [weak self] in
            guard let self, self.entries[key]?.stale == true else { return }
            self.refresh(key, keepingPage: true)
        }
    }

    private func refresh(_ key: Data, keepingPage: Bool = false) {
        guard tasks[key] == nil, var entry = entries[key] else { return }
        clock &+= 1
        entry.requestID = clock
        if !(keepingPage && entry.readiness == .ready && entry.page != nil) {
            entry.readiness = .loading
            entry.page = nil
        }
        entries[key] = entry
        let request = entry.requestID
        let dirtyVersion = entry.dirtyVersion
        let epoch = epoch
        let query = query
        let inputs = entry.inputs
        let cursor = entry.cursor
        tasks[key] = Task { [weak self] in
            let outcome: Result<RustWorkspaceAnswer, any Error>
            var prepared: RustPreparedPage?
            do {
                let request = try Self.pagedQuery(key, cursor: cursor)
                // Collection cursors are separate from the catalog's keyset
                // cursor; the bridge ignores them for list_mode/task_list.
                let answer = try await query(request, inputs, cursor)
                outcome = .success(answer)
                if case .answered(let page) = answer { prepared = await self?.decodeOffActor(key, page) }
            } catch { outcome = .failure(error) }
            self?.complete(key, request: request, dirtyVersion: dirtyVersion, epoch: epoch, outcome: outcome,
                           prepared: prepared)
        }
    }

    /// Decodes against a copy of the workspace's state off the main actor. When the state moved
    /// meanwhile (another page was adopted) it decodes again; a page still out of date after that
    /// reaches the workspace as it is and is decoded there.
    private func decodeOffActor(_ key: Data, _ page: RustWorkspacePage) async -> RustPreparedPage? {
        guard let decoding else { return nil }
        var prepared: RustPreparedPage?
        for _ in 0..<3 {
            guard let context = decoding.context() else { return nil }
            prepared = await Task.detached(priority: .userInitiated) {
                RustPreparedPage.decode(query: key, page: page, context: context)
            }.value
            guard let latest = prepared else { return nil }
            if latest.revision == decoding.revision() { break }
        }
        return prepared
    }

    private func complete(_ key: Data, request: UInt64, dirtyVersion: UInt64, epoch: UInt64,
                          outcome: Result<RustWorkspaceAnswer, any Error>, prepared: RustPreparedPage? = nil) {
        guard epoch == self.epoch, var entry = entries[key], request == entry.requestID else { return }
        tasks[key] = nil
        if dirtyVersion == entry.dirtyVersion { entry.stale = false }
        switch outcome {
        case .success(.answered(let page)):
            guard dirtyVersion == entry.dirtyVersion else { refreshIfLive(key); return }
            guard let generation = UInt64(page.projectionGeneration) else {
                entry.readiness = .failed("MALFORMED_QUERY_RESULT")
                entries[key] = entry
                return
            }
            guard generation >= generationFloor else {
                refresh(key, keepingPage: true)
                return
            }
            generationFloor = max(generationFloor, generation)
            do {
                if let prepared, let decoding { try decoding.publish(key, page, prepared) }
                else { try didPublish(key, page) }
            }
            catch {
                entry.readiness = .failed((error as? RustBridgeError)?.code ?? "MALFORMED_QUERY_RESULT")
                entries[key] = entry
                return
            }
            entry.page = page
            entry.readiness = .ready
            entry.stale = false
            entries[key] = entry
        case .success(.refused(let refusal, let generation)):
            guard dirtyVersion == entry.dirtyVersion else { refreshIfLive(key); return }
            if let generation, let number = UInt64(generation), number < generationFloor { refresh(key); return }
            entry.readiness = .failed(refusal.reason)
            entries[key] = entry
            if let generation, let number = UInt64(generation), number >= generationFloor { didRefuse(key, refusal) }
        case .failure(let error):
            if let bridge = error as? RustBridgeError, bridge.code == "QUERY_RESTART_REQUIRED" {
                entry.cursor = nil
                entry.history = []
                entry.inputs = inputs
                entries[key] = entry
                refresh(key)
                return
            }
            entry.readiness = .failed((error as? RustBridgeError)?.code ?? "QUERY_FAILED")
            entries[key] = entry
        }
        // An invalidation received while a failing request was suspended also
        // survives that completion and gets one fresh request.
        if dirtyVersion != entry.dirtyVersion { refreshIfLive(key) }
    }

    /// An answer that an invalidation overtook is dropped; the entry is asked again now when it is
    /// one of the queries in use, and otherwise stays stale until it is read.
    private func refreshIfLive(_ key: Data) {
        if entries[key]?.page == nil { refresh(key) }
        else if !pendingRefresh.contains(key), liveKeys().contains(key) { refresh(key, keepingPage: true) }
    }

    private static func nextCursor(_ page: RustWorkspacePage) -> String? {
        if let cursor = page.collectionNextCursor { return cursor }
        guard let root = try? JSONSerialization.jsonObject(with: page.result) as? [String: Any],
              let value = root["value"] as? [String: Any] else { return nil }
        return value["next_cursor"] as? String
    }

    private static func pagedQuery(_ data: Data, cursor: String?) throws -> Data {
        guard var root = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw RustDomainError.malformedResult
        }
        if var page = root["page"] as? [String: Any] {
            page["after"] = cursor.map { $0 as Any } ?? NSNull()
            root["page"] = page
        }
        return try JSONSerialization.data(withJSONObject: root, options: [.sortedKeys])
    }
}
