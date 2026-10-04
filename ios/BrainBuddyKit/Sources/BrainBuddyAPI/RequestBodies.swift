import BrainBuddyCore
import Foundation

// Request bodies. Every backend request model is `extra="forbid"`, so these
// encode exactly the documented keys and nothing else.
//
// The server fingerprints a mutation for idempotency from the parsed body
// *and the set of keys that were present* (`app/utils/idempotency.py`), so an
// explicit `"priority": "none"` and an omitted `priority` are different
// requests under one key. Each body therefore has a single canonical
// encoding: optional create fields are omitted when nil, `FieldChange`
// `.unchanged` is omitted, `.clear` is `null`, and `.set` is the value.

/// `POST /tasks` (`TaskCreateRequest`). `title`, `state`, `tag_ids` and
/// `priority` are always sent; `details`, `project_id`, `due_date` and
/// `waiting_for` only when non-nil. `source_capture_ids` / `context_ids` are
/// never sent.
public struct TaskCreateBody: Encodable, Hashable, Sendable {
    public var title: String
    public var details: String?
    public var state: OpenList
    /// Server id of an active project.
    public var projectID: String?
    /// Server ids of active tags, without duplicates.
    public var tagIDs: [String]
    public var dueDate: CalendarDay?
    public var priority: TaskPriority
    /// Required (non-blank) when `state` is `.waiting`; the server ignores it otherwise.
    public var waitingFor: String?

    public init(
        title: String, details: String? = nil, state: OpenList, projectID: String? = nil, tagIDs: [String] = [],
        dueDate: CalendarDay? = nil, priority: TaskPriority = .none, waitingFor: String? = nil
    ) {
        self.title = title
        self.details = details
        self.state = state
        self.projectID = projectID
        self.tagIDs = tagIDs
        self.dueDate = dueDate
        self.priority = priority
        self.waitingFor = waitingFor
    }

    /// Builds the body for a queued `createTask`, mapping client ids to server
    /// ids. `waitingFor` is sent only when the list is Waiting.
    public init(
        _ command: GTDCommand.CreateTask,
        projectServerID: (ProjectID) throws -> String,
        tagServerID: (TagID) throws -> String
    ) rethrows {
        self.init(
            title: command.title, details: command.details, state: command.list,
            projectID: try command.projectID.map(projectServerID), tagIDs: try command.tagIDs.map(tagServerID),
            dueDate: command.dueDate, priority: command.priority,
            waitingFor: command.list == .waiting ? command.waitingFor : nil
        )
    }

    enum CodingKeys: String, CodingKey {
        case title, details, state, priority
        case projectID = "project_id"
        case tagIDs = "tag_ids"
        case dueDate = "due_date"
        case waitingFor = "waiting_for"
    }

    public func encode(to encoder: Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        try values.encode(title, forKey: .title)
        try values.encodeIfPresent(details, forKey: .details)
        try values.encode(state, forKey: .state)
        try values.encodeIfPresent(projectID, forKey: .projectID)
        try values.encode(tagIDs, forKey: .tagIDs)
        try values.encodeIfPresent(dueDate, forKey: .dueDate)
        try values.encode(priority, forKey: .priority)
        try values.encodeIfPresent(waitingFor, forKey: .waitingFor)
    }
}

/// `PATCH /tasks/{id}` (`TaskUpdateRequest`). Omitted and `null` differ:
///
/// | Field | `.unchanged` | `.clear` (`null`) | `.set` |
/// |---|---|---|---|
/// | `title` | kept | 400 "Task title cannot be null." | renamed |
/// | `details`, `project_id`, `due_date` | kept | cleared | set |
/// | `tag_ids` | kept | same as `[]` (a different fingerprint) | replaced |
/// | `priority` | kept | 400 "Task priority cannot be null." | set |
/// | `waiting_for` | kept | 400 (Waiting needs a value) | set; 400 unless the task is Waiting |
public struct TaskUpdateBody: Encodable, Hashable, Sendable {
    public var expectedRevision: Int
    public var title: FieldChange<String>
    public var details: FieldChange<String>
    /// Server project id.
    public var projectID: FieldChange<String>
    /// Server tag ids.
    public var tagIDs: FieldChange<[String]>
    public var dueDate: FieldChange<CalendarDay>
    public var priority: FieldChange<TaskPriority>
    public var waitingFor: FieldChange<String>

    public init(
        expectedRevision: Int, title: FieldChange<String> = .unchanged, details: FieldChange<String> = .unchanged,
        projectID: FieldChange<String> = .unchanged, tagIDs: FieldChange<[String]> = .unchanged,
        dueDate: FieldChange<CalendarDay> = .unchanged, priority: FieldChange<TaskPriority> = .unchanged,
        waitingFor: FieldChange<String> = .unchanged
    ) {
        self.expectedRevision = expectedRevision
        self.title = title
        self.details = details
        self.projectID = projectID
        self.tagIDs = tagIDs
        self.dueDate = dueDate
        self.priority = priority
        self.waitingFor = waitingFor
    }

    /// Converts Core's `TaskChanges` (client ids) into a PATCH body (server
    /// ids). The resolvers run only for ids that are sent; a resolver that
    /// throws (for example "project not synced yet") aborts the conversion.
    public init(
        changes: TaskChanges, expectedRevision: Int,
        projectServerID: (ProjectID) throws -> String,
        tagServerID: (TagID) throws -> String
    ) rethrows {
        self.init(
            expectedRevision: expectedRevision, title: changes.title, details: changes.details,
            projectID: try changes.projectID.mapValue(projectServerID),
            tagIDs: try changes.tagIDs.mapValue { try $0.map(tagServerID) },
            dueDate: changes.dueDate, priority: changes.priority, waitingFor: changes.waitingFor
        )
    }

    /// False when only `expected_revision` would be sent.
    public var hasChanges: Bool {
        title.isChanged || details.isChanged || projectID.isChanged || tagIDs.isChanged || dueDate.isChanged
            || priority.isChanged || waitingFor.isChanged
    }

    enum CodingKeys: String, CodingKey {
        case title, details, priority
        case expectedRevision = "expected_revision"
        case projectID = "project_id"
        case tagIDs = "tag_ids"
        case dueDate = "due_date"
        case waitingFor = "waiting_for"
    }

    public func encode(to encoder: Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        try values.encode(expectedRevision, forKey: .expectedRevision)
        try values.encodeChange(title, forKey: .title)
        try values.encodeChange(details, forKey: .details)
        try values.encodeChange(projectID, forKey: .projectID)
        try values.encodeChange(tagIDs, forKey: .tagIDs)
        try values.encodeChange(dueDate, forKey: .dueDate)
        try values.encodeChange(priority, forKey: .priority)
        try values.encodeChange(waitingFor, forKey: .waitingFor)
    }
}

/// `POST /tasks/{id}/transitions` (`TaskTransitionRequest`). `to_state` and
/// `waiting_for` are omitted when nil.
public struct TaskTransitionBody: Encodable, Hashable, Sendable {
    public var action: TaskTransitionAction
    /// Required for `move` (a different open list) and `reopen`.
    public var toState: OpenList?
    /// Required (non-blank) when `toState` is `.waiting`.
    public var waitingFor: String?
    public var expectedRevision: Int

    public init(
        action: TaskTransitionAction, toState: OpenList? = nil, waitingFor: String? = nil, expectedRevision: Int
    ) {
        self.action = action
        self.toState = toState
        self.waitingFor = waitingFor
        self.expectedRevision = expectedRevision
    }

    /// Builds the body for a queued `transitionTask` in its canonical form:
    /// `complete` / `cancel` send neither `to_state` nor `waiting_for`;
    /// `move` / `reopen` send `to_state`, and `waiting_for` only into Waiting.
    public init(_ command: GTDCommand.TransitionTask, expectedRevision: Int) {
        switch command.action {
        case .complete, .cancel:
            self.init(action: command.action, expectedRevision: expectedRevision)
        case .move, .reopen:
            self.init(
                action: command.action, toState: command.toList,
                waitingFor: command.toList == .waiting ? command.waitingFor : nil, expectedRevision: expectedRevision
            )
        }
    }

    enum CodingKeys: String, CodingKey {
        case action
        case toState = "to_state"
        case waitingFor = "waiting_for"
        case expectedRevision = "expected_revision"
    }

    public func encode(to encoder: Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        try values.encode(action, forKey: .action)
        try values.encodeIfPresent(toState, forKey: .toState)
        try values.encodeIfPresent(waitingFor, forKey: .waitingFor)
        try values.encode(expectedRevision, forKey: .expectedRevision)
    }
}

// MARK: - Bodies behind the parameter-style methods

struct CredentialsBody: Encodable {
    var email: String
    var password: String
}

struct SignupBody: Encodable {
    var email: String
    var password: String
    var inviteCode: String

    enum CodingKeys: String, CodingKey {
        case email, password
        case inviteCode = "invite_code"
    }
}

/// `ProjectCreateRequest`: `color` omitted when nil.
struct ProjectCreateBody: Encodable {
    var name: String
    var color: String?

    func encode(to encoder: Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        try values.encode(name, forKey: .name)
        try values.encodeIfPresent(color, forKey: .color)
    }

    enum CodingKeys: String, CodingKey { case name, color }
}

/// `ProjectUpdateRequest`: `name` omitted when nil; `color` `.clear` is `null` (clears it).
struct ProjectUpdateBody: Encodable {
    var name: String?
    var color: FieldChange<String>
    var expectedRevision: Int

    enum CodingKeys: String, CodingKey {
        case name, color
        case expectedRevision = "expected_revision"
    }

    func encode(to encoder: Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        try values.encodeIfPresent(name, forKey: .name)
        try values.encodeChange(color, forKey: .color)
        try values.encode(expectedRevision, forKey: .expectedRevision)
    }
}

/// `ExpectedRevisionRequest` (project archive).
struct ExpectedRevisionBody: Encodable {
    var expectedRevision: Int
    enum CodingKeys: String, CodingKey { case expectedRevision = "expected_revision" }
}

/// `TagCreateRequest`, `TaskSubtaskCreateRequest`.
struct NameBody: Encodable { var name: String }
struct TitleBody: Encodable { var title: String }

/// `TagUpdateRequest`.
struct NameRevisionBody: Encodable {
    var name: String
    var expectedRevision: Int
    enum CodingKeys: String, CodingKey {
        case name
        case expectedRevision = "expected_revision"
    }
}

/// `TaskSubtaskUpdateRequest`.
struct TitleRevisionBody: Encodable {
    var title: String
    var expectedRevision: Int
    enum CodingKeys: String, CodingKey {
        case title
        case expectedRevision = "expected_revision"
    }
}

/// `TaskSubtaskTransitionRequest`.
struct SubtaskTransitionBody: Encodable {
    var action: SubtaskTransitionAction
    var expectedRevision: Int
    enum CodingKeys: String, CodingKey {
        case action
        case expectedRevision = "expected_revision"
    }
}

/// `TaskCommentCreateRequest`.
struct CommentBody: Encodable { var body: String }

/// `TaskCommentUpdateRequest`.
struct CommentRevisionBody: Encodable {
    var body: String
    var expectedRevision: Int
    enum CodingKeys: String, CodingKey {
        case body
        case expectedRevision = "expected_revision"
    }
}

// MARK: - FieldChange helpers

extension FieldChange {
    /// Maps a `.set` value, keeping `.unchanged` / `.clear`.
    public func mapValue<Other: Hashable & Sendable & Codable>(
        _ transform: (Value) throws -> Other
    ) rethrows -> FieldChange<Other> {
        switch self {
        case .unchanged: .unchanged
        case .clear: .clear
        case .set(let value): .set(try transform(value))
        }
    }
}

extension KeyedEncodingContainer {
    /// `.unchanged` omits the key, `.clear` writes `null`, `.set` writes the value.
    mutating func encodeChange<Value>(_ change: FieldChange<Value>, forKey key: Key) throws {
        switch change {
        case .unchanged: break
        case .clear: try encodeNil(forKey: key)
        case .set(let value): try encode(value, forKey: key)
        }
    }
}
