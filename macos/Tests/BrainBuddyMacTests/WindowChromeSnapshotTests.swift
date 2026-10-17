#if canImport(SwiftUI) && os(macOS)
import AppKit
import BrainBuddyDesign
import BrainBuddyDesignTestSupport
import BrainBuddyMacCore
import SwiftUI
import Testing

@testable import BrainBuddyMac

/// Native AppKit snapshots cover the shipped List and toolbar faces, including their native insets.
@Suite("Mac board window chrome snapshots", .serialized)
@MainActor
struct WindowChromeSnapshotTests {
    enum Appearance: String, CaseIterable, Sendable {
        case light, dark
        var scheme: ColorScheme { self == .dark ? .dark : .light }
    }

    @Test("029-FR-012 M01 compact native sidebar matches the board", arguments: Appearance.allCases)
    func firstRunSidebar(appearance: Appearance) async {
        await sidebar(firstRun: true, appearance: appearance)
    }

    @Test("021-FR-009 M07 normal sidebar keeps board order and active routes", arguments: Appearance.allCases)
    func standardSidebar(appearance: Appearance) async {
        await sidebar(firstRun: false, appearance: appearance)
    }

    @Test("021-FR-009 DSMac nonempty Tags stays reachable in the sidebar", arguments: Appearance.allCases)
    func tagsSidebar(appearance: Appearance) async {
        await sidebar(firstRun: false, hasTags: true, appearance: appearance)
    }

    @Test("Native main-window columns fit the initial and board viewports", arguments: [960.0, 1280.0])
    func nativeWindowLayout(width: Double) async throws {
        _ = NSApplication.shared
        let height = width == 960 ? 640.0 : 800.0
        let folder = TemporaryFolder()
        let host = WorkspaceHost(configuration: MacHostConfiguration(directory: folder.url, isDryRun: true), tokenStore: SpyTokenStore())
        await host.workspace.load()
        let model = BrainBuddyModel(workspace: host.workspace, localStateStore: host.localState)
        model.decideFirstRun()
        await model.prepareVisibleQueries()
        let content = NSHostingView(rootView: WorkspaceView(model: model, sync: MacSyncController(host: host))
            .frame(minWidth: 720, minHeight: 480))
        let window = NSWindow(contentRect: NSRect(x: -10_000, y: -10_000, width: width, height: height),
                              styleMask: [.titled, .closable, .resizable, .fullSizeContentView], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        defer { window.close() }
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.toolbarStyle = .unified
        let toolbar = NSToolbar(identifier: "NativeChromeRegression")
        toolbar.insertItem(withItemIdentifier: .flexibleSpace, at: 0)
        window.toolbar = toolbar
        window.contentView = content
        window.setFrame(NSRect(x: -10_000, y: -10_000, width: width, height: height), display: false)
        try await Task.sleep(for: .milliseconds(100))
        content.layoutSubtreeIfNeeded()
        func firstSplit(in view: NSView) -> NSSplitView? {
            if let split = view as? NSSplitView { return split }
            return view.subviews.lazy.compactMap { firstSplit(in: $0) }.first
        }
        let split = try #require(firstSplit(in: content))
        let bounds = split.convert(split.bounds, to: content)
        #expect(abs(bounds.minX) < 0.5)
        #expect(abs(bounds.width - width) < 0.5)
        #expect(abs(bounds.minY) < 0.5)
        #expect(abs(bounds.height - height) < 0.5)
        let controller = try #require(split.delegate as? NSSplitViewController)
        let sidebar = try #require(controller.splitViewItems.first { $0.behavior == .sidebar })
        #expect(abs(sidebar.minimumThickness - CarryOnLayout.MacWindow.sidebarColumnWidth) < 0.01)
        #expect(sidebar.maximumThickness == 400)
        #expect(abs(sidebar.viewController.view.frame.width - CarryOnLayout.MacWindow.sidebarColumnWidth) < 0.5)
        let detail = try #require(controller.splitViewItems.first { $0.behavior == .default })
        #expect(detail.minimumThickness >= 560)
    }

    private func sidebar(firstRun: Bool, hasTags: Bool = false, appearance: Appearance) async {
        let folder = TemporaryFolder()
        let host = WorkspaceHost(
            configuration: MacHostConfiguration(directory: folder.url, isDryRun: true),
            tokenStore: SpyTokenStore(), makeID: SequentialIDs(namespace: 9).provider)
        await host.workspace.load()
        let model = BrainBuddyModel(workspace: host.workspace, localStateStore: host.localState)
        model.decideFirstRun()
        if !firstRun { model.firstRun.skip() }
        if hasTags { _ = await model.createTag("calls"); _ = await model.createTag("errands") }
        await model.prepareVisibleQueries()
        let sync = MacSyncController(host: host)
        let sidebar = WorkspaceView(model: model, sync: sync).sidebar
        let name = firstRun ? "mac-window-first-run-sidebar" : hasTags ? "mac-window-tags-sidebar" : "mac-window-sidebar"
        snapshot(sidebar, name: name, appearance: appearance, width: 240, height: 800)
    }

    @Test("021-FR-009 M07 native toolbar preserves its three visible actions and app tint", arguments: Appearance.allCases)
    func toolbar(appearance: Appearance) async throws {
        _ = NSApplication.shared
        let folder = TemporaryFolder()
        let host = WorkspaceHost(configuration: MacHostConfiguration(directory: folder.url, isDryRun: true), tokenStore: SpyTokenStore())
        await host.workspace.load()
        let model = BrainBuddyModel(workspace: host.workspace, localStateStore: host.localState)
        model.decideFirstRun()
        model.firstRun.skip()
        await model.prepareVisibleQueries()
        let content = NSHostingView(rootView: WorkspaceView(model: model, sync: MacSyncController(host: host))
            .tint(CarryOnColorStyle.coTextPrimary)
            .environment(\.carryOnPlatform, .mac)
            .environment(\.colorScheme, appearance.scheme))
        content.sceneBridgingOptions = .all
        let window = NSWindow(contentRect: NSRect(x: -10_000, y: -10_000, width: 1280, height: 800),
                              styleMask: [.titled, .closable, .resizable, .fullSizeContentView], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        defer { window.close() }
        window.appearance = NSAppearance(named: appearance == .dark ? .darkAqua : .aqua)
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.toolbarStyle = .unified
        window.contentView = content
        try await Task.sleep(for: .milliseconds(100))
        let toolbar = try #require(window.toolbar)
        #expect(toolbar.items.count == 4)
        #expect(toolbar.items.first?.itemIdentifier == .flexibleSpace)
        let frame = try #require(content.superview)
        frame.layoutSubtreeIfNeeded()
        var actions = NSRect.null
        for item in toolbar.items.dropFirst() {
            let view = try #require(item.view)
            actions = actions.union(view.convert(view.bounds, to: frame))
        }
        #expect(actions.width <= 320)
        #expect(frame.bounds.maxX - actions.maxX < 32)
        // Native assertions cover placement; live app captures cover compositor glass.
        snapshot(
            HStack(spacing: CarryOnSpace.xs) {
                MacWindowToolbarButton(command: .newStep) {}
                MacWindowToolbarButton(command: .voice) {}
                MacWindowToolbarButton(command: .quickOpen) {}
            }.padding(CarryOnSpace.md).tint(CarryOnColorStyle.coTextPrimary),
            name: "mac-window-toolbar", appearance: appearance, width: 320, height: 64)
    }

    private func snapshot(
        _ content: some View, name: String, appearance: Appearance, width: CGFloat, height: CGFloat,
        sourceLocation: SourceLocation = #_sourceLocation
    ) {
        _ = NSApplication.shared
        let host = NSHostingView(rootView: content
            .environment(\.carryOnPlatform, .mac)
            .environment(\.colorScheme, appearance.scheme)
            .frame(width: width, height: height)
            .background(CarryOnColorStyle.coBgGround))
        host.appearance = NSAppearance(named: appearance == .dark ? .darkAqua : .aqua)
        let size = NSSize(width: width, height: height)
        let window = NSWindow(
            contentRect: NSRect(origin: NSPoint(x: -10_000, y: -10_000), size: size),
            styleMask: [.borderless], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.contentView = host
        defer { window.close() }
        host.layoutSubtreeIfNeeded()
        assertNativeView(host, window: window, name: name, appearance: appearance,
                         rect: host.bounds, sourceLocation: sourceLocation)
    }

    private func assertNativeView(
        _ view: NSView, window: NSWindow, name: String, appearance: Appearance, rect: NSRect,
        sourceLocation: SourceLocation = #_sourceLocation
    ) {
        let width = rect.width
        let height = rect.height
        let scale = window.backingScaleFactor
        guard scale == 1 || scale == 2 else {
            Issue.record("Unsupported native snapshot backing scale: \(scale)", sourceLocation: sourceLocation)
            return
        }
        let profile = "native\(Int(scale))x"
        guard let bitmap = NSBitmapImageRep(
            bitmapDataPlanes: nil, pixelsWide: Int(width * 2), pixelsHigh: Int(height * 2),
            bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
            colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0
        ) else { Issue.record("Could not capture native window chrome"); return }
        bitmap.size = rect.size
        view.cacheDisplay(in: rect, to: bitmap)
        guard let cgImage = bitmap.cgImage else { Issue.record("No native chrome image"); return }
        assertMacSnapshot(
            Image(decorative: cgImage, scale: 2).frame(width: width, height: height),
            named: "\(name)-\(appearance.rawValue)-\(profile)", scheme: appearance.scheme, width: width,
            sourceLocation: sourceLocation)
    }
}
#endif
