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
        let request = try rustResolutions.request(for: resolution, among: runtimeIssues) {
            ids().uuidString.lowercased()
        }
        do {
            let context = try rustExecuteContext(at: now())
            let result = try await runtime.resolveIssue(request, context: context)
            // The runtime's own invalidation refreshes status and issues; this catches up at once.
            if binding == runtimeBindingID { await refreshRustStatus() }
            return result
        } catch let error as RustBridgeError {
            let typed = RuntimeIssueResolutionError(code: error.code)
            if binding == runtimeBindingID { rustResolutions.settle(issueID: resolution.issueID, error: typed) }
            throw typed
        }
    }

    /// `resolveIssue` as the screens use it: every refusal becomes an outcome the draft can take in
    /// (`ConflictDecisionDraft.finish`). Nothing is saved unless the outcome is `.resolved`.
    public func submit(_ resolution: RuntimeIssueResolution) async -> RuntimeIssueApplyOutcome {
        do {
            _ = try await resolveIssue(resolution)
            return .resolved
        } catch let error as RuntimeIssueResolutionError {
            switch error {
            case .changedAgain:
                let current = try? await accountVersion(ofIssue: resolution.issueID)
                return .changedAgain(current ?? nil)
            case .alreadyResolved, .unknownIssue: return .gone
            default: return .failed(error)
            }
        } catch {
            return .failed(.failed(code: "UNKNOWN"))
        }
    }

    /// The account's copy of the issue's record, read-only, for the "account version" side of a
    /// conflict. Nil when the issue is gone or has no known record.
    public func accountVersion(ofIssue issueID: String) async throws -> RuntimeIssueAccountVersion? {
        try await accountVersion(ofIssue: issueID, afterRead: nil)
    }

    /// `afterRead` runs between the runtime's answer and the binding check (a test seam).
    func accountVersion(ofIssue issueID: String, afterRead: (@MainActor () async -> Void)?) async throws
        -> RuntimeIssueAccountVersion? {
        guard let runtime = rustRuntime, isRustBound else { throw RuntimeIssueResolutionError.notReady }
        let binding = runtimeBindingID
        let keys = Set(runtimeIssues.first(where: { $0.id == issueID })?.localText.keys.map { $0 } ?? [])
        let read = try await runtime.issueCurrent(issueID)
        await afterRead?()
        // Sign-in, sign-out or a replaced binding while reading: the text may belong to another account.
        guard binding == runtimeBindingID, isRustBound else { throw RuntimeIssueResolutionError.notReady }
        guard let current = read else { return nil }
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

extension SyncRuntimeRebuildResult {
    /// What to tell the person once "Rebuild synced copy" returned, or nil where the recovery card
    /// already says it (a failure keeps its card and reference). A rebuild that never ran must not
    /// read as done.
    public var notice: String? {
        switch self {
        case .rebuilt: "Synced copy rebuilt."
        case .transportUnavailable:
            "Syncing isn't available in this version of the app yet, so nothing was rebuilt. Your waiting changes and saved issues are kept."
        case .failed: nil
        }
    }
}
