import BrainBuddyCore
import BrainBuddyPersistence
import BrainBuddySync
import Foundation

/// A `SyncService` that records calls and emits events on demand. Like the
/// real engine, a successful `signIn` links the account in the shared store
/// and reports the written document.
actor FakeSyncService: SyncService {
    enum Call: Hashable, Sendable {
        case start(LinkedAccount)
        case signIn(serverURL: URL, email: String)
        case signOut
        case request(SyncTrigger)
        case syncNow
        case refreshTask(TaskID)
        case setNetworkAvailable(Bool)
    }

    private(set) var calls: [Call] = []
    private(set) var hasEventHandler = false
    /// Outbox size of the stored document when `signIn` was called.
    private(set) var outboxCountAtSignIn: Int?
    /// Every `discardStaleSessions(loggingOut:)` call (kept out of `calls`).
    private(set) var discardedSessions: [LinkedAccount?] = []

    private let store: (any DocumentStore)?
    private var handler: (@Sendable (SyncEvent) async -> Void)?
    private var signInResult: Result<LinkedAccount, SignInFailure>
    private var syncNowStatus: SyncStatus
    private let deletionCancelled: Bool

    init(
        store: (any DocumentStore)? = nil,
        signInResult: Result<LinkedAccount, SignInFailure> = .success(Fixture.account),
        syncNowStatus: SyncStatus = .idle(lastSyncedAt: Fixture.epoch),
        deletionCancelled: Bool = false
    ) {
        self.store = store
        self.signInResult = signInResult
        self.syncNowStatus = syncNowStatus
        self.deletionCancelled = deletionCancelled
    }

    /// Delivers `event` to the workspace and returns once it was handled.
    func emit(_ event: SyncEvent) async {
        await handler?(event)
    }

    /// Writes to the shared store as the engine would, and reports it.
    @discardableResult
    func write(_ transform: @escaping @Sendable (inout StoreDocument) -> Void) async throws -> StoreDocument {
        guard let store else { throw DocumentStoreError.io("the fake has no store") }
        let written = try await store.update { transform(&$0) }
        await emit(.documentChanged(written))
        return written
    }

    // MARK: SyncService

    func setEventHandler(_ handler: @escaping @Sendable (SyncEvent) async -> Void) async {
        self.handler = handler
        hasEventHandler = true
    }

    func start(account: LinkedAccount) async {
        calls.append(.start(account))
    }

    func signInWithResult(serverURL: URL, email: String, password: String) async throws(SignInFailure) -> SignInResult {
        let account = try await signIn(serverURL: serverURL, email: email, password: password)
        return SignInResult(account: account, deletionCancelled: deletionCancelled)
    }

    func discardStaleSessions(loggingOut account: LinkedAccount?) async {
        discardedSessions.append(account)
    }

    func signIn(serverURL: URL, email: String, password: String) async throws(SignInFailure) -> LinkedAccount {
        calls.append(.signIn(serverURL: serverURL, email: email))
        if let store {
            let stored = try? await store.load()
            outboxCountAtSignIn = stored?.outbox.count ?? 0
        }
        let account: LinkedAccount
        switch signInResult {
        case .success(let linked): account = linked
        case .failure(let failure): throw failure
        }
        await emit(.status(.syncing))
        _ = try? await write { $0.account = account }
        await emit(.status(.idle(lastSyncedAt: Fixture.epoch)))
        return account
    }

    /// Runs inside the next `signOut`, for example another process writing.
    func whileSigningOut(_ work: @escaping @Sendable () async -> Void) {
        duringSignOut = work
    }

    private var duringSignOut: (@Sendable () async -> Void)?

    /// Runs inside the next `signOut` after the local data was removed, as the engine's logout does.
    func afterRemovingDataWhileSigningOut(_ work: @escaping @Sendable () async -> Void) {
        afterRemoval = work
    }

    private var afterRemoval: (@Sendable () async -> Void)?

    func signOut(removingLocalDataWith remove: @Sendable () async throws -> Void) async throws {
        calls.append(.signOut)
        if let work = duringSignOut {
            duringSignOut = nil
            await work()
        }
        try await remove()
        if let work = afterRemoval {
            afterRemoval = nil
            await work()
        }
    }

    func request(_ trigger: SyncTrigger) async {
        calls.append(.request(trigger))
    }

    @discardableResult
    func syncNow() async -> SyncStatus {
        calls.append(.syncNow)
        return syncNowStatus
    }

    func refreshTask(_ id: TaskID) async {
        calls.append(.refreshTask(id))
    }

    func setNetworkAvailable(_ available: Bool) async {
        calls.append(.setNetworkAvailable(available))
    }
}
