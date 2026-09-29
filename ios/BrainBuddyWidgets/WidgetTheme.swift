import SwiftUI

/// The few brand colours the widget extension needs. The app's design system
/// is not compiled into the extension, so the values are repeated here from
/// the design tokens (slate neutrals, sky-500 primary, rose for due dates).
enum WidgetColor {
    static let sky300 = hex(0x7DD3FC)
    static let sky400 = hex(0x38BDF8)
    static let sky500 = hex(0x0EA5E9)
    static let sky700 = hex(0x0369A1)
    static let rose400 = hex(0xFB7185)
    static let rose700 = hex(0xBE123C)
    static let slate50 = hex(0xF8FAFC)
    static let slate400 = hex(0x94A3B8)
    static let slate500 = hex(0x64748B)
    static let slate900 = hex(0x0F172A)
    static let white = hex(0xFFFFFF)

    /// A `0xRRGGBB` value in sRGB.
    static func hex(_ rgb: UInt32, opacity: Double = 1) -> Color {
        Color(
            .sRGB,
            red: Double((rgb >> 16) & 0xFF) / 255,
            green: Double((rgb >> 8) & 0xFF) / 255,
            blue: Double(rgb & 0xFF) / 255,
            opacity: opacity
        )
    }
}

/// Colours for one appearance. Light values are the design tokens; dark ones
/// are derived from the same slate and sky scales, as in the app. In tinted
/// and clear (accented) or Lock Screen (vibrant) rendering the system recolours
/// content, and views mark their accents with `widgetAccentable()`.
struct WidgetPalette {
    /// Widget surface (`surface-raised` in light).
    let background: Color
    let primaryText: Color
    let secondaryText: Color
    /// Icons and fills in the brand colour.
    let accent: Color
    /// Brand-coloured text, darker than `accent` in light so it stays legible.
    let accentText: Color
    /// Glyphs drawn on an `accent` fill.
    let onAccent: Color
    /// Due today or overdue.
    let due: Color

    init(colorScheme: ColorScheme) {
        if colorScheme == .dark {
            background = WidgetColor.slate900
            primaryText = WidgetColor.slate50
            secondaryText = WidgetColor.slate400
            accent = WidgetColor.sky400
            accentText = WidgetColor.sky300
            onAccent = WidgetColor.slate900
            due = WidgetColor.rose400
        } else {
            background = WidgetColor.white
            primaryText = WidgetColor.slate900
            secondaryText = WidgetColor.slate500
            accent = WidgetColor.sky500
            accentText = WidgetColor.sky700
            onAccent = WidgetColor.white
            due = WidgetColor.rose700
        }
    }
}
