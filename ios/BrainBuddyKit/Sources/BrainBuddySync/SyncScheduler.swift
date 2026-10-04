import Foundation
import Synchronization

/// Runs the engine's delayed work: the debounce after a local change and the
/// retry backoff. Production uses `TaskSyncScheduler`; tests use
/// `ManualSyncScheduler`, which never sleeps and runs work when told to.
public protocol SyncScheduler: Sendable {
    /// Runs `action` once after `delay`, unless the returned work is cancelled first.
    func schedule(after delay: Duration, _ action: @escaping @Sendable () async -> Void) -> SyncScheduledWork
}

/// A handle to scheduled work. Cancelling work that already ran does nothing.
public struct SyncScheduledWork: Sendable {
    private let cancelAction: @Sendable () -> Void

    public init(cancel: @escaping @Sendable () -> Void) { cancelAction = cancel }

    public func cancel() { cancelAction() }
}

/// Sleeps in a `Task`, then runs the action.
public struct TaskSyncScheduler: SyncScheduler {
    public init() {}

    public func schedule(after delay: Duration, _ action: @escaping @Sendable () async -> Void) -> SyncScheduledWork {
        let task = Task {
            do { try await Task.sleep(for: delay) } catch { return }
            await action()
        }
        return SyncScheduledWork { task.cancel() }
    }
}

/// A scheduler for tests and previews: work waits until `runNext()` or
/// `runAll()` runs it, in the order it was scheduled, and `pendingDelays`
/// shows what was asked for (for example the backoff sequence).
public final class ManualSyncScheduler: SyncScheduler {
    private struct Entry: Sendable {
        var id: Int
        var delay: Duration
        var action: @Sendable () async -> Void
    }

    private struct State: Sendable {
        var nextID = 0
        var entries: [Entry] = []
        var history: [Duration] = []
    }

    private let state = Mutex(State())

    public init() {}

    public func schedule(after delay: Duration, _ action: @escaping @Sendable () async -> Void) -> SyncScheduledWork {
        let id = state.withLock { state in
            state.nextID += 1
            state.entries.append(Entry(id: state.nextID, delay: delay, action: action))
            state.history.append(delay)
            return state.nextID
        }
        return SyncScheduledWork { [weak self] in
            self?.state.withLock { $0.entries.removeAll { $0.id == id } }
        }
    }

    /// Delays of the work still waiting, oldest first.
    public var pendingDelays: [Duration] { state.withLock { $0.entries.map(\.delay) } }

    /// Every delay ever scheduled, cancelled or not, oldest first.
    public var scheduledDelays: [Duration] { state.withLock { $0.history } }

    /// Runs the oldest waiting work to completion; false when nothing waits.
    @discardableResult
    public func runNext() async -> Bool {
        let entry = state.withLock { state -> Entry? in
            state.entries.isEmpty ? nil : state.entries.removeFirst()
        }
        guard let entry else { return false }
        await entry.action()
        return true
    }

    /// Runs waiting work (including work it schedules) until none is left,
    /// at most `limit` actions.
    public func runAll(limit: Int = 100) async {
        var count = 0
        while count < limit, await runNext() { count += 1 }
    }
}
