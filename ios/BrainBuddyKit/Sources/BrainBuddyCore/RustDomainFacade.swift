import Foundation

// The Apple facade over the shared Rust rules (spec 026, T017, ADR-0031). It mirrors the
// Python facade (`backend/app/modules/tasks/rust_task_facade.py`): the host keeps its own
// state and I/O, the facade maps one command or query to the core's typed values and the
// answer back, and the core's dispatch (`bb_domain::dispatch`) decides. In the migrated
// rule/storage epoch every `GTDCommand` and every catalog query is answered by that one
// result: nothing here falls back to the Swift rules, and no mutation runs both.

/// Which rules decide for a workspace.
public enum RuleEpoch: Sendable {
    /// A file written before the cutover keeps its compatible image: the Swift rules in
    /// this module, until the file is migrated.
    case legacy
    /// The migrated epoch: the shared Rust core.
    case rust(RustDomainFacade)
}

/// What the facade tells the core about this device. The rules never read a clock or the
/// operating system: the instant of a call, its zone and these facts are explicit inputs.
public struct RustDomainContext: Sendable, Equatable {
    /// The scope the local projection belongs to (the envelope's `scope_id`).
    public var scopeID: String
    /// The author recorded for comments written on this device.
    public var actorID: String
    /// The device's IANA zone, used where a command names none.
    public var deviceTimeZone: String

    public init(scopeID: String = "local", actorID: String = "device", deviceTimeZone: String = TimeZone.current.identifier) {
        self.scopeID = scopeID
        self.actorID = actorID
        self.deviceTimeZone = deviceTimeZone
    }
}

/// Decides every `GTDCommand` and answers every catalog query with the shared Rust core.
///
/// The device is not the authoritative side (`authoritative: false`): private Undo and park
/// snapshots belong to the server, so an Undo here is refused as `undoUnavailable` rather
/// than fabricated (contracts/runtime-ffi.md "Pure core"). The core is the revision
/// authority of the epoch: its revisions replace `serverRevision` and `revision`.
public struct RustDomainFacade: Sendable {
    public let runtime: RustBridgeRuntime
    public let context: RustDomainContext

    public init(runtime: RustBridgeRuntime, context: RustDomainContext = RustDomainContext()) {
        self.runtime = runtime
        self.context = context
    }

    // MARK: - Commands

    /// Decides `command` with the core and applies its change set to `state`.
    ///
    /// All or nothing: a refusal throws and leaves `state` untouched.
    /// - Throws: `GTDValidationError` for a refusal the app words, `RustDomainError` for one it
    ///   does not, `RustBridgeError` when the bridge fails (closed, cancelled, internal).
    @discardableResult
    public func apply(
        _ command: GTDCommand, at date: Date, to state: inout GTDState, mode: ApplyMode = .interactive
    ) async throws -> ApplyOutcome {
        guard mode == .interactive else { throw RustDomainError.replayIsRuntimeOwned }
        let before = state
        // The core gates the Review reads on the weekly-review flag, not its writes. What only
        // the review's own surfaces offer stays refused while it is off (FR-042): a product
        // gate at this boundary, not a rule of the domain.
        if Self.isReviewEntry(command), !before.review.isExposed { throw GTDValidationError.reviewUnavailable }
        // FR-011: a person's decision on a task that changed since the card showed it is stale.
        // The core can only see the task's revision; children are the device's to compare.
        if case .decideTask(let decide) = command, let shown = decide.expectedTask, let task = before.tasks[decide.taskID],
            !shown.matches(task, localChildEdits: before.localChildEdits.map { $0[task.id] ?? 0 })
        {
            throw GTDValidationError.formulationChanged
        }
        var ids = RustIDTable()
        let encoded = try RustCommandEncoder.encode(command, at: date, in: before, scopeID: context.scopeID, ids: &ids)
        let changeSet = try await decide(encoded, in: before, ids: ids)
        var next = before
        let outcome = try RustChangeApplier.apply(
            changeSet, to: &next, before: before, at: encoded.issuedAt, ids: ids, actorID: context.actorID)
        // Replay protection of a progress change is the device's record of what it sent.
        if case .progressSession(let progress) = command, var session = next.review.sessions[progress.sessionID] {
            session.appliedProgress.insert(progress.progressID)
            next.review.sessions[progress.sessionID] = session
        }
        // FR-011: a person's child edit on this device, where the caller tracks them.
        if next.localChildEdits != nil, let taskID = command.childEditTaskID {
            next.localChildEdits?[taskID, default: 0] += 1
        }
        state = next
        return outcome
    }

    /// A decision, a bulk release, starting a review, the explainer and "While you were away":
    /// what only the review's own surfaces offer. Undo, settings, progress, finish, consent and
    /// device auto-parks are not review entries.
    private static func isReviewEntry(_ command: GTDCommand) -> Bool {
        switch command {
        case .decideTask, .bulkRelease:
            return true
        case .review(let review):
            switch review {
            case .acknowledgeExplainer, .acknowledgeParks, .startSession:
                return true
            case .updateSettings, .progressSession, .finishSession, .grantNavigatorConsent, .revokeNavigatorConsent:
                return false
            }
        default:
            return false
        }
    }

    /// Sends one encoded command to the core and returns its change set.
    private func decide(_ encoded: RustEncodedCommand, in state: GTDState, ids: RustIDTable) async throws -> WireObject {
        let readSet = try RustJSON.data(RustReadSet.make(state, actorID: context.actorID))
        let envelope = try RustJSON.data(envelopeObject(encoded))
        let inputs = try RustJSON.data(executionInputs(encoded, state))
        let receipts = try RustJSON.data([Any]())
        switch try await runtime.decide(readSet: readSet, envelope: envelope, receipts: receipts, inputs: inputs) {
        case .changed(let changeSet):
            return try RustJSON.object(changeSet)
        case .refused(let refusal):
            throw Self.refusalError(refusal, payload: encoded.payload, in: state)
        }
    }

    private func envelopeObject(_ encoded: RustEncodedCommand) -> WireObject {
        var preconditions: [WireObject] = []
        if let target = encoded.target {
            preconditions.append([
                "entity_type": target.entityType, "entity_id": target.id, "edit_revision": String(target.revision),
            ])
        }
        return [
            "protocol_version": Int(RustBridgeRuntime.supportedProtocolVersion),
            "command_id": UUID().uuidString.lowercased(), "scope_id": context.scopeID, "device_id": "device",
            "device_epoch": "epoch", "local_sequence": "1", "type": encoded.type, "command_version": 1,
            "entity_id": encoded.entityID, "preconditions": preconditions, "depends_on": [String](),
            "issued_at": RustInstant.format(encoded.issuedAt), "payload": encoded.payload,
        ]
    }

    private func executionInputs(_ encoded: RustEncodedCommand, _ state: GTDState) -> WireObject {
        [
            "rule_version": 1, "now": RustInstant.format(encoded.issuedAt), "time_zone": context.deviceTimeZone,
            "origin": "device", "actor_id": context.actorID, "authoritative": false,
            "allocated_ids": encoded.allocatedIDs, "policy": policy(state, provider: encoded.navigatorProvider, version: encoded.consentTextVersion),
        ]
    }

    private func policy(_ state: GTDState, provider: String?, version: Int?) -> WireObject {
        [
            "weekly_review": state.review.isExposed, "navigator_provider": wireNull(provider),
            "navigator_available": provider != nil, "consent_text_version": version ?? 1,
        ]
    }

    // MARK: - Refusals

    /// The error for a refusal: the app's own wording where it has one, the core's typed
    /// reason otherwise.
    static func refusalError(_ refusal: RustRefusal, payload: WireObject, in state: GTDState) -> any Error {
        if let known = validationError(refusal, payload: payload, in: state) { return known }
        return RustDomainError.refused(reason: refusal.reason, field: refusal.field)
    }

    static func validationError(_ refusal: RustRefusal, payload: WireObject, in state: GTDState) -> GTDValidationError? {
        let name = payload["name"] as? String ?? ""
        switch refusal.reason {
        case "text_length": return lengthError(refusal.field)
        case "invalid_payload": return payloadError(refusal.field, payload)
        case "empty_title": return .emptyTitle
        case "empty_name": return .emptyName
        case "id_already_exists": return .idAlreadyExists
        case "waiting_for_required": return .waitingForRequired
        case "waiting_for_only_on_waiting_tasks": return .waitingForOnlyOnWaitingTasks
        // The refusal names the active record that holds the name.
        case "duplicate_project_name":
            let holder = refusal.entityKey.first.flatMap { state.projects[ProjectID($0)] }
            return .duplicateProjectName(holder?.name ?? NameNormalizer.display(name))
        case "duplicate_tag_name":
            let holder = refusal.entityKey.first.flatMap { state.tags[TagID($0)] }
            return .duplicateTagName(holder?.name ?? NameNormalizer.tagDisplay(name))
        case "project_not_active": return .projectNotActive
        case "project_archived": return .projectArchived
        case "project_already_archived": return .projectAlreadyArchived
        case "unarchive_name_in_use":
            let project = refusal.entityKey.first.flatMap { state.projects[ProjectID($0)] }
            return .unarchiveNameInUse(project?.name ?? name)
        case "tag_not_active": return .tagNotActive
        case "tag_already_deleted": return .tagAlreadyDeleted
        case "duplicate_tag", "tag_changes_overlap": return .duplicateTag
        case "task_not_open": return .taskNotOpen
        case "task_not_closed": return .taskNotClosed
        case "move_requires_destination": return .moveRequiresDestination
        case "move_requires_different_list": return .moveRequiresDifferentList
        case "reopen_requires_destination": return .reopenRequiresDestination
        case "subtask_already_in_state": return .subtaskAlreadyInState
        case "nothing_to_change": return .nothingToChange
        case "priority_required": return .priorityRequired
        case "decision_not_allowed": return .decisionNotAllowed
        case "decision_fields_missing": return missingDecisionField(refusal.field)
        case "extension_already_used": return .extensionAlreadyUsed
        case "extension_not_due": return .extensionNotDue
        case "extension_reason_required": return .extensionReasonRequired
        case "formulation_changed", "revision_conflict": return .formulationChanged
        case "undo_unavailable", "undo_expired", "undo_blocked_by_children": return .undoUnavailable
        case "review_unavailable", "review_not_activated": return .reviewUnavailable
        case "session_not_found": return .reviewNotFound
        case "step_not_in_review": return .stepNotInReview
        case "too_many_items": return .tooManyItems
        case "not_found": return notFound(refusal.entityType)
        default: return nil
        }
    }

    private static func notFound(_ entityType: String?) -> GTDValidationError? {
        switch entityType {
        case "task": .taskNotFound
        case "project": .projectNotFound
        case "tag": .tagNotFound
        case "subtask": .subtaskNotFound
        case "comment": .commentNotFound
        case "review_session", "review_bulk_release": .reviewNotFound
        case "review_decision": .undoUnavailable
        default: nil
        }
    }

    private static func missingDecisionField(_ field: String?) -> GTDValidationError? {
        switch field {
        case "title": .emptyTitle
        case "waiting_for": .waitingForRequired
        case "reason": .extensionReasonRequired
        case "formulation_id": .formulationChanged
        default: nil
        }
    }

    /// A value that is too long, by the type the core checked it as.
    private static func lengthError(_ field: String?) -> GTDValidationError? {
        switch field {
        case "Title", "ShortText", "title": .titleTooLong
        case "Details", "details": .detailsTooLong
        case "WaitingFor", "waiting_for": .waitingForTooLong
        case "Name": .nameTooLong
        case "Color": .colorTooLong
        case "CommentBody": .commentTooLong
        case "DesiredOutcome": .outcomeTooLong
        case "ReasonText": .extensionReasonTooLong
        default: nil
        }
    }

    /// The payload types refuse both an empty and an overlong value as one error; the
    /// request says which it was.
    private static func payloadError(_ field: String?, _ payload: WireObject) -> GTDValidationError? {
        let longest = payload.values.compactMap { ($0 as? String)?.unicodeScalars.count }.max() ?? 0
        switch field {
        case "Title", "ShortText": return longest > GTDLimits.title ? .titleTooLong : .emptyTitle
        case "Name": return longest > GTDLimits.name ? .nameTooLong : .emptyName
        case "CommentBody": return longest > GTDLimits.comment ? .commentTooLong : .emptyComment
        case "ReasonText": return longest > GTDLimits.title ? .extensionReasonTooLong : .extensionReasonRequired
        case "Details", "WaitingFor", "Color", "DesiredOutcome": return lengthError(field)
        default: return nil
        }
    }

    // MARK: - Queries

    /// The inputs every query reads besides the state: the instant, the device's zone and policy.
    private func queryInputs(_ state: GTDState, now: Date, zone: String) -> WireObject {
        ["now": RustInstant.format(now), "device_zone": zone, "policy": policy(state, provider: nil, version: nil)]
    }

    /// Asks the core one query; a refusal is a `RustDomainError`.
    private func ask(_ query: WireObject, readSet: Data, inputs: Data) async throws -> WireObject {
        let data = try RustJSON.data(query)
        switch try await runtime.query(readSet: readSet, query: data, inputs: inputs) {
        case .answered(let result): return try RustJSON.object(result)
        case .refused(let refusal): throw RustDomainError.refused(reason: refusal.reason, field: refusal.field)
        }
    }

    /// Every page of a paged query, following its cursor. The read set is encoded once.
    private func pages(
        readSet: Data, inputs: Data, _ build: (String?) -> WireObject
    ) async throws -> [WireObject] {
        var values: [WireObject] = []
        var cursor: String?
        while true {
            let value = try await ask(build(cursor), readSet: readSet, inputs: inputs).object("value")
            values.append(value)
            guard try value.bool("has_more"), let next = value.optionalString("next_cursor") else { break }
            cursor = next
        }
        return values
    }

    private static func page(_ cursor: String?) -> WireObject {
        ["limit": 200, "after": wireNull(cursor)]
    }

    /// The tasks a destination shows. The shared queries answer the open lists, a project, the
    /// agenda, a date view, History and Search; a destination or option they have no answer
    /// for is refused with `RustDomainError.unsupportedQuery`, never answered by the Swift code.
    ///
    /// - Parameters:
    ///   - now: the instant the date views are read at.
    ///   - zone: the device's IANA zone, whose day `now` falls on.
    public func list(
        _ destination: Destination, options: ListOptions, in state: GTDState, now: Date, zone: String
    ) async throws -> TaskListResult {
        let readSet = try RustJSON.data(RustReadSet.make(state, actorID: context.actorID))
        let inputs = try RustJSON.data(queryInputs(state, now: now, zone: zone))
        switch destination {
        case .agenda:
            return try await listMode(["type": "agenda"], options, state, readSet, inputs)
        case .dateView(let view):
            return try await listMode(["type": "date_view", "view": view.rawValue], options, state, readSet, inputs)
        case .history(let kind):
            return try await listMode(["type": "history", "kind": kind.rawValue], options, state, readSet, inputs)
        case .search(let text):
            return try await listMode(["type": "search", "text": text], options, state, readSet, inputs)
        case .list(let list):
            try requirePlainOptions(options, "open list")
            let tasks = try await openTasks(list, project: nil, options, state, readSet, inputs)
            let sections = tasks.isEmpty ? [] : [TaskSection(id: "open", title: nil, kind: .open, tasks: tasks)]
            return TaskListResult(sections: sections, openCount: tasks.count)
        case .project(let id):
            try requirePlainOptions(options, "project")
            var sections: [TaskSection] = []
            for list in GTDQueries.projectListOrder {
                let tasks = try await openTasks(list, project: id, options, state, readSet, inputs)
                if !tasks.isEmpty {
                    sections.append(TaskSection(id: "list:\(list.rawValue)", title: list.title, kind: .list(list), tasks: tasks))
                }
            }
            return TaskListResult(sections: sections, openCount: sections.reduce(0) { $0 + $1.tasks.count })
        case .tag:
            throw RustDomainError.unsupportedQuery("tag")
        }
    }

    /// The shared open-list query has no grouping, completed rows or priority filter.
    private func requirePlainOptions(_ options: ListOptions, _ what: String) throws {
        if options.groupByProject || options.showCompleted || options.showCancelled || !options.priorities.isEmpty {
            throw RustDomainError.unsupportedQuery("\(what) options")
        }
    }

    private func openTasks(
        _ list: OpenList, project: ProjectID?, _ options: ListOptions, _ state: GTDState, _ readSet: Data,
        _ inputs: Data
    ) async throws -> [TaskRecord] {
        let results = try await pages(readSet: readSet, inputs: inputs) { cursor in
            [
                "kind": "task_list", "list": list.rawValue, "project_id": wireNull(project?.rawValue),
                "tag_id": wireNull(options.tagFilter?.rawValue), "sort": options.sort.rawValue, "page": Self.page(cursor),
            ]
        }
        var tasks: [TaskRecord] = []
        for result in results {
            for item in try result.objects("items") {
                if let task = state.tasks[TaskID(try item.string("id"))] { tasks.append(task) }
            }
        }
        return tasks
    }

    private func listMode(
        _ mode: WireObject, _ options: ListOptions, _ state: GTDState, _ readSet: Data, _ inputs: Data
    ) async throws -> TaskListResult {
        let wireOptions: WireObject = [
            "sort": options.sort.rawValue, "group_by_project": options.groupByProject,
            "show_completed": options.showCompleted, "show_cancelled": options.showCancelled,
            "priorities": options.priorities.map(\.rawValue).sorted(), "tag_filter": wireNull(options.tagFilter?.rawValue),
        ]
        let results = try await pages(readSet: readSet, inputs: inputs) { cursor in
            ["kind": "list_mode", "mode": mode, "options": wireOptions, "page": Self.page(cursor)]
        }
        var sections: [TaskSection] = []
        for result in results {
            for section in try result.objects("sections") {
                let id = try section.string("id")
                var tasks: [TaskRecord] = []
                for item in try section.objects("items") {
                    if let task = state.tasks[TaskID(try item.string("id"))] { tasks.append(task) }
                }
                // A section a page starts inside repeats its id.
                if let last = sections.last, last.id == id {
                    sections[sections.count - 1].tasks += tasks
                } else {
                    sections.append(
                        TaskSection(
                            id: id, title: section.optionalString("title"), kind: try Self.sectionKind(section.object("kind")),
                            tasks: tasks))
                }
            }
        }
        let openCount = try results.first?.int("open_count") ?? 0
        return TaskListResult(sections: sections, openCount: openCount)
    }

    private static func sectionKind(_ kind: WireObject) throws -> TaskSection.Kind {
        switch try kind.string("type") {
        case "open": return .open
        case "project": return .project(kind.optionalString("project_id").map { ProjectID($0) })
        case "date_view":
            guard let view = DateView(rawValue: try kind.string("view")) else { throw RustDomainError.malformedResult }
            return .dateView(view)
        case "completed": return .completed
        case "cancelled": return .cancelled
        default: throw RustDomainError.malformedResult
        }
    }

    /// Badge counts over open tasks.
    public func counts(in state: GTDState, now: Date, zone: String) async throws -> ListCounts {
        let readSet = try RustJSON.data(RustReadSet.make(state, actorID: context.actorID))
        let inputs = try RustJSON.data(queryInputs(state, now: now, zone: zone))
        let value = try await ask(["kind": "list_counts"], readSet: readSet, inputs: inputs).object("value")
        return ListCounts(
            inbox: try value.int("inbox"), next: try value.int("next"), waiting: try value.int("waiting"),
            someday: try value.int("someday"), overdue: try value.int("overdue"), today: try value.int("today"))
    }

    /// Active (or archived) projects by name, with their open-task counts.
    public func projects(in state: GTDState, archived: Bool = false, now: Date, zone: String) async throws
        -> [ProjectSummary]
    {
        let readSet = try RustJSON.data(RustReadSet.make(state, actorID: context.actorID))
        let inputs = try RustJSON.data(queryInputs(state, now: now, zone: zone))
        let result = try await ask(
            ["kind": "projects", "filter": archived ? "archived" : "active"], readSet: readSet, inputs: inputs)
        var summaries: [ProjectSummary] = []
        for item in result["value"] as? [WireObject] ?? [] {
            guard let project = state.projects[ProjectID(try item.object("project").string("id"))] else { continue }
            summaries.append(
                ProjectSummary(
                    project: project, openTaskCount: try item.int("open_task_count"),
                    nextActionCount: try item.int("next_action_count")))
        }
        return summaries
    }

    /// Active tags by name, with the number of open tasks carrying each.
    public func tags(in state: GTDState, now: Date, zone: String) async throws -> [TagSummary] {
        let readSet = try RustJSON.data(RustReadSet.make(state, actorID: context.actorID))
        let inputs = try RustJSON.data(queryInputs(state, now: now, zone: zone))
        let result = try await ask(["kind": "tags"], readSet: readSet, inputs: inputs)
        var summaries: [TagSummary] = []
        for item in result["value"] as? [WireObject] ?? [] {
            guard let tag = state.tags[TagID(try item.object("tag").string("id"))] else { continue }
            summaries.append(TagSummary(tag: tag, openTaskCount: try item.int("open_task_count")))
        }
        return summaries
    }

    /// How a project presents itself; nil for a project the state does not hold.
    public func projectDisplay(_ id: ProjectID, in state: GTDState, now: Date, zone: String) async throws
        -> ProjectDisplay?
    {
        guard state.projects[id] != nil else { return nil }
        let readSet = try RustJSON.data(RustReadSet.make(state, actorID: context.actorID))
        let inputs = try RustJSON.data(queryInputs(state, now: now, zone: zone))
        let value = try await ask(["kind": "project_display", "project_id": id.rawValue], readSet: readSet, inputs: inputs)
            .object("value")
        return ProjectDisplay(
            isArchived: try value.bool("is_archived"), acceptsNewTasks: try value.bool("accepts_new_tasks"),
            showsPreLosslessLine: try value.bool("shows_pre_lossless_line"), label: try value.string("label"))
    }

    /// One task with its children, as the state holds it; nil for a task it does not hold.
    public func taskDetail(_ id: TaskID, in state: GTDState, now: Date, zone: String) async throws -> TaskRecord? {
        guard let task = state.tasks[id] else { return nil }
        let readSet = try RustJSON.data(RustReadSet.make(state, actorID: context.actorID))
        let inputs = try RustJSON.data(queryInputs(state, now: now, zone: zone))
        _ = try await ask(["kind": "task_detail", "task_id": id.rawValue], readSet: readSet, inputs: inputs)
        return task
    }

    /// The review's derived facts (`GET /review/state`). A review the policy does not expose is
    /// `exposed: false`, as the server answers `404 weekly_review_disabled`.
    public func reviewState(in state: GTDState, now: Date, zone: String) async throws -> ReviewServerFacts {
        let readSet = try RustJSON.data(RustReadSet.make(state, actorID: context.actorID))
        let inputs = try RustJSON.data(queryInputs(state, now: now, zone: zone))
        let value: WireObject
        do {
            value = try await ask(["kind": "review_state"], readSet: readSet, inputs: inputs).object("value")
        } catch RustDomainError.refused(let reason, _) where reason == "review_unavailable" {
            return ReviewServerFacts(exposed: false)
        }
        var last: LastCountedReview?
        if let counted = value.optionalObject("last_counted_review") {
            let counts = try counted.object("counts")
            var summary = SessionCounts()
            for counter in SessionCounter.allCases { summary[counter] = (counts[counter.rawValue] as? Int) ?? 0 }
            guard let status = ReviewSessionStatus(rawValue: try counted.string("status")),
                let origin = ReviewOrigin(rawValue: try counted.string("origin"))
            else { throw RustDomainError.malformedResult }
            last = LastCountedReview(
                sessionID: ReviewSessionID(try counted.string("session_id")), status: status, origin: origin,
                endedAt: try counted.optionalInstant("ended_at"), counts: summary,
                clearStart: counted.optionalString("clear_start").flatMap { ClearStart(rawValue: $0) })
        }
        return ReviewServerFacts(
            exposed: true, lastCountedReviewAt: try value.optionalInstant("last_counted_review_at"),
            lastCountedReview: last, nextReviewAt: try value.optionalInstant("next_review_at"),
            restartMode: try value.bool("restart_mode"),
            openSessionID: value.optionalObject("open_session").flatMap { $0.optionalString("id") }
                .map { ReviewSessionID($0) },
            pulledAt: now)
    }

    /// The cards of one review step, in queue order.
    public func reviewQueue(
        step: ReviewStep, session: ReviewSessionID? = nil, in state: GTDState, now: Date, zone: String
    ) async throws -> [TaskRecord] {
        let readSet = try RustJSON.data(RustReadSet.make(state, actorID: context.actorID))
        let inputs = try RustJSON.data(queryInputs(state, now: now, zone: zone))
        let value = try await ask(
            ["kind": "review_queue", "step": step.rawValue, "session_id": wireNull(session?.rawValue)], readSet: readSet,
            inputs: inputs
        ).object("value")
        var tasks: [TaskRecord] = []
        for item in try value.objects("items") {
            if let task = state.tasks[TaskID(try item.string("id"))] { tasks.append(task) }
        }
        return tasks
    }

    // MARK: - Smart Add

    private func draftObject(_ draft: CaptureDraft) -> WireObject {
        [
            "text": draft.text, "list": draft.list.rawValue, "waiting_for": draft.waitingFor, "details": draft.details,
            "due_date": wireNull(draft.dueDate?.isoString), "priority": draft.priority.rawValue,
            "context_project": wireNull(draft.contextProjectID?.rawValue), "context_tag": wireNull(draft.contextTagID?.rawValue),
        ]
    }

    /// What capture would do right now: the clean title, the tokens to highlight, the project
    /// and tags it would use or create, and the first problem.
    public func preview(_ draft: CaptureDraft, in state: GTDState) async throws -> CapturePreview {
        let readSet = try RustJSON.data(RustReadSet.make(state, actorID: context.actorID))
        let resolved = try await runtime.smartAddResolve(readSet: readSet, draft: RustJSON.data(draftObject(draft)))
        let value = try RustJSON.object(resolved)
        var tokens: [SmartAddToken] = []
        for token in try value.objects("tokens") {
            let start = try token.int("utf16_start")
            let end = try token.int("utf16_end")
            tokens.append(
                SmartAddToken(
                    kind: try token.string("kind") == "project" ? .project : .tag, utf16Range: start..<end,
                    name: try token.string("name")))
        }
        var problem: GTDValidationError?
        if let refusal = value.optionalObject("problem") {
            let wire = RustRefusal(reason: try refusal.string("reason"), field: refusal.optionalString("field"))
            problem = Self.validationError(wire, payload: [:], in: state)
            if problem == nil { throw RustDomainError.refused(reason: wire.reason, field: wire.field) }
        }
        return CapturePreview(
            title: try value.string("title"), project: try value.optionalObject("project").map(Self.classification),
            tags: try value.objects("tags").map(Self.classification), tokens: tokens, problem: problem)
    }

    private static func classification(_ value: WireObject) throws -> ClassificationPreview {
        ClassificationPreview(name: try value.string("name"), isNew: try value.string("type") == "new")
    }

    /// Captures `draft` as one atomic `task.smart_add` decided by the core: the task and the
    /// project and tags it names or creates. The ids are minted only for the records the
    /// draft creates, project first, then each new tag in token order.
    /// - Returns: the new task's id.
    @discardableResult
    public func capture(
        _ draft: CaptureDraft, at date: Date, to state: inout GTDState, makeTaskID: () -> TaskID = { .random() },
        makeProjectID: () -> ProjectID = { .random() }, makeTagID: () -> TagID = { .random() }
    ) async throws -> TaskID {
        let before = state
        let readSet = try RustJSON.data(RustReadSet.make(before, actorID: context.actorID))
        let draftData = try RustJSON.data(draftObject(draft))
        // The preview tells which records are new, so only those get an id.
        let resolution = try await preview(draft, in: before)
        if let problem = resolution.problem { throw problem }
        var ids = RustIDTable()
        var minted: WireObject = [:]
        if resolution.project?.isNew == true { minted["project"] = ids.new(makeProjectID().rawValue, prefix: "project") }
        var tagIDs: [String] = []
        for tag in resolution.tags where tag.isNew { tagIDs.append(ids.new(makeTagID().rawValue, prefix: "tag")) }
        minted["tags"] = tagIDs
        let proposal = try await runtime.smartAddPropose(
            readSet: readSet, draft: draftData, minted: RustJSON.data(minted))
        let payload: WireObject
        switch proposal {
        case .answered(let data): payload = try RustJSON.object(data)
        case .refused(let refusal): throw Self.refusalError(refusal, payload: [:], in: before)
        }
        let taskID = makeTaskID()
        let encoded = RustEncodedCommand(
            type: "task.smart_add", entityID: ids.new(taskID.rawValue, prefix: "task"), payload: payload, target: nil,
            allocatedIDs: [RustCommandEncoder.derivedFormulation(taskID, date)], issuedAt: date, navigatorProvider: nil,
            consentTextVersion: nil)
        let changeSet = try await decide(encoded, in: before, ids: ids)
        var next = before
        _ = try RustChangeApplier.apply(
            changeSet, to: &next, before: before, at: date, ids: ids, actorID: context.actorID)
        state = next
        return taskID
    }
}
