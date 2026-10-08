import BrainBuddyCore
import BrainBuddyMacCore
import SwiftUI

/// Design X-01, the sidebar footer's sync status line (contracts/mac-app-host.md §6), rendering
/// `SyncStatusLineModel`: one line of 11 pt secondary words (amber with a glyph in attention states),
/// the indicator's reserved slot (a static glyph under Reduce Motion), at most one trailing action
/// in sky, wrapping after " · " rather than truncating, the tooltip, and one polite announcement when
/// an attention state appears. It never presents anything or moves focus by itself: the words and
/// the action are buttons the person presses, and they go through `MacPresentationRouter`.
struct SyncStatusLine: View {
    let controller: MacSyncController
    @FocusState private var focus: FocusTarget?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var now = Date()

    var body: some View {
        let line = controller.line
        let description = line.description
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            SyncStatusGlyph(glyph: description.glyph)
            wordsButton(description)
            if let action = description.trailingActionTitle {
                Button(action) {
                    Task { await controller.performTrailingAction() }
                }
                .buttonStyle(.plain)
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(Color.accentColor)
                .accessibilityLabel(description.action == .retry ? "Retry sync" : action)
                .focused($focus, equals: .statusTrailingAction)
            }
            Spacer(minLength: 0)
            SyncIndicatorSlot(slot: line.indicatorSlot(at: now), reduceMotion: reduceMotion)
        }
        .padding(12)
        .onChange(of: controller.workspace.syncSnapshot, initial: true) { _, _ in
            controller.observeSnapshot()
            announce()
        }
        .task(id: line.describedAt) {
            // One timer: the next relative refresh or the indicator's next change.
            now = Date()
            let wake = controller.line.nextWake(after: now)
            try? await Task.sleep(for: .seconds(max(0.05, wake.timeIntervalSince(now))))
            guard !Task.isCancelled else { return }
            now = Date()
            controller.refreshLine()
            announce()
        }
        .routedFocus($focus, router: controller.router) { target in
            target == .statusWords || target == .statusTrailingAction ? target : nil
        }
    }

    /// The words: a button that opens X-02 (Space or Return when focused), named
    /// "Sync status: <state>. Show details", with the tooltip.
    private func wordsButton(_ description: SyncStatusDescription) -> some View {
        let words = description.trailingActionTitle == nil ? description.text : description.leading
        return Button {
            controller.router.handle(.openSyncDetails(from: .statusWords))
        } label: {
            SyncStatusWords(text: words, attention: description.tone == .attention)
        }
        .buttonStyle(.plain)
        .help(description.tooltip)
        .accessibilityLabel(description.accessibilityLabel)
        .focused($focus, equals: .statusWords)
        .routedSyncDetailsPopover(controller.router, anchor: .statusWords, onClose: { controller.closeSyncDetails() }) {
            SyncStatusPopover(controller: controller)
        }
    }

    private func announce() {
        if let text = controller.takeAnnouncement() { AccessibilityNotification.Announcement(text).post() }
    }
}

/// The words, wrapping after " · " to a second line instead of truncating (large sidebar text, a
/// narrow sidebar).
struct SyncStatusWords: View {
    let text: String
    let attention: Bool

    var body: some View {
        let parts = text.components(separatedBy: " · ")
        ViewThatFits(in: .horizontal) {
            Text(text).lineLimit(1)
            VStack(alignment: .leading, spacing: 1) {
                Text(parts.count > 1 ? parts[0] + " ·" : text)
                if parts.count > 1 { Text(parts.dropFirst().joined(separator: " · ")) }
            }
            .fixedSize(horizontal: false, vertical: true)
        }
        .font(.system(size: 11))
        .foregroundStyle(attention ? AnyShapeStyle(Color.orange) : AnyShapeStyle(HierarchicalShapeStyle.secondary))
    }
}

/// The attention glyph: words always carry the state; colour is never the only signal.
struct SyncStatusGlyph: View {
    let glyph: SyncStatusDescription.Glyph

    var body: some View {
        switch glyph {
        case .none:
            EmptyView()
        case .sessionEnded:
            Image(systemName: "person.crop.circle.badge.exclamationmark")
                .font(.system(size: 11))
                .foregroundStyle(.orange)
                .accessibilityHidden(true)
        case .warning:
            Image(systemName: "exclamationmark.triangle")
                .font(.system(size: 11))
                .foregroundStyle(.orange)
                .accessibilityHidden(true)
        }
    }
}

/// The indicator's slot: always its width, so the words never move; the platform's small progress
/// control while a sync has run longer than 1 s, a static glyph under Reduce Motion. Named
/// "Syncing", not announced when it appears.
struct SyncIndicatorSlot: View {
    let slot: IndicatorSlot
    let reduceMotion: Bool

    var body: some View {
        let label: String = slot.visible ? "Syncing" : ""
        ZStack {
            if slot.visible {
                if reduceMotion {
                    Image(systemName: "arrow.triangle.2.circlepath")
                        .font(.system(size: 10))
                        .foregroundStyle(.secondary)
                } else {
                    ProgressView().controlSize(.mini)
                }
            }
        }
        .frame(width: slot.width, height: slot.width)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(label)
        .accessibilityHidden(!slot.visible)
    }
}

/// X-01 while the sidebar is collapsed: in attention states only, one compact toolbar item with the
/// same words and glyph, which opens X-02; it appears without taking focus. Calm states show nothing
/// about sync in the toolbar (X-07).
struct SyncToolbarStatusItem: View {
    let controller: MacSyncController
    let sidebarHidden: Bool

    var body: some View {
        if let item = controller.line.toolbarItem(sidebarHidden: sidebarHidden) {
            Button {
                controller.router.handle(.openSyncDetails(from: .toolbarItem))
            } label: {
                HStack(spacing: 4) {
                    SyncStatusGlyph(glyph: item.glyph)
                    Text(item.text).font(.system(size: 11))
                }
            }
            .help(controller.line.description.tooltip)
            .accessibilityLabel(item.accessibilityLabel)
            .routedSyncDetailsPopover(controller.router, anchor: .toolbarItem, onClose: { controller.closeSyncDetails() }) {
                SyncStatusPopover(controller: controller)
            }
        }
    }
}
