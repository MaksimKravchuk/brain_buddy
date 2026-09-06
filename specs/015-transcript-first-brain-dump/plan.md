# Implementation Plan: Transcript-first voice brain dump

**Branch**: `claude/brain-dump-mechanics-t35ab7` (PR #194) · **Spec**: [spec.md](spec.md) · **Design**: [design.md](design.md) · **Date**: 2026-09-05

Retro plan: it describes the architecture as built on this branch (commits `12814a7`, `252fa01`, `50369bc`, `051cec1`, `a1f0d2e`, `9f9ae3b`, `43ae843`, `fc6d13b`; `5ffff85` merges `main`). Architecture record: `docs/decisions/0002-async-voice-operation-substrate.md`, both amendments dated 2026-09-05. Vocabulary: ADR-0006 (`Tag`).

## Summary

The server no longer mints tasks from browser-preview fragments; the web shows the preview as a transcript readout. Tasks are produced once by the reconciler over the accurate transcript as GTD next actions, with model-independent guards for fillers and duplicates. Destructive exits confirm on both clients, resume restores the tail and timer, and a terminal failure can be recovered once by an owner-chosen, text-only extraction from the browser transcript that is always labelled provisional.

## Technical Context

Backend Python 3.12, FastAPI, pydantic documents (SQLite with JSON mirrors); web React 19, Vite, Vitest, Playwright (Compose e2e in CI only); mobile Expo, Jest. Cost caps, recovery budget and retention windows come from `.env.example` (`BRAIN_BUDDY_VOICE_*`).

## Constitution Check

- **Consent and local-first**: the reconciler is external processing. Preview text exists on a recording only because `external_processing_allowed` was true when the browser appended it; the recovery re-checks consent at enqueue and before the call and is unavailable after withdrawal. The `voice_brain_dump` flag gates forward actions (record, retry, commit, `reconcile_preview`); `cancel`, `withdraw_consent` and `delete_raw_audio` stay reachable with the flag OFF.
- **Owner scoping**: every route is owner-filtered; commands are idempotent and owner-serialized.
- **Retention**: unchanged. Raw audio 24 h after reconciliation, uncommitted working artifacts 7 days, cancel deletes audio at once.
- **Mobile-first**: 390 px is the primary frame; mobile renders exactly what the server advertises.
- **TDD and gates**: each change landed with its tests; CI is green on `5ffff85` and `0a06a5b`.
- **Design citations**: see the table at the end.

## Architecture as built

- **A1 Preview lane as transcript** — `backend/app/workflows/voice_brain_dump/service.py::append_brain_dump_transcript` persists segments only. Web `BrainDumpRoute.tsx`: `transcriptLane` / `TranscriptReadout` (settled, non-superseded segments), the forming hypothesis beside the microphone. Screens D-01, D-02.
- **A2 Reconciler v3 and guards** — `adapters/reconciler.py`: prompt `brain-dump-reconciler-v3`; `_validate_draft` (provenance, grounding, language fidelity, filler check), `_dedupe_draft` (one proposal per distinct action, renames and removals followed), `_fold_duplicate` (a duplicate's segments and predecessors fold into the survivor), `_DISCOURSE_FILLER_TERMS` kept apart from `_ACTION_PREFIX_TERMS`; `domain.py::normalized_title` shared with the service. Dropped operations are logged by fixed reason. Screen D-03.
- **A3 Commit gate** — `brain_dump_operation_is_committable` requires a surviving proposal; the web and mobile reviews show an honest empty state. D-03.h, D-03.i, M-02.e.
- **A4 Preview recovery** — `domain.py`: `browser_preview_recovery_hypotheses`, checkpoint literals `preview_transcribed` / `preview_reconciled`. `service.py`: `can_reconcile_brain_dump_preview` (state, consent, cost), `reconcile_brain_dump_preview` (queues one `reconciler` run, wakes the runner), `_reconcile_claimed_preview_run`, `_reconcile_accurate_checkpoint(source_checkpoint=…)` writes `provisional_only` + `manual_review`, retry re-queues a preview run. `api/tasks.py`: `reconcile_preview` dispatch, `_brain_dump_available_recovery_actions`. `schemas/tasks.py::BrainDumpRecoveryAction`. Screens D-04, M-01.
- **A5 Web exits, resume, errors** — `DestructiveConfirm` (inline, safe choice focused, Escape keeps), `ProcessingSurface.onCancel`, `latestSegmentText` seeds the tail, `RecordingTimer.initialSeconds` = uploaded audio chunks (1 s each; valid for web-captured recordings), `describeError` renders the server message plus `Ref: <correlation id>`, "Resolve N conflicts before sending." Screens D-01…D-05.
- **A6 Mobile** — `mobile/src/app/brain-dump/[operationId].tsx`: `confirmDiscard` through `Alert.alert` for the three destructive exits, header control "Discard recording", "Delete retained audio", empty review with `heardTranscript` (`mobile/src/braindump/machine.ts`), "Extract tasks from the browser transcript". Screens M-01, M-02, M-03.

## Contracts

| Item | As built |
|---|---|
| Command route | `POST /api/brain-dump-operations/{id}/{action}`; `reconcile_preview` joins `retry`, `review_provisional`, `pause`, `resume`, `finish`, `cancel`, `commit`, `withdraw_consent`, `delete_raw_audio`. Body `{ expected_revision }`, header `Idempotency-Key`. |
| Flag | OFF → 404 for forward actions including `reconcile_preview`; privacy controls stay reachable. |
| Projection | `available_recovery_actions` ⊂ `retry`, `review_provisional`, `reconcile_preview`, `cancel` in that order; `review_provisional` (surviving proposals) and `reconcile_preview` (none) are mutually exclusive. |
| Refusals | `BRAIN_DUMP_PREVIEW_RECOVERY_UNAVAILABLE`, `RECONCILER_CONSENT_REQUIRED`, `RECONCILER_CONSENT_PROVIDER_MISMATCH`, `OPERATION_COST_BUDGET_EXCEEDED`; clients render the message and the reference id. |
| Quality | a preview run freezes at `preview_reconciled` with `reconciliation_quality=provisional_only` and `manual_review=true`; the canonical `accurate` gate cannot be satisfied by preview text; receipts copy the quality. |

## Failure handling and resume

A retryable preview failure lands in `retryable_error`; `retry` re-queues the run over the preview text (no STT, no sealed manifest needed), bounded by `BRAIN_BUDDY_VOICE_MAX_OPERATION_RECOVERIES`. A terminal failure lands in `terminal_error` with cancel as the only exit; the attempt is one shot. Consent withdrawal invalidates an in-flight run and schedules the text for deletion. Reload or offline: ADR-0002 resume; the web seeds the tail and timer (D-01.f), mobile polls the stage (M-03).

## Tests

| Runner | Files | Ids carried |
|---|---|---|
| pytest | `test_voice_brain_dump_recovery.py`, `test_voice_brain_dump_reconciliation.py`, `test_brain_dump_operations_api.py` | FR-002…005, FR-009, FR-011; SC-001, SC-003, SC-006 |
| Vitest | `frontend/src/features/brain-dump/BrainDumpRoute.test.tsx` | FR-001, FR-005…011; SC-002…007 |
| Playwright (CI) | `frontend/tests/native-tasks-voice-brain-dump.compose.spec.ts` | FR-001, FR-003, FR-005, FR-007; SC-002 |
| Jest | `mobile/src/app/brain-dump/__tests__/review.test.tsx`, `mobile/src/braindump/__tests__/machine.test.ts` | FR-005, FR-007, FR-009, FR-010; SC-004, SC-006, SC-007 |

`python3 scripts/check_requirement_coverage.py specs/015-transcript-first-brain-dump` → 18/18 traced (a naming check, not proof that a test is meaningful). Coverage floors: backend 98.47 line / 95.5 branch; frontend 98.76 / 97.77 / 98.64 / 98.84; mobile 94 / 88 / 95 / 94. Mutation gate: no enforced-tier module touched.

## Release gates and rollback

Flag-gated feature; ADR-0008 landing through PR #194; every CI lane including the Compose e2e. Rollback is a clean code rollback only while no recording carries a `preview_transcribed` or `preview_reconciled` attempt: the previous code rejects those documents, so once one exists the path is a forward fix that keeps the checkpoint literals.

## Risk class

Declared `medium` (no auth, migration, CI, deploy or secret paths change). The preflight derives `high` because the artifacts name `backend/app/api/tasks.py`, an ASK-class path, so a review campaign at this class needs the founder's recorded sign-off.

## Design citations

| Plan section | Screens |
|---|---|
| A1 | D-01, D-02 |
| A2, A3 | D-03, M-02 |
| A4 | D-04, M-01 |
| A5 | D-01, D-02, D-03, D-04, D-05 |
| A6 | M-01, M-02, M-03 |

## Deviations

Retro plan; interview and design sign-off waived by the founder; spec 002 frozen and narrowed rather than edited; the second review campaign, acceptance and report were not run (founder, 2026-09-05). Open technical notes from campaign 1 are in the spec's Open items.
