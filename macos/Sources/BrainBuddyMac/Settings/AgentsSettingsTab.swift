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
        let ready: URL? = if case .ready(let url) = link.state { url } else { nil }
        VStack(spacing: 14) {
            Text(AccountSettingsCopy.agentsText).font(MacSheetFont.body).foregroundStyle(CarryOnColorStyle.coTextPrimary)
            Button(AccountSettingsCopy.agentsAction) { if let ready { NSWorkspace.shared.open(ready) } }
                .buttonStyle(.macSecondaryPill).disabled(ready == nil)
            if link.state == .unavailable {
                MacSheetStatus(text: AccountSettingsCopy.agentsUnavailable, tone: .danger, font: MacSheetFont.note)
                Button(AccountSettingsCopy.tryAgain) { Task { await link.load(server: server) } }.buttonStyle(.macText)
            }
        }
        .frame(maxWidth: .infinity, minHeight: 220)
        .task(id: server) { await link.load(server: server) }
    }
}
