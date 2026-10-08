import BrainBuddyCore
import Foundation

/// Typed client for the Brain Buddy REST API: one async method per endpoint,
/// no retries and no sync logic (that is `BrainBuddySync`'s job).
///
/// - Every request carries `X-Client: <identity>/<version>` (`brainbuddy-ios` unless
///   the host passes another `ClientIdentity`) and a fresh
///   lowercase-UUID `X-Correlation-ID` (the server echoes it as `reference_id`).
/// - Mutations take the operation's `Idempotency-Key`; resend the same key and
///   the same body to retry safely (the server keeps keys for 24 hours).
/// - The session cookie lives in the `SessionTokenStore`, never in a cookie jar:
///   it is sent as `Cookie: brainbuddy_session=…`, captured from `Set-Cookie`
///   (login/signup), removed when the server deletes it (logout) and when a
///   request that carried it gets a 401.
/// - Ids in paths and bodies are server ids; path segments and query values
///   are percent-encoded (RFC 3986 unreserved characters only, so `+` is `%2B`).
public final class BrainBuddyAPIClient: Sendable {
    /// API base including `/api`, for example `https://brain-buddy-frontend.fly.dev/api`.
    public let baseURL: URL
    public let clientVersion: String
    public let identity: ClientIdentity
    private let transport: any HTTPTransport
    private let tokenStore: any SessionTokenStore
    private let makeCorrelationID: @Sendable () -> UUID

    public init(
        baseURL: URL = BrainBuddyAPI.defaultServerURL,
        transport: any HTTPTransport = URLSessionTransport(),
        tokenStore: any SessionTokenStore,
        clientVersion: String? = nil,
        identity: ClientIdentity = .iOS,
        correlationID: @escaping @Sendable () -> UUID = { UUID() }
    ) {
        self.baseURL = baseURL
        self.transport = transport
        self.tokenStore = tokenStore
        self.clientVersion = clientVersion ?? identity.version
        self.identity = ClientIdentity(name: identity.name, version: self.clientVersion)
        self.makeCorrelationID = correlationID
    }

    // MARK: - Account and session

    /// `POST /auth/login` → 200 `MeResponse`; stores the session cookie.
    /// Wrong credentials are `.unauthorized` ("Invalid email or password.");
    /// too many attempts are `.rateLimited`.
    public func login(email: String, password: String) async throws(APIError) -> MeDTO {
        try await startSession(["auth", "login"], CredentialsBody(email: email, password: password))
    }

    /// `POST /auth/signup` → 201 `MeResponse`; stores the session cookie.
    /// A bad invite is 400 `.rejected`; a taken email is 409 `.rejected`.
    public func signup(email: String, password: String, inviteCode: String) async throws(APIError) -> MeDTO {
        try await startSession(
            ["auth", "signup"], SignupBody(email: email, password: password, inviteCode: inviteCode)
        )
    }

    /// `POST /auth/logout` → 204. The stored token is removed whatever the
    /// outcome, so signing out always works offline; a 401 counts as success.
    public func logout() async throws(APIError) {
        defer { try? tokenStore.removeToken(for: baseURL) }
        do throws(APIError) {
            _ = try await exchange(Endpoint(.post, ["auth", "logout"]))
        } catch {
            if case .unauthorized = error.kind { return }
            throw error
        }
    }

    /// `GET /auth/me` → 200 `MeResponse`, or `.unauthorized`.
    public func me() async throws(APIError) -> MeDTO {
        try await get(["auth", "me"])
    }

    /// Whether a session token is stored for this server (no network).
    public func hasStoredSession() throws(APIError) -> Bool {
        do { return try tokenStore.token(for: baseURL) != nil } catch { throw APIError.tokenStorage(error) }
    }

    /// Forgets the stored session token without calling the server.
    public func discardStoredSession() throws(APIError) {
        do { try tokenStore.removeToken(for: baseURL) } catch { throw APIError.tokenStorage(error) }
    }

    // MARK: - Projects

    /// `GET /projects[?state=]` → the projects in that state (default `active`), sorted by name.
    /// A server older than spec 021 ignores `state` and lists the active ones.
    public func listProjects(state: ProjectListState = .active) async throws(APIError) -> [ProjectDTO] {
        try await get(["projects"], query: state == .active ? [] : [(name: "state", value: state.rawValue)])
    }

    /// `GET /projects/{id}` → the project in any state (active or archived).
    public func getProject(id: String) async throws(APIError) -> ProjectDTO {
        try await get(["projects", id])
    }

    /// `POST /projects {name, color?, desired_outcome?}` → 201. Nil fields are omitted.
    /// A taken name is `.duplicateName(resource: "Project", name:)`.
    public func createProject(
        name: String, color: String? = nil, desiredOutcome: String? = nil, idempotencyKey: UUID
    ) async throws(APIError) -> ProjectDTO {
        let body = ProjectCreateBody(name: name, color: color, desiredOutcome: desiredOutcome)
        return try await mutate(.post, ["projects"], body, key: idempotencyKey)
    }

    /// `PATCH /projects/{id} {name?, color?, desired_outcome?, expected_revision}`. `name` is
    /// omitted when nil; `color: .clear` sends `null` and removes the colour, and so does
    /// `desiredOutcome: .clear` for the outcome.
    public func updateProject(
        id: String, name: String? = nil, color: FieldChange<String> = .unchanged,
        desiredOutcome: FieldChange<String> = .unchanged, expectedRevision: Int, idempotencyKey: UUID
    ) async throws(APIError) -> ProjectDTO {
        let body = ProjectUpdateBody(
            name: name, color: color, desiredOutcome: desiredOutcome, expectedRevision: expectedRevision)
        return try await mutate(.patch, ["projects", id], body, key: idempotencyKey)
    }

    /// `POST /projects/{id}/archive {expected_revision}`. Since ADR-0020 every task keeps its project.
    public func archiveProject(
        id: String, expectedRevision: Int, idempotencyKey: UUID
    ) async throws(APIError) -> ProjectDTO {
        let body = ExpectedRevisionBody(expectedRevision: expectedRevision)
        return try await mutate(.post, ["projects", id, "archive"], body, key: idempotencyKey)
    }

    /// `POST /projects/{id}/unarchive {expected_revision}`. A project that is active already is
    /// answered unchanged; an active project with the same name is `.duplicateName`.
    public func unarchiveProject(
        id: String, expectedRevision: Int, idempotencyKey: UUID
    ) async throws(APIError) -> ProjectDTO {
        let body = ExpectedRevisionBody(expectedRevision: expectedRevision)
        return try await mutate(.post, ["projects", id, "unarchive"], body, key: idempotencyKey)
    }

    // MARK: - Tags

    /// `GET /tags` → active tags, sorted by name.
    public func listTags() async throws(APIError) -> [TagDTO] {
        try await get(["tags"])
    }

    /// `GET /tags/{id}` → the tag in any state (active or deleted).
    public func getTag(id: String) async throws(APIError) -> TagDTO {
        try await get(["tags", id])
    }

    /// `POST /tags {name}` → 201. A taken name is `.duplicateName(resource: "Tag", name:)`.
    public func createTag(name: String, idempotencyKey: UUID) async throws(APIError) -> TagDTO {
        try await mutate(.post, ["tags"], NameBody(name: name), key: idempotencyKey)
    }

    /// `PATCH /tags/{id} {name, expected_revision}` (rename).
    public func updateTag(
        id: String, name: String, expectedRevision: Int, idempotencyKey: UUID
    ) async throws(APIError) -> TagDTO {
        let body = NameRevisionBody(name: name, expectedRevision: expectedRevision)
        return try await mutate(.patch, ["tags", id], body, key: idempotencyKey)
    }

    /// `DELETE /tags/{id}?expected_revision=N` → 200 with the tag in state
    /// `deleted`. The server also removes it from every task.
    public func deleteTag(id: String, expectedRevision: Int, idempotencyKey: UUID) async throws(APIError) -> TagDTO {
        let query = [(name: "expected_revision", value: String(expectedRevision))]
        return try decode(
            try await exchange(Endpoint(.delete, ["tags", id], query: query, idempotencyKey: idempotencyKey))
        )
    }

    // MARK: - Tasks

    /// `GET /tasks` → one page. Items carry empty `subtasks` / `comments`.
    public func listTasks(
        _ query: TaskListQuery = TaskListQuery(), cursor: String? = nil
    ) async throws(APIError) -> TaskPageDTO {
        try await get(["tasks"], query: query.queryItems(cursor: cursor))
    }

    /// Follows `next_cursor` until the last page and returns every item
    /// (for the full pull use the default `.fullPull`).
    public func listAllTasks(_ query: TaskListQuery = .fullPull) async throws(APIError) -> [TaskDTO] {
        var items: [TaskDTO] = []
        var cursor: String?
        var seenCursors = Set<String>()
        while true {
            let page = try await listTasks(query, cursor: cursor)
            items += page.items
            guard page.hasMore, let next = page.nextCursor else { return items }
            guard seenCursors.insert(next).inserted else {
                throw APIError(
                    kind: .decoding("GET /tasks returned the cursor \(next) twice."),
                    message: "Brain Buddy received a response it couldn't read.", statusCode: 200
                )
            }
            cursor = next
        }
    }

    /// `GET /tasks/{id}` → the task with its subtasks (by order) and comments (oldest first).
    public func getTask(id: String) async throws(APIError) -> TaskDTO {
        try await get(["tasks", id])
    }

    /// `POST /tasks` → 201. A missing referenced project/tag is `.notFound`
    /// naming *that* record; an inactive one is 400 `.rejected`.
    public func createTask(_ body: TaskCreateBody, idempotencyKey: UUID) async throws(APIError) -> TaskDTO {
        try await mutate(.post, ["tasks"], body, key: idempotencyKey)
    }

    /// `PATCH /tasks/{id}` with omitted-vs-null fields (see `TaskUpdateBody`).
    public func updateTask(id: String, _ body: TaskUpdateBody, idempotencyKey: UUID) async throws(APIError) -> TaskDTO {
        try await mutate(.patch, ["tasks", id], body, key: idempotencyKey)
    }

    /// `POST /tasks/{id}/transitions {action, to_state?, waiting_for?, expected_revision}`.
    public func transitionTask(
        id: String, _ body: TaskTransitionBody, idempotencyKey: UUID
    ) async throws(APIError) -> TaskDTO {
        try await mutate(.post, ["tasks", id, "transitions"], body, key: idempotencyKey)
    }

    // MARK: - Subtasks

    /// `POST /tasks/{id}/subtasks {title}` → 201. Does not bump the task's revision.
    public func createSubtask(
        taskID: String, title: String, idempotencyKey: UUID
    ) async throws(APIError) -> SubtaskDTO {
        try await mutate(.post, ["tasks", taskID, "subtasks"], TitleBody(title: title), key: idempotencyKey)
    }

    /// `PATCH /tasks/{id}/subtasks/{sid} {title, expected_revision}`.
    public func updateSubtask(
        taskID: String, subtaskID: String, title: String, expectedRevision: Int, idempotencyKey: UUID
    ) async throws(APIError) -> SubtaskDTO {
        let body = TitleRevisionBody(title: title, expectedRevision: expectedRevision)
        return try await mutate(.patch, ["tasks", taskID, "subtasks", subtaskID], body, key: idempotencyKey)
    }

    /// `POST /tasks/{id}/subtasks/{sid}/transitions {action, expected_revision}`.
    /// A transition to the current state is 400 `.rejected`.
    public func transitionSubtask(
        taskID: String, subtaskID: String, action: SubtaskTransitionAction, expectedRevision: Int,
        idempotencyKey: UUID
    ) async throws(APIError) -> SubtaskDTO {
        let body = SubtaskTransitionBody(action: action, expectedRevision: expectedRevision)
        let path = ["tasks", taskID, "subtasks", subtaskID, "transitions"]
        return try await mutate(.post, path, body, key: idempotencyKey)
    }

    // MARK: - Comments

    /// `POST /tasks/{id}/comments {body}` → 201. Does not bump the task's revision.
    public func createComment(taskID: String, body: String, idempotencyKey: UUID) async throws(APIError) -> CommentDTO {
        try await mutate(.post, ["tasks", taskID, "comments"], CommentBody(body: body), key: idempotencyKey)
    }

    /// `PATCH /tasks/{id}/comments/{cid} {body, expected_revision}`.
    public func updateComment(
        taskID: String, commentID: String, body: String, expectedRevision: Int, idempotencyKey: UUID
    ) async throws(APIError) -> CommentDTO {
        let request = CommentRevisionBody(body: body, expectedRevision: expectedRevision)
        return try await mutate(.patch, ["tasks", taskID, "comments", commentID], request, key: idempotencyKey)
    }
}

// MARK: - Request plumbing

extension BrainBuddyAPIClient {
    struct Endpoint {
        var method: HTTPMethod
        var path: [String]
        var query: [(name: String, value: String)]
        var body: Data?
        var idempotencyKey: UUID?
        /// False for login and signup, which must not carry an old session.
        var sendsSession: Bool

        init(
            _ method: HTTPMethod, _ path: [String], query: [(name: String, value: String)] = [], body: Data? = nil,
            idempotencyKey: UUID? = nil, sendsSession: Bool = true
        ) {
            self.method = method
            self.path = path
            self.query = query
            self.body = body
            self.idempotencyKey = idempotencyKey
            self.sendsSession = sendsSession
        }
    }

    struct Exchange {
        var response: HTTPResponse
        var correlationID: String
        var sessionUpdate: CookieUpdate?
    }

    func get<T: Decodable>(_ path: [String], query: [(name: String, value: String)] = []) async throws(APIError) -> T {
        try decode(try await exchange(Endpoint(.get, path, query: query)))
    }

    func mutate<T: Decodable>(
        _ method: HTTPMethod, _ path: [String], _ body: some Encodable, key: UUID
    ) async throws(APIError) -> T {
        try decode(try await exchange(Endpoint(method, path, body: try encode(body), idempotencyKey: key)))
    }

    /// Login and signup: no old cookie is sent, and a success must set a new one.
    func startSession(_ path: [String], _ body: some Encodable) async throws(APIError) -> MeDTO {
        let exchange = try await exchange(Endpoint(.post, path, body: try encode(body), sendsSession: false))
        guard case .set = exchange.sessionUpdate else {
            throw APIError(
                kind: .decoding("The response did not set the \(BrainBuddyAPI.sessionCookieName) cookie."),
                message: "The server didn't start a session. Check the server address.",
                referenceID: exchange.response.header("X-Correlation-ID") ?? exchange.correlationID,
                statusCode: exchange.response.statusCode
            )
        }
        return try decode(exchange)
    }

    /// Sends `endpoint` and returns a 2xx response, or throws the mapped error.
    func exchange(_ endpoint: Endpoint) async throws(APIError) -> Exchange {
        let correlationID = makeCorrelationID().uuidString.lowercased()
        var headers = [
            "Accept": "application/json",
            "X-Client": "\(identity.name)/\(identity.version)",
            "X-Correlation-ID": correlationID,
        ]
        if endpoint.body != nil { headers["Content-Type"] = "application/json" }
        if let key = endpoint.idempotencyKey { headers["Idempotency-Key"] = key.uuidString.lowercased() }
        var sentToken: String?
        if endpoint.sendsSession {
            do { sentToken = try tokenStore.token(for: baseURL) } catch { throw APIError.tokenStorage(error) }
            if let sentToken { headers["Cookie"] = "\(BrainBuddyAPI.sessionCookieName)=\(sentToken)" }
        }
        let url = try url(for: endpoint)
        let request = HTTPRequest(method: endpoint.method, url: url, headers: headers, body: endpoint.body)

        if Task.isCancelled {
            let notSent = TransportError(
                description: "Cancelled before sending.", requestMayHaveBeenSent: false, isCancellation: true
            )
            throw APIError.transport(notSent, sentCorrelationID: correlationID)
        }
        let response: HTTPResponse
        do {
            response = try await transport.send(request)
        } catch let error as TransportError {
            throw APIError.transport(error, sentCorrelationID: correlationID)
        } catch is CancellationError {
            let cancelled = TransportError(
                description: "Cancelled.", requestMayHaveBeenSent: true, isCancellation: true
            )
            throw APIError.transport(cancelled, sentCorrelationID: correlationID)
        } catch {
            let unknown = TransportError(description: String(describing: error), requestMayHaveBeenSent: true)
            throw APIError.transport(unknown, sentCorrelationID: correlationID)
        }

        let sessionUpdate = response.header("Set-Cookie").flatMap {
            SetCookieParser.update(for: BrainBuddyAPI.sessionCookieName, in: $0)
        }
        do {
            switch sessionUpdate {
            case .set(let token): try tokenStore.setToken(token, for: baseURL)
            case .removed: try tokenStore.removeToken(for: baseURL)
            case nil: break
            }
        } catch {
            throw APIError.tokenStorage(error)
        }

        if response.statusCode == 401, let sentToken, sessionUpdate == nil {
            // Forget only the token this request used: a sign-in that finished
            // meanwhile may already have stored a newer one.
            if (try? tokenStore.token(for: baseURL)) == sentToken { try? tokenStore.removeToken(for: baseURL) }
        }
        guard (200..<300).contains(response.statusCode) else {
            throw APIError.from(response: response, sentCorrelationID: correlationID)
        }
        return Exchange(response: response, correlationID: correlationID, sessionUpdate: sessionUpdate)
    }

    func decode<T: Decodable>(_ exchange: Exchange) throws(APIError) -> T {
        do {
            return try BrainBuddyAPI.makeDecoder().decode(T.self, from: exchange.response.body)
        } catch {
            throw APIError.decoding(error, response: exchange.response, sentCorrelationID: exchange.correlationID)
        }
    }

    func encode(_ body: some Encodable) throws(APIError) -> Data {
        do {
            return try BrainBuddyAPI.makeEncoder().encode(body)
        } catch {
            throw APIError(
                kind: .decoding("Could not encode the request: \(error)"),
                message: "Brain Buddy couldn't prepare this change.", requestMayHaveBeenSent: false
            )
        }
    }

    func url(for endpoint: Endpoint) throws(APIError) -> URL {
        var text = baseURL.absoluteString
        while text.hasSuffix("/") { text.removeLast() }
        for segment in endpoint.path { text += "/" + Self.percentEncode(segment, isPathSegment: true) }
        if !endpoint.query.isEmpty {
            let pairs = endpoint.query.map { "\(Self.percentEncode($0.name))=\(Self.percentEncode($0.value))" }
            text += "?" + pairs.joined(separator: "&")
        }
        guard let url = URL(string: text) else {
            throw APIError(kind: .rejected, message: "The server address isn't valid.", requestMayHaveBeenSent: false)
        }
        return url
    }

    private static let unreserved = CharacterSet(
        charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
    )

    /// RFC 3986 percent-encoding keeping only unreserved characters, so `+`,
    /// `&`, `=`, `/`, `?`, `#`, `%` and spaces are always escaped. A path
    /// segment made only of dots is escaped too, so it cannot be normalized away.
    static func percentEncode(_ value: String, isPathSegment: Bool = false) -> String {
        if isPathSegment, !value.isEmpty, value.allSatisfy({ $0 == "." }) {
            return String(repeating: "%2E", count: value.count)
        }
        return value.addingPercentEncoding(withAllowedCharacters: unreserved) ?? value
    }
}
