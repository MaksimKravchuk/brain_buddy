import BrainBuddyCore
import Foundation
import Testing

@testable import BrainBuddyAPI

@Suite("Request bodies from Core commands")
struct RequestBodyTests {
    private let inbox: ProjectID = "p-client-1"
    private let errands: TagID = "t-client-1"
    private let calls: TagID = "t-client-2"

    private func projectServerID(_ id: ProjectID) throws -> String {
        guard id == inbox else { throw Unresolved(id: id.rawValue) }
        return "project_0a1b2c3d4e5f"
    }

    private func tagServerID(_ id: TagID) throws -> String {
        switch id {
        case errands: "tag_000000000001"
        case calls: "tag_000000000002"
        default: throw Unresolved(id: id.rawValue)
        }
    }

    struct Unresolved: Error, Equatable { var id: String }

    private func json(_ value: some Encodable) throws -> String {
        String(decoding: try BrainBuddyAPI.makeEncoder().encode(value), as: UTF8.self)
    }

    @Test("TaskChanges → PATCH body: omit, null and value, with server ids")
    func updateFromChanges() throws {
        let changes = TaskChanges(
            title: .set("Pay rent"), details: .clear, projectID: .set(inbox), tagIDs: .set([calls, errands]),
            dueDate: .set(CalendarDay(year: 2026, month: 10, day: 1)!)
        )
        let body = try TaskUpdateBody(
            changes: changes, expectedRevision: 3, projectServerID: projectServerID, tagServerID: tagServerID
        )
        #expect(
            try json(body)
                == #"{"details":null,"due_date":"2026-10-01","expected_revision":3,"project_id":"project_0a1b2c3d4e5f","tag_ids":["tag_000000000002","tag_000000000001"],"title":"Pay rent"}"#
        )
    }

    @Test("Clearing the project and tags never asks the resolver")
    func clearsSkipResolver() throws {
        let body = try TaskUpdateBody(
            changes: TaskChanges(projectID: .clear, tagIDs: .clear, priority: .set(.none), waitingFor: .set("Sam")),
            expectedRevision: 9,
            projectServerID: { _ in throw Unresolved(id: "project") },
            tagServerID: { _ in throw Unresolved(id: "tag") }
        )
        #expect(
            try json(body) == #"{"expected_revision":9,"priority":"none","project_id":null,"tag_ids":null,"waiting_for":"Sam"}"#
        )
    }

    @Test("An unresolved id aborts the conversion")
    func unresolvedThrows() {
        #expect(throws: Unresolved(id: "t-unknown")) {
            _ = try TaskUpdateBody(
                changes: TaskChanges(tagIDs: .set(["t-unknown"])), expectedRevision: 1,
                projectServerID: projectServerID, tagServerID: tagServerID
            )
        }
    }

    @Test("An empty change set sends only expected_revision")
    func emptyUpdate() throws {
        let body = TaskUpdateBody(expectedRevision: 4)
        #expect(!body.hasChanges)
        #expect(try json(body) == #"{"expected_revision":4}"#)
        #expect(TaskUpdateBody(expectedRevision: 4, dueDate: .clear).hasChanges)
    }

    @Test("createTask command → POST body; waiting_for only for Waiting")
    func createFromCommand() throws {
        let waiting = GTDCommand.CreateTask(
            taskID: "task-client-1", title: "Hear back", details: "About the lease", list: .waiting, waitingFor: "Landlord",
            dueDate: CalendarDay(year: 2026, month: 11, day: 3), priority: .medium, projectID: inbox, tagIDs: [errands]
        )
        #expect(
            try json(try TaskCreateBody(waiting, projectServerID: projectServerID, tagServerID: tagServerID))
                == #"{"details":"About the lease","due_date":"2026-11-03","priority":"medium","project_id":"project_0a1b2c3d4e5f","state":"waiting","tag_ids":["tag_000000000001"],"title":"Hear back","waiting_for":"Landlord"}"#
        )

        let next = GTDCommand.CreateTask(taskID: "task-client-2", title: "Call", list: .next, waitingFor: "stale note")
        #expect(
            try json(try TaskCreateBody(next, projectServerID: projectServerID, tagServerID: tagServerID))
                == #"{"priority":"none","state":"next","tag_ids":[],"title":"Call"}"#
        )
    }

    @Test("transitionTask command → canonical body")
    func transitionFromCommand() throws {
        let complete = GTDCommand.TransitionTask(taskID: "t", action: .complete, toList: .next, waitingFor: "x")
        #expect(try json(TaskTransitionBody(complete, expectedRevision: 2)) == #"{"action":"complete","expected_revision":2}"#)

        let cancel = GTDCommand.TransitionTask(taskID: "t", action: .cancel)
        #expect(try json(TaskTransitionBody(cancel, expectedRevision: 2)) == #"{"action":"cancel","expected_revision":2}"#)

        let moveNext = GTDCommand.TransitionTask(taskID: "t", action: .move, toList: .next, waitingFor: "ignored")
        #expect(
            try json(TaskTransitionBody(moveNext, expectedRevision: 2))
                == #"{"action":"move","expected_revision":2,"to_state":"next"}"#
        )

        let reopenWaiting = GTDCommand.TransitionTask(taskID: "t", action: .reopen, toList: .waiting, waitingFor: "Sam")
        #expect(
            try json(TaskTransitionBody(reopenWaiting, expectedRevision: 5))
                == #"{"action":"reopen","expected_revision":5,"to_state":"waiting","waiting_for":"Sam"}"#
        )
    }

    @Test("The same command always encodes to the same bytes (idempotency fingerprint)")
    func deterministic() throws {
        let command = GTDCommand.CreateTask(taskID: "x", title: "Same", list: .inbox, tagIDs: [errands, calls])
        let first = try json(try TaskCreateBody(command, projectServerID: projectServerID, tagServerID: tagServerID))
        let second = try json(try TaskCreateBody(command, projectServerID: projectServerID, tagServerID: tagServerID))
        #expect(first == second)
    }

    @Test("FieldChange.mapValue keeps unchanged and clear")
    func mapValue() {
        #expect(FieldChange<Int>.unchanged.mapValue { String($0) } == .unchanged)
        #expect(FieldChange<Int>.clear.mapValue { String($0) } == .clear)
        #expect(FieldChange<Int>.set(7).mapValue { String($0) } == .set("7"))
    }
}
