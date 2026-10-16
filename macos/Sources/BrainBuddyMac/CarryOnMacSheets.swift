import BrainBuddyDesign
import SwiftUI

// The Mac sheets and system surfaces in the Carry On design system (slice 5): sign in, the sync
// line, popover and conflict, the unreadable workspace, Quick Open and the three reviews. They have
// no board of their own, so they take the tokens and the parts of the other Mac boards: the serif
// title, 14 body, 12 meta, `field-bg` fields, `bg-ground` plates and the pills. Presentation only.

/// Instrument faces at the sheets' sizes.
enum MacSheetFont {
    /// A sheet's title: Instrument Serif 22 (the type scale's title).
    static var title: Font { .carryOn(CarryOnTypeScale.title) }
    /// The task or project a review is about: 20 semibold, as the inspector's title.
    static var cardTitle: Font { MacRowFont.action(size: 20, weight: 600, relativeTo: .title3) }
    /// Body text: 14.
    static var body: Font { MacRowFont.title }
    /// A heading inside a sheet or popover: 14 semibold.
    static var heading: Font { MacRowFont.titleStrong }
    /// Popover text: 13.
    static var note: Font { MacRowFont.action(size: 13, weight: 400, relativeTo: .callout) }
    /// A popover line's lead ("Rename “Order soil”"): 13 semibold.
    static var noteStrong: Font { MacRowFont.action(size: 13, weight: 600, relativeTo: .callout) }
    /// Hints, footers and the sync line: 12.
    static var meta: Font { MacRowFont.meta }
    /// Section labels and small text actions: 12 semibold (`meta-strong`).
    static var metaStrong: Font { .carryOn(CarryOnTypeScale.metaStrong) }
    /// Reference ids, to quote: 11 monospaced.
    static var reference: Font { .system(size: 11, design: .monospaced) }
}

/// What a line says about its state. Words always carry it; the ink only repeats it.
enum MacSheetTone: Sendable {
    case primary, secondary, warning, danger

    var style: CarryOnColorStyle {
        switch self {
        case .primary: CarryOnColorStyle.coTextPrimary
        case .secondary: CarryOnColorStyle.coTextSecondary
        case .warning: CarryOnColorStyle.coStatusWarning
        case .danger: CarryOnColorStyle.coStatusDanger
        }
    }
}

extension View {
    /// A sheet's card: `surface-card`, as the inspector.
    func macSheetSurface() -> some View {
        background(CarryOnColorStyle.coSurfaceCard)
    }

    /// A sheet's text field: the capture field (14 on `field-bg`, radius 12) across the width.
    func macSheetField() -> some View {
        frame(maxWidth: .infinity, alignment: .leading).macCaptureField()
    }
}

/// A sheet's title in Instrument Serif 22 and, under it, a 14 secondary line.
struct MacSheetHeader: View {
    let title: String
    var subtitle: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .carryOnText(CarryOnTypeScale.title)
                .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityAddTraits(.isHeader)
            if let subtitle {
                Text(subtitle)
                    .font(MacSheetFont.body)
                    .foregroundStyle(CarryOnColorStyle.coTextSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// A quiet plate: `bg-ground` at radius 10, as the inspector's choice rows. Notes, boxes and the
/// review cards sit on it.
struct MacSheetPlate<Content: View>: View {
    var padding: CGFloat
    var spacing: CGFloat
    let content: Content

    init(padding: CGFloat = 12, spacing: CGFloat = 8, @ViewBuilder content: () -> Content) {
        self.padding = padding
        self.spacing = spacing
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: spacing) { content }
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(CarryOnColorStyle.coBgGround, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
    }
}

/// A line led by an optional glyph, in a tone: the attention lines of sign in and sync.
struct MacSheetStatus: View {
    let text: String
    var systemImage: String?
    var tone: MacSheetTone = .warning
    var font: Font = MacSheetFont.heading

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            if let systemImage {
                Image(systemName: systemImage).accessibilityHidden(true)
            }
            Text(text).fixedSize(horizontal: false, vertical: true)
        }
        .font(font)
        .foregroundStyle(tone.style)
    }
}

/// "Reference ID …": 11 monospaced, secondary, selectable so it can be quoted.
struct MacSheetReference: View {
    let reference: String

    var body: some View {
        Text("Reference ID \(reference)")
            .font(MacSheetFont.reference)
            .foregroundStyle(CarryOnColorStyle.coTextSecondary)
            .textSelection(.enabled)
    }
}

/// A 1 pt rule in `control-quiet`.
struct MacSheetDivider: View {
    var body: some View {
        Rectangle()
            .fill(CarryOnColorStyle.coControlQuiet)
            .frame(height: 1)
            .frame(maxWidth: .infinity)
            .accessibilityHidden(true)
    }
}

/// A text action: 12 semibold in text-primary, no fill ("Copy", "Show in Finder", "Retry").
struct MacTextButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        MacTextButtonBody(label: configuration.label, isPressed: configuration.isPressed)
    }
}

private struct MacTextButtonBody<Label: View>: View {
    let label: Label
    let isPressed: Bool
    @Environment(\.isEnabled) private var isEnabled

    var body: some View {
        label
            .font(MacSheetFont.metaStrong)
            .foregroundStyle(CarryOnColorStyle.coTextPrimary)
            .opacity(isEnabled ? (isPressed ? 0.6 : 1) : 0.4)
            .contentShape(Rectangle())
    }
}

extension ButtonStyle where Self == MacTextButtonStyle {
    static var macText: MacTextButtonStyle { MacTextButtonStyle() }
}

/// A state with nothing to show (loading failed, all reviewed): the list's empty state and, when
/// there is one, its action as a secondary pill under it.
struct MacSheetEmptyState<Actions: View>: View {
    let title: String
    let systemImage: String
    var description: String?
    let actions: Actions

    init(title: String, systemImage: String, description: String? = nil, @ViewBuilder actions: () -> Actions) {
        self.title = title
        self.systemImage = systemImage
        self.description = description
        self.actions = actions()
    }

    var body: some View {
        VStack(spacing: 10) {
            MacEmptyState(title: title, systemImage: systemImage, description: description)
            actions.buttonStyle(.carryOnSecondary)
        }
        .frame(maxWidth: .infinity)
    }
}

extension MacSheetEmptyState where Actions == EmptyView {
    init(title: String, systemImage: String, description: String? = nil) {
        self.init(title: title, systemImage: systemImage, description: description) { EmptyView() }
    }
}

// MARK: - Reviews

/// A review sheet's head: the serif title, its 12 secondary progress line and "Close review" (Esc).
struct MacReviewHeader: View {
    let title: String
    let caption: String
    let onClose: () -> Void

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            MacSheetHeader(title: title)
                .fixedSize(horizontal: true, vertical: false)
            Text(caption)
                .font(MacSheetFont.meta)
                .foregroundStyle(CarryOnColorStyle.coTextSecondary)
                .lineLimit(1)
            Spacer(minLength: 8)
            Button("Close review", action: onClose)
                .buttonStyle(.carryOnQuiet)
                .keyboardShortcut(.cancelAction)
        }
    }
}

/// The item a review is about: its title in 20 semibold, then its lines, on a `bg-ground` plate.
struct MacReviewCard<Lines: View>: View {
    let title: String
    let lines: Lines

    init(title: String, @ViewBuilder lines: () -> Lines) {
        self.title = title
        self.lines = lines()
    }

    var body: some View {
        MacSheetPlate(padding: 18, spacing: 10) {
            Text(title)
                .font(MacSheetFont.cardTitle)
                .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
            lines
        }
    }
}

/// A Waiting for item under review: its title, its notes (up to four lines), who it waits for
/// with the clock glyph, since when and its project.
struct MacWaitingReviewCard: View {
    let title: String
    let details: String?
    let waitingFor: String?
    let since: String?
    let project: String?

    var body: some View {
        MacReviewCard(title: title) {
            if let details, !details.isEmpty {
                MacReviewLine(text: details).lineLimit(4)
            }
            MacSheetStatus(
                text: "Waiting for \(waitingFor ?? "an unspecified response")", systemImage: "hourglass", tone: .primary)
            if let since {
                MacReviewLine(text: since, small: true)
            }
            if let project {
                MacReviewLine(text: project, small: true)
            }
        }
    }
}

/// A Someday item under review: its title, its notes and its project.
struct MacSomedayReviewCard: View {
    let title: String
    let details: String?
    let project: String?

    var body: some View {
        MacReviewCard(title: title) {
            if let details, !details.isEmpty {
                MacReviewLine(text: details)
            }
            if let project {
                MacReviewLine(text: project, small: true)
            }
        }
    }
}

/// A review card's line: 14 in a tone, or 12 for `small`.
struct MacReviewLine: View {
    let text: String
    var tone: MacSheetTone = .secondary
    var small = false

    var body: some View {
        Text(text)
            .font(small ? MacSheetFont.meta : MacSheetFont.body)
            .foregroundStyle(tone.style)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// "What should happen next?" and the like: the review's question, 14 semibold.
struct MacReviewQuestion: View {
    let text: String

    var body: some View {
        Text(text)
            .font(MacSheetFont.heading)
            .foregroundStyle(CarryOnColorStyle.coTextPrimary)
            .accessibilityAddTraits(.isHeader)
    }
}

/// A 12 semibold secondary label over a review section ("WHY REVIEW NOW").
struct MacReviewSectionLabel: View {
    let text: String

    var body: some View {
        Text(text)
            .font(MacSheetFont.metaStrong)
            .foregroundStyle(CarryOnColorStyle.coTextSecondary)
            .accessibilityAddTraits(.isHeader)
    }
}
