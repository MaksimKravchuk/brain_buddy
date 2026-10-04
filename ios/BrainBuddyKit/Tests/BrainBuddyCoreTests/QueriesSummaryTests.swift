import Foundation
import Testing

@testable import BrainBuddyCore

@Suite("Queries › counts, projects and tags")
struct QueriesSummaryTests {
    @Test("Counts: projectless Inbox, every project for the other lists, overdue and today over open tasks")
    func counts() {
        var fixture = QueryFixture()
        let home = fixture.project("Home")
        fixture.task("Loose inbox", .inbox, due: "2026-09-01")
        fixture.task("Project inbox", .inbox, project: home, due: "2026-09-29")
        fixture.task("Next 1", .next, due: "2026-09-29")
        fixture.task("Next 2", .next, project: home)
        fixture.task("Waiting", .waiting, due: "2026-09-30")
        fixture.task("Someday 1", .someday)
        fixture.task("Someday 2", .someday, project: home, due: "2025-01-01")
        fixture.task("Done overdue", .completed, from: .next, due: "2026-09-01")
        fixture.task("Dropped today", .cancelled, from: .inbox, due: "2026-09-29")

        let counts = GTDQueries.counts(in: fixture.state, today: QueryFixture.today)

        #expect(counts == ListCounts(inbox: 1, next: 2, waiting: 1, someday: 2, overdue: 2, today: 2))
        #expect(OpenList.allCases.map(counts.count(for:)) == [1, 2, 1, 2])
        #expect(GTDQueries.counts(in: .empty, today: QueryFixture.today) == ListCounts())
    }

    @Test("Active projects sort by normalized name ignoring diacritics, then display name, then id")
    func projectOrder() {
        var fixture = QueryFixture()
        fixture.project("zulu", id: "p1")
        fixture.project("Éclair", id: "p2")
        fixture.project("  alpha  ", id: "p3")
        fixture.project("Bravo", id: "p5")
        fixture.project("bravo", id: "p4")
        fixture.project("eclair", id: "p6")
        fixture.project("Archived", archived: true, id: "p7")

        let names = GTDQueries.projects(in: fixture.state).map(\.project.name)

        #expect(names == ["  alpha  ", "Bravo", "bravo", "eclair", "Éclair", "zulu"])
    }

    @Test("Project summaries count open tasks and next actions and flag stuck projects")
    func projectCounts() throws {
        var fixture = QueryFixture()
        let moving = fixture.project("Moving")
        let stuck = fixture.project("Stuck")
        let empty = fixture.project("Empty")
        fixture.task("Book van", .next, project: moving)
        fixture.task("Pack books", .next, project: moving)
        fixture.task("Deposit back", .waiting, project: moving)
        fixture.task("Sort cables", .inbox, project: moving)
        fixture.task("Packed kitchen", .completed, from: .next, project: moving)
        fixture.task("Ask landlord", .waiting, project: stuck)
        fixture.task("Old next", .cancelled, from: .next, project: stuck)

        let summaries = Dictionary(
            uniqueKeysWithValues: GTDQueries.projects(in: fixture.state).map { ($0.id, $0) })

        let movingSummary = try #require(summaries[moving])
        #expect(movingSummary.openTaskCount == 4)
        #expect(movingSummary.nextActionCount == 2)
        #expect(!movingSummary.needsNextAction)

        let stuckSummary = try #require(summaries[stuck])
        #expect(stuckSummary.openTaskCount == 1)
        #expect(stuckSummary.nextActionCount == 0)
        #expect(stuckSummary.needsNextAction)

        let emptySummary = try #require(summaries[empty])
        #expect(emptySummary.openTaskCount == 0)
        #expect(emptySummary.needsNextAction)
    }

    @Test("Archived projects are listed on request and never need a next action")
    func archivedProjects() {
        var fixture = QueryFixture()
        fixture.project("Active")
        let old = fixture.project("Zeta old", archived: true)
        fixture.project("Alpha old", archived: true)
        fixture.task("Lingering", .someday, project: old)

        let archived = GTDQueries.projects(in: fixture.state, archived: true)

        #expect(archived.map(\.project.name) == ["Alpha old", "Zeta old"])
        #expect(archived.map(\.openTaskCount) == [0, 1])
        #expect(archived.allSatisfy { !$0.needsNextAction })
        #expect(GTDQueries.projects(in: fixture.state).map(\.project.name) == ["Active"])
    }

    @Test("Active tags sort by name without a leading @ and count open tasks once each")
    func tags() {
        var fixture = QueryFixture()
        let office = fixture.tag("office", id: "t1")
        let home = fixture.tag("@home", id: "t2")
        let calls = fixture.tag("Calls", id: "t3")
        let gone = fixture.tag("gone", deleted: true, id: "t4")
        fixture.task("Call from home", .next, tags: [home, calls])
        fixture.task("Duplicated tag", .waiting, tags: [calls, calls])
        fixture.task("Office inbox", .inbox, tags: [office])
        fixture.task("Done call", .completed, tags: [calls])
        fixture.task("Gone tag", .next, tags: [gone])

        let summaries = GTDQueries.tags(in: fixture.state)

        #expect(summaries.map(\.tag.name) == ["Calls", "@home", "office"])
        #expect(summaries.map(\.openTaskCount) == [2, 1, 1])
        #expect(summaries.map(\.id) == [calls, home, office])
    }
}
