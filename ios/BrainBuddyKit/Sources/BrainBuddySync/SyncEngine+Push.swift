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
                // A request that never left the device starts no 23-hour clock.
                let takeBackClock = operation.firstAttemptAt == nil && !error.requestMayHaveBeenSent
                try await handleFailure(
                    error, of: sending, rounds: conflicts[operation.id] ?? 1, clearingClock: takeBackClock, context,
                    &summary
                )
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
    /// "maybe sent" and the compactor never folds into it; a request that
    /// provably never left the device takes back `firstAttemptAt` (see
    /// `noteFailure`). Nil when the operation changed meanwhile (it is
    /// planned again).
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
    ///
    /// When the queued operation no longer is what was sent (a document
    /// written before `everSent` existed may have folded a later edit into
    /// it while the request was in flight), what was not sent stays queued,
    /// as new operations, instead of being dropped with it.
    private func acknowledge(_ operation: PendingOperation, with record: ServerRecord, _ context: CycleContext) async throws {
        var references = FetchedReferences()
        if case .task(let task) = record { references = try await fetchUnknownReferences(of: [task], context) }
        let date = now()
        let written = try await update(context) { [references] doc in
            references.write(into: &doc, now: date)
            if let index = doc.outbox.firstIndex(where: { $0.id == operation.id }) {
                let queued = doc.outbox[index]
                let remainder = queued.command.remainder(afterSending: operation.command).map {
                    PendingOperation(command: $0, issuedAt: queued.issuedAt)
                }
                doc.outbox.replaceSubrange(index...index, with: remainder)
            }
            let old = doc.base
            doc.apply(record, answering: operation.command, now: date)
            doc.sync.lastPushAt = date
            doc.sync.lastFailure = nil
            doc.rotateKeys(comparedTo: old)
            doc.replayOutbox(now: date)
        }
        rejectionStreak = nil
        lastSyncedAt = written.lastSyncedAt
    }

    /// Everything but success.
    private func handleFailure(
        _ error: APIError, of operation: PendingOperation, rounds: Int, clearingClock: Bool, _ context: CycleContext,
        _ summary: inout PushSummary
    ) async throws {
        switch error.kind {
        case .unauthorized:
            throw error
        case .network, .cancelled, .tokenStorage, .rateLimited:
            // The outcome may be unknown: keep the operation and its key.
            try? await noteFailure(error, of: operation, clearingClock: clearingClock, context)
            throw error
        case .server:
            // Unknown outcome too, unless the server keeps failing this one.
            try? await noteFailure(error, of: operation, clearingClock: clearingClock, context)
            guard try await setAsideIfServerKeepsFailing(operation, error, context) else { throw error }
            summary.changed = true
        case .staleRevision where rounds <= 3:
            summary.needsPull = try await refetch(after: operation, context) || summary.needsPull
            summary.changed = true
        case .duplicateName where rounds <= 2 && operation.command.isNamedCreate:
            try await adoptExisting(for: operation, error, context)
            summary.changed = true
        case .decoding where error.isUncertainOutcome:
            // A 2xx we cannot read: applied, but unusable. Keep the key and try later.
            try? await noteFailure(error, of: operation, clearingClock: clearingClock, context)
            guard try await setAsideIfServerKeepsFailing(operation, error, context) else { throw error }
            summary.changed = true
        default:
            // 400, 404, 422, idempotency conflicts, and conflicts that keep coming back.
            try await setAside(operation, message: error.message, referenceID: error.referenceID, context)
            try await pull(context)
            summary.changed = true
        }
    }

    /// Keeps the failure's words on the operation. `clearingClock`: the
    /// request never left the device, so the uncertainty clock this attempt
    /// started is taken back.
    private func noteFailure(
        _ error: APIError, of operation: PendingOperation, clearingClock: Bool, _ context: CycleContext
    ) async throws {
        try await update(context) { doc in
            guard let index = doc.outbox.firstIndex(where: { $0.id == operation.id }),
                doc.outbox[index].idempotencyKey == operation.idempotencyKey
            else { throw OperationChanged() }
            doc.outbox[index].lastError = error.message
            if clearingClock, doc.outbox[index].firstAttemptAt == operation.firstAttemptAt {
                doc.outbox[index].firstAttemptAt = nil
            }
        }
    }

    static let keptRejectingMessage = "The server kept rejecting this change."

    /// Counts a server-side failure of the operation at the front. After
    /// `rejectionLimit` in a row, or at least two in a row once it has been
    /// failing for `rejectionAge`, it is set aside as a sync issue so the
    /// operations behind it go out. Returns whether it was.
    private func setAsideIfServerKeepsFailing(
        _ operation: PendingOperation, _ error: APIError, _ context: CycleContext
    ) async throws -> Bool {
        let date = now()
        var streak =
            rejectionStreak.flatMap { $0.operationID == operation.id ? $0 : nil }
            ?? RejectionStreak(operationID: operation.id, count: 0, since: operation.firstAttemptAt ?? date)
        streak.count += 1
        rejectionStreak = streak
        let failingFor = date.timeIntervalSince(streak.since)
        guard streak.count >= configuration.rejectionLimit || (streak.count >= 2 && failingFor >= configuration.rejectionAge)
        else { return false }
        rejectionStreak = nil
        try await setAside(operation, message: Self.keptRejectingMessage, referenceID: error.referenceID, context)
        return true
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
            let known = KnownChildren(base.tasks[id])
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
                doc.upsert(task: task, children: .replace(date, known: known), now: date)
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
                    doc.outbox = Self.rewritingOutbox(doc.outbox, adopting: .project(create.projectID, into: survivor))
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
                    doc.outbox = Self.rewritingOutbox(doc.outbox, adopting: .tag(create.tagID, into: survivor))
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

    /// A local project or tag create that a 409 merged into the server's record.
    enum Adoption {
        case project(ProjectID, into: ProjectID)
        case tag(TagID, into: TagID)
    }

    // TODO(merge-helper): switch the body to Core's OutboxReplayer.rewritingAfterMerge(_:project:into:)
    // / rewritingAfterMerge(_:tag:into:) once it lands; that no longer retargets archiveProject,
    // deleteTag or renames at the adopted record. Until then this keeps the old behaviour.
    /// The queued operations after an adoption: every reference to the local
    /// record now names the adopted one. The only place the adoption path
    /// rewrites the outbox.
    private static func rewritingOutbox(_ outbox: [PendingOperation], adopting adoption: Adoption) -> [PendingOperation] {
        outbox.map { operation in
            var operation = operation
            switch adoption {
            case .project(let local, let survivor):
                operation.command = operation.command.replacing(project: local, with: survivor)
            case .tag(let local, let survivor):
                operation.command = operation.command.replacing(tag: local, with: survivor)
            }
            return operation
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
