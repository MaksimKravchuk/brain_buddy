# Settings window and tab chrome correction — 2026-10-17

## Accepted outcome and scope

Match the Settings shell shared by the authoritative [M25](../../design/board/mac/M25-Mac.png) and [M29](../../design/board/mac/M29-Mac.png) PNGs: 820 × 620 pt outer default size, small native title above Account / Agents / Sync, warm native-material header, selected rounded rectangle, and no shared glass capsule. This is a bounded SHOW correction. The owner’s PNG-authority decision supersedes the old wording that let initial height simply follow tab content.

The existing native Settings declaration and its constraints are now shared with native scene tests through `MacSettingsScene`. `defaultSize(820,620)` fixes the initial geometry. The tab boxes are 70 × 50 pt; existing glyphs, fonts, 8 pt radius and semantic colors remain. `sharedBackgroundVisibility(.hidden)` removes only the toolbar item’s shared capsule. The header uses native regular material over existing `bg-ground`; no color was added. Existing window dimensions and the new tab dimensions live in one generated `layout.mac-settings` group.

Main-window chrome and commands, M29 body, M30 sheet, tab binding/order, accessible names/selected traits, request routing, sign-in/sign-out callbacks, authentication, API, persistence and workflows are untouched. No product AppKit frame-setting or activation-policy workaround was added.

## Native finding and comparison

- Before actual: [Before](../../design/evidence/mac-agents-board/after.png) — 1800 × 1016 pixels at native2x, or 900 × 508 pt. The header is white with a shared glass capsule, and the fixed 820 pt body sits inside 40 pt white side strips.
- After actual: [After](../../design/evidence/mac-settings-board/after.png) — 1640 × 1240 pixels, or 820 × 620 pt. Parent manual comparison accepted the header, selected rectangle, absent capsule and removed side strips. The full existing M29 body fits with accessible actions.
- The native probe showed **zero horizontal safe-area insets** and an 820 pt minimum width. The side strips came from the scene’s larger default width around its fixed-width content; they were not extra content padding. No negative padding or offset was needed.
- The existing 420 pt minimum is a **body** minimum. Native 88 pt title/toolbar chrome produces an observed 820 × 508 pt outer minimum. The correction preserves this constraint; it does not force an outer 420 pt window that would shrink existing content.
- Parent exercised Account → Agents → Sync → Account → Agents and confirmed distinct accessible names and selected traits. Closing Settings and reopening with Cmd-comma retained Agents. Existing request handlers and model behavior were unchanged.
- Native regular material is OS-dependent and slightly cooler than the board cream. The parent accepted the existing material and semantic backing; no invented color or further tint iteration was introduced.

The initial probe attempted offscreen placement, which macOS clamped before the test-owned window was ordered out. The retained regression fixes that harness: a test-only native view makes its own window transparent before display, immediately orders it out, then moves it offscreen. It changes no real app window, global appearance, activation policy or owner data.

## Verification

The actual production Scene is hosted through macOS 26 `NSHostingSceneRepresentation`, not a copied toolbar HStack. It asserts the full 820 × 620 default, full-width content, native minimum width and unchanged body minimum plus measured native chrome. Two reviewed native2x PNGs capture only the changed native header, in explicit light and dark appearances; body state coverage remains in existing Settings/M29 tests. The initial native probe failed at 900 × 508; the same accepted geometry passes after the scene correction.

| Check | Result | Local log |
| --- | --- | --- |
| Focused native header replay plus existing Settings contracts | PASS — 10 tests / 2 suites | `/private/tmp/bb-settings-focused-replay.log` |
| Complete native Mac suite | PASS — 459 tests / 49 suites, 71.872 seconds | `/private/tmp/bb-settings-full-mac.log` |
| Complete native kit suite after generated token change | PASS — 1508 tests / 154 suites, 55.570 seconds | `/private/tmp/bb-settings-full-kit.log` |
| Token generation, spec integrity and diff whitespace | PASS | `/private/tmp/bb-settings-final-spec-check.log` |

The record run intentionally emitted two snapshot-record issues before visual review and replay. No tolerance was weakened. Baselines: `macos/Tests/BrainBuddyMacTests/__Snapshots__/mac-settings-chrome-{light,dark}-native2x.png`. Only native2x was available locally; an actual native1x CI capture remains a parent-owned gate.

Prepared from `47c1d175645a565e15d31f86d794e090d16a20ab` on `codex/mac-settings-board`. Parent owns independent exact-SHA QA, CI, integration, push and delivery. This local evidence does not claim those gates or production acceptance have passed.
