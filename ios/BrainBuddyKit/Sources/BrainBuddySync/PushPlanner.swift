import BrainBuddyAPI
import BrainBuddyCore
import Foundation

/// What a 2xx answered with.
enum ServerRecord: Sendable {
    case project(ProjectDTO)
    case tag(TagDTO)
    case task(TaskDTO)
    case subtask(SubtaskDTO)
    case comment(CommentDTO)
}

/// One queued command resolved against the base: server ids in place of
/// client ids, `expected_revision` from the base record, and the values the
/// reducer stored rather than the raw input (titles trimmed, empty notes
/// cleared), so the server ends up with what the device shows.
enum PlannedRequest: Sendable {
    case createProject(name: String, color: String?)
    case updateProject(id: String, name: String?, color: FieldChange<String>, revision: Int)
    case archiveProject(id: String, revision: Int)
    case createTag(name: String)
    case renameTag(id: String, name: String, revision: Int)
    case deleteTag(id: String, revision: Int)
    case createTask(TaskCreateBody)
    case updateTask(id: String, TaskUpdateBody)
    case transitionTask(id: String, TaskTransitionBody)
    case createSubtask(taskID: String, title: String)
    case updateSubtask(taskID: String, subtaskID: String, title: String, revision: Int)
    case transitionSubtask(taskID: String, subtaskID: String, action: SubtaskTransitionAction, revision: Int)
    case createComment(taskID: String, body: String)
    case updateComment(taskID: String, commentID: String, body: String, revision: Int)

    /// Sends the request with `key` as its `Idempotency-Key`.
    func send(with client: BrainBuddyAPIClient, key: UUID) async throws(APIError) -> ServerRecord {
        switch self {
        case .createProject(let name, let color):
            return .project(try await client.createProject(name: name, color: color, idempotencyKey: key))
        case .updateProject(let id, let name, let color, let revision):
            return .project(
                try await client.updateProject(
                    id: id, name: name, color: color, expectedRevision: revision, idempotencyKey: key
                )
            )
        case .archiveProject(let id, let revision):
            return .project(try await client.archiveProject(id: id, expectedRevision: revision, idempotencyKey: key))
        case .createTag(let name):
            return .tag(try await client.createTag(name: name, idempotencyKey: key))
        case .renameTag(let id, let name, let revision):
            return .tag(try await client.updateTag(id: id, name: name, expectedRevision: revision, idempotencyKey: key))
        case .deleteTag(let id, let revision):
            return .tag(try await client.deleteTag(id: id, expectedRevision: revision, idempotencyKey: key))
        case .createTask(let body):
            return .task(try await client.createTask(body, idempotencyKey: key))
        case .updateTask(let id, let body):
            return .task(try await client.updateTask(id: id, body, idempotencyKey: key))
        case .transitionTask(let id, let body):
            return .task(try await client.transitionTask(id: id, body, idempotencyKey: key))
        case .createSubtask(let taskID, let title):
            return .subtask(try await client.createSubtask(taskID: taskID, title: title, idempotencyKey: key))
        case .updateSubtask(let taskID, let subtaskID, let title, let revision):
            return .subtask(
                try await client.updateSubtask(
                    taskID: taskID, subtaskID: subtaskID, title: title, expectedRevision: revision, idempotencyKey: key
                )
            )
        case .transitionSubtask(let taskID, let subtaskID, let action, let revision):
            return .subtask(
                try await client.transitionSubtask(
                    taskID: taskID, subtaskID: subtaskID, action: action, expectedRevision: revision, idempotencyKey: key
                )
            )
        case .createComment(let taskID, let body):
            return .comment(try await client.createComment(taskID: taskID, body: body, idempotencyKey: key))
        case .updateComment(let taskID, let commentID, let body, let revision):
            return .comment(
                try await client.updateComment(
                    taskID: taskID, commentID: commentID, body: body, expectedRevision: revision, idempotencyKey: key
                )
            )
        }
    }
}

/// Builds the request for the first queued operation. Everything it needs
/// is in the base: the outbox is ordered, so whatever a command references
/// was acknowledged before the command reached the front.
enum PushPlanner {
    /// A reference the base cannot resolve (it should not happen; the
    /// operation is set aside rather than blocking the queue).
    struct Unresolvable: Error, Sendable {
        var message = "This change refers to an item that isn't on the server."
    }

    static func plan(_ command: GTDCommand, base: GTDState) throws(Unresolvable) -> PlannedRequest {
        let resolver = Resolver(base: base)
        switch command {
        case .createProject(let create):
            return .createProject(name: create.name, color: create.color)
        case .updateProject(let update):
            let project = try resolver.project(update.projectID)
            return .updateProject(id: project.id, name: update.name, color: update.color, revision: project.revision)
        case .archiveProject(let id):
            let project = try resolver.project(id)
            return .archiveProject(id: project.id, revision: project.revision)
        case .createTag(let create):
            return .createTag(name: create.name)
        case .renameTag(let rename):
            let tag = try resolver.tag(rename.tagID)
            return .renameTag(id: tag.id, name: rename.name, revision: tag.revision)
        case .deleteTag(let id):
            let tag = try resolver.tag(id)
            return .deleteTag(id: tag.id, revision: tag.revision)
        case .createTask(var create):
            create.title = SyncText.strip(create.title)
            if create.details?.isEmpty == true { create.details = nil }
            do {
                return .createTask(
                    try TaskCreateBody(create, projectServerID: resolver.projectID, tagServerID: resolver.tagID)
                )
            } catch {
                throw Unresolvable()
            }
        case .updateTask(let update):
            let task = try resolver.task(update.taskID)
            var changes = update.changes
            if case .set(let title) = changes.title { changes.title = .set(SyncText.strip(title)) }
            if changes.details == .set("") { changes.details = .clear }
            do {
                let body = try TaskUpdateBody(
                    changes: changes, expectedRevision: task.revision, projectServerID: resolver.projectID,
                    tagServerID: resolver.tagID
                )
                return .updateTask(id: task.id, body)
            } catch {
                throw Unresolvable()
            }
        case .transitionTask(let transition):
            let task = try resolver.task(transition.taskID)
            return .transitionTask(id: task.id, TaskTransitionBody(transition, expectedRevision: task.revision))
        case .createSubtask(let create):
            return .createSubtask(taskID: try resolver.task(create.taskID).id, title: SyncText.strip(create.title))
        case .updateSubtask(let update):
            let task = try resolver.task(update.taskID)
            let subtask = try resolver.subtask(update.subtaskID, in: update.taskID)
            return .updateSubtask(
                taskID: task.id, subtaskID: subtask.id, title: SyncText.strip(update.title), revision: subtask.revision
            )
        case .transitionSubtask(let transition):
            let task = try resolver.task(transition.taskID)
            let subtask = try resolver.subtask(transition.subtaskID, in: transition.taskID)
            return .transitionSubtask(
                taskID: task.id, subtaskID: subtask.id, action: transition.action, revision: subtask.revision
            )
        case .createComment(let create):
            return .createComment(taskID: try resolver.task(create.taskID).id, body: create.body)
        case .updateComment(let update):
            let task = try resolver.task(update.taskID)
            let comment = try resolver.comment(update.commentID, in: update.taskID)
            return .updateComment(taskID: task.id, commentID: comment.id, body: update.body, revision: comment.revision)
        }
    }

    /// Server id and revision of base records.
    private struct Resolver {
        let base: GTDState

        struct Reference {
            var id: String
            var revision: Int
        }

        private static func reference(_ record: (any ServerBacked)?) throws(Unresolvable) -> Reference {
            guard let record, let id = record.serverID, let revision = record.serverRevision else { throw Unresolvable() }
            return Reference(id: id, revision: revision)
        }

        func task(_ id: TaskID) throws(Unresolvable) -> Reference { try Self.reference(base.tasks[id]) }
        func project(_ id: ProjectID) throws(Unresolvable) -> Reference { try Self.reference(base.projects[id]) }
        func tag(_ id: TagID) throws(Unresolvable) -> Reference { try Self.reference(base.tags[id]) }

        func subtask(_ id: SubtaskID, in task: TaskID) throws(Unresolvable) -> Reference {
            try Self.reference(base.tasks[task]?.subtasks.first { $0.id == id })
        }

        func comment(_ id: CommentID, in task: TaskID) throws(Unresolvable) -> Reference {
            try Self.reference(base.tasks[task]?.comments.first { $0.id == id })
        }

        func projectID(_ id: ProjectID) throws(Unresolvable) -> String { try project(id).id }
        func tagID(_ id: TagID) throws(Unresolvable) -> String { try tag(id).id }
    }
}
