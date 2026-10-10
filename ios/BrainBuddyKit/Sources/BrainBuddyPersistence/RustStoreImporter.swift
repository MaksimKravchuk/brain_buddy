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
/// Rust store until `RustOutboxImporter` has classified them (`mayRun`).
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
    ///
    /// The core holds the document's own writer lock (the `.store.json.lock` sibling every
    /// `FileDocumentStore` write takes) from its read of the file to the commit, so the app, a widget
    /// or an App Intent cannot save in between; a writer waits for the commit, and the import waits
    /// for a writer for at most `busyTimeoutMilliseconds` (`storeBusy`, retryable). This type takes no
    /// lock of its own: a second handle on the same lock file in this process would only wait for the
    /// core's. The Swift read below is outside that lock, so a save that lands between it and the
    /// core's read shows up as a disagreement of counts; the run then reads once more.
    public func run() async throws -> RustLegacyImportReport {
        do {
            return try await attempt()
        } catch let error as RustStoreImportError where error == .verificationFailed(check: "expected_counts") {
            return try await attempt()
        }
    }

    /// Callable T043 bootstrap. The app's default epoch and T044 activation
    /// stay unchanged. Nothing is exposed until every preparation step succeeds.
    public func prepareAccountlessRuntime(facade: RustDomainFacade, reviewEnabled: Bool = false)
        async throws -> RustWorkspaceRuntime {
        let report = try await run()
        let document = try await retainedDocument(report)
        guard document.account == nil else {
            throw RustStoreImportError.failed(RustBridgeError(code: "INVALID_REQUEST", field: "account_less_import"))
        }
        let retained = retainedSourceURL(report)
        let workspace = try await runtime.openStore(workspaceID: workspaceID, databaseURL: databaseURL,
            busyTimeoutMilliseconds: busyTimeoutMilliseconds)
        do {
            guard case .ready = try await workspace.status() else { throw RustBridgeError(code: "READ_ONLY_RECOVERY") }
            let metadata = try await workspace.captureLegacyReviewMetadata()
            guard let token = try JSONSerialization.jsonObject(with: metadata.token) as? [String: Any],
                  token["import_source_sha256"] as? String == report.sourceSHA256 else {
                throw RustStoreImportError.sourceChanged
            }
            let instant = now()
            let inputs = try facade.workspaceQueryInputs(at: instant, zone: facade.context.deviceTimeZone,
                reviewExposed: reviewEnabled)
            guard let root = try JSONSerialization.jsonObject(with: inputs) as? [String: Any], let policy = root["policy"] else {
                throw RustDomainError.malformedResult
            }
            let context = RustWorkspaceContext(now: instant, timeZone: facade.context.deviceTimeZone,
                actorID: facade.context.actorID, policy: try JSONSerialization.data(withJSONObject: policy, options: [.sortedKeys]))
            var bindings: [RustWorkspaceIdentityBinding] = []
            if !metadata.alreadyActive {
                let identities = Self.reviewIdentities(in: document.base)
                for offset in stride(from: 0, to: identities.count, by: 200) {
                    bindings += try await workspace.resolveIdentities(Array(identities[offset..<min(offset + 200, identities.count)]))
                }
                let prepared = try facade.workspacePrepareLegacyReview(document.base, bindings: bindings)
                _ = try await workspace.activateLegacyReview(metadata, prepared: prepared, context: context)
            }
            try await workspace.establishAccountlessFromImport(retainedSourceURL: retained)
            for source in Self.privateReviewSources(in: document.base) {
                if try await workspace.localReviewPrivateSourceCompleted(retainedSourceURL: retained, selected: source) { continue }
                var cursor: String?
                repeat {
                    guard let fragment = try await workspace.captureLocalReviewPrivateFragment(retainedSourceURL: retained,
                        selected: source, after: cursor, now: now()) else { break }
                    let prepared = try facade.workspacePrepareLegacyReviewPrivate(fragment.page, now: now())
                    _ = try await workspace.admitLocalReviewPrivateFragment(retainedSourceURL: retained, prepared: prepared, now: now())
                    cursor = fragment.nextCursor
                } while cursor != nil
            }
            let outbox = RustOutboxImporter(runtime: runtime, databaseURL: databaseURL, workspaceID: workspaceID,
                busyTimeoutMilliseconds: busyTimeoutMilliseconds, now: now)
            _ = try await outbox.run()
            let unsent = try await workspace.legacyUnsent()
            guard unsent.count <= 200 else { throw RustBridgeError(code: "TOO_MANY_ITEMS", field: "legacy_outbox") }
            if !unsent.isEmpty {
                let decoder = StoreDocumentCoding.makeDecoder()
                let commands = try unsent.map { try decoder.decode(GTDCommand.self, from: $0.command) }
                let dates = try unsent.map { entry -> Date in
                    guard let date = ISO8601Timestamp.date(from: entry.issuedAt) else { throw RustBridgeError(code: "INVALID_REQUEST", field: "issued_at") }
                    return date
                }
                let requests = try facade.workspaceIdentityRequests(for: commands, in: document.base, at: instant)
                bindings = []
                for offset in stride(from: 0, to: requests.count, by: 200) {
                    bindings += try await workspace.resolveIdentities(Array(requests[offset..<min(offset + 200, requests.count)]))
                }
                let encoded = try facade.workspaceLegacyCommands(commands, commandKeys: unsent.map(\.idempotencyKey),
                    at: dates, in: document.base, bindings: bindings)
                let conversion = zip(unsent, encoded).map { RustWorkspaceLegacyConversion(entryID: $0.0.entryID,
                    issuedAt: $0.0.issuedAt, command: $0.1) }
                guard case .saved = try await workspace.convertLegacyUnsent(conversion, context: context) else {
                    throw RustBridgeError(code: "LEGACY_CONVERSION_REFUSED")
                }
            }
            guard try await outbox.run().mayRun else { throw RustBridgeError(code: "LEGACY_OUTBOX_NOT_READY") }
            return workspace
        } catch {
            try? await workspace.close()
            throw error
        }
    }

    private func retainedSourceURL(_ report: RustLegacyImportReport) -> URL {
        (backupDirectory ?? legacyFile.url.deletingLastPathComponent()).appendingPathComponent(report.backupFile)
    }

    /// Check the exact owned bytes before decoding; a second path read would
    /// not prove that the native codec saw the admitted original source.
    func retainedDocument(_ report: RustLegacyImportReport) async throws -> StoreDocument {
        let retained = retainedSourceURL(report)
        let bytes = try await Task.detached(priority: .userInitiated) { try Data(contentsOf: retained) }.value
        guard UInt64(bytes.count) == report.sourceBytes,
              try await runtime.importSourceSHA256(bytes) == report.sourceSHA256 else { throw RustStoreImportError.sourceChanged }
        return try await Task.detached(priority: .userInitiated) { try StoreDocumentCoding.decode(bytes) }.value
    }

    private static func reviewIdentities(in state: GTDState) -> [RustWorkspaceIdentityRequest] {
        state.tasks.keys.sorted().map { .init(entityType: "task", localID: $0.rawValue) }
        + state.projects.keys.sorted().map { .init(entityType: "project", localID: $0.rawValue) }
        + state.tags.keys.sorted().map { .init(entityType: "tag", localID: $0.rawValue) }
        + state.review.sessions.keys.sorted().map { .init(entityType: "review_session", localID: $0.rawValue) }
        + state.review.decisions.keys.sorted().map { .init(entityType: "review_decision", localID: $0.rawValue) }
        + state.review.bulkReleases.keys.sorted().map { .init(entityType: "review_bulk_release", localID: $0.rawValue) }
    }

    private static func privateReviewSources(in state: GTDState) -> [RustWorkspaceLocalReviewSource] {
        [.init(.settings, sourceID: "settings")]
        + state.review.sessions.keys.sorted().map { .init(.session, sourceID: $0.rawValue) }
        + state.review.decisions.keys.sorted().map { .init(.decision, sourceID: $0.rawValue) }
        + state.review.bulkReleases.keys.sorted().map { .init(.bulkRelease, sourceID: $0.rawValue) }
        + state.tasks.values.filter { $0.parked != nil }.sorted { $0.id < $1.id }.map { .init(.taskPark, sourceID: $0.id.rawValue) }
    }

    private func attempt() async throws -> RustLegacyImportReport {
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
