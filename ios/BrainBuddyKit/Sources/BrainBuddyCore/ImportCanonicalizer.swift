import Foundation

/// The field transform of the one-time import of the previous Mac store
/// (contracts/mac-legacy-import.md §2a): every legacy value on its way into the kit becomes
/// a value the kit stores as it is, because it passes the kit's own rules (`NameNormalizer`,
/// `FieldRules`, `GTDLimits`). Pure and total: it never fails and never drops text without a
/// trace. What it changes is listed as adjustments, for the import report.
///
/// It reads and returns only the fields it transforms; the importer takes every other field
/// (priority, dates, order, comment times) from the legacy record with the same id.
public enum ImportCanonicalizer {
    public struct Project: Hashable, Sendable {
        public var id: String
        public var name: String
        public var color: String?
        public var isArchived: Bool
        public var desiredOutcome: String?

        public init(id: String, name: String, color: String? = nil, isArchived: Bool = false, desiredOutcome: String? = nil) {
            self.id = id
            self.name = name
            self.color = color
            self.isArchived = isArchived
            self.desiredOutcome = desiredOutcome
        }
    }

    public struct Tag: Hashable, Sendable {
        public var id: String
        public var name: String
        public var isDeleted: Bool

        public init(id: String, name: String, isDeleted: Bool = false) {
            self.id = id
            self.name = name
            self.isDeleted = isDeleted
        }
    }

    public struct Subtask: Hashable, Sendable {
        public var id: String
        public var title: String

        public init(id: String, title: String) {
            self.id = id
            self.title = title
        }
    }

    public struct Comment: Hashable, Sendable {
        public var id: String
        public var body: String

        public init(id: String, body: String) {
            self.id = id
            self.body = body
        }
    }

    public struct Task: Hashable, Sendable {
        public var id: String
        public var title: String
        public var details: String?
        /// A `TaskState` raw value; anything else is an open task in Inbox.
        public var state: String
        public var lastOpenState: String?
        public var projectID: String?
        public var tagIDs: [String]
        /// `YYYY-MM-DD`; anything else is dropped.
        public var dueDate: String?
        public var waitingFor: String?
        public var subtasks: [Subtask]
        public var comments: [Comment]

        public init(
            id: String, title: String, details: String? = nil, state: String = "inbox", lastOpenState: String? = nil,
            projectID: String? = nil, tagIDs: [String] = [], dueDate: String? = nil, waitingFor: String? = nil,
            subtasks: [Subtask] = [], comments: [Comment] = []
        ) {
            self.id = id
            self.title = title
            self.details = details
            self.state = state
            self.lastOpenState = lastOpenState
            self.projectID = projectID
            self.tagIDs = tagIDs
            self.dueDate = dueDate
            self.waitingFor = waitingFor
            self.subtasks = subtasks
            self.comments = comments
        }
    }

    /// The legacy records, in legacy order.
    public struct Snapshot: Hashable, Sendable {
        public var projects: [Project]
        public var tags: [Tag]
        public var tasks: [Task]

        public init(projects: [Project] = [], tags: [Tag] = [], tasks: [Task] = []) {
            self.projects = projects
            self.tags = tags
            self.tasks = tasks
        }
    }

    /// One changed value, for the import report.
    public struct Adjustment: Hashable, Sendable {
        public var kind: String
        public var original: String
        public var result: String
        public var rule: String
    }

    public struct Result: Hashable, Sendable {
        /// The values the kit will store. Deleted tags are gone, a task's `comments` start with the
        /// "Notes, continued" ones, and the legacy order is kept.
        public var snapshot: Snapshot
        public var adjustments: [Adjustment]
    }

    // MARK: Transform

    public static func canonicalize(_ input: Snapshot) -> Result {
        var adjustments: [Adjustment] = []
        func note(_ kind: String, _ original: String, _ result: String, _ rule: String) {
            if original != result { adjustments.append(Adjustment(kind: kind, original: original, result: result, rule: rule)) }
        }

        var activeProjectKeys = Set<String>()
        let projects = input.projects.map { project -> Project in
            var out = project
            out.name = name(
                project.name, fallback: "Untitled project", display: NameNormalizer.display, key: NameNormalizer.project,
                unique: project.isArchived ? nil : { activeProjectKeys.insert($0).inserted }
            )
            note("project", project.name, out.name, "display form, 1 to 500 characters, unique among active projects")
            out.desiredOutcome = outcome(project.desiredOutcome)
            note("project outcome", project.desiredOutcome ?? "", out.desiredOutcome ?? "", "trimmed, at most 1,000 characters")
            if let color = project.color, scalars(color) > GTDLimits.color {
                out.color = nil
                note("project colour", color, "", "at most 64 characters")
            }
            return out
        }

        var activeTagKeys = Set<String>()
        let tags = input.tags.filter { !$0.isDeleted }.map { tag -> Tag in
            var out = tag
            out.name = name(
                tag.name, fallback: "Untitled tag", display: NameNormalizer.tagDisplay, key: NameNormalizer.tag,
                unique: { activeTagKeys.insert($0).inserted }
            )
            note("tag", tag.name, out.name, "display form, 1 to 500 characters, unique among active tags")
            return out
        }

        let projectIDs = Set(input.projects.map(\.id))
        let tagIDs = Set(input.tags.filter { !$0.isDeleted }.map(\.id))
        let deletedTagIDs = Set(input.tags.filter(\.isDeleted).map(\.id))
        let tasks = input.tasks.map { task -> Task in
            var out = task
            var added: [String] = []

            out.title = text(task.title, fallback: "Untitled task", limit: GTDLimits.title) { added.append("Full title: \($0)") }
            note("task title", task.title, out.title, "trimmed, 1 to 500 characters")

            out.subtasks = task.subtasks.map { subtask in
                var copy = subtask
                copy.title = text(subtask.title, fallback: "Untitled task", limit: GTDLimits.title) {
                    added.append("Full subtask title: \($0)")
                }
                note("subtask title", subtask.title, copy.title, "trimmed, 1 to 500 characters")
                return copy
            }

            if TaskState(rawValue: task.state) == nil {
                out.state = "inbox"
                note("task state", task.state, "inbox", "an unknown state becomes an open task in Inbox")
            }
            let state = TaskState(rawValue: out.state) ?? .inbox
            if state.isOpen {
                out.lastOpenState = nil
            } else if let last = task.lastOpenState, OpenList(rawValue: last) == nil {
                out.lastOpenState = nil
                note("task list", last, "", "an unknown list is forgotten")
            }
            let list = state.openList ?? out.lastOpenState.flatMap(OpenList.init(rawValue:)) ?? .inbox
            if list == .waiting {
                let raw = task.waitingFor ?? ""
                out.waitingFor = text(raw, fallback: "(not recorded)", limit: GTDLimits.waitingFor) { added.append("Waiting for: \($0)") }
                note("task waiting-for", raw, out.waitingFor ?? "", "trimmed, required in Waiting, 1 to 500 characters")
            } else {
                out.waitingFor = nil
            }

            if let due = task.dueDate, CalendarDay(isoString: due) == nil {
                out.dueDate = nil
                note("task due date", due, "", "an unreadable date is dropped")
            }
            if let project = task.projectID, !projectIDs.contains(project) {
                out.projectID = nil
                note("task project reference", project, "", "a missing project is dropped")
            }
            out.tagIDs = task.tagIDs.filter { id in
                if tagIDs.contains(id) { return true }
                if !deletedTagIDs.contains(id) { note("task tag reference", id, "", "a missing tag is dropped") }
                return false
            }

            // Notes: what was added above leads them; what does not fit continues in comments.
            let body = (added.isEmpty ? [] : [added.joined(separator: "\n")]) + (task.details.flatMap { $0.isEmpty ? nil : $0 }.map { [$0] } ?? [])
            let notes = body.joined(separator: "\n\n")
            let head = pieces(notes, size: GTDLimits.details).first ?? ""
            out.details = head.isEmpty ? nil : head
            let rest = String(String.UnicodeScalarView(notes.unicodeScalars.dropFirst(scalars(head))))
            let chunks = pieces(rest, size: GTDLimits.comment - continuationReserve)
            let continued = chunks.enumerated().map {
                Comment(id: "\(task.id)-notes-\($0.offset + 1)", body: "Notes, continued (\($0.offset + 1) of \(chunks.count)):\n\($0.element)")
            }
            if !continued.isEmpty {
                note("task notes", notes, head, "at most 20,000 characters; the rest continues in comments")
            }

            out.comments = continued + task.comments.flatMap { comment -> [Comment] in
                let parts = split(comment.body, first: GTDLimits.comment, then: GTDLimits.comment - "(continued)\n".unicodeScalars.count)
                if parts.count > 1 { note("comment", comment.body, parts[0], "at most 20,000 characters; the rest continues in comments") }
                if parts.isEmpty { note("comment", comment.body, "", "an empty comment is dropped") }
                return parts.enumerated().map {
                    Comment(id: $0.offset == 0 ? comment.id : "\(comment.id)-\($0.offset + 1)", body: $0.offset == 0 ? $0.element : "(continued)\n\($0.element)")
                }
            }
            return out
        }
        return Result(snapshot: Snapshot(projects: projects, tags: tags, tasks: tasks), adjustments: adjustments)
    }

    // MARK: Rules

    /// Room kept free in a continuation comment for its "Notes, continued (k of n):" line.
    private static let continuationReserve = 64

    /// A project or tag name: display form, `fallback` when empty, within 500 scalars, and for an
    /// active record the smallest " (n)" that makes it unique (`unique` claims a key, false when taken).
    private static func name(
        _ raw: String, fallback: String, display: (String) -> String, key: (String) -> String,
        unique: ((String) -> Bool)?
    ) -> String {
        // "…" is not stable under NFKC (it becomes "..."), so a name is cut with the form it is stored in.
        let ellipsis = display("…")
        var name = display(raw)
        if name.isEmpty { name = fallback }
        name = cut(name, to: GTDLimits.name, ellipsis: ellipsis)
        guard let unique else { return name }
        var candidate = name
        var number = 2
        while !unique(key(candidate)) {
            let suffix = " (\(number))"
            candidate = cut(name, to: GTDLimits.name - suffix.unicodeScalars.count, ellipsis: ellipsis) + suffix
            number += 1
        }
        return candidate
    }

    /// A title-like text: trimmed, `fallback` when empty, within `limit` scalars. A longer one is cut
    /// with "…" and the full text goes to `overflow`.
    private static func text(_ raw: String, fallback: String, limit: Int, overflow: (String) -> Void) -> String {
        let value = NameNormalizer.stripped(raw)
        guard !value.isEmpty else { return fallback }
        guard scalars(value) > limit else { return value }
        overflow(value)
        return cut(value, to: limit)
    }

    /// A project's outcome: trimmed, nil when blank, within 1,000 scalars.
    private static func outcome(_ raw: String?) -> String? {
        let value = NameNormalizer.stripped(raw ?? "")
        return value.isEmpty ? nil : cut(value, to: GTDLimits.outcome)
    }

    private static func scalars(_ value: String) -> Int { value.unicodeScalars.count }

    /// `text` within `limit` scalars, cut at a grapheme boundary with `ellipsis` after it.
    private static func cut(_ text: String, to limit: Int, ellipsis: String = "…") -> String {
        guard scalars(text) > limit else { return text }
        let room = limit - scalars(ellipsis)
        var result = ""
        var used = 0
        for character in text {
            let size = character.unicodeScalars.count
            if used + size > room { break }
            result.append(character)
            used += size
        }
        return result + ellipsis
    }

    /// `text` as consecutive pieces of at most `size` scalars, cut at grapheme boundaries (a single
    /// cluster longer than a piece is cut by scalars). Joined, they are the text.
    private static func pieces(_ text: String, size: Int) -> [String] {
        var pieces: [String] = []
        var current = String.UnicodeScalarView()
        var used = 0
        func flush() {
            if used > 0 { pieces.append(String(current)) }
            current = String.UnicodeScalarView()
            used = 0
        }
        for character in text {
            let cluster = Array(character.unicodeScalars)
            if used + cluster.count > size { flush() }
            if cluster.count > size {
                for start in stride(from: 0, to: cluster.count, by: size) {
                    pieces.append(String(String.UnicodeScalarView(cluster[start..<min(start + size, cluster.count)])))
                }
            } else {
                current.append(contentsOf: cluster)
                used += cluster.count
            }
        }
        flush()
        return pieces
    }

    /// `text` in pieces: the first within `first` scalars, the rest within `then`.
    private static func split(_ text: String, first: Int, then: Int) -> [String] {
        guard let head = pieces(text, size: first).first else { return [] }
        let rest = String(String.UnicodeScalarView(text.unicodeScalars.dropFirst(scalars(head))))
        return [head] + pieces(rest, size: then)
    }
}
