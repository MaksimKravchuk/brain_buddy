# Contract: the Mac app host (process, files, triggers, sign-in, UI binding)

**Target**: `macos/` (executable `BrainBuddyMac`).

**Slices**:

- **PR-08**: §1 – §4 and §9, plus X-05, X-06, X-08 and X-09, and the §8 tests `LegacyCookieCleanupTests` and `UnreadableWorkspaceTests`.
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
| Folder override (dry run) | environment variable `BRAINBUDDY_MAC_DATA_DIR`: an absolute path to an existing folder; when set, every file in this table except the Keychain item lives there instead (`WorkspaceHost`, PR-08). The Keychain service and the cookie storage are not redirected, so while it is set the host skips `LegacyCookieCleanup` (launch step 3) and the launch-time token cleanup of step 4, and makes no Keychain call at all (no token or pending-logout read, no write, no removal) until the person signs in inside the dry run. Quickstart Scenario 6 step 0 never signs in, so a dry run sends no request and leaves the real cookie storage, HTTP cache and Keychain items untouched. Used by quickstart Scenario 6 step 0, the dry run on a copy of the owner's real folder (review c2, G02), and by host tests |

**Launch order**:

1. `SingleInstanceGuard`: if it fails, activate the other copy; only if that is not possible, show design **X-08** ("Brain Buddy is already open." / "Switch to the open window to keep working.", default button "OK"), then exit.
2. `LegacyStoreImporter` (contracts/mac-legacy-import.md), including the FR-033 "later file" decision and, after the terminal decision, the deletion of orphaned staging files (data-model E7.1 invariant 5).
3. `LegacyCookieCleanup` (review c1, F36; widened in review c2, G25, G52, G60), once, recorded as `legacyCleanupDoneAt` in `mac-local.json`, and never while `BRAINBUDDY_MAC_DATA_DIR` is set (dry run, table above):
   - **every** `brainbuddy_session` cookie in the app's own `HTTPCookieStorage.shared`, whatever its host, is deleted. Before deletion, each is handed to the kit's pending-logout list (`KeychainSessionTokenStore` pending logouts, data-model E9) **bound to its own cookie's host**: `https://<cookie domain>` (or `http://localhost` for a localhost cookie); a cookie whose host is neither is deleted without a logout. So no logout is ever sent to a host other than the cookie's own, and each session is ended when the network allows. This is the one request an account-less Mac may send (FR-029 as amended);
   - the pre-021 online mode's HTTP response cache is cleared: `URLCache.shared.removeAllCachedResponses()` (same bundle id, so the same on-disk cache) and the files `~/Library/Caches/com.brainbuddy.mac.prototype/Cache.db*` and `fsCachedData` are removed. The 021 transport is ephemeral and caches nothing.
4. `WorkspaceHost.make()` builds `Workspace` with:
   - `FileDocumentStore(fileURL: …/store.json)`;
   - `SyncEngine(store:tokenStore: KeychainSessionTokenStore(service: "app.brainbuddy.mac.session"), configuration: .init(pullInterval: SyncTiming.pullAge), identity: .macOS(version:))`;
   - `device: .mac`;
   - a `didPersist` hook that records `workspaceFirstWrittenAt` in `mac-local.json` on the first write (data-model E7.1 "in use").
   Its launch-time token cleanup runs off the main actor (data-model E9). While `BRAINBUDDY_MAC_DATA_DIR` is set (dry run, §1 table) that cleanup does not run, and the engine's token store answers "no token, no pending logouts" without calling the Keychain until a sign-in the person starts in the dry run; only that sign-in opens `KeychainSessionTokenStore`.
5. `workspace.load()`. If it sets `loadError` (an unreadable or newer `store.json`), the window shows design **X-09** instead of the lists, and sync does not start (§9).
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
  - **Unarchive refused, name in use** (design X-06 "unarchive refused: name in use"; review c1, F32): the local `.unarchiveNameInUse` refusal is immediate. The view shows "Another active project is already called “Old flat”. Rename one first." with "Rename…" for the archived project and no Retry; focus stays on "Unarchive". It reaches X-02 as a sync issue only when the clash appears while offline (kit-commands §4).
  - **"Rename…"** (design X-06 "rename archived project"; review c2, G30) opens the **existing rename sheet** (the sidebar's "Rename…", today `editingCollection = .project(id)`, `ContentView.swift:1978-1982`) for the archived project, with the current name selected. Saving runs `renameProject` (allowed on archived projects, kit-commands §3); a name another project already has shows the sheet's existing duplicate-name error (`GTDValidationError.duplicateProjectName`, whose copy kit-commands §2 keeps unchanged) with focus kept in the field. On success the refusal message clears and focus returns to "Unarchive"; the person presses Unarchive again (no automatic unarchive).
  - **Error focus** (review c2, G31): after a local write failure ("Couldn't unarchive “Old flat”. Try again."), focus moves to "Retry" and the message is announced.
  - "Restore" copy becomes "Unarchive" in every string (ContentView l.919, 1079, 2014, 2456, 3372, 3413, 3565, 3593).
  - The archived project view shows the outcome read-only, with no "Add a task".
  - The FR-027 line, the "no new task" rule and the "<name> · archived" labels come from the kit's `GTDQueries.projectDisplay` (kit-commands §8); the Mac never re-derives them.
  - Evidence: `specs/021-mac-sync/evidence/manual-macos-archive.md` (review c1, F23): every X-06 state, the remembered disclosure state across relaunch, the "Unarchive" strings, focus after archive and unarchive, the keyboard path.
- **Selection, scroll, focus and inline editor**: keyed by `EntityID`; save sends only the changed fields (research R18; FR-009, US1-5).
- **The row under the pointer** (FR-009's third clause; review c2, G04, G17): each list view holds the row under the pointer (`onHover`) and the row being edited in the kit's `ListPresentationHold` (kit-commands §8). An incoming change that would move that row leaves it in place, takes effect for every other row, and applies to the held row when the pointer leaves it or the edit ends. Host-check line in `manual-macos-status.md`.

## 5. Sync triggers (`SyncTriggerSource.swift`, FR-006)

| event | call |
|---|---|
| launch | `Workspace.start()` (kit `.launch`) |
| `NSApplication.didBecomeActiveNotification` | `reloadIfChangedExternally()` then `Workspace.setForegroundActive(true)` (one forced pull; kit-commands §4) |
| the main window becomes visible again (`NSWindow.didChangeOcclusionStateNotification` to visible) | `.foreground` (forces a pull) |
| local change | the kit's 2 s debounce (`localChange`) |
| `NWPathMonitor` satisfied after unsatisfied | `networkAvailabilityChanged(isAvailable: true)` (kit `.networkRestored`) |
| `NWPathMonitor` unsatisfied | `networkAvailabilityChanged(isAvailable: false)` → `SyncSnapshot.isOnline = false` |
| kit `PeriodicSyncTicker`, active for the life of the process (15 s) | `.periodic`: a cycle only when the pull is 30 s old or changes wait, never during a scheduled retry (kit-commands §4) |
| File › "Sync now" ⌘R, popover "Sync now", "Retry" | `syncNow()` (`.manual`) |
| `willResignActive` | `flush()` |
| `willTerminate` (`applicationShouldTerminate` → `.terminateLater`) | `flush()`, then `Workspace.waitForSignOutRemoval()`: a confirmed sign-out finishes removing the account's data before the process ends (FR-018); its server logout is recorded and goes at the next launch if not now |

Sync runs only while the app runs: there is no login item and no agent (spec Assumptions).

**Timers while the window is hidden** (FR-006 as amended; review c2, G07, G64): macOS App Nap throttles the timers of an app that is hidden or fully covered, which would stretch the 15 s tick. While an account is linked, `SyncTriggerSource` holds `ProcessInfo.processInfo.beginActivity(options: .userInitiatedAllowingIdleSystemSleep, reason: "Keeping Brain Buddy in sync")` and ends it at sign-out; account-less, it holds none. The cost is accepted: an idle tick sends nothing, and a full pull runs at most every 30 s. Occlusion turning visible also forces a pull. Host-check line: with the window covered by another app and Brain Buddy not frontmost, a change made on the web appears within 60 s.

**Nothing is sent before sign-in** (FR-029 as amended; review c1, F24; review c2, G38, G52, G60): every trigger above reaches the engine, which guards `runCycle` on an account. The only requests an account-less Mac may send are pending logouts that end a session opened earlier on this Mac (the engine's `retryPendingLogouts()` runs before the account guard): one left by a sign-out, or the pre-021 session handed over by `LegacyCookieCleanup`, each sent only to its own host. They carry no task data. A fresh account-less install sends nothing at all, and an upgraded one with a pre-021 cookie sends exactly one logout (§8 tests).

## 6. Composition of the status UI

- **X-01**: `SyncStatusLine.swift` renders the output of `SyncStatusLineModel` (a pure Mac type over `SyncStatusDescriber.describe(...)` and `SyncActivityIndicator`): it re-describes at least every 30 s and on every snapshot change, keeps the indicator's slot reserved whether or not the indicator shows, and announces an attention state once on entry. The tooltip and accessibility come from the description. No sync state ever presents a sheet, alert or notification, or moves focus (FR-017, SC-004).
- **Sidebar hidden** (design X-01 "sidebar hidden"; review c2, G29): the window is a `NavigationSplitView` whose sidebar can be collapsed. While it is collapsed **and** an attention state holds (session ended, couldn't sync, changes couldn't sync), one compact toolbar item shows the same words and glyph and opens X-02; in calm states the toolbar shows nothing about sync, so X-07's rule holds whenever all is well. The item appears without taking focus.
- **Presentation router** (review c1, F22): `MacPresentationRouter.swift` is the only type that sets the window's sheet, alert or popover and requests focus. Its only inputs are `UserIntent` values (a click, a menu item, a shortcut, the launch notices of X-05, X-08 and X-09); it has no `SyncSnapshot` input. The status line's model produces text, tone, glyph and announcements only. A source-level guard keeps it so (§8 `MacPresentationGuardTests`; review c2, G16).
- **X-02**: `SyncStatusPopover.swift` is a non-modal `.popover` from the status words (or the sidebar-hidden toolbar item), with the copy catalogue of contracts/sync-status.md §3.
  - Issues are listed with `SyncIssueDescriber`, with "Copy" (reference id) and "Dismiss" (`Workspace.dismissIssue`). The kept-outcome issue shows the full outcome, selectable, with "Copy outcome" and **"Discard outcome"** (accessible name "Discard your outcome for “<project>”"); after Discard, "Outcome discarded · Undo" stays 5 s, announced politely, and Undo restores the issue (review c2, G32).
  - **Focus after Dismiss** (review c1, F30): to the next issue's "Copy", or to the previous issue's when the last row was dismissed; after the last issue, to "Sync now", or to "Sign out…" when "Sync now" is disabled.
  - In the session-ended state "Sync now" is shown **disabled**, as in offline and in X-07, never hidden (review c1, F52).
  - While the pre-upgrade backup exists, `popoverBackup` (its three forms) with "Show in Finder"; while the import report exists, `popoverImportAdjusted` with "Show in Finder"; while a previous-version file is kept, `popoverLaterFile` with "Show in Finder".
  - **Tab order** (review c2, G27): attention action (Sign in again, or Sign in… when account-less, or the failing notice's Copy) → each issue's Copy → Copy outcome → Dismiss or Discard outcome → Sync now (skipped when disabled) → the offline notice's last-failure Copy → Sign out… → backup "Show in Finder" → import report "Show in Finder" → earlier-version "Show in Finder".
  - **Focus on open**: the attention action; otherwise "Sync now" when enabled; otherwise "Sign in…" when account-less; otherwise the first enabled control.
  - **"Show in Finder"** reveals the file in Finder, which comes to the front; the popover closes as any transient popover does when the app loses focus, and focus returns to the status words when the person comes back.
  - Esc or a click outside closes it, focus back to the status words.
  - At most 480 pt tall, with an internal scroll.
- **X-07**: `SyncMenuCommands.swift` (SwiftUI `Commands`):
  - File › "Sync now" ⌘R follows `syncNowEnabled`: it is disabled only when the state is `accountLess`, `sessionEnded` or `offline`, and it is never disabled by a running sync. A press during a sync is single-flight (contracts/kit-commands.md §4). The same rule applies to the X-02 "Sync now" and the X-01 "Retry".
  - The app menu offers "Sign in…", "Sign in again…" and "Sign out…". "Sign in…" and "Sign in again…" are disabled while an X-03 flow is open (`MacSyncController.isSignInOpen`, as delivered 2026-10-08; §7 "Single flight"), and also while a confirmed sign-out commits (`MacSyncController.isSigningOut`); "Sign out…" is disabled while an X-03 flow is open (§7 "Account changes are one at a time").

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
  - "couldn't save sign-in" (review c1, F25, F39): the Keychain write failed: "Brain Buddy couldn't save your sign-in on this Mac. Try again." with the reference id; the session the server opened is ended (kit-commands §4 "Keychain write failure at sign-in").
- **The Keychain prompt** (review c2, G34): sign-in is the only interactive Keychain path. If macOS asks to allow access to the saved sign-in (after a local rebuild), the prompt appears during this person-started sheet, never during routine sync. On "Deny", the existing item is deleted and added again; if that is refused too, the "couldn't save sign-in" state shows, and `docs/native-macos-app.md` says how to remove the item in Keychain Access. **As delivered (2026-10-08, PR-09; supersedes the delete-and-re-add above)**: macOS lets a build neither read nor delete an item another build created (`errSecInvalidOwnerEdit`, -25244, with no prompt), so no access prompt is raised and nothing is deleted and re-added. After a rebuild the footer reads "Sign in again to sync"; the person's sign-in saves the new session as the next numbered item (`<host>#1`, `#2`, …) beside the earlier build's item, and the highest-numbered item is the session (contracts/kit-commands.md §4, data-model E9). "Couldn't save sign-in" shows only when that new item cannot be written or does not read back. Known residual: the earlier build's item stays, unread, until its server session expires (30 days) or the person deletes it in Keychain Access (`docs/native-macos-app.md`).
- **Loading** (review c1, F28): while "Signing in…" runs, the fields are read-only but **Cancel and Esc stay enabled** (until the account is linked, below). Cancelling aborts the request, keeps the typed values, puts focus in Password and changes nothing; if the server's reply arrives after the cancel, its session is ended at once and nothing is linked. Other windows and the quick-capture panel stay usable; the main window is behind its sheet, as for any macOS sheet.
- **Cancel is decided once, at the link** (as delivered 2026-10-08, PR-09; refines "Loading" above, which said Cancel stays enabled throughout): the kit's `SignInCancellation` decides Cancel against the link exactly once, in `commit()` immediately before the durable link is written (contracts/kit-commands.md §4). A Cancel that comes first links nothing and ends the session the server opened. After the commit the sheet moves to `SignInFlow.Phase.finishing`: it still reads "Signing in…" with the indicator, **Cancel and Esc are disabled**, the first sync runs as a normal signed-in sync, and the sheet closes signed in (after the "account deletion cancelled" note when there is one). A Cancel pressed in the instant the link wins is refused, and the sheet moves to `finishing` rather than reporting "cancelled" for a sign-in that linked the account.
- **Single flight** (X-03; as delivered 2026-10-08, PR-09): `MacSyncController.beginSignIn` keeps an open flow, whether its sheet is shown or its one request is on its way. A second "Sign in…" or "Sign in again…" (the app menu, the footer, the popover) does nothing, with the typed values and the request untouched, and the app menu's two items are disabled meanwhile (`isSignInOpen`), so two logins can never race.
- **After Cancel the flow is `.cancelling`** (as delivered 2026-10-08, PR-09, a later review; refines "Loading" and "Cancel is decided once" above, which put the sheet straight back to editing): Cancel stops the request and brings back the typed values with focus in Password, but "Sign in" stays disabled (`SignInFlow.Phase.cancelling`) until the cancelled request, and the kit's undoing of a late reply, has ended; only then does the flow return to `.editing`. Cancel and Esc still close the sheet. Password sign-ins also take turns in the engine and the kit refuses a second `signIn` while one runs, so two logins never overlap (contracts/kit-commands.md §4 "Account changes are one at a time").
- **Account changes are one at a time** (as delivered 2026-10-08, PR-09, a later review): sign-in and sign-out never overlap. While an X-03 flow is open (during "Sign in again…" the account stays linked), `requestSignOut` and `presentSignOut` do nothing and the app menu's "Sign out…" is disabled; while a confirmed sign-out commits (`MacSyncController.isSigningOut`: the X-04 flow's `isSigningOut` or `Workspace.isSigningOut`), `beginSignIn` opens nothing and the two sign-in items are disabled. The kit refuses the overlap too (`WorkspaceError.signingIn`, `Workspace.signingOutMessage`), so a sign-in never links an account a sign-out removed meanwhile.
- **Focus on close** (review c1, F29): to the control that opened the sheet when it still exists; otherwise (the popover closed, the trailing action vanished because sign-in succeeded, or a menu item opened it) to the X-01 status words. On Cancel, to the X-01 trailing action when it still exists.
- **Cancelled deletion**: when `Workspace.signInCancelledAccountDeletion` is true, the sheet shows the design's "signed in, account deletion cancelled" state before it closes:
  - the same sheet replaces its form with the note "Your account deletion was cancelled" / "Signing in cancels a deletion you requested in the last 14 days. Delete your account again on the web if you still want to.";
  - focus moves to the note, and "OK", Return or Esc closes the sheet;
  - sync has already started behind it (G-3; FR-017).

**X-04** (`SignOutConfirmation.swift`, an alert sheet):

- The copy is `signOutUnsent` or `signOutNothingUnsent`, followed by `signOutIssues(n)` when sync issues are open (FR-018), then `signOutBackup(until)` or `signOutBackupRemoved` (FR-021, data-model E8); "Cancel" is the default (review c1, F06, F27, F54; review c2, G24, G39). During the first upload the imported records are unsent changes, so the `signOutUnsent` variant applies with their count (review c1, F33).
- **Unsaved weekly-review drafts** (as delivered 2026-10-08, owner decision): signing out also removes the weekly-review form text typed on this Mac and not saved (`LocalReviewState.formDrafts`, in the store file the sign-out deletes), so X-04 names it. `SignOutFlow.Prompt.reviewDrafts` is `Workspace.unsavedReviewDraftCount` and `signOutConfirmation(reviewDrafts:)` appends `signOutReviewDrafts(count)` after `signOutIssues` and before the backup sentence: "1 unsaved weekly-review draft will also be removed from this Mac." / "N unsaved weekly-review drafts will also be removed from this Mac." Drafts alone change neither the title ("Sign out?") nor the button ("Sign out", not destructive), and a changed draft count does not re-present X-04 (FR-018).
- **Unsaved edit or capture draft first** (design X-04 "unsaved edit or capture draft"; review c2, G28): "Sign out…" from X-02 or the app menu first runs today's discard confirmation for an unsaved task edit or a non-empty capture draft (`requestNavigation(.signOut)` in the current app); X-04 opens only after the person discards or there is nothing to discard.
- **Changes that arrive while X-04 is open** (design X-04 "changes arrived while open"; G28): the count shown is kept with the dialog. At confirm, if the count of unsent changes or open issues differs (for example a quick capture taken meanwhile), or the kit refuses a plain "Sign out" with `WorkspaceError.unsyncedChanges`, nothing is signed out and X-04 is presented again with the new count. "Sign out and remove" discards only when the count is unchanged. **As delivered (2026-10-08, PR-09)**: the count is not the whole check, see the next bullet.
- "Sign out and remove" calls `signOut(discardUnsyncedChanges: true)`; "Sign out" calls `signOut(discardUnsyncedChanges: false)`. **As delivered (2026-10-08, PR-09; supersedes the two calls above)**: X-04 captures `Workspace.pendingChanges` when it is shown (`SignOutFlow.Prompt.changes`, each change by operation id and content) and confirming calls `Workspace.signOut(removing:)` with exactly that set, empty for a plain "Sign out". "Sign out and remove" therefore removes only the changes X-04 named. Any other pending change refuses with `WorkspaceError.unsyncedChanges` and the real count: one queued in place of an acknowledged one (same count), one a widget or App Intent queued meanwhile, or an edit compacted into a named change (same id, other content). Nothing is removed in that case, and X-04 is presented again with the real count (contracts/kit-commands.md §4). **Open sync issues are named by identity too** (as delivered 2026-10-08, PR-09, a later review): `Workspace.pendingChanges` covers unsent changes and open issues (`PendingChange`), and every check of `signOut(removing:)`, the one under the store's lock included, compares both, so an unnamed issue, or a named change the server rejected meanwhile (now an issue with another id), refuses with `unsyncedChanges` and X-04 opens again with the real counts.
- **Edits are refused while sign-out runs** (as delivered 2026-10-08, PR-09): from the sign-out's first suspension until it returns, `Workspace.isSigningOut` makes every command fail with `GTDValidationError.signingOut` ("Brain Buddy is signing out. This wasn't saved; try again in a moment."). The global Quick Capture panel and the main window show those words and keep the typed text; the same capture is taken once signed out. A failed sign-out takes edits again.
- On a local removal failure the "Couldn't sign out" alert appears and nothing is removed. The kit's sign-out order (kit-commands §4 "Sign-out order") ends the server session only after the local removal succeeded, so the person really is still signed in, as the copy says (review c1, F59).
- After sign-out:
  - selection resets to Inbox and the footer shows the account-less line;
  - `MacLocalState.legacyImport.signedOutSinceImport = true`, and the backup retention check runs (data-model E8);
  - the sidecar marks are kept.

## 8. Tests and evidence on the macOS lane (review c1, F22, F24, F25, F36, F39)

All in `macos/Tests/BrainBuddyMacTests/`, Swift Testing, run by the `macos-app` lane (PR-01):

| file | cases |
|---|---|
| `MacPresentationRouterTests.swift` | positive control for `021-SC-004`, `021-FR-017`: each `UserIntent` presents exactly its own surface, and a sweep of every `SyncLineState` and transition through the status-line model leaves the router untouched. On its own this cannot fail by construction (the router has no snapshot input), so the guard below carries the evidence (review c2, G16) |
| `MacPresentationGuardTests.swift` (new, review c2, G16) | `021-SC-004`, `021-FR-017`: reads the Mac target's sources (via `#filePath`) and fails if `.sheet(`, `.alert(`, `.confirmationDialog(`, `.popover(isPresented`, `NSAlert`, `NSSound`, `UNUserNotificationCenter`, `NSApp.activate`, `makeFirstResponder` or a `@FocusState` assignment appears outside `MacPresentationRouter.swift` and an explicit allow-list of person-started views (`SignInSheet.swift`, `SignOutConfirmation.swift`, `UpgradeNotice.swift`, the X-08 and X-09 views, and the person-started sheets and confirmations that exist today: `ProjectReviewView.swift`, `QuickCaptureView.swift`, `QuickOpenView.swift` and the editors, rename, move, review, clarify, voice and confirmation sheets of `ContentView.swift` behind marked regions; the test lists each allowed file and region by name, so a new file is not allowed by default); and if any allow-listed call's condition reads `SyncSnapshot` or `syncStatus` |
| `SyncStatusLineModelTests.swift` (new, review c2, G16) | `021-FR-012`, `021-FR-013`: the model re-describes when 30 s pass with no snapshot change; the indicator slot keeps its width whether the indicator shows or not; entering an attention state yields exactly one announcement, and staying in it yields none; calm changes are never announced; the sidebar-hidden toolbar item appears only in attention states and requests no focus (`021-FR-017`) |
| `MacSyncFlowTests.swift` | `021-FR-029`: a host built with a counting `HTTPTransport`, account-less, receives launch, foreground, 15 s `.periodic` ticks, network-restored and local-change triggers and sends **zero** requests; after a sign-out, the only request is the queued logout; an **upgraded** account-less host with a seeded pre-021 cookie for `https://api.example.com` sends exactly one `POST /auth/logout` to that host and nothing else (review c2, G52, G60). `021-FR-030`: with sentinel titles, the captured `os.Logger` lines of the sync category hold no sentinel, no email and no host. `021-FR-001`, `021-FR-004`, `021-FR-018`: sign-in, sign-out and switch-refusal flows against a stub transport, including US4-5's reachable trigger: "Sign in again" whose credentials resolve to a different account id while changes wait → refused, nothing sent (review c2, G40). `021-FR-018` (G28): X-04 opened with 3 unsent changes, a quick capture taken before confirm → nothing is signed out and X-04 shows 4; a plain "Sign out" refused by the kit re-presents X-04. `021-FR-005`: `WorkspaceHost` uses the service `app.brainbuddy.mac.session`, and every token-store call made by the host and the engine arrives off the main thread (a spy store records `Thread.isMainThread`; G34); with `BRAINBUDDY_MAC_DATA_DIR` set and the spy store seeded with a token and a pending logout, launch, foreground, 15 s ticks and network-restored triggers make no token-store call and send nothing, and a sign-in started in the dry run is the first call (§1) |
| `MacKeychainTests.swift` | `021-FR-005` (review c2, G34, G47): each test creates a **temporary keychain** (`SecKeychainCreate` in the test's temporary folder, random password, unlocked), points a `KeychainSessionTokenStore` at it through the macOS-only test initializer, and deletes it afterwards. It never touches the login keychain or prompts, so the hosted runner can run it; a failure to create the keychain **fails** the test instead of downgrading to a host check. Cases: set, read, update, remove, add and remove a pending logout; the stored item is not synchronizable; a non-interactive read of an item whose access is refused returns `errSecInteractionNotAllowed` handling (treated as no token), with no prompt; a person's sign-in writes past an item an earlier build left, so this build reads its session; the newest item decides (as delivered 2026-10-08, PR-09; replaces "delete-and-re-add after a refused interactive write", which macOS refuses with -25244) |
| `MacPrivacyGuardTests.swift` | `021-FR-029`: the voice sources (`VoiceCapture.swift` and the `VoiceTranscriber` actor) contain no `URLSession`, `import Network` or `BrainBuddyAPI` |
| `LegacyCookieCleanupTests.swift` (PR-08) | `021-FR-005`, `021-FR-029` (review c2, G25, G52): seeded `brainbuddy_session` cookies for three hosts in an injected cookie storage are all gone after launch, each is in the pending-logout list bound to its own host, and an `http://` non-localhost cookie is deleted without a logout; a synthetic response seeded in an injected `URLCache` is gone; a second launch does nothing; with `BRAINBUDDY_MAC_DATA_DIR` set, the seeded cookies and cache entry stay, no pending logout is queued and nothing is sent, and a spy token store seeded with a token and a pending logout records no call during launch steps 3 and 4 (`WorkspaceHost.make()` included), so both items stay |
| `UnreadableWorkspaceTests.swift` (new, review c2, G15) | `021-FR-022`, `021-FR-017`: a `store.json` that does not decode shows X-09, starts no sync and sends nothing; "Try again" reloads; "Start fresh" after its confirmation sets the file aside as `store.unreadable-<UTC>.json`, starts an empty workspace, and the import decision then treats the workspace as in use (no import of a `local-gtd.json` present) |
| `SyncTriggerSourceTests.swift` | the §5 table with a fake clock and a fake path monitor; the App Nap activity is held exactly while an account is linked; occlusion to visible requests `.foreground` |

**Host checks** (manual; the evidence protocol is in plan.md "Evidence protocol": each file names the build by the git tree hashes of `macos/`, `ios/BrainBuddyKit/` and `ios/BrainBuddy/`, plus the macOS version and the date, with one line per state):

- `manual-macos-status.md`: SC-004 sweep as before, plus scroll position, selection and keyboard focus kept while an incoming change arrives (FR-009); **the row under the pointer stays put while a pull would move it, and moves when the pointer leaves** (FR-009, G17); with the window covered and Brain Buddy not frontmost, a web change appears within 60 s (G07, G64); the sidebar collapsed during "Sign in again to sync" shows the toolbar item (G29); after signing in, the Keychain item exists (recorded as "Keychain item present: yes", never pasting `security` output, which contains the keychain path; G54) and "token found in files: no" for `store.json`, `mac-local.json` and `defaults read com.brainbuddy.mac.prototype`; the sign-in sheet's Cancel during "Signing in…" (before the account is linked; once it is, Cancel and Esc are disabled); after a rebuild, routine sync shows no Keychain prompt and the prompt, if any, appears only in the sign-in sheet (G34); X-02 Tab order and focus on open in the account-less, offline-with-no-issues and kept-outcome states (G27).
- `manual-macos-upgrade.md` and `manual-macos-archive.md` as listed in the plan, the latter including the archived project's "Rename…" flow (G30).

## 9. Unreadable workspace (design X-09; review c2, G15, G26)

The kit already handles a `store.json` it cannot decode, or one written by a newer build: `Workspace.load()` sets `loadError`, leaves the file and does not start sync (`Workspace.swift:681-691`); `resetUnreadableStore()` sets it aside as `store.unreadable-<UTC>.json` and starts empty; a later sign-out deletes the asides. The iPhone shows this in `ios/BrainBuddy/App/RootView.swift:142-190`. The Mac mirrors it:

- **X-09** replaces the lists in the main window (not a dialog): "We couldn't open your tasks" / "Your tasks are still on this Mac and nothing was changed." + the kit's message, with "Try again" (default) and "Start fresh…". The status line shows nothing about sync; nothing is sent.
- "Start fresh…" asks, in a person-started confirmation: "Set the file aside and start fresh?" / "The unreadable file stays on this Mac, set aside where Brain Buddy won't use it. You start with empty lists; tasks you synced come back when you sign in." · "Keep trying" (default) · "Set aside and start fresh".
- **With the import state machine**: the aside file makes the workspace "in use" (data-model E7.1 invariant 2), so a `local-gtd.json` present after the reset is a later file, never imported.
- The aside files are listed in data-model E5's retention rows and removed by sign-out.
- Downgrades (kit-commands §6) land here too: a document a build cannot decode is reported, never overwritten.
