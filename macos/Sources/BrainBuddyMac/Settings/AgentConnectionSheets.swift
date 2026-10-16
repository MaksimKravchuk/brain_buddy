import BrainBuddyAPI
import BrainBuddyDesign
import BrainBuddyMacCore
import SwiftUI

/// What each agent sheet says and which button Return presses (design G-07, G-08). Pure, so tests read
/// it without drawing.
enum AgentSheetPlan {
    static let bearerLabel = "Bearer token", apiKeyLabel = "API key"
    static let nameLabel = "Name", addressLabel = "Address", credentialLabel = "Credential"

    static func title(_ mode: AgentEditorMode) -> String {
        switch mode {
        case .add: AgentsCopy.addNewAgent
        case .replaceCredential(let c): AgentsCopy.replaceCredential(for: c.name)
        case .edit(let c): c.name
        case .delete(let c): AgentsCopy.delete(c.name)
        }
    }

    static func submitTitle(_ mode: AgentEditorMode, phase: AgentEditorPhase) -> String {
        switch (mode, phase) {
        case (.add, .adding): AgentsCopy.adding
        case (.add, .testing): AgentsCopy.testing
        case (.add, _): AgentsCopy.addAndTest
        case (.replaceCredential, _): AgentsCopy.replace
        case (.edit, _): AgentsCopy.save
        case (.delete, _): "Delete"
        }
    }

    /// Delete is never the default button: Return presses Cancel (030-FR-033).
    static func returnPressesCancel(_ mode: AgentEditorMode) -> Bool {
        if case .delete = mode { return true }
        return false
    }

    static func showsSecret(_ mode: AgentEditorMode) -> Bool {
        switch mode {
        case .add, .replaceCredential: true
        default: false
        }
    }

    static func showsDetails(_ mode: AgentEditorMode) -> Bool {
        switch mode {
        case .add, .edit: true
        default: false
        }
    }
}

/// G-07 and G-08: one 440 pt sheet for Add, Replace credential, Edit and Delete over an
/// `AgentConnectionEditor`. Secrets are in secure fields only and the editor empties them.
struct AgentEditorSheet: View {
    enum Field: Hashable { case name, address, secret, password }

    @Bindable var editor: AgentConnectionEditor
    let onClose: () -> Void
    @FocusState private var focus: Field?

    private var mode: AgentEditorMode { editor.mode }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            MacSheetHeader(title: AgentSheetPlan.title(mode))
            if case .delete = mode {
                Text(AgentsCopy.deleteNote).font(MacSheetFont.body)
                    .foregroundStyle(CarryOnColorStyle.coTextSecondary).fixedSize(horizontal: false, vertical: true)
            }
            Group {
                if AgentSheetPlan.showsDetails(mode) { AgentDetailFields(editor: editor, focus: $focus) }
                if AgentSheetPlan.showsSecret(mode) {
                    labelled(AgentSheetPlan.credentialLabel, helper: AgentsCopy.secretHelper) {
                        SecureField(AgentSheetPlan.credentialLabel, text: $editor.secret)
                            .textFieldStyle(.plain).macSheetField().focused($focus, equals: .secret)
                    }
                }
                if editor.needsPassword {
                    labelled(AgentsCopy.currentPassword, helper: editor.destinationChanged ? AgentsCopy.confirmDestination : nil) {
                        SecureField(AgentsCopy.currentPassword, text: $editor.password)
                            .textFieldStyle(.plain).macSheetField().focused($focus, equals: .password)
                            .onSubmit { if !AgentSheetPlan.returnPressesCancel(mode) { submit() } }
                    }
                }
            }
            .disabled(editor.isBusy)
            if case .failed(let notice) = editor.phase { failure(notice) }
            buttons
        }
        .padding(20)
        .frame(width: 440)
        .macSheetSurface()
        .onExitCommand(perform: cancel)
        .onChange(of: editor.phase) { _, phase in
            if phase == .done { onClose() }
            if case .failed(let notice) = phase, notice.failure == .wrongPassword { focus = .password }
        }
        .onDisappear { editor.dismiss() }
    }

    private var buttons: some View {
        HStack(spacing: 10) {
            Spacer()
            let cancelButton = Button(AgentsCopy.cancel, action: cancel).buttonStyle(.carryOnQuiet).disabled(editor.isBusy)
            let submitButton = Button(AgentSheetPlan.submitTitle(mode, phase: editor.phase), action: submit)
                .buttonStyle(AgentSheetPlan.returnPressesCancel(mode) ? .carryOnSecondary : .carryOnPrimary)
                .disabled(!editor.canSubmit)
            if AgentSheetPlan.returnPressesCancel(mode) {
                cancelButton.keyboardShortcut(.defaultAction)
                submitButton
            } else {
                cancelButton.keyboardShortcut(.cancelAction)
                submitButton.keyboardShortcut(.defaultAction)
            }
        }
    }

    private func failure(_ notice: AgentNotice) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            MacSheetStatus(text: notice.message, tone: .danger, font: MacSheetFont.note)
            if let reference = notice.reference {
                Text(AgentsCopy.reference(reference)).font(MacSheetFont.reference)
                    .foregroundStyle(CarryOnColorStyle.coTextSecondary).textSelection(.enabled)
            }
        }
    }

    private func submit() { Task { await editor.submit() } }

    private func cancel() { if !editor.isBusy { onClose() } }

    private func labelled<Content: View>(
        _ label: String, helper: String?, @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label).font(MacSheetFont.metaStrong).foregroundStyle(CarryOnColorStyle.coTextSecondary)
            content()
            if let helper {
                Text(helper).font(MacSheetFont.meta).foregroundStyle(CarryOnColorStyle.coTextSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}
