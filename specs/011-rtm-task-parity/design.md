# Design: RTM task-management parity

**Feature**: `specs/011-rtm-task-parity/`
**Spec**: `spec.md` (Max's HD-01…HD-09 answers recorded)
**Planning authority**: numbered states and exact copy below
**Founder design decision**: Max, 2026-08-15 — numbered states are sufficient for planning
**Rendered delivery evidence**: screenshots/video mandatory before acceptance (SC-015)

Ids assigned here are stable forever. `plan.md` cites them; the acceptance auditor traces
criteria through them. ADR-0006 vocabulary applies: the user-facing word is **Tag**, and the
user-facing word for a Project is **List**.

## Applicability

This feature has a user-visible surface on both clients, so a design stage is mandatory and
the state inventory below is load-bearing.

This planning stage intentionally did **not** produce static HTML mockups under `design/`.
Max accepted the numbered state inventory as the planning authority (HD-09). This feature adds
capabilities to surfaces that already exist and already have settled visual language —
`frontend/src/features/tasks/TaskListPage.tsx` and `TaskDetailPanel.tsx`,
`mobile/src/features/tasks/TaskListScreen.tsx` and `mobile/src/app/task/[id].tsx`. The
design risk here is **state coverage and semantics**, not layout: whether "archived List"
has a reachable view, whether a destructive delete says what it will and will not destroy,
whether a trashed task is distinguishable from a cancelled one. Those are decided in the
tables below and traced by id.

Rendering remains a delivery obligation: before `/speckit-accept`, the implementation must
capture desktop/mobile screenshots for every D-/M- state group and a keyboard plus
VoiceOver/TalkBack video showing modal entry, announcement, cancellation, success, and
focus restoration. Missing evidence rejects acceptance; it does not reopen HD-09.

## Screen inventory

Existing surfaces gain states; two views are new.

| id | surface | screen | purpose | FR refs |
|---|---|---|---|---|
| B-01 | backend | Task command surface | create/read/update/lifecycle incl. trash, restore and explicit erasure | FR-001…FR-016, FR-038, FR-039 |
| B-02 | backend | List command surface | create/list/read/rename/archive/unarchive/delete | FR-017…FR-021 |
| B-03 | backend | Tag command surface | create/list/rename/global delete, incremental task tagging | FR-009, FR-010, FR-022, FR-023, FR-037 |
| B-04 | backend | Task query surface | search, typed filters, order, pagination, history | FR-024…FR-029 |
| D-01 | web | Task list | filter, search, page, open history | FR-024…FR-029 |
| D-02 | web | Task detail | edit every field, run lifecycle incl. trash/restore | FR-001…FR-016 |
| D-03 | web | List & Tag management | rename/archive/unarchive/delete List, rename/delete Tag | FR-017…FR-023 |
| D-04 | web | Archived Lists view (**new**) | make unarchive reachable | FR-019 |
| D-05 | web | Trash view (**new**) | restore or explicitly erase Trash | FR-012, FR-013, FR-037…FR-039 |
| M-01 | mobile | Task list | same as D-01 | FR-024…FR-029 |
| M-02 | mobile | Task detail | same as D-02 | FR-001…FR-016 |
| M-03 | mobile | List & Tag management (**new on mobile**) | closes the C-68 tier gap | FR-017…FR-023, FR-030 |
| M-04 | mobile | Archived Lists + Trash | same as D-04/D-05, one stacked screen | FR-012, FR-013, FR-019, FR-037…FR-039 |

## State inventory

### B-01…B-04 — backend command and query surfaces

Backend "states" are response classes. Each row is a contract, not a rendering.

| state | trigger | what the caller observes | FR/SC refs |
|---|---|---|---|
| success | valid command, current revision | `200`/`201` with the full updated projection or redacted deletion receipt and `X-Correlation-ID` | FR-001…FR-039 |
| replay | same idempotency key, command and canonical body | byte-identical prior response; zero additional mutation; a delete receipt never reconstructs its subject | FR-015, SC-009 |
| key conflict | same key, different command or body | `409`, no mutation | FR-015 |
| stale revision | `expected_revision` behind current | `409` naming the entity, no mutation | FR-016 |
| invalid transition | e.g. restore on a task that is not trashed, or edit a trashed task | `400` with an actionable message, no mutation | FR-016, FR-039 |
| invalid shape | unknown field, bad enum, due time with no due date | `422` with the offending field named | FR-007, FR-016 |
| unknown filter | unrecognized query parameter | sanitized `400` listing supported parameters without reflecting raw input | FR-027, SC-007 |
| not found / not yours | absent or other-owner id | `404`, indistinguishable between the two cases | FR-031 |
| unauthenticated | missing or invalid session | `401` | FR-031 |

### D-01 / M-01 — Task list

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | filters applied | rows in the documented stable order, with the active filter set visible | "{N} tasks · Sorted by {sort}." | FR-025, FR-028 |
| loading | request in flight | skeleton rows after 200 ms; the previous result stays until replaced | "Updating tasks…" | FR-024 |
| empty (first run) | owner has no tasks | invitation to capture a first task | "Nothing here yet." | FR-001 |
| empty (filtered) | filters match nothing | distinct from first-run, and names the filters that excluded everything, with a one-tap clear | "No tasks match these filters." | SC-007 |
| paging | more results exist | explicit continuation control; never presents page one as the total | "Load more tasks" | FR-028, SC-008 |
| cursor invalidated | filters changed mid-page | restarts at page one rather than mixing result sets | "Filters changed. Showing the first page." | FR-028 |
| history | completed / cancelled / trashed filter active | history rows are visually distinct from open rows and labelled with which history they are | "Showing {Completed|Cancelled|Trash}." | FR-029 |
| error | request failed | retry control plus the correlation id | "Couldn't load your tasks. Try again. Reference: {correlation_id}." | FR-016 |
| offline / interrupted | connectivity lost (mobile) | last successful result with a stale marker; on resume, refetch from page one | "Offline · showing saved results from {time}." | ADR-0002 |

### D-02 / M-02 — Task detail

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | task opened | every editable field, and the lifecycle actions that are currently valid | "Task details" | FR-001…FR-014 |
| loading | task detail request in flight | detail skeleton after 200 ms; no stale task is presented as the requested task | "Loading task…" | FR-001 |
| editing | field focused | pending value with an explicit save/commit path; unsaved input survives a failed save | "Unsaved changes" | FR-002…FR-008 |
| unsaved navigation | user tries to leave with an uncommitted field | navigation pauses and offers Stay or Discard; it never silently drops the edit | "Discard unsaved changes?" | FR-002…FR-008 |
| invalid input | due time with no due date | inline message on the offending field, save blocked | "Set a due date before a due time." | FR-007 |
| trashed | task is trashed | banner stating the task is in Trash, its commitment state preserved and named, and a Restore action; editing is disabled | "In Trash · was Next" | FR-011…FR-013 |
| destructive confirm | Trash pressed | confirmation naming what happens and what does not | "Move to Trash? It keeps its state and you can restore it." | FR-011 |
| permanent-delete confirm | Permanently delete pressed | confirmation names all erased child content and the audit-only residue | "Delete this task forever? The task, its subtasks, and comments will be erased. Only a content-free audit receipt remains. This can't be undone." | FR-037, FR-038 |
| unsupported priority | decoder receives an unrecognized priority | value is preserved, Save is disabled for priority only, and no false rank/color is shown | "Priority unavailable. Update BrainBuddy before changing it." | FR-006 |
| conflict | stale revision | refetch, keep the user's unsaved input, offer explicit retry — never silently overwrite | "This task changed elsewhere." | FR-016 |
| agent run present | a handoff exists | run state shown as clearly separate from task state, with no control that changes one from the other | "Agent run · does not change task status" | FR-032, SC-010 |
| error | command failed | actionable message plus correlation id; no optimistic success | "Couldn't save this task. Try again. Reference: {correlation_id}." | FR-016 |
| offline / interrupted | mobile | queued intent is visible as pending, never as done; resolves against the server on resume | "Waiting for connection. Not saved yet." | ADR-0002 |

### D-03 / M-03 — List & Tag management

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | management opened | active Lists with open counts, Tags with open usage counts | "Lists and Tags" | FR-017, FR-022 |
| loading | initial management request in flight | existing rows remain stale-labelled, or skeleton rows appear after 200 ms when none are cached | "Updating Lists and Tags…" | FR-017, FR-022 |
| empty | none created | invitation to create the first one | "No Lists or Tags yet. Create one to organize tasks." | FR-017, FR-022 |
| archive confirm | Archive pressed | states that tasks keep their membership and the List stops accepting new tasks | "Archive this list? Its tasks keep it and you can unarchive later." | FR-018 |
| delete confirm | Delete pressed | states exactly what is destroyed (the List) and what is not (the tasks); requires explicit confirmation | "Delete this list? Its N tasks stay, unassigned. This can't be undone." | FR-020, SC-005 |
| tag delete confirm | Delete Tag pressed | same shape, for the classification | "Delete this tag? It's removed from N tasks. The tasks stay." | FR-023, SC-005 |
| in flight | command submitted | the affected row is disabled with a pending marker; the rest stays usable | "Saving {name}…" | FR-015 |
| partial failure | one of a multi-record refresh failed | names which record did not update and offers a retry for that one | "{name} may be out of date. Retry this row." | FR-016 |
| conflict | stale revision | refetch and re-present, never auto-retry a destructive command | "{name} changed elsewhere. Review it before trying again." | FR-016 |
| error | command failed | actionable message plus correlation id | "Couldn't update {name}. Try again. Reference: {correlation_id}." | FR-016 |
| offline / interrupted | mobile loses connectivity during a command | no optimistic success; pending input stays visible, and resume refetches before offering an explicit retry | "Waiting for connection. No change was confirmed." | FR-016, ADR-0002 |

### D-04 / M-04 — Archived Lists and Trash

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | view opened | archived Lists / trashed tasks with when they were archived or trashed | "Archived Lists and Trash" | FR-012, FR-019 |
| loading | either view request in flight | its section shows skeleton rows after 200 ms without presenting cached rows as current | "Updating Archived Lists and Trash…" | FR-012, FR-019 |
| empty | nothing archived or trashed | plain statement, not an error | "Nothing archived." / "Trash is empty." | FR-012, FR-019 |
| restore in flight | Restore or Unarchive pressed | pending marker on that row | "Restoring…" / "Unarchiving…" | FR-013, FR-017 |
| restored | success | the row leaves this view and its destination is named | "Restored to Next." | FR-013, SC-003 |
| empty-trash confirm | Empty Trash pressed | names item count and irreversible erasure; Cancel is initial focus | "Empty Trash? {N} tasks, including their subtasks and comments, will be erased. Only content-free audit receipts remain. This can't be undone." | FR-037, FR-038 |
| conflict | stale revision | refetch; the row may already be gone, which is stated rather than shown as an error | "This item changed elsewhere. The latest Trash view is shown." | FR-016 |
| partial refresh | one section or row refresh fails while others succeed | the stale section/row is named and gets its own retry; successful rows remain usable | "Couldn't refresh {section}. Other results are current." | FR-016 |
| error | command failed | actionable message plus correlation id | "Couldn't update {section}. Try again. Reference: {correlation_id}." | FR-016 |
| offline / interrupted | mobile loses connectivity | last confirmed rows remain stale-labelled; resume refetches both sections before another mutation | "Offline · showing saved results. Reconnect before making changes." | ADR-0002 |

## Affordance → requirement map

| screen | affordance | what it does | FR ref |
|---|---|---|---|
| D-02 / M-02 | due date + optional time picker | sets or clears both | FR-003, FR-004 |
| D-02 / M-02 | start date + optional time picker | sets or clears both | FR-005 |
| D-02 / M-02 | priority selector showing `1 — High`, `2 — Medium`, `3 — Low`, `None` | sets priority | FR-006 |
| D-02 / M-02 | per-tag add and remove | incremental tagging only; never resends the whole set | FR-009 |
| D-02 / M-02 | List selector | assigns or clears membership | FR-008 |
| D-02 / M-02 | Trash / Restore | orthogonal soft delete and its reversal | FR-011, FR-013 |
| D-02 / M-02 | Permanently delete | confirmed task-content erasure from Trash only | FR-037, FR-038 |
| D-02 / M-02 | Complete / Reopen with explicit destination | lifecycle | FR-014 |
| D-03 / M-03 | rename, Archive, Unarchive, Delete on a List | List management | FR-017…FR-020 |
| D-03 / M-03 | rename, Delete on a Tag | Tag management | FR-022, FR-023 |
| D-01 / M-01 | search box, typed filter controls, history toggles, continuation control | query surface | FR-024…FR-029 |
| D-04 / M-04 | entry point to archived Lists and Trash; Empty Trash | makes restore/unarchive/explicit erasure reachable | FR-012, FR-013, FR-019, FR-037, FR-038 |

### Requirements with no affordance

- FR-010 (whole-set tag replacement) — an API-level verb kept so the incremental verb is
  honest; no client control exposes it.
- FR-021 (Inbox is virtual) — the absence of rename/archive/delete controls on Inbox **is**
  the requirement.
- FR-026, FR-027, FR-031, FR-032, FR-033, FR-034, FR-035, FR-036, FR-039 —
  contract, export, cache-coherence and documentation requirements with no new user control.

### Affordances with no requirement

None. Every control above traces to an FR.

## Primary loop impact

See `spec.md` §Primary loop impact. This design adds no capture surface and changes no
confirmation contract; the Voice Brain Dump entry path into the Inbox projection is
untouched.

## Mobile viability

- **Viewport**: designed for 390×851 with no horizontal scroll. The new M-03 management
  screen is a vertical list of rows with trailing actions; M-04 stacks archived Lists above
  Trash under one scroll.
- **Tap targets**: 44 pt minimum, including the per-tag remove control, which is the
  smallest new affordance and the one most at risk.
- **One-handed reach**: destructive actions (Delete List, Delete Tag, Trash) sit behind a
  confirmation sheet rather than in the thumb-swipe zone, so an accidental reach cannot
  destroy anything in one gesture.
- **Destructive actions**: every confirmation names what is lost and what survives — see
  the copy column in D-03/M-03. "Trash" is explicitly reversible in its own copy so it does
  not read as deletion.

## Keyboard and focus

- **Tab order**: filters → results → row actions on D-01; field order top-to-bottom on D-02
  with lifecycle actions last.
- **Detail/view entry**: D-02 focuses the task-title heading after its accessible name is
  announced; D-04/D-05 focus the view heading. M-02/M-04 use the equivalent accessibility
  focus after navigation settles, never the destructive action.
- **Confirmation entry**: web moves DOM focus to **Cancel**, the least-destructive action,
  after the dialog title and complete consequence text are associated by
  `aria-labelledby`/`aria-describedby`. Native sheets set modal accessibility, announce
  title then consequence, and place VoiceOver/TalkBack focus on **Cancel**. The destructive
  button's accessible name includes the subject, for example `Delete list Work forever`.
- **Modal containment/dismissal**: web confirmations trap Tab/Shift+Tab; Escape performs
  Cancel. Native `onAccessibilityEscape` performs Cancel. Neither dismissal mutates.
- **Focus restoration**: Cancel/error returns focus to the exact trigger. Success returns to
  that trigger when it still exists; if deletion/removal destroyed it, focus moves to the
  next row, otherwise the section heading. Empty Trash success focuses the `Trash is empty`
  status. No focus is sent to a detached element.
- **Announcements**: in-flight and refresh messages use a polite live region; validation,
  failure, correlation ID, and destructive success use an assertive announcement exactly
  once. Row removal is announced with the destination or erasure result before focus moves.
- **Offline/resume**: VoiceOver/TalkBack announces `Offline · showing saved results` once.
  On reconnection it announces `Back online. Results updated.` only after both sections
  refetch; no mutation control re-enables before that read-back.
- **Accessible names**: the per-tag remove control, the priority selector options, and the
  archived/trash entry points are all icon-capable and each carries an explicit label.
- **State communicated by color alone**: none. Priority uses a numeral as well as color;
  trashed and history rows carry a text label as well as reduced emphasis.

## Design authority

- Existing repository task surfaces supply tokens, colors, type and components; no new
  visual language is introduced.
- Vocabulary check (ADR-0006 — **Tag**, not the retired classification word): pass.
- The design-skill validator was not run: this stage produced no HTML or design-skill
  asset for it to validate.

## Decision and acceptance status

Max resolved all planning design questions in HD-01…HD-09 on 2026-08-15. Numbered states
are sufficient for planning. Implementation remains prohibited until campaign 2 closes,
and final acceptance remains prohibited until SC-015's screenshots and keyboard plus
screen-reader video exist. HD-10 is a separate fresh-digest risk sign-off, not design
approval and not implied by this section.
