# Brain Buddy for Mac (native app)

The Mac app in `macos/` is a SwiftUI app for macOS 26 (Swift 6.2, Swift 6 language mode). Since
spec 021 it is a client of the shared `BrainBuddyKit` package in `ios/BrainBuddyKit`, like the
iPhone app: the GTD rules (`GTDReducer`), the queries, Smart Add, the store file and the sync
engine are the kit's, so the two apps cannot drift. The Mac re-implements no rule. This page is
the Mac's counterpart of `docs/native-ios-app.md`; the runbook (build, test, dry run) is
`macos/README.md`, and the contracts are in `specs/021-mac-sync/contracts/` (`mac-app-host.md`
above all).

## How the app is put together

| part | where | what it does |
|---|---|---|
| `BrainBuddyMacCore` | `macos/Sources/BrainBuddyMacCore/` | Foundation only, so it builds and tests outside the app: the one-time import of the pre-021 store, `mac-local.json`, the single-instance lock, `WorkspaceHost` and the launch (`MacLaunch`), the window's model, and the sync UI's logic (`SyncStatusLineModel`, `SyncPopoverModel`, `SignInFlow`, `SignOutFlow`, `SyncTriggerSource`, `MacPresentationRouter`, `MacSyncController`) |
| `BrainBuddyMac` | `macos/Sources/BrainBuddyMac/` | the SwiftUI and AppKit views that lay that logic out, the menus, `NWPathMonitor`, the App Nap activity, and WhisperKit inside the `VoiceTranscriber` actor |
| the kit | `ios/BrainBuddyKit` | `Workspace`, `SyncEngine`, `FileDocumentStore`, `KeychainSessionTokenStore`, the status describer and its copy |

Launch order (contracts/mac-app-host.md §1): the single-instance lock; the legacy import with its
one-time notices; the pre-021 cookie and cache cleanup; `WorkspaceHost` (the kit `Workspace` over
`store.json`, a `SyncEngine` with the Mac's Keychain service, client identity and 30 s pull age);
`workspace.load()`; then the sync triggers start (`SyncTriggerSource`).

**One presenter.** Sync never interrupts. `MacPresentationRouter` is the only type that shows a
sheet, alert or popover or moves keyboard focus, and it takes only what the person did (a click, a
menu item, a shortcut, a launch notice), never a sync state. `MacPresentationGuardTests` reads the
app's sources and fails if a presentation or a focus move appears anywhere else, outside an
explicit allow-list of person-started surfaces (FR-017, SC-004).

## Files and their lifetimes

Everything lives in `~/Library/Application Support/BrainBuddyMac/` (0700), or in the folder
`BRAINBUDDY_MAC_DATA_DIR` names during a dry run. `docs/data-retention.md` has a row for each.

| file | lifetime |
|---|---|
| `store.json` (+ `.store.json.lock`) | the workspace: until sign-out deletes it; kept through a 401 ("Sign in again to sync"); account-less, until the person removes the folder |
| `store.unreadable-<UTC>.json` | a workspace file that could not be read, set aside after "Start fresh"; until sign-out |
| `store.import-<attemptID>.json` | only during the one-time import |
| `mac-local.json` (+ lock) | review marks, the import record, the sidebar's disclosure; kept across sign-out |
| `local-gtd.backup-<UTC>.json`, `local-gtd.import-report-<UTC>.txt` | the pre-upgrade store and its report: at least 30 days, and deleted only after a sign-out since the update (data-model E8) |
| `.instance.lock` | one running copy per folder |

The 021 transport is ephemeral: no cookie jar, no HTTP cache.

## Signing in, the session token and the login keychain

Sign-in happens only in the sign-in sheet (design X-03). The kit stores the session token in the
person's **login keychain**, a generic password with service `app.brainbuddy.mac.session` and the
server's host as account; pending logouts are kept under `app.brainbuddy.mac.session.pending-logout`
until they reach the server. The token is never written to a file or logged.

- **Not synchronizable.** The item is created with `kSecAttrSynchronizable = false`: it never goes
  to iCloud Keychain. No `kSecAttrAccessible` is set on macOS: the login keychain cannot deliver
  "this device only", so the store does not claim it.
- **Carried by Time Machine and Migration Assistant.** Unlike the iPhone's item, the login
  keychain is part of a Time Machine backup and moves with Migration Assistant, so a restored or
  migrated Mac can still hold the token. It stops working when its server session ends (30 days,
  sign-out elsewhere, account deletion), and a launch with no linked account removes any token
  left over.
- **Deleting the app does not remove it**: the login keychain belongs to the person. The next
  install's first launch with no linked account removes it.
- **No prompt during routine sync.** Every read by the sync engine and the launch cleanup is
  non-interactive: an item this build may not read gives "Sign in again to sync", never a system
  prompt. Every Keychain call runs on the engine actor, off the main actor. Only a sign-in the
  person started may let macOS ask for access.
- **A write that fails at sign-in** shows "Brain Buddy couldn't save your sign-in on this Mac. Try
  again." with a reference id; the session the server just opened is ended at once.

### "Sign in again" after a rebuild

An ad-hoc signed build (`build_app.sh`) is a new client of the Keychain item each time it is
rebuilt. The rebuilt app cannot read the saved token without asking, so routine sync stops and the
footer reads **"Sign in again to sync"**; nothing is lost, and changes wait on the Mac. Choose
"Sign in again" (the email and server are locked to the account): macOS may ask whether the app may
use the saved sign-in. Allow it, or choose "Deny": the sheet then deletes the old item and adds a
new one.

If macOS refuses that too, the sheet shows "couldn't save sign-in". Open **Keychain Access**,
search for `app.brainbuddy.mac.session`, delete that item (and any
`app.brainbuddy.mac.session.pending-logout` items you no longer need), and sign in again.

## Sync in the background

The Mac syncs only while it runs (no login item, no agent). Triggers (contracts/mac-app-host.md §5):

- launch, and activation of the app: one pull;
- the window becoming visible again after being hidden or covered: one pull;
- a local change: the kit's 2 s debounce;
- the network coming back: a cycle;
- the kit's 15 s tick, for the life of the process: a cycle only when the last pull is 30 s old or
  changes wait, and never during a scheduled retry, so an idle tick sends nothing;
- File › "Sync now" (⌘R), the popover's "Sync now" and the footer's "Retry": single-flight;
- resigning and quitting: the workspace's last write is flushed before the app exits.

An open task's detail is read again on every 15 s tick, because subtasks and comments written
elsewhere reach this Mac only that way.

**App Nap.** macOS stretches the timers of an app that is hidden or covered. While an account is
linked, the app holds a `ProcessInfo` activity (`.userInitiatedAllowingIdleSystemSleep`, "Keeping
Brain Buddy in sync"), so a change made on the web or the iPhone appears within about a minute
even when the window is covered; it ends at sign-out, and an account-less Mac holds none. The cost
is accepted: an idle tick sends nothing, and a full pull runs at most every 30 s.

**Nothing is sent before sign-in.** Account-less, every trigger reaches the engine, which sends
nothing but a pending logout: one left by a sign-out, or the pre-021 session handed over by the
cookie cleanup, each to its own host and carrying no task data.

## The first sign-in and its timestamp limit

The first sign-in adds this Mac's tasks to the account: projects and tags with the same name
become one, and tasks are never merged by title. The server stamps creation, completion,
cancellation and waiting-since times itself, so after the first sign-in, tasks completed on the
Mac before the upgrade show the **upload day** as their completion date in History, and a Waiting
task's age, a created date and a cancelled date restart at the upload day, as the iPhone's
account-less upload does. Order, due dates and every other field are kept, and the review marks in
`mac-local.json` do not depend on these times. Keeping the original times would need the server to
accept client times, which is out of scope.

## Sign-out

"Sign out…" (popover or app menu) first runs the window's discard confirmation when a task edit is
unsaved or the capture draft is not empty, then the confirmation with the count of changes that
would be removed, the open sync issues and the pre-upgrade backup. If a change arrives while it is
open, nothing is signed out and it shows again with the new count. The kit records the session as
a pending logout, removes this Mac's copy of the account's data, and only then removes the token
and ends the server session (now, or when the network is back); if the removal fails, nothing is
removed and the person is still signed in ("Couldn't sign out"). Review marks are kept.

## The dry run

`BRAINBUDDY_MAC_DATA_DIR=<an existing folder>` runs the app on a copy of a folder (quickstart
Scenario 6 step 0): every file of the table above lives there, the pre-021 cookies and HTTP cache
are left alone, and the app makes no Keychain call at all (no read, write or removal) until a
sign-in the person starts in the dry run. Never sign in during a dry run of real data. See
`macos/README.md` for the commands.
