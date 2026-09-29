import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// The Today tab: open tasks with a due date, as Overdue, Today and Upcoming.
struct TodayScreen: View {
    @Environment(Workspace.self) private var workspace
    @Environment(AppRouter.self) private var router

    init() {}

    var body: some View {
        let agenda = workspace.list(.agenda)
        List {
            TodayHeader(day: workspace.today, summary: Self.summary(of: agenda))
                .listRowBackground(Color.clear)
                .listRowSeparator(.hidden)
            if agenda.isEmpty {
                EmptyStateView(
                    title: "Nothing due",
                    message: "Tasks with a due date show up here.",
                    systemImage: "calendar"
                )
                .frame(maxWidth: .infinity)
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
        .navigationTitle("Today")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    router.presentCapture(CaptureContext(list: .next))
                } label: {
                    Label("Add task", systemImage: "plus")
                }
            }
        }
        .refreshable { await workspace.syncNow() }
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

/// Today's date as a flat header above the sections.
private struct TodayHeader: View {
    let day: CalendarDay
    let summary: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(day.startDate(), format: .dateTime.weekday(.wide).day().month(.wide))
                .font(.title3.weight(.semibold))
            if let summary {
                Text(summary)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isHeader)
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
            AgendaSectionHeader(title: title, systemImage: symbolName, count: section.tasks.count)
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

private struct AgendaSectionHeader: View {
    let title: String
    let systemImage: String
    let count: Int

    var body: some View {
        HStack {
            Label(title, systemImage: systemImage)
            Spacer(minLength: 8)
            Text(count, format: .number)
                .monospacedDigit()
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilityText)
        .accessibilityAddTraits(.isHeader)
    }

    private var accessibilityText: String {
        count == 1 ? "\(title), 1 task" : "\(title), \(count) tasks"
    }
}
