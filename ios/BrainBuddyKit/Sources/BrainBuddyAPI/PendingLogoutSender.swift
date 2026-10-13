import Foundation

/// The one rule for ending a session recorded as a `PendingLogout`, shared by the legacy sync
/// engine and the Rust runtime's account server so they cannot drift.
public enum PendingLogoutSender {
    /// `POST /auth/logout` carrying `logout.token` through a client of its own, so the stored
    /// sessions are not touched. True when the server ended the session, said it has none (a 401),
    /// or refused in a way a retry will not change: the pending logout may then be removed. False
    /// (a retryable failure: offline, a 5xx) keeps it for the next attempt.
    public static func send(
        _ logout: PendingLogout, transport: any HTTPTransport, clientVersion: String, identity: ClientIdentity
    ) async -> Bool {
        let client = BrainBuddyAPIClient(
            baseURL: logout.serverURL, transport: transport,
            tokenStore: InMemorySessionTokenStore(tokens: [logout.serverURL: logout.token]),
            clientVersion: clientVersion, identity: identity)
        do throws(APIError) {
            try await client.logout()
            return true
        } catch {
            return !error.isRetryable
        }
    }
}
