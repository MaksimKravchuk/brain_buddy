# Feature 030 — PR-12 snapshots and macOS host run

**Status: FAIL for keyboard acceptance (030-SC-008); snapshot acceptance is incomplete.**

This is a separate record for the owner's PR-12 test plan, not an extension of the
028/029/030 retest report. Product fixes are deliberately outside this PR.

## Imported plan and scope

The owner requested executing `pr-12-codex-brief.md` on a fresh Mac build on
2026-10-17. The updated attachment's SHA-256 is
`8835b546c9436685325c5d2ac51697b322324e7bc89a2517a2a80fdce33b5049`.
The imported acceptance inventory is:

- T033: light/dark renders for G-01.03, G-02.01, G-03.01, G-04.02, G-04.03,
  G-05.01, G-05.06, G-05.08, G-05.09, G-06.01, G-06.04 and G-07.01.
- T034: full Mac tests, shared API/agents tests, a real launch with a synthetic
  account and two free local agents, per-action keyboard results in both appearances,
  accessibility names, the stop-only A-17 regression, and cleanup.
- The updated plan assigns comparison with board `1792138611-15e1`, cells
  M21–M24/M29/M30, to Claude on the PR. This run compares against `design.md` only;
  it does not claim board approval. A spoken VoiceOver pass is explicitly not required.

Accepted outcome: preserve actual passes and failures with the tested build identity.
Non-goals: product changes, paid provider calls, `/verify-live`, production mutations,
GitHub settings, or using the owner's account/data. Only tests, renders and this evidence
file change. The earlier results report remains separate.

## Host and artifact identity

| Field | Observed value |
| --- | --- |
| Date / operator | 2026-10-17 / Codex on the owner's Mac |
| Product source SHA | `72a57a9827eeb00cd3045d8afd76a81aa46e66f3` — current `origin/main` when this run started |
| Mac / chip | Mac16,12 / Apple M4 |
| macOS | 26.5.2 (25F84), arm64 |
| Xcode | 26.6 (17F113) |
| Swift | Apple Swift 6.3.3, arm64-apple-macosx26.0 |
| App | Fresh `macos/.build/BrainBuddyMac.app`, built with `build_app.sh` |
| Executable SHA-256 | `6586314df9719d5cff16621b998c556e9a8654a0becd1c8a394c2eb2f1ddb42d` |
| Distribution boundary | No downloadable GitHub app release was listed. Source was fetched and the app was built locally. This is not evidence of a published/notarized Mac release. |
| Personal installed copy | Not replaced; no real-account sign-in or real workspace was used |

The app build used `RUSTUP_TOOLCHAIN=1.99.0 BB_APPLE_TARGETS=aarch64-apple-darwin sh build_app.sh`.
Build exit was 0; `codesign --verify --deep --strict` passed. Existing local Whisper
assets were bundled. Tests/renders added later do not change this product executable.

## Automated checks

Commands used `--disable-sandbox --only-use-versions-from-resolved-file`, with module
caches under each package's `.build`; full logs are retained locally under the private
`bb-pr12-host` scratch folder. No runtime fixture logs are retained.

| Check | Result |
| --- | --- |
| Full `macos/` `swift test` on product source SHA | PASS: 446 Swift Testing tests in 46 suites, plus 8 XCTest tests, 0 failures |
| Full Mac suite after first three snapshot states (`ad388d51`) | PASS: 449 Swift Testing tests in 47 suites, plus 8 XCTest tests, 0 failures |
| Shared kit `swift test --filter 'BrainBuddyAPI\|BrainBuddyAgents'` | PASS: 197 tests in 22 suites, 0 failures |
| Separate `BrainBuddyAgents` target | N/A: no such target exists; agents endpoint tests are in `BrainBuddyAPITests` and were included |
| Opt-in Mac pilot rehearsal | SKIPPED by its existing opt-in condition; not a passing live rehearsal and outside this PR-12 host journey |
| Snapshot replay on normal host | PASS: final 6 tests / 12 light-dark cases, 10.355 s; full-state limitations are listed below |
| Full Mac suite with final normal-host baselines (`84913c60` in the isolated worktree) | PASS: 452 Swift Testing tests in 47 suites, plus 8 XCTest tests, 0 failures, 44.395 s |
| Spec Kit / whitespace | PASS: `python3 scripts/check_spec_kit_specs.py` and `git diff --check` |

The default SwiftPM `Executed 0 tests`/XCTest summary alone is not the Swift Testing
result; the counts above come from the final Swift Testing lines as well.

## Integration base after the host run

While the run was in progress, main advanced to
`c867ad0f091e39f92f84de01c030c8a16e32d128` with the BrainBuddyAgents package extraction.
The evidence/test PR was rebased onto that main. The manual results above remain tied
to the original product/app SHA, not relabelled as a manual pass for the new build.
The backend sources did not change between those bases. Rebased Mac/package tests are
separate integration evidence; the new BrainBuddyAgents test target is now applicable.

Independent review found a locale-specific `Today 10:21` assertion in the new tests.
It now derives the expected time using the same Foundation format as the shipped view;
no locale preference is changed. This fixes the assertion, but does not make the captured
manager date strings locale-independent. Final CI must verify the baselines on its host.

## Real app setup

The app was launched with both `BRAINBUDDY_MAC_DATA_DIR` and `CFFIXED_USER_HOME`
pointing to an owned scratch profile. The backend used its own scratch data directory,
with dotenv loading disabled and provider credentials removed from its child environment.
`external_agent_relay` was `SELECTED_USERS` for the synthetic account only. The backend
and fixtures listened only on loopback. No owner or production account was used.

The two free fixtures were the vendored Helloworld (9999) and Hermes stub (9900).
Hermes used an 8-second scripted reply delay to exercise Running, Needs you and completion.
Two additional throwaway connections to the same Helloworld process exercised Add and test
in Light and Dark; these were not additional remote agents. Fixture preparation through
local APIs is setup evidence, not a successful GUI journey.

The fresh app signed in to the local backend without a Keychain prompt. A restart of the
scratch profile required sign-in again because the dry-run token store intentionally stays
unopened until explicit sign-in; this does not establish normal installed-session persistence.

Keyboard navigation was initially Off, temporarily turned On through System Settings,
and restored Off after the run. The original appearance was Auto; Light and Dark were
both exercised and Auto was restored. VoiceOver remained Off throughout.

An initial relative-path process launch caused UI-control failures (`noWindowsAvailable`
and dropped keys). It was quit, relaunched with its absolute executable path, and affected
checks were repeated. Those tooling failures are not classified as product failures.

## Keyboard results — one action per row

A PASS below applies to the named control/action. Some inspector controls were first
focused with the pointer after the normal Tab route became trapped in the notes editor.
Those explicitly marked setup-assisted passes do **not** establish an end-to-end
keyboard-only story. The complete 030-SC-008 journey is FAIL.

| Action | Light | Dark | Observed result / acceptance boundary |
| --- | --- | --- | --- |
| US1: select an open step with Quick Open | PASS | PASS | Command-O, task title, Return selected the synthetic step. |
| US1: reach Hand off through the required keyboard entry | FAIL | FAIL | No Hand off menu command/shortcut was exposed. From the task title, Tab enters Why; further Tab inserts tab characters rather than reaching Hand off. Synthetic tab characters were removed. |
| US1: arrow between agents | FAIL | FAIL | Initial focus was Cancel, not the selected agent. Down did not change selection. With an agent button focused, Up also did not change to the other agent. Tab/Space was the working alternative. |
| US1: Return sends an enabled hand-off | PASS | PASS | Observed successful dispatches to the local Helloworld. Opening the sheet was setup-assisted. |
| US1: Escape cancels hand-off | PASS | PASS | Returned to the main window without sending. |
| US1: at most three interactions, no password | FAIL | FAIL | The accepted keyboard entry is unavailable, so the promised complete keyboard route cannot meet the bound. The first best-effort fixture path needed entry, Shift-Tab, Space acknowledgement and Return even with default agent selected (4 actions, pointer-assisted entry). No password was requested. |
| US2: reach All runs from the sidebar by keyboard | FAIL | FAIL | Sidebar held focus, but Down did not select/open an agent destination. Pointer navigation worked; that does not satisfy the keyboard criterion. |
| US2: reach individual sidebar agents by keyboard | FAIL | FAIL | Same sidebar keyboard obstruction; visible rows had accessible names. |
| US2: Tab to an All runs run row | PASS | PASS | A run row received keyboard focus after the canvas was opened with the pointer. |
| US2: Return opens focused run row | FAIL | FAIL | Return left the canvas unchanged with the same row focused. |
| US2: Space opens focused run row | PASS | PASS | Inspector opened for the selected synthetic step. This is a working alternative, not the specified Return behavior. |
| US3: type Your answer | PASS | PASS | Setup-assisted initial field focus; entered synthetic answers only. |
| US3: Tab reaches Reply | PASS | PASS | Reply became enabled and received focus. |
| US3: Tab reaches Stop run | PASS | PASS | Stop run received focus; cancellation was not submitted in this check. |
| US3: activate Reply with keyboard | PASS | PASS | Shift-Tab to Reply, Space; observed subsequent completed result from the free Hermes stub. |
| US4: type Make the next step | PASS | PASS | Setup-assisted field focus; synthetic next-step titles only. |
| US4: Tab to Mark step done and activate | PASS | PASS | Original step became completed and the named next step appeared in Next actions. |
| US4: Tab to Hand off again and activate | PASS | PASS | Opened the hand-off sheet for the same step. |
| US5: keyboard opens Settings | PASS | PASS | Command-comma opened Settings. Agents tab was then used for the following actions. |
| US5: Tab reaches Add agent and Space opens | PASS | PASS | Empty sheet appeared with disabled Add and test. |
| US5: Escape cancels Add agent | PASS | PASS | Returned to Agents with no connection created by the cancelled sheet. Light was separately repeated in a fresh synthetic profile before final cleanup. |
| US5: Return submits filled Add agent | PASS | PASS | Keyboard-filled synthetic local connection was added and Tested ready. |
| US5: keyboard reaches/activates Test again | PASS | PASS | Connection returned Tested ready after a real local probe. |
| US5: keyboard opens/cancels Replace credential | PASS | PASS | Named secure fields and Cancel/disabled Replace exposed. No credential rotation submitted. |
| US5: keyboard opens/cancels Edit | PASS | PASS | Name, Address, credential type and Save exposed. |
| US5: keyboard opens/cancels Delete | PASS | PASS | Correct synthetic connection named, current-password field, Cancel/default-safe behavior. No deletion submitted through this dialog. |
| US5: arrows select settings agent | NOT RETESTED | FAIL | Dark arrow key left focus/selection unchanged; Tab/Space worked. Earlier Light attempts preceded the UI-tool restart and are not sufficient evidence. |
| US5: every control has a visible focus ring | NOT ESTABLISHED | NOT ESTABLISHED | Button outlines were observed (including Cancel and Edit). Add fields showed a caret, without a complete focus outline in the captured state. A universal ring pass is not claimed. |

## Accessibility and visual observations

- **Accessible names: PASS on inspected controls**, Light and Dark. Hand-off agent buttons,
  acknowledgement, Send/Cancel, All runs and per-agent entries, run rows, Your answer,
  Reply/Stop run, Make the next step, Mark step done/Hand off again, settings tabs,
  agent management buttons and sheet fields all exposed names through the accessibility tree.
  Standard window chrome and structural scroll containers are not counted as application controls.
- **State words: PASS.** Running, Needs you, Agent reported complete, Tested ready and
  Unreachable were exposed as words; group/run counts were also named. This is not a
  VoiceOver speech-quality result.
- **Waiting for composition: PASS in the live fixture.** The header was `0 people, 1 agent`;
  Agents preceded People and the run row named its task, agent and state. This live fixture
  does not prove the exact `2 people, 4 agents` snapshot state.
- **Settings layout: FAIL, both appearances.** At the shipped settings width, Test again
  wrapped over two lines and Replace credential… over several very short lines, visibly
  extending beyond its pill. Edit had a visible focus outline. No product fix was made.
- The first ImageRenderer-only snapshots omitted native scroll-list rows and showed
  yellow/red field placeholders. The live app did show agent rows and normal input fields;
  therefore these omissions/placeholders were not classified as a product regression.
  Final snapshot-host status is recorded below.

## Stopped-agent regression (A-17 / #510)

**PASS — stop only, routing, and recovery.** Both verified fixture processes were stopped
while their connections were still Tested ready. Without any prior Test again, opening
Hand off performed fresh probes, offered no agent and showed:
`No agent is ready to receive a hand-off.` There was no Send button. Shift-Tab/Space
on Open Settings… opened Settings with Agents selected, showing Unreachable connections.
Both fixture processes were restarted and Test again returned each primary connection to
Tested ready. This supersedes the earlier stop-only failure on the older installed build.

## Snapshot inventory and remaining acceptance

Six parameterized tests record **12 PNGs** (Light and Dark for each test). Recording
used `CARRY_ON_SNAPSHOT_RECORD=1 swift test --filter AgentsSnapshotTests` with the same
sandbox/cache flags; the helper deliberately reports issues while writing new baselines,
so recording exits nonzero. Replay without that variable passed **6 tests / 12 appearance
cases** in 10.355 s in the isolated snapshot worktree on the normal graphics host. The shared `assertMacSnapshot`
compares pixels; an offscreen `NSHostingView` inside this test file captures real native
scroll content and fields before handing its unmodified bitmap to that assertion.
No product file or shared snapshot support file changed.

A normal-host full run first failed all 12 new appearance comparisons against baselines
recorded in a restricted process, while the existing tests passed. A normal-host filtered
run reproduced the same differences, isolating the recording environment rather than
suite ordering. The same worker binary/cache also reproduced those differences when
run outside the process sandbox. Restricted rendering produced a different text raster;
final baselines must therefore be recorded and replayed on the normal macOS graphics
host. No channel tolerance or pixel-comparison gate was relaxed.

| Required state | Evidence | Acceptance result |
| --- | --- | --- |
| G-01.03 sidebar | `mac-agents-sidebar-components-{light,dark}.png` | PARTIAL: shipped row-component composition, with names/counts/Stale. It does not capture the full sidebar/canvas or its Add new agent toolbar button. |
| G-02.01 All runs | `mac-agents-all-runs-{light,dark}.png` | Real shipped canvas: title, 5 runs, five groups in required order and populated rows. Clipped subtitles and colour issue below prevent claiming full visual acceptance. |
| G-03.01 Waiting for | `mac-agents-waiting-components-{light,dark}.png` | PARTIAL: shipped component composition with 2 people, 4 agents and Agents before People; not a full WorkspaceView scene. |
| G-04.02 ready hand-off | No baseline | BLOCKED: initializer constructs live client/system token store and owns private flow state. |
| G-04.03 password hand-off | No baseline | BLOCKED: same private flow boundary. |
| G-05.01 Needs you run | No baseline | BLOCKED: initializer constructs live client/system token store and owns private section state. |
| G-05.06 completed run | No baseline | BLOCKED: same private section boundary. |
| G-05.08 Failed run | No baseline | BLOCKED: same private section boundary. |
| G-05.09 stopped reporting | No baseline | BLOCKED: same private section boundary. |
| G-06.01 loaded Agents | `mac-agents-settings-ready-{light,dark}.png` | Real manager, all three agent rows and details visible. Wrapping is a product layout FAIL; last-contact wording differs for the fixed-date fixture. |
| G-06.04 passwordless | `mac-agents-settings-passwordless-{light,dark}.png` | Real read-only manager with the required set-password notice; board approval pending. |
| G-07.01 empty Add | `mac-agents-add-empty-{light,dark}.png` | Real editor fields, types, helpers and disabled Add and test; board approval pending. |

The missing-state boundary is concrete: `HandoffSheet.swift` creates
`BrainBuddyAPIClient(... WorkspaceHost.systemTokenStore())` and private `@State HandoffFlow`
in its initializer; `AgentRunSection.swift` does the same for private
`@State AgentRunSectionModel`. There is no existing injected flow initializer. Rendering
ready/failed states through those constructors would access real Keychain/network, which
is excluded from fake snapshot tests. This PR does not add product seams or claim that
six absent baselines passed. G-01/G-03 component compositions likewise do not close full-scene acceptance.

Additional `design.md` differences / limits, for review:

1. Settings action labels wrap severely, also observed in the live app. The offscreen
   native host now faithfully captures the list and fields; earlier renderer omissions
   were removed from the final PNGs.
2. The fixed fixture is October 16 at 10:21. `AgentDetailsView` uses its real default
   `Date()` inside the shipped manager, so the capture says `Oct 16 10:21`, not
   `Today 10:21`. This is a missing clock-injection seam/fixture limitation, not evidence
   that a real last contact today is dated incorrectly.
3. `AgentRunsCanvas` also calls `Date()` in shipped rows. Its fake run timestamps are
   anchored to a captured wall clock for stable `4 min`/`2 days`; the model clock and
   component fixtures stay fixed. Thus this is not a completely frozen-clock scene.
4. Five All runs columns at the captured width truncate several subtitles. The required
   group words remain visible; full expected subtitle wording is not visually established.
5. **Colour-role FAIL on the canvas:** the stopped-reporting subtitle goes through
   `.macRowMeta()` (secondary), instead of the warning role required for lost contact.
   The waiting-row `tone` mapping does use accent/warning/danger/secondary roles, as does
   the run-section mapping; the canvas card does not apply that tone. No custom colours
   were introduced by these tests. Failed run-section visual acceptance remains blocked.

A green replay is pixel stability, not board approval or proof that the acceptance
inventory is complete. Claude's board comparison remains pending on the PR.

## Cleanup and privacy (030-SC-005)

**PASS for the created runtime fixtures.** The synthetic account was signed out through
the app; the backend recorded its Mac logout with HTTP 204 and the app showed
`On this Mac · Sign in to sync` with zero open tasks. The test app was then quit.
Only owned fixture listeners (verified by command/working-directory identity) were stopped.
Their backend data, app profile, agent homes, setup scripts and runtime logs were deleted.
A final Light Add/Escape check used a second fresh synthetic profile; it too signed out (HTTP 204), quit and had its backend/profile/logs removed. No runtime secrets or run payload files/logs were retained. Retained Swift/build logs and
this content-free record are test evidence; committed renders contain only intentional
synthetic design fixtures. The existing installed app and personal data were not replaced.
Original Auto/keyboard-navigation Off were read back after restoration; VoiceOver was not enabled.

## Delivery boundary

This report deliberately contains FAIL rows. It does not accept T033/T034, 030-SC-008 or
030-SC-009 as complete, and does not authorize product fixes, merge or production deployment.
The PR is a reviewable evidence/snapshot change; exact-head CI and Claude's board comparison
must be evaluated separately from these manual failures.
