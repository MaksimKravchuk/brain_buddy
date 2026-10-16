import AppKit
import BrainBuddyCore
import BrainBuddyDesign
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
    /// Opening a conflict reads the account's record first; "Review" waits for it.
    @State private var openingConflict = false
    /// What "Try again" on a failed rebuild last told the person (a rebuild that could not run says so).
    @State private var rebuildNotice: String?

    private var runtimeIssues: [SyncRuntimeIssue] { controller.workspace.runtimeIssues.map(SyncRuntimeIssue.init) }

    var body: some View {
        let content = SyncPopoverModel.adding(
            runtimeIssues: runtimeIssues, recovery: controller.recoveryCondition,
            pendingCount: controller.workspace.syncSnapshot.pendingCount, to: controller.popoverContent()
        )
        Group {
            if let model = Binding($conflict) {
                SyncConflictView(
                    model: model, blockedPreview: { action in "Retry: \(action.summary)" }, submit: submit,
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
        .task(id: conflict?.issueID) {
            // The account's record moves when a sync brings a newer one; the draft is kept (D-02.08).
            guard conflict != nil else { return }
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(5))
                guard !Task.isCancelled, var model = conflict, model.isEditable else { continue }
                await controller.refreshConflict(&model)
                if conflict?.issueID == model.issueID, conflict?.isEditable == true { conflict = model }
            }
        }
        .onChange(of: conflict?.draft) { _, _ in
            if let model = conflict, model.isEditable || model.phase == .confirmingDiscard { controller.keepDraft(model) }
        }
        .onChange(of: runtimeIssues.map(\.id)) { _, ids in
            // Resolved elsewhere while open: nothing is left to decide here.
            if let model = conflict, model.phase != .saving, !ids.contains(model.issueID) {
                controller.discardDraft(issueID: model.issueID)
                conflict = nil
            }
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

    /// Open D-02 for `id`: the account's record is read first, the blocked later actions are the
    /// issues it lists, and a kept draft returns (restoring submits nothing).
    private func openConflict(_ id: String) {
        guard !openingConflict else { return }
        openingConflict = true
        Task {
            conflict = await controller.openConflict(id)
            openingConflict = false
        }
    }

    /// Back, Cancel or closing keeps every original and the decision draft; nothing is submitted.
    private func closeConflict() {
        if let model = conflict, model.phase != .saving { controller.keepDraft(model) }
        conflict = nil
        if let initial = controller.popoverContent().initialFocus {
            controller.router.handle(.focusInside(.inPopover(initial)))
        }
    }

    /// Apply: the decision goes to the workspace once. The detail closes only when it is stored
    /// durably; a changed record or a failure keeps it open with the draft.
    private func submit(_ resolution: SyncConflictResolution) {
        Task {
            let outcome = await controller.submit(resolution)
            guard var model = conflict, model.issueID == resolution.issueID else {
                if outcome == .resolved || outcome == .gone { controller.discardDraft(issueID: resolution.issueID) }
                return
            }
            model.finish(outcome)
            switch outcome {
            case .resolved, .gone:
                controller.discardDraft(issueID: model.issueID)
                conflict = nil
                AccessibilityNotification.Announcement("Choice saved").post()
                if let initial = controller.popoverContent().initialFocus {
                    controller.router.handle(.focusInside(.inPopover(initial)))
                }
            case .changedAgain, .failed:
                conflict = model
                controller.keepDraft(model)
            }
        }
    }

    private func recoveryView(_ recovery: SyncRecoveryContent) -> some View {
        SyncPopoverNotice(
            title: recovery.title, systemImage: "arrow.triangle.2.circlepath",
            tone: recovery.condition.isBlocking ? .warning : .primary, detail: recovery.detail
        ) {
            HStack(spacing: 8) {
                ForEach(recovery.actions, id: \.self) { action in
                    switch action {
                    case .copyReference(let reference): copyButton(reference, control: .recovery(action))
                    default:
                        Button(Self.title(of: action)) { perform(action, recovery: recovery) }
                            .buttonStyle(.carryOnSecondary)
                            .focused($focus, equals: .recovery(action))
                    }
                }
            }
        }
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

    private func perform(_ action: SyncRecoveryAction, recovery: SyncRecoveryContent) {
        switch action {
        case .tryAgain:
            if case .rebuildFailed = recovery.condition {
                Task { rebuildNotice = await controller.rebuildSyncedCopy() }
            } else {
                Task { await controller.syncNow() }
            }
        case .rebuildSyncedCopy:
            Task { rebuildNotice = await controller.rebuildSyncedCopy() }
        case .updateApp:
            rebuildNotice = RuntimeRecoveryCard.updateHelp  // no store page of its own to open
        case .openImportReport:
            if let file = controller.host.importer.upgradeFiles().report { NSWorkspace.shared.activateFileViewerSelecting([file]) }
        case .exportSavedData, .copyReference:
            break  // Export has no entry point yet; the reference Copy is its own button.
        }
    }

    private func runtimeIssueRow(_ issue: SyncPopoverRuntimeIssue) -> some View {
        SyncPopoverIssueCard(attempted: issue.attempted, why: issue.why, laterActions: issue.laterActions) {
            if let reference = issue.referenceID { copyButton(reference, control: .runtimeCopy(issue.id)) }
            Button("Review") { openConflict(issue.id) }
                .buttonStyle(.carryOnSecondary)
                .disabled(openingConflict)
                .accessibilityLabel(issue.actionAccessibilityLabel)
                .focused($focus, equals: .openConflict(issue.id))
        }
    }

    private func sections(_ content: SyncPopoverContent) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            if let recovery = content.recovery { recoveryView(recovery) }
            if let rebuildNotice {
                Text(rebuildNotice)
                    .font(MacSheetFont.note)
                    .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityElement(children: .combine)
            }
            if let notice = content.notice { noticeView(notice) }
            if content.lastSynced != nil || content.queue != nil {
                SyncPopoverLines(lastSynced: content.lastSynced, queue: content.queue)
            }
            if !content.issues.isEmpty || !content.runtimeIssues.isEmpty { issuesView(content) }
            if content.syncNowShown {
                Button("Sync now") {
                    Task { await controller.syncNow() }
                }
                .buttonStyle(.carryOnSecondary)
                .disabled(!content.syncNowEnabled)
                .focused($focus, equals: .syncNow)
            }
            if case .offline(_, let reference)? = content.notice, let reference {
                copyButton(reference, control: .offlineCopy)
            }
            if let email = content.email {
                MacSheetDivider()
                SyncPopoverAccount(email: email) {
                    Button(AccountMenuItems.signOutTitle) { controller.requestSignOut() }
                        .buttonStyle(.macText)
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
            SyncPopoverNotice(title: text.title, detail: text.detail) {
                Button(AccountMenuItems.signInTitle) { controller.beginSignIn(from: .popover) }
                    .buttonStyle(.carryOnStrong)
                    .focused($focus, equals: .signIn)
                    .padding(.top, 2)
            }
        case .sessionEnded(let text):
            SyncPopoverNotice(
                title: text.title, systemImage: "person.crop.circle.badge.exclamationmark", tone: .warning,
                detail: text.detail
            ) {
                Button("Sign in again") { controller.beginSignIn(from: .popover) }
                    .buttonStyle(.carryOnStrong)
                    .focused($focus, equals: .signInAgain)
                    .padding(.top, 2)
            }
        case .failing(let text, let reference):
            SyncPopoverNotice(
                title: text.title, systemImage: "exclamationmark.triangle", tone: .warning, detail: text.detail,
                detailTone: .primary, footnote: text.footnote
            ) {
                if let reference { copyButton(reference, control: .failingCopy) }
            }
        case .offline(let text, _):
            SyncPopoverNotice(
                title: text.title, tone: .secondary, titleFont: MacSheetFont.note, footnote: text.footnote
            ) {
                EmptyView()
            }
        }
    }

    private func issuesView(_ content: SyncPopoverContent) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            if let heading = content.issuesHeading {
                MacSheetStatus(text: heading, tone: .warning)
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
            HStack(spacing: 8) {
                Text("Outcome discarded")
                    .font(MacSheetFont.note)
                    .foregroundStyle(CarryOnColorStyle.coTextSecondary)
                Button("Undo") { controller.undoDiscard(issue.id) }
                    .buttonStyle(.macText)
                    .focused($focus, equals: .undoDiscard(issue.id))
            }
        } else {
            SyncPopoverIssueCard(attempted: issue.attempted, why: issue.why, keptOutcome: issue.keptOutcome) {
                if let reference = issue.referenceID {
                    copyButton(reference, control: .issueCopy(issue.id))
                }
                if let outcome = issue.keptOutcome {
                    Button(copyTitle(.copyOutcome(issue.id), "Copy outcome")) {
                        copy(outcome, control: .copyOutcome(issue.id))
                    }
                    .buttonStyle(.macText)
                    .focused($focus, equals: .copyOutcome(issue.id))
                    Button("Discard outcome") {
                        controller.discardOutcome(issue.id)
                        AccessibilityNotification.Announcement("Outcome discarded").post()
                    }
                    .buttonStyle(.macText)
                    .accessibilityLabel(issue.actionAccessibilityLabel)
                    .focused($focus, equals: .discardOutcome(issue.id))
                } else {
                    Button("Dismiss") {
                        let last = content.issues.count == 1
                        controller.dismissIssue(issue.id)
                        if last { AccessibilityNotification.Announcement("No sync issues").post() }
                    }
                    .buttonStyle(.macText)
                    .accessibilityLabel(issue.actionAccessibilityLabel)
                    .focused($focus, equals: .dismiss(issue.id))
                }
            }
        }
    }

    /// "Copy" (the reference id), reading "Copied" for 2 s, announced politely.
    private func copyButton(_ reference: String, control: SyncPopoverControl) -> some View {
        HStack(spacing: 8) {
            MacSheetReference(reference: reference)
                .lineLimit(1)
                .truncationMode(.middle)
            Button(copyTitle(control, "Copy")) { copy(reference, control: control) }
                .buttonStyle(.macText)
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
                .font(MacSheetFont.meta)
                .foregroundStyle(CarryOnColorStyle.coTextSecondary)
                .fixedSize(horizontal: false, vertical: true)
            Button("Show in Finder") { NSWorkspace.shared.activateFileViewerSelecting([file]) }
                .buttonStyle(.macText)
                .focused($focus, equals: control)
        }
    }
}

// MARK: - Parts

/// A notice or recovery block of X-02: the heading (with its glyph and tone), the 13 detail, the
/// selectable 12 footnote and the block's actions.
struct SyncPopoverNotice<Actions: View>: View {
    let title: String
    var systemImage: String?
    var tone: MacSheetTone
    var titleFont: Font
    var detail: String?
    var detailTone: MacSheetTone
    var footnote: String?
    let actions: Actions

    init(
        title: String, systemImage: String? = nil, tone: MacSheetTone = .primary,
        titleFont: Font = MacSheetFont.heading, detail: String? = nil, detailTone: MacSheetTone = .secondary,
        footnote: String? = nil, @ViewBuilder actions: () -> Actions
    ) {
        self.title = title
        self.systemImage = systemImage
        self.tone = tone
        self.titleFont = titleFont
        self.detail = detail
        self.detailTone = detailTone
        self.footnote = footnote
        self.actions = actions()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            MacSheetStatus(text: title, systemImage: systemImage, tone: tone, font: titleFont)
            if let detail {
                Text(detail)
                    .font(MacSheetFont.note)
                    .foregroundStyle(detailTone.style)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let footnote {
                Text(footnote)
                    .font(MacSheetFont.meta)
                    .foregroundStyle(CarryOnColorStyle.coTextSecondary)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
            }
            actions
        }
        .fixedSize(horizontal: false, vertical: true)
    }
}

/// When it last synced (13) and what waits (13, secondary).
struct SyncPopoverLines: View {
    let lastSynced: String?
    let queue: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            if let lastSynced {
                Text(lastSynced).foregroundStyle(CarryOnColorStyle.coTextPrimary)
            }
            if let queue {
                Text(queue).foregroundStyle(CarryOnColorStyle.coTextSecondary)
            }
        }
        .font(MacSheetFont.note)
    }
}

/// One issue: what was attempted (13 semibold), why (13 secondary), the kept outcome in a
/// `bg-ground` box or the count of later actions, then the issue's actions.
struct SyncPopoverIssueCard<Actions: View>: View {
    let attempted: String
    let why: String
    var keptOutcome: String?
    var laterActions: Int
    let actions: Actions

    init(
        attempted: String, why: String, keptOutcome: String? = nil, laterActions: Int = 0,
        @ViewBuilder actions: () -> Actions
    ) {
        self.attempted = attempted
        self.why = why
        self.keptOutcome = keptOutcome
        self.laterActions = laterActions
        self.actions = actions()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(attempted)
                .font(MacSheetFont.noteStrong)
                .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                .lineLimit(1)
            Text(why)
                .font(MacSheetFont.note)
                .foregroundStyle(CarryOnColorStyle.coTextSecondary)
                .fixedSize(horizontal: false, vertical: true)
            if let keptOutcome {
                Text(keptOutcome)
                    .font(MacSheetFont.note)
                    .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(8)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(CarryOnColorStyle.coBgGround, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            }
            if laterActions > 0 {
                Text("\(laterActions) later action\(laterActions == 1 ? "" : "s") need your decision")
                    .font(MacSheetFont.note)
                    .foregroundStyle(CarryOnColorStyle.coTextPrimary)
            }
            HStack(spacing: 12) { actions }
                .padding(.top, 4)
        }
    }
}

/// The signed-in email (13) and its "Sign out…".
struct SyncPopoverAccount<SignOut: View>: View {
    let email: String
    let signOut: SignOut

    init(email: String, @ViewBuilder signOut: () -> SignOut) {
        self.email = email
        self.signOut = signOut()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(email)
                .font(MacSheetFont.note)
                .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                .fixedSize(horizontal: false, vertical: true)
            signOut
        }
    }
}
