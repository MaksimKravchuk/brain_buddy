import BrainBuddyCore
import Foundation
import Testing

@testable import BrainBuddyAPI

/// One endpoint's expected wire request, checked against `backend/app/api/tasks.py`
/// and `backend/app/schemas/tasks.py`. Bodies are compared byte for byte
/// (the client writes sorted keys), so an extra key, a missing key or a
/// `null` where an omission belongs fails the test.
struct EndpointCase: Sendable, CustomTestStringConvertible {
    var name: String
    var response: ScriptedTransport.Step
    var method: HTTPMethod
    var url: String
    var body: String?
    var isMutation: Bool
    var call: @Sendable (BrainBuddyAPIClient) async throws -> Void

    var testDescription: String { name }

    static let base = "https://api.example.test/api"
    static let key = Fixture.key

    static let all: [EndpointCase] = auth + projects + tags + tasks + children

    static let auth: [EndpointCase] = [
        EndpointCase(
            name: "GET /auth/me", response: Fixture.json(200, Fixture.me), method: .get, url: "\(base)/auth/me",
            body: nil, isMutation: false, call: { _ = try await $0.me() }
        ),
    ]

    static let projects: [EndpointCase] = [
        EndpointCase(
            name: "GET /projects", response: Fixture.json(200, "[\(Fixture.project)]"), method: .get,
            url: "\(base)/projects", body: nil, isMutation: false, call: { _ = try await $0.listProjects() }
        ),
        EndpointCase(
            name: "GET /projects?state=all (021-FR-026)", response: Fixture.json(200, "[\(Fixture.project)]"),
            method: .get, url: "\(base)/projects?state=all", body: nil, isMutation: false,
            call: { _ = try await $0.listProjects(state: .all) }
        ),
        EndpointCase(
            name: "GET /projects?state=archived (021-FR-026)", response: Fixture.json(200, "[\(Fixture.archivedProject)]"),
            method: .get, url: "\(base)/projects?state=archived", body: nil, isMutation: false,
            call: { _ = try await $0.listProjects(state: .archived) }
        ),
        EndpointCase(
            name: "GET /projects/{id}", response: Fixture.json(200, Fixture.archivedProject), method: .get,
            url: "\(base)/projects/project_0a1b2c3d4e5f", body: nil, isMutation: false,
            call: { _ = try await $0.getProject(id: "project_0a1b2c3d4e5f") }
        ),
        EndpointCase(
            name: "POST /projects without colour omits color", response: Fixture.json(201, Fixture.project),
            method: .post, url: "\(base)/projects", body: #"{"name":"Home"}"#, isMutation: true,
            call: { _ = try await $0.createProject(name: "Home", idempotencyKey: key) }
        ),
        EndpointCase(
            name: "POST /projects with colour", response: Fixture.json(201, Fixture.project), method: .post,
            url: "\(base)/projects", body: ##"{"color":"#0EA5E9","name":"Home"}"##, isMutation: true,
            call: { _ = try await $0.createProject(name: "Home", color: "#0EA5E9", idempotencyKey: key) }
        ),
        EndpointCase(
            name: "POST /projects with a desired outcome (021-FR-028)", response: Fixture.json(201, Fixture.project),
            method: .post, url: "\(base)/projects", body: #"{"desired_outcome":"Shed built","name":"Home"}"#,
            isMutation: true,
            call: { _ = try await $0.createProject(name: "Home", desiredOutcome: "Shed built", idempotencyKey: key) }
        ),
        EndpointCase(
            name: "PATCH /projects/{id} desired outcome (021-FR-028)", response: Fixture.json(200, Fixture.project),
            method: .patch, url: "\(base)/projects/project_0a1b2c3d4e5f",
            body: #"{"desired_outcome":"Shed built","expected_revision":2}"#, isMutation: true,
            call: {
                _ = try await $0.updateProject(
                    id: "project_0a1b2c3d4e5f", desiredOutcome: .set("Shed built"), expectedRevision: 2, idempotencyKey: key
                )
            }
        ),
        EndpointCase(
            name: "PATCH /projects/{id} clearing the outcome sends null (021-FR-028)",
            response: Fixture.json(200, Fixture.project), method: .patch, url: "\(base)/projects/project_0a1b2c3d4e5f",
            body: #"{"desired_outcome":null,"expected_revision":2}"#, isMutation: true,
            call: {
                _ = try await $0.updateProject(
                    id: "project_0a1b2c3d4e5f", desiredOutcome: .clear, expectedRevision: 2, idempotencyKey: key
                )
            }
        ),
        EndpointCase(
            name: "PATCH /projects/{id} rename omits color", response: Fixture.json(200, Fixture.project),
            method: .patch, url: "\(base)/projects/project_0a1b2c3d4e5f",
            body: #"{"expected_revision":2,"name":"House"}"#, isMutation: true,
            call: {
                _ = try await $0.updateProject(
                    id: "project_0a1b2c3d4e5f", name: "House", expectedRevision: 2, idempotencyKey: key
                )
            }
        ),
        EndpointCase(
            name: "PATCH /projects/{id} clearing colour sends null", response: Fixture.json(200, Fixture.project),
            method: .patch, url: "\(base)/projects/project_0a1b2c3d4e5f",
            body: #"{"color":null,"expected_revision":2}"#, isMutation: true,
            call: {
                _ = try await $0.updateProject(
                    id: "project_0a1b2c3d4e5f", color: .clear, expectedRevision: 2, idempotencyKey: key
                )
            }
        ),
        EndpointCase(
            name: "PATCH /projects/{id} name and colour", response: Fixture.json(200, Fixture.project),
            method: .patch, url: "\(base)/projects/project_0a1b2c3d4e5f",
            body: ##"{"color":"#22C55E","expected_revision":2,"name":"House"}"##, isMutation: true,
            call: {
                _ = try await $0.updateProject(
                    id: "project_0a1b2c3d4e5f", name: "House", color: .set("#22C55E"), expectedRevision: 2,
                    idempotencyKey: key
                )
            }
        ),
        EndpointCase(
            name: "POST /projects/{id}/archive", response: Fixture.json(200, Fixture.archivedProject), method: .post,
            url: "\(base)/projects/project_0a1b2c3d4e5f/archive", body: #"{"expected_revision":2}"#,
            isMutation: true,
            call: { _ = try await $0.archiveProject(id: "project_0a1b2c3d4e5f", expectedRevision: 2, idempotencyKey: key) }
        ),
        EndpointCase(
            name: "POST /projects/{id}/unarchive (021-FR-026)", response: Fixture.json(200, Fixture.project),
            method: .post, url: "\(base)/projects/project_0a1b2c3d4e5f/unarchive", body: #"{"expected_revision":3}"#,
            isMutation: true,
            call: { _ = try await $0.unarchiveProject(id: "project_0a1b2c3d4e5f", expectedRevision: 3, idempotencyKey: key) }
        ),
    ]

    static let tags: [EndpointCase] = [
        EndpointCase(
            name: "GET /tags", response: Fixture.json(200, "[\(Fixture.tag)]"), method: .get, url: "\(base)/tags",
            body: nil, isMutation: false, call: { _ = try await $0.listTags() }
        ),
        EndpointCase(
            name: "GET /tags/{id}", response: Fixture.json(200, Fixture.deletedTag), method: .get,
            url: "\(base)/tags/tag_0a1b2c3d4e5f", body: nil, isMutation: false,
            call: { _ = try await $0.getTag(id: "tag_0a1b2c3d4e5f") }
        ),
        EndpointCase(
            name: "POST /tags", response: Fixture.json(201, Fixture.tag), method: .post, url: "\(base)/tags",
            body: #"{"name":"@errands"}"#, isMutation: true,
            call: { _ = try await $0.createTag(name: "@errands", idempotencyKey: key) }
        ),
        EndpointCase(
            name: "PATCH /tags/{id}", response: Fixture.json(200, Fixture.tag), method: .patch,
            url: "\(base)/tags/tag_0a1b2c3d4e5f", body: #"{"expected_revision":1,"name":"errands"}"#, isMutation: true,
            call: {
                _ = try await $0.updateTag(id: "tag_0a1b2c3d4e5f", name: "errands", expectedRevision: 1, idempotencyKey: key)
            }
        ),
        EndpointCase(
            name: "DELETE /tags/{id}?expected_revision", response: Fixture.json(200, Fixture.deletedTag),
            method: .delete, url: "\(base)/tags/tag_0a1b2c3d4e5f?expected_revision=4", body: nil, isMutation: true,
            call: { _ = try await $0.deleteTag(id: "tag_0a1b2c3d4e5f", expectedRevision: 4, idempotencyKey: key) }
        ),
    ]

    static let tasks: [EndpointCase] = [
        EndpointCase(
            name: "GET /tasks with no filters", response: Fixture.json(200, Fixture.page([Fixture.task()])),
            method: .get, url: "\(base)/tasks", body: nil, isMutation: false,
            call: { _ = try await $0.listTasks() }
        ),
        EndpointCase(
            name: "GET /tasks/{id}", response: Fixture.json(200, Fixture.taskDetail), method: .get,
            url: "\(base)/tasks/task_1a2b3c4d5e6f", body: nil, isMutation: false,
            call: { _ = try await $0.getTask(id: "task_1a2b3c4d5e6f") }
        ),
        EndpointCase(
            name: "POST /tasks minimal always sends priority and tag_ids", response: Fixture.json(201, Fixture.task()),
            method: .post, url: "\(base)/tasks",
            body: #"{"priority":"none","state":"inbox","tag_ids":[],"title":"Buy milk"}"#, isMutation: true,
            call: { _ = try await $0.createTask(TaskCreateBody(title: "Buy milk", state: .inbox), idempotencyKey: key) }
        ),
        EndpointCase(
            name: "POST /tasks with every field", response: Fixture.json(201, Fixture.task(state: "waiting")),
            method: .post, url: "\(base)/tasks",
            body:
                #"{"details":"2 litres","due_date":"2026-10-01","priority":"high","project_id":"project_0a1b2c3d4e5f","state":"waiting","tag_ids":["tag_a","tag_b"],"title":"Buy milk","waiting_for":"Sam"}"#,
            isMutation: true,
            call: {
                _ = try await $0.createTask(
                    TaskCreateBody(
                        title: "Buy milk", details: "2 litres", state: .waiting, projectID: "project_0a1b2c3d4e5f",
                        tagIDs: ["tag_a", "tag_b"], dueDate: CalendarDay(year: 2026, month: 10, day: 1),
                        priority: .high, waitingFor: "Sam"
                    ),
                    idempotencyKey: key
                )
            }
        ),
        EndpointCase(
            name: "PATCH /tasks/{id} sends only expected_revision and set fields",
            response: Fixture.json(200, Fixture.task(revision: 8)), method: .patch,
            url: "\(base)/tasks/task_1a2b3c4d5e6f", body: #"{"expected_revision":7,"priority":"medium","title":"Buy oat milk"}"#,
            isMutation: true,
            call: {
                _ = try await $0.updateTask(
                    id: "task_1a2b3c4d5e6f",
                    TaskUpdateBody(expectedRevision: 7, title: .set("Buy oat milk"), priority: .set(.medium)),
                    idempotencyKey: key
                )
            }
        ),
        EndpointCase(
            name: "PATCH /tasks/{id} clears with null", response: Fixture.json(200, Fixture.task(revision: 8)),
            method: .patch, url: "\(base)/tasks/task_1a2b3c4d5e6f",
            body: #"{"details":null,"due_date":null,"expected_revision":7,"project_id":null,"tag_ids":null}"#,
            isMutation: true,
            call: {
                _ = try await $0.updateTask(
                    id: "task_1a2b3c4d5e6f",
                    TaskUpdateBody(expectedRevision: 7, details: .clear, projectID: .clear, tagIDs: .clear, dueDate: .clear),
                    idempotencyKey: key
                )
            }
        ),
        EndpointCase(
            name: "PATCH /tasks/{id} sets every field", response: Fixture.json(200, Fixture.task(revision: 8)),
            method: .patch, url: "\(base)/tasks/task_1a2b3c4d5e6f",
            body:
                #"{"details":"Oat","due_date":"2026-12-31","expected_revision":7,"priority":"low","project_id":"project_0a1b2c3d4e5f","tag_ids":["tag_a"],"title":"Milk","waiting_for":"Sam"}"#,
            isMutation: true,
            call: {
                _ = try await $0.updateTask(
                    id: "task_1a2b3c4d5e6f",
                    TaskUpdateBody(
                        expectedRevision: 7, title: .set("Milk"), details: .set("Oat"),
                        projectID: .set("project_0a1b2c3d4e5f"), tagIDs: .set(["tag_a"]),
                        dueDate: .set(CalendarDay(year: 2026, month: 12, day: 31)!), priority: .set(.low),
                        waitingFor: .set("Sam")
                    ),
                    idempotencyKey: key
                )
            }
        ),
        EndpointCase(
            name: "POST /tasks/{id}/transitions complete", response: Fixture.json(200, Fixture.task(state: "completed")),
            method: .post, url: "\(base)/tasks/task_1a2b3c4d5e6f/transitions",
            body: #"{"action":"complete","expected_revision":7}"#, isMutation: true,
            call: {
                _ = try await $0.transitionTask(
                    id: "task_1a2b3c4d5e6f", TaskTransitionBody(action: .complete, expectedRevision: 7), idempotencyKey: key
                )
            }
        ),
        EndpointCase(
            name: "POST /tasks/{id}/transitions move into Waiting",
            response: Fixture.json(200, Fixture.task(state: "waiting")), method: .post,
            url: "\(base)/tasks/task_1a2b3c4d5e6f/transitions",
            body: #"{"action":"move","expected_revision":7,"to_state":"waiting","waiting_for":"Sam"}"#, isMutation: true,
            call: {
                _ = try await $0.transitionTask(
                    id: "task_1a2b3c4d5e6f",
                    TaskTransitionBody(action: .move, toState: .waiting, waitingFor: "Sam", expectedRevision: 7),
                    idempotencyKey: key
                )
            }
        ),
        EndpointCase(
            name: "POST /tasks/{id}/transitions reopen", response: Fixture.json(200, Fixture.task(state: "next")),
            method: .post, url: "\(base)/tasks/task_1a2b3c4d5e6f/transitions",
            body: #"{"action":"reopen","expected_revision":3,"to_state":"next"}"#, isMutation: true,
            call: {
                _ = try await $0.transitionTask(
                    id: "task_1a2b3c4d5e6f", TaskTransitionBody(action: .reopen, toState: .next, expectedRevision: 3),
                    idempotencyKey: key
                )
            }
        ),
    ]

    static let children: [EndpointCase] = [
        EndpointCase(
            name: "POST /tasks/{id}/subtasks", response: Fixture.json(201, Fixture.subtask), method: .post,
            url: "\(base)/tasks/task_1a2b3c4d5e6f/subtasks", body: #"{"title":"Call Sam"}"#, isMutation: true,
            call: { _ = try await $0.createSubtask(taskID: "task_1a2b3c4d5e6f", title: "Call Sam", idempotencyKey: key) }
        ),
        EndpointCase(
            name: "PATCH /tasks/{id}/subtasks/{sid}", response: Fixture.json(200, Fixture.subtask), method: .patch,
            url: "\(base)/tasks/task_1a2b3c4d5e6f/subtasks/subtask_5e6f7a8b9c0d",
            body: #"{"expected_revision":1,"title":"Call Sam today"}"#, isMutation: true,
            call: {
                _ = try await $0.updateSubtask(
                    taskID: "task_1a2b3c4d5e6f", subtaskID: "subtask_5e6f7a8b9c0d", title: "Call Sam today",
                    expectedRevision: 1, idempotencyKey: key
                )
            }
        ),
        EndpointCase(
            name: "POST /tasks/{id}/subtasks/{sid}/transitions", response: Fixture.json(200, Fixture.subtask),
            method: .post, url: "\(base)/tasks/task_1a2b3c4d5e6f/subtasks/subtask_5e6f7a8b9c0d/transitions",
            body: #"{"action":"complete","expected_revision":1}"#, isMutation: true,
            call: {
                _ = try await $0.transitionSubtask(
                    taskID: "task_1a2b3c4d5e6f", subtaskID: "subtask_5e6f7a8b9c0d", action: .complete,
                    expectedRevision: 1, idempotencyKey: key
                )
            }
        ),
        EndpointCase(
            name: "POST /tasks/{id}/comments", response: Fixture.json(201, Fixture.comment), method: .post,
            url: "\(base)/tasks/task_1a2b3c4d5e6f/comments", body: #"{"body":"Asked twice."}"#, isMutation: true,
            call: { _ = try await $0.createComment(taskID: "task_1a2b3c4d5e6f", body: "Asked twice.", idempotencyKey: key) }
        ),
        EndpointCase(
            name: "PATCH /tasks/{id}/comments/{cid}", response: Fixture.json(200, Fixture.comment), method: .patch,
            url: "\(base)/tasks/task_1a2b3c4d5e6f/comments/comment_9c0d1e2f3a4b",
            body: #"{"body":"Asked three times.","expected_revision":1}"#, isMutation: true,
            call: {
                _ = try await $0.updateComment(
                    taskID: "task_1a2b3c4d5e6f", commentID: "comment_9c0d1e2f3a4b", body: "Asked three times.",
                    expectedRevision: 1, idempotencyKey: key
                )
            }
        ),
    ]
}

@Suite("Endpoint requests")
struct EndpointRequestTests {
    @Test(arguments: EndpointCase.all)
    func requestShape(_ endpoint: EndpointCase) async throws {
        let transport = ScriptedTransport([endpoint.response])
        let client = Fixture.client(transport, store: Fixture.signedInStore())

        try await endpoint.call(client)

        let request = try #require(transport.lastRequest)
        #expect(transport.requests.count == 1)
        #expect(request.method == endpoint.method)
        #expect(request.url.absoluteString == endpoint.url)
        #expect(request.bodyText == endpoint.body)
        #expect(request.header("Content-Type") == (endpoint.body == nil ? nil : "application/json"))
        #expect(request.header("Accept") == "application/json")
        #expect(request.header("X-Client") == "brainbuddy-ios/1.2.3")
        #expect(request.header("X-Correlation-ID") == Fixture.correlationHeader)
        #expect(request.header("Cookie") == "brainbuddy_session=\(Fixture.token)")
        #expect(request.header("Idempotency-Key") == (endpoint.isMutation ? Fixture.keyHeader : nil))
    }

    @Test("Every mutating route in the design table is covered")
    func coversEveryCommandRoute() {
        // docs/native-ios-app.md › Commands and endpoints: 14 commands, one route each, and spec 021's unarchive.
        let routes = Set(EndpointCase.all.filter(\.isMutation).map { "\($0.method.rawValue) \($0.url)" })
        #expect(routes.count == 15)
    }

    @Test("Login sends credentials, no stale cookie, and no Idempotency-Key")
    func loginRequest() async throws {
        let transport = ScriptedTransport([
            Fixture.json(200, Fixture.me, headers: ["set-cookie": Fixture.loginSetCookie]),
        ])
        let client = Fixture.client(transport, store: Fixture.signedInStore("old-token"))

        let me = try await client.login(email: "ada@example.com", password: "correct horse")

        let request = try #require(transport.lastRequest)
        #expect(request.method == .post)
        #expect(request.url.absoluteString == "https://api.example.test/api/auth/login")
        #expect(request.bodyText == #"{"email":"ada@example.com","password":"correct horse"}"#)
        #expect(request.header("Cookie") == nil)
        #expect(request.header("Idempotency-Key") == nil)
        #expect(me == MeDTO(
            id: "user_1a2b3c4d5e6f", email: "ada@example.com", displayName: "Ada",
            featureFlags: ["voice_brain_dump": true, "mobile_task_classification": false]
        ))
    }

    @Test("Signup sends invite_code and stores the session")
    func signupRequest() async throws {
        let transport = ScriptedTransport([
            Fixture.json(201, Fixture.me, headers: ["set-cookie": Fixture.loginSetCookie]),
        ])
        let store = InMemorySessionTokenStore()
        let client = Fixture.client(transport, store: store)

        _ = try await client.signup(email: "ada@example.com", password: "pw", inviteCode: "INV-42")

        let request = try #require(transport.lastRequest)
        #expect(request.url.absoluteString == "https://api.example.test/api/auth/signup")
        #expect(request.bodyText == #"{"email":"ada@example.com","invite_code":"INV-42","password":"pw"}"#)
        #expect(try store.token(for: Fixture.baseURL) == Fixture.token)
    }

    @Test("Logout is a bodyless POST with the cookie and no Idempotency-Key")
    func logoutRequest() async throws {
        let transport = ScriptedTransport([Fixture.noContent(headers: ["set-cookie": Fixture.logoutSetCookie])])
        let client = Fixture.client(transport, store: Fixture.signedInStore())

        try await client.logout()

        let request = try #require(transport.lastRequest)
        #expect(request.method == .post)
        #expect(request.url.absoluteString == "https://api.example.test/api/auth/logout")
        #expect(request.body == nil)
        #expect(request.header("Content-Type") == nil)
        #expect(request.header("Idempotency-Key") == nil)
        #expect(request.header("Cookie") == "brainbuddy_session=\(Fixture.token)")
    }

    @Test("A trailing slash on the base URL does not double the separator")
    func trailingSlashBase() async throws {
        let transport = ScriptedTransport([Fixture.json(200, "[]")])
        let client = Fixture.client(transport, baseURL: URL(string: "https://api.example.test/api/")!)

        _ = try await client.listTags()

        #expect(transport.lastRequest?.url.absoluteString == "https://api.example.test/api/tags")
    }

    @Test("Path ids are percent-encoded as single segments")
    func pathSegmentsAreEncoded() async throws {
        let transport = ScriptedTransport([
            Fixture.json(200, Fixture.task()), Fixture.json(200, Fixture.task()), Fixture.json(200, Fixture.subtask),
        ])
        let client = Fixture.client(transport)

        _ = try await client.getTask(id: "a/b c?d#e+f%")
        _ = try await client.getTask(id: "..")
        _ = try await client.updateSubtask(
            taskID: "t 1", subtaskID: "s/1", title: "x", expectedRevision: 1, idempotencyKey: Fixture.key
        )

        let urls = transport.requests.map(\.url.absoluteString)
        #expect(urls == [
            "https://api.example.test/api/tasks/a%2Fb%20c%3Fd%23e%2Bf%25",
            "https://api.example.test/api/tasks/%2E%2E",
            "https://api.example.test/api/tasks/t%201/subtasks/s%2F1",
        ])
    }

    @Test("Every request gets its own correlation id by default")
    func correlationIDsAreFresh() async throws {
        let transport = ScriptedTransport([Fixture.json(200, "[]"), Fixture.json(200, "[]")])
        let client = BrainBuddyAPIClient(
            baseURL: Fixture.baseURL, transport: transport, tokenStore: InMemorySessionTokenStore(), clientVersion: "9"
        )

        _ = try await client.listTags()
        _ = try await client.listTags()

        let ids = transport.requests.compactMap { $0.header("X-Correlation-ID") }
        #expect(ids.count == 2)
        #expect(ids[0] != ids[1])
        #expect(ids.allSatisfy { UUID(uuidString: $0) != nil && $0 == $0.lowercased() })
        #expect(transport.lastRequest?.header("X-Client") == "brainbuddy-ios/9")
    }
}
