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
    /// The app's bundle id, kept so the Keychain and the single-instance lookup are stable.
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
    /// True while `BRAINBUDDY_MAC_DATA_DIR` is set: no Keychain item is touched.
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

    package var storeURL: URL { directory.appendingPathComponent(MacFileNames.store) }

    /// The server addresses this Mac knows: the stored one and the default.
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
///
/// Every token-store call is the engine's, on its actor: reads are non-interactive (no Keychain
/// prompt during routine sync; an item this build may not read is "Sign in again to sync"), and
/// only the person's sign-in in X-03 writes interactively (kit `SessionTokenStore`, PR-05).
@MainActor
package final class WorkspaceHost {
    /// `X-Client: brainbuddy-macos/<version>` (FR-031): the app bundle's marketing version, or "dev".
    package static var clientIdentity: ClientIdentity { .macOS(version: BrainBuddyAPI.bundleVersion) }

    package let configuration: MacHostConfiguration
    package let workspace: Workspace
    /// The workspace's engine, for the one trigger the workspace has no call for (`.foreground`
    /// when the window becomes visible again, contracts/mac-app-host.md §5).
    package let engine: SyncEngine
    package let localState: MacLocalStateStore
    package let device: DeviceKind = .mac
    private let now: @Sendable () -> Date
    private var firstWriteRecorded = false

    /// - Parameters:
    ///   - syncScheduler: the engine's debounce and retry timers (tests pass a manual one).
    ///   - tickScheduler: the kit's 15 s `.periodic` ticker.
    package init(
        configuration: MacHostConfiguration, tokenStore: (any SessionTokenStore)? = nil,
        transport: (any HTTPTransport)? = nil, now: @escaping @Sendable () -> Date = { Date() },
        makeID: @escaping @Sendable () -> UUID = { UUID() }, tickScheduler: (any SyncScheduler)? = nil,
        syncScheduler: (any SyncScheduler)? = nil, log: any MacLogSink = SystemMacLog(),
        rust: RustWorkspaceSelection? = nil, rustLifecycle: (any RustAccountLifecyclePort)? = nil
    ) {
        self.configuration = configuration
        self.now = now
        localState = MacLocalStateStore(directory: configuration.directory)
        let store = FileDocumentStore(fileURL: configuration.storeURL)
        let base: @Sendable () -> any SessionTokenStore = { tokenStore ?? Self.systemTokenStore() }
        let tokens: any SessionTokenStore = configuration.isDryRun ? DeferredSessionTokenStore(opening: base) : base()
        let identity = Self.clientIdentity
        engine = SyncEngine(
            store: store, tokenStore: tokens, transport: transport ?? URLSessionTransport(), now: now,
            configuration: SyncConfiguration(
                scheduler: syncScheduler ?? TaskSyncScheduler(), pullInterval: SyncTiming.pullAge,
                clientVersion: identity.version
            ),
            identity: identity
        )
        workspace = Workspace(
            store: store, sync: engine, rust: rust, rustLifecycle: rustLifecycle, now: now, makeID: makeID,
            tickScheduler: tickScheduler ?? TaskSyncScheduler()
        )
        firstWriteRecorded = localState.load()?.workspaceFirstWrittenAt != nil
        workspace.didPersist = { [weak self] in self?.recordFirstWrite() }
    }

    /// The login-keychain store of the Mac (data-model E9).
    package nonisolated static func systemTokenStore() -> any SessionTokenStore {
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
    /// becomes `store.unreadable-<UTC>.json` (kept until sign-out) and an empty workspace opens.
    package func startFresh() async {
        await workspace.resetUnreadableStore()
    }
}

/// Everything the launch needs from the outside world, so tests can run it in a temporary folder
/// with a fake token store and transport.
package struct MacLaunchEnvironment {
    package var configuration: MacHostConfiguration
    package var tokenStore: (any SessionTokenStore)?
    package var transport: (any HTTPTransport)?
    package var now: @Sendable () -> Date
    package var makeID: @Sendable () -> UUID
    package var log: any MacLogSink
    /// The kit's 15 s ticker and the engine's timers; nil is real time (tests pass manual ones).
    package var tickScheduler: (any SyncScheduler)?
    package var syncScheduler: (any SyncScheduler)?
    /// The shared Rust runtime's environment (spec 026, T044); nil keeps the launch exactly the
    /// legacy one. With it, the launch follows the persisted selection in the Mac's folder (the
    /// same one the app reads), and the pilot switch decides whether a first selection is made.
    package var rustRuntime: RustRuntimeEnvironment?
    package var rustPilot: RustRuntimePilotSwitch

    package init(
        configuration: MacHostConfiguration, tokenStore: (any SessionTokenStore)? = nil, transport: (any HTTPTransport)? = nil,
        now: @escaping @Sendable () -> Date = { Date() },
        makeID: @escaping @Sendable () -> UUID = { UUID() }, log: any MacLogSink = SystemMacLog(),
        tickScheduler: (any SyncScheduler)? = nil, syncScheduler: (any SyncScheduler)? = nil,
        rustRuntime: RustRuntimeEnvironment? = nil, rustPilot: RustRuntimePilotSwitch = RustRuntimePilotSwitch()
    ) {
        self.rustRuntime = rustRuntime
        self.rustPilot = rustPilot
        self.tickScheduler = tickScheduler
        self.syncScheduler = syncScheduler
        self.configuration = configuration
        self.tokenStore = tokenStore
        self.transport = transport
        self.now = now
        self.makeID = makeID
        self.log = log
    }

    /// The app's own environment.
    package static func live(_ configuration: MacHostConfiguration) -> MacLaunchEnvironment {
        MacLaunchEnvironment(configuration: configuration, rustRuntime: try? RustRuntimeEnvironment.mac(configuration))
    }
}

extension RustRuntimeEnvironment {
    /// The Mac's environment: its own folder, its login-keychain token store and its REST identity.
    /// A dry run (`BRAINBUDDY_MAC_DATA_DIR`) opens no Keychain item until a sign-in the person starts.
    package static func mac(
        _ configuration: MacHostConfiguration, tokenStore: (any SessionTokenStore)? = nil,
        transports: (any RustTransportProvider)? = nil
    ) throws -> RustRuntimeEnvironment {
        let base: @Sendable () -> any SessionTokenStore = { tokenStore ?? WorkspaceHost.systemTokenStore() }
        let tokens: any SessionTokenStore = configuration.isDryRun ? DeferredSessionTokenStore(opening: base) : base()
        return RustRuntimeEnvironment(
            location: .directory(configuration.directory), legacyStoreURL: configuration.storeURL,
            bridge: try RustBridgeRuntime(),
            // The Mac syncs for the life of the process (no background signal): its foreground,
            // window and network events reach the host through the workspace.
            transports: transports ?? RustSyncTransportProvider(
                tokenStore: tokens, identity: .macOS(version: BrainBuddyAPI.bundleVersion)),
            server: APIRustAccountServer(tokenStore: tokens, identity: .macOS(version: BrainBuddyAPI.bundleVersion)))
    }
}

/// The launch steps of contracts/mac-app-host.md §1 after `SingleInstanceGuard`: the Rust runtime's
/// selection, `WorkspaceHost`, and `workspace.load()`. Step 6, `SyncTriggerSource.start()`,
/// follows in the app once the window has the workspace (PR-09). While it runs the window shows
/// static placeholders (X-05 "loading"); an unreadable `store.json` leaves `loadError` set (X-09).
///
/// When the Rust runtime cannot be opened the launch stops at `.importFailed`: no `WorkspaceHost`
/// and the retired `store.json` as it was. "Try again" (`retryImport`) runs the launch again.
@MainActor
@Observable
package final class MacLaunch {
    package enum Phase {
        case launching
        /// The runtime could not be opened; nothing opened. `retryImport()` runs the launch again.
        case importFailed
        case ready(WorkspaceHost)
    }

    package private(set) var phase: Phase = .launching
    /// The window's model, once the workspace is loaded.
    package private(set) var model: BrainBuddyModel?
    /// The window's sync UI (X-01 – X-04, X-07), once the workspace is loaded.
    package private(set) var sync: MacSyncController?
    /// A launch or a retry is running ("Trying again…").
    package private(set) var isRunning = false
    @ObservationIgnored private let environment: MacLaunchEnvironment

    package init(environment: MacLaunchEnvironment) {
        self.environment = environment
    }

    package var host: WorkspaceHost? {
        if case .ready(let host) = phase { return host }
        return nil
    }

    package var importFailed: Bool {
        if case .importFailed = phase { return true }
        return false
    }

    /// Runs the steps once.
    package func run() async {
        guard case .launching = phase, !isRunning else { return }
        await proceed()
    }

    /// The import-failed state's "Try again": the launch again.
    package func retryImport() async {
        guard importFailed, !isRunning else { return }
        await proceed()
    }

    private func proceed() async {
        isRunning = true
        defer { isRunning = false }
        let environment = self.environment
        let directory = environment.configuration.directory

        // Housekeeping every launch repeats (data-model E7): the sidecar exists before anything
        // reads it, review marks older than 30 days go, and a `store.json` that is already there
        // counts as written. A failure here is logged and never keeps the workspace closed.
        let launchedAt = environment.now()
        let storeURL = environment.configuration.storeURL
        do {
            try MacLocalStateStore(directory: directory).update { state in
                state.pruneOldMarks(now: launchedAt)
                if MacFiles.exists(storeURL), state.workspaceFirstWrittenAt == nil {
                    state.workspaceFirstWrittenAt = launchedAt
                }
            }
        } catch {
            environment.log.log(.import, "launch housekeeping failed class=\(String(describing: type(of: error)))")
        }

        // The runtime (spec 026, T044): the install's persisted selection, the same file the iOS
        // app and its widgets read in their folder. With the pilot switch off and no selection
        // this is `.legacy` and nothing above or below changes. A store that cannot be opened
        // stops the launch like a failed import: the retired file is never opened instead.
        var rustSelection: RustWorkspaceSelection?
        var rustLifecycle: (any RustAccountLifecyclePort)?
        if environment.rustRuntime == nil {
            // The bridge could not initialize (`live` keeps no environment then). An install that
            // already has a selection is the Rust runtime's: it must not fall back to the retired
            // file, whose edits would fork from the selected store. A selection that cannot be read
            // is the same. Only an unselected install may go on as legacy.
            do {
                if try RustRuntimeSelectionStore(location: .directory(directory)).load() != nil {
                    environment.log.log(.import, "rust runtime unavailable code=RUNTIME_INIT_FAILED")
                    phase = .importFailed
                    return
                }
            } catch {
                environment.log.log(.import, "rust runtime unavailable code=SELECTION_UNREADABLE")
                phase = .importFailed
                return
            }
        }
        if let rustEnvironment = environment.rustRuntime {
            switch await RustRuntimeLauncher(environment: rustEnvironment, pilot: environment.rustPilot).resolve() {
            case .legacy:
                break
            case .unavailable(let code):
                environment.log.log(.import, "rust runtime unavailable code=\(code)")
                phase = .importFailed
                return
            case .rust(let selection, let lifecycle):
                rustSelection = selection
                rustLifecycle = lifecycle
            }
        }

        // Steps 4 and 5. A `store.json` that cannot be read is X-09 (`loadError`), never replaced.
        let host = WorkspaceHost(
            configuration: environment.configuration, tokenStore: environment.tokenStore, transport: environment.transport,
            now: environment.now, makeID: environment.makeID, tickScheduler: environment.tickScheduler,
            syncScheduler: environment.syncScheduler, log: environment.log, rust: rustSelection, rustLifecycle: rustLifecycle
        )
        await host.workspace.load()
        let model = BrainBuddyModel(workspace: host.workspace, localStateStore: host.localState, now: environment.now)
        let sync = MacSyncController(host: host, now: environment.now, log: environment.log)
        sync.signOut.didSignOut = { [weak model] in model?.didSignOut() }
        sync.didSync = { [weak model] in await model?.refreshAgentsAfterSync() }
        self.model = model
        self.sync = sync
        phase = .ready(host)
    }
}

/// The words of the launch's stopped state, in the X-09 pattern (one calm panel in place of the
/// lists, "Try again" the default). It says the previous version's file is untouched; there is no
/// "Start fresh", which would fork from the retired file.
package enum LegacyImportFailedCopy {
    package static let title = "Brain Buddy couldn't finish the update"
    package static let message =
        "Brain Buddy couldn't carry over your tasks from the previous version, so it hasn't opened anything yet. The file from the previous version was left exactly as it was."
    package static let hint = "Make sure your Mac has free space, then try again."
    package static let tryAgain = "Try again"
    package static let tryingAgain = "Trying again…"
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
