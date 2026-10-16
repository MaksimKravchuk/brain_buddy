import Foundation
import Testing

@testable import BrainBuddyAPI

/// Fixtures are `BrainDumpOperationResponse` field for field (`backend/app/schemas/tasks.py`).
private enum DumpFixture {
    static let proposal =
        #"{"id":"prop_1","ordinal":1,"title":"Call Sam about the van","status":"reconciled","source_segment_ids":["seg_1"],"predecessor_ids":[],"successor_ids":[],"locked_fields":[],"conflicts":[{"field":"title","current_value":"Call Sam","suggested_value":"Call Sam about the van","producer":"reconciler","source_segment_ids":[]}],"deleted":false,"user_edited":false,"revision":2}"#

    static func operation(status: String = "awaiting_confirmation", revision: Int = 5, actions: String = "[]") -> String {
        #"""
        {"id":"bdo_1","owner_id":"user_1","kind":"voice_brain_dump","status":"\#(status)",\#
        "consent":{"microphone":true,"external_processing_allowed":true,"provider":"openai","providers":["openai"],\#
        "language_hints":["ru","en"],"vocabulary":[],"recorded_at":"2026-10-16T09:00:00Z"},\#
        "segments":[{"id":"seg_1","sequence":1,"text":"the garage is a mess","content_sha256":null,"language":"en",\#
        "confidence":null,"stability":"stable","start_ms":0,"end_ms":1,"provider_role":"accurate","provider":"openai",\#
        "model":null,"supersedes_segment_ids":[],"created_at":"2026-10-16T09:00:01Z"}],\#
        "proposals":[\#(proposal)],"media_ref":null,\#
        "audio_chunks":[{"chunk_number":0,"sha256":"\#(String(repeating: "a", count: 64))","size_bytes":1234}],\#
        "sealed_manifest_hash":null,"raw_audio_expires_at":null,"raw_audio_present":true,\#
        "working_artifacts_expires_at":null,"reconciliation_quality":"accurate","committable":true,\#
        "available_recovery_actions":\#(actions),\#
        "provider_runs":[{"id":"run_1","role":"reconciler","status":"terminal_error","checkpoint":"sealed","attempt":1,\#
        "recovery_count":0,"error":"The provider timed out.","error_code":"RECONCILER_TIMEOUT","provider":"openai",\#
        "model":null,"template_version":null,"estimated_cost_usd":0.0,"reserved_cost_usd":0.0,"consumed_cost_usd":0.0}],\#
        "proposal_patches":[],"action_receipts":[],"status_history":["recording"],"committed_task_ids":["task_1"],\#
        "created_at":"2026-10-16T09:00:00Z","updated_at":"2026-10-16T09:00:02Z","revision":\#(revision)}
        """#
    }
}

@Suite("031 brain dump API")
struct BrainDumpAPITests {
    private func client(_ steps: [ScriptedTransport.Step]) -> (BrainBuddyAPIClient, ScriptedTransport) {
        let transport = ScriptedTransport(steps)
        return (Fixture.client(transport, store: Fixture.signedInStore()), transport)
    }

    private func json(_ request: HTTPRequest?) throws -> [String: Any] {
        let body = try #require(request?.body)
        return try #require(try JSONSerialization.jsonObject(with: body) as? [String: Any])
    }

    // MARK: digests

    @Test("031-FR-005 SHA-256 matches the FIPS 180-4 test vectors")
    func sha256Vectors_031_FR_005() {
        #expect(SHA256Digest.hex(Data()) == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
        #expect(SHA256Digest.hex(Data("abc".utf8)) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        let long = Data("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq".utf8)
        #expect(SHA256Digest.hex(long) == "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1")
        #expect(SHA256Digest.hex(Data(repeating: 0x61, count: 1_000_000))
            == "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0")
    }

    @Test("031-FR-005 the manifest keeps chunks below the count, ascending, in the web's compact JSON")
    func manifestHash_031_FR_005() {
        let chunks = [
            BrainDumpAudioChunkDTO(chunkNumber: 1, sha256: "bb", sizeBytes: 20),
            BrainDumpAudioChunkDTO(chunkNumber: 0, sha256: "aa", sizeBytes: 10),
            BrainDumpAudioChunkDTO(chunkNumber: 2, sha256: "cc", sizeBytes: 30),
        ]
        let text = BrainDumpManifest.json(chunks, expectedChunks: 2)
        #expect(text == #"[{"chunk_number":0,"sha256":"aa","size_bytes":10},{"chunk_number":1,"sha256":"bb","size_bytes":20}]"#)
        #expect(BrainDumpManifest.hash(chunks, expectedChunks: 2) == SHA256Digest.hex(Data(text.utf8)))
        #expect(BrainDumpManifest.json([], expectedChunks: 0) == "[]")
    }

    // MARK: decoding

    @Test("031-FR-008 the operation decodes its status, proposals, conflicts, chunks and recovery actions")
    func decodesOperation_031_FR_008() throws {
        let operation = try BrainBuddyAPI.makeDecoder().decode(
            BrainDumpOperationDTO.self,
            from: Data(DumpFixture.operation(actions: #"["retry","review_provisional","reconcile_preview","cancel","later"]"#).utf8))
        #expect(operation.status == .awaitingConfirmation)
        #expect(operation.externalProcessingAllowed)
        #expect(operation.committable)
        #expect(operation.revision == 5)
        #expect(operation.reconciliationQuality == "accurate")
        #expect(operation.proposals.first?.conflicts.first?.suggestedValue == "Call Sam about the van")
        #expect(operation.audioChunks == [BrainDumpAudioChunkDTO(chunkNumber: 0, sha256: String(repeating: "a", count: 64), sizeBytes: 1234)])
        #expect(operation.availableRecoveryActions == [.retry, .reviewProvisional, .reconcilePreview, .cancel, .unknown("later")])
        #expect(operation.providerRuns.first?.role == "reconciler")
        #expect(operation.committedTaskIDs == ["task_1"])
        #expect(!operation.description.contains("garage"))
        #expect(!operation.description.contains("Sam"))
    }

    @Test("031-FR-007 every status reads as the web's label and only the server's working statuses poll")
    func statusLabels_031_FR_007() {
        let cases: [(String, String, Bool)] = [
            ("recording", "Recording", false), ("paused", "Paused", false), ("sealing", "Sealing audio", true),
            ("fast_processing", "Processing audio", true), ("accurate_transcribing", "Improving transcript", true),
            ("reconciling", "Reconciling tasks", true), ("committing", "Saving tasks", true),
            ("retryable_error", "Needs attention", true), ("terminal_error", "Could not be processed", false),
            ("awaiting_confirmation", "Awaiting review", false), ("completed", "Saved to Inbox", false),
            ("cancelled", "Discarded", false),
        ]
        for (wire, label, polls) in cases {
            let status = BrainDumpStatus(wireValue: wire)
            #expect(status.label == label, "\(wire)")
            #expect(status.isProcessing == polls, "\(wire)")
        }
        #expect(BrainDumpStatus(wireValue: "archived") == .unknown("archived"))
    }

    // MARK: requests

    @Test("031-FR-003 providers are read from the gated route and a flag-off 404 is not found")
    func providers_031_FR_003() async throws {
        let (api, transport) = client([
            Fixture.json(200, #"{"accurate_stt":"openai","reconciler":null}"#),
            Fixture.json(404, #"{"message":"Voice brain dump is not available."}"#),
        ])
        let providers = try await api.brainDumpProviders()
        #expect(providers == BrainDumpProvidersDTO(accurateSTT: "openai", reconciler: nil))
        #expect(transport.lastRequest?.url.absoluteString == "https://api.example.test/api/brain-dump-providers")
        await #expect(throws: APIError.self) { try await api.brainDumpProviders() }
    }

    @Test("031-FR-004 start sends the cloud consent with both named providers once and an Idempotency-Key")
    func start_031_FR_004() async throws {
        let (api, transport) = client([Fixture.json(201, DumpFixture.operation(status: "recording", revision: 1))])
        let consent = BrainDumpConsent.cloud(
            BrainDumpProvidersDTO(accurateSTT: "openai", reconciler: "openai"), languageHints: ["ru", "en"])
        let operation = try await api.startBrainDump(consent: consent, idempotencyKey: Fixture.key)
        #expect(operation.status == .recording)
        let request = try #require(transport.lastRequest)
        #expect(request.method == .post)
        #expect(request.url.path.hasSuffix("/api/brain-dump-operations"))
        #expect(request.headers["Idempotency-Key"] == Fixture.keyHeader)
        let body = try json(request)
        let sent = try #require(body["consent"] as? [String: Any])
        #expect(sent["microphone"] as? Bool == true)
        #expect(sent["external_processing_allowed"] as? Bool == true)
        #expect(sent["provider"] as? String == "openai")
        #expect(sent["providers"] as? [String] == ["openai"])
        #expect(sent["language_hints"] as? [String] == ["ru", "en"])
        #expect(sent["vocabulary"] as? [String] == [])
    }

    @Test("031-FR-005 audio goes up as raw bytes with its media type and SHA-256, without an Idempotency-Key")
    func uploadAudio_031_FR_005() async throws {
        let (api, transport) = client([Fixture.json(200, DumpFixture.operation(status: "recording"))])
        let audio = Data([0x00, 0x01, 0x02, 0x03])
        _ = try await api.uploadBrainDumpAudio(id: "bdo_1", chunkNumber: 0, audio: audio, mimeType: "audio/mp4")
        let request = try #require(transport.lastRequest)
        #expect(request.method == .put)
        #expect(request.url.path.hasSuffix("/api/brain-dump-operations/bdo_1/audio/0"))
        #expect(request.headers["Content-Type"] == "audio/mp4")
        #expect(request.headers["X-Content-SHA256"] == SHA256Digest.hex(audio))
        #expect(request.headers["Idempotency-Key"] == nil)
        #expect(request.body == audio)
    }

    @Test("031-FR-006 live segments carry their sequence and stability")
    func transcript_031_FR_006() async throws {
        let (api, transport) = client([Fixture.json(200, DumpFixture.operation(status: "recording"))])
        _ = try await api.appendBrainDumpTranscript(
            id: "bdo_1", segments: [BrainDumpSegmentInput(sequence: 3, text: "the garage", stability: .interim)],
            idempotencyKey: Fixture.key)
        let request = try #require(transport.lastRequest)
        #expect(request.url.path.hasSuffix("/brain-dump-operations/bdo_1/transcript"))
        let segments = try #require(try json(request)["segments"] as? [[String: Any]])
        #expect(segments.count == 1)
        #expect(segments.first?["sequence"] as? Int == 3)
        #expect(segments.first?["text"] as? String == "the garage")
        #expect(segments.first?["stability"] as? String == "interim")
        #expect(!BrainDumpSegmentInput(sequence: 3, text: "the garage", stability: .stable).description.contains("garage"))
    }

    @Test("031-FR-005 seal names the revision, the chunk count and the manifest hash")
    func seal_031_FR_005() async throws {
        let (api, transport) = client([Fixture.json(200, DumpFixture.operation(status: "sealing"))])
        let hash = String(repeating: "f", count: 64)
        _ = try await api.sealBrainDump(id: "bdo_1", expectedRevision: 4, expectedChunks: 1, manifestHash: hash, idempotencyKey: Fixture.key)
        let request = try #require(transport.lastRequest)
        #expect(request.url.path.hasSuffix("/brain-dump-operations/bdo_1/seal"))
        let body = try json(request)
        #expect(body["expected_revision"] as? Int == 4)
        #expect(body["expected_chunks"] as? Int == 1)
        #expect(body["manifest_hash"] as? String == hash)
    }

    @Test("031-FR-008 a proposal change sends exactly one field and the revision")
    func proposalChanges_031_FR_008() async throws {
        let (api, transport) = client(Array(repeating: Fixture.json(200, DumpFixture.operation()), count: 4))
        let changes: [(BrainDumpProposalChange, String, String?)] = [
            (.title("Call Sam"), "title", "Call Sam"), (.delete, "deleted", nil),
            (.resolveConflict(keepMine: true), "conflict_resolution", "keep"),
            (.resolveConflict(keepMine: false), "conflict_resolution", "accept"),
        ]
        for (change, key, text) in changes {
            _ = try await api.updateBrainDumpProposal(
                id: "bdo_1", proposalID: "prop_1", change: change, expectedRevision: 5, idempotencyKey: Fixture.key)
            let request = try #require(transport.lastRequest)
            #expect(request.method == .patch)
            #expect(request.url.path.hasSuffix("/brain-dump-operations/bdo_1/proposals/prop_1"))
            let body = try json(request)
            #expect(Set(body.keys) == [key, "expected_revision"])
            #expect(body["expected_revision"] as? Int == 5)
            if let text {
                #expect(body[key] as? String == text)
            } else {
                #expect(body[key] as? Bool == true)
            }
        }
    }

    @Test("031-FR-013 commands post the revision to their own path")
    func commands_031_FR_013() async throws {
        let (api, transport) = client(Array(repeating: Fixture.json(200, DumpFixture.operation()), count: BrainDumpCommand.allCases.count))
        for command in BrainDumpCommand.allCases {
            _ = try await api.brainDumpCommand(id: "bdo_1", command, expectedRevision: 7, idempotencyKey: Fixture.key)
            let request = try #require(transport.lastRequest)
            #expect(request.method == .post)
            #expect(request.url.path.hasSuffix("/brain-dump-operations/bdo_1/\(command.rawValue)"))
            #expect(try json(request)["expected_revision"] as? Int == 7)
            #expect(request.headers["Idempotency-Key"] == Fixture.keyHeader)
        }
    }

    @Test("031-FR-015 a stale revision is a 409 carrying the server's message and reference")
    func staleRevision_031_FR_015() async throws {
        let (api, _) = client([
            Fixture.json(409, #"{"message":"Brain dump 'bdo_1' has newer changes; reload before saving.","detail":{"resource":"Brain dump","id":"bdo_1"},"reference_id":"ref-1"}"#)
        ])
        do {
            _ = try await api.brainDumpCommand(id: "bdo_1", .commit, expectedRevision: 1, idempotencyKey: Fixture.key)
            Issue.record("expected a conflict")
        } catch {
            #expect(error.message.contains("newer changes"))
        }
    }
}
