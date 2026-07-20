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
- Mobile protected requests use exactly one `Authorization: Bearer <opaque-session-token>`.
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

### Start

`POST /brain-dump-operations` with `Idempotency-Key` and existing
`BrainDumpOperationStartRequest`.

The client requests microphone permission and records external-processing consent before
creating this operation. It persists the start idempotency key before first attempt and
sends no provider secret. If permission is denied, no operation is created. If external
processing is not allowed and no local provider is configured, no audio upload/provider call
occurs. Recording may be captured locally while offline; the start request then occurs after
reconnect and MUST succeed before the first chunk upload.

### Get/resume

`GET /brain-dump-operations/{operation_id}` returns the current owner-scoped projection.
Mobile polling is the correctness fallback. Reopen starts with GET and reconciles local
chunk/checkpoint state against the response.

### Audio chunks

`PUT /brain-dump-operations/{operation_id}/audio/{chunk_number}`

Headers:

```text
Authorization: Bearer <opaque>
X-Content-SHA256: <64 lowercase hex>
Content-Type: application/octet-stream
```

Body: exact chunk bytes.

Rules:

- chunk numbers are monotonically assigned from zero in the local manifest;
- same operation/number/hash/content retry returns success and no duplicate;
- same operation/number with different content returns `409 CHUNK_CONFLICT`;
- the client marks `acknowledged=true` only after success;
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

### Proposal edit/remove

`PATCH /brain-dump-operations/{operation_id}/proposals/{proposal_id}` with
`Idempotency-Key` and expected proposal revision.

The first slice may edit `title` or set `deleted=true`. It does not infer due date, Project,
Tag, Priority, route, or CRT destination. Server response replaces the projection. Stale
revisions return `409`; open conflicts remain visible and confirmation is unavailable.

### Confirmation

Existing command route:

```text
POST /brain-dump-operations/{operation_id}/commit
Idempotency-Key: <persisted confirm key>
{ "expected_revision": N }
```

The client label is `Confirm N additions`, never “send” or “save” before commit. The server
creates only active selected title-only Inbox actions. Timeout retry reuses the same key.
Success returns committed Task IDs; partial/retryable results remain visible through the
operation projection. No Task exists before this command.

### Cancellation/discard

- local discard before server operation: delete local file/manifest;
- server operation exists: issue existing cancel command idempotently, then follow server
  state and retention rules;
- cancellation during commit does not compensate already committed actions;
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
