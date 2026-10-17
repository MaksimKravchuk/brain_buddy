#if canImport(SwiftUI) && os(macOS)
    import AppKit
    import BrainBuddyDesign
    import BrainBuddyDesignTestSupport
    import SwiftUI
    import Testing

    @testable import BrainBuddyMac

    /// The first-run welcome on the Mac's real native host so AppKit text matches the app.
    @Suite("Mac first-run welcome snapshots", .serialized)
    @MainActor
    struct WelcomeInboxSnapshotTests {
        enum Appearance: String, CaseIterable, Sendable {
            case light, dark

            var scheme: ColorScheme { self == .dark ? .dark : .light }
        }

        @Test("029-FR-003 029-FR-004 029-FR-005 M01 empty welcome matches the board", arguments: Appearance.allCases)
        func emptyWelcome(appearance: Appearance) {
            let content = WelcomeInboxView(
                text: .constant(""), hotkeyAvailable: true, speechAvailable: true, errorText: nil,
                onSubmit: {}, onSkip: {}, onMic: {}
            )
            .environment(\.carryOnPlatform, .mac)
            .environment(\.colorScheme, appearance.scheme)
            .frame(width: 1030, height: 747, alignment: .top)
            .background(CarryOnColorStyle.coBgGround)

            assertHostedSnapshot(content, appearance: appearance, state: "empty")
        }

        @Test("029-FR-006 M02 typed welcome matches the board", arguments: Appearance.allCases)
        func typedWelcome(appearance: Appearance) {
            let content = WelcomeInboxView(
                text: .constant("the garage is a mess and Sam needs the van back"),
                hotkeyAvailable: true, speechAvailable: true, errorText: nil,
                onSubmit: {}, onSkip: {}, onMic: {}
            )
            .environment(\.carryOnPlatform, .mac)
            .environment(\.colorScheme, appearance.scheme)
            .frame(width: 1030, height: 747, alignment: .top)
            .background(CarryOnColorStyle.coBgGround)

            assertHostedSnapshot(content, appearance: appearance, state: "typed")
        }

        private func assertHostedSnapshot(
            _ content: some View, appearance: Appearance, state: String,
            sourceLocation: SourceLocation = #_sourceLocation
        ) {
            let width: CGFloat = 1030
            _ = NSApplication.shared
            let host = NSHostingView(rootView: content)
            host.appearance = NSAppearance(named: appearance == .dark ? .darkAqua : .aqua)
            let size = NSSize(width: width, height: 747)
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
            print("Welcome snapshot \(profile)")
            host.layoutSubtreeIfNeeded()

            guard let bitmap = NSBitmapImageRep(
                bitmapDataPlanes: nil, pixelsWide: Int(width * 2), pixelsHigh: Int(size.height * 2),
                bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0
            ) else {
                Issue.record("Could not capture the hosted welcome surface")
                return
            }
            bitmap.size = size
            host.cacheDisplay(in: host.bounds, to: bitmap)
            guard let cgImage = bitmap.cgImage else {
                Issue.record("Hosted welcome surface did not produce an image")
                return
            }
            let image = Image(decorative: cgImage, scale: 2)
            assertMacSnapshot(
                image.frame(width: width, height: size.height),
                named: "mac-welcome-\(state)-\(appearance.rawValue)-\(profile)",
                scheme: appearance.scheme, width: width, sourceLocation: sourceLocation)
        }
    }
#endif
