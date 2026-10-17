import BrainBuddyDesign
import BrainBuddyMacCore
import SwiftUI

// The Mac window's chrome in the Carry On design system (board "07 Inbox · Mac"): the brand
// mark, the sidebar's section headers and rows, and the list header. Presentation only.

/// Instrument faces at the board's own sizes, which differ from the type scale in places.
private enum MacChromeFont {
    static func action(size: CGFloat, weight: Int, relativeTo style: Font.TextStyle) -> Font {
        CarryOnFonts.register()
        return .custom(CarryOnFontFace.action.postScriptName(weight: weight), size: size, relativeTo: style)
    }

    static var sectionHeader: Font { action(size: 11, weight: 600, relativeTo: .caption) }
    static var rowTitle: Font { action(size: 14, weight: 400, relativeTo: .body) }
    static var rowTitleSelected: Font { action(size: 14, weight: 600, relativeTo: .body) }
    static var rowCount: Font { action(size: 13, weight: 400, relativeTo: .body) }

    static var brand: Font {
        CarryOnFonts.register()
        return .custom(CarryOnFontFace.voice.postScriptName(weight: 400), size: 22, relativeTo: .title)
    }
}

/// The hiker mark of `brand/mark.svg` (viewBox 64×64): ink is text-primary, the sun is the accent
/// fill in both modes.
struct CarryOnMark: View {
    var size: CGFloat = 26
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        Canvas { context, canvas in
            let ink = GraphicsContext.Shading.color(CarryOnColorStyle(CarryOnRole.textPrimary).color(in: scheme))
            let sun = GraphicsContext.Shading.color(CarryOnColorStyle(CarryOnRole.accentFill).color(in: scheme))
            var context = context
            context.scaleBy(x: canvas.width / 64, y: canvas.height / 64)
            context.translateBy(x: 0.8, y: 5.4)
            context.scaleBy(x: 0.82, y: 0.82)

            func stroke(_ width: CGFloat, _ points: [CGPoint]) {
                var path = Path()
                path.move(to: points[0])
                for point in points.dropFirst() { path.addLine(to: point) }
                context.stroke(path, with: ink, style: StrokeStyle(lineWidth: width, lineCap: .round, lineJoin: .round))
            }

            stroke(3.5, [
                CGPoint(x: 16, y: 58), CGPoint(x: 32, y: 58), CGPoint(x: 32, y: 50), CGPoint(x: 42, y: 50),
                CGPoint(x: 42, y: 42), CGPoint(x: 52, y: 42), CGPoint(x: 52, y: 34), CGPoint(x: 60, y: 34),
            ])

            var head = context
            head.translateBy(x: 26.2, y: 25)
            head.rotate(by: .degrees(15))
            head.translateBy(x: -26.2, y: -25)
            head.fill(Path(roundedRect: CGRect(x: 22, y: 18.5, width: 8.5, height: 13), cornerRadius: 3.5), with: ink)

            stroke(6.0, [CGPoint(x: 30, y: 34), CGPoint(x: 26, y: 45), CGPoint(x: 23, y: 55)])
            stroke(6.0, [CGPoint(x: 30, y: 34), CGPoint(x: 37, y: 40), CGPoint(x: 37, y: 47)])
            stroke(7.5, [CGPoint(x: 33.2, y: 22.5), CGPoint(x: 30, y: 34)])
            stroke(4.5, [CGPoint(x: 33, y: 24), CGPoint(x: 39, y: 29), CGPoint(x: 43, y: 26.5)])
            stroke(2.2, [CGPoint(x: 43.5, y: 20), CGPoint(x: 44.6, y: 40.5)])

            context.fill(
                Path(ellipseIn: CGRect(x: 35.4 - 4.8, y: 13 - 4.8, width: 9.6, height: 9.6)), with: sun)
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}

/// The sidebar's brand: the mark, then "Carry On" in Instrument Serif 22.
struct MacSidebarBrand: View {
    var body: some View {
        HStack(spacing: 8) {
            CarryOnMark(size: 26)
            Text("Carry On")
                .font(MacChromeFont.brand)
                .tracking(-0.44)
                .foregroundStyle(.coTextPrimary)
                .lineLimit(1)
        }
        .padding(.horizontal, 6)
        .padding(.bottom, 4)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// A sidebar section header; `trailing` holds the Projects header's buttons.
struct MacSidebarSectionHeader<Trailing: View>: View {
    let title: String
    let trailing: Trailing

    init(title: String, @ViewBuilder trailing: () -> Trailing) {
        self.title = title
        self.trailing = trailing()
    }

    var body: some View {
        HStack {
            Text(title)
            Spacer(minLength: 0)
            trailing
        }
        .font(MacChromeFont.sectionHeader)
        .textCase(nil)
        .foregroundStyle(.coTextSecondary)
        .padding(.top, 12)
        .padding(.bottom, 3)
        .padding(.horizontal, 10)
    }
}

extension MacSidebarSectionHeader where Trailing == EmptyView {
    init(title: String) {
        self.init(title: title) { EmptyView() }
    }
}

/// One sidebar row drawn as the board has it; the selection fill is part of the label.
struct MacSidebarRowLabel: View {
    enum Leading {
        case symbol(String)
        case dot(Color)
        /// One of the board's own icons, drawn at 16pt.
        case icon(MacBoardIcon)
    }

    let title: String
    let leading: Leading
    var trailing: String?
    let selected: Bool
    /// A deferred row is shown in the secondary colour.
    var muted = false
    /// An agent row with a Needs-you run: the accent dot comes before the count (board M22, DSAgents).
    var attention = false

    var body: some View {
        HStack(spacing: 10) {
            leadingView
                .frame(width: 16, height: 16)
                .accessibilityHidden(true)
            Text(title)
                .font(selected ? MacChromeFont.rowTitleSelected : MacChromeFont.rowTitle)
                .foregroundStyle(titleStyle)
                .lineLimit(1)
                .layoutPriority(1)
            Spacer(minLength: 0)
            if attention {
                Circle().fill(CarryOnColorStyle.coStepDotCurrent).frame(width: 7, height: 7)
                    .accessibilityHidden(true)
            }
            if let trailing {
                Text(trailing)
                    .font(MacChromeFont.rowCount)
                    .monospacedDigit()
                    .foregroundStyle(.coTextSecondary)
                    .lineLimit(1)
            }
        }
        .padding(.horizontal, 10)
        .frame(height: 29)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background {
            if selected {
                RoundedRectangle(cornerRadius: 7, style: .continuous).fill(.coSidebarRowSelected)
            }
        }
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityLabel(title)
        .accessibilityValue(Self.accessibilityValue(trailing: trailing, attention: attention))
    }

    /// The count (or status word) the row shows, with the Needs-you dot spoken, so VoiceOver hears what is drawn (030-FR-004).
    static func accessibilityValue(trailing: String?, attention: Bool) -> String {
        [attention ? "Needs you" : nil, trailing].compactMap { $0 }.joined(separator: ", ")
    }

    private var titleStyle: CarryOnColorStyle { muted ? .coTextSecondary : .coTextPrimary }

    private var symbolStyle: CarryOnColorStyle { muted ? .coTextSecondary : .coTextPrimary }

    @ViewBuilder
    private var leadingView: some View {
        switch leading {
        case .symbol(let name):
            Image(systemName: name)
                .font(.system(size: 14))
                .foregroundStyle(symbolStyle)
        case .dot(let color):
            Circle().fill(color).frame(width: 9, height: 9)
        case .icon(let icon):
            MacBoardIconView(icon: icon, size: 16)
                .foregroundStyle(symbolStyle)
        }
    }
}

/// One agent under Agents in the sidebar (030-FR-004, DSAgents): the listed-run count with the accent dot
/// when a run needs you, or, for an agent with no listed runs, its status word unless it is Tested ready.
struct AgentSidebarRow: Equatable, Identifiable {
    let id: String
    var name: String
    var trailing: String?
    var needsYou = false

    private static let testedReady = "Tested ready"

    static func rows(runs: [AgentRunItem], counts: [String: Int], connections: [AgentListRow]) -> [AgentSidebarRow] {
        var byID: [String: AgentSidebarRow] = [:]
        for connection in connections {
            let word = connection.status == testedReady ? nil : connection.status
            byID[connection.id] = AgentSidebarRow(id: connection.id, name: connection.name, trailing: word)
        }
        for id in Set(runs.compactMap(\.connectionID)) {
            let mine = runs.filter { $0.connectionID == id }
            byID[id] = AgentSidebarRow(
                id: id, name: mine[0].agentName, trailing: "\(counts[id] ?? 0)", needsYou: mine.contains { $0.state == .needsYou })
        }
        return byID.values.sorted { ($0.name, $0.id) < ($1.name, $1.id) }
    }
}

/// The list's title in Instrument Serif with its task count on the first baseline, right-aligned.
/// `accessory` sits after the title (the archived badge); `titleView` lets the caller attach focus
/// handling to the title text.
struct MacListHeaderTitle<TitleView: View, Accessory: View>: View {
    let title: String
    let caption: String
    let accessory: Accessory
    let titleView: (Text) -> TitleView

    init(
        title: String, caption: String, @ViewBuilder accessory: () -> Accessory,
        titleView: @escaping (Text) -> TitleView
    ) {
        self.title = title
        self.caption = caption
        self.accessory = accessory()
        self.titleView = titleView
    }

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            titleView(Text(title))
                .carryOnText(CarryOnTypeScale.display)
                .foregroundStyle(.coTextPrimary)
                .lineLimit(2)
            accessory
            Spacer(minLength: 12)
            Text(caption)
                .carryOnFont(CarryOnTypeScale.meta)
                .foregroundStyle(.coTextSecondary)
        }
    }
}

extension MacListHeaderTitle where TitleView == Text, Accessory == EmptyView {
    init(title: String, caption: String) {
        self.init(title: title, caption: caption, accessory: { EmptyView() }, titleView: { $0 })
    }
}
