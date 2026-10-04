import Foundation
import XCTest
@testable import BrainBuddyMac

private final class StubURLProtocol: URLProtocol {
    private static let lock = NSLock()
    static var statusCode = 200
    static var body = Data()
    static var headers: [String: String] = [:]
    static var responses: [String: (status: Int, body: Data, headers: [String: String])] = [:]
    static var methodResponses: [String: (status: Int, body: Data, headers: [String: String])] = [:]
    static var loginBodies: [Data] = []
    static var requests: [URLRequest] = []
    static var requestBodies: [Data] = []
    static var delayedPath: String?
    static var delayGate: DispatchSemaphore?
    static var onDelayedStart: (() -> Void)?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        var body = request.httpBody ?? Data()
        if body.isEmpty, let stream = request.httpBodyStream {
            stream.open()
            defer { stream.close() }
            var buffer = [UInt8](repeating: 0, count: 4096)
            while true {
                let count = stream.read(&buffer, maxLength: buffer.count)
                if count <= 0 { break }
                body.append(contentsOf: buffer[..<count])
            }
        }
        Self.lock.lock()
        Self.requests.append(request)
        Self.requestBodies.append(body)
        Self.lock.unlock()
        let path = request.url!.path
        var result = Self.methodResponses["\(request.httpMethod ?? "GET") \(path)"]
            ?? Self.responses[path] ?? (Self.statusCode, Self.body, Self.headers)
        if path == "/api/auth/login" {
            Self.lock.lock()
            if !Self.loginBodies.isEmpty { result.body = Self.loginBodies.removeFirst() }
            Self.lock.unlock()
        }
        let send = {
            let response = HTTPURLResponse(
                url: self.request.url!, statusCode: result.status, httpVersion: nil, headerFields: result.headers
            )!
            self.client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            self.client?.urlProtocol(self, didLoad: result.body)
            self.client?.urlProtocolDidFinishLoading(self)
        }
        if path == Self.delayedPath, let gate = Self.delayGate {
            Self.onDelayedStart?()
            DispatchQueue.global().async {
                gate.wait()
                send()
            }
        } else {
            send()
        }
    }

    override func stopLoading() {}
}

final class APIClientTests: XCTestCase {
    private func resetStub() {
        StubURLProtocol.responses = [:]
        StubURLProtocol.methodResponses = [:]
        StubURLProtocol.loginBodies = []
        StubURLProtocol.requests = []
        StubURLProtocol.requestBodies = []
        StubURLProtocol.delayedPath = nil
        StubURLProtocol.delayGate = nil
        StubURLProtocol.onDelayedStart = nil
        StubURLProtocol.headers = [:]
    }

    private func client() -> APIClient {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StubURLProtocol.self]
        return APIClient(
            baseURL: URL(string: "https://example.test/api")!,
            session: URLSession(configuration: configuration)
        )
    }

    private var taskJSON: Data {
        Data(#"{"id":"task-1","title":"Call Alex","details":"Ask about lease","state":"waiting","revision":3,"project_id":"project-1","tag_ids":["tag-1"],"due_date":"2026-09-28","priority":"high","waiting_for":"Alex to reply","waiting_since":"2026-09-25T09:00:00Z"}"#.utf8)
    }

    func testTerminalDetailDecodesOriginAndTimestamp() async throws {
        resetStub()
        StubURLProtocol.responses["/api/tasks/task-1"] = (200, Data(
            #"{"id":"task-1","title":"Call Alex","details":"Ask about lease","state":"completed","last_open_state":"waiting","completed_at":"2026-09-25T10:00:00Z","revision":4,"order_key":1,"subtasks":[{"id":"sub-1","title":"Check reply","state":"completed","order_key":1,"revision":2}],"comments":[]}"#.utf8
        ), [:])

        let task = try await client().getTask("task-1")
        XCTAssertEqual(task.last_open_state, .waiting)
        XCTAssertEqual(task.completed_at, "2026-09-25T10:00:00Z")
        XCTAssertNil(task.cancelled_at)
        XCTAssertEqual(task.subtasks.first?.title, "Check reply")
    }

    func testTaskDetailAndClassificationDecode() async throws {
        resetStub()
        StubURLProtocol.responses = [
            "/api/tasks/task-1": (200, taskJSON, [:]),
            "/api/projects": (200, Data(##"[{"id":"project-1","name":"House move","color":"#ff0000","state":"active","revision":2,"open_task_count":3}]"##.utf8), [:]),
            "/api/tags": (200, Data(#"[{"id":"tag-1","name":"home","state":"active","revision":1,"open_task_count":4}]"#.utf8), [:]),
        ]
        let api = client()
        let task = try await api.getTask("task-1")
        XCTAssertEqual(task.project_id, "project-1")
        XCTAssertEqual(task.tag_ids, ["tag-1"])
        XCTAssertEqual(task.due_date, "2026-09-28")
        XCTAssertEqual(task.priority, .high)
        XCTAssertEqual(task.waiting_for, "Alex to reply")
        XCTAssertEqual(task.waiting_since, "2026-09-25T09:00:00Z")
        let projects = try await api.listProjects()
        let tags = try await api.listTags()
        XCTAssertEqual(projects.first?.open_task_count, 3)
        XCTAssertEqual(tags.first?.name, "home")
    }

    func testTaskDetailDecodesSubtasksAndComments() async throws {
        resetStub()
        let detail = #"{"id":"task-1","title":"Call Alex","state":"next","revision":3,"subtasks":[{"id":"subtask-1","title":"Find number","state":"completed","order_key":0,"revision":2}],"comments":[{"id":"comment-1","body":"Called yesterday","actor_id":"owner-1","created_at":"2026-09-25T09:00:00Z","edited_at":null,"revision":1}]}"#
        StubURLProtocol.responses = ["/api/tasks/task-1": (200, Data(detail.utf8), [:])]

        let task = try await client().getTask("task-1")

        XCTAssertEqual(task.subtasks.map(\.title), ["Find number"])
        XCTAssertEqual(task.subtasks.first?.state, "completed")
        XCTAssertEqual(task.comments.map(\.body), ["Called yesterday"])
        XCTAssertEqual(task.comments.first?.created_at, "2026-09-25T09:00:00Z")
    }

    func testSubtaskWritesUseSubtaskRevisionAndIdempotency() async throws {
        resetStub()
        let subtaskJSON = Data(#"{"id":"subtask-1","title":"Find number","state":"open","order_key":0,"revision":2}"#.utf8)
        StubURLProtocol.responses = [
            "/api/tasks/task-1/subtasks": (201, subtaskJSON, [:]),
            "/api/tasks/task-1/subtasks/subtask-1": (200, subtaskJSON, [:]),
            "/api/tasks/task-1/subtasks/subtask-1/transitions": (200, subtaskJSON, [:]),
        ]
        let api = client()
        let subtask = try JSONDecoder().decode(BrainBuddySubtask.self, from: subtaskJSON)
        let createKey = UUID()
        let updateKey = UUID()
        let transitionKey = UUID()

        _ = try await api.createSubtask(taskID: "task-1", title: "Find number", idempotencyKey: createKey)
        _ = try await api.updateSubtask(taskID: "task-1", subtask: subtask, title: "Find new number", idempotencyKey: updateKey)
        _ = try await api.transitionSubtask(taskID: "task-1", subtask: subtask, action: .complete, idempotencyKey: transitionKey)

        XCTAssertEqual(StubURLProtocol.requests.map(\.httpMethod), ["POST", "PATCH", "POST"])
        XCTAssertEqual(StubURLProtocol.requests.map { $0.value(forHTTPHeaderField: "Idempotency-Key") },
                       [createKey.uuidString, updateKey.uuidString, transitionKey.uuidString])
        let bodies = try StubURLProtocol.requestBodies.map {
            try XCTUnwrap(JSONSerialization.jsonObject(with: $0) as? [String: Any])
        }
        XCTAssertEqual(bodies[0]["title"] as? String, "Find number")
        XCTAssertEqual(bodies[1]["expected_revision"] as? Int, 2)
        XCTAssertEqual(bodies[1]["title"] as? String, "Find new number")
        XCTAssertEqual(bodies[2]["expected_revision"] as? Int, 2)
        XCTAssertEqual(bodies[2]["action"] as? String, "complete")
    }

    func testCommentWritesUseCommentRevisionAndIdempotency() async throws {
        resetStub()
        let commentJSON = Data(#"{"id":"comment-1","body":"Called yesterday","actor_id":"owner-1","created_at":"2026-09-25T09:00:00Z","edited_at":null,"revision":4}"#.utf8)
        StubURLProtocol.responses = [
            "/api/tasks/task-1/comments": (201, commentJSON, [:]),
            "/api/tasks/task-1/comments/comment-1": (200, commentJSON, [:]),
        ]
        let api = client()
        let comment = try JSONDecoder().decode(BrainBuddyComment.self, from: commentJSON)
        let createKey = UUID()
        let updateKey = UUID()

        _ = try await api.createComment(taskID: "task-1", body: "Called yesterday", idempotencyKey: createKey)
        _ = try await api.updateComment(taskID: "task-1", comment: comment, body: "Called today", idempotencyKey: updateKey)

        XCTAssertEqual(StubURLProtocol.requests.map(\.httpMethod), ["POST", "PATCH"])
        XCTAssertEqual(StubURLProtocol.requests.map { $0.value(forHTTPHeaderField: "Idempotency-Key") },
                       [createKey.uuidString, updateKey.uuidString])
        let bodies = try StubURLProtocol.requestBodies.map {
            try XCTUnwrap(JSONSerialization.jsonObject(with: $0) as? [String: Any])
        }
        XCTAssertEqual(bodies[0]["body"] as? String, "Called yesterday")
        XCTAssertEqual(bodies[1]["body"] as? String, "Called today")
        XCTAssertEqual(bodies[1]["expected_revision"] as? Int, 4)
    }

    func testTaskQueryUsesServerFiltersAndDecodesCounts() async throws {
        resetStub()
        StubURLProtocol.statusCode = 200
        StubURLProtocol.body = Data(#"{"items":[],"next_cursor":"next","has_more":true,"counts_by_state":{"inbox":1,"next":2,"waiting":3,"someday":4}}"#.utf8)
        let page = try await client().listTasks(
            query: TaskQuery(
                state: .next, projectID: "project 1", tagID: "tag-1",
                includeCompleted: true, q: "call Alex", dueOn: "2026-09-28",
                priority: .high, sort: .due
            ), cursor: "cursor value"
        )
        XCTAssertEqual(page.counts_by_state?.waiting, 3)
        let components = URLComponents(url: try XCTUnwrap(StubURLProtocol.requests.last?.url), resolvingAgainstBaseURL: false)
        let values = Dictionary(uniqueKeysWithValues: (components?.queryItems ?? []).map { ($0.name, $0.value ?? "") })
        XCTAssertEqual(values["state"], "next")
        XCTAssertEqual(values["project_id"], "project 1")
        XCTAssertEqual(values["tag_id"], "tag-1")
        XCTAssertEqual(values["include_completed"], "true")
        XCTAssertEqual(values["q"], "call Alex")
        XCTAssertEqual(values["due_on"], "2026-09-28")
        XCTAssertEqual(values["priority"], "high")
        XCTAssertEqual(values["sort"], "due")
        XCTAssertEqual(values["cursor"], "cursor value")
    }

    @MainActor
    func testPriorityFilterReloadsThroughExistingTaskQuery() async throws {
        resetStub()
        StubURLProtocol.statusCode = 200
        StubURLProtocol.body = Data(#"{"items":[],"next_cursor":null,"has_more":false}"#.utf8)
        let model = BrainBuddyModel(api: client())
        model.priorityFilter = .high
        await model.reload()
        let filtered = URLComponents(
            url: try XCTUnwrap(StubURLProtocol.requests.last?.url),
            resolvingAgainstBaseURL: false
        )?.queryItems ?? []
        XCTAssertEqual(filtered.first(where: { $0.name == "priority" })?.value, "high")

        model.priorityFilter = .all
        await model.reload()
        let all = URLComponents(
            url: try XCTUnwrap(StubURLProtocol.requests.last?.url),
            resolvingAgainstBaseURL: false
        )?.queryItems ?? []
        XCTAssertFalse(all.contains(where: { $0.name == "priority" }))
    }

    func testTerminalHistoryQueriesItsOwnState() async throws {
        resetStub()
        StubURLProtocol.statusCode = 200
        StubURLProtocol.body = Data(#"{"items":[],"next_cursor":null,"has_more":false}"#.utf8)
        _ = try await client().listTasks(query: TaskQuery(terminalState: .completed))
        let components = URLComponents(url: try XCTUnwrap(StubURLProtocol.requests.last?.url), resolvingAgainstBaseURL: false)
        let values = Dictionary(uniqueKeysWithValues: (components?.queryItems ?? []).map { ($0.name, $0.value ?? "") })
        XCTAssertEqual(values["state"], "completed")
        XCTAssertNil(values["include_completed"])
    }

    @MainActor
    func testPagingKeepsSubmittedSearchAndDeduplicatesRows() async throws {
        resetStub()
        let first = try XCTUnwrap(String(data: taskJSON, encoding: .utf8))
        let second = first.replacingOccurrences(of: "task-1", with: "task-2")
        StubURLProtocol.responses["/api/tasks"] = (200, Data(
            "{\"items\":[\(first)],\"next_cursor\":\"page-2\",\"has_more\":true,\"counts_by_state\":{\"inbox\":0,\"next\":12,\"waiting\":0,\"someday\":0}}".utf8
        ), [:])
        let model = BrainBuddyModel(api: client())
        model.searchText = "call"
        await model.reload()
        XCTAssertEqual(model.tasks.map(\.id), ["task-1"])
        XCTAssertEqual(model.openCounts?.next, 12)

        model.searchText = "draft typed but not submitted"
        StubURLProtocol.responses["/api/tasks"] = (200, Data(
            "{\"items\":[\(first),\(second)],\"next_cursor\":null,\"has_more\":false}".utf8
        ), [:])
        await model.loadMore()
        XCTAssertEqual(model.tasks.map(\.id), ["task-1", "task-2"])
        XCTAssertEqual(model.openCounts?.next, 12)
        let pageRequest = try XCTUnwrap(StubURLProtocol.requests.last)
        let pageQuery = URLComponents(url: try XCTUnwrap(pageRequest.url), resolvingAgainstBaseURL: false)?.queryItems ?? []
        XCTAssertEqual(pageQuery.first(where: { $0.name == "q" })?.value, "call")
        XCTAssertEqual(pageQuery.first(where: { $0.name == "cursor" })?.value, "page-2")

        StubURLProtocol.responses["/api/tasks"] = (200, Data(
            #"{"items":[],"next_cursor":null,"has_more":false}"#.utf8
        ), [:])
        await model.reload()
        XCTAssertTrue(model.tasks.isEmpty)
        XCTAssertNil(model.openCounts)
        let newQuery = URLComponents(url: try XCTUnwrap(StubURLProtocol.requests.last?.url), resolvingAgainstBaseURL: false)?.queryItems ?? []
        XCTAssertEqual(newQuery.first(where: { $0.name == "q" })?.value, "draft typed but not submitted")
    }

    func testTaskPatchOmitsUnchangedFieldsAndClearsNullableFields() async throws {
        resetStub()
        StubURLProtocol.statusCode = 200
        StubURLProtocol.body = taskJSON
        let task = try JSONDecoder().decode(BrainBuddyTask.self, from: taskJSON)
        let key = UUID()
        _ = try await client().updateTask(
            task,
            changes: TaskChanges(
                title: .set("Call Alex tomorrow"), details: .clear,
                projectID: .clear, tagIDs: .set([]), dueDate: .clear,
                priority: .set(.medium)
            ),
            idempotencyKey: key
        )
        let sent = try XCTUnwrap(StubURLProtocol.requests.last)
        XCTAssertEqual(sent.httpMethod, "PATCH")
        XCTAssertEqual(sent.value(forHTTPHeaderField: "Idempotency-Key"), key.uuidString)
        let body = try XCTUnwrap(StubURLProtocol.requestBodies.last)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: Any])
        XCTAssertEqual(object["expected_revision"] as? Int, 3)
        XCTAssertEqual(object["title"] as? String, "Call Alex tomorrow")
        XCTAssertTrue(object["details"] is NSNull)
        XCTAssertTrue(object["project_id"] is NSNull)
        XCTAssertTrue(object["due_date"] is NSNull)
        XCTAssertEqual(object["tag_ids"] as? [String], [])
        XCTAssertEqual(object["priority"] as? String, "medium")
        XCTAssertNil(object["waiting_for"])
    }

    func testTransitionAndClassificationCreationIncludeRevisionAndIdempotency() async throws {
        resetStub()
        StubURLProtocol.responses = [
            "/api/tasks/task-1/transitions": (200, taskJSON, [:]),
            "/api/projects": (201, Data(#"{"id":"project-1","name":"House move","color":null,"state":"active","revision":1,"open_task_count":0}"#.utf8), [:]),
            "/api/tags": (201, Data(#"{"id":"tag-1","name":"home","state":"active","revision":1,"open_task_count":0}"#.utf8), [:]),
        ]
        let api = client()
        let task = try JSONDecoder().decode(BrainBuddyTask.self, from: taskJSON)
        let key = UUID()
        _ = try await api.transitionTask(
            task, action: .move, toState: .waiting,
            waitingFor: " Alex to reply ", idempotencyKey: key
        )
        let sent = try XCTUnwrap(StubURLProtocol.requests.last)
        XCTAssertEqual(sent.value(forHTTPHeaderField: "Idempotency-Key"), key.uuidString)
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: XCTUnwrap(StubURLProtocol.requestBodies.last)) as? [String: Any])
        XCTAssertEqual(body["action"] as? String, "move")
        XCTAssertEqual(body["to_state"] as? String, "waiting")
        XCTAssertEqual(body["waiting_for"] as? String, "Alex to reply")
        XCTAssertEqual(body["expected_revision"] as? Int, 3)

        let project = try await api.createProject(name: "House move", idempotencyKey: UUID())
        let tag = try await api.createTag(name: "home", idempotencyKey: UUID())
        XCTAssertEqual(project.name, "House move")
        XCTAssertEqual(tag.name, "home")
        XCTAssertTrue(StubURLProtocol.requests.suffix(2).allSatisfy {
            $0.httpMethod == "POST" && $0.value(forHTTPHeaderField: "Idempotency-Key") != nil
        })
    }

    func testCollectionRenameAndTagDeleteSendRevisionsAndIdempotency() async throws {
        resetStub()
        let project = try JSONDecoder().decode(BrainBuddyProject.self, from: Data(
            #"{"id":"project-1","name":"House move","color":null,"state":"active","revision":2,"open_task_count":0}"#.utf8
        ))
        let tag = try JSONDecoder().decode(BrainBuddyTag.self, from: Data(
            #"{"id":"tag-1","name":"home","state":"active","revision":3,"open_task_count":0}"#.utf8
        ))
        StubURLProtocol.methodResponses = [
            "PATCH /api/projects/project-1": (200, Data(
                #"{"id":"project-1","name":"Moving","color":null,"state":"active","revision":3,"open_task_count":0}"#.utf8
            ), [:]),
            "PATCH /api/tags/tag-1": (200, Data(
                #"{"id":"tag-1","name":"house","state":"active","revision":4,"open_task_count":0}"#.utf8
            ), [:]),
            "DELETE /api/tags/tag-1": (200, Data(
                #"{"id":"tag-1","name":"home","state":"deleted","revision":4,"open_task_count":0}"#.utf8
            ), [:]),
        ]
        let api = client()
        let keys = [UUID(), UUID(), UUID()]
        _ = try await api.renameProject(project, to: "Moving", idempotencyKey: keys[0])
        _ = try await api.renameTag(tag, to: "house", idempotencyKey: keys[1])
        _ = try await api.deleteTag(tag, idempotencyKey: keys[2])

        XCTAssertEqual(StubURLProtocol.requests.map(\.httpMethod), ["PATCH", "PATCH", "DELETE"])
        XCTAssertEqual(StubURLProtocol.requests.map { $0.value(forHTTPHeaderField: "Idempotency-Key") },
                       keys.map(\.uuidString))
        let projectBody = try XCTUnwrap(JSONSerialization.jsonObject(with: StubURLProtocol.requestBodies[0]) as? [String: Any])
        let tagBody = try XCTUnwrap(JSONSerialization.jsonObject(with: StubURLProtocol.requestBodies[1]) as? [String: Any])
        XCTAssertEqual(projectBody["expected_revision"] as? Int, 2)
        XCTAssertEqual(projectBody["name"] as? String, "Moving")
        XCTAssertEqual(tagBody["expected_revision"] as? Int, 3)
        XCTAssertEqual(tagBody["name"] as? String, "house")
        XCTAssertEqual(StubURLProtocol.requests[2].url?.query, "expected_revision=3")
    }

    @MainActor
    func testProjectRenameConflictRefreshesRevisionAndKeepsRequestedName() async throws {
        resetStub()
        let original = #"{"id":"project-1","name":"House move","color":null,"state":"active","revision":2,"open_task_count":0}"#
        let current = #"{"id":"project-1","name":"House moving","color":null,"state":"active","revision":3,"open_task_count":0}"#
        let updated = #"{"id":"project-1","name":"Moving","color":null,"state":"active","revision":4,"open_task_count":0}"#
        StubURLProtocol.methodResponses = [
            "PATCH /api/projects/project-1": (409, Data(#"{"message":"conflict"}"#.utf8), [:]),
        ]
        StubURLProtocol.responses = [
            "/api/projects": (200, Data("[\(current)]".utf8), [:]),
            "/api/tags": (200, Data("[]".utf8), [:]),
        ]
        let model = BrainBuddyModel(api: client())
        model.projects = [try JSONDecoder().decode(BrainBuddyProject.self, from: Data(original.utf8))]
        let firstAttempt = await model.renameProject("project-1", to: "Moving")
        XCTAssertFalse(firstAttempt)
        XCTAssertEqual(model.projects.first?.revision, 3)

        StubURLProtocol.methodResponses["PATCH /api/projects/project-1"] = (200, Data(updated.utf8), [:])
        StubURLProtocol.responses["/api/projects"] = (200, Data("[\(updated)]".utf8), [:])
        let secondAttempt = await model.renameProject("project-1", to: "Moving")
        XCTAssertTrue(secondAttempt)
        let requests = StubURLProtocol.requests.enumerated().filter { $0.element.httpMethod == "PATCH" }
        XCTAssertEqual(requests.count, 2)
        let revisions = try requests.map { index, _ in
            let body = try XCTUnwrap(JSONSerialization.jsonObject(with: StubURLProtocol.requestBodies[index]) as? [String: Any])
            return body["expected_revision"] as? Int
        }
        XCTAssertEqual(revisions, [2, 3])
        XCTAssertNotEqual(requests[0].element.value(forHTTPHeaderField: "Idempotency-Key"),
                          requests[1].element.value(forHTTPHeaderField: "Idempotency-Key"))
        XCTAssertEqual(model.projects.first?.name, "Moving")
    }

    func testSmartAddSendsAtomicClassificationReferences() async throws {
        resetStub()
        let response = #"{"task":{"id":"task-1","title":"Call Alex","details":null,"state":"next","revision":1},"project":null,"tags":[],"created":{"project_id":"project-1","tag_ids":["tag-1"]}}"#
        StubURLProtocol.responses = [
            "/api/tasks/smart-add": (201, Data(response.utf8), [:]),
        ]
        let key = UUID()
        let result = try await client().smartAddTask(
            title: "Call Alex", state: .next,
            project: .id("project-1"), tags: [.name("new tag")],
            idempotencyKey: key
        )
        XCTAssertEqual(result.created.project_id, "project-1")
        XCTAssertEqual(result.created.tag_ids, ["tag-1"])
        let sent = try XCTUnwrap(StubURLProtocol.requests.last)
        XCTAssertEqual(sent.value(forHTTPHeaderField: "Idempotency-Key"), key.uuidString)
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: XCTUnwrap(StubURLProtocol.requestBodies.last)) as? [String: Any])
        XCTAssertEqual(body["project"] as? [String: String], ["id": "project-1"])
        XCTAssertEqual(body["tags"] as? [[String: String]], [["name": "new tag"]])
    }

    @MainActor
    func testProjectCaptureUsesOneAtomicSmartAddRequest() async throws {
        resetStub()
        let smartAddResponse = #"{"task":{"id":"task-1","title":"Email insurer","details":null,"state":"next","revision":1,"project_id":"project-1","tag_ids":["tag-1"]},"project":null,"tags":[],"created":{"project_id":null,"tag_ids":[]}}"#
        StubURLProtocol.responses = [
            "/api/tasks/smart-add": (201, Data(smartAddResponse.utf8), [:]),
            "/api/projects": (200, Data(#"[{"id":"project-1","name":"House move","color":null,"state":"active","revision":1,"open_task_count":1}]"#.utf8), [:]),
            "/api/tags": (200, Data(#"[{"id":"tag-1","name":"home","state":"active","revision":1,"open_task_count":1}]"#.utf8), [:]),
            "/api/tasks": (200, Data(#"{"items":[],"next_cursor":null,"has_more":false}"#.utf8), [:]),
        ]
        let model = BrainBuddyModel(api: client())
        model.projects = try JSONDecoder().decode([BrainBuddyProject].self, from: StubURLProtocol.responses["/api/projects"]!.body)
        model.tags = try JSONDecoder().decode([BrainBuddyTag].self, from: StubURLProtocol.responses["/api/tags"]!.body)
        model.destination = .project("project-1")
        model.draft = "Email insurer #home"

        await model.createTask()

        XCTAssertNil(model.error)
        XCTAssertTrue(model.draft.isEmpty)
        let mutations = StubURLProtocol.requests.enumerated().filter { _, request in
            request.httpMethod == "POST" || request.httpMethod == "PATCH"
        }
        XCTAssertEqual(mutations.count, 1)
        XCTAssertEqual(mutations.first?.element.url?.path, "/api/tasks/smart-add")
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: StubURLProtocol.requestBodies[mutations[0].offset]) as? [String: Any])
        XCTAssertEqual(body["title"] as? String, "Email insurer")
        XCTAssertEqual(body["project"] as? [String: String], ["id": "project-1"])
        XCTAssertEqual(body["tags"] as? [[String: String]], [["id": "tag-1"]])
    }

    @MainActor
    func testEditorPatchesFieldsBeforeMovingState() async throws {
        resetStub()
        let patched = #"{"id":"task-1","title":"Call Alex tomorrow","details":null,"state":"next","revision":4}"#
        let moved = #"{"id":"task-1","title":"Call Alex tomorrow","details":null,"state":"waiting","revision":5,"waiting_for":"Alex to reply"}"#
        StubURLProtocol.responses = [
            "/api/tasks/task-1": (200, Data(patched.utf8), [:]),
            "/api/tasks/task-1/transitions": (200, Data(moved.utf8), [:]),
            "/api/tasks": (200, Data(#"{"items":[],"next_cursor":null,"has_more":false}"#.utf8), [:]),
        ]
        let original = BrainBuddyTask(id: "task-1", title: "Call Alex", details: nil, state: "next", revision: 3)
        let model = BrainBuddyModel(api: client())

        let saved = await model.saveTask(
            original,
            changes: TaskChanges(title: .set("Call Alex tomorrow"), waitingFor: .set("Alex to reply")),
            destinationState: .waiting
        )

        XCTAssertTrue(saved)
        let mutations = StubURLProtocol.requests.enumerated().filter { _, request in
            request.httpMethod == "PATCH" || request.httpMethod == "POST"
        }
        XCTAssertEqual(mutations.map { $0.element.httpMethod }, ["PATCH", "POST"])
        let patch = try XCTUnwrap(JSONSerialization.jsonObject(with: StubURLProtocol.requestBodies[mutations[0].offset]) as? [String: Any])
        XCTAssertEqual(patch["expected_revision"] as? Int, 3)
        XCTAssertNil(patch["waiting_for"])
        let transition = try XCTUnwrap(JSONSerialization.jsonObject(with: StubURLProtocol.requestBodies[mutations[1].offset]) as? [String: Any])
        XCTAssertEqual(transition["expected_revision"] as? Int, 4)
        XCTAssertEqual(transition["waiting_for"] as? String, "Alex to reply")
    }

    @MainActor
    func testRevisionConflictLoadsCurrentTaskAndRetriesWithNewRevisionAndKey() async throws {
        resetStub()
        let current = Data(#"{"id":"task-1","title":"Server title","state":"next","revision":4}"#.utf8)
        let saved = Data(#"{"id":"task-1","title":"My title","state":"next","revision":5}"#.utf8)
        StubURLProtocol.methodResponses = [
            "PATCH /api/tasks/task-1": (409, Data(#"{"message":"Stale revision"}"#.utf8), [:]),
            "GET /api/tasks/task-1": (200, current, [:]),
        ]
        StubURLProtocol.responses["/api/tasks"] = (
            200, Data(#"{"items":[],"next_cursor":null,"has_more":false}"#.utf8), [:]
        )
        let original = BrainBuddyTask(id: "task-1", title: "Old title", details: nil, state: "next", revision: 3)
        let model = BrainBuddyModel(api: client())
        let changes = TaskChanges(title: .set("My title"))

        let firstSucceeded = await model.saveTask(original, changes: changes, destinationState: nil)
        XCTAssertFalse(firstSucceeded)
        XCTAssertEqual(model.syncConflictTaskID, "task-1")
        XCTAssertTrue(model.syncConflictCurrentLoaded)
        XCTAssertEqual(model.taskDetails["task-1"]?.title, "Server title")

        StubURLProtocol.methodResponses["PATCH /api/tasks/task-1"] = (200, saved, [:])
        let latest = try XCTUnwrap(model.taskDetails["task-1"])
        let retrySucceeded = await model.saveTask(latest, changes: changes, destinationState: nil)

        XCTAssertTrue(retrySucceeded)
        XCTAssertNil(model.syncConflictTaskID)
        let patches = StubURLProtocol.requests.enumerated().filter { $0.element.httpMethod == "PATCH" }
        XCTAssertEqual(patches.count, 2)
        let patchBodies = try patches.map { entry in
            try XCTUnwrap(JSONSerialization.jsonObject(
                with: StubURLProtocol.requestBodies[entry.offset]
            ) as? [String: Any])
        }
        XCTAssertEqual(patchBodies.map { $0["expected_revision"] as? Int }, [3, 4])
        XCTAssertNotEqual(
            patches[0].element.value(forHTTPHeaderField: "Idempotency-Key"),
            patches[1].element.value(forHTTPHeaderField: "Idempotency-Key")
        )
    }

    @MainActor
    func testUncertainSaveReusesKeyOnlyWhilePayloadIsUnchanged() async throws {
        resetStub()
        StubURLProtocol.methodResponses["PATCH /api/tasks/task-1"] = (
            503, Data(#"{"message":"Temporarily unavailable"}"#.utf8), [:]
        )
        let original = BrainBuddyTask(id: "task-1", title: "Old title", details: nil, state: "next", revision: 3)
        let model = BrainBuddyModel(api: client())

        _ = await model.saveTask(original, changes: TaskChanges(title: .set("First draft")), destinationState: nil)
        _ = await model.saveTask(original, changes: TaskChanges(title: .set("First draft")), destinationState: nil)
        _ = await model.saveTask(original, changes: TaskChanges(title: .set("Revised draft")), destinationState: nil)

        let keys = StubURLProtocol.requests.compactMap {
            $0.httpMethod == "PATCH" ? $0.value(forHTTPHeaderField: "Idempotency-Key") : nil
        }
        XCTAssertEqual(keys.count, 3)
        XCTAssertEqual(keys[0], keys[1])
        XCTAssertNotEqual(keys[1], keys[2])
    }

    @MainActor
    func testUncertainNestedEditReusesIdempotencyKey() async throws {
        resetStub()
        StubURLProtocol.statusCode = 503
        StubURLProtocol.body = Data(#"{"message":"Temporarily unavailable"}"#.utf8)
        let model = BrainBuddyModel(api: client())
        let subtask = BrainBuddySubtask(id: "sub-1", title: "Draft", state: "open", order_key: 0, revision: 2)
        let comment = BrainBuddyComment(
            id: "comment-1", body: "Old", actor_id: "owner-1", created_at: "2026-09-25T00:00:00Z",
            edited_at: nil, revision: 3
        )

        _ = await model.renameSubtask(subtask, in: "task-1", title: "New")
        _ = await model.renameSubtask(subtask, in: "task-1", title: "New")
        _ = await model.editComment(comment, in: "task-1", body: "Revised")
        _ = await model.editComment(comment, in: "task-1", body: "Revised")

        let keys = StubURLProtocol.requests.compactMap { request in
            request.httpMethod == "PATCH" ? request.value(forHTTPHeaderField: "Idempotency-Key") : nil
        }
        XCTAssertEqual(keys.count, 4)
        XCTAssertEqual(keys[0], keys[1])
        XCTAssertEqual(keys[2], keys[3])
        XCTAssertNotEqual(keys[1], keys[2])
    }

    @MainActor
    func testReopenRequiresDestinationAndWaitingValueAndKeysFollowPayload() async throws {
        resetStub()
        StubURLProtocol.statusCode = 503
        StubURLProtocol.body = Data(#"{"message":"Temporarily unavailable"}"#.utf8)
        let model = BrainBuddyModel(api: client())
        let task = BrainBuddyTask(id: "task-1", title: "Get reply", details: nil, state: "completed", revision: 3)

        let invalidReopen = await model.reopenTask(task, to: .waiting, waitingFor: " ")
        XCTAssertFalse(invalidReopen)
        XCTAssertTrue(StubURLProtocol.requests.isEmpty)
        _ = await model.reopenTask(task, to: .waiting, waitingFor: "Alex")
        _ = await model.reopenTask(task, to: .waiting, waitingFor: "Alex")
        _ = await model.reopenTask(task, to: .next, waitingFor: nil)

        let requests = StubURLProtocol.requests
        XCTAssertEqual(requests.count, 3)
        let keys = requests.compactMap { $0.value(forHTTPHeaderField: "Idempotency-Key") }
        XCTAssertEqual(keys[0], keys[1])
        XCTAssertNotEqual(keys[1], keys[2])
        let bodies = try StubURLProtocol.requestBodies.map {
            try XCTUnwrap(JSONSerialization.jsonObject(with: $0) as? [String: Any])
        }
        XCTAssertEqual(bodies.map { $0["to_state"] as? String }, ["waiting", "waiting", "next"])
        XCTAssertEqual(bodies[0]["waiting_for"] as? String, "Alex")
        XCTAssertNil(bodies[2]["waiting_for"])
    }

    @MainActor
    func testSmartAddKeyChangesWithDestinationContext() async throws {
        resetStub()
        StubURLProtocol.statusCode = 503
        StubURLProtocol.body = Data(#"{"message":"Temporarily unavailable"}"#.utf8)
        let model = BrainBuddyModel(api: client())
        model.draft = "Email insurer"
        model.destination = .project("project-1")
        await model.createTask()
        await model.createTask()
        model.destination = .tag("tag-1")
        await model.createTask()

        let keys = StubURLProtocol.requests.compactMap { request in
            request.url?.path == "/api/tasks/smart-add" ? request.value(forHTTPHeaderField: "Idempotency-Key") : nil
        }
        XCTAssertEqual(keys.count, 3)
        XCTAssertEqual(keys[0], keys[1])
        XCTAssertNotEqual(keys[1], keys[2])
    }

    @MainActor
    func testSubtaskConflictFetchesCurrentRevisionForRetry() async throws {
        resetStub()
        let current = Data(#"{"id":"task-1","title":"Parent","state":"next","revision":4,"subtasks":[{"id":"sub-1","title":"Server edit","state":"open","order_key":0,"revision":3}]}"#.utf8)
        StubURLProtocol.methodResponses = [
            "PATCH /api/tasks/task-1/subtasks/sub-1": (409, Data(#"{"message":"Stale revision"}"#.utf8), [:]),
            "GET /api/tasks/task-1": (200, current, [:]),
        ]
        let model = BrainBuddyModel(api: client())
        let old = BrainBuddySubtask(id: "sub-1", title: "Old", state: "open", order_key: 0, revision: 2)

        let conflicted = await model.renameSubtask(old, in: "task-1", title: "My edit")
        XCTAssertFalse(conflicted)
        XCTAssertEqual(model.taskDetails["task-1"]?.subtasks.first?.revision, 3)
        XCTAssertTrue(model.error?.contains("Subtask changed elsewhere") == true)

        StubURLProtocol.methodResponses["PATCH /api/tasks/task-1/subtasks/sub-1"] = (
            200, Data(#"{"id":"sub-1","title":"My edit","state":"open","order_key":0,"revision":4}"#.utf8), [:]
        )
        let latest = try XCTUnwrap(model.taskDetails["task-1"]?.subtasks.first)
        let retried = await model.renameSubtask(latest, in: "task-1", title: "My edit")
        XCTAssertTrue(retried)
        let patches = StubURLProtocol.requests.enumerated().filter { $0.element.httpMethod == "PATCH" }
        let revisions = try patches.map { entry in
            let payload = try XCTUnwrap(JSONSerialization.jsonObject(with: StubURLProtocol.requestBodies[entry.offset]) as? [String: Any])
            return payload["expected_revision"] as? Int
        }
        XCTAssertEqual(revisions, [2, 3])
        XCTAssertNotEqual(
            patches[0].element.value(forHTTPHeaderField: "Idempotency-Key"),
            patches[1].element.value(forHTTPHeaderField: "Idempotency-Key")
        )
    }

    @MainActor
    func testCommentConflictLoadsCurrentRevisionWithoutDroppingDraft() async throws {
        resetStub()
        StubURLProtocol.methodResponses = [
            "PATCH /api/tasks/task-1/comments/comment-1": (409, Data(#"{"message":"Stale revision"}"#.utf8), [:]),
            "GET /api/tasks/task-1": (200, Data(#"{"id":"task-1","title":"Parent","state":"next","revision":4,"comments":[{"id":"comment-1","body":"Server edit","actor_id":"owner-1","created_at":"2026-09-25T00:00:00Z","edited_at":null,"revision":3}]}"#.utf8), [:]),
        ]
        let model = BrainBuddyModel(api: client())
        let old = BrainBuddyComment(
            id: "comment-1", body: "Old", actor_id: "owner-1",
            created_at: "2026-09-25T00:00:00Z", edited_at: nil, revision: 2
        )

        let conflicted = await model.editComment(old, in: "task-1", body: "My comment")

        XCTAssertFalse(conflicted)
        XCTAssertEqual(model.taskDetails["task-1"]?.comments.first?.revision, 3)
        XCTAssertTrue(model.error?.contains("Comment changed elsewhere") == true)
    }

    @MainActor
    func testInboxCaptureWithProjectRetainsInboxStateAndOpensProject() async throws {
        resetStub()
        let response = #"{"task":{"id":"task-1","title":"Email insurer","details":null,"state":"inbox","revision":1,"project_id":"project-1"},"project":null,"tags":[],"created":{"project_id":null,"tag_ids":[]}}"#
        StubURLProtocol.responses = [
            "/api/tasks/smart-add": (201, Data(response.utf8), [:]),
            "/api/projects": (200, Data(#"[{"id":"project-1","name":"House move","color":null,"state":"active","revision":1,"open_task_count":1}]"#.utf8), [:]),
            "/api/tags": (200, Data("[]".utf8), [:]),
            "/api/tasks": (200, Data(#"{"items":[],"next_cursor":null,"has_more":false}"#.utf8), [:]),
        ]
        let model = BrainBuddyModel(api: client())
        model.destination = .list(.inbox)
        model.selectedList = .inbox
        model.draft = "Email insurer @\"House move\""
        model.projects = try JSONDecoder().decode([BrainBuddyProject].self, from: StubURLProtocol.responses["/api/projects"]!.body)

        await model.createTask()

        XCTAssertNil(model.error)
        XCTAssertEqual(model.destination, .project("project-1"))
        let index = try XCTUnwrap(StubURLProtocol.requests.firstIndex { $0.url?.path == "/api/tasks/smart-add" })
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: StubURLProtocol.requestBodies[index]) as? [String: Any])
        XCTAssertEqual(body["state"] as? String, "inbox")
        XCTAssertEqual(body["project"] as? [String: String], ["id": "project-1"])
    }

    func testStructuredValidationErrorRetainsMessageAndReference() async throws {
        resetStub()
        StubURLProtocol.statusCode = 422
        StubURLProtocol.body = Data(
            #"{"message":"Request validation failed.","detail":[{"loc":["body","title"]}],"reference_id":"ref-422"}"#.utf8
        )
        StubURLProtocol.headers = ["X-Correlation-ID": "ref-422"]

        do {
            _ = try await client().listTasks(state: .inbox)
            XCTFail("Expected a validation error")
        } catch let error as APIError {
            XCTAssertEqual(error.statusCode, 422)
            XCTAssertEqual(error.referenceID, "ref-422")
            XCTAssertTrue(error.localizedDescription.contains("Request validation failed."))
            XCTAssertTrue(error.localizedDescription.contains("ref-422"))
        }
    }

    @MainActor
    func testExpiredSessionRetainsDraftUntilSameOwnerSignsIn() async throws {
        let savedURL = UserDefaults.standard.object(forKey: "BrainBuddyAPIURL")
        defer { UserDefaults.standard.set(savedURL, forKey: "BrainBuddyAPIURL") }
        resetStub()
        StubURLProtocol.statusCode = 401
        StubURLProtocol.body = Data(#"{"message":"Authentication required.","detail":{"reason":"expired"}}"#.utf8)
        StubURLProtocol.headers = [:]

        let model = BrainBuddyModel(api: client())
        model.serverURL = "https://example.test/api"
        model.account = Account(id: "owner-1", email: "owner@example.test", display_name: nil)
        model.tasks = [BrainBuddyTask(id: "task-1", title: "Private task", details: nil, state: "inbox", revision: 1)]
        model.nextCursor = "next-page"
        model.draft = "Unsent private draft"
        model.waitingForDraft = "Alex to reply"

        await model.reload()

        XCTAssertEqual(model.account?.id, "owner-1")
        XCTAssertTrue(model.sessionExpired)
        XCTAssertEqual(model.tasks.first?.title, "Private task")
        XCTAssertEqual(model.nextCursor, "next-page")
        XCTAssertEqual(model.draft, "Unsent private draft")
        XCTAssertEqual(model.waitingForDraft, "Alex to reply")
        XCTAssertEqual(model.error, "Session expired. Sign in again.")

        StubURLProtocol.responses = [
            "/api/auth/login": (200, Data(#"{"id":"owner-1","email":"owner@example.test","display_name":null}"#.utf8), [:]),
            "/api/tasks": (200, Data(#"{"items":[],"next_cursor":null,"has_more":false}"#.utf8), [:]),
            "/api/projects": (200, Data("[]".utf8), [:]),
            "/api/tags": (200, Data("[]".utf8), [:]),
        ]
        await model.signIn(email: "owner@example.test", password: "test-password")
        XCTAssertEqual(model.account?.id, "owner-1")
        XCTAssertFalse(model.sessionExpired)
        XCTAssertEqual(model.draft, "Unsent private draft")
        XCTAssertEqual(model.waitingForDraft, "Alex to reply")
    }

    @MainActor
    func testOtherAccountDoesNotReceiveSuspendedDraft() async throws {
        let savedURL = UserDefaults.standard.object(forKey: "BrainBuddyAPIURL")
        defer { UserDefaults.standard.set(savedURL, forKey: "BrainBuddyAPIURL") }
        resetStub()
        StubURLProtocol.statusCode = 401
        StubURLProtocol.body = Data(#"{"message":"Authentication required."}"#.utf8)
        let model = BrainBuddyModel(api: client())
        model.serverURL = "https://example.test/api"
        model.account = Account(id: "owner-1", email: "owner@example.test", display_name: nil)
        model.draft = "Only owner one should see this"
        model.waitingForDraft = "Private waiting note"
        await model.reload()

        StubURLProtocol.responses = [
            "/api/auth/login": (200, Data(#"{"id":"owner-2","email":"other@example.test","display_name":null}"#.utf8), [:]),
            "/api/tasks": (200, Data(#"{"items":[],"next_cursor":null,"has_more":false}"#.utf8), [:]),
        ]
        await model.signIn(email: "other@example.test", password: "test-password")
        XCTAssertEqual(model.account?.id, "owner-2")
        XCTAssertTrue(model.draft.isEmpty)
        XCTAssertTrue(model.waitingForDraft.isEmpty)
    }

    @MainActor
    func testSameOwnerIDOnAnotherServerDoesNotReceiveDraft() async throws {
        let savedURL = UserDefaults.standard.object(forKey: "BrainBuddyAPIURL")
        defer { UserDefaults.standard.set(savedURL, forKey: "BrainBuddyAPIURL") }
        resetStub()
        StubURLProtocol.statusCode = 401
        StubURLProtocol.body = Data(#"{"message":"Authentication required."}"#.utf8)
        let model = BrainBuddyModel(api: client())
        model.serverURL = "https://example.test/api"
        model.account = Account(id: "owner-1", email: "owner@example.test", display_name: nil)
        model.draft = "Private to the first server"
        await model.reload()

        StubURLProtocol.responses = [
            "/api/auth/login": (200, Data(#"{"id":"owner-1","email":"owner@example.test","display_name":null}"#.utf8), [:]),
            "/api/tasks": (200, Data(#"{"items":[],"next_cursor":null,"has_more":false}"#.utf8), [:]),
        ]
        model.serverURL = "https://another.test/api"
        await model.signIn(email: "owner@example.test", password: "test-password")
        XCTAssertEqual(model.account?.id, "owner-1")
        XCTAssertTrue(model.draft.isEmpty)
    }

    @MainActor
    func testSignInIsSingleFlight() async throws {
        let savedURL = UserDefaults.standard.object(forKey: "BrainBuddyAPIURL")
        defer { UserDefaults.standard.set(savedURL, forKey: "BrainBuddyAPIURL") }
        resetStub()
        let gate = DispatchSemaphore(value: 0)
        let started = expectation(description: "First login request started")
        StubURLProtocol.delayedPath = "/api/auth/login"
        StubURLProtocol.delayGate = gate
        StubURLProtocol.onDelayedStart = { started.fulfill() }
        StubURLProtocol.loginBodies = [
            Data(#"{"id":"owner-a","email":"a@example.test","display_name":null}"#.utf8),
            Data(#"{"id":"owner-b","email":"b@example.test","display_name":null}"#.utf8),
        ]
        StubURLProtocol.responses = [
            "/api/auth/login": (200, Data(), [:]),
            "/api/tasks": (200, Data(#"{"items":[],"next_cursor":null,"has_more":false}"#.utf8), [:]),
        ]
        let watchdog = DispatchWorkItem { gate.signal(); gate.signal() }
        DispatchQueue.global().asyncAfter(deadline: .now() + 2, execute: watchdog)
        defer { gate.signal(); gate.signal(); watchdog.cancel() }

        let model = BrainBuddyModel(api: client())
        model.serverURL = "https://example.test/api"
        let first = Task { await model.signIn(email: "a@example.test", password: "test-password") }
        await fulfillment(of: [started], timeout: 3)
        await model.signIn(email: "b@example.test", password: "test-password")
        gate.signal()
        await first.value

        XCTAssertEqual(model.account?.id, "owner-a")
    }

    @MainActor
    func testLateSessionRestoreCannotEraseSuccessfulSignIn() async throws {
        let savedURL = UserDefaults.standard.object(forKey: "BrainBuddyAPIURL")
        defer { UserDefaults.standard.set(savedURL, forKey: "BrainBuddyAPIURL") }
        resetStub()
        let gate = DispatchSemaphore(value: 0)
        let started = expectation(description: "Session restore request started")
        StubURLProtocol.delayedPath = "/api/auth/me"
        StubURLProtocol.delayGate = gate
        StubURLProtocol.onDelayedStart = { started.fulfill() }
        StubURLProtocol.responses = [
            "/api/auth/me": (401, Data(#"{"message":"Authentication required."}"#.utf8), [:]),
            "/api/auth/login": (200, Data(#"{"id":"owner-new","email":"new@example.test","display_name":null}"#.utf8), [:]),
            "/api/tasks": (200, Data(#"{"items":[],"next_cursor":null,"has_more":false}"#.utf8), [:]),
        ]
        defer { gate.signal() }

        let model = BrainBuddyModel(api: client())
        model.serverURL = "https://example.test/api"
        let restoreTask = Task { await model.restore() }
        await fulfillment(of: [started], timeout: 3)
        await model.signIn(email: "new@example.test", password: "test-password")
        gate.signal()
        await restoreTask.value

        XCTAssertEqual(model.account?.id, "owner-new")
        XCTAssertNil(model.error)
    }
}
