import Foundation

@testable import BrainBuddyCore

/// Builds `GTDState` values directly — no reducer — with deterministic ids,
/// order keys and timestamps: every record gets the next serial number, its
/// order key is `serial * 10` and it was created `serial` seconds after `epoch`.
struct QueryFixture {
    static let today = isoDay("2026-09-29")
    static let epoch = Date(timeIntervalSince1970: 1_790_000_000)

    private(set) var state = GTDState()
    private var serial = 0

    @discardableResult
    mutating func project(_ name: String, archived: Bool = false, id: ProjectID? = nil) -> ProjectID {
        serial += 1
        let id = id ?? ProjectID("project-\(serial)")
        state.projects[id] = ProjectRecord(
            id: id, name: name, state: archived ? .archived : .active, createdAt: Self.epoch)
        return id
    }

    @discardableResult
    mutating func tag(_ name: String, deleted: Bool = false, id: TagID? = nil) -> TagID {
        serial += 1
        let id = id ?? TagID("tag-\(serial)")
        state.tags[id] = TagRecord(id: id, name: name, state: deleted ? .deleted : .active, createdAt: Self.epoch)
        return id
    }

    /// A task; `ended` is the completion or cancellation time of a terminal task.
    @discardableResult
    mutating func task(
        _ title: String, _ taskState: TaskState = .next, id: TaskID? = nil, details: String? = nil,
        from lastOpenList: OpenList? = nil, project: ProjectID? = nil, tags: [TagID] = [],
        due: String? = nil, priority: TaskPriority = .none, orderKey: Int? = nil,
        createdAt: Date? = nil, ended: Date? = nil
    ) -> TaskID {
        serial += 1
        // Zero-padded so id order is creation order.
        let digits = String(serial)
        let id = id ?? TaskID("task-" + String(repeating: "0", count: max(0, 4 - digits.count)) + digits)
        let created = createdAt ?? Self.epoch.addingTimeInterval(TimeInterval(serial))
        state.tasks[id] = TaskRecord(
            id: id, title: title, details: details, state: taskState, lastOpenList: lastOpenList,
            projectID: project, tagIDs: tags, dueDate: due.map(isoDay), priority: priority,
            waitingFor: taskState == .waiting ? "Sam" : nil,
            waitingSince: taskState == .waiting ? created : nil,
            completedAt: taskState == .completed ? ended : nil,
            cancelledAt: taskState == .cancelled ? ended : nil,
            orderKey: orderKey ?? serial * 10, createdAt: created, updatedAt: created)
        return id
    }

    func list(
        _ destination: Destination, _ options: ListOptions = ListOptions(), today: CalendarDay = QueryFixture.today
    ) -> TaskListResult {
        GTDQueries.list(destination, options: options, in: state, today: today)
    }
}

func isoDay(_ iso: String) -> CalendarDay {
    guard let day = CalendarDay(isoString: iso) else { preconditionFailure("Bad fixture day \(iso)") }
    return day
}

/// `QueryFixture.epoch` plus `hours`, for completion and cancellation times.
func at(hours: Double) -> Date {
    QueryFixture.epoch.addingTimeInterval(hours * 3600)
}

extension TaskListResult {
    var sectionIDs: [String] { sections.map(\.id) }
    var sectionTitles: [String?] { sections.map(\.title) }
    /// Task titles per section, in order.
    var titles: [[String]] { sections.map { $0.tasks.map(\.title) } }
    var allTitles: [String] { sections.flatMap { $0.tasks.map(\.title) } }

    func titles(in sectionID: String) -> [String] {
        sections.first { $0.id == sectionID }?.tasks.map(\.title) ?? []
    }
}

/// SplitMix64: a small, seedable generator so generated datasets are the
/// same on every run and platform.
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
