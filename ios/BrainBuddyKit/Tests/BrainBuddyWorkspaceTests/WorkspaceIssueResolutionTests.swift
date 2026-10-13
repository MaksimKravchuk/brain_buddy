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
