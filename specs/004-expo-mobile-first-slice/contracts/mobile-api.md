# Mobile API contract v1

**Feature**: `004-expo-mobile-first-slice`
**Contract version**: `1.0.0`
**Base path**: `/api`
**Authority**: Backend Pydantic/OpenAPI; this document fixes mobile-specific semantics and the
subset consumed by the first slice.

## Common transport rules

- Production requests use HTTPS only.
- Every response includes `X-Correlation-ID`; errors use the existing `ErrorResponse` and
  return the same value as `reference_id`.
- Mobile protected requests use exactly one `Authorization: Bearer OPAQUE_SESSION_TOKEN`.
  The value is an opaque random Session credential, not a JWT.
- Browser requests continue using the HTTP-only `brainbuddy_session` cookie.
- If both cookie and Bearer credential are present, return `400` with an actionable
  ambiguous-credential error. Never choose one silently.
- Missing, malformed, expired, revoked, or unknown credentials return `401`. Wrong-owner
  resource IDs return `404`.
- Every mutation except idempotent chunk upload requires `Idempotency-Key`. A retry of the
  same user intent reuses the same key. Same key plus a different request hash returns `409`.
- Revision-checked commands carry `expected_revision`; stale state returns `409` and performs
  no mutation.
- Tokens, passwords, raw audio, transcript/proposal/task text, file paths, provider payloads,
  and content hashes are excluded from logs and error details.

## API version ownership

`FastAPI.info.version` becomes `AppConfig.api.semantic_version`, initially `1.0.0`.
`DataSettings.schema_version` remains separate and continues in `/health.schema_version`.
The generated OpenAPI document is pinned for mobile client generation.

Compatibility policy:

- additive optional fields/endpoints are allowed within v1;
- required fields, enum additions for strict clients, field/status meaning changes, removals,
  renames, and stricter validation are breaking;
- breaking mobile changes require a versioned contract/route and overlap for the current and
  immediately previous released mobile contract until the documented support window ends;
- CI fails when generated mobile DTOs differ from the pinned OpenAPI snapshot;
- mobile generation uses an operation allowlist and excludes deprecated direct proposal
  `PATCH`, `/finish`, and `/commit` compatibility aliases even while the full OpenAPI snapshot
  still documents them for the bounded web overlap window;
- mobile must ignore unknown response object fields but reject unknown state/command enums
  rather than treating them as current values.

## Mobile session establishment

### `POST /auth/mobile/sessions`

Creates the same server-owned opaque Session used by browser auth, but returns the raw
credential once instead of setting a cookie.

Request:

```json
{
  "email": "person@example.com",
  "password": "at-least-twelve-characters"
}
```

Success: `201 Created`

Required headers:

```text
Cache-Control: no-store
Pragma: no-cache
X-Correlation-ID: <uuid-or-accepted-label>
```

Response:

```json
{
  "session_token": "opaque-random-value",
  "token_type": "Bearer",
  "expires_at": "2026-08-19T12:00:00Z",
  "user": {
    "id": "user_opaque",
    "email": "person@example.com"
  }
}
```

The route MUST NOT set `Set-Cookie`. `session_token` is excluded from generated object
stringification/redaction helpers and all test attachments.

Errors:

| Status | Meaning |
|---|---|
| `401` | Generic invalid email or password; account existence is not revealed. |
| `422` | Invalid request shape/email/password bounds. |
| `429` | Existing source-IP login rate limit. |
| `503` | Session persistence unavailable; no usable credential is returned. |

If Session creation succeeds but the client cannot save SecureStore, the client immediately
calls logout with the in-memory credential, then discards it regardless of response.

### `GET /auth/me`

Unchanged response shape. Accepts cookie or Bearer credential through the common resolver.
Mobile uses it on app start before showing owner-scoped cached UI.

Success: `200 MeResponse`.
Errors: `401` for invalid/expired/revoked credential.

### `POST /auth/logout`

Revokes the currently presented cookie or Bearer Session and returns `204`. It remains
idempotent with no credential. A request presenting both credential sources returns `400`.
The browser response still clears the cookie. The native app clears SecureStore and all
owner-local state whether the response succeeds, fails, or times out.

## Task subset

The mobile first slice consumes existing contracts; it does not add mobile task routes.

| Method/path | First-slice use | Required behavior |
|---|---|---|
| `GET /tasks` | Four open lists; Project/Tag projections; terminal recovery | Server filters, counts, cursor pagination, named accepted sort only. Mobile follows `next_cursor` and never infers totals from page length. |
| `GET /tasks/{task_id}` | Bounded M-04 detail | Return canonical fields, nested arrays if present, `404` for wrong owner. Mobile may display but not expose unsupported mutation controls. |
| `POST /tasks` | Plain fast Inbox capture | Send literal title and `state=inbox`; no Smart Add parsing or inferred metadata. Requires idempotency key. |
| `POST /tasks/{task_id}/transitions` | Complete/move/reopen/cancel when surfaced | Preserve ADR-0006 transition matrix, explicit reopen destination, Waiting input, expected revision, and idempotency. |
| `GET /projects` / `GET /projects/{id}` | Drawer and M-07 read projection | Active owner-scoped records/counts only. No mobile management commands in first slice. |
| `GET /tags` / `GET /tags/{id}` | Drawer and M-08 read projection | Current Tag terminology; no historical Context API and no mobile management commands. |

The app MUST NOT call `POST /tasks/smart-add`, Project/Tag mutation, Subtask, Comment, CRT,
Weekly Review, or Execution routes in this slice.

Task mutation retry sequence:

1. generate and persist an idempotency key in memory before first attempt;
2. send expected revision where required;
3. on timeout/network error, retry with the same key and body;
4. on `409` stale revision, refetch canonical detail and preserve unsent user intent for an
   explicit retry; do not generate a last-write-wins request;
5. on success, replace/invalidate relevant Task, count, Project, and Tag projections.

## Voice Brain Dump subset

ADR-0002 owns these operation semantics. The first mobile client narrows only capture timing
to post-stop upload; it consumes canonical proposal-patch, frozen-batch, confirm, consent, and
retention contracts and never calls the temporary direct proposal `PATCH` or `/commit` aliases.

### Processing policy and current consent

Authenticated `GET /brain-dump-processing-policy` returns a current, `Cache-Control: no-store`
non-secret configuration required before a grant or upload:

```json
{
  "consent_policy_version": "voice-external-v1",
  "required_provider_categories": [
    "brainbuddy_cloud_storage",
    "cloud_stt",
    "cloud_text_reconciler"
  ],
  "consent_valid_for_seconds": 604800,
  "max_chunk_size_bytes": 1048576,
  "max_operation_size_bytes": 26214400,
  "accepted_audio_formats": ["audio/m4a"]
}
```

Category identifiers are stable data-processing classes with human-readable app copy, not
vendor names or credentials. A grant is current only when it is allowed, unexpired, not
withdrawn, uses the current policy version, and its category set exactly equals the current
required category set.
The server is authoritative for policy/version/time checks.

`POST /brain-dump-operations` uses `Idempotency-Key` and:

```json
{
  "consent": {
    "microphone": true,
    "external_processing_allowed": true,
    "consent_policy_version": "voice-external-v1",
    "allowed_provider_categories": [
      "brainbuddy_cloud_storage",
      "cloud_stt",
      "cloud_text_reconciler"
    ],
    "decision_recorded_at": "2026-07-20T12:00:00Z"
  }
}
```

The response records server-validated `recorded_at`, `valid_until`, policy version, categories,
and `status: granted`. The client persists its start key and non-secret decision fields before
first attempt and sends no provider secret. If permission is denied, no operation is created.
Recording may be captured locally while offline, but a missing, expired, withdrawn, or
policy/category-mismatched grant requires a visible new decision after reconnect and before
the first chunk upload.

`POST /brain-dump-operations/{operation_id}/consent-decisions` appends an owner-scoped
`grant` or `withdraw` decision with `Idempotency-Key` and `expected_operation_revision`.
A grant repeats the policy/category/decision-time fields above. Withdrawal has no provider
fields, stops local attempts immediately, prevents new server upload/seal/retry/provider
work after acceptance, cancels not-yet-started provider runs, and schedules uncommitted raw
audio and working transcripts for deletion. An offline withdrawal remains visibly
`remote_withdrawal_pending` locally until acknowledged; the client must not claim that
already-running remote work stopped.

### Get/resume

`GET /brain-dump-operations/{operation_id}` returns the current owner-scoped projection.
Mobile polling is the correctness fallback. Reopen starts with GET and reconciles local
chunk/checkpoint state against the response. Before any resumed upload/seal/retry, mobile also
refetches the processing policy and compares policy version, categories, expiry, and
withdrawal state. A mismatch enters `consent_required`; it never falls back to a persisted
boolean.

The projection includes:

```text
proposal_revision: integer
active_proposal_batch?: ProposalBatchProjection
committed_proposal_batch?: ProposalBatchProjection
import_mode: native_v2 | legacy_preview_only
accurate_reconciliation_available: boolean
operation_warning_codes[]
provisional_review_accepted_at?: UTC datetime
consent: {status, external_processing_allowed, consent_policy_version,
          allowed_provider_categories[], recorded_at, valid_until?, withdrawn_at?}
raw_audio: {state: not_received|retained|deletion_pending|deleted,
            retained_until?, delete_now_available, deleted_at?}
```

Each `ProposalBatchProjection` contains the immutable `snapshot` plus derived `status`,
`committed_at`, and ordered `{action_id, status, result_task_id?}` results folded from receipts.
The result objects are never serialized back into `snapshot.ordered_actions`.

### Audio chunks

`PUT /brain-dump-operations/{operation_id}/audio/{chunk_number}`

Headers:

```text
Authorization: Bearer OPAQUE_SESSION_TOKEN
X-Content-SHA256: <64 lowercase hex>
Content-Type: application/octet-stream
```

Body: exact chunk bytes.

Rules:

- chunk numbers are monotonically assigned from zero in the local manifest;
- same operation/number/hash/content retry returns success and no duplicate;
- same operation/number with different content returns `409 CHUNK_CONFLICT`;
- the client marks `acknowledged=true` only after success;
- mobile checks current policy/operation consent immediately before sending; the server rejects
  a stale grant without persisting bytes or starting provider work;
- the client never logs or attaches the hash or bytes.

The implementation plan MUST read the backend's configured per-chunk/operation size and
format limits before fixing `chunk_size_bytes`; client constants cannot override server
admission.

### Seal

`POST /brain-dump-operations/{operation_id}/seal`

Request:

```json
{
  "expected_revision": 4,
  "expected_chunks": 12,
  "manifest_hash": "<64 lowercase hex>"
}
```

Requires a persisted idempotency key. Seal is attempted only after all local chunks are
acknowledged. Incomplete/conflicting manifests return a visible error and no processing
claim.

### Processing and retry

The client polls GET through:

```text
sealing -> fast_processing -> accurate_transcribing -> reconciling
        -> awaiting_confirmation
```

It renders stage text/indeterminate progress, not a fake percentage. Existing
`retryable_error`, `terminal_error`, cancel, and retry commands remain authoritative.
Closing the app does not call cancel.

### Canonical proposal edit/remove

`POST /brain-dump-operations/{operation_id}/proposals/{proposal_id}/patches` uses
`Idempotency-Key` and exactly one first-slice operation:

```json
{
  "operation": "update",
  "title": "Call the dentist",
  "base_proposal_revision": 7,
  "expected_operation_revision": 12
}
```

or:

```json
{
  "operation": "remove",
  "base_proposal_revision": 7,
  "expected_operation_revision": 12
}
```

The server appends a user `ProposalPatch`; it never erases proposal history. The first slice
does not infer due date, Project, Tag, Priority, route, or CRT destination. Stale/overlapping
revisions return `409`; open conflicts remain visible. Any accepted patch or reconciliation
that changes `proposal_revision` atomically marks an existing frozen batch `superseded`.
The response replaces the mobile projection.

### Freeze a proposal batch

`POST /brain-dump-operations/{operation_id}/proposal-batches` uses a persisted freeze key:

```json
{
  "based_on_proposal_revision": 8,
  "expected_operation_revision": 13,
  "selected_proposal_ids": ["proposal_a", "proposal_b"]
}
```

The server validates that selected IDs are owner-scoped, active, title-only additions at the
current proposal revision, excludes tombstoned/superseded proposals, rejects open conflicts,
and persists an immutable `ProposalBatch` in `frozen` state. It allocates stable ordered
`action_id` values and returns each action's proposal ID, title, typed target, source cue,
warning/confidence, destination `native_inbox`, and before/after summary. Those fields are the
persisted action snapshot. It contains no result status or Task ID. Only one frozen batch is
active; a new freeze supersedes the prior one. A frozen batch never changes in place.

For a one-time imported `legacy_preview_only` operation, the projection must visibly carry
`provisional_only`, preserve imported segment/proposal IDs, title locks, and remove
tombstones, and report `accurate_reconciliation_available=false`. Freeze returns `409` until
the user has explicitly accepted the provisional review through the canonical
`review-provisional` command. The warning is copied into every selected action snapshot and
remains visible through confirmation; neither retry nor an alias may describe the import as
accurately reconciled.

### Confirm the frozen batch

`POST /brain-dump-operations/{operation_id}/confirm` uses the persisted confirm key:

```json
{
  "proposal_batch_id": "batch_opaque",
  "expected_batch_revision": 1,
  "expected_operation_revision": 14
}
```

The server accepts only the current `frozen` batch whose proposal revision still matches.
For every action it derives `H(operation_id, batch_id, action_id)`, persists the title-only
Inbox Task and append-only immutable action receipts, and folds those receipts to return
per-action status/result IDs in batch order. Results are a projection beside the frozen action,
never fields written back into it. The client label is `Confirm N additions`, never “send” or
“save” before confirm. A `legacy_preview_only` batch additionally keeps the visible
`provisional_only` warning before this separate confirmation.
A timeout retry reuses the exact same key and body; reopening first GETs the projection.
Parent-key conflicts return `409 IDEMPOTENCY_CONFLICT`, while deterministic child receipts
prevent duplicate Tasks after process restart, partial failure, a mixed legacy/canonical
retry, or a later outer request. No Task exists before this command.

### Raw-audio retention and delete now

After successful reconciliation, `raw_audio.retained_until` defaults to 24 hours under
server configuration and `delete_now_available=true`. Terminal/cancelled operations expose
their applicable configured state rather than inventing successful cleanup.

`POST /brain-dump-operations/{operation_id}/audio/delete` uses a persisted key and:

```json
{ "expected_operation_revision": 15 }
```

It is available after processing reaches Review or a terminal/cancelled state. Before that,
the user cancels/discards the operation instead. The command is owner-scoped and idempotent,
sets `deletion_pending` before physical cleanup, survives restart, and eventually returns
`deleted`/`deleted_at`; repeated calls return the same result. It removes raw server chunks
and disables future accurate-audio retry but never deletes confirmed Tasks, immutable action
receipts, or required non-audio provenance. Mobile distinguishes local audio deletion from
server deletion and keeps a non-content pending command pointer until acknowledged.

### Cancellation/discard

- local discard before server operation: delete local file/manifest;
- server operation exists: issue existing cancel command idempotently, then follow server
  state and retention rules;
- cancellation during commit does not compensate already committed actions;
- consent withdrawal and delete-now persist their keys before local cleanup and never claim
  remote deletion until the server projection reports it;
- local cleanup never claims remote cancellation succeeded.

## Error-to-UX mapping

| Status/class | Mobile behavior |
|---|---|
| Network/offline | Preserve command key and recoverable local intent; show offline/retry. General Task writes are not queued beyond the active screen. |
| `400` semantic validation | Show server message + correlation; do not retry unchanged. |
| `401` | Delete SecureStore token and in-memory owner/query/proposal state; quarantine durable Voice recovery and reveal it only after the same opaque owner ID reauthenticates or explicitly discards it. |
| `404` | Treat protected resource as missing/not-owned; remove stale navigation pointer without probing. |
| `409` stale revision | Refetch canonical projection; preserve user input and require explicit retry. |
| `409` idempotency conflict | Stop automatic retry; expose correlation/reference and preserve evidence. |
| `422` request contract | Treat as client defect; redact payload and surface generic actionable error. |
| `429` | Show retry guidance; do not reveal account existence. |
| `5xx` / provider retryable | Keep durable checkpoint/key, show retryable stage and correlation; never report success. |
| terminal operation error | Preserve salvage/delete choices and prove no unconfirmed Task creation. |

## Generated-client boundary

Generated files contain DTOs and route signatures only. A handwritten transport wrapper
owns:

- API origin;
- SecureStore credential provider;
- Authorization and `Idempotency-Key` headers;
- correlation extraction and redacted `ApiError`;
- no-store handling for session establishment;
- cancellation/AbortSignal;
- contract-version/drift assertions.

Generated files do not read SecureStore, navigate, persist, retry mutations automatically,
or map states to product copy. Mobile features own those policies.
