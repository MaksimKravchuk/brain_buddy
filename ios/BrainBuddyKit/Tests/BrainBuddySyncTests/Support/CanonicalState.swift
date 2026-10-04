import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyFakeServer
import Foundation

/// A dataset keyed by server id, without client ids or local-only fields,
/// so two devices and the server can be compared record for record.
struct CanonicalState: Hashable, CustomStringConvertible {
    struct TaskEntry: Hashable {
        var title: String
        var details: String?
        var state: TaskState
        var project: String?
        var tags: [String]
        var dueDate: CalendarDay?
        var priority: TaskPriority
        var waitingFor: String?
        var waitingSince: Int64?
        var completedAt: Int64?
        var cancelledAt: Int64?
        var orderKey: Int
        var createdAt: Int64
        var updatedAt: Int64
        var revision: Int
        /// Nil when children are not compared.
        var subtasks: [Subtask]?
        var comments: [Comment]?
    }

    struct Subtask: Hashable {
        var id: String
        var title: String
        var state: SubtaskState
        var orderKey: Int
        var revision: Int
    }

    struct Comment: Hashable {
        var id: String
        var body: String
        var author: String?
        var createdAt: Int64
        var editedAt: Int64?
        var revision: Int
    }

    struct Named: Hashable {
        var name: String
        var color: String?
        var active: Bool
        var revision: Int
    }

    var tasks: [String: TaskEntry] = [:]
    var projects: [String: Named] = [:]
    var tags: [String: Named] = [:]

    static func micros(_ date: Date) -> Int64 { Int64((date.timeIntervalSince1970 * 1_000_000).rounded()) }
    static func micros(_ date: Date?) -> Int64? { date.map(micros) }

    /// A problem in the device state (a record the server never acknowledged).
    struct Unsynced: Error, CustomStringConvertible {
        var description: String
    }

    init() {}

    init(_ state: GTDState, children: Bool) throws {
        for project in state.projects.values {
            guard let id = project.serverID, let revision = project.serverRevision else {
                throw Unsynced(description: "project \(project.name) has no server id")
            }
            projects[id] = Named(name: project.name, color: project.color, active: project.state == .active, revision: revision)
        }
        for tag in state.tags.values {
            guard let id = tag.serverID, let revision = tag.serverRevision else {
                throw Unsynced(description: "tag \(tag.name) has no server id")
            }
            tags[id] = Named(name: tag.name, color: nil, active: tag.state == .active, revision: revision)
        }
        for task in state.tasks.values {
            guard let id = task.serverID, let revision = task.serverRevision else {
                throw Unsynced(description: "task \(task.title) has no server id")
            }
            var subtasks: [Subtask] = []
            for subtask in task.subtasks {
                guard let sid = subtask.serverID, let revision = subtask.serverRevision else {
                    throw Unsynced(description: "subtask \(subtask.title) has no server id")
                }
                subtasks.append(
                    Subtask(id: sid, title: subtask.title, state: subtask.state, orderKey: subtask.orderKey, revision: revision)
                )
            }
            var comments: [Comment] = []
            for comment in task.comments {
                guard let cid = comment.serverID, let revision = comment.serverRevision else {
                    throw Unsynced(description: "comment \(comment.body) has no server id")
                }
                comments.append(
                    Comment(
                        id: cid, body: comment.body, author: comment.authorID, createdAt: Self.micros(comment.createdAt),
                        editedAt: Self.micros(comment.editedAt), revision: revision
                    )
                )
            }
            tasks[id] = TaskEntry(
                title: task.title, details: task.details, state: task.state,
                project: task.projectID.flatMap { state.projects[$0]?.serverID },
                tags: task.tagIDs.compactMap { state.tags[$0]?.serverID }, dueDate: task.dueDate, priority: task.priority,
                waitingFor: task.waitingFor, waitingSince: Self.micros(task.waitingSince),
                completedAt: Self.micros(task.completedAt), cancelledAt: Self.micros(task.cancelledAt),
                orderKey: task.orderKey, createdAt: Self.micros(task.createdAt), updatedAt: Self.micros(task.updatedAt),
                revision: revision, subtasks: children ? subtasks.sorted { $0.id < $1.id } : nil,
                comments: children ? comments.sorted { $0.id < $1.id } : nil
            )
        }
    }

    init(_ snapshot: FakeServerSnapshot, children: Bool) {
        for project in snapshot.projects.values {
            projects[project.id] = Named(
                name: project.name, color: project.color, active: project.state == .active, revision: project.revision
            )
        }
        for tag in snapshot.tags.values {
            tags[tag.id] = Named(name: tag.name, color: nil, active: tag.state == .active, revision: tag.revision)
        }
        for task in snapshot.tasks.values {
            tasks[task.id] = TaskEntry(
                title: task.title, details: task.details, state: task.state, project: task.projectID, tags: task.tagIDs,
                dueDate: task.dueDate, priority: task.priority, waitingFor: task.waitingFor,
                waitingSince: Self.micros(task.waitingSince), completedAt: Self.micros(task.completedAt),
                cancelledAt: Self.micros(task.cancelledAt), orderKey: task.orderKey, createdAt: Self.micros(task.createdAt),
                updatedAt: Self.micros(task.updatedAt), revision: task.revision,
                subtasks: children
                    ? task.subtasks.map {
                        Subtask(id: $0.id, title: $0.title, state: $0.state, orderKey: $0.orderKey, revision: $0.revision)
                    }.sorted { $0.id < $1.id } : nil,
                comments: children
                    ? task.comments.map {
                        Comment(
                            id: $0.id, body: $0.body, author: $0.actorID, createdAt: Self.micros($0.createdAt),
                            editedAt: Self.micros($0.editedAt), revision: $0.revision
                        )
                    }.sorted { $0.id < $1.id } : nil
            )
        }
    }

    /// The server's archived projects and deleted tags that no device can
    /// list (there is no endpoint for them) are left out: a device knows the
    /// ones it saw active or that a task references.
    func restrictingInactive(to other: CanonicalState) -> CanonicalState {
        var copy = self
        copy.projects = projects.filter { $0.value.active || other.projects[$0.key] != nil }
        copy.tags = tags.filter { $0.value.active || other.tags[$0.key] != nil }
        return copy
    }

    /// The first differences, for a readable failure.
    func differences(from other: CanonicalState, limit: Int = 8) -> [String] {
        var lines: [String] = []
        for key in Set(tasks.keys).union(other.tasks.keys).sorted() where tasks[key] != other.tasks[key] {
            lines.append("task \(key): \(String(describing: tasks[key])) vs \(String(describing: other.tasks[key]))")
        }
        for key in Set(projects.keys).union(other.projects.keys).sorted() where projects[key] != other.projects[key] {
            lines.append("project \(key): \(String(describing: projects[key])) vs \(String(describing: other.projects[key]))")
        }
        for key in Set(tags.keys).union(other.tags.keys).sorted() where tags[key] != other.tags[key] {
            lines.append("tag \(key): \(String(describing: tags[key])) vs \(String(describing: other.tags[key]))")
        }
        return Array(lines.prefix(limit))
    }

    var description: String { "\(tasks.count) tasks, \(projects.count) projects, \(tags.count) tags" }
}
