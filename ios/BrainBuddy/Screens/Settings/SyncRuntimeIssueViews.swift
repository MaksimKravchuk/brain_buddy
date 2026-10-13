import BrainBuddyCore
import BrainBuddyPersistence
import BrainBuddyWorkspace
import SwiftUI
import UIKit

/// The shared runtime's typed issues (spec 026 M-02): each row says what happened, keeps the
/// user's text exactly as saved and shows a reference ID. All wording and legality lives in
/// `RuntimeIssuePresenter` / `ConflictDecisionDraft`; this only renders it.
struct RuntimeIssuesList: View {
    @Environment(Workspace.self) private var workspace

    var body: some View {
        let issues = workspace.runtimeIssues
        let cards = RuntimeIssuePresenter.cards(issues)
        if cards.isEmpty {
            EmptyStateView(
                title: "No sync issues",
                message: "Changes your account can't apply show up here.",
                systemImage: "checkmark.circle"
            )
        } else {
            List {
                Section {
                    ForEach(cards) { card in
                        NavigationLink {
                            RuntimeIssueDetail(issueID: card.id)
                        } label: {
                            RuntimeIssueRow(card: card)
                        }
                    }
                } header: {
                    Text("These changes couldn't be applied on your account. They are saved here, and your other changes still sync.")
                        .textCase(nil)
                }
            }
        }
    }
}

private struct RuntimeIssueRow: View {
    let card: RuntimeIssueCard

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(card.title)
                .font(BBFont.bodyMedium)
                .foregroundStyle(BBColor.textPrimary)
            Text(card.message)
                .font(BBFont.secondary)
                .foregroundStyle(BBColor.textSecondary)
            ForEach(card.savedFields, id: \.name) { field in
                Text(field.value)
                    .font(BBFont.secondary)
                    .foregroundStyle(BBColor.textPrimary)
                    .lineLimit(3)
            }
            Text("Reference ID: \(card.referenceID)")
                .font(.footnote.monospaced())
                .foregroundStyle(BBColor.textTertiary)
        }
        .padding(.vertical, BBSpacing.s1)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(card.accessibilityLabel)
    }
}

/// One issue in full: both versions side by side where they are known, the choice, the
/// blocked later actions and the named discard confirmation. Apply stores the decision through the
/// workspace; the draft waits in `FileConflictDraftStore` until it is stored.
struct RuntimeIssueDetail: View {
    @Environment(Workspace.self) private var workspace
    let issueID: String
    @State private var draft: ConflictDecisionDraft?
    /// The account's record as the runtime holds it; the revision a kept edit is decided against.
    @State private var account: AccountState = .loading
    @State private var copied = false

    private let drafts: any ConflictDraftStore = FileConflictDraftStore.applicationSupport()

    enum AccountState: Equatable {
        case loading, unreadable
        case loaded(RuntimeIssueAccountVersion)
    }

    var body: some View {
        Group {
            if let issue = workspace.runtimeIssues.first(where: { $0.id == issueID }) {
                if draft != nil {
                    content(issue)
                } else {
                    ProgressView("Loading…")
                }
            } else {
                EmptyStateView(title: "Issue resolved", message: "Nothing more to do here.", systemImage: "checkmark.circle")
            }
        }
        .task(id: workspace.syncSnapshot.lastSyncedAt) {
            if let issue = workspace.runtimeIssues.first(where: { $0.id == issueID }) { await loadAccount(issue) }
        }
    }

    /// Reads the account's record. The first read starts the draft (restoring one left from before,
    /// which submits nothing); a later read that moved the record clears approvals and asks again.
    private func loadAccount(_ issue: RustWorkspaceIssue) async {
        let version: RuntimeIssueAccountVersion?
        do {
            guard let read = try await workspace.accountVersion(ofIssue: issue.id) else { return }
            version = read
            account = .loaded(read)
        } catch RuntimeIssueResolutionError.notReady {
            return  // the runtime changed under the read: keep what is shown, the draft included
        } catch {
            version = nil
            account = .unreadable
        }
        guard var next = draft else {
            var fresh = RuntimeIssuePresenter.draft(for: issue, among: workspace.runtimeIssues, account: version)
            if let saved = drafts.load(issueID: issue.id) { fresh.restore(from: saved) }
            draft = fresh
            return
        }
        guard next.phase != .saving, let version else { return }
        next.refresh(currentRevision: version.revision)
        draft = next
    }

    private func content(_ issue: RustWorkspaceIssue) -> some View {
        let card = RuntimeIssuePresenter.card(issue)
        let dependents = RuntimeIssuePresenter.dependentSummaries(of: issue, among: workspace.runtimeIssues)
        let current = Binding<ConflictDecisionDraft>(
            get: { draft ?? RuntimeIssuePresenter.draft(for: issue, among: workspace.runtimeIssues) },
            set: { draft = $0 })
        return List {
            Section {
                Text(card.message).font(BBFont.secondary)
                if let version = card.shownVersion {
                    LabeledContent("Version you edited", value: version)
                }
            } header: {
                Text(card.title).textCase(nil)
            }
            versions(card, current)
            if !dependents.isEmpty { dependentSection(dependents, current) }
            Section {
                if card.actions.contains(.copySavedEdit) { copyButton(card) }
                Text("Reference ID: \(card.referenceID)")
                    .font(.footnote.monospaced())
                    .textSelection(.enabled)
                Button {
                    UIPasteboard.general.string = card.referenceID
                } label: {
                    Label("Copy reference ID", systemImage: "doc.on.doc")
                }
            }
            if card.kind == .versionConflict || card.kind == .deletedElsewhere { applySection(issue, card, current) }
        }
        .navigationTitle("Sync issue")
        .navigationBarTitleDisplayMode(.inline)
        .onChange(of: draft) { _, next in
            // Across Back, closing and relaunch: choices only, never submitted by being restored.
            guard let next, next.phase != .saving else { return }
            if next.isUntouched { drafts.clear(issueID: issue.id) } else { drafts.save(next, issueID: issue.id) }
        }
        .confirmationDialog(
            current.wrappedValue.discardPrompt ?? "Discard saved actions?",
            isPresented: Binding(
                get: { current.wrappedValue.phase == .confirmingDiscard },
                set: { shown in if !shown { var next = current.wrappedValue; next.cancelDiscard(); draft = next } }),
            titleVisibility: .visible
        ) {
            Button(current.wrappedValue.discardConfirmTitle, role: .destructive) {
                var next = current.wrappedValue
                next.confirmDiscard()
                draft = next
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text(ConflictDecisionDraft.discardExplanation)
        }
    }

    @ViewBuilder
    private func versions(_ card: RuntimeIssueCard, _ draft: Binding<ConflictDecisionDraft>) -> some View {
        Section {
            ForEach(card.savedFields, id: \.name) { field in
                versionRow("Your saved edit", field: field.name, text: field.value, version: .saved, draft: draft, selectable: card.kind == .versionConflict)
            }
            if card.kind == .versionConflict {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Current account version").font(BBFont.bodyMedium)
                    accountText(card)
                    selectionButton(.account, draft)
                }
            }
        } header: {
            Text(card.kind == .versionConflict ? "Choose a version" : "Your saved edit").textCase(nil)
        }
    }

    @ViewBuilder
    private func accountText(_ card: RuntimeIssueCard) -> some View {
        switch account {
        case .loading:
            Text("Loading the account's version…").font(BBFont.secondary).foregroundStyle(BBColor.textSecondary)
        case .unreadable:
            Text("Couldn't read the account's version. Nothing changes until you apply a choice.")
                .font(BBFont.secondary).foregroundStyle(BBColor.textSecondary)
        case .loaded(let version) where version.isDeleted:
            Text("This item is deleted on your account.").font(BBFont.secondary).foregroundStyle(BBColor.textSecondary)
        case .loaded(let version):
            ForEach(version.fields.sorted { $0.key < $1.key }, id: \.key) { field in
                Text("\(field.key): \(field.value)").font(BBFont.secondary).textSelection(.enabled)
            }
        }
    }

    private func versionRow(
        _ title: String, field: String, text: String, version: ConflictVersion,
        draft: Binding<ConflictDecisionDraft>, selectable: Bool
    ) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(BBFont.bodyMedium)
            Text("\(field): \(text)").font(BBFont.secondary).textSelection(.enabled)
            if selectable { selectionButton(version, draft) }
        }
    }

    private func selectionButton(_ version: ConflictVersion, _ draft: Binding<ConflictDecisionDraft>) -> some View {
        let selected = draft.wrappedValue.version == version
        return Button {
            var next = draft.wrappedValue
            next.choose(version)
            draft.wrappedValue = next
        } label: {
            Label(version == .saved ? "Use my version" : "Use account version",
                  systemImage: selected ? "largecircle.fill.circle" : "circle")
        }
        .frame(minHeight: 44)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }

    private func dependentSection(_ dependents: [DependentSummary], _ draft: Binding<ConflictDecisionDraft>) -> some View {
        Section {
            ForEach(dependents) { dependent in
                VStack(alignment: .leading, spacing: 6) {
                    Text(dependent.summary).font(BBFont.bodyMedium)
                    if let version = dependent.shownVersion {
                        Text("Current target version: \(version)").font(BBFont.meta).foregroundStyle(BBColor.textTertiary)
                    }
                    Picker("Later action", selection: Binding(
                        get: { draft.wrappedValue.choice(for: dependent.id) },
                        set: { choice in
                            var next = draft.wrappedValue
                            next.setChoice(choice, for: dependent.id)
                            draft.wrappedValue = next
                        })) {
                        Text("Keep for later").tag(DependentChoice.keepForLater)
                        if draft.wrappedValue.canRetry(dependent.id) || draft.wrappedValue.choice(for: dependent.id) == .reviewAndRetry {
                            Text("Review and retry").tag(DependentChoice.reviewAndRetry)
                        }
                        Text("Discard action").tag(DependentChoice.discard)
                    }
                    .pickerStyle(.menu)
                    if let reason = draft.wrappedValue.retryUnavailableReason(for: dependent.id) {
                        Text(reason).font(BBFont.meta).foregroundStyle(BBColor.textTertiary)
                    }
                    if draft.wrappedValue.choice(for: dependent.id) == .reviewAndRetry {
                        Toggle("Approve retrying this action", isOn: Binding(
                            get: { draft.wrappedValue.approvedRetries.contains(dependent.id) },
                            set: { on in
                                var next = draft.wrappedValue
                                if on {
                                    next.approveRetry(for: dependent.id)
                                } else {
                                    next.withdrawRetryApproval(for: dependent.id)
                                }
                                draft.wrappedValue = next
                            }))
                    }
                }
                .accessibilityElement(children: .contain)
            }
            if draft.wrappedValue.discardPrompt != nil {
                Button("Discard…", role: .destructive) {
                    var next = draft.wrappedValue
                    next.requestDiscard()
                    draft.wrappedValue = next
                }
            }
        } header: {
            Text(draft.wrappedValue.title).textCase(nil).accessibilityAddTraits(.isHeader)
        } footer: {
            Text("Kept actions stay visible here. Nothing is sent or discarded until you apply your choice.")
        }
    }

    private func applySection(
        _ issue: RustWorkspaceIssue, _ card: RuntimeIssueCard, _ draft: Binding<ConflictDecisionDraft>
    ) -> some View {
        let value = draft.wrappedValue
        let ready: Bool = {
            if card.kind == .deletedElsewhere { return true }
            if case .loaded = account { return true }
            return false
        }()
        return Section {
            Button(card.kind == .deletedElsewhere ? "Keep item deleted" : "Apply choice") { apply(issue) }
                .disabled(!value.canApply || !ready)
        } footer: {
            switch value.phase {
            case .saving, .saveFailed, .changedAgain:
                Text(value.title)
            case .choosing, .confirmingDiscard:
                if !ready {
                    Text(account == .unreadable
                         ? "Couldn't read the account's version. Try again once you're back online."
                         : "Loading the account's version…")
                } else if card.kind == .deletedElsewhere {
                    Text("Keeping it deleted closes this issue once it is stored. Your edit stays saved for export.")
                } else {
                    Text("Both versions stay saved until you apply a choice.")
                }
            }
        }
    }

    /// Stores the decision once. The detail closes only after the runtime stored it durably (the
    /// issue leaves the list); a record that changed again or any refusal keeps the draft.
    private func apply(_ issue: RustWorkspaceIssue) {
        guard var next = draft, let decision = next.apply() else { return }
        draft = next
        let resolution = RuntimeIssueResolution(issueID: issue.id, decision: decision)
        Task {
            let outcome = await workspace.submit(resolution)
            switch outcome {
            case .resolved, .gone:
                drafts.clear(issueID: issue.id)
                draft = nil
            case .changedAgain(let current):
                if let current { account = .loaded(current) }
                var done = draft ?? next
                done.finish(outcome)
                draft = done
            case .failed:
                var done = draft ?? next
                done.finish(outcome)
                draft = done
            }
        }
    }

    private func copyButton(_ card: RuntimeIssueCard) -> some View {
        Button {
            UIPasteboard.general.string = card.savedFields.map(\.value).joined(separator: "\n")
            copied = true
        } label: {
            Label(copied ? "Copied" : "Copy saved edit", systemImage: "doc.on.doc")
        }
    }
}

/// M-03: what the shared runtime reports about recovery (a newer app needed to open the store, a
/// synced-copy rebuild in progress or failed), in words, with its actions. Waiting changes and
/// saved issues are always named as kept. "Try again" on a failed rebuild runs the rebuild; if no
/// transport can run it, it says so rather than pretend.
struct SyncRecoveryRow: View {
    @Environment(Workspace.self) private var workspace
    @State private var notice: String?
    @State private var copied = false

    var body: some View {
        let card = RuntimeRecoveryCard(workspace.syncRecovery, pendingCount: workspace.pendingChangeCount)
        if card != nil || notice != nil {
            VStack(alignment: .leading, spacing: BBSpacing.s2) {
                if let card {
                    Label(card.title, systemImage: "arrow.triangle.2.circlepath")
                        .font(BBFont.bodyMedium)
                        .foregroundStyle(card.isBlocking ? BBColor.warningText : BBColor.textPrimary)
                        .accessibilityAddTraits(.isHeader)
                    Text(card.detail).font(BBFont.secondary).foregroundStyle(BBColor.textSecondary)
                    ForEach(Array(card.actions.enumerated()), id: \.offset) { _, action in
                        actionButton(action, card: card)
                    }
                }
                if let notice {
                    Text(notice).font(BBFont.secondary).foregroundStyle(BBColor.textSecondary)
                }
            }
            .accessibilityElement(children: .contain)
        }
    }

    @ViewBuilder
    private func actionButton(_ action: RuntimeRecoveryCard.Action, card: RuntimeRecoveryCard) -> some View {
        switch action {
        case .updateApp:
            Button("Update app") {
                if let url = URL(string: "itms-apps://apps.apple.com/") { UIApplication.shared.open(url) }
            }
            .frame(minHeight: 44)
        case .tryAgain:
            Button("Try again") {
                Task {
                    if case .rebuildFailed = card.condition {
                        notice = await workspace.rebuildSyncedCopy().notice
                    } else {
                        await workspace.syncNow()
                    }
                }
            }
            .frame(minHeight: 44)
        case .copyReference(let reference):
            HStack {
                Text("Reference ID: \(reference)").font(.footnote.monospaced()).textSelection(.enabled)
                Button(copied ? "Copied" : "Copy") {
                    UIPasteboard.general.string = reference
                    copied = true
                }
                .accessibilityLabel("Copy reference ID")
            }
        }
    }
}
