# ADR-0003: Save a flat Brain Dump session to RTM Inbox

Date: 2026-07-12
Status: Proposed
Decision owner: BrainBuddy
Related: ADR-0001, ADR-0002, PR #60, `specs/003-brain-dump-task-tracker/`

## Context

The first BrainBuddy product tranche must prove one short loop: capture thoughts, turn them
into a plain list of task drafts, and deliberately save that list to Remember The Milk
(RTM) Inbox. Earlier drafts of this decision expanded the loop into review, selection,
routing, and task-by-task confirmation. That added product concepts which are not required
to test the value of Brain Dump.

RTM does not promise idempotent `tasks.add`. A timeout after a request may mean either that
nothing happened or that RTM created the task and the response was lost. BrainBuddy must
therefore keep enough local export state to avoid silently creating a duplicate, without
putting provenance or idempotency markers into the RTM task.

PR #60 (`feat/voice-capture-mvp`) contains useful owner-scoped persistence and module seams,
but its synchronous mock success is not a functional RTM export. It also includes workflow
scope beyond this tranche.

## Decision

Ship one flat Brain Dump session and one explicit `Save session` action.

```text
open or resume the user's one open session
  -> add raw thoughts by voice or text
  -> append task-name drafts to one flat ordered list
  -> manually edit wording, delete drafts, or capture more thoughts
  -> Save session once
  -> freeze every remaining draft
  -> create each frozen name as a plain RTM Inbox task
  -> finish as saved or saved_with_issues
```

There is no separate stop, reconciliation, review, selection, acceptance, confirmation, or
destination step. Seeing drafts never closes capture. Until `Save session` begins, the user
may return to voice or text capture at any time.

### Product scope

In scope:

- create or resume one open Brain Dump session per owner;
- append voice or text input to that session;
- produce a flat chronological list of provisional task-name drafts;
- manually edit a draft's wording or delete a draft;
- perform one explicit bulk save of every remaining draft to RTM Inbox;
- preserve local export state so partial failures and ambiguous creates do not duplicate
  tasks or prevent unaffected drafts from being exported.

Explicitly out of scope:

- Current Reality Tree (CRT), problem candidates, recommendations, or AI advice;
- decomposition, subtasks, task-type classification, or task hierarchy;
- destination selection, routing UI, tags, projects, lists, or metadata controls;
- per-task planner/review decisions or confirmation outcomes;
- Weekly Review behavior;
- editing, completing, deleting, or otherwise mutating existing RTM tasks;
- treating tasks as evidence or attaching execution results to them.

A model may convert newly accepted raw input into zero or more concise task-name drafts. It
must not revise, merge, split, reorder, classify, enrich, or delete an existing draft.
After a draft appears, only a direct user edit may change its wording and only a direct user
delete may remove it. New drafts append after existing drafts.

## Session and draft state contract

There is at most one `open` session per owner. Opening Brain Dump returns that session if it
exists; otherwise it creates one. A `saved` or `saved_with_issues` session is historical and
cannot be reopened. Opening after terminal save creates a new session.

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
  position
  name
  state: provisional | deleted | frozen | exporting |
         exported | failed | ambiguous
  revision
  source_capture_ids[]
  user_edited: bool
  export_id?
  created_at, updated_at, deleted_at?
```

Allowed transitions are exact:

```text
Session:
  (none) -> open
  open -> open                         add capture, append draft, edit, or delete
  open -> saving                       Save session freezes the non-deleted snapshot
  saving -> saved                      every frozen draft exported; empty snapshot is valid
  saving -> saved_with_issues          at least one draft failed or is ambiguous

Draft:
  (none) -> provisional                append after current last position
  provisional -> provisional           direct user wording edit only
  provisional -> deleted               direct user delete only
  provisional -> frozen                atomically when Save session begins
  frozen -> exporting                  durable attempt enters send boundary
  exporting -> exported                RTM returned a complete task reference
  frozen -> failed                     terminal or exhausted proven-pre-send failure
  exporting -> ambiguous               send may have reached RTM but identity is unknown
```

`deleted`, `exported`, `failed`, and `ambiguous` are terminal for this tranche. Deleted
drafts stay as local tombstones for ordering and audit but are excluded from export. Draft
positions and IDs are stable; deletion leaves a gap rather than renumbering durable records.
The UI may render a compact 1..N order without using that display number as identity.

Capture, edits, and deletion require `session.state == open` and an expected revision. They
are rejected after save starts. Concurrent stale commands fail without partial mutation.
There is no transition from `saving` back to `open`.

### Save session semantics

`Save session` is the single confirmation for the whole remaining list. The command:

1. requires an owner-scoped open session and an idempotency key;
2. atomically records one `BrainDumpSave` and freezes the exact ordered set of every
   non-deleted draft at its current revision and wording;
3. creates one local `DraftExport` per frozen draft before any RTM call;
4. returns the same save and export records when the same command is repeated;
5. rejects reuse of the key with changed content;
6. continues processing sibling exports when one export fails or becomes ambiguous;
7. closes the session only after every export reaches a terminal state.

An empty session may be saved. It makes no RTM calls and becomes `saved`.

```text
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
  attempt_count
  external_ref?
  error_code?
  created_at, updated_at
```

The save is one bulk user action, not a set of per-draft approval decisions. Per-draft export
records are an internal reliability mechanism and a truthful status projection only.

## TaskTrackerPort v1

Execution owns the replaceable external boundary. Brain Dump supplies only the frozen task
name and a local export ID. The minimum port is create-only:

```python
class TaskTrackerPort(Protocol):
    def create_task(
        self, request: CreateExternalTaskRequest
    ) -> CreateExternalTaskResult: ...
```

```text
CreateExternalTaskRequest:
  owner_id: str
  export_id: str
  name: str

CreateExternalTaskResult:
  external_ref: ExternalTaskRef

ExternalTaskRef:
  adapter: str
  account_ref: str
  list_ref: str
  task_series_ref: str
  task_ref: str
```

The port has no destination, note, URL, tag, priority, date, recurrence, project, list,
subtask, classification, update, complete, delete, or query fields or methods. Concrete RTM
DTOs and credentials do not cross this boundary. A future tracker can replace RTM for new
sessions by implementing the same create-only contract; existing local RTM references stay
provider-qualified and unchanged.

## RTM export rule

For each frozen draft, the RTM adapter calls `rtm.tasks.add` with:

- `name = frozen_name`;
- `parse = 0`;
- no `list_id`, so RTM uses Inbox;
- no optional task field.

The created RTM object is task-name-only. BrainBuddy sends no tags, notes, URLs,
`external_id`, priority, dates, recurrence, reminder, estimate, location, assignee,
project/list move, source text, transcript, or invented metadata. Even information typed
inside a raw thought is not converted into RTM metadata in this tranche; only the resulting
plain draft name is exported.

BrainBuddy stores session/draft/export linkage and the returned RTM IDs locally. RTM stores
none of that linkage.

## Failure, crash, and ambiguity rules

A local `DraftExport` exists before network I/O. Workers may process exports independently,
but the frozen list order is preserved in the status projection.

- A failure proven to occur before send may be retried within the same save operation under
  a bounded policy. Exhaustion becomes `failed`.
- Once request transmission may have begun, a crash, timeout, connection loss, or malformed
  success becomes `ambiguous` unless a complete returned reference was durably stored.
- An `ambiguous` export never calls create again automatically or through another
  `Save session` invocation.
- No title/time matching is used to infer that an RTM task is the same task.
- A failed or ambiguous export does not stop pending sibling exports.
- Replaying the save command or recovering a worker resumes only `pending` exports. It
  returns stored terminal states for all others.

The UI marks only the affected local draft as failed or ambiguous. For ambiguity it says
that RTM may have created the task and that BrainBuddy will not create it again
automatically. Resolution or existing-task mutation is outside this tranche; the user may
inspect RTM manually. The session finishes `saved_with_issues` after the remaining exports
finish.

## PR #60 disposition

Retain only useful foundation that fits this contract:

- owner-scoped persistence and authentication fixtures;
- durable source input separated from user-editable draft wording;
- command revision and idempotency concepts;
- modular application and Execution seams;
- test fakes which never appear as successful production integrations.

Remove or supersede for this tranche:

- synchronous one-shot completion and runtime mock success;
- pause/stop/review/freeze/selection/per-task confirmation workflow;
- model-driven merge, split, reorder, classification, recommendation, or enrichment;
- Weekly Review and Thinking/CRT product behavior;
- destination routing and broad task-manager APIs;
- generic retries after a request may have reached RTM.

## Minimal implementation graph

```text
A. Flat session domain + API
   one open session, voice/text capture, append-only drafts, manual edit/delete, projection
                         |
B. Save operation + Execution port
   atomic freeze-all, DraftExport records, create-only port, recovery/idempotency tests
                         |
C. RTM adapter
   owner binding, plain Inbox tasks.add mapping, returned-reference persistence
                         |
D. Thin UI + release verification
   capture/list/edit/delete/Save session, partial status, deterministic suites, one sandbox smoke
```

Each step depends on the preceding step. No implementation step may introduce a second
workflow or a generic task-management domain.

## Rationale

This design tests the shortest useful BrainBuddy loop and keeps the interaction legible:
collect, clean up wording, save. One bulk save is a clear external-side-effect boundary.
A small create-only port keeps RTM replaceable without pretending BrainBuddy already needs
a task manager. Local export records solve the real reliability problem—uncertain remote
creates—without polluting the user's RTM Inbox tasks.

## Alternatives considered

### Review and confirm drafts individually

Rejected. It turns a simple capture session into a planner and adds decisions which the
founder explicitly removed from this tranche.

### Add destination or metadata controls

Rejected. Brain Dump is a plain Inbox capture path. GTD classification belongs later and
must not be inferred during capture.

### Retry an ambiguous RTM create

Rejected. RTM has no trusted idempotent create primitive for this use. Retrying can silently
duplicate a task.

### Put a provenance marker in the RTM task

Rejected. The exported object must remain a task-name-only Inbox task. Linkage is
BrainBuddy-owned data.

### Build a BrainBuddy-native task manager now

Rejected. The create-only port preserves replacement without pre-building lists, projects,
or task lifecycle behavior.

## Consequences and guardrails

Positive consequences:

- one understandable workflow and one explicit external write action;
- no metadata or GTD decisions are invented;
- unaffected drafts continue exporting after a sibling problem;
- ambiguous creates cannot be duplicated automatically;
- RTM can be replaced later behind a deliberately small port.

Tradeoffs:

- `saved_with_issues` may require the user to inspect RTM manually;
- no in-product ambiguity resolution exists in this tranche;
- drafts cannot be changed after save begins.

Future agents must preserve the exact state transitions, create-only port, task-name-only
RTM mapping, one bulk save, sibling isolation, and no-retry rule for ambiguous creates.

## Verification

The normative scenarios are in
`specs/003-brain-dump-task-tracker/acceptance-tests.md`. Documentation review must also
confirm that ADR-0001 and ADR-0002 defer to this record for the Brain Dump specialization.
A functional implementation additionally requires deterministic adapter tests and one
controlled credentialed RTM sandbox smoke which creates at most one task.

## Related files

- `docs/decisions/0001-vnext-modular-monolith-and-workflow-contracts.md`
- `docs/decisions/0002-async-voice-operation-substrate.md`
- `specs/003-brain-dump-task-tracker/spec.md`
- `specs/003-brain-dump-task-tracker/acceptance-tests.md`
- PR #60 (`feat/voice-capture-mvp`)
