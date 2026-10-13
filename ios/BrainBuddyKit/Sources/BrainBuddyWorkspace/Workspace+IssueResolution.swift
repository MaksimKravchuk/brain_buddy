import BrainBuddyCore
import BrainBuddySync
import Foundation

// The Workspace entry points behind the sync-issue screens of both apps (spec 026 M-02/M-03, D-02,
// D-03): resolve an issue atomically, read the account's copy of its record, read the recovery
// state, rebuild the synced copy. The screens' drafts decide what is legal; this only executes a
// decision the person applied, through the shared runtime, with the shown revision as precondition.

extension Workspace {
    /// Stores one decision for an issue and every action held behind it, or nothing. Throws
    /// `RuntimeIssueResolutionError` (`.changedAgain` means the account's record moved after it was
    /// shown: reload `accountVersion(ofIssue:)` and ask again; everything stays as it was).
    /// Repeating an already stored decision answers with `repeated == true`.
    public func resolveIssue(_ resolution: RuntimeIssueResolution) async throws -> RuntimeIssueResolutionResult {
        guard let runtime = rustRuntime, isRustBound else { throw RuntimeIssueResolutionError.notReady }
        guard !isSigningOut else { throw RuntimeIssueResolutionError.notReady }
        let binding = runtimeBindingID
        let ids = makeID
        let request = try RuntimeIssueResolutionPlanner.plan(resolution, among: runtimeIssues) {
            ids().uuidString.lowercased()
        }
        do {
            let context = try rustExecuteContext(at: now())
            let result = try await runtime.resolveIssue(request, context: context)
            // The runtime's own invalidation refreshes status and issues; this catches up at once.
            if binding == runtimeBindingID { await refreshRustStatus() }
            return result
        } catch let error as RustBridgeError {
            throw RuntimeIssueResolutionError(code: error.code)
        }
    }

    /// The account's copy of the issue's record, read-only, for the "account version" side of a
    /// conflict. Nil when the issue is gone or has no known record.
    public func accountVersion(ofIssue issueID: String) async throws -> RuntimeIssueAccountVersion? {
        guard let runtime = rustRuntime, isRustBound else { throw RuntimeIssueResolutionError.notReady }
        guard let current = try await runtime.issueCurrent(issueID) else { return nil }
        let keys = Set(runtimeIssues.first(where: { $0.id == issueID })?.localText.keys.map { $0 } ?? [])
        var fields: [String: String] = [:]
        if let body = current.record,
            let object = try JSONSerialization.jsonObject(with: body) as? [String: Any]
        {
            for (key, value) in object {
                if let text = value as? String, keys.isEmpty || keys.contains(key) { fields[key] = text }
            }
        }
        return RuntimeIssueAccountVersion(revision: current.editRevision, isDeleted: current.deleted, fields: fields)
    }

    /// Where recovery stands: the device epoch and account link as the store holds them, whether
    /// the store needs a newer app or could not open, and a rebuild in progress or failed.
    public var syncRecovery: RuntimeSyncRecovery {
        var recovery = RuntimeSyncRecovery(
            epochState: rustSyncState?.deviceEpochState ?? "none",
            accountLinkState: rustSyncState?.accountLinkState ?? "unchosen")
        recovery.storeNeedsUpdate = rustLoadFailureCode == "STORE_UPGRADE_REQUIRED"
        recovery.storeUnavailable = rustLoadFailureCode != nil
        recovery.rebuild = rustRebuild
        return recovery
    }

    /// "Rebuild synced copy": a non-destructive reset that keeps waiting changes and saved issues.
    /// Reports `.rebuilding` through `syncRecovery` while it runs and `.failed` if it stops.
    /// Without an installed transport it does nothing and says so by returning `.transportUnavailable`.
    @discardableResult
    public func rebuildSyncedCopy() async -> SyncRuntimeRebuildResult {
        guard let selection = rustSelection, isRustBound, rustRebuild != .rebuilding else {
            return .transportUnavailable
        }
        let binding = runtimeBindingID
        rustRebuild = .rebuilding
        let result = await selection.transport.rebuildSyncedCopy()
        guard binding == runtimeBindingID else { return result }
        switch result {
        case .rebuilt, .transportUnavailable: rustRebuild = .idle
        case .failed(let reference): rustRebuild = .failed(referenceID: reference)
        }
        await refreshRustStatus()
        return result
    }
}
