import BrainBuddyAPI
import BrainBuddyCore
import Foundation

/// How a task written into the base treats its subtasks and comments.
enum ChildrenUpdate: Sendable {
    /// Keep the base's children (list items and mutation responses carry none).
    case keep
    /// A new task: it has no children on the server yet.
    case created(Date)
    /// A `GET /tasks/{id}` detail: its children replace the base's, except
    /// that a child the base holds at a newer revision keeps that revision,
    /// and a child the base learned after the read started (missing from
    /// `known`, acknowledged meanwhile) is kept even though the detail lacks it.
    case replace(Date, known: KnownChildren)
}

/// The children of one task the base knew when a `GET /tasks/{id}` started.
struct KnownChildren: Hashable, Sendable {
    var subtasks: Set<String> = []
    var comments: Set<String> = []

    init(_ task: TaskRecord?) {
        subtasks = Set(task?.subtasks.compactMap(\.serverID) ?? [])
        comments = Set(task?.comments.compactMap(\.serverID) ?? [])
    }

    /// Per server task id, for the tasks of `base` among `serverIDs`.
    static func snapshot(of serverIDs: some Sequence<String>, in base: GTDState) -> [String: KnownChildren] {
        let wanted = Set(serverIDs)
        var result: [String: KnownChildren] = [:]
        for task in base.tasks.values {
            guard let serverID = task.serverID, wanted.contains(serverID) else { continue }
            result[serverID] = KnownChildren(task)
        }
        return result
    }
}

/// Writing server records into `base`. Every write keeps the client ids the
/// device already uses (matched by `serverID`), never replaces a record with
/// an older revision, and keeps local-only fields (`lastOpenList`).
extension StoreDocument {
    // MARK: - Projects and tags

    /// Writes `dto` into the base and returns its client id: `preferred` for
    /// an acknowledged create, else the id the base already uses for this
    /// server record, else a new one.
    @discardableResult
    mutating func upsert(project dto: ProjectDTO, as preferred: ProjectID? = nil, now: Date) -> ProjectID {
        let known = base.projects.values.first { $0.serverID == dto.id }?.id
        let id = preferred ?? known ?? ProjectID.random()
        if let known, known != id { rekey(project: known, to: id) }
        let existing = base.projects[id]
        if let existing, (existing.serverRevision ?? .min) > dto.revision { return id }
        base.projects[id] = ProjectRecord(
            id: id, serverID: dto.id, serverRevision: dto.revision, name: dto.name, color: dto.color,
            state: dto.state, createdAt: existing?.createdAt ?? now
        )
        if dto.state == .archived {
            // The server removed the project from every task (and bumped them).
            for task in base.tasks.values where task.projectID == id { base.tasks[task.id]?.projectID = nil }
        }
        return id
    }

    @discardableResult
    mutating func upsert(tag dto: TagDTO, as preferred: TagID? = nil, now: Date) -> TagID {
        let known = base.tags.values.first { $0.serverID == dto.id }?.id
        let id = preferred ?? known ?? TagID.random()
        if let known, known != id { rekey(tag: known, to: id) }
        let existing = base.tags[id]
        if let existing, (existing.serverRevision ?? .min) > dto.revision { return id }
        base.tags[id] = TagRecord(
            id: id, serverID: dto.id, serverRevision: dto.revision, name: dto.name, state: dto.state,
            createdAt: existing?.createdAt ?? now
        )
        if dto.state == .deleted {
            for task in base.tasks.values where task.tagIDs.contains(id) { base.tasks[task.id]?.tagIDs.removeAll { $0 == id } }
        }
        return id
    }

    /// Moves a base project to another client id, with every reference to it.
    mutating func rekey(project old: ProjectID, to new: ProjectID) {
        guard old != new, var record = base.projects.removeValue(forKey: old) else { return }
        record.id = new
        base.projects[new] = record
        for task in base.tasks.values where task.projectID == old { base.tasks[task.id]?.projectID = new }
        for index in outbox.indices { outbox[index].command = outbox[index].command.replacing(project: old, with: new) }
    }

    mutating func rekey(tag old: TagID, to new: TagID) {
        guard old != new, var record = base.tags.removeValue(forKey: old) else { return }
        record.id = new
        base.tags[new] = record
        for task in base.tasks.values where task.tagIDs.contains(old) {
            var seen = Set<TagID>()
            base.tasks[task.id]?.tagIDs = task.tagIDs.map { $0 == old ? new : $0 }.filter { seen.insert($0).inserted }
        }
        for index in outbox.indices { outbox[index].command = outbox[index].command.replacing(tag: old, with: new) }
    }

    // MARK: - Tasks

    @discardableResult
    mutating func upsert(task dto: TaskDTO, as preferred: TaskID? = nil, children: ChildrenUpdate, now: Date) -> TaskID {
        let known = base.tasks.values.first { $0.serverID == dto.id }?.id
        let id = preferred ?? known ?? TaskID.random()
        if let known, known != id { rekey(task: known, to: id) }
        let existing = base.tasks[id]
        var record: TaskRecord
        if let existing, (existing.serverRevision ?? .min) > dto.revision {
            record = existing
        } else {
            record = Self.taskRecord(
                dto, id: id, existing: existing,
                projectID: dto.projectID.flatMap { sid in base.projects.values.first { $0.serverID == sid }?.id },
                tagIDs: dto.tagIDs.compactMap { sid in base.tags.values.first { $0.serverID == sid }?.id }
            )
        }
        switch children {
        case .keep:
            break
        case .created(let date):
            if existing == nil {
                record.subtasks = []
                record.comments = []
                record.childrenSyncedAt = date
            }
        case .replace(let date, let known):
            record.subtasks = Self.subtasks(dto.subtasks, existing: existing?.subtasks ?? [], known: known.subtasks)
            record.comments = Self.comments(dto.comments, existing: existing?.comments ?? [], known: known.comments)
            record.childrenSyncedAt = date
        }
        base.tasks[id] = record
        return id
    }

    /// Moves a base task to another client id; queued commands follow it.
    mutating func rekey(task old: TaskID, to new: TaskID) {
        guard old != new, var record = base.tasks.removeValue(forKey: old) else { return }
        record.id = new
        base.tasks[new] = record
        for index in outbox.indices { outbox[index].command = outbox[index].command.replacing(task: old, with: new) }
    }

    /// A base task from a server task. `lastOpenList` is local knowledge: a
    /// task that was open in the base and is now terminal remembers that
    /// list; a terminal task that stays in the same state keeps what it had.
    static func taskRecord(
        _ dto: TaskDTO, id: TaskID, existing: TaskRecord?, projectID: ProjectID?, tagIDs: [TagID]
    ) -> TaskRecord {
        var lastOpenList: OpenList?
        if dto.state.isTerminal, let existing {
            lastOpenList = existing.openList ?? (existing.state == dto.state ? existing.lastOpenList : nil)
        }
        return TaskRecord(
            id: id, serverID: dto.id, serverRevision: dto.revision, title: dto.title, details: dto.details,
            state: dto.state, lastOpenList: lastOpenList, projectID: projectID, tagIDs: tagIDs, dueDate: dto.dueDate,
            priority: dto.priority, waitingFor: dto.waitingFor, waitingSince: dto.waitingSince,
            completedAt: dto.completedAt, cancelledAt: dto.cancelledAt, orderKey: dto.orderKey,
            createdAt: dto.createdAt, updatedAt: dto.updatedAt, subtasks: existing?.subtasks ?? [],
            comments: existing?.comments ?? [], childrenSyncedAt: existing?.childrenSyncedAt
        )
    }

    /// A detail's subtasks under the ids the base uses. A base subtask at a
    /// newer revision than the detail wins; one the detail lacks survives when
    /// `known` (the base's subtasks when the read started) lacks it too.
    static func subtasks(_ items: [SubtaskDTO], existing: [SubtaskRecord], known: Set<String>) -> [SubtaskRecord] {
        var byServerID: [String: SubtaskRecord] = [:]
        for subtask in existing { if let sid = subtask.serverID { byServerID[sid] = subtask } }
        var merged = items.map { item in
            if let current = byServerID[item.id], (current.serverRevision ?? .min) > item.revision { return current }
            return SubtaskRecord(
                id: byServerID[item.id]?.id ?? SubtaskID.random(), serverID: item.id, serverRevision: item.revision,
                title: item.title, state: item.state, orderKey: item.orderKey
            )
        }
        let listed = Set(items.map(\.id))
        merged += existing.filter { subtask in
            guard let sid = subtask.serverID else { return false }
            return !listed.contains(sid) && !known.contains(sid)
        }
        return merged.sorted { ($0.orderKey, $0.serverID ?? "") < ($1.orderKey, $1.serverID ?? "") }
    }

    /// The same for comments.
    static func comments(_ items: [CommentDTO], existing: [CommentRecord], known: Set<String>) -> [CommentRecord] {
        var byServerID: [String: CommentRecord] = [:]
        for comment in existing { if let sid = comment.serverID { byServerID[sid] = comment } }
        var merged = items.map { item in
            if let current = byServerID[item.id], (current.serverRevision ?? .min) > item.revision { return current }
            return CommentRecord(
                id: byServerID[item.id]?.id ?? CommentID.random(), serverID: item.id, serverRevision: item.revision,
                body: item.body, authorID: item.actorID, createdAt: item.createdAt, editedAt: item.editedAt
            )
        }
        let listed = Set(items.map(\.id))
        merged += existing.filter { comment in
            guard let sid = comment.serverID else { return false }
            return !listed.contains(sid) && !known.contains(sid)
        }
        return merged.sorted { ($0.createdAt, $0.serverID ?? "") < ($1.createdAt, $1.serverID ?? "") }
    }

    // MARK: - Subtasks and comments

    mutating func upsert(subtask dto: SubtaskDTO, in taskID: TaskID, as preferred: SubtaskID? = nil) {
        guard var task = base.tasks[taskID] else { return }
        let known = task.subtasks.first { $0.serverID == dto.id }?.id
        let id = preferred ?? known ?? SubtaskID.random()
        if let known, known != id {
            task.subtasks.removeAll { $0.id == id }
            if let index = task.subtasks.firstIndex(where: { $0.id == known }) { task.subtasks[index].id = id }
            for index in outbox.indices {
                outbox[index].command = outbox[index].command.replacing(subtask: known, with: id)
            }
        }
        let record = SubtaskRecord(
            id: id, serverID: dto.id, serverRevision: dto.revision, title: dto.title, state: dto.state,
            orderKey: dto.orderKey
        )
        if let index = task.subtasks.firstIndex(where: { $0.id == id }) {
            if (task.subtasks[index].serverRevision ?? .min) <= dto.revision { task.subtasks[index] = record }
        } else {
            task.subtasks.append(record)
        }
        task.subtasks.sort { ($0.orderKey, $0.serverID ?? "") < ($1.orderKey, $1.serverID ?? "") }
        base.tasks[taskID] = task
    }

    mutating func upsert(comment dto: CommentDTO, in taskID: TaskID, as preferred: CommentID? = nil) {
        guard var task = base.tasks[taskID] else { return }
        let known = task.comments.first { $0.serverID == dto.id }?.id
        let id = preferred ?? known ?? CommentID.random()
        if let known, known != id {
            task.comments.removeAll { $0.id == id }
            if let index = task.comments.firstIndex(where: { $0.id == known }) { task.comments[index].id = id }
            for index in outbox.indices {
                outbox[index].command = outbox[index].command.replacing(comment: known, with: id)
            }
        }
        let record = CommentRecord(
            id: id, serverID: dto.id, serverRevision: dto.revision, body: dto.body, authorID: dto.actorID,
            createdAt: dto.createdAt, editedAt: dto.editedAt
        )
        if let index = task.comments.firstIndex(where: { $0.id == id }) {
            if (task.comments[index].serverRevision ?? .min) <= dto.revision { task.comments[index] = record }
        } else {
            task.comments.append(record)
        }
        task.comments.sort { ($0.createdAt, $0.serverID ?? "") < ($1.createdAt, $1.serverID ?? "") }
        base.tasks[taskID] = task
    }

    // MARK: - Acknowledgements

    /// Writes a 2xx answer to `command` into the base. New records take the
    /// command's client id.
    mutating func apply(_ record: ServerRecord, answering command: GTDCommand, now: Date) {
        switch (command, record) {
        case (.createProject(let create), .project(let dto)):
            upsert(project: dto, as: create.projectID, now: now)
        case (.createTag(let create), .tag(let dto)):
            upsert(tag: dto, as: create.tagID, now: now)
        case (.createTask(let create), .task(let dto)):
            upsert(task: dto, as: create.taskID, children: .created(now), now: now)
        case (.createSubtask(let create), .subtask(let dto)):
            upsert(subtask: dto, in: create.taskID, as: create.subtaskID)
        case (.updateSubtask(let update), .subtask(let dto)):
            upsert(subtask: dto, in: update.taskID, as: update.subtaskID)
        case (.transitionSubtask(let transition), .subtask(let dto)):
            upsert(subtask: dto, in: transition.taskID, as: transition.subtaskID)
        case (.createComment(let create), .comment(let dto)):
            upsert(comment: dto, in: create.taskID, as: create.commentID)
        case (.updateComment(let update), .comment(let dto)):
            upsert(comment: dto, in: update.taskID, as: update.commentID)
        case (_, .project(let dto)):
            upsert(project: dto, now: now)
        case (_, .tag(let dto)):
            upsert(tag: dto, now: now)
        case (_, .task(let dto)):
            upsert(task: dto, children: .keep, now: now)
        case (_, .subtask), (_, .comment):
            break
        }
    }

    // MARK: - Pulls

    /// The base after a full pull: exactly the records the server returned,
    /// under the client ids the device already uses. Children and
    /// `childrenSyncedAt` carry over; a task whose revision changed is marked
    /// for hydration. A record the base has at a newer revision than the
    /// pull (written while the pull was in flight) is kept.
    static func pulledBase(
        from old: GTDState, tasks: [TaskDTO], projects: [ProjectDTO], tags: [TagDTO], now: Date
    ) -> GTDState {
        var new = GTDState()
        var projectIDs: [String: ProjectID] = [:]
        for project in old.projects.values { if let sid = project.serverID { projectIDs[sid] = project.id } }
        var tagIDs: [String: TagID] = [:]
        for tag in old.tags.values { if let sid = tag.serverID { tagIDs[sid] = tag.id } }
        var taskIDs: [String: TaskID] = [:]
        for task in old.tasks.values { if let sid = task.serverID { taskIDs[sid] = task.id } }

        for dto in projects {
            let id = projectIDs[dto.id] ?? ProjectID.random()
            projectIDs[dto.id] = id
            let existing = old.projects[id]
            if let existing, (existing.serverRevision ?? .min) > dto.revision {
                new.projects[id] = existing
                continue
            }
            new.projects[id] = ProjectRecord(
                id: id, serverID: dto.id, serverRevision: dto.revision, name: dto.name, color: dto.color,
                state: dto.state, createdAt: existing?.createdAt ?? now
            )
        }
        for dto in tags {
            let id = tagIDs[dto.id] ?? TagID.random()
            tagIDs[dto.id] = id
            let existing = old.tags[id]
            if let existing, (existing.serverRevision ?? .min) > dto.revision {
                new.tags[id] = existing
                continue
            }
            new.tags[id] = TagRecord(
                id: id, serverID: dto.id, serverRevision: dto.revision, name: dto.name, state: dto.state,
                createdAt: existing?.createdAt ?? now
            )
        }
        for dto in tasks {
            let id = taskIDs[dto.id] ?? TaskID.random()
            taskIDs[dto.id] = id
            let existing = old.tasks[id]
            if let existing, (existing.serverRevision ?? .min) > dto.revision {
                new.tasks[id] = existing
                continue
            }
            var record = taskRecord(
                dto, id: id, existing: existing,
                projectID: dto.projectID.flatMap { new.projects[projectIDs[$0] ?? ProjectID("")]?.id },
                tagIDs: dto.tagIDs.compactMap { new.tags[tagIDs[$0] ?? TagID("")]?.id }
            )
            if existing?.serverRevision != dto.revision { record.childrenSyncedAt = nil }
            new.tasks[id] = record
        }
        return new
    }

    // MARK: - Outbox upkeep

    /// Gives every sent operation whose request body a new base changes (its
    /// `expected_revision`) a new idempotency key: the old key is bound to
    /// the old body, and reusing it would be an idempotency conflict.
    mutating func rotateKeys(comparedTo old: GTDState) {
        for index in outbox.indices where outbox[index].hasBeenSent {
            let command = outbox[index].command
            if command.expectedRevision(in: old) != command.expectedRevision(in: base) { outbox[index].rotateKey() }
        }
    }

    /// Recomputes the outbox against the base: satisfied operations drop out,
    /// merged creates rewrite later references, and rejected operations
    /// become sync issues.
    mutating func replayOutbox(now: Date) {
        let result = OutboxReplayer.replay(outbox, onto: base)
        outbox = result.outbox
        issues += result.rejected.map {
            SyncIssue(command: $0.operation.command, message: $0.error.message, occurredAt: now)
        }
    }

    /// The last time this device exchanged data with the server.
    var lastSyncedAt: Date? {
        switch (sync.lastPullAt, sync.lastPushAt) {
        case (let pull?, let push?): max(pull, push)
        case (let pull, let push): pull ?? push
        }
    }
}
