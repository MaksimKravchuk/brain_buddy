# ADR-0001: Build BrainBuddy vNext as a workflow-oriented modular monolith

Date: 2026-07-11
Status: Proposed
Decision owner: BrainBuddy
Related: `backend/app/container.py`, `backend/app/schemas/domain.py`, `docs/auth.md`,
ADR-0002, Kanban task `t_be41d6d7`

## Context

BrainBuddy already has a deployed FastAPI/React application, invite-gated accounts,
owner-scoped file persistence, a CRT canvas, AI-provider adapters, and automated tests.
The vNext MVP changes the primary product loop to:

> voice brain dump -> transcription -> atomic captures -> clarify/approve -> route
> to one task tracker or a BrainBuddy problem candidate -> smart Weekly Review ->
> optionally promote complex/repeating problems into CRT -> return evidence/results.

The product is being dogfooded by one primary user. The important unknown is whether the
capture/review loop creates value, not whether each noun can be deployed independently.
We therefore need boundaries that make the workflow safe to change without paying the
operational and consistency cost of microservices.

MVP non-goals are a proprietary task manager, calendar/reminder/recurrence engine,
plugin marketplace, general autonomous browser/email agent, multiple task-manager
connectors, and premature microservices. Bounded autonomous execution is explicitly
deferred until capture and review are trusted.

## Decision

Continue in this repository as one deployable modular monolith. Add six bounded modules
behind application-level ports: Capture, Organize, Review, Thinking/CRT, Execution, and
Identity. Each module owns its domain records and transitions. HTTP handlers and a thin
application workflow layer may coordinate modules; modules must not reach into another
module's repository or mutate another module's records.

Use the existing FastAPI process, Pydantic contracts, dependency container, React client,
session authentication, and filesystem repositories for the MVP. Keep external provider
and task-tracker details behind adapters. Domain events are versioned in-process
contracts and audit facts, not a reason to add a broker.

This record is the vNext contract. Existing `requirements/` documents remain historical;
where they conflict with live authentication or this workflow, `docs/auth.md`, live
schemas, and this ADR take precedence.

## Module boundaries

| Module | Owns | Public commands/queries | Must not own |
|---|---|---|---|
| **Identity** | `User`, `Session`, invite and owner resolution | authenticate; resolve current actor; assert owner | capture content, connector behavior, review policy |
| **Capture** | raw-input metadata, media reference, transcription attempts/results, immutable atomic-capture source and provenance | submit input; transcribe/retry; split; get session/source captures | approval, mutable user text, destination choice, task creation, CRT mutation |
| **Organize** | mutable capture item, clarification/approval decisions, text revisions, destination intent, route record | edit; clarify; approve; defer; delete; request route | source transcript/provenance, connector credentials/API calls, review sessions, CRT graph |
| **Review** | weekly review session, immutable per-item outcomes, completion summary | start/resume review; decide item; complete review | canonical capture text, task-tracker state, CRT graph |
| **Thinking/CRT** | problem candidates, promotion records, existing trees/nodes/relations, source links | assess candidate; promote/dismiss; query source/results | transcription, external dispatch, general task management |
| **Execution** | one configured task-tracker adapter, dispatch attempts, evidence/results returned by manual or adapter input | dispatch/retry; record result; query result links | deciding what to execute, arbitrary tools, autonomous agents |

Cross-module dependency rules:

1. Identity is a shared policy dependency and imports no feature module.
2. Capture publishes immutable source facts. Organize creates one mutable `CaptureItem`
   for each `AtomicCaptureSource` ID but never edits the source artifact.
3. Review reads projections and submits Organize or Thinking commands. It records the
   resulting IDs in its outcome; it does not duplicate their state machines.
4. Organize requests dispatch through the `TaskTrackerPort` or candidate creation through
   the `ThinkingPort`; it never imports concrete repositories/adapters.
5. Thinking may attach `EvidenceResult` IDs but Execution owns their content and status.
6. All cross-module writes run through an application service. A repository is private to
   its owning module.
7. The first implementation may keep ports as Python protocols and invoke them
   synchronously. Network clients are only concrete adapters in Execution or Capture.

Migration is incremental. Implement Capture and Organize first under
`backend/app/modules/`, because they establish immutable provenance and the item lifecycle
used by every later workflow. Add Execution and Review next, then move Thinking/CRT only
when its existing services can be wrapped without duplicating the graph model. During the
migration, `container.py` may wire new module ports to adapters around the current flat
services/repositories. New modules may call those adapters; flat code must not import new
module repositories, and each migrated record gains exactly one canonical owner. Identity
remains in its current package initially and is exposed to modules through its policy port.

Suggested backend shape (names are contracts, not a mandatory all-at-once refactor):

```text
backend/app/modules/
  identity/{domain,service,repository}.py
  capture/{domain,service,repository,transcription.py}
  organize/{domain,service,repository}.py
  review/{domain,service,repository}.py
  thinking/{domain,service,repository,crt_adapter.py}
  execution/{domain,service,repository,task_tracker.py}
backend/app/workflows/capture_review.py
```

The current tree services may remain where they are initially; `ThinkingCrtPort` wraps
them until a deliberate move. Do not duplicate the CRT model.

## Canonical data contracts

All records use opaque string IDs, UTC `created_at`/`updated_at`, `schema_version`,
`owner_id`, and integer `revision` for optimistic concurrency. References are IDs, never
embedded copies of another module's mutable record. User-authored text is preserved;
normalization or AI output is stored separately with provider/model provenance.

### CaptureSession

```text
id, owner_id
input_kind: voice | text
status: received | transcribing | transcribed | splitting | ready | failed | cancelled
media_ref?: opaque local/object reference
media: {mime_type, byte_size, duration_ms?, sha256?}
consent: {external_processing_allowed, recorded_at, provider?}
transcript?: {text, language?, confidence?, provider, model?, completed_at}
attempt_count, last_error?: {code, retryable, stage}
atomic_capture_ids[]
created_at, updated_at, schema_version, revision
```

`media_ref` is Capture-private and never returned as a filesystem path. Raw media
retention is configurable; deleting it must not break transcript/capture provenance.
Do not log audio, transcript text, hashes usable as content fingerprints, or local paths.

A successful but empty transcript is `failed` with `last_error.code=EMPTY_TRANSCRIPT`.
Low confidence is not a technical failure: continue to `ready`, mark generated captures
`needs_clarification`, and expose the confidence to the user.

### AtomicCaptureSource and CaptureItem

```text
AtomicCaptureSource (Capture-owned, immutable after creation):
  id, owner_id, capture_session_id, ordinal
  kind: task | note | question | problem_candidate
  source_span?: {start_char, end_char}
  source_text
  classification: {confidence?, model?, reasons[]}
  created_at, schema_version

CaptureItem (Organize-owned, one-to-one with source):
  id (= AtomicCaptureSource.id), owner_id, source_capture_id
  current_text
  review_state: proposed | needs_clarification | approved | deferred | completed | deleted
  clarification?: {question, answer?, resolved_at?}
  destination_intent: none | external_task_tracker | brainbuddy_problem
  route_id?: RouteRecord.id
  crt_candidate_id?: ProblemCandidate.id
  created_at, updated_at, schema_version, revision
```

The shared ID makes API and UI projections simple without sharing repository ownership.
`source_text` is immutable provenance. Edits replace `CaptureItem.current_text`, increment
its `revision`, and append an audit decision; they never rewrite source or transcript.
The one-to-one shared-primary-key mapping is an MVP constraint, not a general claim that a
source can never yield multiple actionable items. Breaking it requires a versioned data
migration that gives `CaptureItem` independent IDs, preserves `source_capture_id` as a
many-to-one foreign reference, updates APIs/events/UI keys to distinguish source and item
IDs, and backfills existing references before accepting one-to-many splits.

`completed` and `deleted` are terminal product states. `completed` preserves successful
work and provenance while removing it from the open review set; `deleted` lets Weekly
Review count avoided/deleted low-value work. Content in either state may be hard-deleted
later by a separate privacy operation.

### OrganizeDecision and RouteRecord

```text
OrganizeDecision:
  id, owner_id, atomic_capture_id, actor_id
  action: edit | clarify | approve | defer | complete | delete | route
  from_state, to_state, reason?, avoidance_reason?, patch?
  created_at, correlation_id, idempotency_key

RouteRecord:
  id, owner_id, atomic_capture_id
  destination: external_task_tracker | brainbuddy_problem
  status: pending | dispatching | succeeded | failed | cancelled
  external_ref?: opaque adapter ID
  candidate_id?: ProblemCandidate.id
  attempt_count, last_error?: {code, retryable}
  requested_at, completed_at?, revision
```

Only one successful route is allowed per capture in the MVP. A repeated request with the
same idempotency key returns the original record. Changing destination after success is a
future explicit “reroute” operation, not an update.

### WeeklyReview and WeeklyReviewOutcome

```text
WeeklyReview:
  id, owner_id, period_start, period_end
  status: open | completed | abandoned
  item_ids[]
  started_at, completed_at?, revision

WeeklyReviewOutcome:
  id, owner_id, weekly_review_id, atomic_capture_id
  action: keep | edit | delete | defer | route | promote_to_crt
  organize_decision_id?: OrganizeDecision.id
  route_id?: RouteRecord.id
  promotion_id?: CrtPromotion.id
  reason?, avoidance_reason?
  decided_at
```

Starting a review snapshots eligible item IDs, not their text. Eligible means an
owner's open captures in `proposed`, `needs_clarification`, `approved`, or `deferred`,
plus recent routing failures. `completed` and `deleted` captures are ineligible. As a
convergence guard for partial cross-module failure, an `approved` capture whose
`RouteRecord` is already `succeeded` is also ineligible even if the follow-up Organize
transition has not yet run; reconciliation must advance it to `completed`. Completing a
review requires one outcome per item or an explicit `defer` outcome. Completion is
idempotent and stores a summary with counts for accepted, deferred, completed,
deleted/avoided, routed, and promoted items.

Within a review, `keep` approves the item without a destination; `edit` updates text and
then approves it; `route` approves and then requests the selected destination; and
`promote_to_crt` approves, creates/uses a candidate, and requests promotion. If any
composed command fails, the outcome is not finalized and the visible underlying
pending/failed record remains retryable.

### ProblemCandidate and CrtPromotion

```text
ProblemCandidate:
  id, owner_id, source_capture_ids[]
  title, context
  signal: manual | repeated | complex
  signal_reasons[]
  status: open | promotion_requested | promoted | dismissed
  created_at, updated_at, revision

CrtPromotion:
  id, owner_id, problem_candidate_id
  status: pending | promoting | succeeded | failed
  tree_id?, root_node_id?
  source_capture_ids[]
  attempt_count, last_error?: {code, retryable}
  requested_at, completed_at?, revision
```

Repetition/complexity detection only proposes a candidate; promotion is user-confirmed.
Promotion creates or links a CRT tree and creates one initial problem/context node. The
live CRT schema treats `source_id` as cause and `target_id` as effect; stale historical
examples that describe the opposite direction must not be copied. Source provenance is
stored in the promotion record and in the node's existing `extra` metadata as IDs, not as
invented graph relations.

### DispatchAttempt and EvidenceResult

```text
DispatchAttempt:
  id, owner_id, route_id, adapter: configured_task_tracker
  status: started | succeeded | failed
  external_ref?, error_code?, retryable?, started_at, completed_at?

EvidenceResult:
  id, owner_id
  source: external_task_tracker | crt | manual
  kind: evidence | result
  status: recorded | superseded
  title, summary?, uri?
  atomic_capture_ids[]
  route_id?, weekly_review_id?, tree_id?, node_ids[]
  observed_at, recorded_at, actor_id
```

Evidence/result return means a result is visible from both its originating capture and
its review/CRT context through IDs. The MVP accepts manual recording and data returned by
the single task-tracker adapter. It does not poll arbitrary systems or run agents.

## State transitions and invariants

### Capture pipeline

```text
received -> transcribing -> transcribed -> splitting -> ready
received/transcribing/transcribed/splitting -> failed
failed --retry if retryable--> transcribing (or splitting for a split failure)
received/failed -> cancelled
```

- Every transition checks `owner_id`, expected `revision`, and allowed prior state.
- Retry appends an attempt; it does not overwrite prior provider/error metadata.
- Splitting creates at least one `AtomicCaptureSource` plus its one-to-one `CaptureItem`,
  or fails with `NO_ATOMIC_CAPTURES`.
- Session `ready` means both source and mutable items are persisted, not approved.

### Capture item decision lifecycle

```text
proposed -> needs_clarification -> proposed
proposed|needs_clarification -> approved | deferred | deleted
deferred -> proposed | approved | deleted
approved -> approved (edit only; revision increases)
approved -> completed (successful route or recorded result)
```

- Route requires `approved`; the route lifecycle is separate from `review_state`.
- `completed` is terminal and retains decision, route, result, and source history. The
  application workflow asks Organize to make this transition after a route reaches
  `succeeded` or after an `EvidenceResult` is recorded for an approved capture. The
  command is idempotent. A failed follow-up is reconciled from the canonical successful
  route/result; it must not make the item eligible for another review in the meantime.
- Delete requires an optional reason and supports a structured `avoidance_reason` for
  low-value work (`not_actionable`, `duplicate`, `obsolete`, `not_worth_cost`, `other`).
- Automatic classification may set `needs_clarification`; it may not approve, delete,
  route, or promote.

### Routing

```text
pending -> dispatching -> succeeded
pending|dispatching -> failed
failed --retry if retryable--> dispatching
pending|failed -> cancelled
```

The application persists `pending` before calling an adapter. A crash may leave a stale
`dispatching` record; retry/reconciliation must first query by idempotency key where the
adapter supports it. External IDs are opaque strings.

### CRT promotion

```text
open -> promotion_requested -> promoted
open -> dismissed
dismissed -> open
pending -> promoting -> succeeded | failed
failed --retry if retryable--> promoting
```

Candidate status becomes `promoted` only after the CRT tree/node and `CrtPromotion`
source links are persisted. Failed promotion leaves the candidate
`promotion_requested`, making retry visible.

### Evidence/result return

`EvidenceResult` is append-only except `recorded -> superseded`. At least one originating
`atomic_capture_id` is required. Every linked route, review, tree, and node must have the
same owner. The application service performs those cross-module checks through each
module's owner-scoped query port; it must not access another module's repository directly.
Removing a destination record must not erase returned evidence.

## Minimal HTTP API

All routes are under `/api`, require the existing session cookie, return the existing
error envelope, and include `X-Correlation-ID`. Mutating requests accept
`Idempotency-Key`; transition requests also accept `expected_revision` and return `409`
on stale state.

| Method and path | Purpose | Key response |
|---|---|---|
| `POST /capture-sessions` | multipart voice upload or JSON text submission | `202 CaptureSession` |
| `GET /capture-sessions/{id}` | poll session, transcript metadata, and captures | `200 CaptureSessionDetail` |
| `POST /capture-sessions/{id}/retry` | retry failed stage | `202 CaptureSession` |
| `POST /captures/{id}/decisions` | edit/clarify/approve/defer/delete | `200 CaptureItemDetail` + decision ID |
| `POST /captures/{id}/routes` | request one destination | `202 RouteRecord` |
| `GET /captures/{id}/results` | linked evidence/results | `200 EvidenceResult[]` |
| `POST /weekly-reviews` | start or resume review for period | `200 WeeklyReviewDetail` |
| `POST /weekly-reviews/{id}/items/{capture_id}/outcomes` | record item outcome and invoke relevant command | `200 WeeklyReviewOutcome` |
| `POST /weekly-reviews/{id}/complete` | validate coverage and complete | `200 WeeklyReviewSummary` |
| `POST /problem-candidates/{id}/promotions` | user-confirmed CRT promotion | `202 CrtPromotion` |
| `POST /results` | manually record linked evidence/result | `201 EvidenceResult` |

Do not add generic CRUD endpoints for every record. State-changing commands preserve
invariants and audit intent. `GET` list endpoints may be added for the capture inbox,
review history, and candidates when their UI needs them.

Voice upload limits (MIME allowlist, byte size, and duration) are configuration-backed
and rejected before provider invocation. ADR-0002 supersedes the synchronous interaction
allowance for voice: brain dumps and voice-led Weekly Review use the shared persisted
`AsyncOperation` substrate, even if its first runner remains in-process.

Each transcription attempt has a configuration-backed deadline, defaulting to 60 seconds.
The runner must enforce the deadline even if the provider client hangs. Expiry transitions
the `CaptureSession` from `transcribing` to `failed` with
`last_error={code: TRANSCRIPTION_TIMEOUT, retryable: true, stage: transcription}` and
closes the corresponding async-operation attempt as failed. Retry creates a new attempt;
it never silently extends or overwrites the timed-out one.

## Internal event contracts

Events are emitted after the owning record is persisted and carry no raw transcript,
audio, credentials, or full user text. Envelope:

```text
id, type, version=1, occurred_at, owner_id, actor_id
aggregate_type, aggregate_id, aggregate_revision
correlation_id, causation_id, payload
```

`correlation_id` is stable for the end-to-end workflow. For HTTP entry points, a client
may supply `X-Correlation-ID` only as a canonical UUID; the server returns `400` for a
malformed value, generates a UUID when absent, and echoes the accepted value in the
response. It is an untrusted observability label, never authorization or idempotency
input. Every accepted command receives a server-generated command ID. An event emitted
directly by that command sets `causation_id` to the command ID; an event emitted while
handling another event sets it to the triggering event ID. Retries keep the workflow's
correlation ID but receive a new command/event ID unless idempotency returns the original.

Event versions are per event type. Backward-compatible additions use optional fields and
retain the version; removing/renaming fields or changing their meaning requires a version
increment and a migration window in which affected consumers support both versions.
Consumers must explicitly reject unsupported versions, record the handler failure with
event ID/type/version, and reconcile from canonical state; they must not deserialize an
unknown version as the current schema or crash the originating HTTP request.

Initial events:

- `capture.transcription_succeeded` `{capture_session_id, confidence_band}`
- `capture.atomic_captures_created` `{capture_session_id, atomic_capture_ids}`
- `organize.capture_decided` `{atomic_capture_id, action, from_state, to_state}`
- `organize.route_requested` `{route_id, atomic_capture_id, destination}`
- `execution.route_succeeded|failed` `{route_id, external_ref?, error_code?}`
- `review.completed` `{weekly_review_id, counts}`
- `thinking.crt_promoted|promotion_failed` `{promotion_id, candidate_id, tree_id?}`
- `execution.result_recorded` `{result_id, atomic_capture_ids, source, kind}`

For MVP these are typed Python/Pydantic values dispatched in-process and appended to a
redacted audit stream. Handlers must be idempotent by event ID. A failed handler records
an error and can reconcile from canonical state; do not add Kafka, RabbitMQ, or a
separate event store.

## Authorization and privacy assumptions

- `get_current_user` establishes `actor_id` and `owner_id`. All reads, transitions,
  references, media, and list queries are owner-scoped. A wrong owner receives `404`,
  matching the existing tree policy.
- The MVP has one role: owner. No sharing, teams, delegated execution, or admin access to
  user content.
- Sessions remain opaque HTTP-only same-origin cookies. This ADR does not change the auth
  threat model in `docs/auth.md`.
- External transcription requires recorded user consent and a configured provider.
  Existing AI consent principles apply; consent is stored with the session.
- Raw-audio retention follows ADR-0002: the default is 24 hours after successful
  reconciliation; unreconciled working artifacts default to seven days after operation
  completion/cancellation. A retry-safe cleanup job enforces both configuration-backed
  periods, and users may request immediate audio deletion after processing. Transcript and
  atomic-source provenance remain after audio deletion.
- Task-tracker credentials are server-side references owned by the adapter and are never
  returned through APIs or events. The adapter uses one allowlisted integration, not an
  arbitrary URL/tool mechanism.
- Logs and analytics contain IDs, enums, sizes, confidence bands, durations, and error
  codes—not transcript/capture/evidence text, audio, emails, cookies, or credentials.

## Observability contract

Every workflow log/metric includes, where applicable:

```text
correlation_id, workflow_id (= capture_session_id or weekly_review_id)
causation_id, event_id, owner_id, actor_id
module, operation, aggregate_id, aggregate_revision
state_from, state_to, attempt, provider_or_adapter
outcome, error_code, retryable, duration_ms, occurred_at
```

`owner_id` and `actor_id` are acceptable in access-controlled application logs but must
be pseudonymized before export to third-party analytics. Required product counters:

- capture sessions started/ready/failed and stage latency;
- atomic captures proposed, approved, deferred, deleted, and clarification rate;
- atomic captures completed, including completion source (`route` or `result`);
- Weekly Reviews started/completed and completion duration;
- `avoidance_reason` counts for deleted low-value items;
- routes requested/succeeded/failed by the single destination;
- candidates proposed and CRT promotions succeeded/failed;
- evidence/results returned and linked to an originating capture.

Metrics count state-transition events, not HTTP retries. Idempotency keys and event IDs
prevent double counting.

## Persistence and consistency

Use owner-scoped JSON repositories under the configured data root and existing atomic
write helpers. A practical MVP layout is:

```text
captures/{owner_id}/{capture_session_id}.json
organize/{owner_id}/{atomic_capture_id}.json
reviews/{owner_id}/{weekly_review_id}.json
candidates/{owner_id}/{candidate_id}.json
promotions/{owner_id}/{promotion_id}.json
dispatches/{owner_id}/{route_id}.json
results/{owner_id}/{result_id}.json
audit/{owner_id}/{yyyy-mm}.jsonl
```

Indexes are derived acceleration data and can be rebuilt from canonical records. A
cross-module workflow is not a filesystem transaction: persist the initiating state,
invoke the next module idempotently, then persist the returned reference. Visible
`pending`/`failed` states plus reconciliation are preferred over pretending atomicity.
No code may mutate embedded records in another module to “repair” partial work.

Move these workflow records to SQLite before broad multi-user rollout if concurrent
writes, scans, or cross-record recovery become a recurring source of complexity. That is
a persistence change inside the monolith, not automatically a service extraction.

## Extraction criteria

A module becomes a separately deployable service only when measured evidence satisfies
at least one criterion and its contract/ownership is stable:

1. **Independent scaling/runtime:** transcription consumes enough CPU/GPU or spends long
   enough in provider calls to exhaust/block web workers, and a worker process cannot
   meet the need. Extract the transcription worker before the whole Capture module.
2. **Security/sandbox isolation:** future Execution runs untrusted code/tools or holds
   credentials whose blast radius requires a separate identity, network policy, or
   sandbox. This is the strongest likely reason to extract Execution.
3. **Failure isolation:** adapter/provider failure repeatedly degrades core capture/review
   availability despite timeouts, queues, and circuit breakers.
4. **Independent release/ownership:** a stable module has a separate team and release
   cadence that is materially blocked by the monolith.
5. **Data/latency boundary:** sustained load requires a distinct storage technology or
   regional placement and measurements show an in-process port is the bottleneck.

Before extraction, document baseline metrics, failure mode, expected improvement,
contract versioning, data migration/ownership, auth propagation, idempotency, and rollback.
A domain noun, table, or repository is never sufficient justification. Identity,
Organize, Review, and core Thinking should remain together unless real operational
pressure—not speculative reuse—demands otherwise.

## Rationale

- The primary loop spans multiple concepts and requires consistent provenance. Keeping it
  in one process makes failures and user-visible states easier to reason about while the
  workflow is changing.
- Explicit ownership and ports prevent a “big ball of mud” and preserve an extraction
  path without network calls, duplicated authorization, or distributed transactions now.
- The existing auth, CRT, provider, deployment, and test infrastructure are valuable and
  should be extended rather than rewritten.
- Separate review, route, and promotion records preserve product decision history while
  avoiding a proprietary task model.
- State machines, idempotency, and evidence links address reliability at the domain
  boundary; microservices would not remove those requirements.

## Alternatives considered

### Entity-per-service microservices

Rejected. `Transcript`, `Capture`, `Review`, `Task`, and `Tree` are domain records, not
independent deployment boundaries. This would add distributed authorization, event
ordering, retries, observability, and operational cost before product fit or scale.

### Continue adding behavior to generic tree services

Rejected. Voice input, approval, routing, and review have lifecycles that are not graph
CRUD. Embedding them in `TreeService` would couple every product action to the CRT data
model and make the simple capture path feel like graph editing.

### Greenfield rewrite

Rejected. Current lag/data-loss issues must be reproduced and stabilized separately;
they do not justify discarding working auth, canvas, deployment, and tests. vNext should
add a new product flow around reusable infrastructure.

### Adopt a full task-management domain

Rejected for MVP. BrainBuddy records capture decisions, review outcomes, route attempts,
and evidence links. Scheduling, recurrence, priorities, reminders, and task completion
semantics remain in the single external tracker.

### Broker-backed event-driven architecture now

Rejected. Typed events are useful module contracts and audit facts, but a broker would
introduce eventual consistency and operations without a measured throughput or isolation
need. Synchronous ports plus explicit pending/failed states are sufficient.

## Consequences

Positive consequences:

- The MVP can ship incrementally in the current repository and deployment.
- Source-to-result provenance and user decisions are explicit and testable.
- Provider and tracker choices remain adapters rather than domain enums spread across the
  codebase.
- Likely future extraction points are visible without pre-building distributed systems.

Tradeoffs and risks:

- File-backed cross-record workflows need idempotency and reconciliation.
- Module boundaries require discipline because Python does not enforce them by default.
- In-process transcription can still tie up web capacity; instrumentation must show when
  to add a worker.
- Soft-deleted content needs a later privacy-retention policy and hard-delete operation.

Future agents must preserve:

- One deployable modular monolith until explicit extraction criteria are evidenced.
- Repository ownership and port-only cross-module writes.
- Immutable source provenance, owner checks, expected revisions, and idempotent commands.
- Human approval before routing, deletion by automation, or CRT promotion.
- Terminal `completed` history and the exclusion of completed/successfully routed items
  from later Weekly Reviews.
- One configured task-tracker adapter and no autonomous Execution in the MVP.
- Evidence/result linkage back to at least one originating atomic capture.

## Verification and tests

Implementation is conformant when automated tests demonstrate:

1. every allowed and forbidden CaptureSession, CaptureItem, Route, Review, and Promotion state
   transition, including stale revisions and idempotent retries;
2. empty transcripts fail, low-confidence transcripts require clarification, and retries
   preserve prior attempts;
3. cross-owner IDs return `404` for reads and commands, including result links;
4. a capture cannot route before approval or route successfully twice;
5. successful routes and recorded results advance approved captures to `completed`;
   completed captures and approved captures with an already-succeeded route are excluded
   from future reviews, including when reconciliation is pending;
6. review completion requires an outcome for every snapshotted item and reports
   completion and delete/avoidance counts;
7. CRT promotion preserves source IDs, uses live relation semantics, and remains retryable
   after partial failure;
8. evidence/results are visible from originating capture and linked CRT/review context;
9. emitted events contain IDs/enums but no transcript, capture, evidence, or credential
   content;
10. correlation and causation IDs follow the command/event derivation rules, unsupported
    event versions fail explicitly, and product metrics do not double count retries;
11. transcription timeout reaches the retryable `failed` state and raw-audio cleanup
    honors the configured retention period;
12. no module imports another module's repository (enforce with an architecture/import
    test once module packages exist).

## Related files

- `backend/app/container.py`
- `backend/app/schemas/domain.py`
- `backend/app/api/dependencies.py`
- `backend/app/api/routes.py`
- `docs/auth.md`
- `requirements/backend_architecture.md` (historical)
- `requirements/api_contracts.md` (historical)
