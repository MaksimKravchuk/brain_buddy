import Foundation

/// The single place GTD rules live. The same function applies a user's
/// command on the device, replays queued commands over newer server state,
/// and runs identically in the app, widgets and App Intents — so every GTD
/// action works without a network.
///
/// It mirrors the server (ADR-0006 lifecycle, `backend/app/modules/tasks`):
/// see `docs/native-ios-app.md` for the rule table. Local-only differences:
/// titles are trimmed, an empty notes string clears the notes, only the
/// references a command sets are checked, and `serverRevision` is never
/// touched (it is the server's number). Subtask and comment edits do not bump
/// the parent task's `updatedAt`, as on the server. In `ApplyMode.replay` a
/// task creation or edit keeps whatever part of it still applies
/// (`Reducer+Replay.swift`).
public enum GTDReducer {
    /// Applies `command` as if issued at `date`.
    /// - Throws: `GTDValidationError` and leaves `state` untouched. Every
    ///   handler validates before its first write, so no copy is needed.
    @discardableResult
    public static func apply(
        _ command: GTDCommand, at date: Date, to state: inout GTDState, mode: ApplyMode = .interactive
    ) throws(GTDValidationError) -> ApplyOutcome {
        let outcome = try dispatch(command, at: date, to: &state, mode: mode)
        // FR-011: a person's child edit on this device, where the caller tracks
        // them (`GTDState.localChildEdits`); replay never counts.
        if mode == .interactive, state.localChildEdits != nil, let taskID = command.childEditTaskID {
            state.localChildEdits?[taskID, default: 0] += 1
        }
        return outcome
    }

    private static func dispatch(
        _ command: GTDCommand, at date: Date, to state: inout GTDState, mode: ApplyMode
    ) throws(GTDValidationError) -> ApplyOutcome {
        switch command {
        case .createProject(let create): try createProject(create, at: date, in: &state, mode: mode)
        case .updateProject(let update): try updateProject(update, in: &state, mode: mode)
        case .archiveProject(let id): try archiveProject(id, at: date, in: &state, mode: mode)
        case .setProjectOutcome(let id, let outcome): try setProjectOutcome(id, to: outcome, in: &state, mode: mode)
        case .unarchiveProject(let id): try unarchiveProject(id, in: &state, mode: mode)
        case .createTag(let create): try createTag(create, at: date, in: &state, mode: mode)
        case .renameTag(let rename): try renameTag(rename, in: &state, mode: mode)
        case .deleteTag(let id): try deleteTag(id, at: date, in: &state, mode: mode)
        case .createTask(let create): try createTask(create, at: date, in: &state, mode: mode)
        case .updateTask(let update): try updateTask(update, at: date, in: &state, mode: mode)
        case .transitionTask(let transition): try transitionTask(transition, at: date, in: &state, mode: mode)
        case .createSubtask(let create): try createSubtask(create, in: &state, mode: mode)
        case .updateSubtask(let update): try updateSubtask(update, in: &state, mode: mode)
        case .transitionSubtask(let transition): try transitionSubtask(transition, in: &state, mode: mode)
        case .createComment(let create): try createComment(create, at: date, in: &state, mode: mode)
        case .updateComment(let update): try updateComment(update, at: date, in: &state, mode: mode)
        case .decideTask(let decide): try decideTask(decide, at: date, in: &state, mode: mode)
        case .undoDecision(let id): try undoDecision(id, at: date, in: &state, mode: mode)
        case .autoParkTask(let park): try autoParkTask(park, at: date, in: &state, mode: mode)
        case .bulkRelease(let release): try bulkRelease(release, at: date, in: &state, mode: mode)
        case .undoBulkRelease(let id): try undoBulkRelease(id, at: date, in: &state, mode: mode)
        case .review(let command): try review(command, at: date, in: &state, mode: mode)
        }
    }

    // MARK: - Tasks

    /// `POST /tasks`: an open task at the end of its list's manual order.
    /// While replaying, references to projects and tags that are missing or
    /// no longer active are dropped rather than failing the task
    /// (`replayable(_:in:)`).
    static func createTask(
        _ command: GTDCommand.CreateTask, at date: Date, in state: inout GTDState, mode: ApplyMode
    ) throws(GTDValidationError) -> ApplyOutcome {
        if state.tasks[command.taskID] != nil { return try satisfied(mode, else: .idAlreadyExists) }
        let command = mode == .replay ? replayable(command, in: state) : command
        let title = try FieldRules.title(command.title)
        let details = try FieldRules.details(command.details)
        try FieldRules.checkWaitingForLength(command.waitingFor)
        try checkReferences(project: command.projectID, tags: command.tagIDs, in: state)
        let waitingFor = try FieldRules.waitingFor(command.waitingFor, entering: command.list)
        let taskState = command.list.taskState
        var maxOrderKey: Int?
        for task in state.tasks.values where task.state == taskState {
            maxOrderKey = max(maxOrderKey ?? task.orderKey, task.orderKey)
        }
        var task = TaskRecord(
            id: command.taskID, title: title, details: details, state: taskState,
            projectID: command.projectID, tagIDs: command.tagIDs, dueDate: command.dueDate,
            priority: command.priority, waitingFor: waitingFor, waitingSince: waitingFor == nil ? nil : date,
            orderKey: maxOrderKey.map { $0 + 1 } ?? 0, createdAt: date, updatedAt: date
        )
        // A task created in Next starts its first formulation (spec 020, FR-001).
        if taskState == .next {
            startClock(&task, id: formulationID(command.newFormulationID, task: command.taskID, at: date), at: date)
        }
        state.tasks[command.taskID] = task
        return .applied
    }

    /// `PATCH /tasks/{id}`: field edits; the list only changes through transitions.
    /// A user's edit is all or nothing. While replaying, each field change
    /// stands on its own: the ones the task can no longer take are dropped
    /// (`replayable(_:for:in:)`), the rest apply, and an edit with nothing
    /// left is already satisfied.
    static func updateTask(
        _ command: GTDCommand.UpdateTask, at date: Date, in state: inout GTDState, mode: ApplyMode
    ) throws(GTDValidationError) -> ApplyOutcome {
        guard let task = state.tasks[command.taskID] else { throw .taskNotFound }
        let changes = mode == .replay ? replayable(command.changes, for: task, in: state) : command.changes
        guard changes.hasChanges else { return try satisfied(mode, else: .nothingToChange) }
        var updated = task
        switch changes.title {
        case .unchanged: break
        case .clear: throw .emptyTitle
        case .set(let value): updated.title = try FieldRules.title(value)
        }
        switch changes.details {
        case .unchanged: break
        case .clear: updated.details = nil
        case .set(let value): updated.details = try FieldRules.details(value)
        }
        switch changes.priority {
        case .unchanged: break
        case .clear: throw .priorityRequired
        case .set(let value): updated.priority = value
        }
        if changes.waitingFor.isChanged {
            let note: String? = if case .set(let value) = changes.waitingFor { value } else { nil }
            try FieldRules.checkWaitingForLength(note)
            guard task.state == .waiting else { throw .waitingForOnlyOnWaitingTasks }
            // Clearing is `waitingForRequired`; editing the note keeps `waitingSince` (ADR-0006).
            updated.waitingFor = try FieldRules.waitingFor(note)
        }
        switch changes.projectID {
        case .unchanged: break
        case .clear: updated.projectID = nil
        case .set(let id):
            try checkReferences(project: id, tags: nil, in: state, current: task.projectID)
            updated.projectID = id
        }
        switch changes.tagIDs {
        case .unchanged: break
        case .clear: updated.tagIDs = []
        case .set(let ids):
            try checkReferences(project: nil, tags: ids, in: state)
            updated.tagIDs = ids
        }
        switch changes.dueDate {
        case .unchanged: break
        case .clear: updated.dueDate = nil
        case .set(let day): updated.dueDate = day
        }
        if updated == task { return try satisfied(mode, else: .nothingToChange) }
        if task.state == .next {
            // FR-001 / FR-002: a substantive title change closes the formulation
            // and starts a new one; FR-046: a due-date change raises the floor.
            if updated.title != task.title, FormulationKey.isSubstantive(from: task.title, to: updated.title) {
                let settings = clockSettings(state)
                closeClock(&updated, evaluating: task, settings: settings, at: date)
                startClock(&updated, id: formulationID(command.newFormulationID, task: task.id, at: date), at: date)
            }
            if updated.dueDate != task.dueDate {
                raiseClockFloor(&updated, to: date.addingTimeInterval(FormulationRule.dueDateFloor))
            }
        }
        updated.updatedAt = date
        state.tasks[command.taskID] = updated
        return .applied
    }

    /// `POST /tasks/{id}/transitions`. Transitions never touch order, project,
    /// tags, due date, priority or notes.
    static func transitionTask(
        _ command: GTDCommand.TransitionTask, at date: Date, in state: inout GTDState, mode: ApplyMode
    ) throws(GTDValidationError) -> ApplyOutcome {
        guard var task = state.tasks[command.taskID] else { throw .taskNotFound }
        let original = task
        switch command.action {
        case .complete, .cancel:
            let terminal: TaskState = command.action == .complete ? .completed : .cancelled
            if task.state == terminal { return try satisfied(mode, else: .taskNotOpen) }
            guard let list = task.openList else { throw .taskNotOpen }
            try FieldRules.checkWaitingForLength(command.waitingFor)
            task.state = terminal
            task.lastOpenList = list
            task.completedAt = terminal == .completed ? date : nil
            task.cancelledAt = terminal == .cancelled ? date : nil
            task.waitingFor = nil
            task.waitingSince = nil
        case .move:
            guard let list = command.toList else { throw .moveRequiresDestination }
            if task.state == list.taskState { return try satisfied(mode, else: .moveRequiresDifferentList) }
            guard task.isOpen else { throw .taskNotOpen }
            try enter(list, waitingFor: command.waitingFor, at: date, task: &task)
        case .reopen:
            guard let list = command.toList else { throw .reopenRequiresDestination }
            if task.isOpen {
                guard task.state == list.taskState else { throw .taskNotClosed }
                return try satisfied(mode, else: .taskNotClosed)
            }
            try enter(list, waitingFor: command.waitingFor, at: date, task: &task)
        }
        changeList(
            of: &task, from: original, settings: clockSettings(state), at: date,
            newFormulationID: command.newFormulationID
        )
        task.updatedAt = date
        state.tasks[command.taskID] = task
        return .applied
    }

    /// Puts `task` in the open `list`: terminal timestamps and the remembered
    /// list are cleared, and the waiting note is set on entering Waiting.
    private static func enter(
        _ list: OpenList, waitingFor raw: String?, at date: Date, task: inout TaskRecord
    ) throws(GTDValidationError) {
        let waitingFor = try FieldRules.waitingFor(raw, entering: list)
        task.state = list.taskState
        task.waitingFor = waitingFor
        task.waitingSince = waitingFor == nil ? nil : date
        task.completedAt = nil
        task.cancelledAt = nil
        task.lastOpenList = nil
    }
}

extension GTDCommand {
    /// The task whose children this command edits (FR-011's child-edit
    /// count): subtask create, edit and complete/reopen/cancel; comment add
    /// and edit. Nil for every other command.
    public var childEditTaskID: TaskID? {
        switch self {
        case .createSubtask(let create): create.taskID
        case .updateSubtask(let update): update.taskID
        case .transitionSubtask(let transition): transition.taskID
        case .createComment(let create): create.taskID
        case .updateComment(let update): update.taskID
        case .createProject, .updateProject, .archiveProject, .setProjectOutcome, .unarchiveProject, .createTag,
            .renameTag, .deleteTag, .createTask, .updateTask, .transitionTask, .decideTask, .undoDecision,
            .autoParkTask, .bulkRelease, .undoBulkRelease, .review:
            nil
        }
    }
}
