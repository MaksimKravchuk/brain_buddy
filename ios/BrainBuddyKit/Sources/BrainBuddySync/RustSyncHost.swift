import BrainBuddyAPI
import BrainBuddyCore
import Foundation
import Synchronization

#if canImport(FoundationNetworking)
    import FoundationNetworking
#endif

/// The Apple host of the shared sync loop (spec 026, PR-40): a `SyncRuntimePort` that drives the
/// Rust `SyncLoop` and hint watcher over `URLSession`.
///
/// Everything network runs on the core's own threads, never the main thread: one sync worker (over
/// its own store connection, so a local save never waits for a request) and, while the app is in the
/// foreground, one reading the hint stream. The session token stays in the `SessionTokenStore`; the
/// core only ever sees paths, bodies and statuses.
///
/// Wiring (what production selection calls): after the account link is recorded, build one host per
/// signed-in workspace with `RustSyncHost.start(...)` and pass it as the selection's `transport`.
/// Call `enterBackground()` when the scene leaves the foreground and `close()` (the workspace does
/// this) on sign-out.
public final class RustSyncHost: SyncRuntimePort {
    /// Who this device is, for binding the store to the signed-in account.
    public struct Binding: Sendable, Equatable {
        public var accountID: String
        public var scopeID: String
        public var deviceID: String
        /// A sign-in or re-authentication fences every earlier request out; false for a relaunch.
        public var freshAuthentication: Bool

        public init(accountID: String, scopeID: String, deviceID: String, freshAuthentication: Bool) {
            self.accountID = accountID
            self.scopeID = scopeID
            self.deviceID = deviceID
            self.freshAuthentication = freshAuthentication
        }
    }

    /// How long `request(.manual)` waits for its round before answering with the status it has.
    public static let manualRoundTimeout: TimeInterval = 45

    private let handle: RustSyncHandle
    private let shared: Shared
    private let manualTimeout: TimeInterval

    /// Opens the workspace's store on the sync worker's own connection, binds it to `binding` and
    /// starts the worker. It is idle until the first `.launch`/`.foreground` request. Throws a
    /// `RustBridgeError` with the session's code (`LINK_REQUIRED`, `ACCOUNT_MISMATCH`,
    /// `UPGRADE_REQUIRED`, …) and changes nothing.
    public static func start(
        workspaceID: String, databaseURL: URL, binding: Binding, context: RustWorkspaceContext,
        serverURL: URL, tokenStore: any SessionTokenStore, identity: ClientIdentity = .iOS,
        urlSessionConfiguration: URLSessionConfiguration = RustSyncURLSession.defaultConfiguration,
        pollInterval: TimeInterval? = nil, now: @escaping @Sendable () -> Date = { Date() },
        manualRoundTimeout: TimeInterval = RustSyncHost.manualRoundTimeout
    ) async throws -> RustSyncHost {
        let shared = Shared(now: now)
        let handle = try await RustSyncHandle.start(
            configuration: RustSyncConfiguration(
                workspaceID: workspaceID, databaseURL: databaseURL, accountID: binding.accountID,
                scopeID: binding.scopeID, deviceID: binding.deviceID,
                freshAuthentication: binding.freshAuthentication, context: context, pollInterval: pollInterval),
            transport: URLSessionRustSyncTransport(
                serverURL: serverURL, tokenStore: tokenStore, identity: identity,
                configuration: urlSessionConfiguration),
            hints: URLSessionRustSyncHintStream(
                serverURL: serverURL, tokenStore: tokenStore, identity: identity,
                configuration: urlSessionConfiguration),
            observer: shared)
        return RustSyncHost(handle: handle, shared: shared, manualTimeout: manualRoundTimeout)
    }

    private init(handle: RustSyncHandle, shared: Shared, manualTimeout: TimeInterval) {
        self.handle = handle
        self.shared = shared
        self.manualTimeout = manualTimeout
    }

    // MARK: SyncRuntimePort

    public func request(_ trigger: SyncTrigger) async -> SyncRuntimeWakeResult {
        guard !shared.isClosed else { return .transportUnavailable }
        // The loop is idle after `enterBackground()` until a foreground wake: any request that
        // follows is one.
        if shared.setBackgrounded(false) { handle.signal(.foreground) }
        switch trigger {
        case .launch, .foreground, .backgroundRefresh:
            handle.signal(.foreground)
        case .networkRestored:
            handle.signal(.networkReturn)
        case .localChange:
            handle.signal(.localChange)
        case .manual:
            let before = shared.rounds
            handle.signal(.manual)
            await shared.waitForRound(after: before, timeout: manualTimeout)
        // The loop polls on its own schedule (30 s, from the start of the last poll).
        case .periodic:
            break
        }
        return shared.current
    }

    public func setNetworkAvailable(_ available: Bool) async {
        guard !shared.isClosed else { return }
        handle.setOnline(available)
    }

    public func rebuildSyncedCopy() async -> SyncRuntimeRebuildResult {
        guard !shared.isClosed else { return .transportUnavailable }
        switch await handle.rebuild() {
        case .rebuilt: return .rebuilt
        case .failed(let code): return .failed(referenceID: code)
        }
    }

    public func close() async {
        guard shared.close() else { return }
        await handle.stop()
    }

    // MARK: Host controls

    /// The scene left the foreground: no polls or pulls until the next `.foreground`, and the hint
    /// stream is closed. Waiting changes stay saved.
    public func enterBackground() {
        guard !shared.isClosed else { return }
        shared.setBackgrounded(true)
        handle.background()
    }

    /// A host is one-shot: quiescing it is closing it (`RustSyncHostPort` starts a new one).
    public func quiesce() async { await close() }

    /// Hears every status the loop reaches, including those between requests (a hint pull, a poll,
    /// a retry). Called on the sync worker: hand off and return. Replaces an earlier handler.
    public func setStatusHandler(_ handler: (@Sendable (SyncRuntimeWakeResult) -> Void)?) {
        shared.setHandler(handler)
    }

    /// Hears each finished round, with what to re-query. Called on the sync worker.
    public func setRoundHandler(_ handler: (@Sendable (RustSyncReport) -> Void)?) {
        shared.setRoundHandler(handler)
    }

    /// The status as of the last finished round (`.syncing` before the first).
    public var currentStatus: SyncRuntimeWakeResult { shared.current }
}

// MARK: - Shared state

/// What the worker thread tells the host, and what `request` waits on.
private final class Shared: RustSyncObserver, Sendable {
    private struct State {
        var closed = false
        /// True until the first request, and after `enterBackground()`: the loop is inactive and only
        /// a foreground wake starts it.
        var backgrounded = true
        var rounds = 0
        var status: SyncRuntimeWakeResult = .status(.syncing)
        var lastSyncedAt: Date?
        var handler: (@Sendable (SyncRuntimeWakeResult) -> Void)?
        var roundHandler: (@Sendable (RustSyncReport) -> Void)?
        var waiters: [Int: CheckedContinuation<Void, Never>] = [:]
        var nextWaiter = 0
    }

    private let state = Mutex(State())
    private let now: @Sendable () -> Date

    init(now: @escaping @Sendable () -> Date) { self.now = now }

    var isClosed: Bool { state.withLock { $0.closed } }

    /// Sets the flag; returns what it was.
    @discardableResult
    func setBackgrounded(_ value: Bool) -> Bool {
        state.withLock { state in
            defer { state.backgrounded = value }
            return state.backgrounded
        }
    }
    var rounds: Int { state.withLock { $0.rounds } }
    var current: SyncRuntimeWakeResult { state.withLock { $0.status } }

    func setHandler(_ handler: (@Sendable (SyncRuntimeWakeResult) -> Void)?) {
        state.withLock { $0.handler = handler }
    }

    func setRoundHandler(_ handler: (@Sendable (RustSyncReport) -> Void)?) {
        state.withLock { $0.roundHandler = handler }
    }

    /// True the first time; later closes find it done.
    func close() -> Bool {
        let (first, waiters) = state.withLock { state -> (Bool, [CheckedContinuation<Void, Never>]) in
            let first = !state.closed
            state.closed = true
            state.handler = nil
            state.roundHandler = nil
            let waiters = Array(state.waiters.values)
            state.waiters = [:]
            return (first, waiters)
        }
        for waiter in waiters { waiter.resume() }
        return first
    }

    func roundFinished(_ report: RustSyncReport) {
        let (handler, roundHandler, status, waiters) = state.withLock { state in
            guard !state.closed else {
                return ((@Sendable (SyncRuntimeWakeResult) -> Void)?.none, (@Sendable (RustSyncReport) -> Void)?.none,
                        state.status, [CheckedContinuation<Void, Never>]())
            }
            if report.state == .synced { state.lastSyncedAt = now() }
            state.status = Self.result(for: report, lastSyncedAt: state.lastSyncedAt)
            state.rounds += 1
            let waiters = Array(state.waiters.values)
            state.waiters = [:]
            return (state.handler, state.roundHandler, state.status, waiters)
        }
        for waiter in waiters { waiter.resume() }
        handler?(status)
        roundHandler?(report)
    }

    /// How a round's end reads in the app's words. A code is never shown as a message.
    static func result(for report: RustSyncReport, lastSyncedAt: Date?) -> SyncRuntimeWakeResult {
        switch report.state {
        case .synced: .status(.idle(lastSyncedAt: lastSyncedAt))
        case .offline: .status(.offline(lastSyncedAt: lastSyncedAt))
        case .authRequired: .status(.needsSignIn)
        case .updateRequired: .updateNeeded
        case .retrying:
            .status(.failing(
                message: "Brain Buddy couldn't reach the sync service. It will try again.", referenceID: nil,
                lastSyncedAt: lastSyncedAt))
        case .failed:
            .status(.failing(
                message: "Syncing stopped. Your changes are saved on this device.",
                referenceID: report.failureCode, lastSyncedAt: lastSyncedAt))
        }
    }

    /// Returns once a round finished after `before` rounds, the host closed, or `timeout` passed.
    func waitForRound(after before: Int, timeout: TimeInterval) async {
        let id = state.withLock { state -> Int? in
            guard !state.closed, state.rounds == before else { return nil }
            state.nextWaiter += 1
            return state.nextWaiter
        }
        guard let id else { return }
        let timer = Task { [weak self] in
            try? await Task.sleep(for: .seconds(timeout))
            self?.resumeWaiter(id)
        }
        await withTaskCancellationHandler {
            await withCheckedContinuation { continuation in
                // A round that finished between the check above and now has nobody to resume us.
                let stale = state.withLock { state -> Bool in
                    if state.closed || state.rounds != before { return true }
                    state.waiters[id] = continuation
                    return false
                }
                if stale { continuation.resume() }
            }
        } onCancel: {
            resumeWaiter(id)
        }
        timer.cancel()
    }

    private func resumeWaiter(_ id: Int) {
        let waiter = state.withLock { $0.waiters.removeValue(forKey: id) }
        waiter?.resume()
    }
}
