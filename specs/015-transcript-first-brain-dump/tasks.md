# Tasks: Transcript-first voice brain dump

<!--
  BrainBuddy override: delivery gates. Upstream treats tasks.md as an
  execution script; here it is portable planning input that never bypasses
  isolated worktrees, tests-before-implementation, independent acceptance,
  ADR-0008 landing classification, or CI. Those gates are restated below and
  must survive any upstream refresh.
-->

**Feature**: `specs/015-transcript-first-brain-dump/` · **Branch**: `claude/brain-dump-mechanics-t35ab7` (PR #194, head `5ffff8531e7fa814f1f50a86ab78bb10badf7ef6`) · **Plan**: [plan.md](plan.md) · **Spec**: [spec.md](spec.md) · **Design**: [design.md](design.md) · **Written**: 2026-09-05

**Input**: Design documents from `/specs/015-transcript-first-brain-dump/` — `plan.md` (Architecture as built A1–A6, work items W-01/W-02, test strategy), `spec.md` (US1–US4, FR-001…FR-011, SC-001…SC-007), `design.md` (D-01…D-05, M-01…M-03 with state ids), `research.md` (R-01…R-13), `data-model.md`, `contracts/brain-dump-operations.md`, `quickstart.md`.

**Prerequisites**: plan.md (required), spec.md (required for user stories), design.md (required when the feature has a user-visible surface), research.md, data-model.md, contracts/ — all present in this directory.

**Kind**: **retro task list.** The implementation already landed on this branch; this file decomposes it by independently testable user story so `/speckit-analyze`, `/speckit-accept` and `/speckit-report` can map onto real files, commits and named tests. A task is ticked `- [x]` only where the description names the landed commit(s) (`git log --oneline main..HEAD`) **and** the test(s) that prove it — by file and test name, with the `015-FR-…`/`015-SC-…` id the test carries. A docs task names the commit and the grep-able heading it added; a verification task names the run or command and its recorded result. A task is left `- [ ]` only where the work is genuinely not done on the branch; each such task says why and who owns it.

**Delivery gates** (non-negotiable, regardless of who executes these tasks):
isolated worktree and feature branch; failing test written and observed failing
before the implementation that satisfies it; Allure taxonomy on every product
test with the covering feature-qualified id (`NNN-FR-###`/`NNN-SC-###`) in
the test name or story; acceptance
graded by an agent that did not write the code; landing class decided by
`scripts/classify_path_risk.py`, with SHIP and SHOW landing PR-less through
verified trunk and ASK-class changes never landing automatically — a PR carries
their review evidence, but merging it does not by itself update `main` (ADR-0008;
see `AGENTS.md` and `docs/autonomous-delivery-runbook.md` for the recorded
approval and ruleset requirements).

Before freeze, the implementation writer MUST produce a typed receipt using
`.specify/templates/pre-freeze-receipt.schema.json` and run
`python3 scripts/validate_pre_freeze_receipt.py <receipt> --sha <full-lowercase-sha>`.
<!-- BrainBuddy pre-freeze receipt contract: tasks. Preserve this section. -->
The receipt covers only writer-owned pre-freeze gates. Independent review, QA,
CI, landing, deploy, and production smoke remain post-freeze obligations under
ADR-0008 and must never be represented as writer PASS evidence.

**Tests**: Tests are expected for behavior changes; this feature carries backend pytest/FastAPI `TestClient`, frontend Vitest/Testing Library, Compose Playwright and mobile Jest tests, all under the Allure taxonomy. Retro caveat, stated in `plan.md` (Constitution Check): the PR #194 tests of commits `12814a7`, `252fa01`, `50369bc`, `051cec1`, `a1f0d2e` and `9f9ae3b` were written together with the fix rather than observed failing first; W-01 (`fc6d13b`) and W-02 (`43ae843`) followed failing-then-passing on the branch.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story. Consent enforcement (T028, T029), mobile/resilience handling (T022, T035, T042, T043), observability (T011, T034, T044), release/smoke validation (T046–T048) and data-safety safeguards (T040–T043) are placed in the story that owns them.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4)
- Exact file paths in every description; landed commit(s) and proving test(s) after the em dash

## Path Conventions

Web app + mobile inside the ADR-0001 modular monolith, as laid out in `plan.md` → Project Structure: `backend/app/` (`api/`, `schemas/`, `workflows/voice_brain_dump/`), `backend/tests/`, `frontend/src/` (`api/`, `features/brain-dump/`, `utils/`), `frontend/tests/` (Compose Playwright), `mobile/src/` (`api/`, `braindump/`, `app/brain-dump/`), `docs/decisions/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: The architecture record, the schema-first contract and the test scaffolding every story below relies on.

- [x] T001 Record the architecture change as two dated ADR-0002 amendments in `docs/decisions/0002-async-voice-operation-substrate.md` ("2026-09-05 amendment: browser preview is a transcript readout, not a task source"; "2026-09-05, same day: `reconcile_preview` — owner-chosen recovery from preview text") and mark §7.1 of `docs/vnext-cloud-design-build-contract.md` superseded — landed `12814a7`, `252fa01` (first amendment, refined), `9f9ae3b` (second amendment), `051cec1` (contract wording for the two-step exits); docs carry no executable test — the headings are grep-able at `docs/decisions/0002-async-voice-operation-substrate.md` lines 10 and 61 and the "Superseded on 2026-09-05 (ADR-0002 amendment)" note in the contract.
- [x] T002 [P] Ship the additive contract schema-first: `BrainDumpRecoveryAction` gains `"reconcile_preview"` and `provider_runs[].checkpoint` gains `"preview_transcribed"`/`"preview_reconciled"` in `backend/app/schemas/tasks.py`; `BrainDumpProviderRunCheckpoint` and `ReconcilerSourceCheckpoint` in `backend/app/workflows/voice_brain_dump/domain.py`; then the client mirrors `frontend/src/api/taskTypes.ts` (`available_recovery_actions`), `frontend/src/api/client.ts` (`commandBrainDump` action union) and `mobile/src/api/types.ts` (`BrainDumpAction`, `available_recovery_actions`) — landed `a1f0d2e` (mobile types), `9f9ae3b` (backend and web); proven by `backend/tests/test_brain_dump_operations_api.py::test_015_FR_009_reconcile_preview_recovers_provisional_tasks_from_browser_preview_text` (015-FR-009 015-SC-006: the projection advertises `reconcile_preview`), `frontend/src/features/brain-dump/BrainDumpRoute.test.tsx` "015-FR-009 015-FR-010 015-SC-006 015-SC-007 extracts tasks from the browser transcript when the server offers reconcile_preview" and `mobile/src/app/brain-dump/__tests__/review.test.tsx` "015-FR-009 015-FR-010 015-SC-006 015-SC-007 posts reconcile_preview with the current revision, waits out reconciling, and reviews the provisional tasks".
- [x] T003 [P] Put the test scaffolding in place: the shared `seed_provisional_proposals` helper in `backend/tests/conftest.py` so every legacy/seeded-proposal test seeds its proposals explicitly instead of relying on preview-derived drafts, and the feature-qualified `015-FR-…`/`015-SC-…` ids on the product tests of all four runners (`backend/tests/`, `frontend/src/features/brain-dump/BrainDumpRoute.test.tsx`, `frontend/tests/native-tasks-voice-brain-dump.compose.spec.ts`, `mobile/src/app/brain-dump/__tests__/review.test.tsx`) — landed `252fa01` (helper), `9f9ae3b` (ids applied across the runners), `43ae843` and `fc6d13b` (ids on the W-02/W-01 tests); proven by `python3 scripts/check_requirement_coverage.py specs/015-transcript-first-brain-dump` → `Requirement coverage passed: 18/18 traced` (run 2026-09-05 on `5ffff85`).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The root-cause fix every story depends on — the preview lane stops minting proposals — and the guarantee that the rules for proposals that already exist did not move.

**⚠️ CRITICAL**: US1 cannot be clean while the preview lane still mints a card per fragment; US3 cannot exist while preview-derived drafts still offer a fallback.

- [x] T004 Make `append_brain_dump_transcript` in `backend/app/workflows/voice_brain_dump/service.py` persist `BrainDumpTranscriptSegmentDocument`s only: remove the heuristic preview extractor and the `fast` provider run, never produce `wording_changing`, keep `interim` upsert-by-`sequence` and the 409 on a changed `stable` segment, and stop pushing `fast_processing` into `status_history` at seal (FR-002, data-model §6 invariant 1) — landed `12814a7`, `252fa01`; proven by `backend/tests/test_brain_dump_operations_api.py::test_transcript_append_records_segments_without_deriving_draft_tasks` (015-FR-002 015-SC-002) and `::test_brain_dump_interim_and_final_segments_persist_without_draft_tasks` (015-FR-002).
- [x] T005 Keep today's rules for proposals that already exist (FR-002 second sentence, FR-011): `commit_brain_dump_operation` in `backend/app/workflows/voice_brain_dump/service.py` still refuses an untouched `provisional` proposal outside a provisional review with `BRAIN_DUMP_PROPOSAL_NOT_RECONCILED`, and owner locks, deletions and split lineage survive accurate reconciliation; the affected tests now seed their proposals through T003's helper — landed `12814a7`, `252fa01`; proven by `backend/tests/test_brain_dump_operations_api.py::test_commit_rejects_an_untouched_fast_proposal_after_a_successful_reconcile` (015-FR-011), `::test_accurate_reconciliation_preserves_unmatched_locked_and_deleted_proposals` (015-FR-002 015-FR-011), `::test_schema_v2_user_title_lock_blocks_accurate_overwrite_with_visible_conflict` (015-FR-002 015-FR-011) and `::test_schema_v2_accurate_reconciliation_persists_split_lineage` (015-FR-002 015-FR-011).

**Checkpoint**: Preview text is transcript only and legacy operations behave as before — the user stories can be judged on their own.

---

## Phase 3: User Story 1 - Clean next actions from a natural dump (Priority: P1) 🎯 MVP

**Goal**: The reference utterance «Так, надо купить молоко. Сходить в магазин. Покрасить комнату.» yields exactly three verb-first next actions in the language spoken, saveable immediately with zero manual cleanup (FR-003, FR-004, FR-005 first sentence; SC-001).

**Independent Test**: Record or replay the reference utterance on a consented recording, press Stop, compare the review list against the three expected titles, press Save without editing and count three Inbox tasks — `spec.md` US1. Automated equivalent: `cd backend && pytest tests/test_voice_brain_dump_reconciliation.py tests/test_brain_dump_operations_api.py -q` plus the two Compose journeys named in T012.

### Tests for User Story 1

- [x] T006 [P] [US1] Adapter tests for the v3 prompt and language-faithful, GTD-phrased titles in `backend/tests/test_voice_brain_dump_reconciliation.py`: `::test_openai_reconciler_v3_prompt_locks_language_gtd_phrasing_and_template` (015-FR-003), `::test_openai_reconciler_grounds_self_corrected_utterances` (015-FR-003), `::test_language_faithful_invariant_drops_translated_title_even_if_grounding_accepts` (015-FR-003), `::test_language_faithful_invariant_accepts_mixed_code_switched_title` (015-FR-003), `::test_gtd_rephrased_titles_ground_against_filler_prefixed_utterances` (015-FR-003) — landed `12814a7`, `252fa01`.
- [x] T007 [P] [US1] Guard tests that hold independently of the model in `backend/tests/test_voice_brain_dump_reconciliation.py`: `::test_filler_only_titles_are_dropped_without_failing_their_siblings` (015-FR-004), `::test_duplicate_titles_within_one_reconciliation_collapse_to_one_proposal` (015-FR-004), `::test_duplicate_from_another_segment_folds_its_provenance_into_the_survivor` (015-FR-004), `::test_structural_duplicate_folds_its_predecessors_into_the_surviving_proposal` (015-FR-004), `::test_add_matching_an_active_proposal_affirms_it_instead_of_minting_a_twin` (015-FR-004), `::test_user_deleted_proposal_cannot_be_restored_under_a_punctuation_variant` (015-FR-004), `::test_envelope_made_only_of_fillers_fails_closed_as_ungrounded` (015-FR-004 015-SC-003) — landed `12814a7`, `252fa01`, `9f9ae3b` (structural fold).
- [x] T008 [P] [US1] HTTP journey for the founder's scenario in `backend/tests/test_brain_dump_operations_api.py::test_seal_reconciles_a_filler_prefixed_dump_into_clean_next_actions` (015-FR-004 015-FR-005 015-SC-001: the review list is GTD next actions, never raw preview text, `committable` true with nothing deleted), with `::test_provider_failure_redacts_sensitive_values_from_logs_and_run_envelope` asserting through `caplog` that no transcript or title text reaches the log (FR-004 second sentence, no 015 id) — landed `12814a7` (journey), redaction test pre-existing and kept green.

### Implementation for User Story 1

- [x] T009 [US1] Reconciler prompt v3 in `backend/app/workflows/voice_brain_dump/adapters/reconciler.py`: `OpenAITextReconciler.template_version = "brain-dump-reconciler-v3"` — verb first, the language spoken, discourse fillers and modal scaffolding dropped, one proposal per distinct action; the version string is persisted on the succeeded run and copied into each action receipt (FR-003) — landed `12814a7`; proven by T006 (`::test_openai_reconciler_v3_prompt_locks_language_gtd_phrasing_and_template`).
- [x] T010 [US1] Server-side guards in `backend/app/workflows/voice_brain_dump/adapters/reconciler.py` — `_validate_draft` with `_DISCOURSE_FILLER_TERMS` and `_SemanticGroundingFailure` (a filler-only title is dropped on its own; protocol defects fail the whole call), `_dedupe_draft`, `_fold_duplicate` (union of cited segments and predecessors; a structural duplicate folds its predecessors into the survivor), `_titles_equivalent`, an `add` restating an active proposal rewritten as an affirming `update`, and the tombstone check keyed on the shared `normalized_title` in `backend/app/workflows/voice_brain_dump/domain.py` (FR-004) — landed `12814a7`, `252fa01`, `9f9ae3b`; proven by T007.
- [x] T011 [US1] Service side of the single mint in `backend/app/workflows/voice_brain_dump/service.py`: `_reconcile_accurate_checkpoint(source_checkpoint="accurate_transcribed")` sends the current proposals (empty for a new operation), applies the returned patches, logs `brain_dump_reconciler_dropped_operations operation_id=… dropped=… reasons=…` by count and fixed reason only, and freezes the run at `checkpoint="reconciled"` with `reconciliation_quality="accurate"` (FR-003, FR-004 second sentence) — landed `12814a7`, `252fa01`; proven by T008 (`::test_seal_reconciles_a_filler_prefixed_dump_into_clean_next_actions`, `::test_provider_failure_redacts_sensitive_values_from_logs_and_run_envelope`).
- [x] T012 [US1] Web review of the clean result in `frontend/src/features/brain-dump/BrainDumpRoute.tsx` (`ReviewSurface`, D-03.a–c, D-03.j, D-03.k): one card per next action with its cited utterances, Send enabled with nothing deleted, "Sending…" while committing, the saved panel with the count — landed `12814a7`, `50369bc` (the Compose assertion follows the settled-line readout); proven by `frontend/tests/native-tasks-voice-brain-dump.compose.spec.ts` "015-FR-001 015-SC-002 Voice Brain Dump shows a live transcript, reviews the reconciled task and saves exactly one Inbox task" and "015-FR-001 015-FR-003 015-FR-005 015-FR-007 015-SC-002 Voice Brain Dump shows a mixed-language preview as transcript and reviews only reconciled next actions".

**Checkpoint**: The reference dump goes from 9 review entries with 6 deletions to exactly 3 saveable next actions with 0 (SC-001).

---

## Phase 4: User Story 2 - Raw text is a status, never a task (Priority: P2)

**Goal**: While speaking, the screen shows what was heard as a transcript readout — the forming hypothesis beside the microphone, settled utterances in a region named as the transcript — and no task card exists before Stop; processing shows the stage and the transcript so far; a review with nothing actionable says so, shows what was heard and cannot be saved (FR-001, FR-002 web half, FR-005 empty review, FR-006 stage-and-transcript clause; SC-002, SC-003).

**Independent Test**: Start a recording in a browser with speech preview, speak several utterances and assert no task card renders before Stop while the readout fills; then process a filler-only dump and assert the review offers no Save — `spec.md` US2. Automated equivalent: `cd frontend && npx vitest run src/features/brain-dump/BrainDumpRoute.test.tsx`, `cd mobile && npx jest src/app/brain-dump/__tests__/review.test.tsx`, and the `015-FR-005 015-SC-003` backend case.

### Tests for User Story 2

- [x] T013 [P] [US2] Recording-surface tests in `frontend/src/features/brain-dump/BrainDumpRoute.test.tsx`: "015-FR-001 015-SC-002 records through browser microphone and shows the running transcript instead of draft task cards", "015-FR-001 replaces an interim speech result with the cumulative final transcript sequence", "015-FR-001 keeps the subtitle static and labels the readout as browser preview while recording" — landed `12814a7`, `252fa01`.
- [x] T014 [P] [US2] Processing-surface tests in `frontend/src/features/brain-dump/BrainDumpRoute.test.tsx`: "015-FR-006 shows schema-v2 processing stages before editable review", "015-FR-006 shows the accurate transcript, not draft cards, while schema-v2 processing continues", "015-FR-006 falls back to the browser preview transcript while accurate transcription is pending", "015-FR-006 keeps the transcript readout neutral while processing has no preview yet" — landed `12814a7`, `252fa01`.
- [x] T015 [P] [US2] Empty-review and cold-open tests on every runner: `backend/tests/test_brain_dump_operations_api.py::test_review_with_no_surviving_proposals_is_not_committable` (015-FR-005 015-SC-003; `committable=false` and `commit` refused) — `252fa01`; `frontend/src/features/brain-dump/BrainDumpRoute.test.tsx` "015-FR-005 015-SC-003 keeps empty review commands as no-ops until an operation exists", "015-FR-005 tells an empty review that discarding is the way back to recording, without promising a record-again control" (`fc6d13b`), with the supporting "shows a loading state while a persisted operation is being fetched" and "reports load failures when an existing brain dump cannot be resumed" (`252fa01`, D-05.a/D-05.b, no 015 id); `mobile/src/app/brain-dump/__tests__/review.test.tsx` "015-FR-005 says nothing was proposed, shows what was heard, and offers no confirm on an empty review" and "015-FR-005 says when no transcript was captured for an empty review" plus `mobile/src/braindump/__tests__/machine.test.ts` `describe("heardTranscript")` — `43ae843`.
- [x] T016 [P] [US2] Browser journey and partial-failure tests: `frontend/tests/native-tasks-voice-brain-dump.compose.spec.ts` "015-FR-001 015-SC-002 Voice Brain Dump shows a live transcript, reviews the reconciled task and saves exactly one Inbox task" (the interim hypothesis is asserted as the live tail and the settled line lands in the "What you've said" region exactly once) — `12814a7`, `50369bc`; `frontend/src/features/brain-dump/BrainDumpRoute.test.tsx` "015-FR-002 reports a refused audio chunk with the server's reason while capture keeps running" (D-01.j) — `fc6d13b`.

### Implementation for User Story 2

- [x] T017 [US2] Recording surface as a transcript readout in `frontend/src/features/brain-dump/BrainDumpRoute.tsx` (`RecordingSurface`, `TranscriptReadout` under "What you've said · browser preview" listing settled, non-superseded segments once each and announcing newly settled ones, `TranscriptTail` for the forming hypothesis beside the microphone, no proposal card mounted while the status is `recording` or `paused`, upload and append failures as banners while capture keeps running — D-01.a–d, D-01.h–j; FR-001, SC-002) — landed `12814a7`, `252fa01` (readout region, tail split, announcements), `fc6d13b` (banner shows the server's reason); proven by T013 and T016.
- [x] T018 [US2] Processing surface in `frontend/src/features/brain-dump/BrainDumpRoute.tsx` (`ProcessingSurface`: the stage from `operationStatusLabels[status]`, the readout under "Browser preview · provisional" then "Accurate transcript" as accurate segments supersede preview ones, an empty dashed readout when no settled preview exists, no task cards, the 1.5 s → 8 s poll over `processingStatuses` plus `retryable_error` — D-02.a–d, D-02.g; FR-006 stage-and-transcript clause, FR-010) with the shared status map `frontend/src/features/brain-dump/brainDumpStatusLabels.ts` (`operationStatusLabels`, `processingStatuses`) also consumed by `frontend/src/features/brain-dump/BrainDumpPrivacyControls.tsx` — landed `12814a7`, `252fa01`; proven by T014.
- [x] T019 [US2] Commit gate for an empty review in `backend/app/workflows/voice_brain_dump/service.py` (`brain_dump_operation_is_committable` requires at least one non-deleted proposal; data-model §6 invariant 4) surfaced as `committable=false` by `_to_brain_dump_response` in `backend/app/api/tasks.py` (FR-005, SC-003) — landed `252fa01`; proven by T015 (`::test_review_with_no_surviving_proposals_is_not_committable`).
- [x] T020 [US2] Web empty review in `frontend/src/features/brain-dump/BrainDumpRoute.tsx` (`ReviewSurface` with `proposals.length === 0`: heading "No tasks to review", the status box "Nothing actionable came out of this dump", the transcript of what was heard or "No transcript was captured for this recording.", **no Send button mounted**, copy "No tasks were proposed from this dump. Here is what was heard; discard it to record again." naming the exit the screen has — D-03.h, D-03.i; FR-004, FR-005, SC-003) — landed `252fa01` (empty state), `fc6d13b` (W-01 copy); proven by T015.
- [x] T021 [US2] Cold-open loading state in `frontend/src/features/brain-dump/BrainDumpRoute.tsx` ("Loading your brain dump" until the projection arrives; a failed fetch falls through to the recording surface carrying "Could not resume brain dump." — D-05.a, D-05.b; FR-008 poll/resume half) — landed `252fa01`; proven by T015's supporting Vitest cases.
- [x] T022 [US2] Mobile empty review (W-02, M-02.e) in `mobile/src/app/brain-dump/[operationId].tsx` and `mobile/src/braindump/machine.ts`: `heardTranscript(segments)` returns the stable, non-superseded segments for the "What was heard" list, `canCommit` requires `visibleProposals(operation).length > 0`, the heading reads "No tasks to review", the card says nothing was proposed and names the discard exit, and the confirm control is absent rather than disabled (FR-005, SC-003) — landed `43ae843`; proven by T015's mobile cases.

**Checkpoint**: 0 task cards before Stop in every recording (SC-002); 0 filler-only reviews offer Save on web or mobile (SC-003).

---

## Phase 5: User Story 3 - Recover a failed recording from the browser transcript (Priority: P3)

**Goal**: After a terminal failure with no surviving task and stable browser-preview text present, the owner may explicitly run one consent- and cost-bounded extraction over that text; the result opens the normal review labelled provisional on web and mobile and saves as provisional; refusals state their reason and reference id (FR-009, FR-010; SC-006, SC-007).

**Independent Test**: Force a terminal failure on a recording holding browser-transcript text; assert the action is offered exactly once, absent after consent withdrawal or over the spend ceiling, and that the resulting review and saved tasks are marked provisional on web and mobile — `spec.md` US3. Automated equivalent: `cd backend && pytest tests/test_voice_brain_dump_recovery.py -q` plus the `015-FR-009` Vitest and Jest cases.

### Tests for User Story 3

- [x] T023 [P] [US3] Service tests in `backend/tests/test_voice_brain_dump_recovery.py`: `::test_015_FR_009_preview_recovery_predicate_requires_every_clause` (state, one shot, consent, cost), `::test_015_FR_009_reconcile_preview_queues_one_provisional_reconciler_run` (pending run at `preview_transcribed`, `runner_wake`, idempotent replay, stale revision), `::test_015_FR_009_runner_reconciles_exactly_the_stable_unsuperseded_preview_text` (`provisional_only` at `preview_reconciled`), `::test_015_FR_009_preview_recovery_commit_creates_inbox_tasks_with_provisional_receipts` — landed `9f9ae3b`.
- [x] T024 [P] [US3] HTTP journey and one-shot tests in `backend/tests/test_brain_dump_operations_api.py`: `::test_015_FR_009_reconcile_preview_recovers_provisional_tasks_from_browser_preview_text` (015-FR-009 015-SC-006: terminal STT failure → `reconcile_preview` → provisional review in one action plus processing) and `::test_reconcile_preview_terminal_failure_leaves_only_cancel` (the run stays labelled preview and only `cancel` is advertised afterwards; no 015 id) — landed `9f9ae3b`.
- [x] T025 [P] [US3] Web tests in `frontend/src/features/brain-dump/BrainDumpRoute.test.tsx`: "015-FR-009 015-FR-010 015-SC-006 015-SC-007 extracts tasks from the browser transcript when the server offers reconcile_preview", "015-FR-010 015-SC-007 labels provisional review truthfully and lets its owner delete retained raw audio", "015-FR-010 015-SC-007 enables Save for an explicitly reviewed provisional operation" — `9f9ae3b`; "015-FR-009 shows the server's refusal and its reference, not the HTTP status, when reconcile_preview is refused" — `fc6d13b`.
- [x] T026 [P] [US3] Mobile tests in `mobile/src/app/brain-dump/__tests__/review.test.tsx`: "015-FR-009 offers to extract tasks from the browser transcript when the server advertises it", "015-FR-009 015-FR-010 015-SC-006 015-SC-007 posts reconcile_preview with the current revision, waits out reconciling, and reviews the provisional tasks", "015-FR-010 015-SC-007 warns when only provisional wording was available", "015-FR-010 015-SC-007 keeps the provisional warning up while the dump is not yet committable" — landed `a1f0d2e`, ids `9f9ae3b`.

### Implementation for User Story 3

- [x] T027 [US3] Recovery input and checkpoints in `backend/app/workflows/voice_brain_dump/domain.py`: `browser_preview_recovery_hypotheses(segments)` (stable, `browser_preview`, unsuperseded, non-blank, `end_ms > start_ms`, in audio order) and the `preview_transcribed`/`preview_reconciled` literals kept distinct from the accurate lane (data-model §2, §3) — landed `9f9ae3b`; proven by T023 (`::test_015_FR_009_runner_reconciles_exactly_the_stable_unsuperseded_preview_text`).
- [x] T028 [US3] Recovery predicate in `backend/app/workflows/voice_brain_dump/service.py`: `_preview_recovery_state_eligible` (terminal failure of `accurate_stt`/`reconciler`, no live proposal, no `preview_*` run anywhere, hypotheses non-empty), `_preview_recovery_consent_refusal` (`RECONCILER_CONSENT_REQUIRED` after withdrawal or without consent, `RECONCILER_CONSENT_PROVIDER_MISMATCH`), `_preview_recovery_within_cost_cap` (`provider_cost_budget_allows` against the reconciler cap and the cumulative cap), composed by `can_reconcile_brain_dump_preview` and `VoiceBrainDumpService.can_reconcile_preview` (FR-009 one shot, consent, ceilings; contracts §2.1) — landed `9f9ae3b`; proven by T023 (`::test_015_FR_009_preview_recovery_predicate_requires_every_clause`).
- [x] T029 [US3] Command `reconcile_brain_dump_preview` in `backend/app/workflows/voice_brain_dump/service.py`: under `command_lock(owner_id)` with idempotency replay and `_assert_revision`, refuses with `BRAIN_DUMP_PREVIEW_RECOVERY_UNAVAILABLE` / consent codes / `OPERATION_COST_BUDGET_EXCEEDED` before any external call, else appends a `pending` `reconciler` run at `preview_transcribed` (`attempt=1`, `recovery_count=0`, reservation = reconciler cap, `input_hash` of the joined stable text), moves to `reconciling` and calls `runner_wake()`; no audio read, no STT (FR-009) — landed `9f9ae3b`; proven by T023 (`::test_015_FR_009_reconcile_preview_queues_one_provisional_reconciler_run`) and T024.
- [x] T030 [US3] Runner and retry in `backend/app/workflows/voice_brain_dump/service.py`: `run_due_brain_dump_provider_runs` dispatches a claimed reconciler run at `preview_transcribed` to `_reconcile_claimed_preview_run`, which hands exactly the hypotheses to `_reconcile_accurate_checkpoint(source_checkpoint="preview_transcribed")`; success writes `reconciliation_quality="provisional_only"`, `manual_review=True` and freezes at `preview_reconciled`, never `reconciled`; `retry_brain_dump_operation` detects `resume_preview` and re-queues over the persisted text without `sealed_manifest_hash`, bounded by `max_operation_recoveries` → `OPERATION_RECOVERY_BUDGET_EXHAUSTED` (data-model §6 invariants 2, 3) — landed `9f9ae3b`; proven by T023 (runner test) and T024 (`::test_reconcile_preview_terminal_failure_leaves_only_cancel`).
- [x] T031 [US3] Provisional receipts in `backend/app/workflows/voice_brain_dump/service.py`: `_action_receipt` names the last succeeded reconciler run at `reconciled` **or** `preview_reconciled` and copies `reconciliation_quality` from the operation, so tasks saved from a recovery carry `provisional_only` plus provider, model and `template_version` (FR-010, data-model §5) — landed `9f9ae3b`; proven by T023 (`::test_015_FR_009_preview_recovery_commit_creates_inbox_tasks_with_provisional_receipts`).
- [x] T032 [US3] API projection and command route in `backend/app/api/tasks.py`: `_brain_dump_available_recovery_actions` emits `retry`, `review_provisional`, `reconcile_preview` (via `service.can_reconcile_preview`) and `cancel` in render order; the catch-all `POST /api/brain-dump-operations/{operation_id}/{action}` accepts `reconcile_preview`, deliberately outside `_VOICE_OFF_REACHABLE_ACTIONS` so the flag-OFF answer stays 404 like every other forward action (contracts §2, §3.1) — landed `9f9ae3b`; proven by T024.
- [x] T033 [US3] Web recovery surface and provisional banner in `frontend/src/features/brain-dump/BrainDumpRoute.tsx` (`RecoverySurface` renders exactly the advertised actions; "Extract tasks from the browser transcript" with the helper sentence naming the destination bound by `aria-describedby`; absence once spent, withdrawn or over the ceiling — D-04.d, D-04.e; `ReviewSurface` shows the amber provisional banner whenever `reconciliation_quality === "provisional_only"`, adding the not-saveable sentence while `committable` is false — D-03.d, D-03.e; FR-009, FR-010, SC-006, SC-007) — landed `9f9ae3b`; proven by T025.
- [x] T034 [US3] W-01 error banners in `frontend/src/features/brain-dump/BrainDumpRoute.tsx`: `describeError` renders the server's `message` (which starts with the fixed refusal code) or `detail` through `getErrorContext` from `frontend/src/utils/error.ts` and appends the `X-Correlation-ID` as "Ref: <id>" on every web brain-dump banner (D-01.j, D-02.e, D-03.m, D-04.g, D-05.b) instead of the bare HTTP status text (FR-009 last sentence) — landed `fc6d13b`; proven by T025 ("015-FR-009 shows the server's refusal and its reference, not the HTTP status, when reconcile_preview is refused") and T016 ("015-FR-002 reports a refused audio chunk with the server's reason while capture keeps running").
- [x] T035 [US3] Mobile recovery and badge in `mobile/src/app/brain-dump/[operationId].tsx`: the failure card renders exactly the server-advertised actions including "Extract tasks from the browser transcript" with the same helper sentence (M-01.c, M-01.d), `runCommand` accepts `reconcile_preview`, posts it with the current revision and a fresh idempotency key and polls `reconciling` until the provisional review opens; the fallback failure copy no longer enumerates recoveries the server may not offer; the "Provisional only —" badge shows for `provisional_only` whether or not the result can be saved (M-02.b, M-02.c); refusals render in `ErrorBanner` with `ref: <id>` (M-01.e) — landed `a1f0d2e`; proven by T026.

**Checkpoint**: From a terminal failure with preview text, one action plus processing time reaches a provisional review (SC-006); the provisional label shows in 100% of provisional reviews on both clients (SC-007).

---

## Phase 6: User Story 4 - Safe destructive exits and faithful resume (Priority: P4)

**Goal**: Every destructive exit — discard a recording, discard all reviewed tasks, delete a failed recording, cancel processing (web); discard everything, discard all, the review header's discard control (mobile) — asks once with the safe choice focused or listed first, and Escape or the safe choice leaves everything as it was; a reopened in-progress recording restores the last utterance and a timer continuing from the captured duration (FR-006 "Cancel processing" clause, FR-007, FR-008; SC-004, SC-005).

**Independent Test**: Trigger each destructive exit and assert a confirmation with focus on the safe choice, that Escape and the safe choice leave the recording unchanged and only the explicit confirm destroys; reload mid-recording and assert the last utterance and the timer on first render — `spec.md` US4. Automated equivalent: the `015-FR-007`/`015-FR-008` Vitest and Jest cases and the Compose failure journey named in T038.

### Tests for User Story 4

- [x] T036 [P] [US4] Web confirmation tests in `frontend/src/features/brain-dump/BrainDumpRoute.test.tsx`: "015-FR-007 015-SC-004 asks before discarding a recording and starts the question on Keep recording", "015-FR-007 closes the discard question on Escape without cancelling and returns focus to Discard", "015-FR-007 015-SC-004 asks before discarding all reviewed tasks and keeps reviewing when declined", "015-FR-007 015-SC-004 asks before deleting a failed recording and keeps it when declined", "015-FR-007 deletes a failed recording permanently after confirmation and returns to a fresh recording screen", "015-FR-006 015-FR-007 015-SC-004 lets the user cancel processing after confirming and returns to a fresh recording screen", "015-FR-007 015-SC-004 keeps processing when the cancel question is declined" — landed `051cec1`.
- [x] T037 [P] [US4] Web resume tests in `frontend/src/features/brain-dump/BrainDumpRoute.test.tsx`: "015-FR-008 015-SC-005 seeds the live tail and the timer from a resumed recording", "015-FR-008 seeds the tail from the latest utterance nothing supersedes and never overwrites a live one", "015-FR-008 starts the capture timer at zero for a recording begun in this session" — landed `051cec1`.
- [x] T038 [P] [US4] Browser failure journey in `frontend/tests/native-tasks-voice-brain-dump.compose.spec.ts`: "015-FR-007 Voice Brain Dump failures are visible and preserve recoverable live sessions" (step "015-FR-007 failed transcript, pause, finish, cancel and commit preserve drafts with visible errors": a refused cancel closes the question and reports through the alert — D-03.m) and the step "015-FR-007 discarding the review is confirmed inline and cancels the operation" inside the mixed-language journey — landed `051cec1`.
- [x] T039 [P] [US4] Mobile confirmation tests in `mobile/src/app/brain-dump/__tests__/review.test.tsx`: "015-FR-007 015-SC-004 asks before discarding all from the review sheet and cancels only once confirmed", "015-FR-007 keeps reviewing, with nothing posted, when the safe answer is chosen", "015-FR-007 015-SC-004 names the header control as a discard and asks before cancelling from it" (asserts the old "Close" name is gone), "015-FR-007 015-SC-004 asks before discarding a failed recording and cancels only once confirmed" — landed `43ae843`.

### Implementation for User Story 4

- [x] T040 [US4] `DestructiveConfirm` in `frontend/src/features/brain-dump/BrainDumpRoute.tsx`: replaces its trigger in place with the question, focuses the safe answer on open, closes on Escape (`preventDefault` and `stopPropagation`, so the overlay does not also dismiss) restoring focus to the trigger, and only the destructive answer calls `onConfirm`, after which the question closes so a stale-revision failure reports in the surface's alert; used four times — Discard on D-01 (D-01.g), "Cancel processing" on D-02 (D-02.f), "Discard all" on D-03 (D-03.l), "Delete recording" on D-04 (D-04.f) — all running the idempotent `cancel` command, whose server side (contracts §2: a repeated `cancel` keeps `completed`/`cancelled` and never touches saved Inbox tasks) is pre-existing ADR-0002 behaviour (FR-007, SC-004 web 4 of 4) — landed `051cec1`; proven by T036 and T038.
- [x] T041 [US4] "Cancel processing" on the processing screen in `frontend/src/features/brain-dump/BrainDumpRoute.tsx` (`ProcessingSurface` offers the confirmed exit while the server advances; processing continues undisturbed while the question is open; the post-cancel reset shares the React Router transition so URL and cleared operation commit together — D-02.f; FR-006 second clause) — landed `051cec1`; proven by T036 ("015-FR-006 015-FR-007 015-SC-004 lets the user cancel processing after confirming…", "015-FR-007 015-SC-004 keeps processing when the cancel question is declined").
- [x] T042 [US4] Resume seeding in `frontend/src/features/brain-dump/BrainDumpRoute.tsx`: while the status is `recording` or `paused` and no live recognizer exists, `latestSegmentText(segments)` seeds `TranscriptTail` from the latest unsuperseded utterance and `RecordingTimer` starts from `audio_chunks.length` seconds (one 1 s MediaRecorder timeslice per chunk, none while paused — the sixth clarification, R-09); a recording begun in-session starts at zero and Pause holds the timer (D-01.e, D-01.f; FR-008, SC-005) — landed `051cec1`; proven by T037.
- [x] T043 [US4] W-02 mobile confirmations in `mobile/src/app/brain-dump/[operationId].tsx`: "Discard everything" (M-01.f), "Discard all" and the review header control (M-02.i) confirm through `Alert.alert` with the `cancel`-styled safe answer first, the destructive answer second and `cancelable: true`; the header control's accessible name is "Discard recording" (Trash2) and it is disabled while a command is pending; the retained-audio control's accessible name is "Delete retained audio" against its visible "Delete now" (FR-007 mobile clause and naming rules; SC-004 mobile 3 of 3) — landed `43ae843`; proven by T039.

**Checkpoint**: Web 4 of 4 and mobile 3 of 3 destructive exits confirm first (SC-004); a resumed recording shows the last utterance and the captured duration on first render (SC-005).

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Cross-story accessibility copy, documentation, traceability, the CI record on the exact head, and the stages that remain open.

- [x] T044 [P] W-01 conflict reason in `frontend/src/features/brain-dump/BrainDumpRoute.tsx`: a live `role="status"` line under Send reads "Resolve N conflicts before sending." while open conflicts disable it, and the button names it with `aria-describedby`, so the disabled state is not carried by dimming alone (D-03.g; FR-011) — landed `fc6d13b`; proven by `frontend/src/features/brain-dump/BrainDumpRoute.test.tsx` "015-FR-011 counts the conflicts blocking Send beside the button and clears the line as they are resolved".
- [x] T045 [P] Documentation updates in `docs/voice-stt.md` (the owner-chosen `reconcile_preview` attempt counted against the existing ceilings) and `docs/e2e-acceptance-charter.md` (the transcript readout replaces draft cards; every destructive exit asks first) — landed `9f9ae3b` (voice-stt), `252fa01` and `051cec1` (charter); docs carry no executable test — the charter rows are grep-able by "2026-09-05 amendment" and "Cancel processing".
- [x] T046 Requirement traceability: `python3 scripts/check_requirement_coverage.py specs/015-transcript-first-brain-dump` lists every `015-FR-001…011` and `015-SC-001…007` as `ok` with at least one test file and ends `Requirement coverage passed: 18/18 traced` — run 2026-09-05 against `5ffff85` (quickstart §1).
- [x] T047 CI lanes on the exact head `5ffff8531e7fa814f1f50a86ab78bb10badf7ef6`: `.github/workflows/ci.yml` run 907 (`https://github.com/MaksimKravchuk/brain_buddy/actions/runs/33994131405`, event `pull_request` for PR #194, started 2026-09-05T21:49:10Z, concluded `success` at 22:03:23Z) — Spec Kit artifacts, Backend, Frontend, Mobile, Backend mutation base/head measurement, Backend mutation gate, Docker Images, Allure Report (quality gate `maxFailures: 0`), Full CI, Secret scan / Gitleaks and Workflow lint all `success`; the two earlier failing runs (878 on `12814a7`, 879 on `252fa01`) were fixed by `50369bc` and every later run (880, 892, 895, 907) is green.
- [x] T048 Compose Playwright E2E lane for the confirmation and empty-review flows (`frontend/tests/native-tasks-voice-brain-dump.compose.spec.ts`, `scripts/run_playwright_e2e.sh`): job "Compose Playwright E2E" `101382491245` of run 907 on the same head, started 2026-09-05T21:57:02Z, concluded `success` at 22:01:44Z (`https://github.com/MaksimKravchuk/brain_buddy/actions/runs/33994131405/job/101382491245`); this lane needs Docker and is not runnable in the authoring sandbox, so the CI record is the evidence — verified 2026-09-05 through the GitHub check-run API for PR #194. The run executed against `refs/pull/194/merge`, whose base `6ad795f` is the `origin/main` already merged into `5ffff85`.
- [ ] T049 Human sign-off for the high-risk review campaign — **owner: the founder (Max)**. `plan.md` declares `medium`; the preflight derives `high` because the artifacts name `backend/app/api/tasks.py`, an ASK path (`.specify/workflows/runs/review-015-campaign-1/planning-context.json`: `derived_risk: "high"`, `artifacts_digest` `32cab900…`). Per ADR-0012 and `docs/spec-kit-workflow.md` the campaign cannot reach `approved` without `.specify/workflows/runs/review-015-campaign-1/human-signoff.json` naming the approver and bound to the run id and the artifact digest. Status at writing: campaign 1 is in progress — the run directory holds only its preflight record (`planning-context.json`), no reviewer output, no verdict and no sign-off file. This is a person's act and cannot be done by an agent; it goes stale if `spec.md`, `plan.md` or `design.md` are edited afterwards.
- [ ] T050 `/speckit-accept` → `specs/015-transcript-first-brain-dump/acceptance.md` (explicit accept | reject verdict) and `specs/015-transcript-first-brain-dump/traceability.md` (criterion → named test matrix keyed on FR-/SC- ids and the D-/M- state ids). Not yet produced: the stage runs after the review verdict, is graded by an agent that did not write the code (`acceptance-auditor`), and reads this file, `quickstart.md` and the CI record in T047/T048 as its evidence. Until it lands the feature is correctly reported as not delivered by `scripts/check_spec_kit_specs.py`.
- [ ] T051 `/speckit-report` → `specs/015-transcript-first-brain-dump/report.md`: the end-to-end report for the founder — intake and the recorded waivers, spec, design, plan, every reviewer verdict and the sign-off record from T049, implementation commits, verification (T046–T048) and the acceptance verdict from T050. Not yet produced; it is the last stage and depends on T049 and T050.

---

## Explicitly not tasks in this list

- **Mobile transcript readout and "Cancel processing" (M-03.b)** — out of scope by the ninth clarification; FR-006 binds the web screen. Raising it is a separate feature, not an open task here.
- **`/verify-live` (the founder's real-voice check of the reference utterance, quickstart §7)** — approval-gated and spends provider money; never run by an agent, a subagent or a schedule (CLAUDE.md). It is the founder's call and is not a checkbox an agent may tick.
- **Landing PR #194** — ASK class (`backend/app/api/tasks.py`); under ADR-0008 the PR carries the review evidence and merging it does not by itself update `main`. Landing, deploy and production smoke are post-freeze obligations outside this checklist and are never writer PASS evidence (see Delivery gates above).
- **Tap targets on the web overlay (32–40 px), `Ref:`/`ref:` and "before sending"/"before confirming" wording splits, M-03.a's untitled spinner, D-05.b's missing retry** — recorded as open decisions for a person in `design.md`; accepted as inherited for this feature.
- **The pre-freeze receipt** — no `pre-freeze-receipt.schema.json` receipt was produced for the PR #194 commits (retro feature); the writer-owned evidence is the commit list and the test names cited above, and the independent evidence is T047/T048. This is recorded so the acceptance auditor sees it, not hidden behind a tick.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: T001 (ADR record) has no dependency; T002 (contract) and T003 (scaffolding) are independent of each other.
- **Foundational (Phase 2)**: T004 depends on nothing in Setup; T005 depends on T003's helper. Both block the stories.
- **User Stories (Phase 3–6)**: all depend on Phase 2. As built they landed in this order: US1 + US2 together (`12814a7` → `252fa01` → `50369bc`), then US4 web (`051cec1`), US3 mobile (`a1f0d2e`), US3 backend + web (`9f9ae3b`), US4 mobile (`43ae843`), W-01 (`fc6d13b`), then the `origin/main` merge (`5ffff85`).
- **Polish (Phase 7)**: T044 and T045 depend only on their stories; T046–T048 depend on every story; T049 depends on the review campaign; T050 depends on T049 and on T046–T048; T051 depends on T049 and T050.

### User Story Dependencies

- **User Story 1 (P1)**: depends on Phase 2 (no preview-derived cards to clean up). Independently testable through the backend journey and the Compose review journeys.
- **User Story 2 (P2)**: depends on Phase 2; shares `ReviewSurface` with US1 but its own assertions (no cards before Stop, empty review has no Send) stand alone.
- **User Story 3 (P3)**: depends on Phase 2 and on US2's empty-review gate (T019) — `reconcile_preview` is offered only when no live proposal exists. Independently testable through `test_voice_brain_dump_recovery.py` and the Vitest/Jest recovery cases.
- **User Story 4 (P4)**: depends on Phase 2 only; its confirmations wrap the pre-existing idempotent `cancel`. Independently testable through the confirmation and resume cases.

### Within Each User Story

- Tests are listed before the implementation they prove; the retro caveat above records where they were written together rather than first.
- Backend schema and domain before service; service before the API projection; API before web and mobile rendering (T002 → T027 → T028–T031 → T032 → T033/T035).
- Story complete before the next priority, as the commit order above shows.

### Parallel Opportunities

- T002 and T003 (Setup) touch different files.
- Within every story the test tasks marked [P] are independent files or independent cases in one file.
- US3 mobile (`a1f0d2e`) landed before US3 backend (`9f9ae3b`) against the already-shipped contract shape — the client and server halves of a story were built in parallel once T002's literals were agreed.
- T044 and T045 (Polish) are independent of each other and of T046–T048.

---

## Parallel Example: User Story 3

```bash
# Backend and client tests of the recovery, together (different files):
Task: "Service tests in backend/tests/test_voice_brain_dump_recovery.py"          # T023
Task: "HTTP journey in backend/tests/test_brain_dump_operations_api.py"            # T024
Task: "Web tests in frontend/src/features/brain-dump/BrainDumpRoute.test.tsx"      # T025
Task: "Mobile tests in mobile/src/app/brain-dump/__tests__/review.test.tsx"        # T026

# Then the server chain in order, and the two clients in parallel after T032:
Task: "domain.py hypotheses and checkpoints"                                       # T027
Task: "service.py predicate -> command -> runner -> receipts"                      # T028, T029, T030, T031
Task: "api/tasks.py projection and route"                                          # T032
Task: "BrainDumpRoute.tsx recovery surface"  |  Task: "[operationId].tsx recovery" # T033 | T035
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 (T001–T003) and Phase 2 (T004–T005) — the preview lane becomes transcript only.
2. Phase 3 (T006–T012) — the reference dump reviews as three clean next actions; validate with `test_seal_reconciles_a_filler_prefixed_dump_into_clean_next_actions` and the Compose review journeys.
3. As built, US1 and US2 shipped together in `12814a7`/`252fa01`/`50369bc` because the transcript readout (US2) is what removes the cards US1 had to clean up.

### Incremental Delivery

1. Setup + Foundational → preview text is a status (`12814a7`).
2. US1 + US2 → clean review, honest empty states, loading state (`252fa01`, `50369bc`) — the MVP that answers the founder's two numbered points.
3. US4 web → confirmed exits, cancel from processing, faithful resume (`051cec1`).
4. US3 → the one-shot browser-transcript recovery on mobile, backend and web (`a1f0d2e`, `9f9ae3b`).
5. US4 mobile and W-01 → platform-dialog confirmations, honest mobile empty review, server reasons with reference ids (`43ae843`, `fc6d13b`).
6. Polish → docs, traceability, CI on the exact head (T044–T048); then the human sign-off, acceptance and report (T049–T051).

### Parallel Team Strategy

With more than one implementer: one owns the reconciler and service (`backend/app/workflows/voice_brain_dump/`), one the web overlay (`frontend/src/features/brain-dump/`), one the Expo screen (`mobile/src/app/brain-dump/`), all against the contract fixed in T002; the API projection (T032) is the hand-off point between them.

---

## Notes

- **[P]** tasks = different files, no dependencies; **[Story]** maps a task to its user story for traceability.
- Every product test named above carries its `015-FR-…`/`015-SC-…` id in the test name or docstring and the Allure epic/feature/story/title/step from the central taxonomy files; `check_requirement_coverage.py` traces 18/18 (T046).
- At the time of writing the `specs/015-transcript-first-brain-dump/` directory is present in the working tree of this branch and not yet committed; PR #194 states it lands in that PR once `make check-specs` is green. No product file is changed by this stage.
- `scripts/check_spec_kit_specs.py` reads delivery mechanically off this file: T049–T051 are unchecked, so 015 is reported as planned, not delivered, until `acceptance.md`, `traceability.md` and `report.md` exist.
- Generated tasks.md is portable planning input only. Do not use it to bypass isolated worktrees, TDD, independent review, CI, landing, or release gates.
