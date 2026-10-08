import BrainBuddyCore
import Foundation
import Testing

@testable import BrainBuddyMacCore

/// X-01's model (contracts/mac-app-host.md §6, §8): what the footer says, when it says it again,
/// the indicator's slot, the one announcement per attention state, and the toolbar item while the
/// sidebar is hidden. The words themselves are the kit's (`SyncPresentationTests`).
@Suite("Sync status line")
struct SyncStatusLineModelTests {
    private static let start = TestClock.importTime
    private static let utc: Calendar = {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        return calendar
    }()

    private static func synced(at date: Date, syncing: Bool = false) -> SyncSnapshot {
        SyncSnapshot(account: .linked(email: "alex@example.com"), isSyncing: syncing, lastSyncedAt: date)
    }

    private static let sessionEnded = SyncSnapshot(
        account: .linked(email: "alex@example.com"), sessionEnded: true, lastSyncedAt: start
    )

    private static func failing(since: Date, lastTried: Date) -> SyncSnapshot {
        SyncSnapshot(
            account: .linked(email: "alex@example.com"), lastSyncedAt: since, failingSince: since,
            lastFailedAttemptAt: lastTried, lastFailureReferenceID: "4e5d9a20-0000-4000-8000-000000000001"
        )
    }

    @Test("021-FR-012 the line describes itself again after 30 s with no snapshot change")
    func describesAgainAfterThirtySeconds() {
        var line = SyncStatusLineModel(snapshot: Self.synced(at: Self.start), now: Self.start, calendar: Self.utc)
        #expect(line.description.text == "Synced just now")
        #expect(line.nextWake(after: Self.start) == Self.start.addingTimeInterval(SyncTiming.relativeRefresh))

        let early = line.refresh(at: Self.start.addingTimeInterval(29))
        #expect(!early, "not before 30 s")
        #expect(line.description.text == "Synced just now")
        let atThirty = line.refresh(at: Self.start.addingTimeInterval(30))
        let atSixty = line.refresh(at: Self.start.addingTimeInterval(60))
        #expect(atThirty && atSixty)
        #expect(line.description.text == "Synced 1 min ago", "the words keep up with the clock")
        #expect(line.describedAt == Self.start.addingTimeInterval(60))
    }

    @Test("021-FR-013 the indicator's slot keeps its width whether the indicator shows or not")
    func indicatorSlotKeepsItsWidth() {
        var line = SyncStatusLineModel(snapshot: Self.synced(at: Self.start), now: Self.start, calendar: Self.utc)
        let idle = line.indicatorSlot(at: Self.start)
        line.update(Self.synced(at: Self.start, syncing: true), at: Self.start)
        let early = line.indicatorSlot(at: Self.start.addingTimeInterval(0.9))
        let shown = line.indicatorSlot(at: Self.start.addingTimeInterval(1.1))

        #expect(!idle.visible && !early.visible, "a sync shorter than 1 s shows nothing")
        #expect(shown.visible)
        #expect(idle.width == shown.width && early.width == shown.width)
        #expect(idle.width == SyncStatusLineModel.indicatorSlotWidth && idle.width > 0)
        #expect(line.nextWake(after: Self.start) == Self.start.addingTimeInterval(SyncTiming.indicatorDelay))
        line.update(Self.synced(at: Self.start.addingTimeInterval(1.2)), at: Self.start.addingTimeInterval(1.2))
        #expect(line.indicatorVisible(at: Self.start.addingTimeInterval(1.4)), "once shown, at least 0.5 s")
        #expect(!line.indicatorVisible(at: Self.start.addingTimeInterval(1.6)))
        #expect(line.description.text == "Synced just now", "the words never change because a sync ran")
    }

    @Test("021-FR-012 021-FR-017 entering an attention state is announced once; staying in it says nothing more")
    func attentionIsAnnouncedOnce() {
        var line = SyncStatusLineModel(snapshot: Self.synced(at: Self.start), now: Self.start, calendar: Self.utc)
        #expect(line.takeAnnouncement() == nil)

        line.update(Self.sessionEnded, at: Self.start.addingTimeInterval(1))
        #expect(line.takeAnnouncement() == "Sign in again to sync")
        #expect(line.announcementCount == 1)
        for second in 2...5 {
            line.update(Self.sessionEnded, at: Self.start.addingTimeInterval(TimeInterval(second * 30)))
            line.refresh(at: Self.start.addingTimeInterval(TimeInterval(second * 30 + 15)))
        }
        #expect(line.takeAnnouncement() == nil, "staying in the state says nothing")
        #expect(line.announcementCount == 1)

        // Another attention state is entered: one more announcement.
        line.update(Self.failing(since: Self.start, lastTried: Self.start.addingTimeInterval(60)), at: Self.start.addingTimeInterval(200))
        #expect(line.takeAnnouncement() == "Couldn't sync · Retry")
        #expect(line.announcementCount == 2)
    }

    @Test("021-FR-012 calm changes are never announced")
    func calmChangesAreNotAnnounced() {
        let start = Self.start
        var line = SyncStatusLineModel(snapshot: Self.synced(at: start), now: start, calendar: Self.utc)
        let calm: [SyncSnapshot] = [
            Self.synced(at: start, syncing: true),
            Self.synced(at: start),
            SyncSnapshot(account: .linked(email: "alex@example.com"), lastSyncedAt: start, pendingCount: 2, oldestPendingAt: start),
            SyncSnapshot(account: .linked(email: "alex@example.com"), isOnline: false, lastSyncedAt: start, pendingCount: 3, oldestPendingAt: start),
            SyncSnapshot(account: .linked(email: "alex@example.com")),
            SyncSnapshot(account: .none),
            // A failure under 60 s is not "Couldn't sync".
            Self.failing(since: start, lastTried: start.addingTimeInterval(59)),
        ]
        for (index, snapshot) in calm.enumerated() {
            line.update(snapshot, at: start.addingTimeInterval(TimeInterval(index * 40)))
            line.refresh(at: start.addingTimeInterval(TimeInterval(index * 40 + 30)))
        }
        #expect(line.announcementCount == 0)
        #expect(line.takeAnnouncement() == nil)
    }

    @Test("021-FR-012 021-FR-017 the sidebar-hidden toolbar item appears only in attention states, named like the line, without focus")
    func toolbarItemOnlyInAttentionStates() {
        let start = Self.start
        let attention: [SyncSnapshot] = [
            Self.sessionEnded,
            Self.failing(since: start, lastTried: start.addingTimeInterval(60)),
            SyncSnapshot(account: .linked(email: "alex@example.com"), lastSyncedAt: start, issueCount: 2),
        ]
        for snapshot in attention {
            let line = SyncStatusLineModel(snapshot: snapshot, now: start.addingTimeInterval(61), calendar: Self.utc)
            let item = line.toolbarItem(sidebarHidden: true)
            #expect(item?.text == line.description.text)
            #expect(item?.accessibilityLabel == "Sync status: \(line.description.text). Show details")
            #expect(item?.glyph == line.description.glyph && item?.glyph != SyncStatusDescription.Glyph.none)
            #expect(item?.requestsFocus == false)
            #expect(line.toolbarItem(sidebarHidden: false) == nil, "with the sidebar shown the footer says it")
        }
        let calm: [SyncSnapshot] = [
            Self.synced(at: start), SyncSnapshot(account: .none),
            SyncSnapshot(account: .linked(email: "alex@example.com"), isOnline: false, lastSyncedAt: start),
            SyncSnapshot(account: .linked(email: "alex@example.com")),
        ]
        for snapshot in calm {
            let line = SyncStatusLineModel(snapshot: snapshot, now: start, calendar: Self.utc)
            #expect(line.toolbarItem(sidebarHidden: true) == nil, "nothing about sync in the toolbar when all is well")
        }
    }
}
