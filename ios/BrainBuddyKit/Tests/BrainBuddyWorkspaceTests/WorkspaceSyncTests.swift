import BrainBuddyCore
import BrainBuddyPersistence
import BrainBuddySync
import Foundation
import Testing

@testable import BrainBuddyWorkspace

/// Signing in and out, the sync service calls, and documents and statuses
/// the sync service reports.
@MainActor
@Suite struct WorkspaceSyncTests {
    /// A document of a signed-in device: one server task, nothing pending.
    static func linkedDocument(outbox: [PendingOperation] = [], issues: [SyncIssue] = []) -> StoreDocument {
        StoreDocument(
            generation: 3, base: Fixture.base([Fixture.serverTask("server-1", "Plan the offsite")]), outbox: outbox,
            issues: issues, account: Fixture.account, sync: SyncMetadata(lastPullAt: Fixture.epoch)
        )
    }

    struct SignedIn {
        let workspace: Workspace
        let sync: FakeSyncService
        let store: ControlledStore
    }

    func signedIn(_ document: StoreDocument = linkedDocument()) async -> SignedIn {
        let store = ControlledStore(InMemoryDocumentStore(document: document))
        let sync = FakeSyncService(store: store.base)
        let workspace = await loadedWorkspace(store: store, sync: sync)
        return SignedIn(workspace: workspace, sync: sync, store: store)
    }

    // MARK: Starting

    @Test func loadStartsSyncForALinkedAccountOnce() async {
        let session = await signedIn()

        await session.workspace.load()
        await session.workspace.reloadIfChangedExternally()

        #expect(await session.sync.calls == [.start(Fixture.account)])
        #expect(await session.sync.hasEventHandler)
        #expect(session.workspace.account == Fixture.account)
        #expect(session.workspace.syncStatus == .idle(lastSyncedAt: Fixture.epoch))
    }

    @Test func loadDuringAWriteKeepsTheWriteAndStillStartsSync() async throws {
        let store = ControlledStore(InMemoryDocumentStore(document: Self.linkedDocument()))
        let sync = FakeSyncService(store: store.base)
        let workspace = makeWorkspace(store: store, sync: sync)
        await store.holdWrites()

        // An App Intent in the app process can write before the app has loaded.
        let id = try workspace.capture(CaptureDraft(text: "Captured by Siri"))
        await store.waitForHeldWrite()
        let loading = Task { await workspace.load() }
        await store.waitForLoads(1)
        await store.releaseWrites()
        await loading.value

        #expect(workspace.task(id) != nil)
        #expect(workspace.task("server-1") != nil)
        #expect(workspace.document.generation == 4)
        #expect(workspace.state == workspace.replayedState)
        #expect(await sync.calls == [.request(.localChange), .start(Fixture.account)])
    }

    @Test func loadWithoutAnAccountDoesNotStartSync() async {
        let sync = FakeSyncService()
        let workspace = await loadedWorkspace(sync: sync)

        #expect(await sync.calls.isEmpty)
        #expect(workspace.syncStatus == .localOnly)
    }

    @Test func eachWriteAsksForASync() async throws {
        let session = await signedIn()

        try session.workspace.capture(CaptureDraft(text: "One"))
        await session.workspace.flush()
        try session.workspace.capture(CaptureDraft(text: "Two"))
        await session.workspace.flush()

        #expect(
            await session.sync.calls == [.start(Fixture.account), .request(.localChange), .request(.localChange)]
        )
    }

    // MARK: Signing in

    @Test func signInFlushesFirstThenLinksTheAccount() async throws {
        let store = InMemoryDocumentStore()
        let sync = FakeSyncService(store: store)
        let workspace = await loadedWorkspace(store: store, sync: sync)
        try workspace.capture(CaptureDraft(text: "Captured before signing in"))
        try workspace.capture(CaptureDraft(text: "And another"))

        try await workspace.signIn(
            serverURL: URL(string: "https://brain-buddy.example/api/")!, email: "ana@example.com",
            password: "correct horse"
        )

        // Both captures were on disk before the engine was asked to sign in.
        #expect(await sync.outboxCountAtSignIn == 2)
        #expect(
            await sync.calls == [
                .request(.localChange), .signIn(serverURL: Fixture.serverURL, email: "ana@example.com"),
            ]
        )
        #expect(workspace.account == Fixture.account)
        #expect(workspace.syncStatus == .idle(lastSyncedAt: Fixture.epoch))
        #expect(try await store.load()?.account == Fixture.account)
        #expect(workspace.pendingChangeCount == 2)
        // Already running after sign-in: not started a second time.
        await workspace.load()
        #expect(await sync.calls.contains(.start(Fixture.account)) == false)
    }

    @Test func aRefusedSignInIsReportedInTheServersWords() async {
        let failure = SignInFailure(message: "Check your email and password.", referenceID: "req-42")
        let sync = FakeSyncService(signInResult: .failure(failure))
        let workspace = await loadedWorkspace(sync: sync)

        await #expect(
            throws: WorkspaceError.signInFailed(message: "Check your email and password.", referenceID: "req-42")
        ) {
            try await workspace.signIn(serverURL: Fixture.serverURL, email: "ana@example.com", password: "wrong")
        }
        #expect(workspace.account == nil)
        #expect(workspace.syncStatus == .localOnly)
    }

    @Test func signInAcceptsOnlyHTTPSOrLocalhost() async throws {
        let sync = FakeSyncService()
        let workspace = await loadedWorkspace(sync: sync)

        await #expect(throws: WorkspaceError.invalidServerURL) {
            try await workspace.signIn(
                serverURL: URL(string: "http://brain-buddy.example/api")!, email: "a@example.com", password: "p"
            )
        }
        #expect(await sync.calls.isEmpty)

        try await workspace.signIn(
            serverURL: URL(string: "http://localhost:8000/api")!, email: "a@example.com", password: "p"
        )
        #expect(await sync.calls.first == .signIn(serverURL: URL(string: "http://localhost:8000/api")!, email: "a@example.com"))
        #expect(workspace.account == Fixture.account)
        #expect(workspace.syncStatus != .localOnly)
    }

    @Test func aSignInThatCancelledTheAccountsDeletionRaisesANoticeUntilAcknowledged() async throws {
        let store = InMemoryDocumentStore()
        let sync = FakeSyncService(store: store, deletionCancelled: true)
        let workspace = await loadedWorkspace(store: store, sync: sync)
        #expect(!workspace.signInCancelledAccountDeletion)

        try await workspace.signIn(serverURL: Fixture.serverURL, email: "ana@example.com", password: "correct horse")
        #expect(workspace.signInCancelledAccountDeletion)
        #expect(workspace.account == Fixture.account)

        workspace.acknowledgeAccountDeletionNotice()
        #expect(!workspace.signInCancelledAccountDeletion)
    }

    @Test func anOrdinarySignInRaisesNoDeletionNotice() async throws {
        let store = InMemoryDocumentStore()
        let workspace = await loadedWorkspace(store: store, sync: FakeSyncService(store: store))
        try await workspace.signIn(serverURL: Fixture.serverURL, email: "ana@example.com", password: "correct horse")
        #expect(!workspace.signInCancelledAccountDeletion)
    }

    @Test func launchingWithoutAnAccountDiscardsStaleSessions() async {
        let sync = FakeSyncService()
        _ = await loadedWorkspace(sync: sync)
        #expect(await sync.discardedSessions == [nil])

        let session = await signedIn()
        #expect(await session.sync.discardedSessions.isEmpty, "a linked account keeps its session")
    }

    @Test func signInWithoutSyncPointsToTheApp() async {
        let workspace = await loadedWorkspace()

        await #expect(throws: WorkspaceError.signInFailed(message: "Sign in from the Brain Buddy app.", referenceID: nil)) {
            try await workspace.signIn(serverURL: Fixture.serverURL, email: "a@example.com", password: "p")
        }
    }

    // MARK: Signing out

    @Test func signOutRefusesWhileChangesAreUnsynced() async throws {
        let session = await signedIn()
        try session.workspace.capture(CaptureDraft(text: "Not synced"))

        await #expect(throws: WorkspaceError.unsyncedChanges(count: 1)) {
            try await session.workspace.signOut(discardUnsyncedChanges: false)
        }

        #expect(session.workspace.account == Fixture.account)
        #expect(await session.sync.calls.contains(.signOut) == false)
        await session.workspace.flush()
        #expect(try await session.store.load()?.outbox.count == 1)
    }

    @Test func signOutDiscardingChangesRemovesTheAccountsData() async throws {
        let session = await signedIn()
        let persisted = CallCounter()
        session.workspace.didPersist = { persisted.record() }
        try session.workspace.capture(CaptureDraft(text: "Not synced"))

        try await session.workspace.signOut(discardUnsyncedChanges: true)

        #expect(try await session.store.load() == nil)
        #expect(await session.sync.calls.contains(.signOut))
        #expect(session.workspace.state == .empty)
        #expect(session.workspace.account == nil)
        #expect(session.workspace.syncStatus == .localOnly)
        #expect(session.workspace.pendingChangeCount == 0)
        #expect(session.workspace.issues.isEmpty)
        #expect(persisted.count >= 1)
    }

    @Test func signOutCountsChangesAWidgetQueuedThatTheAppHasNotSeen() async throws {
        let session = await signedIn()
        let widget = await loadedWorkspace(store: session.store.base, ids: IDSequence(namespace: 2))
        try widget.completeTask("server-1")
        await widget.flush()
        #expect(session.workspace.pendingChangeCount == 0, "not reloaded yet")

        await #expect(throws: WorkspaceError.unsyncedChanges(count: 1)) {
            try await session.workspace.signOut(discardUnsyncedChanges: false)
        }
        #expect(await session.sync.calls.contains(.signOut) == false)
        #expect(try await session.store.load()?.outbox.count == 1)
        #expect(session.workspace.account == Fixture.account)
        #expect(session.workspace.pendingChangeCount == 1, "and now shows it")
        #expect(session.workspace.task("server-1")?.state == .completed)

        try await session.workspace.signOut(discardUnsyncedChanges: true)
        #expect(try await session.store.load() == nil)
        #expect(session.workspace.account == nil)
    }

    @Test func aChangeQueuedWhileSigningOutKeepsTheAccountsData() async throws {
        let session = await signedIn()
        let shared = session.store.base
        // A widget writes after the check, while the engine logs out.
        await session.sync.whileSigningOut {
            _ = try? await shared.update { document in
                let command = GTDCommand.transitionTask(.init(taskID: "server-1", action: .complete))
                document.outbox.append(PendingOperation(command: command, issuedAt: Fixture.epoch))
            }
        }

        await #expect(throws: WorkspaceError.unsyncedChanges(count: 1)) {
            try await session.workspace.signOut(discardUnsyncedChanges: false)
        }
        #expect(try await session.store.load()?.outbox.count == 1, "nothing was removed")
        #expect(session.workspace.account == Fixture.account)
        #expect(session.workspace.pendingChangeCount == 1)
        #expect(
            await session.sync.calls == [.start(Fixture.account), .signOut, .start(Fixture.account)],
            "sync starts again for the account, which will ask to sign in again"
        )
    }

    @Test func signOutWithEverythingSyncedNeedsNoConfirmation() async throws {
        let session = await signedIn()

        try await session.workspace.signOut(discardUnsyncedChanges: false)

        #expect(session.workspace.account == nil)
        #expect(try await session.store.load() == nil)
    }

    @Test func afterSignOutLateEventsOfTheOldAccountAreIgnored() async throws {
        let session = await signedIn()
        try await session.workspace.signOut(discardUnsyncedChanges: false)

        var late = Self.linkedDocument()
        late.generation = 40
        await session.sync.emit(.documentChanged(late))
        await session.sync.emit(.status(.syncing))

        #expect(session.workspace.state == .empty)
        #expect(session.workspace.account == nil)
        #expect(session.workspace.syncStatus == .localOnly)

        // The device keeps working on its own, in a new document.
        let id = try session.workspace.capture(CaptureDraft(text: "Local again"))
        await session.workspace.flush()
        let stored = try #require(try await session.store.load())
        #expect(stored.generation == 1)
        #expect(stored.account == nil)
        #expect(createdTaskIDs(in: stored.outbox) == [id])
    }

    // MARK: Events

    @Test func statusEventsUpdateSyncStatus() async {
        let session = await signedIn()

        await session.sync.emit(.status(.syncing))
        #expect(session.workspace.syncStatus == .syncing)
        await session.sync.emit(.status(.offline(lastSyncedAt: Fixture.epoch)))
        #expect(session.workspace.syncStatus == .offline(lastSyncedAt: Fixture.epoch))
        await session.sync.emit(.status(.needsSignIn))
        #expect(session.workspace.syncStatus == .needsSignIn)
    }

    @Test func anAcknowledgementMovesAChangeIntoTheBase() async throws {
        let session = await signedIn()
        let id = try session.workspace.capture(CaptureDraft(text: "Call Ana"))
        await session.workspace.flush()
        #expect(session.workspace.pendingChangeCount == 1)
        let local = try #require(session.workspace.task(id))

        // The engine sent it: the server's record replaces the operation.
        var record = local
        record.serverID = "task_1a2b3c"
        record.serverRevision = 1
        let acknowledged = record
        try await session.sync.write { document in
            document.outbox.removeAll()
            document.base.tasks[id] = acknowledged
        }

        #expect(session.workspace.pendingChangeCount == 0)
        #expect(session.workspace.task(id)?.serverID == "task_1a2b3c")
        #expect(session.workspace.state == session.workspace.replayedState)
    }

    @Test func aNewBaseKeepsPendingLocalChangesVisible() async throws {
        let session = await signedIn()
        await session.store.failWrites(with: .io("busy"))
        let local = try session.workspace.capture(CaptureDraft(text: "Typed offline"))
        try session.workspace.completeTask("server-1")
        await session.workspace.flush()
        #expect(session.workspace.unpersisted.count == 2)

        // A pull brings a task from the web and a rename of the server task.
        try await session.sync.write { document in
            document.base.tasks["server-1"]?.title = "Plan the offsite in May"
            document.base.tasks["server-2"] = Fixture.serverTask("server-2", "From the web", orderKey: 1)
        }

        let workspace = session.workspace
        #expect(workspace.task("server-2")?.title == "From the web")
        #expect(workspace.task("server-1")?.title == "Plan the offsite in May")
        #expect(workspace.task("server-1")?.state == .completed)
        #expect(workspace.task(local)?.title == "Typed offline")
        #expect(workspace.pendingChangeCount == 2)
        #expect(workspace.state == workspace.replayedState)

        await session.store.failWrites(with: nil)
        let replays = workspace.fullReplayCount
        await workspace.flush()
        let stored = try #require(try await session.store.base.load())
        #expect(stored.outbox.count == 2)
        #expect(workspace.document == stored)
        #expect(workspace.fullReplayCount == replays)
        #expect(workspace.state == workspace.replayedState)
        #expect(workspace.task("server-2") != nil)
    }

    @Test func aDocumentReportedDuringAWriteIsAdoptedAfterItWithoutApplyingTheWriteTwice() async throws {
        let session = await signedIn()
        let workspace = session.workspace
        await session.store.holdWrites()

        try workspace.updateTask("server-1", TaskChanges(title: .set("Renamed here")))
        await session.store.waitForHeldWrite()

        // Reported while our write waits: the engine saw our rename land and
        // then another device's rename after it.
        var later = Self.linkedDocument()
        later.generation = 9
        later.outbox = [
            PendingOperation(
                command: .updateTask(.init(taskID: "server-1", changes: TaskChanges(title: .set("Renamed here")))),
                issuedAt: Fixture.epoch
            ),
            PendingOperation(
                command: .updateTask(.init(taskID: "server-1", changes: TaskChanges(title: .set("Renamed on the iPad")))),
                issuedAt: Fixture.epoch.addingTimeInterval(1)
            ),
        ]
        await session.sync.emit(.documentChanged(later))
        // No flicker back to the old title while the write is pending.
        #expect(workspace.task("server-1")?.title == "Renamed here")

        await session.store.releaseWrites()
        await workspace.flush()

        #expect(workspace.document.generation == 9)
        #expect(workspace.task("server-1")?.title == "Renamed on the iPad")
        #expect(workspace.unpersisted.isEmpty)
    }

    @Test func anOlderDocumentIsIgnored() async throws {
        let session = await signedIn()
        try session.workspace.capture(CaptureDraft(text: "Mine"))
        await session.workspace.flush()
        let current = session.workspace.state

        var stale = Self.linkedDocument()
        stale.generation = session.workspace.document.generation
        await session.sync.emit(.documentChanged(stale))

        #expect(session.workspace.state == current)
    }

    // MARK: Requests

    @Test func syncNowWritesPendingChangesFirstAndReportsTheResult() async throws {
        let store = ControlledStore(InMemoryDocumentStore(document: Self.linkedDocument()))
        let sync = FakeSyncService(store: store.base, syncNowStatus: .offline(lastSyncedAt: Fixture.epoch))
        let workspace = await loadedWorkspace(store: store, sync: sync)
        try workspace.capture(CaptureDraft(text: "Push me"))

        await workspace.syncNow()

        #expect(await sync.calls == [.start(Fixture.account), .request(.localChange), .syncNow])
        #expect(workspace.syncStatus == .offline(lastSyncedAt: Fixture.epoch))
    }

    @Test func syncRequestsNeedALinkedAccount() async {
        let sync = FakeSyncService()
        let workspace = await loadedWorkspace(sync: sync)

        await workspace.syncNow()
        await workspace.refreshTaskDetails("task-1")

        #expect(await sync.calls.isEmpty)
    }

    @Test func refreshTaskDetailsAsksTheSyncService() async {
        let session = await signedIn()

        await session.workspace.refreshTaskDetails("server-1")

        #expect(await session.sync.calls == [.start(Fixture.account), .refreshTask("server-1")])
    }

    @Test func changesQueuedByAnotherProcessAskForASync() async throws {
        let session = await signedIn()
        // A widget (another process, sync disabled) completes a task in the shared store.
        let widget = await loadedWorkspace(store: session.store.base, ids: IDSequence(namespace: 2))
        try widget.completeTask("server-1")
        await widget.flush()

        await session.workspace.reloadIfChangedExternally()

        #expect(session.workspace.task("server-1")?.state == .completed)
        #expect(await session.sync.calls == [.start(Fixture.account), .request(.localChange)])
    }

    @Test func aReloadWithoutNewChangesDoesNotAskForASync() async throws {
        let session = await signedIn()
        let pulledAt = Fixture.epoch.addingTimeInterval(60)
        // A write by the engine whose event this workspace missed.
        _ = try await session.store.base.update { $0.sync.lastPullAt = pulledAt }

        await session.workspace.reloadIfChangedExternally()

        #expect(session.workspace.document.sync.lastPullAt == pulledAt)
        #expect(await session.sync.calls == [.start(Fixture.account)])
    }

    @Test func withoutAnAccountAReloadAsksForNoSync() async throws {
        let store = InMemoryDocumentStore()
        let sync = FakeSyncService(store: store)
        let app = await loadedWorkspace(store: store, sync: sync)
        let widget = await loadedWorkspace(store: store, ids: IDSequence(namespace: 2))
        let id = try widget.capture(CaptureDraft(text: "From the widget"))
        await widget.flush()

        await app.reloadIfChangedExternally()

        #expect(app.task(id) != nil)
        #expect(await sync.calls.isEmpty)
    }

    @Test func networkChangesReachTheSyncServiceInOrder() async {
        let session = await signedIn()

        session.workspace.networkAvailabilityChanged(isAvailable: false)
        session.workspace.networkAvailabilityChanged(isAvailable: true)
        session.workspace.networkAvailabilityChanged(isAvailable: false)
        await session.workspace.waitForNetworkUpdates()

        #expect(
            await session.sync.calls == [
                .start(Fixture.account), .setNetworkAvailable(false), .setNetworkAvailable(true),
                .request(.networkRestored), .setNetworkAvailable(false),
            ]
        )
    }

    // MARK: Issues

    @Test func dismissIssueHidesItAtOnceAndRemovesItFromTheStore() async throws {
        let kept = Fixture.issue("Kept")
        let dismissed = Fixture.issue("Dismissed")
        let session = await signedIn(Self.linkedDocument(issues: [kept, dismissed]))
        await session.store.failWrites(with: .io("busy"))

        session.workspace.dismissIssue(dismissed.id)
        #expect(session.workspace.issues == [kept])

        // A pull reported before the removal is written does not bring it back.
        try await session.sync.write { $0.sync.lastPullAt = Fixture.epoch.addingTimeInterval(60) }
        #expect(session.workspace.document.issues == [kept, dismissed])
        #expect(session.workspace.issues == [kept])

        await session.store.failWrites(with: nil)
        await session.workspace.flush()
        #expect(try await session.store.load()?.issues == [kept])
        #expect(session.workspace.issues == [kept])
    }
}
