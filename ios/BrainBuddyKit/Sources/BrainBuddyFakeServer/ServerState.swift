import BrainBuddyAPI
import BrainBuddyCore
import Foundation

/// Everything the fake server holds, and its request router. It lives in a
/// `Mutex` in `FakeBrainBuddyServer`, so each request is applied atomically,
/// like the backend's owner command lock.
struct ServerState: Sendable {
    var accounts: [String: FakeAccount] = [:]
    var accountIDsByEmail: [String: String] = [:]
    /// Session token → user id.
    var sessions: [String: String] = [:]
    var owners: [String: OwnerData] = [:]
    var ids: IDGenerator

    init(ids: IDGenerator) { self.ids = ids }

    /// `generate_id(prefix)`: `<prefix>_<12 hex>`.
    mutating func mint(_ prefix: String) -> String { "\(prefix)_\(ids.hex(12))" }

    mutating func respond(to request: HTTPRequest, now: Date) -> HTTPResponse {
        let correlationID = request.header("X-Correlation-ID") ?? "fake-\(ids.hex(12))"
        var reply: Reply
        do {
            reply = try route(request, now: now)
        } catch {
            let envelope: JSONValue = .object([
                "message": .string(error.message), "detail": error.detail, "reference_id": .string(correlationID),
            ])
            reply = .json(error.status, envelope)
        }
        reply.headers["x-correlation-id"] = correlationID
        return HTTPResponse(statusCode: reply.status, headers: reply.headers, body: reply.body)
    }

    /// Path segments after `/api`.
    static func segments(of url: URL) -> [String] {
        var parts = url.path.split(separator: "/", omittingEmptySubsequences: true).map(String.init)
        if parts.first == "api" { parts.removeFirst() }
        return parts
    }

    private mutating func route(_ request: HTTPRequest, now: Date) throws(FakeHTTPError) -> Reply {
        let path = Self.segments(of: request.url)
        let method = request.method
        if path.first == "auth", path.count == 2 {
            switch (method, path[1]) {
            case (.post, "login"): return try login(request, now: now)
            case (.post, "logout"): return logout(request)
            case (.get, "me"): return try me(request)
            default: throw .routeNotFound
            }
        }
        guard let resource = path.first, ["tasks", "projects", "tags", "review"].contains(resource) else {
            throw .routeNotFound
        }
        let owner = try authenticate(request)
        if resource == "review" { return try routeReview(method, path, request, owner: owner, now: now) }
        let query = ListQuery(request.url)
        switch resource {
        case "projects":
            switch (method, path.count) {
            case (.get, 1): return listProjects(owner)
            case (.post, 1): return try createProject(request, owner: owner, now: now)
            case (.get, 2): return try getProject(path[1], owner: owner)
            case (.patch, 2): return try updateProject(path[1], request, owner: owner, now: now)
            case (.post, 3) where path[2] == "archive": return try archiveProject(path[1], request, owner: owner, now: now)
            default: throw .routeNotFound
            }
        case "tags":
            switch (method, path.count) {
            case (.get, 1): return listTags(owner)
            case (.post, 1): return try createTag(request, owner: owner, now: now)
            case (.get, 2): return try getTag(path[1], owner: owner)
            case (.patch, 2): return try updateTag(path[1], request, owner: owner, now: now)
            case (.delete, 2): return try deleteTag(path[1], request, query: query, owner: owner, now: now)
            default: throw .routeNotFound
            }
        default:
            return try routeTasks(method, path, request, query: query, owner: owner, now: now)
        }
    }

    private mutating func routeTasks(
        _ method: HTTPMethod, _ path: [String], _ request: HTTPRequest, query: ListQuery, owner: String, now: Date
    ) throws(FakeHTTPError) -> Reply {
        switch (method, path.count) {
        case (.get, 1): return try listTasks(query, owner: owner)
        case (.post, 1): return try createTask(request, owner: owner, now: now)
        case (.get, 2): return try getTask(path[1], owner: owner)
        case (.patch, 2): return try updateTask(path[1], request, owner: owner, now: now)
        case (.post, 3) where path[2] == "transitions":
            return try transitionTask(path[1], request, owner: owner, now: now)
        case (.post, 3) where path[2] == "decisions":
            return try decide(path[1], request, owner: owner, now: now)
        case (.post, 3) where path[2] == "auto-park":
            return try autoPark(path[1], request, owner: owner, now: now)
        case (.post, 3) where path[2] == "subtasks":
            return try createSubtask(path[1], request, owner: owner, now: now)
        case (.post, 3) where path[2] == "comments":
            return try createComment(path[1], request, owner: owner, now: now)
        case (.patch, 4) where path[2] == "subtasks":
            return try updateSubtask(path[1], path[3], request, owner: owner, now: now)
        case (.post, 5) where path[2] == "subtasks" && path[4] == "transitions":
            return try transitionSubtask(path[1], path[3], request, owner: owner, now: now)
        case (.patch, 4) where path[2] == "comments":
            return try updateComment(path[1], path[3], request, owner: owner, now: now)
        default:
            throw .routeNotFound
        }
    }

    // MARK: - Sessions

    static let cookieName = BrainBuddyAPI.sessionCookieName

    func sessionToken(_ request: HTTPRequest) -> String? {
        guard let header = request.header("Cookie") else { return nil }
        for pair in header.split(separator: ";") {
            let parts = pair.split(separator: "=", maxSplits: 1).map { $0.trimmingCharacters(in: .whitespaces) }
            if parts.count == 2, parts[0] == Self.cookieName { return parts[1] }
        }
        return nil
    }

    /// `get_current_user`: 401 without a live session.
    func authenticate(_ request: HTTPRequest) throws(FakeHTTPError) -> String {
        guard let token = sessionToken(request), let owner = sessions[token] else { throw .unauthenticated }
        return owner
    }

    private func meDTO(_ account: FakeAccount, deletionCancelled: Bool = false) -> MeDTO {
        MeDTO(
            id: account.id, email: account.email, displayName: account.displayName, deletionCancelled: deletionCancelled,
            featureFlags: ["weekly_review": account.weeklyReview]
        )
    }

    /// `login`: a login within the deletion grace period cancels the deletion
    /// and reports `deletion_cancelled: true`.
    private mutating func login(_ request: HTTPRequest, now: Date) throws(FakeHTTPError) -> Reply {
        let body = try RequestBody(request.body, allowing: ["email", "password"])
        let email = try body.string("email", required: true) ?? ""
        let password = try body.string("password", required: true) ?? ""
        guard let id = accountIDsByEmail[email.lowercased()], let account = accounts[id], account.password == password
        else { throw FakeHTTPError(status: 401, message: "Invalid email or password.") }
        let token = "session_\(ids.hex(32))"
        sessions[token] = id
        let cancelledDeletion = account.deletionScheduled
        accounts[id]?.deletionScheduled = false
        var reply = Reply.json(200, meDTO(account, deletionCancelled: cancelledDeletion))
        reply.headers["set-cookie"] =
            "\(Self.cookieName)=\(token); HttpOnly; Max-Age=2592000; Path=/; SameSite=lax; Secure"
        return reply
    }

    private mutating func logout(_ request: HTTPRequest) -> Reply {
        if let token = sessionToken(request) { sessions[token] = nil }
        var reply = Reply.noContent()
        reply.headers["set-cookie"] =
            #"\#(Self.cookieName)=""; expires=Thu, 01 Jan 1970 00:00:00 GMT; Max-Age=0; Path=/; SameSite=lax"#
        return reply
    }

    private func me(_ request: HTTPRequest) throws(FakeHTTPError) -> Reply {
        let owner = try authenticate(request)
        guard let account = accounts[owner] else { throw .unauthenticated }
        return .json(200, meDTO(account))
    }

    // MARK: - Owner-serialized writes

    /// `_require_idempotency_key`.
    func idempotencyKey(_ request: HTTPRequest) throws(FakeHTTPError) -> String {
        guard let key = request.header("Idempotency-Key"), !key.isEmpty else { throw .missingIdempotencyKey }
        return key
    }

    /// `_serialized_write`: purges the owner's expired keys (committed even if
    /// the command then fails) and hands back a copy to change; `commit` stores it.
    mutating func beginWrite(_ owner: String, now: Date) -> OwnerData {
        var data = owners[owner] ?? OwnerData()
        let cutoff = now.addingTimeInterval(-FakeBrainBuddyServer.idempotencyRetention)
        data.idempotency = data.idempotency.filter { $0.value.createdAt >= cutoff }
        owners[owner] = data
        return data
    }

    mutating func commit(_ data: OwnerData, owner: String) { owners[owner] = data }

    func data(_ owner: String) -> OwnerData { owners[owner] ?? OwnerData() }
}

/// An answer before it becomes an `HTTPResponse`.
struct Reply {
    var status: Int
    var body: Data
    var headers: [String: String] = ["content-type": "application/json"]

    static let encoder = BrainBuddyAPI.makeEncoder()

    static func json(_ status: Int, _ value: some Encodable) -> Reply {
        Reply(status: status, body: (try? encoder.encode(value)) ?? Data("{}".utf8))
    }

    static func noContent() -> Reply { Reply(status: 204, body: Data(), headers: [:]) }
}

/// SplitMix64, so minted ids look random but repeat run to run.
struct IDGenerator: Sendable {
    var state: UInt64
    init(seed: UInt64) { state = seed }

    mutating func next() -> UInt64 {
        state &+= 0x9E37_79B9_7F4A_7C15
        var value = state
        value = (value ^ (value >> 30)) &* 0xBF58_476D_1CE4_E5B9
        value = (value ^ (value >> 27)) &* 0x94D0_49BB_1331_11EB
        return value ^ (value >> 31)
    }

    mutating func hex(_ digits: Int) -> String {
        var text = ""
        while text.count < digits {
            let chunk = String(next(), radix: 16)
            text += String(repeating: "0", count: 16 - chunk.count) + chunk
        }
        return String(text.prefix(digits))
    }
}
