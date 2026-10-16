import BrainBuddyDesign
import SwiftUI

// The Mac task inspector in the Carry On design system (boards "13 Next action", "14 Due date",
// "15 Not now", "16 What is it?", "18 Waiting for", "19 Someday", "20 Done · Mac" and the empty
// inspector of "07 Inbox · Mac"): the card on the right, 340 wide (Inbox 380), padding 26/24, and
// its parts. Presentation only: values and closures in, nothing bound to app state.

/// Instrument faces at the inspector's own sizes.
private enum MacInspectorFont {
    static var eyebrow: Font { MacRowFont.action(size: 12, weight: 400, relativeTo: .caption) }
    static var sectionLabel: Font { MacRowFont.action(size: 12, weight: 600, relativeTo: .caption) }
    static var body: Font { MacRowFont.action(size: 14, weight: 400, relativeTo: .body) }
    static var detail: Font { MacRowFont.action(size: 12, weight: 400, relativeTo: .caption) }
    static var note: Font { MacRowFont.action(size: 13, weight: 400, relativeTo: .caption) }
    static var item: Font { MacRowFont.action(size: 15, weight: 400, relativeTo: .body) }
    static var person: Font { MacRowFont.action(size: 15, weight: 600, relativeTo: .body) }

    static func sans(size: CGFloat, weight: Int) -> Font {
        MacRowFont.action(size: size, weight: weight, relativeTo: .title2)
    }

    static func serif(size: CGFloat) -> Font {
        CarryOnFonts.register()
        return .custom(CarryOnFontFace.voice.postScriptName(weight: 400), size: size, relativeTo: .title)
    }
}

// MARK: - Panel

/// The inspector card: `surface-card`, padding 26/24, content on top and the action bar pinned to
/// the bottom. `height` is for fixtures; in the app leave it `nil` and the panel fills its column.
struct MacInspectorPanel<Content: View, Bar: View>: View {
    static var defaultWidth: CGFloat { 340 }
    static var inboxWidth: CGFloat { 380 }

    let width: CGFloat
    let height: CGFloat?
    let content: Content
    let bar: Bar

    init(
        width: CGFloat = 340, height: CGFloat? = nil, @ViewBuilder content: () -> Content,
        @ViewBuilder actionBar: () -> Bar
    ) {
        self.width = width
        self.height = height
        self.content = content()
        self.bar = actionBar()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            content
            Spacer(minLength: 16)
            bar
        }
        .padding(.top, 26)
        .padding(.horizontal, 24)
        .padding(.bottom, 24)
        .frame(width: width, height: height, alignment: .topLeading)
        .frame(maxHeight: height ?? .infinity, alignment: .topLeading)
        .background(CarryOnColorStyle.coSurfaceCard)
    }
}

extension MacInspectorPanel where Bar == EmptyView {
    init(width: CGFloat = 340, height: CGFloat? = nil, @ViewBuilder content: () -> Content) {
        self.init(width: width, height: height, content: content, actionBar: { EmptyView() })
    }
}

// MARK: - Eyebrow, title, labels

/// "Garage · Next actions": the project's dot, its name, a middle dot and the list.
struct MacInspectorEyebrow: View {
    let projectName: String?
    let projectColor: BrainBuddyDesign.RGBColor?
    let listName: String

    init(projectName: String?, projectColor: BrainBuddyDesign.RGBColor?, listName: String) {
        self.projectName = projectName
        self.projectColor = projectColor
        self.listName = listName
    }

    /// The Inbox's eyebrow: "Inbox · 1 of 4" (or "Inbox · Sorting 1 of 4" while clarifying).
    static func inbox(position: Int, of total: Int, sorting: Bool = false) -> MacInspectorEyebrow {
        MacInspectorEyebrow(
            projectName: "Inbox", projectColor: nil, listName: sorting ? "Sorting \(position) of \(total)" : "\(position) of \(total)")
    }

    var body: some View {
        HStack(spacing: 6) {
            if let projectColor {
                Circle().fill(Color(projectColor)).frame(width: 8, height: 8).accessibilityHidden(true)
            }
            if let projectName {
                Text(projectName)
                Text("·")
            }
            Text(listName)
        }
        .font(MacInspectorFont.eyebrow)
        .foregroundStyle(CarryOnColorStyle.coTextSecondary)
        .lineLimit(1)
        .accessibilityElement(children: .combine)
    }
}

/// The task's title: Instrument Sans 20 semibold, or Instrument Serif for Someday (26), the Inbox
/// question (24) and the clarify question (22). `struck` is the Done title in `step-text-done`.
struct MacInspectorTitle: View {
    let text: String
    var serif = false
    var size: CGFloat?
    var struck = false

    init(text: String, serif: Bool = false, size: CGFloat? = nil, struck: Bool = false) {
        self.text = text
        self.serif = serif
        self.size = size
        self.struck = struck
    }

    var body: some View {
        Text(text)
            .font(font)
            .tracking(serif ? -0.015 * (size ?? 26) : 0)
            .strikethrough(struck, color: CarryOnColorStyle.coStepTextDone.color(in: scheme))
            .foregroundStyle(struck ? CarryOnColorStyle.coStepTextDone : CarryOnColorStyle.coTextPrimary)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.top, serif ? 8 : 6)
            .accessibilityAddTraits(.isHeader)
    }

    @Environment(\.colorScheme) private var scheme

    private var font: Font {
        serif ? MacInspectorFont.serif(size: size ?? 26) : MacInspectorFont.sans(size: size ?? 20, weight: 600)
    }
}

/// The title as the person edits it ("Saved as you type"): `MacInspectorTitle`'s faces, sizes and
/// spacing in a plain field, or with `item` the Inbox item's 15 (`MacInspectorItemText`).
struct MacInspectorTitleField: View {
    @Binding var text: String
    var serif = false
    var size: CGFloat?
    var item = false

    var body: some View {
        TextField("Task title", text: $text, axis: .vertical)
            .textFieldStyle(.plain)
            .font(font)
            .tracking(serif && !item ? -0.015 * (size ?? 26) : 0)
            .foregroundStyle(CarryOnColorStyle.coTextPrimary)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.top, item || serif ? 8 : 6)
            .accessibilityLabel("Task title")
    }

    private var font: Font {
        if item { return MacInspectorFont.item }
        return serif ? MacInspectorFont.serif(size: size ?? 26) : MacInspectorFont.sans(size: size ?? 20, weight: 600)
    }
}

/// The Inbox item as typed: 15, under the eyebrow. `muted` is the clarify step's secondary ink.
struct MacInspectorItemText: View {
    let text: String
    var muted = false

    var body: some View {
        Text(text)
            .font(MacInspectorFont.item)
            .foregroundStyle(muted ? CarryOnColorStyle.coTextSecondary : CarryOnColorStyle.coTextPrimary)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.top, 8)
    }
}

/// "Why", "Steps inside", "Comments", "Note": 12 semibold secondary, 22 above and 8 below.
struct MacInspectorSectionLabel: View {
    let text: String

    init(_ text: String) {
        self.text = text
    }

    var body: some View {
        Text(text)
            .font(MacInspectorFont.sectionLabel)
            .foregroundStyle(CarryOnColorStyle.coTextSecondary)
            .padding(.top, 22)
            .padding(.bottom, 8)
            .frame(maxWidth: .infinity, alignment: .leading)
            .accessibilityAddTraits(.isHeader)
    }
}

/// A section's text: 14, or the 13 secondary line ("None yet", the Someday hint).
struct MacInspectorBodyText: View {
    let text: String
    var quiet = false
    var topPadding: CGFloat = 0

    var body: some View {
        Text(text)
            .font(quiet ? MacInspectorFont.note : MacInspectorFont.body)
            .foregroundStyle(quiet ? CarryOnColorStyle.coTextSecondary : CarryOnColorStyle.coTextPrimary)
            .lineSpacing(quiet ? 3 : 5)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.top, topPadding)
    }
}

/// A 12 secondary line ("Here since March", "Finished steps are read-only.").
struct MacInspectorMetaText: View {
    let text: String
    var topPadding: CGFloat = 8

    var body: some View {
        Text(text)
            .font(MacInspectorFont.detail)
            .foregroundStyle(CarryOnColorStyle.coTextSecondary)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.top, topPadding)
    }
}

/// One line of "Steps inside": a done check or an open circle, 16 wide, then the title.
struct MacInspectorStepLine: View {
    let title: String
    let done: Bool
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        HStack(spacing: 10) {
            MacInspectorStepMark(done: done)
            Text(title)
                .font(MacInspectorFont.body)
                .strikethrough(done, color: CarryOnColorStyle.coStepTextDone.color(in: scheme))
                .foregroundStyle(done ? CarryOnColorStyle.coStepTextDone : CarryOnColorStyle.coTextPrimary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// The 16 pt mark of a "Steps inside" line: a done check or an open circle.
struct MacInspectorStepMark: View {
    let done: Bool

    var body: some View {
        if done {
            Image(systemName: "checkmark.circle.fill")
                .symbolRenderingMode(.palette)
                .foregroundStyle(CarryOnColorStyle.coBgGround, CarryOnColorStyle.coTextDone)
                .font(.system(size: 16))
                .frame(width: 16, height: 16)
                .accessibilityHidden(true)
        } else {
            Circle()
                .strokeBorder(CarryOnColorStyle.coStepDotOpen, lineWidth: 2)
                .frame(width: 16, height: 16)
                .accessibilityHidden(true)
        }
    }
}

// MARK: - Chips

/// Wraps its children onto lines, like a flex row with `flex-wrap`.
struct MacInspectorFlow: Layout {
    var spacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let limit = proposal.width ?? .infinity
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0
        var widest: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x > 0, x + size.width > limit {
                y += rowHeight + spacing
                x = 0
                rowHeight = 0
            }
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
            widest = max(widest, x - spacing)
        }
        return CGSize(width: widest, height: y + rowHeight)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX
        var y = bounds.minY
        var rowHeight: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x > bounds.minX, x + size.width > bounds.maxX {
                y += rowHeight + spacing
                x = bounds.minX
                rowHeight = 0
            }
            subview.place(at: CGPoint(x: x, y: y), anchor: .topLeading, proposal: ProposedViewSize(size))
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
    }
}

/// The chip row: project (with its dot), due day, then tags; 6 apart, wrapping.
struct MacInspectorChips: View {
    var projectName: String?
    var projectColor: BrainBuddyDesign.RGBColor?
    var dueText: String?
    var dueTone: CarryOnChip.Tone = .plain
    var tags: [String] = []
    var topPadding: CGFloat = 14

    var body: some View {
        MacInspectorFlow(spacing: 6) {
            if let projectName {
                CarryOnChip(projectName, dot: projectColor)
            }
            if let dueText {
                CarryOnChip(dueText, tone: dueTone)
            }
            ForEach(tags, id: \.self) { tag in
                CarryOnChip(tag)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.top, topPadding)
    }
}

// MARK: - Glyphs

/// The 18 pt line icons of the choice rows: the board's list icons plus the project folder and the
/// person.
enum MacInspectorGlyph: Hashable, Sendable {
    case board(MacBoardIcon)
    case folder
    case person
}

private struct MacInspectorFolderShape: Shape {
    func path(in rect: CGRect) -> Path {
        let unit = min(rect.width, rect.height) / 24
        func point(_ x: CGFloat, _ y: CGFloat) -> CGPoint {
            CGPoint(x: rect.minX + x * unit, y: rect.minY + y * unit)
        }
        var path = Path()
        path.move(to: point(3.5, 7.5))
        path.addCurve(to: point(5.5, 5.5), control1: point(3.5, 6.4), control2: point(4.4, 5.5))
        path.addLine(to: point(9.5, 5.5))
        path.addLine(to: point(11.5, 7.5))
        path.addLine(to: point(18.5, 7.5))
        path.addCurve(to: point(20.5, 9.5), control1: point(19.6, 7.5), control2: point(20.5, 8.4))
        path.addLine(to: point(20.5, 17.5))
        path.addCurve(to: point(18.5, 19.5), control1: point(20.5, 18.6), control2: point(19.6, 19.5))
        path.addLine(to: point(5.5, 19.5))
        path.addCurve(to: point(3.5, 17.5), control1: point(4.4, 19.5), control2: point(3.5, 18.6))
        path.closeSubpath()
        return path
    }
}

private struct MacInspectorPersonShape: Shape {
    func path(in rect: CGRect) -> Path {
        let unit = min(rect.width, rect.height) / 24
        func point(_ x: CGFloat, _ y: CGFloat) -> CGPoint {
            CGPoint(x: rect.minX + x * unit, y: rect.minY + y * unit)
        }
        var path = Path()
        path.addEllipse(in: CGRect(x: rect.minX + 8 * unit, y: rect.minY + 4 * unit, width: 8 * unit, height: 8 * unit))
        path.move(to: point(4, 20))
        path.addCurve(to: point(12, 14), control1: point(5.5, 16), control2: point(8.5, 14))
        path.addCurve(to: point(20, 20), control1: point(15.5, 14), control2: point(18.5, 16))
        return path
    }
}

struct MacInspectorGlyphView: View {
    let glyph: MacInspectorGlyph
    var size: CGFloat = 18

    var body: some View {
        switch glyph {
        case .board(let icon):
            MacBoardIconView(icon: icon, size: size)
        case .folder:
            MacInspectorFolderShape()
                .stroke(style: StrokeStyle(lineWidth: 1.8 * size / 24, lineCap: .round, lineJoin: .round))
                .frame(width: size, height: size)
                .accessibilityHidden(true)
        case .person:
            MacInspectorPersonShape()
                .stroke(style: StrokeStyle(lineWidth: 1.8 * size / 24, lineCap: .round, lineJoin: .round))
                .frame(width: size, height: size)
                .accessibilityHidden(true)
        }
    }
}

// MARK: - Person, choices

/// Waiting for: who it is with, first. A 22 pt person glyph, the name in 15 semibold and, under it,
/// "Asked 3 days ago" in 12 secondary.
struct MacInspectorPerson: View {
    let name: String
    let since: String

    var body: some View {
        HStack(spacing: 10) {
            MacInspectorGlyphView(glyph: .person, size: 22)
                .foregroundStyle(CarryOnColorStyle.coTextPrimary)
            VStack(alignment: .leading, spacing: 0) {
                Text(name).font(MacInspectorFont.person).foregroundStyle(CarryOnColorStyle.coTextPrimary)
                Text(since).font(MacInspectorFont.detail).foregroundStyle(CarryOnColorStyle.coTextSecondary)
            }
        }
        .padding(.top, 14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }
}

/// One answer: an 18 pt icon, a 14 title and a 12 detail on a `bg-ground` plate, radius 10, with
/// 6 below it. Used by Inbox "What is it?" and the Not now popover.
struct MacInspectorChoiceRow: View {
    let title: String
    let detail: String
    var glyph: MacInspectorGlyph?
    let action: () -> Void

    init(title: String, detail: String, glyph: MacInspectorGlyph? = nil, action: @escaping () -> Void) {
        self.title = title
        self.detail = detail
        self.glyph = glyph
        self.action = action
    }

    var body: some View {
        Button(action: action) {
            HStack(spacing: 10) {
                if let glyph {
                    MacInspectorGlyphView(glyph: glyph, size: 18)
                        .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                }
                VStack(alignment: .leading, spacing: 0) {
                    Text(title)
                        .font(MacInspectorFont.body)
                        .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                    Text(detail)
                        .font(MacInspectorFont.detail)
                        .foregroundStyle(CarryOnColorStyle.coTextSecondary)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 9)
            .background(
                CarryOnColorStyle.coBgGround, in: RoundedRectangle(cornerRadius: 10, style: .continuous)
            )
            .contentShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        }
        .buttonStyle(.plain)
        .padding(.bottom, 6)
        .accessibilityElement(children: .combine)
    }
}

// MARK: - Action bar, empty

/// A button in the action bar.
struct MacInspectorAction {
    enum Kind: Sendable {
        case primary, secondary, quiet
    }

    let title: String
    var kind: Kind = .secondary
    let perform: () -> Void

    init(_ title: String, kind: Kind = .secondary, perform: @escaping () -> Void) {
        self.title = title
        self.kind = kind
        self.perform = perform
    }

    static func primary(_ title: String, perform: @escaping () -> Void) -> MacInspectorAction {
        MacInspectorAction(title, kind: .primary, perform: perform)
    }

    static func secondary(_ title: String, perform: @escaping () -> Void) -> MacInspectorAction {
        MacInspectorAction(title, kind: .secondary, perform: perform)
    }

    static func quiet(_ title: String, perform: @escaping () -> Void) -> MacInspectorAction {
        MacInspectorAction(title, kind: .quiet, perform: perform)
    }
}

/// The bar pinned to the card's bottom: pills 8 apart and, right-aligned, a 12 secondary note
/// ("Saved as you type", "Skip").
struct MacInspectorActionBar: View {
    let actions: [MacInspectorAction]
    var trailingNote: String?
    /// Makes the note a text button ("Skip").
    var onTrailingNote: (() -> Void)?

    init(actions: [MacInspectorAction], trailingNote: String? = nil, onTrailingNote: (() -> Void)? = nil) {
        self.actions = actions
        self.trailingNote = trailingNote
        self.onTrailingNote = onTrailingNote
    }

    init(primary: MacInspectorAction?, secondary: MacInspectorAction? = nil, trailingNote: String? = nil) {
        self.init(actions: [primary, secondary].compactMap { $0 }, trailingNote: trailingNote)
    }

    private static func buttonStyle(_ kind: MacInspectorAction.Kind) -> CarryOnButtonStyle {
        switch kind {
        case .primary: .carryOnPrimary
        case .secondary: .carryOnSecondary
        case .quiet: .carryOnQuiet
        }
    }

    var body: some View {
        HStack(spacing: 8) {
            ForEach(Array(actions.enumerated()), id: \.offset) { _, action in
                Button(action.title, action: action.perform)
                    .buttonStyle(Self.buttonStyle(action.kind))
            }
            Spacer(minLength: 0)
            if let trailingNote {
                if let onTrailingNote {
                    Button(action: onTrailingNote) {
                        Text(trailingNote)
                            .font(MacInspectorFont.detail)
                            .foregroundStyle(CarryOnColorStyle.coTextSecondary)
                    }
                    .buttonStyle(.plain)
                } else {
                    Text(trailingNote)
                        .font(MacInspectorFont.detail)
                        .foregroundStyle(CarryOnColorStyle.coTextSecondary)
                }
            }
        }
    }
}

/// Nothing selected: the centred 14 secondary placeholder, filling the card.
struct MacInspectorEmpty: View {
    let text: String

    var body: some View {
        Text(text)
            .font(MacInspectorFont.body)
            .foregroundStyle(CarryOnColorStyle.coTextSecondary)
            .lineSpacing(5)
            .multilineTextAlignment(.center)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

// MARK: - Not now popover

/// The Not now popover (board 15): 300 wide, radius 16, padding 14, four answers.
struct MacNotNowPopoverContent: View {
    let onPickDay: () -> Void
    let onWaiting: () -> Void
    let onSomeday: () -> Void
    let onChangeStep: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("Not now. Then when?")
                .font(MacInspectorFont.sectionLabel)
                .foregroundStyle(CarryOnColorStyle.coTextSecondary)
                .padding(.top, 2)
                .padding(.horizontal, 4)
                .padding(.bottom, 8)
                .accessibilityAddTraits(.isHeader)
            MacInspectorChoiceRow(
                title: "Pick a day", detail: "Set a due day. It shows in Today then",
                glyph: .board(.calendar), action: onPickDay)
            MacInspectorChoiceRow(
                title: "Waiting on someone", detail: "Say who, and it moves to Waiting for",
                glyph: .board(.waitingFor), action: onWaiting)
            MacInspectorChoiceRow(
                title: "Someday", detail: "Off your plate, kept for the weekly review",
                glyph: .board(.somedayMaybe), action: onSomeday)
            MacInspectorChoiceRow(
                title: "Change the step", detail: "Rewrite it smaller, so you can start",
                glyph: .board(.nextActions), action: onChangeStep)
        }
        .padding(14)
        .frame(width: 300, alignment: .topLeading)
        .background(
            CarryOnColorStyle.coSurfaceCard.opacity(0.95), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }
}
