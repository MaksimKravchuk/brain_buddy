#if canImport(SwiftUI) && os(macOS)
import AppKit
import BrainBuddyAgents
import BrainBuddyDesign
import SwiftUI
import Testing

@testable import BrainBuddyMac

@Suite("030 All runs canvas layout", .serialized)
@MainActor
struct AgentRunsCanvasTests {
    enum Appearance: String, CaseIterable, Sendable {
        case light, dark
        var scheme: ColorScheme { self == .dark ? .dark : .light }
    }

    @Test("030-FR-007 empty All runs uses the available canvas width", arguments: [560.0, 1032.0])
    func emptyCanvasWidth(width: Double) async throws {
        let (window, content) = await makeCanvas(width: width, appearance: .light)
        defer { window.close() }
        try await Task.sleep(for: .milliseconds(100))
        content.layoutSubtreeIfNeeded()
        func scrollView(in view: NSView) -> NSScrollView? {
            (view as? NSScrollView) ?? view.subviews.lazy.compactMap { scrollView(in: $0) }.first
        }
        let scroll = try #require(scrollView(in: content))
        let bounds = scroll.convert(scroll.bounds, to: content)
        #expect(abs(bounds.minX) < 0.5)
        #expect(abs(bounds.width - width) < 0.5)
    }

    @Test("030-FR-007 M22 empty message stays readable across the canvas", arguments: Appearance.allCases)
    func emptySnapshot(appearance: Appearance) async throws {
        let width: CGFloat = 1032
        let (window, content) = await makeCanvas(width: width, appearance: appearance)
        defer { window.close() }
        try await Task.sleep(for: .milliseconds(100))
        content.layoutSubtreeIfNeeded()
        let scale = window.backingScaleFactor
        guard scale == 1 || scale == 2 else {
            Issue.record("Unsupported native snapshot backing scale: \(scale)")
            return
        }
        let bitmap = try #require(NSBitmapImageRep(
            bitmapDataPlanes: nil, pixelsWide: Int(width * 2), pixelsHigh: Int(content.bounds.height * 2),
            bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
            colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0))
        bitmap.size = content.bounds.size
        content.cacheDisplay(in: content.bounds, to: bitmap)
        let image = try #require(bitmap.cgImage)
        assertMacSnapshot(
            Image(decorative: image, scale: 2).frame(width: width, height: content.bounds.height),
            named: "mac-all-runs-empty-\(appearance.rawValue)-native\(Int(scale))x",
            scheme: appearance.scheme, width: width)
    }

    private func makeCanvas(width: CGFloat, appearance: Appearance) async -> (NSWindow, NSView) {
        _ = NSApplication.shared
        let rig = await AgentsSceneTests.Rig.make()
        #expect(rig.model.agentRuns.phase == .loaded)
        let content = NSHostingView(rootView: AgentRunsCanvas(
            model: rig.model, filter: .all, selectedTaskID: nil, onSelect: { _ in }, onOpen: { _ in })
            .environment(\.carryOnPlatform, .mac)
            .environment(\.colorScheme, appearance.scheme)
            .frame(width: width, height: 748))
        let window = NSWindow(contentRect: NSRect(x: -10_000, y: -10_000, width: width, height: 748),
                              styleMask: [.borderless], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.appearance = NSAppearance(named: appearance == .dark ? .darkAqua : .aqua)
        window.contentView = content
        return (window, content)
    }
}
#endif
