import Foundation

// `GTDCommand` as a catalog command of the shared core (contracts/command-catalog.md):
// the type, the target, the payload with its omitted / `null` / value distinction, the
// revision check on the target, and the identifiers the rules may mint. Nothing here
// decides a rule: it only says what the person asked for. Every identifier it sends is the
// canonical wire ID of `RustIDTable`, the same one the read set carries for that record.

/// One command ready to be put in an envelope.
struct RustEncodedCommand {
    /// The record whose revision the command is checked against.
    struct Target {
        var entityType: String
        var id: String
        var revision: Int
    }

    var type: String
    var entityID: String
    var payload: WireObject
    var target: Target?
    /// IDs the rules may mint, in the order they are consumed.
    var allocatedIDs: [String]
    /// The instant the rules treat as now.
    var issuedAt: Date
    /// Set by the Navigator consent commands, which carry the provider and consent text.
    var navigatorProvider: String?
    var consentTextVersion: Int?
}

enum RustCommandEncoder {
    /// - Throws: `GTDValidationError` for a request the shared payloads cannot carry
    ///   (a null title or priority), as the server reports them.
    static func encode(
        _ command: GTDCommand, at date: Date, in state: GTDState, scopeID: String, ids: inout RustIDTable,
        intendedTagMembership: [String: [TagID]] = [:], intendedDeletedTags: Set<String> = []
    ) throws -> RustEncodedCommand {
        var encoded: RustEncodedCommand
        switch command {
        case .createProject(let create):
            encoded = make("project.create", ids.project(create.projectID), date)
            encoded.payload = [
                "name": create.name, "color": wireNull(create.color), "desired_outcome": wireNull(create.desiredOutcome),
            ]
        case .updateProject(let update):
            encoded = make("project.update", ids.project(update.projectID), date)
            if let name = update.name { encoded.payload["name"] = name }
            if let color = patch(update.color, { $0 }) { encoded.payload["color"] = color }
            encoded.target = target("project", encoded.entityID, revision(state.projects[update.projectID]))
        case .archiveProject(let id):
            encoded = make("project.archive", ids.project(id), date)
            encoded.target = target("project", encoded.entityID, revision(state.projects[id]))
        case .setProjectOutcome(let id, let outcome):
            encoded = make("project.update", ids.project(id), date)
            encoded.payload = ["desired_outcome": wireNull(outcome)]
            encoded.target = target("project", encoded.entityID, revision(state.projects[id]))
        case .unarchiveProject(let id):
            encoded = make("project.unarchive", ids.project(id), date)
            encoded.target = target("project", encoded.entityID, revision(state.projects[id]))
        case .createTag(let create):
            encoded = make("tag.create", ids.tag(create.tagID), date)
            encoded.payload = ["name": create.name]
        case .renameTag(let rename):
            encoded = make("tag.update", ids.tag(rename.tagID), date)
            encoded.payload = ["name": rename.name]
            encoded.target = target("tag", encoded.entityID, revision(state.tags[rename.tagID]))
        case .deleteTag(let id):
            encoded = make("tag.delete", ids.tag(id), date)
            encoded.target = target("tag", encoded.entityID, revision(state.tags[id]))
        case .createTask(let create):
            encoded = make("task.create", ids.task(create.taskID), date)
            encoded.payload = [
                "title": NameNormalizer.stripped(create.title),
                "details": wireNull(create.details.flatMap { $0.isEmpty ? nil : $0 }),
                "state": create.list.rawValue, "project_id": ids.optional(create.projectID?.rawValue, prefix: "project"),
                "tag_ids": create.tagIDs.map { ids.tag($0) }, "due_date": wireNull(create.dueDate?.isoString),
                "priority": create.priority.rawValue, "waiting_for": wireNull(create.waitingFor),
            ]
            if let id = create.newFormulationID { encoded.payload["new_formulation_id"] = ids.newFormulation(id) }
            encoded.allocatedIDs = [derivedFormulation(create.taskID, date)]
        case .updateTask(let update):
            encoded = make("task.update", ids.task(update.taskID), date)
            try encodeTaskChanges(update.changes, of: state.tasks[update.taskID],
                intendedTags: intendedTagMembership[encoded.entityID], deletedTags: intendedDeletedTags,
                into: &encoded.payload, ids: &ids)
            if let id = update.newFormulationID { encoded.payload["new_formulation_id"] = ids.newFormulation(id) }
            encoded.allocatedIDs = [derivedFormulation(update.taskID, date)]
            encoded.target = target("task", encoded.entityID, revision(state.tasks[update.taskID]))
        case .transitionTask(let transition):
            encoded = make("task.transition", ids.task(transition.taskID), date)
            encoded.payload = ["action": transition.action.rawValue]
            if let list = transition.toList { encoded.payload["to_state"] = list.rawValue }
            if let note = transition.waitingFor { encoded.payload["waiting_for"] = note }
            if let id = transition.newFormulationID { encoded.payload["new_formulation_id"] = ids.newFormulation(id) }
            encoded.allocatedIDs = [derivedFormulation(transition.taskID, date)]
            encoded.target = target("task", encoded.entityID, revision(state.tasks[transition.taskID]))
        case .createSubtask(let create):
            encoded = make("subtask.create", ids.subtask(create.subtaskID), date)
            encoded.payload = ["task_id": ids.task(create.taskID), "title": NameNormalizer.stripped(create.title)]
        case .updateSubtask(let update):
            encoded = make("subtask.update", ids.subtask(update.subtaskID), date)
            encoded.payload = ["task_id": ids.task(update.taskID), "title": NameNormalizer.stripped(update.title)]
            encoded.target = target(
                "subtask", encoded.entityID, subtaskRevision(update.subtaskID, update.taskID, state))
        case .transitionSubtask(let transition):
            encoded = make("subtask.transition", ids.subtask(transition.subtaskID), date)
            encoded.payload = ["task_id": ids.task(transition.taskID), "action": transition.action.rawValue]
            encoded.target = target(
                "subtask", encoded.entityID, subtaskRevision(transition.subtaskID, transition.taskID, state))
        case .createComment(let create):
            encoded = make("comment.create", ids.comment(create.commentID), date)
            encoded.payload = ["task_id": ids.task(create.taskID), "body": create.body]
        case .updateComment(let update):
            encoded = make("comment.update", ids.comment(update.commentID), date)
            encoded.payload = ["task_id": ids.task(update.taskID), "body": update.body]
            let comment = state.tasks[update.taskID]?.comments.first { $0.id == update.commentID }
            encoded.target = target("comment", encoded.entityID, revision(comment))
        case .decideTask(let decide):
            encoded = try encodeDecision(decide, at: date, in: state, ids: &ids)
        case .undoDecision(let id):
            encoded = make("review.undo_decision", ids.decision(id), date)
            if let decision = state.review.decisions[id] {
                encoded.target = target("task", ids.task(decision.taskID), revision(state.tasks[decision.taskID]))
            }
        case .autoParkTask(let park):
            encoded = make("review.auto_park", ids.task(park.taskID), park.observedAt ?? date)
            encoded.payload = ["formulation_id": ids.formulation(park.formulationID)]
        case .bulkRelease(let release):
            encoded = make("review.bulk_release", ids.bulk(release.bulkID), date)
            var items: [WireObject] = []
            for id in release.taskIDs {
                items.append([
                    "task_id": ids.task(id), "expected_revision": String(max(revision(state.tasks[id]) ?? 0, 0)),
                ])
            }
            encoded.payload = [
                "kind": release.kind.rawValue, "session_id": ids.optional(release.sessionID?.rawValue, prefix: "review"),
                "items": items,
            ]
        case .undoBulkRelease(let id):
            encoded = make("review.bulk_undo", ids.bulk(id), date)
        case .review(let review):
            encoded = try encodeReview(review, at: date, in: state, scopeID: scopeID, ids: &ids)
        }
        return encoded
    }

    // MARK: - Pieces

    private static func make(_ type: String, _ entityID: String, _ date: Date) -> RustEncodedCommand {
        RustEncodedCommand(
            type: type, entityID: entityID, payload: [:], target: nil, allocatedIDs: [], issuedAt: date,
            navigatorProvider: nil, consentTextVersion: nil)
    }

    /// The revision check on a record the state holds; a missing record has none and the
    /// core reports it as not found.
    private static func target(_ entityType: String, _ id: String, _ revision: Int?) -> RustEncodedCommand.Target? {
        guard let revision else { return nil }
        return RustEncodedCommand.Target(entityType: entityType, id: id, revision: max(revision, 0))
    }

    private static func subtaskRevision(_ id: SubtaskID, _ task: TaskID, _ state: GTDState) -> Int? {
        revision(state.tasks[task]?.subtasks.first { $0.id == id })
    }

    /// A record's revision as the core reads it; nil for a record the state does not hold.
    private static func revision<Record: ServerBacked>(_ record: Record?) -> Int? {
        record.map { $0.serverRevision ?? 0 }
    }

    /// Omitted when unchanged, `null` when cleared, the value when set.
    private static func patch<Value: Hashable & Sendable & Codable>(
        _ change: FieldChange<Value>, _ transform: (Value) -> Any
    ) -> Any? {
        switch change {
        case .unchanged: return nil
        case .clear: return NSNull()
        case .set(let value): return transform(value)
        }
    }

    /// The id a formulation gets when the command carries none, derived as the Swift reducer does.
    static func derivedFormulation(_ task: TaskID, _ date: Date) -> String {
        ClientID.derived("form", from: "\(task.rawValue)|\(date.timeIntervalSinceReferenceDate)")
    }

    private static func encodeTaskChanges(
        _ changes: TaskChanges, of task: TaskRecord?, intendedTags: [TagID]?, deletedTags: Set<String>,
        into payload: inout WireObject, ids: inout RustIDTable
    ) throws {
        // A null title or priority is a request error the shared payloads cannot carry.
        switch changes.title {
        case .unchanged: break
        case .clear: throw GTDValidationError.emptyTitle
        case .set(let title): payload["title"] = NameNormalizer.stripped(title)
        }
        switch changes.priority {
        case .unchanged: break
        case .clear: throw GTDValidationError.priorityRequired
        case .set(let priority): payload["priority"] = priority.rawValue
        }
        if let value = patch(changes.details, { $0.isEmpty ? NSNull() : $0 as Any }) { payload["details"] = value }
        switch changes.projectID {
        case .unchanged: break
        case .clear: payload["project_id"] = NSNull()
        case .set(let id): payload["project_id"] = ids.project(id)
        }
        if let value = patch(changes.dueDate, { $0.isoString }) { payload["due_date"] = value }
        if let value = patch(changes.waitingFor, { $0 }) { payload["waiting_for"] = value }
        // The shared edit names the difference to the stored membership, not the whole list.
        let current = (intendedTags ?? task?.tagIDs ?? []).map { ids.tag($0) }.filter { !deletedTags.contains($0) }
        switch changes.tagIDs {
        case .unchanged:
            break
        case .clear:
            payload["tag_changes"] = ["add_tag_ids": [String](), "remove_tag_ids": current]
        case .set(let wanted):
            let wanted = wanted.map { ids.tag($0) }
            payload["tag_changes"] = [
                "add_tag_ids": wanted.filter { !current.contains($0) },
                "remove_tag_ids": current.filter { !wanted.contains($0) },
            ]
        }
    }

    private static func encodeDecision(
        _ decide: GTDCommand.DecideTask, at date: Date, in state: GTDState, ids: inout RustIDTable
    ) throws -> RustEncodedCommand {
        var encoded = make("review.decide", ids.task(decide.taskID), date)
        var payload: WireObject = [
            "decision_id": ids.decision(decide.decisionID), "type": decide.type.rawValue,
            "formulation_id": ids.optional(decide.formulationID?.rawValue, prefix: "form"),
            "stall_reason": wireNull(decide.stallReason?.rawValue),
            "title": wireNull(decide.title.map(NameNormalizer.stripped)), "waiting_for": wireNull(decide.waitingFor),
            "reason": wireNull(decide.reason),
            "session_id": ids.optional(decide.sessionID?.rawValue, prefix: "review"),
            "ai_use": decide.aiUse.rawValue, "navigator_request_id": wireNull(decide.navigatorRequestID),
            "client_decided_at": RustInstant.format(date),
        ]
        if let id = decide.newFormulationID { payload["new_formulation_id"] = ids.newFormulation(id) }
        encoded.allocatedIDs = [derivedFormulation(decide.taskID, date)]
        if let followUp = decide.followUpTaskID {
            payload["follow_up_task_id"] = ids.task(followUp)
            encoded.allocatedIDs.append(derivedFormulation(followUp, date))
        }
        encoded.payload = payload
        encoded.target = target("task", encoded.entityID, revision(state.tasks[decide.taskID]))
        return encoded
    }

    private static func encodeReview(
        _ review: ReviewCommand, at date: Date, in state: GTDState, scopeID: String, ids: inout RustIDTable
    ) throws -> RustEncodedCommand {
        switch review {
        case .acknowledgeExplainer(let timeZone):
            var encoded = make("review.explainer_ack", scopeID, date)
            encoded.payload = ["time_zone": wireNull(timeZone)]
            return encoded
        case .updateSettings(let change):
            var encoded = make("review.settings", scopeID, date)
            if let days = change.thresholdDays { encoded.payload["threshold_days"] = days }
            if let weekday = change.reviewWeekday { encoded.payload["review_weekday"] = weekday }
            if let time = change.reviewTime { encoded.payload["review_time"] = time }
            if let zone = change.timeZone { encoded.payload["time_zone"] = zone }
            if change.onboarded { encoded.payload["onboarded"] = true }
            // Settings nobody changed are not in the read set (`RustReadSet`); the core's default
            // row for them is at revision 1.
            let stored = state.review.settings != ReviewSettings()
            encoded.target = RustEncodedCommand.Target(
                entityType: "review_settings", id: scopeID,
                revision: stored ? max(state.review.settings.revision ?? 0, 0) : 1)
            return encoded
        case .acknowledgeParks(let items):
            var encoded = make("review.parks_ack", scopeID, date)
            var keys: [WireObject] = []
            for item in items {
                keys.append(["task_id": ids.task(item.taskID), "formulation_id": ids.formulation(item.formulationID)])
            }
            encoded.payload = ["items": keys]
            return encoded
        case .startSession(let start):
            var encoded = make("review.session_start", ids.session(start.sessionID), date)
            encoded.payload = [
                "mode": start.mode.rawValue, "entry": start.entry.rawValue, "origin": start.origin.rawValue,
                "skip_steps": start.skipSteps.map(\.rawValue), "replace_open": true,
            ]
            return encoded
        case .progressSession(let progress):
            var encoded = make("review.session_progress", ids.session(progress.sessionID), date)
            var payload: WireObject = ["progress_id": ids.progress(progress.progressID)]
            if let step = progress.currentStep { payload["current_step"] = step.rawValue }
            if let step = progress.step, let status = progress.stepStatus {
                payload["step"] = ["code": step.rawValue, "status": status.rawValue]
            }
            if let step = progress.activeStep, let seconds = progress.activeSeconds {
                payload["active_seconds"] = ["code": step.rawValue, "seconds": max(seconds, 0)]
            }
            if let task = progress.setAsideTaskID { payload["set_aside_task_id"] = ids.task(task) }
            if let delta = progress.inboxProcessedDelta { payload["inbox_processed_delta"] = delta }
            if progress.snapshotDecisionQueue { payload["snapshot_decision_queue"] = true }
            encoded.payload = payload
            return encoded
        case .finishSession(let finish):
            var encoded = make("review.session_finish", ids.session(finish.sessionID), date)
            encoded.payload = ["clear_start": wireNull(finish.clearStart?.rawValue)]
            return encoded
        case .grantNavigatorConsent(let provider, let version):
            var encoded = make("review.consent_grant", scopeID, date)
            encoded.payload = ["provider": provider, "consent_text_version": version]
            encoded.navigatorProvider = provider
            encoded.consentTextVersion = version
            return encoded
        case .revokeNavigatorConsent(let provider):
            var encoded = make("review.consent_revoke", scopeID, date)
            encoded.payload = ["provider": provider]
            return encoded
        }
    }
}
