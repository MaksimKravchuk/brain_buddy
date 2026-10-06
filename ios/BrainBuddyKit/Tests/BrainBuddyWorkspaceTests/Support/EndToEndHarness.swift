import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyFakeServer
import BrainBuddyPersistence
import BrainBuddySync
import Foundation
import Testing

@testable import BrainBuddyWorkspace

/// One fake Brain Buddy server with one account, and one clock that the
/// server, every sync engine and every workspace read. Nothing sleeps: time
/// moves when a test moves it, and sync timers run when a test runs them.
@MainActor
final class World {
    static let email = "ada@example.com"
    static let password = "correct horse battery"

    let clock = ManualClock()
    let server: FakeBrainBuddyServer
    private var devices = 0

    init() {
        server = FakeBrainBuddyServer(now: clock.provider)
        server.addAccount(email: Self.email, password: Self.password, displayName: "Ada")
    }

    /// What the server holds for the account.
    var snapshot: FakeServerSnapshot { server.snapshot(email: Self.email) }

    /// A device running the app, launched (its store loaded). By default it
    /// has a fresh in-memory store and has never signed in.
    func device(store: (any DocumentStore)? = nil) async -> AppDevice {
        devices += 1
        let device = AppDevice(world: self, store: store ?? InMemoryDocumentStore(), namespace: devices)
        await device.launch()
        return device
    }

    /// A widget or App Intent on the same store as an app: its own process,
    /// so its own ids, and no sync (only the app talks to the server).
    func extensionWorkspace(store: any DocumentStore) async -> Workspace {
        devices += 1
        let ids = IDSequence(namespace: devices)
        let workspace = Workspace(store: store, sync: nil, now: clock.provider, makeID: { ids.next() })
        await workspace.load()
        return workspace
    }
}

/// The app on one device, wired as `Workspace.live` wires it: a real
/// `SyncEngine` over the same store the `Workspace` writes, a session store,
/// and this device's connection to the shared server (which can fail on
/// demand). Timers run on a `ManualSyncScheduler`.
@MainActor
final class AppDevice {
    let world: World
    let store: any DocumentStore
    let tokens: InMemorySessionTokenStore
    let transport: FakeServerTransport
    let ids: IDSequence
    private(set) var scheduler: ManualSyncScheduler
    private(set) var engine: SyncEngine
    private(set) var workspace: Workspace

    init(world: World, store: any DocumentStore, namespace: Int) {
        let tokens = InMemorySessionTokenStore()
        let transport = world.server.makeTransport()
        let ids = IDSequence(namespace: namespace)
        self.world = world
        self.store = store
        self.tokens = tokens
        self.transport = transport
        self.ids = ids
        (scheduler, engine, workspace) = AppDevice.makeApp(
            store: store, tokens: tokens, transport: transport, clock: world.clock, ids: ids
        )
    }

    private static func makeApp(
        store: any DocumentStore, tokens: InMemorySessionTokenStore, transport: FakeServerTransport,
        clock: ManualClock, ids: IDSequence
    ) -> (ManualSyncScheduler, SyncEngine, Workspace) {
        let scheduler = ManualSyncScheduler()
        let engine = SyncEngine(
            store: store, tokenStore: tokens, transport: transport, now: clock.provider,
            configuration: SyncConfiguration(scheduler: scheduler, jitter: { 0.5 }, clientVersion: "test")
        )
        let workspace = Workspace(store: store, sync: engine, now: clock.provider, makeID: { ids.next() })
        return (scheduler, engine, workspace)
    }

    /// Loads the store, as the app does at launch (which starts sync for a
    /// linked account), and waits for that first sync.
    func launch() async {
        await workspace.load()
        await settle()
    }

    /// Quits the app and opens it again: a new engine and workspace over the
    /// same store and session. The ids keep counting (same device).
    func relaunch() async {
        await settle()
        (scheduler, engine, workspace) = AppDevice.makeApp(
            store: store, tokens: tokens, transport: transport, clock: world.clock, ids: ids
        )
        await launch()
    }

    /// Signs in from Settings with the account's credentials.
    func signIn() async throws {
        try await workspace.signIn(serverURL: FakeBrainBuddyServer.baseURL, email: World.email, password: World.password)
        await settle()
    }

    /// What `NWPathMonitor` reports, delivered and acted on.
    func networkChanged(isAvailable: Bool) async {
        workspace.networkAvailabilityChanged(isAvailable: isAvailable)
        await settle()
    }

    /// Runs the oldest waiting sync timer (the debounce after a local change,
    /// or a retry) and waits for the cycle it starts.
    func fireNextTimer() async {
        await scheduler.runNext()
        await settle()
    }

    /// Waits until connectivity updates reached the engine, no cycle runs,
    /// and every change the workspace applied is in the store.
    func settle() async {
        await workspace.waitForNetworkUpdates()
        await engine.waitUntilIdle()
        await workspace.flush()
    }

    /// Requests that got an error answer (none when the server accepted
    /// everything). A gated review read answered `404 weekly_review_disabled`
    /// is the flag being off (spec 020, http "Gate"), not a rejection.
    var rejectedRequests: [String] {
        transport.exchanges.compactMap { exchange in
            guard let status = exchange.statusCode, status >= 400 else { return nil }
            if status == 404, let body = exchange.response?.body,
                String(decoding: body, as: UTF8.self).contains("\"weekly_review_disabled\"")
            {
                return nil
            }
            return "\(exchange.request.method.rawValue) \(exchange.request.url.path) → \(status)"
        }
    }

    /// Expects the device to show exactly what the server holds, record for
    /// record (every record acknowledged, at the server's latest revision).
    func expectInSyncWithServer(children: Bool = true, sourceLocation: SourceLocation = #_sourceLocation) throws {
        let onDevice = try AccountData(device: workspace.state, children: children)
        let onServer = AccountData(server: world.snapshot, children: children).restrictingInactive(to: onDevice)
        #expect(onDevice == onServer, sourceLocation: sourceLocation)
    }
}

extension SyncStatus {
    var isIdle: Bool {
        if case .idle = self { true } else { false }
    }
}
