import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// M-15 (spec 020, FR-030): Inbox to zero. Up to 15 items go one at a time
/// through the Process inbox item view (`InboxClarifier`); over 15 the person
/// picks Process 10, Process all, or Process 10 and release the rest to
/// Someday (`InboxStepPlan`). Every processed item and every Undo moves the
/// run's "Inbox processed" count by one. The release has Undo until the step
/// is left, also after an interruption (the open release is read from the
/// store). Nothing is deleted.
struct InboxStep: View {
    let context: ReviewStepContext

    init(context: ReviewStepContext) {
        self.context = context
    }

    @Environment(Workspace.self) private var workspace
    /// The items to go through, set once the choice (if any) is made.
    @State private var queue: [TaskID]?
    @State private var rest: [TaskID] = []
    @State private var isDone = false
    @State private var problem: String?

    var body: some View {
        let session = workspace.state.review.sessions[context.sessionID]
        let releases = session.map { workspace.openInboxReleases(in: $0) } ?? []
        let items = inboxItems
        if let queue, !isDone, releases.isEmpty {
            InboxClarifier(
                queue: queue, onProcessed: processed, onDone: finishProcessing, showsSkipInToolbar: false,
                onClose: {}
            )
        } else if isDone || !releases.isEmpty {
            InboxDoneContent(
                processed: session?.counts[.inboxProcessed] ?? 0, released: releases.reduce(0) { $0 + $1.released.count },
                isResumed: !isDone, problem: problem, onUndoRelease: { undoRelease(releases) }, onNext: context.advance
            )
        } else if items.isEmpty {
            ReviewStepFrame(title: ReviewCopy.inboxEmpty, primaryTitle: ReviewCopy.next, onPrimary: context.advance) {
                Text(ReviewCopy.nothingToProcess)
                    .font(BBFont.body)
                    .foregroundStyle(BBColor.textSecondary)
            }
        } else if InboxStepPlan.needsChoice(itemCount: items.count) {
            InboxChoiceContent(itemCount: items.count) { choose($0, from: items) }
        } else {
            Color.clear.onAppear { choose(nil, from: items) }
        }
    }

    /// The Inbox as Process inbox sees it: projectless inbox tasks.
    private var inboxItems: [TaskID] {
        workspace.list(.list(.inbox)).sections.flatMap(\.tasks).filter { $0.state == .inbox && $0.projectID == nil }.map(\.id)
    }

    private func choose(_ choice: InboxChoice?, from items: [TaskID]) {
        let plan = InboxStepPlan.split(items, choice: choice)
        queue = plan.process
        rest = plan.release
    }

    private func processed(_ delta: Int) {
        try? workspace.recordReviewProgress(context.sessionID, inboxProcessedDelta: delta)
    }

    /// The last item is done: release the rest that is still in the Inbox.
    private func finishProcessing() {
        isDone = true
        let remaining = rest.filter { workspace.task($0)?.state == .inbox }
        rest = []
        guard !remaining.isEmpty else { return }
        do {
            try workspace.bulkRelease(.inboxRemainder, taskIDs: remaining, sessionID: context.sessionID)
        } catch {
            problem = error.message
        }
    }

    private func undoRelease(_ records: [BulkReleaseRecord]) {
        problem = nil
        do {
            try workspace.undoBulkRelease(records.map(\.id))
        } catch {
            problem = error.message
        }
    }
}

/// Over 15 items: the three choices.
struct InboxChoiceContent: View {
    let itemCount: Int
    let onChoose: (InboxChoice) -> Void

    var body: some View {
        ReviewStepFrame(title: ReviewCopy.stepTitle(.inbox)) {
            Text(ReviewCopy.inboxOver(itemCount))
                .font(BBFont.body)
                .foregroundStyle(BBColor.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            ForEach(InboxChoice.allCases, id: \.self) { choice in
                ReviewChoiceRow(
                    title: ReviewCopy.inboxChoice(choice, itemCount: itemCount),
                    subtitle: choice == .processTenReleaseRest ? ReviewCopy.nothingIsDeleted : nil
                ) {
                    onChoose(choice)
                }
            }
        }
    }
}

/// The queue is finished: the counts, and Undo for a release.
struct InboxDoneContent: View {
    let processed: Int
    let released: Int
    /// The step reopened on a release made before an interruption.
    let isResumed: Bool
    let problem: String?
    let onUndoRelease: () -> Void
    let onNext: () -> Void

    var body: some View {
        ReviewStepFrame(
            title: isResumed && released > 0
                ? ReviewCopy.inboxReleasedResumed(released) : ReviewCopy.inboxProcessed(processed, released: released),
            primaryTitle: ReviewCopy.next, onPrimary: onNext
        ) {
            if released > 0 {
                ReviewChoiceRow(title: ReviewCopy.undoTheReleaseLabel, action: onUndoRelease)
            }
            if let problem {
                InlineProblemText(message: problem)
            }
        }
    }
}

#Preview("M-15 over 15 items") {
    InboxChoiceContent(itemCount: 23, onChoose: { _ in }).environment(ToastCenter())
}

#Preview("M-15 done") {
    InboxDoneContent(processed: 10, released: 0, isResumed: false, problem: nil, onUndoRelease: {}, onNext: {})
        .environment(ToastCenter())
}

#Preview("M-15 done with release") {
    InboxDoneContent(processed: 10, released: 12, isResumed: false, problem: nil, onUndoRelease: {}, onNext: {})
        .environment(ToastCenter())
}

#Preview("M-15 released, resumed after interruption") {
    InboxDoneContent(processed: 10, released: 12, isResumed: true, problem: nil, onUndoRelease: {}, onNext: {})
        .environment(ToastCenter())
}

#Preview("M-15 accessibility size") {
    InboxChoiceContent(itemCount: 23, onChoose: { _ in })
        .environment(ToastCenter())
        .environment(\.dynamicTypeSize, .accessibility5)
}
