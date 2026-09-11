# Research: Compact Task Rows

## Decision 1 — Reuse the Task route as the inline-selection authority

**Decision**: Keep `/tasks/:state/:taskId`, `/projects/:projectId/:taskId`, and
`/tags/:tagId/:taskId` as the selected-Task state. Insert the existing detail panel
under the matching row instead of copying its state into a local accordion model.
When a valid selected Task is absent, clear excluding filters and retain the current
state/Project/Tag route when membership still holds. Otherwise prefer a resolvable
Project, then the open lifecycle state, then `/tasks/next` for terminal/no-Project
Tasks (`showCancelled=1` for cancelled). Replace at most once and automatically walk
at most ten pages, aborting on route/filter change; failure or exhaustion exposes
Retry/Load more instead of looping. A missing/another-owner 404 has no valid detail
response, so it shows one non-leaking list-level error and never redirects.

**Rationale**: Reload, Back/Forward, adjacent navigation, deep links, autosave
controller lookup, and query-cache ownership already follow the route. A second local
selection authority would drift.

**Alternatives considered**: local-only expanded IDs (rejected: not shareable or
recoverable); a new nested route (rejected: no user outcome and more contract surface).

## Decision 2 — Add an inline layout variant to the existing detail component

**Decision**: Preserve `TaskDetailPanel` behavior and add an additive layout variant
that removes full-height sheet chrome/sticky assumptions. `TaskListPage` stops
composing `TaskSideSheet`; the sheet component itself is not deleted. Inline close
flushes scheduled edits into the existing keyed autosave controller/journal before
route collapse; that controller owns completion or recovery after unmount. Completion
uses the existing autosave barrier, collapses detail, and then lets the compact row
re-group under Completed. No outgoing duplicate panel or exit animation is retained.

**Rationale**: The detail owns mature autosave, lifecycle, subtask, comment, run,
recovery, and accessibility behavior. Forking it would create two Task editors.
Closing on completion avoids remounting one editor across separate open/completed list
groups while still preserving pending edits through the existing controller journal.

**Alternatives considered**: new inline detail component (rejected: duplicate state
machine); convert `TaskSideSheet` itself into a polymorphic wrapper (rejected: mixes
modal focus-trap logic with non-modal content).

## Decision 3 — Store only an owner/API-scoped connection ID

**Decision**: Store the last confirmed hand-off connection ID and confirmation time in
`localStorage` under a versioned key containing the normalized API origin and
authenticated owner ID. Resolve it against the current `ready_for_handoff` set and
fall back to the first eligible connection. Clear it after 30 days, on sign-out or
identity transition, and as soon as the stored ID resolves ineligible. A process-global
auth subscriber clears the departing owner on logout, 401, deletion, or A→B transition;
a startup/focus/interval sweep scans all feature keys for malformed/expired records.
Eligibility ends after 30 days. Physical bytes on a browser that never runs BrainBuddy
again require browser site-data deletion, which the privacy copy states honestly.

**Rationale**: Connection identity, not display name, survives duplicate labels. API
and owner scoping prevent cross-account/environment reuse. Eligibility resolution
means the preference cannot grant authority or revive a stale connection. Unlike the
tab-local autosave draft, a remembered agent is intentionally useful across tabs and
browser restarts; the bounded `localStorage` lifecycle provides that value without
creating an indefinite device record.

**Alternatives considered**: agent name (rejected: non-unique); server preference
(rejected: new contract/persistence); derive from latest visible run (rejected: not
necessarily the user's last choice and unavailable before the first run);
`sessionStorage` (rejected: loses the explicitly remembered choice on restart).

## Decision 4 — Keep offline review inspectable

**Decision**: Connectivity does not hide or disable the split trigger. It can open the
existing review offline; the review remains readable, disables confirmation, and says
that nothing is queued.

**Rationale**: This preserves an already-shipped consent/review state and avoids layout
movement. Opening review still sends nothing.

**Alternatives considered**: hide the split (rejected: unstable affordance); disable it
(rejected: prevents inspecting the manifest and eligibility state).

## Decision 5 — The shortcut opens review; confirmation remains the only send

**Decision**: Both robot and chooser produce an `AgentHandoffSeed` and mount the
existing `AgentHandoffOverlay`. Remember the ID only after `onDispatched` succeeds.

**Rationale**: The overlay already provides immutable manifest review,
acknowledgement, reauthentication, idempotent confirmation, and actionable errors.
Remembering only a confirmed choice avoids treating an abandoned preview as intent.

**Alternatives considered**: direct row dispatch (rejected: violates Constitution
Principle I and the 014 immutable-manifest review contract); remember on menu
selection (rejected: records an uncompleted choice).

## Decision 6 — Separate compact visible copy from complete disclosure

**Decision**: Keep `compactRunLabel` as the complete disclosure. Add a pure compact
state projection for the visible 184 × 28 control and use the complete disclosure plus
exact `primary_state_label` in the accessible name. Map `Agent reported complete` to
`Reported`, never `Done`.

**Rationale**: Density and truthfulness are both requirements. The Task checkbox is
the only Task-completion authority.

**Alternatives considered**: truncate the old sentence visually (rejected: unstable
geometry); visible `Done` (rejected: implies verified Task completion); alter server
labels (rejected: contract change).

## Decision 7 — One fixed rail and progressive metadata disclosure

**Decision**: Use a fixed 184 px assigned-control rail and a 54 px pre-assignment
slot, both centered in 44 px hit areas. Title truncates; due/subtask/Tags progressively
hide at narrow widths before controls wrap. Row height remains exact.

**Rationale**: This realizes D-01 and D-04 while keeping state columns directly
comparable and keyboard targets reachable.

**Alternatives considered**: content-width pills (rejected: ragged alignment); wrap
metadata (rejected: violates the accepted density); shrink hit targets to 28 px
(rejected: weak touch/keyboard affordance at narrow responsive width).
