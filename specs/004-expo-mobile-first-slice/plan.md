# Implementation Plan: Expo mobile first slice

**Branch**: `wt/t_d081befc` | **Date**: 2026-07-20 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification, clarification decisions, ADR-0008, and design artifacts under
`specs/004-expo-mobile-first-slice/`

## Summary

Add one Expo SDK 57 / React Native application under `mobile/` for iOS and Android. The app
uses an additive mobile transport for BrainBuddy's existing server-owned opaque Session,
consumes generated DTOs from the FastAPI OpenAPI v1 contract, presents canonical GTD
projections/actions, and implements a bounded foreground Voice Brain Dump from durable local
recording through resumable upload, persisted processing, proposal review, and explicit
confirmation. The existing Vite web app, Tasks module, voice operation workflow, Identity
ownership, and CRT remain authoritative and are not rewritten.

## Technical Context

**Language/Version**: Python 3.11 backend; TypeScript strict; Expo SDK 57 with its pinned
React Native/React versions

**Primary Dependencies**: Existing FastAPI/Pydantic/AuthService/Tasks workflow; Expo Router,
`expo-secure-store`, `expo-audio`, `expo-file-system`, Expo Crypto/runtime SHA-256 support,
React Query, `openapi-typescript` + `openapi-fetch`, Lucide React Native

**Storage**: Existing backend JSON Sessions and SQLite Tasks/operations; SecureStore for one
opaque credential; app-document audio plus an atomic JSON recovery manifest; in-memory
React Query cache only

**Testing**: pytest/FastAPI TestClient/Schemathesis; Jest via `jest-expo` + React Native
Testing Library + Allure Jest adapter/helper; deterministic integration harness; Maestro (or
accepted black-box equivalent); Android/iOS simulator and real-device smoke; privacy scan

**Target Platform**: iOS and Android internal/development builds; foreground operation only

**Project Type**: Existing modular-monolith web/API plus one native mobile client

**Performance Goals**: local waveform/duration feedback under 100 ms; no main-thread file
hash/upload loop; list first content from cached/network projection without fetching all
pages; post-stop upload/progress truthful; retain ADR-0002 processing budgets where backend
supports them

**Constraints**: no JWT or client-owned owner ID; HTTPS production API; exactly one credential
source; no token/password/content in logs or ordinary storage; explicit confirmation before
Task creation through canonical frozen batches; current provider-category-bound consent and
visible raw-audio retention/delete-now; API v1 compatibility; 44-point touch targets; reduced
motion; no background recording/live proposals/general offline task queue

**Scale/Scope**: one active local Voice Brain Dump recovery manifest; existing server limits
for task pages/audio/chunks/operation recovery; M-01/M-02/M-03/M-06 Build,
M-04/M-05/M-07/M-08 Bounded, M-09 Deferred

## Constitution Check

*GATE: Passed before Phase 0 research and re-checked after Phase 1 design.*

- **Spec workflow**: `spec.md` was created through the sequential Spec Kit feature path,
  `/speckit-clarify` decisions are recorded, and plan/checklist/tasks follow in order.
  Implementation remains blocked until these artifacts and ADR-0008 are reviewed.
- **Consent & Safety**: microphone permission and external processing consent remain separate.
  The session token uses SecureStore only. Audio starts in app-document storage and leaves
  the device only after an unexpired grant matches the server policy/provider categories.
  Restart/config change revalidates; withdrawal stops future attempts and schedules cleanup.
  Raw-audio `retained_until` and delete-now remain visible. No raw credential/content/path/hash
  enters logs, fixtures, PR evidence, or generic persistence.
- **Tested Delivery**: backend mobile-auth tests, OpenAPI/Schemathesis, generated-client drift,
  mobile unit/component/integration, simulator/device, interruption/idempotency/privacy, and
  two-platform build evidence are failing-first gates. All mobile tests emit Allure taxonomy.
- **Contract First**: ADR-0008 and `contracts/mobile-api.md` define transport, ownership,
  versioning, API subset, errors, revocation, retries, and operation authority before client
  code. Pydantic/OpenAPI remains source of truth.
- **Observability**: every request/error retains `X-Correlation-ID`; mobile `ApiError` carries
  status/reference only and redacts body content. Operation UI shows real stage/retry/cancel/
  partial states and no fake percentage.
- **Mobile/resilience/performance**: foreground audio is durable before upload; a local atomic
  manifest stores checkpoints and command keys; app close never commits/cancels; reconnect
  reconciles server projection. The CRT is not rendered, so the 200-node web-canvas gate is
  unchanged.
- **Delivery boundary**: Spec Kit produces planning only. Hermes Kanban, isolated worktrees,
  TDD, independent review, CI, PR merge, internal build approval, and human-controlled store
  release remain authoritative.
- **Complexity**: one additive auth endpoint and dual-source resolver are justified by native
  secure storage. No mobile BFF, broker, root workspace, shared runtime package, JWT family,
  generated native project, or new canonical store is added.

No constitution waiver is required.

## Project Structure

### Documentation (this feature)

```text
specs/004-expo-mobile-first-slice/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── mobile-api.md
├── checklists/
│   ├── requirements.md
│   └── mobile-boundaries.md
└── tasks.md

docs/decisions/
└── 0008-add-one-expo-mobile-client-over-opaque-sessions.md
```

### Backend changes

```text
backend/app/
├── core/config.py                 # ApiSettings.semantic_version
├── main.py                        # OpenAPI API version, storage version remains health data
├── schemas/auth.py                # SessionCredentialResponse
├── schemas/tasks.py               # canonical batch/consent/retention transport DTOs
├── services/auth_service.py       # shared verified login returning raw token + Session
├── api/auth.py                    # POST /auth/mobile/sessions; header-aware logout
├── api/dependencies.py            # one-source cookie/Bearer resolver
├── api/tasks.py                   # canonical Voice routes + deprecated alias adapters
└── modules/tasks/
    ├── domain.py                  # ProposalBatch/receipts/consent/raw-audio state
    ├── repository.py              # additive payload migration + media deletion
    └── service.py                 # patch/freeze/confirm/consent/retention authority

backend/tests/
├── test_mobile_session_api.py     # new auth/transport/ownership tests
├── test_auth_routes.py            # browser cookie regression
├── test_api_contract.py           # precise statuses/version/error envelopes
├── test_schemathesis_contract.py  # header/mobile-auth contract coverage
├── test_brain_dump_confirmation_contract.py
├── test_brain_dump_operation_migration.py
├── test_brain_dump_consent.py
└── test_brain_dump_retention.py

frontend/src/features/brain-dump/
├── BrainDumpRoute.tsx             # migrate web review to patch/freeze/confirm
└── BrainDumpRoute.test.tsx        # canonical path + alias-overlap regression

docs/
├── auth.md
└── api-compatibility.md
```

Prefer a small pure credential parser in `backend/app/api/dependencies.py`. If route and test
complexity make that file unwieldy, extract only parsing/resolution into
`backend/app/api/session_auth.py`; do not create a new Identity module or repository.

### Mobile application

```text
mobile/
├── app.config.ts
├── eas.json
├── package.json
├── package-lock.json
├── tsconfig.json
├── babel.config.js
├── jest.config.js
├── app/
│   ├── _layout.tsx
│   ├── (auth)/sign-in.tsx
│   └── (app)/
│       ├── _layout.tsx
│       ├── tasks/[state]/index.tsx
│       ├── tasks/detail/[taskId].tsx
│       ├── projects/[projectId].tsx
│       ├── tags/[tagId].tsx
│       └── brain-dump/
│           ├── new.tsx
│           ├── [operationId]/index.tsx
│           └── [operationId]/review.tsx
├── src/
│   ├── api/
│   │   ├── generated/             # generated DTOs/operations only
│   │   ├── client.ts              # redacted transport + credential provider
│   │   ├── auth.ts
│   │   ├── tasks.ts
│   │   └── brainDump.ts
│   ├── auth/
│   │   ├── AuthProvider.tsx
│   │   ├── secureSession.ts
│   │   └── installMarker.ts
│   ├── design/
│   │   ├── tokens.ts
│   │   └── contract.test.ts
│   ├── features/tasks/
│   │   ├── TaskDrawer.tsx
│   │   ├── TaskListScreen.tsx
│   │   ├── TaskDetailScreen.tsx
│   │   ├── TaskCreator.tsx
│   │   └── taskHooks.ts
│   ├── features/brainDump/
│   │   ├── AudioRecorderPort.ts
│   │   ├── ExpoAudioRecorder.ts
│   │   ├── recoveryManifest.ts
│   │   ├── chunkUploader.ts
│   │   ├── operationReducer.ts
│   │   ├── RecordingScreen.tsx
│   │   ├── ProcessingScreen.tsx
│   │   └── ReviewScreen.tsx
│   ├── storage/atomicJson.ts
│   └── test/allureTaxonomy.ts
├── __tests__/
│   ├── auth/
│   ├── api/
│   ├── tasks/
│   ├── brainDump/
│   └── privacy/
└── e2e/maestro/
    ├── auth-and-tasks.yaml
    └── brain-dump.yaml
```

Generated `ios/` and `android/` remain ignored under CNG. A future accepted native module
lives under `mobile/modules/` with platform tests and config plugin; it is not created in
this slice.

### Repository/build changes

```text
Makefile                              # check/generate/test mobile targets
scripts/generate_openapi.py           # ephemeral test-app snapshot only
scripts/scan_mobile_evidence.py       # deterministic canary/privacy scan
openapi/brainbuddy-v1.json            # pinned API contract snapshot
.github/workflows/ci.yml              # mobile static/contract jobs; no auto submit
.gitignore                             # generated native/build/credential exclusions
```

No root `package.json`, npm workspace, or `packages/` directory is added.

**Structure Decision**: `mobile/` is one self-contained package and deployable client. The
backend contract is shared through generated OpenAPI DTOs, not runtime source imports. Web
and native presentation remain separate; future pure-package extraction requires observed
duplication and a separate plan.

## Architecture and Contracts

### 1. Session establishment and resolver

Add `ApiSettings` to configuration with default semantic API version `1.0.0`; set FastAPI
`version` from it. Keep `/health.schema_version` unchanged. Update
`docs/api-compatibility.md` with the v1 mobile window and snapshot policy.

Refactor AuthService minimally so password verification can produce `(User, raw_token,
Session)` once. Keep existing `login()` compatibility for browser routes or adapt it through
a wrapper; do not duplicate credential verification or session generation.

`POST /auth/mobile/sessions`:

- reuses `LoginRequest`, rate limiter, generic 401, and Session repository;
- returns `SessionCredentialResponse` with expiry;
- sets `Cache-Control: no-store` and `Pragma: no-cache`;
- does not set cookie;
- declares `401/422/429/503` precisely.

Create one credential parser returning a raw token plus source enum. It accepts:

- cookie only → browser;
- `Authorization: Bearer OPAQUE_SESSION_TOKEN` only → mobile;
- neither → absent;
- both → `400` ambiguity;
- malformed scheme/value → `401`.

`get_current_user` looks up the parsed token through AuthService. Logout uses the same parser
without requiring a valid user, deletes the Session digest when present, clears browser
cookie, and remains 204 when absent.

Do not include credentials in Pydantic repr/logs. Add explicit response redaction tests using
seeded canary values.

### 2. Generated API boundary

Generate OpenAPI from `create_app()` under `BRAIN_BUDDY_ENV=test` and a temporary data root.
Commit `openapi/brainbuddy-v1.json`; never fetch production OpenAPI in CI. Use
`openapi-typescript` for DTOs and `openapi-fetch` for route signatures.

`mobile/src/api/client.ts` is handwritten and owns:

- public API origin from app config;
- injected narrow async credential provider;
- Authorization, content type, idempotency, correlation extraction;
- AbortSignal/network mapping;
- a redacted `MobileApiError {status, code?, correlationId, retryable}`;
- 401 callback that clears the credential and in-memory owner/query/proposal state while
  quarantining durable unconfirmed Voice recovery for same-owner reauthentication.

It MUST NOT serialize request bodies or response text to telemetry. Feature adapters map
camelCase UI input to generated snake_case DTOs only where needed and expose no persistence
model.

### 3. Mobile auth lifecycle

On first launch, `installMarker.ts` checks the app-document marker. If absent, it deletes the
SecureStore session and recovery directory before writing the marker. Then AuthProvider:

1. reads SecureStore;
2. with no token, renders sign-in;
3. with token, calls `/auth/me`;
4. on success, sets in-memory user and mounts owner-scoped query provider;
5. on 401/unreadable storage, clears the credential and in-memory caches, quarantines any
   durable recovery by opaque owner ID, and renders sign-in;
6. on transient network failure, renders a retry state without exposing prior owner content.

On sign-in, the token remains in a local variable until SecureStore succeeds. If save fails,
best-effort revoke using that variable and then zero/drop it. On successful reauthentication,
only a manifest with the same `/me` owner ID can be restored. Voluntary logout with active
recovery first requires cancel-sign-out or discard-and-sign-out; after that decision, clear
visible local state, attempt server revoke, and show unresolved remote revocation without
restoring the token.

Do not enable biometric-required reads in this slice. SecureStore uses a service name and
this-device-only iOS accessibility. Configure Android backup exclusion through the plugin.

### 4. Task projections and actions

Expo Router's authenticated layout defaults to `/tasks/next`. `TaskDrawer` renders exactly
four open states, active Projects, active Tags, Voice Brain Dump, and non-interactive Weekly
Review. No search/date/sort/management/CRT/Execution controls are rendered.

React Query keys include owner session generation plus normalized server filters/cursor. Use
infinite queries for list continuation. Counts remain from the server response. On mutation
success, invalidate Task root plus Project/Tag counts; on error, preserve draft/action intent.

First-slice task actions:

- literal `POST /tasks {title, state:"inbox"}`;
- complete open task;
- explicit reopen/move destination; Waiting collects `waiting_for`;
- bounded detail reads canonical fields and offers only supported lifecycle actions.

Do not expose metadata edit, Smart Add, Subtask, Comment, Project/Tag mutation, or agent/Think
controls even though some backend endpoints exist.

### 5. Canonical Voice backend prerequisite

ADR-0002 remains the server authority. Before generating or implementing the mobile Voice
adapter, extend the existing operation payload/service with:

- monotonic `proposal_revision`, persisted immutable `ProposalBatch` records, deterministic
  action IDs/receipts, and active/committed batch pointers;
- canonical `POST .../proposals/{proposal_id}/patches`, `POST .../proposal-batches`, and
  `POST .../confirm` routes;
- current consent policy query and append-only grant/withdraw decisions bound to policy
  version, required provider categories, decision time, and server expiry;
- raw-audio state, `retained_until`, and idempotent `POST .../audio/delete` after processing.

An accepted proposal patch/reconciliation increments `proposal_revision` and atomically
supersedes a frozen batch. Freeze snapshots selected active conflict-free title-only actions.
Confirm rejects stale/superseded batches and persists each Inbox Task with the child receipt
`H(operation_id,batch_id,action_id)`. The outer request key remains conflict-checked, but
child receipts are the exact-once boundary across restart, partial failure, or a new outer
request after status reconciliation.

Stored payload migration is additive. Payloads missing canonical fields derive a stable
initial proposal revision from accepted patch history, default empty batch/receipt lists, and
migrate on first canonical mutation/freeze; completed/cancelled records remain immutable.
During one bounded web overlap, direct proposal `PATCH` delegates to the same patch service and
legacy `/commit` atomically freezes the current conflict-free projection before delegating to
confirm. Mark both deprecated and exclude their operation IDs from mobile generation. Test
canonical/alias races and remove aliases only after the web client and active stored operations
no longer depend on them.

Consent currentness is checked by the mobile client before sending and by the server before
persisting upload, seal, retry, or provider work. Any expiry, withdrawal, policy-version
change, or any required category-set difference fails closed with `consent_required`. Withdrawal prevents
new provider claims, cancels not-yet-started runs, and schedules uncommitted server media/
working transcripts for deletion. Offline mobile withdrawal stops local attempts immediately
but remains remotely pending until acknowledged.

After successful reconciliation, the server publishes the configured raw-audio deadline
(ADR-0002 default 24 hours). Delete-now moves through `deletion_pending` to `deleted`, survives
restart, and removes raw media without deleting action receipts, confirmed Tasks, or required
non-audio provenance. Accurate retry is unavailable after deletion.

### 6. Voice local durability and server sequence

Define `AudioRecorderPort` before Expo implementation so unit/device tests can inject a
deterministic file. `ExpoAudioRecorder` uses `expo-audio` foreground recording configured to
write to documents. It exposes permission, record/pause/stop, URI, duration, and interruption
signals; it does not promise encoded chunks while recording.

`recoveryManifest.ts` implements the schema in `data-model.md` using `atomicJson.ts`. One
active manifest only, bound to the opaque `/me` owner ID. Persist the operation-start key,
non-secret consent policy/category/time/expiry, canonical patch/freeze/confirm/delete keys,
batch pointer, and every acknowledged chunk after response. Never write transcript, proposal,
frozen action, or Task text to this file.

After Stop:

1. fetch current processing policy; require/re-record consent if version/categories/expiry do
   not match the local decision; if no server operation exists, create it with the persisted
   start key after reconnect;
2. if an operation exists, GET its owner-scoped projection and compare consent withdrawal/
   currentness before any upload, seal, retry, or provider-triggering command;
3. stat and validate the durable file against server-configured admission limits;
4. choose bounded chunk size from the backend contract/configuration, not an invented
   constant; read/hash chunks off the UI thread where the runtime permits;
5. PUT missing chunks; same hash retries are success, conflict stops automatic retry;
6. persist expected count/manifest hash and seal with expected operation revision/key;
7. poll GET with focus/reconnect backoff through processing and replace memory projection;
8. after the sealed server copy is durable, delete local audio when no retry requires bytes,
   retaining only the non-content manifest;
9. append canonical edit/remove proposal patches with stable keys and operation/proposal
   revisions;
10. freeze selected active proposals with a persisted key and exact proposal revision;
11. confirm the returned immutable batch with the persisted key and exact batch/operation
    revisions, then reconcile per-action receipts/Task IDs before manifest cleanup;
12. show server raw-audio state/deadline and persist delete-now intent before local/remote
    cleanup; retain an honest remote-pending pointer across offline/restart.

App background/close stops relying on active JS work. The manifest and server projection are
recovery authority. Foreground recording may be interrupted by the OS; show salvage/discard
for the durable file. Closing UI never invokes cancel or commit. Consent withdrawal stops
future uploads/provider calls, deletes local audio, and invokes the persisted remote cleanup
decision without claiming offline remote success.

M-05 copy is honest: local recording, Stop & review, then upload/processing. It does not show
fake transcript or proposal cards while speaking. M-06 uses `Review N additions` and
`Confirm N additions`; Add date is absent and no metadata is inferred.

### 7. Expo/native escape and build boundary

Use SDK 57 with exact compatible dependencies committed by lockfile. `app.config.ts` owns
bundle/package IDs, permissions, plugins, public API origin, build/runtime version, and
`ios.config.usesNonExemptEncryption=false` where valid. `expo-audio` has background recording
disabled. CNG generates native projects in CI for drift review.

A Swift/Kotlin/Expo Module is not part of this plan. If continuous chunks during recording or
another required behavior cannot be achieved, create a separate spike/card. Only after the
ADR-0008 criteria pass may an implementation add `mobile/modules/` or canonical native
projects.

`eas.json` profiles:

- development: development client, simulator/emulator/device debugging;
- preview: internal distribution, non-production API environment;
- production: defined but not invoked automatically; release owner approval required.

EAS-managed credentials are acceptable, but access is least-privilege and no worker handles
raw signing material. PR CI does not submit to stores or publish OTA updates.

## Design Classification Contract

| Frame | Scope | Implementation contract |
|---|---|---|
| M-01 | Build | Next projection, metadata, completion, detail, drawer, Brain Dump; no Execution. |
| M-02 | Build | Four states, Projects, Tags, counts, Brain Dump, Weekly Review deferral. |
| M-03 | Build | Inbox projection, plain capture, completion/detail, Brain Dump. |
| M-04 | Bounded | Read fields + lifecycle only; no metadata edit/Subtasks/Comments/run log/agent. |
| M-05 | Bounded | Foreground durable record, waveform/duration, salvage, post-stop upload/processing; no live transcript/proposals. |
| M-06 | Build | Edit/remove, quality/conflicts, discard/cancel, explicit confirm; no Add date/inference. |
| M-07 | Bounded | Read-only Project task projection; no management/Think. |
| M-08 | Bounded | Read-only Tag task projection; current Tag vocabulary. |
| M-09 | Deferred | `Weekly Review · coming later`; no due cadence or workflow. |

Tests must inventory enabled controls against this table. A design screenshot cannot upgrade a
Bounded/Deferred row without amending spec, plan, tasks, and ADR where consequential.

## Test Strategy and Evidence

### Backend

Failing-first pytest/TestClient coverage:

- mobile session 201/no-cookie/no-store/expiry/token shape;
- generic 401, rate limit, invalid request, persistence failure;
- cookie and Bearer parity for `/me`, Tasks, and operations;
- malformed/dual credentials, expiry, logout/revocation, wrong owner;
- unchanged browser cookie attributes/logout;
- OpenAPI semantic version, exact intentional statuses/error envelopes/correlation;
- Schemathesis with an ephemeral bearer session as a second auth mode;
- canonical proposal-patch/freeze/supersede/confirm owner scope, revisions, parent-key
  conflicts, deterministic child receipts, partial failure, and process restart;
- additive stored-payload migration plus deprecated alias delegation/overlap/races without
  duplicate Tasks or mutation of completed/cancelled records;
- consent expiry, restart, regrant, withdrawal, policy/provider-category change, upload/
  seal/retry/provider fail-closed behavior, and cleanup scheduling;
- raw-audio retained-until projection, delete-now eligibility/idempotency/restart/owner scope,
  physical cleanup, and preserved non-audio provenance/Tasks.

### Mobile unit/component

Jest/RNTL with central Allure helper:

- SecureStore save/read/delete failures and first-install cleanup;
- auth bootstrap/401/transient network/account switch/logout;
- redacted API error and no request/response content logging;
- list query/filter/cursor/count behavior and task action keys/revisions;
- drawer/frame control inventory and accessibility/reduced motion;
- atomic manifest recovery/quarantine/cleanup plus versioned/category-bound consent,
  withdrawal pending, frozen-batch pointers, and remote-audio-delete pending;
- chunk boundaries/hashes/ack replay/conflict/seal prerequisites;
- operation reducer for every backend state and interruption checkpoint;
- canonical proposal patch/freeze/invalidate/confirm exact-once behavior and visible retention.

### Integration/E2E/device

- deterministic fake audio/provider end-to-end against temporary backend;
- >50 task pagination and web/mobile parity;
- process restart at recorded/upload/sealed/processing/review/frozen/confirm-timeout/
  audio-deletion-pending checkpoints;
- permission, consent expiry/withdrawal/policy-category change, network, storage, audio-route,
  provider, stale batch, cancellation, partial confirm, retained-until/delete-now, and logout
  failure paths;
- Android/iOS development and preview builds;
- one real-device smoke each for Keychain/Keystore, microphone, interruption, network resume;
- privacy canary scanner over logs, Allure, screenshots/video, bundle/source map, generated
  native config, and build output.

Allure taxonomy must include non-empty epic, feature, story, human title, and named product
step for pytest, mobile Jest, and black-box device tests.

## Migration and Rollback

### Migration

1. Land API semantic-version configuration and snapshot tooling; preserve health storage
   version.
2. Land mobile session endpoint/resolver behind tests; browser remains unchanged.
3. Scaffold mobile/CNG/static gates and generated client.
4. Deliver secure auth plus read-only Next/Inbox as the first internal checkpoint.
5. Add list continuation/basic Task actions and bounded detail/Project/Tag projections.
6. Land canonical proposal-batch/confirm, consent policy/decisions, retention/delete-now, and
   legacy overlap/migration behind failing backend tests; migrate web off deprecated aliases.
7. Regenerate the mobile operation allowlist/client without deprecated aliases.
8. Add foreground local recording and versioned recovery manifest.
9. Add upload/seal/poll/patch/freeze/confirm/delete-now exact-once path.
10. Produce both-platform internal/device/privacy evidence before release review.

No persisted Session migration is required. Existing API/storage records are additive and
mobile uses the same canonical records. If selective mobile-session revocation becomes a
release requirement, amend the Session schema with backward-compatible `channel="browser"`
default before public rollout; do not infer channel from token shape.

### Rollback

- disable/remove `POST /auth/mobile/sessions` and stop native distribution;
- revoke affected Sessions (global reset if no channel exists) and clear app SecureStore/
  recovery data;
- prior browser sessions/Tasks/operations remain structurally valid;
- never downgrade or replay migrated proposal batches/action receipts. If mobile Voice has
  consumed canonical routes, keep them through the published support window; before release,
  disabling the client leaves canonical backend records readable and resumable;
- deprecated aliases may remain only for the documented web/active-operation overlap and
  still delegate to canonical records; rollback must not restore a parallel direct-write path;
- never delete already confirmed Tasks automatically;
- accepted withdrawal and raw-audio deletion commands continue draining after client rollback;
  unconfirmed local/server artifacts follow explicit discard/retention cleanup;
- CNG allows reverting app/config/plugin sources without repairing committed native projects.

## Release Gates

1. Spec check and ADR/mobile-boundary review.
2. Backend auth/contract/Schemathesis plus canonical Voice confirmation/migration/consent/
   retention and alias-overlap races green.
3. Generated OpenAPI/client drift clean.
4. Expo Doctor, lint, typecheck, Jest/Allure green.
5. Deterministic integration and privacy scan green.
6. Android and iOS development/preview builds successful.
7. Simulator/emulator journeys plus one real-device smoke per platform.
8. Control inventory matches M-01..M-09 classification.
9. Independent QA review and PR CI green.
10. Separate human approval for production signing/store submission; no automatic rollout.

## Complexity Tracking

No constitution violation is accepted. The only new cross-cutting mechanisms are:

| Complexity | Why needed | Simpler alternative rejected because |
|---|---|---|
| Additive mobile session transport | Native app must protect/reuse a revocable credential outside browser cookies | Cookie jars do not provide the explicit SecureStore contract; JWT adds more ownership complexity |
| Atomic local voice recovery manifest | Native interruptions must not silently lose a recording or regenerate command keys | Memory/query cache disappears on process death and cannot resume upload/commit safely |
| Generated OpenAPI snapshot/client | A second long-lived client creates compatibility obligations | Hand-copied TypeScript models drift and a handwritten shared domain package duplicates authority |
| Persisted proposal batches/action receipts | Review authority and child exact-once behavior must survive edits, restart, and alias overlap | Direct mutable proposals plus one outer commit key cannot freeze user intent or deduplicate partial child writes |
| Versioned consent and visible raw-audio retention | Restart/provider change/withdrawal/delete-now must fail closed and remain honest | A local boolean and hidden server cleanup cannot prove current consent or user-controlled deletion |

These mechanisms remain inside the existing Identity/API/mobile boundaries and introduce no
new canonical store, service, broker, or deployment control plane.
