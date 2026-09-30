import Foundation
import Testing

@testable import BrainBuddyCore

@Suite("Queries › agenda and date views")
struct QueriesDateViewTests {
    /// Today is 2026-09-29.
    private func dated() -> QueryFixture {
        var fixture = QueryFixture()
        fixture.task("Undated")
        fixture.task("Last week", due: "2026-09-22", orderKey: 50)
        fixture.task("Yesterday", .inbox, due: "2026-09-28", orderKey: 10)
        fixture.task("Today, key 30", .waiting, due: "2026-09-29", orderKey: 30)
        fixture.task("Today, key 20", .someday, due: "2026-09-29", orderKey: 20)
        fixture.task("Tomorrow", due: "2026-09-30", orderKey: 5)
        fixture.task("Next year", due: "2027-01-01", orderKey: 1)
        fixture.task("Done yesterday", .completed, from: .next, due: "2026-09-28")
        fixture.task("Dropped today", .cancelled, from: .next, due: "2026-09-29")
        return fixture
    }

    @Test("Agenda has Overdue, Today and Upcoming over open tasks, each by due date then manual")
    func agendaSections() {
        let result = dated().list(.agenda)

        #expect(result.sectionIDs == ["date:overdue", "date:today", "date:upcoming"])
        #expect(result.sectionTitles == ["Overdue", "Today", "Upcoming"])
        #expect(result.sections.map(\.kind) == [.dateView(.overdue), .dateView(.today), .dateView(.upcoming)])
        #expect(
            result.titles == [
                ["Last week", "Yesterday"], ["Today, key 20", "Today, key 30"], ["Tomorrow", "Next year"],
            ])
        #expect(result.openCount == 6)
    }

    @Test("Agenda omits empty sections")
    func agendaOmitsEmptySections() {
        var fixture = QueryFixture()
        fixture.task("Tomorrow", due: "2026-09-30")
        fixture.task("Done today", .completed, from: .next, due: "2026-09-29")

        let result = fixture.list(.agenda)

        #expect(result.sectionIDs == ["date:upcoming"])
    }

    @Test("Agenda honours an explicit sort inside each section")
    func agendaExplicitSort() {
        var fixture = QueryFixture()
        fixture.task("Low today", due: "2026-09-29", priority: .low, orderKey: 1)
        fixture.task("High today", due: "2026-09-29", priority: .high, orderKey: 2)
        fixture.task("Later upcoming", due: "2026-10-05", priority: .medium, orderKey: 3)
        fixture.task("Sooner upcoming", due: "2026-10-01", priority: .none, orderKey: 4)

        let result = fixture.list(.agenda, ListOptions(sort: .priority))

        #expect(result.titles == [["High today", "Low today"], ["Later upcoming", "Sooner upcoming"]])
    }

    @Test("Agenda ignores group by project and appends dated history when asked")
    func agendaIgnoresGrouping() {
        let result = dated().list(.agenda, ListOptions(groupByProject: true, showCompleted: true, showCancelled: true))

        #expect(result.sectionIDs == ["date:overdue", "date:today", "date:upcoming", "completed", "cancelled"])
        #expect(result.titles(in: "completed") == ["Done yesterday"])
        #expect(result.titles(in: "cancelled") == ["Dropped today"])
        #expect(result.openCount == 6)
    }

    @Test(
        "A date view shows one range of open tasks in a single section",
        arguments: [
            (DateView.overdue, ["Last week", "Yesterday"]),
            (.today, ["Today, key 20", "Today, key 30"]),
            (.upcoming, ["Tomorrow", "Next year"]),
        ])
    func dateView(view: DateView, expected: [String]) {
        let result = dated().list(.dateView(view))

        #expect(result.sectionIDs == ["open"])
        #expect(result.allTitles == expected)
        #expect(result.openCount == expected.count)
    }

    @Test("Date views sort by due date when the sort is manual")
    func dateViewForcesDueOrder() {
        var fixture = QueryFixture()
        fixture.task("Later, key 1", due: "2026-10-09", orderKey: 1)
        fixture.task("Sooner, key 2", due: "2026-10-01", orderKey: 2)

        #expect(fixture.list(.dateView(.upcoming)).allTitles == ["Sooner, key 2", "Later, key 1"])
        #expect(
            fixture.list(.dateView(.upcoming), ListOptions(sort: .title)).allTitles == [
                "Later, key 1", "Sooner, key 2",
            ])
    }

    @Test("A date view groups by project and appends its range's history")
    func dateViewGroupingAndHistory() {
        var fixture = QueryFixture()
        let work = fixture.project("Work", id: "p-work")
        fixture.task("Work today", project: work, due: "2026-09-29")
        fixture.task("Loose today", .inbox, due: "2026-09-29")
        fixture.task("Work tomorrow", project: work, due: "2026-09-30")
        fixture.task("Done today", .completed, from: .next, due: "2026-09-29")
        fixture.task("Done tomorrow", .completed, from: .next, due: "2026-09-30")

        let result = fixture.list(.dateView(.today), ListOptions(groupByProject: true, showCompleted: true))

        #expect(result.sectionIDs == ["project:p-work", "none", "completed"])
        #expect(result.titles == [["Work today"], ["Loose today"], ["Done today"]])
    }

    @Test("Today is injected: the same data moves between views as the day changes")
    func todayIsInjected() {
        var fixture = QueryFixture()
        fixture.task("Due 30th", due: "2026-09-30")

        #expect(fixture.list(.dateView(.upcoming)).allTitles == ["Due 30th"])
        #expect(fixture.list(.dateView(.today), today: isoDay("2026-09-30")).allTitles == ["Due 30th"])
        #expect(fixture.list(.dateView(.overdue), today: isoDay("2026-10-01")).allTitles == ["Due 30th"])
    }

    @Test("Year and month boundaries compare chronologically")
    func boundaries() {
        var fixture = QueryFixture()
        fixture.task("Dec 31", due: "2025-12-31")
        fixture.task("Jan 1", due: "2026-01-01")
        fixture.task("Feb 29", due: "2028-02-29")

        let result = fixture.list(.agenda, today: isoDay("2026-01-01"))

        #expect(result.titles == [["Dec 31"], ["Jan 1"], ["Feb 29"]])
    }
}
