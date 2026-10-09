import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// The Search tab. Search is local — titles and notes of every task on the
/// device, in every state — so it works offline.
struct SearchScreen: View {
    @Environment(Workspace.self) private var workspace
    @State private var query = ""
    @AppStorage(RecentSearches.storageKey) private var recentStorage = ""

    init() {}

    var body: some View {
        content
            .bbScreenTitle("Search")
            .searchable(text: $query, prompt: "Search tasks")
            .onSubmit(of: .search) {
                recentStorage = RecentSearches.adding(query, to: recentStorage)
            }
    }

    @ViewBuilder private var content: some View {
        let text = RecentSearches.normalize(query)
        if text.isEmpty {
            SearchIdleView(
                recents: RecentSearches.decode(recentStorage),
                select: { query = $0 },
                clear: { recentStorage = "" }
            )
        } else {
            SearchResultsView(text: text, sections: Self.ordered(workspace.list(.search(text)).sections))
        }
    }
}

/// Before typing: recent searches, or a short explanation.
private struct SearchIdleView: View {
    let recents: [String]
    let select: (String) -> Void
    let clear: () -> Void

    var body: some View {
        if recents.isEmpty {
            EmptyStateView(
                title: "Search your tasks",
                message: "Find tasks by title or notes, in every list and in history. Search works offline, on this \(ThisDevice.name).",
                systemImage: "magnifyingglass"
            )
        } else {
            List {
                Section {
                    ForEach(recents, id: \.self) { recent in
                        Button {
                            select(recent)
                        } label: {
                            Label(recent, systemImage: "clock.arrow.circlepath")
                                .labelStyle(.bbRow)
                                .foregroundStyle(BBColor.textPrimary)
                        }
                        .accessibilityHint("Searches again")
                    }
                    Button(role: .destructive) {
                        clear()
                    } label: {
                        // The icon keeps its own colour: the row style would
                        // otherwise paint it brand blue next to red text.
                        Label {
                            Text("Clear recent searches")
                        } icon: {
                            Image(systemName: "trash")
                                .foregroundStyle(BBColor.dangerText)
                        }
                        .labelStyle(.bbRow)
                    }
                } header: {
                    BBSectionHeader("Recent searches")
                } footer: {
                    Text("Searches this \(ThisDevice.name)")
                }
            }
            .bbDenseList()
        }
    }
}

private struct SearchResultsView: View {
    let text: String
    let sections: [TaskSection]

    var body: some View {
        if sections.isEmpty {
            EmptyStateView(
                title: "No results",
                message: "Nothing on this \(ThisDevice.name) matches “\(text)”. Try fewer or different words.",
                systemImage: "magnifyingglass"
            )
        } else {
            List {
                ForEach(sections) { section in
                    Section {
                        ForEach(section.tasks) { task in
                            NavigationLink(value: AppRoute.task(task.id)) {
                                TaskRow(task: task, showsProject: true, showsList: true)
                            }
                            .taskActions(task)
                        }
                    } header: {
                        BBSectionHeader(SearchScreen.title(for: section), count: section.tasks.count, countsTasks: true)
                    } footer: {
                        if section.id == sections.last?.id {
                            Text("Searches this \(ThisDevice.name)")
                        }
                    }
                }
            }
            .bbDenseList()
        }
    }
}

// MARK: - Pure helpers (no SwiftUI)

extension SearchScreen {
    /// Non-empty sections, open results first, then completed, then cancelled.
    static func ordered(_ sections: [TaskSection]) -> [TaskSection] {
        let nonEmpty = sections.filter { !$0.tasks.isEmpty }
        let open = nonEmpty.filter { $0.kind != .completed && $0.kind != .cancelled }
        let completed = nonEmpty.filter { $0.kind == .completed }
        let cancelled = nonEmpty.filter { $0.kind == .cancelled }
        return open + completed + cancelled
    }

    static func title(for section: TaskSection) -> String {
        if let title = section.title { return title }
        switch section.kind {
        case .open: return "Open"
        case .list(let list): return list.title
        case .dateView(let view): return view.title
        case .project(let id): return id == nil ? "No project" : "Project"
        case .completed: return "Completed"
        case .cancelled: return "Cancelled"
        }
    }
}

/// Recent searches, newest first, stored as newline-separated text in
/// `UserDefaults` (via `@AppStorage`). Settings clears them on sign-out.
enum RecentSearches {
    static let storageKey = "search.recentQueries"
    static let limit = 8

    static func decode(_ stored: String) -> [String] {
        stored.split(separator: "\n").map(String.init)
    }

    static func adding(_ query: String, to stored: String) -> String {
        let text = normalize(query)
        guard !text.isEmpty else { return stored }
        var items = decode(stored).filter { $0.caseInsensitiveCompare(text) != .orderedSame }
        items.insert(text, at: 0)
        return items.prefix(limit).joined(separator: "\n")
    }

    static func normalize(_ query: String) -> String {
        query.replacingOccurrences(of: "\n", with: " ").trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
