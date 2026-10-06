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

    /// The formulation clock (spec 020): nil unless in Next with a started
    /// clock. Maintained only by `GTDReducer`; a pull replaces it with the
    /// server's.
    public var formulation: FormulationClock?
    /// FR-005; survives leaving Next.
    public var consecutiveStalledFormulations: Int
    /// Only while in Someday after an auto-park.
    public var parked: ParkMarker?

    public init(
        id: TaskID, serverID: String? = nil, serverRevision: Int? = nil, title: String,
        details: String? = nil, state: TaskState, lastOpenList: OpenList? = nil,
        projectID: ProjectID? = nil, tagIDs: [TagID] = [], dueDate: CalendarDay? = nil,
        priority: TaskPriority = .none, waitingFor: String? = nil, waitingSince: Date? = nil,
        completedAt: Date? = nil, cancelledAt: Date? = nil, orderKey: Int, createdAt: Date,
        updatedAt: Date, subtasks: [SubtaskRecord] = [], comments: [CommentRecord] = [],
        childrenSyncedAt: Date? = nil, formulation: FormulationClock? = nil,
        consecutiveStalledFormulations: Int = 0, parked: ParkMarker? = nil
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
        self.formulation = formulation
        self.consecutiveStalledFormulations = consecutiveStalledFormulations
        self.parked = parked
    }

    public var isOpen: Bool { state.isOpen }
    public var openList: OpenList? { state.openList }

    /// The fields the formulation rule reads and writes. Setting it writes
    /// back state, title, clock, stalled count, due date and park marker;
    /// `revision` is the server's number and is never written.
    public var clocked: ClockedTask {
        get {
            ClockedTask(
                state: state, title: title, revision: serverRevision ?? 0, formulation: formulation,
                consecutiveStalledFormulations: consecutiveStalledFormulations, dueDate: dueDate, parked: parked
            )
        }
        set {
            if let state = newValue.state { self.state = state }
            if let title = newValue.title { self.title = title }
            formulation = newValue.formulation
            consecutiveStalledFormulations = newValue.consecutiveStalledFormulations
            dueDate = newValue.dueDate
            parked = newValue.parked
        }
    }
}

extension TaskRecord {
    private enum CodingKeys: String, CodingKey {
        case id, serverID, serverRevision, title, details, state, lastOpenList, projectID, tagIDs, dueDate, priority
        case waitingFor, waitingSince, completedAt, cancelledAt, orderKey, createdAt, updatedAt, subtasks, comments
        case childrenSyncedAt, formulation, consecutiveStalledFormulations, parked
    }

    /// Documents written before spec 020 have no clock fields; they decode
    /// with no clock, a stalled count of 0 and no park marker.
    public init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        id = try values.decode(TaskID.self, forKey: .id)
        serverID = try values.decodeIfPresent(String.self, forKey: .serverID)
        serverRevision = try values.decodeIfPresent(Int.self, forKey: .serverRevision)
        title = try values.decode(String.self, forKey: .title)
        details = try values.decodeIfPresent(String.self, forKey: .details)
        state = try values.decode(TaskState.self, forKey: .state)
        lastOpenList = try values.decodeIfPresent(OpenList.self, forKey: .lastOpenList)
        projectID = try values.decodeIfPresent(ProjectID.self, forKey: .projectID)
        tagIDs = try values.decode([TagID].self, forKey: .tagIDs)
        dueDate = try values.decodeIfPresent(CalendarDay.self, forKey: .dueDate)
        priority = try values.decode(TaskPriority.self, forKey: .priority)
        waitingFor = try values.decodeIfPresent(String.self, forKey: .waitingFor)
        waitingSince = try values.decodeIfPresent(Date.self, forKey: .waitingSince)
        completedAt = try values.decodeIfPresent(Date.self, forKey: .completedAt)
        cancelledAt = try values.decodeIfPresent(Date.self, forKey: .cancelledAt)
        orderKey = try values.decode(Int.self, forKey: .orderKey)
        createdAt = try values.decode(Date.self, forKey: .createdAt)
        updatedAt = try values.decode(Date.self, forKey: .updatedAt)
        subtasks = try values.decode([SubtaskRecord].self, forKey: .subtasks)
        comments = try values.decode([CommentRecord].self, forKey: .comments)
        childrenSyncedAt = try values.decodeIfPresent(Date.self, forKey: .childrenSyncedAt)
        formulation = try values.decodeIfPresent(FormulationClock.self, forKey: .formulation)
        consecutiveStalledFormulations =
            try values.decodeIfPresent(Int.self, forKey: .consecutiveStalledFormulations) ?? 0
        parked = try values.decodeIfPresent(ParkMarker.self, forKey: .parked)
    }

    /// The clock fields are written only when set, so a task without a clock
    /// keeps the bytes it had before spec 020.
    public func encode(to encoder: any Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        try values.encode(id, forKey: .id)
        try values.encodeIfPresent(serverID, forKey: .serverID)
        try values.encodeIfPresent(serverRevision, forKey: .serverRevision)
        try values.encode(title, forKey: .title)
        try values.encodeIfPresent(details, forKey: .details)
        try values.encode(state, forKey: .state)
        try values.encodeIfPresent(lastOpenList, forKey: .lastOpenList)
        try values.encodeIfPresent(projectID, forKey: .projectID)
        try values.encode(tagIDs, forKey: .tagIDs)
        try values.encodeIfPresent(dueDate, forKey: .dueDate)
        try values.encode(priority, forKey: .priority)
        try values.encodeIfPresent(waitingFor, forKey: .waitingFor)
        try values.encodeIfPresent(waitingSince, forKey: .waitingSince)
        try values.encodeIfPresent(completedAt, forKey: .completedAt)
        try values.encodeIfPresent(cancelledAt, forKey: .cancelledAt)
        try values.encode(orderKey, forKey: .orderKey)
        try values.encode(createdAt, forKey: .createdAt)
        try values.encode(updatedAt, forKey: .updatedAt)
        try values.encode(subtasks, forKey: .subtasks)
        try values.encode(comments, forKey: .comments)
        try values.encodeIfPresent(childrenSyncedAt, forKey: .childrenSyncedAt)
        try values.encodeIfPresent(formulation, forKey: .formulation)
        if consecutiveStalledFormulations != 0 {
            try values.encode(consecutiveStalledFormulations, forKey: .consecutiveStalledFormulations)
        }
        try values.encodeIfPresent(parked, forKey: .parked)
    }
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
    /// The weekly review's records (spec 020, data-model E10).
    public var review: ReviewState

    public init(
        tasks: [TaskID: TaskRecord] = [:], projects: [ProjectID: ProjectRecord] = [:],
        tags: [TagID: TagRecord] = [:], review: ReviewState = .empty
    ) {
        self.tasks = tasks
        self.projects = projects
        self.tags = tags
        self.review = review
    }

    public static let empty = GTDState()

    enum CodingKeys: String, CodingKey {
        case tasks, projects, tags, review
    }

    /// A state written before spec 020 has no `review`; it decodes empty.
    public init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        tasks = try values.decode([TaskID: TaskRecord].self, forKey: .tasks)
        projects = try values.decode([ProjectID: ProjectRecord].self, forKey: .projects)
        tags = try values.decode([TagID: TagRecord].self, forKey: .tags)
        review = try values.decodeIfPresent(ReviewState.self, forKey: .review) ?? .empty
    }
}
