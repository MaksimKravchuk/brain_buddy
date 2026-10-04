import Foundation
import Testing

@testable import BrainBuddyCore

/// Deterministic records, dates and helpers for the GTD rules tests.
enum Fixture {
    static let epoch = Date(timeIntervalSince1970: 1_790_000_000)

    /// `minute` minutes after a fixed epoch, so tests never depend on the clock.
    static func at(_ minute: Int) -> Date { epoch.addingTimeInterval(TimeInterval(minute * 60)) }

    static func task(
        _ id: TaskID, _ title: String = "Task", state: TaskState = .inbox, orderKey: Int = 0,
        projectID: ProjectID? = nil, tagIDs: [TagID] = [], waitingFor: String? = nil,
        subtasks: [SubtaskRecord] = [], comments: [CommentRecord] = []
    ) -> TaskRecord {
        TaskRecord(
            id: id, serverID: "task_\(id)", serverRevision: 3, title: title, state: state,
            projectID: projectID, tagIDs: tagIDs, waitingFor: waitingFor,
            waitingSince: waitingFor == nil ? nil : at(-60),
            completedAt: state == .completed ? at(-30) : nil, cancelledAt: state == .cancelled ? at(-30) : nil,
            orderKey: orderKey, createdAt: at(-120), updatedAt: at(-120), subtasks: subtasks, comments: comments
        )
    }

    static func project(_ id: ProjectID, _ name: String, state: ProjectState = .active) -> ProjectRecord {
        ProjectRecord(id: id, serverID: "project_\(id)", serverRevision: 1, name: name, state: state, createdAt: at(-200))
    }

    static func tag(_ id: TagID, _ name: String, state: TagState = .active) -> TagRecord {
        TagRecord(id: id, serverID: "tag_\(id)", serverRevision: 1, name: name, state: state, createdAt: at(-200))
    }

    static func state(
        tasks: [TaskRecord] = [], projects: [ProjectRecord] = [], tags: [TagRecord] = []
    ) -> GTDState {
        GTDState(
            tasks: Dictionary(uniqueKeysWithValues: tasks.map { ($0.id, $0) }),
            projects: Dictionary(uniqueKeysWithValues: projects.map { ($0.id, $0) }),
            tags: Dictionary(uniqueKeysWithValues: tags.map { ($0.id, $0) })
        )
    }

    /// A small server-confirmed dataset: projects Work (active) and Old (archived),
    /// tags home (active) and gone (deleted), and one task per state.
    static var base: GTDState {
        state(
            tasks: [
                task("inbox", "Inbox task", state: .inbox, orderKey: 4, projectID: "work", tagIDs: ["home"]),
                task("next", "Next task", state: .next, orderKey: 2),
                task("waiting", "Waiting task", state: .waiting, orderKey: 7, waitingFor: "Ana"),
                task("someday", "Someday task", state: .someday),
                task("done", "Done task", state: .completed, projectID: "work", tagIDs: ["home"]),
                task("dropped", "Dropped task", state: .cancelled),
            ],
            projects: [project("work", "Work"), project("old", "Old", state: .archived)],
            tags: [tag("home", "home"), tag("gone", "gone", state: .deleted)]
        )
    }

    static func operation(_ command: GTDCommand, at minute: Int, sent: Bool = false) -> PendingOperation {
        PendingOperation(command: command, issuedAt: at(minute), attempts: sent ? 1 : 0)
    }

    /// Appends each command through the compactor, issued one minute apart.
    static func compacted(_ commands: [GTDCommand], startingAt minute: Int = 0) -> [PendingOperation] {
        commands.enumerated().reduce(into: []) { outbox, item in
            outbox = OutboxCompactor.appending(operation(item.element, at: minute + item.offset), to: outbox)
        }
    }
}

/// Applies `command` at `minute` in `mode`.
@discardableResult
func apply(
    _ command: GTDCommand, to state: inout GTDState, at minute: Int = 1, mode: ApplyMode = .interactive
) throws(GTDValidationError) -> ApplyOutcome {
    try GTDReducer.apply(command, at: Fixture.at(minute), to: &state, mode: mode)
}

/// Expects `command` to fail with `error` and to leave `state` untouched.
func expectRejection(
    _ command: GTDCommand, on state: GTDState, _ error: GTDValidationError, mode: ApplyMode = .interactive,
    sourceLocation: SourceLocation = #_sourceLocation
) {
    var copy = state
    #expect(throws: error, sourceLocation: sourceLocation) {
        try GTDReducer.apply(command, at: Fixture.at(99), to: &copy, mode: mode)
    }
    #expect(copy == state, "a rejected command must not change the state", sourceLocation: sourceLocation)
}

extension GTDState {
    /// The state without the fields the compactor may legitimately change
    /// because the server assigns them when a request lands: `updatedAt`,
    /// `orderKey`, the time of `waitingSince` (not whether it is set) and a
    /// comment's `editedAt`.
    var ignoringServerAssignedFields: GTDState {
        var copy = self
        for id in copy.tasks.keys {
            copy.tasks[id]!.orderKey = 0
            copy.tasks[id]!.updatedAt = Fixture.epoch
            copy.tasks[id]!.waitingSince = copy.tasks[id]!.waitingSince.map { _ in Fixture.epoch }
            for index in copy.tasks[id]!.comments.indices { copy.tasks[id]!.comments[index].editedAt = nil }
        }
        return copy
    }
}

/// SplitMix64: a tiny seeded generator, so property tests are reproducible.
struct SeededGenerator: RandomNumberGenerator {
    private var state: UInt64
    init(seed: UInt64) { state = seed }

    mutating func next() -> UInt64 {
        state &+= 0x9E37_79B9_7F4A_7C15
        var value = state
        value = (value ^ (value >> 30)) &* 0xBF58_476D_1CE4_E5B9
        value = (value ^ (value >> 27)) &* 0x94D0_49BB_1331_11EB
        return value ^ (value >> 31)
    }
}

/// Random commands against the current state: mostly valid, some not (the
/// reducer rejects those), with colliding names to exercise uniqueness. Most
/// task commands target one of the last few tasks used, so histories contain
/// the interleavings folding has to respect (edit, move, edit the same task).
struct CommandGenerator {
    var rng: SeededGenerator
    private var serial = 0
    private var recent: [TaskID] = []

    init(seed: UInt64) { rng = SeededGenerator(seed: seed) }

    private static let titles = ["Call Ana", "  Buy milk ", "Draft plan", "Review", "   "]
    private static let details: [String?] = ["", "Notes", "Before noon", nil]
    private static let waiting: [String?] = ["Bob", "  Ana ", "   ", nil]
    private static let projectNames = ["Work", "work", "Home", " Home ", "Straße", "STRASSE", "Errands"]
    private static let tagNames = ["@home", "Home", "phone", "Phone", "office", "@Office", "calls"]
    private static let colors: [String?] = ["#FF0000", "#00AA00", nil]

    mutating func next(for state: GTDState) -> GTDCommand {
        serial += 1
        let tasks = state.tasks.keys.sorted()
        // Oldest first, so `likelyNewest` can favour a project or tag created
        // moments ago (an edit referencing it must stay after its creation).
        let projects = state.projects.values.sorted { ($0.createdAt, $0.id) < ($1.createdAt, $1.id) }.map(\.id)
        let tags = state.tags.values.sorted { ($0.createdAt, $0.id) < ($1.createdAt, $1.id) }.map(\.id)
        let roll = Int.random(in: 0..<100, using: &rng)
        recent.removeAll { state.tasks[$0] == nil }
        let focused = chance(75) ? recent.randomElement(using: &rng) : nil
        guard let taskID = focused ?? tasks.randomElement(using: &rng), roll >= 15 else {
            return createTask(projects, tags)
        }
        remember(taskID)
        let task = state.tasks[taskID]!
        switch roll {
        case 15..<37: return updateTask(taskID, task, projects, tags)
        case 37..<60: return transitionTask(taskID)
        case 60..<65: return .createProject(.init(projectID: ProjectID("project-\(serial)"), name: pick(Self.projectNames)))
        case 65..<69:
            guard let id = projects.randomElement(using: &rng) else { break }
            return .updateProject(
                .init(projectID: id, name: chance(50) ? pick(Self.projectNames) : nil, color: fieldChange(Self.colors))
            )
        case 69..<71:
            guard let id = projects.randomElement(using: &rng) else { break }
            return .archiveProject(id)
        case 71..<76: return .createTag(.init(tagID: TagID("tag-\(serial)"), name: pick(Self.tagNames)))
        case 76..<79:
            guard let id = tags.randomElement(using: &rng) else { break }
            return .renameTag(.init(tagID: id, name: pick(Self.tagNames)))
        case 79..<81:
            guard let id = tags.randomElement(using: &rng) else { break }
            return .deleteTag(id)
        case 81..<86:
            return .createSubtask(.init(taskID: taskID, subtaskID: SubtaskID("subtask-\(serial)"), title: pick(Self.titles)))
        case 86..<89:
            guard let subtask = task.subtasks.randomElement(using: &rng) else { break }
            return .updateSubtask(.init(taskID: taskID, subtaskID: subtask.id, title: pick(Self.titles)))
        case 89..<93:
            guard let subtask = task.subtasks.randomElement(using: &rng) else { break }
            let action = pick([SubtaskTransitionAction.complete, .cancel, .reopen])
            return .transitionSubtask(.init(taskID: taskID, subtaskID: subtask.id, action: action))
        case 93..<97:
            return .createComment(.init(taskID: taskID, commentID: CommentID("comment-\(serial)"), body: pick(["Hi", " ", ""])))
        default:
            guard let comment = task.comments.randomElement(using: &rng) else { break }
            return .updateComment(.init(taskID: taskID, commentID: comment.id, body: pick(["Edited", "Hi", "Again"])))
        }
        return createTask(projects, tags)
    }

    private mutating func remember(_ id: TaskID) {
        recent.removeAll { $0 == id }
        recent.append(id)
        if recent.count > 3 { recent.removeFirst() }
    }

    private mutating func createTask(_ projects: [ProjectID], _ tags: [TagID]) -> GTDCommand {
        let id = TaskID("task-\(serial)")
        remember(id)
        return .createTask(
            .init(
                taskID: id, title: pick(Self.titles), details: pick(Self.details),
                list: pick(OpenList.allCases), waitingFor: pick(Self.waiting),
                dueDate: chance(30) ? CalendarDay(year: 2026, month: 10, day: Int.random(in: 1...28, using: &rng)) : nil,
                priority: pick(TaskPriority.allCases), projectID: chance(40) ? likelyNewest(projects) : nil,
                tagIDs: subset(tags)
            )
        )
    }

    private mutating func updateTask(
        _ id: TaskID, _ task: TaskRecord, _ projects: [ProjectID], _ tags: [TagID]
    ) -> GTDCommand {
        var changes = TaskChanges()
        if chance(35) { changes.title = .set(pick(Self.titles)) }
        if chance(25) { changes.details = fieldChange(Self.details) }
        if chance(25), let project = likelyNewest(projects) {
            changes.projectID = chance(70) ? .set(project) : .clear
        }
        if chance(25) { changes.tagIDs = chance(80) ? .set(subset(tags)) : .clear }
        if chance(20) { changes.dueDate = chance(70) ? .set(CalendarDay(year: 2026, month: 11, day: 2)!) : .clear }
        if chance(25) { changes.priority = .set(pick(TaskPriority.allCases)) }
        if chance(task.state == .waiting ? 50 : 5) { changes.waitingFor = fieldChange(Self.waiting) }
        return .updateTask(.init(taskID: id, changes: changes))
    }

    private mutating func transitionTask(_ id: TaskID) -> GTDCommand {
        let action = pick([TaskTransitionAction.move, .move, .complete, .cancel, .reopen, .reopen])
        return .transitionTask(
            .init(taskID: id, action: action, toList: chance(95) ? pick(OpenList.allCases) : nil, waitingFor: pick(Self.waiting))
        )
    }

    private mutating func fieldChange<Value: Hashable & Sendable & Codable>(_ values: [Value?]) -> FieldChange<Value> {
        guard let value = pick(values) else { return .clear }
        return .set(value)
    }

    private mutating func likelyNewest<Value>(_ values: [Value]) -> Value? {
        chance(50) ? values.last : values.randomElement(using: &rng)
    }

    private mutating func subset<Value>(_ values: [Value]) -> [Value] {
        let newest = chance(40) ? values.suffix(1) : []
        return (values.dropLast().filter { _ in chance(25) } + newest).shuffled(using: &rng)
    }

    private mutating func pick<Value>(_ values: [Value]) -> Value { values.randomElement(using: &rng)! }
    private mutating func chance(_ percent: Int) -> Bool { Int.random(in: 0..<100, using: &rng) < percent }
}
