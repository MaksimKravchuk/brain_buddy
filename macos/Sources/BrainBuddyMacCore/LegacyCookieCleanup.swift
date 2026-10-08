import BrainBuddyAPI
import Foundation

#if canImport(FoundationNetworking)
    import FoundationNetworking
#endif

/// The cookies the pre-021 online mode left (`HTTPCookieStorage.shared` in the app).
package protocol LegacyCookieJar {
    var allCookies: [HTTPCookie] { get }
    func delete(_ cookie: HTTPCookie)
}

extension HTTPCookieStorage: LegacyCookieJar {
    package var allCookies: [HTTPCookie] { cookies ?? [] }
    package func delete(_ cookie: HTTPCookie) { deleteCookie(cookie) }
}

/// The HTTP response cache the pre-021 online mode filled (`URLCache.shared`).
package protocol LegacyResponseCache {
    func removeAllCachedResponses()
}

extension URLCache: LegacyResponseCache {}

/// Launch step 3 (contracts/mac-app-host.md §1; review c1 F36, c2 G25, G52, G60): once per Mac,
/// every `brainbuddy_session` cookie of the pre-021 app is handed to the kit's pending logouts,
/// bound to its own host, and deleted; the old HTTP response cache is emptied. Never while
/// `BRAINBUDDY_MAC_DATA_DIR` is set: the cookie storage and the Keychain are not redirected by a
/// dry run, so it touches neither. It runs on the main actor, where the app's cookie storage is
/// used; only its token-store writes leave it.
@MainActor
package struct LegacyCookieCleanup {
    package nonisolated static let cookieName = BrainBuddyAPI.sessionCookieName

    package enum Outcome: Hashable, Sendable {
        case skippedDryRun
        case alreadyDone
        case done(cookiesRemoved: Int, logoutsQueued: Int, kept: Int)
    }

    package var jar: any LegacyCookieJar
    package var cache: any LegacyResponseCache
    /// `~/Library/Caches/<bundle id>`, where `Cache.db*` and `fsCachedData` live; nil to skip.
    package var cacheDirectory: URL?
    package var tokenStore: any SessionTokenStore
    package var localState: MacLocalStateStore
    /// Server addresses this Mac knew (the stored `BrainBuddyAPIURL` and the default), so a logout
    /// for a cookie's host keeps that server's API path.
    package var knownServers: [URL]
    package var now: () -> Date
    package var log: any MacLogSink

    package init(
        jar: any LegacyCookieJar, cache: any LegacyResponseCache, cacheDirectory: URL?, tokenStore: any SessionTokenStore,
        localState: MacLocalStateStore, knownServers: [URL], now: @escaping () -> Date = { Date() },
        log: any MacLogSink = SystemMacLog()
    ) {
        self.jar = jar
        self.cache = cache
        self.cacheDirectory = cacheDirectory
        self.tokenStore = tokenStore
        self.localState = localState
        self.knownServers = knownServers
        self.now = now
        self.log = log
    }

    /// Runs the cleanup on the caller's actor; the token-store writes (the Keychain in the app) run
    /// in a detached task, off the main actor.
    package func run(isDryRun: Bool) async throws -> Outcome {
        guard !isDryRun else { return .skippedDryRun }
        guard localState.load()?.legacyCleanupDoneAt == nil else { return .alreadyDone }
        let sessions = jar.allCookies.filter { $0.name == Self.cookieName }
        let signedOutAt = now()
        let logouts = sessions.map { cookie in
            Self.logoutServer(for: cookie, knownServers: knownServers).map {
                PendingLogout(serverURL: $0, token: cookie.value, signedOutAt: signedOutAt)
            }
        }
        let tokenStore = self.tokenStore
        // Which handovers worked; a cookie whose session could not be handed over is kept for the next launch.
        let handedOver: [Bool] = await Task.detached {
            logouts.map { logout in
                guard let logout else { return true }
                return (try? tokenStore.addPendingLogout(logout)) != nil
            }
        }.value
        var removed = 0
        var kept = 0
        for (cookie, handed) in zip(sessions, handedOver) {
            guard handed else {
                kept += 1
                continue
            }
            jar.delete(cookie)
            removed += 1
        }
        let queued = zip(logouts, handedOver).filter { $0.0 != nil && $0.1 }.count
        cache.removeAllCachedResponses()
        if let cacheDirectory {
            for name in MacFiles.names(in: cacheDirectory) where name.hasPrefix("Cache.db") || name == "fsCachedData" {
                try? FileManager.default.removeItem(at: cacheDirectory.appendingPathComponent(name))
            }
        }
        if kept == 0 {
            let at = now()
            _ = try localState.update { $0.legacyCleanupDoneAt = at }
        }
        log.log(.sync, "legacy session cleanup cookies=\(removed) logouts=\(queued) kept=\(kept)")
        return .done(cookiesRemoved: removed, logoutsQueued: queued, kept: kept)
    }

    /// Where a cookie's session is ended: its own host and nothing else. A known server on that
    /// host keeps its API path; otherwise `https://<domain>`, or `http://localhost` for a
    /// localhost cookie. A plain-http cookie of any other host gets no logout.
    package nonisolated static func logoutServer(for cookie: HTTPCookie, knownServers: [URL]) -> URL? {
        var domain = cookie.domain.lowercased()
        while domain.hasPrefix(".") { domain.removeFirst() }
        guard !domain.isEmpty else { return nil }
        if let known = knownServers.first(where: { $0.host?.lowercased() == domain }),
            let server = BrainBuddyAPI.serverURL(from: known.absoluteString)
        {
            return server
        }
        if domain == "localhost" { return URL(string: "http://localhost") }
        guard cookie.isSecure else { return nil }
        return BrainBuddyAPI.serverURL(from: "https://\(domain)")
    }
}
