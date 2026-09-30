import BrainBuddyCore
import Foundation

@testable import BrainBuddyPersistence

#if canImport(Darwin)
import Darwin
#elseif canImport(Glibc)
import Glibc
#elseif canImport(Musl)
import Musl
#endif

enum Fixtures {
    /// Microsecond-exact, so it survives the JSON round trip unchanged.
    static let issuedAt = Date(timeIntervalSinceReferenceDate: 812_345_678.123456)
    static let createdAt = Date(timeIntervalSinceReferenceDate: 812_000_000.5)

    static func operation(_ index: Int, issuedAt: Date = issuedAt) -> PendingOperation {
        PendingOperation(
            command: .createTask(.init(taskID: TaskID("task-\(index)"), title: "Task \(index)", list: .inbox)),
            issuedAt: issuedAt
        )
    }

    /// A document that touches every stored type: records, the outbox,
    /// issues, the account and sync metadata.
    static func richDocument() -> StoreDocument {
        let projectID: ProjectID = "project-1"
        let tagID: TagID = "tag-1"
        let taskID: TaskID = "task-1"
        let task = TaskRecord(
            id: taskID, serverID: "task_1a2b3c4d5e6f", serverRevision: 3, title: "Call the plumber",
            details: "Before Friday", state: .waiting, projectID: projectID, tagIDs: [tagID],
            dueDate: CalendarDay(year: 2026, month: 10, day: 2), priority: .high, waitingFor: "Plumber",
            waitingSince: Date(timeIntervalSinceReferenceDate: 812_100_000.25), orderKey: 7,
            createdAt: createdAt, updatedAt: Date(timeIntervalSinceReferenceDate: 812_200_000.000001),
            subtasks: [SubtaskRecord(id: "subtask-1", title: "Find the number", orderKey: 0)],
            comments: [CommentRecord(id: "comment-1", body: "Left a message", authorID: "user_1", createdAt: createdAt)],
            childrenSyncedAt: createdAt
        )
        return StoreDocument(
            generation: 4,
            base: GTDState(
                tasks: [taskID: task],
                projects: [
                    projectID: ProjectRecord(
                        id: projectID, serverID: "project_1", serverRevision: 1, name: "Home", color: "#0EA5E9",
                        createdAt: createdAt
                    )
                ],
                tags: [tagID: TagRecord(id: tagID, name: "phone", createdAt: createdAt)]
            ),
            outbox: [
                operation(0),
                PendingOperation(
                    command: .transitionTask(.init(taskID: taskID, action: .complete)), issuedAt: issuedAt,
                    attempts: 2, firstAttemptAt: createdAt, lastAttemptAt: issuedAt, lastError: "timeout"
                ),
            ],
            issues: [
                SyncIssue(command: .deleteTag(tagID), message: "Not found", referenceID: "ref-1", occurredAt: createdAt)
            ],
            account: LinkedAccount(
                id: "user_1", email: "sam@example.com", displayName: "Sam",
                serverURL: URL(string: "https://brain-buddy-frontend.fly.dev/api")!, linkedAt: createdAt
            ),
            sync: SyncMetadata(lastPullAt: createdAt, lastPushAt: issuedAt)
        )
    }
}

struct Boom: Error, Equatable {}

/// A fresh, empty directory; pair it with `defer { removeTemporaryDirectory(directory) }`.
func makeTemporaryDirectory() throws -> URL {
    let directory = FileManager.default.temporaryDirectory
        .appendingPathComponent("BrainBuddyPersistenceTests-\(UUID().uuidString)", isDirectory: true)
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    return directory
}

func removeTemporaryDirectory(_ directory: URL) {
    try? FileManager.default.removeItem(at: directory)
}

/// The permission bits of a file, from `stat`.
func permissions(of url: URL) -> Int? {
    var info = stat()
    guard stat(url.path, &info) == 0 else { return nil }
    return Int(info.st_mode) & 0o777
}

func isUnreadable(_ error: DocumentStoreError?) -> Bool {
    if case .unreadable? = error { true } else { false }
}

func isIO(_ error: DocumentStoreError?) -> Bool {
    if case .io? = error { true } else { false }
}

/// A value shared with a plain thread.
final class LockedValue<Value: Sendable>: @unchecked Sendable {
    private let lock = NSLock()
    private var stored: Value

    init(_ value: Value) { stored = value }

    var value: Value {
        lock.lock()
        defer { lock.unlock() }
        return stored
    }

    func set(_ value: Value) {
        lock.lock()
        stored = value
        lock.unlock()
    }
}
