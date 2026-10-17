#if canImport(SwiftUI) && os(macOS)
    import BrainBuddyDesign
    import BrainBuddyDesignTestSupport
    import SwiftUI
    import Testing

    @testable import BrainBuddyMac
    @testable import BrainBuddyMacCore

    @Suite("Mac first-run landing tip snapshots")
    @MainActor
    struct FirstRunLandingTipSnapshotTests {
        enum Appearance: String, CaseIterable, Sendable {
            case light, dark

            var scheme: ColorScheme { self == .dark ? .dark : .light }
        }

        private func tipRow() -> some View {
            LandingTip(
                step: nil,
                tip: FirstRunCopy.landingTip(hotkeyAvailable: true),
                onOpenStep: {},
                onDismiss: {}
            )
            .padding(20)
            .background(CarryOnColorStyle.coBgGround)
        }

        @Test("029-FR-011 M04 landing tip is a quiet stone row", arguments: Appearance.allCases)
        func landingTip(appearance: Appearance) {
            assertMacSnapshot(
                tipRow(),
                named: "mac-first-run-landing-tip-\(appearance.rawValue)",
                scheme: appearance.scheme,
                width: 1030
            )
        }
    }
#endif
