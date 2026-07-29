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

## Phase 6: Planning-review hardening lane (OPEN — code-owned) ⏳

**Goal**: Close the gating gaps the high-risk planning review (run `rerun0729`)
found between the spec's promises and the delivered code. These are **code/test
changes owned by implementers**, not Architect wording; the Architect artifacts
enumerate them here so they are dispatched and evidenced through Hermes Kanban
(not landed as unrepresented working-tree edits on ASK-class paths). All gate the
approved handoff and the ASK landing.

- [ ] T029 [HARDEN] Consent pre-upload complete-set boundary: enforce that the
  *complete* configured vendor set (not any subset) is consented before egress in
  `service.py::_assert_external_provider_consent`; add the vendor-B-only
  negative test proving no upload/persistence/provider invocation; define one
  precedence rule for `providers` vs legacy `provider` (list-only / legacy-only /
  matching / conflicting dual-field). Re-anchor SC-006 evidence to the resulting
  SHA. *(blocking: requirements privacy-consent-gap, architecture consent-contract,
  adversarial evidence-integrity)*
- [ ] T030 [HARDEN] Provider-discovery fail-closed prerequisite (frontend): gate
  consent + Record on `GET /api/brain-dump-providers` having loaded; remove the
  hardcoded `openai` fallback; explicit loading/error/retry state; render the
  actual vendor names (FR-012). Add a client privacy-boundary test proving
  getUserMedia / MediaRecorder / audio PUT cannot start until discovery succeeds
  and consent covers every returned role. *(blocking: privacy-consent-gap,
  privacy-boundary-evidence; adversarial FR-012 degraded-path)*
- [ ] T031 [HARDEN] Review-screen citation rendering (frontend): resolve each
  proposal's `source_segment_ids` to the cited utterance text/cue on the review
  surface (single + multi-segment + missing/stale), fulfilling the US1/FR-002
  "cites the utterance it came from" acceptance behavior; add frontend coverage.
  *(blocking: requirements missing-acceptance-behavior)*
- [ ] T032 [HARDEN] Consent-withdrawal deletion (backend): add a persisted
  withdrawal/cleanup transition that sets an enforceable deletion deadline and
  becomes sweep-eligible without a further user command; retention test proving
  withdrawn uncommitted transcript/proposal text is purged after the configured
  period. *(blocking: architecture privacy-retention)*
- [ ] T033 [HARDEN] Frozen batch + durable partial-commit ledger (backend):
  persist a frozen proposal/action snapshot before the first `TaskPort` write with
  deterministic batch/action child identity and a per-action result record; retry
  consumes the snapshot and skips recorded successes; fault-injection tests (fail
  after action N, restart, edit/delete during partial failure, replay with same
  and new outer key). Satisfies FR-015 / ADR-0002 §485-519 / ADR-0006 B-38.
  *(blocking: architecture commit-consistency, testability partial-commit-recovery)*
- [ ] T034 [HARDEN] ADR-0008 server rollout flag (backend + release): add a named,
  allowlisted, default-OFF feature flag gating the voice-brain-dump UI discovery
  and backend commands, with OFF → INTERNAL → ON behavior; make flag rollback the
  first reversible response. *(blocking: architecture release-rollback)*
- [ ] T035 [HARDEN] Operational evidence report (backend eval): a privacy-safe,
  hash-addressed capture→review→commit report keyed to the exact SHA + corpus
  digest + provider/model config, computing SC-001 (committed count), SC-002
  (task-yielding hits/total), SC-003 (translated/normalized titles/total, with
  code-switched source-word fixtures kept separate from FR-008 morphology), SC-004
  (conjunction false splits), SC-007 (latency). *(blocking: testability
  reference-corpus-evidence + metric-oracle-coverage)*
- [ ] T036 [HARDEN] ADR-0006 authority copy (frontend): replace "Headed to inbox"
  / "Save N to inbox" with the accepted provisional/confirmation language
  ("Provisional · N", "Confirm N"). *(important: requirements accepted-ux-contract-omission)*
- [ ] T037 [HARDEN] Title-shape invariant (reconciler): enforce the FR-006
  language-faithful title policy as a title-generation invariant distinct from the
  FR-008 grounding tolerance, so a verifier cannot accept a translated/ungrounded
  title that FR-006 prohibits. *(important: architecture semantic-contract)*

**Checkpoint**: all Phase 6 items landed with tests; full suites re-run on the
final candidate SHA; SC evidence re-anchored to it; then rerun the planning
campaign for an approved aggregate.

---

## Dependencies & Execution Order

- **Phase 1 (Foundational)** blocks all stories: provider wiring + hermeticity.
- **US1 (P1)** is the MVP and depends only on Phase 1.
- **US2 (P2)** and **US3 (P2)** depend on Phase 1; both build on the US1 pipeline
  but are independently testable (consent enforcement vs. batch resilience).
- **FR-016 (Phase 5)** depends on US1 + US3 (it extends the same grounding path)
  and is delivered (landed in `reconciler.py` after the core, 907 backend tests
  green) with a documented fail-closed residue.
- **Phase 6 (hardening, T029–T037)** is OPEN and gates the approved handoff: it
  closes the code-vs-spec gaps the high-risk review found (consent pre-upload
  boundary, provider-discovery prerequisite, review-screen citations, consent
  withdrawal deletion, frozen-batch partial commit, ADR-0008 rollout flag, corpus
  evidence report, ADR-0006 copy, title-shape invariant). Dispatched through
  Hermes Kanban; each item lands test-first on ASK-class paths.

### Within each story

- Tests written and failing before implementation.
- Adapters/domain before service wiring; service before API/frontend.
- Anti-hallucination rejection matrix (T021) is a standing gate for any FR-016
  change.

## Notes

- Phases 1–5 (T001–T028: US1–US3 core + FR-016 grounding tolerance) are
  delivered on the branch (907 backend tests green, documented FR-016 residue).
  **Phase 6 (T029–T037) is OPEN** — the planning-review hardening lane, code-owned
  and gating the approved handoff and ASK landing.
- Generated tasks.md is planning input only. It does not bypass Hermes Kanban
  ownership, isolated worktrees, TDD, independent review, CI, PR, merge, or Fly
  release gates.
- Rejected alternatives stay out of scope: windowed/batched reconciliation
  (+21% cost, translation regression) and inferring structured fields from speech.
