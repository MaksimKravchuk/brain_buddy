import AppKit
import BrainBuddyCore
import BrainBuddyMacCore
import SwiftUI

/// Design X-02, the sync status popover (contracts/mac-app-host.md §6), laying out
/// `SyncPopoverContent`: last sync, what waits (or the first-upload line), the notices, the issues
/// with Copy and Dismiss (a kept outcome in full with "Copy outcome" and "Discard outcome", then
/// "Outcome discarded · Undo" for 5 s), "Sync now" (disabled, never hidden, where no sync can run),
/// the email and "Sign out…", and the quiet upgrade lines with "Show in Finder". Non-modal, at most
/// 480 pt tall with its own scroll; Esc or a click outside closes it. Focus on open and after Dismiss
/// follow the content's rules, through the router.
struct SyncStatusPopover: View {
    let controller: MacSyncController
    @FocusState private var focus: SyncPopoverControl?
    @State private var copied: SyncPopoverControl?
    /// The conflict detail (D-02) shown in place of the list; Back returns with the draft kept.
    @State private var conflict: SyncConflictModel?
    @State private var drafts: [String: SyncConflictDraft] = [:]

    private var runtimeIssues: [SyncRuntimeIssue] { controller.workspace.runtimeIssues.map(SyncRuntimeIssue.init) }

    var body: some View {
        let content = SyncPopoverModel.adding(
            runtimeIssues: runtimeIssues, pendingCount: controller.workspace.syncSnapshot.pendingCount,
            to: controller.popoverContent()
        )
        Group {
            if let model = Binding($conflict) {
                SyncConflictView(
                    model: model, blockedPreview: { action in "Retry: \(action.summary)" }, submit: nil,
                    back: closeConflict
                )
            } else {
                ViewThatFits(in: .vertical) {
                    sections(content)
                    ScrollView { sections(content) }
                }
            }
        }
        .frame(width: 360)
        .frame(maxHeight: 480)
        .routedFocus($focus, router: controller.router) { target in
            if case .inPopover(let control) = target { return control }
            return nil
        }
        .onAppear {
            if let initial = content.initialFocus { controller.router.handle(.focusInside(.inPopover(initial))) }
        }
        .task(id: controller.discards.nextExpiry) {
            guard let expiry = controller.discards.nextExpiry else { return }
            try? await Task.sleep(for: .seconds(max(0, expiry.timeIntervalSinceNow)))
            guard !Task.isCancelled else { return }
            controller.commitExpiredDiscards()
        }
        .task(id: copied) {
            guard copied != nil else { return }
            try? await Task.sleep(for: .seconds(2))
            if !Task.isCancelled { copied = nil }
        }
    }

    /// Open D-02 for `id`: the blocked later actions are the issues it lists; a kept draft returns.
    private func openConflict(_ id: String) {
        let issues = runtimeIssues
        guard let issue = issues.first(where: { $0.id == id }) else { return }
        let blocked = issue.dependentIDs.map { dependent in
            SyncBlockedAction(id: dependent, summary: issues.first { $0.id == dependent }?.summary ?? "Saved action")
        }
        var model = SyncConflictModel(issue: issue, accountVersion: nil, blocked: blocked)
        if let draft = drafts[id] { model.restore(draft) }
        conflict = model
    }

    /// Back, Cancel or closing keeps every original and the decision draft; nothing is submitted.
    private func closeConflict() {
        if let model = conflict { drafts[model.issueID] = model.draft }
        conflict = nil
        if let initial = controller.popoverContent().initialFocus {
            controller.router.handle(.focusInside(.inPopover(initial)))
        }
    }

    private func recoveryView(_ recovery: SyncRecoveryContent) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Label(recovery.title, systemImage: "arrow.triangle.2.circlepath")
                .font(.headline)
                .foregroundStyle(recovery.condition.isBlocking ? .orange : .primary)
            Text(recovery.detail).foregroundStyle(.secondary)
            HStack(spacing: 10) {
                ForEach(recovery.actions, id: \.self) { action in
                    switch action {
                    case .copyReference(let reference): copyButton(reference, control: .recovery(action))
                    default:
                        Button(Self.title(of: action)) { perform(action) }
                            .focused($focus, equals: .recovery(action))
                    }
                }
            }
        }
        .fixedSize(horizontal: false, vertical: true)
        .accessibilityElement(children: .contain)
    }

    private static func title(of action: SyncRecoveryAction) -> String {
        switch action {
        case .updateApp: return "Update app"
        case .tryAgain: return "Try again"
        case .rebuildSyncedCopy: return "Rebuild synced copy"
        case .exportSavedData: return "Export saved data"
        case .openImportReport: return "Open import report"
        case .copyReference: return "Copy"
        }
    }

    private func perform(_ action: SyncRecoveryAction) {
        switch action {
        case .tryAgain: Task { await controller.syncNow() }
        case .updateApp:
            if let url = URL(string: "macappstore://apps.apple.com/") { NSWorkspace.shared.open(url) }
        case .openImportReport:
            if let file = controller.host.importer.upgradeFiles().report { NSWorkspace.shared.activateFileViewerSelecting([file]) }
        case .rebuildSyncedCopy, .exportSavedData, .copyReference:
            break  // wired by the workspace's recovery API (not present yet); see PR-46 notes
        }
    }

    private func runtimeIssueRow(_ issue: SyncPopoverRuntimeIssue) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(issue.attempted).font(.callout.weight(.medium)).lineLimit(1)
            Text(issue.why).font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            if issue.laterActions > 0 {
                Text("\(issue.laterActions) later action\(issue.laterActions == 1 ? "" : "s") need your decision")
                    .font(.callout)
            }
            HStack(spacing: 10) {
                if let reference = issue.referenceID { copyButton(reference, control: .runtimeCopy(issue.id)) }
                Button("Review") { openConflict(issue.id) }
                    .accessibilityLabel(issue.actionAccessibilityLabel)
                    .focused($focus, equals: .openConflict(issue.id))
            }
        }
    }

    private func sections(_ content: SyncPopoverContent) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            if let recovery = content.recovery { recoveryView(recovery) }
            if let notice = content.notice { noticeView(notice) }
            if content.lastSynced != nil || content.queue != nil {
                VStack(alignment: .leading, spacing: 4) {
                    if let lastSynced = content.lastSynced { Text(lastSynced) }
                    if let queue = content.queue { Text(queue).foregroundStyle(.secondary) }
                }
                .font(.callout)
            }
            if !content.issues.isEmpty || !content.runtimeIssues.isEmpty { issuesView(content) }
            if content.syncNowShown {
                Button("Sync now") {
                    Task { await controller.syncNow() }
                }
                .disabled(!content.syncNowEnabled)
                .focused($focus, equals: .syncNow)
            }
            if case .offline(_, let reference)? = content.notice, let reference {
                copyButton(reference, control: .offlineCopy)
            }
            if let email = content.email {
                Divider()
                VStack(alignment: .leading, spacing: 6) {
                    Text(email)
                        .font(.callout)
                        .fixedSize(horizontal: false, vertical: true)
                    Button(AccountMenuItems.signOutTitle) { controller.requestSignOut() }
                        .focused($focus, equals: .signOut)
                }
            }
            upgradeLines(content)
        }
        .padding(16)
        .fixedSize(horizontal: false, vertical: true)
    }

    @ViewBuilder
    private func noticeView(_ notice: SyncPopoverContent.Notice) -> some View {
        switch notice {
        case .accountLess(let text):
            VStack(alignment: .leading, spacing: 8) {
                Text(text.title).font(.headline)
                if let detail = text.detail { Text(detail).foregroundStyle(.secondary) }
                Button(AccountMenuItems.signInTitle) { controller.beginSignIn(from: .popover) }
                    .buttonStyle(.borderedProminent)
                    .focused($focus, equals: .signIn)
            }
            .fixedSize(horizontal: false, vertical: true)
        case .sessionEnded(let text):
            VStack(alignment: .leading, spacing: 8) {
                Label(text.title, systemImage: "person.crop.circle.badge.exclamationmark")
                    .font(.headline)
                    .foregroundStyle(.orange)
                if let detail = text.detail { Text(detail).foregroundStyle(.secondary) }
                Button("Sign in again") { controller.beginSignIn(from: .popover) }
                    .buttonStyle(.borderedProminent)
                    .focused($focus, equals: .signInAgain)
            }
            .fixedSize(horizontal: false, vertical: true)
        case .failing(let text, let reference):
            VStack(alignment: .leading, spacing: 6) {
                Label(text.title, systemImage: "exclamationmark.triangle")
                    .font(.headline)
                    .foregroundStyle(.orange)
                if let detail = text.detail { Text(detail) }
                if let footnote = text.footnote {
                    Text(footnote).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                }
                if let reference { copyButton(reference, control: .failingCopy) }
            }
            .fixedSize(horizontal: false, vertical: true)
        case .offline(let text, _):
            VStack(alignment: .leading, spacing: 6) {
                Text(text.title).foregroundStyle(.secondary)
                if let footnote = text.footnote {
                    Text(footnote).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                }
            }
            .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func issuesView(_ content: SyncPopoverContent) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            if let heading = content.issuesHeading {
                Text(heading).font(.headline).foregroundStyle(.orange)
            }
            ForEach(content.issues) { issue in
                issueRow(issue, content: content)
            }
            ForEach(content.runtimeIssues) { issue in runtimeIssueRow(issue) }
        }
    }

    @ViewBuilder
    private func issueRow(_ issue: SyncPopoverIssue, content: SyncPopoverContent) -> some View {
        if issue.discarded {
            HStack {
                Text("Outcome discarded")
                Button("Undo") { controller.undoDiscard(issue.id) }
                    .focused($focus, equals: .undoDiscard(issue.id))
            }
            .font(.callout)
        } else {
            VStack(alignment: .leading, spacing: 4) {
                Text(issue.attempted).font(.callout.weight(.medium)).lineLimit(1)
                Text(issue.why).font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                if let outcome = issue.keptOutcome {
                    Text(outcome)
                        .font(.callout)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(8)
                        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 6))
                }
                HStack(spacing: 10) {
                    if let reference = issue.referenceID {
                        copyButton(reference, control: .issueCopy(issue.id))
                    }
                    if let outcome = issue.keptOutcome {
                        Button(copyTitle(.copyOutcome(issue.id), "Copy outcome")) {
                            copy(outcome, control: .copyOutcome(issue.id))
                        }
                        .focused($focus, equals: .copyOutcome(issue.id))
                        Button("Discard outcome") {
                            controller.discardOutcome(issue.id)
                            AccessibilityNotification.Announcement("Outcome discarded").post()
                        }
                        .accessibilityLabel(issue.actionAccessibilityLabel)
                        .focused($focus, equals: .discardOutcome(issue.id))
                    } else {
                        Button("Dismiss") {
                            let last = content.issues.count == 1
                            controller.dismissIssue(issue.id)
                            if last { AccessibilityNotification.Announcement("No sync issues").post() }
                        }
                        .accessibilityLabel(issue.actionAccessibilityLabel)
                        .focused($focus, equals: .dismiss(issue.id))
                    }
                }
            }
        }
    }

    /// "Copy" (the reference id), reading "Copied" for 2 s, announced politely.
    private func copyButton(_ reference: String, control: SyncPopoverControl) -> some View {
        HStack(spacing: 6) {
            Text("Reference ID \(reference)")
                .font(.caption.monospaced())
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .truncationMode(.middle)
                .textSelection(.enabled)
            Button(copyTitle(control, "Copy")) { copy(reference, control: control) }
                .accessibilityLabel("Copy reference ID")
                .focused($focus, equals: control)
        }
    }

    /// "Copied" for 2 s after the control copied, else its own title.
    private func copyTitle(_ control: SyncPopoverControl, _ title: String) -> String {
        copied == control ? "Copied" : title
    }

    private func copy(_ text: String, control: SyncPopoverControl) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
        copied = control
        AccessibilityNotification.Announcement("Copied").post()
    }

    @ViewBuilder
    private func upgradeLines(_ content: SyncPopoverContent) -> some View {
        let files = controller.host.importer.upgradeFiles()
        if let line = content.backupLine, let file = files.backup {
            finderLine(line, file: file, control: .backupShowInFinder)
        }
        if let line = content.reportLine, let file = files.report {
            finderLine(line, file: file, control: .reportShowInFinder)
        }
        if let line = content.laterFileLine, let file = files.laterFile {
            finderLine(line, file: file, control: .laterFileShowInFinder)
        }
    }

    /// A quiet line with "Show in Finder": Finder comes forward, and the popover closes as a
    /// transient popover does when the app loses focus.
    private func finderLine(_ line: String, file: URL, control: SyncPopoverControl) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(line)
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Button("Show in Finder") { NSWorkspace.shared.activateFileViewerSelecting([file]) }
                .font(.caption)
                .focused($focus, equals: control)
        }
    }
}
