# Brain-dump operation commands and projection

**Status**: normative for `015-transcript-first-brain-dump`; describes the contract as built on `claude/brain-dump-mechanics-t35ab7`.
**Base**: authenticated, same-origin `/api`; session cookie required (401 otherwise); every response carries `X-Correlation-ID`.
**Source of truth in code**: `backend/app/api/tasks.py` (routes, projection), `backend/app/schemas/tasks.py` (shapes), `backend/app/workflows/voice_brain_dump/service.py` (guards). Client mirrors: `frontend/src/api/taskTypes.ts`, `frontend/src/api/client.ts`, `mobile/src/api/types.ts`, `mobile/src/api/client.ts`.

## 1. Route family (unchanged shape)

| route | flag-gated | purpose |
|---|---|---|
| `GET /api/brain-dump-providers` | yes | configured provider categories for consent copy |
| `POST /api/brain-dump-operations` | yes | start an operation with consent and language hints |
| `GET /api/brain-dump-operations/{operation_id}` | **no** | owner-scoped projection (§3); reachable with the flag OFF so privacy controls stay usable |
| `POST /api/brain-dump-operations/{operation_id}/transcript` | yes | append browser-preview segments — **transcript only, never proposals** |
| `PUT /api/brain-dump-operations/{operation_id}/audio/{chunk_number}` | yes | idempotent chunk upload |
| `POST /api/brain-dump-operations/{operation_id}/seal` | yes | stop and seal; queues accurate STT |
| `PATCH /api/brain-dump-operations/{operation_id}/proposals/{proposal_id}` | yes | owner edit / delete / conflict resolution |
| `POST /api/brain-dump-operations/{operation_id}/{action}` | per action (§2) | the catch-all command route |

"Flag-gated" means `require_voice_brain_dump_enabled` / `voice_brain_dump_enabled` (`backend/app/api/dependencies.py`): when `voice_brain_dump` is not effective for the caller the route answers **404** `Voice brain dump is not available.` (fail-closed, indistinguishable from a missing resource). A wrong-owner operation id is also 404.

## 2. `POST /api/brain-dump-operations/{operation_id}/{action}`

```http
POST /api/brain-dump-operations/{operation_id}/{action}
Idempotency-Key: <client-generated, unique per logical command>
Content-Type: application/json

{"expected_revision": 7}
```

- `Idempotency-Key` is required: missing → 400 `Idempotency-Key header is required.` Replaying the same key with the same request hash returns the original result; the command is owner-serialized.
- `expected_revision` must equal the operation's current `revision`: otherwise 409 (`ConflictError`, message `Brain dump operation '<id>' has newer changes; reload before saving.`).
- Response: `200` with the full `BrainDumpOperationResponse` (§3). Declared error responses: 400, 401, 404, 409, 422.

| `action` | reachable with flag OFF | guard (service) | effect |
|---|---|---|---|
| `pause` | no | status `recording` | → `paused` |
| `resume` | no | status `paused` | → `recording` |
| `finish` | no | status `recording` or `paused` | → `awaiting_confirmation` directly, without sealing; untouched live proposals become `ready_to_review` |
| `cancel` | **yes** | any status; on `completed`/`cancelled` the status is kept (idempotent) | → `cancelled`; raw audio deleted now; `working_artifacts_expires_at` re-anchored; saved Inbox tasks never touched |
| `commit` | no | status `awaiting_confirmation`; see §4 | freezes the batch and creates title-only Inbox tasks through the `TaskPort`; → `committing` → `completed` |
| `retry` | no | status `retryable_error` (or an expired running claim); a sealed checkpoint, **or** a reconciler run at `preview_transcribed` (no manifest needed) | re-queues a `pending` run at the last checkpoint (`sealed`, `accurate_transcribed` or `preview_transcribed`); `recovery_count ≥ max_operation_recoveries` → `terminal_error` `OPERATION_RECOVERY_BUDGET_EXHAUSTED` |
| `review_provisional` | no | `can_review_brain_dump_provisionally`: `terminal_error`, last run a terminal `accurate_stt`/`reconciler` failure, **≥ 1 live proposal** | → `awaiting_confirmation`, `reconciliation_quality=provisional_only`, `manual_review=true` |
| `reconcile_preview` | no (spends budget, ships text to a vendor) | `_preview_recovery_state_eligible` ∧ consent ∧ cost — see below | appends a `pending` `reconciler` run at `preview_transcribed` (`attempt=1`, `recovery_count=0`, reservation = reconciler cap); → `reconciling`; wakes the runner |
| `withdraw_consent` | **yes** | status not `completed`/`cancelled` | `external_processing_allowed=false`, `consent_withdrawn_at` set; in-flight run → `terminal_error` `CONSENT_WITHDRAWN`; raw audio deleted; working artifacts scheduled for the sweep |
| `delete_raw_audio` | **yes** | refused while an accurate-STT or reconciler run is still `pending`/`running` in `accurate_transcribing`/`reconciling` (the sealed audio is its input) | deletes retained audio only; proposals and transcript untouched |
| anything else | — | — | 400 `Unsupported brain dump operation command.` |

`_VOICE_OFF_REACHABLE_ACTIONS = frozenset({"withdraw_consent", "cancel", "delete_raw_audio"})`.

### 2.1 `reconcile_preview` guards and refusals

Checked in this order, before any external call; each refusal is a 400 `ErrorResponse` whose `message` starts with the fixed code:

| code | condition |
|---|---|
| `BRAIN_DUMP_PREVIEW_RECOVERY_UNAVAILABLE` | not (`status == terminal_error` ∧ last provider run is a `terminal_error` of role `accurate_stt` or `reconciler` ∧ no live (non-deleted) proposal ∧ no run in `provider_runs` with checkpoint `preview_transcribed` or `preview_reconciled` ∧ at least one stable, unsuperseded, non-blank `browser_preview` segment) |
| `RECONCILER_CONSENT_REQUIRED` | `consent.external_processing_allowed` is false **or** `consent_withdrawn_at` is set |
| `RECONCILER_CONSENT_PROVIDER_MISMATCH` | the configured reconciler requires external processing and its `provider_id` is not in the consented provider set |
| `OPERATION_COST_BUDGET_EXCEEDED` | `cumulative_provider_cost_usd(provider_runs) + reconciler.max_cost_usd_per_operation` does not fit under `max_cumulative_cost_usd_per_operation` (defaults 0.50 and 1.00 USD, `BRAIN_BUDDY_VOICE_RECONCILER_MAX_COST_USD`, `BRAIN_BUDDY_VOICE_MAX_CUMULATIVE_COST_USD`) |

The same consent and cost checks run again in the persisted runner before the provider call; a refusal there is persisted on the run as `error_code` and the operation becomes `terminal_error` (cost) or `retryable_error`/`terminal_error` per the bounded budget (consent).

Outcome of a successful run: `status=awaiting_confirmation`, `reconciliation_quality=provisional_only`, `manual_review=true`, the run `succeeded` at `checkpoint=preview_reconciled` with `provider`, `model`, `template_version`, `consumed_cost_usd`. The command is **one shot**: after any `preview_*` run — success or terminal failure — it is never offered again on that operation.

## 3. `BrainDumpOperationResponse` (projection)

Every command and the `GET` return the same shape (`backend/app/schemas/tasks.py`). Fields this feature relies on:

```jsonc
{
  "id": "op_…", "owner_id": "user_…", "kind": "voice_brain_dump",
  "status": "terminal_error",                        // BrainDumpStatus
  "consent": { "microphone": true, "external_processing_allowed": true,
               "provider": null, "providers": ["deepgram", "openai"],
               "language_hints": ["ru", "en"], "vocabulary": [], "recorded_at": "…" },
  "segments": [ { "id": "seg_…", "sequence": 1, "text": "…", "stability": "stable",
                  "provider_role": "browser_preview", "start_ms": 0, "end_ms": 1800,
                  "supersedes_segment_ids": [], "language": null, "confidence": null } ],
  "proposals": [ { "id": "proposal_…", "ordinal": 1, "title": "…",
                   "status": "reconciled",           // BrainDumpProposalStatus
                   "source_segment_ids": ["seg_…"], "predecessor_ids": [], "successor_ids": [],
                   "locked_fields": [], "conflicts": [], "deleted": false,
                   "user_edited": false, "revision": 1 } ],
  "media_ref": "media_…", "audio_chunks": [ { "chunk_number": 0, "sha256": "…", "size_bytes": 1 } ],
  "sealed_manifest_hash": "…", "raw_audio_expires_at": null, "raw_audio_present": true,
  "working_artifacts_expires_at": null,
  "reconciliation_quality": "none",                  // none | provisional_only | accurate | conflicted
  "committable": false,                              // brain_dump_operation_is_committable(operation)
  "available_recovery_actions": ["reconcile_preview", "cancel"],
  "provider_runs": [ { "id": "provider_run_…", "role": "accurate_stt", "status": "terminal_error",
                       "checkpoint": "sealed", "attempt": 1, "recovery_count": 0,
                       "error": "STT_PROVIDER_REJECTED_REQUEST", "error_code": "STT_PROVIDER_REJECTED_REQUEST",
                       "provider": "deepgram", "model": null, "template_version": null,
                       "estimated_cost_usd": 0.0, "reserved_cost_usd": 0.0, "consumed_cost_usd": 0.0 } ],
  "proposal_patches": [], "action_receipts": [],
  "status_history": ["recording", "sealing", "accurate_transcribing", "terminal_error"],
  "committed_task_ids": [], "created_at": "…", "updated_at": "…", "revision": 7
}
```

### 3.1 `available_recovery_actions`

`BrainDumpRecoveryAction = Literal["retry", "review_provisional", "reconcile_preview", "cancel"]`, emitted by `_brain_dump_available_recovery_actions` in render order:

| entry | present when |
|---|---|
| `retry` | `status == retryable_error` |
| `review_provisional` | `can_review_brain_dump_provisionally(operation)` (terminal failure **with** live proposals) |
| `reconcile_preview` | `VoiceBrainDumpService.can_reconcile_preview(operation)` — the service, not the bare document, answers because the predicate depends on the configured reconciler's consent identity and cost cap (terminal failure **without** live proposals) |
| `cancel` | `status ∈ {retryable_error, terminal_error}` |

`review_provisional` and `reconcile_preview` are mutually exclusive by construction. Clients render exactly the advertised entries (web `RecoverySurface`, mobile failure card) and treat an unknown entry as not rendered.

### 3.2 `provider_runs[].checkpoint`

`Literal["sealed", "accurate_transcribed", "reconciled", "preview_transcribed", "preview_reconciled"]`. The two `preview_*` values belong to the owner-chosen recovery only; a client may use `checkpoint == "preview_reconciled"` on the last succeeded reconciler run to know the review came from the browser transcript, although `reconciliation_quality == "provisional_only"` is the field the UI labels on.

### 3.3 `committable`

True iff `status == awaiting_confirmation` ∧ no live proposal has an open conflict ∧ at least one live proposal ∧ (`legacy_import == "legacy_preview_only"` ∨ `manual_review` ∨ (`reconciliation_quality == "accurate"` ∧ a succeeded reconciler run at `reconciled` ∧ every live proposal is `reconciled` or `user_edited`)). Web disables Send and mobile `canCommit` returns false when it is false; both hide the control entirely when there is no live proposal.

### 3.4 `action_receipts[]`

`BrainDumpActionReceiptResponse` carries `reconciliation_quality`, `reconciliation_run_id`, `reconciliation_provider`, `reconciliation_model`, `reconciliation_template_version` (from the last succeeded reconciler run at `reconciled` or `preview_reconciled`), `confirmed_title_sha256`, `source_segment_ids`, `proposal_patch_ids`, `child_idempotency_key`, `decision="create_native_inbox_task"`, `confirmed_at`. A task saved from a preview recovery has `reconciliation_quality == "provisional_only"`.

## 4. `commit` gate (for completeness)

Refusals, in order, all 400 unless noted: not `awaiting_confirmation` → `Brain dump must be awaiting confirmation before save.`; not committable ∧ not a provisional review (`legacy_import`/`manual_review`) ∧ no frozen `reconciled` batch → `BRAIN_DUMP_NOT_RECONCILED: …`; live proposals with open conflicts → `Brain dump conflicts must be reviewed before save.` with `detail.proposal_ids`; outside a provisional review, live proposals whose status is neither `reconciled` nor `user_edited` → `BRAIN_DUMP_PROPOSAL_NOT_RECONCILED: …` with `detail.proposal_ids` (FR-011); otherwise not committable → `Brain dump is not eligible to save.` A repeated commit with the same key replays; an interrupted commit resumes from the frozen batch ledger.

## 5. Error envelope

Every error is `ErrorResponse` (`backend/app/schemas/api.py`):

```json
{"message": "RECONCILER_CONSENT_REQUIRED: external-processing consent naming the configured task reconciler is required before preview text may leave the device.",
 "detail": null,
 "reference_id": "3f0c…"}
```

| exception (`backend/app/api/errors.py`) | HTTP | used here for |
|---|---|---|
| `ValidationFailure` | 400 | every guard refusal above, unsupported action, missing `Idempotency-Key` |
| `NotFoundError` / flag OFF | 404 | unknown or wrong-owner operation; gated action with the flag OFF |
| `ConflictError` | 409 | stale `expected_revision`; a changed `stable` preview segment |
| `RequestValidationError` | 422 | malformed body |

`reference_id` equals the `X-Correlation-ID` response header. Clients show `message` and `reference_id` verbatim (`ErrorBanner` on mobile: message + `ref: <id>`; web via `describeError`: message + `Ref: <id>`) — never the bare HTTP status text.

## 6. Client action unions (mirrors)

- `frontend/src/api/client.ts` `commandBrainDump(operationId, action, expectedRevision, idempotencyKey)` with `action ∈ {pause, resume, finish, cancel, commit, retry, review_provisional, reconcile_preview, withdraw_consent, delete_raw_audio}`; `frontend/src/api/taskTypes.ts` `available_recovery_actions?: Array<"retry" | "review_provisional" | "reconcile_preview" | "cancel">`.
- `mobile/src/api/types.ts` `BrainDumpAction` and `available_recovery_actions` carry the same unions; `mobile/src/braindump/machine.ts` `POLLABLE = {sealing, fast_processing, accurate_transcribing, reconciling, committing}`, `nextPollDelay` 1.5 s → 8 s.

## 7. Compatibility

All changes since spec 002 are additive: one more accepted `action`, two more `checkpoint` literals, one more `BrainDumpRecoveryAction` entry, and a stricter `committable` (requires a live proposal). `fast_processing` (status) and `wording_changing` (proposal status) remain in the literals as read-only values for operations persisted before 2026-09-05. No route was removed or renamed; no request body changed.
