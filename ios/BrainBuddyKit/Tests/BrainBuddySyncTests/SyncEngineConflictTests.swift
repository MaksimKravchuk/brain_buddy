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
        let device = await harness.device()
        try await device.signIn()
        let callSam = GTDCommand.createTask(.init(taskID: "z", title: "Call Sam", list: .next))
        try await device.apply(callSam)
        try await device.apply(.createSubtask(.init(taskID: "z", subtaskID: "zs", title: "Find the number")))
        try await device.apply(.createComment(.init(taskID: "z", commentID: "zc", body: "Before Friday.")))
        try await device.apply(.createTask(.init(taskID: "w", title: "Water plants", list: .next)))
        // The server refuses the body for a reason the device can't see; nothing in it went stale.
        device.transport.inject(.status(422), times: 1_000) { $0.bodyText.contains("Call Sam") }
        device.transport.clearLog()

        #expect(await device.sync() == .idle(lastSyncedAt: harness.clock.now()))
        let document = try await device.document()
        #expect(document.outbox.isEmpty)
        #expect(document.issues.count == 3)
        let first = try #require(document.issues.first)
        #expect(first.message == "Request validation failed.")
        #expect(first.referenceID != nil)
        #expect(first.command == callSam)
        #expect(document.issues.dropFirst().map(\.message) == [
            GTDValidationError.taskNotFound.message, GTDValidationError.taskNotFound.message,
        ])
        #expect(device.mutations.filter { $0.bodyText.contains("Call Sam") }.count == 1, "nothing to drop, so no resend")
        let server = harness.snapshot
        #expect(server.task(titled: "Call Sam") == nil)
        #expect(server.task(titled: "Water plants") != nil, "independent changes still go out")
    }

    // MARK: References that went stale elsewhere

    /// Device b knows the tags "errand" and "shop" (made on a), then a
    /// deletes "errand" while b does not know yet.
    private func errandDeletedElsewhere() async throws -> (SyncHarness, Device, Device, errand: TagID, shop: TagID) {
        let harness = SyncHarness()
        let a = await harness.device()
        let b = await harness.device()
        try await a.signIn()
        try await a.apply(.createTag(.init(tagID: "errand", name: "errand")))
        try await a.apply(.createTag(.init(tagID: "shop", name: "shop")))
        await a.sync()
        try await b.signIn()
        let errand = try #require(try await b.current().tag(named: "errand")).id
        let shop = try #require(try await b.current().tag(named: "shop")).id
        try await a.apply(.deleteTag("errand"))
        await a.sync()
        return (harness, a, b, errand, shop)
    }

    @Test("A capture tagged with a tag deleted elsewhere is resent without it: the task, its subtasks and comments are kept")
    func resendsCaptureWithoutDeletedTag() async throws {
        let (harness, _, b, errand, shop) = try await errandDeletedElsewhere()
        try await b.apply(.createTask(.init(taskID: "z", title: "Buy milk", list: .next, tagIDs: [errand, shop])))
        try await b.apply(.createSubtask(.init(taskID: "z", subtaskID: "zs", title: "Oat milk")))
        try await b.apply(.createComment(.init(taskID: "z", commentID: "zc", body: "Two litres.")))
        b.transport.clearLog()

        #expect(await b.sync() == .idle(lastSyncedAt: harness.clock.now()))
        let creates = b.transport.exchanges.filter { $0.request.route == "POST /tasks" }
        #expect(creates.map(\.statusCode) == [400, 201], "refused once for the deleted tag, then accepted without it")
        try #require(creates.count == 2)
        #expect(creates.first?.errorMessage == "Task contexts must be active; task tags must be active.")
        #expect(creates[0].request.idempotencyKey != creates[1].request.idempotencyKey, "a new body, a new key")
        let errandOnServer = try #require(harness.snapshot.tag(named: "errand"))
        let shopOnServer = try #require(harness.snapshot.tag(named: "shop"))
        #expect(creates[0].request.bodyText.contains(errandOnServer.id))
        #expect(!creates[1].request.bodyText.contains(errandOnServer.id))

        let server = try #require(harness.snapshot.task(titled: "Buy milk"))
        #expect(server.tagIDs == [shopOnServer.id])
        #expect(server.subtasks.map(\.title) == ["Oat milk"])
        #expect(server.comments.map(\.body) == ["Two litres."])
        let document = try await b.document()
        #expect(document.issues.isEmpty)
        #expect(document.outbox.isEmpty)
        #expect(document.base.tasks["z"]?.tagIDs == [shop])
        #expect(document.base.tasks["z"]?.serverID == server.id)
        #expect(document.base.tags[errand]?.state == .deleted)
        #expect(try CanonicalState(await b.current(), children: true) == CanonicalState(harness.snapshot, children: true))
    }

    @Test("021-FR-011 A capture in a project archived elsewhere is resent without the project, keeps everything else and says so")
    func resendsCaptureWithoutArchivedProject() async throws {
        let harness = SyncHarness()
        let a = await harness.device()
        let b = await harness.device()
        try await a.signIn()
        try await a.apply(.createProject(.init(projectID: "garden", name: "Garden")))
        await a.sync()
        try await b.signIn()
        let garden = try #require(try await b.current().project(named: "Garden")).id
        try await a.apply(.archiveProject("garden"))
        await a.sync()
        try await b.apply(
            .createTask(.init(taskID: "z", title: "Plant tulips", list: .someday, priority: .high, projectID: garden))
        )
        try await b.apply(.createSubtask(.init(taskID: "z", subtaskID: "zs", title: "Buy bulbs")))
        b.transport.clearLog()

        #expect(await b.sync() == .idle(lastSyncedAt: harness.clock.now()))
        let creates = b.transport.exchanges.filter { $0.request.route == "POST /tasks" }
        #expect(creates.map(\.statusCode) == [400, 201])
        #expect(creates.first?.errorMessage == "Task project must be active.")
        let server = try #require(harness.snapshot.task(titled: "Plant tulips"))
        #expect(server.projectID == nil)
        #expect(server.state == .someday)
        #expect(server.priority == .high)
        #expect(server.subtasks.map(\.title) == ["Buy bulbs"])
        let document = try await b.document()
        #expect(
            document.issues.map(\.message)
                == ["Project “Garden” was archived on another device, so the task was added without a project."])
        #expect(document.issues.first?.referenceID?.isEmpty == false)
        #expect(document.outbox.isEmpty)
        let onB = try #require(try await b.current().tasks["z"])
        #expect(onB.projectID == nil)
        #expect(onB.serverID == server.id)
        #expect(document.base.projects[garden]?.state == .archived)
    }

    @Test("An edit that sets a tag deleted elsewhere keeps its other changes, after the re-read and the rejection")
    func resendsEditWithoutDeletedTag() async throws {
        let harness = SyncHarness()
        let a = await harness.device()
        let b = await harness.device()
        try await a.signIn()
        try await a.apply(.createTag(.init(tagID: "errand", name: "errand")))
        try await a.apply(.createTag(.init(tagID: "shop", name: "shop")))
        try await a.apply(.createTask(.init(taskID: "x", title: "Buy milk", list: .next)))
        await a.sync()
        try await b.signIn()
        let current = try await b.current()
        let milk = try #require(current.task(titled: "Buy milk")).id
        let errand = try #require(current.tag(named: "errand")).id
        let shop = try #require(current.tag(named: "shop")).id
        try await b.apply(
            .updateTask(.init(taskID: milk, changes: TaskChanges(title: .set("Buy oat milk"), tagIDs: .set([errand, shop]))))
        )
        // Meanwhile on a: the tag goes, and the task changes, so b's edit is stale first.
        try await a.apply(.deleteTag("errand"))
        try await a.apply(.updateTask(.init(taskID: "x", changes: TaskChanges(priority: .set(.high)))))
        await a.sync()
        b.transport.clearLog()

        #expect(await b.sync() == .idle(lastSyncedAt: harness.clock.now()))
        let edits = b.transport.exchanges.filter { $0.request.method == .patch }
        #expect(edits.map(\.statusCode) == [409, 400, 200])
        #expect(Set(edits.compactMap(\.request.idempotencyKey)).count == 3)
        let server = try #require(harness.snapshot.task(titled: "Buy oat milk"))
        #expect(server.tagIDs == [try #require(harness.snapshot.tag(named: "shop")).id])
        #expect(server.priority == .high, "a's edit is kept too")
        let document = try await b.document()
        #expect(document.issues.isEmpty)
        #expect(document.outbox.isEmpty)
        #expect(document.base.tasks[milk]?.tagIDs == [shop])
        #expect(try CanonicalState(await b.current(), children: false) == CanonicalState(harness.snapshot, children: false))
    }

    @Test("A body still refused once its stale references are gone is set aside: each body is resent at most once")
    func setsAsideWhenTheResendIsRefusedToo() async throws {
        let (harness, _, b, errand, _) = try await errandDeletedElsewhere()
        try await b.apply(.createTask(.init(taskID: "z", title: "Buy milk", list: .next, tagIDs: [errand])))
        try await b.apply(.createSubtask(.init(taskID: "z", subtaskID: "zs", title: "Oat milk")))
        let errandOnServer = try #require(harness.snapshot.tag(named: "errand")).id
        b.transport.inject(.status(422), times: 1_000) {
            $0.bodyText.contains("Buy milk") && !$0.bodyText.contains(errandOnServer)
        }
        b.transport.clearLog()

        #expect(await b.sync() == .idle(lastSyncedAt: harness.clock.now()))
        let creates = b.transport.exchanges.filter { $0.request.route == "POST /tasks" }
        #expect(creates.map(\.statusCode) == [400, 422])
        let document = try await b.document()
        #expect(document.outbox.isEmpty)
        #expect(document.issues.map(\.message) == ["Request validation failed.", GTDValidationError.taskNotFound.message])
        #expect(
            document.issues.first?.command == .createTask(.init(taskID: "z", title: "Buy milk", list: .next)),
            "the issue holds the change as last sent"
        )
        #expect(harness.snapshot.task(titled: "Buy milk") == nil)
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
        // Only the push fails: a cycle blocked by the server still pulls.
        device.transport.inject(.status(503), times: 2, matching: FakeServerTransport.isMutation)

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

    @Test("A redirect keeps every change and its key, backs off however long it lasts, and the status says why")
    func keepsEverythingWhileRedirected() async throws {
        let harness = SyncHarness()
        let device = await harness.device()
        try await device.signIn()
        try await device.apply(.createTask(.init(taskID: "x", title: "Call the bank", list: .inbox)))
        try await device.apply(.createTask(.init(taskID: "y", title: "Pay rent", list: .next)))
        let before = try await device.document().outbox
        // A misconfigured proxy starts redirecting every request.
        device.transport.inject(.status(307), times: 1_000)

        #expect(await device.sync() == .idle(lastSyncedAt: harness.clock.now()), "one failure is not yet failing")
        #expect(device.scheduler.pendingDelays == [.seconds(2)])
        let status = await device.sync()
        guard case .failing(let message, _, _) = status else {
            Issue.record("Expected .failing, got \(status)")
            return
        }
        #expect(message == APIError.redirectMessage)
        #expect(device.scheduler.pendingDelays == [.seconds(4)], "backing off")
        // Well past the eight failures and the day after which a change the
        // server keeps failing is set aside.
        for _ in 0..<10 {
            harness.clock.advance(by: 3 * 3600)
            await device.sync()
        }

        let during = try await device.document()
        #expect(during.issues.isEmpty, "a redirect says nothing about the change: nothing is set aside")
        #expect(during.outbox.map(\.id) == before.map(\.id))
        #expect(during.outbox.map(\.idempotencyKey) == before.map(\.idempotencyKey))
        #expect(during.outbox.first?.lastError == APIError.redirectMessage)
        #expect(during.outbox.first?.firstAttemptAt == nil, "nothing processed it, so no 23-hour clock runs")
        #expect(during.sync.lastFailure == APIError.redirectMessage)
        #expect(harness.snapshot.tasks.isEmpty)

        device.transport.clearFaults()
        #expect(await device.sync() == .idle(lastSyncedAt: harness.clock.now()))
        #expect(try await device.document().outbox.isEmpty)
        #expect(harness.snapshot.tasks.values.map(\.title).sorted() == ["Call the bank", "Pay rent"])
    }

    // MARK: An operation the server keeps failing

    /// Device b with a create the server always fails ("chokes") queued before
    /// a healthy one, and a task written on device a since.
    private func poisonedDevice(
        _ configure: (inout SyncConfiguration) -> Void = { _ in }
    ) async throws -> (SyncHarness, Device, Device, fault: FakeServerTransport.Fault) {
        let harness = SyncHarness()
        let a = await harness.device()
        let b = await harness.device(configure)
        try await a.signIn()
        try await b.signIn()
        try await b.apply(.createTask(.init(taskID: "bad", title: "Payload the server chokes on", list: .inbox)))
        try await b.apply(.createTask(.init(taskID: "ok", title: "Fine task", list: .inbox)))
        try await a.apply(.createTask(.init(taskID: "fromA", title: "Written on A", list: .next)))
        await a.sync()
        return (harness, a, b, .status(500))
    }

    @Test("A cycle blocked by a server error still pulls what other devices changed")
    func blockedPushStillPulls() async throws {
        let (harness, a, b, fault) = try await poisonedDevice()
        b.transport.inject(fault, times: 1_000) { $0.bodyText.contains("chokes") }

        let status = await b.sync()
        guard case .idle = status else {
            Issue.record("A first server failure is not yet failing, got \(status)")
            return
        }
        #expect(try await b.current().task(titled: "Written on A") != nil, "the pull ran")
        #expect(try await b.document().outbox.count == 2, "the blocked create keeps its place and key")
        #expect(harness.snapshot.task(titled: "Fine task") == nil, "nothing overtakes it yet")
        #expect(b.scheduler.pendingDelays == [.seconds(2)], "and it is retried with backoff")

        // The retry asks for no pull and the last one is recent: it pulls
        // because the push is still blocked.
        try await a.apply(.createTask(.init(taskID: "later", title: "Also written on A", list: .next)))
        await a.sync()
        #expect(await b.scheduler.runNext())
        await b.engine.waitUntilIdle()
        #expect(try await b.current().task(titled: "Also written on A") != nil)
        #expect(try await b.document().outbox.count == 2)
    }

    @Test("After eight server failures in a row the operation becomes a sync issue and the rest goes out")
    func setsAsideAnOperationTheServerKeepsFailing() async throws {
        let (harness, _, b, fault) = try await poisonedDevice()
        b.transport.inject(fault, times: 1_000) { $0.bodyText.contains("chokes") }

        for _ in 0..<7 {
            harness.clock.advance(by: 60)
            await b.sync()
        }
        #expect(try await b.document().issues.isEmpty, "seven failures are not enough")
        #expect(harness.snapshot.task(titled: "Fine task") == nil)

        harness.clock.advance(by: 60)
        #expect(await b.sync() == .idle(lastSyncedAt: harness.clock.now()))
        let document = try await b.document()
        #expect(document.outbox.isEmpty)
        #expect(document.issues.map(\.message) == ["The server kept rejecting this change."])
        #expect(document.issues.first?.referenceID != nil)
        #expect(harness.snapshot.task(titled: "Fine task") != nil)
        #expect(harness.snapshot.task(titled: "Payload the server chokes on") == nil)
        #expect(try await b.current().task(titled: "Written on A") != nil)
    }

    @Test("A success the device can't read, every time, is set aside the same way")
    func setsAsideAnUnreadableAnswerThatKeepsComing() async throws {
        let (harness, _, b, _) = try await poisonedDevice { $0.rejectionLimit = 3 }
        let garbled = GarbledSuccess(inner: b.transport) { $0.bodyText.contains("chokes") }
        let engine = SyncEngine(
            store: b.store, tokenStore: b.tokens, transport: garbled, now: harness.clock.provider,
            configuration: SyncConfiguration(
                scheduler: ManualSyncScheduler(), jitter: { 0.5 }, rejectionLimit: 3, clientVersion: "test"
            )
        )
        await engine.start(account: try #require(try await b.document().account))
        await engine.waitUntilIdle()
        _ = await engine.syncNow()
        _ = await engine.syncNow()

        let document = try await b.document()
        #expect(document.issues.map(\.message) == ["The server kept rejecting this change."])
        #expect(document.outbox.isEmpty)
        #expect(harness.snapshot.task(titled: "Fine task") != nil)
    }

    @Test("An operation failing for a day is set aside after two failures in a row, even after a relaunch")
    func setsAsideAnOperationFailingForADay() async throws {
        let (harness, a, b, taskOnB) = try await twoDevicesWithTask()
        _ = a
        try await b.apply(.updateTask(.init(taskID: taskOnB, changes: TaskChanges(details: .set("chokes the server")))))
        try await b.apply(.createTask(.init(taskID: "ok", title: "Fine task", list: .inbox)))
        b.transport.inject(.status(500), times: 1_000) { $0.bodyText.contains("chokes") }
        await b.sync()
        #expect(try await b.document().outbox.first?.firstAttemptAt == harness.clock.now())

        // The app is quit and opened a day later.
        harness.clock.advance(by: 25 * 3600)
        let relaunched = SyncEngine(
            store: b.store, tokenStore: b.tokens, transport: b.transport, now: harness.clock.provider,
            configuration: SyncConfiguration(scheduler: ManualSyncScheduler(), jitter: { 0.5 }, clientVersion: "test")
        )
        await relaunched.start(account: try #require(try await b.document().account))
        await relaunched.waitUntilIdle()
        #expect(try await b.document().issues.isEmpty, "one failure after a relaunch is not enough")

        _ = await relaunched.syncNow()
        let document = try await b.document()
        #expect(document.issues.map(\.message) == ["The server kept rejecting this change."])
        #expect(document.outbox.isEmpty)
        #expect(harness.snapshot.task(titled: "Fine task") != nil)
    }
}

/// Answers matching requests with a 201 whose body can't be decoded (after
/// the server applied nothing), like a server returning a shape the app
/// does not know.
final class GarbledSuccess: HTTPTransport {
    let inner: FakeServerTransport
    let matches: @Sendable (HTTPRequest) -> Bool

    init(inner: FakeServerTransport, matches: @escaping @Sendable (HTTPRequest) -> Bool) {
        self.inner = inner
        self.matches = matches
    }

    func send(_ request: HTTPRequest) async throws -> HTTPResponse {
        guard matches(request) else { return try await inner.send(request) }
        return HTTPResponse(statusCode: 201, headers: ["content-type": "application/json"], body: Data("{}".utf8))
    }
}
