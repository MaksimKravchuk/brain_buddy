import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyDesign
import BrainBuddyMacCore
import BrainBuddyWorkspace
import SwiftUI

/// What the inspector shows for Hand off… (030-FR-013, 030-FR-002): nothing with the relay off, the control
/// disabled with its reason for a step the account has not seen yet, otherwise the control.
enum HandOffControl: Equatable {
    case hidden
    case disabled(reason: String)
    case enabled

    init(relayEnabled: Bool, serverID: String?) {
        if !relayEnabled {
            self = .hidden
        } else if serverID == nil {
            self = .disabled(reason: AgentsCopy.stepNotSynced)
        } else {
            self = .enabled
        }
    }

    /// The sheet stays open only while the relay is on (G-04.10).
    static func sheetStaysOpen(relayEnabled: Bool) -> Bool { relayEnabled }

    /// The Hand off… menu command is enabled exactly when the inspector's button is: an open step (Next or
    /// Waiting, where the button is drawn) with the control enabled (030-FR-040).
    static func menuEnabled(control: HandOffControl, variant: TaskInspectorVariant) -> Bool {
        control == .enabled && (variant == .next || variant == .waiting)
    }
}

/// G-04: "Hand to an agent" (030-FR-013 – 030-FR-018). The flow owns every rule; this draws its phase.
/// The password is typed into a `SecureField` only and is never logged.
struct HandoffSheet: View {
    let model: BrainBuddyModel
    let onClose: () -> Void
    @State private var flow: HandoffFlow
    @Environment(\.openSettings) private var openSettings
    @FocusState private var passwordFocused: Bool
    @FocusState private var agentFocus: String?

    init?(model: BrainBuddyModel, task: TaskRecord, onClose: @escaping () -> Void) {
        guard let server = task.serverID, let account = model.workspace.account else { return nil }
        let client = BrainBuddyAPIClient(baseURL: account.serverURL, tokenStore: WorkspaceHost.systemTokenStore(), identity: WorkspaceHost.clientIdentity)
        let runs = model.agentRuns
        let project = task.projectID.flatMap { model.project($0)?.name }
        (self.model, self.onClose) = (model, onClose)
        _flow = State(initialValue: HandoffFlow(
            taskServerID: server, projectName: project, remote: client, availability: model.agentAvailability,
            onSent: { _ in await runs.refresh() }))
    }

    private var busy: Bool { flow.phase == .sending }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(verbatim: AgentsCopy.handToAgent).font(MacRowFont.titleStrong).foregroundStyle(CarryOnColorStyle.coTextPrimary)
            Text(verbatim: AgentsCopy.handOffIntro).font(MacRowFont.meta).foregroundStyle(CarryOnColorStyle.coTextSecondary)
            content
            buttons
        }
        .padding(20).frame(width: 460)
        .task { await flow.start() }
        .onChange(of: model.agentAvailability.relayEnabled) { _, on in
            if !HandOffControl.sheetStaysOpen(relayEnabled: on) { onClose() }
        }
        .onChange(of: flow.phase) { _, phase in
            if case .sent = phase { onClose() }
            if phase == .failed(.wrongPassword) { passwordFocused = true }
            if phase == .previewing || phase == .ready, agentFocus == nil, !passwordFocused { focusSelectedAgent() }
        }
        .onChange(of: flow.selectedID) { _, _ in focusSelectedAgent() }
    }

    @ViewBuilder
    private var content: some View {
        switch flow.phase {
        case .loadingAgents:
            ProgressView().controlSize(.small)
        case .noReadyAgent:
            Text(verbatim: AgentsCopy.noReadyAgent).font(MacRowFont.title).foregroundStyle(CarryOnColorStyle.coTextPrimary)
            Button(AgentsCopy.openSettings) {
                model.agentAvailability.requestAgentsTab()
                openSettings()
            }.buttonStyle(.carryOnSecondary)
        default:
            agentRows
            receipt
            fields
            status
        }
    }

    private var agentRows: some View {
        VStack(spacing: 6) {
            ForEach(flow.agents) { agent in
                let selected = agent.id == flow.selectedID
                Button { Task { await flow.select(agent.id) } } label: {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(verbatim: agent.name).font(MacRowFont.titleStrong).foregroundStyle(CarryOnColorStyle.coTextPrimary)
                        Text(verbatim: agent.detail).font(MacRowFont.meta).foregroundStyle(CarryOnColorStyle.coTextSecondary)
                    }
                    .padding(10).frame(maxWidth: .infinity, alignment: .leading)
                    .background(selected ? CarryOnColorStyle.coSurfaceSelected : .coSurfaceCard, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                }
                .buttonStyle(.plain).disabled(busy)
                .focusable().focused($agentFocus, equals: agent.id)
                .accessibilityAddTraits(selected ? .isSelected : [])
            }
        }
        .onMoveCommand { direction in
            switch direction {
            case .up: Task { await flow.moveSelection(by: -1) }
            case .down: Task { await flow.moveSelection(by: 1) }
            default: break
            }
        }
    }

    /// Focus starts on, and follows, the selected agent row (030-FR-040).
    private func focusSelectedAgent() {
        if let id = flow.selectedID { agentFocus = id }
    }

    /// "What it will get": exactly what the server's preview says it will send, then its disclosures.
    @ViewBuilder
    private var receipt: some View {
        if flow.phase == .previewing {
            MacInspectorSectionLabel(AgentsCopy.whatItWillGet)
            ProgressView().controlSize(.small)
        } else if let manifest = flow.manifest {
            MacInspectorSectionLabel(AgentsCopy.whatItWillGet)
            VStack(alignment: .leading, spacing: 4) {
                Text(verbatim: manifest.title).font(MacRowFont.titleStrong)
                if let note = manifest.details, !note.isEmpty { Text(verbatim: "Note: \(note)").font(MacRowFont.title) }
                ForEach(Array(manifest.supportingItems.enumerated()), id: \.offset) { _, item in
                    Text(verbatim: "\(item.label): \(item.body)").font(MacRowFont.title)
                }
            }
            .foregroundStyle(CarryOnColorStyle.coTextPrimary)
            .padding(10).frame(maxWidth: .infinity, alignment: .leading)
            .background(CarryOnColorStyle.coSurfaceCard, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            .accessibilityElement(children: .combine)
            ForEach(Array([manifest.tierDisclosure, manifest.cancellationDisclosure, manifest.externalCopyNotice].enumerated()), id: \.offset) { _, line in
                Text(verbatim: line).font(MacRowFont.meta).foregroundStyle(CarryOnColorStyle.coTextSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    /// The password and the acknowledgement appear only when the preview asks for them (030-FR-016).
    @ViewBuilder
    private var fields: some View {
        if flow.needsAcknowledgement { Toggle(AgentsCopy.acknowledge, isOn: $flow.acknowledged).disabled(busy) }
        if flow.needsPassword {
            SecureField(AgentsCopy.currentPassword, text: $flow.password)
                .textFieldStyle(.plain).font(MacRowFont.title).foregroundStyle(CarryOnColorStyle.coTextPrimary)
                .padding(.horizontal, 10).padding(.vertical, 7)
                .background(CarryOnColorStyle.coFieldBg, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                .focused($passwordFocused).disabled(busy).accessibilityLabel(AgentsCopy.currentPassword)
        }
    }

    @ViewBuilder
    private var status: some View {
        if busy {
            Text(verbatim: AgentsCopy.sending).font(MacRowFont.meta).foregroundStyle(CarryOnColorStyle.coTextSecondary)
        } else if case .failed(let failure) = flow.phase {
            let words = [failure.text(offline: AgentsCopy.handOffOffline), failure.reference].compactMap { $0 }.joined(separator: " ")
            Text(verbatim: words).font(MacRowFont.meta).foregroundStyle(CarryOnColorStyle.coStatusDanger)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    /// Return sends and Esc cancels. Send has no Return while its fields are unsatisfied.
    private var buttons: some View {
        HStack(spacing: 8) {
            Spacer()
            Button(AgentsCopy.cancel, action: onClose).buttonStyle(.carryOnSecondary)
                .keyboardShortcut(.cancelAction).disabled(busy)
            if flow.phase != .noReadyAgent && flow.phase != .loadingAgents {
                Button(sendTitle) { Task { await flow.tryAgain() } }
                    .buttonStyle(.carryOnPrimary).keyboardShortcut(.defaultAction).disabled(!(flow.canSend || failedBeforePreview))
            }
        }
    }

    /// Failed before a preview arrived (offline, agent list or preview error): Try again reloads instead of sending.
    private var failedBeforePreview: Bool {
        if case .failed = flow.phase { return flow.manifest == nil }
        return false
    }

    private var sendTitle: String {
        if case .failed = flow.phase, flow.canSend || flow.manifest == nil { return AgentsCopy.tryAgain }
        return "Send to \(flow.agents.first { $0.id == flow.selectedID }?.name ?? "agent")"
    }
}
