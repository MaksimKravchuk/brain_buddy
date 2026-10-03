# UI Contract: Compact Task Rows

## Row geometry and content

- A collapsed Task header is exactly 44 px high at supported desktop widths.
- It contains completion, a one-line title, optional compact due/subtask indicators,
  compact Waiting-for text, short Tags, and at most one agent control.
- Project/List and Delete are never row content.
- Optional metadata may disappear progressively; the title, completion target, and
  agent target may not wrap or overlap.

## Route-backed inline detail

- The current Task route parameter is the only selected-Task authority; the existing
  Cmd/Ctrl+\\ shortcut collapses by navigating to the parent route rather than hiding
  detail locally.
- The matching row sets `aria-expanded=true` and owns an inline region immediately
  after its 44 px header.
- Only the 44 px header owns non-control click activation. The inline detail is a
  sibling immediately after that header inside the list item; clicks, text selection,
  whitespace, and semantic content inside detail never re-navigate or collapse it.
- No Task-side-sheet dialog, scrim, or inert list state is present.
- Close, same-row activation, Cmd/Ctrl+\\, and unhandled Escape collapse to the parent
  list route. Cmd/Ctrl+\\ is collapse-only; there is no locally hidden detail to reopen.
- Close restores focus to the originating row; if it disappeared, use the next
  surviving row, otherwise the list heading.
- Existing fields, autosave/recovery, lifecycle, subtask/comment, navigation, and run
  behavior remain available inside the inline region.
- The inline detail owns the previous sheet's Escape exclusion rules for selects,
  comboboxes, listboxes, draft-preserving controls, and nested dialogs. A document-wide
  `[role=dialog][aria-modal=true]` guard suppresses both Escape collapse and Cmd/Ctrl+\\
  while a sibling portal such as `AgentHandoffOverlay` is open; one Escape closes only
  that review. `AppShell` receives no Task panel and does not make the list inert.
- Canonical recovery first removes excluding search/date/group filters and preserves
  the current state/Project/Tag route when membership still holds. Otherwise it chooses
  a resolvable Project, then the Task's open state, then `/tasks/next` for terminal or
  no-Project Tasks; cancelled fallback uses `showCancelled=1`. It performs at most one
  replace-navigation and automatically fetches at most ten sequential pages, aborting
  when Task ID/route/filter changes. A page failure or exhausted bound stops the walk
  and exposes Retry/Load more while the rest of the list stays usable.
- A missing or another-owner Task ID receives the same existing 404 and a non-leaking
  list-level `We couldn't load this task` error with Retry and Close. Because no valid
  detail response exists, no canonical redirect is attempted and no origin row is
  invented.
- A collapse first flushes scheduled edits into the existing keyed autosave
  controller/journal; the controller may finish or expose recovery after the inline
  component unmounts. There is no outgoing duplicate panel or exit animation.
- Completing a selected Task crosses the existing autosave/completion barrier, then
  collapses detail while its compact header moves to the Completed group. Focus follows
  the completed row when rendered, otherwise the next surviving row or list heading.
  Layout animation measures the 44 px header, not expanded detail.

## Pre-assignment agent control

- Present only for non-terminal Tasks with no latest run, relay flag ON, and at least
  one `ready_for_handoff` connection.
- Visual split bounds are 54 × 28 px inside a 54 × 44 px target slot.
- Left button accessible name: `Review hand-off to {resolved agent name} for {Task title}`.
- Right button accessible name: `Choose an agent for {Task title}`; it exposes menu state.
- Menu items are keyed and selected by connection ID, even when names duplicate.
- Either path opens the existing `AgentHandoffOverlay` with `connectionId` preselected.
- Activation performs no confirmation request and sends no Task content.
- Offline, both buttons remain operable to inspect that review; confirmation is
  disabled there and copy explicitly states that nothing is queued.
- After confirmed dispatch replaces the split control, focus moves to the newly
  rendered assigned control for the same Task. If it cannot render, use the row trigger
  and then the normal surviving-row/list-heading fallback.

## Assigned agent control

- Present whenever a latest run summary exists, including relay rollout OFF.
- One button, exactly 184 × 28 px, with no arrow and no popup semantics.
- Internal visual columns are stable: robot, agent-name, separator, state icon, state.
- Visible state is short and truthful; `Agent reported complete` is `Reported`, never
  `Done`.
- Accessible name contains Task title, full agent name, exact `primary_state_label`,
  and the full `compactRunLabel` disclosure including guarantee/cancellation information.
- Activation selects/opens the Task inline detail; full run data remains there.

## Existing network contracts

No API contract changes. The UI may invoke only these existing reads/flows, including
additional calls from the Task-list surface:

- existing Task list/detail responses and routes;
- existing eligible-agent connection projection;
- existing latest-run summary projection;
- existing `AgentHandoffSeed` and immutable review/confirmation flow.
