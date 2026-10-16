import AppKit
import BrainBuddyAPI
import BrainBuddyDesign
import BrainBuddyMacCore
import SwiftUI
import UniformTypeIdentifiers

/// The buttons each Account state offers, in Tab order (S-02); none of the follow-up feature's (028-FR-011).
enum AccountTabControl: CaseIterable {
    case export, cancelExport, exportTryAgain, tryAgain, signIn, signInAgain, signOut

    var title: String {
        switch self {
        case .export: AccountSettingsCopy.exportAction
        case .cancelExport: AccountSettingsCopy.cancel
        case .exportTryAgain, .tryAgain: AccountSettingsCopy.tryAgain
        case .signIn: AccountSettingsCopy.signIn
        case .signInAgain: AccountSettingsCopy.signInAgain
        case .signOut: AccountSettingsCopy.signOut
        }
    }

    static func visible(phase: AccountSettingsPhase, export: AccountExportFlow.State) -> [AccountTabControl] {
        var controls: [AccountTabControl] = []
        switch phase {
        case .notSignedIn: controls = [.signIn]
        case .sessionEnded: controls = [.signInAgain]
        case .offline, .failed: controls = [.tryAgain]
        case .loading, .loaded:
            switch export {
            case .exporting, .choosingLocation: controls = [.cancelExport]
            case .failed: controls = [.exportTryAgain]
            case .idle, .saved: controls = [.export]
            }
            if case .loaded(let rows) = phase, rows.methodsUnavailable { controls.append(.tryAgain) }
        }
        if phase != .notSignedIn { controls.append(.signOut) }
        return controls
    }
}

/// Design S-02 over `AccountSettingsModel` and `AccountExportFlow`; Sign in… and Sign out… use the controller.
struct AccountSettingsTab: View {
    let sync: MacSyncController
    let openMainWindow: () -> Void
    @State private var model: AccountSettingsModel
    @State private var export: AccountExportFlow?
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    init(sync: MacSyncController, openMainWindow: @escaping () -> Void) {
        (self.sync, self.openMainWindow) = (sync, openMainWindow)
        _model = State(
            initialValue: AccountSettingsModel(
                account: sync.workspace.account, sessionEnded: sync.line.description.state == .sessionEnded))
    }

    private var ended: Bool { sync.line.description.state == .sessionEnded }
    private var exportState: AccountExportFlow.State { export?.state ?? .idle }

    var body: some View {
        let controls = AccountTabControl.visible(phase: model.phase, export: exportState)
        VStack(alignment: .leading, spacing: 0) {
            switch model.phase {
            case .loading: dataRows(nil, controls)
            case .loaded(let rows): dataRows(rows, controls)
            case .notSignedIn: notice([AccountSettingsCopy.notSignedIn], controls)
            case .offline: notice([AccountSettingsCopy.offline], controls)
            case .sessionEnded: notice([AccountSettingsCopy.sessionEnded, AccountSettingsCopy.sessionEndedDetail], controls)
            case .failed(let message, let reference, let rateLimited):
                notice(
                    [message] + (rateLimited ? [AccountSettingsCopy.rateLimited] : [])
                        + (reference.map { [AccountSettingsCopy.reference($0)] } ?? []), controls)
            }
            MacSheetDivider().padding(.vertical, 8)
            SettingsRow(label: "") {
                Text(verbatim: sync.line.description.text).font(MacSheetFont.body).foregroundStyle(CarryOnColorStyle.coTextSecondary)
            } trailing: {
                if controls.contains(.signOut) {
                    Button(AccountSettingsCopy.signOut) { onMainWindow { $0.requestSignOut() } }
                        .buttonStyle(.macSecondaryPill).disabled(sync.isSignInOpen)
                }
            }
        }
        .padding(.vertical, 22).padding(.horizontal, 40)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .onChange(of: sync.workspace.account?.id, initial: true) { _, _ in
            export?.cancel()
            export = nil
            refresh()
        }
        .onChange(of: ended) { _, _ in refresh() }
        .onChange(of: scenePhase) { _, phase in if phase == .active { reload() } }
        .onChange(of: model.phase) { _, phase in
            switch phase {
            case .offline: AccessibilityNotification.Announcement(AccountSettingsCopy.offline).post()
            case .sessionEnded: AccessibilityNotification.Announcement(AccountSettingsCopy.sessionEnded).post()
            case .failed(let message, _, _): AccessibilityNotification.Announcement(message).post()
            case .notSignedIn, .loading, .loaded: break
            }
        }
        .onChange(of: exportState) { _, state in
            if case .choosingLocation(let name) = state { chooseLocation(name) }
        }
        .task(id: exportState) {
            guard case .saved = exportState else { return }
            try? await Task.sleep(for: .seconds(5))
            if !Task.isCancelled { export?.cancel() }
        }
        .onDisappear { export?.cancel() }
    }

    @ViewBuilder private func dataRows(_ rows: AccountRows?, _ controls: [AccountTabControl]) -> some View {
        SettingsRow(label: AccountSettingsCopy.nameLabel) {
            value(rows?.name) { name in
                Text(verbatim: name).frame(width: 220, alignment: .leading).padding(.horizontal, 8).padding(.vertical, 5)
                    .background(CarryOnColorStyle.coSurfaceCard, in: RoundedRectangle(cornerRadius: 6, style: .continuous))
            }
        }
        SettingsRow(label: AccountSettingsCopy.stepsLabel) { value(rows?.steps) }
        MacSheetDivider().padding(.vertical, 8)
        SettingsRow(label: AccountSettingsCopy.emailLabel) { value(rows?.email) }
        SettingsRow(label: AccountSettingsCopy.appleLabel) { value(rows?.apple) }
        SettingsRow(label: AccountSettingsCopy.googleLabel) { value(rows?.google) }
        SettingsRow(label: AccountSettingsCopy.passwordLabel) { value(rows?.password) }
        if rows?.methodsUnavailable == true {
            SettingsRow(label: "") {
                MacSheetStatus(text: AccountSettingsCopy.methodsFailed, tone: .danger, font: MacSheetFont.note)
            } trailing: {
                Button(AccountSettingsCopy.tryAgain) { reload() }.buttonStyle(.macText)
            }
        }
        MacSheetDivider().padding(.vertical, 8)
        SettingsRow(label: AccountSettingsCopy.dataLabel) { exportValue } trailing: { exportButton(controls) }
    }

    private func notice(_ lines: [String], _ controls: [AccountTabControl]) -> some View {
        VStack(spacing: 10) {
            ForEach(lines, id: \.self) { line in
                Text(verbatim: line).font(MacSheetFont.body)
                    .foregroundStyle(line == lines.first ? CarryOnColorStyle.coTextPrimary : CarryOnColorStyle.coTextSecondary)
            }
            ForEach([AccountTabControl.tryAgain, .signIn, .signInAgain], id: \.self) { control in
                if controls.contains(control) {
                    Button(control.title) {
                        if control == .tryAgain { reload() } else { onMainWindow { $0.beginSignIn(from: .menu) } }
                    }
                    .buttonStyle(.macSecondaryPill)
                    .disabled(control != .tryAgain && (sync.isSignInOpen || sync.isSigningOut))
                }
            }
        }
        .frame(maxWidth: .infinity, minHeight: 200)
    }

    @ViewBuilder private var exportValue: some View {
        switch exportState {
        case .idle: value(AccountSettingsCopy.dataValue)
        case .saved: value(AccountSettingsCopy.saved)
        case .exporting, .choosingLocation: loadingCell(AccountSettingsCopy.exporting)
        case .failed(let kind, let reference):
            VStack(alignment: .leading, spacing: 4) {
                MacSheetStatus(text: kind.message, tone: .danger, font: MacSheetFont.body)
                if let reference {
                    Text(verbatim: AccountSettingsCopy.reference(reference))
                        .font(MacSheetFont.reference).foregroundStyle(CarryOnColorStyle.coTextSecondary)
                }
            }
        }
    }

    @ViewBuilder private func exportButton(_ controls: [AccountTabControl]) -> some View {
        if controls.contains(.cancelExport) {
            Button(AccountSettingsCopy.cancel) { export?.cancel() }.buttonStyle(.macSecondaryPill)
        } else if let again = controls.first(where: { $0 == .exportTryAgain || $0 == .export }) {
            Button(again.title) { startExport() }.buttonStyle(.macSecondaryPill).disabled(model.phase == .loading)
        }
    }

    private func value(_ text: String?) -> some View { value(text) { Text(verbatim: $0) } }
    private func value<Content: View>(_ text: String?, _ content: (String) -> Content) -> some View {
        Group {
            if let text {
                content(text).font(MacSheetFont.body).foregroundStyle(CarryOnColorStyle.coTextPrimary)
            } else {
                loadingCell(AccountSettingsCopy.loading)
            }
        }
    }

    private func loadingCell(_ words: String) -> some View {
        HStack(spacing: 6) {
            if !reduceMotion { ProgressView().controlSize(.small) }
            Text(words).font(MacSheetFont.body).foregroundStyle(CarryOnColorStyle.coTextSecondary)
        }
    }

    private func refresh() {
        model.update(account: sync.workspace.account, sessionEnded: ended)
        reload()
    }

    private func reload() { Task { await model.reload() } }
    /// S-02.13: the main window comes forward, then the controller's entry runs as the menu's does.
    private func onMainWindow(_ action: @escaping @MainActor (MacSyncController) -> Void) {
        openMainWindow()
        Task { [sync] in action(sync) }
    }

    private func startExport() {
        if export == nil, let account = sync.workspace.account {
            export = AccountExportFlow(
                remote: BrainBuddyAPIClient(
                    baseURL: account.serverURL, tokenStore: WorkspaceHost.systemTokenStore(), identity: WorkspaceHost.clientIdentity))
        }
        export?.start()
    }

    private func chooseLocation(_ name: String) {
        guard let flow = export else { return }
        Task {
            let panel = NSSavePanel()
            (panel.nameFieldStringValue, panel.allowedContentTypes) = (name, [.zip])
            if panel.runModal() == .OK, let url = panel.url { flow.save(to: url) } else { flow.cancel() }
        }
    }
}

/// One row: 150 pt label, value, optional trailing control; label and value read together to VoiceOver.
private struct SettingsRow<Value: View, Trailing: View>: View {
    let label: String
    @ViewBuilder let value: Value
    @ViewBuilder let trailing: Trailing

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 14) {
            HStack(alignment: .firstTextBaseline, spacing: 14) {
                Text(label).font(MacSheetFont.body).foregroundStyle(CarryOnColorStyle.coTextSecondary)
                    .frame(width: 150, alignment: .trailing)
                value.frame(maxWidth: .infinity, alignment: .leading)
            }
            .accessibilityElement(children: .combine)
            trailing
        }
        .padding(.vertical, 6)
    }
}

extension SettingsRow where Trailing == EmptyView {
    fileprivate init(label: String, @ViewBuilder value: () -> Value) { self.init(label: label, value: value, trailing: { EmptyView() }) }
}
