import Foundation
import Synchronization
import Testing

@testable import BrainBuddyAPI

/// A transport that replays scripted steps in order and records every request.
final class ScriptedTransport: HTTPTransport {
    enum Step: Sendable {
        case respond(HTTPResponse)
        case fail(TransportError)
        case raise(any Error & Sendable)
        case run(@Sendable (HTTPRequest) async throws -> HTTPResponse)
    }

    private struct State {
        var steps: [Step]
        var requests: [HTTPRequest] = []
    }

    private let state: Mutex<State>

    init(_ steps: [Step] = []) { state = Mutex(State(steps: steps)) }

    func enqueue(_ step: Step) { state.withLock { $0.steps.append(step) } }

    var requests: [HTTPRequest] { state.withLock { $0.requests } }
    var lastRequest: HTTPRequest? { requests.last }

    func send(_ request: HTTPRequest) async throws -> HTTPResponse {
        let step: Step? = state.withLock { state in
            state.requests.append(request)
            return state.steps.isEmpty ? nil : state.steps.removeFirst()
        }
        switch step {
        case .respond(let response): return response
        case .fail(let error): throw error
        case .raise(let error): throw error
        case .run(let body): return try await body(request)
        case nil:
            Issue.record("Unexpected request: \(request.method.rawValue) \(request.url.absoluteString)")
            throw TransportError(description: "unscripted", requestMayHaveBeenSent: false)
        }
    }
}

/// A token store whose every call fails, like the Keychain before first unlock.
final class FailingTokenStore: SessionTokenStore {
    struct Locked: Error {}
    func token(for serverURL: URL) throws -> String? { throw Locked() }
    func setToken(_ token: String, for serverURL: URL) throws { throw Locked() }
    func removeToken(for serverURL: URL) throws { throw Locked() }
}

/// A token store holding a session this build may not read, like the login keychain after a rebuild.
final class DeniedTokenStore: SessionTokenStore {
    func token(for serverURL: URL) throws -> String? { throw TokenStoreError.accessDenied }
    func setToken(_ token: String, for serverURL: URL) throws {}
    func removeToken(for serverURL: URL) throws {}
}

/// A token store that reads fine but cannot write.
final class ReadOnlyTokenStore: SessionTokenStore {
    struct ReadOnly: Error {}
    func token(for serverURL: URL) throws -> String? { nil }
    func setToken(_ token: String, for serverURL: URL) throws { throw ReadOnly() }
    func removeToken(for serverURL: URL) throws { throw ReadOnly() }
}

enum Fixture {
    static let baseURL = URL(string: "https://api.example.test/api")!
    static let correlationID = UUID(uuidString: "0F0E0D0C-0B0A-4908-8706-050403020100")!
    static let correlationHeader = "0f0e0d0c-0b0a-4908-8706-050403020100"
    static let key = UUID(uuidString: "6F9619FF-8B86-4011-B42D-00C04FC964FF")!
    static let keyHeader = "6f9619ff-8b86-4011-b42d-00c04fc964ff"
    static let token = "session-cookie-fixture"

    static func client(
        _ transport: ScriptedTransport, store: any SessionTokenStore = InMemorySessionTokenStore(),
        baseURL: URL = Fixture.baseURL
    ) -> BrainBuddyAPIClient {
        BrainBuddyAPIClient(
            baseURL: baseURL, transport: transport, tokenStore: store, clientVersion: "1.2.3",
            correlationID: { Fixture.correlationID }
        )
    }

    static func signedInStore(_ token: String = Fixture.token, baseURL: URL = Fixture.baseURL) -> InMemorySessionTokenStore {
        InMemorySessionTokenStore(tokens: [baseURL: token])
    }

    /// A JSON response the way the backend sends one (it echoes the correlation id).
    static func json(_ status: Int, _ body: String, headers: [String: String] = [:]) -> ScriptedTransport.Step {
        var all = ["content-type": "application/json", "x-correlation-id": Fixture.correlationHeader]
        all.merge(headers) { _, new in new }
        return .respond(HTTPResponse(statusCode: status, headers: all, body: Data(body.utf8)))
    }

    static func noContent(headers: [String: String] = [:]) -> ScriptedTransport.Step {
        var all = ["x-correlation-id": Fixture.correlationHeader]
        all.merge(headers) { _, new in new }
        return .respond(HTTPResponse(statusCode: 204, headers: all))
    }

    /// `ErrorResponse` exactly as `backend/app/api/errors.py` writes it.
    static func error(_ status: Int, _ message: String, detail: String = "null", reference: String? = "ref-server-1",
                      headers: [String: String] = [:]) -> ScriptedTransport.Step
    {
        let referenceJSON = reference.map { "\"\($0)\"" } ?? "null"
        return json(status, #"{"message":"\#(message)","detail":\#(detail),"reference_id":\#(referenceJSON)}"#, headers: headers)
    }

    /// Starlette's `set_cookie` output for the production session cookie.
    static let loginSetCookie =
        "brainbuddy_session=\(token); HttpOnly; Max-Age=2592000; Path=/; SameSite=lax; Secure"
    /// Starlette's `delete_cookie` output (`expires` is "now", with a comma).
    static let logoutSetCookie =
        #"brainbuddy_session=""; expires=Tue, 29 Sep 2026 10:00:00 GMT; Max-Age=0; Path=/; SameSite=lax"#

    static let me =
        #"{"id":"user_1a2b3c4d5e6f","email":"ada@example.com","display_name":"Ada","deletion_cancelled":false,"feature_flags":{"voice_brain_dump":true,"mobile_task_classification":false}}"#
    static let project =
        ##"{"id":"project_0a1b2c3d4e5f","name":"Home","color":"#0EA5E9","state":"active","revision":2,"open_task_count":3}"##
    static let archivedProject =
        #"{"id":"project_0a1b2c3d4e5f","name":"Home","color":null,"state":"archived","revision":3,"open_task_count":0}"#
    // The server stores tag names without a leading "@" (`display_tag_name`).
    static let tag = #"{"id":"tag_0a1b2c3d4e5f","name":"errands","state":"active","revision":1,"open_task_count":2}"#
    static let deletedTag = #"{"id":"tag_0a1b2c3d4e5f","name":"errands","state":"deleted","revision":5,"open_task_count":0}"#
    static let subtask = #"{"id":"subtask_5e6f7a8b9c0d","title":"Call Sam","state":"open","order_key":0,"revision":1}"#
    static let comment =
        #"{"id":"comment_9c0d1e2f3a4b","body":"Asked twice.","actor_id":"user_1a2b3c4d5e6f","created_at":"2026-09-28T17:02:03.456789Z","edited_at":null,"revision":1}"#

    /// A `TaskResponse` as `GET /tasks/{id}` returns it.
    static let taskDetail = #"""
        {"id":"task_1a2b3c4d5e6f","title":"Renew passport","details":"Photos first","state":"waiting","project_id":"project_0a1b2c3d4e5f","tag_ids":["tag_0a1b2c3d4e5f"],"due_date":"2026-10-15","priority":"high","waiting_for":"Photo studio","waiting_since":"2026-09-20T09:30:00Z","order_key":4,"source_capture_ids":[],"created_at":"2026-09-01T08:00:00.120000Z","updated_at":"2026-09-20T09:30:00.000001Z","completed_at":null,"cancelled_at":null,"revision":7,"subtasks":[\#(subtask)],"comments":[\#(comment)]}
        """#

    /// A `TaskResponse` as list pages and mutations return it.
    static func task(id: String = "task_1a2b3c4d5e6f", state: String = "inbox", revision: Int = 1) -> String {
        #"{"id":"\#(id)","title":"Buy milk","details":null,"state":"\#(state)","project_id":null,"tag_ids":[],"due_date":null,"priority":"none","waiting_for":null,"waiting_since":null,"order_key":0,"source_capture_ids":[],"created_at":"2026-09-29T08:15:30Z","updated_at":"2026-09-29T08:15:30Z","completed_at":null,"cancelled_at":null,"revision":\#(revision),"subtasks":[],"comments":[]}"#
    }

    static func page(_ items: [String], nextCursor: String? = nil) -> String {
        let cursor = nextCursor.map { "\"\($0)\"" } ?? "null"
        return #"{"items":[\#(items.joined(separator: ","))],"next_cursor":\#(cursor),"has_more":\#(nextCursor != nil),"counts_by_state":{"inbox":1,"next":2,"waiting":3,"someday":4}}"#
    }

    /// Midnight-based UTC date from components (for expected values).
    static func utc(_ year: Int, _ month: Int, _ day: Int, _ hour: Int = 0, _ minute: Int = 0, _ second: Int = 0) -> Date {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        return calendar.date(from: DateComponents(year: year, month: month, day: day, hour: hour, minute: minute, second: second))!
    }
}

extension HTTPRequest {
    var bodyText: String? { body.map { String(decoding: $0, as: UTF8.self) } }
}

/// Runs `body` and returns the `APIError` it throws (recording an issue otherwise).
/// (Closures do not infer typed throws in Swift 6.2, hence the cast.)
func expectAPIError(
    sourceLocation: SourceLocation = #_sourceLocation, _ body: () async throws -> Void
) async -> APIError? {
    do {
        try await body()
        Issue.record("Expected an APIError", sourceLocation: sourceLocation)
        return nil
    } catch let error as APIError {
        return error
    } catch {
        Issue.record("Expected an APIError, got \(error)", sourceLocation: sourceLocation)
        return nil
    }
}
