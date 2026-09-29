import Foundation

/// Fields every synchronizable record carries. `serverID` and `serverRevision`
/// are nil until the server has acknowledged the record's creation.
public protocol ServerBacked {
    var serverID: String? { get }
    var serverRevision: Int? { get }
}

public struct TaskRecord: Identifiable, Hashable, Sendable, Codable, ServerBacked {
    public var id: TaskID
    public var serverID: String?
    public var serverRevision: Int?

    public var title: String
    public var details: String?
    public var state: TaskState
    /// The open list the task was in before it was completed or cancelled.
    /// Local knowledge only (the API does not expose it); nil when unknown.
    public var lastOpenList: OpenList?
    public var projectID: ProjectID?
    public var tagIDs: [TagID]
    public var dueDate: CalendarDay?
    public var priority: TaskPriority
    public var waitingFor: String?
    public var waitingSince: Date?
    public var completedAt: Date?
    public var cancelledAt: Date?
    /// Manual ordering: ascending `orderKey`, then `createdAt`, then `id`.
    public var orderKey: Int
    public var createdAt: Date
    public var updatedAt: Date

    public var subtasks: [SubtaskRecord]
    public var comments: [CommentRecord]
    /// When subtasks and comments were last loaded from the server. The list
    /// endpoint omits them, so they are hydrated per task.
    public var childrenSyncedAt: Date?

    public init(
        id: TaskID, serverID: String? = nil, serverRevision: Int? = nil, title: String,
        details: String? = nil, state: TaskState, lastOpenList: OpenList? = nil,
        projectID: ProjectID? = nil, tagIDs: [TagID] = [], dueDate: CalendarDay? = nil,
        priority: TaskPriority = .none, waitingFor: String? = nil, waitingSince: Date? = nil,
        completedAt: Date? = nil, cancelledAt: Date? = nil, orderKey: Int, createdAt: Date,
        updatedAt: Date, subtasks: [SubtaskRecord] = [], comments: [CommentRecord] = [],
        childrenSyncedAt: Date? = nil
    ) {
        self.id = id
        self.serverID = serverID
        self.serverRevision = serverRevision
        self.title = title
        self.details = details
        self.state = state
        self.lastOpenList = lastOpenList
        self.projectID = projectID
        self.tagIDs = tagIDs
        self.dueDate = dueDate
        self.priority = priority
        self.waitingFor = waitingFor
        self.waitingSince = waitingSince
        self.completedAt = completedAt
        self.cancelledAt = cancelledAt
        self.orderKey = orderKey
        self.createdAt = createdAt
        self.updatedAt = updatedAt
        self.subtasks = subtasks
        self.comments = comments
        self.childrenSyncedAt = childrenSyncedAt
    }

    public var isOpen: Bool { state.isOpen }
    public var openList: OpenList? { state.openList }
}

public struct SubtaskRecord: Identifiable, Hashable, Sendable, Codable, ServerBacked {
    public var id: SubtaskID
    public var serverID: String?
    public var serverRevision: Int?
    public var title: String
    public var state: SubtaskState
    public var orderKey: Int

    public init(
        id: SubtaskID, serverID: String? = nil, serverRevision: Int? = nil, title: String,
        state: SubtaskState = .open, orderKey: Int
    ) {
        self.id = id
        self.serverID = serverID
        self.serverRevision = serverRevision
        self.title = title
        self.state = state
        self.orderKey = orderKey
    }
}

public struct CommentRecord: Identifiable, Hashable, Sendable, Codable, ServerBacked {
    public var id: CommentID
    public var serverID: String?
    public var serverRevision: Int?
    public var body: String
    /// The server's `actor_id`. Nil for comments written on this device that
    /// the server has not acknowledged yet (they are the signed-in user's).
    public var authorID: String?
    public var createdAt: Date
    public var editedAt: Date?

    public init(
        id: CommentID, serverID: String? = nil, serverRevision: Int? = nil, body: String,
        authorID: String? = nil, createdAt: Date, editedAt: Date? = nil
    ) {
        self.id = id
        self.serverID = serverID
        self.serverRevision = serverRevision
        self.body = body
        self.authorID = authorID
        self.createdAt = createdAt
        self.editedAt = editedAt
    }
}

public struct ProjectRecord: Identifiable, Hashable, Sendable, Codable, ServerBacked {
    public var id: ProjectID
    public var serverID: String?
    public var serverRevision: Int?
    public var name: String
    /// Free-form colour token (the API stores up to 64 characters; the apps use `#RRGGBB`).
    public var color: String?
    public var state: ProjectState
    public var createdAt: Date

    public init(
        id: ProjectID, serverID: String? = nil, serverRevision: Int? = nil, name: String,
        color: String? = nil, state: ProjectState = .active, createdAt: Date
    ) {
        self.id = id
        self.serverID = serverID
        self.serverRevision = serverRevision
        self.name = name
        self.color = color
        self.state = state
        self.createdAt = createdAt
    }
}

public struct TagRecord: Identifiable, Hashable, Sendable, Codable, ServerBacked {
    public var id: TagID
    public var serverID: String?
    public var serverRevision: Int?
    public var name: String
    public var state: TagState
    public var createdAt: Date

    public init(
        id: TagID, serverID: String? = nil, serverRevision: Int? = nil, name: String,
        state: TagState = .active, createdAt: Date
    ) {
        self.id = id
        self.serverID = serverID
        self.serverRevision = serverRevision
        self.name = name
        self.state = state
        self.createdAt = createdAt
    }
}

/// The whole GTD dataset. It is used twice: as the *base* (what the server
/// has confirmed) and as the *current* state the UI shows, which is always
/// `OutboxReplayer.replay(outbox, onto: base).state`.
public struct GTDState: Hashable, Sendable, Codable {
    public var tasks: [TaskID: TaskRecord]
    public var projects: [ProjectID: ProjectRecord]
    public var tags: [TagID: TagRecord]

    public init(
        tasks: [TaskID: TaskRecord] = [:], projects: [ProjectID: ProjectRecord] = [:],
        tags: [TagID: TagRecord] = [:]
    ) {
        self.tasks = tasks
        self.projects = projects
        self.tags = tags
    }

    public static let empty = GTDState()
}
