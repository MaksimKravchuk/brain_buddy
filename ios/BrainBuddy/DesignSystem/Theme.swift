import BrainBuddyDesign
import SwiftUI
import UIKit

// MARK: - Colour

/// Brand colour tokens, mapped onto the Carry On design system.
///
/// Every value is read from the generated tokens in `BrainBuddyDesign`
/// (`CarryOnRole`, `CarryOnComponentColor`, `CarryOnProjectColor`); nothing here
/// types a hex. Carry On swaps roles between light and dark rather than
/// inventing colours, so each `BBColor` resolves its role's light or dark value
/// through UIKit traits and follows the system appearance.
///
/// Carry On reserves terracotta for the one next step, so the app tint, brand
/// text and filled controls are basalt (limestone in dark mode), not an accent.
/// Carry On defines no Increase Contrast variants, so every `highContrast:`
/// parameter below is nil.
///
/// Grey text (`textSecondary`, `textTertiary`, `success`) is 3.98:1 on stone
/// (`surfaceSunken`, `brandSoft`, `hairline`, `tagBackground`, `dueBackground`).
/// That is the board's colour and is kept on purpose (`ios/AGENTS.md`).
enum BBColor {
    // MARK: Brand

    /// text-primary: basalt in light mode, limestone in dark mode. The app tint.
    static let brand = color(Tone(CarryOnRole.textPrimary))
    /// surface-selected. Selected rows, soft brand fills.
    static let brandSoft = color(Tone(CarryOnRole.surfaceSelected))
    /// Brand-coloured text and symbols (text-primary). The app's tint.
    static let brandText = color(brandTextTone)
    /// `brandText` for UIKit views (the Smart Add highlight).
    static var brandTextUIColor: UIColor { uiColor(brandTextTone) }
    /// text-primary. Fills that carry `onBrand` text or a glyph: prominent
    /// buttons, the Inbox count pill, the completed check.
    static let brandFill = color(brandTextTone)
    private static let brandTextTone = Tone(CarryOnRole.textPrimary)
    /// text-secondary. Sparing secondary accents.
    static let secondary = color(Tone(CarryOnRole.textSecondary))
    /// bg-ground. Text and symbols placed on a `brandFill`; the inverse of the
    /// fill in both modes.
    static let onBrand = color(Tone(CarryOnRole.bgGround))

    // MARK: Surfaces

    /// bg-ground. The page background; always flat.
    static let surfaceBase = color(Tone(CarryOnRole.bgGround))
    /// bg-sunken. Panels and grouped backgrounds.
    static let surfaceSunken = color(Tone(CarryOnRole.bgSunken))
    /// surface-card. Rows, cards and dialogs.
    static let surfaceRaised = color(Tone(CarryOnRole.surfaceCard))

    // MARK: Text

    /// text-primary. Primary body text and titles.
    static let textPrimary = color(Tone(CarryOnRole.textPrimary))
    /// text-secondary. Secondary copy.
    static let textSecondary = color(Tone(CarryOnRole.textSecondary))
    /// text-secondary. Captions and row metadata.
    static let textTertiary = color(Tone(CarryOnRole.textSecondary), highContrast: nil)
    /// mark-open. Placeholders and plain counts.
    static let textPlaceholder = color(Tone(CarryOnRole.markOpen), highContrast: nil)

    // MARK: Lines

    /// control-quiet. The universal hairline, and the fill of quiet controls.
    static let hairline = color(Tone(CarryOnRole.controlQuiet), highContrast: nil)
    /// control-quiet-pressed. Pressed hairline.
    static let hairlineStrong = color(Tone(CarryOnRole.controlQuietPressed), highContrast: nil)
    /// mark-open. The outline of a control that is drawn as a shape only, such
    /// as the open completion circle.
    static let controlStroke = color(Tone(CarryOnRole.markOpen), highContrast: nil)

    // MARK: Semantics

    /// text-done.
    static let success = color(Tone(CarryOnRole.textDone))
    static let successBackground = color(Tone(CarryOnRole.surfaceSelected))
    static let successBorder = color(Tone(CarryOnRole.controlQuiet))
    static let successText = color(Tone(CarryOnRole.textPrimary))

    /// status-warning.
    static let warning = color(Tone(CarryOnRole.statusWarning))
    static let warningBackground = color(Tone(CarryOnRole.bgSunken))
    static let warningBorder = color(Tone(CarryOnRole.controlQuiet))
    static let warningText = color(Tone(CarryOnRole.statusWarning))

    /// status-danger.
    static let danger = color(Tone(CarryOnRole.statusDanger))
    static let dangerBackground = color(Tone(CarryOnRole.bgSunken))
    static let dangerBorder = color(Tone(CarryOnRole.controlQuiet))
    static let dangerText = color(Tone(CarryOnRole.statusDanger))

    /// text-secondary.
    static let info = color(Tone(CarryOnRole.textSecondary))
    static let infoBackground = color(Tone(CarryOnRole.bgSunken))
    static let infoBorder = color(Tone(CarryOnRole.controlQuiet))
    static let infoText = color(Tone(CarryOnRole.textPrimary))

    // MARK: Chips

    /// Due-date chip. Only for real deadlines; the foreground is the Carry On
    /// due colour (chip-due-fg), not red.
    static let dueBackground = color(Tone(CarryOnComponentColor.chipBg))
    static let dueBorder = color(Tone(CarryOnComponentColor.chipBg))
    static let dueText = color(Tone(CarryOnComponentColor.chipDueFg))
    /// chip-overdue-fg. The due date of an open task that is past due.
    static let overdueText = color(Tone(CarryOnComponentColor.chipOverdueFg))
    /// step-text-done. The struck-through title of a finished task.
    static let stepTextDone = color(Tone(CarryOnComponentColor.stepTextDone))

    /// Tag pill inside task rows.
    static let tagBackground = color(Tone(CarryOnComponentColor.chipBg))
    static let tagText = color(Tone(CarryOnComponentColor.chipFg))

    // MARK: Projects

    /// A project's colour. Carry On project colours are shown as stored; a colour
    /// saved before Carry On (the old ten-colour palette) is shown as the Carry On
    /// colour at the same index (`legacyProjectPalette`). Projects without a
    /// colour, or with a value that is not `#RRGGBB`, get the neutral `projectFallback`.
    static func project(_ hex: String?) -> Color {
        guard let hex else { return projectFallback }
        let shown = displayedProjectColor(forStored: hex)?.hex ?? hex
        guard let parsed = Color(validatingHex: shown) else { return projectFallback }
        return parsed
    }

    /// mark-open, the neutral dot for a project without a colour.
    static let projectFallback = color(Tone(CarryOnRole.markOpen))

    /// Colours offered when creating or recolouring a project, as `#RRGGBB`.
    static let projectColorPalette: [String] = projectColorOptions.map(\.hex)

    /// The ten Carry On project colours with spoken names, for pickers and VoiceOver.
    static let projectColorOptions: [BBProjectColor] = CarryOnProjectColor.all.map { entry in
        BBProjectColor(hex: BBColor.hexString(entry.color), name: BBColor.spokenName(entry.name))
    }

    /// The project palette before Carry On, in order. Stored colours are never
    /// rewritten: a value in this table is only displayed as the Carry On colour
    /// at the same index in `projectColorOptions` (Sky → Lake, Indigo → Slate,
    /// Emerald → Moss, Amber → Ochre, Rose → Plum, Violet → Heather, Teal → Sage,
    /// Orange → Sand, Pink → Rosewood, Slate → Dust).
    static let legacyProjectPalette: [String] = [
        "#0EA5E9", "#6366F1", "#10B981", "#F59E0B", "#E11D48",
        "#8B5CF6", "#14B8A6", "#F97316", "#EC4899", "#64748B",
    ]

    /// The Carry On colour a stored value is shown as: itself when it is already
    /// a Carry On colour, the colour at the same index when it is an old-palette
    /// value, and nil for any other (custom) value. Pure; reads and writes nothing.
    static func displayedProjectColor(forStored hex: String?) -> BBProjectColor? {
        guard let hex else { return nil }
        var wanted = hex.trimmingCharacters(in: .whitespaces).uppercased()
        if !wanted.hasPrefix("#") { wanted = "#" + wanted }
        if let current = projectColorOptions.first(where: { $0.hex == wanted }) { return current }
        guard let index = legacyProjectPalette.firstIndex(of: wanted), index < projectColorOptions.count
        else { return nil }
        return projectColorOptions[index]
    }

    /// The spoken name of a palette colour (old-palette values included, under
    /// their Carry On name), or nil for a custom value.
    static func projectColorName(for hex: String?) -> String? {
        displayedProjectColor(forStored: hex)?.name
    }

    private static func hexString(_ rgb: RGBColor) -> String {
        String(format: "#%06X", rgb.hex)
    }

    private static func spokenName(_ token: String) -> String {
        token.prefix(1).uppercased() + token.dropFirst()
    }

    // MARK: Construction

    /// A role's light and dark values as `0xRRGGBB`.
    fileprivate struct Tone {
        let light: UInt32
        let dark: UInt32

        init(_ themed: ThemedColor) {
            self.light = themed.light.hex
            self.dark = themed.dark.hex
        }
    }

    private static func color(_ normal: Tone, highContrast: Tone? = nil) -> Color {
        Color(uiColor: uiColor(normal, highContrast: highContrast))
    }

    private static func uiColor(_ normal: Tone, highContrast: Tone? = nil) -> UIColor {
        UIColor { traits in
            let tone = traits.accessibilityContrast == .high ? (highContrast ?? normal) : normal
            if traits.userInterfaceStyle == .dark {
                return UIColor(bbRGB: tone.dark, alpha: 1)
            }
            return UIColor(bbRGB: tone.light, alpha: 1)
        }
    }
}

/// One entry of the project colour palette.
struct BBProjectColor: Hashable, Sendable, Identifiable {
    /// `#RRGGBB`, uppercase.
    let hex: String
    /// Spoken name, for example "Lake".
    let name: String
    var id: String { hex }
    var color: Color { BBColor.project(hex) }
}

extension Color {
    /// A colour from `#RGB`, `#RRGGBB` or `#RRGGBBAA` (the `#` is optional).
    /// Invalid input yields the neutral dust project colour rather than crashing, because
    /// project colours are free-form user data.
    init(hex: String) {
        self = Color(validatingHex: hex) ?? Color(CarryOnProjectColor.dust)
    }

    /// A colour from `#RGB`, `#RRGGBB` or `#RRGGBBAA`, or nil when `hex` is
    /// not one of those forms.
    init?(validatingHex hex: String) {
        guard let rgba = BBHex.rgba(hex) else { return nil }
        self = Color(.sRGB, red: rgba.red, green: rgba.green, blue: rgba.blue, opacity: rgba.alpha)
    }
}

/// Hex colour parsing, kept free of UI types.
enum BBHex {
    struct RGBA: Hashable, Sendable {
        let red: Double
        let green: Double
        let blue: Double
        let alpha: Double
    }

    static func rgba(_ string: String) -> RGBA? {
        var digits = Substring(string.trimmingCharacters(in: .whitespacesAndNewlines))
        if digits.hasPrefix("#") { digits = digits.dropFirst() }
        guard digits.allSatisfy(\.isHexDigit) else { return nil }
        let expanded: String
        switch digits.count {
        case 3: expanded = digits.map { "\($0)\($0)" }.joined() + "FF"
        case 6: expanded = String(digits) + "FF"
        case 8: expanded = String(digits)
        default: return nil
        }
        guard let value = UInt64(expanded, radix: 16) else { return nil }
        return RGBA(
            red: Double((value >> 24) & 0xFF) / 255,
            green: Double((value >> 16) & 0xFF) / 255,
            blue: Double((value >> 8) & 0xFF) / 255,
            alpha: Double(value & 0xFF) / 255
        )
    }
}

extension UIColor {
    fileprivate convenience init(bbRGB rgb: UInt32, alpha: CGFloat) {
        self.init(
            red: CGFloat((rgb >> 16) & 0xFF) / 255,
            green: CGFloat((rgb >> 8) & 0xFF) / 255,
            blue: CGFloat(rgb & 0xFF) / 255,
            alpha: alpha
        )
    }
}

// MARK: - Spacing, radii, metrics

/// The 4-pt spacing scale (`--bb-space-*`). `s1`…`s8` mirror the token names;
/// the size aliases are the same values.
enum BBSpacing {
    static let s1: CGFloat = 4
    static let s2: CGFloat = 8
    static let s3: CGFloat = 12
    static let s4: CGFloat = 16
    static let s5: CGFloat = 20
    static let s6: CGFloat = 24
    static let s8: CGFloat = 32

    static let xxs: CGFloat = 4
    static let xs: CGFloat = 8
    static let sm: CGFloat = 12
    static let md: CGFloat = 16
    static let lg: CGFloat = 20
    static let xl: CGFloat = 24
    static let xxl: CGFloat = 32
}

/// Corner radii from the design system.
enum BBRadius {
    /// Inputs and menu items.
    static let input: CGFloat = 6
    /// Buttons and chips-as-buttons.
    static let chip: CGFloat = 8
    /// Task rows.
    static let row = CGFloat(CarryOnLayout.Row.radius)
    /// Mobile task cards.
    static let card = CGFloat(CarryOnRadius.md)
    /// Shells and auth cards.
    static let shell: CGFloat = 16
    /// Dialogs, panels and toasts.
    static let dialog: CGFloat = 20
}

enum BBMetrics {
    /// Minimum touch target (design system: 44 pt+).
    static let hitTarget: CGFloat = 44
    /// Visual diameter of the completion circle before Dynamic Type scaling.
    static let completionCircle: CGFloat = 22
    /// The largest the completion circle grows with Dynamic Type, so it stays
    /// inside its 44 pt target at accessibility sizes.
    static let completionCircleMax: CGFloat = 36
    /// Project colour dot before Dynamic Type scaling.
    static let projectDot: CGFloat = 8
}

// MARK: - Motion

/// The brand motion: `cubic-bezier(0.22, 1, 0.36, 1)` ("ease-smooth"), soft
/// arrival with no overshoot, 150–250 ms. Applies to our own animations only;
/// Liquid Glass morphing keeps the system springs (docs deviation 4).
enum BBMotion {
    enum Speed: Sendable, CaseIterable {
        /// 150 ms. Small state changes (press, toggles).
        case quick
        /// 200 ms. The default.
        case base
        /// 250 ms. Rows arriving or leaving.
        case settle

        var duration: Double {
            switch self {
            case .quick: 0.15
            case .base: 0.2
            case .settle: 0.25
            }
        }
    }

    /// The brand curve at `speed`.
    static func curve(_ speed: Speed) -> Animation {
        .timingCurve(0.22, 1, 0.36, 1, duration: speed.duration)
    }

    static var quick: Animation { curve(.quick) }
    static var base: Animation { curve(.base) }
    static var settle: Animation { curve(.settle) }

    /// The brand curve at `speed`, or nil (no animation) with Reduce Motion on.
    static func animation(_ speed: Speed = .base, reduceMotion: Bool) -> Animation? {
        reduceMotion ? nil : curve(speed)
    }

    /// `animation`, or nil (no animation) with Reduce Motion on.
    static func animation(_ animation: Animation, reduceMotion: Bool) -> Animation? {
        reduceMotion ? nil : animation
    }
}

private struct BBAnimationModifier<Value: Equatable>: ViewModifier {
    let speed: BBMotion.Speed
    let value: Value
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func body(content: Content) -> some View {
        content.animation(BBMotion.animation(speed, reduceMotion: reduceMotion), value: value)
    }
}

// MARK: - Typography

/// The brand type scale on the Carry On styles: Instrument Serif for the voice
/// (display, title), Instrument Sans for everything else. Each is a
/// `Font.carryOn` style that scales with Dynamic Type. Carry On has six styles,
/// so several names share one: subtitle and bodyMedium are `bodyStrong`; body and
/// rowTitle are `body`; secondary, meta, caption, micro and label are `meta`.
enum BBFont {
    /// Empty-state headlines.
    static let display = Font.carryOn(CarryOnTypeScale.display)
    /// Pane and dialog titles.
    static let title = Font.carryOn(CarryOnTypeScale.title)
    static let subtitle = Font.carryOn(CarryOnTypeScale.bodyStrong)
    static let body = Font.carryOn(CarryOnTypeScale.body)
    static let bodyMedium = Font.carryOn(CarryOnTypeScale.bodyStrong)
    /// Task titles in rows.
    static let rowTitle = Font.carryOn(CarryOnTypeScale.body)
    /// Secondary lines under a title.
    static let secondary = Font.carryOn(CarryOnTypeScale.meta)
    /// Row metadata (project, list, waiting note).
    static let meta = Font.carryOn(CarryOnTypeScale.meta)
    /// Chips and pills.
    static let caption = Font.carryOn(CarryOnTypeScale.meta)
    static let micro = Font.carryOn(CarryOnTypeScale.meta)
    /// Section labels, in sentence case; see `bbSectionLabel()`.
    static let label = Font.carryOn(CarryOnTypeScale.meta)
}

// MARK: - View helpers

extension View {
    /// Section labels ("Projects", "Tags"): sentence case in text-secondary.
    func bbSectionLabel() -> some View {
        font(BBFont.label)
            .foregroundStyle(BBColor.textSecondary)
    }

    /// A Carry On card: surface-card fill, no shadow and no stroke. Content
    /// only; chrome uses Liquid Glass instead.
    func bbCard(cornerRadius: CGFloat = BBRadius.row) -> some View {
        background {
            RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                .fill(BBColor.surfaceRaised)
        }
    }

    /// The flat brand page background behind a screen.
    func bbScreenBackground() -> some View {
        background {
            BBColor.surfaceBase.ignoresSafeArea()
        }
    }

    /// For `List` / `Form`: hides the system grouped background and shows the
    /// brand page background instead.
    func bbListBackground() -> some View {
        scrollContentBackground(.hidden)
            .background {
                BBColor.surfaceBase.ignoresSafeArea()
            }
    }

    /// Animates changes to `value` on the brand curve; no animation with
    /// Reduce Motion on.
    func bbAnimation<Value: Equatable>(_ speed: BBMotion.Speed = .base, value: Value) -> some View {
        modifier(BBAnimationModifier(speed: speed, value: value))
    }
}
