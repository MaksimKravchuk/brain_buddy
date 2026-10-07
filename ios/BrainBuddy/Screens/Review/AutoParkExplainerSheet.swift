import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// M-26 (spec 020, FR-051): the one-time explainer shown before anything else
/// at the first app open after the weekly review is switched on. "Got it" or
/// Close records it as seen through `Workspace.acknowledgeExplainer()` (with
/// the device's zone; queued when offline; on this device only without an
/// account), which starts the 14-day grace for tasks already in Next
/// (FR-016). An app kill while it shows records nothing, so it shows again.
/// "Change the number of days" opens the 7/14/21/28 choice inline; "Got it"
/// saves it too. The body scrolls at every text size, and the actions follow
/// it at accessibility sizes so "Got it" stays reachable.
struct AutoParkExplainerSheet: View {
    @Environment(Workspace.self) private var workspace
    @Environment(\.dismiss) private var dismiss
    @State private var threshold: Int?
    @State private var choosesDays = false
    @State private var problem: String?

    init() {}

    var body: some View {
        let stored = workspace.state.review.settings.thresholdDays
        NavigationStack {
            AutoParkExplainerContent(
                threshold: threshold ?? stored,
                graceUntil: ReviewCopy.day(
                    workspace.reviewNow.addingTimeInterval(FormulationRule.activationGrace), in: .current
                ),
                choosesDays: choosesDays, isOffline: isOffline, problem: problem,
                onChooseThreshold: { threshold = $0 },
                onChangeDays: { choosesDays = true },
                onGotIt: acknowledge
            )
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    // Close does the same as "Got it" (design M-26).
                    Button("Close", action: acknowledge)
                }
            }
        }
        .presentationDetents([.large])
        // Only "Got it" and Close record it; nothing dismisses it by accident.
        .interactiveDismissDisabled()
    }

    private var isOffline: Bool {
        if case .offline = workspace.syncStatus { return true }
        return false
    }

    private func acknowledge() {
        do {
            try workspace.acknowledgeExplainer()
        } catch {
            problem = error.message
            return
        }
        if let threshold, threshold != workspace.state.review.settings.thresholdDays {
            do {
                try workspace.updateReviewSettings(ReviewSettingsChange(thresholdDays: threshold))
            } catch {
                // The explainer is recorded; the threshold can be set in Settings.
            }
        }
        dismiss()
    }
}

/// The explainer's content for given values (every state has a preview).
struct AutoParkExplainerContent: View {
    let threshold: Int
    /// "Fri 23 Oct": nothing already in Next moves before it (FR-016).
    let graceUntil: String
    let choosesDays: Bool
    let isOffline: Bool
    let problem: String?
    let onChooseThreshold: (Int) -> Void
    let onChangeDays: () -> Void
    let onGotIt: () -> Void

    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    /// VoiceOver starts on the heading: the sheet appears without a tap.
    @AccessibilityFocusState private var isHeadingFocused: Bool

    private static let thresholds = OwnerClockSettings.allowedThresholds.sorted()

    init(
        threshold: Int, graceUntil: String, choosesDays: Bool, isOffline: Bool, problem: String?,
        onChooseThreshold: @escaping (Int) -> Void, onChangeDays: @escaping () -> Void, onGotIt: @escaping () -> Void
    ) {
        self.threshold = threshold
        self.graceUntil = graceUntil
        self.choosesDays = choosesDays
        self.isOffline = isOffline
        self.problem = problem
        self.onChooseThreshold = onChooseThreshold
        self.onChangeDays = onChangeDays
        self.onGotIt = onGotIt
    }

    var body: some View {
        let actionsScroll = dynamicTypeSize.isAccessibilitySize
        ScrollView {
            VStack(alignment: .leading, spacing: BBSpacing.s5) {
                Text(ReviewCopy.explainerTitle)
                    .font(BBFont.display)
                    .foregroundStyle(BBColor.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityAddTraits(.isHeader)
                    .accessibilityFocused($isHeadingFocused)
                point(
                    "When a task stalls", systemImage: "questionmark.circle",
                    text: choosesDays
                        ? ReviewCopy.explainerRule(thresholdDays: threshold)
                        : ReviewCopy.explainerRule(thresholdDays: threshold) + " That's feedback on the wording, not on you."
                )
                if choosesDays {
                    thresholdChoice
                } else {
                    point("If it stays undecided", systemImage: "archivebox", text: ReviewCopy.explainerPark)
                    point("Your tasks get time", systemImage: "calendar", text: ReviewCopy.explainerGrace(until: graceUntil))
                }
                if isOffline {
                    Label("Offline. This is saved on this iPhone and syncs later.", systemImage: "icloud.slash")
                        .font(BBFont.meta)
                        .foregroundStyle(BBColor.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if let problem {
                    InlineProblemText(message: problem)
                }
                if actionsScroll {
                    actions
                }
            }
            .padding(BBSpacing.s4)
        }
        .bbScreenBackground()
        .safeAreaInset(edge: .bottom) {
            if !actionsScroll {
                actions
                    .padding(BBSpacing.s4)
                    .background(.bar)
            }
        }
        .onAppear { isHeadingFocused = true }
    }

    private func point(_ title: String, systemImage: String, text: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: BBSpacing.s3) {
            Image(systemName: systemImage)
                .foregroundStyle(BBColor.brandText)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: BBSpacing.s1) {
                Text(title)
                    .font(BBFont.bodyMedium)
                    .foregroundStyle(BBColor.textPrimary)
                Text(text)
                    .font(BBFont.secondary)
                    .foregroundStyle(BBColor.textSecondary)
            }
            .fixedSize(horizontal: false, vertical: true)
        }
        .accessibilityElement(children: .combine)
    }

    private var thresholdChoice: some View {
        VStack(alignment: .leading, spacing: BBSpacing.s2) {
            Text("Ask for a decision after")
                .font(BBFont.subtitle)
                .foregroundStyle(BBColor.textSecondary)
            VStack(spacing: 0) {
                ForEach(Self.thresholds, id: \.self) { days in
                    Button {
                        onChooseThreshold(days)
                    } label: {
                        HStack {
                            Text("\(days) days")
                                .foregroundStyle(BBColor.textPrimary)
                            Spacer()
                            if days == threshold {
                                Image(systemName: "checkmark")
                                    .foregroundStyle(BBColor.brandText)
                                    .accessibilityHidden(true)
                            }
                        }
                        .padding(.horizontal, BBSpacing.s4)
                        .frame(minHeight: BBMetrics.hitTarget)
                        .contentShape(.rect)
                    }
                    .buttonStyle(.plain)
                    .accessibilityAddTraits(days == threshold ? .isSelected : [])
                }
            }
            .bbCard()
            Text(
                "You can change this any time in Settings. Tasks already in Next still won't move before \(graceUntil)."
            )
            .font(BBFont.meta)
            .foregroundStyle(BBColor.textTertiary)
            .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var actions: some View {
        VStack(spacing: BBSpacing.s2) {
            Button(action: onGotIt) {
                Text(ReviewCopy.gotIt)
                    .frame(maxWidth: .infinity, minHeight: BBMetrics.hitTarget)
            }
            .buttonStyle(.borderedProminent)
            if !choosesDays {
                Button(action: onChangeDays) {
                    Text(ReviewCopy.changeDays)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: .infinity, minHeight: BBMetrics.hitTarget)
                }
            }
        }
    }
}

// MARK: - Previews (every M-26 state)

@MainActor
private func explainerPreview(choosesDays: Bool = false, threshold: Int = 14, isOffline: Bool = false) -> some View {
    NavigationStack {
        AutoParkExplainerContent(
            threshold: threshold, graceUntil: "Fri 23 Oct", choosesDays: choosesDays, isOffline: isOffline, problem: nil,
            onChooseThreshold: { _ in }, onChangeDays: {}, onGotIt: {}
        )
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("Close") {}
            }
        }
    }
}

#Preview("M-26 default") {
    explainerPreview()
}

#Preview("M-26 change the number of days") {
    explainerPreview(choosesDays: true, threshold: 7)
}

#Preview("M-26 offline") {
    explainerPreview(isOffline: true)
}

#Preview("M-26 accessibility size") {
    explainerPreview()
        .environment(\.dynamicTypeSize, .accessibility5)
}
