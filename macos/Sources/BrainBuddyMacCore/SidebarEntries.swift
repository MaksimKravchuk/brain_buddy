import BrainBuddyCore
import Foundation

// The sidebar's fixed entries as plain values, so they can be unit-tested without
// SwiftUI or AppKit (`WeeklyReviewRowTests`). `ContentView.sidebar` renders
// them; Projects and Tags follow them and come from the workspace. Keep this file free of
// UI frameworks.

/// The four open GTD lists are the kit's `OpenList`; this name stays for the Mac's views.
package typealias TaskList = OpenList

extension OpenList {
    /// The sidebar keeps its short name for Someday (020 PR-06's row contract); elsewhere the
    /// kit's list names apply ("Someday / maybe").
    package var sidebarTitle: String { self == .someday ? "Someday" : title }

    package var symbol: String {
        switch self {
        case .inbox: "tray"
        case .next: "checklist"
        case .waiting: "clock"
        case .someday: "archivebox"
        }
    }
}

package enum DateDestination: String, Hashable, Sendable {
    case overdue, today, upcoming

    package var title: String { rawValue.capitalized }
    package var symbol: String {
        switch self {
        case .overdue: "exclamationmark.triangle"
        case .today: "calendar"
        case .upcoming: "arrow.up.right"
        }
    }

    package var dateView: DateView {
        switch self {
        case .overdue: .overdue
        case .today: .today
        case .upcoming: .upcoming
        }
    }
}

package enum WorkspaceDestination: Hashable, Sendable {
    case list(TaskList)
    case date(DateDestination)
    case project(ProjectID)
    case tag(TagID)
    case history(HistoryState)

    package var isHistory: Bool {
        if case .history = self { return true }
        return false
    }

    /// The kit's query for this screen.
    package var query: Destination {
        switch self {
        case .list(let list): .list(list)
        case .date(let date): .dateView(date.dateView)
        case .project(let id): .project(id)
        case .tag(let id): .tag(id)
        case .history(let state): .history(state.kind)
        }
    }
}

package enum HistoryState: String, Hashable, Sendable {
    case completed, cancelled

    package var title: String { rawValue.capitalized }
    package var symbol: String { self == .completed ? "checkmark.circle" : "xmark.circle" }
    package var kind: HistoryKind { self == .completed ? .completed : .cancelled }
}

/// One fixed sidebar row.
package struct SidebarRow: Identifiable, Hashable {
    package enum Kind: Hashable {
        /// Choosing the row opens this destination.
        case destination(WorkspaceDestination)
        /// A visibly deferred feature: shown, never interactive, and says so in words.
        case deferred(note: String)
    }

    package let id: String
    package let title: String
    package let symbol: String
    package let kind: Kind

    package var destination: WorkspaceDestination? {
        if case .destination(let destination) = kind { return destination }
        return nil
    }

    package var deferredNote: String? {
        if case .deferred(let note) = kind { return note }
        return nil
    }

    /// False for a deferred row: it is rendered as static text, not as a button, and
    /// cannot be selected.
    package var isInteractive: Bool { destination != nil }

    /// What VoiceOver reads for the whole row; a deferred row includes its note.
    package var accessibilityLabel: String {
        deferredNote.map { "\(title), \($0)" } ?? title
    }
}

/// A group of fixed sidebar rows. A `nil` header renders a section without a title.
package struct SidebarSection: Identifiable, Hashable {
    package let id: String
    package let header: String?
    package let rows: [SidebarRow]
}

/// The fixed part of the Mac sidebar, in display order.
package struct SidebarEntries: Hashable {
    package let sections: [SidebarSection]

    package static let weeklyReviewRowID = "weekly-review"

    package static let standard = SidebarEntries(sections: [
        SidebarSection(
            id: "lists",
            header: "Lists",
            rows: TaskList.allCases.map { list in
                SidebarRow(
                    id: "list.\(list.rawValue)", title: list.sidebarTitle, symbol: list.symbol, kind: .destination(.list(list))
                )
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
