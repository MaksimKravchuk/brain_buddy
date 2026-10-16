#if canImport(SwiftUI) && os(macOS)
    import BrainBuddyDesign
    import BrainBuddyDesignTestSupport
    import SwiftUI
    import Testing

    @testable import BrainBuddyMac

    /// The Mac task inspector against its approved renders, light and dark: the boards' Next
    /// action, Inbox "What is it?", Waiting for, Someday, Done, Not now popover and empty inspector,
    /// composed from the inspector components with the boards' own text.
    @Suite("Carry On Mac inspector snapshots")
    @MainActor
    struct CarryOnInspectorSnapshotTests {
        enum Appearance: String, CaseIterable, Sendable {
            case light, dark

            var scheme: ColorScheme { self == .dark ? .dark : .light }
        }

        private let garage = CarryOnProjectColor.ochre
        private let allotment = CarryOnProjectColor.moss

        /// The card sits on the window's ground, as on the boards.
        private func onGround<Content: View>(_ content: Content) -> some View {
            content.background(CarryOnColorStyle.coBgGround)
        }

        @Test("The Next action inspector renders as approved", arguments: Appearance.allCases)
        func next(appearance: Appearance) {
            let view = onGround(
                MacInspectorPanel(
                    height: 620,
                    content: {
                        MacInspectorEyebrow(projectName: "Garage", projectColor: garage, listName: "Next actions")
                        MacInspectorTitle(text: "Call Sam about the van")
                        MacInspectorChips(
                            projectName: "Garage", projectColor: garage, dueText: "Due Friday", tags: ["calls"])
                        MacInspectorSectionLabel("Why")
                        MacInspectorBodyText(text: "He needs the van back before the weekend. Ask when he can pick it up.")
                        MacInspectorSectionLabel("Steps inside")
                        VStack(alignment: .leading, spacing: 8) {
                            MacInspectorStepLine(title: "Find his new number", done: true)
                            MacInspectorStepLine(title: "Agree a day", done: false)
                        }
                        MacInspectorSectionLabel("Comments")
                        MacInspectorBodyText(text: "None yet", quiet: true)
                    },
                    actionBar: {
                        MacInspectorActionBar(
                            actions: [.primary("Done") {}, .secondary("Not now") {}],
                            trailingNote: "Saved as you type")
                    }))
            assertMacSnapshot(view, named: "mac-inspector-next-\(appearance.rawValue)", scheme: appearance.scheme, width: 340)
        }

        @Test("The Inbox inspector renders as approved", arguments: Appearance.allCases)
        func inbox(appearance: Appearance) {
            let view = onGround(
                MacInspectorPanel(
                    width: 380, height: 620,
                    content: {
                        MacInspectorEyebrow.inbox(position: 1, of: 4)
                        MacInspectorItemText(text: "the garage is a mess and Sam needs the van back")
                        MacInspectorTitle(text: "What is it?", serif: true, size: 24)
                            .padding(.top, 14)
                            .padding(.bottom, 12)
                        MacInspectorChoiceRow(
                            title: "A step I can take", detail: "Write the first step, it goes to Next actions",
                            glyph: .board(.nextActions)) {}
                        MacInspectorChoiceRow(
                            title: "Bigger than one step", detail: "Make it a project with a first step",
                            glyph: .folder) {}
                        MacInspectorChoiceRow(
                            title: "Waiting on someone", detail: "Say who, it goes to Waiting for",
                            glyph: .board(.waitingFor)) {}
                        MacInspectorChoiceRow(
                            title: "Someday", detail: "Not now, keep it for later",
                            glyph: .board(.somedayMaybe)) {}
                    },
                    actionBar: {
                        MacInspectorActionBar(
                            actions: [.secondary("Done already") {}, .quiet("Not needed") {}],
                            trailingNote: "Skip")
                    }))
            assertMacSnapshot(view, named: "mac-inspector-inbox-\(appearance.rawValue)", scheme: appearance.scheme, width: 380)
        }

        @Test("The Waiting for inspector renders as approved", arguments: Appearance.allCases)
        func waiting(appearance: Appearance) {
            let view = onGround(
                MacInspectorPanel(
                    height: 520,
                    content: {
                        MacInspectorEyebrow(projectName: "Garage", projectColor: garage, listName: "Waiting for")
                        MacInspectorTitle(text: "Quote for the van")
                        MacInspectorPerson(name: "Sam", since: "Asked 3 days ago")
                        MacInspectorSectionLabel("Note")
                        MacInspectorBodyText(text: "He said he would send it after the inspection.")
                        MacInspectorChips(projectName: "Garage", projectColor: garage, dueText: "Due Friday")
                    },
                    actionBar: {
                        MacInspectorActionBar(actions: [.primary("Got it") {}, .quiet("Follow up") {}])
                    }))
            assertMacSnapshot(view, named: "mac-inspector-waiting-\(appearance.rawValue)", scheme: appearance.scheme, width: 340)
        }

        @Test("The Someday inspector renders as approved", arguments: Appearance.allCases)
        func someday(appearance: Appearance) {
            let view = onGround(
                MacInspectorPanel(
                    height: 520,
                    content: {
                        MacInspectorEyebrow(projectName: "Allotment", projectColor: allotment, listName: "Someday")
                        MacInspectorTitle(text: "Build a cold frame", serif: true)
                        MacInspectorMetaText(text: "Here since March")
                        MacInspectorSectionLabel("Note")
                        MacInspectorBodyText(text: "Old windows from the neighbours could work.")
                        MacInspectorBodyText(
                            text: "Ready to start? Write the first step and it moves to Next actions.",
                            quiet: true, topPadding: 18)
                    },
                    actionBar: {
                        MacInspectorActionBar(actions: [.primary("Start it") {}, .quiet("Not needed") {}])
                    }))
            assertMacSnapshot(view, named: "mac-inspector-someday-\(appearance.rawValue)", scheme: appearance.scheme, width: 340)
        }

        @Test("The Done inspector renders as approved", arguments: Appearance.allCases)
        func done(appearance: Appearance) {
            let view = onGround(
                MacInspectorPanel(
                    height: 520,
                    content: {
                        MacInspectorEyebrow(projectName: "Garage", projectColor: garage, listName: "Done on Monday")
                        MacInspectorTitle(text: "Clear the shelves", struck: true)
                        MacInspectorSectionLabel("Note")
                        MacInspectorBodyText(text: "Two boxes to the tip, one to the charity shop.")
                        MacInspectorMetaText(text: "Finished steps are read-only.", topPadding: 16)
                    },
                    actionBar: {
                        MacInspectorActionBar(actions: [.secondary("Reopen…") {}])
                    }))
            assertMacSnapshot(view, named: "mac-inspector-done-\(appearance.rawValue)", scheme: appearance.scheme, width: 340)
        }

        @Test("The Not now popover renders as approved", arguments: Appearance.allCases)
        func notNow(appearance: Appearance) {
            let view = onGround(
                MacNotNowPopoverContent(onPickDay: {}, onWaiting: {}, onSomeday: {}, onChangeStep: {})
                    .padding(20))
            assertMacSnapshot(view, named: "mac-inspector-notnow-\(appearance.rawValue)", scheme: appearance.scheme, width: 340)
        }

        @Test("The empty inspector renders as approved", arguments: Appearance.allCases)
        func empty(appearance: Appearance) {
            let view = onGround(
                MacInspectorPanel(height: 520) {
                    MacInspectorEmpty(text: "Select something to sort it.\nOr press Sort them one by one.")
                })
            assertMacSnapshot(view, named: "mac-inspector-empty-\(appearance.rawValue)", scheme: appearance.scheme, width: 340)
        }
    }
#endif
