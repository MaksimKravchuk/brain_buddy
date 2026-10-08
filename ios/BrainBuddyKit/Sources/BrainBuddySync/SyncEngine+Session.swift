import BrainBuddyAPI
import BrainBuddyCore
import Foundation
import Synchronization

/// Server sessions beyond the linked one: ending a session (now, or when the
/// network is back), undoing a login the device won't link, and forgetting
/// sessions no account on the device owns.
extension SyncEngine {
    public func signOut(removingLocalDataWith remove: @Sendable () async throws -> Void) async throws {
        await waitForNativeCommit()
        invalidateNativeSignIn()
        guard let signedOut = account else { return try await remove() }
        signingOut = true
        await stopWork()
        // Recorded first and kept in the token store, so a crash after the removal still ends the
        // server session at the next launch. If the Keychain refuses, it expires by itself.
        let url = signedOut.serverURL
        let logout = storedToken(for: url).map { PendingLogout(serverURL: url, token: $0, signedOutAt: now()) }
        if let logout, (try? tokenStore.addPendingLogout(logout)) != nil { mayHavePendingLogouts = true }
        do {
            try await remove()
        } catch {
            if let logout { try? tokenStore.removePendingLogout(logout) }
            signingOut = false
            if status == .syncing { await setStatus(.idle(lastSyncedAt: lastSyncedAt)) }
            pullRequested = true
            kick()
            throw error
        }
        epoch += 1
        account = nil
        needsSignIn = false
        pullFirst = false
        failingSince = nil
        try? tokenStore.removeToken(for: url)
        signingOut = false
        // Signed out here at once; the server is told now, or when the network is back.
        if let logout, networkAvailable, await send(logout) == .done { try? tokenStore.removePendingLogout(logout) }
        await setStatus(.localOnly)
    }

    public func discardStaleSessions(loggingOut previous: LinkedAccount?) async {
        guard account == nil, signInsInProgress == 0 else { return }
        if let previous, let token = storedToken(for: previous.serverURL) {
            try? tokenStore.removeToken(for: previous.serverURL)
            await endSession(token: token, on: previous.serverURL)
        }
        // A sign-in may have started while that logout was on its way.
        guard account == nil, signInsInProgress == 0 else { return }
        try? tokenStore.removeAllTokens()
        retryPendingLogouts()
    }

    /// The session token stored for `url`, nil when there is none or it can't be read.
    func storedToken(for url: URL) -> String? {
        do {
            return try tokenStore.token(for: url)
        } catch {
            return nil
        }
    }

    /// Ends the session `token` opens on `serverURL`. When the server can't
    /// be told now (offline, or it failed), the logout waits in the token
    /// store and goes out once the network is back.
    func endSession(token: String, on serverURL: URL) async {
        let logout = PendingLogout(serverURL: serverURL, token: token, signedOutAt: now())
        if networkAvailable, await send(logout) == .done { return }
        do {
            try tokenStore.addPendingLogout(logout)
            mayHavePendingLogouts = true
        } catch {
            // The Keychain refused: the session expires on the server by itself.
        }
    }

    /// A login this device won't link (another account's changes are
    /// waiting, or the document couldn't be written): its session ends and
    /// the session stored before it is put back.
    func abandonSession(on url: URL, restoring previousToken: String?) async {
        let created = storedToken(for: url)
        if let previousToken {
            try? tokenStore.setToken(previousToken, for: url)
        } else {
            try? tokenStore.removeToken(for: url)
        }
        if let created, created != previousToken { await endSession(token: created, on: url) }
    }

    /// After another account replaced `previous` on this device, its session
    /// is stale: the login overwrote it when both share a server (the token
    /// read before the login is it); otherwise it is still stored.
    func retireSessions(of previous: LinkedAccount, replacedOn url: URL, previousToken: String?) async {
        if BrainBuddyAPI.sessionScope(for: previous.serverURL) == BrainBuddyAPI.sessionScope(for: url) {
            if let previousToken { await endSession(token: previousToken, on: previous.serverURL) }
        } else if let token = storedToken(for: previous.serverURL) {
            try? tokenStore.removeToken(for: previous.serverURL)
            await endSession(token: token, on: previous.serverURL)
        }
    }

    /// Sends the logouts that waited for the network, in the background
    /// (`waitUntilIdle()` waits for them).
    func retryPendingLogouts() {
        // A sign-out in progress has recorded its logout but not yet removed the data it protects.
        guard networkAvailable, mayHavePendingLogouts, logoutWork == nil, !signingOut else { return }
        let pending: [PendingLogout]
        do {
            pending = try tokenStore.pendingLogouts()
        } catch {
            return
        }
        guard !pending.isEmpty else {
            mayHavePendingLogouts = false
            return
        }
        logoutWork = Task { await self.sendPendingLogouts(pending) }
    }

    private func sendPendingLogouts(_ pending: [PendingLogout]) async {
        for logout in pending {
            guard networkAvailable else { break }
            if await send(logout) == .done { try? tokenStore.removePendingLogout(logout) }
        }
        logoutWork = nil
    }

    enum LogoutOutcome {
        /// The server ended the session, or said it has none (a 401), or
        /// refused in a way a retry won't change.
        case done
        case retryLater
    }

    /// `POST /auth/logout` carrying `logout.token`, through a client of its
    /// own, so the stored sessions are not touched.
    private func send(_ logout: PendingLogout) async -> LogoutOutcome {
        let client = BrainBuddyAPIClient(
            baseURL: logout.serverURL, transport: transport,
            tokenStore: InMemorySessionTokenStore(tokens: [logout.serverURL: logout.token]),
            clientVersion: configuration.clientVersion, identity: identity
        )
        do throws(APIError) {
            try await client.logout()
            return .done
        } catch {
            return error.isRetryable ? .retryLater : .done
        }
    }
}

extension LinkedAccount {
    /// The same user on the same server, however its address was spelled.
    func isSameAccount(as other: LinkedAccount) -> Bool {
        id == other.id && Self.serverKey(serverURL) == Self.serverKey(other.serverURL)
    }

    private static func serverKey(_ url: URL) -> String {
        var text = (BrainBuddyAPI.serverURL(from: url.absoluteString) ?? url).absoluteString.lowercased()
        while text.hasSuffix("/") { text.removeLast() }
        return text
    }
}

/// The account a sign-in's document write replaced, handed out of the
/// store's (synchronous, `@Sendable`) transform.
final class ReplacedAccount: Sendable {
    private let account = Mutex<LinkedAccount?>(nil)

    func set(_ replaced: LinkedAccount) { account.withLock { $0 = replaced } }

    var value: LinkedAccount? { account.withLock { $0 } }
}
