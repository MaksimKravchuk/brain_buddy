#if canImport(SwiftUI) && os(macOS)
    import BrainBuddyDesign
    import BrainBuddyDesignTestSupport
    import BrainBuddyMacCore
    import SwiftUI
    import Testing

    @testable import BrainBuddyMac

    /// The Mac sheets and system surfaces against their approved renders, light and dark: sign in
    /// (email and password, and with an error), the sync popover, the conflict detail, the
    /// unreadable workspace, Quick Open and the project, Waiting for and Someday reviews, composed from
    /// the sheet components with sample text. Text fields, pickers and scroll views are AppKit-backed
    /// and do not render here, so each field is its text in the field's own style and a bounded box
    /// is its text.
    @Suite("Carry On Mac sheets snapshots")
    @MainActor
    struct CarryOnSheetsSnapshotTests {
        enum Appearance: String, CaseIterable, Sendable {
            case light, dark

            var scheme: ColorScheme { self == .dark ? .dark : .light }
        }

        /// A sheet: its padding and width on `surface-card`.
        private func onSheet<Content: View>(_ content: Content, padding: CGFloat = 24, width: CGFloat) -> some View {
            content
                .padding(padding)
                .frame(width: width, alignment: .topLeading)
                .macSheetSurface()
        }

        private func signInSheet(message: MacSignInMessage?) -> some View {
            onSheet(
                MacSignInForm(
                    title: SignInCopy.title, subtitle: SignInCopy.subtitle,
                    showsLocalTasksNotice: message == nil, message: message, footer: nil, submitTitle: SignInCopy.signIn,
                    isSigningIn: false, canCancel: true, canSubmit: true, onCancel: {}, onSubmit: {}
                ) {
                    Text("max@example.com").macSheetField()
                    Text("••••••••••").macSheetField()
                },
                padding: 28, width: 460)
        }

        @Test("Sign in renders as approved", arguments: Appearance.allCases)
        func signIn(appearance: Appearance) {
            assertSnapshot(
                signInSheet(message: nil), named: "mac-sheets-signin-\(appearance.rawValue)", scheme: appearance.scheme,
                width: 460)
        }

        @Test("Sign in with an error renders as approved", arguments: Appearance.allCases)
        func signInError(appearance: Appearance) {
            let message = MacSignInMessage(
                title: SignInCopy.offline, detail: SignInCopy.offlineReassurance,
                referenceID: "7f3a9c2e")
            assertSnapshot(
                signInSheet(message: message), named: "mac-sheets-signin-error-\(appearance.rawValue)",
                scheme: appearance.scheme, width: 460)
        }

        @Test("The sync popover renders as approved", arguments: Appearance.allCases)
        func syncPopover(appearance: Appearance) {
            let view = VStack(alignment: .leading, spacing: 14) {
                SyncPopoverNotice(
                    title: "Sync isn't working", systemImage: "exclamationmark.triangle", tone: .warning,
                    detail: "Your changes are saved on this Mac and will sync when it works again.", detailTone: .primary
                ) {
                    HStack(spacing: 8) {
                        MacSheetReference(reference: "b41c07d2").lineLimit(1)
                        Button("Copy") {}.buttonStyle(.macText)
                    }
                }
                SyncPopoverLines(lastSynced: "Last synced · Today at 14:31", queue: "2 changes waiting to sync")
                VStack(alignment: .leading, spacing: 10) {
                    MacSheetStatus(text: "1 change couldn't sync", tone: .warning)
                    SyncPopoverIssueCard(
                        attempted: "Rename “Order soil”", why: "It was renamed on another device first.", laterActions: 2
                    ) {
                        Button("Copy") {}.buttonStyle(.macText)
                        Button("Review") {}.buttonStyle(.macSecondaryPill)
                    }
                }
                Button("Sync now") {}.buttonStyle(.macSecondaryPill)
                MacSheetDivider()
                SyncPopoverAccount(email: "max@example.com") {
                    Button("Sign out…") {}.buttonStyle(.macText)
                }
            }
            .padding(16)
            .frame(width: 360, alignment: .topLeading)
            .macSheetSurface()
            assertSnapshot(view, named: "mac-sheets-sync-popover-\(appearance.rawValue)", scheme: appearance.scheme, width: 360)
        }

        @Test("The conflict detail renders as approved", arguments: Appearance.allCases)
        func conflict(appearance: Appearance) {
            let view = VStack(alignment: .leading, spacing: 12) {
                Button("Back") {}.buttonStyle(.macText)
                Text("Choose a title")
                    .font(MacSheetFont.heading)
                    .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                MacSheetStatus(text: "Your choice is saved and waiting to sync.", tone: .warning, font: MacSheetFont.note)
                VStack(alignment: .leading, spacing: 8) {
                    SyncConflictVersionOption(label: "Your saved edit", selected: true) {
                        SyncConflictText(text: "Order potting soil").syncConflictBox()
                    }
                    SyncConflictVersionOption(label: "Current account version", selected: false) {
                        SyncConflictText(text: "Order soil for the allotment").syncConflictBox()
                    }
                }
                Button("Apply choice") {}.buttonStyle(.macStrongPill)
            }
            .padding(16)
            .frame(width: 360, alignment: .topLeading)
            .macSheetSurface()
            assertSnapshot(view, named: "mac-sheets-conflict-\(appearance.rawValue)", scheme: appearance.scheme, width: 360)
        }

        @Test("The unreadable workspace renders as approved", arguments: Appearance.allCases)
        func unreadable(appearance: Appearance) {
            let view = MacWorkspaceNoticePanel(
                title: UnreadableWorkspaceCopy.title, message: UnreadableWorkspaceCopy.message,
                detail: "The data file was saved by a newer version of Brain Buddy."
            ) {
                Button(UnreadableWorkspaceCopy.startFresh) {}.buttonStyle(.macSecondaryPill)
                Button(UnreadableWorkspaceCopy.tryAgain) {}.buttonStyle(.macStrongPill)
            }
            assertSnapshot(view, named: "mac-sheets-unreadable-\(appearance.rawValue)", scheme: appearance.scheme, width: 720)
        }

        @Test("Quick Open renders as approved", arguments: Appearance.allCases)
        func quickOpen(appearance: Appearance) {
            let view = onSheet(
                VStack(alignment: .leading, spacing: 14) {
                    QuickOpenSearchField {
                        Text("gar")
                            .font(MacSheetFont.body)
                            .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                    }
                    VStack(spacing: 2) {
                        QuickOpenResultRow(symbol: "folder", title: "Garage", subtitle: "Project", selected: true)
                        QuickOpenResultRow(
                            symbol: "circle", title: "Call Sam about the van", subtitle: "Next actions · Garage",
                            selected: false)
                        QuickOpenResultRow(
                            symbol: "tag", title: "garden", subtitle: "Tag", selected: false)
                    }
                    QuickOpenFooter(onClose: {})
                },
                padding: 18, width: 620)
            assertSnapshot(view, named: "mac-sheets-quickopen-\(appearance.rawValue)", scheme: appearance.scheme, width: 620)
        }

        @Test("The project review renders as approved", arguments: Appearance.allCases)
        func reviewProject(appearance: Appearance) {
            let view = onSheet(
                VStack(alignment: .leading, spacing: 16) {
                    MacReviewHeader(
                        title: "Review projects", caption: "3 projects on this page · revisit after seven days",
                        onClose: {})
                    HStack(spacing: 8) {
                        Button("Previous") {}.buttonStyle(.macQuietPill).disabled(true)
                        Text("1 of 3")
                            .font(MacSheetFont.meta)
                            .foregroundStyle(CarryOnColorStyle.coTextSecondary)
                        Button("Next") {}.buttonStyle(.macQuietPill)
                        Spacer()
                        Button("Open project to edit actions") {}.buttonStyle(.macSecondaryPill)
                    }
                    MacProjectReviewDetails(
                        name: "Garage", lastReviewed: "Last reviewed 2 Oct 2026",
                        reasons: ["Actions changed since the last review", "1 Someday item to reconsider"],
                        desiredOutcome: "A garage the van fits into",
                        sections: [
                            MacProjectReviewSection(
                                title: "NEXT ACTIONS · 1", rows: [MacProjectReviewRow(title: "Call Sam about the van")]),
                            MacProjectReviewSection(
                                title: "WAITING FOR · 1",
                                rows: [MacProjectReviewRow(title: "Quote for the shelves", waitingFor: "Alex")]),
                        ],
                        closuresTitle: "RECENT CLOSURES", closures: ["Completed · Clear the workbench"])
                    MacSheetDivider()
                    MacReviewLine(text: "A review does not change task dates or GTD states.", small: true)
                    Button("Mark reviewed") {}.buttonStyle(.macStrongPill)
                },
                width: 700)
            assertSnapshot(view, named: "mac-sheets-review-project-\(appearance.rawValue)", scheme: appearance.scheme, width: 700)
        }

        @Test("The Waiting for review renders as approved", arguments: Appearance.allCases)
        func reviewWaiting(appearance: Appearance) {
            let view = onSheet(
                VStack(alignment: .leading, spacing: 18) {
                    MacReviewHeader(title: "Review Waiting for", caption: "1 of 4", onClose: {})
                    MacWaitingReviewCard(
                        title: "Quote for the shelves", details: "Two options: pine or birch ply.", waitingFor: "Alex",
                        since: "Since 2 Oct 2026", project: "Project · Garage")
                    MacReviewQuestion(text: "What should happen next?")
                    HStack(spacing: 8) {
                        Button("Keep waiting") {}
                        Button("Create follow-up…") {}
                        Button("Returned to me…") {}
                        Button("No longer relevant…", role: .destructive) {}
                    }
                    .buttonStyle(.macSecondaryPill)
                },
                width: 640)
            assertSnapshot(view, named: "mac-sheets-review-waiting-\(appearance.rawValue)", scheme: appearance.scheme, width: 640)
        }

        @Test("The Someday review renders as approved", arguments: Appearance.allCases)
        func reviewSomeday(appearance: Appearance) {
            let view = onSheet(
                VStack(alignment: .leading, spacing: 18) {
                    MacReviewHeader(title: "Review Someday", caption: "2 of 5", onClose: {})
                    MacSomedayReviewCard(
                        title: "Learn to sharpen chisels", details: "The old set in the drawer.", project: "Project · Garage")
                    MacReviewQuestion(text: "Is this relevant now?")
                    HStack(spacing: 8) {
                        Button("Keep in Someday") {}
                        Button("Make it a Next action…") {}
                        Button("No longer relevant…", role: .destructive) {}
                    }
                    .buttonStyle(.macSecondaryPill)
                },
                width: 640)
            assertSnapshot(view, named: "mac-sheets-review-someday-\(appearance.rawValue)", scheme: appearance.scheme, width: 640)
        }
    }
#endif
