import BrainBuddyAgents
import BrainBuddyDesign
import SwiftUI

/// One agent run in Waiting for's Agents group (board M22, 034-FR-004): the robot mark, the step's
/// title and "<agent> · ● <state>" under it. The state word is the kit's `compactState` and the dot
/// carries the colour: Needs you is the accent, Lost contact warning, Failed danger, the rest quiet.
/// The row is content only; the list applies `bbCardRow()` outside the button, like a task row.
/// Agent text is shown verbatim, never as Markdown.
struct AgentRunRow: View {
    let item: AgentRunItem
    let onOpen: () -> Void

    var body: some View {
        TimelineView(.periodic(from: .now, by: 60)) { context in
            let state = item.compactState(now: context.date)
            Button(action: onOpen) {
                content(state: state)
            }
            .buttonStyle(.plain)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("\(item.stepTitle), \(item.agentName), \(state)")
            .accessibilityAddTraits(.isButton)
        }
    }

    private func content(state: String) -> some View {
        HStack(alignment: .center, spacing: CGFloat(CarryOnLayout.Row.gap)) {
            AgentRobotGlyph()
                .stroke(style: StrokeStyle(lineWidth: 1.8, lineCap: .round, lineJoin: .round))
                .foregroundStyle(CarryOnColorStyle.coMarkOpen)
                .frame(width: 24, height: 24)
            VStack(alignment: .leading, spacing: CGFloat(CarryOnLayout.Row.metaGap)) {
                Text(verbatim: item.stepTitle)
                    .font(BBFont.rowTitle)
                    .foregroundStyle(BBColor.textPrimary)
                    .lineLimit(3)
                    .multilineTextAlignment(.leading)
                stateLine(state)
            }
            Spacer(minLength: 0)
        }
        .contentShape(.rect)
    }

    private func stateLine(_ state: String) -> some View {
        HStack(spacing: 6) {
            Text(verbatim: "\(item.agentName) ·")
            Circle().fill(tone.dot).frame(width: 7, height: 7)
            Text(verbatim: state).foregroundStyle(tone.ink)
        }
        .font(BBFont.meta)
        .foregroundStyle(CarryOnColorStyle.coTextSecondary)
        .lineLimit(2)
    }

    /// "Only your moves get colour": the same table as the Mac's Waiting for row.
    private var tone: (ink: CarryOnColorStyle, dot: CarryOnColorStyle) {
        if item.state == .failed { return (.coStatusDanger, .coStatusDanger) }
        switch item.group {
        case .needsYou: return (.coTextAccent, .coAccentFill)
        case .lostContact: return (.coStatusWarning, .coStatusWarning)
        case .running, .queued, .toReview: return (.coTextSecondary, .coMarkOpen)
        }
    }
}

/// The agent mark of the canvas: a rounded head, two eyes and an antenna, drawn on a 24-point grid.
private struct AgentRobotGlyph: Shape {
    func path(in rect: CGRect) -> Path {
        let scale = min(rect.width, rect.height) / 24
        func point(_ x: Double, _ y: Double) -> CGPoint {
            CGPoint(x: rect.minX + x * scale, y: rect.minY + y * scale)
        }
        var path = Path()
        path.addRoundedRect(
            in: CGRect(origin: point(4, 6), size: CGSize(width: 16 * scale, height: 12 * scale)),
            cornerSize: CGSize(width: 4 * scale, height: 4 * scale), style: .continuous)
        for x in [9.5, 14.5] {
            path.addEllipse(
                in: CGRect(origin: point(x - 1.2, 10.8), size: CGSize(width: 2.4 * scale, height: 2.4 * scale)))
        }
        path.move(to: point(12, 3))
        path.addLine(to: point(12, 6))
        return path
    }
}
