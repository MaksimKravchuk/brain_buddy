import BrainBuddyRustBindings
import Foundation
import Synchronization

// The Swift face of the core's sync host (`rust/bindings/swift/src/sync.rs`, spec 026 PR-40): the
// ports the OS adapter implements (transport, hint stream, observer) as plain Swift protocols, and
// `RustSyncHandle` over the running host. No generated type is part of the kit's API, and no
// credential is: the adapter adds the session cookie it already holds.

// MARK: - Cancellation

/// What a running call polls to know it should stop (a reset, a sign-out, `close`).
public final class RustSyncCancellation: Sendable {
    fileprivate let token: BridgeCancel

    public init() { token = BridgeCancel() }
    fileprivate init(_ token: BridgeCancel) { self.token = token }

    public var isCancelled: Bool { token.isCancelled() }

    /// Raises the token (tests drive an adapter's cancellation path with this).
    public func cancel() { token.raise() }
}

// MARK: - Transport

public enum RustSyncMethod: Sendable, Equatable {
    case get, post
}

/// One HTTP call to perform. `path` is origin-relative and already percent-encoded.
public struct RustSyncRequest: Sendable, Equatable {
    public let method: RustSyncMethod
    public let path: String
    /// The JSON body of a `POST`, byte for byte.
    public let body: Data?
    /// How long the adapter may wait for the whole answer.
    public let timeout: TimeInterval

    public init(method: RustSyncMethod, path: String, body: Data? = nil, timeout: TimeInterval) {
        self.method = method
        self.path = path
        self.body = body
        self.timeout = timeout
    }
}

public struct RustSyncResponse: Sendable, Equatable {
    public let status: Int
    /// The parsed `Retry-After`, in seconds.
    public let retryAfter: TimeInterval?
    public let body: Data

    public init(status: Int, retryAfter: TimeInterval? = nil, body: Data = Data()) {
        self.status = status
        self.retryAfter = retryAfter
        self.body = body
    }
}

/// Why no HTTP answer arrived. A non-2xx status is an answer, not a failure.
public enum RustSyncTransportFailure: Error, Sendable, Equatable {
    case timeout, connection, cancelled
}

/// The authenticated HTTP adapter. It is called on the core's sync worker thread (never the main
/// thread), so it may block; it must stop with `.cancelled` once `cancel` is raised.
public protocol RustSyncTransport: Sendable {
    func send(_ request: RustSyncRequest, cancel: RustSyncCancellation) throws(RustSyncTransportFailure)
        -> RustSyncResponse
}

// MARK: - Hint stream

public enum RustSyncStreamFailure: Error, Sendable, Equatable {
    /// The route answered with this status instead of a stream.
    case status(Int)
    /// Nothing arrived within the idle timeout.
    case timeout
    case connection
    case cancelled
}

/// An open `text/event-stream` body.
public protocol RustSyncHintReader: Sendable {
    /// At most `maxLength` bytes; empty when the server closed the stream.
    func read(maxLength: Int, cancel: RustSyncCancellation) throws(RustSyncStreamFailure) -> Data
}

/// The authenticated streaming GET: it adds the credential and `Accept: text/event-stream`, sends
/// no `Last-Event-ID`, and returns the body only for a `200`.
public protocol RustSyncHintStream: Sendable {
    func open(path: String, idleTimeout: TimeInterval, cancel: RustSyncCancellation)
        throws(RustSyncStreamFailure) -> any RustSyncHintReader
}

// MARK: - Observer

public enum RustSyncState: Sendable, Equatable {
    case synced
    /// No HTTP answer. Changes are kept and sent later.
    case offline
    /// `429`, `5xx` or unfinished work; the loop retries with backoff.
    case retrying
    /// `401` or a revoked session: paused until the person signs in again.
    case authRequired
    /// The server or protocol is newer than this build (`UPGRADE_REQUIRED`).
    case updateRequired
    case failed
}

/// What to re-query after a round.
public struct RustSyncInvalidation: Sendable, Equatable {
    public let projectionGeneration: String
    public let recordsChanged: Bool
    public let issuesChanged: Bool
    public let statusChanged: Bool
}

/// One finished round. Content-free: `failureCode` is a stable code, never text from a payload.
public struct RustSyncReport: Sendable, Equatable {
    public let state: RustSyncState
    public let failureCode: String?
    public let sent: Int
    public let settled: Int
    public let pulledTransactions: Int
    public let invalidation: RustSyncInvalidation?

    public init(
        state: RustSyncState, failureCode: String? = nil, sent: Int = 0, settled: Int = 0,
        pulledTransactions: Int = 0, invalidation: RustSyncInvalidation? = nil
    ) {
        self.state = state
        self.failureCode = failureCode
        self.sent = sent
        self.settled = settled
        self.pulledTransactions = pulledTransactions
        self.invalidation = invalidation
    }
}

/// Told after every round, on the sync worker thread: hand off and return. It must not call back
/// into `RustSyncHandle.stop()`.
public protocol RustSyncObserver: Sendable {
    func roundFinished(_ report: RustSyncReport)
}

// MARK: - The handle

public enum RustSyncWake: Sendable, Equatable {
    /// The app became active (launch, foreground, a background refresh): starts the schedule and
    /// the hint stream.
    case foreground
    case networkReturn
    /// The person asked to sync now.
    case manual
    /// A local change is waiting: round again at once, without forgiving a backoff.
    case localChange
}

public enum RustSyncRebuildOutcome: Sendable, Equatable {
    case rebuilt
    /// Stopped; waiting changes and saved issues are untouched. The code is safe to quote.
    case failed(code: String)
}

public struct RustSyncConfiguration: Sendable {
    public let workspaceID: String
    public let databaseURL: URL
    public let busyTimeoutMilliseconds: UInt32
    public let accountID: String
    public let scopeID: String
    public let deviceID: String
    /// A sign-in or re-authentication (every earlier request is fenced out); false for a relaunch.
    public let freshAuthentication: Bool
    /// The rules' time zone, actor and policy for applying the feed (`now` is read per application).
    public let context: RustWorkspaceContext
    /// The fallback poll interval; nil keeps the 30 seconds sync-v1 section 7 allows.
    public let pollInterval: TimeInterval?

    public init(
        workspaceID: String, databaseURL: URL, busyTimeoutMilliseconds: UInt32 = 2_000, accountID: String,
        scopeID: String, deviceID: String, freshAuthentication: Bool, context: RustWorkspaceContext,
        pollInterval: TimeInterval? = nil
    ) {
        self.workspaceID = workspaceID
        self.databaseURL = databaseURL
        self.busyTimeoutMilliseconds = busyTimeoutMilliseconds
        self.accountID = accountID
        self.scopeID = scopeID
        self.deviceID = deviceID
        self.freshAuthentication = freshAuthentication
        self.context = context
        self.pollInterval = pollInterval
    }
}

/// The running sync host. Safe to share between tasks and threads; `stop()` is final and idempotent.
public final class RustSyncHandle: Sendable {
    private let host: BridgeSyncHost

    private init(_ host: BridgeSyncHost) { self.host = host }

    /// Opens the store on the worker's own connection, binds it to the signed-in account and starts
    /// the worker (idle until the first `.foreground`). Runs off the caller's actor. Fails with the
    /// session's code (`LINK_REQUIRED`, `ACCOUNT_MISMATCH`, `DEVICE_MISMATCH`, `UPGRADE_REQUIRED`).
    public static func start(
        configuration: RustSyncConfiguration, transport: any RustSyncTransport, hints: any RustSyncHintStream,
        observer: any RustSyncObserver
    ) async throws -> RustSyncHandle {
        let config = BridgeSyncConfig(
            workspaceId: configuration.workspaceID, databasePath: configuration.databaseURL.path,
            busyTimeoutMs: configuration.busyTimeoutMilliseconds, accountId: configuration.accountID,
            scopeId: configuration.scopeID, deviceId: configuration.deviceID,
            freshAuthentication: configuration.freshAuthentication, context: configuration.context.bridgedForSync,
            pollIntervalMs: configuration.pollInterval.map { UInt64(max(0.001, $0) * 1000) })
        let ports = (
            TransportAdapter(transport), HintStreamAdapter(hints), ObserverAdapter(observer)
        )
        let outcome = await Task.detached { () -> Result<BridgeSyncHost, RustBridgeError> in
            do {
                return .success(
                    try BridgeSyncHost.start(
                        config: config, transport: ports.0, hints: ports.1, observer: ports.2))
            } catch { return .failure(RustBridgeError(syncThrown: error)) }
        }.value
        return RustSyncHandle(try outcome.get())
    }

    public func signal(_ wake: RustSyncWake) {
        host.signal(wake: {
            switch wake {
            case .foreground: .foreground
            case .networkReturn: .networkReturn
            case .manual: .manual
            case .localChange: .localChange
            }
        }())
    }

    public func background() { host.background() }

    public func setOnline(_ online: Bool) { host.setOnline(online: online) }

    /// Rebuilds the synced copy from a snapshot, keeping every waiting change and saved issue.
    public func rebuild() async -> RustSyncRebuildOutcome {
        let host = host
        return await Task.detached {
            switch host.rebuild() {
            case .rebuilt: RustSyncRebuildOutcome.rebuilt
            case .failed(let code): RustSyncRebuildOutcome.failed(code: code)
            }
        }.value
    }

    /// Cancels calls in flight, closes the stream and releases the store. Durable commands survive.
    public func stop() async {
        let host = host
        await Task.detached { host.stop() }.value
    }
}

extension RustWorkspaceContext {
    fileprivate var bridgedForSync: BridgeExecuteContext {
        BridgeExecuteContext(now: RustInstant.format(now), timeZone: timeZone, actorId: actorID, policy: policy)
    }
}

extension RustBridgeError {
    fileprivate init(syncThrown error: any Error) {
        if let bridge = error as? BridgeError, case let .Failed(code, retryable, field) = bridge {
            self.init(code: code, retryable: retryable, field: field)
        } else {
            self.init(code: "INTERNAL_ERROR")
        }
    }
}

// MARK: - Adapters (generated callback interfaces over the protocols above)

private final class TransportAdapter: BridgeTransport {
    private let transport: any RustSyncTransport

    init(_ transport: any RustSyncTransport) { self.transport = transport }

    func send(request: BridgeHttpRequest, cancel: BridgeCancel) throws -> BridgeHttpResponse {
        let call = RustSyncRequest(
            method: request.method == .get ? .get : .post, path: request.path, body: request.body,
            timeout: TimeInterval(request.timeoutMs) / 1000)
        do {
            let answer = try transport.send(call, cancel: RustSyncCancellation(cancel))
            return BridgeHttpResponse(
                status: UInt16(clamping: answer.status),
                retryAfterMs: answer.retryAfter.map { UInt64(max(0, $0) * 1000) }, body: answer.body)
        } catch {
            switch error {
            case .timeout: throw BridgeTransportError.Timeout
            case .connection: throw BridgeTransportError.Connection
            case .cancelled: throw BridgeTransportError.Cancelled
            }
        }
    }
}

private final class ReaderAdapter: BridgeHintReader {
    private let reader: any RustSyncHintReader

    init(_ reader: any RustSyncHintReader) { self.reader = reader }

    func read(maxLen: UInt32, cancel: BridgeCancel) throws -> Data {
        do {
            return try reader.read(maxLength: Int(maxLen), cancel: RustSyncCancellation(cancel))
        } catch { throw error.bridged }
    }
}

private final class HintStreamAdapter: BridgeHintStream {
    private let stream: any RustSyncHintStream

    init(_ stream: any RustSyncHintStream) { self.stream = stream }

    func openStream(path: String, idleMs: UInt64, cancel: BridgeCancel) throws -> BridgeHintReader {
        do {
            return ReaderAdapter(
                try stream.open(
                    path: path, idleTimeout: TimeInterval(idleMs) / 1000, cancel: RustSyncCancellation(cancel)))
        } catch { throw error.bridged }
    }
}

extension RustSyncStreamFailure {
    fileprivate var bridged: BridgeStreamError {
        switch self {
        case .status(let code): .Status(code: UInt16(clamping: code))
        case .timeout: .Timeout
        case .connection: .Connection
        case .cancelled: .Cancelled
        }
    }
}

private final class ObserverAdapter: BridgeSyncObserver {
    private let observer: any RustSyncObserver

    init(_ observer: any RustSyncObserver) { self.observer = observer }

    func roundFinished(report: BridgeSyncReport) {
        let state: RustSyncState =
            switch report.state {
            case .synced: .synced
            case .offline: .offline
            case .retrying: .retrying
            case .authRequired: .authRequired
            case .updateRequired: .updateRequired
            case .failed: .failed
            }
        observer.roundFinished(
            RustSyncReport(
                state: state, failureCode: report.failureCode, sent: Int(report.sent), settled: Int(report.settled),
                pulledTransactions: Int(clamping: report.pulledTransactions),
                invalidation: report.invalidation.map {
                    RustSyncInvalidation(
                        projectionGeneration: $0.projectionGeneration, recordsChanged: $0.recordsChanged,
                        issuesChanged: $0.issuesChanged, statusChanged: $0.statusChanged)
                }))
    }
}
