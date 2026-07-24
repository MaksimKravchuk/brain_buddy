# Implementation Plan: Real, friend-demo-ready Voice Brain Dump

**Branch**: historical `feat/voice-brain-dump-real-product` | **Amended**: 2026-07-24
**Spec**: `specs/002-async-voice-workflows/spec.md`
**Architecture**: [ADR-0002](../../docs/decisions/0002-async-voice-operation-substrate.md)

## Summary

Promote the Voice Brain Dump from a deterministic-fake contract shell to a
real, friend-demo-ready BrainBuddy capability. The user speaks naturally on a
real mobile browser in Russian or mixed RU/EN; the browser records and uploads
original audio; Stop runs a real accurate-STT adapter over sealed audio bytes;
a real structured semantic text reconciler emits schema-valid proposal
operations; the user reviews/edits/deletes/resolves conflicts; explicit
confirmation creates title-only native Inbox tasks exactly once; reload/relogin
shows exactly those durable tasks.

This plan amends the 2026-07-18 plan. The operation/patch/confirmation
substrate, ADR-0002 state machine, provider-port boundaries, and
deterministic CI contract are preserved. The amendment targets the five
verified root causes: browser locale, UTF-8 audio decoding, regex extraction,
synthetic-tone evaluation, and consent/hint propagation.

## Historical root-cause baseline and current disposition

The following five root causes were confirmed against `origin/main` `c0c12b0`
on 2026-07-19. They are retained as the causal record, not as claims about the
current implementation:

1. **Browser locale**: `frontend/src/features/brain-dump/BrainDumpRoute.tsx:139`
   sets `recognition.lang = navigator.language || "en-US"`. Russian speech on
   an English-locale browser runs under English recognition.
2. **UTF-8 audio decoding**: `backend/app/workflows/voice_brain_dump/providers.py:124-129`
   `DeterministicAccurateStt.transcribe_sealed_audio` decodes
   `request.sealed_audio.decode("utf-8", errors="ignore")` as text.
   `backend/app/modules/tasks/service.py:116` defaults
   `self.accurate_stt = accurate_stt or DeterministicAccurateStt()`, so
   production silently instantiates the fake.
3. **Regex extraction**: `providers.py:174-197` `_extract_titles` uses regex
   splits on `[.;\n]`, `then`, `потом`, plus hardcoded fixture matches for
   `BrainBuddy`/`production smoke`/`Наташа` and `купить хлеб и молоко`.
   `service.py:670` calls `self._extract_task_titles(accurate_segment.text)`
   in the production path.
4. **Synthetic-tone evaluation**: `evaluation.py:117-145` validates synthetic
   WAVs by tone frequency and injects expected transcripts via
   `transcripts` dict keyed by `fixture_{case_id}`. No test listens to real
   speech.
5. **Consent/hint propagation**: `schemas/tasks.py:254-257`
   `BrainDumpConsentRequest` has no `language_hints` or `vocabulary` fields.
   `domain.py:159` defaults `external_processing_allowed: bool = False`.
   `service.py:602-612` constructs `AccurateSttRequest` without
   `language_hints` or `vocabulary` (both default to empty list in
   `providers.py:18-20`). Browser locale is the only language signal.

Re-verification on 2026-07-24 at `origin/main` `77fe9aa` found all five root
causes fixed in the shipped code: declared hints drive browser locale; the
OpenAI adapter sends sealed bytes as multipart audio; deterministic STT is
test-only; regex extraction is limited to non-committable preview/CI paths; the
real-audio harness separates STT from extraction metrics; and consent, hints,
and vocabulary reach every external provider call. Offline closure T057, T058,
T061, and T064 is complete on the current candidate. Remaining terminal
acceptance work is recorded in `tasks.md` T044, T053, T055, T060, T062, and
T063 and summarized in `implementation-readiness.md`.

## Technical context

**Language/Version**: Python 3.11 (backend); TypeScript strict + React (frontend).

**Primary dependencies**: Existing FastAPI, Pydantic, sqlite3, React, React
Query, Vite. The first real STT adapter may use `httpx` (already a backend
dependency) to call OpenAI `gpt-4o-mini-transcribe`/`gpt-4o-transcribe`; at
least one credible alternative (ElevenLabs Scribe v2 or Deepgram Nova-3) is
benchmarked before locking. The real text reconciler uses a current text model
through the existing model-routing configuration; no new SDK is introduced into
the production decision path unless benchmarks require it.

**Storage**: Canonical tasks remain in `backend/data/tasks.sqlite3`. Voice
operations, idempotency records, and the migration ledger are owner-scoped in
`voice_operations.sqlite3`; raw audio chunks remain under the configured data
root behind opaque owner-scoped media references and retention cleanup. No new
external database, broker, or worker service is introduced in this slice.

**Testing**: pytest/FastAPI TestClient, Vitest + Testing Library, Playwright
Compose E2E, deterministic labelled audio/text fixtures for state-machine CI,
repository restart/lease/idempotency tests, `scripts/check_spec_kit_specs.py`,
normal backend/frontend CI gates, plus a real-audio evaluation harness
separating STT from extraction quality.

**Target platform**: Responsive web app; mobile browser recording with
server-side FastAPI processing.

**Project type**: Existing backend/frontend web application (modular monolith).

**Performance goals**: ADR-0002 p95 budgets unchanged: local recording
feedback <100 ms; stable fast segment <700 ms after segment end; first
provisional task <1.5 s after a semantic boundary; visible patch <500 ms after
emission; streamed fast drain <2 s; reconciled two-minute dump <8 s and
configured maximum <20 s; local confirmation acknowledgement <1 s. Real
provider latency is measured and reported by duration, language, and model
version; a labelled fallback is allowed when budgets are missed, never a safety
weakening.

**Constraints**: Explicit external-processing consent; original audio required
for new schema-v2 accurate reconciliation; polling must restore full state; no
raw content in telemetry; bounded retries/leases; no canonical task before
confirmation; no paid live provider in ordinary CI; production must not
instantiate deterministic STT silently; binary audio never decoded as UTF-8
text; no regex/hardcoded fixture logic in production decision path.

**Scale/scope**: One primary-user MVP workflow with bounded recording duration
and short working-artifact retention. Weekly Review receives shared
substrate-compatible contracts only; no Weekly Review UX expansion in this
slice. No diarization, no general voice-agent framework.

## Constitution check

Gate result: PASS before and after this plan. No waiver required.

- **Spec workflow**: `spec.md`, `acceptance-tests.md`, this plan, requirements
  checklist, and `tasks.md` are current. ADR-0002 is the architecture source of
  truth.
- **Consent & safety**: Media leaves the device only under current
  external-processing consent naming the configured provider category. Audio,
  transcripts, task text, vocabulary, paths, hashes usable as fingerprints, and
  real user data stay out of logs, metrics, committed fixtures, and PR
  evidence. Test fixtures are synthetic; real-audio corpus is founder-supplied
  and versioned separately from committed code.
- **Tests**: Every behavior task starts with failing deterministic
  backend/frontend tests. Provider failure, timeout, retry, cancellation,
  owner isolation, idempotency, migration, polling, partial recovery, consent
  denial, cost-limit, and disabled-provider states are explicit acceptance
  groups. STT quality is measured separately from extraction quality.
- **Contracts**: Schema-v2 operation, transcript version, proposal
  patch/conflict, provider port, API projection, state machine, and v1
  compatibility aliases are defined in ADR-0002. The real-provider adapter and
  real reconciler implement those ports; they do not introduce new domain
  enums or branches.
- **Observability**: Correlation IDs, redacted stage events, real progress
  labels, retry/error codes, lease recovery counts, provider/model version,
  cost-budget consumption, and fallback quality are required; no fake
  percentages, no raw audio/transcript in logs.
- **Mobile/resilience/performance**: Chunked local recording survives offline
  windows within limits. UI closure does not cancel. Polling and persisted
  leases/checkpoints recover state. Real provider latency is measured on real
  audio by language and model version.
- **Delivery boundary**: These tasks are planning input. Hermes Kanban
  ownership, isolated worktrees, TDD, independent
  architecture/product/AI-QA review, CI, PR, merge, Fly deploy, and
  production-safe smoke remain authoritative. `/speckit-implement` is
  disabled; implementation starts only when the Kanban dispatcher spawns the
  owning specialist profile.

## Architecture and ownership

### Application workflow package (unchanged boundary)

`backend/app/workflows/voice_brain_dump/` remains the owner of async-operation
orchestration and contracts:

```text
backend/app/workflows/voice_brain_dump/
├── __init__.py       # public workflow types/service
├── domain.py         # schema-v2 operation, runs, segment versions, patches/conflicts
├── providers.py      # FastSttPort, AccurateSttPort, TextReconcilerPort + deterministic CI fakes
├── evaluation.py     # real-audio evaluation harness (STT vs extraction quality)
├── audio_media.py    # admitted media inspection and canonical MIME handling
├── confirmation.py   # confirmation orchestration across the TaskPort
├── task_port.py      # explicit canonical Task application boundary
├── adapters/         # real provider adapters
│   ├── __init__.py
│   ├── openai_stt.py     # OpenAI gpt-4o-mini-transcribe / gpt-4o-transcribe
│   └── reconciler.py    # structured semantic text-model reconciler
├── repository.py     # owner-scoped payload/history, leases, media refs, v1 import
└── service.py        # commands, projections, patches, due-run leases/recovery
```

The shipped `adapters/` subpackage implements the same ports
(`AccurateSttPort`, `TextReconcilerPort`) as the deterministic fakes; they are
wired by dependency injection in `backend/app/container.py` based on
configuration. A provider change must not change operation, transcript,
proposal, or confirmation contracts.

### Existing files changed by the slice

```text
backend/app/core/config.py                    # voice provider selection, credentials, deadlines, retention, cost limits
backend/app/container.py                      # wire real adapters vs deterministic fakes by config + consent
backend/app/main.py                           # due-run/retention sweep lifecycle
backend/app/api/dependencies.py               # resolve VoiceBrainDumpService with configured providers
backend/app/api/tasks.py                      # add language_hints/vocabulary to start request; unchanged route family
backend/app/schemas/tasks.py                  # BrainDumpConsentRequest + BrainDumpOperationStartRequest: language_hints, vocabulary
backend/app/modules/tasks/domain.py           # canonical native Task source link only
backend/app/modules/tasks/service.py          # title-only idempotent Inbox create command only
backend/app/workflows/voice_brain_dump/domain.py # BrainDumpConsent hints/vocabulary and operation records
backend/app/workflows/voice_brain_dump/service.py # consent/hint propagation and provider orchestration
backend/app/workflows/voice_brain_dump/providers.py  # contract guard: accurate_stt must not decode audio as UTF-8; extract fakes to CI-only
backend/app/workflows/voice_brain_dump/evaluation.py # real-audio harness: STT CER/WER separate from extraction metrics
frontend/src/features/brain-dump/BrainDumpRoute.tsx   # recognition.lang from declared language hints, not navigator.language
frontend/src/api/taskTypes.ts                 # consent schema: language_hints, vocabulary
frontend/src/api/client.ts                    # start request: send language_hints/vocabulary
frontend/tests/native-tasks-voice-brain-dump.compose.spec.ts  # credentialed E2E with real audio (gated)
```

### Provider configuration contract

Configuration is role- and schema-based, never a stored vendor enum:

```python
# backend/app/core/config.py (new voice.* section)
voice:
  accurate_stt:
    provider: "openai" | "elevenlabs" | "deepgram" | "deterministic" | "disabled"
    model: "gpt-4o-mini-transcribe"  # or provider-specific
    api_key_env: "OPENAI_API_KEY"     # env var name, never the value
    timeout_seconds: 60
    max_retries: 3
    retry_backoff_seconds: [2, 4, 8]
    max_cost_usd_per_operation: 0.50
  fast_stt:
    provider: "disabled"  # current MVP; same schema retained for a measured adapter
    # ... same shape; do not enable without corpus evidence
  reconciler:
    provider: "openai" | "deterministic" | "disabled"
    model: "gpt-4o"
    # ... same shape
  retention:
    raw_audio_seconds: 86400       # 24h after successful reconciliation
    working_artifacts_seconds: 604800  # 7 days after completion/cancellation
```

- `provider: "deterministic"` is valid ONLY in CI/test configuration. Production
  startup MUST refuse `"deterministic"` for `accurate_stt` unconditionally.
- `provider: "disabled"` is the safe default when no credentials or consent are
  present. The operation enters `terminal_error` or `provisional_only` review
  with a redacted error code; it never silently falls back to deterministic
  fakes.
- Provider/model/version is recorded in `ProviderRun` as provenance, never as a
  domain-state enum.

### Consent and language hint propagation

`BrainDumpConsentRequest` and `BrainDumpConsent` gain:

```python
class BrainDumpConsentRequest(StrictBaseModel):
    microphone: bool
    external_processing_allowed: bool = False
    provider: str | None = Field(default=None, max_length=100)
    language_hints: list[str] = Field(default_factory=list, max_length=10)
    vocabulary: list[str] = Field(default_factory=list, max_length=200)
```

- `language_hints` carries declared speech languages (e.g. `["ru"]`,
  `["ru", "en"]`). The frontend sends the user's declared input language(s);
  the backend propagates them to `FastSttRequest.language_hints`,
  `AccurateSttRequest.language_hints`, and `ReconcileTextRequest` context.
- `vocabulary` carries recurring keyterms (`BrainBuddy`, `production smoke`,
  `Наташа`, project/person names). The backend propagates them to every STT
  and reconciler invocation as `SttContext.vocabulary`.
- The frontend sets `recognition.lang` from the first declared language hint
  (e.g. `"ru-RU"` for `ru`, `"en-US"` for `en`), falling back to
  `navigator.language` only when no hint is declared. Browser preview remains
  labelled `browser_preview` and never authoritative.
- External-processing consent is evaluated against the configured provider
  category. Without consent, no audio leaves the device; with
  `provider: "disabled"` or missing credentials, the operation surfaces an
  explicit disabled state.

### Sealed-original-audio lifecycle

The sealed original audio lifecycle is unchanged from ADR-0002:

1. `MediaRecorder` produces monotonic chunks with `(operation_id, chunk_no,
   content_sha256)` identity.
2. `seal` validates the complete manifest hash and marks audio as sealed.
3. Accurate STT receives the sealed `media_ref` (opaque reference to stored
   bytes), audio metadata, language hints, and vocabulary. It NEVER receives
   fast text as its audio input.
4. The adapter decodes audio bytes using the provider's audio API (e.g.
   multipart upload to OpenAI), NOT `bytes.decode("utf-8")`.
5. After successful reconciliation, raw audio is retained for 24h then deleted;
   transcript provenance and confirmed action receipts follow ADR-0001
   retention rules.
6. Users can delete raw audio immediately after processing; the transcript
   and source provenance remain valid.

### Transcript provenance

- Every proposal links to `source_segment_ids`.
- Every committed action links to source transcript segment IDs and the
  operation action receipt.
- Native Inbox tasks link the operation action receipt and proposal ID through
  their source reference (existing `source_capture_ids` field or a new
  `source_operation_action_id` field on `TaskCreateRequest`).
- `ProviderRun` records `provider`, `model`, `template_version`,
  `input_hash`, `output_ref`, `attempt`, `error_code` as immutable provenance.

### Schema-valid semantic reconciliation operations

The real reconciler MUST emit only schema-valid `ProposalPatch` operations
defined in `domain.py`:

- `add`: create a new proposal with stable ID, title, source spans.
- `update`: revise wording/source spans of an existing proposal, preserving ID.
- `split`: atomically create two+ server-assigned IDs, link each child to the
  predecessor, mark predecessor `superseded`.
- `merge`: atomically create one server-assigned ID linked to all predecessors,
  mark each predecessor `superseded`.
- `remove`: mark a proposal `tombstoned`.
- `supersede`: one-to-one replacement when semantic identity changed.
- `reorder`: pin relative order (user only).

The reconciler receives `AccurateTranscriptProjection`,
`ProposalProjection`, `UserLocks`, and `OpenConflicts` (per ADR-0002 port
signature). It returns `ProposalPatchDraft[]`; the service allocates IDs and
atomically materializes validated patches. The reconciler never mutates
canonical state, never resolves existing targets semantically without user
selection, and never infers metadata (tags, project, priority, due date,
details) for native Brain Dump tasks.

### User review/edit/delete conflict rules

Preserved from ADR-0002 §"Concurrent speech and user edits":

- User patches have highest authority and are never silently overwritten.
- Editing `title` locks only `title`; deleting locks lifecycle state; a user
  reorder locks relative order.
- A reconciler draft touching a locked field creates a `ProposalConflict`
  containing the current user value and suggested value but does not apply the
  field change.
- Review shows both values with `Keep mine` and `Use suggestion`. Resolving
  either choice is a user patch and closes the conflict without deleting it.
- Freeze/confirm is rejected while an active proposal has an open conflict.
- A user-deleted proposal never reappears because of a provider rerun; any
  suggested restoration is a conflict requiring an explicit user action.
- A stale-base title patch (base_revision < current title_revision) is treated
  as a conflicting stale patch (PA-05): rejected into an open conflict, never
  a silent overwrite.

### Exactly-once Inbox persistence

Preserved from ADR-0002 §"Confirmation, commit, idempotency":

- For native `voice_brain_dump`, every selected action is exactly
  `create_native_inbox_task {proposal_id, title}`.
- The Task application port sets `state=inbox`, `details=null`,
  `project_id=null`, `tag_ids=[]`, `due_date=null`, `priority=none`.
- Confirmation uses one command idempotency key and one deterministic child
  key per action: `H(operation_id, batch_id, action_id)`.
- Repeating the same key and request hash returns the original result; reusing
  a key with another hash returns `409 IDEMPOTENCY_CONFLICT`.
- One action key produces at most one task ID even after timeout, process
  restart, or retry with a new outer HTTP request.
- No task row, Capture/Organize record, route, or external side effect exists
  before the confirmation command.
- Tombstoned/superseded proposals are excluded; an open conflict prevents
  freeze/confirm.

### Observability rules (raw audio/transcripts excluded from ordinary logs)

- Operation events carry IDs, enum states, counts, coarse confidence bands, and
  progress only—never audio, transcript text, task text, vocabulary, paths,
  hashes usable as content fingerprints, emails, or credentials.
- `ProviderRun` records provider/model/version, attempt, input_hash (SHA-256 of
  sealed audio, used only for dedup, never logged as content), error_code,
  and stage timings.
- Analytics contain only pseudonymous IDs, stage timings, coarse confidence
  bands, counts, error codes, and cost-budget consumption.
- The GET projection omits provider payloads and hidden proposal bodies but
  includes IDs needed for owner-scoped audit view.
- A wrong-owner operation or nested ID returns `404` without revealing
  existence.
- The real-audio evaluation harness reports aggregate metrics (CER/WER,
  critical-term recall, task-count accuracy, boundary precision/recall) by
  language and provider/model version; individual corpus recordings and
  ground-truth transcripts are never committed to the repo.

## Evaluation protocol: STT accuracy vs extraction accuracy

The evaluation harness separates the two quality dimensions:

### STT accuracy (provider/model-level)

- Input: sealed original audio bytes from the founder corpus.
- Output: transcript text + segment timing.
- Metrics: CER (character error rate), WER (word error rate), critical-term
  recall (percentage of declared keyterms preserved), omission count (dropped
  words), hallucination count (invented words), latency by duration/language.
- Ground truth: founder-supplied transcript labels, prepared by the agent
  after receiving the recording, versioned separately from code.
- No injected expected transcripts: the harness calls the real provider
  adapter with real audio and compares output to ground truth.

### Task extraction accuracy (reconciler-level)

- Input: the accurate transcript (from STT step).
- Output: proposal patches (add/update/split/merge/remove/supersede).
- Metrics: exact task-count accuracy, task-boundary precision/recall, title
  cleanliness, task-identity accuracy, invented-task count, provenance-only
  boundary precision/recall, conjunction false-split rate, split/merge
  accuracy, semantic preservation score, confidence calibration error.
- Ground truth: founder-supplied expected task titles/boundaries.
- The reconciler is called with the accurate transcript projection; no
  regex/hardcoded fixture logic is in the production decision path.
- Deterministic fakes remain valid only for ordinary state-machine CI (e.g.
  ML-01–ML-06 contract scenarios), never as speech-quality evidence.

### Release targets

- STT: 100% critical-term preservation on the approved corpus; a measured
  CER/WER threshold established from the first baseline (not invented before
  corpus evidence).
- Extraction: at least 95% exact task-count accuracy, at least 95%
  identity-aware task-boundary precision/recall, 100% accepted task identities,
  zero invented tasks, zero silent user-edit loss, zero canonical writes before
  confirmation, zero duplicate tasks after retries. Provenance-only boundary
  precision/recall is reported separately and never substitutes for task
  identity.
- Safety invariants are release-blocking regardless of latency/cost.

## Migration and compatibility constraints with native GTD contracts

### Native GTD lifecycle (ADR-0006)

- Voice Brain Dump confirmation creates tasks with `state=inbox` only. The
  operation never infers `next`, `waiting`, `someday`, `completed`, or
  `cancelled` from speech.
- No inferred tags, project assignment, priority, due date, details, or
  waiting-for from speech. These fields remain user-controlled.
- The `create_native_inbox_task` port is the same one Smart Add (ADR-0007)
  uses; voice does not bypass it.

### Schema-v1 migration (ADR-0002)

- Completed/cancelled v1 operations remain readable and immutable. Never
  replay them or create tasks during migration.
- Active v1 operations import once as `legacy_preview_only`; they cannot
  claim accurate reconciliation because no original audio exists.
- `/transcript`, `/finish`, `/commit`, and direct proposal PATCH remain
  additive aliases for one compatibility window, mapping to preview-seal,
  confirm, and user-patch semantics.
- The 2026-07-19 amendment adds no new migration step; it changes the
  production provider wiring and reconciler implementation, not the operation
  schema. Existing v2 operations remain valid.

### Provider adapter migration

- `DeterministicAccurateStt` is moved to a CI-only import path. Production
  startup refuses it unconditionally.
- The canonical `TaskService` has no STT dependency. The container wires the
  configured real adapter into `VoiceBrainDumpService`; missing
  credentials/consent surface as `provider: "disabled"`.
- `_extract_titles` fixture logic is absent from the committable reconciliation
  path; it remains only inside `DeterministicTextReconciler` for CI
  state-machine tests. The workflow service's separate local title heuristic
  feeds visibly provisional, non-committable browser-preview proposals only.

## Contracts and flow

1. `POST /api/brain-dump-operations` records consent, `language_hints`, and
   `vocabulary`; returns schema-v2 `recording` projection.
2. `MediaRecorder` uploads monotonic audio chunks with capture-clock spans and
   content hash. Browser Web Speech posts preview segments labelled
   `browser_preview` with corrected locale from declared hints. The current MVP
   uses a local heuristic only to render non-committable provisional proposals;
   the server `fast_stt` provider role remains disabled until corpus evidence
   justifies an adapter.
3. Stop posts `seal` with expected count/manifest hash. The persisted runner
   advances `sealing -> fast_processing -> accurate_transcribing -> reconciling`.
4. Accurate STT receives the sealed opaque media reference (not fast text),
   language hints, and vocabulary. Accepted segment versions explicitly
   supersede covered fast/preview IDs.
5. The real text reconciler receives the active accurate projection, stable
   proposal IDs, full lineage, user locks, and conflicts. It returns
   structured add/update/split/merge/remove/supersede drafts. The service
   allocates IDs and atomically appends validated patches.
6. `awaiting_confirmation` renders Review. Open conflicts block freeze. A
   frozen batch pins one proposal revision.
7. `confirm` calls the native Task port once per selected active proposal with
   deterministic child key and title only. The Task port supplies
   Inbox/default fields and returns one stable task ID.
8. GET projection plus polling exposes the persisted state. Reconnect never
   depends on client-held transcript/proposal state; no SSE/WebSocket control
   plane is required for correctness.

## Test and evaluation strategy

- **Domain/unit**: all state transitions; transcript active projection;
  many-to-many supersession; patch preconditions; stable IDs; split/merge
  positions; tombstone visibility; lock/conflict resolution; freeze rules;
  schema-valid operation enforcement; contract guard rejecting UTF-8 audio
  decoding in production adapters.
- **Repository**: owner isolation; v1 import once; lease claim/race/expiry;
  process-restart recovery; timeout-after-accept; append atomicity;
  deterministic child idempotency.
- **API**: chunk/seal gaps and conflicts; commands/revisions;
  polling/event equivalence; nested wrong-owner `404`; redacted envelopes;
  compatibility aliases; confirmation defaults; consent denial;
  missing-credentials disabled state; cost-limit retryable state.
- **Frontend**: MediaRecorder plus preview fallback; progressive stable-key
  list; explicit processing labels; polling resume; edit/delete locks;
  conflict UI; fallback warning; Save disabled until conflict-free;
  `recognition.lang` from declared hints.
- **Evaluation**: real-audio harness separates STT CER/WER/critical-term
  recall from extraction task-count accuracy/boundary precision-recall;
  deterministic ML-01–ML-06 remain valid for state-machine CI only.
- **E2E**: record -> provisional list -> stop -> processing -> accurate
  correction and split/merge -> edit/delete/conflict resolution -> explicit
  Save -> reload/relogin Inbox; uses credentialed real providers and genuine
  spoken audio for the product E2E; deterministic fake providers for ordinary
  CI.

## Rollout and release

1. Storage/contracts/OpenAI adapter/reconciler are shipped; schema-v1 remains
   default-compatible and deterministic fakes remain CI-only.
2. Keep production provider use disabled until explicit consent, credentials,
   provider audit metadata, and corpus-backed baseline gates are present;
   benchmark at least one credible alternative before locking.
3. Run exact-head backend/frontend/Compose E2E and labelled evaluation gates;
   real-audio corpus gates run in a credentialed track, not ordinary CI.
4. Enable configured real providers only with consent, credentials,
   deadlines, and budget; provider absence is an explicit disabled/fallback
   state.
5. Independent Product QA and AI-QA review the same immutable candidate head.
6. Classify the change under ADR-0008. SHIP/SHOW uses verified-trunk serial
   landing; ASK uses its explicit approval and audited temporary-ruleset path.
   Then verify automatic Fly deploy, main CI, authenticated production-safe
   smoke, and the final credentialed real-phone Russian journey.

## Complexity tracking

No constitution violation. The amendment replaces deterministic fakes with
real adapters behind the same ports, adds a real reconciler emitting
schema-valid operations, and separates STT from extraction quality in the
evaluation harness. No new broker, worker service, CRDT, distributed
transaction, domain-state vendor enum, or external side effect is introduced.
The operation/patch/confirmation substrate and ADR-0002 state machine are
preserved.
