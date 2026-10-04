import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyFakeServer
import BrainBuddyPersistence
import Foundation
import Synchronization
import Testing

@testable import BrainBuddySync

/// Where a held response waits: the test learns that it arrived, then lets it go.
actor ResponseGate {
    private var isOpen = false
    private var arrived = false
    private var waiters: [CheckedContinuation<Void, Never>] = []
    private var arrivalWaiters: [CheckedContinuation<Void, Never>] = []

    func arrive() {
        arrived = true
        arrivalWaiters.forEach { $0.resume() }
        arrivalWaiters = []
    }

    func waitForArrival() async {
        if arrived { return }
        await withCheckedContinuation { arrivalWaiters.append($0) }
    }

    func wait() async {
        if isOpen { return }
        await withCheckedContinuation { waiters.append($0) }
    }

    func open() {
        isOpen = true
        waiters.forEach { $0.resume() }
        waiters = []
    }
}

/// Lets the server answer the first request `matches` accepts at once (so
/// the server state already reflects it), then holds the response until
/// `gate` opens: a request caught in flight after it landed.
final class HoldingTransport: HTTPTransport {
    let inner: FakeServerTransport
    let gate = ResponseGate()
    let matches: @Sendable (HTTPRequest) -> Bool
    /// Not armed until the device is set up; then holds exactly one request.
    private let used = Mutex(true)

    init(inner: FakeServerTransport, matches: @escaping @Sendable (HTTPRequest) -> Bool) {
        self.inner = inner
        self.matches = matches
    }

    func arm() { used.withLock { $0 = false } }

    func send(_ request: HTTPRequest) async throws -> HTTPResponse {
        let hold =
            matches(request)
            && used.withLock { used in
                if used { return false }
                used = true
                return true
            }
        guard hold else { return try await inner.send(request) }
        let response: HTTPResponse
        do {
            response = try await inner.send(request)
        } catch {
            await gate.arrive()
            await gate.wait()
            throw error
        }
        await gate.arrive()
        await gate.wait()
        return response
    }
}

/// A device like `Device`, over a `HoldingTransport`.
final class HeldDevice: Sendable {
    let clock: ManualClock
    let store = InMemoryDocumentStore()
    let tokens = InMemorySessionTokenStore()
    let inner: FakeServerTransport
    let transport: HoldingTransport
    let engine: SyncEngine

    init(harness: SyncHarness, matches: @escaping @Sendable (HTTPRequest) -> Bool) {
        clock = harness.clock
        inner = harness.server.makeTransport()
        transport = HoldingTransport(inner: inner, matches: matches)
        let configuration = SyncConfiguration(scheduler: ManualSyncScheduler(), jitter: { 0.5 }, clientVersion: "test")
        engine = SyncEngine(
            store: store, tokenStore: tokens, transport: transport, now: harness.clock.provider,
            configuration: configuration
        )
    }

    /// Signs in and waits for the first sync; only then does the transport hold.
    func signIn() async throws {
        _ = try await engine.signIn(
            serverURL: FakeBrainBuddyServer.baseURL, email: SyncHarness.email, password: SyncHarness.password
        )
        await engine.waitUntilIdle()
        transport.arm()
    }

    /// Like `Device.apply`: validated against the current state, appended through the compactor.
    @discardableResult
    func apply(_ command: GTDCommand) async throws -> StoreDocument {
        let date = clock.now()
        return try await store.update { doc in
            var state = OutboxReplayer.replay(doc.outbox, onto: doc.base).state
            try GTDReducer.apply(command, at: date, to: &state)
            doc.outbox = OutboxCompactor.appending(PendingOperation(command: command, issuedAt: date), to: doc.outbox)
        }
    }

    func document() async throws -> StoreDocument { try await store.load() ?? StoreDocument() }

    func current() async throws -> GTDState {
        let document = try await document()
        return OutboxReplayer.replay(document.outbox, onto: document.base).state
    }

    /// Mutations the server was sent (held or not).
    var mutations: [HTTPRequest] { inner.requests.filter(FakeServerTransport.isMutation) }
}
