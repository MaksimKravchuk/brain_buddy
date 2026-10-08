import Foundation
import Testing

@testable import BrainBuddyCore

@Suite("SyncIssueDescriber")
struct SyncIssueDescriberTests {
    private let state = Fixture.state(
        tasks: [
            Fixture.task("t", "Buy milk", state: .next, subtasks: [SubtaskRecord(id: "s", title: "Oat", orderKey: 0)]),
            Fixture.task("long", String(repeating: "x", count: 70)),
        ],
        projects: [Fixture.project("p", "Work"), Fixture.project("old", "Old flat", state: .archived)],
        tags: [Fixture.tag("g", "home")]
    )

    private func describe(_ command: GTDCommand) -> String { SyncIssueDescriber.describe(command, in: state) }

    @Test("021-FR-011 every description the iPhone's Sync issues screen gave, word for word")
    func existingDescriptions() {
        let cases: [(GTDCommand, String)] = [
            (.createProject(.init(projectID: "n", name: "Home")), "Create project “Home”"),
            (.updateProject(.init(projectID: "p", name: "Home")), "Rename project “Work” to “Home”"),
            (.updateProject(.init(projectID: "p", name: "Work", color: .set("#fff"))), "Rename project to “Work” and change its colour"),
            (.updateProject(.init(projectID: "p", color: .set("#fff"))), "Change the colour of project “Work”"),
            (.updateProject(.init(projectID: "p", color: .clear)), "Remove the colour of project “Work”"),
            (.updateProject(.init(projectID: "p")), "Edit project “Work”"),
            (.archiveProject("p"), "Archive project “Work”"),
            (.archiveProject("missing"), "Archive a project"),
            (.createTag(.init(tagID: "n", name: "x")), "Create tag #x"),
            (.renameTag(.init(tagID: "g", name: "house")), "Rename #home to #house"),
            (.renameTag(.init(tagID: "missing", name: "house")), "Rename tag to #house"),
            (.deleteTag("g"), "Delete #home"),
            (.createTask(.init(taskID: "n", title: "Call", list: .next)), "Add “Call” to Next actions"),
            (.updateTask(.init(taskID: "t", changes: .init(title: .set("Milk")))), "Rename “Buy milk” to “Milk”"),
            (.updateTask(.init(taskID: "t", changes: .init(details: .clear))), "Clear the notes of “Buy milk”"),
            (.updateTask(.init(taskID: "t", changes: .init(details: .set("n")))), "Edit the notes of “Buy milk”"),
            (.updateTask(.init(taskID: "t", changes: .init(projectID: .set("p")))), "Move “Buy milk” to project “Work”"),
            (.updateTask(.init(taskID: "t", changes: .init(projectID: .clear))), "Remove “Buy milk” from its project"),
            (.updateTask(.init(taskID: "t", changes: .init(tagIDs: .set(["g"])))), "Change the tags on “Buy milk”"),
            (.updateTask(.init(taskID: "t", changes: .init(dueDate: .clear))), "Remove the due date from “Buy milk”"),
            (.updateTask(.init(taskID: "t", changes: .init(priority: .set(.high)))), "Set the priority of “Buy milk” to high"),
            (.updateTask(.init(taskID: "t", changes: .init(priority: .set(.none)))), "Remove the priority from “Buy milk”"),
            (.updateTask(.init(taskID: "t", changes: .init(waitingFor: .set("Ana")))), "Change what “Buy milk” is waiting for"),
            (.updateTask(.init(taskID: "t", changes: .init(title: .set("A"), priority: .set(.low)))), "Edit “Buy milk”"),
            (.transitionTask(.init(taskID: "t", action: .complete)), "Complete “Buy milk”"),
            (.transitionTask(.init(taskID: "t", action: .cancel)), "Cancel “Buy milk”"),
            (.transitionTask(.init(taskID: "t", action: .move, toList: .waiting, waitingFor: "A")), "Move “Buy milk” to Waiting for"),
            (.transitionTask(.init(taskID: "t", action: .reopen, toList: .inbox)), "Reopen “Buy milk” in Inbox"),
            (.createSubtask(.init(taskID: "t", subtaskID: "n", title: "Foam")), "Add subtask “Foam” to “Buy milk”"),
            (.updateSubtask(.init(taskID: "t", subtaskID: "s", title: "Soy")), "Rename subtask “Oat” to “Soy”"),
            (.transitionSubtask(.init(taskID: "t", subtaskID: "s", action: .complete)), "Complete subtask “Oat”"),
            (.createComment(.init(taskID: "t", commentID: "c", body: "x")), "Comment on “Buy milk”"),
            (.updateComment(.init(taskID: "t", commentID: "c", body: "x")), "Edit a comment on “Buy milk”"),
            (.undoDecision("d"), "Undo a decision"),
            (.bulkRelease(.init(bulkID: "b", kind: .restart, taskIDs: ["t"])), "Move 1 task to Someday / maybe"),
            (.bulkRelease(.init(bulkID: "b", kind: .restart, taskIDs: ["t", "long"])), "Move 2 tasks to Someday / maybe"),
            (.undoBulkRelease("b"), "Undo moving tasks to Someday / maybe"),
            (.review(.revokeNavigatorConsent(provider: "x")), "Save weekly review progress"),
        ]
        for (command, expected) in cases { #expect(describe(command) == expected) }
    }

    @Test("021-FR-011 names are curly-quoted and clipped at 60 characters")
    func clipping() {
        #expect(describe(.completeTask("long")) == "Complete “\(String(repeating: "x", count: 59))…”")
        #expect(SyncIssueDescriber.quote("a\nb") == "“a b”")
    }

    @Test("021-FR-011 021-FR-026 the unarchive and outcome commands, and the project an unarchive refused")
    func newCommands() {
        #expect(describe(.unarchiveProject(project: "old")) == "Unarchive project “Old flat”")
        #expect(describe(.unarchiveProject(project: "missing")) == "Unarchive a project")
        #expect(describe(.setProjectOutcome(project: "p", outcome: "Done")) == "Change the desired outcome of “Work”")
    }

    @Test("021-FR-011 021-FR-026 an unarchive refused for a taken name, with and without the tasks kept out of the project")
    func unarchiveNameCopy() {
        #expect(SyncIssueDescriber.unarchiveNameInUse("Shed", keptWithoutProject: 0) == "Another active project is already called “Shed”.")
        #expect(
            SyncIssueDescriber.unarchiveNameInUse("Shed", keptWithoutProject: 1)
                == "Another active project is already called “Shed”. 1 task you added to it was kept without a project."
        )
        #expect(
            SyncIssueDescriber.unarchiveNameInUse("Shed", keptWithoutProject: 2)
                == "Another active project is already called “Shed”. 2 tasks you added to it were kept without a project."
        )
    }

    @Test("021-FR-011 a repeated rejection says what state the project is left in; other commands keep the old words")
    func repeatedRejection() {
        #expect(
            SyncIssueDescriber.keptRejecting(.unarchiveProject(project: "p"))
                == "Brain Buddy couldn't unarchive it, so it's still archived. Try Unarchive again later."
        )
        #expect(
            SyncIssueDescriber.keptRejecting(.archiveProject("p"))
                == "Brain Buddy couldn't archive it, so it's still active. Try again later."
        )
        #expect(SyncIssueDescriber.keptRejecting(.deleteTag("g")) == "The server kept rejecting this change.")
    }

    @Test("021-FR-003 021-FR-028 the outcome a merge kept off the account's project is shown in full, never clipped")
    func keptOutcomeInFull() {
        let outcome = String(repeating: "o", count: 1_000)
        let issue = SyncIssue(
            command: .setProjectOutcome(project: "p", outcome: outcome), message: GTDValidationError.outcomeKept.message,
            referenceID: "ref-1", occurredAt: Fixture.at(0)
        )
        let description = SyncIssueDescriber.describe(issue, in: state)
        #expect(description.attempted == "Desired outcome for “Work”")
        #expect(description.why == "Kept the desired outcome already on your account. Yours is below, so you can copy it.")
        #expect(description.keptOutcome == outcome && description.keptOutcome?.count == 1_000)
    }

    @Test("021-FR-003 a merge that did not archive the account's project says so")
    func archiveNotMerged() {
        let issue = SyncIssue(
            command: .archiveProject("p"), message: GTDValidationError.archiveNotMerged("Old flat").message,
            referenceID: "ref-2", occurredAt: Fixture.at(0)
        )
        let description = SyncIssueDescriber.describe(issue, in: state)
        #expect(description.attempted == "Archive project “Work”")
        #expect(
            description.why
                == "Your account already has an active project called “Old flat”. This Mac's tasks were added to it, and it stays active."
        )
    }

    @Test("021-FR-011 the server-out-of-date, archived-elsewhere and deleted-elsewhere reasons")
    func otherReasons() {
        #expect(
            SyncIssueDescriber.serverStillClears(project: "Old flat")
                == "Your account's server is out of date, so archiving “Old flat” removed its tasks from the project."
        )
        #expect(
            SyncIssueDescriber.archivedElsewhere(project: "Old flat")
                == "Project “Old flat” was archived on another device, so the task was added without a project."
        )
        #expect(
            SyncIssueDescriber.deletedElsewhere(task: "Buy milk")
                == "Couldn't save your change to “Buy milk”: it was deleted on another device."
        )
    }

    @Test("021-FR-015 021-SC-004 every description carries the issue's reference id")
    func referenceIDs() {
        let commands: [GTDCommand] = [
            .archiveProject("p"), .unarchiveProject(project: "old"), .setProjectOutcome(project: "p", outcome: "x"),
            .updateTask(.init(taskID: "t", changes: .init(title: .set("A")))), .createTask(.init(taskID: "n", title: "T", list: .inbox)),
        ]
        for (index, command) in commands.enumerated() {
            let issue = SyncIssue(command: command, message: "why", referenceID: "ref-\(index)", occurredAt: Fixture.at(0))
            let description = SyncIssueDescriber.describe(issue, in: state)
            #expect(description.referenceID == "ref-\(index)" && description.why == "why" && !description.attempted.isEmpty)
        }
    }
}

extension GTDCommand {
    fileprivate static func completeTask(_ id: TaskID) -> GTDCommand {
        .transitionTask(.init(taskID: id, action: .complete))
    }
}
