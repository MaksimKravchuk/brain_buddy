import BrainBuddyCore
import Foundation

/// X-01's model (contracts/mac-app-host.md §6): the words, tone, glyph and tooltip of the sidebar
/// footer from the kit's `SyncStatusDescriber`, and the indicator from `SyncActivityIndicator`.
/// It produces text, tone, glyph and announcements only: it has no way to present anything or move
/// focus (FR-017, SC-004), which `MacPresentationGuardTests` keeps true at the source level.
///
/// A value with no timers: the view describes again on every snapshot change (`update`) and sets one
/// timer for `nextWake(after:)`, which is at most `SyncTiming.relativeRefresh` away (`refresh`).
package struct SyncStatusLineModel: Equatable, Sendable {
    /// The indicator's reserved slot, in points: the same whether the indicator shows or not, so the
    /// words never move when a sync starts or stops (design X-01 "No flicker").
    package static let indicatorSlotWidth: Double = 14

    package let device: DeviceKind
    package let calendar: Calendar
    package private(set) var snapshot: SyncSnapshot
    package private(set) var description: SyncStatusDescription
    /// When `description` was made.
    package private(set) var describedAt: Date
    private var indicator = SyncActivityIndicator()
    /// The announcement entering an attention state asks for, until the view posts it.
    package private(set) var pendingAnnouncement: String?
    /// Every announcement asked for so far (one per entry into an attention state).
    package private(set) var announcementCount = 0

    package init(snapshot: SyncSnapshot, now: Date, device: DeviceKind = .mac, calendar: Calendar = .current) {
        self.device = device
        self.calendar = calendar
        self.snapshot = snapshot
        describedAt = now
        description = SyncStatusDescriber.describe(snapshot, now: now, device: device, calendar: calendar)
        if snapshot.isSyncing { indicator.started(at: now) }
        if description.announceOnEntry { announce() }
    }

    /// A snapshot from the workspace (changed or not): describes again, follows the sync for the
    /// indicator, and asks for one polite announcement when this enters an attention state.
    package mutating func update(_ snapshot: SyncSnapshot, at now: Date) {
        if snapshot.isSyncing, !self.snapshot.isSyncing { indicator.started(at: now) }
        if !snapshot.isSyncing, self.snapshot.isSyncing { indicator.finished(at: now) }
        self.snapshot = snapshot
        describe(at: now)
    }

    /// The view's timer: describes the same snapshot again once `relativeRefresh` has passed, so
    /// "Synced 3 min ago" keeps up with the clock. Returns whether it described.
    @discardableResult
    package mutating func refresh(at now: Date) -> Bool {
        guard now.timeIntervalSince(describedAt) >= SyncTiming.relativeRefresh else { return false }
        describe(at: now)
        return true
    }

    private mutating func describe(at now: Date) {
        let previous = description
        description = SyncStatusDescriber.describe(snapshot, now: now, device: device, calendar: calendar)
        describedAt = now
        // Calm changes (minutes ticking, syncing, waiting) are never announced; an attention state is
        // announced when it appears, and staying in it says nothing more.
        if description.announceOnEntry, description.state != previous.state { announce() }
    }

    private mutating func announce() {
        pendingAnnouncement = description.text
        announcementCount += 1
    }

    /// The announcement to post now, once.
    package mutating func takeAnnouncement() -> String? {
        defer { pendingAnnouncement = nil }
        return pendingAnnouncement
    }

    /// When the view should look again: the next relative refresh, or sooner when the indicator
    /// appears or ends.
    package func nextWake(after now: Date) -> Date {
        let refresh = describedAt.addingTimeInterval(SyncTiming.relativeRefresh)
        guard let change = indicator.nextChange(after: now) else { return max(refresh, now) }
        return min(max(refresh, now), change)
    }

    package func indicatorVisible(at now: Date) -> Bool { indicator.isVisible(at: now) }

    /// The reserved slot at `now`: its width never depends on whether the indicator shows.
    package func indicatorSlot(at now: Date) -> IndicatorSlot {
        IndicatorSlot(visible: indicatorVisible(at: now), width: Self.indicatorSlotWidth)
    }

    /// The compact toolbar item shown while the sidebar is collapsed (design X-01 "sidebar
    /// hidden"): only in attention states, with the line's words, glyph and accessible name, and it
    /// never takes focus. Calm states put nothing about sync in the toolbar (X-07).
    package func toolbarItem(sidebarHidden: Bool) -> SyncToolbarItem? {
        guard sidebarHidden, description.tone == .attention else { return nil }
        return SyncToolbarItem(
            text: description.text, glyph: description.glyph, accessibilityLabel: description.accessibilityLabel,
            requestsFocus: false
        )
    }
}

/// The indicator's slot in X-01.
package struct IndicatorSlot: Equatable, Sendable {
    package var visible: Bool
    package var width: Double
}

/// X-01's toolbar item while the sidebar is hidden.
package struct SyncToolbarItem: Equatable, Sendable {
    package var text: String
    package var glyph: SyncStatusDescription.Glyph
    package var accessibilityLabel: String
    /// Always false: the item appears without taking focus (FR-017).
    package var requestsFocus: Bool
}
