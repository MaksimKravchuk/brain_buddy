import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// Any list of tasks: the four GTD lists, Today (agenda) and date views,
/// a project or tag, completed or cancelled history, and search results.
/// Content is flat (plain list, brand rows); only the toolbar is glass.
///
/// While it is on top of its tab it publishes where a capture from here goes
/// (its list, its active project or its tag) to the router, so the capture
/// bar and ⌘N file into the screen you are looking at.
struct TaskListScreen: View {
    private let destination: Destination

    @Environment(Workspace.self) private var workspace
    @Environment(AppRouter.self) private var router
    @Environment(\.appTab) private var tab
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    /// Read so date views and due chips redraw on a new day.
    @Environment(\.dayChangeCount) private var dayChangeCount
    /// JSON-encoded `ListOptions`, one key per destination (see `ListOptionsStore`).
    /// The default value is the destination's default options, so a fresh
    /// install starts with Next actions grouped by project.
    @AppStorage private var storedOptions: String
    /// The decision card (M-03) a marker chip opened, as a large sheet.
    @State private var decisionCard: DecisionCardTarget?

    init(destination: Destination) {
        self.destination = destination
        _storedOptions = AppStorage(
            wrappedValue: ListOptionsStore.encode(ListOptionsStore.defaults(for: destination)),
            ListOptionsStore.key(for: destination)
        )
    }

    var body: some View {
        let _ = dayChangeCount
        let options = effectiveOptions
        let result = workspace.list(destination, options: options)
        let card = $decisionCard
        taskList(result, options: options)
            // Marker chips (M-01) open the decision card over the list.
            .environment(\.openDecisionCard, OpenDecisionCardAction { taskID in
                card.wrappedValue = DecisionCardTarget(taskID: taskID)
            })
            .sheet(item: $decisionCard) { target in
                DecisionCardSheet(taskID: target.taskID)
            }
            .bbScreenTitle(title)
            .modifier(
                ListSubtitle(summary: result.isEmpty ? nil : caption(for: result, options: options))
            )
            .toolbar { toolbarContent(result) }
            .refreshable {
                await workspace.syncNow()
            }
            .onChange(of: hasDanglingTagFilter, initial: true) { _, isDangling in
                // The tag was deleted (here or on another device): drop the
                // filter so the menu does not claim the list is filtered.
                if isDangling { storedOptions.listOptions.tagFilter = nil }
            }
            .onAppear(perform: publishCaptureContext)
            .onChange(of: filesCaptures) { _, _ in
                // The project was archived or the tag deleted while on screen.
                publishCaptureContext()
            }
            .onDisappear {
                if let tab { router.withdrawCaptureContext(for: destination, on: tab) }
            }
    }

    // MARK: Capture

    /// Where a capture started from this screen goes, or nil when it files
    /// nothing (dates, history, search, an archived project, a deleted tag).
    /// Projects capture next actions, since a project moves forward by its
    /// next action.
    private var captureContext: CaptureContext? {
        switch destination {
        case .list(let list):
            return CaptureContext(list: list)
        case .project(let id):
            guard workspace.project(id)?.state == .active else { return nil }
            return CaptureContext(list: .next, projectID: id)
        case .tag(let id):
            guard workspace.tag(id)?.state == .active else { return nil }
            return CaptureContext(tagID: id)
        case .agenda, .dateView, .history, .search:
            return nil
        }
    }

    private var filesCaptures: Bool { captureContext != nil }

    private func publishCaptureContext() {
        guard let tab else { return }
        router.publishCaptureContext(captureContext, for: destination, on: tab)
    }

    private var isArchivedProject: Bool {
        guard case .project(let id) = destination else { return false }
        return workspace.project(id)?.state == .archived
    }

    private func taskList(_ result: TaskListResult, options: ListOptions) -> some View {
        List {
            if case .list(.next) = destination, !result.isEmpty {
                reviewNotes
            }
            if case .project(let projectID) = destination {
                ProjectStatusRow(projectID: projectID)
            }
            ForEach(result.sections) { section in
                taskSection(section)
            }
        }
        .listStyle(.plain)
        .bbDenseList()
        .animation(
            BBMotion.animation(.settle, reduceMotion: reduceMotion),
            value: result.sections.flatMap(\.tasks).map(\.id)
        )
        .overlay {
            if result.isEmpty {
                if case .list(.next) = destination {
                    // The empty state would cover notes in the list: they
                    // sit above it instead.
                    VStack(spacing: 0) {
                        reviewNotes
                            .padding(.horizontal, BBSpacing.s4)
                        emptyState(isFiltered: ListOptionsRules.isFiltered(options))
                            .frame(maxHeight: .infinity)
                    }
                } else {
                    emptyState(isFiltered: ListOptionsRules.isFiltered(options))
                }
            }
        }
    }

    /// Weekly review notes on Next (M-01 threshold changed, M-03 error rows);
    /// each shows only when it applies.
    @ViewBuilder private var reviewNotes: some View {
        ReviewThresholdNote()
        DecisionIssuesNote()
    }

    private func taskSection(_ section: TaskSection) -> some View {
        Section {
            ForEach(section.tasks) { task in
                NavigationLink(value: AppRoute.task(task.id)) {
                    TaskRow(task: task, showsProject: showsProject, showsList: showsList)
                }
                // The row carries its own affordance; the chevron would only
                // take width from the title and its metadata.
                .navigationLinkIndicatorVisibility(.hidden)
                // The completion circle's 44 pt target starts near the edge.
                .listRowInsets(Self.rowInsets)
                .taskActions(task)
            }
        } header: {
            if let title = section.title {
                BBSectionHeader(
                    title, count: section.tasks.count, dotColor: projectDotColor(for: section), countsTasks: true
                )
                .listRowInsets(Self.headerInsets)
            }
        }
    }

    private static let rowInsets = EdgeInsets(top: 0, leading: 8, bottom: 0, trailing: 20)
    private static let headerInsets = EdgeInsets(top: 12, leading: 16, bottom: 4, trailing: 20)

    /// The project's colour for a project group, or nil for any other section
    /// (and for "No project").
    private func projectDotColor(for section: TaskSection) -> Color? {
        guard case .project(let id?) = section.kind else { return nil }
        return BBColor.project(workspace.project(id)?.color)
    }

    @ToolbarContentBuilder
    private func toolbarContent(_ result: TaskListResult) -> some ToolbarContent {
        if case .list(.inbox) = destination {
            ToolbarItem(placement: .topBarTrailing) {
                Button("Process") {
                    router.isProcessingInbox = true
                }
                .disabled(result.openCount == 0)
                .accessibilityHint("Clarify your inbox one item at a time.")
            }
        }
        ToolbarItem(placement: .topBarTrailing) {
            ListOptionsMenu(options: $storedOptions.listOptions, destination: destination)
        }
    }

    // MARK: Options

    private var hasDanglingTagFilter: Bool {
        guard let tagID = storedOptions.listOptions.tagFilter else { return false }
        return workspace.tag(tagID)?.state != .active
    }

    /// Stored options with anything that no longer applies removed: a tag
    /// filter whose tag was deleted, and options this destination does not offer.
    private var effectiveOptions: ListOptions {
        var options = storedOptions.listOptions
        if let tagID = options.tagFilter,
            !ListOptionsRules.allowsTagFilter(destination) || workspace.tag(tagID)?.state != .active
        {
            options.tagFilter = nil
        }
        if !ListOptionsRules.allowsGrouping(destination) { options.groupByProject = false }
        if !ListOptionsRules.allowsHistory(destination) {
            options.showCompleted = false
            options.showCancelled = false
        }
        return options
    }

    // MARK: Presentation

    private var showsProject: Bool {
        if case .project = destination { return false }
        return true
    }

    private var showsList: Bool {
        if case .list = destination { return false }
        return true
    }

    private var title: String {
        switch destination {
        case .list(let list): list.title
        case .agenda: "Today"
        case .dateView(let view): view.title
        case .project(let id): workspace.project(id)?.name ?? "Project"
        case .tag(let id): workspace.tag(id)?.name ?? "Tag"
        case .history(let kind): kind.title
        case .search: "Search"
        }
    }

    private func caption(for result: TaskListResult, options: ListOptions) -> String {
        var parts: [String] = []
        switch destination {
        case .history(let kind):
            let count = result.sections.reduce(0) { $0 + $1.tasks.count }
            parts.append("\(count) \(kind == .completed ? "completed" : "cancelled")")
        case .search:
            let count = result.sections.reduce(0) { $0 + $1.tasks.count }
            parts.append(count == 1 ? "1 match" : "\(count) matches")
        default:
            parts.append(result.openCount == 1 ? "1 open task" : "\(result.openCount) open tasks")
        }
        if ListOptionsRules.isFiltered(options) { parts.append("filtered") }
        if options.sort != .manual { parts.append("sorted by \(options.sort.title.lowercased())") }
        return parts.joined(separator: " · ")
    }

    private func emptyState(isFiltered: Bool) -> some View {
        let copy =
            isArchivedProject
            ? EmptyListCopy.archivedProject
            : isFiltered ? EmptyListCopy.filtered : EmptyListCopy.forDestination(destination)
        return VStack(spacing: 16) {
            EmptyStateView(title: copy.title, message: copy.message, systemImage: copy.systemImage)
            SyncStatusLabel()
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
        .padding()
    }
}

/// The line under the title: the list's summary ("14 open tasks · filtered")
/// and the sync state in words, joined with " · ". It sits in the navigation
/// bar instead of in two rows of the list. An empty list passes no summary
/// and shows the sync state alone, so the line is never blank. Relative times
/// ("Synced 2 minutes ago") refresh every 30 seconds without redrawing the list.
private struct ListSubtitle: ViewModifier {
    let summary: String?

    @Environment(Workspace.self) private var workspace
    /// Bumped every 30 seconds so the subtitle recomputes against the clock.
    @State private var tick = 0

    func body(content: Content) -> some View {
        content
            .bbScreenSubtitle(subtitle)
            .task {
                while !Task.isCancelled {
                    try? await Task.sleep(for: .seconds(30))
                    tick &+= 1
                }
            }
    }

    private var subtitle: String {
        let _ = tick
        let sync = SyncStatusLabel.describe(
            workspace.syncStatus,
            pendingChanges: workspace.pendingChangeCount,
            now: Date(),
            deviceName: SyncStatusLabel.deviceName
        ).text
        guard let summary else { return sync }
        return summary + " · " + sync
    }
}

/// "Needs a next action" and archived state for a project view, in words.
private struct ProjectStatusRow: View {
    let projectID: ProjectID

    @Environment(Workspace.self) private var workspace

    var body: some View {
        if let project = workspace.project(projectID), project.state == .archived {
            Label("Archived project", systemImage: "archivebox")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .listRowSeparator(.hidden)
        } else if let summary = workspace.projects().first(where: { $0.id == projectID }), summary.needsNextAction {
            Label {
                VStack(alignment: .leading, spacing: 2) {
                    Text("This project needs a next action")
                        .font(.subheadline.weight(.semibold))
                    Text("Move one of its tasks to Next actions, or capture the next step.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            } icon: {
                Image(systemName: "exclamationmark.circle")
                    .foregroundStyle(BBColor.warning)
                    .accessibilityHidden(true)
            }
            .accessibilityElement(children: .combine)
            .listRowSeparator(.hidden)
        }
    }
}

/// M-01 "threshold just changed" (FR-039): after a threshold change, one
/// dismissible note says how many tasks ask now and the date before which
/// nothing moves to Someday (the owner park floor Core set). It shows until
/// dismissed for that change, or until that date has passed
/// (`ThresholdChangeNote`); sync keeps the change instant this device set.
private struct ReviewThresholdNote: View {
    @Environment(Workspace.self) private var workspace
    /// The `thresholdChangedAt` (seconds since 1970) whose note was dismissed.
    @AppStorage("review.thresholdNoteDismissedAt") private var dismissedChange: Double = 0

    init() {}

    var body: some View {
        let settings = workspace.state.review.settings
        if workspace.reviewExposed,
            let changedAt = ThresholdChangeNote.change(
                settings: settings, dismissedChange: dismissedChange, now: workspace.reviewNow
            ),
            let floor = settings.ownerParkFloorAt
        {
            HStack(alignment: .firstTextBaseline, spacing: BBSpacing.s3) {
                Text(
                    Self.text(
                        threshold: settings.thresholdDays, asking: workspace.askCount(),
                        floor: ReviewCopy.day(floor, in: .current)
                    )
                )
                .font(BBFont.meta)
                .foregroundStyle(BBColor.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: BBSpacing.s2)
                Button("OK") { dismissedChange = changedAt.timeIntervalSince1970 }
                    .buttonStyle(.borderless)
                    .frame(minWidth: BBMetrics.hitTarget, minHeight: BBMetrics.hitTarget)
                    .accessibilityLabel("Dismiss the threshold note")
            }
            .listRowSeparator(.hidden)
        }
    }

    static func text(threshold: Int, asking: Int, floor: String) -> String {
        let asks = asking == 1 ? "1 task asks for a decision." : "\(asking) tasks ask for a decision."
        return "Your threshold is now \(threshold) days. \(asks) Nothing moves to Someday before \(floor)."
    }
}

/// M-03 "error": decisions the server set aside after sync appear in Sync
/// issues with their Ref (FR-045); Next carries a non-blocking note to them.
private struct DecisionIssuesNote: View {
    @Environment(Workspace.self) private var workspace

    init() {}

    var body: some View {
        let count = workspace.issues.filter { issue in
            if case .decideTask = issue.command { return true }
            return false
        }.count
        let text: String = count == 1 ? "1 decision couldn't be saved" : "\(count) decisions couldn't be saved"
        if count > 0 {
            NavigationLink(value: AppRoute.syncIssues) {
                Label(text, systemImage: "exclamationmark.circle")
                .font(BBFont.meta)
                .foregroundStyle(BBColor.textSecondary)
            }
            .listRowSeparator(.hidden)
        }
    }
}

/// Calm empty-state copy per destination.
private struct EmptyListCopy {
    let title: String
    let message: String
    let systemImage: String

    static let filtered = EmptyListCopy(
        title: "No tasks match these filters",
        message: "Change or clear the filters in list options.",
        systemImage: "line.3.horizontal.decrease.circle"
    )

    /// Archiving took the project off its tasks, and an archived project
    /// takes no new ones, so there is nothing to add here.
    static let archivedProject = EmptyListCopy(
        title: "This project is archived",
        message: "Archived projects are read-only. Its tasks stayed in their lists.",
        systemImage: BBSymbol.archivedProjects
    )

    static func forDestination(_ destination: Destination) -> EmptyListCopy {
        switch destination {
        case .list(let list): forList(list)
        case .agenda:
            EmptyListCopy(
                title: "Nothing due", message: "Tasks with a due date show up here.",
                systemImage: DateView.today.symbolName)
        case .dateView(let view): forDateView(view)
        case .project:
            EmptyListCopy(
                title: "No tasks in this project",
                message: "Tasks you capture from here join this project as next actions.",
                systemImage: "folder")
        case .tag:
            EmptyListCopy(
                title: "No tasks with this tag", message: "Add this tag to a task to see it here.",
                systemImage: "tag")
        case .history(.completed):
            EmptyListCopy(
                title: "Nothing completed yet", message: "Tasks you complete show up here.",
                systemImage: HistoryKind.completed.symbolName)
        case .history(.cancelled):
            EmptyListCopy(
                title: "Nothing cancelled", message: "Tasks you cancel show up here.",
                systemImage: HistoryKind.cancelled.symbolName)
        case .search(let query):
            query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                ? EmptyListCopy(
                    title: "Search your tasks", message: "Search titles and notes across every list.",
                    systemImage: "magnifyingglass")
                : EmptyListCopy(
                    title: "No matches", message: "Try a different word.", systemImage: "magnifyingglass")
        }
    }

    private static func forList(_ list: OpenList) -> EmptyListCopy {
        switch list {
        case .inbox:
            EmptyListCopy(
                title: "Inbox zero", message: "Capture anything on your mind with the bar below.",
                systemImage: list.symbolName)
        case .next:
            EmptyListCopy(
                title: "No next actions", message: "Move a task here once you know its next concrete step.",
                systemImage: list.symbolName)
        case .waiting:
            EmptyListCopy(
                title: "Nothing to wait on", message: "Tasks you hand off or wait for show up here.",
                systemImage: list.symbolName)
        case .someday:
            EmptyListCopy(
                title: "Nothing parked", message: "Keep ideas here that you might act on later.",
                systemImage: list.symbolName)
        }
    }

    private static func forDateView(_ view: DateView) -> EmptyListCopy {
        switch view {
        case .overdue:
            EmptyListCopy(
                title: "Nothing overdue", message: "You're caught up on deadlines.", systemImage: view.symbolName)
        case .today:
            EmptyListCopy(
                title: "Nothing due today", message: "Tasks due today show up here.", systemImage: view.symbolName)
        case .upcoming:
            EmptyListCopy(
                title: "Nothing upcoming", message: "Tasks with a future due date show up here.",
                systemImage: view.symbolName)
        }
    }
}

/// Persists `ListOptions` per destination as JSON in `UserDefaults`.
/// Projects and tags get their own key; searches share one.
enum ListOptionsStore {
    static func key(for destination: Destination) -> String {
        switch destination {
        case .list(let list): "listOptions.list.\(list.rawValue)"
        case .agenda: "listOptions.agenda"
        case .dateView(let view): "listOptions.dateView.\(view.rawValue)"
        case .project(let id): "listOptions.project.\(id.rawValue)"
        case .tag(let id): "listOptions.tag.\(id.rawValue)"
        case .history(let kind): "listOptions.history.\(kind.rawValue)"
        case .search: "listOptions.search"
        }
    }

    /// Next actions groups by project by default; everything else starts flat
    /// in manual order.
    static func defaults(for destination: Destination) -> ListOptions {
        if case .list(.next) = destination { return ListOptions(groupByProject: true) }
        return ListOptions()
    }

    static func decode(_ raw: String) -> ListOptions? {
        try? JSONDecoder().decode(ListOptions.self, from: Data(raw.utf8))
    }

    static func encode(_ options: ListOptions) -> String {
        guard let data = try? JSONEncoder().encode(options) else { return "" }
        return String(decoding: data, as: UTF8.self)
    }
}

extension String {
    /// The stored JSON read and written as `ListOptions`, so
    /// `$storedOptions.listOptions` is a two-way binding built from a key path
    /// (no capturing closures). Unreadable JSON reads as the plain defaults.
    fileprivate var listOptions: ListOptions {
        get { ListOptionsStore.decode(self) ?? ListOptions() }
        set { self = ListOptionsStore.encode(newValue) }
    }
}
