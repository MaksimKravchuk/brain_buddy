import AppKit
import BrainBuddyDesign
import BrainBuddyMacCore
import SwiftUI

enum MacSettingsTab: Int, CaseIterable, Identifiable {
    case account, agents, sync

    var id: Int { rawValue }
    var title: String { AccountSettingsCopy.tabNames[rawValue] }
    /// Each tab's own accessible name (028-FR-002); never shared between tabs.
    var accessibilityName: String { title }
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
        ScrollView {
            if let sync = launch.sync {
                switch selection {
                case .account: AccountSettingsTab(sync: sync, openMainWindow: openMainWindow)
                case .agents: AgentsSettingsTab(sync: sync, availability: launch.model?.agentAvailability)
                case .sync: SyncSettingsTab(controller: sync)
                }
            }
        }
        .frame(
            minWidth: Self.width, maxWidth: Self.width,
            minHeight: Self.minHeight, idealHeight: Self.idealHeight, maxHeight: .infinity)
        .background(CarryOnColorStyle.coBgGround)
        .navigationTitle(selection.title)
        .onChange(of: launch.model?.agentAvailability.addAgentRequested ?? false) { _, requested in
            selection = Self.selection(current: selection, addAgentRequested: requested)
        }
        .onAppear {
            selection = Self.selection(
                current: selection, addAgentRequested: launch.model?.agentAvailability.addAgentRequested ?? false)
        }
        .toolbar {
            ToolbarItem(placement: .principal) {
                HStack(spacing: 4) { ForEach(MacSettingsTab.allCases) { tabButton($0) } }
                    .accessibilityElement(children: .contain)
            }
        }
    }

    /// Design S-01: 820 pt wide; M25 draws Account 620 pt tall. The window opens at the ideal height, can
    /// be resized taller or shorter down to the minimum, and each tab scrolls instead of clipping.
    static let width: CGFloat = 820
    static let idealHeight: CGFloat = 620
    static let minHeight: CGFloat = 420

    /// The canvas's "Add new agent" request brings the Agents tab forward; the tab opens the sheet once.
    static func selection(current: MacSettingsTab, addAgentRequested: Bool) -> MacSettingsTab {
        addAgentRequested ? .agents : current
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
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(tab.accessibilityName)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(tab.accessibilityName)
        .accessibilityIdentifier("settings-tab-\(tab.accessibilityName.lowercased())")
        .accessibilityAddTraits(chosen ? .isSelected : [])
    }

    private func openMainWindow() {
        openWindow(id: "main")
        NSApp.activate()
    }
}
