import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI
import UIKit

/// Sync state in words — never a coloured dot alone: "On this iPhone",
/// "Synced 2 minutes ago", "Syncing…", "Offline — 3 changes waiting",
/// "Sign in again to sync", "Sync failed — <reason>" with its reference ID.
/// Relative times refresh every 30 seconds.
struct SyncStatusLabel: View {
    @Environment(Workspace.self) private var workspace

    var body: some View {
        TimelineView(.periodic(from: .now, by: 30)) { context in
            let description = Self.describe(
                workspace.syncStatus,
                pendingChanges: workspace.pendingChangeCount,
                now: context.date,
                deviceName: Self.deviceName
            )
            SyncStatusContent(description: description)
        }
    }

    /// What the label says for a status.
    struct Description: Equatable {
        var text: String
        var detail: String?
        var symbolName: String
        var needsAttention: Bool
    }

    @MainActor static var deviceName: String {
        UIDevice.current.userInterfaceIdiom == .pad ? "iPad" : "iPhone"
    }

    nonisolated static func describe(
        _ status: SyncStatus, pendingChanges: Int, now: Date, deviceName: String
    ) -> Description {
        switch status {
        case .localOnly:
            return Description(
                text: "On this \(deviceName)", detail: nil, symbolName: deviceName == "iPad" ? "ipad" : "iphone",
                needsAttention: false
            )
        case .idle(let lastSyncedAt):
            var text = lastSyncedAt.map { "Synced \(relativeTime($0, now: now))" } ?? "Not synced yet"
            if pendingChanges > 0 { text += " · \(changesWaiting(pendingChanges))" }
            return Description(text: text, detail: nil, symbolName: "checkmark.icloud", needsAttention: false)
        case .syncing:
            return Description(
                text: "Syncing…", detail: nil, symbolName: "arrow.triangle.2.circlepath.icloud", needsAttention: false
            )
        case .offline:
            let text = pendingChanges > 0 ? "Offline — \(changesWaiting(pendingChanges))" : "Offline"
            return Description(text: text, detail: nil, symbolName: "icloud.slash", needsAttention: false)
        case .needsSignIn:
            return Description(
                text: "Sign in again to sync", detail: nil,
                symbolName: "person.crop.circle.badge.exclamationmark", needsAttention: true
            )
        case .failing(let message, let referenceID, _):
            return Description(
                text: "Sync failed — \(message)", detail: referenceID.map { "Reference ID: \($0)" },
                symbolName: "exclamationmark.icloud", needsAttention: true
            )
        }
    }

    /// "1 change waiting" / "3 changes waiting".
    nonisolated static func changesWaiting(_ count: Int) -> String {
        count == 1 ? "1 change waiting" : "\(count) changes waiting"
    }

    /// "just now" under a minute (or with a clock ahead of ours), otherwise
    /// "2 minutes ago", "yesterday", …
    nonisolated static func relativeTime(_ date: Date, now: Date) -> String {
        guard now.timeIntervalSince(date) >= 60 else { return "just now" }
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .full
        formatter.dateTimeStyle = .named
        return formatter.localizedString(for: date, relativeTo: now)
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
    }
}
