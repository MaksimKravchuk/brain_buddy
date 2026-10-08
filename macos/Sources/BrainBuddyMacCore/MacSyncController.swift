import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyWorkspace
import Foundation
import Observation

/// The app menu's account items (design X-07): "Sign in…" account-less, "Sign out…" signed in,
/// "Sign in again…" and "Sign out…" once the session ended.
package struct AccountMenuItems: Equatable, Sendable {
    package var signIn: Bool
    package var signInAgain: Bool
    package var signOut: Bool

    package init(signIn: Bool, signInAgain: Bool, signOut: Bool) {
        self.signIn = signIn
        self.signInAgain = signInAgain
        self.signOut = signOut
    }

    /// No window: no account item.
    package static let hidden = AccountMenuItems(signIn: false, signInAgain: false, signOut: false)

    package static let signInTitle = "Sign in…"
    package static let signInAgainTitle = "Sign in again…"
    package static let signOutTitle = "Sign out…"
    package static let syncNowTitle = "Sync now"
}

/// The Mac's sync UI over one workspace, with no view (PR-09): X-01's line, X-02's content, X-03
/// and X-04's flows, X-07's menu state, all presenting through `MacPresentationRouter`. The views
/// in the app target only lay these out.
@MainActor
@Observable
package final class MacSyncController {
    package let host: WorkspaceHost
    package let router: MacPresentationRouter
    package let signOut: SignOutFlow
    package private(set) var signIn: SignInFlow?
    package private(set) var line: SyncStatusLineModel
    package private(set) var discards = OutcomeDiscards()
    /// Bumped by "Sign out…" (X-02, X-07): the window runs its unsaved-edit guard, then
    /// `presentSignOut()`.
    package private(set) var signOutRequests = 0
    @ObservationIgnored package var triggers: SyncTriggerSource?

    @ObservationIgnored private let now: @Sendable () -> Date
    @ObservationIgnored private let calendar: Calendar
    @ObservationIgnored private let log: any MacLogSink
    @ObservationIgnored private let defaultServer: @MainActor () -> URL

    package init(
        host: WorkspaceHost, router: MacPresentationRouter = MacPresentationRouter(),
        now: @escaping @Sendable () -> Date = { Date() }, calendar: Calendar = .current, log: any MacLogSink = SystemMacLog(),
        defaultServer: @escaping @MainActor () -> URL = { MacHostConfiguration.knownServers().first ?? BrainBuddyAPI.defaultServerURL }
    ) {
        self.host = host
        self.router = router
        self.now = now
        self.calendar = calendar
        self.log = log
        self.defaultServer = defaultServer
        signOut = SignOutFlow(workspace: host.workspace, importer: host.importer, now: now, calendar: calendar, log: log)
        line = SyncStatusLineModel(snapshot: host.workspace.syncSnapshot, now: now(), device: .mac, calendar: calendar)
    }

    package var workspace: Workspace { host.workspace }

    // MARK: X-01

    /// A snapshot change: describe again.
    package func observeSnapshot() {
        line.update(workspace.syncSnapshot, at: now())
    }

    /// The line's timer.
    package func refreshLine() {
        line.update(workspace.syncSnapshot, at: now())
    }

    /// The polite announcement to post, once.
    package func takeAnnouncement() -> String? { line.takeAnnouncement() }

    /// X-01's trailing action, by the description's action.
    package func performTrailingAction() async {
        switch line.description.action {
        case .signIn: beginSignIn(from: .statusLineAction)
        case .retry: await syncNow()
        case .signInAgain, .showIssues, .none: router.handle(.openSyncDetails(from: .statusWords))
        }
    }

    /// Design X-01 "first load, empty list": signed in and "Not synced yet", an empty list reads
    /// "Your tasks are still arriving." instead of its celebratory empty copy.
    package var tasksStillArriving: Bool {
        workspace.account != nil && line.description.state == .notSyncedYet
    }

    // MARK: X-02

    package func popoverContent() -> SyncPopoverContent {
        SyncPopoverModel.content(
            snapshot: workspace.syncSnapshot, issues: workspace.issues, state: workspace.state,
            files: host.importer.upgradeFiles(), discarded: discards.ids, now: now(), device: .mac, calendar: calendar
        )
    }

    /// "Dismiss" on an issue: it goes, and focus moves as the design says.
    package func dismissIssue(_ id: SyncIssue.ID) {
        let focus = popoverContent().focusAfterRemoving(id)
        workspace.dismissIssue(id)
        if let focus { router.handle(.focusInside(.inPopover(focus))) }
    }

    /// "Discard outcome": "Outcome discarded · Undo" for 5 s; focus stays on the row's Undo.
    package func discardOutcome(_ id: SyncIssue.ID) {
        discards.discard(id, at: now())
        router.handle(.focusInside(.inPopover(.undoDiscard(id))))
    }

    package func undoDiscard(_ id: SyncIssue.ID) {
        discards.undo(id)
        router.handle(.focusInside(.inPopover(.copyOutcome(id))))
    }

    /// The discards whose 5 s are over go for good.
    package func commitExpiredDiscards() {
        for id in discards.expired(at: now()) { workspace.dismissIssue(id) }
    }

    /// X-02 closed (Esc, click outside): what was discarded goes for good, since Undo is gone.
    package func closeSyncDetails() {
        for id in discards.all() { workspace.dismissIssue(id) }
        router.handle(.closeSyncDetails)
    }

    // MARK: X-03

    /// An X-03 flow is open: its sheet is shown, or its one request is on its way. The app menu's
    /// "Sign in…" and "Sign in again…" are disabled meanwhile.
    package var isSignInOpen: Bool {
        guard let signIn else { return false }
        return signIn.isSigningIn || router.signInRequest != nil
    }

    /// "Sign in to sync", "Sign in…" or "Sign in again": the sheet, locked to the linked account when
    /// one is linked (its session ended). Single-flight: while a flow is open it stays, with what was
    /// typed and the request on its way, and no second flow (or second login) starts.
    package func beginSignIn(from entry: SignInEntry) {
        guard !isSignInOpen else {
            log.log(.sync, "sign-in already open")
            return
        }
        let workspace = self.workspace
        let account = workspace.account
        let mode: SignInFlow.Mode = account.map { .signInAgain(email: $0.email, serverURL: $0.serverURL) } ?? .signIn
        signIn = SignInFlow(
            mode: mode, hasLocalTasks: account == nil && workspace.pendingChangeCount > 0, defaultServer: defaultServer(),
            isOnline: { workspace.syncSnapshot.isOnline },
            signIn: { url, email, password, cancellation in
                try await workspace.signIn(serverURL: url, email: email, password: password, cancellation: cancellation)
            },
            deletionCancelled: { workspace.signInCancelledAccountDeletion },
            acknowledgeDeletion: { workspace.acknowledgeAccountDeletionNotice() }, log: log
        )
        router.handle(account == nil ? .signIn(from: entry) : .signInAgain(from: entry))
    }

    /// The sheet closed: signed in, or cancelled.
    package func closeSignIn() {
        guard let flow = signIn else { return }
        if flow.phase == .signingIn { flow.cancel() }
        // Linked, its first sync still running (a Cancel the kit refused): signed in all the same.
        let signedIn = flow.phase == .finished || flow.phase == .finishing
        signIn = nil
        observeSnapshot()
        triggers?.accountLinkChanged()
        router.handle(
            .closeSignIn(
                SignInClose(outcome: signedIn ? .signedIn : .cancelled, trailingActionShown: line.description.trailingActionTitle != nil)
            )
        )
    }

    // MARK: X-04

    /// "Sign out…" from X-02 or the app menu: the window's unsaved-edit guard runs first.
    package func requestSignOut() {
        if case .syncDetails = router.surface { closeSyncDetails() }
        signOutRequests += 1
    }

    /// After the guard: X-04 with what holds now.
    package func presentSignOut() {
        signOut.open()
        router.handle(.signOut)
    }

    package func cancelSignOut() {
        signOut.cancel()
        router.handle(.closeSignOut)
    }

    /// "Sign out" or "Sign out and remove".
    @discardableResult
    package func confirmSignOut() async -> SignOutFlow.Outcome {
        let outcome = await signOut.confirm()
        switch outcome {
        case .changed:
            // The same alert again, with the new count, focus on Cancel.
            router.handle(.signOut)
        case .signedOut, .failed:
            router.handle(.closeSignOut)
        }
        observeSnapshot()
        triggers?.accountLinkChanged()
        return outcome
    }

    // MARK: X-07

    /// File › "Sync now" follows `syncNowEnabled`: disabled only account-less, offline or with the
    /// session ended; never because a sync runs (single-flight).
    package var syncNowEnabled: Bool { SyncPopoverModel.syncNowAvailable(line.snapshot, line.description) }

    package var accountMenu: AccountMenuItems {
        let linked = workspace.account != nil
        let ended = line.description.state == .sessionEnded
        return AccountMenuItems(signIn: !linked, signInAgain: linked && ended, signOut: linked)
    }

    /// File › "Sync now" ⌘R, X-02 "Sync now", X-01 "Retry".
    package func syncNow() async {
        guard syncNowEnabled else { return }
        if let triggers { await triggers.syncNowRequested() } else { await workspace.syncNow() }
    }
}
