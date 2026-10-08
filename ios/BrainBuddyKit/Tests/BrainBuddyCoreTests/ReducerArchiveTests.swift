import Foundation
import Testing

@testable import BrainBuddyCore

/// ADR-0020 as the reducer applies it (contracts/kit-commands.md §3).
@Suite("GTDReducer: lossless archive and unarchive")
struct ReducerArchiveTests {
    /// Work (active) holds an open, a completed and a cancelled task; Other is a second active project.
    private static var members: GTDState {
        Fixture.state(
            tasks: [
                Fixture.task("open", state: .next, projectID: "work"),
                Fixture.task("done", state: .completed, projectID: "work"),
                Fixture.task("dropped", state: .cancelled, projectID: "work"),
                Fixture.task("loose", state: .inbox),
            ],
            projects: [Fixture.project("work", "Work"), Fixture.project("other", "Other")]
        )
    }

    private static var archived: GTDState {
        var state = members
        try! apply(.archiveProject("work"), to: &state, at: 7)
        return state
    }

    @Test("021-FR-024 archiving keeps every task's project, stamps archivedAt and changes no task")
    func archiveIsLossless() throws {
        var state = Self.members
        #expect(try apply(.archiveProject("work"), to: &state, at: 7) == .applied)
        let project = try #require(state.projects["work"])
        #expect(project.state == .archived && project.archivedAt == Fixture.at(7) && !project.archivedBeforeLossless)
        #expect(state.tasks == Self.members.tasks, "no task changes: not its project, not its updatedAt")
    }

    @Test("021-FR-027 a repeat archive is already satisfied and never touches archivedAt or the marker")
    func repeatArchiveKeepsTheMarker() throws {
        var state = Self.members
        state.projects["work"]?.state = .archived
        state.projects["work"]?.archivedBeforeLossless = true
        let before = state
        var replayed = state
        #expect(try apply(.archiveProject("work"), to: &replayed, at: 9, mode: .replay) == .alreadySatisfied)
        #expect(replayed == before, "archivedAt stays nil and the marker stays true")
        expectRejection(.archiveProject("work"), on: before, .projectAlreadyArchived)
    }

    @Test("021-FR-026 unarchiving makes the project active again and leaves the marker and every task alone")
    func unarchive() throws {
        var state = Self.archived
        state.projects["work"]?.archivedBeforeLossless = true
        let before = state
        #expect(try apply(.unarchiveProject(project: "work"), to: &state, at: 9) == .applied)
        let project = try #require(state.projects["work"])
        #expect(project.state == .active && project.archivedAt == nil && project.archivedBeforeLossless)
        #expect(state.tasks == before.tasks)
    }

    @Test("021-FR-026 unarchive needs an archived project; an active one is already satisfied in replay")
    func unarchiveNeedsAnArchivedProject() throws {
        let state = Self.members
        expectRejection(.unarchiveProject(project: "work"), on: state, .nothingToChange)
        expectRejection(.unarchiveProject(project: "missing"), on: state, .projectNotFound)
        var replayed = state
        #expect(try apply(.unarchiveProject(project: "work"), to: &replayed, mode: .replay) == .alreadySatisfied)
        #expect(replayed == state)
    }

    @Test("021-FR-025 unarchive is refused while another active project has the same normalized name")
    func unarchiveNameInUse() throws {
        var state = Self.archived
        try apply(.createProject(.init(projectID: "again", name: "WORK")), to: &state)
        for mode in [ApplyMode.interactive, .replay] {
            expectRejection(.unarchiveProject(project: "work"), on: state, .unarchiveNameInUse("WORK"), mode: mode)
        }
        #expect(
            GTDValidationError.unarchiveNameInUse("WORK").message
                == "Another active project is already called “WORK”. Rename one first."
        )
        // Archived namesakes do not count.
        state.projects["again"]?.state = .archived
        try apply(.unarchiveProject(project: "work"), to: &state)
        #expect(state.projects["work"]?.state == .active)
    }

    @Test("021-FR-025 a new task cannot name an archived project")
    func createTaskIntoAnArchivedProject() {
        let state = Self.archived
        let create = GTDCommand.createTask(.init(taskID: "new", title: "New", list: .inbox, projectID: "work"))
        expectRejection(create, on: state, .projectNotActive)
    }

    @Test("021-FR-025 an edit may keep the project a task is archived with, but not choose another archived one")
    func updateTaskWithAnArchivedProject() throws {
        var state = Self.archived
        state.projects["other"]?.state = .archived
        expectRejection(
            .updateTask(.init(taskID: "open", changes: .init(projectID: .set("other")))), on: state, .projectNotActive
        )
        expectRejection(
            .updateTask(.init(taskID: "loose", changes: .init(projectID: .set("work")))), on: state, .projectNotActive
        )
        try apply(.updateTask(.init(taskID: "open", changes: .init(title: .set("Renamed")))), to: &state)
        try apply(
            .updateTask(.init(taskID: "open", changes: .init(title: .set("Again"), projectID: .set("work")))),
            to: &state)
        #expect(state.tasks["open"]?.projectID == "work" && state.tasks["open"]?.title == "Again")
        try apply(.updateTask(.init(taskID: "open", changes: .init(projectID: .clear))), to: &state)
        #expect(state.tasks["open"]?.projectID == nil)
    }

    @Test("021-FR-025 replay keeps a membership the task already had in an archived project and drops a new one")
    func replayKeepsACarriedMembership() {
        let state = Self.archived
        let carried = GTDCommand.updateTask(
            .init(taskID: "open", changes: .init(title: .set("T"), projectID: .set("work"))))
        #expect(GTDReducer.replayable(carried, in: state) == carried)
        let fresh = GTDCommand.updateTask(.init(taskID: "loose", changes: .init(projectID: .set("work"))))
        #expect(
            GTDReducer.replayable(fresh, in: state)
                == .updateTask(.init(taskID: "loose", changes: .init(projectID: .clear))))
        let create = GTDCommand.createTask(.init(taskID: "new", title: "New", list: .inbox, projectID: "work"))
        #expect(
            GTDReducer.replayable(create, in: state) == .createTask(.init(taskID: "new", title: "New", list: .inbox))
        )
    }

    @Test("021-FR-025 an archived project can still be renamed, recoloured and given an outcome")
    func archivedProjectsStayEditable() throws {
        var state = Self.archived
        try apply(.updateProject(.init(projectID: "work", name: "Job", color: .set("#123456"))), to: &state)
        try apply(.setProjectOutcome(project: "work", outcome: "Shipped"), to: &state)
        let project = try #require(state.projects["work"])
        #expect(project.name == "Job" && project.color == "#123456" && project.desiredOutcome == "Shipped")
        #expect(project.state == .archived)
    }
}
