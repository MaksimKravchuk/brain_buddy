# Contract: the Mac app host (process, files, triggers, sign-in, UI binding)

**Target**: `macos/` (executable `BrainBuddyMac`).

**Slices**:

- **PR-08**: §1 – §4 and §6, plus X-05 and X-06.
- **PR-09**: §5 and §7, plus X-01 – X-04 and X-07.

**Design**: every screen and state id below is from `specs/021-mac-sync/design.md`.

## 1. Process and files

| item | value |
|---|---|
| Folder | `~/Library/Application Support/BrainBuddyMac/` (0700, existing) |
| Workspace document | `store.json` + `.store.json.lock` (kit `FileDocumentStore`, `flock`) |
| Sidecar | `mac-local.json` + `.mac-local.json.lock` (data-model E7) |
| Legacy store | `local-gtd.json` + `.local-gtd.json.lock` (`lockf`, import only), then `local-gtd.backup-<UTC>.json` |
| Single instance | `.instance.lock`, an exclusive non-blocking `flock` held for the process lifetime (`SingleInstanceGuard.swift`, research R6) |
| Keychain | service `app.brainbuddy.mac.session` (data-model E9) |
| Server address | `UserDefaults` key `BrainBuddyAPIURL` (existing), https only, `http://localhost` allowed (kit rule) |

**Launch order**:

1. `SingleInstanceGuard`: if it fails, activate the other copy or show the "already open" alert (design gap G-8), then exit.
2. `LegacyStoreImporter` (contracts/mac-legacy-import.md).
3. `WorkspaceHost.make()` builds `Workspace` with:
   - `FileDocumentStore(fileURL: …/store.json)`;
   - `SyncEngine(store:tokenStore: KeychainSessionTokenStore(service: "app.brainbuddy.mac.session"), configuration: .init(pullInterval: SyncTiming.pullAge), identity: .macOS(version:))`;
   - `device: .mac`.
4. `workspace.load()`.
5. `SyncTriggerSource.start()`.

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
  - The sidebar section "Archived projects · N" is collapsible, starts collapsed, and remembers its state in the sidecar.
  - Right-click offers "Unarchive project"; the project header has an "Unarchive" button.
  - "Restore" copy becomes "Unarchive" in every string (ContentView l.919, 1079, 2014, 2456, 3372, 3413, 3565, 3593).
  - The archived project view shows the outcome read-only, with no "Add a task".
  - The FR-027 line follows the http.md §2 display rule.
  - Labels read "<name> · archived".
- **Selection, scroll, focus and inline editor**: keyed by `EntityID`; save sends only the changed fields (research R18; FR-009, US1-5).

## 5. Sync triggers (`SyncTriggerSource.swift`, FR-006)

| event | call |
|---|---|
| launch | `Workspace.start()` (kit `.launch`) |
| `NSApplication.didBecomeActiveNotification` | `reloadIfChangedExternally()` then `.foreground` (forces a pull) |
| local change | the kit's 2 s debounce (`localChange`) |
| `NWPathMonitor` satisfied after unsatisfied | `networkAvailabilityChanged(isAvailable: true)` (kit `.networkRestored`) |
| `NWPathMonitor` unsatisfied | `networkAvailabilityChanged(isAvailable: false)` → `SyncSnapshot.isOnline = false` |
| 15 s timer, while the process runs | `.periodic` (pull only when older than 45 s) |
| File › "Sync now" ⌘R, popover "Sync now", "Retry" | `syncNow()` (`.manual`) |
| `willResignActive`, `willTerminate` | `flush()` |

Sync runs only while the app runs: there is no login item and no agent (spec Assumptions).

## 6. Composition of the status UI

- **X-01**: `SyncStatusLine.swift` renders `SyncStatusDescriber.describe(...)` at least every 30 s and on every snapshot change. The indicator in a reserved slot comes from `SyncActivityIndicator`. The tooltip and accessibility come from the description. No sync state ever presents a sheet, alert or notification, or moves focus (FR-017, SC-004).
- **X-02**: `SyncStatusPopover.swift` is a non-modal `.popover` from the status words, with the copy catalogue of contracts/sync-status.md §3.
  - Issues are listed with `SyncIssueDescriber`, with "Copy" (reference id) and "Dismiss" (`Workspace.dismissIssue`).
  - Focus order and Esc behaviour are as in design "Keyboard and focus".
  - At most 480 pt tall, with an internal scroll.
- **X-07**: `SyncMenuCommands.swift` (SwiftUI `Commands`):
  - File › "Sync now" ⌘R is disabled when the state is `accountLess`, `sessionEnded` or `offline`.
  - The app menu offers "Sign in…", "Sign in again…" and "Sign out…".

## 7. Sign-in and sign-out (FR-001, FR-003 – FR-005, FR-017, FR-018)

**X-03** (`SignInSheet.swift`, a window sheet):

- It calls `Workspace.signIn(email:password:serverURL:)`. Its states:
  - "first sign-in with local tasks", whose info box is shown when the outbox holds account-less data;
  - wrong password (401), with the reference id;
  - 429 / 5xx;
  - offline;
  - "sign in again", with the email locked;
  - "account switch refused", with the copy catalogue's `accountSwitchRefused` and the device `.mac`.
- **Cancelled deletion**: when `Workspace.signInCancelledAccountDeletion` is true, the sheet shows the iPhone's wording inside itself before it closes (G-3; FR-017).

**X-04** (`SignOutConfirmation.swift`, an alert sheet):

- The copy is `signOutUnsent` or `signOutNothingUnsent`; "Cancel" is the default.
- "Sign out and remove" calls `signOut(discardUnsyncedChanges: true)`; "Sign out" calls `signOut(discardUnsyncedChanges: false)`.
- On a local removal failure the "Couldn't sign out" alert appears and nothing is removed.
- After sign-out:
  - selection resets to Inbox and the footer shows the account-less line;
  - `MacLocalState.legacyImport.signedOutSinceImport = true`, and the backup retention check runs (data-model E8);
  - the sidecar marks are kept.
