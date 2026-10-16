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
                if ListOptionsRules.allowsTagFilter(destination) {
                    tagPicker
                }
                if ListOptionsRules.isFiltered(options) {
                    Button {
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

    private var tagPicker: some View {
        let page = workspace.tagsPageState()
        return Menu {
            if page.readiness != .ready {
                Button("Retry loading tags") { Task { await workspace.prepareTags() } }
            }
            Picker("Tag", selection: $options.tagFilter) {
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
        options.tagFilter != nil
    }
}
