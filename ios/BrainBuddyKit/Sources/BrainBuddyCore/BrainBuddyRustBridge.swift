import BrainBuddyRustBindings
import Foundation

// The Swift face of the shared Rust core's bridge (spec 026, contracts/runtime-ffi.md).
// The UniFFI-generated `BrainBuddyRustBindings` module is imported here and nowhere else,
// so no generated type is part of the kit's API. Everything that crosses is an owned
// value (`Data`, `String`, integers); there are no pointers, and no error carries
// payload text. This mirrors the Python bridge (`rust/bindings/python`).

/// A typed, content-free failure of the Rust bridge: a stable `code`, whether retrying
/// can help, and the static name of the rule or field it concerns.
///
/// `CANCELLED` is raised on this side too, when the calling task was cancelled.
public struct RustBridgeError: Error, Equatable, Sendable, CustomStringConvertible {
    public let code: String
    public let retryable: Bool
    public let field: String?

    public init(code: String, retryable: Bool = false, field: String? = nil) {
        self.code = code
        self.retryable = retryable
        self.field = field
    }

    /// The calling task was cancelled before or while the call ran; nothing was kept.
    public static let cancelled = RustBridgeError(code: "CANCELLED")

    public var description: String {
        if let field { return "\(code) (\(field))" }
        return code
    }

    /// Maps whatever the generated bindings threw. A panic that escaped the Rust guard,
    /// or any unexpected binding error, is reported as `INTERNAL_ERROR` without its
    /// message, which could embed input text.
    fileprivate init(thrown error: any Error) {
        if let bridge = error as? BridgeError, case let .Failed(code, retryable, field) = bridge {
            self.init(code: code, retryable: retryable, field: field)
        } else if let existing = error as? RustBridgeError {
            self = existing
        } else {
            self.init(code: "INTERNAL_ERROR")
        }
    }
}

/// A command envelope decoded and validated by the Rust codec (sync-v1 section 3).
public struct RustDecodedCommand: Equatable, Sendable {
    public let protocolVersion: UInt32
    public let commandID: String
    public let scopeID: String
    public let deviceID: String
    /// A decimal string: counters can exceed what JSON numbers (and `Double`) hold exactly.
    public let localSequence: String
    public let commandType: String
    public let commandVersion: UInt32
    public let entityID: String
    /// True when this build can execute the command. Otherwise `unsupportedReason`
    /// says why, and the command is kept in its stable recovery form (`UPGRADE_REQUIRED`).
    public let executable: Bool
    public let unsupportedReason: String?
    /// The stable envelope as wire bytes; omitted optional fields stay omitted.
    public let wire: Data

    fileprivate init(_ command: BridgeCommand) {
        protocolVersion = command.protocolVersion
        commandID = command.commandId
        scopeID = command.scopeId
        deviceID = command.deviceId
        localSequence = command.localSequence
        commandType = command.commandType
        commandVersion = command.commandVersion
        entityID = command.entityId
        executable = command.executable
        unsupportedReason = command.unsupportedReason
        wire = command.wire
    }
}

/// A typed domain refusal: a stable reason code and, at most, the field or record it
/// concerns. Never user text (026-FR-022).
public struct RustRefusal: Equatable, Sendable {
    /// The wire spelling of the core's refusal reason, such as `empty_title`.
    public let reason: String
    /// The request field or payload key concerned.
    public let field: String?
    /// The record type of `entityKey` (`task`, `project`, ...).
    public let entityType: String?
    public let entityKey: [String]
    /// The revision a stale check saw, as a decimal string.
    public let currentRevision: String?

    public init(
        reason: String, field: String? = nil, entityType: String? = nil, entityKey: [String] = [],
        currentRevision: String? = nil
    ) {
        self.reason = reason
        self.field = field
        self.entityType = entityType
        self.entityKey = entityKey
        self.currentRevision = currentRevision
    }

    fileprivate init(_ refusal: BridgeRefusal) {
        self.init(
            reason: refusal.reason, field: refusal.field, entityType: refusal.entityType,
            entityKey: refusal.entityKey, currentRevision: refusal.currentRevision)
    }
}

/// What the core's `decide` answered: the change set as JSON bytes, or a refusal.
public enum RustDecision: Equatable, Sendable {
    case changed(Data)
    case refused(RustRefusal)
}

/// What the core's `query` and Smart Add reads answered: the result as JSON bytes, or a refusal.
public enum RustAnswer: Equatable, Sendable {
    case answered(Data)
    case refused(RustRefusal)
}

/// What a legacy `StoreDocument` file holds, counted by the means any reader of the file has
/// (spec 026, T041). The Swift importer counts the file with the kit's own decoder and the
/// Rust importer counts the same bytes with its own reader; the two must agree before the
/// store is switched.
public struct RustImportCounts: Equatable, Hashable, Sendable {
    public var tasks: UInt64
    public var subtasks: UInt64
    public var comments: UInt64
    public var projects: UInt64
    public var tags: UInt64
    /// Pending operations; carried whole for the outbox import.
    public var outboxEntries: UInt64
    /// Sync issues; carried whole for the outbox import.
    public var issues: UInt64
    public var reviewSessions: UInt64
    public var reviewDecisions: UInt64
    public var reviewReceipts: UInt64
    public var reviewParkAcks: UInt64
    public var reviewBulkReleases: UInt64
    public var reviewNavigatorConsents: UInt64
    /// Unsaved Review form text (`local.formDrafts`).
    public var formDrafts: UInt64

    public init(
        tasks: UInt64 = 0, subtasks: UInt64 = 0, comments: UInt64 = 0, projects: UInt64 = 0, tags: UInt64 = 0,
        outboxEntries: UInt64 = 0, issues: UInt64 = 0, reviewSessions: UInt64 = 0, reviewDecisions: UInt64 = 0,
        reviewReceipts: UInt64 = 0, reviewParkAcks: UInt64 = 0, reviewBulkReleases: UInt64 = 0,
        reviewNavigatorConsents: UInt64 = 0, formDrafts: UInt64 = 0
    ) {
        self.tasks = tasks
        self.subtasks = subtasks
        self.comments = comments
        self.projects = projects
        self.tags = tags
        self.outboxEntries = outboxEntries
        self.issues = issues
        self.reviewSessions = reviewSessions
        self.reviewDecisions = reviewDecisions
        self.reviewReceipts = reviewReceipts
        self.reviewParkAcks = reviewParkAcks
        self.reviewBulkReleases = reviewBulkReleases
        self.reviewNavigatorConsents = reviewNavigatorConsents
        self.formDrafts = formDrafts
    }

    fileprivate init(_ counts: BridgeImportCounts) {
        self.init(
            tasks: counts.tasks, subtasks: counts.subtasks, comments: counts.comments, projects: counts.projects,
            tags: counts.tags, outboxEntries: counts.outboxEntries, issues: counts.issues,
            reviewSessions: counts.reviewSessions, reviewDecisions: counts.reviewDecisions,
            reviewReceipts: counts.reviewReceipts, reviewParkAcks: counts.reviewParkAcks,
            reviewBulkReleases: counts.reviewBulkReleases, reviewNavigatorConsents: counts.reviewNavigatorConsents,
            formDrafts: counts.formDrafts)
    }

    fileprivate var bridged: BridgeImportCounts {
        BridgeImportCounts(
            tasks: tasks, subtasks: subtasks, comments: comments, projects: projects, tags: tags,
            outboxEntries: outboxEntries, issues: issues, reviewSessions: reviewSessions,
            reviewDecisions: reviewDecisions, reviewReceipts: reviewReceipts, reviewParkAcks: reviewParkAcks,
            reviewBulkReleases: reviewBulkReleases, reviewNavigatorConsents: reviewNavigatorConsents,
            formDrafts: formDrafts)
    }
}

/// The import of the legacy `StoreDocument` file into the Rust store of one workspace.
public struct RustLegacyImportRequest: Equatable, Sendable {
    public var workspaceID: String
    /// The Rust store file. Created when it does not exist.
    public var databasePath: String
    /// The legacy JSON file. It is only read.
    public var sourcePath: String
    /// Where the backup and the schema manifest go; beside the source when nil.
    public var backupDirectory: String?
    /// The instant of the import, RFC 3339.
    public var now: String
    /// The bound on every lock wait; running out is a retryable `STORE_BUSY`.
    public var busyTimeoutMilliseconds: UInt32
    /// The counts an independent reader took from the same file.
    public var expected: RustImportCounts?

    public init(
        workspaceID: String, databasePath: String, sourcePath: String, backupDirectory: String? = nil,
        now: String, busyTimeoutMilliseconds: UInt32 = 5_000, expected: RustImportCounts? = nil
    ) {
        self.workspaceID = workspaceID
        self.databasePath = databasePath
        self.sourcePath = sourcePath
        self.backupDirectory = backupDirectory
        self.now = now
        self.busyTimeoutMilliseconds = busyTimeoutMilliseconds
        self.expected = expected
    }

    fileprivate var bridged: BridgeImportRequest {
        BridgeImportRequest(
            workspaceId: workspaceID, databasePath: databasePath, sourcePath: sourcePath,
            backupDirectory: backupDirectory, now: now, busyTimeoutMs: busyTimeoutMilliseconds,
            expected: expected?.bridged)
    }
}

/// The activation marker of a finished import: what the legacy file was and what was
/// kept of it. No user text.
public struct RustLegacyImportReport: Equatable, Sendable {
    /// The same file had already been imported: nothing was done.
    public let alreadyActive: Bool
    /// SHA-256 of the legacy file's bytes, lowercase hex.
    public let sourceSHA256: String
    public let sourceBytes: UInt64
    public let sourceVersion: Int64
    public let sourceGeneration: Int64
    /// File names, beside the source (or in the requested directory).
    public let backupFile: String
    public let manifestFile: String
    public let importedAt: String
    public let counts: RustImportCounts
    /// Identity aliases written (a server ID the file proved for a local ID).
    public let aliases: UInt64
    /// Tasks whose local-only facts (`lastOpenList`, `childrenSyncedAt`, the private part of a
    /// park) were kept.
    public let localTaskFacts: UInt64

    fileprivate init(_ report: BridgeImportReport) {
        alreadyActive = report.alreadyActive
        sourceSHA256 = report.sourceSha256
        sourceBytes = report.sourceBytes
        sourceVersion = report.sourceVersion
        sourceGeneration = report.sourceGeneration
        backupFile = report.backupFile
        manifestFile = report.manifestFile
        importedAt = report.importedAt
        counts = RustImportCounts(report.counts)
        aliases = report.aliases
        localTaskFacts = report.localTaskFacts
    }
}

/// One bridge runtime handle. It is safe to share between tasks and threads; `close()`
/// is final and idempotent, and later calls fail with `WORKSPACE_CLOSED`.
public final class RustBridgeRuntime: Sendable {
    // The generated class is `Sendable`: the Rust object behind it is `Send + Sync`
    // (an atomic lifecycle state), which UniFFI requires of every exported object.
    private let runtime: BridgeRuntime

    /// The sync protocol version this build speaks.
    public static var supportedProtocolVersion: UInt32 { bridgeProtocolVersion() }

    /// Opens a runtime. An unsupported `protocolVersion` fails with `UPGRADE_REQUIRED`.
    public init(protocolVersion: UInt32 = RustBridgeRuntime.supportedProtocolVersion) throws {
        do {
            runtime = try BridgeRuntime(protocolVersion: protocolVersion)
        } catch {
            throw RustBridgeError(thrown: error)
        }
    }

    public var isOpen: Bool { runtime.isOpen() }

    /// Closes the runtime. Calls still running report `CANCELLED`.
    public func close() { runtime.close() }

    /// Decodes and validates one command envelope off the caller's actor.
    ///
    /// A cancelled caller gets `CANCELLED` and nothing is kept. The call is pure, so a
    /// cancellation that lands while it runs discards the result rather than interrupting
    /// the Rust code.
    public func decodeCommand(_ data: Data) async throws -> RustDecodedCommand {
        if Task.isCancelled { throw RustBridgeError.cancelled }
        let runtime = self.runtime
        let outcome = await Task.detached(priority: .userInitiated) {
            () -> Result<BridgeCommand, RustBridgeError> in
            do {
                return .success(try runtime.decodeCommand(data: data))
            } catch {
                return .failure(RustBridgeError(thrown: error))
            }
        }.value
        if Task.isCancelled { throw RustBridgeError.cancelled }
        return RustDecodedCommand(try outcome.get())
    }

    /// Decides one command envelope against an owned read set, off the caller's actor. A
    /// refusal of the rules is a value; only a bridge failure throws.
    public func decide(readSet: Data, envelope: Data, receipts: Data, inputs: Data) async throws -> RustDecision {
        try await offActor { (runtime: BridgeRuntime) throws -> RustDecision in
            switch try runtime.decide(readSet: readSet, envelope: envelope, receipts: receipts, inputs: inputs) {
            case .changed(let changeSet): return .changed(changeSet)
            case .refused(let refusal): return .refused(RustRefusal(refusal))
            }
        }
    }

    /// Answers one typed query over an owned read set, off the caller's actor.
    public func query(readSet: Data, query: Data, inputs: Data) async throws -> RustAnswer {
        try await offActor { (runtime: BridgeRuntime) throws -> RustAnswer in
            switch try runtime.query(readSet: readSet, query: query, inputs: inputs) {
            case .answered(let result): return .answered(result)
            case .refused(let refusal): return .refused(RustRefusal(refusal))
            }
        }
    }

    /// Resolves a Smart Add draft against an owned read set (the capture sheet's preview).
    public func smartAddResolve(readSet: Data, draft: Data) async throws -> Data {
        try await offActor { (runtime: BridgeRuntime) throws -> Data in
            try runtime.smartAddResolve(readSet: readSet, draft: draft)
        }
    }

    /// The `task.smart_add` payload a draft would send, given the IDs minted for the records
    /// it creates; a blocked draft is a refusal.
    public func smartAddPropose(readSet: Data, draft: Data, minted: Data) async throws -> RustAnswer {
        try await offActor { (runtime: BridgeRuntime) throws -> RustAnswer in
            switch try runtime.smartAddPropose(readSet: readSet, draft: draft, minted: minted) {
            case .answered(let result): return .answered(result)
            case .refused(let refusal): return .refused(RustRefusal(refusal))
            }
        }
    }

    /// Imports the legacy `StoreDocument` file into the Rust store, off the caller's actor.
    ///
    /// The file is only read; the store switches in one transaction after the imported rows were
    /// checked against it, or not at all, so every failure leaves the legacy file as it was. A
    /// caller that was cancelled before the call gets `CANCELLED` and nothing is done. One that is
    /// cancelled while it runs also gets `CANCELLED`, but the import is atomic and runs to its end:
    /// call again and it reports `alreadyActive`.
    public func importLegacyStore(_ request: RustLegacyImportRequest) async throws -> RustLegacyImportReport {
        let bridged = request.bridged
        return try await offActor { (runtime: BridgeRuntime) throws -> RustLegacyImportReport in
            RustLegacyImportReport(try runtime.importLegacyStore(request: bridged))
        }
    }

    /// Runs one pure call off the caller's actor. A cancelled caller gets `CANCELLED` and
    /// nothing is kept.
    private func offActor<Output: Sendable>(
        _ work: @escaping @Sendable (BridgeRuntime) throws -> Output
    ) async throws -> Output {
        if Task.isCancelled { throw RustBridgeError.cancelled }
        let runtime = self.runtime
        let outcome = await Task.detached(priority: .userInitiated) { () -> Result<Output, RustBridgeError> in
            do {
                return .success(try work(runtime))
            } catch {
                return .failure(RustBridgeError(thrown: error))
            }
        }.value
        if Task.isCancelled { throw RustBridgeError.cancelled }
        return try outcome.get()
    }
}
