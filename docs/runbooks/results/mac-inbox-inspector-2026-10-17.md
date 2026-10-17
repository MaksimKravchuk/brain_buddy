# Ordinary Inbox inspector correction — 2026-10-17

## Accepted outcome and scope

The authoritative [M16 PNG](../../design/board/mac/M16-Mac.png) shows the entered item, “What is it?”, four clarification choices, and Done already / Not needed / Skip. The existing ordinary Inbox instead appended Note, Steps inside, Comments, List, Project, and Date and tags editors. Under the owner's PNG-authority policy, their removal from this ordinary state is an intentional functional presentation change, not merely a color or spacing correction.

This bounded SHOW correction omits those editors only while choosing what the Inbox item is. Existing task metadata is preserved. First-step authoring still exposes its existing editors. Other inspector variants, choice actions, autosave and submission callbacks, persistence, API/authentication, main-window geometry, tokens and workflows are untouched.

## Implementation and visual evidence

- [Before actual native window](../../design/evidence/mac-inbox-inspector-board/before.png): generic editors extend below the four choices and diverge from M16.
- [After actual-host light render](../../../macos/Tests/BrainBuddyMacTests/__Snapshots__/mac-inspector-inbox-ordinary-light-native2x.png) and [dark render](../../../macos/Tests/BrainBuddyMacTests/__Snapshots__/mac-inspector-inbox-ordinary-dark-native2x.png): the production `TaskInspector`, populated with synthetic existing metadata, retains the four choices and footer with no generic editors visible or residual layout gap. These are offscreen native-host renders, not screenshots of a launched app.
- Note and properties mount only in first-step authoring. Their draft bindings belong to the outer editor. `TaskDetailExtras` stays mounted with zero height, transparent clipped content, disabled input, no hit testing and no accessibility exposure in ordinary Inbox. Retaining the full subtree preserves unfinished subtask/comment drafts and child retry identities across Back → A step I can take.
- Back explicitly returns focus to the visible entered-item title. The parent-owned actual native journey must verify that focus and unfinished first-step drafts survive the round trip; offscreen host assertions do not claim that interactive journey has been exercised.

The first attempt to disable the whole editor group left the native Note `NSTextView` editable. That candidate was rejected. The retained solution omits that editor and all generic property controls. Native assertions verify that the retained New step / Write a comment fields are disabled and cannot become key views, and that rendering leaves every stored metadata field unchanged.

## Verification

The existing component-composition M16 fixture already covered the choices and footer but never instantiated the production inspector's appended editors. A bounded actual-inspector fixture now covers that missing risk in both appearances. It waits for AppKit's insertion transaction before capture and rejects blank native images. No snapshot tolerance was weakened.

| Check | Result | Local log |
| --- | --- | --- |
| Stock-view regression | FAIL as expected — Note, properties and extra input controls exposed in both appearances | `/private/tmp/bb-m16-control-red.log` |
| Actual-host candidate regression against stock images | FAIL as expected — two changed images; native visibility/reachability/data assertions pass | `/private/tmp/bb-m16-render-red.log` |
| Focused inspector snapshot replay | PASS — 8 tests / 1 suite, 6.920 seconds | `/private/tmp/bb-m16-focused.log` |
| Complete native Mac suite | PASS — 457 tests / 47 suites, 36.447 seconds | `/private/tmp/bb-m16-full-mac.log` |
| Diff whitespace | PASS | `git diff --check` |

No tracked kit source or generated token changed, so a kit rerun is not required for this correction. Local native backing scale is 2x; the snapshot names retain explicit native profiles. A genuine native1x CI reference, independent exact-SHA native QA, CI, integration and delivery remain parent-owned gates. This receipt does not claim those gates or production acceptance have passed.

Prepared from `bae38ea826ec069778ea0f9558e082e98ec7ff0a` on `codex/mac-inbox-inspector-board`. Builds reused the exclusive leased `mac-board-parity/brain_buddy/macos/.build` cache. Missing ignored Apple bridge artifacts were copied from that worktree's kit artifacts/bindings only; no tracked kit source or existing bridge product was replaced.
