import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyPersistence
import BrainBuddySync
import BrainBuddyWorkspace
import Foundation
import Observation
import Synchronization

#if canImport(FoundationNetworking)
    import FoundationNetworking
#endif

/// Where the Mac keeps its files, and whether this run is a dry run (contracts/mac-app-host.md §1).
package struct MacHostConfiguration: Hashable, Sendable {
    /// The dry-run folder override: an absolute path to an existing folder.
    package static let dataDirectoryVariable = "BRAINBUDDY_MAC_DATA_DIR"
    package static let keychainService = "app.brainbuddy.mac.session"
    /// The pre-021 app's bundle id, kept so the Keychain and the single-instance lookup are stable.
    package static let bundleIdentifier = "com.brainbuddy.mac.prototype"
    package static let serverDefaultsKey = "BrainBuddyAPIURL"

    package enum Problem: Error, Hashable, Sendable {
        /// `BRAINBUDDY_MAC_DATA_DIR` is set but is not an absolute path to an existing folder. The
        /// app stops rather than fall back to the real folder, which a dry run must never touch.
        case invalidDataDirectory

        package var message: String {
            "BRAINBUDDY_MAC_DATA_DIR must be the full path of an existing folder. Brain Buddy didn't open anything."
        }
    }

    package var directory: URL
    /// True while `BRAINBUDDY_MAC_DATA_DIR` is set: no cookie, cache or Keychain item is touched.
    package var isDryRun: Bool

    package init(directory: URL, isDryRun: Bool) {
        self.directory = directory
        self.isDryRun = isDryRun
    }

    /// `~/Library/Application Support/BrainBuddyMac/`.
    package static var defaultDirectory: URL {
        let support =
            FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/Application Support")
        return support.appendingPathComponent("BrainBuddyMac", isDirectory: true)
    }

    package static func fromEnvironment(
        _ environment: [String: String] = ProcessInfo.processInfo.environment
    ) throws(Problem) -> MacHostConfiguration {
        guard let raw = environment[dataDirectoryVariable] else {
            return MacHostConfiguration(directory: defaultDirectory, isDryRun: false)
        }
        var isDirectory: ObjCBool = false
        guard raw.hasPrefix("/"), FileManager.default.fileExists(atPath: raw, isDirectory: &isDirectory), isDirectory.boolValue
        else { throw .invalidDataDirectory }
        return MacHostConfiguration(directory: URL(fileURLWithPath: raw, isDirectory: true), isDryRun: true)
    }

    package var storeURL: URL { directory.appendingPathComponent(LegacyFileNames.store) }

    /// `~/Library/Caches/<bundle id>`, the pre-021 HTTP cache's folder.
    package static var legacyCacheDirectory: URL? {
        FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first?
            .appendingPathComponent(bundleIdentifier, isDirectory: true)
    }

    /// The server addresses this Mac knew before 021: the stored one and the default.
    package static func knownServers(_ defaults: UserDefaults = .standard) -> [URL] {
        let stored = defaults.string(forKey: serverDefaultsKey).flatMap(BrainBuddyAPI.serverURL(from:))
        return [stored, BrainBuddyAPI.defaultServerURL].compactMap { $0 }
    }
}

/// The token store of a dry run (contracts/mac-app-host.md §1, data-model E9): it answers "no
/// token, no pending logouts" and calls nothing until a sign-in the person starts writes its token
/// (`setToken(_:for:interactive: true)`); only then is the real store opened, and every call
/// after goes to it.
package final class DeferredSessionTokenStore: SessionTokenStore {
    private let open: @Sendable () -> any SessionTokenStore
    private let opened = Mutex<(any SessionTokenStore)?>(nil)

    package init(opening open: @escaping @Sendable () -> any SessionTokenStore) {
        self.open = open
    }

    private var store: (any SessionTokenStore)? { opened.withLock { $0 } }

    package func token(for serverURL: URL) throws -> String? { try store?.token(for: serverURL) }

    package func setToken(_ token: String, for serverURL: URL) throws { try store?.setToken(token, for: serverURL) }

    package func setToken(_ token: String, for serverURL: URL, interactive: Bool) throws {
        if interactive {
            let open = self.open
            let store = opened.withLock { opened in
                if let opened { return opened }
                let store = open()
                opened = store
                return store
            }
            try store.setToken(token, for: serverURL, interactive: true)
        } else {
            try store?.setToken(token, for: serverURL, interactive: false)
        }
    }

    package func removeToken(for serverURL: URL) throws { try store?.removeToken(for: serverURL) }
    package func removeAllTokens() throws { try store?.removeAllTokens() }
    package func pendingLogouts() throws -> [PendingLogout] { try store?.pendingLogouts() ?? [] }
    package func addPendingLogout(_ logout: PendingLogout) throws { try store?.addPendingLogout(logout) }
    package func removePendingLogout(_ logout: PendingLogout) throws { try store?.removePendingLogout(logout) }
}

/// Launch step 4 (contracts/mac-app-host.md §1): the kit `Workspace` over `store.json` in the Mac's
/// folder, with a sync engine for the Mac (keychain service, client identity, 30 s pull age). The
/// engine's launch-time token cleanup runs on the engine actor, off the main actor; in a dry run
/// the token store makes no Keychain call until a sign-in the person starts.
@MainActor
package final class WorkspaceHost {
    package let configuration: MacHostConfiguration
    package let workspace: Workspace
    package let localState: MacLocalStateStore
    package let importer: LegacyImportCoordinator
    package let device: DeviceKind = .mac
    private let now: @Sendable () -> Date
    private var firstWriteRecorded = false

    package init(
        configuration: MacHostConfiguration, tokenStore: (any SessionTokenStore)? = nil,
        transport: (any HTTPTransport)? = nil, now: @escaping @Sendable () -> Date = { Date() },
        makeID: @escaping @Sendable () -> UUID = { UUID() }, tickScheduler: (any SyncScheduler)? = nil,
        log: any MacLogSink = SystemMacLog()
    ) {
        self.configuration = configuration
        self.now = now
        localState = MacLocalStateStore(directory: configuration.directory)
        importer = LegacyImportCoordinator(directory: configuration.directory, localState: localState, now: now, log: log)
        let store = FileDocumentStore(fileURL: configuration.storeURL)
        let base: @Sendable () -> any SessionTokenStore = { tokenStore ?? Self.systemTokenStore() }
        let tokens: any SessionTokenStore = configuration.isDryRun ? DeferredSessionTokenStore(opening: base) : base()
        let engine = SyncEngine(
            store: store, tokenStore: tokens, transport: transport ?? URLSessionTransport(), now: now,
            configuration: SyncConfiguration(pullInterval: SyncTiming.pullAge),
            identity: .macOS(version: BrainBuddyAPI.bundleVersion)
        )
        workspace = Workspace(
            store: store, sync: engine, now: now, makeID: makeID, tickScheduler: tickScheduler ?? TaskSyncScheduler()
        )
        firstWriteRecorded = localState.load()?.workspaceFirstWrittenAt != nil
        workspace.didPersist = { [weak self] in self?.recordFirstWrite() }
    }

    /// The login-keychain store of the Mac (data-model E9).
    nonisolated static func systemTokenStore() -> any SessionTokenStore {
        #if canImport(Security)
            KeychainSessionTokenStore(service: MacHostConfiguration.keychainService)
        #else
            InMemorySessionTokenStore()
        #endif
    }

    /// Data-model E7.1 "in use": the first successful write of `store.json` is recorded once.
    private func recordFirstWrite() {
        guard !firstWriteRecorded, MacFiles.exists(configuration.storeURL) else { return }
        let at = now()
        if (try? localState.update { state in
            if state.workspaceFirstWrittenAt == nil { state.workspaceFirstWrittenAt = at }
        }) != nil {
            firstWriteRecorded = true
        }
    }

    /// X-09 "Try again".
    package func retryLoad() async {
        await workspace.load()
    }

    /// X-09 "Set aside and start fresh", after the person confirmed: the unreadable `store.json`
    /// becomes `store.unreadable-<UTC>.json` (kept until sign-out) and an empty workspace opens. The
    /// set-aside file makes the folder "in use", so no later launch imports into it.
    package func startFresh() async {
        await workspace.resetUnreadableStore()
    }
}

/// Everything the launch needs from the outside world, so tests can run it in a temporary folder
/// with a fake cookie jar, cache, token store and transport.
package struct MacLaunchEnvironment {
    package var configuration: MacHostConfiguration
    package var tokenStore: (any SessionTokenStore)?
    package var transport: (any HTTPTransport)?
    package var cookieJar: any LegacyCookieJar
    package var responseCache: any LegacyResponseCache
    package var cacheDirectory: URL?
    package var knownServers: [URL]
    package var now: @Sendable () -> Date
    package var makeID: @Sendable () -> UUID
    package var log: any MacLogSink
    package var legacyLocking: any LegacyStoreLocking
    package var importHooks: LegacyImportTestHooks

    package init(
        configuration: MacHostConfiguration, tokenStore: (any SessionTokenStore)? = nil, transport: (any HTTPTransport)? = nil,
        cookieJar: any LegacyCookieJar, responseCache: any LegacyResponseCache, cacheDirectory: URL? = nil,
        knownServers: [URL] = [], now: @escaping @Sendable () -> Date = { Date() },
        makeID: @escaping @Sendable () -> UUID = { UUID() }, log: any MacLogSink = SystemMacLog(),
        legacyLocking: any LegacyStoreLocking = LockfLegacyStoreLocking(), importHooks: LegacyImportTestHooks = LegacyImportTestHooks()
    ) {
        self.configuration = configuration
        self.tokenStore = tokenStore
        self.transport = transport
        self.cookieJar = cookieJar
        self.responseCache = responseCache
        self.cacheDirectory = cacheDirectory
        self.knownServers = knownServers
        self.now = now
        self.makeID = makeID
        self.log = log
        self.legacyLocking = legacyLocking
        self.importHooks = importHooks
    }

    /// The app's own environment.
    package static func live(_ configuration: MacHostConfiguration) -> MacLaunchEnvironment {
        MacLaunchEnvironment(
            configuration: configuration, cookieJar: HTTPCookieStorage.shared, responseCache: URLCache.shared,
            cacheDirectory: MacHostConfiguration.legacyCacheDirectory, knownServers: MacHostConfiguration.knownServers()
        )
    }
}

/// Launch steps 2 – 5 (contracts/mac-app-host.md §1), after `SingleInstanceGuard`: the legacy
/// import with its X-05 notices, the legacy cookie and cache cleanup, `WorkspaceHost`, and
/// `workspace.load()`. Sync triggers start in PR-09. While it runs the window shows static
/// placeholders (X-05 "loading"); an unreadable `store.json` leaves `loadError` set (X-09).
@MainActor
@Observable
package final class MacLaunch {
    package enum Phase {
        case launching
        case ready(WorkspaceHost)
    }

    package private(set) var phase: Phase = .launching
    /// The window's model, once the workspace is loaded.
    package private(set) var model: BrainBuddyModel?
    @ObservationIgnored private let environment: MacLaunchEnvironment

    package init(environment: MacLaunchEnvironment) {
        self.environment = environment
    }

    package var host: WorkspaceHost? {
        if case .ready(let host) = phase { return host }
        return nil
    }

    /// Runs the steps once. `presentNotice` shows one X-05 alert and returns when the person chose
    /// "Continue" or "Show in Finder"; the notice is recorded as seen only then.
    package func run(presentNotice: @MainActor (LegacyImportNotice) async -> Void) async {
        guard case .launching = phase, host == nil else { return }
        let environment = self.environment
        let directory = environment.configuration.directory
        let importer = LegacyImportCoordinator(
            directory: directory, now: environment.now, makeID: environment.makeID, log: environment.log,
            legacyLocking: environment.legacyLocking, hooks: environment.importHooks
        )
        // Step 2: off the main actor (a large store takes a moment); nothing is shown meanwhile but
        // the placeholders.
        let result = await Task.detached { () -> Result<LegacyImportLaunchResult, any Error> in
            Result { try importer.run() }
        }.value
        switch result {
        case .success(let launch):
            for notice in launch.notices {
                await presentNotice(notice)
                try? importer.recordNoticeSeen(notice)
            }
        case .failure(let error):
            // Nothing was imported and nothing renamed; the next launch decides again.
            environment.log.log(.import, "import step failed class=\(String(describing: type(of: error)))")
        }

        // Step 3: once per Mac, never in a dry run.
        let cleanup = LegacyCookieCleanup(
            jar: environment.cookieJar, cache: environment.responseCache, cacheDirectory: environment.cacheDirectory,
            tokenStore: environment.tokenStore ?? WorkspaceHost.systemTokenStore(),
            localState: MacLocalStateStore(directory: directory), knownServers: environment.knownServers,
            now: environment.now, log: environment.log
        )
        if !environment.configuration.isDryRun {
            do {
                _ = try await cleanup.run(isDryRun: false)
            } catch {
                environment.log.log(.sync, "legacy session cleanup failed class=\(String(describing: type(of: error)))")
            }
        }

        // Steps 4 and 5.
        let host = WorkspaceHost(
            configuration: environment.configuration, tokenStore: environment.tokenStore, transport: environment.transport,
            now: environment.now, makeID: environment.makeID, log: environment.log
        )
        await host.workspace.load()
        model = BrainBuddyModel(workspace: host.workspace, localStateStore: host.localState, now: environment.now)
        phase = .ready(host)
    }
}

/// Design X-09's words: the main window's panel when `store.json` cannot be read, and its
/// person-started confirmation (contracts/mac-app-host.md §9).
package enum UnreadableWorkspaceCopy {
    package static let title = "We couldn't open your tasks"
    package static let message = "Your tasks are still on this Mac and nothing was changed."
    package static let tryAgain = "Try again"
    package static let tryingAgain = "Trying again…"
    package static let startFresh = "Start fresh…"
    package static let confirmTitle = "Set the file aside and start fresh?"
    package static let confirmMessage =
        "The unreadable file stays on this Mac, set aside where Brain Buddy won't use it. You start with empty lists; tasks you synced come back when you sign in."
    package static let keepTrying = "Keep trying"
    package static let confirm = "Set aside and start fresh"
}
