import Foundation
import Testing

@testable import BrainBuddyCore

@Suite("GTDReducer: subtasks")
struct ReducerSubtaskTests {
    @Test("Subtasks append in order, on open and terminal tasks, without touching the task")
    func create() throws {
        var state = Fixture.base
        try apply(.createSubtask(.init(taskID: "done", subtaskID: "s1", title: "  First ")), to: &state, at: 3)
        try apply(.createSubtask(.init(taskID: "done", subtaskID: "s2", title: "Second")), to: &state, at: 4)
        let task = try #require(state.tasks["done"])
        #expect(task.subtasks.map(\.id) == ["s1", "s2"])
        #expect(task.subtasks.map(\.orderKey) == [0, 1])
        #expect(task.subtasks[0] == SubtaskRecord(id: "s1", title: "First", state: .open, orderKey: 0))
        #expect(task.updatedAt == Fixture.base.tasks["done"]?.updatedAt, "the server does not bump the parent")
    }

    @Test("Order keys continue after the highest existing one")
    func orderKeys() throws {
        var state = Fixture.state(
            tasks: [Fixture.task("t", subtasks: [SubtaskRecord(id: "a", title: "A", orderKey: 7)])]
        )
        try apply(.createSubtask(.init(taskID: "t", subtaskID: "b", title: "B")), to: &state)
        #expect(state.tasks["t"]?.subtasks.last?.orderKey == 8)
    }

    @Test("Creation rules")
    func createRules() throws {
        var state = Fixture.base
        try apply(.createSubtask(.init(taskID: "next", subtaskID: "s", title: "S")), to: &state)
        expectRejection(.createSubtask(.init(taskID: "missing", subtaskID: "x", title: "X")), on: state, .taskNotFound)
        expectRejection(.createSubtask(.init(taskID: "next", subtaskID: "x", title: " ")), on: state, .emptyTitle)
        expectRejection(.createSubtask(.init(taskID: "next", subtaskID: "s", title: "Again")), on: state, .idAlreadyExists)
        var replayed = state
        #expect(
            try apply(.createSubtask(.init(taskID: "next", subtaskID: "s", title: "S")), to: &replayed, mode: .replay)
                == .alreadySatisfied
        )
    }

    @Test("Rename and transition to any other state")
    func updateAndTransition() throws {
        var state = Fixture.base
        try apply(.createSubtask(.init(taskID: "next", subtaskID: "s", title: "S")), to: &state)
        try apply(.updateSubtask(.init(taskID: "next", subtaskID: "s", title: " Renamed ")), to: &state)
        #expect(state.tasks["next"]?.subtasks.first?.title == "Renamed")
        expectRejection(.updateSubtask(.init(taskID: "next", subtaskID: "s", title: "Renamed")), on: state, .nothingToChange)
        expectRejection(.updateSubtask(.init(taskID: "next", subtaskID: "x", title: "X")), on: state, .subtaskNotFound)

        try apply(.transitionSubtask(.init(taskID: "next", subtaskID: "s", action: .complete)), to: &state)
        #expect(state.tasks["next"]?.subtasks.first?.state == .completed)
        try apply(.transitionSubtask(.init(taskID: "next", subtaskID: "s", action: .cancel)), to: &state)
        #expect(state.tasks["next"]?.subtasks.first?.state == .cancelled)
        try apply(.transitionSubtask(.init(taskID: "next", subtaskID: "s", action: .reopen)), to: &state)
        #expect(state.tasks["next"]?.subtasks.first?.state == .open)
        #expect(state.tasks["next"]?.updatedAt == Fixture.base.tasks["next"]?.updatedAt)

        let reopen = GTDCommand.transitionSubtask(.init(taskID: "next", subtaskID: "s", action: .reopen))
        expectRejection(reopen, on: state, .subtaskAlreadyInState)
        var replayed = state
        #expect(try apply(reopen, to: &replayed, mode: .replay) == .alreadySatisfied)
        #expect(replayed == state)
        expectRejection(
            .transitionSubtask(.init(taskID: "next", subtaskID: "x", action: .complete)), on: state, .subtaskNotFound
        )
    }
}

@Suite("GTDReducer: comments")
struct ReducerCommentTests {
    @Test("Comments are stored verbatim, with no author until the server acknowledges them")
    func create() throws {
        var state = Fixture.base
        try apply(.createComment(.init(taskID: "done", commentID: "c", body: "  Called, no answer \n")), to: &state, at: 4)
        let comment = try #require(state.tasks["done"]?.comments.first)
        #expect(comment == CommentRecord(id: "c", body: "  Called, no answer \n", authorID: nil, createdAt: Fixture.at(4)))
        #expect(state.tasks["done"]?.updatedAt == Fixture.base.tasks["done"]?.updatedAt)
    }

    @Test("Only the empty string is rejected (the server does not trim comments); 20 000 scalars at most")
    func limits() throws {
        var state = Fixture.base
        try apply(.createComment(.init(taskID: "next", commentID: "space", body: " ")), to: &state)
        #expect(state.tasks["next"]?.comments.first?.body == " ")
        expectRejection(.createComment(.init(taskID: "next", commentID: "x", body: "")), on: state, .emptyComment)
        expectRejection(
            .createComment(.init(taskID: "next", commentID: "x", body: String(repeating: "c", count: 20_001))), on: state,
            .commentTooLong
        )
        expectRejection(.createComment(.init(taskID: "missing", commentID: "x", body: "Hi")), on: state, .taskNotFound)
        expectRejection(.createComment(.init(taskID: "next", commentID: "space", body: "Hi")), on: state, .idAlreadyExists)
    }

    @Test("Editing sets editedAt; an identical body changes nothing")
    func update() throws {
        var state = Fixture.base
        try apply(.createComment(.init(taskID: "next", commentID: "c", body: "Hi")), to: &state, at: 1)
        try apply(.updateComment(.init(taskID: "next", commentID: "c", body: "Hello")), to: &state, at: 2)
        let comment = try #require(state.tasks["next"]?.comments.first)
        #expect(comment.body == "Hello" && comment.editedAt == Fixture.at(2) && comment.createdAt == Fixture.at(1))
        expectRejection(.updateComment(.init(taskID: "next", commentID: "c", body: "Hello")), on: state, .nothingToChange)
        expectRejection(.updateComment(.init(taskID: "next", commentID: "c", body: "")), on: state, .emptyComment)
        expectRejection(.updateComment(.init(taskID: "next", commentID: "x", body: "Hi")), on: state, .commentNotFound)
        var replayed = state
        #expect(
            try apply(.updateComment(.init(taskID: "next", commentID: "c", body: "Hello")), to: &replayed, mode: .replay)
                == .alreadySatisfied
        )
    }
}
