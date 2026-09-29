import BrainBuddyAPI
import BrainBuddyCore
import Foundation

// The fake server's storage rows, field for field with the backend's
// documents (`backend/app/modules/tasks/domain.py`), and their projections
// into the API's response DTOs (`backend/app/api/tasks.py` `_to_*_response`).

struct TaskRow: Hashable, Sendable {
    var id: String
    var title: String
    var details: String?
    var state: TaskState
    var projectID: String?
    var tagIDs: [String]
    var dueDate: CalendarDay?
    var priority: TaskPriority
    var waitingFor: String?
    var waitingSince: Date?
    var orderKey: Int
    var createdAt: Date
    var updatedAt: Date
    var completedAt: Date?
    var cancelledAt: Date?
    var revision: Int

    /// `_to_response`: list pages and mutations carry no children; `GET /tasks/{id}` passes them.
    func dto(subtasks: [SubtaskDTO] = [], comments: [CommentDTO] = []) -> TaskDTO {
        TaskDTO(
            id: id, title: title, details: details, state: state, projectID: projectID, tagIDs: tagIDs,
            dueDate: dueDate, priority: priority, waitingFor: waitingFor, waitingSince: waitingSince,
            orderKey: orderKey, createdAt: createdAt, updatedAt: updatedAt, completedAt: completedAt,
            cancelledAt: cancelledAt, revision: revision, subtasks: subtasks, comments: comments
        )
    }
}

struct ProjectRow: Hashable, Sendable {
    var id: String
    var name: String
    var normalizedName: String
    var color: String?
    var state: ProjectState
    var createdAt: Date
    var updatedAt: Date
    var revision: Int
}

struct TagRow: Hashable, Sendable {
    var id: String
    var name: String
    var normalizedName: String
    var state: TagState
    var createdAt: Date
    var updatedAt: Date
    var revision: Int
}

struct SubtaskRow: Hashable, Sendable {
    var id: String
    var taskID: String
    var title: String
    var orderKey: Int
    var state: SubtaskState
    var createdAt: Date
    var updatedAt: Date
    var revision: Int

    var dto: SubtaskDTO { SubtaskDTO(id: id, title: title, state: state, orderKey: orderKey, revision: revision) }
}

struct CommentRow: Hashable, Sendable {
    var id: String
    var taskID: String
    var actorID: String
    var body: String
    var createdAt: Date
    var editedAt: Date?
    var revision: Int

    var dto: CommentDTO {
        CommentDTO(id: id, body: body, actorID: actorID, createdAt: createdAt, editedAt: editedAt, revision: revision)
    }
}

/// What an idempotency record points at: the resource as the first request left it.
enum StoredResult: Hashable, Sendable {
    case task(TaskRow)
    case project(ProjectRow)
    case tag(TagRow)
    case subtask(SubtaskRow)
    case comment(CommentRow)
}

/// `IdempotencyRecord`: one owner-scoped key, the command it was used for
/// and the request fingerprint (command + body + the keys that were sent).
struct IdempotencyRow: Hashable, Sendable {
    var key: String
    var command: String
    var fingerprint: String
    var result: StoredResult
    var createdAt: Date
}

/// Everything one account owns.
struct OwnerData: Sendable {
    var tasks: [String: TaskRow] = [:]
    var projects: [String: ProjectRow] = [:]
    var tags: [String: TagRow] = [:]
    var subtasks: [String: SubtaskRow] = [:]
    var comments: [String: CommentRow] = [:]
    var idempotency: [String: IdempotencyRow] = [:]

    func openTaskCount(project id: String) -> Int {
        tasks.values.filter { $0.projectID == id && $0.state.isOpen }.count
    }

    func openTaskCount(tag id: String) -> Int {
        tasks.values.filter { $0.tagIDs.contains(id) && $0.state.isOpen }.count
    }

    func projectDTO(_ row: ProjectRow) -> ProjectDTO {
        ProjectDTO(
            id: row.id, name: row.name, color: row.color, state: row.state, revision: row.revision,
            openTaskCount: openTaskCount(project: row.id)
        )
    }

    func tagDTO(_ row: TagRow) -> TagDTO {
        TagDTO(id: row.id, name: row.name, state: row.state, revision: row.revision, openTaskCount: openTaskCount(tag: row.id))
    }

    /// `get_task_detail`: subtasks by `(order_key, id)`, comments by `(created_at, id)`.
    func detailDTO(_ task: TaskRow) -> TaskDTO {
        let subtasks = subtasks.values.filter { $0.taskID == task.id }
            .sorted { ($0.orderKey, $0.id) < ($1.orderKey, $1.id) }
        let comments = comments.values.filter { $0.taskID == task.id }
            .sorted { ($0.createdAt, $0.id) < ($1.createdAt, $1.id) }
        return task.dto(subtasks: subtasks.map(\.dto), comments: comments.map(\.dto))
    }
}

struct FakeAccount: Sendable {
    var id: String
    var email: String
    var password: String
    var displayName: String?
}

extension OwnerData {
    /// `_idempotency_record`: the stored result for `key`, or 409 when the key
    /// was used for another command or body.
    func replay(key: String, command: String, fingerprint: String) throws(FakeHTTPError) -> StoredResult? {
        guard let record = idempotency[key] else { return nil }
        guard record.command == command, record.fingerprint == fingerprint else {
            throw .conflict("Idempotency-Key", key)
        }
        return record.result
    }

    mutating func remember(key: String, command: String, fingerprint: String, result: StoredResult, now: Date) {
        idempotency[key] = IdempotencyRow(key: key, command: command, fingerprint: fingerprint, result: result, createdAt: now)
    }

    func task(_ id: String) throws(FakeHTTPError) -> TaskRow {
        guard let task = tasks[id] else { throw .notFound("Task", id) }
        return task
    }

    func project(_ id: String) throws(FakeHTTPError) -> ProjectRow {
        guard let project = projects[id] else { throw .notFound("Project", id) }
        return project
    }

    func tag(_ id: String) throws(FakeHTTPError) -> TagRow {
        guard let tag = tags[id] else { throw .notFound("Tag", id) }
        return tag
    }
}
