#if canImport(SwiftUI)
    import SwiftUI

    /// Metadata in words. Colour never carries meaning alone: a due or overdue chip
    /// says so in its text, and the tone only repeats it. A selected chip (the chosen
    /// quick day, board 14) is inverted and semibold; the screen also announces the
    /// selection to VoiceOver, so colour is not the only cue.
    public struct CarryOnChip: View {
        public enum Tone: Sendable {
            case plain, dueSoon, overdue
        }

        /// `quick` is the taller chip of a row of preset choices.
        public enum Size: Sendable {
            case standard, quick
        }

        typealias Metrics = CarryOnLayout.Chip

        let text: String
        let tone: Tone
        let dot: RGBColor?
        let size: Size
        let isSelected: Bool

        public init(
            _ text: String, tone: Tone = .plain, dot: RGBColor? = nil,
            size: Size = .standard, isSelected: Bool = false
        ) {
            self.text = text
            self.tone = tone
            self.dot = dot
            self.size = size
            self.isSelected = isSelected
        }

        public var body: some View {
            HStack(spacing: Metrics.gap) {
                if let dot { CarryOnProjectDot(dot) }
                Text(text)
                    .carryOnFont(isSelected ? CarryOnTypeScale.metaStrong : CarryOnTypeScale.meta)
                    .lineLimit(1)
            }
            .foregroundStyle(foreground)
            .padding(.horizontal, size == .quick ? CarryOnLayout.QuickChip.paddingX : Metrics.paddingX)
            .frame(minHeight: size == .quick ? CarryOnLayout.QuickChip.height : Metrics.height)
            .background(fill, in: Capsule())
        }

        private var fill: CarryOnColorStyle {
            isSelected ? .coChipSelectedBg : .coChipBg
        }

        private var foreground: CarryOnColorStyle {
            if isSelected { return .coChipSelectedFg }
            switch tone {
            case .plain: return .coChipFg
            case .dueSoon: return .coChipDueFg
            case .overdue: return .coChipOverdueFg
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
