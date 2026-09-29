import BrainBuddyCore
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

    // MARK: Construction

    /// Production workspace backed by the shared App Group file. Extensions
    /// pass `enableSync: false`; only the app talks to the server.
    public static func live(appGroupID: String, enableSync: Bool = true) -> Workspace {
        fatalError("Workspace.live is not implemented yet")
    }

    /// In-memory workspace with sample data for SwiftUI previews and UI tests.
    public static func preview() -> Workspace {
        fatalError("Workspace.preview is not implemented yet")
    }

    /// Loads (or creates) the stored document and starts sync if an account is linked.
    public func load() async {
        fatalError("Workspace.load is not implemented yet")
    }

    /// Picks up writes made by another process (widget, App Intent). Call on
    /// scene activation and when the shared-store change notification fires.
    public func reloadIfChangedExternally() async {
        fatalError("Workspace.reloadIfChangedExternally is not implemented yet")
    }

    /// Waits until every change applied so far is on disk.
    public func flush() async {
        fatalError("Workspace.flush is not implemented yet")
    }

    // MARK: Reading

    /// The device's current local calendar day, used by date views.
    public var today: CalendarDay { CalendarDay(date: Date()) }

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
        fatalError("Workspace.capture is not implemented yet")
    }

    public func updateTask(_ id: TaskID, _ changes: TaskChanges) throws(GTDValidationError) {
        fatalError("Workspace.updateTask is not implemented yet")
    }

    /// Moves an open task to another open list; Waiting requires `waitingFor`.
    public func moveTask(_ id: TaskID, to list: OpenList, waitingFor: String? = nil) throws(GTDValidationError) {
        fatalError("Workspace.moveTask is not implemented yet")
    }

    public func completeTask(_ id: TaskID) throws(GTDValidationError) {
        fatalError("Workspace.completeTask is not implemented yet")
    }

    public func cancelTask(_ id: TaskID) throws(GTDValidationError) {
        fatalError("Workspace.cancelTask is not implemented yet")
    }

    /// Reopens a completed or cancelled task into an explicit open list.
    public func reopenTask(_ id: TaskID, to list: OpenList, waitingFor: String? = nil) throws(GTDValidationError) {
        fatalError("Workspace.reopenTask is not implemented yet")
    }

    @discardableResult
    public func addSubtask(to taskID: TaskID, title: String) throws(GTDValidationError) -> SubtaskID {
        fatalError("Workspace.addSubtask is not implemented yet")
    }

    public func renameSubtask(_ subtaskID: SubtaskID, in taskID: TaskID, to title: String) throws(GTDValidationError) {
        fatalError("Workspace.renameSubtask is not implemented yet")
    }

    public func transitionSubtask(
        _ subtaskID: SubtaskID, in taskID: TaskID, _ action: SubtaskTransitionAction
    ) throws(GTDValidationError) {
        fatalError("Workspace.transitionSubtask is not implemented yet")
    }

    @discardableResult
    public func addComment(to taskID: TaskID, body: String) throws(GTDValidationError) -> CommentID {
        fatalError("Workspace.addComment is not implemented yet")
    }

    public func editComment(_ commentID: CommentID, in taskID: TaskID, body: String) throws(GTDValidationError) {
        fatalError("Workspace.editComment is not implemented yet")
    }

    @discardableResult
    public func createProject(name: String, color: String? = nil) throws(GTDValidationError) -> ProjectID {
        fatalError("Workspace.createProject is not implemented yet")
    }

    public func renameProject(_ id: ProjectID, to name: String) throws(GTDValidationError) {
        fatalError("Workspace.renameProject is not implemented yet")
    }

    public func setProjectColor(_ id: ProjectID, color: String?) throws(GTDValidationError) {
        fatalError("Workspace.setProjectColor is not implemented yet")
    }

    /// Archives a project. Like the server today, this removes the project
    /// from all of its tasks; the tasks stay in their lists. There is no unarchive.
    public func archiveProject(_ id: ProjectID) throws(GTDValidationError) {
        fatalError("Workspace.archiveProject is not implemented yet")
    }

    @discardableResult
    public func createTag(name: String) throws(GTDValidationError) -> TagID {
        fatalError("Workspace.createTag is not implemented yet")
    }

    public func renameTag(_ id: TagID, to name: String) throws(GTDValidationError) {
        fatalError("Workspace.renameTag is not implemented yet")
    }

    /// Deletes a tag and removes it from every task; the tasks stay.
    public func deleteTag(_ id: TagID) throws(GTDValidationError) {
        fatalError("Workspace.deleteTag is not implemented yet")
    }

    // MARK: Account and sync

    /// Signs in and links this device's data to the account. Local-only data
    /// is uploaded; the account's existing data is downloaded and merged.
    public func signIn(serverURL: URL, email: String, password: String) async throws {
        fatalError("Workspace.signIn is not implemented yet")
    }

    /// Signs out and removes the account's data from this device. Fails with
    /// `WorkspaceError.unsyncedChanges` unless `discardUnsyncedChanges` is set
    /// while changes are still pending.
    public func signOut(discardUnsyncedChanges: Bool) async throws {
        fatalError("Workspace.signOut is not implemented yet")
    }

    /// Pushes pending changes and pulls the latest server state now.
    public func syncNow() async {
        fatalError("Workspace.syncNow is not implemented yet")
    }

    /// Loads subtasks and comments for a task from the server (when online);
    /// call when a task detail opens.
    public func refreshTaskDetails(_ id: TaskID) async {
        fatalError("Workspace.refreshTaskDetails is not implemented yet")
    }

    public func dismissIssue(_ id: SyncIssue.ID) {
        fatalError("Workspace.dismissIssue is not implemented yet")
    }

    /// Informs the sync scheduler about connectivity (from NWPathMonitor in the app).
    public func networkAvailabilityChanged(isAvailable: Bool) {
        fatalError("Workspace.networkAvailabilityChanged is not implemented yet")
    }
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
