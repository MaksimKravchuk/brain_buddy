import Foundation

/// Text folding for search and for title and name order. `locale: nil` keeps
/// the result identical on Apple platforms and Linux.
enum QueryText {
    /// NFKC, then case- and diacritic-insensitive folding: `Straße` → `strasse`,
    /// `Éclair` → `eclair`, full-width → ASCII. The server's search
    /// normalization (NFKC + casefold) plus diacritics.
    static func fold(_ text: String) -> String {
        text.precomposedStringWithCompatibilityMapping
            .folding(options: [.caseInsensitive, .diacriticInsensitive], locale: nil)
    }

    /// The query as the server normalizes it (trimmed, whitespace collapsed,
    /// folded), or nil when nothing is left to match.
    static func searchQuery(_ raw: String) -> String? {
        let query = collapsingWhitespace(fold(raw))
        return query.isEmpty ? nil : query
    }

    /// What a query is matched against: title and notes joined by a newline,
    /// which a collapsed query never contains, so a match cannot span both.
    static func searchHaystack(of task: TaskRecord) -> String {
        fold(task.title + "\n" + (task.details ?? ""))
    }

    static func collapsingWhitespace(_ text: String) -> String {
        text.split(whereSeparator: \.isWhitespace).joined(separator: " ")
    }
}

/// The task orders `TaskSort` names, plus recency for history. Every order
/// ends in the task id, so results never depend on dictionary order.
enum TaskOrdering {
    static func sorted(_ tasks: [TaskRecord], by sort: TaskSort) -> [TaskRecord] {
        switch sort {
        case .manual:
            return tasks.sorted(by: manualPrecedes)
        case .due:
            return tasks.sorted { lhs, rhs in
                switch (lhs.dueDate, rhs.dueDate) {
                case let (left?, right?) where left != right: left < right
                case (.some, nil): true
                case (nil, .some): false
                default: manualPrecedes(lhs, rhs)
                }
            }
        case .priority:
            return tasks.sorted { lhs, rhs in
                lhs.priority == rhs.priority
                    ? manualPrecedes(lhs, rhs) : lhs.priority.sortRank < rhs.priority.sortRank
            }
        case .title:
            // Fold each title once, not once per comparison.
            let keyed: [(key: String, task: TaskRecord)] = tasks.map { (QueryText.fold($0.title), $0) }
            return keyed.sorted(by: titlePrecedes).map(\.task)
        }
    }

    private static func titlePrecedes(_ lhs: (key: String, task: TaskRecord), _ rhs: (key: String, task: TaskRecord)) -> Bool {
        lhs.key == rhs.key ? lhs.task.id < rhs.task.id : lhs.key < rhs.key
    }

    /// Most recently completed or cancelled first, unknown times last, then id.
    static func byRecency(_ tasks: [TaskRecord]) -> [TaskRecord] {
        tasks.sorted { lhs, rhs in
            switch (endedAt(lhs), endedAt(rhs)) {
            case let (left?, right?) where left != right: left > right
            case (.some, nil): true
            case (nil, .some): false
            default: lhs.id < rhs.id
            }
        }
    }

    /// `orderKey`, then `createdAt`, then `id` — the server's manual order.
    static func manualPrecedes(_ lhs: TaskRecord, _ rhs: TaskRecord) -> Bool {
        if lhs.orderKey != rhs.orderKey { return lhs.orderKey < rhs.orderKey }
        if lhs.createdAt != rhs.createdAt { return lhs.createdAt < rhs.createdAt }
        return lhs.id < rhs.id
    }

    private static func endedAt(_ task: TaskRecord) -> Date? {
        switch task.state {
        case .completed: task.completedAt
        case .cancelled: task.cancelledAt
        case .inbox, .next, .waiting, .someday: nil
        }
    }
}

/// Name order for projects and tags: the normalized name folded for
/// diacritics (so `Éclair` sits beside `eclair`), then the normalized name,
/// then the display name, then the id.
struct NameSortKey: Comparable {
    let folded: String
    let normalized: String
    let display: String
    let id: String

    init(normalized: String, display: String, id: String) {
        self.folded = QueryText.fold(normalized)
        self.normalized = normalized
        self.display = display
        self.id = id
    }

    static func < (lhs: NameSortKey, rhs: NameSortKey) -> Bool {
        (lhs.folded, lhs.normalized, lhs.display, lhs.id) < (rhs.folded, rhs.normalized, rhs.display, rhs.id)
    }
}

extension ProjectRecord {
    var nameSortKey: NameSortKey {
        NameSortKey(normalized: NameNormalizer.project(name), display: name, id: id.rawValue)
    }
}

extension TagRecord {
    /// Tags sort without their optional leading `@`.
    var nameSortKey: NameSortKey {
        NameSortKey(normalized: NameNormalizer.tag(name), display: name, id: id.rawValue)
    }
}

extension DateView {
    /// The view a due date falls in relative to `today`; nil without a due date.
    init?(due: CalendarDay?, today: CalendarDay) {
        guard let due else { return nil }
        self = due < today ? .overdue : due == today ? .today : .upcoming
    }
}
