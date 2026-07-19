# Tasks: Real, friend-demo-ready Voice Brain Dump

**Input**: `spec.md`, `plan.md`, ADR-0002, and `acceptance-tests.md` in this
feature directory.

**Tests**: Behavioral work is TDD. Add the focused test first, run it to prove
the expected failure, implement the minimum change, then rerun the focused and
affected suites.

**Execution boundary**: This file is planning input. Hermes Kanban task
dependencies, isolated worktrees, independent review, CI, PR, merge, deploy, and
smoke evidence remain the authoritative delivery workflow. `/speckit-implement`
is disabled; implementation starts only when the Kanban dispatcher spawns the
owning specialist profile.

## Format: `[ID] [P?] [Story] Description`

## Phase 1: Contract and deterministic-test foundation (preserve)

- [x] T001 Add synthetic, versioned RU/EN/code-switch audio/text fixture
  manifest and labels for ML-01–ML-06 under
  `backend/tests/fixtures/voice_brain_dump/v1/`; record source/license and
  expected spans/task boundaries, with no real-user media.
- [x] T002 [P] Add failing provider-port and invalid-output tests for PV-01,
  PV-02, and PV-05 in
  `backend/tests/test_voice_brain_dump_reconciliation.py`.
- [x] T003 [P] Add failing schema/state/segment-projection tests for OP-01,
  OP-02, PV-03, and PV-04 in
  `backend/tests/test_voice_brain_dump_domain.py`.
- [x] T004 [P] Add failing v1 import/idempotency/lease tests for PV-06,
  RC-01–RC-04, and MG-01–MG-03 in
  `backend/tests/test_voice_brain_dump_repository.py` and
  `backend/tests/test_voice_brain_dump_runner.py`.
- [x] T005 Add schema-v2 domain records and pure projection/validation
  functions in `backend/app/workflows/voice_brain_dump/domain.py`; expose
  public types from `backend/app/workflows/voice_brain_dump/__init__.py`.
- [x] T006 Add `FastSttPort`, `AccurateSttPort`, `TextReconcilerPort`, their
  draft contracts, and deterministic fakes in
  `backend/app/workflows/voice_brain_dump/providers.py`; no vendor branch or
  live call in these tests.

**Checkpoint**: Provider roles and append-only domain semantics are executable
without HTTP, React, a paid provider, or canonical task writes.

## Phase 2: Persisted operation/media/runner foundation (preserve)

- [x] T007 Add failing repository tests for owner-scoped
  operation/chunk/nested-artifact reads, append revision conflicts,
  duplicate/conflicting chunks, and exact missing manifest gaps in
  `backend/tests/test_voice_brain_dump_repository.py` (UP-01–UP-05, TR-07).
- [x] T008 Implement schema-v2 operation payload/history, opaque media refs,
  chunk manifests, compare-and-set leases, provider-run lookup, and one-time
  v1 import in `backend/app/workflows/voice_brain_dump/repository.py`.
- [x] T009 Add configuration-backed recording limits, role selection,
  provider deadlines, max attempts, retry cap, recovery budget, lease
  duration, and retention in `backend/app/core/config.py`.
- [x] T010 Add failing runner tests for due-run claim, deadline, retry delay,
  expired-lease restart, successful input-hash reuse, cancellation, and
  terminal recovery budget in
  `backend/tests/test_voice_brain_dump_runner.py`.
- [x] T011 Implement the bounded scanner/lease runner in
  `backend/app/workflows/voice_brain_dump/runner.py`.
- [x] T012 Wire workflow repository, ports, service shell, and runner through
  `backend/app/container.py`; add startup/shutdown lifecycle in
  `backend/app/main.py` and a resolver in
  `backend/app/api/dependencies.py`.

**Checkpoint**: Persisted work survives process replacement and cannot
hot-loop or duplicate accepted provider output.

## Phase 3: US1 — Provisional mixed-language tasks while speaking (P1)

**Independent test**: ML-01 produces three numbered provisional tasks while
recording and Inbox remains unchanged.

- [x] T013 [US1] Add failing API tests for operation creation, audio upload,
  preview labels, fast-window scheduling, progressive proposals, polling
  projection, consent denial, and cross-owner nested IDs in
  `backend/tests/test_brain_dump_operations_api.py`.
- [x] T014 [US1] Implement start/chunk/preview/GET/events contracts in
  `backend/app/schemas/tasks.py` and `backend/app/api/tasks.py`; route
  orchestration through `backend/app/modules/tasks/service.py`.
- [x] T015 [US1] Implement fast-window scheduling and validated
  `TextReconcilerPort.extract_provisional` patch materialization in
  `backend/app/modules/tasks/service.py`; stable IDs and source audio spans.
- [x] T016 [P] [US1] Add failing TypeScript API contract tests/types for
  schema-v2 projection, audio chunks, preview segments, events, and polling
  in `frontend/src/api/taskTypes.ts` and `frontend/src/api/__tests__/`.
- [x] T017 [US1] Implement client calls in `frontend/src/api/client.ts` and
  MediaRecorder original-audio capture/upload plus optional labelled Web
  Speech preview in `frontend/src/features/brain-dump/BrainDumpRoute.tsx`.
- [x] T018 [US1] Add/extend failing UI tests in
  `frontend/src/features/brain-dump/BrainDumpRoute.test.tsx` for progressive
  stable-key numbered cards, RU/EN preview, offline/microphone/storage
  errors, pause/resume, and polling resume.

**Checkpoint**: Original audio is durable and provisional tasks are useful,
but no native Task can exist.

## Phase 4: US2 — Accurate original-audio reconciliation and safe Review (P1)

**Independent test**: ML-02 corrects from audio, ML-03 splits a run-on, ML-04
does not split `купить хлеб и молоко`, and ML-06 surfaces a lock conflict.

- [x] T019 [US2] Add failing API/service tests for
  `sealing -> fast_processing -> accurate_transcribing -> reconciling ->
  awaiting_confirmation`, accurate input media ref, segment supersession, and
  fast/accurate/reconciler fallbacks.
- [x] T020 [US2] Implement seal scheduling and accurate-STT generation
  acceptance from `media_ref` in
  `backend/app/modules/tasks/service.py`; reject missing spans/schema and
  never pass fast text as audio input.
- [x] T021 [US2] Add failing pure patch tests for update identity, split,
  merge, remove, supersede, ordering, hidden history, stale-base
  rebase/reject, and provider retry ID reuse (PA-02, PA-04–PA-08, PA-15,
  PA-16).
- [x] T022 [US2] Implement validated patch materialization/projection in
  `backend/app/workflows/voice_brain_dump/domain.py`; array position must
  never identify a proposal.
- [x] T023 [US2] Add failing lock/conflict/freeze tests for PA-03, PA-10,
  PA-14, ML-06; implement field-specific user patches and append-only
  conflict resolution.
- [x] T024 [US2] Add failing UI tests for `Finishing upload`, `Improving
  transcript`, `Reconciling tasks`, Review-only-at-awaiting-confirmation,
  lineage-safe edit/delete, visible mine/suggestion conflict, and Save
  blocking.
- [x] T025 [US2] Implement processing and Review projections/conflict
  controls in `frontend/src/features/brain-dump/BrainDumpRoute.tsx`.
- [x] T026 [US2] Add a deterministic evaluation runner/report test for
  ML-01–ML-06 metrics.

**Checkpoint**: Review is accurate or explicitly labelled provisional-only;
user authority and proposal history survive every model rerun.

## Phase 5: US3 — Resumable explicit exactly-once Inbox save (P1)

**Independent test**: Close/reopen with polling, retry bounded provider
failure, resolve conflicts, Save twice, reload/relogin, and observe one
title-only Inbox task per selection.

- [x] T027 [US3] Add failing native Task port tests for deterministic child
  keys and exact defaults (`inbox`, null details/project/due date, empty tags,
  `priority=none`) (CO-03, CO-04, CO-11).
- [x] T028 [US3] Add the title-only idempotent command/source receipt to
  `backend/app/modules/tasks/service.py`, `domain.py`, and `repository.py`;
  expose it as a port to the workflow.
- [x] T029 [US3] Implement conflict-free batch freeze and confirm in
  `backend/app/modules/tasks/service.py` and `backend/app/api/tasks.py`;
  persist per-action results and resume unresolved actions without
  duplicates.
- [x] T030 [US3] Add failing UI tests for polling-only reopen,
  retry/provisional-only warning, conflict resolution, repeated Save, success
  count, and Inbox cache refresh.
- [x] T031 [US3] Add v1 alias regression tests for `/transcript`,
  `/finish`, `/commit`, and direct proposal PATCH; keep responses additive
  and old terminal operations immutable.

**Checkpoint**: The complete native Brain Dump loop is restart-safe and
produces no inferred metadata or duplicate tasks.

## Phase 6: Real provider wiring and consent propagation (new, amended)

These tasks replace the deterministic-fake production default with real
adapters behind the same ports. They are the core of the 2026-07-19 amendment.

- [ ] T039 [P] [US4] Add failing tests for PV-08 (no UTF-8 audio decoding),
  PV-09 (no deterministic default in production), and PV-10 (browser locale
  from declared hints) in
  `backend/tests/test_voice_brain_dump_reconciliation.py` and
  `frontend/src/features/brain-dump/BrainDumpRoute.test.tsx`.
- [ ] T040 [US4] Add `language_hints` and `vocabulary` fields to
  `BrainDumpConsentRequest`, `BrainDumpConsent`, and
  `BrainDumpOperationStartRequest` in `backend/app/schemas/tasks.py` and
  `backend/app/modules/tasks/domain.py`; propagate them to
  `AccurateSttRequest` in
  `backend/app/workflows/voice_brain_dump/providers.py` and to every STT
  and reconciler invocation in
  `backend/app/modules/tasks/service.py`.
- [ ] T041 [US4] Correct browser preview locale in
  `frontend/src/features/brain-dump/BrainDumpRoute.tsx`: set
  `recognition.lang` from declared `language_hints` rather than
  `navigator.language`; update `frontend/src/api/client.ts` to send
  `language_hints`/`vocabulary` in the start request.
- [ ] T042 [US4] Add `voice.*` configuration section to
  `backend/app/core/config.py`: `accurate_stt.provider`,
  `accurate_stt.model`, `accurate_stt.api_key_env`,
  `accurate_stt.timeout_seconds`, `accurate_stt.max_retries`,
  `accurate_stt.retry_backoff_seconds`, `accurate_stt.max_cost_usd_per_operation`,
  same shape for `fast_stt` and `reconciler`, and `retention.*`; add focused
  config tests.
- [ ] T043 [US4] Create `backend/app/workflows/voice_brain_dump/adapters/`
  with `openai_stt.py` implementing `AccurateSttPort` over
  `gpt-4o-mini-transcribe`/`gpt-4o-transcribe` using `httpx`; pass sealed
  audio bytes as multipart audio, NOT `bytes.decode("utf-8")`; enforce
  timeout/retry/cost limits; record `provider`/`model`/`template_version`
  in `ProviderRun`.
- [ ] T044 [US4] Benchmark at least one credible alternative STT provider
  (ElevenLabs Scribe v2 or Deepgram Nova-3) behind the same `AccurateSttPort`;
  record metrics in the evaluation report; do not lock the provider until
  corpus evidence justifies it.
- [ ] T045 [US5] Wire real adapters vs deterministic fakes by config + consent
  in `backend/app/container.py`; refuse
  `DeterministicAccurateStt` at production startup unless
  `BRAINBUDDY_ALLOW_DETERMINISTIC_STT=1` env var is set; missing
  credentials/consent surface as `provider: "disabled"`.
- [ ] T046 [US5] Remove `DeterministicAccurateStt` default from
  `backend/app/modules/tasks/service.py:116`; the container injects the
  configured adapter.
- [ ] T047 [P] [US5] Add failing tests for PR-07 (language hints propagate),
  PR-08 (cost limit reached), PR-09 (missing credentials disabled state),
  and UP-08 (no external consent) in
  `backend/tests/test_brain_dump_operations_api.py`.

**Checkpoint**: Production consumes sealed audio as audio; consent and hints
propagate; missing credentials surface as disabled, never silent
deterministic fakes.

## Phase 7: Real semantic reconciler (new, amended)

These tasks replace regex/hardcoded fixture extraction with a structured
text-model reconciler emitting schema-valid operations.

- [ ] T048 [US4] Add failing tests for PA-17 (schema-valid operations only)
  and PA-18 (no regex in production path) in
  `backend/tests/test_voice_brain_dump_reconciliation.py`; assert the
  production reconciler path contains no `_extract_titles` regex calls.
- [ ] T049 [US4] Create
  `backend/app/workflows/voice_brain_dump/adapters/reconciler.py`
  implementing `TextReconcilerPort.reconcile` using a current text model
  (e.g. `gpt-4o`) through the existing model-routing configuration; emit
  only schema-valid `add/update/split/merge/remove/supersede` patches;
  preserve transcript provenance, user locks, and conflicts; never infer
  metadata.
- [ ] T050 [US4] Wire the real reconciler in
  `backend/app/container.py` by config + consent; remove
  `_extract_titles` from the production decision path in
  `backend/app/modules/tasks/service.py`; keep
  `DeterministicTextReconciler` for CI state-machine tests only.
- [ ] T051 [US4] Add transcript provenance link: native Inbox tasks link the
  operation action receipt and proposal ID through their source reference in
  `backend/app/modules/tasks/domain.py` and `repository.py`.

**Checkpoint**: The production reconciler is a structured semantic process;
regex/hardcoded fixtures are CI-only.

## Phase 8: Real-audio evaluation harness (new, amended)

These tasks separate STT accuracy from extraction accuracy and establish
corpus-based release gates.

- [ ] T052 [P] [US4] Amend
  `backend/app/workflows/voice_brain_dump/evaluation.py` to separate STT
  metrics (CER, WER, critical-term recall, omission/hallucination counts,
  latency) from extraction metrics (task-count accuracy, boundary
  precision/recall, title cleanliness, conjunction false-split rate,
  split/merge accuracy, semantic preservation, calibration error); report by
  language and provider/model version.
- [ ] T053 [US4] Add credentialed-track tests for SA-01–SA-05 (STT accuracy)
  and EA-01–EA-07 (extraction accuracy) in
  `backend/tests/test_voice_brain_dump_evaluation.py`; skip with explicit
  disabled-state report when credentials/consent are absent; never commit
  recordings or ground-truth transcripts to the repo.
- [ ] T054 [US4] Remove synthetic-tone frequency validation and injected
  expected transcripts from the production evaluation path; synthetic
  fixtures remain valid only for ordinary state-machine CI.
- [ ] T055 [US4] Establish a measured CER/WER threshold from the first
  baseline on the founder corpus; document it in the evaluation report; do
  not invent a threshold before corpus evidence.

**Checkpoint**: STT quality is measured separately from extraction quality;
release gates are corpus-backed.

## Phase 9: Integrated quality, privacy, and release gates (amended)

- [ ] T056 Extend `frontend/tests/native-tasks-voice-brain-dump.compose.spec.ts`
  with the exact deterministic journey: provisional mixed-language list ->
  processing stages -> accurate correction/split/merge -> edit/delete/conflict
  -> explicit Save -> reload/relogin Inbox.
- [ ] T057 [P] Add redaction/retention/consent-withdrawal tests for PR-01–PR-09
  in `backend/tests/test_voice_brain_dump_repository.py` and API tests;
  inspect captured logs/events to prove no content leakage.
- [ ] T058 [P] Add architecture/import test proving the workflow does not
  import task repositories and Weekly Review has no second voice engine.
- [ ] T059 Run focused backend tests, full `make ci-backend`, frontend focused
  tests, `make ci-frontend`, `make test-e2e`, and
  `python3 scripts/check_spec_kit_specs.py`; record real counts/results in
  the PR.
- [ ] T060 Run the versioned multilingual evaluation (deterministic ML-01–ML-06
  for CI, real-audio corpus for credentialed track) and attach aggregate
  metrics (no raw user content) to the PR; block release on SC-001–SC-009 or
  any safety invariant failure.
- [ ] T061 Update `.env.example` and operator docs for provider selection,
  timeout/retention configuration, consent, and disabled/fallback behavior;
  document provider-disabled state without secrets.
- [ ] T062 Add credentialed full-stack E2E using genuine spoken audio
  (gated track, not ordinary CI): record -> real STT -> real reconciler ->
  Review -> Save -> reload/relogin Inbox.
- [ ] T063 Hand the immutable PR head to independent Product QA and AI-QA;
  after approval and green exact-head CI, merge through the normal path,
  verify main CI/automatic Fly deploy, and run authenticated production-safe
  smoke. The credentialed real-phone Russian journey is the final
  acceptance step.

## Dependencies and parallel opportunities

- T001–T012 (Phases 1–2) are complete; they establish contracts, deterministic
  fixtures, and persisted operation/media/runner foundation.
- T013–T031 (Phases 3–5) are complete; they deliver US1–US3 with deterministic
  fakes.
- Phase 6 (T039–T047) blocks Phase 7 (T048–T051) because the real reconciler
  needs the consent/hint propagation and provider config from Phase 6.
- Phase 7 blocks Phase 8 (T052–T055) because the evaluation harness measures
  the real adapters and real reconciler.
- Phase 8 blocks Phase 9 (T056–T063) because release gates depend on
  corpus-backed metrics.
- Tasks marked `[P]` touch distinct files or test surfaces and may run in
  parallel after their phase dependency, but every implementation follows its
  failing test.
- The founder corpus (t_24d29290) is a separate Kanban track; Phase 8 tasks
  that require real audio are blocked until the corpus is available. Phases
  6–7 do not depend on the corpus and may proceed in parallel.
