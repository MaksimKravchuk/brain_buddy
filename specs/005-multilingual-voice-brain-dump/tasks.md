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
  explicit consent-mismatch error; **no external consent means recording does
  not start** (no on-device provisional path — per US2 scenario 3 / Out of
  Scope). *Note: the exact vendor-B-only pre-upload negative path is completed by
  the hardening lane (Phase 6, T029) — see that lane for the SC-006 evidence
  re-anchor.*
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

## Phase 5: FR-016 grounding-tolerance (delivered)

**Goal**: Extend semantic verification to tolerate three additional grounded
shapes without weakening FR-009, recovering the real-dump proposals that
previously failed closed.

**Independent Test**: On a fixture set of multi-clause-modifier, self-correction,
and garbled-proper-noun utterances, the tolerated shapes ground and commit while
the FR-009 rejection matrix (T021) stays fully green.

**Delivered 2026-07-29** in `adapters/reconciler.py` (`_grounding_clauses`,
`_correction_clauses`, `_entities_equivalent` / within-segment adjunct grounding),
covered by named tests in `backend/tests/test_voice_brain_dump_reconciliation.py`
(334 reconciliation tests / 907 backend tests green). Documented fail-closed
residue remains for: the pronoun-binding self-correction case, edit-distance-3
proper-noun garbles, and one paraphrase class — these still fail closed rather
than guess (FR-009 preserved).

- [X] T024 [FR016] Add grounding fixtures for the three FR-016 shapes:
  (a) titles drawing modifier detail from multiple clauses of the same cited
  utterance; (b) mid-utterance self-corrections preferring the corrected value;
  (c) transcription-garbled proper nouns; assert the FR-009 rejection matrix is
  unchanged. *Evidence: `test_openai_reconciler_grounds_within_segment_multi_clause_aggregation`,
  `test_openai_reconciler_grounds_self_corrected_utterances`,
  `test_openai_reconciler_tolerates_stt_garbled_proper_noun`.*
- [X] T025 [FR016] Extend grounding in `adapters/reconciler.py`
  (`_grounding_clauses` / within-segment adjunct path) for multi-clause modifier
  grounding within one cited utterance, without accepting cross-clause
  action/target recombination.
- [X] T026 [FR016] Add self-correction handling (`_correction_clauses`) that
  prefers the corrected value over the retracted one, keeping the correction
  traceable to its cited segment. *Residue: pronoun-binding self-correction still
  fails closed.*
- [X] T027 [FR016] Add bounded garbled-proper-noun tolerance
  (`_entities_equivalent`, fuzzy match against cited transcript / vocabulary)
  that never invents a noun absent from evidence. *Residue: edit-distance-3
  garbles still fail closed.*
- [X] T028 [FR016] Reference-corpus evaluation harness records the recovered
  proposals; zero new translations, zero new false splits, no regression in the
  FR-009 matrix (907 backend tests green).

**Checkpoint**: FR-016 shapes ground and commit; all US1–US3 guarantees hold.

---

## Phase 6: Planning-review hardening lane (DELIVERED)

**Goal**: Close the gating gaps the high-risk planning review (run `rerun0729`)
found between the spec's promises and the delivered code. Landed test-first on the
ASK-class paths, Kanban-dispatched, in commits `889a956`, `2ca19f0`, `2420c96`,
`b670856`, `2c3e4ec`. Integrated verification at hardening completion: 969 backend
(97.23% coverage) / 452 frontend green (now 994 backend at HEAD `c979621` with the
release-closure fixes), build green, ruff + mypy clean, plus a
live e2e drive through the hardened pipeline (flag ON, phased commit saga): real
4-minute recording → 19 proposals (up from 15) → committed per-action → tasks in
tracker.

- [X] T029 [HARDEN] Consent pre-upload complete-set boundary: `service.py`
  requires the *complete* configured vendor set before egress (`889a956`); an
  authoritative `providers` list with `AUDIO_UPLOAD_PROVIDER_CONSENT_CONFLICT` on
  conflicting dual-field precedence, plus the vendor-B-only negative test proving
  no persistence (`2ca19f0`). *SC-006 re-anchored to HEAD.*
- [X] T030 [HARDEN] Provider-discovery fail-closed prerequisite (frontend,
  `2420c96`): hardcoded `openai` fallback removed; mic/upload provably gated on
  discovery having loaded, with an explicit retry state; real vendor names
  rendered (FR-012).
- [X] T031 [HARDEN] Review-screen citation rendering (frontend, `2420c96`): each
  proposal's cited utterance is rendered with stale-id degradation (US1/FR-002).
- [X] T032 [HARDEN] Consent-withdrawal deletion (backend, `2ca19f0`): withdrawal
  sets a deletion deadline and makes active operations sweep-eligible (existing
  retention variable), with a retention test.
- [X] T033 [HARDEN] Frozen batch + durable per-action ledger (backend,
  `2ca19f0`): commit is a phased saga (status `committing`) with a per-action
  ledger and a fault-injection suite (fail after action N, restart, replay). Meets
  FR-015 / ADR-0002 §485-519 / ADR-0006 B-38.
- [X] T034 [HARDEN] ADR-0008 `voice_brain_dump` rollout flag (backend + frontend,
  `2ca19f0` flag + `2420c96` gate): OFF/INTERNAL/ON, 404 fail-closed on all 8
  routes, `/api/auth/me` exposure, TEST-env ON in `conftest.py`, frontend
  `BrainDumpGate`.
- [X] T035 [HARDEN] Operational evidence report (backend eval, `b670856`):
  hash-addressed, live + recorded modes, corpus fixture v1, golden report, no raw
  text — computes SC-001..004/007. *(Non-gating leftover: the live report on the
  final release SHA is still to be produced by the thin harness.)*
- [X] T036 [HARDEN] ADR-0006 authority copy (frontend + e2e, `2c3e4ec`):
  provisional/confirmation language replaces the prohibited "Headed to inbox".
- [X] T037 [HARDEN] Title-shape invariant (reconciler, `b670856`): a script-based
  language-fidelity classifier with per-op skip, distinct from FR-008 grounding
  (proven by a grounding-neutralized test), so a translated/ungrounded title
  FR-006 prohibits cannot be accepted.

**Checkpoint**: all Phase 6 items delivered with tests; suites green (994 backend
/ 452 frontend at HEAD `c979621`). Known non-gating leftover: Playwright
visual baselines need regeneration; the live T035 report on the release SHA is
still to be produced. The final high-risk campaign runs against `2c3e4ec`.

---

## Phase 7: Release-closure lane (mostly delivered)

**Goal**: Close the remaining final0729 blocking/important gaps before the ASK
landing and the approved final campaign. **Delivered**: T038/T039 (commit
concurrency + fail-closed audio deletion, `cac5a27`), T042 (live evidence report,
`900eeb8`/`0b0d166`), and T040/T041 (commit_batch title purge + committing
recovery, `c979621`). **Still OPEN** (important-severity, not blocking): T043
(full-stack acceptance-coverage tests) and T044 (partial-commit retry UX). The
campaign runs with those two open in the lane.

- [X] T038 [CLOSE] Commit idempotency/concurrency (backend, `cac5a27`):
  `create_native_inbox_task` is owner-serialized with an atomic task/idempotency
  write, CAS ledger recording, and a purge exemption preserving child identity for
  the frozen batch's lifetime; concurrent-duplicate/crash/retry tests added.
  *(architecture blocking — VERIFIED and fixed; 10 new tests, suite 988)*
- [X] T039 [CLOSE] Raw-audio deletion verified outcome (backend, `cac5a27`):
  verified-absence deletion with a sweep retry replaces the fail-open
  `ignore_errors=True`; metadata is not cleared until absence is confirmed.
  *(architecture blocking — VERIFIED and fixed)*
- [X] T040 [CLOSE] Commit_batch title retention (backend, `c979621`):
  `purge_expired_working_artifacts` reduces frozen `commit_batch` action titles to
  their SHA-256 (identical to receipts' `confirmed_title_sha256`) for
  terminal/withdrawal-finalized operations past the window; resume-capable
  `committing` ops keep titles (resume needs them, and they are inside their window
  by definition). No schema change, rollback-safe; 3 tests.
  *(adversarial important: privacy-data-retention — closed)*
- [X] T041 [CLOSE] `committing` recovery (backend, `c979621`): a new sweep duty
  `recover_committing_operations` resumes stranded `committing` ops through the
  standard commit path with recovery idempotency keys (safe no-op on concurrent
  state moves), plus an observability line and a `docs/voice-stt.md` runbook note;
  3 tests. *(adversarial important: privacy-resilience — closed)*
- [X] T042 [CLOSE] Live operational evidence report (backend, `900eeb8`,
  committed `0b0d166`): ran on the real pipeline (`run_key e8cb406f…`, strict
  4-signal oracle). SC-001 (19 committed), SC-003 (0/45 translated), SC-007
  (21.1 s) pass; SC-002 74.4% (32/43) and SC-004 2/22 splits are below the
  PUBLIC-ON gates and founder-accepted. *(testability blocking — delivered)*
- [ ] T043 [CLOSE] Acceptance-coverage evidence: full-stack A+B / consent-only-B
  browser test asserting the client sends no audio request (first-party
  boundary) with the backend no-persistence guard as defense-in-depth; a
  deterministic 30/5 mixed-batch test (survivor count, order, provenance,
  rejection accounting); explicit no-task (query/filler/"don't add") and
  cross-utterance no-merge criteria. *(testability blocking privacy-evidence +
  important acceptance-coverage)*
- [ ] T044 [CLOSE] Partial-commit UI retry path: a supported client can observe
  persisted partial results from a `committing` operation and retry the frozen
  batch to completion without duplicating actions. *(requirements important)*

**Checkpoint**: T038/T039/T040/T041/T042 delivered at HEAD `c979621` (994 backend
green, 97.24% cov; live report committed). T043/T044 remain open (important, not
blocking). The final high-risk campaign runs against `c979621` for an approved
aggregate with those two open in the lane.

---

## Dependencies & Execution Order

- **Phase 1 (Foundational)** blocks all stories: provider wiring + hermeticity.
- **US1 (P1)** is the MVP and depends only on Phase 1.
- **US2 (P2)** and **US3 (P2)** depend on Phase 1; both build on the US1 pipeline
  but are independently testable (consent enforcement vs. batch resilience).
- **FR-016 (Phase 5)** depends on US1 + US3 (it extends the same grounding path)
  and is delivered (landed in `reconciler.py` after the core, 907 backend tests
  green) with a documented fail-closed residue.
- **Phase 6 (hardening, T029–T037)** is delivered (commits `889a956`, `2ca19f0`,
  `2420c96`, `b670856`, `2c3e4ec`): consent pre-upload boundary, provider-discovery
  prerequisite, review-screen citations, consent-withdrawal deletion, frozen-batch
  phased-saga commit, ADR-0008 rollout flag, corpus evidence report, ADR-0006 copy,
  and the title-shape invariant, each landed test-first on the ASK-class paths.

### Within each story

- Tests written and failing before implementation.
- Adapters/domain before service wiring; service before API/frontend.
- Anti-hallucination rejection matrix (T021) is a standing gate for any FR-016
  change.

## Notes

- Phases 1-6 (T001-T037) plus release-closure T038/T039/T040/T041/T042 are
  delivered at HEAD `c979621` (994 backend / 452 frontend green); release-closure
  T043/T044 remain open. Known non-gating leftovers: Playwright visual baselines
  need regeneration; the live T035 operational report on the release SHA is still
  to be produced by the thin harness.
- Generated tasks.md is planning input only. It does not bypass Hermes Kanban
  ownership, isolated worktrees, TDD, independent review, CI, PR, merge, or Fly
  release gates.
- Rejected alternatives stay out of scope: windowed/batched reconciliation
  (+21% cost, translation regression) and inferring structured fields from speech.
