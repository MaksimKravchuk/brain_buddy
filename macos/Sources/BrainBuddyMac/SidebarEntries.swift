import Foundation

// The sidebar's fixed entries as plain values, so they can be unit-tested without
// SwiftUI or AppKit (`WeeklyReviewRowTests`). `ContentView.sidebar(account:)` renders
// them; Projects and Tags follow them and come from the store. Keep this file free of
// UI frameworks.

enum DateDestination: String, Hashable {
    case overdue, today, upcoming

    var title: String { rawValue.capitalized }
    var symbol: String {
        switch self {
        case .overdue: "exclamationmark.triangle"
        case .today: "calendar"
        case .upcoming: "arrow.up.right"
        }
    }
}

enum WorkspaceDestination: Hashable {
    case list(TaskList)
    case date(DateDestination)
    case project(String)
    case tag(String)
    case history(HistoryState)

    var isHistory: Bool {
        if case .history = self { return true }
        return false
    }
}

enum HistoryState: String, Hashable {
    case completed, cancelled

    var title: String { rawValue.capitalized }
    var symbol: String { self == .completed ? "checkmark.circle" : "xmark.circle" }
}

/// One fixed sidebar row.
struct SidebarRow: Identifiable, Hashable {
    enum Kind: Hashable {
        /// Choosing the row opens this destination.
        case destination(WorkspaceDestination)
        /// A visibly deferred feature: shown, never interactive, and says so in words.
        case deferred(note: String)
    }

    let id: String
    let title: String
    let symbol: String
    let kind: Kind

    var destination: WorkspaceDestination? {
        if case .destination(let destination) = kind { return destination }
        return nil
    }

    var deferredNote: String? {
        if case .deferred(let note) = kind { return note }
        return nil
    }

    /// False for a deferred row: it is rendered as static text, not as a button, and
    /// cannot be selected.
    var isInteractive: Bool { destination != nil }

    /// What VoiceOver reads for the whole row; a deferred row includes its note.
    var accessibilityLabel: String {
        deferredNote.map { "\(title), \($0)" } ?? title
    }
}

/// A group of fixed sidebar rows. A `nil` header renders a section without a title.
struct SidebarSection: Identifiable, Hashable {
    let id: String
    let header: String?
    let rows: [SidebarRow]
}

/// The fixed part of the Mac sidebar, in display order.
struct SidebarEntries: Hashable {
    let sections: [SidebarSection]

    static let weeklyReviewRowID = "weekly-review"

    static let standard = SidebarEntries(sections: [
        SidebarSection(
            id: "lists",
            header: "Lists",
            rows: TaskList.allCases.map { list in
                SidebarRow(id: "list.\(list.rawValue)", title: list.title, symbol: list.symbol, kind: .destination(.list(list)))
            }
        ),
        // 020-FR-041: until Mac↔backend sync exists, weekly review is visibly deferred
        // (the iOS `DeferredRow` pattern). It sits apart from the four lists, because it
        // is not a fifth list (ADR-0006), and the Mac ships no local-only review.
        SidebarSection(
            id: weeklyReviewRowID,
            header: nil,
            rows: [
                SidebarRow(
                    id: weeklyReviewRowID, title: "Weekly review", symbol: "arrow.counterclockwise",
                    kind: .deferred(note: "coming later")
                ),
            ]
        ),
        SidebarSection(
            id: "dates",
            header: "Dates",
            rows: [DateDestination.overdue, .today, .upcoming].map { day in
                SidebarRow(id: "date.\(day.rawValue)", title: day.title, symbol: day.symbol, kind: .destination(.date(day)))
            }
        ),
        SidebarSection(
            id: "history",
            header: "History",
            rows: [HistoryState.completed, .cancelled].map { state in
                SidebarRow(
                    id: "history.\(state.rawValue)", title: state.title, symbol: state.symbol,
                    kind: .destination(.history(state))
                )
            }
        ),
    ])
}
