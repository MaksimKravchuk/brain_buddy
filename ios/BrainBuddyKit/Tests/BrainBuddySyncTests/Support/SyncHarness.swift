import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyFakeServer
import BrainBuddyPersistence
import Foundation
import Synchronization
import Testing

@testable import BrainBuddySync

/// One fake server, one clock, any number of devices.
struct SyncHarness {
    static let email = "ada@example.com"
    static let password = "correct horse battery"

    let clock = ManualClock()
    let server: FakeBrainBuddyServer
    let accountID: String

    init() {
        server = FakeBrainBuddyServer(now: clock.provider)
        accountID = server.addAccount(email: Self.email, password: Self.password, displayName: "Ada")
    }

    func device(_ configure: (inout SyncConfiguration) -> Void = { _ in }) async -> Device {
        await Device(harness: self, configure: configure)
    }

    var snapshot: FakeServerSnapshot { server.snapshot(email: Self.email) }
}

/// A device: its own document store, session, transport (with faults) and
/// engine on manual timers. Commands go in the way the workspace applies
/// them: validated by `GTDReducer` against the current state, then appended
/// through `OutboxCompactor`, in one read-modify-write.
final class Device: Sendable {
    let clock: ManualClock
    let store: InMemoryDocumentStore
    let tokens: InMemorySessionTokenStore
    let transport: FakeServerTransport
    let scheduler: ManualSyncScheduler
    let engine: SyncEngine
    let events = EventLog()

    init(harness: SyncHarness, configure: (inout SyncConfiguration) -> Void) async {
        clock = harness.clock
        store = InMemoryDocumentStore()
        tokens = InMemorySessionTokenStore()
        transport = harness.server.makeTransport()
        scheduler = ManualSyncScheduler()
        var configuration = SyncConfiguration(scheduler: scheduler, jitter: { 0.5 }, clientVersion: "test")
        configure(&configuration)
        engine = SyncEngine(
            store: store, tokenStore: tokens, transport: transport, now: harness.clock.provider,
            configuration: configuration
        )
        let events = events
        await engine.setEventHandler { event in events.append(event) }
    }

    @discardableResult
    func signIn() async throws -> LinkedAccount {
        try await engine.signIn(serverURL: FakeBrainBuddyServer.baseURL, email: SyncHarness.email, password: SyncHarness.password)
    }

    @discardableResult
    func sync() async -> SyncStatus { await engine.syncNow() }

    /// Applies `command` now; throws the reducer's error for an invalid one.
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

    /// What the UI shows: the outbox replayed onto the base.
    func current() async throws -> GTDState {
        let document = try await document()
        return OutboxReplayer.replay(document.outbox, onto: document.base).state
    }

    var status: SyncStatus { get async { await engine.status } }

    /// Mutating requests sent since the log was last cleared.
    var mutations: [HTTPRequest] { transport.requests.filter(FakeServerTransport.isMutation) }
}

/// Everything the engine reported, in order.
final class EventLog: Sendable {
    private let events = Mutex<[SyncEvent]>([])

    func append(_ event: SyncEvent) { events.withLock { $0.append(event) } }

    var all: [SyncEvent] { events.withLock { $0 } }

    var statuses: [SyncStatus] {
        all.compactMap { if case .status(let status) = $0 { status } else { nil } }
    }

    var documents: [StoreDocument] {
        all.compactMap { if case .documentChanged(let document) = $0 { document } else { nil } }
    }

    func clear() { events.withLock { $0.removeAll() } }
}

extension HTTPRequest {
    /// `METHOD /path` after `/api`, for readable expectations.
    var route: String {
        var path = url.path
        if path.hasPrefix("/api") { path.removeFirst(4) }
        return "\(method.rawValue) \(path)"
    }

    var idempotencyKey: String? { header("Idempotency-Key") }

    var bodyText: String { body.map { String(decoding: $0, as: UTF8.self) } ?? "" }
}

extension SyncStatus {
    var isIdle: Bool {
        if case .idle = self { true } else { false }
    }
}

extension GTDState {
    func task(titled title: String) -> TaskRecord? { tasks.values.first { $0.title == title } }
    func project(named name: String) -> ProjectRecord? { projects.values.first { $0.name == name } }
    func tag(named name: String) -> TagRecord? { tags.values.first { $0.name == name } }
}

extension FakeServerSnapshot {
    func task(titled title: String) -> TaskDTO? { tasks.values.first { $0.title == title } }
    func project(named name: String) -> ProjectDTO? { projects.values.first { $0.name == name } }
    func tag(named name: String) -> TagDTO? { tags.values.first { $0.name == name } }
}

/// SplitMix64, so randomized tests replay exactly.
struct SeededGenerator: RandomNumberGenerator {
    private var state: UInt64
    init(seed: UInt64) { state = seed }

    mutating func next() -> UInt64 {
        state &+= 0x9E37_79B9_7F4A_7C15
        var value = state
        value = (value ^ (value >> 30)) &* 0xBF58_476D_1CE4_E5B9
        value = (value ^ (value >> 27)) &* 0x94D0_49BB_1331_11EB
        return value ^ (value >> 31)
    }
}
