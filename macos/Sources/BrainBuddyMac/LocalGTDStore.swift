import Foundation
import Darwin
import CryptoKit

/// The task surface reads and writes one store. A network client can be used
/// separately for optional synchronization; the local store needs no session.
@MainActor
protocol GTDStore {
    func listTasks(state: TaskList, cursor: String?) async throws -> TaskPage
    func listTasks(query: TaskQuery, cursor: String?) async throws -> TaskPage
    func getTask(_ id: String) async throws -> BrainBuddyTask
    func createTask(title: String, state: TaskList, waitingFor: String?, idempotencyKey: UUID) async throws -> BrainBuddyTask
    func smartAddTask(
        title: String, details: String?, state: TaskList, waitingFor: String?,
        dueDate: String?, priority: TaskPriority, project: ClassificationRef?,
        tags: [ClassificationRef], idempotencyKey: UUID
    ) async throws -> SmartAddResult
    func completeTask(_ task: BrainBuddyTask, idempotencyKey: UUID) async throws -> BrainBuddyTask
    func updateTask(_ task: BrainBuddyTask, changes: TaskChanges, idempotencyKey: UUID) async throws -> BrainBuddyTask
    func transitionTask(
        _ task: BrainBuddyTask, action: TaskTransitionAction, toState: TaskList?,
        waitingFor: String?, idempotencyKey: UUID
    ) async throws -> BrainBuddyTask
    func createSubtask(taskID: String, title: String, idempotencyKey: UUID) async throws -> BrainBuddySubtask
    func updateSubtask(taskID: String, subtask: BrainBuddySubtask, title: String, idempotencyKey: UUID) async throws -> BrainBuddySubtask
    func transitionSubtask(taskID: String, subtask: BrainBuddySubtask, action: SubtaskTransitionAction, idempotencyKey: UUID) async throws -> BrainBuddySubtask
    func createComment(taskID: String, body: String, idempotencyKey: UUID) async throws -> BrainBuddyComment
    func updateComment(taskID: String, comment: BrainBuddyComment, body: String, idempotencyKey: UUID) async throws -> BrainBuddyComment
    func listProjects() async throws -> [BrainBuddyProject]
    func listArchivedProjects() async throws -> [BrainBuddyProject]
    func listTags() async throws -> [BrainBuddyTag]
    func createProject(name: String, idempotencyKey: UUID) async throws -> BrainBuddyProject
    func createTag(name: String, idempotencyKey: UUID) async throws -> BrainBuddyTag
    func renameProject(_ project: BrainBuddyProject, to name: String, idempotencyKey: UUID) async throws -> BrainBuddyProject
    func archiveProject(_ project: BrainBuddyProject, idempotencyKey: UUID) async throws -> BrainBuddyProject
    func unarchiveProject(_ project: BrainBuddyProject, idempotencyKey: UUID) async throws -> BrainBuddyProject
    func renameTag(_ tag: BrainBuddyTag, to name: String, idempotencyKey: UUID) async throws -> BrainBuddyTag
    func deleteTag(_ tag: BrainBuddyTag, idempotencyKey: UUID) async throws -> BrainBuddyTag
}

extension APIClient: GTDStore {}

/// A versioned, single-file store. Every mutation writes an atomic replacement
/// before its result is returned. An unreadable file is never reset implicitly.
@MainActor
final class LocalGTDStore: GTDStore {
    private struct Snapshot: Codable {
        var version = 1
        var generation = 0
        var tasks: [StoredTask] = []
        var projects: [StoredProject] = []
        var tags: [StoredTag] = []
        var idempotency: [String: String] = [:]
        var idempotencyReceipts: [String: IdempotencyReceipt]?
    }

    private struct IdempotencyReceipt: Codable {
        let fingerprint: String
        let response: Data
    }

    private struct StoredTask: Codable {
        var id: String
        var title: String
        var details: String?
        var state: String
        var lastOpenState: TaskList?
        var revision: Int
        var projectID: String?
        var tagIDs: [String]
        var dueDate: String?
        var priority: TaskPriority
        var waitingFor: String?
        var waitingSince: String?
        var completedAt: String?
        var cancelledAt: String?
        var orderKey: Int
        var createdAt: String
        var subtasks: [StoredSubtask]
        var comments: [StoredComment]

        var isOpen: Bool { TaskList(rawValue: state) != nil }

        func publicValue() -> BrainBuddyTask {
            BrainBuddyTask(
                id: id, title: title, details: details, state: state,
                revision: revision, project_id: projectID, tag_ids: tagIDs,
                due_date: dueDate, priority: priority, waiting_for: waitingFor,
                waiting_since: waitingSince, last_open_state: lastOpenState,
                completed_at: completedAt, cancelled_at: cancelledAt,
                subtasks: subtasks.map { $0.publicValue() },
                comments: comments.map { $0.publicValue() }
            )
        }
    }

    private struct StoredSubtask: Codable {
        var id: String
        var title: String
        var state: String
        var orderKey: Int
        var revision: Int

        func publicValue() -> BrainBuddySubtask {
            BrainBuddySubtask(id: id, title: title, state: state, order_key: orderKey, revision: revision)
        }
    }

    private struct StoredComment: Codable {
        var id: String
        var body: String
        var actorID: String
        var createdAt: String
        var editedAt: String?
        var revision: Int

        func publicValue() -> BrainBuddyComment {
            BrainBuddyComment(
                id: id, body: body, actor_id: actorID,
                created_at: createdAt, edited_at: editedAt, revision: revision
            )
        }
    }

    private struct StoredProject: Codable {
        var id: String
        var name: String
        var color: String?
        var state: String
        var revision: Int
    }

    private struct StoredTag: Codable {
        var id: String
        var name: String
        var state: String
        var revision: Int
    }

    private let fileURL: URL
    private var snapshot = Snapshot()
    private var loadError: Error?

    nonisolated static func defaultFileURL() -> URL {
        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return support.appendingPathComponent("BrainBuddyMac", isDirectory: true)
            .appendingPathComponent("local-gtd.json")
    }

    init(fileURL: URL = LocalGTDStore.defaultFileURL()) {
        self.fileURL = fileURL
        guard FileManager.default.fileExists(atPath: fileURL.path) else { return }
        do {
            let decoded = try JSONDecoder().decode(Snapshot.self, from: Data(contentsOf: fileURL))
            guard decoded.version == 1 else {
                throw APIError(message: "This local task database uses an unsupported version.")
            }
            snapshot = decoded
        } catch {
            loadError = error
        }
    }

    private func checkLoaded() throws {
        if let loadError {
            throw APIError(message: "The local task database could not be read: \(loadError.localizedDescription)")
        }
    }

    private func mutate<Result>(_ change: (inout Snapshot) throws -> Result) throws -> Result {
        try checkLoaded()
        let directory = fileURL.deletingLastPathComponent()
        try FileManager.default.createDirectory(
            at: directory, withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: directory.path)
        let lockURL = directory.appendingPathComponent(".\(fileURL.lastPathComponent).lock")
        let lockDescriptor = Darwin.open(lockURL.path, O_CREAT | O_RDWR, 0o600)
        guard lockDescriptor >= 0 else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
        }
        defer { Darwin.close(lockDescriptor) }
        guard Darwin.fchmod(lockDescriptor, 0o600) == 0 else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
        }
        guard Darwin.lockf(lockDescriptor, F_LOCK, 0) == 0 else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
        }
        defer { Darwin.lockf(lockDescriptor, F_ULOCK, 0) }
        if FileManager.default.fileExists(atPath: fileURL.path) {
            let current = try JSONDecoder().decode(Snapshot.self, from: Data(contentsOf: fileURL))
            guard current.version == 1, current.generation == snapshot.generation else {
                throw APIError(message: "Local tasks changed in another app process. Reopen Brain Buddy before editing.", statusCode: 409)
            }
        } else if snapshot.generation != 0 {
            throw APIError(message: "Local tasks changed in another app process. Reopen Brain Buddy before editing.", statusCode: 409)
        }
        var next = snapshot
        let result = try change(&next)
        next.generation += 1
        let data = try JSONEncoder().encode(next)
        let stagedURL = directory.appendingPathComponent(".\(fileURL.lastPathComponent).\(UUID().uuidString).tmp")
        defer { try? FileManager.default.removeItem(at: stagedURL) }
        try data.write(to: stagedURL, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: stagedURL.path)
        let descriptor = Darwin.open(stagedURL.path, O_RDONLY)
        guard descriptor >= 0 else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
        }
        defer { Darwin.close(descriptor) }
        guard Darwin.fsync(descriptor) == 0 else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
        }
        guard Darwin.rename(stagedURL.path, fileURL.path) == 0 else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
        }
        snapshot = next
        return result
    }

    private static func id(_ prefix: String) -> String { "\(prefix)_\(UUID().uuidString.lowercased())" }
    private static func now() -> String { ISO8601DateFormatter().string(from: Date()) }
    private static func text(_ value: String, label: String, max: Int) throws -> String {
        let result = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !result.isEmpty, result.count <= max else {
            throw APIError(message: "\(label) must contain 1–\(max) characters.")
        }
        return result
    }
    private static func conflict(_ name: String) -> APIError {
        APIError(message: "\(name) changed since it was opened. Reload and try again.", statusCode: 409)
    }
    private static func missing(_ name: String) -> APIError {
        APIError(message: "\(name) no longer exists.", statusCode: 404)
    }

    private static func fingerprint<Body: Encodable>(_ command: String, body: Body) throws -> String {
        let encoder = JSONEncoder()
        encoder.outputFormatting = .sortedKeys
        let data = try encoder.encode(body)
        let digest = SHA256.hash(data: Data(command.utf8) + Data([0]) + data)
        return digest.map { String(format: "%02x", $0) }.joined()
    }

    private static func replay<Response: Decodable>(
        from data: Snapshot, key: String, fingerprint: String
    ) throws -> Response? {
        guard data.idempotency[key] != nil else { return nil }
        guard let receipt = data.idempotencyReceipts?[key], receipt.fingerprint == fingerprint else {
            throw APIError(message: "Idempotency key was used for a different command.", statusCode: 409)
        }
        return try JSONDecoder().decode(Response.self, from: receipt.response)
    }

    private static func record<Response: Encodable>(
        in data: inout Snapshot, key: String, objectID: String,
        fingerprint: String, response: Response
    ) throws {
        data.idempotency[key] = objectID
        var receipts = data.idempotencyReceipts ?? [:]
        receipts[key] = IdempotencyReceipt(
            fingerprint: fingerprint, response: try JSONEncoder().encode(response)
        )
        data.idempotencyReceipts = receipts
    }

    private func projectValue(_ project: StoredProject, in data: Snapshot) -> BrainBuddyProject {
        BrainBuddyProject(
            id: project.id, name: project.name, color: project.color,
            state: project.state, revision: project.revision,
            open_task_count: data.tasks.filter { $0.projectID == project.id && $0.isOpen }.count
        )
    }

    private func tagValue(_ tag: StoredTag, in data: Snapshot) -> BrainBuddyTag {
        BrainBuddyTag(
            id: tag.id, name: tag.name, state: tag.state, revision: tag.revision,
            open_task_count: data.tasks.filter { $0.tagIDs.contains(tag.id) && $0.isOpen }.count
        )
    }
}

extension GTDStore {
    func listArchivedProjects() async throws -> [BrainBuddyProject] { [] }
    func archiveProject(_ project: BrainBuddyProject, idempotencyKey: UUID) async throws -> BrainBuddyProject {
        throw APIError(message: "Project archive is unavailable for this store.")
    }
    func unarchiveProject(_ project: BrainBuddyProject, idempotencyKey: UUID) async throws -> BrainBuddyProject {
        throw APIError(message: "Project restore is unavailable for this store.")
    }
    func listTasks(state: TaskList) async throws -> TaskPage {
        try await listTasks(state: state, cursor: nil)
    }
    func listTasks(query: TaskQuery) async throws -> TaskPage {
        try await listTasks(query: query, cursor: nil)
    }
    func transitionTask(
        _ task: BrainBuddyTask, action: TaskTransitionAction,
        idempotencyKey: UUID
    ) async throws -> BrainBuddyTask {
        try await transitionTask(task, action: action, toState: nil, waitingFor: nil, idempotencyKey: idempotencyKey)
    }
    func smartAddTask(
        title: String, state: TaskList, waitingFor: String? = nil,
        project: ClassificationRef? = nil, tags: [ClassificationRef] = [],
        idempotencyKey: UUID
    ) async throws -> SmartAddResult {
        try await smartAddTask(
            title: title, details: nil, state: state, waitingFor: waitingFor,
            dueDate: nil, priority: .none, project: project, tags: tags,
            idempotencyKey: idempotencyKey
        )
    }
}

extension LocalGTDStore {
    func listTasks(state: TaskList, cursor: String? = nil) async throws -> TaskPage {
        try await listTasks(
            query: TaskQuery(state: state, unassignedProject: state == .inbox),
            cursor: cursor
        )
    }

    func listTasks(query: TaskQuery, cursor: String? = nil) async throws -> TaskPage {
        try checkLoaded()
        if query.projectID != nil && query.unassignedProject == true {
            throw APIError(message: "Choose a project or unassigned tasks, not both.")
        }
        if let id = query.projectID,
           !snapshot.projects.contains(where: { $0.id == id && ($0.state == "active" || $0.state == "archived") }) {
            throw Self.missing("Project")
        }
        if let id = query.tagID,
           !snapshot.tags.contains(where: { $0.id == id && $0.state == "active" }) {
            throw Self.missing("Tag")
        }
        let dueFilters = [query.dueBefore, query.dueOn, query.dueAfter].compactMap { $0 }
        if dueFilters.count > 1 { throw APIError(message: "Use only one due date filter at a time.") }
        let search = query.q?.trimmingCharacters(in: .whitespacesAndNewlines)
            .folding(options: [.caseInsensitive, .diacriticInsensitive], locale: .current) ?? ""
        func matchesCommon(_ task: StoredTask) -> Bool {
            if let id = query.projectID, task.projectID != id { return false }
            if let id = query.tagID, !task.tagIDs.contains(id) { return false }
            if query.unassignedProject == true && task.projectID != nil { return false }
            if let priority = query.priority, task.priority != priority { return false }
            if !search.isEmpty {
                let content = "\(task.title)\n\(task.details ?? "")"
                    .folding(options: [.caseInsensitive, .diacriticInsensitive], locale: .current)
                if !content.contains(search) { return false }
            }
            if let date = query.dueBefore, !(task.dueDate.map { $0 < date } ?? false) { return false }
            if let date = query.dueOn, task.dueDate != date { return false }
            if let date = query.dueAfter, !(task.dueDate.map { $0 > date } ?? false) { return false }
            return true
        }
        let common = snapshot.tasks.filter(matchesCommon)
        let counts = TaskCounts(
            inbox: common.filter { $0.state == TaskList.inbox.rawValue }.count,
            next: common.filter { $0.state == TaskList.next.rawValue }.count,
            waiting: common.filter { $0.state == TaskList.waiting.rawValue }.count,
            someday: common.filter { $0.state == TaskList.someday.rawValue }.count
        )
        let rows = common.filter { task in
            if let terminal = query.terminalState { return task.state == terminal.rawValue }
            if let state = query.state {
                if task.state == state.rawValue { return true }
                return task.lastOpenState == state &&
                    ((task.state == "completed" && query.includeCompleted == true) ||
                     (task.state == "cancelled" && query.includeCancelled == true))
            }
            return task.isOpen ||
                (task.state == "completed" && query.includeCompleted == true) ||
                (task.state == "cancelled" && query.includeCancelled == true)
        }.sorted { lhs, rhs in
            switch query.sort ?? .manual {
            case .manual: break
            case .due:
                if lhs.dueDate != rhs.dueDate {
                    if lhs.dueDate == nil { return false }
                    if rhs.dueDate == nil { return true }
                    return lhs.dueDate! < rhs.dueDate!
                }
            case .priority:
                let rank: [TaskPriority: Int] = [.high: 0, .medium: 1, .low: 2, .none: 3]
                if lhs.priority != rhs.priority { return rank[lhs.priority]! < rank[rhs.priority]! }
            case .title:
                let result = lhs.title.localizedStandardCompare(rhs.title)
                if result != .orderedSame { return result == .orderedAscending }
            }
            if lhs.orderKey != rhs.orderKey { return lhs.orderKey < rhs.orderKey }
            if lhs.createdAt != rhs.createdAt { return lhs.createdAt < rhs.createdAt }
            return lhs.id < rhs.id
        }
        var start = 0
        if let cursor {
            let parts = cursor.split(separator: ":", omittingEmptySubsequences: false)
            guard parts.count == 2, Int(parts[0]) == snapshot.generation,
                  let offset = Int(parts[1]), offset >= 0, offset <= rows.count else {
                throw APIError(message: "Task list changed. Reload it from the start.", statusCode: 409)
            }
            start = offset
        }
        let end = min(start + 100, rows.count)
        return TaskPage(
            items: Array(rows[start..<end]).map { $0.publicValue() },
            next_cursor: end < rows.count ? "\(snapshot.generation):\(end)" : nil,
            has_more: end < rows.count, counts_by_state: counts
        )
    }

    func getTask(_ id: String) async throws -> BrainBuddyTask {
        try checkLoaded()
        guard let task = snapshot.tasks.first(where: { $0.id == id }) else { throw Self.missing("Task") }
        return task.publicValue()
    }

    func createTask(
        title: String, state: TaskList, waitingFor: String?, idempotencyKey: UUID
    ) async throws -> BrainBuddyTask {
        try await smartAddTask(
            title: title, details: nil, state: state, waitingFor: waitingFor,
            dueDate: nil, priority: .none, project: nil, tags: [],
            idempotencyKey: idempotencyKey
        ).task
    }

    func smartAddTask(
        title: String, details: String? = nil, state: TaskList,
        waitingFor: String? = nil, dueDate: String? = nil,
        priority: TaskPriority = .none, project: ClassificationRef? = nil,
        tags: [ClassificationRef] = [], idempotencyKey: UUID
    ) async throws -> SmartAddResult {
        let cleanTitle = try Self.text(title, label: "Task title", max: 500)
        let waiting = waitingFor?.trimmingCharacters(in: .whitespacesAndNewlines)
        if state == .waiting && (waiting?.isEmpty ?? true) {
            throw APIError(message: "Waiting tasks require who or what you are waiting for.")
        }
        if state != .waiting && !(waiting?.isEmpty ?? true) {
            throw APIError(message: "Only Waiting tasks may include waiting_for.")
        }
        if let dueDate { try Self.validateDate(dueDate) }
        let key = idempotencyKey.uuidString
        let fingerprint = try Self.fingerprint("task.smart-add", body: SmartAddTaskBody(
            title: title, details: details, state: state.rawValue,
            waiting_for: waitingFor, due_date: dueDate, priority: priority,
            project: project, tags: tags
        ))
        try checkLoaded()
        if let replay: SmartAddResult = try Self.replay(
            from: snapshot, key: key, fingerprint: fingerprint
        ) { return replay }
        return try mutate { data -> SmartAddResult in
            var createdProjectID: String?
            var createdTagIDs: [String] = []
            var projectID: String?
            if let project {
                switch project {
                case .id(let id):
                    guard data.projects.contains(where: { $0.id == id && $0.state == "active" }) else {
                        throw Self.missing("Project")
                    }
                    projectID = id
                case .name(let name):
                    let clean = try Self.text(name, label: "Project name", max: 500)
                    if let found = data.projects.first(where: { $0.state == "active" && $0.name.localizedCaseInsensitiveCompare(clean) == .orderedSame }) {
                        projectID = found.id
                    } else {
                        if data.projects.contains(where: { $0.state == "archived" && $0.name.localizedCaseInsensitiveCompare(clean) == .orderedSame }) {
                            throw APIError(message: "Restore the archived project before using its name.", statusCode: 409)
                        }
                        let item = StoredProject(id: Self.id("project"), name: clean, color: nil, state: "active", revision: 1)
                        data.projects.append(item)
                        projectID = item.id
                        createdProjectID = item.id
                    }
                }
            }
            var tagIDs: [String] = []
            for tag in tags {
                let id: String
                switch tag {
                case .id(let supplied):
                    guard data.tags.contains(where: { $0.id == supplied && $0.state == "active" }) else {
                        throw Self.missing("Tag")
                    }
                    id = supplied
                case .name(let name):
                    let clean = try Self.text(name, label: "Tag name", max: 500)
                    if let found = data.tags.first(where: { $0.state == "active" && $0.name.localizedCaseInsensitiveCompare(clean) == .orderedSame }) {
                        id = found.id
                    } else {
                        let item = StoredTag(id: Self.id("tag"), name: clean, state: "active", revision: 1)
                        data.tags.append(item)
                        id = item.id
                        createdTagIDs.append(id)
                    }
                }
                if !tagIDs.contains(id) { tagIDs.append(id) }
            }
            let now = Self.now()
            let item = StoredTask(
                id: Self.id("task"), title: cleanTitle, details: details,
                state: state.rawValue, lastOpenState: nil, revision: 1,
                projectID: projectID, tagIDs: tagIDs, dueDate: dueDate,
                priority: priority, waitingFor: state == .waiting ? waiting : nil,
                waitingSince: state == .waiting ? now : nil,
                completedAt: nil, cancelledAt: nil,
                orderKey: (data.tasks.filter { $0.state == state.rawValue }.map(\.orderKey).max() ?? 0) + 1,
                createdAt: now, subtasks: [], comments: []
            )
            data.tasks.append(item)
            let result = SmartAddResult(
                task: item.publicValue(),
                project: data.projects.first(where: { $0.id == item.projectID }).map { projectValue($0, in: data) },
                tags: data.tags.filter { item.tagIDs.contains($0.id) }.map { tagValue($0, in: data) },
                created: SmartAddCreated(project_id: createdProjectID, tag_ids: createdTagIDs)
            )
            try Self.record(in: &data, key: key, objectID: item.id,
                            fingerprint: fingerprint, response: result)
            return result
        }
    }

    private static func validateDate(_ value: String) throws {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.isLenient = false
        guard value.count == 10, let parsed = formatter.date(from: value),
              formatter.string(from: parsed) == value else {
            throw APIError(message: "Use a due date in YYYY-MM-DD form.")
        }
    }
}

extension LocalGTDStore {
    func completeTask(_ task: BrainBuddyTask, idempotencyKey: UUID) async throws -> BrainBuddyTask {
        try await transitionTask(
            task, action: .complete, toState: nil, waitingFor: nil,
            idempotencyKey: idempotencyKey
        )
    }

    func updateTask(
        _ task: BrainBuddyTask, changes: TaskChanges, idempotencyKey: UUID
    ) async throws -> BrainBuddyTask {
        let key = idempotencyKey.uuidString
        let fingerprint = try Self.fingerprint("task.update/\(task.id)", body: TaskUpdateBody(
            expected_revision: task.revision, changes: changes
        ))
        try checkLoaded()
        if let replay: StoredTask = try Self.replay(from: snapshot, key: key, fingerprint: fingerprint) {
            return replay.publicValue()
        }
        let updated = try mutate { data -> StoredTask in
            guard let index = data.tasks.firstIndex(where: { $0.id == task.id }) else {
                throw Self.missing("Task")
            }
            guard data.tasks[index].revision == task.revision else { throw Self.conflict("Task") }
            var item = data.tasks[index]
            switch changes.title {
            case .unchanged: break
            case .clear: throw APIError(message: "Task title cannot be empty.")
            case .set(let value): item.title = try Self.text(value, label: "Task title", max: 500)
            }
            switch changes.details {
            case .unchanged: break
            case .clear: item.details = nil
            case .set(let value): item.details = value
            }
            switch changes.projectID {
            case .unchanged: break
            case .clear: item.projectID = nil
            case .set(let id):
                guard data.projects.contains(where: { $0.id == id && $0.state == "active" }) else {
                    throw Self.missing("Project")
                }
                item.projectID = id
            }
            switch changes.tagIDs {
            case .unchanged: break
            case .clear: item.tagIDs = []
            case .set(let ids):
                guard Set(ids).count == ids.count,
                      ids.allSatisfy({ id in data.tags.contains(where: { $0.id == id && $0.state == "active" }) }) else {
                    throw APIError(message: "Choose existing, distinct tags.")
                }
                item.tagIDs = ids
            }
            switch changes.dueDate {
            case .unchanged: break
            case .clear: item.dueDate = nil
            case .set(let value):
                try Self.validateDate(value)
                item.dueDate = value
            }
            switch changes.priority {
            case .unchanged: break
            case .clear: item.priority = .none
            case .set(let value): item.priority = value
            }
            switch changes.waitingFor {
            case .unchanged: break
            case .clear:
                if item.state == TaskList.waiting.rawValue {
                    throw APIError(message: "Waiting tasks require who or what you are waiting for.")
                }
                item.waitingFor = nil
                item.waitingSince = nil
            case .set(let value):
                guard item.state == TaskList.waiting.rawValue else {
                    throw APIError(message: "Only Waiting tasks may include waiting_for.")
                }
                item.waitingFor = try Self.text(value, label: "Waiting for", max: 500)
                item.waitingSince = item.waitingSince ?? Self.now()
            }
            item.revision += 1
            data.tasks[index] = item
            try Self.record(in: &data, key: key, objectID: item.id,
                            fingerprint: fingerprint, response: item)
            return item
        }
        return updated.publicValue()
    }

    func transitionTask(
        _ task: BrainBuddyTask, action: TaskTransitionAction,
        toState: TaskList? = nil, waitingFor: String? = nil,
        idempotencyKey: UUID
    ) async throws -> BrainBuddyTask {
        let key = idempotencyKey.uuidString
        let fingerprint = try Self.fingerprint("task.transition/\(task.id)", body: TaskTransitionBody(
            action: action.rawValue, to_state: toState?.rawValue,
            waiting_for: waitingFor?.trimmingCharacters(in: .whitespacesAndNewlines),
            expected_revision: task.revision
        ))
        try checkLoaded()
        if let replay: StoredTask = try Self.replay(from: snapshot, key: key, fingerprint: fingerprint) {
            return replay.publicValue()
        }
        let updated = try mutate { data -> StoredTask in
            guard let index = data.tasks.firstIndex(where: { $0.id == task.id }) else {
                throw Self.missing("Task")
            }
            guard data.tasks[index].revision == task.revision else { throw Self.conflict("Task") }
            var item = data.tasks[index]
            let now = Self.now()
            switch action {
            case .complete, .cancel:
                guard item.isOpen else { throw APIError(message: "Task is already closed.") }
                item.lastOpenState = TaskList(rawValue: item.state)
                item.state = action == .complete ? "completed" : "cancelled"
                item.completedAt = action == .complete ? now : nil
                item.cancelledAt = action == .cancel ? now : nil
                item.waitingFor = nil
                item.waitingSince = nil
            case .move, .reopen:
                guard let toState else { throw APIError(message: "Choose an open destination.") }
                if action == .move && !item.isOpen { throw APIError(message: "Reopen this task before moving it.") }
                if action == .move && item.state == toState.rawValue {
                    throw APIError(message: "Move requires a different open destination.")
                }
                if action == .reopen && item.isOpen { throw APIError(message: "Task is already open.") }
                let waiting = waitingFor?.trimmingCharacters(in: .whitespacesAndNewlines)
                if toState == .waiting && (waiting?.isEmpty ?? true) {
                    throw APIError(message: "Waiting tasks require who or what you are waiting for.")
                }
                if toState != .waiting && !(waiting?.isEmpty ?? true) {
                    throw APIError(message: "Only Waiting tasks may include waiting_for.")
                }
                item.state = toState.rawValue
                item.lastOpenState = nil
                item.completedAt = nil
                item.cancelledAt = nil
                item.waitingFor = toState == .waiting ? waiting : nil
                item.waitingSince = toState == .waiting ? now : nil
                item.orderKey = (data.tasks.filter { $0.state == toState.rawValue }.map(\.orderKey).max() ?? 0) + 1
            }
            item.revision += 1
            data.tasks[index] = item
            try Self.record(in: &data, key: key, objectID: item.id,
                            fingerprint: fingerprint, response: item)
            return item
        }
        return updated.publicValue()
    }
}

extension LocalGTDStore {
    func createSubtask(
        taskID: String, title: String, idempotencyKey: UUID
    ) async throws -> BrainBuddySubtask {
        let clean = try Self.text(title, label: "Subtask title", max: 500)
        let key = idempotencyKey.uuidString
        let fingerprint = try Self.fingerprint("subtask.create/\(taskID)", body: SubtaskCreateBody(title: title))
        try checkLoaded()
        if let replay: StoredSubtask = try Self.replay(from: snapshot, key: key, fingerprint: fingerprint) {
            return replay.publicValue()
        }
        let created = try mutate { data -> StoredSubtask in
            guard let index = data.tasks.firstIndex(where: { $0.id == taskID }) else {
                throw Self.missing("Task")
            }
            let item = StoredSubtask(
                id: Self.id("subtask"), title: clean, state: "open",
                orderKey: (data.tasks[index].subtasks.map(\.orderKey).max() ?? 0) + 1,
                revision: 1
            )
            data.tasks[index].subtasks.append(item)
            data.tasks[index].revision += 1
            try Self.record(in: &data, key: key, objectID: item.id,
                            fingerprint: fingerprint, response: item)
            return item
        }
        return created.publicValue()
    }

    func updateSubtask(
        taskID: String, subtask: BrainBuddySubtask, title: String, idempotencyKey: UUID
    ) async throws -> BrainBuddySubtask {
        let clean = try Self.text(title, label: "Subtask title", max: 500)
        let key = idempotencyKey.uuidString
        let fingerprint = try Self.fingerprint("subtask.update/\(taskID)/\(subtask.id)", body:
            SubtaskUpdateBody(title: title, expected_revision: subtask.revision))
        try checkLoaded()
        if let replay: StoredSubtask = try Self.replay(from: snapshot, key: key, fingerprint: fingerprint) {
            return replay.publicValue()
        }
        let updated = try mutate { data -> StoredSubtask in
            guard let taskIndex = data.tasks.firstIndex(where: { $0.id == taskID }),
                  let index = data.tasks[taskIndex].subtasks.firstIndex(where: { $0.id == subtask.id }) else {
                throw Self.missing("Subtask")
            }
            guard data.tasks[taskIndex].subtasks[index].revision == subtask.revision else {
                throw Self.conflict("Subtask")
            }
            data.tasks[taskIndex].subtasks[index].title = clean
            data.tasks[taskIndex].subtasks[index].revision += 1
            data.tasks[taskIndex].revision += 1
            let item = data.tasks[taskIndex].subtasks[index]
            try Self.record(in: &data, key: key, objectID: item.id,
                            fingerprint: fingerprint, response: item)
            return item
        }
        return updated.publicValue()
    }

    func transitionSubtask(
        taskID: String, subtask: BrainBuddySubtask,
        action: SubtaskTransitionAction, idempotencyKey: UUID
    ) async throws -> BrainBuddySubtask {
        let key = idempotencyKey.uuidString
        let fingerprint = try Self.fingerprint("subtask.transition/\(taskID)/\(subtask.id)", body:
            SubtaskTransitionBody(action: action, expected_revision: subtask.revision))
        try checkLoaded()
        if let replay: StoredSubtask = try Self.replay(from: snapshot, key: key, fingerprint: fingerprint) {
            return replay.publicValue()
        }
        let updated = try mutate { data -> StoredSubtask in
            guard let taskIndex = data.tasks.firstIndex(where: { $0.id == taskID }),
                  let index = data.tasks[taskIndex].subtasks.firstIndex(where: { $0.id == subtask.id }) else {
                throw Self.missing("Subtask")
            }
            guard data.tasks[taskIndex].subtasks[index].revision == subtask.revision else {
                throw Self.conflict("Subtask")
            }
            let oldState = data.tasks[taskIndex].subtasks[index].state
            if action == .reopen && oldState == "open" {
                throw APIError(message: "Subtask is already open.")
            }
            if action != .reopen && oldState != "open" {
                throw APIError(message: "Subtask is already closed.")
            }
            switch action {
            case .complete: data.tasks[taskIndex].subtasks[index].state = "completed"
            case .cancel: data.tasks[taskIndex].subtasks[index].state = "cancelled"
            case .reopen: data.tasks[taskIndex].subtasks[index].state = "open"
            }
            data.tasks[taskIndex].subtasks[index].revision += 1
            data.tasks[taskIndex].revision += 1
            let item = data.tasks[taskIndex].subtasks[index]
            try Self.record(in: &data, key: key, objectID: item.id,
                            fingerprint: fingerprint, response: item)
            return item
        }
        return updated.publicValue()
    }

    func createComment(
        taskID: String, body: String, idempotencyKey: UUID
    ) async throws -> BrainBuddyComment {
        let clean = try Self.text(body, label: "Comment", max: 20_000)
        let key = idempotencyKey.uuidString
        let fingerprint = try Self.fingerprint("comment.create/\(taskID)", body: CommentCreateBody(body: body))
        try checkLoaded()
        if let replay: StoredComment = try Self.replay(from: snapshot, key: key, fingerprint: fingerprint) {
            return replay.publicValue()
        }
        let created = try mutate { data -> StoredComment in
            guard let taskIndex = data.tasks.firstIndex(where: { $0.id == taskID }) else {
                throw Self.missing("Task")
            }
            let item = StoredComment(
                id: Self.id("comment"), body: clean, actorID: "local",
                createdAt: Self.now(), editedAt: nil, revision: 1
            )
            data.tasks[taskIndex].comments.append(item)
            data.tasks[taskIndex].revision += 1
            try Self.record(in: &data, key: key, objectID: item.id,
                            fingerprint: fingerprint, response: item)
            return item
        }
        return created.publicValue()
    }

    func updateComment(
        taskID: String, comment: BrainBuddyComment, body: String, idempotencyKey: UUID
    ) async throws -> BrainBuddyComment {
        let clean = try Self.text(body, label: "Comment", max: 20_000)
        let key = idempotencyKey.uuidString
        let fingerprint = try Self.fingerprint("comment.update/\(taskID)/\(comment.id)", body:
            CommentUpdateBody(body: body, expected_revision: comment.revision))
        try checkLoaded()
        if let replay: StoredComment = try Self.replay(from: snapshot, key: key, fingerprint: fingerprint) {
            return replay.publicValue()
        }
        let updated = try mutate { data -> StoredComment in
            guard let taskIndex = data.tasks.firstIndex(where: { $0.id == taskID }),
                  let index = data.tasks[taskIndex].comments.firstIndex(where: { $0.id == comment.id }) else {
                throw Self.missing("Comment")
            }
            guard data.tasks[taskIndex].comments[index].revision == comment.revision else {
                throw Self.conflict("Comment")
            }
            data.tasks[taskIndex].comments[index].body = clean
            data.tasks[taskIndex].comments[index].editedAt = Self.now()
            data.tasks[taskIndex].comments[index].revision += 1
            data.tasks[taskIndex].revision += 1
            let item = data.tasks[taskIndex].comments[index]
            try Self.record(in: &data, key: key, objectID: item.id,
                            fingerprint: fingerprint, response: item)
            return item
        }
        return updated.publicValue()
    }
}

extension LocalGTDStore {
    func listProjects() async throws -> [BrainBuddyProject] {
        try checkLoaded()
        return snapshot.projects.filter { $0.state == "active" }
            .sorted { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
            .map { projectValue($0, in: snapshot) }
    }

    func listArchivedProjects() async throws -> [BrainBuddyProject] {
        try checkLoaded()
        return snapshot.projects.filter { $0.state == "archived" }
            .sorted { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
            .map { projectValue($0, in: snapshot) }
    }

    func listTags() async throws -> [BrainBuddyTag] {
        try checkLoaded()
        return snapshot.tags.filter { $0.state == "active" }
            .sorted { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
            .map { tagValue($0, in: snapshot) }
    }

    func createProject(name: String, idempotencyKey: UUID) async throws -> BrainBuddyProject {
        let clean = try Self.text(name, label: "Project name", max: 500)
        let key = idempotencyKey.uuidString
        let fingerprint = try Self.fingerprint("project.create", body: CreateProjectBody(name: name))
        try checkLoaded()
        if let result: BrainBuddyProject = try Self.replay(from: snapshot, key: key, fingerprint: fingerprint) {
            return result
        }
        return try mutate { data -> BrainBuddyProject in
            guard !data.projects.contains(where: { $0.name.localizedCaseInsensitiveCompare(clean) == .orderedSame }) else {
                throw APIError(message: "A project with that name already exists.", statusCode: 409)
            }
            let project = StoredProject(id: Self.id("project"), name: clean, color: nil, state: "active", revision: 1)
            data.projects.append(project)
            let result = projectValue(project, in: data)
            try Self.record(in: &data, key: key, objectID: project.id, fingerprint: fingerprint, response: result)
            return result
        }
    }

    func createTag(name: String, idempotencyKey: UUID) async throws -> BrainBuddyTag {
        let clean = try Self.text(name, label: "Tag name", max: 500)
        let key = idempotencyKey.uuidString
        let fingerprint = try Self.fingerprint("tag.create", body: CreateTagBody(name: name))
        try checkLoaded()
        if let result: BrainBuddyTag = try Self.replay(from: snapshot, key: key, fingerprint: fingerprint) {
            return result
        }
        return try mutate { data -> BrainBuddyTag in
            guard !data.tags.contains(where: { $0.state == "active" && $0.name.localizedCaseInsensitiveCompare(clean) == .orderedSame }) else {
                throw APIError(message: "A tag with that name already exists.", statusCode: 409)
            }
            let tag = StoredTag(id: Self.id("tag"), name: clean, state: "active", revision: 1)
            data.tags.append(tag)
            let result = tagValue(tag, in: data)
            try Self.record(in: &data, key: key, objectID: tag.id, fingerprint: fingerprint, response: result)
            return result
        }
    }

    func renameProject(
        _ project: BrainBuddyProject, to name: String, idempotencyKey: UUID
    ) async throws -> BrainBuddyProject {
        let clean = try Self.text(name, label: "Project name", max: 500)
        let key = idempotencyKey.uuidString
        let fingerprint = try Self.fingerprint(
            "project.rename/\(project.id)", body: RenameCollectionBody(name: name, expected_revision: project.revision)
        )
        try checkLoaded()
        if let result: BrainBuddyProject = try Self.replay(from: snapshot, key: key, fingerprint: fingerprint) {
            return result
        }
        return try mutate { data -> BrainBuddyProject in
            guard let index = data.projects.firstIndex(where: { $0.id == project.id && $0.state == "active" }) else {
                throw Self.missing("Project")
            }
            guard data.projects[index].revision == project.revision else { throw Self.conflict("Project") }
            guard !data.projects.contains(where: {
                $0.id != project.id &&
                    $0.name.localizedCaseInsensitiveCompare(clean) == .orderedSame
            }) else { throw APIError(message: "A project with that name already exists.", statusCode: 409) }
            data.projects[index].name = clean
            data.projects[index].revision += 1
            let result = projectValue(data.projects[index], in: data)
            try Self.record(in: &data, key: key, objectID: project.id, fingerprint: fingerprint, response: result)
            return result
        }
    }

    func renameTag(
        _ tag: BrainBuddyTag, to name: String, idempotencyKey: UUID
    ) async throws -> BrainBuddyTag {
        let clean = try Self.text(name, label: "Tag name", max: 500)
        let key = idempotencyKey.uuidString
        let fingerprint = try Self.fingerprint(
            "tag.rename/\(tag.id)", body: RenameCollectionBody(name: name, expected_revision: tag.revision)
        )
        try checkLoaded()
        if let result: BrainBuddyTag = try Self.replay(from: snapshot, key: key, fingerprint: fingerprint) {
            return result
        }
        return try mutate { data -> BrainBuddyTag in
            guard let index = data.tags.firstIndex(where: { $0.id == tag.id && $0.state == "active" }) else {
                throw Self.missing("Tag")
            }
            guard data.tags[index].revision == tag.revision else { throw Self.conflict("Tag") }
            guard !data.tags.contains(where: {
                $0.id != tag.id && $0.state == "active" &&
                    $0.name.localizedCaseInsensitiveCompare(clean) == .orderedSame
            }) else { throw APIError(message: "A tag with that name already exists.", statusCode: 409) }
            data.tags[index].name = clean
            data.tags[index].revision += 1
            let result = tagValue(data.tags[index], in: data)
            try Self.record(in: &data, key: key, objectID: tag.id, fingerprint: fingerprint, response: result)
            return result
        }
    }

    func deleteTag(_ tag: BrainBuddyTag, idempotencyKey: UUID) async throws -> BrainBuddyTag {
        let key = idempotencyKey.uuidString
        let fingerprint = try Self.fingerprint("tag.delete/\(tag.id)", body: ["expected_revision": tag.revision])
        try checkLoaded()
        if let result: BrainBuddyTag = try Self.replay(from: snapshot, key: key, fingerprint: fingerprint) {
            return result
        }
        return try mutate { data -> BrainBuddyTag in
            guard let index = data.tags.firstIndex(where: { $0.id == tag.id }) else { throw Self.missing("Tag") }
            guard data.tags[index].state == "active" else { throw Self.missing("Tag") }
            guard data.tags[index].revision == tag.revision else { throw Self.conflict("Tag") }
            data.tags[index].state = "deleted"
            data.tags[index].revision += 1
            for taskIndex in data.tasks.indices where data.tasks[taskIndex].tagIDs.contains(tag.id) {
                data.tasks[taskIndex].tagIDs.removeAll { $0 == tag.id }
                data.tasks[taskIndex].revision += 1
            }
            let result = tagValue(data.tags[index], in: data)
            try Self.record(in: &data, key: key, objectID: tag.id, fingerprint: fingerprint, response: result)
            return result
        }
    }

    /// Hides the project but retains every task's project membership, including
    /// completed and cancelled tasks. Local archive is available before sync.
    func archiveProject(_ project: BrainBuddyProject, idempotencyKey: UUID) async throws -> BrainBuddyProject {
        let key = idempotencyKey.uuidString
        let fingerprint = try Self.fingerprint("project.archive/\(project.id)", body: ["expected_revision": project.revision])
        try checkLoaded()
        if let result: BrainBuddyProject = try Self.replay(from: snapshot, key: key, fingerprint: fingerprint) {
            return result
        }
        return try mutate { data -> BrainBuddyProject in
            guard let index = data.projects.firstIndex(where: { $0.id == project.id }) else {
                throw Self.missing("Project")
            }
            guard data.projects[index].state == "active" else { throw Self.missing("Project") }
            guard data.projects[index].revision == project.revision else { throw Self.conflict("Project") }
            data.projects[index].state = "archived"
            data.projects[index].revision += 1
            let result = projectValue(data.projects[index], in: data)
            try Self.record(in: &data, key: key, objectID: project.id, fingerprint: fingerprint, response: result)
            return result
        }
    }

    func unarchiveProject(_ project: BrainBuddyProject, idempotencyKey: UUID) async throws -> BrainBuddyProject {
        let key = idempotencyKey.uuidString
        let fingerprint = try Self.fingerprint("project.unarchive/\(project.id)", body: ["expected_revision": project.revision])
        try checkLoaded()
        if let result: BrainBuddyProject = try Self.replay(from: snapshot, key: key, fingerprint: fingerprint) {
            return result
        }
        return try mutate { data -> BrainBuddyProject in
            guard let index = data.projects.firstIndex(where: { $0.id == project.id }) else {
                throw Self.missing("Project")
            }
            guard data.projects[index].state == "archived" else { throw Self.missing("Project") }
            guard data.projects[index].revision == project.revision else { throw Self.conflict("Project") }
            guard !data.projects.contains(where: {
                $0.id != project.id && $0.state == "active" &&
                    $0.name.localizedCaseInsensitiveCompare(project.name) == .orderedSame
            }) else { throw APIError(message: "An active project already uses this name.", statusCode: 409) }
            data.projects[index].state = "active"
            data.projects[index].revision += 1
            let result = projectValue(data.projects[index], in: data)
            try Self.record(in: &data, key: key, objectID: project.id, fingerprint: fingerprint, response: result)
            return result
        }
    }
}
