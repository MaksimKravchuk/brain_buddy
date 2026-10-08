import Foundation
import Testing

@testable import BrainBuddyCore

@Suite("TaskEditDraft and SelectionAnchor")
struct TaskEditDraftTests {
    private static let due = CalendarDay(year: 2026, month: 10, day: 20)!

    private func task() -> TaskRecord {
        var task = Fixture.task("t", "Call Ana", state: .waiting, projectID: "work", tagIDs: ["home"], waitingFor: "Ana")
        task.details = "Before noon"
        task.dueDate = Self.due
        task.priority = .high
        return task
    }

    @Test("021-FR-009 an untouched draft changes nothing")
    func untouched() {
        #expect(TaskEditDraft(task()).changes() == TaskChanges())
    }

    @Test("021-FR-009 changes() sends touched fields only: omitted, null or a value")
    func touchedFieldsOnly() {
        var draft = TaskEditDraft(task())
        draft.title = "Call Ana today"
        draft.details = nil
        draft.projectID = nil
        draft.tagIDs = []
        draft.dueDate = CalendarDay(year: 2026, month: 10, day: 21)
        draft.priority = .none
        draft.waitingFor = "Ana (legal)"
        #expect(
            draft.changes()
                == TaskChanges(
                    title: .set("Call Ana today"), details: .clear, projectID: .clear, tagIDs: .clear,
                    dueDate: .set(CalendarDay(year: 2026, month: 10, day: 21)!), priority: .set(.none),
                    waitingFor: .set("Ana (legal)")
                )
        )
        var onlyNotes = TaskEditDraft(task())
        onlyNotes.details = "After lunch"
        #expect(onlyNotes.changes() == TaskChanges(details: .set("After lunch")))
        var cleared = TaskEditDraft(task())
        cleared.dueDate = nil
        #expect(cleared.changes() == TaskChanges(dueDate: .clear))
    }

    @Test("021-FR-009 a draft edited back to its baseline sends nothing")
    func editedBack() {
        var draft = TaskEditDraft(task())
        draft.title = "Other"
        draft.title = "Call Ana"
        #expect(draft.changes() == TaskChanges())
    }

    @Test("021-FR-009 rebasing shows an incoming change to an untouched field and keeps a touched one")
    func rebase() {
        var draft = TaskEditDraft(task())
        draft.details = "Typed locally"
        var incoming = task()
        incoming.details = "Changed elsewhere"
        incoming.priority = .low
        incoming.title = "Call Ana now"

        let rebased = draft.rebased(onto: incoming)
        #expect(rebased.details == "Typed locally", "the touched field is not overwritten")
        #expect(rebased.priority == .low && rebased.title == "Call Ana now", "untouched fields show the incoming values")
        #expect(rebased.changes() == TaskChanges(details: .set("Typed locally")), "only the local edit is sent")

        var agreeing = TaskEditDraft(task())
        agreeing.priority = .low
        #expect(agreeing.rebased(onto: incoming).changes() == TaskChanges(), "a local edit the pull already holds is not sent")
    }

    // MARK: SelectionAnchor

    @Test("021-FR-009 an anchor resolves by id wherever the row moved")
    func anchorByID() {
        let anchor = SelectionAnchor(id: "c", in: ["a", "b", "c", "d"])
        #expect(anchor.resolved(in: ["d", "c", "a"]) == "c")
    }

    @Test("021-FR-009 when the row left the list the anchor falls back to the nearest surviving neighbour")
    func anchorFallsBack() {
        let anchor = SelectionAnchor(id: "c", in: ["a", "b", "c", "d", "e"])
        #expect(anchor.resolved(in: ["a", "b", "d", "e"]) == "d", "the next row moves up into the gap")
        #expect(anchor.resolved(in: ["a", "b", "e"]) == "b", "nearer than the one after")
        #expect(anchor.resolved(in: ["a", "e"]) == "e", "equally near: the one after")
        #expect(anchor.resolved(in: ["a"]) == "a")
        #expect(anchor.resolved(in: []) == nil)
    }

    @Test("021-FR-009 an anchor to a row the list never held resolves only to itself")
    func anchorWithoutNeighbours() {
        let anchor = SelectionAnchor(id: "z", in: ["a", "b"])
        #expect(anchor.resolved(in: ["z"]) == "z")
        #expect(anchor.resolved(in: ["a", "b"]) == nil)
    }
}
