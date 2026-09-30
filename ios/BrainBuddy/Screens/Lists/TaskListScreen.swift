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
    /// Read so date views and due chips redraw on a new day.
    @Environment(\.dayChangeCount) private var dayChangeCount
    /// JSON-encoded `ListOptions`, one key per destination (see `ListOptionsStore`).
    /// The default value is the destination's default options, so a fresh
    /// install starts with Next actions grouped by project.
    @AppStorage private var storedOptions: String

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
        taskList(result, options: options)
            .navigationTitle(title)
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
            if !result.isEmpty {
                captionRow(for: result, options: options)
            }
            if case .project(let projectID) = destination {
                ProjectStatusRow(projectID: projectID)
            }
            ForEach(result.sections) { section in
                taskSection(section)
            }
            if !result.isEmpty {
                SyncStatusLabel()
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, minHeight: 44)
                    .listRowSeparator(.hidden)
                    .listRowBackground(Color.clear)
            }
        }
        .listStyle(.plain)
        .overlay {
            if result.isEmpty {
                emptyState(isFiltered: ListOptionsRules.isFiltered(options))
            }
        }
    }

    private func taskSection(_ section: TaskSection) -> some View {
        Section {
            ForEach(section.tasks) { task in
                NavigationLink(value: AppRoute.task(task.id)) {
                    TaskRow(task: task, showsProject: showsProject, showsList: showsList)
                }
                .taskActions(task)
            }
        } header: {
            if let title = section.title {
                Text(title)
            }
        }
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

    private func captionRow(for result: TaskListResult, options: ListOptions) -> some View {
        Text(caption(for: result, options: options))
            .font(.footnote)
            .foregroundStyle(.secondary)
            .listRowSeparator(.hidden)
            .listRowBackground(Color.clear)
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
