# Design: Compact task rows

**Feature**: `specs/017-compact-task-rows/`
**Spec**: `spec.md` (Clarifications settled: 2026-09-10)
**Screens**: `design/*.html`
**Human sign-off**: Max, 2026-09-10 — approved the 44 px rows, inline detail,
pre-assignment split control, removal of the assigned arrow, equal-size assigned
controls, context-preserving → Project → lifecycle → Next-actions canonical recovery,
an offline split control that still opens read-only review, and moving full
tier/cancellation disclosure from visible desktop-row copy into the accessible name
and inline detail.

<!--
  Produced by /speckit-design via the design-architect subagent, after
  /speckit-clarify and before /speckit-plan. Screen and state ids are stable:
  append new ids rather than renumbering existing ones.
-->

## Applicability

This feature changes the existing desktop-web Task list and its responsive-web
presentation. It replaces card-like collapsed rows with 44 px hairline-separated
rows, moves the existing Task detail directly below the selected row, and gives
agent state one fixed alignment rail. It does not redesign the native mobile
client, the hand-off review, Task lifecycle, the relay contract, or the shell.

## Design rationale

- **Color**: flat slate-50 page, white list/detail surfaces, slate-200 rules,
  sky-500 interaction/focus, amber needs-user, rose failure, and restrained
  emerald only where an authenticated agent report is terminal. Status always
  has text and an icon; color is supplementary.
- **Type**: Inter when available, then the existing system sans stack. Task titles
  are 14 px/500; status labels and row metadata are 11 px/500; pane titles are
  20 px/600. No external font request is present in the artifacts.
- **Layout**: the memorable structural element is a disciplined right-hand agent
  rail. Every assigned visual control is exactly 184 × 28 px and uses the same
  internal grid: robot icon, 50 px agent-name column, separator, state icon, state
  label. The title owns all remaining width and truncates first; short Tags then
  disappear progressively at narrow widths.
- **Restraint review**: the accepted dense list does not benefit from task cards,
  repeated Project/List text, shadows, gradients, decorative badges, or row-level
  Delete. Those elements were removed. Dividers communicate row boundaries; the
  selected row uses a low-chroma sky fill and a 2 px left rule.

## Screen inventory

| id | surface | screen | purpose | FR refs |
|---|---|---|---|---|
| D-01 | desktop web, 1440×900 and ≥768 px | Compact Task list | Scan at least ten 44 px rows; preserve completion, title, short Tags and indicators; align one optional agent control | FR-001–FR-003, FR-007–FR-016 |
| D-02 | desktop web | Inline Task detail | Edit and act on one route-selected Task without hiding the surrounding list or opening a side sheet/scrim | FR-004–FR-006, FR-011–FR-013, FR-016 |
| D-03 | desktop web | Agent entry and assigned-state rail | Specify the split pre-assignment control, eligible-agent chooser, compact state vocabulary and the invariant 184 × 28 geometry | FR-007–FR-014, FR-016 |
| D-04 | responsive web, 390×851 and constrained desktop | Resilience and narrow states | Keep the primary Task path usable during loading, empty, error, partial, cached/offline, terminal, long-content and narrow states | FR-001–FR-006, FR-010–FR-016 |

Files:

- `design/D-01-compact-task-list.html`
- `design/D-02-inline-task-detail.html`
- `design/D-03-agent-control-states.html`
- `design/D-04-resilience-narrow.html`

## State inventory

### D-01 — Compact Task list

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| D-01-S01 default dense list | ten or more open Tasks load | One 44 px row per Task, separated by a slate hairline; completion target, one-line title, short Tags/indicators, and at most one right-aligned agent control | Existing list title and count | FR-001, FR-002; SC-001, SC-002 |
| D-01-S02 selected collapsed row | route identifies a Task before detail settles | Sky-50 row fill, 2 px sky left rule, visible focus on the title/row trigger, and `aria-expanded=true`; row remains 44 px | Full Task title remains the accessible name | FR-004, FR-006; SC-004, SC-005 |
| D-01-S03 long title | title exceeds its flexible column | Title ellipsizes on one line; full text remains available to accessibility APIs; right-side controls do not move | The original full title | FR-002, FR-016; SC-002 |
| D-01-S04 many or long Tags | metadata competes for width | Tag pills truncate, then progressively hide from the end before the title or agent rail wraps | Plain Tag names | FR-002, FR-016 |
| D-01-S05 no Tags | Task has no Tags | The title expands into the unused metadata space; no placeholder or reserved gap appears before the agent control | — | FR-002, FR-016 |
| D-01-S06 due, subtasks and Waiting-for | indicators apply | Compact due chip, numeric subtask indicator and Waiting-for text remain on the same line and yield before the fixed agent rail | Existing due copy; `{done}/{total}`; current `waiting_for` | FR-002, FR-016 |
| D-01-S07 completion pending | owner activates completion | The 44 px completion target is disabled and shows existing pending feedback; row does not move or appear complete until the canonical save succeeds | Existing pending feedback | FR-002, FR-005, FR-016; SC-007 |
| D-01-S08 completed Task | canonical completion succeeds | Checked circle plus slate-500 struck title; row follows the accepted Completed grouping; an agent `Reported` control does not itself produce this Task state | `Completed` | FR-005, FR-013, FR-016; SC-007 |
| D-01-S09 cancelled Task | cancelled history is shown | Cancelled icon/text treatment remains distinct from completion; no collapsed-row Delete action appears | `Cancelled` | FR-003, FR-005, FR-016 |
| D-01-S10 Task-list loading | first page is unresolved | List frame, heading and filters remain; 44 px skeleton rows appear after about 250 ms and never masquerade as empty | `Loading tasks…` | FR-016 |
| D-01-S11 empty (first run) | no Tasks exist in this list | Existing one-line invitation and Add task path; no empty agent column or Completed heading | `No tasks yet` | FR-016 |
| D-01-S12 empty (filtered to nothing) | active filter/query has no matches | Active filters remain visible with a clear-filter action; no first-run prompt | `No tasks match these filters` | FR-016 |
| D-01-S13 Task-list error | Task fetch fails with no cache | Specific error, correlation reference when supplied, and Retry; no fake rows | `We couldn’t load these tasks` · `Retry` | FR-016 |
| D-01-S14 agent-summary loading/error | Tasks load but no trustworthy latest-run projection is available | Task rows remain fully usable and render no agent placeholder; summary loading never shifts row height | — | FR-016 |
| D-01-S15 summary refresh failure | the one batch summary read fails | With trustworthy cached summaries, controls stay visible and are marked possibly stale; without cache, no speculative agent control renders. One non-blocking notice offers Retry | `Agent updates couldn’t be refreshed. Tasks are still available.` | FR-016 |
| D-01-S16 cached/offline | a previously confirmed list is available while network is offline | Cached Tasks remain readable; cached run controls retain their last known label and their accessible name says the state may be stale; mutations follow existing offline rules | `Offline · showing saved tasks` | FR-016 |
| D-01-S17 relay rollout OFF | relay flag is off | Existing assigned controls remain. A non-terminal Task with no run has no pre-assignment split control | No new row copy | FR-014 |

### D-02 — Inline Task detail

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| D-02-S01 default expanded | owner activates a title or non-control row area | Existing Task detail is inserted immediately after the selected 44 px row. The list stays visible; there is no side sheet, modal role, scrim, or inert list | Existing Task fields and actions | FR-004, FR-005; SC-005 |
| D-02-S02 route restore | URL names a Task on load/reload/back | Loaded pages are searched for the matching row and inline detail restores in list position; heading receives programmatic focus only when route navigation requires an announcement | Existing Task title | FR-005, FR-006 |
| D-02-S03 loading | row route resolves while detail request is pending | Expanded inline frame with fixed header and skeleton/body loading copy; neighbouring rows do not shift twice | `Loading task detail…` | FR-005, FR-016 |
| D-02-S04 missing/error | selected Task cannot be loaded | When an origin row exists, the error stays below it. A missing/another-owner ID has no invented row and uses the same non-leaking list-level error below the heading; both provide Retry and Close and surface a correlation reference when supplied | `We couldn’t load this task` · `Retry` | FR-005, FR-016 |
| D-02-S05 autosave in flight/saved | an editable field changes | Existing compact save status in the inline header; fields remain available under the current autosave rules | `Saving…` · `Saved` | FR-005, FR-016; SC-007 |
| D-02-S06 conflict recovery | canonical revision changed elsewhere | Existing conflict recovery appears inside the detail, preserving unsaved input and offering explicit retry/discard; list remains usable | `Task changed elsewhere` · `Retry my edits` | FR-005, FR-016 |
| D-02-S07 save failure | autosave is rejected or unverifiable | Actionable inline recovery, retained edits, Retry, and correlation/error details; no optimistic success | `Couldn’t save changes` | FR-005, FR-016 |
| D-02-S08 offline/interrupted edit | connection drops during an edit | Draft remains in the current tab, is labelled not saved, and uses the existing explicit retry-on-reconnect path | `You’re offline` · `Your edits remain in this tab.` | FR-005, FR-016 |
| D-02-S09 adjacent navigation | Previous/Next is activated | Route and inline detail update in place; focus goes to the new detail heading and the list position indicator updates | `{position} of {total}` | FR-005, FR-006 |
| D-02-S10 close/collapse | Close, Escape outside a nested control, Cmd/Ctrl+\\, or the same row trigger is activated | Inline region collapses and focus returns to the originating row trigger when it survives. The shortcut is collapse-only; a sibling modal/review consumes its own Escape first | `Close task` | FR-004, FR-006; SC-004, SC-005 |
| D-02-S11 selected Task moves or disappears | completion re-groups the row, or state/filtering removes it | Completion first crosses the existing autosave barrier, then collapses detail as the 44 px header moves to Completed and focus follows the moved row (or survivor/heading fallback). A state/filter move navigates to the canonical list and reopens under the real row; only an unavailable Task closes to the fallback | Existing completion/filter announcement | FR-005, FR-006, FR-016 |
| D-02-S12 nested partial failure | a subtask, comment, or run request fails while Task detail itself is valid | Successful sections remain; the failed section owns its error and retry without replacing the Task | Existing section-specific recovery copy | FR-005, FR-016 |
| D-02-S13 latest run detail | assigned control or Task row opens a Task with a run | Full exact `primary_state_label`, guarantee tier, cancellation state, last contact, timeline and available actions appear in the existing run section | Server-owned run state and disclosure | FR-005, FR-011, FR-012 |
| D-02-S14 agent-reported completion | latest run reports terminal completion | Inline run section says `Agent reported complete`; Task completion remains a separate owner action and the Task stays open | `This is what the agent said it did. The task is still open — completing it is your call.` | FR-013 |
| D-02-S15 no run | selected Task has never been handed off | Existing detail has no empty run-history chrome; while eligible and rollout is ON, `Hand to agent` remains in the detail path | `Hand to agent` | FR-005, FR-007, FR-014 |
| D-02-S16 valid Task outside current projection | detail resolves but filtering, movement, or unloaded pagination leaves no matching row | Clear excluding filters and keep the current route when membership holds; otherwise replace once to resolvable Project, open state, or Next actions for terminal/no-Project (`showCancelled=1` when cancelled). Fetch at most ten pages per attempt, abort on route change, and show Retry/Load more on failure or exhaustion | Existing list title and Task title | FR-005, FR-006, FR-016 |

An inline detail has no independent first-run or filtered-empty state: it is rendered only
for a selected Task. A missing/filtered-away selected Task is handled by D-02-S04 or
D-02-S11 rather than displaying an invented empty detail.

### D-03 — Agent entry and assigned-state rail

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| D-03-S01 pre-assignment default | eligible connections exist, Task is non-terminal, has no latest run, rollout is ON | A 54 × 28 px visual split control inside a 44 px target slot: robot shortcut on the left, chevron chooser on the right | Accessible: `Review hand-off to {last-used eligible agent} for {Task}` and `Choose an agent for {Task}` | FR-007–FR-009; SC-004, SC-006 |
| D-03-S02 remembered eligible identity | owner-scoped local identity still matches an eligible connection | Robot accessible name names that connection and Task; no visible agent-name badge is added to the dense row | `Review hand-off to Hermes for Call the dentist` | FR-008 |
| D-03-S03 remembered identity stale/ineligible | stored identity is absent from the eligible set | Robot deterministically targets the first eligible connection; the stale identity is ignored without an error toast | `Review hand-off to {first eligible agent} for {Task}` | FR-008 |
| D-03-S04 no remembered identity | no local preference exists | Same deterministic first-eligible fallback as S03 | `Review hand-off to {first eligible agent} for {Task}` | FR-008 |
| D-03-S05 chooser open | arrow is activated | Anchored menu of eligible connections ordered by the existing connection projection; focus moves to the first/selected option; Escape closes and returns focus to the arrow | `Choose an agent` | FR-007, FR-009; SC-004 |
| D-03-S06 duplicate names | two eligible connections share a display name | Separate menu options retain unique connection identity; selection never depends on the label alone; duplicate visible names append the safe hostname parsed from `agent_address` | `Hermes · research.example` · `Hermes · ops.example` | FR-008 |
| D-03-S07 connections loading | eligibility is unresolved | No speculative split control or skeleton button; the Task row remains stable and usable | — | FR-016 |
| D-03-S08 no connections | none are saved | No collapsed-row split control. The existing detail path exposes the existing no-connections review state and route to Connected agents | `No agents connected yet` | FR-007, FR-016 |
| D-03-S09 no eligible connections | saved connections exist but all are stale, changed, disconnected, unsupported, or otherwise ineligible | No collapsed-row split control. Existing detail/review lists why each connection is unavailable | `None of your agents can take this hand-off` | FR-007–FR-009, FR-016 |
| D-03-S10 shortcut activated | robot side is activated | Existing immutable review opens with the resolved connection preselected; no content is sent and no run is created by this click | Existing `Hand this task to an agent` review | FR-009; SC-006 |
| D-03-S11 chooser selection | a menu option is activated | Existing immutable review opens with that exact connection identity preselected; no content is sent | Existing review | FR-008, FR-009; SC-006 |
| D-03-S12 preview loading | existing review builds the manifest | Existing review loading state states that no Task content has been sent | `Building the hand-off preview…` | FR-009, FR-016 |
| D-03-S13 preview error | preview fails | Existing specific error/correlation ID/Retry; Task row remains available and nothing is sent | `We couldn’t build this hand-off` | FR-009, FR-016 |
| D-03-S14 re-review | immutable manifest changes | Existing warning and rebuilt review require confirmation again | `What would be sent has changed. Review it again before confirming.` | FR-009, FR-016 |
| D-03-S15 reauthentication | existing relay contract requires password verification | Existing password step remains in review; the row shortcut never bypasses it | Existing reauthentication explanation | FR-009 |
| D-03-S16 offline before assignment | browser is offline | Split control remains operable and opens the existing readable review; confirmation is disabled there and nothing is queued | `Sending is unavailable and nothing is queued.` | FR-007, FR-009, FR-016 |
| D-03-S17 assigned — Queued | latest run exact state is `Queued` | 184 × 28 control in the fixed rail; clock icon plus visible `Queued`; no arrow | Visible `Hermes · Queued`; accessible name includes Task title, `Queued`, and full disclosure | FR-010–FR-013; SC-003, SC-004 |
| D-03-S18 assigned — Running | exact state is `Running` | Same geometry/columns; live-state icon plus visible `Running`; no animation is required | Visible `Hermes · Running`; accessible name includes `Running` and full disclosure | FR-010–FR-013; SC-003, SC-004 |
| D-03-S19 assigned — Needs you | exact state is `Needs you` | Same geometry/columns; alert-circle icon, amber text/border, visible `Needs you`; no color-only meaning | Visible `Hermes · Needs you`; accessible name includes exact state and full disclosure | FR-010–FR-013; SC-003, SC-004 |
| D-03-S20 assigned — agent-reported completion | exact state is `Agent reported complete` | Same geometry/columns; report/document icon plus visible short label `Reported`, never `Done`; Task checkbox remains open | Visible `Hermes · Reported`; accessible name includes `Agent reported complete` and full disclosure | FR-010–FR-013; SC-003, SC-004 |
| D-03-S21 assigned — Failed | exact state is `Failed` | Same geometry/columns; warning icon plus visible `Failed`; no arrow | Visible `Hermes · Failed`; accessible name includes `Failed` and full disclosure | FR-010–FR-013; SC-003, SC-004 |
| D-03-S22 other server-owned state | exact state is another current relay label | Same 184 × 28 geometry with a truthful compact label preserving uncertainty/provenance; exact server label is never replaced in the accessible name/detail | Examples: `Unconfirmed`, `No updates`, `Disconnected` | FR-010–FR-013 |
| D-03-S23 cancellation withdrawal | run’s cancellation outcome is unsupported/not cancelable | Geometry does not change. Visible state stays primary; accessible name adds `Cancellation not supported`; full line appears in detail | `Cancellation not supported` in accessible disclosure/detail | FR-012, FR-013 |
| D-03-S24 assigned activated | any assigned control is activated | Task expands as D-02 and focuses its detail heading; full run information is visible there | `Open {agent} run for {task}. Server status: {exact state}. {full disclosure}` | FR-011, FR-012; SC-004, SC-005 |
| D-03-S25 rollout OFF with an existing run | flag turns off after a run exists | Assigned control remains visible and operable. Only the new split control is gated away | Existing server-owned state | FR-014 |
| D-03-S26 confirmed hand-off replaces trigger | confirmation succeeds and the split control becomes assigned | Focus moves to the newly rendered assigned control for the same Task; if it cannot render, focus uses the row trigger then survivor/heading fallback | Assigned control's Task-disambiguated accessible name | FR-006, FR-009–FR-012; SC-004, SC-006 |

#### Compact visible-state map

The visible label is a density projection only. The assigned control’s accessible name
and D-02 run detail always use the exact `primary_state_label` and full disclosure.

| exact server-owned label | visible compact label | non-color cue |
|---|---|---|
| `Queued` | `Queued` | Clock |
| `Sent` | `Sent` | Send |
| `Accepted` | `Accepted` | Circle check |
| `Running` | `Running` | Circle dot |
| `Needs you` | `Needs you` | Circle alert |
| `Cancellation requested` | `Cancel req.` | Clock alert |
| `Agent reported complete` | `Reported` | File text; never a Task-completion checkmark on its own |
| `Failed` | `Failed` | Triangle alert |
| `Cancelled` | `Cancelled` | Circle x |
| `Delivery unconfirmed` | `Unconfirmed` | Circle help |
| `Stopped reporting` | `No updates` | Radio off |
| `Agent no longer reports this run` | `Missing` | Unplug |
| `Content expired under retention policy` | `Expired` | Archive x |
| `Connection disconnected` | `Disconnected` | Unlink |
| `Not sent` | `Not sent` | Send x |

### D-04 — Resilience and narrow responsive web

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| D-04-S01 supported minimum desktop | viewport is 768 px or wider | Every collapsed row remains exactly 44 px and one line; the 184 × 28 assigned control is unchanged | — | FR-001, FR-002, FR-010, FR-016; SC-002, SC-003 |
| D-04-S02 narrow web default | viewport is 390×851 | Desktop sidebar becomes the existing drawer; short Tags/due/subtask metadata progressively hide before the title or agent target is harmed; no page-level horizontal scroll | Existing responsive shell copy | FR-002, FR-016 |
| D-04-S03 narrow assigned row | a narrow row has a latest run | The 184 × 28 visual control sits inside a 184 × 44 px hit target; title gets the remaining one-line width; full names are accessible | Visible compact state | FR-010–FR-013, FR-016; SC-004 |
| D-04-S04 narrow pre-assignment row | narrow Task is eligible for hand-off | The 54 × 28 visual split sits inside a 54 × 44 px hit target; robot and arrow remain separate keyboard targets and never wrap | Accessible shortcut and chooser names | FR-007–FR-009, FR-016; SC-004 |
| D-04-S05 narrow inline detail | Task is selected at 390 px | Detail remains directly below the row in a one-column flow; fields and section actions use ≥44 px targets; page does not scroll horizontally | Existing Task detail copy | FR-004–FR-006, FR-016 |
| D-04-S06 long agent/title/Tags | untrusted agent name or Task metadata is unusually long | Agent name truncates within its fixed 50 px visual column; state column remains aligned; title truncates; Tags hide; accessible names retain full strings | Original full strings in accessibility APIs | FR-010, FR-012, FR-016 |
| D-04-S07 cached/offline narrow | cached list opens offline | One compact status banner precedes the list; rows and detail stay reachable; pending work is never presented as saved | `Offline · showing saved tasks` | FR-016 |
| D-04-S08 empty/error narrow | no result or request failure | First-run, filtered-empty and fetch-error copy remain distinct, with the single applicable action in a 44 px target | As D-01-S11–S13 | FR-016 |
| D-04-S09 summary refresh failure narrow | the batch summary refresh fails | One non-blocking notice wraps above the list; cached controls remain marked stale when trustworthy, otherwise no row reserves an agent slot | `Agent updates couldn’t be refreshed. Tasks are still available.` | FR-016 |

## Affordance → requirement map

| screen | affordance | what it does | FR ref |
|---|---|---|---|
| D-01 / D-04 | 44 px completion target | Uses the existing explicit Task completion command; an agent report never activates it | FR-002, FR-005, FR-013 |
| D-01 / D-02 / D-04 | Task title and non-control 44 px header area | Opens or collapses the route-backed inline detail and maintains `aria-expanded`; detail content is outside this activation hit region | FR-004, FR-006 |
| D-02 | Close task / Escape | Collapses inline detail and restores focus to the originating row or deterministic fallback | FR-004, FR-006 |
| D-02 | Previous task / Next task | Changes route selection and the inline detail without obscuring the list | FR-005, FR-006 |
| D-02 | Existing detail fields, lifecycle controls, subtasks and comments | Preserve the complete existing Task-detail workflow and recovery behavior | FR-005 |
| D-02 / D-03 | Existing run detail actions | Preserve complete projection, reply/cancel/check controls and relay truthfulness in the inline region | FR-005, FR-011, FR-012 |
| D-03 / D-04 | Robot side of pre-assignment split | Resolves last-used eligible identity (or deterministic fallback) and opens review with it preselected; its name includes the Task; sends nothing | FR-007–FR-009 |
| D-03 / D-04 | Chevron side of pre-assignment split | Opens the eligible-connection menu; selection opens the same immutable review and sends nothing | FR-007–FR-009 |
| D-03 / D-04 | Assigned 184 × 28 control | Opens the Task’s inline detail/run information; never opens an assignment menu | FR-010–FR-012 |
| D-01 / D-04 | Retry tasks / Retry agent updates | Re-runs the applicable existing read without blocking usable Task rows | FR-016 |
| D-01 / D-04 | Clear filters | Recovers from filtered-to-nothing while retaining the list’s spatial frame | FR-016 |

### Requirements with no affordance

- **FR-001** — fixed row geometry is a layout invariant, not an action.
- **FR-003** — the absence of Project/List text and collapsed-row Delete is the
  requirement.
- **FR-008** — identity storage and fallback constrain the robot shortcut; they do
  not add a separate user control.
- **FR-012** — the accessible name and full inline disclosure constrain the assigned
  control rather than adding another visible button.
- **FR-014** — rollout gating determines which existing control is present.
- **FR-015** — the no-contract/no-provider/no-native-mobile boundary has no UI.
- **FR-016** — resilience and responsive constraints apply across the mapped controls.
- **FR-017** — privacy/retention disclosure is policy content, not a Task-list action.

### Affordances with no requirement

None. Existing shell navigation, Add task, filter controls and account chrome appear in
the HTML only to preserve spatial orientation; this design neither adds nor changes them.

## Primary loop impact

This improves the **clarify/approve → route/review → evidence/results** portion of
capture → atomic items → clarify/approve → route or CRT candidate → Weekly Review →
evidence/results. More Tasks remain visible while one Task is inspected, so the owner
keeps their list position during clarification and review. Capture, atomic-item creation, CRT
routing and Task lifecycle authority are unchanged. Weekly Review remains visibly
deferred. An external run remains a separate evidence lane: `Reported` opens evidence;
it never completes the Task.

## Mobile viability

- **Native mobile impact**: N/A — FR-015 explicitly excludes native-mobile behavior.
- **Responsive-web viewport**: represented at 390×851 in D-04 with no horizontal
  page scroll. At 768 px and above the exact 44 px desktop-row requirement applies.
- **Tap targets**: at narrow width each 28 px visual agent control is centered in a
  44 px target slot; completion, close, navigation and field actions remain at least
  44 px. The desktop visual dimensions remain 184 × 28 px for assigned controls.
- **One-handed reach**: the common row actions remain completion at the leading edge
  and detail/agent access on the row; lifecycle/destructive actions stay in detail.
- **Destructive actions**: no new destructive action is added. Delete remains absent
  from collapsed rows; existing deeper lifecycle confirmation/recovery copy is unchanged.

## Keyboard and focus

- **Tab order**: list-level controls → each row’s completion → title/row trigger →
  optional due/subtask action if already interactive → robot then chooser before
  assignment, or one assigned-control button after assignment. Hidden/truncated Tags
  do not create tab stops.
- **Focus on open**: activating a Task moves focus to the inline-detail heading after
  the region is inserted and announced. Route restoration may focus the heading when
  needed to announce navigation without unexpectedly stealing focus during reload.
- **Focus restored on close to**: the exact originating Task row trigger; if removed,
  the next surviving row, otherwise the list heading.
- **Escape**: first closes any nested menu/disclosure according to its existing rules;
  otherwise collapses inline detail. A document-wide modal guard means one Escape while
  a portaled hand-off review is open closes only that review. Escape from the agent
  chooser returns focus to its arrow. It never confirms a hand-off or mutation.
- **Split-button semantics**: robot and chevron are two adjacent real buttons in one
  labelled group. Each has its own accessible name and visible focus ring. Arrow keys
  follow normal menu behavior once the chooser opens.
- **Assigned-control semantics**: one button, no chevron and no popup semantics. The
  accessible name contains full agent name, exact server `primary_state_label`, full
  compact relay disclosure, guarantee tier, and cancellation withdrawal when applicable.
- **Visible focus**: the BrainBuddy double ring — 2 px white plus 2 px sky at 50% —
  is used on every changed control and on the programmatically focused detail/list heading.
- **Announcements**: under SC-004, loading uses the existing polite status pattern;
  failures and unsaved conflict use the existing alert pattern; collapse/removal
  announces the destination before moving focus. D-04 demonstrates list status/error
  roles and D-02 retains the existing autosave live region.
- **State communicated by color alone**: none. Every assigned state uses visible text
  plus a distinct Lucide icon; terminal Task status separately uses text/checkbox semantics.

## Design authority

- Tokens, colors, type, easing and the Sprout logo path come from the
  `brain-buddy-design` skill. The static files embed the authoritative Sprout path and
  request no CDN or external font.
- Exactly four open GTD primary lists remain: Inbox, Next actions, Waiting for, and
  Someday / maybe. Projects and Tags remain secondary; Weekly Review stays visibly
  deferred.
- Feature 017 narrowly supersedes feature 014's desktop-web compact-row visible-copy
  requirement. Native iOS stays unchanged; exact state/tier/cancellation copy remains
  in the desktop control's accessible name and inline detail.
- Vocabulary sweep over `design.md` and `design/`: pass.
- Self-contained asset sweep (`<link>`, `@import`, remote URL, rendering-dependent
  `<script>`): pass.
- Repository design-skill validator: pass (6 tests).

## Open decisions for the human

None. The owner already settled density, visible metadata, inline expansion,
pre-assignment split behavior, no arrow after assignment, fixed assigned-control size,
the `Reported` wording, canonical-route precedence, and offline review behavior.
