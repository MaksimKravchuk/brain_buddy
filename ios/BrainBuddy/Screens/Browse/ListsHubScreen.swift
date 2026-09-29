import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// The Lists tab: every way into the task store, in the web sidebar's order —
/// the four open lists, dates, projects, tags, history, then settings.
struct ListsHubScreen: View {
    @Environment(Workspace.self) private var workspace

    /// How many tags the hub shows before "All tags".
    private static let topTagLimit = 6

    init() {}

    var body: some View {
        let counts = workspace.counts()
        List {
            listsSection(counts)
            datesSection(counts)
            projectsSection
            tagsSection
            historySection
            settingsSection
        }
        .navigationTitle("Lists")
    }

    private func listsSection(_ counts: ListCounts) -> some View {
        Section("Lists") {
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
            DeferredRow(title: "Weekly review", systemImage: "arrow.counterclockwise")
        }
    }

    private func datesSection(_ counts: ListCounts) -> some View {
        Section("Dates") {
            ForEach(DateView.allCases, id: \.self) { view in
                NavigationLink(value: AppRoute.destination(.dateView(view))) {
                    HubRow(title: view.title, systemImage: view.symbolName, count: count(for: view, in: counts))
                }
            }
        }
    }

    private func count(for view: DateView, in counts: ListCounts) -> Int {
        switch view {
        case .overdue: return counts.overdue
        case .today: return counts.today
        case .upcoming: return workspace.list(.dateView(.upcoming)).openCount
        }
    }

    @ViewBuilder private var projectsSection: some View {
        let projects = workspace.projects()
        let hasArchived = !workspace.projects(archived: true).isEmpty
        Section("Projects") {
            if projects.isEmpty {
                Text("No projects yet")
                    .foregroundStyle(.secondary)
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
        }
    }

    @ViewBuilder private var tagsSection: some View {
        let tags = workspace.tags()
        Section("Tags") {
            if tags.isEmpty {
                Text("No tags yet")
                    .foregroundStyle(.secondary)
            }
            ForEach(Self.topTags(tags, limit: Self.topTagLimit)) { summary in
                NavigationLink(value: AppRoute.destination(.tag(summary.id))) {
                    TagSummaryRow(summary: summary)
                }
            }
            NavigationLink(value: AppRoute.tags) {
                Label("All tags", systemImage: "tag")
            }
        }
    }

    private var historySection: some View {
        Section("History") {
            ForEach(HistoryKind.allCases, id: \.self) { kind in
                NavigationLink(value: AppRoute.destination(.history(kind))) {
                    HubRow(title: kind.title, systemImage: kind.symbolName)
                }
            }
        }
    }

    private var settingsSection: some View {
        Section {
            NavigationLink(value: AppRoute.settings) {
                Label {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Settings")
                        SyncStatusLabel()
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                } icon: {
                    Image(systemName: "gearshape")
                }
            }
        }
    }

    /// The most-used tags first (by open tasks), then by name.
    static func topTags(_ tags: [TagSummary], limit: Int) -> [TagSummary] {
        let ranked = tags.sorted { lhs, rhs in
            if lhs.openTaskCount != rhs.openTaskCount { return lhs.openTaskCount > rhs.openTaskCount }
            return lhs.tag.name.localizedStandardCompare(rhs.tag.name) == .orderedAscending
        }
        return Array(ranked.prefix(limit))
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
            Spacer(minLength: 8)
            if count > 0 {
                CountBadge(count: count, prominent: prominent)
            }
        }
    }
}

/// A visibly deferred feature: shown, not interactive, and says so in words.
private struct DeferredRow: View {
    let title: String
    let systemImage: String

    var body: some View {
        HStack {
            Label(title, systemImage: systemImage)
            Spacer(minLength: 8)
            Text("coming later")
                .font(.footnote)
        }
        .foregroundStyle(.secondary)
        .accessibilityElement(children: .combine)
    }
}
