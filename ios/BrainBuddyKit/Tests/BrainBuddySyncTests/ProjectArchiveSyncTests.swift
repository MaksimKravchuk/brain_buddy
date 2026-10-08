import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyFakeServer
import Foundation
import Testing

@testable import BrainBuddySync

@Suite("SyncEngine: archive, unarchive, desired outcome and issue copy (spec 021)")
struct ProjectArchiveSyncTests {
    /// Two devices on one account; A made and synced project "Shed" holding the task "Dig".
    private func shed() async throws -> (harness: SyncHarness, a: Device, b: Device) {
        let harness = SyncHarness()
        let a = await harness.device()
        try await a.signIn()
        try await a.apply(.createProject(.init(projectID: "shed", name: "Shed", desiredOutcome: "A shed that stands")))
        try await a.apply(.createTask(.init(taskID: "dig", title: "Dig", list: .next, projectID: "shed")))
        await a.sync()
        let b = await harness.device()
        try await b.signIn()
        return (harness, a, b)
    }

    @Test("021-FR-024 021-FR-026 an archive keeps the task's project everywhere, and an unarchive reaches the other device")
    func archiveAndUnarchiveRoundTrip() async throws {
        let (harness, a, b) = try await shed()
        let revision = try #require(harness.snapshot.task(titled: "Dig")).revision
        try await a.apply(.archiveProject("shed"))
        a.transport.clearLog()
        await a.sync()
        #expect(a.mutations.map(\.route).count == 1)

        let server = harness.snapshot
        let project = try #require(server.project(named: "Shed"))
        #expect(project.state == .archived && project.archivedAt != nil && !project.archivedBeforeLossless)
        #expect(server.task(titled: "Dig")?.projectID == project.id && server.task(titled: "Dig")?.revision == revision)

        await b.sync()
        let archived = try await b.current()
        let onB = try #require(archived.project(named: "Shed"))
        #expect(onB.state == .archived && onB.archivedAt != nil && onB.desiredOutcome == "A shed that stands")
        #expect(archived.task(titled: "Dig")?.projectID == onB.id, "the membership survives the pull")

        try await a.apply(.unarchiveProject(project: "shed"))
        await a.sync()
        #expect(harness.snapshot.project(named: "Shed")?.state == .active)
        await b.sync()
        let restored = try await b.current().project(named: "Shed")
        #expect(restored?.state == .active && restored?.archivedAt == nil)
    }

    @Test("021-FR-024 a pull includes an archived project that no task references, in one listing")
    func pullIncludesArchivedProjectsWithoutTasks() async throws {
        let harness = SyncHarness()
        let a = await harness.device()
        try await a.signIn()
        try await a.apply(.createProject(.init(projectID: "empty", name: "Empty")))
        try await a.apply(.archiveProject("empty"))
        await a.sync()
        let b = await harness.device()
        b.transport.clearLog()
        try await b.signIn()
        #expect(try await b.current().project(named: "Empty")?.state == .archived)
        let reads = b.transport.requests.map(\.route).filter { $0.hasPrefix("GET /projects") }
        #expect(reads == ["GET /projects"], "a single listing (the query is not part of the route)")
        #expect(b.transport.requests.contains { $0.url.query == "state=all" })
    }

    @Test("021-FR-024 against a server that ignores ?state= the per-id fallback still fetches a referenced archived project")
    func perIDFallback() async throws {
        let (harness, a, b) = try await shed()
        try await a.apply(.archiveProject("shed"))
        await a.sync()
        b.transport.clearLog()
        let older = LegacyProjectsServer(inner: b.transport, ignoresState: true)
        let engine = SyncEngine(
            store: b.store, tokenStore: b.tokens, transport: older, now: harness.clock.provider,
            configuration: SyncConfiguration(scheduler: ManualSyncScheduler(), jitter: { 0.5 }, clientVersion: "test")
        )
        await engine.start(account: try #require(try await b.document().account))
        await engine.waitUntilIdle()
        _ = await engine.syncNow()
        let base = try await b.document().base
        let project = try #require(base.project(named: "Shed"))
        #expect(project.state == .archived)
        #expect(base.task(titled: "Dig")?.projectID == project.id)
        #expect(b.transport.requests.contains { $0.route.hasPrefix("GET /projects/project_") }, "fetched by id")
    }

    @Test("021-FR-011 021-FR-026 an unarchive refused for a name taken meanwhile reverts at once; the capture behind it is kept without the project under one issue")
    func unarchiveNameClash() async throws {
        let (harness, a, b) = try await shed()
        try await a.apply(.archiveProject("shed"))
        await a.sync()
        await b.sync()
        // B makes an active "Shed" while A, offline from it, unarchives its own.
        try await b.apply(.createProject(.init(projectID: "twin", name: "Shed")))
        await b.sync()
        try await a.apply(.unarchiveProject(project: "shed"))
        try await a.apply(.createTask(.init(taskID: "tools", title: "Buy tools", list: .inbox, projectID: "shed")))
        a.transport.clearLog()
        await a.sync()

        let exchanges = a.transport.exchanges
        #expect(exchanges.compactMap(\.statusCode).filter { $0 == 400 }.isEmpty, "no 400 for the capture")
        let document = try await a.document()
        #expect(document.outbox.isEmpty)
        let issue = try #require(document.issues.first)
        #expect(document.issues.count == 1 && issue.command == .unarchiveProject(project: "shed"))
        #expect(
            issue.message
                == "Another active project is already called “Shed”. 1 task you added to it was kept without a project."
        )
        #expect(issue.referenceID != nil)
        let current = try await a.current()
        #expect(current.projects["shed"]?.state == .archived, "reverted at once, not at the next pull")
        #expect(current.task(titled: "Buy tools")?.projectID == nil)
        #expect(harness.snapshot.task(titled: "Buy tools")?.projectID == nil)
        #expect(current.task(titled: "Dig")?.projectID == "shed", "the archived project still holds what it held")
    }

    @Test("021-FR-024 021-FR-011 a server that still clears on archive raises one issue instead of letting the next pull strip memberships")
    func clearingServerGuard() async throws {
        let (harness, a, _) = try await shed()
        try await a.apply(.archiveProject("shed"))
        let older = LegacyProjectsServer(inner: a.transport, clearsOnArchive: true)
        let engine = SyncEngine(
            store: a.store, tokenStore: a.tokens, transport: older, now: harness.clock.provider,
            configuration: SyncConfiguration(scheduler: ManualSyncScheduler(), jitter: { 0.5 }, clientVersion: "test")
        )
        await engine.start(account: try #require(try await a.document().account))
        await engine.waitUntilIdle()
        _ = await engine.syncNow()
        let issues = try await a.document().issues
        #expect(issues.count == 1)
        #expect(issues.first?.command == .archiveProject("shed"))
        #expect(
            issues.first?.message
                == "Your account's server is out of date, so archiving “Shed” removed its tasks from the project."
        )
    }

    @Test("021-FR-028 a desired outcome goes out as a PATCH, and a 409 stale revision is refetched, replayed and resent")
    func outcomeConflict() async throws {
        let (harness, a, b) = try await shed()
        await b.sync()
        let projectOnB = try #require(try await b.current().project(named: "Shed")).id
        try await a.apply(.setProjectOutcome(project: "shed", outcome: "  Done by spring "))
        await a.sync()
        #expect(harness.snapshot.project(named: "Shed")?.desiredOutcome == "Done by spring")
        #expect(a.mutations.last?.bodyText.contains(#""desired_outcome":"Done by spring""#) == true)

        // B edits from the revision it knows: stale.
        try await b.apply(.setProjectOutcome(project: projectOnB, outcome: "Done by summer"))
        b.transport.clearLog()
        await b.sync()
        #expect(b.transport.exchanges.compactMap(\.statusCode).contains(409))
        #expect(harness.snapshot.project(named: "Shed")?.desiredOutcome == "Done by summer")
        let document = try await b.document()
        #expect(document.outbox.isEmpty && document.issues.isEmpty)

        try await b.apply(.setProjectOutcome(project: projectOnB, outcome: nil))
        await b.sync()
        #expect(harness.snapshot.project(named: "Shed")?.desiredOutcome == nil, "null clears it")
    }

    @Test("021-FR-011 021-FR-015 a task edit the server answers 404 becomes an issue that says the task was deleted elsewhere, with the reference id")
    func deletedElsewhereCopy() async throws {
        let (_, a, _) = try await shed()
        try await a.apply(.updateTask(.init(taskID: "dig", changes: .init(title: .set("Dig deeper")))))
        a.transport.inject(.status(404), matching: FakeServerTransport.path("tasks", method: .patch))
        await a.sync()
        let issue = try #require(try await a.document().issues.first)
        #expect(issue.message == "Couldn't save your change to “Dig”: it was deleted on another device.")
        #expect(issue.referenceID != nil)
    }
}

/// An older server in front of the fake: one that ignores `?state=` on the project list
/// (before spec 021) and one that still clears on archive (before ADR-0020).
final class LegacyProjectsServer: HTTPTransport {
    let inner: FakeServerTransport
    let ignoresState: Bool
    let clearsOnArchive: Bool

    init(inner: FakeServerTransport, ignoresState: Bool = false, clearsOnArchive: Bool = false) {
        self.inner = inner
        self.ignoresState = ignoresState
        self.clearsOnArchive = clearsOnArchive
    }

    func send(_ request: HTTPRequest) async throws -> HTTPResponse {
        var request = request
        if ignoresState, request.method == .get, request.url.path.hasSuffix("/projects"),
            var components = URLComponents(url: request.url, resolvingAgainstBaseURL: false)
        {
            components.queryItems = nil
            request.url = components.url ?? request.url
        }
        let response = try await inner.send(request)
        guard clearsOnArchive, request.method == .post, request.url.path.hasSuffix("/archive"),
            var project = (try? JSONSerialization.jsonObject(with: response.body)) as? [String: Any]
        else { return response }
        project["archived_before_lossless"] = true
        project["archived_at"] = NSNull()
        var changed = response
        changed.body = (try? JSONSerialization.data(withJSONObject: project)) ?? response.body
        return changed
    }
}
