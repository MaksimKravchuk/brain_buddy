# ADR-0002: Use one asynchronous operation substrate for voice capture and Weekly Review

Date: 2026-07-11
Status: Proposed
Decision owner: BrainBuddy
Related: ADR-0001, Kanban task `t_8a1164be`

## Context

ADR-0001 defines the vNext modular-monolith boundaries and durable capture/review
records, but its first implementation allowance for synchronous transcription does not
provide an adequate interaction contract for long voice input. A user must be able to
keep speaking while provisional work appears, leave and resume an operation, recover
from upload/provider failures, and approve durable changes only after a smarter pass has
reconciled the provisional output.

Weekly Review has the same shape: a long-lived user interaction receives transcript
segments, proposes incremental edits/actions against a bounded target set, reconciles
those proposals, and commits only confirmed outcomes. A separate blocking voice-review
flow would duplicate cancellation, retries, progress, ordering, privacy, and idempotency.

Todoist Ramble validates the usefulness of record, process, review, then add, but public
documentation does not establish live incremental task creation or correction. BrainBuddy
will deliberately go further with provisional streaming while retaining an explicit commit
gate.

## Decision

Introduce a shared `AsyncOperation` application substrate inside the modular monolith.
Both `voice_brain_dump` and `weekly_review_voice` use it. The operation owns orchestration,
progress, ordered model patches, confirmation batches, retry checkpoints, and operation
audit metadata. Domain modules continue to own canonical records and transitions.

Use two model stages:

1. A **fast streaming stage** transcribes stable speech segments and emits conservative,
   provisional candidates. It optimizes for responsiveness and may only touch the
   operation workspace.
2. A **smart reconciliation stage** runs after stop, pause-settle, or an explicit review
   checkpoint. It resolves targets and proposes merge/split/edit/route/review actions.
   It still cannot write canonical domain records.

Only an explicit user confirmation command applies a frozen proposal batch through
Capture, Organize, Review, Thinking, or Execution ports. Neither model stage may approve,
delete, route, promote, or mutate an external task.

## Ownership and records

`AsyncOperation` belongs to the application workflow layer, not to Capture or Review:

```text
AsyncOperation:
  id, owner_id, kind: voice_brain_dump | weekly_review_voice
  status: recording | uploading | fast_processing | reconciling |
          awaiting_confirmation | committing | completed |
          retryable_error | terminal_error | cancelling | cancelled
  phase_revision, proposal_revision, last_sequence
  target_snapshot?: {kind, ids[], revisions_by_id}
  upload?: {session_id, received_chunks[], expected_chunks?, sealed_at?}
  progress: {phase, completed_units?, total_units?, message_code, updated_at}
  consent: {microphone, external_processing_allowed, recorded_at, provider?}
  checkpoint: {last_stable_segment, fast_stage_complete, reconciler_input_hash?}
  active_proposal_batch_id?, committed_batch_id?
  last_error?: {code, stage, retryable, retry_after_ms?}
  created_at, updated_at, expires_at?, schema_version, revision

TranscriptSegment (operation-private):
  id, operation_id, sequence, start_ms, end_ms
  text, stability: interim | stable, confidence?, provider, model?
  supersedes_segment_id?, created_at

ProposalPatch (append-only):
  id, operation_id, sequence, base_proposal_revision
  producer: fast | reconciler | user
  operation: add | replace | remove | merge | split | reorder
  target: {kind: provisional | capture_item | review_item, id}
  payload, source_segment_ids[], confidence, reasons[]
  created_at

ProposalBatch:
  id, operation_id, based_on_proposal_revision
  status: draft | frozen | committing | committed | superseded | failed
  ordered_actions[]
  warnings[], unresolved_targets[]
  created_at, frozen_at?, committed_at?, revision

OperationCommand:
  id, operation_id, actor_id, command
  idempotency_key, expected_operation_revision
  request_hash, result_ref?, created_at
```

Raw audio remains Capture-private. Operation records contain an opaque upload/session
reference, not bytes or filesystem paths. Transcript segments and proposals are working
artifacts with a configurable short retention period; immutable source provenance and
confirmed audit decisions follow ADR-0001 retention rules.

A Weekly Review operation stores `weekly_review_id` and snapshots its item IDs and
revisions when it starts. It does not copy item text into its canonical record. Voice
proposals may address only that snapshot unless the user explicitly adds an item to the
review.

## Interaction and state machine

`idle` is a client state before an operation exists. The complete user-visible flow is:

```text
idle
  -> recording
  -> uploading
  -> fast_processing
  -> reconciling
  -> awaiting_confirmation
  -> committing
  -> completed
```

Recording and upload overlap in normal operation. `recording` remains the principal state
while chunks upload and stable segments/candidates arrive; progress exposes concurrent
subphases. After stop, the server seals the upload, drains fast processing, then starts
reconciliation. The serial diagram above describes completion gates, not a prohibition on
overlap.

Allowed exceptional transitions:

```text
recording|uploading|fast_processing|reconciling|awaiting_confirmation
  -> cancelling -> cancelled
recording|uploading|fast_processing|reconciling|committing
  -> retryable_error
recording|uploading|fast_processing|reconciling|committing
  -> terminal_error
retryable_error -> last durable checkpoint state
awaiting_confirmation -> reconciling       (user requests rerun after edits)
awaiting_confirmation -> committing         (confirm frozen batch)
committing -> awaiting_confirmation          (stale target or resolvable action failure)
```

Rules:

- Stop recording seals audio; it is not cancellation.
- Cancel is idempotent. Before commit it discards unconfirmed proposals and schedules raw
  media deletion. During commit it prevents not-yet-started actions but does not compensate
  already committed domain writes. The UI reports the partial result and offers undo where
  defined.
- Closing the UI never cancels. Reopening subscribes/polls by operation ID and resumes the
  current projection.
- A terminal error preserves enough redacted metadata to explain failure and allows audio
  deletion; it never creates canonical captures or review outcomes.
- Operation expiry cannot occur while recording, processing, awaiting confirmation, or
  committing. Expiry applies only to abandoned terminal/draft operations under policy.

## Offline, upload, retry, and progress

The client records chunked audio locally and assigns monotonically increasing chunk
numbers. Each chunk uses `(operation_id, chunk_number, content_sha256)` as its upload
identity. Repeating an identical chunk returns success; the same number with a different
hash returns `409 CHUNK_CONFLICT`. The seal command includes expected chunk count and a
manifest hash. Reconciliation cannot start until the manifest is complete.

If connectivity is lost while recording, the client continues local capture within a
configured storage/time limit and shows `Offline — recording locally`. On reconnection it
resumes missing chunks. If the local limit is approached, the UI warns and offers stop or
continue without server guarantees. Browser storage eviction or microphone loss is a
terminal capture error with an explicit salvage option for already-uploaded audio.

Retries resume from the last durable checkpoint:

- upload: request missing chunk numbers; never resend acknowledged chunks unnecessarily;
- fast stage: resume after the last stable transcript segment;
- reconciler: rerun from a sealed immutable input and current user patches;
- commit: query each action's idempotency key and continue unresolved actions.

The server publishes progress through an ordered event stream; polling the operation
projection is the required fallback. The UI shows recording duration/waveform, network
state, uploaded bytes or chunks, stable transcript availability, provisional candidate
count, reconciliation status, confirmation count, commit progress, and retryable error.
It must not show a fake percentage when total work is unknown; use indeterminate progress
plus stage text.

## Ordered event and patch contract

Events have `operation_id`, monotonically increasing `sequence`, `operation_revision`,
`type`, and a redacted payload. Delivery is at least once. Clients ignore a duplicate
sequence, buffer a bounded gap, and refetch the full projection if the gap does not close.
A reconnect sends `after_sequence`; server retention gaps return `projection_required`.

Model output never replaces the proposal document wholesale. It emits `ProposalPatch`
records against `base_proposal_revision`:

1. User patches have highest authority and are never silently overwritten.
2. Reconciler patches supersede fast patches only when all referenced source segments are
   represented and no user-edited field is changed.
3. Fast patches may replace only their own provisional targets.
4. A stale-base patch is rebased if it touches disjoint targets; otherwise it is rejected
   and the producer reruns against the current projection.
5. Display order defaults to earliest source-segment time, then patch sequence. A user
   reorder pins relative order. Merges occupy the earliest merged position; splits occupy
   the original position in source-span order.
6. Merge creates a new provisional ID, records all predecessor IDs and source segment IDs,
   and tombstones predecessors. Split does the analogous one-to-many mapping. UI selection
   and edits follow this lineage where unambiguous; otherwise confirmation is required.

Patch payloads distinguish transcript wording from inferred fields. The UI visually marks
provisional, reconciled, user-edited, low-confidence, conflicted, and removed proposals.
Churn is coalesced to at most one visible update per candidate every 500 ms; stable user
text is not made visually unstable by interim transcript updates.

## Concurrent speech and user edits

The user may edit provisional candidates while still speaking. Every edit is a `user`
patch with the candidate revision and locks only fields actually changed. New speech can
continue to add candidates. Reconciliation receives transcript segments, candidate
lineage, and user patches; it may suggest a conflicting alternative but cannot overwrite
a locked field.

The operation may also propose edits to existing BrainBuddy `CaptureItem`s or current
Weekly Review items. Such targets are resolved by opaque ID from the owner-scoped target
snapshot, never by title alone. A target proposal carries `expected_target_revision` and a
human-readable before/after diff. External task tracker objects are not editable in this
MVP; speech referring to one becomes a new capture or an unresolved proposal.

## Target resolution and confidence

Resolution is deterministic before semantic:

1. explicit UI-selected ID or voice disambiguation token;
2. unique exact alias/title within the operation target snapshot;
3. unique semantic match above the applicable threshold and margin;
4. unresolved target requiring user selection.

Never resolve across owners or outside the snapshot. If the best and second-best semantic
scores differ by less than `0.10`, or no candidate meets `0.85`, the target is unresolved.
Titles alone are hints, not durable identifiers. A user-selected resolution is stored as a
user patch and wins over later model output.

Confidence bands use calibrated scores, not provider labels copied without validation:

- `>= 0.90`: show as normal provisional/reconciled proposal;
- `0.75–0.89`: show with a review marker and include in the batch;
- `< 0.75`: do not infer destructive/routing intent; require clarification or preserve as
  an unclassified capture;
- any delete, route, merge across existing items, CRT promotion, or existing-item edit
  always requires confirmation regardless of score.

Thresholds are configuration-backed and changed only with evaluation evidence. Language,
microphone, and model/version are dimensions in calibration metrics.

## Two-stage responsibilities and latency budgets

The fast stage may:

- emit interim/stable transcript segments;
- detect clause boundaries;
- create, append to, or conservatively split provisional captures;
- classify broad `task | note | question | problem_candidate` intent;
- mark ambiguity and collect source spans.

It must not resolve existing targets semantically, merge independent captures, infer a
destination, modify domain records, or emit confirmation-ready destructive actions.

The reconciler may propose normalized wording, deduplication, merge/split, destination,
clarification questions, existing-item edits, Weekly Review outcomes, and CRT candidates.
It must preserve source lineage and user field locks, explain nontrivial changes, and emit
patches rather than mutate canonical state.

Service-level objectives measured at p95 on supported conditions:

- local recording feedback: `<100 ms` from captured frame;
- stable partial transcript: `<700 ms` after a speech segment ends;
- first provisional candidate: `<1.5 s` after a clause boundary;
- visible patch propagation: `<500 ms` after server emission;
- post-stop fast-stage drain: `<2 s` for already-streamed audio;
- reconciled batch: `<8 s` for a 2-minute dump, `<20 s` for the configured maximum;
- commit acknowledgement: `<1 s` for local writes, while external route completion remains
  an independently visible asynchronous state.

Budgets are product targets, not correctness timeouts. On fast-stage failure, continue
recording/upload and run batch transcription after stop. On reconciler failure, retain
user-edited and stable fast candidates, mark them unreconciled, and allow manual review or
retry. If both fail but audio is intact, offer transcript-only retry. No fallback bypasses
confirmation.

## Confirmation, commit, idempotency, and partial failure

Before confirmation, freeze a `ProposalBatch` at a proposal revision. Every action shows
its target, before/after state, source cue, confidence/warning, and destination. The user
may select all safe additions but destructive or existing-item changes remain individually
visible. Editing after freeze supersedes the batch and requires a new freeze.

Confirmation uses one command idempotency key and one deterministic child key per action:
`H(operation_id, batch_id, action_id)`. Repeating the same key and request hash returns the
original result; reusing a key with another hash returns `409 IDEMPOTENCY_CONFLICT`.

Commit order is:

1. persist new immutable Capture sources and mutable Organize items;
2. apply confirmed edits/decisions to existing items using expected revisions;
3. record Weekly Review outcomes referencing successful decisions;
4. request routes or CRT promotions, which remain separately asynchronous;
5. mark the batch and operation completed when all local actions are recorded.

Actions form a dependency DAG. Independent actions may commit concurrently, but audit and
result presentation use batch order. A dependency failure skips dependants and does not
roll back successful independent actions. The batch becomes `failed` with per-action
results and can be retried idempotently. A stale target never receives a last-write-wins
update: refresh its diff and return to confirmation.

## Undo

Undo is a new, explicit, idempotent domain command linked to the original action; it is not
history deletion:

- unconfirmed patches: remove/revert freely within the operation workspace;
- newly created, not-routed captures: soft-delete and record an undo decision;
- existing-item edits: apply the stored inverse patch only if its current revision still
  equals the committed result revision; otherwise require a new reviewed edit;
- review outcomes: append a superseding outcome while the review is open;
- pending routes/promotions: cancel if the adapter/domain has not started them;
- successful external route, promotion, or evidence record: no automatic undo in MVP;
  show what happened and provide an explicit follow-up action.

The UI displays the actual undo scope and expiry rather than promising atomic rollback.

## Provenance, consent, and privacy

Every proposal and committed action links to source transcript segment IDs and, after
commit, to ADR-0001 `AtomicCaptureSource` IDs. Model/provider/version, prompt/template
version, confidence, operation ID, proposal lineage, user edits, confirmation actor/time,
and idempotency keys are audit metadata. Raw text/audio never enters logs, metrics, or
operation events.

Microphone permission and external-processing consent are separate. Recording may begin
only after microphone permission; audio may leave the device only after current external
processing consent naming the configured provider category. With no external consent, use
a configured local model or disable voice processing clearly—never silently upload.
Consent withdrawal stops future upload/provider calls and schedules uncommitted audio and
working transcripts for deletion; already confirmed domain provenance follows the product
retention policy and must be separately erasable through a privacy operation.

Default working-artifact retention is seven days after completion/cancellation and 24 hours
for raw audio after successful reconciliation, both configuration-backed. Users can delete
raw audio immediately after processing and can see the retention state. Analytics contain
only IDs, stage timings, coarse confidence bands, counts, and error codes.

## API and transport contract

Minimum endpoints (all owner-scoped, authenticated, correlation-ID-bearing):

```text
POST /operations                         -> create kind/consent/target snapshot
GET  /operations/{id}                    -> current projection
GET  /operations/{id}/events?after=N     -> SSE or long-poll ordered events
PUT   /operations/{id}/audio/{chunk_no}  -> idempotent chunk upload
POST  /operations/{id}/seal              -> seal manifest / stop
POST  /operations/{id}/commands          -> edit, reorder, resolve, cancel, retry
POST  /operations/{id}/proposal-batches  -> freeze current revision
POST  /operations/{id}/confirm           -> idempotent batch commit
POST  /operations/{id}/undo              -> explicit inverse command
```

WebSocket is optional; correctness must not depend on it. SSE plus REST upload/commands and
polling fallback is sufficient. Commands require `Idempotency-Key` and
`expected_operation_revision`. Chunk upload uses its manifest identity instead.

ADR-0001 capture/review endpoints remain domain-level contracts. The operation workflow
invokes those ports; clients should not orchestrate a voice flow by calling domain
endpoints directly.

## Weekly Review specialization

A voice-led Weekly Review starts/resumes the ADR-0001 `WeeklyReview`, then creates a
`weekly_review_voice` operation with the review snapshot. Spoken commands produce the same
patch forms and confirmation batches as a brain dump. Review-specific proposals can
`keep`, `edit`, `delete`, `defer`, `route`, or `promote_to_crt`; new thoughts create normal
provisional captures in the same batch.

The UI may converse item by item while the microphone remains active. The currently shown
item ID is an explicit target hint, not permission to mutate it. The user can navigate away
and resume from operation projection. Completing the review is a confirmed final action
that validates one outcome per snapshotted item. Failure or cancellation leaves the
Weekly Review open and resumable; there is no blocking request and no separate voice state
machine.

## Rationale

The two-stage design separates responsiveness from authority. Fast output reassures the
user that speech is being captured and makes correction possible while context is fresh;
the reconciler gets a sealed, provenance-rich input suitable for global merge, split, and
target proposals. Keeping both stages proposal-only means a latency optimization cannot
silently become a data-integrity or external-side-effect policy.

A shared operation substrate is justified by lifecycle, not by the word “voice.” Brain
dump and Weekly Review need the same reconnect, event ordering, cancellation, patch,
confirmation, commit, privacy, and retry guarantees. Domain ownership remains in the
ADR-0001 modules, so this reuse does not collapse Capture and Review into a generic model.

Explicit snapshots, expected revisions, source lineage, and action idempotency make the
hard cases visible: concurrent edits become confirmation conflicts, timeout-after-accept
becomes a lookup/retry, and partial commit becomes a result set rather than an invented
transaction. This is more honest and implementable on the existing modular monolith than
promising atomic rollback across local and external systems.

## Consequences

Positive:

- responsive capture without trusting unstable partial inference;
- one recovery, privacy, progress, patch, and commit contract for both workflows;
- user edits and immutable provenance survive model reconciliation;
- retries and reconnects cannot duplicate domain writes;
- provider/model stages remain replaceable and measurable.

Costs and risks:

- operation projections, patch lineage, and idempotent batch commits add complexity;
- file-backed persistence must serialize per-operation append/write and may reach ADR-0001's
  SQLite migration trigger sooner;
- confidence thresholds require an evaluation corpus and ongoing calibration;
- partial commit and bounded undo must be communicated honestly in the UI.

Future agents must preserve:

- one operation substrate and state machine for brain dump and voice-led Weekly Review;
- model output as proposals only, with explicit confirmation before canonical writes;
- user-edit field locks, immutable source lineage, owner-scoped snapshot target resolution,
  expected revisions, and deterministic action idempotency keys;
- ordered replayable events with a projection/polling fallback rather than transport-bound
  correctness;
- separate microphone permission and external-processing consent, redacted telemetry, and
  configurable deletion/retention;
- bounded undo and transparent partial outcomes instead of claimed cross-system rollback.

## Alternatives considered

### Batch only after recording

Rejected as the primary UX. It is simpler and is a valid fallback, but gives no early
capture confidence and prevents correction while speaking.

### Let the fast model create tasks directly

Rejected. Partial speech is unstable, target resolution is ambiguous, and direct writes
would make corrections, deduplication, privacy, and idempotency unsafe.

### One large smart-model call

Rejected. It misses responsiveness targets and creates a single failure/retry boundary.
The reconciler remains a bounded second stage over an immutable sealed input.

### Separate Weekly Review voice workflow

Rejected. Its lifecycle and failure semantics are the same as voice capture. Review owns
outcomes; it does not need a second operation engine.

### Broker and dedicated workers immediately

Rejected for MVP. Persisted operations plus an in-process/background runner are sufficient.
Extract transcription only when ADR-0001's measured scaling/failure criteria are met.

## Verification

The [acceptance scenarios](../../specs/002-async-voice-workflows/acceptance-tests.md) are
normative for implementation.
No product code is introduced by this ADR.

## Related files

- `docs/decisions/0001-vnext-modular-monolith-and-workflow-contracts.md`
- `specs/002-async-voice-workflows/spec.md`
- `specs/002-async-voice-workflows/acceptance-tests.md`
- `AGENTS.md`
