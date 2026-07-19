# ADR-0002: Use one asynchronous operation substrate for voice capture and Weekly Review

Date: 2026-07-11
Status: Proposed
Decision owner: BrainBuddy
Related: ADR-0001, Kanban tasks `t_8a1164be` and `t_58293688`
Last amended: 2026-07-19 (real-provider invariants and STT/extraction evaluation separation)

## 2026-07-19 amendment: real-provider invariants

The 2026-07-18 contract assumed deterministic fakes as the production default.
The shipped v1 code confirmed five root causes against `origin/main` `c0c12b0`:
browser locale from `navigator.language`, `DeterministicAccurateStt` decoding
binary audio as UTF-8, regex/hardcoded fixture extraction in the production
path, synthetic-tone evaluation with injected expected transcripts, and
hardcoded `external_processing_allowed=False` with no language/vocabulary hint
propagation.

The real-provider amendment adds these invariants without altering the
operation/patch/confirmation substrate:

- Production MUST NOT instantiate `DeterministicAccurateStt` silently. An
  explicit env escape hatch (`BRAINBUDDY_ALLOW_DETERMINISTIC_STT=1`) is
  allowed for local dev and logged as a warning; production startup refuses
  it otherwise.
- The production accurate-STT adapter MUST consume sealed original audio bytes
  as audio (e.g. multipart upload). Binary audio MUST NEVER be decoded as
  UTF-8 text in the production decision path.
- The production task reconciler MUST be a structured semantic text-model
  process emitting only schema-valid `add/update/split/merge/remove/supersede`
  operations. Regex/hardcoded fixture extraction is removed from the
  production decision path; `DeterministicTextReconciler` remains CI-only.
- `language_hints` (`ru`, `ru+en`) and `vocabulary` (recurring project, person,
  and product names) MUST propagate from operation consent to every fast-STT,
  accurate-STT, and reconciler invocation. Browser preview locale MUST follow
  declared hints, not `navigator.language` alone.
- Provider configuration is role- and schema-based (`provider`, `model`,
  `api_key_env`, `timeout_seconds`, `max_retries`, `retry_backoff_seconds`,
  `max_cost_usd_per_operation`); a provider change must not alter operation,
  transcript, proposal, or confirmation contracts.
- A real-audio evaluation harness MUST report STT quality (CER/WER,
  critical-term recall, omission/hallucination counts, latency) separately
  from task-extraction quality (task-count accuracy, boundary
  precision/recall, title cleanliness, conjunction false-split rate, semantic
  preservation, calibration) by language and provider/model version, without
  injecting expected transcripts or tone fixtures into the production
  decision path.
- Release targets on the approved founder corpus: 100% critical-term
  preservation, zero invented tasks, at least 95% exact task-count accuracy,
  at least 95% task-boundary precision/recall, and all safety/idempotency
  invariants passing. A measured CER/WER threshold is established from the
  first baseline.

These invariants are already implicit in the provider-port, consent, privacy,
and observability sections above. The amendment makes them explicit for
implementation agents. See `specs/002-async-voice-workflows/` for the amended
spec, plan, tasks, checklist, and acceptance tests.

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

Use three replaceable logical provider roles, with task extraction and reconciliation as
two methods of the same text role:

1. **Fast STT** consumes bounded windows of the original recording and emits low-latency,
   time-aligned transcript hypotheses. Browser speech recognition may supply a labelled
   preview fallback, but is never the authoritative mixed-language transcript.
2. **Accurate STT** runs after stop or an explicit reconciliation checkpoint and processes
   the sealed original audio. It does not transcribe the fast text. It emits a new,
   time-aligned transcript generation that explicitly supersedes the hypotheses it
   corrects.
3. **Text task reconciler** extracts conservative provisional tasks from stable fast
   windows while recording, then reconciles the accurate transcript against current
   proposal lineage, user edits, and field locks. Both methods emit append-only proposal
   patches; neither mutates canonical tasks.

The roles may be separate providers or two modes of one provider. Role selection is
configuration and dependency-injection wiring, not a stored vendor enum or a branch in
domain logic. A provider change must not change operation, transcript, proposal, or
confirmation contracts.

Only an explicit user confirmation command applies a frozen proposal batch through
Capture, Organize, Review, Thinking, or Execution ports. No provider role may approve,
delete, route, promote, create a native task, or mutate an external task.

## Ownership and records

`AsyncOperation` belongs to the application workflow layer, not to Capture or Review:

```text
AsyncOperation:
  id, owner_id, kind: voice_brain_dump | weekly_review_voice
  status: recording | paused | sealing | fast_processing |
          accurate_transcribing | reconciling |
          awaiting_confirmation | committing | completed |
          retryable_error | terminal_error | cancelling | cancelled
  phase_revision, proposal_revision, last_sequence
  target_snapshot?: {kind, ids[], revisions_by_id}
  audio: {session_id, media_ref, received_chunks[], expected_chunks?,
          manifest_hash?, duration_ms?, sealed_at?, retention_until?}
  progress: {phase, completed_units?, total_units?, message_code, updated_at}
  consent: {microphone, external_processing_allowed, recorded_at,
            allowed_provider_categories[]}
  checkpoint: {last_audio_chunk, last_fast_window_end_ms?,
               accurate_generation_id?, reconciler_input_hash?,
               resume_status?, recovery_count}
  reconciliation_quality: none | provisional_only | accurate | conflicted
  active_proposal_batch_id?, committed_batch_id?
  last_error?: {code, stage, retryable, retry_after_ms?}
  created_at, updated_at, expires_at?, schema_version, revision

ProviderRun (append-only attempt/result envelope):
  id, operation_id, role: fast_stt | accurate_stt | text_reconciler
  method: transcribe_window | transcribe_audio |
          extract_provisional | reconcile
  input_hash, provider, model?, template_version?
  status: queued | leased | succeeded | retry_wait | failed | cancelled
  attempt, max_attempts, deadline_at?, next_attempt_at?
  lease_owner?, lease_expires_at?, output_ref?, error_code?
  created_at, updated_at

TranscriptSegmentVersion (operation-private, append-only):
  id, operation_id, sequence, generation_id
  lane: browser_preview | fast | accurate
  start_ms, end_ms, text
  stability: interim | stable | final
  language_codes[], confidence?, provider_run_id
  supersedes_segment_ids[], created_at

Proposal (projection rebuilt from patches):
  id, operation_id, ordinal
  state: active | tombstoned | superseded
  title, source_segment_ids[], source_audio_spans[]
  predecessor_ids[], successor_ids[]
  locked_fields[], open_conflict_ids[]
  created_at, revision

ProposalPatch (append-only):
  id, operation_id, sequence, base_proposal_revision
  producer: fast_extractor | reconciler | user
  provider_run_id?, input_hash?, idempotency_key
  operation: add | update | split | merge | remove | supersede | reorder
  target_ids[], creates[], field_changes?
  source_segment_ids[], source_audio_spans[]
  confidence?, reasons[], created_at

ProposalConflict (append-only resolution history):
  id, operation_id, proposal_id, field
  locked_value, suggested_value, source_patch_id
  status: open | accepted | dismissed
  resolved_by?, resolved_at?, created_at

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

`sequence` is append order, not transcript display order. The transcript projection sorts
active segment versions by `(start_ms, end_ms, sequence)`. A segment version is active when
no later accepted version names it in `supersedes_segment_ids`. Many-to-many correction is
therefore representable: one accurate segment may supersede several fast hypotheses, or
several accurate segments may supersede one run-on hypothesis. The old versions remain
auditable. Every provider-produced segment has a non-negative audio span with
`end_ms > start_ms`; browser preview adapters must provide at least the corresponding
client capture-clock span and label its precision as preview-only.

The authoritative reconciliation transcript is the active `accurate` generation from the
latest successful accurate-STT run. Fast and browser-preview segments remain available as
provenance and fallback material but cannot silently outrank it. The accurate provider is
passed the sealed `media_ref`, audio metadata, language hints (for example `ru` and `en`),
and optional product vocabulary. It is never passed fast text as the audio input.

Raw audio remains Capture-private. Operation records contain an opaque upload/session
reference, not bytes or filesystem paths. Transcript segments and proposals are working
artifacts with a configurable short retention period; immutable source provenance and
confirmed audit decisions follow ADR-0001 retention rules.

A Weekly Review operation stores `weekly_review_id` and snapshots its item IDs and
revisions when it starts. It does not copy item text into its canonical record. Voice
proposals may address only that snapshot unless the user explicitly adds an item to the
review.

## Provider ports and persisted runner

The application workflow depends on narrow ports. Drafts returned by an adapter contain
no domain objects and cannot be persisted directly:

```text
FastSttPort.transcribe_window(
  AudioWindowRef, SttContext
) -> TranscriptSegmentDraft[]

AccurateSttPort.transcribe_audio(
  SealedAudioRef, SttContext
) -> TranscriptSegmentDraft[]

TextReconcilerPort.extract_provisional(
  StableTranscriptWindow, ProposalProjection
) -> ProposalPatchDraft[]

TextReconcilerPort.reconcile(
  AccurateTranscriptProjection, ProposalProjection,
  UserLocks, OpenConflicts
) -> ProposalPatchDraft[]
```

`SttContext` carries permitted language hints, product vocabulary, audio format/duration,
and a correlation ID. It never contains credentials. The workflow validates spans,
references, patch preconditions, output size, and schema version before materializing
provider drafts. The server allocates segment, proposal, patch, and conflict IDs; provider
text cannot choose owner IDs or canonical task IDs.

`ProviderRun` is the persisted work queue for the MVP. An in-process background runner
scans due runs, claims one with a compare-and-set lease, invokes the configured port under
a deadline, and atomically appends accepted output plus the next checkpoint. Correctness
must not depend on an in-memory queue or an untracked `asyncio` task. On process start and
periodically thereafter, expired leases are returned to `queued` or `retry_wait` and the
operation projection is reconciled from persisted state.

Each stage has configuration-backed timeout, maximum attempts (default three), exponential
retry delay with a cap, and an operation-level recovery budget. A timeout or process death
never increments a transcript/proposal revision unless output was durably accepted. The
same `(operation_id, role, method, input_hash)` reuses the successful run and output;
provider timeout-after-accept therefore cannot append duplicate segments or patches.
Exhausting a retryable stage moves the operation to `retryable_error` with its prior
checkpoint and a manual retry action. Exceeding the operation recovery budget moves it to
`terminal_error` without canonical task creation. Adding a broker, Celery, a worker
service, or distributed leases requires measured evidence under ADR-0001's extraction
criteria.

## Interaction and state machine

`idle` is a client state before an operation exists. The complete user-visible flow is:

```text
idle
  -> recording
  <-> paused
  -> sealing
  -> fast_processing
  -> accurate_transcribing
  -> reconciling
  -> awaiting_confirmation
  -> committing
  -> completed
```

Recording and upload overlap in normal operation. `recording` remains the principal state
while chunks upload and stable segments/candidates arrive; progress exposes concurrent
subphases. `paused` stops microphone capture but does not discard acknowledged chunks or
proposals. After Stop, the server enters `sealing`, validates the complete audio manifest,
drains fast processing, calls accurate STT on the sealed original audio, and reconciles its
final transcript. The serial diagram describes completion gates, not a prohibition on
recording, upload, fast STT, and provisional extraction overlapping.

Allowed exceptional transitions:

```text
recording|paused|sealing|fast_processing|accurate_transcribing|
reconciling|awaiting_confirmation
  -> cancelling -> cancelled
recording|sealing|fast_processing|accurate_transcribing|reconciling|committing
  -> retryable_error
recording|sealing|fast_processing|accurate_transcribing|reconciling|committing
  -> terminal_error
retryable_error -> last durable checkpoint state
retryable_error -> awaiting_confirmation    (explicit provisional-only review)
awaiting_confirmation -> accurate_transcribing (retry from original audio)
awaiting_confirmation -> reconciling        (rerun after edits)
awaiting_confirmation -> committing         (confirm frozen batch)
committing -> awaiting_confirmation         (stale target or resolvable action failure)
```

Rules:

- Stop recording requests a seal; it is not cancellation and does not jump directly to
  Review. The UI shows `Finishing upload`, `Improving transcript`, and `Reconciling tasks`
  for `sealing`, `accurate_transcribing`, and `reconciling` respectively. Only
  `awaiting_confirmation` renders the explicit Review state.
- `awaiting_confirmation` exposes `reconciliation_quality`. A provisional-only fallback
  is visibly labelled, requires the user to choose it after accurate-STT/reconciler
  exhaustion, and still uses explicit confirmation. It is never called accurate or
  silently selected.
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
- fast STT/extraction: resume at the first uncovered audio window and reuse a successful
  `(role, method, input_hash)` run;
- accurate STT: rerun against the same sealed original-audio manifest and append a new
  generation only after full output validation;
- reconciler: rerun from the immutable accurate generation plus the current proposal
  projection, locks, and conflicts;
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
2. Reconciler `update` keeps a proposal ID only when the same user intent remains. It may
   correct wording and source spans but must not change a locked field.
3. Fast-extractor patches may update only active provisional proposals created by the same
   source window. They cannot revive tombstoned/superseded proposals.
4. A stale-base patch is rebased if it touches disjoint targets; otherwise it is rejected
   and the producer reruns against the current projection.
5. Display order defaults to earliest source-segment time, then patch sequence. A user
   reorder pins relative order. Merges occupy the earliest merged position; splits occupy
   the original position in source-span order.
6. `split` atomically creates two or more server-assigned IDs, links each child to the one
   predecessor, and marks that predecessor `superseded`. `merge` atomically creates one
   server-assigned ID linked to all predecessors and marks each predecessor `superseded`.
   Structural successors inherit source spans and unlocked fields, not user locks by
   guesswork. If a locked predecessor cannot map unambiguously, the patch creates a visible
   conflict and leaves the active projection unchanged.
7. `remove` marks a proposal `tombstoned`; `supersede` performs a one-to-one replacement
   when semantic identity changed. Neither operation erases a proposal or patch. Active
   API lists hide tombstoned/superseded proposals by default, while an audit/debug
   projection can include them.
8. New IDs are allocated while atomically materializing a successful provider run. A
   repeated run with the same input hash returns the prior patch IDs and proposal-ID
   mapping. A later run receives current opaque IDs and must express lineage explicitly;
   array position is never identity.

Patch payloads distinguish transcript wording from inferred fields. The UI visually marks
provisional, reconciled, user-edited, low-confidence, conflicted, and removed proposals.
Churn is coalesced to at most one visible update per candidate every 500 ms; stable user
text is not made visually unstable by interim transcript updates.

## Concurrent speech and user edits

The user may edit provisional candidates while still speaking. Every edit is a `user`
patch with the candidate revision and locks only fields actually changed. New speech can
continue to add candidates. Reconciliation receives transcript segments, candidate
lineage, and user patches; it may suggest a conflicting alternative but cannot overwrite
a locked field. Editing `title` locks only `title`; deleting locks lifecycle state; a user
reorder locks relative order. Unedited source spans and confidence may still improve.

When a reconciler draft touches a lock, the workflow appends `ProposalConflict` containing
the current user value and suggested value but does not apply the field change. Review
shows both values with `Keep mine` and `Use suggestion`. Resolving either choice is a user
patch and closes the conflict without deleting it. Freeze/confirm is rejected while an
active proposal has an open conflict. A user-deleted proposal never reappears because of a
provider rerun; any suggested restoration is a conflict requiring an explicit user action.

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

## Provider-role responsibilities and latency budgets

Fast STT may emit interim/stable, time-aligned transcript versions and language/confidence
metadata. It does not create proposals. Accurate STT may emit only final, time-aligned
transcript versions from sealed original audio. It does not consume proposal text or make
task decisions.

The text role's provisional method may detect semantic task boundaries, create/update
provisional proposals, mark ambiguity, and collect source spans. It must not resolve
existing targets semantically, merge independent existing items, infer metadata or a
destination, modify domain records, or emit confirmation-ready destructive actions. For
`voice_brain_dump`, its proposal payload is deliberately limited to `title`, source spans,
confidence, and reasons.

The text role's reconciliation method may propose normalized wording, deduplication,
add/update/split/merge/remove/supersede operations, clarification, and—when invoked by the
Weekly Review specialization—review outcomes and target actions. It must preserve source
lineage and field locks, explain nontrivial changes, and emit patches rather than mutate
canonical state. Semantic boundaries come from the utterance and context, not punctuation
or conjunction tokens alone: `купить хлеб и молоко` is one task, while an unpunctuated
run-on containing distinct intents can be several.

Service-level objectives measured at p95 on supported conditions:

- local recording feedback: `<100 ms` from captured frame;
- stable partial transcript: `<700 ms` after a speech segment ends;
- first provisional candidate: `<1.5 s` after a clause boundary;
- visible patch propagation: `<500 ms` after server emission;
- post-stop fast-stage drain: `<2 s` for already-streamed audio;
- reconciled batch: `<8 s` for a 2-minute dump, `<20 s` for the configured maximum;
- commit acknowledgement: `<1 s` for local writes, while external route completion remains
  an independently visible asynchronous state.

Budgets are product targets, not correctness timeouts. On fast-STT failure, continue
recording/upload and run accurate STT after stop. On accurate-STT failure, preserve the
original audio and provisional tasks for bounded retry or explicitly chosen
provisional-only review. On reconciler failure, retain the accurate transcript, user edits,
and stable provisional candidates, mark them unreconciled, and allow retry or explicit
manual review. If audio is intact, offer an accurate-transcript retry from that audio—not a
retry over fast text. No fallback bypasses confirmation.

## Confirmation, commit, idempotency, and partial failure

Before confirmation, freeze a `ProposalBatch` at a proposal revision. Every action shows
its target, before/after state, source cue, confidence/warning, and destination. The user
may select all safe additions but destructive or existing-item changes remain individually
visible. Editing after freeze supersedes the batch and requires a new freeze.

Confirmation uses one command idempotency key and one deterministic child key per action:
`H(operation_id, batch_id, action_id)`. Repeating the same key and request hash returns the
original result; reusing a key with another hash returns `409 IDEMPOTENCY_CONFLICT`.

For the native `voice_brain_dump` vertical slice, every selected action is exactly
`create_native_inbox_task {proposal_id, title}`. The Task application port sets
`state=inbox`, `details=null`, `project_id=null`, `tag_ids=[]`, `due_date=null`, and
`priority=none`; the operation never infers those fields from speech. Tombstoned or
superseded proposals are excluded, and an open conflict prevents freeze/confirm. One
action key can produce at most one task ID even after timeout, process restart, or a retry
with a new outer HTTP request. No task row, Capture/Organize record, route, or external
side effect exists before this confirmation command.

Commit order is specialization-aware:

1. for native Brain Dump additions, persist each Inbox task plus an immutable operation
   action receipt/source link under the child key; for ADR-0001 capture flows, persist new
   immutable Capture sources before mutable Organize items;
2. apply confirmed edits/decisions to existing items using expected revisions;
3. record Weekly Review outcomes referencing successful decisions;
4. request routes or CRT promotions, which remain separately asynchronous;
5. mark the batch and operation completed when all applicable local actions are recorded.

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

Every proposal and committed action links to source transcript segment IDs. ADR-0001
capture flows additionally link `AtomicCaptureSource` IDs; native Inbox tasks link the
operation action receipt and proposal ID through their source reference. Model/provider/
version, prompt/template version, confidence, operation ID, proposal lineage, user edits,
confirmation actor/time, and idempotency keys are audit metadata. Raw text/audio never
enters logs, metrics, or operation events.

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

The first vertical slice keeps the current owner-scoped route family rather than adding a
second generic controller. All endpoints are authenticated and correlation-ID-bearing:

```text
POST /api/brain-dump-operations
  -> create operation with consent and language hints
GET  /api/brain-dump-operations/{id}
  -> current owner-scoped projection
GET  /api/brain-dump-operations/{id}/events?after=N
  -> SSE or long-poll ordered events
PUT  /api/brain-dump-operations/{id}/audio/{chunk_no}
  -> idempotent chunk upload with hash/start_ms/end_ms
POST /api/brain-dump-operations/{id}/seal
  -> stop and seal expected chunk count/manifest hash
POST /api/brain-dump-operations/{id}/commands/{pause|resume|cancel|retry|review-provisional}
  -> persisted state command
POST /api/brain-dump-operations/{id}/preview-segments
  -> optional browser-preview hypotheses; never authoritative
POST /api/brain-dump-operations/{id}/proposals/{proposal_id}/patches
  -> user edit/remove/reorder with field locks
POST /api/brain-dump-operations/{id}/conflicts/{conflict_id}/resolve
  -> keep user value or accept suggestion
POST /api/brain-dump-operations/{id}/proposal-batches
  -> freeze active, conflict-free proposal revision
POST /api/brain-dump-operations/{id}/confirm
  -> idempotent native Inbox task creation
POST /api/brain-dump-operations/{id}/undo
  -> explicit inverse command
```

WebSocket is optional; correctness must not depend on it. SSE plus REST upload/commands and
polling fallback is sufficient. Commands require `Idempotency-Key` and
`expected_operation_revision`. Chunk upload uses its manifest identity instead.

The GET projection is a cacheable representation, not the append log. In addition to the
operation fields above it returns:

```text
transcript: {
  authoritative_generation_id?, quality,
  active_segments[]: {id, lane, start_ms, end_ms, text,
                      language_codes[], confidence?, supersedes_segment_ids[]}
}
proposals[]: {
  id, ordinal, state=active, title, source_audio_spans[],
  predecessor_ids[], locked_fields[], open_conflicts[], revision
}
history: {last_sequence, hidden_proposal_count, projection_revision}
```

The default projection omits provider payloads and hidden proposal bodies but includes the
IDs needed to request an owner-scoped audit view. Every referenced segment, proposal,
conflict, provider run, batch, and resulting task is checked against the operation owner;
a wrong-owner operation or nested ID returns `404` without revealing existence. Event
payloads carry IDs, enum states, counts, coarse confidence bands, and progress only—never
audio, transcript/task text, language vocabulary, provider responses, local paths, emails,
or credentials.

ADR-0001 capture/review endpoints remain domain-level contracts. The operation workflow
invokes those ports; clients should not orchestrate a voice flow by calling domain
endpoints directly.

## Current implementation migration and smallest vertical slice

At this amendment, the shipped v1 Brain Dump stores one JSON/SQLite payload per operation,
accepts browser Web Speech text through `/transcript`, mutates an interim segment in place,
rebuilds proposals positionally from punctuation/number-list splitting, and moves `finish`
directly to `awaiting_confirmation`. The browser fixes one locale from
`navigator.language`. These are compatibility facts, not behavior to preserve for new
operations.

Use `schema_version=2` for newly recorded operations and migrate without a flag day:

1. Completed/cancelled v1 operations remain readable and immutable. Never replay them or
   create tasks during migration.
2. An active v1 operation is imported once as `legacy_preview_only`: each old segment
   becomes a `browser_preview` segment version with an unknown/coarse capture span; each
   proposal keeps its existing ID through a synthetic `add` patch; `user_edited=true`
   becomes a `title` lock; `deleted=true` becomes a user `remove` tombstone.
3. Because v1 has no durable original audio, imported operations cannot claim accurate
   reconciliation. They may be cancelled or explicitly reviewed/confirmed with a visible
   `provisional_only` warning. Retry never fabricates an accurate transcript.
4. During one frontend/backend compatibility window, `/transcript`, `/finish`, `/commit`,
   and direct proposal PATCH remain aliases for preview-segment, seal, confirm, and user
   patch commands only for v1-aware clients. Responses include new fields additively. Remove
   aliases only after deployed clients and stored active operations no longer need them.
5. The existing owner-partitioned SQLite payload can store v2 append arrays and projections
   for the thin slice. Add normalized tables or another store only after measured payload,
   contention, or recovery evidence; do not introduce a broker or microservice as a schema
   migration.

Implementation order is one thin end-to-end slice, not a provider platform program:

1. Record/upload original audio with v2 operation, segment-version, patch, lease, polling,
   retention, and v1 migration contracts.
2. Wire one fast-STT adapter/fake plus provisional extraction so numbered proposals grow
   while speaking; retain browser Web Speech only as labelled preview/fallback.
3. On seal, run accurate STT from `media_ref`, then reconcile into stable lineage and
   conflicts; expose processing and Review states.
4. Freeze and explicitly confirm title-only native Inbox actions with deterministic child
   keys; add the deterministic multilingual/e2e gates before enabling a paid provider.

Weekly Review reuses these substrate types and ports later, but this slice adds no Weekly
Review UX, CRT, routing, external tracker, inferred metadata, or autonomous execution.

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

The role-separated design separates responsiveness, transcription authority, and task
interpretation. Fast output reassures the user that speech is being captured; accurate STT
can correct mixed-language names from original audio; the reconciler gets a sealed,
provenance-rich transcript suitable for global merge, split, and target proposals. Keeping
every provider role operation-private means a latency or quality optimization cannot
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
- append-heavy operation payloads and leases add SQLite contention/payload-growth risk and
  may eventually justify normalized operation tables;
- confidence thresholds require an evaluation corpus and ongoing calibration;
- partial commit and bounded undo must be communicated honestly in the UI.

Future agents must preserve:

- one operation substrate and state machine for brain dump and voice-led Weekly Review;
- replaceable fast-STT, accurate-STT, and text-reconciler roles, with accurate STT reading
  sealed original audio rather than fast text;
- append-only, time-aligned transcript versions with explicit supersession, and stable
  proposal identity with split/merge/tombstone lineage rather than positional arrays;
- model output as proposals only, with explicit confirmation before canonical writes; native
  Brain Dump confirmation creates title-only Inbox tasks and infers no metadata;
- user-edit field locks, immutable source lineage, owner-scoped snapshot target resolution,
  visible conflicts, expected revisions, and deterministic action idempotency keys;
- persisted work leases, bounded retry/recovery, and restart reconciliation rather than
  correctness depending on process memory;
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
Accurate STT and text reconciliation remain bounded roles over immutable sealed input.

### Browser Web Speech as the transcript source

Rejected as authoritative. A single browser locale is not reliable for RU/EN code-switching,
browser hypotheses do not constitute durable original audio, and later text processing
cannot recover words the browser never captured. It may remain a clearly labelled preview
fallback while MediaRecorder audio is uploaded independently.

### Encode one concrete AI vendor in operation records

Rejected. Fast and accurate modes may initially share a vendor, but persisted contracts are
role- and schema-based. Vendor enums in domain state would make replacement and deterministic
fakes a migration rather than adapter wiring.

### Separate Weekly Review voice workflow

Rejected. Its lifecycle and failure semantics are the same as voice capture. Review owns
outcomes; it does not need a second operation engine.

### Broker and dedicated workers immediately

Rejected for MVP. Persisted operations plus an in-process/background runner are sufficient.
Extract transcription only when ADR-0001's measured scaling/failure criteria are met.

## Verification

The [acceptance scenarios](../../specs/002-async-voice-workflows/acceptance-tests.md) are
normative for implementation.

Outcome-to-contract mapping:

| Required outcome | Architecture mechanism | Normative scenarios |
|---|---|---|
| Mixed RU/EN speech preserves `BrainBuddy` and `production smoke` and yields three tasks | multilingual hints, accurate original-audio generation, semantic text reconciliation | ML-01, ML-05 |
| Fast `brain body` is corrected from original audio | accurate port receives sealed `media_ref`; cross-lane segment supersession | ML-02, PV-02 |
| Unpunctuated run-on becomes several tasks | semantic boundary patches and stable split lineage, not regex position | ML-03, PA-07 |
| `купить хлеб и молоко` remains one task | conjunction is evidence inside semantic context, never a split rule | ML-04 |
| User edits/deletes survive accurate reconciliation | field locks, tombstones, visible conflicts, conflict-gated freeze | PA-03, PA-14, ML-06 |
| Stop visibly reconciles before Review | `sealing -> accurate_transcribing -> reconciling -> awaiting_confirmation` | OP-02, UI-01 |
| Save creates native Inbox tasks once and no metadata | frozen title-only actions plus deterministic child idempotency keys | CO-03, CO-11 |
| Restart/failure is bounded and resumable | persisted provider runs, leases, checkpoints, retry budget, polling projection | OP-09, RC-01, RC-02 |
| Existing data remains safe | schema-v2 import rules; terminal v1 is read-only; active v1 is visibly provisional-only | MG-01, MG-02 |

No product code is introduced by this ADR.

## Related files

- `docs/decisions/0001-vnext-modular-monolith-and-workflow-contracts.md`
- `specs/002-async-voice-workflows/spec.md`
- `specs/002-async-voice-workflows/acceptance-tests.md`
- `AGENTS.md`
