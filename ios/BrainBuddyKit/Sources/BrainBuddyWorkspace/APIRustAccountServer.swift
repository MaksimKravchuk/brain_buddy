import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddySync
import Foundation

/// The server side of the Rust runtime's account lifecycle over the app's own REST client and
/// session token store: the same login and logout calls the legacy engine makes, with the same
/// words for a refusal. It owns no sync; a logout that cannot be sent now waits in the token
/// store as a pending logout, which the sync host sends when the network is back.
public struct APIRustAccountServer: RustAccountServer {
    private let tokenStore: any SessionTokenStore
    private let transport: any HTTPTransport
    private let identity: ClientIdentity
    private let now: @Sendable () -> Date

    public init(
        tokenStore: any SessionTokenStore, transport: any HTTPTransport = URLSessionTransport(),
        identity: ClientIdentity = .iOS, now: @escaping @Sendable () -> Date = { Date() }
    ) {
        self.tokenStore = tokenStore
        self.transport = transport
        self.identity = identity
        self.now = now
    }

    private func client(for url: URL, tokens: any SessionTokenStore) -> BrainBuddyAPIClient {
        BrainBuddyAPIClient(baseURL: url, transport: transport, tokenStore: tokens, clientVersion: identity.version, identity: identity)
    }

    public func login(serverURL: URL, email: String, password: String) async throws -> RustServerLogin {
        guard let url = BrainBuddyAPI.serverURL(from: serverURL.absoluteString) else {
            throw SignInFailure(message: "Use an https server address.")
        }
        let previous = try? tokenStore.token(for: url)
        let me: MeDTO
        do {
            me = try await client(for: url, tokens: tokenStore).login(email: email, password: password)
        } catch {
            throw Self.failure(error)
        }
        let account = LinkedAccount(id: me.id, email: me.email, displayName: me.displayName, serverURL: url, linkedAt: now())
        return RustServerLogin(account: account, deletionCancelled: me.deletionCancelled, previousToken: previous)
    }

    public func abandon(_ login: RustServerLogin) async {
        let url = login.account.serverURL
        let created = (try? tokenStore.token(for: url)) ?? nil
        if let previous = login.previousToken {
            try? tokenStore.setToken(previous, for: url)
        } else {
            try? tokenStore.removeToken(for: url)
        }
        if let created, created != login.previousToken { await end(PendingLogout(serverURL: url, token: created, signedOutAt: now())) }
    }

    public func beginSignOut(of account: LinkedAccount) async throws -> RustSignOutTicket {
        guard let token = try tokenStore.token(for: account.serverURL) else { return RustSignOutTicket(logout: nil) }
        let logout = PendingLogout(serverURL: account.serverURL, token: token, signedOutAt: now())
        try tokenStore.addPendingLogout(logout)
        return RustSignOutTicket(logout: logout)
    }

    public func finishSignOut(_ ticket: RustSignOutTicket, of account: LinkedAccount) async {
        try? tokenStore.removeToken(for: account.serverURL)
        guard let logout = ticket.logout else { return }
        if await send(logout) { try? tokenStore.removePendingLogout(logout) }
    }

    public func cancelSignOut(_ ticket: RustSignOutTicket) async {
        if let logout = ticket.logout { try? tokenStore.removePendingLogout(logout) }
    }

    /// Ends a session now, or leaves it as a pending logout.
    private func end(_ logout: PendingLogout) async {
        if await send(logout) { return }
        try? tokenStore.addPendingLogout(logout)
    }

    /// The shared rule (`PendingLogoutSender`): true when a retry would change nothing.
    private func send(_ logout: PendingLogout) async -> Bool {
        await PendingLogoutSender.send(logout, transport: transport, clientVersion: identity.version, identity: identity)
    }

    /// Sends the logouts that waited for the network and removes each one by the same rule the
    /// legacy engine uses: only when the server ended it or refused for good.
    public func drainPendingLogouts() async {
        guard let pending = try? tokenStore.pendingLogouts() else { return }
        for logout in pending {
            if Task.isCancelled { return }
            if await send(logout) { try? tokenStore.removePendingLogout(logout) }
        }
    }

    private static func failure(_ error: APIError) -> SignInFailure {
        switch error.kind {
        case .unauthorized: SignInFailure(message: "Check your email and password.", referenceID: error.referenceID)
        case .rateLimited: SignInFailure(message: "Too many attempts. Try again in a few minutes.", referenceID: error.referenceID)
        case .network: SignInFailure(message: SyncEngine.networkFailureMessage, referenceID: error.referenceID)
        case .cancelled: SignInFailure(message: SyncEngine.networkFailureMessage)
        default: SignInFailure(message: error.message, referenceID: error.referenceID)
        }
    }
}
