#if canImport(SwiftUI) && os(macOS)
    import BrainBuddyMacCore
    import Foundation
    import Testing

    @testable import BrainBuddyMac

    /// The Settings window's structure (spec 028, design S-01 – S-04): the tabs in the board's order,
    /// the buttons each Account state offers (and none of the follow-up feature's), the existing
    /// sign-out entry, and the Sync tab hosting the popover without touching the router.
    @Suite("Mac Settings scene")
    @MainActor
    struct MacSettingsSceneTests {
        private static let rows = AccountRows(
            name: "Max", steps: "214", email: "max@example.com · Verified", apple: "Connected", google: "Not connected",
            password: "Set · also used for Mac sign-in", methodsUnavailable: false)
        private static let phases: [AccountSettingsPhase] = [
            .notSignedIn, .loading, .loaded(rows), .loaded(AccountRows(
                name: "Max", steps: "214", email: "max@example.com · Unavailable", apple: "Unavailable",
                google: "Unavailable", password: "Unavailable", methodsUnavailable: true)),
            .offline, .sessionEnded,
            .failed(message: AccountSettingsCopy.loadFailed, reference: "ref-1", rateLimited: false),
            .failed(message: AccountSettingsCopy.loadFailed, reference: nil, rateLimited: true),
        ]
        private static let exports: [AccountExportFlow.State] = [
            .idle, .exporting, .choosingLocation(suggestedName: "brainbuddy-export.zip"), .saved,
            .failed(kind: .offline, reference: nil), .failed(kind: .cannotSave, reference: nil),
            .failed(kind: .server, reference: "ref-2"),
        ]

        @Test("028-FR-002 the tab bar has Account, Agents, Sync in that order, each with its own glyph")
        func tabsInOrder() {
            #expect(MacSettingsTab.allCases.map(\.title) == ["Account", "Agents", "Sync"])
            #expect(MacSettingsTab.allCases.map(\.title) == AccountSettingsCopy.tabNames)
            #expect(MacSettingsTab.allCases.map(\.icon) == [.account, .agents, .sync])
            #expect(MacSettingsTab.allCases.first == .account, "the window opens on Account")
        }

        @Test("028-FR-011 028-SC-008 no state offers Change…, Connect…, Remove… or Delete account…")
        func noFollowUpControlInAnyState() {
            let allowed: Set<String> = [
                "Export…", "Cancel", "Try again", "Sign in…", "Sign in again…", "Sign out…",
            ]
            let forbidden = ["Change", "Connect", "Remove", "Delete", "Manage on the web"]
            #expect(Set(AccountTabControl.allCases.map(\.title)).isSubset(of: allowed))
            for phase in Self.phases {
                for export in Self.exports {
                    for control in AccountTabControl.visible(phase: phase, export: export) {
                        #expect(allowed.contains(control.title), "\(phase) \(export)")
                        #expect(!forbidden.contains { control.title.hasPrefix($0) })
                    }
                }
            }
        }

        @Test("028-FR-014 028-FR-015 028-FR-016 the buttons of each Account state, in Tab order")
        func controlsPerState() {
            func controls(_ phase: AccountSettingsPhase, _ export: AccountExportFlow.State = .idle) -> [AccountTabControl] {
                AccountTabControl.visible(phase: phase, export: export)
            }
            #expect(controls(.notSignedIn) == [.signIn], "no Sign out… without an account")
            #expect(controls(.sessionEnded) == [.signInAgain, .signOut])
            #expect(controls(.offline) == [.tryAgain, .signOut])
            #expect(controls(.failed(message: "x", reference: nil, rateLimited: true)) == [.tryAgain, .signOut])
            #expect(controls(.loading) == [.export, .signOut])
            #expect(controls(.loaded(Self.rows)) == [.export, .signOut])
            #expect(controls(.loaded(Self.rows), .exporting) == [.cancelExport, .signOut])
            #expect(controls(.loaded(Self.rows), .choosingLocation(suggestedName: "a.zip")) == [.cancelExport, .signOut])
            #expect(controls(.loaded(Self.rows), .saved) == [.export, .signOut])
            #expect(controls(.loaded(Self.rows), .failed(kind: .server, reference: nil)) == [.exportTryAgain, .signOut])
        }

        @Test("028-FR-004 028-FR-012 export failures read from AccountExportFlow, one source")
        func exportFailureWordsHaveOneSource() {
            #expect(AccountExportFlow.FailureKind.offline.message == AccountSettingsCopy.exportOffline)
            #expect(AccountExportFlow.FailureKind.cannotSave.message == AccountSettingsCopy.exportNotWritable)
            #expect(AccountExportFlow.FailureKind.server.message == AccountSettingsCopy.exportFailed)
        }

        @Test("028-FR-014 Sign out… from Settings asks the controller exactly as the menu does")
        func signOutRequestMatchesMenu() async {
            let rig = await MacSyncFlowTests.Rig()
            await rig.signIn()
            #expect(rig.controller.accountMenu.signOut)
            let before = rig.controller.signOutRequests
            // The Settings button and the app menu both call this entry; the window runs its guard next.
            rig.controller.requestSignOut()
            #expect(rig.controller.signOutRequests == before + 1)
            #expect(rig.controller.router.surface == nil, "X-04 waits for the main window's guard")
            #expect(rig.controller.signOut.prompt == nil)
        }

        @Test("028-FR-020 hosting the Sync tab leaves the router's surface and requests unchanged")
        func syncTabLeavesRouterAlone() async {
            let rig = await MacSyncFlowTests.Rig()
            await rig.signIn()
            let router = rig.controller.router
            let surface = router.surface
            let serial = router.presentationSerial
            let focus = router.focus?.serial
            let tab = SyncSettingsTab(controller: rig.controller)
            #expect(tab.controller === rig.controller)
            #expect(router.surface == surface)
            #expect(router.presentationSerial == serial)
            #expect(router.focus?.serial == focus)
        }
    }
#endif
