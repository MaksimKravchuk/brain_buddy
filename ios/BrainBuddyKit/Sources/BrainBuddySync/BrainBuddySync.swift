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

/// What a sign-in did.
public struct SignInResult: Hashable, Sendable {
    public var account: LinkedAccount
    /// The account was scheduled for deletion and this sign-in cancelled that
    /// (the server does so on login during the grace period). Tell the person.
    public var deletionCancelled: Bool

    public init(account: LinkedAccount, deletionCancelled: Bool = false) {
        self.account = account
        self.deletionCancelled = deletionCancelled
    }
}

public struct NativeSignInAttempt: Hashable, Sendable {
    public let id: UUID
    public let serverURL: URL
    public let expectedAccountID: String?
    public init(id: UUID, serverURL: URL, expectedAccountID: String?) {
        self.id = id
        self.serverURL = serverURL
        self.expectedAccountID = expectedAccountID
    }
}

public enum NativeSignInOutcome: Hashable, Sendable {
    case signedIn(SignInResult)
    /// No session is installed for mailbox/recovery/collision continuations.
    case continuation(AuthCompletionDTO)
}

/// What `Workspace` needs from sync. `SyncEngine` is the implementation;
/// workspace tests use fakes. Every write the engine makes goes through the
/// shared `DocumentStore` (read-modify-write under its lock), so the engine
/// never holds a stale copy of the outbox and never races the workspace.
public protocol SyncService: Sendable {
    func beginSignIn(serverURL: URL) async throws(SignInFailure) -> NativeSignInAttempt
    func completeSignIn(_ attempt: NativeSignInAttempt, credential: NativeSignInCredential) async throws(SignInFailure) -> NativeSignInOutcome
    func cancelSignIn(_ attempt: NativeSignInAttempt) async
    func setEventHandler(_ handler: @escaping @Sendable (SyncEvent) async -> Void) async
    /// Starts syncing the account already linked in the stored document
    /// (after launch). Emits `.status` and schedules a `.launch` cycle.
    func start(account: LinkedAccount) async
    /// Logs in, stores the session, links the account in the document
    /// (`StoreDocument.account`) and runs the first cycle: pull first, so
    /// local-only data merges by name, then push, then pull.
    ///
    /// Signing in to another account (or server) than the one linked is
    /// refused while that account's changes or sync issues are still on the
    /// device, so they are never uploaded into the wrong account.
    func signIn(serverURL: URL, email: String, password: String) async throws(SignInFailure) -> LinkedAccount
    /// `signIn`, also reporting what the server said about the account.
    func signInWithResult(serverURL: URL, email: String, password: String) async throws(SignInFailure) -> SignInResult
    /// Logs out on the server (best effort; retried later when offline) and
    /// forgets the session. The workspace removes the document itself.
    func signOut() async
    /// No account is linked on this device (launch without one, or after the
    /// stored document was set aside): every stored session is stale and is
    /// forgotten. `account`, when known, is the account of a document just set
    /// aside; its session is logged out on the server first (best effort).
    func discardStaleSessions(loggingOut account: LinkedAccount?) async
    /// Asks for a cycle; returns at once.
    func request(_ trigger: SyncTrigger) async
    /// Runs a cycle now (joining one in flight) and returns the resulting status.
    @discardableResult
    func syncNow() async -> SyncStatus
    /// Loads a task's subtasks and comments (`GET /tasks/{id}`) when online,
    /// inside the engine's single-flight cycle, so never beside a push.
    func refreshTask(_ id: TaskID) async
    func setNetworkAvailable(_ available: Bool) async
}

extension SyncService {
    public func beginSignIn(serverURL: URL) async throws(SignInFailure) -> NativeSignInAttempt {
        throw SignInFailure(message: "This app can't start this sign-in method.")
    }
    public func completeSignIn(_ attempt: NativeSignInAttempt, credential: NativeSignInCredential) async throws(SignInFailure) -> NativeSignInOutcome {
        throw SignInFailure(message: "This app can't complete this sign-in method.")
    }
    public func cancelSignIn(_ attempt: NativeSignInAttempt) async {}
    /// Services that cannot tell a cancelled deletion report none.
    public func signInWithResult(
        serverURL: URL, email: String, password: String
    ) async throws(SignInFailure) -> SignInResult {
        SignInResult(account: try await signIn(serverURL: serverURL, email: email, password: password))
    }

    public func discardStaleSessions(loggingOut account: LinkedAccount?) async {}
}
