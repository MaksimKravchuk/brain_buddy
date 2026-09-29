import AppIntents
import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI
import WidgetKit

// MARK: - Configuration

/// Which list the widget shows. Today puts overdue tasks first, as the Today
/// tab does, so nothing slips past its date unseen.
enum TaskListChoice: String, AppEnum, CaseIterable {
    case next, today

    static let typeDisplayRepresentation = TypeDisplayRepresentation(name: "List")

    static let caseDisplayRepresentations: [TaskListChoice: DisplayRepresentation] = [
        .next: DisplayRepresentation(title: "Next actions", image: .init(systemName: "checklist")),
        .today: DisplayRepresentation(title: "Today", image: .init(systemName: "calendar")),
    ]

    var name: String {
        switch self {
        case .next: OpenList.next.title
        case .today: DateView.today.title
        }
    }

    var systemImage: String {
        switch self {
        case .next: "checklist"
        case .today: "calendar"
        }
    }

    var emptyTitle: String {
        switch self {
        case .next: "No next actions"
        case .today: "Nothing due today"
        }
    }

    var emptyHint: String {
        switch self {
        case .next: "Process your inbox to choose what comes next."
        case .today: "Tasks show up here on their due date."
        }
    }

    func countDescription(_ count: Int) -> String {
        switch self {
        case .next: count == 1 ? "1 next action" : "\(count) next actions"
        case .today: "\(count) due today or earlier"
        }
    }
}

struct NextActionsConfigurationIntent: WidgetConfigurationIntent {
    static let title: LocalizedStringResource = "Choose a list"

    static let description = IntentDescription("Show your next actions or what's due today.")

    @Parameter(title: "List", default: .next)
    var list: TaskListChoice

    init() {}

    init(list: TaskListChoice) {
        self.list = list
    }
}

// MARK: - Timeline

/// A task row, copied out of the store so the entry stays small and `Sendable`.
struct WidgetTask: Identifiable, Hashable, Sendable {
    let id: String
    let title: String
    let listName: String
    let dueDate: CalendarDay?

    init(id: String, title: String, listName: String, dueDate: CalendarDay?) {
        self.id = id
        self.title = title
        self.listName = listName
        self.dueDate = dueDate
    }

    init(record: TaskRecord) {
        self.init(
            id: record.id.rawValue,
            title: record.title,
            listName: TaskEntity.listName(for: record.state),
            dueDate: record.dueDate
        )
    }

    /// What the completion button sends; the intent looks the task up by id.
    var entity: TaskEntity {
        TaskEntity(id: id, title: title, listName: listName, dueDate: dueDate?.startDate())
    }
}

struct NextActionsEntry: TimelineEntry, Sendable {
    let date: Date
    let choice: TaskListChoice
    /// Up to `NextActionsLoader.rowLimit` open tasks, in list order.
    let tasks: [WidgetTask]
    /// Every open task in the chosen list, shown or not.
    let totalCount: Int
    /// Projectless Inbox tasks, as on the app's Inbox badge.
    let inboxCount: Int
    /// False when the store could not be read (for example before the first unlock).
    let isAvailable: Bool

    var today: CalendarDay { CalendarDay(date: date) }

    static func unavailable(_ choice: TaskListChoice, at date: Date) -> NextActionsEntry {
        NextActionsEntry(date: date, choice: choice, tasks: [], totalCount: 0, inboxCount: 0, isAvailable: false)
    }

    /// Placeholder and widget gallery content.
    static func sample(_ choice: TaskListChoice, at date: Date = Date()) -> NextActionsEntry {
        let today = CalendarDay(date: date)
        let list = OpenList.next.title
        let isToday = choice == .today
        let tasks = [
            WidgetTask(id: "sample-1", title: "Call Sam about the lease", listName: list, dueDate: today),
            WidgetTask(
                id: "sample-2", title: "Draft the project brief", listName: list,
                dueDate: isToday ? today : today.adding(days: 1)
            ),
            WidgetTask(id: "sample-3", title: "Book a dentist appointment", listName: list, dueDate: isToday ? today : nil),
            WidgetTask(id: "sample-4", title: "Order printer paper", listName: list, dueDate: isToday ? today : nil),
        ]
        return NextActionsEntry(
            date: date, choice: choice, tasks: tasks, totalCount: isToday ? 4 : 7, inboxCount: 3, isAvailable: true
        )
    }
}

/// A row's due label: relative near today, a short date otherwise.
struct DueLabel: Hashable, Sendable {
    let text: String
    /// Due today or overdue.
    let isUrgent: Bool

    init(due: CalendarDay, today: CalendarDay) {
        isUrgent = due <= today
        if due == today {
            text = "Today"
        } else if due == today.adding(days: 1) {
            text = "Tomorrow"
        } else if due == today.adding(days: -1) {
            text = "Yesterday"
        } else {
            text = due.startDate().formatted(.dateTime.day().month(.abbreviated))
        }
    }
}

/// Refresh policy for every widget in the extension.
enum WidgetSchedule {
    /// Date views change at midnight. Writes from the app, App Intents and
    /// widget buttons reload timelines sooner through `WidgetCenter`.
    static func nextMidnight(after date: Date, calendar: Calendar = .current) -> Date {
        let startOfToday = calendar.startOfDay(for: date)
        return calendar.date(byAdding: .day, value: 1, to: startOfToday) ?? date.addingTimeInterval(24 * 60 * 60)
    }
}

/// Reads the shared store once per timeline, copies what the widget shows and
/// lets the workspace go. Never syncs.
@MainActor
enum NextActionsLoader {
    /// The most rows any family shows (large).
    static let rowLimit = 8

    static func load(_ choice: TaskListChoice, at date: Date = Date()) async -> NextActionsEntry {
        let workspace = await SharedWorkspace.make()
        guard workspace.isLoaded, workspace.loadError == nil else {
            return .unavailable(choice, at: date)
        }
        let records: [TaskRecord]
        switch choice {
        case .next:
            records = openTasks(in: workspace.list(.list(.next)))
        case .today:
            records = openTasks(in: workspace.list(.dateView(.overdue)))
                + openTasks(in: workspace.list(.dateView(.today)))
        }
        return NextActionsEntry(
            date: date,
            choice: choice,
            tasks: records.prefix(rowLimit).map(WidgetTask.init(record:)),
            totalCount: records.count,
            inboxCount: workspace.counts().inbox,
            isAvailable: true
        )
    }

    private static func openTasks(in result: TaskListResult) -> [TaskRecord] {
        result.sections.flatMap(\.tasks).filter(\.isOpen)
    }
}

struct NextActionsProvider: AppIntentTimelineProvider {
    func placeholder(in context: Context) -> NextActionsEntry {
        .sample(.next)
    }

    func snapshot(for configuration: NextActionsConfigurationIntent, in context: Context) async -> NextActionsEntry {
        if context.isPreview {
            return .sample(configuration.list)
        }
        return await NextActionsLoader.load(configuration.list)
    }

    func timeline(
        for configuration: NextActionsConfigurationIntent, in context: Context
    ) async -> Timeline<NextActionsEntry> {
        let entry = await NextActionsLoader.load(configuration.list)
        return Timeline(entries: [entry], policy: .after(WidgetSchedule.nextMidnight(after: entry.date)))
    }
}

// MARK: - Widget

struct NextActionsWidget: Widget {
    static let kind = "com.brainbuddy.ios.widget.next-actions"

    var body: some WidgetConfiguration {
        AppIntentConfiguration(
            kind: Self.kind,
            intent: NextActionsConfigurationIntent.self,
            provider: NextActionsProvider()
        ) { entry in
            NextActionsWidgetView(entry: entry)
        }
        .configurationDisplayName("Next actions")
        .description("Your next actions or what's due today. Complete tasks without opening the app.")
        .supportedFamilies([.systemSmall, .systemMedium, .systemLarge])
    }
}

struct NextActionsWidgetView: View {
    let entry: NextActionsEntry

    @Environment(\.widgetFamily) private var family
    @Environment(\.colorScheme) private var colorScheme

    private var palette: WidgetPalette { WidgetPalette(colorScheme: colorScheme) }

    /// Rows that fit each family, down to the 4.7-inch iPhone.
    private var rowLimit: Int {
        switch family {
        case .systemSmall: 1
        case .systemMedium: 3
        default: NextActionsLoader.rowLimit
        }
    }

    var body: some View {
        Group {
            if !entry.isAvailable {
                WidgetUnavailableView(palette: palette)
            } else if family == .systemSmall {
                smallBody
            } else {
                listBody
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .containerBackground(palette.background, for: .widget)
    }

    /// Count and the first task. A small widget is one tap target, so it
    /// opens the app; the row's completion button still works in place.
    private var smallBody: some View {
        VStack(alignment: .leading, spacing: 2) {
            WidgetListHeader(choice: entry.choice, palette: palette)
            Text(entry.totalCount, format: .number)
                .font(.system(size: 40, weight: .semibold))
                .monospacedDigit()
                .foregroundStyle(palette.primaryText)
                .contentTransition(.numericText())
                .accessibilityLabel(entry.choice.countDescription(entry.totalCount))
            Spacer(minLength: 0)
            if let first = entry.tasks.first {
                WidgetTaskRow(task: first, due: nil, titleLineLimit: 2, palette: palette)
            } else {
                Text(entry.choice.emptyTitle)
                    .font(.footnote)
                    .foregroundStyle(palette.secondaryText)
            }
        }
    }

    private var listBody: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                WidgetListHeader(choice: entry.choice, palette: palette)
                Text(entry.totalCount, format: .number)
                    .font(.caption.weight(.semibold))
                    .monospacedDigit()
                    .foregroundStyle(palette.secondaryText)
                    .accessibilityLabel(entry.choice.countDescription(entry.totalCount))
                Spacer(minLength: 4)
                if entry.inboxCount > 0 {
                    InboxBadge(count: entry.inboxCount, palette: palette)
                }
                CaptureLink(palette: palette)
            }
            if entry.tasks.isEmpty {
                WidgetEmptyState(title: entry.choice.emptyTitle, hint: entry.choice.emptyHint, palette: palette)
            } else {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(entry.tasks.prefix(rowLimit)) { task in
                        WidgetTaskRow(task: task, due: dueLabel(for: task), palette: palette)
                    }
                }
                Spacer(minLength: 0)
                if family == .systemLarge, entry.totalCount > shownCount {
                    Text("\(entry.totalCount - shownCount) more")
                        .font(.caption)
                        .foregroundStyle(palette.secondaryText)
                }
            }
        }
    }

    private var shownCount: Int { min(entry.tasks.count, rowLimit) }

    /// Today rows only flag overdue dates; every other Today task is due today.
    private func dueLabel(for task: WidgetTask) -> DueLabel? {
        guard let due = task.dueDate else { return nil }
        if entry.choice == .today, due == entry.today { return nil }
        return DueLabel(due: due, today: entry.today)
    }
}

// MARK: - Components

/// One task: a completion button that works without opening the app, the
/// title, and the due date when it matters.
struct WidgetTaskRow: View {
    let task: WidgetTask
    let due: DueLabel?
    var titleLineLimit = 1
    let palette: WidgetPalette

    var body: some View {
        HStack(alignment: titleLineLimit > 1 ? .top : .center, spacing: 8) {
            Button(intent: CompleteTaskIntent(task: task.entity)) {
                Image(systemName: "circle")
                    .font(.body)
                    .foregroundStyle(palette.secondaryText)
                    .frame(width: 24, height: 24)
                    .contentShape(Circle())
            }
            .buttonStyle(.plain)
            .widgetAccentable()
            .accessibilityLabel("Complete \(task.title)")

            Text(task.title)
                .font(.subheadline)
                .foregroundStyle(palette.primaryText)
                .lineLimit(titleLineLimit)
                .privacySensitive()

            Spacer(minLength: 4)

            if let due {
                Text(due.text)
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(due.isUrgent ? palette.due : palette.secondaryText)
                    .lineLimit(1)
            }
        }
    }
}

struct WidgetListHeader: View {
    let choice: TaskListChoice
    let palette: WidgetPalette

    var body: some View {
        Label {
            Text(choice.name)
                .foregroundStyle(palette.primaryText)
        } icon: {
            Image(systemName: choice.systemImage)
                .foregroundStyle(palette.accent)
                .widgetAccentable()
        }
        .font(.caption.weight(.semibold))
        .lineLimit(1)
    }
}

/// Inbox count in the brand colour, as on the app's Inbox badge.
struct InboxBadge: View {
    let count: Int
    let palette: WidgetPalette

    private var accessibilityText: String {
        count == 1 ? "1 item in Inbox" : "\(count) items in Inbox"
    }

    var body: some View {
        Label {
            Text(count, format: .number)
                .monospacedDigit()
        } icon: {
            Image(systemName: "tray")
        }
        .labelStyle(.titleAndIcon)
        .font(.caption2.weight(.semibold))
        .foregroundStyle(palette.accentText)
        .padding(.horizontal, 7)
        .padding(.vertical, 3)
        .background(Capsule().fill(palette.accent.opacity(0.14)))
        .widgetAccentable()
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilityText)
    }
}

/// Opens the app on the capture sheet (`brainbuddy://capture`).
struct CaptureLink: View {
    let palette: WidgetPalette

    @Environment(\.widgetRenderingMode) private var renderingMode

    var body: some View {
        Link(destination: SharedConstants.captureURL) {
            symbol
                .font(.title2)
                .frame(width: 30, height: 30)
                .contentShape(Circle())
        }
        .accessibilityLabel("Capture")
    }

    @ViewBuilder private var symbol: some View {
        if renderingMode == .fullColor {
            Image(systemName: "plus.circle.fill")
                .symbolRenderingMode(.palette)
                .foregroundStyle(palette.onAccent, palette.accent)
        } else {
            // Tinted, clear and Lock Screen rendering recolour the symbol;
            // the plus stays cut out of the filled circle.
            Image(systemName: "plus.circle.fill")
                .widgetAccentable()
        }
    }
}

struct WidgetEmptyState: View {
    let title: String
    let hint: String
    let palette: WidgetPalette

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(palette.primaryText)
            Text(hint)
                .font(.caption)
                .foregroundStyle(palette.secondaryText)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }
}

/// Shown when the store can't be read yet, typically before the first unlock
/// after a restart. Tapping the widget opens the app.
struct WidgetUnavailableView: View {
    let palette: WidgetPalette

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Image(systemName: "tray")
                .font(.title3)
                .foregroundStyle(palette.accent)
                .widgetAccentable()
            Spacer(minLength: 0)
            Text("Open Brain Buddy")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(palette.primaryText)
            Text("Your lists show here once the app can read them.")
                .font(.caption)
                .foregroundStyle(palette.secondaryText)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }
}
