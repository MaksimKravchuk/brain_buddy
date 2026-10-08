# Feature 021 — macOS upgrade, host run (slice PR-08, T113 – T114)

**Status: PENDING. Nothing below has been run on a Mac yet.** The implementing agent wrote
this plan on 2026-10-08 on Linux, where the Mac app cannot be built (see "Agent pre-check on
Linux" at the end).

- **Who runs it:** the owner, or the owner's agent on the owner's Mac.
- **Order matters:** run the CI lane (step 1), then the dry run on a copy of the real folder
  (step 2, quickstart Scenario 6 step 0). **The owner's own upgrade waits until step 2
  passes.** Only then run steps 3 – 8 from a real pre-021 build with test data.
- **What may be recorded here:** counts, "adjusted: N", "not carried: N", "bytes identical:
  yes/no", pass/fail. **Never** task titles, project or tag names, notes, the import report's
  content, the home folder path or screenshots of real data.
- **If a check fails:** stop, set the status to `FAIL (<step>)`, keep the folders as they are
  (nothing in them is deleted by the app), and the fix lands in a separate PR.
- **Acceptance:** 021-FR-020, 021-FR-021, 021-FR-022, 021-FR-033 and 021-SC-003 are not
  accepted on the Mac until the Results table is filled in from that run.

## What changed (the run is checking this)

- On the first launch after the update, `local-gtd.json` is carried into the kit's
  `store.json` (contracts/mac-legacy-import.md): read, planned as kit commands, written to
  `store.import-<attempt>.json`, verified against the original, then renamed into place with
  an exclusive rename. The original is renamed, unchanged, to `local-gtd.backup-<UTC>.json`.
  It is never edited or deleted.
- An unreadable or newer `local-gtd.json`, or a carry-over that does not verify, leaves the
  original exactly as it was and shows X-05 once; the workspace starts empty only after
  "Continue". A `local-gtd.json` that appears after the new workspace exists is never imported
  (FR-033): X-05 "later file", once.
- `mac-local.json` keeps the review marks, the import record and the Archived-projects
  disclosure state; `.instance.lock` keeps a second copy out (X-08).
- `BRAINBUDDY_MAC_DATA_DIR=<absolute folder>` points the app at a copy and leaves the
  cookies, the HTTP cache and the Keychain alone.

## Owner steps on the Mac

Prerequisites: macOS 26 or later, Xcode 26 with its command-line tools selected, the Whisper
model and tokenizer `macos/build_app.sh` needs (`macos/README.md`), and a pre-021 build of the
Mac app (any commit before 021 PR-08, for example `git switch --detach 9b58bc5` then
`sh macos/build_app.sh`; keep that `.app` as `BrainBuddyMac-pre021.app`).

### 1. CI lane and build on the exact SHA (T113)

The `macos-app` lane of `.github/workflows/ci.yml` runs on the PR head. Record its job URL,
the `swift build --only-use-versions-from-resolved-file` result and the `Executed … tests`
line. Then on the Mac:

```sh
cd <your brain_buddy clone>
git fetch origin
git switch --detach <SHA under test>
git rev-parse HEAD; sw_vers; xcodebuild -version; swift --version
set -o pipefail
cd macos
swift build --only-use-versions-from-resolved-file 2>&1 | tee /tmp/bb-021-pr08-build.log
echo "build exit: $?"
swift test --only-use-versions-from-resolved-file 2>&1 | tee /tmp/bb-021-pr08-test.log
echo "test exit: $?"
grep -E "Executed [0-9]+ tests|Test run with [0-9]+ tests" /tmp/bb-021-pr08-test.log
git status --porcelain Package.resolved    # expect no output: the pins were not rewritten
sh build_app.sh
```

Expect: build exit 0, test exit 0, Swift Testing "Test run with N tests … passed" and XCTest
"Executed 8 tests, with 0 failures", and `Package.resolved` unchanged.

### 2. Dry run on a copy of the owner's real folder (Scenario 6 step 0)

Quit the pre-021 app first. Do **not** sign in during the dry run.

```sh
REAL="$HOME/Library/Application Support/BrainBuddyMac"
COPY="$(mktemp -d /tmp/bb-dry-run.XXXXXX)"
cp -Rp "$REAL/." "$COPY/"
shasum -a 256 "$REAL/local-gtd.json"            # note it; do not record it here
BRAINBUDDY_MAC_DATA_DIR="$COPY" .build/BrainBuddyMac.app/Contents/MacOS/BrainBuddyMac
```

| # | Check | Expected |
|---|---|---|
| D1 | Notice | No X-05 alert, or only "Brain Buddy carried over your earlier tasks, except a few it couldn't read" with the reason understood. |
| D2 | Counts | Open, completed and cancelled tasks, projects (active and archived), tags, subtasks and comments in the window equal the old app's counts. Count in the old app first. |
| D3 | Footer | "On this Mac · Sign in to sync". |
| D4 | Files in the copy | `store.json`, `mac-local.json`, `local-gtd.backup-<UTC>.json`; no `local-gtd.json`, no `store.import-*.json`. `shasum -a 256` of the backup equals the original's: record "bytes identical: yes/no" only. |
| D5 | Import report | If `local-gtd.import-report-*.txt` exists, the owner reads it on the Mac; record "adjusted: N" and "not carried: N" only. Do not copy it anywhere. |
| D6 | Real folder untouched | `shasum -a 256 "$REAL/local-gtd.json"` is unchanged and `$REAL` has no `store.json`. |
| D7 | Nothing else touched | Keychain Access shows no new `app.brainbuddy.mac.session` item; the old cookies are still there (`ls ~/Library/HTTPStorages/com.brainbuddy.mac.prototype*`). |
| D8 | Bad variable | `BRAINBUDDY_MAC_DATA_DIR=relative/path` (or a folder that does not exist) shows "Brain Buddy couldn't start" and quits; nothing is created anywhere. |

Delete `$COPY` when done. **Only if D1 – D8 pass**, go on.

### 3. Prepare a pre-021 store with test data (Scenario 6 step 2.1)

Use a scratch macOS user, or move the real folder aside first and restore it at the end:
`mv "$REAL" "$REAL.owner-kept"`. With `BrainBuddyMac-pre021.app`, create the design's
example data (spec design "Example data used in every mockup"): an archived project "Old flat"
with three open tasks, an active project with a desired outcome, Waiting items with a reason,
Someday items, a Project review and Keep-waiting marks, subtasks in three states, an edited
comment, a completed and a cancelled task, the project "Квартира №5", and the tags "@home" and
"home". Quit it.

### 4. Upgrade (Scenario 6 steps 2.2 and 2.8)

Launch the 021 build normally (no variable).

| # | Check | Expected |
|---|---|---|
| U1 | Notice | None. |
| U2 | Records | Every record present, same counts as in the old app; "Old flat" under "Archived projects · 1" with its three tasks; outcomes, subtasks and comments as before. |
| U3 | Footer | "On this Mac · Sign in to sync". |
| U4 | Backup | `local-gtd.backup-<UTC>.json` beside `store.json`; "bytes identical: yes" against a copy taken before the launch. |
| U5 | Old names (2.8) | "Квартира No5", "home" and "home (2)"; `local-gtd.import-report-<UTC>.txt` lists the three adjustments. Record "adjusted: 3" (or the number seen). |
| U6 | Review marks | Items marked "Keep waiting" in the old app are not due in "Review Waiting for"; a reviewed project is not in "Review projects". |
| U7 | Second launch | Quit and relaunch: no notice, nothing imported again, same counts. |

### 5. Corrupt and newer files (Scenario 6 step 2.4)

On a fresh folder each time (`BRAINBUDDY_MAC_DATA_DIR` set to an empty scratch folder):

1. Copy a pre-021 `local-gtd.json` into it, truncate the copy
   (`head -c 200 local-gtd.json > x && mv x local-gtd.json`), note its `shasum`, launch.
   **Expect** X-05 "Brain Buddy couldn't read your earlier tasks", the path selectable, "Continue"
   focused, Escape does nothing, Return continues; after "Continue" an empty workspace; the file's
   `shasum` unchanged; no `store.json` until the first change; no staging file.
2. Same with `"version": 2` in the file's header. **Expect** the "newer version" copy.
3. End the app while the alert is open (`killall BrainBuddyMac` from Terminal), relaunch.
   **Expect** the alert again.
4. "Show in Finder" reveals `local-gtd.json` and closes the alert.

### 5a. The import cannot finish (E7.1 invariant 4)

On a fresh scratch folder holding a pre-021 `local-gtd.json` (note its `shasum -a 256`), make
the folder refuse writes, then launch with the variable set:

```sh
touch "$DIR/.instance.lock"   # the single-instance lock must exist, or the launch stops earlier
chmod 555 "$DIR"
BRAINBUDDY_MAC_DATA_DIR="$DIR" .build/BrainBuddyMac.app/Contents/MacOS/BrainBuddyMac
```

| # | Check | Expected |
|---|---|---|
| I1 | Panel | "Brain Buddy couldn't finish the update" / "Brain Buddy couldn't carry over your tasks from the previous version, so it hasn't opened anything yet. The file from the previous version was left exactly as it was." / "Make sure your Mac has free space, then try again."; no lists, no sidebar, no "Start fresh"; "Try again" focused and the default. |
| I2 | Nothing changed | `local-gtd.json` has the same `shasum`; no `store.json` and no `store.import-*.json` in the folder. |
| I3 | Still failing | "Try again" while the folder is still read-only: the button reads "Trying again…", then the panel stays. |
| I4 | Recovery | `chmod 700 "$DIR"`, then "Try again": the workspace opens with every record (same counts as the old app), no notice; the folder holds `store.json` and `local-gtd.backup-<UTC>.json` ("bytes identical: yes"). |
| I5 | Quit instead | Repeat I1, quit, `chmod 700 "$DIR"`, relaunch: the import runs at launch, as in I4. |

### 6. A previous-version file comes back (Scenario 6 steps 2.5 and 2.6)

After step 4, note `shasum` of `store.json`, quit, launch `BrainBuddyMac-pre021.app` once and
add one task (it writes a new `local-gtd.json`), quit it, then launch the 021 build.

| # | Check | Expected |
|---|---|---|
| L1 | Notice | X-05 "Brain Buddy found tasks from the previous version", once. |
| L2 | Workspace | Same task count; `store.json` "bytes identical: yes" before and after the launch. |
| L3 | File | The new `local-gtd.json` left in place, unchanged. |
| L4 | Second launch | No notice. |
| L5 | Without the sidecar (2.6) | Quit, delete `mac-local.json`, put the pre-021 file back if needed, relaunch: the same notice once, and no import. |

(The X-02 quiet line and the sign-out steps 2.3 and 2.7 need sign-in, which arrives in PR-09.)

### 7. Unreadable `store.json` (X-09)

With a scratch folder, write `garbage` into `store.json` and launch with the variable set.

| # | Check | Expected |
|---|---|---|
| X1 | Panel | "We couldn't open your tasks" / "Your tasks are still on this Mac and nothing was changed." plus the reason; no lists, no footer; "Try again" focused. |
| X2 | Try again | Reads "Trying again…" while it runs; the panel stays; the file is unchanged. |
| X3 | Start fresh… | Confirmation "Set the file aside and start fresh?"; Return and Escape both mean "Keep trying". |
| X4 | Confirm | "Set aside and start fresh" opens an empty workspace; `store.unreadable-<UTC>.json` holds the old bytes. |
| X5 | No import | Put a pre-021 `local-gtd.json` into the folder and relaunch: X-05 "later file", nothing imported. |

### 8. Two copies (Scenario 8)

1. Open the bundled app twice from Finder (or `open -n`). **Expect** the first window comes
   forward and the second copy exits without any alert.
2. With the bundled app open, run `swift run BrainBuddyMac` in `macos/`. **Expect** the bundled
   app's window comes forward and the `swift run` copy exits. (The lock names the running
   process, so it can be brought forward; see "Deviation" below.)
3. X-08 "unreachable": quit Brain Buddy, hold the lock from another process, then launch:
   ```sh
   python3 -c 'import fcntl,time,sys; f=open(sys.argv[1],"a"); fcntl.flock(f,fcntl.LOCK_EX); time.sleep(120)' \
     "$HOME/Library/Application Support/BrainBuddyMac/.instance.lock" &
   open .build/BrainBuddyMac.app
   ```
   **Expect** the alert "Brain Buddy is already open." / "Switch to the open window to keep
   working." with one default button "OK", then the copy exits and nothing in the folder
   changed.

Restore the real folder at the end if it was moved aside (`mv "$REAL.owner-kept" "$REAL"`).

**Deviation from quickstart Scenario 8 step 2:** the quickstart expects the X-08 alert when a
`swift run` copy starts while the bundled app is open. Research R6 looks the other copy up by
bundle id, which finds the bundled app in that case too, so the step's expectation did not
follow from R6 either. The build records the owner's process id in `.instance.lock` and brings
exactly that process forward, falling back to R6's bundle-id lookup; step 8.3 reaches
"unreachable" deliberately.

## Results (owner fills in; leave blank until the run is done)

| Field | Value |
|---|---|
| Date of run | |
| Run by | |
| Commit SHA under test | |
| Mac model / chip, macOS, Xcode, Swift | |
| CI `macos-app` job URL, build and `Executed …` / `Test run with …` lines | |
| Step 1 local build / test exit codes; `Package.resolved` unchanged (yes/no) | |
| D1 – D8 (dry run) | |
| Dry run counts: tasks / projects / tags / subtasks / comments (old app = new app: yes/no) | |
| Dry run: adjusted N, not carried N, backup bytes identical (yes/no) | |
| U1 – U7 (upgrade) | |
| Upgrade: adjusted N, not carried N, backup bytes identical (yes/no) | |
| Step 5 (corrupt, newer, interrupted, Show in Finder) | |
| I1 – I5 (import cannot finish) | |
| L1 – L5 (later file) | |
| X1 – X5 (unreadable store) | |
| Scenario 8 steps 1 – 3 | |
| Notes / deviations | |

When every row is filled in and everything passes, change the status line at the top to
`PASS (owner run, <date>, <SHA>)`. If anything fails, set it to `FAIL` and name the check.

## Agent pre-check on Linux (not host evidence)

Recorded by the implementing agent on 2026-10-08.

- **Not compiled:** the `BrainBuddyMac` app target (SwiftUI, AppKit, WhisperKit) cannot be
  built on Linux. Every changed Swift file under `macos/` passed `swiftc -parse
  -swift-version 6` (syntax only). The first type-check of the views is the CI `macos-app`
  lane.
- **Compiled and tested on Linux:** `BrainBuddyMacCore` and every suite in
  `macos/Tests/BrainBuddyMacTests` (they all import only the core), in a throwaway SwiftPM package outside the repository that copies those files verbatim and
  depends on the real kit (`swift:6.2-noble`, Swift 6 mode), with a minimal stand-in for
  CryptoKit's `HMAC<SHA256>`/`SHA256` (CryptoKit does not exist on Linux). Result: "Test run
  with 78 tests in 7 suites passed" and XCTest "Executed 8 tests, with 0 failures". The
  importer's golden file was produced there; on macOS `LegacyStoreImporterTests` compares the
  importer's output with it byte for byte, so a macOS-only difference in JSON encoding would
  show up as that test failing.
- **Kit:** `sh ios/scripts/swift-linux.sh test`: "Test run with 992 tests in 95 suites passed".
