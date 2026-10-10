import Foundation

/// A migration-only private payload. It never enters the public Review read set.
public struct RustWorkspaceLegacyReviewPrivatePreparation: Sendable {
    public let payload: Data
}

extension RustDomainFacade {
    /// `capture` contains bounded fragments from the runtime-verified original
    /// backup, not a current Swift projection. Rust revalidates every echoed
    /// proof and supplies the admitted native revisions under its write lock.
    public func workspacePrepareLegacyReviewPrivate(_ capture: Data, now: Date) throws
        -> RustWorkspaceLegacyReviewPrivatePreparation {
        let object = try RustJSON.object(capture)
        let entries = try object.objects("entries")
        guard entries.count <= 200 else { throw RustDomainError.malformedResult }
        let bindings = try workspaceIdentityBindings(from: RustJSON.data(object["aliases"] ?? []))
        var prepared: [WireObject] = []
        var references = Set<String>()
        for entry in entries {
            references.insert(try entry.string("source_kind") + ":" + entry.string("source_id"))
            for key in try entry.object("source_tasks").keys { references.insert("task:" + key) }
            if let session = entry.optionalObject("source_session") {
                references.insert("session:" + (try session.string("id")))
            }
            guard references.count <= 200 else { throw RustDomainError.malformedResult }
            prepared.append(try RustLegacyReviewPrivateCodec.prepare(entry, bindings: bindings, now: now))
        }
        return RustWorkspaceLegacyReviewPrivatePreparation(payload: try RustJSON.data([
            "token": try object.object("token"), "entries": prepared,
        ]))
    }
}

enum RustLegacyReviewPrivateCodec {
    private static let proofKeys = ["source_kind", "source_id", "source_fragment_sha256", "entity_type",
                                    "record_key", "public_sha256", "public_record_version", "task_public"]

    static func prepare(_ entry: WireObject, bindings: [RustWorkspaceIdentityBinding], now: Date) throws -> WireObject {
        var result: WireObject = [:]
        for key in proofKeys {
            guard let value = entry[key] else { throw RustDomainError.malformedResult }
            result[key] = value
        }
        result["session_public"] = entry["session_public"] ?? NSNull()
        result["task_before_park"] = NSNull()
        let source = try entry.object("source")
        let tasks = try decode([TaskID: TaskRecord].self, entry.object("source_tasks"))
        guard tasks.allSatisfy({ $0.key == $0.value.id }) else { throw RustDomainError.malformedResult }
        let publicRecord = try entry.object("public")
        let recordKey = try entry.strings("record_key")
        guard recordKey == [try publicRecord.string("id")] else { throw RustDomainError.malformedResult }
        var forms = Set(tasks.values.compactMap { $0.formulation?.id.rawValue })
        forms.formUnion(tasks.values.compactMap { $0.parked?.formulationID.rawValue })
        switch try entry.string("source_kind") {
        case "decision":
            let decision = try decode(ReviewDecision.self, source)
            guard decision.id.rawValue == (try entry.string("source_id")),
                  try entry.string("entity_type") == "review_decision" else { throw RustDomainError.malformedResult }
            forms.formUnion([decision.formulationID?.rawValue, decision.undo?.taskBefore.formulation?.id.rawValue,
                             decision.undo?.taskBefore.parked?.formulationID.rawValue,
                             decision.undo?.taskBefore.parked?.clockBefore?.id.rawValue].compactMap { $0 })
            var ids = RustIDTable(bindings: bindings, canonicalFormulationIDs: forms)
            guard ids.decision(decision.id) == recordKey[0],
                  ids.task(decision.taskID) == (try publicRecord.string("task_id")) else { throw RustDomainError.malformedResult }
            let mapped = try decisionFields(decision, tasks: tasks, session: entry.optionalObject("source_session"),
                                            publicRecord: publicRecord, ids: &ids, now: now)
            result["private"] = mapped.fields.map { ["kind": "decision", "fields": $0] as Any } ?? NSNull()
            if mapped.fields != nil, let marker = decision.undo?.taskBefore.parked {
                result["task_before_park"] = parkFields(marker, ids: &ids).map { $0 as Any } ?? NSNull()
            }
            result["evidence"] = ["task_matches": mapped.taskMatches,
                                  "created_task_matches": wireNull(mapped.createdMatches),
                                  "session_matches": wireNull(mapped.sessionMatches)] as WireObject
        case "bulk_release":
            let bulk = try decode(BulkReleaseRecord.self, source)
            guard bulk.id.rawValue == (try entry.string("source_id")),
                  try entry.string("entity_type") == "review_bulk_release" else { throw RustDomainError.malformedResult }
            forms.formUnion(bulk.released.compactMap { $0.clockBefore?.clock.id.rawValue })
            var ids = RustIDTable(bindings: bindings, canonicalFormulationIDs: forms)
            guard ids.bulk(bulk.id) == recordKey[0] else { throw RustDomainError.malformedResult }
            let rows = try publicRecord.objects("released")
            guard rows.count == bulk.released.count else { throw RustDomainError.malformedResult }
            for (item, row) in zip(bulk.released, rows) {
                guard ids.task(item.taskID) == (try row.string("task_id")) else { throw RustDomainError.malformedResult }
            }
            let fields = bulkFields(bulk, tasks: tasks, ids: &ids, now: now)
            result["private"] = fields.map { ["kind": "bulk", "fields": $0] as Any } ?? NSNull()
            result["evidence"] = ["task_matches": NSNull(), "created_task_matches": NSNull(),
                                  "session_matches": NSNull()] as WireObject
        case "task_park":
            let task = try decode(TaskRecord.self, source)
            guard task.id.rawValue == (try entry.string("source_id")),
                  try entry.string("entity_type") == "task" else { throw RustDomainError.malformedResult }
            if let form = task.parked?.formulationID { forms.insert(form.rawValue) }
            if let form = task.parked?.clockBefore?.id { forms.insert(form.rawValue) }
            var ids = RustIDTable(bindings: bindings, canonicalFormulationIDs: forms)
            guard ids.task(task.id) == recordKey[0] else { throw RustDomainError.malformedResult }
            let fields = task.parked.flatMap { parkFields($0, ids: &ids) }
            result["private"] = fields.map { ["kind": "task_park", "fields": $0] as Any } ?? NSNull()
            result["evidence"] = ["task_matches": TaskStamp(task).matches(tasks[task.id]),
                                  "created_task_matches": NSNull(), "session_matches": NSNull()] as WireObject
        default: throw RustDomainError.malformedResult
        }
        return result
    }

    private struct DecisionFields {
        var fields: WireObject?
        var taskMatches: Bool
        var createdMatches: Bool?
        var sessionMatches: Bool?
    }

    private static func decisionFields(_ decision: ReviewDecision, tasks: [TaskID: TaskRecord], session: WireObject?,
                                      publicRecord: WireObject, ids: inout RustIDTable, now: Date) throws -> DecisionFields {
        let taskMatches = decision.taskAfter.matches(tasks[decision.taskID])
        let createdMatches = decision.undo?.createdTaskID.map { id in
            decision.undo?.createdTaskAfter?.matches(tasks[id]) ?? false
        }
        var result = DecisionFields(taskMatches: taskMatches, createdMatches: createdMatches)
        guard now < decision.decidedAt.addingTimeInterval(ReviewRetention.snapshotWindow),
              let undo = decision.undo else { return result }
        guard undo.taskBefore.id == decision.taskID else { throw RustDomainError.malformedResult }
        var before = RustReadSet.task(undo.taskBefore, &ids)
        if var parked = before["parked"] as? WireObject {
            // The adapter-only sibling preserves a missing original counter.
            // Rust injects the strict ParkPrivate after pairing its baseline.
            parked.removeValue(forKey: "private")
            before["parked"] = parked
        }
        // This is a paired public counter, not evidence that a missing native
        // source revision was zero. The separate original stamp match is proof.
        before["revision"] = try publicRecord.string("task_revision_before")
        var replaced: Any = NSNull()
        if let receipt = undo.receiptReplaced {
            replaced = ["receipt": RustReadSet.receipt(receipt, &ids),
                        "task_was_unchanged": receipt.taskIsUnchanged(undo.taskBefore)] as WireObject
        }
        var previousSession: Any = NSNull()
        if let frozen = undo.sessionBefore, let session, let sessionID = decision.sessionID {
            let original = try decode(ReviewSession.self, session)
            guard original.id == sessionID else { throw RustDomainError.malformedResult }
            let matches = original.lastActivityAt == frozen.lastActivityAfter
            result.sessionMatches = matches
            if matches {
                previousSession = ["qualifying_activity": frozen.qualifyingActivity,
                    "last_activity_at": RustInstant.format(frozen.lastActivityAt),
                    "last_activity_after": RustInstant.format(frozen.lastActivityAfter),
                    // Runtime replaces this only after source/public proof.
                    "revision_after": NSNull()] as WireObject
            }
        }
        result.fields = ["task_before": before,
            "created_task_revision": wireNull(undo.createdTaskAfter?.serverRevision.map { String($0) }),
            "receipt_kind": wireNull(undo.receiptWritten?.rawValue),
            "local_before": ["receipt_replaced": replaced, "session_before": previousSession] as WireObject]
        return result
    }

    private static func bulkFields(_ bulk: BulkReleaseRecord, tasks: [TaskID: TaskRecord],
                                   ids: inout RustIDTable, now: Date) -> [Any]? {
        guard now < bulk.createdAt.addingTimeInterval(ReviewRetention.snapshotWindow), bulk.undoneAt == nil else { return nil }
        var fields: [Any] = []
        for item in bulk.released {
            let sourceMatches = item.taskAfter.matches(tasks[item.taskID])
            if sourceMatches && (!item.clockKnown || (item.previousState == .next && item.clockBefore == nil)) {
                fields.append(NSNull()); continue
            }
            var before: Any = NSNull()
            if item.clockKnown, let clock = item.clockBefore {
                before = clockBefore(clock, ids: &ids)
            }
            var receipt: Any = NSNull()
            if let previous = item.receiptReplaced {
                // Bulk preserves the server revision but not the original
                // write instant. An instant constraint cannot be reconstructed.
                let revisionMatches = previous.taskRevision == nil || previous.taskRevision == item.taskAfter.serverRevision
                receipt = ["receipt": RustReadSet.receipt(previous, &ids),
                           "task_was_unchanged": previous.taskUpdatedAt == nil && revisionMatches] as WireObject
            }
            fields.append(["previous_state": item.previousState.rawValue, "clock_before": before,
                "local_receipt_replaced": receipt,
                "local_source_task_unchanged": sourceMatches] as WireObject)
        }
        return fields
    }

    private static func clockBefore(_ released: ReleasedClock, ids: inout RustIDTable) -> WireObject {
        let clock = released.clock
        return ["formulation_id": ids.formulation(clock.id), "started_at": RustInstant.format(clock.startedAt),
                "extended_at": wireInstant(clock.extendedAt), "extension_reason": wireNull(clock.extensionReason),
                "park_floor_at": wireInstant(clock.parkFloorAt), "stalled_before": max(released.stalledBefore, 0)]
    }

    private static func parkFields(_ marker: ParkMarker, ids: inout RustIDTable) -> WireObject? {
        guard let before = marker.clockBefore else { return nil }
        let clock = clockBefore(ReleasedClock(clock: before, stalledBefore: marker.stalledBefore), ids: &ids)
        return ["from_revision": wireNull(marker.fromRevision.map { String($0) }), "clock_before": clock]
    }

    private static func decode<T: Decodable>(_ type: T.Type, _ object: WireObject) throws -> T {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let text = try decoder.singleValueContainer().decode(String.self)
            guard let date = RustInstant.parse(text) else { throw RustDomainError.malformedResult }
            return date
        }
        return try decoder.decode(type, from: RustJSON.data(object))
    }
}
