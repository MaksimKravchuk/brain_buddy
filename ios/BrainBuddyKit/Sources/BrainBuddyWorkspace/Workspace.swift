import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyPersistence
import BrainBuddySync
import Foundation
import Observation

/// An explicitly selected, already prepared runtime. Production migration and
/// account cutover install this configuration; the default initializer remains
/// in the legacy epoch. A selected runtime never opens the retired document.
public struct RustWorkspaceSelection: Sendable {
    /// Authority is an explicit lifecycle choice, never inferred from a flag
    /// or missing account. Rust verifies that fresh setup is still unchosen.
    public enum Startup: Sendable {
        case prepared
        case freshAccountless
    }

    public let runtime: RustWorkspaceRuntime
    public let facade: RustDomainFacade
    public let transport: any SyncRuntimePort
    public let account: LinkedAccount?
    public let reviewEnabled: Bool
    public let startup: Startup

    public init(runtime: RustWorkspaceRuntime, facade: RustDomainFacade,
                transport: any SyncRuntimePort = PendingRustSyncRuntimePort(),
                account: LinkedAccount? = nil, reviewEnabled: Bool = false,
                startup: Startup = .prepared) {
        self.runtime = runtime
        self.facade = facade
        self.transport = transport
        self.account = account
        self.reviewEnabled = reviewEnabled
        self.startup = startup
    }

    /// Prepare the importer-owned accountless runtime before any Workspace UI
    /// binding. Production selection remains the separately gated T044 choice.
    public static func importAccountless(using importer: RustStoreImporter, facade: RustDomainFacade,
                                         transport: any SyncRuntimePort = PendingRustSyncRuntimePort(),
                                         reviewEnabled: Bool = false) async throws -> RustWorkspaceSelection {
        let runtime = try await importer.prepareAccountlessRuntime(facade: facade, reviewEnabled: reviewEnabled)
        return RustWorkspaceSelection(runtime: runtime, facade: facade, transport: transport,
            reviewEnabled: reviewEnabled)
    }
}

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
    /// This device's child edits per task since launch (`GTDState.localChildEdits`):
    /// only grows, so acknowledgement, compaction and replay never move it.
    /// In memory only: no decision card stays open across a relaunch.
    @ObservationIgnored var localChildEdits: [TaskID: Int] = [:]
    /// The device's current zone (`TimeZone.current`; tests inject one).
    @ObservationIgnored public var deviceTimeZone: @Sendable () -> TimeZone = { TimeZone.current }
    /// Issues the user dismissed that are not removed on disk yet.
    @ObservationIgnored private var pendingDismissals: Set<SyncIssue.ID> = []
    /// The write loop, while it runs. Writes never overlap or reorder.
    @ObservationIgnored private var writer: Task<Void, Never>?
    @ObservationIgnored private var writerToken = 0
    @ObservationIgnored private var legacySavingEditors: Set<String> = []
    /// True while a store write is in flight: documents read meanwhile wait
    /// in `deferredDocument`, so the commands being written are never
    /// applied twice (once from the new document, once from `unpersisted`).
    @ObservationIgnored private var isWriting = false
    @ObservationIgnored private var deferredDocument: StoreDocument?
    /// Set during sign-out: nothing new is written for the old account.
    @ObservationIgnored private var writesSuspended = false
    /// A sign-out is committing (spec 021, FR-018, X-04): from its last count check to the empty
    /// workspace, every command is refused with `GTDValidationError.signingOut`, so a change made
    /// meanwhile (the Mac's global Quick Capture, an in-process App Intent) is never accepted and
    /// then removed unseen. The caller keeps what was typed and can try again once it is done.
    @ObservationIgnored public private(set) var isSigningOut = false
    /// A sign-out has its local removal still to do (or to fail): `waitForSignOutRemoval()`.
    @ObservationIgnored private var signOutRemovalPending = false
    @ObservationIgnored private var signOutRemovalWaiters: [CheckedContinuation<Void, Never>] = []
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
    /// Fires `.periodic` while the app is in the foreground (`setForegroundActive`).
    @ObservationIgnored private let foregroundTicker: PeriodicSyncTicker?
    @ObservationIgnored private var isForeground = false
    @ObservationIgnored private var todayCache: TodayCache?
    /// How many times `state` was rebuilt by a full replay (for tests).
    @ObservationIgnored private(set) var fullReplayCount = 0

    @ObservationIgnored private let rustSelection: RustWorkspaceSelection?
    @ObservationIgnored private(set) var rustRuntime: RustWorkspaceRuntime?
    @ObservationIgnored private(set) var rustFacade: RustDomainFacade?
    @ObservationIgnored private(set) var rustQueries: RustWorkspaceAdapter?
    @ObservationIgnored private var rustGestureSaver: RustWorkspaceGestureSaver?
    @ObservationIgnored private var rustSubscription: RustWorkspaceSubscription?
    @ObservationIgnored private var rustWatcher: Task<Void, Never>?
    @ObservationIgnored private(set) var runtimeBindingID = UUID()
    @ObservationIgnored private var rustTaskFrames: [TaskID: RustWorkspaceTaskFrame] = [:]
    @ObservationIgnored private var rustTaskInterests: [Data: Set<TaskID>] = [:]
    @ObservationIgnored private var rustProjectInterests: [Data: Set<ProjectID>] = [:]
    @ObservationIgnored private var rustTagInterests: [Data: Set<TagID>] = [:]
    @ObservationIgnored private var rustPruningDrafts = false
    @ObservationIgnored var rustReviewPresentationSaving = false
    var rustLocalReview = LocalReviewState()
    var rustReviewDraftCount = 0
    var rustReviewState: RustWorkspaceReviewState?
    var rustIdentityBindings: [RustWorkspaceIdentityBinding] = []
    public private(set) var runtimeTransportUnavailable = false
    public private(set) var runtimeIssues: [RustWorkspaceIssue] = []
    public private(set) var queryError: String?
    var presentationDraftError: String?
    @ObservationIgnored private var rustStatusRequestID: UInt64 = 0
    private var rustSyncState: RustWorkspaceSyncState?

    public var isRustSelected: Bool { rustSelection != nil }
    public var isRustBound: Bool { rustRuntime != nil && rustQueries != nil }

    // MARK: Construction

    /// A workspace over `store`. Pass `sync: nil` where nothing may talk to
    /// the server (widgets, App Intents, previews). `now` and `makeID` are the
    /// clock and the id source for new commands (ids, operation ids and
    /// idempotency keys); tests inject deterministic ones, and the scheduler
    /// that runs the foreground tick.
    public init(
        store: any DocumentStore, sync: (any SyncService)?, rust: RustWorkspaceSelection? = nil,
        now: @escaping @Sendable () -> Date = { Date() },
        makeID: @escaping @Sendable () -> UUID = { UUID() },
        tickScheduler: any SyncScheduler = TaskSyncScheduler()
    ) {
        self.store = store
        self.sync = rust == nil ? sync : nil
        rustSelection = rust
        self.now = now
        self.makeID = makeID
        foregroundTicker = (rust == nil ? sync : nil).map { sync in
            PeriodicSyncTicker(scheduler: tickScheduler) { await sync.request(.periodic) }
        }
    }

    /// Production workspace backed by the shared App Group file. Extensions
    /// pass `enableSync: false`; only the app talks to the server. `identity` is what the
    /// server's logs call this client (`X-Client`).
    public static func live(appGroupID: String, enableSync: Bool = true, identity: ClientIdentity = .iOS) -> Workspace {
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
        return Workspace(store: store, sync: SyncEngine(store: store, tokenStore: tokenStore, identity: identity))
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
        if isRustSelected { await refreshRustStatus(); return }
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
        if isRustSelected { await refreshRustStatus(); return }
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
        guard !isRustSelected else { return nil }
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
        if isRustSelected {
            guard let key = try? rustFacade?.workspaceListQuery(destination, options: options, bindings: rustIdentityBindings),
                  let page = rustPage(for: key), let facade = rustFacade else { return TaskListResult(sections: [], openCount: 0) }
            do { return try facade.workspaceList(from: page, keeping: state, at: now()).list }
            catch { markRustQueryError(error); return TaskListResult(sections: [], openCount: 0) }
        }
        var result = GTDQueries.list(destination, options: options, in: state, today: today)
        if let search = options.search, !search.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            let matches = Set(GTDQueries.list(.search(search), options: ListOptions(), in: state, today: today).sections.flatMap(\.tasks).map(\.id))
            result.sections = result.sections.compactMap { section in
                var narrowed = section
                narrowed.tasks = section.tasks.filter { matches.contains($0.id) }
                return narrowed.tasks.isEmpty ? nil : narrowed
            }
            result.openCount = result.sections.flatMap(\.tasks).filter(\.isOpen).count
        }
        return result
    }

    public func counts() -> ListCounts {
        if isRustSelected {
            guard let key = try? rustFacade?.workspaceReadQuery("list_counts"), let page = rustPage(for: key),
                  let facade = rustFacade else { return ListCounts() }
            do { return try facade.workspaceCounts(from: page.result) }
            catch { markRustQueryError(error); return ListCounts() }
        }
        return GTDQueries.counts(in: state, today: today)
    }
    public func task(_ id: TaskID) -> TaskRecord? {
        if let task = state.tasks[id] { return task }
        guard isRustSelected, let canonical = rustIdentityBindings.first(where: { $0.entityType == "task" && $0.localID == id.rawValue })?.canonicalID else { return nil }
        return state.tasks[TaskID(canonical)]
    }
    public func project(_ id: ProjectID) -> ProjectRecord? {
        if let project = state.projects[id] { return project }
        guard isRustSelected, let canonical = rustIdentityBindings.first(where: { $0.entityType == "project" && $0.localID == id.rawValue })?.canonicalID else { return nil }
        return state.projects[ProjectID(canonical)]
    }
    public func tag(_ id: TagID) -> TagRecord? {
        if let tag = state.tags[id] { return tag }
        guard isRustSelected, let canonical = rustIdentityBindings.first(where: { $0.entityType == "tag" && $0.localID == id.rawValue })?.canonicalID else { return nil }
        return state.tags[TagID(canonical)]
    }
    public func projects(archived: Bool = false, search: String? = nil) -> [ProjectSummary] {
        if isRustSelected {
            guard let key = try? rustFacade?.workspaceProjectsQuery(archived: archived, search: search),
                  let page = rustPage(for: key), let facade = rustFacade else { return [] }
            do { return try facade.workspaceProjects(from: page.result, keeping: state, at: now()) }
            catch { markRustQueryError(error); return [] }
        }
        let rows = GTDQueries.projects(in: state, archived: archived)
        guard let search, !search.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return rows }
        return rows.filter { $0.project.name.localizedStandardContains(search.trimmingCharacters(in: .whitespacesAndNewlines)) }
    }
    public func tags(search: String? = nil) -> [TagSummary] {
        if isRustSelected {
            guard let key = try? rustFacade?.workspaceTagsQuery(search: search), let page = rustPage(for: key),
                  let facade = rustFacade else { return [] }
            do { return try facade.workspaceTags(from: page.result, keeping: state, at: now()) }
            catch { markRustQueryError(error); return [] }
        }
        let rows = GTDQueries.tags(in: state)
        guard let search, !search.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return rows }
        return rows.filter { $0.tag.name.localizedStandardContains(search.trimmingCharacters(in: .whitespacesAndNewlines)) }
    }
    public func capturePreview(_ draft: CaptureDraft) -> CapturePreview {
        if isRustSelected {
            guard let key = try? rustCapturePreviewKey(draft), let page = rustPage(for: key), let facade = rustFacade else {
                return CapturePreview(title: "", project: nil, tags: [], tokens: [], problem: nil)
            }
            do { return try facade.workspaceCapturePreview(from: page.result, in: state) }
            catch { markRustQueryError(error); return CapturePreview(title: "", project: nil, tags: [], tokens: [], problem: nil) }
        }
        return CapturePlanner.preview(draft, in: state)
    }

    /// True when `comment` was written by the signed-in user (or on this device).
    public func isOwnComment(_ comment: CommentRecord) -> Bool {
        comment.authorID == nil || comment.authorID == account?.id || account == nil
    }

    // MARK: Writing (synchronous, offline, validated)

    /// Captures one task from a Smart Add draft; creates missing projects/tags.
    @discardableResult
    public func capture(_ draft: CaptureDraft) throws(GTDValidationError) -> TaskID {
        guard !isRustSelected else { throw .asynchronousSaveRequired }
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

    /// Archives a project. Every task keeps it and stays in its list (ADR-0020).
    public func archiveProject(_ id: ProjectID) throws(GTDValidationError) {
        try perform(.archiveProject(id))
    }

    /// Makes an archived project active again; refused while another active project has its name.
    public func unarchiveProject(_ id: ProjectID) throws(GTDValidationError) {
        try perform(.unarchiveProject(project: id))
    }

    /// Sets (or, with nil or blank, clears) a project's desired outcome, archived or not.
    public func setProjectOutcome(_ id: ProjectID, outcome: String?) throws(GTDValidationError) {
        try perform(.setProjectOutcome(project: id, outcome: outcome))
    }

    /// Clarifies an Inbox item as a project, as one change: creates the project (with its desired
    /// `outcome`, if any), makes the item its first Next action under the title `firstAction`, with
    /// `changes` (tags, due date) applied too. Pass the text trimmed, as every client does.
    @discardableResult
    public func clarifyAsProject(
        _ id: TaskID, projectName: String, outcome: String? = nil, firstAction: String,
        changes: TaskChanges = TaskChanges()
    ) throws(GTDValidationError) -> ProjectID {
        guard !isRustSelected else { throw .asynchronousSaveRequired }
        guard let task = state.tasks[id] else { throw .taskNotFound }
        let projectID = ProjectID(Self.rawID(makeID()))
        var changes = changes
        changes.projectID = .set(projectID)
        changes.title = firstAction == task.title ? .unchanged : .set(firstAction)
        try perform([
            .createProject(.init(projectID: projectID, name: projectName, desiredOutcome: outcome)),
            .updateTask(.init(taskID: id, changes: changes)),
            .transitionTask(.init(taskID: id, action: .move, toList: .next)),
        ])
        return projectID
    }

    /// Applies `commands` in order as one change: all of them are validated on a scratch state and
    /// queued together, or none is and the reason is thrown. For flows that are several commands
    /// to the person (clarify an Inbox item as a project, follow up a Waiting item). The server still
    /// receives one request per command, in order.
    public func apply(_ commands: [GTDCommand]) throws(GTDValidationError) {
        try perform(commands)
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
    ///
    /// `cancellation` is the person's Cancel (the Mac's X-03): one that wins links nothing and
    /// throws the kit's "cancelled" failure; once the link won, this returns as a normal sign-in.
    ///
    /// Account changes are one at a time (spec 021, FR-018): while a sign-out commits this is
    /// refused with `signInFailed` (`signingOutMessage`) and sends nothing, and while it runs a
    /// sign-out is refused (`WorkspaceError.signingIn`), so a sign-in never links an account a
    /// sign-out removed meanwhile. A second sign-in while one runs (a Cancel's request included,
    /// until it has ended) is refused too (`signInOnItsWayMessage`).
    public func signIn(
        serverURL: URL, email: String, password: String, cancellation: SignInCancellation = SignInCancellation()
    ) async throws {
        guard !isRustSelected else { throw WorkspaceError.signInFailed(message: "This account change isn't available yet. Your work is kept.", referenceID: nil) }
        guard let url = BrainBuddyAPI.serverURL(from: serverURL.absoluteString) else {
            throw WorkspaceError.invalidServerURL
        }
        guard let sync else {
            throw WorkspaceError.signInFailed(message: "Sign in from the Brain Buddy app.", referenceID: nil)
        }
        try refuseAnotherAccountChange()
        // The engine uploads what is in the store, so everything must be there.
        await flush()
        if account == nil { try await convertLocalAutoParksForLinking() }
        await installEventHandlerIfNeeded(sync)
        // Checked again after the suspensions above, in the same step that marks the sign-in.
        try refuseAnotherAccountChange()
        isSigningIn = true
        let linked: LinkedAccount
        do {
            let result = try await sync.signInWithResult(
                serverURL: url, email: email, password: password, cancellation: cancellation)
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

    /// A sign-in's refusal while a sign-out commits or another sign-in runs.
    private func refuseAnotherAccountChange() throws(WorkspaceError) {
        if isSigningOut { throw .signInFailed(message: Self.signingOutMessage, referenceID: nil) }
        if isSigningIn { throw .signInFailed(message: Self.signInOnItsWayMessage, referenceID: nil) }
    }

    /// Additive iOS authentication; legacy password callers keep their contract.
    public func beginSignIn(serverURL: URL) async throws -> NativeSignInAttempt {
        guard !isRustSelected else { throw WorkspaceError.signInFailed(message: "This account change isn't available yet. Your work is kept.", referenceID: nil) }
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
        guard !isRustSelected else { throw WorkspaceError.signInFailed(message: "This account change isn't available yet. Your work is kept.", referenceID: nil) }
        guard let sync, nativeSignInID == attempt.id else { throw WorkspaceError.signInFailed(message: "Start a fresh sign-in. Your local tasks are kept.", referenceID: nil) }
        await flush()
        guard nativeSignInID == attempt.id else { throw WorkspaceError.signInFailed(message: "This sign-in was cancelled.", referenceID: nil) }
        if account == nil { try await convertLocalAutoParksForLinking() }
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
        guard !isRustSelected else { return }
        if nativeSignInID == attempt.id { nativeSignInID = nil; isSigningIn = false }
        await sync?.cancelSignIn(attempt)
        refreshDerivedState()
    }

    /// Acknowledges `signInCancelledAccountDeletion` once the person was told.
    public func acknowledgeAccountDeletionNotice() {
        if signInCancelledAccountDeletion { signInCancelledAccountDeletion = false }
    }

    /// The local changes a sign-out would remove, each by its id and what it holds: unsent ones and
    /// open sync issues, for a sign-out confirmation to name (`signOut(removing:)`).
    public var pendingChanges: Set<PendingChange> { isRustSelected ? [] : PendingChange.all(in: document, unpersisted: unpersisted) }

    /// Signs out and removes the account's data from this device. Fails with
    /// `WorkspaceError.unsyncedChanges` unless `discardUnsyncedChanges` is set
    /// while changes are still pending, counting those a widget or App Intent
    /// queued in the store that this workspace has not picked up yet. With it
    /// set, it removes the changes pending when called and no others
    /// (`signOut(removing:)`).
    public func signOut(discardUnsyncedChanges: Bool) async throws {
        try await signOut(removing: discardUnsyncedChanges ? pendingChanges : [])
    }

    /// Signs out and removes the account's data from this device, with no more of its unsent
    /// changes and sync issues than `confirmed`: the ones the confirmation named (`pendingChanges`
    /// when it was shown; empty for a plain sign-out). Spec 021, FR-018, X-04.
    ///
    /// Any other pending change or issue fails it with `WorkspaceError.unsyncedChanges` and the real
    /// count, and nothing is removed: one already pending, one a widget or App Intent queues in the
    /// store meanwhile (checked again under the store's lock), also when a named change was
    /// acknowledged in between so the count still matches, an edit was folded into a named change
    /// so its id still matches, or a named change the server rejected became an issue. One made in
    /// this workspace meanwhile is refused (`GTDValidationError.signingOut`, `isSigningOut`). While a sign-in runs (its link and first sync) it is refused with
    /// `WorkspaceError.signingIn` and nothing is removed.
    public func signOut(removing confirmed: Set<PendingChange>) async throws {
        guard !isRustSelected else { throw WorkspaceError.storage("This account change isn't available yet. Your work is kept.") }
        guard !isSigningIn else { throw WorkspaceError.signingIn }
        let pending = pendingChanges
        if !pending.isSubset(of: confirmed) { throw WorkspaceError.unsyncedChanges(count: pending.count) }
        // Set before the first suspension: nothing performed from here on can slip past the changes
        // the person confirmed and be removed with the account's data.
        isSigningOut = true
        signOutRemovalPending = true
        defer {
            isSigningOut = false
            signOutRemovalEnded()
        }
        // A browser sign-in not yet completing is cancelled (one completing refused this sign-out).
        nativeSignInID = nil
        // Let a write in flight finish, and write nothing new for this account.
        writesSuspended = true
        if let writer { await writer.value }
        // Another process may have queued changes since the last reload.
        let unpersisted = self.unpersisted
        let latest = try? await store.load()
        let unsynced = PendingChange.all(in: latest, unpersisted: unpersisted)
        if !unsynced.isSubset(of: confirmed) {
            writesSuspended = false
            await refreshFromStore()
            schedulePersistence()
            throw WorkspaceError.unsyncedChanges(count: unsynced.count)
        }
        let store = self.store
        // The engine runs this once it has recorded the session's logout; it is checked again under
        // the store's lock, so nothing queued in between is lost: a change that was not confirmed
        // (any, for a plain sign-out) and nothing is removed.
        let removeData: @Sendable () async throws -> Void = { [weak self] in
            try await store.destroy(after: { stored in
                let unsynced = PendingChange.all(in: stored, unpersisted: unpersisted)
                if !unsynced.isSubset(of: confirmed) { throw WorkspaceError.unsyncedChanges(count: unsynced.count) }
            })
            // Removed: a quit may go ahead now (the logout is recorded, and sent next launch if not now).
            await self?.signOutRemovalEnded()
        }
        do {
            if let sync { try await sync.signOut(removingLocalDataWith: removeData) } else { try await removeData() }
        } catch {
            // Nothing was removed and the engine kept the session and resumed: still signed in.
            writesSuspended = false
            await refreshFromStore()
            schedulePersistence()
            if let error = error as? WorkspaceError { throw error }
            throw WorkspaceError.storage(Self.storageMessage(for: error))
        }
        resetToEmptyLocalWorkspace()
        writesSuspended = false
        didPersist?()
    }

    /// Returns once no sign-out has its local removal still to do: at once when none runs, else when
    /// its data is removed (or it failed and removed nothing). The Mac's quit waits for it (spec 021,
    /// FR-018), so a confirmed sign-out never leaves the account's data on the device for the next
    /// launch. The server logout is not waited for: it is recorded first and sent at the next launch.
    public func waitForSignOutRemoval() async {
        while signOutRemovalPending { await withCheckedContinuation { signOutRemovalWaiters.append($0) } }
    }

    private func signOutRemovalEnded() {
        signOutRemovalPending = false
        let waiters = signOutRemovalWaiters
        signOutRemovalWaiters = []
        waiters.forEach { $0.resume() }
    }

    /// The app came to the foreground (or went away). Active: starts the 15 s tick and asks for one
    /// pull now; inactive: stops the tick. Asking for the state it is in changes nothing. The Mac
    /// calls it with `true` and never `false`; the iPhone follows its scene phase.
    public func setForegroundActive(_ active: Bool) async {
        guard active != isForeground else { return }
        isForeground = active
        if isRustSelected { if active { await wakeRustTransport(.foreground) }; return }
        foregroundTicker?.setActive(active)
        if active { await sync?.request(.foreground) }
    }

    /// Everything the sync status line is told (`SyncStatusDescriber.describe`). A change counts as
    /// waiting from when it became sendable: the later of its issue time and the account's link time,
    /// so a first sign-in with months-old local data does not read as days of failure; the ones
    /// issued before the link are the first upload.
    public var syncSnapshot: SyncSnapshot {
        if isRustSelected {
            return SyncSnapshot(account: account.map { .linked(email: $0.email) } ?? .none,
                sessionEnded: syncStatus == .needsSignIn, isOnline: networkIsAvailable, isSyncing: syncStatus == .syncing,
                lastSyncedAt: rustSyncState?.lastSuccessAt, pendingCount: pendingChangeCount,
                oldestPendingAt: rustSyncState?.oldestPendingAt, initialUploadRemaining: 0,
                issueCount: Int(clamping: rustSyncState?.openIssues ?? 0), failingSince: nil,
                lastFailedAttemptAt: nil, lastFailureReferenceID: nil)
        }
        let operations = document.outbox + unpersisted
        let linkedAt = account?.linkedAt
        let sendable = operations.map { max($0.issuedAt, linkedAt ?? $0.issuedAt) }
        let metadata = document.sync
        return SyncSnapshot(
            account: account.map { .linked(email: $0.email) } ?? .none,
            sessionEnded: syncStatus == .needsSignIn, isOnline: networkIsAvailable, isSyncing: syncStatus == .syncing,
            lastSyncedAt: [metadata.lastPullAt, metadata.lastPushAt].compactMap { $0 }.max(),
            pendingCount: operations.count, oldestPendingAt: sendable.min(),
            initialUploadRemaining: operations.filter { $0.issuedAt < (linkedAt ?? .distantPast) }.count,
            issueCount: issues.count, failingSince: metadata.failingSince,
            lastFailedAttemptAt: metadata.lastFailedAttemptAt, lastFailureReferenceID: metadata.lastFailureReferenceID)
    }

    /// Pushes pending changes and pulls the latest server state now.
    public func syncNow() async {
        if isRustSelected { await maintainRuntimeDrafts(); await wakeRustTransport(.manual); await refreshRustStatus(); return }
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
        if isRustSelected {
            await prepareTaskDetail(id)
            return
        }
        guard let sync, account != nil else { return }
        await sync.refreshTask(id)
    }

    public func dismissIssue(_ id: SyncIssue.ID) {
        guard !isRustSelected else { return }
        guard document.issues.contains(where: { $0.id == id }) else { return }
        pendingDismissals.insert(id)
        issues.removeAll { $0.id == id }
        schedulePersistence()
    }

    /// Informs the sync scheduler about connectivity (from NWPathMonitor in the app).
    public func networkAvailabilityChanged(isAvailable: Bool) {
        networkIsAvailable = isAvailable
        if isRustSelected, let selection = rustSelection {
            let binding = runtimeBindingID
            let previous = networkUpdates
            networkUpdates = Task {
                await previous?.value
                guard binding == self.runtimeBindingID else { return }
                await selection.transport.setNetworkAvailable(isAvailable)
                if isAvailable { await self.wakeRustTransport(.networkRestored) }
            }
            return
        }
        guard let sync else { return }
        // Chained, so the engine sees the changes in the order they happened.
        let previous = networkUpdates
        networkUpdates = Task {
            await previous?.value
            await sync.setNetworkAvailable(isAvailable)
            if isAvailable { await sync.request(.networkRestored) }
        }
    }

    /// Waits until the connectivity updates sent so far reached the sync service (tests, and the
    /// Mac host's trigger tests, spec 021).
    public func waitForNetworkUpdates() async {
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
        guard !isRustSelected else { throw .asynchronousSaveRequired }
        guard !isSigningOut else { throw .signingOut }
        let issuedAt = Self.storedPrecision(now())
        let makeID = self.makeID
        let commands =
            reviewExposed ? commands.map { Self.stampingFormulationID($0) { FormulationID.make(makeID()) } } : commands
        var next = state
        // The device's exposure input for Core's review rules (the reducer
        // refuses a person's review actions while it is hidden); never kept
        // in `state` or stored.
        next.review.accountlessReleaseSwitch = accountlessReleaseSwitch
        // This device's child-edit counts (FR-011): Core counts and compares
        // them during the apply; they live here, not in `state`.
        next.localChildEdits = localChildEdits
        for command in commands {
            try GTDReducer.apply(command, at: issuedAt, to: &next, mode: .interactive)
        }
        next.review.accountlessReleaseSwitch = nil
        localChildEdits = next.localChildEdits ?? localChildEdits
        next.localChildEdits = nil
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
        guard !isRustSelected else { return }
        pendingEdits.append(change)
        schedulePersistence()
    }

    /// Starts the write loop unless it is running (it picks up new changes
    /// itself) or there is nothing to write.
    func schedulePersistence() {
        guard !isRustSelected else { return }
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

    nonisolated static func awaitedStorageMessage(for error: any Error) -> String {
        if let error = error as? DocumentStoreError { return error.message }
        return "This change couldn't be saved on this device. Your text is still here. Try again."
    }

    /// Async save callers keep their draft and use the same validation copy.
    /// Bridge failures expose only safe, stable codes at this boundary.
    public nonisolated static func saveMessage(for error: any Error) -> String {
        if let validation = error as? GTDValidationError { return validation.message }
        if let workspace = error as? WorkspaceError { return workspace.message }
        if let bridge = error as? RustBridgeError {
            switch bridge.code {
            case "CANCELLED": return "This save was cancelled. Your text is still here."
            case "STORE_BUSY": return "Another window is saving. Try again."
            case "STORE_UPGRADE_REQUIRED": return "Update Brain Buddy before saving on this device."
            case "WORKSPACE_CLOSED": return "This workspace was closed. Open it and try again."
            default: break
            }
        }
        return "This save couldn't be confirmed on this device. Your text is still here. Try again."
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
        guard !isRustSelected else { return }
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
        guard !isRustSelected else { return nil }
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
        if isRustSelected { await bindRustRuntime(); return }
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
        localChildEdits = [:]
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
        guard !isRustSelected else { return }
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
    /// A sign-out while a sign-in runs: refused, nothing removed (spec 021, FR-018).
    case signingIn

    public var message: String {
        switch self {
        case .unsyncedChanges(let count):
            count == 1 ? "1 change hasn't synced yet." : "\(count) changes haven't synced yet."
        case .invalidServerURL: "Use an https server address."
        case .signInFailed(let message, _): message
        case .storage(let message): message
        case .signingIn: "Brain Buddy is still signing in. Nothing was removed; try again in a moment."
        }
    }
}

extension Workspace {
    /// `signIn`'s refusal while a sign-out commits (`WorkspaceError.signInFailed`).
    public nonisolated static let signingOutMessage = "Brain Buddy is signing out. Try signing in again in a moment."
    /// `signIn`'s refusal while another sign-in runs (`WorkspaceError.signInFailed`).
    public nonisolated static let signInOnItsWayMessage = "Brain Buddy is still finishing the last sign-in. Try again in a moment."
}


extension Workspace {
    func markRustQueryError(_ error: any Error) {
        markRustQueryError((error as? RustBridgeError)?.code ?? "MALFORMED_QUERY_RESULT")
    }

    func markRustQueryError(_ code: String) { queryError = code }

    private func bindRustRuntime() async {
        guard let selection = rustSelection, rustRuntime == nil else { return }
        let binding = UUID()
        runtimeBindingID = binding
        do {
            guard case .ready = try await selection.runtime.status() else {
                throw RustBridgeError(code: "READ_ONLY_RECOVERY")
            }
            switch selection.startup {
            case .prepared: break
            case .freshAccountless:
                guard selection.account == nil else { throw RustBridgeError(code: "INVALID_REQUEST", field: "account_less_setup") }
                try await selection.runtime.establishAccountless()
            }
            guard binding == runtimeBindingID else { return }
            rustRuntime = selection.runtime
            rustFacade = selection.facade
            rustGestureSaver = RustWorkspaceGestureSaver(runtime: selection.runtime)
            account = selection.account
            accountlessReviewEnabled = selection.reviewEnabled
            let inputs = try selection.facade.workspaceQueryInputs(at: now(), zone: deviceTimeZone().identifier,
                reviewExposed: selection.reviewEnabled)
            let runtime = selection.runtime
            rustQueries = RustWorkspaceAdapter(inputs: inputs, query: { key, inputs, cursor in
                let root = try JSONSerialization.jsonObject(with: key) as? [String: Any]
                if root?["kind"] as? String == "capture_preview", let draft = root?["draft"] {
                    let data = try JSONSerialization.data(withJSONObject: draft, options: [.sortedKeys])
                    return try await runtime.smartAddResolve(draft: selection.facade.workspaceResolveReferences(data, runtime: runtime))
                }
                if root?["kind"] as? String == "records" {
                    let requests = try Self.rustRecordRequests(from: key)
                    return try await runtime.records(requests)
                }
                var request = root ?? [:]
                let limit = request.removeValue(forKey: "_collection_limit") as? Int ?? 200
                guard (1...200).contains(limit) else { throw RustBridgeError(code: "INVALID_QUERY_LIMIT") }
                let wire = try JSONSerialization.data(withJSONObject: request, options: [.sortedKeys])
                let canonical = try await selection.facade.workspaceResolveReferences(wire, runtime: runtime)
                return try await runtime.query(canonical, inputs: inputs, collectionLimit: UInt32(limit), collectionAfter: cursor)
            }, didPublish: { [weak self] key, page in
                guard let self, self.runtimeBindingID == binding else { return }
                try self.adoptRustPage(query: key, page: page)
            }, didRefuse: { [weak self] key, refusal in
                guard let self, self.runtimeBindingID == binding else { return }
                if refusal.reason == "review_unavailable" {
                    self.rustReviewState = nil
                    self.state.review.server?.exposed = false
                }
                if refusal.reason == "not_found", let root = try? JSONSerialization.jsonObject(with: key) as? [String: Any],
                   let id = root["task_id"] as? String {
                    self.state.tasks.removeValue(forKey: TaskID(id))
                }
            })
            var local = try await runtime.loadDraft("runtime:local-review")
            if local == nil { local = try await runtime.loadDraft("legacy-local-review") }
            if let local {
                var decoded = try StoreDocumentCoding.makeDecoder().decode(LocalReviewState.self, from: local.fields)
                decoded.formDrafts = [:]
                guard binding == runtimeBindingID else { return }
                rustLocalReview = decoded
            }
            guard binding == runtimeBindingID else { return }
            let subscription = try await runtime.subscribe()
            guard binding == runtimeBindingID else { return }
            rustSubscription = subscription
            rustWatcher = Task { [weak self] in
                var token: String?
                do {
                    while !Task.isCancelled {
                        guard let event = try await subscription.next(after: token) else {
                            if self == nil { return }
                            continue
                        }
                        guard let self, self.runtimeBindingID == binding else { return }
                        token = event.token
                        if let generation = UInt64(event.projectionGeneration),
                           generation > (self.rustQueries?.generationFloor ?? 0) || !event.changedKinds.isEmpty {
                            let inputs = try selection.facade.workspaceQueryInputs(at: self.now(),
                                zone: self.deviceTimeZone().identifier, reviewExposed: selection.reviewEnabled)
                            self.rustQueries?.invalidate(generation: generation, inputs: inputs)
                        }
                        if event.syncStatusChanged || event.issuesChanged { await self.refreshRustStatus() }
                        if !event.changedKinds.isEmpty { await self.maintainRuntimeDrafts() }
                    }
                } catch {
                    guard let self, self.runtimeBindingID == binding, !Task.isCancelled else { return }
                    self.markRustQueryError(error)
                }
            }
            if let counts = try? selection.facade.workspaceReadQuery("list_counts") { await prepareRustQuery(counts) }
            await refreshRustStatus()
            await maintainRuntimeDrafts()
            await wakeRustTransport(.launch)
            guard binding == runtimeBindingID else { return }
            isLoaded = true
            loadError = nil
        } catch {
            guard binding == runtimeBindingID else { return }
            loadError = Self.saveMessage(for: error)
            isLoaded = true
        }
    }

    public func closeRuntime() async {
        guard let selection = rustSelection else { return }
        runtimeBindingID = UUID()
        rustWatcher?.cancel()
        rustWatcher = nil
        rustQueries?.close()
        rustQueries = nil
        rustSubscription = nil
        rustRuntime = nil
        rustFacade = nil
        rustGestureSaver = nil
        rustStatusRequestID &+= 1
        rustTaskFrames = [:]
        rustTaskInterests = [:]
        rustProjectInterests = [:]
        rustTagInterests = [:]
        state = .empty
        await selection.transport.close()
        do { try await selection.runtime.close() }
        catch { markRustQueryError(error) }
    }

    func rustPage(for key: Data) -> RustWorkspacePage? { rustQueries?.page(for: key) }
    func rustReadiness(for key: Data) -> WorkspaceQueryReadiness { rustQueries?.readiness(for: key) ?? .notRequested }
    func prepareRustQuery(_ key: Data) async { await rustQueries?.prepare(key) }

    func rustQueryPageState(_ build: () throws -> Data) -> WorkspaceQueryPageState {
        guard isRustSelected else { return WorkspaceQueryPageState(readiness: .ready) }
        guard isRustBound else { return WorkspaceQueryPageState(readiness: .notRequested) }
        do { return rustQueries?.pageState(for: try build()) ?? WorkspaceQueryPageState(readiness: .notRequested) }
        catch { return WorkspaceQueryPageState(readiness: .failed(Self.rustQueryCode(error))) }
    }

    private static func rustQueryCode(_ error: any Error) -> String {
        (error as? RustBridgeError)?.code ?? "MALFORMED_QUERY_RESULT"
    }

    func prepareOwnedQuery(_ build: () throws -> Data,
                           identities: [RustWorkspaceIdentityRequest] = []) async {
        guard isRustSelected else { return }
        do {
            try await resolveRustIdentities(identities)
            await prepareRustQuery(try build())
        } catch {
            if let key = try? build() { rustQueries?.recordFailure(key, code: Self.rustQueryCode(error)) }
            markRustQueryError(error)
        }
    }

    private func rustListKey(_ destination: Destination, options: ListOptions) throws -> Data {
        guard let facade = rustFacade else { throw RustBridgeError(code: "WORKSPACE_NOT_READY") }
        return try facade.workspaceListQuery(destination, options: options, bindings: rustIdentityBindings)
    }

    public func prepareList(_ destination: Destination, options: ListOptions = ListOptions()) async {
        var refs: [RustWorkspaceIdentityRequest] = []
        if case .project(let id) = destination { refs.append(.init(entityType: "project", localID: id.rawValue)) }
        if case .tag(let id) = destination { refs.append(.init(entityType: "tag", localID: id.rawValue)) }
        if let id = options.tagFilter { refs.append(.init(entityType: "tag", localID: id.rawValue)) }
        await prepareOwnedQuery({ try rustListKey(destination, options: options) }, identities: refs)
    }

    public func listReadiness(_ destination: Destination, options: ListOptions = ListOptions()) -> WorkspaceQueryReadiness {
        listPageState(destination, options: options).readiness
    }

    public func listPageState(_ destination: Destination, options: ListOptions = ListOptions()) -> WorkspaceQueryPageState {
        rustQueryPageState { try rustListKey(destination, options: options) }
    }

    public func nextListPage(_ destination: Destination, options: ListOptions = ListOptions()) async {
        guard let key = try? rustListKey(destination, options: options) else { return }
        await rustQueries?.nextPage(key)
    }

    public func previousListPage(_ destination: Destination, options: ListOptions = ListOptions()) async {
        guard let key = try? rustListKey(destination, options: options) else { return }
        await rustQueries?.previousPage(key)
    }

    public func listShownTask(_ id: TaskID, destination: Destination, options: ListOptions = ListOptions()) -> ShownTask? {
        guard isRustSelected else { return list(destination, options: options).sections.flatMap(\.tasks).first { $0.id == id }.map { shownTask(of: $0) } }
        guard let key = try? rustListKey(destination, options: options) else { return nil }
        return rustQueryShownTask(id, key: key)
    }

    func rustQueryShownTask(_ id: TaskID, key: Data) -> ShownTask? {
        guard let facade = rustFacade, let page = rustPage(for: key) else { return nil }
        let raw = rustIdentityBindings.first { $0.entityType == "task" && $0.localID == id.rawValue }?.canonicalID
        let canonical = raw.map { TaskID($0) } ?? id
        do { return try facade.workspaceShownTask(canonical, from: page, at: now(), localChildEdits: localChildEdits[canonical] ?? 0) }
        catch { rustQueries?.recordFailure(key, code: Self.rustQueryCode(error)); markRustQueryError(error); return nil }
    }

    public func listFormulation(_ id: TaskID, destination: Destination, options: ListOptions = ListOptions()) -> RustWorkspaceFormulation? {
        guard isRustSelected else { return legacyFormulation(id) }
        guard let key = try? rustListKey(destination, options: options) else { return nil }
        return rustQueryFormulation(id, key: key)
    }

    public func taskDetailFormulation(_ id: TaskID) -> RustWorkspaceFormulation? {
        guard isRustSelected else { return legacyFormulation(id) }
        guard let key = try? rustTaskDetailKey(id) else { return nil }
        return rustQueryFormulation(id, key: key)
    }

    func rustQueryFormulation(_ id: TaskID, key: Data) -> RustWorkspaceFormulation? {
        guard let facade = rustFacade, let page = rustPage(for: key) else { return nil }
        let canonical = rustIdentityBindings.first { $0.entityType == "task" && $0.localID == id.rawValue }
            .flatMap { $0.canonicalID }.map { TaskID($0) } ?? id
        do { return try facade.workspaceTaskFormulation(canonical, from: page) }
        catch { rustQueries?.recordFailure(key, code: Self.rustQueryCode(error)); markRustQueryError(error); return nil }
    }

    private func rustCountsKey() throws -> Data {
        guard let facade = rustFacade else { throw RustBridgeError(code: "WORKSPACE_NOT_READY") }
        return try facade.workspaceReadQuery("list_counts")
    }

    public func prepareCounts() async { await prepareOwnedQuery { try rustCountsKey() } }
    public func countsReadiness() -> WorkspaceQueryReadiness { rustQueryPageState { try rustCountsKey() }.readiness }

    func rustCapturePreviewKey(_ draft: CaptureDraft) throws -> Data {
        guard let facade = rustFacade else { throw RustBridgeError(code: "WORKSPACE_NOT_READY") }
        let draft = try facade.workspaceCaptureDraft(draft, bindings: rustIdentityBindings)
        return try JSONSerialization.data(withJSONObject: ["kind": "capture_preview", "draft": JSONSerialization.jsonObject(with: draft)], options: [.sortedKeys])
    }

    public func prepareCapturePreview(_ draft: CaptureDraft) async {
        var refs: [RustWorkspaceIdentityRequest] = []
        if let id = draft.contextProjectID { refs.append(.init(entityType: "project", localID: id.rawValue)) }
        if let id = draft.contextTagID { refs.append(.init(entityType: "tag", localID: id.rawValue)) }
        await prepareOwnedQuery({ try rustCapturePreviewKey(draft) }, identities: refs)
    }

    public func capturePreviewReadiness(_ draft: CaptureDraft) -> WorkspaceQueryReadiness {
        rustQueryPageState { try rustCapturePreviewKey(draft) }.readiness
    }

    func rustMutateShown(_ mutation: (inout GTDState) -> Void) { mutation(&state) }

    func rustAdoptTasks(_ tasks: [TaskRecord], for query: Data, frames: [RustWorkspaceTaskFrame]? = nil) {
        rustTaskInterests[query] = Set(tasks.map(\.id))
        for var task in tasks {
            if let frame = frames?.first(where: { $0.taskID == task.id }) ?? (frames == nil ? rustTaskFrames[task.id] : nil) {
                task.lastOpenList = frame.lastOpenList
                task.childrenSyncedAt = frame.childrenKnown ? now() : nil
            }
            state.tasks[task.id] = task
        }
        pruneRustRecords(keeping: query)
    }

    private func pruneRustRecords(keeping query: Data) {
        let active = Set(rustQueries?.entries.keys ?? Dictionary<Data, RustWorkspaceAdapter.Entry>().keys).union([query])
        rustTaskInterests = rustTaskInterests.filter { active.contains($0.key) }
        rustProjectInterests = rustProjectInterests.filter { active.contains($0.key) }
        rustTagInterests = rustTagInterests.filter { active.contains($0.key) }
        let tasks = Set(rustTaskInterests.values.flatMap { $0 })
        let projects = Set(rustProjectInterests.values.flatMap { $0 })
        let tags = Set(rustTagInterests.values.flatMap { $0 })
        state.tasks = state.tasks.filter { tasks.contains($0.key) }
        rustTaskFrames = rustTaskFrames.filter { tasks.contains($0.key) }
        state.projects = state.projects.filter { projects.contains($0.key) }
        state.tags = state.tags.filter { tags.contains($0.key) }
    }

    private func adoptRustPage(query: Data, page: RustWorkspacePage) throws {
        guard let facade = rustFacade,
              let root = try JSONSerialization.jsonObject(with: query) as? [String: Any],
              let kind = root["kind"] as? String else { throw RustDomainError.malformedResult }
        let frames = try facade.workspaceTaskFrames(from: page)
        for frame in frames { rustTaskFrames[frame.taskID] = frame }
        switch kind {
        case "list_mode":
            let list = try facade.workspaceList(from: page, keeping: state, at: now())
            rustAdoptTasks(list.list.sections.flatMap(\.tasks), for: query)
        case "task_detail":
            let task = try facade.workspaceTask(from: page.result, detail: true, at: now())
            rustAdoptTasks([task], for: query)
        case "projects", "native_projects":
            let projects = try facade.workspaceProjects(from: page.result, keeping: state, at: now())
            rustProjectInterests[query] = Set(projects.map { $0.project.id })
            for row in projects { state.projects[row.project.id] = row.project }
            pruneRustRecords(keeping: query)
        case "tags", "native_tags":
            let tags = try facade.workspaceTags(from: page.result, keeping: state, at: now())
            rustTagInterests[query] = Set(tags.map { $0.tag.id })
            for row in tags { state.tags[row.tag.id] = row.tag }
            pruneRustRecords(keeping: query)
        case "task_list", "native_task_views":
            rustAdoptTasks(try facade.workspaceRenderedTasks(from: page, at: now()), for: query)
        case "records":
            let requests = try Self.rustRecordRequests(from: query)
            var owned = GTDState.empty
            try facade.workspaceApplyRecords(from: page.result, requests: requests, to: &owned, at: now())
            rustAdoptTasks(Array(owned.tasks.values), for: query)
            rustProjectInterests[query] = Set(owned.projects.keys)
            rustTagInterests[query] = Set(owned.tags.keys)
            for (id, record) in owned.projects { state.projects[id] = record }
            for (id, record) in owned.tags { state.tags[id] = record }
            pruneRustRecords(keeping: query)
        case "list_counts": _ = try facade.workspaceCounts(from: page.result)
        case "capture_preview": _ = try facade.workspaceCapturePreview(from: page.result, in: state)
        default: try adoptRustReviewPage(query: query, page: page)
        }
    }

    func rustReadRecords(_ requests: [RustWorkspaceRecordRequest]) async throws -> RustWorkspacePage {
        guard let runtime = rustRuntime else { throw RustBridgeError(code: "WORKSPACE_NOT_READY") }
        let binding = runtimeBindingID
        let answer = try await runtime.records(requests)
        guard binding == runtimeBindingID else { throw RustBridgeError(code: "CLOSED") }
        switch answer {
        case .answered(let page):
            guard let generation = UInt64(page.projectionGeneration), generation >= (rustQueries?.generationFloor ?? 0) else {
                throw RustBridgeError(code: "QUERY_RESTART_REQUIRED")
            }
            return page
        case .refused(let refusal, _): throw RustDomainError.refused(reason: refusal.reason, field: refusal.field)
        }
    }

    private func refreshRustStatus() async {
        guard let runtime = rustRuntime, let facade = rustFacade else { return }
        let binding = runtimeBindingID
        rustStatusRequestID &+= 1
        let request = rustStatusRequestID
        do {
            let status = try facade.workspaceSyncState(from: await runtime.syncStatus())
            guard binding == runtimeBindingID, request == rustStatusRequestID else { return }
            guard status.generation >= (rustQueries?.generationFloor ?? 0) else { return }
            rustSyncState = status
            pendingChangeCount = Int(clamping: status.pending)
            let answer = try await runtime.issues()
            guard binding == runtimeBindingID, request == rustStatusRequestID else { return }
            if case .answered(let page) = answer, let generation = UInt64(page.projectionGeneration),
               generation >= (rustQueries?.generationFloor ?? 0) {
                runtimeIssues = try facade.workspaceIssues(from: page.result)
            }
        } catch {
            guard binding == runtimeBindingID, request == rustStatusRequestID else { return }
            markRustQueryError(error)
        }
    }

    private func wakeRustTransport(_ trigger: SyncTrigger) async {
        guard let selection = rustSelection, isRustBound else { return }
        let binding = runtimeBindingID
        let result = await selection.transport.request(trigger)
        guard binding == runtimeBindingID else { return }
        switch result {
        case .status(let status): runtimeTransportUnavailable = false; syncStatus = status
        case .transportUnavailable: runtimeTransportUnavailable = true
        }
    }

    func performAsync(_ commands: [GTDCommand], editorID: String, authoredIntent: Data, shown: GTDState)
        async throws -> RustWorkspaceSavedGesture {
        guard let runtime = rustRuntime, let facade = rustFacade, let saver = rustGestureSaver else {
            throw RustBridgeError(code: "WORKSPACE_NOT_READY")
        }
        let binding = runtimeBindingID
        let instant = now()
        let witnesses = localChildEdits
        let result = try await saver.save(editorID: editorID, authoredIntent: authoredIntent) {
            for command in commands {
                if case .decideTask(let decision) = command {
                    guard let expected = decision.expectedTask, expected.runtimeAdmissionToken != nil else {
                        throw RustBridgeError(code: "SHOWN_FRAME_RELOAD_REQUIRED")
                    }
                    guard expected.matches(shown.tasks[decision.taskID], localChildEdits: witnesses[decision.taskID]) else {
                        throw GTDValidationError.formulationChanged
                    }
                }
            }
            let identities = try facade.workspaceIdentityRequests(for: commands, in: shown, at: instant)
            let bindings = try await runtime.resolveIdentities(identities)
            guard binding == self.runtimeBindingID else { throw RustBridgeError(code: "CLOSED") }
            var encoded = try facade.workspaceCommands(commands, commandIDs: commands.map { _ in self.makeID() },
                at: commands.map { _ in instant }, in: shown, bindings: bindings)
            for index in commands.indices {
                if case .decideTask(let decision) = commands[index] {
                    guard let token = decision.expectedTask?.runtimeAdmissionToken else {
                        throw RustBridgeError(code: "SHOWN_FRAME_RELOAD_REQUIRED")
                    }
                    let data = try JSONSerialization.data(withJSONObject: [JSONSerialization.jsonObject(with: token)], options: [.sortedKeys])
                    let original = encoded[index]
                    encoded[index] = RustWorkspaceCommand(commandID: original.commandID, commandType: original.commandType,
                        entityID: original.entityID, payload: original.payload, preconditions: original.preconditions,
                        dependsOn: original.dependsOn, admissionTokens: data)
                }
            }
            return RustWorkspaceGesture(authoredIntent: authoredIntent, commands: encoded,
                context: try self.rustExecuteContext(at: instant))
        }
        switch result {
        case .refused(let refusal, let failedCommandID, let original):
            var context = shown
            if let type = refusal.entityType, ["project", "tag"].contains(type), let id = refusal.entityKey.first {
                let requests = [RustWorkspaceRecordRequest(entityType: type, recordKey: [id])]
                do {
                    let page = try await rustReadRecords(requests)
                    try facade.workspaceApplyRecords(from: page.result, requests: requests, to: &context, at: instant)
                } catch { if binding == runtimeBindingID { markRustQueryError(error) } }
            }
            if let index = original.firstIndex(where: { $0.commandID == failedCommandID }),
               let error = try facade.workspaceValidationError(refusal, command: original[index], in: context,
                    precedingCommands: Array(original[..<index])) { throw error }
            throw RustDomainError.refused(reason: refusal.reason, field: refusal.field)
        case .saved(let saved):
            await finishRustSave(saved, binding: binding)
            return saved
        }
    }

    func rustExecuteContext(at instant: Date) throws -> RustWorkspaceContext {
        guard let facade = rustFacade else { throw RustBridgeError(code: "WORKSPACE_NOT_READY") }
        let inputs = try facade.workspaceQueryInputs(at: instant, zone: deviceTimeZone().identifier,
            reviewExposed: rustSelection?.reviewEnabled == true)
        guard let root = try JSONSerialization.jsonObject(with: inputs) as? [String: Any], let policy = root["policy"] else {
            throw RustDomainError.malformedResult
        }
        return RustWorkspaceContext(now: instant, timeZone: deviceTimeZone().identifier, actorID: facade.context.actorID,
            policy: try JSONSerialization.data(withJSONObject: policy, options: [.sortedKeys]))
    }
}


extension Workspace {
    func finishRustSave(_ saved: RustWorkspaceSavedGesture, binding: UUID) async {
        guard binding == runtimeBindingID, let facade = rustFacade else { return }
        let generation = saved.receipts.compactMap { UInt64($0.projectionGeneration) }.max() ?? 0
        let inputs = try? facade.workspaceQueryInputs(at: now(), zone: deviceTimeZone().identifier,
            reviewExposed: rustSelection?.reviewEnabled == true)
        rustQueries?.invalidate(generation: generation, inputs: inputs)
        await refreshRustStatus()
        for key in Array(rustQueries?.entries.keys ?? Dictionary<Data, RustWorkspaceAdapter.Entry>().keys) {
            await prepareRustQuery(key)
        }
        await wakeRustTransport(.localChange)
        guard binding == runtimeBindingID else { return }
        didPersist?()
    }

    @discardableResult
    public func capture(_ draft: CaptureDraft, editorID: String) async throws -> TaskID {
        if !isRustSelected {
            let makeID = self.makeID
            let plan = try CapturePlanner.plan(draft, in: state,
                makeTaskID: { TaskID(Self.rawID(makeID())) },
                makeProjectID: { ProjectID(Self.rawID(makeID())) }, makeTagID: { TagID(Self.rawID(makeID())) })
            try await performLegacyDurably(plan.commands, editorID: editorID)
            return plan.taskID
        }
        guard let runtime = rustRuntime, let facade = rustFacade, let saver = rustGestureSaver else {
            throw RustBridgeError(code: "WORKSPACE_NOT_READY")
        }
        let shown = state
        let binding = runtimeBindingID
        let instant = now()
        let intent = try StoreDocumentCoding.makeEncoder().encode(draft)
        let result = try await saver.save(editorID: editorID, authoredIntent: intent) {
            let raw = try facade.workspaceCaptureDraft(draft, bindings: self.rustIdentityBindings)
            let request = try await facade.workspaceResolveReferences(raw, runtime: runtime)
            let resolution = try await runtime.smartAddResolve(draft: request)
            guard binding == self.runtimeBindingID else { throw RustBridgeError(code: "CLOSED") }
            guard case .answered(let page) = resolution else { throw RustDomainError.malformedResult }
            let preview = try facade.workspaceCapturePreview(from: page.result, in: shown)
            if let problem = preview.problem { throw problem }
            let project = preview.project?.isNew == true ? ProjectID(Self.rawID(self.makeID())) : nil
            let tags = preview.tags.filter(\.isNew).map { _ in TagID(Self.rawID(self.makeID())) }
            let minted = try facade.workspaceCaptureMinted(projectID: project, tagIDs: tags)
            let proposed = try await runtime.smartAddPropose(draft: request, minted: minted, expectedGeneration: page.projectionGeneration)
            guard binding == self.runtimeBindingID else { throw RustBridgeError(code: "CLOSED") }
            guard case .answered(let proposal) = proposed else { throw RustDomainError.malformedResult }
            let command = facade.workspaceCaptureCommand(taskID: TaskID(Self.rawID(self.makeID())),
                commandID: self.makeID(), proposal: proposal)
            return RustWorkspaceGesture(authoredIntent: intent, commands: [command], context: try self.rustExecuteContext(at: instant))
        }
        switch result {
        case .refused(let refusal, let failedCommandID, let commands):
            if let command = commands.first(where: { $0.commandID == failedCommandID }), let error = try facade.workspaceValidationError(refusal, command: command, in: shown) { throw error }
            throw RustDomainError.refused(reason: refusal.reason, field: refusal.field)
        case .saved(let saved):
            await finishRustSave(saved, binding: binding)
            guard let id = saved.receipts.first?.entityID else { throw RustDomainError.malformedResult }
            return TaskID(facade.workspaceLocalID(id))
        }
    }

    func saveRustCommands(_ commands: [GTDCommand], editorID: String, authoredIntent: Data? = nil)
        async throws -> RustWorkspaceSavedGesture {
        let intent = try authoredIntent ?? StoreDocumentCoding.makeEncoder().encode(commands)
        return try await performAsync(commands, editorID: editorID, authoredIntent: intent, shown: state)
    }

    public func apply(_ commands: [GTDCommand], editorID: String) async throws {
        if !isRustSelected { try await performLegacyDurably(commands, editorID: editorID); return }
        _ = try await saveRustCommands(commands, editorID: editorID)
    }
}


extension Workspace {
    public func updateTask(_ id: TaskID, _ changes: TaskChanges, editorID: String) async throws {
        if !isRustSelected { try await performLegacyDurably([.updateTask(.init(taskID: id, changes: changes))], editorID: editorID); return }
        _ = try await saveRustCommands([.updateTask(.init(taskID: id, changes: changes))], editorID: editorID)
    }

    public func moveTask(_ id: TaskID, to list: OpenList, waitingFor: String? = nil, editorID: String) async throws {
        if !isRustSelected { try await performLegacyDurably([.transitionTask(.init(taskID: id, action: .move, toList: list, waitingFor: waitingFor))], editorID: editorID); return }
        _ = try await saveRustCommands([.transitionTask(.init(taskID: id, action: .move, toList: list, waitingFor: waitingFor))], editorID: editorID)
    }

    public func completeTask(_ id: TaskID, editorID: String) async throws {
        if !isRustSelected { try await performLegacyDurably([.transitionTask(.init(taskID: id, action: .complete))], editorID: editorID); return }
        _ = try await saveRustCommands([.transitionTask(.init(taskID: id, action: .complete))], editorID: editorID)
    }

    public func cancelTask(_ id: TaskID, editorID: String) async throws {
        if !isRustSelected { try await performLegacyDurably([.transitionTask(.init(taskID: id, action: .cancel))], editorID: editorID); return }
        _ = try await saveRustCommands([.transitionTask(.init(taskID: id, action: .cancel))], editorID: editorID)
    }

    public func reopenTask(_ id: TaskID, to list: OpenList, waitingFor: String? = nil, editorID: String) async throws {
        if !isRustSelected { try await performLegacyDurably([.transitionTask(.init(taskID: id, action: .reopen, toList: list, waitingFor: waitingFor))], editorID: editorID); return }
        _ = try await saveRustCommands([.transitionTask(.init(taskID: id, action: .reopen, toList: list, waitingFor: waitingFor))], editorID: editorID)
    }

    public func renameSubtask(_ subtaskID: SubtaskID, in taskID: TaskID, to title: String, editorID: String) async throws {
        if !isRustSelected { try await performLegacyDurably([.updateSubtask(.init(taskID: taskID, subtaskID: subtaskID, title: title))], editorID: editorID); return }
        _ = try await saveRustCommands([.updateSubtask(.init(taskID: taskID, subtaskID: subtaskID, title: title))], editorID: editorID)
    }

    public func transitionSubtask(_ subtaskID: SubtaskID, in taskID: TaskID, _ action: SubtaskTransitionAction, editorID: String) async throws {
        if !isRustSelected { try await performLegacyDurably([.transitionSubtask(.init(taskID: taskID, subtaskID: subtaskID, action: action))], editorID: editorID); return }
        _ = try await saveRustCommands([.transitionSubtask(.init(taskID: taskID, subtaskID: subtaskID, action: action))], editorID: editorID)
    }

    public func editComment(_ commentID: CommentID, in taskID: TaskID, body: String, editorID: String) async throws {
        if !isRustSelected { try await performLegacyDurably([.updateComment(.init(taskID: taskID, commentID: commentID, body: body))], editorID: editorID); return }
        _ = try await saveRustCommands([.updateComment(.init(taskID: taskID, commentID: commentID, body: body))], editorID: editorID)
    }

    public func renameProject(_ id: ProjectID, to name: String, editorID: String) async throws {
        if !isRustSelected { try await performLegacyDurably([.updateProject(.init(projectID: id, name: name))], editorID: editorID); return }
        _ = try await saveRustCommands([.updateProject(.init(projectID: id, name: name))], editorID: editorID)
    }

    public func setProjectColor(_ id: ProjectID, color: String?, editorID: String) async throws {
        if !isRustSelected { try await performLegacyDurably([.updateProject(.init(projectID: id, color: color.map { .set($0) } ?? .clear))], editorID: editorID); return }
        _ = try await saveRustCommands([.updateProject(.init(projectID: id, color: color.map { .set($0) } ?? .clear))], editorID: editorID)
    }

    public func archiveProject(_ id: ProjectID, editorID: String) async throws {
        if !isRustSelected { try await performLegacyDurably([.archiveProject(id)], editorID: editorID); return }
        _ = try await saveRustCommands([.archiveProject(id)], editorID: editorID)
    }

    public func unarchiveProject(_ id: ProjectID, editorID: String) async throws {
        if !isRustSelected { try await performLegacyDurably([.unarchiveProject(project: id)], editorID: editorID); return }
        _ = try await saveRustCommands([.unarchiveProject(project: id)], editorID: editorID)
    }

    public func setProjectOutcome(_ id: ProjectID, outcome: String?, editorID: String) async throws {
        if !isRustSelected { try await performLegacyDurably([.setProjectOutcome(project: id, outcome: outcome)], editorID: editorID); return }
        _ = try await saveRustCommands([.setProjectOutcome(project: id, outcome: outcome)], editorID: editorID)
    }

    public func renameTag(_ id: TagID, to name: String, editorID: String) async throws {
        if !isRustSelected { try await performLegacyDurably([.renameTag(.init(tagID: id, name: name))], editorID: editorID); return }
        _ = try await saveRustCommands([.renameTag(.init(tagID: id, name: name))], editorID: editorID)
    }

    public func deleteTag(_ id: TagID, editorID: String) async throws {
        if !isRustSelected { try await performLegacyDurably([.deleteTag(id)], editorID: editorID); return }
        _ = try await saveRustCommands([.deleteTag(id)], editorID: editorID)
    }

}


extension Workspace {
    @discardableResult
    public func addSubtask(to taskID: TaskID, title: String, editorID: String) async throws -> SubtaskID {
        if !isRustSelected {
            let result = SubtaskID(Self.rawID(makeID()))
            try await performLegacyDurably([.createSubtask(.init(taskID: taskID, subtaskID: result, title: title))], editorID: editorID)
            return result
        }
        let intent = try JSONSerialization.data(withJSONObject: ["action": "add_subtask", "task": taskID.rawValue, "title": title], options: [.sortedKeys])
        let created = SubtaskID(Self.rawID(makeID()))
        let saved = try await saveRustCommands([.createSubtask(.init(taskID: taskID, subtaskID: created, title: title))],
            editorID: editorID, authoredIntent: intent)
        guard let id = saved.receipts.first?.entityID else { throw RustDomainError.malformedResult }
        return SubtaskID(id)
    }

    @discardableResult
    public func addComment(to taskID: TaskID, body: String, editorID: String) async throws -> CommentID {
        if !isRustSelected {
            let result = CommentID(Self.rawID(makeID()))
            try await performLegacyDurably([.createComment(.init(taskID: taskID, commentID: result, body: body))], editorID: editorID)
            return result
        }
        let intent = try JSONSerialization.data(withJSONObject: ["action": "add_comment", "task": taskID.rawValue, "body": body], options: [.sortedKeys])
        let created = CommentID(Self.rawID(makeID()))
        let saved = try await saveRustCommands([.createComment(.init(taskID: taskID, commentID: created, body: body))],
            editorID: editorID, authoredIntent: intent)
        guard let id = saved.receipts.first?.entityID else { throw RustDomainError.malformedResult }
        return CommentID(id)
    }

    @discardableResult
    public func createProject(name: String, color: String? = nil, editorID: String) async throws -> ProjectID {
        if !isRustSelected {
            let result = ProjectID(Self.rawID(makeID()))
            try await performLegacyDurably([.createProject(.init(projectID: result, name: name, color: color))], editorID: editorID)
            return result
        }
        let intent = try JSONSerialization.data(withJSONObject: ["action": "create_project", "name": name,
            "color": color.map { $0 as Any } ?? NSNull()], options: [.sortedKeys])
        let created = ProjectID(Self.rawID(makeID()))
        let saved = try await saveRustCommands([.createProject(.init(projectID: created, name: name, color: color))],
            editorID: editorID, authoredIntent: intent)
        guard let id = saved.receipts.first?.entityID else { throw RustDomainError.malformedResult }
        return ProjectID(id)
    }

    @discardableResult
    public func createTag(name: String, editorID: String) async throws -> TagID {
        if !isRustSelected {
            let result = TagID(Self.rawID(makeID()))
            try await performLegacyDurably([.createTag(.init(tagID: result, name: name))], editorID: editorID)
            return result
        }
        let intent = try JSONSerialization.data(withJSONObject: ["action": "create_tag", "name": name], options: [.sortedKeys])
        let created = TagID(Self.rawID(makeID()))
        let saved = try await saveRustCommands([.createTag(.init(tagID: created, name: name))],
            editorID: editorID, authoredIntent: intent)
        guard let id = saved.receipts.first?.entityID else { throw RustDomainError.malformedResult }
        return TagID(id)
    }

    @discardableResult
    public func clarifyAsProject(_ id: TaskID, projectName: String, outcome: String? = nil, firstAction: String,
                                 changes: TaskChanges = TaskChanges(), editorID: String) async throws -> ProjectID {
        if !isRustSelected {
            guard let task = state.tasks[id] else { throw GTDValidationError.taskNotFound }
            let result = ProjectID(Self.rawID(makeID()))
            var changed = changes
            changed.projectID = .set(result)
            changed.title = firstAction == task.title ? .unchanged : .set(firstAction)
            try await performLegacyDurably([
                .createProject(.init(projectID: result, name: projectName, desiredOutcome: outcome)),
                .updateTask(.init(taskID: id, changes: changed)),
                .transitionTask(.init(taskID: id, action: .move, toList: .next))], editorID: editorID)
            return result
        }
        let intent = try JSONSerialization.data(withJSONObject: ["action": "clarify_project", "task": id.rawValue,
            "name": projectName, "outcome": outcome.map { $0 as Any } ?? NSNull(), "first_action": firstAction,
            "changes": try JSONSerialization.jsonObject(with: StoreDocumentCoding.makeEncoder().encode(changes))], options: [.sortedKeys])
        let created = ProjectID(Self.rawID(makeID()))
        var changed = changes
        changed.projectID = .set(created)
        if firstAction != state.tasks[id]?.title { changed.title = .set(firstAction) }
        let saved = try await saveRustCommands([
            .createProject(.init(projectID: created, name: projectName, desiredOutcome: outcome)),
            .updateTask(.init(taskID: id, changes: changed)),
            .transitionTask(.init(taskID: id, action: .move, toList: .next))], editorID: editorID, authoredIntent: intent)
        guard let id = saved.commands.first(where: { $0.commandType == "project.create" })?.entityID else {
            throw RustDomainError.malformedResult
        }
        return ProjectID(id)
    }
}


extension Workspace {
    func rustShownTask(of task: TaskRecord) -> ShownTask {
        var shown = ShownTask(task, localChildEdits: localChildEdits[task.id] ?? 0)
        if let frame = rustTaskFrames[task.id], state.tasks[task.id] == task {
            shown.childrenKnown = frame.childrenKnown
            shown.runtimeAdmissionToken = frame.token
        } else {
            shown.childrenKnown = false
        }
        return shown
    }

    /// The awaited legacy path uses the existing writer and document lock.
    /// New commands are never optimistic: a returned failure leaves them absent.
    func performLegacyDurably(
        _ authored: [GTDCommand], editorID: String,
        edits: [@Sendable (inout StoreDocument) -> Void] = []
    ) async throws {
        guard !isRustSelected else { throw GTDValidationError.asynchronousSaveRequired }
        guard !isSigningOut, !writesSuspended else { throw GTDValidationError.signingOut }
        guard !editorID.isEmpty, editorID.utf8.count <= 200 else { throw RustBridgeError(code: "INVALID_DRAFT_ID") }
        guard legacySavingEditors.insert(editorID).inserted else { throw RustBridgeError(code: "STORE_BUSY") }
        defer { legacySavingEditors.remove(editorID) }
        let issuedAt = Self.storedPrecision(now())
        let commands = reviewExposed ? authored.map {
            Self.stampingFormulationID($0) { FormulationID.make(self.makeID()) }
        } : authored
        let operations = commands.map {
            PendingOperation(id: makeID(), command: $0, issuedAt: issuedAt, idempotencyKey: makeID())
        }
        let previous = writer
        let ownedEpoch = epoch
        let exposure = accountlessReleaseSwitch
        let clockAware = reviewExposed
        writerToken += 1
        let token = writerToken
        let transaction = Task { @MainActor () -> Result<Void, any Error> in
            if let previous { await previous.value }
            guard ownedEpoch == self.epoch, !self.writesSuspended, !self.isSigningOut else {
                return .failure(GTDValidationError.signingOut)
            }
            // A prior failure is not permission to stage a new gesture.
            if previous != nil, self.hasPendingWrites, let error = self.storageError {
                return .failure(WorkspaceError.storage(error))
            }
            if self.hasPendingWrites, !(await self.drainWrites(epoch: ownedEpoch)) {
                return .failure(WorkspaceError.storage(self.storageError ?? "This save couldn't be completed."))
            }
            guard ownedEpoch == self.epoch, !self.writesSuspended, !self.isSigningOut else {
                return .failure(GTDValidationError.signingOut)
            }
            let childEdits = self.localChildEdits
            self.isWriting = true
            do {
                let written = try await self.store.update { document in
                    var next = OutboxReplayer.replay(document.outbox, onto: document.base,
                        activatedAt: document.local.activatedAt).state
                    ReviewSessionUpkeep.closeIdle(document.local.idleClosedSessions, in: &next)
                    next.review.accountlessReleaseSwitch = exposure
                    next.localChildEdits = childEdits
                    for command in commands {
                        try GTDReducer.apply(command, at: issuedAt, to: &next, mode: .interactive)
                    }
                    for operation in operations {
                        document.outbox = OutboxCompactor.appending(operation, to: document.outbox, clockAware: clockAware)
                    }
                    for edit in edits { edit(&document) }
                }
                self.isWriting = false
                // The commit is known. Cancellation or subsequent maintenance
                // cannot turn it into a retryable save failure.
                if ownedEpoch == self.epoch {
                    for command in commands {
                        if let task = command.childEditTaskID { self.localChildEdits[task, default: 0] += 1 }
                    }
                    self.storageError = nil
                    self.adoptWritten(written, recomputing: true)
                    self.adoptDeferredDocument()
                    self.didPersist?()
                    if !operations.isEmpty, let sync = self.sync { await sync.request(.localChange) }
                }
                return .success(())
            } catch {
                self.isWriting = false
                if ownedEpoch == self.epoch {
                    self.adoptDeferredDocument()
                    if !(error is GTDValidationError) { self.storageError = Self.awaitedStorageMessage(for: error) }
                }
                if let validation = error as? GTDValidationError { return .failure(validation) }
                return .failure(WorkspaceError.storage(Self.awaitedStorageMessage(for: error)))
            }
        }
        // Registered before the first suspension: flush, sign-out and quit
        // all wait for this exact transaction through the same writer.
        writer = Task {
            let result = await transaction.value
            guard self.writerToken == token else { return }
            self.writer = nil
            switch result {
            case .success: self.schedulePersistence()
            case .failure(let error) where error is GTDValidationError: self.schedulePersistence()
            case .failure: break
            }
        }
        try await transaction.value.get()
    }
}


extension Workspace {
    private func resolveRustIdentities(_ requests: [RustWorkspaceIdentityRequest]) async throws {
        guard let runtime = rustRuntime else { throw RustBridgeError(code: "WORKSPACE_NOT_READY") }
        guard requests.count <= 200 else { throw RustBridgeError(code: "TOO_MANY_ITEMS") }
        guard !requests.isEmpty else { return }
        let binding = runtimeBindingID
        let resolved = try await runtime.resolveIdentities(requests)
        guard binding == runtimeBindingID else { throw RustBridgeError(code: "CLOSED") }
        for row in resolved {
            rustIdentityBindings.removeAll { $0.entityType == row.entityType && $0.localID == row.localID }
            rustIdentityBindings.append(row)
        }
        if rustIdentityBindings.count > 1_024 { rustIdentityBindings.removeFirst(rustIdentityBindings.count - 1_024) }
    }

    private func rustProjectsKey(archived: Bool, search: String? = nil, projectID: ProjectID? = nil) throws -> Data {
        guard let facade = rustFacade else { throw RustBridgeError(code: "WORKSPACE_NOT_READY") }
        return try facade.workspaceProjectsQuery(archived: archived, search: search, projectID: projectID, bindings: rustIdentityBindings)
    }

    private func rustTagsKey(search: String? = nil, topLimit: Int? = nil) throws -> Data {
        guard let facade = rustFacade else { throw RustBridgeError(code: "WORKSPACE_NOT_READY") }
        let key = try facade.workspaceTagsQuery(search: search, sort: topLimit == nil ? .name : .openCount)
        guard let topLimit else { return key }
        guard (1...200).contains(topLimit), var root = try JSONSerialization.jsonObject(with: key) as? [String: Any] else {
            throw RustBridgeError(code: "INVALID_QUERY_LIMIT")
        }
        root["_collection_limit"] = topLimit
        return try JSONSerialization.data(withJSONObject: root, options: [.sortedKeys])
    }

    public func prepareProjects(archived: Bool = false, search: String? = nil) async {
        await prepareOwnedQuery { try rustProjectsKey(archived: archived, search: search) }
    }
    public func prepareTags(search: String? = nil) async { await prepareOwnedQuery { try rustTagsKey(search: search) } }
    public func projectsReadiness(archived: Bool = false, search: String? = nil) -> WorkspaceQueryReadiness {
        projectsPageState(archived: archived, search: search).readiness
    }
    public func tagsReadiness(search: String? = nil) -> WorkspaceQueryReadiness { tagsPageState(search: search).readiness }
    public func projectsPageState(archived: Bool = false, search: String? = nil) -> WorkspaceQueryPageState {
        rustQueryPageState { try rustProjectsKey(archived: archived, search: search) }
    }
    public func tagsPageState(search: String? = nil) -> WorkspaceQueryPageState { rustQueryPageState { try rustTagsKey(search: search) } }
    public func nextProjectsPage(archived: Bool = false, search: String? = nil) async {
        guard let key = try? rustProjectsKey(archived: archived, search: search) else { return }
        await rustQueries?.nextPage(key)
    }
    public func previousProjectsPage(archived: Bool = false, search: String? = nil) async {
        guard let key = try? rustProjectsKey(archived: archived, search: search) else { return }
        await rustQueries?.previousPage(key)
    }
    public func nextTagsPage(search: String? = nil) async {
        guard let key = try? rustTagsKey(search: search) else { return }
        await rustQueries?.nextPage(key)
    }
    public func previousTagsPage(search: String? = nil) async {
        guard let key = try? rustTagsKey(search: search) else { return }
        await rustQueries?.previousPage(key)
    }
    public func prepareTopTags(limit: Int = 5) async { await prepareOwnedQuery { try rustTagsKey(topLimit: limit) } }
    public func topTagsReadiness(limit: Int = 5) -> WorkspaceQueryReadiness { rustQueryPageState { try rustTagsKey(topLimit: limit) }.readiness }
    public func topTags(limit: Int = 5) -> [TagSummary] {
        if !isRustSelected {
            return Array(tags().sorted {
                if $0.openTaskCount != $1.openTaskCount { return $0.openTaskCount > $1.openTaskCount }
                return $0.tag.name.localizedStandardCompare($1.tag.name) == .orderedAscending
            }.prefix(max(0, limit)))
        }
        guard let key = try? rustTagsKey(topLimit: limit), let page = rustPage(for: key), let facade = rustFacade else { return [] }
        return (try? facade.workspaceTags(from: page.result, keeping: .empty, at: now())) ?? []
    }

}


extension Workspace {
    /// Owner-side retention runs even while Review is hidden. A failure can
    /// retry on the next lifecycle event; it never changes a saved receipt.
    public func maintainRuntimeDrafts() async {
        guard let runtime = rustRuntime, !rustPruningDrafts else { return }
        let binding = runtimeBindingID
        rustPruningDrafts = true
        defer { if binding == runtimeBindingID { rustPruningDrafts = false } }
        do {
            let removed = try await runtime.pruneLocalReviewPrivate(now: now())
            guard binding == runtimeBindingID else { return }
            if removed > 0 { invalidateRustPrivateQueries() }
            let result = try await runtime.pruneReviewForms(now: now())
            guard binding == runtimeBindingID,
                  let generation = UInt64(result.projectionGeneration), generation >= (rustQueries?.generationFloor ?? 0) else { return }
            rustReviewDraftCount = result.liveCount
            presentationDraftError = nil
        } catch {
            guard binding == runtimeBindingID else { return }
            presentationDraftError = (error as? RustBridgeError)?.code ?? "DRAFT_MAINTENANCE_FAILED"
        }
    }

    /// Private admission and expiry do not advance the public projection.
    /// Reuse the owned cache's dirty fence so formulation metadata is reread.
    private func invalidateRustPrivateQueries() {
        let inputs = try? rustFacade?.workspaceQueryInputs(at: now(), zone: deviceTimeZone().identifier,
            reviewExposed: rustSelection?.reviewEnabled == true)
        rustQueries?.invalidate(generation: rustQueries?.generationFloor ?? 0, inputs: inputs)
    }
}

/// Exact public record identities; no table names or arbitrary composite keys.
public enum WorkspaceRecordRead: Hashable, Sendable {
    case task(TaskID)
    case project(ProjectID)
    case tag(TagID)

    var identity: RustWorkspaceIdentityRequest {
        switch self {
        case .task(let id): .init(entityType: "task", localID: id.rawValue)
        case .project(let id): .init(entityType: "project", localID: id.rawValue)
        case .tag(let id): .init(entityType: "tag", localID: id.rawValue)
        }
    }
}

/// One bounded exact answer. Dictionary keys are the original requested IDs;
/// each record's own ID remains the authoritative canonical identity.
public struct WorkspaceRecordPage: Sendable {
    public let tasks: [TaskID: TaskRecord]
    public let projects: [ProjectID: ProjectRecord]
    public let tags: [TagID: TagRecord]
    public let missing: Set<WorkspaceRecordRead>
    public let requested: Set<WorkspaceRecordRead>

    public func exists(_ read: WorkspaceRecordRead) -> Bool? {
        guard requested.contains(read) else { return nil }
        return !missing.contains(read)
    }
}

extension Workspace {
    private func rustTaskDetailKey(_ id: TaskID) throws -> Data {
        guard let facade = rustFacade else { throw RustBridgeError(code: "WORKSPACE_NOT_READY") }
        return try facade.workspaceReadQuery("task_detail", taskID: id, bindings: rustIdentityBindings)
    }

    public func prepareTaskDetail(_ id: TaskID) async {
        guard isRustSelected else { await refreshTaskDetails(id); return }
        await prepareOwnedQuery({ try rustTaskDetailKey(id) }, identities: [.init(entityType: "task", localID: id.rawValue)])
    }
    public func taskDetailReadiness(_ id: TaskID) -> WorkspaceQueryReadiness { taskDetailPageState(id).readiness }
    public func taskDetailPageState(_ id: TaskID) -> WorkspaceQueryPageState { rustQueryPageState { try rustTaskDetailKey(id) } }
    public func taskDetail(_ id: TaskID) -> TaskRecord? {
        guard isRustSelected else { return task(id) }
        guard let key = try? rustTaskDetailKey(id), let page = rustPage(for: key), let facade = rustFacade else { return nil }
        do {
            var task = try facade.workspaceTask(from: page.result, detail: true, at: now())
            if let frame = try facade.workspaceTaskFrames(from: page).first(where: { $0.taskID == task.id }) {
                task.lastOpenList = frame.lastOpenList
                task.childrenSyncedAt = frame.childrenKnown ? now() : nil
            }
            return task
        } catch { rustQueries?.recordFailure(key, code: Self.rustQueryCode(error)); markRustQueryError(error); return nil }
    }
    public func nextTaskDetailPage(_ id: TaskID) async {
        guard let key = try? rustTaskDetailKey(id) else { return }
        await rustQueries?.nextPage(key)
    }
    public func previousTaskDetailPage(_ id: TaskID) async {
        guard let key = try? rustTaskDetailKey(id) else { return }
        await rustQueries?.previousPage(key)
    }
    public func taskDetailShownTask(_ id: TaskID) -> ShownTask? {
        guard isRustSelected else { return task(id).map { shownTask(of: $0) } }
        guard let key = try? rustTaskDetailKey(id) else { return nil }
        return rustQueryShownTask(id, key: key)
    }

    public func prepareProjectSummary(_ id: ProjectID) async {
        await prepareOwnedQuery({ try rustProjectsKey(archived: false, projectID: id) },
                                identities: [.init(entityType: "project", localID: id.rawValue)])
    }
    public func projectSummaryReadiness(_ id: ProjectID) -> WorkspaceQueryReadiness {
        rustQueryPageState { try rustProjectsKey(archived: false, projectID: id) }.readiness
    }
    public func projectSummary(_ id: ProjectID) -> ProjectSummary? {
        if !isRustSelected {
            guard let project = project(id), var summary = GTDQueries.projects(in: state, archived: project.state == .archived).first(where: { $0.id == id }) else { return nil }
            let sections = GTDQueries.list(.project(id), options: ListOptions(), in: state, today: today).sections
            summary.countsByState = Dictionary(uniqueKeysWithValues: OpenList.allCases.map { list in
                (list, sections.filter { $0.kind == .list(list) }.reduce(0) { $0 + $1.totalCount })
            })
            return summary
        }
        guard let key = try? rustProjectsKey(archived: false, projectID: id), let page = rustPage(for: key), let facade = rustFacade else { return nil }
        return (try? facade.workspaceProjects(from: page.result, keeping: .empty, at: now()))?.first
    }

    private func rustFirstNextKey(_ id: ProjectID) throws -> Data {
        guard let facade = rustFacade else { throw RustBridgeError(code: "WORKSPACE_NOT_READY") }
        return try facade.workspaceFirstNextQuery(id, bindings: rustIdentityBindings)
    }
    public func prepareFirstNextAction(_ id: ProjectID) async {
        await prepareOwnedQuery({ try rustFirstNextKey(id) }, identities: [.init(entityType: "project", localID: id.rawValue)])
    }
    public func firstNextActionReadiness(_ id: ProjectID) -> WorkspaceQueryReadiness { rustQueryPageState { try rustFirstNextKey(id) }.readiness }
    public func firstNextAction(_ id: ProjectID) -> TaskRecord? {
        if !isRustSelected {
            return GTDQueries.list(.project(id), options: ListOptions(), in: state, today: today).sections.first { $0.kind == .list(.next) }?.tasks.first
        }
        guard let key = try? rustFirstNextKey(id), let page = rustPage(for: key), let facade = rustFacade else { return nil }
        return (try? facade.workspaceRenderedTasks(from: page, at: now()))?.first
    }

    private func rustRecordsKey(_ reads: [WorkspaceRecordRead]) throws -> Data {
        guard reads.count <= 200 else { throw RustBridgeError(code: "TOO_MANY_ITEMS") }
        guard let facade = rustFacade else { throw RustBridgeError(code: "WORKSPACE_NOT_READY") }
        let items: [[String: Any]] = reads.map { read in
            let identity = read.identity
            let request = facade.workspaceRecordRequest(identity.entityType, localID: identity.localID, bindings: rustIdentityBindings)
            return ["entity_type": request.entityType, "record_key": request.recordKey]
        }
        return try JSONSerialization.data(withJSONObject: ["kind": "records", "items": items], options: [.sortedKeys])
    }

    nonisolated private static func rustRecordRequests(from key: Data) throws -> [RustWorkspaceRecordRequest] {
        guard let root = try JSONSerialization.jsonObject(with: key) as? [String: Any],
              let items = root["items"] as? [[String: Any]], items.count <= 200 else {
            throw RustBridgeError(code: "MALFORMED_QUERY_RESULT")
        }
        return try items.map { item in
            guard let type = item["entity_type"] as? String, ["task", "project", "tag"].contains(type),
                  let keys = item["record_key"] as? [String], keys.count == 1 else {
                throw RustBridgeError(code: "MALFORMED_QUERY_RESULT")
            }
            return RustWorkspaceRecordRequest(entityType: type, recordKey: keys)
        }
    }

    @discardableResult
    public func prepareRecords(_ reads: [WorkspaceRecordRead]) async throws -> WorkspaceRecordPage {
        guard reads.count <= 200 else { throw RustBridgeError(code: "TOO_MANY_ITEMS") }
        if !isRustSelected { return legacyRecords(reads) }
        try await resolveRustIdentities(reads.map(\.identity))
        let key = try rustRecordsKey(reads)
        await prepareRustQuery(key)
        guard let page = records(reads) else {
            if case .failed(let code) = rustReadiness(for: key) { throw RustBridgeError(code: code) }
            throw RustBridgeError(code: Task.isCancelled ? "CANCELLED" : "WORKSPACE_NOT_READY")
        }
        return page
    }
    @discardableResult
    public func prepareTaskRecords(_ ids: [TaskID]) async throws -> WorkspaceRecordPage {
        try await prepareRecords(ids.map(WorkspaceRecordRead.task))
    }
    public func recordsReadiness(_ reads: [WorkspaceRecordRead]) -> WorkspaceQueryReadiness {
        guard reads.count <= 200 else { return .failed("TOO_MANY_ITEMS") }
        return rustQueryPageState { try rustRecordsKey(reads) }.readiness
    }
    public func recordReadiness(_ read: WorkspaceRecordRead) -> WorkspaceQueryReadiness { recordsReadiness([read]) }
    public func recordExists(_ read: WorkspaceRecordRead) -> Bool? { records([read])?.exists(read) }
    public func recordsShownTask(_ id: TaskID, reads: [WorkspaceRecordRead]) -> ShownTask? {
        guard isRustSelected else { return task(id).map { shownTask(of: $0) } }
        guard let key = try? rustRecordsKey(reads) else { return nil }
        return rustQueryShownTask(id, key: key)
    }

    public func records(_ reads: [WorkspaceRecordRead]) -> WorkspaceRecordPage? {
        if !isRustSelected { return reads.count <= 200 ? legacyRecords(reads) : nil }
        guard let facade = rustFacade, let key = try? rustRecordsKey(reads), let page = rustPage(for: key) else { return nil }
        do {
            let requests = try Self.rustRecordRequests(from: key)
            var owned = GTDState.empty
            try facade.workspaceApplyRecords(from: page.result, requests: requests, to: &owned, at: now())
            var tasks: [TaskID: TaskRecord] = [:]
            var projects: [ProjectID: ProjectRecord] = [:]
            var tags: [TagID: TagRecord] = [:]
            var missing: Set<WorkspaceRecordRead> = []
            for (index, read) in reads.enumerated() {
                let canonical = requests[index].recordKey[0]
                switch read {
                case .task(let id):
                    if var value = owned.tasks[TaskID(canonical)] {
                        // Record reads hold only this returned child subset, never full detail.
                        value.subtasks = []
                        value.comments = []
                        value.childrenSyncedAt = nil
                        if let frame = try facade.workspaceTaskFrames(from: page).first(where: { $0.taskID == value.id }) { value.lastOpenList = frame.lastOpenList }
                        tasks[id] = value
                    } else { missing.insert(read) }
                case .project(let id):
                    if let value = owned.projects[ProjectID(canonical)] { projects[id] = value } else { missing.insert(read) }
                case .tag(let id):
                    if let value = owned.tags[TagID(canonical)] { tags[id] = value } else { missing.insert(read) }
                }
            }
            return WorkspaceRecordPage(tasks: tasks, projects: projects, tags: tags, missing: missing, requested: Set(reads))
        } catch { rustQueries?.recordFailure(key, code: Self.rustQueryCode(error)); markRustQueryError(error); return nil }
    }

    private func legacyRecords(_ reads: [WorkspaceRecordRead]) -> WorkspaceRecordPage {
        var tasks: [TaskID: TaskRecord] = [:]
        var projects: [ProjectID: ProjectRecord] = [:]
        var tags: [TagID: TagRecord] = [:]
        var missing: Set<WorkspaceRecordRead> = []
        for read in reads {
            switch read {
            case .task(let id): if let value = task(id) { tasks[id] = value } else { missing.insert(read) }
            case .project(let id): if let value = project(id) { projects[id] = value } else { missing.insert(read) }
            case .tag(let id): if let value = tag(id) { tags[id] = value } else { missing.insert(read) }
            }
        }
        return WorkspaceRecordPage(tasks: tasks, projects: projects, tags: tags, missing: missing, requested: Set(reads))
    }
}


extension Workspace {
    private func rustTaskViewsKey(_ ids: [TaskID]) throws -> Data {
        guard let facade = rustFacade else { throw RustBridgeError(code: "WORKSPACE_NOT_READY") }
        return try facade.workspaceTaskViewsQuery(ids, bindings: rustIdentityBindings)
    }

    @discardableResult
    public func prepareTaskViews(_ ids: [TaskID]) async throws -> [TaskRecord] {
        guard ids.count <= 200 else { throw RustBridgeError(code: "TOO_MANY_ITEMS") }
        guard isRustSelected else { return legacyTaskViews(ids) }
        try await resolveRustIdentities(ids.map { .init(entityType: "task", localID: $0.rawValue) })
        let key = try rustTaskViewsKey(ids)
        await prepareRustQuery(key)
        guard let rows = taskViews(ids) else {
            if case .failed(let code) = rustReadiness(for: key) { throw RustBridgeError(code: code) }
            throw RustBridgeError(code: Task.isCancelled ? "CANCELLED" : "WORKSPACE_NOT_READY")
        }
        return rows
    }

    public func taskViewsReadiness(_ ids: [TaskID]) -> WorkspaceQueryReadiness {
        guard ids.count <= 200 else { return .failed("TOO_MANY_ITEMS") }
        return rustQueryPageState { try rustTaskViewsKey(ids) }.readiness
    }

    public func taskViews(_ ids: [TaskID]) -> [TaskRecord]? {
        guard ids.count <= 200 else { return nil }
        guard isRustSelected else { return legacyTaskViews(ids) }
        guard let key = try? rustTaskViewsKey(ids), let page = rustPage(for: key), let facade = rustFacade else { return nil }
        do { return try facade.workspaceRenderedTasks(from: page, at: now()) }
        catch { rustQueries?.recordFailure(key, code: Self.rustQueryCode(error)); markRustQueryError(error); return nil }
    }

    /// Only a ready exact answer proves these requested identities absent.
    public func taskViewsMissing(_ ids: [TaskID]) -> Set<TaskID>? {
        guard let rows = taskViews(ids) else { return nil }
        let found = Set(rows.map(\.id))
        return Set(ids.filter { id in
            let canonical = rustIdentityBindings.first { $0.entityType == "task" && $0.localID == id.rawValue }
                .flatMap { $0.canonicalID }.map { TaskID($0) } ?? id
            return !found.contains(canonical)
        })
    }

    public func taskViewsShownTask(_ id: TaskID, ids: [TaskID]) -> ShownTask? {
        guard isRustSelected else { return legacyTaskViews(ids).first { $0.id == id }.map { shownTask(of: $0) } }
        guard let key = try? rustTaskViewsKey(ids) else { return nil }
        return rustQueryShownTask(id, key: key)
    }

    public func taskViewsFormulation(_ id: TaskID, ids: [TaskID]) -> RustWorkspaceFormulation? {
        guard isRustSelected else { return legacyTaskViews(ids).contains { $0.id == id } ? legacyFormulation(id) : nil }
        guard let key = try? rustTaskViewsKey(ids) else { return nil }
        return rustQueryFormulation(id, key: key)
    }

    private func legacyTaskViews(_ ids: [TaskID]) -> [TaskRecord] {
        var seen: Set<TaskID> = []
        return ids.compactMap { seen.insert($0).inserted ? task($0) : nil }
    }
}
