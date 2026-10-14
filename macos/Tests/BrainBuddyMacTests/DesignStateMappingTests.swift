import BrainBuddyCore
import Foundation
import Testing

@testable import BrainBuddyMacCore

/// 026-SC-008, the part a model can prove on the Mac: each sync and recovery state maps to the state,
/// words and control that `specs/026-rust-core-sync/design.md` gives it (D-01 status, D-02 conflict,
/// D-03 recovery), and each recovery action is reachable: it is a control in the popover's Tab order
/// (the keyboard path), it can take first focus where it must, and the row it belongs to has a spoken
/// label.
///
/// Not claimed here: that a representative user finishes the three journeys uncoached, that VoiceOver
/// reads the rendered popover, or that the layout matches the design. Those stay in
/// `evidence/mac-ux.md` until a real-Mac run. The button titles themselves are SwiftUI view code
/// (`SyncStatusPopover`), outside this package, and are checked in that run.
@Suite("026-SC-008 design state mapping and action reachability (Mac model)")
struct DesignStateMappingTests {
    private static let now = TestClock.importTime
    private static let email = SyncSnapshot.Account.linked(email: "alex@example.com")

    private static func line(_ snapshot: SyncSnapshot, updateNeeded: Bool = false) -> SyncStatusDescription {
        var model = SyncStatusLineModel(snapshot: snapshot, now: now)
        if updateNeeded { model.setUpdateNeeded(true, at: now) }
        return model.description
    }

    private static func content(
        _ snapshot: SyncSnapshot, issues: [SyncRuntimeIssue] = [], recovery: SyncRecoveryCondition? = nil
    ) -> SyncPopoverContent {
        SyncPopoverModel.content(
            snapshot: snapshot, issues: [], state: .empty, files: .none, runtimeIssues: issues, recovery: recovery,
            now: now)
    }

    private static func conflict(dependents: [String] = []) -> SyncRuntimeIssue {
        SyncRuntimeIssue(
            id: "issue-1", commandID: "cmd-1", reason: "REVISION_CONFLICT", summary: "Rename “Order soil”",
            savedEdit: "Order potting soil", shownBaseRevision: "rev-7", dependentIDs: dependents)
    }

    // MARK: D-01 sync status

    @Test("026-SC-008 D-01: every status state shows the design's words, with a spoken label that repeats them")
    func statusStatesMatchTheDesign() {
        let failing = SyncSnapshot(
            account: Self.email, lastSyncedAt: Self.now, failingSince: Self.now.addingTimeInterval(-SyncTiming.failureSurfacesAfter),
            lastFailedAttemptAt: Self.now, lastFailureReferenceID: "demo-026-sync-01")
        let rows: [(design: String, snapshot: SyncSnapshot, text: String)] = [
            ("D-01.01", SyncSnapshot(account: Self.email, lastSyncedAt: Self.now), "Synced just now"),
            ("D-01.03", SyncSnapshot(account: .none), "On this Mac · Sign in to sync"),
            (
                "D-01.05",
                SyncSnapshot(account: Self.email, isOnline: false, lastSyncedAt: Self.now, pendingCount: 3, oldestPendingAt: Self.now),
                "Offline · 3 changes waiting"
            ),
            (
                "D-01.06",
                SyncSnapshot(
                    account: Self.email, lastSyncedAt: Self.now.addingTimeInterval(-180), pendingCount: 3,
                    oldestPendingAt: Self.now.addingTimeInterval(-120)),
                "Synced 3 min ago · 3 changes waiting"
            ),
            ("D-01.07", failing, "Couldn't sync · Retry"),
            ("D-01.08", SyncSnapshot(account: Self.email, lastSyncedAt: Self.now, issueCount: 1), "1 change couldn't sync"),
            ("D-01.09", SyncSnapshot(account: Self.email, sessionEnded: true, lastSyncedAt: Self.now), "Sign in again to sync"),
        ]
        for row in rows {
            let description = Self.line(row.snapshot)
            #expect(description.text == row.text, "\(row.design) words")
            #expect(description.accessibilityLabel == "Sync status: \(row.text). Show details", "\(row.design) label")
        }
        let update = Self.line(SyncSnapshot(account: Self.email, lastSyncedAt: Self.now), updateNeeded: true)
        #expect(update.text == "Update needed to sync")  // D-01.10
        #expect(update.accessibilityLabel == "Sync status: Update needed to sync. Show details")
    }

    @Test("026-SC-008 D-01 the states that need the person put their control in the Tab order and, where urgent, first focus")
    func statusControlsAreKeyboardReachable() {
        let session = Self.content(SyncSnapshot(account: Self.email, sessionEnded: true, lastSyncedAt: Self.now))
        #expect(session.tabOrder.contains(.signInAgain) && session.initialFocus == .signInAgain)  // D-01.09

        let accountLess = Self.content(SyncSnapshot(account: .none))
        #expect(accountLess.tabOrder == [.signIn])  // D-01.03

        let failing = Self.content(
            SyncSnapshot(
                account: Self.email, lastSyncedAt: Self.now,
                failingSince: Self.now.addingTimeInterval(-SyncTiming.failureSurfacesAfter), lastFailedAttemptAt: Self.now,
                lastFailureReferenceID: "demo-026-sync-01"))
        #expect(failing.tabOrder.contains(.failingCopy) && failing.tabOrder.contains(.syncNow))  // D-01.07 Copy + Retry
        #expect(failing.initialFocus == .failingCopy)

        let rejected = Self.content(
            SyncSnapshot(account: Self.email, lastSyncedAt: Self.now, issueCount: 1), issues: [Self.conflict()])
        #expect(rejected.tabOrder.contains(.openConflict("issue-1")))  // D-01.08 Review
        #expect(rejected.tabOrder.contains(.runtimeCopy("issue-1")))

        let quiet = Self.content(SyncSnapshot(account: Self.email, lastSyncedAt: Self.now))
        #expect(quiet.tabOrder == [.syncNow, .signOut] && quiet.initialFocus == .syncNow)  // D-01.01
    }

    @Test("026-SC-008 D-01 each runtime issue row reads its action aloud and offers a reference to copy")
    func runtimeIssueRowsAreLabelled() {
        let content = Self.content(
            SyncSnapshot(account: Self.email, lastSyncedAt: Self.now, issueCount: 1),
            issues: [Self.conflict(dependents: ["later-1"]), SyncRuntimeIssue(id: "later-1", commandID: "c2", reason: "DEPENDENCY_REJECTED", summary: "Move task")])
        #expect(content.runtimeIssues.count == 1)
        let row = content.runtimeIssues[0]
        #expect(row.actionAccessibilityLabel == "Review: Rename “Order soil”")
        #expect(row.referenceID == "issue-1")
        #expect(row.laterActions == 1)
    }

    // MARK: D-02 conflict

    @Test("026-SC-008 D-02 the conflict detail walks the design's states in the design's words")
    func conflictStatesMatchTheDesign() throws {
        func blocked() -> [SyncBlockedAction] {
            [SyncBlockedAction(id: "later-1", summary: "Move task 1 to Garden"), SyncBlockedAction(id: "later-2", summary: "Move task 2 to Garden")]
        }
        // D-02.01 default: two versions, no default selection, Apply disabled.
        var model = SyncConflictModel(issue: Self.conflict(), accountVersion: "Order soil")
        #expect(model.versionLabels.map(\.1) == ["Your saved edit", "Current account version"])
        #expect(model.selected == nil && !model.applyEnabled && model.apply() == nil)
        // D-02.02 saving, D-02.05 failed save keeps both versions and the selection.
        model.select(.yours)
        let first = model.apply()
        _ = try #require(first)
        #expect(model.statusLine == "Saving your choice…" && model.apply() == nil)
        model.saveFailed()
        #expect(model.statusLine == "Your choice wasn't saved. Try again." && model.selected == .yours)
        // D-02.07 offline: stored and shown as waiting.
        _ = model.apply()
        model.savedWhileOffline()
        #expect(model.statusLine == "Your choice is saved and waiting to sync." && !model.isEditable)
        // D-02.08 changed again keeps the draft and requires an explicit apply.
        var again = SyncConflictModel(issue: Self.conflict(), accountVersion: "Order soil")
        again.select(.yours)
        again.accountChanged(revision: "rev-8", accountVersion: "Order soil v2")
        #expect(again.statusLine == "This task changed again. Review both versions." && again.yourEdit == "Order potting soil")
        // D-02.09 deleted elsewhere: the edit is preserved and the only outcome is keeping it deleted.
        let deleted = SyncRuntimeIssue(
            id: "tag-1", commandID: "c", reason: "ENTITY_DELETED", summary: "Rename tag", savedEdit: "errands-2",
            shownBaseRevision: "rev-2")
        var gone = SyncConflictModel(issue: deleted, accountVersion: nil)
        #expect(gone.title == "Deleted on another device" && gone.yourEdit == "errands-2")
        let keptDeleted = gone.apply()
        #expect(try #require(keptDeleted).outcome == .keepDeleted)
        // D-02.11 later actions default to Keep for later; D-02.12 discard is named and Cancel is first focus.
        var held = SyncConflictModel(issue: Self.conflict(dependents: ["later-1", "later-2"]), accountVersion: "x", blocked: blocked())
        #expect(held.blockedHeading == "2 later actions need your decision")
        #expect(held.actions.allSatisfy { $0.choice == .keepForLater && !$0.retryApproved })
        held.select(.account)
        held.setChoice(.discard, for: "later-1")
        held.setChoice(.discard, for: "later-2")
        #expect(held.apply() == nil && held.phase == .confirmingDiscard)
        #expect(held.confirmDiscardTitle == "Discard these 2 saved actions?")
        #expect(held.confirmDiscardButton == "Discard 2 actions")
        #expect(held.confirmDiscardDetail == "They will not be sent. Other saved actions will be kept.")
        #expect(held.discardSummaries == ["Move task 1 to Garden", "Move task 2 to Garden"])
        #expect(held.initialFocus == .cancelDiscard)
    }

    @Test("026-SC-008 D-02 every state of the detail starts focus on something the sheet renders")
    func conflictInitialFocusIsAlwaysRendered() {
        let plain = SyncConflictModel(issue: Self.conflict(), accountVersion: "x")
        #expect(plain.initialFocus == .title)
        let held = SyncConflictModel(
            issue: Self.conflict(dependents: ["later-1"]), accountVersion: "x",
            blocked: [SyncBlockedAction(id: "later-1", summary: "Move task 1")])
        #expect(held.initialFocus == .blockedHeading)
    }

    // MARK: D-03 recovery

    private static let allConditions: [SyncRecoveryCondition] = [
        .updateNeededSync, .updateNeededStore, .rebuilding, .rebuildFailed(referenceID: "ref-9"), .importFailed,
        .migrationUncertain, .interrupted,
    ]

    @Test("026-SC-008 D-03 every recovery state shows the design's title and actions, and names the work it keeps")
    func recoveryStatesMatchTheDesign() {
        let expected: [(design: String, condition: SyncRecoveryCondition, title: String, actions: [SyncRecoveryAction])] = [
            ("D-03.08", .updateNeededSync, "Update needed to sync", [.updateApp]),
            ("D-03.09", .updateNeededStore, "Update needed to open tasks", [.updateApp, .tryAgain, .exportSavedData]),
            ("D-03.02", .rebuilding, "Rebuilding synced copy…", []),
            ("D-03.05", .rebuildFailed(referenceID: "ref-9"), "Couldn't rebuild the synced copy.", [.tryAgain, .copyReference("ref-9")]),
            ("D-03.06", .importFailed, "Couldn't import earlier data", [.openImportReport, .tryAgain]),
            ("D-03.10", .migrationUncertain, "Earlier changes need verification", [.tryAgain]),
            ("D-03.07", .interrupted, "Connect to finish recovery", []),
        ]
        #expect(expected.map(\.condition) == Self.allConditions, "every recovery condition is in the table")
        for row in expected {
            let content = SyncRecoveryContent(row.condition, pendingCount: 3)
            #expect(content.title == row.title, "\(row.design) title")
            #expect(content.actions == row.actions, "\(row.design) actions")
            #expect(!content.detail.isEmpty, "\(row.design) explains itself")
        }
        // Waiting work is always named as kept, or as saved, in the states that interrupt sync.
        for condition in [SyncRecoveryCondition.updateNeededSync, .rebuilding, .rebuildFailed(referenceID: nil), .migrationUncertain, .interrupted] {
            let detail = SyncRecoveryContent(condition, pendingCount: 3).detail
            #expect(detail.contains("kept") || detail.contains("saved") || detail.contains("stay"), "\(condition) names what is kept")
        }
    }

    @Test("026-SC-008 D-03 every recovery action is a control in the popover's Tab order, in the order the card lists them")
    func recoveryActionsAreKeyboardReachable() {
        for condition in Self.allConditions {
            let content = Self.content(SyncSnapshot(account: Self.email, lastSyncedAt: Self.now), recovery: condition)
            let recovery = content.recovery
            #expect(recovery?.condition == condition)
            let actions = recovery?.actions ?? []
            let reachable = content.tabOrder.compactMap { control -> SyncRecoveryAction? in
                if case .recovery(let action) = control { return action }
                return nil
            }
            #expect(reachable == actions, "\(condition): every action has a Tab stop, none extra")
        }
    }

    @Test("026-SC-008 D-03 a blocking recovery takes first focus on its first action, which is Update app")
    func blockingRecoveryTakesFocus() {
        for condition in [SyncRecoveryCondition.updateNeededSync, .updateNeededStore] {
            let content = Self.content(SyncSnapshot(account: Self.email, lastSyncedAt: Self.now), recovery: condition)
            #expect(content.recovery?.condition.isBlocking == true)
            #expect(content.initialFocus == .recovery(.updateApp))
            #expect(content.tabOrder.first == .recovery(.updateApp), "recovery outranks the other controls")
        }
        for condition in [SyncRecoveryCondition.rebuilding, .interrupted, .migrationUncertain] {
            let content = Self.content(SyncSnapshot(account: Self.email, lastSyncedAt: Self.now), recovery: condition)
            #expect(content.recovery?.condition.isBlocking == false)
            #expect(content.initialFocus == .syncNow, "a calm recovery does not steal focus")
        }
    }

    @Test("026-SC-008 D-03 a failed rebuild's reference is a copyable control and carries no task content")
    func recoveryReferenceIsCopyable() {
        let content = SyncRecoveryContent(.rebuildFailed(referenceID: "ref-9"), pendingCount: 2)
        #expect(content.referenceID == "ref-9")
        #expect(content.actions.contains(.copyReference("ref-9")))
        #expect(!content.title.contains("ref-9") && !content.detail.contains("ref-9"))
        #expect(SyncRecoveryContent(.rebuildFailed(referenceID: nil), pendingCount: 2).actions == [.tryAgain])
    }

    @Test("026-SC-008 D-01 existing status thresholds hold with the 026 states present")
    func existingThresholdsArePreserved() {
        #expect(SyncTiming.failureSurfacesAfter == 60)
        // Not yet 60 s of failure: still the quiet row. At 60 s: Couldn't sync.
        let before = SyncSnapshot(
            account: Self.email, lastSyncedAt: Self.now, failingSince: Self.now.addingTimeInterval(-59), lastFailedAttemptAt: Self.now)
        #expect(Self.line(before).text == "Synced just now")
        let at = SyncSnapshot(
            account: Self.email, lastSyncedAt: Self.now, failingSince: Self.now.addingTimeInterval(-60), lastFailedAttemptAt: Self.now)
        #expect(Self.line(at).text == "Couldn't sync · Retry")
    }
}
