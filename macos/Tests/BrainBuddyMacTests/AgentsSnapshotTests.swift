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

        /// The M29 board's "Today 10:21" in the host's Amsterdam time zone.
        private static let now = Calendar.current.date(from: DateComponents(
            year: 2026, month: 10, day: 16, hour: 10, minute: 21))!

        private func hermesFixture() -> AgentConnectionDTO {
            let contactAt = ISO8601DateFormatter().string(from: Self.now)
            let data = Data(#"""
                {"id":"agent_1","name":"Hermes","agent_address":"https://hermes.myhost.dev",
                "auth_scheme":"bearer","auth_header_name":null,"status":"ready","stale":false,
                "stale_after_seconds":900,"ready_for_handoff":true,
                "capabilities":{"streaming":true,"push_notifications":false},
                "controls_offered":{"reply":true,"cancel":true},
                "card":{"name":"Hermes","version":"2.3","description":null,"protocol_version":"1.0",
                "interface_url":null,"skills":[{"id":"s1","name":"Web research","description":null},
                {"id":"s2","name":"bookings","description":null},
                {"id":"s3","name":"email drafts","description":null}]},
                "guarantee_tier":"guaranteed","tier_disclosure":null,"cancellation_disclosure":null,
                "agent_changed":false,"last_test_error_code":null,"last_contact_at":"\#(contactAt)",
                "last_tested_at":"2026-10-16T08:00:00Z","created_at":"2026-10-01T08:00:00Z","revision":3}
                """#.utf8)
            return try! BrainBuddyAPI.makeDecoder().decode(AgentConnectionDTO.self, from: data)
        }

        private func makeController(password: Bool = true) async -> AgentsTabController {
            let availability = AgentAvailability(
                account: AccountFixtures.account(),
                remote: { _ in FakeAvailabilityRemote(password: password) }, now: { Self.now })
            await availability.refresh()
            let agents = [
                hermesFixture(),
                AgentFixtures.connection(id: "agent_2", name: "Claude", address: "https://claude.example.org"),
                AgentFixtures.connection(id: "agent_3", name: "Home server", stale: true, ready: false),
            ]
            let remote = FakeAgentRemote(list: .success(agents))
            let model = AgentSettingsModel(
                account: AccountFixtures.account(), availability: availability, remote: { _ in remote })
            let controller = AgentsTabController(model: model, availability: availability)
            await controller.load(account: AccountFixtures.account())
            #expect(model.rows.map(\.name) == ["Hermes", "Claude", "Home server"])
            #expect(model.rows.map(\.status) == ["Tested ready", "Tested ready", "Stale"])
            #expect(model.details?.skills == "Web research, bookings, email drafts")
            #expect(model.details?.lastContact == Self.now)
            #expect(AgentDetailsView.contact(Self.now, now: Self.now) == "Today 10:21")
            return controller
        }

        private func manager(_ controller: AgentsTabController) -> some View {
            AgentsManagerView(controller: controller, accountURL: URL(string: "https://app.brainbuddy.example/settings/account"), onOpen: { _ in })
                .frame(width: 820, height: MacSettingsView.idealHeight, alignment: .topLeading)
                .background(CarryOnColorStyle.coBgGround)
        }

        @Test("030_FR_029 030_SC_009 Settings Agents details render in both appearances", arguments: Appearance.allCases)
        func loadedDetails(appearance: Appearance) async {
            let controller = await makeController()
            assertMacSnapshot(
                manager(controller), named: "mac-agents-settings-ready-\(appearance.rawValue)",
                scheme: appearance.scheme, width: 820)
        }

        @Test("030_FR_036 030_SC_009 passwordless Settings Agents render read-only in both appearances", arguments: Appearance.allCases)
        func passwordlessDetails(appearance: Appearance) async {
            let controller = await makeController(password: false)
            assertMacSnapshot(
                manager(controller), named: "mac-agents-settings-passwordless-\(appearance.rawValue)",
                scheme: appearance.scheme, width: 820)
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
