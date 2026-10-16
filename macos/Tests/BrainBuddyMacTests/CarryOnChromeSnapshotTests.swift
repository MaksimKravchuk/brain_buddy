#if canImport(SwiftUI) && os(macOS)
    import BrainBuddyDesign
    import SwiftUI
    import Testing

    @testable import BrainBuddyMac

    /// The Mac window chrome against its approved renders, light and dark. The sidebar is drawn on
    /// `coBgGround` as a stand-in for the system glass.
    @Suite("Carry On Mac chrome snapshots")
    @MainActor
    struct CarryOnChromeSnapshotTests {
        enum Appearance: String, CaseIterable, Sendable {
            case light, dark

            var scheme: ColorScheme { self == .dark ? .dark : .light }
        }

        private struct Fixture {
            let title: String
            let icon: MacBoardIcon
            var count: String?
            var selected = false
        }

        private func rows(_ fixtures: [Fixture]) -> some View {
            ForEach(fixtures, id: \.title) { fixture in
                MacSidebarRowLabel(
                    title: fixture.title, leading: .icon(fixture.icon), trailing: fixture.count,
                    selected: fixture.selected)
            }
        }

        private var sidebar: some View {
            VStack(alignment: .leading, spacing: 0) {
                MacSidebarBrand()
                MacSidebarSectionHeader(title: "Lists")
                rows([
                    Fixture(title: "Inbox", icon: .inbox, count: "4", selected: true),
                    Fixture(title: "Next actions", icon: .nextActions, count: "12"),
                    Fixture(title: "Waiting for", icon: .waitingFor, count: "3"),
                    Fixture(title: "Someday / maybe", icon: .somedayMaybe, count: "9"),
                ])
                MacSidebarSectionHeader(title: "Dates")
                rows([
                    Fixture(title: "Overdue", icon: .calendar, count: "1"),
                    Fixture(title: "Today", icon: .calendar, count: "2"),
                    Fixture(title: "Upcoming", icon: .calendar, count: "5"),
                ])
                MacSidebarSectionHeader(title: "Projects")
                MacSidebarRowLabel(title: "Garage", leading: .dot(projectTint("#B8862B")), selected: false)
                MacSidebarRowLabel(title: "Wedding", leading: .dot(projectTint("#7A4E6B")), selected: false)
                MacSidebarRowLabel(title: "Taxes", leading: .dot(projectTint("#3E6A7A")), selected: false)
                MacSidebarSectionHeader(title: "History")
                rows([
                    Fixture(title: "Done", icon: .history),
                    Fixture(title: "Cancelled", icon: .history),
                ])
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 12)
            .frame(maxWidth: .infinity, alignment: .topLeading)
            .background(.coBgGround)
        }

        @Test("The sidebar renders as approved", arguments: Appearance.allCases)
        func macSidebar(appearance: Appearance) {
            assertSnapshot(
                sidebar, named: "mac-sidebar-\(appearance.rawValue)", scheme: appearance.scheme, width: 240)
        }

        @Test("The list header renders as approved", arguments: Appearance.allCases)
        func macListHeader(appearance: Appearance) {
            assertSnapshot(
                MacListHeaderTitle(title: "Inbox", caption: "4 open tasks")
                    .padding(28)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(.coBgGround),
                named: "mac-list-header-\(appearance.rawValue)", scheme: appearance.scheme, width: 700)
        }
    }
#endif
