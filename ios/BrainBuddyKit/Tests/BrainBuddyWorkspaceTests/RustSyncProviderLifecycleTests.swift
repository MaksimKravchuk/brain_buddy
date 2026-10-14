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
        #expect(await rig.server.logins == 0)
        #expect(!FileManager.default.fileExists(atPath: rig.location.root.path), "no store was opened, so nothing could merge")
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
        // The transport wake runs behind the save's return (on the main actor): let it run before this
        // thread blocks on the stub.
        await app.settleRustWork()
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

    @Test("026-FR-003 026-FR-005: work written before the account survives the first sign-in and is sent exactly once")
    @MainActor
    func localWorkIsMergedAndSentOnce() async throws {
        let rig = try Rig()
        defer { rig.cleanup() }
        let app = try await rig.app(provider: rig.counting())
        _ = try await app.capture(CaptureDraft(text: "Written before the account"), editorID: "scene:merge:a")
        _ = try await app.capture(CaptureDraft(text: "Also before"), editorID: "scene:merge:b")
        #expect(app.hasLocalWorkToMerge)
        #expect(rig.stub.requests.isEmpty, "account-less: nothing is sent")

        try await app.signIn(serverURL: rig.serverURL, email: "a@example.com", password: "secret")
        #expect(app.account == rig.account)
        await app.settleRustWork()
        #expect(rig.stub.wait(timeout: 30) { requests, _ in
            requests.filter { $0.method == "POST" && $0.url.path == "/api/sync/v1/commands" }.count >= 2
        })
        await app.settleRustWork()
        await app.syncNow()
        await app.refreshRustStatus()
        #expect(app.pendingChangeCount == 0)
        let sent = rig.model.commandIDs
        #expect(sent.count == 2 && Set(sent).count == 2, "one command per record, each sent once: \(sent)")
        let shown = await eventually(app) { $0 == ["Written before the account", "Also before"] }
        #expect(shown == ["Written before the account", "Also before"])

        // More rounds (foreground, manual, a restart of the host) send nothing again.
        await app.requestForegroundPull()
        await app.syncNow()
        let port = try #require(app.rustSelection?.transport as? RustSyncHostPort)
        await port.quiesce()
        await app.syncNow()
        #expect(rig.model.commandIDs == sent)
        await app.closeRuntime()
    }

    @Test("026-FR-003: a sign-in that crashed after saving the selection is finished at the next launch, once")
    @MainActor
    func crashBeforeTheMergeIsFinishedOnRelaunch() async throws {
        let rig = try Rig()
        defer { rig.cleanup() }
        let first = try await rig.app(provider: rig.counting())
        _ = try await first.capture(CaptureDraft(text: "Survives the crash"), editorID: "scene:crash:a")
        await first.closeRuntime()
        // The state a crash leaves: the selection names the account, the merge never committed.
        var record = try #require(try rig.selections.load())
        #expect(record.account == nil)
        record.account = rig.account
        try rig.selections.save(record)

        for launch in 1...2 {
            let relaunched = try await rig.app(provider: rig.counting())
            #expect(relaunched.account == rig.account, "launch \(launch)")
            await relaunched.syncNow()
            await relaunched.settleRustWork()
            #expect(rig.stub.wait(timeout: 30) { requests, _ in
                requests.contains { $0.method == "POST" && $0.url.path == "/api/sync/v1/commands" }
            })
            await relaunched.syncNow()
            await relaunched.refreshRustStatus()
            #expect(relaunched.pendingChangeCount == 0)
            #expect(rig.model.commandIDs.count == 1, "launch \(launch): \(rig.model.commandIDs)")
            await relaunched.closeRuntime()
        }
    }

    @Test("026-FR-003: another account's workspace is never taken over by the merge")
    @MainActor
    func otherAccountKeepsItsWorkspace() async throws {
        let rig = try Rig()
        defer { rig.cleanup() }
        let app = try await rig.app(provider: rig.counting())
        try await app.signIn(serverURL: rig.serverURL, email: "a@example.com", password: "secret")
        let selection = try #require(app.rustSelection)
        let device = try #require(try rig.selections.load()).deviceID
        let other = try await selection.runtime.linkAndMerge(
            accountID: "owner-b", scopeID: "owner-b", deviceID: device,
            context: RustWorkspaceContext(now: Date(), timeZone: "UTC", actorID: "device",
                policy: Data(#"{"weekly_review":false,"navigator_provider":null,"navigator_available":false,"consent_text_version":1}"#.utf8)))
        #expect(other == .otherAccount)
        await app.closeRuntime()
    }

    @Test("026-FR-005: a status reached between requests (a background round) reaches the Workspace")
    @MainActor
    func backgroundRoundsUpdateTheStatus() async throws {
        let rig = try Rig()
        defer { rig.cleanup() }
        let stub = rig.stub
        let provider = CountingProvider(RustSyncTransportProvider(
            tokenStore: rig.tokens, urlSessionConfiguration: { stub.sessionConfiguration }, pollInterval: 0.2))
        let app = try await rig.app(provider: provider)
        try await app.signIn(serverURL: rig.serverURL, email: "a@example.com", password: "secret")
        await app.syncNow()
        guard case .idle = app.syncStatus else {
            Issue.record("synced first: \(app.syncStatus)")
            return
        }
        // The server goes away; the worker's own poll finds out, no request came from the Workspace.
        rig.go(offline: true)
        var seen = app.syncStatus
        for _ in 0..<200 {
            if case .offline = seen { break }
            try? await Task.sleep(for: .milliseconds(50))
            seen = app.syncStatus
        }
        guard case .offline = seen else {
            Issue.record("expected offline, saw \(seen)")
            return
        }
        rig.go(offline: false)
        for _ in 0..<200 {
            if case .idle = seen { break }
            try? await Task.sleep(for: .milliseconds(50))
            seen = app.syncStatus
        }
        guard case .idle = seen else {
            Issue.record("expected idle again, saw \(seen)")
            return
        }
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
    let model: SyncModel
    private let down = Flag()
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
        self.model = model
        let down = down
        stub.respond { request in down.value ? .fail(.notConnectedToInternet) : model.answer(request) }
    }

    func go(offline: Bool) { down.set(offline) }

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

/// The Inbox titles once `done` holds (the last seen ones if it never does within 10 s).
@MainActor
private func eventually(_ workspace: Workspace, _ done: (Set<String>) -> Bool) async -> Set<String> {
    var titles = Set<String>()
    for _ in 0..<200 {
        await workspace.prepareList(.list(.inbox))
        titles = Set(workspace.list(.list(.inbox)).sections.flatMap(\.tasks).map(\.title))
        if done(titles) { break }
        try? await Task.sleep(for: .milliseconds(50))
    }
    return titles
}

private final class Flag: Sendable {
    private let state = Mutex(false)
    var value: Bool { state.withLock { $0 } }
    func set(_ value: Bool) { state.withLock { $0 = value } }
}
