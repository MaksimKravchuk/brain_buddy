import Foundation
import Testing

@testable import BrainBuddyCore

@Suite("Queries › open lists")
struct QueriesListTests {
    @Test("Inbox shows only open, projectless inbox tasks")
    func inboxIsProjectless() {
        var fixture = QueryFixture()
        let home = fixture.project("Home")
        fixture.task("Loose idea", .inbox)
        fixture.task("Idea for home", .inbox, project: home)
        fixture.task("Next thing", .next)
        fixture.task("Done idea", .completed, from: .inbox)

        let result = fixture.list(.list(.inbox))

        #expect(result.sectionIDs == ["open"])
        #expect(result.sectionTitles == [nil])
        #expect(result.sections.first?.kind == .open)
        #expect(result.allTitles == ["Loose idea"])
        #expect(result.openCount == 1)
    }

    @Test("Next, Waiting and Someday show their state in every project", arguments: [OpenList.next, .waiting, .someday])
    func otherListsIncludeProjects(list: OpenList) {
        var fixture = QueryFixture()
        let home = fixture.project("Home")
        fixture.task("Plain", list.taskState)
        fixture.task("In project", list.taskState, project: home)
        fixture.task("Elsewhere", list == .next ? .someday : .next)
        fixture.task("Inbox", .inbox)
        fixture.task("Finished", .completed, from: list)
        fixture.task("Dropped", .cancelled, from: list)

        let result = fixture.list(.list(list))

        #expect(result.allTitles == ["Plain", "In project"])
        #expect(result.openCount == 2)
    }

    @Test("Manual order is order key, then creation time, then id")
    func manualOrder() {
        var fixture = QueryFixture()
        fixture.task("Key 30", orderKey: 30)
        fixture.task("Key 10, later", orderKey: 10, createdAt: at(hours: 2))
        fixture.task("Key 10, earlier", orderKey: 10, createdAt: at(hours: 1))
        fixture.task("Key 20, id b", id: "b", orderKey: 20, createdAt: at(hours: 1))
        fixture.task("Key 20, id a", id: "a", orderKey: 20, createdAt: at(hours: 1))
        fixture.task("Negative key", orderKey: -5)

        #expect(
            fixture.list(.list(.next)).allTitles == [
                "Negative key", "Key 10, earlier", "Key 10, later", "Key 20, id a", "Key 20, id b", "Key 30",
            ])
    }

    @Test("Due order puts dated tasks first by date, then manual; undated last in manual order")
    func dueOrder() {
        var fixture = QueryFixture()
        fixture.task("Undated early", orderKey: 1)
        fixture.task("October", due: "2026-10-01", orderKey: 50)
        fixture.task("Undated late", orderKey: 99)
        fixture.task("September, key 40", due: "2026-09-15", orderKey: 40)
        fixture.task("September, key 20", due: "2026-09-15", orderKey: 20)
        fixture.task("Last year", due: "2025-12-31", orderKey: 60)

        #expect(
            fixture.list(.list(.next), ListOptions(sort: .due)).allTitles == [
                "Last year", "September, key 20", "September, key 40", "October", "Undated early", "Undated late",
            ])
    }

    @Test("Priority order is high, medium, low, none, then manual")
    func priorityOrder() {
        var fixture = QueryFixture()
        fixture.task("None", priority: .none, orderKey: 1)
        fixture.task("Low", priority: .low, orderKey: 2)
        fixture.task("High late", priority: .high, orderKey: 9)
        fixture.task("Medium", priority: .medium, orderKey: 4)
        fixture.task("High early", priority: .high, orderKey: 5)

        #expect(
            fixture.list(.list(.next), ListOptions(sort: .priority)).allTitles == [
                "High early", "High late", "Medium", "Low", "None",
            ])
    }

    @Test("Title order ignores case, diacritics and width, then falls back to id")
    func titleOrder() {
        var fixture = QueryFixture()
        fixture.task("zebra", id: "t1")
        fixture.task("Éclair", id: "t3")
        fixture.task("eclair", id: "t2")
        fixture.task("Banana", id: "t4")
        fixture.task("ａpple", id: "t5")  // full-width a
        fixture.task("apple pie", id: "t6")
        fixture.task("Dates", id: "t7")

        let titles = fixture.list(.list(.next), ListOptions(sort: .title)).allTitles

        #expect(titles == ["ａpple", "apple pie", "Banana", "Dates", "eclair", "Éclair", "zebra"])
    }

    @Test("Group by project: sections in project name order, No project last, sort kept inside")
    func groupByProject() {
        var fixture = QueryFixture()
        let zulu = fixture.project("zulu", id: "p-zulu")
        let alpha = fixture.project("Alpha", id: "p-alpha")
        let eclair = fixture.project("Éclair", id: "p-eclair")
        let bravo = fixture.project("bravo", id: "p-bravo")
        fixture.task("Loose 2", orderKey: 2)
        fixture.task("Zulu 1", project: zulu, orderKey: 1)
        fixture.task("Alpha 2", project: alpha, orderKey: 20)
        fixture.task("Alpha 1", project: alpha, orderKey: 10)
        fixture.task("Eclair 1", project: eclair, orderKey: 3)
        fixture.task("Loose 1", orderKey: 1)
        fixture.task("Bravo someday", .someday, project: bravo)

        let result = fixture.list(.list(.next), ListOptions(groupByProject: true))

        #expect(result.sectionIDs == ["project:p-alpha", "project:p-eclair", "project:p-zulu", "none"])
        #expect(result.sectionTitles == ["Alpha", "Éclair", "zulu", "No project"])
        #expect(result.sections.map(\.kind) == [.project(alpha), .project(eclair), .project(zulu), .project(nil)])
        #expect(result.titles == [["Alpha 1", "Alpha 2"], ["Eclair 1"], ["Zulu 1"], ["Loose 1", "Loose 2"]])
        #expect(result.openCount == 6)
    }

    @Test("Group by project keeps a non-manual sort inside each section")
    func groupByProjectKeepsSort() {
        var fixture = QueryFixture()
        let home = fixture.project("Home", id: "p-home")
        fixture.task("Home low", project: home, priority: .low, orderKey: 1)
        fixture.task("Home high", project: home, priority: .high, orderKey: 2)
        fixture.task("Loose none", priority: .none, orderKey: 1)
        fixture.task("Loose medium", priority: .medium, orderKey: 2)

        let result = fixture.list(.list(.next), ListOptions(sort: .priority, groupByProject: true))

        #expect(result.titles == [["Home high", "Home low"], ["Loose medium", "Loose none"]])
    }

    @Test("Group by project: archived projects after active ones, unknown projects under No project")
    func groupByProjectEdgeProjects() {
        var fixture = QueryFixture()
        let old = fixture.project("Aardvark", archived: true, id: "p-old")
        let live = fixture.project("Zebra", id: "p-live")
        fixture.task("In archived", project: old)
        fixture.task("In active", project: live)
        fixture.task("Dangling", project: "p-missing")

        let result = fixture.list(.list(.next), ListOptions(groupByProject: true))

        #expect(result.sectionIDs == ["project:p-live", "project:p-old", "none"])
        #expect(result.titles == [["In active"], ["In archived"], ["Dangling"]])
    }

    @Test("Group by project is ignored in Inbox")
    func groupByProjectIgnoredInInbox() {
        var fixture = QueryFixture()
        fixture.task("Loose", .inbox)

        #expect(fixture.list(.list(.inbox), ListOptions(groupByProject: true)).sectionIDs == ["open"])
    }

    @Test("Show completed appends tasks completed from this list, in the list's sort")
    func showCompleted() {
        var fixture = QueryFixture()
        fixture.task("Open")
        fixture.task("Done from next, key 20", .completed, from: .next, orderKey: 20, ended: at(hours: 1))
        fixture.task("Done from next, key 10", .completed, from: .next, orderKey: 10, ended: at(hours: 2))
        fixture.task("Done from someday", .completed, from: .someday)
        fixture.task("Done, origin unknown", .completed)
        fixture.task("Dropped from next", .cancelled, from: .next)

        let result = fixture.list(.list(.next), ListOptions(showCompleted: true))

        #expect(result.sectionIDs == ["open", "completed"])
        #expect(result.sectionTitles == [nil, "Completed"])
        #expect(result.sections.last?.kind == .completed)
        #expect(result.titles(in: "completed") == ["Done from next, key 10", "Done from next, key 20"])
        #expect(result.openCount == 1)
    }

    @Test("Show cancelled appends tasks cancelled from this list after the completed ones")
    func showCancelled() {
        var fixture = QueryFixture()
        fixture.task("Dropped from waiting", .cancelled, from: .waiting)
        fixture.task("Dropped from next", .cancelled, from: .next)
        fixture.task("Done from waiting", .completed, from: .waiting)

        let cancelledOnly = fixture.list(.list(.waiting), ListOptions(showCancelled: true))
        #expect(cancelledOnly.sectionIDs == ["cancelled"])
        #expect(cancelledOnly.sectionTitles == ["Cancelled"])
        #expect(cancelledOnly.allTitles == ["Dropped from waiting"])
        #expect(cancelledOnly.openCount == 0)
        #expect(!cancelledOnly.isEmpty)

        let both = fixture.list(.list(.waiting), ListOptions(showCompleted: true, showCancelled: true))
        #expect(both.sectionIDs == ["completed", "cancelled"])
    }

    @Test("Inbox history is projectless too")
    func inboxHistoryIsProjectless() {
        var fixture = QueryFixture()
        let home = fixture.project("Home")
        fixture.task("Done loose", .completed, from: .inbox)
        fixture.task("Done in project", .completed, from: .inbox, project: home)

        #expect(fixture.list(.list(.inbox), ListOptions(showCompleted: true)).allTitles == ["Done loose"])
    }

    @Test("Completed and cancelled sections stay flat when grouping by project")
    func historyStaysFlatWhenGrouped() {
        var fixture = QueryFixture()
        let home = fixture.project("Home", id: "p-home")
        fixture.task("Open in home", project: home)
        fixture.task("Done in home", .completed, from: .next, project: home)
        fixture.task("Done loose", .completed, from: .next)

        let result = fixture.list(.list(.next), ListOptions(groupByProject: true, showCompleted: true))

        #expect(result.sectionIDs == ["project:p-home", "completed"])
        #expect(result.titles(in: "completed") == ["Done in home", "Done loose"])
    }

    @Test("Priority filter keeps the chosen priorities, in every section")
    func priorityFilter() {
        var fixture = QueryFixture()
        fixture.task("High", priority: .high)
        fixture.task("Low", priority: .low)
        fixture.task("None", priority: .none)
        fixture.task("Done high", .completed, from: .next, priority: .high)
        fixture.task("Done low", .completed, from: .next, priority: .low)

        let result = fixture.list(
            .list(.next), ListOptions(showCompleted: true, priorities: [.high, .none]))

        #expect(result.titles == [["High", "None"], ["Done high"]])
        #expect(result.openCount == 2)
    }

    @Test("An empty priority filter means every priority")
    func emptyPriorityFilter() {
        var fixture = QueryFixture()
        for priority in TaskPriority.allCases { fixture.task(priority.title, priority: priority) }

        #expect(fixture.list(.list(.next), ListOptions(priorities: [])).openCount == TaskPriority.allCases.count)
    }

    @Test("Tag filter narrows to tasks carrying the tag, in every section")
    func tagFilter() {
        var fixture = QueryFixture()
        let phone = fixture.tag("phone")
        let errand = fixture.tag("errand")
        fixture.task("Call", tags: [phone])
        fixture.task("Call and buy", tags: [errand, phone])
        fixture.task("Buy", tags: [errand])
        fixture.task("Untagged")
        fixture.task("Called", .completed, from: .next, tags: [phone])
        fixture.task("Bought", .completed, from: .next, tags: [errand])

        let result = fixture.list(.list(.next), ListOptions(showCompleted: true, tagFilter: phone))

        #expect(result.titles == [["Call", "Call and buy"], ["Called"]])
    }

    @Test("A list with nothing to show has no sections")
    func emptyList() {
        var fixture = QueryFixture()
        fixture.task("Someday thing", .someday)

        let result = fixture.list(.list(.next), ListOptions(groupByProject: true, showCompleted: true, showCancelled: true))

        #expect(result.sections.isEmpty)
        #expect(result.isEmpty)
        #expect(result.openCount == 0)
        #expect(GTDQueries.list(.agenda, options: ListOptions(), in: .empty, today: QueryFixture.today).sections.isEmpty)
    }

    @Test("Results do not depend on dictionary order")
    func deterministic() {
        var fixture = QueryFixture()
        for index in 0..<40 {
            fixture.task("Same", id: TaskID("id-\(index % 7)-\(index)"), orderKey: index % 3, createdAt: QueryFixture.epoch)
        }
        let first = fixture.list(.list(.next), ListOptions(sort: .title)).sections.flatMap { $0.tasks.map(\.id) }
        let copied = GTDState(tasks: Dictionary(uniqueKeysWithValues: fixture.state.tasks.map { ($0.key, $0.value) }))
        let second = GTDQueries.list(.list(.next), options: ListOptions(sort: .title), in: copied, today: QueryFixture.today)
            .sections.flatMap { $0.tasks.map(\.id) }

        #expect(first == second)
        #expect(first == first.sorted())
    }
}
