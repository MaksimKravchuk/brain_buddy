import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// M-10 (spec 020, FR-017, FR-038): no counted review for 21 days, or the
/// first review after setting up. A neutral welcome and, when Next holds
/// actions older than 4 weeks, one offer: release them all to Someday / maybe
/// (a bulk release, offline too) or keep them. The release can be undone
/// until the person moves on ("Start the review" or Close); the released
/// state is read from the store, so it is still there, with its Undo, after
/// an app kill. Which actions are old, what a release keeps and how Undo
/// restores every clock exactly are Core's.
struct RestartScreen: View {
    let onStart: () -> Void

    @Environment(Workspace.self) private var workspace
    /// The words about the last Undo, until the next release.
    @State private var undoMessage: String?
    @State private var problem: String?

    init(onStart: @escaping () -> Void) {
        self.onStart = onStart
    }

    var body: some View {
        let released = workspace.openRestartReleases()
        let candidates = workspace.restartCandidates()
        let now = workspace.reviewNow
        RestartContent(
            heading: heading, welcome: welcome,
            ages: candidates.map { RestartContent.Row(id: $0.id, title: $0.title, age: age(of: $0, now: now)) },
            releasedCount: released.reduce(0) { $0 + $1.released.count },
            partial: released.reduce(0) { $0 + $1.skipped.count },
            nextNow: workspace.counts().next, undoMessage: undoMessage, problem: problem,
            onRelease: { release(candidates) }, onUndo: { undo(released) }, onStart: onStart
        )
    }

    private var heading: String {
        workspace.lastCountedReview() == nil ? ReviewCopy.restartFirstReview : ReviewCopy.weeklyReview
    }

    private var welcome: String {
        guard let days = workspace.daysSinceLastReview() else { return ReviewCopy.restartFitWeek }
        return ReviewCopy.restartWelcome(daysSinceLastReview: days)
    }

    private func age(of task: TaskRecord, now: Date) -> String {
        task.formulation.map { ReviewCopy.daysInNext(since: $0.startedAt, now: now) } ?? ""
    }

    private func release(_ candidates: [TaskRecord]) {
        problem = nil
        do {
            try workspace.bulkRelease(.restart, taskIDs: candidates.map(\.id))
            undoMessage = nil
        } catch {
            problem = error.message
        }
    }

    private func undo(_ records: [BulkReleaseRecord]) {
        problem = nil
        do {
            try workspace.undoBulkRelease(records.map(\.id))
        } catch {
            problem = error.message
            return
        }
        let results = records.compactMap { workspace.state.review.bulkReleases[$0.id]?.undoResult }
        let restored = results.reduce(0) { $0 + $1.restored.count }
        let skipped = results.reduce(0) { $0 + $1.skipped.count }
        undoMessage = skipped == 0
            ? ReviewCopy.restartUndone(restored) : ReviewCopy.restartUndonePartial(restored: restored, skipped: skipped)
    }
}

/// The screen for given values (every state has a preview).
struct RestartContent: View {
    struct Row: Hashable, Identifiable {
        var id: TaskID
        var title: String
        var age: String
    }

    let heading: String
    let welcome: String
    let ages: [Row]
    /// Tasks of the open release; 0 before one.
    let releasedCount: Int
    /// Tasks the release left in Next because they changed elsewhere.
    let partial: Int
    let nextNow: Int
    let undoMessage: String?
    let problem: String?
    let onRelease: () -> Void
    let onUndo: () -> Void
    let onStart: () -> Void

    @State private var listsThem = false

    init(
        heading: String, welcome: String, ages: [Row], releasedCount: Int, partial: Int, nextNow: Int,
        undoMessage: String?, problem: String?, onRelease: @escaping () -> Void, onUndo: @escaping () -> Void,
        onStart: @escaping () -> Void
    ) {
        self.heading = heading
        self.welcome = welcome
        self.ages = ages
        self.releasedCount = releasedCount
        self.partial = partial
        self.nextNow = nextNow
        self.undoMessage = undoMessage
        self.problem = problem
        self.onRelease = onRelease
        self.onUndo = onUndo
        self.onStart = onStart
    }

    var body: some View {
        ReviewStepFrame(title: heading, primaryTitle: ReviewCopy.startTheReview, onPrimary: onStart) {
            Text(welcome)
                .font(BBFont.body)
                .foregroundStyle(BBColor.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            if releasedCount > 0 {
                released
            } else if ages.isEmpty {
                Text(undoMessage ?? ReviewCopy.restartNothingOld)
                    .font(BBFont.body)
                    .foregroundStyle(BBColor.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                offer
            }
            if let problem {
                InlineProblemText(message: problem)
            }
        }
    }

    private var offer: some View {
        VStack(alignment: .leading, spacing: BBSpacing.s3) {
            if let undoMessage {
                Text(undoMessage)
                    .font(BBFont.body)
                    .foregroundStyle(BBColor.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            DisclosureGroup(isExpanded: $listsThem) {
                VStack(alignment: .leading, spacing: BBSpacing.s2) {
                    ForEach(ages) { row in
                        Text("\(row.title) · \(row.age)")
                            .font(BBFont.secondary)
                            .foregroundStyle(BBColor.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            } label: {
                Text(ages.count == 1 ? ReviewCopy.seeWhichOnes : ReviewCopy.restartOlderThanFourWeeks(ages.count))
                    .font(BBFont.bodyMedium)
                    .foregroundStyle(BBColor.textPrimary)
            }
            .accessibilityHint(ReviewCopy.seeWhichOnes)
            ReviewChoiceRow(title: ReviewCopy.releaseOlder(ages.count), subtitle: ReviewCopy.nothingIsDeleted, action: onRelease)
            Text(ReviewCopy.keepThem)
                .font(BBFont.meta)
                .foregroundStyle(BBColor.textTertiary)
        }
    }

    private var released: some View {
        VStack(alignment: .leading, spacing: BBSpacing.s3) {
            Text(ReviewCopy.restartReleased(releasedCount, nextNow: nextNow))
                .font(BBFont.body)
                .foregroundStyle(BBColor.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
            if partial > 0 {
                Text(ReviewCopy.restartReleasePartial(partial))
                    .font(BBFont.meta)
                    .foregroundStyle(BBColor.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            ReviewChoiceRow(title: ReviewCopy.undoTheRelease(count: releasedCount), action: onUndo)
        }
    }
}

// MARK: - Previews (every M-10 state)

private extension RestartContent {
    static let rows = [
        Row(id: "t1", title: "Renovate the bathroom", age: "41 days in Next"),
        Row(id: "t2", title: "Sort the paperwork drawer", age: "33 days in Next"),
    ]

    init(
        heading: String = "Weekly review", welcome: String = ReviewCopy.restartWelcome(daysSinceLastReview: 26),
        ages: [Row] = RestartContent.rows, releasedCount: Int = 0, partial: Int = 0, undoMessage: String? = nil
    ) {
        self.init(
            heading: heading, welcome: welcome, ages: ages, releasedCount: releasedCount, partial: partial, nextNow: 12,
            undoMessage: undoMessage, problem: nil, onRelease: {}, onUndo: {}, onStart: {}
        )
    }
}

#Preview("M-10 default") {
    RestartContent().environment(ToastCenter())
}

#Preview("M-10 set up but never reviewed") {
    RestartContent(heading: ReviewCopy.restartFirstReview, welcome: ReviewCopy.restartFitWeek)
        .environment(ToastCenter())
}

#Preview("M-10 released, or resumed after interruption") {
    RestartContent(ages: [], releasedCount: 17).environment(ToastCenter())
}

#Preview("M-10 released, some stayed") {
    RestartContent(ages: [], releasedCount: 15, partial: 2).environment(ToastCenter())
}

#Preview("M-10 undone") {
    RestartContent(undoMessage: ReviewCopy.restartUndone(17)).environment(ToastCenter())
}

#Preview("M-10 undone, some skipped") {
    RestartContent(undoMessage: ReviewCopy.restartUndonePartial(restored: 15, skipped: 2)).environment(ToastCenter())
}

#Preview("M-10 nothing older than 4 weeks") {
    RestartContent(ages: []).environment(ToastCenter())
}

#Preview("M-10 accessibility size") {
    RestartContent().environment(ToastCenter()).environment(\.dynamicTypeSize, .accessibility5)
}
