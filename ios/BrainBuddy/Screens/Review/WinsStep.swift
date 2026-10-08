import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// M-13 (spec 020, FR-028): the tasks finished in the last 7 days, before any
/// backlog. Nothing to decide, so finishing it is qualifying activity (Core).
struct WinsStep: View {
    let context: ReviewStepContext

    init(context: ReviewStepContext) {
        self.context = context
    }

    @Environment(Workspace.self) private var workspace

    var body: some View {
        WinsContent(titles: workspace.wins().map(\.title), onNext: context.advance)
    }
}

/// The step for given titles (every state has a preview).
struct WinsContent: View {
    let titles: [String]
    let onNext: () -> Void

    var body: some View {
        ReviewStepFrame(
            title: titles.isEmpty ? ReviewCopy.stepTitle(.wins) : ReviewCopy.wins(titles.count),
            primaryTitle: ReviewCopy.next, onPrimary: onNext
        ) {
            if titles.isEmpty {
                Text(ReviewCopy.quietWeek)
                    .font(BBFont.body)
                    .foregroundStyle(BBColor.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                VStack(alignment: .leading, spacing: BBSpacing.s3) {
                    ForEach(Array(titles.enumerated()), id: \.offset) { _, title in
                        Label(title, systemImage: "checkmark.circle")
                            .font(BBFont.body)
                            .foregroundStyle(BBColor.textPrimary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
        }
    }
}

#Preview("M-13 wins") {
    WinsContent(titles: ["Book the dentist", "Send the invoice", "Renew the passport"], onNext: {})
        .environment(ToastCenter())
}

#Preview("M-13 a quiet week") {
    WinsContent(titles: [], onNext: {}).environment(ToastCenter())
}

#Preview("M-13 accessibility size") {
    WinsContent(titles: ["Book the dentist", "Send the invoice"], onNext: {})
        .environment(ToastCenter())
        .environment(\.dynamicTypeSize, .accessibility5)
}
