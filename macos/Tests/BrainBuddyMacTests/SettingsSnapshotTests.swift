#if canImport(SwiftUI) && os(macOS)
    import BrainBuddyDesign
    import BrainBuddyDesignTestSupport
    import BrainBuddyMacCore
    import SwiftUI
    import Testing

    @testable import BrainBuddyMac

    /// The Mac Settings window (spec 028, design S-02 – S-04) against its approved renders, light and dark:
    /// the Account tab's loaded, loading, methods-unavailable, offline, session-ended, signed-out, exporting
    /// and export-failed states, the Agents tab's ready and unavailable states, and the Sync tab. The tabs
    /// read a live sync controller and fetch their own state, so each state is composed here from the same
    /// parts with sample text, as `CarryOnSheetsSnapshotTests` composes the sheets. The row layout mirrors
    /// `SettingsRow` and the value styles mirror `AccountSettingsTab`. A spinner is not drawn (it is
    /// AppKit-backed); the static words that replace it under Reduce Motion are what render.
    @Suite("Mac Settings snapshots")
    @MainActor
    struct SettingsSnapshotTests {
        enum Appearance: String, CaseIterable, Sendable {
            case light, dark

            var scheme: ColorScheme { self == .dark ? .dark : .light }
        }

        // MARK: Parts

        /// One row as `SettingsRow` lays it out: a 150 pt right-aligned label, the value and the trailing control.
        private func row(_ label: String, value: some View, trailing: some View) -> some View {
            HStack(alignment: .firstTextBaseline, spacing: 14) {
                HStack(alignment: .firstTextBaseline, spacing: 14) {
                    Text(verbatim: label).font(MacSheetFont.body).foregroundStyle(CarryOnColorStyle.coTextSecondary)
                        .frame(width: 150, alignment: .trailing)
                    value.frame(maxWidth: .infinity, alignment: .leading)
                }
                trailing
            }
            .padding(.vertical, 6)
        }

        private func divider() -> some View {
            MacSheetDivider().padding(.vertical, 8)
        }

        private func valueText(_ text: String) -> some View {
            Text(verbatim: text).font(MacSheetFont.body).foregroundStyle(CarryOnColorStyle.coTextPrimary)
        }

        /// Words in the secondary style: "Loading…", "Exporting…" and the sync line.
        private func wordsCell(_ words: String) -> some View {
            Text(verbatim: words).font(MacSheetFont.body).foregroundStyle(CarryOnColorStyle.coTextSecondary)
        }

        /// A value cell: its text, or "Loading…" while the read is in flight.
        private func cell(_ text: String?) -> some View {
            Group {
                if let text {
                    valueText(text)
                } else {
                    wordsCell(AccountSettingsCopy.loading)
                }
            }
        }

        /// The Name value: read-only text in a `surface-card` box, 220 pt wide, as drawn.
        private func nameCell(_ name: String?) -> some View {
            Group {
                if let name {
                    Text(verbatim: name).font(MacSheetFont.body).foregroundStyle(CarryOnColorStyle.coTextPrimary)
                        .frame(width: 220, alignment: .leading).padding(.horizontal, 8).padding(.vertical, 5)
                        .background(CarryOnColorStyle.coSurfaceCard, in: RoundedRectangle(cornerRadius: 6, style: .continuous))
                } else {
                    wordsCell(AccountSettingsCopy.loading)
                }
            }
        }

        private func secondaryButton(_ title: String, disabled: Bool = false) -> some View {
            Button(title) {}.buttonStyle(.macSecondaryPill).disabled(disabled)
        }

        private func textButton(_ title: String) -> some View {
            Button(title) {}.buttonStyle(.macText)
        }

        /// Name and Steps taken, then the rule.
        private func identityRows(name: String?, steps: String?) -> some View {
            VStack(alignment: .leading, spacing: 0) {
                row(AccountSettingsCopy.nameLabel, value: nameCell(name), trailing: EmptyView())
                row(AccountSettingsCopy.stepsLabel, value: cell(steps), trailing: EmptyView())
                divider()
            }
        }

        /// Email, Apple, Google and Password.
        private func methodRows(email: String?, apple: String?, google: String?, password: String?) -> some View {
            VStack(alignment: .leading, spacing: 0) {
                row(AccountSettingsCopy.emailLabel, value: cell(email), trailing: EmptyView())
                row(AccountSettingsCopy.appleLabel, value: cell(apple), trailing: EmptyView())
                row(AccountSettingsCopy.googleLabel, value: cell(google), trailing: EmptyView())
                row(AccountSettingsCopy.passwordLabel, value: cell(password), trailing: EmptyView())
            }
        }

        /// S-02.03: the one line under the Password row, with Try again.
        private func methodsFailedRow() -> some View {
            row(
                "",
                value: MacSheetStatus(text: AccountSettingsCopy.methodsFailed, tone: .danger, font: MacSheetFont.note),
                trailing: textButton(AccountSettingsCopy.tryAgain))
        }

        /// The "Your data" row: the value, and the trailing control of the state.
        private func dataRow(value: some View, trailing: some View) -> some View {
            row(AccountSettingsCopy.dataLabel, value: value, trailing: trailing)
        }

        /// The footer under every Account state: the sync status words, and Sign out… while signed in.
        private func footer(signedIn: Bool) -> some View {
            VStack(alignment: .leading, spacing: 0) {
                divider()
                if signedIn {
                    row("", value: wordsCell("Synced a minute ago"), trailing: secondaryButton(AccountSettingsCopy.signOut))
                } else {
                    row("", value: wordsCell("Synced a minute ago"), trailing: EmptyView())
                }
            }
        }

        /// A notice that replaces the rows (S-02.04 – S-02.06): centred words, then one button.
        private func notice(primary: String, secondary: String?, action: String) -> some View {
            VStack(spacing: 10) {
                Text(verbatim: primary).font(MacSheetFont.body).foregroundStyle(CarryOnColorStyle.coTextPrimary)
                if let secondary {
                    Text(verbatim: secondary).font(MacSheetFont.body).foregroundStyle(CarryOnColorStyle.coTextSecondary)
                }
                secondaryButton(action)
            }
            .frame(maxWidth: .infinity, minHeight: 200)
        }

        /// The Account tab on the window's ground, with the tab's padding (22 top and bottom, 40 sides).
        private func accountTab(_ content: some View) -> some View {
            content
                .padding(.vertical, 22).padding(.horizontal, 40)
                .frame(maxWidth: .infinity, alignment: .topLeading)
                .background(CarryOnColorStyle.coBgGround)
        }

        /// The loaded rows (S-02.02) for the M25 sample, with the export row given by the caller.
        private func loadedRows(export: some View, footerSignedIn: Bool = true) -> some View {
            VStack(alignment: .leading, spacing: 0) {
                identityRows(name: "Max", steps: "214")
                methodRows(
                    email: AccountSettingsCopy.email("max@example.com", verified: true),
                    apple: AccountSettingsCopy.connected, google: AccountSettingsCopy.notConnected,
                    password: AccountSettingsCopy.passwordSet)
                divider()
                export
                footer(signedIn: footerSignedIn)
            }
        }

        // MARK: Account tab (S-02)

        /// S-02.02, the M25 sample: Max, 214 steps, verified email, Apple connected, Google not, password set.
        private func accountLoaded() -> some View {
            accountTab(
                loadedRows(
                    export: dataRow(
                        value: valueText(AccountSettingsCopy.dataValue),
                        trailing: secondaryButton(AccountSettingsCopy.exportAction))))
        }

        /// S-02.01: each value reads "Loading…", and Export… is disabled.
        private func accountLoading() -> some View {
            accountTab(
                VStack(alignment: .leading, spacing: 0) {
                    identityRows(name: nil, steps: nil)
                    methodRows(email: nil, apple: nil, google: nil, password: nil)
                    divider()
                    dataRow(
                        value: valueText(AccountSettingsCopy.dataValue),
                        trailing: secondaryButton(AccountSettingsCopy.exportAction, disabled: true))
                    footer(signedIn: true)
                })
        }

        /// S-02.03: the account read, the methods read failed; "· Unavailable" and the line with Try again.
        private func accountMethodsUnavailable() -> some View {
            accountTab(
                VStack(alignment: .leading, spacing: 0) {
                    identityRows(name: "Max", steps: "214")
                    methodRows(
                        email: AccountSettingsCopy.email("max@example.com", verified: nil),
                        apple: AccountSettingsCopy.unavailable, google: AccountSettingsCopy.unavailable,
                        password: AccountSettingsCopy.unavailable)
                    methodsFailedRow()
                    divider()
                    dataRow(
                        value: valueText(AccountSettingsCopy.dataValue),
                        trailing: secondaryButton(AccountSettingsCopy.exportAction))
                    footer(signedIn: true)
                })
        }

        /// S-02.04: the rows are replaced by the offline words and Try again; the footer stays.
        private func accountOffline() -> some View {
            accountTab(
                VStack(alignment: .leading, spacing: 0) {
                    notice(primary: AccountSettingsCopy.offline, secondary: nil, action: AccountSettingsCopy.tryAgain)
                    divider()
                    footer(signedIn: true)
                })
        }

        /// S-02.05: the session ended; Sign in again… and the footer stays.
        private func accountSessionEnded() -> some View {
            accountTab(
                VStack(alignment: .leading, spacing: 0) {
                    notice(
                        primary: AccountSettingsCopy.sessionEnded, secondary: AccountSettingsCopy.sessionEndedDetail,
                        action: AccountSettingsCopy.signInAgain)
                    divider()
                    footer(signedIn: true)
                })
        }

        /// S-02.06: not signed in; Sign in… and no Sign out… in the footer.
        private func accountSignedOut() -> some View {
            accountTab(
                VStack(alignment: .leading, spacing: 0) {
                    notice(primary: AccountSettingsCopy.notSignedIn, secondary: nil, action: AccountSettingsCopy.signIn)
                    divider()
                    footer(signedIn: false)
                })
        }

        /// S-02.09: the data value reads "Exporting…" and Export… is replaced by Cancel.
        private func accountExporting() -> some View {
            accountTab(
                loadedRows(
                    export: dataRow(
                        value: wordsCell(AccountSettingsCopy.exporting),
                        trailing: secondaryButton(AccountSettingsCopy.cancel))))
        }

        /// S-02.11: the failure in words, the reference, and Try again.
        private func accountExportFailed() -> some View {
            accountTab(
                loadedRows(
                    export: dataRow(
                        value: VStack(alignment: .leading, spacing: 4) {
                            MacSheetStatus(text: AccountSettingsCopy.exportOffline, tone: .danger, font: MacSheetFont.body)
                            Text(verbatim: AccountSettingsCopy.reference("7f3a9c2e"))
                                .font(MacSheetFont.reference).foregroundStyle(CarryOnColorStyle.coTextSecondary)
                        },
                        trailing: secondaryButton(AccountSettingsCopy.tryAgain))))
        }

        // MARK: Agents tab (S-03)

        /// S-03.01 (ready) and S-03.03 (origin unavailable): the text and the web button, centred.
        private func agentsTab(unavailable: Bool) -> some View {
            VStack(spacing: 14) {
                Text(verbatim: AccountSettingsCopy.agentsText)
                    .font(MacSheetFont.body).foregroundStyle(CarryOnColorStyle.coTextPrimary)
                secondaryButton(AccountSettingsCopy.agentsAction, disabled: unavailable)
                if unavailable {
                    MacSheetStatus(text: AccountSettingsCopy.agentsUnavailable, tone: .danger, font: MacSheetFont.note)
                    textButton(AccountSettingsCopy.tryAgain)
                }
            }
            .frame(maxWidth: .infinity, minHeight: 220)
            .background(CarryOnColorStyle.coBgGround)
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
                accountLoaded(), named: "mac-settings-account-loaded-\(appearance.rawValue)",
                scheme: appearance.scheme, width: 820)
        }

        @Test("028_FR_004 028_FR_022 028_SC_007 the Account tab's loading state renders as approved", arguments: Appearance.allCases)
        func accountLoadingRenders(appearance: Appearance) {
            assertSnapshot(
                accountLoading(), named: "mac-settings-account-loading-\(appearance.rawValue)",
                scheme: appearance.scheme, width: 820)
        }

        @Test(
            "028_FR_008 028_FR_010 028_FR_017 028_FR_022 028_SC_007 the methods-unavailable state renders as approved",
            arguments: Appearance.allCases)
        func accountMethodsUnavailableRenders(appearance: Appearance) {
            assertSnapshot(
                accountMethodsUnavailable(), named: "mac-settings-account-methods-unavailable-\(appearance.rawValue)",
                scheme: appearance.scheme, width: 820)
        }

        @Test("028_FR_016 028_FR_022 028_SC_007 the offline state renders as approved", arguments: Appearance.allCases)
        func accountOfflineRenders(appearance: Appearance) {
            assertSnapshot(
                accountOffline(), named: "mac-settings-account-offline-\(appearance.rawValue)",
                scheme: appearance.scheme, width: 820)
        }

        @Test(
            "028_FR_005 028_FR_016 028_FR_022 028_SC_007 the session-ended state renders as approved",
            arguments: Appearance.allCases)
        func accountSessionEndedRenders(appearance: Appearance) {
            assertSnapshot(
                accountSessionEnded(), named: "mac-settings-account-session-ended-\(appearance.rawValue)",
                scheme: appearance.scheme, width: 820)
        }

        @Test("028_FR_015 028_FR_022 028_SC_007 the signed-out state renders as approved", arguments: Appearance.allCases)
        func accountSignedOutRenders(appearance: Appearance) {
            assertSnapshot(
                accountSignedOut(), named: "mac-settings-account-signed-out-\(appearance.rawValue)",
                scheme: appearance.scheme, width: 820)
        }

        @Test("028_FR_012 028_FR_022 028_SC_007 the exporting state renders as approved", arguments: Appearance.allCases)
        func accountExportingRenders(appearance: Appearance) {
            assertSnapshot(
                accountExporting(), named: "mac-settings-account-exporting-\(appearance.rawValue)",
                scheme: appearance.scheme, width: 820)
        }

        @Test(
            "028_FR_013 028_FR_017 028_FR_022 028_SC_007 the export-failed state renders as approved",
            arguments: Appearance.allCases)
        func accountExportFailedRenders(appearance: Appearance) {
            assertSnapshot(
                accountExportFailed(), named: "mac-settings-account-export-failed-\(appearance.rawValue)",
                scheme: appearance.scheme, width: 820)
        }

        @Test("028_FR_019 028_FR_022 028_SC_007 the Agents tab renders as approved", arguments: Appearance.allCases)
        func agentsReadyRenders(appearance: Appearance) {
            assertSnapshot(
                agentsTab(unavailable: false), named: "mac-settings-agents-ready-\(appearance.rawValue)",
                scheme: appearance.scheme, width: 820)
        }

        @Test(
            "028_FR_019 028_FR_022 028_SC_007 the Agents tab with the origin unavailable renders as approved",
            arguments: Appearance.allCases)
        func agentsUnavailableRenders(appearance: Appearance) {
            assertSnapshot(
                agentsTab(unavailable: true), named: "mac-settings-agents-unavailable-\(appearance.rawValue)",
                scheme: appearance.scheme, width: 820)
        }

        @Test("028_FR_020 028_FR_022 028_SC_007 the Sync tab renders as approved", arguments: Appearance.allCases)
        func syncTabRenders(appearance: Appearance) {
            assertSnapshot(
                syncTab(), named: "mac-settings-sync-\(appearance.rawValue)", scheme: appearance.scheme, width: 820)
        }
    }
#endif
