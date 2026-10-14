import Foundation
import Testing

@testable import BrainBuddyCore

@Suite("Workspace sync status: one source for every surface")
struct WorkspaceSyncStatusPresenterTests {
    let now = Date(timeIntervalSince1970: 1_790_000_000)
    let account = SyncSnapshot.Account.linked(email: "a@example.com")

    private func snapshot(
        online: Bool = true, pending: Int = 3, failingFor: TimeInterval? = nil
    ) -> SyncSnapshot {
        SyncSnapshot(
            account: account, isOnline: online, lastSyncedAt: now.addingTimeInterval(-60), pendingCount: pending,
            oldestPendingAt: pending > 0 ? now.addingTimeInterval(-120) : nil,
            failingSince: failingFor.map { now.addingTimeInterval(-$0) },
            lastFailedAttemptAt: failingFor == nil ? nil : now)
    }

    @Test("026-FR-023 server down while the network path is up: offline, waiting, and the saved line")
    func serverDownReadsOffline() {
        let status = WorkspaceSyncStatusPresenter.describe(
            snapshot: snapshot(online: true), status: .offline(lastSyncedAt: now.addingTimeInterval(-60)),
            now: now, device: .iPhone)
        #expect(status.headline == "Offline · 3 changes waiting")
        #expect(status.detail == "Your changes are saved on this device.")
        #expect(status.syncNowDisabledReason == "Connect to sync.")
        #expect(status.distinction == .savedLocally)
    }

    @Test("026-FR-023 the Inbox header, lists hub and Settings take the same text from one fixed state")
    func surfacesAgree() {
        let cases: [(SyncSnapshot, SyncStatus, String)] = [
            (snapshot(), .offline(lastSyncedAt: nil), "Offline · 3 changes waiting"),
            (snapshot(online: false), .idle(lastSyncedAt: nil), "Offline · 3 changes waiting"),
            (snapshot(failingFor: 90), .failing(message: "x", referenceID: "ref-1", lastSyncedAt: nil), "Couldn't sync · Retry"),
            (snapshot(pending: 0), .idle(lastSyncedAt: nil), "Synced 1 min ago"),
            (snapshot(), .idle(lastSyncedAt: nil), "Synced 1 min ago · 3 changes waiting"),
        ]
        for (snap, status, expected) in cases {
            // Every surface calls the same function with the same inputs.
            let inbox = WorkspaceSyncStatusPresenter.describe(snapshot: snap, status: status, now: now, device: .iPhone)
            let hub = WorkspaceSyncStatusPresenter.describe(snapshot: snap, status: status, now: now, device: .iPhone)
            let settings = WorkspaceSyncStatusPresenter.describe(snapshot: snap, status: status, now: now, device: .iPhone)
            #expect(inbox.headline == expected)
            #expect(hub.headline == inbox.headline)
            #expect(settings.headline == inbox.headline)
            #expect(settings.detail == inbox.detail)
        }
    }

    @Test("026-FR-023 a failing transport shows its reference ID and the saved line")
    func failingShowsReference() {
        let status = WorkspaceSyncStatusPresenter.describe(
            snapshot: snapshot(), status: .failing(message: "boom", referenceID: "ref-9", lastSyncedAt: nil),
            now: now, device: .iPhone)
        #expect(status.headline == "Couldn't sync · Retry")
        #expect(status.referenceID == "ref-9")
        #expect(status.detail == "Your changes are saved on this device.")
    }

    @Test("026-FR-023 an unavailable transport is a failure; an update-needed store wins")
    func transportUnavailableAndUpdate() {
        let failing = WorkspaceSyncStatusPresenter.describe(
            snapshot: snapshot(), status: .idle(lastSyncedAt: nil), transportUnavailable: true, now: now, device: .iPhone)
        #expect(failing.distinction == .failing)
        let update = WorkspaceSyncStatusPresenter.describe(
            snapshot: snapshot(), status: .offline(lastSyncedAt: nil), updateNeeded: true, now: now, device: .iPhone)
        #expect(update.headline == "Update needed to sync")
    }

    @Test("026-FR-023 no account reads On this iPhone")
    func accountLess() {
        let status = WorkspaceSyncStatusPresenter.describe(
            snapshot: SyncSnapshot(account: .none), status: .localOnly, now: now, device: .iPhone)
        #expect(status.headline == "On this iPhone · Sign in to sync")
    }
}

@Suite("Capture preview hold")
struct CapturePreviewHoldTests {
    private func preview(_ title: String) -> CapturePreview {
        CapturePreview(title: title, project: nil, tags: [], tokens: [], problem: nil)
    }

    @Test("026-FR-023 while a preview loads the last ready one stays, and the fresh one is not read")
    func loadingKeepsLastReady() {
        var hold = CapturePreviewHold()
        hold.record(preview("Rehearsal"), isReady: true)
        hold.record(preview("ignored"), isReady: false)
        var read = false
        let shown = hold.shown(isReady: false) { read = true; return preview("fresh") }
        #expect(shown.title == "Rehearsal")
        #expect(!read)
    }

    @Test("026-FR-023 a ready preview is shown as is, and nothing ready yet shows an empty one")
    func readyAndEmpty() {
        let hold = CapturePreviewHold()
        #expect(hold.shown(isReady: false) { preview("x") } == CapturePreviewHold.empty)
        #expect(hold.shown(isReady: true) { preview("fresh") }.title == "fresh")
    }

    @Test("026-FR-023 only a failed preview has a message, and it keeps the text")
    func failureMessage() {
        #expect(CapturePreviewGate.failureMessage(isFailed: false) == nil)
        #expect(CapturePreviewGate.failureMessage(isFailed: true)?.contains("Your text is kept") == true)
    }
}
