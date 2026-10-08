import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyFakeServer
import BrainBuddyPersistence
import Foundation
import Synchronization
import Testing

@testable import BrainBuddySync

/// Reports the network gone, as the path monitor would, while a request is on its way, and fails that request.
final class DroppingNetworkTransport: HTTPTransport {
    private let inner: FakeServerTransport
    private let engine = Mutex<SyncEngine?>(nil)
    private let armed = Mutex(false)

    init(_ inner: FakeServerTransport) { self.inner = inner }

    func arm(for engine: SyncEngine) {
        self.engine.withLock { $0 = engine }
        armed.withLock { $0 = true }
    }

    func send(_ request: HTTPRequest) async throws -> HTTPResponse {
        guard armed.withLock({ $0 }), let engine = engine.withLock({ $0 }) else { return try await inner.send(request) }
        armed.withLock { $0 = false }
        await engine.setNetworkAvailable(false)
        throw TransportError(description: "The Internet connection appears to be offline.", requestMayHaveBeenSent: false)
    }
}

/// The failing clock of the line "Couldn't sync" (spec 021, FR-014, FR-015, SC-005).
@Suite("SyncEngine: the failing clock")
struct SyncEngineFailingClockTests {
    /// Every way a cycle can be blocked on the server's side.
    static let blockedByTheServer: [(name: String, fault: FakeServerTransport.Fault)] = [
        ("5xx", .status(503)), ("429", .status(429)), ("redirect", .status(302)), ("unreadable 2xx", .status(200)),
        ("timeout with a network", .timeout),
    ]

    /// What the status line would say about the stored metadata.
    private func lineState(_ document: StoreDocument, at now: Date) -> SyncLineState {
        let sync = document.sync
        let snapshot = SyncSnapshot(
            account: .linked(email: SyncHarness.email), lastSyncedAt: sync.lastPullAt, failingSince: sync.failingSince,
            lastFailedAttemptAt: sync.lastFailedAttemptAt, lastFailureReferenceID: sync.lastFailureReferenceID)
        return SyncStatusDescriber.describe(snapshot, now: now, device: .mac, calendar: Calendar(identifier: .gregorian)).state
    }

    private func seconds(_ duration: Duration) -> TimeInterval {
        Double(duration.components.seconds) + Double(duration.components.attoseconds) / 1e18
    }

    @Test("021-FR-014 021-FR-015 a cycle the server blocked starts the clock and keeps the request's reference id")
    func blockedCycleStartsTheClock() async throws {
        for (name, fault) in Self.blockedByTheServer {
            let harness = SyncHarness()
            let device = await harness.device()
            try await device.signIn()
            harness.clock.advance(by: 100)
            let started = harness.clock.now()
            device.transport.inject(fault, times: 1_000)

            await device.sync()
            var sync = try await device.document().sync
            #expect(sync.failingSince == started, "\(name)")
            #expect(sync.lastFailedAttemptAt == started, "\(name)")
            let sent = try #require(device.transport.requests.last).header("X-Correlation-ID")
            #expect(sync.lastFailureReferenceID == sent, "\(name): the id the server can find in its logs")
            #expect(sent?.isEmpty == false)

            harness.clock.advance(by: 7)
            await device.sync()
            sync = try await device.document().sync
            #expect(sync.failingSince == started, "\(name): the run keeps its start")
            #expect(sync.lastFailedAttemptAt == started.addingTimeInterval(7), "\(name): and its last try moves")
        }
    }

    @Test("021-FR-014 the clock survives a relaunch and a completed cycle clears it")
    func survivesRelaunchAndClearsOnSuccess() async throws {
        let harness = SyncHarness()
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(
            "FailingClock-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = FileDocumentStore(fileURL: directory.appendingPathComponent("store.json"))
        let tokens = InMemorySessionTokenStore()
        let transport = harness.server.makeTransport()
        func launch() -> SyncEngine {
            SyncEngine(
                store: store, tokenStore: tokens, transport: transport, now: harness.clock.provider,
                configuration: SyncConfiguration(scheduler: ManualSyncScheduler(), jitter: { 0.5 }, clientVersion: "test"))
        }

        let first = launch()
        let account = try await first.signIn(
            serverURL: FakeBrainBuddyServer.baseURL, email: SyncHarness.email, password: SyncHarness.password)
        harness.clock.advance(by: 30)
        let started = harness.clock.now()
        transport.inject(.status(503), times: 1_000)
        await first.syncNow()
        #expect(try await store.load()?.sync.failingSince == started)

        // The app quits and starts again over the stored document.
        harness.clock.advance(by: 45)
        let second = launch()
        await second.start(account: account)
        await second.waitUntilIdle()
        let relaunched = try #require(try await store.load()).sync
        #expect(relaunched.failingSince == started, "the 60 s clock did not restart")
        #expect(relaunched.lastFailedAttemptAt == harness.clock.now())

        transport.clearFaults()
        await second.syncNow()
        let cleared = try #require(try await store.load()).sync
        #expect(cleared.failingSince == nil)
        #expect(cleared.lastFailedAttemptAt == nil)
        #expect(cleared.lastFailureReferenceID == nil)
        #expect(cleared.lastPullAt == harness.clock.now())
    }

    @Test("021-FR-014 021-SC-005 retries land at about 2, 6, 14 and 30 s and one at exactly 60 s, at either end of the jitter")
    func retriesLandOnTheSixtySecondMark() async throws {
        let cases: [(jitter: Double, offsets: [TimeInterval])] = [
            (0.5, [2, 6, 14, 30, 60]), (0.0, [1.6, 4.8, 11.2, 24, 49.6, 60]), (1.0, [2.4, 7.2, 16.8, 36, 60]),
        ]
        for (jitter, expected) in cases {
            let harness = SyncHarness()
            let device = await harness.device { $0.jitter = { jitter } }
            try await device.signIn()
            device.transport.inject(.status(503), times: 10_000)
            let started = harness.clock.now()
            await device.sync()

            var offsets: [TimeInterval] = []
            while offsets.count < expected.count {
                let delay = try #require(device.scheduler.pendingDelays.first, "a retry is waiting")
                harness.clock.advance(by: seconds(delay))
                await device.scheduler.runNext()
                await device.engine.waitUntilIdle()
                offsets.append(harness.clock.now().timeIntervalSince(started))
            }
            for (offset, wanted) in zip(offsets, expected) {
                #expect(abs(offset - wanted) < 0.01, "jitter \(jitter): \(offsets)")
            }
            let last = try #require(try await device.document().sync.lastFailedAttemptAt)
            #expect(abs(last.timeIntervalSince(started) - 60) < 0.01, "the attempt on the mark failed too")
        }
    }

    @Test("021-FR-014 021-SC-005 an outage that ends before the 60 s attempt never surfaces; one that outlasts it does")
    func outageAgainstTheSixtySecondMark() async throws {
        for (outageEnds, surfaces) in [(59.0, false), (61.0, true)] {
            let harness = SyncHarness()
            let device = await harness.device()
            try await device.signIn()
            device.transport.inject(.status(503), times: 10_000)
            let started = harness.clock.now()
            await device.sync()

            var surfaced = false
            var offset = 0.0
            while offset < 59.999 {
                let delay = try #require(device.scheduler.pendingDelays.first)
                harness.clock.advance(by: seconds(delay))
                offset = harness.clock.now().timeIntervalSince(started)
                if offset >= outageEnds { device.transport.clearFaults() }
                await device.scheduler.runNext()
                await device.engine.waitUntilIdle()
                let document = try await device.document()
                if lineState(document, at: harness.clock.now()) == .failing { surfaced = true }
            }
            #expect(surfaced == surfaces, "outage ending at \(outageEnds) s")

            // The next success clears it.
            device.transport.clearFaults()
            if let delay = device.scheduler.pendingDelays.first {
                harness.clock.advance(by: seconds(delay))
                await device.scheduler.runNext()
                await device.engine.waitUntilIdle()
            }
            let sync = try await device.document().sync
            #expect(sync.failingSince == nil && sync.lastFailedAttemptAt == nil)
            #expect(await device.status.isIdle)
        }
    }

    @Test("021-FR-014 offline keeps the clock, a failure with the network gone never starts it, and back online it shows at once")
    func offlineKeepsAndNeverStartsTheClock() async throws {
        // Kept: a run that began while online survives the network going away and coming back.
        let harness = SyncHarness()
        let device = await harness.device()
        try await device.signIn()
        device.transport.inject(.status(503), times: 10_000)
        let started = harness.clock.now()
        await device.sync()
        harness.clock.advance(by: 100)
        await device.engine.setNetworkAvailable(false)
        #expect(try await device.document().sync.failingSince == started)
        harness.clock.advance(by: 100)
        await device.engine.setNetworkAvailable(true)
        await device.engine.waitUntilIdle()
        let back = try await device.document()
        #expect(back.sync.failingSince == started)
        #expect(lineState(back, at: harness.clock.now()) == .failing, "the first failed attempt back online surfaces it")

        // Never started: the request failed because the network went away.
        let other = SyncHarness()
        let transport = DroppingNetworkTransport(other.server.makeTransport())
        let store = InMemoryDocumentStore()
        let engine = SyncEngine(
            store: store, tokenStore: InMemorySessionTokenStore(), transport: transport, now: other.clock.provider,
            configuration: SyncConfiguration(scheduler: ManualSyncScheduler(), jitter: { 0.5 }, clientVersion: "test"))
        _ = try await engine.signIn(
            serverURL: FakeBrainBuddyServer.baseURL, email: SyncHarness.email, password: SyncHarness.password)
        transport.arm(for: engine)
        await engine.syncNow()
        let offline = try #require(try await store.load()).sync
        #expect(offline.failingSince == nil && offline.lastFailedAttemptAt == nil)
        #expect(await engine.status == .offline(lastSyncedAt: offline.lastPullAt))
    }

    @Test("021-FR-014 a 401 ends the session at once and starts no clock")
    func unauthorizedNeedsSignIn() async throws {
        let harness = SyncHarness()
        let device = await harness.device()
        try await device.signIn()
        device.transport.inject(.status(401))
        #expect(await device.sync() == .needsSignIn)
        #expect(try await device.document().sync.failingSince == nil)
    }
}
