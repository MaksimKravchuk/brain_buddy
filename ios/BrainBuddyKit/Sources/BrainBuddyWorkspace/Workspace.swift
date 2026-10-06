import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyPersistence
import BrainBuddySync
import Foundation
import Observation

/// The app's single source of truth on the main actor. SwiftUI views read
/// `state` and the query helpers; every write goes through a command method,
/// which validates and applies the change in memory at once (no network, no
/// waiting), then persists it and queues it for sync in the background.
///
/// PUBLIC API CONTRACT: the SwiftUI app, widgets and App Intents are written
/// against these signatures. Implementations may add members but must not
/// change or remove these.
///
/// How it works: the workspace keeps the last known `StoreDocument` and the
/// commands applied since that are not on disk yet (`unpersisted`). `state` is
/// always `OutboxReplayer.replay(document.outbox + unpersisted, onto: document.base).state`.
/// A command is applied to `state` directly (no replay); a document written
/// by someone else (sync, a widget, an App Intent) is adopted with a full
/// replay, so pending local changes stay visible on top of it. Writes run one
/// at a time, in order, each appending the queued commands through
/// `OutboxCompactor` under the store's lock.
///
/// After compaction folds a command into an earlier one, fields the server
/// assigns when a request lands (`updatedAt`, a new task's `orderKey`,
/// `waitingSince`, a comment's `editedAt`) can differ from a fresh replay
/// until the next full replay (see `OutboxCompactor`).
@MainActor
@Observable
public final class Workspace {
    // MARK: Observable state

    /// Current state: server base plus replayed local changes.
    public private(set) var state: GTDState = .empty
    public private(set) var isLoaded = false
    /// Set when the stored file cannot be read; the UI offers recovery.
    public private(set) var loadError: String?
    public private(set) var account: LinkedAccount?
    public private(set) var syncStatus: SyncStatus = .localOnly
    /// Local changes the server rejected, shown in Settings › Sync.
    public private(set) var issues: [SyncIssue] = []
    /// Local changes not yet acknowledged by the server.
    public private(set) var pendingChangeCount = 0
    /// Set while the latest changes could not be written to this device's
    /// store (`WorkspaceError.storage`'s message). The changes stay applied in
    /// memory and are written again with the next change or `flush()`;
    /// cleared by the next successful write.
    public private(set) var storageError: String?
    /// True after a sign-in that cancelled the account's pending deletion
    /// (signing in during the grace period does that). The app tells the
    /// person, then calls `acknowledgeAccountDeletionNotice()`.
    public private(set) var signInCancelledAccountDeletion = false

    /// Called on the main actor after each successful write to the store, and
    /// after sign-out removed it. The app reloads widget timelines here.
    @ObservationIgnored public var didPersist: (@MainActor () -> Void)?

    // MARK: Collaborators

    let store: any DocumentStore
    let sync: (any SyncService)?
    let now: @Sendable () -> Date
    let makeID: @Sendable () -> UUID

    // MARK: Internal state (not observed)

    /// The document as last read or written.
    @ObservationIgnored private(set) var document = StoreDocument()
    /// Commands applied to `state` but not written yet, oldest first.
    @ObservationIgnored private(set) var unpersisted: [PendingOperation] = []
    /// Document edits that are not commands (device-local review state,
    /// local retention), applied in order with the next write (spec 020).
    @ObservationIgnored var pendingEdits: [@Sendable (inout StoreDocument) -> Void] = []
    /// What the app's `NWPathMonitor` last reported.
    @ObservationIgnored var networkIsAvailable = true
    /// The account-less release switch (`BBWeeklyReviewLocal`, ios-commands §8).
    @ObservationIgnored public var accountlessReviewEnabled = false
    /// The device's current zone (`TimeZone.current`; tests inject one).
    @ObservationIgnored public var deviceTimeZone: @Sendable () -> TimeZone = { TimeZone.current }
    /// Issues the user dismissed that are not removed on disk yet.
    @ObservationIgnored private var pendingDismissals: Set<SyncIssue.ID> = []
    /// The write loop, while it runs. Writes never overlap or reorder.
    @ObservationIgnored private var writer: Task<Void, Never>?
    @ObservationIgnored private var writerToken = 0
    /// True while a store write is in flight: documents read meanwhile wait
    /// in `deferredDocument`, so the commands being written are never
    /// applied twice (once from the new document, once from `unpersisted`).
    @ObservationIgnored private var isWriting = false
    @ObservationIgnored private var deferredDocument: StoreDocument?
    /// Set during sign-out: nothing new is written for the old account.
    @ObservationIgnored private var writesSuspended = false
    /// Bumped when the workspace is reset, so results of work started
    /// before (a load, a write) are discarded.
    @ObservationIgnored private var epoch = 0
    @ObservationIgnored private var loadTask: Task<Void, Never>?
    @ObservationIgnored private var hasEventHandler = false
    /// The account the sync service was started (or signed in) for.
    @ObservationIgnored private var syncStartedFor: String?
    @ObservationIgnored private var isSigningIn = false
    @ObservationIgnored private var nativeSignInID: UUID?
    @ObservationIgnored private var networkUpdates: Task<Void, Never>?
    @ObservationIgnored private var todayCache: TodayCache?
    /// How many times `state` was rebuilt by a full replay (for tests).
    @ObservationIgnored private(set) var fullReplayCount = 0

    // MARK: Construction

    /// A workspace over `store`. Pass `sync: nil` where nothing may talk to
    /// the server (widgets, App Intents, previews). `now` and `makeID` are the
    /// clock and the id source for new commands (ids, operation ids and
    /// idempotency keys); tests inject deterministic ones.
    public init(
        store: any DocumentStore, sync: (any SyncService)?,
        now: @escaping @Sendable () -> Date = { Date() },
        makeID: @escaping @Sendable () -> UUID = { UUID() }
    ) {
        self.store = store
        self.sync = sync
        self.now = now
        self.makeID = makeID
    }

    /// Production workspace backed by the shared App Group file. Extensions
    /// pass `enableSync: false`; only the app talks to the server.
    public static func live(appGroupID: String, enableSync: Bool = true) -> Workspace {
        #if canImport(Darwin)
            let fileURL =
                FileDocumentStore.appGroupDocumentURL(appGroupID: appGroupID)
                ?? FileDocumentStore.applicationSupportDocumentURL()
        #else
            let fileURL = FileDocumentStore.applicationSupportDocumentURL()
        #endif
        let store = FileDocumentStore(fileURL: fileURL)
        guard enableSync else { return Workspace(store: store, sync: nil) }
        #if canImport(Security)
            let tokenStore: any SessionTokenStore = KeychainSessionTokenStore()
        #else
            let tokenStore: any SessionTokenStore = InMemorySessionTokenStore()
        #endif
        return Workspace(store: store, sync: SyncEngine(store: store, tokenStore: tokenStore))
    }

    /// In-memory workspace with sample data for SwiftUI previews and UI tests.
    public static func preview() -> Workspace {
        let document = SampleData.document(now: Date())
        let workspace = Workspace(store: InMemoryDocumentStore(document: document), sync: nil)
        workspace.adoptLoaded(document)
        return workspace
    }

    /// Loads (or creates) the stored document and starts sync if an account is linked.
    ///
    /// A missing document is an empty workspace in memory; the file is only
    /// created by the first write. An unreadable one sets `loadError` and is
    /// left untouched (see `resetUnreadableStore()`). Concurrent calls share
    /// one load.
    public func load() async {
        if let loadTask { return await loadTask.value }
        let task = Task {
            await self.performLoad()
            self.loadTask = nil
        }
        loadTask = task
        await task.value
    }

    /// Picks up writes made by another process (widget, App Intent). Call on
    /// scene activation and when the shared-store change notification fires.
    ///
    /// When nothing changed it only reads the stored generation (no decode of
    /// the document, no replay). Changes not written yet stay applied on top.
    /// Before the first successful load it loads instead.
    ///
    /// Changes the other process queued are local changes of this device, and
    /// only the app syncs, so they get the same debounced sync as the app's own.
    public func reloadIfChangedExternally() async {
        guard isLoaded, loadError == nil else { return await load() }
        let known = Set((document.outbox + unpersisted).map(\.id))
        guard let reloaded = await refreshFromStore() else { return }
        if let sync, account != nil, reloaded.outbox.contains(where: { !known.contains($0.id) }) {
            await sync.request(.localChange)
        }
    }

    /// Waits until every change applied so far is on disk. When the last
    /// write failed, it tries once more; `storageError` says whether that worked.
    public func flush() async {
        if let writer { await writer.value }
        schedulePersistence()
        if let writer { await writer.value }
    }

    /// Sets an unreadable or too-new store document aside (it is kept next to
    /// the store, not deleted, until the next sign-out removes it) and starts
    /// from an empty one. Call it only after the person confirmed. Returns
    /// where the old document now is.
    ///
    /// The fresh start is linked to no account, so the stored session of the
    /// set-aside document's account is logged out (best effort) and forgotten.
    @discardableResult
    public func resetUnreadableStore() async -> URL? {
        if let loadTask { await loadTask.value }
        let setAsideAccount = await store.storedAccount()
        let quarantined: URL?
        do {
            quarantined = try await store.quarantineUnreadableDocument()
        } catch {
            loadError = error.message
            return nil
        }
        if quarantined != nil, let sync { await sync.discardStaleSessions(loggingOut: setAsideAccount) }
        await load()
        return quarantined
    }

    // MARK: Reading

    /// The device's current local calendar day, used by date views. Cached
    /// until the next local midnight (and for at most a minute, in case the
    /// time zone changes), because views ask for it on every render.
    public var today: CalendarDay {
        let instant = now()
        if let cache = todayCache, cache.validFrom <= instant, instant < cache.validUntil { return cache.day }
        let day = CalendarDay(date: instant)
        let validUntil = min(day.adding(days: 1).startDate(), instant.addingTimeInterval(60))
        todayCache = validUntil > instant ? TodayCache(day: day, validFrom: instant, validUntil: validUntil) : nil
        return day
    }

    public func list(_ destination: Destination, options: ListOptions = ListOptions()) -> TaskListResult {
        GTDQueries.list(destination, options: options, in: state, today: today)
    }

    public func counts() -> ListCounts { GTDQueries.counts(in: state, today: today) }
    public func task(_ id: TaskID) -> TaskRecord? { state.tasks[id] }
    public func project(_ id: ProjectID) -> ProjectRecord? { state.projects[id] }
    public func tag(_ id: TagID) -> TagRecord? { state.tags[id] }
    public func projects(archived: Bool = false) -> [ProjectSummary] { GTDQueries.projects(in: state, archived: archived) }
    public func tags() -> [TagSummary] { GTDQueries.tags(in: state) }
    public func capturePreview(_ draft: CaptureDraft) -> CapturePreview { CapturePlanner.preview(draft, in: state) }

    /// True when `comment` was written by the signed-in user (or on this device).
    public func isOwnComment(_ comment: CommentRecord) -> Bool {
        comment.authorID == nil || comment.authorID == account?.id || account == nil
    }

    // MARK: Writing (synchronous, offline, validated)

    /// Captures one task from a Smart Add draft; creates missing projects/tags.
    @discardableResult
    public func capture(_ draft: CaptureDraft) throws(GTDValidationError) -> TaskID {
        let makeID = self.makeID
        let plan = try CapturePlanner.plan(
            draft, in: state,
            makeTaskID: { TaskID(Self.rawID(makeID())) },
            makeProjectID: { ProjectID(Self.rawID(makeID())) },
            makeTagID: { TagID(Self.rawID(makeID())) }
        )
        try perform(plan.commands)
        return plan.taskID
    }

    public func updateTask(_ id: TaskID, _ changes: TaskChanges) throws(GTDValidationError) {
        try perform(.updateTask(.init(taskID: id, changes: changes)))
    }

    /// Moves an open task to another open list; Waiting requires `waitingFor`.
    public func moveTask(_ id: TaskID, to list: OpenList, waitingFor: String? = nil) throws(GTDValidationError) {
        try perform(.transitionTask(.init(taskID: id, action: .move, toList: list, waitingFor: waitingFor)))
    }

    public func completeTask(_ id: TaskID) throws(GTDValidationError) {
        try perform(.transitionTask(.init(taskID: id, action: .complete)))
    }

    public func cancelTask(_ id: TaskID) throws(GTDValidationError) {
        try perform(.transitionTask(.init(taskID: id, action: .cancel)))
    }

    /// Reopens a completed or cancelled task into an explicit open list.
    public func reopenTask(_ id: TaskID, to list: OpenList, waitingFor: String? = nil) throws(GTDValidationError) {
        try perform(.transitionTask(.init(taskID: id, action: .reopen, toList: list, waitingFor: waitingFor)))
    }

    @discardableResult
    public func addSubtask(to taskID: TaskID, title: String) throws(GTDValidationError) -> SubtaskID {
        let subtaskID = SubtaskID(Self.rawID(makeID()))
        try perform(.createSubtask(.init(taskID: taskID, subtaskID: subtaskID, title: title)))
        return subtaskID
    }

    public func renameSubtask(_ subtaskID: SubtaskID, in taskID: TaskID, to title: String) throws(GTDValidationError) {
        try perform(.updateSubtask(.init(taskID: taskID, subtaskID: subtaskID, title: title)))
    }

    public func transitionSubtask(
        _ subtaskID: SubtaskID, in taskID: TaskID, _ action: SubtaskTransitionAction
    ) throws(GTDValidationError) {
        try perform(.transitionSubtask(.init(taskID: taskID, subtaskID: subtaskID, action: action)))
    }

    @discardableResult
    public func addComment(to taskID: TaskID, body: String) throws(GTDValidationError) -> CommentID {
        let commentID = CommentID(Self.rawID(makeID()))
        try perform(.createComment(.init(taskID: taskID, commentID: commentID, body: body)))
        return commentID
    }

    public func editComment(_ commentID: CommentID, in taskID: TaskID, body: String) throws(GTDValidationError) {
        try perform(.updateComment(.init(taskID: taskID, commentID: commentID, body: body)))
    }

    @discardableResult
    public func createProject(name: String, color: String? = nil) throws(GTDValidationError) -> ProjectID {
        let projectID = ProjectID(Self.rawID(makeID()))
        try perform(.createProject(.init(projectID: projectID, name: name, color: color)))
        return projectID
    }

    public func renameProject(_ id: ProjectID, to name: String) throws(GTDValidationError) {
        try perform(.updateProject(.init(projectID: id, name: name)))
    }

    public func setProjectColor(_ id: ProjectID, color: String?) throws(GTDValidationError) {
        try perform(.updateProject(.init(projectID: id, color: color.map { .set($0) } ?? .clear)))
    }

    /// Archives a project. Like the server today, this removes the project
    /// from all of its tasks; the tasks stay in their lists. There is no unarchive.
    public func archiveProject(_ id: ProjectID) throws(GTDValidationError) {
        try perform(.archiveProject(id))
    }

    @discardableResult
    public func createTag(name: String) throws(GTDValidationError) -> TagID {
        let tagID = TagID(Self.rawID(makeID()))
        try perform(.createTag(.init(tagID: tagID, name: name)))
        return tagID
    }

    public func renameTag(_ id: TagID, to name: String) throws(GTDValidationError) {
        try perform(.renameTag(.init(tagID: id, name: name)))
    }

    /// Deletes a tag and removes it from every task; the tasks stay.
    public func deleteTag(_ id: TagID) throws(GTDValidationError) {
        try perform(.deleteTag(id))
    }

    // MARK: Account and sync

    /// Signs in and links this device's data to the account. Local-only data
    /// is uploaded; the account's existing data is downloaded and merged.
    ///
    /// - Throws: `WorkspaceError.invalidServerURL` for an address that is not
    ///   https (or http on localhost), `.signInFailed` with the server's
    ///   words otherwise (always, in a workspace without sync).
    public func signIn(serverURL: URL, email: String, password: String) async throws {
        guard let url = BrainBuddyAPI.serverURL(from: serverURL.absoluteString) else {
            throw WorkspaceError.invalidServerURL
        }
        guard let sync else {
            throw WorkspaceError.signInFailed(message: "Sign in from the Brain Buddy app.", referenceID: nil)
        }
        // The engine uploads what is in the store, so everything must be there.
        await flush()
        if account == nil { try await convertLocalAutoParksForLinking() }
        await installEventHandlerIfNeeded(sync)
        isSigningIn = true
        let linked: LinkedAccount
        do {
            let result = try await sync.signInWithResult(serverURL: url, email: email, password: password)
            linked = result.account
            if result.deletionCancelled { signInCancelledAccountDeletion = true }
        } catch {
            isSigningIn = false
            refreshDerivedState()
            throw WorkspaceError.signInFailed(message: error.message, referenceID: error.referenceID)
        }
        syncStartedFor = linked.id
        // The engine linked the account in the document; pick that up if its
        // event has not arrived yet.
        await refreshFromStore()
        isSigningIn = false
        refreshDerivedState()
        if account != linked { account = linked }
        if syncStatus == .localOnly { syncStatus = .idle(lastSyncedAt: document.sync.lastPullAt) }
    }

    /// Additive iOS authentication; legacy password callers keep their contract.
    public func beginSignIn(serverURL: URL) async throws -> NativeSignInAttempt {
        guard let sync else { throw WorkspaceError.signInFailed(message: "Sign in from the Brain Buddy app.", referenceID: nil) }
        await flush()
        await installEventHandlerIfNeeded(sync)
        do {
            let attempt = try await sync.beginSignIn(serverURL: serverURL)
            nativeSignInID = attempt.id
            return attempt
        } catch {
            throw WorkspaceError.signInFailed(message: error.message, referenceID: error.referenceID)
        }
    }

    public func completeSignIn(_ attempt: NativeSignInAttempt, credential: NativeSignInCredential) async throws -> NativeSignInOutcome {
        guard let sync, nativeSignInID == attempt.id else { throw WorkspaceError.signInFailed(message: "Start a fresh sign-in. Your local tasks are kept.", referenceID: nil) }
        await flush()
        guard nativeSignInID == attempt.id else { throw WorkspaceError.signInFailed(message: "This sign-in was cancelled.", referenceID: nil) }
        isSigningIn = true
        do {
            let outcome = try await sync.completeSignIn(attempt, credential: credential)
            guard nativeSignInID == attempt.id else { throw WorkspaceError.signInFailed(message: "This sign-in was cancelled.", referenceID: nil) }
            if case .signedIn(let result) = outcome {
                syncStartedFor = result.account.id
                if result.deletionCancelled { signInCancelledAccountDeletion = true }
                await refreshFromStore()
                guard nativeSignInID == attempt.id else { throw WorkspaceError.signInFailed(message: "This sign-in was cancelled.", referenceID: nil) }
                nativeSignInID = nil
            }
            isSigningIn = false
            refreshDerivedState()
            return outcome
        } catch {
            if nativeSignInID == attempt.id {
                isSigningIn = false
                refreshDerivedState()
            }
            if let failure = error as? SignInFailure { throw WorkspaceError.signInFailed(message: failure.message, referenceID: failure.referenceID) }
            throw error
        }
    }

    public func cancelSignIn(_ attempt: NativeSignInAttempt) async {
        if nativeSignInID == attempt.id { nativeSignInID = nil; isSigningIn = false }
        await sync?.cancelSignIn(attempt)
        refreshDerivedState()
    }

    /// Acknowledges `signInCancelledAccountDeletion` once the person was told.
    public func acknowledgeAccountDeletionNotice() {
        if signInCancelledAccountDeletion { signInCancelledAccountDeletion = false }
    }

    /// Signs out and removes the account's data from this device. Fails with
    /// `WorkspaceError.unsyncedChanges` unless `discardUnsyncedChanges` is set
    /// while changes are still pending, counting those a widget or App Intent
    /// queued in the store that this workspace has not picked up yet.
    public func signOut(discardUnsyncedChanges: Bool) async throws {
        if pendingChangeCount > 0, !discardUnsyncedChanges {
            throw WorkspaceError.unsyncedChanges(count: pendingChangeCount)
        }
        nativeSignInID = nil
        isSigningIn = false
        // Let a write in flight finish, and write nothing new for this account.
        writesSuspended = true
        if let writer { await writer.value }
        if !discardUnsyncedChanges {
            // Another process may have queued changes since the last reload.
            let unsynced = unpersisted.count + ((try? await store.load())?.outbox.count ?? 0)
            if unsynced > 0 {
                writesSuspended = false
                await refreshFromStore()
                schedulePersistence()
                throw WorkspaceError.unsyncedChanges(count: unsynced)
            }
        }
        await sync?.signOut()
        do {
            // Checked again under the store's lock, so nothing queued in between is lost.
            let unpersistedCount = unpersisted.count
            let discard = discardUnsyncedChanges
            try await store.destroy(after: { stored in
                let unsynced = unpersistedCount + (stored?.outbox.count ?? 0)
                if unsynced > 0, !discard { throw WorkspaceError.unsyncedChanges(count: unsynced) }
            })
        } catch {
            writesSuspended = false
            await refreshFromStore()
            schedulePersistence()
            // The account stays linked but its session was ended: sync starts
            // again and asks to sign in again.
            syncStartedFor = nil
            await startSyncIfNeeded()
            if let error = error as? WorkspaceError { throw error }
            throw WorkspaceError.storage(Self.storageMessage(for: error))
        }
        resetToEmptyLocalWorkspace()
        writesSuspended = false
        didPersist?()
    }

    /// Pushes pending changes and pulls the latest server state now.
    public func syncNow() async {
        guard let sync, account != nil else { return }
        await flush()
        let status = await sync.syncNow()
        if account != nil, syncStatus != status { syncStatus = status }
        // The engine reports its writes as events; this catches up if one was missed.
        await refreshFromStore()
    }

    /// Loads subtasks and comments for a task from the server (when online);
    /// call when a task detail opens.
    public func refreshTaskDetails(_ id: TaskID) async {
        guard let sync, account != nil else { return }
        await sync.refreshTask(id)
    }

    public func dismissIssue(_ id: SyncIssue.ID) {
        guard document.issues.contains(where: { $0.id == id }) else { return }
        pendingDismissals.insert(id)
        issues.removeAll { $0.id == id }
        schedulePersistence()
    }

    /// Informs the sync scheduler about connectivity (from NWPathMonitor in the app).
    public func networkAvailabilityChanged(isAvailable: Bool) {
        networkIsAvailable = isAvailable
        guard let sync else { return }
        // Chained, so the engine sees the changes in the order they happened.
        let previous = networkUpdates
        networkUpdates = Task {
            await previous?.value
            await sync.setNetworkAvailable(isAvailable)
            if isAvailable { await sync.request(.networkRestored) }
        }
    }

    /// Waits until the connectivity updates sent so far reached the sync service.
    func waitForNetworkUpdates() async {
        await networkUpdates?.value
    }
}

// MARK: - Applying commands

extension Workspace {
    func perform(_ command: GTDCommand) throws(GTDValidationError) {
        try perform([command])
    }

    /// Applies `commands` all-or-nothing to `state`, queues them, and starts
    /// a write. A rejected command leaves everything untouched. Once the
    /// review is exposed, every command that may start a formulation carries
    /// a client formulation id minted here (spec 020), sent as
    /// `new_formulation_id`, so device and server name the same formulation.
    /// Before that the reducer derives one (no id is drawn, so nothing else
    /// changes while the feature is off).
    func perform(_ commands: [GTDCommand]) throws(GTDValidationError) {
        let issuedAt = Self.storedPrecision(now())
        let makeID = self.makeID
        let commands =
            reviewExposed ? commands.map { Self.stampingFormulationID($0) { FormulationID.make(makeID()) } } : commands
        var next = state
        for command in commands {
            try GTDReducer.apply(command, at: issuedAt, to: &next, mode: .interactive)
        }
        ReviewActivation.apply(
            to: &next, activatedAt: next.review.settings.activatedAt ?? local.activatedAt,
            startsMissingClocks: next.review.server == nil
        )
        state = next
        for command in commands {
            unpersisted.append(
                PendingOperation(id: makeID(), command: command, issuedAt: issuedAt, idempotencyKey: makeID())
            )
        }
        pendingChangeCount = document.outbox.count + unpersisted.count
        schedulePersistence()
    }

    /// `command` with a fresh `form_<uuid>` where it may start a formulation
    /// and has none.
    nonisolated static func stampingFormulationID(
        _ command: GTDCommand, _ makeFormulationID: () -> FormulationID
    ) -> GTDCommand {
        switch command {
        case .createTask(var create) where create.list == .next && create.newFormulationID == nil:
            create.newFormulationID = makeFormulationID()
            return .createTask(create)
        case .updateTask(var update) where update.changes.title.isChanged && update.newFormulationID == nil:
            update.newFormulationID = makeFormulationID()
            return .updateTask(update)
        case .transitionTask(var transition)
        where transition.toList == .next && (transition.action == .move || transition.action == .reopen)
            && transition.newFormulationID == nil:
            transition.newFormulationID = makeFormulationID()
            return .transitionTask(transition)
        default:
            return command
        }
    }

    /// A client id in the same form as `EntityID.random()`.
    nonisolated static func rawID(_ uuid: UUID) -> String { uuid.uuidString.lowercased() }

    /// `date` as the store keeps it (whole microseconds, rounded the way
    /// `StoreDocumentCoding` rounds), so a command applied in memory gives
    /// exactly what replaying the stored command gives.
    nonisolated static func storedPrecision(_ date: Date) -> Date {
        let interval = date.timeIntervalSinceReferenceDate
        guard interval.isFinite else { return date }
        var whole = interval.rounded(.down)
        var microseconds = ((interval - whole) * 1_000_000).rounded()
        if microseconds == 1_000_000 {
            whole += 1
            microseconds = 0
        }
        return Date(timeIntervalSinceReferenceDate: whole + microseconds / 1_000_000)
    }
}

// MARK: - Persistence

extension Workspace {
    private var hasPendingWrites: Bool { !unpersisted.isEmpty || !pendingDismissals.isEmpty || !pendingEdits.isEmpty }

    /// Queues a document edit that is not a command and starts a write.
    func edit(_ change: @escaping @Sendable (inout StoreDocument) -> Void) {
        pendingEdits.append(change)
        schedulePersistence()
    }

    /// Starts the write loop unless it is running (it picks up new changes
    /// itself) or there is nothing to write.
    func schedulePersistence() {
        guard writer == nil, hasPendingWrites, !writesSuspended else { return }
        writerToken += 1
        let token = writerToken
        let epoch = self.epoch
        writer = Task {
            let succeeded = await self.drainWrites(epoch: epoch)
            guard self.writerToken == token else { return }
            self.writer = nil
            // Changes queued after a reset still need writing; after a
            // failure, the next change or `flush()` retries.
            if succeeded { self.schedulePersistence() }
        }
    }

    /// Writes queued changes one batch at a time, in order, until none are
    /// left. Returns false when a write failed; its changes stay queued.
    private func drainWrites(epoch: Int) async -> Bool {
        while hasPendingWrites, !writesSuspended, epoch == self.epoch {
            let operations = unpersisted
            let dismissals = pendingDismissals
            let edits = pendingEdits
            isWriting = true
            let result = await write(operations, dismissing: dismissals, edits: edits, clockAware: reviewExposed)
            isWriting = false
            guard epoch == self.epoch else { return true }
            switch result {
            case .failure(let error):
                let message = WorkspaceError.storage(Self.storageMessage(for: error)).message
                if storageError != message { storageError = message }
                adoptDeferredDocument()
                return false
            case .success(let written):
                unpersisted.removeFirst(operations.count)
                pendingDismissals.subtract(dismissals)
                pendingEdits.removeFirst(edits.count)
                if storageError != nil { storageError = nil }
                adoptWritten(written, recomputing: !edits.isEmpty)
                adoptDeferredDocument()
                didPersist?()
                if !operations.isEmpty, let sync { await sync.request(.localChange) }
            }
        }
        return true
    }

    /// One read-modify-write under the store's lock (the file store keeps the
    /// process from being suspended while it holds the lock).
    private func write(
        _ operations: [PendingOperation], dismissing dismissals: Set<SyncIssue.ID>,
        edits: [@Sendable (inout StoreDocument) -> Void], clockAware: Bool
    ) async -> Result<StoreDocument, any Error> {
        do {
            let written = try await store.update { document in
                for operation in operations {
                    document.outbox = OutboxCompactor.appending(operation, to: document.outbox, clockAware: clockAware)
                }
                if !dismissals.isEmpty { document.issues.removeAll { dismissals.contains($0.id) } }
                for edit in edits { edit(&document) }
            }
            return .success(written)
        } catch {
            return .failure(error)
        }
    }

    /// Adopts the document this workspace just wrote. When nobody else wrote
    /// in between, it is the held document plus the written commands, which
    /// `state` already shows: no replay needed.
    private func adoptWritten(_ written: StoreDocument, recomputing: Bool = false) {
        let expectedGeneration = document.generation + 1
        document = written
        if recomputing || written.generation != expectedGeneration { recomputeState() }
        refreshDerivedState()
    }

    nonisolated static func storageMessage(for error: any Error) -> String {
        if let error = error as? DocumentStoreError { return error.message }
        return "Your latest changes couldn't be saved on this device yet. They're kept and saved with your next change."
    }
}

// MARK: - Adopting documents

extension Workspace {
    /// Takes a document read from the store or reported by sync, if it is
    /// newer than the held one: every write increments the generation, so an
    /// older or equal one is a late event or a read that started before one of
    /// our own writes landed. While a write is in flight it waits for that
    /// write, so the commands being written are not applied twice.
    private func receive(_ incoming: StoreDocument) {
        guard incoming.generation > document.generation else { return }
        guard !isWriting else {
            if incoming.generation > deferredDocument?.generation ?? Int.min { deferredDocument = incoming }
            return
        }
        adopt(incoming)
    }

    private func adoptDeferredDocument() {
        guard let deferred = deferredDocument else { return }
        deferredDocument = nil
        if deferred.generation > document.generation { adopt(deferred) }
    }

    private func adopt(_ incoming: StoreDocument) {
        document = incoming
        recomputeState()
        refreshDerivedState()
    }

    /// Shows `document` as loaded, synchronously (previews).
    func adoptLoaded(_ loaded: StoreDocument) {
        adopt(loaded)
        isLoaded = true
    }

    /// Rebuilds `state` from the document and the unwritten commands.
    private func recomputeState() {
        fullReplayCount += 1
        var replayed = OutboxReplayer.replay(document.outbox + unpersisted, onto: document.base, activatedAt: local.activatedAt).state
        ReviewSessionUpkeep.closeIdle(local.idleClosedSessions, in: &replayed)
        if replayed != state { state = replayed }
    }

    /// Everything derived from `document` except `state`. Assigns only what
    /// changed, so views are not invalidated for nothing.
    private func refreshDerivedState() {
        if account != document.account { account = document.account }
        let visibleIssues = document.issues.filter { !pendingDismissals.contains($0.id) }
        if issues != visibleIssues { issues = visibleIssues }
        let pending = document.outbox.count + unpersisted.count
        if pendingChangeCount != pending { pendingChangeCount = pending }
        if account == nil {
            if !isSigningIn, syncStatus != .localOnly { syncStatus = .localOnly }
        } else if syncStatus == .localOnly {
            syncStatus = .idle(lastSyncedAt: document.sync.lastPullAt)
        }
    }

    /// Adopts the stored document when it is newer than the held one, and
    /// returns it (nil when there was nothing newer to read).
    @discardableResult
    func refreshFromStore() async -> StoreDocument? {
        let storedGeneration: Int?
        do {
            storedGeneration = try await store.generation()
        } catch {
            return nil
        }
        guard let storedGeneration, storedGeneration > document.generation else { return nil }
        let loaded: StoreDocument?
        do {
            loaded = try await store.load()
        } catch {
            return nil
        }
        if let loaded { receive(loaded) }
        return loaded
    }

    private func performLoad() async {
        let epoch = self.epoch
        let loaded: StoreDocument?
        do {
            loaded = try await store.load()
        } catch {
            guard epoch == self.epoch else { return }
            loadError = error.message
            isLoaded = true
            return
        }
        guard epoch == self.epoch else { return }
        if loadError != nil { loadError = nil }
        if let loaded { receive(loaded) }
        isLoaded = true
        // A command issued before loading may be writing; the document (and
        // with it the account) is adopted once that write lands.
        if let writer { await writer.value }
        await startSyncIfNeeded()
        // No account on this device: a session left in the Keychain (it
        // survives deleting the app) belongs to nobody here.
        if account == nil, !isSigningIn, epoch == self.epoch, let sync {
            await sync.discardStaleSessions(loggingOut: nil)
        }
        if epoch == self.epoch { runReviewUpkeep() }
    }

    /// Back to an empty, local-only workspace (after sign-out).
    private func resetToEmptyLocalWorkspace() {
        epoch += 1
        unpersisted = []
        pendingDismissals = []
        pendingEdits = []
        deferredDocument = nil
        document = StoreDocument()
        syncStartedFor = nil
        if storageError != nil { storageError = nil }
        if state != .empty { state = .empty }
        refreshDerivedState()
    }
}

// MARK: - Sync events

extension Workspace {
    private func installEventHandlerIfNeeded(_ sync: any SyncService) async {
        guard !hasEventHandler else { return }
        hasEventHandler = true
        await sync.setEventHandler { [weak self] event in
            await self?.handle(event)
        }
    }

    private func startSyncIfNeeded() async {
        guard let sync, let account, syncStartedFor != account.id else { return }
        syncStartedFor = account.id
        await installEventHandlerIfNeeded(sync)
        await sync.start(account: account)
    }

    func handle(_ event: SyncEvent) {
        switch event {
        case .status(let status):
            // A late status from before sign-out must not replace "On this iPhone".
            guard account != nil || isSigningIn else { return }
            if syncStatus != status { syncStatus = status }
        case .documentChanged(let incoming):
            // Likewise a late document of the account that was just removed.
            if incoming.account != nil, account == nil, !isSigningIn { return }
            let lastPull = document.sync.lastPullAt
            receive(incoming)
            // After each pull (contracts/ios-commands.md §5).
            if document.sync.lastPullAt != lastPull, !isSigningIn { runReviewUpkeep() }
        }
    }
}

// MARK: - Supporting types

/// `Workspace.today`, valid for `validFrom..<validUntil`.
struct TodayCache {
    var day: CalendarDay
    var validFrom: Date
    var validUntil: Date
}

public enum WorkspaceError: Error, Hashable, Sendable {
    case unsyncedChanges(count: Int)
    case invalidServerURL
    case signInFailed(message: String, referenceID: String?)
    case storage(String)

    public var message: String {
        switch self {
        case .unsyncedChanges(let count):
            count == 1 ? "1 change hasn't synced yet." : "\(count) changes haven't synced yet."
        case .invalidServerURL: "Use an https server address."
        case .signInFailed(let message, _): message
        case .storage(let message): message
        }
    }
}
