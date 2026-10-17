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
        VStack(alignment: .leading, spacing: 14) {
            field(AgentSheetPlan.nameLabel) {
                TextField(AgentSheetPlan.nameLabel, text: $editor.name)
                    .textFieldStyle(.plain).macSheetField().focused(focus, equals: .name)
            }
            field(AgentSheetPlan.addressLabel, helper: isAdd ? AgentsCopy.addAgentHelper : nil) {
                TextField(AgentSheetPlan.addressLabel, text: $editor.address)
                    .textFieldStyle(.plain).macSheetField().focused(focus, equals: .address)
            }
            field(isAdd ? nil : AgentSheetPlan.credentialLabel) {
                Picker(AgentSheetPlan.credentialLabel, selection: $editor.scheme) {
                    Text(AgentSheetPlan.bearerLabel).tag(AgentAuthScheme.bearer)
                    Text(AgentSheetPlan.apiKeyLabel).tag(AgentAuthScheme.apiKey)
                }
                .pickerStyle(.segmented).labelsHidden()
            }
        }
        .onAppear { focus.wrappedValue = .name }
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
