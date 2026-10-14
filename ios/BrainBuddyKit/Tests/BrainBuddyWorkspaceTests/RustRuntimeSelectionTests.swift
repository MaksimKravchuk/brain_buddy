import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyPersistence
import BrainBuddySync
import Foundation
import Synchronization
import Testing

@testable import BrainBuddyWorkspace

/// The production selection of the Rust runtime and its account lifecycle, over real Rust stores
/// in a temporary folder with a stubbed server (spec 026, T044, PR-54 pilot): what the app, a
/// widget and an App Intent read, when the import is allowed to run, and what sign-in and
/// sign-out do to the store.
@Suite("Rust runtime selection and account lifecycle (026-FR-003, 026-FR-010, 026-FR-011, 026-FR-025)")
struct RustRuntimeSelectionTests {
    // MARK: Selection

    @Test("026-FR-025: with the pilot switch off nothing is selected, opened or written")
    @MainActor
    func pilotOffChangesNothing() async throws {
        let lane = try SelectionLane()
        defer { lane.cleanup() }
        switch await lane.launcher(pilot: false).resolve() {
        case .legacy(.pilotOff): break
        default: Issue.record("the install must stay legacy")
        }
        #expect(!FileManager.default.fileExists(atPath: lane.location.root.path))
        guard case .legacy = await Workspace.openForExtension(location: lane.location, bridge: lane.bridge) else {
            Issue.record("a widget must follow the missing selection to the legacy runtime")
            return
        }
    }

    @Test("026-FR-025: app, widget and App Intent read the one persisted selection and write into its scope")
    @MainActor
    func selectionIsSharedAndSticky() async throws {
        let lane = try SelectionLane()
        defer { lane.cleanup() }
        let app = try await lane.app()
        let record = try #require(try lane.selections.load())
        #expect(record.runtime == .rust && record.account == nil && record.workspaceID.hasPrefix("local-"))

        guard case .rust(let widget) = await Workspace.openForExtension(location: lane.location, bridge: lane.bridge) else {
            Issue.record("the widget must open the selected store")
            return
        }
        await widget.load()
        let id = try await widget.capture(CaptureDraft(text: "From the widget"), editorID: "scene:widget:1")
        await app.reloadIfChangedExternally()
        await app.prepareList(.list(.inbox))
        #expect(app.task(id)?.title == "From the widget")
        // A widget never owns sync.
        await widget.requestForegroundPull()
        #expect(widget.runtimeTransportUnavailable)

        // The pilot switch is only the way in: with it off again the install keeps its selection,
        // because its work is in the Rust store now.
        await widget.closeRuntime()
        await app.closeRuntime()
        guard case .rust(let again, _) = await lane.launcher(pilot: false).resolve() else {
            Issue.record("a made selection does not depend on the switch")
            return
        }
        #expect(try lane.selections.load()?.workspaceID == record.workspaceID)
        try await again.runtime.close()
    }

    @Test("026-FR-025: an unreadable selection never falls back to the retired file")
    @MainActor
    func unreadableSelectionIsUnavailable() async throws {
        let lane = try SelectionLane()
        defer { lane.cleanup() }
        try FileManager.default.createDirectory(at: lane.location.root, withIntermediateDirectories: true)
        try Data("not json".utf8).write(to: lane.location.selectionURL)
        if case .unavailable(let code) = await lane.launcher(pilot: true).resolve() { #expect(code == "SELECTION_UNREADABLE") }
        else { Issue.record("the install must not open the legacy file") }
        guard case .unavailable = await Workspace.openForExtension(location: lane.location, bridge: lane.bridge) else {
            Issue.record("a widget must refuse to write")
            return
        }
        // A selection a newer build wrote is as unreadable.
        var newer = RustRuntimeSelectionRecord(workspaceID: "x", account: nil, deviceID: "d", selectedAt: lane.instant)
        newer.version = 99
        try JSONEncoder().encode(newer).write(to: lane.location.selectionURL)
        #expect(throws: RustRuntimeSelectionError.unreadable) { _ = try lane.selections.load() }
    }

    // MARK: The handoff against legacy writers

    @Test("026-FR-025: a legacy writer that gets the lock after the handoff is refused and the edit is not stranded")
    @MainActor
    func writerAfterHandoffIsRefused() async throws {
        let lane = try SelectionLane()
        defer { lane.cleanup() }
        try await lane.writeLegacy(lane.legacyDocument(account: nil))
        guard case .rust(let selection, _) = await lane.launcher(pilot: true).resolve() else {
            Issue.record("a clean legacy file must be imported")
            return
        }
        let before = try Data(contentsOf: lane.legacyURL)
        // An App Intent that was waiting for the legacy lock gets it now: the selection exists.
        let legacy = FileDocumentStore(fileURL: lane.legacyURL)
        await #expect(throws: DocumentStoreError.io(FileDocumentStore.retiredReason)) {
            _ = try await legacy.update { $0 = $0 }
        }
        #expect(try Data(contentsOf: lane.legacyURL) == before, "nothing was committed to the retired file")
        try await selection.runtime.close()
    }

    @Test("026-FR-025: a legacy write that lands between the import and the handoff keeps the install legacy")
    @MainActor
    func writerBeforeHandoffBlocksTheSelection() async throws {
        let lane = try SelectionLane()
        defer { lane.cleanup() }
        try await lane.writeLegacy(lane.legacyDocument(account: nil))
        var environment = lane.environment()
        let url = lane.legacyURL
        environment.beforeHandoff = {
            // The writer that was queued behind the import's lock commits first.
            _ = try? await FileDocumentStore(fileURL: url).update { _ in }
        }
        let switchBox = RustRuntimePilotSwitch(suiteName: lane.suite)
        switchBox.set(true)
        let resolution = await RustRuntimeLauncher(environment: environment, pilot: switchBox).resolve()
        guard case .legacy(.notReady(let code)) = resolution else {
            Issue.record("the selection must not be published over a newer legacy file")
            return
        }
        #expect(code == "LEGACY_CHANGED")
        #expect(try lane.selections.load() == nil)
    }

    // MARK: The import, gated

    @Test("026-FR-010: the pilot imports the legacy file once, binds the Rust store and leaves the file as it was")
    @MainActor
    func importBindsTheRustStore() async throws {
        let lane = try SelectionLane()
        defer { lane.cleanup() }
        try await lane.writeLegacy(lane.legacyDocument(account: nil))
        let before = try Data(contentsOf: lane.legacyURL)

        guard case .rust(let selection, let lifecycle) = await lane.launcher(pilot: true).resolve() else {
            Issue.record("a clean legacy file must be imported")
            return
        }
        let app = Workspace.selected(selection, lifecycle: lifecycle)
        await app.load()
        await app.prepareList(.list(.next))
        #expect(app.list(.list(.next)).sections.flatMap(\.tasks).map(\.title) == ["Imported task"])
        #expect(app.account == nil)
        #expect(try lane.selections.load()?.workspaceID == RustRuntimeLauncher.importedWorkspaceID)
        #expect(try Data(contentsOf: lane.legacyURL) == before)
        await app.closeRuntime()

        // The next launch opens the selected store and does not import again.
        guard case .rust(let reopened, _) = await lane.launcher(pilot: false).resolve() else {
            Issue.record("the selection must open")
            return
        }
        try await reopened.runtime.close()
    }

    @Test("026-FR-010: a signed-in legacy file is imported already linked to its account")
    @MainActor
    func signedInFileKeepsItsAccount() async throws {
        let lane = try SelectionLane()
        defer { lane.cleanup() }
        try await lane.writeLegacy(lane.legacyDocument(account: lane.accountA))
        guard case .rust(let selection, let lifecycle) = await lane.launcher(pilot: true).resolve() else {
            Issue.record("a signed-in legacy file must be imported")
            return
        }
        #expect(selection.account == lane.accountA)
        #expect(try lane.selections.load()?.account == lane.accountA)
        let app = Workspace.selected(selection, lifecycle: lifecycle)
        await app.load()
        #expect(app.account == lane.accountA)
        // Linking the same account again changes nothing.
        #expect(try await selection.runtime.linkAccount(accountID: lane.accountA.id) == .alreadyLinked)
        #expect(try await selection.runtime.linkAccount(accountID: lane.accountB.id) == .otherAccount)
        await app.closeRuntime()
    }

    @Test("026-FR-010: a file that cannot be imported keeps the install legacy and the next launch tries again")
    @MainActor
    func failedImportStaysLegacy() async throws {
        let lane = try SelectionLane()
        defer { lane.cleanup() }
        try Data("{ damaged".utf8).write(to: lane.legacyURL)
        guard case .legacy(.notReady(let code)) = await lane.launcher(pilot: true).resolve() else {
            Issue.record("a damaged file must not select the Rust runtime")
            return
        }
        #expect(!code.isEmpty)
        #expect(try lane.selections.load() == nil)
        guard case .legacy = await Workspace.openForExtension(location: lane.location, bridge: lane.bridge) else {
            Issue.record("a widget must stay on the legacy runtime")
            return
        }
        try FileManager.default.removeItem(at: lane.legacyURL)
        try await lane.writeLegacy(lane.legacyDocument(account: nil))
        guard case .rust(let selection, _) = await lane.launcher(pilot: true).resolve() else {
            Issue.record("the retry must import")
            return
        }
        try await selection.runtime.close()
    }

    // MARK: Sign-in

    @Test("026-FR-003: sign-in on an empty account-less install links the account in the store and the selection")
    @MainActor
    func signInLinksTheStore() async throws {
        let lane = try SelectionLane()
        defer { lane.cleanup() }
        let app = try await lane.app()
        try await app.signIn(serverURL: lane.serverURL, email: "a@example.com", password: "secret")

        #expect(app.account == lane.accountA)
        #expect(try lane.selections.load()?.account == lane.accountA)
        #expect(await lane.server.logins == 1)
        let selection = try #require(app.rustSelection)
        #expect(try await selection.runtime.linkAccount(accountID: lane.accountA.id) == .alreadyLinked)
        // The widget of a linked install shows the account and still never syncs.
        guard case .rust(let widget) = await Workspace.openForExtension(location: lane.location, bridge: lane.bridge) else {
            Issue.record("the widget must open the selected store")
            return
        }
        await widget.load()
        #expect(widget.account == lane.accountA)
        await widget.closeRuntime()
        await app.closeRuntime()
    }

    @Test("026-FR-003: the first sign-in carries account-less work into the account as queued commands, and a retry queues nothing more")
    @MainActor
    func localWorkIsMergedOnFirstSignIn() async throws {
        let lane = try SelectionLane()
        defer { lane.cleanup() }
        let app = try await lane.app()
        let id = try await app.capture(CaptureDraft(text: "Written before the account"), editorID: "scene:life:pre")
        await app.prepareList(.list(.inbox))
        await app.settleRustWork()  // the local-records read follows the save behind its return
        #expect(app.hasLocalWorkToMerge)

        try await app.signIn(serverURL: lane.serverURL, email: "a@example.com", password: "secret")
        #expect(await lane.server.logins == 1)
        #expect(app.account == lane.accountA)
        #expect(try lane.selections.load()?.account == lane.accountA)
        await app.refreshRustStatus()
        #expect(app.pendingChangeCount == 1, "the record is now a command waiting to be sent")
        await app.prepareList(.list(.inbox))
        #expect(app.list(.list(.inbox)).sections.flatMap(\.tasks).map(\.title) == ["Written before the account"])
        _ = id

        // Retried (a crash after the commit, a second launch): the same account is a no-op.
        let selection = try #require(app.rustSelection)
        let again = try await selection.runtime.linkAndMerge(
            accountID: lane.accountA.id, scopeID: lane.accountA.id, deviceID: try #require(try lane.selections.load()).deviceID,
            context: RustWorkspaceContext(now: lane.instant, timeZone: "UTC", actorID: "device",
                policy: Data(#"{"weekly_review":false,"navigator_provider":null,"navigator_available":false,"consent_text_version":1}"#.utf8)))
        #expect(again == .alreadyLinked)
        await app.refreshRustStatus()
        #expect(app.pendingChangeCount == 1)
        await app.closeRuntime()
    }

    @Test("026-FR-011: a Cancel that came first links nothing and ends the session the server opened")
    @MainActor
    func cancelledSignInLinksNothing() async throws {
        let lane = try SelectionLane()
        defer { lane.cleanup() }
        let app = try await lane.app()
        let cancellation = SignInCancellation()
        _ = cancellation.cancel()
        await #expect(throws: WorkspaceError.self) {
            try await app.signIn(serverURL: lane.serverURL, email: "a@example.com", password: "secret", cancellation: cancellation)
        }
        #expect(app.account == nil)
        #expect(try lane.selections.load()?.account == nil)
        #expect(await lane.server.abandoned == [lane.accountA.id])
        let selection = try #require(app.rustSelection)
        #expect(try await selection.runtime.linkAccount(accountID: lane.accountA.id) == .linked, "the store was never linked")
        await app.closeRuntime()
    }

    @Test("026-FR-003: another account is refused, its session ended, and nothing moves")
    @MainActor
    func otherAccountIsRefused() async throws {
        let lane = try SelectionLane()
        defer { lane.cleanup() }
        let app = try await lane.app()
        try await app.signIn(serverURL: lane.serverURL, email: "a@example.com", password: "secret")
        await lane.server.next(lane.accountB)
        await #expect(throws: WorkspaceError.signInFailed(message: HostRustAccountLifecycle.differentAccountMessage, referenceID: nil)) {
            try await app.signIn(serverURL: lane.serverURL, email: "b@example.com", password: "secret")
        }
        #expect(app.account == lane.accountA)
        #expect(try lane.selections.load()?.account == lane.accountA)
        #expect(await lane.server.abandoned == [lane.accountB.id])
        await app.closeRuntime()
    }

    @Test("026-FR-013: a late response of the account-less binding is dropped once sign-in links the account")
    @MainActor
    func lateResponseAfterSignIn() async throws {
        let lane = try SelectionLane()
        defer { lane.cleanup() }
        let old = GatedTransport()
        let app = try await lane.app(transports: [old])
        await old.hold()
        let pull = Task { await app.requestForegroundPull() }
        await old.waitForRequests(2)
        try await app.signIn(serverURL: lane.serverURL, email: "a@example.com", password: "secret")
        #expect(app.account == lane.accountA)
        await old.release(.status(.needsSignIn))
        await pull.value
        #expect(app.syncStatus != .needsSignIn)
        #expect(await old.isClosed)
        await app.closeRuntime()
    }

    // MARK: Sign-out

    @Test("026-FR-011: the confirmation is checked again under the store's lock; work a widget queued meanwhile removes nothing")
    @MainActor
    func confirmationIsRecheckedUnderTheLock() async throws {
        let lane = try SelectionLane()
        defer { lane.cleanup() }
        let gate = Gate()
        let app = try await lane.app(gate: gate)
        try await app.signIn(serverURL: lane.serverURL, email: "a@example.com", password: "secret")
        let first = try await app.capture(CaptureDraft(text: "Queued by the app"), editorID: "scene:life:one")
        await app.settleRustWork()  // the pending list follows the save behind its return
        let named = app.pendingChanges
        #expect(named.count == 1)
        let oldIdentity = try #require(try lane.selections.load()).workspaceID

        let signOut = Task { try await app.signOut(removing: named) }
        await gate.waitUntilReached()
        guard case .rust(let widget) = await Workspace.openForExtension(location: lane.location, bridge: lane.bridge) else {
            Issue.record("the widget must open the selected store")
            return
        }
        await widget.load()
        let second = try await widget.capture(CaptureDraft(text: "Queued by a widget"), editorID: "scene:widget:1")
        await gate.open()
        do {
            try await signOut.value
            Issue.record("the widget's change was queued after the count was named; it must not be removed")
        } catch let error as WorkspaceError {
            #expect(error == .unsyncedChanges(count: 2))
        }
        #expect(app.account == lane.accountA)
        let cancelled = await lane.server.cancelledSignOuts
        let finished = await lane.server.finishedSignOuts
        #expect(cancelled == 1 && finished == 0)
        await app.reloadIfChangedExternally()
        await app.prepareList(.list(.inbox))
        #expect(app.task(first)?.title == "Queued by the app" && app.task(second)?.title == "Queued by a widget")

        // The next sign-out names both, removes the copy and starts an empty identity.
        await gate.open()
        try await app.signOut(removing: app.pendingChanges)
        #expect(app.account == nil)
        #expect(await lane.server.finishedSignOuts == 1)
        let next = try #require(try lane.selections.load())
        #expect(next.workspaceID != oldIdentity && next.account == nil && next.deviceID != "")
        #expect(!FileManager.default.fileExists(atPath: lane.location.identityDirectory(oldIdentity).path))
        await app.prepareList(.list(.inbox))
        #expect(app.list(.list(.inbox)).sections.flatMap(\.tasks).isEmpty)

        // A widget opened now writes into the new identity only.
        guard case .rust(let nextWidget) = await Workspace.openForExtension(location: lane.location, bridge: lane.bridge) else {
            Issue.record("the widget must follow the new selection")
            return
        }
        await nextWidget.load()
        let third = try await nextWidget.capture(CaptureDraft(text: "Next identity"), editorID: "scene:widget:2")
        await app.reloadIfChangedExternally()
        await app.prepareList(.list(.inbox))
        #expect(app.task(third)?.title == "Next identity")
        await widget.closeRuntime()
        await nextWidget.closeRuntime()
        await app.closeRuntime()
    }

    @Test("026-FR-013: a late response of the previous owner is dropped after sign-out")
    @MainActor
    func lateResponseAfterSignOut() async throws {
        let lane = try SelectionLane()
        defer { lane.cleanup() }
        let account = GatedTransport()
        let app = try await lane.app(transports: [PendingRustSyncRuntimePort(), account])
        try await app.signIn(serverURL: lane.serverURL, email: "a@example.com", password: "secret")
        await account.hold()
        let pull = Task { await app.requestForegroundPull() }
        await account.waitForRequests(2)
        try await app.signOut(removing: [])
        #expect(app.account == nil)
        await account.release(.status(.idle(lastSyncedAt: lane.instant)))
        await pull.value
        #expect(app.syncStatus == .localOnly)
        #expect(await account.isClosed)
        await app.closeRuntime()
    }
}

// MARK: - Support

/// A temporary install: a folder for the runtime and the retired file, and a real bridge.
struct SelectionLane: Sendable {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent("selection-\(UUID().uuidString)")
    let bridge: RustBridgeRuntime
    let instant = Date(timeIntervalSince1970: 1_790_000_000)
    let serverURL = URL(string: "https://example.com/api")!
    let accountA: LinkedAccount
    let accountB: LinkedAccount
    let server: StubAccountServer
    let suite = "selection-\(UUID().uuidString)"

    init() throws {
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        bridge = try RustBridgeRuntime()
        let url = URL(string: "https://example.com/api")!
        accountA = LinkedAccount(id: "owner-a", email: "a@example.com", serverURL: url, linkedAt: Date(timeIntervalSince1970: 1_789_000_000))
        accountB = LinkedAccount(id: "owner-b", email: "b@example.com", serverURL: url, linkedAt: Date(timeIntervalSince1970: 1_789_000_000))
        server = StubAccountServer(account: accountA)
    }

    var location: RustRuntimeLocation { .directory(root) }
    var legacyURL: URL { root.appendingPathComponent("store.json") }
    var selections: RustRuntimeSelectionStore { RustRuntimeSelectionStore(location: location) }

    func cleanup() {
        UserDefaults(suiteName: suite)?.removePersistentDomain(forName: suite)
        try? FileManager.default.removeItem(at: root)
    }

    func environment(transports: [any SyncRuntimePort] = []) -> RustRuntimeEnvironment {
        let instant = instant
        return RustRuntimeEnvironment(
            location: location, legacyStoreURL: legacyURL, bridge: bridge,
            transports: QueuedTransports(transports), server: server, now: { instant })
    }

    func launcher(pilot: Bool, transports: [any SyncRuntimePort] = []) -> RustRuntimeLauncher {
        let switchBox = RustRuntimePilotSwitch(suiteName: suite)
        switchBox.set(pilot)
        return RustRuntimeLauncher(environment: environment(transports: transports), pilot: switchBox)
    }

    /// The app of a fresh install with the pilot on: account-less, loaded.
    @MainActor
    func app(transports: [any SyncRuntimePort] = [], gate: Gate? = nil) async throws -> Workspace {
        guard case .rust(let selection, let lifecycle) = await launcher(pilot: true, transports: transports).resolve() else {
            throw SelectionLaneError.notSelected
        }
        let port: any RustAccountLifecyclePort = gate.map { GatedLifecycle(inner: lifecycle, gate: $0) } ?? lifecycle
        let workspace = Workspace.selected(selection, lifecycle: port)
        await workspace.load()
        guard workspace.isRustBound else { throw SelectionLaneError.notSelected }
        return workspace
    }

    func writeLegacy(_ document: StoreDocument) async throws {
        _ = try await FileDocumentStore(fileURL: legacyURL).update { $0 = document }
    }

    func legacyDocument(account: LinkedAccount?) -> StoreDocument {
        let created = Date(timeIntervalSince1970: 1_788_000_000)
        let task = TaskRecord(
            id: "task-1", title: "Imported task", state: .next, orderKey: 1, createdAt: created, updatedAt: created)
        return StoreDocument(generation: 1, base: GTDState(tasks: ["task-1": task]), account: account)
    }
}

enum SelectionLaneError: Error { case notSelected }

/// Hands out the transports a test queued, in the order the bindings ask, then nothing.
final class QueuedTransports: RustTransportProvider {
    private let queue: Mutex<[any SyncRuntimePort]>

    init(_ transports: [any SyncRuntimePort]) {
        queue = Mutex(transports)
    }

    func transport(for context: RustTransportContext) -> any SyncRuntimePort {
        queue.withLock { $0.isEmpty ? PendingRustSyncRuntimePort() : $0.removeFirst() }
    }
}

/// Holds a sign-out between the workspace's own count check and the port's check under the lock.
struct GatedLifecycle: RustAccountLifecyclePort {
    let inner: any RustAccountLifecyclePort
    let gate: Gate

    func signIn(_ request: RustSignInRequest) async throws -> RustSignInOutcome { try await inner.signIn(request) }

    func signOut(_ request: RustSignOutRequest) async throws -> RustWorkspaceSelection {
        await gate.reach()
        return try await inner.signOut(request)
    }
}

/// The server, as a test script: one account per login unless told otherwise.
actor StubAccountServer: RustAccountServer {
    private var account: LinkedAccount
    private(set) var logins = 0
    private(set) var abandoned: [String] = []
    private(set) var beganSignOuts = 0
    private(set) var finishedSignOuts = 0
    private(set) var cancelledSignOuts = 0
    var deletionCancelled = false

    init(account: LinkedAccount) {
        self.account = account
    }

    func next(_ account: LinkedAccount) { self.account = account }

    func login(serverURL: URL, email: String, password: String) async throws -> RustServerLogin {
        logins += 1
        return RustServerLogin(account: account, deletionCancelled: deletionCancelled)
    }

    func abandon(_ login: RustServerLogin) async { abandoned.append(login.account.id) }

    func beginSignOut(of account: LinkedAccount) async throws -> RustSignOutTicket {
        beganSignOuts += 1
        return RustSignOutTicket(logout: nil)
    }

    func finishSignOut(_ ticket: RustSignOutTicket, of account: LinkedAccount) async { finishedSignOuts += 1 }

    func cancelSignOut(_ ticket: RustSignOutTicket) async { cancelledSignOuts += 1 }
}
