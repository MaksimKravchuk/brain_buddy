#if canImport(SwiftUI) && os(macOS)
    import BrainBuddyDesign
    import BrainBuddyDesignTestSupport
    import SwiftUI
    import Testing

    /// The Mac app's snapshot assertion: `assertSnapshot` with the view under the Mac sizes
    /// (`\.carryOnPlatform` = `.mac`), as the app's root scenes set them.
    @MainActor
    func assertMacSnapshot(
        _ view: some View,
        named name: String,
        scheme: ColorScheme,
        width: CGFloat,
        channelTolerance: Int = 3,
        filePath: String = #filePath,
        sourceLocation: SourceLocation = #_sourceLocation
    ) {
        assertSnapshot(
            view.environment(\.carryOnPlatform, .mac),
            named: name, scheme: scheme, width: width, channelTolerance: channelTolerance,
            filePath: filePath, sourceLocation: sourceLocation)
    }
#endif
