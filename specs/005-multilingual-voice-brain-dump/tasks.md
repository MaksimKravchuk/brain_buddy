---
description: "Task list for stable multilingual voice brain dump"
---

# Tasks: Stable Multilingual Voice Brain Dump

**Input**: `specs/005-multilingual-voice-brain-dump/spec.md`, `plan.md`

**Prerequisites**: plan.md, spec.md (user stories US1–US3 + FR-016 follow-up)

**Tests**: Required and written failing-first for every behavior change (backend
pytest/FastAPI TestClient, frontend Vitest/Testing Library, plus the real-audio
evaluation harness reported separately per ADR-0002).

**Organization**: Tasks are grouped by independently testable user story. `[X]`
marks work delivered and live-verified 2026-07-29 with the evidence cited inline;
`[ ]` marks the open FR-016 lane. This file is planning input only — Hermes
Kanban owns implementation ownership, isolated worktrees, TDD, review, CI, PR,
and Fly release gates.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Independent file, parallelizable
- **[Story]**: US1 / US2 / US3 / FR016

---

## Phase 1: Foundational — provider wiring and hermeticity (shared)

**Purpose**: Config/DI seams and test isolation every story depends on. No new
persistence store or domain module is introduced.

- [X] T001 Add role-and-schema provider defaults in `backend/app/core/config.py`:
  accurate provider selects `nova-3` + `DEEPGRAM_API_KEY` (Deepgram) or
  `gpt-4o-mini-transcribe` + `OPENAI_API_KEY` (OpenAI); no vendor enum on the
  operation. *Evidence: config defaults live; provider change is DI-only.*
- [X] T002 Wire `DeepgramAccurateStt` in `backend/app/container.py`
  (`provider == "deepgram"` branch) behind the `AccurateSttPort`; keep the
  reconciler behind `TextReconcilerPort`. *Evidence: split-vendor deployment is
  wiring, not schema.*
- [X] T003 [P] Make the backend test environment hermetic in
  `backend/tests/conftest.py`: scrub `OPENAI_API_KEY`/`DEEPGRAM_API_KEY` so a
  developer `.env` cannot alter deterministic test-provider selection (FR-014).
  *Evidence: 875 backend tests green with keys present in ambient env.*

**Checkpoint**: providers selectable by config; CI deterministic regardless of
local `.env`.

---

## Phase 2: User Story 1 — Multilingual dump becomes reviewable tasks (P1) 🎯 MVP

**Goal**: A real multi-minute RU/EN recording yields ≥15 individually reviewable,
correctly split, language-faithful proposals, each citing its source utterance,
and commits idempotently.

**Independent Test**: Replay the reference 4-minute RU/EN corpus through
capture → review → commit and count committed tasks and their languages.

### Tests for User Story 1

- [X] T004 [P] [US1] Deepgram adapter contract tests
  (`backend/tests/`): multilingual `nova-3` transcription emits one
  `TranscriptHypothesis` per utterance with order/timing/language; embedded
  English proper nouns preserved; no forced single language (FR-001, FR-002).
- [X] T005 [P] [US1] OpenAI accurate-STT hardening tests: 180 s timeout;
  `insufficient_quota` 429 → terminal `STT_PROVIDER_REJECTED_REQUEST` (no retry
  burn) while transient 429/408/409/5xx stay retryable; single-hint pins the
  decode language, zero/multiple hints auto-detect; malformed output →
  `STT_PROVIDER_INVALID_RESPONSE` (FR-001, FR-013).
- [X] T006 [P] [US1] Reconciler grounding + shaping tests: one intent = one task,
  simple «и»/"and" never splits (FR-003); separate utterances not merged unless
  same action (FR-004); queries/display/fillers/«не добавляй…» yield no task
  (FR-005); titles stay in source language, never translated (FR-006); titles
  concise, no inferred deadlines/tags/projects (FR-007).
- [X] T007 [P] [US1] Idempotent commit test: committing reviewed proposals
  creates each task exactly once under command replay (FR-015).

### Implementation for User Story 1

- [X] T008 [US1] Implement `adapters/deepgram_stt.py`: multilingual `nova-3`
  accurate STT emitting per-utterance `TranscriptHypothesis` segments; malformed
  response → `STT_PROVIDER_INVALID_RESPONSE`. *Evidence: live 4-min m4a → 62
  utterance segments.*
- [X] T009 [US1] Harden `adapters/openai_stt.py`: `timeout_seconds = 180.0`;
  `_is_insufficient_quota` terminal 429 classification; single-hint pinning with
  zero/multi-hint auto-detect; audio-size/format/missing terminal codes.
- [X] T010 [US1] Add `TranscriptHypothesis` and per-utterance segment build in
  `backend/app/workflows/voice_brain_dump/domain.py`.
- [X] T011 [US1] `service.py` multi-segment persistence: persist every utterance
  segment and feed the reconciler the *full* segment list so each proposal cites
  its exact source segment(s); allowlist `STT_PROVIDER_INVALID_RESPONSE`
  (FR-002). *Evidence: SC-002 ≈82% one-task accuracy; SC-004 zero conjunction
  splits.*
- [X] T012 [US1] Author the `brain-dump-reconciler-v2` prompt in
  `adapters/reconciler.py` (`template_version = "brain-dump-reconciler-v2"`):
  language-lock, segment-boundary, accounting, conciseness; `gpt-4o` strict
  structured output emitting only schema-valid operations. *Evidence: SC-003
  zero translations.*
- [X] T013 [US1] Confirm title-only idempotent commit through `TaskPort`
  (`confirmation.py`) — one `create_native_inbox_task` per proposal, no inferred
  metadata (ADR-0002). *Evidence: SC-001 15 committed tasks e2e; SC-007 ~30 s.*

**Checkpoint**: US1 independently verified against the reference corpus.

---

## Phase 3: User Story 2 — Consent names every vendor (P2)

**Goal**: Before audio or derived text leaves the device, consent names the
actual configured vendors (including split transcription/reconciliation), and any
stage whose vendor is not consented fails closed with no upload.

**Independent Test**: Configure different transcription/reconciliation vendors,
start a recording, and inspect the consent payload and fail-closed behavior when
consent names the wrong vendor.

### Tests for User Story 2

- [X] T014 [P] [US2] Consent enforcement tests: split-vendor consent names both
  vendors; consent omitting the transcription vendor fails closed with an
  explicit consent-mismatch error and no upload; no external consent yields
  on-device provisional only (FR-011).
- [X] T015 [P] [US2] Frontend discovery tests: `useBrainDumpProviders` renders
  the real configured vendor names; the consent payload carries the providers
  array; no hardcoded label (FR-012).

### Implementation for User Story 2

- [X] T016 [US2] Add `providers: list[str]` to the consent record in
  `domain.py` (`max_length=5`), keeping the legacy single `provider` for
  backward-compatible migration.
- [X] T017 [US2] Per-stage consent guards in `service.py`: each stage verifies
  its own configured vendor is in `consent.providers` before data leaves the
  device; mismatch fails closed. *Evidence: SC-006 fail-closed live.*
- [X] T018 [US2] Add `GET /api/brain-dump-providers` in
  `backend/app/api/tasks.py` returning the deployment's configured vendor names
  (session-scoped, correlation-ID bearing, no owner data).
- [X] T019 [US2] Frontend consent discovery: `useBrainDumpProviders` +
  typed client (`taskHooks.ts`, `client.ts`) feeding `BrainDumpRoute.tsx` the
  consent providers array from real config.

**Checkpoint**: US2 independently verified with a split-vendor deployment.

---

## Phase 4: User Story 3 — One bad proposal never destroys the batch (P2)

**Goal**: A single unverifiable proposal is dropped individually while every
verified sibling still reaches review; an entirely unverifiable batch fails
explicitly; anti-hallucination guarantees are never weakened for yield.

**Independent Test**: Process a transcript where at least one extracted proposal
fails verification and count surviving proposals.

### Tests for User Story 3

- [X] T020 [P] [US3] Per-operation skip tests: a mixed batch delivers every
  verified sibling and drops only the unverifiable proposal(s); an
  all-unverifiable batch raises an explicit validation error (not empty success);
  structural protocol violations still fail the whole batch (FR-010).
- [X] T021 [P] [US3] Anti-hallucination rejection matrix: reject concrete-identity
  swaps, cross-clause action/target recombination, restoration of user-deleted
  proposals, and destructive removals without explicit destructive language;
  accept legitimate source-language morphological variation and title-fragment ↔
  clause grounding (FR-008, FR-009).

### Implementation for User Story 3

- [X] T022 [US3] Implement `_SemanticGroundingFailure` per-proposal skip in
  `adapters/reconciler.py`, isolating one unverifiable proposal from its
  siblings. *Evidence: SC-005 skip semantics live in production shape.*
- [X] T023 [US3] Implement morphology-tolerant grounding (`_tokens_equivalent`)
  and title-fragment ↔ clause grounding, preserving all FR-009 rejections.

**Checkpoint**: US3 independently verified; grounding accept/reject matrix green.

---

## Phase 5: FR-016 grounding-tolerance follow-up (open lane) ⏳

**Goal**: Extend semantic verification to tolerate three additional grounded
shapes without weakening FR-009, recovering the ~1/3 of real-dump proposals that
currently fail closed.

**Independent Test**: On a fixture set of multi-clause-modifier, self-correction,
and garbled-proper-noun utterances, the tolerated shapes ground and commit while
the FR-009 rejection matrix (T021) stays fully green.

- [ ] T024 [FR016] Add failing grounding fixtures for the three FR-016 shapes:
  (a) titles drawing modifier detail from multiple clauses of the same cited
  utterance; (b) mid-utterance self-corrections preferring the corrected value;
  (c) transcription-garbled proper nouns. Assert the FR-009 rejection matrix is
  unchanged.
- [ ] T025 [FR016] Extend `_tokens_equivalent` / grounding in
  `adapters/reconciler.py` for multi-clause modifier grounding within one cited
  utterance, without accepting cross-clause action/target recombination.
- [ ] T026 [FR016] Add self-correction handling that prefers the corrected value
  over the retracted one, keeping the correction traceable to its cited segment.
- [ ] T027 [FR016] Add bounded garbled-proper-noun tolerance (fuzzy match against
  cited transcript / vocabulary) that never invents a noun absent from evidence.
- [ ] T028 [FR016] Re-run the reference-corpus evaluation harness and record the
  recovered-proposal delta; confirm zero new translations, zero new false splits,
  and no regression in the FR-009 matrix before release.

**Checkpoint**: FR-016 shapes ground and commit; all US1–US3 guarantees hold.

---

## Dependencies & Execution Order

- **Phase 1 (Foundational)** blocks all stories: provider wiring + hermeticity.
- **US1 (P1)** is the MVP and depends only on Phase 1.
- **US2 (P2)** and **US3 (P2)** depend on Phase 1; both build on the US1 pipeline
  but are independently testable (consent enforcement vs. batch resilience).
- **FR-016 (Phase 5)** depends on US1 + US3 (it extends the same grounding path)
  and is the only open lane; it is dispatched through Hermes Kanban.

### Within each story

- Tests written and failing before implementation.
- Adapters/domain before service wiring; service before API/frontend.
- Anti-hallucination rejection matrix (T021) is a standing gate for any FR-016
  change.

## Notes

- `[X]` tasks are delivered and live-verified 2026-07-29; `[ ]` FR-016 tasks
  remain open.
- Generated tasks.md is planning input only. It does not bypass Hermes Kanban
  ownership, isolated worktrees, TDD, independent review, CI, PR, merge, or Fly
  release gates.
- Rejected alternatives stay out of scope: windowed/batched reconciliation
  (+21% cost, translation regression) and inferring structured fields from speech.
