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
            Fixture.operation(.createTask(.init(taskID: "t", title: "T", list: .next, projectID: "old")), at: 2),
            Fixture.operation(.createSubtask(.init(taskID: "t", subtaskID: "s", title: "S")), at: 3),
            Fixture.operation(.updateTask(.init(taskID: "inbox", changes: .init(priority: .set(.high)))), at: 4),
        ]
        let result = OutboxReplayer.replay(outbox, onto: base)
        #expect(result.rejected.map(\.error) == [.taskNotOpen, .projectNotActive, .taskNotFound])
        #expect(result.rejected.map(\.operation) == Array(outbox[0..<3]))
        #expect(result.outbox == [outbox[3]])
        #expect(result.state.tasks["inbox"]?.priority == .high)
    }

    @Test("A project created offline under a name the server already has merges, and later operations follow it")
    func mergesProjects() throws {
        let outbox = [
            Fixture.operation(.createProject(.init(projectID: "local", name: " work ")), at: 1),
            Fixture.operation(.createTask(.init(taskID: "t", title: "T", list: .next, projectID: "local")), at: 2),
            Fixture.operation(.updateTask(.init(taskID: "next", changes: .init(projectID: .set("local")))), at: 3),
            Fixture.operation(.updateProject(.init(projectID: "local", color: .set("#FFFFFF"))), at: 4),
        ]
        let result = OutboxReplayer.replay(outbox, onto: Fixture.base)
        #expect(result.rejected.isEmpty)
        #expect(result.state.projects["local"] == nil)
        #expect(result.state.tasks["t"]?.projectID == "work" && result.state.tasks["next"]?.projectID == "work")
        #expect(result.state.projects["work"]?.color == "#FFFFFF")
        #expect(result.outbox.map(\.command) == outbox[1...].map { $0.command.replacing(project: "local", with: "work") })
        #expect(result.outbox.map(\.id) == outbox[1...].map(\.id), "rewritten operations keep their identity")
    }

    @Test("A tag created offline under a taken name merges; a task naming both keeps one")
    func mergesTags() {
        let outbox = [
            Fixture.operation(.createTag(.init(tagID: "local", name: "@Home")), at: 1),
            Fixture.operation(.createTask(.init(taskID: "t", title: "T", list: .next, tagIDs: ["local", "home"])), at: 2),
            Fixture.operation(.deleteTag("local"), at: 3),
        ]
        let result = OutboxReplayer.replay(outbox, onto: Fixture.base)
        #expect(result.rejected.isEmpty)
        guard case .createTask(let create) = result.outbox.first?.command else {
            Issue.record("expected the task creation to stay queued")
            return
        }
        #expect(create.tagIDs == ["home"])
        #expect(result.outbox.last?.command == .deleteTag("home"))
        #expect(result.state.tags["home"]?.state == .deleted && result.state.tasks["t"]?.tagIDs == [])
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
