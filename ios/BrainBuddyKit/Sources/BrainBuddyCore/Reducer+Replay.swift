import Foundation

/// How a queued task command is re-applied on top of newer server state.
///
/// A command was valid when the user issued it; by the time it is replayed,
/// another device may have archived its project, deleted one of its tags or
/// moved its task out of Waiting. Replay then keeps what still makes sense
/// instead of losing the whole command:
///
/// - a reference to a project or tag that is missing or no longer active is
///   dropped, and the task keeps everything else. That is the server's own
///   outcome had the command landed first: archiving a project and deleting
///   a tag remove them from every task. A task edit that set such a project
///   therefore clears the project rather than restoring the previous one;
/// - a task edit keeps every field change the task can still take, and loses
///   only the others (a waiting note on a task that left Waiting, a value
///   that fails a limit), so a folded edit is never rejected for the sake of
///   one of its fields.
///
/// Interactive commands stay strict: the user is told why, and nothing is
/// dropped silently.
extension GTDReducer {
    /// `command` as `ApplyMode.replay` applies it to `state`: `createTask` and
    /// `updateTask` without the references and field changes described above;
    /// every other command unchanged.
    ///
    /// `OutboxReplayer` queues this form in place of an unsent operation, so
    /// what is sent is what was applied. Sync can use it for an operation the
    /// server definitively rejected, against the state that operation
    /// replays onto.
    public static func replayable(_ command: GTDCommand, in state: GTDState) -> GTDCommand {
        switch command {
        case .createTask(let create):
            return .createTask(replayable(create, in: state))
        case .updateTask(var update):
            guard let task = state.tasks[update.taskID] else { return command }
            update.changes = replayable(update.changes, for: task, in: state)
            return .updateTask(update)
        case .createProject, .updateProject, .archiveProject, .createTag, .renameTag, .deleteTag, .transitionTask,
            .createSubtask, .updateSubtask, .transitionSubtask, .createComment, .updateComment:
            return command
        }
    }

    /// A creation keeps its task; only its references can go.
    static func replayable(_ create: GTDCommand.CreateTask, in state: GTDState) -> GTDCommand.CreateTask {
        var create = create
        if let id = create.projectID, !isActive(project: id, in: state) { create.projectID = nil }
        create.tagIDs = activeTags(create.tagIDs, in: state)
        return create
    }

    /// Each field change on its own: the ones `task` can still take, as the
    /// strict path in `updateTask` would accept them.
    static func replayable(_ changes: TaskChanges, for task: TaskRecord, in state: GTDState) -> TaskChanges {
        var changes = changes
        switch changes.title {
        case .unchanged: break
        case .clear: changes.title = .unchanged
        case .set(let value): if !passes({ try FieldRules.title(value) }) { changes.title = .unchanged }
        }
        if case .set(let value) = changes.details, !passes({ try FieldRules.details(value) }) {
            changes.details = .unchanged
        }
        if changes.priority == .clear { changes.priority = .unchanged }
        if changes.waitingFor.isChanged {
            let note: String? = if case .set(let value) = changes.waitingFor { value } else { nil }
            if task.state != .waiting || !passes({ try FieldRules.waitingFor(note) }) {
                changes.waitingFor = .unchanged
            }
        }
        if case .set(let id) = changes.projectID, !isActive(project: id, in: state) { changes.projectID = .clear }
        if case .set(let ids) = changes.tagIDs { changes.tagIDs = .set(activeTags(ids, in: state)) }
        return changes
    }

    /// Whether `rule` accepts its value. (Not `try?`, which would also treat
    /// a rule's valid `nil`, such as empty notes, as a failure.)
    private static func passes<Value>(_ rule: () throws -> Value) -> Bool {
        do {
            _ = try rule()
            return true
        } catch {
            return false
        }
    }

    private static func isActive(project id: ProjectID, in state: GTDState) -> Bool {
        state.projects[id]?.state == .active
    }

    /// The active tags among `ids`, in order, each once.
    private static func activeTags(_ ids: [TagID], in state: GTDState) -> [TagID] {
        var seen = Set<TagID>()
        return ids.filter { state.tags[$0]?.state == .active && seen.insert($0).inserted }
    }
}
