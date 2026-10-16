import BrainBuddyDesign
import SwiftUI

/// Board 04: the one tip under the first step on Next actions, shown once. "Got it" dismisses
/// it for good. The bar it points at is the capture accessory above the tab bar.
struct LandingTip: View {
    private typealias Layout = CarryOnLayout.LandingTip

    /// One line of "Got it" as the board sets it.
    private static let actionLineHeight = CGFloat(CarryOnTypeScale.bodyStrong.iosSize * CarryOnTypeScale.bodyStrong.lineHeight)

    let dismiss: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: Layout.actionGap) {
            Text("This is your next step. When it is done, tap Done. Anything else on your mind goes in the bar below.")
                .carryOnText(CarryOnTypeScale.body)
                .foregroundStyle(.coTextPrimary)
                .fixedSize(horizontal: false, vertical: true)
            Button("Got it", action: dismiss)
                .buttonStyle(.plain)
                .carryOnText(CarryOnTypeScale.bodyStrong)
                .foregroundStyle(.coTextPrimary)
                // The board draws a text line; the tap target still reaches 44 pt.
                .contentShape(Rectangle().inset(by: -max(0, BBMetrics.hitTarget - Self.actionLineHeight) / 2))
                .accessibilityHint("Hides this tip.")
        }
        .padding(.vertical, Layout.paddingY)
        .padding(.horizontal, Layout.paddingX)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.coControlQuiet, in: RoundedRectangle(cornerRadius: Layout.radius))
    }
}
