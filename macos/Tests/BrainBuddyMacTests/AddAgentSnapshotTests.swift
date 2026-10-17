#if canImport(SwiftUI) && os(macOS)
    import AppKit
    import BrainBuddyAgents
    import BrainBuddyAPI
    import BrainBuddyDesign
    import Foundation
    import SwiftUI
    import Testing

    @testable import BrainBuddyMac
    @testable import BrainBuddyMacCore

    /// M30 uses the real editor sheet, including native text and secure fields.
    @Suite("Mac Add agent snapshots", .serialized)
    @MainActor
    struct AddAgentSnapshotTests {
        enum Appearance: String, CaseIterable, Sendable {
            case light, dark
            var scheme: ColorScheme { self == .dark ? .dark : .light }
        }

        private func editor(filled: Bool) async -> AgentConnectionEditor {
            let availability = AgentAvailability(account: AccountFixtures.account(), remote: { _ in FakeAvailabilityRemote() })
            await availability.refresh()
            let remote = FakeAgentRemote(list: .success([]))
            let model = AgentSettingsModel(account: AccountFixtures.account(), availability: availability, remote: { _ in remote })
            await model.reload()
            let editor = AgentConnectionEditor(mode: .add, model: model)
            if filled {
                editor.name = "Hermes"
                editor.address = "https://hermes.myhost.dev"
                editor.secret = "synthetic-credential"
            }
            #expect(editor.needsPassword)
            #expect(editor.canConfirmAdd == filled && !editor.canSubmit)
            return editor
        }

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
            let profile = "native\(Int(scale))x"
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

        enum Stage: String, CaseIterable, Sendable { case empty, filled, confirmation }

        @Test("030_FR_031 030_SC_009 M30 form and required proof render in both appearances", arguments: Appearance.allCases, Stage.allCases)
        func sheet(appearance: Appearance, stage: Stage) async {
            let editor = await editor(filled: stage != .empty)
            let flow = AgentEditorSheetFlow()
            if stage == .confirmation {
                await flow.performPrimary(editor: editor)
                editor.password = "synthetic-password"
                #expect(flow.confirmingAdd && editor.canSubmit)
            }
            assertHostedSnapshot(AgentEditorSheet(editor: editor, onClose: {}, flow: flow),
                named: "mac-agent-add-\(stage.rawValue)-\(appearance.rawValue)",
                scheme: appearance.scheme, width: CarryOnLayout.MacAgentAdd.width)
        }
    }
#endif
