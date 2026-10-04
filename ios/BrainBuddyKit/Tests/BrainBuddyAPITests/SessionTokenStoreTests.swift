import Foundation
import Testing

@testable import BrainBuddyAPI

@Suite("Session token stores")
struct SessionTokenStoreTests {
    private let prod = URL(string: "https://brain-buddy-frontend.fly.dev/api")!
    private let dev = URL(string: "http://localhost:8000/api")!
    private let date = Date(timeIntervalSinceReferenceDate: 812_345_678)

    @Test("Removing every token forgets the sessions of all servers, not the logouts still to send")
    func removesAllTokensButKeepsPendingLogouts() throws {
        let store = InMemorySessionTokenStore(tokens: [prod: "a", dev: "b"])
        let logout = PendingLogout(serverURL: prod, token: "old", signedOutAt: date)
        try store.addPendingLogout(logout)

        try store.removeAllTokens()
        #expect(try store.token(for: prod) == nil)
        #expect(try store.token(for: dev) == nil)
        #expect(try store.pendingLogouts() == [logout])
    }

    @Test("Pending logouts are kept apart from the sessions, in order, until each is removed")
    func keepsPendingLogouts() throws {
        let store = InMemorySessionTokenStore(tokens: [prod: "current"])
        let first = PendingLogout(serverURL: prod, token: "one", signedOutAt: date)
        let second = PendingLogout(serverURL: dev, token: "two", signedOutAt: date.addingTimeInterval(60))
        try store.addPendingLogout(first)
        try store.addPendingLogout(second)
        try store.addPendingLogout(first)

        #expect(try store.pendingLogouts() == [second, first], "adding again moves it to the end, once")
        #expect(try store.token(for: prod) == "current", "a pending logout is not a session")
        try store.removePendingLogout(first)
        #expect(try store.pendingLogouts() == [second])
    }

    @Test("Stores that keep only the current session have nothing to enumerate")
    func defaultsForMinimalStores() throws {
        let store: any SessionTokenStore = CurrentSessionOnly()
        try store.addPendingLogout(PendingLogout(serverURL: prod, token: "x", signedOutAt: date))
        #expect(try store.pendingLogouts().isEmpty)
        try store.removeAllTokens()
    }
}

/// A conformer relying on the protocol's defaults.
private final class CurrentSessionOnly: SessionTokenStore {
    func token(for serverURL: URL) throws -> String? { nil }
    func setToken(_ token: String, for serverURL: URL) throws {}
    func removeToken(for serverURL: URL) throws {}
}
