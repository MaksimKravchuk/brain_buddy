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
    @State private var pendingProgress = 0
    @State private var editorID = UUID().uuidString
    @State private var isSaving = false

    var body: some View {
        let queueRead = WorkspaceReviewRead.queue(.inbox, context.sessionID)
        let queuePage = workspace.reviewPageState(queueRead)
        let releasesRead = WorkspaceReviewRead.releases(.inboxRemainder, context.sessionID)
        let releasesReadiness = workspace.reviewReadiness(releasesRead)
        let readiness = queuePage.readiness == .ready ? releasesReadiness : queuePage.readiness
        let session = workspace.state.review.sessions[context.sessionID]
        let releases = session.map { workspace.openInboxReleases(in: $0) } ?? []
        let items = inboxItems
        WorkspaceQueryContent(readiness: readiness, retry: {
            Task { try? await workspace.prepareReviewRead(queueRead); try? await workspace.prepareReviewRead(releasesRead) }
        }) {
        Group {
        if let queue, !isDone, releases.isEmpty {
            InboxClarifier(
                queue: queue, onProcessed: processed, onDone: finishProcessing, showsSkipInToolbar: false,
                progressProblem: problem, onRetryProgress: retryProgress,
                reviewSessionID: context.sessionID, onClose: {}
            )
        } else if isDone || !releases.isEmpty {
            InboxDoneContent(
                processed: session?.counts[.inboxProcessed] ?? 0, released: releases.reduce(0) { $0 + $1.released.count },
                isResumed: !isDone, problem: problem, onUndoRelease: { undoRelease(releases) },
                onRetry: retryPendingWork, onNext: context.advance
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
        }
        .safeAreaInset(edge: .bottom) {
            WorkspaceQueryPageControls(page: queuePage,
                previous: { try? await workspace.previousReviewPage(queueRead); queue = nil },
                next: { try? await workspace.nextReviewPage(queueRead); queue = nil })
        }
        .task { try? await workspace.prepareReviewRead(queueRead); try? await workspace.prepareReviewRead(releasesRead) }
    }

    /// The Inbox as Process inbox sees it: projectless inbox tasks.
    private var inboxItems: [TaskID] {
        workspace.inboxReviewQueue(session: context.sessionID).map(\.id)
    }

    private func choose(_ choice: InboxChoice?, from items: [TaskID]) {
        let plan = InboxStepPlan.split(items, choice: choice)
        queue = plan.process
        rest = plan.release
    }

    @MainActor private func processed(_ delta: Int) async {
        pendingProgress += delta
        await retryProgressDurably()
    }

    private func retryProgress() { Task { await retryProgressDurably() } }

    @MainActor private func retryProgressDurably() async {
        guard pendingProgress != 0, !isSaving else { return }
        isSaving = true
        defer { isSaving = false }
        let delta = pendingProgress
        do {
            try await workspace.recordReviewProgress(context.sessionID, inboxProcessedDelta: delta, editorID: editorID)
            pendingProgress = 0
            problem = nil
        } catch { problem = TaskCommandRunner.message(for: error) }
    }

    /// The last item is done: release the rest that is still in the Inbox.
    private func finishProcessing() {
        Task { await finishProcessingDurably() }
    }

    @MainActor private func finishProcessingDurably() async {
        guard !isSaving else { return }
        isSaving = true
        defer { isSaving = false }
        let stillInbox = Set(workspace.inboxReviewQueue(session: context.sessionID).map(\.id))
        let remaining = rest.filter { stillInbox.contains($0) }
        guard !remaining.isEmpty else { isDone = true; return }
        do {
            try await workspace.bulkRelease(.inboxRemainder, taskIDs: remaining, sessionID: context.sessionID, editorID: editorID)
            rest = []
            isDone = true
        } catch {
            problem = TaskCommandRunner.message(for: error)
            isDone = true
        }
    }

    private func retryPendingWork() {
        if pendingProgress != 0 { retryProgress() } else { finishProcessing() }
    }

    private func undoRelease(_ records: [BulkReleaseRecord]) {
        Task { await undoReleaseDurably(records) }
    }

    @MainActor private func undoReleaseDurably(_ records: [BulkReleaseRecord]) async {
        guard !isSaving else { return }
        isSaving = true
        defer { isSaving = false }
        problem = nil
        do {
            try await workspace.undoBulkRelease(records.map(\.id), editorID: editorID)
        } catch {
            problem = TaskCommandRunner.message(for: error)
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
    let onRetry: () -> Void
    let onNext: () -> Void

    var body: some View {
        ReviewStepFrame(
            title: isResumed && released > 0
                ? ReviewCopy.inboxReleasedResumed(released) : ReviewCopy.inboxProcessed(processed, released: released),
            primaryTitle: ReviewCopy.next, primaryEnabled: problem == nil, onPrimary: onNext
        ) {
            if released > 0 {
                ReviewChoiceRow(title: ReviewCopy.undoTheReleaseLabel, action: onUndoRelease)
            }
            if let problem {
                InlineProblemText(message: problem)
                ReviewChoiceRow(title: "Retry save", action: onRetry)
            }
        }
    }
}

#Preview("M-15 over 15 items") {
    InboxChoiceContent(itemCount: 23, onChoose: { _ in }).environment(ToastCenter())
}

#Preview("M-15 done") {
    InboxDoneContent(processed: 10, released: 0, isResumed: false, problem: nil, onUndoRelease: {}, onRetry: {}, onNext: {})
        .environment(ToastCenter())
}

#Preview("M-15 done with release") {
    InboxDoneContent(processed: 10, released: 12, isResumed: false, problem: nil, onUndoRelease: {}, onRetry: {}, onNext: {})
        .environment(ToastCenter())
}

#Preview("M-15 released, resumed after interruption") {
    InboxDoneContent(processed: 10, released: 12, isResumed: true, problem: nil, onUndoRelease: {}, onRetry: {}, onNext: {})
        .environment(ToastCenter())
}

#Preview("M-15 accessibility size") {
    InboxChoiceContent(itemCount: 23, onChoose: { _ in })
        .environment(ToastCenter())
        .environment(\.dynamicTypeSize, .accessibility5)
}
