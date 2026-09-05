# Data Model: Transcript-first voice brain dump

**Feature**: `specs/015-transcript-first-brain-dump/` · **Plan**: [plan.md](plan.md) · **Contracts**: [contracts/brain-dump-operations.md](contracts/brain-dump-operations.md)

Phase 1 output, written from the code as built. The persistence records live in
`backend/app/workflows/voice_brain_dump/domain.py` (pydantic `StorageBaseModel`
documents) and are stored by `OperationRepository`
(`backend/app/workflows/voice_brain_dump/repository.py`) in the operation-private
SQLite database `voice_operations.sqlite3` with JSON mirrors under
`brain-dump-operations/<owner>/<operation>.json`; raw audio lives under
`brain-dump-media/<owner>/<operation>/`. Every record below already existed
before this feature; the deltas are new **literal values**, tightened
**invariants** and one new **state-machine edge**. There is no migration:
`schema_version` stays `2` and older documents remain readable.

The spec's Key Entities map onto these documents as follows: Recording
(operation) → `BrainDumpOperationDocument`; Transcript segment →
`BrainDumpTranscriptSegmentDocument`; Task proposal →
`BrainDumpProposalDocument` (+ `BrainDumpProposalPatchDocument` lineage);
Processing attempt → `BrainDumpProviderRunDocument`; Saved-task receipt →
`BrainDumpActionReceiptDocument`.

## 1. `BrainDumpOperationDocument` (the recording)

| field | type | delta in this feature |
|---|---|---|
| `id`, `owner_id`, `kind="voice_brain_dump"` | str | — (owner scoping unchanged; wrong-owner reads are 404) |
| `status` | `BrainDumpStatus` | literal unchanged: `recording, paused, sealing, fast_processing, accurate_transcribing, reconciling, retryable_error, terminal_error, awaiting_confirmation, committing, completed, cancelled`. `fast_processing` is **retained read-only**: the server no longer enters it |
| `consent` | `BrainDumpConsent` (`microphone`, `external_processing_allowed`, `provider`, `providers[]`, `language_hints[]`, `vocabulary[]`, `recorded_at`) | — ; `external_processing_allowed` is the precondition for accepting preview text and for the recovery |
| `consent_withdrawn_at` | datetime? | — ; when set, `reconcile_preview` is refused with `RECONCILER_CONSENT_REQUIRED` and the working artifacts are scheduled for the sweep |
| `segments[]` | `BrainDumpTranscriptSegmentDocument` | **preview segments are transcript only** — appending them never creates a proposal (FR-002) |
| `segment_content_hashes[]` | id → sha256 map captured at the working-artifact purge | — |
| `proposals[]` | `BrainDumpProposalDocument` | minted only by the reconciler after seal (FR-003); empty for a new operation until then |
| `proposal_patches[]` | `BrainDumpProposalPatchDocument` | — (append-only lineage) |
| `provider_runs[]` | `BrainDumpProviderRunDocument` | may now contain a run at checkpoint `preview_transcribed` / `preview_reconciled` (see §3) |
| `reconciliation_quality` | `none \| provisional_only \| accurate \| conflicted` | `provisional_only` is now also written by the preview recovery (previously by `review_provisional` and legacy import only); `accurate` only by the canonical path; `conflicted` by a terminal `RECONCILER_VALIDATION_REJECTED` |
| `manual_review` | bool | set `true` by `review_provisional` **and** by a successful preview recovery — the one flag that lets a `provisional_only` review commit |
| `legacy_import` | `"legacy_preview_only"`? | — (pre-existing schema-v1 import marker; FR-011 rules apply) |
| `media_ref`, `audio_chunks[]`, `sealed_manifest_hash` | | — ; `sealed_manifest_hash` is **not** required to retry a preview run |
| `raw_audio_expires_at` | datetime? | stamped once at the first successful reconciliation (either checkpoint) as now + raw-audio retention; never recomputed |
| `working_artifacts_expires_at` | datetime? | re-anchored on `cancel` and on consent withdrawal (unchanged behaviour) |
| `commit_batch`, `action_receipts[]`, `committed_task_ids[]` | | — (see §5) |
| `status_history[]` | `BrainDumpStatus[]` | the recovery appends `reconciling`, then `awaiting_confirmation` |
| `created_at`, `updated_at`, `schema_version=2`, `revision` | | every command asserts `expected_revision == revision` (409 `ConflictError` otherwise) and increments `revision` |

**Derived, not stored** (computed in `backend/app/api/tasks.py` for every
response): `committable = brain_dump_operation_is_committable(operation)` and
`available_recovery_actions` (see contracts §3).

## 2. `BrainDumpTranscriptSegmentDocument` (transcript segment)

| field | type | note |
|---|---|---|
| `id`, `sequence ≥ 1` | | `sequence` is the client's append order and the upsert key in `append_brain_dump_transcript` |
| `text` (1…20 000 chars), `content_sha256` | | the hash is stamped at persistence and survives the text purge |
| `stability` | `interim \| stable` | an `interim` segment may be rewritten in place by a later append with the same `sequence`; a changed `stable` one is a 409 |
| `provider_role` | `browser_preview \| fast \| accurate` (default `browser_preview`) | preview text keeps `browser_preview` even when it is handed to the reconciler by the recovery |
| `start_ms`, `end_ms > start_ms` | int | a segment with an empty span is skipped by `browser_preview_recovery_hypotheses` |
| `supersedes_segment_ids[]` | str[] | accurate-STT utterances supersede preview ones; a superseded preview segment is never recovery input |
| `language`, `confidence`, `provider`, `model`, `created_at` | | — |

**Recovery input** (`domain.browser_preview_recovery_hypotheses`): the segments
with `provider_role == "browser_preview"`, `stability == "stable"`, not named in
any `supersedes_segment_ids`, non-blank text and a positive span, in audio
order. This is exactly the readout the owner watched, minus interim fragments.

## 3. `BrainDumpProviderRunDocument` (processing attempt)

| field | type | delta |
|---|---|---|
| `id` | str | — |
| `role` | `accurate_stt \| reconciler` | — (the preview recovery is a `reconciler` run) |
| `status` | `pending \| running \| succeeded \| retryable_error \| terminal_error` | — |
| `input_hash` | sha256 | for a preview run: SHA-256 of the joined stable preview text |
| `checkpoint` | `BrainDumpProviderRunCheckpoint` = `sealed \| accurate_transcribed \| reconciled \| preview_transcribed \| preview_reconciled` | **two new literals.** `preview_transcribed` = the durable stage a preview run resumes from; `preview_reconciled` = where a successful preview run freezes. They are kept distinct from `accurate_transcribed` / `reconciled` so nothing derived from preview text can satisfy the canonical `accurate` gate. `ReconcilerSourceCheckpoint = accurate_transcribed \| preview_transcribed` names the two reconciler inputs |
| `attempt`, `recovery_count` | int ≥ 0 | a preview run starts at `attempt=1`, `recovery_count=0` — a fresh stage with its own bounded retry budget |
| `error`, `error_code` | str? | allowlisted codes only (`_redact_provider_error`); new observable values on this path: `OPERATION_COST_BUDGET_EXCEEDED`, `RECONCILER_CONSENT_REQUIRED`, `RECONCILER_CONSENT_PROVIDER_MISMATCH`, `RECONCILER_VALIDATION_REJECTED`, `OPERATION_RECOVERY_BUDGET_EXHAUSTED`, `CONSENT_WITHDRAWN`, fallback `PROVIDER_ERROR_UNSPECIFIED` |
| `provider`, `model`, `template_version` | str? | on success: the reconciler's `provider_id`, `model` and `template_version` (`brain-dump-reconciler-v3`) |
| `estimated_cost_usd`, `reserved_cost_usd`, `consumed_cost_usd` | float ≥ 0 | `reserved_cost_usd` = the reconciler's `max_cost_usd_per_operation` while pending/running; on success `reserved` → 0 and `consumed` = the estimate |
| `lease_owner`, `lease_expires_at` | | CAS lease stamped by the runner; an expired lease is reclaimable |
| `output_segment_ids[]`, `created_at`, `updated_at` | | — |

**Checkpoint transitions**

```text
accurate lane:   sealed ──accurate_stt──▶ accurate_transcribed ──reconciler──▶ reconciled
preview recovery:                          preview_transcribed  ──reconciler──▶ preview_reconciled
```

## 4. `BrainDumpProposalDocument` (task proposal)

| field | type | delta |
|---|---|---|
| `id`, `ordinal ≥ 1`, `title` (1…500) | | ids are server-owned; the adapter rejects client-chosen ids |
| `status` | `provisional \| wording_changing \| ready_to_review \| user_edited \| reconciled \| conflicted` | `wording_changing` **retained read-only** for proposals persisted before 2026-09-05; `_proposal_document_to_reconciled` folds it into `provisional`; nothing produces it |
| `source_segment_ids[]` | | a folded duplicate's survivor carries the union of both utterances' segments (FR-004 evidence) |
| `predecessor_ids[]`, `successor_ids[]` | | split/merge lineage; a folded structural duplicate hands its predecessors to the survivor |
| `locked_fields[]`, `conflicts[]` (`BrainDumpProposalConflictDocument`) | | user locks and provider suggestions; any open conflict blocks commit |
| `deleted`, `user_edited`, `title_revision`, `revision`, timestamps | | a deletion is a tombstone: the adapter refuses to re-add an equivalent title (`normalized_title`) |

## 5. `BrainDumpActionReceiptDocument` (saved-task receipt)

| field | type | delta |
|---|---|---|
| `id = receipt:{operation}:{proposal}`, `proposal_id`, `task_id`, `child_idempotency_key` | | deterministic identity; idempotent across resume |
| `source_segment_ids[]`, `proposal_patch_ids[]`, `source_operation_id`, `source_manifest_hash` | | provenance; `source_manifest_hash` is copied from the operation's `sealed_manifest_hash` |
| `reconciliation_run_id`, `reconciliation_provider`, `reconciliation_model`, `reconciliation_template_version` | str? | taken from the last succeeded reconciler run at `reconciled` **or** `preview_reconciled` |
| `reconciliation_quality` | `none \| provisional_only \| accurate \| conflicted` | copied from the operation at commit — `provisional_only` for every task saved from a preview recovery or a provisional review (FR-010) |
| `confirmed_title_sha256`, `proposal_revision`, `user_edited`, `confidence="unknown"`, `confirmed_by_actor_id`, `decision="create_native_inbox_task"`, `confirmed_at` | | — |

## 6. Invariants enforced by the service

1. **Preview text never becomes a proposal.** `append_brain_dump_transcript`
   writes `segments` only (FR-002).
2. **One reconciliation source at a time.** A reconciler run reads either the
   accurate transcript (`accurate_transcribed`) or the stable preview text
   (`preview_transcribed`); the accurate path fails closed when its checkpoint is
   missing; the preview path never reads audio.
3. **Quality follows the source.** `preview_transcribed` → `provisional_only` +
   `manual_review=true` + `preview_reconciled`; `accurate_transcribed` →
   `accurate` + `reconciled`. No code path writes `accurate` from preview text.
4. **Committable** ⇔ `status == awaiting_confirmation` ∧ no open conflict on a
   live proposal ∧ ≥ 1 live proposal ∧ (`legacy_import == legacy_preview_only`
   ∨ `manual_review` ∨ (`reconciliation_quality == accurate` ∧ a succeeded
   `reconciled` run ∧ every live proposal is `reconciled` or `user_edited`)).
5. **Recovery is one shot and mutually exclusive.** `reconcile_preview` is
   offered only when no live proposal exists (otherwise `review_provisional`
   is) and no `preview_*` run exists anywhere in `provider_runs`.
6. **Consent is re-checked at every hop**: append (`TRANSCRIPT_CONSENT_REQUIRED`),
   enqueue (`RECONCILER_CONSENT_REQUIRED`, `RECONCILER_CONSENT_PROVIDER_MISMATCH`),
   runner (same codes persisted on the run).
7. **Cost is admitted before I/O**: `provider_cost_budget_allows(cumulative,
   worst_case_next, cap)` with cumulative = accepted spend plus every
   unresolved reservation across all runs; refusal is
   `OPERATION_COST_BUDGET_EXCEEDED`.
8. **Every mutation is owner-serialized and idempotent**: `command_lock(owner_id)`
   or `@_serialized_write`, an `Idempotency-Key` record per command, and
   `expected_revision` checks (409 on drift). A repeated `cancel` on a
   `completed`/`cancelled` operation keeps that status.

## 7. State transitions touched by this feature

```text
recording ⇄ paused ─finish/seal─▶ sealing ─▶ accurate_transcribing ─▶ reconciling ─▶ awaiting_confirmation ─commit─▶ committing ─▶ completed
                                                   │                       │
                                                   ▼                       ▼
                                           retryable_error ─retry─▶ (last checkpoint)
                                                   │
                                                   ▼
                                            terminal_error ─review_provisional (live proposals)─▶ awaiting_confirmation [provisional_only, manual_review]
                                            terminal_error ─reconcile_preview (no live proposals, stable preview text, consent, budget; once)─▶ reconciling ─▶ awaiting_confirmation [provisional_only, manual_review, preview_reconciled]
any non-terminal ─cancel─▶ cancelled        (idempotent; audio deleted; working artifacts scheduled)
```

The `terminal_error → reconciling` edge is the one edge added by the 2026-09-05
amendment; every other transition is pre-existing ADR-0002 behaviour.

## 8. Retention and purge (unchanged, restated for the auditor)

| record | clock | sweep |
|---|---|---|
| raw audio (`brain-dump-media/…`) | `raw_audio_expires_at` = first successful reconciliation + `BRAIN_BUDDY_VOICE_RAW_AUDIO_RETENTION_SECONDS` (86 400); immediate on `cancel`, `withdraw_consent`, `delete_raw_audio` | `purge_expired_raw_audio` |
| uncommitted segments and proposals | `working_artifacts_expires_at` (+ `BRAIN_BUDDY_VOICE_WORKING_ARTIFACT_RETENTION_SECONDS`, 604 800) | `purge_expired_working_artifacts` |
| receipts, `committed_task_ids`, `segment_content_hashes` | life of the account | account purge (`AccountService`) |

Account export already includes brain-dump operations; the recovery adds no new
record kind, so export and purge coverage are unchanged.
