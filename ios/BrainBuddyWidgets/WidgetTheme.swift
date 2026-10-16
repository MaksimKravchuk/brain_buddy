import BrainBuddyDesign
import SwiftUI

/// Colours for one appearance, read from the Carry On roles the app uses, so
/// a widget matches the boards in light and dark. In tinted and clear
/// (accented) or Lock Screen (vibrant) rendering the system recolours
/// content, and views mark their accents with `widgetAccentable()`.
struct WidgetPalette {
    /// Widget surface (`surface-card`).
    let background: Color
    let primaryText: Color
    let secondaryText: Color
    /// The one next step's fill (`accent-fill`).
    let accent: Color
    /// Accent-coloured text (`text-accent`), legible on the surface.
    let accentText: Color
    /// Glyphs drawn on an `accent` fill.
    let onAccent: Color
    /// Due today or overdue (`status-danger`).
    let due: Color

    init(colorScheme: ColorScheme) {
        func role(_ themed: ThemedColor) -> Color {
            Color(colorScheme == .dark ? themed.dark : themed.light)
        }
        background = role(CarryOnRole.surfaceCard)
        primaryText = role(CarryOnRole.textPrimary)
        secondaryText = role(CarryOnRole.textSecondary)
        accent = role(CarryOnRole.accentFill)
        accentText = role(CarryOnRole.textAccent)
        onAccent = role(CarryOnRole.onAccent)
        due = role(CarryOnRole.statusDanger)
    }
}

/// The Instrument faces at the widget board's own sizes (board 12), which the
/// type scale has no style for.
enum WidgetFont {
    /// Instrument Serif, for the Inbox count.
    static func voice(size: CGFloat) -> Font {
        CarryOnFonts.register()
        return .custom(CarryOnFontFace.voice.postScriptName(weight: 400), size: size)
    }

    /// Instrument Sans, for the label and the line under the count.
    static func action(size: CGFloat, weight: Int = 400) -> Font {
        CarryOnFonts.register()
        return .custom(CarryOnFontFace.action.postScriptName(weight: weight), size: size)
    }
}
