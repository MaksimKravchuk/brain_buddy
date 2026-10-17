import BrainBuddyCore
import BrainBuddyPersistence
import BrainBuddySync
import BrainBuddyWorkspace
import Foundation
import Testing

@testable import BrainBuddyMacCore
@testable import BrainBuddyWorkspace

/// A Mac on the shared runtime whose sync rounds keep failing: the status line and the popover show
/// "Couldn't sync" with the reference ID of the failed round, as the legacy engine does (spec 026,
/// FR-023).
@Suite("Rust-path sync failure on the Mac")
@MainActor
struct RustSyncFailurePopoverTests {
    private actor Port: SyncRuntimePort {
        private var next: SyncRuntimeWakeResult = .transportUnavailable
        func emit(_ result: SyncRuntimeWakeResult) { next = result }
        func request(_ trigger: SyncTrigger) async -> SyncRuntimeWakeResult { next }
        func setNetworkAvailable(_ available: Bool) async {}
        func close() async {}
    }

    @Test("026-FR-023: a failing Rust sync shows Couldn't sync and the round's reference ID in the status line and popover, then recovers")
    func failureReachesTheLineAndThePopover() async throws {
        let folder = TemporaryFolder()
        let clock = TestClock()
        let port = Port()
        let bridge = try RustBridgeRuntime()
        let runtime = try await bridge.openStore(workspaceID: "owner", databaseURL: folder.file("store.sqlite3"))
        let url = try #require(URL(string: "https://example.com/api"))
        let account = LinkedAccount(
            id: "owner", email: "alex@example.com", serverURL: url, linkedAt: clock.now.addingTimeInterval(-86_400))
        let workspace = Workspace(store: InMemoryDocumentStore(), sync: nil,
            rust: RustWorkspaceSelection(runtime: runtime,
                facade: RustDomainFacade(runtime: bridge, context: RustDomainContext(deviceTimeZone: "UTC")),
                transport: port, account: account, startup: .prepared), now: clock.provider)
        await workspace.load()
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        let reference = "4e5d9a20-0000-4000-8000-000000000001"

        await port.emit(.status(.failing(message: "Syncing stopped.", referenceID: reference, lastSyncedAt: nil)))
        await workspace.syncNow()
        clock.advance(SyncTiming.failureSurfacesAfter)
        await workspace.syncNow()

        let snapshot = workspace.syncSnapshot
        let line = SyncStatusLineModel(snapshot: snapshot, now: clock.now, device: .mac, calendar: calendar)
        #expect(line.description.text == "Couldn't sync · Retry")
        let content = SyncPopoverModel.content(
            snapshot: snapshot, issues: workspace.issues, state: workspace.state, discarded: [],
            now: clock.now, calendar: calendar)
        guard case .failing(_, let shownReference)? = content.notice else {
            Issue.record("expected the failing notice, got \(String(describing: content.notice))")
            return
        }
        #expect(shownReference == reference)

        await port.emit(.status(.idle(lastSyncedAt: clock.now)))
        await workspace.syncNow()
        let recovered = SyncStatusLineModel(
            snapshot: workspace.syncSnapshot, now: clock.now, device: .mac, calendar: calendar)
        #expect(recovered.description.text != "Couldn't sync · Retry")
        #expect(workspace.syncSnapshot.lastFailureReferenceID == nil)
        await workspace.closeRuntime()
    }
}
