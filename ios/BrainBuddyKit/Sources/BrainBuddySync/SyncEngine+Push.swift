import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyPersistence
import Foundation

/// What a push changed.
struct PushSummary: Sendable {
    /// Something was acknowledged, set aside or adopted.
    var changed = false
    /// An acknowledged archive or tag delete changed other records on the server.
    var needsPull = false
}

extension SyncEngine {
    /// Sends the outbox front to back, one request per operation, until it
    /// is empty. Throws the `APIError` that blocks it (network, 5xx, 429,
    /// 401), leaving that operation and its key in place.
    func pushOutbox(_ context: CycleContext) async throws -> PushSummary {
        var summary = PushSummary()
        var conflicts: [UUID: Int] = [:]
        while true {
            try checkActive(context)
            let document = try await loadDocument()
            guard let operation = document.outbox.first else { return summary }
            if isUncertainAndOld(operation) {
                try await resolveUncertainCreate(operation, context)
                summary.changed = true
                continue
            }
            let planned: PlannedRequest
            do {
                planned = try PushPlanner.plan(operation.command, base: document.base)
            } catch {
                try await setAside(operation, message: error.message, referenceID: nil, context)
                summary.changed = true
                continue
            }
            guard let sending = try await recordAttempt(operation, context) else { continue }
            let record: ServerRecord
            do {
                record = try await planned.send(with: context.client, key: sending.idempotencyKey)
            } catch {
                try checkActive(context)
                conflicts[operation.id, default: 0] += 1
                try await handleFailure(error, of: sending, rounds: conflicts[operation.id] ?? 1, context, &summary)
                continue
            }
            try await acknowledge(sending, with: record, context)
            summary.changed = true
            if operation.command.changesOtherRecords { summary.needsPull = true }
        }
    }

    /// A sent create whose first attempt is so old that the server may have
    /// forgotten its key.
    private func isUncertainAndOld(_ operation: PendingOperation) -> Bool {
        guard operation.hasBeenSent, operation.command.isCreate, let first = operation.firstAttemptAt else { return false }
        return now().timeIntervalSince(first) > configuration.uncertainCreateAge
    }

    /// Marks the attempt before sending, so a crash leaves the operation
    /// "maybe sent" and the compactor never folds into it. Nil when the
    /// operation changed meanwhile (it is planned again).
    private func recordAttempt(_ operation: PendingOperation, _ context: CycleContext) async throws -> PendingOperation? {
        let date = now()
        do {
            let document = try await update(context) { doc in
                guard let first = doc.outbox.first, first.id == operation.id, first.command == operation.command,
                    first.idempotencyKey == operation.idempotencyKey
                else { throw OperationChanged() }
                doc.outbox[0].attempts += 1
                if doc.outbox[0].firstAttemptAt == nil { doc.outbox[0].firstAttemptAt = date }
                doc.outbox[0].lastAttemptAt = date
            }
            return document.outbox.first
        } catch is OperationChanged {
            return nil
        }
    }

    /// 2xx: the answer goes into the base under the command's ids, the
    /// operation leaves the outbox, and the rest is replayed on the new base.
    private func acknowledge(_ operation: PendingOperation, with record: ServerRecord, _ context: CycleContext) async throws {
        var references = FetchedReferences()
        if case .task(let task) = record { references = try await fetchUnknownReferences(of: [task], context) }
        let date = now()
        let written = try await update(context) { [references] doc in
            references.write(into: &doc, now: date)
            let old = doc.base
            doc.apply(record, answering: operation.command, now: date)
            doc.outbox.removeAll { $0.id == operation.id }
            doc.sync.lastPushAt = date
            doc.sync.lastFailure = nil
            doc.rotateKeys(comparedTo: old)
            doc.replayOutbox(now: date)
        }
        lastSyncedAt = written.lastSyncedAt
    }

    /// Everything but success.
    private func handleFailure(
        _ error: APIError, of operation: PendingOperation, rounds: Int, _ context: CycleContext,
        _ summary: inout PushSummary
    ) async throws {
        switch error.kind {
        case .unauthorized:
            throw error
        case .network, .cancelled, .tokenStorage, .rateLimited, .server:
            // The outcome may be unknown: keep the operation and its key.
            try? await noteFailure(error, of: operation, context)
            throw error
        case .staleRevision where rounds <= 3:
            summary.needsPull = try await refetch(after: operation, context) || summary.needsPull
            summary.changed = true
        case .duplicateName where rounds <= 2 && operation.command.isNamedCreate:
            try await adoptExisting(for: operation, error, context)
            summary.changed = true
        case .decoding where error.isUncertainOutcome:
            // A 2xx we cannot read: applied, but unusable. Keep the key and try later.
            try? await noteFailure(error, of: operation, context)
            throw error
        default:
            // 400, 404, 422, idempotency conflicts, and conflicts that keep coming back.
            try await setAside(operation, message: error.message, referenceID: error.referenceID, context)
            try await pull(context)
            summary.changed = true
        }
    }

    private func noteFailure(_ error: APIError, of operation: PendingOperation, _ context: CycleContext) async throws {
        try await update(context) { doc in
            guard let index = doc.outbox.firstIndex(where: { $0.id == operation.id }),
                doc.outbox[index].idempotencyKey == operation.idempotencyKey
            else { throw OperationChanged() }
            doc.outbox[index].lastError = error.message
        }
    }

    /// Moves the operation to sync issues and replays, so operations that
    /// depended on it are set aside with it.
    func setAside(
        _ operation: PendingOperation, message: String, referenceID: String?, _ context: CycleContext
    ) async throws {
        let date = now()
        try await update(context) { doc in
            guard let index = doc.outbox.firstIndex(where: { $0.id == operation.id }) else { return }
            let removed = doc.outbox.remove(at: index)
            doc.issues.append(
                SyncIssue(command: removed.command, message: message, referenceID: referenceID, occurredAt: date)
            )
            doc.replayOutbox(now: date)
        }
    }

    /// 409 stale revision: re-read the record into the base, replay (an
    /// operation whose goal now holds drops out), and give a surviving
    /// operation a new key, since its `expected_revision` changes. Returns
    /// whether a pull should follow (the record was archived or deleted).
    private func refetch(after operation: PendingOperation, _ context: CycleContext) async throws -> Bool {
        let base = try await loadDocument().base
        let date = now()
        switch operation.command.conflictTarget {
        case .task(let id)?:
            guard let serverID = base.tasks[id]?.serverID else { break }
            let task: TaskDTO
            do {
                task = try await context.client.getTask(id: serverID)
            } catch {
                return try await gone(operation, error, context)
            }
            let references = try await fetchUnknownReferences(of: [task], context)
            try await update(context) { doc in
                references.write(into: &doc, now: date)
                let old = doc.base
                doc.upsert(task: task, children: .replace(date), now: date)
                Self.renewKey(of: operation, in: &doc)
                doc.rotateKeys(comparedTo: old)
                doc.replayOutbox(now: date)
            }
            return false
        case .project(let id)?:
            guard let serverID = base.projects[id]?.serverID else { break }
            let project: ProjectDTO
            do {
                project = try await context.client.getProject(id: serverID)
            } catch {
                return try await gone(operation, error, context)
            }
            try await update(context) { doc in
                let old = doc.base
                doc.upsert(project: project, now: date)
                Self.renewKey(of: operation, in: &doc)
                doc.rotateKeys(comparedTo: old)
                doc.replayOutbox(now: date)
            }
            return project.state == .archived
        case .tag(let id)?:
            guard let serverID = base.tags[id]?.serverID else { break }
            let tag: TagDTO
            do {
                tag = try await context.client.getTag(id: serverID)
            } catch {
                return try await gone(operation, error, context)
            }
            try await update(context) { doc in
                let old = doc.base
                doc.upsert(tag: tag, now: date)
                Self.renewKey(of: operation, in: &doc)
                doc.rotateKeys(comparedTo: old)
                doc.replayOutbox(now: date)
            }
            return tag.state == .deleted
        case nil:
            break
        }
        try await setAside(operation, message: "This change conflicts with the server.", referenceID: nil, context)
        return true
    }

    /// The record a conflict was about could not be read again: a 404 sets
    /// the operation aside (and pulls); anything else stops the push.
    private func gone(_ operation: PendingOperation, _ error: APIError, _ context: CycleContext) async throws -> Bool {
        guard case .notFound = error.kind else { throw error }
        try await setAside(operation, message: error.message, referenceID: error.referenceID, context)
        try await pull(context)
        return false
    }

    private static func renewKey(of operation: PendingOperation, in doc: inout StoreDocument) {
        guard let index = doc.outbox.firstIndex(where: { $0.id == operation.id }) else { return }
        doc.outbox[index].rotateKey()
    }

    /// 409 duplicate name on a project or tag create: the server already has
    /// an active record with this name (made elsewhere since the last pull).
    /// Adopt it: it enters the base, the outbox is rewritten from the local
    /// id to it, and the create is dropped.
    private func adoptExisting(for operation: PendingOperation, _ error: APIError, _ context: CycleContext) async throws {
        let date = now()
        switch operation.command {
        case .createProject(let create):
            let key = NameNormalizer.project(create.name)
            let projects = try await context.client.listProjects()
            if let match = projects.first(where: { NameNormalizer.project($0.name) == key }) {
                try await update(context) { doc in
                    guard doc.outbox.contains(where: { $0.id == operation.id }) else { return }
                    let survivor = doc.upsert(project: match, now: date)
                    doc.outbox.removeAll { $0.id == operation.id }
                    for index in doc.outbox.indices {
                        doc.outbox[index].command = doc.outbox[index].command.replacing(
                            project: create.projectID, with: survivor
                        )
                    }
                    doc.replayOutbox(now: date)
                }
                return
            }
        case .createTag(let create):
            let key = NameNormalizer.tag(NameNormalizer.tagDisplay(create.name))
            let tags = try await context.client.listTags()
            if let match = tags.first(where: { NameNormalizer.tag($0.name) == key }) {
                try await update(context) { doc in
                    guard doc.outbox.contains(where: { $0.id == operation.id }) else { return }
                    let survivor = doc.upsert(tag: match, now: date)
                    doc.outbox.removeAll { $0.id == operation.id }
                    for index in doc.outbox.indices {
                        doc.outbox[index].command = doc.outbox[index].command.replacing(tag: create.tagID, with: survivor)
                    }
                    doc.replayOutbox(now: date)
                }
                return
            }
        default:
            break
        }
        // Not in the active list (a race): a pull lets the replay merge it, or
        // the create goes out again with a fresh key.
        try await pull(context)
        try await update(context) { doc in
            guard let index = doc.outbox.firstIndex(where: { $0.id == operation.id }) else { return }
            doc.outbox[index].rotateKey()
        }
    }
}

/// The operation changed between planning and writing; plan it again.
struct OperationChanged: Error {}

extension GTDCommand {
    /// Creates that answer 409 when the normalized name is taken.
    var isNamedCreate: Bool {
        switch self {
        case .createProject, .createTag: true
        default: false
        }
    }
}
