import Foundation
import Testing

@testable import BrainBuddyCore

@Suite("Queries › project and tag views")
struct QueriesProjectTagTests {
    @Test("A project view has one section per open list: Next actions, Waiting for, Inbox, Someday / maybe")
    func projectSections() {
        var fixture = QueryFixture()
        let kitchen = fixture.project("Kitchen")
        let other = fixture.project("Garden")
        fixture.task("Heated floors", .someday, project: kitchen)
        fixture.task("Skylight idea", .inbox, project: kitchen)
        fixture.task("Quote from Sam", .waiting, project: kitchen)
        fixture.task("Call contractor, key 20", .next, project: kitchen, orderKey: 20)
        fixture.task("Measure walls, key 10", .next, project: kitchen, orderKey: 10)
        fixture.task("Plant roses", .next, project: other)
        fixture.task("Loose", .next)
        fixture.task("Tiles picked", .completed, from: .next, project: kitchen)

        let result = fixture.list(.project(kitchen))

        #expect(result.sectionIDs == ["list:next", "list:waiting", "list:inbox", "list:someday"])
        #expect(result.sectionTitles == ["Next actions", "Waiting for", "Inbox", "Someday / maybe"])
        #expect(result.sections.map(\.kind) == [.list(.next), .list(.waiting), .list(.inbox), .list(.someday)])
        #expect(
            result.titles == [
                ["Measure walls, key 10", "Call contractor, key 20"], ["Quote from Sam"], ["Skylight idea"],
                ["Heated floors"],
            ])
        #expect(result.openCount == 5)
        #expect(GTDQueries.projectListOrder == [.next, .waiting, .inbox, .someday])
    }

    @Test("A project view omits empty lists, ignores group by project and honours the sort")
    func projectViewOptions() {
        var fixture = QueryFixture()
        let kitchen = fixture.project("Kitchen")
        fixture.task("Buy paint", .next, project: kitchen)
        fixture.task("Arrange tiles", .next, project: kitchen)
        fixture.task("Ask Sam", .waiting, project: kitchen)

        let result = fixture.list(.project(kitchen), ListOptions(sort: .title, groupByProject: true))

        #expect(result.sectionIDs == ["list:next", "list:waiting"])
        #expect(result.titles(in: "list:next") == ["Arrange tiles", "Buy paint"])
    }

    @Test("A project view appends the project's completed and cancelled tasks, whatever list they came from")
    func projectHistory() {
        var fixture = QueryFixture()
        let kitchen = fixture.project("Kitchen")
        fixture.task("Done from next", .completed, from: .next, project: kitchen)
        fixture.task("Done, origin unknown", .completed, project: kitchen)
        fixture.task("Dropped", .cancelled, from: .someday, project: kitchen)
        fixture.task("Done elsewhere", .completed, from: .next)

        let result = fixture.list(.project(kitchen), ListOptions(showCompleted: true, showCancelled: true))

        #expect(result.sectionIDs == ["completed", "cancelled"])
        #expect(result.titles == [["Done from next", "Done, origin unknown"], ["Dropped"]])
        #expect(result.openCount == 0)
        #expect(fixture.list(.project(kitchen)).isEmpty)
    }

    @Test("A project view works for an archived project and is empty for an unknown one")
    func archivedAndUnknownProjects() {
        var fixture = QueryFixture()
        let old = fixture.project("Old", archived: true)
        fixture.task("Still referencing", .next, project: old)
        fixture.task("Old history", .completed, from: .next, project: old)

        #expect(fixture.list(.project(old), ListOptions(showCompleted: true)).titles == [["Still referencing"], ["Old history"]])
        #expect(fixture.list(.project("p-missing")).sections.isEmpty)
    }

    @Test("A project view applies priority and tag filters")
    func projectFilters() {
        var fixture = QueryFixture()
        let kitchen = fixture.project("Kitchen")
        let phone = fixture.tag("phone")
        fixture.task("Call, high", project: kitchen, tags: [phone], priority: .high)
        fixture.task("Call, low", project: kitchen, tags: [phone], priority: .low)
        fixture.task("Measure, high", project: kitchen, priority: .high)

        let result = fixture.list(.project(kitchen), ListOptions(priorities: [.high], tagFilter: phone))

        #expect(result.allTitles == ["Call, high"])
    }

    @Test("A tag view shows open tasks carrying the tag in every list and project")
    func tagView() {
        var fixture = QueryFixture()
        let home = fixture.project("Home")
        let phone = fixture.tag("phone")
        let errand = fixture.tag("errand")
        fixture.task("Call mum", .next, tags: [phone])
        fixture.task("Call plumber", .waiting, project: home, tags: [errand, phone])
        fixture.task("Captured call", .inbox, project: home, tags: [phone])
        fixture.task("Buy milk", .next, tags: [errand])
        fixture.task("Called bank", .completed, from: .next, tags: [phone])

        let result = fixture.list(.tag(phone))

        #expect(result.sectionIDs == ["open"])
        #expect(result.allTitles == ["Call mum", "Call plumber", "Captured call"])
        #expect(result.openCount == 3)
    }

    @Test("A tag view groups by project and appends the tag's history regardless of origin list")
    func tagViewGroupingAndHistory() {
        var fixture = QueryFixture()
        let home = fixture.project("Home", id: "p-home")
        let phone = fixture.tag("phone")
        fixture.task("Call plumber", .next, project: home, tags: [phone])
        fixture.task("Call mum", .someday, tags: [phone])
        fixture.task("Called bank", .completed, from: .waiting, tags: [phone])
        fixture.task("Called gran", .completed, tags: [phone])
        fixture.task("Cancelled call", .cancelled, from: .next, tags: [phone])

        let result = fixture.list(.tag(phone), ListOptions(groupByProject: true, showCompleted: true))

        #expect(result.sectionIDs == ["project:p-home", "none", "completed"])
        #expect(result.titles == [["Call plumber"], ["Call mum"], ["Called bank", "Called gran"]])
    }

    @Test("A tag view with a different tag filter shows tasks carrying both")
    func tagViewWithTagFilter() {
        var fixture = QueryFixture()
        let phone = fixture.tag("phone")
        let urgent = fixture.tag("urgent")
        fixture.task("Call now", tags: [phone, urgent])
        fixture.task("Call later", tags: [phone])
        fixture.task("Urgent errand", tags: [urgent])

        #expect(fixture.list(.tag(phone), ListOptions(tagFilter: urgent)).allTitles == ["Call now"])
    }

    @Test("A deleted or unknown tag shows nothing")
    func deletedTag() {
        var fixture = QueryFixture()
        let gone = fixture.tag("gone", deleted: true)
        fixture.task("Untagged")

        #expect(fixture.list(.tag(gone)).isEmpty)
        #expect(fixture.list(.tag("t-missing")).isEmpty)
    }
}
