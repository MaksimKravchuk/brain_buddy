import Foundation

/// The account-linking step for local auto-parks (contracts/ios-commands.md
/// §7, owner decision 2026-10-06, FR-014). The server re-evaluates a device
/// park with its own clocks, which for tasks it only now receives start at
/// upload, so it would answer `applied: false` and move every account-less
/// park back to Next. Before an account-less store is uploaded, its unsent
/// outbox is rewritten:
///
/// - every unsent `autoParkTask` becomes an ordinary move to Someday at the
///   same position and `issuedAt` (no park marker, no `clockBefore`); those
///   parks count as seen, so unsent park acknowledgements for them go;
/// - every unsent `extend` decision (and its queued Undo) is dropped and its
///   task listed once on "While you were away" (`linkedExtensionNotices`):
///   the server's fresh clock gives it at least the 7 days, and an `extend`
///   would be refused as `extension_not_due`. The reason is discarded with it;
/// - everything else is kept, unchanged and in order.
///
/// Deterministic, and run once per linking.
public enum ReviewAccountLinking {
    public static func convertLocalAutoParks(_ document: StoreDocument) -> StoreDocument {
        var converted = document
        var parkedTasks = Set<TaskID>()
        var droppedDecisions = Set<DecisionID>()
        var outbox: [PendingOperation] = []
        for operation in document.outbox {
            guard !operation.hasBeenSent else {
                outbox.append(operation)
                continue
            }
            switch operation.command {
            case .autoParkTask(let park):
                var move = operation
                move.command = .transitionTask(.init(taskID: park.taskID, action: .move, toList: .someday))
                parkedTasks.insert(park.taskID)
                outbox.append(move)
            case .decideTask(let decide) where decide.type == .extend:
                droppedDecisions.insert(decide.decisionID)
                if !converted.local.linkedExtensionNotices.contains(decide.taskID) {
                    converted.local.linkedExtensionNotices.append(decide.taskID)
                }
            case .undoDecision(let id) where droppedDecisions.contains(id):
                continue
            default:
                outbox.append(operation)
            }
        }
        // Converted parks count as seen: their unsent acknowledgements go.
        converted.outbox = outbox.compactMap { operation in
            guard !operation.hasBeenSent, case .review(.acknowledgeParks(let items)) = operation.command else {
                return operation
            }
            let kept = items.filter { !parkedTasks.contains($0.taskID) }
            guard !kept.isEmpty else { return nil }
            var rewritten = operation
            rewritten.command = .review(.acknowledgeParks(kept))
            return rewritten
        }
        for task in parkedTasks { converted.local.issuedAutoParks[task] = nil }
        return converted
    }
}
