import BrainBuddyAPI
import BrainBuddyCore
import Foundation
import Synchronization

/// Why a sync cycle is wanted. `localChange` is debounced (about 2 s after
/// the last change); the others run as soon as the engine is free, except
/// `periodic`, the repeating tick (`PeriodicSyncTicker`): it does nothing
/// unless the last pull is due or changes wait, and never shortens a retry's backoff.
public enum SyncTrigger: String, Sendable, Hashable {
    case launch, foreground, localChange, networkRestored, manual, backgroundRefresh, periodic
}

/// What the engine tells the workspace.
public enum SyncEvent: Sendable, Hashable {
    /// The engine wrote the document (an acknowledgement, a pull, an issue, a
    /// link). The workspace recomputes its state from this document.
    case documentChanged(StoreDocument)
    case status(SyncStatus)
}

/// The selected Rust epoch's lifecycle port. It has no DocumentStore or
/// documentChanged callback: the durable runtime subscription owns its state.
public protocol SyncRuntimePort: Sendable {
    func request(_ trigger: SyncTrigger) async -> SyncRuntimeWakeResult
    func setNetworkAvailable(_ available: Bool) async
    func close() async
}

public enum SyncRuntimeWakeResult: Hashable, Sendable {
    case status(SyncStatus)
    /// The accepted transport slice has not been installed. Pending local
    /// commands remain durable; this is never represented as synced.
    case transportUnavailable
}

/// Used by the dark native runtime until the accepted transport slice (026,
/// PR-40). Production activation must inject the real coarse transport port.
public struct PendingRustSyncRuntimePort: SyncRuntimePort {
    public init() {}
    public func request(_ trigger: SyncTrigger) async -> SyncRuntimeWakeResult { .transportUnavailable }
    public func setNetworkAvailable(_ available: Bool) async {}
    public func close() async {}
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

/// One password sign-in's Cancel against its link (spec 021 FR-001, design X-03): whichever comes
/// first wins, exactly once. Cancel before the link: nothing is linked, and the session the server
/// opened is ended at once. Once the engine starts saving the link, the device is signed in and its
/// first sync runs like any other: Cancel no longer applies, and `cancel()` says so, so the sheet
/// never reports as cancelled a sign-in that linked the account (and may upload local tasks).
public final class SignInCancellation: Sendable {
    private enum State { case open, cancelled, committed }
    private let state = Mutex(State.open)
    private let onCommit: @Sendable () -> Void

    /// `onCommit` runs once, on the engine, when the link wins.
    public init(onCommit: @escaping @Sendable () -> Void = {}) {
        self.onCommit = onCommit
    }

    /// True when the sign-in is cancelled (now or earlier) and will link nothing; false when the
    /// account is already being linked.
    @discardableResult
    public func cancel() -> Bool {
        state.withLock { state in
            if state == .open { state = .cancelled }
            return state == .cancelled
        }
    }

    public var isCancelled: Bool { state.withLock { $0 == .cancelled } }
    public var isCommitted: Bool { state.withLock { $0 == .committed } }

    /// The engine, right before it saves the link: true to save it, false when Cancel came first.
    func commit() -> Bool {
        let won = state.withLock { state in
            if state == .open { state = .committed }
            return state == .committed
        }
        if won { onCommit() }
        return won
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
    /// `signInWithResult`, with the person's Cancel (`SignInCancellation`): a Cancel that wins links
    /// nothing and throws `SyncEngine.signInCancelledMessage`; once the link won, the sign-in and its
    /// first sync finish as a normal one.
    func signInWithResult(
        serverURL: URL, email: String, password: String, cancellation: SignInCancellation
    ) async throws(SignInFailure) -> SignInResult
    /// Signs out. In order: stop syncing and wait for a running cycle; record the session as a
    /// pending logout (so a crash from here on still ends it); run `remove`, which removes the
    /// device's data; then forget the session and log out on the server now, or when the network
    /// is back. When `remove` throws, the pending logout is withdrawn, syncing resumes, the error
    /// is rethrown, and nothing else has changed: the person is still signed in. The same holds,
    /// without running `remove`, when the session can't be read or its logout can't be recorded.
    func signOut(removingLocalDataWith remove: @Sendable () async throws -> Void) async throws
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

    /// Services that link as they log in decide Cancel against the link before they start.
    public func signInWithResult(
        serverURL: URL, email: String, password: String, cancellation: SignInCancellation
    ) async throws(SignInFailure) -> SignInResult {
        guard cancellation.commit() else { throw SignInFailure(message: SyncEngine.signInCancelledMessage) }
        return try await signInWithResult(serverURL: serverURL, email: email, password: password)
    }

    public func discardStaleSessions(loggingOut account: LinkedAccount?) async {}
}
