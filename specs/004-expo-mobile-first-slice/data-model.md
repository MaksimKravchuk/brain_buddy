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

### BrainDumpOperation (existing workflow record)

The mobile app consumes the existing `BrainDumpOperationResponse` and commands. Canonical
fields remain backend-owned. Mobile never persists a second proposal or operation domain
model; it caches a replaceable projection and stores only the recovery pointer below.

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
  schema_version: 1
  local_manifest_id: UUID
  owner_id: opaque server User ID
  start_idempotency_key: UUID
  server_operation_id?: string
  operation_revision?: integer
  audio_uri: app-document URI
  audio_format: string
  audio_size_bytes?: integer
  duration_ms?: integer
  consent_recorded: boolean
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
  proposal_command_keys: map<proposal_id, UUID>
  confirm_idempotency_key?: UUID
  local_status:
    recording | recorded | preparing_chunks | uploading |
    ready_to_seal | sealed | processing | awaiting_confirmation |
    committing | cleanup_pending | recoverable_error
  last_error_code?: enum
  created_at: UTC datetime
  updated_at: UTC datetime
```

Do not persist the raw session token, email, transcript text, proposal titles, task titles,
or provider response in this manifest. `owner_id` is the opaque server ID returned by `/me`;
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
- delete manifest and audio only after server state and retention policy permit cleanup;
- on parse/schema failure, preserve audio, quarantine the manifest, and offer explicit
  salvage/discard rather than silently deleting the recording.

Local state transitions:

```text
recording -> recorded -> preparing_chunks -> uploading
uploading -> uploading | ready_to_seal | recoverable_error
ready_to_seal -> sealed -> processing
processing -> processing | awaiting_confirmation | recoverable_error
awaiting_confirmation -> committing | cleanup_pending
committing -> awaiting_confirmation | cleanup_pending | recoverable_error
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

## Retention and deletion

- Session token: until logout, server expiry/revocation, unreadable SecureStore, or first-
  install cleanup.
- Query/proposal projections: memory only; clear on logout and process termination.
- Local audio/manifest: retain only while recording/upload/recovery/confirmation requires
  them; delete after successful reconciliation/commit or explicit discard under the
  accepted operation retention policy.
- Server audio/transcript/operation artifacts: unchanged ADR-0002/backend policy; mobile
  cannot shorten server retention by deleting its local copy.
