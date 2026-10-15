#if canImport(SwiftUI)
    import SwiftUI

    extension Color {
        public init(_ rgb: RGBColor) {
            self.init(.sRGB, red: rgb.red, green: rgb.green, blue: rgb.blue, opacity: 1)
        }
    }

    /// A role or component colour as a SwiftUI style. It resolves from the view's own
    /// `colorScheme`, so a preview, an `ImageRenderer` snapshot and the running app
    /// all pick the same value: `.foregroundStyle(.coTextPrimary)`.
    public struct CarryOnColorStyle: ShapeStyle {
        public let themed: ThemedColor

        public init(_ themed: ThemedColor) {
            self.themed = themed
        }

        public func color(in scheme: ColorScheme) -> Color {
            Color(scheme == .dark ? themed.dark : themed.light)
        }

        public func resolve(in environment: EnvironmentValues) -> Color {
            color(in: environment.colorScheme)
        }
    }
#endif
