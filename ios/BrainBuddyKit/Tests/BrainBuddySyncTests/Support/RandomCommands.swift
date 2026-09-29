import BrainBuddyCore
import Foundation

/// Random commands against a device's current state, mostly valid (the
/// reducer rejects the rest before they reach the outbox). Titles, subtask
/// titles and comment bodies are unique per device and step, so a duplicated
/// create shows up on the server as a repeated title; project and tag names
/// come from a small pool that collides on purpose (case, `@`, spaces).
struct RandomCommands {
    var rng: SeededGenerator
    let device: String
    private var serial = 0

    init(seed: UInt64, device: String) {
        rng = SeededGenerator(seed: seed)
        self.device = device
    }

    private static let projectNames = ["Work", "work", "Home", " Home ", "Garden", "Errands"]
    private static let tagNames = ["@home", "Home", "phone", "Phone", "calls", "@Office"]
    private static let colors: [String?] = ["#0EA5E9", "#F97316", nil]
    private static let people = ["Bob", "  Ana ", "The bank"]

    mutating func next(for state: GTDState) -> GTDCommand {
        serial += 1
        let stamp = "\(device)-\(serial)"
        let tasks = state.tasks.values.sorted { $0.id < $1.id }
        let projects = state.projects.values.filter { $0.state == .active }.sorted { $0.id < $1.id }.map(\.id)
        let tags = state.tags.values.filter { $0.state == .active }.sorted { $0.id < $1.id }.map(\.id)
        let roll = Int.random(in: 0..<100, using: &rng)
        guard roll >= 16, let task = tasks.randomElement(using: &rng) else {
            return createTask(stamp, projects, tags)
        }
        switch roll {
        case 16..<32:
            return updateTask(task, stamp, projects, tags)
        case 32..<48:
            return transition(task)
        case 48..<53:
            return .createProject(
                .init(projectID: ProjectID("\(stamp)-project"), name: pick(Self.projectNames), color: pick(Self.colors))
            )
        case 53..<56:
            guard let id = projects.randomElement(using: &rng) else { break }
            return .updateProject(
                .init(projectID: id, name: chance(60) ? pick(Self.projectNames) : nil, color: fieldChange(Self.colors))
            )
        case 56..<58:
            guard let id = projects.randomElement(using: &rng) else { break }
            return .archiveProject(id)
        case 58..<63:
            return .createTag(.init(tagID: TagID("\(stamp)-tag"), name: pick(Self.tagNames)))
        case 63..<65:
            guard let id = tags.randomElement(using: &rng) else { break }
            return .renameTag(.init(tagID: id, name: pick(Self.tagNames)))
        case 65..<67:
            guard let id = tags.randomElement(using: &rng) else { break }
            return .deleteTag(id)
        case 67..<75:
            return .createSubtask(.init(taskID: task.id, subtaskID: SubtaskID("\(stamp)-subtask"), title: "\(stamp) step"))
        case 75..<80:
            guard let subtask = task.subtasks.randomElement(using: &rng) else { break }
            return .updateSubtask(.init(taskID: task.id, subtaskID: subtask.id, title: "\(stamp) renamed"))
        case 80..<86:
            guard let subtask = task.subtasks.randomElement(using: &rng) else { break }
            let action = pick([SubtaskTransitionAction.complete, .cancel, .reopen].filter { $0.targetState != subtask.state })
            return .transitionSubtask(.init(taskID: task.id, subtaskID: subtask.id, action: action))
        case 86..<93:
            return .createComment(.init(taskID: task.id, commentID: CommentID("\(stamp)-comment"), body: "\(stamp) note"))
        default:
            guard let comment = task.comments.randomElement(using: &rng) else { break }
            return .updateComment(.init(taskID: task.id, commentID: comment.id, body: "\(stamp) edited"))
        }
        return createTask(stamp, projects, tags)
    }

    private mutating func createTask(_ stamp: String, _ projects: [ProjectID], _ tags: [TagID]) -> GTDCommand {
        let list = pick(OpenList.allCases)
        return .createTask(
            .init(
                taskID: TaskID("\(stamp)-task"), title: chance(20) ? "  \(stamp)  " : stamp,
                details: chance(30) ? pick(["Notes", "", "Before noon"]) : nil, list: list,
                waitingFor: list == .waiting ? pick(Self.people) : nil,
                dueDate: chance(30) ? CalendarDay(year: 2026, month: 10, day: Int.random(in: 1...28, using: &rng)) : nil,
                priority: pick(TaskPriority.allCases), projectID: chance(40) ? projects.randomElement(using: &rng) : nil,
                tagIDs: subset(tags)
            )
        )
    }

    private mutating func updateTask(
        _ task: TaskRecord, _ stamp: String, _ projects: [ProjectID], _ tags: [TagID]
    ) -> GTDCommand {
        var changes = TaskChanges()
        if chance(40) { changes.title = .set("\(stamp) title") }
        if chance(25) { changes.details = fieldChange(["Edited notes", "", nil]) }
        if chance(25) { changes.projectID = chance(70) ? projects.randomElement(using: &rng).map { .set($0) } ?? .clear : .clear }
        if chance(25) { changes.tagIDs = chance(80) ? .set(subset(tags)) : .clear }
        if chance(20) { changes.dueDate = chance(70) ? .set(CalendarDay(year: 2026, month: 11, day: 2)!) : .clear }
        if chance(25) { changes.priority = .set(pick(TaskPriority.allCases)) }
        if task.state == .waiting, chance(40) { changes.waitingFor = .set(pick(Self.people)) }
        if !changes.hasChanges { changes.title = .set("\(stamp) title") }
        return .updateTask(.init(taskID: task.id, changes: changes))
    }

    private mutating func transition(_ task: TaskRecord) -> GTDCommand {
        guard let current = task.openList else {
            let list = pick(OpenList.allCases)
            return .transitionTask(
                .init(taskID: task.id, action: .reopen, toList: list, waitingFor: list == .waiting ? pick(Self.people) : nil)
            )
        }
        switch Int.random(in: 0..<10, using: &rng) {
        case 0..<5:
            let list = pick(OpenList.allCases.filter { $0 != current })
            return .transitionTask(
                .init(taskID: task.id, action: .move, toList: list, waitingFor: list == .waiting ? pick(Self.people) : nil)
            )
        case 5..<8:
            return .transitionTask(.init(taskID: task.id, action: .complete))
        default:
            return .transitionTask(.init(taskID: task.id, action: .cancel))
        }
    }

    private mutating func fieldChange<Value: Hashable & Sendable & Codable>(_ values: [Value?]) -> FieldChange<Value> {
        guard let value = pick(values) else { return .clear }
        return .set(value)
    }

    private mutating func subset<Value>(_ values: [Value]) -> [Value] {
        values.filter { _ in chance(30) }
    }

    mutating func pick<Value>(_ values: [Value]) -> Value { values.randomElement(using: &rng)! }
    mutating func chance(_ percent: Int) -> Bool { Int.random(in: 0..<100, using: &rng) < percent }
}
