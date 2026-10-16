import BrainBuddyCore
import BrainBuddyDesign
import BrainBuddyWorkspace
import SwiftUI

/// One task in a list, as a Carry On step row: the mark (which is also the
/// completion control), the title and, under it, one metadata line of
/// text-secondary words joined with " · " (project, list, waiting note,
/// subtasks, due date, tags). A task due today shows that in the due colour and
/// an overdue one in the overdue colour; the words say it too. The line wraps
/// under large Dynamic Type.
///
/// The row is content only. Inside a `List`, apply `bbCardRow()` to it (outside
/// the `TaskOpenButton`) for the card: surface, radius, padding and no divider.
/// Outside a `List`, wrap it with `.padding().bbCard()`.
///
/// `showsMark: false` is the Inbox, whose rows are the raw text alone;
/// `isCurrent` marks the project's one current next action.
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
    var showsMark: Bool = true
    var isCurrent: Bool = false

    @Environment(Workspace.self) private var workspace
    @Environment(\.openDecisionCard) private var openDecisionCard
    /// Read so due dates and "since" dates redraw on a new day.
    @Environment(\.dayChangeCount) private var dayChangeCount

    init(
        task: TaskRecord, showsProject: Bool = true, showsList: Bool = false,
        preparedFormulation: RustWorkspaceFormulation? = nil, showsMark: Bool = true, isCurrent: Bool = false
    ) {
        self.task = task
        self.showsProject = showsProject
        self.showsList = showsList
        self.preparedFormulation = preparedFormulation
        self.showsMark = showsMark
        self.isCurrent = isCurrent
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
    }

    /// The mark: waiting for tasks in Waiting for, done for completed ones, the
    /// current step when the screen says so, otherwise an open ring. A cancelled
    /// task keeps the open ring (it is not a step taken); its title is struck.
    private var markStatus: CarryOnStepRow.Status {
        switch task.state {
        case .completed: .done
        case .waiting: .waiting
        case .cancelled: .open
        case .inbox, .next, .someday: isCurrent ? .current : .open
        }
    }

    private var row: some View {
        let marker = ReviewRowMarker.style(for: task, in: workspace, prepared: preparedFormulation)
        let details = TaskRowDetails(
            task: task, workspace: workspace, showsProject: showsProject, showsList: showsList, marker: marker
        )
        let opensCard = marker?.opensCard == true ? openDecisionCard : nil
        return HStack(alignment: .center, spacing: CGFloat(CarryOnLayout.Row.gap)) {
            if showsMark {
                CompletionControl(task: task, status: markStatus)
            }
            VStack(alignment: .leading, spacing: CGFloat(CarryOnLayout.Row.metaGap)) {
                TaskRowTitle(task: task, isCurrent: isCurrent)
                if details.hasMetadata {
                    TaskRowMetadata(details: details, openDecisionCard: opensCard)
                }
            }
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

/// The title in the step-row type: 17 pt, semibold for the current step, struck
/// through in step-text-done once finished, text-secondary while waiting.
private struct TaskRowTitle: View {
    let task: TaskRecord
    var isCurrent: Bool = false
    var lineLimit: Int = 3

    var body: some View {
        Text(task.title)
            .strikethrough(task.state.isTerminal, color: titleColor)
            .carryOnText(isCurrent ? CarryOnTypeScale.bodyStrong : CarryOnTypeScale.body, lineHeight: CarryOnLayout.Row.lineHeight)
            .foregroundStyle(titleColor)
            .lineLimit(lineLimit)
            .multilineTextAlignment(.leading)
    }

    private var titleColor: Color {
        switch task.state {
        case .completed, .cancelled: BBColor.stepTextDone
        case .waiting: BBColor.textSecondary
        default: BBColor.textPrimary
        }
    }
}

// MARK: - Metadata

private struct TaskRowMetadata: View {
    let details: TaskRowDetails
    let openDecisionCard: OpenDecisionCardAction?

    var body: some View {
        VStack(alignment: .leading, spacing: BBSpacing.s1) {
            if let marker = details.marker {
                ReviewMarkerButton(style: marker, taskID: details.task.id, openDecisionCard: openDecisionCard)
            }
            if let line = details.metaLine {
                Text(line)
                    .carryOnText(CarryOnTypeScale.meta, lineHeight: CarryOnLayout.Row.lineHeight)
                    .foregroundStyle(BBColor.textSecondary)
                    .lineLimit(3)
                    .multilineTextAlignment(.leading)
            }
        }
    }
}

/// The metadata line being built: words joined with " · ", each in the row's
/// metadata colour unless it carries its own.
private struct MetaLine {
    private(set) var text = AttributedString()

    var isEmpty: Bool { text.characters.isEmpty }

    mutating func append(_ string: String, color: Color? = nil) {
        if !isEmpty { text.append(AttributedString(" · ")) }
        var part = AttributedString(string)
        if let color { part.foregroundColor = color }
        text.append(part)
    }
}

/// Everything the row shows, resolved once per render from the workspace.
@MainActor
private struct TaskRowDetails {
    let task: TaskRecord
    let today: CalendarDay
    let project: ProjectRecord?
    let tagNames: [String]
    /// Project, list, waiting note, subtasks, due date and tags, joined with
    /// " · "; the due date is coloured when it is today or overdue.
    let metaLine: AttributedString?
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

        var line = MetaLine()
        if let project { line.append(project.name) }
        if let listName { line.append(listName) }
        for part in waiting.visible { line.append(part) }
        if !counted.isEmpty { line.append("\(done)/\(counted.count) subtasks") }
        if let due = task.dueDate {
            line.append(Self.dueText(due, today: today, isOpen: task.isOpen), color: Self.dueColor(due, today: today, isOpen: task.isOpen))
        }
        for name in tagNames { line.append(name) }

        self.task = task
        self.today = today
        self.project = project
        self.tagNames = tagNames
        self.metaLine = line.isEmpty ? nil : line.text
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
        if !tagNames.isEmpty {
            spoken.append((tagNames.count == 1 ? "Tag " : "Tags ") + tagNames.joined(separator: ", "))
        }
        spokenParts = spoken
    }

    var hasMetadata: Bool { marker != nil || metaLine != nil }

    var accessibilityLabel: String { spokenParts.joined(separator: ", ") }

    /// "Today", the date, or "Overdue (Sep 22)": the words carry the state, the
    /// colour only repeats it.
    static func dueText(_ day: CalendarDay, today: CalendarDay, isOpen: Bool) -> String {
        let label = DueChip.label(for: day, today: today)
        return isOpen && day < today ? "Overdue (\(label))" : label
    }

    /// chip-due-fg for a task due today, chip-overdue-fg for an overdue one, and
    /// nil (the line's own colour) for every other date and for finished tasks.
    static func dueColor(_ day: CalendarDay, today: CalendarDay, isOpen: Bool) -> Color? {
        guard isOpen else { return nil }
        if day < today { return BBColor.overdueText }
        return BBDayMath.offset(from: today, to: day) == 0 ? BBColor.dueText : nil
    }

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

/// The completion target, 44 pt around the 24 pt mark (the hit area reaches into
/// the card's padding, so the row stays as tall as the board draws it). Open
/// tasks complete on tap: the mark turns to done, then the task completes
/// (under 600 ms in total; with Reduce Motion the change is instant and the row
/// does not slide). Finished tasks show their static mark.
private struct CompletionControl: View {
    let task: TaskRecord
    let status: CarryOnStepRow.Status

    /// How far the hit area reaches past the mark on each side.
    private static let hitOutset = (BBMetrics.hitTarget - CGFloat(CarryOnLayout.Row.mark)) / 2

    @Environment(Workspace.self) private var workspace
    @Environment(ToastCenter.self) private var toasts
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var isCompleting = false
    @State private var isSavingCompletion = false
    @State private var completionEditorID = UUID().uuidString

    var body: some View {
        if task.isOpen {
            Button(action: complete) {
                CarryOnStepMark(isCompleting ? .done : status)
                    .contentShape(.interaction, Rectangle().inset(by: -Self.hitOutset))
            }
            .buttonStyle(.borderless)
            .disabled(isCompleting)
            .accessibilityLabel("Complete")
        } else {
            CarryOnStepMark(status)
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
