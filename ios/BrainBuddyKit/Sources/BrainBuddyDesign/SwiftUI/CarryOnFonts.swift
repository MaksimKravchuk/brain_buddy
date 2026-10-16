#if canImport(SwiftUI) && canImport(CoreText)
    import CoreText
    import Foundation
    import SwiftUI

    /// The bundled Instrument Serif and Instrument Sans (SIL OFL 1.1, `Resources/OFL.txt`).
    public enum CarryOnFonts {
        /// Registers the bundled faces for this process once. Every `Font.carryOn` call
        /// does this itself; call it early only to avoid the first-use cost.
        @discardableResult
        public static func register() -> Bool { registered }

        private static let registered: Bool = {
            let urls = Bundle.module.urls(forResourcesWithExtension: "ttf", subdirectory: nil) ?? []
            for url in urls {
                // A face already registered (a second test bundle in one process) is not an error.
                CTFontManagerRegisterFontsForURL(url as CFURL, .process, nil)
            }
            return !urls.isEmpty
        }()

        /// The height CoreText gives one line of `style` before any line-height rule.
        static func naturalLineHeight(_ style: TypeStyle, size: Double) -> Double {
            register()
            let font = CTFontCreateWithName(style.postScriptName as CFString, size, nil)
            return Double(CTFontGetAscent(font) + CTFontGetDescent(font) + CTFontGetLeading(font))
        }
    }

    extension TextStyleName {
        var swiftUI: Font.TextStyle {
            switch self {
            case .largeTitle: .largeTitle
            case .title: .title
            case .title2: .title2
            case .body: .body
            case .subheadline: .subheadline
            }
        }
    }

    extension EnvironmentValues {
        /// The platform whose sizes Carry On text uses. Defaults to the running one.
        @Entry public var carryOnPlatform: CarryOnPlatform = .current
    }

    extension Font {
        /// A Carry On type style at a platform's size, scaling with Dynamic Type.
        public static func carryOn(_ style: TypeStyle, on platform: CarryOnPlatform = .current) -> Font {
            CarryOnFonts.register()
            return .custom(
                style.postScriptName, size: style.size(for: platform), relativeTo: style.textStyle.swiftUI)
        }
    }

    /// The style's font at the size of the environment's platform.
    struct CarryOnFontModifier: ViewModifier {
        let style: TypeStyle
        @Environment(\.carryOnPlatform) private var platform

        func body(content: Content) -> some View {
            content.font(.carryOn(style, on: platform))
        }
    }

    /// Font, tracking and a CSS-style line box: the extra height of `lineHeight` is
    /// shared between the lines and half of it sits above the first and below the last,
    /// so text takes the same height it takes on the design boards.
    struct CarryOnTextModifier: ViewModifier {
        let style: TypeStyle
        let lineHeight: Double
        @Environment(\.carryOnPlatform) private var platform

        func body(content: Content) -> some View {
            let size = style.size(for: platform)
            let extra = max(0, size * lineHeight - CarryOnFonts.naturalLineHeight(style, size: size))
            return content
                .font(.carryOn(style, on: platform))
                .tracking(size * style.tracking)
                .lineSpacing(extra)
                .padding(.vertical, extra / 2)
        }
    }

    extension View {
        /// The style's font only, for single-line controls whose height is fixed.
        public func carryOnFont(_ style: TypeStyle) -> some View {
            modifier(CarryOnFontModifier(style: style))
        }

        /// The style's font, tracking and line height. A component whose board sets its
        /// own line height (a row, the card's project line) passes that layout token.
        public func carryOnText(_ style: TypeStyle, lineHeight: Double? = nil) -> some View {
            modifier(CarryOnTextModifier(style: style, lineHeight: lineHeight ?? style.lineHeight))
        }
    }
#endif
