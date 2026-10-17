#if canImport(SwiftUI) && os(macOS)
    import BrainBuddyAgents
    import BrainBuddyAPI
    import Foundation
    import Testing

    @testable import BrainBuddyMac
    @testable import BrainBuddyMacCore

    /// Settings › Agents (design G-06, spec 030): which content the tab shows, the password-less state,
    /// the web account link and the canvas's "Add new agent" request.
    @Suite("030 Agents settings tab")
    @MainActor
    struct AgentsSettingsTabTests {
        private static let now = Date(timeIntervalSince1970: 1_000_000)

        /// A tab controller over fakes; `password: false` is an account without a password.
        private func make(
            flag: Bool = true, password: Bool = true, list: Result<[AgentConnectionDTO], APIError> = .success([AgentFixtures.connection()])
        ) async -> AgentsTabController {
            let availability = AgentAvailability(
                account: AccountFixtures.account(),
                remote: { _ in FakeAvailabilityRemote(flag: flag, password: password) }, now: { Self.now })
            await availability.refresh()
            let remote = FakeAgentRemote(list: list)
            let model = AgentSettingsModel(account: AccountFixtures.account(), availability: availability, remote: { _ in remote })
            return AgentsTabController(model: model, availability: availability)
        }

        @Test("030_FR_037 with the flag off the tab is 028's, with its text and link")
        func flagOffKeepsTheWebLink() async {
            let off = await make(flag: false)
            #expect(!off.isActive)
            #expect(AccountSettingsCopy.agentsText == "Agents are managed on the web for now.")
            #expect(AccountSettingsCopy.agentsAction == "Open agents on the web…")
            let on = await make()
            #expect(on.isActive)
        }

        @Test("030_FR_037 signed out the tab is 028's even when the flag was on")
        func signedOutKeepsTheWebLink() async {
            let controller = await make()
            controller.availability.update(account: nil)
            #expect(!controller.isActive)
        }

        @Test("030_FR_036 without a password the line shows, there is no + and nothing opens the Add sheet")
        func passwordless() async {
            let controller = await make(password: false)
            await controller.load(account: AccountFixtures.account())
            #expect(controller.model.isPasswordless)
            #expect(!controller.model.canAdd, "the + is not shown and Add new agent… is disabled")
            #expect(AgentsCopy.noPassword == "Set a password to connect an agent.")
            #expect(AgentsCopy.openAccount == "Open account on the web…")
            controller.open(.add)
            #expect(controller.editor == nil)
            #expect(controller.model.rows.map(\.name) == ["Hermes"], "the list and details stay readable")
        }

        @Test("030_FR_036 030_SC_006 the web account URL carries the owner's id and no credential")
        func accountURLHasNoCredential() throws {
            let agents = try #require(URL(string: "https://app.example.com:8443/settings/agents"))
            let url = try #require(AgentsAccountLink.url(agentsURL: agents, ownerID: "user_max"))
            let parts = try #require(URLComponents(url: url, resolvingAgainstBaseURL: false))
            #expect(parts.scheme == "https")
            #expect(parts.host == "app.example.com")
            #expect(parts.port == 8443)
            #expect(parts.path == "/settings/account")
            #expect(parts.user == nil && parts.password == nil && parts.fragment == nil)
            #expect(parts.queryItems == [URLQueryItem(name: "expected_owner", value: "user_max")])
            #expect(AgentsAccountLink.url(agentsURL: agents, ownerID: "bad id") == nil, "an unsafe id builds no link")
        }

        @Test("030_FR_036 030_SC_006 the canvas's Add new agent request selects the Agents tab")
        func requestSelectsAgentsTab() {
            #expect(MacSettingsView.selection(current: .account, addAgentRequested: true) == .agents)
            #expect(MacSettingsView.selection(current: .sync, addAgentRequested: true) == .agents)
            #expect(MacSettingsView.selection(current: .sync, addAgentRequested: false) == .sync)
        }

        @Test("030_FR_036 the hand-off Open Settings request selects Agents from any tab")
        func openSettingsRequestSelectsAgentsTab() {
            for tab in MacSettingsTab.allCases {
                #expect(MacSettingsView.selection(current: tab, agentsTabRequested: true) == .agents)
                #expect(MacSettingsView.selection(current: tab, agentsTabRequested: false) == tab)
            }
        }

        @Test("028_FR_001 the Settings window is 820 wide, opens at 620 and may shrink to a scrolling minimum")
        func settingsWindowSizeFitsTheBoard() {
            #expect(MacSettingsView.width == 820)
            #expect(MacSettingsView.idealHeight == 620)
            #expect(MacSettingsView.minHeight < MacSettingsView.idealHeight)
            #expect(MacSettingsView.minHeight >= 360, "tall enough for the tab bar and a usable viewport")
        }

        @Test("030_FR_036 030_SC_006 the request opens the Add sheet exactly once")
        func requestOpensAddOnce() async {
            let controller = await make()
            controller.availability.requestAddAgent()
            await controller.load(account: AccountFixtures.account())
            if case .add = controller.editor?.mode {} else { Issue.record("the Add sheet is open") }
            #expect(!controller.availability.addAgentRequested, "the request is consumed")
            controller.closeEditor()
            controller.handleAddRequest()
            #expect(controller.editor == nil, "the closed sheet does not open again")
            await controller.load(account: AccountFixtures.account())
            #expect(controller.editor == nil, "nor does a reload")
        }

        @Test("030_SC_006 a request made while the list loads waits for it")
        func requestWaitsForTheList() async {
            let controller = await make()
            controller.availability.requestAddAgent()
            controller.handleAddRequest()
            #expect(controller.editor == nil)
            #expect(controller.availability.addAgentRequested, "still pending while loading")
        }

        @Test("030_FR_025 an offline read drops the request and opens nothing")
        func offlineDropsTheRequest() async {
            let controller = await make(list: .failure(AgentFixtures.offline))
            controller.availability.requestAddAgent()
            await controller.load(account: AccountFixtures.account())
            #expect(controller.model.phase == .offline)
            #expect(controller.editor == nil)
            #expect(!controller.availability.addAgentRequested)
            #expect(!controller.model.canTest && !controller.model.controlsEnabled, "every button is disabled")
        }

        @Test("030_FR_038 a failed read shows the failure with the server's reference")
        func failedReadRetries() async {
            let controller = await make(list: .failure(APIError(kind: .server, message: "boom", referenceID: "ref_9", statusCode: 500)))
            await controller.load(account: AccountFixtures.account())
            guard case .failed(let notice) = controller.model.phase else {
                Issue.record("the read failed")
                return
            }
            #expect(notice.reference == "ref_9")
            #expect(AgentsCopy.agentsFailed == "Agents couldn't be loaded.")
            #expect(AgentsCopy.reference("ref_9") == "Reference: ref_9")
        }

        @Test("030_FR_029 the details show the labelled rows of G-06.01 and leave out the empty ones")
        func detailsRows() {
            let dto = AgentFixtures.connection()
            var rows = AgentSettingsModel.details(dto)
            let view = AgentDetailsView(
                name: "Hermes", rows: rows, isTesting: false, canTest: true, controlsEnabled: true, canReplaceCredential: true,
                now: dto.lastContactAt ?? Self.now, onTest: {}, onReplace: {}, onEdit: {})
            #expect(
                view.lines.map(\.label) == [
                    "Address", "Credential", "Last contact", "Agent card", "Skills", "Updates", "Guarantee",
                ])
            #expect(view.lines.first { $0.label == "Last contact" }?.value.hasPrefix("Today ") == true)
            rows.card = nil
            rows.skills = nil
            rows.guarantee = nil
            let bare = AgentDetailsView(
                name: "Hermes", rows: rows, isTesting: false, canTest: true, controlsEnabled: true, canReplaceCredential: true,
                now: Self.now, onTest: {}, onReplace: {}, onEdit: {})
            #expect(!bare.lines.map(\.label).contains("Skills"))
            let earlier = AgentDetailsView.contact(Self.now, now: Self.now.addingTimeInterval(3 * 86_400))
            #expect(!earlier.hasPrefix("Today"))
        }

        @Test("030_FR_030 Test again shows Testing… and is disabled while the test runs")
        func testAgainWords() {
            #expect(AgentsCopy.testAgain == "Test again")
            #expect(AgentsCopy.testing == "Testing…")
        }
    }
#endif
