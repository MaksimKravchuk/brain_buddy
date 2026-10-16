import BrainBuddyDesign
import BrainBuddyMacCore
import SwiftUI

/// F-03 (029-FR-011, 029-FR-031): the next-step card with the label "Now" (no project is created)
/// and the one tip under it. Focus starts on "Got it", which Return or Space presses; the tip is
/// announced once, politely. The card opens the step in the inspector, where Done and Not now are.
struct LandingTip: View {
    let step: String?
    let tip: String
    let onOpenStep: () -> Void
    let onDismiss: () -> Void
    @FocusState private var gotItFocused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let step {
                Button(action: onOpenStep) {
                    CarryOnNextStepCard(project: FirstRunCopy.nowLabel, step: step)
                }
                .buttonStyle(.plain)
            }
            VStack(alignment: .leading, spacing: 12) {
                Text(tip)
                    .carryOnFont(CarryOnTypeScale.body)
                    .foregroundStyle(.coTextPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                Button(FirstRunCopy.gotIt, action: onDismiss)
                    .buttonStyle(.carryOnSecondary)
                    .keyboardShortcut(.defaultAction)
                    .focused($gotItFocused)
            }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(CarryOnColorStyle.coSurfaceCard, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(CarryOnColorStyle.coControlQuiet, lineWidth: 1))
        }
        .task { gotItFocused = true }
        .onAppear { AccessibilityNotification.Announcement(tip).post() }
    }
}
