# Requirements Checklist: Real, friend-demo-ready Voice Brain Dump

**Purpose**: Verify that the materially amended async-voice specification is
complete, consistent with ADR-0002/constitution, and implementation-ready for
the real-product amendment.

**Amended**: 2026-07-21

**Feature**: `../spec.md`

## Product outcome and scope

- [x] CHK001 US1–US5 describe independently testable user value and all are
  P1 for the real friend-demo-ready Brain Dump loop.
- [x] CHK002 Required founder examples explicitly cover RU/EN code switching,
  original-audio correction, an unpunctuated run-on, and a one-task
  conjunction phrase.
- [x] CHK003 Progressive proposals, explicit processing, Review, and Save
  states are distinct.
- [x] CHK004 Weekly Review substrate compatibility is preserved without adding
  Weekly Review UX or a second engine.
- [x] CHK005 CRT, routing, external trackers, autonomous execution, inferred
  metadata, text-to-speech, brokers, microservices, diarization, and general
  voice-agent framework are explicit non-goals.
- [x] CHK036 The feature is promoted from deterministic-fake contract shell to
  real friend-demo-ready product; production must not instantiate
  deterministic STT silently.

## Contract completeness

- [x] CHK006 Fast STT, accurate STT, and text reconciliation are replaceable
  logical roles; one vendor may implement several roles without entering
  domain contracts.
- [x] CHK007 Accurate STT is required to process sealed original audio, not
  fast transcript text.
- [x] CHK008 Transcript versions define ordering, audio spans, generation/lane,
  append-only history, and explicit many-to-many supersession.
- [x] CHK009 Proposal patches define stable IDs,
  add/update/split/merge/remove/supersede/reorder semantics, source lineage,
  hidden tombstones, and structural successors.
- [x] CHK010 User changes define field-level locks, visible conflicts,
  explicit resolution, and conflict-gated freeze.
- [x] CHK011 State transitions include recording, pause, seal/drain, accurate
  transcription, reconciliation, Review, commit, error/retry, cancellation,
  and completion.
- [x] CHK012 API contracts define owner-scoped audio, projection, optional
  events, user patches/conflicts, freeze, confirm, and polling fallback.
- [x] CHK013 Confirmation defines deterministic child idempotency and
  title-only Inbox defaults with no canonical write before explicit Save.
- [x] CHK037 `language_hints` and `vocabulary` are defined on consent and
  propagate to every STT and reconciler invocation.
- [x] CHK038 Provider configuration is role- and schema-based, never a stored
  vendor enum; a provider change must not alter operation, transcript,
  proposal, or confirmation contracts.

## Persistence, migration, and failure behavior

- [x] CHK014 Provider runs, input hashes, leases, deadlines, retry limits,
  checkpoints, and operation recovery budgets are persisted and bounded.
- [x] CHK015 Process death, timeout-after-accept, duplicate output, and
  competing runner claims have deterministic recovery assertions.
- [x] CHK016 Chunk gaps, duplicate/conflicting chunks, offline windows,
  microphone loss, and local storage limits have visible outcomes.
- [x] CHK017 Schema-v1 terminal operations remain immutable; active v1 user
  edits/deletes and IDs import once and remain visibly provisional-only
  without fabricated audio accuracy.
- [x] CHK018 Compatibility aliases have a bounded migration window and
  additive responses.
- [x] CHK019 SQLite plus one in-process runner is justified as the minimum; no
  unnecessary infrastructure is prescribed.
- [x] CHK039 The production accurate-STT adapter consumes sealed audio bytes
  as audio; binary audio is never decoded as UTF-8 text in the production
  decision path.
- [x] CHK040 Provider cost limit or rate limit surfaces as a labelled
  retryable or disabled state; it never silently falls back to
  deterministic fakes.
- [x] CHK041 Missing credentials or missing consent surfaces as an explicit
  disabled state with redacted error code, never a silent degradation.

## Consent, privacy, owner isolation, and observability

- [x] CHK020 Microphone permission and external-processing consent are
  separate and current.
- [x] CHK021 Every operation and nested reference is owner-scoped with
  wrong-owner `404`.
- [x] CHK022 Logs/events/analytics exclude audio, transcript/task text,
  vocabulary, paths, emails, credentials, and content fingerprints.
- [x] CHK023 Retention, consent withdrawal, immediate audio deletion, and
  cleanup are configuration-backed and retry-safe.
- [x] CHK024 UI/telemetry expose real stages, retries, fallback quality, and
  indeterminate work without fake percentages.
- [x] CHK042 External-processing consent gates every real provider call;
  without consent, no audio leaves the device.
- [x] CHK043 Provider/model/version, attempt count, and cost-budget
  consumption are observable as redacted metadata.
- [x] CHK044 Transcript provenance links every proposal and committed action
  to source transcript segment IDs; native Inbox tasks link the operation
  action receipt and proposal ID.

## Acceptance and measurable success

- [x] CHK025 Acceptance IDs are unique and cover state, upload, providers,
  multilingual semantics, events, patches, targets, confirmation, UI, undo,
  review, privacy, recovery, migration, latency, STT accuracy, extraction
  accuracy, and evaluation.
- [x] CHK026 ML-01 requires exactly three tasks and preserves
  `BrainBuddy`/`production smoke`.
- [x] CHK027 ML-02 proves correction from original audio and retained fast
  history.
- [x] CHK028 ML-03 and ML-04 distinguish semantic run-on splitting from naive
  conjunction splitting.
- [x] CHK029 Safety gates require zero silent edit loss, zero pre-confirm
  canonical writes, zero inferred task metadata, and zero retry duplicates.
- [x] CHK030 Evaluation metrics include task-boundary precision/recall,
  exact-count accuracy, title cleanliness, code-switched-term accuracy, and
  conjunction false-split rate.
- [x] CHK031 The browser journey proves reload/relogin persistence and uses
  deterministic fakes rather than paid live providers in ordinary CI.
- [x] CHK045 STT accuracy (CER/WER, critical-term recall,
  omission/hallucination counts) is measured separately from task-extraction
  accuracy (task-count accuracy, boundary precision/recall, title
  cleanliness, conjunction false-split rate, semantic preservation,
  calibration).
- [x] CHK046 A real-audio evaluation harness reports STT and extraction
  quality by language and provider/model version, without injecting expected
  transcripts or tone fixtures into the production decision path.
- [x] CHK047 Editable-draft release floors are explicit and evidence-backed:
  WER `<=20%`, CER `<=15%`, critical-term recall `>=90%`, exact task count
  `>=65%`, semantic preservation `>=45%`, and invented proposals `<=0.20` per
  case (`<=10` across 50), while safety/idempotency invariants remain absolute.
- [x] CHK048 The production task reconciler emits only schema-valid operations;
  regex/hardcoded fixture logic is absent from the production decision path.
- [x] CHK049 Deepgram Nova-3 multilingual is selected by corpus evidence, and
  any future STT provider/model change must pass the same gate before default.
- [x] CHK050 Credentialed full-stack E2E uses genuine spoken audio, not text
  bytes disguised as WebM or a mocked provider response.
- [x] CHK051 GPT-5.6 Luna with `product-operation-v1` and no `temperature` is
  the configurable semantic MVP ceiling; its measured pass and comparable
  usage-priced ceiling of $0.06909 per 50 cases (~$0.001382/case) are stated.
- [x] CHK052 Terra is neither the production default nor an automatic fallback;
  Sol and Fable tiers are unauthorized, and unavailable/recovery UX fails
  truthfully rather than escalating model tier.
- [x] CHK053 Requirements distinguish aggregate editable-draft quality floors
  from zero-tolerance confirmation, provenance, privacy, owner-isolation,
  exactly-once, no-metadata-inference, and no-destructive-update invariants.
- [x] CHK054 A cheaper small/local model can replace Luna through configuration
  after the same corpus gate, without changing the operation architecture.
- [x] CHK055 Independent review, exact-head CI, normal PR/merge/Fly release,
  production smoke, and real physical-phone acceptance remain required.

## Planning and delivery readiness

- [x] CHK032 `plan.md` names real current files, proposed package boundaries,
  ownership, migration, tests, rollout, and constitution checks.
- [x] CHK033 `tasks.md` is grouped by user story and amendment phase, uses
  exact paths, and places failing tests before implementation.
- [x] CHK034 ADR-0001 modular-monolith boundaries and amended ADR-0002
  operation safety principles remain binding.
- [x] CHK035 Spec Kit artifacts remain planning input; Hermes Kanban,
  independent review, CI, PR, deploy, and smoke gates are not bypassed.

## Notes

All requirement checks are satisfied for independent architecture review. The
2026-07-21 amendment selects the cheapest measured passing MVP configuration
and lowers only recoverable editable-draft quality gates without altering the
ADR-0002 operation/patch/confirmation substrate, safety invariants, or native
GTD contracts. Any
implementation change to role boundaries, state transitions, persistence
ownership, confirmation payload, or migration behavior must amend the
spec/ADR/plan before code proceeds.
