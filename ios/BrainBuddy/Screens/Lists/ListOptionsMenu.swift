import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// Sort, grouping, history and filter options for one task list. Only the
/// options that mean something for `destination` are offered: Inbox is always
/// projectless and a project view is one project, so neither groups by
/// project; history lists already are the completed or cancelled tasks.
struct ListOptionsMenu: View {
    @Binding private var options: ListOptions
    private let destination: Destination

    @Environment(Workspace.self) private var workspace

    init(options: Binding<ListOptions>, destination: Destination) {
        _options = options
        self.destination = destination
    }

    var body: some View {
        Menu {
            Picker(selection: $options.sort) {
                ForEach(TaskSort.allCases, id: \.self) { sort in
                    Text(sort.title).tag(sort)
                }
            } label: {
                Label("Sort by", systemImage: "arrow.up.arrow.down")
            }
            .pickerStyle(.menu)

            if ListOptionsRules.allowsGrouping(destination) {
                Toggle(isOn: $options.groupByProject) {
                    Label("Group by project", systemImage: "folder")
                }
            }

            if ListOptionsRules.allowsHistory(destination) {
                Section {
                    Toggle(isOn: $options.showCompleted) {
                        Label("Show completed", systemImage: HistoryKind.completed.symbolName)
                    }
                    Toggle(isOn: $options.showCancelled) {
                        Label("Show cancelled", systemImage: HistoryKind.cancelled.symbolName)
                    }
                }
            }

            Section {
                priorityMenu
                if ListOptionsRules.allowsTagFilter(destination) {
                    tagPicker
                }
                if ListOptionsRules.isFiltered(options) {
                    Button {
                        options.priorities = []
                        options.tagFilter = nil
                    } label: {
                        Label("Clear filters", systemImage: "xmark.circle")
                    }
                }
            }
        } label: {
            Label(
                "List options",
                systemImage: ListOptionsRules.isFiltered(options)
                    ? "line.3.horizontal.decrease.circle.fill" : "line.3.horizontal.decrease.circle"
            )
        }
        .accessibilityLabel("List options")
        .accessibilityValue(ListOptionsRules.isFiltered(options) ? "Filters on" : "")
        .task { if ListOptionsRules.allowsTagFilter(destination) { await workspace.prepareTags() } }
    }

    private var priorityMenu: some View {
        Menu {
            Toggle(TaskPriority.high.title, isOn: $options.includesHighPriority)
            Toggle(TaskPriority.medium.title, isOn: $options.includesMediumPriority)
            Toggle(TaskPriority.low.title, isOn: $options.includesLowPriority)
            Toggle(TaskPriority.none.title, isOn: $options.includesNoPriority)
            if !options.priorities.isEmpty {
                Button("Any priority") { options.priorities = [] }
            }
        } label: {
            Label(priorityMenuTitle, systemImage: "flag")
        }
    }

    private var tagPicker: some View {
        let page = workspace.tagsPageState()
        return Menu {
            if page.readiness != .ready {
                Button("Retry loading tags") { Task { await workspace.prepareTags() } }
            }
            Picker(selection: $options.tagFilter) {
                Text("Any tag").tag(TagID?.none)
                ForEach(workspace.tags()) { summary in
                    Text(summary.tag.name).tag(Optional(summary.id))
                }
            }
            .pickerStyle(.menu)
            if page.hasPrevious {
                Button("Previous tags") { Task { await workspace.previousTagsPage() } }
            }
            if page.hasNext {
                Button("More tags") { Task { await workspace.nextTagsPage() } }
            }
        } label: {
            Label("Tag", systemImage: "tag")
        }
    }

    private var priorityMenuTitle: String {
        let chosen = Self.priorityOrder.filter { options.priorities.contains($0) }
        guard !chosen.isEmpty else { return "Priority" }
        return "Priority: " + chosen.map(\.title).joined(separator: ", ")
    }

    private static let priorityOrder: [TaskPriority] = [.high, .medium, .low, .none]
}

/// Per-priority switches over `priorities`, so each menu toggle binds through
/// a key path (`$options.includesHighPriority`) instead of a capturing closure.
extension ListOptions {
    fileprivate var includesHighPriority: Bool {
        get { priorities.contains(.high) }
        set { setPriority(.high, included: newValue) }
    }

    fileprivate var includesMediumPriority: Bool {
        get { priorities.contains(.medium) }
        set { setPriority(.medium, included: newValue) }
    }

    fileprivate var includesLowPriority: Bool {
        get { priorities.contains(.low) }
        set { setPriority(.low, included: newValue) }
    }

    fileprivate var includesNoPriority: Bool {
        get { priorities.contains(TaskPriority.none) }
        set { setPriority(TaskPriority.none, included: newValue) }
    }

    fileprivate mutating func setPriority(_ priority: TaskPriority, included: Bool) {
        if included {
            priorities.insert(priority)
        } else {
            priorities.remove(priority)
        }
    }
}

/// Which options apply to which destination, shared by the menu and the list
/// screen so a hidden option can never narrow a list.
enum ListOptionsRules {
    static func allowsGrouping(_ destination: Destination) -> Bool {
        switch destination {
        case .list(let list): list != .inbox
        case .project: false
        case .agenda, .dateView, .tag, .history, .search: true
        }
    }

    static func allowsHistory(_ destination: Destination) -> Bool {
        switch destination {
        case .list, .project, .tag: true
        case .agenda, .dateView, .history, .search: false
        }
    }

    static func allowsTagFilter(_ destination: Destination) -> Bool {
        if case .tag = destination { return false }
        return true
    }

    static func isFiltered(_ options: ListOptions) -> Bool {
        !options.priorities.isEmpty || options.tagFilter != nil
    }
}
