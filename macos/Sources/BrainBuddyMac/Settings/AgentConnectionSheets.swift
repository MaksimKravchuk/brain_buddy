import BrainBuddyAgents
import BrainBuddyAPI
import BrainBuddyDesign
import BrainBuddyMacCore
import Observation
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

/// The Add sheet's two presentation stages share one editor. Opening the password stage never
/// sends a request; a rejection returns to the form because the editor clears both secrets.
@MainActor
@Observable
final class AgentEditorSheetFlow {
    private(set) var confirmingAdd = false

    func performPrimary(editor: AgentConnectionEditor) async {
        if editor.mode == .add, !confirmingAdd {
            guard editor.canConfirmAdd else { return }
            confirmingAdd = true
            return
        }
        guard editor.canSubmit else { return }
        await editor.submit()
        if case .failed = editor.phase { confirmingAdd = false }
    }
}

/// G-07 and G-08: M30's Add form and proof stage, and the existing other agent-operation sheets.
/// Secrets stay in secure fields, and the same editor empties them on completion or dismissal.
struct AgentEditorSheet: View {
    enum Field: Hashable { case name, address, secret, password }

    @Bindable var editor: AgentConnectionEditor
    let onClose: () -> Void
    @FocusState private var focus: Field?
    @State private var flow: AgentEditorSheetFlow

    init(editor: AgentConnectionEditor, onClose: @escaping () -> Void, flow: AgentEditorSheetFlow = AgentEditorSheetFlow()) {
        self.editor = editor
        self.onClose = onClose
        _flow = State(initialValue: flow)
    }

    private var mode: AgentEditorMode { editor.mode }
    private var isAdd: Bool { mode == .add }
    private var initialField: Field {
        if isAdd, flow.confirmingAdd { return .password }
        if isAdd, case .failed = editor.phase { return .secret }
        return .name
    }

    var body: some View {
        VStack(alignment: .leading, spacing: isAdd ? CarryOnSpace.sm : 14) {
            MacSheetHeader(title: AgentSheetPlan.title(mode))
            if case .delete = mode {
                Text(AgentsCopy.deleteNote).font(MacSheetFont.body)
                    .foregroundStyle(CarryOnColorStyle.coTextSecondary).fixedSize(horizontal: false, vertical: true)
            }
            Group {
                if AgentSheetPlan.showsDetails(mode), !flow.confirmingAdd { AgentDetailFields(editor: editor, focus: $focus) }
                if AgentSheetPlan.showsSecret(mode), !isAdd {
                    labelled(AgentSheetPlan.credentialLabel, helper: AgentsCopy.secretHelper) {
                        SecureField(AgentSheetPlan.credentialLabel, text: $editor.secret)
                            .textFieldStyle(.plain).macSheetField().focused($focus, equals: .secret)
                    }
                }
                if editor.needsPassword, !isAdd || flow.confirmingAdd {
                    labelled(AgentsCopy.currentPassword, helper: editor.destinationChanged ? AgentsCopy.confirmDestination : nil) {
                        SecureField(AgentsCopy.currentPassword, text: $editor.password)
                            .textFieldStyle(.plain).agentEditorField(isAdd: isAdd).focused($focus, equals: .password)
                            .onSubmit { if !AgentSheetPlan.returnPressesCancel(mode) { submit() } }
                            .onAppear {
                                if isAdd && flow.confirmingAdd {
                                    // The field must register after the sheet replaces its form and resizes.
                                    DispatchQueue.main.async {
                                        focus = .password
                                    }
                                }
                            }
                    }
                }
            }
            .id(isAdd && flow.confirmingAdd)
            .defaultFocus($focus, initialField, priority: isAdd && flow.confirmingAdd ? .userInitiated : .automatic)
            .disabled(editor.isBusy)
            if case .failed(let notice) = editor.phase { failure(notice) }
            buttons
        }
        .padding(isAdd ? CarryOnLayout.MacAgentAdd.padding : 20)
        .frame(width: isAdd ? CarryOnLayout.MacAgentAdd.width : 440)
        .background {
            if isAdd {
                Rectangle().fill(.regularMaterial).background(CarryOnColorStyle.coBgGround)
            }
            else { Rectangle().fill(CarryOnColorStyle.coSurfaceCard) }
        }
        .onExitCommand(perform: cancel)
        .onChange(of: editor.phase) { _, phase in
            if phase == .done { onClose() }
            if case .failed(let notice) = phase, notice.failure == .wrongPassword, !isAdd { focus = .password }
        }
        .onChange(of: flow.confirmingAdd) { _, confirming in
            if isAdd, !confirming { focus = .secret }
        }
        .onDisappear { editor.dismiss() }
    }

    private var buttons: some View {
        HStack(spacing: 10) {
            Spacer()
            let cancelButton = Button(AgentsCopy.cancel, action: cancel).buttonStyle(.carryOnQuiet).disabled(editor.isBusy)
            let submitButton = Button(AgentSheetPlan.submitTitle(mode, phase: editor.phase), action: submit)
                .buttonStyle(isAdd ? .carryOnStrong : (AgentSheetPlan.returnPressesCancel(mode) ? .carryOnSecondary : .carryOnPrimary))
                .disabled(!(isAdd && !flow.confirmingAdd ? editor.canConfirmAdd : editor.canSubmit))
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

    private func submit() {
        if isAdd, !flow.confirmingAdd, editor.canConfirmAdd { focus = nil }
        Task { await flow.performPrimary(editor: editor) }
    }

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
