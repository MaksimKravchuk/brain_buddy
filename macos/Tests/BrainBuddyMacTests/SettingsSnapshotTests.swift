#if canImport(SwiftUI) && os(macOS)
    import BrainBuddyDesign
    import BrainBuddyDesignTestSupport
    import Foundation
    import SwiftUI
    import Testing

    @testable import BrainBuddyMac
    @testable import BrainBuddyMacCore

    /// The Mac Settings window (spec 028, design S-02 – S-04) against its approved renders, light and dark:
    /// the Account tab's loaded, loading, methods-unavailable, offline, session-ended, signed-out, exporting
    /// and export-failed states, the Agents tab's ready and unavailable states, and the Sync tab. The Account
    /// and Agents states render the shipped `AccountSettingsContent` and `AgentsSettingsContent` from fixed
    /// state, so the shipped layout is what is compared. The Sync tab hosts the unchanged 021 popover parts,
    /// which need a live controller as a whole. A spinner is not drawn (it is AppKit-backed): `showsProgress`
    /// is off, the static words that replace it under Reduce Motion are what render.
    @Suite("Mac Settings snapshots")
    @MainActor
    struct SettingsSnapshotTests {
        enum Appearance: String, CaseIterable, Sendable {
            case light, dark

            var scheme: ColorScheme { self == .dark ? .dark : .light }
        }

        // MARK: Sample state (the M25 sample)

        private static let loadedRows = AccountRows(
            name: "Max", steps: "214", email: AccountSettingsCopy.email("max@example.com", verified: true),
            apple: AccountSettingsCopy.connected, google: AccountSettingsCopy.notConnected,
            password: AccountSettingsCopy.passwordSet, methodsUnavailable: false)

        private static let methodsUnavailableRows = AccountRows(
            name: "Max", steps: "214", email: AccountSettingsCopy.email("max@example.com", verified: nil),
            apple: AccountSettingsCopy.unavailable, google: AccountSettingsCopy.unavailable,
            password: AccountSettingsCopy.unavailable, methodsUnavailable: true)

        private static let agentsURL = URL(string: "https://app.brainbuddy.example/settings/agents") ?? URL(fileURLWithPath: "/")

        private func accountTab(
            _ phase: AccountSettingsPhase, export: AccountExportFlow.State = .idle
        ) -> some View {
            AccountSettingsContent(
                phase: phase, export: export, syncLine: "Synced a minute ago", signInBusy: false, signOutBusy: false,
                showsProgress: false, onTryAgain: {}, onSignIn: {}, onSignOut: {}, onExport: {}, onCancelExport: {}
            )
            .background(CarryOnColorStyle.coBgGround)
        }

        private func agentsTab(_ state: AgentsWebLink.State) -> some View {
            AgentsSettingsContent(state: state, onOpen: { _ in }, onTryAgain: {})
                .background(CarryOnColorStyle.coBgGround)
        }

        private func secondaryButton(_ title: String) -> some View {
            Button(title) {}.buttonStyle(.macSecondaryPill)
        }

        private func textButton(_ title: String) -> some View {
            Button(title) {}.buttonStyle(.macText)
        }

        // MARK: Sync tab (S-04)

        /// S-04.01: the 021 X-02 popover content at the popover's width, centred in the tab.
        private func syncTab() -> some View {
            VStack(alignment: .leading, spacing: 14) {
                SyncPopoverLines(lastSynced: "Last synced · Today at 14:31", queue: "2 changes waiting to sync")
                secondaryButton("Sync now")
                MacSheetDivider()
                SyncPopoverAccount(email: "max@example.com") {
                    textButton(AccountSettingsCopy.signOut)
                }
            }
            .padding(16)
            .frame(width: 360, alignment: .topLeading)
            .macSheetSurface()
            .frame(maxWidth: .infinity)
            .padding(.vertical, 22)
            .background(CarryOnColorStyle.coBgGround)
        }

        // MARK: Tests

        @Test(
            "028_FR_006 028_FR_022 028_SC_007 the Account tab's loaded state renders as approved",
            arguments: Appearance.allCases)
        func accountLoadedRenders(appearance: Appearance) {
            assertSnapshot(
                accountTab(.loaded(Self.loadedRows)), named: "mac-settings-account-loaded-\(appearance.rawValue)",
                scheme: appearance.scheme, width: 820)
        }

        @Test("028_FR_004 028_FR_022 028_SC_007 the Account tab's loading state renders as approved", arguments: Appearance.allCases)
        func accountLoadingRenders(appearance: Appearance) {
            assertSnapshot(
                accountTab(.loading), named: "mac-settings-account-loading-\(appearance.rawValue)",
                scheme: appearance.scheme, width: 820)
        }

        @Test(
            "028_FR_008 028_FR_010 028_FR_017 028_FR_022 028_SC_007 the methods-unavailable state renders as approved",
            arguments: Appearance.allCases)
        func accountMethodsUnavailableRenders(appearance: Appearance) {
            assertSnapshot(
                accountTab(.loaded(Self.methodsUnavailableRows)), named: "mac-settings-account-methods-unavailable-\(appearance.rawValue)",
                scheme: appearance.scheme, width: 820)
        }

        @Test("028_FR_016 028_FR_022 028_SC_007 the offline state renders as approved", arguments: Appearance.allCases)
        func accountOfflineRenders(appearance: Appearance) {
            assertSnapshot(
                accountTab(.offline), named: "mac-settings-account-offline-\(appearance.rawValue)",
                scheme: appearance.scheme, width: 820)
        }

        @Test(
            "028_FR_005 028_FR_016 028_FR_022 028_SC_007 the session-ended state renders as approved",
            arguments: Appearance.allCases)
        func accountSessionEndedRenders(appearance: Appearance) {
            assertSnapshot(
                accountTab(.sessionEnded), named: "mac-settings-account-session-ended-\(appearance.rawValue)",
                scheme: appearance.scheme, width: 820)
        }

        @Test("028_FR_015 028_FR_022 028_SC_007 the signed-out state renders as approved", arguments: Appearance.allCases)
        func accountSignedOutRenders(appearance: Appearance) {
            assertSnapshot(
                accountTab(.notSignedIn), named: "mac-settings-account-signed-out-\(appearance.rawValue)",
                scheme: appearance.scheme, width: 820)
        }

        @Test("028_FR_012 028_FR_022 028_SC_007 the exporting state renders as approved", arguments: Appearance.allCases)
        func accountExportingRenders(appearance: Appearance) {
            assertSnapshot(
                accountTab(.loaded(Self.loadedRows), export: .exporting), named: "mac-settings-account-exporting-\(appearance.rawValue)",
                scheme: appearance.scheme, width: 820)
        }

        @Test(
            "028_FR_013 028_FR_017 028_FR_022 028_SC_007 the export-failed state renders as approved",
            arguments: Appearance.allCases)
        func accountExportFailedRenders(appearance: Appearance) {
            assertSnapshot(
                accountTab(.loaded(Self.loadedRows), export: .failed(kind: .offline, reference: "7f3a9c2e")), named: "mac-settings-account-export-failed-\(appearance.rawValue)",
                scheme: appearance.scheme, width: 820)
        }

        @Test("028_FR_019 028_FR_022 028_SC_007 the Agents tab renders as approved", arguments: Appearance.allCases)
        func agentsReadyRenders(appearance: Appearance) {
            assertSnapshot(
                agentsTab(.ready(Self.agentsURL)), named: "mac-settings-agents-ready-\(appearance.rawValue)",
                scheme: appearance.scheme, width: 820)
        }

        @Test(
            "028_FR_019 028_FR_022 028_SC_007 the Agents tab with the origin unavailable renders as approved",
            arguments: Appearance.allCases)
        func agentsUnavailableRenders(appearance: Appearance) {
            assertSnapshot(
                agentsTab(.unavailable), named: "mac-settings-agents-unavailable-\(appearance.rawValue)",
                scheme: appearance.scheme, width: 820)
        }

        @Test("028_FR_020 028_FR_022 028_SC_007 the Sync tab renders as approved", arguments: Appearance.allCases)
        func syncTabRenders(appearance: Appearance) {
            assertSnapshot(
                syncTab(), named: "mac-settings-sync-\(appearance.rawValue)", scheme: appearance.scheme, width: 820)
        }
    }
#endif
