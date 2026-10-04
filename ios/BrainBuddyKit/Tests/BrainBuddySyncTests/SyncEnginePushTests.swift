import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyFakeServer
import Foundation
import Testing

@testable import BrainBuddySync

@Suite("SyncEngine: push")
struct SyncEnginePushTests {
    /// Applies `command`, syncs, and checks exactly one mutation went out.
    private func push(
        _ command: GTDCommand, on device: Device, expecting route: String,
        sourceLocation: SourceLocation = #_sourceLocation
    ) async throws {
        device.transport.clearLog()
        try await device.apply(command)
        let status = await device.sync()
        #expect(status == .idle(lastSyncedAt: device.clock.now()), sourceLocation: sourceLocation)
        #expect(device.mutations.map(\.route) == [route], sourceLocation: sourceLocation)
        let document = try await device.document()
        #expect(document.outbox.isEmpty, sourceLocation: sourceLocation)
        #expect(document.issues.isEmpty, "\(document.issues)", sourceLocation: sourceLocation)
    }

    @Test("Every command goes out as its one request and lands in the base")
    func pushesEveryCommand() async throws {
        let harness = SyncHarness()
        let device = await harness.device()
        try await device.signIn()

        try await push(
            .createProject(.init(projectID: "p", name: "  Home  ", color: "#0EA5E9")), on: device,
            expecting: "POST /projects"
        )
        let projectServerID = try #require(try await device.document().base.projects["p"]?.serverID)
        #expect(try await device.document().base.projects["p"]?.name == "Home", "the server's name wins")
        try await push(
            .updateProject(.init(projectID: "p", name: "House", color: .clear)), on: device,
            expecting: "PATCH /projects/\(projectServerID)"
        )
        try await push(.createTag(.init(tagID: "t", name: "@errands")), on: device, expecting: "POST /tags")
        let tagServerID = try #require(try await device.document().base.tags["t"]?.serverID)
        #expect(try await device.document().base.tags["t"]?.name == "errands")
        try await push(.renameTag(.init(tagID: "t", name: "Errands")), on: device, expecting: "PATCH /tags/\(tagServerID)")
        try await push(
            .createTask(
                .init(
                    taskID: "x", title: "  Renew passport ", details: "", list: .inbox,
                    dueDate: CalendarDay(year: 2026, month: 10, day: 15), priority: .high, projectID: "p", tagIDs: ["t"]
                )
            ),
            on: device, expecting: "POST /tasks"
        )
        let taskServerID = try #require(try await device.document().base.tasks["x"]?.serverID)
        try await push(
            .updateTask(.init(taskID: "x", changes: TaskChanges(details: .set("Photos first"), priority: .set(.medium)))),
            on: device, expecting: "PATCH /tasks/\(taskServerID)"
        )
        try await push(
            .transitionTask(.init(taskID: "x", action: .move, toList: .waiting, waitingFor: " Photo studio ")),
            on: device, expecting: "POST /tasks/\(taskServerID)/transitions"
        )
        try await push(
            .createSubtask(.init(taskID: "x", subtaskID: "s", title: " Book photos ")), on: device,
            expecting: "POST /tasks/\(taskServerID)/subtasks"
        )
        let subtaskServerID = try #require(try await device.document().base.tasks["x"]?.subtasks.first?.serverID)
        try await push(
            .updateSubtask(.init(taskID: "x", subtaskID: "s", title: "Book photo studio")), on: device,
            expecting: "PATCH /tasks/\(taskServerID)/subtasks/\(subtaskServerID)"
        )
        try await push(
            .transitionSubtask(.init(taskID: "x", subtaskID: "s", action: .complete)), on: device,
            expecting: "POST /tasks/\(taskServerID)/subtasks/\(subtaskServerID)/transitions"
        )
        try await push(
            .createComment(.init(taskID: "x", commentID: "c", body: "Asked twice.")), on: device,
            expecting: "POST /tasks/\(taskServerID)/comments"
        )
        let commentServerID = try #require(try await device.document().base.tasks["x"]?.comments.first?.serverID)
        try await push(
            .updateComment(.init(taskID: "x", commentID: "c", body: "Asked three times.")), on: device,
            expecting: "PATCH /tasks/\(taskServerID)/comments/\(commentServerID)"
        )
        try await push(
            .transitionTask(.init(taskID: "x", action: .complete)), on: device,
            expecting: "POST /tasks/\(taskServerID)/transitions"
        )
        try await push(.deleteTag("t"), on: device, expecting: "DELETE /tags/\(tagServerID)")
        try await push(.archiveProject("p"), on: device, expecting: "POST /projects/\(projectServerID)/archive")

        let server = harness.snapshot
        let task = try #require(server.tasks[taskServerID])
        #expect(task.title == "Renew passport")
        #expect(task.details == "Photos first")
        #expect(task.state == .completed)
        #expect(task.priority == .medium)
        #expect(task.projectID == nil)
        #expect(task.tagIDs.isEmpty)
        #expect(task.subtasks.map(\.title) == ["Book photo studio"])
        #expect(task.subtasks.map(\.state) == [.completed])
        #expect(task.comments.map(\.body) == ["Asked three times."])
        #expect(server.projects[projectServerID]?.name == "House")
        #expect(server.projects[projectServerID]?.state == .archived)
        #expect(server.tags[tagServerID]?.name == "Errands")
        #expect(server.tags[tagServerID]?.state == .deleted)

        // The device holds the server's view under its own ids; the completed
        // task remembers the list it was completed from.
        let base = try await device.document().base
        #expect(base.tasks["x"]?.serverRevision == task.revision)
        #expect(base.tasks["x"]?.lastOpenList == .waiting)
        #expect(base.tasks["x"]?.subtasks.first?.id == "s")
        #expect(base.tasks["x"]?.comments.first?.id == "c")
        #expect(base.tasks["x"]?.comments.first?.authorID == harness.accountID)
        #expect(try CanonicalState(await device.current(), children: true) == CanonicalState(server, children: true))
    }

    @Test("A project and tag go out before the task that uses them, which carries their server ids")
    func sendsDependenciesFirst() async throws {
        let harness = SyncHarness()
        let device = await harness.device()
        try await device.signIn()
        device.transport.clearLog()
        try await device.apply(.createProject(.init(projectID: "p", name: "Garden")))
        try await device.apply(.createTag(.init(tagID: "t", name: "outside")))
        try await device.apply(.createTask(.init(taskID: "x", title: "Plant tulips", list: .next, projectID: "p", tagIDs: ["t"])))
        try await device.apply(.createSubtask(.init(taskID: "x", subtaskID: "s", title: "Buy bulbs")))

        #expect(await device.sync() == .idle(lastSyncedAt: harness.clock.now()))
        #expect(device.mutations.map(\.route).map { $0.split(separator: "/").prefix(2).joined(separator: "/") } == [
            "POST /projects", "POST /tags", "POST /tasks", "POST /tasks",
        ])
        let server = harness.snapshot
        let project = try #require(server.project(named: "Garden"))
        let tag = try #require(server.tag(named: "outside"))
        let task = try #require(server.task(titled: "Plant tulips"))
        #expect(task.projectID == project.id)
        #expect(task.tagIDs == [tag.id])
        #expect(task.subtasks.map(\.title) == ["Buy bulbs"])
        // Every request carried its own key.
        #expect(Set(device.mutations.compactMap(\.idempotencyKey)).count == 4)
    }

    @Test("A lost response is retried with the same key and applies once")
    func retriesLostResponseWithSameKey() async throws {
        let harness = SyncHarness()
        let device = await harness.device()
        try await device.signIn()
        try await device.apply(.createTask(.init(taskID: "x", title: "Call the bank", list: .inbox)))
        device.transport.clearLog()
        device.transport.inject(.dropResponse, matching: FakeServerTransport.isMutation)

        #expect(await device.sync() == .offline(lastSyncedAt: harness.clock.now()))
        let pending = try #require(try await device.document().outbox.first)
        #expect(pending.attempts == 1)
        #expect(pending.lastError != nil)
        #expect(harness.snapshot.tasks.count == 1, "the server applied the first attempt")

        harness.clock.advance(by: 30)
        #expect(await device.sync() == .idle(lastSyncedAt: harness.clock.now()))
        let keys = device.mutations.compactMap(\.idempotencyKey)
        #expect(keys.count == 2)
        #expect(keys[0] == pending.idempotencyKey.uuidString.lowercased())
        #expect(keys[1] == keys[0])
        #expect(harness.snapshot.tasks.count == 1, "the retry replayed instead of creating a second task")
        let document = try await device.document()
        #expect(document.outbox.isEmpty)
        #expect(document.base.tasks["x"]?.serverID == harness.snapshot.tasks.keys.first)
    }

    @Test("A request that never arrived is sent again and applies once")
    func resendsAfterOfflineFailure() async throws {
        let harness = SyncHarness()
        let device = await harness.device()
        try await device.signIn()
        try await device.apply(.createTask(.init(taskID: "x", title: "Call the bank", list: .inbox)))
        device.transport.inject(.timeout, matching: FakeServerTransport.isMutation)
        device.transport.inject(.status(503), matching: FakeServerTransport.isMutation)

        #expect(await device.sync() == .offline(lastSyncedAt: harness.clock.now()))
        #expect(harness.snapshot.tasks.isEmpty)
        #expect(await device.sync() == .idle(lastSyncedAt: harness.clock.now()), "a first 503 is not yet a failure")
        #expect(harness.snapshot.tasks.isEmpty)
        #expect(await device.sync() == .idle(lastSyncedAt: harness.clock.now()))
        #expect(harness.snapshot.tasks.count == 1)
        #expect(Set(device.mutations.compactMap(\.idempotencyKey)).count == 1)
    }

    @Test("Retries back off 2 s, 4 s, 8 s and stop after a success")
    func backsOffExponentially() async throws {
        let harness = SyncHarness()
        let device = await harness.device()
        try await device.signIn()
        try await device.apply(.createTask(.init(taskID: "x", title: "Call the bank", list: .inbox)))
        device.transport.inject(.offline, times: 3)

        #expect(await device.sync() == .offline(lastSyncedAt: harness.clock.now()))
        #expect(device.scheduler.pendingDelays == [.seconds(2)])
        #expect(await device.scheduler.runNext())
        await device.engine.waitUntilIdle()
        #expect(device.scheduler.pendingDelays == [.seconds(4)])
        #expect(await device.scheduler.runNext())
        await device.engine.waitUntilIdle()
        #expect(device.scheduler.pendingDelays == [.seconds(8)])
        #expect(await device.scheduler.runNext())
        await device.engine.waitUntilIdle()
        #expect(device.scheduler.pendingDelays.isEmpty)
        #expect(await device.status == .idle(lastSyncedAt: harness.clock.now()))
        #expect(harness.snapshot.tasks.count == 1)
    }

    @Test("The backoff delay is capped at five minutes and spread by jitter")
    func capsBackoff() {
        var configuration = SyncConfiguration(jitter: { 0.5 })
        #expect(configuration.retryDelay(afterFailures: 1) == 2)
        #expect(configuration.retryDelay(afterFailures: 8) == 256)
        #expect(configuration.retryDelay(afterFailures: 9) == 300)
        #expect(configuration.retryDelay(afterFailures: 40) == 300)
        configuration.jitter = { 0 }
        #expect(abs(configuration.retryDelay(afterFailures: 1) - 1.6) < 1e-9)
        #expect(configuration.retryDelay(afterFailures: 20) == 240)
        configuration.jitter = { 0.999_999 }
        #expect(abs(configuration.retryDelay(afterFailures: 2) - 4.8) < 0.001)
        #expect(configuration.retryDelay(afterFailures: 20) == 300)
    }
}
