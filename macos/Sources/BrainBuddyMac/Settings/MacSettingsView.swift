import AppKit
import BrainBuddyDesign
import BrainBuddyMacCore
import SwiftUI

enum MacSettingsTab: Int, CaseIterable, Identifiable {
    case account, agents, sync

    var id: Int { rawValue }
    var title: String { AccountSettingsCopy.tabNames[rawValue] }
    var icon: MacBoardIcon {
        switch self {
        case .account: .account
        case .agents: .agents
        case .sync: .sync
        }
    }
}

/// Design S-01: ⌘, / Settings…, no flag (028-FR-001). The selection lives in the app, so it is kept.
struct MacSettingsView: View {
    let launch: MacLaunch
    @Binding var selection: MacSettingsTab
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        Group {
            if let sync = launch.sync {
                switch selection {
                case .account: AccountSettingsTab(sync: sync, openMainWindow: openMainWindow)
                case .agents: AgentsSettingsTab(sync: sync)
                case .sync: SyncSettingsTab(controller: sync)
                }
            }
        }
        .frame(minWidth: 820, maxWidth: 820, minHeight: 240)
        .background(CarryOnColorStyle.coBgGround)
        .navigationTitle(selection.title)
        .toolbar {
            ToolbarItem(placement: .principal) {
                HStack(spacing: 4) { ForEach(MacSettingsTab.allCases) { tabButton($0) } }
            }
        }
    }

    private func tabButton(_ tab: MacSettingsTab) -> some View {
        let chosen = tab == selection
        return Button {
            selection = tab
        } label: {
            VStack(spacing: 2) {
                MacBoardIconView(icon: tab.icon, size: 20)
                Text(tab.title).font(chosen ? MacSheetFont.metaStrong : MacSheetFont.meta)
            }
            .foregroundStyle(chosen ? CarryOnColorStyle.coTextPrimary : CarryOnColorStyle.coTextSecondary)
            .padding(.horizontal, 12).padding(.vertical, 4)
            .background {
                if chosen { RoundedRectangle(cornerRadius: 8, style: .continuous).fill(CarryOnColorStyle.coControlQuiet) }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(tab.title)
        .accessibilityAddTraits(chosen ? .isSelected : [])
    }

    private func openMainWindow() {
        openWindow(id: "main")
        NSApp.activate()
    }
}
