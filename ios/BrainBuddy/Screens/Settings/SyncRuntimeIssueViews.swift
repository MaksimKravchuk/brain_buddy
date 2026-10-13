import BrainBuddyCore
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
/// blocked later actions and the named discard confirmation.
struct RuntimeIssueDetail: View {
    @Environment(Workspace.self) private var workspace
    let issueID: String
    @State private var draft: ConflictDecisionDraft?
    @State private var copied = false

    var body: some View {
        if let issue = workspace.runtimeIssues.first(where: { $0.id == issueID }) {
            content(issue)
        } else {
            EmptyStateView(title: "Issue resolved", message: "Nothing more to do here.", systemImage: "checkmark.circle")
        }
    }

    private func content(_ issue: RustWorkspaceIssue) -> some View {
        let card = RuntimeIssuePresenter.card(issue)
        let dependents = RuntimeIssuePresenter.dependentSummaries(of: issue, among: workspace.runtimeIssues)
        let current = Binding<ConflictDecisionDraft>(
            get: { draft ?? ConflictDecisionDraft(dependentIDs: issue.dependentIDs, shownRevision: issue.shownBaseRevision) },
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
            if card.kind == .versionConflict { applySection(current) }
        }
        .navigationTitle("Sync issue")
        .navigationBarTitleDisplayMode(.inline)
        .onChange(of: issue.shownBaseRevision) { _, revision in
            var next = current.wrappedValue
            next.refresh(currentRevision: revision)
            draft = next
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
                    Text("Open the item to read its current text. Nothing changes until you apply a choice.")
                        .font(BBFont.secondary).foregroundStyle(BBColor.textSecondary)
                    selectionButton(.account, draft)
                }
            }
        } header: {
            Text(card.kind == .versionConflict ? "Choose a version" : "Your saved edit").textCase(nil)
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
                        Text("Review and retry").tag(DependentChoice.reviewAndRetry)
                        Text("Discard action").tag(DependentChoice.discard)
                    }
                    .pickerStyle(.menu)
                    if draft.wrappedValue.choice(for: dependent.id) == .reviewAndRetry {
                        Toggle("Approve retrying this action", isOn: Binding(
                            get: { draft.wrappedValue.approvedRetries.contains(dependent.id) },
                            set: { on in
                                var next = draft.wrappedValue
                                if on { next.approveRetry(for: dependent.id) }
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

    private func applySection(_ draft: Binding<ConflictDecisionDraft>) -> some View {
        Section {
            Button("Apply choice") {}
                .disabled(true)
        } footer: {
            Text(draft.wrappedValue.phase == .changedAgain
                 ? "This task changed again. Review both versions."
                 : "Saving a choice isn't available in this version of the app yet. Both versions stay saved.")
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
