import Foundation
import Testing

@testable import BrainBuddyCore

@Suite("Bounded original-source private Review components (026-FR-013, 026-FR-025)")
struct RustLegacyReviewPrivateCodecTests {
    private let instant = "2026-10-10T09:00:00Z"
    private let taskID = "00000000-0000-4000-8000-000000000011"
    private let decisionID = "00000000-0000-4000-8000-000000000014"
    private let bulkID = "00000000-0000-4000-8000-000000000015"
    private let sessionID = "00000000-0000-4000-8000-000000000013"

    private func fixture() throws -> WireObject {
        var root = URL(fileURLWithPath: #filePath)
        for _ in 0..<5 { root.deleteLastPathComponent() }
        return try RustJSON.object(Data(contentsOf: root.appendingPathComponent(
            "rust/crates/bb-client/tests/fixtures/legacy-review-activation.json")))
    }

    private func page(kind: String, id: String, type: String, canonical: String, component: String,
                      length: Int, offset: Int = 0, count: Int = 1, ordinal: Int = 0) -> WireObject {
        ["header": ["codec_version": 1, "token": ["workspace_id": "local"],
            "binding": ["source_kind": kind, "source_id": id, "source_fragment_sha256": "whole-original-source-digest",
                "entity_type": type, "record_key": [canonical], "public_sha256": "runtime-public-digest",
                "public_record_version": "0", "task_public": [:] as WireObject, "session_public": NSNull()] as WireObject,
            "source_at": instant, "deadline": kind == "task_park" ? NSNull() : "2026-10-17T09:00:00Z" as Any,
            "component_lengths": [component: length]] as WireObject,
         "ordinal": ordinal, "component": component, "offset": offset, "count": count,
         "fragment_sha256": "runtime-selected-component-digest", "aliases": [WireObject](),
         "task_public": [:] as WireObject, "session_public": NSNull(), "source_tasks": [:] as WireObject,
         "source_session": NSNull(), "next_cursor": "opaque-next-component"]
    }

    private func decisionPage() throws -> WireObject {
        let fixture = try fixture()
        var source = try fixture.object("source_review").object("decisions").object(decisionID)
        var undo = try source.object("undo")
        var before = try undo.object("taskBefore")
        for key in ["tagIDs", "subtasks", "comments", "childrenSyncedAt"] { before.removeValue(forKey: key) }
        undo["taskBefore"] = before
        source["undo"] = undo
        var result = page(kind: "decision", id: decisionID, type: "review_decision", canonical: "decision_" + decisionID,
                          component: "decision_scalar", length: 1)
        result["source"] = source
        result["public"] = try fixture.object("expected_read_set").object("decisions").object("decision_" + decisionID)
        result["source_tasks"] = [taskID: ["id": taskID, "serverRevision": 5, "updatedAt": instant]] as WireObject
        result["source_session"] = ["id": sessionID, "lastActivityAt": instant] as WireObject
        result["aliases"] = [["entity_type": "task", "local_id": taskID, "server_id": "task_history_proven"]]
        return result
    }

    private func prepare(_ page: WireObject, at instant: String = "2026-10-10T10:00:00Z") throws -> WireObject {
        let aliases = try page.objects("aliases").map { row in
            RustWorkspaceIdentityBinding(entityType: try row.string("entity_type"), localID: try row.string("local_id"),
                                         canonicalID: try row.string("server_id"))
        }
        return try RustLegacyReviewPrivateCodec.preparePage(page, bindings: aliases, now: #require(RustInstant.parse(instant)))
    }

    @Test("Scalar Undo uses narrow witnesses; omitted children and tags never become empty or complete")
    func scalarWitnessesAndReceipts() throws {
        var captured = try decisionPage()
        var source = try captured.object("source")
        var undo = try source.object("undo")
        var before = try undo.object("taskBefore")
        before.removeValue(forKey: "serverRevision")
        undo["taskBefore"] = before
        undo["receiptReplaced"] = ["taskID": taskID, "kind": "waiting", "reviewedAt": instant,
            "hiddenUntil": instant, "source": "keep", "taskUpdatedAt": instant] as WireObject
        source["undo"] = undo
        source["taskAfter"] = ["updatedAt": instant] as WireObject
        captured["source"] = source
        captured["source_tasks"] = [taskID: ["id": taskID, "updatedAt": instant]] as WireObject
        let result = try prepare(captured)
        let fields = try result.object("private").object("fields")
        let taskBefore = try fields.object("task_before")
        #expect(try result.object("evidence").bool("task_matches"))
        #expect(taskBefore["tag_ids"] == nil)
        #expect(taskBefore["subtasks"] == nil && taskBefore["comments"] == nil)
        #expect(taskBefore["children_known"] == nil)
        #expect(try fields.object("local_before").object("receipt_replaced").bool("task_was_unchanged"))
        #expect(try fields.object("local_before").object("receipt_replaced").object("receipt").string("hidden_until") == instant)
        #expect(try result.string("fragment_sha256") == "runtime-selected-component-digest")
        #expect(try result.object("header").object("binding").string("source_fragment_sha256") == "whole-original-source-digest")
        var receipt = try undo.object("receiptReplaced")
        receipt["taskUpdatedAt"] = "2026-10-10T09:00:01Z"
        undo["receiptReplaced"] = receipt
        source["undo"] = undo
        captured["source"] = source
        #expect(try !prepare(captured).object("private").object("fields").object("local_before")
            .object("receipt_replaced").bool("task_was_unchanged"))
        source["taskAfter"] = ["serverRevision": 5] as WireObject
        captured["source"] = source
        captured["source_tasks"] = [taskID: ["id": taskID, "serverRevision": 5, "updatedAt": "2026-10-10T10:00:00Z"]] as WireObject
        #expect(try prepare(captured).object("evidence").bool("task_matches"))
        // Only the witness crosses the seam; the full immutable digest binds
        // the original store's irrelevant child and session collections.
        let witness = try RustLegacyPrivateSourceDecoding.decode(RustLegacyTaskStampWitness.self,
            ["id": taskID, "updatedAt": instant] as WireObject)
        #expect(witness.serverRevision == nil)
        #expect(TaskStamp(updatedAt: try #require(RustInstant.parse(instant)), serverRevision: nil).matchesLegacyWitness(witness))
    }

    @Test("Original session activity and the exact seven-day deadline fence each prepared page")
    func sessionAndRetention() throws {
        var captured = try decisionPage()
        let result = try prepare(captured)
        #expect(try result.object("evidence").bool("session_matches"))
        let frozen = try result.object("private").object("fields").object("local_before").object("session_before")
        #expect(frozen["revision_after"] is NSNull)
        captured["source_session"] = ["id": sessionID, "lastActivityAt": "2026-10-10T09:00:01Z"] as WireObject
        let later = try prepare(captured)
        #expect(try !later.object("evidence").bool("session_matches"))
        #expect(try later.object("private").object("fields").object("local_before")["session_before"] is NSNull)
        #expect(try prepare(captured, at: "2026-10-17T09:00:00Z")["private"] is NSNull)
        #expect(try prepare(captured, at: "2026-10-17T08:59:59Z")["private"] is WireObject)
    }

    @Test("201- and 500-item releases prepare independent bounded pages, preserving original stale flags")
    func multiPageBulk() throws {
        for total in [201, 500] {
            for offset in stride(from: 0, to: total, by: 20) {
                let count = min(20, total - offset)
                var captured = page(kind: "bulk_release", id: bulkID, type: "review_bulk_release", canonical: "bulk_" + bulkID,
                    component: "bulk_released", length: total, offset: offset, count: count, ordinal: offset / 20)
                var sourceRows: [WireObject] = [], publicRows: [WireObject] = [], aliases: [WireObject] = []
                var witnesses: WireObject = [:]
                for item in offset..<(offset + count) {
                    let id = String(format: "00000000-0000-4000-8000-%012x", 1_000 + item)
                    sourceRows.append(["taskID": id, "previousState": "next", "clockKnown": false,
                        "taskAfter": ["serverRevision": 6, "updatedAt": instant],
                        "receiptReplaced": ["taskID": id, "kind": "someday", "reviewedAt": instant,
                            "hiddenUntil": "2026-11-09T09:00:00Z", "source": "keep", "taskRevision": 6,
                            "taskUpdatedAt": instant]] as WireObject)
                    publicRows.append(["task_id": "task_" + id, "revision_after": "6"])
                    witnesses[id] = ["id": id, "serverRevision": 99, "updatedAt": instant] as WireObject
                    aliases.append(["entity_type": "task", "local_id": id, "server_id": "task_" + id])
                }
                captured["source"] = ["id": bulkID, "createdAt": instant, "released": sourceRows] as WireObject
                captured["public"] = ["id": "bulk_" + bulkID, "released": publicRows] as WireObject
                captured["source_tasks"] = witnesses
                captured["aliases"] = aliases
                let result = try prepare(captured)
                let fields = try #require(try result.object("private")["fields"] as? [WireObject])
                #expect(fields.count == count)
                #expect(fields.allSatisfy { $0["local_source_task_unchanged"] as? Bool == false })
                #expect(fields.allSatisfy { $0["clock_before"] is NSNull })
                #expect(try !fields[0].object("local_receipt_replaced").bool("task_was_unchanged"))
                #expect(try result.int("offset") == offset)
                #expect(result["next_cursor"] == nil)
                #expect(try RustJSON.data(result).count < 32_768)
            }
        }
    }

    @Test("Meaningful tags stay in distinct components and use exact typed aliases")
    func tagComponentsAndBounds() throws {
        for offset in [0, 80, 160] {
            let count = min(80, 201 - offset)
            var captured = page(kind: "decision", id: decisionID, type: "review_decision", canonical: "decision_" + decisionID,
                component: "decision_tags", length: 201, offset: offset, count: count, ordinal: 1 + offset / 80)
            let ids = (offset..<(offset + count)).map { String(format: "00000000-0000-4000-8000-%012x", 2_000 + $0) }
            captured["source"] = ids
            captured["public"] = NSNull()
            captured["aliases"] = ids.map { ["entity_type": "tag", "local_id": $0, "server_id": "tag_" + $0] }
            let result = try prepare(captured)
            #expect(try result.object("private").strings("fields") == ids.map { "tag_" + $0 })
            #expect(try result.string("component") == "decision_tags")
        }
        var oversized = page(kind: "decision", id: decisionID, type: "review_decision", canonical: "decision_" + decisionID,
            component: "decision_tags", length: 201, count: 201)
        oversized["source"] = Array(repeating: taskID, count: 201)
        #expect(throws: RustDomainError.malformedResult) { try prepare(oversized) }
        var copiedChildren = try decisionPage()
        var source = try copiedChildren.object("source"), undo = try source.object("undo"), before = try undo.object("taskBefore")
        before["subtasks"] = [WireObject]()
        undo["taskBefore"] = before
        source["undo"] = undo
        copiedChildren["source"] = source
        #expect(throws: RustDomainError.malformedResult) { try prepare(copiedChildren) }
    }

    @Test("Standalone and nested parks retain an absent source counter for the explicit LOCAL anchor")
    func parkComponents() throws {
        let marker: WireObject = ["at": instant, "formulationID": "00000000-0000-4000-8000-000000000016",
            "clockBefore": ["id": "00000000-0000-4000-8000-000000000016", "startedAt": instant,
                "extendedAt": instant, "extensionReason": "Exact private reason"], "stalledBefore": 2]
        var captured = page(kind: "task_park", id: taskID, type: "task", canonical: "task_history_proven", component: "task_park", length: 1)
        captured["source"] = ["id": taskID, "updatedAt": instant, "parked": marker] as WireObject
        captured["source_tasks"] = [taskID: ["id": taskID, "updatedAt": instant]] as WireObject
        captured["aliases"] = [["entity_type": "task", "local_id": taskID, "server_id": "task_history_proven"]]
        let park = try prepare(captured, at: "2026-10-30T09:00:00Z").object("private").object("fields")
        #expect(park["from_revision"] is NSNull)
        #expect(try park.object("clock_before").string("extension_reason") == "Exact private reason")
        var decision = try decisionPage()
        var source = try decision.object("source"), undo = try source.object("undo"), before = try undo.object("taskBefore")
        before["parked"] = marker
        undo["taskBefore"] = before
        source["undo"] = undo
        decision["source"] = source
        let prepared = try prepare(decision)
        #expect(try prepared.object("task_before_park")["from_revision"] is NSNull)
        #expect(try prepared.object("private").object("fields").object("task_before").object("parked")["private"] == nil)
    }

    @Test("Imported progress IDs use their own components without payload digests; settings keep only source bookkeeping")
    func sessionProgressAndSettings() throws {
        var session = page(kind: "session", id: sessionID, type: "review_session", canonical: "review_" + sessionID,
                           component: "session_scalar", length: 1)
        var header = try session.object("header")
        header["deadline"] = NSNull()
        header["component_lengths"] = ["session_scalar": 1, "session_progress": 201]
        session["header"] = header
        session["source"] = ["id": sessionID, "status": "open", "qualifyingActivity": true] as WireObject
        let scalar = try prepare(session).object("private").object("fields")
        #expect(try scalar.object("applied_progress").isEmpty)
        #expect(try scalar.strings("finished_empty").isEmpty)
        #expect(try scalar.strings("local_imported_progress").isEmpty)
        #expect(scalar["qualifying_activity"] == nil)
        for offset in [0, 80, 160] {
            var progress = session
            let count = min(80, 201 - offset)
            progress["ordinal"] = 1 + offset / 80
            progress["component"] = "session_progress"
            progress["offset"] = offset
            progress["count"] = count
            let ids = (offset..<(offset + count)).map { String(format: "00000000-0000-4000-8000-%012x", 3_000 + $0) }
            progress["source"] = ids
            let fields = try prepare(progress).object("private").strings("fields")
            #expect(fields == ids.map { "progress_" + $0 })
        }
        var settings = page(kind: "settings", id: "settings", type: "review_settings", canonical: "unused",
                            component: "settings", length: 1)
        header = try settings.object("header")
        header["deadline"] = NSNull()
        var binding = try header.object("binding")
        binding["record_key"] = [String]()
        header["binding"] = binding
        settings["header"] = header
        settings["source"] = try fixture().object("source_review").object("settings")
        let fields = try prepare(settings).object("private").object("fields")
        #expect(try fields.string("threshold_changed_at") == instant)
        #expect(fields["last_effective_sweep_at"] is NSNull)
    }
}
