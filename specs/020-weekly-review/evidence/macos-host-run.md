# Feature 020 — macOS host run for FR-041 (slice PR-06)

**Status: PENDING (owner run).** Nobody has run this on a macOS host yet. This file
is a template, not evidence. Do not treat it as a passing run, and do not accept
020-FR-041 on it, until the **Results** section below is filled in from a real run.

## What this run proves

- **020-FR-041** (spec.md): until Mac↔backend sync exists, the Mac app shows a
  non-interactive "Weekly review · coming later" entry and ships no local-only review.
- **Tasks**: T164 (RED `WeeklyReviewRowTests`) and T165 (GREEN `ContentView`, plus this
  recorded run), tasks.md slice PR-06; quickstart Scenario 6.
- **Why a host run is needed**: no CI lane builds or tests `macos/`. A test file under
  `macos/Tests` that names `020-FR-041` satisfies the name-matching coverage gate, but it
  only proves that a test exists. The plan ("Test strategy") requires this recorded run
  in addition to the name match.

## What changed (the run is checking this)

- `macos/Sources/BrainBuddyMac/SidebarEntries.swift` (new): the sidebar's fixed entries
  as a value with no UI framework: Lists, then the deferred Weekly review row in its own
  section without a header, then Dates and History. `DateDestination`,
  `WorkspaceDestination` and `HistoryState` moved here unchanged from `ContentView.swift`.
- `macos/Sources/BrainBuddyMac/ContentView.swift`: `sidebar(account:)` renders
  `SidebarEntries.standard`. The deferred row is plain static content, not a `Button`:
  icon, "Weekly review", trailing "coming later" in caption, secondary colour, one
  accessibility element labelled "Weekly review, coming later" with the static-text
  trait, `.selectionDisabled()`. Projects and Tags are unchanged.
- `macos/Tests/BrainBuddyMacTests/WeeklyReviewRowTests.swift` (new): 8 XCTest cases, all
  named `test_020_FR_041_…`.

## Owner steps on the Mac

Prerequisites: macOS 26 or later, Xcode with its command-line tools selected
(`xcode-select -p`), and for step 4 the local Whisper model and tokenizer that
`macos/build_app.sh` needs (see `macos/README.md`).

### 1. Check out the slice and record the host

```sh
cd <your brain_buddy clone>
git fetch origin
git switch --detach <SHA under test>      # the PR-06 commit; record it below
git rev-parse HEAD
sw_vers
xcodebuild -version
swift --version
```

### 2. Build the package

```sh
set -o pipefail          # so `$?` after `| tee` is the Swift exit code (zsh and bash)
cd macos
swift build 2>&1 | tee /tmp/bb-020-pr06-build.log
echo "build exit: $?"
```

In a restricted workspace, first set `CLANG_MODULE_CACHE_PATH` and
`SWIFT_MODULE_CACHE_PATH` to directories under `macos/.build` (`macos/README.md`).

### 3. Run the tests

```sh
# Same shell as step 2 (pipefail still set, still in macos/).
# The FR-041 tests on their own:
swift test --disable-sandbox --filter WeeklyReviewRowTests 2>&1 | tee /tmp/bb-020-pr06-row-tests.log
echo "row tests exit: $?"
# The whole macOS suite, to show the extraction broke nothing:
swift test --disable-sandbox 2>&1 | tee /tmp/bb-020-pr06-all-tests.log
echo "all tests exit: $?"
grep -E "Executed [0-9]+ tests" /tmp/bb-020-pr06-row-tests.log /tmp/bb-020-pr06-all-tests.log
```

Expect `Executed 8 tests, with 0 failures` for `WeeklyReviewRowTests` and 0 failures
for the whole suite.

### 4. Launch the app and look at the row

```sh
sh build_app.sh
open .build/BrainBuddyMac.app
```

The app opens on the local "On this Mac" workspace. Check each item and mark it
pass or fail in the Results table:

| # | Check | Expected |
|---|---|---|
| V1 | Position | The row sits directly under the four Lists rows (Inbox, Next actions, Waiting for, Someday), in its own group with no header, and above the Dates header. It is not inside Lists. |
| V2 | Copy | Left: the circular-arrow icon and "Weekly review". Right: "coming later" in smaller text. Both are in the secondary (dimmer) colour. Nothing else, and no count badge. |
| V3 | Click | Clicking the row does nothing: no highlight, the main pane stays on the current list, and no sheet or window opens. Clicking a list afterwards still works. |
| V4 | Keyboard | Moving through the sidebar with the keyboard (Tab / arrow keys) never selects or activates the row. |
| V5 | Context menu | Right-clicking the row shows no menu. |
| V6 | VoiceOver | With VoiceOver on (Cmd-F5), the row reads as one item, "Weekly review, coming later", announced as text, not as a "button", and not "dimmed". |
| V7 | Accessibility Inspector | Xcode › Open Developer Tool › Accessibility Inspector, pointed at the row: role is static text (`AXStaticText`), label "Weekly review, coming later", with no press action. |
| V8 | Narrow sidebar | Drag the sidebar to its narrowest width. The row truncates with an ellipsis like the other rows, and the layout does not break. |
| V9 | Appearance | Light and Dark mode both legible. |
| V10 | Regression | Inbox, Next actions, Waiting for, Someday, Overdue, Today, Upcoming, Completed and Cancelled still open their views, with the same icons, the selected-row highlight, and the list counts as before. Projects (including the Review button) and Tags are unchanged. |
| V11 | No local review | No sidebar entry, menu item or shortcut opens a weekly review. The existing POC "Review Waiting for" / "Review Someday" buttons and "Review projects" are pre-existing and out of scope. |

If you take screenshots, use a store with test data only, and do not commit
screenshots that show real tasks.

## Results (owner fills in; leave blank until the run is done)

| Field | Value |
|---|---|
| Date of run | |
| Run by | |
| Commit SHA under test (`git rev-parse HEAD`) | |
| Mac model / chip | |
| macOS version (`sw_vers`) | |
| Xcode version (`xcodebuild -version`) | |
| Swift version (`swift --version`) | |
| Step 2 `swift build` exit code | |
| Step 3 `WeeklyReviewRowTests` exit code and `Executed …` line | |
| Step 3 full `swift test --disable-sandbox` exit code and `Executed …` line | |
| V1 Position | |
| V2 Copy | |
| V3 Click | |
| V4 Keyboard | |
| V5 Context menu | |
| V6 VoiceOver | |
| V7 Accessibility Inspector | |
| V8 Narrow sidebar | |
| V9 Appearance | |
| V10 Regression | |
| V11 No local review | |
| Notes / deviations | |

When every row above is filled in and everything passes, change the status line at the
top to `PASS (owner run, <date>, <SHA>)`. If anything fails, set it to `FAIL` and say
which check.

## Agent pre-check on Linux (not host evidence)

Recorded by the implementing agent on 2026-10-06, so the owner knows what was and was
not exercised before the host run. None of it replaces the run above.

- **Full `macos/` package on Linux (`swift:6.2-noble` Docker image)**: `swift package
  dump-package` succeeds. `swift build` resolves the dependencies, then fails before it
  reaches `BrainBuddyMac`, because WhisperKit's `ArgmaxCore` imports `os.lock` ("no such
  module 'os.lock'"). The target also imports SwiftUI and AppKit, which do not exist on
  Linux. So no part of `macos/` builds or tests on Linux, and `ContentView.swift` was
  never type-checked.
- **Syntax only**: `swiftc -parse` on `ContentView.swift`, `SidebarEntries.swift` and
  `WeeklyReviewRowTests.swift` exits 0. That is a parse, not a type-check.
- **UI-free part in a scratch harness**: a throwaway SwiftPM package outside the
  repository held verbatim copies of `SidebarEntries.swift` and
  `WeeklyReviewRowTests.swift` (checked with `cmp`) and the `TaskList` enum (lines 1–25
  of `APIClient.swift`), with the library target named `BrainBuddyMac` so
  `@testable import BrainBuddyMac` resolves.
  - RED, before the row was added: 8 tests ran and 5 failed on assertions ("the sidebar
    has no Weekly review row"; sections `["lists", "dates", "history"]`).
  - GREEN: `Executed 8 tests, with 0 failures`. The same result with
    `-strict-concurrency=complete -warnings-as-errors`.
  - This exercises the Linux XCTest and Foundation, not the macOS ones, and not the
    package's own test target.
