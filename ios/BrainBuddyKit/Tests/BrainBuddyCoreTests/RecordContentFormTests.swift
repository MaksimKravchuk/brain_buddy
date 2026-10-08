import Foundation
import Testing

@testable import BrainBuddyCore

@Suite("RecordContentForm")
struct RecordContentFormTests {
    /// A Waiting task in "Work" with two tags and two subtasks, under client ids `prefix`.
    private func world(prefix: String = "", mutate: (inout GTDState) -> Void = { _ in }) -> (GTDState, TaskID) {
        var task = Fixture.task(
            TaskID("\(prefix)t"), "Call Ana", state: .waiting, projectID: ProjectID("\(prefix)work"),
            tagIDs: [TagID("\(prefix)home"), TagID("\(prefix)phone")], waitingFor: "Ana",
            subtasks: [
                SubtaskRecord(id: SubtaskID("\(prefix)s1"), title: "Find the number", state: .completed, orderKey: 0),
                SubtaskRecord(id: SubtaskID("\(prefix)s2"), title: "Dial", state: .open, orderKey: 1),
            ]
        )
        task.details = "Before noon"
        task.dueDate = CalendarDay(year: 2026, month: 10, day: 20)
        task.priority = .high
        var state = Fixture.state(
            tasks: [task],
            projects: [Fixture.project(ProjectID("\(prefix)work"), "Work")],
            tags: [Fixture.tag(TagID("\(prefix)home"), "home"), Fixture.tag(TagID("\(prefix)phone"), "phone")]
        )
        mutate(&state)
        return (state, task.id)
    }

    private func bytes(_ mutate: (inout GTDState) -> Void = { _ in }, prefix: String = "") -> [UInt8] {
        let (state, id) = world(prefix: prefix, mutate: mutate)
        return RecordContentForm.bytes(of: state.tasks[id]!, in: state)
    }

    @Test("021-FR-023 the bytes ignore ids, server ids and revisions, server times and re-keying")
    func unchangedByServerFacts() {
        let base = bytes()
        #expect(bytes { $0.tasks["t"]?.updatedAt = Fixture.at(500) } == base, "a pull that changes only updatedAt")
        #expect(bytes { $0.tasks["t"]?.serverID = "task_other"; $0.tasks["t"]?.serverRevision = 99 } == base)
        #expect(bytes { $0.tasks["t"]?.createdAt = Fixture.at(-5); $0.tasks["t"]?.orderKey = 40 } == base)
        #expect(bytes { $0.projects["work"]?.serverID = nil; $0.projects["work"]?.serverRevision = nil } == base)
        #expect(bytes(prefix: "again-") == base, "sign-out and sign-in: the same content under new client ids")
        #expect(bytes { $0.tasks["t"]?.tagIDs = ["phone", "home"] } == base, "tags are by name, not by order")
    }

    @Test("021-FR-023 an edit of any listed field changes the bytes")
    func changedByAnyListedField() {
        let base = bytes()
        let edits: [(String, (inout GTDState) -> Void)] = [
            ("title", { $0.tasks["t"]?.title = "Call Bob" }),
            ("notes", { $0.tasks["t"]?.details = nil }),
            ("list", { $0.tasks["t"]?.state = .next; $0.tasks["t"]?.waitingFor = nil }),
            ("waiting-for", { $0.tasks["t"]?.waitingFor = "Bob" }),
            ("due date", { $0.tasks["t"]?.dueDate = nil }),
            ("priority", { $0.tasks["t"]?.priority = .low }),
            ("project", { $0.tasks["t"]?.projectID = nil }),
            ("project name", { $0.projects["work"]?.name = "Job" }),
            ("tag name", { $0.tags["home"]?.name = "house" }),
            ("tag set", { $0.tasks["t"]?.tagIDs = ["home"] }),
            ("subtask title", { $0.tasks["t"]?.subtasks[1].title = "Dial again" }),
            ("subtask state", { $0.tasks["t"]?.subtasks[1].state = .completed }),
            ("subtask added", { $0.tasks["t"]?.subtasks.append(SubtaskRecord(id: "s3", title: "Talk", orderKey: 2)) }),
        ]
        for (field, edit) in edits { #expect(bytes(edit) != base, "\(field)") }
    }

    @Test("021-FR-023 length prefixes keep different field sets apart")
    func lengthPrefixes() {
        let first = bytes { $0.tasks["t"]?.title = "ab"; $0.tasks["t"]?.details = "c" }
        let second = bytes { $0.tasks["t"]?.title = "a"; $0.tasks["t"]?.details = "bc" }
        #expect(first != second)
        let none = bytes { $0.tasks["t"]?.details = nil }
        let empty = bytes { $0.tasks["t"]?.details = "" }
        #expect(none != empty, "no notes is not empty notes")
    }

    @Test("021-FR-023 a project's bytes are the sorted bytes of its tasks, whatever their ids or order")
    func projectBytes() {
        func project(_ ids: [TaskID], titles: [String]) -> [UInt8] {
            let tasks = zip(ids, titles).map { Fixture.task($0, $1, state: .next, projectID: "work") }
            let state = Fixture.state(tasks: tasks, projects: [Fixture.project("work", "Work")])
            return RecordContentForm.bytes(ofTasksIn: "work", in: state)
        }
        let base = project(["a", "b"], titles: ["First", "Second"])
        #expect(project(["x", "y"], titles: ["Second", "First"]) == base)
        #expect(project(["a", "b"], titles: ["First", "Third"]) != base)
        #expect(project(["a", "b", "c"], titles: ["First", "Second", "First"]) != base)
        #expect(RecordContentForm.bytes(ofTasksIn: "none", in: .empty).isEmpty)
    }
}
