import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// One task in a list: completion circle, title, and the metadata (list,
/// project, waiting note, subtasks, due date, priority, tags). The metadata
/// sits trailing on the title's own line when both fit, which makes a one-line
/// task a 44 pt row; otherwise (a long title, large Dynamic Type) it wraps
/// under the title.
///
/// The row is flat content on the brand raised surface; it sets its own
/// `listRowBackground`, so inside a `List` it needs nothing else. Outside a
/// `List`, wrap it with `.padding().bbCard()` for the brand card look.
///
/// For VoiceOver the whole row is one element whose label carries every piece
/// of metadata. Its actions (Complete, Move, Cancel task, Reopen into…) come
/// from the `taskActions(_:)` modifier the lists apply, so they are offered
/// once and reopening always asks for the list.
///
/// Weekly review (spec 020, M-01): while the review is exposed, a Next task
/// that asks for a decision or moves to Someday tomorrow carries that marker
/// (Core's `MarkerStyle`; never "Ageing" in a list), re-classified every
/// minute. Tapping it opens the decision card where the screen offers one
/// (`openDecisionCard`); VoiceOver gets the same as a named action.
struct TaskRow: View {
    let task: TaskRecord
    var showsProject: Bool = true
    var showsList: Bool = false
    var preparedFormulation: RustWorkspaceFormulation? = nil

    @Environment(Workspace.self) private var workspace
    @Environment(\.openDecisionCard) private var openDecisionCard
    /// Read so due chips and "since" dates redraw on a new day.
    @Environment(\.dayChangeCount) private var dayChangeCount
    /// How far the circle's centre sits above the title's first baseline
    /// (about half the x-height), scaled with Dynamic Type.
    @ScaledMetric(relativeTo: .body) private var circleLift: CGFloat = 6

    /// Space above and below the text; the 44 pt completion target sets the
    /// height of a one-line row.
    private static let verticalPadding: CGFloat = 6

    init(task: TaskRecord, showsProject: Bool = true, showsList: Bool = false, preparedFormulation: RustWorkspaceFormulation? = nil) {
        self.task = task
        self.showsProject = showsProject
        self.showsList = showsList
        self.preparedFormulation = preparedFormulation
    }

    var body: some View {
        let _ = dayChangeCount
        Group {
            if task.state == .next && workspace.reviewExposed {
                // Markers follow the clock without waiting for another change.
                TimelineView(.everyMinute) { _ in
                    row
                }
            } else {
                row
            }
        }
        .contentShape(.rect)
        .listRowBackground(BBColor.surfaceRaised)
    }

    /// Title and metadata: side by side when they fit on one line, otherwise
    /// the metadata wraps under the title.
    @ViewBuilder
    private func content(
        details: TaskRowDetails, openDecisionCard: OpenDecisionCardAction?, lift: CGFloat
    ) -> some View {
        if details.hasMetadata {
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .firstTextBaseline, spacing: BBSpacing.s2) {
                    TaskRowTitle(task: task, lineLimit: 2)
                    Spacer(minLength: BBSpacing.s2)
                    TaskRowMetadata(details: details, openDecisionCard: openDecisionCard)
                        .fixedSize()
                        // Chips have no text baseline: centre them on the
                        // title's x-height, as the completion circle is.
                        .alignmentGuide(.firstTextBaseline) { dimensions in
                            dimensions[VerticalAlignment.center] + lift
                        }
                }
                VStack(alignment: .leading, spacing: BBSpacing.s1) {
                    TaskRowTitle(task: task)
                    TaskRowMetadata(details: details, openDecisionCard: openDecisionCard)
                }
            }
        } else {
            TaskRowTitle(task: task)
        }
    }

    private var row: some View {
        let marker = ReviewRowMarker.style(for: task, in: workspace, prepared: preparedFormulation)
        let details = TaskRowDetails(
            task: task, workspace: workspace, showsProject: showsProject, showsList: showsList, marker: marker
        )
        let lift = circleLift
        let opensCard = marker?.opensCard == true ? openDecisionCard : nil
        return HStack(alignment: .firstTextBaseline, spacing: BBSpacing.s2) {
            CompletionControl(task: task)
                .alignmentGuide(.firstTextBaseline) { dimensions in
                    dimensions[VerticalAlignment.center] + lift
                }
            content(details: details, openDecisionCard: opensCard, lift: lift)
                .padding(.vertical, Self.verticalPadding)
            Spacer(minLength: 0)
        }
        .contentShape(.rect)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(details.accessibilityLabel)
        .accessibilityActions {
            if let marker, let opensCard {
                Button(ReviewRowMarker.actionName(marker, title: task.title)) {
                    opensCard.run(task.id)
                }
            }
        }
    }
}

// MARK: - Review marker (spec 020, M-01)

@MainActor
enum ReviewRowMarker {
    /// The list marker for `task`, or nil: only while the review is exposed,
    /// only in Next, and only the states lists show (asks, moves tomorrow).
    /// Before activation Core classifies nothing, so nothing shows (FR-051).
    static func style(for task: TaskRecord, in workspace: Workspace, prepared: RustWorkspaceFormulation?) -> MarkerStyle? {
        guard workspace.reviewExposed, task.state == .next else {
            return nil
        }
        let kind: FormulationClass
        if workspace.isRustSelected {
            guard let prepared else { return nil }
            kind = prepared.classification
        } else {
            guard let legacy = workspace.formulationClass(of: task.id) else { return nil }
            kind = legacy
        }
        let style = MarkerStyle.for(kind)
        return style.showsInLists ? style : nil
    }

    /// "Asks for a decision. Open decision for <title>" (design accessible names).
    static func actionName(_ style: MarkerStyle, title: String) -> String {
        "\(style.text ?? ReviewCopy.markerAsks). Open decision for \(title)"
    }
}

/// The marker as a button with a 44 × 44 pt hit area around the chip, or the
/// chip alone where no decision card can be opened.
private struct ReviewMarkerButton: View {
    let style: MarkerStyle
    let taskID: TaskID
    let openDecisionCard: OpenDecisionCardAction?

    var body: some View {
        if let chip = ReviewMarkerChip(style) {
            if let openDecisionCard {
                Button {
                    openDecisionCard.run(taskID)
                } label: {
                    chip
                }
                .buttonStyle(.borderless)
                // The chip is about 22 pt tall; its hit area reaches 44 × 44 pt
                // without making the row taller (design "Tap targets").
                .contentShape(.interaction, Rectangle().inset(by: -11))
            } else {
                chip
            }
        }
    }
}

// MARK: - Title

private struct TaskRowTitle: View {
    let task: TaskRecord
    var lineLimit: Int = 3

    var body: some View {
        Text(task.title)
            .font(BBFont.rowTitle)
            .foregroundStyle(titleColor)
            .strikethrough(task.state.isTerminal, color: titleColor)
            .lineLimit(lineLimit)
            .multilineTextAlignment(.leading)
    }

    private var titleColor: Color {
        switch task.state {
        case .completed: BBColor.textTertiary
        case .cancelled: BBColor.textPlaceholder
        default: BBColor.textPrimary
        }
    }
}

// MARK: - Metadata

private struct TaskRowMetadata: View {
    let details: TaskRowDetails
    let openDecisionCard: OpenDecisionCardAction?

    var body: some View {
        BBFlowLayout(spacing: 6, lineSpacing: BBSpacing.s1) {
            if let marker = details.marker {
                ReviewMarkerButton(style: marker, taskID: details.task.id, openDecisionCard: openDecisionCard)
            }
            if let project = details.project {
                ProjectLabel(name: project.name, color: project.color)
            }
            if !details.textParts.isEmpty {
                Text(details.joinedText)
                    .font(BBFont.meta)
                    .foregroundStyle(BBColor.textTertiary)
                    .lineLimit(2)
            }
            if let progress = details.subtaskProgress {
                Label(progress, systemImage: BBSymbol.subtasks)
                    .labelStyle(.titleAndIcon)
                    .font(BBFont.meta)
                    .foregroundStyle(BBColor.textTertiary)
            }
            if let due = details.task.dueDate {
                DueChip(day: due, today: details.today, isDeadlineActive: details.task.isOpen)
            }
            PriorityBadge(priority: details.task.priority)
            ForEach(details.tagNames, id: \.self) { name in
                TagPill(name: name)
            }
        }
    }
}

/// Everything the row shows, resolved once per render from the workspace.
@MainActor
private struct TaskRowDetails {
    let task: TaskRecord
    let today: CalendarDay
    let project: ProjectRecord?
    let tagNames: [String]
    /// List name and waiting note, joined with " · ".
    let textParts: [String]
    /// "2/5" when the task has subtasks.
    let subtaskProgress: String?
    /// The weekly review's list marker (M-01), if any.
    let marker: MarkerStyle?
    private let spokenParts: [String]

    init(task: TaskRecord, workspace: Workspace, showsProject: Bool, showsList: Bool, marker: MarkerStyle? = nil) {
        let today = workspace.today
        let project = showsProject ? task.projectID.flatMap { workspace.project($0) } : nil
        let tagNames = task.tagIDs.compactMap { workspace.tag($0) }.filter { $0.state == .active }.map(\.name)
        let listName = showsList && task.state != .waiting ? Self.listName(for: task.state) : nil
        let waiting = Self.waitingParts(for: task, today: today)
        let counted = task.subtasks.filter { $0.state != .cancelled }
        let done = counted.filter { $0.state == .completed }.count

        self.task = task
        self.today = today
        self.project = project
        self.tagNames = tagNames
        self.textParts = [listName].compactMap { $0 } + waiting.visible
        self.subtaskProgress = counted.isEmpty ? nil : "\(done)/\(counted.count)"
        self.marker = marker

        var spoken: [String] = [task.title]
        if let markerText = marker?.text { spoken.append(markerText) }
        if task.state.isTerminal { spoken.append(Self.listName(for: task.state)) }
        if let listName { spoken.append(listName) }
        if let project { spoken.append("Project \(project.name)") }
        if let spokenWaiting = waiting.spoken { spoken.append(spokenWaiting) }
        if !counted.isEmpty { spoken.append("\(done) of \(counted.count) subtasks done") }
        if let due = task.dueDate {
            spoken.append(DueChip.accessibilityText(for: due, today: today, isDeadlineActive: task.isOpen))
        }
        if task.priority != .none { spoken.append("\(task.priority.title) priority") }
        if !tagNames.isEmpty {
            spoken.append((tagNames.count == 1 ? "Tag " : "Tags ") + tagNames.joined(separator: ", "))
        }
        spokenParts = spoken
    }

    /// The text metadata, continuing the " · " chain after the project label.
    var joinedText: String {
        let text = textParts.joined(separator: " · ")
        return project == nil ? text : "· " + text
    }

    var hasMetadata: Bool {
        marker != nil || project != nil || !textParts.isEmpty || subtaskProgress != nil || task.dueDate != nil
            || task.priority != .none || !tagNames.isEmpty
    }

    var accessibilityLabel: String { spokenParts.joined(separator: ", ") }

    static func listName(for state: TaskState) -> String {
        if let list = state.openList { return list.title }
        return state == .completed ? HistoryKind.completed.title : HistoryKind.cancelled.title
    }

    /// "Waiting for Sam" and "since Sep 22", plus the spoken form.
    static func waitingParts(for task: TaskRecord, today: CalendarDay) -> (visible: [String], spoken: String?) {
        guard task.state == .waiting,
            let who = task.waitingFor?.trimmingCharacters(in: .whitespacesAndNewlines), !who.isEmpty
        else { return ([], nil) }
        let lead = "Waiting for \(who)"
        guard let since = task.waitingSince else { return ([lead], lead) }
        let sinceText = sinceDescription(since, today: today)
        return ([lead, "since \(sinceText)"], "\(lead) since \(sinceText)")
    }

    static func sinceDescription(_ date: Date, today: CalendarDay) -> String {
        let day = CalendarDay(date: date)
        switch BBDayMath.offset(from: today, to: day) {
        case 0: return "today"
        case -1: return "yesterday"
        default:
            let style: Date.FormatStyle = day.year == today.year
                ? .dateTime.month(.abbreviated).day()
                : .dateTime.month(.abbreviated).day().year()
            return date.formatted(style)
        }
    }
}

// MARK: - Completion control

/// The completion target, at least 44 pt. Open tasks complete on tap: the circle fills
/// on the brand curve, then the task completes (under 600 ms in total; with
/// Reduce Motion the fill is instant and the row does not slide). Finished
/// tasks show a static filled check or cross.
private struct CompletionControl: View {
    let task: TaskRecord

    @Environment(Workspace.self) private var workspace
    @Environment(ToastCenter.self) private var toasts
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var isCompleting = false
    @State private var isSavingCompletion = false
    @State private var completionEditorID = UUID().uuidString

    var body: some View {
        if task.isOpen {
            Button(action: complete) {
                CompletionCircle(style: isCompleting ? .completed : .open)
                    .frame(minWidth: BBMetrics.hitTarget, minHeight: BBMetrics.hitTarget)
                    .contentShape(.rect)
            }
            .buttonStyle(.borderless)
            .disabled(isCompleting)
            .accessibilityLabel("Complete")
        } else {
            CompletionCircle(style: task.state == .completed ? .completed : .cancelled)
                .frame(minWidth: BBMetrics.hitTarget, minHeight: BBMetrics.hitTarget)
                .accessibilityHidden(true)
        }
    }

    private func complete() {
        guard !isCompleting, !isSavingCompletion else { return }
        isSavingCompletion = true
        let task = task
        let workspace = workspace
        let toasts = toasts
        let pause: Duration = reduceMotion ? .milliseconds(150) : .milliseconds(300)
        Task {
            try? await Task.sleep(for: pause)
            let completed = await TaskCommandRunner.complete(task, workspace: workspace, toasts: toasts, editorID: completionEditorID)
            if completed {
                withAnimation(BBMotion.animation(.base, reduceMotion: reduceMotion)) { isCompleting = true }
            }
            isSavingCompletion = false
        }
    }
}

private struct CompletionCircle: View {
    enum Style {
        case open, completed, cancelled
    }

    let style: Style
    @ScaledMetric(relativeTo: .body) private var scaledDiameter: CGFloat = BBMetrics.completionCircle

    /// Grows with Dynamic Type up to a cap, so it stays inside its 44 pt target.
    private var diameter: CGFloat { min(scaledDiameter, BBMetrics.completionCircleMax) }

    var body: some View {
        ZStack {
            Circle()
                .fill(fill)
            Circle()
                .strokeBorder(stroke, lineWidth: 1.5)
            if let symbol {
                Image(systemName: symbol)
                    .font(.system(size: diameter * 0.45, weight: .bold))
                    .foregroundStyle(style == .completed ? BBColor.onBrand : BBColor.textTertiary)
                    .transition(.opacity)
            }
        }
        .frame(width: diameter, height: diameter)
    }

    private var fill: Color {
        switch style {
        case .open: BBColor.surfaceRaised
        case .completed: BBColor.brandFill
        case .cancelled: BBColor.surfaceSunken
        }
    }

    private var stroke: Color {
        switch style {
        case .open: BBColor.controlStroke
        case .completed: BBColor.brandFill
        case .cancelled: BBColor.hairline
        }
    }

    private var symbol: String? {
        switch style {
        case .open: nil
        case .completed: "checkmark"
        case .cancelled: "xmark"
        }
    }
}
