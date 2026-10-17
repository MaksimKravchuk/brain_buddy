# Mac fix loop for a local agent (Codex)

How an agent running on the owner's Mac finds a visual or keyboard bug in the Mac app, fixes it
and opens a PR. It complements `manual-mac-tests-028-029-030.md`, which is check-only; here the
agent changes product code, one bug per PR.

## 0. Rules

1. **Synthetic data only.** Scratch data folder (`BRAINBUDDY_MAC_DATA_DIR`), local test server,
   throwaway `@example.com` accounts. Never the owner's real account or the real app's
   `~/Library/Application Support/BrainBuddyMac/`.
2. **Never run `/verify-live`** and make no paid provider calls. The test agents are local and free.
3. **The board decides how it looks.** Compare against `docs/design/board/mac/` (index in its
   `README.md`). Use only existing design tokens and `BrainBuddyDesign` components; never type a
   hex, size or radius into a screen and never invent a colour, word or behaviour the board and the
   spec do not show. If the board and the spec disagree, or a fix would need a new behaviour, stop
   and write it in the PR as a question instead of choosing.
4. **Do not touch** `.github/workflows/**`, `fly*.toml`, deploy files, `.claude/settings.json`, the
   `Makefile`, anything listed in `GUARDED_FILES` in `scripts/check_gate_integrity.py`, or any
   GitHub repository setting. Those need the owner.
5. **Content-free reports:** no tokens, keychain output, home paths or real emails in a PR or log.

## 1. Run the app

Do §§ 1.1–1.5 of `manual-mac-tests-028-029-030.md`: toolchain, `swift build`, `swift test`,
`sh build_app.sh`, the app on a scratch folder, the local backend with Account A and the
`external_agent_relay` flag, the two local test agents and the three test steps.

Without the backend the app still runs offline (first run, lists, inspector, capture); start the
backend only for Settings › Account (028) and agents (030).

## 2. Find a bug

Work screen by screen through the board index. For each screen:

1. Bring the app to the same state as the board cell (same list, same selected step, same sheet).
   Use the board's sample words where the app lets you type them.
2. Take a window screenshot: `screencapture -l <window id> -o shot.png`
   (window id from `osascript -e 'tell app "System Events" to get id of window 1 of process "BrainBuddyMac"'`,
   or `screencapture -i -w`).
3. Compare with the board PNG for layout, spacing, type, colour role, words and what is shown or
   hidden. Data differences (counts, dates, names) are not bugs.
4. Then check the keyboard on that screen: Tab and Shift-Tab order, arrows in lists, Return on a
   row, Esc on sheets, the menu shortcuts the board shows (⌘N, ⌘O, ⌘R, …).

Write each finding down before fixing anything: screen number, what the board shows, what the app
shows, both images.

## 3. Fix it

- Find the view: the Mac app is `macos/Sources/BrainBuddyMac/`; shared agent models are in
  `ios/BrainBuddyKit/Sources/BrainBuddyAgents/` (re-exported by
  `macos/Sources/BrainBuddyMacCore/AgentsKit.swift`), design components in
  `ios/BrainBuddyKit/Sources/BrainBuddyDesign/`. Anything the Mac app calls across that package
  boundary must be `public`.
- Keep the fix minimal: what the finding needs, no refactor around it.
- Add or update a test that would have caught it:
  - **Look:** a snapshot test with `assertMacSnapshot` (see `SettingsSnapshotTests.swift`),
    light and dark. Record with `CARRY_ON_SNAPSHOT_RECORD=1 swift test --filter <Suite>`, look at
    the new PNG in `__Snapshots__/` next to the board PNG, then run again without the variable.
  - **Keyboard or behaviour:** a Swift Testing test on the model (`HandoffFlowTests`,
    `AgentSettingsModelTests`, …). Logic goes in the model, not only in the view.
  - Name the test after the requirement it covers with the feature-qualified id, e.g.
    `` @Test("030-FR-012 arrows move the hand-off selection") ``. A bare `FR-012` is rejected.
- Run `cd macos && swift test --only-use-versions-from-resolved-file` until green. If you changed
  the kit, also `cd ios/BrainBuddyKit && swift test`.
- Rebuild the app and repeat the check from § 2 to see the fix in the running app.

## 4. Open the PR

- One finding per branch and PR, branch `codex/mac-<short-name>` from the latest `origin/main`.
- Conventional commit: `fix(macos): <what the user sees now>`.
- PR body:
  - **Before / After:** one sentence each, with the before screenshot, the after screenshot and
    the board PNG path (e.g. `docs/design/board/mac/M29-Mac.png`).
  - **Test:** the test name and the `swift test` summary line.
  - **Questions:** anything from rule 3 you did not decide.
- Open it as a draft. Claude reviews it against the board and drives it to merge; push follow-up
  fixes to the same branch when asked.
