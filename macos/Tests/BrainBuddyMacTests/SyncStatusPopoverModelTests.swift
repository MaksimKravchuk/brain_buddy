import BrainBuddyCore
import Foundation
import Testing

@testable import BrainBuddyMacCore

/// X-02's content (contracts/mac-app-host.md §6, design X-02): its lines in each state, "Sync now"
/// disabled but never hidden, the Tab order, focus on open, focus after Dismiss, and "Discard
/// outcome" with its 5 s Undo.
@Suite("Sync status popover")
struct SyncStatusPopoverModelTests {
    private static let now = TestClock.importTime
    private static let utc: Calendar = {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        return calendar
    }()
    private static let email = SyncSnapshot.Account.linked(email: "alex@example.com")
    private static let reference = "4e5d9a20-0000-4000-8000-000000000001"

    private static func issue(_ n: Int, reference: String? = Self.reference) -> SyncIssue {
        SyncIssue(
            id: UUID(uuidString: "00000000-0000-0000-0000-00000000000\(n)")!,
            command: .createTask(.init(taskID: TaskID("t\(n)"), title: "Order soil \(n)", list: .next)),
            message: "Project “Garden” was archived on another device, so the task was added without a project.",
            referenceID: reference, occurredAt: now
        )
    }

    private static let gardenID = ProjectID("garden")
    private static var stateWithGarden: GTDState {
        var state = GTDState.empty
        state.projects[gardenID] = ProjectRecord(id: gardenID, name: "Garden", createdAt: now)
        return state
    }

    private static func keptOutcome(_ n: Int) -> SyncIssue {
        SyncIssue(
            id: UUID(uuidString: "00000000-0000-0000-0000-00000000010\(n)")!,
            command: .setProjectOutcome(project: gardenID, outcome: "A vegetable bed that feeds us from June to September."),
            message: GTDValidationError.outcomeKept.message, referenceID: nil, occurredAt: now
        )
    }

    private static func content(
        _ snapshot: SyncSnapshot, issues: [SyncIssue] = [], files: MacUpgradeFiles = .none, discarded: Set<UUID> = []
    ) -> SyncPopoverContent {
        SyncPopoverModel.content(
            snapshot: snapshot, issues: issues, state: stateWithGarden, files: files, discarded: discarded, now: now,
            calendar: utc
        )
    }

    @Test("021-FR-016 account-less: one explanation and “Sign in…”, no times, no counts, no Sync now")
    func accountLess() {
        let content = Self.content(SyncSnapshot(account: .none))
        guard case .accountLess(let text)? = content.notice else {
            Issue.record("expected the account-less notice")
            return
        }
        #expect(text.title == "Your tasks are stored on this Mac")
        #expect(content.lastSynced == nil && content.queue == nil && !content.syncNowShown && content.email == nil)
        #expect(content.tabOrder == [.signIn])
        #expect(content.initialFocus == .signIn)
    }

    @Test("021-FR-016 021-FR-006 synced: last sync, waiting, Sync now enabled and focused; Sign out… last")
    func synced() {
        let snapshot = SyncSnapshot(
            account: Self.email, lastSyncedAt: Self.now.addingTimeInterval(-180), pendingCount: 2,
            oldestPendingAt: Self.now.addingTimeInterval(-40)
        )
        let content = Self.content(snapshot)
        #expect(content.lastSynced == "Last synced · Today at 14:31")
        #expect(content.queue == "Waiting to sync · 2 changes · oldest 40 s")
        #expect(content.syncNowShown && content.syncNowEnabled)
        #expect(content.tabOrder == [.syncNow, .signOut])
        #expect(content.initialFocus == .syncNow)
        #expect(content.email == "alex@example.com")
    }

    @Test("021-FR-016 021-FR-001 session ended: Sign in again first and focused; Sync now shown disabled, never hidden")
    func sessionEnded() {
        let content = Self.content(SyncSnapshot(account: Self.email, sessionEnded: true, lastSyncedAt: Self.now))
        #expect(content.syncNowShown && !content.syncNowEnabled)
        #expect(content.tabOrder == [.signInAgain, .signOut], "a disabled Sync now is skipped")
        #expect(content.initialFocus == .signInAgain)
    }

    @Test("021-FR-015 021-FR-016 offline after a failure keeps its time and reference with Copy; Sync now disabled")
    func offlineWithEarlierFailure() {
        let snapshot = SyncSnapshot(
            account: Self.email, isOnline: false, lastSyncedAt: Self.now, failingSince: Self.now.addingTimeInterval(-600),
            lastFailedAttemptAt: Self.now.addingTimeInterval(-60), lastFailureReferenceID: Self.reference
        )
        let content = Self.content(snapshot)
        guard case .offline(let text, let reference)? = content.notice else {
            Issue.record("expected the offline notice")
            return
        }
        #expect(text.footnote == "Last failed 14:33 · Reference ID \(Self.reference)")
        #expect(reference == Self.reference)
        #expect(!content.syncNowEnabled)
        #expect(content.tabOrder == [.offlineCopy, .signOut])
        #expect(content.initialFocus == .offlineCopy, "with Sync now disabled, the first enabled control")
    }

    @Test("021-FR-014 021-FR-015 couldn't sync: the notice's Copy is the attention action and first in focus")
    func failing() {
        let snapshot = SyncSnapshot(
            account: Self.email, lastSyncedAt: Self.now.addingTimeInterval(-1_920),
            failingSince: Self.now.addingTimeInterval(-1_920), lastFailedAttemptAt: Self.now.addingTimeInterval(-60),
            lastFailureReferenceID: Self.reference
        )
        let content = Self.content(snapshot)
        guard case .failing(let text, _)? = content.notice else {
            Issue.record("expected the failing notice")
            return
        }
        #expect(text.title == "Couldn't sync since 14:02")
        #expect(content.tabOrder == [.failingCopy, .syncNow, .signOut])
        #expect(content.initialFocus == .failingCopy)
    }

    @Test("021-FR-003 021-FR-016 the first upload shows its progress line instead of the waiting count")
    func firstUpload() {
        let snapshot = SyncSnapshot(
            account: Self.email, pendingCount: 1_284, oldestPendingAt: Self.now, initialUploadRemaining: 1_284
        )
        #expect(Self.content(snapshot).queue == "Adding your tasks to your account · 1,284 left")
    }

    @Test("021-FR-016 the full Tab order: issues, kept outcome, Sync now, Sign out…, then the three Show in Finder")
    func fullTabOrder() {
        let files = MacUpgradeFiles(
            backup: URL(fileURLWithPath: "/tmp/backup.json"), backupKeptUntil: Self.now.addingTimeInterval(30 * 86_400),
            report: URL(fileURLWithPath: "/tmp/report.txt"), laterFile: URL(fileURLWithPath: "/tmp/local-gtd.json")
        )
        let issues = [Self.issue(1), Self.keptOutcome(1), Self.issue(2, reference: nil)]
        let content = Self.content(
            SyncSnapshot(account: Self.email, lastSyncedAt: Self.now, issueCount: 3), issues: issues, files: files
        )
        #expect(content.issuesHeading == "3 changes couldn't sync")
        #expect(
            content.tabOrder == [
                .issueCopy(issues[0].id), .dismiss(issues[0].id), .copyOutcome(issues[1].id), .discardOutcome(issues[1].id),
                .dismiss(issues[2].id), .syncNow, .signOut, .backupShowInFinder, .reportShowInFinder, .laterFileShowInFinder,
            ]
        )
        #expect(content.backupLine == "Backup from before the update · kept until 5 Nov")
        #expect(content.reportLine == "Some details changed during the update.")
        #expect(content.laterFileLine == "A file from the previous version is on this Mac. It was not added.")
        let kept = content.issues[1]
        #expect(kept.keptOutcome == "A vegetable bed that feeds us from June to September.", "in full")
        #expect(kept.actionAccessibilityLabel == "Discard your outcome for “Garden”")
        #expect(content.issues[0].actionAccessibilityLabel.hasPrefix("Dismiss: Add “Order soil 1”"))
    }

    @Test("021-FR-016 after Dismiss, focus goes to the next issue's Copy, or the previous one's, then Sync now or Sign out…")
    func focusAfterDismiss() {
        let issues = [Self.issue(1), Self.issue(2), Self.issue(3)]
        let snapshot = SyncSnapshot(account: Self.email, lastSyncedAt: Self.now, issueCount: 3)
        let content = Self.content(snapshot, issues: issues)
        #expect(content.focusAfterRemoving(issues[0].id) == .issueCopy(issues[1].id), "the next issue's Copy")
        #expect(content.focusAfterRemoving(issues[2].id) == .issueCopy(issues[1].id), "the previous one's when the last row went")

        let last = Self.content(snapshot, issues: [issues[0]])
        #expect(last.focusAfterRemoving(issues[0].id) == .syncNow)
        let offline = Self.content(
            SyncSnapshot(account: Self.email, isOnline: false, lastSyncedAt: Self.now, issueCount: 1), issues: [issues[0]]
        )
        #expect(offline.focusAfterRemoving(issues[0].id) == .signOut, "Sync now disabled: Sign out…")
    }

    @Test("021-FR-016 long titles are shortened on one line past 60 characters; a kept outcome never is")
    func longTitles() {
        let long = String(repeating: "Call the landlord about the boiler ", count: 4)
        let issue = SyncIssue(
            command: .createTask(.init(taskID: "t", title: long, list: .next)), message: "Why.", occurredAt: Self.now
        )
        let row = Self.content(SyncSnapshot(account: Self.email, issueCount: 1), issues: [issue]).issues[0]
        #expect(row.attempted.count == SyncPopoverModel.titleLimit)
        #expect(row.attempted.hasSuffix("…"))
    }

    @Test("021-FR-015 021-FR-028 Discard outcome: “Outcome discarded · Undo” for 5 s, Undo restores it, then it goes")
    func discardOutcomeWithUndo() {
        var discards = OutcomeDiscards()
        let id = Self.keptOutcome(1).id
        discards.discard(id, at: Self.now)
        let content = Self.content(
            SyncSnapshot(account: Self.email, issueCount: 1), issues: [Self.keptOutcome(1)], discarded: discards.ids
        )
        #expect(content.issues[0].discarded)
        #expect(content.issuesHeading == nil, "nothing else waits")
        #expect(content.tabOrder.first == .undoDiscard(id))
        #expect(discards.nextExpiry == Self.now.addingTimeInterval(5))
        #expect(discards.expired(at: Self.now.addingTimeInterval(4.9)).isEmpty)

        discards.undo(id)
        #expect(discards.ids.isEmpty, "Undo restores the issue")

        discards.discard(id, at: Self.now)
        #expect(discards.expired(at: Self.now.addingTimeInterval(5)) == [id], "after 5 s it goes for good")
        #expect(discards.ids.isEmpty)
    }
}
