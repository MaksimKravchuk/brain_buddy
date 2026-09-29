import Foundation

/// The four open GTD lists. Raw values are the server's task states.
public enum OpenList: String, CaseIterable, Codable, Sendable, Hashable, Identifiable {
    case inbox, next, waiting, someday

    public var id: String { rawValue }
    public var taskState: TaskState { TaskState(rawValue: rawValue)! }

    /// Verbatim list names from the design system.
    public var title: String {
        switch self {
        case .inbox: "Inbox"
        case .next: "Next actions"
        case .waiting: "Waiting for"
        case .someday: "Someday / maybe"
        }
    }
}

/// Server task lifecycle (ADR-0006): four open states and two terminal ones.
public enum TaskState: String, CaseIterable, Codable, Sendable, Hashable {
    case inbox, next, waiting, someday, completed, cancelled

    public var openList: OpenList? { OpenList(rawValue: rawValue) }
    public var isOpen: Bool { openList != nil }
    public var isTerminal: Bool { !isOpen }
}

public enum TaskPriority: String, CaseIterable, Codable, Sendable, Hashable, Comparable {
    case none, low, medium, high

    /// high → medium → low → none, as the server sorts.
    public var sortRank: Int {
        switch self {
        case .high: 0
        case .medium: 1
        case .low: 2
        case .none: 3
        }
    }

    public static func < (lhs: TaskPriority, rhs: TaskPriority) -> Bool { lhs.sortRank > rhs.sortRank }

    public var title: String {
        switch self {
        case .none: "No priority"
        case .low: "Low"
        case .medium: "Medium"
        case .high: "High"
        }
    }
}

public enum TaskTransitionAction: String, Codable, Sendable, Hashable {
    case move, complete, reopen, cancel
}

public enum SubtaskState: String, Codable, Sendable, Hashable {
    case open, completed, cancelled
}

public enum SubtaskTransitionAction: String, Codable, Sendable, Hashable {
    case complete, reopen, cancel

    public var targetState: SubtaskState {
        switch self {
        case .complete: .completed
        case .reopen: .open
        case .cancel: .cancelled
        }
    }
}

public enum ProjectState: String, Codable, Sendable, Hashable {
    case active, archived
}

public enum TagState: String, Codable, Sendable, Hashable {
    case active, deleted
}

/// Server-side input limits, mirrored so validation never needs the network.
public enum GTDLimits {
    public static let title = 500
    public static let details = 20_000
    public static let waitingFor = 500
    public static let name = 500
    public static let color = 64
    public static let comment = 20_000
}
