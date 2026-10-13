import Foundation
import Testing

@testable import BrainBuddyCore

/// The draft behind both apps' conflict screens, as it is wired to the runtime: what it submits,
/// what it refuses to offer, what survives a relaunch (spec 026 M-02, D-02).
@Suite("Conflict decision wiring (026-FR-007, 026-FR-010)")
struct ConflictDecisionWiringTests {
    private static func draft(
        _ ids: [String] = ["a", "b"], rules: [String: [String]]? = nil, requiresVersion: Bool = true
    ) -> ConflictDecisionDraft {
        ConflictDecisionDraft(
            dependentIDs: ids, shownRevision: "7", issueID: "issue-1", requiresVersion: requiresVersion,
            retryDependencies: rules)
    }

    @discardableResult
    private static func applied(_ draft: inout ConflictDecisionDraft) throws -> ConflictDecision {
        let decision = draft.apply()
        return try #require(decision)
    }

    @Test("026-FR-007: my saved version keeps my edit, the account's version uses it, deleted keeps it deleted")
    func decisionMapsOntoTheRuntimeOutcome() throws {
        var saved = Self.draft([])
        saved.choose(.saved)
        let keepMine = try Self.applied(&saved)
        #expect(RuntimeIssueResolution(issueID: "issue-1", decision: keepMine).outcome == .keepMine)
        #expect(RuntimeIssueResolution(issueID: "issue-1", decision: keepMine).shownRevision == "7")

        var account = Self.draft([])
        account.choose(.account)
        let useAccount = try Self.applied(&account)
        #expect(RuntimeIssueResolution(issueID: "issue-1", decision: useAccount).outcome == .useAccountVersion)

        var deleted = Self.draft([], requiresVersion: false)
        #expect(deleted.canApply)
        let keepDeleted = try Self.applied(&deleted)
        #expect(keepDeleted.version == nil)
        #expect(RuntimeIssueResolution(issueID: "issue-1", decision: keepDeleted).outcome == .keepDeleted)
    }

    @Test("026-FR-010: every held action lands in exactly one of keep, retry and discard, and discard waits for confirmation")
    func everyHeldActionInExactlyOneList() throws {
        var draft = Self.draft(["a", "b", "c"], rules: ["a": [], "b": [], "c": []])
        draft.choose(.saved)
        draft.setChoice(.reviewAndRetry, for: "a")
        draft.approveRetry(for: "a")
        draft.setChoice(.discard, for: "c")
        #expect(draft.apply() == nil, "an unconfirmed discard is never submitted")
        draft.requestDiscard()
        #expect(draft.apply() == nil, "still waiting on the named confirmation")
        draft.confirmDiscard()
        let decision = try Self.applied(&draft)
        let resolution = RuntimeIssueResolution(issueID: "issue-1", decision: decision)
        #expect(resolution.keepForLater == ["b"] && resolution.retry.map(\.id) == ["a"] && resolution.discard == ["c"])
        #expect(Set(resolution.keepForLater + resolution.retry.map(\.id) + resolution.discard) == ["a", "b", "c"])
    }

    @Test("026-FR-010: a retry the runtime would refuse is not offered: it waits on a held action that is not retried")
    func retryWaitingOnAnotherHeldActionIsNotOffered() {
        var draft = Self.draft(["a", "b"], rules: ["a": [], "b": ["a"]])
        draft.choose(.account)
        #expect(draft.canRetry("a") && !draft.canRetry("b"))
        #expect(draft.retryUnavailableReason(for: "b") != nil && draft.retryUnavailableReason(for: "a") == nil)
        draft.setChoice(.reviewAndRetry, for: "b")
        #expect(draft.choice(for: "b") == .keepForLater, "the unavailable choice is ignored")
        draft.setChoice(.reviewAndRetry, for: "a")
        #expect(draft.canRetry("b"))
        draft.setChoice(.reviewAndRetry, for: "b")
        draft.approveRetry(for: "a")
        draft.approveRetry(for: "b")
        #expect(draft.canApply)
        // Taking the predecessor back out of retry takes its successor with it, and its approval.
        draft.setChoice(.keepForLater, for: "a")
        #expect(draft.choice(for: "b") == .keepForLater && !draft.approvedRetries.contains("b"))
    }

    @Test("026-FR-010: an action that is not a saved issue cannot be retried from here")
    func unknownActionCannotBeRetried() {
        var draft = Self.draft(["a", "ghost"], rules: ["a": []])
        #expect(!draft.canRetry("ghost"))
        draft.setChoice(.reviewAndRetry, for: "ghost")
        #expect(draft.choice(for: "ghost") == .keepForLater)
    }

    @Test("026-FR-007: a record that changed again keeps the draft, clears approvals, and saves nothing")
    func changedAgainOutcome() throws {
        var draft = Self.draft(["a"], rules: ["a": []])
        draft.choose(.saved)
        draft.setChoice(.reviewAndRetry, for: "a")
        draft.approveRetry(for: "a")
        try Self.applied(&draft)
        draft.finish(.changedAgain(RuntimeIssueAccountVersion(revision: "9", isDeleted: false, fields: [:])))
        #expect(draft.phase == .changedAgain && draft.shownRevision == "9")
        #expect(draft.version == nil && draft.approvedRetries.isEmpty && !draft.canApply)
        #expect(draft.choice(for: "a") == .reviewAndRetry, "the choices stay")
        // A second submit is a no-op until the person decides again.
        #expect(draft.apply() == nil)
    }

    @Test("026-FR-007: any other refusal keeps the draft and offers the same decision again; a double submit is ignored")
    func failedOutcomeKeepsTheDraft() throws {
        var draft = Self.draft(["a"])
        draft.choose(.account)
        let first = try Self.applied(&draft)
        #expect(draft.apply() == nil, "a double submit creates no second resolution")
        draft.finish(.failed(.failed(code: "STORE_BUSY")))
        #expect(draft.phase == .saveFailed && draft.version == .account && draft.canApply)
        #expect(draft.apply() == first)
    }

    @Test("026-FR-007: a stored resolution leaves nothing to keep")
    func resolvedOutcome() throws {
        var draft = Self.draft([])
        draft.choose(.saved)
        try Self.applied(&draft)
        draft.finish(.resolved)
        #expect(draft.phase == .saving, "the screen drops the draft; it never becomes editable again")
        #expect(draft.apply() == nil)
    }

    @Test("026-FR-010: only choices are written down; a restored draft submits nothing and discard comes back unconfirmed")
    func persistedDraftIsInertData() throws {
        var draft = Self.draft(["a", "b"], rules: ["a": [], "b": []])
        draft.choose(.saved)
        draft.setChoice(.reviewAndRetry, for: "a")
        draft.approveRetry(for: "a")
        draft.setChoice(.discard, for: "b")
        draft.requestDiscard()
        draft.confirmDiscard()
        #expect(draft.canApply)
        let data = try JSONEncoder().encode(draft)
        let text = String(decoding: data, as: UTF8.self)
        #expect(!text.contains("discardConfirmed") && !text.contains("phase"))

        var fresh = Self.draft(["a", "b"], rules: ["a": [], "b": []])
        fresh.restore(from: try JSONDecoder().decode(ConflictDecisionDraft.self, from: data))
        #expect(fresh.phase == .choosing && fresh.version == .saved)
        #expect(fresh.choice(for: "a") == .reviewAndRetry && fresh.approvedRetries == ["a"])
        #expect(fresh.choice(for: "b") == .discard && !fresh.canApply, "the discard must be confirmed again")
        #expect(fresh.apply() == nil)
    }

    @Test("026-FR-010: a draft saved against another revision of the record returns as changed again; other issues' drafts are ignored")
    func restoreAgainstMovedRecord() throws {
        var saved = Self.draft(["a"])
        saved.choose(.account)
        saved.setChoice(.discard, for: "a")
        var moved = ConflictDecisionDraft(dependentIDs: ["a", "new"], shownRevision: "8", issueID: "issue-1")
        moved.restore(from: saved)
        #expect(moved.phase == .changedAgain && moved.version == nil && moved.shownRevision == "8")
        #expect(moved.choice(for: "a") == .discard && moved.choice(for: "new") == .keepForLater)

        var other = ConflictDecisionDraft(dependentIDs: ["a"], shownRevision: "7", issueID: "issue-2")
        other.restore(from: saved)
        #expect(other.version == nil && other.choice(for: "a") == .keepForLater)
    }

    @Test("026-FR-010: the presenter builds the draft from the issue: retry only for known issues, and what they wait on")
    func presenterBuildsDraft() {
        let primary = RuntimeIssueResolutionTests.issue("cmd-2", dependents: ["cmd-3", "cmd-4", "cmd-5"])
        let first = RuntimeIssueResolutionTests.issue("cmd-3", reason: "BLOCKED_DEPENDENCY", dependsOn: ["cmd-2"])
        let second = RuntimeIssueResolutionTests.issue("cmd-4", reason: "BLOCKED_DEPENDENCY", dependsOn: ["cmd-2", "cmd-3"])
        let account = RuntimeIssueAccountVersion(revision: "5", isDeleted: false, fields: ["title": "Theirs"])
        var draft = RuntimeIssuePresenter.draft(for: primary, among: [primary, first, second], account: account)
        #expect(draft.issueID == primary.id && draft.shownRevision == "5" && draft.requiresVersion)
        #expect(draft.canRetry("cmd-3") && !draft.canRetry("cmd-4") && !draft.canRetry("cmd-5"))
        draft.setChoice(.reviewAndRetry, for: "cmd-3")
        #expect(draft.canRetry("cmd-4"))

        let deleted = RuntimeIssueResolutionTests.issue("cmd-9", reason: "ENTITY_DELETED")
        #expect(!RuntimeIssuePresenter.draft(for: deleted, among: [deleted]).requiresVersion)
        #expect(RuntimeIssuePresenter.draft(for: deleted, among: [deleted]).shownRevision == "1", "no account read: the edited revision")
    }

    @Test("026-FR-010: the recovery card words update-needed, rebuilding and a failed rebuild, and keeps waiting work named")
    func recoveryCard() throws {
        #expect(RuntimeRecoveryCard(RuntimeSyncRecovery(), pendingCount: 0) == nil)
        let update = try #require(RuntimeRecoveryCard(RuntimeSyncRecovery(storeNeedsUpdate: true), pendingCount: 2))
        #expect(update.condition == .updateNeededStore && update.isBlocking)
        #expect(update.title == "Update needed to open tasks" && update.actions == [.updateApp, .tryAgain])
        let rebuilding = try #require(RuntimeRecoveryCard(RuntimeSyncRecovery(rebuild: .rebuilding), pendingCount: 3))
        #expect(rebuilding.detail.hasPrefix("3 changes waiting.") && rebuilding.actions.isEmpty && !rebuilding.isBlocking)
        let failed = try #require(RuntimeRecoveryCard(RuntimeSyncRecovery(rebuild: .failed(referenceID: "ref-9")), pendingCount: 1))
        #expect(failed.actions == [.tryAgain, .copyReference("ref-9")])
        #expect(failed.accessibilityLabel.contains("Reference ID: ref-9") && failed.detail == "Your waiting changes are saved.")
        let noReference = try #require(RuntimeRecoveryCard(RuntimeSyncRecovery(rebuild: .failed(referenceID: nil)), pendingCount: 1))
        #expect(noReference.actions == [.tryAgain])
    }

    @Test("026-FR-010: a retry on another record carries the revision its preview showed, into the runtime resolution")
    func retryCarriesDisplayedRevision() throws {
        let primary = RuntimeIssueResolutionTests.issue("cmd-2", dependents: ["cmd-3", "cmd-4"])
        let other = RuntimeIssueResolutionTests.issue("cmd-3", reason: "BLOCKED_DEPENDENCY", entity: "task-9", dependsOn: ["cmd-2"], revision: "8")
        let same = RuntimeIssueResolutionTests.issue("cmd-4", reason: "BLOCKED_DEPENDENCY", dependsOn: ["cmd-2"], revision: "2")
        var draft = RuntimeIssuePresenter.draft(for: primary, among: [primary, other, same])
        #expect(draft.dependentRevisions == ["cmd-3": "8"], "only another record needs its own revision")
        draft.choose(.account)
        for id in ["cmd-3", "cmd-4"] { draft.setChoice(.reviewAndRetry, for: id); draft.approveRetry(for: id) }
        let decision = try Self.applied(&draft)
        let resolution = RuntimeIssueResolution(issueID: primary.id, decision: decision)
        #expect(resolution.retry == [RetryDependent(id: "cmd-3", shownRevision: "8"), RetryDependent(id: "cmd-4")])
    }
}
