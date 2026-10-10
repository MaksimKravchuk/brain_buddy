import BrainBuddyCore
import Foundation

// The move from the JSON store file to the Rust store (spec 026, T041, contracts/runtime-ffi.md
// "Migration and packaging boundary"). The legacy file is the source of truth until the Rust
// core has verified everything it took from it; this type only decides *whether to ask*, and
// reports what happened. Backing the file up, staging, validating and switching the store
// happen in `bb-client` (`import.rs`), in one transaction under the migration lock.

/// Why a legacy import did not switch the store. Whatever it is, the legacy file is exactly as
/// it was and the Rust store has no marker; none of these carries user text.
public enum RustStoreImportError: Error, Equatable, Sendable {
    /// There is no legacy file.
    case sourceMissing
    /// The file cannot be read from disk.
    case sourceIO
    /// The file is not a `StoreDocument` the kit can decode. It is left untouched for the user to
    /// export or reset (`DocumentStoreError.unreadable`).
    case sourceUnreadable
    /// The file was saved by a newer version of the app (`DocumentStoreError.unsupportedVersion`).
    case sourceNewer(version: Int)
    /// The file holds a member the importer does not carry, so importing it would drop data.
    case sourceNotCarried(field: String?)
    /// The file decodes but cannot be imported without guessing (a dangling relation, a repeated
    /// identity, a value the shared rules refuse).
    case sourceInconsistent(field: String?)
    /// The file changed while it was being imported. Run the import again.
    case sourceChanged
    /// Another process holds the store. Run the import again.
    case storeBusy
    /// The disk or the database is full.
    case storeFull
    /// The Rust store file is not a readable store. It is left as it is.
    case storeCorrupt
    /// The Rust store was written by a newer build.
    case storeNewer
    /// The Rust store already holds data of its own; an import never merges into it.
    case storeInUse
    /// A different legacy file was imported before; this one is never merged.
    case alreadyImportedOther
    /// The imported rows did not equal the source, so nothing was switched.
    case verificationFailed(check: String?)
    /// Any other bridge failure.
    case failed(RustBridgeError)

    /// Whether running the import again can succeed without any change.
    public var isRetryable: Bool {
        switch self {
        case .sourceChanged, .storeBusy: true
        case .failed(let error): error.retryable
        default: false
        }
    }

    init(_ error: RustBridgeError) {
        switch error.code {
        case "IMPORT_SOURCE_MISSING": self = .sourceMissing
        case "IMPORT_SOURCE_UNREADABLE": self = .sourceUnreadable
        case "IMPORT_SOURCE_UNSUPPORTED": self = .sourceNotCarried(field: error.field)
        case "IMPORT_SOURCE_INCONSISTENT": self = .sourceInconsistent(field: error.field)
        case "IMPORT_SOURCE_CHANGED": self = .sourceChanged
        case "IMPORT_TARGET_IN_USE": self = .storeInUse
        case "IMPORT_ALREADY_IMPORTED": self = .alreadyImportedOther
        case "IMPORT_VERIFICATION_FAILED": self = .verificationFailed(check: error.field)
        case "STORE_BUSY": self = .storeBusy
        case "STORE_FULL": self = .storeFull
        case "STORE_CORRUPT": self = .storeCorrupt
        case "STORE_UPGRADE_REQUIRED": self = .storeNewer
        default: self = .failed(error)
        }
    }
}

extension RustImportCounts {
    /// The counts of a decoded legacy document, by the kit's own reader.
    public init(counting document: StoreDocument) {
        let tasks = document.base.tasks.values
        let review = document.base.review
        self.init(
            tasks: UInt64(document.base.tasks.count),
            subtasks: UInt64(tasks.reduce(0) { $0 + $1.subtasks.count }),
            comments: UInt64(tasks.reduce(0) { $0 + $1.comments.count }),
            projects: UInt64(document.base.projects.count),
            tags: UInt64(document.base.tags.count),
            outboxEntries: UInt64(document.outbox.count),
            issues: UInt64(document.issues.count),
            reviewSessions: UInt64(review.sessions.count),
            reviewDecisions: UInt64(review.decisions.count),
            reviewReceipts: UInt64(review.receipts.count),
            reviewParkAcks: UInt64(review.parkAcks.count),
            reviewBulkReleases: UInt64(review.bulkReleases.count),
            reviewNavigatorConsents: UInt64(review.navigatorConsents.count),
            formDrafts: UInt64(document.local.formDrafts.count))
    }
}

/// Imports the legacy `StoreDocument` file (`FileDocumentStore`'s `store.json`) into the Rust
/// store of one workspace.
///
/// The importer reads the file once with the kit's own decoder (so a damaged file or one a newer
/// app wrote is reported as the file store reports it, and nothing is attempted), counts it, and
/// hands the Rust core the paths and those counts. The core backs the file up with a schema
/// manifest, stages the typed records, validates them against the source (the counts handed in
/// among the checks) and switches the store under the migration lock, or changes nothing.
///
/// Running it again after a success is safe (`alreadyActive`). Running it over a *different*
/// file after a success is refused: the second file is never merged. The legacy file is never
/// modified, renamed or deleted here; retiring it is the caller's decision once the Rust store is
/// the workspace's store.
///
/// The pending operations and sync issues of the legacy file are carried whole and counted
/// (`counts.outboxEntries`, `counts.issues`) but not converted: the workspace must not run on the
/// Rust store until the outbox import has consumed them.
public struct RustStoreImporter: Sendable {
    private let runtime: RustBridgeRuntime
    private let legacyFile: DocumentFile
    private let databaseURL: URL
    private let workspaceID: String
    private let backupDirectory: URL?
    private let busyTimeoutMilliseconds: UInt32
    private let now: @Sendable () -> Date

    /// - Parameters:
    ///   - legacyFileURL: the `store.json` of the workspace. Must be a file URL.
    ///   - databaseURL: where the Rust store lives (created when missing).
    ///   - workspaceID: the workspace the Rust store is bound to.
    ///   - backupDirectory: where the backup and the schema manifest go; beside the legacy file by default.
    public init(
        runtime: RustBridgeRuntime, legacyFileURL: URL, databaseURL: URL, workspaceID: String,
        backupDirectory: URL? = nil, busyTimeoutMilliseconds: UInt32 = 5_000,
        now: @escaping @Sendable () -> Date = { Date() }
    ) {
        precondition(legacyFileURL.isFileURL, "RustStoreImporter needs a file URL, got \(legacyFileURL)")
        self.runtime = runtime
        self.legacyFile = DocumentFile(url: legacyFileURL)
        self.databaseURL = databaseURL
        self.workspaceID = workspaceID
        self.backupDirectory = backupDirectory
        self.busyTimeoutMilliseconds = busyTimeoutMilliseconds
        self.now = now
    }

    /// Runs the import. Throws `RustStoreImportError`.
    public func run() async throws -> RustLegacyImportReport {
        if Task.isCancelled { throw RustStoreImportError.failed(.cancelled) }
        let bytes: Data?
        do {
            bytes = try legacyFile.readContents()
        } catch {
            throw RustStoreImportError.sourceIO
        }
        guard let data = bytes else { throw RustStoreImportError.sourceMissing }

        let document: StoreDocument
        do {
            document = try StoreDocumentCoding.decode(data)
        } catch DocumentStoreError.unsupportedVersion(let version) {
            throw RustStoreImportError.sourceNewer(version: version)
        } catch {
            throw RustStoreImportError.sourceUnreadable
        }

        guard let stamp = ISO8601Timestamp.string(from: now()) else {
            throw RustStoreImportError.failed(RustBridgeError(code: "INVALID_REQUEST", field: "now"))
        }
        let request = RustLegacyImportRequest(
            workspaceID: workspaceID, databasePath: databaseURL.path, sourcePath: legacyFile.path,
            backupDirectory: backupDirectory?.path, now: stamp, busyTimeoutMilliseconds: busyTimeoutMilliseconds,
            expected: RustImportCounts(counting: document))
        do {
            return try await runtime.importLegacyStore(request)
        } catch let error as RustBridgeError {
            throw RustStoreImportError(error)
        } catch {
            throw RustStoreImportError.failed(RustBridgeError(code: "INTERNAL_ERROR"))
        }
    }
}
