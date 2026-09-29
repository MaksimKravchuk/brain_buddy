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
/// the parent task's `updatedAt`, as on the server.
public enum GTDReducer {
    /// Applies `command` as if issued at `date`.
    /// - Throws: `GTDValidationError` and leaves `state` untouched. Every
    ///   handler validates before its first write, so no copy is needed.
    @discardableResult
    public static func apply(
        _ command: GTDCommand, at date: Date, to state: inout GTDState, mode: ApplyMode = .interactive
    ) throws(GTDValidationError) -> ApplyOutcome {
        switch command {
        case .createProject(let create): try createProject(create, at: date, in: &state, mode: mode)
        case .updateProject(let update): try updateProject(update, in: &state, mode: mode)
        case .archiveProject(let id): try archiveProject(id, at: date, in: &state, mode: mode)
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
        }
    }

    // MARK: - Tasks

    /// `POST /tasks`: an open task at the end of its list's manual order.
    static func createTask(
        _ command: GTDCommand.CreateTask, at date: Date, in state: inout GTDState, mode: ApplyMode
    ) throws(GTDValidationError) -> ApplyOutcome {
        if state.tasks[command.taskID] != nil { return try satisfied(mode, else: .idAlreadyExists) }
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
        state.tasks[command.taskID] = TaskRecord(
            id: command.taskID, title: title, details: details, state: taskState,
            projectID: command.projectID, tagIDs: command.tagIDs, dueDate: command.dueDate,
            priority: command.priority, waitingFor: waitingFor, waitingSince: waitingFor == nil ? nil : date,
            orderKey: maxOrderKey.map { $0 + 1 } ?? 0, createdAt: date, updatedAt: date
        )
        return .applied
    }

    /// `PATCH /tasks/{id}`: field edits; the list only changes through transitions.
    static func updateTask(
        _ command: GTDCommand.UpdateTask, at date: Date, in state: inout GTDState, mode: ApplyMode
    ) throws(GTDValidationError) -> ApplyOutcome {
        guard let task = state.tasks[command.taskID] else { throw .taskNotFound }
        let changes = command.changes
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
            try checkReferences(project: id, tags: nil, in: state)
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
