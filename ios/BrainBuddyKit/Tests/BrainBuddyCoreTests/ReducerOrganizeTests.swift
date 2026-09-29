import Foundation
import Testing

@testable import BrainBuddyCore

@Suite("GTDReducer: projects")
struct ReducerProjectTests {
    @Test("A new project stores the server's display form of its name")
    func create() throws {
        var state = Fixture.base
        try apply(.createProject(.init(projectID: "p", name: "  Ｄｅｅｐ   work ", color: "#123456")), to: &state, at: 2)
        let project = try #require(state.projects["p"])
        #expect(project.name == "Deep work" && project.color == "#123456")
        #expect(project.state == .active && project.createdAt == Fixture.at(2) && project.serverID == nil)
    }

    @Test("Names are unique among active projects after NFKC, collapsing and case folding")
    func uniqueness() throws {
        var state = Fixture.base
        expectRejection(.createProject(.init(projectID: "p", name: " WORK ")), on: state, .duplicateProjectName("Work"))
        try apply(.createProject(.init(projectID: "old2", name: "old")), to: &state)
        #expect(state.projects["old2"]?.name == "old", "an archived project's name is free again")
        try apply(.createProject(.init(projectID: "s", name: "Straße")), to: &state)
        expectRejection(.createProject(.init(projectID: "t", name: "STRASSE")), on: state, .duplicateProjectName("Straße"))
    }

    @Test("In replay, a taken name merges into the existing project instead of creating one")
    func mergeInReplay() throws {
        var state = Fixture.base
        #expect(try apply(.createProject(.init(projectID: "p", name: "work")), to: &state, mode: .replay) == .mergedProject(into: "work"))
        #expect(state == Fixture.base)
    }

    @Test("Name and colour limits")
    func limits() {
        let state = Fixture.base
        expectRejection(.createProject(.init(projectID: "p", name: "")), on: state, .emptyName)
        expectRejection(.createProject(.init(projectID: "p", name: " \n ")), on: state, .emptyName)
        expectRejection(.createProject(.init(projectID: "p", name: String(repeating: "n", count: 501))), on: state, .nameTooLong)
        expectRejection(
            .createProject(.init(projectID: "p", name: "P", color: String(repeating: "c", count: 65))), on: state, .colorTooLong
        )
        expectRejection(.createProject(.init(projectID: "work", name: "Other")), on: state, .idAlreadyExists)
    }

    @Test("Rename and recolour, including a case-only rename of itself")
    func update() throws {
        var state = Fixture.base
        try apply(.updateProject(.init(projectID: "work", name: "WORK", color: .set("#00FF00"))), to: &state)
        #expect(state.projects["work"]?.name == "WORK" && state.projects["work"]?.color == "#00FF00")
        try apply(.updateProject(.init(projectID: "work", color: .clear)), to: &state)
        #expect(state.projects["work"]?.color == nil && state.projects["work"]?.name == "WORK")
        try apply(.createProject(.init(projectID: "home", name: "Home")), to: &state)
        expectRejection(.updateProject(.init(projectID: "work", name: "home")), on: state, .duplicateProjectName("Home"))
        expectRejection(.updateProject(.init(projectID: "work", name: " ")), on: state, .emptyName)
        expectRejection(.updateProject(.init(projectID: "missing", name: "X")), on: state, .projectNotFound)
    }

    @Test("Archived projects can be renamed, without a uniqueness check (server rule)")
    func renameArchived() throws {
        var state = Fixture.base
        try apply(.updateProject(.init(projectID: "old", name: "Work")), to: &state)
        #expect(state.projects["old"]?.name == "Work" && state.projects["old"]?.state == .archived)
    }

    @Test("An update that changes nothing: nothingToChange for the user, satisfied in replay")
    func noOpUpdate() throws {
        for command in [
            GTDCommand.updateProject(.init(projectID: "work")),
            .updateProject(.init(projectID: "work", name: " Work ", color: .clear)),
        ] {
            expectRejection(command, on: Fixture.base, .nothingToChange)
            var state = Fixture.base
            #expect(try apply(command, to: &state, mode: .replay) == .alreadySatisfied)
        }
    }

    @Test("Archiving removes the project from every task, open or terminal")
    func archive() throws {
        var state = Fixture.base
        try apply(.archiveProject("work"), to: &state, at: 7)
        #expect(state.projects["work"]?.state == .archived)
        for id: TaskID in ["inbox", "done"] {
            #expect(state.tasks[id]?.projectID == nil)
            #expect(state.tasks[id]?.updatedAt == Fixture.at(7))
            #expect(state.tasks[id]?.state == Fixture.base.tasks[id]?.state, "tasks stay in their lists")
        }
        #expect(state.tasks["next"] == Fixture.base.tasks["next"], "other tasks are untouched")
        expectRejection(.updateTask(.init(taskID: "next", changes: .init(projectID: .set("work")))), on: state, .projectNotActive)
        expectRejection(.archiveProject("work"), on: state, .projectAlreadyArchived)
        var replayed = state
        #expect(try apply(.archiveProject("work"), to: &replayed, mode: .replay) == .alreadySatisfied)
        #expect(replayed == state)
        expectRejection(.archiveProject("missing"), on: state, .projectNotFound, mode: .replay)
    }
}

@Suite("GTDReducer: tags")
struct ReducerTagTests {
    @Test("A new tag drops a leading @ and is unique among active tags")
    func create() throws {
        var state = Fixture.base
        try apply(.createTag(.init(tagID: "o", name: " @Office  hours ")), to: &state, at: 3)
        #expect(state.tags["o"]?.name == "Office hours" && state.tags["o"]?.createdAt == Fixture.at(3))
        expectRejection(.createTag(.init(tagID: "x", name: "@HOME")), on: state, .duplicateTagName("home"))
        expectRejection(.createTag(.init(tagID: "x", name: "@")), on: state, .emptyName)
        expectRejection(.createTag(.init(tagID: "home", name: "Other")), on: state, .idAlreadyExists)
        try apply(.createTag(.init(tagID: "g", name: "Gone")), to: &state)
        #expect(state.tags["g"]?.state == .active, "a deleted tag's name is free again")
    }

    @Test("In replay, a taken name merges into the existing tag")
    func mergeInReplay() throws {
        var state = Fixture.base
        #expect(try apply(.createTag(.init(tagID: "t", name: "Home")), to: &state, mode: .replay) == .mergedTag(into: "home"))
        #expect(state == Fixture.base)
    }

    @Test("Rename keeps uniqueness among active tags; deleted tags can be renamed")
    func rename() throws {
        var state = Fixture.base
        try apply(.createTag(.init(tagID: "p", name: "phone")), to: &state)
        try apply(.renameTag(.init(tagID: "p", name: "@Calls")), to: &state)
        #expect(state.tags["p"]?.name == "Calls")
        try apply(.renameTag(.init(tagID: "home", name: "HOME")), to: &state)
        #expect(state.tags["home"]?.name == "HOME")
        expectRejection(.renameTag(.init(tagID: "p", name: "home")), on: state, .duplicateTagName("HOME"))
        try apply(.renameTag(.init(tagID: "gone", name: "home")), to: &state)
        #expect(state.tags["gone"]?.name == "home" && state.tags["gone"]?.state == .deleted)
        expectRejection(.renameTag(.init(tagID: "p", name: "Calls")), on: state, .nothingToChange)
        var replayed = state
        #expect(try apply(.renameTag(.init(tagID: "p", name: "@Calls")), to: &replayed, mode: .replay) == .alreadySatisfied)
        expectRejection(.renameTag(.init(tagID: "missing", name: "X")), on: state, .tagNotFound)
    }

    @Test("Deleting a tag is a soft delete that removes it from every task")
    func delete() throws {
        var state = Fixture.base
        try apply(.deleteTag("home"), to: &state, at: 5)
        #expect(state.tags["home"]?.state == .deleted)
        for id: TaskID in ["inbox", "done"] {
            #expect(state.tasks[id]?.tagIDs == [])
            #expect(state.tasks[id]?.updatedAt == Fixture.at(5))
        }
        #expect(state.tasks["next"] == Fixture.base.tasks["next"])
        expectRejection(.deleteTag("home"), on: state, .tagAlreadyDeleted)
        var replayed = state
        #expect(try apply(.deleteTag("home"), to: &replayed, mode: .replay) == .alreadySatisfied)
        #expect(replayed == state)
        expectRejection(.deleteTag("missing"), on: state, .tagNotFound)
    }
}
