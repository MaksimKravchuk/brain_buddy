import AppKit
import BrainBuddyAPI
import BrainBuddyDesign
import BrainBuddyMacCore
import SwiftUI

/// Design S-03: agents are managed on the web for now. The origin is read from the account's server
/// (or the default one signed out); the button opens `<origin>/settings/agents` (028-FR-019).
struct AgentsSettingsTab: View {
    let sync: MacSyncController
    @State private var link = AgentsWebLink()

    private var server: URL {
        sync.workspace.account?.serverURL ?? MacHostConfiguration.knownServers().first ?? BrainBuddyAPI.defaultServerURL
    }

    var body: some View {
        AgentsSettingsContent(
            state: link.state,
            onOpen: { url in NSWorkspace.shared.open(url) },
            onTryAgain: { Task { await link.load(server: server) } }
        )
        .task(id: server) { await link.load(server: server) }
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
