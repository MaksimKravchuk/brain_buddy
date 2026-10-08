import BrainBuddyCore

/// A pending change as a sign-out confirmation names it (spec 021, FR-018, X-04): the operation
/// and what it holds. An edit folded into it (`OutboxCompactor`) keeps the operation's id but makes
/// it another change, which "Sign out and remove" then refuses to remove unseen.
public struct PendingChange: Hashable, Sendable {
    public let id: PendingOperation.ID
    let command: GTDCommand

    init(_ operation: PendingOperation) {
        id = operation.id
        command = operation.command
    }
}
