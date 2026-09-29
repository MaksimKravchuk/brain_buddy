import BrainBuddyCore
import BrainBuddyPersistence
import BrainBuddySync
import Foundation
import Synchronization
import Testing

@testable import BrainBuddyWorkspace

enum Fixture {
    /// 2026-09-28 in UTC, microsecond-exact, so it survives the store's JSON round trip.
    static let epoch = Date(timeIntervalSinceReferenceDate: 812_345_678.123456)
    static let serverURL = URL(string: "https://brain-buddy.example/api")!
    static let account = LinkedAccount(
        id: "user_1", email: "ana@example.com", displayName: "Ana", serverURL: serverURL, linkedAt: epoch
    )

    /// A task as the server confirmed it (it has a server id and revision).
    static func serverTask(
        _ id: TaskID, _ title: String, state: TaskState = .next, orderKey: Int = 0
    ) -> TaskRecord {
        TaskRecord(
            id: id, serverID: "task_\(id)", serverRevision: 1, title: title, state: state,
            completedAt: state == .completed ? epoch : nil, orderKey: orderKey,
            createdAt: epoch.addingTimeInterval(-3_600), updatedAt: epoch.addingTimeInterval(-3_600)
        )
    }

    static func base(_ tasks: [TaskRecord]) -> GTDState {
        GTDState(tasks: Dictionary(uniqueKeysWithValues: tasks.map { ($0.id, $0) }))
    }

    static func issue(_ message: String, id: UUID = UUID()) -> SyncIssue {
        SyncIssue(id: id, command: .deleteTag("tag-gone"), message: message, referenceID: "ref-9", occurredAt: epoch)
    }

    /// Bytes that are not a store document at all.
    static let garbage = Data("this is not a Brain Buddy store".utf8)
    /// A document header written by a newer app version.
    static let newerVersion = Data(#"{"version":99,"generation":7}"#.utf8)
}

/// A settable clock for `Workspace(now:)`.
final class TestClock: Sendable {
    private let current: Mutex<Date>

    init(_ start: Date = Fixture.epoch) {
        current = Mutex(start)
    }

    var now: Date { current.withLock { $0 } }

    func advance(by seconds: TimeInterval) {
        current.withLock { $0 = $0.addingTimeInterval(seconds) }
    }
}

/// Sequential UUIDs (`00000000-0000-0000-0000-000000000001`, …) for
/// `Workspace(makeID:)`. Workspaces standing for different processes on one
/// store use different namespaces (`…-0000-0002-…`), as random ids would differ.
final class IDSequence: Sendable {
    private let namespace: Int
    private let count = Mutex(0)

    init(namespace: Int = 0) {
        self.namespace = namespace
    }

    func next() -> UUID {
        let value = count.withLock { count in
            count += 1
            return count
        }
        return UUID(uuidString: "00000000-0000-0000-\(Self.pad(namespace, 4))-\(Self.pad(value, 12))")!
    }

    private static func pad(_ value: Int, _ width: Int) -> String {
        let digits = String(value)
        return String(repeating: "0", count: max(0, width - digits.count)) + digits
    }
}

/// Counts calls of `Workspace.didPersist`.
@MainActor
final class CallCounter {
    private(set) var count = 0
    func record() { count += 1 }
}

@MainActor
func makeWorkspace(
    store: any DocumentStore = InMemoryDocumentStore(), sync: (any SyncService)? = nil,
    clock: TestClock = TestClock(), ids: IDSequence = IDSequence()
) -> Workspace {
    Workspace(store: store, sync: sync, now: { clock.now }, makeID: { ids.next() })
}

/// A loaded workspace (by default over an empty in-memory store).
@MainActor
func loadedWorkspace(
    store: any DocumentStore = InMemoryDocumentStore(), sync: (any SyncService)? = nil,
    clock: TestClock = TestClock(), ids: IDSequence = IDSequence()
) async -> Workspace {
    let workspace = makeWorkspace(store: store, sync: sync, clock: clock, ids: ids)
    await workspace.load()
    return workspace
}

extension Workspace {
    /// What `state` must always equal.
    var replayedState: GTDState {
        OutboxReplayer.replay(document.outbox + unpersisted, onto: document.base).state
    }

    /// The single task whose title is `title`.
    func task(titled title: String) -> TaskRecord? {
        state.tasks.values.first { $0.title == title }
    }
}

/// Expects `body` to throw `expected` and to leave the workspace untouched.
@MainActor
func expectRejected(
    _ expected: GTDValidationError, in workspace: Workspace,
    sourceLocation: SourceLocation = #_sourceLocation,
    _ body: () throws -> Void
) {
    let state = workspace.state
    let unpersisted = workspace.unpersisted
    let pending = workspace.pendingChangeCount
    #expect(throws: expected, sourceLocation: sourceLocation) { try body() }
    #expect(workspace.state == state, sourceLocation: sourceLocation)
    #expect(workspace.unpersisted == unpersisted, sourceLocation: sourceLocation)
    #expect(workspace.pendingChangeCount == pending, sourceLocation: sourceLocation)
}

/// The ids of the tasks created in `outbox`, in order.
func createdTaskIDs(in outbox: [PendingOperation]) -> [TaskID] {
    outbox.compactMap { operation in
        guard case .createTask(let create) = operation.command else { return nil }
        return create.taskID
    }
}

/// A fresh, empty directory; pair it with `defer { removeTemporaryDirectory(directory) }`.
func makeTemporaryDirectory() throws -> URL {
    let directory = FileManager.default.temporaryDirectory
        .appendingPathComponent("BrainBuddyWorkspaceTests-\(UUID().uuidString)", isDirectory: true)
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    return directory
}

func removeTemporaryDirectory(_ directory: URL) {
    try? FileManager.default.removeItem(at: directory)
}
