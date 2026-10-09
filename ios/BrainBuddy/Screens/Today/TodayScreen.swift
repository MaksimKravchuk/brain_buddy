import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// The Today tab: open tasks with a due date, as Overdue, Today and Upcoming.
/// It redraws at midnight (and when the clock or time zone changes), so
/// yesterday's "Today" moves to Overdue without another change.
struct TodayScreen: View {
    @Environment(Workspace.self) private var workspace
    @Environment(AppRouter.self) private var router
    @Environment(\.dayChangeCount) private var dayChangeCount

    init() {}

    var body: some View {
        let _ = dayChangeCount
        let agenda = workspace.list(.agenda)
        List {
            if agenda.isEmpty {
                EmptyStateView(
                    title: "Nothing due",
                    message: "Tasks with a due date show up here.",
                    systemImage: "calendar"
                )
                .frame(maxWidth: .infinity)
                .listRowInsets(EdgeInsets())
                .listRowBackground(Color.clear)
                .listRowSeparator(.hidden)
            } else {
                ForEach(agenda.sections) { section in
                    if !section.tasks.isEmpty {
                        AgendaSection(section: section)
                    }
                }
            }
        }
        .listStyle(.plain)
        .bbDenseList()
        .bbScreenTitle("Today")
        .bbScreenSubtitle(subtitle(summary: Self.summary(of: agenda)))
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    router.presentCapture(CaptureContext(list: .next, dueDate: workspace.today))
                } label: {
                    Label("Add task due today", systemImage: "plus")
                }
            }
        }
        .refreshable { await workspace.syncNow() }
    }

    /// "Friday, October 9 · 2 overdue · 3 due today": the date, then the
    /// summary when something is due.
    private func subtitle(summary: String?) -> String {
        let date = workspace.today.startDate().formatted(.dateTime.weekday(.wide).month(.wide).day())
        guard let summary else { return date }
        return "\(date) · \(summary)"
    }

    /// "2 overdue · 3 due today", or nil when nothing is due.
    static func summary(of agenda: TaskListResult) -> String? {
        var parts: [String] = []
        for section in agenda.sections where !section.tasks.isEmpty {
            guard case .dateView(let view) = section.kind else { continue }
            let count = section.tasks.count
            switch view {
            case .overdue: parts.append("\(count) overdue")
            case .today: parts.append("\(count) due today")
            case .upcoming: parts.append("\(count) upcoming")
            }
        }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }
}

/// One of Overdue, Today or Upcoming.
private struct AgendaSection: View {
    let section: TaskSection

    var body: some View {
        Section {
            ForEach(section.tasks) { task in
                NavigationLink(value: AppRoute.task(task.id)) {
                    TaskRow(task: task, showsProject: true, showsList: true)
                }
                .taskActions(task)
            }
        } header: {
            BBSectionHeader(
                title,
                count: section.tasks.count,
                systemImage: symbolName,
                tint: dateView == .overdue ? BBColor.dueText : nil
            )
        }
    }

    private var dateView: DateView? {
        switch section.kind {
        case .dateView(let view): return view
        default: return nil
        }
    }

    private var title: String { section.title ?? dateView?.title ?? "Due" }
    private var symbolName: String { dateView?.symbolName ?? "calendar" }
}
