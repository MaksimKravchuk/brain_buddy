import BrainBuddyCore
import BrainBuddyDesign
import BrainBuddyWorkspace
import SwiftUI

/// Board 25: Sign out is the last thing on the Account screen, a full-width stone pill. Signing
/// out removes the account's tasks from this device, so it is always confirmed; with unsynced
/// changes the dialog says they would be lost. Moved here from Settings unchanged.
struct AccountSignOutSection: View {
    @Environment(Workspace.self) private var workspace
    @Environment(ToastCenter.self) private var toasts

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

    var body: some View {
        Section {
            signOutButton
                .listRowBackground(Color.clear)
                .listRowInsets(EdgeInsets())
        } footer: {
            Text("Signing out removes your tasks from this \(ThisDevice.name). They stay in your account.")
                .carryOnFont(CarryOnTypeScale.meta)
                .foregroundStyle(.coTextSecondary)
        }
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

    private var signOutButton: some View {
        Button(role: .destructive) {
            requestSignOut()
        } label: {
            HStack(spacing: CGFloat(CarryOnSpace.xs)) {
                Text("Sign out")
                if isSigningOut {
                    ProgressView()
                }
            }
            .frame(maxWidth: .infinity)
        }
        .buttonStyle(.carryOnSecondary)
        .disabled(isSigningOut)
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
}
