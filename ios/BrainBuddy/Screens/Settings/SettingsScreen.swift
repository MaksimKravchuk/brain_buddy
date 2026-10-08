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
        }
        .navigationTitle("Settings")
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
            if unsyncedCount > 0 {
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
                if let name = account.displayName, !name.isEmpty {
                    LabeledContent("Name", value: name)
                }
                LabeledContent("Email", value: account.email)
                LabeledContent("Server", value: Self.hostDescription(account.serverURL))
                Button("Manage account") { openAccount(account, deleting: false) }
                    .frame(minHeight: 44)
                Button("Delete account", role: .destructive) { openAccount(account, deleting: true) }
                    .frame(minHeight: 44)
                if accountLinkFailed {
                    Text("Couldn't open account settings. Use the account linked to this iPhone.")
                        .font(BBFont.secondary)
                    Button("Retry account links") { Task { await loadAccountOrigin() } }.frame(minHeight: 44)
                }
                if workspace.syncStatus == .needsSignIn {
                    Button("Sign in again") {
                        signInRequest = SignInRequest(email: account.email, serverURL: account.serverURL)
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
                Text(localOnlyExplanation)
                Button("Sign in") {
                    signInRequest = SignInRequest(email: "", serverURL: nil)
                }
            } header: {
                Text("Account")
            }
        }
    }

    private var signOutButton: some View {
        Button(role: .destructive) {
            requestSignOut()
        } label: {
            HStack {
                Text("Sign out")
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
        guard unsyncedCount > 0 else {
            return "Your tasks are removed from this \(ThisDevice.name). They stay in your account."
        }
        let pronoun = unsyncedCount == 1 ? "it" : "them"
        return "Sign out and remove \(pronoun) from this \(ThisDevice.name)?"
    }

    // MARK: Sync

    private var syncSection: some View {
        Section {
            SyncStatusLabel()
            LabeledContent("Waiting to sync", value: Self.pendingDescription(workspace.pendingChangeCount))
            if let lastSyncedAt {
                TimelineView(.periodic(from: .now, by: 60)) { _ in
                    LabeledContent("Last synced", value: lastSyncedAt.formatted(.relative(presentation: .named)))
                }
            }
            if let referenceID = failureReferenceID {
                LabeledContent("Reference ID") {
                    Text(referenceID)
                        .font(.footnote.monospaced())
                        .textSelection(.enabled)
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

    private var lastSyncedAt: Date? {
        switch workspace.syncStatus {
        case .idle(let date), .offline(let date): return date
        case .failing(_, _, let date): return date
        case .localOnly, .syncing, .needsSignIn: return nil
        }
    }

    private var failureReferenceID: String? {
        if case .failing(_, let referenceID, _) = workspace.syncStatus { return referenceID }
        return nil
    }

    // MARK: About

    private var aboutSection: some View {
        Section {
            LabeledContent("Version", value: Self.versionDescription)
            if let buildLabel = Self.buildLabel {
                LabeledContent("Build", value: buildLabel)
            }
            VStack(alignment: .leading, spacing: BBSpacing.s1) {
                Text("Works offline")
                Text(offlineExplanation)
                    .font(BBFont.meta)
                    .foregroundStyle(BBColor.textTertiary)
            }
            .accessibilityElement(children: .combine)
        } header: {
            Text("About")
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
        unsyncedChanges = workspace.pendingChanges
        unsyncedCount = unsyncedChanges.count
        isConfirmingSignOut = true
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
                if case .unsyncedChanges(let count) = error {
                    // Changes arrived after the check; ask again with the real count.
                    unsyncedCount = count
                    unsyncedChanges = workspace.pendingChanges
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
