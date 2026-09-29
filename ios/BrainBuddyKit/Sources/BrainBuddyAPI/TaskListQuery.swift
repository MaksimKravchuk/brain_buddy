import BrainBuddyCore
import Foundation

/// `GET /tasks` sort orders.
public enum TaskSort: String, Hashable, Sendable, CaseIterable {
    case manual, due, priority, title
}

/// The server accepts one due-date filter at a time.
public enum DueDateFilter: Hashable, Sendable {
    case before(CalendarDay)
    case on(CalendarDay)
    case after(CalendarDay)
}

/// Filters for `GET /tasks`. Without `state` the server returns the four open
/// lists; `includeCompleted` / `includeCancelled` add the terminal ones.
/// A `next_cursor` is bound to the filters that produced it, so follow a
/// cursor with the same query.
public struct TaskListQuery: Hashable, Sendable {
    public var state: TaskState?
    /// Server project id. Cannot be combined with `unassignedProject`.
    public var projectID: String?
    /// Server tag id.
    public var tagID: String?
    public var unassignedProject: Bool
    public var includeCompleted: Bool
    public var includeCancelled: Bool
    /// Search text; trimmed, and omitted when empty.
    public var search: String?
    /// Sent as repeated `priority` parameters, duplicates dropped.
    public var priorities: [TaskPriority]
    public var due: DueDateFilter?
    /// Nil uses the server default (`manual`).
    public var sort: TaskSort?
    /// 1...200; nil uses the server default (50).
    public var limit: Int?

    public init(
        state: TaskState? = nil, projectID: String? = nil, tagID: String? = nil, unassignedProject: Bool = false,
        includeCompleted: Bool = false, includeCancelled: Bool = false, search: String? = nil,
        priorities: [TaskPriority] = [], due: DueDateFilter? = nil, sort: TaskSort? = nil, limit: Int? = nil
    ) {
        self.state = state
        self.projectID = projectID
        self.tagID = tagID
        self.unassignedProject = unassignedProject
        self.includeCompleted = includeCompleted
        self.includeCancelled = includeCancelled
        self.search = search
        self.priorities = priorities
        self.due = due
        self.sort = sort
        self.limit = limit
    }

    /// Every task in every state, in manual order, 200 per page — the sync pull.
    public static let fullPull = TaskListQuery(
        includeCompleted: true, includeCancelled: true, sort: .manual, limit: BrainBuddyAPI.maximumPageSize
    )

    /// Query items in a fixed order. Booleans are sent only when true (the
    /// server's defaults are false).
    func queryItems(cursor: String?) -> [(name: String, value: String)] {
        var items: [(name: String, value: String)] = []
        if let state { items.append(("state", state.rawValue)) }
        if let projectID { items.append(("project_id", projectID)) }
        if let tagID { items.append(("tag_id", tagID)) }
        if unassignedProject { items.append(("unassigned_project", "true")) }
        if includeCompleted { items.append(("include_completed", "true")) }
        if includeCancelled { items.append(("include_cancelled", "true")) }
        if let search = search?.trimmingCharacters(in: .whitespacesAndNewlines), !search.isEmpty {
            items.append(("q", search))
        }
        var seen = Set<TaskPriority>()
        for priority in priorities where seen.insert(priority).inserted {
            items.append(("priority", priority.rawValue))
        }
        switch due {
        case .before(let day): items.append(("due_before", day.isoString))
        case .on(let day): items.append(("due_on", day.isoString))
        case .after(let day): items.append(("due_after", day.isoString))
        case nil: break
        }
        if let sort { items.append(("sort", sort.rawValue)) }
        if let cursor { items.append(("cursor", cursor)) }
        if let limit { items.append(("limit", String(limit))) }
        return items
    }
}
