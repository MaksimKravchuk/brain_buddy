import Foundation
import Testing

@testable import BrainBuddyCore

@Suite("Queries › search")
struct QueriesSearchTests {
    private func titles(for query: String, in fixture: QueryFixture) -> [String] {
        fixture.list(.search(query)).allTitles
    }

    @Test(
        "Matching ignores case, diacritics and width, and folds like the server",
        arguments: [
            ("café", "Book the Cafe"),
            ("CAFE", "Book the Café"),
            ("ｃａｆｅ", "Book the café"),  // full-width query
            ("cafe", "Book the ｃａｆé"),  // full-width title
            ("strasse", "Walk down the Straße"),
            ("STRASSE", "Walk down the strasse"),
            ("naive", "A naïve plan"),
            ("istanbul", "Fly to İstanbul"),
            ("file", "Rename the ﬁle"),  // ligature
        ])
    func folding(query: String, title: String) {
        var fixture = QueryFixture()
        fixture.task(title)
        fixture.task("Unrelated")

        #expect(titles(for: query, in: fixture) == [title])
    }

    @Test("The query is trimmed and its whitespace collapsed")
    func queryWhitespace() {
        var fixture = QueryFixture()
        fixture.task("Buy oat milk")

        #expect(titles(for: "  buy \t  oat\n milk  ", in: fixture) == ["Buy oat milk"])
    }

    @Test("Notes are searched, but a match cannot span title and notes")
    func notes() {
        var fixture = QueryFixture()
        fixture.task("Buy milk", details: "From the corner shop")
        fixture.task("Plain", details: nil)

        #expect(titles(for: "corner", in: fixture) == ["Buy milk"])
        #expect(titles(for: "milk from", in: fixture).isEmpty)
    }

    @Test("A blank query matches nothing", arguments: ["", " ", "\n\t", "\u{301}"])
    func blankQuery(query: String) {
        var fixture = QueryFixture()
        fixture.task("Anything")

        let result = fixture.list(.search(query), ListOptions(showCompleted: true))

        #expect(result.sections.isEmpty)
        #expect(result.openCount == 0)
    }

    @Test("Search covers every state: open first, then completed, then cancelled")
    func allStates() {
        var fixture = QueryFixture()
        fixture.task("Report done", .completed, from: .next, ended: at(hours: 1))
        fixture.task("Report dropped", .cancelled, ended: at(hours: 1))
        fixture.task("Report draft", .someday)
        fixture.task("Report inbox", .inbox)
        let home = fixture.project("Home")
        fixture.task("Report for home", .inbox, project: home)
        fixture.task("Unrelated", .next)

        let result = fixture.list(.search("report"))

        #expect(result.sectionIDs == ["open", "completed", "cancelled"])
        #expect(result.sectionTitles == [nil, "Completed", "Cancelled"])
        #expect(result.titles == [["Report draft", "Report inbox", "Report for home"], ["Report done"], ["Report dropped"]])
        #expect(result.openCount == 3)
    }

    @Test("Search honours the sort, filters and group by project")
    func searchOptions() {
        var fixture = QueryFixture()
        let home = fixture.project("Home", id: "p-home")
        let phone = fixture.tag("phone")
        fixture.task("Call plumber", project: home, tags: [phone], priority: .low)
        fixture.task("Call bank", tags: [phone], priority: .high)
        fixture.task("Call mum", priority: .high)
        fixture.task("Called gran", .completed, tags: [phone], priority: .high)

        let sorted = fixture.list(.search("call"), ListOptions(sort: .priority))
        #expect(sorted.titles == [["Call bank", "Call mum", "Call plumber"], ["Called gran"]])

        let filtered = fixture.list(.search("call"), ListOptions(priorities: [.high], tagFilter: phone))
        #expect(filtered.titles == [["Call bank"], ["Called gran"]])

        let grouped = fixture.list(.search("call"), ListOptions(groupByProject: true))
        #expect(grouped.sectionIDs == ["project:p-home", "none", "completed"])
    }
}
