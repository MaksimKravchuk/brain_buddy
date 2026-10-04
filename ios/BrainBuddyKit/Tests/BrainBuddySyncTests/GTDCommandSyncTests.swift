import BrainBuddyCore
import Foundation
import Testing

@testable import BrainBuddySync

@Suite("GTDCommand and PendingOperation: sync bookkeeping")
struct GTDCommandSyncTests {
    private let date = Date(timeIntervalSinceReferenceDate: 812_345_678)

    @Test("A new key after an attempt keeps the operation sent, so the compactor never folds into it")
    func renewedKeyStaysSent() {
        var operation = PendingOperation(
            command: .updateTask(.init(taskID: "t", changes: TaskChanges(title: .set("Draft v2")))), issuedAt: date,
            attempts: 1, firstAttemptAt: date, lastAttemptAt: date
        )
        let oldKey = operation.idempotencyKey
        operation.rotateKey()
        #expect(operation.idempotencyKey != oldKey)
        #expect(operation.attempts == 0)
        #expect(operation.firstAttemptAt == nil)
        #expect(operation.everSent)
        #expect(operation.hasBeenSent)
        operation.rotateKey()
        #expect(operation.hasBeenSent, "sticky across rotations")

        let edit = PendingOperation(
            command: .updateTask(.init(taskID: "t", changes: TaskChanges(details: .set("Notes")))), issuedAt: date
        )
        #expect(OutboxCompactor.appending(edit, to: [operation]).count == 2)

        var unsent = PendingOperation(command: operation.command, issuedAt: date)
        unsent.rotateKey()
        #expect(!unsent.hasBeenSent, "a key renewed before any attempt changes nothing")
        #expect(OutboxCompactor.appending(edit, to: [unsent]).count == 1)
    }

    @Test("Nothing remains of a command acknowledged as it was sent")
    func nothingRemainsOfAnUnchangedCommand() {
        let command = GTDCommand.transitionTask(.init(taskID: "t", action: .complete))
        #expect(command.remainder(afterSending: command).isEmpty)
    }

    @Test("What remains of an edit is the fields that differ from what was sent")
    func editRemainder() {
        let sent = GTDCommand.updateTask(.init(taskID: "t", changes: TaskChanges(title: .set("A"), priority: .set(.low))))
        let queued = GTDCommand.updateTask(
            .init(taskID: "t", changes: TaskChanges(title: .set("A"), details: .set("Notes"), priority: .set(.high)))
        )
        #expect(
            queued.remainder(afterSending: sent) == [
                .updateTask(.init(taskID: "t", changes: TaskChanges(details: .set("Notes"), priority: .set(.high))))
            ]
        )
        let project = GTDCommand.updateProject(.init(projectID: "p", name: "Home", color: .set("#fff")))
        #expect(
            GTDCommand.updateProject(.init(projectID: "p", name: "Home", color: .clear)).remainder(afterSending: project)
                == [.updateProject(.init(projectID: "p", color: .clear))]
        )
    }

    @Test("What remains of a create is the move and edit to what it says now")
    func createRemainder() {
        let sent = GTDCommand.createTask(.init(taskID: "t", title: "Call Ana", list: .inbox, priority: .low))
        let queued = GTDCommand.createTask(
            .init(taskID: "t", title: "Call Ana today", list: .waiting, waitingFor: "Ana", priority: .low, tagIDs: ["g"])
        )
        #expect(
            queued.remainder(afterSending: sent) == [
                .transitionTask(.init(taskID: "t", action: .move, toList: .waiting, waitingFor: "Ana")),
                .updateTask(.init(taskID: "t", changes: TaskChanges(title: .set("Call Ana today"), tagIDs: .set(["g"])))),
            ]
        )
        let subtask = GTDCommand.createSubtask(.init(taskID: "t", subtaskID: "s", title: "Milk"))
        #expect(
            GTDCommand.createSubtask(.init(taskID: "t", subtaskID: "s", title: "Oat milk")).remainder(afterSending: subtask)
                == [.updateSubtask(.init(taskID: "t", subtaskID: "s", title: "Oat milk"))]
        )
        let tag = GTDCommand.createTag(.init(tagID: "g", name: "calls"))
        #expect(
            GTDCommand.createTag(.init(tagID: "g", name: "phone")).remainder(afterSending: tag)
                == [.renameTag(.init(tagID: "g", name: "phone"))]
        )
    }
}
