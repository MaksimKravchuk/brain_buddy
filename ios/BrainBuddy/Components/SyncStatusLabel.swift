import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI
import UIKit

/// Sync state in words — never a coloured dot alone: "On this iPhone",
/// "Synced 2 minutes ago", "Syncing…", "Offline · 3 changes waiting",
/// "Sign in again to sync", "Couldn't sync · Retry" with its reference ID.
/// Relative times refresh every 30 seconds.
struct SyncStatusLabel: View {
    @Environment(Workspace.self) private var workspace

    var body: some View {
        TimelineView(.periodic(from: .now, by: 30)) { context in
            SyncStatusContent(description: Self.describe(workspace, now: context.date))
        }
    }

    /// What the label says for a status.
    struct Description: Equatable {
        var text: String
        var detail: String?
        var symbolName: String
        var needsAttention: Bool
        /// Overrides the combined label where the typed status has a fuller one.
        var accessibilityLabel: String?
        /// Why Sync now is off, when it is (offline, session ended, update required).
        var syncNowDisabledReason: String?

        init(
            text: String, detail: String?, symbolName: String, needsAttention: Bool, accessibilityLabel: String? = nil,
            syncNowDisabledReason: String? = nil
        ) {
            self.syncNowDisabledReason = syncNowDisabledReason
            self.text = text
            self.detail = detail
            self.symbolName = symbolName
            self.needsAttention = needsAttention
            self.accessibilityLabel = accessibilityLabel
        }
    }

    @MainActor static var device: DeviceKind {
        UIDevice.current.userInterfaceIdiom == .pad ? .iPad : .iPhone
    }

    /// The label for the workspace, for every surface (Inbox header, lists hub, Settings) and for
    /// both runtimes: `WorkspaceSyncStatusPresenter` over the workspace's snapshot. `updateNeeded`
    /// is the store being newer than this build or the sync transport's `UPGRADE_REQUIRED`.
    @MainActor static func describe(_ workspace: Workspace, now: Date) -> Description {
        let device = Self.device
        let status = WorkspaceSyncStatusPresenter.describe(
            snapshot: workspace.syncSnapshot, status: workspace.syncStatus,
            updateNeeded: workspace.syncRecovery.storeNeedsUpdate || workspace.syncRecovery.syncNeedsUpdate,
            transportUnavailable: workspace.runtimeTransportUnavailable, now: now, device: device)
        return Description(
            text: status.headline, detail: status.detail, symbolName: symbolName(status.distinction, device: device),
            needsAttention: status.needsAttention, accessibilityLabel: status.accessibilityLabel,
            syncNowDisabledReason: status.syncNowDisabledReason)
    }

    nonisolated static func symbolName(_ distinction: RuntimeSyncStatus.Distinction, device: DeviceKind) -> String {
        switch distinction {
        case .localOnly: device == .iPad ? "ipad" : "iphone"
        case .notSyncedYet: "icloud"
        case .savedLocally: "icloud.slash"
        case .pending: "arrow.triangle.2.circlepath.icloud"
        case .synced: "checkmark.icloud"
        case .signInNeeded: "person.crop.circle.badge.exclamationmark"
        case .updateNeeded: "arrow.down.app"
        case .hasIssues, .failing: "exclamationmark.icloud"
        }
    }
}

private struct SyncStatusContent: View {
    let description: SyncStatusLabel.Description

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Label {
                Text(description.text)
            } icon: {
                Image(systemName: description.symbolName)
                    .foregroundStyle(description.needsAttention ? BBColor.warning : BBColor.textTertiary)
            }
            .foregroundStyle(description.needsAttention ? BBColor.warningText : BBColor.textTertiary)
            if let detail = description.detail {
                Text(detail)
                    .font(BBFont.caption)
                    .foregroundStyle(BBColor.textTertiary)
                    .textSelection(.enabled)
            }
        }
        .font(BBFont.meta)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(
            description.accessibilityLabel
                ?? [description.text, description.detail].compactMap { $0 }.joined(separator: ". "))
    }
}
