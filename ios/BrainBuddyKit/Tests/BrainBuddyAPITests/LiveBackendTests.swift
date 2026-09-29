import BrainBuddyCore
import Foundation
import Testing

@testable import BrainBuddyAPI

/// End-to-end contract check against a real, disposable backend through the
/// real `URLSessionTransport`. Skipped unless `BRAINBUDDY_LIVE_API_URL` (for
/// example `http://127.0.0.1:8000/api`) and `BRAINBUDDY_LIVE_INVITE` (from
/// `python -m app.cli create-invite`) are set. Never point it at production:
/// it signs up a new account.
@Suite(
    "Live backend contract",
    .enabled(if: ProcessInfo.processInfo.environment["BRAINBUDDY_LIVE_API_URL"] != nil)
)
struct LiveBackendTests {
    private let environment = ProcessInfo.processInfo.environment

    @Test("Every endpoint against the real server")
    func everyEndpoint() async throws {
        let baseURL = try #require(environment["BRAINBUDDY_LIVE_API_URL"].flatMap(URL.init(string:)))
        let invite = try #require(environment["BRAINBUDDY_LIVE_INVITE"])
        let store = InMemorySessionTokenStore()
        let api = BrainBuddyAPIClient(baseURL: baseURL, tokenStore: store, clientVersion: "live-test")
        let run = UUID().uuidString.prefix(8).lowercased()
        // email-validator rejects special-use TLDs such as `.test`.
        let email = "ios-\(run)@example.com"

        // Account and session.
        let signedUp = try await api.signup(email: email, password: "live-test-password-\(run)", inviteCode: invite)
        #expect(signedUp.email == email)
        #expect(try store.token(for: baseURL) != nil)
        let me = try await api.me()
        #expect(me.id == signedUp.id)
        let wrong = await expectAPIError { _ = try await api.login(email: email, password: "wrong") }
        #expect(wrong?.kind == .unauthorized)
        #expect(wrong?.message == "Invalid email or password.")
        let relogged = try await api.login(email: email, password: "live-test-password-\(run)")
        #expect(relogged.id == me.id)

        // Projects.
        let projectKey = UUID()
        let project = try await api.createProject(name: "Home \(run)", color: "#0EA5E9", idempotencyKey: projectKey)
        let replayed = try await api.createProject(name: "Home \(run)", color: "#0EA5E9", idempotencyKey: projectKey)
        #expect(replayed.id == project.id)
        let duplicate = await expectAPIError {
            _ = try await api.createProject(name: "  home \(run.uppercased()) ", idempotencyKey: UUID())
        }
        #expect(duplicate?.kind == .duplicateName(resource: "Project", name: "home \(run.uppercased())"))
        let reused = await expectAPIError { _ = try await api.createProject(name: "Other", idempotencyKey: projectKey) }
        #expect(reused?.kind == .idempotencyConflict)
        let recoloured = try await api.updateProject(
            id: project.id, color: .clear, expectedRevision: project.revision, idempotencyKey: UUID()
        )
        #expect(recoloured.color == nil)
        #expect(recoloured.name == "Home \(run)")
        let stale = await expectAPIError {
            _ = try await api.updateProject(
                id: project.id, name: "X", expectedRevision: project.revision, idempotencyKey: UUID()
            )
        }
        #expect(stale?.kind == .staleRevision(resource: "Project", id: project.id))

        // Tags.
        let tag = try await api.createTag(name: "@errands-\(run)", idempotencyKey: UUID())
        #expect(tag.name == "errands-\(run)")
        let duplicateTag = await expectAPIError { _ = try await api.createTag(name: "Errands-\(run)", idempotencyKey: UUID()) }
        #expect(duplicateTag?.kind == .duplicateName(resource: "Tag", name: "Errands-\(run)"))
        let renamed = try await api.updateTag(
            id: tag.id, name: "Errands \(run)", expectedRevision: tag.revision, idempotencyKey: UUID()
        )
        #expect(renamed.name == "Errands \(run)")
        #expect(try await api.listTags().contains { $0.id == tag.id })

        // Tasks.
        let due = CalendarDay(year: 2026, month: 12, day: 24)!
        let created = try await api.createTask(
            TaskCreateBody(
                title: "C++ review \(run)", details: "Read chapter 3", state: .next, projectID: project.id,
                tagIDs: [tag.id], dueDate: due, priority: .high
            ),
            idempotencyKey: UUID()
        )
        #expect(created.state == .next)
        #expect(created.projectID == project.id)
        #expect(created.tagIDs == [tag.id])
        #expect(created.dueDate == due)
        #expect(created.priority == .high)
        #expect(abs(created.createdAt.timeIntervalSinceNow) < 300)

        let edited = try await api.updateTask(
            id: created.id,
            TaskUpdateBody(expectedRevision: created.revision, details: .clear, dueDate: .clear, priority: .set(.low)),
            idempotencyKey: UUID()
        )
        #expect(edited.details == nil)
        #expect(edited.dueDate == nil)
        #expect(edited.priority == .low)
        #expect(edited.title == created.title)
        #expect(edited.projectID == project.id)
        let staleTask = await expectAPIError {
            _ = try await api.updateTask(
                id: created.id, TaskUpdateBody(expectedRevision: created.revision, title: .set("x")),
                idempotencyKey: UUID()
            )
        }
        #expect(staleTask?.kind == .staleRevision(resource: "Task", id: created.id))
        let nullTitle = await expectAPIError {
            _ = try await api.updateTask(
                id: created.id, TaskUpdateBody(expectedRevision: edited.revision, title: .clear), idempotencyKey: UUID()
            )
        }
        #expect(nullTitle?.kind == .rejected)
        #expect(nullTitle?.message == "Task title cannot be null.")

        let waiting = try await api.transitionTask(
            id: created.id,
            TaskTransitionBody(action: .move, toState: .waiting, waitingFor: "Sam", expectedRevision: edited.revision),
            idempotencyKey: UUID()
        )
        #expect(waiting.state == .waiting)
        #expect(waiting.waitingFor == "Sam")
        #expect(waiting.waitingSince != nil)
        let completed = try await api.transitionTask(
            id: created.id, TaskTransitionBody(action: .complete, expectedRevision: waiting.revision),
            idempotencyKey: UUID()
        )
        #expect(completed.state == .completed)
        #expect(completed.completedAt != nil)
        #expect(completed.waitingFor == nil)

        // Subtasks and comments.
        let subtask = try await api.createSubtask(taskID: created.id, title: "Chapter 3", idempotencyKey: UUID())
        let retitled = try await api.updateSubtask(
            taskID: created.id, subtaskID: subtask.id, title: "Chapter 3 and 4", expectedRevision: subtask.revision,
            idempotencyKey: UUID()
        )
        let done = try await api.transitionSubtask(
            taskID: created.id, subtaskID: subtask.id, action: .complete, expectedRevision: retitled.revision,
            idempotencyKey: UUID()
        )
        #expect(done.state == .completed)
        let comment = try await api.createComment(taskID: created.id, body: "Great + useful", idempotencyKey: UUID())
        let rewritten = try await api.updateComment(
            taskID: created.id, commentID: comment.id, body: "Great", expectedRevision: comment.revision,
            idempotencyKey: UUID()
        )
        #expect(rewritten.editedAt != nil)
        let detail = try await api.getTask(id: created.id)
        #expect(detail.subtasks.map(\.title) == ["Chapter 3 and 4"])
        #expect(detail.comments.map(\.body) == ["Great"])
        #expect(detail.revision == completed.revision)

        // Listing: search with "+", paging with a cursor.
        let second = try await api.createTask(TaskCreateBody(title: "Second \(run)", state: .inbox), idempotencyKey: UUID())
        let found = try await api.listTasks(TaskListQuery(includeCompleted: true, search: "c++ REVIEW \(run)"))
        #expect(found.items.map(\.id) == [created.id])
        var paged = TaskListQuery.fullPull
        paged.limit = 1
        let all = try await api.listAllTasks(paged)
        #expect(Set(all.map(\.id)) == [created.id, second.id])

        // Archive, delete, not found.
        let archived = try await api.archiveProject(id: project.id, expectedRevision: recoloured.revision, idempotencyKey: UUID())
        #expect(archived.state == .archived)
        #expect(try await api.getProject(id: project.id).state == .archived)
        #expect(try await !api.listProjects().contains { $0.id == project.id })
        let deleted = try await api.deleteTag(id: tag.id, expectedRevision: renamed.revision, idempotencyKey: UUID())
        #expect(deleted.state == .deleted)
        let missing = await expectAPIError { _ = try await api.getTask(id: "task_000000000000") }
        #expect(missing?.kind == .notFound(resource: "Task", id: "task_000000000000"))
        #expect(missing?.referenceID != nil)

        // Sign out.
        try await api.logout()
        #expect(try store.token(for: baseURL) == nil)
        let signedOut = await expectAPIError { _ = try await api.me() }
        #expect(signedOut?.kind == .unauthorized)
    }
}
