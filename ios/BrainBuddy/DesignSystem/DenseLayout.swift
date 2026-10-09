import SwiftUI

// The compact layout every screen shares: the title sits on the toolbar's
// line, rows are 44 pt (the hit target, grown by Dynamic Type), section
// headers are the design system's small uppercase label, and grouped rows
// keep their icons in one fixed column so text lines up from row to row.

extension BBMetrics {
    /// Minimum height of a list row: the 44 pt hit target, nothing more.
    static let rowMinHeight: CGFloat = 44
    /// Width of the leading icon column in grouped rows before Dynamic Type
    /// scaling. Symbols, project dots and empty slots all take this width.
    static let iconColumn: CGFloat = 24
}

extension View {
    /// A screen's title, drawn large on the same line as the toolbar buttons
    /// (`.inlineLarge`) instead of in its own band above the content.
    func bbScreenTitle(_ title: String) -> some View {
        navigationTitle(title)
            .toolbarTitleDisplayMode(.inlineLarge)
    }

    /// One line of context under the title ("14 open tasks · Syncing…"),
    /// replacing caption and status rows inside the content.
    func bbScreenSubtitle(_ subtitle: String) -> some View {
        navigationSubtitle(subtitle)
    }

    /// Dense lists: rows no taller than their content or the 44 pt target,
    /// and compact spacing between grouped sections.
    func bbDenseList() -> some View {
        environment(\.defaultMinListRowHeight, BBMetrics.rowMinHeight)
            .listSectionSpacing(.compact)
    }
}

/// A list section header: the 10-pt-style uppercase label, with an optional
/// project dot or symbol before it and a count on the trailing edge.
///
/// VoiceOver reads it as one header: "Website relaunch, 4".
struct BBSectionHeader: View {
    let title: String
    var count: Int?
    var dotColor: Color?
    var systemImage: String?
    /// Colour for the symbol and title, for example `BBColor.dueText` on
    /// Overdue. Nil keeps the tertiary label colour.
    var tint: Color?

    @ScaledMetric(relativeTo: .caption2) private var dotSize: CGFloat = 7

    init(_ title: String, count: Int? = nil, dotColor: Color? = nil, systemImage: String? = nil, tint: Color? = nil) {
        self.title = title
        self.count = count
        self.dotColor = dotColor
        self.systemImage = systemImage
        self.tint = tint
    }

    var body: some View {
        HStack(spacing: 6) {
            if let dotColor {
                Circle()
                    .fill(dotColor)
                    .frame(width: dotSize, height: dotSize)
                    .accessibilityHidden(true)
            }
            if let systemImage {
                Image(systemName: systemImage)
                    .accessibilityHidden(true)
            }
            Text(title)
            Spacer(minLength: BBSpacing.s2)
            if let count {
                Text("\(count)")
                    .monospacedDigit()
                    .foregroundStyle(BBColor.textPlaceholder)
            }
        }
        .font(BBFont.label)
        .textCase(.uppercase)
        .tracking(0.6)
        .foregroundStyle(tint ?? BBColor.textTertiary)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isHeader)
    }
}

/// Rows in grouped screens: the icon is centred in a fixed column (24 pt,
/// scaled with Dynamic Type) in the brand text colour, so titles line up
/// whether a row shows a wide symbol, a narrow one or a project dot.
struct BBRowLabelStyle: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        BBRowLabel(icon: configuration.icon, title: configuration.title)
    }
}

extension LabelStyle where Self == BBRowLabelStyle {
    /// `BBRowLabelStyle`: icon in a fixed column, title after it.
    static var bbRow: BBRowLabelStyle { BBRowLabelStyle() }
}

private struct BBRowLabel: View {
    let icon: LabelStyleConfiguration.Icon
    let title: LabelStyleConfiguration.Title

    @ScaledMetric(relativeTo: .body) private var column: CGFloat = BBMetrics.iconColumn

    var body: some View {
        HStack(spacing: BBSpacing.s3) {
            icon
                .foregroundStyle(BBColor.brandText)
                .frame(width: column)
            title
        }
    }
}

/// A project's colour dot sized for `BBRowLabelStyle`'s icon column, so
/// project names line up with the symbol rows around them.
struct BBProjectDot: View {
    let color: Color

    @ScaledMetric(relativeTo: .body) private var size: CGFloat = 10

    var body: some View {
        Circle()
            .fill(color)
            .frame(width: size, height: size)
            .accessibilityHidden(true)
    }
}

#Preview("Dense layout") {
    NavigationStack {
        List {
            Section {
                Label("Next actions", systemImage: "checklist")
                Label {
                    Text("Website relaunch")
                } icon: {
                    BBProjectDot(color: BBColor.project("#0EA5E9"))
                }
            } header: {
                BBSectionHeader("Website relaunch", count: 4, dotColor: BBColor.project("#0EA5E9"))
            }
        }
        .labelStyle(.bbRow)
        .bbDenseList()
        .bbScreenTitle("Lists")
        .bbScreenSubtitle("3 open tasks · Synced just now")
    }
}
