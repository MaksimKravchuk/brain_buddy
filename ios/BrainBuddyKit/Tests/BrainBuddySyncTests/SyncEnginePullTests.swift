import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyFakeServer
import Foundation
import Testing

@testable import BrainBuddySync

@Suite("SyncEngine: pull, sign-in and hydration")
struct SyncEnginePullTests {
    @Test("A pull merges under pending local changes: local intent wins on the fields it changed")
    func pullKeepsLocalIntent() async throws {
        let harness = SyncHarness()
        let a = await harness.device()
        let b = await harness.device()
        try await a.signIn()
        try await a.apply(.createTask(.init(taskID: "x", title: "Renew passport", list: .next)))
        await a.sync()
        try await b.signIn()
        let taskOnB = try #require(try await b.current().task(titled: "Renew passport")).id

        // b's session expires with a change queued; meanwhile a edits other fields.
        try await b.apply(.updateTask(.init(taskID: taskOnB, changes: TaskChanges(title: .set("Renew passport now")))))
        b.transport.inject(.status(401))
        #expect(await b.sync() == .needsSignIn)
        try await a.apply(.updateTask(.init(taskID: "x", changes: TaskChanges(priority: .set(.high)))))
        try await a.apply(.createTask(.init(taskID: "y", title: "Book photos", list: .inbox)))
        await a.sync()
        b.events.clear()
        harness.clock.advance(by: 60)
        let pullTime = harness.clock.now()

        // Signing in again pulls first, with the change still queued.
        try await b.signIn()
        let pulled = try #require(b.events.documents.first { $0.sync.lastPullAt == pullTime })
        #expect(pulled.outbox.count == 1)
        let merged = OutboxReplayer.replay(pulled.outbox, onto: pulled.base).state
        #expect(merged.tasks[taskOnB]?.title == "Renew passport now")
        #expect(merged.tasks[taskOnB]?.priority == .high)
        #expect(merged.task(titled: "Book photos") != nil)

        let server = harness.snapshot
        #expect(server.task(titled: "Renew passport now")?.priority == .high)
        #expect(try CanonicalState(await b.current(), children: false) == CanonicalState(server, children: false))
    }

    @Test("A pull maps server records to the ids the device uses and drops what the server no longer has")
    func pullKeepsClientIDs() async throws {
        let harness = SyncHarness()
        let device = await harness.device()
        try await device.signIn()
        try await device.apply(.createProject(.init(projectID: "p", name: "Garden")))
        try await device.apply(.createTag(.init(tagID: "t", name: "outside")))
        try await device.apply(.createTask(.init(taskID: "x", title: "Plant tulips", list: .next, projectID: "p", tagIDs: ["t"])))
        await device.sync()
        let other = await harness.device()
        try await other.signIn()
        let otherProject = try #require(try await other.current().project(named: "Garden")).id
        try await other.apply(.archiveProject(otherProject))
        await other.sync()

        harness.clock.advance(by: 120)
        #expect(await device.sync() == .idle(lastSyncedAt: harness.clock.now()))
        let base = try await device.document().base
        #expect(Set(base.tasks.keys) == ["x"])
        #expect(base.projects["p"]?.state == .archived, "a known archived project comes with the listing")
        #expect(base.tasks["x"]?.projectID == "p", "an archive keeps the membership (ADR-0020)")
        #expect(base.tasks["x"]?.tagIDs == ["t"])
        #expect(base.tasks["x"]?.serverRevision == harness.snapshot.tasks.values.first?.revision)
    }

    @Test("021-FR-024 021-FR-026 the pull lists projects with ?state=all, not one request per archived project; deleted tags are still fetched by id")
    func pullListsEveryProjectAtOnce() async throws {
        let harness = SyncHarness()
        let a = await harness.device()
        try await a.signIn()
        try await a.apply(.createProject(.init(projectID: "p", name: "Garden")))
        try await a.apply(.createTag(.init(tagID: "t", name: "outside")))
        try await a.apply(.createTask(.init(taskID: "x", title: "Plant tulips", list: .next, projectID: "p", tagIDs: ["t"])))
        await a.sync()
        let b = await harness.device()
        try await b.signIn()
        try await a.apply(.archiveProject("p"))
        try await a.apply(.deleteTag("t"))
        await a.sync()

        harness.clock.advance(by: 120)
        b.transport.clearLog()
        await b.sync()
        let routes = b.transport.requests.map(\.route)
        #expect(routes.filter { $0.hasPrefix("GET /projects") } == ["GET /projects"], "one listing, no GET by id")
        #expect(b.transport.requests.first { $0.route == "GET /projects" }?.url.query == "state=all")
        #expect(routes.contains { $0.hasPrefix("GET /tags/tag_") }, "the tag endpoint has no filter")
        let base = try await b.document().base
        #expect(base.project(named: "Garden")?.state == .archived && base.tag(named: "outside")?.state == .deleted)
    }

    @Test("Signing in with local-only data pulls first, merges projects and tags by name, and uploads the rest")
    func firstSignInMergesByName() async throws {
        let harness = SyncHarness()
        let a = await harness.device()
        try await a.signIn()
        try await a.apply(.createProject(.init(projectID: "work", name: "Work")))
        try await a.apply(.createTag(.init(tagID: "home", name: "home")))
        try await a.apply(.createTask(.init(taskID: "old", title: "Existing task", list: .next, projectID: "work")))
        await a.sync()

        // A device used without an account.
        let b = await harness.device()
        try await b.apply(.createProject(.init(projectID: "local-work", name: " work ")))
        try await b.apply(.createTag(.init(tagID: "local-home", name: "@Home")))
        try await b.apply(.createProject(.init(projectID: "garden", name: "Garden")))
        try await b.apply(
            .createTask(.init(taskID: "t1", title: "Plan the week", list: .next, projectID: "local-work", tagIDs: ["local-home"]))
        )
        try await b.apply(.createTask(.init(taskID: "t2", title: "Plant tulips", list: .someday, projectID: "garden")))
        #expect(await b.status == .localOnly)
        b.transport.clearLog()

        let account = try await b.signIn()
        #expect(account.email == SyncHarness.email)
        #expect(b.transport.requests.first?.route == "POST /auth/login")
        #expect(b.transport.requests.dropFirst().first?.route == "GET /tasks", "the first cycle pulls before it pushes")
        #expect(b.mutations.map(\.route) == ["POST /projects", "POST /tasks", "POST /tasks"])

        let server = harness.snapshot
        #expect(server.projects.values.map(\.name).sorted() == ["Garden", "Work"])
        #expect(server.tags.values.map(\.name) == ["home"])
        #expect(server.tasks.count == 3)
        #expect(server.task(titled: "Plan the week")?.projectID == server.project(named: "Work")?.id)
        #expect(server.task(titled: "Plan the week")?.tagIDs == [try #require(server.tag(named: "home")).id])
        let document = try await b.document()
        #expect(document.account?.id == harness.accountID)
        #expect(document.issues.isEmpty)
        #expect(try CanonicalState(await b.current(), children: false) == CanonicalState(server, children: false))
    }

    @Test("A create left uncertain for more than 23 hours adopts the record it made instead of sending it again")
    func adoptsUncertainCreate() async throws {
        let harness = SyncHarness()
        let device = await harness.device()
        try await device.signIn()
        try await device.apply(.createTask(.init(taskID: "x", title: "  Call the bank ", list: .waiting, waitingFor: "Bank")))
        try await device.apply(.createSubtask(.init(taskID: "x", subtaskID: "s", title: "Find the number")))
        device.transport.inject(.dropResponse, matching: FakeServerTransport.isMutation)
        #expect(await device.sync() == .offline(lastSyncedAt: harness.clock.now()))
        #expect(harness.snapshot.tasks.count == 1)

        // A day later the server has forgotten the key.
        harness.clock.advance(by: 25 * 3600)
        device.transport.clearLog()
        #expect(await device.sync() == .idle(lastSyncedAt: harness.clock.now()))
        #expect(device.mutations.map(\.route).allSatisfy { $0.hasSuffix("/subtasks") }, "the task was not created again")
        let server = harness.snapshot
        #expect(server.tasks.count == 1)
        let document = try await device.document()
        #expect(document.outbox.isEmpty)
        #expect(document.issues.isEmpty)
        #expect(document.base.tasks["x"]?.serverID == server.tasks.keys.first)
        #expect(document.base.tasks.count == 1)
        #expect(server.tasks.values.first?.subtasks.map(\.title) == ["Find the number"])
    }

    @Test("An uncertain create the server never saw is sent again after 23 hours, once")
    func resendsUncertainCreateThatNeverLanded() async throws {
        let harness = SyncHarness()
        let device = await harness.device()
        try await device.signIn()
        try await device.apply(.createTask(.init(taskID: "x", title: "Call the bank", list: .inbox)))
        try await device.apply(.createComment(.init(taskID: "x", commentID: "c", body: "Ask about fees.")))
        device.transport.inject(.timeout, matching: FakeServerTransport.isMutation)
        #expect(await device.sync() == .offline(lastSyncedAt: harness.clock.now()))
        let firstKey = try #require(try await device.document().outbox.first).idempotencyKey

        harness.clock.advance(by: 25 * 3600)
        device.transport.clearLog()
        #expect(await device.sync() == .idle(lastSyncedAt: harness.clock.now()))
        let posts = device.mutations.filter { $0.route == "POST /tasks" }
        #expect(posts.count == 1)
        #expect(posts.first?.idempotencyKey != firstKey.uuidString.lowercased(), "an expired key is not reused")
        #expect(harness.snapshot.tasks.count == 1)
        #expect(harness.snapshot.tasks.values.first?.comments.map(\.body) == ["Ask about fees."])
    }

    @Test("An uncertain subtask or comment older than 23 hours is adopted from the task detail")
    func adoptsUncertainChildren() async throws {
        let harness = SyncHarness()
        let device = await harness.device()
        try await device.signIn()
        try await device.apply(.createTask(.init(taskID: "x", title: "Call the bank", list: .inbox)))
        await device.sync()
        try await device.apply(.createSubtask(.init(taskID: "x", subtaskID: "s", title: "Find the number")))
        device.transport.inject(.dropResponse, matching: FakeServerTransport.isMutation)
        await device.sync()
        harness.clock.advance(by: 24 * 3600)
        try await device.apply(.createComment(.init(taskID: "x", commentID: "c", body: "Ask about fees.")))
        harness.clock.advance(by: 30)

        device.transport.clearLog()
        #expect(await device.sync() == .idle(lastSyncedAt: harness.clock.now()))
        #expect(device.mutations.map(\.route).allSatisfy { $0.hasSuffix("/comments") })
        let task = try #require(harness.snapshot.tasks.values.first)
        #expect(task.subtasks.map(\.title) == ["Find the number"])
        let base = try await device.document().base
        #expect(base.tasks["x"]?.subtasks.map(\.id) == ["s"])
        #expect(base.tasks["x"]?.subtasks.first?.serverID == task.subtasks.first?.id)
    }

    @Test("A create that never left the device starts no 23-hour clock and goes out later under its own key")
    func offlineAttemptStartsNoUncertaintyClock() async throws {
        let harness = SyncHarness()
        let device = await harness.device()
        try await device.signIn()
        try await device.apply(.createTask(.init(taskID: "x", title: "Call the bank", list: .inbox)))
        device.transport.inject(.offline, matching: FakeServerTransport.isMutation)
        #expect(await device.sync() == .offline(lastSyncedAt: harness.clock.now()))
        let pending = try #require(try await device.document().outbox.first)
        #expect(pending.firstAttemptAt == nil, "the request provably never left")
        #expect(pending.lastAttemptAt == harness.clock.now())

        // A day later it is simply sent, with its key: no pull-and-adopt detour.
        harness.clock.advance(by: 25 * 3600)
        device.transport.clearLog()
        #expect(await device.sync() == .idle(lastSyncedAt: harness.clock.now()))
        #expect(device.transport.requests.first?.route == "POST /tasks", "not resolved as an uncertain create")
        #expect(device.mutations.compactMap(\.idempotencyKey) == [pending.idempotencyKey.uuidString.lowercased()])
        #expect(harness.snapshot.tasks.count == 1)
    }

    @Test("An uncertain subtask is matched against the task's current subtasks: the newest same-titled one is ours")
    func adoptsTheNewestMatchingSubtask() async throws {
        let harness = SyncHarness()
        let a = await harness.device()
        let b = await harness.device()
        try await a.signIn()
        try await a.apply(.createTask(.init(taskID: "x", title: "Groceries", list: .next)))
        await a.sync()
        try await b.signIn()
        let taskOnB = try #require(try await b.current().task(titled: "Groceries")).id
        #expect(try await b.document().base.tasks[taskOnB]?.childrenSyncedAt != nil)

        // a adds "Milk"; b never learns (subtasks don't bump the task).
        try await a.apply(.createSubtask(.init(taskID: "x", subtaskID: "a-milk", title: "Milk")))
        await a.sync()
        await b.sync()
        #expect(try await b.document().base.tasks[taskOnB]?.subtasks.isEmpty == true)

        // b adds its own "Milk"; the answer is lost.
        try await b.apply(.createSubtask(.init(taskID: taskOnB, subtaskID: "b-milk", title: "Milk")))
        b.transport.inject(.dropResponse, matching: FakeServerTransport.isMutation)
        await b.sync()
        let serverTask = try #require(harness.snapshot.tasks.values.first)
        #expect(serverTask.subtasks.map(\.title) == ["Milk", "Milk"])
        let bMilkOnServer = try #require(serverTask.subtasks.last).id

        // A day later the key is gone: b adopts its own subtask, not a's.
        harness.clock.advance(by: 25 * 3600)
        #expect(await b.sync() == .idle(lastSyncedAt: harness.clock.now()))
        let subtasks = try #require(try await b.document().base.tasks[taskOnB]?.subtasks)
        #expect(subtasks.first { $0.id == "b-milk" }?.serverID == bMilkOnServer)
        #expect(harness.snapshot.tasks.values.first?.subtasks.count == 2, "nothing was created twice")
        #expect(try await b.document().outbox.isEmpty)
    }

    @Test("Open tasks are hydrated after a pull, within the budget; a changed revision hydrates again")
    func hydratesChildren() async throws {
        let harness = SyncHarness()
        let a = await harness.device()
        try await a.signIn()
        for index in 1...3 {
            let id = TaskID("t\(index)")
            try await a.apply(.createTask(.init(taskID: id, title: "Task \(index)", list: .next)))
            try await a.apply(.createSubtask(.init(taskID: id, subtaskID: SubtaskID("s\(index)"), title: "Step \(index)")))
            try await a.apply(.createComment(.init(taskID: id, commentID: CommentID("c\(index)"), body: "Note \(index)")))
        }
        try await a.apply(.transitionTask(.init(taskID: "t3", action: .complete)))
        await a.sync()

        let b = await harness.device { $0.hydrationBudget = 1 }
        try await b.signIn()
        var base = try await b.document().base
        let hydrated = base.tasks.values.filter { $0.childrenSyncedAt != nil }
        #expect(hydrated.count == 1, "one task per cycle with a budget of 1")
        #expect(hydrated.first?.subtasks.count == 1)
        await b.sync()
        base = try await b.document().base
        #expect(base.tasks.values.filter { $0.isOpen && $0.childrenSyncedAt == nil }.isEmpty)
        #expect(base.task(titled: "Task 3")?.childrenSyncedAt == nil, "terminal tasks wait until opened")
        #expect(base.task(titled: "Task 1")?.comments.map(\.body) == ["Note 1"])

        // A subtask added elsewhere does not bump the task: only opening it shows it...
        try await a.apply(.createSubtask(.init(taskID: "t1", subtaskID: "s1b", title: "Step 1b")))
        await a.sync()
        await b.sync()
        let taskOnB = try #require(try await b.current().task(titled: "Task 1"))
        #expect(taskOnB.subtasks.count == 1)
        await b.engine.refreshTask(taskOnB.id)
        #expect(try await b.current().tasks[taskOnB.id]?.subtasks.map(\.title) == ["Step 1", "Step 1b"])

        // ...while an edit to the task marks it and the next cycle hydrates it.
        harness.clock.advance(by: 60)
        try await a.apply(.createComment(.init(taskID: "t2", commentID: "c2b", body: "Note 2b")))
        try await a.apply(.updateTask(.init(taskID: "t2", changes: TaskChanges(priority: .set(.high)))))
        await a.sync()
        await b.sync()
        #expect(try await b.current().task(titled: "Task 2")?.comments.map(\.body) == ["Note 2", "Note 2b"])
        #expect(try CanonicalState(await b.current(), children: false) == CanonicalState(harness.snapshot, children: false))
    }

    @Test("Pulls follow the task cursor across pages")
    func pullsEveryPage() async throws {
        let harness = SyncHarness()
        let a = await harness.device()
        try await a.signIn()
        for index in 0..<205 {
            try await a.apply(.createTask(.init(taskID: TaskID("t\(index)"), title: "Task \(index)", list: .inbox)))
        }
        await a.sync()
        let b = await harness.device { $0.hydrationBudget = 0 }
        try await b.signIn()
        #expect(b.transport.requests.filter { $0.route == "GET /tasks" }.count == 2)
        #expect(try await b.document().base.tasks.count == 205)
    }
}
