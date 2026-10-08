import XCTest
@testable import BrainBuddyMacCore

/// 020-FR-041: until Mac↔backend sync exists, the Mac sidebar shows a non-interactive
/// "Weekly review · coming later" row right after Lists, in the iOS `DeferredRow`
/// pattern, and no local-only review ships.
///
/// No CI lane runs `macos/`, so these tests only count as evidence together with the
/// recorded macOS-host run in `specs/020-weekly-review/evidence/macos-host-run.md`.
final class WeeklyReviewRowTests: XCTestCase {
    private let entries = SidebarEntries.standard

    private func section(_ id: String) throws -> SidebarSection {
        try XCTUnwrap(entries.sections.first { $0.id == id }, "missing sidebar section \(id)")
    }

    private func weeklyReviewRow() throws -> SidebarRow {
        try XCTUnwrap(
            entries.sections.flatMap(\.rows).first { $0.id == SidebarEntries.weeklyReviewRowID },
            "the sidebar has no Weekly review row"
        )
    }

    func test_020_FR_041_weeklyReviewRowSitsRightAfterLists() throws {
        XCTAssertEqual(entries.sections.map(\.id), ["lists", "weekly-review", "dates", "history"])
        let review = try section("weekly-review")
        XCTAssertNil(review.header, "the review row sits apart from the lists, without a header of its own")
        XCTAssertEqual(review.rows.map(\.id), [SidebarEntries.weeklyReviewRowID])
    }

    func test_020_FR_041_weeklyReviewRowShowsTheComingLaterCopy() throws {
        let row = try weeklyReviewRow()
        XCTAssertEqual(row.title, "Weekly review")
        XCTAssertEqual(row.deferredNote, "coming later")
        XCTAssertEqual("\(row.title) · \(row.deferredNote ?? "")", "Weekly review · coming later")
        XCTAssertEqual(row.symbol, "arrow.counterclockwise", "same symbol as the iOS deferred row")
    }

    func test_020_FR_041_weeklyReviewRowHasNoActionAndIsNotSelectable() throws {
        let row = try weeklyReviewRow()
        XCTAssertEqual(row.kind, .deferred(note: "coming later"))
        XCTAssertNil(row.destination, "a deferred row navigates nowhere")
        XCTAssertFalse(row.isInteractive, "a deferred row is neither a button nor a selectable row")
    }

    func test_020_FR_041_weeklyReviewRowReadsAsOneStaticElement() throws {
        let row = try weeklyReviewRow()
        // VoiceOver reads the title and the note together, so the deferral is said in
        // words; ContentView renders it as static text with no button trait.
        XCTAssertEqual(row.accessibilityLabel, "Weekly review, coming later")
    }

    func test_020_FR_041_weeklyReviewIsNotAFifthList() throws {
        let lists = try section("lists")
        XCTAssertEqual(lists.header, "Lists")
        let listDestinations: [WorkspaceDestination?] = TaskList.allCases.map { .list($0) }
        XCTAssertEqual(lists.rows.map(\.destination), listDestinations)
        XCTAssertFalse(lists.rows.contains { $0.id == SidebarEntries.weeklyReviewRowID })
    }

    func test_020_FR_041_noLocalOnlyReviewEntryShips() {
        let rows = entries.sections.flatMap(\.rows)
        let deferred = rows.filter { !$0.isInteractive }
        XCTAssertEqual(deferred.map(\.id), [SidebarEntries.weeklyReviewRowID], "only the review row is deferred")
        let reviewRows = rows.filter { $0.title.lowercased().contains("review") }
        XCTAssertEqual(reviewRows.map(\.id), [SidebarEntries.weeklyReviewRowID])
        XCTAssertTrue(reviewRows.allSatisfy { $0.destination == nil }, "no sidebar entry opens a local review")
    }

    /// Guardrail for the extraction: Lists, Dates and History keep the titles, symbols
    /// and destinations that `ContentView.sidebar(account:)` hard-coded before 020.
    func test_020_FR_041_extractionKeepsListsDatesAndHistoryUnchanged() throws {
        struct Expected: Equatable {
            let title: String
            let symbol: String
            let destination: WorkspaceDestination?
        }
        func shape(_ id: String) throws -> [Expected] {
            try section(id).rows.map { Expected(title: $0.title, symbol: $0.symbol, destination: $0.destination) }
        }

        XCTAssertEqual(try shape("lists"), [
            Expected(title: "Inbox", symbol: "tray", destination: .list(.inbox)),
            Expected(title: "Next actions", symbol: "checklist", destination: .list(.next)),
            Expected(title: "Waiting for", symbol: "clock", destination: .list(.waiting)),
            Expected(title: "Someday", symbol: "archivebox", destination: .list(.someday)),
        ])
        XCTAssertEqual(try section("dates").header, "Dates")
        XCTAssertEqual(try shape("dates"), [
            Expected(title: "Overdue", symbol: "exclamationmark.triangle", destination: .date(.overdue)),
            Expected(title: "Today", symbol: "calendar", destination: .date(.today)),
            Expected(title: "Upcoming", symbol: "arrow.up.right", destination: .date(.upcoming)),
        ])
        XCTAssertEqual(try section("history").header, "History")
        XCTAssertEqual(try shape("history"), [
            Expected(title: "Completed", symbol: "checkmark.circle", destination: .history(.completed)),
            Expected(title: "Cancelled", symbol: "xmark.circle", destination: .history(.cancelled)),
        ])
    }

    func test_020_FR_041_sidebarIdsAreUniqueForRendering() {
        let sectionIDs = entries.sections.map(\.id)
        XCTAssertEqual(Set(sectionIDs).count, sectionIDs.count)
        let rowIDs = entries.sections.flatMap(\.rows).map(\.id)
        XCTAssertEqual(Set(rowIDs).count, rowIDs.count)
    }
}
