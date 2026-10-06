# Contract: the Mac app host (process, files, triggers, sign-in, UI binding)

**Target**: `macos/` (executable `BrainBuddyMac`).

**Slices**:

- **PR-08**: §1 – §4, plus X-05, X-06 and X-08.
- **PR-09**: §5 – §8, plus X-01 – X-04 and X-07.

**Design**: every screen and state id below is from `specs/021-mac-sync/design.md`.

## 1. Process and files

| item | value |
|---|---|
| Folder | `~/Library/Application Support/BrainBuddyMac/` (0700, existing) |
| Workspace document | `store.json` + `.store.json.lock` (kit `FileDocumentStore`, `flock`) |
| Sidecar | `mac-local.json` + `.mac-local.json.lock` (data-model E7) |
| Legacy store | `local-gtd.json` + `.local-gtd.json.lock` (`lockf`, import only), then `local-gtd.backup-<UTC>.json` |
| Import staging | `store.import-<attemptID>.json`, moved to `store.json` only after verification, by an exclusive rename (data-model E7.1) |
| Single instance | `.instance.lock`, an exclusive non-blocking `flock` held for the process lifetime (`SingleInstanceGuard.swift`, research R6) |
| Keychain | service `app.brainbuddy.mac.session`, login keychain (data-model E9) |
| Server address | `UserDefaults` key `BrainBuddyAPIURL` (existing), https only, `http://localhost` allowed (kit rule) |

**Launch order**:

1. `SingleInstanceGuard`: if it fails, activate the other copy; only if that is not possible, show design **X-08** ("Brain Buddy is already open." / "Switch to the open window to keep working.", default button "OK"), then exit.
2. `LegacyStoreImporter` (contracts/mac-legacy-import.md), including the FR-033 "later file" decision.
3. `LegacyCookieCleanup` (review c1, F36): on the first 021 launch, the pre-021 client's cookies for the stored `BrainBuddyAPIURL` host and the default host are deleted from `HTTPCookieStorage.shared`. A `brainbuddy_session` cookie found there is handed to the kit's pending-logout list (`KeychainSessionTokenStore` pending logouts, data-model E9) before it is deleted, so its server session is ended when the network allows. Done once; recorded in `mac-local.json`.
4. `WorkspaceHost.make()` builds `Workspace` with:
   - `FileDocumentStore(fileURL: …/store.json)`;
   - `SyncEngine(store:tokenStore: KeychainSessionTokenStore(service: "app.brainbuddy.mac.session"), configuration: .init(pullInterval: SyncTiming.pullAge), identity: .macOS(version:))`;
   - `device: .mac`.
5. `workspace.load()`.
6. `SyncTriggerSource.start()`.

## 2. Package (`macos/Package.swift`)

```swift
// swift-tools-version: 6.2
// shape only
dependencies: [
  .package(url: "https://github.com/argmaxinc/argmax-oss-swift.git", from: "0.18.0"),
  .package(path: "../ios/BrainBuddyKit"),
],
targets: [
  .executableTarget(name: "BrainBuddyMac", dependencies: [
     .product(name: "WhisperKit", package: "argmax-oss-swift"),
     .product(name: "BrainBuddyCore", package: "BrainBuddyKit"),
     .product(name: "BrainBuddyPersistence", package: "BrainBuddyKit"),
     .product(name: "BrainBuddyAPI", package: "BrainBuddyKit"),
     .product(name: "BrainBuddySync", package: "BrainBuddyKit"),
     .product(name: "BrainBuddyWorkspace", package: "BrainBuddyKit")]),
  .testTarget(name: "BrainBuddyMacTests", dependencies: ["BrainBuddyMac"], resources: [.copy("Resources")]),
]
```

- Swift 6 language mode (the 6.2 default); no `unsafeFlags`; no `@unchecked Sendable` without a comment (research R2).
- `macos/build_app.sh` is unchanged except that `swift build` now also builds the kit.
- The `AppInfo.plist` bundle id is unchanged (`com.brainbuddy.mac.prototype`), so the keychain and the single-instance lookup are stable.

## 3. What is removed from the Mac target (design "Notes for the plan")

- **Files**: `LocalGTDStore.swift`, `APIClient.swift`, `SmartAddParser.swift` (the kit's `SmartAddParser` / `CapturePlanner` replace it). Before the Mac file is deleted, its `SmartAddParserTests` cases that the kit lacks are ported to `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/SmartAddParserTests.swift` in PR-04.
- **`BrainBuddyModel`**: its GTD rules and store calls go, and its pending-key maps (ContentView l.68 – 83) are replaced by the kit outbox.
- **Views and controls**:
  - the full-window `signIn` view (l.1927 – 1956) and the `sessionExpired` overlay (l.1567 – 1575);
  - the "Sync needs attention" banner and `syncConflictTaskID` (l.2370 – 2393, 1144 – 1150);
  - the toolbar "Refresh" (l.1539 – 1544);
  - "Try local voice capture" (l.1951);
  - "Desired outcome is not available in this workspace yet." (l.2489 – 2491).
- **`isLocalWorkspace` gates**: every one goes (l.110, 174, 250, 400, 505, 1996 – 2000, 2009 – 2020, 2312 – 2318, 2476 – 2482, 2555 – 2558, 3102, `QuickCaptureView.swift:74`). Archived projects, "Set outcome", the Waiting, Someday and Project reviews, Inbox "clarify as project" and quick capture all work signed in and account-less alike (FR-010, FR-023, FR-026, FR-028).

## 4. Mac-only behaviour kept

- **Waiting, Someday and Project reviews**: they read their due state from `MacLocalState` (data-model E7) and write marks only there.
- **Composite flows** go through `Workspace.apply([...])` (contracts/kit-commands.md §2):
  - follow-up + keep-waiting;
  - Someday → Next with a new title;
  - Inbox → new project with an outcome and a first Next action.
- **Quick capture** (⌃⌥⇧B), **voice to draft** (WhisperKit, local only) and **Smart Add**: unchanged in feel. They capture through `Workspace.capture`, which never waits on the network (FR-010).
- **Archived projects (X-06)**:
  - The sidebar section "Archived projects · N" is collapsible, starts collapsed, and remembers its state in the sidecar. Its disclosure is in the tab order, with the accessible name "Archived projects, 2, collapsed" / "…, expanded" (review c1, F31).
  - Right-click offers "Archive project" or "Unarchive project"; the project header has an "Unarchive" button.
  - **Keyboard path** (review c1, F31): `ProjectMenuCommands.swift` adds File › "Archive project" (selected active project) and File › "Unarchive project" (selected archived project), with no shortcut. "Archive project" keeps today's guard: disabled while a task edit is unsaved or the capture draft is not empty, with the same help text ("Add or clear the current task draft before archiving"; `ContentView.swift:1983-1989`).
  - **After archiving the open project** (design X-06 "archived (just now)"): selection stays on the project, which re-renders as the archived view with the chip and "Unarchive"; the Archived section expands to reveal its row; focus goes to the title.
  - **Unarchive refused, name in use** (design X-06 "unarchive refused: name in use"; review c1, F32): the local `.duplicateProjectName` refusal is immediate. The view shows "Another active project is already called “Old flat”. Rename one first." with "Rename…" for the archived project and no Retry; focus stays on "Unarchive". It reaches X-02 as a sync issue only when the clash appears while offline (kit-commands §4).
  - "Restore" copy becomes "Unarchive" in every string (ContentView l.919, 1079, 2014, 2456, 3372, 3413, 3565, 3593).
  - The archived project view shows the outcome read-only, with no "Add a task".
  - The FR-027 line, the "no new task" rule and the "<name> · archived" labels come from the kit's `GTDQueries.projectDisplay` (kit-commands §8); the Mac never re-derives them.
  - Evidence: `specs/021-mac-sync/evidence/manual-macos-archive.md` (review c1, F23): every X-06 state, the remembered disclosure state across relaunch, the "Unarchive" strings, focus after archive and unarchive, the keyboard path.
- **Selection, scroll, focus and inline editor**: keyed by `EntityID`; save sends only the changed fields (research R18; FR-009, US1-5).

## 5. Sync triggers (`SyncTriggerSource.swift`, FR-006)

| event | call |
|---|---|
| launch | `Workspace.start()` (kit `.launch`) |
| `NSApplication.didBecomeActiveNotification` | `reloadIfChangedExternally()` then `.foreground` (forces a pull) |
| local change | the kit's 2 s debounce (`localChange`) |
| `NWPathMonitor` satisfied after unsatisfied | `networkAvailabilityChanged(isAvailable: true)` (kit `.networkRestored`) |
| `NWPathMonitor` unsatisfied | `networkAvailabilityChanged(isAvailable: false)` → `SyncSnapshot.isOnline = false` |
| kit `PeriodicSyncTicker`, active for the life of the process (15 s) | `.periodic`: a cycle only when the pull is 30 s old or changes wait, never during a scheduled retry (kit-commands §4) |
| File › "Sync now" ⌘R, popover "Sync now", "Retry" | `syncNow()` (`.manual`) |
| `willResignActive`, `willTerminate` | `flush()` |

Sync runs only while the app runs: there is no login item and no agent (spec Assumptions).

**Nothing is sent before sign-in** (FR-029; review c1, F24): every trigger above reaches the engine, which guards `runCycle` on an account. The one request an account-less Mac may send is a pending logout of a session that ended earlier (the engine's `retryPendingLogouts()` runs before the account guard), which ends a session and carries no user data. A fresh account-less install sends nothing at all (§8 test).

## 6. Composition of the status UI

- **X-01**: `SyncStatusLine.swift` renders `SyncStatusDescriber.describe(...)` at least every 30 s and on every snapshot change. The indicator in a reserved slot comes from `SyncActivityIndicator`. The tooltip and accessibility come from the description. No sync state ever presents a sheet, alert or notification, or moves focus (FR-017, SC-004).
- **Presentation router** (review c1, F22): `MacPresentationRouter.swift` is the only type that sets the window's sheet, alert or popover and requests focus. Its only inputs are `UserIntent` values (a click, a menu item, a shortcut, the launch notices of X-05 and X-08); it has no `SyncSnapshot` input. The status line's model produces text, tone, glyph and announcements only. This makes SC-004 mechanical (§8).
- **X-02**: `SyncStatusPopover.swift` is a non-modal `.popover` from the status words, with the copy catalogue of contracts/sync-status.md §3.
  - Issues are listed with `SyncIssueDescriber`, with "Copy" (reference id) and "Dismiss" (`Workspace.dismissIssue`). The kept-outcome issue shows the full outcome, selectable, with "Copy outcome" before "Dismiss"; its Dismiss is named "Dismiss and discard the outcome for <project>".
  - **Focus after Dismiss** (review c1, F30): to the next issue's "Copy", or to the previous issue's when the last row was dismissed; after the last issue, to "Sync now", or to "Sign out…" when "Sync now" is disabled.
  - In the session-ended state "Sync now" is shown **disabled**, as in offline and in X-07, never hidden (review c1, F52).
  - While the pre-upgrade backup exists, a quiet line `popoverBackup(until)` with "Show in Finder"; while a previous-version file is kept, `popoverLaterFile` with "Show in Finder".
  - Focus order and Esc behaviour are as in design "Keyboard and focus".
  - At most 480 pt tall, with an internal scroll.
- **X-07**: `SyncMenuCommands.swift` (SwiftUI `Commands`):
  - File › "Sync now" ⌘R follows `syncNowEnabled`: it is disabled only when the state is `accountLess`, `sessionEnded` or `offline`, and it is never disabled by a running sync. A press during a sync is single-flight (contracts/kit-commands.md §4). The same rule applies to the X-02 "Sync now" and the X-01 "Retry".
  - The app menu offers "Sign in…", "Sign in again…" and "Sign out…".

## 7. Sign-in and sign-out (FR-001, FR-003 – FR-005, FR-017, FR-018)

**X-03** (`SignInSheet.swift`, a window sheet):

- It calls `Workspace.signIn(email:password:serverURL:)`. Its states:
  - "first sign-in with local tasks", whose info box is shown when the outbox holds account-less data;
  - wrong password (401), with the reference id;
  - 429 / 5xx;
  - offline;
  - "sign in again", with the email locked;
  - "account switch refused", with the copy catalogue's `accountSwitchRefused` and the device `.mac`;
  - "no answer" (review c1, F28): online but the request got no reply before the transport's timeout: "Brain Buddy didn't answer. Try again." with the reference id the client sent;
  - "couldn't save sign-in" (review c1, F25, F39): the Keychain write failed: "Brain Buddy couldn't save your sign-in on this Mac. Try again." with the reference id; the session the server opened is ended (kit-commands §4).
- **Loading** (review c1, F28): while "Signing in…" runs, the fields are read-only but **Cancel and Esc stay enabled**. Cancelling aborts the request, keeps the typed values, puts focus in Password and changes nothing; if the server's reply arrives after the cancel, its session is ended at once and nothing is linked. Other windows and the quick-capture panel stay usable; the main window is behind its sheet, as for any macOS sheet.
- **Focus on close** (review c1, F29): to the control that opened the sheet when it still exists; otherwise (the popover closed, the trailing action vanished because sign-in succeeded, or a menu item opened it) to the X-01 status words. On Cancel, to the X-01 trailing action when it still exists.
- **Cancelled deletion**: when `Workspace.signInCancelledAccountDeletion` is true, the sheet shows the design's "signed in, account deletion cancelled" state before it closes:
  - the same sheet replaces its form with the note "Your account deletion was cancelled" / "Signing in cancels a deletion you requested in the last 14 days. Delete your account again on the web if you still want to.";
  - focus moves to the note, and "OK", Return or Esc closes the sheet;
  - sync has already started behind it (G-3; FR-017).

**X-04** (`SignOutConfirmation.swift`, an alert sheet):

- The copy is `signOutUnsent` or `signOutNothingUnsent`, followed by `signOutIssues(n)` when sync issues are open (FR-018) and `signOutBackup(until)` while the pre-upgrade backup exists (FR-021); "Cancel" is the default (review c1, F06, F27, F54). During the first upload the imported records are unsent changes, so the `signOutUnsent` variant applies with their count (review c1, F33).
- "Sign out and remove" calls `signOut(discardUnsyncedChanges: true)`; "Sign out" calls `signOut(discardUnsyncedChanges: false)`.
- On a local removal failure the "Couldn't sign out" alert appears and nothing is removed. The kit's sign-out order (kit-commands §4 "Sign-out order") ends the server session only after the local removal succeeded, so the person really is still signed in, as the copy says (review c1, F59).
- After sign-out:
  - selection resets to Inbox and the footer shows the account-less line;
  - `MacLocalState.legacyImport.signedOutSinceImport = true`, and the backup retention check runs (data-model E8);
  - the sidecar marks are kept.

## 8. Tests and evidence on the macOS lane (review c1, F22, F24, F25, F36, F39)

All in `macos/Tests/BrainBuddyMacTests/`, Swift Testing, run by the `macos-app` lane (PR-01):

| file | cases |
|---|---|
| `MacPresentationRouterTests.swift` | `021-SC-004`, `021-FR-017`: sweeps every `SyncLineState` and every transition between them (with and without issues, offline, failing, session ended, first upload) through the status-line model and the router; asserts no sheet, alert or popover is presented and no focus request is made. Positive control: each `UserIntent` presents exactly its own surface |
| `MacSyncFlowTests.swift` | `021-FR-029`: a host built with a counting `HTTPTransport`, account-less, receives launch, foreground, 15 s `.periodic` ticks, network-restored and local-change triggers and sends **zero** requests; after a sign-out, the only request is the queued logout. `021-FR-030`: with sentinel titles, the captured `os.Logger` lines of the sync category hold no sentinel, no email and no host. `021-FR-001`, `021-FR-004`, `021-FR-018`: sign-in, sign-out and switch-refusal flows against a stub transport. `021-FR-005`: `WorkspaceHost` uses the service `app.brainbuddy.mac.session` |
| `MacKeychainTests.swift` | `021-FR-005`: `KeychainSessionTokenStore` round trip against the real login keychain with a test-only service (`app.brainbuddy.mac.session.tests`, removed after each test): set, read, update, remove, add and remove a pending logout; the stored item is not synchronizable. If the hosted runner's keychain is unavailable, the test reports that and the task records the same round trip as a host check instead |
| `MacPrivacyGuardTests.swift` | `021-FR-029`: the voice sources (`VoiceCapture.swift` and the `VoiceTranscriber` actor) contain no `URLSession`, `import Network` or `BrainBuddyAPI` |
| `LegacyCookieCleanupTests.swift` (PR-08) | `021-FR-005`: a seeded `brainbuddy_session` cookie in an injected cookie storage is gone after launch, and its value is in the pending-logout list; a second launch does nothing |
| `SyncTriggerSourceTests.swift` | the §5 table with a fake clock and a fake path monitor |

**Host checks** (manual, recorded under `specs/021-mac-sync/evidence/`, each file headed by the commit SHA, the build, the macOS version and the date, with one line per state; PR-10's check validates the headers):

- `manual-macos-status.md`: SC-004 sweep as before, plus scroll position, selection and keyboard focus kept while an incoming change arrives (FR-009); after signing in, the Keychain item exists (`security find-generic-password -s app.brainbuddy.mac.session` finds it) and the token appears in neither `store.json`, `mac-local.json` nor `defaults read com.brainbuddy.mac.prototype` (recorded as "token found in files: no"); the sign-in sheet's Cancel during "Signing in…".
- `manual-macos-upgrade.md` and `manual-macos-archive.md` as listed in the plan.
