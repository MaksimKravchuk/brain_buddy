import BrainBuddyAPI
import BrainBuddyCore
import Foundation
import Testing

@testable import BrainBuddyMacCore

#if canImport(FoundationNetworking)
    import FoundationNetworking
#endif

/// Launch step 3 (contracts/mac-app-host.md §1, §8; T096): the pre-021 session cookies are ended at
/// their own host and deleted, the old HTTP cache is emptied, once; a dry run touches none of it.
@Suite("Legacy cookie cleanup")
@MainActor
struct LegacyCookieCleanupTests {
    private let api = URL(string: "https://api.example.com")!

    private func jar() -> FakeCookieJar {
        FakeCookieJar([
            FakeCookieJar.session("token-api", domain: "api.example.com"),
            FakeCookieJar.session("token-brain", domain: ".brain.example.org"),
            FakeCookieJar.session("token-local", domain: "localhost", secure: false),
            FakeCookieJar.session("token-plain", domain: "plain.example.net", secure: false),
            FakeCookieJar.session("other", domain: "api.example.com", name: "theme"),
        ])
    }

    private func cleanup(
        _ folder: TemporaryFolder, jar: FakeCookieJar, cache: FakeResponseCache, tokens: SpyTokenStore, cacheDirectory: URL? = nil
    ) -> LegacyCookieCleanup {
        LegacyCookieCleanup(
            jar: jar, cache: cache, cacheDirectory: cacheDirectory, tokenStore: tokens,
            localState: MacLocalStateStore(directory: folder.url),
            knownServers: [URL(string: "https://brain.example.org/api")!], now: TestClock().provider, log: CapturingMacLog()
        )
    }

    @Test("021-FR-005 021-FR-029 every session cookie goes, each ended at its own host; a plain-http one on another host gets no logout")
    func cookiesAreEndedAtTheirOwnHost() async throws {
        let folder = TemporaryFolder()
        let cookies = jar()
        let cache = FakeResponseCache()
        let tokens = SpyTokenStore()
        let caches = folder.root.appendingPathComponent("Caches/com.brainbuddy.mac.prototype", isDirectory: true)
        try FileManager.default.createDirectory(at: caches.appendingPathComponent("fsCachedData"), withIntermediateDirectories: true)
        for name in ["Cache.db", "Cache.db-wal", "Cache.db-shm"] { try Data("cached".utf8).write(to: caches.appendingPathComponent(name)) }

        let outcome = try await cleanup(folder, jar: cookies, cache: cache, tokens: tokens, cacheDirectory: caches).run(isDryRun: false)

        #expect(outcome == .done(cookiesRemoved: 4, logoutsQueued: 3, kept: 0))
        #expect(cookies.allCookies.map(\.name) == ["theme"], "only the session cookies go")
        let servers = tokens.storedPending.map(\.serverURL.absoluteString).sorted()
        #expect(servers == ["http://localhost", "https://api.example.com", "https://brain.example.org/api"])
        #expect(tokens.storedPending.first { $0.serverURL == api }?.token == "token-api")
        #expect(!tokens.storedPending.contains { $0.token == "token-plain" })
        #expect(tokens.calls.allSatisfy { !$0.onMainThread }, "the token store is written off the main thread")
        #expect(cache.cleared == 1 && cache.entries == 0)
        #expect(MacFiles.names(in: caches).isEmpty, "Cache.db* and fsCachedData are removed")
        #expect(MacLocalStateStore(directory: folder.url).load()?.legacyCleanupDoneAt == TestClock.importTime)
    }

    #if canImport(Darwin)
        @Test("021-FR-005 a response cached by the pre-021 online mode is gone")
        func realCacheIsEmptied() async throws {
            let folder = TemporaryFolder()
            let cache = URLCache(memoryCapacity: 1 << 20, diskCapacity: 1 << 20, directory: folder.root.appendingPathComponent("cache"))
            let request = URLRequest(url: URL(string: "https://api.example.com/api/auth/me")!)
            let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: "HTTP/1.1", headerFields: ["Cache-Control": "max-age=600"])!
            cache.storeCachedResponse(CachedURLResponse(response: response, data: Data("{\"email\":\"alex@example.com\"}".utf8)), for: request)
            #expect(cache.cachedResponse(for: request) != nil)
            let cleanup = LegacyCookieCleanup(
                jar: FakeCookieJar(), cache: cache, cacheDirectory: nil, tokenStore: SpyTokenStore(),
                localState: MacLocalStateStore(directory: folder.url), knownServers: [], log: CapturingMacLog()
            )
            _ = try await cleanup.run(isDryRun: false)
            #expect(cache.cachedResponse(for: request) == nil)
        }
    #endif

    @Test("021-FR-005 a second launch does nothing")
    func runsOnce() async throws {
        let folder = TemporaryFolder()
        let tokens = SpyTokenStore()
        _ = try await cleanup(folder, jar: jar(), cache: FakeResponseCache(), tokens: tokens).run(isDryRun: false)
        let cookies = FakeCookieJar([FakeCookieJar.session("late", domain: "api.example.com")])
        let cache = FakeResponseCache()
        let outcome = try await cleanup(folder, jar: cookies, cache: cache, tokens: tokens).run(isDryRun: false)
        #expect(outcome == .alreadyDone)
        #expect(cookies.allCookies.count == 1 && cache.cleared == 0)
    }

    @Test("021-FR-005 a cookie whose session could not be handed over is kept for the next launch")
    func failedHandOverKeepsTheCookie() async throws {
        let folder = TemporaryFolder()
        let cookies = FakeCookieJar([FakeCookieJar.session("token-api", domain: "api.example.com")])
        let outcome = try await LegacyCookieCleanup(
            jar: cookies, cache: FakeResponseCache(), cacheDirectory: nil, tokenStore: FailingTokenStore(),
            localState: MacLocalStateStore(directory: folder.url), knownServers: [], log: CapturingMacLog()
        ).run(isDryRun: false)
        #expect(outcome == .done(cookiesRemoved: 0, logoutsQueued: 0, kept: 1))
        #expect(cookies.allCookies.count == 1)
        #expect(MacLocalStateStore(directory: folder.url).load()?.legacyCleanupDoneAt == nil, "it runs again next launch")
    }

    @Test("021-FR-005 021-FR-029 with BRAINBUDDY_MAC_DATA_DIR set, launch steps 3 and 4 touch no cookie, cache or token store, and send nothing")
    func dryRunTouchesNothing() async throws {
        let folder = TemporaryFolder()
        let cookies = jar()
        let cache = FakeResponseCache()
        let tokens = SpyTokenStore(
            token: "keep-me", for: api, pending: [PendingLogout(serverURL: api, token: "pending", signedOutAt: TestClock.importTime)]
        )
        let transport = CountingTransport()
        let launch = MacLaunch(
            environment: MacLaunchEnvironment(
                configuration: MacHostConfiguration(directory: folder.url, isDryRun: true), tokenStore: tokens,
                transport: transport, cookieJar: cookies, responseCache: cache, knownServers: [api], now: TestClock().provider,
                log: CapturingMacLog()
            )
        )
        await launch.run { _ in }
        try await Task.sleep(nanoseconds: 100_000_000)

        #expect(launch.host != nil)
        #expect(cookies.allCookies.count == 5 && cache.cleared == 0)
        #expect(tokens.calls.isEmpty, "no token-store call before a sign-in the person starts")
        #expect(tokens.storedTokens.count == 1 && tokens.storedPending.count == 1, "both items stay")
        #expect(transport.requests.isEmpty)
        #expect(MacLocalStateStore(directory: folder.url).load()?.legacyCleanupDoneAt == nil)
    }

    @Test("021-FR-005 the dry run's token store opens the real one only at a person-started sign-in")
    func dryRunStoreOpensAtSignIn() throws {
        let tokens = SpyTokenStore(token: "keep-me", for: api)
        let deferred = DeferredSessionTokenStore(opening: { tokens })
        #expect(try deferred.token(for: api) == nil && (try deferred.pendingLogouts()).isEmpty)
        try deferred.removeAllTokens()
        try deferred.setToken("routine", for: api)
        #expect(tokens.calls.isEmpty)
        try deferred.setToken("signed-in", for: api, interactive: true)
        #expect(tokens.calls.map(\.name) == ["setTokenInteractive"])
        #expect(try deferred.token(for: api) == "signed-in")
    }

    @Test("021-FR-029 an upgraded Mac sends exactly one logout, to the cookie's own host, and keeps its pending logouts at launch")
    func upgradedLaunchSendsOneLogout() async throws {
        let folder = TemporaryFolder()
        let tokens = SpyTokenStore(token: "stale", for: URL(string: "https://old.example.com")!)
        let transport = CountingTransport()
        let launch = MacLaunch(
            environment: MacLaunchEnvironment(
                configuration: MacHostConfiguration(directory: folder.url, isDryRun: false), tokenStore: tokens,
                transport: transport, cookieJar: FakeCookieJar([FakeCookieJar.session("token-api", domain: "api.example.com")]),
                responseCache: FakeResponseCache(), now: TestClock().provider, log: CapturingMacLog()
            )
        )
        await launch.run { _ in }
        for _ in 0..<50 where transport.requests.isEmpty { try await Task.sleep(nanoseconds: 20_000_000) }

        #expect(transport.requests.count == 1)
        let logout = try #require(transport.requests.first)
        #expect(logout.method == .post && logout.url.host == "api.example.com" && logout.url.path == "/auth/logout")
        #expect(logout.body == nil || logout.body?.isEmpty == true, "a logout carries no task data")
        #expect(tokens.storedTokens.isEmpty, "with no account linked, the stale session is forgotten")
        #expect(tokens.calls.allSatisfy { !$0.onMainThread })
    }
}

/// A token store whose writes fail (a Keychain that refuses).
private struct FailingTokenStore: SessionTokenStore {
    struct Refused: Error {}
    func token(for serverURL: URL) throws -> String? { nil }
    func setToken(_ token: String, for serverURL: URL) throws { throw Refused() }
    func removeToken(for serverURL: URL) throws {}
    func addPendingLogout(_ logout: PendingLogout) throws { throw Refused() }
}
