import Foundation
import Testing

@testable import BrainBuddyCore

@Suite("Runtime issue resolution planning (026-FR-007, 026-FR-010)")
struct RuntimeIssueResolutionTests {
    static let t0 = Date(timeIntervalSince1970: 1_790_000_000)

    static func issue(
        _ command: String, reason: String = "REVISION_CONFLICT", entity: String = "task-1",
        preconditions: [[String: Any]] = [], dependsOn: [String] = [], dependents: [String] = [],
        text: [String: String] = ["title": "Mine"], revision: String? = "1"
    ) -> RustWorkspaceIssue {
        let intent: [String: Any] = ["entity_id": entity, "preconditions": preconditions, "depends_on": dependsOn]
        return RustWorkspaceIssue(
            id: "issue_\(command)", commandID: command, reason: reason,
            localIntent: try! JSONSerialization.data(withJSONObject: intent, options: [.sortedKeys]),
            localText: text, shownBaseRevision: revision, dependentIDs: dependents, createdAt: t0)
    }

    static func revision(_ id: String, _ revision: String) -> [String: Any] {
        ["entity_type": "task", "entity_id": id, "edit_revision": revision]
    }

    static func after(_ command: String, entity: String) -> [String: Any] {
        ["after_command": ["command_id": command, "entity_type": "task", "entity_id": entity]]
    }

    static func ids() -> () -> String {
        var next = 0
        return { next += 1; return "new-\(next)" }
    }

    static func preconditions(_ replacement: RustIssueReplacement) -> [[String: Any]] {
        (try? JSONSerialization.jsonObject(with: replacement.preconditions)) as? [[String: Any]] ?? []
    }

    @Test("026-FR-007: keeping my version queues a new command against the revision the person was shown")
    func keepMineUsesShownRevision() throws {
        let primary = Self.issue("cmd-2", preconditions: [Self.revision("task-1", "1")])
        let request = try RuntimeIssueResolutionPlanner.plan(
            RuntimeIssueResolution(issueID: primary.id, outcome: .keepMine, shownRevision: "4"),
            among: [primary], makeCommandID: Self.ids())
        guard case .keepMine(let replacement) = request.choice else { Issue.record("expected keepMine"); return }
        #expect(replacement.commandID == "new-1")
        #expect(Self.preconditions(replacement).first?["edit_revision"] as? String == "4")
        #expect(request.dependents.isEmpty)
    }

    @Test("026-FR-007: the account's version and keep-deleted dismiss the saved edit without a replacement")
    func useCurrentHasNoReplacement() throws {
        let primary = Self.issue("cmd-2", reason: "ENTITY_DELETED")
        for outcome in [RuntimeIssueResolution.Outcome.useAccountVersion, .keepDeleted] {
            let request = try RuntimeIssueResolutionPlanner.plan(
                RuntimeIssueResolution(issueID: primary.id, outcome: outcome, shownRevision: nil),
                among: [primary], makeCommandID: Self.ids())
            #expect(request.choice == .useCurrent)
        }
    }

    @Test("026-FR-010: every held action needs a choice; omission, repeats and strangers are refused")
    func everyHeldActionDecided() {
        let primary = Self.issue("cmd-2", dependents: ["cmd-3", "cmd-4"])
        func plan(_ resolution: RuntimeIssueResolution) throws -> RustIssueResolveRequest {
            try RuntimeIssueResolutionPlanner.plan(resolution, among: [primary], makeCommandID: Self.ids())
        }
        func decision(keep: [String] = [], retry: [RetryDependent] = [], discard: [String] = []) -> RuntimeIssueResolution {
            RuntimeIssueResolution(
                issueID: primary.id, outcome: .useAccountVersion, shownRevision: "2", keepForLater: keep,
                retry: retry, discard: discard)
        }
        #expect(throws: RuntimeIssueResolutionError.incompleteDecision) { try plan(decision(keep: ["cmd-3"])) }
        #expect(throws: RuntimeIssueResolutionError.incompleteDecision) {
            try plan(decision(keep: ["cmd-3", "cmd-3"], discard: ["cmd-4"]))
        }
        #expect(throws: RuntimeIssueResolutionError.incompleteDecision) {
            try plan(decision(keep: ["cmd-3", "cmd-4", "cmd-9"]))
        }
        #expect(throws: RuntimeIssueResolutionError.unknownIssue) {
            try RuntimeIssueResolutionPlanner.plan(
                RuntimeIssueResolution(issueID: "issue_other", outcome: .keepMine, shownRevision: nil),
                among: [primary], makeCommandID: Self.ids())
        }
    }

    @Test("026-FR-010: keep, retry and discard are carried through; discard only goes out confirmed")
    func dependentChoices() throws {
        let primary = Self.issue("cmd-2", dependents: ["cmd-3", "cmd-4", "cmd-5"])
        let retried = Self.issue(
            "cmd-3", reason: "BLOCKED_DEPENDENCY",
            preconditions: [Self.revision("task-1", "2")], dependsOn: ["cmd-2"], text: ["details": "Later"])
        let request = try RuntimeIssueResolutionPlanner.plan(
            RuntimeIssueResolution(
                issueID: primary.id, outcome: .keepMine, shownRevision: "3", keepForLater: ["cmd-4"],
                retry: [RetryDependent(id: "cmd-3")], discard: ["cmd-5"]),
            among: [primary, retried], makeCommandID: Self.ids())
        #expect(request.dependents.map(\.commandID) == ["cmd-3", "cmd-4", "cmd-5"])
        guard case .retry(let replacement) = request.dependents[0].choice else { Issue.record("expected retry"); return }
        // It built on the edit that is queued again, so it now follows the new command.
        #expect(replacement.commandID == "new-2")
        #expect(replacement.dependsOn == ["new-1"])
        let after = Self.preconditions(replacement).first?["after_command"] as? [String: Any]
        #expect(after?["command_id"] as? String == "new-1")
        #expect(after?["entity_id"] as? String == "task-1")
        #expect(request.dependents[1].choice == .keepForLater)
        #expect(request.dependents[2].choice == .discard(confirmed: true))
    }

    @Test("026-FR-010: a retry after choosing the account's version is approved against the shown revision and drops the wait on the dismissed edit")
    func retryAfterAccountVersion() throws {
        let primary = Self.issue("cmd-2", dependents: ["cmd-3"])
        let retried = Self.issue(
            "cmd-3", reason: "BLOCKED_DEPENDENCY", preconditions: [Self.revision("task-1", "2")],
            dependsOn: ["cmd-2", "cmd-1"])
        let request = try RuntimeIssueResolutionPlanner.plan(
            RuntimeIssueResolution(
                issueID: primary.id, outcome: .useAccountVersion, shownRevision: "7", retry: [RetryDependent(id: "cmd-3")]),
            among: [primary, retried], makeCommandID: Self.ids())
        guard case .retry(let replacement) = request.dependents[0].choice else { Issue.record("expected retry"); return }
        #expect(Self.preconditions(replacement).first?["edit_revision"] as? String == "7")
        #expect(replacement.dependsOn == ["cmd-1"])
    }

    @Test("026-FR-007: runtime refusal codes map to typed errors")
    func errorCodes() {
        #expect(RuntimeIssueResolutionError(code: "REVISION_CONFLICT") == .changedAgain)
        #expect(RuntimeIssueResolutionError(code: "ISSUE_ALREADY_RESOLVED") == .alreadyResolved)
        #expect(RuntimeIssueResolutionError(code: "ISSUE_NOT_RESOLVABLE") == .notResolvable)
        #expect(RuntimeIssueResolutionError(code: "ENTITY_DELETED") == .itemDeleted)
        #expect(RuntimeIssueResolutionError(code: "DISCARD_NOT_CONFIRMED") == .incompleteDecision)
        #expect(RuntimeIssueResolutionError(code: "CANCELLED") == .failed(code: "CANCELLED"))
    }

    @Test("026-FR-010: recovery reads the store's epoch and link, and unknown values stay visible")
    func recoveryValues() {
        let closed = RuntimeSyncRecovery(epochState: "closed", accountLinkState: "linked")
        #expect(closed.epochClosed && closed.needsAttention && closed.accountLink == .linked)
        let strange = RuntimeSyncRecovery(epochState: "future_state", accountLinkState: "other")
        #expect(strange.epoch == .unknown && strange.accountLink == .unknown && !strange.needsAttention)
        var rebuilding = RuntimeSyncRecovery()
        rebuilding.rebuild = .rebuilding
        #expect(rebuilding.needsAttention)
    }

    @Test("026-FR-010: a retried action on another entity is approved against the revision its own preview showed")
    func retryOnAnotherEntityUsesItsDisplayedRevision() throws {
        let primary = Self.issue("cmd-2", dependents: ["cmd-3", "cmd-4"])
        let other = Self.issue(
            "cmd-3", reason: "BLOCKED_DEPENDENCY", entity: "task-9", preconditions: [Self.revision("task-9", "5")],
            dependsOn: ["cmd-2"])
        let same = Self.issue(
            "cmd-4", reason: "BLOCKED_DEPENDENCY", preconditions: [Self.revision("task-1", "2")], dependsOn: ["cmd-2"])
        let request = try RuntimeIssueResolutionPlanner.plan(
            RuntimeIssueResolution(
                issueID: primary.id, outcome: .keepMine, shownRevision: "3",
                retry: [RetryDependent(id: "cmd-3", shownRevision: "8"), RetryDependent(id: "cmd-4")]),
            among: [primary, other, same], makeCommandID: Self.ids())
        guard case .retry(let onOther) = request.dependents[0].choice,
            case .retry(let onSame) = request.dependents[1].choice
        else { Issue.record("expected retries"); return }
        let otherShown = Self.preconditions(onOther).first
        #expect(otherShown?["edit_revision"] as? String == "8")
        #expect(otherShown?["entity_id"] as? String == "task-9")
        // On the issue's own record it still follows the kept edit's replacement.
        #expect((Self.preconditions(onSame).first?["after_command"] as? [String: Any])?["command_id"] as? String == "new-1")
        // Without a displayed revision the action's own precondition is untouched.
        let untouched = try RuntimeIssueResolutionPlanner.plan(
            RuntimeIssueResolution(
                issueID: primary.id, outcome: .keepMine, shownRevision: "3",
                keepForLater: ["cmd-4"], retry: [RetryDependent(id: "cmd-3")]),
            among: [primary, other, same], makeCommandID: Self.ids())
        guard case .retry(let kept) = untouched.dependents[0].choice else { Issue.record("expected retry"); return }
        #expect(Self.preconditions(kept).first?["edit_revision"] as? String == "5")
    }

    @Test("026-FR-007: a repeated Apply reuses the exact submitted request, minted IDs included")
    func ledgerReusesSubmittedRequest() throws {
        let primary = Self.issue("cmd-2", preconditions: [Self.revision("task-1", "1")])
        let resolution = RuntimeIssueResolution(issueID: primary.id, outcome: .keepMine, shownRevision: "4")
        var ledger = RuntimeIssueResolutionLedger()
        let first = try ledger.request(for: resolution, among: [primary], makeCommandID: Self.ids())
        // The issue has left the list since (it was resolved, the answer was lost): same request.
        let again = try ledger.request(for: resolution, among: [], makeCommandID: Self.ids())
        #expect(first == again)
        guard case .keepMine(let replacement) = again.choice else { Issue.record("expected keepMine"); return }
        #expect(replacement.commandID == "new-1")
        // Uncertain failures keep it; proof that nothing was stored drops it.
        ledger.settle(issueID: primary.id, error: .failed(code: "CANCELLED"))
        #expect(try ledger.request(for: resolution, among: [], makeCommandID: Self.ids()) == first)
        ledger.settle(issueID: primary.id, error: .changedAgain)
        #expect(throws: RuntimeIssueResolutionError.unknownIssue) {
            try ledger.request(for: resolution, among: [], makeCommandID: Self.ids())
        }
        // A different decision for the same issue is planned anew.
        let other = RuntimeIssueResolution(issueID: primary.id, outcome: .keepMine, shownRevision: "5")
        let replanned = try ledger.request(for: other, among: [primary], makeCommandID: Self.ids())
        guard case .keepMine(let fresh) = replanned.choice else { Issue.record("expected keepMine"); return }
        #expect(Self.preconditions(fresh).first?["edit_revision"] as? String == "5")
    }
}
