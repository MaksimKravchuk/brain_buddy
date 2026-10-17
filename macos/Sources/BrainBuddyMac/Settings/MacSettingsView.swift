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

/// Keep the native Settings scene in one place so its window constraints are also exercised by
/// native scene tests. The app owns the selection, exactly as before.
struct MacSettingsScene<Content: View>: Scene {
    @ViewBuilder var content: Content

    var body: some Scene {
        Settings {
            content.environment(\.carryOnPlatform, .mac)
        }
        .windowResizability(.contentMinSize)
        .defaultSize(width: MacSettingsView.width, height: MacSettingsView.idealHeight)
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
        .containerBackground(CarryOnColorStyle.coBgGround, for: .window)
        .toolbarBackground(.regularMaterial, for: .windowToolbar)
        .toolbarBackgroundVisibility(.visible, for: .windowToolbar)
        .navigationTitle(selection.title)
        .onChange(of: launch.model?.agentAvailability.addAgentRequested ?? false) { _, requested in
            selection = Self.selection(current: selection, addAgentRequested: requested)
        }
        .onChange(of: launch.model?.agentAvailability.agentsTabRequested ?? false) { _, requested in
            if requested { showRequestedAgentsTab() }
        }
        .onAppear {
            selection = Self.selection(
                current: selection, addAgentRequested: launch.model?.agentAvailability.addAgentRequested ?? false)
            showRequestedAgentsTab()
        }
        .toolbar {
            ToolbarItem(placement: .principal) {
                HStack(spacing: CarryOnSpace.xxs) { ForEach(MacSettingsTab.allCases) { tabButton($0) } }
                    .accessibilityElement(children: .contain)
            }
            .sharedBackgroundVisibility(.hidden)
        }
    }

    /// M25/M29 draw an 820 × 620 pt outer window. The native toolbar adds to the content's
    /// 420 pt minimum; each tab continues to scroll when the window is shortened.
    static let width = CarryOnLayout.MacSettings.width
    static let idealHeight = CarryOnLayout.MacSettings.height
    static let minHeight = CarryOnLayout.MacSettings.minContentHeight

    /// The canvas's "Add new agent" request brings the Agents tab forward; the tab opens the sheet once.
    static func selection(current: MacSettingsTab, addAgentRequested: Bool) -> MacSettingsTab {
        addAgentRequested ? .agents : current
    }

    /// The hand-off sheet's "Open Settings" brings Agents forward, whether Settings was closed or open elsewhere.
    private func showRequestedAgentsTab() {
        guard let availability = launch.model?.agentAvailability else { return }
        selection = Self.selection(current: selection, agentsTabRequested: availability.consumeAgentsTabRequest())
    }

    static func selection(current: MacSettingsTab, agentsTabRequested: Bool) -> MacSettingsTab {
        agentsTabRequested ? .agents : current
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
            .frame(width: CarryOnLayout.MacSettings.tabWidth, height: CarryOnLayout.MacSettings.tabHeight)
            .background {
                if chosen { RoundedRectangle(cornerRadius: CarryOnRadius.sm, style: .continuous).fill(CarryOnColorStyle.coControlQuiet) }
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
