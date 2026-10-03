import XCTest
@testable import BrainBuddyMac

@MainActor
final class LocalGTDStoreTests: XCTestCase {
    private func makeURL() throws -> URL {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("BrainBuddyLocalTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }
        return root.appendingPathComponent("private", isDirectory: true)
            .appendingPathComponent("tasks.json")
    }

    func testLocalCRUDAndHistorySurviveRestart() async throws {
        let url = try makeURL()
        let store = LocalGTDStore(fileURL: url)
        let project = try await store.createProject(name: "House move", idempotencyKey: UUID())
        let tag = try await store.createTag(name: "home", idempotencyKey: UUID())
        let created = try await store.smartAddTask(
            title: "Confirm transfer", details: "Ask the insurer", state: .next,
            waitingFor: nil, dueDate: "2026-10-03", priority: .high,
            project: .id(project.id), tags: [.id(tag.id)], idempotencyKey: UUID()
        )
        let task = created.task
        XCTAssertEqual(task.project_id, project.id)
        XCTAssertEqual(task.tag_ids, [tag.id])

        let subtask = try await store.createSubtask(taskID: task.id, title: "Get policy number", idempotencyKey: UUID())
        _ = try await store.transitionSubtask(taskID: task.id, subtask: subtask, action: .complete, idempotencyKey: UUID())
        let comment = try await store.createComment(taskID: task.id, body: "Called Tuesday", idempotencyKey: UUID())
        _ = try await store.updateComment(taskID: task.id, comment: comment, body: "Called Wednesday", idempotencyKey: UUID())
        let withChildren = try await store.getTask(task.id)
        XCTAssertEqual(withChildren.subtasks.first?.state, "completed")
        XCTAssertEqual(withChildren.comments.first?.body, "Called Wednesday")

        let edited = try await store.updateTask(
            withChildren,
            changes: TaskChanges(details: .set("Confirmed by email")),
            idempotencyKey: UUID()
        )
        let completed = try await store.completeTask(edited, idempotencyKey: UUID())
        XCTAssertEqual(completed.last_open_state, .next)

        let reopenedStore = LocalGTDStore(fileURL: url)
        let persisted = try await reopenedStore.getTask(task.id)
        XCTAssertEqual(persisted.details, "Confirmed by email")
        XCTAssertEqual(persisted.comments.first?.body, "Called Wednesday")
        XCTAssertEqual(persisted.state, "completed")
        let nextPage = try await reopenedStore.listTasks(
            query: TaskQuery(state: .next, includeCompleted: true)
        )
        XCTAssertEqual(nextPage.items.map(\.id), [task.id])
        XCTAssertEqual(nextPage.counts_by_state?.total, 0)
        let projects = try await reopenedStore.listProjects()
        XCTAssertEqual(projects.first?.open_task_count, 0)

        let directoryMode = try FileManager.default.attributesOfItem(
            atPath: url.deletingLastPathComponent().path
        )[.posixPermissions] as? NSNumber
        let fileMode = try FileManager.default.attributesOfItem(atPath: url.path)[.posixPermissions] as? NSNumber
        XCTAssertEqual(directoryMode?.intValue, 0o700)
        XCTAssertEqual(fileMode?.intValue, 0o600)
    }

    func testWaitingCompletionAndReopenSurviveOfflineRestart() async throws {
        let url = try makeURL()
        let store = LocalGTDStore(fileURL: url)
        let waiting = try await store.createTask(
            title: "Hear from insurer", state: .waiting,
            waitingFor: "Insurer", idempotencyKey: UUID()
        )
        XCTAssertEqual(waiting.waiting_for, "Insurer")
        do {
            _ = try await store.transitionTask(
                waiting, action: .move, toState: .waiting,
                waitingFor: "Insurer", idempotencyKey: UUID()
            )
            XCTFail("Same-state move must not reset the Waiting clock")
        } catch let error as APIError {
            XCTAssertTrue(error.message.contains("different open destination"))
        }
        let unchanged = try await store.getTask(waiting.id)
        XCTAssertEqual(unchanged.revision, waiting.revision)
        XCTAssertEqual(unchanged.waiting_since, waiting.waiting_since)
        let completed = try await store.completeTask(waiting, idempotencyKey: UUID())
        XCTAssertEqual(completed.last_open_state, .waiting)
        XCTAssertNil(completed.waiting_for)
        XCTAssertNil(completed.waiting_since)

        let reopenedStore = LocalGTDStore(fileURL: url)
        let persisted = try await reopenedStore.getTask(waiting.id)
        XCTAssertEqual(persisted.state, "completed")
        XCTAssertNil(persisted.waiting_for)
        XCTAssertNil(persisted.waiting_since)
        do {
            _ = try await reopenedStore.transitionTask(
                persisted, action: .reopen, toState: .waiting,
                idempotencyKey: UUID()
            )
            XCTFail("Reopening into Waiting requires a person or condition")
        } catch let error as APIError {
            XCTAssertTrue(error.message.contains("Waiting tasks require"))
        }
        let reopened = try await reopenedStore.transitionTask(
            persisted, action: .reopen, toState: .waiting,
            waitingFor: "Insurer", idempotencyKey: UUID()
        )
        XCTAssertEqual(reopened.state, "waiting")
        XCTAssertEqual(reopened.waiting_for, "Insurer")
        XCTAssertNotNil(reopened.waiting_since)
        XCTAssertNil(reopened.completed_at)

        let cancelled = try await reopenedStore.transitionTask(
            reopened, action: .cancel, idempotencyKey: UUID()
        )
        XCTAssertEqual(cancelled.state, "cancelled")
        XCTAssertEqual(cancelled.last_open_state, .waiting)
        XCTAssertNil(cancelled.waiting_for)
        XCTAssertNil(cancelled.waiting_since)
        let cancelledAfterRestart = try await LocalGTDStore(fileURL: url).getTask(waiting.id)
        XCTAssertNil(cancelledAfterRestart.waiting_for)
        XCTAssertNil(cancelledAfterRestart.waiting_since)
    }

    func testSmartAddReplayAndConflictingKeyAfterOfflineRestart() async throws {
        let url = try makeURL()
        let key = UUID()
        let store = LocalGTDStore(fileURL: url)
        let created = try await store.smartAddTask(
            title: "Email insurer", state: .next,
            project: .name("House move"), tags: [.name("home")],
            idempotencyKey: key
        )
        let fileBeforeReplay = try Data(contentsOf: url)
        let reopened = LocalGTDStore(fileURL: url)
        let replay = try await reopened.smartAddTask(
            title: "Email insurer", state: .next,
            project: .name("House move"), tags: [.name("home")],
            idempotencyKey: key
        )
        XCTAssertEqual(replay.task.id, created.task.id)
        XCTAssertEqual(replay.created.project_id, created.created.project_id)
        XCTAssertEqual(replay.created.tag_ids, created.created.tag_ids)
        XCTAssertEqual(try Data(contentsOf: url), fileBeforeReplay)

        do {
            _ = try await reopened.smartAddTask(
                title: "Book a van", state: .next,
                project: .name("House move"), tags: [.name("home")],
                idempotencyKey: key
            )
            XCTFail("A changed capture must not be reported as the earlier task")
        } catch let error as APIError {
            XCTAssertEqual(error.statusCode, 409)
        }
        XCTAssertEqual(try Data(contentsOf: url), fileBeforeReplay)
        let remaining = try await reopened.listTasks(state: .next)
        XCTAssertEqual(remaining.items.map(\.id), [created.task.id])
    }

    func testEditedTaskAndNestedCommandReplayOriginalResultAfterRestart() async throws {
        let url = try makeURL()
        let store = LocalGTDStore(fileURL: url)
        let original = try await store.createTask(
            title: "Book a van", state: .next, waitingFor: nil, idempotencyKey: UUID()
        )
        let editKey = UUID()
        let edit = TaskChanges(details: .set("Call on Monday"))
        let edited = try await store.updateTask(original, changes: edit, idempotencyKey: editKey)
        let commentKey = UUID()
        let comment = try await store.createComment(
            taskID: original.id, body: "Need a quote", idempotencyKey: commentKey
        )
        let later = try await store.completeTask(
            try await store.getTask(original.id), idempotencyKey: UUID()
        )
        XCTAssertEqual(later.state, "completed")

        let reopened = LocalGTDStore(fileURL: url)
        let fileBeforeReplay = try Data(contentsOf: url)
        let editReplay = try await reopened.updateTask(original, changes: edit, idempotencyKey: editKey)
        let commentReplay = try await reopened.createComment(
            taskID: original.id, body: "Need a quote", idempotencyKey: commentKey
        )
        XCTAssertEqual(editReplay.revision, edited.revision)
        XCTAssertEqual(editReplay.state, "next")
        XCTAssertEqual(commentReplay.id, comment.id)
        XCTAssertEqual(try Data(contentsOf: url), fileBeforeReplay)
        do {
            _ = try await reopened.createComment(
                taskID: original.id, body: "Different body", idempotencyKey: editKey
            )
            XCTFail("One key cannot identify two different commands")
        } catch let error as APIError {
            XCTAssertEqual(error.statusCode, 409)
        }
        XCTAssertEqual(try Data(contentsOf: url), fileBeforeReplay)
    }

    func testCollectionReplayRetainsOriginalResponseAndRejectsChangedName() async throws {
        let url = try makeURL()
        let store = LocalGTDStore(fileURL: url)
        let createKey = UUID()
        let project = try await store.createProject(name: "House move", idempotencyKey: createKey)
        let renameKey = UUID()
        let renamed = try await store.renameProject(project, to: "New home", idempotencyKey: renameKey)
        XCTAssertEqual(renamed.revision, 2)

        let reopened = LocalGTDStore(fileURL: url)
        let fileBeforeReplay = try Data(contentsOf: url)
        let createReplay = try await reopened.createProject(name: "House move", idempotencyKey: createKey)
        let renameReplay = try await reopened.renameProject(project, to: "New home", idempotencyKey: renameKey)
        XCTAssertEqual(createReplay.id, project.id)
        XCTAssertEqual(createReplay.name, "House move")
        XCTAssertEqual(renameReplay.name, "New home")
        XCTAssertEqual(try Data(contentsOf: url), fileBeforeReplay)
        do {
            _ = try await reopened.createProject(name: "Another home", idempotencyKey: createKey)
            XCTFail("Changing a collection payload must not replay an earlier project")
        } catch let error as APIError {
            XCTAssertEqual(error.statusCode, 409)
        }
        XCTAssertEqual(try Data(contentsOf: url), fileBeforeReplay)
    }

    func testLocalCollectionAndCommentLengthsMatchEditorLimits() async throws {
        let store = LocalGTDStore(fileURL: try makeURL())
        let projectName = String(repeating: "P", count: 500)
        let tagName = String(repeating: "T", count: 500)
        let project = try await store.createProject(name: projectName, idempotencyKey: UUID())
        let tag = try await store.createTag(name: tagName, idempotencyKey: UUID())
        XCTAssertEqual(project.name.count, 500)
        XCTAssertEqual(tag.name.count, 500)
        let renamedProject = try await store.renameProject(
            project, to: String(repeating: "Q", count: 500), idempotencyKey: UUID()
        )
        let renamedTag = try await store.renameTag(
            tag, to: String(repeating: "U", count: 500), idempotencyKey: UUID()
        )
        XCTAssertEqual(renamedProject.name.count, 500)
        XCTAssertEqual(renamedTag.name.count, 500)

        let task = try await store.smartAddTask(
            title: "Capture", state: .next,
            project: .name(String(repeating: "R", count: 500)),
            tags: [.name(String(repeating: "V", count: 500))],
            idempotencyKey: UUID()
        ).task
        let comment = try await store.createComment(
            taskID: task.id, body: String(repeating: "a", count: 20_000), idempotencyKey: UUID()
        )
        XCTAssertEqual(comment.body.count, 20_000)
        let updated = try await store.updateComment(
            taskID: task.id, comment: comment,
            body: String(repeating: "b", count: 20_000), idempotencyKey: UUID()
        )
        XCTAssertEqual(updated.body.count, 20_000)
        do {
            _ = try await store.createComment(
                taskID: task.id, body: String(repeating: "c", count: 20_001), idempotencyKey: UUID()
            )
            XCTFail("Local comments must keep the UI's 20,000-character upper bound")
        } catch let error as APIError {
            XCTAssertTrue(error.message.contains("20000"))
        }
    }

    func testSecondOpenStoreCannotOverwriteNewerOfflineTasks() async throws {
        let url = try makeURL()
        let first = LocalGTDStore(fileURL: url)
        let second = LocalGTDStore(fileURL: url)
        let created = try await first.createTask(
            title: "Keep this task", state: .inbox, waitingFor: nil, idempotencyKey: UUID()
        )
        let fileBeforeAttempt = try Data(contentsOf: url)
        do {
            _ = try await second.createTask(
                title: "Stale writer", state: .inbox, waitingFor: nil, idempotencyKey: UUID()
            )
            XCTFail("A stale store must not replace a newer local snapshot")
        } catch let error as APIError {
            XCTAssertEqual(error.statusCode, 409)
        }
        XCTAssertEqual(try Data(contentsOf: url), fileBeforeAttempt)
        let reopened = LocalGTDStore(fileURL: url)
        let tasks = try await reopened.listTasks(state: .inbox)
        XCTAssertEqual(tasks.items.map(\.id), [created.id])
    }

    func testTransitionReplayRejectsChangedWaitingTarget() async throws {
        let url = try makeURL()
        let store = LocalGTDStore(fileURL: url)
        let task = try await store.createTask(
            title: "Book a van", state: .next, waitingFor: nil, idempotencyKey: UUID()
        )
        let key = UUID()
        _ = try await store.transitionTask(task, action: .move, toState: .inbox, idempotencyKey: key)
        let reopened = LocalGTDStore(fileURL: url)
        let fileBeforeAttempt = try Data(contentsOf: url)
        do {
            _ = try await reopened.transitionTask(
                task, action: .move, toState: .inbox,
                waitingFor: "Insurer", idempotencyKey: key
            )
            XCTFail("A changed transition body must not replay the prior success")
        } catch let error as APIError {
            XCTAssertEqual(error.statusCode, 409)
        }
        XCTAssertEqual(try Data(contentsOf: url), fileBeforeAttempt)
    }

    func testCorruptSnapshotIsNeverReplacedByNewWrites() async throws {
        let url = try makeURL()
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let corrupt = Data("not json".utf8)
        try corrupt.write(to: url)
        let store = LocalGTDStore(fileURL: url)
        do {
            _ = try await store.createTask(title: "Must not be saved", state: .inbox, waitingFor: nil, idempotencyKey: UUID())
            XCTFail("Corrupt local data must reject writes")
        } catch {
            XCTAssertTrue(error.localizedDescription.contains("could not be read"))
        }
        XCTAssertEqual(try Data(contentsOf: url), corrupt)
    }

    func testFailedDiskWriteDoesNotChangeInMemoryState() async throws {
        let root = try makeURL().deletingLastPathComponent().deletingLastPathComponent()
        let occupied = root.appendingPathComponent("occupied")
        try Data("file".utf8).write(to: occupied)
        let store = LocalGTDStore(fileURL: occupied.appendingPathComponent("tasks.json"))
        do {
            _ = try await store.createTask(title: "Unsaved", state: .inbox, waitingFor: nil, idempotencyKey: UUID())
            XCTFail("Disk write should fail")
        } catch { }
        let page = try await store.listTasks(state: .inbox)
        XCTAssertTrue(page.items.isEmpty)
    }

    func testProjectArchiveAndRestoreKeepEveryTaskMembership() async throws {
        let url = try makeURL()
        let store = LocalGTDStore(fileURL: url)
        let project = try await store.createProject(name: "House move", idempotencyKey: UUID())
        func member(_ title: String) async throws -> BrainBuddyTask {
            try await store.smartAddTask(
                title: title, state: .next,
                project: .id(project.id), idempotencyKey: UUID()
            ).task
        }
        let open = try await member("Book van")
        let completed = try await store.completeTask(try await member("Get quote"), idempotencyKey: UUID())
        let cancelled = try await store.transitionTask(
            try await member("Old plan"), action: .cancel, idempotencyKey: UUID()
        )

        let archived = try await store.archiveProject(project, idempotencyKey: UUID())
        XCTAssertEqual(archived.state, "archived")
        let activeProjects = try await store.listProjects()
        let archivedProjects = try await store.listArchivedProjects()
        XCTAssertTrue(activeProjects.isEmpty)
        XCTAssertEqual(archivedProjects.map(\.id), [project.id])
        for id in [open.id, completed.id, cancelled.id] {
            let member = try await store.getTask(id)
            XCTAssertEqual(member.project_id, project.id)
        }
        let archivedView = try await store.listTasks(query: TaskQuery(
            projectID: project.id, includeCompleted: true, includeCancelled: true
        ))
        XCTAssertEqual(Set(archivedView.items.map(\.id)), Set([open.id, completed.id, cancelled.id]))
        do {
            _ = try await store.smartAddTask(
                title: "New assignment", state: .next,
                project: .id(project.id), idempotencyKey: UUID()
            )
            XCTFail("Archived projects must not accept new tasks")
        } catch let error as APIError {
            XCTAssertEqual(error.statusCode, 404)
        }
        do {
            _ = try await store.createProject(name: project.name, idempotencyKey: UUID())
            XCTFail("A duplicate active name would prevent restoring the archive")
        } catch let error as APIError {
            XCTAssertEqual(error.statusCode, 409)
        }

        let reopenedStore = LocalGTDStore(fileURL: url)
        let savedArchives = try await reopenedStore.listArchivedProjects()
        let restored = try await reopenedStore.unarchiveProject(
            try XCTUnwrap(savedArchives.first),
            idempotencyKey: UUID()
        )
        XCTAssertEqual(restored.state, "active")
        let restoredProjects = try await reopenedStore.listProjects()
        XCTAssertEqual(restoredProjects.map(\.id), [project.id])
        for id in [open.id, completed.id, cancelled.id] {
            let member = try await reopenedStore.getTask(id)
            XCTAssertEqual(member.project_id, project.id)
        }
    }
}
