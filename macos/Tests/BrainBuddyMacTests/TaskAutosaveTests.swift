import BrainBuddyCore
import Foundation
import Testing

@testable import BrainBuddyMacCore

/// The inspector's "Saved as you type" (boards 13–20): which inspector a task gets, what is dirty,
/// when a pause makes a save due, what one save sends, and that neither a save finishing nor a
/// change arriving from elsewhere ever undoes what the person is typing. The clock is the test's.
@Suite("Task inspector autosave")
struct TaskAutosaveTests {
    private static let start = Date(timeIntervalSince1970: 1_791_297_240)

    private static func at(_ seconds: TimeInterval) -> Date { start.addingTimeInterval(seconds) }

    private static func task(
        _ title: String = "Call Sam about the van", state: TaskState = .next, details: String? = nil,
        projectID: ProjectID? = nil, waitingFor: String? = nil
    ) -> TaskRecord {
        TaskRecord(
            id: "t1", title: title, details: details, state: state, projectID: projectID, waitingFor: waitingFor,
            orderKey: 0, createdAt: start, updatedAt: start)
    }

    @Test("Each task state gets its own inspector, and only Done and Cancelled are read-only")
    func variants() {
        #expect(TaskInspectorVariant(state: .inbox) == .inbox)
        #expect(TaskInspectorVariant(state: .next) == .next)
        #expect(TaskInspectorVariant(state: .waiting) == .waiting)
        #expect(TaskInspectorVariant(state: .someday) == .someday)
        #expect(TaskInspectorVariant(state: .completed) == .finished(cancelled: false))
        #expect(TaskInspectorVariant(state: .cancelled) == .finished(cancelled: true))
        #expect(TaskState.allCases.filter { TaskInspectorVariant(state: $0).isReadOnly } == [.completed, .cancelled])
    }

    @Test("An edit is dirty; spaces around the title alone, or setting what is there, are not")
    func dirtyTracking() {
        var form = TaskAutosave(task: Self.task())
        #expect(!form.isDirty && form.deadline == nil)

        form.set(\.title, to: "Call Sam about the van", at: Self.at(1))
        #expect(form.lastEditAt == nil, "setting the same value is not an edit")

        form.set(\.title, to: "  Call Sam about the van ", at: Self.at(1))
        #expect(!form.isDirty, "the saved title is trimmed, so spaces alone change nothing")
        #expect(form.saveRequest() == nil)

        form.set(\.details, to: "Ask when he can pick it up.", at: Self.at(2))
        #expect(form.isDirty)
        #expect(form.saveRequest() == TaskAutosaveRequest(changes: TaskChanges(details: .set("Ask when he can pick it up.")), moveTo: nil))
    }

    @Test("Field edits save once the person pauses for 0.6 s; another keystroke restarts the wait")
    func debounce() {
        var form = TaskAutosave(task: Self.task())
        form.set(\.title, to: "Call Sam", at: Self.at(0))
        #expect(form.deadline == Self.at(TaskAutosave.delay))
        #expect(!form.isDue(at: Self.at(0.5)))
        #expect(form.isDue(at: Self.at(0.6)))

        form.set(\.title, to: "Call Sam today", at: Self.at(0.5))
        #expect(!form.isDue(at: Self.at(0.6)), "typing again pushes the save back")
        #expect(form.isDue(at: Self.at(1.2)))
    }

    @Test("Fields that cannot save are never due and say why: no title, or a Waiting task without who")
    func invalidFieldsWait() throws {
        var form = TaskAutosave(task: Self.task())
        form.set(\.title, to: "   ", at: Self.at(0))
        #expect(form.isDirty && !form.isValid)
        #expect(!form.isDue(at: Self.at(5)))
        #expect(form.saveRequest() == nil)
        #expect(try #require(form.problem).contains("title"))

        var waiting = TaskAutosave(task: Self.task("Quote for the van", state: .waiting, waitingFor: "Sam"))
        waiting.set(\.waitingFor, to: nil, at: Self.at(0))
        #expect(!waiting.isValid && waiting.saveRequest() == nil)
        waiting.set(\.waitingFor, to: "Sam's garage", at: Self.at(1))
        #expect(waiting.saveRequest() == TaskAutosaveRequest(changes: TaskChanges(waitingFor: .set("Sam's garage")), moveTo: nil))
    }

    @Test("A list move saves at once with the pending fields; the task's own list is not a move")
    func moveIsItsOwnSave() {
        var form = TaskAutosave(task: Self.task())
        #expect(form.saveRequest(moveTo: .next) == nil, "nothing to send")
        #expect(form.saveRequest(moveTo: .someday) == TaskAutosaveRequest(changes: TaskChanges(), moveTo: .someday))

        form.set(\.projectID, to: "p1", at: Self.at(0))
        #expect(
            form.saveRequest(moveTo: .someday)
                == TaskAutosaveRequest(changes: TaskChanges(projectID: .set("p1")), moveTo: .someday))
    }

    @Test("One save at a time: while one is in flight nothing else is due or sent")
    func oneSaveInFlight() throws {
        var form = TaskAutosave(task: Self.task())
        form.set(\.title, to: "Call Sam", at: Self.at(0))
        let request = try #require(form.beginSave(at: Self.at(1)))
        #expect(request.changes == TaskChanges(title: .set("Call Sam")))
        #expect(form.isSaving)
        #expect(!form.isDue(at: Self.at(5)))
        #expect(form.saveRequest() == nil)
    }

    @Test("A finished save keeps what was typed meanwhile, which then waits for its own pause")
    func typingDuringASaveIsKept() throws {
        var form = TaskAutosave(task: Self.task())
        form.set(\.title, to: "Call Sam", at: Self.at(0))
        _ = try #require(form.beginSave(at: Self.at(1)))
        form.set(\.title, to: "Call Sam tonight", at: Self.at(1.2))

        form.finishSave(succeeded: true, current: Self.task("Call Sam"))
        #expect(!form.isSaving)
        #expect(form.draft.title == "Call Sam tonight", "the save never undoes typing")
        #expect(form.saveRequest()?.changes == TaskChanges(title: .set("Call Sam tonight")), "only the newer edit is left")
        #expect(form.isDue(at: Self.at(1.9)))
    }

    @Test("After a save the fields are clean, even when the draft's spacing differs from what was stored")
    func savedIsClean() throws {
        var form = TaskAutosave(task: Self.task())
        form.set(\.title, to: "Call Sam ", at: Self.at(0))
        _ = try #require(form.beginSave(at: Self.at(1)))
        form.finishSave(succeeded: true, current: Self.task("Call Sam"))
        #expect(form.draft.title == "Call Sam ", "the space the person is about to type after stays")
        #expect(!form.isDirty && form.deadline == nil)
    }

    @Test("A failed save stays pending without retrying in a loop; the next flush sends it again")
    func failedSaveStaysPending() throws {
        var form = TaskAutosave(task: Self.task())
        form.set(\.title, to: "Call Sam", at: Self.at(0))
        _ = try #require(form.beginSave(at: Self.at(1)))
        form.finishSave(succeeded: false, current: nil)
        #expect(form.isDirty)
        #expect(!form.isDue(at: Self.at(10)), "no automatic retry")
        #expect(form.saveRequest()?.changes == TaskChanges(title: .set("Call Sam")))
    }

    @Test("A change from elsewhere fills untouched fields and never overwrites the field being typed in")
    func rebaseKeepsTheFieldBeingTyped() {
        var form = TaskAutosave(task: Self.task(details: "old note"))
        form.set(\.title, to: "Call Sam", at: Self.at(0))

        var incoming = Self.task("Call Sam about the van and the trailer", details: "new note")
        incoming.dueDate = CalendarDay(year: 2026, month: 10, day: 16)
        form.rebase(onto: incoming, typingIn: nil)
        #expect(form.draft.title == "Call Sam", "a touched field keeps what was typed")
        #expect(form.draft.details == "new note", "an untouched field takes the incoming value")
        #expect(form.draft.dueDate == incoming.dueDate)

        // The person types the notes back to what they were; the field still has focus.
        var typing = TaskAutosave(task: Self.task(details: "old note"))
        typing.set(\.details, to: "old note!", at: Self.at(0))
        typing.set(\.details, to: "old note", at: Self.at(0.2))
        typing.rebase(onto: Self.task(details: "changed elsewhere"), typingIn: .details)
        #expect(typing.draft.details == "old note", "the focused field is never overwritten")
        #expect(typing.isDirty, "against the new baseline it is the person's edit, and it saves")
        typing.rebase(onto: Self.task(details: "changed again"), typingIn: nil)
        #expect(typing.draft.details == "old note", "and stays theirs after focus leaves")
    }

    @Test("A change for another task, or after the task moved lists, keeps the form on its own task")
    func rebaseTracksState() {
        var form = TaskAutosave(task: Self.task())
        var other = Self.task("Something else")
        other.id = "t2"
        form.rebase(onto: other, typingIn: nil)
        #expect(form.draft.title == "Call Sam about the van")

        form.rebase(onto: Self.task(state: .someday), typingIn: nil)
        #expect(form.state == .someday)
        #expect(form.saveRequest(moveTo: .someday) == nil, "already there")
    }
}
