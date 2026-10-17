import BrainBuddyAgents
import AppKit
import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyDesign
import BrainBuddyMacCore
import Observation
import SwiftUI

/// Design S-03 and, with the relay flag on and an account signed in, G-06. The flag off or signed out
/// leaves 028's tab as it was (030-FR-037): agents are managed on the web for now, and the origin is
/// read from the account's server (or the default one signed out); the button opens
/// `<origin>/settings/agents` (028-FR-019).
struct AgentsSettingsTab: View {
    let sync: MacSyncController
    @State private var link = AgentsWebLink()
    @State private var controller: AgentsTabController?

    init(sync: MacSyncController, availability: AgentAvailability?) {
        self.sync = sync
        _controller = State(
            initialValue: availability.map {
                AgentsTabController(
                    model: AgentSettingsModel(account: sync.workspace.account, availability: $0), availability: $0)
            })
    }

    private var server: URL {
        sync.workspace.account?.serverURL ?? MacHostConfiguration.knownServers().first ?? BrainBuddyAPI.defaultServerURL
    }

    private var accountURL: URL? {
        guard case .ready(let agents) = link.state, let owner = sync.workspace.account?.id else { return nil }
        return AgentsAccountLink.url(agentsURL: agents, ownerID: owner)
    }

    var body: some View {
        Group {
            if let controller, controller.isActive, sync.workspace.account != nil {
                AgentsManagerView(controller: controller, accountURL: accountURL, onOpen: { NSWorkspace.shared.open($0) })
                    .task(id: sync.workspace.account?.id) { await controller.load(account: sync.workspace.account) }
                    .onChange(of: controller.availability.addAgentRequested) { _, _ in controller.handleAddRequest() }
            } else {
                AgentsSettingsContent(
                    state: link.state,
                    onOpen: { url in NSWorkspace.shared.open(url) },
                    onTryAgain: { Task { await link.load(server: server) } }
                )
            }
        }
        .task(id: server) { await link.load(server: server) }
    }
}

/// The web account page for "Open account on the web…" (030-FR-036): the agents page's origin with the
/// kit's account path. The only query is the expected owner's id; there is no credential.
enum AgentsAccountLink {
    static func url(agentsURL: URL, ownerID: String) -> URL? {
        guard var parts = URLComponents(url: agentsURL, resolvingAgainstBaseURL: false) else { return nil }
        (parts.path, parts.query, parts.fragment) = ("", nil, nil)
        return parts.string.flatMap { NativeAccountDestination.url(origin: $0, ownerID: ownerID, deleting: false) }
    }
}

/// What Settings › Agents (G-06) does besides drawing: whether it shows, the sheet it opens, and the
/// one-shot "Add new agent" request from the canvas. The sheets are attached to `editor`.
@MainActor
@Observable
final class AgentsTabController {
    let model: AgentSettingsModel
    let availability: AgentAvailability
    private(set) var editor: AgentConnectionEditor?

    init(model: AgentSettingsModel, availability: AgentAvailability) {
        self.model = model
        self.availability = availability
    }

    /// 030-FR-037: the flag on and an account signed in; otherwise 028's tab.
    var isActive: Bool { availability.ownerID != nil && availability.relayEnabled }

    func load(account: LinkedAccount?) async {
        model.update(account: account)
        await model.reload()
        handleAddRequest()
    }

    /// Opens the Add sheet once for a pending request. While the list is still loading the request waits;
    /// when the controls cannot be used (offline, failed, no password) it is dropped, not kept for later.
    func handleAddRequest() {
        guard availability.addAgentRequested, model.phase != .loading else { return }
        if availability.consumeAddAgentRequest() { open(.add) }
    }

    func open(_ mode: AgentEditorMode) {
        guard editor == nil else { return }
        switch mode {
        case .add: guard model.canAdd else { return }
        default: guard model.controlsEnabled else { return }
        }
        editor = AgentConnectionEditor(mode: mode, model: model, log: SystemMacLog())
    }

    func closeEditor() {
        editor?.dismiss()
        editor = nil
    }
}

/// G-06: the list with + and −, the details and, under them, the password-less line, the offline line or
/// the read failure (030-FR-025, 030-FR-029, 030-FR-036, 030-FR-038).
struct AgentsManagerView: View {
    private typealias Metrics = CarryOnLayout.MacAgents
    let controller: AgentsTabController
    let accountURL: URL?
    let onOpen: (URL) -> Void
    var now: Date = Date()

    @FocusState private var focusedRow: String?

    private var model: AgentSettingsModel { controller.model }

    var body: some View {
        VStack(alignment: .leading, spacing: CarryOnSpace.md) {
            switch model.phase {
            case .loading where model.connections.isEmpty:
                ProgressView().controlSize(.small).frame(maxWidth: .infinity, minHeight: 160)
            case .sessionEnded:
                MacSheetStatus(text: AccountSettingsCopy.sessionEnded, tone: .warning)
            case .failed(let notice):
                failure(notice)
            default:
                HStack(alignment: .top, spacing: Metrics.gap) {
                    list
                    detail
                }
                .frame(maxHeight: .infinity)
                footer
            }
        }
        .padding(.horizontal, Metrics.paddingX)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .containerRelativeFrame(.vertical, alignment: .topLeading) { height, _ in
            max(0, height - Metrics.paddingY * 2)
        }
        .padding(.vertical, Metrics.paddingY)
        .sheet(isPresented: Binding(get: { controller.editor != nil }, set: { if !$0 { controller.closeEditor() } })) {
            if let editor = controller.editor { AgentEditorSheet(editor: editor, onClose: { controller.closeEditor() }) }
        }
    }

    private var list: some View {
        VStack(alignment: .leading, spacing: CarryOnSpace.xs) {
            ScrollView {
                VStack(spacing: CarryOnSpace.xxs) {
                    ForEach(model.rows) { row in
                        let chosen = row.id == model.selectedID
                        Button { model.select(row.id) } label: {
                            HStack(spacing: CarryOnSpace.xs) {
                                MacBoardIconView(icon: .agents, size: Metrics.icon).accessibilityHidden(true)
                                Text(row.name).font(chosen ? MacSheetFont.heading : MacSheetFont.body).lineLimit(1)
                                Spacer(minLength: CarryOnSpace.xxs)
                                statusDot(row.id)
                                Text(row.status).font(MacSheetFont.meta).lineLimit(1)
                                    .foregroundStyle(statusStyle(row.id))
                            }
                            .padding(.horizontal, CarryOnSpace.sm)
                            .frame(maxWidth: .infinity, minHeight: CarryOnLayout.MacSidebarRow.height, alignment: .leading)
                            .background {
                                if chosen {
                                    RoundedRectangle(cornerRadius: CarryOnRadius.sm, style: .continuous)
                                        .fill(CarryOnColorStyle.coSurfaceCard)
                                }
                            }
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .focused($focusedRow, equals: row.id)
                        .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                        .accessibilityElement(children: .combine)
                        .accessibilityAddTraits(chosen ? .isSelected : [])
                    }
                }
            }
            .onKeyPress(.upArrow) { moveSelection(by: -1) }
            .onKeyPress(.downArrow) { moveSelection(by: 1) }
            .frame(maxHeight: .infinity)
            if !model.isPasswordless {
                HStack(spacing: CarryOnSpace.xs) {
                    Button { controller.open(.add) } label: { MacBoardIconView(icon: .plus, size: Metrics.icon) }
                        .disabled(!model.canAdd).accessibilityLabel(AgentsCopy.addAgentEllipsis)
                    Button { if let target = model.selected { controller.open(.delete(target)) } } label: { Text("−") }
                        .disabled(!model.controlsEnabled || model.selected == nil).accessibilityLabel("Delete")
                }
                .buttonStyle(.carryOnSecondaryIcon)
            }
        }
        .frame(width: Metrics.listWidth)
    }

    /// Up/Down change the selected agent and carry focus with it (030-FR-040).
    private func moveSelection(by offset: Int) -> KeyPress.Result {
        guard let id = model.moveSelection(by: offset) else { return .ignored }
        focusedRow = id
        return .handled
    }

    private func statusStyle(_ id: String) -> CarryOnColorStyle {
        model.connections.first { $0.id == id }?.stale == true ? .coStatusWarning : .coTextSecondary
    }

    private func statusDotStyle(_ id: String) -> CarryOnColorStyle {
        model.connections.first { $0.id == id }?.stale == true ? .coStatusWarning : .coMarkOpen
    }

    private func statusDot(_ id: String) -> some View {
        Circle().fill(statusDotStyle(id))
            .frame(width: Metrics.statusDot, height: Metrics.statusDot).accessibilityHidden(true)
    }

    private var detail: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: CarryOnSpace.xs) {
                if let rows = model.details, let target = model.selected {
                    AgentDetailsView(
                        name: target.name, rows: rows, isTesting: model.isTesting, canTest: model.canTest,
                        controlsEnabled: model.controlsEnabled, canReplaceCredential: !model.isPasswordless,
                        statusStyle: statusStyle(target.id), statusDotStyle: statusDotStyle(target.id), now: now,
                        onTest: { Task { await model.testAgain() } },
                        onReplace: { controller.open(.replaceCredential(target)) }, onEdit: { controller.open(.edit(target)) })
                    if let notice = model.notice { noticeLines(notice) }
                } else {
                    Text(AgentsCopy.noAgents).font(MacSheetFont.body).foregroundStyle(CarryOnColorStyle.coTextSecondary)
                    if !model.isPasswordless {
                        Button(AgentsCopy.addAgentEllipsis) { controller.open(.add) }
                            .buttonStyle(.carryOnSecondary).disabled(!model.canAdd)
                    }
                }
            }
            .padding(Metrics.detailPadding)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(CarryOnColorStyle.coSurfaceCard, in: RoundedRectangle(cornerRadius: CarryOnRadius.md, style: .continuous))
    }

    @ViewBuilder private var footer: some View {
        if model.phase == .offline {
            MacSheetStatus(text: AgentsCopy.needsConnection, tone: .secondary, font: MacSheetFont.note)
        }
        if model.isPasswordless {
            HStack(spacing: 10) {
                MacSheetStatus(text: AgentsCopy.noPassword, tone: .secondary, font: MacSheetFont.note)
                Button(AgentsCopy.openAccount) { if let accountURL { onOpen(accountURL) } }
                    .buttonStyle(.carryOnSecondary).disabled(accountURL == nil)
            }
        }
    }

    private func failure(_ notice: AgentNotice) -> some View {
        VStack(spacing: 10) {
            MacSheetStatus(text: AgentsCopy.agentsFailed, tone: .danger, font: MacSheetFont.note)
            if let reference = notice.reference { referenceLine(reference) }
            Button(AgentsCopy.tryAgain) { Task { await model.reload() } }.buttonStyle(.macText)
        }
        .frame(maxWidth: .infinity, minHeight: 160)
    }

    private func noticeLines(_ notice: AgentNotice) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            MacSheetStatus(text: notice.message, tone: .danger, font: MacSheetFont.note)
            if let reference = notice.reference { referenceLine(reference) }
        }
    }

    private func referenceLine(_ reference: String) -> some View {
        Text(AgentsCopy.reference(reference)).font(MacSheetFont.reference)
            .foregroundStyle(CarryOnColorStyle.coTextSecondary).textSelection(.enabled)
    }
}

/// What the Agents tab shows for one `AgentsWebLink.State`; the snapshot tests render it directly.
struct AgentsSettingsContent: View {
    let state: AgentsWebLink.State
    let onOpen: (URL) -> Void
    let onTryAgain: () -> Void

    var body: some View {
        let ready: URL? = if case .ready(let url) = state { url } else { nil }
        VStack(spacing: 14) {
            Text(AccountSettingsCopy.agentsText).font(MacSheetFont.body).foregroundStyle(CarryOnColorStyle.coTextPrimary)
            Button(AccountSettingsCopy.agentsAction) { if let ready { onOpen(ready) } }
                .buttonStyle(.carryOnSecondary).disabled(ready == nil)
            if state == .unavailable {
                MacSheetStatus(text: AccountSettingsCopy.agentsUnavailable, tone: .danger, font: MacSheetFont.note)
                Button(AccountSettingsCopy.tryAgain) { onTryAgain() }.buttonStyle(.macText)
            }
        }
        .frame(maxWidth: .infinity, minHeight: 220)
    }
}
