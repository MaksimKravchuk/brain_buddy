import SwiftUI
import UIKit

// MARK: - Colour

/// Brand colour tokens.
///
/// Light values are copied verbatim from the design system source of truth,
/// `.claude/skills/brain-buddy-design/colors_and_type.css` (mirrored for the
/// Expo app in `mobile/src/theme/tokens.ts`).
///
/// DARK VALUES ARE DERIVED, NEEDS SIGN-OFF: the design system defines light
/// tokens only (docs/native-ios-app.md, deviation 2). Dark counterparts come
/// from the same Tailwind slate / sky / indigo / emerald / amber / rose scales:
/// surfaces step up in lightness with elevation (sunken `#0B1120` < base
/// `#0F172A` < raised `#1E293B`), text uses slate-100/300/400, hairlines
/// slate-700, the sky brand stays `#0EA5E9`, and semantic backgrounds are the
/// dim 950 shades with 300-level text.
///
/// With Increase Contrast on, tertiary text, placeholders and hairlines step
/// one shade stronger so metadata stays legible.
enum BBColor {
    // MARK: Brand

    /// sky-500. Interactive accents, selection, the Inbox badge, completed checks.
    static let brand = color(Tone(0x0EA5E9, 0x0EA5E9))
    /// sky-500 at 10% (18% in dark mode). Selected rows, soft brand fills.
    static let brandSoft = color(Tone(0x0EA5E9, 0x0EA5E9, lightAlpha: 0.10, darkAlpha: 0.18))
    /// Brand-coloured text that meets contrast on the base surfaces
    /// (sky-700 in light mode, sky-400 in dark mode).
    static let brandText = color(Tone(0x0369A1, 0x38BDF8))
    /// indigo-500. Sparing secondary accents.
    static let secondary = color(Tone(0x6366F1, 0x818CF8))
    /// Text and symbols placed on a `brand` fill.
    static let onBrand = Color.white

    // MARK: Surfaces

    /// slate-50. The page background; always flat.
    static let surfaceBase = color(Tone(0xF8FAFC, 0x0F172A))
    /// slate-100. Panels and grouped backgrounds.
    static let surfaceSunken = color(Tone(0xF1F5F9, 0x0B1120))
    /// White. Rows, cards and dialogs.
    static let surfaceRaised = color(Tone(0xFFFFFF, 0x1E293B))

    // MARK: Text

    /// slate-900. Primary body text and titles.
    static let textPrimary = color(Tone(0x0F172A, 0xF1F5F9))
    /// slate-700. Secondary copy.
    static let textSecondary = color(Tone(0x334155, 0xCBD5E1))
    /// slate-500. Captions and row metadata.
    static let textTertiary = color(Tone(0x64748B, 0x94A3B8), highContrast: Tone(0x475569, 0xCBD5E1))
    /// slate-400. Placeholders and plain counts.
    static let textPlaceholder = color(Tone(0x94A3B8, 0x64748B), highContrast: Tone(0x64748B, 0x94A3B8))

    // MARK: Lines

    /// slate-200. The universal hairline.
    static let hairline = color(Tone(0xE2E8F0, 0x334155), highContrast: Tone(0xCBD5E1, 0x475569))
    /// slate-300. Hover / pressed hairline and the open completion circle.
    static let hairlineStrong = color(Tone(0xCBD5E1, 0x475569), highContrast: Tone(0x94A3B8, 0x64748B))

    // MARK: Semantics

    static let success = color(Tone(0x10B981, 0x34D399))
    static let successBackground = color(Tone(0xECFDF5, 0x022C22))
    static let successBorder = color(Tone(0xA7F3D0, 0x065F46))
    static let successText = color(Tone(0x065F46, 0x6EE7B7))

    static let warning = color(Tone(0xD97706, 0xFBBF24))
    static let warningBackground = color(Tone(0xFFFBEB, 0x451A03))
    static let warningBorder = color(Tone(0xFDE68A, 0x92400E))
    static let warningText = color(Tone(0x92400E, 0xFCD34D))

    static let danger = color(Tone(0xE11D48, 0xFB7185))
    static let dangerBackground = color(Tone(0xFFF1F2, 0x4C0519))
    static let dangerBorder = color(Tone(0xFECDD3, 0x9F1239))
    static let dangerText = color(Tone(0x9F1239, 0xFDA4AF))

    static let info = color(Tone(0x0EA5E9, 0x38BDF8))
    static let infoBackground = color(Tone(0xF0F9FF, 0x082F49))
    static let infoBorder = color(Tone(0xBAE6FD, 0x075985))
    static let infoText = color(Tone(0x0369A1, 0x7DD3FC))

    // MARK: Chips

    /// Due-date chip (rose family). Only for real deadlines.
    static let dueBackground = color(Tone(0xFFF1F2, 0x4C0519))
    static let dueBorder = color(Tone(0xFECDD3, 0x881337))
    static let dueText = color(Tone(0xBE123C, 0xFDA4AF))

    /// Tag pill inside task rows.
    static let tagBackground = color(Tone(0xF1F5F9, 0x334155))
    static let tagText = color(Tone(0x475569, 0xCBD5E1))

    // MARK: Projects

    /// A project's colour token, or the neutral slate-300 dot the web uses for
    /// projects without a colour (or with a value that is not `#RRGGBB`).
    static func project(_ hex: String?) -> Color {
        guard let hex, let parsed = Color(validatingHex: hex) else { return projectFallback }
        return parsed
    }

    static let projectFallback = color(Tone(0xCBD5E1, 0x64748B))

    /// Colours offered when creating or recolouring a project, as `#RRGGBB`.
    static let projectColorPalette: [String] = projectColorOptions.map(\.hex)

    /// The palette with spoken names, for pickers and VoiceOver.
    static let projectColorOptions: [BBProjectColor] = [
        BBProjectColor(hex: "#0EA5E9", name: "Sky"),
        BBProjectColor(hex: "#6366F1", name: "Indigo"),
        BBProjectColor(hex: "#10B981", name: "Emerald"),
        BBProjectColor(hex: "#F59E0B", name: "Amber"),
        BBProjectColor(hex: "#E11D48", name: "Rose"),
        BBProjectColor(hex: "#8B5CF6", name: "Violet"),
        BBProjectColor(hex: "#14B8A6", name: "Teal"),
        BBProjectColor(hex: "#F97316", name: "Orange"),
        BBProjectColor(hex: "#EC4899", name: "Pink"),
        BBProjectColor(hex: "#64748B", name: "Slate"),
    ]

    /// The spoken name of a palette colour, or nil for a custom value.
    static func projectColorName(for hex: String?) -> String? {
        guard let hex else { return nil }
        var wanted = hex.trimmingCharacters(in: .whitespaces).uppercased()
        if !wanted.hasPrefix("#") { wanted = "#" + wanted }
        return projectColorOptions.first { $0.hex == wanted }?.name
    }

    // MARK: Construction

    fileprivate struct Tone {
        let light: UInt32
        let dark: UInt32
        let lightAlpha: CGFloat
        let darkAlpha: CGFloat

        init(_ light: UInt32, _ dark: UInt32, lightAlpha: CGFloat = 1, darkAlpha: CGFloat = 1) {
            self.light = light
            self.dark = dark
            self.lightAlpha = lightAlpha
            self.darkAlpha = darkAlpha
        }
    }

    private static func color(_ normal: Tone, highContrast: Tone? = nil) -> Color {
        Color(uiColor: UIColor { traits in
            let tone = traits.accessibilityContrast == .high ? (highContrast ?? normal) : normal
            if traits.userInterfaceStyle == .dark {
                return UIColor(bbRGB: tone.dark, alpha: tone.darkAlpha)
            }
            return UIColor(bbRGB: tone.light, alpha: tone.lightAlpha)
        })
    }
}

/// One entry of the project colour palette.
struct BBProjectColor: Hashable, Sendable, Identifiable {
    /// `#RRGGBB`, uppercase.
    let hex: String
    /// Spoken name, for example "Sky".
    let name: String
    var id: String { hex }
    var color: Color { BBColor.project(hex) }
}

extension Color {
    /// A colour from `#RGB`, `#RRGGBB` or `#RRGGBBAA` (the `#` is optional).
    /// Invalid input yields neutral slate-400 rather than crashing, because
    /// project colours are free-form user data.
    init(hex: String) {
        self = Color(validatingHex: hex) ?? Color(uiColor: UIColor(bbRGB: 0x94A3B8, alpha: 1))
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
    static let row: CGFloat = 12
    /// Mobile task cards.
    static let card: CGFloat = 14
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

/// The brand type scale on the system font (docs deviation 3: SF Pro instead
/// of Inter), expressed as Dynamic Type text styles so every size scales.
///
/// Brand → iOS: display 28 → `.title`, title 20 → `.title3`, subtitle 15 →
/// `.subheadline`, body 14 → `.body` (iOS reading size), metadata 11–13 →
/// `.footnote` / `.caption`, micro 11 → `.caption2`, label 10 uppercase →
/// `.caption2` semibold with tracking (see `bbSectionLabel()`).
enum BBFont {
    /// Empty-state headlines.
    static let display = Font.title.weight(.semibold)
    /// Pane and dialog titles.
    static let title = Font.title3.weight(.semibold)
    static let subtitle = Font.subheadline.weight(.medium)
    static let body = Font.body
    static let bodyMedium = Font.body.weight(.medium)
    /// Task titles in rows.
    static let rowTitle = Font.body
    /// Secondary lines under a title.
    static let secondary = Font.subheadline
    /// Row metadata (project, list, waiting note).
    static let meta = Font.footnote
    /// Chips and pills.
    static let caption = Font.caption
    static let micro = Font.caption2
    /// Uppercase section labels; pair with `.textCase(.uppercase)` and tracking,
    /// or use `bbSectionLabel()`.
    static let label = Font.caption2.weight(.semibold)
}

// MARK: - View helpers

extension View {
    /// The only uppercase text in the product: 10-pt-style section labels
    /// ("PROJECTS", "TAGS") with wide tracking in tertiary slate.
    func bbSectionLabel() -> some View {
        font(BBFont.label)
            .textCase(.uppercase)
            .tracking(0.6)
            .foregroundStyle(BBColor.textTertiary)
    }

    /// A flat brand card: raised surface, slate hairline, soft shadow. Content
    /// only; chrome uses Liquid Glass instead.
    func bbCard(cornerRadius: CGFloat = BBRadius.row) -> some View {
        background {
            RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                .fill(BBColor.surfaceRaised)
                .shadow(color: Color.black.opacity(0.04), radius: 1, x: 0, y: 1)
        }
        .overlay {
            RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                .strokeBorder(BBColor.hairline, lineWidth: 1)
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
