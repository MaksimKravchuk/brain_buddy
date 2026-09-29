import Foundation

/// Keeps the outbox proportional to the data rather than to the edit history,
/// which matters most without an account, where the outbox *is* the data.
///
/// A new operation folds into the latest earlier operation on the same record
/// when that is unsent and moving the new effect back to it cannot change any
/// operation in between:
///
/// - a task edit folds into the task's unsent creation, or merges with its
///   latest unsent edit (`TaskChanges.merged(with:)`);
/// - a move of a task whose creation is unsent becomes the creation's list;
/// - complete / cancel then reopen of such a task cancels out, and the reopen
///   becomes the creation's list;
/// - subtask and comment edits fold into their unsent creation or edit;
/// - project and tag renames (and recolours) fold into their unsent creation or edit.
///
/// It never folds into or across an operation that may have reached the
/// server, never across a project archive or tag delete, and never moves an
/// edit before the creation of a project or tag it references, before a
/// transition that changes its waiting note, or a name before another name
/// change of the same kind (uniqueness depends on that order).
///
/// Replaying a compacted outbox gives the same state as the operations one by
/// one, except for fields the server assigns at the time a request lands:
/// `updatedAt`, `orderKey` (a creation now lands directly in its final list),
/// `waitingSince` (the entry time into Waiting), and a comment's `editedAt`
/// (an edit folded into its creation is no edit to the server).
public enum OutboxCompactor {
    /// Appends `operation` to `outbox`, folding it into an earlier unsent
    /// operation when that keeps the replayed state identical (for example an
    /// edit of a task whose creation has not been sent yet). Operations with
    /// `hasBeenSent == true` are never modified.
    public static func appending(_ operation: PendingOperation, to outbox: [PendingOperation]) -> [PendingOperation] {
        var result = outbox
        if !operation.hasBeenSent, fold(operation.command, into: &result) { return result }
        result.append(operation)
        return result
    }

    private static func fold(_ command: GTDCommand, into outbox: inout [PendingOperation]) -> Bool {
        switch command {
        case .updateTask(let update): foldTaskEdit(update, into: &outbox)
        case .transitionTask(let move) where move.action == .move: foldMove(move, into: &outbox)
        case .transitionTask(let reopen) where reopen.action == .reopen: foldReopen(reopen, into: &outbox)
        case .updateSubtask(let update): foldSubtaskEdit(update, into: &outbox)
        case .updateComment(let update): foldCommentEdit(update, into: &outbox)
        case .updateProject(let update): foldProjectEdit(update, into: &outbox)
        case .renameTag(let rename): foldTagRename(rename, into: &outbox)
        default: false
        }
    }

    /// Walks back from `end` to the latest operation `isTarget` accepts and
    /// returns its index, provided that operation is unsent and `canCross`
    /// accepts every operation after it.
    private static func unsentTarget(
        in outbox: [PendingOperation], before end: Int? = nil, isTarget: (GTDCommand) -> Bool,
        canCross: (PendingOperation) -> Bool
    ) -> Int? {
        for index in (outbox.startIndex..<(end ?? outbox.endIndex)).reversed() {
            let operation = outbox[index]
            if isTarget(operation.command) { return operation.hasBeenSent ? nil : index }
            guard canCross(operation) else { return nil }
        }
        return nil
    }

    // MARK: - Tasks

    private static func foldTaskEdit(_ update: GTDCommand.UpdateTask, into outbox: inout [PendingOperation]) -> Bool {
        let changes = update.changes
        // Clearing a title, priority or waiting note is invalid; leave it for the reducer to report.
        guard changes.title != .clear, changes.priority != .clear, changes.waitingFor != .clear,
            let index = unsentTarget(
                in: outbox,
                isTarget: { command in
                    switch command {
                    case .createTask(let create): create.taskID == update.taskID
                    case .updateTask(let earlier): earlier.taskID == update.taskID
                    default: false
                    }
                },
                canCross: { editCanCross($0, task: update.taskID, changes: changes) }
            )
        else { return false }
        switch outbox[index].command {
        case .createTask(var create):
            create.fold(changes)
            outbox[index].command = .createTask(create)
        case .updateTask(var earlier):
            earlier.changes = earlier.changes.merged(with: changes)
            outbox[index].command = .updateTask(earlier)
        default:
            return false
        }
        return true
    }

    private static func foldMove(_ move: GTDCommand.TransitionTask, into outbox: inout [PendingOperation]) -> Bool {
        guard let list = move.toList,
            let index = unsentTarget(
                in: outbox, isTarget: { $0.creates(task: move.taskID) },
                canCross: { listChangeCanCross($0, task: move.taskID) }
            ),
            case .createTask(var create) = outbox[index].command
        else { return false }
        create.enter(list, waitingFor: move.waitingFor)
        outbox[index].command = .createTask(create)
        return true
    }

    private static func foldReopen(_ reopen: GTDCommand.TransitionTask, into outbox: inout [PendingOperation]) -> Bool {
        let task = reopen.taskID
        guard let list = reopen.toList,
            let terminalIndex = unsentTarget(
                in: outbox,
                isTarget: { command in
                    guard case .transitionTask(let transition) = command else { return false }
                    return transition.taskID == task
                },
                canCross: { listChangeCanCross($0, task: task) }
            ),
            case .transitionTask(let terminal) = outbox[terminalIndex].command,
            terminal.action == .complete || terminal.action == .cancel,
            let createIndex = unsentTarget(
                in: outbox, before: terminalIndex, isTarget: { $0.creates(task: task) },
                canCross: { listChangeCanCross($0, task: task) }
            ),
            case .createTask(var create) = outbox[createIndex].command
        else { return false }
        create.enter(list, waitingFor: reopen.waitingFor)
        outbox[createIndex].command = .createTask(create)
        outbox.remove(at: terminalIndex)
        return true
    }

    /// Whether a task edit can move before `operation`: not across a sent
    /// operation on the task, an archive or delete, the creation of a project
    /// or tag it references, or (for a waiting note) a transition.
    private static func editCanCross(_ operation: PendingOperation, task: TaskID, changes: TaskChanges) -> Bool {
        let command = operation.command
        if command.taskID == task {
            guard !operation.hasBeenSent else { return false }
            if case .transitionTask = command { return !changes.waitingFor.isChanged }
            return true
        }
        switch command {
        case .archiveProject, .deleteTag:
            return false
        case .createProject(let create):
            return changes.projectID != .set(create.projectID)
        case .createTag(let create):
            guard case .set(let ids) = changes.tagIDs else { return true }
            return !ids.contains(create.tagID)
        default:
            return true
        }
    }

    /// Whether a list change can move back before `operation`: not across a
    /// sent operation on the task, another transition, an edit of the waiting
    /// note (valid only in Waiting), or an archive or delete.
    private static func listChangeCanCross(_ operation: PendingOperation, task: TaskID) -> Bool {
        let command = operation.command
        if command.taskID == task {
            guard !operation.hasBeenSent else { return false }
            switch command {
            case .transitionTask: return false
            case .updateTask(let update): return !update.changes.waitingFor.isChanged
            default: return true
            }
        }
        switch command {
        case .archiveProject, .deleteTag: return false
        default: return true
        }
    }

    // MARK: - Subtasks and comments

    private static func foldSubtaskEdit(
        _ update: GTDCommand.UpdateSubtask, into outbox: inout [PendingOperation]
    ) -> Bool {
        guard
            let index = unsentTarget(
                in: outbox,
                isTarget: { command in
                    switch command {
                    case .createSubtask(let create): create.taskID == update.taskID && create.subtaskID == update.subtaskID
                    case .updateSubtask(let earlier):
                        earlier.taskID == update.taskID && earlier.subtaskID == update.subtaskID
                    default: false
                    }
                },
                canCross: { childEditCanCross($0, task: update.taskID) }
            )
        else { return false }
        switch outbox[index].command {
        case .createSubtask(var create):
            create.title = update.title
            outbox[index].command = .createSubtask(create)
        case .updateSubtask(var earlier):
            earlier.title = update.title
            outbox[index].command = .updateSubtask(earlier)
        default:
            return false
        }
        return true
    }

    private static func foldCommentEdit(
        _ update: GTDCommand.UpdateComment, into outbox: inout [PendingOperation]
    ) -> Bool {
        guard
            let index = unsentTarget(
                in: outbox,
                isTarget: { command in
                    switch command {
                    case .createComment(let create): create.taskID == update.taskID && create.commentID == update.commentID
                    case .updateComment(let earlier):
                        earlier.taskID == update.taskID && earlier.commentID == update.commentID
                    default: false
                    }
                },
                canCross: { childEditCanCross($0, task: update.taskID) }
            )
        else { return false }
        switch outbox[index].command {
        case .createComment(var create):
            create.body = update.body
            outbox[index].command = .createComment(create)
        case .updateComment(var earlier):
            earlier.body = update.body
            outbox[index].command = .updateComment(earlier)
        default:
            return false
        }
        return true
    }

    private static func childEditCanCross(_ operation: PendingOperation, task: TaskID) -> Bool {
        if operation.command.taskID == task { return !operation.hasBeenSent }
        switch operation.command {
        case .archiveProject, .deleteTag: return false
        default: return true
        }
    }

    // MARK: - Projects and tags

    private static func foldProjectEdit(
        _ update: GTDCommand.UpdateProject, into outbox: inout [PendingOperation]
    ) -> Bool {
        guard
            let index = unsentTarget(
                in: outbox,
                isTarget: { command in
                    switch command {
                    case .createProject(let create): create.projectID == update.projectID
                    case .updateProject(let earlier): earlier.projectID == update.projectID
                    default: false
                    }
                },
                canCross: { operation in
                    switch operation.command {
                    case .createProject, .updateProject, .archiveProject, .deleteTag: false
                    default: true
                    }
                }
            )
        else { return false }
        switch outbox[index].command {
        case .createProject(var create):
            if let name = update.name { create.name = name }
            switch update.color {
            case .unchanged: break
            case .clear: create.color = nil
            case .set(let color): create.color = color
            }
            outbox[index].command = .createProject(create)
        case .updateProject(var earlier):
            earlier.name = update.name ?? earlier.name
            earlier.color = earlier.color.merged(with: update.color)
            outbox[index].command = .updateProject(earlier)
        default:
            return false
        }
        return true
    }

    private static func foldTagRename(_ rename: GTDCommand.RenameTag, into outbox: inout [PendingOperation]) -> Bool {
        guard
            let index = unsentTarget(
                in: outbox,
                isTarget: { command in
                    switch command {
                    case .createTag(let create): create.tagID == rename.tagID
                    case .renameTag(let earlier): earlier.tagID == rename.tagID
                    default: false
                    }
                },
                canCross: { operation in
                    switch operation.command {
                    case .createTag, .renameTag, .deleteTag, .archiveProject: false
                    default: true
                    }
                }
            )
        else { return false }
        switch outbox[index].command {
        case .createTag(var create):
            create.name = rename.name
            outbox[index].command = .createTag(create)
        case .renameTag(var earlier):
            earlier.name = rename.name
            outbox[index].command = .renameTag(earlier)
        default:
            return false
        }
        return true
    }
}

extension GTDCommand {
    /// The task a task-scoped command acts on.
    fileprivate var taskID: TaskID? {
        switch self {
        case .createTask(let create): create.taskID
        case .updateTask(let update): update.taskID
        case .transitionTask(let transition): transition.taskID
        case .createSubtask(let create): create.taskID
        case .updateSubtask(let update): update.taskID
        case .transitionSubtask(let transition): transition.taskID
        case .createComment(let create): create.taskID
        case .updateComment(let update): update.taskID
        case .createProject, .updateProject, .archiveProject, .createTag, .renameTag, .deleteTag: nil
        }
    }

    fileprivate func creates(task: TaskID) -> Bool {
        guard case .createTask(let create) = self else { return false }
        return create.taskID == task
    }
}

extension GTDCommand.CreateTask {
    /// Applies field edits to the creation (invalid clears are excluded by the caller).
    fileprivate mutating func fold(_ changes: TaskChanges) {
        if case .set(let value) = changes.title { title = value }
        switch changes.details {
        case .unchanged: break
        case .clear: details = nil
        case .set(let value): details = value
        }
        switch changes.projectID {
        case .unchanged: break
        case .clear: projectID = nil
        case .set(let id): projectID = id
        }
        switch changes.tagIDs {
        case .unchanged: break
        case .clear: tagIDs = []
        case .set(let ids): tagIDs = ids
        }
        switch changes.dueDate {
        case .unchanged: break
        case .clear: dueDate = nil
        case .set(let day): dueDate = day
        }
        if case .set(let value) = changes.priority { priority = value }
        switch changes.waitingFor {
        case .unchanged: break
        case .clear: waitingFor = nil
        case .set(let value): waitingFor = value
        }
    }

    /// Creates the task directly in `list`, as a move or reopen would leave it.
    fileprivate mutating func enter(_ list: OpenList, waitingFor note: String?) {
        self.list = list
        waitingFor = list == .waiting ? note : nil
    }
}
