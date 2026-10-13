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

        init(text: String, detail: String?, symbolName: String, needsAttention: Bool, accessibilityLabel: String? = nil) {
            self.text = text
            self.detail = detail
            self.symbolName = symbolName
            self.needsAttention = needsAttention
            self.accessibilityLabel = accessibilityLabel
        }
    }

    @MainActor static var deviceName: String {
        UIDevice.current.userInterfaceIdiom == .pad ? "iPad" : "iPhone"
    }

    /// The label for the workspace: the typed runtime status (spec 026 M-01) when the shared core
    /// runs it, otherwise the legacy engine's status. `updateNeeded` is false until the workspace
    /// exposes the runtime's unsupported-version state.
    @MainActor static func describe(_ workspace: Workspace, now: Date) -> Description {
        guard workspace.isRustSelected else {
            return describe(
                workspace.syncStatus, pendingChanges: workspace.pendingChangeCount, now: now, deviceName: deviceName)
        }
        let device: DeviceKind = UIDevice.current.userInterfaceIdiom == .pad ? .iPad : .iPhone
        var failure: TransportFailure?
        if case .failing(_, let referenceID, _) = workspace.syncStatus {
            failure = TransportFailure(referenceID: referenceID)
        } else if workspace.runtimeTransportUnavailable {
            failure = TransportFailure(referenceID: nil)
        }
        let status = RuntimeSyncStatusPresenter.describe(
            workspace.syncSnapshot, updateNeeded: workspace.syncRecovery.storeNeedsUpdate, transportFailure: failure, now: now, device: device)
        return Description(
            text: status.headline, detail: status.detail, symbolName: symbolName(status.distinction, device: device),
            needsAttention: status.needsAttention, accessibilityLabel: status.accessibilityLabel)
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
        .accessibilityLabel(
            description.accessibilityLabel
                ?? [description.text, description.detail].compactMap { $0 }.joined(separator: ". "))
    }
}
