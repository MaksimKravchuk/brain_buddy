import BrainBuddyAgents
import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyDesign
import BrainBuddyWorkspace
import SwiftUI
import UIKit

/// Boards 23 and 24 (034-FR-005 – 034-FR-008): one agent run of a step, as a sheet from Waiting for. The
/// iPhone port of the Mac's `AgentRunSectionView`: the same kit model and actions, laid out as the run's
/// timeline, the agent's question or result, and a glass bar of actions. Agent text is `Text(verbatim:)`:
/// no Markdown, no HTML, no link.
struct AgentRunSheet: View {
    let item: AgentRunItem

    @Environment(Workspace.self) private var workspace
    @Environment(AgentsSession.self) private var agents: AgentsSession?

    init(item: AgentRunItem) {
        self.item = item
    }

    var body: some View {
        if let agents, let account = workspace.account, let taskID = agents.stepID(forServerID: item.taskServerID) {
            let project = workspace.task(taskID)?.projectID
            AgentRunSheetContent(
                item: item, agents: agents, project: project.flatMap { workspace.project($0) },
                model: AgentRunSectionModel(
                    taskServerID: item.taskServerID, projectID: project?.rawValue,
                    remote: AgentsClient.make(for: account), availability: agents.availability,
                    steps: WorkspaceStepCommands(workspace: workspace, taskID: taskID),
                    refreshStore: { await agents.runs.refresh() }))
        } else {
            AgentRunSheetLabelOnly(item: item)
        }
    }
}

/// The run's title block, shared by the full sheet and the label-only fallback.
private struct AgentRunHeader: View {
    let agentName: String
    let title: String
    let project: ProjectRecord?

    var body: some View {
        VStack(alignment: .leading, spacing: CGFloat(CarryOnSpace.xs)) {
            HStack(spacing: CGFloat(CarryOnSpace.xs)) {
                if let project {
                    CarryOnProjectDot(BBColor.projectRGB(project.color))
                        .accessibilityHidden(true)
                }
                Text(verbatim: [project?.name, agentName].compactMap { $0 }.joined(separator: " · "))
            }
            .carryOnText(CarryOnTypeScale.meta)
            .foregroundStyle(.coTextSecondary)
            Text(verbatim: title)
                .carryOnText(CarryOnTypeScale.step)
                .foregroundStyle(.coTextPrimary)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityAddTraits(.isHeader)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// When the account or the step cannot be resolved: the row's label only.
private struct AgentRunSheetLabelOnly: View {
    let item: AgentRunItem

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: CGFloat(CarryOnSpace.sm)) {
                AgentRunHeader(agentName: item.agentName, title: item.stepTitle, project: nil)
                Text(verbatim: item.state.label)
                    .carryOnText(CarryOnTypeScale.meta)
                    .foregroundStyle(.coTextSecondary)
            }
            .padding(.horizontal, CGFloat(CarryOnSpace.lg))
            .padding(.top, CGFloat(CarryOnSpace.lg))
        }
        .bbScreenBackground()
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
    }
}

private struct AgentRunSheetContent: View {
    let item: AgentRunItem
    let agents: AgentsSession
    let project: ProjectRecord?
    @State private var section: AgentRunSectionModel
    @State private var isMarkingDone = false
    @State private var isHandingOff = false

    @Environment(\.dismiss) private var dismiss

    init(item: AgentRunItem, agents: AgentsSession, project: ProjectRecord?, model: AgentRunSectionModel) {
        (self.item, self.agents, self.project) = (item, agents, project)
        _section = State(initialValue: model)
    }

    private var online: Bool { agents.availability.isOnline }
    private var working: Bool { section.actions.phase == .working }
    private var refreshKey: String {
        "\(item.state.label)|\(item.lastContactAt?.timeIntervalSince1970 ?? 0)|\(agents.runs.lastUpdated?.timeIntervalSince1970 ?? 0)"
    }

    private var block: AgentRunBlock? {
        section.shown.map { AgentRunBlock($0, now: section.now(), relay: agents.availability.relayEnabled) }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: CGFloat(CarryOnSpace.sm)) {
                AgentRunHeader(agentName: section.shown?.agentName ?? item.agentName, title: item.stepTitle, project: project)
                if let run = section.shown, let block {
                    runContent(run, block)
                } else {
                    statusLine(item.state.label, .coTextSecondary, .coMarkOpen)
                }
                earlierRuns
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
        .task(id: refreshKey) { await section.load() }
        .onChange(of: section.actions.phase) { _, phase in
            if isMarkingDone && phase == .done { dismiss() }
        }
        .sheet(isPresented: $isHandingOff) {
            HandoffSheet(taskServerID: section.taskServerID, projectName: project?.name)
        }
    }

    // MARK: Run

    @ViewBuilder
    private func runContent(_ run: AgentRunDTO, _ block: AgentRunBlock) -> some View {
        statusLine(block.label, block.color, block.tone == .plain ? .coMarkOpen : block.color)
        if !block.isExpired {
            timeline(run, block)
            if !online || agents.runs.phase == .stale, let at = agents.runs.lastUpdated {
                note(AgentsCopy.lastUpdated(at.formatted(date: .omitted, time: .shortened)))
            }
            stateBlock(run, block)
        }
    }

    private func statusLine(_ text: String, _ color: CarryOnColorStyle, _ dot: CarryOnColorStyle) -> some View {
        HStack(spacing: CGFloat(CarryOnSpace.xs)) {
            Circle().fill(dot).frame(width: 8, height: 8).accessibilityHidden(true)
            Text(verbatim: text)
        }
        .carryOnText(CarryOnTypeScale.meta)
        .foregroundStyle(color)
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }

    private func timeline(_ run: AgentRunDTO, _ block: AgentRunBlock) -> some View {
        let rows = AgentTimelineRow.rows(run)
        return VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(rows.enumerated()), id: \.offset) { index, row in
                let isLast = index == rows.count - 1
                timelineRow(row, isLast: isLast, isCurrent: isLast && block.reply)
            }
        }
        .padding(.top, CGFloat(CarryOnSpace.xs))
    }

    private func timelineRow(_ row: AgentTimelineRow, isLast: Bool, isCurrent: Bool) -> some View {
        HStack(alignment: .top, spacing: CGFloat(CarryOnSpace.sm)) {
            VStack(spacing: 0) {
                Circle()
                    .fill(isCurrent ? CarryOnColorStyle.coAccentFill : CarryOnColorStyle.coTextDone)
                    .frame(width: 12, height: 12)
                    .padding(.top, 5)
                if !isLast {
                    Rectangle()
                        .fill(CarryOnColorStyle.coControlQuietPressed)
                        .frame(width: 2)
                        .frame(maxHeight: .infinity)
                        .padding(.vertical, CGFloat(CarryOnSpace.xxs))
                }
            }
            .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 0) {
                Text(verbatim: row.word)
                    .carryOnText(isCurrent ? CarryOnTypeScale.bodyStrong : CarryOnTypeScale.body)
                    .foregroundStyle(.coTextPrimary)
                Text(verbatim: row.meta)
                    .carryOnText(CarryOnTypeScale.meta)
                    .foregroundStyle(.coTextSecondary)
            }
            .padding(.bottom, isLast ? 0 : 14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .accessibilityElement(children: .combine)
        }
    }

    // MARK: State blocks

    @ViewBuilder
    private func stateBlock(_ run: AgentRunDTO, _ block: AgentRunBlock) -> some View {
        if let question = block.question {
            card(AgentsCopy.asks(run.agentName), question)
            if block.reply { replyForm(run) }
        }
        if let detail = block.detail { plain(detail, block.color) }
        if let contact = block.contact { note(contact) }
        if block.showsResult { resultBlock(block) }
        if block.check && section.asksPassword {
            field(AgentsCopy.currentPassword, text: $section.password, secure: true)
        }
        if (block.reply || block.stop || block.check) && !online { note(AgentsCopy.needsConnection) }
        if case .failed(let failure) = section.actions.phase {
            plain([failure.text(), failure.reference].compactMap { $0 }.joined(separator: " "), .coStatusDanger)
        }
    }

    private func replyForm(_ run: AgentRunDTO) -> some View {
        VStack(alignment: .leading, spacing: CGFloat(CarryOnSpace.xs)) {
            field(AgentsCopy.yourAnswer, text: $section.answer)
            if run.replyPending { note(AgentsCopy.replySent) }
        }
    }

    @ViewBuilder
    private func resultBlock(_ block: AgentRunBlock) -> some View {
        sectionLabel(AgentsCopy.result)
        if block.result != nil || block.resultLink != nil {
            VStack(alignment: .leading, spacing: CGFloat(CarryOnSpace.sm)) {
                if let result = block.result {
                    Text(verbatim: result)
                        .carryOnText(CarryOnTypeScale.body)
                        .foregroundStyle(.coTextPrimary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if let link = block.resultLink { linkRow(link) }
            }
            .padding(CGFloat(CarryOnSpace.md))
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.coSurfaceCard, in: cardShape)
        }
        note(AgentsCopy.finishingIsYours)
        sectionLabel(AgentsCopy.then)
        nextStepField
    }

    /// The link is shown as text and copied, never opened (034-FR-007).
    private func linkRow(_ link: String) -> some View {
        HStack(spacing: CGFloat(CarryOnSpace.xs)) {
            Text(verbatim: link)
                .carryOnText(CarryOnTypeScale.meta)
                .foregroundStyle(.coTextSecondary)
                .lineLimit(1)
                .truncationMode(.middle)
                .frame(maxWidth: .infinity, alignment: .leading)
            Button {
                UIPasteboard.general.string = link
            } label: {
                Image(systemName: "doc.on.doc")
                    .font(BBFont.meta)
                    .foregroundStyle(.coTextSecondary)
                    .frame(width: BBMetrics.hitTarget, height: BBMetrics.hitTarget)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Copy link")
        }
        .padding(.leading, CGFloat(CarryOnSpace.sm))
        .background(.coControlQuiet, in: RoundedRectangle(cornerRadius: CGFloat(CarryOnRadius.sm), style: .continuous))
    }

    /// The canvas's "Make the next step" row: the stairs glyph and a field the next step is typed into.
    private var nextStepField: some View {
        HStack(spacing: CGFloat(CarryOnSpace.sm)) {
            Image(systemName: "stairs")
                .font(BBFont.body)
                .foregroundStyle(.coTextPrimary)
                .frame(width: BBMetrics.iconColumn)
                .accessibilityHidden(true)
            TextField(AgentsCopy.makeNextStep, text: $section.nextStep, axis: .vertical)
                .lineLimit(1...4)
                .carryOnText(CarryOnTypeScale.body)
                .foregroundStyle(.coTextPrimary)
                .accessibilityLabel(AgentsCopy.makeNextStep)
        }
        .padding(.vertical, CGFloat(CarryOnSpace.sm))
        .padding(.horizontal, CGFloat(CarryOnLayout.Row.paddingX))
        .frame(minHeight: BBMetrics.hitTarget)
        .background(.coSurfaceCard, in: cardShape)
    }

    @ViewBuilder
    private var earlierRuns: some View {
        if section.runs.count > 1 {
            sectionLabel(AgentsCopy.earlierRuns)
            ForEach(Array(section.runs.dropFirst()), id: \.id) { run in
                earlierRow(run)
            }
        }
    }

    private func earlierRow(_ run: AgentRunDTO) -> some View {
        let label = AgentRunBlock(run, now: section.now(), relay: false).label
        let day = run.createdAt.formatted(.dateTime.day().month(.abbreviated))
        return Button {
            section.choose(run)
        } label: {
            Text(verbatim: [run.agentName, label, day].joined(separator: " · "))
                .carryOnText(CarryOnTypeScale.meta)
                .foregroundStyle(.coTextSecondary)
                .frame(maxWidth: .infinity, minHeight: BBMetrics.hitTarget, alignment: .leading)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(section.shown?.id == run.id ? .isSelected : [])
    }

    // MARK: Bar

    @ViewBuilder
    private var actionBar: some View {
        if let block, !block.isExpired, hasBarButtons(block) {
            BBGlassActionBar {
                if block.reply { replyButton }
                if block.markDone { markDoneButton }
                if block.stop { stopButton }
                if block.check { checkButton(block) }
                if block.handOffAgain { handOffButton }
            }
        }
    }

    private func hasBarButtons(_ block: AgentRunBlock) -> Bool {
        block.reply || block.markDone || block.stop || block.check || block.handOffAgain
    }

    private var replyButton: some View {
        barButton(AgentsCopy.reply, .glassPrimary) { Task { await section.sendReply() } }
            .disabled(
                !online || working || (section.shown?.replyPending ?? false)
                    || section.answer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
    }

    private var markDoneButton: some View {
        barButton(AgentsCopy.markDone, .glassPrimary) {
            isMarkingDone = true
            Task {
                await section.actions.markStepDone(
                    taskServerID: section.taskServerID, projectID: section.projectID, nextStep: section.nextStep)
                if section.actions.phase != .done { isMarkingDone = false }
            }
        }
        .disabled(working)
    }

    private var stopButton: some View {
        barButton(AgentsCopy.stopRun, .quiet) {
            Task { if let run = section.shown { await section.actions.stop(run) } }
        }
        .disabled(!online || working)
    }

    private func checkButton(_ block: AgentRunBlock) -> some View {
        barButton(AgentsCopy.checkAgain, .quiet) { Task { await section.checkAgain() } }
            .disabled(!online || working || (section.asksPassword && section.password.isEmpty))
    }

    private var handOffButton: some View {
        barButton(AgentsCopy.handOffAgain, .quiet) { isHandingOff = true }
    }

    private func barButton(
        _ title: String, _ kind: CarryOnButtonStyle.Kind, action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Text(title)
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(CarryOnButtonStyle(kind))
    }

    // MARK: Pieces

    private var cardShape: RoundedRectangle {
        RoundedRectangle(cornerRadius: CGFloat(CarryOnRadius.md), style: .continuous)
    }

    private func sectionLabel(_ text: String) -> some View {
        Text(verbatim: text)
            .carryOnText(CarryOnTypeScale.metaStrong)
            .foregroundStyle(.coTextSecondary)
            .padding(.top, CGFloat(CarryOnSpace.xs))
            .frame(maxWidth: .infinity, alignment: .leading)
            .accessibilityAddTraits(.isHeader)
    }

    private func note(_ text: String) -> some View {
        Text(verbatim: text)
            .carryOnText(CarryOnTypeScale.meta)
            .foregroundStyle(.coTextSecondary)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func plain(_ text: String, _ color: CarryOnColorStyle) -> some View {
        Text(verbatim: text)
            .carryOnText(CarryOnTypeScale.body)
            .foregroundStyle(color)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func card(_ title: String, _ text: String) -> some View {
        VStack(alignment: .leading, spacing: CGFloat(CarryOnSpace.xxs)) {
            Text(verbatim: title)
                .carryOnText(CarryOnTypeScale.meta)
                .foregroundStyle(.coTextSecondary)
            Text(verbatim: text)
                .carryOnText(CarryOnTypeScale.body)
                .foregroundStyle(.coTextPrimary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(CGFloat(CarryOnSpace.md))
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.coSurfaceCard, in: cardShape)
        .accessibilityElement(children: .combine)
    }

    private func field(_ name: String, text: Binding<String>, secure: Bool = false) -> some View {
        Group {
            if secure {
                SecureField(name, text: text)
            } else {
                TextField(name, text: text, axis: .vertical).lineLimit(2...5)
            }
        }
        .carryOnText(CarryOnTypeScale.body)
        .foregroundStyle(.coTextPrimary)
        .padding(CGFloat(CarryOnSpace.sm))
        .frame(minHeight: BBMetrics.hitTarget, alignment: .leading)
        .background(.coControlQuiet, in: cardShape)
        .accessibilityLabel(name)
    }
}

private extension AgentRunBlock {
    /// The label's colour by tone, as the Mac's run section draws it.
    var color: CarryOnColorStyle {
        switch tone {
        case .plain: .coTextPrimary
        case .accent: .coTextAccent
        case .warning: .coStatusWarning
        case .danger: .coStatusDanger
        }
    }
}
