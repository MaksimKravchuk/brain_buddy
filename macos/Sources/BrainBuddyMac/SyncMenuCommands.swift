import BrainBuddyMacCore
import SwiftUI

/// Design X-07 (contracts/mac-app-host.md §6): File › "Sync now" ⌘R, enabled whenever a sync can
/// run (also while one runs, and as the retry while failing; a press during a sync joins it or
/// queues one follow-up), disabled, never hidden, account-less, offline or with the session ended;
/// ⌘R works anywhere in the main window, also while typing, and opens no popover. The app menu
/// offers "Sign in…", or "Sign out…" signed in, and "Sign in again…" too once the session ended.
/// Menu items we own use sentence case.
struct SyncMenuCommands: Commands {
    @FocusedValue(\.macSyncController) private var controller

    var body: some Commands {
        CommandGroup(after: .newItem) {
            Button(AccountMenuItems.syncNowTitle) {
                if let controller { Task { await controller.syncNow() } }
            }
            .keyboardShortcut("r", modifiers: [.command])
            .disabled(!(controller?.syncNowEnabled ?? false))
        }
        CommandGroup(after: .appInfo) {
            let items = controller?.accountMenu ?? AccountMenuItems.hidden
            Divider()
            if items.signIn {
                Button(AccountMenuItems.signInTitle) { controller?.beginSignIn(from: .menu) }
            }
            if items.signInAgain {
                Button(AccountMenuItems.signInAgainTitle) { controller?.beginSignIn(from: .menu) }
            }
            if items.signOut {
                Button(AccountMenuItems.signOutTitle) { controller?.requestSignOut() }
            }
        }
    }
}

private struct MacSyncControllerKey: FocusedValueKey {
    typealias Value = MacSyncController
}

extension FocusedValues {
    /// The main window's sync controller, for `SyncMenuCommands`.
    var macSyncController: MacSyncController? {
        get { self[MacSyncControllerKey.self] }
        set { self[MacSyncControllerKey.self] = newValue }
    }
}
