import Foundation

// A `ChangeSet` of the shared core applied to the Swift state. The core's records are
// after-images of the fields it owns; what only this device knows (children, the last
// open list of a closed task, the undo snapshots of the legacy image) is kept from the
// record already in the state. The core is the revision authority of the migrated epoch,
// so its revisions replace `serverRevision` and `revision`.

enum RustChangeApplier {
    private static let epoch = Date(timeIntervalSince1970: 0)

    /// Applies every change in order.
    /// - Parameters:
    ///   - before: the state the command was decided against.
    ///   - date: the instant the command was decided at.
    static func apply(
        _ changeSet: WireObject, to state: inout GTDState, before: GTDState, at date: Date, ids: RustIDTable,
        actorID: String
    ) throws -> ApplyOutcome {
        var decisions: [DecisionID] = []
        var receipts: [(task: TaskID, kind: ReceiptKind)] = []
        var releases: [BulkID] = []
        for change in try changeSet.objects("changes") {
            let entityType = try change.string("entity_type")
            switch try change.string("operation") {
            case "upsert":
                let value = try change.object("value")
                switch entityType {
                case "task": try upsertTask(value, &state, ids)
                case "project": try upsertProject(value, &state, ids)
                case "tag": try upsertTag(value, &state, ids)
                case "subtask": try upsertSubtask(value, &state, ids)
                case "comment": try upsertComment(value, &state, ids, actorID: actorID)
                case "review_settings": try upsertSettings(value, &state, at: date)
                case "review_session": try upsertSession(value, &state, ids)
                case "review_decision_queue": try upsertQueue(value, &state, ids)
                case "review_decision":
                    decisions.append(try upsertDecision(value, &state, ids))
                case "review_receipt":
                    receipts.append(try upsertReceipt(value, &state, ids))
                case "review_park_ack": try upsertParkAck(value, &state, ids)
                case "review_bulk_release":
                    releases.append(try upsertBulkRelease(value, &state, before: before, ids))
                case "review_navigator_consent": try upsertConsent(value, &state)
                default: break
                }
            case "tombstone":
                try remove(entityType, key: try change.strings("record_key"), from: &state, ids)
            default:
                throw RustDomainError.malformedResult
            }
        }
        stamp(&state, decisions: decisions, receipts: receipts, releases: releases)
        let outcome = try changeSet.string("outcome")
        let applied = changeSet.optionalObject("result")?["applied"] as? Bool
        return outcome == "no_op" || applied == false ? .alreadySatisfied : .applied
    }

    /// The device's own stamps of the tasks the review records name, taken once every task
    /// change is in: what a decision or receipt saw is the task as the command left it.
    private static func stamp(
        _ state: inout GTDState, decisions: [DecisionID], receipts: [(task: TaskID, kind: ReceiptKind)],
        releases: [BulkID]
    ) {
        for id in decisions {
            guard let decision = state.review.decisions[id], let task = state.tasks[decision.taskID] else { continue }
            state.review.decisions[id]?.taskAfter = TaskStamp(task)
        }
        for item in receipts {
            guard let task = state.tasks[item.task], var receipt = state.review.receipt(for: item.task, kind: item.kind)
            else { continue }
            receipt.taskUpdatedAt = task.updatedAt
            state.review.setReceipt(receipt)
        }
        for id in releases {
            guard var record = state.review.bulkReleases[id] else { continue }
            for index in record.released.indices where record.released[index].taskAfter.serverRevision == nil {
                if let task = state.tasks[record.released[index].taskID] {
                    record.released[index].taskAfter = TaskStamp(task)
                }
            }
            state.review.bulkReleases[id] = record
        }
    }

    // MARK: - Helpers

    private static func code<E: RawRepresentable>(_ type: E.Type, _ object: WireObject, _ key: String) throws -> E
    where E.RawValue == String {
        guard let value = E(rawValue: try object.string(key)) else { throw RustDomainError.malformedResult }
        return value
    }

    private static func optionalCode<E: RawRepresentable>(_ type: E.Type, _ object: WireObject, _ key: String) throws
        -> E? where E.RawValue == String
    {
        guard let text = object.optionalString(key) else { return nil }
        guard let value = E(rawValue: text) else { throw RustDomainError.malformedResult }
        return value
    }

    private static func clock(_ object: WireObject, keeping existing: FormulationClock?, ids: RustIDTable) throws
        -> FormulationClock
    {
        FormulationClock(
            id: FormulationID(ids.swift(try object.string("id"))),
            startedAt: try object.instant("started_at", keeping: existing?.startedAt),
            extendedAt: try object.optionalInstant("extended_at", keeping: existing?.extendedAt),
            extensionReason: object.optionalString("extension_reason"),
            parkFloorAt: try object.optionalInstant("park_floor_at", keeping: existing?.parkFloorAt))
    }

    private static func park(_ object: WireObject, existing: ParkMarker?, ids: RustIDTable) throws -> ParkMarker {
        let formulation = FormulationID(ids.swift(try object.string("formulation_id")))
        var marker = ParkMarker(at: try object.instant("at", keeping: existing?.at), formulationID: formulation)
        if let secret = object.optionalObject("private"), let before = secret.optionalObject("clock_before") {
            marker.fromRevision = try secret.counter("from_revision")
            marker.stalledBefore = try before.int("stalled_before")
            marker.clockBefore = FormulationClock(
                id: formulation, startedAt: try before.instant("started_at"),
                extendedAt: try before.optionalInstant("extended_at"),
                extensionReason: before.optionalString("extension_reason"),
                parkFloorAt: try before.optionalInstant("park_floor_at"))
        } else if let existing, existing.formulationID == formulation {
            // The core did not write the private part: what this device holds still stands.
            marker.fromRevision = existing.fromRevision
            marker.clockBefore = existing.clockBefore
            marker.stalledBefore = existing.stalledBefore
        }
        return marker
    }

    // MARK: - Tasks and organization

    private static func upsertTask(_ value: WireObject, _ state: inout GTDState, _ ids: RustIDTable) throws {
        let id = TaskID(ids.swift(try value.string("id")))
        let existing = state.tasks[id]
        var task =
            existing
            ?? TaskRecord(id: id, title: "", state: .inbox, orderKey: 0, createdAt: epoch, updatedAt: epoch)
        let newState = try code(TaskState.self, value, "state")
        // The list a closed task came from is local knowledge the core does not hold.
        if newState.isOpen {
            task.lastOpenList = nil
        } else if let existing, existing.isOpen {
            task.lastOpenList = existing.openList
        }
        task.state = newState
        task.title = try value.string("title")
        task.details = value.optionalString("details").flatMap { $0.isEmpty ? nil : $0 }
        task.projectID = value.optionalString("project_id").map { ProjectID(ids.swift($0)) }
        task.tagIDs = try value.strings("tag_ids").map { TagID(ids.swift($0)) }
        task.dueDate = value.optionalString("due_date").flatMap { CalendarDay(isoString: $0) }
        task.priority = try code(TaskPriority.self, value, "priority")
        task.waitingFor = value.optionalString("waiting_for")
        task.waitingSince = try value.optionalInstant("waiting_since", keeping: existing?.waitingSince)
        task.completedAt = try value.optionalInstant("completed_at", keeping: existing?.completedAt)
        task.cancelledAt = try value.optionalInstant("cancelled_at", keeping: existing?.cancelledAt)
        task.orderKey = try value.counter("order_key")
        task.createdAt = try value.instant("created_at", keeping: existing?.createdAt)
        task.updatedAt = try value.instant("updated_at", keeping: existing?.updatedAt)
        task.serverRevision = try value.counter("revision")
        task.consecutiveStalledFormulations = try value.int("consecutive_stalled_formulations")
        task.formulation = try value.optionalObject("formulation").map {
            try clock($0, keeping: existing?.formulation, ids: ids)
        }
        task.parked = try value.optionalObject("parked").map { try park($0, existing: existing?.parked, ids: ids) }
        state.tasks[id] = task
    }

    private static func upsertProject(_ value: WireObject, _ state: inout GTDState, _ ids: RustIDTable) throws {
        let id = ProjectID(ids.swift(try value.string("id")))
        let existing = state.projects[id]
        var project = existing ?? ProjectRecord(id: id, name: "", createdAt: epoch)
        project.name = try value.string("name")
        project.color = value.optionalString("color")
        project.state = try code(ProjectState.self, value, "state")
        project.serverRevision = try value.counter("revision")
        project.desiredOutcome = value.optionalString("desired_outcome")
        project.archivedAt = try value.optionalInstant("archived_at", keeping: existing?.archivedAt)
        project.archivedBeforeLossless = try value.bool("archived_before_lossless")
        project.createdAt = try value.instant("created_at", keeping: existing?.createdAt)
        state.projects[id] = project
    }

    private static func upsertTag(_ value: WireObject, _ state: inout GTDState, _ ids: RustIDTable) throws {
        let id = TagID(ids.swift(try value.string("id")))
        let existing = state.tags[id]
        var tag = existing ?? TagRecord(id: id, name: "", createdAt: epoch)
        tag.name = try value.string("name")
        tag.state = try code(TagState.self, value, "state")
        tag.serverRevision = try value.counter("revision")
        tag.createdAt = try value.instant("created_at", keeping: existing?.createdAt)
        state.tags[id] = tag
    }

    private static func upsertSubtask(_ value: WireObject, _ state: inout GTDState, _ ids: RustIDTable) throws {
        let taskID = TaskID(ids.swift(try value.string("task_id")))
        let id = SubtaskID(ids.swift(try value.string("id")))
        guard var task = state.tasks[taskID] else { throw RustDomainError.malformedResult }
        var subtask = task.subtasks.first { $0.id == id } ?? SubtaskRecord(id: id, title: "", orderKey: 0)
        subtask.title = try value.string("title")
        subtask.state = try code(SubtaskState.self, value, "state")
        subtask.orderKey = try value.counter("order_key")
        subtask.serverRevision = try value.counter("revision")
        task.subtasks.removeAll { $0.id == id }
        task.subtasks.append(subtask)
        task.subtasks.sort { ($0.orderKey, $0.id.rawValue) < ($1.orderKey, $1.id.rawValue) }
        state.tasks[taskID] = task
    }

    private static func upsertComment(
        _ value: WireObject, _ state: inout GTDState, _ ids: RustIDTable, actorID: String
    ) throws {
        let taskID = TaskID(ids.swift(try value.string("task_id")))
        let id = CommentID(ids.swift(try value.string("id")))
        guard var task = state.tasks[taskID] else { throw RustDomainError.malformedResult }
        let existing = task.comments.first { $0.id == id }
        var comment = existing ?? CommentRecord(id: id, body: "", createdAt: epoch)
        comment.body = try value.string("body")
        // A comment written on this device has no author of its own until the server names one.
        let author = try value.string("actor_id")
        comment.authorID = author == actorID ? nil : author
        comment.createdAt = try value.instant("created_at", keeping: existing?.createdAt)
        comment.editedAt = try value.optionalInstant("edited_at", keeping: existing?.editedAt)
        comment.serverRevision = try value.counter("revision")
        if let index = task.comments.firstIndex(where: { $0.id == id }) {
            task.comments[index] = comment
        } else {
            task.comments.append(comment)
        }
        state.tasks[taskID] = task
    }

    // MARK: - Review

    private static func upsertSettings(_ value: WireObject, _ state: inout GTDState, at date: Date) throws {
        var settings = state.review.settings
        let days = try value.int("threshold_days")
        if days != settings.thresholdDays { settings.thresholdChangedAt = date }
        settings.thresholdDays = days
        settings.reviewWeekday = try value.int("review_weekday")
        settings.reviewTime = try value.string("review_time")
        settings.timeZone = try value.string("time_zone")
        settings.onboardedAt = try value.optionalInstant("onboarded_at", keeping: settings.onboardedAt)
        settings.activatedAt = try value.optionalInstant("activated_at", keeping: settings.activatedAt)
        settings.ownerParkFloorAt = try value.optionalInstant("owner_park_floor_at", keeping: settings.ownerParkFloorAt)
        settings.revision = try value.counter("revision")
        state.review.settings = settings
    }

    private static func upsertSession(_ value: WireObject, _ state: inout GTDState, _ ids: RustIDTable) throws {
        let id = ReviewSessionID(ids.swift(try value.string("id")))
        let existing = state.review.sessions[id]
        var session: ReviewSession
        if let existing {
            session = existing
        } else {
            session = ReviewSession(
                id: id, mode: try code(ReviewMode.self, value, "mode"), entry: try code(ReviewEntry.self, value, "entry"),
                origin: try code(ReviewOrigin.self, value, "origin"), startedAt: try value.instant("started_at"))
        }
        session.mode = try code(ReviewMode.self, value, "mode")
        session.entry = try code(ReviewEntry.self, value, "entry")
        session.origin = try code(ReviewOrigin.self, value, "origin")
        session.status = try code(ReviewSessionStatus.self, value, "status")
        session.startedAt = try value.instant("started_at", keeping: existing?.startedAt)
        session.lastActivityAt = try value.instant("last_activity_at", keeping: existing?.lastActivityAt)
        session.endedAt = try value.optionalInstant("ended_at", keeping: existing?.endedAt)
        session.currentStep = try optionalCode(ReviewStep.self, value, "current_step")
        var steps: [ReviewStep: StepStatus] = [:]
        for (key, status) in try value.object("steps") {
            if let step = ReviewStep(rawValue: key), let text = status as? String, let known = StepStatus(rawValue: text) {
                steps[step] = known
            }
        }
        session.steps = steps
        var seconds: [ReviewStep: Int] = [:]
        for (key, amount) in try value.object("active_seconds_by_step") {
            if let step = ReviewStep(rawValue: key), let amount = amount as? Int { seconds[step] = amount }
        }
        session.activeSecondsByStep = seconds
        let counts = try value.object("counts")
        var summary = SessionCounts()
        for counter in SessionCounter.allCases { summary[counter] = (counts[counter.rawValue] as? Int) ?? 0 }
        session.counts = summary
        session.setAsideCount = try value.int("set_aside_count")
        session.qualifyingActivity = try value.bool("qualifying_activity")
        session.clearStart = try optionalCode(ClearStart.self, value, "clear_start")
        session.revision = try value.counter("revision")
        state.review.sessions[id] = session
    }

    private static func upsertQueue(_ value: WireObject, _ state: inout GTDState, _ ids: RustIDTable) throws {
        let id = ReviewSessionID(ids.swift(try value.string("session_id")))
        guard var session = state.review.sessions[id] else { return }
        session.decisionQueue = value.optionalStrings("task_ids")?.map { TaskID(ids.swift($0)) }
        session.setAsideTaskIDs = try value.strings("set_aside_task_ids").map { TaskID(ids.swift($0)) }
        state.review.sessions[id] = session
    }

    private static func upsertDecision(_ value: WireObject, _ state: inout GTDState, _ ids: RustIDTable) throws
        -> DecisionID
    {
        let id = DecisionID(ids.swift(try value.string("id")))
        let existing = state.review.decisions[id]
        var decision: ReviewDecision
        if let existing {
            decision = existing
        } else {
            decision = ReviewDecision(
                id: id, taskID: TaskID(ids.swift(try value.string("task_id"))),
                type: try code(DecisionType.self, value, "type"), decidedAt: epoch,
                taskAfter: TaskStamp(updatedAt: nil, serverRevision: nil))
        }
        decision.sessionID = value.optionalString("session_id").map { ReviewSessionID(ids.swift($0)) }
        decision.decidedAt = try value.instant("decided_at", keeping: existing?.decidedAt)
        decision.formulationID = value.optionalString("formulation_id").map { FormulationID(ids.swift($0)) }
        decision.stallReason = try optionalCode(StallReason.self, value, "stall_reason")
        decision.substantive = value["substantive"] as? Bool
        decision.aiUse = try code(AIUse.self, value, "ai_use")
        decision.reasonText = value.optionalString("reason_text")
        decision.yieldedAutoPark = try value.bool("yielded_auto_park")
        state.review.decisions[id] = decision
        return id
    }

    private static func upsertReceipt(_ value: WireObject, _ state: inout GTDState, _ ids: RustIDTable) throws
        -> (task: TaskID, kind: ReceiptKind)
    {
        let task = TaskID(ids.swift(try value.string("task_id")))
        let kind = try code(ReceiptKind.self, value, "kind")
        let existing = state.review.receipt(for: task, kind: kind)
        state.review.setReceipt(
            ReviewReceipt(
                taskID: task, kind: kind, reviewedAt: try value.instant("reviewed_at", keeping: existing?.reviewedAt),
                hiddenUntil: try value.instant("hidden_until", keeping: existing?.hiddenUntil),
                source: try code(ReceiptSource.self, value, "source"), taskRevision: try value.counter("task_revision"),
                taskUpdatedAt: existing?.taskUpdatedAt,
                decisionID: value.optionalString("decision_id").map { DecisionID(ids.swift($0)) },
                bulkID: value.optionalString("bulk_id").map { BulkID(ids.swift($0)) }))
        return (task, kind)
    }

    /// An acknowledgement is present on this device exactly while the park is seen.
    private static func upsertParkAck(_ value: WireObject, _ state: inout GTDState, _ ids: RustIDTable) throws {
        let task = TaskID(ids.swift(try value.string("task_id")))
        let formulation = FormulationID(ids.swift(try value.string("formulation_id")))
        state.review.parkAcks.removeAll { $0.taskID == task && $0.formulationID == formulation }
        if value.optionalString("seen_at") != nil {
            state.review.parkAcks.append(
                ParkAck(taskID: task, formulationID: formulation, parkedAt: try value.instant("parked_at")))
        }
    }

    private static func upsertBulkRelease(
        _ value: WireObject, _ state: inout GTDState, before: GTDState, _ ids: RustIDTable
    ) throws -> BulkID {
        let id = BulkID(ids.swift(try value.string("id")))
        let existing = state.review.bulkReleases[id]
        var released: [BulkReleasedTask] = []
        for item in try value.objects("released") {
            let task = TaskID(ids.swift(try item.string("task_id")))
            if let kept = existing?.released.first(where: { $0.taskID == task }) {
                released.append(kept)
                continue
            }
            // The device shows what it released from; the core's private snapshot is the server's.
            let prior = before.tasks[task]
            released.append(
                BulkReleasedTask(
                    taskID: task, previousState: prior?.openList ?? .someday,
                    clockBefore: prior?.formulation.map {
                        ReleasedClock(clock: $0, stalledBefore: prior?.consecutiveStalledFormulations ?? 0)
                    }, taskAfter: TaskStamp(updatedAt: nil, serverRevision: nil)))
        }
        var skipped: [BulkSkippedTask] = []
        for item in try value.objects("skipped") {
            skipped.append(
                BulkSkippedTask(taskID: TaskID(ids.swift(try item.string("task_id"))), reason: try item.string("reason")))
        }
        var undoResult: BulkUndoResult?
        if let undo = value.optionalObject("undo") {
            undoResult = BulkUndoResult(
                restored: try undo.strings("restored").map { TaskID(ids.swift($0)) },
                skipped: try undo.objects("skipped").map { TaskID(ids.swift(try $0.string("task_id"))) })
        }
        state.review.bulkReleases[id] = BulkReleaseRecord(
            id: id, kind: try code(BulkReleaseKindCode.self, value, "kind"),
            sessionID: value.optionalString("session_id").map { ReviewSessionID(ids.swift($0)) },
            createdAt: try value.instant("created_at", keeping: existing?.createdAt), released: released,
            skipped: skipped, undoneAt: try value.optionalInstant("undone_at", keeping: existing?.undoneAt),
            undoResult: undoResult)
        return id
    }

    private static func upsertConsent(_ value: WireObject, _ state: inout GTDState) throws {
        let provider = try value.string("provider")
        guard let grant = value.optionalObject("consent") else {
            state.review.navigatorConsents[provider] = NavigatorConsent(provider: provider)
            return
        }
        let existing = state.review.navigatorConsents[provider]
        state.review.navigatorConsents[provider] = NavigatorConsent(
            provider: provider, grantedAt: try grant.instant("granted_at", keeping: existing?.grantedAt),
            revokedAt: try grant.optionalInstant("revoked_at", keeping: existing?.revokedAt),
            consentTextVersion: try grant.int("consent_text_version"))
    }

    // MARK: - Removals

    private static func remove(_ entityType: String, key: [String], from state: inout GTDState, _ ids: RustIDTable) throws
    {
        switch entityType {
        case "task":
            if let id = key.first { state.tasks[TaskID(ids.swift(id))] = nil }
        case "subtask":
            if let id = key.first {
                for task in state.tasks.keys { state.tasks[task]?.subtasks.removeAll { $0.id.rawValue == ids.swift(id) } }
            }
        case "comment":
            if let id = key.first {
                for task in state.tasks.keys { state.tasks[task]?.comments.removeAll { $0.id.rawValue == ids.swift(id) } }
            }
        case "review_decision":
            if let id = key.first { state.review.decisions[DecisionID(ids.swift(id))] = nil }
        case "review_receipt":
            if key.count == 2, let kind = ReceiptKind(rawValue: key[1]) {
                state.review.removeReceipt(for: TaskID(ids.swift(key[0])), kind: kind)
            }
        case "review_park_ack":
            if key.count == 2 {
                let task = TaskID(ids.swift(key[0]))
                let formulation = FormulationID(ids.swift(key[1]))
                state.review.parkAcks.removeAll { $0.taskID == task && $0.formulationID == formulation }
            }
        default:
            break
        }
    }
}
