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
                CarryOnStepMark(status)
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
    }
#endif
