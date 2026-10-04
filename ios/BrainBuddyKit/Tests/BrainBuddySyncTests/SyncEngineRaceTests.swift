import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyFakeServer
import BrainBuddyPersistence
import Foundation
import Testing

@testable import BrainBuddySync

/// Requests caught in flight: what the device does while an answer is late.
@Suite("SyncEngine: requests in flight")
struct SyncEngineRaceTests {
    /// A task synced from device a, and device b signed in over a transport
    /// that holds the first request `matches` accepts.
    private func taskOnHeldDevice(
        title: String, matches: @escaping @Sendable (_ serverTaskID: String, HTTPRequest) -> Bool
    ) async throws -> (SyncHarness, Device, HeldDevice, serverTaskID: String, taskOnB: TaskID) {
        let harness = SyncHarness()
        let a = await harness.device()
        try await a.signIn()
        try await a.apply(.createTask(.init(taskID: "x", title: title, list: .next)))
        await a.sync()
        let serverTaskID = try #require(harness.snapshot.tasks.keys.first)
        let b = HeldDevice(harness: harness) { matches(serverTaskID, $0) }
        try await b.signIn()
        let taskOnB = try #require(try await b.current().task(titled: title)).id
        return (harness, a, b, serverTaskID, taskOnB)
    }

    @Test("A task detail read runs in the sync slot: a push waits for it, so its stale answer can't drop an acknowledged subtask")
    func detailReadNeverOverlapsAPush() async throws {
        let (harness, _, b, serverTaskID, taskOnB) = try await taskOnHeldDevice(title: "Groceries") { id, request in
            request.method == .get && request.url.path.hasSuffix("/tasks/\(id)")
        }

        // The task detail opens: the read is answered (no subtasks yet) and held.
        let refresh = Task { await b.engine.refreshTask(taskOnB) }
        await b.transport.gate.waitForArrival()

        // Meanwhile a subtask is added and ticked off; the tick meets a dead network.
        try await b.apply(.createSubtask(.init(taskID: taskOnB, subtaskID: "s1", title: "Milk")))
        try await b.apply(.transitionSubtask(.init(taskID: taskOnB, subtaskID: "s1", action: .complete)))
        b.inner.inject(.offline) { $0.url.path.hasSuffix("/transitions") && $0.url.path.contains("/subtasks/") }
        let sync = Task { await b.engine.syncNow() }
        while await b.engine.joinedCycles == 0 { await Task.yield() }
        #expect(b.mutations.isEmpty, "the push waits for the read in flight")

        await b.transport.gate.open()
        await refresh.value
        #expect(await sync.value == .offline(lastSyncedAt: harness.clock.now()))
        let document = try await b.document()
        #expect(document.base.tasks[taskOnB]?.subtasks.map(\.id) == ["s1"], "the acknowledged subtask stays")
        #expect(document.outbox.count == 1, "the tick is still queued")
        #expect(document.issues.isEmpty)
        #expect(try await b.current().tasks[taskOnB]?.subtasks.map(\.state) == [.completed])

        b.inner.clearFaults()
        #expect(await b.engine.syncNow() == .idle(lastSyncedAt: harness.clock.now()))
        #expect(harness.snapshot.tasks[serverTaskID]?.subtasks.map(\.title) == ["Milk"])
        #expect(harness.snapshot.tasks[serverTaskID]?.subtasks.map(\.state) == [.completed])
        #expect(try await b.document().issues.isEmpty)
    }

    @Test("A task detail asked for while a cycle runs is read before that cycle's slot is free")
    func detailReadJoinsARunningCycle() async throws {
        let (harness, a, b, serverTaskID, taskOnB) = try await taskOnHeldDevice(title: "Report") { _, request in
            request.method == .get && request.url.path.hasSuffix("/tasks")
        }
        try await a.apply(.createSubtask(.init(taskID: "x", subtaskID: "a1", title: "Outline")))
        await a.sync()
        #expect(harness.snapshot.tasks[serverTaskID]?.subtasks.count == 1)

        // A pull is in flight when the detail opens.
        b.inner.clearLog()
        let sync = Task { await b.engine.syncNow() }
        await b.transport.gate.waitForArrival()
        let refresh = Task { await b.engine.refreshTask(taskOnB) }
        while await b.engine.requestedRefreshes.isEmpty { await Task.yield() }
        let detailReads = b.inner.requests.filter { $0.url.path.hasSuffix("/tasks/\(serverTaskID)") }
        #expect(detailReads.isEmpty, "not beside the running cycle")

        await b.transport.gate.open()
        await refresh.value
        _ = await sync.value
        #expect(try await b.current().tasks[taskOnB]?.subtasks.map(\.title) == ["Outline"])
        #expect(await b.engine.requestedRefreshes.isEmpty)
        let routes = b.inner.requests.map(\.url.path)
        let read = try #require(routes.firstIndex(of: "/api/tasks/\(serverTaskID)"))
        #expect(routes.prefix(read).contains("/api/tasks"), "read after the cycle's pull, not beside it")
    }

    @Test("A key renewed while its request is in flight keeps the operation unfoldable, so a later edit is sent too")
    func renewedKeyKeepsOperationUnfoldable() async throws {
        let (harness, _, b, serverTaskID, taskOnB) = try await taskOnHeldDevice(title: "Draft") { id, request in
            request.method == .patch && request.url.path.hasSuffix("/tasks/\(id)")
        }

        // The rename lands on the server; its answer is held.
        try await b.apply(.updateTask(.init(taskID: taskOnB, changes: TaskChanges(title: .set("Draft v2")))))
        let cycle = Task { await b.engine.syncNow() }
        await b.transport.gate.waitForArrival()

        // The key is renewed meanwhile (as a newer base does to a sent operation).
        let renewed = try await b.store.update { doc in doc.outbox[0].rotateKey() }
        #expect(renewed.outbox.first?.attempts == 0)
        #expect(renewed.outbox.first?.everSent == true)
        #expect(renewed.outbox.first?.hasBeenSent == true, "it may still land")

        // A later edit is queued on its own, not folded into the one in flight.
        try await b.apply(.updateTask(.init(taskID: taskOnB, changes: TaskChanges(details: .set("Call the editor first")))))
        #expect(try await b.document().outbox.count == 2)

        await b.transport.gate.open()
        _ = await cycle.value
        _ = await b.engine.syncNow()
        let server = try #require(harness.snapshot.tasks[serverTaskID])
        #expect(server.title == "Draft v2")
        #expect(server.details == "Call the editor first")
        let document = try await b.document()
        #expect(document.outbox.isEmpty)
        #expect(document.issues.isEmpty)
        #expect(try await b.current().tasks[taskOnB]?.details == "Call the editor first")
    }

    @Test("An acknowledgement keeps what was folded into the operation after it was sent")
    func acknowledgementKeepsWhatWasNotSent() async throws {
        let (harness, _, b, serverTaskID, taskOnB) = try await taskOnHeldDevice(title: "Draft") { id, request in
            request.method == .patch && request.url.path.hasSuffix("/tasks/\(id)")
        }
        try await b.apply(.updateTask(.init(taskID: taskOnB, changes: TaskChanges(title: .set("Draft v2")))))
        let cycle = Task { await b.engine.syncNow() }
        await b.transport.gate.waitForArrival()

        // An older app version folded an edit into the operation in flight.
        let folded = GTDCommand.updateTask(
            .init(taskID: taskOnB, changes: TaskChanges(title: .set("Draft v2"), priority: .set(.high)))
        )
        _ = try await b.store.update { doc in doc.outbox[0].command = folded }

        await b.transport.gate.open()
        _ = await cycle.value
        _ = await b.engine.syncNow()
        let server = try #require(harness.snapshot.tasks[serverTaskID])
        #expect(server.title == "Draft v2")
        #expect(server.priority == .high, "the folded field was sent after the acknowledgement")
        let patches = b.mutations.filter { $0.method == .patch }
        #expect(patches.count == 2)
        #expect(!(patches.last?.bodyText.contains("title") ?? true), "only what was not sent goes out again")
        #expect(try await b.document().outbox.isEmpty)
    }
}
