import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyPersistence
import Foundation

/// Projects and tags a task references that the base does not know yet
/// (created elsewhere), fetched before the task is written.
struct FetchedReferences: Sendable {
    var projects: [ProjectDTO] = []
    var tags: [TagDTO] = []

    func write(into document: inout StoreDocument, now: Date) {
        for project in projects { document.upsert(project: project, now: now) }
        for tag in tags { document.upsert(tag: tag, now: now) }
    }
}

extension SyncEngine {
    // MARK: - Pull

    /// A full pull (there is no delta endpoint): every task in every state,
    /// every project (`?state=all`), the active tags, and the deleted tags that
    /// tasks reference or the base knows. A server that ignores `state` lists
    /// the active projects only, and the archived ones that tasks reference or
    /// the base knows are fetched by id as before. The new base replaces the
    /// old one under the same client ids, then the outbox is replayed on it.
    func pull(_ context: CycleContext) async throws {
        let client = context.client
        let tasks = try await client.listAllTasks(.fullPull)
        var projects = try await client.listProjects(state: .all)
        var tags = try await client.listTags()
        let known = try await loadDocument().base
        let listedProjects = Set(projects.map(\.id))
        let activeTags = Set(tags.map(\.id))
        let missingProjects = Set(tasks.compactMap(\.projectID)).union(known.projects.values.compactMap(\.serverID))
            .subtracting(listedProjects)
        let missingTags = Set(tasks.flatMap(\.tagIDs)).union(known.tags.values.compactMap(\.serverID))
            .subtracting(activeTags)
        for id in missingProjects.sorted() {
            do { projects.append(try await client.getProject(id: id)) } catch { try Self.ignoreNotFound(error) }
        }
        for id in missingTags.sorted() {
            do { tags.append(try await client.getTag(id: id)) } catch { try Self.ignoreNotFound(error) }
        }
        let review = try await pullReviewState(client)
        let date = now()
        let written = try await update(context) { [projects, tags] doc in
            let old = doc.base
            doc.base = StoreDocument.pulledBase(from: old, tasks: tasks, projects: projects, tags: tags, now: date)
            switch review {
            case .state(let state): doc.mergeReviewState(state, now: date)
            case .notExposed: doc.markReviewNotExposed(now: date)
            case .unavailable: break
            }
            doc.rotateKeys(comparedTo: old)
            doc.replayOutbox(now: date)
            doc.sync.lastPullAt = date
            doc.sync.lastFailure = nil
        }
        lastSyncedAt = written.lastSyncedAt
    }

    enum ReviewPull: Sendable {
        case state(ReviewStateDTO)
        /// `404 weekly_review_disabled`, or a server without the review.
        case notExposed
        /// A server-side failure: the review state stays as it was.
        case unavailable
    }

    /// `GET /review/state` after the task pull (spec 020, R16). Only the
    /// network and the session stop the pull; the review being switched off
    /// hides it while its local state is kept.
    func pullReviewState(_ client: BrainBuddyAPIClient) async throws -> ReviewPull {
        do {
            return .state(try await client.reviewState())
        } catch {
            switch error.kind {
            case .featureDisabled, .notFound: return .notExposed
            case .network, .cancelled, .unauthorized, .tokenStorage: throw error
            case .rateLimited, .staleRevision, .idempotencyConflict, .duplicateName, .rejected, .server, .decoding:
                return .unavailable
            }
        }
    }

    static func ignoreNotFound(_ error: APIError) throws(APIError) {
        guard case .notFound = error.kind else { throw error }
    }

    /// GETs the projects and tags `tasks` reference that the base does not
    /// know (a 404 leaves the reference out).
    func fetchUnknownReferences(of tasks: [TaskDTO], _ context: CycleContext) async throws -> FetchedReferences {
        let base = try await loadDocument().base
        let knownProjects = Set(base.projects.values.compactMap(\.serverID))
        let knownTags = Set(base.tags.values.compactMap(\.serverID))
        var references = FetchedReferences()
        for id in Set(tasks.compactMap(\.projectID)).subtracting(knownProjects).sorted() {
            do { references.projects.append(try await context.client.getProject(id: id)) } catch { try Self.ignoreNotFound(error) }
        }
        for id in Set(tasks.flatMap(\.tagIDs)).subtracting(knownTags).sorted() {
            do { references.tags.append(try await context.client.getTag(id: id)) } catch { try Self.ignoreNotFound(error) }
        }
        return references
    }

    // MARK: - Hydration

    /// Loads subtasks and comments for open tasks never hydrated or changed
    /// since (`childrenSyncedAt == nil`), newest first, within the budget.
    /// Ties go by server id: a pulled task's client id is random per device.
    /// Only a 401 fails the cycle; other failures wait for the next cycle.
    func hydrateChangedTasks(_ context: CycleContext) async throws {
        guard configuration.hydrationBudget > 0 else { return }
        let base = try await loadDocument().base
        let candidates = base.tasks.values
            .filter { $0.isOpen && $0.childrenSyncedAt == nil && $0.serverID != nil }
            .sorted { ($0.updatedAt, $0.serverID ?? "") > ($1.updatedAt, $1.serverID ?? "") }
            .prefix(configuration.hydrationBudget)
            .compactMap(\.serverID)
        do {
            try await hydrate(Array(candidates), context)
        } catch let error as APIError {
            if case .unauthorized = error.kind { throw error }
        }
    }

    /// The details `refreshTask` asked for, read in the single-flight slot.
    /// Only a 401 is reported; otherwise the detail shows what the device has.
    func hydrateRequestedTasks(epoch cycleEpoch: Int) async {
        let ids = requestedRefreshes
        requestedRefreshes.removeAll()
        guard let account, !ids.isEmpty else { return }
        let context = CycleContext(account: account, client: client(for: account.serverURL), epoch: cycleEpoch)
        do {
            let base = try await loadDocument().base
            try await hydrate(ids.compactMap { base.tasks[$0]?.serverID }, context)
        } catch let error as APIError {
            if case .unauthorized = error.kind, context.epoch == epoch {
                needsSignIn = true
                await setStatus(.needsSignIn)
            }
        } catch {
            // Offline, aborted or unreadable: the detail shows what the device has.
        }
    }

    /// `GET /tasks/{id}` for each server id, at most
    /// `hydrationConcurrency` at a time; each batch is written as it lands.
    /// Children the base learned while a read was out are kept (see
    /// `ChildrenUpdate.replace`).
    func hydrate(_ serverIDs: [String], _ context: CycleContext) async throws {
        let client = context.client
        var start = 0
        while start < serverIDs.count {
            try checkActive(context)
            let batch = serverIDs[start..<min(start + configuration.hydrationConcurrency, serverIDs.count)]
            start += batch.count
            let known = KnownChildren.snapshot(of: batch, in: try await loadDocument().base)
            let results = await withTaskGroup(of: Result<TaskDTO, APIError>.self) { group in
                for id in batch {
                    group.addTask {
                        do throws(APIError) {
                            return .success(try await client.getTask(id: id))
                        } catch {
                            return .failure(error)
                        }
                    }
                }
                var results: [Result<TaskDTO, APIError>] = []
                for await result in group { results.append(result) }
                return results
            }
            var details: [TaskDTO] = []
            var failure: APIError?
            for result in results {
                switch result {
                case .success(let task): details.append(task)
                case .failure(let error):
                    if case .notFound = error.kind { continue }
                    if case .unauthorized = error.kind { failure = error } else if failure == nil { failure = error }
                }
            }
            if !details.isEmpty {
                let references = try await fetchUnknownReferences(of: details, context)
                let date = now()
                try await update(context) { [details] doc in
                    references.write(into: &doc, now: date)
                    let old = doc.base
                    for task in details.sorted(by: { $0.id < $1.id }) {
                        let children = ChildrenUpdate.replace(date, known: known[task.id] ?? KnownChildren(nil))
                        doc.upsert(task: task, children: children, now: date)
                    }
                    doc.rotateKeys(comparedTo: old)
                    doc.replayOutbox(now: date)
                }
            }
            if let failure { throw failure }
        }
    }

    // MARK: - Uncertain creates

    /// A create sent more than `uncertainCreateAge` ago without a usable
    /// answer: its key may be gone from the server, so resending could
    /// duplicate it. Look for the record the first attempt may have made
    /// (same title and list, created at or after the attempt, new to this
    /// device) and adopt it; otherwise resend under a new key.
    func resolveUncertainCreate(_ operation: PendingOperation, _ context: CycleContext) async throws {
        let date = now()
        let since = (operation.firstAttemptAt ?? date).addingTimeInterval(-configuration.clockSkewTolerance)
        switch operation.command {
        case .createTask(let create):
            let before = Set(try await loadDocument().base.tasks.values.compactMap(\.serverID))
            try await pull(context)
            let title = NameNormalizer.stripped(create.title)
            try await update(context) { doc in
                guard let index = doc.outbox.firstIndex(where: { $0.id == operation.id }) else { return }
                let referenced = Set(doc.outbox.compactMap(\.command.taskID))
                let match = doc.base.tasks.values.filter { task in
                    guard let serverID = task.serverID, !before.contains(serverID), !referenced.contains(task.id) else {
                        return false
                    }
                    return task.title == title && task.state == create.list.taskState && task.createdAt >= since
                }.min { ($0.createdAt, $0.id) < ($1.createdAt, $1.id) }
                if let match {
                    doc.outbox.remove(at: index)
                    doc.rekey(task: match.id, to: create.taskID)
                } else {
                    doc.outbox[index].rotateKey()
                }
                doc.replayOutbox(now: date)
            }
            return
        case .createSubtask(let create):
            let base = try await loadDocument().base
            guard let parent = base.tasks[create.taskID], let serverID = parent.serverID else { break }
            let known = KnownChildren(parent)
            let detail: TaskDTO
            do { detail = try await context.client.getTask(id: serverID) } catch {
                try Self.ignoreNotFound(error)
                break
            }
            let title = NameNormalizer.stripped(create.title)
            try await update(context) { doc in
                // Candidates are the detail's subtasks this device doesn't
                // hold as it is written, not as it was before the read.
                let held = KnownChildren(doc.base.tasks[create.taskID]).subtasks
                doc.upsert(task: detail, children: .replace(date, known: known), now: date)
                guard let index = doc.outbox.firstIndex(where: { $0.id == operation.id }) else { return }
                // The server numbers subtasks in creation order, so one the
                // first attempt made comes after every same-titled subtask
                // that existed before it (which a stale base may not hold).
                let match = detail.subtasks.last { !held.contains($0.id) && $0.title == title && $0.state == .open }
                if let match {
                    doc.outbox.remove(at: index)
                    doc.upsert(subtask: match, in: create.taskID, as: create.subtaskID)
                } else {
                    doc.outbox[index].rotateKey()
                }
                doc.replayOutbox(now: date)
            }
            return
        case .createComment(let create):
            let base = try await loadDocument().base
            guard let parent = base.tasks[create.taskID], let serverID = parent.serverID else { break }
            let known = KnownChildren(parent)
            let detail: TaskDTO
            do { detail = try await context.client.getTask(id: serverID) } catch {
                try Self.ignoreNotFound(error)
                break
            }
            let author = context.account.id
            try await update(context) { doc in
                let held = KnownChildren(doc.base.tasks[create.taskID]).comments
                doc.upsert(task: detail, children: .replace(date, known: known), now: date)
                guard let index = doc.outbox.firstIndex(where: { $0.id == operation.id }) else { return }
                let match = detail.comments.first {
                    !held.contains($0.id) && $0.body == create.body && $0.actorID == author && $0.createdAt >= since
                }
                if let match {
                    doc.outbox.remove(at: index)
                    doc.upsert(comment: match, in: create.taskID, as: create.commentID)
                } else {
                    doc.outbox[index].rotateKey()
                }
                doc.replayOutbox(now: date)
            }
            return
        default:
            // Projects and tags: after a pull the replay merges a create into
            // an active record with the same name; otherwise it is resent.
            try await pull(context)
        }
        try await update(context) { doc in
            guard let index = doc.outbox.firstIndex(where: { $0.id == operation.id }) else { return }
            if doc.outbox[index].hasBeenSent { doc.outbox[index].rotateKey() }
        }
    }
}
