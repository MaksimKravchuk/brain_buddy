# Async Voice Workflows implementation readiness

**Re-verified**: 2026-07-24
**Baseline**: `origin/main` `77fe9aae8d20ba0eea2c88dcfc231135d442d13a`
**Governing decisions**: ADR-0001, ADR-0002, ADR-0006, ADR-0008

## Decision

The shipped Voice Brain Dump architecture is coherent and preserves the
modular-monolith boundary: the workflow owns operation/provider orchestration,
canonical Tasks owns Task persistence and transitions, and the composition root
connects them through `TaskPort`. The operation, patch, confirmation,
idempotency, migration, privacy, and disabled-provider contracts are
implementation-ready.

The exact candidate is **code-landing ready only after independent exact-SHA
approval and green Full CI**. T057, T058, T061, and T064 are closed in this
candidate. Landing is an enabling delivery stage, not terminal product
acceptance: the outcome root remains open until the landed main revision passes
the credentialed aggregate track, automatic production deploy, and the
authenticated real-provider phone journey.

Task status on this candidate: **51 of 57 complete (89.5%)**. Remaining:
T044, T053, T055, T060, T062, and T063. These are external/runtime evidence
gates, not additional implementation lanes or permission to represent the
feature as friend-demo ready before they pass.

## Architecture invariants

1. `backend/app/workflows/voice_brain_dump/` MUST NOT import Task repositories or
   `TaskService`. Confirmation crosses only `TaskPort`; `container.py` is the
   composition root.
2. Accurate STT receives sealed original audio bytes, language hints, and
   vocabulary. Fast/browser text is never substituted as audio input.
3. Browser preview and the local preview-title heuristic are visibly
   provisional and non-committable. Accurate reconciliation or an explicit
   provisional-only review decision is required before confirmation.
4. External provider calls require current consent naming an allowed provider
   category, configured credentials, bounded retries/deadlines, and cumulative
   cost admission. Missing prerequisites fail closed as `disabled` or a redacted
   provider error.
5. Provider output cannot allocate canonical IDs, infer Task metadata, bypass
   user locks/conflicts, or write canonical Tasks.
6. Confirmation creates title-only Inbox Tasks with deterministic child keys and
   immutable operation/proposal provenance. Reconnect, retry, and
   timeout-after-accept cannot duplicate a Task.
7. Raw audio and working artifacts remain owner-scoped and retention-bounded;
   raw text/audio, vocabulary, provider payloads, credentials, and paths do not
   enter logs or metrics.
8. Voice Brain Dump performs no downstream external Task side effect. Any future
   Task executor is a separate feature and MUST have explicit action-specific
   user confirmation and an idempotent execution receipt.

## Implemented contracts

- HTTP: owner-scoped start/get, transcript preview, chunk upload, seal,
  proposal patch, pause/resume/cancel/retry/review/commit/withdraw/delete-audio
  commands under the existing `/api/brain-dump-operations` route family.
  Persisted GET projection plus polling is authoritative; no parallel SSE or
  broker control plane is required.
- Providers: `AccurateSttPort.transcribe_sealed_audio` and
  `TextReconcilerPort.reconcile`; OpenAI production adapters, deterministic
  test adapters, and explicit disabled adapters preserve the same domain/API
  schema.
- Persistence: `voice_operations.sqlite3` stores owner-scoped operation payloads,
  idempotency rows, and the one-time legacy import ledger; media bytes are
  owner-scoped files under the data root; canonical Tasks remain in
  `tasks.sqlite3`.
- Migration: legacy v1 JSON imports once as schema v2 and remains
  `legacy_preview_only`. No new database migration is required by the remaining
  offline work.
- Rollback: provider use defaults to disabled. Rollback is configuration-only
  (disable accurate STT/reconciler) and does not rewrite operation or Task data.

## Findings

| ID | Severity | Finding | Required closure |
|---|---|---|---|
| F1 | CLOSED | Reconciler runs now persist safe adapter-owned model/template-version provenance into provider-run documents and immutable receipts. The public `TextReconcilerPort` remains backward compatible; optional provenance is discovered fail-safe. | T064 closed with success/failure/action-receipt assertions plus a legacy-adapter compatibility guard. |
| F2 | CLOSED | Executable AST/import-boundary coverage protects the Task boundary and detects a second provider-role engine outside the shared workflow package. | T058 closed in `backend/tests/test_voice_workflow_architecture.py`. |
| F3 | CLOSED | Captured logs and persisted event/provider-run envelopes are asserted not to expose raw text/audio, vocabulary, payloads, credentials, or private paths. | T057 closed in focused privacy/API tests. |
| F4 | CLOSED | `.env.example` and `docs/voice-stt.md` enumerate supported retry, deadline, cost, lease, audio-limit, retention, sweep, consent, provider-disabled, and fallback behavior without secrets. | T061 closed. |
| F5 | HIGH | The real-audio harness and credentialed CLI exist, but no approved corpus/credentialed baseline or alternative-provider benchmark evidence exists. | T044/T053/T055/T060: run the external aggregate-only track; do not invent a CER/WER threshold or commit media/transcripts. |
| F6 | HIGH | Ordinary CI proves the complete deterministic journey, not a genuine spoken-audio, real-STT, real-reconciler phone journey. | T062/T063: run the gated journey on the exact candidate head, then independent Product QA and AI-QA plus ADR-0008 release evidence. |
| F7 | LOW | Historical plan/task paths and UI wording had drifted from the shipped workflow package and `Sealing audio` label. | Corrected in this re-verification. |

No constitution conflict was found. The incomplete credentialed gates block
terminal root completion and the friend demo. They do not authorize bypassing
ADR-0008, and they are not implementation-card blockers. The audited landing
exists to create the exact deployed main revision that T062/T063 must validate;
failure of any external/runtime gate after landing leaves the root open and
requires rollback or bounded remediation rather than a false success report.

## Smallest ownership split

### Implementation lane — offline contract closure (one `coder` worktree)

Scope: T057, T058, T061, T064.

Owned files:

- `backend/app/workflows/voice_brain_dump/providers.py`
- `backend/app/workflows/voice_brain_dump/adapters/reconciler.py`
- `backend/app/workflows/voice_brain_dump/service.py`
- `backend/tests/test_brain_dump_operations_api.py`
- `backend/tests/test_voice_workflow_architecture.py` (new)
- relevant existing voice privacy tests
- `.env.example`
- `docs/voice-stt.md`

Do not modify `backend/app/modules/tasks/service.py`, Task repositories, API route
families, operation state names, persistence schema, or confirmation semantics.
No alternative-provider adapter is added without corpus/credential evidence.

Shared-hotspot ownership is explicit even though neither hotspot needs a current
write:

- `backend/app/container.py`: only a future sealed-audio STT lane may change it,
  and only if T044 corpus evidence justifies alternative-provider wiring. The
  offline implementation lane does not touch it.
- `backend/app/modules/tasks/service.py`: only a future reconciliation/Task
  provenance lane may change it, and only for a verified canonical Task defect.
  T064 is workflow audit metadata and must not touch it.

## Evidence gates (not implementation cards)

After the implementation lane produces an immutable candidate, independent QA
verifies T057/T058/T061/T064, focused voice tests, complete backend/frontend
gates, Spec Kit checks, and deterministic Compose E2E. Any implementation
finding returns to the same physical coder lane; verification does not create a
second writer.

Credentialed acceptance for T044/T053/T055/T060/T062/T063 remains one external
gate requiring an approved founder corpus outside Git and provider credentials
from the runtime secret store. It emits aggregate metrics and exact-head
evidence only; raw recordings, transcripts, vocabulary, provider payloads,
paths, and secrets never enter Kanban, Git, logs, or CI artifacts. This gate is
recorded only when inputs are available rather than represented by a permanently
blocked implementation card.

## Verification evidence at baseline

- Spec Kit prerequisites with explicit feature directory: passed.
- `python3 scripts/check_spec_kit_specs.py`: passed.
- Focused backend voice/config/Task suite: **480 passed**.
- Backend CI-equivalent lane (`ruff`, `mypy`, full pytest, coverage/taxonomy):
  **802 passed**, **97.48%** total line/branch coverage, backend coverage policy
  passed, taxonomy valid for **1,762** Allure result files.
- Focused frontend Brain Dump/API suite: **80 passed**.
- Frontend CI-equivalent lane (lint, Vitest coverage, taxonomy, typecheck,
  production build): **442 passed in 58 files**, 97.46% statements / 95.03%
  branches, taxonomy valid for **522** Allure result files, build passed.
- Compose Playwright E2E: **23 passed, 1 skipped**; taxonomy passed; artifact
  validator found 23 executed results and six required product stories.
- Independent Claude Code `fable` read-only review completed. Its findings were
  treated as evidence to verify, not authority; Hermes retained T057/T061 as
  incomplete and added T064 after direct source/test inspection.

The checks above contain no credentialed real-provider corpus run and therefore
must not be presented as T044/T053/T055/T060/T062/T063 acceptance evidence.
