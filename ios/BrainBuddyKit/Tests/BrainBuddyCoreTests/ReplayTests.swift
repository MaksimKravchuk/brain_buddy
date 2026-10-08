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

    @Test("021-FR-003 an archive of a project that merged by name is reported, and its tasks follow the survivor")
    func mergedProjectArchiveIsNotRetargeted() throws {
        let outbox = [
            Fixture.operation(.createProject(.init(projectID: "local", name: "work")), at: 1),
            Fixture.operation(.createTask(.init(taskID: "t", title: "T", list: .next, projectID: "local")), at: 2),
            Fixture.operation(.updateTask(.init(taskID: "done", changes: .init(projectID: .set("local")))), at: 3),
            Fixture.operation(.archiveProject("local"), at: 4),
            Fixture.operation(.updateProject(.init(projectID: "local", name: "Archived work")), at: 5),
        ]
        let result = OutboxReplayer.replay(outbox, onto: Fixture.base)
        #expect(result.rejected == [RejectedOperation(operation: outbox[3], error: .archiveNotMerged("Work"))])
        #expect(result.state.projects == Fixture.base.projects, "Work is neither archived nor renamed")
        #expect(result.state.tasks["inbox"]?.projectID == "work", "the account's own tasks stay in Work")
        #expect(result.state.tasks["t"]?.projectID == "work" && result.state.tasks["done"]?.projectID == "work")
        #expect(
            result.outbox.map(\.command) == [.createTask(.init(taskID: "t", title: "T", list: .next, projectID: "work"))],
            "the edit that moved a task into the survivor finds it there already"
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
        #expect(result == ReplayResult(state: account, outbox: [], rejected: [RejectedOperation(operation: outbox[1], error: .archiveNotMerged("Work"))]))
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

    private let survivor = Fixture.project("new", "New")

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
        let rewritten = OutboxReplayer.rewritingAfterMerge(outbox, project: "old", into: survivor, issuedAt: Fixture.at(0)).outbox
        #expect(
            rewritten.map(\.command) == [
                .createTask(.init(taskID: "a", title: "A", list: .next, projectID: "new")),
                .updateTask(.init(taskID: "b", changes: .init(title: .set("B"), projectID: .set("new")))),
            ] + unrelated
        )
        #expect(rewritten.map(\.id) == [outbox[1], outbox[3]].map(\.id) + outbox[5...].map(\.id))
    }

    @Test("021-FR-003 an archive of the merged project is reported, not sent, and its tasks follow the survivor")
    func projectArchiveIsReported() {
        let outbox = operations(
            [
                .createTask(.init(taskID: "a", title: "A", list: .next, projectID: "old")),
                .updateTask(.init(taskID: "b", changes: .init(title: .set("B"), projectID: .set("old")))),
                .archiveProject("old"),
                .unarchiveProject(project: "old"),
                .updateProject(.init(projectID: "old", name: "Old work")),
            ] + unrelated
        )
        let merge = OutboxReplayer.rewritingAfterMerge(outbox, project: "old", into: survivor, issuedAt: Fixture.at(0))
        #expect(
            merge.outbox.map(\.command) == [
                .createTask(.init(taskID: "a", title: "A", list: .next, projectID: "new")),
                .updateTask(.init(taskID: "b", changes: .init(title: .set("B"), projectID: .set("new")))),
            ] + unrelated
        )
        #expect(merge.rejected == [RejectedOperation(operation: outbox[2], error: .archiveNotMerged("New"))])
        #expect(!merge.outbox.contains { $0.command == .archiveProject("new") }, "the survivor is never archived")
    }

    @Test("021-FR-003 sync's adoption: once the refused creation is gone, a queued archive of it is reported")
    func adoptionReportsTheArchive() {
        let outbox = operations([
            .archiveProject("mine"), .createTask(.init(taskID: "a", title: "A", list: .inbox, projectID: "mine")),
        ])
        let merge = OutboxReplayer.rewritingAfterMerge(outbox, project: "mine", into: survivor, issuedAt: Fixture.at(0))
        #expect(merge.outbox.map(\.command) == [.createTask(.init(taskID: "a", title: "A", list: .inbox, projectID: "new"))])
        #expect(merge.rejected.map(\.error) == [.archiveNotMerged("New")])
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

@Suite("OutboxReplayer.withoutAssignments")
struct WithoutAssignmentsTests {
    @Test("021-FR-011 021-FR-026 a project that refused to unarchive keeps the tasks queued for it out of it")
    func keepsQueuedTasksOut() {
        let outbox = [
            Fixture.operation(.createTask(.init(taskID: "a", title: "A", list: .inbox, projectID: "shed")), at: 1),
            Fixture.operation(.updateTask(.init(taskID: "b", changes: .init(title: .set("B"), projectID: .set("shed")))), at: 2),
            Fixture.operation(.updateTask(.init(taskID: "c", changes: .init(projectID: .set("shed")))), at: 3),
            Fixture.operation(.createTask(.init(taskID: "d", title: "D", list: .inbox, projectID: "other")), at: 4),
            Fixture.operation(.updateTask(.init(taskID: "e", changes: .init(projectID: .clear))), at: 5),
        ]
        let result = OutboxReplayer.withoutAssignments(to: "shed", in: outbox)
        #expect(result.affected == 3)
        #expect(
            result.outbox.map(\.command) == [
                .createTask(.init(taskID: "a", title: "A", list: .inbox)),
                .updateTask(.init(taskID: "b", changes: .init(title: .set("B")))),
                outbox[3].command, outbox[4].command,
            ],
            "a moved-in task keeps its other edits; an edit with nothing left goes"
        )
        #expect(result.outbox.map(\.id) == [outbox[0], outbox[1], outbox[3], outbox[4]].map(\.id))
    }
}

/// The merge table of contracts/kit-commands.md §3 (ADR-0020): what happens to
/// a local project, its tasks and its outcome when an account project has the same name.
@Suite("OutboxReplayer: merging by name under lossless archive")
struct ReplayLosslessMergeTests {
    private static let outcome = String(repeating: "o", count: 1_000)

    /// The legacy import's outbox shape for an archived "Old flat" with three tasks.
    private func importedArchive(outcome: String? = nil, extra: [GTDCommand] = []) -> [PendingOperation] {
        let commands: [GTDCommand] =
            [.createProject(.init(projectID: "local", name: "Old flat", desiredOutcome: outcome))]
            + ["a", "b", "c"].map { .createTask(.init(taskID: TaskID($0), title: "Task \($0)", list: .next, projectID: "local")) }
            + [.archiveProject("local")] + extra
        return commands.enumerated().map { Fixture.operation($0.element, at: $0.offset + 1) }
    }

    private func account(_ state: ProjectState, outcome: String? = nil) -> GTDState {
        var project = Fixture.project("flat", "Old flat", state: state)
        project.desiredOutcome = outcome
        return Fixture.state(projects: [project])
    }

    @Test("021-FR-003 021-SC-003 an archived local project meets an active account project: membership follows, nothing is archived")
    func archivedAgainstActive() throws {
        let outbox = importedArchive()
        let result = OutboxReplayer.replay(outbox, onto: account(.active))
        #expect(result.state.projects.count == 1 && result.state.projects["flat"]?.state == .active)
        for id: TaskID in ["a", "b", "c"] { #expect(result.state.tasks[id]?.projectID == "flat") }
        #expect(result.outbox.map(\.id) == outbox[1...3].map(\.id), "the three creations stay, in the account's project")
        #expect(result.outbox.allSatisfy { $0.command.taskID != nil })
        #expect(result.rejected == [RejectedOperation(operation: outbox[4], error: .archiveNotMerged("Old flat"))])
    }

    @Test("021-FR-003 an active local project beside an archived-only account project stays a separate active project")
    func activeAgainstArchivedOnly() {
        let outbox = Array(importedArchive().dropLast())
        let result = OutboxReplayer.replay(outbox, onto: account(.archived))
        #expect(result.rejected.isEmpty && result.state.projects.count == 2)
        #expect(result.state.projects["local"]?.state == .active && result.state.projects["flat"]?.state == .archived)
    }

    @Test("021-SC-003 an archived local project beside an archived-only account project gives two archived projects")
    func archivedAgainstArchivedOnly() {
        let result = OutboxReplayer.replay(importedArchive(), onto: account(.archived))
        #expect(result.rejected.isEmpty && result.state.projects.count == 2)
        #expect(result.state.projects.values.allSatisfy { $0.state == .archived })
        #expect(result.state.tasks.values.allSatisfy { $0.projectID == "local" }, "membership kept: the tasks stay with the local one")
        let activeNames = result.state.projects.values.filter { $0.state == .active }.map { NameNormalizer.project($0.name) }
        #expect(Set(activeNames).count == activeNames.count, "duplicates are counted on active names only")
    }

    @Test("021-FR-003 021-FR-028 both sides have an outcome: the account's stays and the issue carries the full local text")
    func bothHaveAnOutcome() throws {
        let outbox = importedArchive(outcome: Self.outcome)
        let result = OutboxReplayer.replay(outbox, onto: account(.active, outcome: "Theirs"))
        #expect(result.state.projects["flat"]?.desiredOutcome == "Theirs")
        #expect(!result.outbox.contains { if case .setProjectOutcome = $0.command { true } else { false } })
        let kept = try #require(result.rejected.first { $0.error == .outcomeKept })
        #expect(kept.operation.command == .setProjectOutcome(project: "flat", outcome: Self.outcome))
        #expect(GTDValidationError.outcomeKept.message == "Kept the desired outcome already on your account. Yours is below, so you can copy it.")
    }

    @Test("021-FR-003 021-FR-028 a survivor without an outcome gets the local one, re-issued once")
    func survivorWithoutAnOutcome() throws {
        let result = OutboxReplayer.replay(importedArchive(outcome: "Mine"), onto: account(.active))
        #expect(result.state.projects["flat"]?.desiredOutcome == "Mine")
        let reissued = result.outbox.filter { if case .setProjectOutcome = $0.command { true } else { false } }
        #expect(reissued.map(\.command) == [.setProjectOutcome(project: "flat", outcome: "Mine")])
        #expect(!result.rejected.contains { $0.error == .outcomeKept })
    }

    @Test("021-FR-003 021-FR-028 an outcome set after the local archive never reaches the account's project")
    func outcomeAfterTheArchive() throws {
        let later = importedArchive(outcome: "First", extra: [.setProjectOutcome(project: "local", outcome: "Later")])
        let kept = OutboxReplayer.replay(later, onto: account(.active, outcome: "Theirs"))
        #expect(kept.state.projects["flat"]?.desiredOutcome == "Theirs")
        #expect(!kept.outbox.contains { if case .setProjectOutcome = $0.command { true } else { false } }, "no PATCH carries it")
        #expect(kept.rejected.first { $0.error == .outcomeKept }?.operation.command == .setProjectOutcome(project: "flat", outcome: "Later"))
        let adopted = OutboxReplayer.replay(later, onto: account(.active))
        #expect(adopted.state.projects["flat"]?.desiredOutcome == "Later")
        #expect(adopted.outbox.filter { if case .setProjectOutcome = $0.command { true } else { false } }.count == 1)
    }

    @Test("021-FR-028 the same outcome on both sides is nothing to report")
    func sameOutcome() {
        let result = OutboxReplayer.replay(importedArchive(outcome: "Same"), onto: account(.active, outcome: "Same"))
        #expect(result.rejected.map(\.error) == [.archiveNotMerged("Old flat")])
    }
}
