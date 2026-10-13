import BrainBuddyCore
import BrainBuddyPersistence
import BrainBuddySync
import Foundation
import Testing

@testable import BrainBuddyWorkspace

@Suite("Workspace issue resolution and recovery API (026-FR-007, 026-FR-010)")
struct WorkspaceIssueResolutionTests {
    private static let instant = Date(timeIntervalSince1970: 1_790_000_000)

    @MainActor
    private func workspace(transport: any SyncRuntimePort = PendingRustSyncRuntimePort()) async throws
        -> (Workspace, URL) {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let bridge = try RustBridgeRuntime()
        let runtime = try await bridge.openStore(workspaceID: "local",
            databaseURL: directory.appendingPathComponent("store.sqlite3"))
        let workspace = Workspace(store: ControlledStore(), sync: nil,
            rust: RustWorkspaceSelection(runtime: runtime,
                facade: RustDomainFacade(runtime: bridge, context: RustDomainContext(deviceTimeZone: "UTC")),
                transport: transport, startup: .freshAccountless),
            now: { Self.instant })
        await workspace.load()
        return (workspace, directory)
    }

    @Test("026-FR-007: resolving an issue that is not open is refused as unknown and changes nothing")
    @MainActor
    func unknownIssue() async throws {
        let (workspace, directory) = try await workspace()
        defer { try? FileManager.default.removeItem(at: directory) }
        let resolution = RuntimeIssueResolution(issueID: "issue_missing", outcome: .keepMine, shownRevision: "2")
        await #expect(throws: RuntimeIssueResolutionError.unknownIssue) { try await workspace.resolveIssue(resolution) }
        #expect(try await workspace.accountVersion(ofIssue: "issue_missing") == nil)
        #expect(workspace.pendingChangeCount == 0)
        await workspace.closeRuntime()
        await #expect(throws: RuntimeIssueResolutionError.notReady) { try await workspace.resolveIssue(resolution) }
    }

    @Test("026-FR-007: submitting for an issue that is gone answers gone; a closed runtime answers a failure and saves nothing")
    @MainActor
    func submitOutcomes() async throws {
        let (workspace, directory) = try await workspace()
        defer { try? FileManager.default.removeItem(at: directory) }
        let resolution = RuntimeIssueResolution(issueID: "issue_missing", outcome: .useAccountVersion, shownRevision: "2")
        #expect(await workspace.submit(resolution) == .gone)
        #expect(workspace.pendingChangeCount == 0)
        await workspace.closeRuntime()
        #expect(await workspace.submit(resolution) == .failed(.notReady))
        // A draft that outcome leaves behind stays editable and applies again.
        var draft = ConflictDecisionDraft(dependentIDs: [], shownRevision: "2", issueID: "issue_missing")
        draft.choose(.account)
        let decision = draft.apply()
        #expect(decision != nil)
        draft.finish(await workspace.submit(resolution))
        #expect(draft.phase == .saveFailed && draft.canApply && draft.version == .account)
    }

    @Test("026-FR-010: a draft written by one launch is read by the next, holds no text, and is forgotten once resolved")
    func draftStoreSurvivesRelaunch() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        var draft = ConflictDecisionDraft(dependentIDs: ["a", "b"], shownRevision: "7", issueID: "issue_1")
        draft.choose(.saved)
        draft.setChoice(.discard, for: "b")
        draft.requestDiscard()
        draft.confirmDiscard()

        let first = FileConflictDraftStore(directory: directory)
        #expect(first.save(draft, issueID: "issue_1"))
        // A new store value over the same folder is a relaunch.
        let second = FileConflictDraftStore(directory: directory)
        let loaded = try #require(second.load(issueID: "issue_1"))
        var restored = ConflictDecisionDraft(dependentIDs: ["a", "b"], shownRevision: "7", issueID: "issue_1")
        restored.restore(from: loaded)
        #expect(restored.version == .saved && restored.choice(for: "b") == .discard)
        #expect(restored.phase == .choosing && !restored.canApply, "restoring neither submits nor pre-confirms the discard")
        #expect(second.load(issueID: "issue_2") == nil)
        let files = try FileManager.default.contentsOfDirectory(atPath: directory.path)
        #expect(files.count == 1 && files[0].hasSuffix(".json") && !files[0].contains("issue"), "the id never names a path")

        #expect(!second.save(draft, issueID: "issue_2") || second.load(issueID: "issue_2") == nil, "a draft only reads back for its own issue")
        let other = ConflictDecisionDraft(dependentIDs: [], shownRevision: "1", issueID: "issue_2")
        second.save(other, issueID: "issue_2")
        second.prune(keeping: ["issue_2"])
        #expect(second.load(issueID: "issue_1") == nil && second.load(issueID: "issue_2") != nil)
        second.clear(issueID: "issue_2")
        #expect(FileConflictDraftStore(directory: directory).load(issueID: "issue_2") == nil)
    }

    @Test("026-FR-010: a rebuild that could not run is said so, and never reads as done")
    func rebuildNotices() {
        #expect(SyncRuntimeRebuildResult.rebuilt.notice == "Synced copy rebuilt.")
        #expect(SyncRuntimeRebuildResult.transportUnavailable.notice?.contains("nothing was rebuilt") == true)
        #expect(SyncRuntimeRebuildResult.failed(referenceID: "r").notice == nil)
    }

    @Test("026-FR-010: a fresh runtime reports no recovery, and the epoch and link are read as values")
    @MainActor
    func recoveryDefaults() async throws {
        let (workspace, directory) = try await workspace()
        defer { try? FileManager.default.removeItem(at: directory) }
        let recovery = workspace.syncRecovery
        #expect(recovery.accountLink == .accountLess)
        #expect(recovery.epoch == .none)
        #expect(!recovery.needsAttention)
        #expect(recovery.rebuild == .idle)
        await workspace.closeRuntime()
    }

    @Test("026-FR-010: Rebuild synced copy reports rebuilding, then failed with a reference, then clears when it works")
    @MainActor
    func rebuildStates() async throws {
        let port = ScriptedRebuildPort()
        let (workspace, directory) = try await workspace(transport: port)
        defer { try? FileManager.default.removeItem(at: directory) }
        await port.script(.failed(referenceID: "ref-1"))
        let failed = await workspace.rebuildSyncedCopy()
        #expect(failed == .failed(referenceID: "ref-1"))
        #expect(workspace.syncRecovery.rebuild == .failed(referenceID: "ref-1"))
        #expect(workspace.syncRecovery.needsAttention)
        await port.script(.rebuilt)
        #expect(await workspace.rebuildSyncedCopy() == .rebuilt)
        #expect(workspace.syncRecovery.rebuild == .idle)
        await workspace.closeRuntime()
    }

    @Test("026-FR-010: without an installed transport the rebuild does nothing and says so")
    @MainActor
    func rebuildWithoutTransport() async throws {
        let (workspace, directory) = try await workspace()
        defer { try? FileManager.default.removeItem(at: directory) }
        #expect(await workspace.rebuildSyncedCopy() == .transportUnavailable)
        #expect(workspace.syncRecovery.rebuild == .idle)
        await workspace.closeRuntime()
    }
}

private actor ScriptedRebuildPort: SyncRuntimePort {
    private var next = SyncRuntimeRebuildResult.rebuilt
    func script(_ result: SyncRuntimeRebuildResult) { next = result }
    func request(_ trigger: SyncTrigger) async -> SyncRuntimeWakeResult { .transportUnavailable }
    func setNetworkAvailable(_ available: Bool) async {}
    func close() async {}
    func rebuildSyncedCopy() async -> SyncRuntimeRebuildResult { next }
}
