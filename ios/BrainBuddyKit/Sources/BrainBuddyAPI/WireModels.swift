import BrainBuddyCore
import Foundation

// Response DTOs, field for field with `backend/app/schemas/tasks.py` and
// `backend/app/schemas/auth.py`. Ids are the server's (`task_1a2b3c4d5e6f`);
// mapping them to client `EntityID`s is the sync engine's job. Decode with
// `BrainBuddyAPI.makeDecoder()` (datetimes are `WireDate`s).

/// `MeResponse` from `/auth/me`, `/auth/login` and `/auth/signup`.
public struct MeDTO: Codable, Hashable, Sendable {
    public var id: String
    public var email: String
    public var displayName: String?
    /// True only on a login that cancelled a pending account deletion.
    public var deletionCancelled: Bool
    public var featureFlags: [String: Bool]

    public init(
        id: String, email: String, displayName: String? = nil, deletionCancelled: Bool = false,
        featureFlags: [String: Bool] = [:]
    ) {
        self.id = id
        self.email = email
        self.displayName = displayName
        self.deletionCancelled = deletionCancelled
        self.featureFlags = featureFlags
    }

    enum CodingKeys: String, CodingKey {
        case id, email
        case displayName = "display_name"
        case deletionCancelled = "deletion_cancelled"
        case featureFlags = "feature_flags"
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        id = try values.decode(String.self, forKey: .id)
        email = try values.decode(String.self, forKey: .email)
        displayName = try values.decodeIfPresent(String.self, forKey: .displayName)
        deletionCancelled = try values.decodeIfPresent(Bool.self, forKey: .deletionCancelled) ?? false
        featureFlags = try values.decodeIfPresent([String: Bool].self, forKey: .featureFlags) ?? [:]
    }
}

/// `GET /projects?state=`: `active` is the default and the server's own.
public enum ProjectListState: String, Sendable {
    case active, archived, all
}

/// `ProjectResponse`. `GET /projects` lists the active ones unless a state is
/// asked for; `GET /projects/{id}` returns any state. The last three fields
/// are spec 021's and absent from an older server.
public struct ProjectDTO: Codable, Hashable, Sendable, Identifiable {
    public var id: String
    public var name: String
    public var color: String?
    public var state: ProjectState
    public var revision: Int
    public var openTaskCount: Int
    public var desiredOutcome: String?
    public var archivedAt: Date?
    public var archivedBeforeLossless: Bool

    public init(
        id: String, name: String, color: String? = nil, state: ProjectState, revision: Int, openTaskCount: Int = 0,
        desiredOutcome: String? = nil, archivedAt: Date? = nil, archivedBeforeLossless: Bool = false
    ) {
        self.id = id
        self.name = name
        self.color = color
        self.state = state
        self.revision = revision
        self.openTaskCount = openTaskCount
        self.desiredOutcome = desiredOutcome
        self.archivedAt = archivedAt
        self.archivedBeforeLossless = archivedBeforeLossless
    }

    enum CodingKeys: String, CodingKey {
        case id, name, color, state, revision
        case openTaskCount = "open_task_count"
        case desiredOutcome = "desired_outcome"
        case archivedAt = "archived_at"
        case archivedBeforeLossless = "archived_before_lossless"
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        id = try values.decode(String.self, forKey: .id)
        name = try values.decode(String.self, forKey: .name)
        color = try values.decodeIfPresent(String.self, forKey: .color)
        state = try values.decode(ProjectState.self, forKey: .state)
        revision = try values.decode(Int.self, forKey: .revision)
        openTaskCount = try values.decodeIfPresent(Int.self, forKey: .openTaskCount) ?? 0
        desiredOutcome = try values.decodeIfPresent(String.self, forKey: .desiredOutcome)
        archivedAt = try values.decodeIfPresent(Date.self, forKey: .archivedAt)
        archivedBeforeLossless = try values.decodeIfPresent(Bool.self, forKey: .archivedBeforeLossless) ?? false
    }
}

/// `TagResponse`. `GET /tags` lists active ones only; `GET /tags/{id}` returns any state.
public struct TagDTO: Codable, Hashable, Sendable, Identifiable {
    public var id: String
    public var name: String
    public var state: TagState
    public var revision: Int
    public var openTaskCount: Int

    public init(id: String, name: String, state: TagState, revision: Int, openTaskCount: Int = 0) {
        self.id = id
        self.name = name
        self.state = state
        self.revision = revision
        self.openTaskCount = openTaskCount
    }

    enum CodingKeys: String, CodingKey {
        case id, name, state, revision
        case openTaskCount = "open_task_count"
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        id = try values.decode(String.self, forKey: .id)
        name = try values.decode(String.self, forKey: .name)
        state = try values.decode(TagState.self, forKey: .state)
        revision = try values.decode(Int.self, forKey: .revision)
        openTaskCount = try values.decodeIfPresent(Int.self, forKey: .openTaskCount) ?? 0
    }
}

/// `TaskSubtaskResponse`. Subtask edits do not bump the parent task's revision.
public struct SubtaskDTO: Codable, Hashable, Sendable, Identifiable {
    public var id: String
    public var title: String
    public var state: SubtaskState
    public var orderKey: Int
    public var revision: Int

    public init(id: String, title: String, state: SubtaskState, orderKey: Int, revision: Int) {
        self.id = id
        self.title = title
        self.state = state
        self.orderKey = orderKey
        self.revision = revision
    }

    enum CodingKeys: String, CodingKey {
        case id, title, state, revision
        case orderKey = "order_key"
    }
}

/// `TaskCommentResponse`. Comment edits do not bump the parent task's revision.
public struct CommentDTO: Codable, Hashable, Sendable, Identifiable {
    public var id: String
    public var body: String
    public var actorID: String
    public var createdAt: Date
    public var editedAt: Date?
    public var revision: Int

    public init(id: String, body: String, actorID: String, createdAt: Date, editedAt: Date? = nil, revision: Int) {
        self.id = id
        self.body = body
        self.actorID = actorID
        self.createdAt = createdAt
        self.editedAt = editedAt
        self.revision = revision
    }

    enum CodingKeys: String, CodingKey {
        case id, body, revision
        case actorID = "actor_id"
        case createdAt = "created_at"
        case editedAt = "edited_at"
    }
}

/// `TaskResponse`. `subtasks` and `comments` are filled by `GET /tasks/{id}`
/// only; list pages and mutation responses carry them empty.
public struct TaskDTO: Codable, Hashable, Sendable, Identifiable {
    public var id: String
    public var title: String
    public var details: String?
    public var state: TaskState
    public var projectID: String?
    public var tagIDs: [String]
    public var dueDate: CalendarDay?
    public var priority: TaskPriority
    public var waitingFor: String?
    public var waitingSince: Date?
    public var orderKey: Int
    public var sourceCaptureIDs: [String]
    public var createdAt: Date
    public var updatedAt: Date
    public var completedAt: Date?
    public var cancelledAt: Date?
    public var revision: Int
    public var subtasks: [SubtaskDTO]
    public var comments: [CommentDTO]
    /// Spec 020 (http §2): nil unless the task is in Next with a started clock.
    public var formulation: TaskFormulationDTO?
    /// Spec 020: set only by auto-park, while the task is in Someday.
    public var parked: TaskParkDTO?

    public init(
        id: String, title: String, details: String? = nil, state: TaskState, projectID: String? = nil,
        tagIDs: [String] = [], dueDate: CalendarDay? = nil, priority: TaskPriority = .none,
        waitingFor: String? = nil, waitingSince: Date? = nil, orderKey: Int, sourceCaptureIDs: [String] = [],
        createdAt: Date, updatedAt: Date, completedAt: Date? = nil, cancelledAt: Date? = nil, revision: Int,
        subtasks: [SubtaskDTO] = [], comments: [CommentDTO] = [], formulation: TaskFormulationDTO? = nil,
        parked: TaskParkDTO? = nil
    ) {
        self.id = id
        self.title = title
        self.details = details
        self.state = state
        self.projectID = projectID
        self.tagIDs = tagIDs
        self.dueDate = dueDate
        self.priority = priority
        self.waitingFor = waitingFor
        self.waitingSince = waitingSince
        self.orderKey = orderKey
        self.sourceCaptureIDs = sourceCaptureIDs
        self.createdAt = createdAt
        self.updatedAt = updatedAt
        self.completedAt = completedAt
        self.cancelledAt = cancelledAt
        self.revision = revision
        self.subtasks = subtasks
        self.comments = comments
        self.formulation = formulation
        self.parked = parked
    }

    enum CodingKeys: String, CodingKey {
        case id, title, details, state, priority, revision, subtasks, comments, formulation, parked
        case projectID = "project_id"
        case tagIDs = "tag_ids"
        case dueDate = "due_date"
        case waitingFor = "waiting_for"
        case waitingSince = "waiting_since"
        case orderKey = "order_key"
        case sourceCaptureIDs = "source_capture_ids"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case completedAt = "completed_at"
        case cancelledAt = "cancelled_at"
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        id = try values.decode(String.self, forKey: .id)
        title = try values.decode(String.self, forKey: .title)
        details = try values.decodeIfPresent(String.self, forKey: .details)
        state = try values.decode(TaskState.self, forKey: .state)
        projectID = try values.decodeIfPresent(String.self, forKey: .projectID)
        tagIDs = try values.decodeIfPresent([String].self, forKey: .tagIDs) ?? []
        dueDate = try values.decodeIfPresent(CalendarDay.self, forKey: .dueDate)
        priority = try values.decodeIfPresent(TaskPriority.self, forKey: .priority) ?? .none
        waitingFor = try values.decodeIfPresent(String.self, forKey: .waitingFor)
        waitingSince = try values.decodeIfPresent(Date.self, forKey: .waitingSince)
        orderKey = try values.decode(Int.self, forKey: .orderKey)
        sourceCaptureIDs = try values.decodeIfPresent([String].self, forKey: .sourceCaptureIDs) ?? []
        createdAt = try values.decode(Date.self, forKey: .createdAt)
        updatedAt = try values.decode(Date.self, forKey: .updatedAt)
        completedAt = try values.decodeIfPresent(Date.self, forKey: .completedAt)
        cancelledAt = try values.decodeIfPresent(Date.self, forKey: .cancelledAt)
        revision = try values.decode(Int.self, forKey: .revision)
        subtasks = try values.decodeIfPresent([SubtaskDTO].self, forKey: .subtasks) ?? []
        comments = try values.decodeIfPresent([CommentDTO].self, forKey: .comments) ?? []
        formulation = try values.decodeIfPresent(TaskFormulationDTO.self, forKey: .formulation)
        parked = try values.decodeIfPresent(TaskParkDTO.self, forKey: .parked)
    }
}

/// `TaskFormulationResponse` (spec 020, http §2). The derived instants are
/// advisory for display and null while the owner is not activated.
public struct TaskFormulationDTO: Codable, Hashable, Sendable {
    public var id: String
    public var startedAt: Date
    public var extendedAt: Date?
    public var extensionReason: String?
    public var parkFloorAt: Date?
    public var consecutiveStalled: Int
    public var ageingAt: Date?
    public var askAt: Date?
    public var parkDueAt: Date?
    public var pausedUntil: Date?

    public init(
        id: String, startedAt: Date, extendedAt: Date? = nil, extensionReason: String? = nil, parkFloorAt: Date? = nil,
        consecutiveStalled: Int = 0, ageingAt: Date? = nil, askAt: Date? = nil, parkDueAt: Date? = nil,
        pausedUntil: Date? = nil
    ) {
        self.id = id
        self.startedAt = startedAt
        self.extendedAt = extendedAt
        self.extensionReason = extensionReason
        self.parkFloorAt = parkFloorAt
        self.consecutiveStalled = consecutiveStalled
        self.ageingAt = ageingAt
        self.askAt = askAt
        self.parkDueAt = parkDueAt
        self.pausedUntil = pausedUntil
    }

    enum CodingKeys: String, CodingKey {
        case id
        case startedAt = "started_at"
        case extendedAt = "extended_at"
        case extensionReason = "extension_reason"
        case parkFloorAt = "park_floor_at"
        case consecutiveStalled = "consecutive_stalled"
        case ageingAt = "ageing_at"
        case askAt = "ask_at"
        case parkDueAt = "park_due_at"
        case pausedUntil = "paused_until"
    }

    /// The clock fields as the device stores them.
    public var clock: FormulationClock {
        FormulationClock(
            id: FormulationID(id), startedAt: startedAt, extendedAt: extendedAt, extensionReason: extensionReason,
            parkFloorAt: parkFloorAt
        )
    }
}

/// `TaskParkResponse`: `clock_before` stays on the server.
public struct TaskParkDTO: Codable, Hashable, Sendable {
    public var at: Date
    public var formulationID: String

    public init(at: Date, formulationID: String) {
        self.at = at
        self.formulationID = formulationID
    }

    enum CodingKeys: String, CodingKey {
        case at
        case formulationID = "formulation_id"
    }
}

/// `TaskCounts`: open tasks per list, for the same filters (ignoring state, cursor and limit).
public struct TaskCountsDTO: Codable, Hashable, Sendable {
    public var inbox: Int
    public var next: Int
    public var waiting: Int
    public var someday: Int

    public init(inbox: Int = 0, next: Int = 0, waiting: Int = 0, someday: Int = 0) {
        self.inbox = inbox
        self.next = next
        self.waiting = waiting
        self.someday = someday
    }

    public subscript(list: OpenList) -> Int {
        switch list {
        case .inbox: inbox
        case .next: next
        case .waiting: waiting
        case .someday: someday
        }
    }
}

/// `TaskListResponse`, one page of `GET /tasks`.
public struct TaskPageDTO: Codable, Hashable, Sendable {
    public var items: [TaskDTO]
    public var nextCursor: String?
    public var hasMore: Bool
    public var countsByState: TaskCountsDTO

    public init(
        items: [TaskDTO], nextCursor: String? = nil, hasMore: Bool = false,
        countsByState: TaskCountsDTO = TaskCountsDTO()
    ) {
        self.items = items
        self.nextCursor = nextCursor
        self.hasMore = hasMore
        self.countsByState = countsByState
    }

    enum CodingKeys: String, CodingKey {
        case items
        case nextCursor = "next_cursor"
        case hasMore = "has_more"
        case countsByState = "counts_by_state"
    }
}
