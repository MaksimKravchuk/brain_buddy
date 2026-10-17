#if canImport(SwiftUI) && os(macOS)
    import AppKit
    import BrainBuddyCore
    import BrainBuddyPersistence
    import BrainBuddyWorkspace
    import BrainBuddyAgents
    import BrainBuddyAPI
    import BrainBuddyDesign
    import Foundation
    import SwiftUI
    import Testing

    @testable import BrainBuddyMac
    @testable import BrainBuddyMacCore
    /// The shipped M29 manager, including its Settings scroll viewport and read-only notice.
    @Suite("Mac agent manager snapshots", .serialized)
    @MainActor
    struct AgentsManagerSnapshotTests {
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
            #expect(AgentDetailsView.contact(Self.now, now: Self.now) == "Today \(Self.now.formatted(.dateTime.hour().minute()))")
            return controller
        }

        private func manager(_ controller: AgentsTabController) -> some View {
            ScrollView { AgentsManagerView(controller: controller, accountURL: URL(string: "https://app.brainbuddy.example/settings/account"), onOpen: { _ in }, now: Self.now) }
                .frame(width: 820, height: MacSettingsView.idealHeight, alignment: .topLeading)
                .background(CarryOnColorStyle.coBgGround)
        }

        /// ImageRenderer omits ScrollView document views and native text fields. Host the real
        /// view offscreen, then use the shared assertion for the resulting unmodified bitmap.
        /// Native text follows the window's backing scale; Foundation dates use the host's
        /// hour cycle. Keep explicit observed host profiles, never a best-matching fallback.
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
            let scale = window.backingScaleFactor
            guard scale == 1 || scale == 2 else {
                Issue.record("Unsupported native snapshot backing scale: \(scale)", sourceLocation: sourceLocation)
                return
            }
            let clock: String
            switch Locale.current.hourCycle {
            case .zeroToEleven, .oneToTwelve: clock = "12h"
            case .zeroToTwentyThree, .oneToTwentyFour: clock = "24h"
            @unknown default:
                Issue.record("Unsupported native snapshot hour cycle", sourceLocation: sourceLocation)
                return
            }
            let profile = "native\(Int(scale))x-\(clock)"
            print("Agent snapshot \(name): \(profile), locale \(Locale.current.identifier)")
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
                named: "\(name)-\(profile)", scheme: scheme, width: width, sourceLocation: sourceLocation)
        }

        @Test("030_FR_029 030_SC_009 M29 manager fills its Settings viewport", arguments: Appearance.allCases)
        func loaded(appearance: Appearance) async {
            let controller = await makeController()
            assertHostedSnapshot(manager(controller), named: "mac-agents-manager-loaded-\(appearance.rawValue)",
                scheme: appearance.scheme, width: 820, height: MacSettingsView.idealHeight)
        }

        @Test("030_FR_036 030_SC_009 M29 passwordless manager preserves its read-only notice", arguments: Appearance.allCases)
        func passwordless(appearance: Appearance) async {
            let controller = await makeController(password: false)
            assertHostedSnapshot(manager(controller), named: "mac-agents-manager-passwordless-\(appearance.rawValue)",
                scheme: appearance.scheme, width: 820, height: MacSettingsView.idealHeight)
        }
    }
#endif
