import Foundation

/// A bounded canonical list window. The cursor belongs to this generation and
/// the frozen query inputs; callers request another page only when needed.
public struct RustWorkspaceListPage: Sendable {
    public let generation: UInt64
    public let list: TaskListResult
    public let nextCursor: String?
}

/// Runtime issue IDs and catalog intents are kept intact. They are not
/// coerced into a legacy UUID/GTDCommand SyncIssue.
public struct RustWorkspaceIssue: Identifiable, Equatable, Sendable {
    public let id: String
    public let commandID: String
    public let reason: String
    public let localIntent: Data
    public let localText: [String: String]
    public let shownBaseRevision: String?
    public let dependentIDs: [String]
    public let createdAt: Date
}

public struct RustWorkspaceSyncState: Sendable {
    public let generation: UInt64
    public let pending: UInt64
    public let openIssues: UInt64
    public let lastSuccessAt: Date?
    public let oldestPendingAt: Date?
    public let deviceEpochState: String
    public let accountLinkState: String
}

extension RustDomainFacade {
    public func workspaceIssues(from result: Data) throws -> [RustWorkspaceIssue] {
        let root = try RustJSON.object(result)
        guard try root.string("kind") == "issues", let rows = root["value"] as? [WireObject] else {
            throw RustDomainError.malformedResult
        }
        return try rows.map { row in
            RustWorkspaceIssue(id: try row.string("issue_id"), commandID: try row.string("command_id"),
                reason: try row.string("reason"), localIntent: try RustJSON.data(row.object("local_intent")),
                localText: row["local_text"] as? [String: String] ?? [:],
                shownBaseRevision: row.optionalString("shown_base_revision"), dependentIDs: try row.strings("dependent_ids"),
                createdAt: try row.instant("created_at"))
        }
    }

    public func workspaceSyncState(from result: Data) throws -> RustWorkspaceSyncState {
        let row = try RustJSON.object(result)
        func counter(_ key: String) throws -> UInt64 {
            guard let value = UInt64(try row.string(key)) else { throw RustDomainError.malformedResult }
            return value
        }
        return RustWorkspaceSyncState(generation: try counter("projection_generation"), pending: try counter("pending"),
            openIssues: try counter("open_issues"), lastSuccessAt: try row.optionalInstant("last_success_at"),
            oldestPendingAt: try row.optionalInstant("oldest_pending_at"), deviceEpochState: try row.string("device_epoch_state"),
            accountLinkState: try row.string("account_link_state"))
    }

    public func workspaceRecordRequest(_ kind: String, localID: String,
                                       bindings: [RustWorkspaceIdentityBinding] = []) -> RustWorkspaceRecordRequest {
        var ids = RustIDTable(bindings: bindings)
        let prefixes = ["review_session": "review", "review_decision": "decision", "review_bulk_release": "bulk"]
        return RustWorkspaceRecordRequest(entityType: kind,
            recordKey: [ids.wire(localID, prefix: prefixes[kind] ?? kind)])
    }

    /// Applies only exact requested after-images. Null proves absence for that
    /// identity, so the caller may evict it after its generation fence passed.
    public func workspaceApplyRecords(from result: Data, requests: [RustWorkspaceRecordRequest],
                                      to state: inout GTDState, at date: Date) throws {
        let root = try RustJSON.object(result)
        guard try root.string("kind") == "records", let rows = root["value"] as? [Any],
              rows.count == requests.count else { throw RustDomainError.malformedResult }
        let ids = RustIDTable(stripsUUIDPrefixes: true)
        var next = state
        for index in requests.indices {
            if let row = rows[index] as? WireObject {
                guard try row.string("entity_type") == requests[index].entityType else { throw RustDomainError.malformedResult }
                try applyOwned(requests[index].entityType, value: row.object("value"), to: &next, at: date, ids: ids)
                continue
            }
            guard rows[index] is NSNull, let raw = requests[index].recordKey.first else { throw RustDomainError.malformedResult }
            let id = ids.swift(raw)
            switch requests[index].entityType {
            case "task": next.tasks[TaskID(id)] = nil
            case "project": next.projects[ProjectID(id)] = nil
            case "tag": next.tags[TagID(id)] = nil
            case "review_session": next.review.sessions[ReviewSessionID(id)] = nil
            case "review_decision": next.review.decisions[DecisionID(id)] = nil
            case "review_bulk_release": next.review.bulkReleases[BulkID(id)] = nil
            case "review_settings": next.review.settings = ReviewSettings()
            case "review_navigator_consent": next.review.navigatorConsents[id] = nil
            case "review_decision_queue":
                next.review.sessions[ReviewSessionID(id)]?.decisionQueue = nil
                next.review.sessions[ReviewSessionID(id)]?.setAsideTaskIDs = []
            case "review_receipt":
                guard requests[index].recordKey.count == 2,
                      let kind = ReceiptKind(rawValue: requests[index].recordKey[1]) else { throw RustDomainError.malformedResult }
                next.review.removeReceipt(for: TaskID(id), kind: kind)
            case "review_park_ack":
                guard requests[index].recordKey.count == 2 else { throw RustDomainError.malformedResult }
                let formulation = FormulationID(ids.swift(requests[index].recordKey[1]))
                next.review.parkAcks.removeAll { $0.taskID == TaskID(id) && $0.formulationID == formulation }
            default: throw RustDomainError.malformedResult
            }
        }
        state = next
    }

    public func workspaceCaptureDraft(_ draft: CaptureDraft,
                                      bindings: [RustWorkspaceIdentityBinding] = []) throws -> Data {
        var ids = RustIDTable(bindings: bindings)
        return try RustJSON.data(["text": draft.text, "list": draft.list.rawValue,
            "waiting_for": draft.waitingFor, "details": draft.details,
            "due_date": wireNull(draft.dueDate?.isoString), "priority": draft.priority.rawValue,
            "context_project": ids.optional(draft.contextProjectID?.rawValue, prefix: "project"),
            "context_tag": ids.optional(draft.contextTagID?.rawValue, prefix: "tag")])
    }

    public func workspaceCapturePreview(from result: Data, in shown: GTDState) throws -> CapturePreview {
        let value = try RustJSON.object(result)
        let tokens = try value.objects("tokens").map { token in
            SmartAddToken(kind: try token.string("kind") == "project" ? .project : .tag,
                utf16Range: try token.int("utf16_start")..<token.int("utf16_end"), name: try token.string("name"))
        }
        func classification(_ row: WireObject) throws -> ClassificationPreview {
            ClassificationPreview(name: try row.string("name"), isNew: try row.string("type") == "new")
        }
        var problem: GTDValidationError?
        if let refusal = value.optionalObject("problem") {
            let wire = RustRefusal(reason: try refusal.string("reason"), field: refusal.optionalString("field"))
            problem = Self.validationError(wire, payload: [:], in: shown, ids: RustIDTable(stripsUUIDPrefixes: true))
            if problem == nil { throw RustDomainError.refused(reason: wire.reason, field: wire.field) }
        }
        return CapturePreview(title: try value.string("title"),
            project: try value.optionalObject("project").map(classification),
            tags: try value.objects("tags").map(classification), tokens: tokens, problem: problem)
    }

    public func workspaceCaptureMinted(projectID: ProjectID?, tagIDs: [TagID]) throws -> Data {
        var ids = RustIDTable()
        var minted: WireObject = ["tags": tagIDs.map { ids.tag($0) }]
        if let projectID { minted["project"] = ids.project(projectID) }
        return try RustJSON.data(minted)
    }

    public func workspaceCaptureCommand(taskID: TaskID, commandID: UUID, proposal: RustWorkspacePage) -> RustWorkspaceCommand {
        var ids = RustIDTable()
        return RustWorkspaceCommand(commandID: commandID.uuidString.lowercased(), commandType: "task.smart_add",
            entityID: ids.task(taskID), payload: proposal.result)
    }

    public func workspaceListQuery(_ destination: Destination, options: ListOptions,
                                   after cursor: String? = nil,
                                   bindings: [RustWorkspaceIdentityBinding] = []) throws -> Data {
        var ids = RustIDTable(stripsUUIDPrefixes: true, bindings: bindings)
        let mode: WireObject
        switch destination {
        case .list(let list): mode = ["type": "open_list", "list": list.rawValue]
        case .project(let id): mode = ["type": "project", "project_id": ids.project(id)]
        case .tag(let id): mode = ["type": "tag", "tag_id": ids.tag(id)]
        case .agenda: mode = ["type": "agenda"]
        case .dateView(let view): mode = ["type": "date_view", "view": view.rawValue]
        case .history(let kind): mode = ["type": "history", "kind": kind.rawValue]
        case .search(let text): mode = ["type": "search", "text": text]
        }
        return try RustJSON.data(["kind": "list_mode", "mode": mode,
            "options": ["sort": options.sort.rawValue, "group_by_project": options.groupByProject,
                "show_completed": options.showCompleted, "show_cancelled": options.showCancelled,
                "priorities": options.priorities.map(\.rawValue).sorted(),
                "tag_filter": ids.optional(options.tagFilter?.rawValue, prefix: "tag")],
            "page": ["limit": 200, "after": wireNull(cursor)]])
    }

    public func workspaceReadQuery(_ kind: String, taskID: TaskID? = nil,
                                  sessionID: ReviewSessionID? = nil, filter: String? = nil,
                                  bindings: [RustWorkspaceIdentityBinding] = []) throws -> Data {
        var ids = RustIDTable(stripsUUIDPrefixes: true, bindings: bindings)
        var query: WireObject = ["kind": kind]
        if let taskID { query["task_id"] = ids.task(taskID) }
        if let sessionID { query["session_id"] = ids.session(sessionID) }
        if let filter { query["filter"] = filter }
        return try RustJSON.data(query)
    }

    public func workspaceQueryInputs(at date: Date, zone: String, reviewExposed: Bool) throws -> Data {
        try RustJSON.data(["now": RustInstant.format(date), "device_zone": zone,
            "policy": ["weekly_review": reviewExposed, "navigator_provider": NSNull(),
                       "navigator_available": false, "consent_text_version": 1]])
    }

    /// Decodes the query's own after-image. List rows omit child contents;
    /// detail answers replace the authoritative child set, including emptiness.
    public func workspaceTask(from result: Data, keeping previous: TaskRecord? = nil,
                              detail: Bool, at date: Date) throws -> TaskRecord {
        let root = try RustJSON.object(result)
        let row = root["kind"] != nil ? try root.object("value") : root
        return try workspaceTask(row, keeping: previous, detail: detail, at: date)
    }

    public func workspaceList(from page: RustWorkspacePage, keeping state: GTDState,
                              at date: Date) throws -> RustWorkspaceListPage {
        guard let generation = UInt64(page.projectionGeneration) else { throw RustDomainError.malformedResult }
        let root = try RustJSON.object(page.result)
        guard try root.string("kind") == "list_mode" else { throw RustDomainError.malformedResult }
        let value = try root.object("value")
        let ids = RustIDTable(stripsUUIDPrefixes: true)
        let sections = try value.objects("sections").map { section -> TaskSection in
            let kind = try section.object("kind")
            let sectionKind: TaskSection.Kind
            switch try kind.string("type") {
            case "open": sectionKind = .open
            case "project": sectionKind = .project(kind.optionalString("project_id").map { ProjectID(ids.swift($0)) })
            case "list":
                guard let list = OpenList(rawValue: try kind.string("list")) else { throw RustDomainError.malformedResult }
                sectionKind = .list(list)
            case "date_view":
                guard let view = DateView(rawValue: try kind.string("view")) else { throw RustDomainError.malformedResult }
                sectionKind = .dateView(view)
            case "completed": sectionKind = .completed
            case "cancelled": sectionKind = .cancelled
            default: throw RustDomainError.malformedResult
            }
            let wireID = try section.string("id")
            let sectionID = wireID.hasPrefix("project:")
                ? "project:" + ids.swift(String(wireID.dropFirst(8))) : wireID
            let tasks = try section.objects("items").map { row in
                let id = TaskID(ids.swift(try row.string("id")))
                return try workspaceTask(row, keeping: state.tasks[id], detail: false, at: date)
            }
            return TaskSection(id: sectionID, title: section.optionalString("title"), kind: sectionKind, tasks: tasks)
        }
        return RustWorkspaceListPage(generation: generation,
            list: TaskListResult(sections: sections, openCount: try value.int("open_count")),
            nextCursor: page.collectionNextCursor ?? value.optionalString("next_cursor"))
    }

    public func workspaceCounts(from result: Data) throws -> ListCounts {
        let root = try RustJSON.object(result)
        guard try root.string("kind") == "list_counts" else { throw RustDomainError.malformedResult }
        let value = try root.object("value")
        return ListCounts(inbox: try value.int("inbox"), next: try value.int("next"),
            waiting: try value.int("waiting"), someday: try value.int("someday"),
            overdue: try value.int("overdue"), today: try value.int("today"))
    }

    public func workspaceProjects(from result: Data, keeping previous: GTDState, at date: Date) throws -> [ProjectSummary] {
        let root = try RustJSON.object(result)
        guard try root.string("kind") == "projects", let rows = root["value"] as? [WireObject] else {
            throw RustDomainError.malformedResult
        }
        let ids = RustIDTable(stripsUUIDPrefixes: true)
        return try rows.map { row in
            let project = try row.object("project")
            let id = ProjectID(ids.swift(try project.string("id")))
            var state = GTDState.empty
            state.projects[id] = previous.projects[id]
            try applyOwned("project", value: project, to: &state, at: date, ids: ids)
            guard let record = state.projects[id] else { throw RustDomainError.malformedResult }
            return ProjectSummary(project: record, openTaskCount: try row.int("open_task_count"),
                                  nextActionCount: try row.int("next_action_count"))
        }
    }

    public func workspaceTags(from result: Data, keeping previous: GTDState, at date: Date) throws -> [TagSummary] {
        let root = try RustJSON.object(result)
        guard try root.string("kind") == "tags", let rows = root["value"] as? [WireObject] else {
            throw RustDomainError.malformedResult
        }
        let ids = RustIDTable(stripsUUIDPrefixes: true)
        return try rows.map { row in
            let tag = try row.object("tag")
            let id = TagID(ids.swift(try tag.string("id")))
            var state = GTDState.empty
            state.tags[id] = previous.tags[id]
            try applyOwned("tag", value: tag, to: &state, at: date, ids: ids)
            guard let record = state.tags[id] else { throw RustDomainError.malformedResult }
            return TagSummary(tag: record, openTaskCount: try row.int("open_task_count"))
        }
    }

    private func workspaceTask(_ row: WireObject, keeping previous: TaskRecord?, detail: Bool,
                               at date: Date) throws -> TaskRecord {
        let ids = RustIDTable(stripsUUIDPrefixes: true)
        let id = TaskID(ids.swift(try row.string("id")))
        var state = GTDState.empty
        state.tasks[id] = previous
        var record = row
        record["consecutive_stalled_formulations"] = row["consecutive_stalled_formulations"]
            ?? row.optionalObject("formulation")?["consecutive_stalled"]
            ?? previous?.consecutiveStalledFormulations ?? 0
        try applyOwned("task", value: record, to: &state, at: date, ids: ids)
        if detail {
            state.tasks[id]?.subtasks = []
            state.tasks[id]?.comments = []
            state.tasks[id]?.childrenSyncedAt = date
            for child in try row.objects("subtasks") {
                var value = child
                value["task_id"] = try row.string("id")
                try applyOwned("subtask", value: value, to: &state, at: date, ids: ids)
            }
            for child in try row.objects("comments") {
                var value = child
                value["task_id"] = try row.string("id")
                try applyOwned("comment", value: value, to: &state, at: date, ids: ids)
            }
        }
        guard let task = state.tasks[id] else { throw RustDomainError.malformedResult }
        return task
    }

    func applyOwned(_ kind: String, value: WireObject, to state: inout GTDState,
                            at date: Date, ids: RustIDTable) throws {
        let before = state
        _ = try RustChangeApplier.apply(["changes": [["operation": "upsert", "entity_type": kind, "value": value]],
                                        "outcome": "applied"], to: &state, before: before, at: date,
                                       ids: ids, actorID: context.actorID)
    }
}
