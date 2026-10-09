import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI
import UIKit

/// Account, sync, the weekly review's threshold and about. Everything here
/// reads the workspace; the only network actions are signing in and out and
/// "Sync now".
struct SettingsScreen: View {
    @Environment(Workspace.self) private var workspace
    @Environment(ToastCenter.self) private var toasts
    @Environment(\.openURL) private var openURL

    @State private var signInRequest: SignInRequest?
    @State private var isConfirmingSignOut = false
    @State private var unsyncedCount = 0
    /// Open sync issues the confirmation names on their own (FR-018): they are removed too.
    @State private var unsyncedIssueCount = 0
    /// Unsaved weekly-review drafts the confirmation names (FR-018): sign-out removes them too, but
    /// they neither change the buttons nor count as unsent changes.
    @State private var unsavedDraftCount = 0
    /// The unsent changes the confirmation names: "Sign out and remove" removes these and no others.
    @State private var unsyncedChanges: Set<PendingChange> = []
    @State private var isSigningOut = false
    @State private var accountOrigin: String?
    @State private var accountLinkFailed = false

    init() {}

    var body: some View {
        List {
            accountSection
            if workspace.account != nil {
                syncSection
            } else if !workspace.issues.isEmpty {
                Section { syncIssuesLink }
            }
            // Weekly review (spec 020, M-23); shown only while it is exposed.
            ReviewSettingsSection()
            aboutSection
            deleteAccountSection
        }
        .labelStyle(.bbRow)
        .bbDenseList()
        .bbScreenTitle("Settings")
        .task(id: workspace.account?.serverURL) { await loadAccountOrigin() }
        .sheet(item: $signInRequest) { request in
            SignInSheet(email: request.email, serverURL: request.serverURL)
        }
        // Signing out removes the account's tasks from this device, so it is
        // always confirmed; with unsynced changes the dialog says they'd be lost.
        .confirmationDialog(
            signOutTitle,
            isPresented: $isConfirmingSignOut,
            titleVisibility: .visible
        ) {
            if unsyncedCount > 0 || unsyncedIssueCount > 0 {
                Button("Sign out and remove", role: .destructive) { signOut(removing: unsyncedChanges) }
            } else {
                Button("Sign out", role: .destructive) { signOut(removing: []) }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text(signOutMessage)
        }
    }

    // MARK: Account

    @ViewBuilder private var accountSection: some View {
        if let account = workspace.account {
            Section {
                AccountIdentityRow(
                    name: account.displayName, email: account.email,
                    host: Self.hostDescription(account.serverURL))
                Button {
                    openAccount(account, deleting: false)
                } label: {
                    Label("Manage account", systemImage: "person.crop.circle")
                }
                if accountLinkFailed {
                    Label {
                        Text("Couldn't open account settings. Use the account linked to this iPhone.")
                            .font(BBFont.secondary)
                    } icon: {
                        Image(systemName: "exclamationmark.circle")
                            .foregroundStyle(BBColor.warningText)
                    }
                    Button {
                        Task { await loadAccountOrigin() }
                    } label: {
                        Label("Retry account links", systemImage: "arrow.clockwise")
                    }
                }
                if workspace.syncStatus == .needsSignIn {
                    Button {
                        signInRequest = SignInRequest(email: account.email, serverURL: account.serverURL)
                    } label: {
                        Label("Sign in again", systemImage: "person.crop.circle.badge.exclamationmark")
                    }
                }
                signOutButton
            } header: {
                Text("Account")
            } footer: {
                Text(signedInFooter)
            }
        } else {
            Section {
                Button {
                    signInRequest = SignInRequest(email: "", serverURL: nil)
                } label: {
                    Label("Sign in", systemImage: "person.crop.circle.badge.plus")
                }
            } header: {
                Text("Account")
            } footer: {
                Text(localOnlyExplanation)
            }
        }
    }

    /// Deleting the account is always available when signed in (GDPR), in a
    /// section of its own at the bottom so it is never next to a routine row.
    @ViewBuilder private var deleteAccountSection: some View {
        if let account = workspace.account {
            Section {
                Button(role: .destructive) {
                    openAccount(account, deleting: true)
                } label: {
                    destructiveLabel("Delete account", systemImage: "trash")
                }
            }
        }
    }

    /// A row label whose icon is red like its text, not the brand colour that
    /// `.bbRow` gives every other icon.
    private func destructiveLabel(_ title: String, systemImage: String) -> some View {
        Label {
            Text(title)
        } icon: {
            Image(systemName: systemImage)
                .foregroundStyle(Color.red)
        }
    }

    private var signOutButton: some View {
        Button(role: .destructive) {
            requestSignOut()
        } label: {
            HStack {
                destructiveLabel("Sign out", systemImage: "rectangle.portrait.and.arrow.right")
                if isSigningOut {
                    Spacer()
                    ProgressView()
                }
            }
        }
        .disabled(isSigningOut)
    }

    private var localOnlyExplanation: String {
        "Your tasks are stored on this \(ThisDevice.name). Sign in to sync with Brain Buddy on the web."
    }

    private var signedInFooter: String {
        "Signing out removes your tasks from this \(ThisDevice.name). They stay in your account."
    }

    private var signOutTitle: String {
        unsyncedCount > 0 ? WorkspaceError.unsyncedChanges(count: unsyncedCount).message : "Sign out?"
    }

    private var signOutMessage: String {
        var sentences: [String]
        if unsyncedCount > 0 {
            let pronoun = unsyncedCount == 1 ? "it" : "them"
            sentences = ["Sign out and remove \(pronoun) from this \(ThisDevice.name)?"]
        } else {
            sentences = ["Your tasks are removed from this \(ThisDevice.name). They stay in your account."]
        }
        if unsyncedIssueCount > 0 {
            sentences.append(
                "\(SyncCopy.changes(unsyncedIssueCount)) that couldn't sync will also be removed from this \(ThisDevice.name).")
        }
        if unsavedDraftCount > 0 {
            sentences.append(
                "\(SyncCopy.reviewDrafts(unsavedDraftCount)) will also be removed from this \(ThisDevice.name).")
        }
        return sentences.joined(separator: " ")
    }

    // MARK: Sync

    private var syncSection: some View {
        Section {
            syncStatusRow
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
            if !workspace.issues.isEmpty {
                syncIssuesLink
            }
        } header: {
            Text("Sync")
        }
    }

    /// "Status" with the sync state in words trailing ("Synced 2 minutes
    /// ago"), which also says when it last synced.
    private var syncStatusRow: some View {
        TimelineView(.periodic(from: .now, by: 30)) { context in
            let description = SyncStatusLabel.describe(
                workspace.syncStatus,
                pendingChanges: workspace.pendingChangeCount,
                now: context.date,
                deviceName: SyncStatusLabel.deviceName
            )
            LabeledContent {
                Text(description.text)
                    .foregroundStyle(description.needsAttention ? BBColor.warningText : BBColor.textTertiary)
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
        } label: {
            Label(title, systemImage: systemImage)
        }
    }

    private var syncNowButton: some View {
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
        .disabled(isSyncing)
    }

    private var syncIssuesLink: some View {
        NavigationLink(value: AppRoute.syncIssues) {
            HStack {
                Label("Sync issues", systemImage: "exclamationmark.triangle")
                Spacer(minLength: BBSpacing.s2)
                Text(workspace.issues.count, format: .number)
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
        } header: {
            Text("About")
        } footer: {
            Text(offlineExplanation)
        }
    }

    private var offlineExplanation: String {
        "Everything you do is saved on this \(ThisDevice.name) first, so capture, lists and search work without a connection. When you're signed in, changes sync as soon as you're back online."
    }

    // MARK: Actions

    private func loadAccountOrigin() async {
        accountOrigin = nil
        guard let account = workspace.account else { return }
        let ownerID = account.id
        let api = BrainBuddyAPIClient(baseURL: account.serverURL, tokenStore: InMemorySessionTokenStore())
        do {
            let methods = try await api.authMethods()
            guard workspace.account?.id == ownerID, workspace.account?.serverURL == account.serverURL,
                !Task.isCancelled else { return }
            accountOrigin = methods.webAccountOrigin
            accountLinkFailed = methods.webAccountOrigin.flatMap {
                NativeAccountDestination.url(origin: $0, ownerID: ownerID, deleting: false)
            } == nil
        } catch {
            if workspace.account?.id == ownerID, !Task.isCancelled { accountLinkFailed = true }
        }
    }

    private func openAccount(_ account: LinkedAccount, deleting: Bool) {
        guard workspace.account?.id == account.id, workspace.account?.serverURL == account.serverURL,
            let origin = accountOrigin,
            let url = NativeAccountDestination.url(origin: origin, ownerID: account.id, deleting: deleting)
        else { accountLinkFailed = true; return }
        // Browser authentication stays separate. No native session is copied,
        // and opening/cancelling this destination changes no local records.
        openURL(url) { accepted in accountLinkFailed = !accepted }
    }

    /// Always asks first. Without unsynced changes (or sync issues, which
    /// would be removed too) a plain sign-out is confirmed; if changes arrive
    /// meanwhile, `signOut` asks again with the real count.
    private func requestSignOut() {
        captureUnsynced()
        isConfirmingSignOut = true
    }

    /// What the confirmation names: unsent changes and open sync issues, counted apart (FR-018),
    /// and the exact set "Sign out and remove" may remove.
    private func captureUnsynced() {
        unsyncedChanges = workspace.pendingChanges
        unsyncedCount = workspace.pendingChangeCount
        unsyncedIssueCount = workspace.issues.count
        unsavedDraftCount = workspace.unsavedReviewDraftCount
    }

    private func signOut(removing changes: Set<PendingChange>) {
        guard !isSigningOut else { return }
        isSigningOut = true
        Task {
            do {
                try await workspace.signOut(removing: changes)
                isSigningOut = false
                // Recent searches can hold words from the account's tasks.
                UserDefaults.standard.removeObject(forKey: RecentSearches.storageKey)
                toasts.show("Signed out", actionTitle: nil, action: nil)
            } catch let error as WorkspaceError {
                isSigningOut = false
                if case .unsyncedChanges = error {
                    // Changes or issues arrived after the check; ask again with the real counts.
                    captureUnsynced()
                    isConfirmingSignOut = true
                } else {
                    toasts.show("\(error.message)", actionTitle: nil, action: nil)
                }
            } catch {
                isSigningOut = false
                toasts.show("Couldn't sign out. Try again.", actionTitle: nil, action: nil)
            }
        }
    }

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
                .font(.footnote.weight(.semibold))
                .foregroundStyle(BBColor.brandText)
                .frame(width: avatar, height: avatar)
                .background(BBColor.brandSoft, in: Circle())
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.body.weight(.medium))
                Text(subtitle)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
        .accessibilityElement(children: .combine)
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
