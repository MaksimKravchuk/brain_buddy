import Foundation

// Voice brain dump (spec 031 on iPhone; the protocol is specs 002, 005 and 015):
// `backend/app/api/tasks.py` `/brain-dump-operations`, `backend/app/schemas/tasks.py`.
// Every route answers the whole operation. Unknown status and action words decode as
// `.unknown`, so a newer server never breaks the sheet. Descriptions print no transcript,
// title or audio: the operation is the person's speech.

/// `BrainDumpStatus`.
public enum BrainDumpStatus: Hashable, Sendable, Decodable {
    case recording, paused, sealing, fastProcessing, accurateTranscribing, reconciling
    case retryableError, terminalError, awaitingConfirmation, committing, completed, cancelled
    case unknown(String)

    public init(wireValue: String) {
        let known: [String: Self] = [
            "recording": .recording, "paused": .paused, "sealing": .sealing,
            "fast_processing": .fastProcessing, "accurate_transcribing": .accurateTranscribing,
            "reconciling": .reconciling, "retryable_error": .retryableError, "terminal_error": .terminalError,
            "awaiting_confirmation": .awaitingConfirmation, "committing": .committing,
            "completed": .completed, "cancelled": .cancelled,
        ]
        self = known[wireValue] ?? .unknown(wireValue)
    }

    public init(from decoder: any Decoder) throws {
        self.init(wireValue: try decoder.singleValueContainer().decode(String.self))
    }

    /// The server is still working: the client polls (`brainDumpStatusLabels.ts`).
    public var isProcessing: Bool {
        switch self {
        case .sealing, .fastProcessing, .accurateTranscribing, .reconciling, .committing, .retryableError: true
        default: false
        }
    }

    /// The web's words for the status (`frontend/src/features/brain-dump/brainDumpStatusLabels.ts`).
    public var label: String {
        switch self {
        case .recording: "Recording"
        case .paused: "Paused"
        case .sealing: "Sealing audio"
        case .fastProcessing: "Processing audio"
        case .accurateTranscribing: "Improving transcript"
        case .reconciling: "Reconciling tasks"
        case .committing: "Saving tasks"
        case .awaitingConfirmation: "Awaiting review"
        case .retryableError: "Needs attention"
        case .terminalError: "Could not be processed"
        case .completed: "Saved to Inbox"
        case .cancelled: "Discarded"
        case .unknown(let word): word
        }
    }
}

/// `BrainDumpRecoveryAction`, in the order the server lists them.
public enum BrainDumpRecoveryAction: Hashable, Sendable, Decodable {
    case retry, reviewProvisional, reconcilePreview, cancel
    case unknown(String)

    public init(from decoder: any Decoder) throws {
        let word = try decoder.singleValueContainer().decode(String.self)
        switch word {
        case "retry": self = .retry
        case "review_provisional": self = .reviewProvisional
        case "reconcile_preview": self = .reconcilePreview
        case "cancel": self = .cancel
        default: self = .unknown(word)
        }
    }
}

/// The commands of `POST /brain-dump-operations/{id}/{action}`.
public enum BrainDumpCommand: String, Hashable, Sendable, CaseIterable {
    case pause, resume, finish, cancel, commit, retry
    case reviewProvisional = "review_provisional"
    case reconcilePreview = "reconcile_preview"
    case withdrawConsent = "withdraw_consent"
    case deleteRawAudio = "delete_raw_audio"
}

/// `BrainDumpProvidersResponse`: the provider category each role must be consented to, or nil
/// when that role sends nothing out (recording needs a named `accurateSTT`).
public struct BrainDumpProvidersDTO: Hashable, Sendable, Decodable {
    public let accurateSTT: String?
    public let reconciler: String?

    public init(accurateSTT: String?, reconciler: String?) {
        self.accurateSTT = accurateSTT
        self.reconciler = reconciler
    }

    enum CodingKeys: String, CodingKey {
        case accurateSTT = "accurate_stt"
        case reconciler
    }
}

/// `BrainDumpConsentRequest`.
public struct BrainDumpConsent: Hashable, Sendable, Encodable {
    public var microphone: Bool
    public var externalProcessingAllowed: Bool
    public var provider: String?
    public var providers: [String]
    public var languageHints: [String]
    public var vocabulary: [String]

    public init(
        microphone: Bool = true, externalProcessingAllowed: Bool, provider: String?, providers: [String],
        languageHints: [String], vocabulary: [String] = []
    ) {
        self.microphone = microphone
        self.externalProcessingAllowed = externalProcessingAllowed
        self.provider = provider
        self.providers = providers
        self.languageHints = languageHints
        self.vocabulary = vocabulary
    }

    /// The consent the web sends for `providers`: the accurate STT provider, then the
    /// reconciler when it is named and different.
    public static func cloud(_ providers: BrainDumpProvidersDTO, languageHints: [String]) -> BrainDumpConsent {
        var named: [String] = []
        for provider in [providers.accurateSTT, providers.reconciler].compactMap({ $0 }) where !named.contains(provider) {
            named.append(provider)
        }
        return BrainDumpConsent(
            externalProcessingAllowed: true, provider: providers.accurateSTT, providers: named,
            languageHints: languageHints)
    }

    enum CodingKeys: String, CodingKey {
        case microphone, provider, providers, vocabulary
        case externalProcessingAllowed = "external_processing_allowed"
        case languageHints = "language_hints"
    }
}

/// One live-recognition result for `POST …/transcript`.
public struct BrainDumpSegmentInput: Hashable, Sendable, Encodable, CustomStringConvertible {
    public enum Stability: String, Hashable, Sendable, Encodable { case interim, stable }
    public var sequence: Int
    public var text: String
    public var stability: Stability

    public init(sequence: Int, text: String, stability: Stability) {
        self.sequence = sequence
        self.text = text
        self.stability = stability
    }

    public var description: String { "Segment \(sequence) (\(stability.rawValue), redacted)" }
}

/// `BrainDumpTranscriptSegmentResponse`, the fields a client shows.
public struct BrainDumpSegmentDTO: Hashable, Sendable, Decodable, CustomStringConvertible {
    public let id: String
    public let sequence: Int
    public let text: String
    public let stability: String
    public let providerRole: String
    public let supersedesSegmentIDs: [String]

    public var description: String { "Segment \(id) (redacted)" }

    enum CodingKeys: String, CodingKey {
        case id, sequence, text, stability
        case providerRole = "provider_role"
        case supersedesSegmentIDs = "supersedes_segment_ids"
    }

    public init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        id = try values.decode(String.self, forKey: .id)
        sequence = try values.decode(Int.self, forKey: .sequence)
        text = try values.decode(String.self, forKey: .text)
        stability = try values.decodeIfPresent(String.self, forKey: .stability) ?? "stable"
        providerRole = try values.decodeIfPresent(String.self, forKey: .providerRole) ?? "browser_preview"
        supersedesSegmentIDs = try values.decodeIfPresent([String].self, forKey: .supersedesSegmentIDs) ?? []
    }
}

/// `BrainDumpProposalConflictResponse`.
public struct BrainDumpConflictDTO: Hashable, Sendable, Decodable, CustomStringConvertible {
    public let field: String
    public let currentValue: String?
    public let suggestedValue: String?

    public var description: String { "Conflict on \(field) (redacted)" }

    enum CodingKeys: String, CodingKey {
        case field
        case currentValue = "current_value"
        case suggestedValue = "suggested_value"
    }
}

/// `BrainDumpProposalResponse`: one proposed step.
public struct BrainDumpProposalDTO: Hashable, Sendable, Decodable, CustomStringConvertible {
    public let id: String
    public let ordinal: Int
    public let title: String
    /// `BrainDumpProposalStatus` as sent (provisional, wording_changing, ready_to_review,
    /// user_edited, reconciled, conflicted).
    public let status: String
    public let sourceSegmentIDs: [String]
    public let conflicts: [BrainDumpConflictDTO]
    public let deleted: Bool
    public let userEdited: Bool
    public let revision: Int

    public var description: String { "Proposal \(id) #\(ordinal) (\(status), redacted)" }

    enum CodingKeys: String, CodingKey {
        case id, ordinal, title, status, conflicts, deleted, revision
        case sourceSegmentIDs = "source_segment_ids"
        case userEdited = "user_edited"
    }

    public init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        id = try values.decode(String.self, forKey: .id)
        ordinal = try values.decode(Int.self, forKey: .ordinal)
        title = try values.decode(String.self, forKey: .title)
        status = try values.decode(String.self, forKey: .status)
        sourceSegmentIDs = try values.decodeIfPresent([String].self, forKey: .sourceSegmentIDs) ?? []
        conflicts = try values.decodeIfPresent([BrainDumpConflictDTO].self, forKey: .conflicts) ?? []
        deleted = try values.decode(Bool.self, forKey: .deleted)
        userEdited = try values.decodeIfPresent(Bool.self, forKey: .userEdited) ?? false
        revision = try values.decode(Int.self, forKey: .revision)
    }
}

/// `BrainDumpAudioChunkResponse`: what the server holds of one uploaded chunk.
public struct BrainDumpAudioChunkDTO: Hashable, Sendable, Decodable {
    public let chunkNumber: Int
    public let sha256: String
    public let sizeBytes: Int

    public init(chunkNumber: Int, sha256: String, sizeBytes: Int) {
        self.chunkNumber = chunkNumber
        self.sha256 = sha256
        self.sizeBytes = sizeBytes
    }

    enum CodingKeys: String, CodingKey {
        case sha256
        case chunkNumber = "chunk_number"
        case sizeBytes = "size_bytes"
    }
}

/// `BrainDumpProviderRunResponse`, the fields that name a failed stage.
public struct BrainDumpProviderRunDTO: Hashable, Sendable, Decodable {
    /// `accurate_stt` or `reconciler`.
    public let role: String
    public let status: String
    public let error: String?
    public let errorCode: String?

    enum CodingKeys: String, CodingKey {
        case role, status, error
        case errorCode = "error_code"
    }
}

/// `BrainDumpOperationResponse`: one recording and everything proposed from it.
public struct BrainDumpOperationDTO: Hashable, Sendable, Decodable, CustomStringConvertible {
    public let id: String
    public let status: BrainDumpStatus
    public let externalProcessingAllowed: Bool
    public let segments: [BrainDumpSegmentDTO]
    public let proposals: [BrainDumpProposalDTO]
    public let audioChunks: [BrainDumpAudioChunkDTO]
    public let rawAudioPresent: Bool
    /// `none`, `provisional_only`, `accurate` or `conflicted`.
    public let reconciliationQuality: String
    public let committable: Bool
    public let availableRecoveryActions: [BrainDumpRecoveryAction]
    public let providerRuns: [BrainDumpProviderRunDTO]
    public let committedTaskIDs: [String]
    public let revision: Int

    public var description: String {
        "Brain dump \(id) r\(revision) (\(status.label), \(proposals.count) proposals, redacted)"
    }

    enum CodingKeys: String, CodingKey {
        case id, status, consent, segments, proposals, committable, revision
        case audioChunks = "audio_chunks"
        case rawAudioPresent = "raw_audio_present"
        case reconciliationQuality = "reconciliation_quality"
        case availableRecoveryActions = "available_recovery_actions"
        case providerRuns = "provider_runs"
        case committedTaskIDs = "committed_task_ids"
    }

    private struct Consent: Decodable {
        let externalProcessingAllowed: Bool
        enum CodingKeys: String, CodingKey { case externalProcessingAllowed = "external_processing_allowed" }
    }

    public init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        id = try values.decode(String.self, forKey: .id)
        status = try values.decode(BrainDumpStatus.self, forKey: .status)
        externalProcessingAllowed = try values.decode(Consent.self, forKey: .consent).externalProcessingAllowed
        segments = try values.decodeIfPresent([BrainDumpSegmentDTO].self, forKey: .segments) ?? []
        proposals = try values.decodeIfPresent([BrainDumpProposalDTO].self, forKey: .proposals) ?? []
        audioChunks = try values.decodeIfPresent([BrainDumpAudioChunkDTO].self, forKey: .audioChunks) ?? []
        rawAudioPresent = try values.decodeIfPresent(Bool.self, forKey: .rawAudioPresent) ?? false
        reconciliationQuality = try values.decodeIfPresent(String.self, forKey: .reconciliationQuality) ?? "none"
        committable = try values.decodeIfPresent(Bool.self, forKey: .committable) ?? false
        availableRecoveryActions =
            try values.decodeIfPresent([BrainDumpRecoveryAction].self, forKey: .availableRecoveryActions) ?? []
        providerRuns = try values.decodeIfPresent([BrainDumpProviderRunDTO].self, forKey: .providerRuns) ?? []
        committedTaskIDs = try values.decodeIfPresent([String].self, forKey: .committedTaskIDs) ?? []
        revision = try values.decode(Int.self, forKey: .revision)
    }
}

/// A change to one proposal (`BrainDumpProposalUpdateRequest`): exactly one of these per request.
public enum BrainDumpProposalChange: Hashable, Sendable {
    case title(String)
    case delete
    /// `keep` keeps the person's value, `accept` takes the suggestion.
    case resolveConflict(keepMine: Bool)
}

/// The seal's manifest hash (`frontend/src/features/brain-dump/BrainDumpRoute.tsx`, the server's
/// `MANIFEST_CONFLICT` check): the server's chunks numbered below `expectedChunks`, ascending, as
/// compact JSON objects with `chunk_number`, `sha256`, `size_bytes` in that order; SHA-256 of
/// the UTF-8 bytes in lowercase hex.
public enum BrainDumpManifest {
    public static func json(_ chunks: [BrainDumpAudioChunkDTO], expectedChunks: Int) -> String {
        let entries = chunks
            .filter { $0.chunkNumber < expectedChunks }
            .sorted { $0.chunkNumber < $1.chunkNumber }
            .map { #"{"chunk_number":\#($0.chunkNumber),"sha256":"\#($0.sha256)","size_bytes":\#($0.sizeBytes)}"# }
        return "[" + entries.joined(separator: ",") + "]"
    }

    public static func hash(_ chunks: [BrainDumpAudioChunkDTO], expectedChunks: Int) -> String {
        SHA256Digest.hex(Data(json(chunks, expectedChunks: expectedChunks).utf8))
    }
}

private struct BrainDumpStartBody: Encodable { var consent: BrainDumpConsent }
private struct BrainDumpTranscriptBody: Encodable { var segments: [BrainDumpSegmentInput] }

private struct BrainDumpSealBody: Encodable {
    var expectedRevision: Int
    var expectedChunks: Int
    var manifestHash: String
    enum CodingKeys: String, CodingKey {
        case expectedRevision = "expected_revision"
        case expectedChunks = "expected_chunks"
        case manifestHash = "manifest_hash"
    }
}

private struct BrainDumpProposalBody: Encodable {
    var change: BrainDumpProposalChange
    var expectedRevision: Int

    enum CodingKeys: String, CodingKey {
        case title, deleted
        case conflictResolution = "conflict_resolution"
        case expectedRevision = "expected_revision"
    }

    func encode(to encoder: any Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        switch change {
        case .title(let title): try values.encode(title, forKey: .title)
        case .delete: try values.encode(true, forKey: .deleted)
        case .resolveConflict(let keepMine): try values.encode(keepMine ? "keep" : "accept", forKey: .conflictResolution)
        }
        try values.encode(expectedRevision, forKey: .expectedRevision)
    }
}

extension BrainBuddyAPIClient {
    /// `GET /brain-dump-providers`; 404 when the account's `voice_brain_dump` flag is off.
    public func brainDumpProviders() async throws(APIError) -> BrainDumpProvidersDTO {
        try await get(["brain-dump-providers"])
    }

    /// `POST /brain-dump-operations {consent}` → 201, an operation in `recording`.
    public func startBrainDump(
        consent: BrainDumpConsent, idempotencyKey: UUID
    ) async throws(APIError) -> BrainDumpOperationDTO {
        try await mutate(.post, ["brain-dump-operations"], BrainDumpStartBody(consent: consent), key: idempotencyKey)
    }

    /// `GET /brain-dump-operations/{id}`.
    public func brainDump(id: String) async throws(APIError) -> BrainDumpOperationDTO {
        try await get(["brain-dump-operations", id])
    }

    /// `POST /brain-dump-operations/{id}/transcript {segments}`: live-recognition text, a readout
    /// and recovery source that never becomes a proposal by itself.
    public func appendBrainDumpTranscript(
        id: String, segments: [BrainDumpSegmentInput], idempotencyKey: UUID
    ) async throws(APIError) -> BrainDumpOperationDTO {
        try await mutate(
            .post, ["brain-dump-operations", id, "transcript"], BrainDumpTranscriptBody(segments: segments),
            key: idempotencyKey)
    }

    /// `PUT /brain-dump-operations/{id}/audio/{chunk}`: raw bytes with their media type and
    /// `X-Content-SHA256`. No Idempotency-Key: the same bytes again are answered unchanged,
    /// different bytes are `409 CHUNK_CONFLICT`.
    public func uploadBrainDumpAudio(
        id: String, chunkNumber: Int, audio: Data, mimeType: String
    ) async throws(APIError) -> BrainDumpOperationDTO {
        let endpoint = Endpoint(
            .put, ["brain-dump-operations", id, "audio", String(chunkNumber)], body: audio,
            contentType: mimeType, headers: ["X-Content-SHA256": SHA256Digest.hex(audio)])
        return try decode(try await exchange(endpoint))
    }

    /// `POST /brain-dump-operations/{id}/seal`; the hash is `BrainDumpManifest.hash`.
    public func sealBrainDump(
        id: String, expectedRevision: Int, expectedChunks: Int, manifestHash: String, idempotencyKey: UUID
    ) async throws(APIError) -> BrainDumpOperationDTO {
        let body = BrainDumpSealBody(
            expectedRevision: expectedRevision, expectedChunks: expectedChunks, manifestHash: manifestHash)
        return try await mutate(.post, ["brain-dump-operations", id, "seal"], body, key: idempotencyKey)
    }

    /// `PATCH /brain-dump-operations/{id}/proposals/{proposal}`.
    public func updateBrainDumpProposal(
        id: String, proposalID: String, change: BrainDumpProposalChange, expectedRevision: Int,
        idempotencyKey: UUID
    ) async throws(APIError) -> BrainDumpOperationDTO {
        let body = BrainDumpProposalBody(change: change, expectedRevision: expectedRevision)
        return try await mutate(.patch, ["brain-dump-operations", id, "proposals", proposalID], body, key: idempotencyKey)
    }

    /// `POST /brain-dump-operations/{id}/{command} {expected_revision}`.
    public func brainDumpCommand(
        id: String, _ command: BrainDumpCommand, expectedRevision: Int, idempotencyKey: UUID
    ) async throws(APIError) -> BrainDumpOperationDTO {
        try await mutate(
            .post, ["brain-dump-operations", id, command.rawValue], ExpectedRevisionBody(expectedRevision: expectedRevision),
            key: idempotencyKey)
    }
}
