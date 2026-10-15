#if canImport(SwiftUI)
    import SwiftUI

    /// The pill buttons. Primary (terracotta) appears once per screen, secondary is
    /// stone, quiet is text only. Pressed scales to 0.97; disabled is 40 %.
    public struct CarryOnButtonStyle: ButtonStyle {
        public enum Kind: Sendable {
            case primary, secondary, quiet
        }

        public let kind: Kind

        public init(_ kind: Kind) {
            self.kind = kind
        }

        public func makeBody(configuration: Configuration) -> some View {
            CarryOnButtonBody(kind: kind, label: configuration.label, isPressed: configuration.isPressed)
        }
    }

    struct CarryOnButtonBody<Label: View>: View {
        typealias Metrics = CarryOnLayout.Button

        let kind: CarryOnButtonStyle.Kind
        let label: Label
        let isPressed: Bool
        @Environment(\.isEnabled) private var isEnabled

        var body: some View {
            HStack(spacing: Metrics.gap) { label }
                .carryOnFont(CarryOnTypeScale.bodyStrong)
                .foregroundStyle(foreground)
                .padding(.horizontal, kind == .quiet ? Metrics.quietPaddingX : Metrics.paddingX)
                .frame(height: Metrics.height)
                .background {
                    if let background { Capsule().fill(background) }
                }
                .scaleEffect(isPressed && kind != .quiet ? Metrics.pressedScale : 1)
                .opacity(isEnabled ? 1 : Metrics.disabledOpacity)
                .contentShape(Capsule())
        }

        private var foreground: CarryOnColorStyle {
            switch kind {
            case .primary: .coButtonPrimaryFg
            case .secondary: .coButtonSecondaryFg
            case .quiet: .coTextPrimary
            }
        }

        private var background: CarryOnColorStyle? {
            switch kind {
            case .primary: isPressed ? .coButtonPrimaryBgPressed : .coButtonPrimaryBg
            case .secondary: isPressed ? .coButtonSecondaryBgPressed : .coButtonSecondaryBg
            case .quiet: nil
            }
        }
    }

    extension ButtonStyle where Self == CarryOnButtonStyle {
        public static var carryOnPrimary: CarryOnButtonStyle { CarryOnButtonStyle(.primary) }
        public static var carryOnSecondary: CarryOnButtonStyle { CarryOnButtonStyle(.secondary) }
        public static var carryOnQuiet: CarryOnButtonStyle { CarryOnButtonStyle(.quiet) }
    }
#endif
