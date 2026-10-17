import BrainBuddyCore
import BrainBuddyDesign
import BrainBuddyWorkspace
import SwiftUI
import UIKit

/// Account, sync, the weekly review's threshold and about. Everything here
/// reads the workspace; the only network actions are signing in and
/// "Sync now".
struct SettingsScreen: View {
    @Environment(Workspace.self) private var workspace
    @Environment(\.colorScheme) private var scheme
    /// Nil unless the build records performance diagnostics (beta builds).
    @Environment(PerformanceDiagnostics.self) private var diagnostics: PerformanceDiagnostics?

    @State private var signInRequest: SignInRequest?

    init() {}

    var body: some View {
        List {
            accountSection
            AgentsAccountSection()
            if workspace.account != nil {
                syncSection
            } else if issueCount > 0 {
                Section { syncIssuesLink }
                .listRowBackground(cardBackground)
            }
            // Weekly review (spec 020, M-23); shown only while it is exposed.
            ReviewSettingsSection()
                .listRowBackground(cardBackground)
            if diagnostics != nil {
                RustRuntimePilotRow()
                    .listRowBackground(cardBackground)
            }
            aboutSection
        }
        .labelStyle(.bbRow)
        .bbDenseList()
        // Carry On board 25: inset grouped sections of surface-card rows on bg-ground.
        .listStyle(.insetGrouped)
        .carryOnFont(CarryOnTypeScale.body)
        .listRowSeparatorTint(groundColor)
        .scrollContentBackground(.hidden)
        .background(.coBgGround)
        .bbScreenTitle("Settings")
        .sheet(item: $signInRequest) { request in
            SignInSheet(email: request.email, serverURL: request.serverURL)
        }
    }

    // MARK: Account

    @ViewBuilder private var accountSection: some View {
        if let account = workspace.account {
            Section {
                NavigationLink(value: AppRoute.account) {
                    AccountIdentityRow(
                        name: account.displayName, email: account.email,
                        host: Self.hostDescription(account.serverURL))
                }
                if workspace.syncStatus == .needsSignIn {
                    Button {
                        signInRequest = SignInRequest(email: account.email, serverURL: account.serverURL)
                    } label: {
                        Label("Sign in again", systemImage: "person.crop.circle.badge.exclamationmark")
                    }
                }
            } header: {
                SettingsSectionHeader("Account")
            }
            .listRowBackground(cardBackground)
        } else {
            Section {
                Button {
                    signInRequest = SignInRequest(email: "", serverURL: nil)
                } label: {
                    Label("Sign in", systemImage: "person.crop.circle.badge.plus")
                }
            } header: {
                SettingsSectionHeader("Account")
            } footer: {
                Text(localOnlyExplanation)
                    .carryOnFont(CarryOnTypeScale.meta)
                    .foregroundStyle(.coTextSecondary)
            }
            .listRowBackground(cardBackground)
        }
    }

    private var groundColor: Color {
        CarryOnColorStyle(CarryOnRole.bgGround).color(in: scheme)
    }

    private var cardBackground: some View {
        Rectangle().fill(.coSurfaceCard)
    }

    private var localOnlyExplanation: String {
        "Your tasks are stored on this \(ThisDevice.name). Sign in to sync with Brain Buddy on the web."
    }

    // MARK: Sync

    private var syncSection: some View {
        Section {
            syncStatusRow
            if workspace.isRustSelected { SyncRecoveryRow() }
            if let lastSyncedAt = staleLastSyncedAt {
                TimelineView(.periodic(from: .now, by: 60)) { _ in
                    valueRow(
                        "Last synced", systemImage: "clock",
                        value: lastSyncedAt.formatted(.relative(presentation: .named)))
                }
            }
            valueRow(
                "Waiting to sync", systemImage: "arrow.up.circle",
                value: Self.pendingDescription(workspace.pendingChangeCount))
            if let referenceID = failureReferenceID {
                LabeledContent {
                    Text(referenceID)
                        .font(.footnote.monospaced())
                        .textSelection(.enabled)
                } label: {
                    Label("Reference ID", systemImage: "number")
                }
            }
            syncNowButton
            if issueCount > 0 {
                syncIssuesLink
            }
        } header: {
            SettingsSectionHeader("Sync")
        }
        .listRowBackground(cardBackground)
    }

    /// "Status" with the sync state in words trailing ("Synced 2 minutes
    /// ago"), which also says when it last synced.
    private var syncStatusRow: some View {
        TimelineView(.periodic(from: .now, by: 30)) { context in
            let description = SyncStatusLabel.describe(workspace, now: context.date)
            LabeledContent {
                VStack(alignment: .trailing, spacing: 2) {
                    Text(description.text)
                        .carryOnFont(CarryOnTypeScale.meta)
                        .foregroundStyle(description.needsAttention ? BBColor.warningText : BBColor.textSecondary)
                    if let detail = description.detail {
                        Text(detail)
                            .font(BBFont.caption)
                            .foregroundStyle(BBColor.textTertiary)
                    }
                }
                .multilineTextAlignment(.trailing)
            } label: {
                Label {
                    Text("Status")
                } icon: {
                    Image(systemName: description.symbolName)
                        .foregroundStyle(description.needsAttention ? BBColor.warning : BBColor.brandText)
                }
            }
            .accessibilityElement(children: .combine)
        }
    }

    /// When it last synced, for the states whose status text doesn't say so
    /// (offline, failing); idle already reads "Synced 2 minutes ago".
    private var staleLastSyncedAt: Date? {
        switch workspace.syncStatus {
        case .offline(let date): return date
        case .failing(_, _, let date): return date
        case .localOnly, .idle, .syncing, .needsSignIn: return nil
        }
    }

    private func valueRow(_ title: String, systemImage: String, value: String) -> some View {
        LabeledContent {
            Text(value)
                .carryOnFont(CarryOnTypeScale.meta)
                .foregroundStyle(.coTextSecondary)
        } label: {
            Label(title, systemImage: systemImage)
        }
    }

    private var syncNowButton: some View {
        let reason = SyncStatusLabel.describe(workspace, now: Date()).syncNowDisabledReason
        return VStack(alignment: .leading, spacing: 2) {
            Button {
                Task { await workspace.syncNow() }
            } label: {
                HStack {
                    Label("Sync now", systemImage: "arrow.triangle.2.circlepath")
                    Spacer()
                    if isSyncing {
                        ProgressView()
                    }
                }
            }
            .disabled(isSyncing || reason != nil)
            if let reason {
                Text(reason).font(BBFont.caption).foregroundStyle(BBColor.textTertiary)
            }
        }
    }

    /// Open issues of whichever engine runs the workspace.
    private var issueCount: Int {
        workspace.isRustSelected ? workspace.runtimeIssues.count : workspace.issues.count
    }

    private var syncIssuesLink: some View {
        NavigationLink(value: AppRoute.syncIssues) {
            HStack {
                Label("Sync issues", systemImage: "exclamationmark.triangle")
                Spacer(minLength: BBSpacing.s2)
                Text(issueCount, format: .number)
                    .monospacedDigit()
                    .foregroundStyle(BBColor.textTertiary)
            }
            .accessibilityElement(children: .combine)
        }
    }

    private var isSyncing: Bool { workspace.syncStatus == .syncing }

    private var failureReferenceID: String? {
        if case .failing(_, let referenceID, _) = workspace.syncStatus { return referenceID }
        return nil
    }

    // MARK: About

    private var aboutSection: some View {
        Section {
            valueRow("Version", systemImage: "info.circle", value: Self.versionDescription)
            if let buildLabel = Self.buildLabel {
                valueRow("Build", systemImage: "hammer", value: buildLabel)
            }
            if diagnostics != nil {
                NavigationLink(value: AppRoute.performance) {
                    Label("Performance", systemImage: "gauge.with.dots.needle.33percent")
                }
            }
        } header: {
            SettingsSectionHeader("About")
        } footer: {
            Text(offlineExplanation)
                .carryOnFont(CarryOnTypeScale.meta)
                .foregroundStyle(.coTextSecondary)
        }
        .listRowBackground(cardBackground)
    }

    private var offlineExplanation: String {
        "Everything you do is saved on this \(ThisDevice.name) first, so capture, lists and search work without a connection. When you're signed in, changes sync as soon as you're back online."
    }

    // MARK: Actions

    // MARK: Formatting

    static func pendingDescription(_ count: Int) -> String {
        switch count {
        case 0: return "Nothing"
        case 1: return "1 change"
        default: return "\(count) changes"
        }
    }

    static func hostDescription(_ url: URL) -> String {
        guard let host = url.host(), !host.isEmpty else { return url.absoluteString }
        if let port = url.port { return "\(host):\(port)" }
        return host
    }

    static var versionDescription: String {
        let info = Bundle.main.infoDictionary
        let version = info?["CFBundleShortVersionString"] as? String ?? "Unknown"
        if let build = info?["CFBundleVersion"] as? String, build != version {
            return "\(version) (\(build))"
        }
        return version
    }

    /// "<branch> @ <commit>" on TestFlight builds (BB_BUILD_LABEL in
    /// project.yml); nil on local builds.
    static var buildLabel: String? {
        let label = Bundle.main.infoDictionary?["BBBuildLabel"] as? String
        guard let label, !label.isEmpty else { return nil }
        return label
    }
}

/// The signed-in account as one two-line row: the name (or email) over
/// "email · server", with an initials circle where other rows keep their icon.
private struct AccountIdentityRow: View {
    let name: String?
    let email: String
    let host: String

    @ScaledMetric(relativeTo: .body) private var avatar: CGFloat = 32

    private var displayName: String {
        name?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    }

    private var title: String { displayName.isEmpty ? email : displayName }

    private var subtitle: String { displayName.isEmpty ? host : "\(email) · \(host)" }

    private var initials: String {
        let words = displayName.split(whereSeparator: \.isWhitespace)
        if words.count >= 2, let first = words.first?.first, let last = words.last?.first {
            return String([first, last]).uppercased()
        }
        return title.first.map { String($0).uppercased() } ?? "?"
    }

    var body: some View {
        HStack(spacing: BBSpacing.s3) {
            Text(initials)
                .carryOnFont(CarryOnTypeScale.bodyStrong)
                .foregroundStyle(.coTextPrimary)
                .frame(width: avatar, height: avatar)
                .background(.coControlQuiet, in: Circle())
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .carryOnFont(CarryOnTypeScale.bodyStrong)
                    .foregroundStyle(.coTextPrimary)
                Text(subtitle)
                    .carryOnFont(CarryOnTypeScale.meta)
                    .foregroundStyle(.coTextSecondary)
            }
        }
        .accessibilityElement(children: .combine)
    }
}

/// A Carry On section header (board 25): meta-strong, secondary text, sentence case.
struct SettingsSectionHeader: View {
    let title: String

    init(_ title: String) {
        self.title = title
    }

    var body: some View {
        Text(title)
            .carryOnFont(CarryOnTypeScale.metaStrong)
            .foregroundStyle(.coTextSecondary)
            .textCase(nil)
    }
}

private struct SignInRequest: Identifiable {
    let id = UUID()
    let email: String
    let serverURL: URL?
}

/// "iPhone" or "iPad", for copy such as "stored on this iPhone".
enum ThisDevice {
    @MainActor static var name: String {
        UIDevice.current.userInterfaceIdiom == .pad ? "iPad" : "iPhone"
    }
}
