#if canImport(SwiftUI) && os(macOS)
    import BrainBuddyDesign
    import SwiftUI
    import Testing

    @testable import BrainBuddyMac

    /// The Mac list column's rows against their approved renders, light and dark: the boards'
    /// Inbox, Next actions, Waiting for, Someday and Done lists, drawn with the app's own row views
    /// on `coBgGround` at the column's 760 pt.
    @Suite("Carry On Mac rows snapshots")
    @MainActor
    struct CarryOnRowsSnapshotTests {
        enum Appearance: String, CaseIterable, Sendable {
            case light, dark

            var scheme: ColorScheme { self == .dark ? .dark : .light }
        }

        private func list<Content: View>(@ViewBuilder _ content: () -> Content) -> some View {
            VStack(alignment: .leading, spacing: 0) { content() }
                .padding(26)
                .frame(maxWidth: .infinity, alignment: .topLeading)
                .background(CarryOnColorStyle.coBgGround)
        }

        @Test("The Inbox rows render as approved", arguments: Appearance.allCases)
        func inbox(appearance: Appearance) {
            let view = list {
                MacTaskRow(title: "the garage is a mess and Sam needs the van back", kind: .inbox)
                MacTaskRow(title: "tax letter??", kind: .inbox)
                MacTaskRow(title: "Ana wedding speech", kind: .inbox)
                MacTaskRow(title: "drill from Tom", kind: .inbox)
                Button("Clarify Inbox") {}
                    .buttonStyle(.macSecondaryPill)
                    .padding(.top, 14)
            }
            assertSnapshot(view, named: "mac-rows-inbox-\(appearance.rawValue)", scheme: appearance.scheme, width: 760)
        }

        @Test("The Next actions rows render as approved", arguments: Appearance.allCases)
        func next(appearance: Appearance) {
            let view = list {
                MacTaskRow(title: "Buy bin bags", kind: .open, meta: "Garage", selected: true)
                MacTaskRow(title: "Draft the toast for Ana", kind: .open, meta: "Wedding")
                MacTaskRow(title: "Renew parking permit", kind: .open, meta: "Due today", tone: .due)
                MacTaskRow(title: "Find last year's tax letter", kind: .open, meta: "Taxes")
                MacTaskRow(title: "Order seed potatoes", kind: .open, meta: "Allotment")
                MacTaskRow(title: "Return the drill to Tom", kind: .open, meta: "Overdue · 2 days", tone: .overdue)
                MacListSectionHeader(title: "Garage", top: 16)
                MacTaskRow(title: "Call Sam about the van", kind: .current, meta: "now")
                MacTaskRow(title: "List what is in the garage", kind: .done)
            }
            assertSnapshot(view, named: "mac-rows-next-\(appearance.rawValue)", scheme: appearance.scheme, width: 760)
        }

        @Test("The Waiting for rows render as approved", arguments: Appearance.allCases)
        func waiting(appearance: Appearance) {
            let view = list {
                MacTaskRow(title: "Quote for the van", kind: .waiting, meta: "Sam · 3 days", selected: true)
                MacTaskRow(title: "Tax letter copy", kind: .waiting, meta: "Accountant · 12 days")
                MacTaskRow(title: "Drill back", kind: .waiting, meta: "Tom · 1 day")
            }
            assertSnapshot(view, named: "mac-rows-waiting-\(appearance.rawValue)", scheme: appearance.scheme, width: 760)
        }

        @Test("The Someday rows render as approved", arguments: Appearance.allCases)
        func someday(appearance: Appearance) {
            let view = list {
                MacTaskRow(title: "Learn to sharpen chisels", kind: .someday)
                MacTaskRow(title: "Repaint the shed", kind: .someday, meta: "Allotment")
                MacTaskRow(title: "Build a cold frame", kind: .someday, meta: "Allotment", selected: true)
                MacTaskRow(title: "Read the bee-keeping book", kind: .someday)
            }
            assertSnapshot(view, named: "mac-rows-someday-\(appearance.rawValue)", scheme: appearance.scheme, width: 760)
        }

        @Test("The Done rows render as approved", arguments: Appearance.allCases)
        func done(appearance: Appearance) {
            let view = list {
                MacTaskRow(title: "Clear the shelves", kind: .done, meta: "Monday", selected: true)
                MacTaskRow(title: "Decide what to throw away", kind: .done, meta: "Last week")
                MacTaskRow(title: "List what is in the garage", kind: .done, meta: "Last week")
                MacTaskRow(title: "Book the MOT", kind: .done, meta: "September")
                MacTaskRow(title: "Ring the old landlord", kind: .cancelled)
            }
            assertSnapshot(view, named: "mac-rows-done-\(appearance.rawValue)", scheme: appearance.scheme, width: 760)
        }
    }
#endif
