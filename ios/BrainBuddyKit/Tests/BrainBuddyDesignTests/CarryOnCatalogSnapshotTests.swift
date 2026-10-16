#if canImport(SwiftUI) && os(macOS)
    import BrainBuddyDesign
    import SwiftUI
    import Testing

    /// Each component section of the catalog against its approved render, at iPhone
    /// and Mac sizes, light and dark. The approved PNGs are compared with the design
    /// boards before they are committed; after that, any change to a component's
    /// pixels fails here.
    @Suite("Carry On component snapshots")
    @MainActor
    struct CarryOnCatalogSnapshotTests {
        enum Appearance: String, CaseIterable, Sendable {
            case light, dark

            var scheme: ColorScheme { self == .dark ? .dark : .light }
        }

        @Test(
            "A catalog section renders as approved",
            arguments: CarryOnCatalog.Section.allCases,
            CarryOnPlatform.allCases.flatMap { platform in Appearance.allCases.map { (platform, $0) } })
        func section(_ section: CarryOnCatalog.Section, variant: (CarryOnPlatform, Appearance)) {
            let (platform, appearance) = variant
            assertSnapshot(
                CarryOnCatalog.view(section).environment(\.carryOnPlatform, platform),
                named: "\(section.rawValue)-\(platform.rawValue)-\(appearance.rawValue)",
                scheme: appearance.scheme,
                width: 390)
        }
    }
#endif
