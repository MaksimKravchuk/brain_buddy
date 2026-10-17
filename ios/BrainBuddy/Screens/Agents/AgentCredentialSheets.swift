import BrainBuddyAPI
import BrainBuddyAgents
import BrainBuddyDesign
import SwiftUI

/// Design I-09 (030 G-08): Replace credential and Delete, as a sheet over an `AgentConnectionEditor`
/// opened from the agent's details. Both ask for Current password; Replace also takes the new secret.
/// Delete is never the default action: its note says what is destroyed and Cancel sits first
/// (030-FR-032, 030-FR-033). Secrets are typed in secure fields and the editor empties them.
struct AgentCredentialSheet: View {
    @Bindable var editor: AgentConnectionEditor
    let onClose: () -> Void

    @FocusState private var focus: Field?

    private enum Field: Hashable { case secret, password }

    private var isDelete: Bool {
        if case .delete = editor.mode { return true }
        return false
    }

    private var title: String {
        switch editor.mode {
        case .replaceCredential(let connection): AgentsCopy.replaceCredential(for: connection.name)
        case .delete(let connection): AgentsCopy.delete(connection.name)
        case .add: AgentsCopy.addNewAgent
        case .edit(let connection): connection.name
        }
    }

    private var showsSecret: Bool {
        if case .replaceCredential = editor.mode { return true }
        return false
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                Text(verbatim: title)
                    .carryOnText(CarryOnTypeScale.title)
                    .foregroundStyle(.coTextPrimary)
                    .accessibilityAddTraits(.isHeader)
                if isDelete {
                    Text(verbatim: AgentsCopy.deleteNote)
                        .carryOnFont(CarryOnTypeScale.body)
                        .foregroundStyle(.coTextSecondary)
                        .padding(.top, CGFloat(CarryOnSpace.xs))
                        .fixedSize(horizontal: false, vertical: true)
                }
                fields
                    .disabled(editor.isBusy)
                if case .failed(let notice) = editor.phase {
                    AgentFailureLines(notice: notice)
                        .padding(.top, CGFloat(CarryOnSpace.sm))
                }
            }
            .padding(.horizontal, CGFloat(CarryOnSpace.lg))
            .padding(.top, CGFloat(CarryOnSpace.lg))
            .padding(.bottom, CGFloat(CarryOnSpace.md))
        }
        .scrollDismissesKeyboard(.interactively)
        .safeAreaInset(edge: .bottom, spacing: 0) { actionBar }
        .bbScreenBackground()
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
        .interactiveDismissDisabled(editor.isBusy)
        .onAppear { focus = showsSecret ? .secret : .password }
        .onChange(of: editor.phase) { _, phase in
            if phase == .done { onClose() }
            if case .failed(let notice) = phase, notice.failure == .wrongPassword { focus = .password }
        }
        .onDisappear { editor.dismiss() }
    }

    @ViewBuilder private var fields: some View {
        if showsSecret {
            AgentFormLabel("Credential")
            SecureField("Credential", text: $editor.secret)
                .submitLabel(.next)
                .focused($focus, equals: .secret)
                .onSubmit { focus = .password }
                .agentFieldBox()
            AgentFormHelper(AgentsCopy.secretHelper)
        }
        if editor.needsPassword {
            AgentFormLabel(AgentsCopy.currentPassword)
            SecureField(AgentsCopy.currentPassword, text: $editor.password)
                .textContentType(.password)
                .submitLabel(.done)
                .focused($focus, equals: .password)
                .onSubmit { if !isDelete { submit() } }
                .agentFieldBox()
        }
    }

    /// Cancel first; the action is the decisive button, except for Delete, which is the plain one.
    private var actionBar: some View {
        BBGlassActionBar {
            Button(action: cancel) {
                Text(verbatim: AgentsCopy.cancel)
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.carryOnQuiet)
            .disabled(editor.isBusy)
            Button(action: submit) {
                Text(verbatim: submitTitle)
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.carryOnSecondary)
            .disabled(!editor.canSubmit)
        }
    }

    private var submitTitle: String {
        isDelete ? "Delete" : AgentsCopy.replace
    }

    private func submit() { Task { await editor.submit() } }

    private func cancel() { if !editor.isBusy { onClose() } }
}
