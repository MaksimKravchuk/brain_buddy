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
        /// The `index`-th unsent command of a selected runtime, which reports a count: a sign-out
        /// names how many it removes, and the runtime checks the count again under its lock.
        case runtimeUnsent(Int, generation: UInt64)
        case runtimeIssue(String)
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

    init(runtimeUnsent index: Int, generation: UInt64) {
        id = Self.deterministicID(UInt64(index), salt: 1)
        content = .runtimeUnsent(index, generation: generation)
    }

    init(runtimeIssue issueID: String) {
        var hash: UInt64 = 0xcbf2_9ce4_8422_2325
        for byte in issueID.utf8 { hash = (hash ^ UInt64(byte)) &* 0x100_0000_01b3 }
        id = Self.deterministicID(hash, salt: 2)
        content = .runtimeIssue(issueID)
    }

    /// How many unsent changes a runtime sign-out confirmation names.
    var runtimeUnsentCount: Int {
        if case .runtimeUnsent = content { 1 } else { 0 }
    }

    /// The projection generation the unsent change was named at: a change queued or replaced
    /// since moves it, so a count that merely stays equal is not the same work.
    var runtimeUnsentGeneration: UInt64? {
        if case .runtimeUnsent(_, let generation) = content { generation } else { nil }
    }

    var runtimeIssueID: String? {
        if case .runtimeIssue(let id) = content { id } else { nil }
    }

    private static func deterministicID(_ value: UInt64, salt: UInt8) -> UUID {
        var bytes = [UInt8](repeating: 0, count: 16)
        bytes[0] = salt
        for shift in 0..<8 { bytes[8 + shift] = UInt8(truncatingIfNeeded: value >> (8 * UInt64(shift))) }
        return UUID(uuid: (bytes[0], bytes[1], bytes[2], bytes[3], bytes[4], bytes[5], bytes[6], bytes[7],
                           bytes[8], bytes[9], bytes[10], bytes[11], bytes[12], bytes[13], bytes[14], bytes[15]))
    }

    /// Every change `document` holds, plus `unpersisted` operations not written to it yet.
    static func all(in document: StoreDocument?, unpersisted: [PendingOperation] = []) -> Set<PendingChange> {
        let operations = (document?.outbox ?? []) + unpersisted
        return Set(operations.map(PendingChange.init)).union((document?.issues ?? []).map(PendingChange.init))
    }
}
