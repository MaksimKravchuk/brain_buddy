import Foundation

/// Projects and tags. Names are stored in the server's display form and are
/// unique among *active* records by normalized name; archived projects and
/// deleted tags can still be renamed, without a uniqueness check (server rule).
extension GTDReducer {
    // MARK: - Projects

    /// `POST /projects`. While replaying, a name already taken by an active
    /// project merges into it instead of failing. The existing project is
    /// left exactly as it is: the local creation's colour is not applied,
    /// even when the existing project has none, because it is the account's
    /// record and a colour change would be a separate `PATCH` the user never
    /// made to it (`OutboxReplayer.rewritingAfterMerge` drops later recolours
    /// for the same reason, and carries a local outcome over only where the
    /// account's project has none).
    static func createProject(
        _ command: GTDCommand.CreateProject, at date: Date, in state: inout GTDState, mode: ApplyMode
    ) throws(GTDValidationError) -> ApplyOutcome {
        if state.projects[command.projectID] != nil { return try satisfied(mode, else: .idAlreadyExists) }
        let name = try FieldRules.name(command.name, display: NameNormalizer.display)
        let color = try FieldRules.color(command.color)
        let outcome = try FieldRules.outcome(command.desiredOutcome)
        if let existing = activeProject(named: name, other: command.projectID, in: state) {
            guard mode == .replay else { throw .duplicateProjectName(existing.name) }
            return .mergedProject(into: existing.id)
        }
        state.projects[command.projectID] = ProjectRecord(
            id: command.projectID, name: name, color: color, state: .active, createdAt: date, desiredOutcome: outcome
        )
        return .applied
    }

    /// `PATCH /projects/{id}`: rename and recolour, allowed on archived projects.
    static func updateProject(
        _ command: GTDCommand.UpdateProject, in state: inout GTDState, mode: ApplyMode
    ) throws(GTDValidationError) -> ApplyOutcome {
        guard let project = state.projects[command.projectID] else { throw .projectNotFound }
        var updated = project
        if let name = command.name {
            updated.name = try FieldRules.name(name, display: NameNormalizer.display)
        }
        switch command.color {
        case .unchanged: break
        case .clear: updated.color = nil
        case .set(let color): updated.color = try FieldRules.color(color)
        }
        if updated == project { return try satisfied(mode, else: .nothingToChange) }
        if updated.state == .active, updated.name != project.name,
            let existing = activeProject(named: updated.name, other: project.id, in: state)
        {
            throw .duplicateProjectName(existing.name)
        }
        state.projects[command.projectID] = updated
        return .applied
    }

    /// `POST /projects/{id}/archive` (ADR-0020): every task keeps its project, so this
    /// changes no task. A project that is archived already is satisfied, and its
    /// `archivedAt` and `archivedBeforeLossless` stay as they are.
    static func archiveProject(
        _ id: ProjectID, at date: Date, in state: inout GTDState, mode: ApplyMode
    ) throws(GTDValidationError) -> ApplyOutcome {
        guard let project = state.projects[id] else { throw .projectNotFound }
        if project.state == .archived { return try satisfied(mode, else: .projectAlreadyArchived) }
        state.projects[id]?.state = .archived
        state.projects[id]?.archivedAt = date
        return .applied
    }

    /// `POST /projects/{id}/unarchive`: the project is active again, whatever the
    /// marker says; no task changes. Another active project with the same name
    /// refuses it, in replay too (the server would answer 409).
    static func unarchiveProject(
        _ id: ProjectID, in state: inout GTDState, mode: ApplyMode
    ) throws(GTDValidationError) -> ApplyOutcome {
        guard let project = state.projects[id] else { throw .projectNotFound }
        if project.state == .active { return try satisfied(mode, else: .nothingToChange) }
        if let existing = activeProject(named: project.name, other: id, in: state) {
            throw .unarchiveNameInUse(existing.name)
        }
        state.projects[id]?.state = .active
        state.projects[id]?.archivedAt = nil
        return .applied
    }

    /// `PATCH /projects/{id}` with `desired_outcome`, allowed on an archived project.
    static func setProjectOutcome(
        _ id: ProjectID, to outcome: String?, in state: inout GTDState, mode: ApplyMode
    ) throws(GTDValidationError) -> ApplyOutcome {
        guard let project = state.projects[id] else { throw .projectNotFound }
        let value = try FieldRules.outcome(outcome)
        if value == project.desiredOutcome { return try satisfied(mode, else: .nothingToChange) }
        state.projects[id]?.desiredOutcome = value
        return .applied
    }

    /// The active project, other than `id`, whose normalized name equals `name`'s.
    static func activeProject(named name: String, other id: ProjectID, in state: GTDState) -> ProjectRecord? {
        let key = NameNormalizer.project(name)
        return state.projects.values
            .filter { $0.id != id && $0.state == .active && NameNormalizer.project($0.name) == key }
            .min { $0.id < $1.id }
    }

    // MARK: - Tags

    /// `POST /tags`. While replaying, a name already taken by an active tag
    /// merges into it instead of failing.
    static func createTag(
        _ command: GTDCommand.CreateTag, at date: Date, in state: inout GTDState, mode: ApplyMode
    ) throws(GTDValidationError) -> ApplyOutcome {
        if state.tags[command.tagID] != nil { return try satisfied(mode, else: .idAlreadyExists) }
        let name = try FieldRules.name(command.name, display: NameNormalizer.tagDisplay)
        if let existing = activeTag(named: name, other: command.tagID, in: state) {
            guard mode == .replay else { throw .duplicateTagName(existing.name) }
            return .mergedTag(into: existing.id)
        }
        state.tags[command.tagID] = TagRecord(id: command.tagID, name: name, state: .active, createdAt: date)
        return .applied
    }

    /// `PATCH /tags/{id}`, allowed on deleted tags.
    static func renameTag(
        _ command: GTDCommand.RenameTag, in state: inout GTDState, mode: ApplyMode
    ) throws(GTDValidationError) -> ApplyOutcome {
        guard let tag = state.tags[command.tagID] else { throw .tagNotFound }
        let name = try FieldRules.name(command.name, display: NameNormalizer.tagDisplay)
        if name == tag.name { return try satisfied(mode, else: .nothingToChange) }
        if tag.state == .active, let existing = activeTag(named: name, other: tag.id, in: state) {
            throw .duplicateTagName(existing.name)
        }
        state.tags[command.tagID]?.name = name
        return .applied
    }

    /// `DELETE /tags/{id}`: a soft delete that removes the tag from every task.
    static func deleteTag(
        _ id: TagID, at date: Date, in state: inout GTDState, mode: ApplyMode
    ) throws(GTDValidationError) -> ApplyOutcome {
        guard let tag = state.tags[id] else { throw .tagNotFound }
        if tag.state == .deleted { return try satisfied(mode, else: .tagAlreadyDeleted) }
        state.tags[id]?.state = .deleted
        let tagged = state.tasks.values.filter { $0.tagIDs.contains(id) }.map(\.id)
        for taskID in tagged {
            state.tasks[taskID]?.tagIDs.removeAll { $0 == id }
            state.tasks[taskID]?.updatedAt = date
        }
        return .applied
    }

    /// The active tag, other than `id`, whose normalized name equals `name`'s
    /// (`name` is already in display form, as stored).
    static func activeTag(named name: String, other id: TagID, in state: GTDState) -> TagRecord? {
        let key = NameNormalizer.tag(name)
        return state.tags.values
            .filter { $0.id != id && $0.state == .active && NameNormalizer.tag($0.name) == key }
            .min { $0.id < $1.id }
    }
}
