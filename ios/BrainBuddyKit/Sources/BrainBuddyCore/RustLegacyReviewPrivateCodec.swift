import Foundation

/// One migration-only prepared page. Public Review records contain none of it.
public struct RustWorkspaceLegacyReviewPrivatePreparation: Sendable {
    public let payload: Data
}

extension RustDomainFacade {
    /// Prepare one bounded capture page independently. Rust owns contiguous
    /// accumulation and finalization; Swift never rebuilds the complete source.
    public func workspacePrepareLegacyReviewPrivate(_ page: Data, now: Date) throws
        -> RustWorkspaceLegacyReviewPrivatePreparation {
        guard page.count <= RustLegacyReviewPrivateCodec.byteLimit else { throw RustDomainError.malformedResult }
        let object = try RustJSON.object(page)
        let bindings = try workspaceIdentityBindings(from: RustJSON.data(object["aliases"] ?? []))
        let prepared = try RustLegacyReviewPrivateCodec.preparePage(object, bindings: bindings, now: now)
        return RustWorkspaceLegacyReviewPrivatePreparation(payload: try RustJSON.data(prepared))
    }
}

/// Foundation-only mapping of typed source components. Runtime capture owns all
/// digests, pins, cursors and source omission; none are inferred by this codec.
enum RustLegacyReviewPrivateCodec {
    static let byteLimit = 8 * 1024 * 1024

    static func preparePage(_ page: WireObject, bindings: [RustWorkspaceIdentityBinding], now: Date) throws -> WireObject {
        let header = try page.object("header")
        let binding = try header.object("binding")
        let component = try page.string("component")
        let offset = try page.int("offset"), count = try page.int("count")
        let lengths = try header.object("component_lengths")
        let length = try lengths.int(component)
        guard try header.int("codec_version") == 1, offset >= 0, count >= 0,
              offset <= length, count <= length - offset, count <= 200,
              try page.int("ordinal") >= 0,
              try RustJSON.data(page).count <= byteLimit,
              try copiedCost(page) <= 200 else { throw RustDomainError.malformedResult }
        var result: WireObject = [:]
        for key in ["header", "ordinal", "component", "offset", "count", "fragment_sha256", "task_public", "session_public"] {
            guard let value = page[key] else { throw RustDomainError.malformedResult }
            result[key] = value
        }
        result["private"] = NSNull()
        result["task_before_park"] = NSNull()
        result["evidence"] = emptyEvidence
        // Expired content is filtered by capture before FFI. This second guard
        // handles expiry between capture and preparation without renewing TTL.
        if let deadline = try header.optionalInstant("deadline"), now >= deadline { return result }
        let taskSources = try page.object("source_tasks")
        for value in taskSources.values {
            guard let witness = value as? WireObject,
                  Set(witness.keys).isSubset(of: ["id", "serverRevision", "updatedAt"]) else { throw RustDomainError.malformedResult }
        }
        if let session = page.optionalObject("source_session") {
            guard Set(session.keys).isSubset(of: ["id", "lastActivityAt"]) else { throw RustDomainError.malformedResult }
        }
        let witnesses = try decode([TaskID: RustLegacyTaskStampWitness].self, taskSources)
        guard witnesses.allSatisfy({ $0.key == $0.value.id }) else { throw RustDomainError.malformedResult }
        switch component {
        case "decision_scalar":
            guard count == 1, offset == 0, try binding.string("source_kind") == "decision" else { throw RustDomainError.malformedResult }
            let source = try page.object("source")
            if let before = source.optionalObject("undo")?.optionalObject("taskBefore") {
                guard before["tagIDs"] == nil, before["subtasks"] == nil, before["comments"] == nil,
                      before["childrenSyncedAt"] == nil else { throw RustDomainError.malformedResult }
            }
            let decision = try decode(RustLegacyDecisionSource.self, source)
            let publicRecord = try page.object("public")
            var forms = Set([decision.formulationID?.rawValue, decision.undo?.taskBefore.formulation?.id.rawValue,
                decision.undo?.taskBefore.parked?.formulationID.rawValue,
                decision.undo?.taskBefore.parked?.clockBefore?.id.rawValue].compactMap { $0 })
            if let marker = decision.undo?.taskBefore.parked { forms.insert(marker.formulationID.rawValue) }
            var ids = RustIDTable(bindings: bindings, canonicalFormulationIDs: forms)
            try requireIdentity(binding, sourceID: decision.id.rawValue, canonicalID: ids.decision(decision.id), type: "review_decision")
            guard ids.task(decision.taskID) == (try publicRecord.string("task_id")) else { throw RustDomainError.malformedResult }
            let mapped = try decisionFields(decision, witnesses: witnesses, session: page.optionalObject("source_session"),
                publicRecord: publicRecord, ids: &ids, now: now)
            result["private"] = mapped.fields.map { ["kind": "decision", "fields": $0] as Any } ?? NSNull()
            result["evidence"] = mapped.evidence
            if mapped.fields != nil, let marker = decision.undo?.taskBefore.parked {
                result["task_before_park"] = parkFields(marker, ids: &ids).map { $0 as Any } ?? NSNull()
            }
        case "decision_tags":
            guard try binding.string("source_kind") == "decision" else { throw RustDomainError.malformedResult }
            let tags = try decode([TagID].self, requiredSource(page))
            guard tags.count == count else { throw RustDomainError.malformedResult }
            var ids = RustIDTable(bindings: bindings)
            result["private"] = ["kind": "decision_tags", "fields": tags.map { ids.tag($0) }] as WireObject
        case "bulk_released":
            guard try binding.string("source_kind") == "bulk_release" else { throw RustDomainError.malformedResult }
            let bulk = try decode(BulkPageSource.self, page.object("source"))
            let publicRecord = try page.object("public")
            let publicRows = try publicRecord.objects("released")
            guard bulk.released.count == count, publicRows.count == count else { throw RustDomainError.malformedResult }
            var ids = RustIDTable(bindings: bindings,
                canonicalFormulationIDs: Set(bulk.released.compactMap { $0.clockBefore?.clock.id.rawValue }))
            try requireIdentity(binding, sourceID: bulk.id.rawValue, canonicalID: ids.bulk(bulk.id), type: "review_bulk_release")
            for (item, row) in zip(bulk.released, publicRows) {
                guard ids.task(item.taskID) == (try row.string("task_id")) else { throw RustDomainError.malformedResult }
            }
            if now < bulk.createdAt.addingTimeInterval(ReviewRetention.snapshotWindow), bulk.undoneAt == nil {
                result["private"] = ["kind": "bulk", "fields": bulkFields(bulk.released, witnesses: witnesses, ids: &ids)] as WireObject
            }
        case "task_park":
            guard count == 1, offset == 0, try binding.string("source_kind") == "task_park" else { throw RustDomainError.malformedResult }
            let task = try decode(RustLegacyParkSource.self, page.object("source"))
            var ids = RustIDTable(bindings: bindings,
                canonicalFormulationIDs: Set([task.parked?.formulationID.rawValue, task.parked?.clockBefore?.id.rawValue].compactMap { $0 }))
            try requireIdentity(binding, sourceID: task.id.rawValue, canonicalID: ids.task(task.id), type: "task")
            let fields = task.parked.flatMap { parkFields($0, ids: &ids) }
            result["private"] = fields.map { ["kind": "task_park", "fields": $0] as Any } ?? NSNull()
            result["evidence"] = ["task_matches": task.stamp.matchesLegacyWitness(witnesses[task.id]),
                "created_task_matches": NSNull(), "session_matches": NSNull()] as WireObject
        case "session_scalar":
            guard count == 1, offset == 0, try binding.string("source_kind") == "session" else { throw RustDomainError.malformedResult }
            let source = try page.object("source")
            guard source["appliedProgress"] == nil, source["setAsideTaskIDs"] == nil,
                  source["decisionQueue"] == nil else { throw RustDomainError.malformedResult }
            let session = try decode(RustLegacySessionScalar.self, source)
            var ids = RustIDTable(bindings: bindings)
            try requireIdentity(binding, sourceID: session.id.rawValue, canonicalID: ids.session(session.id), type: "review_session")
            result["private"] = ["kind": "session", "fields": ["applied_progress": [:] as WireObject,
                "finished_empty": [String](), "local_imported_progress": [String]()] as WireObject] as WireObject
        case "session_progress":
            guard try binding.string("source_kind") == "session" else { throw RustDomainError.malformedResult }
            let progress = try decode([ProgressID].self, requiredSource(page))
            guard progress.count == count else { throw RustDomainError.malformedResult }
            var ids = RustIDTable(bindings: bindings)
            result["private"] = ["kind": "session_progress", "fields": progress.map { ids.progress($0) }] as WireObject
        case "settings":
            guard count == 1, offset == 0, try binding.string("source_kind") == "settings",
                  try binding.string("entity_type") == "review_settings",
                  try binding.strings("record_key").isEmpty else { throw RustDomainError.malformedResult }
            let settings = try decode(ReviewSettings.self, page.object("source"))
            result["private"] = ["kind": "settings", "fields": ["last_effective_sweep_at": NSNull(),
                "threshold_changed_at": wireInstant(settings.thresholdChangedAt)] as WireObject] as WireObject
        default: throw RustDomainError.malformedResult
        }
        guard try RustJSON.data(result).count <= byteLimit else { throw RustDomainError.malformedResult }
        return result
    }

    private static var emptyEvidence: WireObject {
        ["task_matches": NSNull(), "created_task_matches": NSNull(), "session_matches": NSNull()]
    }

    private struct DecisionFields {
        var fields: WireObject?
        var evidence: WireObject
    }

    private struct BulkPageSource: Decodable {
        let id: BulkID
        let createdAt: Date
        let undoneAt: Date?
        let released: [BulkReleasedTask]
    }

    private static func decisionFields(_ decision: RustLegacyDecisionSource,
        witnesses: [TaskID: RustLegacyTaskStampWitness], session: WireObject?, publicRecord: WireObject,
        ids: inout RustIDTable, now: Date) throws -> DecisionFields {
        var evidence = emptyEvidence
        evidence["task_matches"] = decision.taskAfter.matchesLegacyWitness(witnesses[decision.taskID])
        if let id = decision.undo?.createdTaskID {
            evidence["created_task_matches"] = decision.undo?.createdTaskAfter?.matchesLegacyWitness(witnesses[id]) ?? false
        }
        var result = DecisionFields(evidence: evidence)
        guard now < decision.decidedAt.addingTimeInterval(ReviewRetention.snapshotWindow), let undo = decision.undo else { return result }
        guard undo.taskBefore.id == decision.taskID else { throw RustDomainError.malformedResult }
        let before = undo.taskBefore.wire(revision: try publicRecord.string("task_revision_before"), ids: &ids)
        var replaced: Any = NSNull()
        if let receipt = undo.receiptReplaced {
            replaced = ["receipt": RustReadSet.receipt(receipt, &ids),
                "task_was_unchanged": receipt.taskIsUnchanged(undo.taskBefore.stampWitness)] as WireObject
        }
        var previousSession: Any = NSNull()
        if let frozen = undo.sessionBefore, let session, let sessionID = decision.sessionID {
            let original = try decode(RustLegacySessionWitness.self, session)
            guard original.id == sessionID else { throw RustDomainError.malformedResult }
            let matches = original.lastActivityAt == frozen.lastActivityAfter
            result.evidence["session_matches"] = matches
            if matches {
                previousSession = ["qualifying_activity": frozen.qualifyingActivity,
                    "last_activity_at": RustInstant.format(frozen.lastActivityAt),
                    "last_activity_after": RustInstant.format(frozen.lastActivityAfter), "revision_after": NSNull()] as WireObject
            }
        }
        result.fields = ["task_before": before,
            "created_task_revision": wireNull(undo.createdTaskAfter?.serverRevision.map { String($0) }),
            "receipt_kind": wireNull(undo.receiptWritten?.rawValue),
            "local_before": ["receipt_replaced": replaced, "session_before": previousSession] as WireObject]
        return result
    }

    private static func bulkFields(_ released: [BulkReleasedTask], witnesses: [TaskID: RustLegacyTaskStampWitness],
                                   ids: inout RustIDTable) -> [Any] {
        released.map { item -> Any in
            let matches = item.taskAfter.matchesLegacyWitness(witnesses[item.taskID])
            if matches && (!item.clockKnown || (item.previousState == .next && item.clockBefore == nil)) { return NSNull() }
            var receipt: Any = NSNull()
            if let previous = item.receiptReplaced {
                let revisionMatches = previous.taskRevision == nil || previous.taskRevision == item.taskAfter.serverRevision
                receipt = ["receipt": RustReadSet.receipt(previous, &ids),
                    "task_was_unchanged": previous.taskUpdatedAt == nil && revisionMatches] as WireObject
            }
            let clock: Any = item.clockKnown ? wireNull(item.clockBefore.map { clockBefore($0, ids: &ids) }) : NSNull()
            return ["previous_state": item.previousState.rawValue, "clock_before": clock,
                "local_receipt_replaced": receipt, "local_source_task_unchanged": matches] as WireObject
        }
    }

    private static func clockBefore(_ released: ReleasedClock, ids: inout RustIDTable) -> WireObject {
        let clock = released.clock
        return ["formulation_id": ids.formulation(clock.id), "started_at": RustInstant.format(clock.startedAt),
            "extended_at": wireInstant(clock.extendedAt), "extension_reason": wireNull(clock.extensionReason),
            "park_floor_at": wireInstant(clock.parkFloorAt), "stalled_before": max(released.stalledBefore, 0)]
    }

    private static func parkFields(_ marker: ParkMarker, ids: inout RustIDTable) -> WireObject? {
        guard let before = marker.clockBefore else { return nil }
        return ["from_revision": wireNull(marker.fromRevision.map { String($0) }),
            "clock_before": clockBefore(ReleasedClock(clock: before, stalledBefore: marker.stalledBefore), ids: &ids)]
    }

    private static func requireIdentity(_ binding: WireObject, sourceID: String, canonicalID: String, type: String) throws {
        guard sourceID == (try binding.string("source_id")), type == (try binding.string("entity_type")),
              [canonicalID] == (try binding.strings("record_key")) else { throw RustDomainError.malformedResult }
    }

    private static func requiredSource(_ page: WireObject) throws -> Any {
        guard let source = page["source"] else { throw RustDomainError.malformedResult }
        return source
    }

    private static func decode<T: Decodable>(_ type: T.Type, _ value: Any) throws -> T {
        try RustLegacyPrivateSourceDecoding.decode(type, value)
    }

    /// Count copied arrays plus the witness/pin maps, not hidden source rows.
    private static func copiedCost(_ value: Any, key: String? = nil) throws -> Int {
        var count = 0
        if let array = value as? [Any] {
            count = array.count
            for item in array { count += try copiedCost(item) }
        } else if let object = value as? WireObject {
            if key.map({ ["source_tasks", "task_public"].contains($0) }) ?? false { count += object.count }
            if key.map({ ["source_session", "session_public"].contains($0) }) ?? false { count += 1 }
            for (name, item) in object { count += try copiedCost(item, key: name) }
        }
        guard count <= 200 else { throw RustDomainError.malformedResult }
        return count
    }
}
