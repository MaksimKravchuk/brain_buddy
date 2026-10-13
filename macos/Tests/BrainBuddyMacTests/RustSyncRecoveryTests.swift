import BrainBuddyCore
import Foundation
import Testing

@testable import BrainBuddyMacCore

/// Spec 026 D-01/D-02/D-03 on the Mac: typed runtime issues in the popover, the conflict detail's
/// state machine (both versions, deleted elsewhere, blocked later actions, named discard), the
/// recovery states, and "Update needed to sync" without moving any existing threshold.
@Suite("Rust sync conflict and recovery")
struct RustSyncRecoveryTests {
    private static let now = TestClock.importTime
    private static let email = SyncSnapshot.Account.linked(email: "alex@example.com")

    private static func conflictIssue(dependents: [String] = []) -> SyncRuntimeIssue {
        SyncRuntimeIssue(
            id: "issue-1", commandID: "cmd-1", reason: "REVISION_CONFLICT", summary: "Rename “Order soil”",
            savedEdit: "Order potting soil", shownBaseRevision: "rev-7", dependentIDs: dependents
        )
    }

    private static func later(_ n: Int) -> SyncRuntimeIssue {
        SyncRuntimeIssue(
            id: "later-\(n)", commandID: "cmd-l\(n)", reason: "DEPENDENCY_REJECTED", summary: "Move task \(n) to Garden",
            shownBaseRevision: "rev-\(n)"
        )
    }

    private static func blocked() -> [SyncBlockedAction] {
        [SyncBlockedAction(id: "later-1", summary: "Move task 1 to Garden"), SyncBlockedAction(id: "later-2", summary: "Move task 2 to Garden")]
    }

    private static func content(
        issues: [SyncRuntimeIssue] = [], recovery: SyncRecoveryCondition? = nil, snapshot: SyncSnapshot? = nil
    ) -> SyncPopoverContent {
        SyncPopoverModel.content(
            snapshot: snapshot ?? SyncSnapshot(account: email, lastSyncedAt: now), issues: [], state: .empty,
            files: .none, runtimeIssues: issues, recovery: recovery, now: now
        )
    }

    @Test("026-FR-007 reasons map to conflict, deleted-elsewhere, blocked and other, keeping the ids")
    func classifiesReasons() {
        #expect(SyncRuntimeIssueKind(reason: "REVISION_CONFLICT") == .versionConflict)
        #expect(SyncRuntimeIssueKind(reason: "ENTITY_DELETED") == .deletedElsewhere)
        #expect(SyncRuntimeIssueKind(reason: "DEPENDENCY_REJECTED") == .dependencyRejected)
        #expect(SyncRuntimeIssueKind(reason: "validation_failed") == .rejected)
        #expect(Self.conflictIssue().referenceID == "issue-1")
    }

    @Test("026-FR-007 the popover lists runtime issues with a safe copyable reference and a Review control")
    func popoverListsRuntimeIssues() {
        let content = Self.content(issues: [Self.conflictIssue(dependents: ["later-1", "later-2"]), Self.later(1), Self.later(2)])
        #expect(content.issuesHeading == "1 change couldn't sync")
        #expect(content.runtimeIssues.count == 1)
        #expect(content.runtimeIssues[0].laterActions == 2)
        #expect(content.tabOrder.contains(.runtimeCopy("issue-1")))
        #expect(content.tabOrder.contains(.openConflict("issue-1")))
        let copy = content.tabOrder.firstIndex(of: .runtimeCopy("issue-1"))!
        #expect(copy < content.tabOrder.firstIndex(of: .openConflict("issue-1"))!)
        #expect(content.tabOrder.firstIndex(of: .openConflict("issue-1"))! < content.tabOrder.firstIndex(of: .syncNow)!)
    }

    @Test("026-FR-010 without runtime issues the popover content is exactly what it was")
    func noRuntimeIssuesNoChange() {
        let content = Self.content()
        #expect(content.runtimeIssues.isEmpty)
        #expect(content.recovery == nil)
        #expect(content.issuesHeading == nil)
        #expect(content.tabOrder == [.syncNow, .signOut])
    }

    @Test("026-FR-007 version choice: no default, Apply disabled until a version is selected")
    func versionChoiceHasNoDefault() throws {
        var model = SyncConflictModel(issue: Self.conflictIssue(), accountVersion: "Order soil (account)")
        #expect(model.selected == nil)
        #expect(!model.applyEnabled)
        #expect(model.apply() == nil)
        model.select(.account)
        #expect(model.applyEnabled)
        let applied = model.apply()
        let resolution = try #require(applied)
        #expect(resolution.outcome == .version(.account))
        #expect(resolution.shownRevision == "rev-7")
        #expect(model.phase == .saving)
        #expect(model.statusLine == "Saving your choice…")
        // Resubmission while saving creates no second resolution.
        #expect(model.apply() == nil)
    }

    @Test("026-FR-007 both versions are shown; your saved edit is kept in full")
    func bothVersionsShown() {
        let model = SyncConflictModel(issue: Self.conflictIssue(), accountVersion: "Order soil")
        #expect(model.versionLabels.map(\.1) == ["Your saved edit", "Current account version"])
        #expect(model.yourEdit == "Order potting soil")
        #expect(model.accountVersion == "Order soil")
    }

    @Test("026-FR-007 a failed save keeps both versions and the selection")
    func failedSaveKeepsSelection() {
        var model = SyncConflictModel(issue: Self.conflictIssue(), accountVersion: "Order soil")
        model.select(.yours)
        _ = model.apply()
        model.saveFailed()
        #expect(model.statusLine == "Your choice wasn't saved. Try again.")
        #expect(model.selected == .yours)
        #expect(model.applyEnabled)
    }

    @Test("026-FR-010 a choice made offline is shown as waiting and cannot be edited")
    func offlineChoiceWaits() {
        var model = SyncConflictModel(issue: Self.conflictIssue(), accountVersion: "Order soil")
        model.select(.yours)
        _ = model.apply()
        model.savedWhileOffline()
        #expect(model.statusLine == "Your choice is saved and waiting to sync.")
        #expect(!model.isEditable)
    }

    @Test("026-FR-007 changed again: draft kept, approvals cleared, explicit apply required")
    func changedAgainClearsApprovals() {
        var model = SyncConflictModel(issue: Self.conflictIssue(), accountVersion: "Order soil", blocked: Self.blocked())
        model.select(.yours)
        model.setChoice(.reviewAndRetry, for: "later-1")
        model.approveRetry("later-1")
        #expect(model.applyEnabled)
        model.accountChanged(revision: "rev-8", accountVersion: "Order soil v2")
        #expect(model.statusLine == "This task changed again. Review both versions.")
        #expect(model.selected == .yours)
        #expect(model.yourEdit == "Order potting soil")
        #expect(model.shownRevision == "rev-8")
        #expect(!model.actions[0].retryApproved)
        #expect(!model.applyEnabled)
        model.approveRetry("later-1")
        #expect(model.applyEnabled)
        // The same revision again is not a change.
        var same = model
        same.accountChanged(revision: "rev-8", accountVersion: "Order soil v2")
        #expect(same == model)
    }

    @Test("026-FR-007 blocked later actions: Keep for later is the default and nothing is dropped")
    func blockedActionsPreserved() throws {
        var model = SyncConflictModel(issue: Self.conflictIssue(dependents: ["later-1", "later-2"]), accountVersion: "x", blocked: Self.blocked())
        #expect(model.blockedHeading == "2 later actions need your decision")
        #expect(model.actions.allSatisfy { $0.choice == .keepForLater && !$0.retryApproved })
        model.select(.account)
        let applied = model.apply()
        let resolution = try #require(applied)
        #expect(resolution.keep == ["later-1", "later-2"])
        #expect(resolution.retry.isEmpty && resolution.discard.isEmpty)
    }

    @Test("026-FR-007 review and retry needs an explicit approval; changing the choice clears it")
    func retryNeedsExplicitApproval() throws {
        var model = SyncConflictModel(issue: Self.conflictIssue(), accountVersion: "x", blocked: Self.blocked())
        model.select(.account)
        model.setChoice(.reviewAndRetry, for: "later-1")
        #expect(!model.applyEnabled)
        model.approveRetry("later-2")  // not a retry choice: ignored
        #expect(!model.actions[1].retryApproved)
        model.approveRetry("later-1")
        #expect(model.applyEnabled)
        model.setChoice(.keepForLater, for: "later-1")
        model.setChoice(.reviewAndRetry, for: "later-1")
        #expect(!model.actions[0].retryApproved)
        model.approveRetry("later-1")
        let applied = model.apply()
        let resolution = try #require(applied)
        #expect(resolution.retry == ["later-1"])
        #expect(resolution.keep == ["later-2"])
    }

    @Test("026-FR-007 discard asks for the named confirmation; Cancel keeps every choice")
    func discardRequiresNamedConfirmation() throws {
        var model = SyncConflictModel(issue: Self.conflictIssue(), accountVersion: "x", blocked: Self.blocked())
        model.select(.account)
        model.setChoice(.discard, for: "later-1")
        model.setChoice(.discard, for: "later-2")
        #expect(model.apply() == nil)
        #expect(model.phase == .confirmingDiscard)
        #expect(model.confirmDiscardTitle == "Discard these 2 saved actions?")
        #expect(model.confirmDiscardButton == "Discard 2 actions")
        #expect(model.discardSummaries == ["Move task 1 to Garden", "Move task 2 to Garden"])
        #expect(model.confirmDiscardDetail == "They will not be sent. Other saved actions will be kept.")
        model.cancelDiscard()
        #expect(model.phase == .choosing)
        #expect(model.actions.allSatisfy { $0.choice == .discard })
        #expect(model.apply() == nil)
        let applied = model.confirmDiscard()
        let resolution = try #require(applied)
        #expect(resolution.discard == ["later-1", "later-2"])
        // Confirming outside the confirmation does nothing.
        var other = SyncConflictModel(issue: Self.conflictIssue(), accountVersion: "x", blocked: Self.blocked())
        other.select(.account)
        other.setChoice(.discard, for: "later-1")
        #expect(other.confirmDiscard() == nil)
    }

    @Test("026-FR-010 interruption: the draft restores on relaunch and never submits or pre-confirms a discard")
    func draftRestoresWithoutSubmitting() throws {
        var model = SyncConflictModel(issue: Self.conflictIssue(), accountVersion: "x", blocked: Self.blocked())
        model.select(.yours)
        model.setChoice(.reviewAndRetry, for: "later-1")
        model.approveRetry("later-1")
        model.setChoice(.discard, for: "later-2")
        _ = model.apply()
        #expect(model.phase == .confirmingDiscard)
        let data = try JSONEncoder().encode(model.draft)

        var fresh = SyncConflictModel(issue: Self.conflictIssue(), accountVersion: "x", blocked: Self.blocked())
        fresh.restore(try JSONDecoder().decode(SyncConflictDraft.self, from: data))
        #expect(fresh.phase == .choosing)
        #expect(fresh.selected == .yours)
        #expect(fresh.actions[0].choice == .reviewAndRetry && fresh.actions[0].retryApproved)
        #expect(fresh.actions[1].choice == .discard)
        // A draft for another issue is ignored.
        var wrong = SyncConflictModel(issue: SyncRuntimeIssue(id: "other", commandID: "c", reason: "x", summary: "s"), accountVersion: nil)
        wrong.restore(model.draft)
        #expect(wrong.selected == nil)
    }

    @Test("026-FR-008 deleted elsewhere: edit preserved, Keep item deleted needs no version and revives nothing")
    func deletedElsewhere() throws {
        let issue = SyncRuntimeIssue(
            id: "tag-1", commandID: "c", reason: "ENTITY_DELETED", summary: "Rename tag", savedEdit: "errands-2",
            shownBaseRevision: "rev-2"
        )
        var model = SyncConflictModel(issue: issue, accountVersion: nil)
        #expect(model.yourEdit == "errands-2")
        #expect(model.applyEnabled)
        let applied = model.apply()
        let resolution = try #require(applied)
        #expect(resolution.outcome == .keepDeleted)
        #expect(resolution.shownRevision == "rev-2")
    }

    @Test("026-FR-023 recovery: update needed outranks and takes first focus; actions are the design's")
    func recoveryStates() {
        let sync = Self.content(recovery: .updateNeededSync)
        #expect(sync.recovery?.title == "Update needed to sync")
        #expect(sync.recovery?.detail == "Your saved tasks and waiting changes stay on this device.")
        #expect(sync.initialFocus == .recovery(.updateApp))
        #expect(sync.tabOrder.first == .recovery(.updateApp))

        let store = Self.content(recovery: .updateNeededStore).recovery
        #expect(store?.title == "Update needed to open tasks")
        #expect(store?.actions == [.updateApp, .tryAgain, .exportSavedData])

        let failed = SyncRecoveryContent(.rebuildFailed(referenceID: "ref-9"), pendingCount: 3)
        #expect(failed.title == "Couldn't rebuild the synced copy.")
        #expect(failed.detail == "Your waiting changes are saved.")
        #expect(failed.actions == [.tryAgain, .copyReference("ref-9")])

        #expect(SyncRecoveryContent(.rebuilding, pendingCount: 3).detail.hasPrefix("3 changes waiting."))
        #expect(SyncRecoveryContent(.importFailed, pendingCount: 0).detail.contains("unchanged"))
        #expect(SyncRecoveryContent(.migrationUncertain, pendingCount: 0).title == "Earlier changes need verification")
        #expect(SyncRecoveryContent(.interrupted, pendingCount: 2).title == "Connect to finish recovery")
    }

    @Test("026-FR-011 session ended still reads Sign in again and keeps its place when no recovery applies")
    func authStateUnchanged() {
        let ended = Self.content(snapshot: SyncSnapshot(account: Self.email, sessionEnded: true, lastSyncedAt: Self.now))
        #expect(ended.initialFocus == .signInAgain)
        #expect(ended.recovery == nil)
    }

    @Test("026-FR-012 the status line says Update needed to sync above other states and announces once")
    func statusLineUpdateNeeded() {
        let start = Self.now
        let snapshot = SyncSnapshot(account: Self.email, lastSyncedAt: start)
        var line = SyncStatusLineModel(snapshot: snapshot, now: start)
        #expect(line.description.text == "Synced just now")
        #expect(line.announcementCount == 0)

        line.setUpdateNeeded(true, at: start)
        #expect(line.description.text == "Update needed to sync")
        #expect(line.description.tone == .attention)
        #expect(line.description.syncNowEnabled == false)
        #expect(line.description.trailingActionTitle == nil)
        #expect(line.description.accessibilityLabel == "Sync status: Update needed to sync. Show details")
        #expect(line.announcementCount == 1)
        #expect(line.takeAnnouncement() == "Update needed to sync")

        // Staying in it, or a refresh, says nothing more.
        line.update(snapshot, at: start.addingTimeInterval(5))
        line.setUpdateNeeded(true, at: start.addingTimeInterval(6))
        #expect(line.announcementCount == 1)

        line.setUpdateNeeded(false, at: start.addingTimeInterval(7))
        #expect(line.description.text == "Synced just now")
        #expect(line.announcementCount == 1)
    }

    @Test("026-FR-012 update needed does not hide account-less and moves no existing threshold")
    func updateNeededKeepsThresholds() {
        let start = Self.now
        var accountLess = SyncStatusLineModel(snapshot: SyncSnapshot(account: .none), now: start)
        accountLess.setUpdateNeeded(true, at: start)
        #expect(accountLess.description.text == "On this Mac · Sign in to sync")

        // Failing after 60 s still reads Couldn't sync when update is not needed.
        let failing = SyncSnapshot(
            account: Self.email, lastSyncedAt: start, failingSince: start,
            lastFailedAttemptAt: start.addingTimeInterval(SyncTiming.failureSurfacesAfter)
        )
        let line = SyncStatusLineModel(snapshot: failing, now: start.addingTimeInterval(SyncTiming.failureSurfacesAfter))
        #expect(line.description.text == "Couldn't sync · Retry")
    }
}
