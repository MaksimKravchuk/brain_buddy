#if canImport(SwiftUI)
    import SwiftUI

    /// The pill buttons. Primary (terracotta) appears once per screen, secondary is
    /// stone, quiet is text only, strong is basalt/limestone (the one decisive action
    /// on a sheet, board 14) and glassPrimary is the terracotta tint on Liquid Glass
    /// (boards 09 and 13: inside a floating glass bar only). Pressed scales to 0.97
    /// (glassPrimary uses the system's interactive glass instead); disabled is 40 %.
    /// On the Mac (`\.carryOnPlatform`) every kind is the board's 32 pt pill with
    /// 14 pt of side padding (board M10); the label follows the type scale's Mac size.
    public struct CarryOnButtonStyle: ButtonStyle {
        public enum Kind: Sendable {
            case primary, secondary, quiet, strong, glassPrimary
        }

        public let kind: Kind
        public let iconOnly: Bool

        public init(_ kind: Kind, iconOnly: Bool = false) {
            self.kind = kind
            self.iconOnly = iconOnly
        }

        public func makeBody(configuration: Configuration) -> some View {
            CarryOnButtonBody(kind: kind, iconOnly: iconOnly, label: configuration.label, isPressed: configuration.isPressed)
        }
    }

    struct CarryOnButtonBody<Label: View>: View {
        typealias Metrics = CarryOnLayout.Button

        let kind: CarryOnButtonStyle.Kind
        var iconOnly: Bool = false
        let label: Label
        let isPressed: Bool
        @Environment(\.isEnabled) private var isEnabled
        @Environment(\.colorScheme) private var scheme
        @Environment(\.carryOnPlatform) private var platform

        var body: some View {
            HStack(spacing: Metrics.gap) { label }
                .carryOnFont(CarryOnTypeScale.bodyStrong)
                .foregroundStyle(foreground)
                .padding(.horizontal, paddingX)
                .frame(width: compactIcon ? CarryOnLayout.MacAgents.actionSize : nil,
                    height: compactIcon ? CarryOnLayout.MacAgents.actionSize : nil)
                .frame(minHeight: compactIcon ? CarryOnLayout.MacAgents.actionSize : (platform == .mac ? Metrics.macHeight : Metrics.height))
                .modifier(CarryOnButtonSurface(kind: kind, fill: background, glassTint: glassTint))
                .scaleEffect(isPressed && kind != .quiet && kind != .glassPrimary ? Metrics.pressedScale : 1)
                .opacity(isEnabled ? 1 : Metrics.disabledOpacity)
                .contentShape(Capsule())
        }

        private var compactIcon: Bool { iconOnly && platform == .mac }

        private var paddingX: Double {
            if compactIcon { return 0 }
            if platform == .mac { return Metrics.macPaddingX }
            return kind == .quiet ? Metrics.quietPaddingX : Metrics.paddingX
        }

        private var foreground: CarryOnColorStyle {
            switch kind {
            case .primary: .coButtonPrimaryFg
            case .secondary: .coButtonSecondaryFg
            case .quiet: .coTextPrimary
            case .strong: CarryOnColorStyle(CarryOnComponentColor.buttonStrongFg)
            case .glassPrimary: CarryOnColorStyle(CarryOnComponentColor.buttonGlassFg)
            }
        }

        private var background: CarryOnColorStyle? {
            switch kind {
            case .primary: isPressed ? .coButtonPrimaryBgPressed : .coButtonPrimaryBg
            case .secondary: isPressed ? .coButtonSecondaryBgPressed : .coButtonSecondaryBg
            case .quiet, .glassPrimary: nil
            case .strong: CarryOnColorStyle(CarryOnComponentColor.buttonStrongBg)
            }
        }

        /// The accent fill at the board's glass opacity, for `glassEffect`'s tint.
        private var glassTint: Color {
            CarryOnColorStyle(CarryOnComponentColor.buttonGlassTint).color(in: scheme)
                .opacity(Metrics.glassTintOpacity)
        }
    }

    /// A flat capsule fill, or for `glassPrimary` a tinted interactive Liquid Glass
    /// capsule (iOS 26 and macOS 26, the package minimum).
    private struct CarryOnButtonSurface: ViewModifier {
        let kind: CarryOnButtonStyle.Kind
        let fill: CarryOnColorStyle?
        let glassTint: Color

        func body(content: Content) -> some View {
            if kind == .glassPrimary {
                content.glassEffect(.regular.tint(glassTint).interactive(), in: .capsule)
            } else {
                content.background {
                    if let fill { Capsule().fill(fill) }
                }
            }
        }
    }

    extension ButtonStyle where Self == CarryOnButtonStyle {
        public static var carryOnPrimary: CarryOnButtonStyle { CarryOnButtonStyle(.primary) }
        public static var carryOnSecondary: CarryOnButtonStyle { CarryOnButtonStyle(.secondary) }
        /// M29's compact circular secondary controls, sharing the pill's interaction states.
        public static var carryOnSecondaryIcon: CarryOnButtonStyle { CarryOnButtonStyle(.secondary, iconOnly: true) }
        public static var carryOnQuiet: CarryOnButtonStyle { CarryOnButtonStyle(.quiet) }
        public static var carryOnStrong: CarryOnButtonStyle { CarryOnButtonStyle(.strong) }
        public static var carryOnGlassPrimary: CarryOnButtonStyle { CarryOnButtonStyle(.glassPrimary) }
    }
#endif
