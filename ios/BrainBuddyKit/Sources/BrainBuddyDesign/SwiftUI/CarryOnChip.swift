#if canImport(SwiftUI)
    import SwiftUI

    /// Metadata in words. Colour never carries meaning alone: a due or overdue chip
    /// says so in its text, and the tone only repeats it. A selected chip (the chosen
    /// quick day, board 14) is inverted and semibold; the screen also announces the
    /// selection to VoiceOver, so colour is not the only cue.
    ///
    /// On the Mac (`\.carryOnPlatform`, board M10) both sizes are one 26 pt chip with
    /// 13 pt text, and a selected chip keeps the regular weight: the inversion alone
    /// marks it.
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
        @Environment(\.carryOnPlatform) private var platform

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
                    .font(font)
                    .lineLimit(1)
            }
            .foregroundStyle(foreground)
            .padding(.horizontal, paddingX)
            .frame(minHeight: height)
            .background(fill, in: Capsule())
        }

        private var isQuick: Bool { size == .quick && platform != .mac }

        private var paddingX: Double { isQuick ? CarryOnLayout.QuickChip.paddingX : Metrics.paddingX }

        private var height: Double {
            if platform == .mac { return Metrics.macHeight }
            return isQuick ? CarryOnLayout.QuickChip.height : Metrics.height
        }

        /// meta (metaStrong when selected) at the platform's size; on the Mac the
        /// regular face at the chip's own 13 pt, which the type scale has no style for.
        private var font: Font {
            if platform == .mac {
                CarryOnFonts.register()
                let meta = CarryOnTypeScale.meta
                return .custom(meta.postScriptName, size: Metrics.macFontSize, relativeTo: meta.textStyle.swiftUI)
            }
            return .carryOn(isSelected ? CarryOnTypeScale.metaStrong : CarryOnTypeScale.meta, on: platform)
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
