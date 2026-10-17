#if canImport(SwiftUI) && os(macOS)
    import AppKit
    import BrainBuddyCore
    import BrainBuddyPersistence
    import BrainBuddyWorkspace
    import BrainBuddyAPI
    import BrainBuddyDesign
    import Foundation
    import SwiftUI
    import Testing

    @testable import BrainBuddyMac
    @testable import BrainBuddyMacCore
    /// Synthetic agent surfaces. G-01/G-03 compose the shipped row components, following
    /// CarryOnChromeSnapshotTests; they do not claim full WorkspaceView scene acceptance.
    /// G-04/G-05 cannot inject their private flow state without constructing a live client.
    @Suite("Mac agent snapshots", .serialized)
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

        /// ImageRenderer omits ScrollView document views and native text fields. Host the real
        /// view offscreen, then use the shared assertion for the resulting unmodified bitmap.
        private func assertHostedSnapshot(
            _ view: some View, named name: String, scheme: ColorScheme, width: CGFloat,
            height: CGFloat? = nil, sourceLocation: SourceLocation = #_sourceLocation
        ) {
            let content = view.environment(\.carryOnPlatform, .mac).environment(\.colorScheme, scheme)
            let host = NSHostingView(rootView: content.frame(width: width))
            host.appearance = NSAppearance(named: scheme == .dark ? .darkAqua : .aqua)
            let size = NSSize(width: width, height: height ?? host.fittingSize.height)
            host.frame = NSRect(origin: .zero, size: size)
            let window = NSWindow(
                contentRect: NSRect(origin: NSPoint(x: -10_000, y: -10_000), size: size),
                styleMask: [.borderless], backing: .buffered, defer: false)
            window.isReleasedWhenClosed = false
            window.contentView = host
            defer { window.close() }
            host.layoutSubtreeIfNeeded()
            guard let bitmap = NSBitmapImageRep(
                bitmapDataPlanes: nil, pixelsWide: Int(size.width * 2), pixelsHigh: Int(size.height * 2),
                bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0) else {
                Issue.record("Could not capture hosted agent surface", sourceLocation: sourceLocation)
                return
            }
            bitmap.size = size
            host.cacheDisplay(in: host.bounds, to: bitmap)
            guard let image = bitmap.cgImage else {
                Issue.record("Hosted agent surface did not produce an image", sourceLocation: sourceLocation)
                return
            }
            assertMacSnapshot(
                Image(decorative: image, scale: CGFloat(image.width) / width).frame(width: width, height: size.height),
                named: name, scheme: scheme, width: width, sourceLocation: sourceLocation)
        }

        /// The real All runs view has a model seam, but its rows still call Date() directly.
        /// Only their relative timestamps follow a captured wall clock (4 min / 2 days);
        /// the store clock and every component fixture remain fixed. This is not a frozen scene clock.
        private func runsModel() async -> (BrainBuddyModel, TemporaryFolder) {
            let folder = TemporaryFolder()
            let fixedNow = Self.now
            let names = ["Compare van hire prices", "Find local van firms", "Check opening hours", "Draft the booking email", "Check insurance terms"]
            let labels = ["Needs you", "Running", "Queued", "Agent reported complete", "Stopped reporting"]
            let remote = SnapshotRunsRemote(labels: labels)
            var tasks: [TaskID: TaskRecord] = [:]
            for index in names.indices {
                let id = TaskID("step_\(index)")
                tasks[id] = TaskRecord(
                    id: id, serverID: "task_\(index)", title: names[index], state: .next,
                    orderKey: index, createdAt: Self.now, updatedAt: Self.now)
            }
            let workspace = Workspace(store: InMemoryDocumentStore(document: StoreDocument(
                generation: 1, base: GTDState(tasks: tasks), account: AccountFixtures.account())), sync: nil)
            await workspace.load()
            let model = BrainBuddyModel(
                workspace: workspace, localStateStore: MacLocalStateStore(directory: folder.url), now: { fixedNow },
                agentAvailabilityRemote: { _ in FakeAvailabilityRemote() }, agentRunsRemote: remote)
            await model.refreshAgents()
            #expect(model.listedRuns.count == 5)
            #expect(model.agentRuns.sections.map(\.group) == [.needsYou, .running, .queued, .toReview, .lostContact])
            return (model, folder)
        }

        private struct SnapshotRunsRemote: AgentRunsRemote {
            let labels: [String]
            private let wallClock = Date()

            func agentRunSummaries(taskIDs: [String]) async throws(APIError) -> [String: AgentRunSummaryDTO] {
                var result: [String: AgentRunSummaryDTO] = [:]
                for (index, label) in labels.enumerated() {
                    let task = "task_\(index)"
                    let json = #"{"id":"run_\#(index)","task_id":"\#(task)","agent_name":"\#(index == 1 ? "Claude" : "Hermes")","primary_state_label":"\#(label)","needs_user":false,"stopped_reporting":false,"last_contact_at":null,"guarantee_tier":"guaranteed","cancel_outcome":"none","agent_task_missing":false}"#
                    result[task] = try! BrainBuddyAPI.makeDecoder().decode(AgentRunSummaryDTO.self, from: Data(json.utf8))
                }
                return result
            }

            func agentRun(id: String) async throws(APIError) -> AgentRunDTO {
                let index = Int(id.dropFirst(4))!
                let label = labels[index]
                let created = wallClock.addingTimeInterval(-240).formatted(.iso8601)
                let contact = wallClock.addingTimeInterval(index == 4 ? -172_800 : 0).formatted(.iso8601)
                let json = #"""
                    {"id":"\#(id)","task_id":"task_\#(index)","connection_id":"agent_\#(index)","agent_name":"\#(index == 1 ? "Claude" : "Hermes")",
                    "primary_state_label":"\#(label)","needs_user":false,"stopped_reporting":false,"connection_disconnected":false,
                    "reply_pending":false,"cancel_requested":false,"progress_text":null,"question_text":"asks about card holds",
                    "result_text":null,"result_link":null,"result_link_interactive":false,"failure_reason":null,"content_expired":false,
                    "content_expires_at":"2099-01-01T00:00:00Z","last_contact_at":"\#(contact)","observation_interval_seconds":60,
                    "capabilities":{"reply":true,"cancel":true},"guarantee_tier":"guaranteed","exchange_state":"open","cancel_outcome":"none",
                    "result_availability":null,"events":[],"commands":[],"created_at":"\#(created)","revision":1}
                    """#
                return try! BrainBuddyAPI.makeDecoder().decode(AgentRunDTO.self, from: Data(json.utf8))
            }
        }

        @Test("030_FR_007 030_SC_009 G-02.01 shipped All runs canvas", arguments: Appearance.allCases)
        func allRuns(appearance: Appearance) async {
            let (model, folder) = await runsModel()
            withExtendedLifetime(folder) {
                assertHostedSnapshot(
                    AgentRunsCanvas(model: model, filter: .all, selectedTaskID: nil, onSelect: { _ in })
                        .frame(width: 1160, height: 560),
                    named: "mac-agents-all-runs-\(appearance.rawValue)", scheme: appearance.scheme, width: 1160, height: 560)
            }
        }

        @Test("030_FR_004 030_SC_009 G-01.03 shipped sidebar component composition", arguments: Appearance.allCases)
        func sidebarComponents(appearance: Appearance) {
            let view = VStack(alignment: .leading, spacing: 0) {
                MacSidebarBrand()
                MacSidebarSectionHeader(title: AgentsCopy.sidebar)
                MacSidebarRowLabel(title: AgentsCopy.allRuns, leading: .icon(.agentRun), trailing: "5", selected: true)
                MacSidebarRowLabel(title: "Hermes", leading: .icon(.agentRun), trailing: "1", selected: false, attention: true)
                MacSidebarRowLabel(title: "Claude", leading: .icon(.agentRun), trailing: "1", selected: false)
                MacSidebarRowLabel(title: "Home server", leading: .icon(.agentRun), trailing: "Stale", selected: false)
            }
            .padding(10).background(CarryOnColorStyle.coBgGround)
            assertMacSnapshot(view, named: "mac-agents-sidebar-components-\(appearance.rawValue)", scheme: appearance.scheme, width: 340)
        }

        @Test("030_FR_009 030_SC_009 G-03.01 shipped Waiting for component composition", arguments: Appearance.allCases)
        func waitingComponents(appearance: Appearance) {
            let titles = ["Compare van hire prices", "Find local van firms", "Draft the booking email", "Check insurance terms"]
            let states: [AgentPrimaryState] = [.needsYou, .running, .agentReportedComplete, .stoppedReporting]
            let view = VStack(alignment: .leading, spacing: 0) {
                MacListHeaderTitle(title: "Waiting for", caption: AgentsCopy.waitingHeader(people: 2, agents: 4))
                    .padding(.bottom, 20)
                MacListSectionHeader(title: AgentsCopy.waitingAgents, top: 0)
                ForEach(titles.indices, id: \.self) { index in
                    AgentRunRow(item: AgentRunItem(
                        stepTitle: titles[index], taskServerID: "task_\(index)", runID: "run_\(index)", agentName: "Hermes",
                        state: states[index], sentAt: Self.now.addingTimeInterval(-240),
                        lastContactAt: Self.now.addingTimeInterval(index == 3 ? -172_800 : 0)),
                        style: .waiting, now: Self.now, selected: false, onSelect: {})
                }
                MacListSectionHeader(title: AgentsCopy.waitingPeople, top: 14)
                ForEach(["Quote for the van", "Confirm Saturday pickup"], id: \.self) { title in
                    MacTaskRowShell {
                        MacBoardIconView(icon: .waitingFor, size: 18).foregroundStyle(CarryOnColorStyle.coMarkOpen)
                    } title: {
                        Text(title).font(MacRowFont.title).foregroundStyle(CarryOnColorStyle.coTextPrimary)
                    } trailing: {
                        Text("Sam").font(MacRowFont.meta).foregroundStyle(CarryOnColorStyle.coTextSecondary)
                    }
                }
            }
            .padding(28).background(CarryOnColorStyle.coBgGround)
            assertMacSnapshot(view, named: "mac-agents-waiting-components-\(appearance.rawValue)", scheme: appearance.scheme, width: 960)
        }

        @Test("030_FR_029 030_SC_009 Settings Agents details render in both appearances", arguments: Appearance.allCases)
        func loadedDetails(appearance: Appearance) async {
            let controller = await makeController()
            assertHostedSnapshot(
                manager(controller), named: "mac-agents-settings-ready-\(appearance.rawValue)",
                scheme: appearance.scheme, width: 820)
        }

        @Test("030_FR_036 030_SC_009 passwordless Settings Agents render read-only in both appearances", arguments: Appearance.allCases)
        func passwordlessDetails(appearance: Appearance) async {
            let controller = await makeController(password: false)
            assertHostedSnapshot(
                manager(controller), named: "mac-agents-settings-passwordless-\(appearance.rawValue)",
                scheme: appearance.scheme, width: 820)
        }

        @Test("030_FR_031 030_SC_009 empty Add agent sheet renders in both appearances", arguments: Appearance.allCases)
        func addAgent(appearance: Appearance) async {
            let controller = await makeController()
            let editor = AgentConnectionEditor(mode: .add, model: controller.model)
            assertHostedSnapshot(
                AgentEditorSheet(editor: editor, onClose: {}), named: "mac-agents-add-empty-\(appearance.rawValue)",
                scheme: appearance.scheme, width: 440)
        }
    }
#endif
