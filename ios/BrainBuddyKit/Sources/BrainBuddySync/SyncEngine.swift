import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyPersistence
import Foundation

/// Pushes the outbox and pulls the account's data. See `docs/native-ios-app.md`
/// › Sync for the protocol. CONTRACT: the initializer below is what
/// `Workspace.live` calls; implementations keep it.
public actor SyncEngine: SyncService {
    /// - Parameters:
    ///   - store: the same document store the workspace writes to.
    ///   - tokenStore: where the session cookie value lives (Keychain in the app).
    ///   - transport: HTTP; tests pass a fake server.
    ///   - now: the clock, injectable for tests.
    public init(
        store: any DocumentStore, tokenStore: any SessionTokenStore,
        transport: any HTTPTransport = URLSessionTransport(), now: @escaping @Sendable () -> Date = { Date() }
    ) {
        fatalError("SyncEngine is not implemented yet")
    }

    public func setEventHandler(_ handler: @escaping @Sendable (SyncEvent) async -> Void) async {
        fatalError("SyncEngine is not implemented yet")
    }

    public func start(account: LinkedAccount) async {
        fatalError("SyncEngine is not implemented yet")
    }

    public func signIn(serverURL: URL, email: String, password: String) async throws(SignInFailure) -> LinkedAccount {
        fatalError("SyncEngine is not implemented yet")
    }

    public func signOut() async {
        fatalError("SyncEngine is not implemented yet")
    }

    public func request(_ trigger: SyncTrigger) async {
        fatalError("SyncEngine is not implemented yet")
    }

    @discardableResult
    public func syncNow() async -> SyncStatus {
        fatalError("SyncEngine is not implemented yet")
    }

    public func refreshTask(_ id: TaskID) async {
        fatalError("SyncEngine is not implemented yet")
    }

    public func setNetworkAvailable(_ available: Bool) async {
        fatalError("SyncEngine is not implemented yet")
    }
}
