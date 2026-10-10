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
    /// Open tasks in the list, any project — except Inbox, which shows only
    /// projectless inbox tasks (`docs/projectless-inbox-contract.md`).
    case list(OpenList)
    /// Open dated tasks as Overdue, Today and Upcoming sections (empty ones
    /// omitted), in due order unless another sort is chosen.
    case agenda
    /// One of the agenda's sections on its own screen.
    case dateView(DateView)
    /// Open tasks in the project, one section per list in
    /// `GTDQueries.projectListOrder`. Works for archived projects too.
    case project(ProjectID)
    /// Open tasks carrying the tag, any list.
    case tag(TagID)
    /// Completed or cancelled tasks, most recent first.
    case history(HistoryKind)
    /// Title and notes, NFKC + case- and diacritic-insensitive, all states:
    /// open matches first, then completed, then cancelled. A blank query
    /// matches nothing.
    case search(String)
}

public enum TaskSort: String, CaseIterable, Codable, Sendable, Hashable {
    /// `orderKey`, `createdAt`, `id`. Date views use `.due` instead, and
    /// history most recent first.
    case manual
    /// Dated first by date, then manual.
    case due
    /// high → none, then manual.
    case priority
    /// Title ignoring case, diacritics and width (the same on every
    /// platform), then `id`.
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
    /// Sections per project, sorted by name, with tasks without a project last
    /// ("No project"). Applies to open tasks; the Completed and Cancelled
    /// sections stay flat. Ignored in Inbox (always projectless), project
    /// views and the agenda (already sectioned by date).
    public var groupByProject: Bool
    /// Append this list's completed tasks as a section (tasks whose
    /// `lastOpenList` is the list; unknown origins only appear in History).
    /// Project, tag and date screens append the completed tasks in that
    /// project, with that tag or due in that range. Search always includes
    /// them; History ignores it.
    public var showCompleted: Bool
    /// As `showCompleted`, for cancelled tasks.
    public var showCancelled: Bool
    /// Empty means every priority.
    public var priorities: Set<TaskPriority>
    /// Narrow to tasks carrying this tag (GTD "context").
    public var tagFilter: TagID?
    /// Narrow the destination with canonical title/notes search before paging.
    public var search: String?

    public init(
        sort: TaskSort = .manual, groupByProject: Bool = false, showCompleted: Bool = false,
        showCancelled: Bool = false, priorities: Set<TaskPriority> = [], tagFilter: TagID? = nil, search: String? = nil
    ) {
        self.sort = sort
        self.groupByProject = groupByProject
        self.showCompleted = showCompleted
        self.showCancelled = showCancelled
        self.priorities = priorities
        self.tagFilter = tagFilter
        self.search = search
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

    /// Stable across recomputation, for SwiftUI diffing: `open`,
    /// `project:<id>`, `none` (no project), `date:<overdue|today|upcoming>`,
    /// `list:<inbox|next|waiting|someday>`, `completed`, `cancelled`.
    public var id: String
    /// Section header, or nil for a single unnamed section.
    public var title: String?
    public var kind: Kind
    public var tasks: [TaskRecord]
    private var canonicalTotalCount: Int?
    /// Whole matching section count; legacy constructors retain their computed total.
    public var totalCount: Int { canonicalTotalCount ?? tasks.count }

    public init(id: String, title: String?, kind: Kind, tasks: [TaskRecord], totalCount: Int? = nil) {
        self.id = id
        self.title = title
        self.kind = kind
        self.tasks = tasks
        canonicalTotalCount = totalCount
    }
}

public struct TaskListResult: Hashable, Sendable {
    public var sections: [TaskSection]
    /// Open tasks in the result (terminal history rows excluded).
    public var openCount: Int
    private var canonicalTotalCount: Int?
    private var canonicalCompletedCount: Int?
    private var canonicalCancelledCount: Int?
    public var totalCount: Int { canonicalTotalCount ?? sections.reduce(0) { $0 + $1.totalCount } }
    public var completedCount: Int { canonicalCompletedCount ?? sections.flatMap(\.tasks).filter { $0.state == .completed }.count }
    public var cancelledCount: Int { canonicalCancelledCount ?? sections.flatMap(\.tasks).filter { $0.state == .cancelled }.count }

    public init(sections: [TaskSection], openCount: Int, totalCount: Int? = nil,
                completedCount: Int? = nil, cancelledCount: Int? = nil) {
        self.sections = sections
        self.openCount = openCount
        canonicalTotalCount = totalCount
        canonicalCompletedCount = completedCount
        canonicalCancelledCount = cancelledCount
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
    /// Whole-project facts from a canonical native summary, never a task page count.
    public var countsByState: [OpenList: Int]?
    /// An active project without an open next action (including one with no
    /// open tasks at all) — the GTD signal that a project is stuck.
    public var needsNextAction: Bool { project.state == .active && nextActionCount == 0 }

    public var id: ProjectID { project.id }

    public init(project: ProjectRecord, openTaskCount: Int, nextActionCount: Int, countsByState: [OpenList: Int]? = nil) {
        self.project = project
        self.openTaskCount = openTaskCount
        self.nextActionCount = nextActionCount
        self.countsByState = countsByState
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
/// deterministic and follow the device's local calendar day. It mirrors the
/// server's list semantics (`backend/app/modules/tasks/service.py`) and the
/// web task list; every call is O(n log n) in the number of tasks.
public enum GTDQueries {
    /// The tasks a screen shows. Sections are never empty (an empty result
    /// has none); open sections come first, then "Completed", then
    /// "Cancelled". `options.priorities` and `options.tagFilter` apply to
    /// every section.
    public static func list(
        _ destination: Destination, options: ListOptions, in state: GTDState, today: CalendarDay
    ) -> TaskListResult {
        TaskListBuilder(state: state, options: options, today: today).build(destination)
    }

    /// Sidebar and badge counts over open tasks: Inbox counts projectless
    /// inbox tasks, the other lists count every project.
    public static func counts(in state: GTDState, today: CalendarDay) -> ListCounts {
        var counts = ListCounts()
        for task in state.tasks.values {
            switch task.state {
            case .inbox: if task.projectID == nil { counts.inbox += 1 }
            case .next: counts.next += 1
            case .waiting: counts.waiting += 1
            case .someday: counts.someday += 1
            case .completed, .cancelled: continue
            }
            switch DateView(due: task.dueDate, today: today) {
            case .overdue: counts.overdue += 1
            case .today: counts.today += 1
            case .upcoming, nil: break
            }
        }
        return counts
    }

    /// Active projects by name (archived ones when `archived` is true): the
    /// normalized name ignoring diacritics, then the display name.
    public static func projects(in state: GTDState, archived: Bool = false) -> [ProjectSummary] {
        let wanted: ProjectState = archived ? .archived : .active
        var openCounts: [ProjectID: Int] = [:]
        var nextCounts: [ProjectID: Int] = [:]
        for task in state.tasks.values where task.isOpen {
            guard let id = task.projectID else { continue }
            openCounts[id, default: 0] += 1
            if task.state == .next { nextCounts[id, default: 0] += 1 }
        }
        return state.projects.values
            .filter { $0.state == wanted }
            .map { (key: $0.nameSortKey, project: $0) }
            .sorted { $0.key < $1.key }
            .map {
                ProjectSummary(
                    project: $0.project, openTaskCount: openCounts[$0.project.id] ?? 0,
                    nextActionCount: nextCounts[$0.project.id] ?? 0)
            }
    }

    /// Active tags by name (ignoring a leading `@` and diacritics), with the
    /// number of open tasks carrying each.
    public static func tags(in state: GTDState) -> [TagSummary] {
        var openCounts: [TagID: Int] = [:]
        for task in state.tasks.values where task.isOpen {
            for id in Set(task.tagIDs) { openCounts[id, default: 0] += 1 }
        }
        return state.tags.values
            .filter { $0.state == .active }
            .map { (key: $0.nameSortKey, tag: $0) }
            .sorted { $0.key < $1.key }
            .map { TagSummary(tag: $0.tag, openTaskCount: openCounts[$0.tag.id] ?? 0) }
    }
}

extension GTDQueries {
    /// The tasks a screen shows, from the rules `rules` selects. With `.rust` the shared core
    /// answers (and refuses a destination or option it has no answer for with
    /// `RustDomainError.unsupportedQuery`); with `.legacy` the Swift read model does.
    /// `calendar` fixes the device's day and zone.
    public static func list(
        _ destination: Destination, options: ListOptions, in state: GTDState, now: Date,
        calendar: Calendar = .current, rules: RuleEpoch
    ) async throws -> TaskListResult {
        switch rules {
        case .legacy:
            return list(destination, options: options, in: state, today: CalendarDay(date: now, calendar: calendar))
        case .rust(let facade):
            return try await facade.list(
                destination, options: options, in: state, now: now, zone: calendar.timeZone.identifier)
        }
    }

    /// Sidebar and badge counts from the rules `rules` selects.
    public static func counts(
        in state: GTDState, now: Date, calendar: Calendar = .current, rules: RuleEpoch
    ) async throws -> ListCounts {
        switch rules {
        case .legacy:
            return counts(in: state, today: CalendarDay(date: now, calendar: calendar))
        case .rust(let facade):
            return try await facade.counts(in: state, now: now, zone: calendar.timeZone.identifier)
        }
    }

    /// Active (or archived) projects by name from the rules `rules` selects.
    public static func projects(
        in state: GTDState, archived: Bool = false, now: Date, calendar: Calendar = .current, rules: RuleEpoch
    ) async throws -> [ProjectSummary] {
        switch rules {
        case .legacy:
            return projects(in: state, archived: archived)
        case .rust(let facade):
            return try await facade.projects(
                in: state, archived: archived, now: now, zone: calendar.timeZone.identifier)
        }
    }

    /// Active tags by name from the rules `rules` selects.
    public static func tags(
        in state: GTDState, now: Date, calendar: Calendar = .current, rules: RuleEpoch
    ) async throws -> [TagSummary] {
        switch rules {
        case .legacy:
            return tags(in: state)
        case .rust(let facade):
            return try await facade.tags(in: state, now: now, zone: calendar.timeZone.identifier)
        }
    }

    /// How a project presents itself, from the rules `rules` selects.
    public static func projectDisplay(
        _ id: ProjectID, in state: GTDState, now: Date, calendar: Calendar = .current, rules: RuleEpoch
    ) async throws -> ProjectDisplay? {
        switch rules {
        case .legacy:
            return projectDisplay(id, in: state)
        case .rust(let facade):
            return try await facade.projectDisplay(id, in: state, now: now, zone: calendar.timeZone.identifier)
        }
    }
}
