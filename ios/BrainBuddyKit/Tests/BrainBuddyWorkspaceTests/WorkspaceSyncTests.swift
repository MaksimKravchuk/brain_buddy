import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyFakeServer
import BrainBuddyPersistence
import BrainBuddySync
import Foundation
import Synchronization
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
            await session.sync.calls == [.start(Fixture.account), .signOut],
            "the engine resumes by itself: the session was never ended"
        )
    }

    /// A capture through the workspace while its sign-out is suspended: the refusal's words, or nil
    /// when it was taken.
    static func captureWhileSigningOut(_ workspace: Workspace, _ title: String, into refusal: Refusal) async {
        await MainActor.run {
            do throws(GTDValidationError) {
                _ = try workspace.capture(CaptureDraft(text: title))
            } catch {
                refusal.record(error.message)
            }
        }
    }

    /// The words a refused capture showed.
    final class Refusal: Sendable {
        private let words = Mutex<String?>(nil)
        func record(_ message: String) { words.withLock { $0 = message } }
        var message: String? { words.withLock { $0 } }
    }

    @Test(
        "021-FR-018 a capture while a sign-out waits for the engine, before the removal, is refused with words, never silently removed",
        arguments: [false, true])
    func captureBeforeTheRemovalIsNeverLost(discard: Bool) async throws {
        let session = await signedIn()
        let workspace = session.workspace
        let refusal = Refusal()
        await session.sync.whileSigningOut { await Self.captureWhileSigningOut(workspace, "Water the tomatoes", into: refusal) }

        try await workspace.signOut(discardUnsyncedChanges: discard)

        let refused = refusal.message
        #expect(
            refused != nil || workspace.state.tasks.values.contains { $0.title == "Water the tomatoes" },
            "the capture was refused, so its text is still where it was typed, or it was kept")
        #expect(refused == GTDValidationError.signingOut.message)
        #expect(workspace.account == nil, "the sign-out went through")
        let retried = try workspace.capture(CaptureDraft(text: "Water the tomatoes"))
        #expect(workspace.task(retried) != nil, "once signed out, the same capture is taken")
    }

    @Test("021-FR-018 a capture after the removal, while the logout is on its way, is refused with words, never silently removed")
    func captureAfterTheRemovalIsNeverLost() async throws {
        let session = await signedIn()
        let workspace = session.workspace
        let refusal = Refusal()
        await session.sync.afterRemovingDataWhileSigningOut {
            await Self.captureWhileSigningOut(workspace, "Water the tomatoes", into: refusal)
        }

        try await workspace.signOut(discardUnsyncedChanges: false)

        let refused = refusal.message
        #expect(
            refused != nil || workspace.state.tasks.values.contains { $0.title == "Water the tomatoes" },
            "the capture was refused, so its text is still where it was typed, or it was kept")
        #expect(refused == GTDValidationError.signingOut.message)
        #expect(workspace.account == nil && workspace.pendingChangeCount == 0)
    }

    @Test("021-FR-018 Sign out and remove removes only the changes it counted: one another process queued meanwhile stops it")
    func signOutAndRemoveKeepsAChangeQueuedMeanwhile() async throws {
        let session = await signedIn()
        try session.workspace.capture(CaptureDraft(text: "Counted and removed"))
        #expect(session.workspace.pendingChangeCount == 1, "what the confirmation named")
        let shared = session.store.base
        // A widget writes after the confirmation, while the engine logs out.
        await session.sync.whileSigningOut {
            _ = try? await shared.update { document in
                let command = GTDCommand.transitionTask(.init(taskID: "server-1", action: .complete))
                document.outbox.append(PendingOperation(command: command, issuedAt: Fixture.epoch))
            }
        }

        await #expect(throws: WorkspaceError.unsyncedChanges(count: 2)) {
            try await session.workspace.signOut(discardUnsyncedChanges: true)
        }
        #expect(try await session.store.load()?.outbox.count == 2, "nothing was removed")
        #expect(session.workspace.account == Fixture.account)
        #expect(session.workspace.pendingChangeCount == 2, "asked again with the real count")

        try await session.workspace.signOut(discardUnsyncedChanges: true)
        #expect(try await session.store.load() == nil)
    }

    @Test("021-FR-018 Sign out and remove removes only the changes it named: one acknowledged and another queued meanwhile stops it")
    func signOutAndRemoveKeepsAChangeQueuedInPlaceOfAnAcknowledgedOne() async throws {
        let session = await signedIn()
        try session.workspace.capture(CaptureDraft(text: "Counted and removed"))
        await session.workspace.flush()
        let confirmed = session.workspace.pendingChangeIDs
        #expect(confirmed.count == 1 && confirmed == Set(session.workspace.document.outbox.map(\.id)), "what the confirmation named")
        let shared = session.store.base
        let queuedElsewhere = PendingOperation(
            command: .transitionTask(.init(taskID: "server-1", action: .complete)), issuedAt: Fixture.epoch)
        // While the engine logs out, the server acknowledges the named change and a widget queues
        // another one: the count is what the confirmation named, the change is not.
        await session.sync.whileSigningOut {
            _ = try? await shared.update { document in
                document.outbox.removeAll { confirmed.contains($0.id) }
                document.outbox.append(queuedElsewhere)
            }
        }

        await #expect(throws: WorkspaceError.unsyncedChanges(count: 1)) {
            try await session.workspace.signOut(removing: confirmed)
        }
        #expect(try await session.store.load()?.outbox.map(\.id) == [queuedElsewhere.id], "the widget's change is kept")
        #expect(session.workspace.account == Fixture.account)
        #expect(session.workspace.pendingChangeCount == 1, "asked again, naming it")
    }

    @Test("021-FR-018 a sign-out that fails takes changes again at once")
    func aFailedSignOutTakesChangesAgain() async throws {
        let session = await signedIn()
        try session.workspace.capture(CaptureDraft(text: "Not synced"))
        await #expect(throws: WorkspaceError.unsyncedChanges(count: 1)) {
            try await session.workspace.signOut(discardUnsyncedChanges: false)
        }
        let id = try session.workspace.capture(CaptureDraft(text: "Still taking changes"))
        #expect(session.workspace.task(id) != nil)
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

    // MARK: Foreground and the status snapshot

    @Test("021-FR-032 021-FR-006 the foreground starts the tick and asks for one pull; leaving stops it; repeats change nothing")
    func foregroundStartsAndStopsTheTick() async {
        let store = ControlledStore(InMemoryDocumentStore(document: Self.linkedDocument()))
        let sync = FakeSyncService(store: store.base)
        let scheduler = ManualSyncScheduler()
        let workspace = Workspace(store: store, sync: sync, tickScheduler: scheduler)
        await workspace.load()

        await workspace.setForegroundActive(true)
        await workspace.setForegroundActive(true)
        #expect(await sync.calls == [.start(Fixture.account), .request(.foreground)])
        #expect(scheduler.pendingDelays == [.seconds(15)])

        await scheduler.runNext()
        await scheduler.runNext()
        #expect(await sync.calls.suffix(2) == [.request(.periodic), .request(.periodic)])

        await workspace.setForegroundActive(false)
        await workspace.setForegroundActive(false)
        let calls = await sync.calls
        #expect(scheduler.pendingDelays.isEmpty)
        #expect(await scheduler.runNext() == false)
        #expect(await sync.calls == calls)

        await workspace.setForegroundActive(true)
        #expect(await sync.calls.last == .request(.foreground), "coming back asks for a pull again")
        #expect(scheduler.pendingDelays == [.seconds(15)])
    }

    @Test("021-FR-012 021-FR-016 021-FR-018 the snapshot dates waiting changes from when they became sendable and counts the first upload")
    func snapshotFromTheDocument() async throws {
        func create(_ id: TaskID, issuedAt: Date) -> PendingOperation {
            PendingOperation(command: .createTask(.init(taskID: id, title: "Task \(id)", list: .inbox)), issuedAt: issuedAt)
        }
        var document = Self.linkedDocument(
            outbox: [
                create("a", issuedAt: Fixture.epoch.addingTimeInterval(-213 * 86_400)),
                create("b", issuedAt: Fixture.epoch.addingTimeInterval(-3_600)),
                create("c", issuedAt: Fixture.epoch.addingTimeInterval(30)),
            ], issues: [Fixture.issue("Refused")])
        document.sync = SyncMetadata(
            lastPullAt: Fixture.epoch, lastPushAt: Fixture.epoch.addingTimeInterval(10),
            failingSince: Fixture.epoch.addingTimeInterval(100), lastFailedAttemptAt: Fixture.epoch.addingTimeInterval(170),
            lastFailureReferenceID: "ref-1")
        let session = await signedIn(document)
        let workspace = session.workspace

        var snapshot = workspace.syncSnapshot
        #expect(snapshot.account == .linked(email: "ana@example.com"))
        #expect(snapshot.pendingCount == 3)
        #expect(snapshot.oldestPendingAt == Fixture.epoch, "months-old changes wait from when the account was linked")
        #expect(snapshot.initialUploadRemaining == 2, "the two issued before the account was linked")
        #expect(snapshot.issueCount == 1)
        #expect(snapshot.lastSyncedAt == Fixture.epoch.addingTimeInterval(10))
        #expect(snapshot.failingSince == Fixture.epoch.addingTimeInterval(100))
        #expect(snapshot.lastFailedAttemptAt == Fixture.epoch.addingTimeInterval(170))
        #expect(snapshot.lastFailureReferenceID == "ref-1")
        #expect(snapshot.isOnline && !snapshot.isSyncing && !snapshot.sessionEnded)

        try workspace.capture(CaptureDraft(text: "Not on disk yet"))
        #expect(workspace.syncSnapshot.pendingCount == 4, "a change applied but not yet written counts")
        await session.sync.emit(.status(.syncing))
        #expect(workspace.syncSnapshot.isSyncing)
        await session.sync.emit(.status(.needsSignIn))
        #expect(workspace.syncSnapshot.sessionEnded)
        workspace.networkAvailabilityChanged(isAvailable: false)
        snapshot = workspace.syncSnapshot
        #expect(!snapshot.isOnline)

        let accountLess = await loadedWorkspace()
        try accountLess.capture(CaptureDraft(text: "On this device"))
        #expect(accountLess.syncSnapshot.account == .none)
        #expect(accountLess.syncSnapshot.pendingCount == 0, "account-less, nothing waits")
    }

    // MARK: Signing out, in order

    @Test("021-FR-018 021-FR-005 a sign-out whose removal fails keeps the token, sends no logout and leaves the person signed in")
    func failedRemovalKeepsTheSession() async throws {
        let world = World()
        let phone = WiredDevice(world: world, identity: .iOS, namespace: 1, store: DestroyFailingStore(InMemoryDocumentStore()))
        await phone.launch()
        try await phone.signIn()
        phone.fake.clearLog()

        await #expect(throws: WorkspaceError.self) { try await phone.workspace.signOut(discardUnsyncedChanges: false) }
        await phone.settle()

        #expect(try phone.tokens.token(for: FakeBrainBuddyServer.baseURL) != nil)
        #expect(try phone.tokens.pendingLogouts().isEmpty)
        #expect(phone.fake.requests.allSatisfy { $0.url.path != "/api/auth/logout" })
        #expect(phone.workspace.syncStatus != .needsSignIn)
        #expect(phone.workspace.account?.email == World.email)
        #expect(world.server.liveSessionCount(email: World.email) == 1)
    }

    @Test("021-FR-005 a sign-out that succeeds removes the data, the token and the server session")
    func signOutEndsTheSession() async throws {
        let world = World()
        let phone = WiredDevice(world: world, identity: .macOS(version: "0.1.0"), namespace: 1)
        await phone.launch()
        try await phone.signIn()
        phone.fake.clearLog()

        try await phone.workspace.signOut(discardUnsyncedChanges: false)

        #expect(try phone.tokens.token(for: FakeBrainBuddyServer.baseURL) == nil)
        #expect(try phone.tokens.pendingLogouts().isEmpty)
        #expect(phone.fake.requests.map { "\($0.method.rawValue) \($0.url.path)" } == ["POST /api/auth/logout"])
        #expect(world.server.liveSessionCount(email: World.email) == 0)
        #expect(try await phone.store.load() == nil)
        #expect(phone.workspace.account == nil)
    }

    @Test("021-FR-005 a crash between the removal and the token's removal still ends the session, once, at the next launch")
    func crashBetweenRemovalAndTokenRemoval() async throws {
        let world = World()
        let survivors = InMemorySessionTokenStore()
        let tokens = SnapshottingTokenStore(survivors)
        let first = WiredDevice(world: world, identity: .macOS(version: "0.1.0"), namespace: 1, tokens: tokens)
        await first.launch()
        try await first.signIn()
        // Offline, so this run never tells the server itself: whatever ends the session is the relaunch.
        await first.networkChanged(isAvailable: false)
        try await first.workspace.signOut(discardUnsyncedChanges: false)
        #expect(world.server.liveSessionCount(email: World.email) == 1)

        // The process died when the token was about to go: what remains is the copy taken then,
        // and the store, which the removal had already emptied.
        let relaunched = WiredDevice(
            world: world, identity: .macOS(version: "0.1.0"), namespace: 2, store: InMemoryDocumentStore(), tokens: survivors)
        #expect(try survivors.token(for: FakeBrainBuddyServer.baseURL) != nil)
        #expect(try survivors.pendingLogouts().count == 1)
        await relaunched.launch()

        #expect(relaunched.fake.requests.map { "\($0.method.rawValue) \($0.url.path)" } == ["POST /api/auth/logout"])
        #expect(world.server.liveSessionCount(email: World.email) == 0)
        #expect(try survivors.pendingLogouts().isEmpty)
        #expect(try survivors.token(for: FakeBrainBuddyServer.baseURL) == nil)
    }

    // MARK: First load

    @Test("021-FR-012 021-FR-032 with the first pull held open, local work answers at once and the line reads Not synced yet")
    func firstLoadDoesNotBlock() async throws {
        let world = World()
        let mac = WiredDevice(
            world: world, identity: .macOS(version: "0.1.0"), namespace: 1, wrapping: { HeldPullTransport($0) })
        await mac.launch()
        let transport = try #require(mac.transport as? HeldPullTransport)
        let signIn = Task { try await mac.workspace.signIn(serverURL: FakeBrainBuddyServer.baseURL, email: World.email, password: World.password) }
        await transport.arrived()

        // The pull has not answered: commands and queries still do.
        let id = try mac.workspace.capture(CaptureDraft(text: "Written while loading", list: .next))
        #expect(mac.workspace.task(id)?.title == "Written while loading")
        #expect(mac.workspace.list(.list(.next)).sections.flatMap(\.tasks).map(\.id) == [id])
        let line = SyncStatusDescriber.describe(
            mac.workspace.syncSnapshot, now: world.clock.now(), device: .mac, calendar: Calendar(identifier: .gregorian))
        #expect(line.text == "Not synced yet")
        #expect(line.state == .notSyncedYet)

        await transport.release()
        try await signIn.value
        await mac.settle()
        await mac.workspace.syncNow()
        #expect(world.snapshot.task(titled: "Written while loading") != nil)
        let synced = SyncStatusDescriber.describe(
            mac.workspace.syncSnapshot, now: world.clock.now(), device: .mac, calendar: Calendar(identifier: .gregorian))
        #expect(synced.text == "Synced just now")
    }
}

/// Holds the first task pull until `release()`, so a test can act while a first load is in flight.
final class HeldPullTransport: HTTPTransport {
    private actor Gate {
        var arrived = false
        var isOpen = false
        var arrivalWaiters: [CheckedContinuation<Void, Never>] = []
        var waiters: [CheckedContinuation<Void, Never>] = []

        func arrive() {
            arrived = true
            arrivalWaiters.forEach { $0.resume() }
            arrivalWaiters = []
        }

        func waitForArrival() async {
            if arrived { return }
            await withCheckedContinuation { arrivalWaiters.append($0) }
        }

        func waitUntilOpen() async {
            if isOpen { return }
            await withCheckedContinuation { waiters.append($0) }
        }

        func open() {
            isOpen = true
            waiters.forEach { $0.resume() }
            waiters = []
        }
    }

    private let inner: any HTTPTransport
    private let gate = Gate()
    private let holding = Mutex(true)

    init(_ inner: any HTTPTransport) { self.inner = inner }

    func arrived() async { await gate.waitForArrival() }
    func release() async { await gate.open() }

    func send(_ request: HTTPRequest) async throws -> HTTPResponse {
        let isPull = request.method == .get && request.url.path.hasSuffix("/tasks")
        let firstPull = isPull && holding.withLock { first in
            defer { first = false }
            return first
        }
        if firstPull {
            await gate.arrive()
            await gate.waitUntilOpen()
        }
        return try await inner.send(request)
    }
}

/// A store whose removal fails like a full disk; everything else is its base.
actor DestroyFailingStore: DocumentStore {
    let base: any DocumentStore

    init(_ base: any DocumentStore) { self.base = base }

    func load() async throws(DocumentStoreError) -> StoreDocument? { try await base.load() }

    func update(_ transform: @Sendable (inout StoreDocument) throws -> Void) async throws -> StoreDocument {
        try await base.update(transform)
    }

    func generation() async throws(DocumentStoreError) -> Int? { try await base.generation() }
    func destroy() async throws(DocumentStoreError) { throw DocumentStoreError.io("disk full") }
    func destroy(after check: @Sendable (StoreDocument?) throws -> Void) async throws { throw DocumentStoreError.io("disk full") }
    func storedAccount() async -> LinkedAccount? { await base.storedAccount() }
    func quarantineUnreadableDocument() async throws(DocumentStoreError) -> URL? { try await base.quarantineUnreadableDocument() }
}

/// A token store that copies what it holds into `survivors` the moment a token is about to be removed:
/// what a crash at that point would leave in the Keychain.
final class SnapshottingTokenStore: SessionTokenStore {
    private let inner = InMemorySessionTokenStore()
    private let survivors: InMemorySessionTokenStore

    init(_ survivors: InMemorySessionTokenStore) { self.survivors = survivors }

    func token(for serverURL: URL) throws -> String? { try inner.token(for: serverURL) }
    func setToken(_ token: String, for serverURL: URL) throws { try inner.setToken(token, for: serverURL) }

    func removeToken(for serverURL: URL) throws {
        if let token = try inner.token(for: serverURL) { try survivors.setToken(token, for: serverURL) }
        for logout in try inner.pendingLogouts() { try survivors.addPendingLogout(logout) }
        try inner.removeToken(for: serverURL)
    }

    func removeAllTokens() throws { try inner.removeAllTokens() }
    func pendingLogouts() throws -> [PendingLogout] { try inner.pendingLogouts() }
    func addPendingLogout(_ logout: PendingLogout) throws { try inner.addPendingLogout(logout) }
    func removePendingLogout(_ logout: PendingLogout) throws { try inner.removePendingLogout(logout) }
}
