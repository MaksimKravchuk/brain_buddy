import Foundation
import Testing

@testable import BrainBuddyCore

@Suite("Original-source local Review private codec (026-FR-013, 026-FR-025)")
struct RustLegacyReviewPrivateCodecTests {
    private let instant = "2026-10-10T09:00:00Z"
    private let taskID = "00000000-0000-4000-8000-000000000011"

    private func fixture() throws -> WireObject {
        var root = URL(fileURLWithPath: #filePath)
        for _ in 0..<5 { root.deleteLastPathComponent() }
        return try RustJSON.object(Data(contentsOf: root.appendingPathComponent(
            "rust/crates/bb-client/tests/fixtures/legacy-review-activation.json")))
    }

    private func entry(_ kind: String) throws -> WireObject {
        let fixture = try fixture()
        let family = kind == "decision" ? "decisions" : "bulkReleases"
        let publicFamily = kind == "decision" ? "decisions" : "bulk_releases"
        let source = try #require(try fixture.object("source_review").object(family).values.first as? WireObject)
        let record = try #require(try fixture.object("expected_read_set").object(publicFamily).values.first as? WireObject)
        let session = try #require(try fixture.object("source_review").object("sessions").values.first as? WireObject)
        return ["source_kind": kind, "source_id": try source.string("id"),
                "source_fragment_sha256": "runtime-owned-source-digest", "entity_type": "review_" + kind,
                "record_key": [try record.string("id")], "public_sha256": "runtime-owned-public-digest",
                "public_record_version": "9", "task_public": ["task_history_proven": ["record_version": "9",
                    "public_sha256": "runtime-owned-task-digest", "edit_revision": "4"]] as WireObject,
                "session_public": ["record_version": "9", "public_sha256": "runtime-owned-session-digest",
                                   "edit_revision": "2"] as WireObject,
                "source": source, "public": record,
                "source_tasks": try fixture.object("source_tasks"), "source_session": session]
    }

    private func prepare(_ entry: WireObject, at instant: String = "2026-10-10T10:00:00Z") throws -> WireObject {
        try RustLegacyReviewPrivateCodec.prepare(entry, bindings: [.init(entityType: "task", localID: taskID,
            canonicalID: "task_history_proven")], now: #require(RustInstant.parse(instant)))
    }

    @Test("Exact Undo snapshot and source receipt stamp are private; missing revisions require source match evidence")
    func originalDecisionAndReceipt() throws {
        var captured = try entry("decision")
        var source = try captured.object("source")
        var undo = try source.object("undo")
        var before = try undo.object("taskBefore")
        before.removeValue(forKey: "serverRevision")
        undo["taskBefore"] = before
        undo["receiptReplaced"] = ["taskID": taskID, "kind": "waiting", "reviewedAt": instant,
            "hiddenUntil": "2026-10-17T09:00:00Z", "source": "keep", "taskUpdatedAt": instant] as WireObject
        source["undo"] = undo
        source["taskAfter"] = ["updatedAt": instant] as WireObject
        captured["source"] = source
        var publicRecord = try captured.object("public")
        publicRecord["task_revision_before"] = "0"
        publicRecord["task_revision_after"] = "0"
        captured["public"] = publicRecord
        var tasks = try captured.object("source_tasks")
        var original = try tasks.object(taskID)
        original.removeValue(forKey: "serverRevision")
        tasks[taskID] = original
        captured["source_tasks"] = tasks
        let result = try prepare(captured)
        let fields = try result.object("private").object("fields")
        #expect(try result.object("evidence").bool("task_matches"))
        #expect(try fields.object("task_before").string("title") == before.string("title"))
        #expect(try fields.object("task_before").string("revision") == captured.object("public").string("task_revision_before"))
        #expect(try fields.object("local_before").object("receipt_replaced").bool("task_was_unchanged"))
        #expect(fields["created_task_revision"] as? String == "1")
        #expect(try result.string("source_fragment_sha256") == "runtime-owned-source-digest")
        var ids = RustIDTable()
        let decision = try decode(ReviewDecision.self, source)
        #expect(RustReadSet.decision(decision, &ids)["private"] == nil)
        #expect(RustReadSet.decision(decision, &ids)["local_before"] == nil)
        original["updatedAt"] = "2026-10-10T09:00:01Z"
        tasks[taskID] = original
        captured["source_tasks"] = tasks
        #expect(try !prepare(captured).object("evidence").bool("task_matches"))
        var replaced = try undo.object("receiptReplaced")
        replaced["taskRevision"] = 4
        undo["receiptReplaced"] = replaced
        source["undo"] = undo
        captured["source"] = source
        #expect(try !prepare(captured).object("private").object("fields").object("local_before")
            .object("receipt_replaced").bool("task_was_unchanged"))
    }

    @Test("Only the frozen original session instant admits restoration; exact seven days never extends retention")
    func sessionAndRetention() throws {
        var captured = try entry("decision")
        let mapped = try prepare(captured)
        #expect(try mapped.object("evidence").bool("session_matches"))
        let frozen = try mapped.object("private").object("fields").object("local_before").object("session_before")
        #expect(try frozen.string("last_activity_after") == instant)
        #expect(frozen["revision_after"] is NSNull)
        var session = try captured.object("source_session")
        session["lastActivityAt"] = "2026-10-10T09:00:01Z"
        captured["source_session"] = session
        let later = try prepare(captured)
        #expect(try !later.object("evidence").bool("session_matches"))
        #expect(try later.object("private").object("fields").object("local_before")["session_before"] is NSNull)
        #expect(try prepare(captured, at: "2026-10-17T09:00:00Z")["private"] is NSNull)
        #expect(try prepare(captured, at: "2026-10-17T08:59:59Z")["private"] is WireObject)
    }

    @Test("Bulk clock identity stays exact; a replaced receipt with no pre-release instant proof stays stale")
    func bulkClockAndReceipt() throws {
        var captured = try entry("bulk_release")
        var source = try captured.object("source")
        source.removeValue(forKey: "undoneAt")
        source.removeValue(forKey: "undoResult")
        var item = try #require(try source.objects("released").first)
        item["clockKnown"] = true
        item["previousState"] = "next"
        item["clockBefore"] = ["clock": ["id": "00000000-0000-4000-8000-000000000016",
            "startedAt": instant, "extensionReason": "Original private reason"], "stalledBefore": 2] as WireObject
        item["receiptReplaced"] = ["taskID": taskID, "kind": "someday", "reviewedAt": instant,
            "hiddenUntil": "2026-11-09T09:00:00Z", "source": "keep", "taskRevision": 6] as WireObject
        source["released"] = [item]
        captured["source"] = source
        var tasks = try captured.object("source_tasks")
        var task = try tasks.object(taskID)
        task["serverRevision"] = 6
        tasks[taskID] = task
        captured["source_tasks"] = tasks
        let fields = try #require(try prepare(captured).object("private")["fields"] as? [WireObject])
        #expect(try fields[0].object("clock_before").string("formulation_id") == "00000000-0000-4000-8000-000000000016")
        #expect(try fields[0].bool("local_source_task_unchanged"))
        #expect(try fields[0].object("local_receipt_replaced").bool("task_was_unchanged"))
        var receipt = try item.object("receiptReplaced")
        receipt["taskUpdatedAt"] = instant
        item["receiptReplaced"] = receipt
        source["released"] = [item]
        captured["source"] = source
        let stale = try #require(try prepare(captured).object("private")["fields"] as? [WireObject])
        #expect(try !stale[0].object("local_receipt_replaced").bool("task_was_unchanged"))
        item["clockKnown"] = false
        source["released"] = [item]
        captured["source"] = source
        let unknown = try #require(try prepare(captured).object("private")["fields"] as? [Any])
        #expect(unknown[0] is NSNull)
        task["serverRevision"] = 99
        tasks[taskID] = task
        captured["source_tasks"] = tasks
        let knownStale = try #require(try prepare(captured).object("private")["fields"] as? [WireObject])
        #expect(try !knownStale[0].bool("local_source_task_unchanged"))
        #expect(knownStale[0]["clock_before"] is NSNull)
        #expect(try prepare(captured, at: "2026-10-17T09:00:00Z")["private"] is NSNull)
    }

    @Test("Original accountless park clocks retain an absent counter for Rust's explicit baseline anchor")
    func originalParkAndNestedSnapshot() throws {
        let fixture = try fixture()
        var task = try fixture.object("source_tasks").object(taskID)
        task.removeValue(forKey: "serverRevision")
        task["state"] = "someday"
        task.removeValue(forKey: "waitingFor")
        task.removeValue(forKey: "waitingSince")
        task["parked"] = ["at": instant, "formulationID": "00000000-0000-4000-8000-000000000016",
            "clockBefore": ["id": "00000000-0000-4000-8000-000000000016", "startedAt": instant,
                "extendedAt": instant, "extensionReason": "Exact private clock reason"], "stalledBefore": 2] as WireObject
        let captured: WireObject = ["source_kind": "task_park", "source_id": taskID,
            "source_fragment_sha256": "runtime-owned-source-digest", "entity_type": "task",
            "record_key": ["task_history_proven"], "public_sha256": "runtime-owned-public-digest",
            "public_record_version": "0", "task_public": [:] as WireObject,
            "source": task, "source_tasks": [taskID: task], "public": ["id": "task_history_proven"] as WireObject]
        let park = try prepare(captured).object("private").object("fields")
        #expect(park["from_revision"] is NSNull)
        #expect(try park.object("clock_before").string("extension_reason") == "Exact private clock reason")
        #expect(try park.object("clock_before").string("formulation_id") == "00000000-0000-4000-8000-000000000016")
        // Park retention follows the existing marker policy, not a new retry TTL.
        #expect(try prepare(captured, at: "2026-10-30T09:00:00Z").object("private").object("fields")["from_revision"] is NSNull)
        var decision = try entry("decision")
        var source = try decision.object("source")
        var undo = try source.object("undo")
        undo["taskBefore"] = task
        undo["receiptReplaced"] = ["taskID": taskID, "kind": "waiting", "reviewedAt": instant,
            "hiddenUntil": instant, "source": "keep"] as WireObject
        source["undo"] = undo
        decision["source"] = source
        let prepared = try prepare(decision)
        #expect(try prepared.object("task_before_park")["from_revision"] is NSNull)
        #expect(try prepared.object("private").object("fields").object("task_before").object("parked")["private"] == nil)
        // An expired receipt keeps its original deadline; its task constraints
        // are independently proven and never use a reconstructed revision.
        #expect(try prepared.object("private").object("fields").object("local_before")
            .object("receipt_replaced").bool("task_was_unchanged"))
    }

    private func decode<T: Decodable>(_ type: T.Type, _ object: WireObject) throws -> T {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let text = try decoder.singleValueContainer().decode(String.self)
            return try #require(RustInstant.parse(text))
        }
        return try decoder.decode(type, from: RustJSON.data(object))
    }
}
