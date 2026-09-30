import BrainBuddyAPI
import BrainBuddyCore
import Foundation

/// A request's query string, repeated names kept in order.
struct ListQuery: Sendable {
    var items: [(name: String, value: String)]

    init(_ url: URL) {
        let components = URLComponents(url: url, resolvingAgainstBaseURL: false)
        items = (components?.queryItems ?? []).map { ($0.name, $0.value ?? "") }
    }

    func values(_ name: String) -> [String] { items.filter { $0.name == name }.map(\.value) }
    func value(_ name: String) -> String? { values(name).last }

    /// FastAPI's bool parsing.
    func bool(_ name: String) throws(FakeHTTPError) -> Bool {
        guard let raw = value(name)?.lowercased() else { return false }
        switch raw {
        case "true", "1", "yes", "on", "t", "y": return true
        case "false", "0", "no", "off", "f", "n": return false
        default: throw .validation(["query", name], "Input should be a valid boolean", type: "bool_parsing")
        }
    }

    func day(_ name: String) throws(FakeHTTPError) -> CalendarDay? {
        guard let raw = value(name) else { return nil }
        guard let day = CalendarDay(isoString: raw) else {
            throw .validation(["query", name], "Input should be a valid date", type: "date_parsing")
        }
        return day
    }
}

/// One element of a manual/due/priority/title sort key, compared like a Python tuple item.
enum SortPart: Comparable, Sendable {
    case int(Int)
    case string(String)

    var json: JSONValue {
        switch self {
        case .int(let value): .number(Double(value))
        case .string(let value): .string(value)
        }
    }

    init?(_ json: JSONValue) {
        switch json {
        case .number(let value) where value.rounded() == value: self = .int(Int(value))
        case .string(let value): self = .string(value)
        default: return nil
        }
    }
}

/// `GET /tasks` (`TaskService.list_tasks`): filters, four sorts, keyset
/// pagination with an opaque cursor bound to the filters, open counts.
extension ServerState {
    private static let priorityRank: [TaskPriority: Int] = [.high: 0, .medium: 1, .low: 2, .none: 3]

    func listTasks(_ query: ListQuery, owner: String) throws(FakeHTTPError) -> Reply {
        let data = data(owner)
        var state: TaskState?
        if let raw = query.value("state") {
            guard let value = TaskState(rawValue: raw) else {
                throw .validation(["query", "state"], "Input should be one of the allowed values", type: "literal_error")
            }
            state = value
        }
        let projectID = query.value("project_id")
        let tagID = query.value("tag_id")
        let unassigned = try query.bool("unassigned_project")
        let includeCompleted = try query.bool("include_completed")
        let includeCancelled = try query.bool("include_cancelled")
        let search = Self.normalizedSearch(query.value("q") ?? "")
        var priorities: [TaskPriority] = []
        for raw in query.values("priority") {
            guard let priority = TaskPriority(rawValue: raw) else {
                throw .validation(["query", "priority"], "Input should be one of the allowed values", type: "literal_error")
            }
            priorities.append(priority)
        }
        let dueBefore = try query.day("due_before")
        let dueOn = try query.day("due_on")
        let dueAfter = try query.day("due_after")
        let sort = query.value("sort") ?? "manual"
        guard ["manual", "due", "priority", "title"].contains(sort) else {
            throw .validation(["query", "sort"], "Input should be one of the allowed values", type: "literal_error")
        }
        var limit = 50
        if let raw = query.value("limit") {
            guard let value = Int(raw), (1...200).contains(value) else {
                throw .validation(["query", "limit"], "Input should be between 1 and 200", type: "less_than_equal")
            }
            limit = value
        }

        if projectID != nil, unassigned {
            throw .rejected("project_id and unassigned_project cannot be used together.")
        }
        if let projectID { _ = try data.project(projectID) }
        if let tagID { _ = try data.tag(tagID) }
        if [dueBefore, dueOn, dueAfter].compactMap({ $0 }).count > 1 {
            throw .rejected("Use only one due date filter at a time.")
        }
        guard Set(priorities).count == priorities.count else {
            throw .rejected("Priority filters cannot contain duplicates.")
        }

        let filters: JSONValue = .object([
            "state": state.map { .string($0.rawValue) } ?? .null,
            "project_id": projectID.map(JSONValue.string) ?? .null,
            "tag_id": tagID.map(JSONValue.string) ?? .null,
            "unassigned_project": .bool(unassigned),
            "include_completed": .bool(includeCompleted),
            "include_cancelled": .bool(includeCancelled),
            "q": .string(search),
            "priority": .array(priorities.map(\.rawValue).sorted().map(JSONValue.string)),
            "due_before": dueBefore.map { .string($0.isoString) } ?? .null,
            "due_on": dueOn.map { .string($0.isoString) } ?? .null,
            "due_after": dueAfter.map { .string($0.isoString) } ?? .null,
            "sort": .string(sort),
        ])
        var last: [SortPart]?
        if let cursor = query.value("cursor") { last = try Self.decodeCursor(cursor, filters) }

        var allowed: Set<TaskState> = state.map { [$0] } ?? [.inbox, .next, .waiting, .someday]
        if includeCompleted { allowed.insert(.completed) }
        if includeCancelled { allowed.insert(.cancelled) }
        let matching = data.tasks.values.filter { task in
            (projectID == nil || task.projectID == projectID) && (tagID == nil || task.tagIDs.contains(tagID!))
                && (!unassigned || task.projectID == nil) && (search.isEmpty || Self.matches(task, search))
                && (priorities.isEmpty || priorities.contains(task.priority))
                && Self.matchesDue(task, before: dueBefore, on: dueOn, after: dueAfter)
        }
        var filtered = matching.filter { allowed.contains($0.state) }
            .map { (key: Self.sortKey($0, sort: sort), task: $0) }
            .sorted { $0.key.lexicographicallyPrecedes($1.key) }
        if let last { filtered.removeAll { !last.lexicographicallyPrecedes($0.key) } }
        let page = Array(filtered.prefix(limit))
        let hasMore = filtered.count > limit
        let nextCursor = hasMore ? page.last.map { Self.encodeCursor(filters, $0.key) } : nil
        var counts = TaskCountsDTO()
        for task in matching {
            switch task.state {
            case .inbox: counts.inbox += 1
            case .next: counts.next += 1
            case .waiting: counts.waiting += 1
            case .someday: counts.someday += 1
            case .completed, .cancelled: break
            }
        }
        return .json(
            200, TaskPageDTO(items: page.map { $0.task.dto() }, nextCursor: nextCursor, hasMore: hasMore, countsByState: counts)
        )
    }

    // MARK: - Helpers

    /// NFKC, whitespace collapsed, lowercased (the server case-folds).
    static func normalizedSearch(_ raw: String) -> String {
        PythonText.strip(raw).split(whereSeparator: { $0.unicodeScalars.allSatisfy(PythonText.isSpace) })
            .joined(separator: " ").precomposedStringWithCompatibilityMapping.lowercased()
    }

    static func matches(_ task: TaskRow, _ search: String) -> Bool {
        [task.title, task.details ?? ""].joined(separator: "\n").precomposedStringWithCompatibilityMapping.lowercased()
            .contains(search)
    }

    static func matchesDue(_ task: TaskRow, before: CalendarDay?, on: CalendarDay?, after: CalendarDay?) -> Bool {
        if let before { return task.dueDate.map { $0 < before } ?? false }
        if let on { return task.dueDate == on }
        if let after { return task.dueDate.map { $0 > after } ?? false }
        return true
    }

    /// `TaskService._sort_key`. `created_at` is compared as microseconds.
    static func sortKey(_ task: TaskRow, sort: String) -> [SortPart] {
        let micros = Int((task.createdAt.timeIntervalSince1970 * 1_000_000).rounded())
        let manual: [SortPart] = [.int(task.orderKey), .int(micros), .string(task.id)]
        switch sort {
        case "due":
            return [.int(task.dueDate == nil ? 1 : 0), .string(task.dueDate?.isoString ?? "")] + manual
        case "priority":
            return [.int(priorityRank[task.priority] ?? 3)] + manual
        case "title":
            return [.string(task.title.precomposedStringWithCompatibilityMapping.lowercased()), .string(task.id)]
        default:
            return manual
        }
    }

    static func encodeCursor(_ filters: JSONValue, _ last: [SortPart]) -> String {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        let payload: JSONValue = .object(["filters": filters, "last": .array(last.map(\.json))])
        let data = (try? encoder.encode(payload)) ?? Data()
        return data.base64EncodedString().replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
    }

    static func decodeCursor(_ cursor: String, _ filters: JSONValue) throws(FakeHTTPError) -> [SortPart] {
        let invalid = FakeHTTPError.rejected("Invalid or mismatched task cursor.")
        var base64 = cursor.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        while base64.count % 4 != 0 { base64 += "=" }
        guard let data = Data(base64Encoded: base64),
            let payload = try? JSONDecoder().decode(JSONValue.self, from: data),
            payload["filters"] == filters, case .array(let items)? = payload["last"], !items.isEmpty
        else { throw invalid }
        let parts = items.compactMap(SortPart.init)
        guard parts.count == items.count else { throw invalid }
        return parts
    }
}
