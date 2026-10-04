import BrainBuddyCore
import Foundation
import Testing

@testable import BrainBuddyAPI

@Suite("GET /tasks query encoding")
struct TaskListQueryTests {
    private func requestedURL(_ query: TaskListQuery, cursor: String? = nil) async throws -> String {
        let transport = ScriptedTransport([Fixture.json(200, Fixture.page([]))])
        _ = try await Fixture.client(transport).listTasks(query, cursor: cursor)
        return try #require(transport.lastRequest).url.absoluteString
    }

    @Test("Every filter, in a fixed order, priority repeated and deduplicated (contracts/api-client-parity.json)")
    func everyFilter() async throws {
        let query = TaskListQuery(
            state: .inbox, projectID: "project-1", tagID: "tag-1", unassignedProject: true, includeCompleted: true,
            includeCancelled: true, search: "  shared  ", priorities: [.high, .medium, .high],
            due: .before(CalendarDay(year: 2026, month: 8, day: 1)!), sort: .due, limit: 25
        )
        let url = try await requestedURL(query, cursor: "page-2")
        #expect(
            url
                == "https://api.example.test/api/tasks?state=inbox&project_id=project-1&tag_id=tag-1&unassigned_project=true&include_completed=true&include_cancelled=true&q=shared&priority=high&priority=medium&due_before=2026-08-01&sort=due&cursor=page-2&limit=25"
        )
    }

    @Test("The full pull asks for every state, manual order, 200 per page")
    func fullPull() async throws {
        let url = try await requestedURL(.fullPull)
        #expect(url == "https://api.example.test/api/tasks?include_completed=true&include_cancelled=true&sort=manual&limit=200")
    }

    @Test("A plus sign in the search is %2B, never a space")
    func plusIsEncoded() async throws {
        let url = try await requestedURL(TaskListQuery(search: "C++ & notes=1 50% #x"))
        #expect(url == "https://api.example.test/api/tasks?q=C%2B%2B%20%26%20notes%3D1%2050%25%20%23x")
    }

    @Test("Non-ASCII search text is UTF-8 percent-encoded")
    func unicodeSearch() async throws {
        let url = try await requestedURL(TaskListQuery(search: "café"))
        #expect(url == "https://api.example.test/api/tasks?q=caf%C3%A9")
    }

    @Test("Blank search and false booleans are omitted")
    func omitsDefaults() async throws {
        let url = try await requestedURL(TaskListQuery(search: " \n "))
        #expect(url == "https://api.example.test/api/tasks")
    }

    @Test("due_on and due_after")
    func dueFilters() async throws {
        let day = CalendarDay(year: 2026, month: 8, day: 2)!
        #expect(try await requestedURL(TaskListQuery(due: .on(day))) == "https://api.example.test/api/tasks?due_on=2026-08-02")
        #expect(
            try await requestedURL(TaskListQuery(due: .after(day))) == "https://api.example.test/api/tasks?due_after=2026-08-02"
        )
    }

    @Test("Terminal state filter and title sort")
    func terminalState() async throws {
        let url = try await requestedURL(TaskListQuery(state: .completed, sort: .title))
        #expect(url == "https://api.example.test/api/tasks?state=completed&sort=title")
    }

    @Test("A cursor is sent verbatim when it is URL-safe base64, escaped otherwise")
    func cursorEncoding() async throws {
        let safe = "eyJmaWx0ZXJzIjp7fSwibGFzdCI6WzAsIjIwMjYiLCJ0YXNrXzEiXX0"
        #expect(try await requestedURL(TaskListQuery(), cursor: safe) == "https://api.example.test/api/tasks?cursor=\(safe)")
        #expect(try await requestedURL(TaskListQuery(), cursor: "a+b/c=") == "https://api.example.test/api/tasks?cursor=a%2Bb%2Fc%3D")
    }

    @Test("The page decodes items, cursor and counts")
    func pageDecodes() async throws {
        let transport = ScriptedTransport([
            Fixture.json(200, Fixture.page([Fixture.task(id: "task_a"), Fixture.task(id: "task_b")], nextCursor: "c1")),
        ])
        let page = try await Fixture.client(transport).listTasks()
        #expect(page.items.map(\.id) == ["task_a", "task_b"])
        #expect(page.nextCursor == "c1")
        #expect(page.hasMore)
        #expect(page.countsByState == TaskCountsDTO(inbox: 1, next: 2, waiting: 3, someday: 4))
        #expect(page.countsByState[.waiting] == 3)
    }

    @Test("listAllTasks follows next_cursor with the same filters")
    func listAllFollowsCursor() async throws {
        let transport = ScriptedTransport([
            Fixture.json(200, Fixture.page([Fixture.task(id: "task_a")], nextCursor: "c1")),
            Fixture.json(200, Fixture.page([Fixture.task(id: "task_b")], nextCursor: "c2")),
            Fixture.json(200, Fixture.page([Fixture.task(id: "task_c")])),
        ])
        let tasks = try await Fixture.client(transport).listAllTasks()

        #expect(tasks.map(\.id) == ["task_a", "task_b", "task_c"])
        let prefix = "https://api.example.test/api/tasks?include_completed=true&include_cancelled=true&sort=manual"
        #expect(transport.requests.map(\.url.absoluteString) == [
            "\(prefix)&limit=200", "\(prefix)&cursor=c1&limit=200", "\(prefix)&cursor=c2&limit=200",
        ])
    }

    @Test("listAllTasks stops instead of looping on a repeated cursor")
    func listAllDetectsLoop() async throws {
        let transport = ScriptedTransport([
            Fixture.json(200, Fixture.page([Fixture.task(id: "task_a")], nextCursor: "c1")),
            Fixture.json(200, Fixture.page([Fixture.task(id: "task_b")], nextCursor: "c1")),
        ])
        let client = Fixture.client(transport)
        let error = await expectAPIError { _ = try await client.listAllTasks() }
        guard case .decoding = error?.kind else {
            Issue.record("Expected a decoding error, got \(String(describing: error))")
            return
        }
        #expect(transport.requests.count == 2)
    }
}
