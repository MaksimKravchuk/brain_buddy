# Tasks: Multilingual Voice Brain Dump Reconciliation

**Input**: `spec.md`, `plan.md`, ADR-0002, and `acceptance-tests.md` in this feature directory.

**Tests**: Behavioral work is TDD. Add the focused test first, run it to prove the expected
failure, implement the minimum change, then rerun the focused and affected suites.

**Execution boundary**: This file is planning input. Hermes Kanban task dependencies,
isolated worktrees, independent review, CI, PR, merge, deploy, and smoke evidence remain the
authoritative delivery workflow.

## Format: `[ID] [P?] [Story] Description`

## Phase 1: Contract and deterministic-test foundation

- [ ] T001 Add synthetic, versioned RU/EN/code-switch audio/text fixture manifest and labels
  for ML-01–ML-06 under `backend/tests/fixtures/voice_brain_dump/v1/`; record source/license
  and expected spans/task boundaries, with no real-user media.
- [ ] T002 [P] Add failing provider-port and invalid-output tests for PV-01, PV-02, and PV-05
  in `backend/tests/test_voice_brain_dump_reconciliation.py`.
- [ ] T003 [P] Add failing schema/state/segment-projection tests for OP-01, OP-02, PV-03, and
  PV-04 in `backend/tests/test_voice_brain_dump_domain.py`.
- [ ] T004 [P] Add failing v1 import/idempotency/lease tests for PV-06, RC-01–RC-04, and
  MG-01–MG-03 in `backend/tests/test_voice_brain_dump_repository.py` and
  `backend/tests/test_voice_brain_dump_runner.py`.
- [ ] T005 Add schema-v2 domain records and pure projection/validation functions in
  `backend/app/workflows/voice_brain_dump/domain.py`; expose public types from
  `backend/app/workflows/voice_brain_dump/__init__.py` until T003 passes.
- [ ] T006 Add `FastSttPort`, `AccurateSttPort`, `TextReconcilerPort`, their draft contracts,
  and deterministic fakes in `backend/app/workflows/voice_brain_dump/providers.py` until T002
  passes; no vendor branch or live call in these tests.

**Checkpoint**: Provider roles and append-only domain semantics are executable without HTTP,
React, a paid provider, or canonical task writes.

## Phase 2: Persisted operation/media/runner foundation

- [ ] T007 Add failing repository tests for owner-scoped operation/chunk/nested-artifact
  reads, append revision conflicts, duplicate/conflicting chunks, and exact missing manifest
  gaps in `backend/tests/test_voice_brain_dump_repository.py` (UP-01–UP-05, TR-07).
- [ ] T008 Implement schema-v2 operation payload/history, opaque media refs, chunk manifests,
  compare-and-set leases, provider-run lookup, and one-time v1 import in
  `backend/app/workflows/voice_brain_dump/repository.py`; keep storage in the configured data
  root/SQLite deployment and make T004/T007 pass.
- [ ] T009 Add configuration-backed recording limits, role selection, provider deadlines,
  max attempts, retry cap, recovery budget, lease duration, and retention in
  `backend/app/core/config.py` plus focused config tests.
- [ ] T010 Add failing runner tests for due-run claim, deadline, retry delay, expired-lease
  restart, successful input-hash reuse, cancellation, and terminal recovery budget in
  `backend/tests/test_voice_brain_dump_runner.py`.
- [ ] T011 Implement the bounded scanner/lease runner in
  `backend/app/workflows/voice_brain_dump/runner.py` until T010 passes; never rely on an
  in-memory queue for correctness.
- [ ] T012 Wire workflow repository, ports, service shell, and runner through
  `backend/app/container.py`; add startup/shutdown lifecycle in `backend/app/main.py` and a
  resolver in `backend/app/api/dependencies.py`, with focused app/container tests.

**Checkpoint**: Persisted work survives process replacement and cannot hot-loop or duplicate
accepted provider output.

## Phase 3: US1 — Provisional mixed-language tasks while speaking (P1)

**Independent test**: ML-01 produces three numbered provisional tasks while recording and
Inbox remains unchanged.

- [ ] T013 [US1] Add failing API tests for operation creation, audio upload, preview labels,
  fast-window scheduling, progressive proposals, polling projection, consent denial, and
  cross-owner nested IDs in `backend/tests/test_brain_dump_operations_api.py`.
- [ ] T014 [US1] Implement start/chunk/preview/GET/events contracts in
  `backend/app/schemas/tasks.py` and `backend/app/api/tasks.py`; route orchestration through
  `backend/app/workflows/voice_brain_dump/service.py`, not `TaskService` internals.
- [ ] T015 [US1] Implement fast-window scheduling and validated
  `TextReconcilerPort.extract_provisional` patch materialization in
  `backend/app/workflows/voice_brain_dump/service.py`; stable IDs and source audio spans must
  make T013 and PA-01/PA-09 pass.
- [ ] T016 [P] [US1] Add failing TypeScript API contract tests/types for schema-v2
  projection, audio chunks, preview segments, events, and polling in
  `frontend/src/api/taskTypes.ts` and `frontend/src/api/__tests__/client.test.ts`.
- [ ] T017 [US1] Implement client calls in `frontend/src/api/client.ts` and MediaRecorder
  original-audio capture/upload plus optional labelled Web Speech preview in
  `frontend/src/features/brain-dump/BrainDumpRoute.tsx` until T016 passes.
- [ ] T018 [US1] Add/extend failing UI tests in
  `frontend/src/features/brain-dump/BrainDumpRoute.test.tsx` for progressive stable-key
  numbered cards, RU/EN preview, offline/microphone/storage errors, pause/resume, and polling
  resume; implement the minimal recording UI behavior.

**Checkpoint**: Original audio is durable and provisional tasks are useful, but no native
Task can exist.

## Phase 4: US2 — Accurate original-audio reconciliation and safe Review (P1)

**Independent test**: ML-02 corrects from audio, ML-03 splits a run-on, ML-04 does not split
`купить хлеб и молоко`, and ML-06 surfaces a lock conflict.

- [ ] T019 [US2] Add failing API/service tests for
  `sealing -> fast_processing -> accurate_transcribing -> reconciling -> awaiting_confirmation`,
  accurate input media ref, segment supersession, and fast/accurate/reconciler fallbacks in
  `backend/tests/test_brain_dump_operations_api.py` and
  `backend/tests/test_voice_brain_dump_reconciliation.py`.
- [ ] T020 [US2] Implement seal scheduling and accurate-STT generation acceptance from
  `media_ref` in `backend/app/workflows/voice_brain_dump/service.py` and `runner.py`; reject
  missing spans/schema and never pass fast text as audio input.
- [ ] T021 [US2] Add failing pure patch tests for update identity, split, merge, remove,
  supersede, ordering, hidden history, stale-base rebase/reject, and provider retry ID reuse
  in `backend/tests/test_voice_brain_dump_reconciliation.py` (PA-02, PA-04–PA-08, PA-15,
  PA-16).
- [ ] T022 [US2] Implement validated patch materialization/projection in
  `backend/app/workflows/voice_brain_dump/service.py` and `domain.py` until T021 passes;
  array position must never identify a proposal.
- [ ] T023 [US2] Add failing lock/conflict/freeze tests for PA-03, PA-10, PA-14, ML-06 in
  `backend/tests/test_voice_brain_dump_reconciliation.py`; implement field-specific user
  patches and append-only conflict resolution in the workflow service/API.
- [ ] T024 [US2] Add failing UI tests for `Finishing upload`, `Improving transcript`,
  `Reconciling tasks`, Review-only-at-awaiting-confirmation, lineage-safe edit/delete, visible
  mine/suggestion conflict, and Save blocking in `BrainDumpRoute.test.tsx`.
- [ ] T025 [US2] Implement processing and Review projections/conflict controls in
  `frontend/src/features/brain-dump/BrainDumpRoute.tsx` and update
  `frontend/src/api/taskTypes.ts`/`client.ts` until T024 passes.
- [ ] T026 [US2] Add a deterministic evaluation runner/report test for ML-01–ML-06 metrics
  under `backend/tests/test_voice_brain_dump_reconciliation.py`; fail on wrong exact count,
  code-switched terms, or conjunction false split.

**Checkpoint**: Review is accurate or explicitly labelled provisional-only; user authority
and proposal history survive every model rerun.

## Phase 5: US3 — Resumable explicit exactly-once Inbox save (P1)

**Independent test**: Close/reopen with polling, retry bounded provider failure, resolve
conflicts, Save twice, reload/relogin, and observe one title-only Inbox task per selection.

- [ ] T027 [US3] Add failing native Task port tests for deterministic child keys and exact
  defaults (`inbox`, null details/project/due date, empty tags, `priority=none`) in
  `backend/tests/test_task_repository.py` and `test_brain_dump_operations_api.py` (CO-03,
  CO-04, CO-11).
- [ ] T028 [US3] Add the title-only idempotent command/source receipt to
  `backend/app/modules/tasks/service.py`, `domain.py`, and `repository.py`; expose it as a
  port to the workflow without permitting operation orchestration inside TaskService.
- [ ] T029 [US3] Implement conflict-free batch freeze and confirm in
  `backend/app/workflows/voice_brain_dump/service.py` and `backend/app/api/tasks.py`; persist
  per-action results and resume unresolved actions without duplicates.
- [ ] T030 [US3] Add failing UI tests for polling-only reopen, retry/provisional-only warning,
  conflict resolution, repeated Save, success count, and Inbox cache refresh in
  `BrainDumpRoute.test.tsx`; implement in `BrainDumpRoute.tsx`/`client.ts`.
- [ ] T031 [US3] Add v1 alias regression tests for `/transcript`, `/finish`, `/commit`, and
  direct proposal PATCH in `backend/tests/test_brain_dump_operations_api.py`; keep responses
  additive and old terminal operations immutable.

**Checkpoint**: The complete native Brain Dump loop is restart-safe and produces no inferred
metadata or duplicate tasks.

## Phase 6: Integrated quality, privacy, and release gates

- [ ] T032 Extend `frontend/tests/native-tasks-voice-brain-dump.compose.spec.ts` with the exact
  deterministic journey: provisional mixed-language list -> processing stages -> accurate
  correction/split/merge -> edit/delete/conflict -> explicit Save -> reload/relogin Inbox.
- [ ] T033 [P] Add redaction/retention/consent-withdrawal tests in
  `backend/tests/test_voice_brain_dump_repository.py` and API tests for PR-01–PR-06; inspect
  captured logs/events to prove no content leakage.
- [ ] T034 [P] Add architecture/import test proving the workflow does not import task
  repositories and Weekly Review has no second voice engine.
- [ ] T035 Run focused backend tests, full `make ci-backend`, frontend focused tests,
  `make ci-frontend`, `make test-e2e`, and `python3 scripts/check_spec_kit_specs.py`; record
  real counts/results in the PR, using direct Python commands only if `make` is unavailable.
- [ ] T036 Run the versioned multilingual evaluation and attach its aggregate metrics (no raw
  user content) to the PR; block release on SC-001–SC-005 or any safety invariant failure.
- [ ] T037 Update `.env.example` and operator docs only for selected role/timeout/retention
  configuration; document provider-disabled behavior and consent without secrets.
- [ ] T038 Hand the immutable PR head to independent Product QA and AI-QA; after approval and
  green exact-head CI, merge through the normal path, verify main CI/automatic Fly deploy,
  and run authenticated production-safe smoke without paid provider calls.

## Dependencies and parallel opportunities

- T001–T006 establish contracts and deterministic fixtures; T007–T012 block all user stories.
- US1 is the first vertical slice and blocks US2 because accurate reconciliation consumes its
  durable audio and proposal projection.
- US2 blocks US3 freeze/confirm because conflict-free stable lineage is the batch input.
- Tasks marked `[P]` touch distinct files or test surfaces and may run in parallel after their
  phase dependency, but every implementation follows its failing test.
- T032–T038 run only after US1–US3 pass independently.
