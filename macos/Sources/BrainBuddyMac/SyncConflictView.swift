import AppKit
import BrainBuddyDesign
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
            Button("Back", action: back).buttonStyle(.macText)
            Text(model.title)
                .font(MacSheetFont.heading)
                .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                .accessibilityAddTraits(.isHeader)
                .focusable()
                .focused($focus, equals: .title)
            if let status = model.statusLine {
                MacSheetStatus(
                    text: status, tone: model.phase == .saveFailed ? .danger : .warning, font: MacSheetFont.note)
                    .accessibilityElement(children: .combine)
            }
            if model.kind == .unknownOutcome {
                unknownBody
            } else {
                if model.kind == .deletedElsewhere { deletedBody } else { versionsBody }
                if let heading = model.blockedHeading { blockedBody(heading) }
                Button(model.kind == .deletedElsewhere ? "Keep item deleted" : "Apply choice") { if let resolution = model.apply() { submit?(resolution) } }
                    .buttonStyle(.macStrongPill)
                    .disabled(!model.applyEnabled || submit == nil)
                    .focused($focus, equals: .apply)
            }
        }
    }

    private var versionsBody: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(model.versionLabels, id: \.0) { version, label in
                let text = version == .yours ? model.yourEdit : (model.accountVersion ?? "Not available")
                Button {
                    model.select(version)
                } label: {
                    SyncConflictVersionOption(label: label, selected: model.selected == version) {
                        versionText(text)
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
        ScrollView { SyncConflictText(text: text) }
            .frame(maxHeight: 72)
            .syncConflictBox()
    }

    /// An uncertain send is never resolved here and never suggested as safe to retry: the runtime
    /// checks what reached the account first. Only the saved edit can be copied.
    private var unknownBody: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("We can't tell whether this change reached your account. It is kept and won't be sent again as a new change.")
                .font(MacSheetFont.note)
                .foregroundStyle(CarryOnColorStyle.coTextPrimary)
            versionText(model.yourEdit)
            Button(copied ? "Copied" : "Copy saved edit") {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(model.yourEdit, forType: .string)
                copied = true
                AccessibilityNotification.Announcement("Copied").post()
            }
            .buttonStyle(.macText)
            .focused($focus, equals: .copyEdit)
        }
    }

    private var deletedBody: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("This item was deleted on another device. Your edit is saved in this issue.")
                .font(MacSheetFont.note)
                .foregroundStyle(CarryOnColorStyle.coTextPrimary)
            versionText(model.yourEdit)
            Button(copied ? "Copied" : "Copy saved edit") {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(model.yourEdit, forType: .string)
                copied = true
                AccessibilityNotification.Announcement("Copied").post()
            }
            .buttonStyle(.macText)
            .focused($focus, equals: .copyEdit)
            Text("Keep item deleted closes this issue once your choice is stored. Your edit stays available in export.")
                .font(MacSheetFont.meta)
                .foregroundStyle(CarryOnColorStyle.coTextSecondary)
        }
    }

    private func blockedBody(_ heading: String) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(heading)
                .font(MacSheetFont.heading)
                .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                .accessibilityAddTraits(.isHeader)
                .focusable()
                .focused($focus, equals: .blockedHeading)
            ForEach(model.actions) { action in
                VStack(alignment: .leading, spacing: 4) {
                    Text(action.summary)
                        .font(MacSheetFont.noteStrong)
                        .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                    Picker("Decision for \(action.summary)", selection: choiceBinding(action)) {
                        Text("Keep for later").tag(SyncDependentChoice.keepForLater)
                        Text("Review and retry").tag(SyncDependentChoice.reviewAndRetry)
                        Text("Discard action").tag(SyncDependentChoice.discard)
                    }
                    .pickerStyle(.radioGroup)
                    .font(MacSheetFont.note)
                    .disabled(!model.isEditable)
                    .focused($focus, equals: .action(action.id))
                    if let reason = model.retryUnavailableReason(for: action.id), action.choice != .reviewAndRetry {
                        Text(reason).font(MacSheetFont.meta).foregroundStyle(CarryOnColorStyle.coTextSecondary)
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
                Text(preview).font(MacSheetFont.note).foregroundStyle(CarryOnColorStyle.coTextSecondary)
            } else {
                Text("The target is unavailable. This action stays saved as an issue.")
                    .font(MacSheetFont.note).foregroundStyle(CarryOnColorStyle.coTextSecondary)
            }
            if blockedPreview(action) != nil {
                Toggle("Approve this retry", isOn: Binding(
                    get: { action.retryApproved },
                    set: { if $0 { model.approveRetry(action.id) } else { model.withdrawRetryApproval(action.id) } }
                ))
                .font(MacSheetFont.note)
            }
        }
    }

    private func choiceBinding(_ action: SyncBlockedAction) -> Binding<SyncDependentChoice> {
        Binding(get: { action.choice }, set: { model.setChoice($0, for: action.id) })
    }

    /// D-02.12: names exactly what will not be sent; Cancel is focused first.
    private var discardConfirmation: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(model.confirmDiscardTitle)
                .font(MacSheetFont.heading)
                .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                .accessibilityAddTraits(.isHeader)
            ForEach(model.discardSummaries, id: \.self) { summary in
                Text("• \(summary)").font(MacSheetFont.note).foregroundStyle(CarryOnColorStyle.coTextPrimary)
            }
            Text(model.confirmDiscardDetail).font(MacSheetFont.note).foregroundStyle(CarryOnColorStyle.coTextSecondary)
            HStack(spacing: 8) {
                Button("Cancel") { model.cancelDiscard() }
                    .buttonStyle(.macQuietPill)
                    .keyboardShortcut(.cancelAction)
                    .focused($focus, equals: .cancelDiscard)
                Button(model.confirmDiscardButton, role: .destructive) {
                    if let resolution = model.confirmDiscard() { submit?(resolution) }
                }
                .buttonStyle(.macSecondaryPill)
                .disabled(submit == nil)
            }
        }
    }
}

// MARK: - Parts

/// One version of D-02: the radio mark, the version's label (13 semibold) and its text (`content`,
/// the bounded box).
struct SyncConflictVersionOption<Content: View>: View {
    let label: String
    let selected: Bool
    let content: Content

    init(label: String, selected: Bool, @ViewBuilder content: () -> Content) {
        self.label = label
        self.selected = selected
        self.content = content()
    }

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: selected ? "largecircle.fill.circle" : "circle")
                .font(.system(size: 14))
                .foregroundStyle(selected ? CarryOnColorStyle.coTextPrimary : CarryOnColorStyle.coMarkOpen)
            VStack(alignment: .leading, spacing: 4) {
                Text(label)
                    .font(MacSheetFont.noteStrong)
                    .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                content
            }
        }
        .contentShape(Rectangle())
    }
}

/// A version's text: 13, selectable.
struct SyncConflictText: View {
    let text: String

    var body: some View {
        Text(text)
            .font(MacSheetFont.note)
            .foregroundStyle(CarryOnColorStyle.coTextPrimary)
            .textSelection(.enabled)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

extension View {
    /// The box a long version scrolls in: `bg-ground`, radius 8, padding 6/8.
    func syncConflictBox() -> some View {
        padding(.vertical, 6)
            .padding(.horizontal, 8)
            .background(CarryOnColorStyle.coBgGround, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}
