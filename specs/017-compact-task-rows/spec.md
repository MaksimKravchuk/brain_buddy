# Feature Specification: Compact Task Rows

**Feature Branch**: `codex/compact-task-rows`

**Created**: 2026-09-10

**Status**: Founder-accepted for implementation through 2026-10-10; ASK landing remains separately gated

**Input**: Make desktop Task lists compact, expand Task detail inline, and replace verbose agent summaries with aligned agent controls.

## Clarifications

### Session 2026-09-10

- Q: How dense must the collapsed desktop list be? → A: A 13-inch Mac must show at least ten Tasks without difficulty; each collapsed row is 44 px.
- Q: Which Task classification appears on a collapsed row? → A: Short Tags are visible; Project/List text is not.
- Q: Where does Task detail open? → A: Directly below the selected row; the right-side sheet is removed from desktop Task lists.
- Q: How does agent assignment work? → A: Before assignment, the robot opens review for the last-used eligible agent and the arrow chooses another; mandatory review and confirmation remain.
- Q: What remains after an agent is selected? → A: One fixed-size agent-and-status control without an arrow; clicking it opens the Task detail and run information.
- Q: Is Delete present on the collapsed row? → A: No.
- Q: What happens when a valid deep link names a Task outside the rendered filter/page? → A: Navigate to the Task's current canonical list, load through the page containing its real row, and expand it there.
- Q: Where do guarantee-tier and cancellation-withdrawal disclosures live in the compact desktop row? → A: The visible 184 px control stays short; the complete disclosure remains in its accessible name and inline detail. Native mobile remains unchanged.
- Q: Which canonical list wins when a valid Task is outside the current projection? → A: Preserve the current route after clearing excluding filters when the Task still belongs there; otherwise prefer a resolvable Project, then an open lifecycle list, and use Next actions for terminal/no-Project Tasks. Cancelled fallback adds `showCancelled=1`.
- Q: What does the pre-assignment split control do while offline? → A: It remains operable and opens the existing readable review; confirmation is disabled and the review states that nothing is queued.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Scan a dense task list (Priority: P1)

As the owner, I can scan a quiet list of compact Tasks on my everyday laptop without card chrome, wrapped actions, Project/List repetition, or excessive scrolling.

**Why this priority**: Fast scanning is the primary value of the redesign and applies before any Task is opened.

**Independent Test**: Render ten representative open Tasks in the desktop list viewport and verify that every collapsed row remains 44 px, titles truncate on one line, Tags remain visible, and no Project/List or Delete action appears.

**Acceptance Scenarios**:

1. **Given** ten open Tasks at a desktop viewport representative of a 13-inch Mac, **When** the list is shown, **Then** all ten collapsed rows fit without a row action wrapping to another line.
2. **Given** a Task with a Project and one or more Tags, **When** its row is collapsed, **Then** the short Tags are visible and the Project/List name is absent.
3. **Given** a long title and several Tags or an agent state, **When** horizontal space is constrained, **Then** the title truncates before controls overlap, wrap, or produce horizontal page scrolling.

---

### User Story 2 - Work with one Task in list context (Priority: P1)

As the owner, I can open the existing Task detail directly below its row, make the same edits and lifecycle changes, then collapse it without losing my place in the list.

**Why this priority**: Removing the side sheet is the central interaction change and preserves the list as the user's spatial frame of reference.

**Independent Test**: Select a Task through its route-backed row, exercise the existing detail controls inline, navigate to the adjacent Task, then close the detail and verify focus returns to the originating row.

**Acceptance Scenarios**:

1. **Given** a collapsed Task row, **When** the owner selects its title or non-control row area, **Then** Task detail expands immediately below that row and no right-side Task sheet or modal scrim appears.
2. **Given** an expanded Task, **When** the owner closes it or activates the same Task row again, **Then** the detail collapses and keyboard focus returns to that Task row when it still exists.
3. **Given** an expanded Task, **When** the owner edits fields, completes or moves the Task, manages subtasks, comments, or agent runs, **Then** existing autosave, conflict recovery, navigation, and state rules remain available.
4. **Given** a URL naming a Task, **When** the page loads or reloads, **Then** that Task is expanded inline so selection remains shareable and recoverable.
5. **Given** a valid URL naming a Task that moved, is excluded by the current filter, or is beyond loaded pages, **When** detail resolves, **Then** the owner is taken to the Task's deterministic canonical list, pages are loaded until its real row is present, and the Task expands below that row.

---

### User Story 3 - Hand a Task to an agent without noisy row copy (Priority: P2)

As the owner, I can start a hand-off for the last-used eligible agent with one compact control, choose a different eligible agent when needed, and understand the latest run state without a sentence-length badge.

**Why this priority**: Agent controls must coexist with dense scanning while preserving the relay's consent and truthfulness guarantees.

**Independent Test**: With the relay flag enabled and eligible connections present, use the robot shortcut and chooser, verify the existing immutable review opens with the expected connection preselected, then render queued, running, needs-user, completed, and failed summaries in equal-size controls with no trailing arrow.

**Acceptance Scenarios**:

1. **Given** a non-terminal Task without a run and at least one eligible connection, **When** the row renders, **Then** it shows a compact split control whose robot is the last-used eligible agent shortcut and whose arrow opens an eligible-agent menu.
2. **Given** no remembered eligible connection, **When** the robot shortcut is used, **Then** it selects the first eligible connection as a deterministic fallback and opens the existing hand-off review.
3. **Given** the robot shortcut or an agent menu choice, **When** it is activated, **Then** the hand-off review opens with that connection selected and no Task content is sent until the owner completes the existing confirmation.
4. **Given** a latest agent run, **When** the row renders, **Then** it shows the agent name and a short honest state such as Queued, Running, Needs you, Reported, or Failed in a 184 × 28 px control, with the exact server-owned state and complete disclosure available to assistive technology and in inline detail.
5. **Given** queued, running, needs-user, completed, or failed states, **When** their controls render, **Then** they share the same bounds and internal alignment, have no dropdown arrow, and pair status text with any status color or icon.
6. **Given** an assigned state control, **When** it is activated, **Then** the Task expands inline and exposes the complete run information and available actions.
7. **Given** the external-agent relay flag is off, **When** a Task has no existing run, **Then** no assignment control appears; existing run summaries remain reachable as before.
8. **Given** an eligible split control while the browser is offline, **When** either side is activated, **Then** the existing review remains inspectable with confirmation disabled and explicitly states that nothing is queued.

### Edge Cases

- A Task with no Tags leaves no placeholder gap before its right-aligned agent control.
- Multiple long Tags truncate or are progressively hidden before the task title or agent control wraps.
- An agent remembered in the browser but now stale, disconnected, changed, or otherwise ineligible is ignored; the first eligible connection becomes the shortcut fallback.
- Duplicate connection names never decide the shortcut; connection identity does.
- Connection loading, no-connections, no-eligible-connections, preview failure, offline, re-review, and reauthentication continue to use the existing hand-off review states.
- A missing or another-owner Task ID receives the existing indistinguishable 404 and shows one non-leaking list-level error/close path; no canonical redirect is attempted without a valid detail response.
- Agent summary loading or failure does not block the Task list; the row remains usable without an agent control until a trustworthy projection exists.
- Needs-user state remains distinguishable without color alone.
- Completing a selected Task first crosses the existing autosave barrier, then collapses
  inline detail as its compact row moves into the Completed group; focus follows that
  completed row, or the next surviving row/list heading if it is not rendered.
- A state/filter change that removes a selected Task from the current projection follows
  the canonical-list rule instead of leaving detached detail behind.
- If the batch summary refresh fails with no cache, all Tasks remain usable without agent controls; if trustworthy cached summaries exist, they remain visible as stale while one non-blocking retry notice is shown.
- Narrow responsive web keeps controls reachable without horizontal page scrolling; this slice does not redesign native mobile.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Every collapsed desktop Task row MUST occupy exactly 44 px vertically, excluding an explicitly expanded detail region.
- **FR-002**: A collapsed row MUST keep the completion control, one-line Task title, short Tags, applicable due/subtask indicators, compact `waiting_for` text for Waiting Tasks, and agent control on one line without action wrapping at supported desktop widths. `waiting_for`, Tags, due, and subtask metadata MUST progressively yield before the title or agent control wraps.
- **FR-003**: A collapsed row MUST NOT display Project/List text or a Delete action.
- **FR-004**: Selecting a Task from a desktop Task list MUST render its existing Task detail immediately below that row and MUST NOT open the Task side sheet, modal scrim, or a second list-obscuring surface. Row activation MUST be bounded to the 44 px header so selecting or clicking plain content inside expanded detail cannot collapse or re-navigate the Task.
- **FR-005**: Inline Task detail MUST preserve route-addressable selection, close and same-row collapse behavior, adjacent-Task navigation, autosave and recovery, Task lifecycle controls, subtasks, comments, and agent run detail. The Task route MUST be the sole open/closed authority: every collapse action, including Cmd/Ctrl+\\, returns to the parent list route; the shortcut is intentionally collapse-only because there is no hidden local panel state to reopen. Before unmounting detail, a collapse MUST flush scheduled edits into the existing autosave controller/journal so an in-flight, failed, or conflicted save remains recoverable. Completing a selected Task MUST cross the existing completion/autosave barrier and collapse detail as its row re-groups. For a valid selected Task absent from the rendered projection, canonical recovery MUST: (1) clear excluding search/date/group filters and retain the current state/Project/Tag route if membership still holds; otherwise (2) choose a resolvable Project, then the Task's open lifecycle state, then `/tasks/next` for a terminal/no-Project Task, adding `showCancelled=1` for cancelled Tasks; (3) perform at most one replace-navigation; and (4) fetch no more than ten sequential pages per recovery attempt, stop on route/filter change or request failure, and expose an explicit Retry/Load more recovery without blocking the list if the real row is still absent.
- **FR-006**: Opening and closing inline detail MUST provide visible focus, update `aria-expanded`, and restore focus to the originating Task row or a deterministic surviving fallback.
- **FR-007**: When external-agent hand-off is allowed for a non-terminal Task with no latest run, the row MUST show a compact split control: the robot chooses the last-used eligible connection and the arrow lists all eligible connections. Each button's accessible name MUST include the Task title. Offline, both remain operable to open the existing review, whose confirmation is disabled and whose copy says nothing is queued.
- **FR-008**: The last-used shortcut MUST use an API-origin- and owner-scoped browser-local `{connectionId, confirmedAt}` record, MUST erase an unavailable, expired, ineligible, or malformed stored identity, and MUST use the first eligible connection as a deterministic fallback. The preference MUST update only after a successfully confirmed dispatch from either row or detail; closing review, preview failure, or an unconfirmed selection MUST leave it unchanged. A production-wired auth subscription MUST erase the departing owner on logout, 401 session loss, account deletion, or A→B identity transition. A cross-identity sweep MUST make records older than 30 days ineligible and erase every expired/malformed feature key at application startup, focus, and the bounded sweep interval while BrainBuddy is running; physical removal while BrainBuddy never runs again is controlled by browser site-data deletion and MUST be disclosed honestly.
- **FR-009**: Both pre-assignment actions MUST enter the existing immutable hand-off review with the chosen connection preselected; they MUST NOT bypass acknowledgement, reauthentication, consent, or confirmation and MUST NOT send Task content on their own.
- **FR-010**: A Task with a latest run MUST show one 184 × 28 px assigned control containing the agent name and a compact state label that preserves provenance and uncertainty; every assigned state control MUST share the same external bounds and internal column alignment. In particular, agent completion MUST read `Reported`, never `Done`, so the row does not imply BrainBuddy verified or completed the Task.
- **FR-011**: An assigned control MUST NOT show a dropdown arrow. Activating it MUST open that Task's inline detail, where the full run projection, tier, cancellation state, last contact, and available actions remain visible.
- **FR-012**: The assigned control's accessible name MUST include the Task title, full agent name, exact server-owned `primary_state_label`, and the full compact relay disclosure, including guarantee tier and cancellation withdrawal when applicable, even though the collapsed visible copy is intentionally shorter.
- **FR-013**: Needs-user, live, terminal-complete, and failure states MUST remain distinguishable by text plus icon or other non-color information; the Task itself MUST remain open after an agent-reported completion.
- **FR-014**: Existing run summaries MUST remain visible when relay rollout is disabled, while creation of new hand-offs remains gated by the existing server-owned feature flag.
- **FR-015**: The redesign MUST add no backend contract, endpoint, request shape, external provider call, or native-mobile behavior. Additional Task-list invocations of the existing owner-scoped connection read and latest-run summary read are permitted; no new network category is introduced.
- **FR-016**: Loading, empty, error, whole-batch agent-summary failure, cached/offline, terminal Task, long-content, unavailable browser storage, and narrow-responsive states MUST keep the primary Task controls usable without overlap or horizontal page scrolling. A failed summary refresh with trustworthy cache MAY retain stale assigned controls with one retry notice; without cache it MUST render no speculative agent control.
- **FR-017**: The user-facing privacy policy and retention schedule MUST state what the last-used-agent browser record contains, that it never reaches the server or account export, its logical 30-day eligibility, its startup/focus/auth-transition cleanup limits, and how browser site-data deletion removes residual bytes.

### Key Entities

- **Collapsed Task row**: A 44 px desktop list projection containing Task identity, completion, selected short metadata, and at most one agent control.
- **Inline Task detail**: The existing Task detail projection rendered beneath the selected row and addressed by the existing Task route.
- **Agent assignment control**: A pre-run split control that chooses an eligible connection but always enters the existing review before sending.
- **Assigned agent state control**: A fixed-size projection of the latest run's agent and honest primary state with a route to full inline detail.
- **Last-used agent preference**: An owner-scoped browser-local connection identifier used only to preselect hand-off review; it grants no authorization and is ignored when ineligible.

### Narrow supersession of feature 014

For the desktop-web collapsed Task row only, **017-FR-010** and **017-FR-012**
narrow the visible-copy clause of **014-FR-013** and the web compact-row portion of
**014-SC-004**. The 184 × 28 control visibly shows agent plus short primary state;
guarantee tier, cancellation withdrawal, missing-agent-task state, and complete relay
disclosure remain in the same control's accessible name and in inline detail. Both web
and iOS still derive meaning from the same server projection, but native iOS retains its
existing fuller visible compact copy in this feature. The existing web compact-row
assertion is intentionally replaced by 017 evidence; all full-detail disclosure tests
remain authoritative.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: At least ten representative collapsed Tasks are fully visible in the ordinary desktop list area at a 1440 × 900 viewport without vertical compression below 44 px.
- **SC-002**: Every collapsed Task row measures 44 px and no row child begins a second visual line at supported desktop widths of 768 px and above.
- **SC-003**: Queued, running, needs-user, completed, and failed assigned controls each measure 184 × 28 px at desktop width and their agent and state columns share the same horizontal coordinates.
- **SC-004**: All changed actions are operable with keyboard alone, expose visible focus and Task-disambiguated accessible names, announce changed loading/error/collapse outcomes through the existing live-region patterns, and introduce no serious or critical accessibility violation on the affected surface.
- **SC-005**: In automated interaction tests, 100% of Task selections open inline with no Task side-sheet dialog or scrim, and closing restores focus to the correct row or documented fallback.
- **SC-006**: In automated hand-off tests, 100% of robot-shortcut and explicit-agent selections open the existing review with the intended eligible connection and make zero dispatch calls before review confirmation.
- **SC-007**: Existing Task mutation, autosave recovery, completion animation, relay review, run monitoring, and rollout-OFF behavior remains passing in affected frontend suites. Assertions that intentionally encoded the old modal/inert sheet, mobile-web slide-over screenshot, or sentence-length web row disclosure MUST be replaced by inline, responsive, and accessible-disclosure evidence rather than preserved verbatim.
- **SC-008**: Automated production-wiring tests prove logout, 401 session loss, account deletion, A→B transition, malformed storage, ineligible identity, and 30-day startup/focus sweep cleanup; policy tests pin the corresponding privacy/retention copy and server-export exclusion.

## Assumptions

- The approved design targets desktop web first; native mobile remains unchanged.
- The existing hand-off overlay remains the sole content-bearing consent and confirmation surface.
- Browser-local last-used connection identity is acceptable because it contains no
  Task content or credential, is owner/API scoped, becomes unusable after 30 days,
  and is erased on identity transition, invalid eligibility, the next global sweep,
  or explicit browser site-data deletion.
- Existing task, connection, and run-summary APIs contain every field needed by this redesign.
- The owner explicitly approved moving the desktop-web compact row's tier and cancellation-withdrawal copy into the accessible name and inline detail on 2026-09-10. Native mobile remains unchanged and visibly fuller.
