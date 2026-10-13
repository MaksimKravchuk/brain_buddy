import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyPersistence
import BrainBuddySync
import Foundation

// Production selection of the Rust runtime (spec 026, T044, PR-54 pilot), behind the pilot switch.
// The app resolves it once at launch, before the legacy workspace loads: a persisted selection
// opens its store; with no selection and the switch on, the legacy file is imported (the PR-41/42
// importers) and, only when the outbox status says `mayRun`, the install is switched; anything
// else stays legacy and is tried again at the next launch. Widgets and App Intents never import
// and never read the switch: they follow the selection file (`openForExtension`).

/// What the sync host needs to drive one runtime for one account.
public struct RustTransportContext: Sendable {
    public let runtime: RustWorkspaceRuntime
    public let workspaceID: String
    public let databaseURL: URL
    /// nil while the identity is account-less: nothing is sent.
    public let account: LinkedAccount?
    /// The install's device identity for this workspace identity (random, allocated once).
    public let deviceID: String
    /// True for the sign-in that just created this binding: every earlier request is fenced out.
    /// False for a launch, which resumes the same still-valid session.
    public var freshAuthentication = false
    /// Whether the weekly review is exposed (the policy the feed is applied under).
    public var reviewEnabled = false
}

/// THE SEAM for the Swift sync host (PR-54 host slice): given an open runtime and who it belongs
/// to, the port that wakes, drives and closes its transport. The sign-in, the sign-out and the
/// launch ask for one per binding; the workspace closes the port it replaces. Registering the
/// device epoch with the server and binding the scope and device (scope = the account's id, device
/// = `deviceID`) is the host's first request, as `bb-client`'s sync session defines it.
public protocol RustTransportProvider: Sendable {
    func transport(for context: RustTransportContext) -> any SyncRuntimePort
}

/// The provider until the sync host is installed: nothing is sent, and nothing says "synced".
public struct PendingRustTransportProvider: RustTransportProvider {
    public init() {}

    public func transport(for context: RustTransportContext) -> any SyncRuntimePort { PendingRustSyncRuntimePort() }
}

/// Everything the runtime selection and the account lifecycle need from the outside.
public struct RustRuntimeEnvironment: Sendable {
    public var location: RustRuntimeLocation
    /// The retired document, the source of the one import.
    public var legacyStoreURL: URL
    public var bridge: RustBridgeRuntime
    public var transports: any RustTransportProvider
    public var server: any RustAccountServer
    public var reviewEnabled: Bool
    public var busyTimeoutMilliseconds: UInt32
    public var now: @Sendable () -> Date
    public var makeID: @Sendable () -> UUID

    public init(
        location: RustRuntimeLocation, legacyStoreURL: URL, bridge: RustBridgeRuntime,
        transports: any RustTransportProvider = PendingRustTransportProvider(), server: any RustAccountServer,
        reviewEnabled: Bool = false, busyTimeoutMilliseconds: UInt32 = 2_000,
        now: @escaping @Sendable () -> Date = { Date() }, makeID: @escaping @Sendable () -> UUID = { UUID() }
    ) {
        self.location = location
        self.legacyStoreURL = legacyStoreURL
        self.bridge = bridge
        self.transports = transports
        self.server = server
        self.reviewEnabled = reviewEnabled
        self.busyTimeoutMilliseconds = busyTimeoutMilliseconds
        self.now = now
        self.makeID = makeID
    }

    var selections: RustRuntimeSelectionStore { RustRuntimeSelectionStore(location: location) }

    func facade() -> RustDomainFacade {
        RustDomainFacade(runtime: bridge, context: RustDomainContext(deviceTimeZone: TimeZone.current.identifier))
    }

    func openRuntime(_ workspaceID: String) async throws -> RustWorkspaceRuntime {
        try await bridge.openStore(workspaceID: workspaceID, databaseURL: location.databaseURL(workspaceID),
            busyTimeoutMilliseconds: busyTimeoutMilliseconds)
    }

    func selection(_ runtime: RustWorkspaceRuntime, for record: RustRuntimeSelectionRecord) -> RustWorkspaceSelection {
        let context = RustTransportContext(runtime: runtime, workspaceID: record.workspaceID,
            databaseURL: location.databaseURL(record.workspaceID), account: record.account, deviceID: record.deviceID,
            reviewEnabled: record.reviewEnabled)
        return RustWorkspaceSelection(runtime: runtime, facade: facade(), transport: transports.transport(for: context),
            account: record.account, reviewEnabled: record.reviewEnabled, startup: .prepared)
    }

    func newIdentity() -> String { "local-\(makeID().uuidString.lowercased())" }
}

public struct RustRuntimeLauncher: Sendable {
    public enum LegacyReason: Equatable, Sendable {
        /// The switch is off (the production default).
        case pilotOff
        /// The switch is on and the move did not finish; nothing was changed and the next launch
        /// tries again. The code names the step; it never carries user text.
        case notReady(code: String)
    }

    public enum Resolution: Sendable {
        case legacy(LegacyReason)
        /// The install's runtime. Hand `lifecycle` to the workspace for sign-in and sign-out.
        case rust(RustWorkspaceSelection, lifecycle: any RustAccountLifecyclePort)
        /// The install is the Rust runtime's but its store cannot be opened (busy, written by a
        /// newer build, damaged). The app must not open the legacy file instead.
        case unavailable(code: String)
    }

    /// The identity a legacy import fills. Fixed, so an import that finished but whose selection
    /// was not saved (a crash) resumes into the same store instead of making a second one.
    public static let importedWorkspaceID = "imported"

    public let environment: RustRuntimeEnvironment
    public let pilot: RustRuntimePilotSwitch

    public init(environment: RustRuntimeEnvironment, pilot: RustRuntimePilotSwitch = RustRuntimePilotSwitch()) {
        self.environment = environment
        self.pilot = pilot
    }

    public func resolve() async -> Resolution {
        let record: RustRuntimeSelectionRecord?
        do {
            record = try environment.selections.load()
        } catch {
            return .unavailable(code: "SELECTION_UNREADABLE")
        }
        if let record { return await open(record) }
        guard pilot.isEnabled else { return .legacy(.pilotOff) }
        return await select()
    }

    // MARK: A persisted selection

    private func open(_ record: RustRuntimeSelectionRecord) async -> Resolution {
        do {
            let runtime = try await environment.openRuntime(record.workspaceID)
            // A sign-in that saved the selection and crashed before its merge committed is finished
            // here (idempotent: a merge that did commit reports `.alreadyLinked`, queueing nothing).
            if let account = record.account {
                switch try await environment.linkAndMerge(
                    runtime, account: account, deviceID: record.deviceID, facade: environment.facade(),
                    reviewEnabled: record.reviewEnabled)
                {
                case .merged, .alreadyLinked: break
                case .otherAccount:
                    try? await runtime.close()
                    return .unavailable(code: "ACCOUNT_LINK_MISMATCH")
                }
            }
            return .rust(environment.selection(runtime, for: record), lifecycle: lifecycle())
        } catch {
            return .unavailable(code: Self.code(error))
        }
    }

    func lifecycle() -> HostRustAccountLifecycle { HostRustAccountLifecycle(environment: environment) }

    // MARK: The move (pilot switch on, no selection yet)

    private func select() async -> Resolution {
        let hasLegacyFile = FileManager.default.fileExists(atPath: environment.legacyStoreURL.path)
        do {
            let record: RustRuntimeSelectionRecord
            let runtime: RustWorkspaceRuntime
            if hasLegacyFile {
                let workspaceID = Self.importedWorkspaceID
                let importer = RustStoreImporter(
                    runtime: environment.bridge, legacyFileURL: environment.legacyStoreURL,
                    databaseURL: environment.location.databaseURL(workspaceID), workspaceID: workspaceID,
                    busyTimeoutMilliseconds: environment.busyTimeoutMilliseconds, now: environment.now)
                let prepared = try await importer.prepareImportedRuntime(
                    facade: environment.facade(), reviewEnabled: environment.reviewEnabled)
                runtime = prepared.runtime
                record = RustRuntimeSelectionRecord(
                    workspaceID: workspaceID, account: prepared.account, deviceID: environment.makeID().uuidString.lowercased(),
                    selectedAt: environment.now(), reviewEnabled: environment.reviewEnabled)
            } else {
                let workspaceID = environment.newIdentity()
                runtime = try await environment.openRuntime(workspaceID)
                do { try await runtime.establishAccountless() } catch {
                    try? await runtime.close()
                    throw error
                }
                record = RustRuntimeSelectionRecord(
                    workspaceID: workspaceID, account: nil, deviceID: environment.makeID().uuidString.lowercased(),
                    selectedAt: environment.now(), reviewEnabled: environment.reviewEnabled)
            }
            do { try environment.selections.save(record) } catch {
                try? await runtime.close()
                return .legacy(.notReady(code: "SELECTION_NOT_SAVED"))
            }
            return .rust(environment.selection(runtime, for: record), lifecycle: lifecycle())
        } catch {
            return .legacy(.notReady(code: Self.code(error)))
        }
    }

    static func code(_ error: any Error) -> String {
        switch error {
        case let error as RustBridgeError: error.code
        case let error as RustStoreImportError: "IMPORT_\(String(describing: error).prefix(48))"
        case let error as RustOutboxImportError: "OUTBOX_\(String(describing: error).prefix(48))"
        default: "UNAVAILABLE"
        }
    }
}

extension RustRuntimeLocation {
    /// The retired `store.json` beside the runtime's folder: the source of the one import.
    public static func legacyStoreURL(appGroupID: String) -> URL {
        #if canImport(Darwin)
            FileDocumentStore.appGroupDocumentURL(appGroupID: appGroupID) ?? FileDocumentStore.applicationSupportDocumentURL()
        #else
            FileDocumentStore.applicationSupportDocumentURL()
        #endif
    }
}

extension RustRuntimeEnvironment {
    /// The iOS app's environment: the App Group's folder, the app's own session token store and
    /// REST client. `transports` defaults to the Rust sync host (`RustSyncTransportProvider`), which
    /// only ever starts for a selected, signed-in workspace.
    public static func appGroup(
        _ appGroupID: String, tokenStore: (any SessionTokenStore)? = nil,
        transports: (any RustTransportProvider)? = nil, reviewEnabled: Bool = false,
        identity: ClientIdentity = .iOS
    ) throws -> RustRuntimeEnvironment {
        #if canImport(Security)
            let tokenStore = tokenStore ?? KeychainSessionTokenStore()
        #else
            let tokenStore = tokenStore ?? InMemorySessionTokenStore()
        #endif
        return RustRuntimeEnvironment(
            location: .appGroup(appGroupID), legacyStoreURL: RustRuntimeLocation.legacyStoreURL(appGroupID: appGroupID),
            bridge: try RustBridgeRuntime(),
            transports: transports ?? RustSyncTransportProvider(tokenStore: tokenStore, identity: identity),
            server: APIRustAccountServer(tokenStore: tokenStore, identity: identity), reviewEnabled: reviewEnabled)
    }
}

// MARK: - Widgets, App Intents

public enum RustExtensionResolution {
    /// No selection: the install still runs the legacy runtime.
    case legacy
    case rust(Workspace)
    /// The install is the Rust runtime's and its store cannot be opened; the extension refuses to
    /// write rather than fall back to the retired document.
    case unavailable(code: String)
}

extension Workspace {
    /// What a widget or App Intent opens: the selected identity's store through the same database
    /// lock, never syncing (`extensionWorkspace(over:)`), or the legacy runtime when the install
    /// has no selection.
    @MainActor
    public static func openForExtension(location: RustRuntimeLocation, busyTimeoutMilliseconds: UInt32 = 2_000,
                                        bridge: RustBridgeRuntime? = nil) async -> RustExtensionResolution {
        let record: RustRuntimeSelectionRecord
        do {
            guard let found = try RustRuntimeSelectionStore(location: location).load() else { return .legacy }
            record = found
        } catch {
            return .unavailable(code: "SELECTION_UNREADABLE")
        }
        do {
            let bridge = try bridge ?? RustBridgeRuntime()
            let runtime = try await bridge.openStore(workspaceID: record.workspaceID,
                databaseURL: location.databaseURL(record.workspaceID), busyTimeoutMilliseconds: busyTimeoutMilliseconds)
            let selection = RustWorkspaceSelection(
                runtime: runtime,
                facade: RustDomainFacade(runtime: bridge, context: RustDomainContext(deviceTimeZone: TimeZone.current.identifier)),
                account: record.account, reviewEnabled: record.reviewEnabled, startup: .prepared)
            return .rust(extensionWorkspace(over: selection))
        } catch {
            return .unavailable(code: RustRuntimeLauncher.code(error))
        }
    }

    /// The workspace the app shows until the runtime resolution replaces it, when the install has
    /// a selection: it opens and syncs nothing, so no legacy engine starts for a Rust install.
    @MainActor
    public static func pending() -> Workspace { Workspace(store: InMemoryDocumentStore(), sync: nil) }

    /// The install's workspace over the selected runtime, with the account lifecycle.
    @MainActor
    public static func selected(_ selection: RustWorkspaceSelection, lifecycle: any RustAccountLifecyclePort) -> Workspace {
        Workspace(store: InMemoryDocumentStore(), sync: nil, rust: selection, rustLifecycle: lifecycle)
    }

    /// A workspace that shows why the install's store cannot be used instead of an empty list.
    @MainActor
    public static func unavailable(code: String) -> Workspace {
        let workspace = Workspace(store: InMemoryDocumentStore(), sync: nil)
        workspace.markUnavailable(code: code)
        return workspace
    }
}
