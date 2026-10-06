import Foundation

public struct RejectedOperation: Hashable, Sendable {
    public var operation: PendingOperation
    public var error: GTDValidationError
    public init(operation: PendingOperation, error: GTDValidationError) {
        self.operation = operation
        self.error = error
    }
}

public struct ReplayResult: Hashable, Sendable {
    /// What the UI shows.
    public var state: GTDState
    /// The operations still to send. Satisfied and rejected ones are removed;
    /// an unsent task creation or edit is queued as it was applied
    /// (`GTDReducer.replayable(_:in:)`); the operations after a merged project
    /// or tag creation are rewritten (`OutboxReplayer.rewritingAfterMerge`).
    public var outbox: [PendingOperation]
    public var rejected: [RejectedOperation]

    public init(state: GTDState, outbox: [PendingOperation], rejected: [RejectedOperation]) {
        self.state = state
        self.outbox = outbox
        self.rejected = rejected
    }
}

public enum OutboxReplayer {
    /// Applies `outbox` in order onto `base` with `ApplyMode.replay`, each
    /// operation at its own `issuedAt`, so the result is deterministic.
    ///
    /// - An operation whose goal already holds is dropped.
    /// - A task creation or edit keeps whatever part of it still applies
    ///   (`GTDReducer.replayable(_:in:)`): a project archived or a tag deleted
    ///   elsewhere is dropped from it, not the task. An unsent operation is
    ///   queued in that form, so the server receives what was applied; a sent
    ///   one keeps the body its idempotency key is bound to.
    /// - A project or tag creation whose name an active record already has is
    ///   dropped, and the operations after it are rewritten with
    ///   `rewritingAfterMerge`: references follow the existing record, but a
    ///   rename, recolour, archive or delete of the local record does not.
    /// - An operation the reducer rejects is dropped into `rejected`; later
    ///   operations that depend on it are rejected in turn (a subtask of a
    ///   task that was never created) or lose the reference (a task keeps its
    ///   place without a project that was never created).
    ///
    /// After the last operation the post-replay activation step runs
    /// (`ReviewActivation`, spec 020): keyed on the activation instant the
    /// state holds, or `activatedAt` (the account-less anchor) when it holds
    /// none, so the same inputs always give the same clocks.
    public static func replay(
        _ outbox: [PendingOperation], onto base: GTDState, activatedAt fallback: Date? = nil
    ) -> ReplayResult {
        var result = replayOperations(outbox, onto: base)
        ReviewActivation.apply(
            to: &result.state, activatedAt: result.state.review.settings.activatedAt ?? fallback,
            startsMissingClocks: result.state.review.server == nil
        )
        return result
    }

    private static func replayOperations(_ outbox: [PendingOperation], onto base: GTDState) -> ReplayResult {
        var state = base
        var pending = outbox
        var kept: [PendingOperation] = []
        var rejected: [RejectedOperation] = []
        /// Decisions the replay could not apply, kept for the server to answer.
        var unapplied = Set<DecisionID>()
        kept.reserveCapacity(pending.count)
        var index = pending.startIndex
        while index < pending.endIndex {
            let operation = pending[index]
            index += 1
            let command = GTDReducer.replayable(operation.command, in: state)
            if case .undoDecision(let id) = command, unapplied.contains(id) {
                // Its decision waits for the server's answer; so does the Undo.
                kept.append(operation)
                continue
            }
            let outcome: ApplyOutcome
            do throws(GTDValidationError) {
                outcome = try GTDReducer.apply(command, at: operation.issuedAt, to: &state, mode: .replay)
            } catch {
                if case .decideTask(let decide) = operation.command {
                    unapplied.insert(decide.decisionID)
                    // Spec 020: a decision is never refused by the replay. It
                    // may already be applied (an answer lost before a pull) or
                    // yield to a park; the server answers it under the same
                    // decision id (matching record, yield rule), and a real
                    // conflict comes back as 409 with the "It's in <list> now"
                    // copy and its Ref (ios-commands §4).
                    kept.append(operation)
                    continue
                }
                rejected.append(RejectedOperation(operation: operation, error: error))
                continue
            }
            switch outcome {
            case .applied:
                var applied = operation
                if !operation.hasBeenSent { applied.command = command }
                kept.append(applied)
            case .alreadySatisfied:
                break
            case .mergedProject(into: let survivor):
                guard case .createProject(let create) = command else { break }
                let rest = rewritingAfterMerge(Array(pending[index...]), project: create.projectID, into: survivor)
                pending.replaceSubrange(index..., with: rest)
            case .mergedTag(into: let survivor):
                guard case .createTag(let create) = command else { break }
                let rest = rewritingAfterMerge(Array(pending[index...]), tag: create.tagID, into: survivor)
                pending.replaceSubrange(index..., with: rest)
            }
        }
        return ReplayResult(state: state, outbox: kept, rejected: rejected)
    }

    // MARK: - Merges

    /// `outbox` after the local project `old` was merged into the existing
    /// project `new` because their names collide: by replay, or by sync when
    /// the server answers `old`'s creation with 409 duplicate name.
    ///
    /// Only references follow the merge: a task created in or moved to `old`
    /// is created in or moved to `new`. What the user did to their own record
    /// does not, because `new` is the account's project, which other devices
    /// use: a rename or recolour of `old` is dropped (`new` keeps its name and
    /// colour), and so is an archive of `old`. When `outbox` archives `old`,
    /// its tasks lose the reference instead of following it, as the local
    /// archive left them (`withdrawing(project:from:)`).
    ///
    /// The merged creation itself is dropped too if it is still in `outbox`.
    /// Operation ids, keys and bookkeeping are kept.
    public static func rewritingAfterMerge(
        _ outbox: [PendingOperation], project old: ProjectID, into new: ProjectID
    ) -> [PendingOperation] {
        if outbox.contains(where: { $0.command == .archiveProject(old) }) {
            return withdrawing(project: old, from: outbox)
        }
        return outbox.compactMap { operation in
            switch operation.command {
            case .createProject(let create) where create.projectID == old: return nil
            case .updateProject(let update) where update.projectID == old: return nil
            default:
                var rewritten = operation
                rewritten.command = operation.command.replacing(project: old, with: new)
                return rewritten
            }
        }
    }

    /// `outbox` after the local tag `old` was merged into the existing tag
    /// `new`. As for projects: task references follow the merge (a task
    /// naming both keeps one); a rename or delete of `old` is dropped, and
    /// when `outbox` deletes `old` its tasks lose the tag instead.
    public static func rewritingAfterMerge(
        _ outbox: [PendingOperation], tag old: TagID, into new: TagID
    ) -> [PendingOperation] {
        if outbox.contains(where: { $0.command == .deleteTag(old) }) {
            return withdrawing(tag: old, from: outbox)
        }
        return outbox.compactMap { operation in
            switch operation.command {
            case .createTag(let create) where create.tagID == old: return nil
            case .renameTag(let rename) where rename.tagID == old: return nil
            default:
                var rewritten = operation
                rewritten.command = operation.command.replacing(tag: old, with: new)
                return rewritten
            }
        }
    }

    /// `outbox` as if the project `id` had been archived before any of it:
    /// its creation, edits and archive are dropped, a task created in it is
    /// created without a project, and an edit that moved a task to it
    /// clears the task's project (which is where archiving left it).
    static func withdrawing(project id: ProjectID, from outbox: [PendingOperation]) -> [PendingOperation] {
        outbox.compactMap { operation in
            switch operation.command {
            case .createProject(let create) where create.projectID == id: return nil
            case .updateProject(let update) where update.projectID == id: return nil
            case .archiveProject(let archived) where archived == id: return nil
            default:
                var rewritten = operation
                rewritten.command = operation.command.removing(project: id)
                return rewritten
            }
        }
    }

    /// `outbox` as if the tag `id` had been deleted before any of it: its
    /// creation, renames and delete are dropped and tasks lose the tag.
    static func withdrawing(tag id: TagID, from outbox: [PendingOperation]) -> [PendingOperation] {
        outbox.compactMap { operation in
            switch operation.command {
            case .createTag(let create) where create.tagID == id: return nil
            case .renameTag(let rename) where rename.tagID == id: return nil
            case .deleteTag(let deleted) where deleted == id: return nil
            default:
                var rewritten = operation
                rewritten.command = operation.command.removing(tag: id)
                return rewritten
            }
        }
    }
}

extension GTDCommand {
    /// The same command with every reference to `old` replaced by `new`. This
    /// moves a record to another client id (sync re-keying the same server
    /// record); a merge into a *different* record goes through
    /// `OutboxReplayer.rewritingAfterMerge`, which does not carry renames or
    /// archives over.
    public func replacing(project old: ProjectID, with new: ProjectID) -> GTDCommand {
        func swap(_ id: ProjectID) -> ProjectID { id == old ? new : id }
        switch self {
        case .createProject(var create):
            create.projectID = swap(create.projectID)
            return .createProject(create)
        case .updateProject(var update):
            update.projectID = swap(update.projectID)
            return .updateProject(update)
        case .archiveProject(let id):
            return .archiveProject(swap(id))
        case .createTask(var create):
            create.projectID = create.projectID.map(swap)
            return .createTask(create)
        case .updateTask(var update):
            if case .set(let id) = update.changes.projectID { update.changes.projectID = .set(swap(id)) }
            return .updateTask(update)
        case .createTag, .renameTag, .deleteTag, .transitionTask, .createSubtask, .updateSubtask,
            .transitionSubtask, .createComment, .updateComment, .decideTask, .undoDecision, .autoParkTask,
            .bulkRelease, .undoBulkRelease, .review:
            return self
        }
    }

    /// The same command with every reference to `old` replaced by `new`. A
    /// tag list that then names `new` twice keeps its first occurrence. Like
    /// `replacing(project:with:)`, for re-keying one record.
    public func replacing(tag old: TagID, with new: TagID) -> GTDCommand {
        func swap(_ ids: [TagID]) -> [TagID] {
            guard ids.contains(old) else { return ids }
            var seen = Set<TagID>()
            return ids.map { $0 == old ? new : $0 }.filter { seen.insert($0).inserted }
        }
        switch self {
        case .createTag(var create):
            if create.tagID == old { create.tagID = new }
            return .createTag(create)
        case .renameTag(var rename):
            if rename.tagID == old { rename.tagID = new }
            return .renameTag(rename)
        case .deleteTag(let id):
            return .deleteTag(id == old ? new : id)
        case .createTask(var create):
            create.tagIDs = swap(create.tagIDs)
            return .createTask(create)
        case .updateTask(var update):
            if case .set(let ids) = update.changes.tagIDs { update.changes.tagIDs = .set(swap(ids)) }
            return .updateTask(update)
        case .createProject, .updateProject, .archiveProject, .transitionTask, .createSubtask,
            .updateSubtask, .transitionSubtask, .createComment, .updateComment, .decideTask, .undoDecision,
            .autoParkTask, .bulkRelease, .undoBulkRelease, .review:
            return self
        }
    }

    /// The same task command without project `id`: a creation without a
    /// project, an edit that set it clears the project instead. Commands on
    /// the project itself are the caller's to drop.
    func removing(project id: ProjectID) -> GTDCommand {
        switch self {
        case .createTask(var create) where create.projectID == id:
            create.projectID = nil
            return .createTask(create)
        case .updateTask(var update) where update.changes.projectID == .set(id):
            update.changes.projectID = .clear
            return .updateTask(update)
        default:
            return self
        }
    }

    /// The same task command without tag `id` in its tag list.
    func removing(tag id: TagID) -> GTDCommand {
        switch self {
        case .createTask(var create) where create.tagIDs.contains(id):
            create.tagIDs.removeAll { $0 == id }
            return .createTask(create)
        case .updateTask(var update):
            guard case .set(var ids) = update.changes.tagIDs, ids.contains(id) else { return self }
            ids.removeAll { $0 == id }
            update.changes.tagIDs = .set(ids)
            return .updateTask(update)
        default:
            return self
        }
    }
}
