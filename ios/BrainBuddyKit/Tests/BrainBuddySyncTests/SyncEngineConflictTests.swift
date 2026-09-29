import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyFakeServer
import Foundation
import Testing

@testable import BrainBuddySync

@Suite("SyncEngine: conflicts and failures")
struct SyncEngineConflictTests {
    /// Two signed-in devices sharing a task created (and synced) on `a`.
    private func twoDevicesWithTask() async throws -> (SyncHarness, Device, Device, TaskID) {
        let harness = SyncHarness()
        let a = await harness.device()
        let b = await harness.device()
        try await a.signIn()
        try await a.apply(.createTask(.init(taskID: "x", title: "Renew passport", list: .next, priority: .low)))
        await a.sync()
        try await b.signIn()
        let onB = try #require(try await b.current().task(titled: "Renew passport"))
        return (harness, a, b, onB.id)
    }

    @Test("A stale revision re-reads the task, replays, and resends under a new key: local intent wins on its fields")
    func resolvesStaleRevision() async throws {
        let (harness, a, b, taskOnB) = try await twoDevicesWithTask()
        try await b.apply(.updateTask(.init(taskID: taskOnB, changes: TaskChanges(title: .set("Renew passport today")))))
        try await a.apply(.updateTask(.init(taskID: "x", changes: TaskChanges(details: .set("Photos first"), priority: .set(.high)))))
        harness.clock.advance(by: 60)
        await a.sync()
        b.transport.clearLog()

        #expect(await b.sync() == .idle(lastSyncedAt: harness.clock.now()))
        let patches = b.mutations.filter { $0.method == .patch }
        #expect(patches.count == 2, "the first PATCH is stale, the second carries the new revision")
        #expect(patches[0].idempotencyKey != patches[1].idempotencyKey)
        #expect(patches[1].bodyText.contains(#""expected_revision":2"#))
        #expect(patches[1].bodyText.contains(#""title":"Renew passport today""#))
        #expect(!patches[1].bodyText.contains("priority"), "only the fields b changed are sent")

        let server = try #require(harness.snapshot.tasks.values.first)
        #expect(server.title == "Renew passport today")
        #expect(server.details == "Photos first")
        #expect(server.priority == .high)
        #expect(try await b.document().issues.isEmpty)
        #expect(try CanonicalState(await b.current(), children: false) == CanonicalState(harness.snapshot, children: false))
    }

    @Test("A change whose goal already holds after the re-read is dropped, not sent again")
    func dropsSatisfiedChange() async throws {
        let (harness, a, b, taskOnB) = try await twoDevicesWithTask()
        try await a.apply(.transitionTask(.init(taskID: "x", action: .complete)))
        await a.sync()
        try await b.apply(.transitionTask(.init(taskID: taskOnB, action: .complete)))
        b.transport.clearLog()

        #expect(await b.sync() == .idle(lastSyncedAt: harness.clock.now()))
        #expect(b.mutations.count == 1, "one stale attempt, no resend")
        let document = try await b.document()
        #expect(document.outbox.isEmpty)
        #expect(document.issues.isEmpty)
        let server = try #require(harness.snapshot.tasks.values.first)
        #expect(server.state == .completed)
        #expect(server.revision == 2, "only a's completion changed the task")
        #expect(document.base.tasks[taskOnB]?.state == .completed)
        #expect(document.base.tasks[taskOnB]?.lastOpenList == .next)
    }

    @Test("A change the re-read makes impossible becomes a sync issue")
    func setsAsideImpossibleChange() async throws {
        let (harness, a, b, taskOnB) = try await twoDevicesWithTask()
        try await a.apply(.transitionTask(.init(taskID: "x", action: .complete)))
        await a.sync()
        try await b.apply(.transitionTask(.init(taskID: taskOnB, action: .move, toList: .someday)))

        #expect(await b.sync() == .idle(lastSyncedAt: harness.clock.now()))
        let document = try await b.document()
        #expect(document.outbox.isEmpty)
        #expect(document.issues.map(\.message) == [GTDValidationError.taskNotOpen.message])
        #expect(harness.snapshot.tasks.values.first?.state == .completed)
    }

    @Test("A project or tag created elsewhere under the same name is adopted, and the outbox follows it")
    func adoptsDuplicateName() async throws {
        let harness = SyncHarness()
        let a = await harness.device()
        let b = await harness.device()
        try await a.signIn()
        try await b.signIn()
        try await a.apply(.createProject(.init(projectID: "work-a", name: "Work")))
        try await a.apply(.createTag(.init(tagID: "home-a", name: "home")))
        await a.sync()
        try await b.apply(.createProject(.init(projectID: "work-b", name: " WORK ")))
        try await b.apply(.createTag(.init(tagID: "home-b", name: "@Home")))
        try await b.apply(.createTask(.init(taskID: "y", title: "Plan the week", list: .next, projectID: "work-b", tagIDs: ["home-b"])))
        b.transport.clearLog()

        #expect(await b.sync() == .idle(lastSyncedAt: harness.clock.now()))
        #expect(b.mutations.map(\.route) == ["POST /projects", "POST /tags", "POST /tasks"])
        let server = harness.snapshot
        #expect(server.projects.count == 1)
        #expect(server.tags.count == 1)
        let work = try #require(server.project(named: "Work"))
        let home = try #require(server.tag(named: "home"))
        #expect(server.task(titled: "Plan the week")?.projectID == work.id)
        #expect(server.task(titled: "Plan the week")?.tagIDs == [home.id])
        let document = try await b.document()
        #expect(document.issues.isEmpty)
        #expect(document.base.projects["work-b"] == nil, "the local id was replaced by the adopted record")
        #expect(document.base.tasks["y"]?.projectID == document.base.projects.values.first?.id)
    }

    @Test("A rejected change becomes an issue with the server's words, and the changes that depend on it follow")
    func setsAsideRejectedChangeAndDependents() async throws {
        let harness = SyncHarness()
        let a = await harness.device()
        let b = await harness.device()
        try await a.signIn()
        try await a.apply(.createTag(.init(tagID: "t", name: "calls")))
        await a.sync()
        try await b.signIn()
        let tagOnB = try #require(try await b.current().tag(named: "calls")).id
        try await a.apply(.deleteTag("t"))
        await a.sync()
        try await b.apply(.createTask(.init(taskID: "z", title: "Call Sam", list: .next, tagIDs: [tagOnB])))
        try await b.apply(.createSubtask(.init(taskID: "z", subtaskID: "zs", title: "Find the number")))
        try await b.apply(.createComment(.init(taskID: "z", commentID: "zc", body: "Before Friday.")))
        try await b.apply(.createTask(.init(taskID: "w", title: "Water plants", list: .next)))

        #expect(await b.sync() == .idle(lastSyncedAt: harness.clock.now()))
        let document = try await b.document()
        #expect(document.outbox.isEmpty)
        #expect(document.issues.count == 3)
        let first = try #require(document.issues.first)
        #expect(first.message == "Task contexts must be active; task tags must be active.")
        #expect(first.referenceID != nil)
        #expect(document.issues.dropFirst().map(\.message) == [
            GTDValidationError.taskNotFound.message, GTDValidationError.taskNotFound.message,
        ])
        let server = harness.snapshot
        #expect(server.task(titled: "Call Sam") == nil)
        #expect(server.task(titled: "Water plants") != nil, "independent changes still go out")
        #expect(document.base.tags[tagOnB]?.state == .deleted)
    }

    @Test("A 401 stops sync and keeps every change until the user signs in again")
    func keepsEverythingOnUnauthorized() async throws {
        let harness = SyncHarness()
        let device = await harness.device()
        try await device.signIn()
        try await device.apply(.createProject(.init(projectID: "p", name: "Garden")))
        try await device.apply(.createTask(.init(taskID: "x", title: "Plant tulips", list: .next, projectID: "p")))
        let before = try await device.document().outbox
        harness.server.revokeSessions(email: SyncHarness.email)

        #expect(await device.sync() == .needsSignIn)
        let after = try await device.document()
        #expect(after.outbox.map(\.id) == before.map(\.id))
        #expect(after.outbox.map(\.idempotencyKey) == before.map(\.idempotencyKey))
        #expect(after.issues.isEmpty)
        #expect(try device.tokens.token(for: FakeBrainBuddyServer.baseURL) == nil, "the dead session is forgotten")
        #expect(device.scheduler.pendingDelays.isEmpty, "no retries until the user signs in")

        device.transport.clearLog()
        await device.engine.request(.foreground)
        #expect(await device.sync() == .needsSignIn)
        #expect(device.transport.requests.isEmpty)

        try await device.signIn()
        #expect(await device.status == .idle(lastSyncedAt: harness.clock.now()))
        #expect(try await device.document().outbox.isEmpty)
        #expect(harness.snapshot.task(titled: "Plant tulips")?.projectID == harness.snapshot.project(named: "Garden")?.id)
    }

    @Test("Repeated server errors turn the status to failing, with the server's words")
    func reportsRepeatedServerErrors() async throws {
        let harness = SyncHarness()
        let device = await harness.device()
        try await device.signIn()
        try await device.apply(.createTask(.init(taskID: "x", title: "Call the bank", list: .inbox)))
        device.transport.inject(.status(503), times: 2)

        #expect(await device.sync() == .idle(lastSyncedAt: harness.clock.now()))
        let status = await device.sync()
        guard case .failing(let message, let referenceID, _) = status else {
            Issue.record("Expected .failing, got \(status)")
            return
        }
        #expect(message == "Storage is temporarily unavailable; please retry.")
        #expect(referenceID != nil)
        #expect(try await device.document().sync.lastFailure == message)
        #expect(await device.sync() == .idle(lastSyncedAt: harness.clock.now()))
        #expect(try await device.document().sync.lastFailure == nil)
    }
}
