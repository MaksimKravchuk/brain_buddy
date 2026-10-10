import Foundation

// The wire codec of `RustDomainFacade` (spec 026, T017): Foundation-only JSON values in
// the shapes of `rust/crates/bb-domain` (snake_case keys, decimal-string counters, RFC 3339
// instants). Everything here is synchronous and pure; the values are built and read inside
// one call and never held across a suspension point.

/// A JSON object under construction or read back from the Rust core.
typealias WireObject = [String: Any]

/// Why a call through the Rust core produced no usable Swift result. Never carries
/// payload text.
public enum RustDomainError: Error, Equatable, Sendable {
    /// The core refused the command or query with a reason that has no
    /// `GTDValidationError` of its own.
    case refused(reason: String, field: String?)
    /// `ApplyMode.replay` is the legacy outbox's re-run over newer server state. In the
    /// migrated epoch the Rust runtime owns replay, so the facade does not decide it.
    case replayIsRuntimeOwned
    /// A destination or option the shared queries do not answer. Nothing falls back to
    /// the Swift query code in the migrated epoch.
    case unsupportedQuery(String)
    /// The core's answer did not have the documented shape.
    case malformedResult
}

// MARK: - Reading values

extension Dictionary where Key == String, Value == Any {
    func string(_ key: String) throws -> String {
        guard let value = self[key] as? String else { throw RustDomainError.malformedResult }
        return value
    }

    /// Nil when the member is absent or `null`.
    func optionalString(_ key: String) -> String? { self[key] as? String }

    func int(_ key: String) throws -> Int {
        guard let value = self[key] as? Int else { throw RustDomainError.malformedResult }
        return value
    }

    func bool(_ key: String) throws -> Bool {
        guard let value = self[key] as? Bool else { throw RustDomainError.malformedResult }
        return value
    }

    /// A decimal-string counter.
    func counter(_ key: String) throws -> Int {
        guard let text = self[key] as? String, let value = Int(text) else { throw RustDomainError.malformedResult }
        return value
    }

    func optionalCounter(_ key: String) -> Int? {
        guard let text = self[key] as? String else { return nil }
        return Int(text)
    }

    func object(_ key: String) throws -> WireObject {
        guard let value = self[key] as? WireObject else { throw RustDomainError.malformedResult }
        return value
    }

    func optionalObject(_ key: String) -> WireObject? { self[key] as? WireObject }

    func objects(_ key: String) throws -> [WireObject] {
        guard let value = self[key] as? [WireObject] else { throw RustDomainError.malformedResult }
        return value
    }

    func strings(_ key: String) throws -> [String] {
        guard let value = self[key] as? [String] else { throw RustDomainError.malformedResult }
        return value
    }

    func optionalStrings(_ key: String) -> [String]? { self[key] as? [String] }

    /// An instant member. `existing` is returned when it prints as the same text, so a
    /// round trip through the wire does not change a `Date` the core did not touch.
    func optionalInstant(_ key: String, keeping existing: Date? = nil) throws -> Date? {
        guard let text = self[key] as? String else { return nil }
        if let existing, RustInstant.format(existing) == text { return existing }
        guard let date = RustInstant.parse(text) else { throw RustDomainError.malformedResult }
        return date
    }

    func instant(_ key: String, keeping existing: Date? = nil) throws -> Date {
        guard let date = try optionalInstant(key, keeping: existing) else { throw RustDomainError.malformedResult }
        return date
    }
}

// MARK: - Writing values

/// `null` for a missing value.
func wireNull(_ value: Any?) -> Any { value ?? NSNull() }

func wireInstant(_ date: Date?) -> Any {
    guard let date else { return NSNull() }
    return RustInstant.format(date)
}

enum RustJSON {
    static func data(_ value: Any) throws -> Data {
        guard JSONSerialization.isValidJSONObject(value) else { throw RustDomainError.malformedResult }
        return try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
    }

    static func object(_ data: Data) throws -> WireObject {
        guard let value = try JSONSerialization.jsonObject(with: data) as? WireObject else {
            throw RustDomainError.malformedResult
        }
        return value
    }

    static func array(_ data: Data) throws -> [Any] {
        guard let value = try JSONSerialization.jsonObject(with: data) as? [Any] else {
            throw RustDomainError.malformedResult
        }
        return value
    }
}

// MARK: - Instants

/// RFC 3339 UTC instants as the core reads and writes them: `...Z`, with microseconds
/// only when non-zero. Integer arithmetic over `CalendarDay`; no formatter, no locale.
enum RustInstant {
    static func format(_ date: Date) -> String {
        let micros = Int((date.timeIntervalSince1970 * 1_000_000).rounded())
        var seconds = micros / 1_000_000
        var fraction = micros % 1_000_000
        if fraction < 0 {
            fraction += 1_000_000
            seconds -= 1
        }
        var days = seconds / 86_400
        var secondOfDay = seconds % 86_400
        if secondOfDay < 0 {
            secondOfDay += 86_400
            days -= 1
        }
        let day = CalendarDay(clampingDayNumber: days)
        var text = "\(day.isoString)T\(pad(secondOfDay / 3600, 2)):\(pad(secondOfDay % 3600 / 60, 2)):\(pad(secondOfDay % 60, 2))"
        if fraction != 0 { text += "." + pad(fraction, 6) }
        return text + "Z"
    }

    /// `YYYY-MM-DDTHH:MM:SS[.f...]` followed by `Z` or `±HH:MM`.
    static func parse(_ text: String) -> Date? {
        let s = Array(text.utf8)
        guard s.count >= 20, let day = CalendarDay(isoString: String(decoding: s[0..<10], as: UTF8.self)),
            s[10] == UInt8(ascii: "T") || s[10] == UInt8(ascii: "t"),
            s[13] == UInt8(ascii: ":"), s[16] == UInt8(ascii: ":"),
            let hour = number(s, 11, 2), let minute = number(s, 14, 2), let second = number(s, 17, 2),
            hour < 24, minute < 60, second < 61
        else { return nil }
        var index = 19
        var nanoseconds = 0
        if s[index] == UInt8(ascii: ".") {
            index += 1
            var digits = 0
            while index < s.count, (48...57).contains(s[index]) {
                if digits < 9 {
                    nanoseconds = nanoseconds * 10 + Int(s[index] - 48)
                    digits += 1
                }
                index += 1
            }
            guard digits > 0 else { return nil }
            for _ in digits..<9 { nanoseconds *= 10 }
        }
        guard index < s.count else { return nil }
        var offset = 0
        switch s[index] {
        case UInt8(ascii: "Z"), UInt8(ascii: "z"):
            guard index + 1 == s.count else { return nil }
        case UInt8(ascii: "+"), UInt8(ascii: "-"):
            guard s.count == index + 6, s[index + 3] == UInt8(ascii: ":"), let hours = number(s, index + 1, 2),
                let minutes = number(s, index + 4, 2)
            else { return nil }
            offset = (hours * 3600 + minutes * 60) * (s[index] == UInt8(ascii: "-") ? -1 : 1)
        default:
            return nil
        }
        let whole = day.dayNumber * 86_400 + hour * 3600 + minute * 60 + second - offset
        return Date(timeIntervalSince1970: Double(whole) + Double(nanoseconds) / 1_000_000_000)
    }

    private static func number(_ s: [UInt8], _ start: Int, _ count: Int) -> Int? {
        guard start + count <= s.count else { return nil }
        var value = 0
        for index in start..<(start + count) {
            guard (48...57).contains(s[index]) else { return nil }
            value = value * 10 + Int(s[index] - 48)
        }
        return value
    }

    private static func pad(_ value: Int, _ width: Int) -> String {
        let digits = String(value)
        return String(repeating: "0", count: max(0, width - digits.count)) + digits
    }
}

// MARK: - Identifiers

/// The canonical wire identifier of every record, in both directions of one call.
///
/// The core refuses a new record whose ID is not `<prefix>_<lowercased UUID>`, while the
/// Swift state keys records by the bare UUID `EntityID.random()` mints. The mapping from the
/// bare form to the prefixed one is deterministic and is applied everywhere an identifier is
/// sent: in the read set (as the record's own ID and in every reference to it) and in the
/// command (target, payload and minted IDs). A create of an ID the state already holds then
/// meets the same wire ID in the read set and is refused as `id_already_exists`, instead of
/// creating a second record the Swift state would overwrite. An ID that is already prefixed,
/// or of no shape the core could accept, crosses unchanged.
struct RustIDTable {
    /// Prefixed wire ID to the Swift ID it stands for.
    private(set) var known: [String: String] = [:]

    init() {}

    mutating func wire(_ raw: String, prefix: String) -> String {
        if ClientID.isValid(raw, prefix: prefix) { return raw }
        let wire = "\(prefix)_\(raw)"
        guard ClientID.isValid(wire, prefix: prefix) else { return raw }
        known[wire] = raw
        return wire
    }

    /// `null` for no identifier.
    mutating func optional(_ raw: String?, prefix: String) -> Any {
        guard let raw else { return NSNull() }
        return wire(raw, prefix: prefix)
    }

    /// The Swift identifier a wire identifier stands for; one that was never mapped is its own.
    func swift(_ wire: String) -> String { known[wire] ?? wire }

    mutating func task(_ id: TaskID) -> String { wire(id.rawValue, prefix: "task") }
    mutating func project(_ id: ProjectID) -> String { wire(id.rawValue, prefix: "project") }
    mutating func tag(_ id: TagID) -> String { wire(id.rawValue, prefix: "tag") }
    mutating func subtask(_ id: SubtaskID) -> String { wire(id.rawValue, prefix: "subtask") }
    mutating func comment(_ id: CommentID) -> String { wire(id.rawValue, prefix: "comment") }
    mutating func formulation(_ id: FormulationID) -> String { wire(id.rawValue, prefix: "form") }
    mutating func decision(_ id: DecisionID) -> String { wire(id.rawValue, prefix: "decision") }
    mutating func bulk(_ id: BulkID) -> String { wire(id.rawValue, prefix: "bulk") }
    mutating func session(_ id: ReviewSessionID) -> String { wire(id.rawValue, prefix: "review") }
    mutating func progress(_ id: ProgressID) -> String { wire(id.rawValue, prefix: "progress") }
}

// MARK: - The read set

/// The Swift state as the core's read set. The whole state is encoded: the device holds one
/// owner's rows and the rules read what they need. Every identifier is the canonical wire ID
/// (`RustIDTable`).
enum RustReadSet {
    static func make(_ state: GTDState, actorID: String, ids: inout RustIDTable) -> WireObject {
        var tasks: WireObject = [:]
        var subtasks: WireObject = [:]
        var comments: WireObject = [:]
        var parkAcks: [WireObject] = []
        for task in state.tasks.values {
            let taskWire = ids.task(task.id)
            tasks[taskWire] = self.task(task, &ids)
            for subtask in task.subtasks {
                subtasks[ids.subtask(subtask.id)] = self.subtask(subtask, of: taskWire, &ids)
            }
            for comment in task.comments {
                comments[ids.comment(comment.id)] = self.comment(comment, of: taskWire, actorID: actorID, &ids)
            }
            // A park the person has not seen is a row of its own in the core.
            if let park = task.parked, !state.review.hasSeen(task.id, park) {
                parkAcks.append(
                    parkAck(task: taskWire, formulation: ids.formulation(park.formulationID), parked: park.at, seen: nil))
            }
        }
        var projects: WireObject = [:]
        for project in state.projects.values { projects[ids.project(project.id)] = self.project(project, &ids) }
        var tags: WireObject = [:]
        for tag in state.tags.values { tags[ids.tag(tag.id)] = self.tag(tag, &ids) }

        let review = state.review
        for ack in review.parkAcks {
            let parked = ack.parkedAt ?? state.tasks[ack.taskID]?.parked?.at ?? Date(timeIntervalSince1970: 0)
            parkAcks.append(
                parkAck(task: ids.task(ack.taskID), formulation: ids.formulation(ack.formulationID), parked: parked, seen: parked))
        }
        var sessions: WireObject = [:]
        var queues: WireObject = [:]
        for session in review.sessions.values {
            let sessionWire = ids.session(session.id)
            sessions[sessionWire] = self.session(session, &ids)
            if session.decisionQueue != nil || !session.setAsideTaskIDs.isEmpty {
                queues[sessionWire] = queue(session, decisions: review.decisions.values, &ids)
            }
        }
        var decisions: WireObject = [:]
        for decision in review.decisions.values { decisions[ids.decision(decision.id)] = self.decision(decision, &ids) }
        var bulkReleases: WireObject = [:]
        for bulk in review.bulkReleases.values { bulkReleases[ids.bulk(bulk.id)] = self.bulkRelease(bulk, &ids) }
        var receipts: [WireObject] = []
        for item in review.receipts { receipts.append(receipt(item, &ids)) }

        var readSet: WireObject = [
            "tasks": tasks, "projects": projects, "tags": tags, "subtasks": subtasks, "comments": comments,
            "sessions": sessions, "decision_queues": queues, "decisions": decisions, "receipts": receipts,
            "park_acks": parkAcks, "bulk_releases": bulkReleases,
            "consents": review.navigatorConsents.values.map(consent),
        ]
        // Settings nobody changed are "not stored" for the rules, which then use their defaults.
        if review.settings != ReviewSettings() { readSet["settings"] = settings(review.settings) }
        return readSet
    }

    // MARK: Tasks and organization

    static func task(_ task: TaskRecord, _ ids: inout RustIDTable) -> WireObject {
        [
            "id": ids.task(task.id), "title": task.title, "details": wireNull(task.details),
            "state": task.state.rawValue, "project_id": ids.optional(task.projectID?.rawValue, prefix: "project"),
            "tag_ids": task.tagIDs.map { ids.tag($0) }, "due_date": wireNull(task.dueDate?.isoString),
            "priority": task.priority.rawValue, "waiting_for": wireNull(task.waitingFor),
            "waiting_since": wireInstant(task.waitingSince), "order_key": String(max(task.orderKey, 0)),
            "source_capture_ids": [String](), "created_at": RustInstant.format(task.createdAt),
            "updated_at": RustInstant.format(task.updatedAt), "completed_at": wireInstant(task.completedAt),
            "cancelled_at": wireInstant(task.cancelledAt), "revision": String(task.serverRevision ?? 0),
            "consecutive_stalled_formulations": max(task.consecutiveStalledFormulations, 0),
            "formulation": wireNull(task.formulation.map { clock($0, &ids) }),
            "parked": wireNull(task.parked.map { park($0, &ids) }),
        ]
    }

    static func clock(_ clock: FormulationClock, _ ids: inout RustIDTable) -> WireObject {
        [
            "id": ids.formulation(clock.id), "started_at": RustInstant.format(clock.startedAt),
            "extended_at": wireInstant(clock.extendedAt), "extension_reason": wireNull(clock.extensionReason),
            "park_floor_at": wireInstant(clock.parkFloorAt),
        ]
    }

    /// The public park marker, plus the private clock before it when this device parked the task.
    static func park(_ marker: ParkMarker, _ ids: inout RustIDTable) -> WireObject {
        var wire: WireObject = [
            "at": RustInstant.format(marker.at), "formulation_id": ids.formulation(marker.formulationID),
        ]
        if let revision = marker.fromRevision, let before = marker.clockBefore {
            wire["private"] = [
                "from_revision": String(max(revision, 0)),
                "clock_before": [
                    "formulation_id": NSNull(), "started_at": RustInstant.format(before.startedAt),
                    "extended_at": wireInstant(before.extendedAt), "extension_reason": wireNull(before.extensionReason),
                    "park_floor_at": wireInstant(before.parkFloorAt), "stalled_before": max(marker.stalledBefore, 0),
                ] as WireObject,
            ] as WireObject
        }
        return wire
    }

    static func project(_ project: ProjectRecord, _ ids: inout RustIDTable) -> WireObject {
        [
            "id": ids.project(project.id), "name": project.name, "color": wireNull(project.color),
            "state": project.state.rawValue, "revision": String(project.serverRevision ?? 0),
            "desired_outcome": wireNull(project.desiredOutcome), "archived_at": wireInstant(project.archivedAt),
            "archived_before_lossless": project.archivedBeforeLossless,
            "created_at": RustInstant.format(project.createdAt),
        ]
    }

    static func tag(_ tag: TagRecord, _ ids: inout RustIDTable) -> WireObject {
        [
            "id": ids.tag(tag.id), "name": tag.name, "state": tag.state.rawValue,
            "revision": String(tag.serverRevision ?? 0), "created_at": RustInstant.format(tag.createdAt),
        ]
    }

    static func subtask(_ subtask: SubtaskRecord, of task: String, _ ids: inout RustIDTable) -> WireObject {
        [
            "id": ids.subtask(subtask.id), "task_id": task, "title": subtask.title,
            "state": subtask.state.rawValue, "order_key": String(max(subtask.orderKey, 0)),
            "revision": String(subtask.serverRevision ?? 0),
        ]
    }

    static func comment(
        _ comment: CommentRecord, of task: String, actorID: String, _ ids: inout RustIDTable
    ) -> WireObject {
        [
            "id": ids.comment(comment.id), "task_id": task, "body": comment.body,
            "actor_id": comment.authorID ?? actorID, "created_at": RustInstant.format(comment.createdAt),
            "edited_at": wireInstant(comment.editedAt), "revision": String(comment.serverRevision ?? 0),
        ]
    }

    // MARK: Review

    static func settings(_ settings: ReviewSettings) -> WireObject {
        [
            "threshold_days": settings.thresholdDays, "review_weekday": settings.reviewWeekday,
            "review_time": settings.reviewTime, "time_zone": settings.timeZone,
            "onboarded_at": wireInstant(settings.onboardedAt), "activated_at": wireInstant(settings.activatedAt),
            "owner_park_floor_at": wireInstant(settings.ownerParkFloorAt),
            "revision": String(settings.revision ?? 0),
        ]
    }

    static func session(_ session: ReviewSession, _ ids: inout RustIDTable) -> WireObject {
        var counts: WireObject = [:]
        for counter in SessionCounter.allCases { counts[counter.rawValue] = session.counts[counter] }
        var steps: WireObject = [:]
        for (step, status) in session.steps { steps[step.rawValue] = status.rawValue }
        var seconds: WireObject = [:]
        for (step, value) in session.activeSecondsByStep { seconds[step.rawValue] = max(value, 0) }
        return [
            "id": ids.session(session.id), "mode": session.mode.rawValue, "entry": session.entry.rawValue,
            "origin": session.origin.rawValue, "status": session.status.rawValue,
            "started_at": RustInstant.format(session.startedAt),
            "last_activity_at": RustInstant.format(session.lastActivityAt), "ended_at": wireInstant(session.endedAt),
            "current_step": wireNull(session.currentStep?.rawValue), "steps": steps,
            "active_seconds_by_step": seconds, "counts": counts, "set_aside_count": max(session.setAsideCount, 0),
            "qualifying_activity": session.qualifyingActivity, "clear_start": wireNull(session.clearStart?.rawValue),
            "revision": String(session.revision ?? 0),
        ]
    }

    /// The decided cards of a run are the decisions made in it.
    static func queue(
        _ session: ReviewSession, decisions: Dictionary<DecisionID, ReviewDecision>.Values, _ ids: inout RustIDTable
    ) -> WireObject {
        let decided = decisions.filter { $0.sessionID == session.id }
            .sorted { ($0.decidedAt, $0.id) < ($1.decidedAt, $1.id) }
            .map { ids.task($0.taskID) }
        return [
            "session_id": ids.session(session.id),
            "task_ids": wireNull(session.decisionQueue.map { $0.map { ids.task($0) } }),
            "decided_task_ids": decided, "set_aside_task_ids": session.setAsideTaskIDs.map { ids.task($0) },
        ]
    }

    /// The public face of a decision: the Undo snapshot is the authoritative side's.
    static func decision(_ decision: ReviewDecision, _ ids: inout RustIDTable) -> WireObject {
        let after = decision.taskAfter.serverRevision ?? 0
        let before = decision.undo?.taskBefore.serverRevision ?? after
        return [
            "id": ids.decision(decision.id), "type": decision.type.rawValue, "task_id": ids.task(decision.taskID),
            "session_id": ids.optional(decision.sessionID?.rawValue, prefix: "review"),
            "decided_at": RustInstant.format(decision.decidedAt),
            "substantive": wireNull(decision.substantive), "stall_reason": wireNull(decision.stallReason?.rawValue),
            "ai_use": decision.aiUse.rawValue, "yielded_auto_park": decision.yieldedAutoPark,
            "formulation_id": ids.optional(decision.formulationID?.rawValue, prefix: "form"),
            "task_revision_before": String(max(before, 0)), "task_revision_after": String(max(after, 0)),
            "created_task_id": ids.optional(decision.undo?.createdTaskID?.rawValue, prefix: "task"),
            "navigator_request_id": NSNull(), "review_counts_as": decision.type.countsAs.rawValue,
            "client_decided_at": NSNull(), "reason_text": wireNull(decision.reasonText),
            "undo_available_until": NSNull(),
        ]
    }

    static func receipt(_ receipt: ReviewReceipt, _ ids: inout RustIDTable) -> WireObject {
        [
            "task_id": ids.task(receipt.taskID), "kind": receipt.kind.rawValue,
            "hidden_until": RustInstant.format(receipt.hiddenUntil), "task_revision": String(max(receipt.taskRevision ?? 0, 0)),
            "reviewed_at": RustInstant.format(receipt.reviewedAt), "source": receipt.source.rawValue,
            "decision_id": ids.optional(receipt.decisionID?.rawValue, prefix: "decision"),
            "bulk_id": ids.optional(receipt.bulkID?.rawValue, prefix: "bulk"),
        ]
    }

    static func parkAck(task: String, formulation: String, parked: Date, seen: Date?) -> WireObject {
        [
            "task_id": task, "formulation_id": formulation,
            "parked_at": RustInstant.format(parked), "seen_at": wireInstant(seen), "returned_at": NSNull(),
        ]
    }

    static func bulkRelease(_ bulk: BulkReleaseRecord, _ ids: inout RustIDTable) -> WireObject {
        let undo: Any
        if let result = bulk.undoResult {
            undo =
                [
                    "restored": result.restored.map { ids.task($0) },
                    "skipped": result.skipped.map { ["task_id": ids.task($0), "reason": "stale"] },
                ] as WireObject
        } else {
            undo = NSNull()
        }
        return [
            "id": ids.bulk(bulk.id), "kind": bulk.kind.rawValue,
            "session_id": ids.optional(bulk.sessionID?.rawValue, prefix: "review"),
            "created_at": RustInstant.format(bulk.createdAt), "undone_at": wireInstant(bulk.undoneAt),
            "released": bulk.released.map {
                ["task_id": ids.task($0.taskID), "revision_after": String(max($0.taskAfter.serverRevision ?? 0, 0))]
            },
            "skipped": bulk.skipped.map { ["task_id": ids.task($0.taskID), "reason": $0.reason] },
            "undo": undo,
        ]
    }

    static func consent(_ consent: NavigatorConsent) -> WireObject {
        var grant: Any = NSNull()
        if let grantedAt = consent.grantedAt {
            grant =
                [
                    "granted_at": RustInstant.format(grantedAt), "revoked_at": wireInstant(consent.revokedAt),
                    "consent_text_version": consent.consentTextVersion ?? 1,
                ] as WireObject
        }
        return ["provider": consent.provider, "consent": grant]
    }
}
