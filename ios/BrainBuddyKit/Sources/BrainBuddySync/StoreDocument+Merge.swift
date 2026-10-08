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
        base.projects[id] = ProjectRecord(dto, id: id, createdAt: existing?.createdAt ?? now)
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
            comments: existing?.comments ?? [], childrenSyncedAt: existing?.childrenSyncedAt,
            formulation: dto.formulation?.clock,
            // The count is on the wire only with an open formulation; outside
            // Next the device keeps what it knew (FR-005).
            consecutiveStalledFormulations: dto.formulation?.consecutiveStalled
                ?? existing?.consecutiveStalledFormulations ?? 0,
            parked: dto.parked.map { park in
                // The server keeps `clock_before`; a park this device made keeps
                // its own, and a park made elsewhere of the formulation this
                // device last saw in Next keeps that clock, so a decision made
                // before the park can yield with the clock it was made on.
                let local = existing?.parked.flatMap { $0.formulationID.rawValue == park.formulationID ? $0 : nil }
                let seen = existing.flatMap { task in
                    task.state == .next && task.formulation?.id.rawValue == park.formulationID ? task : nil
                }
                return ParkMarker(
                    at: park.at, formulationID: FormulationID(park.formulationID),
                    fromRevision: local?.fromRevision,
                    clockBefore: local?.clockBefore ?? seen?.formulation,
                    stalledBefore: local?.stalledBefore ?? seen?.consecutiveStalledFormulations ?? 0
                )
            }
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

    /// Writes a 2xx answer to `operation` into the base. New records take the
    /// command's client id.
    mutating func apply(_ record: ServerRecord, answering operation: PendingOperation, now: Date) {
        if applyReview(record, answering: operation, now: now) { return }
        let command = operation.command
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
        case (_, .subtask), (_, .comment), (_, .decision), (_, .undoneDecision), (_, .autoPark), (_, .reviewState),
            (_, .reviewSettings), (_, .session), (_, .bulkRelease), (_, .bulkUndo), (_, .accepted):
            break
        }
    }

    // MARK: - Weekly review (spec 020)

    /// The base task with this server id.
    func baseTaskID(server id: String) -> TaskID? { base.tasks.values.first { $0.serverID == id }?.id }

    /// Writes an acknowledged review command into the base: the command is
    /// applied to the base (so it holds what was acknowledged, with the
    /// device's own records such as an Undo snapshot), then the server's
    /// answer overrides tasks, revisions and counts. Returns false for other
    /// commands.
    mutating func applyReview(_ record: ServerRecord, answering operation: PendingOperation, now: Date) -> Bool {
        let command = operation.command
        var scratch = base
        _ = try? GTDReducer.apply(command, at: operation.issuedAt, to: &scratch, mode: .replay)
        switch (command, record) {
        case (.decideTask(let decide), .decision(let answer)):
            base.review = scratch.review
            upsert(task: answer.task, as: decide.taskID, children: .keep, now: now)
            if let created = answer.createdTask, let followUp = decide.followUpTaskID {
                upsert(task: created, as: followUp, children: .created(now), now: now)
            }
            guard let task = base.tasks[decide.taskID] else { return true }
            if base.review.decisions[decide.decisionID] == nil {
                // The base already reflected the decision (its answer was lost
                // before a pull), so the replay could not record it: keep it as
                // the server answered, without a local Undo snapshot.
                base.review.decisions[decide.decisionID] = ReviewDecision(
                    id: decide.decisionID, taskID: decide.taskID, type: decide.type,
                    sessionID: answer.decision.sessionID.map { ReviewSessionID($0) }, decidedAt: operation.issuedAt,
                    formulationID: decide.formulationID, stallReason: decide.stallReason,
                    substantive: answer.decision.substantive, aiUse: decide.aiUse,
                    reasonText: decide.type == .extend ? decide.reason : nil, undo: nil, taskAfter: TaskStamp(task),
                    yieldedAutoPark: answer.decision.yieldedAutoPark, snapshotOnServer: true
                )
            }
            guard var decision = base.review.decisions[decide.decisionID] else { return true }
            decision.taskAfter = TaskStamp(task)
            if let followUp = decide.followUpTaskID, let created = base.tasks[followUp] {
                decision.undo?.createdTaskAfter = TaskStamp(created)
            }
            decision.substantive = answer.decision.substantive
            decision.yieldedAutoPark = answer.decision.yieldedAutoPark
            if answer.decision.sessionID == nil { decision.sessionID = nil }
            base.review.decisions[decide.decisionID] = decision
            if let receipt = answer.receipt {
                base.review.setReceipt(
                    ReviewReceipt(
                        taskID: decide.taskID, kind: receipt.kind, reviewedAt: decision.decidedAt, hiddenUntil: receipt.hiddenUntil,
                        source: decide.type == .someday ? .release : .keep, taskRevision: receipt.taskRevision,
                        taskUpdatedAt: task.serverRevision == receipt.taskRevision ? task.updatedAt : nil,
                        decisionID: decide.decisionID
                    )
                )
            }
            if let counts = answer.sessionCounts, let session = decision.sessionID {
                base.review.sessions[session]?.counts = counts
            }
        case (.undoDecision(let id), .undoneDecision(let answer)):
            let session = base.review.decisions[id]?.sessionID
            base.review = scratch.review
            base.review.decisions[id] = nil
            upsert(task: answer.task, children: .keep, now: now)
            if let deleted = answer.deletedTaskID, let local = baseTaskID(server: deleted) { base.tasks[local] = nil }
            if let counts = answer.sessionCounts, let session { base.review.sessions[session]?.counts = counts }
        case (.undoDecision(let id), .accepted):
            // Already undone on the server (a retry whose first delivery
            // applied): the goal holds; the next pull brings the task.
            base.review = scratch.review
            base.review.decisions[id] = nil
        case (.autoParkTask(let park), .autoPark(let answer)):
            upsert(task: answer.task, as: park.taskID, children: .keep, now: now)
            if answer.applied { base.review.parkAcks.removeAll { $0.taskID == park.taskID } }
        case (.review(.acknowledgeExplainer), .reviewState(let state)):
            mergeReviewState(state, now: now)
        case (.review(.updateSettings), .reviewSettings(let settings)):
            // The replayed change holds this device's `thresholdChangedAt`.
            base.review.settings = settings.settings.keepingThresholdChange(of: scratch.review.settings)
        case (.review(.startSession(let start)), .session(let answer)):
            base.review = scratch.review
            base.review.sessions[start.sessionID] = answer.session(keeping: scratch.review.sessions[start.sessionID])
        case (.review(.progressSession(let progress)), .session(let answer)):
            let local = scratch.review.sessions[progress.sessionID]
            base.review = scratch.review
            var merged = answer.session(keeping: local)
            merged.movedOnElsewhere = progress.currentStep != nil && answer.currentStep != progress.currentStep
            base.review.sessions[progress.sessionID] = merged
        case (.review(.finishSession(let finish)), .session(let answer)):
            base.review = scratch.review
            base.review.sessions[finish.sessionID] = answer.session(keeping: scratch.review.sessions[finish.sessionID])
        case (.bulkRelease(let release), .bulkRelease(let answer)):
            base.review = scratch.review
            // The released set is the server's answer, not the replay's: a
            // replay onto a base that already shows the release finds nothing
            // eligible (an answer lost before a pull).
            let replayed = base.review.bulkReleases[release.bulkID]
            var record =
                replayed
                ?? BulkReleaseRecord(
                    id: release.bulkID, kind: release.kind, sessionID: release.sessionID, createdAt: operation.issuedAt,
                    released: [], skipped: []
                )
            let previous: OpenList = release.kind == .restart ? .next : .inbox
            record.released = answer.released.compactMap { item in
                guard let local = baseTaskID(server: item.taskID) else { return nil }
                let stamp = TaskStamp(updatedAt: nil, serverRevision: item.revisionAfter)
                if var known = replayed?.released.first(where: { $0.taskID == local }) {
                    known.taskAfter = stamp
                    return known
                }
                // This device's replay did not release it, so its Next clock is
                // still in the base (the answer carries none): the Undo needs it.
                let task = base.tasks[local]
                let clock = release.undoRetained && previous == .next && task?.state == .next
                    ? task?.formulation.map {
                        ReleasedClock(clock: $0, stalledBefore: task?.consecutiveStalledFormulations ?? 0)
                    } : nil
                return BulkReleasedTask(
                    taskID: local, previousState: previous, clockBefore: clock, taskAfter: stamp,
                    clockKnown: previous != .next || clock != nil
                )
            }
            record.skipped = answer.skipped.map { item in
                BulkSkippedTask(taskID: baseTaskID(server: item.taskID) ?? TaskID(item.taskID), reason: item.reason)
            }
            base.review.bulkReleases[release.bulkID] = record
        case (.undoBulkRelease, .bulkUndo):
            base.review = scratch.review
        case (.review, .accepted):
            base.review = scratch.review
        case (.decideTask, _), (.undoDecision, _), (.autoParkTask, _), (.bulkRelease, _), (.undoBulkRelease, _), (.review, _):
            base.review = scratch.review
        default:
            return false
        }
        return true
    }

    /// `GET /review/state` into the base (and the clock offset into `local`):
    /// settings, the counted-review facts, the open session, receipts, and
    /// which parks were seen.
    mutating func mergeReviewState(_ state: ReviewStateDTO, now: Date) {
        var review = base.review
        review.settings = state.settings.settings.keepingThresholdChange(of: heldReviewSettings())
        // An open session this build cannot read is still open: only its id is used.
        let openID = (state.openSession?.id ?? state.unreadableOpenSessionID).map { ReviewSessionID($0) }
        for session in review.sessions.values where session.status == .open && session.id != openID {
            // Finished or replaced on another device ("review ended elsewhere").
            var ended = session
            ended.status = ReviewSessionStatus.ended(by: .replace, qualifyingActivity: session.qualifyingActivity)
            ended.endedElsewhere = true
            review.sessions[session.id] = ended
        }
        if let open = state.openSession, let id = openID {
            review.sessions[id] = open.session(keeping: review.sessions[id])
        }
        review.server = ReviewServerFacts(
            exposed: true, lastCountedReviewAt: state.lastCountedReviewAt,
            lastCountedReview: state.lastCountedReview.map {
                LastCountedReview(
                    sessionID: ReviewSessionID($0.sessionID), status: $0.status, origin: $0.origin, endedAt: $0.endedAt,
                    counts: $0.counts, clearStart: $0.clearStart
                )
            },
            nextReviewAt: state.nextReviewAt, restartMode: state.restartMode, openSessionID: openID, pulledAt: now
        )
        review.receipts = state.receipts.compactMap { receipt in
            guard let id = baseTaskID(server: receipt.taskID), let task = base.tasks[id] else { return nil }
            return ReviewReceipt(
                taskID: id, kind: receipt.kind, reviewedAt: review.receipt(for: id, kind: receipt.kind)?.reviewedAt ?? now,
                hiddenUntil: receipt.hiddenUntil, source: review.receipt(for: id, kind: receipt.kind)?.source ?? .keep,
                taskRevision: receipt.taskRevision,
                taskUpdatedAt: task.serverRevision == receipt.taskRevision ? task.updatedAt : nil
            )
        }
        let unseen = Set(state.unseenParks.map { "\($0.taskID)|\($0.formulationID)" })
        review.parkAcks = base.tasks.values.compactMap { task in
            guard task.state == .someday, let marker = task.parked, let serverID = task.serverID,
                !unseen.contains("\(serverID)|\(marker.formulationID.rawValue)")
            else { return nil }
            return ParkAck(taskID: task.id, formulationID: marker.formulationID, parkedAt: marker.at)
        }
        base.review = review
        local.serverClockOffset = state.serverNow.timeIntervalSince(now)
    }

    /// The review settings the device shows: the base's with the queued
    /// settings changes applied (a change whose answer was lost may already
    /// be on the server while it is still queued here).
    func heldReviewSettings() -> ReviewSettings {
        var scratch = GTDState(review: base.review)
        for operation in outbox {
            guard case .review(.updateSettings) = operation.command else { continue }
            _ = try? GTDReducer.apply(operation.command, at: operation.issuedAt, to: &scratch, mode: .replay)
        }
        return scratch.review.settings
    }

    /// A gated read answered `404 weekly_review_disabled` (or a server without
    /// the review): hide the review, keep its state.
    mutating func markReviewNotExposed(now: Date) {
        var facts = base.review.server ?? ReviewServerFacts(exposed: false)
        facts.exposed = false
        facts.pulledAt = now
        base.review.server = facts
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
        // The review state is pulled on its own (`mergeReviewState`).
        var new = GTDState(review: old.review)
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
            new.projects[id] = ProjectRecord(dto, id: id, createdAt: existing?.createdAt ?? now)
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
            if command.bodyRevisions(in: old) != command.bodyRevisions(in: base) { outbox[index].rotateKey() }
        }
    }

    /// Recomputes the outbox against the base: satisfied operations drop out,
    /// merged creates rewrite later references, and rejected operations
    /// become sync issues.
    mutating func replayOutbox(now: Date) {
        let result = OutboxReplayer.replay(outbox, onto: base, activatedAt: local.activatedAt)
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

extension ProjectRecord {
    /// A base project from a server project, under the client id the device uses.
    init(_ dto: ProjectDTO, id: ProjectID, createdAt: Date) {
        self.init(
            id: id, serverID: dto.id, serverRevision: dto.revision, name: dto.name, color: dto.color, state: dto.state,
            createdAt: createdAt, desiredOutcome: dto.desiredOutcome, archivedAt: dto.archivedAt,
            archivedBeforeLossless: dto.archivedBeforeLossless
        )
    }
}
