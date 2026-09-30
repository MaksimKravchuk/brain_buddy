import Foundation
import Testing

@testable import BrainBuddyCore

@Suite("OutboxReplayer")
struct ReplayTests {
    @Test("An empty outbox leaves the base as it is")
    func emptyOutbox() {
        let result = OutboxReplayer.replay([], onto: Fixture.base)
        #expect(result == ReplayResult(state: Fixture.base, outbox: [], rejected: []))
    }

    @Test("Operations apply in order, each at its own issue time, and stay queued")
    func appliesInOrder() {
        let outbox = [
            Fixture.operation(.createTask(.init(taskID: "t", title: "T", list: .inbox)), at: 10),
            Fixture.operation(.transitionTask(.init(taskID: "t", action: .complete)), at: 20),
        ]
        let result = OutboxReplayer.replay(outbox, onto: Fixture.base)
        #expect(result.outbox == outbox && result.rejected.isEmpty)
        #expect(result.state.tasks["t"]?.createdAt == Fixture.at(10))
        #expect(result.state.tasks["t"]?.completedAt == Fixture.at(20))
        #expect(OutboxReplayer.replay(outbox, onto: Fixture.base) == result, "replay is deterministic")
    }

    @Test("An operation whose goal already holds on the server is dropped")
    func dropsSatisfied() {
        let outbox = [
            Fixture.operation(.transitionTask(.init(taskID: "done", action: .complete)), at: 1),
            Fixture.operation(.transitionTask(.init(taskID: "next", action: .move, toList: .next)), at: 2),
            Fixture.operation(.deleteTag("gone"), at: 3),
            Fixture.operation(.archiveProject("old"), at: 4),
            Fixture.operation(.transitionTask(.init(taskID: "next", action: .complete)), at: 5),
        ]
        let result = OutboxReplayer.replay(outbox, onto: Fixture.base)
        #expect(result.outbox == [outbox[4]])
        #expect(result.rejected.isEmpty)
        #expect(result.state.tasks["next"]?.state == .completed)
    }

    @Test("A creation the server already acknowledged under the same id is dropped")
    func dropsAcknowledgedCreation() {
        let outbox = [Fixture.operation(.createTask(.init(taskID: "next", title: "Next task", list: .next)), at: 1)]
        let result = OutboxReplayer.replay(outbox, onto: Fixture.base)
        #expect(result.outbox.isEmpty && result.rejected.isEmpty && result.state == Fixture.base)
    }

    @Test("A violated rule sets the operation aside; the rest still apply, dependants are rejected in turn")
    func rejects() {
        var base = Fixture.base
        base.tasks["next"]?.state = .completed  // completed elsewhere
        let outbox = [
            Fixture.operation(.transitionTask(.init(taskID: "next", action: .move, toList: .someday)), at: 1),
            Fixture.operation(.createTask(.init(taskID: "t", title: "T", list: .waiting)), at: 2),
            Fixture.operation(.createSubtask(.init(taskID: "t", subtaskID: "s", title: "S")), at: 3),
            Fixture.operation(.updateTask(.init(taskID: "inbox", changes: .init(priority: .set(.high)))), at: 4),
        ]
        let result = OutboxReplayer.replay(outbox, onto: base)
        #expect(result.rejected.map(\.error) == [.taskNotOpen, .waitingForRequired, .taskNotFound])
        #expect(result.rejected.map(\.operation) == Array(outbox[0..<3]))
        #expect(result.outbox == [outbox[3]])
        #expect(result.state.tasks["inbox"]?.priority == .high)
    }

    // MARK: References that went away elsewhere

    @Test("A task captured offline in a project archived and with a tag deleted elsewhere is kept without them")
    func captureOutlivesArchivedReferences() throws {
        let outbox = [
            Fixture.operation(
                .createTask(
                    .init(taskID: "milk", title: "Buy milk", list: .next, projectID: "old", tagIDs: ["gone", "home"])
                ),
                at: 1
            ),
            Fixture.operation(.createSubtask(.init(taskID: "milk", subtaskID: "s", title: "Oat")), at: 2),
            Fixture.operation(.createTask(.init(taskID: "bread", title: "Bread", list: .inbox, projectID: "never")), at: 3),
        ]
        let result = OutboxReplayer.replay(outbox, onto: Fixture.base)
        #expect(result.rejected.isEmpty)
        let milk = try #require(result.state.tasks["milk"])
        #expect(milk.projectID == nil && milk.tagIDs == ["home"] && milk.state == .next)
        #expect(milk.subtasks.map(\.title) == ["Oat"], "what depends on the task still applies")
        #expect(result.state.tasks["bread"]?.projectID == nil, "a project that was never created is dropped too")
        #expect(
            result.outbox.map(\.command) == [
                .createTask(.init(taskID: "milk", title: "Buy milk", list: .next, tagIDs: ["home"])),
                outbox[1].command,
                .createTask(.init(taskID: "bread", title: "Bread", list: .inbox)),
            ],
            "the server is sent what was applied"
        )
        #expect(result.outbox.map(\.id) == outbox.map(\.id) && result.outbox.map(\.idempotencyKey) == outbox.map(\.idempotencyKey))
    }

    @Test("A sent operation keeps the body its idempotency key is bound to; the state still shows what applies")
    func sentOperationKeepsItsBody() {
        let outbox = [
            Fixture.operation(.createTask(.init(taskID: "milk", title: "Buy milk", list: .next, tagIDs: ["gone"])), at: 1, sent: true)
        ]
        let result = OutboxReplayer.replay(outbox, onto: Fixture.base)
        #expect(result.rejected.isEmpty)
        #expect(result.outbox == outbox)
        #expect(result.state.tasks["milk"]?.tagIDs == [])
    }

    @Test("A folded edit loses only the field its task can no longer take")
    func foldedEditIsNotRejectedWhole() {
        var base = Fixture.base
        // Another device moved the task out of Waiting, which cleared its note.
        base.tasks["waiting"]?.state = .next
        base.tasks["waiting"]?.waitingFor = nil
        base.tasks["waiting"]?.waitingSince = nil
        let folded = Fixture.compacted([
            .updateTask(.init(taskID: "waiting", changes: .init(title: .set("Contract v2")))),
            .updateTask(.init(taskID: "waiting", changes: .init(waitingFor: .set("Alice (legal)")))),
            .updateTask(.init(taskID: "waiting", changes: .init(projectID: .set("old"), tagIDs: .set(["gone", "home"])))),
        ])
        #expect(folded.count == 1, "the three edits fold into one request")

        let result = OutboxReplayer.replay(folded, onto: base)
        #expect(result.rejected.isEmpty)
        let task = result.state.tasks["waiting"]
        #expect(task?.title == "Contract v2" && task?.state == .next && task?.waitingFor == nil)
        #expect(task?.projectID == nil && task?.tagIDs == ["home"])
        #expect(
            result.outbox.map(\.command) == [
                .updateTask(
                    .init(taskID: "waiting", changes: .init(title: .set("Contract v2"), projectID: .clear, tagIDs: .set(["home"])))
                )
            ]
        )

        let unfolded = [
            Fixture.operation(.updateTask(.init(taskID: "waiting", changes: .init(title: .set("Contract v2")))), at: 1),
            Fixture.operation(.updateTask(.init(taskID: "waiting", changes: .init(waitingFor: .set("Alice (legal)")))), at: 2),
        ]
        let separate = OutboxReplayer.replay(unfolded, onto: base)
        #expect(separate.rejected.isEmpty, "an edit with nothing left to apply is satisfied, not rejected")
        #expect(separate.outbox == [unfolded[0]])
        #expect(separate.state.tasks["waiting"]?.title == "Contract v2")
        #expect(separate.state.tasks["waiting"]?.waitingFor == nil)
    }

    // MARK: Merges by name

    @Test("A project created offline under a name the server already has merges; references follow it, edits do not")
    func mergesProjects() throws {
        let outbox = [
            Fixture.operation(.createProject(.init(projectID: "local", name: " work ", color: "#000000")), at: 1),
            Fixture.operation(.createTask(.init(taskID: "t", title: "T", list: .next, projectID: "local")), at: 2),
            Fixture.operation(.updateTask(.init(taskID: "next", changes: .init(projectID: .set("local")))), at: 3),
            Fixture.operation(.updateProject(.init(projectID: "local", color: .set("#FFFFFF"))), at: 4),
            Fixture.operation(.updateProject(.init(projectID: "local", name: "Job")), at: 5),
        ]
        let result = OutboxReplayer.replay(outbox, onto: Fixture.base)
        #expect(result.rejected.isEmpty)
        #expect(result.state.projects["local"] == nil)
        #expect(result.state.tasks["t"]?.projectID == "work" && result.state.tasks["next"]?.projectID == "work")
        #expect(result.state.projects == Fixture.base.projects, "the account's project keeps its name and colour")
        #expect(result.outbox.map(\.command) == outbox[1...2].map { $0.command.replacing(project: "local", with: "work") })
        #expect(result.outbox.map(\.id) == outbox[1...2].map(\.id), "rewritten operations keep their identity")
    }

    @Test("Archiving a project that merged by name leaves the account's project alone; its tasks lose it")
    func mergedProjectArchiveIsNotRetargeted() throws {
        let outbox = [
            Fixture.operation(.createProject(.init(projectID: "local", name: "work")), at: 1),
            Fixture.operation(.createTask(.init(taskID: "t", title: "T", list: .next, projectID: "local")), at: 2),
            Fixture.operation(.updateTask(.init(taskID: "done", changes: .init(projectID: .set("local")))), at: 3),
            Fixture.operation(.archiveProject("local"), at: 4),
            Fixture.operation(.updateProject(.init(projectID: "local", name: "Archived work")), at: 5),
        ]
        let result = OutboxReplayer.replay(outbox, onto: Fixture.base)
        #expect(result.rejected.isEmpty)
        #expect(result.state.projects == Fixture.base.projects, "Work is neither archived nor renamed")
        #expect(result.state.tasks["inbox"]?.projectID == "work", "the account's own tasks stay in Work")
        #expect(result.state.tasks["t"]?.projectID == nil && result.state.tasks["done"]?.projectID == nil)
        #expect(
            result.outbox.map(\.command) == [
                .createTask(.init(taskID: "t", title: "T", list: .next)),
                .updateTask(.init(taskID: "done", changes: .init(projectID: .clear))),
            ]
        )
    }

    @Test("A tag created offline under a taken name merges; a task naming both keeps one; renames do not follow")
    func mergesTags() {
        let outbox = [
            Fixture.operation(.createTag(.init(tagID: "local", name: "@Home")), at: 1),
            Fixture.operation(.createTask(.init(taskID: "t", title: "T", list: .next, tagIDs: ["local", "home"])), at: 2),
            Fixture.operation(.renameTag(.init(tagID: "local", name: "House")), at: 3),
        ]
        let result = OutboxReplayer.replay(outbox, onto: Fixture.base)
        #expect(result.rejected.isEmpty)
        #expect(result.outbox.map(\.command) == [.createTask(.init(taskID: "t", title: "T", list: .next, tagIDs: ["home"]))])
        #expect(result.state.tags == Fixture.base.tags, "the account's tag keeps its name")
        #expect(result.state.tasks["t"]?.tagIDs == ["home"])
    }

    @Test("Deleting a tag that merged by name leaves the account's tag alone; its tasks lose it")
    func mergedTagDeleteIsNotRetargeted() {
        let outbox = [
            Fixture.operation(.createTag(.init(tagID: "local", name: "@Home")), at: 1),
            Fixture.operation(.createTask(.init(taskID: "t", title: "T", list: .next, tagIDs: ["local", "home"])), at: 2),
            Fixture.operation(.createTask(.init(taskID: "u", title: "U", list: .next, tagIDs: ["local"])), at: 3),
            Fixture.operation(.deleteTag("local"), at: 4),
        ]
        let result = OutboxReplayer.replay(outbox, onto: Fixture.base)
        #expect(result.rejected.isEmpty)
        #expect(result.state.tags["home"]?.state == .active)
        #expect(result.state.tasks["inbox"]?.tagIDs == ["home"], "the account's own tasks keep the tag")
        #expect(result.state.tasks["t"]?.tagIDs == ["home"], "a tag the task named itself stays")
        #expect(result.state.tasks["u"]?.tagIDs == [])
        #expect(
            result.outbox.map(\.command) == [
                .createTask(.init(taskID: "t", title: "T", list: .next, tagIDs: ["home"])),
                .createTask(.init(taskID: "u", title: "U", list: .next)),
            ]
        )
    }

    @Test("Signing in with a throwaway project and tag of the same names leaves the account's records alone")
    func throwawayRecordsDoNotTouchTheAccount() {
        let account = Fixture.state(
            tasks: [
                Fixture.task("report", "Quarterly report", state: .next, projectID: "work"),
                Fixture.task("invoice", "Pay invoice", state: .next, tagIDs: ["urgent"]),
            ],
            projects: [Fixture.project("work", "Work")],
            tags: [Fixture.tag("urgent", "urgent")]
        )
        // Recorded one by one, as a device without an account would before compaction.
        let outbox = [
            Fixture.operation(.createProject(.init(projectID: "mine", name: "work")), at: 1),
            Fixture.operation(.archiveProject("mine"), at: 2),
            Fixture.operation(.createTag(.init(tagID: "mytag", name: "Urgent")), at: 3),
            Fixture.operation(.deleteTag("mytag"), at: 4),
        ]
        let result = OutboxReplayer.replay(outbox, onto: account)
        #expect(result == ReplayResult(state: account, outbox: [], rejected: []))
    }

    @Test("A rename to a name taken on the server is rejected, not merged")
    func renameCollision() {
        var base = Fixture.base
        base.projects["home"] = Fixture.project("home", "Home")
        let outbox = [Fixture.operation(.updateProject(.init(projectID: "work", name: "HOME")), at: 1)]
        let result = OutboxReplayer.replay(outbox, onto: base)
        #expect(result.rejected.map(\.error) == [.duplicateProjectName("Home")])
        #expect(result.outbox.isEmpty && result.state == base)
    }
}

@Suite("GTDCommand.replacing")
struct ReplacingTests {
    private let changes = TaskChanges(projectID: .set("old"), tagIDs: .set(["a", "old", "b"]))

    @Test("Every project reference is rewritten")
    func projects() {
        let cases: [(GTDCommand, GTDCommand)] = [
            (.createProject(.init(projectID: "old", name: "N")), .createProject(.init(projectID: "new", name: "N"))),
            (.updateProject(.init(projectID: "old", name: "N")), .updateProject(.init(projectID: "new", name: "N"))),
            (.archiveProject("old"), .archiveProject("new")),
            (
                .createTask(.init(taskID: "t", title: "T", list: .inbox, projectID: "old")),
                .createTask(.init(taskID: "t", title: "T", list: .inbox, projectID: "new"))
            ),
            (
                .updateTask(.init(taskID: "t", changes: changes)),
                .updateTask(.init(taskID: "t", changes: .init(projectID: .set("new"), tagIDs: .set(["a", "old", "b"]))))
            ),
        ]
        for (command, expected) in cases {
            #expect(command.replacing(project: "old", with: "new") == expected)
        }
    }

    @Test("Every tag reference is rewritten, without duplicating a tag")
    func tags() {
        let cases: [(GTDCommand, GTDCommand)] = [
            (.createTag(.init(tagID: "old", name: "N")), .createTag(.init(tagID: "new", name: "N"))),
            (.renameTag(.init(tagID: "old", name: "N")), .renameTag(.init(tagID: "new", name: "N"))),
            (.deleteTag("old"), .deleteTag("new")),
            (
                .createTask(.init(taskID: "t", title: "T", list: .inbox, tagIDs: ["new", "old"])),
                .createTask(.init(taskID: "t", title: "T", list: .inbox, tagIDs: ["new"]))
            ),
            (
                .updateTask(.init(taskID: "t", changes: changes)),
                .updateTask(.init(taskID: "t", changes: .init(projectID: .set("old"), tagIDs: .set(["a", "new", "b"]))))
            ),
        ]
        for (command, expected) in cases {
            #expect(command.replacing(tag: "old", with: "new") == expected)
        }
    }

    @Test("Unrelated commands and cleared fields are left alone")
    func unrelated() {
        let commands: [GTDCommand] = [
            .createProject(.init(projectID: "other", name: "N")),
            .archiveProject("other"),
            .deleteTag("other"),
            .updateTask(.init(taskID: "t", changes: .init(projectID: .clear, tagIDs: .clear))),
            .transitionTask(.init(taskID: "t", action: .complete)),
            .createSubtask(.init(taskID: "t", subtaskID: "s", title: "S")),
            .updateSubtask(.init(taskID: "t", subtaskID: "s", title: "S")),
            .transitionSubtask(.init(taskID: "t", subtaskID: "s", action: .complete)),
            .createComment(.init(taskID: "t", commentID: "c", body: "B")),
            .updateComment(.init(taskID: "t", commentID: "c", body: "B")),
        ]
        for command in commands {
            #expect(command.replacing(project: "old", with: "new") == command)
            #expect(command.replacing(tag: "old", with: "new") == command)
        }
    }
}

/// The rewrite shared by replay merges and sync's 409 duplicate-name adoption.
@Suite("OutboxReplayer.rewritingAfterMerge")
struct RewritingAfterMergeTests {
    private func operations(_ commands: [GTDCommand]) -> [PendingOperation] {
        commands.enumerated().map { Fixture.operation($0.element, at: $0.offset) }
    }

    private let unrelated: [GTDCommand] = [
        .createProject(.init(projectID: "other", name: "Other")),
        .updateProject(.init(projectID: "other", name: "Else")),
        .archiveProject("other"),
        .createTag(.init(tagID: "other", name: "other")),
        .renameTag(.init(tagID: "other", name: "else")),
        .deleteTag("other"),
        .transitionTask(.init(taskID: "t", action: .complete)),
        .createSubtask(.init(taskID: "t", subtaskID: "s", title: "S")),
        .createComment(.init(taskID: "t", commentID: "c", body: "B")),
        .updateTask(.init(taskID: "t", changes: .init(projectID: .clear, tagIDs: .clear))),
    ]

    @Test("Project references follow the merge; the local record's creation, rename and recolour are dropped")
    func projectReferencesFollow() {
        let outbox = operations(
            [
                .createProject(.init(projectID: "old", name: "Work", color: "#111111")),
                .createTask(.init(taskID: "a", title: "A", list: .next, projectID: "old")),
                .updateProject(.init(projectID: "old", name: "Job")),
                .updateTask(.init(taskID: "b", changes: .init(title: .set("B"), projectID: .set("old")))),
                .updateProject(.init(projectID: "old", color: .set("#222222"))),
            ] + unrelated
        )
        let rewritten = OutboxReplayer.rewritingAfterMerge(outbox, project: "old", into: "new")
        #expect(
            rewritten.map(\.command) == [
                .createTask(.init(taskID: "a", title: "A", list: .next, projectID: "new")),
                .updateTask(.init(taskID: "b", changes: .init(title: .set("B"), projectID: .set("new")))),
            ] + unrelated
        )
        #expect(rewritten.map(\.id) == [outbox[1], outbox[3]].map(\.id) + outbox[5...].map(\.id))
    }

    @Test("An archive of the merged project is dropped, and its tasks lose the project instead of following it")
    func projectArchiveIsWithdrawn() {
        let outbox = operations(
            [
                .createTask(.init(taskID: "a", title: "A", list: .next, projectID: "old")),
                .updateTask(.init(taskID: "b", changes: .init(title: .set("B"), projectID: .set("old")))),
                .archiveProject("old"),
                .updateProject(.init(projectID: "old", name: "Old work")),
            ] + unrelated
        )
        let rewritten = OutboxReplayer.rewritingAfterMerge(outbox, project: "old", into: "new")
        #expect(
            rewritten.map(\.command) == [
                .createTask(.init(taskID: "a", title: "A", list: .next)),
                .updateTask(.init(taskID: "b", changes: .init(title: .set("B"), projectID: .clear))),
            ] + unrelated
        )
        #expect(!rewritten.contains { $0.command == .archiveProject("new") }, "the survivor is never archived")
    }

    @Test("Sync's adoption: once the refused creation is gone, a queued archive of it goes too")
    func adoptionDropsTheArchive() {
        let outbox = operations([
            .archiveProject("mine"), .createTask(.init(taskID: "a", title: "A", list: .inbox)),
        ])
        #expect(OutboxReplayer.rewritingAfterMerge(outbox, project: "mine", into: "work") == [outbox[1]])
    }

    @Test("Tag references follow the merge without repeating a tag; the local tag's creation and rename are dropped")
    func tagReferencesFollow() {
        let outbox = operations(
            [
                .createTag(.init(tagID: "old", name: "home")),
                .createTask(.init(taskID: "a", title: "A", list: .next, tagIDs: ["new", "old"])),
                .renameTag(.init(tagID: "old", name: "house")),
                .updateTask(.init(taskID: "b", changes: .init(tagIDs: .set(["x", "old"])))),
            ] + unrelated
        )
        let rewritten = OutboxReplayer.rewritingAfterMerge(outbox, tag: "old", into: "new")
        #expect(
            rewritten.map(\.command) == [
                .createTask(.init(taskID: "a", title: "A", list: .next, tagIDs: ["new"])),
                .updateTask(.init(taskID: "b", changes: .init(tagIDs: .set(["x", "new"])))),
            ] + unrelated
        )
    }

    @Test("A delete of the merged tag is dropped, and its tasks lose the tag instead of following it")
    func tagDeleteIsWithdrawn() {
        let outbox = operations(
            [
                .createTask(.init(taskID: "a", title: "A", list: .next, tagIDs: ["new", "old"])),
                .updateTask(.init(taskID: "b", changes: .init(tagIDs: .set(["old"])))),
                .deleteTag("old"),
                .renameTag(.init(tagID: "old", name: "gone")),
            ] + unrelated
        )
        let rewritten = OutboxReplayer.rewritingAfterMerge(outbox, tag: "old", into: "new")
        #expect(
            rewritten.map(\.command) == [
                .createTask(.init(taskID: "a", title: "A", list: .next, tagIDs: ["new"])),
                .updateTask(.init(taskID: "b", changes: .init(tagIDs: .set([])))),
            ] + unrelated
        )
        #expect(!rewritten.contains { $0.command == .deleteTag("new") }, "the survivor is never deleted")
    }
}
