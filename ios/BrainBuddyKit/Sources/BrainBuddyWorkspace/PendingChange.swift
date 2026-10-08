import BrainBuddyCore
import Foundation

/// A local change a sign-out confirmation names (spec 021, FR-018, X-04): an unsent operation or
/// an open sync issue, with what it holds. An edit folded into an operation (`OutboxCompactor`)
/// keeps its id but makes it another change, and an operation the server rejected meanwhile becomes
/// an issue, another change too: "Sign out and remove" refuses to remove either unseen.
public struct PendingChange: Hashable, Sendable {
    private enum Content: Hashable, Sendable {
        case unsent(GTDCommand)
        case issue(SyncIssue)
    }

    public let id: UUID
    private let content: Content

    init(_ operation: PendingOperation) {
        id = operation.id
        content = .unsent(operation.command)
    }

    init(_ issue: SyncIssue) {
        id = issue.id
        content = .issue(issue)
    }

    /// Every change `document` holds, plus `unpersisted` operations not written to it yet.
    static func all(in document: StoreDocument?, unpersisted: [PendingOperation] = []) -> Set<PendingChange> {
        let operations = (document?.outbox ?? []) + unpersisted
        return Set(operations.map(PendingChange.init)).union((document?.issues ?? []).map(PendingChange.init))
    }
}
