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
///
/// While the device is locked, suggestions and search return nothing, so
/// Siri never lists or reads back task titles on the Lock Screen. Lookup by
/// id still works (for example the task a Lock Screen capture just created).
struct TaskEntityQuery: EntityStringQuery {
    init() {}

    func entities(for identifiers: [TaskEntity.ID]) async throws -> [TaskEntity] {
        try await TaskEntityLookup.entities(for: identifiers)
    }

    func entities(matching string: String) async throws -> [TaskEntity] {
        guard !DeviceLock.isLocked() else { return [] }
        return try await TaskEntityLookup.search(string)
    }

    func suggestedEntities() async throws -> [TaskEntity] {
        guard !DeviceLock.isLocked() else { return [] }
        return try await TaskEntityLookup.suggested()
    }
}

/// Reads the shared store on the main actor, where `Workspace` lives.
@MainActor
enum TaskEntityLookup {
    /// Siri and Shortcuts show short lists; keep them quick to build.
    static let limit = 50

    static func entities(for identifiers: [String]) async throws -> [TaskEntity] {
        let workspace = await SharedWorkspace.make()
        var result: [TaskEntity] = []
        for batch in stride(from: 0, to: identifiers.count, by: 200).map({ start in
            Array(identifiers[start ..< min(start + 200, identifiers.count)])
        }) {
            let ids = batch.map(TaskID.init)
            let page = try await workspace.prepareTaskRecords(ids)
            result.append(contentsOf: ids.compactMap { page.tasks[$0].map(TaskEntity.init(record:)) })
        }
        return result
    }

    static func suggested() async throws -> [TaskEntity] {
        let workspace = await SharedWorkspace.make()
        let reads: [(Destination, ListOptions)] = [(.dateView(.overdue), ListOptions()), (.dateView(.today), ListOptions()), (.list(.next), ListOptions())]
        var records: [TaskRecord] = []
        for (destination, options) in reads {
            await workspace.prepareList(destination, options: options)
            guard workspace.listReadiness(destination, options: options) == .ready else {
                throw TaskEntityQueryUnavailable()
            }
            records.append(contentsOf: openTasks(in: workspace.list(destination, options: options)))
        }
        return entities(from: records)
    }

    static func search(_ text: String) async throws -> [TaskEntity] {
        let query = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return try await suggested() }
        let workspace = await SharedWorkspace.make()
        let options = ListOptions(search: query)
        await workspace.prepareList(.search(query), options: options)
        guard workspace.listReadiness(.search(query), options: options) == .ready else {
            throw TaskEntityQueryUnavailable()
        }
        return entities(from: openTasks(in: workspace.list(.search(query), options: options)))
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

private struct TaskEntityQueryUnavailable: Error {}
