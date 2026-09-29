import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyPersistence
import Foundation

extension SyncEngine {
    /// One cycle: push until empty or blocked → pull (when warranted) → push
    /// again if the replay left work → hydrate children.
    func runCycle(epoch cycleEpoch: Int) async -> CycleOutcome {
        guard let account, canRun, cycleEpoch == epoch else { return .aborted }
        await setStatus(.syncing)
        let context = CycleContext(account: account, client: client(for: account.serverURL), epoch: cycleEpoch)
        do {
            var pulled = false
            let neverPulled = try await loadDocument().sync.lastPullAt == nil
            if pullFirst || neverPulled {
                try await pull(context)
                pullFirst = false
                pulled = true
            }
            let push = try await pushOutbox(context)
            let lastPull = try await loadDocument().sync.lastPullAt
            let pullIsOld = lastPull.map { now().timeIntervalSince($0) > configuration.pullInterval } ?? true
            var wantsPull = firstCycle || pullRequested || push.changed || push.needsPull || pullIsOld
            if pulled, !push.changed, !push.needsPull { wantsPull = false }
            firstCycle = false
            pullRequested = false
            pastPullDecision = true
            if wantsPull {
                try await pull(context)
                // Operations queued meanwhile (or re-enabled by the new base) go out now.
                var rounds = 0
                while rounds < 2, !(try await loadDocument().outbox.isEmpty) {
                    rounds += 1
                    let again = try await pushOutbox(context)
                    guard again.needsPull else { break }
                    try await pull(context)
                }
            }
            try await hydrateChangedTasks(context)
            return .synced
        } catch {
            return outcome(for: error, epoch: cycleEpoch)
        }
    }

    func outcome(for error: any Error, epoch cycleEpoch: Int) -> CycleOutcome {
        guard cycleEpoch == epoch, !(error is SyncAborted) else { return .aborted }
        if let error = error as? APIError {
            switch error.kind {
            case .unauthorized: return .unauthorized
            case .network, .cancelled: return .offline
            default: return .serverFailure(message: error.message, referenceID: error.referenceID)
            }
        }
        if let error = error as? DocumentStoreError {
            return .serverFailure(message: error.message, referenceID: nil)
        }
        return .serverFailure(message: "Brain Buddy couldn't sync. It will try again.", referenceID: nil)
    }

    // MARK: - Document access

    func loadDocument() async throws -> StoreDocument {
        try await store.load() ?? StoreDocument()
    }

    /// Throws `SyncAborted` when the cycle's account is no longer the engine's.
    func checkActive(_ context: CycleContext) throws {
        guard context.epoch == epoch, !Task.isCancelled else { throw SyncAborted() }
    }

    /// A read-modify-write of the latest document for the cycle's account,
    /// followed by `.documentChanged`. Nothing is written when the document
    /// is no longer linked to that account.
    @discardableResult
    func update(
        _ context: CycleContext, _ transform: @Sendable (inout StoreDocument) throws -> Void
    ) async throws -> StoreDocument {
        try checkActive(context)
        let accountID = context.account.id
        let document = try await store.update { doc in
            guard doc.account?.id == accountID else { throw SyncAborted() }
            try transform(&doc)
        }
        await emit(.documentChanged(document))
        return document
    }
}
