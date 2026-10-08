import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// M-22 (spec 020, FR-029, FR-033): the ten counts in a fixed order (zero
/// ones dimmed), the next review, the optional "Clear how to start the week?"
/// and Done, which finishes the run. Two columns, one at accessibility text
/// sizes (`ReviewLayout`). A review done without any step shows the same calm
/// screen. Everything is saved on this iPhone and syncs later.
struct SummaryStep: View {
    let context: ReviewStepContext

    init(context: ReviewStepContext) {
        self.context = context
    }

    @Environment(Workspace.self) private var workspace
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @State private var clearStart: ClearStart?

    var body: some View {
        let session = workspace.state.review.sessions[context.sessionID]
        let counts = session?.counts ?? SessionCounts()
        let zone = TimeZone.current
        SummaryContent(
            counts: SessionCounter.allCases.map { SummaryContent.Count(counter: $0, value: counts[$0]) },
            columns: ReviewLayout.summaryColumns(isAccessibilitySize: dynamicTypeSize.isAccessibilitySize),
            showsCalmLine: counts.total == 0 && (session?.steps.values.contains(.finished) ?? false),
            nextReview: workspace.nextReviewReminder().map {
                ReviewCopy.nextReview(day: ReviewCopy.day($0, in: zone), time: ReviewCopy.time($0, in: zone))
            },
            isOffline: isOffline, clearStart: $clearStart, onDone: { context.finish(clearStart) }
        )
    }

    private var isOffline: Bool {
        if case .offline = workspace.syncStatus { return true }
        return false
    }
}

/// The summary for given values (every state has a preview).
struct SummaryContent: View {
    struct Count: Identifiable {
        var counter: SessionCounter
        var value: Int
        var id: SessionCounter { counter }
    }

    let counts: [Count]
    let columns: Int
    let showsCalmLine: Bool
    let nextReview: String?
    let isOffline: Bool
    @Binding var clearStart: ClearStart?
    let onDone: () -> Void

    init(
        counts: [Count], columns: Int, showsCalmLine: Bool, nextReview: String?, isOffline: Bool,
        clearStart: Binding<ClearStart?>, onDone: @escaping () -> Void
    ) {
        self.counts = counts
        self.columns = columns
        self.showsCalmLine = showsCalmLine
        self.nextReview = nextReview
        self.isOffline = isOffline
        _clearStart = clearStart
        self.onDone = onDone
    }

    var body: some View {
        ReviewStepFrame(title: ReviewCopy.reviewDone, primaryTitle: ReviewCopy.done, onPrimary: onDone) {
            if let nextReview {
                Text(nextReview)
                    .font(BBFont.body)
                    .foregroundStyle(BBColor.textSecondary)
            }
            if showsCalmLine {
                Text(ReviewCopy.nothingNeededChanging)
                    .font(BBFont.body)
                    .foregroundStyle(BBColor.textPrimary)
            } else if counts.contains(where: { $0.value > 0 }) {
                LazyVGrid(
                    columns: Array(repeating: GridItem(.flexible(), alignment: .leading), count: columns),
                    alignment: .leading, spacing: BBSpacing.s3
                ) {
                    ForEach(counts) { count in
                        HStack(alignment: .firstTextBaseline) {
                            Text(ReviewCopy.counterLabel(count.counter))
                                .font(BBFont.secondary)
                            Spacer(minLength: BBSpacing.s2)
                            Text("\(count.value)")
                                .font(BBFont.bodyMedium.monospacedDigit())
                        }
                        .foregroundStyle(count.value == 0 ? BBColor.textTertiary : BBColor.textPrimary)
                        .accessibilityElement(children: .combine)
                    }
                }
            }
            question
            if isOffline {
                Label(ReviewCopy.summaryOffline, systemImage: "icloud.slash")
                    .font(BBFont.meta)
                    .foregroundStyle(BBColor.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var question: some View {
        VStack(alignment: .leading, spacing: BBSpacing.s2) {
            Text("\(ReviewCopy.clearStartQuestion) · \(ReviewCopy.optional)")
                .font(BBFont.subtitle)
                .foregroundStyle(BBColor.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: BBSpacing.s2) {
                answer(ReviewCopy.clearYes, .yes)
                answer(ReviewCopy.clearNotReally, .notReally)
            }
            if clearStart != nil {
                Text(ReviewCopy.clearStartThanks)
                    .font(BBFont.meta)
                    .foregroundStyle(BBColor.textTertiary)
            }
        }
    }

    private func answer(_ title: String, _ value: ClearStart) -> some View {
        let isSelected = clearStart == value
        return Button {
            // Tapping the chosen answer again clears it.
            clearStart = isSelected ? nil : value
        } label: {
            Text(title)
                .font(BBFont.secondary)
                .foregroundStyle(isSelected ? BBColor.brandText : BBColor.textPrimary)
                .padding(.horizontal, BBSpacing.s3)
                .frame(minHeight: BBMetrics.hitTarget)
                .background(
                    isSelected ? BBColor.brandSoft : BBColor.surfaceRaised,
                    in: RoundedRectangle(cornerRadius: BBRadius.chip, style: .continuous)
                )
                .overlay {
                    RoundedRectangle(cornerRadius: BBRadius.chip, style: .continuous)
                        .strokeBorder(isSelected ? BBColor.brandText : BBColor.hairline, lineWidth: isSelected ? 2 : 1)
                }
                .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }
}

// MARK: - Previews (every M-22 state)

private extension SummaryContent {
    static func sample(_ values: [SessionCounter: Int]) -> [Count] {
        SessionCounter.allCases.map { Count(counter: $0, value: values[$0] ?? 0) }
    }

    static let busy = sample([.done: 3, .reformulated: 2, .someday: 1, .inboxProcessed: 10, .kept: 4, .movedToNext: 1])
}

#Preview("M-22 default") {
    @Previewable @State var clear: ClearStart? = nil
    SummaryContent(
        counts: SummaryContent.busy, columns: 2, showsCalmLine: false, nextReview: "Next review: Fri 16 Oct, 16:00",
        isOffline: false, clearStart: $clear, onDone: {}
    )
    .environment(ToastCenter())
}

#Preview("M-22 answered") {
    @Previewable @State var clear: ClearStart? = .yes
    SummaryContent(
        counts: SummaryContent.busy, columns: 2, showsCalmLine: false, nextReview: "Next review: Fri 16 Oct, 16:00",
        isOffline: false, clearStart: $clear, onDone: {}
    )
    .environment(ToastCenter())
}

#Preview("M-22 nothing needed changing") {
    @Previewable @State var clear: ClearStart? = nil
    SummaryContent(
        counts: SummaryContent.sample([:]), columns: 2, showsCalmLine: true,
        nextReview: "Next review: Fri 16 Oct, 16:00", isOffline: false, clearStart: $clear, onDone: {}
    )
    .environment(ToastCenter())
}

#Preview("M-22 done without any step") {
    @Previewable @State var clear: ClearStart? = nil
    SummaryContent(
        counts: SummaryContent.sample([:]), columns: 2, showsCalmLine: false,
        nextReview: "Next review: Fri 16 Oct, 16:00", isOffline: false, clearStart: $clear, onDone: {}
    )
    .environment(ToastCenter())
}

#Preview("M-22 offline") {
    @Previewable @State var clear: ClearStart? = nil
    SummaryContent(
        counts: SummaryContent.busy, columns: 2, showsCalmLine: false, nextReview: "Next review: Fri 16 Oct, 16:00",
        isOffline: true, clearStart: $clear, onDone: {}
    )
    .environment(ToastCenter())
}

#Preview("M-22 accessibility size") {
    @Previewable @State var clear: ClearStart? = nil
    SummaryContent(
        counts: SummaryContent.busy, columns: ReviewLayout.summaryColumns(isAccessibilitySize: true),
        showsCalmLine: false, nextReview: "Next review: Fri 16 Oct, 16:00", isOffline: false, clearStart: $clear,
        onDone: {}
    )
    .environment(ToastCenter())
    .environment(\.dynamicTypeSize, .accessibility5)
}
