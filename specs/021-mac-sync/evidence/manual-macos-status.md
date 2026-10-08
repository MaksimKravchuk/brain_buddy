# Feature 021 — macOS sync UI, host run (slice PR-09, T132 – T133)

**Status: PENDING. Nothing below has been run on a Mac yet.** The implementing agent wrote this
plan on 2026-10-08 on Linux, where the Mac app cannot be built (see "Agent pre-check on Linux" at
the end). Manual checks follow the merge (owner's decision of 2026-10-08): the slice merges once
CI is green, and this run is made on the landed build, or a candidate with identical trees.

- **Who runs it:** the owner, or the owner's agent on the owner's Mac.
- **Test account only.** Use a seeded synthetic account on a test server or a scratch account with
  the design's example data (`alex@example.com`-style addresses, "Garden", "Old flat"). Never the
  owner's real account or tasks.
- **What may be recorded here:** pass/fail, counts, "yes/no", times rounded to seconds, the words
  shown on screen for the design's example data. **Never** a session token, the output of
  `security` (it contains the keychain path), a home-folder path, a real email or real task text.
- **If a check fails:** stop, set the status to `FAIL (<check>)`, and the fix lands in a separate PR.
- **Acceptance:** 021-SC-004, 021-FR-009 and 021-FR-006 (and the on-screen halves of FR-001,
  FR-004, FR-005, FR-012 – FR-018) are not accepted on the Mac until the Results table is filled in
  from that run.

## What changed (the run is checking this)

- **X-01** the sidebar footer: one line of words from the kit's describer ("Synced 3 min ago",
  "Offline · 3 changes waiting", "Couldn't sync · Retry", "Sign in again to sync", "N changes
  couldn't sync"), a reserved indicator slot, at most one trailing action; a toolbar item with the
  same words only in attention states while the sidebar is collapsed.
- **X-02** the status popover from the words; **X-03** the sign-in sheet; **X-04** the sign-out
  confirmation; **X-07** File › "Sync now" ⌘R and the app menu's "Sign in…", "Sign in again…",
  "Sign out…".
- **Sync in the background**: the kit's 15 s tick for the life of the process, a pull on
  activation and when the window becomes visible again, an App Nap activity while signed in.
- **Session token** in the login keychain, service `app.brainbuddy.mac.session`; no prompt during
  routine sync; the only interactive write is the person's sign-in.
- **No sync state presents anything or moves focus** (`MacPresentationRouter`; the source guard
  `MacPresentationGuardTests`).

## Owner steps on the Mac

Prerequisites: macOS 26 or later, Xcode 26 with its command-line tools selected, the Whisper model
and tokenizer `macos/build_app.sh` needs (`macos/README.md`), a test account on a test server (or
the production server with a scratch account), and the web app open in a browser on the same
account. Turn on VoiceOver with ⌘F5 when a check asks for it. Before step 2, open Keychain Access ›
login and delete any `app.brainbuddy.mac.session` items an earlier build left, so S10 and O4 start
from none (a rebuilt app cannot delete them itself; K2).

### 1. CI lane and build on the exact SHA (T132)

The `macos-app` lane of `.github/workflows/ci.yml` runs on the merge commit. Record its job URL,
the `swift build` result and the `Test run with …` / `Executed …` lines. `MacKeychainTests` must
appear as run (not skipped). Then on the Mac:

```sh
cd <your brain_buddy clone>
git fetch origin
git switch --detach <SHA under test>
git rev-parse HEAD; sw_vers; xcodebuild -version; swift --version
set -o pipefail
cd macos
swift build --only-use-versions-from-resolved-file 2>&1 | tee /tmp/bb-021-pr09-build.log
echo "build exit: $?"
swift test --only-use-versions-from-resolved-file 2>&1 | tee /tmp/bb-021-pr09-test.log
echo "test exit: $?"
grep -E "Executed [0-9]+ tests|Test run with [0-9]+ tests" /tmp/bb-021-pr09-test.log
grep -E "Keychain on macOS" /tmp/bb-021-pr09-test.log | tail -n 3
sh build_app.sh
```

Expect: build exit 0, test exit 0, the "Keychain on macOS" suite passed (seven tests), and no
Keychain prompt during `swift test` (it uses a temporary keychain of its own).

Use a scratch data folder for every step below, so the owner's real folder is never touched:

```sh
DIR="$(mktemp -d /tmp/bb-021-status.XXXXXX)"
BRAINBUDDY_MAC_DATA_DIR="$DIR" .build/BrainBuddyMac.app/Contents/MacOS/BrainBuddyMac
```

(With the variable set, the app makes no Keychain call until you sign in; after that it uses the
real login keychain, so sign out at the end of the run.)

### 2. Sign-in (X-03; Scenario 6 step 2.3)

| # | Check | Expected |
|---|---|---|
| S1 | Account-less | Footer "On this Mac · Sign in to sync"; "On this Mac" opens X-02 with "Your tasks are stored on this Mac" and "Sign in…"; no times, no "Sync now". |
| S2 | First sign-in box | Add two tasks and a project "Garden" first. "Sign in to sync" opens X-03 with the sky box "Your tasks on this Mac will be added to your account. …"; focus in Email; "Sign in" disabled until both fields are filled. |
| S3 | Wrong password | "Check your email and password." in amber with a Reference ID; focus back in Password. |
| S4 | Offline | Wi-Fi off: "Can't reach the server. Check your connection." and "Signing in is the only thing that needs a connection. …", no Reference ID. Wi-Fi on. |
| S5 | No answer | Advanced › server `https://localhost:9` (a closed port): "Brain Buddy didn't answer. Try again." with a Reference ID. "Use the default server" restores the address. |
| S6 | Signing in… | Press "Sign in": fields read-only, "Signing in…" with the indicator; press Esc at once: the sheet stays, the typed values stay, focus in Password, nothing linked (footer unchanged). Sign in again and let it finish. |
| S7 | First load | The sheet closes with no toast; the footer reads "Not synced yet" (indicator after 1 s), then "Synced just now"; an empty list reads "Your tasks are still arriving." until the first load lands. |
| S8 | Merge (Scenario 6 step 2.3) | With "Garden" already on the account: one "Garden" on the web with the Mac's tasks; Waiting and Project review marks still present on the Mac. |
| S9 | Focus on close | After S7 the trailing "Sign in to sync" is gone: focus is on the status words. Open X-03 again from the app menu and Cancel: focus on the words. |
| S10 | Keychain item | Keychain Access › login shows an item `app.brainbuddy.mac.session` (record "Keychain item present: yes"). Copy the token's first 8 characters from Keychain Access ("Show password"; do not record them), then `grep -c "<those 8>" "$DIR"/store.json "$DIR"/mac-local.json` and `defaults read com.brainbuddy.mac.prototype | grep -c "<those 8>"`: record "token found in files: no" when every count is 0. Never paste the output or the characters. |
| S11 | Deletion cancelled | Only on a test account scheduled for deletion on the web: signing in shows "Your account deletion was cancelled" in the sheet with "OK" focused; Return or Esc closes it. Otherwise record "n/a". |

### 3. The status line in every state (Scenario 5 step 4; SC-004)

Keep a text field focused in the main window (the task draft) during this whole section, and
watch for any sheet, alert, notification, sound or focus change.

| # | State | How | Expected words |
|---|---|---|---|
| L1 | synced | wait | "Synced just now", later "Synced 1 min ago" (refreshes by itself) |
| L2 | syncing > 1 s | a large pull, or Network Link Conditioner "Very Bad Network" | the words unchanged; the small indicator in its slot, at least 0.5 s; nothing moves |
| L3 | waiting | Network Link Conditioner 100 % loss, add a task, wait 15 s | "Synced … · 1 change waiting" |
| L4 | offline | Wi-Fi off | "Offline · N changes waiting", calm slate; X-02 "Sync now" disabled |
| L5 | session ended | sign out on the web (revokes the session), then ⌘R | "Sign in again to sync" in amber with the person glyph, at once; the waiting changes kept |
| L6 | failing | with Wi-Fi on, make the server unreachable for more than 60 s: on a local test server stop it; otherwise point its host at a closed address in `/etc/hosts` (`sudo` edit, undo afterwards) | nothing for 60 s, then "Couldn't sync · Retry"; the tooltip has "Last tried …" and a Reference ID; "Retry" runs a sync and updates "Last tried" |
| L7 | rejected | on the web create an active "Old flat"; on the Mac (offline) unarchive the archived "Old flat", then go online | "1 change couldn't sync"; X-02 lists it with Copy and Dismiss |
| L8 | back to calm | undo each cause | "Synced just now"; nothing says "back online" |
| L9 | SC-004 | through L1 – L8 | no sheet, alert, notification or sound; focus never left the text field; the typed text is intact |

### 4. VoiceOver, keyboard, Reduce Motion, text size

| # | Check | Expected |
|---|---|---|
| A1 | X-01 name | VoiceOver reads "Sync status: Synced 3 min ago. Show details" (the words of the state); "Retry sync" for Retry; the indicator, when shown, "Syncing", not announced. |
| A2 | Announcements | Entering L5, L6 and L7 is announced once each; minutes ticking, syncing and waiting are not. |
| A3 | Keyboard | Tab reaches the status words, then the trailing action, as the last stops in the sidebar; Space or Return on the words opens X-02. |
| A4 | X-02 Tab order (three states) | Account-less: "Sign in…" focused on open. Offline with no issues: focus on the first enabled control, "Sync now" skipped (disabled), then "Sign out…". With a kept outcome (S8 with "Garden" having a desired outcome on both sides): issue Copy → "Copy outcome" → "Discard outcome" → Sync now → Sign out… → "Show in Finder" lines. Esc closes, focus back on the words. |
| A5 | Discard outcome | "Discard outcome" (VoiceOver: "Discard your outcome for “Garden”") shows "Outcome discarded · Undo" for 5 s, announced; Undo restores the row; after 5 s it goes. |
| A6 | Dismiss focus | With two issues, Dismiss the first: focus on the next issue's Copy; Dismiss the last: VoiceOver "No sync issues", focus on "Sync now" (or "Sign out…" when Sync now is disabled). |
| A7 | X-03 / X-04 / X-05 | VoiceOver reads the sheet's title, the error with its Reference ID (announced), the sign-out alert's text with "Cancel" as default; X-05 as in `manual-macos-upgrade.md`. |
| A8 | Reduce Motion | System Settings › Accessibility › Display › Reduce motion: the indicator is a static glyph. |
| A9 | Large sidebar text | System Settings › Appearance › Sidebar icon size Large and a narrow sidebar: "Synced yesterday · 1,284 changes waiting" wraps after " · ", never truncated. |
| A10 | Sidebar hidden | Collapse the sidebar during L5: a toolbar item "Sign in again to sync" with the glyph appears without taking focus and opens X-02; in calm states the toolbar shows nothing about sync. |

### 5. Incoming changes, cadence, menus (FR-009, FR-006)

| # | Check | Expected |
|---|---|---|
| C1 | Scroll, selection, focus | Scroll a long list, select a task, type in its editor; on the web rename another task in the same list. Within 60 s the rename shows; scroll position, selection and focus unchanged; the typed text kept. |
| C2 | Row under the pointer | Rest the pointer on a row; on the web move that task to another list. The row stays while the pointer is on it and moves when the pointer leaves. |
| C3 | Covered window | Cover Brain Buddy's window with another app's window, make that app frontmost; on the web add a task; uncover after 60 s: the task is there (it arrived while covered: check the footer's "Synced just now" at uncovering). |
| C4 | Open task detail | Open a task's detail; on the web add a subtask and a comment to it: both appear within 60 s. |
| C5 | ⌘R | ⌘R while typing in the draft runs a sync (indicator if > 1 s), keeps the text, opens no popover. File › "Sync now" is dimmed, never hidden, account-less, offline and with the session ended; enabled while a sync runs. |
| C6 | App menu | Account-less "Sign in…"; signed in "Sign out…"; session ended "Sign in again…" and "Sign out…". |
| C7 | Sleep and wake | Signed in, sleep the Mac for 5 minutes, change a task on the web, wake: within 60 s the change shows; no alert. |

### 6. Sign-out (X-04)

| # | Check | Expected |
|---|---|---|
| O1 | Unsaved edit first | With an unsaved task edit, "Sign out…": the window's "Discard unsaved changes?" first; "Keep editing" cancels the sign-out, the edit intact. |
| O2 | Count changed | Offline, add 3 tasks, "Sign out…": "3 changes haven't synced yet. … You're offline, so they can't be sent now."; take a quick capture (⌃⌥⇧B) without closing the alert if possible, otherwise between opening and confirming; "Sign out and remove": nothing signed out, the alert again with 4. Cancel. |
| O3 | Backup sentence | On a folder upgraded from a pre-021 store (`manual-macos-upgrade.md` step 4): the alert ends with "A copy of your tasks from before the update stays on this Mac until <date>." |
| O4 | Sign out | Confirm: the workspace is empty, selection Inbox, footer "On this Mac · Sign in to sync"; Keychain Access has no `app.brainbuddy.mac.session` item left (record yes/no); the web session list shows the Mac's session ended. |
| O5 | Later file after sign-out (Scenario 6 step 2.7) | Quit, run the pre-021 build once on the same folder and add a task, quit, launch the 021 build: X-05 "later file" if not yet seen (otherwise only the X-02 line), no import, the workspace still empty. |

### 7. Account switch, Keychain prompt, X-09

| # | Check | Expected |
|---|---|---|
| K1 | Account switch refused (US4-5) | Only on a local test server where an account can be deleted and created again with the same email (a new account id). Signed in as that account with a change waiting offline: delete the account and create it again on the server, go online ("Sign in again to sync"), then "Sign in again" with the new password: "Sign out first to use another account." / "Changes from the other account are still waiting on this Mac."; the sheet stays open; nothing reaches the new account. Without such a server record "n/a (covered by `MacSyncFlowTests`)". |
| K2 | Rebuild | Signed in, quit, `sh build_app.sh` again (ad-hoc signature changes), launch: no Keychain prompt; footer "Sign in again to sync". "Sign in again": no access prompt (only an unlock prompt, during the sheet, if the login keychain is locked); the sign-in succeeds and syncs. Keychain Access › login now shows two items of `app.brainbuddy.mac.session`, accounts `<host>` (the earlier build's) and `<host>#1` (record "new item beside the old: yes/no"). Quit and relaunch: still synced, no prompt. Sign out: `<host>#1` is gone and `<host>` stays (the app cannot delete it; record yes/no); deleting it in Keychain Access as the docs say works. |
| K3 | X-09 | Quit, write `garbage` into `$DIR/store.json`, relaunch: "We couldn't open your tasks"; no footer line, nothing sent; "Start fresh…" confirmation, then an empty workspace. |

At the end, sign out, remove any `app.brainbuddy.mac.session` item left in Keychain Access, and
delete `$DIR`.

## Results (owner fills in; leave blank until the run is done)

| Field | Value |
|---|---|
| Date of run | |
| Run by | |
| Commit SHA under test, tree hashes of `macos/`, `ios/BrainBuddyKit/`, `ios/BrainBuddy/` | |
| Mac model / chip, macOS, Xcode, Swift | |
| CI `macos-app` job URL, build and `Executed …` / `Test run with …` lines; "Keychain on macOS" ran (yes/no) | |
| Step 1 local build / test exit codes | |
| S1 – S11 (sign-in) | |
| Keychain item present (yes/no); token found in files (yes/no) | |
| L1 – L9 (status line, SC-004) | |
| A1 – A10 (VoiceOver, keyboard, Reduce Motion, text size, sidebar hidden) | |
| C1 – C7 (incoming changes, cadence, menus, sleep) | |
| O1 – O5 (sign-out) | |
| K1 – K3 (account switch, Keychain prompt, X-09) | |
| Notes / deviations | |

When every row is filled in and everything passes, change the status line at the top to
`PASS (owner run, <date>, <SHA>)`. If anything fails, set it to `FAIL` and name the check.

## Agent pre-check on Linux (not host evidence)

Recorded by the implementing agent on 2026-10-08.

- **Not compiled:** the `BrainBuddyMac` app target (SwiftUI, AppKit, WhisperKit, Network) cannot
  be built on Linux. Every Swift file under `macos/` passed `swiftc -parse -swift-version 6`
  (syntax only). The first type-check of the views (`SyncStatusLine`, `SyncStatusPopover`,
  `SignInSheet`, `SignOutConfirmation`, `SyncMenuCommands`, `SyncTriggerSource+Live`,
  `MacPresentationRouter+SwiftUI`, the `ContentView` and `BrainBuddyMacApp` changes) is the CI
  `macos-app` lane. `MacKeychainTests` is macOS-only and also runs there first.
- **Compiled and tested on Linux:** `BrainBuddyMacCore` and every other suite in
  `macos/Tests/BrainBuddyMacTests`, in a throwaway SwiftPM package outside the repository that
  copies those files verbatim and depends on the real kit (`swift:6.2-noble`, Swift 6 mode), with
  a minimal stand-in for CryptoKit. `MacPresentationGuardTests` and `MacPrivacyGuardTests` read the
  real `macos/Sources` of the worktree there. Result: see the PR description.
- **Kit:** `sh ios/scripts/swift-linux.sh test`: see the PR description.
