# Async voice workflows: acceptance test specification

Status: Materially amended 2026-07-21 for assisted-draft quality floors and the
Luna cost ceiling.

Decision: [ADR-0002](../../docs/decisions/0002-async-voice-operation-substrate.md)

These scenarios are implementation requirements. Unit tests should cover
transition and merge functions; repository tests should cover
append/idempotency recovery; API tests should cover owner scoping and command
envelopes; frontend tests should use a fake ordered event stream and fake
timers. Provider tests use deterministic fakes for ordinary state-machine CI,
never live models. Real-audio corpus tests run in a credentialed track separate
from ordinary CI and never commit recordings or ground-truth transcripts to
the repo.

## Fixtures

- owner A and owner B;
- a schema-v2 voice brain-dump operation with three numbered, time-aligned
  audio chunks and an opaque sealed `media_ref`;
- an open Weekly Review snapshot containing capture `c1@revision=4` and
  `c2@revision=2`;
- browser-preview, fast-STT, accurate-STT, and text-reconciler fakes able to
  emit controlled segment versions, patches, delays, timeout-after-accept,
  and errors;
- a task-tracker fake that records idempotency keys and can time out after
  accepting;
- a native Task port fake that records complete Inbox task payloads and child
  idempotency keys;
- a clock, process lease owner, and event stream whose delivery can
  duplicate, delay, or omit events;
- a versioned founder corpus of genuine Russian and RU/EN spoken audio with
  ground-truth transcripts and expected task titles/boundaries, stored outside
  the repo and consumed only by the credentialed evaluation track.

## State-machine tests

| ID | Scenario | Required assertion |
|---|---|---|
| OP-01 | create brain dump | operation starts in `recording`; no canonical capture exists |
| OP-02 | normal stop | state advances through `sealing`, `fast_processing`, `accurate_transcribing`, `reconciling`, and `awaiting_confirmation`; freeze occurs only on request, then confirm completes |
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

## Provider-role and transcript-version tests

| ID | Scenario | Required assertion |
|---|---|---|
| PV-01 | replace provider adapter | swapping the configured fast, accurate, or text fake changes no domain/API schema and vendor names do not drive workflow branches |
| PV-02 | accurate input contract | accurate fake receives sealed original `media_ref`, audio metadata, RU/EN hints, and vocabulary; it is never invoked with fast text as its audio input |
| PV-03 | segment correction | accepted accurate versions carry audio spans and explicitly supersede overlapping fast IDs; old versions remain queryable in owner-scoped audit history |
| PV-04 | many-to-many supersession | one-to-many and many-to-one transcript corrections project in `(start_ms, end_ms, sequence)` order without mutating old text |
| PV-05 | invalid provider output | missing/negative spans, unknown segment/proposal IDs, oversized text, or unsupported schema is rejected before revision changes |
| PV-06 | duplicate provider result | the same role/method/input hash returns the stored run, segment IDs, patch IDs, and proposal-ID mapping exactly once |
| PV-07 | browser preview | fixed-locale browser text is labelled `browser_preview`, has a coarse capture-clock span, and never becomes authoritative when accurate output exists |
| PV-08 | no UTF-8 audio decoding | the production accurate-STT adapter never calls `bytes.decode("utf-8")` on audio input; binary audio is passed to the provider audio API |
| PV-09 | no deterministic default in production | production startup refuses `DeterministicAccurateStt` unless an explicit env escape hatch is set; missing credentials surface as `disabled` |
| PV-10 | browser locale from hints | `recognition.lang` is set from declared `language_hints`, not `navigator.language` alone |

## Multilingual semantic acceptance

Provider fakes use versioned labelled audio/text fixtures; ordinary CI never
calls a live or paid model. The founder examples remain release-blocking
deterministic contract cases. Live-provider quality is evaluated by aggregate
corpus floors rather than requiring every model call to match every fixture.
Real-audio corpus cases run in the credentialed track.

| ID | Scenario | Required assertion |
|---|---|---|
| ML-01 | `Надо починить BrainBuddy, потом сделать production smoke и написать Наташе` | accurate transcript preserves `BrainBuddy` and `production smoke`; active Review projection contains exactly three tasks for fixing BrainBuddy, doing production smoke, and writing Natasha |
| ML-02 | fast says `brain body`, audio says `BrainBuddy` | fast version remains in history; accurate version from original audio supersedes it; reconciled active title contains `BrainBuddy` and not `brain body` |
| ML-03 | long run-on without punctuation | semantic reconciliation emits the labelled number of distinct task intents with split lineage even though punctuation provides no boundaries |
| ML-04 | `купить хлеб и молоко` | active Review projection contains exactly one task; no patch splits solely on `и` or another conjunction |
| ML-05 | in-sentence RU→EN→RU code switch | code-switched-term accuracy and exact task count meet the versioned fixture expectations; per-segment language labels may contain both `ru` and `en` |
| ML-06 | edit then accurate correction | an edited title remains locked; a differing accurate suggestion becomes an open visible conflict and cannot be frozen until the user resolves it |

## STT accuracy tests (credentialed track, real audio)

These tests call the real accurate-STT adapter over genuine founder-corpus
audio and measure STT quality independently from downstream task extraction.
They run only when credentials and consent are present; otherwise they skip
with an explicit disabled-state report.

| ID | Scenario | Required assertion |
|---|---|---|
| SA-01 | Russian corpus STT | CER and WER are reported per case and aggregate; WER is `<=20%`, CER is `<=15%`, and critical-term recall is `>=90%` on the approved corpus |
| SA-02 | RU+EN code-switch STT | code-switched-term accuracy is reported and contributes to the aggregate critical-term recall floor; per-segment language labels reflect both languages |
| SA-03 | omission/hallucination counts | dropped-word and invented-word counts are reported per case and per provider/model version |
| SA-04 | STT latency | p95 transcription latency is reported by duration and language; a labelled fallback is allowed when the budget is missed, never a safety weakening |
| SA-05 | provider selection and change | Deepgram Nova-3 multilingual is the MVP default because it passes the floor; any provider/model change reruns the same STT gate before becoming default |

## Task extraction accuracy tests (credentialed track, real transcript)

These tests call the real text reconciler over the accurate transcript and
measure extraction quality independently from STT quality.

| ID | Scenario | Required assertion |
|---|---|---|
| EA-01 | exact task-count accuracy | at least 65% exact task-count accuracy on the approved corpus |
| EA-02 | boundary precision/recall | identity-aware and provenance-only task-boundary precision/recall are reported separately as diagnostics; this amendment defines no release threshold for either |
| EA-03 | title cleanliness | title cleanliness is reported as a diagnostic; regex artifacts and positional splits remain independently forbidden by deterministic contract tests |
| EA-04 | conjunction false-split rate | the aggregate false-split rate is reported as a diagnostic; deterministic ML-04 remains the contract gate against splitting on `и`/`and` alone |
| EA-05 | split/merge accuracy | aggregate split/merge accuracy is reported as a diagnostic; deterministic patch tests continue to require valid lineage and stable IDs |
| EA-06 | semantic preservation and inventions | semantic preservation is at least 45%; invented proposals are at most 0.20 per case and at most 10 across the fixed 50-case corpus; every draft remains editable and source-linked, while task-identity accuracy remains a reported diagnostic |
| EA-07 | confidence calibration | calibration error is reported against semantic/task identity correctness as a diagnostic; this amendment defines no release threshold |
| EA-08 | semantic usage-priced cost | the comparable 50-case Luna run costs at most $0.06909 total (approximately $0.001382 per case) under the same template and pricing basis; a higher-cost default requires an explicit decision |

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
| PA-06 | merge | result sits at earliest predecessor position and marks predecessors superseded with lineage |
| PA-07 | split | children occupy predecessor position in source-span order |
| PA-08 | user reorder then reconcile | pinned relative order remains unchanged |
| PA-09 | interim churn | candidate repaint is coalesced to at most once per 500 ms |
| PA-10 | edit frozen batch | old batch is superseded and cannot be confirmed |
| PA-11 | low confidence | proposal is marked/requires clarification and cannot infer route/delete/promotion |
| PA-12 | reconciler failure | stable fast candidates and user edits remain manually reviewable and marked unreconciled |
| PA-13 | fast failure | sealed audio uses batch transcription/reconciliation fallback |
| PA-14 | reconciler touches locked title | suggested change is stored as an open conflict; title is unchanged and freeze fails until explicit resolution |
| PA-15 | remove/supersede audit | tombstoned and structurally superseded proposals are hidden from active list but remain in owner-scoped history with predecessor/successor links |
| PA-16 | wording correction, same intent | `update` preserves proposal ID and revises wording/source spans; array position is not used to match the proposal |
| PA-17 | schema-valid operations only | the real reconciler emits only `add/update/split/merge/remove/supersede/reorder` patches; invalid operations are rejected before revision changes |
| PA-18 | no regex in production path | the production reconciler path contains no regex/hardcoded fixture extraction; deterministic `_extract_titles` is CI-only |
| PA-19 | assisted editable draft | the transcript and every active proposal are visible before confirmation; each proposal can be edited or deleted and retains source-segment provenance; no proposal auto-persists |
| PA-20 | uncertain terms | uncertain names or terms remain visibly editable and source-linked; the reconciler does not silently convert them into a date, priority, project, person, route, or destructive update |

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
| CO-11 | native Brain Dump save | each selected active proposal creates exactly one task with only title plus defaults `state=inbox`, null details/project/due date, empty tags, and `priority=none`; no write exists before confirm |
| CO-12 | no silent metadata or destructive action | confirmation can persist only the visible selected title-only additions; invented date, priority, project, person, route, existing-item update, or destructive action is rejected rather than silently applied |

## Brain Dump UI transition tests

| ID | Scenario | Required assertion |
|---|---|---|
| UI-01 | stop and process | Stop leaves recording and visibly renders `Finishing upload`, `Improving transcript`, then `Reconciling tasks`; editable Review appears only at `awaiting_confirmation` |
| UI-02 | progressive list | stable proposal IDs are React keys; numbered active proposals grow without repainting user-edited titles; hidden tombstones do not renumber identity |
| UI-03 | conflict review | Review shows mine/suggestion values and blocks Save until every open conflict is explicitly kept or accepted |
| UI-04 | leave/resume without events | polling restores exact stage, authoritative transcript quality, active proposals, locks, conflicts, and last sequence |
| UI-05 | provisional-only fallback | after bounded accurate/reconciler failure, manual Review is opt-in and visibly labelled unreconciled; it never looks like the successful accurate path |
| UI-06 | declared language on preview | the browser preview recognition locale follows declared `language_hints`, not `navigator.language` alone |
| UI-07 | transcript and proposal authority | Review displays the authoritative transcript beside every active proposal with edit/delete controls and an explicit confirmation action; no copy implies that a draft already persisted |

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
| PR-07 | language hints propagate | `language_hints` and `vocabulary` from consent reach every STT and reconciler invocation |
| PR-08 | cost limit reached | provider call is refused with a redacted retryable/disabled error code; no silent fallback to deterministic fakes and no automatic escalation to Terra, Sol, Fable, or another unauthorized tier |
| PR-09 | missing credentials | operation surfaces explicit `disabled` state; no silent deterministic default |

## Runner recovery and migration tests

| ID | Scenario | Required assertion |
|---|---|---|
| RC-01 | process dies with leased accurate run | after lease expiry, a new runner resumes from persisted sealed audio/input hash; one accurate generation is accepted and recovery count is bounded |
| RC-02 | retries exhausted | stage reaches `retryable_error`, then terminal state at operation recovery budget; no hot loop, duplicate patch, or canonical task is produced |
| RC-03 | provider timeout after durable accept | lookup by role/method/input hash returns prior output IDs and does not append another generation or proposal patch |
| RC-04 | two runner instances | compare-and-set lease permits one invocation per due run; loser observes persisted state and does no provider call |
| MG-01 | load completed/cancelled schema-v1 operation | operation remains readable and immutable; migration performs no provider call, replay, or native task write |
| MG-02 | load active schema-v1 operation | existing proposal IDs/user edits/deletions import once into patches/locks/tombstones, quality is `provisional_only`, and UI cannot claim accurate reconciliation |
| MG-03 | compatibility aliases | v1 `/transcript`, `/finish`, `/commit`, and proposal PATCH map to preview/seal/confirm/user-patch semantics with additive responses and preserve idempotency |

## Latency and evaluation gates

Automated performance tests use deterministic delayed fakes and verify
telemetry/budget classification rather than relying on wall-clock model calls.
A release candidate reports p50/p95 by audio duration, language,
device/network class, and model version.

- p95 local recording feedback `<100 ms`;
- stable partial transcript `<700 ms` after segment end;
- first provisional candidate `<1.5 s` after clause boundary;
- emitted-to-visible patch `<500 ms`;
- post-stop fast drain `<2 s` for streamed audio;
- reconciled batch `<8 s` for two minutes and `<20 s` at configured maximum;
- local commit acknowledgement `<1 s`.

Confidence thresholds cannot ship from intuition alone. A versioned offline
labelled text/audio corpus must cover Russian, English, useful Dutch fixtures,
in-sentence code switching, missing/wrong punctuation, product names,
low-confidence audio, retries, and edit-then-reconcile. The real-audio
evaluation harness reports STT quality (CER/WER, critical-term recall,
omission/hallucination counts) separately from task-extraction quality
(task-boundary precision/recall, exact task-count accuracy, title cleanliness,
code-switched-term accuracy, conjunction false-split rate, proposal
split/merge quality, and calibration by language/model). Required safety
invariants are zero silent user-edit loss, zero automatic canonical writes,
zero destructive/routing actions without confirmation, and zero duplicate
tasks after retries. Latency degradation may trigger a labelled fallback but
never relaxes those invariants.

The credentialed MVP gate additionally requires Deepgram Nova-3 multilingual
to meet WER `<=20%`, CER `<=15%`, and critical-term recall `>=90%`, and GPT-5.6
Luna with `product-operation-v1` and no `temperature` to meet exact task-count
accuracy `>=65%`, semantic preservation `>=45%`, and invented proposals
`<=0.20` per case (`<=10` across 50), with comparable semantic usage-priced
cost `<= $0.06909` total (approximately `$0.001382` per case). These are
editable-draft quality floors and a selection ceiling;
they never relax the absolute safety, confirmation, provenance, privacy,
owner-isolation, bounded-cost, or exactly-once assertions above.
