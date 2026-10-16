import BrainBuddyCore
import BrainBuddyDesign
import SwiftUI

/// Board 14, the due date of one task: quick days (Today, Tomorrow, the day
/// after, Next week) above the system's graphical month, a note on what a
/// due day means, and a glass bar with "Due <day>" and "No date".
///
/// The quick days are only preset days for the same field; nothing here
/// decides anything about the task. The sheet owns its choice until a bar
/// button is pressed: "Due <day>" reports that day, "No date" reports nil
/// (clears it), and swiping the sheet away changes nothing.
///
/// The month is the system graphical `DatePicker`, not a drawn grid: it draws
/// today and the chosen day itself (today in the tint, the chosen day filled).
struct DueDateSheet: View {
    private let taskTitle: String
    private let today: CalendarDay
    private let onPick: (CalendarDay?) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var selection: CalendarDay?

    init(taskTitle: String, day: CalendarDay?, today: CalendarDay, onPick: @escaping (CalendarDay?) -> Void) {
        self.taskTitle = taskTitle
        self.today = today
        self.onPick = onPick
        _selection = State(initialValue: day)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                Text("Due date · \(taskTitle)")
                    .carryOnText(CarryOnTypeScale.meta)
                    .foregroundStyle(.coTextSecondary)
                    .lineLimit(1)
                Text("When should it be done?")
                    .carryOnText(CarryOnTypeScale.title)
                    .foregroundStyle(.coTextPrimary)
                    .accessibilityAddTraits(.isHeader)
                    .padding(.top, CGFloat(CarryOnSpace.xs))
                    .padding(.bottom, CGFloat(CarryOnSpace.sm))
                quickDays
                DatePicker("Due date", selection: dateBinding, displayedComponents: .date)
                    .datePickerStyle(.graphical)
                    .padding(.top, CGFloat(CarryOnSpace.md))
                Text(note)
                    .carryOnText(CarryOnTypeScale.meta)
                    .foregroundStyle(.coTextSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, CGFloat(CarryOnSpace.sm))
            }
            .padding(.horizontal, CGFloat(CarryOnSpace.lg))
            .padding(.top, CGFloat(CarryOnSpace.lg))
            .padding(.bottom, CGFloat(CarryOnSpace.md))
        }
        .safeAreaInset(edge: .bottom, spacing: 0) {
            BBGlassActionBar {
                Button {
                    pick(selection)
                } label: {
                    Text(primaryTitle)
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.carryOnSecondary)
                .disabled(selection == nil)
                Button("No date") { pick(nil) }
                    .buttonStyle(.carryOnQuiet)
            }
        }
        .bbScreenBackground()
        .presentationDetents([.large])
        .presentationDragIndicator(.visible)
    }

    // MARK: Quick days

    private struct Preset: Hashable {
        let title: String
        let day: CalendarDay
    }

    private var presets: [Preset] {
        let dayAfter = today.adding(days: 2)
        return [
            Preset(title: "Today", day: today),
            Preset(title: "Tomorrow", day: today.adding(days: 1)),
            Preset(title: dayAfter.startDate().formatted(.dateTime.weekday(.wide)), day: dayAfter),
            Preset(title: "Next week", day: today.adding(days: 7)),
        ]
    }

    /// The presets as chips; the chosen one is outlined and announced as
    /// selected, so the choice never rests on colour.
    private var quickDays: some View {
        BBFlowLayout(spacing: CGFloat(CarryOnSpace.xs), lineSpacing: CGFloat(CarryOnSpace.xs)) {
            ForEach(presets, id: \.self) { preset in
                let isChosen = preset.day == selection
                Button {
                    selection = preset.day
                } label: {
                    CarryOnChip(preset.title)
                        .overlay {
                            if isChosen {
                                Capsule()
                                    .strokeBorder(.coFocusRing, lineWidth: CGFloat(CarryOnLayout.FocusRing.width))
                            }
                        }
                        .frame(minHeight: BBMetrics.hitTarget)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(preset.title)
                .accessibilityAddTraits(isChosen ? .isSelected : [])
            }
        }
    }

    // MARK: Month

    /// The month shows the chosen day, or today while nothing is chosen.
    private var dateBinding: Binding<Date> {
        Binding(
            get: { (selection ?? today).startDate() },
            set: { selection = CalendarDay(date: $0) }
        )
    }

    // MARK: Copy

    /// "Due Friday 16", "Due today"; the month (and year) only when it is not
    /// this one.
    private var primaryTitle: String {
        guard let selection else { return "Choose a day" }
        switch BBDayMath.offset(from: today, to: selection) {
        case 0: return "Due today"
        case 1: return "Due tomorrow"
        default:
            let date = selection.startDate()
            var text = "Due \(date.formatted(.dateTime.weekday(.wide))) \(date.formatted(.dateTime.day()))"
            if selection.month != today.month || selection.year != today.year {
                text += " \(date.formatted(.dateTime.month(.abbreviated)))"
            }
            if selection.year != today.year {
                text += " \(date.formatted(.dateTime.year()))"
            }
            return text
        }
    }

    private var note: String {
        let lead = "A day, not a time."
        guard let selection else { return lead }
        let offset = BBDayMath.offset(from: today, to: selection)
        let when: String
        switch offset {
        case ..<1: return lead
        case 1: when = "tomorrow"
        case 2...6: when = "on \(selection.startDate().formatted(.dateTime.weekday(.wide)))"
        default: when = "on \(selection.startDate().formatted(.dateTime.month(.wide).day()))"
        }
        return "\(lead) It shows up in Today \(when) and turns overdue after."
    }

    private func pick(_ day: CalendarDay?) {
        onPick(day)
        dismiss()
    }
}
