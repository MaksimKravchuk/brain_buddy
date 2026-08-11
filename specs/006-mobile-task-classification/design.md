# Design: Assign project and tags from the mobile task screen

**Feature**: `specs/006-mobile-task-classification/`
**Created**: 2026-08-11
**Screens**: `design/*.html` — self-contained, inline CSS, no CDN, no external fonts

## Applicability

This feature has a user-visible surface, designed below. It is mobile-only; the
web client already has this capability and is out of scope, so there are no
`D-` desktop screens.

## Screen inventory

| id | surface | screen | purpose | FR refs |
|---|---|---|---|---|
| M-01 | mobile | Task detail — classification | The whole feature: project and Tags become editable where they are already displayed | FR-001, FR-002, FR-003, FR-013 |
| M-01b | mobile | Task detail — changed offline | A change made with no connection looks exactly like one the server has; only the last-synced footer speaks | FR-006, FR-007 |
| M-01c | mobile | Task detail — rollout flag OFF | With the flag off this is today's read-only screen, unchanged | FR-015 |
| M-02 | mobile | Project picker | Pick one, clear it, or create one | FR-001, FR-003, FR-004, FR-005 |
| M-03 | mobile | Tag picker | Attach and detach several; create is unavailable offline and says why | FR-002, FR-004, FR-005, FR-016 |
| M-04 | mobile | Conflict resolution | The server rejected a queued change by revision; the person chooses | FR-008, FR-012 |
| M-05 | mobile | Discard-unsent warning | Sign-out, account change or server change would lose unsent work | FR-011 |

M-01b and M-01c are listed as screens rather than states because each is a
distinct build of the same route that a reviewer must be able to look at on its
own. Their per-state rows live under M-01.

## State inventory

### M-01 — Task detail, classification

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | task loaded, online | Project and Tags rows, tappable, chevron affordance | — | FR-001, FR-002, SC-001 |
| loading | route opened before the task resolves | Skeleton rows after 300 ms; no spinner before that | — | — |
| empty (first run) | task has no project and no Tags | Rows present with muted placeholders, not hidden | "Add a project", "Add Tags" | FR-001, FR-002 |
| empty (filtered to nothing) | n/a on this screen | — | — | — |
| error | save rejected for any reason other than revision | Row reverts to the server value, inline error, retry | "Could not save. Tap to try again." + correlation id | FR-012 |
| partial failure | **unreachable as specified** — `PATCH /tasks/{id}` is atomic, so no event sequence produces a half-saved task. Open decision 4 | The succeeded half shows as saved, the failed half reverts and is named | "Project saved. Tags could not be saved." | FR-012 |
| offline / interrupted | no connection at the moment of the change | Change applied locally and shown as made. No marker, no banner, no per-row decoration. The footer's last-synced time is the only signal | "Last synced 14 minutes ago" | FR-006, FR-007, SC-004 |
| flag OFF | server-owned flag defaults OFF | Exactly today's screen: values shown, no controls, no disabled affordances | — | FR-015 |

### M-02 — Project picker

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | opened | "None" first with a check when unset, then projects | — | FR-001, FR-003 |
| loading | list not yet fetched | Three skeleton rows | — | — |
| empty (first run) | no projects exist at all | "None" plus the create row only | "No projects yet" | FR-004 |
| empty (filtered to nothing) | search matches nothing | Create row carrying the typed name | "Create \"<typed>\"" | FR-004, FR-005 |
| error | list fetch failed | Inline retry, the current value still shown and still clearable | + correlation id | FR-012 |
| partial failure | n/a — one list, one call | — | — | — |
| offline / interrupted | no connection | Existing projects still selectable — from the list last stored on the device, which survives a cold start; create row disabled with a reason | "Needs a connection — new projects are named by the server" | FR-016 |
| offline, never fetched | offline and this device has never loaded the list | The empty-first-run copy would be a lie here, so it says so and offers no create row | "Can't load your projects without a connection" | FR-016 |

### M-03 — Tag picker

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | opened | Tags with checks on the attached ones; multi-select | — | FR-002 |
| loading | list not yet fetched | Three skeleton rows | — | — |
| empty (first run) | no Tags exist | Create row only | "No Tags yet" | FR-004 |
| empty (filtered to nothing) | search matches nothing | Create row carrying the typed name | "Create \"<typed>\"" | FR-004, FR-005 |
| error | list fetch failed | Inline retry; already-attached Tags still shown | + correlation id | FR-012 |
| partial failure | **unreachable as specified** — `tag_ids` is sent as one intended set, applied whole or not at all. Open decision 4 | Named per Tag, not as one blanket failure | — | FR-012 |
| offline / interrupted | no connection | Existing Tags selectable from the list last stored on the device; create row disabled with the reason visible before it is tapped | "Needs a connection — new Tags are named by the server" | FR-016 |
| offline, never fetched | offline and this device has never loaded the list | Stated plainly rather than shown as "no Tags yet" | "Can't load your Tags without a connection" | FR-016 |

### M-04 — Conflict resolution

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | queued change rejected on revision | Sheet naming what was changed and when, both values side by side, two explicit choices. Naming the change is load-bearing: nothing on the task screen ever said it was in flight | "You changed the project 14 minutes ago. This task changed somewhere else since." | FR-008, SC-005 |
| loading | resolution being sent | Chosen button shows progress; both stay visible | — | — |
| empty | n/a | — | — | — |
| error | the resolution itself fails | Sheet stays open, nothing discarded, retry offered | + correlation id | FR-012, SC-003 |
| partial failure | several conflicted tasks | One sheet per task, queued; count shown | "1 of 3" | FR-008 |
| offline / interrupted | connection lost while the sheet is open | Sheet stays, choice is queued, nothing decided automatically | — | FR-008, SC-005 |
| dismissed | person backgrounds the app | Treated as "not yet answered"; the change stays queued and the sheet returns. Nothing on the task screen records it, so the sheet returning is the only reminder | — | SC-005 |

### M-05 — Discard-unsent warning

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | sign-out, account change or server change with a non-empty queue | The count and which action discards it. **No list** — decided at sign-off | "2 changes have not been sent" | FR-011, SC-007 |
| loading | queue draining while the sheet is open | Count decrements live rather than showing a stale number | — | FR-011 |
| empty | queue empty | Sheet never appears; the action proceeds | — | FR-011 |
| error | drain fails during the wait | Count stays, the person can still choose | + correlation id | FR-012 |
| partial failure | some entries sent, some not | The count reflects only the still-unsent ones | — | FR-011 |
| offline / interrupted | no connection | "Stay and let them send" is disabled with the reason; discarding is still available | "Nothing can be sent without a connection" | FR-006, FR-011 |

## Affordance → requirement map

| screen | affordance | what it does | FR ref |
|---|---|---|---|
| M-01 | Project row | Opens M-02 | FR-001 |
| M-01 | Tags row | Opens M-03 | FR-002 |
| M-01 | Last-synced footer | Says how current the screen is, once, for the whole screen | FR-007, SC-004 |
| M-02 | "None" row | Clears the project | FR-001, FR-003 |
| M-02 | Project row | Selects one, replacing any previous | FR-001, FR-003 |
| M-02 | Search field | Filters, and seeds the create row | FR-005 |
| M-02 | Create row | Creates and attaches in one action | FR-004 |
| M-03 | Tag row | Toggles attach/detach | FR-002 |
| M-03 | Create row | Creates and attaches in one action | FR-004 |
| M-03 | Create row, disabled | States why creation needs a connection, before it is tapped | FR-016 |
| M-04 | "Keep mine, replace theirs" | Re-sends against the current revision | FR-008 |
| M-04 | "Discard mine, keep the server's" | Drops the queued entry | FR-008 |
| M-04 | Correlation id | Makes the rejection reportable | FR-012 |
| M-05 | "Stay and let them send" | Cancels the identity transition | FR-011 |
| M-05 | "Discard N changes and continue" | Proceeds, discarding. The count is the whole of what the person is told | FR-011, SC-007 |

### Requirements with no affordance

- **FR-009** (queue survives restart) — no control; observable as the queue and
  its markers still being there after a cold start.
- **FR-010** (net effect of several queued changes) — deliberately invisible.
  The person sees one pending state per task, never a list of operations.
- **FR-014** (no task route, no web change) — an architectural constraint.
- **FR-017** (at most once) — correctness with no surface. Its absence would be
  visible, though: a double-applied change is what a person would report as the
  app undoing their work.
- **FR-015** has the M-01c state rather than a control: the flag is
  server-owned, so there is nothing for a person to toggle here.

### Affordances with no requirement

- None.

## Primary loop impact

The loop is capture → atomic items → **clarify/approve** → route or CRT
candidate → smart Weekly Review → evidence/results. This lands squarely in
clarify/approve. Capture already happens on the phone; classification does not,
so the loop currently breaks across two devices at exactly this step. Nothing
else in the loop changes: no capture surface, no CRT canvas, no Weekly Review.

## Mobile viability

- **Viewport**: designed and checked at 390×851; no horizontal scroll. Long
  project names truncate with an ellipsis rather than widening a row.
- **Tap targets**: 44 pt minimum honored. Rows are 52 px, buttons 48 px, nav
  buttons 44×44.
- **One-handed reach**: the two destructive or consequential choices (M-04,
  M-05) are bottom sheets, so the buttons sit in the lower third. The
  non-destructive option is always the upper of the two.
- **Destructive actions**: M-05 states the count and that the discard cannot be
  undone. It does **not** name the items — decided at sign-off. Combined with
  the removal of the per-change marker, the consequence is that a person can
  discard work they were never able to identify; that is the accepted trade,
  recorded here so it is visible to review rather than discovered later. M-04
  discards nothing until a choice is made.

## Keyboard and focus

- **Tab order**: search field → option rows in visual order → create row. In
  the sheets: heading → the two buttons, non-destructive first.
- **Focus on open**: M-02 and M-03 focus the search field. M-04 and M-05 focus
  the sheet heading, not a button, so no destructive action is one keypress
  from an accidental confirm. **Focus restored on close to**: the row that
  opened the picker.
- **Escape**: closes a picker, discarding nothing. On M-04 and M-05 it is the
  same as the non-destructive choice, and it never resolves a conflict.
- **Accessible names**: the chevrons are decorative and hidden from assistive
  technology; the row itself carries the name and current value. The
  last-synced footer is a live region that announces only when the time changes
  materially, not on every tick.
- **State communicated by color alone**: none. The disabled create row states
  its reason in text rather than relying on being greyed, and the last-synced
  footer is words rather than a colored dot.

## Design authority

- Tokens, colors, type and UI kit from the `brain-buddy-design` skill.
- Vocabulary check (ADR-0006, `Tag` not the forbidden alternatives): pass
- `python3 -m unittest scripts/test_validate_brain_buddy_design_skill.py`: pass

## Human sign-off

Signed off by MaksimKravchuk on 2026-08-11, after one round of changes. The
first presentation was declined on the not-sent marker; the revision removing
it, and the count-only discard warning, were both accepted.

## Decisions taken at sign-off

1. **Resolved at sign-off, and it reversed an earlier answer: there is no
   not-sent marker at all.** The human's instruction was to hold the data on the
   device until there is a connection and show only when the last sync happened.
   The consequence to watch is that unsent work is now invisible on the task
   screen — the only surfaces that reveal it are the last-synced time, which
   says *when* and never *what*, and the discard warning at M-05, which is also
   the last moment to act on it. That is why M-04 must name what was changed: a
   person can reach a conflict prompt for a change nothing ever told them was in
   flight. M-05 does **not** name them — decision 2 below was taken in the same
   session and deliberately went the other way, which is the whole reason both
   decisions are recorded separately here.
2. **Resolved at sign-off: M-05 shows the count only, no list.** With the
   per-change marker also gone, no surface in the app names an unsent change.
   The person can learn that two changes exist and that continuing destroys
   them, but never which two. Recorded as the decision it is, so the review
   lenses can weigh it rather than assume it was an oversight.
3. **The flag-off state is today's screen exactly** — values shown, no controls
   at all. The alternative is showing disabled rows so the capability is
   discoverable before rollout, at the cost of advertising something nobody can
   use yet.
