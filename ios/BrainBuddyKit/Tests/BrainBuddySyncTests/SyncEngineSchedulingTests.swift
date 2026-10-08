import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyFakeServer
import BrainBuddyPersistence
import Foundation
import Synchronization
import Testing

@testable import BrainBuddySync

/// Holds the first request that matches until the test releases it, so a
/// cycle can be caught in flight without sleeping.
final class GatedTransport: HTTPTransport {
    private struct State {
        var armed: (@Sendable (HTTPRequest) -> Bool)?
        var held: CheckedContinuation<Void, Never>?
        var arrivals: [CheckedContinuation<Void, Never>] = []
        var arrived = false
    }

    private let inner: FakeServerTransport
    private let state = Mutex(State())

    init(_ inner: FakeServerTransport) { self.inner = inner }

    func hold(_ matching: @escaping @Sendable (HTTPRequest) -> Bool) { state.withLock { $0.armed = matching } }

    /// Returns once a held request is waiting.
    func arrived() async {
        await withCheckedContinuation { continuation in
            let ready = state.withLock { state -> Bool in
                if state.arrived { return true }
                state.arrivals.append(continuation)
                return false
            }
            if ready { continuation.resume() }
        }
    }

    func release() {
        let held = state.withLock { state -> CheckedContinuation<Void, Never>? in
            defer { state.held = nil }
            return state.held
        }
        held?.resume()
    }

    func send(_ request: HTTPRequest) async throws -> HTTPResponse {
        let shouldHold = state.withLock { state -> Bool in
            guard let armed = state.armed, armed(request) else { return false }
            state.armed = nil
            return true
        }
        if shouldHold {
            await withCheckedContinuation { continuation in
                let waiting = state.withLock { state -> [CheckedContinuation<Void, Never>] in
                    state.held = continuation
                    state.arrived = true
                    defer { state.arrivals.removeAll() }
                    return state.arrivals
                }
                for waiter in waiting { waiter.resume() }
            }
        }
        return try await inner.send(request)
    }
}

@Suite("SyncEngine: triggers, status and account")
struct SyncEngineSchedulingTests {
    @Test("Without an account the engine stays local and sends nothing")
    func staysLocalWithoutAccount() async throws {
        let harness = SyncHarness()
        let device = await harness.device()
        try await device.apply(.createTask(.init(taskID: "x", title: "Buy milk", list: .inbox)))
        await device.engine.request(.localChange)
        await device.engine.request(.foreground)
        #expect(await device.sync() == .localOnly)
        await device.engine.refreshTask("x")
        #expect(device.transport.requests.isEmpty)
        #expect(device.scheduler.pendingDelays.isEmpty)
        #expect(try await device.document().outbox.count == 1)
    }

    @Test("A local change syncs two seconds after the last one")
    func debouncesLocalChanges() async throws {
        let harness = SyncHarness()
        let device = await harness.device()
        try await device.signIn()
        device.transport.clearLog()
        try await device.apply(.createTask(.init(taskID: "x", title: "Buy milk", list: .inbox)))
        await device.engine.request(.localChange)
        try await device.apply(.createTask(.init(taskID: "y", title: "Buy bread", list: .inbox)))
        await device.engine.request(.localChange)

        #expect(device.scheduler.pendingDelays == [.seconds(2)], "the second change restarts the wait")
        #expect(device.transport.requests.isEmpty)
        #expect(await device.scheduler.runNext())
        await device.engine.waitUntilIdle()
        #expect(device.mutations.count == 2)
        #expect(harness.snapshot.tasks.count == 2)
    }

    @Test("Starting a linked account reports its last sync and runs a launch cycle")
    func startsLinkedAccount() async throws {
        let harness = SyncHarness()
        let first = await harness.device()
        let account = try await first.signIn()
        try await first.apply(.createTask(.init(taskID: "x", title: "Buy milk", list: .inbox)))
        let signedInAt = harness.clock.now()
        harness.clock.advance(by: 600)

        // The app relaunches: a new engine over the same document and session.
        let relaunched = SyncEngine(
            store: first.store, tokenStore: first.tokens, transport: first.transport, now: harness.clock.provider,
            configuration: SyncConfiguration(scheduler: ManualSyncScheduler(), jitter: { 0.5 }, clientVersion: "test")
        )
        let events = EventLog()
        await relaunched.setEventHandler { events.append($0) }
        await relaunched.start(account: account)
        await relaunched.waitUntilIdle()
        #expect(events.statuses == [
            .idle(lastSyncedAt: signedInAt), .syncing, .idle(lastSyncedAt: harness.clock.now()),
        ])
        #expect(harness.snapshot.tasks.count == 1)
    }

    @Test("Offline: nothing is attempted and the status says so; back online, a cycle runs")
    func followsNetworkAvailability() async throws {
        let harness = SyncHarness()
        let device = await harness.device()
        try await device.signIn()
        let syncedAt = harness.clock.now()
        await device.engine.setNetworkAvailable(false)
        #expect(await device.status == .offline(lastSyncedAt: syncedAt))
        device.transport.clearLog()
        try await device.apply(.createTask(.init(taskID: "x", title: "Buy milk", list: .inbox)))
        await device.engine.request(.localChange)
        await device.scheduler.runAll()
        #expect(await device.sync() == .offline(lastSyncedAt: syncedAt))
        #expect(device.transport.requests.isEmpty)

        harness.clock.advance(by: 5)
        await device.engine.setNetworkAvailable(true)
        await device.engine.waitUntilIdle()
        #expect(await device.status == .idle(lastSyncedAt: harness.clock.now()))
        #expect(harness.snapshot.tasks.count == 1)
    }

    @Test("syncNow joins a cycle in flight instead of starting a second one")
    func joinsRunningCycle() async throws {
        let harness = SyncHarness()
        let transport = GatedTransport(harness.server.makeTransport())
        let store = InMemoryDocumentStore()
        let engine = SyncEngine(
            store: store, tokenStore: InMemorySessionTokenStore(), transport: transport, now: harness.clock.provider,
            configuration: SyncConfiguration(scheduler: ManualSyncScheduler(), jitter: { 0.5 }, clientVersion: "test")
        )
        _ = try await engine.signIn(
            serverURL: FakeBrainBuddyServer.baseURL, email: SyncHarness.email, password: SyncHarness.password
        )
        let date = harness.clock.now()
        _ = try await store.update { doc in
            let command = GTDCommand.createTask(.init(taskID: "x", title: "Buy milk", list: .inbox))
            doc.outbox = OutboxCompactor.appending(PendingOperation(command: command, issuedAt: date), to: doc.outbox)
        }
        transport.hold { $0.method == .post && $0.url.path.hasSuffix("/tasks") }

        let first = Task { await engine.syncNow() }
        await transport.arrived()
        let second = Task { await engine.syncNow() }
        while await engine.joinedCycles == 0 { await Task.yield() }
        transport.release()
        let statuses = await [first.value, second.value]
        #expect(statuses == [.idle(lastSyncedAt: date), .idle(lastSyncedAt: date)])
        #expect(harness.snapshot.tasks.count == 1)
    }

    @Test("A sync reports syncing, then idle")
    func reportsStatus() async throws {
        let harness = SyncHarness()
        let device = await harness.device()
        try await device.signIn()
        #expect(device.events.statuses == [.syncing, .idle(lastSyncedAt: harness.clock.now())])
        device.events.clear()
        harness.clock.advance(by: 10)
        await device.sync()
        #expect(device.events.statuses == [.syncing, .idle(lastSyncedAt: harness.clock.now())])
    }

    @Test("Sign-in failures come back in words for the sign-in sheet, and nothing is linked")
    func explainsSignInFailures() async throws {
        let harness = SyncHarness()
        let device = await harness.device()
        do {
            _ = try await device.engine.signIn(serverURL: FakeBrainBuddyServer.baseURL, email: SyncHarness.email, password: "wrong")
            Issue.record("Expected a failure")
        } catch {
            #expect(error.message == "Check your email and password.")
            #expect(error.referenceID != nil)
        }
        device.transport.inject(.status(429))
        await expectSignInFailure(device, "Too many attempts. Try again in a few minutes.")
        device.transport.inject(.offline)
        await expectSignInFailure(device, "Can't reach the server. Check your connection.")
        do {
            _ = try await device.engine.signIn(
                serverURL: URL(string: "http://example.com/api")!, email: SyncHarness.email, password: SyncHarness.password
            )
            Issue.record("Expected a failure")
        } catch {
            #expect(error.message == "Use an https server address.")
        }
        #expect(try await device.store.load() == nil, "a failed sign-in writes nothing")
        #expect(await device.status == .localOnly)
    }

    private func expectSignInFailure(_ device: Device, _ message: String, sourceLocation: SourceLocation = #_sourceLocation) async {
        do {
            _ = try await device.engine.signIn(
                serverURL: FakeBrainBuddyServer.baseURL, email: SyncHarness.email, password: SyncHarness.password
            )
            Issue.record("Expected a failure", sourceLocation: sourceLocation)
        } catch {
            #expect(error.message == message, sourceLocation: sourceLocation)
        }
    }

    @Test("Signing out logs out on the server, forgets the session, and leaves the document alone")
    func signsOut() async throws {
        let harness = SyncHarness()
        let device = await harness.device()
        try await device.signIn()
        try await device.apply(.createTask(.init(taskID: "x", title: "Buy milk", list: .inbox)))
        let before = try await device.document()
        device.transport.clearLog()

        try await device.engine.signOut(removingLocalDataWith: {})
        #expect(device.transport.requests.map(\.route) == ["POST /auth/logout"])
        #expect(try device.tokens.token(for: FakeBrainBuddyServer.baseURL) == nil)
        #expect(try await device.document() == before)
        #expect(await device.status == .localOnly)
        await device.engine.request(.manual)
        #expect(await device.sync() == .localOnly)
        #expect(device.transport.requests.count == 1)
    }

    // MARK: Periodic ticks and Sync now

    @Test("021-FR-006 021-FR-032 a tick inside the pull age runs no cycle, reports nothing and asks for no pull; at 30 s it pulls")
    func quietTicksPullAtThirtySeconds() async throws {
        let harness = SyncHarness()
        let device = await harness.device { $0.pullInterval = SyncTiming.pullAge }
        try await device.signIn()
        device.transport.clearLog()
        device.events.clear()

        for elapsed in [15.0, 14.0] {  // ticks at 15 s and, as it may drift, at 29 s
            harness.clock.advance(by: elapsed)
            await device.engine.request(.periodic)
            await device.engine.waitUntilIdle()
            #expect(device.transport.requests.isEmpty, "no request")
            #expect(device.events.all.isEmpty, "no .status and no .documentChanged")
            #expect(await device.engine.pullRequested == false)
        }

        harness.clock.advance(by: 1)
        await device.engine.request(.periodic)
        await device.engine.waitUntilIdle()
        #expect(device.transport.requests.contains { $0.route == "GET /tasks" }, "the pull is due")
        #expect(await device.status == .idle(lastSyncedAt: harness.clock.now()))
    }

    @Test("021-FR-006 a tick sends changes that wait, but not while a debounce is scheduled")
    func tickSendsWaitingChanges() async throws {
        let harness = SyncHarness()
        let device = await harness.device { $0.pullInterval = SyncTiming.pullAge }
        try await device.signIn()
        try await device.apply(.createTask(.init(taskID: "x", title: "Buy milk", list: .inbox)))
        await device.engine.request(.localChange)
        harness.clock.advance(by: 1)

        await device.engine.request(.periodic)
        await device.engine.waitUntilIdle()
        #expect(device.mutations.isEmpty, "the debounce will send it")

        await device.scheduler.runAll()
        await device.engine.waitUntilIdle()
        #expect(harness.snapshot.tasks.count == 1)
        try await device.apply(.createTask(.init(taskID: "y", title: "Buy bread", list: .inbox)))
        harness.clock.advance(by: 5)
        await device.engine.request(.periodic)
        await device.engine.waitUntilIdle()
        #expect(harness.snapshot.tasks.count == 2, "no debounce was waiting for this one")
    }

    @Test("021-FR-006 a tick never shortens a backoff, while Retry runs at once")
    func tickLeavesTheBackoffAlone() async throws {
        let harness = SyncHarness()
        let device = await harness.device { $0.pullInterval = SyncTiming.pullAge }
        try await device.signIn()
        try await device.apply(.createTask(.init(taskID: "x", title: "Buy milk", list: .inbox)))
        device.transport.inject(.status(503), matching: FakeServerTransport.isMutation)
        await device.engine.request(.localChange)
        await device.scheduler.runNext()
        await device.engine.waitUntilIdle()
        #expect(device.scheduler.pendingDelays.count == 1, "a retry is waiting")

        device.transport.clearLog()
        harness.clock.advance(by: 100)
        await device.engine.request(.periodic)
        await device.engine.waitUntilIdle()
        #expect(device.transport.requests.isEmpty)
        #expect(device.scheduler.pendingDelays.count == 1)

        await device.engine.request(.manual)
        await device.engine.waitUntilIdle()
        #expect(harness.snapshot.tasks.count == 1, "Retry sent it at once")
        #expect(device.scheduler.pendingDelays.isEmpty)
    }

    @Test("021-FR-019 Sync now pressed three times during a cycle queues exactly one follow-up and is never refused")
    func syncNowIsSingleFlight() async throws {
        let harness = SyncHarness()
        let inner = harness.server.makeTransport()
        let transport = GatedTransport(inner)
        let engine = SyncEngine(
            store: InMemoryDocumentStore(), tokenStore: InMemorySessionTokenStore(), transport: transport,
            now: harness.clock.provider,
            configuration: SyncConfiguration(scheduler: ManualSyncScheduler(), jitter: { 0.5 }, clientVersion: "test"))
        _ = try await engine.signIn(
            serverURL: FakeBrainBuddyServer.baseURL, email: SyncHarness.email, password: SyncHarness.password)
        inner.clearLog()
        transport.hold { $0.url.path.hasSuffix("/tags") }  // inside the pull, after the cycle decided to pull

        let first = Task { await engine.syncNow() }
        await transport.arrived()
        let second = Task { await engine.syncNow() }
        let third = Task { await engine.syncNow() }
        while await engine.joinedCycles < 2 { await Task.yield() }
        transport.release()

        let statuses = await [first.value, second.value, third.value]
        await engine.waitUntilIdle()
        #expect(statuses.allSatisfy { $0.isIdle }, "every press got an answer")
        #expect(inner.requests.filter { $0.route == "GET /tasks" }.count == 2, "the running cycle and one follow-up")
    }
}
