#if canImport(SwiftUI)
    import SwiftUI

    /// Metadata in words. Colour never carries meaning alone: a due or overdue chip
    /// says so in its text, and the tone only repeats it.
    public struct CarryOnChip: View {
        public enum Tone: Sendable {
            case plain, dueSoon, overdue
        }

        typealias Metrics = CarryOnLayout.Chip

        let text: String
        let tone: Tone
        let dot: RGBColor?

        public init(_ text: String, tone: Tone = .plain, dot: RGBColor? = nil) {
            self.text = text
            self.tone = tone
            self.dot = dot
        }

        public var body: some View {
            HStack(spacing: Metrics.gap) {
                if let dot { CarryOnProjectDot(dot) }
                Text(text)
                    .carryOnFont(CarryOnTypeScale.meta)
                    .lineLimit(1)
            }
            .foregroundStyle(foreground)
            .padding(.horizontal, Metrics.paddingX)
            .frame(height: Metrics.height)
            .background(.coChipBg, in: Capsule())
        }

        private var foreground: CarryOnColorStyle {
            switch tone {
            case .plain: .coChipFg
            case .dueSoon: .coChipDueFg
            case .overdue: .coChipOverdueFg
            }
        }
    }

    /// A project's colour. Dots only, never text.
    public struct CarryOnProjectDot: View {
        let color: RGBColor
        let size: Double

        public init(_ color: RGBColor, size: Double = CarryOnLayout.Chip.dot) {
            self.color = color
            self.size = size
        }

        public var body: some View {
            Circle()
                .fill(Color(color))
                .frame(width: size, height: size)
        }
    }
#endif
