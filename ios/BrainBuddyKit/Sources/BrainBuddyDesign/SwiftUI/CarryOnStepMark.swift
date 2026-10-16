#if canImport(SwiftUI)
    import SwiftUI

    /// The mark in front of a task: an open ring, the one terracotta current step, a
    /// check for done, the waiting clock. `CarryOnStepRow` draws it, and so does any
    /// screen row that needs the same mark inside its own control (a completion button).
    public struct CarryOnStepMark: View {
        typealias Metrics = CarryOnLayout.Row

        let status: CarryOnStepRow.Status

        public init(_ status: CarryOnStepRow.Status) {
            self.status = status
        }

        public var body: some View {
            let size = Metrics.mark
            switch status {
            case .open:
                Circle()
                    .strokeBorder(.coStepDotOpen, lineWidth: Metrics.markStroke)
                    .frame(width: size, height: size)
            case .current:
                Circle()
                    .fill(.coStepDotCurrent)
                    .frame(width: size, height: size)
            case .done:
                Circle()
                    .fill(.coTextDone)
                    .overlay {
                        CheckMark()
                            .stroke(.coBgGround, style: StrokeStyle(lineWidth: 2.6 * 16 / 24, lineCap: .round, lineJoin: .round))
                            .frame(width: 16, height: 16)
                    }
                    .frame(width: size, height: size)
            case .waiting:
                Clock()
                    .stroke(.coMarkOpen, style: StrokeStyle(lineWidth: 1.8, lineCap: .round, lineJoin: .round))
                    .frame(width: size, height: size)
            }
        }
    }

    /// The board's tick, `M5 12.5l4.5 4.5L19 7.5` on a 24 grid.
    private struct CheckMark: Shape {
        func path(in rect: CGRect) -> Path {
            let unit = rect.width / 24
            var path = Path()
            path.move(to: CGPoint(x: 5 * unit, y: 12.5 * unit))
            path.addLine(to: CGPoint(x: 9.5 * unit, y: 17 * unit))
            path.addLine(to: CGPoint(x: 19 * unit, y: 7.5 * unit))
            return path
        }
    }

    /// The board's waiting clock: a circle of radius 8 and hands `M12 7.5V12l3 2` on a 24 grid.
    private struct Clock: Shape {
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
#endif
