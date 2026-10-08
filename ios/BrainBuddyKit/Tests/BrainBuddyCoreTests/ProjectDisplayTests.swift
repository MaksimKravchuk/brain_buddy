import Testing

@testable import BrainBuddyCore

@Suite("GTDQueries.projectDisplay")
struct ProjectDisplayTests {
    private func state(_ projectState: ProjectState, marker: Bool, tasks: [TaskState]) -> GTDState {
        var project = Fixture.project("p", "Old flat", state: projectState)
        project.archivedBeforeLossless = marker
        return Fixture.state(
            tasks: tasks.enumerated().map { Fixture.task(TaskID("t\($0.offset)"), state: $0.element, projectID: "p") },
            projects: [project]
        )
    }

    @Test("021-FR-025 021-FR-027 each combination of state, marker and task count", arguments: [
        (ProjectState.active, false, 0), (.active, false, 2), (.active, true, 0), (.archived, false, 0),
        (.archived, false, 3), (.archived, true, 0), (.archived, true, 1),
    ])
    func combinations(projectState: ProjectState, marker: Bool, tasks: Int) throws {
        let state = state(projectState, marker: marker, tasks: Array(repeating: .inbox, count: tasks))
        let display = try #require(GTDQueries.projectDisplay("p", in: state))
        let archived = projectState == .archived
        #expect(display.isArchived == archived)
        #expect(display.acceptsNewTasks == !archived)
        #expect(display.showsPreLosslessLine == (marker && tasks == 0))
        #expect(display.label == (archived ? "Old flat · archived" : "Old flat"))
    }

    @Test("021-FR-027 a task in any state, completed or cancelled included, hides the pre-lossless line")
    func anyTaskStateHidesTheLine() throws {
        for taskState in TaskState.allCases {
            let display = try #require(GTDQueries.projectDisplay("p", in: state(.archived, marker: true, tasks: [taskState])))
            #expect(!display.showsPreLosslessLine, "\(taskState)")
        }
        let empty = try #require(GTDQueries.projectDisplay("p", in: state(.archived, marker: true, tasks: [])))
        #expect(empty.showsPreLosslessLine)
    }

    @Test("021-FR-025 an unknown project has no display")
    func unknownProject() {
        #expect(GTDQueries.projectDisplay("missing", in: state(.active, marker: false, tasks: [])) == nil)
    }
}
