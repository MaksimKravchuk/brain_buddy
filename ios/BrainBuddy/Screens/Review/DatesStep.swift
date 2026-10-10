import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// M-21 (spec 020, FR-028): what is due in the next 14 days, grouped by day
/// with the list each task is in. Nothing to decide.
struct DatesStep: View {
    let context: ReviewStepContext

    init(context: ReviewStepContext) {
        self.context = context
    }

    @Environment(Workspace.self) private var workspace

    var body: some View {
        let read = WorkspaceReviewRead.queue(.dates, context.sessionID)
        let page = workspace.reviewPageState(read)
        DatesContent(
            days: workspace.datesAhead(session: context.sessionID).map { due in
                DatesContent.Day(
                    heading: due.day.startDate().formatted(.dateTime.weekday(.wide).day().month(.abbreviated)),
                    rows: due.tasks.map { task in
                        DatesContent.Row(id: task.id, title: task.title, list: task.openList?.title ?? "")
                    }
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
struct DatesContent: View {
    struct Row: Identifiable {
        var id: TaskID
        var title: String
        var list: String
    }

    struct Day: Identifiable {
        var heading: String
        var rows: [Row]
        var id: String { heading }
    }

    let days: [Day]
    let onNext: () -> Void

    var body: some View {
        ReviewStepFrame(
            title: days.isEmpty ? ReviewCopy.clearTwoWeeks : ReviewCopy.stepTitle(.dates), primaryTitle: ReviewCopy.next,
            onPrimary: onNext
        ) {
            if days.isEmpty {
                Text(ReviewCopy.nothingDue)
                    .font(BBFont.body)
                    .foregroundStyle(BBColor.textSecondary)
            }
            ForEach(days) { day in
                VStack(alignment: .leading, spacing: BBSpacing.s2) {
                    Text(day.heading)
                        .font(BBFont.subtitle)
                        .foregroundStyle(BBColor.textSecondary)
                        .accessibilityAddTraits(.isHeader)
                    ForEach(day.rows) { row in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(row.title)
                                .font(BBFont.body)
                                .foregroundStyle(BBColor.textPrimary)
                                .fixedSize(horizontal: false, vertical: true)
                            Text(row.list)
                                .font(BBFont.meta)
                                .foregroundStyle(BBColor.textTertiary)
                        }
                    }
                }
            }
        }
    }
}

#Preview("M-21 default") {
    DatesContent(
        days: [
            .init(heading: "Monday 12 Oct", rows: [.init(id: "t1", title: "Send the invoice", list: "Next actions")]),
            .init(heading: "Friday 16 Oct", rows: [.init(id: "t2", title: "Pick up the drill", list: "Waiting for")]),
        ],
        onNext: {}
    )
    .environment(ToastCenter())
}

#Preview("M-21 a clear two weeks") {
    DatesContent(days: [], onNext: {}).environment(ToastCenter())
}
