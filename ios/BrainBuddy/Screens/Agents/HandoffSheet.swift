import BrainBuddyAgents
import BrainBuddyAPI
import BrainBuddyDesign
import BrainBuddyWorkspace
import SwiftUI

/// Board M21 (034-FR-009): "Hand to an agent". Choose a ready agent, see exactly what it will get, send.
/// The kit's `HandoffFlow` owns every rule; this draws its phase. The password is typed into a
/// `SecureField` only and is never logged. Agent and manifest text is shown verbatim (never Markdown).
///
/// Environment values are not available in `init`, so this outer view reads them and builds the inner view
/// that owns the flow.
struct HandoffSheet: View {
    private let taskServerID: String
    private let projectName: String?

    @Environment(Workspace.self) private var workspace
    @Environment(AgentsSession.self) private var agents: AgentsSession?

    init(taskServerID: String, projectName: String?) {
        self.taskServerID = taskServerID
        self.projectName = projectName
    }

    var body: some View {
        if let agents, let account = workspace.account {
            HandoffSheetContent(
                taskServerID: taskServerID, projectName: projectName, session: agents,
                remote: AgentsClient.make(for: account))
        } else {
            Color.clear.bbScreenBackground()
        }
    }
}

/// The sheet itself, owning the flow for as long as it is presented.
private struct HandoffSheetContent: View {
    let session: AgentsSession
    @State private var flow: HandoffFlow
    @Environment(\.dismiss) private var dismiss
    @FocusState private var passwordFocused: Bool

    init(taskServerID: String, projectName: String?, session: AgentsSession, remote: any HandoffRemote) {
        self.session = session
        let runs = session.runs
        _flow = State(
            initialValue: HandoffFlow(
                taskServerID: taskServerID, projectName: projectName, remote: remote,
                availability: session.availability, onSent: { _ in await runs.refresh() }))
    }

    private var busy: Bool { flow.phase == .sending }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                Text(verbatim: AgentsCopy.handToAgent)
                    .carryOnText(CarryOnTypeScale.title)
                    .foregroundStyle(.coTextPrimary)
                    .accessibilityAddTraits(.isHeader)
                Text(verbatim: AgentsCopy.handOffIntro)
                    .carryOnText(CarryOnTypeScale.meta)
                    .foregroundStyle(.coTextSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, CGFloat(CarryOnSpace.xxs))
                content
            }
            .padding(.horizontal, CGFloat(CarryOnSpace.lg))
            .padding(.top, CGFloat(CarryOnSpace.lg))
            .padding(.bottom, CGFloat(CarryOnSpace.md))
        }
        .safeAreaInset(edge: .bottom, spacing: 0) { actionBar }
        .bbScreenBackground()
        .presentationDetents([.large])
        .presentationDragIndicator(.visible)
        .task { await flow.start() }
        .onChange(of: flow.phase) { _, phase in
            if case .sent = phase { dismiss() }
            if phase == .failed(.wrongPassword) { passwordFocused = true }
        }
    }

    // MARK: Content

    @ViewBuilder private var content: some View {
        switch flow.phase {
        case .loadingAgents:
            ProgressView()
                .padding(.top, CGFloat(CarryOnSpace.lg))
        case .noReadyAgent:
            Text(verbatim: AgentsCopy.noReadyAgent)
                .carryOnText(CarryOnTypeScale.body)
                .foregroundStyle(.coTextPrimary)
                .padding(.top, CGFloat(CarryOnSpace.lg))
        default:
            agentList
            receipt
            fields
            status
        }
    }

    private func sectionLabel(_ text: String) -> some View {
        Text(verbatim: text)
            .font(BBFont.meta.weight(.semibold))
            .foregroundStyle(.coTextSecondary)
            .accessibilityAddTraits(.isHeader)
            .padding(.top, CGFloat(CarryOnSpace.md))
            .padding(.bottom, CGFloat(CarryOnSpace.xs))
    }

    // MARK: Agents

    @ViewBuilder private var agentList: some View {
        if !flow.agents.isEmpty {
            sectionLabel("Choose agent")
            VStack(spacing: CGFloat(CarryOnSpace.xs)) {
                ForEach(flow.agents) { agent in
                    agentCard(agent)
                }
            }
        }
    }

    private func agentCard(_ agent: HandoffAgent) -> some View {
        let selected = agent.id == flow.selectedID
        let shape = RoundedRectangle(cornerRadius: CGFloat(CarryOnRadius.md), style: .continuous)
        return Button {
            Task { await flow.select(agent.id) }
        } label: {
            HStack(spacing: CGFloat(CarryOnSpace.sm)) {
                HandoffRobotGlyph()
                    .stroke(style: StrokeStyle(lineWidth: 1.8, lineCap: .round, lineJoin: .round))
                    .foregroundStyle(.coTextPrimary)
                    .frame(width: 24, height: 24)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 0) {
                    Text(verbatim: agent.name)
                        .font(selected ? BBFont.bodyMedium : BBFont.body)
                        .foregroundStyle(.coTextPrimary)
                    Text(verbatim: agent.detail)
                        .font(BBFont.meta)
                        .foregroundStyle(.coTextSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .multilineTextAlignment(.leading)
                Spacer(minLength: 0)
            }
            .padding(.vertical, CGFloat(CarryOnSpace.sm))
            .padding(.horizontal, CGFloat(CarryOnSpace.sm))
            .frame(maxWidth: .infinity, minHeight: BBMetrics.hitTarget, alignment: .leading)
            .background(.coSurfaceCard, in: shape)
            .overlay {
                if selected {
                    shape.strokeBorder(CarryOnColorStyle.coTextPrimary, lineWidth: 2)
                }
            }
            .contentShape(shape)
        }
        .buttonStyle(.plain)
        .disabled(busy)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }

    // MARK: What it will get

    /// Exactly what the server's preview says it will send, then its disclosures.
    @ViewBuilder private var receipt: some View {
        if flow.phase == .previewing {
            sectionLabel(AgentsCopy.whatItWillGet)
            ProgressView()
        } else if let manifest = flow.manifest {
            sectionLabel(AgentsCopy.whatItWillGet)
            manifestBox(manifest)
            VStack(alignment: .leading, spacing: CGFloat(CarryOnSpace.xxs)) {
                ForEach(
                    Array([manifest.tierDisclosure, manifest.cancellationDisclosure, manifest.externalCopyNotice].enumerated()),
                    id: \.offset
                ) { _, line in
                    Text(verbatim: line)
                        .font(BBFont.meta)
                        .foregroundStyle(.coTextSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(.top, CGFloat(CarryOnSpace.sm))
        }
    }

    private func manifestBox(_ manifest: AgentManifestDTO) -> some View {
        VStack(alignment: .leading, spacing: CGFloat(CarryOnSpace.xxs)) {
            Text(verbatim: manifest.title)
                .font(BBFont.meta.weight(.semibold))
            if let note = manifest.details, !note.isEmpty {
                Text(verbatim: AgentsCopy.note(note))
                    .font(BBFont.meta)
            }
            ForEach(Array(manifest.supportingItems.enumerated()), id: \.offset) { _, item in
                Text(verbatim: "\(item.label): \(item.body)")
                    .font(BBFont.meta)
            }
        }
        .foregroundStyle(.coTextPrimary)
        .fixedSize(horizontal: false, vertical: true)
        .padding(CGFloat(CarryOnSpace.sm))
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            .coControlQuiet, in: RoundedRectangle(cornerRadius: CGFloat(CarryOnRadius.md), style: .continuous)
        )
        .accessibilityElement(children: .combine)
    }

    // MARK: Password, acknowledgement, status

    /// The password and the acknowledgement appear only when the preview asks for them (030-FR-016).
    @ViewBuilder private var fields: some View {
        if flow.needsAcknowledgement {
            Toggle(AgentsCopy.acknowledge, isOn: $flow.acknowledged)
                .disabled(busy)
                .padding(.top, CGFloat(CarryOnSpace.md))
        }
        if flow.needsPassword {
            SecureField(AgentsCopy.currentPassword, text: $flow.password)
                .textContentType(.password)
                .focused($passwordFocused)
                .disabled(busy)
                .padding(.horizontal, CGFloat(CarryOnSpace.md))
                .frame(minHeight: BBMetrics.hitTarget)
                .background(
                    .coSurfaceCard,
                    in: RoundedRectangle(cornerRadius: CGFloat(CarryOnRadius.md), style: .continuous)
                )
                .accessibilityLabel(AgentsCopy.currentPassword)
                .padding(.top, CGFloat(CarryOnSpace.md))
        }
    }

    @ViewBuilder private var status: some View {
        if busy {
            Text(verbatim: AgentsCopy.sending)
                .font(BBFont.meta)
                .foregroundStyle(.coTextSecondary)
                .padding(.top, CGFloat(CarryOnSpace.sm))
        } else if case .failed(let failure) = flow.phase {
            let words = [failure.text(offline: AgentsCopy.handOffOffline), failure.reference]
                .compactMap { $0 }.joined(separator: " ")
            Text(verbatim: words)
                .font(BBFont.meta)
                .foregroundStyle(.coStatusDanger)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, CGFloat(CarryOnSpace.sm))
        }
    }

    // MARK: Bottom bar

    private var actionBar: some View {
        BBGlassActionBar {
            if flow.phase != .noReadyAgent && flow.phase != .loadingAgents {
                Button {
                    Task { await flow.tryAgain() }
                } label: {
                    Text(verbatim: sendTitle)
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.carryOnGlassPrimary)
                .disabled(busy || !(flow.canSend || failedBeforePreview))
            }
            Button {
                dismiss()
            } label: {
                Text(verbatim: AgentsCopy.cancel)
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.carryOnQuiet)
            .disabled(busy)
        }
    }

    /// Failed before a preview arrived (offline, agent list or preview error): Try again reloads instead of sending.
    private var failedBeforePreview: Bool {
        if case .failed = flow.phase { return flow.manifest == nil }
        return false
    }

    private var sendTitle: String {
        if busy { return AgentsCopy.sending }
        if case .failed = flow.phase, flow.canSend || flow.manifest == nil { return AgentsCopy.tryAgain }
        return AgentsCopy.send(to: flow.agents.first { $0.id == flow.selectedID }?.name ?? "agent")
    }
}

/// The agent mark of the boards: a rounded body, two eyes and an antenna, on a 24 pt grid.
private struct HandoffRobotGlyph: Shape {
    func path(in rect: CGRect) -> Path {
        let unit = min(rect.width, rect.height) / 24
        func point(_ x: CGFloat, _ y: CGFloat) -> CGPoint {
            CGPoint(x: rect.minX + x * unit, y: rect.minY + y * unit)
        }
        var path = Path()
        path.addRoundedRect(
            in: CGRect(x: rect.minX + 4 * unit, y: rect.minY + 6 * unit, width: 16 * unit, height: 12 * unit),
            cornerSize: CGSize(width: 4 * unit, height: 4 * unit), style: .continuous)
        for x: CGFloat in [9.5, 14.5] {
            path.addEllipse(
                in: CGRect(x: rect.minX + (x - 1.2) * unit, y: rect.minY + (12 - 1.2) * unit, width: 2.4 * unit, height: 2.4 * unit))
        }
        path.move(to: point(12, 3))
        path.addLine(to: point(12, 6))
        return path
    }
}
