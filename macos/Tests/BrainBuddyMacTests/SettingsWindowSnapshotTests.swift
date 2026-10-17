#if canImport(SwiftUI) && os(macOS)
    import AppKit
    import BrainBuddyDesign
    import BrainBuddyMacCore
    import Observation
    import SwiftUI
    import Testing

    @testable import BrainBuddyMac

    /// Host the production Scene, not a copy of the tab HStack: native window sizing and toolbar
    /// backgrounds are part of S-01. The fake launch stays unopened; tab-body states have their
    /// own coverage. The test-owned window is transparent before display, then kept offscreen.
    @Suite("Mac Settings native window", .serialized)
    @MainActor
    struct SettingsWindowSnapshotTests {
        @Test("028_FR_001 028_FR_002 028_SC_007 native Settings opens at board size with its tab chrome")
        func nativeWindow() async throws {
            CarryOnFonts.register()
            let folder = TemporaryFolder()
            let launch = MacLaunch(environment: MacLaunchEnvironment(
                configuration: MacHostConfiguration(directory: folder.url, isDryRun: true),
                tokenStore: SpyTokenStore(), transport: CountingTransport(), now: TestClock().provider,
                log: CapturingMacLog()))
            let application = NSApplication.shared
            let priorWindows = Set(application.windows.map(\.windowNumber))
            let appearance = SettingsTestAppearance()
            let representation = NSHostingSceneRepresentation {
                MacSettingsScene { SettingsTestContent(launch: launch, appearance: appearance) }
            }
            application.addSceneRepresentation(representation)
            representation.environment.openSettings()
            let window = try #require(application.windows.first { !priorWindows.contains($0.windowNumber) })
            window.orderOut(nil)
            window.setFrameOrigin(NSPoint(x: -10_000, y: -10_000))
            defer { window.close() }
            #expect(window.alphaValue == 0, "The native scene must be hidden before its first display")
            for _ in 0..<30 { await Task.yield() }
            let frame = try #require(window.contentView?.superview)
            frame.layoutSubtreeIfNeeded()
            #expect(window.frame.width == 820 && window.frame.height == 620)
            #expect(window.contentLayoutRect.width == 820)
            #expect(window.contentMinSize.width == 820)
            let chromeHeight = window.frame.height - window.contentLayoutRect.height
            #expect(window.contentMinSize.height == 420 + chromeHeight, "Keep the existing body minimum plus native chrome")
            let scale = window.backingScaleFactor
            #expect(scale == 1 || scale == 2)
            let profile = "native\(Int(scale))x"
            print("Settings native window: \(window.frame.size), layout \(window.contentLayoutRect.size), minimum \(window.contentMinSize), \(profile)")
            for dark in [false, true] {
                appearance.scheme = dark ? .dark : .light
                window.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
                for _ in 0..<30 { await Task.yield() }
                frame.layoutSubtreeIfNeeded()
                let bitmap = try #require(NSBitmapImageRep(
                    bitmapDataPlanes: nil, pixelsWide: Int(frame.bounds.width * 2), pixelsHigh: Int(frame.bounds.height * 2),
                    bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                    colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0))
                bitmap.size = frame.bounds.size
                frame.cacheDisplay(in: frame.bounds, to: bitmap)
                let image = try #require(bitmap.cgImage)
                let header = try #require(image.cropping(to: CGRect(
                    x: 0, y: 0, width: image.width, height: Int(chromeHeight * 2))))
                assertMacSnapshot(
                    Image(decorative: header, scale: 2).frame(width: frame.bounds.width, height: chromeHeight),
                    named: "mac-settings-chrome-\(dark ? "dark" : "light")-\(profile)",
                    scheme: dark ? .dark : .light, width: 820)
            }
        }
    }

    @MainActor @Observable
    private final class SettingsTestAppearance {
        var scheme = ColorScheme.light
    }

    private struct SettingsTestContent: View {
        let launch: MacLaunch
        let appearance: SettingsTestAppearance
        var body: some View {
            MacSettingsView(launch: launch, selection: .constant(.agents))
                .environment(\.colorScheme, appearance.scheme)
                .preferredColorScheme(appearance.scheme)
                .toolbarColorScheme(appearance.scheme, for: .windowToolbar)
                .background(SettingsTestWindowGuard())
        }
    }

    /// This guard changes only the test's native window before it can draw. Product scenes keep
    /// the normal visibility and activation behavior; no frame or activation workaround is shipped.
    private struct SettingsTestWindowGuard: NSViewRepresentable {
        final class View: NSView {
            override func viewWillMove(toWindow newWindow: NSWindow?) {
                newWindow?.alphaValue = 0
                newWindow?.animationBehavior = .none
                super.viewWillMove(toWindow: newWindow)
            }
        }
        func makeNSView(context: Context) -> View { View() }
        func updateNSView(_ nsView: View, context: Context) {}
    }
#endif
