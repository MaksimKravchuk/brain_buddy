# Data model: Expo mobile first slice

**Feature**: `004-expo-mobile-first-slice`
**Date**: 2026-07-20

This feature adds no mobile-owned canonical domain entity. Identity, Tasks, Projects, Tags,
and Voice Brain Dump operations remain backend-owned. The mobile app stores one device
credential and one bounded recovery record for an unconfirmed local recording.

## Server-owned records

### Session (existing Identity record)

```text
Session:
  token_hash: string       # SHA-256 of opaque raw token; primary key/file name
  user_id: string          # server-resolved owner/actor
  created_at: UTC datetime
  expires_at: UTC datetime
```

No JWT claims, refresh token, device owner ID, scope list, or raw token is added. Browser and
mobile session establishment create the same record. Existing sessions require no data
migration.

Validation and lifecycle:

- raw token has 256 bits of entropy and is returned only at establishment;
- only the digest is persisted;
- `expires_at <= now` is invalid and lazily deleted;
- logout deletes the digest record;
- `user_id` is always derived from the session record, never accepted from a client;
- cookie and Authorization header are transport alternatives, not different owners.

### SessionCredentialResponse (mobile transport DTO)

```text
SessionCredentialResponse:
  session_token: string    # opaque, returned once; sensitive
  token_type: "Bearer"
  expires_at: UTC datetime
  user:
    id: string
    email: string
```

This is a response contract, not persisted server state. Responses are `no-store` and the
token is excluded from serialization/logging helpers.

### API contract version (configuration, not domain data)

```text
ApiSettings:
  semantic_version: semver       # OpenAPI info.version, initially 1.0.0
```

Storage schema version remains `DataSettings.schema_version` and `/health.schema_version`.
A committed OpenAPI v1 snapshot records the supported mobile transport contract.

### Task / Project / Tag (existing Tasks records)

The mobile app consumes existing public projections without copying persistence models.
Normative fields and lifecycle remain in `backend/app/schemas/tasks.py` and ADR-0006.

First-slice mobile writes:

- `TaskCreateRequest`: plain title, `state=inbox`, no Smart Add or inferred metadata;
- `TaskTransitionRequest`: complete and explicit reopen/move where surfaced;
- every mutation has one durable client-generated idempotency key;
- expected revision is sent for transitions/updates;
- server response replaces optimistic local projection.

### BrainDumpOperation and canonical confirmation records (workflow-owned)

Before mobile Voice implementation, the existing operation payload gains additive ADR-0002
confirmation, consent, and retention fields:

```text
BrainDumpOperation:
  ...existing workflow fields...
  schema_version: 2
  proposal_revision: integer >= 0
  confirmation_contract_version: 2
  proposal_batches: ProposalBatch[]
  action_receipts: OperationActionReceipt[]
  active_proposal_batch_id?: string
  committed_proposal_batch_id?: string
  import_mode: native_v2 | legacy_preview_only
  legacy_imported_at?: UTC datetime
  accurate_reconciliation_available: boolean
  provisional_review_accepted_at?: UTC datetime
  operation_warning_codes: string[]
  consent_decisions: ExternalProcessingConsentDecision[]
  raw_audio: RawAudioRetention

ProposalBatch:
  id: opaque string
  based_on_proposal_revision: integer
  ordered_actions[]:
    id: opaque string
    operation: create_native_inbox_task
    proposal_id: opaque string
    title: string
    target:
      kind: new_native_inbox_task
    before_summary: string
    after_summary: string
    source_cue:
      transcript_segment_ids: opaque string[]
      display_summary: string
    confidence?: number in [0, 1]
    destination: native_inbox
    warning_codes: string[]
  created_at: UTC datetime
  frozen_at: UTC datetime
  snapshot_revision: 1

OperationActionReceipt:
  id: opaque string
  action_key: H(operation_id, batch_id, action_id)
  operation_id: opaque string
  batch_id: opaque string
  action_id: opaque string
  request_hash: string
  receipt_sequence: monotonically increasing integer per action_key
  attempt: integer >= 1
  outcome: started | succeeded | failed_retryable | failed_terminal | skipped_dependency
  result_task_id?: opaque string
  recorded_at: UTC datetime

ProposalBatchProjection (derived, not persisted into ProposalBatch):
  snapshot: ProposalBatch
  status: frozen | committing | committed | superseded | failed
  committed_at?: UTC datetime
  action_results[]:
    action_id: opaque string
    status: pending | succeeded | failed | skipped
    result_task_id?: opaque string

ExternalProcessingConsentDecision:
  id: opaque string
  decision: grant | withdraw
  external_processing_allowed: boolean
  consent_policy_version?: string
  allowed_provider_categories: string[]
  decision_recorded_at: UTC datetime
  recorded_at: server UTC datetime
  valid_until?: server UTC datetime
  withdrawn_at?: server UTC datetime

RawAudioRetention:
  state: not_received | retained | deletion_pending | deleted
  retained_until?: server UTC datetime
  delete_now_available: boolean
  deleted_at?: server UTC datetime
```

`ProposalBatch` is the persisted immutable confirmation snapshot. Its ordered action preserves
the complete review evidence from ADR-0002: target, before/after summaries, source cue,
confidence and warnings, and destination. Neither the batch nor an action contains execution
status or a result Task ID, and later proposal edits cannot change the snapshot. Any accepted
proposal patch or reconciliation that increments `proposal_revision` supersedes the active
batch and requires a new snapshot.

`OperationActionReceipt` is an append-only immutable execution event, not a mutable field on
the frozen action. The server folds receipts in `receipt_sequence` order to project batch
`frozen | committing | committed | superseded | failed` state and each action's
`pending | succeeded | failed | skipped` result. A successful receipt and its Task ID are
terminal for an action key; later attempts cannot create another Task. Retryable failures may
be followed by a higher-sequence attempt with the same request hash. Reusing an action key
with another request hash conflicts. `committed_at`, when projected, is derived from terminal
receipt times. Creation of a native Inbox Task and its `succeeded` receipt is atomic under the
child action key. This split preserves an immutable review snapshot while allowing truthful
partial-result and restart recovery.

Existing payload migration follows ADR-0002 rather than treating legacy previews as accurate
input. Completed/cancelled v1 payloads remain readable and immutable and are never replayed.
Under the existing owner-serialized write boundary, the first v2 load of each active v1
payload atomically persists `schema_version=2`, `import_mode=legacy_preview_only`, and
`legacy_imported_at`; that marker makes the import one-time and retry-safe. The operation ID,
old segment IDs, proposal IDs, title locks (`user_edited=true`), and remove tombstones
(`deleted=true`) are preserved. Every old segment becomes a `browser_preview` version with an
unknown/coarse span. Synthetic patch IDs derive from
`H(operation_id,"legacy-import",proposal_id,operation)`; proposals retain stored order with ID
as the tie-break, and an optional `remove` follows its `add`. Repeating import therefore
reconstructs the same projection without duplicate patches or a claim of accurate
reconciliation.

An imported operation always has `accurate_reconciliation_available=false` and exposes
`provisional_only` in `operation_warning_codes`, proposal review, every frozen action, and the
batch/result projection. Accurate retry is unavailable because no original audio exists.
Freeze is rejected until the user explicitly accepts provisional review through the canonical
`review-provisional` command; confirmation remains a separate explicit command against the
resulting immutable batch. Cancellation remains available. Deprecated direct proposal
`PATCH` and `/commit` adapters use these same records during the bounded web overlap but may
not bypass the visible warning or provisional-review gate; mobile does not generate or call
those aliases.

The mobile app consumes the backend projection and commands. Canonical fields remain
backend-owned. Mobile never persists a second proposal, batch, action receipt, or operation
domain model; it caches a replaceable projection and stores only the recovery pointer below.

## Mobile-owned local records

### Secure session entry

```text
SecureSessionEntry:
  key: "brainbuddy.session.v1"
  value: opaque session_token
  keychain_service: "brainbuddy.mobile.session"
  iOS accessibility: this-device-only, available while unlocked
```

Only the token is sensitive state. Expiry and current user may live in memory after `/me`
validation but are not required in SecureStore. Password is never persisted.

State transitions:

```text
absent -> establishing -> stored -> validated
stored|validated -> expired|revoked|unreadable -> absent
stored|validated -> local_logout -> absent
```

The transition to `stored` is complete only after SecureStore succeeds. If server session
creation succeeds but local storage fails, the client best-effort revokes the new session,
drops the token from memory, and reports sign-in failure.

### Installation marker

```text
InstallationMarker:
  path: application documents / .brainbuddy-install-v1
  value: non-secret random or fixed schema marker
```

The marker has no authorization or analytics meaning. On startup:

1. marker absent → delete residual SecureStore session, clear local operation directory,
   write marker, show sign-in;
2. marker present → continue normal session validation.

This handles possible iOS Keychain persistence after uninstall without turning a device ID
into identity.

### VoiceRecoveryManifest

One active manifest is allowed in the first slice.

```text
VoiceRecoveryManifest:
  schema_version: 2
  local_manifest_id: UUID
  owner_id: opaque server User ID
  start_idempotency_key: UUID
  server_operation_id?: string
  operation_revision?: integer
  audio_uri?: app-document URI
  audio_format: string
  audio_size_bytes?: integer
  duration_ms?: integer
  consent:
    decision: grant | withdraw
    consent_policy_version?: string
    allowed_provider_categories: string[]
    decision_recorded_at: UTC datetime
    valid_until?: UTC datetime
    remote_status: unsubmitted | current | revalidation_required |
                   withdrawal_pending | withdrawn
  chunk_size_bytes: integer
  chunks[]:
    number: integer >= 0
    byte_start: integer >= 0
    byte_end_exclusive: integer > byte_start
    sha256: 64 lowercase hex
    acknowledged: boolean
  expected_chunks?: integer
  manifest_hash?: 64 lowercase hex
  seal_idempotency_key?: UUID
  consent_decision_idempotency_key?: UUID
  proposal_patch_keys: map<proposal_id, UUID>
  freeze_idempotency_key?: UUID
  frozen_batch_id?: string
  frozen_batch_revision?: integer
  confirm_idempotency_key?: UUID
  confirm_request_operation_revision?: integer
  raw_audio_delete_idempotency_key?: UUID
  local_status:
    recording | recorded | preparing_chunks | uploading |
    ready_to_seal | sealed | processing | awaiting_confirmation |
    batch_frozen | committing | consent_required | withdrawal_pending |
    remote_audio_delete_pending | cleanup_pending | recoverable_error
  last_error_code?: enum
  created_at: UTC datetime
  updated_at: UTC datetime
```

Do not persist the raw session token, email, transcript text, proposal titles, frozen action
titles, task titles, or provider response in this manifest. `owner_id` is the opaque server ID returned by `/me`;
it is not client-supplied authority. It prevents a prior owner's recovery record from being
shown after an account switch and permits an involuntarily signed-out user to recover after
the same owner reauthenticates. A mismatched owner may see only that quarantined recovery
exists and may discard it; the app never exposes its audio path, operation ID, or content.
Hashes and file URIs are sensitive local recovery data. They are never emitted to logs,
analytics, crash metadata, screenshots, or Allure attachments.

Atomicity:

- write to a sibling temporary file, flush, then replace the manifest;
- mark a chunk acknowledged only after a successful server response;
- persist the operation-start and every later command/idempotency key before first network
  attempt;
- never regenerate a key for a retry of the same user intent;
- on restart/reconnect, compare consent policy version/categories/expiry and the server's
  current/withdrawn state before any upload, seal, retry, or provider-triggering command;
- persist withdrawal/delete-now intent before deleting the local audio; keep a non-content
  pending command pointer until remote acknowledgement, and never claim remote deletion from
  local cleanup alone;
- delete local audio once the sealed server copy is durable and local upload recovery no
  longer needs bytes; the manifest may remain without `audio_uri` while confirmation or a
  remote deletion command is pending;
- delete the manifest only after all pending commands have a server result or the user accepts
  an explicit local-only discard with honest remote-state warning;
- on parse/schema failure, preserve audio, quarantine the manifest, and offer explicit
  salvage/discard rather than silently deleting the recording.

Local state transitions:

```text
recording -> recorded -> preparing_chunks -> uploading
uploading -> uploading | ready_to_seal | recoverable_error
ready_to_seal -> sealed -> processing
processing -> processing | awaiting_confirmation | recoverable_error
awaiting_confirmation -> batch_frozen | consent_required | cleanup_pending
batch_frozen -> awaiting_confirmation | committing | cleanup_pending
committing -> awaiting_confirmation | cleanup_pending | recoverable_error
consent_required -> last durable pre-provider state | withdrawal_pending | cleanup_pending
withdrawal_pending -> cleanup_pending | recoverable_error
remote_audio_delete_pending -> cleanup_pending | recoverable_error
recoverable_error -> last durable state | cleanup_pending
any pre-commit state -> cleanup_pending (explicit discard/cancel)
cleanup_pending -> deleted
```

The server operation state is authoritative whenever `server_operation_id` exists. Local
state describes device work only and may not invent `completed`, canonical Task IDs, or
proposal status.

## Mobile in-memory projections

### AuthState

```text
unknown | signed_out | validating | signed_in | auth_error
```

`AuthState` contains `MeResponse` only when signed in. It never exposes the raw token to UI
stores; the API transport reads it through a narrow credential provider.

### TaskQueryProjection

```text
key: normalized server filters + cursor page
value: TaskListResponse
persistence: memory only
```

Counts and pages come from the server. On owner/session change, all entries are removed.
Mutations replace/invalidate projections only after a server success.

### BrainDumpProjection

A memory-only rendering projection of `BrainDumpOperationResponse`. It may include transcript
and proposal text while the screen is open but is not persisted in generic state, telemetry,
or crash snapshots. Reopen refetches by owner-scoped operation ID from
`VoiceRecoveryManifest`.

## Ownership and reference invariants

1. Session resolution supplies `current_user.id`; mobile never sends owner ID as authority.
2. Task, Project, Tag, operation, proposal, and resulting Task IDs are opaque server IDs.
3. Wrong-owner IDs return `404` and are removed from mobile projections without probing.
4. Project/Tag projections and task counts remain server-derived; no local canonical index.
5. A Voice Brain Dump proposal is provisional. Only confirm returns canonical Task IDs.
6. One local manifest can point to one server operation; recording may begin before that
   operation is reachable, but upload cannot begin until operation start succeeds.
7. Involuntary authentication loss clears visible owner projections and quarantines recovery
   until the same `owner_id` reauthenticates. Voluntary logout requires explicit discard of
   active recovery; a different owner can never inspect it.
8. A persisted consent decision is not sufficient by itself. Resume requires a fresh server
   projection/policy comparison; expiry, withdrawal, or any required category/policy change
   moves local state to `consent_required` before bytes or provider-triggering commands leave.
9. A frozen batch ID/revision is only a retry pointer. The server snapshot and deterministic
   action receipts are authoritative; mobile never rebuilds or edits a frozen batch locally.

## Retention and deletion

- Session token: until logout, server expiry/revocation, unreadable SecureStore, or first-
  install cleanup.
- Query/proposal projections: memory only; clear on logout and process termination.
- Local audio: retain only while recording/upload recovery requires bytes. Delete after the
  complete sealed server copy is durable, or immediately after withdrawal/explicit discard;
  keep only a non-content manifest when confirmation or remote cleanup remains pending.
- Local manifest: retain while recovery or an idempotent command result is unresolved, then
  delete. Its deletion never claims server cancellation/audio deletion.
- Server raw audio: projection exposes `retained_until`, deletion state, and delete-now after
  processing. Default successful-reconciliation retention is 24 hours under ADR-0002/config;
  withdrawal schedules uncommitted media cleanup. Delete-now removes raw media but preserves
  required non-audio provenance, action receipts, and confirmed Tasks.
- Server working transcripts/operation artifacts: seven-day default after completion/
  cancellation under ADR-0002/config, with privacy erasure handled separately from raw-audio
  delete-now.
