import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyFakeServer
import Foundation
import Testing

/// The fake server behaves like `backend/app/api/tasks.py` where the sync
/// engine depends on it; checked through the real API client.
@Suite("FakeBrainBuddyServer")
struct FakeBrainBuddyServerTests {
    let clock = ManualClock()
    let server: FakeBrainBuddyServer
    let transport: FakeServerTransport
    let client: BrainBuddyAPIClient

    init() async throws {
        server = FakeBrainBuddyServer(now: clock.provider)
        server.addAccount(email: "ada@example.com", password: "secret", displayName: "Ada")
        transport = server.makeTransport()
        client = BrainBuddyAPIClient(
            baseURL: FakeBrainBuddyServer.baseURL, transport: transport, tokenStore: InMemorySessionTokenStore(),
            clientVersion: "test"
        )
        _ = try await client.login(email: "ada@example.com", password: "secret")
    }

    private func apiError(_ body: () async throws -> Void) async -> APIError? {
        do {
            try await body()
            return nil
        } catch let error as APIError {
            return error
        } catch {
            return nil
        }
    }

    @Test("Sessions: login sets the cookie, task routes need it, logout ends it")
    func sessions() async throws {
        #expect(try await client.me().displayName == "Ada")
        let stranger = BrainBuddyAPIClient(
            baseURL: FakeBrainBuddyServer.baseURL, transport: transport, tokenStore: InMemorySessionTokenStore()
        )
        #expect(await apiError { _ = try await stranger.listTasks() }?.kind == .unauthorized)
        let wrong = await apiError { _ = try await stranger.login(email: "ada@example.com", password: "nope") }
        #expect(wrong?.kind == .unauthorized)
        #expect(wrong?.message == "Invalid email or password.")
        try await client.logout()
        #expect(try client.hasStoredSession() == false)
        #expect(await apiError { _ = try await client.me() }?.kind == .unauthorized)
    }

    @Test("Ids are minted by the server; revisions go up by one and must match exactly")
    func revisions() async throws {
        let key = UUID()
        let task = try await client.createTask(TaskCreateBody(title: "Buy milk", state: .inbox), idempotencyKey: key)
        #expect(task.id.wholeMatch(of: /task_[0-9a-f]{12}/) != nil)
        #expect(task.revision == 1)
        let moved = try await client.transitionTask(
            id: task.id, TaskTransitionBody(action: .move, toState: .next, expectedRevision: 1), idempotencyKey: UUID()
        )
        #expect(moved.revision == 2)
        #expect(moved.orderKey == task.orderKey, "transitions keep the order key")
        let stale = await apiError {
            let body = TaskUpdateBody(expectedRevision: 1, priority: .set(.high))
            _ = try await client.updateTask(id: task.id, body, idempotencyKey: UUID())
        }
        #expect(stale?.kind == .staleRevision(resource: "Task", id: task.id))
        let rejected = await apiError {
            let body = TaskUpdateBody(expectedRevision: 2, waitingFor: .set("Bob"))
            _ = try await client.updateTask(id: task.id, body, idempotencyKey: UUID())
        }
        #expect(rejected?.kind == .rejected)
        #expect(rejected?.message == "waiting_for can only be edited on Waiting tasks.")
    }

    @Test("Idempotency: same key and body replays, another body conflicts, keys expire after 24 hours")
    func idempotency() async throws {
        let key = UUID()
        let first = try await client.createTask(TaskCreateBody(title: "Buy milk", state: .inbox), idempotencyKey: key)
        let replay = try await client.createTask(TaskCreateBody(title: "Buy milk", state: .inbox), idempotencyKey: key)
        #expect(replay == first)
        #expect(server.snapshot(email: "ada@example.com").tasks.count == 1)
        let conflict = await apiError {
            _ = try await client.createTask(TaskCreateBody(title: "Buy bread", state: .inbox), idempotencyKey: key)
        }
        #expect(conflict?.kind == .idempotencyConflict)

        clock.advance(by: 24 * 3600 + 1)
        let later = try await client.createTask(TaskCreateBody(title: "Buy milk", state: .inbox), idempotencyKey: key)
        #expect(later.id != first.id, "the expired key no longer protects the create")
        #expect(server.idempotencyKeyCount(email: "ada@example.com") == 1)
    }

    @Test("Active names are unique after normalization; archived names are free again")
    func uniqueNames() async throws {
        let work = try await client.createProject(name: "Work", idempotencyKey: UUID())
        let duplicate = await apiError { _ = try await client.createProject(name: "  WORK ", idempotencyKey: UUID()) }
        #expect(duplicate?.kind == .duplicateName(resource: "Project", name: "WORK"))
        let tag = try await client.createTag(name: "@Home", idempotencyKey: UUID())
        #expect(tag.name == "Home")
        #expect(await apiError { _ = try await client.createTag(name: "home", idempotencyKey: UUID()) }?.kind
            == .duplicateName(resource: "Tag", name: "home"))
        _ = try await client.archiveProject(id: work.id, expectedRevision: 1, idempotencyKey: UUID())
        let again = try await client.createProject(name: "work", idempotencyKey: UUID())
        #expect(again.id != work.id)
        #expect(try await client.listProjects().map(\.id) == [again.id])
        #expect(try await client.getProject(id: work.id).state == .archived)
    }

    @Test("Tag deletion changes member tasks, archiving keeps them (ADR-0020); subtask and comment edits change nothing")
    func sideEffects() async throws {
        let project = try await client.createProject(name: "Garden", idempotencyKey: UUID())
        let tag = try await client.createTag(name: "outside", idempotencyKey: UUID())
        let task = try await client.createTask(
            TaskCreateBody(title: "Plant tulips", state: .next, projectID: project.id, tagIDs: [tag.id]), idempotencyKey: UUID()
        )
        let subtask = try await client.createSubtask(taskID: task.id, title: "Buy bulbs", idempotencyKey: UUID())
        _ = try await client.updateSubtask(
            taskID: task.id, subtaskID: subtask.id, title: "Buy 40 bulbs", expectedRevision: 1, idempotencyKey: UUID()
        )
        _ = try await client.createComment(taskID: task.id, body: "Before frost.", idempotencyKey: UUID())
        #expect(try await client.getTask(id: task.id).revision == 1)

        _ = try await client.archiveProject(id: project.id, expectedRevision: 1, idempotencyKey: UUID())
        _ = try await client.deleteTag(id: tag.id, expectedRevision: 1, idempotencyKey: UUID())
        let detail = try await client.getTask(id: task.id)
        #expect(detail.projectID == project.id, "an archive leaves the task alone")
        #expect(detail.tagIDs.isEmpty)
        #expect(detail.revision == 2, "only the tag deletion touched it")
        #expect(detail.subtasks.map(\.title) == ["Buy 40 bulbs"])
        #expect(detail.comments.map(\.body) == ["Before frost."])
        let listed = try await client.listAllTasks()
        #expect(listed.first?.subtasks.isEmpty == true, "list items carry no children")
        let referencing = await apiError {
            let body = TaskCreateBody(title: "Rake", state: .next, projectID: project.id)
            _ = try await client.createTask(body, idempotencyKey: UUID())
        }
        #expect(referencing?.message == "Task project must be active.")
    }

    @Test("Task pages follow an opaque cursor bound to the filters")
    func pagination() async throws {
        for index in 0..<5 {
            _ = try await client.createTask(TaskCreateBody(title: "Task \(index)", state: .inbox), idempotencyKey: UUID())
        }
        let query = TaskListQuery(limit: 2)
        var titles: [String] = []
        var cursor: String?
        var pages = 0
        repeat {
            let page = try await client.listTasks(query, cursor: cursor)
            titles += page.items.map(\.title)
            cursor = page.nextCursor
            pages += 1
            #expect(page.countsByState.inbox == 5)
        } while cursor != nil
        #expect(pages == 3)
        #expect(titles == (0..<5).map { "Task \($0)" })

        let first = try await client.listTasks(query)
        let mismatched = await apiError {
            _ = try await client.listTasks(TaskListQuery(sort: .title, limit: 2), cursor: first.nextCursor)
        }
        #expect(mismatched?.message == "Invalid or mismatched task cursor.")
    }

    @Test("A replayed subtask edit answers with the current subtask")
    func replaysCurrentChild() async throws {
        let task = try await client.createTask(TaskCreateBody(title: "Pack", state: .next), idempotencyKey: UUID())
        let subtask = try await client.createSubtask(taskID: task.id, title: "Socks", idempotencyKey: UUID())
        let key = UUID()
        _ = try await client.updateSubtask(
            taskID: task.id, subtaskID: subtask.id, title: "Wool socks", expectedRevision: 1, idempotencyKey: key
        )
        _ = try await client.transitionSubtask(
            taskID: task.id, subtaskID: subtask.id, action: .complete, expectedRevision: 2, idempotencyKey: UUID()
        )
        let replay = try await client.updateSubtask(
            taskID: task.id, subtaskID: subtask.id, title: "Wool socks", expectedRevision: 1, idempotencyKey: key
        )
        #expect(replay.revision == 3)
        #expect(replay.state == .completed)
    }

    @Test("Injected faults: nothing applied, applied then lost, or an HTTP error")
    func faults() async throws {
        transport.inject(.offline, matching: FakeServerTransport.isMutation)
        let offline = await apiError { _ = try await client.createProject(name: "A", idempotencyKey: UUID()) }
        #expect(offline?.requestMayHaveBeenSent == false)
        transport.inject(.dropResponse)
        let lost = await apiError { _ = try await client.createProject(name: "B", idempotencyKey: UUID()) }
        #expect(lost?.isUncertainOutcome == true)
        transport.inject(.status(503))
        #expect(await apiError { _ = try await client.listProjects() }?.kind == .server)
        #expect(try await client.listProjects().map(\.name) == ["B"])
        #expect(transport.exchanges.dropFirst().map(\.fault) == [.offline, .dropResponse, .status(503), nil], "after the login")
    }
}
