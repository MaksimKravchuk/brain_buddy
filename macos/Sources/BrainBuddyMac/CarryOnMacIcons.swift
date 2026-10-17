import BrainBuddyCore
import BrainBuddyMacCore
import Foundation
import SwiftUI

// The design board's own sidebar icons (M07-Mac), ported from its 24x24 SVGs: stroke
// `currentColor`, stroke-width 1.8, round caps and joins, no fill. Each case is drawn in the
// 24x24 space and scaled to its frame. SVG arcs are converted to cubic segments from the arc's
// own centre and radius, so the sweep direction does not depend on SwiftUI's arc conventions.

enum MacBoardIcon: Hashable, Sendable {
    /// `<path d="M4 13l2.5-7h11L20 13v5H4z"/><path d="M4 13h4.5l1 2h5l1-2H20"/>`
    case inbox
    /// `<path d="M5 18h4v-4h4v-4h4V6h2"/>`
    case nextActions
    /// `<circle cx="12" cy="12" r="8"/><path d="M12 7.5V12l3 2"/>`
    case waitingFor
    /// `<path d="M5 18h14M7 18V9l5-4 5 4v9"/>`
    case somedayMaybe
    /// `<rect x="4" y="5.5" width="16" height="14" rx="3"/><path d="M4 10h16M9 3.5v4M15 3.5v4"/>`
    /// The board uses this one calendar for Overdue, Today and Upcoming.
    case calendar
    /// `<path d="M4 12a8 8 0 108-8 8 8 0 00-6 2.7"/><path d="M4 4v4h4M12 8v4l3 2"/>`
    /// The board uses this one history icon for Done and Cancelled.
    case history
    /// Settings tabs (spec 028): a person, a robot head with an antenna, two circling arrows.
    case account, agents, sync
    /// Settings › Voice (spec 037): the board's mic, as on the toolbar's voice button (`MacMicGlyph`).
    case voice
    /// Agents on the board (M22–M24, DSAgents): All runs, each agent row and a run's mark in Waiting for.
    /// `<rect x="4" y="6" width="16" height="12" rx="4"/><circle cx="9.5" cy="12" r="1.2"/><circle cx="14.5" cy="12" r="1.2"/><path d="M12 3v3"/>`
    case agentRun
    /// `<path d="M12 5v14M5 12h14"/>`: the board's plus, on "New step" and "Add new agent".
    case plus
}

/// A board icon as a `Shape`; stroke it with `MacBoardIconView` (or `.stroke(style:)`).
struct MacBoardIconShape: Shape {
    let icon: MacBoardIcon

    func path(in rect: CGRect) -> Path {
        let scale = min(rect.width, rect.height) / 24
        let originX = rect.minX + (rect.width - 24 * scale) / 2
        let originY = rect.minY + (rect.height - 24 * scale) / 2
        func point(_ x: Double, _ y: Double) -> CGPoint {
            CGPoint(x: originX + CGFloat(x) * scale, y: originY + CGFloat(y) * scale)
        }
        func polyline(_ points: [(Double, Double)], closed: Bool = false) -> Path {
            var path = Path()
            guard let first = points.first else { return path }
            path.move(to: point(first.0, first.1))
            for next in points.dropFirst() {
                path.addLine(to: point(next.0, next.1))
            }
            if closed { path.closeSubpath() }
            return path
        }
        /// Appends an arc of the circle (`centerX`, `centerY`, `radius`) from angle `from` to angle
        /// `to`, in radians measured as SVG does (y down: increasing angle runs clockwise on
        /// screen), as cubic segments of at most a quarter turn. The path must already be at the
        /// start angle's point.
        func addCircleArc(
            into path: inout Path, centerX: Double, centerY: Double, radius: Double, from: Double, to: Double
        ) {
            let segments = max(1, Int((abs(to - from) / (Double.pi / 2)).rounded(.up)))
            let step = (to - from) / Double(segments)
            let handle = 4.0 / 3.0 * tan(step / 4)
            for index in 0..<segments {
                let a = from + step * Double(index)
                let b = a + step
                let end = point(centerX + radius * cos(b), centerY + radius * sin(b))
                let control1 = point(
                    centerX + radius * (cos(a) - handle * sin(a)),
                    centerY + radius * (sin(a) + handle * cos(a))
                )
                let control2 = point(
                    centerX + radius * (cos(b) + handle * sin(b)),
                    centerY + radius * (sin(b) - handle * cos(b))
                )
                path.addCurve(to: end, control1: control1, control2: control2)
            }
        }

        var path = Path()
        switch icon {
        case .inbox:
            // M4 13 l2.5-7 h11 L20 13 v5 H4 z
            path.addPath(polyline([(4, 13), (6.5, 6), (17.5, 6), (20, 13), (20, 18), (4, 18)], closed: true))
            // M4 13 h4.5 l1 2 h5 l1-2 H20
            path.addPath(polyline([(4, 13), (8.5, 13), (9.5, 15), (14.5, 15), (15.5, 13), (20, 13)]))
        case .nextActions:
            // M5 18 h4 v-4 h4 v-4 h4 V6 h2
            path.addPath(polyline([(5, 18), (9, 18), (9, 14), (13, 14), (13, 10), (17, 10), (17, 6), (19, 6)]))
        case .waitingFor:
            // circle cx=12 cy=12 r=8
            path.addEllipse(in: CGRect(origin: point(4, 4), size: CGSize(width: 16 * scale, height: 16 * scale)))
            // M12 7.5 V12 l3 2
            path.addPath(polyline([(12, 7.5), (12, 12), (15, 14)]))
        case .somedayMaybe:
            // M5 18 h14
            path.addPath(polyline([(5, 18), (19, 18)]))
            // M7 18 V9 l5-4 5 4 v9
            path.addPath(polyline([(7, 18), (7, 9), (12, 5), (17, 9), (17, 18)]))
        case .calendar:
            // rect x=4 y=5.5 width=16 height=14 rx=3
            path.addPath(
                RoundedRectangle(cornerRadius: 3 * scale, style: .circular)
                    .path(in: CGRect(origin: point(4, 5.5), size: CGSize(width: 16 * scale, height: 14 * scale)))
            )
            // M4 10 h16
            path.addPath(polyline([(4, 10), (20, 10)]))
            // M9 3.5 v4
            path.addPath(polyline([(9, 3.5), (9, 7.5)]))
            // M15 3.5 v4
            path.addPath(polyline([(15, 3.5), (15, 7.5)]))
        case .history:
            // M4 12 a8 8 0 1 0 8-8: circle centre (12,12) r=8 from (4,12) to (12,4), large arc,
            // sweep 0 (angle decreasing): 180 degrees down to -90 degrees.
            path.move(to: point(4, 12))
            addCircleArc(
                into: &path, centerX: 12, centerY: 12, radius: 8, from: Double.pi, to: -Double.pi / 2
            )
            // 8 8 0 0 0 -6 2.7: the same circle from (12,4) to (6,6.7), small arc, sweep 0.
            addCircleArc(
                into: &path, centerX: 12, centerY: 12, radius: 8, from: -Double.pi / 2,
                to: atan2(6.7 - 12, 6 - 12)
            )
            // M4 4 v4 h4
            path.addPath(polyline([(4, 4), (4, 8), (8, 8)]))
            // M12 8 v4 l3 2
            path.addPath(polyline([(12, 8), (12, 12), (15, 14)]))
        case .account:
            path.addEllipse(in: CGRect(origin: point(8.5, 4.5), size: CGSize(width: 7 * scale, height: 7 * scale)))
            path.move(to: point(5, 20))
            addCircleArc(into: &path, centerX: 12, centerY: 20, radius: 7, from: Double.pi, to: 2 * Double.pi)
        case .agents:
            path.addPath(
                RoundedRectangle(cornerRadius: 4 * scale, style: .circular)
                    .path(in: CGRect(origin: point(5, 8), size: CGSize(width: 14 * scale, height: 11 * scale)))
            )
            path.addPath(polyline([(12, 8), (12, 4.5)]))
            path.addPath(polyline([(9.5, 13), (9.5, 14)]))
            path.addPath(polyline([(14.5, 13), (14.5, 14)]))
        case .agentRun:
            path.addPath(
                RoundedRectangle(cornerRadius: 4 * scale, style: .circular)
                    .path(in: CGRect(origin: point(4, 6), size: CGSize(width: 16 * scale, height: 12 * scale)))
            )
            for x in [9.5, 14.5] {
                path.addEllipse(in: CGRect(origin: point(x - 1.2, 10.8), size: CGSize(width: 2.4 * scale, height: 2.4 * scale)))
            }
            path.addPath(polyline([(12, 3), (12, 6)]))
        case .plus:
            path.addPath(polyline([(12, 5), (12, 19)]))
            path.addPath(polyline([(5, 12), (19, 12)]))
        case .sync:
            path.move(to: point(19, 12))
            addCircleArc(into: &path, centerX: 12, centerY: 12, radius: 7, from: 0, to: -3 * Double.pi / 4)
            path.addLine(to: point(5, 9))
            path.addPath(polyline([(5, 5), (5, 9), (9, 9)]))
            path.move(to: point(5, 12))
            addCircleArc(into: &path, centerX: 12, centerY: 12, radius: 7, from: Double.pi, to: Double.pi / 4)
            path.addLine(to: point(19, 15))
            path.addPath(polyline([(19, 19), (19, 15), (15, 15)]))
        case .voice:
            path.addPath(
                MacMicGlyph().path(in: CGRect(origin: point(0, 0), size: CGSize(width: 24 * scale, height: 24 * scale))))
        }
        return path
    }
}

/// A board icon drawn at `size` points with the board's stroke (1.8 in the 24-unit space),
/// in the surrounding foreground style. Decorative: hidden from accessibility.
struct MacBoardIconView: View {
    let icon: MacBoardIcon
    var size: CGFloat = 16

    var body: some View {
        MacBoardIconShape(icon: icon)
            .stroke(style: StrokeStyle(lineWidth: 1.8 * size / 24, lineCap: .round, lineJoin: .round))
            .frame(width: size, height: size)
            .accessibilityHidden(true)
    }
}

extension MacBoardIcon {
    /// The icon the board uses for a fixed sidebar destination; nil for Projects and Tags.
    init?(destination: WorkspaceDestination) {
        switch destination {
        case .list(.inbox): self = .inbox
        case .list(.next): self = .nextActions
        case .list(.waiting): self = .waitingFor
        case .list(.someday): self = .somedayMaybe
        case .date: self = .calendar
        case .history: self = .history
        case .agentRuns: self = .agentRun
        case .project, .tag: return nil
        }
    }
}
