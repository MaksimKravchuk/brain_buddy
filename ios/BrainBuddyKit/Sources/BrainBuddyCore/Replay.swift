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
    /// references to a merged project or tag are rewritten to the survivor.
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
    /// - A project or tag creation whose name an active record already has is
    ///   dropped, and every later operation is rewritten to the existing record.
    /// - An operation the reducer rejects is dropped into `rejected`; later
    ///   operations that depend on it are rejected in turn by the reducer.
    public static func replay(_ outbox: [PendingOperation], onto base: GTDState) -> ReplayResult {
        var state = base
        var pending = outbox
        var kept: [PendingOperation] = []
        var rejected: [RejectedOperation] = []
        kept.reserveCapacity(pending.count)
        for index in pending.indices {
            let operation = pending[index]
            let outcome: ApplyOutcome
            do throws(GTDValidationError) {
                outcome = try GTDReducer.apply(operation.command, at: operation.issuedAt, to: &state, mode: .replay)
            } catch {
                rejected.append(RejectedOperation(operation: operation, error: error))
                continue
            }
            switch outcome {
            case .applied:
                kept.append(operation)
            case .alreadySatisfied:
                break
            case .mergedProject(into: let survivor):
                guard case .createProject(let create) = operation.command else { break }
                for later in pending.indices where later > index {
                    pending[later].command = pending[later].command.replacing(project: create.projectID, with: survivor)
                }
            case .mergedTag(into: let survivor):
                guard case .createTag(let create) = operation.command else { break }
                for later in pending.indices where later > index {
                    pending[later].command = pending[later].command.replacing(tag: create.tagID, with: survivor)
                }
            }
        }
        return ReplayResult(state: state, outbox: kept, rejected: rejected)
    }
}

extension GTDCommand {
    /// The same command with every reference to `old` replaced by `new`.
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
            .transitionSubtask, .createComment, .updateComment:
            return self
        }
    }

    /// The same command with every reference to `old` replaced by `new`. A
    /// tag list that then names `new` twice keeps its first occurrence.
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
            .updateSubtask, .transitionSubtask, .createComment, .updateComment:
            return self
        }
    }
}
