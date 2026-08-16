# Feature Specification: RTM task-management parity

**Feature Branch**: `011-rtm-task-parity`

**Created**: 2026-08-15

**Status**: Planning repaired; implementation prohibited until the campaign-2 gate closes

**Input**: `intake.md` — portable founder brief and Max's named 2026-08-15 answers to
HD-01…HD-09; `research.md` embeds the portable source provenance and campaign-1 carry-forward.

**Current-behavior authority**: `capability-matrix.md`. This spec cites row ids (`C-nn`)
and does not restate current behavior. Where a requirement says "today", the evidence is
in that file.

## Clarifications

### Session 2026-08-15 (portable brief plus named founder answers)

The projected brief's two ADR conflicts and campaign 1's seven additional product
questions are now settled by Max's named 2026-08-15 answers HD-01…HD-09 in `intake.md`.
ADR-0020 records only the priority and archive supersessions. These answers are product
authority; they are not HD-10 high-risk approval and are not bound to campaign 2's as-yet
unknown digest.

- **Q: Does trashing a task reuse `cancelled`?** → No. Trash is an **orthogonal** axis
  (a `trashed_at`-style marker) layered over the unchanged
  `inbox|next|waiting|someday|completed|cancelled` states. A trashed task retains its
  commitment state; restore reveals exactly that state and all metadata. Rationale: RTM
  Trash is deletion, `cancelled` is an outcome, and collapsing them destroys the
  distinction the product already sells. (Settled — does not touch ADR-0006.)
- **Q: What is the public priority vocabulary and label?** → `1 | 2 | 3 | none`, `1`
  highest. Labels are exactly `1 — High`, `2 — Medium`, `3 — Low`, `None`. All clients and
  persisted projections converge through FR-006's staged compatibility contract. (Max,
  HD-01/HD-02; ADR-0020.)
- **Q: Do due/start carry timezone semantics?** → No. Local calendar date plus an optional
  **floating** local time, with no reminder, timezone or DST promise. This is a deliberate
  divergence from RTM, whose reminders are timezone-bound; it is revisited only in the P1
  reminders slice. (Settled — does not touch ADR-0006.)
- **Q: What does archiving a List do to its member tasks?** → It retains membership,
  removes the List from active navigation, and blocks new assignment until unarchive.
  Existing archived membership may survive an unrelated Task PATCH. (Max, HD-03;
  ADR-0020.)
- **Q: What does deleting a List do to its member tasks?** → It atomically unassigns them.
  It never deletes, completes, cancels or trashes a member task. It is separately confirmed
  and idempotent. (Settled independent of OD-2: unassignment on delete holds whichever way
  OD-2 resolves.)
- **Q: Is Inbox a List?** → No. It stays the virtual server projection defined in
  `docs/projectless-inbox-contract.md` (`state=inbox AND project_id IS NULL`). There is no
  Inbox row, so there is nothing to rename, archive or delete. (Settled.)
- **Q: How do typed filters compose?** → AND across different fields, OR within repeated
  values of one field. Negation, grouping and saved queries are P1. (Settled.)
- **Q: Does agent execution affect Task lifecycle?** → Never. Routing or starting an agent
  does not complete, trash or transition a Task, and no Task command writes Run state.
  (Settled.)
- **Q: What does restore do after a List or Tag changes while the task is trashed?** → It
  clears only `trashed_at`; it does not apply a pre-trash snapshot. The commitment state and
  ordinary fields remain as stored, while a legitimate later List/Tag deletion stays in
  force. (Max, HD-04.)
- **Q: How long does Trash retain tasks?** → No automatic purge. A trashed task is retained
  until the user explicitly and separately confirms permanent deletion or Empty Trash, or
  until the existing account purge. (Max, HD-05.)
- **Q: What survives List/Tag deletion?** → The name and record are erased immediately.
  A durable owner-scoped audit retains only IDs, action, and time for the life of the
  account; it is included in export and erased by account purge. (Max, HD-06.)
- **Q: Which P0 writes are idempotent?** → Every P0 mutation, over the exact command
  inventory in FR-015. (Max, HD-07.)
- **Q: When may numeric priority become the default response/storage vocabulary?** → Only
  after the release-evidence owner verifies every active internal backend, web, and
  installed mobile build. Missing or unknown inventory blocks the switch. (Max, HD-08.)
- **Q: Are rendered designs required now?** → The numbered state inventory is sufficient
  for planning; screenshots/video for D-01…D-05 and M-01…M-04 are mandatory delivery
  evidence before acceptance. (Max, HD-09.)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Manage Lists and Tags safely (Priority: P1)

A user reorganizes their system: renames a List, archives one they are not working on now,
brings it back later, deletes one for good, and prunes their tags — without ever losing a
task and without silently losing a List assignment.

**Why this priority**: it is the substrate. Trash, restore and the new filters all sit on
top of the List/Tag contract, and the two behavioral divergences (C-36, C-39) live here.
Landing it first means every later slice builds on settled semantics.

**Independent Test**: fully testable through List and Tag management alone — create a List,
assign tasks, archive, confirm the tasks keep their membership and stop appearing in active
navigation, unarchive, confirm they are reachable again, delete, confirm the tasks survive
unassigned.

**Acceptance Scenarios**:

1. **Given** a List with one open, one completed and one cancelled member task,
   **When** the owner archives the List, **Then** all three tasks keep their List
   membership, none changes lifecycle state, and the List no longer appears in active
   navigation.
2. **Given** an archived List, **When** the owner tries to assign a new task to it,
   **Then** the command is rejected with an actionable message and no task is created.
3. **Given** an archived List, **When** the owner unarchives it, **Then** it returns to
   active navigation with its members intact and accepts new assignment again.
4. **Given** a List with member tasks, **When** the owner confirms deletion, **Then** every
   member task survives with its lifecycle state unchanged and its List membership cleared,
   the List name is erased, a redacted audit entry contains only IDs/action/time, and
   replaying the same delete command returns the same redacted receipt without recreating
   the List.
5. **Given** a task carrying three tags, **When** the owner removes one tag from that task,
   **Then** the other two remain, and no other task is affected.
6. **Given** a tag used by several tasks, **When** the owner deletes the tag globally,
   **Then** every task loses that classification, keeps all its other tags, and none is
   deleted or completed; the Tag name is erased and only the redacted audit remains.
7. **Given** any of the above performed on mobile, **When** the owner reloads,
   **Then** the observed result matches the web and backend result.

---

### User Story 2 - Edit a task's real fields and move it through its life (Priority: P2)

A user opens a task and sets what actually matters: when it is due, when it can start, how
important it is, which List it belongs to, which tags it carries. Then completes it,
reopens it, trashes one they no longer want, and restores it when they change their mind.

**Why this priority**: this is the visible product value, but it depends on Story 1's
entity contract for List membership and tag semantics.

**Independent Test**: testable through one task's detail surface — set every field, reload,
confirm persistence, then walk complete → reopen → trash → restore and confirm the task
returns exactly as it was.

**Acceptance Scenarios**:

1. **Given** an open task, **When** the owner sets a due date and an optional due time, a
   start date and an optional start time, and a priority, **Then** all values persist
   across reload on every tier and render identically.
2. **Given** rollout stage 1, **When** a stale client omits the numeric-priority capability,
   **Then** it receives only the legacy vocabulary; **given** the operational gate is green
   and stage 2 has switched, **when** a current client reads the same task, **Then** the
   public value is one of `1`, `2`, `3`, `none` and the exact label is rendered.
3. **Given** a completed task, **When** the owner reopens it, **Then** the destination open
   state is explicit and required; the server never infers it.
4. **Given** an open task, **When** the owner trashes it, **Then** the task disappears from
   normal lists, its commitment state is preserved unchanged, and it is reachable through
   an explicit trashed view.
5. **Given** a trashed task whose List or Tag was legitimately deleted afterward, **When**
   the owner restores it, **Then** only the Trash marker clears: its preserved commitment
   state and remaining metadata return, and the deleted classification is not resurrected.
6. **Given** any P0 mutating command, **When** the client retries it with the same
   idempotency key and body, **Then** the original result is returned and nothing mutates
   twice.
7. **Given** an invalid lifecycle command, **When** it is submitted, **Then** it is rejected
   with an actionable message and nothing mutates.
8. **Given** a task with a running agent handoff, **When** that run reaches any state,
   **Then** the Task's own lifecycle state and trashed marker are unchanged.
9. **Given** one or more trashed tasks, **When** the owner separately confirms permanent
   deletion or Empty Trash, **Then** the selected task content is erased, a redacted audit
   receipt remains, and replay cannot resurrect any task, subtask, comment or classification.

---

### User Story 3 - Find anything, including history (Priority: P3)

A user searches by words in a task's name or notes, narrows by List, tag, status, priority
and date windows, pages through more results than fit on one screen, and looks back at what
they already finished or threw away.

**Why this priority**: highest leverage once the data exists, and it depends on Story 2's
new fields to filter on.

**Independent Test**: testable through the list surface alone against a seeded set — apply
each filter, assert the returned set and the count, page to the end, and confirm ordering is
identical across repeated requests.

**Acceptance Scenarios**:

1. **Given** tasks whose match is only in the notes body, **When** the owner searches that
   word, **Then** those tasks are returned.
2. **Given** an active filter set, **When** the owner adds a second field's filter,
   **Then** results narrow (AND); **when** they add a second value to the same field,
   **Then** results widen (OR).
3. **Given** a mixture of dated and undated tasks, **When** the owner filters for tasks with
   no due date, **Then** exactly the undated tasks are returned.
4. **Given** an unsupported filter name, **When** it is sent, **Then** the request is
   rejected rather than silently returning an unfiltered list.
5. **Given** more results than one page, **When** the owner pages forward, **Then** every
   task appears exactly once and the order is stable across repeats.
6. **Given** a page cursor, **When** the filter set changes, **Then** the cursor is rejected
   rather than paging over a different result set.
7. **Given** completed and trashed tasks, **When** the owner asks for that history,
   **Then** it is returned, and it is absent from the default open lists.

### Edge Cases

- Trashing a task that is already trashed, and restoring one that is not trashed.
- Trashing a task whose List is archived, then unarchiving the List, then restoring.
- Deleting a List whose members include trashed tasks — they stay trashed and lose only
  the List assignment.
- Deleting a Tag whose members include trashed tasks — they stay trashed and lose only
  that Tag; restore never re-adds it.
- PATCH of a non-trashed task that already belongs to an archived List: omission or an
  unchanged same-ID `project_id` retains membership; clearing it or moving to an active List
  succeeds; assigning any task newly to an archived List fails.
- Direct PATCH, lifecycle transition, tag add/remove/replace, or List reassignment of a
  trashed task — all fail without mutation. Only restore, permanent deletion, and the
  classification cleanup caused by List/Tag deletion may mutate a trashed task.
- A stale `expected_revision` on any new command, including trash, restore, unarchive and
  delete: the command is rejected and nothing mutates.
- Replaying one idempotency key against a *different* command or body.
- A tag removed from a task by one client while another client holds a stale full tag set —
  the incremental verb is what prevents the clobber, so a client must not fall back to
  whole-set replace for an add/remove.
- A due time with no due date, and a start time with no start date.
- A start date later than the due date — permitted, and not silently corrected.
- Priority migration encountering a value written by an older client mid-rollout, an
  unrecognized value on a current client, or an installed build absent from the operational
  evidence inventory. The fallback never silently maps an unknown value to a priority.
- Mobile performing a management action while offline or interrupted; on resume the state
  shown matches the server, per ADR-0002.
- A filter combination that matches nothing, distinguished in the UI from a failed request.
- Delete replay after the source List/Tag row and compatibility mirror are gone; the
  durable audit/idempotency receipt returns without resource reconstruction.

### Primary loop impact (Constitution Principle V)

This feature sits on the **atomic items → clarify/approve** segment of the capture → review
→ route loop. It adds no capture path and changes no confirmation contract. Voice Brain
Dump, Smart Add and idempotency recovery must be observably unchanged (C-70): every slice
re-runs their suites, and a regression there blocks the slice.

## Requirements *(mandatory)*

### Functional Requirements

**Task fields**

- **FR-001**: Users MUST be able to create a task, read it in a list, open its detail, and
  update it, including creating it directly into a selected List.
- **FR-002**: Users MUST be able to edit a task's title and notes body.
- **FR-003**: Users MUST be able to set, change and clear a task's due date.
- **FR-004**: Users MUST be able to set, change and clear an optional due time of day,
  interpreted as a floating local time carrying no timezone, reminder or DST promise.
- **FR-005**: Users MUST be able to set, change and clear a start date and an optional
  start time under the same floating-local-time rule as FR-004.
- **FR-006**: The final public and stored priority vocabulary MUST be exactly `1`, `2`, `3`
  or `none` (`1` highest), with exact labels `1 — High`, `2 — Medium`, `3 — Low`, `None`
  and order `1, 2, 3, none` before the existing total tie-breakers. Migration MUST use the
  reversible mapping `high↔1`, `medium↔2`, `low↔3`, `none↔none` over both SQLite JSON
  payloads and compatibility JSON mirrors. Rollout MUST be ordered: **stage 1** dual-reads
  and accepts both request vocabularies, stores legacy values, and returns legacy values to
  a client that does not explicitly advertise numeric-priority support; current clients
  MUST safely render both vocabularies and render an unrecognized value as `Priority
  unavailable` without changing it. A capability-advertising current build MAY receive the
  numeric response solely to produce gate evidence. **Stage 2** rewrites both stores and
  makes numeric the default response only after the release-evidence owner records every
  active internal backend, web, and installed mobile build as verified; an unknown or
  unverified active build blocks the switch, and the legacy response fallback remains
  available during rollback. **Stage 3** rejects legacy input and removes that fallback
  only after a second complete inventory check. The inverse rewrite of both stores MUST
  complete before an older backend or client becomes eligible during rollback.
- **FR-007**: The system MUST reject a due time without a due date and a start time without
  a start date, with an actionable message.
- **FR-008**: Users MUST be able to change a task's List membership, including clearing it.
- **FR-009**: Users MUST be able to add or remove a single tag on a task without resending
  the whole tag set, and such a change MUST leave every unrelated tag on that task intact.
- **FR-010**: The system MUST retain whole-tag-set replacement as a separate, explicit
  operation so that the incremental verb is never a silent read-modify-write.

**Task lifecycle**

- **FR-011**: Users MUST be able to trash a task. Trash MUST be an orthogonal soft-deletion
  marker that leaves the task's `inbox|next|waiting|someday|completed|cancelled` state
  unchanged, and MUST NOT be represented as completion or cancellation.
- **FR-012**: Trashed tasks MUST be excluded by default from task lists, search, filters,
  pagination, `counts_by_state`, Project open-member counts, Tag open-usage counts, Inbox,
  and all other open/history views that do not explicitly request Trash. They MUST remain
  reachable through the explicit trashed view. Destructive confirmation impact counts are
  different and MUST count every affected Task, including completed, cancelled, and
  trashed Tasks.
- **FR-013**: Users MUST be able to restore a trashed task, and restore MUST return it to
  its preserved commitment state by clearing only the Trash marker. Restore MUST preserve
  the task data as it exists at restore time and MUST NOT resurrect a List or Tag removed by
  a legitimate later global deletion.
- **FR-014**: Users MUST be able to complete and reopen tasks, with the reopen destination
  always explicit and never inferred.
- **FR-015**: Every P0 mutation MUST use the owner-scoped idempotency contract: Task
  create/update/transition/tag-add/tag-remove/tag-replace/trash/restore/permanent-delete,
  Empty Trash, List create/rename/archive/unarchive/delete, and Tag create/rename/delete.
  During the documented 24-hour client-retry window, replay of the same key, command and
  canonical body MUST return the original response with zero additional mutation; reuse of
  that key for another command/body MUST return `409`. A destructive delete replay MUST
  never reconstruct a deleted resource; after the transient window its durable redacted
  audit receipt MUST still make same-subject deletion a successful no-op.
- **FR-016**: Every rejected P0 command and query MUST return an actionable sanitized
  message and `X-Correlation-ID`, MUST distinguish semantic invalidity (`400`), absence or
  other-owner identity (`404`), stale revision/key conflict (`409`), and invalid shape
  (`422`), and MUST leave all state unmutated. Correlation IDs are observability labels
  only, never authorization or idempotency input.

**Lists**

- **FR-017**: Users MUST be able to create, list, read, rename, archive, unarchive and
  delete regular Lists.
- **FR-018**: Archiving a List MUST retain every member task's List membership, MUST NOT
  change any member's lifecycle state, MUST remove the List from active navigation, and
  MUST block new assignment until it is unarchived. Archiving the List MUST NOT change
  whether its member tasks appear in default state lists, the Inbox projection, counts,
  search or filters — those continue to be governed only by each task's own state and the
  filters applied, exactly as an active List's members are today. Only the List's own row
  disappears from List navigation and from the active-Lists listing; a task belonging to an
  archived List remains reachable everywhere a task belonging to an active List is
  reachable, findable by its List filter, and its List name renders normally in that
  context. Task create/new assignment to an archived List MUST fail. An existing member's
  PATCH that omits `project_id`, or explicitly carries the unchanged archived ID, MUST
  retain membership and may update another field; clearing it or moving to an active List
  MUST succeed. Active and archived List queries together MUST provide name resolution,
  while assignment selectors expose active Lists only.
- **FR-019**: Archived Lists MUST remain discoverable through an explicit archived view, so
  that unarchiving is reachable without prior knowledge of the List's id.
- **FR-020**: Deleting a List MUST require an explicit confirmation, MUST atomically clear
  the List assignment from every member task in one observable SQLite step, including
  completed, cancelled and trashed members, and MUST NOT delete, complete, cancel, restore
  or trash any member task. The List row, normalized name and compatibility mirror MUST be
  erased immediately; only FR-037's redacted audit receipt survives. Replay MUST return
  that receipt without recreating the List.
- **FR-021**: Inbox MUST remain a virtual server projection with no persisted List row, and
  MUST therefore be unavailable to rename, archive or delete.

**Tags**

- **FR-022**: Users MUST be able to create and list tags with their usage count, rename a
  tag, and delete a tag globally.
- **FR-023**: Deleting a tag globally MUST atomically remove that classification from every
  task, including completed, cancelled and trashed tasks, and MUST NOT delete, complete,
  cancel, restore or trash any task. The Tag row, normalized name and compatibility mirror
  MUST be erased immediately; only FR-037's redacted audit receipt survives. Replay MUST
  return that receipt without recreating the Tag.

**Search, filters and history**

- **FR-024**: Users MUST be able to search tasks by words in the name or the notes body.
- **FR-025**: Users MUST be able to filter by List, by tag, by status, by priority, and by
  due windows covering today, overdue, a closed date range, and "no due date"; and by start
  windows covering "available now" and "starts in the future".
- **FR-026**: Typed filters MUST compose with AND across different fields and OR within
  repeated values of one field, and this semantic MUST be stated in the published API
  documentation rather than left implicit.
- **FR-027**: The system MUST reject an unrecognized filter parameter rather than ignoring
  it and returning an unfiltered result; the error MUST name the supported parameter set
  without echoing the caller's raw unknown name or value.
- **FR-028**: Task results MUST paginate in one documented total order: manual/default is
  `order_key ASC, created_at ASC, id ASC`; due is dated-first `due_date ASC` then manual;
  priority is `1,2,3,none` then manual; title is normalized case-insensitive title then
  `id`; Trash is `trashed_at DESC, id ASC`. Active/archived List and Tag collections MUST
  use normalized name then `id`. Every page cursor MUST bind the owner, exact normalized
  filter set, visibility mode, sort mode and last sort tuple, so reuse under any different
  query is rejected.
- **FR-029**: Users MUST be able to retrieve completed, cancelled and trashed history
  through explicit filters, and that history MUST NOT appear in the default open lists.

**Cross-cutting**

- **FR-030**: Every user-facing capability in FR-001 through FR-029 MUST be reachable and
  observably equivalent on the backend API, the web client and the Expo mobile client.
  FR-010's whole-tag-set replacement is intentionally a contract-only operation: it MUST
  remain supported by the API and typed clients but needs no standalone client affordance.
- **FR-031**: Every task, List and Tag surface MUST remain owner-scoped, and a record
  belonging to another owner MUST be indistinguishable from an absent one.
- **FR-032**: Task lifecycle and the trashed marker MUST remain independent of agent
  Execution/Run state: no agent routing, start, progress or completion may change them, and
  no Task command may write Run state.
- **FR-033**: Voice Brain Dump, Smart Add and idempotency recovery MUST keep their current
  observable behavior.
- **FR-034**: The published API documentation MUST record the deliberate divergences from
  the RTM reference model: floating local times with no reminder or timezone promise, no
  undo-by-transaction, and archive retaining rather than clearing membership.
- **FR-035**: A trashed task, its trashed marker, and its full metadata MUST be included in
  the account data export, exactly as completed and cancelled tasks are today. FR-012's
  exclusion of trashed tasks from default lists and counts is a query-surface rule and MUST
  NOT be implemented as a repository-level default that also hides trashed rows from the
  export or from other owner-scoped internal reads. Archived Lists and FR-037 audit entries
  MUST also be exported. Permanently deleted Tasks and deleted List/Tag names MUST be
  absent. Account purge MUST erase tasks, archived Lists, audits, SQLite rows and every
  compatibility mirror.
- **FR-036**: A successful List rename, archive, unarchive or delete, and a successful Tag
  rename or delete, MUST invalidate any device-local cache of that List's or Tag's name on
  the next reachable client run; a task trash MUST invalidate any device-local cache keyed
  to that task's visibility. Clients MUST NOT rely solely on a periodic cache sweep for
  these cases. Task create/update/lifecycle/tag/List-assignment mutations MUST invalidate
  task list/detail/history/count caches and affected classification counts; List/Tag
  mutations MUST invalidate active, archived, all-name-resolution, selector and filtered
  task caches. Trash/restore/permanent-delete/Empty-Trash MUST invalidate default, history,
  Trash, Inbox and count caches. An interrupted mobile client MUST refetch the affected
  roots before offering retry; a periodic sweep alone is insufficient.
- **FR-037**: Every List deletion, Tag deletion, task permanent deletion and Empty Trash
  MUST atomically append a durable, owner-scoped destructive audit receipt containing only
  `audit_id`, `owner_id`, `subject_id`, `action`, `occurred_at`, and the request correlation
  ID; the action value identifies whether the subject was a List, Tag, Task, or Trash batch.
  It MUST contain no title, List/Tag name, notes, request body,
  idempotency key, email, or other user content. It is retained for the life of the
  account, included in account export, owner-isolated with 404-not-403 behavior on any read,
  and erased by account purge.
- **FR-038**: Trash MUST have no automatic time-based purge. A trashed task and its owned
  subtasks/comments persist until restore, separately confirmed permanent deletion or
  Empty Trash, or account purge. Permanent deletion/Empty Trash MUST atomically erase the
  selected Task content from SQLite and compatibility mirrors, emit only FR-037 receipts,
  and be idempotent without resurrection.
- **FR-039**: While a Task is trashed, direct Task PATCH, ordinary lifecycle transition,
  tag add/remove/replace, and List assignment MUST fail with no mutation. Only restore,
  permanent deletion, and owner-authorized List/Tag deletion cleanup may alter it. List/Tag
  rename/archive/unarchive may change name resolution or container state without rewriting
  the Task; restore observes those legitimate current facts.

### Key Entities

- **Task** — the user's commitment. Carries title, notes body, commitment state, an
  orthogonal trashed marker, optional List membership, zero or more Tags, due date with
  optional floating time, start date with optional floating time, priority, and revision.
- **List** (persisted as Project) — an owner-scoped named container with an active or
  archived state. Archiving is reversible and non-destructive; deleting is destructive to
  the container only.
- **Tag** — an owner-scoped classification applied to zero or more tasks. Deleting removes
  the classification, never the tasks.
- **Inbox** — a virtual projection over tasks, not a stored entity.
- **Execution/Run** — the agent-side record. Referenced here only to state that this
  feature does not touch it.
- **Destructive audit receipt** — durable owner-scoped metadata containing IDs, action and
  time only. It proves irreversible erasure occurred without retaining deleted names or
  Task content.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The canonical P0 gap list is exactly these 12 `capability-matrix.md` rows —
  C-09, C-10, C-11, C-12 (DIVERGENT), C-14, C-25, C-26, C-36 (DIVERGENT), C-38, C-39, C-55,
  C-56. (C-47 names the same capability as C-14 under a different taxonomy grouping and is
  not counted twice.) All 12 are closed and evidenced by a named automated test; zero remain
  open and zero are reclassified out of scope. This is a correction from an earlier "11" —
  the first draft undercounted by one; see `analysis.md`. PARTIAL rows the plan also
  improves (C-51, C-54, C-68) are tracked separately and are not part of this denominator,
  because they already have a working path today and closing them is quality work, not gap
  closure.
- **SC-002**: Every one of the 12 SC-001 capabilities is exercised by at least one automated
  test on each of the three tiers per the evidence map in `tasks.md` §Evidence map, so no
  tier reaches acceptance on another tier's evidence.
- **SC-003**: A user can trash and restore a task with its commitment state and every
  unchanged field preserved; a field-by-field test also deletes one List/Tag while the task
  is trashed and proves restore does not resurrect that classification.
- **SC-004**: Archiving and then unarchiving a List leaves 100% of member tasks with their
  original List membership and lifecycle state.
- **SC-005**: Deleting a List or a Tag deletes zero tasks.
- **SC-006**: Adding or removing one tag on a task leaves 100% of that task's unrelated tags
  intact under a concurrent-edit test.
- **SC-007**: Every unrecognized filter parameter is rejected; zero filter names are
  silently ignored.
- **SC-008**: Repeated identical list requests return an identical task order, and paging
  through a multi-page result returns every task exactly once with zero duplicates and zero
  omissions.
- **SC-009**: Replaying any P0 mutating command with the same key and body produces an
  identical response and zero additional state changes during the documented retry window;
  the command inventory has 100% named replay/key-conflict coverage.
- **SC-010**: Zero agent Execution/Run records change state as a result of any Task command,
  and zero Task lifecycle or trashed values change as a result of any Run state change.
- **SC-011**: The existing Voice Brain Dump, Smart Add and idempotency-recovery suites pass
  unchanged at the end of every slice.
- **SC-012**: For each irreversible deletion, one durable audit receipt is exported with
  only the allowed IDs/action/time fields; deleted names and content have zero occurrences
  in SQLite, mirrors, API responses and export, and account purge leaves zero audit rows.
- **SC-013**: Every new P0 read/write surface has automated same-owner, other-owner and
  absent-resource evidence; other-owner and absent responses are indistinguishable, and
  every success/replay/error response carries a non-empty correlation ID that is never
  accepted as authorization or an idempotency key.
- **SC-014**: Numeric-priority stage 2 and stage 3 each have a dated evidence record owned
  by the release operator that lists 100% of active internal backend, web and installed
  mobile build IDs as verified, with zero unknown or unverified active builds.
- **SC-015**: Before acceptance, screenshots at the specified desktop/mobile viewports and
  a screen-reader/keyboard video cover every numbered D-01…D-05 and M-01…M-04 state group;
  missing rendered evidence keeps acceptance rejected without changing planning status.

## Assumptions

- The portable founder brief and Max's named 2026-08-15 HD-01…HD-09 answers are recorded
  in `intake.md`/`research.md`. ADR-0020 resolves the two ADR-0006 conflicts. HD-10 remains
  a separate run/digest-bound high-risk sign-off and is not assumed here.
- RTM is a reference model for expected capability, not an integration target. No RTM
  account, credential or network call is involved anywhere in this feature.
- Single-owner product. No sharing, assignment, contacts or permissions are in scope, so
  none of the RTM collaboration surface applies.
- The existing session-cookie auth, per-owner filtering, correlation-id and optimistic-
  concurrency (`expected_revision`) mechanisms are reused unchanged; this feature introduces
  no new authentication or authorization concept.
- SQLite remains canonical. Task fields live primarily in the `tasks.payload` JSON blob,
  with scalar compatibility/index columns and write-through JSON mirrors. Migrations and
  rollback must rewrite/verify both representations; compatibility mirrors are never a
  second post-ledger authority.
- There is no production user data to preserve (`AGENTS.md`), so the priority migration's
  risk is contained to development and internal environments — but it is still written to be
  reversible, because the compatibility window spans clients that update independently.
- P1 and P2 items are specified only to the depth needed to keep them out of P0. They are
  not silently implemented in this tranche.
