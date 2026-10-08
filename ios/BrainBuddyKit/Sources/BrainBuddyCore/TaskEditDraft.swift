import Foundation

/// An editor's draft of a task: the fields as they were when the editor opened (the
/// baseline) and as the person has them now. `changes()` is only what the person
/// touched, so saving never writes back a stale value of a field they left alone
/// (FR-009); `rebased(onto:)` brings in what a pull changed meanwhile.
public struct TaskEditDraft: Hashable, Sendable {
    private struct Fields: Hashable, Sendable {
        public var title: String
        public var details: String?
        public var projectID: ProjectID?
        public var tagIDs: [TagID]
        public var dueDate: CalendarDay?
        public var priority: TaskPriority
        public var waitingFor: String?

        init(_ task: TaskRecord) {
            title = task.title
            details = task.details
            projectID = task.projectID
            tagIDs = task.tagIDs
            dueDate = task.dueDate
            priority = task.priority
            waitingFor = task.waitingFor
        }
    }

    private var baseline: Fields
    public var title: String
    public var details: String?
    public var projectID: ProjectID?
    public var tagIDs: [TagID]
    public var dueDate: CalendarDay?
    public var priority: TaskPriority
    public var waitingFor: String?

    public init(_ task: TaskRecord) {
        let fields = Fields(task)
        baseline = fields
        title = fields.title
        details = fields.details
        projectID = fields.projectID
        tagIDs = fields.tagIDs
        dueDate = fields.dueDate
        priority = fields.priority
        waitingFor = fields.waitingFor
    }

    /// The fields where the draft differs from the baseline: omitted, `null` (clear) or a value.
    public func changes() -> TaskChanges {
        TaskChanges(
            title: title == baseline.title ? .unchanged : .set(title),
            details: Self.change(details, from: baseline.details),
            projectID: Self.change(projectID, from: baseline.projectID),
            tagIDs: tagIDs == baseline.tagIDs ? .unchanged : (tagIDs.isEmpty ? .clear : .set(tagIDs)),
            dueDate: Self.change(dueDate, from: baseline.dueDate),
            priority: priority == baseline.priority ? .unchanged : .set(priority),
            waitingFor: Self.change(waitingFor, from: baseline.waitingFor)
        )
    }

    /// The draft against the `incoming` task (a pull changed it): a field the person has not touched
    /// shows the incoming value, one they have keeps what they typed. The baseline becomes the incoming task's.
    public func rebased(onto incoming: TaskRecord) -> TaskEditDraft {
        var result = TaskEditDraft(incoming)
        if title != baseline.title { result.title = title }
        if details != baseline.details { result.details = details }
        if projectID != baseline.projectID { result.projectID = projectID }
        if tagIDs != baseline.tagIDs { result.tagIDs = tagIDs }
        if dueDate != baseline.dueDate { result.dueDate = dueDate }
        if priority != baseline.priority { result.priority = priority }
        if waitingFor != baseline.waitingFor { result.waitingFor = waitingFor }
        return result
    }

    private static func change<Value: Hashable & Sendable & Codable>(
        _ value: Value?, from baseline: Value?
    ) -> FieldChange<Value> {
        guard value != baseline else { return .unchanged }
        return value.map { .set($0) } ?? .clear
    }
}

/// A selection or scroll position that survives a pull: it names a row by id, and when
/// that row has left the list it falls back to the nearest row that survived.
public struct SelectionAnchor<ID: Hashable & Sendable>: Hashable, Sendable {
    public let id: ID
    private let order: [ID]

    /// `order` is the list on screen when the anchor was taken.
    public init(id: ID, in order: [ID]) {
        self.id = id
        self.order = order.contains(id) ? order : []
    }

    /// The anchored row in `newOrder`, else the nearest neighbour it had that is still there (the row
    /// after, when equally near), else nil.
    public func resolved(in newOrder: [ID]) -> ID? {
        let present = Set(newOrder)
        if present.contains(id) { return id }
        guard let index = order.firstIndex(of: id) else { return nil }
        for distance in 1..<max(order.count, 1) {
            if index + distance < order.count, present.contains(order[index + distance]) { return order[index + distance] }
            if index - distance >= 0, present.contains(order[index - distance]) { return order[index - distance] }
        }
        return nil
    }
}
