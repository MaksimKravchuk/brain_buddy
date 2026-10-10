import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// M-17 (spec 020, FR-031): the rest of Next with the capacity mirror: how
/// many next actions, the pace of the last 4 weeks and what it implies. There
/// is no limit and nothing to decide; the list shows the list markers only.
struct RestOfNextStep: View {
    let context: ReviewStepContext

    init(context: ReviewStepContext) {
        self.context = context
    }

    @Environment(Workspace.self) private var workspace

    var body: some View {
        let read = WorkspaceReviewRead.queue(.restOfNext, context.sessionID)
        let page = workspace.reviewPageState(read)
        let capacity = ReviewCopy.capacity(workspace.capacityMirror(session: context.sessionID))
        let tasks = workspace.restOfNext(session: context.sessionID)
        RestOfNextContent(
            figures: capacity.figures, note: capacity.note,
            rows: tasks.map { task in
                RestOfNextContent.Row(
                    id: task.id, title: task.title,
                    marker: workspace.reviewFormulation(task.id, read: read).map(\.classification).map { MarkerStyle.for($0) }.flatMap { $0.showsInLists ? $0 : nil }
                )
            },
            onNext: context.advance
        )
        .overlay {
            if page.readiness != .ready {
                WorkspaceQueryContent(readiness: page.readiness, retry: { Task { try? await workspace.prepareReviewRead(read) } }) { EmptyView() }
            }
        }
        .safeAreaInset(edge: .bottom) {
            WorkspaceQueryPageControls(page: page,
                previous: { try? await workspace.previousReviewPage(read) },
                next: { try? await workspace.nextReviewPage(read) })
        }
        .task { try? await workspace.prepareReviewRead(read) }
    }
}

/// The step for given values (every state has a preview).
struct RestOfNextContent: View {
    struct Row: Identifiable {
        var id: TaskID
        var title: String
        var marker: MarkerStyle?
    }

    let figures: [String]
    let note: String
    let rows: [Row]
    let onNext: () -> Void

    var body: some View {
        ReviewStepFrame(title: ReviewCopy.stepTitle(.restOfNext), primaryTitle: ReviewCopy.next, onPrimary: onNext) {
            VStack(alignment: .leading, spacing: BBSpacing.s2) {
                ForEach(figures, id: \.self) { figure in
                    Text(figure)
                        .font(BBFont.bodyMedium)
                        .foregroundStyle(BBColor.textPrimary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Text(note)
                    .font(BBFont.secondary)
                    .foregroundStyle(BBColor.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            VStack(alignment: .leading, spacing: BBSpacing.s3) {
                ForEach(rows) { row in
                    VStack(alignment: .leading, spacing: BBSpacing.s1) {
                        Text(row.title)
                            .font(BBFont.body)
                            .foregroundStyle(BBColor.textPrimary)
                            .fixedSize(horizontal: false, vertical: true)
                        if let marker = row.marker, let chip = ReviewMarkerChip(marker) {
                            chip
                        }
                    }
                }
            }
        }
    }
}

#Preview("M-17 default") {
    let capacity = ReviewCopy.capacity(CapacityMirror(nextCount: 41, weeksOfHistory: 6, weeklyAverage4w: 9, impliedWeeks: 4.5))
    RestOfNextContent(
        figures: capacity.figures, note: capacity.note,
        rows: [
            .init(id: "t1", title: "Renovate the bathroom", marker: MarkerStyle.for(.asks)),
            .init(id: "t2", title: "Call the plumber", marker: nil),
        ],
        onNext: {}
    )
    .environment(ToastCenter())
}

#Preview("M-17 first run") {
    let capacity = ReviewCopy.capacity(CapacityMirror(nextCount: 3, weeksOfHistory: 1, weeklyAverage4w: nil, impliedWeeks: nil))
    RestOfNextContent(
        figures: capacity.figures, note: capacity.note, rows: [.init(id: "t1", title: "Call the plumber", marker: nil)],
        onNext: {}
    )
    .environment(ToastCenter())
}

#Preview("M-17 Next is empty") {
    let capacity = ReviewCopy.capacity(CapacityMirror(nextCount: 0, weeksOfHistory: 0, weeklyAverage4w: nil, impliedWeeks: nil))
    RestOfNextContent(figures: capacity.figures, note: capacity.note, rows: [], onNext: {}).environment(ToastCenter())
}
