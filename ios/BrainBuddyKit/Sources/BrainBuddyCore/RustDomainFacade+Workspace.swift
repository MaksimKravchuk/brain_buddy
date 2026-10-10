import Foundation

public struct RustWorkspaceReviewPreparation: Sendable {
    public let readSet: Data
    public let aliases: Data
    public let decisionQueues: UInt64
    public let unseenParkAcknowledgements: UInt64
}

extension RustDomainFacade {
    /// Runtime IDs remain canonical. A UUID-shaped suffix is not alias proof.
    public func workspaceLocalID(_ canonical: String) -> String {
        RustIDTable(stripsUUIDPrefixes: false).swift(canonical)
    }

    public func workspaceIdentityBindings(from data: Data) throws -> [RustWorkspaceIdentityBinding] {
        try RustJSON.array(data).map { value in
            guard let row = value as? WireObject else { throw RustDomainError.malformedResult }
            return RustWorkspaceIdentityBinding(entityType: try row.string("entity_type"),
                localID: try row.string("local_id"), canonicalID: try row.string("server_id"))
        }
    }

    /// Only identifiers explicitly touched by this gesture; no database-wide
    /// native read set is sent back to the runtime.
    public func workspaceIdentityRequests(for commands: [GTDCommand], in shown: GTDState,
                                         at date: Date) throws -> [RustWorkspaceIdentityRequest] {
        var ids = RustIDTable(collectsRequests: true)
        for command in commands {
            _ = try RustCommandEncoder.encode(command, at: date, in: shown, scopeID: context.scopeID, ids: &ids)
        }
        return ids.requested.sorted {
            ($0.entityType, $0.localID) < ($1.entityType, $1.localID)
        }
    }

    /// One migration-only use of the established native Review codec. This
    /// result is admitted atomically by the runtime, never used as a query.
    public func workspacePrepareLegacyReview(_ source: GTDState,
        bindings: [RustWorkspaceIdentityBinding]) throws -> RustWorkspaceReviewPreparation {
        var admitted = bindings
        var additions: [WireObject] = []
        for decision in source.review.decisions.values.sorted(by: { $0.id < $1.id }) {
            guard let before = decision.undo?.taskBefore, let server = before.serverID,
                  !admitted.contains(where: { $0.entityType == "task" && $0.localID == before.id.rawValue }) else { continue }
            // Exact source metadata only. The runtime rereads the immutable
            // carrier and validates this proof before admitting the alias.
            admitted.append(RustWorkspaceIdentityBinding(entityType: "task", localID: before.id.rawValue, canonicalID: server))
            additions.append(["entity_type": "task", "local_id": before.id.rawValue, "server_id": server])
        }
        var ids = RustIDTable(bindings: admitted, canonicalFormulationIDs: Self.workspaceFormulationIDs(in: source))
        var records = RustReadSet.make(source, actorID: context.actorID, ids: &ids)
        for key in ["tasks", "projects", "tags", "subtasks", "comments"] { records.removeValue(forKey: key) }
        let queues = records["decision_queues"] as? WireObject ?? [:]
        let unseen = (records["park_acks"] as? [WireObject] ?? []).filter { $0["seen_at"] is NSNull }.count
        return RustWorkspaceReviewPreparation(readSet: try RustJSON.data(records), aliases: try RustJSON.data(additions),
            decisionQueues: UInt64(queues.count), unseenParkAcknowledgements: UInt64(unseen))
    }

    /// Encodes an intent only; the runtime decides under its DB write lock.
    /// afterCommand names an earlier command in the same all-or-nothing gesture
    /// that writes this target, so no guessed revision replaces its result.
    public func workspaceCommand(_ command: GTDCommand, commandID: UUID, at date: Date,
                                 in state: GTDState, afterCommand: UUID? = nil,
                                 bindings: [RustWorkspaceIdentityBinding] = [],
                                 intendedTagMembership: [String: [TagID]] = [:],
                                 intendedDeletedTags: Set<String> = []) throws -> RustWorkspaceCommand {
        let proved = Self.workspaceCanonicalBindings(in: state) + bindings
        var ids = RustIDTable(bindings: proved, canonicalFormulationIDs: Self.workspaceFormulationIDs(in: state))
        let shown = Self.workspaceAliasView(state, bindings: bindings)
        var encoded = try RustCommandEncoder.encode(command, at: date, in: shown, scopeID: context.scopeID, ids: &ids,
            intendedTagMembership: intendedTagMembership, intendedDeletedTags: intendedDeletedTags)
        if case .undoDecision(let id) = command {
            guard let decision = shown.review.decisions[id], let revision = decision.taskAfter.serverRevision else {
                throw RustDomainError.refused(reason: "incomplete_read_set", field: "decision")
            }
            encoded.target = RustEncodedCommand.Target(entityType: "task", id: ids.task(decision.taskID), revision: revision)
        }
        var preconditions: [WireObject] = []
        if let afterCommand, let type = encoded.target?.entityType ?? Self.workspaceTargetType(encoded.type) {
            preconditions = [["after_command": ["command_id": afterCommand.uuidString.lowercased(),
                "entity_type": type, "entity_id": encoded.target?.id ?? encoded.entityID]]]
        } else if let target = encoded.target {
            preconditions = [["entity_type": target.entityType, "entity_id": target.id,
                              "edit_revision": String(target.revision)]]
        }
        return RustWorkspaceCommand(commandID: commandID.uuidString.lowercased(), commandType: encoded.type,
            entityID: encoded.entityID, payload: try RustJSON.data(encoded.payload),
            preconditions: try RustJSON.data(preconditions))
    }

    /// Sequential intent encoding advances only explicit desired memberships.
    /// It never decides a command or publishes a scratch projection/revision.
    public func workspaceCommands(_ commands: [GTDCommand], commandIDs: [UUID], at dates: [Date],
                                  in shown: GTDState, bindings: [RustWorkspaceIdentityBinding] = []) throws
        -> [RustWorkspaceCommand] {
        guard commands.count == commandIDs.count, commands.count == dates.count else {
            throw RustDomainError.malformedResult
        }
        var membership: [String: [TagID]] = [:]
        var deletedTags: Set<String> = []
        var earlier: [String: UUID] = [:]
        var result: [RustWorkspaceCommand] = []
        var ids = RustIDTable(bindings: Self.workspaceCanonicalBindings(in: shown) + bindings)
        for index in commands.indices {
            var encoded = try workspaceCommand(commands[index], commandID: commandIDs[index], at: dates[index],
                in: shown, bindings: bindings, intendedTagMembership: membership, intendedDeletedTags: deletedTags)
            let primary = try Self.workspacePrimaryTarget(encoded)
            if let primary, let previous = earlier[primary], !encoded.commandType.hasSuffix(".create") {
                encoded = try workspaceCommand(commands[index], commandID: commandIDs[index], at: dates[index],
                    in: shown, afterCommand: previous, bindings: bindings, intendedTagMembership: membership,
                    intendedDeletedTags: deletedTags)
            }
            if case .bulkRelease(let release) = commands[index] {
                var refs = try RustJSON.array(encoded.preconditions)
                for task in release.taskIDs {
                    let target = ids.task(task)
                    if let previous = earlier["task:" + target] {
                        refs.append(["after_command": ["command_id": previous.uuidString.lowercased(),
                            "entity_type": "task", "entity_id": target]])
                    }
                }
                encoded = RustWorkspaceCommand(commandID: encoded.commandID, commandType: encoded.commandType,
                    entityID: encoded.entityID, payload: encoded.payload, preconditions: try RustJSON.data(refs))
            }
            if case .deleteTag = commands[index] {
                var guards = try RustJSON.array(encoded.preconditions)
                var guarded: Set<String> = []
                for later in commands.indices where later > index {
                    let frozen = try workspaceCommand(commands[later], commandID: commandIDs[later], at: dates[later],
                        in: shown, bindings: bindings)
                    for value in try RustJSON.array(frozen.preconditions) {
                        guard let row = value as? WireObject, row.optionalString("entity_type") == "task",
                              let task = row.optionalString("entity_id"), row.optionalString("edit_revision") != nil,
                              guarded.insert(task).inserted else { continue }
                        // Only an explicit later shown dependency. The store
                        // decides whether this delete actually produced a task.
                        guards.append(row)
                    }
                }
                encoded = RustWorkspaceCommand(commandID: encoded.commandID, commandType: encoded.commandType,
                    entityID: encoded.entityID, payload: encoded.payload, preconditions: try RustJSON.data(guards),
                    dependsOn: encoded.dependsOn, admissionTokens: encoded.admissionTokens)
            }
            result.append(encoded)
            if let primary { earlier[primary] = commandIDs[index] }
            switch commands[index] {
            case .createTask(let create): membership[ids.task(create.taskID)] = create.tagIDs
            case .updateTask(let update):
                switch update.changes.tagIDs {
                case .set(let tags): membership[ids.task(update.taskID)] = tags
                case .clear: membership[ids.task(update.taskID)] = []
                case .unchanged: break
                }
            case .deleteTag(let tag):
                let removed = ids.tag(tag)
                deletedTags.insert(removed)
                for key in Array(membership.keys) {
                    membership[key] = membership[key]?.filter { ids.tag($0) != removed }
                }
            case .bulkRelease(let release):
                // Requested identities only: the runtime resolves the actual
                // produced version, or the frozen guard for a proven skipped
                // item. The mapper never predicts eligibility or revisions.
                for task in release.taskIDs { earlier["task:" + ids.task(task)] = commandIDs[index] }
            default: break
            }
        }
        return result
    }

    private static func workspacePrimaryTarget(_ command: RustWorkspaceCommand) throws -> String? {
        if let first = try RustJSON.array(command.preconditions).first as? WireObject {
            let target = first.optionalObject("after_command") ?? first
            if let type = target.optionalString("entity_type"), let id = target.optionalString("entity_id") {
                return type + ":" + id
            }
        }
        guard let type = workspaceTargetType(command.commandType), let id = command.entityID else { return nil }
        return type + ":" + id
    }

    private static func workspaceTargetType(_ type: String) -> String? {
        let prefix = type.split(separator: ".").first.map(String.init)
        if let prefix, ["task", "project", "tag", "subtask", "comment"].contains(prefix) { return prefix }
        switch type {
        case "review.decide", "review.auto_park": return "task"
        case "review.undo_decision": return "review_decision"
        case "review.bulk_release", "review.bulk_undo": return "review_bulk_release"
        default: return nil
        }
    }

    public func workspaceValidationError(_ refusal: RustRefusal, command: RustWorkspaceCommand,
                                         in state: GTDState) throws -> GTDValidationError? {
        let ids = RustIDTable(stripsUUIDPrefixes: false)
        return Self.validationError(refusal, payload: try RustJSON.object(command.payload), in: state, ids: ids)
    }

    /// An encoding lookup view of the shown records, not a projected state.
    /// An imported command can still name the local ID whose alias the store
    /// proved. Its revision comes from that same shown canonical record.
    private static func workspaceAliasView(_ state: GTDState, bindings: [RustWorkspaceIdentityBinding]) -> GTDState {
        let ids = RustIDTable(stripsUUIDPrefixes: false)
        var shown = state
        for binding in bindings {
            guard let canonical = binding.canonicalID else { continue }
            let key = ids.swift(canonical)
            switch binding.entityType {
            case "task":
                if let task = state.tasks[TaskID(key)] { shown.tasks[TaskID(binding.localID)] = task }
            case "project":
                if let project = state.projects[ProjectID(key)] { shown.projects[ProjectID(binding.localID)] = project }
            case "tag":
                if let tag = state.tags[TagID(key)] { shown.tags[TagID(binding.localID)] = tag }
            case "review_session":
                if let session = state.review.sessions[ReviewSessionID(key)] {
                    shown.review.sessions[ReviewSessionID(binding.localID)] = session
                }
            case "review_decision":
                if let decision = state.review.decisions[DecisionID(key)] {
                    shown.review.decisions[DecisionID(binding.localID)] = decision
                }
            default: break
            }
        }
        return shown
    }

    /// Adopts an authoritative bootstrap image, retaining device-local facts on
    /// surviving records. List screens use bounded query results after bootstrap.
    public func workspaceState(from snapshot: RustWorkspaceSnapshot, keeping previous: GTDState,
                               at date: Date) throws -> GTDState {
        guard let records = try JSONSerialization.jsonObject(with: snapshot.records) as? [WireObject] else {
            throw RustDomainError.malformedResult
        }
        let ids = RustIDTable(stripsUUIDPrefixes: false)
        var next = previous
        let byKind = try Dictionary(grouping: records) { try $0.string("entity_type") }
        func identifiers(_ kind: String) throws -> Set<String> {
            try Set((byKind[kind] ?? []).map { ids.swift(try $0.object("value").string("id")) })
        }
        let tasks = try identifiers("task")
        let projects = try identifiers("project")
        let tags = try identifiers("tag")
        let subtasks = try identifiers("subtask")
        let comments = try identifiers("comment")
        next.tasks = next.tasks.filter { tasks.contains($0.key.rawValue) }
        next.projects = next.projects.filter { projects.contains($0.key.rawValue) }
        next.tags = next.tags.filter { tags.contains($0.key.rawValue) }
        for id in next.tasks.keys {
            next.tasks[id]?.subtasks.removeAll { !subtasks.contains($0.id.rawValue) }
            next.tasks[id]?.comments.removeAll { !comments.contains($0.id.rawValue) }
        }
        next.review.settings = ReviewSettings()
        let sessions = try identifiers("review_session")
        let decisions = try identifiers("review_decision")
        let releases = try identifiers("review_bulk_release")
        next.review.sessions = next.review.sessions.filter { sessions.contains($0.key.rawValue) }
        for id in next.review.sessions.keys {
            next.review.sessions[id]?.decisionQueue = nil
            next.review.sessions[id]?.setAsideTaskIDs = []
        }
        next.review.decisions = next.review.decisions.filter { decisions.contains($0.key.rawValue) }
        next.review.receipts = []
        next.review.parkAcks = []
        next.review.bulkReleases = next.review.bulkReleases.filter { releases.contains($0.key.rawValue) }
        next.review.navigatorConsents = [:]
        let order = ["project", "tag", "task", "subtask", "comment", "review_settings", "review_session",
                     "review_decision_queue", "review_decision", "review_receipt", "review_park_ack",
                     "review_bulk_release", "review_navigator_consent"]
        let changes = try order.flatMap { kind in
            try (byKind[kind] ?? []).map { record -> WireObject in
                ["operation": "upsert", "entity_type": kind, "value": try record.object("value")]
            }
        }
        _ = try RustChangeApplier.apply(["changes": changes, "outcome": "applied"], to: &next,
                                       before: previous, at: date, ids: ids, actorID: context.actorID)
        return next
    }
}


extension RustDomainFacade {
    private static func workspaceCanonicalBindings(in state: GTDState) -> [RustWorkspaceIdentityBinding] {
        var result: [RustWorkspaceIdentityBinding] = []
        func append(_ type: String, _ id: String) {
            result.append(.init(entityType: type, localID: id, canonicalID: id))
        }
        for task in state.tasks.values {
            append("task", task.id.rawValue)
            if let project = task.projectID { append("project", project.rawValue) }
            for tag in task.tagIDs { append("tag", tag.rawValue) }
            for child in task.subtasks { append("subtask", child.id.rawValue) }
            for child in task.comments { append("comment", child.id.rawValue) }
        }
        for id in state.projects.keys { append("project", id.rawValue) }
        for id in state.tags.keys { append("tag", id.rawValue) }
        for id in state.review.sessions.keys { append("review_session", id.rawValue) }
        for decision in state.review.decisions.values {
            append("review_decision", decision.id.rawValue)
            append("task", decision.taskID.rawValue)
        }
        for id in state.review.bulkReleases.keys { append("review_bulk_release", id.rawValue) }
        return result
    }

    private static func workspaceFormulationIDs(in state: GTDState) -> Set<String> {
        var ids = Set(state.tasks.values.compactMap { $0.formulation?.id.rawValue })
        ids.formUnion(state.tasks.values.compactMap { $0.parked?.formulationID.rawValue })
        ids.formUnion(state.review.parkAcks.map { $0.formulationID.rawValue })
        ids.formUnion(state.review.decisions.values.compactMap { $0.formulationID?.rawValue })
        ids.formUnion(state.review.decisions.values.compactMap { $0.undo?.taskBefore.formulation?.id.rawValue })
        ids.formUnion(state.review.decisions.values.compactMap { $0.undo?.taskBefore.parked?.formulationID.rawValue })
        return ids
    }
}
