import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyFakeServer
import BrainBuddyPersistence
import BrainBuddySync
import Foundation
import Synchronization
import Testing

@testable import BrainBuddyWorkspace

/// The production selection with the real sync host plugged in (`RustSyncTransportProvider`),
/// over real Rust stores and a stubbed sync-v1 server (026-FR-003, 026-FR-005, 026-FR-025): the
/// host exists only for a selected, signed-in workspace, starts after sign-in, stops before the
/// account's copy is removed, and never starts while the pilot switch is off.
@Suite("Rust sync host under the production selection (026-FR-003, 026-FR-005, 026-FR-025)")
struct RustSyncProviderLifecycleTests {
    @Test("026-FR-025: with the pilot switch off no host is built and nothing reaches the server")
    @MainActor
    func pilotOffNeverStartsAHost() async throws {
        let rig = try Rig()
        defer { rig.cleanup() }
        let provider = rig.counting()
        switch await rig.launcher(pilot: false, provider: provider).resolve() {
        case .legacy(.pilotOff): break
        default: Issue.record("the install must stay legacy")
        }
        #expect(provider.built == 0)
        #expect(rig.stub.requests.isEmpty)
    }

    @Test("026-FR-003: an account-less selection gets a port that sends nothing")
    @MainActor
    func accountlessSendsNothing() async throws {
        let rig = try Rig()
        defer { rig.cleanup() }
        let provider = rig.counting()
        let app = try await rig.app(provider: provider)
        #expect(provider.built == 1)
        await app.syncNow()
        await app.requestForegroundPull()
        #expect(rig.stub.requests.isEmpty)
        #expect(app.runtimeTransportUnavailable)
        await app.closeRuntime()
    }

    @Test("026-FR-005: sign-in starts the host, the edit is sent, and sign-out stops it before the copy is removed")
    @MainActor
    func signInStartsAndSignOutStops() async throws {
        let rig = try Rig()
        defer { rig.cleanup() }
        let app = try await rig.app(provider: rig.counting())
        try await app.signIn(serverURL: rig.serverURL, email: "a@example.com", password: "secret")
        #expect(app.account == rig.account)

        // The host runs on the linked store, as this device, with the stored session.
        #expect(rig.stub.wait(timeout: 20) { requests, _ in
            requests.contains { $0.url.path == "/api/sync/v1/capabilities" }
        })
        await app.syncNow()
        #expect(rig.stub.requests.contains { $0.url.path == "/api/sync/v1/snapshots" })
        #expect(rig.stub.requests.allSatisfy { $0.header("Cookie") == "brainbuddy_session=tok-1" })
        let port = try #require(app.rustSelection?.transport as? RustSyncHostPort)
        #expect(await port.isRunning)

        _ = try await app.capture(CaptureDraft(text: "Sent after sign-in"), editorID: "scene:provider:capture")
        #expect(rig.stub.wait(timeout: 20) { requests, _ in
            requests.contains { $0.method == "POST" && $0.url.path == "/api/sync/v1/commands" }
        })
        await app.syncNow()
        await app.refreshRustStatus()
        #expect(app.pendingChangeCount == 0)

        // Sign-out: the host is gone before anything is removed, and the new identity syncs nothing.
        let old = try #require(try rig.selections.load()).workspaceID
        try await app.signOut(removing: [])
        #expect(!(await port.isRunning))
        #expect(!FileManager.default.fileExists(atPath: rig.location.identityDirectory(old).path))
        let sent = rig.stub.requests.count
        await app.syncNow()
        await app.requestForegroundPull()
        #expect(rig.stub.requests.count == sent)
        #expect(app.account == nil)
        await app.closeRuntime()
    }

    @Test("026-FR-005: a quiesced port starts a new host on its next request, and a closed one never does")
    @MainActor
    func quiesceRestartsAndCloseIsFinal() async throws {
        let rig = try Rig()
        defer { rig.cleanup() }
        let app = try await rig.app(provider: rig.counting())
        try await app.signIn(serverURL: rig.serverURL, email: "a@example.com", password: "secret")
        await app.syncNow()
        let port = try #require(app.rustSelection?.transport as? RustSyncHostPort)
        #expect(await port.isRunning)

        await port.quiesce()
        #expect(!(await port.isRunning))
        let before = rig.stub.requests.filter { $0.url.path == "/api/sync/v1/capabilities" }.count
        await app.syncNow()
        #expect(await port.isRunning)
        #expect(rig.stub.requests.filter { $0.url.path == "/api/sync/v1/capabilities" }.count > before)

        await port.close()
        #expect(await port.request(.manual) == .transportUnavailable)
        #expect(!(await port.isRunning))
        await app.closeRuntime()
    }

    @Test("026-FR-017: a server newer than this build reads as update needed through the provider's port")
    @MainActor
    func newerServer() async throws {
        let rig = try Rig(protocolVersions: [99])
        defer { rig.cleanup() }
        let app = try await rig.app(provider: rig.counting())
        try await app.signIn(serverURL: rig.serverURL, email: "a@example.com", password: "secret")
        await app.syncNow()
        #expect(app.runtimeSyncNeedsUpdate)
        await app.closeRuntime()
    }
}

private final class CountingProvider: RustTransportProvider {
    private let inner: RustSyncTransportProvider
    private let count = Mutex(0)

    init(_ inner: RustSyncTransportProvider) { self.inner = inner }

    var built: Int { count.withLock { $0 } }

    func transport(for context: RustTransportContext) -> any SyncRuntimePort {
        count.withLock { $0 += 1 }
        return inner.transport(for: context)
    }
}

private struct Rig: Sendable {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent("provider-\(UUID().uuidString)")
    let bridge: RustBridgeRuntime
    let stub = StubServer()
    let account: LinkedAccount
    let server: StubAccountServer
    let tokens: InMemorySessionTokenStore
    private let suite = "provider-\(UUID().uuidString)"

    var serverURL: URL { stub.secureServerURL }
    var location: RustRuntimeLocation { .directory(root) }
    var selections: RustRuntimeSelectionStore { RustRuntimeSelectionStore(location: location) }

    init(protocolVersions: [Int] = [1]) throws {
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        bridge = try RustBridgeRuntime()
        account = LinkedAccount(id: "owner-a", email: "a@example.com", serverURL: stub.secureServerURL,
            linkedAt: Date(timeIntervalSince1970: 1_789_000_000))
        server = StubAccountServer(account: account)
        tokens = InMemorySessionTokenStore(tokens: [stub.secureServerURL: "tok-1"])
        let model = SyncModel(protocolVersions: protocolVersions, scope: account.id)
        stub.respond { model.answer($0) }
    }

    func cleanup() {
        UserDefaults(suiteName: suite)?.removePersistentDomain(forName: suite)
        try? FileManager.default.removeItem(at: root)
    }

    fileprivate func counting() -> CountingProvider {
        let stub = stub
        return CountingProvider(RustSyncTransportProvider(
            tokenStore: tokens, urlSessionConfiguration: { stub.sessionConfiguration }))
    }

    fileprivate func launcher(pilot: Bool, provider: CountingProvider) -> RustRuntimeLauncher {
        let switchBox = RustRuntimePilotSwitch(suiteName: suite)
        switchBox.set(pilot)
        let instant = Date(timeIntervalSince1970: 1_790_000_000)
        let environment = RustRuntimeEnvironment(
            location: location, legacyStoreURL: root.appendingPathComponent("store.json"), bridge: bridge,
            transports: provider, server: server, now: { instant })
        return RustRuntimeLauncher(environment: environment, pilot: switchBox)
    }

    /// The app of a fresh install with the pilot on: account-less, loaded.
    @MainActor
    fileprivate func app(provider: CountingProvider) async throws -> Workspace {
        guard case .rust(let selection, let lifecycle) = await launcher(pilot: true, provider: provider).resolve() else {
            throw SelectionLaneError.notSelected
        }
        let workspace = Workspace.selected(selection, lifecycle: lifecycle)
        await workspace.load()
        return workspace
    }
}
