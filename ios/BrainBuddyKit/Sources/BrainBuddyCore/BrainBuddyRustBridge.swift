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

/// A server ID a retained receipt proved for a local ID of an old command (spec 026, T042).
public struct RustLegacyAlias: Equatable, Hashable, Sendable {
    /// The wire name of the entity type (`task`, `project`, ...).
    public var entityType: String
    public var oldLocalID: String
    public var serverID: String

    public init(entityType: String, oldLocalID: String, serverID: String) {
        self.entityType = entityType
        self.oldLocalID = oldLocalID
        self.serverID = serverID
    }

    fileprivate var bridged: BridgeLegacyAlias {
        BridgeLegacyAlias(entityType: entityType, oldLocalId: oldLocalID, serverId: serverID)
    }
}

/// What the server can prove about one old send. Only a receipt for the send's own idempotency key
/// is proof; a missing receipt, a pending one or no answer at all is `.unproven`, and a title, list or
/// time is never evidence of anything.
public enum RustLegacyAnswer: Equatable, Hashable, Sendable {
    /// A retained receipt says the server did it (or it was a no-op), and the identities it proves.
    case accepted(aliases: [RustLegacyAlias])
    /// A retained receipt says the server refused it; `code` is its error code.
    case rejected(code: String)
    case unproven

    fileprivate var bridged: BridgeLegacyAnswer {
        switch self {
        case .accepted(let aliases): .accepted(aliases: aliases.map(\.bridged))
        case .rejected(let code): .rejected(code: code)
        case .unproven: .unproven
        }
    }
}

/// One old send still to ask the server about, by the key it was made with.
public struct RustLegacySend: Equatable, Hashable, Sendable {
    public let entryID: String
    public let idempotencyKey: String
    /// The old command as the legacy file held it, JSON.
    public let command: Data

    fileprivate init(_ send: BridgeLegacySend) {
        entryID = send.entryId
        idempotencyKey = send.idempotencyKey
        command = send.command
    }
}

/// The classification of the outbox a legacy import carried (spec 026, T042).
public struct RustLegacyOutboxRequest: Equatable, Sendable {
    public var workspaceID: String
    public var databasePath: String
    /// The instant of the classification, RFC 3339: the 24-hour window ends against it.
    public var now: String
    public var busyTimeoutMilliseconds: UInt32
    /// The answers already fetched, by idempotency key (case does not matter). A key without an
    /// answer is `.unproven`.
    public var receipts: [String: RustLegacyAnswer]

    public init(
        workspaceID: String, databasePath: String, now: String, busyTimeoutMilliseconds: UInt32 = 5_000,
        receipts: [String: RustLegacyAnswer] = [:]
    ) {
        self.workspaceID = workspaceID
        self.databasePath = databasePath
        self.now = now
        self.busyTimeoutMilliseconds = busyTimeoutMilliseconds
        self.receipts = receipts
    }

    fileprivate var bridged: BridgeLegacyOutboxRequest {
        BridgeLegacyOutboxRequest(
            workspaceId: workspaceID, databasePath: databasePath, now: now, busyTimeoutMs: busyTimeoutMilliseconds,
            receipts: receipts.sorted { $0.key < $1.key }.map {
                BridgeLegacyReceipt(idempotencyKey: $0.key, answer: $0.value.bridged)
            })
    }
}

/// Where the legacy outbox stands. Counts only; no user text.
public struct RustLegacyOutboxStatus: Equatable, Sendable {
    /// Pending sends the import carried, and what became of them.
    public let carried: UInt64
    /// Never sent: the intent is still pending and waits to become a new command.
    public let unsent: UInt64
    /// Durable runtime commands still awaiting their server outcome.
    public let converted: UInt64
    /// Settled by a receipt for their own key.
    public let accepted: UInt64
    /// Refused by the server: an issue keeps the intent.
    public let rejected: UInt64
    /// Sent, no proof yet, and the server still keeps the key.
    public let awaiting: UInt64
    /// Sent, no proof, window over: an issue keeps everything, never reissued.
    public let uncertain: UInt64
    public let carriedIssues: UInt64
    public let convertedIssues: UInt64
    /// Issues of legacy origin still waiting for the user or for proof.
    public let openIssues: UInt64
    /// Identities receipts proved.
    public let aliases: UInt64
    /// Every carried entry and issue has a verdict.
    public let classified: Bool
    /// The Rust store may take the workspace: classified, and no untouched intent waits.
    public let mayRun: Bool
    /// Nothing of the old file waits on the server or the user. Never true while an uncertain
    /// submission or an old issue exists.
    public let fullySynced: Bool

    fileprivate init(_ status: BridgeLegacyOutboxStatus) {
        carried = status.carried
        unsent = status.unsent
        converted = status.converted
        accepted = status.accepted
        rejected = status.rejected
        awaiting = status.awaiting
        uncertain = status.uncertain
        carriedIssues = status.carriedIssues
        convertedIssues = status.convertedIssues
        openIssues = status.openIssues
        aliases = status.aliases
        classified = status.classified
        mayRun = status.mayRun
        fullySynced = status.fullySynced
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

    /// Hash the same owned bytes that the importer decodes, in bounded chunks.
    /// This ephemeral digest is integrity evidence, never workspace authority.
    public func importSourceSHA256(_ data: Data) async throws -> String {
        try await offActor { _ in
            let digest = BridgeDigest()
            let chunkLimit = 8 * 1024 * 1024
            var offset = 0
            while offset < data.count {
                let end = min(data.count, offset + chunkLimit)
                try digest.update(data: Data(data[offset..<end]))
                offset = end
            }
            return try digest.digest()
        }
    }

    /// The old sends a receipt lookup is still needed for, read from the Rust store (spec 026,
    /// T042): the legacy file is not read again. Only the workspace, the path and the busy timeout
    /// of `request` are used.
    public func legacyOutboxSends(_ request: RustLegacyOutboxRequest) async throws -> [RustLegacySend] {
        let bridged = request.bridged
        return try await offActor { (runtime: BridgeRuntime) throws -> [RustLegacySend] in
            try runtime.legacyOutboxSends(request: bridged).map(RustLegacySend.init)
        }
    }

    /// Classifies the outbox and issues a legacy import carried, off the caller's actor: a send a
    /// receipt proves is settled, one that may have reached the server stays an issue and is never
    /// reissued. One transaction, or nothing; running it again is safe.
    public func resolveLegacyOutbox(_ request: RustLegacyOutboxRequest) async throws -> RustLegacyOutboxStatus {
        let bridged = request.bridged
        return try await offActor { (runtime: BridgeRuntime) throws -> RustLegacyOutboxStatus in
            RustLegacyOutboxStatus(try runtime.resolveLegacyOutbox(request: bridged))
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

// MARK: - Durable workspace

/// One immutable catalog intent. Keep commandID with the draft until completion
/// is known; retrying with a fresh ID could save the same intent twice.
public struct RustWorkspaceCommand: Equatable, Sendable, Codable {
    public let commandID: String
    public let commandType: String
    public let entityID: String?
    public let payload: Data
    public let preconditions: Data
    public let dependsOn: [String]
    public let admissionTokens: Data

    public init(commandID: String, commandType: String, entityID: String?, payload: Data,
                preconditions: Data = Data("[]".utf8), dependsOn: [String] = [],
                admissionTokens: Data = Data("[]".utf8)) {
        self.commandID = commandID
        self.commandType = commandType
        self.entityID = entityID
        self.payload = payload
        self.preconditions = preconditions
        self.dependsOn = dependsOn
        self.admissionTokens = admissionTokens
    }

    enum CodingKeys: String, CodingKey { case commandID, commandType, entityID, payload, preconditions, dependsOn, admissionTokens }

    public init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        commandID = try values.decode(String.self, forKey: .commandID)
        commandType = try values.decode(String.self, forKey: .commandType)
        entityID = try values.decodeIfPresent(String.self, forKey: .entityID)
        payload = try values.decode(Data.self, forKey: .payload)
        preconditions = try values.decode(Data.self, forKey: .preconditions)
        dependsOn = try values.decode([String].self, forKey: .dependsOn)
        admissionTokens = try values.decodeIfPresent(Data.self, forKey: .admissionTokens) ?? Data("[]".utf8)
    }

    fileprivate var bridged: BridgeWorkspaceCommand {
        BridgeWorkspaceCommand(commandId: commandID, commandType: commandType, entityId: entityID,
                               payload: payload, preconditions: preconditions, dependsOn: dependsOn, admissionTokens: admissionTokens)
    }
}

public struct RustWorkspaceContext: Sendable, Codable {
    public let now: Date
    public let timeZone: String
    public let actorID: String
    public let policy: Data

    public init(now: Date, timeZone: String, actorID: String, policy: Data) {
        self.now = now
        self.timeZone = timeZone
        self.actorID = actorID
        self.policy = policy
    }

    fileprivate var bridged: BridgeExecuteContext {
        BridgeExecuteContext(now: RustInstant.format(now), timeZone: timeZone, actorId: actorID, policy: policy)
    }
}

public struct RustWorkspaceSaved: Equatable, Sendable {
    public let commandID: String
    public let entityID: String
    public let localSequence: String
    public let projectionGeneration: String
    public let replayed: Bool

    fileprivate init(_ value: BridgeSaved) {
        commandID = value.commandId
        entityID = value.entityId
        localSequence = value.localSequence
        projectionGeneration = value.projectionGeneration
        replayed = value.replayed
    }
}

public enum RustWorkspaceExecution: Equatable, Sendable {
    case saved([RustWorkspaceSaved])
    case refused(RustRefusal, failedCommandID: String? = nil)
}

public struct RustWorkspacePage: Equatable, Sendable {
    public let projectionGeneration: String
    public let result: Data
    public let collectionNextCursor: String?
    public let taskFrames: Data

    public init(projectionGeneration: String, result: Data, collectionNextCursor: String? = nil,
                taskFrames: Data = Data("[]".utf8)) {
        self.projectionGeneration = projectionGeneration
        self.result = result
        self.collectionNextCursor = collectionNextCursor
        self.taskFrames = taskFrames
    }
}

public enum RustWorkspaceAnswer: Equatable, Sendable {
    case answered(RustWorkspacePage)
    case refused(RustRefusal, projectionGeneration: String? = nil)
}

public struct RustWorkspaceSnapshot: Equatable, Sendable {
    public let projectionGeneration: String
    public let records: Data
    public let pending: String
    public let openIssues: String
}

public struct RustWorkspaceLegacyUnsent: Equatable, Sendable {
    public let entryID: String
    public let idempotencyKey: String
    public let issuedAt: String
    public let command: Data
}

public struct RustWorkspaceLegacyConversion: Equatable, Sendable {
    public let entryID: String
    public let issuedAt: String
    public let command: RustWorkspaceCommand

    public init(entryID: String, issuedAt: String, command: RustWorkspaceCommand) {
        self.entryID = entryID
        self.issuedAt = issuedAt
        self.command = command
    }
}

public struct RustWorkspaceLegacyConversionPlan: Sendable {
    public let token: String
    public let context: RustWorkspaceContext
    public let sourceCount: UInt64
    public let atomicGroup: Bool
}
public struct RustWorkspaceLegacyConversionPage: Sendable {
    public let items: [RustWorkspaceLegacyUnsent]
    public let pageToken: String
    public let nextAfter: String?
}
public struct RustWorkspaceLegacyConversionProgress: Sendable {
    public let sourceCount: UInt64
    public let processedCount: UInt64
    public let complete: Bool
    public let status: RustLegacyOutboxStatus

    fileprivate init(_ value: BridgeLegacyConversionProgress) {
        sourceCount = value.sourceCount
        processedCount = value.processedCount
        complete = value.complete
        status = RustLegacyOutboxStatus(value.status)
    }
}

public struct RustWorkspaceIdentityRequest: Hashable, Sendable {
    public let entityType: String
    public let localID: String

    public init(entityType: String, localID: String) {
        self.entityType = entityType
        self.localID = localID
    }
}

public struct RustWorkspaceRecordRequest: Equatable, Sendable {
    public let entityType: String
    public let recordKey: [String]

    public init(entityType: String, recordKey: [String]) {
        self.entityType = entityType
        self.recordKey = recordKey
    }
}

public struct RustWorkspaceIdentityBinding: Equatable, Sendable {
    public let entityType: String
    public let localID: String
    public let canonicalID: String?

    public init(entityType: String, localID: String, canonicalID: String?) {
        self.entityType = entityType
        self.localID = localID
        self.canonicalID = canonicalID
    }
}

/// Device-local editor metadata in the runtime's existing drafts table.
/// A prepared gesture keeps its exact command IDs, payload and trusted context
/// here before execution, so reopening can reconcile the original receipt.
public struct RustWorkspaceDraft: Equatable, Sendable {
    public let draftID: String
    public let editorKind: String
    public let recordType: String?
    public let recordKey: String?
    public let baseRevision: String?
    public let fields: Data
    public let updatedAt: String

    public init(draftID: String, editorKind: String, recordType: String? = nil, recordKey: String? = nil,
                baseRevision: String? = nil, fields: Data, updatedAt: String) {
        self.draftID = draftID
        self.editorKind = editorKind
        self.recordType = recordType
        self.recordKey = recordKey
        self.baseRevision = baseRevision
        self.fields = fields
        self.updatedAt = updatedAt
    }

    fileprivate var bridged: BridgeWorkspaceDraft {
        BridgeWorkspaceDraft(draftId: draftID, editorKind: editorKind, recordType: recordType,
            recordKey: recordKey, baseRevision: baseRevision, fields: fields, updatedAt: updatedAt)
    }

    fileprivate init(_ draft: BridgeWorkspaceDraft) {
        self.init(draftID: draft.draftId, editorKind: draft.editorKind, recordType: draft.recordType,
            recordKey: draft.recordKey, baseRevision: draft.baseRevision, fields: draft.fields, updatedAt: draft.updatedAt)
    }
}

public struct RustWorkspaceReviewFormLoaded: Sendable {
    public let sourceKey: String
    public let draft: FormDraft?
    public let liveCount: Int
    public let projectionGeneration: String
}

public struct RustWorkspaceReviewFormCount: Sendable {
    public let liveCount: Int
    public let projectionGeneration: String
}

public struct RustWorkspaceSourceIdentityRequest: Sendable {
    public let entityType: String
    public let canonicalID: String
    public init(entityType: String, canonicalID: String) {
        self.entityType = entityType
        self.canonicalID = canonicalID
    }
}

public struct RustWorkspaceSourceIdentityBinding: Sendable {
    public let entityType: String
    public let canonicalID: String
    public let sourceID: String?
}

public enum RustWorkspaceStoreStatus: Equatable, Sendable {
    case ready
    case readOnlyRecovery(found: Int64)
}

public struct RustWorkspaceLegacyReview: Sendable {
    public let token: Data
    public let review: Data
    public let aliases: Data
    public let sourceCounts: Data
    public let alreadyActive: Bool
}

public struct RustWorkspaceLegacyReviewMetadata: Sendable {
    public let token: Data
    public let sourceCounts: Data
    public let alreadyActive: Bool
}

public struct RustWorkspaceReviewActivated: Sendable {
    public let projectionGeneration: String
    public let alreadyActive: Bool
    public let aliases: Data
}

/// Original legacy identity only; private bodies stay in the retained source.
public struct RustWorkspaceLocalReviewSource: Codable, Hashable, Sendable {
    public enum Kind: String, Codable, Hashable, Sendable {
        case decision, bulkRelease = "bulk_release", taskPark = "task_park", session, settings
    }
    public let sourceKind: Kind
    public let sourceID: String

    public init(_ sourceKind: Kind, sourceID: String) {
        self.sourceKind = sourceKind
        self.sourceID = sourceID
    }

    enum CodingKeys: String, CodingKey {
        case sourceKind = "source_kind", sourceID = "source_id"
    }
}

public struct RustWorkspaceLocalReviewFragment: Sendable {
    public let page: Data
    public let nextCursor: String?
}

public enum RustWorkspaceLocalReviewAdmission: Equatable, Sendable {
    case pending(nextOrdinal: UInt32)
    case admitted
    case alreadyAdmitted
}

public struct RustWorkspaceInvalidation: Equatable, Sendable {
    public let projectionGeneration: String
    public let changedKinds: [String]
    public let syncStatusChanged: Bool
    public let issuesChanged: Bool
    public let pending: String
    public let openIssues: String
    public let token: String
}

extension RustBridgeRuntime {
    public func openStore(workspaceID: String, databaseURL: URL, busyTimeoutMilliseconds: UInt32 = 2_000)
        async throws -> RustWorkspaceRuntime {
        let request = BridgeStoreRequest(workspaceId: workspaceID, databasePath: databaseURL.path,
                                        busyTimeoutMs: busyTimeoutMilliseconds)
        return try await offActor { runtime in
            RustWorkspaceRuntime(try runtime.openStore(request: request))
        }
    }
}

/// All disk work runs off the caller's actor. The adapter chooses where to
/// adopt results. The generated handle owns no borrowed buffers or pointers.
public final class RustWorkspaceRuntime: Sendable {
    private let workspace: BridgeWorkspace

    fileprivate init(_ workspace: BridgeWorkspace) { self.workspace = workspace }

    private func offActor<T: Sendable>(_ work: @escaping @Sendable (BridgeWorkspace) throws -> T) async throws -> T {
        if Task.isCancelled { throw RustBridgeError.cancelled }
        let workspace = workspace
        let outcome = await Task.detached(priority: .userInitiated) { () -> Result<T, RustBridgeError> in
            do { return .success(try work(workspace)) }
            catch { return .failure(RustBridgeError(thrown: error)) }
        }.value
        if Task.isCancelled { throw RustBridgeError.cancelled }
        return try outcome.get()
    }

    public func status() async throws -> RustWorkspaceStoreStatus {
        try await offActor { workspace in
            switch try workspace.status() {
            case .ready: return .ready
            case .readOnlyRecovery(let found): return .readOnlyRecovery(found: found)
            }
        }
    }

    /// Explicit trusted lifecycle choice, independently verified by Rust.
    public func establishAccountless() async throws {
        try await committing { workspace, operation in try workspace.establishAccountLess(operation: operation) }
    }

    public func establishAccountlessFromImport(retainedSourceURL: URL) async throws {
        guard retainedSourceURL.isFileURL else { throw RustBridgeError(code: "INVALID_REQUEST", field: "retained_source_path") }
        let path = retainedSourceURL.path
        try await committing { workspace, operation in
            try workspace.establishAccountLessFromImport(retainedSourcePath: path, operation: operation)
        }
    }

    public func pruneLocalReviewPrivate(now: Date, limit: UInt32 = 200) async throws -> UInt32 {
        let instant = RustInstant.format(now)
        return try await committing { workspace, operation in
            try workspace.pruneLocalReviewPrivate(now: instant, limit: limit, operation: operation)
        }
    }

    public func captureLocalReviewPrivateFragment(retainedSourceURL: URL, selected: RustWorkspaceLocalReviewSource,
                                                after: String? = nil, now: Date) async throws -> RustWorkspaceLocalReviewFragment? {
        guard retainedSourceURL.isFileURL else { throw RustBridgeError(code: "INVALID_REQUEST", field: "retained_source_path") }
        let path = retainedSourceURL.path
        let selection = try JSONEncoder().encode(selected)
        let instant = RustInstant.format(now)
        return try await offActor { workspace in
            let page = try workspace.captureLocalReviewPrivateFragment(retainedSourcePath: path, selected: selection,
                after: after, now: instant)
            guard page.count <= 8 * 1024 * 1024 else { throw RustBridgeError(code: "MALFORMED_QUERY_RESULT") }
            let decoded = try JSONSerialization.jsonObject(with: page, options: [.fragmentsAllowed])
            if decoded is NSNull { return nil }
            guard let object = decoded as? [String: Any],
                  object["next_cursor"] is NSNull || object["next_cursor"] is String else {
                throw RustBridgeError(code: "MALFORMED_QUERY_RESULT")
            }
            return RustWorkspaceLocalReviewFragment(page: page, nextCursor: object["next_cursor"] as? String)
        }
    }

    public func localReviewPrivateSourceCompleted(retainedSourceURL: URL,
                                                 selected: RustWorkspaceLocalReviewSource) async throws -> Bool {
        guard retainedSourceURL.isFileURL else { throw RustBridgeError(code: "INVALID_REQUEST", field: "retained_source_path") }
        let path = retainedSourceURL.path
        let selection = try JSONEncoder().encode(selected)
        return try await offActor { workspace in
            try workspace.localReviewPrivateSourceCompleted(retainedSourcePath: path, selected: selection)
        }
    }

    public func admitLocalReviewPrivateFragment(retainedSourceURL: URL,
                                               prepared: RustWorkspaceLegacyReviewPrivatePreparation,
                                               now: Date) async throws -> RustWorkspaceLocalReviewAdmission {
        guard retainedSourceURL.isFileURL else { throw RustBridgeError(code: "INVALID_REQUEST", field: "retained_source_path") }
        let path = retainedSourceURL.path
        let payload = prepared.payload
        let instant = RustInstant.format(now)
        return try await committing { workspace, operation in
            let bytes = try workspace.admitLocalReviewPrivateFragment(retainedSourcePath: path, prepared: payload,
                now: instant, operation: operation)
            guard let object = try JSONSerialization.jsonObject(with: bytes) as? [String: Any] else {
                throw RustBridgeError(code: "MALFORMED_QUERY_RESULT")
            }
            switch object["status"] as? String {
            case "pending":
                guard let ordinal = object["next_ordinal"] as? NSNumber,
                      let next = UInt32(ordinal.stringValue) else { throw RustBridgeError(code: "MALFORMED_QUERY_RESULT") }
                return .pending(nextOrdinal: next)
            case "admitted": return .admitted
            case "already_admitted": return .alreadyAdmitted
            default: throw RustBridgeError(code: "MALFORMED_QUERY_RESULT")
            }
        }
    }

    public func captureLegacyReview() async throws -> RustWorkspaceLegacyReview {
        try await offActor { workspace in
            let source = try workspace.captureLegacyReview()
            return RustWorkspaceLegacyReview(token: source.token, review: source.review, aliases: source.aliases,
                sourceCounts: source.sourceCounts, alreadyActive: source.alreadyActive)
        }
    }

    /// The importer already owns the verified source document. Only immutable
    /// token/count metadata crosses this port; no private legacy body does.
    public func captureLegacyReviewMetadata() async throws -> RustWorkspaceLegacyReviewMetadata {
        try await offActor { workspace in
            let source = try workspace.captureLegacyReviewMetadata()
            return RustWorkspaceLegacyReviewMetadata(token: source.token, sourceCounts: source.sourceCounts,
                alreadyActive: source.alreadyActive)
        }
    }

    public func activateLegacyReview(_ source: RustWorkspaceLegacyReviewMetadata,
                                    prepared: RustWorkspaceReviewPreparation,
                                    context: RustWorkspaceContext) async throws -> RustWorkspaceReviewActivated {
        let metadata = RustWorkspaceLegacyReview(token: source.token, review: Data(), aliases: Data(),
            sourceCounts: source.sourceCounts, alreadyActive: source.alreadyActive)
        return try await activateLegacyReview(metadata, prepared: prepared, context: context)
    }

    public func activateLegacyReview(_ source: RustWorkspaceLegacyReview,
                                    prepared: RustWorkspaceReviewPreparation,
                                    context: RustWorkspaceContext) async throws -> RustWorkspaceReviewActivated {
        let counts = try JSONSerialization.data(withJSONObject: ["decision_queues": prepared.decisionQueues,
            "unseen_park_acks": prepared.unseenParkAcknowledgements], options: [.sortedKeys])
        let request = BridgeLegacyReviewPrepared(token: source.token, readSet: prepared.readSet,
            aliases: prepared.aliases, derivedCounts: counts)
        let context = context.bridged
        return try await committing { workspace, operation in
            let result = try workspace.activateLegacyReview(prepared: request, context: context, operation: operation)
            return RustWorkspaceReviewActivated(projectionGeneration: result.projectionGeneration,
                alreadyActive: result.alreadyActive, aliases: result.aliases)
        }
    }

    /// The committed receipt is delivered even if Task cancellation arrived
    /// after commit. Cancellation that wins before commit returns CANCELLED.
    /// A storage/bridge error leaves caller-owned command IDs available for retry.
    public func execute(_ commands: [RustWorkspaceCommand], context: RustWorkspaceContext)
        async throws -> RustWorkspaceExecution {
        let commands = commands.map(\.bridged)
        let context = context.bridged
        return try await durable { workspace, operation in
            try workspace.execute(commands: commands, context: context, operation: operation)
        }
    }

    /// Read-only recovery: nil means at least one original command is unknown.
    /// It never executes an unknown suffix or creates a replacement gesture.
    public func lookupKnownBatch(_ commands: [RustWorkspaceCommand], context: RustWorkspaceContext)
        async throws -> [RustWorkspaceSaved]? {
        let commands = commands.map(\.bridged)
        let context = context.bridged
        return try await offActor { workspace in
            switch try workspace.lookupKnownBatch(commands: commands, context: context) {
            case .known(let results): return results.map(RustWorkspaceSaved.init)
            case .notKnown: return nil
            }
        }
    }

    /// Source bodies are immutable and read from the imported Rust store.
    /// Only entries proven never sent are eligible for this conversion.
    public func legacyUnsent() async throws -> [RustWorkspaceLegacyUnsent] {
        try await offActor { workspace in
            try workspace.legacyUnsent().map {
                RustWorkspaceLegacyUnsent(entryID: $0.entryId, idempotencyKey: $0.idempotencyKey,
                                          issuedAt: $0.issuedAt, command: $0.command)
            }
        }
    }

    public func resolveIdentities(_ identities: [RustWorkspaceIdentityRequest]) async throws -> [RustWorkspaceIdentityBinding] {
        let items = identities.map { BridgeIdentityRequest(entityType: $0.entityType, localId: $0.localID) }
        return try await offActor { workspace in
            try workspace.resolveIdentities(items: items).map {
                RustWorkspaceIdentityBinding(entityType: $0.entityType, localID: $0.localId, canonicalID: $0.canonicalId)
            }
        }
    }

    public func issues(limit: UInt32 = 200, after: String? = nil) async throws -> RustWorkspaceAnswer {
        try await offActor { workspace in Self.answer(try workspace.workspaceIssues(limit: limit, after: after)) }
    }

    public func records(_ requests: [RustWorkspaceRecordRequest]) async throws -> RustWorkspaceAnswer {
        let items = try requests.map {
            BridgeRecordRequest(entityType: $0.entityType,
                recordKey: try JSONSerialization.data(withJSONObject: $0.recordKey))
        }
        return try await offActor { workspace in Self.answer(try workspace.records(items: items)) }
    }

    public func syncStatus() async throws -> Data {
        try await offActor { workspace in try workspace.syncStatus() }
    }

    public func reverseIdentities(_ requests: [RustWorkspaceSourceIdentityRequest]) async throws -> [RustWorkspaceSourceIdentityBinding] {
        let items = requests.map { BridgeSourceIdentityRequest(entityType: $0.entityType, canonicalId: $0.canonicalID) }
        return try await offActor { workspace in
            try workspace.reverseIdentities(items: items).map {
                RustWorkspaceSourceIdentityBinding(entityType: $0.entityType, canonicalID: $0.canonicalId, sourceID: $0.sourceId)
            }
        }
    }

    public func loadReviewForm(_ key: String, now: Date) async throws -> RustWorkspaceReviewFormLoaded {
        let instant = RustInstant.format(now)
        return try await offActor { workspace in
            let result = try workspace.loadReviewForm(key: key, now: instant)
            let draft = try result.draft.map { form -> FormDraft in
                guard let date = RustInstant.parse(form.savedAt) else { throw RustBridgeError(code: "MALFORMED_DRAFT") }
                return FormDraft(text: form.text, savedAt: date)
            }
            guard let count = Int(result.liveCount), count >= 0 else { throw RustBridgeError(code: "MALFORMED_DRAFT_COUNT") }
            return RustWorkspaceReviewFormLoaded(sourceKey: result.sourceKey, draft: draft, liveCount: count,
                projectionGeneration: result.projectionGeneration)
        }
    }

    public func reviewFormCount(now: Date) async throws -> RustWorkspaceReviewFormCount {
        let instant = RustInstant.format(now)
        return try await offActor { workspace in try Self.formCount(workspace.reviewFormCount(now: instant)) }
    }

    public func saveReviewForm(_ key: String, sourceKey: String?, draft: FormDraft?, now: Date) async throws -> RustWorkspaceReviewFormCount {
        let form = draft.map { BridgeReviewForm(text: $0.text, savedAt: RustInstant.format($0.savedAt)) }
        let instant = RustInstant.format(now)
        return try await committing { workspace, operation in
            try Self.formCount(workspace.saveReviewForm(key: key, sourceKey: sourceKey, draft: form, now: instant, operation: operation))
        }
    }

    public func clearReviewFormsForTask(_ canonicalTaskID: String, now: Date) async throws -> RustWorkspaceReviewFormCount {
        let instant = RustInstant.format(now)
        return try await committing { workspace, operation in
            try Self.formCount(workspace.clearReviewFormsForTask(canonicalTaskId: canonicalTaskID, now: instant, operation: operation))
        }
    }

    public func pruneReviewForms(now: Date) async throws -> RustWorkspaceReviewFormCount {
        let instant = RustInstant.format(now)
        return try await committing { workspace, operation in
            try Self.formCount(workspace.pruneReviewForms(now: instant, operation: operation))
        }
    }

    private static func formCount(_ result: BridgeReviewFormCount) throws -> RustWorkspaceReviewFormCount {
        guard let count = Int(result.liveCount), count >= 0 else { throw RustBridgeError(code: "MALFORMED_DRAFT_COUNT") }
        return RustWorkspaceReviewFormCount(liveCount: count, projectionGeneration: result.projectionGeneration)
    }

    public func loadDraft(_ draftID: String) async throws -> RustWorkspaceDraft? {
        try await offActor { workspace in try workspace.loadDraft(draftId: draftID).map(RustWorkspaceDraft.init) }
    }

    public func saveDraft(_ draft: RustWorkspaceDraft) async throws {
        let draft = draft.bridged
        try await committing { workspace, operation in try workspace.saveDraft(draft: draft, operation: operation) }
    }

    public func deleteDraft(_ draftID: String) async throws {
        try await committing { workspace, operation in try workspace.deleteDraft(draftId: draftID, operation: operation) }
    }

    public func convertLegacyUnsent(_ entries: [RustWorkspaceLegacyConversion], context: RustWorkspaceContext)
        async throws -> RustWorkspaceExecution {
        let items = try Self.boundedLegacyConversions(entries)
        let context = context.bridged
        return try await durable { workspace, operation in
            try workspace.convertLegacyUnsent(items: items, context: context, operation: operation)
        }
    }

    /// The original migration context survives prefix commits and process death.
    public func beginLegacyConversion(context: RustWorkspaceContext, atomicGroup: Bool = false)
        async throws -> RustWorkspaceLegacyConversionPlan {
        let context = context.bridged
        return try await committing { workspace, operation in
            let plan = try workspace.beginLegacyConversion(context: context, atomicGroup: atomicGroup, operation: operation)
            guard let now = RustInstant.parse(plan.context.now) else { throw RustDomainError.malformedResult }
            return RustWorkspaceLegacyConversionPlan(token: plan.token,
                context: RustWorkspaceContext(now: now, timeZone: plan.context.timeZone,
                    actorID: plan.context.actorId, policy: plan.context.policy),
                sourceCount: plan.sourceCount, atomicGroup: plan.atomicGroup)
        }
    }

    public func legacyConversionPage(token: String, after: String? = nil) async throws -> RustWorkspaceLegacyConversionPage {
        try await offActor { workspace in
            let page = try workspace.legacyConversionPage(token: token, after: after)
            return RustWorkspaceLegacyConversionPage(items: page.items.map {
                RustWorkspaceLegacyUnsent(entryID: $0.entryId, idempotencyKey: $0.idempotencyKey,
                    issuedAt: $0.issuedAt, command: $0.command)
            }, pageToken: page.pageToken, nextAfter: page.nextAfter)
        }
    }

    public func convertLegacyConversionPage(_ entries: [RustWorkspaceLegacyConversion], token: String,
                                           pageToken: String, atomicStage: Bool)
        async throws -> RustWorkspaceLegacyConversionProgress {
        let items = try Self.boundedLegacyConversions(entries)
        return try await committing { workspace, operation in
            RustWorkspaceLegacyConversionProgress(try workspace.convertLegacyConversionPage(token: token,
                pageToken: pageToken, items: items, atomicStage: atomicStage, operation: operation))
        }
    }

    public func finalizeLegacyConversion(token: String) async throws -> RustWorkspaceLegacyConversionProgress {
        try await committing { workspace, operation in
            RustWorkspaceLegacyConversionProgress(try workspace.finalizeLegacyConversion(token: token, operation: operation))
        }
    }

    public func smartAddResolve(draft: Data) async throws -> RustWorkspaceAnswer {
        try await offActor { workspace in
            Self.answer(try workspace.smartAddResolve(draft: draft))
        }
    }

    /// Private content marks stay in the owned query cache and never become
    /// domain query inputs or durable runtime state.
    public func reviewContentStamps(key: Data, taskIDs: [String], projectIDs: [String])
        async throws -> RustWorkspaceAnswer {
        guard key.count <= 8 * 1024 * 1024 else { throw RustBridgeError(code: "TOO_MANY_BYTES", field: "key") }
        guard taskIDs.count <= 200, projectIDs.count <= 200,
              taskIDs.count + projectIDs.count <= 200 else { throw RustBridgeError(code: "TOO_MANY_ITEMS") }
        return try await offActor { workspace in
            Self.answer(try workspace.reviewContentStamps(key: key, taskIds: taskIDs, projectIds: projectIDs))
        }
    }

    public func smartAddPropose(draft: Data, minted: Data, expectedGeneration: String)
        async throws -> RustWorkspaceAnswer {
        try await offActor { workspace in
            Self.answer(try workspace.smartAddPropose(draft: draft, minted: minted, expectedGeneration: expectedGeneration))
        }
    }

    private static func answer(_ answer: BridgeWorkspaceAnswer) -> RustWorkspaceAnswer {
        switch answer {
        case .answered(let page):
            return .answered(RustWorkspacePage(projectionGeneration: page.projectionGeneration, result: page.result,
                                              collectionNextCursor: page.collectionNextCursor, taskFrames: page.taskFrames))
        case .refused(let refusal, let generation): return .refused(RustRefusal(refusal), projectionGeneration: generation)
        }
    }

    private static func boundedLegacyConversions(_ entries: [RustWorkspaceLegacyConversion]) throws -> [BridgeLegacyConversion] {
        guard entries.count <= 200 else { throw RustBridgeError(code: "TOO_MANY_ITEMS", field: "legacy_outbox") }
        let bytes = entries.reduce(0) { $0 + $1.command.payload.count + $1.command.preconditions.count
            + $1.command.admissionTokens.count + $1.command.dependsOn.reduce(0) { $0 + $1.utf8.count }
            + $1.entryID.utf8.count + $1.issuedAt.utf8.count + $1.command.commandID.utf8.count
            + $1.command.commandType.utf8.count + ($1.command.entityID?.utf8.count ?? 0) + 256 }
        guard bytes <= 8 * 1024 * 1024 else { throw RustBridgeError(code: "TOO_MANY_BYTES", field: "legacy_outbox") }
        return entries.map { BridgeLegacyConversion(entryId: $0.entryID, issuedAt: $0.issuedAt, command: $0.command.bridged) }
    }

    private func durable(_ work: @escaping @Sendable (BridgeWorkspace, BridgeOperation) throws -> BridgeExecution)
        async throws -> RustWorkspaceExecution {
        try await committing { workspace, operation in
            switch try work(workspace, operation) {
            case .saved(let results): return .saved(results.map(RustWorkspaceSaved.init))
            case .refused(let refusal, let failedCommandID): return .refused(RustRefusal(refusal), failedCommandID: failedCommandID)
            }
        }
    }

    private func committing<T: Sendable>(_ work: @escaping @Sendable (BridgeWorkspace, BridgeOperation) throws -> T)
        async throws -> T {
        let operation = BridgeOperation()
        let workspace = workspace
        return try await withTaskCancellationHandler {
            let outcome = await Task.detached(priority: .userInitiated) {
                () -> Result<T, RustBridgeError> in
                do { return .success(try work(workspace, operation)) }
                catch { return .failure(RustBridgeError(thrown: error)) }
            }.value
            return try outcome.get()
        } onCancel: { _ = operation.cancel() }
    }

    public func query(_ query: Data, inputs: Data, collectionLimit: UInt32 = 200,
                      collectionAfter: String? = nil) async throws -> RustWorkspaceAnswer {
        try await offActor { workspace in
            switch try workspace.query(query: query, inputs: inputs, collectionLimit: collectionLimit,
                                       collectionAfter: collectionAfter) {
            case .answered(let page):
                return .answered(RustWorkspacePage(projectionGeneration: page.projectionGeneration, result: page.result,
                                                  collectionNextCursor: page.collectionNextCursor, taskFrames: page.taskFrames))
            case .refused(let refusal, let generation): return .refused(RustRefusal(refusal), projectionGeneration: generation)
            }
        }
    }

    /// Bootstrap/diagnostic only. Ordinary lists use the bounded query method.
    public func snapshot() async throws -> RustWorkspaceSnapshot {
        try await offActor { workspace in
            let snapshot = try workspace.snapshot()
            return RustWorkspaceSnapshot(projectionGeneration: snapshot.projectionGeneration, records: snapshot.records,
                                         pending: snapshot.pending, openIssues: snapshot.openIssues)
        }
    }

    public func subscribe() async throws -> RustWorkspaceSubscription {
        try await offActor { RustWorkspaceSubscription(try $0.subscribe()) }
    }

    /// Always settles the handle, even when the caller's Task is cancelled.
    public func close() async throws {
        let workspace = workspace
        let outcome = await Task.detached { () -> Result<Void, RustBridgeError> in
            do { try workspace.close(); return .success(()) }
            catch { return .failure(RustBridgeError(thrown: error)) }
        }.value
        try outcome.get()
    }
}

public final class RustWorkspaceSubscription: Sendable {
    private let subscription: BridgeSubscription
    fileprivate init(_ subscription: BridgeSubscription) { self.subscription = subscription }

    public func cancel() { subscription.cancel() }

    /// No callback queue: callers consume one latest invalidation and requery.
    public func next(after token: String?, timeoutMilliseconds: UInt32 = 1_000)
        async throws -> RustWorkspaceInvalidation? {
        let subscription = subscription
        return try await withTaskCancellationHandler {
            let outcome = await Task.detached { () -> Result<RustWorkspaceInvalidation?, RustBridgeError> in
                do {
                    guard let value = try subscription.next(after: token, timeoutMs: timeoutMilliseconds) else {
                        return .success(nil)
                    }
                    return .success(RustWorkspaceInvalidation(projectionGeneration: value.projectionGeneration,
                        changedKinds: value.changedKinds, syncStatusChanged: value.syncStatusChanged,
                        issuesChanged: value.issuesChanged, pending: value.pending, openIssues: value.openIssues, token: value.token))
                } catch { return .failure(RustBridgeError(thrown: error)) }
            }.value
            if Task.isCancelled { throw RustBridgeError.cancelled }
            return try outcome.get()
        } onCancel: { subscription.cancel() }
    }
}
