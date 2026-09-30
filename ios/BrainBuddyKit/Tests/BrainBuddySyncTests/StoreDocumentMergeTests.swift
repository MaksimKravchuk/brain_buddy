import BrainBuddyAPI
import BrainBuddyCore
import Foundation
import Testing

@testable import BrainBuddySync

/// Writing a `GET /tasks/{id}` detail into the base.
@Suite("StoreDocument: merging a task detail")
struct StoreDocumentMergeTests {
    private let date = Date(timeIntervalSinceReferenceDate: 812_345_678)

    private func subtask(_ id: SubtaskID, _ serverID: String, revision: Int, title: String, order: Int) -> SubtaskRecord {
        SubtaskRecord(id: id, serverID: serverID, serverRevision: revision, title: title, orderKey: order)
    }

    private func comment(_ id: CommentID, _ serverID: String, revision: Int, body: String, minute: Int) -> CommentRecord {
        CommentRecord(
            id: id, serverID: serverID, serverRevision: revision, body: body, authorID: "user_1",
            createdAt: date.addingTimeInterval(Double(minute) * 60)
        )
    }

    private func document(subtasks: [SubtaskRecord], comments: [CommentRecord]) -> StoreDocument {
        let task = TaskRecord(
            id: "t", serverID: "task_1", serverRevision: 4, title: "Groceries", state: .next, orderKey: 0,
            createdAt: date, updatedAt: date, subtasks: subtasks, comments: comments, childrenSyncedAt: date
        )
        return StoreDocument(base: GTDState(tasks: ["t": task]))
    }

    private func detail(subtasks: [SubtaskDTO], comments: [CommentDTO]) -> TaskDTO {
        TaskDTO(
            id: "task_1", title: "Groceries", state: .next, orderKey: 0, createdAt: date, updatedAt: date, revision: 4,
            subtasks: subtasks, comments: comments
        )
    }

    @Test("A late detail never replaces a newer child, and keeps children acknowledged while it was read")
    func lateDetailKeepsNewerChildren() throws {
        var doc = document(
            subtasks: [
                subtask("renamed", "sub_1", revision: 3, title: "Oat milk", order: 0),
                subtask("acked", "sub_2", revision: 1, title: "Bread", order: 1),
                subtask("gone", "sub_3", revision: 1, title: "Eggs", order: 2),
            ],
            comments: [
                comment("edited", "com_1", revision: 2, body: "Before six", minute: 0),
                comment("posted", "com_2", revision: 1, body: "Cash only", minute: 1),
            ]
        )
        // The read started before sub_2 and com_2 were acknowledged, and
        // answers with sub_1 and com_1 as they were before this device's edits.
        let known = KnownChildren(
            TaskRecord(
                id: "t", title: "", state: .next, orderKey: 0, createdAt: date, updatedAt: date,
                subtasks: [
                    subtask("renamed", "sub_1", revision: 2, title: "Milk", order: 0),
                    subtask("gone", "sub_3", revision: 1, title: "Eggs", order: 2),
                ],
                comments: [comment("edited", "com_1", revision: 1, body: "Before five", minute: 0)]
            )
        )
        let late = detail(
            subtasks: [
                SubtaskDTO(id: "sub_1", title: "Milk", state: .open, orderKey: 0, revision: 2),
                SubtaskDTO(id: "sub_9", title: "Butter", state: .open, orderKey: 5, revision: 1),
            ],
            comments: [CommentDTO(id: "com_1", body: "Before five", actorID: "user_1", createdAt: date, revision: 1)]
        )

        doc.upsert(task: late, children: .replace(date, known: known), now: date)

        let task = try #require(doc.base.tasks["t"])
        #expect(task.subtasks.map(\.serverID) == ["sub_1", "sub_2", "sub_9"], "sub_3 was deleted on the server")
        #expect(task.subtasks.first?.title == "Oat milk", "revision 3 beats the detail's 2")
        #expect(task.subtasks.first?.id == "renamed")
        #expect(task.subtasks[1].id == "acked", "acknowledged after the read started")
        #expect(task.comments.map(\.serverID) == ["com_1", "com_2"])
        #expect(task.comments.first?.body == "Before six")
        #expect(task.comments.last?.id == "posted")
    }

    @Test("A current detail replaces the children, dropping those the server no longer has")
    func currentDetailReplacesChildren() throws {
        var doc = document(
            subtasks: [subtask("a", "sub_1", revision: 1, title: "Milk", order: 0)],
            comments: [comment("c", "com_1", revision: 1, body: "Note", minute: 0)]
        )
        let known = KnownChildren(doc.base.tasks["t"])
        let current = detail(
            subtasks: [
                SubtaskDTO(id: "sub_2", title: "Bread", state: .open, orderKey: 1, revision: 1),
                SubtaskDTO(id: "sub_1", title: "Oat milk", state: .completed, orderKey: 0, revision: 3),
            ],
            comments: []
        )

        doc.upsert(task: current, children: .replace(date, known: known), now: date)

        let task = try #require(doc.base.tasks["t"])
        #expect(task.subtasks.map(\.serverID) == ["sub_1", "sub_2"])
        #expect(task.subtasks.first?.id == "a", "the client id stays")
        #expect(task.subtasks.first?.title == "Oat milk")
        #expect(task.subtasks.first?.state == .completed)
        #expect(task.comments.isEmpty)
        #expect(task.childrenSyncedAt == date)
    }
}
