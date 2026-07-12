# Brain Dump flat session + RTM Inbox export specification

Status: Design contract
Decision: [ADR-0003](../../docs/decisions/0003-brain-dump-task-tracker-port.md)
Acceptance tests: [acceptance-tests.md](acceptance-tests.md)

## Goal

A user can open or resume one Brain Dump session, add thoughts by voice or text, see a flat
ordered list of provisional task names, manually edit or delete those names, return to
capture whenever wanted, and use one `Save session` action to export every remaining name
as a plain RTM Inbox task.

## Release boundary

This release contains only Brain Dump capture and save-to-Inbox. It does not contain CRT,
problem candidates, recommendations, advice, decomposition, subtasks, task typing,
destination selection, routing, planner/review decisions, Weekly Review, existing-task
mutation, or tasks-as-evidence/results behavior.

## User contract

1. Opening Brain Dump resumes the owner's existing open session or creates one.
2. Voice and text are equivalent capture inputs to the same session.
3. Accepted input may append zero or more provisional task-name drafts.
4. Drafts form one flat chronological list. New drafts append; there are no parents,
   children, groups, destinations, or task types.
5. Once visible, a draft changes only through a direct user wording edit or direct user
   deletion. Processing later input cannot revise, merge, split, reorder, enrich, or delete
   an existing draft.
6. Viewing or editing the list does not leave capture mode. The user may add more voice or
   text until saving starts.
7. `Save session` is one explicit bulk action over every non-deleted draft. There is no
   selection or per-draft confirmation step.
8. Saving freezes the ordered names. Capture, edit, and delete commands are rejected after
   that point.
9. Every frozen name is independently exported to RTM Inbox. One failure or ambiguous
   outcome does not stop siblings.
10. RTM receives the frozen name only. BrainBuddy keeps all linkage locally.
11. An ambiguous create marks only that local draft and is never created again
    automatically. Replaying save returns the stored state and continues only safe pending
    work.
12. The session ends as `saved` when all drafts export, or `saved_with_issues` when any
    export fails or is ambiguous. Saving an empty session is valid and makes zero RTM calls.

## State transitions

```text
Session:
  absent -> open
  open -> open                         capture / append / manual edit / manual delete
  open -> saving                       Save session atomically freezes all remaining drafts
  saving -> saved                      every frozen draft exported, or no drafts remained
  saving -> saved_with_issues          at least one frozen draft failed or is ambiguous

Draft:
  absent -> provisional                append at end of the flat list
  provisional -> provisional           direct user wording edit
  provisional -> deleted               direct user delete
  provisional -> frozen                Save session snapshot
  frozen -> exporting                  durable export crosses the send boundary
  exporting -> exported                complete RTM reference returned and stored
  frozen -> failed                     terminal/exhausted proven-pre-send failure
  exporting -> ambiguous               RTM may have accepted; identity is unknown
```

No other transitions are valid in this release. `deleted`, `exported`, `failed`, and
`ambiguous` are terminal. A saved session is historical; the next open starts a new session.

## Minimal records

```text
BrainDumpSession:
  id, owner_id
  state: open | saving | saved | saved_with_issues
  revision
  ordered_draft_ids[]
  active_save_id?
  created_at, updated_at, saved_at?

BrainDumpDraft:
  id, session_id, owner_id
  position, name
  state: provisional | deleted | frozen | exporting |
         exported | failed | ambiguous
  revision, source_capture_ids[], user_edited
  export_id?, created_at, updated_at, deleted_at?

BrainDumpSave:
  id, session_id, owner_id
  idempotency_key_hash, frozen_session_revision
  ordered_export_ids[]
  state: pending | exporting | saved | saved_with_issues
  created_at, completed_at?

DraftExport:
  id, save_id, session_id, draft_id, owner_id
  frozen_name
  state: pending | exporting | exported | failed | ambiguous
  attempt_count, external_ref?, error_code?
  created_at, updated_at
```

Stable IDs, not display positions, address drafts. Deleted drafts remain local tombstones.
Optimistic concurrency uses expected session/draft revisions. Wrong-owner IDs return `404`.

## API behavior slices

Route names may follow existing `/api` conventions, but behavior must expose:

```text
POST   /brain-dumps/open                         create or resume one open session
GET    /brain-dumps/{session_id}                 reload the owner-scoped projection
POST   /brain-dumps/{session_id}/captures/text   append raw text input
PUT    /brain-dumps/{session_id}/audio/{chunk}   append idempotent voice input
PATCH  /brain-dumps/{session_id}/drafts/{id}     manual name edit only
DELETE /brain-dumps/{session_id}/drafts/{id}     manual delete only
POST   /brain-dumps/{session_id}/save            freeze all and start/resume one bulk save
```

Mutations carry an idempotency key and expected revision where applicable. Reusing a key
with identical content returns the original record. Reusing it with changed content returns
`409 IDEMPOTENCY_CONFLICT` without mutation or RTM calls.

There are deliberately no pause, stop, review, select, confirm, route, destination,
classification, recommendation, subtask, or existing-task mutation endpoints in this
specialization.

## Save operation

The save transaction atomically:

1. validates that the session is `open` and owned by the caller;
2. snapshots every non-deleted draft in stable list order;
3. changes those drafts to `frozen` and the session to `saving`;
4. creates one ordered `DraftExport` per frozen draft before network I/O;
5. records one `BrainDumpSave` as the idempotent parent operation.

Workers continue every sibling until all exports are terminal. Recovery resumes `pending`
exports, does not resend `exporting` exports whose send outcome is unknown, and never
reprocesses terminal exports. Repeating `Save session` cannot create a second save operation.

## Execution boundary

The replaceable port is create-only:

```text
create_task({owner_id, export_id, name})
  -> {external_ref: {adapter, account_ref, list_ref, task_series_ref, task_ref}}
```

Execution owns adapter selection, owner credential lookup, local export attempts, and
external references. The port cannot express metadata, destination choice, hierarchy,
classification, queries, or mutations of existing tasks.

## RTM mapping

For each `DraftExport`, call `rtm.tasks.add` with the frozen name, `parse=0`, and no
`list_id`. Omit every optional task field. This creates a task-name-only RTM Inbox item:

- no tags, notes, URLs, or `external_id`;
- no priority, due/start date, recurrence, reminder, estimate, location, or assignee;
- no project/list move, hierarchy, type, or BrainBuddy provenance.

Persist the returned RTM list, task-series, and task IDs in BrainBuddy. Do not write local
session, draft, capture, or export IDs into RTM.

## Failure and ambiguity behavior

A proven pre-send transient failure may retry within the same save under a bounded policy.
An exhausted or terminal pre-send error becomes `failed`. Once sending may have started, a
timeout, connection loss, process crash, or incomplete/malformed success becomes
`ambiguous` unless a complete RTM reference was stored.

An ambiguous export:

- causes no second create call from workers, recovery, or repeated save requests;
- remains attached only to its local draft;
- does not stop sibling exports;
- displays that RTM may have created the task and BrainBuddy will not create it again
  automatically;
- requires manual inspection of RTM outside this release's product flow.

The application does not search by title/time and does not infer or adopt an existing RTM
task. Existing-task lookup, linking, editing, deletion, and resolution UI are out of scope.

## Security and privacy

RTM deployment credentials and owner auth tokens remain server-side and never enter client
DTOs, logs, session/draft/save/export records, or external references. Logs use IDs,
states, timings, and allowlisted error codes only. RTM receives only each frozen draft name.
It receives no raw audio, transcript, source spans, discarded drafts, prompt/model metadata,
email, or other BrainBuddy content.

## Minimal implementation graph

1. Flat session domain/API: one open session, voice/text capture, append-only flat drafts,
   manual wording edit/delete, owner-scoped projection.
2. Save + Execution: atomic freeze-all, one idempotent save, ordered export records,
   create-only port, sibling isolation, restart recovery, ambiguity no-resend tests.
3. RTM adapter: owner binding, signed `tasks.add`, exact plain Inbox mapping, complete returned
   reference persistence, deterministic fake-client contract tests.
4. Thin UI + gate: capture/list/edit/delete/Save session, per-draft export status only for
   failures/ambiguity, deterministic suites, and one controlled sandbox create smoke.

Each step depends on the previous one. PR #60 may contribute only conforming owner-scoped
persistence, source/draft separation, idempotency/revision primitives, module seams, and
test fakes. Runtime mock success and broader workflow behavior must not ship.

## Definition of done

- every normative scenario in `acceptance-tests.md` passes at its specified layer;
- there is at most one open session and one save operation per session;
- no existing draft changes without a direct user edit/delete command;
- one save freezes all remaining drafts and continues after sibling problems;
- the port is create-only and RTM receives task-name-only Inbox adds;
- a forced ambiguous send produces exactly one create call across replay and restart;
- production cannot report a fake adapter's invented success;
- one opt-in sandbox smoke creates at most one uniquely named plain Inbox task and verifies
  the returned reference without uncontrolled cleanup or retry.
