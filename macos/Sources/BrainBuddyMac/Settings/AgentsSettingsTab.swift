import AppKit
import BrainBuddyAPI
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
        editor = AgentConnectionEditor(mode: mode, model: model)
    }

    func closeEditor() {
        editor?.dismiss()
        editor = nil
    }
}

/// G-06: the list with + and −, the details and, under them, the password-less line, the offline line or
/// the read failure (030-FR-025, 030-FR-029, 030-FR-036, 030-FR-038).
struct AgentsManagerView: View {
    let controller: AgentsTabController
    let accountURL: URL?
    let onOpen: (URL) -> Void

    private var model: AgentSettingsModel { controller.model }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            switch model.phase {
            case .loading where model.connections.isEmpty:
                ProgressView().controlSize(.small).frame(maxWidth: .infinity, minHeight: 160)
            case .sessionEnded:
                MacSheetStatus(text: AccountSettingsCopy.sessionEnded, tone: .warning)
            case .failed(let notice):
                failure(notice)
            default:
                HStack(alignment: .top, spacing: 18) {
                    list
                    detail
                }
                footer
            }
        }
        .padding(20)
        .frame(maxWidth: .infinity, minHeight: 220, alignment: .topLeading)
    }

    private var list: some View {
        VStack(spacing: 6) {
            ScrollView {
                VStack(spacing: 0) {
                    ForEach(model.rows) { row in
                        let chosen = row.id == model.selectedID
                        Button { model.select(row.id) } label: {
                            HStack(spacing: 6) {
                                Text(row.name).font(MacSheetFont.body).lineLimit(1)
                                Spacer(minLength: 4)
                                Text(row.status).font(MacSheetFont.meta).lineLimit(1)
                                    .foregroundStyle(CarryOnColorStyle.coTextSecondary)
                            }
                            .padding(.horizontal, 8).padding(.vertical, 6)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(chosen ? CarryOnColorStyle.coSurfaceSelected : CarryOnColorStyle.coBgGround)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                        .accessibilityElement(children: .combine)
                        .accessibilityAddTraits(chosen ? .isSelected : [])
                    }
                }
            }
            .frame(width: 200, height: 160)
            .overlay { RoundedRectangle(cornerRadius: 6, style: .continuous).strokeBorder(CarryOnColorStyle.coControlQuiet) }
            if !model.isPasswordless {
                HStack(spacing: 6) {
                    Button { controller.open(.add) } label: { MacBoardIconView(icon: .plus, size: 15) }
                        .disabled(!model.canAdd).accessibilityLabel(AgentsCopy.addAgentEllipsis)
                    Button { if let target = model.selected { controller.open(.delete(target)) } } label: { Text("−") }
                        .disabled(!model.controlsEnabled || model.selected == nil).accessibilityLabel("Delete")
                    Spacer()
                }
                .buttonStyle(.carryOnQuiet)
            }
        }
    }

    @ViewBuilder private var detail: some View {
        if let rows = model.details, let target = model.selected {
            VStack(alignment: .leading, spacing: 8) {
                AgentDetailsView(
                    rows: rows, isTesting: model.isTesting, canTest: model.canTest, controlsEnabled: model.controlsEnabled,
                    canReplaceCredential: !model.isPasswordless, onTest: { Task { await model.testAgain() } },
                    onReplace: { controller.open(.replaceCredential(target)) }, onEdit: { controller.open(.edit(target)) })
                if let notice = model.notice { noticeLines(notice) }
            }
        } else {
            VStack(spacing: 10) {
                Text(AgentsCopy.noAgents).font(MacSheetFont.body).foregroundStyle(CarryOnColorStyle.coTextSecondary)
                if !model.isPasswordless {
                    Button(AgentsCopy.addAgentEllipsis) { controller.open(.add) }
                        .buttonStyle(.carryOnSecondary).disabled(!model.canAdd)
                }
            }
            .frame(maxWidth: .infinity, minHeight: 160)
        }
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
        .padding(.leading, 164)
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
