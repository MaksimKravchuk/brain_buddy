import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyDesign
import BrainBuddyMacCore
import BrainBuddyWorkspace
import SwiftUI

protocol AgentRunSectionRemote: AgentRunActionsRemote {
    func agentRuns(taskID: String) async throws(APIError) -> [AgentRunDTO]
}

extension BrainBuddyAPIClient: AgentRunSectionRemote {}

/// What one run shows in the inspector (G-05): its label and only the blocks and controls its state and
/// the server's `controls` allow (030-FR-020 – 030-FR-023). Agent text is carried as plain strings and
/// content past its expiry is replaced by the expired label alone (030-FR-027).
struct AgentRunBlock: Equatable {
    enum Tone { case plain, accent, warning, danger }

    var label: String
    var tone = Tone.plain
    var isExpired = false
    var question: String?
    var detail: String?
    var contact: String?
    var showsResult = false
    var result: String?
    var resultLink: String?
    var reply = false, stop = false, check = false, markDone = false, handOffAgain = false

    var color: CarryOnColorStyle {
        switch tone {
        case .plain: .coTextPrimary
        case .accent: .coTextAccent
        case .warning: .coStatusWarning
        case .danger: .coStatusDanger
        }
    }

    init(_ run: AgentRunDTO, now: Date, relay: Bool) {
        let state = run.primaryState
        label = state.label
        if run.contentExpired || state == .contentExpired || now >= run.contentExpiresAt {
            (label, isExpired) = (AgentsCopy.expired, true)
            return
        }
        let time = run.lastContactAt.map { $0.formatted(date: .omitted, time: .shortened) }
        switch state {
        case .needsYou:
            (tone, question, reply, stop) = (.accent, run.questionText, run.controls.reply, run.controls.cancel)
        case .sent, .accepted, .running:
            (detail, stop, contact) = (run.progressText, run.controls.cancel, time.map(AgentsCopy.lastContact))
        case .queued:
            (detail, stop) = (AgentsCopy.queued, run.controls.cancel)
        case .deliveryUnconfirmed:
            check = true
        case .agentReportedComplete:
            label = time.map { "\(AgentsCopy.reportedComplete) · \($0)" } ?? label
            let tooLarge = run.resultAvailability == "too_large"
            (showsResult, markDone, handOffAgain) = (true, true, relay)
            (result, resultLink) = (tooLarge ? AgentsCopy.resultTooLarge : run.resultText, run.resultLink)
        case .failed:
            (tone, detail, handOffAgain) = (.danger, run.failureReason, relay)
        case .stoppedReporting:
            let ago = AgentRunItem.elapsed(since: run.lastContactAt, now: now).map(AgentsCopy.stoppedAgo)
            label = ago.map { "\(AgentsCopy.stoppedReporting) · \($0)" } ?? label
            (tone, stop, handOffAgain) = (.warning, run.controls.cancel, relay)
        case .cancelled, .agentNoLongerReportsThisRun, .connectionDisconnected:
            handOffAgain = relay
        case .notSent, .cancellationRequested, .contentExpired, .unknown:
            break
        }
    }
}

/// One line of the timeline: the state word and "10:02 · Guaranteed single start".
struct AgentTimelineRow: Equatable {
    var word: String
    var meta: String

    static func rows(_ run: AgentRunDTO) -> [AgentTimelineRow] {
        func time(_ date: Date) -> String { date.formatted(date: .omitted, time: .shortened) }
        let tier: String? = switch run.guaranteeTier {
        case .guaranteed: AgentsCopy.guaranteed
        case .bestEffort: AgentsCopy.bestEffort
        default: nil
        }
        let first = AgentTimelineRow(word: AgentPrimaryState.sent.label, meta: ([time(run.createdAt)] + [tier].compactMap { $0 }).joined(separator: " · "))
        let words = ["accepted": "Accepted", "running": "Running", "blocked": "Needs you", "completed": AgentsCopy.reportedComplete, "failed": "Failed"]
        return [first] + run.events.sorted { $0.receivedAt < $1.receivedAt }.map { event in
            AgentTimelineRow(word: event.kind == "task_succession" ? AgentsCopy.succession : words[event.type] ?? "Cancelled", meta: time(event.receivedAt))
        }
    }
}

/// The state behind one step's run section: its runs (newest first), the drafts and the run actions. Memory only.
@MainActor
@Observable
final class AgentRunSectionModel {
    private(set) var runs: [AgentRunDTO] = []
    private(set) var asksPassword = false
    /// The last read of this step's runs failed: what shows is the last known state, read-only (030-FR-025).
    private(set) var isStale = false
    var selectedRunID: String?
    var answer = ""
    var nextStep = ""
    var password = ""

    let taskServerID: String
    let projectID: String?
    @ObservationIgnored private let remote: any AgentRunSectionRemote
    @ObservationIgnored private let availability: AgentAvailability
    @ObservationIgnored private let steps: any StepCommands
    @ObservationIgnored private let refreshStore: @MainActor () async -> Void
    @ObservationIgnored let now: @MainActor () -> Date
    @ObservationIgnored private let cachedRun: @MainActor () -> AgentRunDTO?
    @ObservationIgnored private(set) lazy var actions = AgentRunActions(
        remote: remote, availability: availability, steps: steps, refresh: { [weak self] in await self?.refreshAll() })

    init(
        taskServerID: String, projectID: String?, remote: any AgentRunSectionRemote, availability: AgentAvailability,
        steps: any StepCommands, now: @escaping @MainActor () -> Date = { Date() },
        refreshStore: @escaping @MainActor () async -> Void = {},
        cachedRun: @escaping @MainActor () -> AgentRunDTO? = { nil }
    ) {
        (self.taskServerID, self.projectID, self.remote) = (taskServerID, projectID, remote)
        (self.availability, self.steps, self.now, self.refreshStore) = (availability, steps, now, refreshStore)
        self.cachedRun = cachedRun
    }

    var shown: AgentRunDTO? { runs.first { $0.id == selectedRunID } ?? runs.first }

    /// Choosing the shown earlier run again goes back to the latest.
    func choose(_ run: AgentRunDTO) { selectedRunID = selectedRunID == run.id ? nil : run.id }

    func load() async {
        guard let all = try? await remote.agentRuns(taskID: taskServerID) else {
            isStale = true
            if runs.isEmpty, let cached = cachedRun() { runs = [cached] }
            return
        }
        isStale = false
        runs = all.sorted { $0.createdAt > $1.createdAt }
        if let selectedRunID, !runs.contains(where: { $0.id == selectedRunID }) { self.selectedRunID = nil }
    }

    private func refreshAll() async {
        await refreshStore()
        await load()
    }

    func sendReply() async {
        guard let run = shown else { return }
        await actions.reply(to: run, message: answer)
        if actions.phase == .done { answer = "" }
    }

    /// The password field appears only after the server refused a check for want of it, and is cleared after each try.
    func checkAgain() async {
        guard let run = shown else { return }
        await actions.checkAgain(run, password: password)
        password = ""
        asksPassword = actions.phase == .failed(.wrongPassword)
    }
}

/// The workspace's complete and create commands, for the step this inspector shows (030-FR-012, 030-FR-022).
@MainActor
struct InspectorStepCommands: StepCommands {
    let model: BrainBuddyModel
    let taskID: TaskID

    func completeStep(serverID: String) async throws {
        try await model.workspace.completeTask(taskID, editorID: UUID().uuidString)
    }

    func createNextAction(title: String, projectID: String?) async throws {
        let project = projectID.map { ProjectID($0) }
        let command: GTDCommand = .createTask(.init(taskID: .random(), title: title, list: .next, projectID: project))
        try await model.workspace.apply([command], editorID: UUID().uuidString)
    }
}

/// G-05: the latest run of the step in the inspector (030-FR-019 – 030-FR-028). Agent text is `Text(verbatim:)`:
/// no Markdown, no HTML, no link.
struct AgentRunSectionView: View {
    let model: BrainBuddyModel
    let task: TaskRecord
    /// "Hand off again" shows only when this is set (the hand-off sheet, 030 PR-09).
    var onHandOff: (() -> Void)?
    @State private var section: AgentRunSectionModel

    init?(model: BrainBuddyModel, task: TaskRecord, onHandOff: (() -> Void)? = nil) {
        guard let server = task.serverID, let account = model.workspace.account else { return nil }
        let client = BrainBuddyAPIClient(baseURL: account.serverURL, tokenStore: WorkspaceHost.systemTokenStore(), identity: WorkspaceHost.clientIdentity)
        let runs = model.agentRuns
        (self.model, self.task, self.onHandOff) = (model, task, onHandOff)
        _section = State(initialValue: AgentRunSectionModel(
            taskServerID: server, projectID: task.projectID?.rawValue, remote: client, availability: model.agentAvailability,
            steps: InspectorStepCommands(model: model, taskID: task.id), refreshStore: { await runs.refresh() },
            cachedRun: { [server] in runs.cachedRun(taskServerID: server) }))
    }

    /// Actions need a connection and a fresh read of this run; a stale view is read-only.
    private var online: Bool { model.agentAvailability.isOnline && !section.isStale }
    private var item: AgentRunItem? { model.agentRuns.items.first { $0.taskServerID == task.serverID } }
    private var refreshKey: String {
        "\(item?.state.label ?? "")|\(item?.lastContactAt?.timeIntervalSince1970 ?? 0)|\(model.agentRuns.lastUpdated?.timeIntervalSince1970 ?? 0)"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let run = section.shown {
                runContent(run, AgentRunBlock(run, now: section.now(), relay: model.agentAvailability.relayEnabled && onHandOff != nil))
            }
            earlierRuns
        }
        .task(id: refreshKey) { await section.load() }
    }

    @ViewBuilder
    private func runContent(_ run: AgentRunDTO, _ block: AgentRunBlock) -> some View {
        MacInspectorSectionLabel(run.agentName)
        Text(verbatim: block.label)
            .font(MacRowFont.titleStrong).foregroundStyle(block.color)
            .frame(maxWidth: .infinity, alignment: .leading)
            .accessibilityLabel(block.label)
        if block.isExpired { EmptyView() } else { details(run, block) }
    }

    @ViewBuilder
    private func details(_ run: AgentRunDTO, _ block: AgentRunBlock) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(Array(AgentTimelineRow.rows(run).enumerated()), id: \.offset) { _, row in
                HStack(spacing: 6) {
                    Text(verbatim: row.word).font(MacRowFont.sectionHeader).foregroundStyle(CarryOnColorStyle.coTextPrimary)
                    Text(verbatim: row.meta).font(MacRowFont.meta).foregroundStyle(CarryOnColorStyle.coTextSecondary)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading).padding(.top, 8)
        if !online || model.agentRuns.phase == .stale, let at = model.agentRuns.lastUpdated ?? run.lastContactAt {
            MacInspectorMetaText(text: AgentsCopy.lastUpdated(at.formatted(date: .omitted, time: .shortened)))
        }
        stateBlock(run, block)
    }

    @ViewBuilder
    private func stateBlock(_ run: AgentRunDTO, _ block: AgentRunBlock) -> some View {
        if let question = block.question {
            card(AgentsCopy.asks(run.agentName), question)
            if block.reply { replyForm(run, block) }
        }
        if let detail = block.detail { plain(detail, block.color) }
        if let contact = block.contact { MacInspectorMetaText(text: contact) }
        if block.showsResult { resultBlock(block) }
        if block.check { checkForm }
        if (block.stop && !block.reply) || (block.handOffAgain && !block.markDone) { buttonRow(block) }
        if (block.reply || block.stop || block.check) && !online { MacInspectorMetaText(text: AgentsCopy.needsConnection) }
        if case .failed(let failure) = section.actions.phase {
            plain([failure.text(), failure.reference].compactMap { $0 }.joined(separator: " "), .coStatusDanger)
        }
    }

    private func plain(_ text: String, _ color: CarryOnColorStyle) -> some View {
        Text(verbatim: text).font(MacRowFont.action(size: 14, weight: 400, relativeTo: .body)).foregroundStyle(color)
            .fixedSize(horizontal: false, vertical: true).frame(maxWidth: .infinity, alignment: .leading).padding(.top, 8)
    }

    private func card(_ title: String, _ text: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(verbatim: title).font(MacRowFont.sectionHeader).foregroundStyle(CarryOnColorStyle.coTextSecondary)
            Text(verbatim: text).font(MacRowFont.action(size: 14, weight: 400, relativeTo: .body)).foregroundStyle(CarryOnColorStyle.coTextPrimary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(10).frame(maxWidth: .infinity, alignment: .leading)
        .background(CarryOnColorStyle.coSurfaceCard, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        .padding(.top, 8).accessibilityElement(children: .combine)
    }

    private func field(_ name: String, text: Binding<String>, secure: Bool = false) -> some View {
        Group {
            if secure { SecureField(name, text: text) } else { TextField(name, text: text, axis: .vertical).lineLimit(2...5) }
        }
        .textFieldStyle(.plain).font(MacRowFont.title).foregroundStyle(CarryOnColorStyle.coTextPrimary)
        .padding(.horizontal, 10).padding(.vertical, 7)
        .background(CarryOnColorStyle.coFieldBg, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        .padding(.top, 8).accessibilityLabel(name)
    }

    private func replyForm(_ run: AgentRunDTO, _ block: AgentRunBlock) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            field(AgentsCopy.yourAnswer, text: $section.answer)
            if run.replyPending { MacInspectorMetaText(text: AgentsCopy.replySent) }
            HStack(spacing: 8) {
                Button(AgentsCopy.reply) { Task { await section.sendReply() } }
                    .buttonStyle(.carryOnPrimary)
                    .disabled(!online || run.replyPending || section.actions.phase == .working
                        || section.answer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                if block.stop {
                    Button(AgentsCopy.stopRun) { Task { if let run = section.shown { await section.actions.stop(run) } } }
                        .buttonStyle(.carryOnSecondary).disabled(!online || section.actions.phase == .working)
                }
            }
            .padding(.top, 8)
        }
    }

    @ViewBuilder
    private var checkForm: some View {
        if section.asksPassword { field(AgentsCopy.currentPassword, text: $section.password, secure: true) }
        Button(AgentsCopy.checkAgain) { Task { await section.checkAgain() } }
            .buttonStyle(.carryOnSecondary).padding(.top, 8)
            .disabled(!online || section.actions.phase == .working || (section.asksPassword && section.password.isEmpty))
    }

    /// Stop run where the question is not shown (running, queued, stopped reporting), and Hand off again where offered.
    private func buttonRow(_ block: AgentRunBlock) -> some View {
        HStack(spacing: 8) {
            if block.stop && !block.reply {
                Button(AgentsCopy.stopRun) { Task { if let run = section.shown { await section.actions.stop(run) } } }
                    .buttonStyle(.carryOnSecondary).disabled(!online || section.actions.phase == .working)
            }
            if block.handOffAgain, let onHandOff { Button(AgentsCopy.handOffAgain, action: onHandOff).buttonStyle(.carryOnSecondary) }
        }
        .padding(.top, 8)
    }

    @ViewBuilder
    private func resultBlock(_ block: AgentRunBlock) -> some View {
        MacInspectorSectionLabel(AgentsCopy.result)
        if let result = block.result { plain(result, .coTextPrimary) }
        if let link = block.resultLink { plain(link, .coTextSecondary) }
        MacInspectorMetaText(text: AgentsCopy.finishingIsYours)
        MacInspectorSectionLabel(AgentsCopy.then)
        field(AgentsCopy.makeNextStep, text: $section.nextStep)
        HStack(spacing: 8) {
            Button(AgentsCopy.markDone) { Task { await section.actions.markStepDone(taskServerID: section.taskServerID, projectID: section.projectID, nextStep: section.nextStep) } }
                .buttonStyle(.carryOnPrimary).disabled(section.actions.phase == .working)
            if block.handOffAgain, let onHandOff { Button(AgentsCopy.handOffAgain, action: onHandOff).buttonStyle(.carryOnSecondary) }
        }
        .padding(.top, 8)
    }

    @ViewBuilder
    private var earlierRuns: some View {
        if section.runs.count > 1 {
            MacInspectorSectionLabel(AgentsCopy.earlierRuns)
            ForEach(Array(section.runs.dropFirst()), id: \.id) { run in
                Button { section.choose(run) } label: {
                    Text(verbatim: [run.agentName, AgentRunBlock(run, now: section.now(), relay: false).label, run.createdAt.formatted(.dateTime.day().month(.abbreviated))].joined(separator: " · ")).font(MacRowFont.meta).foregroundStyle(CarryOnColorStyle.coTextSecondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .buttonStyle(.plain).padding(.bottom, 4)
                .accessibilityAddTraits(section.shown?.id == run.id ? .isSelected : [])
            }
        }
    }
}
