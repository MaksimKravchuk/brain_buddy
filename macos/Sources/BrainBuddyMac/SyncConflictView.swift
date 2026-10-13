import AppKit
import BrainBuddyMacCore
import SwiftUI

/// Design D-02, "Resolve conflict", laying out `SyncConflictModel` inside the sync popover: the two
/// versions as a radio choice with no default, the blocked later actions (Keep for later / Review and
/// retry / Discard action), the named discard confirmation with Cancel focused first, and Apply choice.
/// Bounded: it scrolls inside the popover's 480 pt and shows each long text in a scrollable box.
/// `submit` hands the applied decision to the workspace; it is nil only where none can be stored, and Apply is then disabled.
struct SyncConflictView: View {
    @Binding var model: SyncConflictModel
    let blockedPreview: (SyncBlockedAction) -> String?
    let submit: ((SyncConflictResolution) -> Void)?
    let back: () -> Void

    @FocusState private var focus: Field?
    @State private var copied = false

    private enum Field: Hashable {
        case title, blockedHeading, version(SyncConflictVersion), copyEdit, keepDeleted, action(String), cancelDiscard, apply
    }

    private static func field(_ focus: SyncConflictModel.InitialFocus) -> Field {
        switch focus {
        case .title: return .title
        case .blockedHeading: return .blockedHeading
        case .cancelDiscard: return .cancelDiscard
        }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                if model.phase == .confirmingDiscard {
                    discardConfirmation
                } else {
                    sheet
                }
            }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .defaultFocus($focus, Self.field(model.initialFocus))
    }

    private var sheet: some View {
        VStack(alignment: .leading, spacing: 12) {
            Button("Back", action: back).buttonStyle(.link)
            Text(model.title).font(.headline).accessibilityAddTraits(.isHeader)
                .focusable()
                .focused($focus, equals: .title)
            if let status = model.statusLine {
                Text(status)
                    .font(.callout)
                    .foregroundStyle(model.phase == .saveFailed ? .red : .orange)
                    .accessibilityElement(children: .combine)
            }
            if model.kind == .deletedElsewhere { deletedBody } else { versionsBody }
            if let heading = model.blockedHeading { blockedBody(heading) }
            Button(model.kind == .deletedElsewhere ? "Keep item deleted" : "Apply choice") { if let resolution = model.apply() { submit?(resolution) } }
                .buttonStyle(.borderedProminent)
                .disabled(!model.applyEnabled || submit == nil)
                .focused($focus, equals: .apply)
        }
    }

    private var versionsBody: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(model.versionLabels, id: \.0) { version, label in
                let text = version == .yours ? model.yourEdit : (model.accountVersion ?? "Not available")
                Button {
                    model.select(version)
                } label: {
                    HStack(alignment: .top, spacing: 8) {
                        Image(systemName: model.selected == version ? "largecircle.fill.circle" : "circle")
                        VStack(alignment: .leading, spacing: 2) {
                            Text(label).font(.callout.weight(.medium))
                            versionText(text)
                        }
                    }
                }
                .buttonStyle(.plain)
                .disabled(!model.isEditable)
                .focused($focus, equals: .version(version))
                .accessibilityElement(children: .combine)
                .accessibilityLabel("\(label): \(text)")
                .accessibilityValue(model.selected == version ? "Selected" : "Not selected")
                .accessibilityAddTraits(.isButton)
            }
        }
    }

    /// A long version stays bounded: it scrolls in a box instead of growing the sheet.
    private func versionText(_ text: String) -> some View {
        ScrollView { Text(text).font(.callout).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }
            .frame(maxHeight: 72)
            .padding(6)
            .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 6))
    }

    private var deletedBody: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("This item was deleted on another device. Your edit is saved in this issue.")
                .font(.callout)
            versionText(model.yourEdit)
            Button(copied ? "Copied" : "Copy saved edit") {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(model.yourEdit, forType: .string)
                copied = true
                AccessibilityNotification.Announcement("Copied").post()
            }
            .focused($focus, equals: .copyEdit)
            Text("Keep item deleted closes this issue once your choice is stored. Your edit stays available in export.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private func blockedBody(_ heading: String) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(heading)
                .font(.headline)
                .accessibilityAddTraits(.isHeader)
                .focusable()
                .focused($focus, equals: .blockedHeading)
            ForEach(model.actions) { action in
                VStack(alignment: .leading, spacing: 4) {
                    Text(action.summary).font(.callout.weight(.medium))
                    Picker("Decision for \(action.summary)", selection: choiceBinding(action)) {
                        Text("Keep for later").tag(SyncDependentChoice.keepForLater)
                        Text("Review and retry").tag(SyncDependentChoice.reviewAndRetry)
                        Text("Discard action").tag(SyncDependentChoice.discard)
                    }
                    .pickerStyle(.radioGroup)
                    .disabled(!model.isEditable)
                    .focused($focus, equals: .action(action.id))
                    if let reason = model.retryUnavailableReason(for: action.id), action.choice != .reviewAndRetry {
                        Text(reason).font(.caption).foregroundStyle(.secondary)
                    }
                    if action.choice == .reviewAndRetry {
                        retryPreview(action)
                    }
                }
            }
        }
    }

    private func retryPreview(_ action: SyncBlockedAction) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            if let preview = blockedPreview(action) {
                Text(preview).font(.callout).foregroundStyle(.secondary)
            } else {
                Text("The target is unavailable. This action stays saved as an issue.")
                    .font(.callout).foregroundStyle(.secondary)
            }
            if blockedPreview(action) != nil {
                Toggle("Approve this retry", isOn: Binding(
                    get: { action.retryApproved },
                    set: { if $0 { model.approveRetry(action.id) } else { model.withdrawRetryApproval(action.id) } }
                ))
            }
        }
    }

    private func choiceBinding(_ action: SyncBlockedAction) -> Binding<SyncDependentChoice> {
        Binding(get: { action.choice }, set: { model.setChoice($0, for: action.id) })
    }

    /// D-02.12: names exactly what will not be sent; Cancel is focused first.
    private var discardConfirmation: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(model.confirmDiscardTitle).font(.headline).accessibilityAddTraits(.isHeader)
            ForEach(model.discardSummaries, id: \.self) { summary in
                Text("• \(summary)").font(.callout)
            }
            Text(model.confirmDiscardDetail).font(.callout).foregroundStyle(.secondary)
            HStack {
                Button("Cancel") { model.cancelDiscard() }
                    .keyboardShortcut(.cancelAction)
                    .focused($focus, equals: .cancelDiscard)
                Button(model.confirmDiscardButton, role: .destructive) {
                    if let resolution = model.confirmDiscard() { submit?(resolution) }
                }
                .disabled(submit == nil)
            }
        }
    }
}
