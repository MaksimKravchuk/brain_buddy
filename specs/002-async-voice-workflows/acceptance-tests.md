# Async voice workflows: acceptance test specification

Status: Design contract
Decision: [ADR-0002](../../docs/decisions/0002-async-voice-operation-substrate.md)

Release scope: [ADR-0003](../../docs/decisions/0003-brain-dump-task-tracker-port.md)
and its acceptance suite supersede this file for the current Brain Dump specialization.
The broader Brain Dump and Weekly Review scenarios here remain future design and are not
release gates for the flat session-to-Inbox tranche.

These scenarios are implementation requirements. Unit tests should cover transition and
merge functions; repository tests should cover append/idempotency recovery; API tests
should cover owner scoping and command envelopes; frontend tests should use a fake ordered
event stream and fake timers. Provider tests use deterministic fakes, never live models.

## Fixtures

- owner A and owner B;
- a voice brain-dump operation with three numbered audio chunks;
- an open Weekly Review snapshot containing capture `c1@revision=4` and `c2@revision=2`;
- fast and reconciler fakes able to emit controlled segments/patches/errors;
- a task-tracker fake that records idempotency keys and can time out after accepting;
- a clock and event stream whose delivery can duplicate, delay, or omit events.

## State-machine tests

| ID | Scenario | Required assertion |
|---|---|---|
| OP-01 | create brain dump | operation starts in `recording`; no canonical capture exists |
| OP-02 | normal stop | seal drains fast stage, reconciles, freezes only on request, confirms, then completes |
| OP-03 | stop vs cancel | stop seals input; cancel reaches `cancelled` and commits nothing |
| OP-04 | close/reopen UI | server operation continues; refetched projection restores current phase and proposals |
| OP-05 | illegal transition | command returns domain error and leaves revision/state unchanged |
| OP-06 | cancel twice | same idempotency key returns same cancelled result |
| OP-07 | cancel during commit | unstarted actions stop; committed action IDs are reported, not rolled back |
| OP-08 | terminal provider error | operation is terminal, canonical records remain absent, deletion action is available |
| OP-09 | retryable error | retry resumes recorded checkpoint rather than creating a second operation |
| OP-10 | abandoned draft retention | expiry follows policy but never expires active/committing work |

## Upload and offline tests

| ID | Scenario | Required assertion |
|---|---|---|
| UP-01 | duplicate identical chunk | second PUT succeeds without duplicate bytes/manifest entry |
| UP-02 | conflicting chunk | same number with another hash returns `409 CHUNK_CONFLICT` |
| UP-03 | incomplete manifest | seal/reconciliation waits or fails retryably with exact missing chunk numbers |
| UP-04 | offline then reconnect | local recording continues, missing chunks upload in order, transcript has no duplicated span |
| UP-05 | upload timeout after accept | retry queries/repeats idempotently and stores one chunk |
| UP-06 | microphone loss | uploaded portion is offered for salvage; no fabricated complete transcript appears |
| UP-07 | local storage limit | warning/stop affordance appears before data loss; no fake server progress is shown |
| UP-08 | no external consent | external provider fake has zero calls; local fallback or explicit disabled state is used |

## Event stream and projection tests

| ID | Scenario | Required assertion |
|---|---|---|
| EV-01 | duplicate sequence | client applies event once |
| EV-02 | out-of-order sequence | client buffers bounded gap and reaches server projection order |
| EV-03 | unrecoverable gap | client refetches projection and resumes with `after_sequence` |
| EV-04 | SSE unavailable | polling produces equivalent visible operation state |
| EV-05 | concurrent subphases | recording remains primary while upload/transcript/candidate progress updates independently |
| EV-06 | unknown total | UI renders indeterminate stage, not a made-up percentage |
| EV-07 | redaction | events/logs contain no audio, transcript text, capture text, paths, email, or credential |

## Patch, ordering, and user-edit tests

| ID | Scenario | Required assertion |
|---|---|---|
| PA-01 | fast adds candidate | candidate is provisional and linked to source segment IDs |
| PA-02 | reconciler replaces fast wording | replacement preserves candidate/source lineage |
| PA-03 | user edits while speaking | later fast/reconciler patches do not overwrite edited fields; new speech still adds candidates |
| PA-04 | disjoint stale patch | patch rebases and both changes survive |
| PA-05 | conflicting stale patch | patch is rejected/rerun; no last-write-wins mutation occurs |
| PA-06 | merge | result sits at earliest predecessor position and tombstones predecessors with lineage |
| PA-07 | split | children occupy predecessor position in source-span order |
| PA-08 | user reorder then reconcile | pinned relative order remains unchanged |
| PA-09 | interim churn | candidate repaint is coalesced to at most once per 500 ms |
| PA-10 | edit frozen batch | old batch is superseded and cannot be confirmed |
| PA-11 | low confidence | proposal is marked/requires clarification and cannot infer route/delete/promotion |
| PA-12 | reconciler failure | stable fast candidates and user edits remain manually reviewable and marked unreconciled |
| PA-13 | fast failure | sealed audio uses batch transcription/reconciliation fallback |

## Target-resolution tests

| ID | Scenario | Required assertion |
|---|---|---|
| TR-01 | selected target | explicit owner-scoped ID wins over semantic alternatives |
| TR-02 | unique exact alias | target resolves within snapshot and carries expected target revision |
| TR-03 | semantic score below 0.85 | target remains unresolved |
| TR-04 | top-two margin below 0.10 | target remains unresolved and asks user to choose |
| TR-05 | user resolves ambiguity | user patch wins over later model rerun |
| TR-06 | target outside snapshot | rejected even if title is an excellent match |
| TR-07 | cross-owner target | returns `404` and leaks no existence/content |
| TR-08 | stale existing item | commit returns refreshed diff to confirmation; no mutation occurs |
| TR-09 | external tracker reference | no external mutation; produce unresolved/new capture according to confirmation |

## Confirmation, commit, and idempotency tests

| ID | Scenario | Required assertion |
|---|---|---|
| CO-01 | model output before confirmation | no Capture/Organize/Review/Execution canonical write occurs |
| CO-02 | confirm additions | immutable sources are created before mutable items and preserve segment provenance |
| CO-03 | repeated confirm, same body | same result/action IDs return; counts and writes remain one |
| CO-04 | repeated key, different body | returns `409 IDEMPOTENCY_CONFLICT` |
| CO-05 | timeout after external accept | retry finds one route/external task through child idempotency key |
| CO-06 | independent action failure | successful siblings remain; dependants skip; batch exposes per-action results |
| CO-07 | retry failed batch | only unresolved actions execute and final result contains no duplicates |
| CO-08 | route or promotion | local operation can complete while destination record remains visibly asynchronous |
| CO-09 | destructive action | always appears individually in confirmation regardless of confidence |
| CO-10 | event replay | state-transition metrics count once per event/command identity |

## Undo tests

| ID | Scenario | Required assertion |
|---|---|---|
| UN-01 | undo unconfirmed user patch | workspace projection reverts; domain repositories unchanged |
| UN-02 | undo new unrouted capture | capture item soft-deletes and audit records inverse action |
| UN-03 | undo existing edit at same revision | inverse patch applies and increments revision |
| UN-04 | undo existing edit after another edit | inverse is refused and a reviewed follow-up diff is required |
| UN-05 | undo open review outcome | append superseding outcome; do not erase history |
| UN-06 | undo pending route | cancellation occurs only if adapter work has not started |
| UN-07 | undo successful external route | UI says automatic undo unavailable and offers explicit follow-up; external task remains |

## Weekly Review substrate tests

| ID | Scenario | Required assertion |
|---|---|---|
| WR-01 | start voice review | creates `weekly_review_voice` AsyncOperation referencing the open review snapshot |
| WR-02 | spoken edit current card | shown item ID is a hint; proposal still carries ID/revision and requires confirmation |
| WR-03 | spoken thought unrelated to card | creates a new provisional capture in the same operation/batch |
| WR-04 | incremental keep/edit/delete/defer | patches use common ordering, confidence, and confirmation semantics |
| WR-05 | leave/resume | review and operation remain open and restore exact item/proposal position |
| WR-06 | cancel voice operation | Weekly Review stays open and resumable; no implicit outcomes are recorded |
| WR-07 | partial commit failure | successful decisions are visible; failed outcome remains retryable/idempotent |
| WR-08 | complete with uncovered item | rejected until each snapshotted item has an outcome or explicit defer |
| WR-09 | confirmed completion | one completion and one summary are stored despite repeated request |
| WR-10 | architecture | Weekly Review imports/uses shared operation substrate; no second voice state machine exists |

## Privacy, consent, and provenance tests

| ID | Scenario | Required assertion |
|---|---|---|
| PR-01 | microphone denied | operation does not record/upload and shows permission remediation |
| PR-02 | consent withdrawal mid-recording | future uploads/provider calls stop; uncommitted deletion is scheduled |
| PR-03 | immediate audio delete after reconcile | raw media becomes unavailable while transcript/source provenance remains valid |
| PR-04 | retention sweep | raw and working artifacts delete at configured boundaries, not before |
| PR-05 | provenance inspection | committed action traces to segments/source, model/template, user patches, and confirmer |
| PR-06 | analytics export | only pseudonymous IDs, timings, bands, counts, and error codes leave app logs |

## Latency and evaluation gates

Automated performance tests use deterministic delayed fakes and verify telemetry/budget
classification rather than relying on wall-clock model calls. A release candidate reports
p50/p95 by audio duration, language, device/network class, and model version.

- p95 local recording feedback `<100 ms`;
- stable partial transcript `<700 ms` after segment end;
- first provisional candidate `<1.5 s` after clause boundary;
- emitted-to-visible patch `<500 ms`;
- post-stop fast drain `<2 s` for streamed audio;
- reconciled batch `<8 s` for two minutes and `<20 s` at configured maximum;
- local commit acknowledgement `<1 s`.

Confidence thresholds cannot ship from intuition alone. An offline labelled corpus must
measure target-resolution precision, candidate split/merge quality, destructive-intent
false positives, and calibration by language/model. Required safety invariants are zero
automatic canonical writes and zero destructive/routing actions without confirmation;
latency degradation may trigger fallback but never relax those invariants.
