import BrainBuddyCore
import Foundation

// The second step of the move to the Rust store (spec 026, T042). `RustStoreImporter` carried the legacy
// file's pending sends and sync issues whole; this type has the core classify them. The core decides
// (`bb-client` `legacy_outbox.rs`); this type only asks the server's receipts and reports.
//
// What it never does: send anything, rebuild a send as a new command, or match by title, list or
// time. An old send is settled only by the receipt for its own idempotency key. One that may have
// reached the server and has no proof stays an issue with everything the old engine knew (`everSent`,
// `issuedAt`, `attempts`, the key and the body), is exported with the account's data, and is never
// reissued. Until the core says `mayRun`, the workspace must not run on the Rust store.
//
// The list of sends to look up comes from the Rust store, not from a second reading of `store.json`,
// so this type takes no lock on the legacy file: the file's writers and `RustStoreImporter` own it.

/// Why the outbox was not classified. Whatever it is, nothing was saved; none carries user text.
public enum RustOutboxImportError: Error, Equatable, Sendable {
    /// The Rust store holds no legacy import: run `RustStoreImporter` first.
    case notImported
    /// A carried entry cannot be classified without inventing an identity.
    case unreadable(field: String?)
    /// Another process holds the store. Run it again.
    case storeBusy
    case storeFull
    case storeCorrupt
    /// The Rust store was written by a newer build.
    case storeNewer
    /// Any other bridge failure.
    case failed(RustBridgeError)

    /// Whether running it again can succeed without any change.
    public var isRetryable: Bool {
        switch self {
        case .storeBusy: true
        case .failed(let error): error.retryable
        default: false
        }
    }

    init(_ error: RustBridgeError) {
        switch error.code {
        case "LEGACY_OUTBOX_NOT_IMPORTED": self = .notImported
        case "LEGACY_OUTBOX_UNREADABLE": self = .unreadable(field: error.field)
        case "STORE_BUSY": self = .storeBusy
        case "STORE_FULL": self = .storeFull
        case "STORE_CORRUPT": self = .storeCorrupt
        case "STORE_UPGRADE_REQUIRED": self = .storeNewer
        default: self = .failed(error)
        }
    }
}

/// Where the server's retained receipts are asked. The transport (spec 026, T040) provides the real
/// one; until then `NoLegacyReceipts` answers `.unproven`, which keeps every old send an issue.
public protocol LegacyReceiptLookup: Sendable {
    /// What the server can prove about `send`, by its idempotency key. Anything short of a receipt
    /// for that key under the same body (not found, pending, offline) is `.unproven`.
    func answer(for send: RustLegacySend) async -> RustLegacyAnswer
}

/// The lookup that proves nothing.
public struct NoLegacyReceipts: LegacyReceiptLookup {
    public init() {}

    public func answer(for send: RustLegacySend) async -> RustLegacyAnswer { .unproven }
}

/// Classifies the outbox and issues a legacy import carried into the Rust store of one workspace.
///
/// Running it again is safe: a verdict that is final is kept, and a send without proof is asked
/// about again (inside the 24-hour window it waits, after it it is an issue).
public struct RustOutboxImporter: Sendable {
    private let runtime: RustBridgeRuntime
    private let databaseURL: URL
    private let workspaceID: String
    private let busyTimeoutMilliseconds: UInt32
    private let now: @Sendable () -> Date

    /// - Parameters:
    ///   - databaseURL: the Rust store `RustStoreImporter` imported into.
    ///   - workspaceID: the workspace the Rust store is bound to.
    public init(
        runtime: RustBridgeRuntime, databaseURL: URL, workspaceID: String, busyTimeoutMilliseconds: UInt32 = 5_000,
        now: @escaping @Sendable () -> Date = { Date() }
    ) {
        self.runtime = runtime
        self.databaseURL = databaseURL
        self.workspaceID = workspaceID
        self.busyTimeoutMilliseconds = busyTimeoutMilliseconds
        self.now = now
    }

    /// Asks `lookup` about every old send that has no final verdict, then has the core classify
    /// the carried outbox and issues in one transaction. Throws `RustOutboxImportError`.
    public func run(lookup: any LegacyReceiptLookup = NoLegacyReceipts()) async throws -> RustLegacyOutboxStatus {
        if Task.isCancelled { throw RustOutboxImportError.failed(.cancelled) }
        guard let stamp = ISO8601Timestamp.string(from: now()) else {
            throw RustOutboxImportError.failed(RustBridgeError(code: "INVALID_REQUEST", field: "now"))
        }
        var request = RustLegacyOutboxRequest(
            workspaceID: workspaceID, databasePath: databaseURL.path, now: stamp,
            busyTimeoutMilliseconds: busyTimeoutMilliseconds)
        do {
            // The lookups run with no transaction open, so a slow server holds no lock.
            for send in try await runtime.legacyOutboxSends(request) {
                request.receipts[send.idempotencyKey] = await lookup.answer(for: send)
            }
            return try await runtime.resolveLegacyOutbox(request)
        } catch let error as RustBridgeError {
            throw RustOutboxImportError(error)
        } catch {
            throw RustOutboxImportError.failed(RustBridgeError(code: "INTERNAL_ERROR"))
        }
    }
}
