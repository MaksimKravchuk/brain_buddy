# ADR-0003: Ship Brain Dump through a narrow task-tracker port

Date: 2026-07-12
Status: Proposed
Decision owner: BrainBuddy
Related: ADR-0001, ADR-0002, PR #60, `specs/003-brain-dump-task-tracker/`

## Context

ADR-0001 defines the modular-monolith boundaries and ADR-0002 defines a shared async
voice-operation substrate. The next product tranche is narrower: prove the Brain Dump
loop with Remember The Milk (RTM) as the concrete task tracker. Weekly Review and CRT are
not deliverables in this tranche. Their existing contracts may remain, but they must not
expand the implementation or the task-tracker interface.

PR #60 (`feat/voice-capture-mvp`) establishes useful module and persistence scaffolding,
but calls a `MockTaskTrackerAdapter` that invents a successful external reference. It also
processes each submission synchronously and lets Execution import Organize records and its
repository. That is not a functional Brain Dump MVP and violates the intended ownership
boundary. A mock success cannot stand in for a durable external side effect.

RTM's official API supports authenticated task creation, task listing, task references,
notes, timelines, and an `external_id` supplied by an application. The documentation does
not promise that `tasks.add` is idempotent or that an `external_id` is unique. A timeout
can therefore mean either "not created" or "created but the response was lost". BrainBuddy
must represent that uncertainty instead of blindly retrying and potentially duplicating a
task.

## Decision

Ship only the Brain Dump workflow and a small Execution-owned `TaskTrackerPort` v1. RTM is
the first adapter. A future BrainBuddy-native tracker implements the same port.

The MVP lifecycle is:

```text
create/resume session
  -> record and append numbered provisional drafts
  -> pause (settle a checkpoint) / resume the same session
  -> stop (seal input)
  -> reconcile and review the numbered drafts
  -> explicitly confirm selected drafts, individually or as a batch
  -> create one route/outbox item per accepted task
  -> dispatch accepted tasks through TaskTrackerPort
  -> show one durable result per task
```

Models may add, reorder, merge, split, or revise provisional drafts, subject to ADR-0002's
lineage and user-edit locks. They may not confirm, route, or create an external task. Pause
is resumable and does not imply confirmation. Stop seals the input but does not write to
the tracker. Closing the client neither stops nor confirms a session.

### Scope

In scope:

- create/resume/pause/resume/stop a Brain Dump session;
- append live, chronological, numbered provisional task drafts;
- reconcile drafts after pause checkpoints and stop;
- edit, reject, or accept each draft and batch-confirm the current selection;
- create accepted tasks in the configured tracker;
- show durable success, failure, reconciliation, and ambiguous-outcome results;
- RTM connect/status, Inbox creation, read-back, and bounded reconciliation.

Out of scope:

- Weekly Review UI or domain implementation;
- CRT candidate detection or promotion;
- task completion, editing, deletion, recurrence, reminders, projects, calendars, or sync;
- autonomous tags, priorities, dates, list selection, or `na` classification;
- multiple active tracker adapters per user;
- a proprietary BrainBuddy task schema.

### No-silent-write invariant

An external create is allowed only when all of these are true:

1. the operation has been stopped or explicitly checkpointed for review;
2. a proposal batch is frozen at a known revision;
3. the user explicitly accepts that draft, or selects it in an explicit batch confirmation;
4. the confirmed projection displays the exact title, destination, and any optional fields;
5. a durable local route and outbox record exist before the adapter call.

Repeated confirmation with the same key and body returns the original local route/result.
A changed body under the same key is rejected. Neither model confidence nor a previous
user preference substitutes for confirmation.

## Brain Dump records and states

ADR-0002 `AsyncOperation` is retained but the first implementation exposes only
`voice_brain_dump`. The operation projection must include stable draft IDs and display
numbers. Display numbers are a projection of current chronological order; durable
references and confirmations use draft IDs, never numbers.

```text
BrainDumpSessionProjection:
  operation_id, owner_id
  status: recording | paused | reconciling | awaiting_confirmation |
          committing | completed | retryable_error | terminal_error | cancelled
  input_revision, proposal_revision, last_event_sequence
  drafts: BrainDumpDraft[]
  active_batch_id?, created_at, updated_at

BrainDumpDraft:
  id, display_number, position
  title
  state: provisional | reconciled | needs_clarification | rejected | accepted
  source_segment_ids[], predecessor_draft_ids[]
  confidence_band, user_edited_fields[]
  warnings[], revision

DraftConfirmation:
  action_id, draft_id, draft_revision
  decision: accept | reject
  exact_title, destination, explicit_fields
  confirmed_by, confirmed_at
```

`pause` drains the current stable input and may run reconciliation, then reaches `paused`
or `awaiting_confirmation`. New audio cannot append while paused. `resume` continues the
same operation and preserves events, drafts, edits, and numbering lineage. Any accepted
but not yet confirmed proposal remains non-authoritative. `stop` seals the input manifest;
a stopped session cannot resume recording. Edits after a batch is frozen supersede the
batch and require a new confirmation.

The commit result is per action, not a single optimistic banner:

```text
DraftCommitResult:
  action_id, draft_id, route_id
  status: queued | creating | succeeded | failed | reconciliation_required |
          ambiguous | cancelled
  external_ref?: ExternalTaskRef
  task?: ExternalTaskSnapshot
  error?: TaskTrackerError
  attempt_count, updated_at
```

The operation may complete its local commit while routes remain queued or creating. The UI
keeps results durable and reloadable by operation ID. It must never translate
`reconciliation_required` or `ambiguous` into success.

## TaskTrackerPort v1

The port is owned by Execution and speaks only its own DTOs. It must not accept
`RouteRecord`, `CaptureItem`, transcript objects, audio, or another module's repository.
It has exactly three operations needed by Brain Dump:

```python
class TaskTrackerPort(Protocol):
    def create_task(self, request: CreateExternalTaskRequest) -> CreateExternalTaskResult: ...
    def get_task(self, owner_id: str, ref: ExternalTaskRef) -> ExternalTaskSnapshot: ...
    def list_tasks(self, query: ExternalTaskQuery) -> list[ExternalTaskSnapshot]: ...
```

These are the exact v1 DTOs:

```text
CreateExternalTaskRequest:
  owner_id: str
  route_id: str                    # local durable id; one task per route
  title: str                       # exact user-confirmed task title
  destination: TaskDestination
  explicit_fields: ExplicitTaskFields
  provenance: TaskProvenance

TaskDestination:
  kind: inbox | selected_container
  container_ref?: str              # required only for selected_container
  display_name: str                # frozen confirmation text

ExplicitTaskFields:
  due_at?: datetime
  priority?: str
  tags: tuple[str, ...]             # empty by default
  # Fields exist only to carry a user's explicit confirmation; adapters do not infer them.

TaskProvenance:
  source: brainbuddy_brain_dump_v1
  operation_id: str
  draft_id: str
  route_id: str
  marker: str                       # deterministic `bb:v1:<route_id>`

CreateExternalTaskResult:
  ref: ExternalTaskRef
  snapshot: ExternalTaskSnapshot
  remote_transaction_ref?: str

ExternalTaskRef:
  adapter: str                      # `rtm` or future `brainbuddy`
  account_ref: str                  # opaque, non-secret account binding id
  container_ref: str
  task_series_ref?: str
  task_ref: str

ExternalTaskSnapshot:
  ref: ExternalTaskRef
  title: str
  destination_display_name: str
  state: open | completed | unknown
  created_at?: datetime
  provenance_marker?: str
  permalink?: str

ExternalTaskQuery:
  owner_id: str
  destination?: TaskDestination
  created_from?: datetime
  created_to?: datetime
  provenance_marker?: str
  max_results: int                  # hard-capped by adapter
```

`ExternalTaskRef` is immutable linked evidence after a successful or reconciled create.
Adapter-specific IDs are opaque outside Execution. No port method edits or deletes an
external task. `get_task` exists for result verification and reopening durable results;
`list_tasks` exists only for the Brain Dump result view and bounded reconciliation, not as
a general task browser.

### Capabilities

The configured binding records adapter capabilities rather than making callers guess:

```text
TaskTrackerCapabilities:
  supports_create: true
  supports_get: true
  supports_bounded_list: true
  supports_native_idempotent_create: bool
  supports_provenance_lookup: bool
  supports_selected_container: bool
  supported_explicit_fields: set[due_at | priority | tags]
```

Brain Dump v1 requires create/get/bounded-list. A capability may disable an optional field
or selected destination before confirmation. Unsupported confirmed fields fail locally;
they are never dropped silently. Native idempotency is false for RTM unless a credentialed
contract test proves stronger semantics than the public API promises.

### Error taxonomy

Adapters return results or raise a typed `TaskTrackerError`; Execution persists the public
fields and does not log exception bodies that may contain task text or credentials.

```text
TaskTrackerError:
  code: AUTH_REQUIRED | PERMISSION_DENIED | INVALID_REQUEST |
        DESTINATION_NOT_FOUND | RATE_LIMITED | UNAVAILABLE | TIMEOUT |
        REMOTE_REJECTED | PROTOCOL_ERROR | AMBIGUOUS_OUTCOME
  retry_disposition: user_action | safe_retry | reconcile_first | terminal
  message_code: str                 # localized/redacted UX key
  retry_after_ms?: int
  remote_code?: str                 # allowlisted code only
```

Authentication and permission failures require user action. Invalid requests and missing
destinations are terminal for that frozen action and return to review. Rate limits and
pre-send unavailability may be safely retried. A timeout, connection loss after request
bytes were sent, malformed success response, or process crash while `sending` is
`reconcile_first`; it is never blindly retried.

## RTMTaskTrackerAdapter

### Credentials and account binding

Each BrainBuddy owner has one server-side `TaskTrackerBinding` containing an opaque secret
reference, RTM account/user ID, granted permission (`write` minimum), connection state,
and last successful token check. API key/shared secret are deployment configuration;
user auth tokens are encrypted at rest or held in the deployment secret store and are
never returned by APIs, events, logs, outbox records, or external refs. Every adapter call
resolves credentials by `owner_id`; credentials are never process-global user state.

Connection uses RTM's supported user authorization flow and `auth.checkToken`. Revoked or
expired tokens map to `AUTH_REQUIRED`. BrainBuddy requests only the permission needed by
v1; it does not request delete permission.

### Create mapping

For an accepted draft, the adapter:

1. resolves the owner binding and validates write permission;
2. obtains/reuses an RTM timeline according to the client policy;
3. calls `rtm.tasks.add` with:
   - `name = request.title`;
   - `parse = 0`, so task text cannot silently create dates, tags, priority, or lists;
   - no `list_id` for the default `inbox` destination;
   - an explicitly selected and previously resolved regular-list ID only for
     `selected_container`;
   - `external_id = request.provenance.marker` as a reconciliation marker;
4. durably stores the returned `list_id`, `taskseries_id`, `task_id`, and transaction ID;
5. adds a fixed provenance note after the create result is stored;
6. reads the task back and stores the snapshot before reporting success.

The fixed RTM note is:

```text
Created from BrainBuddy Brain Dump.
Session: <operation_id>
Draft: <draft_id>
Route: <route_id>
Reference: bb:v1:<route_id>
```

It contains no audio, transcript, source spans, model output, user email, or credentials.
The accepted task title necessarily leaves BrainBuddy as the task title. No transcript or
other draft content is copied into the note.

Inbox is the safe default. The adapter adds no `na`, `@w8`, context/domain tag, priority,
due/start date, recurrence, reminder, location, estimate, assignee, or invented list. It
applies optional fields only when the frozen confirmation says the user explicitly chose
them and the binding reports support. V1 should initially expose none of those optional
fields in the UI; the DTOs prevent a future UI addition from bypassing confirmation.

### Get and list semantics

`get_task` uses the complete RTM task path in `ExternalTaskRef` and returns a normalized
snapshot. A not-found response does not erase the immutable reference; it returns
`state=unknown` or a typed result explaining that linked evidence can no longer be
verified.

`list_tasks` is bounded to one owner and at most 100 normalized results. For the normal
Brain Dump result view it may list recent tasks in the selected destination. For
reconciliation it restricts the query to the destination and a small attempt-time window,
then compares the exact `external_id` marker when the RTM response exposes it. Title and
timestamp may narrow candidates but never establish identity by themselves.

## Crash, retry, outbox, and reconciliation

Execution persists these records before network I/O:

```text
TaskRoute:
  id, owner_id, operation_id, draft_id, confirmation_action_id
  request_hash, status, external_ref?, created_at, updated_at, revision

TaskOutboxItem:
  id, owner_id, route_id, adapter, provenance_marker
  status: prepared | sending | succeeded | failed | reconciliation_required |
          ambiguous | cancelled
  next_attempt_at?, lease_owner?, lease_expires_at?
  attempt_count, last_error?, created_at, updated_at

TaskDispatchAttempt:
  id, owner_id, route_id, attempt_no
  status: started | succeeded | failed | outcome_unknown | reconciled
  request_hash, started_at, completed_at?
  external_ref?, remote_transaction_ref?
  error?: TaskTrackerError

TaskRouteResult:
  route_id, status, external_ref?, snapshot?, error?
  resolution: direct | reconciled | user_linked | user_confirmed_absent_retry
  updated_at
```

`(owner_id, confirmation_action_id)` and `(owner_id, route_id)` are unique. One worker may
lease an outbox item at a time. The request hash covers title, destination, explicit fields,
and provenance. A retry with another hash is rejected.

Recovery rules:

Never silently duplicate a task. In particular:

1. `prepared` can call create.
2. A failure proven to occur before any request was sent may become `failed/safe_retry`.
3. Any crash or transport/protocol failure after send begins becomes
   `reconciliation_required`; no automatic second create is allowed.
4. Reconciliation performs a bounded list query for the exact provenance marker.
5. Exactly one marker match is adopted, read back, and recorded as `reconciled/succeeded`.
6. More than one marker match becomes `ambiguous`; no candidate is silently chosen.
7. No match after bounded retries does not prove absence. The route becomes `ambiguous`
   unless the adapter can provide a trustworthy negative result.
8. The UI says: "RTM may have created this task. Check RTM, then link the existing task or
   confirm it is absent before retrying." It offers read-only candidate links, manual link,
   cancel, and an explicit "I checked; retry create" action.
9. That explicit retry creates a new attempt on the same route and remains auditable. If it
   later produces a duplicate, BrainBuddy shows both references; it never deletes one.

The RTM `external_id` is a marker, not assumed uniqueness or native idempotency. The
credentialed sandbox smoke test must confirm whether it is returned by the deployed API
and usable in reconciliation. If not, RTM remains supported with honest manual ambiguity;
title/time matching may suggest candidates but may not auto-resolve them.

The provenance-note call is a second remote side effect. Because the task reference is
persisted before adding the note, a note timeout retries/reconciles the note without
recreating the task. Note failure leaves task creation succeeded with a visible
`provenance_note_pending` warning and a retryable follow-up; it does not hide the task.

## Future BrainBuddy-native tracker

A future `BrainBuddyTaskTrackerAdapter` implements this same port. It may report native
idempotent create and provenance lookup, but Brain Dump does not gain tracker-specific
branches. Migration changes the configured binding only for new routes.

Existing RTM `ExternalTaskRef` values and route results are immutable linked evidence.
They remain rendered as RTM references even after the default adapter changes. There is no
bulk import, silent relinking, or rewriting of historical refs. If product evidence later
justifies a native tracker, its own schema is designed then. This tranche must not build
lists, calendars, recurrence, reminders, task editing, or completion semantics in advance.

## PR #60 assessment and corrective sequence

PR #60 is reusable foundation, not functional completion.

Retain surgically:

- modular package shape and application-workflow seam;
- owner-scoped persistence/auth/API test fixtures;
- immutable source versus mutable draft/item separation;
- expected revisions, command idempotency records, and decision audit concepts;
- route/attempt/result separation after moving ownership fully into Execution.

Correct or remove before merge:

- replace synchronous one-shot voice processing with the ADR-0002 operation lifecycle,
  including live numbered drafts, pause/resume, stop, projection reload, and confirmation;
- replace sentence heuristics/mock transcription as the claimed functional path (fakes may
  remain test-only);
- remove Weekly Review/Thinking/CRT product implementation from this tranche;
- move `TaskTrackerPort` and all its DTOs under Execution; it must not accept Organize's
  `RouteRecord` or return an internal `DispatchAttempt`;
- remove Execution's import of `OrganizeRepository` and direct mutation of routes;
- replace `MockTaskTrackerAdapter` as runtime default; a fake belongs in tests and must not
  invent completed external work in product responses;
- replace generic `except Exception -> retryable ADAPTER_ERROR` with the typed taxonomy and
  ambiguous-outcome handling;
- persist outbox/attempt before I/O, use deterministic markers, and surface durable
  per-draft results;
- never swallow a completion conflict after external success; reconcile local state and
  display the partial result.

Recommended surgical PR graph:

```text
A. Foundation salvage from #60
   Capture/Organize records + owner-scoped repositories + test fakes
   remove runtime mock success, synchronous completion claim, Weekly Review, and CRT scope
                |
B. Brain Dump operation and UI
   live numbered drafts + pause/resume/stop + review/freeze/confirm + reconnect projection
                |
C. Execution contract
   TaskTrackerPort DTOs + route/outbox/attempt/result + fake-client contract tests
                |
D. RTM adapter
   user binding + create/get/list + Inbox mapping + note + reconciliation
                |
E. Credentialed dogfood gate
   controlled sandbox task, read-back, cleanup/manual completion, evidence recorded
```

A and C may be combined if the diff remains reviewable. B can use an Execution fake but
may report only queued/test state outside production. D cannot merge as functional until
contract tests pass. E is a release gate, not a unit-test dependency.

## Rationale

This scope tests the product's shortest valuable loop without turning BrainBuddy into a
second task manager. Execution-owned DTOs prevent RTM concepts and Organize records from
leaking across boundaries. A durable outbox and explicit ambiguity are necessary because
local idempotency cannot make an uncooperative remote create idempotent. Keeping historical
external refs immutable preserves evidence and makes a future native tracker a plug-in
change rather than a migration fiction.

## Alternatives considered

### Merge PR #60 as the MVP and replace the mock later

Rejected. It reports fake external success, ignores the asynchronous interaction contract,
and has no safe crash/retry behavior. That would validate tests, not user value.

### Put RTM calls directly in the Brain Dump workflow

Rejected. It couples product state to one provider, exposes credentials and error semantics
to Organize, and blocks a future native adapter.

### Build a generic task-manager abstraction

Rejected. Update, complete, delete, recurrence, reminders, projects, and full sync are not
needed to prove Brain Dump and would create a lowest-common-denominator API.

### Retry timeout failures automatically with the same external ID

Rejected. RTM documents `external_id` as app-attached data, not as a uniqueness or
idempotency guarantee. Automatic retry could silently duplicate tasks.

### Build the BrainBuddy-native tracker now

Rejected. There is no evidence yet for a proprietary task-management model. The port and
immutable external refs preserve the future option without paying for it now.

## Consequences

Positive:

- the tranche has one testable user outcome;
- no external task exists without explicit confirmation;
- RTM defaults are deliberately low-authority and preserve the user's GTD decisions;
- crashes and timeouts remain recoverable without silent duplication;
- the adapter can change without rewriting Brain Dump or historical evidence.

Costs and risks:

- local route/outbox/attempt/result records add persistence work;
- RTM create plus provenance note is not atomic;
- ambiguous outcomes sometimes require the user to inspect RTM;
- the shared ADR-0002 substrate remains broader than the first shipped specialization.

Future agents must preserve:

- Brain Dump-only product scope until this tranche's acceptance tests pass;
- live drafts as provisional, with explicit per-draft/batch confirmation;
- Inbox, `parse=0`, and no inferred RTM metadata as defaults;
- Execution ownership of the port, outbox, attempts, refs, and result snapshots;
- reconciliation before retry after any potentially accepted create;
- immutable provider-qualified external refs;
- no proprietary task-manager domain until a separate accepted decision justifies it.

## Verification

The normative scenarios are in
`specs/003-brain-dump-task-tracker/acceptance-tests.md`. Implementation is not a functional
MVP until deterministic tests and one controlled credentialed RTM smoke test pass. PR #60's
mock success tests do not satisfy that gate.

## Related files

- `docs/decisions/0001-vnext-modular-monolith-and-workflow-contracts.md`
- `docs/decisions/0002-async-voice-operation-substrate.md`
- `specs/003-brain-dump-task-tracker/spec.md`
- `specs/003-brain-dump-task-tracker/acceptance-tests.md`
- PR #60 (`feat/voice-capture-mvp`)
- RTM API: `rtm.tasks.add`, `rtm.tasks.getList`, `rtm.tasks.notes.add`,
  `rtm.auth.checkToken`, and timelines
