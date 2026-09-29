import Foundation

public enum DateView: String, CaseIterable, Codable, Sendable, Hashable {
    /// Open tasks due before today.
    case overdue
    /// Open tasks due today.
    case today
    /// Open tasks due after today.
    case upcoming

    public var title: String {
        switch self {
        case .overdue: "Overdue"
        case .today: "Today"
        case .upcoming: "Upcoming"
        }
    }
}

public enum HistoryKind: String, CaseIterable, Codable, Sendable, Hashable {
    case completed, cancelled

    public var title: String {
        switch self {
        case .completed: "Completed"
        case .cancelled: "Cancelled"
        }
    }
}

/// A screen that lists tasks.
public enum Destination: Hashable, Codable, Sendable {
    /// Inbox shows only projectless inbox tasks (`docs/projectless-inbox-contract.md`).
    case list(OpenList)
    /// Overdue, Today and Upcoming as three sections.
    case agenda
    case dateView(DateView)
    case project(ProjectID)
    case tag(TagID)
    case history(HistoryKind)
    /// Title and notes, NFKC + case- and diacritic-insensitive, all states.
    case search(String)
}

public enum TaskSort: String, CaseIterable, Codable, Sendable, Hashable {
    /// `orderKey`, `createdAt`, `id`.
    case manual
    /// Dated first by date, then manual.
    case due
    /// high → none, then manual.
    case priority
    /// Localized title order, then `id`.
    case title

    public var title: String {
        switch self {
        case .manual: "Manual"
        case .due: "Due date"
        case .priority: "Priority"
        case .title: "Title"
        }
    }
}

public struct ListOptions: Hashable, Codable, Sendable {
    public var sort: TaskSort
    /// Sections per project, sorted by name, with tasks without a project last.
    /// Ignored in Inbox (always projectless) and project views.
    public var groupByProject: Bool
    /// Append this list's completed tasks as a section (tasks whose
    /// `lastOpenList` is the list; unknown origins only appear in History).
    public var showCompleted: Bool
    public var showCancelled: Bool
    /// Empty means every priority.
    public var priorities: Set<TaskPriority>
    /// Narrow to tasks carrying this tag (GTD "context").
    public var tagFilter: TagID?

    public init(
        sort: TaskSort = .manual, groupByProject: Bool = false, showCompleted: Bool = false,
        showCancelled: Bool = false, priorities: Set<TaskPriority> = [], tagFilter: TagID? = nil
    ) {
        self.sort = sort
        self.groupByProject = groupByProject
        self.showCompleted = showCompleted
        self.showCancelled = showCancelled
        self.priorities = priorities
        self.tagFilter = tagFilter
    }
}

public struct TaskSection: Identifiable, Hashable, Sendable {
    public enum Kind: Hashable, Sendable {
        case open
        case project(ProjectID?)
        case dateView(DateView)
        case list(OpenList)
        case completed
        case cancelled
    }

    /// Stable across recomputation, for SwiftUI diffing.
    public var id: String
    /// Section header, or nil for a single unnamed section.
    public var title: String?
    public var kind: Kind
    public var tasks: [TaskRecord]

    public init(id: String, title: String?, kind: Kind, tasks: [TaskRecord]) {
        self.id = id
        self.title = title
        self.kind = kind
        self.tasks = tasks
    }
}

public struct TaskListResult: Hashable, Sendable {
    public var sections: [TaskSection]
    /// Open tasks in the result (terminal history rows excluded).
    public var openCount: Int

    public init(sections: [TaskSection], openCount: Int) {
        self.sections = sections
        self.openCount = openCount
    }

    public var isEmpty: Bool { sections.allSatisfy(\.tasks.isEmpty) }
}

/// Global badge counts; they ignore the screen's filters.
public struct ListCounts: Hashable, Sendable {
    public var inbox: Int
    public var next: Int
    public var waiting: Int
    public var someday: Int
    public var overdue: Int
    public var today: Int

    public init(inbox: Int = 0, next: Int = 0, waiting: Int = 0, someday: Int = 0, overdue: Int = 0, today: Int = 0) {
        self.inbox = inbox
        self.next = next
        self.waiting = waiting
        self.someday = someday
        self.overdue = overdue
        self.today = today
    }

    public func count(for list: OpenList) -> Int {
        switch list {
        case .inbox: inbox
        case .next: next
        case .waiting: waiting
        case .someday: someday
        }
    }
}

public struct ProjectSummary: Identifiable, Hashable, Sendable {
    public var project: ProjectRecord
    public var openTaskCount: Int
    public var nextActionCount: Int
    /// An active project with open tasks but no next action — the GTD signal
    /// that a project is stuck.
    public var needsNextAction: Bool { project.state == .active && nextActionCount == 0 }

    public var id: ProjectID { project.id }

    public init(project: ProjectRecord, openTaskCount: Int, nextActionCount: Int) {
        self.project = project
        self.openTaskCount = openTaskCount
        self.nextActionCount = nextActionCount
    }
}

public struct TagSummary: Identifiable, Hashable, Sendable {
    public var tag: TagRecord
    public var openTaskCount: Int
    public var id: TagID { tag.id }

    public init(tag: TagRecord, openTaskCount: Int) {
        self.tag = tag
        self.openTaskCount = openTaskCount
    }
}

/// Pure read model over `GTDState`. `today` is injected so date views are
/// deterministic and follow the device's local calendar day.
public enum GTDQueries {
    public static func list(
        _ destination: Destination, options: ListOptions, in state: GTDState, today: CalendarDay
    ) -> TaskListResult {
        fatalError("GTDQueries.list is not implemented yet")
    }

    public static func counts(in state: GTDState, today: CalendarDay) -> ListCounts {
        fatalError("GTDQueries.counts is not implemented yet")
    }

    /// Active projects by name (archived ones when `archived` is true).
    public static func projects(in state: GTDState, archived: Bool = false) -> [ProjectSummary] {
        fatalError("GTDQueries.projects is not implemented yet")
    }

    /// Active tags by name.
    public static func tags(in state: GTDState) -> [TagSummary] {
        fatalError("GTDQueries.tags is not implemented yet")
    }
}
