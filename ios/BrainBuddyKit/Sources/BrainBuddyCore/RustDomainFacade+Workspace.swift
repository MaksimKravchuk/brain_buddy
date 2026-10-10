import Foundation

extension RustDomainFacade {
    /// Encodes an intent only; the runtime decides under its DB write lock.
    /// afterCommand names an earlier command in the same all-or-nothing gesture
    /// that writes this target, so no guessed revision replaces its result.
    public func workspaceCommand(_ command: GTDCommand, commandID: UUID, at date: Date,
                                 in state: GTDState, afterCommand: UUID? = nil) throws -> RustWorkspaceCommand {
        var ids = RustIDTable()
        _ = RustReadSet.make(state, actorID: context.actorID, ids: &ids)
        let encoded = try RustCommandEncoder.encode(command, at: date, in: state, scopeID: context.scopeID, ids: &ids)
        var preconditions: [WireObject] = []
        if let target = encoded.target {
            if let afterCommand {
                preconditions = [["after_command": ["command_id": afterCommand.uuidString.lowercased(),
                    "entity_type": target.entityType, "entity_id": target.id]]]
            } else {
                preconditions = [["entity_type": target.entityType, "entity_id": target.id,
                                  "edit_revision": String(target.revision)]]
            }
        }
        return RustWorkspaceCommand(commandID: commandID.uuidString.lowercased(), commandType: encoded.type,
            entityID: encoded.entityID, payload: try RustJSON.data(encoded.payload),
            preconditions: try RustJSON.data(preconditions))
    }

    public func workspaceValidationError(_ refusal: RustRefusal, command: RustWorkspaceCommand,
                                         in state: GTDState) throws -> GTDValidationError? {
        var ids = RustIDTable(stripsUUIDPrefixes: true)
        _ = RustReadSet.make(state, actorID: context.actorID, ids: &ids)
        return Self.validationError(refusal, payload: try RustJSON.object(command.payload), in: state, ids: ids)
    }

    /// Adopts an authoritative bootstrap image, retaining device-local facts on
    /// surviving records. List screens use bounded query results after bootstrap.
    public func workspaceState(from snapshot: RustWorkspaceSnapshot, keeping previous: GTDState,
                               at date: Date) throws -> GTDState {
        guard let records = try JSONSerialization.jsonObject(with: snapshot.records) as? [WireObject] else {
            throw RustDomainError.malformedResult
        }
        let ids = RustIDTable(stripsUUIDPrefixes: true)
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
