import AppIntents
import BrainBuddyCore
import BrainBuddyWorkspace
import Foundation

/// A task as Siri, Shortcuts, Spotlight and widgets see it. `id` is the
/// permanent client id (`TaskID.rawValue`), so it stays valid across sync.
struct TaskEntity: AppEntity {
    static let typeDisplayRepresentation = TypeDisplayRepresentation(name: "Task")

    static let defaultQuery = TaskEntityQuery()

    let id: String

    @Property(title: "Title")
    var title: String

    @Property(title: "List")
    var listName: String

    @Property(title: "Due date")
    var dueDate: Date?

    init(id: String, title: String, listName: String, dueDate: Date?) {
        self.id = id
        self.title = title
        self.listName = listName
        self.dueDate = dueDate
    }

    init(record: TaskRecord) {
        self.init(
            id: record.id.rawValue,
            title: record.title,
            listName: Self.listName(for: record.state),
            dueDate: record.dueDate?.startDate()
        )
    }

    var displayRepresentation: DisplayRepresentation {
        DisplayRepresentation(
            title: "\(title)",
            subtitle: "\(subtitle)",
            image: DisplayRepresentation.Image(systemName: "circle")
        )
    }

    /// "Next actions · Due 3 Oct"
    private var subtitle: String {
        guard let dueDate else { return listName }
        let due = "Due \(dueDate.formatted(.dateTime.day().month(.abbreviated)))"
        return listName.isEmpty ? due : "\(listName) · \(due)"
    }

    /// The list a task is in, or its history name once it is closed.
    static func listName(for state: TaskState) -> String {
        if let list = state.openList { return list.title }
        return state == .completed ? HistoryKind.completed.title : HistoryKind.cancelled.title
    }
}

/// Resolves tasks for Siri and Shortcuts: by id, suggestions (due today or
/// earlier, then next actions), and title search over open tasks.
struct TaskEntityQuery: EntityStringQuery {
    init() {}

    func entities(for identifiers: [TaskEntity.ID]) async throws -> [TaskEntity] {
        await TaskEntityLookup.entities(for: identifiers)
    }

    func entities(matching string: String) async throws -> [TaskEntity] {
        await TaskEntityLookup.search(string)
    }

    func suggestedEntities() async throws -> [TaskEntity] {
        await TaskEntityLookup.suggested()
    }
}

/// Reads the shared store on the main actor, where `Workspace` lives.
@MainActor
enum TaskEntityLookup {
    /// Siri and Shortcuts show short lists; keep them quick to build.
    static let limit = 50

    static func entities(for identifiers: [String]) async -> [TaskEntity] {
        let workspace = await SharedWorkspace.make()
        return identifiers.compactMap { identifier in
            workspace.task(TaskID(identifier)).map(TaskEntity.init(record:))
        }
    }

    static func suggested() async -> [TaskEntity] {
        let workspace = await SharedWorkspace.make()
        let records = openTasks(in: workspace.list(.dateView(.overdue)))
            + openTasks(in: workspace.list(.dateView(.today)))
            + openTasks(in: workspace.list(.list(.next)))
        return entities(from: records)
    }

    static func search(_ text: String) async -> [TaskEntity] {
        let query = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return await suggested() }
        let workspace = await SharedWorkspace.make()
        return entities(from: openTasks(in: workspace.list(.search(query))))
    }

    private static func openTasks(in result: TaskListResult) -> [TaskRecord] {
        result.sections.flatMap(\.tasks).filter(\.isOpen)
    }

    /// First occurrence of each task, capped at `limit`.
    private static func entities(from records: [TaskRecord]) -> [TaskEntity] {
        var seen = Set<TaskID>()
        var entities: [TaskEntity] = []
        for record in records where seen.insert(record.id).inserted {
            entities.append(TaskEntity(record: record))
            if entities.count == limit { break }
        }
        return entities
    }
}
