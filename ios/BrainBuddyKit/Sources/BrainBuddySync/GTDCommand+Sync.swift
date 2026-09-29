import BrainBuddyCore
import Foundation

/// The record a queued command changes on the server, which is what a 409
/// stale revision makes the engine re-read.
enum SyncTarget: Hashable, Sendable {
    case task(TaskID)
    case project(ProjectID)
    case tag(TagID)
}

extension GTDCommand {
    /// The server record a revision conflict on this command is about (the
    /// parent task for subtask and comment edits, whose detail carries the
    /// children). Nil for creates of projects, tags and tasks.
    var conflictTarget: SyncTarget? {
        switch self {
        case .createProject, .createTag, .createTask: nil
        case .updateProject(let update): .project(update.projectID)
        case .archiveProject(let id): .project(id)
        case .renameTag(let rename): .tag(rename.tagID)
        case .deleteTag(let id): .tag(id)
        case .updateTask(let update): .task(update.taskID)
        case .transitionTask(let transition): .task(transition.taskID)
        case .createSubtask(let create): .task(create.taskID)
        case .updateSubtask(let update): .task(update.taskID)
        case .transitionSubtask(let transition): .task(transition.taskID)
        case .createComment(let create): .task(create.taskID)
        case .updateComment(let update): .task(update.taskID)
        }
    }

    /// The server revision this command's request carries as
    /// `expected_revision` (nil for creates, and when the record is missing).
    /// When a new base changes it, the request body changes, so a sent
    /// operation needs a new idempotency key.
    func expectedRevision(in base: GTDState) -> Int? {
        switch self {
        case .createProject, .createTag, .createTask, .createSubtask, .createComment: nil
        case .updateProject(let update): base.projects[update.projectID]?.serverRevision
        case .archiveProject(let id): base.projects[id]?.serverRevision
        case .renameTag(let rename): base.tags[rename.tagID]?.serverRevision
        case .deleteTag(let id): base.tags[id]?.serverRevision
        case .updateTask(let update): base.tasks[update.taskID]?.serverRevision
        case .transitionTask(let transition): base.tasks[transition.taskID]?.serverRevision
        case .updateSubtask(let update):
            base.tasks[update.taskID]?.subtasks.first { $0.id == update.subtaskID }?.serverRevision
        case .transitionSubtask(let transition):
            base.tasks[transition.taskID]?.subtasks.first { $0.id == transition.subtaskID }?.serverRevision
        case .updateComment(let update):
            base.tasks[update.taskID]?.comments.first { $0.id == update.commentID }?.serverRevision
        }
    }

    /// Archiving a project or deleting a tag also changes (and bumps the
    /// revision of) every member task on the server, so a pull follows.
    var changesOtherRecords: Bool {
        switch self {
        case .archiveProject, .deleteTag: true
        default: false
        }
    }

    /// Creates whose server record can be found again after an uncertain
    /// attempt whose idempotency key may have expired.
    var isCreate: Bool {
        switch self {
        case .createProject, .createTag, .createTask, .createSubtask, .createComment: true
        default: false
        }
    }

    /// The task this command belongs to, if any.
    var taskID: TaskID? {
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

    /// The same command acting on task `new` wherever it named `old`.
    func replacing(task old: TaskID, with new: TaskID) -> GTDCommand {
        func swap(_ id: TaskID) -> TaskID { id == old ? new : id }
        switch self {
        case .createTask(var create):
            create.taskID = swap(create.taskID)
            return .createTask(create)
        case .updateTask(var update):
            update.taskID = swap(update.taskID)
            return .updateTask(update)
        case .transitionTask(var transition):
            transition.taskID = swap(transition.taskID)
            return .transitionTask(transition)
        case .createSubtask(var create):
            create.taskID = swap(create.taskID)
            return .createSubtask(create)
        case .updateSubtask(var update):
            update.taskID = swap(update.taskID)
            return .updateSubtask(update)
        case .transitionSubtask(var transition):
            transition.taskID = swap(transition.taskID)
            return .transitionSubtask(transition)
        case .createComment(var create):
            create.taskID = swap(create.taskID)
            return .createComment(create)
        case .updateComment(var update):
            update.taskID = swap(update.taskID)
            return .updateComment(update)
        case .createProject, .updateProject, .archiveProject, .createTag, .renameTag, .deleteTag:
            return self
        }
    }

    /// The same command acting on subtask `new` wherever it named `old`.
    func replacing(subtask old: SubtaskID, with new: SubtaskID) -> GTDCommand {
        switch self {
        case .createSubtask(var create) where create.subtaskID == old:
            create.subtaskID = new
            return .createSubtask(create)
        case .updateSubtask(var update) where update.subtaskID == old:
            update.subtaskID = new
            return .updateSubtask(update)
        case .transitionSubtask(var transition) where transition.subtaskID == old:
            transition.subtaskID = new
            return .transitionSubtask(transition)
        default:
            return self
        }
    }

    /// The same command acting on comment `new` wherever it named `old`.
    func replacing(comment old: CommentID, with new: CommentID) -> GTDCommand {
        switch self {
        case .createComment(var create) where create.commentID == old:
            create.commentID = new
            return .createComment(create)
        case .updateComment(var update) where update.commentID == old:
            update.commentID = new
            return .updateComment(update)
        default:
            return self
        }
    }
}

extension GTDCommand {
    /// What is left to send of this command (the operation as it is queued
    /// now) after `sent` (the same operation as it was sent) was
    /// acknowledged. Empty when nothing changed since it was sent.
    ///
    /// A command can only change after it was sent through an older document
    /// (one that folded a later edit into it before `everSent` existed) or an
    /// id rewrite. Edits keep only the fields that differ from what was sent;
    /// a create becomes the edits (and move) that bring the acknowledged record
    /// to what the create now says. Replay drops whatever already holds.
    func remainder(afterSending sent: GTDCommand) -> [GTDCommand] {
        guard self != sent else { return [] }
        switch (sent, self) {
        case (.createTask(let sent), .createTask(let now)):
            return Self.taskRemainder(sent: sent, now: now)
        case (.createSubtask(let sent), .createSubtask(let now)):
            guard sent.title != now.title else { return [] }
            return [.updateSubtask(.init(taskID: now.taskID, subtaskID: now.subtaskID, title: now.title))]
        case (.createComment(let sent), .createComment(let now)):
            guard sent.body != now.body else { return [] }
            return [.updateComment(.init(taskID: now.taskID, commentID: now.commentID, body: now.body))]
        case (.createProject(let sent), .createProject(let now)):
            let update = GTDCommand.UpdateProject(
                projectID: now.projectID, name: sent.name == now.name ? nil : now.name,
                color: sent.color == now.color ? .unchanged : now.color.map { .set($0) } ?? .clear
            )
            return update.name == nil && update.color == .unchanged ? [] : [.updateProject(update)]
        case (.createTag(let sent), .createTag(let now)):
            guard sent.name != now.name else { return [] }
            return [.renameTag(.init(tagID: now.tagID, name: now.name))]
        case (.updateTask(let sent), .updateTask(let now)):
            let changes = TaskChanges(
                title: Self.unsent(now.changes.title, sent.changes.title),
                details: Self.unsent(now.changes.details, sent.changes.details),
                projectID: Self.unsent(now.changes.projectID, sent.changes.projectID),
                tagIDs: Self.unsent(now.changes.tagIDs, sent.changes.tagIDs),
                dueDate: Self.unsent(now.changes.dueDate, sent.changes.dueDate),
                priority: Self.unsent(now.changes.priority, sent.changes.priority),
                waitingFor: Self.unsent(now.changes.waitingFor, sent.changes.waitingFor)
            )
            return changes.hasChanges ? [.updateTask(.init(taskID: now.taskID, changes: changes))] : []
        case (.updateProject(let sent), .updateProject(let now)):
            let update = GTDCommand.UpdateProject(
                projectID: now.projectID, name: sent.name == now.name ? nil : now.name,
                color: Self.unsent(now.color, sent.color)
            )
            return update.name == nil && update.color == .unchanged ? [] : [.updateProject(update)]
        default:
            return [self]
        }
    }

    /// `now` unless it asks for exactly what was sent.
    private static func unsent<Value>(_ now: FieldChange<Value>, _ sent: FieldChange<Value>) -> FieldChange<Value> {
        now == sent ? .unchanged : now
    }

    private static func taskRemainder(sent: CreateTask, now: CreateTask) -> [GTDCommand] {
        var commands: [GTDCommand] = []
        if now.list != sent.list {
            commands.append(
                .transitionTask(.init(taskID: now.taskID, action: .move, toList: now.list, waitingFor: now.waitingFor))
            )
        }
        var changes = TaskChanges()
        if now.title != sent.title { changes.title = .set(now.title) }
        if now.details != sent.details { changes.details = now.details.map { .set($0) } ?? .clear }
        if now.projectID != sent.projectID { changes.projectID = now.projectID.map { .set($0) } ?? .clear }
        if now.tagIDs != sent.tagIDs { changes.tagIDs = .set(now.tagIDs) }
        if now.dueDate != sent.dueDate { changes.dueDate = now.dueDate.map { .set($0) } ?? .clear }
        if now.priority != sent.priority { changes.priority = .set(now.priority) }
        if now.list == sent.list, now.list == .waiting, now.waitingFor != sent.waitingFor, let note = now.waitingFor {
            changes.waitingFor = .set(note)
        }
        if changes.hasChanges { commands.append(.updateTask(.init(taskID: now.taskID, changes: changes))) }
        return commands
    }
}

extension PendingOperation {
    /// A fresh `Idempotency-Key`, for a request whose body changed (or whose
    /// old key may have expired): the attempt bookkeeping starts over, but an
    /// operation that may have been sent stays `everSent`, so the compactor
    /// never folds a later edit into it (its old request may still land).
    mutating func rotateKey() {
        if attempts > 0 { everSent = true }
        idempotencyKey = UUID()
        attempts = 0
        firstAttemptAt = nil
        lastAttemptAt = nil
    }
}
