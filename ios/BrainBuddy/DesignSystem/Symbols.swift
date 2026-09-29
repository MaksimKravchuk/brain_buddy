import BrainBuddyCore

// SF Symbols instead of Lucide (docs/native-ios-app.md, deviation 1 — needs
// product sign-off). Mapping from the design doc: Inbox `tray`, Next
// `checklist`, Waiting `clock`, Someday `archivebox`, Today `calendar`,
// Search `magnifyingglass`, Lists `square.stack`.

extension OpenList {
    var symbolName: String {
        switch self {
        case .inbox: "tray"
        case .next: "checklist"
        case .waiting: "clock"
        case .someday: "archivebox"
        }
    }
}

extension DateView {
    var symbolName: String {
        switch self {
        case .overdue: "calendar.badge.exclamationmark"
        case .today: "calendar"
        case .upcoming: "calendar.badge.clock"
        }
    }
}

extension HistoryKind {
    var symbolName: String {
        switch self {
        case .completed: "checkmark.circle"
        case .cancelled: "xmark.circle"
        }
    }
}

extension TaskPriority {
    /// The number of exclamation marks carries the level, so priority never
    /// relies on colour alone.
    var symbolName: String {
        switch self {
        case .none: "minus"
        case .low: "exclamationmark"
        case .medium: "exclamationmark.2"
        case .high: "exclamationmark.3"
        }
    }
}

extension AppTab {
    var symbolName: String {
        switch self {
        case .inbox: OpenList.inbox.symbolName
        case .next: OpenList.next.symbolName
        case .today: "calendar"
        case .lists: "square.stack"
        case .search: "magnifyingglass"
        }
    }

    /// Tab titles; list names verbatim from the design system.
    var title: String {
        switch self {
        case .inbox: OpenList.inbox.title
        case .next: OpenList.next.title
        case .today: "Today"
        case .lists: "Lists"
        case .search: "Search"
        }
    }
}

/// Other symbols used across screens, so the same concept always gets the
/// same glyph.
enum BBSymbol {
    static let capture = "plus"
    static let project = "folder"
    static let archivedProjects = "archivebox"
    static let tag = "tag"
    static let settings = "gearshape"
    static let search = "magnifyingglass"
    static let processInbox = "tray.and.arrow.down"
    static let subtasks = "checklist"
    static let comments = "text.bubble"
    static let notes = "note.text"
    static let dueDate = "calendar"
    static let overdue = "exclamationmark.circle"
    static let waiting = "hourglass"
    static let complete = "checkmark.circle"
    static let cancel = "xmark.circle"
    static let reopen = "arrow.uturn.backward.circle"
    static let move = "arrow.right.circle"
    static let syncIssues = "exclamationmark.icloud"
    static let account = "person.crop.circle"
}
