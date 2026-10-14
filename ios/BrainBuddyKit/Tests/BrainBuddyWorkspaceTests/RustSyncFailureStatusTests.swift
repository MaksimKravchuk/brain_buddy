import BrainBuddyCore
import BrainBuddySync
import Foundation
import Testing

@testable import BrainBuddyWorkspace

/// What the sync status line says on the shared-runtime path while rounds fail and then recover:
/// the snapshot carries the failure's start, its last attempt and the reference ID the failed round
/// reported, with the legacy engine's words (spec 026 FR-023, user-visible sync status).
@Suite("Rust-path sync failure status (026-FR-023)")
struct RustSyncFailureStatusTests {
    @Test("026-FR-023: failing rounds fill the snapshot, keep their start, and the next success clears them")
    @MainActor
    func failingThenRecovered() async throws {
        let h = Harness()
        defer { h.cleanup() }
        let clock = TestClock(h.instant)
        let transport = ScriptedPort()
        let workspace = try await h.workspace(
            scope: "a", account: h.accountA, transport: transport, lifecycle: nil, clock: clock)
        func line() -> SyncStatusDescription {
            SyncStatusDescriber.describe(
                workspace.syncSnapshot, now: clock.now, device: .mac, calendar: Calendar(identifier: .gregorian))
        }
        await transport.emit(.status(.idle(lastSyncedAt: h.instant)))
        await workspace.syncNow()
        // The fake store has no successful round of its own, so the line reads "Not synced yet".
        #expect(line().state == .notSyncedYet)
        #expect(workspace.syncSnapshot.failingSince == nil)

        // First failed round: the run starts, but 60 s have not passed, so no failure is shown yet.
        clock.advance(by: 10)
        let started = clock.now
        await transport.emit(.status(.failing(message: "Syncing stopped.", referenceID: "ref-1", lastSyncedAt: h.instant)))
        await workspace.syncNow()
        var snapshot = workspace.syncSnapshot
        #expect(snapshot.failingSince == started)
        #expect(snapshot.lastFailedAttemptAt == started)
        #expect(snapshot.lastFailureReferenceID == "ref-1")
        #expect(line().state != .failing)

        // A failed round 60 s later: the start is kept, the last attempt moves, the line shows it.
        clock.advance(by: 60)
        await transport.emit(.status(.failing(message: "Syncing stopped.", referenceID: "ref-2", lastSyncedAt: h.instant)))
        await workspace.syncNow()
        snapshot = workspace.syncSnapshot
        #expect(snapshot.failingSince == started, "the run keeps its start")
        #expect(snapshot.lastFailedAttemptAt == clock.now)
        #expect(snapshot.lastFailureReferenceID == "ref-2")
        #expect(line().text == "Couldn't sync · Retry")
        #expect(line().tooltip.hasSuffix("Reference ID ref-2"))

        // A retrying round carries no ID: none is made up and no stale one is kept.
        clock.advance(by: 5)
        await transport.emit(.status(.failing(message: "retrying", referenceID: nil, lastSyncedAt: h.instant)))
        await workspace.syncNow()
        #expect(workspace.syncSnapshot.failingSince == started)
        #expect(workspace.syncSnapshot.lastFailureReferenceID == nil)

        // The next success ends it.
        clock.advance(by: 30)
        await transport.emit(.status(.idle(lastSyncedAt: clock.now)))
        await workspace.syncNow()
        snapshot = workspace.syncSnapshot
        #expect(snapshot.failingSince == nil && snapshot.lastFailedAttemptAt == nil && snapshot.lastFailureReferenceID == nil)
        #expect(line().state == .notSyncedYet && line().text == "Not synced yet", "no longer \"Couldn't sync\"")
        await workspace.closeRuntime()
    }

    @Test("026-FR-023: offline keeps the failing run and a ended session ends it, for statuses reached between requests")
    @MainActor
    func betweenRequestsAndOffline() async throws {
        let h = Harness()
        defer { h.cleanup() }
        let clock = TestClock(h.instant)
        let transport = ScriptedPort()
        let workspace = try await h.workspace(
            scope: "a", account: h.accountA, transport: transport, lifecycle: nil, clock: clock)
        await transport.push(.status(.failing(message: "x", referenceID: "ref-9", lastSyncedAt: nil)))
        try await waitUntil { workspace.syncSnapshot.failingSince != nil }
        #expect(workspace.syncSnapshot.lastFailureReferenceID == "ref-9")

        await transport.push(.status(.offline(lastSyncedAt: nil)))
        try await waitUntil { workspace.syncStatus == .offline(lastSyncedAt: nil) }
        #expect(workspace.syncSnapshot.failingSince != nil, "offline keeps the run")

        await transport.push(.status(.needsSignIn))
        try await waitUntil { workspace.syncStatus == .needsSignIn }
        #expect(workspace.syncSnapshot.failingSince == nil, "an ended session ends the run")
        await workspace.closeRuntime()
    }

    @MainActor
    private func waitUntil(_ done: () -> Bool) async throws {
        for _ in 0..<500 where !done() { try await Task.sleep(for: .milliseconds(10)) }
        #expect(done())
    }
}

/// Answers each request with the last emitted result and lets a test push a status between requests.
actor ScriptedPort: SyncRuntimePort {
    private var next: SyncRuntimeWakeResult = .transportUnavailable
    private var handler: (@Sendable (SyncRuntimeWakeResult) -> Void)?

    func emit(_ result: SyncRuntimeWakeResult) { next = result }
    func push(_ result: SyncRuntimeWakeResult) { handler?(result) }

    func request(_ trigger: SyncTrigger) async -> SyncRuntimeWakeResult { next }
    func setNetworkAvailable(_ available: Bool) async {}
    func close() async {}
    func setStatusHandler(_ handler: (@Sendable (SyncRuntimeWakeResult) -> Void)?) async { self.handler = handler }
}
