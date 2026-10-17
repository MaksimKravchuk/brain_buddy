import BrainBuddyAgents
import BrainBuddyAPI
import BrainBuddyDesign
import BrainBuddyMacCore
import SwiftUI

/// G-07 and G-08.02: Name, Address and the credential type, shared by Add new agent and Edit. The
/// type is a two-segment control (Bearer token | API key); the helper under Address is Add's only.
struct AgentDetailFields: View {
    @Bindable var editor: AgentConnectionEditor
    var focus: FocusState<AgentEditorSheet.Field?>.Binding

    private var isAdd: Bool { editor.mode == .add }

    var body: some View {
        VStack(alignment: .leading, spacing: isAdd ? CarryOnSpace.sm : 14) {
            field(AgentSheetPlan.nameLabel) {
                TextField(AgentSheetPlan.nameLabel, text: $editor.name)
                    .textFieldStyle(.plain).agentEditorField(isAdd: isAdd).focused(focus, equals: .name)
            }
            field(AgentSheetPlan.addressLabel, helper: isAdd ? AgentsCopy.addAgentHelper : nil) {
                TextField(AgentSheetPlan.addressLabel, text: $editor.address)
                    .textFieldStyle(.plain).agentEditorField(isAdd: isAdd).focused(focus, equals: .address)
            }
            if isAdd {
                field(AgentSheetPlan.credentialLabel, helper: AgentsCopy.secretHelper) {
                    VStack(spacing: CarryOnSpace.xs) {
                        AgentCredentialPicker(selection: $editor.scheme)
                        SecureField(AgentSheetPlan.credentialLabel, text: $editor.secret)
                            .textFieldStyle(.plain).agentEditorField(isAdd: true).focused(focus, equals: .secret)
                    }
                }
            } else {
                field(AgentSheetPlan.credentialLabel) {
                    Picker(AgentSheetPlan.credentialLabel, selection: $editor.scheme) {
                        Text(AgentSheetPlan.bearerLabel).tag(AgentAuthScheme.bearer)
                        Text(AgentSheetPlan.apiKeyLabel).tag(AgentAuthScheme.apiKey)
                    }
                    .pickerStyle(.segmented).labelsHidden()
                }
            }
        }
        .onAppear {
            if isAdd, case .failed = editor.phase { focus.wrappedValue = .secret }
            else { focus.wrappedValue = .name }
        }
    }

    private func field<Content: View>(
        _ label: String?, helper: String? = nil, @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            if let label {
                Text(label).font(MacSheetFont.metaStrong).foregroundStyle(CarryOnColorStyle.coTextSecondary)
            }
            content()
            if let helper {
                Text(helper).font(MacSheetFont.meta).foregroundStyle(CarryOnColorStyle.coTextSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

/// M30's two choices use the existing Mac choice-row keyboard convention. Words and selected
/// traits expose the selection to VoiceOver; the focus ring remains visible on the whole control.
private struct AgentCredentialPicker: View {
    private typealias Metrics = CarryOnLayout.MacAgentAdd
    @Binding var selection: AgentAuthScheme
    @Environment(\.isEnabled) private var isEnabled
    @FocusState private var isFocused: Bool

    var body: some View {
        HStack(spacing: 0) {
            option(.bearer, title: AgentSheetPlan.bearerLabel)
            option(.apiKey, title: AgentSheetPlan.apiKeyLabel)
        }
        .padding(Metrics.segmentInset)
        .background(CarryOnColorStyle.coControlQuiet, in: Capsule())
        .opacity(isEnabled ? 1 : CarryOnLayout.Button.disabledOpacity)
        .focusable(isEnabled)
        .focused($isFocused)
        .focusEffectDisabled()
        .overlay {
            if isFocused {
                Capsule().strokeBorder(CarryOnColorStyle.coFocusRing, lineWidth: CarryOnLayout.FocusRing.width)
            }
        }
        .onKeyPress(.leftArrow) { choose(.bearer) }
        .onKeyPress(.rightArrow) { choose(.apiKey) }
        .accessibilityElement(children: .contain)
        .accessibilityLabel(AgentSheetPlan.credentialLabel)
    }

    private func option(_ scheme: AgentAuthScheme, title: String) -> some View {
        let selected = selection == scheme
        return Button { selection = scheme } label: {
            Text(title)
                .font(selected ? MacSheetFont.heading : MacSheetFont.body)
                .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                .frame(maxWidth: .infinity, minHeight: Metrics.segmentHeight - Metrics.segmentInset * 2)
                .background {
                    if selected { Capsule().fill(CarryOnColorStyle.coSurfaceCard) }
                }
                .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(title)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }

    private func choose(_ scheme: AgentAuthScheme) -> KeyPress.Result {
        guard isEnabled else { return .ignored }
        selection = scheme
        return .handled
    }
}

extension View {
    /// Only Add agent uses M30's white fields; other agent operations retain their existing fields.
    @ViewBuilder
    func agentEditorField(isAdd: Bool) -> some View {
        if isAdd {
            font(MacSheetFont.body)
                .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                .padding(.horizontal, CarryOnLayout.MacAgentAdd.fieldPaddingX)
                .padding(.vertical, CarryOnSpace.xs)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(CarryOnColorStyle.coSurfaceCard, in: RoundedRectangle(cornerRadius: CarryOnRadius.sm, style: .continuous))
        } else {
            macSheetField()
        }
    }
}
