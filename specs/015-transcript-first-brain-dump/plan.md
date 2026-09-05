# Implementation Plan: Transcript-first voice brain dump

**Branch**: `claude/brain-dump-mechanics-t35ab7` (Spec Kit feature `015-transcript-first-brain-dump`) | **Date**: 2026-09-05 | **Spec**: [spec.md](spec.md) · **Design**: [design.md](design.md) · **Intake**: [intake.md](intake.md) · **Checklist**: [checklists/requirements.md](checklists/requirements.md)

**Input**: Feature specification from `specs/015-transcript-first-brain-dump/spec.md` (FR-001…FR-011, SC-001…SC-007, ten recorded clarifications).

**Kind**: **retro plan.** The architecture below is the one already built on this branch (PR #194, commits `12814a7`, `252fa01`, `50369bc`) plus two follow-up work items ([W-01, W-02](#work-items-landing-on-this-branch)) landing on the same branch while this plan is written. It is written so that `/speckit-tasks`, `/speckit-converge` and `/speckit-accept` can map onto real files and named tests; nothing below proposes code that does not exist unless it is marked as a work item. The architecture record is `docs/decisions/0002-async-voice-operation-substrate.md`, both amendments dated 2026-09-05 ("browser preview is a transcript readout, not a task source" and "`reconcile_preview` — owner-chosen recovery from preview text"). Vocabulary follows ADR-0006 (`Tag` is the canonical term; neither retired synonym appears here).

**Risk class (ADR-0012)**: declared **`medium`** — see [Risk class and landing class](#risk-class-and-landing-class) for why the preflight classifier nevertheless derives `high` and what that means for the review campaign.

## Summary

The browser Web Speech preview used to mint a `fast` draft proposal per interim fragment; the reconciler could not retire them, so the reference utterance produced nine review entries and a disabled Save. As built, browser-preview segments are persisted and rendered as a **transcript readout** only. Proposals are minted **once**, by the text reconciler (prompt `brain-dump-reconciler-v3`) over the accurate transcript after seal, as GTD next actions, with server-side filler and duplicate guards that hold independently of the model. A review with no surviving proposal is not committable. A terminal failure of the accurate lane on an operation that still holds stable preview text exposes one explicit, one-shot, consent- and cost-bounded recovery command, `reconcile_preview`, whose result is frozen as `provisional_only` and is never called accurate. The web overlay gained inline destructive confirmations, a "Cancel processing" exit and resume seeding (last utterance plus timer); mobile renders the server-advertised recovery and the provisional label and, with W-02, confirms its destructive exits through the platform dialog.

## Technical Context

**Language/Version**: Python 3.12 (backend); TypeScript / React 19 (web); TypeScript / React Native on Expo (mobile).

**Primary Dependencies**: FastAPI and pydantic v2 (`StrictBaseModel` contracts, `StorageBaseModel` documents), `httpx` transport for the OpenAI reconciler adapter; React Router, TanStack Query and Vite on the web; Expo Router and TanStack Query on mobile.

**Storage**: operation-private SQLite `voice_operations.sqlite3` with JSON mirrors under `brain-dump-operations/<owner>/<operation>.json` and raw audio under `brain-dump-media/<owner>/<operation>/` (`OperationRepository` in `backend/app/workflows/voice_brain_dump/repository.py`). No migration: the operation document is `schema_version=2` and every field this feature relies on is additive (see [data-model.md](data-model.md)).

**Testing**: pytest with the FastAPI `TestClient` (`api_client` fixture) and the `DeterministicTextReconciler` wired by the container in `AppEnvironment.TEST`; Vitest + Testing Library; Playwright against the Docker Compose stack; Jest with `mobile/src/test/fakeBackend.ts`. Allure taxonomy on every runner.

**Target Platform**: Linux backend on Fly.io (private Flycast app behind the frontend proxy); evergreen browsers from a 390 px viewport up; iOS-first Expo app.

**Project Type**: web service + web SPA + mobile app inside the ADR-0001 modular monolith.

**Performance Goals**: ADR-0002 budgets unchanged (reconciled batch under 8 s p95 for a 2-minute dump); both clients poll the projection with 1.5 s → 8 s exponential backoff.

**Constraints**: external processing is consent-gated; reconciler per-role cap `BRAIN_BUDDY_VOICE_RECONCILER_MAX_COST_USD=0.50` and cumulative cap `BRAIN_BUDDY_VOICE_MAX_CUMULATIVE_COST_USD=1.00`; `BRAIN_BUDDY_VOICE_MAX_OPERATION_RECOVERIES=2`; retention unchanged (raw audio 86 400 s after reconciliation, uncommitted working artifacts 604 800 s); the `voice_brain_dump` flag gates forward actions only.

**Scale/Scope**: single-user deployment today, owner-scoped for many; one workflow package, one route module, one web route, one mobile screen; 18 feature-qualified requirement ids traced to tests.

## Constitution Check

*GATE: evaluated against the built code, not a proposal.*

- **Spec workflow** — `spec.md` is current (2026-09-05); its `## Clarifications` session records ten decisions, each attributed; `checklists/requirements.md` is 16/16; zero unresolved-clarification markers remain. Spec 002 is narrowed in prose and stays hash-frozen (`scripts/check_spec_kit_specs.py` pins it), per the first clarification.
- **Consent & Safety** — Preview text is accepted only while `consent.external_processing_allowed` is true (`append_brain_dump_transcript` raises `TRANSCRIPT_CONSENT_REQUIRED`). The recovery re-checks consent at enqueue (`RECONCILER_CONSENT_REQUIRED`, `RECONCILER_CONSENT_PROVIDER_MISMATCH`) and the runner re-checks it before the provider call (`_reconcile_accurate_checkpoint`); after `withdraw_brain_dump_consent` the predicate is false and the action leaves `available_recovery_actions`. Provider I/O never runs in a request handler: commands persist a `pending` run and call `runner_wake()`. Provisional output stays in the operation workspace until `commit`; every action receipt records `reconciliation_quality`. Logs carry ids, counts and fixed reason strings — `brain_dump_reconciler_dropped_operations operation_id=… dropped=… reasons=…` — never transcript or title text, and provider errors pass through the `_redact_provider_error` allowlist. Tests use the deterministic reconciler and synthetic WAV bytes; no secrets, real data or raw audio enter fixtures or evidence.
- **Tests** — Backend: `backend/tests/test_voice_brain_dump_reconciliation.py` (FR-003, FR-004 guards), `backend/tests/test_voice_brain_dump_recovery.py` (four `015_FR_009` tests: predicate clauses, enqueue with idempotent replay, runner input, provisional receipts), `backend/tests/test_brain_dump_operations_api.py` (FR-002, FR-004, FR-005, FR-009, FR-011, SC-001, SC-002, SC-003, SC-006 through the HTTP client). Web: `frontend/src/features/brain-dump/BrainDumpRoute.test.tsx` (FR-001, FR-005, FR-006, FR-007, FR-008, FR-009, FR-010, SC-002…SC-007). Compose e2e: `frontend/tests/native-tasks-voice-brain-dump.compose.spec.ts` (FR-001, FR-003, FR-005, FR-007, SC-002). Mobile: `mobile/src/app/brain-dump/__tests__/review.test.tsx` (FR-009, FR-010, SC-006, SC-007). `python3 scripts/check_requirement_coverage.py specs/015-transcript-first-brain-dump` reports 18/18. Edge cases covered: consent denial and withdrawal, cost cap reached, one attempt spent, stale revision, cancel during processing, idempotent replay, partial upload failure, filler-only envelope, deleted-title revival. Retro caveat: the PR #194 tests were written with the fix rather than strictly before it; W-01 and W-02 follow failing-then-passing on the branch.
- **Contracts** — Backend schema first (`backend/app/schemas/tasks.py`), then `frontend/src/api/taskTypes.ts` and `mobile/src/api/types.ts`. Changes are additive: `BrainDumpRecoveryAction` gains `reconcile_preview`; the provider-run `checkpoint` literal gains `preview_transcribed` and `preview_reconciled`; `committable` additionally requires a surviving proposal; `fast_processing` (status) and `wording_changing` (proposal status) stay in the literals, read-only, for operations persisted before the amendment. No endpoint is removed or renamed; the catch-all command route accepts one more `action`. Full detail in [contracts/brain-dump-operations.md](contracts/brain-dump-operations.md).
- **Observability** — Every response carries `X-Correlation-ID` (`backend/app/api/middleware.py`) and every error body is `ErrorResponse{message, detail, reference_id}` (`backend/app/api/errors.py`). Mobile's `ErrorBanner` prints the server message plus `ref: <id>`; W-01 brings the web banners to the same contract (`describeError` over `getErrorContext`, rendering "… Ref: <id>"). Provider runs persist `checkpoint`, `attempt`, `recovery_count`, `error_code`, cost fields and `template_version`; progress is the status projection polled at 1.5 s → 8 s; cancellation is the distinct `cancelled` status with `status_history`.
- **Mobile/resilience/performance** — The operation is server-durable and closing the UI never cancels (ADR-0002). Web resume re-seeds the live tail from the latest unsuperseded segment and the timer from `audio_chunks.length` (1 s timeslices, pauses excluded) — D-01.f. Mobile pauses polling in the background and refetches on foreground (M-03.b). Browser preview is best-effort: a browser without it records and reviews the accurate transcript (D-02.d). No canvas code is touched, so the ~200-node responsiveness budget is unaffected.
- **Delivery boundary** — `tasks.md` (next stage) is portable planning input. Isolated worktree and branch, tests first, independent verification (`delivery-verifier`), ADR-0008 landing and the CI/Fly gates remain authoritative. The diff touches `backend/app/api/tasks.py`, an ASK exact path in `scripts/classify_path_risk.py`, so landing is ASK class through PR #194. `/verify-live` is approval-gated and is never run by an agent.
- **Design citation** — This feature has a user-visible surface. `design.md` is cited throughout, and the table below names the screen and state ids each section realizes.

| plan section | `design.md` ids realized |
|---|---|
| A1 Preview lane is a transcript readout | D-01.a, D-01.b, D-01.c, D-01.d, D-01.h, D-01.i, D-01.j, D-02.a, D-02.b, D-02.c, D-02.d, D-02.g |
| A2 Tasks minted once by the reconciler | D-03.a, D-03.b, D-03.c, D-03.h, D-03.i, D-03.k |
| A3 One-shot preview recovery | D-04.a, D-04.b, D-04.c, D-04.d, D-04.e, D-04.g, D-03.d, D-03.e, M-01.a, M-01.b, M-01.c, M-01.d, M-01.e, M-02.b, M-02.c |
| A4 Commit gate, receipts, legacy rules | D-03.f, D-03.g, D-03.j, D-03.k, M-02.a, M-02.d, M-02.f, M-02.g |
| A5 Web confirmations, cancel, resume, loading | D-01.e, D-01.f, D-01.g, D-02.e, D-02.f, D-03.l, D-03.m, D-04.f, D-05.a, D-05.b |
| A6 Mobile surfaces | M-01.a–e, M-02.a–h, M-03.a, M-03.b, M-03.c |
| W-01 web error banners, conflict line, empty copy | D-02.e, D-03.g, D-03.h, D-03.i, D-03.m, D-04.g |
| W-02 mobile confirmations and empty review | M-01.a–e, M-02.a–f, M-02.e, M-02.h |

## Project Structure

### Documentation (this feature)

```text
specs/015-transcript-first-brain-dump/
├── intake.md                   # the founder's ask and the waiver record (interview stage, waived)
├── spec.md                     # FR-001…FR-011, SC-001…SC-007, Clarifications
├── checklists/requirements.md  # 16/16
├── design.md + design/*.html   # D-01…D-05, M-01…M-03 with state ids
├── plan.md                     # this file
├── research.md                 # Phase 0: decisions already taken, as Decision / Rationale / Alternatives
├── data-model.md               # Phase 1: operation document deltas
├── contracts/
│   └── brain-dump-operations.md    # Phase 1: command route, guards, projection, error codes
├── quickstart.md               # Phase 1: runnable validation per runner
└── tasks.md                    # Phase 2: /speckit-tasks output — NOT created by this stage
```

### Source Code (repository root)

Only the branches this feature touches or relies on; every path exists on the branch.

```text
backend/
├── app/
│   ├── api/
│   │   ├── tasks.py                 # brain-dump route family incl. the catch-all command route,
│   │   │                            #   _VOICE_OFF_REACHABLE_ACTIONS, _to_brain_dump_response,
│   │   │                            #   _brain_dump_available_recovery_actions
│   │   ├── dependencies.py          # voice_brain_dump_enabled / require_voice_brain_dump_enabled (relied on)
│   │   ├── errors.py                # ErrorResponse mapping with reference_id (relied on)
│   │   └── middleware.py            # X-Correlation-ID (relied on)
│   ├── schemas/tasks.py             # BrainDumpRecoveryAction, BrainDumpOperationResponse, run/receipt responses
│   ├── workflows/voice_brain_dump/
│   │   ├── service.py               # VoiceBrainDumpService: append_brain_dump_transcript,
│   │   │                            #   can_reconcile_brain_dump_preview, reconcile_brain_dump_preview,
│   │   │                            #   _reconcile_accurate_checkpoint(source_checkpoint=…),
│   │   │                            #   retry_brain_dump_operation, brain_dump_operation_is_committable,
│   │   │                            #   run_due_brain_dump_provider_runs, withdraw_brain_dump_consent
│   │   ├── domain.py                # BrainDumpProviderRunCheckpoint, normalized_title,
│   │   │                            #   browser_preview_recovery_hypotheses, the operation documents
│   │   ├── repository.py            # OperationRepository (SQLite + JSON mirrors, command_lock)
│   │   └── adapters/reconciler.py   # OpenAITextReconciler (brain-dump-reconciler-v3), _validate_draft,
│   │                                #   _dedupe_draft, _fold_duplicate, _DISCOURSE_FILLER_TERMS
│   ├── container.py                 # wires VoiceBrainDumpService (caps, retention, reconciler, flag check)
│   └── main.py                      # periodic sweep calls run_due_brain_dump_provider_runs
└── tests/
    ├── test_voice_brain_dump_recovery.py
    ├── test_voice_brain_dump_reconciliation.py
    ├── test_brain_dump_operations_api.py
    └── test_task_branch_coverage.py      # api/tasks.py and voice-service branch coverage; carries no 015 id

frontend/
├── src/
│   ├── api/client.ts                # ApiError (status, payload, correlationId); commandBrainDump(... "reconcile_preview" ...)
│   ├── api/taskTypes.ts             # BrainDumpOperationResponse.available_recovery_actions / reconciliation_quality
│   ├── utils/error.ts               # getErrorContext (consumed by W-01)
│   └── features/brain-dump/
│       ├── BrainDumpRoute.tsx       # Recording / Processing / Review / Recovery / Loading surfaces, DestructiveConfirm
│       ├── brainDumpStatusLabels.ts # operationStatusLabels, processingStatuses
│       ├── brainDumpNavigation.ts   # overlay routing over a background location
│       └── BrainDumpRoute.test.tsx
└── tests/
    └── native-tasks-voice-brain-dump.compose.spec.ts   # Compose Playwright journeys

mobile/
└── src/
    ├── api/types.ts                 # available_recovery_actions and BrainDumpAction incl. reconcile_preview
    ├── api/client.ts                # ApiError with correlationId (relied on)
    ├── components/ErrorBanner.tsx   # server message + "ref: <id>" (relied on)
    ├── braindump/machine.ts         # POLLABLE statuses, nextPollDelay, canCommit, processingStageLabel
    └── app/brain-dump/
        ├── [operationId].tsx        # BrainDumpOperationScreen: recovery, review, confirmations (W-02)
        └── __tests__/review.test.tsx

docs/decisions/0002-async-voice-operation-substrate.md   # the two 2026-09-05 amendments (already written)
```

**Structure Decision**: No new module, package, route family or store. The feature lives where ADR-0001 and ADR-0002 already place voice capture: the `voice_brain_dump` application workflow (`service.py`, `domain.py`, `adapters/reconciler.py`), the existing owner-scoped brain-dump route family in `backend/app/api/tasks.py`, the response contracts in `backend/app/schemas/tasks.py`, the web brain-dump overlay feature folder and the Expo brain-dump operation screen. `app/modules/tasks/` is reached only through the injected `TaskPort` at commit, exactly as before; routes receive the service through `Depends(get_voice_brain_dump_service)`.

## Architecture as built

### A1. The preview lane is a transcript readout, never a task source (FR-001, FR-002 → D-01, D-02)

- **Server.** `append_brain_dump_transcript` (`service.py`) is `@_serialized_write` and replays by `Idempotency-Key`. It requires `consent.external_processing_allowed` (else `TRANSCRIPT_CONSENT_REQUIRED`) and status `recording` or `paused`, upserts `BrainDumpTranscriptSegmentDocument`s keyed by `sequence` (an `interim` segment may be rewritten in place; a changed `stable` one raises `ConflictError`, 409) and persists **segments only**. No proposal, patch or `fast` provider run is created; the "fast" extraction method is retired and `wording_changing` is never produced. Segments default to `provider_role="browser_preview"` and carry `stability`, `content_sha256` and `supersedes_segment_ids`; accurate-STT output later supersedes them, which is what relabels the readout (D-02.c).
- **Web.** `RecordingSurface` renders settled utterances through `TranscriptReadout` under "What you've said · browser preview" and the forming hypothesis beside the microphone (`TranscriptTail`); no proposal card is mounted while the status is `recording` or `paused` (D-01.a–d, SC-002). Upload and append failures surface as banners while capture keeps running (D-01.j); consent withdrawal mid-capture stops the recognizer and recorder locally before the round trip (D-01.h). `ProcessingSurface` shows `operationStatusLabels[status]` and the same readout under the processing headings ("Browser preview · provisional", then "Accurate transcript"), with an empty dashed readout when no settled preview exists (D-02.a–d).
- **Mobile.** Has no preview lane and captures nothing new. `processingStageLabel` names the stage (M-03.b).

### A2. Tasks are minted once, by the reconciler, as GTD next actions (FR-003, FR-004, FR-005 → D-03)

- **Prompt and provenance.** `OpenAITextReconciler.template_version = "brain-dump-reconciler-v3"` (`adapters/reconciler.py`) phrases every title verb-first in the language spoken, drops discourse fillers and modal scaffolding, and proposes each distinct action once. The version string is persisted on the succeeded provider run and copied into each action receipt, so output produced under different prompt versions stays distinguishable without storing prompt text.
- **Guards independent of the model** (the adapter's `_materialize` loop). `_validate_draft` fails the whole call on protocol defects (model-chosen ids, unknown targets, unknown provenance) and drops a single operation as `_SemanticGroundingFailure` when its title names no action or object — the filler check consults `_DISCOURSE_FILLER_TERMS` (English and Russian fillers such as "so", "um", «так», «ну», «потом») together with the prefix and negation scaffolding sets. `_dedupe_draft` folds a title restated within one envelope into the survivor via `_fold_duplicate` (union of cited segments and predecessors; two structural operations converging on one title become a `merge`), rewrites an `add` that restates an active proposal into an `update` affirming it, and drops an `update` converging on another active title. `_titles_equivalent` compares content tokens after stripping scaffolding, fillers, articles, quotes, punctuation and case, and falls back to `domain.normalized_title`, which is also what the tombstone check in `_validate_draft` keys on — so a deleted «Купить молоко.» cannot be revived as «купить молоко». An envelope whose every operation was dropped raises `ValidationFailure("All reconciler operations were dropped as ungrounded: …")`, which the service records as `RECONCILER_VALIDATION_REJECTED`.
- **Service side.** `_reconcile_accurate_checkpoint(source_checkpoint="accurate_transcribed")` sends the reconciler the current proposals (empty for a new operation, so only `add` is valid), applies the returned patches through `_apply_reconciler_patches`, logs dropped operations by count and fixed reason, and freezes the run at `checkpoint="reconciled"` with `reconciliation_quality="accurate"`. In `AppEnvironment.TEST` the container wires `DeterministicTextReconciler`, whose fixture titles flow through `_reconcile_accurate_titles` into the same opaque-id patch projection.
- **Empty review.** `brain_dump_operation_is_committable` returns false when no non-deleted proposal exists and the projection carries `committable=false`. The web renders D-03.h/D-03.i ("No tasks to review", the status box, the transcript of what was heard) and mounts **no** Send button when `proposals.length === 0`; mobile `canCommit` requires `visibleProposals(operation).length > 0` (M-02.e).

### A3. One-shot, owner-chosen recovery from the browser transcript (FR-009, FR-010 → D-04, M-01, D-03.d/e, M-02.b/c)

- **Predicate** (`can_reconcile_brain_dump_preview`, `service.py`) = state ∧ consent ∧ cost. State (`_preview_recovery_state_eligible`): `status == "terminal_error"`; the last provider run is a `terminal_error` of role `accurate_stt` or `reconciler`; no non-deleted proposal survives (so `review_provisional` and `reconcile_preview` are mutually exclusive); no run anywhere in `provider_runs` carries checkpoint `preview_transcribed` or `preview_reconciled` (one shot, success or failure alike); `browser_preview_recovery_hypotheses(segments)` is non-empty — stable, `browser_preview`, unsuperseded, non-blank segments with `end_ms > start_ms`. Consent (`_preview_recovery_consent_refusal`): `external_processing_allowed` true and `consent_withdrawn_at` unset, else `RECONCILER_CONSENT_REQUIRED`; the reconciler's `provider_id` in the consented provider set, else `RECONCILER_CONSENT_PROVIDER_MISMATCH`. Cost (`_preview_recovery_within_cost_cap`): `provider_cost_budget_allows(cumulative_provider_cost_usd(provider_runs), reconciler.max_cost_usd_per_operation, max_cumulative_cost_usd_per_operation)`. The predicate is deliberately not gated on the accurate lane's exhausted recovery budget.
- **Command** (`reconcile_brain_dump_preview`). Under `command_lock(owner_id)` with idempotency replay and `_assert_revision`; refuses with a `ValidationFailure` whose message starts with the fixed code — `BRAIN_DUMP_PREVIEW_RECOVERY_UNAVAILABLE`, `RECONCILER_CONSENT_REQUIRED` or `RECONCILER_CONSENT_PROVIDER_MISMATCH`, `OPERATION_COST_BUDGET_EXCEEDED` — before any external call; otherwise appends a `pending` `reconciler` run at `checkpoint="preview_transcribed"` with `attempt=1`, `recovery_count=0`, `reserved_cost_usd` equal to the reconciler's per-operation cap and `input_hash` = SHA-256 of the joined stable preview text, moves the operation to `reconciling`, stores the idempotency record and calls `runner_wake()`. No audio is read and no STT call is made.
- **Runner.** `run_due_brain_dump_provider_runs` skips owners whose `voice_brain_dump` flag is OFF, claims the run (`pending` → `running` under a CAS lease of `provider_run_lease_seconds`), and dispatches a claimed reconciler run at `preview_transcribed` to `_reconcile_claimed_preview_run`, which hands exactly `browser_preview_recovery_hypotheses(segments)` — role kept as `browser_preview` — to `_reconcile_accurate_checkpoint(source_checkpoint="preview_transcribed")`. Cost admission, the consent re-check, patch projection and failure persistence are the shared path; only the labels differ: success writes `reconciliation_quality="provisional_only"`, `manual_review=True`, and freezes at `checkpoint="preview_reconciled"` — never `reconciled` — so the canonical `accurate` commit gate is unsatisfiable from preview text. The outcome is persisted only if the operation revision is unchanged since the claim.
- **Retry of the recovery.** A *retryable* preview failure is retried with the ordinary `retry` command: `retry_brain_dump_operation` detects `resume_preview` (latest run is a reconciler at `preview_transcribed`), re-queues at `preview_transcribed` over the persisted text without requiring `sealed_manifest_hash` (raw audio may already be gone), bounded by `max_operation_recoveries` → `OPERATION_RECOVERY_BUDGET_EXHAUSTED` → `terminal_error`, after which the one-shot rule leaves only `cancel`.
- **Projection.** `_brain_dump_available_recovery_actions` (`api/tasks.py`) emits, in render order: `retry` (status `retryable_error`), `review_provisional` (`can_review_brain_dump_provisionally`), `reconcile_preview` (`service.can_reconcile_preview`), `cancel` (status `retryable_error` or `terminal_error`). Both clients render only what is advertised: the web `RecoverySurface` (D-04.a–e) and the mobile failure card (M-01.a–d) show "Extract tasks from the browser transcript" with the helper sentence naming the destination; refusals render in the surface's error banner (D-04.g, M-01.e).
- **Labelling.** The web `ReviewSurface` shows the amber provisional banner whenever `reconciliation_quality === "provisional_only"`, adding the not-saveable sentence while `committable` is false (D-03.d, D-03.e); mobile shows the "Provisional only —" badge under the same condition, saveable or not (M-02.b, M-02.c).

### A4. Commit gate, receipts and legacy rules (FR-005, FR-010, FR-011 → D-03.f/g/j/k, M-02.a/d/f/g)

- `commit_brain_dump_operation` requires `awaiting_confirmation`, then: `is_provisional_review = legacy_import == "legacy_preview_only" or manual_review`; a non-committable, non-provisional operation without a frozen `reconciled` batch is refused `BRAIN_DUMP_NOT_RECONCILED`; open conflicts are refused with the offending `proposal_ids`; outside provisional review an untouched `provisional` proposal is refused `BRAIN_DUMP_PROPOSAL_NOT_RECONCILED` (FR-011, the pre-amendment rule); then `_freeze_commit_batch` snapshots title-only `create_native_inbox_task` actions with deterministic child keys (`brain_dump_action:{operation_id}:{proposal_id}`) and commits through the injected `TaskPort`.
- `_action_receipt` names the run whose model produced the titles — the last succeeded reconciler run at `reconciled` **or** `preview_reconciled` — and copies `reconciliation_quality` from the operation, so a preview recovery's tasks carry `provisional_only` plus that run's provider, model and `template_version` after the working artifacts expire (D-03.k, M-02.g).
- The web disables Send while `!committable || hasUnresolvedConflicts || isSaving` and shows "Sending…" during commit (D-03.g, D-03.j); mobile `canCommit` mirrors it (M-02.d, M-02.f).

### A5. Web: confirmations, cancel processing, resume, loading (FR-006, FR-007, FR-008 → D-01.e–g, D-02.e/f, D-03.l/m, D-04.f, D-05)

- `DestructiveConfirm` (`BrainDumpRoute.tsx`) replaces its trigger in place with the question, focuses the safe answer on open, closes on Escape (`preventDefault` and `stopPropagation`, so the overlay does not also dismiss) and restores focus to the trigger; only the destructive answer calls `onConfirm`, then the question closes so a stale-revision failure reports in the surface's alert (D-03.m). Four uses: Discard on D-01 (D-01.g), "Cancel processing" on D-02 (D-02.f), "Discard all" on D-03 (D-03.l), "Delete recording" on D-04 (D-04.f). All four run the idempotent `cancel` command; the server keeps a `completed` or `cancelled` status on a repeated cancel and never removes saved Inbox tasks.
- `ProcessingSurface` offers the cancel confirmation while the server advances; processing continues undisturbed while the question is open (D-02.f). The poll (`POLL_INITIAL_MS=1500`, doubling to `POLL_MAX_MS=8000`) covers `processingStatuses` plus `retryable_error` (D-02.g).
- Resume: opening `/brain-dump/{id}` cold renders the "Loading your brain dump" panel until the projection arrives (D-05.a); a failed fetch falls through to the recording surface carrying the error (D-05.b). While the status is `recording` or `paused` and no live recognizer exists, `latestSegmentText(segments)` seeds the tail and `RecordingTimer` starts from `audio_chunks.length` seconds (D-01.f, SC-005); a recording begun in-session starts at zero; Pause holds the timer (D-01.e).

### A6. Mobile surfaces (FR-005, FR-007, FR-009, FR-010 → M-01, M-02, M-03)

- `BrainDumpOperationScreen` (`mobile/src/app/brain-dump/[operationId].tsx`) polls the `POLLABLE` statuses with `nextPollDelay` (1.5 s → 8 s), pauses in the background and refetches on foreground (M-03.a, M-03.b), renders `ErrorBanner` (server message plus `ref:`) for load and action failures (M-03.c, M-01.e), and renders exactly the recovery actions the server advertises (M-01.a–d). `runCommand` accepts `reconcile_preview`, posts it with the current revision and a fresh idempotency key, then polls `reconciling` until the provisional review opens (M-02.b, M-02.c).
- W-02 adds the platform-dialog confirmations, the header rename and the honest empty review (M-02.e); see below.

## Contracts

Normative detail is in [contracts/brain-dump-operations.md](contracts/brain-dump-operations.md); the summary:

| surface | as built |
|---|---|
| `POST /api/brain-dump-operations/{operation_id}/{action}` | catch-all command route; `Idempotency-Key` header required (400 `Idempotency-Key header is required.` otherwise); body `ExpectedRevisionRequest`; actions `pause`, `resume`, `finish`, `cancel`, `commit`, `retry`, `review_provisional`, **`reconcile_preview`**, `withdraw_consent`, `delete_raw_audio`; anything else → 400 `Unsupported brain dump operation command.` |
| flag semantics | `_VOICE_OFF_REACHABLE_ACTIONS = {withdraw_consent, cancel, delete_raw_audio}` stay reachable when `voice_brain_dump` is OFF; every other action — including `reconcile_preview`, which spends budget and ships text to a vendor — returns 404 `Voice brain dump is not available.`; `GET /api/brain-dump-operations/{id}` is never gated |
| projection | `BrainDumpOperationResponse.available_recovery_actions: BrainDumpRecoveryAction[]` with `BrainDumpRecoveryAction = Literal["retry", "review_provisional", "reconcile_preview", "cancel"]`; `committable`; `provider_runs[].checkpoint` ∈ `{sealed, accurate_transcribed, reconciled, preview_transcribed, preview_reconciled}`; `reconciliation_quality` ∈ `{none, provisional_only, accurate, conflicted}` on the operation and on each `action_receipts[]` entry |
| error codes surfaced to clients | `BRAIN_DUMP_PREVIEW_RECOVERY_UNAVAILABLE`, `RECONCILER_CONSENT_REQUIRED`, `RECONCILER_CONSENT_PROVIDER_MISMATCH`, `OPERATION_COST_BUDGET_EXCEEDED` (HTTP 400, `message` prefixed with the code, `reference_id` = the correlation id); persisted run `error_code`s additionally include `OPERATION_RECOVERY_BUDGET_EXHAUSTED`, `RECONCILER_VALIDATION_REJECTED`, `CONSENT_WITHDRAWN` and the fallback `PROVIDER_ERROR_UNSPECIFIED` |
| quality marking | preview recovery → `reconciliation_quality="provisional_only"`, `manual_review=true`, run frozen at `preview_reconciled`; accurate path → `accurate`, `reconciled` |

Compatibility: every change is an additive literal plus one more accepted `action`. A client that ignores unknown `available_recovery_actions` entries keeps working; `fast_processing` and `wording_changing` remain valid read-only values for operations persisted before 2026-09-05. Schema-first order (backend `schemas/tasks.py`, then `taskTypes.ts` and `types.ts`) was followed on the branch.

## Data handling and observability

- **What is stored**: no new kind of durable record. The recovery adds one `BrainDumpProviderRunDocument` of the existing kind carrying a new checkpoint literal; receipts already carry `reconciliation_quality`. Retention is unchanged: `raw_audio_expires_at` is stamped once at the first successful reconciliation as now + `BRAIN_BUDDY_VOICE_RAW_AUDIO_RETENTION_SECONDS` (86 400); uncommitted working artifacts expire after 604 800 s; `cancel` deletes audio immediately and re-anchors `working_artifacts_expires_at`; consent withdrawal deletes audio and schedules the transcript for the sweep. Account export and purge already cover operations, mirrors and media (`docs/data-retention.md`).
- **What is logged**: `brain_dump_reconciler_dropped_operations operation_id=<id> dropped=<n> reasons=<fixed adapter strings>` — the reasons are the adapter's constant skip strings, never a title or transcript; provider failures are stored as allowlisted codes (`_redact_provider_error`, fallback `PROVIDER_ERROR_UNSPECIFIED`). No transcript text, title text, audio, path or credential enters logs, run envelopes or Allure attachments.
- **Correlation**: `X-Correlation-ID` on every response and `reference_id` in every error body; both clients surface it (`ref:` on mobile, `Ref:` on the web via W-01) so a refused recovery can be quoted for support without quoting content.
- **Progress and state**: `status`, `status_history`, `provider_runs[].checkpoint`, `attempt`, `recovery_count`, `error_code`, `reserved_cost_usd` and `consumed_cost_usd` per run; clients poll the projection — stage words, no fabricated percentage.

## Failure handling, retry and resume (ADR-0002)

| situation | server | web | mobile |
|---|---|---|---|
| retryable accurate-STT or reconciler failure | `retryable_error`; `retry` re-queues from `sealed` or `accurate_transcribed`; bounded by `max_operation_recoveries` | D-04.a / D-04.b retry plus confirmed delete | M-01.a "Try again" |
| terminal failure, proposals survive (legacy or seeded) | `review_provisional` → `awaiting_confirmation`, `provisional_only`, `manual_review` | D-04.c → D-03.d / D-03.e | M-01.b → M-02.b / M-02.c |
| terminal failure, no proposals, stable preview text, consent standing, budget left | `reconcile_preview` → `reconciling` → `awaiting_confirmation` (`provisional_only`, `preview_reconciled`) | D-04.d → D-02 → D-03.d | M-01.c → M-03.b → M-02.b |
| same, but refused or already spent | `BRAIN_DUMP_PREVIEW_RECOVERY_UNAVAILABLE` / consent / cost codes; the action is not advertised | D-04.e, D-04.g | M-01.d, M-01.e |
| consent withdrawn mid-flight | the in-flight run becomes `terminal_error` `CONSENT_WITHDRAWN`; audio deleted; recovery unavailable | D-01.h chip, then D-04.e | M-01.d |
| cancel during processing | idempotent `cancel`; a repeated cancel keeps `cancelled`; saved tasks are never removed | D-02.f, D-03.m | W-02 dialog |
| stale `expected_revision` | `ConflictError` 409 "… has newer changes; reload before saving." | rose banner; the question closes | `ErrorBanner` plus refetch |
| process death or expired lease | an expired `running` lease is reclaimable by the runner and swept by `recover_due_provider_leases`; the outcome is persisted only if the revision is unchanged since the claim | D-02.g resume on reopen | M-03.b |
| UI closed, device offline | the operation is server-durable; reopening polls by id | D-05.a → surface by status | M-03.a |

## Work items landing on this branch

Both items were identified by the design stage ("Requirements with no affordance" and "Open decisions for the human" 1, 2, 4 and 5 in `design.md`) and are being implemented on `claude/brain-dump-mechanics-t35ab7` while this plan is written; their Vitest and Jest cases already carry `015-` ids. `/speckit-tasks` should list them as the only open tasks and `/speckit-accept` grades their final state.

- **W-01 — web error banners, conflict line, empty-review copy (FR-005, FR-009 → D-02.e, D-03.g, D-03.h, D-03.i, D-03.m, D-04.g).** Files: `frontend/src/features/brain-dump/BrainDumpRoute.tsx`, `frontend/src/features/brain-dump/BrainDumpRoute.test.tsx`, reusing `frontend/src/utils/error.ts` (`getErrorContext`). Every banner shows the server's `message` — which begins with the fixed reason code for a refused recovery — and the request's `reference_id` ("… Ref: <id>") instead of `ApiError.message`, which is the bare HTTP status text; a Send disabled by open conflicts gets the text reason "Resolve N conflicts before sending." (linked by `aria-describedby`); the D-03.h/D-03.i copy names the exit the screen actually has (discard, which returns to a fresh recording). Test ids: `015-FR-009` (a refusal shows reason and reference, not the status), `015-FR-005`.
- **W-02 — mobile destructive confirmations and honest empty review (FR-005, FR-007, SC-004 → M-01.a–e, M-02.a–f, M-02.e, M-02.h).** Files: `mobile/src/app/brain-dump/[operationId].tsx`, `mobile/src/app/brain-dump/__tests__/review.test.tsx`. "Discard everything" (M-01), "Discard all" (M-02) and the review header's discard control confirm through the platform dialog (`Alert.alert` with the cancel-styled safe answer listed first and `cancelable: true`, so any other dismissal keeps everything); the header control's accessible name changes from "Close" to one that says it discards the recording; the raw-audio control's accessible name says it deletes audio only; the empty review states that nothing was proposed and hides the confirm control instead of rendering a disabled "Confirm 0 additions". Test ids: `015-FR-007`, `015-SC-004`, `015-FR-005`.

A mobile transcript readout and "Cancel processing" (M-03.b) stay out of scope by the ninth clarification; the web tap-target exception (open decision 6) is accepted as inherited and is not a work item.

## Test strategy

| runner | files | requirement ids carried | command | floor / gate |
|---|---|---|---|---|
| pytest + `TestClient` | `backend/tests/test_voice_brain_dump_recovery.py`, `backend/tests/test_voice_brain_dump_reconciliation.py`, `backend/tests/test_brain_dump_operations_api.py` (plus `backend/tests/test_task_branch_coverage.py` for route branches, no 015 id) | FR-002, FR-003, FR-004, FR-005, FR-009, FR-011, SC-001, SC-002, SC-003, SC-006 | `make test-backend` (bare loop: `cd backend && pytest`) | `--cov-fail-under=95` in `backend/pyproject.toml` and `backend/coverage-floor.json` (line 0.9847, branch 0.9561) via `scripts/validate_coverage_floor.py`; Allure taxonomy validator |
| Vitest + Testing Library | `frontend/src/features/brain-dump/BrainDumpRoute.test.tsx` | FR-001, FR-005, FR-006, FR-007, FR-008, FR-009, FR-010, SC-002, SC-003, SC-004, SC-005, SC-006, SC-007 | `make test-frontend` (`npm run test:coverage`) | `frontend/coverage-floor.json` statements 0.9876, branches 0.9777, functions 0.9864, lines 0.9884; no `istanbul ignore` (rejected by `validate_ci_artifacts.py coverage-suppressions`) |
| Playwright (Compose) | `frontend/tests/native-tasks-voice-brain-dump.compose.spec.ts` | FR-001, FR-003, FR-005, FR-007, SC-002 | `make test-e2e` (`scripts/run_playwright_e2e.sh`, needs Docker Compose) — the CI `e2e` job; not runnable in a session without Docker | `validate_ci_artifacts.py results` and `product-e2e-results`; Allure quality gate |
| Jest (Expo) | `mobile/src/app/brain-dump/__tests__/review.test.tsx` | FR-009, FR-010, SC-006, SC-007 (plus FR-005, FR-007, SC-004 with W-02) | `make test-mobile` (`npx jest --coverage`) | `mobile/coverage-floor.json` 0.94 statements, 0.88 branches, 0.95 functions, 0.94 lines |
| traceability | all of the above | all 18 | `python3 scripts/check_requirement_coverage.py specs/015-transcript-first-brain-dump` | 18/18 at plan time |

- **Mutation gate**: `backend/mutation-enforced-scope.txt` (the ADR-0016 enforced tier) lists only the tree, version and relation services and repositories; this feature touches none of them, so the `mutation-gate` job measures nothing here and cannot block. The nightly observed tier (`mutation-quality.yml`), frontend Stryker (ADR-0013) and `make mutation-mobile` (ADR-0015) are report-only; the reconciler guards are natural candidates for a scoped `npx stryker run --mutate` or mutmut pass, but no threshold binds them.
- **Allure taxonomy**: central defaults in `backend/tests/allure_taxonomy.py`, `frontend/src/test/allureTaxonomy.ts`, `mobile/src/test/allureTaxonomy.ts` and `frontend/tests/allure.fixtures.ts`; every test in the table has a human title and at least one step; the `allure-report` job grades the run with `maxFailures: 0`.
- **Not automated**: the founder's real-voice check of the reference utterance (`/verify-live`, approval-gated, spends provider money) — a human step, never a subagent or scheduled run.

## Release gates

1. **Flag**: `voice_brain_dump` (ADR-0008 rollout OFF → INTERNAL → ON, resolved through the runtime flag resolver of feature 010 / ADR-0018). Forward actions — `transcript`, `audio`, `seal`, proposal `PATCH`, `commit`, `retry`, `review_provisional`, `reconcile_preview` — are gated; reads, `cancel`, `withdraw_consent` and `delete_raw_audio` are not; the runner pauses provider work for an owner whose flag is OFF (`voice_enabled_for_owner`). No new flag is introduced.
2. **CI**: `.github/workflows/ci.yml` lanes `spec-kit` (this directory passes `check_spec_kit_specs.py` once `tasks.md` exists), `backend`, `frontend`, `mobile`, `mutation-gate` (no-op scope here), `docker`, `e2e` (Compose Playwright, after `backend` and `frontend`), `allure-report`, `full-ci`. Wait for `full-ci` green on the exact SHA.
3. **Landing (ADR-0008)**: the diff touches `backend/app/api/tasks.py` (ASK exact path: the owner-filtered task API) → ASK class → PR #194 carries the review evidence and lands only through the recorded-approval path; merging does not by itself update `main`. Fly deploys `main` through the normal release path (`fly.backend.toml`, `fly.frontend.toml`).
4. **Post-deploy**: `/self-verify` (`make verify-all`) is the free everyday check; the paid `/verify-live` drive is the founder's call.
5. **Rollback**: pure code rollback; no migration, no flag-state change, no new store. An operation already frozen at `preview_reconciled` remains readable by older code as `awaiting_confirmation` with `provisional_only` and `manual_review=true`, which is exactly the pre-existing `review_provisional` shape.

## Risk class and landing class

- **Declared (ADR-0012)**: `medium`. Reasoning: the change adds no authentication, session, invite, migration, CI/workflow, deploy, secrets or permissions logic; it adds one action branch to an existing owner-scoped command route, one predicate and one checkpoint literal in the voice workflow, and client rendering. Owner scoping (404 for a wrong-owner id) and the session-cookie path are untouched.
- **Derived**: `scripts/spec_kit_planning_review.py preflight` runs every path-like token in `spec.md`, `plan.md` and `design.md` through `scripts/classify_path_risk.py`; `backend/app/api/tasks.py` is an ASK exact path and any `scripts/*.py` is under an ASK prefix, so the classifier derives **`high`**. Derivation only raises (ADR-0012), so the review campaign runs at `high`: the `adversarial-high-risk` lens joins the panel and `approved` additionally requires a recorded human sign-off at `.specify/workflows/runs/<run-id>/human-signoff.json`. This plan does not argue the classifier down; it records that the escalation comes from *mentioning* an ASK path, which is the asymmetry the classifier chooses on purpose.
- **Landing class (ADR-0008)**: ASK, for the same file; see Release gates.

## Complexity Tracking

No constitution principle is violated. The deviations below are procedural and are recorded so the review and acceptance stages see them:

| deviation | why needed | simpler alternative rejected because |
|---|---|---|
| Retro plan: code (PR #194) preceded spec, design and plan | the founder reported a defect and directed «просто доделай»; the fix shipped the same day | leaving 015 undocumented would fail the `check_spec_kit_specs.py` minimum and leave the ADR-0002 amendment as the only record |
| Interview and design sign-off waived by the founder (seventh clarification; recorded in `intake.md`) | the founder's explicit directive | the interview cannot run in a subagent and the founder declined further elicitation |
| Spec 002 narrowed in prose, not edited | first clarification ("path A"); 002's normative files are hash-pinned | editing 002 would invalidate its grandfathering and force its whole pipeline to rerun |
| `fast_processing` and `wording_changing` retained in the literals | operations persisted before 2026-09-05 still carry them | removing them would make old operations unreadable — a breaking contract change for no user benefit |
| `test_task_branch_coverage.py` carries no 015 id | it exercises route and service branches generically | requirement tracing relies on the three other backend files, which already give 18/18 |
| Declared `medium`, derived `high` | see [Risk class and landing class](#risk-class-and-landing-class) | declaring `high` up front would misstate the change; `low` can never be derived and is unjustified here |

## Phase outputs

- **Phase 0** — [research.md](research.md): the ten clarifications and the two ADR-0002 amendments restated as Decision / Rationale / Alternatives; no unresolved-clarification marker remained to research.
- **Phase 1** — [data-model.md](data-model.md) (operation document deltas, checkpoint literals, quality and manual-review marking, receipts, state transitions), [contracts/brain-dump-operations.md](contracts/brain-dump-operations.md) (command route, guards, projection, error envelope), [quickstart.md](quickstart.md) (runnable validation per runner).
- **Phase 2** — `tasks.md` is produced by `/speckit-tasks` after the `/speckit-review` gate; at plan time the only open work is W-01 and W-02.
