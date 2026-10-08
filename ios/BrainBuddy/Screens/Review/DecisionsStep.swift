import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// M-16 (spec 020, FR-034, FR-050, SC-002): the tasks that ask for a decision,
/// one full-screen decision card at a time (M-03), earliest-asking first, from
/// the queue snapshot taken when the step opened. A decision shows its Undo
/// status line and the next card; "Not now" sets the task aside (it keeps
/// asking and auto-park continues on schedule). Which card is next, and
/// whether everything is decided, is Core's (`GTDQueries.decisionStep`).
struct DecisionsStep: View {
    let context: ReviewStepContext

    init(context: ReviewStepContext) {
        self.context = context
    }

    @Environment(Workspace.self) private var workspace
    @Environment(ToastCenter.self) private var toasts
    /// The threshold when the step opened: a change elsewhere leaves the queue as it is.
    @State private var openedThreshold: Int?

    var body: some View {
        let settings = workspace.state.review.settings
        VStack(spacing: 0) {
            if let openedThreshold, openedThreshold != settings.thresholdDays {
                Text(ReviewCopy.thresholdChangedMidReview(days: settings.thresholdDays))
                    .font(BBFont.meta)
                    .foregroundStyle(BBColor.textTertiary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, BBSpacing.s4)
            }
            if let session = workspace.state.review.sessions[context.sessionID] {
                switch workspace.decisionStep(in: session) {
                case .card(let id, let position, let total):
                    card(id, position: position, total: total)
                case .nothingAsks:
                    DecisionsDoneContent(
                        title: ReviewCopy.nothingAsks, detail: nil, onNext: context.advance
                    )
                case .allDecided(let count, let keptWording):
                    DecisionsDoneContent(
                        title: ReviewCopy.allDecided(count),
                        detail: keptWording == 0 ? ReviewCopy.nothingWaitingForDecision : ReviewCopy.keptItsWording(keptWording),
                        onNext: context.advance
                    )
                case .someLeft(let decided, let total, let stillAsking):
                    DecisionsDoneContent(
                        title: ReviewCopy.someDecided(decided, of: total), detail: ReviewCopy.stillAsk(stillAsking),
                        onNext: context.advance
                    )
                }
            }
        }
        .task {
            guard openedThreshold == nil else { return }
            openedThreshold = settings.thresholdDays
            // The queue is fixed for this run when the step first opens.
            if workspace.state.review.sessions[context.sessionID]?.decisionQueue == nil {
                try? workspace.recordReviewProgress(context.sessionID, snapshotDecisionQueue: true)
            }
        }
    }

    private func card(_ id: TaskID, position: Int, total: Int) -> some View {
        VStack(spacing: 0) {
            DecisionCardSheet(
                taskID: id,
                review: ReviewDecisionContext(
                    sessionID: context.sessionID, position: ReviewCopy.decisionPosition(position, of: total),
                    onDecided: { decisionID, decision, title in
                        DecisionUndoToast.show(
                            decisionID, decision: decision, title: title, taskID: id, workspace: workspace, toasts: toasts
                        )
                    },
                    onNotNow: {
                        try? workspace.recordReviewProgress(context.sessionID, setAsideTaskID: id)
                    }
                )
            )
            .id(id)
            ToastHost()
        }
    }
}

/// The queue is finished (or empty): the count and what is left.
struct DecisionsDoneContent: View {
    let title: String
    let detail: String?
    let onNext: () -> Void

    var body: some View {
        ReviewStepFrame(title: title, primaryTitle: ReviewCopy.next, onPrimary: onNext) {
            if let detail {
                Text(detail)
                    .font(BBFont.body)
                    .foregroundStyle(BBColor.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

#Preview("M-16 all decided") {
    DecisionsDoneContent(
        title: ReviewCopy.allDecided(5), detail: ReviewCopy.nothingWaitingForDecision, onNext: {}
    )
    .environment(ToastCenter())
}

#Preview("M-16 all decided, one kept its wording") {
    DecisionsDoneContent(title: ReviewCopy.allDecided(5), detail: ReviewCopy.keptItsWording(1), onNext: {})
        .environment(ToastCenter())
}

#Preview("M-16 some left") {
    DecisionsDoneContent(
        title: ReviewCopy.someDecided(3, of: 5), detail: ReviewCopy.stillAsk(2), onNext: {}
    )
    .environment(ToastCenter())
}

#Preview("M-16 nothing asks") {
    DecisionsDoneContent(title: ReviewCopy.nothingAsks, detail: nil, onNext: {}).environment(ToastCenter())
}

#Preview("M-16 accessibility size") {
    DecisionsDoneContent(
        title: ReviewCopy.someDecided(3, of: 5), detail: ReviewCopy.stillAsk(2), onNext: {}
    )
    .environment(ToastCenter())
    .environment(\.dynamicTypeSize, .accessibility5)
}
