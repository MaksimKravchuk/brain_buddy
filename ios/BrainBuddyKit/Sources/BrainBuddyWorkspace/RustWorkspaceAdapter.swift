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
    }

    private(set) var entries: [Data: Entry] = [:]
    private(set) var generationFloor: UInt64 = 0
    @ObservationIgnored private var inputs: Data
    @ObservationIgnored private var epoch: UInt64 = 0
    @ObservationIgnored private var clock: UInt64 = 0
    @ObservationIgnored private var accessed: [Data: UInt64] = [:]
    @ObservationIgnored private var tasks: [Data: Task<Void, Never>] = [:]
    @ObservationIgnored private let query: @Sendable (Data, Data, String?) async throws -> RustWorkspaceAnswer
    @ObservationIgnored private let didPublish: @MainActor (Data, RustWorkspacePage) throws -> Void
    @ObservationIgnored private let didRefuse: @MainActor (Data, RustRefusal) -> Void

    init(inputs: Data,
         query: @escaping @Sendable (Data, Data, String?) async throws -> RustWorkspaceAnswer,
         didPublish: @escaping @MainActor (Data, RustWorkspacePage) throws -> Void,
         didRefuse: @escaping @MainActor (Data, RustRefusal) -> Void = { _, _ in }) {
        self.inputs = inputs
        self.query = query
        self.didPublish = didPublish
        self.didRefuse = didRefuse
    }

    func page(for query: Data) -> RustWorkspacePage? {
        register(query)
        guard entries[query]?.readiness == .ready else { return nil }
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
        while let task = tasks[query] {
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
        for key in Array(entries.keys) {
            guard var entry = entries[key] else { continue }
            entry.dirtyVersion &+= 1
            entry.inputs = inputs
            entry.cursor = nil
            entry.history = []
            entries[key] = entry
            refresh(key)
        }
    }

    func close() {
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
        entries[key] = Entry(inputs: inputs)
        if start { refresh(key) }
    }

    private func refresh(_ key: Data) {
        guard tasks[key] == nil, var entry = entries[key] else { return }
        clock &+= 1
        entry.requestID = clock
        entry.readiness = .loading
        entry.page = nil
        entries[key] = entry
        let request = entry.requestID
        let dirtyVersion = entry.dirtyVersion
        let epoch = epoch
        let query = query
        let inputs = entry.inputs
        let cursor = entry.cursor
        tasks[key] = Task { [weak self] in
            let outcome: Result<RustWorkspaceAnswer, any Error>
            do {
                let request = try Self.pagedQuery(key, cursor: cursor)
                // Collection cursors are separate from the catalog's keyset
                // cursor; the bridge ignores them for list_mode/task_list.
                outcome = .success(try await query(request, inputs, cursor))
            } catch { outcome = .failure(error) }
            self?.complete(key, request: request, dirtyVersion: dirtyVersion, epoch: epoch, outcome: outcome)
        }
    }

    private func complete(_ key: Data, request: UInt64, dirtyVersion: UInt64, epoch: UInt64,
                          outcome: Result<RustWorkspaceAnswer, any Error>) {
        guard epoch == self.epoch, var entry = entries[key], request == entry.requestID else { return }
        tasks[key] = nil
        switch outcome {
        case .success(.answered(let page)):
            guard dirtyVersion == entry.dirtyVersion else { refresh(key); return }
            guard let generation = UInt64(page.projectionGeneration) else {
                entry.readiness = .failed("MALFORMED_QUERY_RESULT")
                entries[key] = entry
                return
            }
            guard generation >= generationFloor else {
                refresh(key)
                return
            }
            generationFloor = max(generationFloor, generation)
            do { try didPublish(key, page) }
            catch {
                entry.readiness = .failed((error as? RustBridgeError)?.code ?? "MALFORMED_QUERY_RESULT")
                entries[key] = entry
                return
            }
            entry.page = page
            entry.readiness = .ready
            entries[key] = entry
        case .success(.refused(let refusal, let generation)):
            guard dirtyVersion == entry.dirtyVersion else { refresh(key); return }
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
        if dirtyVersion != entry.dirtyVersion { refresh(key) }
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
