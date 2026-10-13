import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddySync
import Foundation

#if canImport(FoundationNetworking)
    import FoundationNetworking
#endif

/// The production `RustTransportProvider` (spec 026, PR-54): a selected, signed-in workspace syncs
/// through `RustSyncHost`; an account-less one gets the pending port and sends nothing. The host
/// is only built here, so it exists only for a runtime the launcher selected (the pilot switch
/// gates that) and an account the lifecycle linked.
public struct RustSyncTransportProvider: RustTransportProvider {
    private let tokenStore: any SessionTokenStore
    private let identity: ClientIdentity
    private let urlSessionConfiguration: @Sendable () -> URLSessionConfiguration
    private let pollInterval: TimeInterval?
    private let now: @Sendable () -> Date

    public init(
        tokenStore: any SessionTokenStore, identity: ClientIdentity = .iOS,
        urlSessionConfiguration: @escaping @Sendable () -> URLSessionConfiguration = { RustSyncURLSession.defaultConfiguration },
        pollInterval: TimeInterval? = nil, now: @escaping @Sendable () -> Date = { Date() }
    ) {
        self.tokenStore = tokenStore
        self.identity = identity
        self.urlSessionConfiguration = urlSessionConfiguration
        self.pollInterval = pollInterval
        self.now = now
    }

    public func transport(for context: RustTransportContext) -> any SyncRuntimePort {
        guard let account = context.account else { return PendingRustSyncRuntimePort() }
        return RustSyncHostPort(
            context: context, account: account, tokenStore: tokenStore, identity: identity,
            urlSessionConfiguration: urlSessionConfiguration, pollInterval: pollInterval, now: now)
    }
}

/// One binding's sync port: starts the host on first use (the store open and the session bind
/// are I/O, and the provider is not async), restarts it after `quiesce()`, and never starts one
/// once closed. A host that cannot start answers `transportUnavailable` (or `updateNeeded`) and is
/// tried again by the next request.
actor RustSyncHostPort: SyncRuntimePort {
    private let context: RustTransportContext
    private let account: LinkedAccount
    private let tokenStore: any SessionTokenStore
    private let identity: ClientIdentity
    private let urlSessionConfiguration: @Sendable () -> URLSessionConfiguration
    private let pollInterval: TimeInterval?
    private let now: @Sendable () -> Date

    private var host: RustSyncHost?
    private var starting: Task<RustSyncHost?, Never>?
    private var closed = false
    private var online = true
    private var fresh: Bool
    private var updateRequired = false
    /// Bumped by `quiesce()`: a start that began before it is discarded when it ends.
    private var epoch = 0

    init(
        context: RustTransportContext, account: LinkedAccount, tokenStore: any SessionTokenStore,
        identity: ClientIdentity, urlSessionConfiguration: @escaping @Sendable () -> URLSessionConfiguration,
        pollInterval: TimeInterval?, now: @escaping @Sendable () -> Date
    ) {
        self.context = context
        self.account = account
        self.tokenStore = tokenStore
        self.identity = identity
        self.urlSessionConfiguration = urlSessionConfiguration
        self.pollInterval = pollInterval
        self.now = now
        fresh = context.freshAuthentication
    }

    /// Whether a host is running (tests).
    var isRunning: Bool { host != nil }

    private func running() async -> RustSyncHost? {
        if closed { return nil }
        if let host { return host }
        if let starting { return await starting.value }
        let task = Task { await start() }
        let began = epoch
        starting = task
        let started = await task.value
        if began == epoch { starting = nil }
        guard let started else { return nil }
        if closed || began != epoch {
            await started.close()
            return nil
        }
        host = started
        if !online { await started.setNetworkAvailable(false) }
        return started
    }

    private func start() async -> RustSyncHost? {
        let policy = Data(
            #"{"weekly_review":\#(context.reviewEnabled),"navigator_provider":null,"navigator_available":false,"consent_text_version":1}"#.utf8)
        let instant = now()
        do {
            let started = try await RustSyncHost.start(
                workspaceID: context.workspaceID, databaseURL: context.databaseURL,
                binding: .init(accountID: account.id, scopeID: account.id, deviceID: context.deviceID,
                               freshAuthentication: fresh),
                context: RustWorkspaceContext(
                    now: instant, timeZone: TimeZone.current.identifier, actorID: RustDomainContext().actorID, policy: policy),
                serverURL: account.serverURL, tokenStore: tokenStore, identity: identity,
                urlSessionConfiguration: urlSessionConfiguration(), pollInterval: pollInterval, now: now)
            // Later restarts resume the session this start bound.
            fresh = false
            updateRequired = false
            return started
        } catch let error as RustBridgeError {
            updateRequired = error.code == "UPGRADE_REQUIRED"
            return nil
        } catch {
            return nil
        }
    }

    private var unavailable: SyncRuntimeWakeResult { updateRequired ? .updateNeeded : .transportUnavailable }

    func request(_ trigger: SyncTrigger) async -> SyncRuntimeWakeResult {
        guard let host = await running() else { return unavailable }
        return await host.request(trigger)
    }

    func setNetworkAvailable(_ available: Bool) async {
        online = available
        await host?.setNetworkAvailable(available)
    }

    func rebuildSyncedCopy() async -> SyncRuntimeRebuildResult {
        guard let host = await running() else { return .transportUnavailable }
        return await host.rebuildSyncedCopy()
    }

    func enterBackground() async { await host?.enterBackground() }

    func quiesce() async {
        epoch += 1
        let stopping = host
        host = nil
        starting = nil
        await stopping?.close()
    }

    func close() async {
        closed = true
        await quiesce()
    }
}
