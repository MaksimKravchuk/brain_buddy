import BrainBuddyAPI
import BrainBuddyCore
import Foundation

/// Why a sync cycle is wanted. `localChange` is debounced (about 2 s after
/// the last change); the others run as soon as the engine is free.
public enum SyncTrigger: String, Sendable, Hashable {
    case launch, foreground, localChange, networkRestored, manual, backgroundRefresh
}

/// What the engine tells the workspace.
public enum SyncEvent: Sendable, Hashable {
    /// The engine wrote the document (an acknowledgement, a pull, an issue, a
    /// link). The workspace recomputes its state from this document.
    case documentChanged(StoreDocument)
    case status(SyncStatus)
}

/// A sign-in the server refused, in words for the sign-in sheet.
public struct SignInFailure: Error, Hashable, Sendable {
    public var message: String
    public var referenceID: String?
    public init(message: String, referenceID: String? = nil) {
        self.message = message
        self.referenceID = referenceID
    }
}

/// What `Workspace` needs from sync. `SyncEngine` is the implementation;
/// workspace tests use fakes. Every write the engine makes goes through the
/// shared `DocumentStore` (read-modify-write under its lock), so the engine
/// never holds a stale copy of the outbox and never races the workspace.
public protocol SyncService: Sendable {
    func setEventHandler(_ handler: @escaping @Sendable (SyncEvent) async -> Void) async
    /// Starts syncing the account already linked in the stored document
    /// (after launch). Emits `.status` and schedules a `.launch` cycle.
    func start(account: LinkedAccount) async
    /// Logs in, stores the session, links the account in the document
    /// (`StoreDocument.account`) and runs the first cycle: pull first, so
    /// local-only data merges by name, then push, then pull.
    func signIn(serverURL: URL, email: String, password: String) async throws(SignInFailure) -> LinkedAccount
    /// Logs out on the server (best effort) and forgets the session. The
    /// workspace removes the document itself.
    func signOut() async
    /// Asks for a cycle; returns at once.
    func request(_ trigger: SyncTrigger) async
    /// Runs a cycle now (joining one in flight) and returns the resulting status.
    @discardableResult
    func syncNow() async -> SyncStatus
    /// Loads a task's subtasks and comments (`GET /tasks/{id}`) when online.
    func refreshTask(_ id: TaskID) async
    func setNetworkAvailable(_ available: Bool) async
}
