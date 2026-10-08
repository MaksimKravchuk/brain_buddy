import BrainBuddyCore
import BrainBuddyWorkspace
import Foundation
import Observation

/// Design X-04's words beyond the copy catalogue.
package enum SignOutCopy {
    package static let cancel = "Cancel"
    package static let signOut = "Sign out"
    package static let signOutAndRemove = "Sign out and remove"
    package static let failedTitle = "Couldn't sign out"
    package static let failedDetail =
        "Brain Buddy couldn't remove your tasks from this Mac, so you're still signed in. Nothing was removed."
    package static let ok = "OK"
}

/// X-04 "error": nothing was removed, so the person is still signed in (no reference id: local).
package struct SignOutFailure: Equatable, Sendable {
    package var title = SignOutCopy.failedTitle
    package var detail = SignOutCopy.failedDetail

    package init() {}
}

/// The unsaved-edit guard of "Sign out…" (design X-04 "unsaved edit or capture draft"; review c2,
/// G28): the window's existing discard confirmation comes first whenever a task edit is unsaved or
/// the capture draft is not empty, so nothing typed is lost without the person choosing to.
package enum SignOutGuard {
    package static func needsDiscardConfirmation(taskEditUnsaved: Bool, captureDraft: String, waitingForDraft: String) -> Bool {
        taskEditUnsaved || !captureDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            || !waitingForDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
}

/// X-04's logic (contracts/mac-app-host.md §7, design X-04), with no view.
///
/// The order and the failure contract are the kit's (kit-commands §4 "Sign-out order"): the engine
/// records the session as a pending logout before anything is removed, removes the token and logs
/// out only after the local removal succeeded, and on a failure withdraws the pending logout and
/// resumes: the person is still signed in, as "Couldn't sign out" says. This flow adds the Mac's
/// rules around it: the count shown is the count removed, the backup sentence, and what follows a
/// sign-out (data-model E8).
@MainActor
@Observable
package final class SignOutFlow {
    /// What X-04 says, captured when it opened; confirming compares it with what holds then.
    package struct Prompt: Equatable, Sendable {
        package var unsent: Int
        package var issues: Int
        package var offline: Bool
        package var sessionEnded: Bool
        package var backup: SignOutBackupNote?
        package var text: SyncCopyText
        /// "Sign out and remove" when changes would be removed, else "Sign out".
        package var confirmTitle: String
        /// The unsent changes it names, by identity: confirming removes these and no others.
        package var changes: Set<PendingChange>
        package var removesUnsent: Bool { unsent > 0 }
    }

    package enum Outcome: Equatable, Sendable {
        case signedOut
        /// The count changed (or the kit refused a plain sign-out): nothing was signed out, and X-04
        /// shows again with the new count.
        case changed
        /// The local removal failed: nothing was removed, still signed in.
        case failed
    }

    package private(set) var prompt: Prompt?
    /// "Couldn't sign out", until dismissed.
    package private(set) var failure: SignOutFailure?
    /// Times X-04 was shown (re-presentations included).
    package private(set) var presentations = 0
    package private(set) var isSigningOut = false

    @ObservationIgnored private let workspace: Workspace
    @ObservationIgnored private let importer: LegacyImportCoordinator?
    @ObservationIgnored private let now: @Sendable () -> Date
    @ObservationIgnored private let calendar: Calendar
    @ObservationIgnored private let log: any MacLogSink
    /// After a sign-out: selection to Inbox, drafts cleared (the window's part).
    @ObservationIgnored package var didSignOut: (@MainActor () -> Void)?

    package init(
        workspace: Workspace, importer: LegacyImportCoordinator?, now: @escaping @Sendable () -> Date = { Date() },
        calendar: Calendar = .current, log: any MacLogSink = SystemMacLog()
    ) {
        self.workspace = workspace
        self.importer = importer
        self.now = now
        self.calendar = calendar
        self.log = log
    }

    /// X-04 as it reads now.
    package func currentPrompt() -> Prompt {
        let snapshot = workspace.syncSnapshot
        let unsent = workspace.pendingChangeCount
        let issues = workspace.issues.count
        let backup = backupNote(initialUploadRemaining: snapshot.initialUploadRemaining)
        let text = SyncCopy.signOutConfirmation(
            unsent: unsent, offline: !snapshot.isOnline, sessionEnded: snapshot.sessionEnded, issues: issues,
            backup: backup, device: .mac, now: now(), calendar: calendar
        )
        return Prompt(
            unsent: unsent, issues: issues, offline: !snapshot.isOnline, sessionEnded: snapshot.sessionEnded,
            backup: backup, text: text, confirmTitle: unsent > 0 ? SignOutCopy.signOutAndRemove : SignOutCopy.signOut,
            changes: workspace.pendingChanges
        )
    }

    /// Opens X-04 (after the unsaved-edit guard).
    @discardableResult
    package func open() -> Prompt {
        let prompt = currentPrompt()
        self.prompt = prompt
        failure = nil
        presentations += 1
        return prompt
    }

    /// Cancel (the default) or Esc.
    package func cancel() {
        prompt = nil
    }

    /// "Sign out" or "Sign out and remove". Removes only what the dialog named: when the count of
    /// unsent changes or open issues differs from it, or the kit finds a change it did not name (by
    /// id and content, so also one queued in place of an acknowledged one or an edit folded into a
    /// named one), nothing is signed out and X-04 opens again with the new count.
    @discardableResult
    package func confirm() async -> Outcome {
        guard !isSigningOut else { return .changed }
        guard let shown = prompt else {
            open()
            return .changed
        }
        let current = currentPrompt()
        if current.unsent != shown.unsent || current.issues != shown.issues {
            log.log(.sync, "sign-out re-presented reason=countChanged")
            open()
            return .changed
        }
        isSigningOut = true
        defer { isSigningOut = false }
        let initialUpload = workspace.syncSnapshot.initialUploadRemaining
        do {
            try await workspace.signOut(removing: shown.changes)
        } catch WorkspaceError.unsyncedChanges {
            log.log(.sync, "sign-out re-presented reason=unsyncedChanges")
            open()
            return .changed
        } catch {
            log.log(.sync, "sign-out failed class=\(String(describing: type(of: error)))")
            prompt = nil
            failure = SignOutFailure()
            return .failed
        }
        prompt = nil
        // Data-model E7.1 and E8: the sign-out is recorded, the backup goes when it is due, staging
        // files go. Best effort: a sidecar that can't be written now is caught up at the next launch.
        var backupRemoved = false
        if let importer {
            do {
                backupRemoved = try importer.didSignOut(initialUploadRemaining: initialUpload)
            } catch {
                log.log(.sync, "sign-out retention check failed class=\(String(describing: type(of: error)))")
            }
        }
        log.log(.sync, "sign-out done removedChanges=\(shown.unsent) backupRemoved=\(backupRemoved)")
        didSignOut?()
        return .signedOut
    }

    /// "OK" on "Couldn't sign out".
    package func dismissFailure() { failure = nil }

    /// `signOutBackup` while the backup stays after this sign-out, `signOutBackupRemoved` when this
    /// sign-out deletes it (data-model E8), nil without a backup.
    private func backupNote(initialUploadRemaining: Int) -> SignOutBackupNote? {
        guard let importer, let backup = importer.backup() else { return nil }
        if importer.backupWillBeRemovedAtSignOut(initialUploadRemaining: initialUploadRemaining) { return .removed }
        return .kept(until: backup.keptUntil)
    }
}
