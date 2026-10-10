import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// The Lists tab: every way into the task store — the four open lists, dates,
/// projects, tags, history, then weekly review and settings. Grouped rows keep
/// their icons in one column (`.bbRow`) so every title starts at the same x.
struct ListsHubScreen: View {
    @Environment(Workspace.self) private var workspace
    @Environment(AppRouter.self) private var router
    /// Read so the Overdue and Today counts change at midnight.
    @Environment(\.dayChangeCount) private var dayChangeCount

    /// How many tags the hub shows before "All tags".
    private static let topTagLimit = 5

    init() {}

    var body: some View {
        let _ = dayChangeCount
        let counts = workspace.counts()
        let readiness = hubReadiness
        WorkspaceQueryContent(readiness: readiness, retry: prepareHub) {
        List {
            listsSection(counts)
            datesSection(counts)
            projectsSection
            tagsSection
            historySection
            footerSection
        }
        .listStyle(.insetGrouped)
        .labelStyle(.bbRow)
        .bbDenseList()
        .bbScreenTitle("Lists")
        }
        .task { await prepareHub() }
    }

    private var hubReadiness: WorkspaceQueryReadiness {
        [workspace.countsReadiness(), workspace.listReadiness(.dateView(.upcoming)),
         workspace.projectsReadiness(), workspace.projectsReadiness(archived: true),
         workspace.topTagsReadiness(limit: Self.topTagLimit)]
            .first { $0 != .ready } ?? .ready
    }

    private func prepareHub() {
        Task {
            await workspace.prepareCounts()
            await workspace.prepareList(.dateView(.upcoming))
            await workspace.prepareProjects()
            await workspace.prepareProjects(archived: true)
            await workspace.prepareTopTags(limit: Self.topTagLimit)
        }
    }

    private func listsSection(_ counts: ListCounts) -> some View {
        Section {
            ForEach(OpenList.allCases) { list in
                NavigationLink(value: AppRoute.destination(.list(list))) {
                    HubRow(
                        title: list.title,
                        systemImage: list.symbolName,
                        count: counts.count(for: list),
                        prominent: list == .inbox
                    )
                }
            }
        } header: {
            BBSectionHeader("Lists")
        }
    }

    /// Overdue, Today and Upcoming as three tiles in one row. Each tile is its
    /// own button (a row holding several links would route every tap to the
    /// first), so each is independently tappable and 44 pt tall.
    private func datesSection(_ counts: ListCounts) -> some View {
        Section {
            HStack(spacing: BBSpacing.s2) {
                ForEach(DateView.allCases, id: \.self) { view in
                    DateTile(view: view, count: count(for: view, in: counts)) {
                        router.open(.destination(.dateView(view)))
                    }
                }
            }
            .listRowInsets(
                EdgeInsets(top: BBSpacing.s1, leading: BBSpacing.s2, bottom: BBSpacing.s1, trailing: BBSpacing.s2)
            )
        } header: {
            BBSectionHeader("Dates")
        }
    }

    private func count(for view: DateView, in counts: ListCounts) -> Int {
        switch view {
        case .overdue: return counts.overdue
        case .today: return counts.today
        case .upcoming: return workspace.list(.dateView(.upcoming)).totalCount
        }
    }

    @ViewBuilder private var projectsSection: some View {
        let projects = workspace.projects()
        let hasArchived = !workspace.projects(archived: true).isEmpty
        Section {
            if projects.isEmpty {
                EmptyHubRow(title: "No projects yet")
            }
            ForEach(projects) { summary in
                NavigationLink(value: AppRoute.destination(.project(summary.id))) {
                    ProjectSummaryRow(summary: summary)
                }
            }
            NavigationLink(value: AppRoute.projects) {
                Label("All projects", systemImage: "folder")
            }
            if hasArchived {
                NavigationLink(value: AppRoute.archivedProjects) {
                    Label("Archived", systemImage: "folder.badge.minus")
                }
            }
        } header: {
            BBSectionHeader("Projects")
        }
    }

    @ViewBuilder private var tagsSection: some View {
        let tags = workspace.topTags(limit: Self.topTagLimit)
        Section {
            if tags.isEmpty {
                EmptyHubRow(title: "No tags yet")
            } else {
                TopTagsRow(tags: tags) { id in
                    router.open(.destination(.tag(id)))
                }
            }
            NavigationLink(value: AppRoute.tags) {
                Label("All tags", systemImage: "tag")
            }
        } header: {
            BBSectionHeader("Tags")
        }
    }

    private var historySection: some View {
        Section {
            ForEach(HistoryKind.allCases, id: \.self) { kind in
                NavigationLink(value: AppRoute.destination(.history(kind))) {
                    HubRow(title: kind.title, systemImage: kind.symbolName)
                }
            }
        } header: {
            BBSectionHeader("History")
        }
    }

    /// Weekly review and Settings, in one section without a header. Weekly
    /// review is not a fifth list: while it is exposed it is a working row with
    /// a neutral recap; until then it is visibly deferred (FR-042).
    private var footerSection: some View {
        Section {
            if workspace.reviewExposed {
                NavigationLink(value: AppRoute.review) {
                    Label {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(ReviewCopy.weeklyReview)
                            Text(workspace.daysSinceLastReview().map { ReviewCopy.lastReview(daysAgo: $0) } ?? ReviewCopy.setUpInAMinute)
                                .font(BBFont.meta)
                                .foregroundStyle(BBColor.textTertiary)
                        }
                    } icon: {
                        Image(systemName: "arrow.counterclockwise")
                    }
                }
            } else {
                DeferredRow(title: ReviewCopy.weeklyReview, systemImage: "arrow.counterclockwise")
            }
            NavigationLink(value: AppRoute.settings) {
                HStack(spacing: BBSpacing.s2) {
                    Label("Settings", systemImage: "gearshape")
                        .layoutPriority(1)
                    Spacer(minLength: BBSpacing.s2)
                    HubSyncStatus()
                }
            }
        }
    }

}

/// A navigation row: symbol, verbatim name, optional count. Only the Inbox
/// count is a prominent badge (design system).
private struct HubRow: View {
    let title: String
    let systemImage: String
    var count: Int = 0
    var prominent: Bool = false

    var body: some View {
        HStack {
            Label(title, systemImage: systemImage)
            Spacer(minLength: BBSpacing.s2)
            if count > 0 {
                CountBadge(count: count, prominent: prominent)
            }
        }
    }
}

/// One of the three date views: symbol and count on top, name under it.
/// Overdue is drawn in the due colour; the label says the same in words.
private struct DateTile: View {
    let view: DateView
    let count: Int
    let open: () -> Void

    var body: some View {
        Button {
            open()
        } label: {
            VStack(spacing: 2) {
                HStack(spacing: BBSpacing.s1) {
                    Image(systemName: view.symbolName)
                        .foregroundStyle(accent)
                        .accessibilityHidden(true)
                    Text(count, format: .number)
                        .font(.title3.weight(.semibold))
                        .monospacedDigit()
                        .foregroundStyle(isOverdue ? BBColor.dueText : BBColor.textPrimary)
                }
                Text(view.title)
                    .font(BBFont.meta)
                    .foregroundStyle(BBColor.textSecondary)
            }
            .frame(maxWidth: .infinity, minHeight: BBMetrics.hitTarget)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(view.title), \(count)")
    }

    private var isOverdue: Bool { view == .overdue }
    private var accent: Color { isOverdue ? BBColor.dueText : BBColor.brandText }
}

/// "No projects yet" / "No tags yet": a muted label whose empty icon slot keeps
/// the text on the same x as the rows around it.
private struct EmptyHubRow: View {
    let title: String

    var body: some View {
        Label {
            Text(title)
                .foregroundStyle(BBColor.textTertiary)
        } icon: {
            Color.clear.frame(width: 1, height: 1)
        }
        .labelStyle(.bbRow)
    }
}

/// The top tags as one wrapping row of pills with their counts, behind a `tag`
/// symbol in the icon column. Each pill opens its tag.
private struct TopTagsRow: View {
    let tags: [TagSummary]
    let open: (TagID) -> Void

    @ScaledMetric(relativeTo: .body) private var column: CGFloat = BBMetrics.iconColumn

    var body: some View {
        HStack(alignment: .top, spacing: BBSpacing.s3) {
            Image(systemName: "tag")
                .foregroundStyle(BBColor.brandText)
                .frame(width: column, height: BBMetrics.hitTarget)
                .accessibilityHidden(true)
            BBFlowLayout(spacing: BBSpacing.s2, lineSpacing: 0) {
                ForEach(tags) { summary in
                    TagButton(summary: summary) { open(summary.id) }
                }
            }
        }
    }
}

/// A tag pill, at least 32 pt tall inside a 44 pt hit area.
private struct TagButton: View {
    let summary: TagSummary
    let open: () -> Void

    var body: some View {
        Button {
            open()
        } label: {
            HStack(spacing: BBSpacing.s1) {
                Text(summary.tag.name)
                    .lineLimit(1)
                if summary.openTaskCount > 0 {
                    Text(summary.openTaskCount, format: .number)
                        .monospacedDigit()
                        .foregroundStyle(BBColor.textTertiary)
                }
            }
            .font(BBFont.caption)
            .foregroundStyle(BBColor.tagText)
            .padding(.horizontal, BBSpacing.s3)
            .frame(minHeight: 32)
            .background(BBColor.tagBackground, in: Capsule())
            .padding(.vertical, 6)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(accessibilityText)
    }

    private var accessibilityText: String {
        let count = summary.openTaskCount
        let tasks = count == 0 ? "no open tasks" : count == 1 ? "1 open task" : "\(count) open tasks"
        return "Tag \(summary.tag.name), \(tasks)"
    }
}

/// Sync state in words, trailing on the Settings row: "Synced just now",
/// "Offline — 3 changes waiting"; amber when it needs the person's attention.
private struct HubSyncStatus: View {
    @Environment(Workspace.self) private var workspace

    var body: some View {
        TimelineView(.periodic(from: .now, by: 30)) { context in
            let description = SyncStatusLabel.describe(
                workspace.syncStatus,
                pendingChanges: workspace.pendingChangeCount,
                now: context.date,
                deviceName: SyncStatusLabel.deviceName
            )
            Text(description.text)
                .font(BBFont.meta)
                .foregroundStyle(description.needsAttention ? BBColor.warningText : BBColor.textTertiary)
                .multilineTextAlignment(.trailing)
        }
    }
}

/// A visibly deferred feature: shown, not interactive, and says so in words.
private struct DeferredRow: View {
    let title: String
    let systemImage: String

    var body: some View {
        HStack {
            Label {
                Text(title)
            } icon: {
                Image(systemName: systemImage)
                    .foregroundStyle(BBColor.textTertiary)
            }
            Spacer(minLength: BBSpacing.s2)
            Text("coming later")
                .font(BBFont.meta)
        }
        .foregroundStyle(BBColor.textTertiary)
        .accessibilityElement(children: .combine)
    }
}
