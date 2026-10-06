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

    /// Every entry of the file; a malformed one stops the suite instead of
    /// silently dropping out.
    static let entries: [Entry] = {
        guard let url = Bundle.module.url(forResource: "review_wire_fixtures", withExtension: "json", subdirectory: "Resources"),
            let data = try? Data(contentsOf: url),
            let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let entries = root["entries"] as? [[String: Any]]
        else { fatalError("Missing or unreadable test resource Resources/review_wire_fixtures.json") }
        return entries.map { entry in
            guard let id = entry["id"] as? String, let model = entry["model"] as? String,
                let kind = entry["kind"] as? String, let valid = entry["valid"] as? Bool, let body = entry["body"],
                let encoded = try? JSONSerialization.data(withJSONObject: body, options: [.sortedKeys])
            else { fatalError("Malformed wire fixture entry \(entry)") }
            let keys = (body as? [String: Any]).map { Set($0.filter { !($0.value is NSNull) }.keys) } ?? []
            return Entry(id: id, model: model, kind: kind, valid: valid, body: encoded, keys: keys)
        }
    }()

    /// Where each entry runs. Invalid request bodies run against the fake
    /// server in `ReviewSyncTests.fakeServerRefusesInvalidBodies` (the device
    /// never builds them); the navigator suggestion request belongs to the
    /// PR-08 navigator client and has no body type here yet.
    static let responses = entries.filter { $0.kind == "response" && $0.valid && $0.model != "ErrorResponse" }
    static let errors = entries.filter { $0.model == "ErrorResponse" }
    static let requests = entries.filter { $0.kind == "request" && $0.valid && $0.model != "NavigatorSuggestionRequest" }
    static let invalidResponses = entries.filter { $0.kind == "response" && !$0.valid }
    static let invalidRequests = entries.filter { $0.kind == "request" && !$0.valid }
    static let navigatorRequests = entries.filter { $0.model == "NavigatorSuggestionRequest" }

    private let decoder = BrainBuddyAPI.makeDecoder()
    private let encoder = BrainBuddyAPI.makeEncoder()

    @Test("020-FR-011 every fixture entry is accounted for, exactly once")
    func everyEntryRuns() {
        #expect(Self.entries.count == 61)
        let groups = [Self.responses, Self.errors, Self.requests, Self.invalidResponses, Self.invalidRequests]
        var seen: [String] = groups.flatMap { $0.map(\.id) }
        seen += Self.navigatorRequests.filter(\.valid).map(\.id)
        #expect(seen.count == Set(seen).count, "no entry runs twice")
        #expect(Set(seen) == Set(Self.entries.map(\.id)))
        #expect(Set(Self.navigatorRequests.map(\.id)) == ["W-063", "W-064", "W-067", "W-R04", "W-R13"])
        #expect(Set(Self.errors.map(\.id)) == ["W-070", "W-071"])
        #expect(Set(Self.invalidResponses.map(\.id)) == ["W-R09", "W-R11"])
    }

    // MARK: - Responses

    @Test("020-FR-011 every valid response fixture decodes into its DTO and re-encodes to the same fields", arguments: responses)
    func decodesResponse(_ entry: Entry) throws {
        let encoded: Data
        switch entry.model {
        case "TaskResponse": encoded = try encoder.encode(try decoder.decode(TaskDTO.self, from: entry.body))
        case "DecisionResponse": encoded = try encoder.encode(try decoder.decode(DecisionResponseDTO.self, from: entry.body))
        case "UndoDecisionResponse": encoded = try encoder.encode(try decoder.decode(UndoDecisionResponseDTO.self, from: entry.body))
        case "AutoParkResponse": encoded = try encoder.encode(try decoder.decode(AutoParkResponseDTO.self, from: entry.body))
        case "ReviewStateResponse": encoded = try encoder.encode(try decoder.decode(ReviewStateDTO.self, from: entry.body))
        case "ReviewSettingsResponse": encoded = try encoder.encode(try decoder.decode(ReviewSettingsDTO.self, from: entry.body))
        case "SessionResponse": encoded = try encoder.encode(try decoder.decode(SessionDTO.self, from: entry.body))
        case "QueueResponse": encoded = try encoder.encode(try decoder.decode(QueueResponseDTO.self, from: entry.body))
        case "BulkReleaseResponse": encoded = try encoder.encode(try decoder.decode(BulkReleaseResponseDTO.self, from: entry.body))
        case "BulkReleaseUndoResponse": encoded = try encoder.encode(try decoder.decode(BulkReleaseUndoResponseDTO.self, from: entry.body))
        case "NavigatorStatusResponse": encoded = try encoder.encode(try decoder.decode(NavigatorStatusDTO.self, from: entry.body))
        case "NavigatorSuggestionResponse":
            encoded = try encoder.encode(try decoder.decode(NavigatorSuggestionResponseDTO.self, from: entry.body))
        default:
            Issue.record("No DTO mapped for \(entry.model)")
            return
        }
        let expected = WireLeaves(try JSONSerialization.jsonObject(with: entry.body))
        let actual = WireLeaves(try JSONSerialization.jsonObject(with: encoded))
        for (path, value) in expected.values {
            guard let decoded = actual.values[path] else {
                // A zero counter is not kept (SessionCounts stores non-zero ones).
                #expect(value == "0", "\(entry.id): \(path) = \(value) was dropped")
                continue
            }
            #expect(WireLeaves.same(value, decoded), "\(entry.id): \(path) is \(decoded), expected \(value)")
        }
        #expect(Set(actual.values.keys).subtracting(expected.values.keys).isEmpty, "\(entry.id): fields the server never sent")
    }

    @Test("020-FR-011 invalid response bodies are not taken as valid")
    func invalidResponses() throws {
        // W-R11: exactly one of proposals and clarifying_question.
        #expect(throws: (any Error).self) {
            try decoder.decode(NavigatorSuggestionResponseDTO.self, from: Self.entry("W-R11").body)
        }
        // W-R09: set_aside_task_ids stays server-side; the device keeps only the count.
        let session = try decoder.decode(SessionDTO.self, from: Self.entry("W-R09").body)
        let keys = try #require(try JSONSerialization.jsonObject(with: encoder.encode(session)) as? [String: Any]).keys
        #expect(!keys.contains("set_aside_task_ids"))
    }

    @Test("020-FR-045 a client id reused by another record (W-071) is a rejection with its Ref, not retried")
    func idConflict() async throws {
        let fixture = Self.entry("W-071")
        let client = Fixture.client(
            ScriptedTransport([.respond(HTTPResponse(statusCode: 409, headers: ["content-type": "application/json"], body: fixture.body))]),
            store: Fixture.signedInStore()
        )
        let error = try #require(await expectAPIError { _ = try await client.session(id: "review_x") })
        #expect(error.kind == .rejected)
        #expect(error.reason == "id_conflict")
        #expect(!error.isRetryable)
        #expect(error.referenceID == "corr_8b1d4f6a2c9e")
    }

    @Test("020-FR-045 unknown values on the response side are tolerated, not fatal")
    func lenientResponses() throws {
        var state = try #require(try JSONSerialization.jsonObject(with: Self.entry("W-030").body) as? [String: Any])
        var open = try #require(state["open_session"] as? [String: Any])
        open["entry"] = "watch"
        open["origin"] = "android"
        open["current_step"] = "reflect"
        var steps = try #require(open["steps"] as? [String: Any])
        steps["reflect"] = "finished"
        steps["inbox"] = "half_done"
        open["steps"] = steps
        var seconds = try #require(open["active_seconds_by_step"] as? [String: Any])
        seconds["reflect"] = 5
        open["active_seconds_by_step"] = seconds
        var counts = try #require(open["counts"] as? [String: Any])
        counts["celebrated"] = 2
        open["counts"] = counts
        state["open_session"] = open
        var receipts = try #require(state["receipts"] as? [[String: Any]])
        receipts.append(["task_id": "task_1a2b3c4d5e6f", "kind": "someday_plus", "hidden_until": "2026-10-12T10:00:00Z", "task_revision": 1])
        state["receipts"] = receipts
        var last = try #require(state["last_counted_review"] as? [String: Any])
        last["status"] = "archived_by_admin"
        state["last_counted_review"] = last

        let decoded = try decoder.decode(ReviewStateDTO.self, from: JSONSerialization.data(withJSONObject: state))
        let session = try #require(decoded.openSession)
        #expect(session.currentStep == nil)
        #expect(session.steps == [.wins: .finished, .decisions: .pending, .summary: .pending])
        #expect(session.activeSecondsByStep[.wins] == 42 && session.activeSecondsByStep.count == 3)
        #expect(session.counts[.firstStep] == 1 && session.counts.total == 1)
        #expect(session.entry == .list, "an unknown entry (metrics only) reads as list")
        #expect(session.origin == .web, "an unknown origin reads as another device")
        #expect(decoded.receipts.map(\.taskID) == ["task_6d2f8b4a1c7e"], "an unknown receipt kind is dropped")
        #expect(decoded.lastCountedReview == nil, "an unreadable summary is dropped, not fatal")

        var response = try #require(try JSONSerialization.jsonObject(with: Self.entry("W-014").body) as? [String: Any])
        var decision = try #require(response["decision"] as? [String: Any])
        decision["type"] = "snooze"
        decision["stall_reason"] = "bored"
        decision["ai_use"] = "magic"
        response["decision"] = decision
        let answer = try decoder.decode(DecisionResponseDTO.self, from: JSONSerialization.data(withJSONObject: response))
        #expect(answer.decision.type == nil && answer.decision.stallReason == nil && answer.decision.aiUse == AIUse.none)
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

/// The non-null leaves of a JSON value by path (`a.b`, `a[0].c`), as text.
struct WireLeaves {
    var values: [String: String] = [:]

    init(_ value: Any) { collect(value, path: "") }

    private mutating func collect(_ value: Any, path: String) {
        switch value {
        case is NSNull:
            break
        case let object as [String: Any]:
            for (key, member) in object { collect(member, path: path.isEmpty ? key : "\(path).\(key)") }
        case let array as [Any]:
            for (index, item) in array.enumerated() { collect(item, path: "\(path)[\(index)]") }
        case let number as NSNumber:
            // Both sides go through JSONSerialization, so a Bool reads the same on each.
            values[path] = number.stringValue
        default:
            values[path] = "\(value)"
        }
    }

    /// Equal text, or the same instant written with another precision.
    static func same(_ lhs: String, _ rhs: String) -> Bool {
        if lhs == rhs { return true }
        guard let left = WireDate.parse(lhs), let right = WireDate.parse(rhs) else { return false }
        return left == right
    }
}
