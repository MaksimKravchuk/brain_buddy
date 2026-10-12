import BrainBuddyCore
import BrainBuddyPersistence
import BrainBuddySync
import Foundation
import Testing

@testable import BrainBuddyWorkspace

/// Account changes on a Rust-selected Workspace, against real runtime stores: the previous
/// owner's late responses are fenced, a widget or App Intent writes through the same database
/// lock into the scope it was opened for, and the first-sign-in merge and the sign-out warning
/// keep their meaning (spec 026, T044).
@Suite("Rust account lifecycle at the real boundary (026-FR-003, 026-FR-011, 026-FR-013, 026-FR-025)")
struct RustAccountLifecycleTests {
    @Test("026-FR-013: a late response of the previous owner is dropped after sign-out")
    @MainActor
    func lateOwnerResponseAfterSignOut() async throws {
        let h = Harness()
        defer { h.cleanup() }
        let old = GatedTransport()
        let lifecycle = try await h.lifecycle()
        let workspace = try await h.workspace(scope: "a", account: h.accountA, transport: old, lifecycle: lifecycle)
        #expect(workspace.account == h.accountA)
        await old.hold()
        let pull = Task { await workspace.requestForegroundPull() }
        await old.waitForRequests(2)

        try await workspace.signOut(removing: [])
        #expect(workspace.account == nil)
        #expect(workspace.isRustBound)
        await old.release(.status(.idle(lastSyncedAt: h.instant)))
        await pull.value

        #expect(workspace.syncStatus == .localOnly)
        #expect(workspace.runtimeTransportUnavailable)
        #expect(await old.isClosed)
        await workspace.closeRuntime()
    }

    @Test("026-FR-013: a late response of the account-less binding is dropped after sign-in links the account")
    @MainActor
    func lateResponseAfterSignIn() async throws {
        let h = Harness()
        defer { h.cleanup() }
        let old = GatedTransport()
        let recorder = Recorder()
        let lifecycle = try await h.lifecycle(recorder: recorder)
        let workspace = try await h.workspace(scope: "local", account: nil, transport: old, lifecycle: lifecycle)
        let id = try await workspace.capture(CaptureDraft(text: "Written before the account"), editorID: "scene:life:pre")
        await old.hold()
        let pull = Task { await workspace.requestForegroundPull() }
        await old.waitForRequests(3)

        try await workspace.signIn(serverURL: h.serverURL, email: "a@example.com", password: "secret")
        #expect(workspace.account == h.accountA)
        await old.release(.status(.needsSignIn))
        await pull.value

        #expect(workspace.syncStatus != .needsSignIn)
        // The explicit first-sign-in merge: the local work is the account's now, not dropped.
        #expect(await recorder.signIns == [true])
        await workspace.prepareList(.list(.inbox))
        #expect(workspace.task(id)?.title == "Written before the account")
        await workspace.closeRuntime()
    }

    @Test("026-FR-003: an owner other than the linked one is refused and nothing moves")
    @MainActor
    func otherOwnerRefused() async throws {
        let h = Harness()
        defer { h.cleanup() }
        let recorder = Recorder()
        let lifecycle = try await h.lifecycle(recorder: recorder, signInAccount: h.accountB)
        let workspace = try await h.workspace(scope: "a", account: h.accountA, lifecycle: lifecycle)
        let id = try await workspace.capture(CaptureDraft(text: "Stays with the first owner"), editorID: "scene:life:own")

        await #expect(throws: WorkspaceError.self) {
            try await workspace.signIn(serverURL: h.serverURL, email: "b@example.com", password: "secret")
        }
        #expect(workspace.account == h.accountA)
        #expect(workspace.isRustBound)
        #expect(await recorder.signIns == [false])
        await workspace.prepareList(.list(.inbox))
        #expect(workspace.task(id)?.title == "Stays with the first owner")
        await workspace.closeRuntime()
    }

    @Test("026-FR-011: a cancelled sign-in links nothing")
    @MainActor
    func cancelledSignIn() async throws {
        let h = Harness()
        defer { h.cleanup() }
        let lifecycle = try await h.lifecycle(cancelling: true)
        let workspace = try await h.workspace(scope: "local", account: nil, lifecycle: lifecycle)
        await #expect(throws: WorkspaceError.signInFailed(message: "This sign-in was cancelled.", referenceID: nil)) {
            try await workspace.signIn(serverURL: h.serverURL, email: "a@example.com", password: "secret")
        }
        #expect(workspace.account == nil)
        #expect(workspace.isRustBound)
        await workspace.closeRuntime()
    }

    @Test("026-FR-011: the sign-out warning names the unsent work and removes no more than it named")
    @MainActor
    func signOutWarning() async throws {
        let h = Harness()
        defer { h.cleanup() }
        let recorder = Recorder()
        let lifecycle = try await h.lifecycle(recorder: recorder)
        let workspace = try await h.workspace(scope: "a", account: h.accountA, lifecycle: lifecycle)
        _ = try await workspace.capture(CaptureDraft(text: "Not yet synced"), editorID: "scene:life:warn")
        let named = workspace.pendingChanges
        #expect(named.count == 1)

        do {
            try await workspace.signOut(discardUnsyncedChanges: false)
            Issue.record("a plain sign-out must warn about unsent work")
        } catch let error as WorkspaceError {
            #expect(error == .unsyncedChanges(count: 1))
        }
        #expect(await recorder.signOuts.isEmpty)
        #expect(workspace.account == h.accountA)

        try await workspace.signOut(removing: named)
        #expect(await recorder.signOuts == [1])
        #expect(workspace.account == nil)
        await workspace.prepareList(.list(.inbox))
        #expect(workspace.list(.list(.inbox)).sections.flatMap(\.tasks).isEmpty)
        await workspace.closeRuntime()
    }

    @Test("026-FR-011: account changes are one at a time and a sign-out accepts no new change")
    @MainActor
    func oneAccountChangeAtATime() async throws {
        let h = Harness()
        defer { h.cleanup() }
        let gate = Gate()
        let lifecycle = try await h.lifecycle(signOutGate: gate)
        let workspace = try await h.workspace(scope: "a", account: h.accountA, lifecycle: lifecycle)
        let signOut = Task { try await workspace.signOut(removing: []) }
        await gate.waitUntilReached()

        #expect(workspace.isSigningOut)
        await #expect(throws: GTDValidationError.signingOut) {
            _ = try await workspace.capture(CaptureDraft(text: "Would be removed unseen"), editorID: "scene:life:late")
        }
        await #expect(throws: WorkspaceError.signInFailed(message: Workspace.signingOutMessage, referenceID: nil)) {
            try await workspace.signIn(serverURL: h.serverURL, email: "a@example.com", password: "secret")
        }
        await gate.open()
        try await signOut.value
        #expect(workspace.account == nil)
        await workspace.closeRuntime()
    }

    @Test("026-FR-003: a widget write during a sign-out goes through the same lock and is never removed unseen")
    @MainActor
    func extensionWriteDuringSignOut() async throws {
        let h = Harness()
        defer { h.cleanup() }
        let gate = Gate()
        let appTransport = CountingTransport()
        let lifecycle = try await h.lifecycle(signOutGate: gate)
        let app = try await h.workspace(scope: "a", account: h.accountA, transport: appTransport, lifecycle: lifecycle)
        let widgetSelection = try await h.selection(scope: "a", account: h.accountA)
        let widget = Workspace.extensionWorkspace(over: widgetSelection)
        await widget.load()

        let signOut = Task { try await app.signOut(removing: []) }
        await gate.waitUntilReached()
        let id = try await widget.capture(CaptureDraft(text: "From the widget"), editorID: "scene:widget:1")
        await gate.open()
        do {
            try await signOut.value
            Issue.record("the widget's change was queued after the count was checked; it must not be removed")
        } catch let error as WorkspaceError {
            #expect(error == .unsyncedChanges(count: 1))
        }

        // Nothing was removed and the app is still the linked account's, now seeing the change.
        #expect(app.account == h.accountA)
        #expect(app.isRustBound)
        await app.reloadIfChangedExternally()
        await app.prepareList(.list(.inbox))
        #expect(app.task(id)?.title == "From the widget")
        // The widget never owned sync: only the app's transport was ever asked.
        await widget.requestForegroundPull()
        #expect(widget.runtimeTransportUnavailable)
        #expect(await appTransport.requests > 0)

        // The next sign-out names it and removes it; the next identity starts empty, and a widget
        // opened for it writes into that scope only.
        try await app.signOut(removing: app.pendingChanges)
        #expect(app.account == nil)
        await app.prepareList(.list(.inbox))
        #expect(app.list(.list(.inbox)).sections.flatMap(\.tasks).isEmpty)
        let nextWidget = Workspace.extensionWorkspace(over: try #require(app.rustSelection))
        await nextWidget.load()
        _ = try await nextWidget.capture(CaptureDraft(text: "Next identity"), editorID: "scene:widget:2")
        await app.reloadIfChangedExternally()
        await app.prepareList(.list(.inbox))
        #expect(app.list(.list(.inbox)).sections.flatMap(\.tasks).map(\.title) == ["Next identity"])
        await widget.closeRuntime()
        await nextWidget.closeRuntime()
        await app.closeRuntime()
    }

    @Test("026-FR-003: concurrent widget and app writes both land in the one scope")
    @MainActor
    func concurrentWrites() async throws {
        let h = Harness()
        defer { h.cleanup() }
        let app = try await h.workspace(scope: "a", account: h.accountA, lifecycle: nil)
        let widget = Workspace.extensionWorkspace(over: try await h.selection(scope: "a", account: h.accountA))
        await widget.load()
        async let fromApp = app.capture(CaptureDraft(text: "From the app"), editorID: "scene:app:1")
        async let fromWidget = widget.capture(CaptureDraft(text: "From the widget"), editorID: "scene:widget:1")
        _ = try await (fromApp, fromWidget)

        await app.reloadIfChangedExternally()
        await app.prepareList(.list(.inbox))
        #expect(Set(app.list(.list(.inbox)).sections.flatMap(\.tasks).map(\.title)) == ["From the app", "From the widget"])
        #expect(app.pendingChanges.count == 2)
        await widget.closeRuntime()
        await app.closeRuntime()
    }

    @Test("026-FR-025: without a lifecycle the account change keeps its refusal and the work")
    @MainActor
    func withoutLifecycle() async throws {
        let h = Harness()
        defer { h.cleanup() }
        let workspace = try await h.workspace(scope: "a", account: h.accountA, lifecycle: nil)
        await #expect(throws: WorkspaceError.self) { try await workspace.signOut(removing: []) }
        await #expect(throws: WorkspaceError.self) {
            try await workspace.signIn(serverURL: h.serverURL, email: "a@example.com", password: "secret")
        }
        #expect(workspace.account == h.accountA)
        #expect(workspace.isRustBound)
        await workspace.closeRuntime()
    }

    @Test("026-FR-025: paths follow the workspace identity and cannot leave their folder")
    func identityPaths() {
        let a = Workspace.rustDatabaseURL(appGroupID: "group.test", workspaceID: "owner-a")
        let b = Workspace.rustDatabaseURL(appGroupID: "group.test", workspaceID: "owner-b")
        let hostile = Workspace.rustDatabaseURL(appGroupID: "group.test", workspaceID: "../../etc")
        #expect(a != b)
        #expect(a == Workspace.rustDatabaseURL(appGroupID: "group.test", workspaceID: "owner-a"))
        #expect(a.deletingLastPathComponent().deletingLastPathComponent()
            == hostile.deletingLastPathComponent().deletingLastPathComponent())
        #expect(!hostile.path.contains(".."))
    }
}

// MARK: - Support

struct Harness: Sendable {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let bridge: RustBridgeRuntime
    let instant = Date(timeIntervalSince1970: 1_790_000_000)
    let serverURL = URL(string: "https://example.com/api")!
    let accountA: LinkedAccount
    let accountB: LinkedAccount

    init() {
        // The bridge only fails when the library is missing, which the package refuses to build without.
        bridge = try! RustBridgeRuntime()  // swiftlint:disable:this force_try
        let url = URL(string: "https://example.com/api")!
        accountA = LinkedAccount(id: "owner-a", email: "a@example.com", serverURL: url,
            linkedAt: Date(timeIntervalSince1970: 1_789_000_000))
        accountB = LinkedAccount(id: "owner-b", email: "b@example.com", serverURL: url,
            linkedAt: Date(timeIntervalSince1970: 1_789_000_000))
    }

    func cleanup() { try? FileManager.default.removeItem(at: root) }

    func selection(scope: String, account: LinkedAccount?, transport: any SyncRuntimePort = PendingRustSyncRuntimePort(),
                   startup: RustWorkspaceSelection.Startup = .prepared) async throws -> RustWorkspaceSelection {
        let runtime = try await bridge.openStore(workspaceID: scope,
            databaseURL: root.appendingPathComponent(scope).appendingPathComponent("store.sqlite3"))
        return RustWorkspaceSelection(runtime: runtime,
            facade: RustDomainFacade(runtime: bridge, context: RustDomainContext(deviceTimeZone: "UTC")),
            transport: transport, account: account, startup: startup)
    }

    @MainActor
    func workspace(scope: String, account: LinkedAccount?, transport: any SyncRuntimePort = PendingRustSyncRuntimePort(),
                   lifecycle: (any RustAccountLifecyclePort)?) async throws -> Workspace {
        let selection = try await selection(scope: scope, account: account, transport: transport)
        let instant = instant
        let workspace = Workspace(store: ControlledStore(), sync: nil, rust: selection, rustLifecycle: lifecycle,
            now: { instant })
        await workspace.load()
        #expect(workspace.isRustBound)
        return workspace
    }

    /// A host's lifecycle over real stores: sign-in links the same workspace in place (the merge),
    /// sign-out checks the confirmation against the store's own count after `signOutGate`, then
    /// returns an empty account-less identity.
    func lifecycle(recorder: Recorder = Recorder(), signInAccount: LinkedAccount? = nil, cancelling: Bool = false,
                   signOutGate: Gate? = nil) async throws -> any RustAccountLifecyclePort {
        ScriptedLifecycle(harness: self, recorder: recorder, signInAccount: signInAccount ?? accountA,
                          cancelling: cancelling, signOutGate: signOutGate)
    }
}

struct ScriptedLifecycle: RustAccountLifecyclePort {
    let harness: Harness
    let recorder: Recorder
    let signInAccount: LinkedAccount
    let cancelling: Bool
    let signOutGate: Gate?

    func signIn(_ request: RustSignInRequest) async throws -> RustSignInOutcome {
        await recorder.recordSignIn(merging: request.mergesLocalWork)
        if cancelling { request.cancellation.cancel() }
        let current = request.current
        if signInAccount.id != current.account?.id, current.account != nil {
            // A different owner gets its own workspace; the old one's work is never moved into it.
            let other = try await harness.selection(scope: signInAccount.id, account: signInAccount)
            return RustSignInOutcome(selection: other)
        }
        return RustSignInOutcome(selection: RustWorkspaceSelection(runtime: current.runtime, facade: current.facade,
            transport: PendingRustSyncRuntimePort(), account: signInAccount, startup: .prepared))
    }

    func signOut(_ request: RustSignOutRequest) async throws -> RustWorkspaceSelection {
        await signOutGate?.reach()
        // Under the store's own lock in a real host: whatever a widget queued meanwhile counts.
        let pending = Int(try await request.current.runtime.snapshot().pending) ?? 0
        guard pending <= request.confirmed.unsent else { throw WorkspaceError.unsyncedChanges(count: pending) }
        await recorder.recordSignOut(removing: pending)
        return try await harness.selection(scope: "local-\(UUID().uuidString)", account: nil)
    }
}

actor Recorder {
    private(set) var signIns: [Bool] = []
    private(set) var signOuts: [Int] = []
    func recordSignIn(merging: Bool) { signIns.append(merging) }
    func recordSignOut(removing count: Int) { signOuts.append(count) }
}

/// Holds a caller at a point until the test opens it.
actor Gate {
    private var isOpen = false
    private var reached = false
    private var waiters: [CheckedContinuation<Void, Never>] = []
    private var watchers: [CheckedContinuation<Void, Never>] = []

    func reach() async {
        reached = true
        for watcher in watchers { watcher.resume() }
        watchers = []
        if isOpen { return }
        await withCheckedContinuation { waiters.append($0) }
    }

    func waitUntilReached() async {
        if reached { return }
        await withCheckedContinuation { watchers.append($0) }
    }

    func open() {
        isOpen = true
        for waiter in waiters { waiter.resume() }
        waiters = []
    }
}

/// A transport whose answers wait until the test releases them, to make a response late.
actor GatedTransport: SyncRuntimePort {
    private var holding = false
    private var count = 0
    private var held: [CheckedContinuation<SyncRuntimeWakeResult, Never>] = []
    private var watchers: [(Int, CheckedContinuation<Void, Never>)] = []
    private(set) var isClosed = false

    func hold() { holding = true }

    func release(_ result: SyncRuntimeWakeResult) {
        holding = false
        for continuation in held { continuation.resume(returning: result) }
        held = []
    }

    func waitForRequests(_ expected: Int) async {
        if count >= expected { return }
        await withCheckedContinuation { watchers.append((expected, $0)) }
    }

    func request(_ trigger: SyncTrigger) async -> SyncRuntimeWakeResult {
        count += 1
        for (expected, watcher) in watchers where count >= expected { watcher.resume() }
        watchers.removeAll { count >= $0.0 }
        guard holding else { return .transportUnavailable }
        return await withCheckedContinuation { held.append($0) }
    }

    func setNetworkAvailable(_ available: Bool) async {}
    func close() async { isClosed = true }
}

actor CountingTransport: SyncRuntimePort {
    private(set) var requests = 0
    func request(_ trigger: SyncTrigger) async -> SyncRuntimeWakeResult {
        requests += 1
        return .transportUnavailable
    }
    func setNetworkAvailable(_ available: Bool) async {}
    func close() async {}
}
