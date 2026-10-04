import Foundation
import Testing

@testable import BrainBuddyCore

@Suite("Queries › history")
struct QueriesHistoryTests {
    @Test("Completed history is most recent first, then id; unknown times last")
    func completedHistory() {
        var fixture = QueryFixture()
        fixture.task("Oldest", .completed, from: .next, ended: at(hours: 1))
        fixture.task("Newest", .completed, from: .inbox, ended: at(hours: 9))
        fixture.task("Tie b", .completed, id: "b", ended: at(hours: 5))
        fixture.task("Tie a", .completed, id: "a", ended: at(hours: 5))
        fixture.task("Unknown time", .completed, from: .someday)
        fixture.task("Cancelled", .cancelled, from: .next, ended: at(hours: 20))
        fixture.task("Open", .next)

        let result = fixture.list(.history(.completed))

        #expect(result.sectionIDs == ["completed"])
        #expect(result.sectionTitles == [nil])
        #expect(result.sections.first?.kind == .completed)
        #expect(result.allTitles == ["Newest", "Tie a", "Tie b", "Oldest", "Unknown time"])
        #expect(result.openCount == 0)
    }

    @Test("Cancelled history orders by cancellation time")
    func cancelledHistory() {
        var fixture = QueryFixture()
        fixture.task("Dropped early", .cancelled, from: .next, ended: at(hours: 1))
        fixture.task("Dropped late", .cancelled, from: .waiting, ended: at(hours: 3))
        fixture.task("Completed", .completed, from: .next, ended: at(hours: 2))

        let result = fixture.list(.history(.cancelled))

        #expect(result.sectionIDs == ["cancelled"])
        #expect(result.sections.first?.kind == .cancelled)
        #expect(result.allTitles == ["Dropped late", "Dropped early"])
    }

    @Test("History ignores show completed and show cancelled")
    func historyIgnoresShowOptions() {
        var fixture = QueryFixture()
        fixture.task("Done", .completed, ended: at(hours: 1))
        fixture.task("Dropped", .cancelled, ended: at(hours: 1))

        let result = fixture.list(.history(.completed), ListOptions(showCompleted: false, showCancelled: true))

        #expect(result.allTitles == ["Done"])
    }

    @Test("History honours an explicit sort")
    func historyExplicitSort() {
        var fixture = QueryFixture()
        fixture.task("Bravo", .completed, ended: at(hours: 9))
        fixture.task("alpha", .completed, ended: at(hours: 1))
        fixture.task("Charlie", .completed, ended: at(hours: 5))

        #expect(fixture.list(.history(.completed), ListOptions(sort: .title)).allTitles == ["alpha", "Bravo", "Charlie"])
    }

    @Test("History groups by project and applies filters")
    func historyGroupingAndFilters() {
        var fixture = QueryFixture()
        let home = fixture.project("Home", id: "p-home")
        let phone = fixture.tag("phone")
        fixture.task("Home call", .completed, project: home, tags: [phone], ended: at(hours: 2))
        fixture.task("Home chore", .completed, project: home, ended: at(hours: 3))
        fixture.task("Loose call old", .completed, tags: [phone], priority: .high, ended: at(hours: 1))
        fixture.task("Loose call new", .completed, tags: [phone], priority: .high, ended: at(hours: 4))

        let grouped = fixture.list(.history(.completed), ListOptions(groupByProject: true, tagFilter: phone))
        #expect(grouped.sectionIDs == ["project:p-home", "none"])
        #expect(grouped.titles == [["Home call"], ["Loose call new", "Loose call old"]])
        #expect(grouped.openCount == 0)

        let highOnly = fixture.list(.history(.completed), ListOptions(priorities: [.high]))
        #expect(highOnly.allTitles == ["Loose call new", "Loose call old"])
    }

    @Test("Empty history has no sections")
    func emptyHistory() {
        var fixture = QueryFixture()
        fixture.task("Open")

        #expect(fixture.list(.history(.cancelled)).sections.isEmpty)
    }
}
