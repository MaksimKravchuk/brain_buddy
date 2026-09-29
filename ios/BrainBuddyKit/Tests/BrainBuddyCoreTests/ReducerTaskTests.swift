import Foundation
import Testing

@testable import BrainBuddyCore

@Suite("GTDReducer: creating tasks")
struct ReducerCreateTaskTests {
    @Test("A new task gets the next order key in its list and the issue time")
    func createsAtEndOfList() throws {
        var state = Fixture.base
        let outcome = try apply(
            .createTask(
                .init(
                    taskID: "new", title: "  Buy milk \n", details: "2 litres", list: .inbox, waitingFor: "ignored",
                    dueDate: CalendarDay(year: 2026, month: 10, day: 1), priority: .high, projectID: "work",
                    tagIDs: ["home"]
                )
            ),
            to: &state, at: 5
        )
        #expect(outcome == .applied)
        let task = try #require(state.tasks["new"])
        #expect(task.title == "Buy milk")
        #expect(task.details == "2 litres")
        #expect(task.state == .inbox)
        #expect(task.orderKey == 5, "inbox's highest order key is 4")
        #expect(task.waitingFor == nil && task.waitingSince == nil, "a non-waiting task drops the note, as the server does")
        #expect(task.projectID == "work" && task.tagIDs == ["home"])
        #expect(task.dueDate == CalendarDay(year: 2026, month: 10, day: 1) && task.priority == .high)
        #expect(task.createdAt == Fixture.at(5) && task.updatedAt == Fixture.at(5))
        #expect(task.serverID == nil && task.serverRevision == nil && task.lastOpenList == nil)
        #expect(task.completedAt == nil && task.cancelledAt == nil && task.subtasks.isEmpty && task.comments.isEmpty)
    }

    @Test("Order keys count only tasks in the same state; an empty list starts at 0")
    func orderKeys() throws {
        var state = Fixture.base
        try apply(.createTask(.init(taskID: "a", title: "A", list: .someday)), to: &state)
        #expect(state.tasks["a"]?.orderKey == 1)
        var empty = GTDState.empty
        try apply(.createTask(.init(taskID: "b", title: "B", list: .next)), to: &empty)
        try apply(.createTask(.init(taskID: "c", title: "C", list: .next)), to: &empty)
        #expect(empty.tasks["b"]?.orderKey == 0 && empty.tasks["c"]?.orderKey == 1)
    }

    @Test("Waiting needs a trimmed, non-blank note and records when waiting began")
    func waitingNote() throws {
        var state = Fixture.base
        try apply(.createTask(.init(taskID: "w", title: "W", list: .waiting, waitingFor: "  Bob ")), to: &state, at: 3)
        #expect(state.tasks["w"]?.waitingFor == "Bob")
        #expect(state.tasks["w"]?.waitingSince == Fixture.at(3))
        #expect(state.tasks["w"]?.orderKey == 8)
        expectRejection(.createTask(.init(taskID: "x", title: "X", list: .waiting)), on: state, .waitingForRequired)
        expectRejection(
            .createTask(.init(taskID: "x", title: "X", list: .waiting, waitingFor: " \t ")), on: state, .waitingForRequired
        )
        let long = String(repeating: "a", count: 501)
        expectRejection(
            .createTask(.init(taskID: "x", title: "X", list: .next, waitingFor: long)), on: state, .waitingForTooLong
        )
    }

    @Test("Titles are trimmed, 1…500 Unicode scalars (Python's len), not grapheme clusters")
    func titleRules() throws {
        let state = Fixture.base
        expectRejection(.createTask(.init(taskID: "x", title: "", list: .inbox)), on: state, .emptyTitle)
        expectRejection(.createTask(.init(taskID: "x", title: " \u{1F}\n", list: .inbox)), on: state, .emptyTitle)
        expectRejection(
            .createTask(.init(taskID: "x", title: String(repeating: "a", count: 501), list: .inbox)), on: state,
            .titleTooLong
        )
        // 251 flags are 251 characters but 502 scalars: too long for the server.
        expectRejection(
            .createTask(.init(taskID: "x", title: String(repeating: "🇺🇸", count: 251), list: .inbox)), on: state,
            .titleTooLong
        )
        var accepted = state
        try apply(.createTask(.init(taskID: "x", title: String(repeating: "🇺🇸", count: 250), list: .inbox)), to: &accepted)
        #expect(accepted.tasks["x"] != nil)
    }

    @Test("Empty notes mean no notes; notes are limited to 20 000 scalars")
    func detailsRules() throws {
        var state = Fixture.base
        try apply(.createTask(.init(taskID: "x", title: "X", details: "", list: .inbox)), to: &state)
        #expect(state.tasks["x"]?.details == nil)
        expectRejection(
            .createTask(.init(taskID: "y", title: "Y", details: String(repeating: "n", count: 20_001), list: .inbox)),
            on: state, .detailsTooLong
        )
    }

    @Test("Project and tags must exist, be active and not repeat")
    func references() {
        let state = Fixture.base
        func create(project: ProjectID? = nil, tags: [TagID] = []) -> GTDCommand {
            .createTask(.init(taskID: "x", title: "X", list: .next, projectID: project, tagIDs: tags))
        }
        expectRejection(create(project: "missing"), on: state, .projectNotFound)
        expectRejection(create(project: "old"), on: state, .projectNotActive)
        expectRejection(create(tags: ["missing"]), on: state, .tagNotFound)
        expectRejection(create(tags: ["gone"]), on: state, .tagNotActive)
        expectRejection(create(tags: ["home", "home"]), on: state, .duplicateTag)
    }

    @Test("An existing id is an error for the user and already satisfied in replay")
    func existingID() throws {
        let command = GTDCommand.createTask(.init(taskID: "next", title: "Again", list: .inbox))
        expectRejection(command, on: Fixture.base, .idAlreadyExists)
        var state = Fixture.base
        #expect(try apply(command, to: &state, mode: .replay) == .alreadySatisfied)
        #expect(state == Fixture.base)
    }
}

@Suite("GTDReducer: editing tasks")
struct ReducerUpdateTaskTests {
    @Test("Every field can be edited; the edit bumps updatedAt and nothing else")
    func editsFields() throws {
        var state = Fixture.base
        let before = try #require(state.tasks["inbox"])
        let changes = TaskChanges(
            title: .set(" Renamed "), details: .set("Notes"), projectID: .clear, tagIDs: .set([]),
            dueDate: .set(CalendarDay(year: 2026, month: 12, day: 24)!), priority: .set(.medium)
        )
        #expect(try apply(.updateTask(.init(taskID: "inbox", changes: changes)), to: &state, at: 9) == .applied)
        let task = try #require(state.tasks["inbox"])
        #expect(task.title == "Renamed" && task.details == "Notes")
        #expect(task.projectID == nil && task.tagIDs.isEmpty)
        #expect(task.dueDate == CalendarDay(year: 2026, month: 12, day: 24) && task.priority == .medium)
        #expect(task.updatedAt == Fixture.at(9))
        #expect(task.state == before.state && task.orderKey == before.orderKey && task.createdAt == before.createdAt)
        #expect(task.serverRevision == before.serverRevision, "the revision is the server's number")
    }

    @Test("Tag order is kept; clearing tags empties them; an empty notes string clears the notes")
    func tagsAndDetails() throws {
        var state = Fixture.base
        state.tags["b"] = Fixture.tag("b", "b")
        try apply(.updateTask(.init(taskID: "next", changes: .init(tagIDs: .set(["home", "b"])))), to: &state)
        #expect(state.tasks["next"]?.tagIDs == ["home", "b"])
        try apply(.updateTask(.init(taskID: "next", changes: .init(tagIDs: .set(["b", "home"])))), to: &state)
        #expect(state.tasks["next"]?.tagIDs == ["b", "home"])
        try apply(.updateTask(.init(taskID: "next", changes: .init(details: .set("x"), tagIDs: .clear))), to: &state)
        #expect(state.tasks["next"]?.tagIDs == [])
        try apply(.updateTask(.init(taskID: "next", changes: .init(details: .set("")))), to: &state)
        #expect(state.tasks["next"]?.details == nil)
    }

    @Test("A title or priority cannot be cleared")
    func requiredFields() {
        expectRejection(.updateTask(.init(taskID: "next", changes: .init(title: .clear))), on: Fixture.base, .emptyTitle)
        expectRejection(
            .updateTask(.init(taskID: "next", changes: .init(title: .set("  ")))), on: Fixture.base, .emptyTitle
        )
        expectRejection(
            .updateTask(.init(taskID: "next", changes: .init(priority: .clear))), on: Fixture.base, .priorityRequired
        )
    }

    @Test("The waiting note is edited only while Waiting, keeps waitingSince, and cannot be blank")
    func waitingNote() throws {
        var state = Fixture.base
        let since = state.tasks["waiting"]?.waitingSince
        try apply(.updateTask(.init(taskID: "waiting", changes: .init(waitingFor: .set("  Bob ")))), to: &state)
        #expect(state.tasks["waiting"]?.waitingFor == "Bob")
        #expect(state.tasks["waiting"]?.waitingSince == since)
        expectRejection(
            .updateTask(.init(taskID: "next", changes: .init(waitingFor: .set("Bob")))), on: state,
            .waitingForOnlyOnWaitingTasks
        )
        expectRejection(
            .updateTask(.init(taskID: "done", changes: .init(waitingFor: .clear))), on: state,
            .waitingForOnlyOnWaitingTasks
        )
        expectRejection(.updateTask(.init(taskID: "waiting", changes: .init(waitingFor: .clear))), on: state, .waitingForRequired)
        expectRejection(
            .updateTask(.init(taskID: "waiting", changes: .init(waitingFor: .set(" ")))), on: state, .waitingForRequired
        )
        expectRejection(
            .updateTask(.init(taskID: "waiting", changes: .init(waitingFor: .set(String(repeating: "b", count: 501))))),
            on: state, .waitingForTooLong
        )
    }

    @Test("Assigned projects and tags must exist and be active")
    func references() {
        let state = Fixture.base
        func update(_ changes: TaskChanges) -> GTDCommand { .updateTask(.init(taskID: "next", changes: changes)) }
        expectRejection(update(.init(projectID: .set("old"))), on: state, .projectNotActive)
        expectRejection(update(.init(projectID: .set("missing"))), on: state, .projectNotFound)
        expectRejection(update(.init(tagIDs: .set(["gone"]))), on: state, .tagNotActive)
        expectRejection(update(.init(tagIDs: .set(["missing"]))), on: state, .tagNotFound)
        expectRejection(update(.init(tagIDs: .set(["home", "home"]))), on: state, .duplicateTag)
        expectRejection(.updateTask(.init(taskID: "missing", changes: .init(priority: .set(.low)))), on: state, .taskNotFound)
    }

    @Test("Terminal tasks can still be edited")
    func editsTerminalTasks() throws {
        var state = Fixture.base
        try apply(.updateTask(.init(taskID: "done", changes: .init(title: .set("Done, renamed")))), to: &state)
        #expect(state.tasks["done"]?.title == "Done, renamed")
        #expect(state.tasks["done"]?.state == .completed)
    }

    @Test("An edit that changes nothing: nothingToChange for the user, satisfied in replay")
    func noOpEdits() throws {
        let unchanged = GTDCommand.updateTask(.init(taskID: "inbox", changes: TaskChanges()))
        let same = GTDCommand.updateTask(
            .init(
                taskID: "inbox",
                changes: .init(title: .set(" Inbox task "), projectID: .set("work"), tagIDs: .set(["home"]), priority: .set(.none))
            )
        )
        for command in [unchanged, same] {
            expectRejection(command, on: Fixture.base, .nothingToChange)
            var state = Fixture.base
            #expect(try apply(command, to: &state, mode: .replay) == .alreadySatisfied)
            #expect(state == Fixture.base)
        }
        var state = Fixture.base
        let partly = GTDCommand.updateTask(
            .init(taskID: "inbox", changes: .init(title: .set("Inbox task"), priority: .set(.low)))
        )
        #expect(try apply(partly, to: &state, mode: .replay) == .applied)
        #expect(state.tasks["inbox"]?.priority == .low)
    }
}

@Suite("GTDReducer: task transitions")
struct ReducerTransitionTests {
    private func transition(
        _ id: TaskID, _ action: TaskTransitionAction, to list: OpenList? = nil, waitingFor: String? = nil
    ) -> GTDCommand {
        .transitionTask(.init(taskID: id, action: action, toList: list, waitingFor: waitingFor))
    }

    @Test("Move changes only the list and the waiting fields")
    func move() throws {
        var state = Fixture.base
        let before = try #require(state.tasks["inbox"])
        try apply(transition("inbox", .move, to: .next, waitingFor: "dropped"), to: &state, at: 4)
        let task = try #require(state.tasks["inbox"])
        #expect(task.state == .next)
        #expect(task.waitingFor == nil && task.waitingSince == nil)
        #expect(task.updatedAt == Fixture.at(4))
        var expected = before
        expected.state = .next
        expected.updatedAt = Fixture.at(4)
        #expect(task == expected, "order, project, tags, due date, priority and notes are kept")
    }

    @Test("Entering Waiting needs a note and sets waitingSince; leaving clears both")
    func waiting() throws {
        var state = Fixture.base
        expectRejection(transition("next", .move, to: .waiting), on: state, .waitingForRequired)
        expectRejection(transition("next", .move, to: .waiting, waitingFor: "  "), on: state, .waitingForRequired)
        try apply(transition("next", .move, to: .waiting, waitingFor: " Ana "), to: &state, at: 6)
        #expect(state.tasks["next"]?.waitingFor == "Ana" && state.tasks["next"]?.waitingSince == Fixture.at(6))
        try apply(transition("waiting", .move, to: .someday), to: &state)
        #expect(state.tasks["waiting"]?.waitingFor == nil && state.tasks["waiting"]?.waitingSince == nil)
    }

    @Test("Move needs an open task and a different destination")
    func moveRules() throws {
        let state = Fixture.base
        expectRejection(transition("inbox", .move), on: state, .moveRequiresDestination)
        expectRejection(transition("inbox", .move, to: .inbox), on: state, .moveRequiresDifferentList)
        expectRejection(transition("done", .move, to: .next), on: state, .taskNotOpen)
        expectRejection(transition("missing", .move, to: .next), on: state, .taskNotFound)
        var replayed = state
        #expect(try apply(transition("inbox", .move, to: .inbox), to: &replayed, mode: .replay) == .alreadySatisfied)
        #expect(replayed == state)
        expectRejection(transition("done", .move, to: .next), on: state, .taskNotOpen, mode: .replay)
    }

    @Test("Complete and cancel record the time, remember the list and clear the waiting note")
    func terminal() throws {
        var state = Fixture.base
        let before = try #require(state.tasks["waiting"])
        try apply(transition("waiting", .complete), to: &state, at: 8)
        let completed = try #require(state.tasks["waiting"])
        #expect(completed.state == .completed && completed.completedAt == Fixture.at(8) && completed.cancelledAt == nil)
        #expect(completed.lastOpenList == .waiting)
        #expect(completed.waitingFor == nil && completed.waitingSince == nil)
        #expect(completed.orderKey == before.orderKey && completed.updatedAt == Fixture.at(8))

        try apply(transition("next", .cancel), to: &state, at: 9)
        let cancelled = try #require(state.tasks["next"])
        #expect(cancelled.state == .cancelled && cancelled.cancelledAt == Fixture.at(9) && cancelled.completedAt == nil)
        #expect(cancelled.lastOpenList == .next)
    }

    @Test("Complete and cancel need an open task; repeating one is satisfied in replay")
    func terminalRules() throws {
        let state = Fixture.base
        expectRejection(transition("done", .complete), on: state, .taskNotOpen)
        expectRejection(transition("done", .cancel), on: state, .taskNotOpen)
        expectRejection(transition("dropped", .complete), on: state, .taskNotOpen, mode: .replay)
        var replayed = state
        #expect(try apply(transition("done", .complete), to: &replayed, mode: .replay) == .alreadySatisfied)
        #expect(try apply(transition("dropped", .cancel), to: &replayed, mode: .replay) == .alreadySatisfied)
        #expect(replayed == state)
    }

    @Test("Reopen needs a terminal task and an explicit list, and clears terminal fields")
    func reopen() throws {
        var state = Fixture.base
        try apply(transition("inbox", .complete), to: &state, at: 2)
        try apply(transition("inbox", .reopen, to: .waiting, waitingFor: "Bob"), to: &state, at: 3)
        let task = try #require(state.tasks["inbox"])
        #expect(task.state == .waiting && task.waitingFor == "Bob" && task.waitingSince == Fixture.at(3))
        #expect(task.completedAt == nil && task.cancelledAt == nil && task.lastOpenList == nil)
        #expect(task.projectID == "work" && task.tagIDs == ["home"])

        try apply(transition("dropped", .reopen, to: .someday), to: &state)
        #expect(state.tasks["dropped"]?.state == .someday && state.tasks["dropped"]?.cancelledAt == nil)

        expectRejection(transition("done", .reopen), on: state, .reopenRequiresDestination)
        expectRejection(transition("done", .reopen, to: .waiting), on: state, .waitingForRequired)
        expectRejection(transition("next", .reopen, to: .next), on: state, .taskNotClosed)
        expectRejection(transition("next", .reopen, to: .inbox), on: state, .taskNotClosed, mode: .replay)
        var replayed = state
        #expect(try apply(transition("next", .reopen, to: .next), to: &replayed, mode: .replay) == .alreadySatisfied)
        #expect(replayed == state)
    }
}
