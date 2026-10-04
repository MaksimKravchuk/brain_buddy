import Foundation

/// Subtasks and comments. They can be added and edited on open and terminal
/// tasks alike, and (as on the server) do not change the parent task.
extension GTDReducer {
    // MARK: - Subtasks

    /// `POST /tasks/{id}/subtasks`: appended after the task's last subtask.
    static func createSubtask(
        _ command: GTDCommand.CreateSubtask, in state: inout GTDState, mode: ApplyMode
    ) throws(GTDValidationError) -> ApplyOutcome {
        guard let task = state.tasks[command.taskID] else { throw .taskNotFound }
        if task.subtasks.contains(where: { $0.id == command.subtaskID }) {
            return try satisfied(mode, else: .idAlreadyExists)
        }
        let title = try FieldRules.title(command.title)
        let orderKey = (task.subtasks.map(\.orderKey).max() ?? -1) + 1
        state.tasks[command.taskID]?.subtasks.append(
            SubtaskRecord(id: command.subtaskID, title: title, state: .open, orderKey: orderKey)
        )
        return .applied
    }

    /// `PATCH /tasks/{id}/subtasks/{sid}`.
    static func updateSubtask(
        _ command: GTDCommand.UpdateSubtask, in state: inout GTDState, mode: ApplyMode
    ) throws(GTDValidationError) -> ApplyOutcome {
        guard let task = state.tasks[command.taskID] else { throw .taskNotFound }
        guard let index = task.subtasks.firstIndex(where: { $0.id == command.subtaskID }) else {
            throw .subtaskNotFound
        }
        let title = try FieldRules.title(command.title)
        if task.subtasks[index].title == title { return try satisfied(mode, else: .nothingToChange) }
        state.tasks[command.taskID]?.subtasks[index].title = title
        return .applied
    }

    /// `POST /tasks/{id}/subtasks/{sid}/transitions`: any state other than the current one.
    static func transitionSubtask(
        _ command: GTDCommand.TransitionSubtask, in state: inout GTDState, mode: ApplyMode
    ) throws(GTDValidationError) -> ApplyOutcome {
        guard let task = state.tasks[command.taskID] else { throw .taskNotFound }
        guard let index = task.subtasks.firstIndex(where: { $0.id == command.subtaskID }) else {
            throw .subtaskNotFound
        }
        let target = command.action.targetState
        if task.subtasks[index].state == target { return try satisfied(mode, else: .subtaskAlreadyInState) }
        state.tasks[command.taskID]?.subtasks[index].state = target
        return .applied
    }

    // MARK: - Comments

    /// `POST /tasks/{id}/comments`. The author is unknown until the server
    /// acknowledges the comment (it is the signed-in user's).
    static func createComment(
        _ command: GTDCommand.CreateComment, at date: Date, in state: inout GTDState, mode: ApplyMode
    ) throws(GTDValidationError) -> ApplyOutcome {
        guard let task = state.tasks[command.taskID] else { throw .taskNotFound }
        if task.comments.contains(where: { $0.id == command.commentID }) {
            return try satisfied(mode, else: .idAlreadyExists)
        }
        let body = try FieldRules.comment(command.body)
        state.tasks[command.taskID]?.comments.append(
            CommentRecord(id: command.commentID, body: body, authorID: nil, createdAt: date)
        )
        return .applied
    }

    /// `PATCH /tasks/{id}/comments/{cid}`.
    static func updateComment(
        _ command: GTDCommand.UpdateComment, at date: Date, in state: inout GTDState, mode: ApplyMode
    ) throws(GTDValidationError) -> ApplyOutcome {
        guard let task = state.tasks[command.taskID] else { throw .taskNotFound }
        guard let index = task.comments.firstIndex(where: { $0.id == command.commentID }) else {
            throw .commentNotFound
        }
        let body = try FieldRules.comment(command.body)
        if task.comments[index].body == body { return try satisfied(mode, else: .nothingToChange) }
        state.tasks[command.taskID]?.comments[index].body = body
        state.tasks[command.taskID]?.comments[index].editedAt = date
        return .applied
    }
}
