import BrainBuddyCore
import BrainBuddyWorkspace
import Foundation
import SwiftUI
import UIKit

/// Local changes the server rejected. Each one says what was attempted, why
/// it failed, and a reference ID to quote when reporting it.
struct SyncIssuesScreen: View {
    @Environment(Workspace.self) private var workspace

    init() {}

    var body: some View {
        let issues = workspace.issues.sorted { $0.occurredAt > $1.occurredAt }
        Group {
            if issues.isEmpty {
                EmptyStateView(
                    title: "No sync issues",
                    message: "Changes the server can't apply show up here.",
                    systemImage: "checkmark.circle"
                )
            } else {
                List {
                    Section {
                        ForEach(issues) { issue in
                            row(issue)
                        }
                    } header: {
                        Text(explanation)
                            .textCase(nil)
                    }
                }
            }
        }
        .navigationTitle("Sync issues")
    }

    private func row(_ issue: SyncIssue) -> some View {
        SyncIssueRow(issue: issue, summary: SyncIssueDescriber.describe(issue, in: workspace.state).attempted)
            .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                Button {
                    workspace.dismissIssue(issue.id)
                } label: {
                    Label("Dismiss", systemImage: "xmark")
                }
            }
            .contextMenu {
                if let referenceID = issue.referenceID {
                    Button {
                        UIPasteboard.general.string = referenceID
                    } label: {
                        Label("Copy reference ID", systemImage: "doc.on.doc")
                    }
                }
                Button {
                    workspace.dismissIssue(issue.id)
                } label: {
                    Label("Dismiss", systemImage: "xmark")
                }
            }
    }

    private var explanation: String {
        if workspace.pendingChangeCount > 0 {
            return "These changes couldn't be applied on the server. Your other changes still sync as usual."
        }
        return "These changes couldn't be applied on the server. Your other changes are synced."
    }
}

private struct SyncIssueRow: View {
    let issue: SyncIssue
    let summary: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(summary)
                .font(BBFont.bodyMedium)
                .foregroundStyle(BBColor.textPrimary)
            Text(issue.message)
                .font(BBFont.secondary)
                .foregroundStyle(BBColor.textSecondary)
            if let referenceID = issue.referenceID {
                Text("Reference ID: \(referenceID)")
                    .font(.footnote.monospaced())
                    .foregroundStyle(BBColor.textTertiary)
                    .textSelection(.enabled)
            }
            Text(issue.occurredAt.formatted(date: .abbreviated, time: .shortened))
                .font(BBFont.meta)
                .foregroundStyle(BBColor.textTertiary)
        }
        .padding(.vertical, BBSpacing.s1)
    }
}
