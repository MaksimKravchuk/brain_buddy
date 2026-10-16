import BrainBuddyCore
import BrainBuddyDesign
import SwiftUI

// The Mac list column in the Carry On design system (boards "07 Inbox", "08 Next actions",
// "09 Project", "18 Waiting for", "19 Someday", "20 Done · Mac"): task rows, the pill button, the
// list's section headers and its empty state. Presentation only.

/// Instrument Sans at the Mac list's own sizes.
enum MacRowFont {
    static func action(size: CGFloat, weight: Int, relativeTo style: Font.TextStyle) -> Font {
        CarryOnFonts.register()
        return .custom(CarryOnFontFace.action.postScriptName(weight: weight), size: size, relativeTo: style)
    }

    /// A row's title: 14.
    static var title: Font { .carryOn(CarryOnTypeScale.body) }
    /// The current step's title: 14, semibold.
    static var titleStrong: Font { .carryOn(CarryOnTypeScale.bodyStrong) }
    /// A row's trailing meta: 12.
    static var meta: Font { .carryOn(CarryOnTypeScale.meta) }
    /// A section header inside the list: 12, semibold.
    static var sectionHeader: Font { action(size: 12, weight: 600, relativeTo: .caption) }
    /// The pill button's label: 14, semibold.
    static var pill: Font { .carryOn(CarryOnTypeScale.bodyStrong) }
}

/// What a row's mark and ink say about its task.
enum MacRowKind: Sendable {
    /// Not a step yet: no mark.
    case inbox
    /// An open step: an open circle.
    case open
    /// The one step the view calls current: a terracotta dot and a semibold title.
    case current
    case done
    case cancelled
    /// With someone else: the clock.
    case waiting
    /// Quiet: no mark, secondary ink.
    case someday

    init(state: TaskState, isCurrent: Bool = false) {
        switch state {
        case .inbox: self = .inbox
        case .next: self = isCurrent ? .current : .open
        case .waiting: self = .waiting
        case .someday: self = .someday
        case .completed: self = .done
        case .cancelled: self = .cancelled
        }
    }

    var hasMark: Bool {
        switch self {
        case .inbox, .someday: false
        case .open, .current, .done, .cancelled, .waiting: true
        }
    }

    var isStruck: Bool { self == .done || self == .cancelled }
}

/// How a due day reads in a row's meta.
enum MacDueTone: Sendable {
    case plain, due, overdue

    init(due: CalendarDay, today: CalendarDay) {
        if due < today {
            self = .overdue
        } else if due == today {
            self = .due
        } else {
            self = .plain
        }
    }
}

/// The 17 pt mark at the start of a step row.
struct MacRowMark: View {
    static let size: CGFloat = 17

    let kind: MacRowKind

    var body: some View {
        switch kind {
        case .inbox, .someday:
            Color.clear.frame(width: 0, height: Self.size)
        case .open:
            Circle()
                .strokeBorder(CarryOnColorStyle.coStepDotOpen, lineWidth: 2)
                .frame(width: Self.size, height: Self.size)
        case .current:
            Circle()
                .fill(CarryOnColorStyle.coStepDotCurrent)
                .frame(width: Self.size, height: Self.size)
        case .done:
            Image(systemName: "checkmark.circle.fill")
                .symbolRenderingMode(.palette)
                .foregroundStyle(CarryOnColorStyle.coBgGround, CarryOnColorStyle.coTextDone)
                .font(.system(size: 16))
                .frame(width: Self.size, height: Self.size)
        case .cancelled:
            Image(systemName: "xmark.circle")
                .font(.system(size: 16))
                .foregroundStyle(CarryOnColorStyle.coMarkOpen)
                .frame(width: Self.size, height: Self.size)
        case .waiting:
            MacRowClock()
                .stroke(
                    CarryOnColorStyle.coMarkOpen,
                    style: StrokeStyle(lineWidth: 1.8, lineCap: .round, lineJoin: .round)
                )
                .frame(width: Self.size, height: Self.size)
        }
    }
}

/// The board's waiting clock: a circle of radius 8 and hands `M12 7.5V12l3 2` on a 24 grid.
private struct MacRowClock: Shape {
    func path(in rect: CGRect) -> Path {
        let unit = rect.width / 24
        var path = Path()
        path.addEllipse(in: CGRect(x: 4 * unit, y: 4 * unit, width: 16 * unit, height: 16 * unit))
        path.move(to: CGPoint(x: 12 * unit, y: 7.5 * unit))
        path.addLine(to: CGPoint(x: 12 * unit, y: 12 * unit))
        path.addLine(to: CGPoint(x: 15 * unit, y: 14 * unit))
        return path
    }
}

/// A row's title. Done and cancelled are text-done and struck through; Someday is secondary. Colours
/// match the board on the selection fill too (Max, 2026-10-16: board first, rework only if rejected).
struct MacRowTitleText: View {
    let title: String
    let kind: MacRowKind
    var selected = false
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        Text(title)
            .strikethrough(kind.isStruck, color: strikeColor)
            .font(kind == .current ? MacRowFont.titleStrong : MacRowFont.title)
            .foregroundStyle(ink)
            .lineLimit(1)
    }

    private var ink: CarryOnColorStyle {
        switch kind {
        case .done, .cancelled: return CarryOnColorStyle.coStepTextDone
        case .someday: return CarryOnColorStyle.coTextSecondary
        case .inbox, .open, .current, .waiting: return CarryOnColorStyle.coTextPrimary
        }
    }

    private var strikeColor: Color { ink.color(in: scheme) }
}

/// Trailing meta: 12, secondary, or the due and overdue ink.
struct MacRowMetaStyle: ViewModifier {
    var tone: MacDueTone = .plain
    var selected = false

    func body(content: Content) -> some View {
        content
            .font(MacRowFont.meta)
            .foregroundStyle(ink)
            .lineLimit(1)
    }

    private var ink: CarryOnColorStyle {
        switch tone {
        case .due: return CarryOnColorStyle.coChipDueFg
        case .overdue: return CarryOnColorStyle.coChipOverdueFg
        case .plain: return CarryOnColorStyle.coTextSecondary
        }
    }
}

extension View {
    func macRowMeta(tone: MacDueTone = .plain, selected: Bool = false) -> some View {
        modifier(MacRowMetaStyle(tone: tone, selected: selected))
    }

    /// The row's surface: the selection fill at radius 8, nothing when not selected.
    func macRowSurface(selected: Bool) -> some View {
        background {
            if selected {
                RoundedRectangle(cornerRadius: 8, style: .continuous).fill(CarryOnColorStyle.coRowBgSelected)
            }
        }
    }
}

/// A row's line: mark, title, then trailing meta, at padding 9/12 and gap 12. The surface is applied
/// by the caller (`macRowSurface`) so an open editor can sit inside it.
struct MacTaskRowShell<Leading: View, Title: View, Trailing: View>: View {
    let leading: Leading
    let title: Title
    let trailing: Trailing

    init(
        @ViewBuilder leading: () -> Leading, @ViewBuilder title: () -> Title,
        @ViewBuilder trailing: () -> Trailing
    ) {
        self.leading = leading()
        self.title = title()
        self.trailing = trailing()
    }

    var body: some View {
        HStack(spacing: 12) {
            leading
            title
            Spacer(minLength: 8)
            trailing
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 9)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// One complete, static row: the board's rows with fixture values.
struct MacTaskRow: View {
    let title: String
    var kind: MacRowKind = .open
    var meta: String?
    var tone: MacDueTone = .plain
    var selected = false

    var body: some View {
        MacTaskRowShell {
            if kind.hasMark { MacRowMark(kind: kind) }
        } title: {
            MacRowTitleText(title: title, kind: kind, selected: selected)
        } trailing: {
            if let meta {
                Text(meta).macRowMeta(tone: tone, selected: selected)
            }
        }
        .macRowSurface(selected: selected)
    }
}

/// The board's pill: primary (terracotta), secondary or quiet; 32 high, 14 semibold, padding 0 14. `quiet` is text only.
struct MacPillButtonStyle: ButtonStyle {
    enum Kind: Sendable {
        case primary, secondary, quiet
    }

    let kind: Kind

    func makeBody(configuration: Configuration) -> some View {
        MacPillButtonBody(kind: kind, label: configuration.label, isPressed: configuration.isPressed)
    }
}

private struct MacPillButtonBody<Label: View>: View {
    let kind: MacPillButtonStyle.Kind
    let label: Label
    let isPressed: Bool
    @Environment(\.isEnabled) private var isEnabled

    var body: some View {
        label
            .font(MacRowFont.pill)
            .foregroundStyle(foreground)
            .padding(.horizontal, 14)
            .frame(minHeight: 32)
            .background {
                if let background { Capsule().fill(background) }
            }
            .scaleEffect(isPressed && kind != .quiet ? 0.97 : 1)
            .opacity(isEnabled ? 1 : 0.4)
            .contentShape(Capsule())
    }

    private var foreground: CarryOnColorStyle {
        switch kind {
        case .primary: CarryOnColorStyle.coButtonPrimaryFg
        case .secondary: CarryOnColorStyle.coButtonSecondaryFg
        case .quiet: CarryOnColorStyle.coTextPrimary
        }
    }

    private var background: CarryOnColorStyle? {
        switch kind {
        case .primary: isPressed ? CarryOnColorStyle.coButtonPrimaryBgPressed : CarryOnColorStyle.coButtonPrimaryBg
        case .secondary: isPressed ? CarryOnColorStyle.coButtonSecondaryBgPressed : CarryOnColorStyle.coButtonSecondaryBg
        case .quiet: nil
        }
    }
}

extension ButtonStyle where Self == MacPillButtonStyle {
    static var macPrimaryPill: MacPillButtonStyle { MacPillButtonStyle(kind: .primary) }
    static var macSecondaryPill: MacPillButtonStyle { MacPillButtonStyle(kind: .secondary) }
    static var macQuietPill: MacPillButtonStyle { MacPillButtonStyle(kind: .quiet) }
}

/// A section header inside the list: Instrument Sans 12, secondary, in line with the rows' text.
struct MacListSectionHeader: View {
    let title: String
    let top: CGFloat

    var body: some View {
        Text(title)
            .font(MacRowFont.sectionHeader)
            .foregroundStyle(CarryOnColorStyle.coTextSecondary)
            .padding(.top, top)
            .padding(.bottom, 4)
            .padding(.horizontal, 12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .accessibilityAddTraits(.isHeader)
    }
}

/// A list's empty state: a quiet symbol, a 14 line in secondary and, when there is one, a 12 line.
struct MacEmptyState: View {
    let title: String
    let systemImage: String
    var description: String?

    var body: some View {
        VStack(spacing: 6) {
            Image(systemName: systemImage)
                .font(.system(size: 24))
                .foregroundStyle(CarryOnColorStyle.coMarkOpen)
                .padding(.bottom, 4)
            Text(title)
                .font(MacRowFont.titleStrong)
                .foregroundStyle(CarryOnColorStyle.coTextSecondary)
            if let description {
                Text(description)
                    .font(MacRowFont.title)
                    .foregroundStyle(CarryOnColorStyle.coTextSecondary)
            }
        }
        .multilineTextAlignment(.center)
        .padding(24)
        .accessibilityElement(children: .combine)
    }
}
