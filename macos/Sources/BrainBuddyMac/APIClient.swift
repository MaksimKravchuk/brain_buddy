import Foundation

enum TaskList: String, CaseIterable, Identifiable, Codable {
    case inbox, next, waiting, someday

    var id: String { rawValue }

    var title: String {
        switch self {
        case .inbox: "Inbox"
        case .next: "Next actions"
        case .waiting: "Waiting for"
        case .someday: "Someday"
        }
    }

    var symbol: String {
        switch self {
        case .inbox: "tray"
        case .next: "checklist"
        case .waiting: "clock"
        case .someday: "archivebox"
        }
    }
}

struct Account: Decodable {
    let id: String
    let email: String
    let display_name: String?
}

enum TaskPriority: String, Codable, CaseIterable {
    case none, low, medium, high
}

enum PriorityFilter: String, CaseIterable, Identifiable {
    case all, high, medium, low, none

    var id: String { rawValue }
    var title: String { rawValue.capitalized }
    var priority: TaskPriority? { self == .all ? nil : TaskPriority(rawValue: rawValue) }
}

struct BrainBuddySubtask: Codable, Identifiable {
    let id: String
    let title: String
    let state: String
    let order_key: Int
    let revision: Int
}

struct BrainBuddyComment: Codable, Identifiable {
    let id: String
    let body: String
    let actor_id: String
    let created_at: String
    let edited_at: String?
    let revision: Int
}

enum SubtaskTransitionAction: String, Encodable {
    case complete, reopen, cancel
}

enum TaskSort: String, CaseIterable, Identifiable {
    case manual, due, priority, title

    var id: String { rawValue }
    var title: String { rawValue.capitalized }
}

struct BrainBuddyTask: Codable, Identifiable {
    let id: String
    let title: String
    let details: String?
    let state: String
    let last_open_state: TaskList?
    let revision: Int
    let project_id: String?
    let tag_ids: [String]
    /// Calendar date in YYYY-MM-DD form; no time-zone conversion is applied.
    let due_date: String?
    let priority: TaskPriority
    let waiting_for: String?
    let waiting_since: String?
    let completed_at: String?
    let cancelled_at: String?
    let subtasks: [BrainBuddySubtask]
    let comments: [BrainBuddyComment]

    init(
        id: String, title: String, details: String?, state: String, revision: Int,
        project_id: String? = nil, tag_ids: [String] = [], due_date: String? = nil,
        priority: TaskPriority = .none, waiting_for: String? = nil, waiting_since: String? = nil,
        last_open_state: TaskList? = nil, completed_at: String? = nil, cancelled_at: String? = nil,
        subtasks: [BrainBuddySubtask] = [], comments: [BrainBuddyComment] = []
    ) {
        self.id = id
        self.title = title
        self.details = details
        self.state = state
        self.last_open_state = last_open_state
        self.revision = revision
        self.project_id = project_id
        self.tag_ids = tag_ids
        self.due_date = due_date
        self.priority = priority
        self.waiting_for = waiting_for
        self.waiting_since = waiting_since
        self.completed_at = completed_at
        self.cancelled_at = cancelled_at
        self.subtasks = subtasks
        self.comments = comments
    }

    private enum CodingKeys: String, CodingKey {
        case id, title, details, state, last_open_state, revision, project_id, tag_ids, due_date, priority, waiting_for, waiting_since,
             completed_at, cancelled_at,
             subtasks, comments
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        self.init(
            id: try values.decode(String.self, forKey: .id),
            title: try values.decode(String.self, forKey: .title),
            details: try values.decodeIfPresent(String.self, forKey: .details),
            state: try values.decode(String.self, forKey: .state),
            revision: try values.decode(Int.self, forKey: .revision),
            project_id: try values.decodeIfPresent(String.self, forKey: .project_id),
            tag_ids: try values.decodeIfPresent([String].self, forKey: .tag_ids) ?? [],
            due_date: try values.decodeIfPresent(String.self, forKey: .due_date),
            priority: try values.decodeIfPresent(TaskPriority.self, forKey: .priority) ?? .none,
            waiting_for: try values.decodeIfPresent(String.self, forKey: .waiting_for),
            waiting_since: try values.decodeIfPresent(String.self, forKey: .waiting_since),
            last_open_state: try values.decodeIfPresent(TaskList.self, forKey: .last_open_state),
            completed_at: try values.decodeIfPresent(String.self, forKey: .completed_at),
            cancelled_at: try values.decodeIfPresent(String.self, forKey: .cancelled_at),
            subtasks: try values.decodeIfPresent([BrainBuddySubtask].self, forKey: .subtasks) ?? [],
            comments: try values.decodeIfPresent([BrainBuddyComment].self, forKey: .comments) ?? []
        )
    }
}

struct TaskCounts: Decodable {
    let inbox: Int
    let next: Int
    let waiting: Int
    let someday: Int

    var total: Int { inbox + next + waiting + someday }

    func count(for list: TaskList) -> Int {
        switch list {
        case .inbox: inbox
        case .next: next
        case .waiting: waiting
        case .someday: someday
        }
    }
}

struct TaskPage: Decodable {
    let items: [BrainBuddyTask]
    let next_cursor: String?
    let has_more: Bool
    let counts_by_state: TaskCounts?
}

struct BrainBuddyProject: Codable, Identifiable {
    let id: String
    let name: String
    let color: String?
    let state: String
    let revision: Int
    let open_task_count: Int
}

struct BrainBuddyTag: Codable, Identifiable {
    let id: String
    let name: String
    let state: String
    let revision: Int
    let open_task_count: Int
}

struct TaskQuery: Equatable {
    var state: TaskList? = nil
    var terminalState: HistoryState? = nil
    var projectID: String? = nil
    var tagID: String? = nil
    var unassignedProject: Bool? = nil
    var includeCompleted: Bool? = nil
    var includeCancelled: Bool? = nil
    var q: String? = nil
    var dueBefore: String? = nil
    var dueOn: String? = nil
    var dueAfter: String? = nil
    var priority: TaskPriority? = nil
    var sort: TaskSort? = nil

    init(
        state: TaskList? = nil, projectID: String? = nil, tagID: String? = nil,
        unassignedProject: Bool? = nil, includeCompleted: Bool? = nil,
        includeCancelled: Bool? = nil, q: String? = nil, dueBefore: String? = nil,
        dueOn: String? = nil, dueAfter: String? = nil,
        priority: TaskPriority? = nil, sort: TaskSort? = nil,
        terminalState: HistoryState? = nil
    ) {
        self.state = state
        self.terminalState = terminalState
        self.projectID = projectID
        self.tagID = tagID
        self.unassignedProject = unassignedProject
        self.includeCompleted = includeCompleted
        self.includeCancelled = includeCancelled
        self.q = q
        self.dueBefore = dueBefore
        self.dueOn = dueOn
        self.dueAfter = dueAfter
        self.priority = priority
        self.sort = sort
    }
}

enum FieldChange<Value: Encodable> {
    case unchanged
    case clear
    case set(Value)
}

struct TaskChanges {
    var title: FieldChange<String> = .unchanged
    var details: FieldChange<String> = .unchanged
    var projectID: FieldChange<String> = .unchanged
    var tagIDs: FieldChange<[String]> = .unchanged
    var dueDate: FieldChange<String> = .unchanged
    var priority: FieldChange<TaskPriority> = .unchanged
    var waitingFor: FieldChange<String> = .unchanged

    init(
        title: FieldChange<String> = .unchanged, details: FieldChange<String> = .unchanged,
        projectID: FieldChange<String> = .unchanged, tagIDs: FieldChange<[String]> = .unchanged,
        dueDate: FieldChange<String> = .unchanged,
        priority: FieldChange<TaskPriority> = .unchanged,
        waitingFor: FieldChange<String> = .unchanged
    ) {
        self.title = title
        self.details = details
        self.projectID = projectID
        self.tagIDs = tagIDs
        self.dueDate = dueDate
        self.priority = priority
        self.waitingFor = waitingFor
    }
}

enum TaskTransitionAction: String {
    case move, complete, reopen, cancel
}

enum ClassificationRef: Encodable {
    case id(String)
    case name(String)

    private enum CodingKeys: String, CodingKey { case id, name }

    func encode(to encoder: Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        switch self {
        case .id(let id): try values.encode(id, forKey: .id)
        case .name(let name): try values.encode(name, forKey: .name)
        }
    }
}

struct SmartAddCreated: Codable {
    let project_id: String?
    let tag_ids: [String]
}

struct SmartAddResult: Codable {
    let task: BrainBuddyTask
    let project: BrainBuddyProject?
    let tags: [BrainBuddyTag]
    let created: SmartAddCreated
}

private struct LoginBody: Encodable {
    let email: String
    let password: String
}

private struct CreateTaskBody: Encodable {
    let title: String
    let state: String
    let waiting_for: String?
}

struct SmartAddTaskBody: Encodable {
    let title: String
    let details: String?
    let state: String
    let waiting_for: String?
    let due_date: String?
    let priority: TaskPriority
    let project: ClassificationRef?
    let tags: [ClassificationRef]
}

struct CreateProjectBody: Encodable {
    let name: String
}

struct CreateTagBody: Encodable {
    let name: String
}

struct RenameCollectionBody: Encodable {
    let name: String
    let expected_revision: Int
}

struct TaskUpdateBody: Encodable {
    let expected_revision: Int
    let changes: TaskChanges

    private enum CodingKeys: String, CodingKey {
        case expected_revision, title, details, project_id, tag_ids, due_date, priority, waiting_for
    }

    func encode(to encoder: Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        try values.encode(expected_revision, forKey: .expected_revision)
        try values.encodeChange(changes.title, forKey: .title)
        try values.encodeChange(changes.details, forKey: .details)
        try values.encodeChange(changes.projectID, forKey: .project_id)
        try values.encodeChange(changes.tagIDs, forKey: .tag_ids)
        try values.encodeChange(changes.dueDate, forKey: .due_date)
        try values.encodeChange(changes.priority, forKey: .priority)
        try values.encodeChange(changes.waitingFor, forKey: .waiting_for)
    }
}

private extension KeyedEncodingContainer {
    mutating func encodeChange<Value: Encodable>(
        _ change: FieldChange<Value>, forKey key: Key
    ) throws {
        switch change {
        case .unchanged: break
        case .clear: try encodeNil(forKey: key)
        case .set(let value): try encode(value, forKey: key)
        }
    }
}

struct TaskTransitionBody: Encodable {
    let action: String
    let to_state: String?
    let waiting_for: String?
    let expected_revision: Int
}

struct SubtaskCreateBody: Encodable {
    let title: String
}

struct SubtaskUpdateBody: Encodable {
    let title: String
    let expected_revision: Int
}

struct SubtaskTransitionBody: Encodable {
    let action: SubtaskTransitionAction
    let expected_revision: Int
}

struct CommentCreateBody: Encodable {
    let body: String
}

struct CommentUpdateBody: Encodable {
    let body: String
    let expected_revision: Int
}

private struct ErrorBody: Decodable {
    let message: String?
    let reference_id: String?
}

struct APIError: LocalizedError {
    let message: String
    var statusCode: Int? = nil
    var referenceID: String? = nil

    var errorDescription: String? {
        guard let referenceID, !referenceID.isEmpty else { return message }
        return "\(message) Reference ID: \(referenceID)."
    }
}

final class APIClient {
    private let session: URLSession
    private(set) var baseURL: URL

    init(baseURL: URL, session: URLSession? = nil) {
        self.baseURL = baseURL
        if let session {
            self.session = session
        } else {
            let configuration = URLSessionConfiguration.default
            configuration.httpCookieStorage = .shared
            configuration.httpShouldSetCookies = true
            self.session = URLSession(configuration: configuration)
        }
    }

    func setBaseURL(_ raw: String) throws {
        guard let url = URL(string: raw.trimmingCharacters(in: .whitespacesAndNewlines)),
              let host = url.host,
              (url.scheme == "https" || (url.scheme == "http" && ["localhost", "127.0.0.1"].contains(host)))
        else {
            throw APIError(message: "Use an HTTPS API URL, or HTTP on localhost.")
        }
        baseURL = url
    }

    func me() async throws -> Account {
        try await request("/auth/me")
    }

    func login(email: String, password: String) async throws -> Account {
        try await request("/auth/login", method: "POST", body: LoginBody(email: email, password: password))
    }

    func logout() async throws {
        let _: EmptyResponse = try await request("/auth/logout", method: "POST")
    }

    func listTasks(state: TaskList, cursor: String? = nil) async throws -> TaskPage {
        try await listTasks(
            query: TaskQuery(state: state, unassignedProject: state == .inbox),
            cursor: cursor
        )
    }

    func listTasks(query: TaskQuery, cursor: String? = nil) async throws -> TaskPage {
        var components = URLComponents()
        components.path = "/tasks"
        var items = [URLQueryItem(name: "limit", value: "100")]
        func append(_ name: String, _ value: String?) {
            if let value { items.append(URLQueryItem(name: name, value: value)) }
        }
        func boolean(_ value: Bool?) -> String? {
            value.map { $0 ? "true" : "false" }
        }
        append("state", query.terminalState?.rawValue ?? query.state?.rawValue)
        append("project_id", query.projectID)
        append("tag_id", query.tagID)
        append("unassigned_project", boolean(query.unassignedProject))
        append("include_completed", boolean(query.includeCompleted))
        append("include_cancelled", boolean(query.includeCancelled))
        append("q", query.q)
        append("due_before", query.dueBefore)
        append("due_on", query.dueOn)
        append("due_after", query.dueAfter)
        append("priority", query.priority?.rawValue)
        append("sort", query.sort?.rawValue)
        append("cursor", cursor)
        components.queryItems = items
        return try await request(components.string ?? "/tasks")
    }

    func getTask(_ id: String) async throws -> BrainBuddyTask {
        try await request("/tasks/\(id)")
    }

    func createSubtask(
        taskID: String, title: String, idempotencyKey: UUID
    ) async throws -> BrainBuddySubtask {
        try await request(
            "/tasks/\(taskID)/subtasks", method: "POST",
            body: SubtaskCreateBody(title: title), idempotencyKey: idempotencyKey
        )
    }

    func updateSubtask(
        taskID: String, subtask: BrainBuddySubtask, title: String, idempotencyKey: UUID
    ) async throws -> BrainBuddySubtask {
        try await request(
            "/tasks/\(taskID)/subtasks/\(subtask.id)", method: "PATCH",
            body: SubtaskUpdateBody(title: title, expected_revision: subtask.revision),
            idempotencyKey: idempotencyKey
        )
    }

    func transitionSubtask(
        taskID: String, subtask: BrainBuddySubtask, action: SubtaskTransitionAction,
        idempotencyKey: UUID
    ) async throws -> BrainBuddySubtask {
        try await request(
            "/tasks/\(taskID)/subtasks/\(subtask.id)/transitions", method: "POST",
            body: SubtaskTransitionBody(
                action: action,
                expected_revision: subtask.revision
            ),
            idempotencyKey: idempotencyKey
        )
    }

    func createComment(
        taskID: String, body: String, idempotencyKey: UUID
    ) async throws -> BrainBuddyComment {
        try await request(
            "/tasks/\(taskID)/comments", method: "POST",
            body: CommentCreateBody(body: body), idempotencyKey: idempotencyKey
        )
    }

    func updateComment(
        taskID: String, comment: BrainBuddyComment, body: String, idempotencyKey: UUID
    ) async throws -> BrainBuddyComment {
        try await request(
            "/tasks/\(taskID)/comments/\(comment.id)", method: "PATCH",
            body: CommentUpdateBody(body: body, expected_revision: comment.revision),
            idempotencyKey: idempotencyKey
        )
    }

    func listProjects() async throws -> [BrainBuddyProject] {
        try await request("/projects")
    }

    func listTags() async throws -> [BrainBuddyTag] {
        try await request("/tags")
    }

    func createProject(name: String, idempotencyKey: UUID) async throws -> BrainBuddyProject {
        try await request(
            "/projects", method: "POST", body: CreateProjectBody(name: name),
            idempotencyKey: idempotencyKey
        )
    }

    func createTag(name: String, idempotencyKey: UUID) async throws -> BrainBuddyTag {
        try await request(
            "/tags", method: "POST", body: CreateTagBody(name: name),
            idempotencyKey: idempotencyKey
        )
    }

    func renameProject(
        _ project: BrainBuddyProject, to name: String, idempotencyKey: UUID
    ) async throws -> BrainBuddyProject {
        try await request(
            "/projects/\(project.id)", method: "PATCH",
            body: RenameCollectionBody(name: name, expected_revision: project.revision),
            idempotencyKey: idempotencyKey
        )
    }

    func renameTag(
        _ tag: BrainBuddyTag, to name: String, idempotencyKey: UUID
    ) async throws -> BrainBuddyTag {
        try await request(
            "/tags/\(tag.id)", method: "PATCH",
            body: RenameCollectionBody(name: name, expected_revision: tag.revision),
            idempotencyKey: idempotencyKey
        )
    }

    func deleteTag(_ tag: BrainBuddyTag, idempotencyKey: UUID) async throws -> BrainBuddyTag {
        try await request(
            "/tags/\(tag.id)?expected_revision=\(tag.revision)", method: "DELETE",
            idempotencyKey: idempotencyKey
        )
    }

    func createTask(
        title: String,
        state: TaskList,
        waitingFor: String?,
        idempotencyKey: UUID
    ) async throws -> BrainBuddyTask {
        let waitingFor = waitingFor?.trimmingCharacters(in: .whitespacesAndNewlines)
        if state == .waiting && (waitingFor?.isEmpty ?? true) {
            throw APIError(message: "Waiting tasks require who or what you are waiting for.")
        }
        if state != .waiting && !(waitingFor?.isEmpty ?? true) {
            throw APIError(message: "Only Waiting tasks may include waiting_for.")
        }
        return try await request(
            "/tasks",
            method: "POST",
            body: CreateTaskBody(
                title: title,
                state: state.rawValue,
                waiting_for: state == .waiting ? waitingFor : nil
            ),
            idempotencyKey: idempotencyKey
        )
    }

    func smartAddTask(
        title: String, details: String? = nil, state: TaskList,
        waitingFor: String? = nil, dueDate: String? = nil,
        priority: TaskPriority = .none, project: ClassificationRef? = nil,
        tags: [ClassificationRef] = [], idempotencyKey: UUID
    ) async throws -> SmartAddResult {
        let waitingFor = waitingFor?.trimmingCharacters(in: .whitespacesAndNewlines)
        if state == .waiting && (waitingFor?.isEmpty ?? true) {
            throw APIError(message: "Waiting tasks require who or what you are waiting for.")
        }
        if state != .waiting && !(waitingFor?.isEmpty ?? true) {
            throw APIError(message: "Only Waiting tasks may include waiting_for.")
        }
        return try await request(
            "/tasks/smart-add", method: "POST",
            body: SmartAddTaskBody(
                title: title, details: details, state: state.rawValue,
                waiting_for: state == .waiting ? waitingFor : nil,
                due_date: dueDate, priority: priority, project: project, tags: tags
            ),
            idempotencyKey: idempotencyKey
        )
    }

    func completeTask(_ task: BrainBuddyTask, idempotencyKey: UUID) async throws -> BrainBuddyTask {
        try await transitionTask(task, action: .complete, idempotencyKey: idempotencyKey)
    }

    func updateTask(
        _ task: BrainBuddyTask, changes: TaskChanges, idempotencyKey: UUID
    ) async throws -> BrainBuddyTask {
        try await request(
            "/tasks/\(task.id)", method: "PATCH",
            body: TaskUpdateBody(expected_revision: task.revision, changes: changes),
            idempotencyKey: idempotencyKey
        )
    }

    func transitionTask(
        _ task: BrainBuddyTask, action: TaskTransitionAction,
        toState: TaskList? = nil, waitingFor: String? = nil,
        idempotencyKey: UUID
    ) async throws -> BrainBuddyTask {
        if (action == .move || action == .reopen) && toState == nil {
            throw APIError(message: "Choose an open destination.")
        }
        let waitingFor = waitingFor?.trimmingCharacters(in: .whitespacesAndNewlines)
        if toState == .waiting && (waitingFor?.isEmpty ?? true) {
            throw APIError(message: "Waiting tasks require who or what you are waiting for.")
        }
        return try await request(
            "/tasks/\(task.id)/transitions",
            method: "POST",
            body: TaskTransitionBody(
                action: action.rawValue,
                to_state: toState?.rawValue,
                waiting_for: toState == .waiting ? waitingFor : nil,
                expected_revision: task.revision
            ),
            idempotencyKey: idempotencyKey
        )
    }

    private struct EmptyResponse: Decodable {}

    private func request<Response: Decodable>(
        _ path: String,
        method: String = "GET",
        body: (any Encodable)? = nil,
        idempotencyKey: UUID? = nil
    ) async throws -> Response {
        let root = baseURL.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard let url = URL(string: root + path) else { throw APIError(message: "Invalid API URL.") }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = 30
        request.httpShouldHandleCookies = true
        if let body {
            request.httpBody = try JSONEncoder().encode(AnyEncodable(body))
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        if let idempotencyKey {
            request.setValue(idempotencyKey.uuidString, forHTTPHeaderField: "Idempotency-Key")
        }
        let (data, rawResponse) = try await session.data(for: request)
        guard let response = rawResponse as? HTTPURLResponse else {
            throw APIError(message: "No HTTP response.")
        }
        if response.statusCode == 204 { return try JSONDecoder().decode(Response.self, from: Data("{}".utf8)) }
        guard (200..<300).contains(response.statusCode) else {
            let server = try? JSONDecoder().decode(ErrorBody.self, from: data)
            let referenceID = server?.reference_id ?? response.value(forHTTPHeaderField: "X-Correlation-ID")
            throw APIError(
                message: server?.message ?? "Request failed (HTTP \(response.statusCode)).",
                statusCode: response.statusCode,
                referenceID: referenceID
            )
        }
        return try JSONDecoder().decode(Response.self, from: data)
    }
}

private struct AnyEncodable: Encodable {
    let encodeBody: (Encoder) throws -> Void

    init(_ body: any Encodable) { encodeBody = body.encode }
    func encode(to encoder: Encoder) throws { try encodeBody(encoder) }
}
