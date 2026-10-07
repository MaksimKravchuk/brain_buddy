import BrainBuddyCore
import SwiftUI
import UIKit

// MARK: - Tag pill

/// A tag as a neutral pill (`calls`, `errands`); plain names, no `@` prefix.
struct TagPill: View {
    let name: String

    var body: some View {
        Text(name)
            .font(BBFont.caption)
            .foregroundStyle(BBColor.tagText)
            .lineLimit(1)
            .padding(.horizontal, BBSpacing.s2)
            .padding(.vertical, 2)
            .background(BBColor.tagBackground, in: Capsule())
            .accessibilityLabel("Tag \(name)")
    }
}

// MARK: - Project label

/// A project colour dot followed by the project name, in metadata style.
struct ProjectLabel: View {
    let name: String
    let color: Color
    @ScaledMetric(relativeTo: .footnote) private var dotSize: CGFloat = BBMetrics.projectDot

    init(name: String, color: Color) {
        self.name = name
        self.color = color
    }

    /// `color` is the project's stored colour token (`#RRGGBB`), if any.
    init(name: String, color hex: String?) {
        self.init(name: name, color: BBColor.project(hex))
    }

    var body: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(color)
                .frame(width: dotSize, height: dotSize)
            Text(name)
                .lineLimit(1)
        }
        .font(BBFont.meta)
        .foregroundStyle(BBColor.textTertiary)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Project \(name)")
    }
}

// MARK: - Due chip

/// A due date in words — "Today", "Tomorrow", "Yesterday", a weekday within
/// the coming week, otherwise a short date — as the brand's rose deadline chip.
/// Overdue deadlines add a warning symbol and the word "Overdue" for VoiceOver,
/// so the state never rests on colour. Pass `isDeadlineActive: false` for
/// completed or cancelled tasks: their date is history, not a deadline, and is
/// shown neutral.
struct DueChip: View {
    let day: CalendarDay
    let today: CalendarDay
    var isDeadlineActive: Bool = true

    init(day: CalendarDay, today: CalendarDay, isDeadlineActive: Bool = true) {
        self.day = day
        self.today = today
        self.isDeadlineActive = isDeadlineActive
    }

    private var isOverdue: Bool { isDeadlineActive && day < today }

    var body: some View {
        HStack(spacing: BBSpacing.s1) {
            Image(systemName: isOverdue ? "exclamationmark.circle.fill" : "calendar")
                .imageScale(.small)
            Text(Self.label(for: day, today: today))
        }
        .font(BBFont.caption.weight(isOverdue ? .semibold : .regular))
        .foregroundStyle(isDeadlineActive ? BBColor.dueText : BBColor.tagText)
        .lineLimit(1)
        .padding(.horizontal, BBSpacing.s2)
        .padding(.vertical, 2)
        .background(isDeadlineActive ? BBColor.dueBackground : BBColor.tagBackground, in: Capsule())
        .overlay {
            Capsule().strokeBorder(isDeadlineActive ? BBColor.dueBorder : BBColor.hairline, lineWidth: 1)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Self.accessibilityText(for: day, today: today, isDeadlineActive: isDeadlineActive))
    }

    /// The visible words for `day` seen from `today`.
    static func label(for day: CalendarDay, today: CalendarDay, calendar: Calendar = .current) -> String {
        let offset = BBDayMath.offset(from: today, to: day)
        switch offset {
        case 0: return "Today"
        case 1: return "Tomorrow"
        case -1: return "Yesterday"
        case 2...6: return format(day, .dateTime.weekday(.abbreviated), calendar: calendar)
        default:
            let style: Date.FormatStyle = day.year == today.year
                ? .dateTime.month(.abbreviated).day()
                : .dateTime.month(.abbreviated).day().year()
            return format(day, style, calendar: calendar)
        }
    }

    /// The spoken description, for example "Due tomorrow" or
    /// "Overdue, due September 22".
    static func accessibilityText(
        for day: CalendarDay, today: CalendarDay, isDeadlineActive: Bool = true, calendar: Calendar = .current
    ) -> String {
        let offset = BBDayMath.offset(from: today, to: day)
        let spoken: String
        switch offset {
        case 0: spoken = "today"
        case 1: spoken = "tomorrow"
        case -1: spoken = "yesterday"
        case 2...6: spoken = format(day, .dateTime.weekday(.wide), calendar: calendar)
        default:
            let style: Date.FormatStyle = day.year == today.year
                ? .dateTime.month(.wide).day()
                : .dateTime.month(.wide).day().year()
            spoken = format(day, style, calendar: calendar)
        }
        return isDeadlineActive && offset < 0 ? "Overdue, due \(spoken)" : "Due \(spoken)"
    }

    private static func format(_ day: CalendarDay, _ style: Date.FormatStyle, calendar: Calendar) -> String {
        var style = style
        style.timeZone = calendar.timeZone
        return day.startDate(in: calendar).formatted(style)
    }
}

/// Whole-day arithmetic on `CalendarDay`, independent of time zones and DST.
enum BBDayMath {
    /// Days from `start` to `end` (negative when `end` is earlier).
    static func offset(from start: CalendarDay, to end: CalendarDay) -> Int {
        var gregorian = Calendar(identifier: .gregorian)
        gregorian.timeZone = TimeZone(secondsFromGMT: 0) ?? .current
        guard let from = gregorian.date(from: DateComponents(year: start.year, month: start.month, day: start.day)),
            let to = gregorian.date(from: DateComponents(year: end.year, month: end.month, day: end.day))
        else { return 0 }
        return gregorian.dateComponents([.day], from: from, to: to).day ?? 0
    }
}

// MARK: - Priority badge

/// Priority as exclamation marks plus the word, so it never relies on colour.
/// Renders nothing for `.none`.
struct PriorityBadge: View {
    let priority: TaskPriority

    var body: some View {
        if priority != .none {
            HStack(spacing: 2) {
                Image(systemName: priority.symbolName)
                    .imageScale(.small)
                Text(priority.title)
            }
            .font(BBFont.caption.weight(.medium))
            .foregroundStyle(Self.color(for: priority))
            .lineLimit(1)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("\(priority.title) priority")
        }
    }

    /// Text-contrast shades of the semantic colours (high rose, medium amber,
    /// low sky), matching the Expo app's priority dot.
    static func color(for priority: TaskPriority) -> Color {
        switch priority {
        case .high: BBColor.dangerText
        case .medium: BBColor.warningText
        case .low: BBColor.infoText
        case .none: BBColor.textTertiary
        }
    }
}

// MARK: - Review marker (spec 020, M-01, M-02)

/// A formulation marker: words plus an SF Symbol, never colour alone. Indigo
/// for "Asks for a decision", amber (the warning semantic) for "Moves to
/// Someday tomorrow", slate for the detail-only states. Rose is reserved for
/// real due dates and is never an age colour (FR-004, FR-038). The text,
/// symbol and role come from Core (`MarkerStyle`, `ReviewCopy`); the label
/// wraps instead of truncating at accessibility text sizes.
struct ReviewMarkerChip: View {
    let text: String
    let symbol: String?
    let role: MarkerRole

    init(text: String, symbol: String?, role: MarkerRole) {
        self.text = text
        self.symbol = symbol
        self.role = role
    }

    /// Nil for a style without text (fresh, none).
    init?(_ style: MarkerStyle) {
        guard let text = style.text else { return nil }
        self.init(text: text, symbol: style.symbol, role: style.role)
    }

    var body: some View {
        let colors = ReviewMarkerColors.colors(for: role)
        HStack(alignment: .firstTextBaseline, spacing: BBSpacing.s1) {
            if let symbol {
                Image(systemName: symbol)
                    .imageScale(.small)
                    .accessibilityHidden(true)
            }
            Text(text)
                .multilineTextAlignment(.leading)
                .fixedSize(horizontal: false, vertical: true)
        }
        .font(BBFont.caption.weight(.medium))
        .foregroundStyle(colors.text)
        .padding(.horizontal, BBSpacing.s2)
        .padding(.vertical, 2)
        .background(colors.background, in: RoundedRectangle(cornerRadius: BBRadius.chip, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: BBRadius.chip, style: .continuous)
                .strokeBorder(colors.border, lineWidth: 1)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(text)
    }
}

/// Marker colours from the design (indigo-50/200/700, amber-50/200/800,
/// slate-100/600). Indigo is not a general app token, so it lives here, with
/// dark values derived from the same scale (indigo-950/800/300).
enum ReviewMarkerColors {
    struct Colors {
        let background: Color
        let border: Color
        let text: Color
    }

    static func colors(for role: MarkerRole) -> Colors {
        switch role {
        case .decision:
            Colors(background: indigoBackground, border: indigoBorder, text: indigoText)
        case .caution:
            Colors(background: BBColor.warningBackground, border: BBColor.warningBorder, text: BBColor.warningText)
        case .neutral, .none:
            Colors(background: BBColor.tagBackground, border: BBColor.hairline, text: BBColor.tagText)
        case .destructive:
            // Never produced for an age class (Core's MarkerStyle test);
            // drawn neutral rather than rose should that ever change.
            Colors(background: BBColor.tagBackground, border: BBColor.hairline, text: BBColor.tagText)
        }
    }

    static let indigoBackground = dynamic(light: 0xEEF2FF, dark: 0x1E1B4B)
    static let indigoBorder = dynamic(light: 0xC7D2FE, dark: 0x3730A3)
    static let indigoText = dynamic(light: 0x4338CA, dark: 0xA5B4FC)

    private static func dynamic(light: UInt32, dark: UInt32) -> Color {
        Color(
            uiColor: UIColor { traits in
                let rgb = traits.userInterfaceStyle == .dark ? dark : light
                return UIColor(
                    red: CGFloat((rgb >> 16) & 0xFF) / 255, green: CGFloat((rgb >> 8) & 0xFF) / 255,
                    blue: CGFloat(rgb & 0xFF) / 255, alpha: 1
                )
            }
        )
    }
}

// MARK: - Count badge

/// A list count. `prominent` is the Inbox's sky pill (sky-700, so the white
/// numerals meet contrast); other counts are plain slate-500 numerals.
/// Nothing is shown for zero.
struct CountBadge: View {
    let count: Int
    var prominent: Bool = false
    @ScaledMetric(relativeTo: .caption2) private var pillHeight: CGFloat = 20

    init(count: Int, prominent: Bool = false) {
        self.count = count
        self.prominent = prominent
    }

    var body: some View {
        if count > 0 {
            if prominent {
                Text(count, format: .number)
                    .font(BBFont.micro.weight(.semibold))
                    .monospacedDigit()
                    .foregroundStyle(BBColor.onBrand)
                    .padding(.horizontal, 6)
                    .frame(minWidth: pillHeight, minHeight: pillHeight)
                    .background(BBColor.brandFill, in: Capsule())
                    .accessibilityLabel(Self.spokenCount(count))
            } else {
                Text(count, format: .number)
                    .font(BBFont.meta)
                    .monospacedDigit()
                    .foregroundStyle(BBColor.textTertiary)
                    .accessibilityLabel(Self.spokenCount(count))
            }
        }
    }

    static func spokenCount(_ count: Int) -> String {
        count == 1 ? "1 task" : "\(count) tasks"
    }
}

// MARK: - Flow layout

/// Lays children out left to right and wraps onto new lines, vertically
/// centring each line. Used for row metadata (chips and pills).
struct BBFlowLayout: Layout {
    var spacing: CGFloat = 6
    var lineSpacing: CGFloat = BBSpacing.s1

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let lines = arrange(maxWidth: proposal.width ?? .infinity, subviews: subviews)
        let width = lines.map(\.width).max() ?? 0
        let height = lines.last.map { $0.y + $0.height } ?? 0
        return CGSize(width: width, height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let lines = arrange(maxWidth: bounds.width, subviews: subviews)
        for line in lines {
            for item in line.items {
                let origin = CGPoint(
                    x: bounds.minX + item.x,
                    y: bounds.minY + line.y + (line.height - item.size.height) / 2
                )
                subviews[item.index].place(at: origin, anchor: .topLeading, proposal: ProposedViewSize(item.size))
            }
        }
    }

    private struct Item {
        let index: Int
        let size: CGSize
        let x: CGFloat
    }

    private struct Line {
        var items: [Item] = []
        var y: CGFloat = 0
        var width: CGFloat = 0
        var height: CGFloat = 0
    }

    private func arrange(maxWidth: CGFloat, subviews: Subviews) -> [Line] {
        var lines: [Line] = []
        var line = Line()
        for index in subviews.indices {
            var size = subviews[index].sizeThatFits(.unspecified)
            if size.width > maxWidth {
                size = subviews[index].sizeThatFits(ProposedViewSize(width: maxWidth, height: nil))
                size.width = min(size.width, maxWidth)
            }
            if size.width <= 0, size.height <= 0 {
                // Empty children (a hidden badge) take no room and no spacing.
                line.items.append(Item(index: index, size: .zero, x: line.width))
                continue
            }
            let x = line.width > 0 ? line.width + spacing : 0
            if line.width > 0, x + size.width > maxWidth {
                let nextY = line.y + line.height + lineSpacing
                lines.append(line)
                line = Line(items: [Item(index: index, size: size, x: 0)], y: nextY, width: size.width, height: size.height)
            } else {
                line.items.append(Item(index: index, size: size, x: x))
                line.width = x + size.width
                line.height = max(line.height, size.height)
            }
        }
        if !line.items.isEmpty { lines.append(line) }
        return lines
    }
}

#Preview("Chips") {
    let today = CalendarDay(date: Date())
    VStack(alignment: .leading, spacing: 12) {
        HStack {
            TagPill(name: "errands")
            TagPill(name: "deep-work")
        }
        ProjectLabel(name: "Launch v2", color: "#6366F1")
        HStack {
            DueChip(day: today, today: today)
            DueChip(day: today.adding(days: 3), today: today)
            DueChip(day: today.adding(days: -4), today: today)
        }
        HStack {
            PriorityBadge(priority: .high)
            PriorityBadge(priority: .medium)
            PriorityBadge(priority: .low)
        }
        HStack {
            CountBadge(count: 17, prominent: true)
            CountBadge(count: 6)
        }
    }
    .padding()
    .bbScreenBackground()
}

#Preview("Review markers (M-01, M-02)") {
    VStack(alignment: .leading, spacing: 12) {
        ForEach(FormulationClass.allCases, id: \.self) { kind in
            if let chip = ReviewMarkerChip(MarkerStyle.for(kind)) {
                chip
            }
        }
    }
    .padding()
    .bbScreenBackground()
}
