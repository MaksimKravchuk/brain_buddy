#if canImport(SwiftUI)
    import SwiftUI

    /// A task row. Done is dust and struck through, waiting is dust with a name, and
    /// only the current step gets terracotta.
    public struct CarryOnStepRow: View {
        public enum Status: Sendable {
            case open, current, done, waiting
        }

        typealias Metrics = CarryOnLayout.Row

        let title: String
        let detail: String?
        let status: Status
        let isSelected: Bool
        @Environment(\.colorScheme) private var colorScheme

        public init(_ title: String, detail: String? = nil, status: Status = .open, isSelected: Bool = false) {
            self.title = title
            self.detail = detail
            self.status = status
            self.isSelected = isSelected
        }

        public var body: some View {
            HStack(alignment: .center, spacing: Metrics.gap) {
                mark
                VStack(alignment: .leading, spacing: Metrics.metaGap) {
                    titleText
                    if let detail {
                        Text(detail)
                            .carryOnText(CarryOnTypeScale.meta, lineHeight: Metrics.lineHeight)
                            .foregroundStyle(.coTextSecondary)
                    }
                }
                Spacer(minLength: 0)
            }
            .padding(.vertical, Metrics.paddingY)
            .padding(.horizontal, Metrics.paddingX)
            .background(
                isSelected ? CarryOnColorStyle.coRowBgSelected : .coRowBg,
                in: RoundedRectangle(cornerRadius: Metrics.radius, style: .continuous)
            )
        }

        private var titleText: some View {
            let style = status == .current ? CarryOnTypeScale.bodyStrong : CarryOnTypeScale.body
            let done = CarryOnColorStyle.coStepTextDone.color(in: colorScheme)
            return Text(title)
                .strikethrough(status == .done, color: done)
                .carryOnText(style, lineHeight: Metrics.lineHeight)
                .foregroundStyle(titleColor)
        }

        private var titleColor: CarryOnColorStyle {
            switch status {
            case .open, .current: .coTextPrimary
            case .done: .coStepTextDone
            case .waiting: .coTextSecondary
            }
        }

        @ViewBuilder private var mark: some View {
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
