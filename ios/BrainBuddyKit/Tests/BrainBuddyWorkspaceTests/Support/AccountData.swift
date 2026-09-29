import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyFakeServer
import Foundation

/// An account's data keyed by server id, without client ids or local-only
/// fields, so what a device shows and what the server holds can be compared
/// record for record. Revisions are included: equal data means the device
/// shows the latest version of every record. (A leaner cousin of
/// `BrainBuddySyncTests`' `CanonicalState`, which this target cannot import.)
struct AccountData: Hashable {
    struct Task: Hashable {
        var title: String
        var details: String?
        var state: TaskState
        var project: String?
        var tags: [String]
        var dueDate: CalendarDay?
        var priority: TaskPriority
        var waitingFor: String?
        var revision: Int
        /// Nil when children are not compared.
        var subtasks: [String: Subtask]?
        var comments: [String: Comment]?
    }

    struct Subtask: Hashable {
        var title: String
        var state: SubtaskState
        var revision: Int
    }

    struct Comment: Hashable {
        var body: String
        var author: String?
        var revision: Int
    }

    struct Named: Hashable {
        var name: String
        var color: String?
        var active: Bool
        var revision: Int
    }

    /// A record on the device the server never acknowledged.
    struct Unsynced: Error, CustomStringConvertible {
        var description: String
    }

    var tasks: [String: Task] = [:]
    var projects: [String: Named] = [:]
    var tags: [String: Named] = [:]

    /// What a device's current state says the server holds.
    init(device state: GTDState, children: Bool = true) throws(Unsynced) {
        for project in state.projects.values {
            let (id, revision) = try Self.reference(project, "project \(project.name)")
            projects[id] = Named(name: project.name, color: project.color, active: project.state == .active, revision: revision)
        }
        for tag in state.tags.values {
            let (id, revision) = try Self.reference(tag, "tag \(tag.name)")
            tags[id] = Named(name: tag.name, color: nil, active: tag.state == .active, revision: revision)
        }
        for task in state.tasks.values {
            let (id, revision) = try Self.reference(task, "task \(task.title)")
            var subtasks: [String: Subtask] = [:]
            var comments: [String: Comment] = [:]
            for subtask in task.subtasks {
                let (sid, revision) = try Self.reference(subtask, "subtask \(subtask.title)")
                subtasks[sid] = Subtask(title: subtask.title, state: subtask.state, revision: revision)
            }
            for comment in task.comments {
                let (cid, revision) = try Self.reference(comment, "comment \(comment.body)")
                comments[cid] = Comment(body: comment.body, author: comment.authorID, revision: revision)
            }
            tasks[id] = Task(
                title: task.title, details: task.details, state: task.state,
                project: task.projectID.flatMap { state.projects[$0]?.serverID },
                tags: task.tagIDs.compactMap { state.tags[$0]?.serverID }, dueDate: task.dueDate,
                priority: task.priority, waitingFor: task.waitingFor, revision: revision,
                subtasks: children ? subtasks : nil, comments: children ? comments : nil
            )
        }
    }

    /// What the server holds.
    init(server snapshot: FakeServerSnapshot, children: Bool = true) {
        for project in snapshot.projects.values {
            projects[project.id] = Named(
                name: project.name, color: project.color, active: project.state == .active, revision: project.revision
            )
        }
        for tag in snapshot.tags.values {
            tags[tag.id] = Named(name: tag.name, color: nil, active: tag.state == .active, revision: tag.revision)
        }
        for task in snapshot.tasks.values {
            tasks[task.id] = Task(
                title: task.title, details: task.details, state: task.state, project: task.projectID, tags: task.tagIDs,
                dueDate: task.dueDate, priority: task.priority, waitingFor: task.waitingFor, revision: task.revision,
                subtasks: children
                    ? Dictionary(
                        uniqueKeysWithValues: task.subtasks.map {
                            ($0.id, Subtask(title: $0.title, state: $0.state, revision: $0.revision))
                        }) : nil,
                comments: children
                    ? Dictionary(
                        uniqueKeysWithValues: task.comments.map {
                            ($0.id, Comment(body: $0.body, author: $0.actorID, revision: $0.revision))
                        }) : nil
            )
        }
    }

    private static func reference(_ record: some ServerBacked, _ name: String) throws(Unsynced) -> (String, Int) {
        guard let id = record.serverID, let revision = record.serverRevision else {
            throw Unsynced(description: "\(name) has no server id")
        }
        return (id, revision)
    }

    /// Without the archived projects and deleted tags `device` never saw: no
    /// endpoint lists them, so a device only knows those it saw active or
    /// that one of its tasks references.
    func restrictingInactive(to device: AccountData) -> AccountData {
        var copy = self
        copy.projects = projects.filter { $0.value.active || device.projects[$0.key] != nil }
        copy.tags = tags.filter { $0.value.active || device.tags[$0.key] != nil }
        return copy
    }
}

extension FakeServerSnapshot {
    func task(titled title: String) -> TaskDTO? { tasks.values.first { $0.title == title } }
    func project(named name: String) -> ProjectDTO? { projects.values.first { $0.name == name } }
    func tag(named name: String) -> TagDTO? { tags.values.first { $0.name == name } }
}
