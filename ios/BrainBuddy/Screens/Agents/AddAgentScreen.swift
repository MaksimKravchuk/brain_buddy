import BrainBuddyAPI
import BrainBuddyAgents
import BrainBuddyDesign
import SwiftUI

/// Board M30 / design I-08: Add new agent, pushed from the Agents section (034-FR-012, 030-FR-031).
/// Name, Address, the credential type and secret, and Current password; "Add and test" adds the agent,
/// tests it, selects it and pops back, whether or not the test succeeds. The secret and the password
/// are typed in secure fields and the editor empties them after every outcome (030-FR-035).
struct AddAgentScreen: View {
    @State private var editor: AgentConnectionEditor
    @Environment(\.dismiss) private var dismiss

    init(model: AgentSettingsModel) {
        _editor = State(initialValue: AgentConnectionEditor(mode: .add, model: model))
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                Text(verbatim: AgentsCopy.addNewAgent)
                    .carryOnFont(CarryOnTypeScale.title)
                    .foregroundStyle(.coTextPrimary)
                    .accessibilityAddTraits(.isHeader)
                AddAgentFields(editor: editor)
                    .disabled(editor.isBusy)
                if case .failed(let notice) = editor.phase {
                    AgentFailureLines(notice: notice)
                        .padding(.top, CGFloat(CarryOnSpace.sm))
                }
            }
            .padding(.horizontal, CGFloat(CarryOnSpace.md) + CGFloat(CarryOnSpace.xxs))
            .padding(.top, CGFloat(CarryOnSpace.xxs))
            .padding(.bottom, CGFloat(CarryOnSpace.md))
        }
        .scrollDismissesKeyboard(.interactively)
        .safeAreaInset(edge: .bottom, spacing: 0) { actionBar }
        .bbScreenBackground()
        .navigationBarTitleDisplayMode(.inline)
        .onChange(of: editor.phase) { _, phase in
            if phase == .done { dismiss() }
        }
        .onDisappear { editor.dismiss() }
    }

    private var actionBar: some View {
        BBGlassActionBar {
            Button {
                Task { await editor.submit() }
            } label: {
                Text(verbatim: submitTitle)
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.carryOnStrong)
            .disabled(!editor.canSubmit)
            Button {
                dismiss()
            } label: {
                Text(verbatim: AgentsCopy.cancel)
            }
            .buttonStyle(.carryOnQuiet)
            .disabled(editor.isBusy)
        }
    }

    private var submitTitle: String {
        switch editor.phase {
        case .adding: AgentsCopy.adding
        case .testing: AgentsCopy.testing
        default: AgentsCopy.addAndTest
        }
    }
}

/// Name, Address (with its helper), the credential type, the secret and Current password.
private struct AddAgentFields: View {
    @Bindable var editor: AgentConnectionEditor
    @FocusState private var focus: Field?

    private enum Field: Hashable { case name, address, secret, password }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            AgentFormLabel("Name")
            TextField("Name", text: $editor.name)
                .textInputAutocapitalization(.words)
                .submitLabel(.next)
                .focused($focus, equals: .name)
                .onSubmit { focus = .address }
                .agentFieldBox()
            AgentFormLabel("Address")
            TextField("Address", text: $editor.address)
                .keyboardType(.URL)
                .textContentType(.URL)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .submitLabel(.next)
                .focused($focus, equals: .address)
                .onSubmit { focus = .secret }
                .agentFieldBox()
            AgentFormHelper(AgentsCopy.addAgentHelper)
            AgentFormLabel("Credential")
            Picker("Credential", selection: $editor.scheme) {
                Text(verbatim: "Bearer token").tag(AgentAuthScheme.bearer)
                Text(verbatim: "API key").tag(AgentAuthScheme.apiKey)
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            SecureField("Credential", text: $editor.secret)
                .submitLabel(.next)
                .focused($focus, equals: .secret)
                .onSubmit { focus = .password }
                .agentFieldBox()
                .padding(.top, CGFloat(CarryOnSpace.xs))
            AgentFormHelper(AgentsCopy.secretHelper)
            AgentFormLabel(AgentsCopy.currentPassword)
            SecureField(AgentsCopy.currentPassword, text: $editor.password)
                .textContentType(.password)
                .submitLabel(.done)
                .focused($focus, equals: .password)
                .onSubmit { if editor.canSubmit { Task { await editor.submit() } } }
                .agentFieldBox()
        }
        .onAppear { focus = .name }
        .onChange(of: editor.phase) { _, phase in
            if case .failed(let notice) = phase, notice.failure == .wrongPassword { focus = .password }
        }
    }
}

// MARK: - Shared form pieces (also used by the credential sheets)

/// A field label in the section-header voice (meta-strong, secondary).
struct AgentFormLabel: View {
    let text: String

    init(_ text: String) { self.text = text }

    var body: some View {
        Text(verbatim: text)
            .carryOnFont(CarryOnTypeScale.metaStrong)
            .foregroundStyle(.coTextSecondary)
            .padding(.top, CGFloat(CarryOnSpace.sm))
            .padding(.bottom, CGFloat(CarryOnSpace.xs))
            .accessibilityHidden(true)
    }
}

/// The small line under a field.
struct AgentFormHelper: View {
    let text: String

    init(_ text: String) { self.text = text }

    var body: some View {
        Text(verbatim: text)
            .carryOnFont(CarryOnTypeScale.meta)
            .foregroundStyle(.coTextSecondary)
            .padding(.top, CGFloat(CarryOnSpace.xxs))
            .fixedSize(horizontal: false, vertical: true)
    }
}

/// The failure line of an editor, with the server's reference. Agent and server text is shown verbatim.
struct AgentFailureLines: View {
    let notice: AgentNotice

    var body: some View {
        VStack(alignment: .leading, spacing: CGFloat(CarryOnSpace.xxs)) {
            Text(verbatim: notice.message)
                .carryOnFont(CarryOnTypeScale.meta)
                .foregroundStyle(.coStatusDanger)
                .fixedSize(horizontal: false, vertical: true)
            if let reference = notice.reference {
                Text(verbatim: AgentsCopy.reference(reference))
                    .carryOnFont(CarryOnTypeScale.meta)
                    .foregroundStyle(.coTextSecondary)
                    .textSelection(.enabled)
            }
        }
        .accessibilityElement(children: .combine)
    }
}

extension View {
    /// A text field on a surface-card box (board M30): 14 radius, 44 pt tall at least.
    func agentFieldBox() -> some View {
        self
            .carryOnFont(CarryOnTypeScale.body)
            .foregroundStyle(.coTextPrimary)
            .padding(.horizontal, CGFloat(CarryOnSpace.sm))
            .frame(minHeight: BBMetrics.hitTarget)
            .background(
                .coSurfaceCard, in: RoundedRectangle(cornerRadius: CGFloat(CarryOnRadius.md), style: .continuous))
    }
}
