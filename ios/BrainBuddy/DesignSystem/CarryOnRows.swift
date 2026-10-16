import BrainBuddyDesign
import SwiftUI

// The Carry On list chrome (boards 07 to 09): every row is its own card on the
// limestone ground, 16 pt from the screen edge and 8 pt from the next card, no
// dividers. A `List` keeps its swipe actions, so the card is the row's
// background, drawn inside the cell, and the row's insets put the content where
// the board puts it. Every number below is a `BrainBuddyDesign` token.

enum BBCardRow {
    /// Space between the screen edge and a card (spacing md).
    static let sideMargin = CGFloat(CarryOnSpace.md)
    /// Space between two cards (spacing xs).
    static let gap = CGFloat(CarryOnSpace.xs)
    /// The card's corner radius (row radius).
    static let radius = CGFloat(CarryOnLayout.Row.radius)

    /// Where a card's content sits inside its list cell: the card's own
    /// padding, plus half the gap above and below and the side margin.
    static let contentInsets = EdgeInsets(
        top: gap / 2 + CGFloat(CarryOnLayout.Row.paddingY),
        leading: sideMargin + CGFloat(CarryOnLayout.Row.paddingX),
        bottom: gap / 2 + CGFloat(CarryOnLayout.Row.paddingY),
        trailing: sideMargin + CGFloat(CarryOnLayout.Row.paddingX)
    )

    /// For a row that draws its own surface (the next-step card) or none (a
    /// button): the side margin and half the gap.
    static let bareInsets = EdgeInsets(top: gap / 2, leading: sideMargin, bottom: gap / 2, trailing: sideMargin)

    /// Section headers sit on the card edge.
    static let headerInsets = EdgeInsets(
        top: CGFloat(CarryOnSpace.sm), leading: sideMargin, bottom: CGFloat(CarryOnSpace.xxs), trailing: sideMargin
    )
}

/// The card behind a list row: row-bg, inset from the cell by the side margin
/// and half the gap, so neighbouring cards are one gap apart.
struct BBCardRowBackground: View {
    var body: some View {
        RoundedRectangle(cornerRadius: BBCardRow.radius, style: .continuous)
            .fill(.coRowBg)
            .padding(.horizontal, BBCardRow.sideMargin)
            .padding(.vertical, BBCardRow.gap / 2)
    }
}

extension View {
    /// A list row as a Carry On card: row-bg surface, radius 12, padding 14 × 16,
    /// no divider. Apply it to the row, outside any `NavigationLink`.
    func bbCardRow() -> some View {
        listRowInsets(BBCardRow.contentInsets)
            .listRowSeparator(.hidden)
            .listRowBackground(BBCardRowBackground())
    }

    /// A list row with no surface of its own: a button or the next-step card,
    /// kept on the same side margin and gap as the cards.
    func bbBareRow() -> some View {
        listRowInsets(BBCardRow.bareInsets)
            .listRowSeparator(.hidden)
            .listRowBackground(Color.clear)
    }

    /// The row surface for the rows of a grouped list (the Lists hub, Projects,
    /// recent searches): row-bg instead of the system grouped fill. Apply it to
    /// a `Section`.
    func bbGroupedRows() -> some View {
        listRowBackground(Rectangle().fill(.coRowBg))
    }
}
