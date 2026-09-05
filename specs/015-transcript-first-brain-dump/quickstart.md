# Quickstart: validating transcript-first voice brain dump

**Feature**: `specs/015-transcript-first-brain-dump/` · **Plan**: [plan.md](plan.md) · **Contracts**: [contracts/brain-dump-operations.md](contracts/brain-dump-operations.md)

Runnable, key-free validation for the behaviour this feature specifies. Each
command below is the one the corresponding CI lane runs (or a narrower slice of
it); expected outcomes are stated so the acceptance auditor can compare. Nothing
here spends provider money — the paid `/verify-live` drive is approval-gated and
belongs to the founder.

## Prerequisites

- Backend: the `backend/` virtual environment with dev dependencies (see the
  `Makefile` install targets); `cd backend && pytest` runs against the
  `DeterministicTextReconciler` that `backend/app/container.py` wires in
  `AppEnvironment.TEST`, so no API key is needed.
- Frontend: `cd frontend && npm ci` (Node 20.19.0 in CI).
- Mobile: `cd mobile && npm ci`.
- Compose e2e: Docker with Compose; `cp .env.example .env` first.

## 1. Requirement traceability (fast, deterministic)

```bash
python3 scripts/check_requirement_coverage.py specs/015-transcript-first-brain-dump
```

Expected: every `015-FR-001…011` and `015-SC-001…007` listed `ok` with at least
one test file; final line `Requirement coverage passed: 18/18 traced`.

```bash
python3 scripts/check_spec_kit_specs.py
```

Expected once `tasks.md` exists: no `specs/015-transcript-first-brain-dump` line
in the failures. Until `/speckit-tasks` runs, the only complaint about 015 is
`missing tasks.md`.

## 2. Backend (pytest + FastAPI TestClient)

Targeted slice for this feature:

```bash
cd backend && pytest \
  tests/test_voice_brain_dump_reconciliation.py \
  tests/test_voice_brain_dump_recovery.py \
  tests/test_brain_dump_operations_api.py -q
```

Expected: all pass. What the named tests prove:

| test (by docstring / name) | requirement | outcome |
|---|---|---|
| `test_seal_reconciles_a_filler_prefixed_dump_into_clean_next_actions` (`test_brain_dump_operations_api.py`) | 015-FR-004, 015-FR-005, 015-SC-001 | the review list is GTD next actions, never raw preview text; `committable` true with nothing deleted |
| `test_review_with_no_surviving_proposals_is_not_committable` | 015-FR-005, 015-SC-003 | an empty review has `committable=false` and `commit` is refused |
| the `015-FR-002` cases around `append_brain_dump_transcript` | 015-FR-002, 015-SC-002 | interim and final preview segments persist as transcript only; no proposal is created |
| `test_015_FR_009_preview_recovery_predicate_requires_every_clause` (`test_voice_brain_dump_recovery.py`) | 015-FR-009 | `reconcile_preview` is advertised only while every clause holds (state, one shot, consent, cost) |
| `test_015_FR_009_reconcile_preview_queues_one_provisional_reconciler_run` | 015-FR-009 | the command persists a `pending` run at `preview_transcribed`, wakes the runner, replays idempotently |
| `test_015_FR_009_runner_reconciles_exactly_the_stable_unsuperseded_preview_text` | 015-FR-009 | the reconciler receives only stable, unsuperseded preview text; the result is `provisional_only` at `preview_reconciled` |
| `test_015_FR_009_preview_recovery_commit_creates_inbox_tasks_with_provisional_receipts` | 015-FR-009, 015-FR-010 | committing a preview recovery creates Inbox tasks whose receipts say `provisional_only` |
| `test_015_FR_009_reconcile_preview_recovers_provisional_tasks_from_browser_preview_text` (`test_brain_dump_operations_api.py`) | 015-FR-009, 015-SC-006 | the HTTP journey: terminal STT failure → `reconcile_preview` → provisional review in one action |
| the `015-FR-003` / `015-FR-004` cases in `test_voice_brain_dump_reconciliation.py` | 015-FR-003, 015-FR-004, 015-SC-003 | prompt v3 provenance, filler titles dropped on their own, duplicates folded with provenance, affirmation instead of a twin, tombstone blocks punctuation variants, an all-filler envelope is rejected |

Full lane with the coverage floor and the Allure taxonomy validator:

```bash
make test-backend
```

Expected: pytest green, `--cov-fail-under=95` satisfied, `scripts/validate_coverage_floor.py` accepts `backend/coverage.xml` against `backend/coverage-floor.json` (line 0.9847, branch 0.9561), taxonomy validator passes.

## 3. Web (Vitest + Testing Library)

```bash
cd frontend && npx vitest run src/features/brain-dump/BrainDumpRoute.test.tsx
```

Expected: all pass, including the `015-` titled cases — transcript instead of
draft cards while recording (FR-001, SC-002), processing stages with the
transcript and no cards (FR-006), the four inline confirmations with focus on
the safe answer and Escape restoring the trigger (FR-007, SC-004), resume
seeding of the tail and timer (FR-008, SC-005), `reconcile_preview` offered and
labelled provisional (FR-009, FR-010, SC-006, SC-007), and (W-01) a refused
recovery showing the server's reason and reference rather than the HTTP status.

Full lane:

```bash
make test-frontend
```

Expected: `frontend/coverage-floor.json` satisfied (statements 0.9876, branches 0.9777, functions 0.9864, lines 0.9884); taxonomy validator passes.

## 4. Mobile (Jest over the fake backend)

```bash
cd mobile && npx jest src/app/brain-dump/__tests__/review.test.tsx
```

Expected: all pass, including `015-FR-009` (the recovery is offered when the
server advertises it and posts `reconcile_preview` with the current revision),
`015-FR-010` / `015-SC-007` (provisional badge, saveable or not), `015-SC-006`,
and (W-02) the platform-dialog confirmations for the three destructive exits.

Full lane:

```bash
make test-mobile
```

Expected: `mobile/coverage-floor.json` satisfied (0.94 / 0.88 / 0.95 / 0.94).

## 5. Compose end-to-end (Playwright, CI `e2e` job)

```bash
make test-e2e
```

Runs `scripts/run_playwright_e2e.sh` (builds and boots the Compose stack on
free ports, runs `frontend/tests/*.spec.ts`, validates the Allure results). The
015 journeys in `frontend/tests/native-tasks-voice-brain-dump.compose.spec.ts`:

- "015-FR-001 015-SC-002 Voice Brain Dump shows a live transcript, reviews the reconciled task and saves exactly one Inbox task";
- "015-FR-001 015-FR-003 015-FR-005 015-FR-007 015-SC-002 … shows a mixed-language preview as transcript and reviews only reconciled next actions" (with the inline discard confirmation step);
- "015-FR-007 Voice Brain Dump failures are visible and preserve recoverable live sessions".

Expected: green in the CI `e2e` lane; it needs Docker and is not runnable in a
sandbox without it.

## 6. Everything the merge gate runs

```bash
make verify-all
```

`check-specs`, `validate-ci`, backend, frontend and mobile lanes, then `test-e2e`
— the `/self-verify` equivalent. Wait for `full-ci` green on the exact SHA before
any landing decision; landing is ASK class (see `plan.md`, Release gates).

## 7. Manual acceptance of the founder's scenario (human only)

With a real provider configured and the `voice_brain_dump` flag ON for the
account, record «Так, надо купить молоко. [pause] Сходить в магазин. [pause]
Покрасить комнату.» in the web overlay and press Stop.

Expected (SC-001, SC-002): while speaking, the readout fills and no task card
appears; the review lists exactly «Купить молоко», «Сходить в магазин»,
«Покрасить комнату»; Send is enabled without deleting anything; saving creates
exactly three Inbox tasks whose receipts carry `reconciliation_quality =
accurate`. This is the `/verify-live` drive: approval-gated, spends money,
never run by an agent or a schedule.
