import Foundation
import Testing

@testable import BrainBuddyCore

@Suite("OutboxCompactor: folding rules")
struct CompactionTests {
    private let create = GTDCommand.createTask(.init(taskID: "t", title: "Draft", list: .inbox))

    private func update(_ changes: TaskChanges, task: TaskID = "t") -> GTDCommand {
        .updateTask(.init(taskID: task, changes: changes))
    }

    private func transition(
        _ action: TaskTransitionAction, to list: OpenList? = nil, waitingFor: String? = nil, task: TaskID = "t"
    ) -> GTDCommand {
        .transitionTask(.init(taskID: task, action: action, toList: list, waitingFor: waitingFor))
    }

    @Test("An edit of an unsent task folds into its creation")
    func editFoldsIntoCreation() {
        let outbox = Fixture.compacted([
            create,
            update(.init(title: .set("Final"), details: .set("Notes"), projectID: .set("work"), priority: .set(.high))),
            update(.init(details: .clear, tagIDs: .set(["home"]), dueDate: .set(CalendarDay(year: 2026, month: 1, day: 2)!))),
        ])
        #expect(
            outbox.map(\.command) == [
                .createTask(
                    .init(
                        taskID: "t", title: "Final", list: .inbox, dueDate: CalendarDay(year: 2026, month: 1, day: 2),
                        priority: .high, projectID: "work", tagIDs: ["home"]
                    )
                )
            ]
        )
        #expect(outbox.first?.issuedAt == Fixture.at(0), "the creation keeps its identity and time")
    }

    @Test("Moves of an unsent task become its creation's list, including the waiting note")
    func moveFoldsIntoCreation() {
        let toWaiting = Fixture.compacted([create, transition(.move, to: .waiting, waitingFor: "Ana")])
        #expect(toWaiting.map(\.command) == [.createTask(.init(taskID: "t", title: "Draft", list: .waiting, waitingFor: "Ana"))])
        let editedNote = Fixture.compacted([
            create, transition(.move, to: .waiting, waitingFor: "Ana"), update(.init(waitingFor: .set("Bob"))),
        ])
        #expect(editedNote.map(\.command) == [.createTask(.init(taskID: "t", title: "Draft", list: .waiting, waitingFor: "Bob"))])
        let leftWaiting = Fixture.compacted([
            create, transition(.move, to: .waiting, waitingFor: "Ana"), transition(.move, to: .someday),
        ])
        #expect(leftWaiting.map(\.command) == [.createTask(.init(taskID: "t", title: "Draft", list: .someday))])
    }

    @Test("Complete (or cancel) then reopen of an unsent task cancels out")
    func completeThenReopenCancelsOut() {
        for terminal in [TaskTransitionAction.complete, .cancel] {
            let outbox = Fixture.compacted([
                create, transition(terminal), update(.init(title: .set("Renamed"))), transition(.reopen, to: .next),
            ])
            #expect(outbox.map(\.command) == [.createTask(.init(taskID: "t", title: "Renamed", list: .next))])
        }
    }

    @Test("Consecutive edits of a sent task merge, across unrelated operations")
    func editsMerge() {
        let outbox = Fixture.compacted([
            update(.init(title: .set("A"), priority: .set(.low)), task: "next"),
            .createTask(.init(taskID: "other", title: "Other", list: .inbox)),
            update(.init(title: .set("B"), dueDate: .clear), task: "next"),
        ])
        #expect(outbox.count == 2)
        #expect(outbox.first?.command == update(.init(title: .set("B"), dueDate: .clear, priority: .set(.low)), task: "next"))
    }

    @Test("A waiting-note edit does not cross a transition of its task")
    func waitingNoteKeepsOrder() {
        let commands = [
            update(.init(title: .set("A")), task: "waiting"),
            transition(.move, to: .next, task: "waiting"),
            transition(.move, to: .waiting, waitingFor: "Ana", task: "waiting"),
            update(.init(waitingFor: .set("Bob")), task: "waiting"),
        ]
        #expect(Fixture.compacted(commands).map(\.command) == commands)
    }

    @Test("Field edits may cross a transition of their task")
    func fieldEditsCrossTransitions() {
        let outbox = Fixture.compacted([
            update(.init(title: .set("A")), task: "next"), transition(.complete, task: "next"),
            update(.init(priority: .set(.high)), task: "next"),
        ])
        #expect(outbox.map(\.command) == [
            update(.init(title: .set("A"), priority: .set(.high)), task: "next"), transition(.complete, task: "next"),
        ])
    }

    @Test("Subtask and comment edits fold into their unsent creation or edit")
    func childrenFold() {
        let outbox = Fixture.compacted([
            .createSubtask(.init(taskID: "next", subtaskID: "s", title: "One")),
            .transitionSubtask(.init(taskID: "next", subtaskID: "s", action: .complete)),
            .updateSubtask(.init(taskID: "next", subtaskID: "s", title: "Two")),
            .createComment(.init(taskID: "next", commentID: "c", body: "Hi")),
            .updateComment(.init(taskID: "next", commentID: "c", body: "Hello")),
            .updateSubtask(.init(taskID: "next", subtaskID: "sent", title: "A")),
            .updateSubtask(.init(taskID: "next", subtaskID: "sent", title: "B")),
            .updateComment(.init(taskID: "next", commentID: "old", body: "A")),
            .updateComment(.init(taskID: "next", commentID: "old", body: "B")),
        ])
        #expect(outbox.map(\.command) == [
            .createSubtask(.init(taskID: "next", subtaskID: "s", title: "Two")),
            .transitionSubtask(.init(taskID: "next", subtaskID: "s", action: .complete)),
            .createComment(.init(taskID: "next", commentID: "c", body: "Hello")),
            .updateSubtask(.init(taskID: "next", subtaskID: "sent", title: "B")),
            .updateComment(.init(taskID: "next", commentID: "old", body: "B")),
        ])
    }

    @Test("Project and tag renames fold into their unsent creation or rename")
    func namesFold() {
        let outbox = Fixture.compacted([
            .createProject(.init(projectID: "p", name: "Plan", color: "#111111")),
            .updateProject(.init(projectID: "p", name: "Plans", color: .clear)),
            .createTag(.init(tagID: "g", name: "calls")),
            .renameTag(.init(tagID: "g", name: "phone")),
            .updateProject(.init(projectID: "work", name: "Job")),
            .updateProject(.init(projectID: "work", color: .set("#222222"))),
        ])
        #expect(outbox.map(\.command) == [
            .createProject(.init(projectID: "p", name: "Plans")),
            .createTag(.init(tagID: "g", name: "phone")),
            .updateProject(.init(projectID: "work", name: "Job", color: .set("#222222"))),
        ])
    }

    @Test("A rename does not move before another rename of its kind (uniqueness depends on order)")
    func renamesKeepOrder() {
        let commands: [GTDCommand] = [
            .createProject(.init(projectID: "p", name: "A")),
            .updateProject(.init(projectID: "q", name: "X")),
            .updateProject(.init(projectID: "p", name: "B")),
            .createTag(.init(tagID: "g", name: "a")),
            .createTag(.init(tagID: "h", name: "b")),
            .renameTag(.init(tagID: "g", name: "c")),
        ]
        #expect(Fixture.compacted(commands).map(\.command) == commands)
    }

    @Test("Nothing folds into or across a sent operation")
    func sentOperationsAreFinal() {
        let sentCreate = [Fixture.operation(create, at: 0, sent: true)]
        let afterSent = OutboxCompactor.appending(Fixture.operation(update(.init(title: .set("B"))), at: 1), to: sentCreate)
        #expect(afterSent.count == 2 && afterSent[0] == sentCreate[0])

        let sentEdit = [Fixture.operation(create, at: 0), Fixture.operation(transition(.complete), at: 1, sent: true)]
        let afterSentEdit = OutboxCompactor.appending(
            Fixture.operation(update(.init(title: .set("B"))), at: 2), to: sentEdit
        )
        #expect(afterSentEdit.count == 3 && Array(afterSentEdit.prefix(2)) == sentEdit)

        let reopen = OutboxCompactor.appending(Fixture.operation(transition(.reopen, to: .next), at: 2), to: sentEdit)
        #expect(reopen.count == 3, "a sent completion stays")

        let sentOp = Fixture.operation(update(.init(title: .set("A"))), at: 0, sent: true)
        #expect(OutboxCompactor.appending(sentOp, to: [Fixture.operation(create, at: 0)]).count == 2)
    }

    @Test("Nothing folds across an archive or a delete, or before a referenced creation")
    func barriers() {
        let archive: [GTDCommand] = [create, .archiveProject("work"), update(.init(title: .set("B")))]
        #expect(Fixture.compacted(archive).map(\.command) == archive)
        let delete: [GTDCommand] = [create, .deleteTag("home"), transition(.move, to: .next)]
        #expect(Fixture.compacted(delete).map(\.command) == delete)
        let referenced: [GTDCommand] = [
            create, .createProject(.init(projectID: "p", name: "P")), update(.init(projectID: .set("p"))),
            update(.init(title: .set("X"))), .createTag(.init(tagID: "g", name: "G")), update(.init(tagIDs: .set(["g"]))),
        ]
        #expect(
            Fixture.compacted(referenced).map(\.command) == [
                create, .createProject(.init(projectID: "p", name: "P")),
                update(.init(title: .set("X"), projectID: .set("p"))),
                .createTag(.init(tagID: "g", name: "G")), update(.init(tagIDs: .set(["g"]))),
            ],
            "an edit waits after the creation of what it references; later edits merge with it"
        )
    }

    @Test("A move does not fold across an edit of the waiting note")
    func moveAfterWaitingEdit() {
        let commands: [GTDCommand] = [
            .createTask(.init(taskID: "t", title: "T", list: .waiting, waitingFor: "Ana")),
            .createProject(.init(projectID: "p", name: "P")),
            update(.init(projectID: .set("p"), waitingFor: .set("Bob"))),
            transition(.move, to: .next),
        ]
        #expect(Fixture.compacted(commands).map(\.command) == commands)
    }
}
