import Foundation
import Testing

@testable import BrainBuddyCore

@Suite("Sync status description and copy")
struct SyncPresentationTests {
    static let calendar: Calendar = {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        return calendar
    }()

    static func date(_ y: Int, _ m: Int, _ d: Int, _ h: Int = 0, _ min: Int = 0, _ s: Double = 0) -> Date {
        calendar.date(from: DateComponents(year: y, month: m, day: d, hour: h, minute: min))!.addingTimeInterval(s)
    }

    /// Thursday 8 October 2026, 14:40 UTC.
    static let now = date(2026, 10, 8, 14, 40)
    static let linked = SyncSnapshot.Account.linked(email: "ana@example.com")

    /// Linked, online, synced 3 minutes ago, nothing waiting.
    static func synced(_ change: (inout SyncSnapshot) -> Void = { _ in }) -> SyncSnapshot {
        var snapshot = SyncSnapshot(account: linked, lastSyncedAt: now.addingTimeInterval(-180))
        change(&snapshot)
        return snapshot
    }

    static func describe(
        _ snapshot: SyncSnapshot, device: DeviceKind = .mac, at now: Date = SyncPresentationTests.now
    ) -> SyncStatusDescription {
        SyncStatusDescriber.describe(snapshot, now: now, device: device, calendar: calendar)
    }

    static func text(_ snapshot: SyncSnapshot, device: DeviceKind = .mac) -> String {
        describe(snapshot, device: device).text
    }

    /// The failing run of the catalogue examples: since 14:02, last tried 14:35.
    static func failingRun(_ snapshot: inout SyncSnapshot) {
        snapshot.failingSince = date(2026, 10, 8, 14, 2)
        snapshot.lastFailedAttemptAt = date(2026, 10, 8, 14, 35)
        snapshot.lastFailureReferenceID = "ref-4e5d9a20"
    }

    // MARK: Rows and precedence

    @Test("021-FR-012 every row of the status table, for the Mac and the iPhone")
    func everyRow() {
        for (device, noun) in [(DeviceKind.mac, "Mac"), (.iPhone, "iPhone")] {
            let rows: [(SyncSnapshot, SyncLineState, String)] = [
                (SyncSnapshot(account: .none), .accountLess, "On this \(noun) · Sign in to sync"),
                (Self.synced { $0.sessionEnded = true }, .sessionEnded, "Sign in again to sync"),
                (Self.synced { $0.issueCount = 1 }, .rejected, "1 change couldn't sync"),
                (Self.synced { $0.issueCount = 1_284 }, .rejected, "1,284 changes couldn't sync"),
                (Self.synced(Self.failingRun), .failing, "Couldn't sync · Retry"),
                (Self.synced { $0.isOnline = false }, .offline, "Offline"),
                (SyncSnapshot(account: Self.linked), .notSyncedYet, "Not synced yet"),
                (Self.synced(), .synced, "Synced 3 min ago"),
            ]
            for (snapshot, state, text) in rows {
                let description = Self.describe(snapshot, device: device)
                #expect(description.state == state)
                #expect(description.text == text)
            }
        }
    }

    @Test("021-FR-012 021-FR-014 each pair of rows gives the earlier one; a failure while offline reads as offline")
    func precedence() {
        let conditions: [(SyncLineState, (inout SyncSnapshot) -> Void)] = [
            (.accountLess, { $0.account = .none }),
            (.sessionEnded, { $0.sessionEnded = true }),
            (.rejected, { $0.issueCount = 2 }),
            (.failing, { Self.failingRun(&$0); $0.isOnline = true }),
            (.offline, { $0.isOnline = false }),
            (.notSyncedYet, { $0.lastSyncedAt = nil }),
            (.synced, { _ in }),
        ]
        for (i, first) in conditions.enumerated() {
            for second in conditions[(i + 1)...] {
                var snapshot = Self.synced()
                first.1(&snapshot)
                second.1(&snapshot)
                // The pair that cannot hold together: a failure while offline reads as offline.
                let expected = (first.0 == .failing && second.0 == .offline) ? SyncLineState.offline : first.0
                #expect(Self.describe(snapshot).state == expected, "\(first.0) with \(second.0)")
            }
        }
    }

    @Test("021-FR-014 offline hides the failure without clearing it, and coming back online shows it at once")
    func failingThenOffline() {
        var snapshot = SyncSnapshot(
            account: Self.linked, lastSyncedAt: Self.now, pendingCount: 3, oldestPendingAt: Self.now.addingTimeInterval(-120))
        Self.failingRun(&snapshot)
        #expect(Self.describe(snapshot).state == .failing)
        snapshot.isOnline = false
        #expect(Self.text(snapshot) == "Offline · 3 changes waiting")
        #expect(Self.describe(snapshot).trailingActionTitle == nil)
        snapshot.isOnline = true
        #expect(Self.describe(snapshot).state == .failing)
    }

    @Test("021-FR-012 offline with none, one and two changes waiting")
    func offlineCounts() {
        for (count, expected) in [(0, "Offline"), (1, "Offline · 1 change waiting"), (2, "Offline · 2 changes waiting")] {
            let snapshot = SyncSnapshot(
                account: Self.linked, isOnline: false, lastSyncedAt: Self.now, pendingCount: count,
                oldestPendingAt: Self.now)
            #expect(Self.text(snapshot) == expected)
        }
    }

    // MARK: Thresholds

    @Test("021-FR-014 failing only once the attempt at 60 s has failed, also after a relaunch")
    func failureSurfacesAfterSixtySeconds() throws {
        let since = Self.date(2026, 10, 8, 14, 2, 0.123456)
        for (gap, expected) in [(59.999, SyncLineState.synced), (60, .failing), (61, .failing), (0, .synced)] {
            var metadata = SyncMetadata(lastPullAt: Self.now)
            metadata.failingSince = since
            metadata.lastFailedAttemptAt = since.addingTimeInterval(gap)
            metadata.lastFailureReferenceID = "ref-1"
            let decoded = try JSONDecoder().decode(SyncMetadata.self, from: JSONEncoder().encode(metadata))
            let snapshot = Self.synced {
                $0.failingSince = decoded.failingSince
                $0.lastFailedAttemptAt = decoded.lastFailedAttemptAt
                $0.lastFailureReferenceID = decoded.lastFailureReferenceID
            }
            #expect(Self.describe(snapshot).state == expected, "gap \(gap)")
        }
        #expect(try JSONDecoder().decode(SyncMetadata.self, from: Data(#"{"lastPullAt":0}"#.utf8)).failingSince == nil)
    }

    @Test("021-FR-012 the waiting suffix shows after 10 s and is measured from when the change became sendable")
    func waitingSuffix() {
        for (wait, expected) in [(0.0, "Synced 3 min ago"), (10, "Synced 3 min ago"), (10.001, "Synced 3 min ago · 2 changes waiting")] {
            let snapshot = SyncSnapshot(
                account: Self.linked, lastSyncedAt: Self.now.addingTimeInterval(-180), pendingCount: 2,
                oldestPendingAt: Self.now.addingTimeInterval(-wait))
            #expect(Self.text(snapshot) == expected, "waited \(wait)")
        }
        // Issued 213 days ago, but sendable only since the account was linked 5 s ago.
        let linkedMoments = SyncSnapshot(
            account: Self.linked, lastSyncedAt: Self.now, pendingCount: 1_284,
            oldestPendingAt: Self.now.addingTimeInterval(-5))
        #expect(Self.text(linkedMoments) == "Synced just now")
        let single = SyncSnapshot(
            account: Self.linked, lastSyncedAt: Self.now, pendingCount: 1, oldestPendingAt: Self.now.addingTimeInterval(-11))
        #expect(Self.text(single) == "Synced just now · 1 change waiting")
    }

    @Test("021-FR-012 021-FR-016 the first upload reads Not synced yet and Adding your tasks, not an age")
    func firstUpload() {
        let snapshot = SyncSnapshot(
            account: Self.linked, lastSyncedAt: Self.now, pendingCount: 1_300,
            oldestPendingAt: Self.now.addingTimeInterval(-3_600), initialUploadRemaining: 1_284)
        #expect(Self.describe(snapshot).state == .notSyncedYet)
        #expect(SyncCopy.popoverQueue(snapshot, now: Self.now) == "Adding your tasks to your account · 1,284 left")
        let drained = SyncSnapshot(
            account: Self.linked, lastSyncedAt: Self.now, pendingCount: 16,
            oldestPendingAt: Self.now.addingTimeInterval(-40))
        #expect(SyncCopy.popoverQueue(drained, now: Self.now) == "Waiting to sync · 16 changes · oldest 40 s")
    }

    @Test("021-FR-012 the relative time of the last sync, at every boundary")
    func relativeLadder() {
        let cases: [(now: Date, last: Date, expected: String)] = [
            (Self.now, Self.now.addingTimeInterval(-59), "Synced just now"),
            (Self.now, Self.now.addingTimeInterval(-60), "Synced 1 min ago"),
            (Self.now, Self.now.addingTimeInterval(-3_599), "Synced 59 min ago"),
            (Self.now, Self.now.addingTimeInterval(-3_600), "Synced 1 h ago"),
            (Self.now, Self.date(2026, 10, 8, 0, 0), "Synced 14 h ago"),
            (Self.now, Self.now.addingTimeInterval(120), "Synced just now"),
            (Self.date(2026, 10, 9, 0, 0), Self.date(2026, 10, 8, 23, 59), "Synced 1 min ago"),
            (Self.date(2026, 10, 9, 0, 0), Self.date(2026, 10, 8, 22, 59), "Synced yesterday"),
            (Self.now, Self.date(2026, 10, 7, 9, 0), "Synced yesterday"),
            (Self.now, Self.date(2026, 10, 6, 23, 0), "Synced 2 days ago"),
            (Self.now, Self.date(2026, 10, 2, 9, 0), "Synced 6 days ago"),
            (Self.now, Self.date(2026, 10, 1, 9, 0), "Synced on 1 Oct"),
            (Self.now, Self.date(2026, 9, 28, 9, 0), "Synced on 28 Sep"),
            (Self.date(2027, 1, 5, 9, 0), Self.date(2026, 12, 20, 9, 0), "Synced on 20 Dec 2026"),
        ]
        for (now, last, expected) in cases {
            let snapshot = SyncSnapshot(account: Self.linked, lastSyncedAt: last)
            #expect(Self.describe(snapshot, at: now).text == expected, "\(last) from \(now)")
        }
    }

    @Test("021-FR-019 021-FR-006 Sync now is off exactly where no sync can run, and never because one is running")
    func syncNowEnabled() {
        let states: [(SyncSnapshot, Bool)] = [
            (SyncSnapshot(account: .none), false),
            (Self.synced { $0.sessionEnded = true }, false),
            (Self.synced { $0.isOnline = false }, false),
            (Self.synced { $0.issueCount = 1 }, true),
            (Self.synced(Self.failingRun), true),
            (SyncSnapshot(account: Self.linked), true),
            (Self.synced(), true),
        ]
        for (snapshot, expected) in states {
            for syncing in [false, true] {
                var running = snapshot
                running.isSyncing = syncing
                #expect(Self.describe(running).syncNowEnabled == expected)
            }
        }
    }

    @Test("021-FR-012 the snapshot holds to data-model E6 whatever it is given")
    func snapshotValidation() {
        let oldest = Self.now.addingTimeInterval(-60)
        let negative = SyncSnapshot(account: Self.linked, pendingCount: -4, oldestPendingAt: oldest, initialUploadRemaining: 9)
        #expect(negative.pendingCount == 0)
        #expect(negative.oldestPendingAt == nil, "no age without a change")
        #expect(negative.initialUploadRemaining == 0)
        let oversized = SyncSnapshot(account: Self.linked, pendingCount: 3, oldestPendingAt: oldest, initialUploadRemaining: 9)
        #expect(oversized.pendingCount == 3)
        #expect(oversized.oldestPendingAt == oldest)
        #expect(oversized.initialUploadRemaining == 3, "the first upload is part of the queue")
        let accountLess = SyncSnapshot(account: .none, pendingCount: 3, oldestPendingAt: oldest, initialUploadRemaining: 2)
        #expect(accountLess.pendingCount == 0, "account-less, the outbox is the data and nothing waits")
        #expect(accountLess.oldestPendingAt == nil)
        #expect(accountLess.initialUploadRemaining == 0)
    }

    // MARK: Words around the line

    @Test("021-FR-012 021-FR-015 the line's actions, glyphs, accessibility name, tooltip and last try")
    func lineDetails() {
        let accountLess = Self.describe(SyncSnapshot(account: .none))
        #expect(accountLess.leading == "On this Mac")
        #expect(accountLess.trailingActionTitle == "Sign in to sync")
        #expect(accountLess.action == .signIn)
        #expect(accountLess.tooltip == "Your tasks are stored on this Mac. Click for details.")
        #expect(Self.describe(SyncSnapshot(account: .none), device: .iPhone).tooltip == "Your tasks are stored on this iPhone. Click for details.")

        let ended = Self.describe(Self.synced { $0.sessionEnded = true })
        #expect(ended.tone == .attention)
        #expect(ended.glyph == .sessionEnded)
        #expect(ended.action == .signInAgain)
        #expect(ended.announceOnEntry)
        #expect(ended.tooltip == "Your session ended. Sign in again to keep syncing.")
        #expect(ended.accessibilityLabel == "Sync status: Sign in again to sync. Show details")

        let rejected = Self.describe(Self.synced { $0.issueCount = 2 })
        #expect(rejected.glyph == .warning)
        #expect(rejected.action == .showIssues)
        #expect(rejected.tooltip == "2 changes couldn't sync. Click for details.")
        #expect(Self.describe(Self.synced { $0.issueCount = 1 }).tooltip == "1 change couldn't sync. Click for details.")

        let failing = Self.describe(Self.synced(Self.failingRun))
        #expect(failing.leading == "Couldn't sync")
        #expect(failing.trailingActionTitle == "Retry")
        #expect(failing.action == .retry)
        #expect(failing.glyph == .warning)
        #expect(failing.lastTriedText == "Last tried 14:35")
        #expect(
            failing.tooltip
                == "Couldn't reach Brain Buddy since 14:02. Last tried 14:35. It keeps trying. Reference ID ref-4e5d9a20")

        let synced = Self.describe(Self.synced { $0.isSyncing = true })
        #expect(synced.tone == .calm)
        #expect(synced.glyph == .none)
        #expect(synced.action == .none)
        #expect(!synced.announceOnEntry)
        #expect(synced.lastTriedText == nil)
        #expect(synced.text == "Synced 3 min ago", "a running sync never changes the words")
        #expect(synced.tooltip == "Last synced today at 14:37. Click for details.")
        let older = SyncSnapshot(account: Self.linked, lastSyncedAt: Self.date(2026, 10, 7, 9, 5))
        #expect(Self.describe(older).tooltip == "Last synced yesterday at 09:05. Click for details.")
        let oldest = SyncSnapshot(account: Self.linked, lastSyncedAt: Self.date(2026, 9, 28, 9, 5))
        #expect(Self.describe(oldest).tooltip == "Last synced on 28 Sep at 09:05. Click for details.")
        #expect(Self.describe(SyncSnapshot(account: Self.linked)).tooltip == "Not synced yet. Click for details.")
        #expect(Self.describe(Self.synced { $0.isOnline = false }).tooltip == "Last synced today at 14:37. Click for details.")
    }

    @Test("021-FR-015 021-SC-004 a failure shows its reference id and the time of the last try")
    func failureCarriesItsReferenceID() {
        let snapshot = Self.synced(Self.failingRun)
        #expect(Self.describe(snapshot).tooltip.hasSuffix("Reference ID ref-4e5d9a20"))
        let popover = SyncCopy.popoverFailing(snapshot, now: Self.now, device: .mac, calendar: Self.calendar)
        #expect(popover?.footnote == "Last tried 14:35 · Reference ID ref-4e5d9a20")
        let days = Self.synced {
            $0.failingSince = Self.date(2026, 10, 3, 9, 0)
            $0.lastFailedAttemptAt = Self.date(2026, 10, 8, 14, 35)
        }
        #expect(SyncCopy.popoverFailing(days, now: Self.now, device: .mac, calendar: Self.calendar)?.title == "Couldn't sync since Sat 3 Oct")
        #expect(SyncCopy.popoverFailing(Self.synced(), now: Self.now, device: .mac, calendar: Self.calendar) == nil)
    }

    @Test("021-FR-016 the popover's sentences, word for word, for both devices")
    func popoverCopy() {
        let calendar = Self.calendar
        let at = Self.date(2026, 10, 8, 14, 31)
        #expect(SyncCopy.popoverLastSynced(at, now: Self.now, calendar: calendar) == "Last synced · Today at 14:31")
        #expect(SyncCopy.popoverLastSynced(Self.date(2026, 10, 7, 9, 0), now: Self.now, calendar: calendar) == "Last synced · Yesterday at 09:00")
        #expect(SyncCopy.popoverWaitingNothing == "Waiting to sync · Nothing")
        #expect(SyncCopy.popoverWaiting(count: 2, oldest: 40) == "Waiting to sync · 2 changes · oldest 40 s")
        #expect(SyncCopy.popoverWaiting(count: 1, oldest: 3 * 86_400) == "Waiting to sync · 1 change · oldest 3 days")
        #expect(SyncCopy.popoverQueue(Self.synced(), now: Self.now) == "Waiting to sync · Nothing")
        #expect(SyncCopy.popoverLaterFile == "A file from the previous version is on this Mac. It was not added.")
        #expect(SyncCopy.popoverImportAdjusted == "Some details changed during the update.")
        #expect(SyncCopy.popoverFirstLoadEmpty == "Your tasks are still arriving.")
        for (device, noun) in [(DeviceKind.mac, "Mac"), (.iPhone, "iPhone")] {
            #expect(
                SyncCopy.popoverOffline(Self.synced { $0.isOnline = false }, now: Self.now, device: device, calendar: calendar)
                    == SyncCopyText(title: "You're offline. Changes are saved on this \(noun) and sync when you're back online."))
            let offlineAfterFailure = SyncCopy.popoverOffline(
                Self.synced { Self.failingRun(&$0); $0.isOnline = false }, now: Self.now, device: device, calendar: calendar)
            #expect(offlineAfterFailure.footnote == "Last failed 14:35 · Reference ID ref-4e5d9a20")
            #expect(
                SyncCopy.popoverFailing(Self.synced(Self.failingRun), now: Self.now, device: device, calendar: calendar)
                    == SyncCopyText(
                        title: "Couldn't sync since 14:02",
                        detail: "Brain Buddy didn't answer. Your changes are safe on this \(noun), and it keeps trying.",
                        footnote: "Last tried 14:35 · Reference ID ref-4e5d9a20"))
            #expect(
                SyncCopy.popoverSessionEnded(device: device)
                    == SyncCopyText(
                        title: "Your session ended",
                        detail: "Sign in again to keep syncing. Your changes stay on this \(noun) until then."))
            let accountLess = SyncCopy.popoverAccountLess(device: device)
            #expect(accountLess.title == "Your tasks are stored on this \(noun)")
            #expect(accountLess.detail?.hasPrefix("Nothing is sent anywhere until you sign in. Sign in to use the same tasks on your ") == true)
        }
        #expect(SyncCopy.popoverAccountLess(device: .mac).detail?.hasSuffix("on your iPhone and the web.") == true)
    }

    @Test("021-FR-021 the backup line in its three forms")
    func popoverBackupForms() {
        let until = Self.date(2026, 11, 5)
        let calendar = Self.calendar
        #expect(SyncCopy.popoverBackup(until: until, notCarried: false, now: Self.now, calendar: calendar) == "Backup from before the update · kept until 5 Nov")
        let later = Self.date(2026, 11, 6)
        #expect(SyncCopy.popoverBackup(until: until, notCarried: false, now: later, calendar: calendar) == "Backup from before the update · removed when you sign out")
        #expect(SyncCopy.popoverBackup(until: until, notCarried: true, now: later, calendar: calendar) == "Backup from before the update · kept because some records couldn't be carried over")
    }

    @Test("021-FR-004 the account-switch refusal names the device and carries no other text")
    func accountSwitchRefusal() {
        for (device, noun) in [(DeviceKind.mac, "Mac"), (.iPhone, "iPhone")] {
            let copy = SyncCopy.accountSwitchRefused(device: device)
            #expect(copy.title == "Sign out first to use another account.")
            #expect(copy.detail == "Changes from the other account are still waiting on this \(noun).")
            #expect(copy.sentence == "Sign out first to use another account. Changes from the other account are still waiting on this \(noun).")
        }
    }

    // MARK: Signing out

    @Test("021-FR-018 the unsent-changes warning in each of its variants")
    func signOutUnsent() {
        let cases: [(Int, Bool, Bool, String, String)] = [
            (3, false, false, "3 changes haven't synced yet.", "Sign out and remove them from this Mac? They haven't reached your account."),
            (1, false, false, "1 change hasn't synced yet.", "Sign out and remove it from this Mac? It hasn't reached your account."),
            (1, true, false, "1 change hasn't synced yet.", "Sign out and remove it from this Mac? It hasn't reached your account. You're offline, so it can't be sent now."),
            (2, true, false, "2 changes haven't synced yet.", "Sign out and remove them from this Mac? They haven't reached your account. You're offline, so they can't be sent now."),
            (5, false, true, "5 changes haven't synced yet.", "Sign out and remove them from this Mac? To send them first, choose Cancel and sign in again."),
            (1, true, true, "1 change hasn't synced yet.", "Sign out and remove it from this Mac? To send it first, choose Cancel and sign in again."),
            (1_284, false, false, "1,284 changes haven't synced yet.", "Sign out and remove them from this Mac? They haven't reached your account."),
        ]
        for (count, offline, ended, title, detail) in cases {
            let copy = SyncCopy.signOutUnsent(count: count, offline: offline, sessionEnded: ended, device: .mac)
            #expect(copy == SyncCopyText(title: title, detail: detail))
            let phone = SyncCopy.signOutUnsent(count: count, offline: offline, sessionEnded: ended, device: .iPhone)
            #expect(phone.detail == detail.replacingOccurrences(of: "this Mac", with: "this iPhone"))
        }
        #expect(
            SyncCopy.signOutNothingUnsent(device: .mac)
                == SyncCopyText(title: "Sign out?", detail: "Your tasks are removed from this Mac. They stay in your account."))
        #expect(SyncCopy.signOutNothingUnsent(device: .iPhone).detail == "Your tasks are removed from this iPhone. They stay in your account.")
    }

    @Test("021-FR-018 021-FR-021 open issues and the backup follow the base text, in that order")
    func signOutSentences() {
        let calendar = Self.calendar
        let until = Self.date(2026, 11, 5)
        func confirm(
            unsent: Int = 0, issues: Int = 0, backup: SignOutBackupNote? = nil, device: DeviceKind = .mac,
            at now: Date = SyncPresentationTests.now
        ) -> SyncCopyText {
            SyncCopy.signOutConfirmation(
                unsent: unsent, offline: false, sessionEnded: false, issues: issues, backup: backup, device: device,
                now: now, calendar: calendar)
        }
        let base = "Your tasks are removed from this Mac. They stay in your account."
        #expect(confirm().detail == base)
        #expect(SyncCopy.signOutIssues(count: 1, device: .mac) == "1 change that couldn't sync will also be removed from this Mac.")
        #expect(SyncCopy.signOutIssues(count: 2, device: .iPhone) == "2 changes that couldn't sync will also be removed from this iPhone.")
        #expect(confirm(issues: 2).detail == base + " 2 changes that couldn't sync will also be removed from this Mac.")
        #expect(confirm(issues: 2, device: .iPhone).detail == "Your tasks are removed from this iPhone. They stay in your account. 2 changes that couldn't sync will also be removed from this iPhone.")

        let dated = "A copy of your tasks from before the update stays on this Mac until 5 Nov."
        let undated = "A copy of your tasks from before the update stays on this Mac."
        let removed = "The copy of your tasks from before the update will also be removed from this Mac."
        #expect(SyncCopy.signOutBackup(until: until, now: Self.now, calendar: calendar) == dated)
        #expect(SyncCopy.signOutBackup(until: until, now: Self.date(2026, 11, 6), calendar: calendar) == undated)
        #expect(SyncCopy.signOutBackupRemoved == removed)
        #expect(confirm(issues: 2, backup: .kept(until: until)).detail == base + " 2 changes that couldn't sync will also be removed from this Mac. " + dated)
        #expect(confirm(backup: .kept(until: until), at: Self.date(2026, 11, 6)).detail == base + " " + undated)
        #expect(confirm(issues: 1, backup: .removed).detail == base + " 1 change that couldn't sync will also be removed from this Mac. " + removed)
        #expect(!confirm(backup: .removed).sentence.contains("stays on this Mac"), "the removal is never said together with the keep")
        #expect(confirm(unsent: 3).title == "3 changes haven't synced yet.")
    }

    @Test("021-FR-018 unsaved weekly-review drafts are named singular and plural, after the issues and before the backup")
    func signOutReviewDraftSentences() {
        let calendar = Self.calendar
        let until = Self.date(2026, 11, 5)
        func confirm(
            unsent: Int = 0, issues: Int = 0, drafts: Int, backup: SignOutBackupNote? = nil, device: DeviceKind = .mac
        ) -> SyncCopyText {
            SyncCopy.signOutConfirmation(
                unsent: unsent, offline: false, sessionEnded: false, issues: issues, reviewDrafts: drafts, backup: backup,
                device: device, now: SyncPresentationTests.now, calendar: calendar)
        }
        let base = "Your tasks are removed from this Mac. They stay in your account."
        let one = "1 unsaved weekly-review draft will also be removed from this Mac."
        let many = "3 unsaved weekly-review drafts will also be removed from this Mac."
        #expect(SyncCopy.signOutReviewDrafts(count: 1, device: .mac) == one)
        #expect(SyncCopy.signOutReviewDrafts(count: 3, device: .mac) == many)
        #expect(SyncCopy.signOutReviewDrafts(count: 2, device: .iPhone) == "2 unsaved weekly-review drafts will also be removed from this iPhone.")
        #expect(SyncCopy.reviewDrafts(1) == "1 unsaved weekly-review draft")
        #expect(SyncCopy.reviewDrafts(1_200) == "1,200 unsaved weekly-review drafts")
        #expect(confirm(drafts: 0).detail == base, "no drafts, no sentence")
        #expect(confirm(drafts: 1).detail == base + " " + one)
        #expect(confirm(unsent: 2, drafts: 3).detail?.hasSuffix(" " + many) == true)
        let full = confirm(issues: 2, drafts: 3, backup: .kept(until: until)).detail
        let issues = "2 changes that couldn't sync will also be removed from this Mac."
        let backup = "A copy of your tasks from before the update stays on this Mac until 5 Nov."
        #expect(full == [base, issues, many, backup].joined(separator: " "))
        #expect(confirm(drafts: 1, backup: .removed).detail == [base, one, SyncCopy.signOutBackupRemoved].joined(separator: " "))
        #expect(confirm(unsent: 3, drafts: 0).title == "3 changes haven't synced yet.", "drafts never change the title")
        #expect(!SyncCopy.signOutReviewDrafts(count: 2, device: .mac).contains("—"))
    }

    // MARK: Formats and the retired dash

    @Test("021-FR-016 how old the oldest change is, at each boundary")
    func ageFormat() {
        let cases: [(TimeInterval, String)] = [
            (0, "0 s"), (59, "59 s"), (60, "1 min"), (3_599, "59 min"), (3_600, "1 h"), (23 * 3_600, "23 h"),
            (86_400, "1 day"), (2 * 86_400, "2 days"), (41 * 86_400, "41 days"),
        ]
        for (interval, expected) in cases { #expect(SyncCopy.age(interval) == expected) }
    }

    @Test("021-FR-012 no sentence uses the retired em dash")
    func noEmDash() {
        var strings: [String] = []
        for device in [DeviceKind.mac, .iPhone] {
            for snapshot in [
                SyncSnapshot(account: .none), Self.synced { $0.sessionEnded = true }, Self.synced { $0.issueCount = 3 },
                Self.synced(Self.failingRun),
                SyncSnapshot(account: Self.linked, isOnline: false, pendingCount: 2, oldestPendingAt: Self.now),
                SyncSnapshot(account: Self.linked), Self.synced(),
            ] {
                let description = Self.describe(snapshot, device: device)
                strings += [description.text, description.tooltip, description.accessibilityLabel]
            }
            strings += [
                SyncCopy.accountSwitchRefused(device: device).sentence, SyncCopy.popoverSessionEnded(device: device).sentence,
                SyncCopy.popoverAccountLess(device: device).sentence,
                SyncCopy.signOutUnsent(count: 2, offline: true, sessionEnded: false, device: device).sentence,
                SyncCopy.signOutNothingUnsent(device: device).sentence, SyncCopy.signOutIssues(count: 2, device: device),
            ]
        }
        strings += [SyncCopy.popoverLaterFile, SyncCopy.popoverImportAdjusted, SyncCopy.popoverFirstLoadEmpty, SyncCopy.signOutBackupRemoved]
        #expect(!strings.isEmpty && strings.allSatisfy { !$0.contains("—") })
    }
}

@Suite("Runtime issue and status presentation (spec 026 M-01/M-02/M-03)")
struct RuntimeSyncPresentationTests {
    static let t0 = Date(timeIntervalSince1970: 1_790_000_000)

    static func issue(
        _ id: String, reason: String, text: [String: String] = [:], revision: String? = "7",
        dependents: [String] = [], at offset: TimeInterval = 0
    ) -> RustWorkspaceIssue {
        RustWorkspaceIssue(
            id: id, commandID: "cmd-\(id)", reason: reason, localIntent: Data(), localText: text,
            shownBaseRevision: revision, dependentIDs: dependents, createdAt: t0.addingTimeInterval(offset))
    }

    @Test("026-FR-007 a conflict card keeps the saved text verbatim, the shown version and a safe reference")
    func conflictCard() {
        let text = "  Buy oat milk 🥛\nand more  "
        let card = RuntimeIssuePresenter.card(Self.issue("iss-1", reason: "REVISION_CONFLICT", text: ["title": text]))
        #expect(card.kind == .versionConflict)
        #expect(card.savedFields == [RuntimeSavedField(name: "title", value: text)])
        #expect(card.shownVersion == "7")
        #expect(card.referenceID == "iss-1")
        #expect(card.actions == [.chooseVersion, .copySavedEdit, .copyReference])
        #expect(card.accessibilityLabel.contains(text) && card.accessibilityLabel.contains("Reference ID: iss-1"))
    }

    @Test("026-FR-008 deleted elsewhere offers copy and keep deleted, never a recreate action")
    func deletedElsewhere() {
        let card = RuntimeIssuePresenter.card(Self.issue("iss-2", reason: "ENTITY_DELETED", text: ["name": "Chores"]))
        #expect(card.kind == .deletedElsewhere)
        #expect(card.message == "This item was deleted on another device. Your edit is saved in this issue.")
        #expect(card.actions == [.copySavedEdit, .keepItemDeleted, .copyReference])
    }

    @Test("026-FR-010 blocked dependants are counted, kept and offered the three safe choices")
    func blockedDependants() {
        let parent = Self.issue("p", reason: "REVISION_CONFLICT", text: ["title": "A"], dependents: ["cmd-c1", "c2"])
        let child = Self.issue("c1", reason: "BLOCKED_DEPENDENCY", text: ["notes": "later"], at: 1)
        let card = RuntimeIssuePresenter.card(parent)
        #expect(card.blockedDependentCount == 2)
        #expect(card.message.contains("2 later actions need your decision."))
        #expect(card.actions.contains(.reviewDependents))
        #expect(RuntimeIssuePresenter.card(child).actions == [.keepForLater, .reviewAndRetry, .discardAction, .copyReference])
        let summaries = RuntimeIssuePresenter.dependentSummaries(of: parent, among: [parent, child])
        #expect(summaries.map(\.summary) == ["notes: later", "Saved action"])
    }

    @Test("026-FR-010 unknown outcomes and other refusals are distinguished and never get a retry action")
    func unknownOutcome() {
        let unknown = RuntimeIssuePresenter.card(Self.issue("u", reason: "OUTCOME_UNKNOWN", text: ["title": "T"]))
        #expect(unknown.kind == .unknownOutcome)
        #expect(!unknown.actions.contains(.reviewAndRetry))
        #expect(RuntimeIssueKind(reason: "title_too_long") == .rejected(code: "title_too_long"))
    }

    @Test("026-FR-007 cards are ordered oldest first so dependants follow their predecessor")
    func ordering() {
        let cards = RuntimeIssuePresenter.cards([
            Self.issue("b", reason: "BLOCKED_DEPENDENCY", at: 5), Self.issue("a", reason: "REVISION_CONFLICT", at: 1),
        ])
        #expect(cards.map(\.id) == ["a", "b"])
    }

    @Test("026-FR-007 Apply stays off until a version is chosen; there is no default choice")
    func applyNeedsChoice() {
        var draft = ConflictDecisionDraft(dependentIDs: [], shownRevision: "7")
        #expect(draft.version == nil && !draft.canApply && draft.apply() == nil)
        draft.choose(.saved)
        #expect(draft.canApply)
        #expect(draft.apply() == ConflictDecision(version: .saved, againstRevision: "7", keepForLater: [], retry: [], discard: []))
    }

    @Test("026-FR-007 a second apply while saving creates no second resolution, and a failed save keeps the draft")
    func applyOnce() {
        var draft = ConflictDecisionDraft(dependentIDs: ["a"], shownRevision: "7")
        draft.choose(.account)
        #expect(draft.apply() != nil)
        #expect(draft.phase == .saving && draft.title == "Saving your choice…")
        #expect(draft.apply() == nil)
        draft.saveFailed()
        #expect(draft.phase == .saveFailed && draft.title == "Your choice wasn't saved. Try again.")
        #expect(draft.version == .account && draft.choice(for: "a") == .keepForLater && draft.canApply)
    }

    @Test("026-FR-010 later actions start as Keep for later and Review and retry needs explicit approval")
    func retryNeedsApproval() {
        var draft = ConflictDecisionDraft(dependentIDs: ["a", "b"], shownRevision: "7")
        #expect(draft.title == "2 later actions need your decision")
        draft.choose(.saved)
        #expect(draft.canApply && draft.discardedIDs.isEmpty)
        draft.setChoice(.reviewAndRetry, for: "a")
        #expect(!draft.canApply)
        draft.approveRetry(for: "a")
        #expect(draft.canApply)
        draft.setChoice(.keepForLater, for: "a")
        draft.setChoice(.reviewAndRetry, for: "a")
        #expect(!draft.canApply, "changing the choice withdraws the approval")
        draft.approveRetry(for: "b")
        #expect(!draft.approvedRetries.contains("b"), "approval only for an action marked for retry")
    }

    @Test("026-FR-010 discard needs the named confirmation; Cancel keeps every selection")
    func discardConfirmation() {
        var draft = ConflictDecisionDraft(dependentIDs: ["a", "b"], shownRevision: "7")
        draft.choose(.account)
        draft.requestDiscard()
        #expect(draft.phase == .choosing, "nothing selected to discard")
        draft.setChoice(.discard, for: "a")
        draft.setChoice(.discard, for: "b")
        #expect(!draft.canApply)
        draft.requestDiscard()
        #expect(draft.phase == .confirmingDiscard)
        #expect(draft.discardPrompt == "Discard these 2 saved actions?")
        #expect(draft.discardConfirmTitle == "Discard 2 actions")
        #expect(ConflictDecisionDraft.discardExplanation == "They will not be sent. Other saved actions will be kept.")
        draft.cancelDiscard()
        #expect(draft.phase == .choosing && draft.discardedIDs == ["a", "b"] && !draft.canApply)
        draft.requestDiscard()
        draft.confirmDiscard()
        #expect(draft.canApply)
        #expect(draft.apply()?.discard == ["a", "b"])
    }

    @Test("026-FR-007 a version change keeps the draft, clears the choice and approvals and requires apply again")
    func changedAgain() {
        var draft = ConflictDecisionDraft(dependentIDs: ["a", "b"], shownRevision: "7")
        draft.choose(.saved)
        draft.setChoice(.reviewAndRetry, for: "a")
        draft.approveRetry(for: "a")
        draft.setChoice(.discard, for: "b")
        draft.refresh(currentRevision: "7")
        #expect(draft.phase == .choosing && draft.version == .saved, "same version: nothing changes")
        draft.refresh(currentRevision: "8")
        #expect(draft.phase == .changedAgain && draft.title == "This task changed again. Review both versions.")
        #expect(draft.version == nil && draft.approvedRetries.isEmpty && !draft.canApply)
        #expect(draft.choice(for: "a") == .reviewAndRetry && draft.choice(for: "b") == .discard)
        #expect(draft.shownRevision == "8")
        draft.choose(.account)
        #expect(draft.phase == .choosing && !draft.canApply, "retry and discard still need approval")
    }

    @Test("026-FR-010 a draft is plain data: restoring it submits nothing")
    func interruptionKeepsDraft() {
        var draft = ConflictDecisionDraft(dependentIDs: ["a"], shownRevision: "7")
        draft.choose(.saved)
        draft.setChoice(.discard, for: "a")
        let restored = draft
        #expect(restored == draft && restored.phase == .choosing && !restored.canApply)
    }

    static func snapshot(_ change: (inout SyncSnapshot) -> Void = { _ in }) -> SyncSnapshot {
        var snapshot = SyncSnapshot(account: .linked(email: "a@example.com"), lastSyncedAt: t0.addingTimeInterval(-180))
        change(&snapshot)
        return snapshot
    }

    static func status(_ snapshot: SyncSnapshot, updateNeeded: Bool = false) -> RuntimeSyncStatus {
        RuntimeSyncStatusPresenter.describe(snapshot, updateNeeded: updateNeeded, now: t0, device: .iPhone)
    }

    @Test("026-FR-004 locally saved, pending, synced, auth, update and failure read differently")
    func statusDistinctions() {
        #expect(Self.status(Self.snapshot()).distinction == .synced)
        let account = Self.status(SyncSnapshot(account: .none))
        #expect(account.distinction == .localOnly && account.headline == "On this iPhone · Sign in to sync")
        let offline = Self.status(Self.snapshot { $0.isOnline = false })
        #expect(offline.distinction == .savedLocally && offline.detail == "Your changes are saved on this device.")
        #expect(offline.syncNowDisabledReason != nil)
        let waiting = Self.status(
            SyncSnapshot(
                account: Self.linkedAccount, lastSyncedAt: Self.t0.addingTimeInterval(-180), pendingCount: 3,
                oldestPendingAt: Self.t0.addingTimeInterval(-30)))
        #expect(waiting.distinction == .pending && waiting.headline.contains("3 changes waiting"))
        let auth = Self.status(Self.snapshot { $0.sessionEnded = true })
        #expect(auth.distinction == .signInNeeded && auth.action == .signInAgain && auth.headline == "Sign in again to sync")
        #expect(auth.detail?.contains("Your waiting changes stay with this account.") == true)
        let update = Self.status(Self.snapshot(), updateNeeded: true)
        #expect(update.distinction == .updateNeeded && update.action == .updateApp && update.headline == "Update needed to sync")
    }

    static let linkedAccount = SyncSnapshot.Account.linked(email: "a@example.com")

    @Test("026-FR-023 priority: update, then session ended, then issues, then failure; a reference ID shows only on failure")
    func statusPriority() {
        let both = Self.snapshot { $0.sessionEnded = true; $0.issueCount = 1 }
        #expect(Self.status(both, updateNeeded: true).distinction == .updateNeeded)
        #expect(Self.status(both).distinction == .signInNeeded)
        let issues = Self.status(Self.snapshot { $0.issueCount = 1 })
        #expect(issues.distinction == .hasIssues && issues.action == .openIssues && issues.headline == "1 change couldn't sync")
        let failing = Self.status(Self.snapshot {
            $0.failingSince = Self.t0.addingTimeInterval(-120); $0.lastFailedAttemptAt = Self.t0.addingTimeInterval(-10)
            $0.lastFailureReferenceID = "ref-9"
        })
        #expect(failing.distinction == .failing && failing.action == .retry && failing.referenceID == "ref-9")
        #expect(failing.accessibilityLabel.contains("Reference ID: ref-9"))
        #expect(Self.status(Self.snapshot()).referenceID == nil)
    }

    @Test("026-FR-005 a transport failure reported by the runtime shows Retry and its reference ID, not Synced")
    func runtimeTransportFailure() {
        let quiet = Self.snapshot()
        let failing = RuntimeSyncStatusPresenter.describe(
            quiet, transportFailure: TransportFailure(referenceID: "ref-3"), now: Self.t0, device: .iPhone)
        #expect(failing.distinction == .failing && failing.action == .retry && failing.referenceID == "ref-3")
        #expect(failing.headline == "Couldn't sync · Retry" && failing.needsAttention)
        let unavailable = RuntimeSyncStatusPresenter.describe(
            quiet, transportFailure: TransportFailure(referenceID: nil), now: Self.t0, device: .iPhone)
        #expect(unavailable.distinction == .failing && unavailable.referenceID == nil)
        let signedOut = RuntimeSyncStatusPresenter.describe(
            Self.snapshot { $0.sessionEnded = true }, transportFailure: TransportFailure(referenceID: "r"),
            now: Self.t0, device: .iPhone)
        #expect(signedOut.distinction == .signInNeeded, "sign-in outranks a transport failure")
    }

    @Test("026-FR-004 Not synced yet is its own non-success state")
    func notSyncedYetIsNotSynced() {
        let first = Self.status(SyncSnapshot(account: Self.linkedAccount))
        #expect(first.headline == "Not synced yet" && first.distinction == .notSyncedYet)
    }

    @Test("026-FR-004 the iPad reads as the iPad, not the iPhone")
    func ipadNoun() {
        let status = RuntimeSyncStatusPresenter.describe(SyncSnapshot(account: .none), now: Self.t0, device: .iPad)
        #expect(status.headline == "On this iPad · Sign in to sync")
    }

    @Test("026-FR-010 switching a retry approval off withdraws it and Apply follows")
    func retryApprovalWithdrawn() {
        var draft = ConflictDecisionDraft(dependentIDs: ["a"], shownRevision: "7")
        draft.choose(.saved)
        draft.setChoice(.reviewAndRetry, for: "a")
        draft.approveRetry(for: "a")
        #expect(draft.canApply)
        draft.withdrawRetryApproval(for: "a")
        #expect(draft.approvedRetries.isEmpty && !draft.canApply)
    }
}
