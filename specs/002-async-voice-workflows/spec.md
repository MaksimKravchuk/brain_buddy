# Feature specification: asynchronous voice workflows

Status: Materially amended 2026-07-19 for friend-demo-ready real product.
Architecture: [ADR-0002](../../docs/decisions/0002-async-voice-operation-substrate.md)
Acceptance tests: [acceptance-tests.md](acceptance-tests.md)

## Goal

Let a user speak a brain dump or conduct a Weekly Review without blocking on one
request. Persist the original audio, show fast provisional understanding while
speech continues, retranscribe sealed audio with an accurate multilingual lane,
reconcile versioned text and proposal lineage, and persist only an explicitly
confirmed, idempotent batch with full provenance.

The 2026-07-19 amendment promotes the feature from a deterministic-fake
contract shell to a real, friend-demo-ready BrainBuddy capability: production
must not instantiate deterministic STT silently, binary audio must never be
decoded as UTF-8 text, real Russian and RU/EN recordings must produce
inspectable faithful transcripts, and a real structured semantic reconciler
must replace regex/hardcoded fixture logic in the production decision path.

## User stories

### US1 — See useful provisional tasks while speaking (P1)

As a user giving a long natural brain dump, I see a growing numbered list of
provisional tasks without pausing between thoughts. A mixed Russian/English
sentence preserves product and technical terms. Independent acceptance: the
ML-01 fixture shows three provisional tasks while recording and no native task
exists yet.

### US2 — Review accurate corrections without losing my edits (P1)

As a user who stops recording, I see explicit processing before Review while
the original audio is retranscribed accurately and task boundaries are
reconciled. Corrections can update, split, merge, remove, or supersede
proposals with visible lineage. If I edited or deleted a proposal while
speaking, the model cannot silently reverse me. Independent acceptance: ML-02
corrects `brain body` to `BrainBuddy` from audio, ML-03 splits a run-on, ML-04
keeps one conjunction task, and ML-06 exposes rather than applies a lock
conflict.

### US3 — Resume safely and save exactly once (P1)

As a user, I can leave/reopen, retry a bounded failure, inspect whether output
is accurate or provisional-only, and explicitly Save the active Review list.
Independent acceptance: polling alone restores the operation, and repeated Save
creates exactly one title-only native Inbox task per selected proposal with no
inferred metadata.

### US4 — Speak naturally on a real phone and get a faithful transcript (P1)

As a user on a real mobile browser, I speak a natural Russian or mixed
RU/EN brain dump. Stop yields a faithful transcript preserving critical names
and keyterms (`BrainBuddy`, `production smoke`, `Наташа`, recurring project and
person names). Browser recognition remains a labelled provisional preview; it
is never authoritative or required for final success. Independent acceptance:
real-audio corpus cases preserve every critical keyterm.

### US5 — Control consent, cost, and provider behavior (P1)

As a user, I explicitly consent to external processing per provider category. I
can disable external processing and see a clearly labelled fallback or disabled
state rather than a silent upload. The chosen provider, model, language hints,
and vocabulary/keyterm prompts are configuration-backed; a provider change does
not alter operation, transcript, proposal, or confirmation contracts.

## Required user outcomes

1. The user can start, stop, cancel, leave, resume, retry, and understand
   current progress.
2. Stable partial transcript and numbered provisional captures appear while
   recording continues; fast, accurate, and text-reconciler roles remain
   replaceable.
3. The user can edit/reorder provisional work without a later model
   overwriting it.
4. The reconciler can propose merge, split, edit, target, route, review, or
   CRT actions with source cues, confidence, and before/after diffs.
5. Ambiguous or stale targets require resolution; title similarity never
   silently edits an existing item.
6. No canonical capture, existing-item edit, review outcome, route, or
   promotion is written before confirmation.
7. Duplicate delivery, retry, reconnect, and timeout-after-accept create no
   duplicate write.
8. Undo communicates and enforces its bounded scope; it never claims to
   reverse an already completed external side effect.
9. Voice-led Weekly Review uses the same operation/events/patch/confirmation
   substrate and remains resumable when its voice operation fails or is
   cancelled.
10. The user controls microphone permission, external processing consent,
    raw-audio deletion, and can inspect retention/provenance without sensitive
    text entering logs.
11. Mixed RU/EN speech preserves product/technical terms, accurate STT can
    correct fast words from original audio, and semantic task boundaries do
    not split on conjunctions alone.
12. Native Brain Dump confirmation creates only title-only Inbox tasks, exactly
    once, with no inferred tags, project, priority, details, or dates.
13. Production STT consumes sealed original audio bytes as audio; binary audio
    is never decoded as UTF-8 text. Deterministic fakes are CI-only and must
    not be the production default.
14. Real Russian and RU/EN recordings produce inspectable faithful transcripts
    that preserve every critical keyterm on the approved founder corpus.
15. The production task reconciler is a structured semantic text-model process
    emitting schema-valid operations; regex/hardcoded fixture logic is removed
    from the production decision path.
16. External-processing consent gates every real provider call; language hints
    and vocabulary/keyterm prompts propagate from operation consent to every
    STT and reconciler invocation.
17. Provider configuration, timeout/retry/cost limits, and disabled/fallback
    behavior are explicit and observable; no raw audio or transcript enters
    ordinary logs.

## Scope

In scope: operation state/projection; original-audio chunk upload; replaceable
fast/accurate STT and text-reconciler ports; versioned time-aligned transcript
supersession; ordered events with polling fallback; stable proposal IDs and
lineage patches; user field locks/conflicts; snapshot-scoped target
resolution; confirmation batches; idempotent commit; persisted bounded
recovery; migration; privacy/retention; Weekly Review substrate compatibility;
real configurable accurate-STT adapter over sealed original audio (initial
provider candidates: OpenAI `gpt-4o-mini-transcribe`/`gpt-4o-transcribe`, plus
at least one credible alternative such as ElevenLabs Scribe v2 or Deepgram
Nova-3 benchmarked before locking); explicit RU/RU+EN language handling and
vocabulary/keyterm prompting; browser recognition as labelled provisional
preview only; real structured semantic task reconciler; explicit
external-processing consent; provider configuration, timeout/retry/cost limits,
disabled/fallback behavior; real-audio evaluation harness separating STT
quality from task-extraction quality; credentialed full-stack E2E using genuine
spoken audio.

Out of scope: live product implementation in this spec artifact set (implementation
is handed to specialist Kanban cards); external tracker task editing; automatic
approval/routing/deletion/promotion; a broker; a separate Weekly Review voice
engine; arbitrary tool execution; automatic compensation of completed external
writes; unrelated GTD redesign; visual redesign; broad platform framework;
self-hosted GPU infrastructure; diarization; general voice-agent functionality
unless measured corpus evidence proves necessity for this single loop;
deterministic fakes as speech-quality or product E2E evidence.

## Functional requirements

- **FR-001** The operation MUST persist the original recording as chunked,
  owner-scoped working media before accurate reconciliation can start.
- **FR-002** Fast STT, accurate STT, and text reconciliation MUST be replaceable
  logical roles; ordinary tests MUST use deterministic fakes. Production MUST
  NOT instantiate deterministic STT silently.
- **FR-003** Transcript history MUST be ordered, time-aligned, append-only,
  versioned, and explicitly superseded; no mutable text blob may be
  authoritative.
- **FR-004** Proposals MUST have stable IDs and append-only
  add/update/split/merge/remove/supersede/reorder patches with source spans
  and auditable hidden predecessors.
- **FR-005** User changes MUST lock only changed fields. A conflicting model
  suggestion MUST remain visible and unresolved until an explicit user
  decision.
- **FR-006** Stop MUST run seal, accurate transcription from original audio,
  and text reconciliation before successful Review; fallback quality MUST be
  visible.
- **FR-007** Operation state, progress, retries, leases/checkpoints, and
  results MUST survive UI closure and process restart, with polling sufficient
  for correctness.
- **FR-008** Every operation/artifact lookup MUST be owner-isolated;
  telemetry/events MUST be redacted; processing and retention MUST honor
  consent.
- **FR-009** Only explicit confirmation of a frozen conflict-free revision may
  create native Inbox tasks. Confirmation MUST be exactly-once and MUST infer
  no metadata.
- **FR-010** Schema-v1 terminal operations MUST remain read-only; active
  operations without source audio MUST be visibly provisional-only and MUST
  NOT claim accurate correction.
- **FR-011** The production accurate-STT adapter MUST consume sealed original
  audio bytes as audio; binary audio MUST NEVER be decoded as UTF-8 text in
  the production decision path.
- **FR-012** External-processing consent MUST gate every real provider call.
  Without current consent naming the configured provider category, no audio
  may leave the device; a configured local model or explicit disabled state
  is used instead—never a silent upload.
- **FR-013** Language hints (`ru`, `ru+en`) and vocabulary/keyterm prompts
  (recurring project, person, and product names) MUST propagate from
  operation consent to every fast-STT, accurate-STT, and reconciler
  invocation. Browser preview locale MUST be corrected to reflect declared
  languages rather than `navigator.language` alone.
- **FR-014** Provider configuration, timeout/retry/cost limits, and
  disabled/fallback behavior MUST be explicit, configuration-backed, and
  observable. Provider absence is an explicit disabled/fallback state, never
  a silent degradation to deterministic fakes.
- **FR-015** Raw audio, transcripts, task text, vocabulary, paths, content
  hashes usable as fingerprints, emails, and credentials MUST NOT enter logs,
  metrics, analytics, operation events, committed fixtures, or PR evidence.
- **FR-016** The production task reconciler MUST be a structured semantic
  text-model process emitting schema-valid add/update/split/merge/remove/
  supersede/reorder operations. Regex/hardcoded fixture extraction MUST be
  removed from the production decision path; deterministic fixtures remain
  valid only for ordinary state-machine CI, never as speech-quality or
  product E2E evidence.
- **FR-017** Transcript provenance MUST link every proposal and committed
  action to source transcript segment IDs; native Inbox tasks MUST link the
  operation action receipt and proposal ID through their source reference.
- **FR-018** A real-audio evaluation harness MUST report STT quality
  (CER/WER, critical-term recall, omission/hallucination counts) separately
  from task-extraction quality (task-count accuracy, boundary
  precision/recall, title cleanliness, conjunction false-split rate,
  semantic preservation) by provider/model version, without injecting
  expected transcripts or tone fixtures into the production decision path.

## Edge cases and failure behavior

- Missing chunks block seal with exact resumable gaps; duplicate
  chunks/results are idempotent and conflicting chunk hashes fail visibly.
- Fast failure does not stop recording; accurate failure preserves audio and
  proposals for bounded retry; reconciler failure preserves accurate text and
  user work.
- A user edit racing model output either rebases disjoint changes or creates a
  conflict—no last-write-wins overwrite.
- A process dying under a lease resumes after lease expiry without duplicate
  versions, patches, or tasks; exhausted recovery cannot hot-loop.
- Consent withdrawal stops future upload/provider calls and schedules
  uncommitted working artifacts for deletion.
- Provider timeout after durable accept is resolved by
  `(operation_id, role, method, input_hash)` lookup, never by appending a
  duplicate generation or patch.
- Provider cost limit or rate limit surfaces as a labelled retryable or
  disabled state; it never silently falls back to deterministic fakes.
- Missing credentials or missing consent surfaces as an explicit disabled
  state with redacted error code, never a silent degradation.

## Privacy and observability impact

External processing remains opt-in by provider category. Logs, metrics,
analytics, and operation events contain only pseudonymous IDs, stage names,
timings, counts, coarse confidence bands, and error codes—not audio,
transcripts, task text, vocabulary, paths, hashes usable as content
fingerprints, emails, or credentials. UI progress names real stages and uses
indeterminate progress when totals are unknown. Provider/model version,
attempt count, and cost budget consumption are observable as redacted
metadata.

## Success criteria

- **SC-001** ML-01 through ML-06 pass against a versioned labelled corpus,
  including exact three-task and one-task founder examples.
- **SC-002** Evaluation reports task-boundary precision/recall, exact-count
  accuracy, title cleanliness, code-switched-term accuracy, and conjunction
  false-split rate by language and provider/model version, separated from STT
  CER/WER and critical-term recall.
- **SC-003** Automated tests show zero silent user-edit loss, zero canonical
  writes before confirmation, zero inferred task metadata, and zero duplicate
  tasks after retries.
- **SC-004** The browser journey records, shows provisional tasks, processes
  accurate audio, reconciles, resolves edits/deletions/conflicts, saves, and
  shows persisted Inbox tasks after reload/relogin without a paid-provider
  dependency in CI.
- **SC-005** p95 stage telemetry meets the budgets in ADR-0002 or visibly
  reports a labelled fallback without weakening safety invariants.
- **SC-006** Production cannot instantiate deterministic STT silently; binary
  audio is never decoded as UTF-8 text in the production path.
- **SC-007** Real Russian and RU/EN recordings from the approved founder
  corpus produce inspectable faithful transcripts; every critical keyterm is
  preserved.
- **SC-008** The production task reconciler emits only schema-valid operations;
  regex/hardcoded fixture logic is absent from the production decision path.
- **SC-009** Release target on the approved founder corpus: 100%
  critical-term preservation, zero invented tasks, at least 95% exact
  task-count accuracy, at least 95% task-boundary precision/recall, and all
  safety/idempotency invariants passing. A measured CER/WER threshold is
  established from the first baseline rather than invented before corpus
  evidence.

## Release gate

Implementation is releasable only when every safety/idempotency/privacy
scenario in the [acceptance test specification](acceptance-tests.md) passes,
latency telemetry is produced for all stated SLOs, the configured confidence
thresholds are backed by a versioned labelled evaluation report, the real-audio
evaluation harness separates STT from extraction quality, and the credentialed
full-stack E2E uses genuine spoken audio rather than text bytes disguised as
WebM or a mocked provider response.
