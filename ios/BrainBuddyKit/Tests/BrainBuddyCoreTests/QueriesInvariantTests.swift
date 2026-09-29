import Foundation
import Testing

@testable import BrainBuddyCore

/// Cross-checks between queries over a generated dataset of a few thousand
/// tasks: the numbers the sidebar shows must agree with the screens.
@Suite("Queries › invariants over a generated dataset")
struct QueriesInvariantTests {
    private static let dataset: QueryFixture = {
        var generator = SeededGenerator(seed: 0xB2A1_7D0C)
        var fixture = QueryFixture()
        let projects = (0..<12).map { fixture.project("Project \($0)", archived: $0 == 11) }
        let tags = (0..<6).map { fixture.tag("tag\($0)") }
        let words = ["call", "email", "buy", "Café", "report", "plan", "fix", "read"]
        for index in 0..<3_000 {
            let state = TaskState.allCases.randomElement(using: &generator)!
            let hasProject = Bool.random(using: &generator)
            let tagCount = Int.random(in: 0...2, using: &generator)
            let dueOffset = Int.random(in: -20...20, using: &generator)
            let origin: OpenList? = state.isTerminal ? OpenList.allCases.randomElement(using: &generator) : nil
            fixture.task(
                "\(words[index % words.count]) \(index)", state,
                from: Bool.random(using: &generator) ? origin : nil,
                project: hasProject ? projects.randomElement(using: &generator) : nil,
                tags: (0..<tagCount).map { _ in tags.randomElement(using: &generator)! },
                due: Bool.random(using: &generator) ? QueryFixture.today.adding(days: dueOffset).isoString : nil,
                priority: TaskPriority.allCases.randomElement(using: &generator)!,
                orderKey: Int.random(in: 0...50, using: &generator),
                ended: at(hours: Double(Int.random(in: 0...500, using: &generator))))
        }
        return fixture
    }()

    private var state: GTDState { Self.dataset.state }
    private let today = QueryFixture.today

    private func list(_ destination: Destination, _ options: ListOptions = ListOptions()) -> TaskListResult {
        GTDQueries.list(destination, options: options, in: state, today: today)
    }

    @Test("Each list's open count matches the sidebar count")
    func listCountsAgree() {
        let counts = GTDQueries.counts(in: state, today: today)
        for list in OpenList.allCases {
            #expect(self.list(.list(list)).openCount == counts.count(for: list))
        }
        #expect(list(.dateView(.overdue)).openCount == counts.overdue)
        #expect(list(.dateView(.today)).openCount == counts.today)
    }

    @Test("The agenda is exactly the three date views")
    func agendaMatchesDateViews() {
        let agenda = list(.agenda)
        for view in DateView.allCases {
            #expect(agenda.titles(in: "date:\(view.rawValue)") == list(.dateView(view)).allTitles)
        }
        #expect(agenda.openCount == DateView.allCases.map { list(.dateView($0)).openCount }.reduce(0, +))
    }

    @Test("Grouping by project changes sections, never membership or order within a project")
    func groupingPreservesMembership() {
        for sort in TaskSort.allCases {
            let flat = list(.list(.next), ListOptions(sort: sort))
            let grouped = list(.list(.next), ListOptions(sort: sort, groupByProject: true))
            #expect(grouped.openCount == flat.openCount)
            #expect(Set(grouped.allTitles) == Set(flat.allTitles))
            for section in grouped.sections {
                let members = Set(section.tasks.map(\.id))
                #expect(section.tasks.map(\.id) == flat.sections.flatMap(\.tasks).map(\.id).filter(members.contains))
            }
        }
    }

    @Test("Project summaries agree with project views")
    func projectSummariesAgree() {
        for summary in GTDQueries.projects(in: state) + GTDQueries.projects(in: state, archived: true) {
            let view = list(.project(summary.id))
            #expect(view.openCount == summary.openTaskCount)
            #expect(view.titles(in: "list:next").count == summary.nextActionCount)
        }
    }

    @Test("Tag summaries agree with tag views")
    func tagSummariesAgree() {
        for summary in GTDQueries.tags(in: state) {
            #expect(list(.tag(summary.id)).openCount == summary.openTaskCount)
        }
    }

    @Test("History views together hold every terminal task, and search finds every task by its unique word")
    func historyAndSearchCoverage() {
        let terminal = state.tasks.values.filter(\.state.isTerminal).count
        #expect(list(.history(.completed)).allTitles.count + list(.history(.cancelled)).allTitles.count == terminal)

        let everyTask = list(.search("cafe"))
        #expect(everyTask.allTitles.count == state.tasks.values.filter { $0.title.hasPrefix("Café") }.count)
        #expect(list(.search("café 3")).allTitles.allSatisfy { $0.hasPrefix("Café 3") })
    }

    @Test("Every sort is a total order: sorting is stable across repeated calls")
    func sortsAreTotal() {
        for sort in TaskSort.allCases {
            let options = ListOptions(sort: sort, showCompleted: true, showCancelled: true)
            let first = list(.list(.someday), options).sections.flatMap(\.tasks).map(\.id)
            let reshuffled = GTDState(tasks: Dictionary(uniqueKeysWithValues: state.tasks.reversed()), projects: state.projects)
            let second = GTDQueries.list(.list(.someday), options: options, in: reshuffled, today: today)
                .sections.flatMap(\.tasks).map(\.id)
            #expect(first == second)
        }
    }
}
