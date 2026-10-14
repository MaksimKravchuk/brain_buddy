import Foundation
import Testing

@testable import BrainBuddyCore

/// 026-SC-008, the part a model can prove on the iPhone side: each sync and recovery state maps to
/// the state, words and action that `specs/026-rust-core-sync/design.md` gives it (M-01 status, M-02
/// conflict, M-03 recovery), and every action a person needs there exists in the model, carries a
/// label a screen reader can speak, and is exposed as a control rather than hidden in a gesture.
///
/// What this cannot show, and does not claim: that a representative user completes the three
/// journeys uncoached, that VoiceOver reads the rendered screens, or that the pixels match the
/// design. Those stay in `evidence/apple-ux.md` and `evidence/apple-pilot.md` until a device run.
@Suite("026-SC-008 design state mapping and action reachability (iPhone model)")
struct DesignStateMappingTests {
    private static let now = SyncPresentationTests.now
    private static let calendar = SyncPresentationTests.calendar
    private static let saved = "Your changes are saved on this device."

    private static func status(
        _ snapshot: SyncSnapshot, updateNeeded: Bool = false, failure: TransportFailure? = nil
    ) -> RuntimeSyncStatus {
        RuntimeSyncStatusPresenter.describe(
            snapshot, updateNeeded: updateNeeded, transportFailure: failure, now: now, device: .iPhone, calendar: calendar)
    }

    // MARK: M-01 sync status

    @Test("026-SC-008 M-01: every status state shows the design's words, distinction and action")
    func statusStatesMatchTheDesign() {
        struct Row {
            let design: String
            let snapshot: SyncSnapshot
            var updateNeeded = false
            let distinction: RuntimeSyncStatus.Distinction
            let headline: String
            let action: RuntimeSyncAction
            let disabledReason: String?
        }
        let waiting = SyncSnapshot(
            account: SyncPresentationTests.linked, lastSyncedAt: Self.now.addingTimeInterval(-180), pendingCount: 3,
            oldestPendingAt: Self.now.addingTimeInterval(-120))
        let offline = SyncSnapshot(
            account: SyncPresentationTests.linked, isOnline: false, lastSyncedAt: Self.now, pendingCount: 3,
            oldestPendingAt: Self.now)
        let rows: [Row] = [
            Row(design: "M-01.01", snapshot: SyncPresentationTests.synced(), distinction: .synced,
                headline: "Synced 3 min ago", action: .none, disabledReason: nil),
            Row(design: "M-01.03", snapshot: SyncSnapshot(account: .none), distinction: .localOnly,
                headline: "On this iPhone · Sign in to sync", action: .none, disabledReason: nil),
            Row(design: "M-01.05", snapshot: offline, distinction: .savedLocally,
                headline: "Offline · 3 changes waiting", action: .none, disabledReason: "Connect to sync."),
            Row(design: "M-01.06", snapshot: waiting, distinction: .pending,
                headline: "Synced 3 min ago · 3 changes waiting", action: .none, disabledReason: nil),
            Row(design: "M-01.08", snapshot: SyncPresentationTests.synced { $0.issueCount = 1 }, distinction: .hasIssues,
                headline: "1 change couldn't sync", action: .openIssues, disabledReason: nil),
            Row(design: "M-01.09", snapshot: SyncPresentationTests.synced { $0.sessionEnded = true }, distinction: .signInNeeded,
                headline: "Sign in again to sync", action: .signInAgain, disabledReason: "Sign in again to sync."),
            Row(design: "M-01.10", snapshot: SyncPresentationTests.synced(), updateNeeded: true, distinction: .updateNeeded,
                headline: "Update needed to sync", action: .updateApp, disabledReason: "Update the app to sync again."),
        ]
        for row in rows {
            let result = Self.status(row.snapshot, updateNeeded: row.updateNeeded)
            #expect(result.distinction == row.distinction, "\(row.design) distinction")
            #expect(result.headline == row.headline, "\(row.design) headline")
            #expect(result.action == row.action, "\(row.design) action")
            #expect(result.syncNowDisabledReason == row.disabledReason, "\(row.design) Sync now")
            #expect(result.accessibilityLabel.hasPrefix("Sync status: \(row.headline)"), "\(row.design) label")
        }
    }

    @Test("026-SC-008 M-01.07 a persistent failure reads Couldn't sync, offers Retry and a safe reference ID to copy")
    func persistentFailureOffersRetryAndReference() {
        let result = Self.status(
            SyncPresentationTests.synced(SyncPresentationTests.failingRun))
        #expect(result.distinction == .failing)
        #expect(result.headline == "Couldn't sync · Retry")
        #expect(result.action == .retry)
        #expect(result.referenceID == "ref-4e5d9a20")
        #expect(result.accessibilityLabel.contains("Reference ID: ref-4e5d9a20"))
        #expect(result.detail == Self.saved)
        // The reference is opaque: the label carries it and no task text.
        #expect(!result.accessibilityLabel.contains("Task"))
    }

    @Test("026-SC-008 M-01 offline and waiting say the work is saved here, in words rather than colour")
    func offlineSaysSavedOnThisDevice() {
        let offline = SyncSnapshot(
            account: SyncPresentationTests.linked, isOnline: false, lastSyncedAt: Self.now, pendingCount: 3,
            oldestPendingAt: Self.now)
        let result = Self.status(offline)
        #expect(result.detail == Self.saved)
        #expect(result.accessibilityLabel == "Sync status: Offline · 3 changes waiting. \(Self.saved)")
    }

    @Test("026-SC-008 M-01 every state that needs the person's action exposes that action; calm states expose none")
    func statusActionsAreExposedWhereNeeded() {
        let needing: [(RuntimeSyncStatus, RuntimeSyncAction)] = [
            (Self.status(SyncPresentationTests.synced { $0.issueCount = 2 }), .openIssues),
            (Self.status(SyncPresentationTests.synced { $0.sessionEnded = true }), .signInAgain),
            (Self.status(SyncPresentationTests.synced(SyncPresentationTests.failingRun)), .retry),
            (Self.status(SyncPresentationTests.synced(), updateNeeded: true), .updateApp),
        ]
        for (result, action) in needing {
            #expect(result.action == action)
            #expect(result.needsAttention, "an action-bearing state is announced as needing attention")
            #expect(!result.accessibilityLabel.isEmpty)
        }
        for calm in [SyncPresentationTests.synced(), SyncSnapshot(account: .none)] {
            #expect(Self.status(calm).action == .none)
        }
    }

    @Test("026-SC-008 M-01 update needed outranks every other state, as the design's priority says")
    func updateNeededOutranksOtherStates() {
        let busy = SyncPresentationTests.synced {
            $0.issueCount = 3
            $0.sessionEnded = true
        }
        let result = Self.status(busy, updateNeeded: true)
        #expect(result.distinction == .updateNeeded)
        #expect(result.action == .updateApp)
    }

    // MARK: M-02 conflict

    private static func issue(
        _ reason: String, text: [String: String] = ["title": "Order potting soil"], dependents: [String] = []
    ) -> RustWorkspaceIssue {
        RustWorkspaceIssue(
            id: "issue-1", commandID: "cmd-1", reason: reason, localIntent: Data(), localText: text,
            shownBaseRevision: "7", dependentIDs: dependents, createdAt: Date(timeIntervalSince1970: 0))
    }

    @Test("026-SC-008 M-02 each issue kind shows the design's words and the actions that resolve it")
    func issueKindsMatchTheDesign() {
        let conflict = RuntimeIssuePresenter.card(Self.issue("REVISION_CONFLICT"))
        #expect(conflict.kind == .versionConflict)
        #expect(conflict.title == "Choose a version")
        #expect(conflict.actions == [.chooseVersion, .copySavedEdit, .copyReference])

        let deleted = RuntimeIssuePresenter.card(Self.issue("ENTITY_DELETED"))
        #expect(deleted.kind == .deletedElsewhere)
        #expect(deleted.message == "This item was deleted on another device. Your edit is saved in this issue.")
        #expect(deleted.actions == [.copySavedEdit, .keepItemDeleted, .copyReference])

        let blocked = RuntimeIssuePresenter.card(Self.issue("BLOCKED_DEPENDENCY"))
        #expect(blocked.actions == [.keepForLater, .reviewAndRetry, .discardAction, .copyReference])

        let withLater = RuntimeIssuePresenter.card(Self.issue("REVISION_CONFLICT", dependents: ["a", "b"]))
        #expect(withLater.message.hasSuffix("2 later actions need your decision."))
        #expect(withLater.actions.contains(.reviewDependents))

        let unknown = RuntimeIssuePresenter.card(Self.issue("OUTCOME_UNKNOWN"))
        #expect(unknown.title == "Earlier changes need verification")
        #expect(!unknown.actions.contains(.reviewAndRetry), "an uncertain send is never offered a retry")
    }

    @Test("026-SC-008 M-02 every card has a copyable reference, a spoken label with the saved text, and no hidden action")
    func everyIssueCardIsReachable() {
        let reasons = ["REVISION_CONFLICT", "ENTITY_DELETED", "BLOCKED_DEPENDENCY", "DEPENDENCY_REJECTED", "OUTCOME_UNKNOWN", "VALIDATION_FAILED"]
        for reason in reasons {
            let card = RuntimeIssuePresenter.card(Self.issue(reason))
            #expect(card.actions.last == .copyReference, "\(reason) can always copy its reference")
            #expect(card.referenceID == "issue-1")
            #expect(card.accessibilityLabel.contains("Reference ID: issue-1"), "\(reason)")
            #expect(card.accessibilityLabel.contains("title: Order potting soil"), "\(reason) reads the saved edit")
            #expect(Set(card.actions.map { "\($0)" }).count == card.actions.count, "\(reason) lists no action twice")
        }
        let noText = RuntimeIssuePresenter.card(Self.issue("VALIDATION_FAILED", text: [:]))
        #expect(!noText.actions.contains(.copySavedEdit), "nothing to copy is not offered")
    }

    @Test("026-SC-008 M-02 the decision walks the design's states: no default, saving, failed, changed again, later actions, named discard")
    func decisionStatesMatchTheDesign() throws {
        // M-02.01: a radio choice without a default; Apply stays off until a version is picked.
        var draft = ConflictDecisionDraft(dependentIDs: [], shownRevision: "7", issueID: "issue-1")
        #expect(draft.version == nil && !draft.canApply)
        #expect(draft.title == "Choose a version")
        draft.choose(.saved)
        #expect(draft.canApply)

        // M-02.02: saving; a second submit creates no second resolution.
        #expect(draft.apply() != nil)
        #expect(draft.title == "Saving your choice…" && draft.apply() == nil)

        // M-02.05: a failed save keeps the selection and offers the same decision again.
        draft.saveFailed()
        #expect(draft.title == "Your choice wasn't saved. Try again.")
        #expect(draft.version == .saved && draft.canApply)

        // M-02.08: changed again keeps the draft and requires an explicit apply.
        _ = draft.apply()
        draft.finish(.changedAgain(RuntimeIssueAccountVersion(revision: "9", isDeleted: false, fields: [:])))
        #expect(draft.title == "This task changed again. Review both versions.")
        #expect(draft.shownRevision == "9" && !draft.canApply)

        // M-02.11: later actions start as Keep for later; retry needs approval.
        var later = ConflictDecisionDraft(
            dependentIDs: ["a", "b"], shownRevision: "7", issueID: "issue-1", retryDependencies: ["a": [], "b": []])
        #expect(later.title == "2 later actions need your decision")
        #expect(["a", "b"].allSatisfy { later.choice(for: $0) == .keepForLater })
        later.choose(.account)
        later.setChoice(.reviewAndRetry, for: "a")
        #expect(!later.canApply, "a retry is not applied until its preview is approved")
        later.approveRetry(for: "a")
        #expect(later.canApply)

        // M-02.12: discard is named, lists what goes, and Cancel keeps every choice.
        later.setChoice(.discard, for: "b")
        later.requestDiscard()
        #expect(later.phase == .confirmingDiscard)
        #expect(later.discardPrompt == "Discard these 1 saved action?")
        #expect(later.discardConfirmTitle == "Discard 1 action")
        #expect(ConflictDecisionDraft.discardExplanation == "They will not be sent. Other saved actions will be kept.")
        later.cancelDiscard()
        #expect(later.choice(for: "b") == .discard && later.version == .account)
    }

    @Test("026-SC-008 M-02.09 a deleted item needs no version and offers only keep-deleted, never a recreate")
    func deletedElsewhereOffersKeepDeletedOnly() throws {
        var draft = ConflictDecisionDraft(dependentIDs: [], shownRevision: "7", issueID: "t", requiresVersion: false)
        #expect(draft.canApply)
        let applied = draft.apply()
        let decision = try #require(applied)
        #expect(RuntimeIssueResolution(issueID: "t", decision: decision).outcome == .keepDeleted)
    }

    // MARK: M-03 recovery

    @Test("026-SC-008 M-03 every recovery state shows the design's title, detail and actions")
    func recoveryStatesMatchTheDesign() throws {
        func card(_ recovery: RuntimeSyncRecovery, pending: Int = 3) throws -> RuntimeRecoveryCard {
            try #require(RuntimeRecoveryCard(recovery, pendingCount: pending))
        }
        let unsupportedStore = try card(RuntimeSyncRecovery(storeNeedsUpdate: true))
        #expect(unsupportedStore.title == "Update needed to open tasks")  // M-03.09
        #expect(unsupportedStore.actions == [.updateApp, .tryAgain] && unsupportedStore.isBlocking)

        let rebuilding = try card(RuntimeSyncRecovery(rebuild: .rebuilding))
        #expect(rebuilding.title == "Rebuilding synced copy…")  // M-03.02
        #expect(rebuilding.detail == "3 changes waiting. Your waiting changes and saved conflicts will be kept.")
        #expect(rebuilding.actions.isEmpty && !rebuilding.isBlocking)

        let failed = try card(RuntimeSyncRecovery(rebuild: .failed(referenceID: "ref-9")))
        #expect(failed.title == "Couldn't rebuild the synced copy.")  // M-03.05
        #expect(failed.detail == "Your waiting changes are saved.")
        #expect(failed.actions == [.tryAgain, .copyReference("ref-9")])

        let uncertain = try card(RuntimeSyncRecovery(epoch: .closed))
        #expect(uncertain.title == "Earlier changes need verification")  // M-03.10
        #expect(uncertain.detail == "Your earlier store and waiting changes are kept while sync checks what reached your account.")
        #expect(uncertain.actions == [.tryAgain])

        #expect(RuntimeRecoveryCard(RuntimeSyncRecovery(), pendingCount: 0) == nil, "nothing to recover shows no card")
    }

    @Test("026-SC-008 M-03 every recovery card speaks its state and names the work it keeps; blocking states carry an action")
    func recoveryCardsAreSpeakableAndActionable() throws {
        let recoveries = [
            RuntimeSyncRecovery(storeNeedsUpdate: true), RuntimeSyncRecovery(rebuild: .rebuilding),
            RuntimeSyncRecovery(rebuild: .failed(referenceID: "ref-9")), RuntimeSyncRecovery(epoch: .closed),
        ]
        for recovery in recoveries {
            let card = try #require(RuntimeRecoveryCard(recovery, pendingCount: 2))
            #expect(card.accessibilityLabel.hasPrefix(card.title))
            #expect(card.accessibilityLabel.contains(card.detail))
            if card.isBlocking { #expect(card.actions.contains(.updateApp), "a blocked person can act") }
        }
        // The failure's reference is in the spoken label and in the Copy action, and nowhere else.
        let failed = try #require(RuntimeRecoveryCard(RuntimeSyncRecovery(rebuild: .failed(referenceID: "ref-9")), pendingCount: 1))
        #expect(failed.accessibilityLabel.hasSuffix("Reference ID: ref-9"))
        #expect(failed.actions.contains(.copyReference("ref-9")))
    }
}
