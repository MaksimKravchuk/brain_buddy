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
    /// Applies `outbox` in order onto `base` with `ApplyMode.replay`.
    public static func replay(_ outbox: [PendingOperation], onto base: GTDState) -> ReplayResult {
        fatalError("OutboxReplayer.replay is not implemented yet")
    }
}

public enum OutboxCompactor {
    /// Appends `operation` to `outbox`, folding it into an earlier unsent
    /// operation when that keeps the replayed state identical (for example an
    /// edit of a task whose creation has not been sent yet). Operations with
    /// `hasBeenSent == true` are never modified.
    public static func appending(_ operation: PendingOperation, to outbox: [PendingOperation]) -> [PendingOperation] {
        fatalError("OutboxCompactor.appending is not implemented yet")
    }
}

extension GTDCommand {
    /// The same command with every reference to `old` replaced by `new`.
    public func replacing(project old: ProjectID, with new: ProjectID) -> GTDCommand {
        fatalError("GTDCommand.replacing(project:with:) is not implemented yet")
    }

    /// The same command with every reference to `old` replaced by `new`.
    public func replacing(tag old: TagID, with new: TagID) -> GTDCommand {
        fatalError("GTDCommand.replacing(tag:with:) is not implemented yet")
    }
}
