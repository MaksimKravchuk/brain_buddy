import BrainBuddyCore
import Foundation
import Testing

@testable import BrainBuddyAPI

/// The weekly review's wire shapes against the golden
/// `review_wire_fixtures.json` (a byte-identical copy of
/// `backend/tests/fixtures/review_wire_fixtures.json`; tasks.md T055).
@Suite("Review wire shapes (spec 020)")
struct ReviewWireTests {
    struct Entry: Sendable, CustomTestStringConvertible {
        var id: String
        var model: String
        var kind: String
        var valid: Bool
        var body: Data
        var keys: Set<String>

        var testDescription: String { "\(id) \(model)" }
    }

    static let entries: [Entry] = {
        guard let url = Bundle.module.url(forResource: "review_wire_fixtures", withExtension: "json", subdirectory: "Resources"),
            let data = try? Data(contentsOf: url),
            let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let entries = root["entries"] as? [[String: Any]]
        else { fatalError("Missing or unreadable test resource Resources/review_wire_fixtures.json") }
        return entries.compactMap { entry in
            guard let id = entry["id"] as? String, let model = entry["model"] as? String,
                let kind = entry["kind"] as? String, let valid = entry["valid"] as? Bool, let body = entry["body"],
                let encoded = try? JSONSerialization.data(withJSONObject: body, options: [.sortedKeys])
            else { return nil }
            let keys = (body as? [String: Any]).map { Set($0.filter { !($0.value is NSNull) }.keys) } ?? []
            return Entry(id: id, model: model, kind: kind, valid: valid, body: encoded, keys: keys)
        }
    }()

    /// Response models the device decodes (the navigator's are PR-08's client,
    /// decoded here too since the DTO exists).
    static let responses = entries.filter { $0.kind == "response" && $0.valid && $0.model != "ErrorResponse" }
    /// Request models the device sends (the navigator suggestion request is PR-08's).
    static let requests = entries.filter { $0.kind == "request" && $0.valid && $0.model != "NavigatorSuggestionRequest" }

    private let decoder = BrainBuddyAPI.makeDecoder()
    private let encoder = BrainBuddyAPI.makeEncoder()

    // MARK: - Responses

    @Test("020-FR-011 every valid response fixture decodes into its DTO", arguments: responses)
    func decodesResponse(_ entry: Entry) throws {
        switch entry.model {
        case "TaskResponse": _ = try decoder.decode(TaskDTO.self, from: entry.body)
        case "DecisionResponse": _ = try decoder.decode(DecisionResponseDTO.self, from: entry.body)
        case "UndoDecisionResponse": _ = try decoder.decode(UndoDecisionResponseDTO.self, from: entry.body)
        case "AutoParkResponse": _ = try decoder.decode(AutoParkResponseDTO.self, from: entry.body)
        case "ReviewStateResponse": _ = try decoder.decode(ReviewStateDTO.self, from: entry.body)
        case "ReviewSettingsResponse": _ = try decoder.decode(ReviewSettingsDTO.self, from: entry.body)
        case "SessionResponse": _ = try decoder.decode(SessionDTO.self, from: entry.body)
        case "QueueResponse": _ = try decoder.decode(QueueResponseDTO.self, from: entry.body)
        case "BulkReleaseResponse": _ = try decoder.decode(BulkReleaseResponseDTO.self, from: entry.body)
        case "BulkReleaseUndoResponse": _ = try decoder.decode(BulkReleaseUndoResponseDTO.self, from: entry.body)
        case "NavigatorStatusResponse": _ = try decoder.decode(NavigatorStatusDTO.self, from: entry.body)
        case "NavigatorSuggestionResponse": _ = try decoder.decode(NavigatorSuggestionResponseDTO.self, from: entry.body)
        default: Issue.record("No DTO mapped for \(entry.model)")
        }
    }

    @Test("020-FR-001 020-FR-012 TaskDTO carries the formulation and park marker, and decodes a body without them")
    func taskFormulationAndPark() throws {
        let running = try decoder.decode(TaskDTO.self, from: Self.entry("W-002").body)
        #expect(running.formulation?.id == "form_9d2a6c1e-4b7f-4e83-a0d5-7f1b3c8e2a64")
        #expect(running.formulation?.consecutiveStalled == 1)
        #expect(running.parked == nil)
        let parked = try decoder.decode(TaskDTO.self, from: Self.entry("W-003").body)
        #expect(parked.formulation == nil)
        #expect(parked.parked?.formulationID == "form_1c4f7a2e-9b3d-4f60-8a15-2e7c9d0b6f43")
        // A pre-020 body has neither key at all (decodeIfPresent).
        var object = try #require(try JSONSerialization.jsonObject(with: Self.entry("W-001").body) as? [String: Any])
        object["formulation"] = nil
        object["parked"] = nil
        let legacy = try decoder.decode(TaskDTO.self, from: JSONSerialization.data(withJSONObject: object))
        #expect(legacy.formulation == nil && legacy.parked == nil)
    }

    @Test("020-FR-016 020-FR-051 the review state carries activation, the open session and the server clock")
    func reviewState() throws {
        let state = try decoder.decode(ReviewStateDTO.self, from: Self.entry("W-030").body)
        #expect(state.settings.settings.activatedAt != nil)
        #expect(state.openSession?.id == "review_3e8f1a6c-5d2b-4c97-b04e-9a7d2f6c1e85")
        #expect(state.unseenParks.map(\.taskID) == ["task_7e1a3c5b9d2f"])
        #expect(state.counts.asksForDecision == 4)
        let fresh = try decoder.decode(ReviewStateDTO.self, from: Self.entry("W-031").body)
        #expect(fresh.settings.settings.activatedAt == nil && !fresh.explainerSeen)
    }

    // MARK: - Requests

    @Test("020-FR-011 every valid request fixture round-trips through its body with the same keys", arguments: requests)
    func requestRoundTrip(_ entry: Entry) throws {
        switch entry.model {
        case "DecisionRequest": try roundTrip(DecisionRequestBody.self, entry)
        case "UndoDecisionRequest": try roundTrip(UndoDecisionBody.self, entry)
        case "AutoParkRequest": try roundTrip(AutoParkBody.self, entry)
        case "ExplainerAcknowledgeRequest": try roundTrip(ExplainerAcknowledgeBody.self, entry)
        case "ReviewSettingsUpdateRequest": try roundTrip(ReviewSettingsUpdateBody.self, entry)
        case "ParkAcknowledgeRequest": try roundTrip(ParkAcknowledgeBody.self, entry)
        case "SessionStartRequest": try roundTrip(SessionStartBody.self, entry)
        case "SessionProgressRequest": try roundTrip(SessionProgressBody.self, entry)
        case "SessionFinishRequest": try roundTrip(SessionFinishBody.self, entry)
        case "BulkReleaseRequest": try roundTrip(BulkReleaseBody.self, entry)
        case "NavigatorConsentGrantRequest": try roundTrip(NavigatorConsentGrantBody.self, entry)
        default: Issue.record("No body mapped for \(entry.model)")
        }
    }

    private func roundTrip<Body: Codable & Equatable>(_ type: Body.Type, _ entry: Entry) throws {
        let body = try decoder.decode(Body.self, from: entry.body)
        let encoded = try encoder.encode(body)
        #expect(try decoder.decode(Body.self, from: encoded) == body, "\(entry.id) changes on a round trip")
        let object = try #require(try JSONSerialization.jsonObject(with: encoded) as? [String: Any])
        #expect(entry.keys.isSubset(of: object.keys), "\(entry.id): a fixture key is not sent")
        // The device always sends two fields the server would default:
        // `ai_use: "none"` and `skip_steps: []`.
        for extra in Set(object.keys).subtracting(entry.keys) {
            switch extra {
            case "ai_use": #expect(object[extra] as? String == "none", "\(entry.id)")
            case "skip_steps": #expect((object[extra] as? [Any])?.isEmpty == true, "\(entry.id)")
            default: Issue.record("\(entry.id): sends \(extra), which the fixture leaves out")
            }
        }
    }

    @Test("020-FR-011 a decision from iOS sends decision_id, new_formulation_id and follow_up_task_id")
    func decisionIDs() throws {
        let body = DecisionRequestBody(
            decisionID: "decision_0e4b7c2a-6f19-4d38-a5c1-8b2e9d7f3a60", type: .followUp, expectedRevision: 2,
            title: "Ask Ann about the quote", newFormulationID: "form_5b8e2d7a-3c16-4f94-9e0b-6a1d4c7f2e85",
            followUpTaskID: "task_2f6b9d1c-7e4a-4c25-b8f0-3a9e6d2c7b18"
        )
        let object = try #require(try JSONSerialization.jsonObject(with: encoder.encode(body)) as? [String: Any])
        #expect(object["decision_id"] as? String == "decision_0e4b7c2a-6f19-4d38-a5c1-8b2e9d7f3a60")
        #expect(object["new_formulation_id"] as? String == "form_5b8e2d7a-3c16-4f94-9e0b-6a1d4c7f2e85")
        #expect(object["follow_up_task_id"] as? String == "task_2f6b9d1c-7e4a-4c25-b8f0-3a9e6d2c7b18")
        #expect(try decoder.decode(DecisionRequestBody.self, from: Self.entry("W-013").body) == body)
    }

    @Test("020-FR-001 task writes that start a formulation send new_formulation_id, only into Next")
    func newFormulationIDOnTaskWrites() throws {
        let id = FormulationID("form_9d2a6c1e-4b7f-4e83-a0d5-7f1b3c8e2a64")
        let next = TaskCreateBody(
            .init(taskID: "t1", title: "Call Bob", list: .next, newFormulationID: id), projectServerID: { $0.rawValue },
            tagServerID: { $0.rawValue }
        )
        let inbox = TaskCreateBody(
            .init(taskID: "t2", title: "Idea", list: .inbox, newFormulationID: id), projectServerID: { $0.rawValue },
            tagServerID: { $0.rawValue }
        )
        let move = TaskTransitionBody(
            .init(taskID: "t1", action: .move, toList: .next, newFormulationID: id), expectedRevision: 3
        )
        #expect(try keys(next).contains("new_formulation_id"))
        #expect(try !keys(inbox).contains("new_formulation_id"))
        #expect(try keys(move).contains("new_formulation_id"))
    }

    private func keys(_ value: some Encodable) throws -> Set<String> {
        Set(try #require(try JSONSerialization.jsonObject(with: encoder.encode(value)) as? [String: Any]).keys)
    }

    @Test("020-FR-001 client ids are <prefix>_<lowercased UUID>")
    func clientIDShapes() {
        let uuid = UUID(uuidString: "6F9619FF-8B86-4011-B42D-00C04FC964FF")!
        #expect(DecisionID.make(uuid).rawValue == "decision_6f9619ff-8b86-4011-b42d-00c04fc964ff")
        #expect(FormulationID.make(uuid).rawValue == "form_6f9619ff-8b86-4011-b42d-00c04fc964ff")
        #expect(ProgressID.make(uuid).rawValue == "progress_6f9619ff-8b86-4011-b42d-00c04fc964ff")
        #expect(ReviewSessionID.make(uuid).rawValue == "review_6f9619ff-8b86-4011-b42d-00c04fc964ff")
        #expect(BulkID.make(uuid).rawValue == "bulk_6f9619ff-8b86-4011-b42d-00c04fc964ff")
        #expect(ClientID.isValid(ClientID.derived("form", from: "task_1|1"), prefix: "form"))
        #expect(!ClientID.isValid("form_Renovate the bathroom", prefix: "form"))
    }

    // MARK: - Errors

    @Test("020-FR-045 a 404 weekly_review_disabled is featureDisabled: kept and retried, never set aside")
    func featureDisabled() async throws {
        let fixture = Self.entry("W-070")
        let client = Fixture.client(
            ScriptedTransport([.respond(HTTPResponse(statusCode: 404, headers: ["content-type": "application/json"], body: fixture.body))]),
            store: Fixture.signedInStore()
        )
        let error = try #require(await expectAPIError { _ = try await client.reviewState() })
        #expect(error.kind == .featureDisabled)
        #expect(error.reason == "weekly_review_disabled")
        #expect(error.isRetryable)
        #expect(!error.isUncertainOutcome)
        #expect(error.referenceID == "corr_5f2a9c7e1b3d")
    }

    @Test("020-FR-045 a plain 404 stays notFound")
    func plainNotFound() async throws {
        let client = Fixture.client(
            ScriptedTransport([Fixture.error(404, "Review session was not found.", detail: #"{"resource":"Review session","id":"review_x"}"#)]),
            store: Fixture.signedInStore()
        )
        let error = try #require(await expectAPIError { _ = try await client.session(id: "review_x") })
        #expect(error.kind != .featureDisabled)
        #expect(!error.isRetryable)
    }

    static func entry(_ id: String) -> Entry {
        guard let entry = entries.first(where: { $0.id == id }) else { fatalError("No wire fixture \(id)") }
        return entry
    }
}
