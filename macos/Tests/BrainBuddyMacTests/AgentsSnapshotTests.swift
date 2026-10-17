#if canImport(SwiftUI) && os(macOS)
    import BrainBuddyAPI
    import BrainBuddyDesign
    import Foundation
    import SwiftUI
    import Testing

    @testable import BrainBuddyMac
    @testable import BrainBuddyMacCore

    /// Deterministic renders for G-06 and G-07. The higher-level run and hand-off screens currently
    /// construct live API clients inside their views, so they cannot be seeded by these fakes.
    @Suite("Mac agent snapshots")
    @MainActor
    struct AgentsSnapshotTests {
        enum Appearance: String, CaseIterable, Sendable {
            case light, dark

            var scheme: ColorScheme { self == .dark ? .dark : .light }
        }

        private static let now = Date(timeIntervalSince1970: 1_792_132_860)

        private func makeController(password: Bool = true) async -> AgentsTabController {
            let availability = AgentAvailability(
                account: AccountFixtures.account(),
                remote: { _ in FakeAvailabilityRemote(password: password) }, now: { Self.now })
            await availability.refresh()
            let agents = [
                AgentFixtures.connection(),
                AgentFixtures.connection(id: "agent_2", name: "Claude", address: "https://claude.example.org"),
                AgentFixtures.connection(id: "agent_3", name: "Home server", stale: true),
            ]
            let remote = FakeAgentRemote(list: .success(agents))
            let model = AgentSettingsModel(
                account: AccountFixtures.account(), availability: availability, remote: { _ in remote })
            let controller = AgentsTabController(model: model, availability: availability)
            await controller.load(account: AccountFixtures.account())
            return controller
        }

        private func manager(_ controller: AgentsTabController) -> some View {
            AgentsManagerView(controller: controller, accountURL: URL(string: "https://app.brainbuddy.example/settings/account"), onOpen: { _ in })
                .frame(width: 560, alignment: .topLeading)
                .background(CarryOnColorStyle.coBgGround)
        }

        @Test("030_FR_029 030_SC_009 Settings Agents details render in both appearances", arguments: Appearance.allCases)
        func loadedDetails(appearance: Appearance) async {
            let controller = await makeController()
            assertMacSnapshot(
                manager(controller), named: "mac-agents-settings-ready-\(appearance.rawValue)",
                scheme: appearance.scheme, width: 560)
        }

        @Test("030_FR_036 030_SC_009 passwordless Settings Agents render read-only in both appearances", arguments: Appearance.allCases)
        func passwordlessDetails(appearance: Appearance) async {
            let controller = await makeController(password: false)
            assertMacSnapshot(
                manager(controller), named: "mac-agents-settings-passwordless-\(appearance.rawValue)",
                scheme: appearance.scheme, width: 560)
        }

        @Test("030_FR_031 030_SC_009 empty Add agent sheet renders in both appearances", arguments: Appearance.allCases)
        func addAgent(appearance: Appearance) async {
            let controller = await makeController()
            let editor = AgentConnectionEditor(mode: .add, model: controller.model)
            assertMacSnapshot(
                AgentEditorSheet(editor: editor, onClose: {}), named: "mac-agents-add-empty-\(appearance.rawValue)",
                scheme: appearance.scheme, width: 440)
        }
    }
#endif
