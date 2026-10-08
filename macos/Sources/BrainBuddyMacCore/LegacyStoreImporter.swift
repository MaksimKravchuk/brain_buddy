import BrainBuddyCore
import BrainBuddyPersistence
import CryptoKit
import Foundation

/// The names of the files the one-time import works with, all in the Mac's folder (contracts
/// mac-app-host §1, data-model E7.1 and E8).
package enum LegacyFileNames {
    package static let legacy = "local-gtd.json"
    package static let legacyLock = ".local-gtd.json.lock"
    package static let store = "store.json"
    package static let backupPrefix = "local-gtd.backup-"
    package static let reportPrefix = "local-gtd.import-report-"
    package static let stagingPrefix = "store.import-"
    package static let quarantinedPrefix = "store.unreadable-"

    /// `yyyyMMdd'T'HHmmss'Z'` in UTC, safe in a file name.
    package static func stamp(_ date: Date) -> String {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        let parts = calendar.dateComponents([.year, .month, .day, .hour, .minute, .second], from: date)
        func pad(_ value: Int?, _ width: Int) -> String {
            let digits = String(value ?? 0)
            return String(repeating: "0", count: max(0, width - digits.count)) + digits
        }
        return pad(parts.year, 4) + pad(parts.month, 2) + pad(parts.day, 2) + "T" + pad(parts.hour, 2)
            + pad(parts.minute, 2) + pad(parts.second, 2) + "Z"
    }

    package static func backup(_ date: Date) -> String { "\(backupPrefix)\(stamp(date)).json" }
    package static func report(_ date: Date) -> String { "\(reportPrefix)\(stamp(date)).txt" }
    package static func staging(_ attemptID: UUID) -> String { "\(stagingPrefix)\(attemptID.uuidString.lowercased()).json" }

    /// The import date written into a backup's name, for when `mac-local.json` is lost (E8).
    package static func backupDate(fromFileName name: String) -> Date? {
        guard name.hasPrefix(backupPrefix), name.hasSuffix(".json") else { return nil }
        let stamp = name.dropFirst(backupPrefix.count).prefix(16)
        guard stamp.count == 16 else { return nil }
        let characters = Array(stamp)
        func number(_ range: Range<Int>) -> Int? { Int(String(characters[range])) }
        guard characters[8] == "T", characters[15] == "Z", let year = number(0..<4), let month = number(4..<6),
            let day = number(6..<8), let hour = number(9..<11), let minute = number(11..<13),
            let second = number(13..<15)
        else { return nil }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        return calendar.date(
            from: DateComponents(year: year, month: month, day: day, hour: hour, minute: minute, second: second)
        )
    }

    package static func isStaging(_ name: String) -> Bool { name.hasPrefix(stagingPrefix) && name.hasSuffix(".json") }
    package static func isBackup(_ name: String) -> Bool { name.hasPrefix(backupPrefix) && name.hasSuffix(".json") }
    package static func isReport(_ name: String) -> Bool { name.hasPrefix(reportPrefix) && name.hasSuffix(".txt") }
    package static func isQuarantined(_ name: String) -> Bool { name.hasPrefix(quarantinedPrefix) }
}

/// One value the import changed, for the report (contracts/mac-legacy-import.md §2a).
package struct LegacyAdjustment: Hashable, Sendable {
    package var kind: String
    package var original: String
    package var result: String
    package var rule: String

    package init(kind: String, original: String, result: String, rule: String) {
        self.kind = kind
        self.original = original
        self.result = result
        self.rule = rule
    }
}

/// A legacy record the import could not carry (none is known; the category exists so nothing is
/// ever dropped silently, contracts/mac-legacy-import.md §2a).
package struct LegacyNotCarried: Hashable, Sendable {
    package var kind: String
    package var text: String
    package var reason: String
}

/// What the import log line reports: counts and a duration only (FR-030).
package struct LegacyImportCounts: Hashable, Sendable {
    package var tasks = 0
    package var projects = 0
    package var tags = 0
    package var subtasks = 0
    package var comments = 0
    package var adjusted = 0
    package var notCarried = 0
    package var skippedDeletedTags = 0
    package var skippedCommentEdits = 0
    package var reviewMarks = 0

    var logFields: String {
        "tasks=\(tasks) projects=\(projects) tags=\(tags) subtasks=\(subtasks) comments=\(comments) "
            + "adjusted=\(adjusted) notCarried=\(notCarried) skippedDeletedTags=\(skippedDeletedTags) "
            + "skippedCommentEdits=\(skippedCommentEdits) reviewMarks=\(reviewMarks)"
    }
}

/// What the account-less document must hold after the import: the canonical values of
/// contracts/mac-legacy-import.md §2a, never the raw legacy ones (§3).
package struct LegacyImportExpectation: Sendable {
    package struct Task: Sendable {
        package var id: TaskID
        package var title: String
        package var details: String?
        package var state: TaskState
        package var lastOpenList: OpenList?
        package var projectID: ProjectID?
        package var tagIDs: [TagID]
        package var dueDate: CalendarDay?
        package var priority: TaskPriority
        package var waitingFor: String?
        package var waitingSince: Date?
        package var createdAt: Date
        package var completedAt: Date?
        package var cancelledAt: Date?
        package var subtasks: [Subtask]
        package var comments: [String]
    }

    package struct Subtask: Hashable, Sendable {
        package var title: String
        package var state: SubtaskState
    }

    package struct Project: Sendable {
        package var id: ProjectID
        package var name: String
        package var color: String?
        package var isArchived: Bool
        package var desiredOutcome: String?
    }

    package var tasks: [Task] = []
    package var projects: [Project] = []
    package var tags: [(id: TagID, name: String)] = []
    /// The open tasks of each list in the order they were created, which is the order each list
    /// must show (the Mac's order, with the name-clashing archived projects' tasks first, §2 step 2).
    package var listOrder: [OpenList: [TaskID]] = [:]
}

/// The legacy review receipts to carry into `mac-local.json` (§4), by new id.
package struct LegacyReviewMarks: Sendable {
    package var waiting: [(task: TaskID, reviewedAt: Date)] = []
    package var someday: [(task: TaskID, reviewedAt: Date)] = []
    package var projects: [(project: ProjectID, reviewedAt: Date, decision: ProjectReviewDecision)] = []

    package var count: Int { waiting.count + someday.count + projects.count }
}

/// The importer's result before anything is written.
package struct LegacyImportPlan: Sendable {
    package var document: StoreDocument
    package var expectation: LegacyImportExpectation
    package var adjustments: [LegacyAdjustment]
    package var notCarried: [LegacyNotCarried]
    package var counts: LegacyImportCounts
    package var marks: LegacyReviewMarks
}

/// An importer defect (a reducer rejection of a canonical value): reported as
/// `verificationFailed`, never as a damaged file (§2).
package struct LegacyImportDefect: Error, Hashable, Sendable {
    package var step: String
}

/// Turns the pre-021 Mac store into the account-less kit document (contracts/mac-legacy-import.md
/// §2a, §2, §3). Pure apart from the injected id source: the same snapshot, ids and clock give the
/// same bytes (§6 golden artifact).
package enum LegacyStoreImporter {
    /// The importer's rule version; a later build with a higher one may retry an `unreadable` file
    /// while the workspace is not in use (data-model E7.1 row 12).
    package static let version = 1

    /// Builds the outbox: every value through `ImportCanonicalizer`, the commands of §2 in their
    /// order, applied through `GTDReducer` in interactive mode at the original instants, without
    /// compaction. `notCarried` names legacy task ids forced through the "not carried" path (a
    /// test-only hook; §2a carries everything known).
    package static func plan(
        _ snapshot: LegacySnapshot, importedAt: Date, makeID: @escaping () -> UUID, notCarried forced: Set<String> = []
    ) throws(LegacyImportDefect) -> LegacyImportPlan {
        var adjustments: [LegacyAdjustment] = []
        func note(_ kind: String, _ original: String, _ result: String, _ rule: String) {
            adjustments.append(LegacyAdjustment(kind: kind, original: original, result: result, rule: rule))
        }

        // §2a: the canonical values.
        let canonicalInput = ImportCanonicalizer.Snapshot(
            projects: snapshot.projects.map { project in
                if project.state != "active", project.state != "archived" {
                    note("project state", project.state, "active", "an unknown project state becomes active")
                }
                return ImportCanonicalizer.Project(
                    id: project.id, name: project.name, color: project.color, isArchived: project.state == "archived",
                    desiredOutcome: project.desiredOutcome
                )
            },
            tags: snapshot.tags.map { tag in
                if tag.state != "active", tag.state != "deleted" {
                    note("tag state", tag.state, "active", "an unknown tag state becomes active")
                }
                return ImportCanonicalizer.Tag(id: tag.id, name: tag.name, isDeleted: tag.state == "deleted")
            },
            tasks: snapshot.tasks.map { task in
                ImportCanonicalizer.Task(
                    id: task.id, title: task.title, details: task.details, state: task.state,
                    lastOpenState: task.lastOpenState, projectID: task.projectID, tagIDs: task.tagIDs,
                    dueDate: task.dueDate, waitingFor: task.waitingFor,
                    subtasks: task.subtasks.sorted { ($0.orderKey, $0.id) < ($1.orderKey, $1.id) }.map {
                        .init(id: $0.id, title: $0.title)
                    },
                    comments: task.comments.map { .init(id: $0.id, body: $0.body) }
                )
            }
        )
        let canonical = ImportCanonicalizer.canonicalize(canonicalInput)
        adjustments += canonical.adjustments.map {
            LegacyAdjustment(kind: $0.kind, original: $0.original, result: $0.result, rule: $0.rule)
        }

        let legacyTasks = Dictionary(snapshot.tasks.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
        var builder = Builder(importedAt: importedAt, makeID: makeID)
        var expectation = LegacyImportExpectation()
        var notCarried: [LegacyNotCarried] = []
        var counts = LegacyImportCounts()
        counts.skippedDeletedTags = snapshot.tags.filter { $0.state == "deleted" }.count

        // The tasks that are carried, each with its canonical values and its legacy record, in
        // one global order: (list, orderKey, createdAt, id), across projects (§2 step 4).
        struct Item {
            var canonical: ImportCanonicalizer.Task
            var legacy: LegacySnapshot.Task
            var list: OpenList
            var createdAt: Date
        }
        var items: [Item] = []
        for task in canonical.snapshot.tasks {
            guard let legacy = legacyTasks[task.id] else { continue }
            if forced.contains(task.id) {
                notCarried.append(LegacyNotCarried(kind: "task", text: legacy.title, reason: "could not be read"))
                continue
            }
            let state = TaskState(rawValue: task.state) ?? .inbox
            let list = state.openList ?? task.lastOpenState.flatMap(OpenList.init(rawValue:)) ?? .inbox
            var createdAt = LegacySnapshot.date(legacy.createdAt)
            if createdAt == nil {
                note("task created date", legacy.createdAt, "", "an unreadable date becomes the time of the update")
                createdAt = importedAt
            }
            items.append(Item(canonical: task, legacy: legacy, list: list, createdAt: createdAt ?? importedAt))
        }
        let listRank = Dictionary(uniqueKeysWithValues: OpenList.allCases.enumerated().map { ($1, $0) })
        items.sort { lhs, rhs in
            let left = (listRank[lhs.list] ?? 0, lhs.legacy.orderKey)
            let right = (listRank[rhs.list] ?? 0, rhs.legacy.orderKey)
            if left != right { return left < right }
            if lhs.createdAt != rhs.createdAt { return lhs.createdAt < rhs.createdAt }
            return lhs.legacy.id < rhs.legacy.id
        }

        // Step 1: active tags, at the import time (the legacy tag has no timestamp).
        var tagIDs: [String: TagID] = [:]
        for tag in canonical.snapshot.tags {
            let id = TagID(builder.newID())
            tagIDs[tag.id] = id
            try builder.apply(.createTag(.init(tagID: id, name: tag.name)), at: importedAt, step: "tag")
            expectation.tags.append((id, tag.name))
            counts.tags += 1
        }

        // Projects: an archived project whose kit key another project shares is created, filled
        // and archived on its own, before its namesake exists (§2 step 2; extended to archived
        // namesakes, which may not be active at the same time either).
        let keys = canonical.snapshot.projects.map { NameNormalizer.project($0.name) }
        var keyCounts: [String: Int] = [:]
        for key in keys { keyCounts[key, default: 0] += 1 }
        var projectIDs: [String: ProjectID] = [:]
        for project in canonical.snapshot.projects { projectIDs[project.id] = ProjectID(builder.newID()) }
        let clashing = canonical.snapshot.projects.enumerated().filter { $0.element.isArchived && keyCounts[keys[$0.offset], default: 0] > 1 }
            .map(\.element)
        let clashingIDs = Set(clashing.map(\.id))

        func projectIssuedAt(_ legacyID: String) -> Date {
            items.filter { $0.canonical.projectID == legacyID }.map(\.createdAt).min() ?? importedAt
        }
        func createProject(_ project: ImportCanonicalizer.Project) throws(LegacyImportDefect) {
            guard let id = projectIDs[project.id] else { return }
            try builder.apply(
                .createProject(.init(projectID: id, name: project.name, color: project.color, desiredOutcome: project.desiredOutcome)),
                at: projectIssuedAt(project.id), step: "project"
            )
            expectation.projects.append(
                .init(id: id, name: project.name, color: project.color, isArchived: project.isArchived, desiredOutcome: project.desiredOutcome)
            )
            counts.projects += 1
        }

        func carry(_ item: Item) throws(LegacyImportDefect) {
            let task = item.canonical
            let legacy = item.legacy
            let id = TaskID(builder.newID())
            let state = TaskState(rawValue: task.state) ?? .inbox
            let priority = TaskPriority(rawValue: legacy.priority) ?? .none
            if TaskPriority(rawValue: legacy.priority) == nil {
                note("task priority", legacy.priority, TaskPriority.none.rawValue, "an unknown priority becomes none")
            }
            let projectID = task.projectID.flatMap { projectIDs[$0] }
            var taskTagIDs: [TagID] = []
            for tagID in task.tagIDs.compactMap({ tagIDs[$0] }) where !taskTagIDs.contains(tagID) { taskTagIDs.append(tagID) }
            if taskTagIDs.count != task.tagIDs.count {
                note("task tag reference", "", "", "a tag listed twice on a task is kept once")
            }
            let dueDate = task.dueDate.flatMap(CalendarDay.init(isoString:))
            let isOpenWaiting = state == .waiting
            var waitingSince: Date?
            if isOpenWaiting {
                waitingSince = LegacySnapshot.date(legacy.waitingSince)
                if waitingSince == nil, legacy.waitingSince != nil {
                    note("task waiting date", legacy.waitingSince ?? "", "", "an unreadable date becomes the creation time")
                }
                waitingSince = waitingSince ?? item.createdAt
            }

            // 4.1: the task, in its list, at its creation time.
            try builder.apply(
                .createTask(
                    .init(
                        taskID: id, title: task.title, details: task.details, list: item.list,
                        waitingFor: item.list == .waiting ? task.waitingFor : nil, dueDate: dueDate, priority: priority,
                        projectID: projectID, tagIDs: taskTagIDs
                    )
                ), at: item.createdAt, step: "task"
            )
            let comments = task.comments
            let continued = comments.prefix { $0.id.hasPrefix("\(task.id)-notes-") }
            // 4.2: the notes that did not fit, right after the task, before its own comments.
            for comment in continued {
                try builder.apply(
                    .createComment(.init(taskID: id, commentID: CommentID(builder.newID()), body: comment.body)),
                    at: item.createdAt, step: "comment"
                )
            }
            // 4.3: a Waiting task that entered Waiting after it was created keeps its own
            // `waitingSince`. It is created in Waiting (so its order key is Waiting's next one), then
            // re-enters Waiting at that instant through Inbox: transitions never change the order key,
            // so the list keeps the Mac's order (the contract's create-in-Inbox route would take
            // Inbox's order key; deviation recorded in the PR).
            if isOpenWaiting, let since = waitingSince, Int(since.timeIntervalSince1970) != Int(item.createdAt.timeIntervalSince1970) {
                try builder.apply(.transitionTask(.init(taskID: id, action: .move, toList: .inbox)), at: since, step: "waiting")
                try builder.apply(
                    .transitionTask(.init(taskID: id, action: .move, toList: .waiting, waitingFor: task.waitingFor)),
                    at: since, step: "waiting"
                )
            }
            // 4.4: subtasks in order, then their states.
            let legacySubtasks = Dictionary(legacy.subtasks.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
            var expectedSubtasks: [LegacyImportExpectation.Subtask] = []
            for subtask in task.subtasks {
                let subtaskID = SubtaskID(builder.newID())
                try builder.apply(
                    .createSubtask(.init(taskID: id, subtaskID: subtaskID, title: subtask.title)), at: item.createdAt,
                    step: "subtask"
                )
                let legacyState = legacySubtasks[subtask.id]?.state ?? "open"
                let subtaskState = SubtaskState(rawValue: legacyState) ?? .open
                if SubtaskState(rawValue: legacyState) == nil {
                    note("subtask state", legacyState, "open", "an unknown subtask state becomes open")
                }
                let action: SubtaskTransitionAction? =
                    switch subtaskState {
                    case .open: nil
                    case .completed: .complete
                    case .cancelled: .cancel
                    }
                if let action {
                    try builder.apply(
                        .transitionSubtask(.init(taskID: id, subtaskID: subtaskID, action: action)), at: item.createdAt,
                        step: "subtask"
                    )
                }
                expectedSubtasks.append(.init(title: subtask.title, state: subtaskState))
                counts.subtasks += 1
            }
            // 4.5: the comments, split when long, at their own times. The edit marker is not carried.
            let legacyComments = Dictionary(legacy.comments.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
            for comment in comments.dropFirst(continued.count) {
                let base = legacyComments[comment.id] ?? legacyComments[String(comment.id.split(separator: "-").dropLast().joined(separator: "-"))]
                let at = LegacySnapshot.date(base?.createdAt) ?? item.createdAt
                try builder.apply(
                    .createComment(.init(taskID: id, commentID: CommentID(builder.newID()), body: comment.body)), at: at,
                    step: "comment"
                )
            }
            counts.comments += comments.count
            counts.skippedCommentEdits += legacy.comments.filter { $0.editedAt != nil }.count
            // 4.6: a closed task closes at its own time.
            var completedAt: Date?
            var cancelledAt: Date?
            if state == .completed || state == .cancelled {
                let raw = state == .completed ? legacy.completedAt : legacy.cancelledAt
                var at = LegacySnapshot.date(raw)
                if at == nil {
                    note("task closed date", raw ?? "", "", "an unreadable date becomes the creation time")
                    at = item.createdAt
                }
                let closedAt = at ?? item.createdAt
                try builder.apply(
                    .transitionTask(.init(taskID: id, action: state == .completed ? .complete : .cancel)), at: closedAt,
                    step: "close"
                )
                if state == .completed { completedAt = closedAt } else { cancelledAt = closedAt }
                if legacy.lastOpenState == nil {
                    note("task list", "", OpenList.inbox.rawValue, "a closed task with no recorded list reopens to Inbox")
                }
            } else {
                expectation.listOrder[item.list, default: []].append(id)
            }

            expectation.tasks.append(
                .init(
                    id: id, title: task.title, details: task.details, state: state,
                    lastOpenList: state.isOpen ? nil : item.list, projectID: projectID, tagIDs: taskTagIDs, dueDate: dueDate,
                    priority: priority, waitingFor: isOpenWaiting ? task.waitingFor : nil, waitingSince: waitingSince,
                    createdAt: item.createdAt, completedAt: completedAt, cancelledAt: cancelledAt, subtasks: expectedSubtasks,
                    comments: comments.map(\.body)
                )
            )
            builder.taskIDs[legacy.id] = id
            counts.tasks += 1
        }

        // Step 2: the name-clashing archived projects, one at a time.
        for project in clashing {
            try createProject(project)
            for item in items where item.canonical.projectID == project.id { try carry(item) }
            if let id = projectIDs[project.id] { try builder.apply(.archiveProject(id), at: importedAt, step: "archive") }
        }
        // Step 3: every other project.
        for project in canonical.snapshot.projects where !clashingIDs.contains(project.id) { try createProject(project) }
        // Step 4: the remaining tasks in one global order.
        for item in items where !(item.canonical.projectID.map { clashingIDs.contains($0) } ?? false) { try carry(item) }
        // Step 5: the other archived projects, once all their tasks exist.
        for project in canonical.snapshot.projects where project.isArchived && !clashingIDs.contains(project.id) {
            if let id = projectIDs[project.id] { try builder.apply(.archiveProject(id), at: importedAt, step: "archive") }
        }

        // §4: the review receipts that were still valid before the upgrade.
        var marks = LegacyReviewMarks()
        for (legacyID, receipt) in (snapshot.waitingReviews ?? [:]).sorted(by: { $0.key < $1.key }) {
            guard let legacy = legacyTasks[legacyID], legacy.state == "waiting", receipt.taskRevision == legacy.revision,
                let id = builder.taskIDs[legacyID], let reviewedAt = LegacySnapshot.date(receipt.reviewedAt)
            else { continue }
            marks.waiting.append((id, reviewedAt))
        }
        for (legacyID, receipt) in (snapshot.somedayReviews ?? [:]).sorted(by: { $0.key < $1.key }) {
            guard let legacy = legacyTasks[legacyID], legacy.state == "someday", receipt.taskRevision == legacy.revision,
                let id = builder.taskIDs[legacyID], let reviewedAt = LegacySnapshot.date(receipt.reviewedAt)
            else { continue }
            marks.someday.append((id, reviewedAt))
        }
        for project in snapshot.projects {
            guard let reviewedAt = LegacySnapshot.date(project.lastReviewedAt),
                let decision = project.lastReviewDecision.flatMap(ProjectReviewDecision.init(rawValue:)),
                let signature = project.lastReviewedTaskSignature, signature == legacySignature(project.id, in: snapshot),
                let id = projectIDs[project.id]
            else { continue }
            marks.projects.append((id, reviewedAt, decision))
        }
        counts.reviewMarks = marks.count
        counts.adjusted = adjustments.count
        counts.notCarried = notCarried.count

        let document = StoreDocument(outbox: builder.outbox)
        return LegacyImportPlan(
            document: document, expectation: expectation, adjustments: adjustments, notCarried: notCarried, counts: counts,
            marks: marks
        )
    }

    /// The old store's "changed since review" signature (`LocalGTDStore.projectTaskSignature`):
    /// SHA-256 over `id:revision` of the project's tasks, sorted by id.
    static func legacySignature(_ projectID: String, in snapshot: LegacySnapshot) -> String {
        let payload = snapshot.tasks.filter { $0.projectID == projectID }.sorted { $0.id < $1.id }
            .map { "\($0.id):\($0.revision)" }.joined(separator: "|")
        return SHA256.hash(data: Data(payload.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    /// Applies commands as the person's device would, and records each as one outbox operation.
    private struct Builder {
        let importedAt: Date
        let makeID: () -> UUID
        var state = GTDState()
        var outbox: [PendingOperation] = []
        var taskIDs: [String: TaskID] = [:]

        init(importedAt: Date, makeID: @escaping () -> UUID) {
            self.importedAt = importedAt
            self.makeID = makeID
        }

        func newID() -> String { makeID().uuidString.lowercased() }

        mutating func apply(_ command: GTDCommand, at date: Date, step: String) throws(LegacyImportDefect) {
            do {
                try GTDReducer.apply(command, at: date, to: &state, mode: .interactive)
            } catch {
                throw LegacyImportDefect(step: step)
            }
            outbox.append(PendingOperation(id: makeID(), command: command, issuedAt: date, idempotencyKey: makeID()))
        }
    }

    // MARK: Verification (§3)

    /// Every difference between the stored document, replayed as the workspace will show it, and the
    /// canonical expectation. Empty means verified. The differences name fields, never values.
    package static func verify(_ data: Data, against expectation: LegacyImportExpectation, today: CalendarDay) -> [String] {
        let document: StoreDocument
        do {
            document = try StoreDocumentCoding.decode(data)
        } catch {
            return ["document does not decode"]
        }
        let replay = document.replayed()
        var problems: [String] = []
        if !replay.rejected.isEmpty { problems.append("\(replay.rejected.count) operations rejected on replay") }
        if replay.outbox.count != document.outbox.count { problems.append("the outbox changed on replay") }
        let state = replay.state
        func second(_ date: Date?) -> Int? { date.map { Int($0.timeIntervalSince1970.rounded(.down)) } }

        if state.tasks.count != expectation.tasks.count { problems.append("task count") }
        for expected in expectation.tasks {
            guard let task = state.tasks[expected.id] else {
                problems.append("missing task")
                continue
            }
            if task.title != expected.title { problems.append("task title") }
            if task.details != expected.details { problems.append("task notes") }
            if task.state != expected.state { problems.append("task state") }
            if task.lastOpenList != expected.lastOpenList { problems.append("task previous list") }
            if task.projectID != expected.projectID { problems.append("task project") }
            if task.tagIDs != expected.tagIDs { problems.append("task tags") }
            if task.dueDate != expected.dueDate { problems.append("task due date") }
            if task.priority != expected.priority { problems.append("task priority") }
            if task.waitingFor != expected.waitingFor { problems.append("task waiting-for") }
            if second(task.waitingSince) != second(expected.waitingSince) { problems.append("task waiting since") }
            if second(task.createdAt) != second(expected.createdAt) { problems.append("task created") }
            if second(task.completedAt) != second(expected.completedAt) { problems.append("task completed") }
            if second(task.cancelledAt) != second(expected.cancelledAt) { problems.append("task cancelled") }
            let subtasks = task.subtasks.sorted { ($0.orderKey, $0.id) < ($1.orderKey, $1.id) }
                .map { LegacyImportExpectation.Subtask(title: $0.title, state: $0.state) }
            if subtasks != expected.subtasks { problems.append("task subtasks") }
            if task.comments.map(\.body) != expected.comments { problems.append("task comments") }
        }
        if state.projects.count != expectation.projects.count { problems.append("project count") }
        for expected in expectation.projects {
            guard let project = state.projects[expected.id] else {
                problems.append("missing project")
                continue
            }
            if project.name != expected.name { problems.append("project name") }
            if project.color != expected.color { problems.append("project colour") }
            if (project.state == .archived) != expected.isArchived { problems.append("project state") }
            if project.desiredOutcome != expected.desiredOutcome { problems.append("project outcome") }
        }
        let activeTags = state.tags.values.filter { $0.state == .active }
        if activeTags.count != expectation.tags.count || state.tags.count != expectation.tags.count { problems.append("tag count") }
        for expected in expectation.tags where state.tags[expected.id]?.name != expected.name {
            problems.append("tag name")
        }

        // Order: each open list across projects, as the lists show it, and each project's lists.
        let options = ListOptions()
        for list in OpenList.allCases {
            let expected = expectation.listOrder[list] ?? []
            let shown = GTDQueries.list(.list(list), options: options, in: state, today: today).sections.flatMap(\.tasks).map(\.id)
            let wanted = list == .inbox ? expected.filter { state.tasks[$0]?.projectID == nil } : expected
            if shown != wanted { problems.append("order of \(list.rawValue)") }
        }
        for project in expectation.projects {
            let result = GTDQueries.list(.project(project.id), options: options, in: state, today: today)
            for section in result.sections {
                guard case .list(let list) = section.kind else { continue }
                let wanted = (expectation.listOrder[list] ?? []).filter { state.tasks[$0]?.projectID == project.id }
                if section.tasks.map(\.id) != wanted { problems.append("order within a project") }
            }
        }
        return problems
    }

    // MARK: Report (§2a, data-model E8)

    /// The import report: each adjusted value and each record not carried, with the original text.
    /// Written only when there is one of either. It quotes the person's text, so it is never logged.
    package static func reportText(
        adjustments: [LegacyAdjustment], notCarried: [LegacyNotCarried], importedAt: Date
    ) -> String {
        var lines = [
            "Brain Buddy: carrying over your tasks from the previous version",
            "Updated: \(LegacyFileNames.stamp(importedAt))",
            "Values adjusted: \(adjustments.count)",
            "Records not carried: \(notCarried.count)",
            "",
        ]
        if !adjustments.isEmpty {
            lines.append("Adjusted values (what it was → what it is now, and why):")
            for entry in adjustments {
                lines.append("- \(entry.kind): “\(entry.original)” → “\(entry.result)” (\(entry.rule))")
            }
            lines.append("")
        }
        if !notCarried.isEmpty {
            lines.append("Not carried over (still in the file from the previous version, which stays on this Mac):")
            for entry in notCarried { lines.append("- \(entry.kind): “\(entry.text)” (\(entry.reason))") }
            lines.append("")
        }
        return lines.joined(separator: "\n")
    }
}
