import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// M-09 (spec 020, FR-015): the auto-parked tasks this person has not seen,
/// at app open (at most once a calendar day, `WhileAwayPresentation`) with a
/// one-tap "Return to Next" per row and "Return all N". "Continue" marks them
/// seen (`Workspace.dismissWhileAway()`); a swipe-down does not, so they show
/// again on a later day. A return is the ordinary move to Next, which starts a
/// fresh formulation (US2-4). When the device's safety valve held more parks
/// back, Continue applies and shows the next batch. Rows for an unsent "Keep
/// 7 more days" that account linking dropped are information only, shown
/// once. Everything is local, so it works offline.
struct WhileYouWereAwaySheet: View {
    @Environment(Workspace.self) private var workspace
    @Environment(\.dismiss) private var dismiss
    /// The parks and notices listed when the sheet appeared; returned rows
    /// stay listed with their outcome.
    @State private var parkIDs: [TaskID] = []
    @State private var noticeIDs: [TaskID] = []
    @State private var outcomes: [TaskID: WhileAwayRow.Outcome] = [:]
    @State private var summary: String?
    @State private var problem: String?
    @State private var hasContinued = false
    @State private var hasLoaded = false

    init() {}

    var body: some View {
        NavigationStack {
            WhileAwayContent(
                rows: rows, summary: summary, problem: problem,
                morePending: workspace.localReview.parkBatchWaiting, isOffline: isOffline,
                onReturn: { _ = returnTask($0) }, onReturnAll: returnAll, onContinue: continueReview
            )
        }
        .presentationDetents([.large])
        .onAppear(perform: load)
        .onDisappear(perform: closedWithoutContinue)
    }

    private var isOffline: Bool {
        if case .offline = workspace.syncStatus { return true }
        return false
    }

    private var rows: [WhileAwayRow] {
        let zone = TimeZone.current
        let parks = parkIDs.compactMap { id -> WhileAwayRow? in
            guard let task = workspace.task(id) else { return nil }
            let project = task.projectID.flatMap { workspace.project($0) }
            var place = project?.name ?? "no project"
            if project?.state == .archived { place += " (archived)" }
            let parkedOn = task.parked.map { "Parked \(ReviewCopy.day($0.at, in: zone)) · \(place)" } ?? place
            let archived = project?.state == .archived ? project?.name : nil
            return WhileAwayRow(
                id: id, title: task.title, detail: parkedOn,
                outcome: outcomes[id] ?? (archived.map { WhileAwayRow.Outcome.archived(project: $0) } ?? .waiting)
            )
        }
        let notices = noticeIDs.compactMap { id -> WhileAwayRow? in
            guard let task = workspace.task(id) else { return nil }
            return WhileAwayRow(
                id: id, title: task.title, detail: ReviewCopy.extensionRestarted(title: task.title), outcome: .notice
            )
        }
        return parks + notices
    }

    private func load() {
        guard !hasLoaded else { return }
        hasLoaded = true
        reloadLists()
    }

    private func reloadLists() {
        parkIDs = workspace.unseenParks().map(\.id)
        noticeIDs = workspace.linkedExtensionNotices
        outcomes = [:]
        summary = nil
    }

    // MARK: Returning

    /// Returns one task with the ordinary move to Next; says why when it
    /// cannot (archived project, changed elsewhere).
    @discardableResult
    private func returnTask(_ id: TaskID) -> Bool {
        problem = nil
        guard let task = workspace.task(id), task.state == .someday, task.parked != nil else {
            outcomes[id] = .changedElsewhere
            if let task = workspace.task(id) { summary = ReviewCopy.returnChangedElsewhere(title: task.title) }
            return false
        }
        if let project = task.projectID.flatMap({ workspace.project($0) }), project.state == .archived {
            outcomes[id] = .archived(project: project.name)
            return false
        }
        do {
            try workspace.moveTask(id, to: .next)
            outcomes[id] = .returned
            return true
        } catch {
            if error == .projectArchived || error == .projectNotActive {
                let name = task.projectID.flatMap { workspace.project($0)?.name } ?? ""
                outcomes[id] = .archived(project: name)
            } else {
                problem = error.message
            }
            return false
        }
    }

    private func returnAll() {
        let pending = rows.filter { $0.outcome == .waiting }
        var returned = 0
        var blocked: [WhileAwayRow] = []
        for row in pending {
            if returnTask(row.id) { returned += 1 } else { blocked.append(row) }
        }
        let archivedRows = blocked.compactMap { row -> String? in
            guard case .archived(let project)? = outcomes[row.id] else { return nil }
            return ReviewCopy.returnBlockedArchived(title: row.title, project: project)
        }
        if archivedRows.isEmpty, blocked.isEmpty {
            summary = ReviewCopy.allReturned(returned)
        } else if !archivedRows.isEmpty {
            let lead = returned == 1 ? "1 task is back in Next." : "\(returned) tasks are back in Next."
            summary = ([lead] + archivedRows + ["Restore the project first to bring it back."]).joined(separator: " ")
        }
    }

    // MARK: Leaving

    /// Continue: the listed parks are seen; held-back parks may now apply,
    /// and when they do the sheet shows the next batch instead of closing.
    private func continueReview() {
        let batchWaiting = workspace.localReview.parkBatchWaiting
        do {
            try workspace.dismissWhileAway()
        } catch {
            problem = error.message
            return
        }
        hasContinued = true
        if batchWaiting, workspace.applyDueAutoParks() > 0, !workspace.unseenParks().isEmpty {
            hasContinued = false
            reloadLists()
            return
        }
        dismiss()
    }

    /// Swiping down is not "seen" (FR-015): parks stay unseen. Information
    /// rows alone have nothing to acknowledge and are shown once.
    private func closedWithoutContinue() {
        guard !hasContinued, workspace.unseenParks().isEmpty, !workspace.linkedExtensionNotices.isEmpty else { return }
        try? workspace.dismissWhileAway()
    }
}

/// One row: a park with its return state, or a linking notice.
struct WhileAwayRow: Identifiable, Hashable {
    enum Outcome: Hashable {
        /// Still in Someday, "Return to Next" offered.
        case waiting
        case returned
        case archived(project: String)
        case changedElsewhere
        /// "Account linked: extension restarted", no button.
        case notice
    }

    let id: TaskID
    let title: String
    let detail: String
    let outcome: Outcome
}

/// The sheet's content for given rows (every state has a preview). The list
/// scrolls and rows wrap at every text size; at accessibility sizes the
/// actions follow the rows instead of being pinned.
struct WhileAwayContent: View {
    let rows: [WhileAwayRow]
    let summary: String?
    let problem: String?
    let morePending: Bool
    let isOffline: Bool
    let onReturn: (TaskID) -> Void
    let onReturnAll: () -> Void
    let onContinue: () -> Void

    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    /// VoiceOver starts on the heading: the sheet appears without a tap.
    @AccessibilityFocusState private var isHeadingFocused: Bool

    init(
        rows: [WhileAwayRow], summary: String?, problem: String?, morePending: Bool, isOffline: Bool,
        onReturn: @escaping (TaskID) -> Void, onReturnAll: @escaping () -> Void, onContinue: @escaping () -> Void
    ) {
        self.rows = rows
        self.summary = summary
        self.problem = problem
        self.morePending = morePending
        self.isOffline = isOffline
        self.onReturn = onReturn
        self.onReturnAll = onReturnAll
        self.onContinue = onContinue
    }

    private var parkCount: Int { rows.filter { $0.outcome != .notice }.count }
    private var returnable: Int { rows.filter { $0.outcome == .waiting }.count }

    var body: some View {
        let actionsScroll = dynamicTypeSize.isAccessibilitySize
        ScrollView {
            VStack(alignment: .leading, spacing: BBSpacing.s4) {
                Text(ReviewCopy.whileAwayTitle)
                    .font(BBFont.display)
                    .foregroundStyle(BBColor.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityAddTraits(.isHeader)
                    .accessibilityFocused($isHeadingFocused)
                if parkCount > 0 {
                    Text(summary ?? intro)
                        .font(BBFont.secondary)
                        .foregroundStyle(BBColor.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                VStack(spacing: 0) {
                    ForEach(rows) { row in
                        WhileAwayRowView(row: row, onReturn: { onReturn(row.id) })
                        if row.id != rows.last?.id {
                            Divider()
                        }
                    }
                }
                .bbCard()
                if let problem {
                    InlineProblemText(message: problem)
                }
                if isOffline {
                    Label("Offline. Changes are saved on this iPhone and sync later.", systemImage: "icloud.slash")
                        .font(BBFont.meta)
                        .foregroundStyle(BBColor.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)
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

    private var intro: String {
        let text = ReviewCopy.whileAwayIntro(count: parkCount)
        return morePending ? "\(text) \(ReviewCopy.moreParksFollow)" : text
    }

    private var actions: some View {
        VStack(spacing: BBSpacing.s2) {
            if returnable > 1 {
                Button(action: onReturnAll) {
                    Text(ReviewCopy.returnAll(returnable))
                        .frame(maxWidth: .infinity, minHeight: BBMetrics.hitTarget)
                }
                .buttonStyle(.bordered)
            }
            Button(action: onContinue) {
                Text(ReviewCopy.continueLabel)
                    .frame(maxWidth: .infinity, minHeight: BBMetrics.hitTarget)
            }
            .buttonStyle(.borderedProminent)
        }
    }
}

private struct WhileAwayRowView: View {
    let row: WhileAwayRow
    let onReturn: () -> Void

    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    init(row: WhileAwayRow, onReturn: @escaping () -> Void) {
        self.row = row
        self.onReturn = onReturn
    }

    var body: some View {
        let layout = dynamicTypeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: BBSpacing.s2))
            : AnyLayout(HStackLayout(alignment: .center, spacing: BBSpacing.s3))
        layout {
            VStack(alignment: .leading, spacing: 2) {
                Text(row.title)
                    .font(BBFont.bodyMedium)
                    .foregroundStyle(BBColor.textPrimary)
                Text(detailLine)
                    .font(BBFont.meta)
                    .foregroundStyle(BBColor.textTertiary)
            }
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
            trailing
        }
        .padding(.horizontal, BBSpacing.s4)
        .padding(.vertical, BBSpacing.s3)
    }

    private var detailLine: String {
        switch row.outcome {
        case .returned: ReviewCopy.returnedOne
        case .waiting, .archived, .changedElsewhere, .notice: row.detail
        }
    }

    @ViewBuilder private var trailing: some View {
        switch row.outcome {
        case .waiting:
            Button(ReviewCopy.returnToNext, action: onReturn)
                .buttonStyle(.bordered)
                .frame(minHeight: BBMetrics.hitTarget)
                .accessibilityLabel("Return \(row.title) to Next")
        case .returned:
            Text("Returned")
                .font(BBFont.meta.weight(.semibold))
                .foregroundStyle(BBColor.successText)
        case .archived(let project):
            Text("Project archived")
                .font(BBFont.meta)
                .foregroundStyle(BBColor.textTertiary)
                .accessibilityLabel("Return unavailable: project \(project) is archived")
        case .changedElsewhere:
            Text("Changed elsewhere")
                .font(BBFont.meta)
                .foregroundStyle(BBColor.textTertiary)
        case .notice:
            EmptyView()
        }
    }
}

// MARK: - Previews (every M-09 state)

@MainActor
private func whileAwayPreview(
    _ rows: [WhileAwayRow], summary: String? = nil, morePending: Bool = false, isOffline: Bool = false
) -> some View {
    WhileAwayContent(
        rows: rows, summary: summary, problem: nil, morePending: morePending, isOffline: isOffline, onReturn: { _ in },
        onReturnAll: {}, onContinue: {}
    )
}

private enum WhileAwayPreviewRows {
    static func row(_ n: Int, _ title: String, _ detail: String, _ outcome: WhileAwayRow.Outcome = .waiting) -> WhileAwayRow {
        WhileAwayRow(id: TaskID("preview-\(n)"), title: title, detail: detail, outcome: outcome)
    }

    static let four = [
        row(1, "Learn basic Portuguese", "Parked Thu 8 Oct · Personal"),
        row(2, "Clean out the garage", "Parked Thu 8 Oct · Home"),
        row(3, "Update the CV", "Parked Tue 6 Oct · no project"),
        row(4, "Write to the old landlord", "Parked Sun 4 Oct · Home"),
    ]

    static let oneReturned = [
        row(1, "Learn basic Portuguese", "Parked Thu 8 Oct · Personal"),
        row(2, "Clean out the garage", "Parked Thu 8 Oct · Home", .returned),
        row(3, "Update the CV", "Parked Tue 6 Oct · no project"),
        row(4, "Write to the old landlord", "Parked Sun 4 Oct · Home"),
    ]

    static let allReturned = [
        row(1, "Learn basic Portuguese", "", .returned),
        row(2, "Clean out the garage", "", .returned),
        row(3, "Update the CV", "", .returned),
        row(4, "Write to the old landlord", "", .returned),
    ]
}

#Preview("M-09 default") {
    whileAwayPreview(WhileAwayPreviewRows.four)
}

#Preview("M-09 one returned") {
    whileAwayPreview(WhileAwayPreviewRows.oneReturned)
}

#Preview("M-09 project archived, partial failure") {
    whileAwayPreview(
        [
            WhileAwayPreviewRows.row(1, "Learn basic Portuguese", "", .returned),
            WhileAwayPreviewRows.row(2, "Clean out the garage", "", .returned),
            WhileAwayPreviewRows.row(3, "Update the CV", "", .returned),
            WhileAwayPreviewRows.row(
                4, "Return the old router", "Parked Thu 8 Oct · Old flat (archived)", .archived(project: "Old flat")
            ),
        ],
        summary: "3 tasks are back in Next. "
            + ReviewCopy.returnBlockedArchived(title: "Return the old router", project: "Old flat")
            + " Restore the project first to bring it back."
    )
}

#Preview("M-09 changed elsewhere") {
    whileAwayPreview(
        [
            WhileAwayPreviewRows.row(1, "Learn basic Portuguese", "", .returned),
            WhileAwayPreviewRows.row(3, "Update the CV", "In Next", .changedElsewhere),
        ],
        summary: ReviewCopy.returnChangedElsewhere(title: "Update the CV")
    )
}

#Preview("M-09 all returned") {
    whileAwayPreview(WhileAwayPreviewRows.allReturned, summary: ReviewCopy.allReturned(4))
}

#Preview("M-09 offline") {
    whileAwayPreview(Array(WhileAwayPreviewRows.four.prefix(2)), isOffline: true)
}

#Preview("M-09 more parks waiting") {
    whileAwayPreview(WhileAwayPreviewRows.four, morePending: true)
}

#Preview("M-09 account linked: extension restarted") {
    whileAwayPreview(
        [
            WhileAwayPreviewRows.row(1, "Learn basic Portuguese", "Parked Thu 8 Oct · Personal"),
            WhileAwayPreviewRows.row(
                5, "Call the landlord", ReviewCopy.extensionRestarted(title: "Call the landlord"), .notice
            ),
        ]
    )
}

#Preview("M-09 accessibility size") {
    whileAwayPreview(WhileAwayPreviewRows.four)
        .environment(\.dynamicTypeSize, .accessibility5)
}
