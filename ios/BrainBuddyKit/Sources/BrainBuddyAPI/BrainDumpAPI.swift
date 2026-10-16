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

/// SHA-256 (FIPS 180-4) for audio chunk and manifest hashes. Foundation has no digest on Linux and
/// the kit takes no crypto dependency; these hashes are integrity checks, not secrets.
public enum SHA256Digest {
    private static let k: [UInt32] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
        0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
        0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
        0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
        0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
        0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
        0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
    ]

    public static func digest(_ data: Data) -> [UInt8] {
        var h: [UInt32] = [
            0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
        ]
        var message = [UInt8](data)
        let bitLength = UInt64(message.count) &* 8
        message.append(0x80)
        while message.count % 64 != 56 { message.append(0) }
        for shift in stride(from: 56, through: 0, by: -8) { message.append(UInt8(truncatingIfNeeded: bitLength >> UInt64(shift))) }
        var w = [UInt32](repeating: 0, count: 64)
        for chunk in stride(from: 0, to: message.count, by: 64) {
            for i in 0..<16 {
                let b = chunk + i * 4
                w[i] = UInt32(message[b]) << 24 | UInt32(message[b + 1]) << 16 | UInt32(message[b + 2]) << 8 | UInt32(message[b + 3])
            }
            for i in 16..<64 {
                let s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >> 3)
                let s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >> 10)
                w[i] = w[i - 16] &+ s0 &+ w[i - 7] &+ s1
            }
            var (a, b, c, d, e, f, g, hh) = (h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7])
            for i in 0..<64 {
                let s1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)
                let choice = (e & f) ^ (~e & g)
                let t1 = hh &+ s1 &+ choice &+ k[i] &+ w[i]
                let s0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)
                let majority = (a & b) ^ (a & c) ^ (b & c)
                let t2 = s0 &+ majority
                hh = g; g = f; f = e; e = d &+ t1
                d = c; c = b; b = a; a = t1 &+ t2
            }
            h[0] = h[0] &+ a; h[1] = h[1] &+ b; h[2] = h[2] &+ c; h[3] = h[3] &+ d
            h[4] = h[4] &+ e; h[5] = h[5] &+ f; h[6] = h[6] &+ g; h[7] = h[7] &+ hh
        }
        return h.flatMap { word in (0..<4).map { UInt8(truncatingIfNeeded: word >> UInt32(24 - $0 * 8)) } }
    }

    public static func hex(_ data: Data) -> String {
        digest(data).map { byte in
            let text = String(byte, radix: 16)
            return byte < 16 ? "0" + text : text
        }.joined()
    }

    private static func rotr(_ value: UInt32, _ amount: UInt32) -> UInt32 {
        (value >> amount) | (value << (32 - amount))
    }
}
