import Foundation
import Testing

@testable import BrainBuddyCore

/// The legacy Mac import's field transform (contracts/mac-legacy-import.md §2a, §6).
@Suite("ImportCanonicalizer")
struct ImportCanonicalizerTests {
    typealias Snapshot = ImportCanonicalizer.Snapshot

    private func canonical(
        projects: [ImportCanonicalizer.Project] = [], tags: [ImportCanonicalizer.Tag] = [],
        tasks: [ImportCanonicalizer.Task] = []
    ) -> ImportCanonicalizer.Result {
        ImportCanonicalizer.canonicalize(Snapshot(projects: projects, tags: tags, tasks: tasks))
    }

    private func task(
        title: String = "Task", details: String? = nil, state: String = "inbox", lastOpenState: String? = nil,
        projectID: String? = nil, tagIDs: [String] = [], dueDate: String? = nil, waitingFor: String? = nil,
        subtasks: [ImportCanonicalizer.Subtask] = [], comments: [ImportCanonicalizer.Comment] = []
    ) -> ImportCanonicalizer.Task {
        .init(
            id: "t", title: title, details: details, state: state, lastOpenState: lastOpenState, projectID: projectID,
            tagIDs: tagIDs, dueDate: dueDate, waitingFor: waitingFor, subtasks: subtasks, comments: comments
        )
    }

    private func entry(_ result: ImportCanonicalizer.Result, _ kind: String, original: String) -> ImportCanonicalizer.Adjustment? {
        result.adjustments.first { $0.kind == kind && $0.original == original }
    }

    // MARK: Names

    @Test("021-FR-020 project names take the server's display form", arguments: [
        ("Квартира №5", "Квартира No5"), ("™ Ideas", "TM Ideas"), ("Home  Repair", "Home Repair"), ("  ", "Untitled project"),
    ])
    func projectDisplayForm(legacy: String, expected: String) {
        let result = canonical(projects: [.init(id: "p", name: legacy)])
        #expect(result.snapshot.projects.map(\.name) == [expected])
        #expect(entry(result, "project", original: legacy)?.result == expected)
    }

    @Test("021-FR-020 active projects that collide get the smallest free number; an archived namesake is left alone")
    func activeDuplicates() {
        let result = canonical(
            projects: [
                .init(id: "a", name: "Home  Repair"), .init(id: "b", name: "Home Repair"),
                .init(id: "c", name: "Home Repair", isArchived: true), .init(id: "d", name: "home repair (2)"),
            ]
        )
        #expect(result.snapshot.projects.map(\.name) == ["Home Repair", "Home Repair (2)", "Home Repair", "home repair (2) (2)"])
        #expect(entry(result, "project", original: "Home Repair")?.result == "Home Repair (2)")
    }

    @Test("021-FR-020 tags lose a leading @ and collide the same way")
    func tags() {
        let result = canonical(
            tags: [.init(id: "1", name: "@home"), .init(id: "2", name: "home"), .init(id: "3", name: "Errands "), .init(id: "4", name: "old", isDeleted: true)]
        )
        #expect(result.snapshot.tags.map(\.name) == ["home", "home (2)", "Errands"])
        #expect(entry(result, "tag", original: "@home")?.result == "home")
        #expect(entry(result, "tag", original: "Errands ")?.result == "Errands")
        #expect(canonical(tags: [.init(id: "1", name: "@")]).snapshot.tags.map(\.name) == ["Untitled tag"])
    }

    @Test("021-FR-020 a name over 500 scalars is cut so the kit stores exactly what is reported, and it validates")
    func longNamesValidate() throws {
        let long = String(repeating: "™", count: 300) + " " + String(repeating: "x", count: 400)
        let result = canonical(
            projects: [.init(id: "a", name: long), .init(id: "b", name: long)],
            tags: [.init(id: "t", name: String(repeating: "👍🏽", count: 400))]
        )
        var state = GTDState()
        for (index, project) in result.snapshot.projects.enumerated() {
            #expect(project.name.unicodeScalars.count <= GTDLimits.name)
            try apply(.createProject(.init(projectID: ProjectID("p\(index)"), name: project.name)), to: &state)
            #expect(state.projects[ProjectID("p\(index)")]?.name == project.name, "the reducer stores it as is")
        }
        let tag = try #require(result.snapshot.tags.first)
        try apply(.createTag(.init(tagID: "t", name: tag.name)), to: &state)
        #expect(state.tags["t"]?.name == tag.name)
        #expect(result.snapshot.projects[1].name.hasSuffix(" (2)"))
    }

    // MARK: Titles, notes and comments

    @Test("021-FR-020 a title of 500 emoji graphemes is cut within 500 scalars with an ellipsis, and the full title leads the notes")
    func longTitle() throws {
        let original = String(repeating: "👍🏽", count: 500)
        #expect(original.unicodeScalars.count == 1_000)
        let result = canonical(tasks: [task(title: original, details: "My notes")])
        let task = try #require(result.snapshot.tasks.first)
        #expect(task.title.unicodeScalars.count <= 500 && task.title.hasSuffix("…"))
        #expect(task.title.dropLast().allSatisfy { $0 == "👍🏽" }, "no grapheme is split")
        #expect(task.details == "Full title: \(original)\n\nMy notes")
        #expect(entry(result, "task title", original: original) != nil)
    }

    @Test("021-FR-020 titles are not collapsed, only trimmed; an empty one is Untitled task")
    func titlesKeepTheirSpaces() {
        let result = canonical(tasks: [task(title: "Call  mom"), task(title: " \n ")])
        #expect(result.snapshot.tasks.map(\.title) == ["Call  mom", "Untitled task"])
        #expect(entry(result, "task title", original: "Call  mom") == nil)
    }

    @Test("021-FR-020 notes over 20,000 scalars keep the first part and continue in comments that together equal the original")
    func longNotes() throws {
        let original = (0..<25_000).map { String($0 % 10) }.joined()
        let result = canonical(tasks: [task(details: original)])
        let task = try #require(result.snapshot.tasks.first)
        let notes = try #require(task.details)
        #expect(notes.unicodeScalars.count <= 20_000)
        let continued = task.comments.map(\.body)
        #expect(continued.count == 1 && continued[0].hasPrefix("Notes, continued (1 of 1):"))
        #expect(notes + continued[0].dropFirst("Notes, continued (1 of 1):\n".count) == original)
        #expect(continued.allSatisfy { $0.unicodeScalars.count <= 20_000 })
    }

    @Test("021-FR-020 a comment over 20,000 scalars is split in two, and the second starts (continued)")
    func longComment() throws {
        let original = String(repeating: "c", count: 30_000)
        let result = canonical(tasks: [task(comments: [.init(id: "c", body: original)])])
        let comments = try #require(result.snapshot.tasks.first).comments.map(\.body)
        #expect(comments.count == 2 && comments[1].hasPrefix("(continued)"))
        #expect(comments.allSatisfy { $0.unicodeScalars.count <= 20_000 })
        #expect(comments[0] + comments[1].dropFirst("(continued)\n".count) == original)
        let own = canonical(tasks: [task(details: String(repeating: "n", count: 20_001), comments: [.init(id: "c", body: "mine")])])
        #expect(try #require(own.snapshot.tasks.first).comments.map(\.body).last == "mine", "the task's own comments come after the continuation")
    }

    @Test("021-FR-020 waiting-for is stripped, required in Waiting, cut at 500 with the original in the notes; subtasks too")
    func waitingAndSubtasks() throws {
        let long = String(repeating: "w", count: 600)
        let result = canonical(
            tasks: [
                task(state: "waiting", waitingFor: "  "), task(state: "waiting", waitingFor: long),
                task(state: "next", waitingFor: "ignored"),
                task(subtasks: [.init(id: "s", title: String(repeating: "s", count: 501))]),
            ]
        )
        let tasks = result.snapshot.tasks
        #expect(tasks[0].waitingFor == "(not recorded)")
        #expect(tasks[1].waitingFor?.unicodeScalars.count == 500 && tasks[1].waitingFor?.hasSuffix("…") == true)
        #expect(tasks[1].details == "Waiting for: \(long)")
        #expect(tasks[2].waitingFor == nil)
        #expect(tasks[3].subtasks[0].title.unicodeScalars.count == 500)
        #expect(tasks[3].details == "Full subtask title: \(String(repeating: "s", count: 501))")
    }

    // MARK: Outcome, colour and references

    @Test("021-FR-020 an outcome over 1,000 scalars is cut with an ellipsis and the report holds the full text")
    func longOutcome() throws {
        let original = String(repeating: "o", count: 1_200)
        let result = canonical(projects: [.init(id: "p", name: "P", desiredOutcome: original)])
        let outcome = try #require(result.snapshot.projects.first?.desiredOutcome)
        #expect(outcome.unicodeScalars.count == 1_000 && outcome.hasSuffix("…"))
        #expect(entry(result, "project outcome", original: original)?.result == outcome)
        #expect(canonical(projects: [.init(id: "p", name: "P", desiredOutcome: "  ")]).snapshot.projects[0].desiredOutcome == nil)
    }

    @Test("021-FR-020 a colour over 64 scalars is dropped and reported")
    func longColour() {
        let colour = String(repeating: "c", count: 100)
        let result = canonical(projects: [.init(id: "p", name: "P", color: colour), .init(id: "q", name: "Q", color: "#123456")])
        #expect(result.snapshot.projects.map(\.color) == [nil, "#123456"])
        #expect(entry(result, "project colour", original: colour) != nil)
    }

    @Test("021-FR-020 a missing project or tag reference is dropped and reported; a deleted tag is dropped quietly")
    func references() throws {
        let result = canonical(
            projects: [.init(id: "p", name: "P")],
            tags: [.init(id: "keep", name: "keep"), .init(id: "gone", name: "gone", isDeleted: true)],
            tasks: [task(projectID: "nope", tagIDs: ["keep", "gone", "missing"]), task(projectID: "p")]
        )
        let first = try #require(result.snapshot.tasks.first)
        #expect(first.projectID == nil && first.tagIDs == ["keep"])
        #expect(result.snapshot.tasks[1].projectID == "p")
        #expect(result.adjustments.filter { $0.kind == "task project reference" }.count == 1)
        #expect(result.adjustments.filter { $0.kind == "task tag reference" }.count == 1, "only the missing one")
    }

    @Test("021-FR-020 an unparseable due date is dropped; an unknown state is an open task in Inbox")
    func datesAndStates() {
        let result = canonical(
            tasks: [
                task(dueDate: "someday"), task(dueDate: "2026-10-20"), task(state: "archived"),
                task(state: "completed", lastOpenState: "next"), task(state: "completed", lastOpenState: "bogus"),
            ]
        )
        let tasks = result.snapshot.tasks
        #expect(tasks.map(\.dueDate) == [nil, "2026-10-20", nil, nil, nil])
        #expect(tasks[2].state == "inbox")
        #expect(tasks[3].state == "completed" && tasks[3].lastOpenState == "next")
        #expect(tasks[4].lastOpenState == nil)
        #expect(entry(result, "task due date", original: "someday") != nil)
        #expect(entry(result, "task state", original: "archived") != nil)
    }

    @Test("021-FR-020 the same snapshot twice gives identical output")
    func deterministic() {
        let snapshot = Snapshot(
            projects: [.init(id: "a", name: "Home  Repair"), .init(id: "b", name: "Home Repair")],
            tags: [.init(id: "t", name: "@home")],
            tasks: [task(title: String(repeating: "x", count: 600), details: String(repeating: "n", count: 30_000))]
        )
        #expect(ImportCanonicalizer.canonicalize(snapshot) == ImportCanonicalizer.canonicalize(snapshot))
        #expect(
            ImportCanonicalizer.canonicalize(ImportCanonicalizer.canonicalize(snapshot).snapshot).adjustments.isEmpty,
            "canonical output is its own fixed point"
        )
    }
}
