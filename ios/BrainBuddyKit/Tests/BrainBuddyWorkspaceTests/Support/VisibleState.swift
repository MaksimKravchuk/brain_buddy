import BrainBuddyCore
import BrainBuddyWorkspace
import Foundation

/// What a person sees in the app, read through the workspace's public
/// queries and keyed by client id: which tasks every list, history, project
/// and tag screen shows, the badges, the projects and tags, and each task's
/// detail with its subtasks and comments.
///
/// Fields the server assigns when a request lands (timestamps and the manual
/// order) are left out, and screens are compared as sets: a fresh replay of a
/// compacted outbox may assign them differently (see `OutboxCompactor`).
struct VisibleState: Hashable {
    struct Detail: Hashable {
        var title: String
        var notes: String?
        var state: TaskState
        var project: ProjectID?
        var tags: [TagID]
        var due: CalendarDay?
        var priority: TaskPriority
        var waitingFor: String?
        var subtasks: [SubtaskID: String]
        var comments: [CommentID: String]
    }

    var tasks: [TaskID: Detail] = [:]
    var screens: [Destination: Set<TaskID>] = [:]
    var counts = ListCounts()
    var projects: [ProjectID: String] = [:]
    var archivedProjects: [ProjectID: String] = [:]
    var tags: [TagID: String] = [:]

    @MainActor
    init(_ workspace: Workspace) {
        counts = workspace.counts()
        for summary in workspace.projects() { projects[summary.id] = summary.project.name }
        for summary in workspace.projects(archived: true) { archivedProjects[summary.id] = summary.project.name }
        for summary in workspace.tags() { tags[summary.id] = summary.tag.name }

        var destinations: [Destination] = OpenList.allCases.map { .list($0) }
        destinations += [.agenda, .history(.completed), .history(.cancelled)]
        destinations += projects.keys.map { .project($0) } + archivedProjects.keys.map { .project($0) }
        destinations += tags.keys.map { .tag($0) }
        // Lists show their finished tasks too, which exercises `lastOpenList`.
        let everything = ListOptions(showCompleted: true, showCancelled: true)
        for destination in destinations {
            let shown = workspace.list(destination, options: everything).sections.flatMap(\.tasks)
            screens[destination] = Set(shown.map(\.id))
            for task in shown { tasks[task.id] = Self.detail(task) }
        }
    }

    static func detail(_ task: TaskRecord) -> Detail {
        Detail(
            title: task.title, notes: task.details, state: task.state, project: task.projectID, tags: task.tagIDs,
            due: task.dueDate, priority: task.priority, waitingFor: task.waitingFor,
            subtasks: Dictionary(uniqueKeysWithValues: task.subtasks.map { ($0.id, "\($0.title) · \($0.state.rawValue)") }),
            comments: Dictionary(uniqueKeysWithValues: task.comments.map { ($0.id, $0.body) })
        )
    }

    /// Task titles on a screen, sorted (for readable expectations).
    func titles(on destination: Destination) -> [String] {
        (screens[destination] ?? []).compactMap { tasks[$0]?.title }.sorted()
    }
}
