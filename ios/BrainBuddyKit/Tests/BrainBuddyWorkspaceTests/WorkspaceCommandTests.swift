import BrainBuddyCore
import BrainBuddyPersistence
import Foundation
import Testing

@testable import BrainBuddyWorkspace

/// Every command method: applied at once in memory with the injected clock
/// and ids, queued for the store, and rejected without side effects.
@MainActor
@Suite struct WorkspaceCommandTests {
    // MARK: Capture

    @Test func offlineSmartAddCaptureCreatesTheProjectTagAndTask() async throws {
        let store = InMemoryDocumentStore()
        let workspace = await loadedWorkspace(store: store)

        let taskID = try workspace.capture(CaptureDraft(text: "Call the plumber #home @Renovation", list: .next))

        // In memory at once, before anything is written.
        let task = try #require(workspace.task(taskID))
        #expect(task.title == "Call the plumber")
        #expect(task.state == .next)
        #expect(task.createdAt == Fixture.epoch)
        let project = try #require(task.projectID.flatMap(workspace.project))
        #expect(project.name == "Renovation")
        #expect(task.tagIDs.compactMap { workspace.tag($0)?.name } == ["home"])
        #expect(workspace.pendingChangeCount == 3)
        #expect(workspace.unpersisted.map(\.issuedAt) == Array(repeating: Fixture.epoch, count: 3))

        await workspace.flush()

        let stored = try #require(try await store.load())
        let commands = stored.outbox.map(\.command)
        #expect(commands.count == 3)
        guard case .createProject(let createProject) = commands[0], case .createTag(let createTag) = commands[1],
            case .createTask(let createTask) = commands[2]
        else {
            Issue.record("Expected createProject, createTag, createTask; got \(commands)")
            return
        }
        #expect(createProject.name == "Renovation")
        #expect(createTag.name == "home")
        #expect(createTask.projectID == createProject.projectID)
        #expect(createTask.tagIDs == [createTag.tagID])
        #expect(stored == workspace.document)
        #expect(workspace.unpersisted.isEmpty)
        #expect(workspace.pendingChangeCount == 3)
        #expect(OutboxReplayer.replay(stored.outbox, onto: stored.base).state == workspace.state)
    }

    @Test func captureUsesExistingProjectsAndTagsAndMintsDistinctIDs() async throws {
        let workspace = await loadedWorkspace()
        let first = try workspace.capture(CaptureDraft(text: "Paint the hall @Home #errands"))
        let second = try workspace.capture(CaptureDraft(text: "Buy brushes @home #Errands"))

        #expect(first != second)
        #expect(workspace.state.projects.count == 1)
        #expect(workspace.state.tags.count == 1)
        #expect(workspace.task(first)?.projectID == workspace.task(second)?.projectID)
        #expect(workspace.pendingChangeCount == 4)
    }

    @Test func captureRejectsABlankTitleAndAWaitingTaskWithoutANote() async {
        let workspace = await loadedWorkspace()

        expectRejected(.emptyTitle, in: workspace) { _ = try workspace.capture(CaptureDraft(text: "   ")) }
        expectRejected(.waitingForRequired, in: workspace) {
            _ = try workspace.capture(CaptureDraft(text: "Quote @New #tag", list: .waiting))
        }
        // All or nothing: the project and tag the draft would create are not there either.
        #expect(workspace.state == .empty)
    }

    // MARK: Tasks

    @Test func updateTaskEditsFieldsAndRejectsAnEmptyTitle() async throws {
        let workspace = await loadedWorkspace()
        let id = try workspace.capture(CaptureDraft(text: "Call Ana"))
        let due = try #require(CalendarDay(year: 2026, month: 10, day: 2))

        try workspace.updateTask(
            id, TaskChanges(title: .set("Call Ana back"), details: .set("About the quote"), dueDate: .set(due),
                priority: .set(.high))
        )

        let task = try #require(workspace.task(id))
        #expect(task.title == "Call Ana back")
        #expect(task.details == "About the quote")
        #expect(task.dueDate == due)
        #expect(task.priority == .high)
        expectRejected(.emptyTitle, in: workspace) { try workspace.updateTask(id, TaskChanges(title: .clear)) }
        expectRejected(.taskNotFound, in: workspace) {
            try workspace.updateTask("missing", TaskChanges(title: .set("x")))
        }
    }

    @Test func moveTaskChangesTheListAndRejectsTheSameList() async throws {
        let workspace = await loadedWorkspace()
        let id = try workspace.capture(CaptureDraft(text: "Venue quote"))

        try workspace.moveTask(id, to: .waiting, waitingFor: "  Harbour Hall  ")

        let task = try #require(workspace.task(id))
        #expect(task.state == .waiting)
        #expect(task.waitingFor == "Harbour Hall")
        #expect(task.waitingSince == Fixture.epoch)
        expectRejected(.moveRequiresDifferentList, in: workspace) {
            try workspace.moveTask(id, to: .waiting, waitingFor: "Someone else")
        }
        let other = try workspace.capture(CaptureDraft(text: "Other"))
        expectRejected(.waitingForRequired, in: workspace) { try workspace.moveTask(other, to: .waiting) }
    }

    @Test func completeTaskFinishesAnOpenTaskOnlyOnce() async throws {
        let clock = TestClock()
        let workspace = await loadedWorkspace(clock: clock)
        let id = try workspace.capture(CaptureDraft(text: "Measure the walls", list: .next))
        clock.advance(by: 90)

        try workspace.completeTask(id)

        let task = try #require(workspace.task(id))
        #expect(task.state == .completed)
        #expect(task.lastOpenList == .next)
        #expect(task.completedAt == Fixture.epoch.addingTimeInterval(90))
        expectRejected(.taskNotOpen, in: workspace) { try workspace.completeTask(id) }
    }

    @Test func cancelTaskDropsATaskAndRejectsAnUnknownOne() async throws {
        let workspace = await loadedWorkspace()
        let id = try workspace.capture(CaptureDraft(text: "Order blue tiles", list: .someday))

        try workspace.cancelTask(id)

        #expect(workspace.task(id)?.state == .cancelled)
        #expect(workspace.list(.history(.cancelled)).openCount == 0)
        #expect(workspace.list(.history(.cancelled)).sections.flatMap(\.tasks).map(\.id) == [id])
        expectRejected(.taskNotFound, in: workspace) { try workspace.cancelTask("missing") }
    }

    @Test func reopenTaskReturnsATaskToAChosenListAndRejectsAnOpenOne() async throws {
        let workspace = await loadedWorkspace()
        let id = try workspace.capture(CaptureDraft(text: "Send the poll", list: .next))
        try workspace.completeTask(id)

        try workspace.reopenTask(id, to: .someday)

        #expect(workspace.task(id)?.state == .someday)
        #expect(workspace.task(id)?.completedAt == nil)
        expectRejected(.taskNotClosed, in: workspace) { try workspace.reopenTask(id, to: .next) }
    }

    // MARK: Subtasks and comments

    @Test func subtasksCanBeAddedRenamedAndTransitioned() async throws {
        let workspace = await loadedWorkspace()
        let taskID = try workspace.capture(CaptureDraft(text: "Draft the agenda"))

        let subtaskID = try workspace.addSubtask(to: taskID, title: "List sessions")
        try workspace.renameSubtask(subtaskID, in: taskID, to: "List possible sessions")
        try workspace.transitionSubtask(subtaskID, in: taskID, .complete)

        let subtask = try #require(workspace.task(taskID)?.subtasks.first)
        #expect(subtask.id == subtaskID)
        #expect(subtask.title == "List possible sessions")
        #expect(subtask.state == .completed)
        expectRejected(.emptyTitle, in: workspace) { _ = try workspace.addSubtask(to: taskID, title: " ") }
        expectRejected(.subtaskNotFound, in: workspace) {
            try workspace.renameSubtask("missing", in: taskID, to: "Anything")
        }
        expectRejected(.subtaskAlreadyInState, in: workspace) {
            try workspace.transitionSubtask(subtaskID, in: taskID, .complete)
        }
    }

    @Test func commentsCanBeAddedAndEdited() async throws {
        let clock = TestClock()
        let workspace = await loadedWorkspace(clock: clock)
        let taskID = try workspace.capture(CaptureDraft(text: "Draft the agenda"))

        let commentID = try workspace.addComment(to: taskID, body: "Priya prefers day one.")
        clock.advance(by: 60)
        try workspace.editComment(commentID, in: taskID, body: "Priya prefers the first day.")

        let comment = try #require(workspace.task(taskID)?.comments.first)
        #expect(comment.id == commentID)
        #expect(comment.body == "Priya prefers the first day.")
        #expect(comment.createdAt == Fixture.epoch)
        #expect(comment.editedAt == Fixture.epoch.addingTimeInterval(60))
        #expect(workspace.isOwnComment(comment))
        expectRejected(.emptyComment, in: workspace) { _ = try workspace.addComment(to: taskID, body: "") }
        expectRejected(.commentNotFound, in: workspace) {
            try workspace.editComment("missing", in: taskID, body: "Anything")
        }
    }

    // MARK: Projects

    @Test func createProjectAddsAnActiveProjectAndRejectsADuplicateName() async throws {
        let workspace = await loadedWorkspace()

        let id = try workspace.createProject(name: "Home", color: "#0EA5E9")

        #expect(workspace.project(id)?.name == "Home")
        #expect(workspace.project(id)?.color == "#0EA5E9")
        #expect(workspace.projects().map(\.id) == [id])
        #expect(workspace.projects().first?.needsNextAction == true)
        expectRejected(.duplicateProjectName("Home"), in: workspace) { _ = try workspace.createProject(name: " home ") }
    }

    @Test func renameProjectAndSetProjectColor() async throws {
        let workspace = await loadedWorkspace()
        let id = try workspace.createProject(name: "Kitchen")

        try workspace.renameProject(id, to: "Kitchen renovation")
        try workspace.setProjectColor(id, color: "#22C55E")
        #expect(workspace.project(id)?.name == "Kitchen renovation")
        #expect(workspace.project(id)?.color == "#22C55E")

        try workspace.setProjectColor(id, color: nil)
        #expect(workspace.project(id)?.color == nil)
        expectRejected(.emptyName, in: workspace) { try workspace.renameProject(id, to: "   ") }
        expectRejected(.colorTooLong, in: workspace) {
            try workspace.setProjectColor(id, color: String(repeating: "f", count: 65))
        }
    }

    @Test("021-FR-024 archiving keeps the project on its tasks, and the project can be unarchived")
    func archiveProjectKeepsItsTasksAndUnarchiveRestoresIt() async throws {
        let workspace = await loadedWorkspace()
        let taskID = try workspace.capture(CaptureDraft(text: "Clear the beds @Garden", list: .next))
        let projectID = try #require(workspace.task(taskID)?.projectID)

        try workspace.archiveProject(projectID)

        #expect(workspace.project(projectID)?.state == .archived)
        #expect(workspace.task(taskID)?.projectID == projectID)
        #expect(workspace.task(taskID)?.state == .next)
        #expect(workspace.projects(archived: true).map(\.id) == [projectID])
        expectRejected(.projectAlreadyArchived, in: workspace) { try workspace.archiveProject(projectID) }

        try workspace.unarchiveProject(projectID)
        #expect(workspace.project(projectID)?.state == .active && workspace.project(projectID)?.archivedAt == nil)
        #expect(workspace.task(taskID)?.projectID == projectID)
        expectRejected(.nothingToChange, in: workspace) { try workspace.unarchiveProject(projectID) }
    }

    @Test("021-FR-025 021-FR-026 an unarchive is refused while another active project has the name")
    func unarchiveRefusedForATakenName() async throws {
        let workspace = await loadedWorkspace()
        let first = try workspace.createProject(name: "Shed")
        try workspace.archiveProject(first)
        _ = try workspace.createProject(name: "shed")
        expectRejected(.unarchiveNameInUse("shed"), in: workspace) { try workspace.unarchiveProject(first) }
    }

    @Test("021-FR-028 a project's desired outcome is set, trimmed, cleared and limited, archived or not")
    func setProjectOutcome() async throws {
        let workspace = await loadedWorkspace()
        let id = try workspace.createProject(name: "Trip")
        try workspace.setProjectOutcome(id, outcome: "  Two weeks away ")
        #expect(workspace.project(id)?.desiredOutcome == "Two weeks away")
        try workspace.archiveProject(id)
        try workspace.setProjectOutcome(id, outcome: nil)
        #expect(workspace.project(id)?.desiredOutcome == nil)
        expectRejected(.outcomeTooLong, in: workspace) {
            try workspace.setProjectOutcome(id, outcome: String(repeating: "o", count: 1_001))
        }
        expectRejected(.projectNotFound, in: workspace) { try workspace.setProjectOutcome("missing", outcome: "x") }
    }

    @Test("021-FR-026 apply queues a whole sequence in one write, or none of it")
    func applyIsAllOrNothing() async throws {
        let store = InMemoryDocumentStore()
        let workspace = await loadedWorkspace(store: store)
        let item = try workspace.capture(CaptureDraft(text: "Plan the trip"))
        let waiting = try workspace.capture(CaptureDraft(text: "Quote", list: .waiting, waitingFor: "Harbour Hall"))
        await workspace.flush()
        let generation = try #require(try await store.load()).generation

        // Inbox "clarify as project", Waiting "follow up and keep waiting".
        try workspace.apply([
            .createProject(.init(projectID: "trip", name: "Trip")),
            .updateTask(.init(taskID: item, changes: .init(projectID: .set("trip")))),
            .transitionTask(.init(taskID: item, action: .move, toList: .next)),
            .createTask(.init(taskID: "follow-up", title: "Chase the quote", list: .next)),
            .updateTask(.init(taskID: waiting, changes: .init(waitingFor: .set("Harbour Hall (again)")))),
        ])
        #expect(workspace.task(item)?.projectID == "trip" && workspace.task(item)?.state == .next)
        #expect(workspace.task("follow-up")?.title == "Chase the quote")
        #expect(workspace.pendingChangeCount == 7)
        await workspace.flush()
        let stored = try #require(try await store.load())
        #expect(stored.generation == generation + 1, "one document write")
        #expect(stored == workspace.document && OutboxReplayer.replay(stored.outbox, onto: stored.base).state == workspace.state)

        // Someday to Next with a new title, but the second command is invalid: nothing happens.
        let before = workspace.state
        expectRejected(.emptyTitle, in: workspace) {
            try workspace.apply([
                .updateTask(.init(taskID: item, changes: .init(title: .set("Plan the trip, day by day")))),
                .updateTask(.init(taskID: item, changes: .init(title: .set("  ")))),
            ])
        }
        #expect(workspace.state == before && workspace.unpersisted.isEmpty)
    }

    @Test("Clarifying an Inbox item as a project makes it the project's first Next action, or changes nothing")
    func clarifyAsProjectCreatesTheProjectAndTheFirstAction() async throws {
        let workspace = await loadedWorkspace()
        let tag = try workspace.createTag(name: "work")
        let item = try workspace.capture(CaptureDraft(text: "Collect user interviews"))

        let projectID = try workspace.clarifyAsProject(
            item, projectName: "Collect user interviews", outcome: "Ten interviews summarised",
            firstAction: "Email Anna for three contacts", changes: TaskChanges(tagIDs: .set([tag]))
        )

        #expect(workspace.project(projectID)?.name == "Collect user interviews")
        #expect(workspace.project(projectID)?.desiredOutcome == "Ten interviews summarised")
        let task = try #require(workspace.task(item))
        #expect(task.title == "Email Anna for three contacts" && task.state == .next)
        #expect(task.projectID == projectID && task.tagIDs == [tag])
        #expect(workspace.projects().first { $0.id == projectID }?.needsNextAction == false)

        // Keeping the item's own title as the first action leaves the title alone.
        let other = try workspace.capture(CaptureDraft(text: "Call the plumber"))
        let second = try workspace.clarifyAsProject(other, projectName: "Fix the leak", firstAction: "Call the plumber")
        #expect(workspace.task(other)?.title == "Call the plumber" && workspace.task(other)?.projectID == second)
        #expect(workspace.project(second)?.desiredOutcome == nil, "the outcome is optional")

        // A taken name or a blank first action refuses the whole change.
        let third = try workspace.capture(CaptureDraft(text: "Plan the trip"))
        expectRejected(.duplicateProjectName("Fix the leak"), in: workspace) {
            _ = try workspace.clarifyAsProject(third, projectName: "fix the leak", firstAction: "Pick dates")
        }
        expectRejected(.emptyTitle, in: workspace) {
            _ = try workspace.clarifyAsProject(third, projectName: "Trip", firstAction: "")
        }
        expectRejected(.taskNotFound, in: workspace) {
            _ = try workspace.clarifyAsProject("missing", projectName: "Trip", firstAction: "Pick dates")
        }
    }

    // MARK: Tags

    @Test func createTagAddsATagAndRejectsADuplicateName() async throws {
        let workspace = await loadedWorkspace()

        let id = try workspace.createTag(name: "calls")

        #expect(workspace.tag(id)?.name == "calls")
        #expect(workspace.tags().map(\.id) == [id])
        expectRejected(.duplicateTagName("calls"), in: workspace) { _ = try workspace.createTag(name: "Calls") }
    }

    @Test func renameTagAndRejectAnUnknownOne() async throws {
        let workspace = await loadedWorkspace()
        let id = try workspace.createTag(name: "phone")

        try workspace.renameTag(id, to: "calls")

        #expect(workspace.tag(id)?.name == "calls")
        expectRejected(.tagNotFound, in: workspace) { try workspace.renameTag("missing", to: "errands") }
    }

    @Test func deleteTagRemovesItFromItsTasksOnce() async throws {
        let workspace = await loadedWorkspace()
        let taskID = try workspace.capture(CaptureDraft(text: "Buy bulbs #errands"))
        let tagID = try #require(workspace.task(taskID)?.tagIDs.first)

        try workspace.deleteTag(tagID)

        #expect(workspace.tag(tagID)?.state == .deleted)
        #expect(workspace.task(taskID)?.tagIDs == [])
        #expect(workspace.tags().isEmpty)
        expectRejected(.tagAlreadyDeleted, in: workspace) { try workspace.deleteTag(tagID) }
    }

    // MARK: Ids, time and reading

    @Test func commandsUseTheInjectedClockAndIDs() async throws {
        let workspace = await loadedWorkspace()

        let projectID = try workspace.createProject(name: "Offsite")

        #expect(projectID == ProjectID("00000000-0000-0000-0000-000000000001"))
        let operation = try #require(workspace.unpersisted.first)
        #expect(operation.id == UUID(uuidString: "00000000-0000-0000-0000-000000000002"))
        #expect(operation.idempotencyKey == UUID(uuidString: "00000000-0000-0000-0000-000000000003"))
        #expect(operation.issuedAt == Fixture.epoch)
        #expect(!operation.hasBeenSent)
    }

    @Test func issueTimesAreKeptAtTheStoresPrecision() async throws {
        // Sub-microsecond digits the store's JSON cannot keep.
        let clock = TestClock(Date(timeIntervalSinceReferenceDate: 812_345_678.123_456_789))
        let store = InMemoryDocumentStore()
        let workspace = await loadedWorkspace(store: store, clock: clock)

        try workspace.capture(CaptureDraft(text: "Round me #home @Errands"))
        await workspace.flush()

        // What another process reads back is exactly what this one shows.
        let reader = await loadedWorkspace(store: store)
        #expect(reader.state == workspace.state)
        #expect(Workspace.storedPrecision(Date(timeIntervalSinceReferenceDate: 10.999_999_9)) == Date(
            timeIntervalSinceReferenceDate: 11))
    }

    @Test func todayFollowsTheInjectedClock() async {
        let clock = TestClock()
        let workspace = makeWorkspace(clock: clock)

        #expect(workspace.today == CalendarDay(date: Fixture.epoch))
        clock.advance(by: 24 * 60 * 60)
        #expect(workspace.today == CalendarDay(date: Fixture.epoch).adding(days: 1))
        clock.advance(by: -3 * 24 * 60 * 60)
        #expect(workspace.today == CalendarDay(date: Fixture.epoch).adding(days: -2))
    }

    @Test func dateViewsAndCountsUseToday() async throws {
        let workspace = await loadedWorkspace()
        let today = workspace.today

        try workspace.capture(CaptureDraft(text: "Overdue", list: .next, dueDate: today.adding(days: -1)))
        try workspace.capture(CaptureDraft(text: "Due today", dueDate: today))
        try workspace.capture(CaptureDraft(text: "Later", list: .someday, dueDate: today.adding(days: 7)))

        let counts = workspace.counts()
        #expect(counts.inbox == 1)
        #expect(counts.overdue == 1)
        #expect(counts.today == 1)
        #expect(workspace.list(.dateView(.upcoming)).sections.flatMap(\.tasks).map(\.title) == ["Later"])
        #expect(workspace.capturePreview(CaptureDraft(text: "New @Home")).project?.isNew == true)
    }
}
