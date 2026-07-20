# ADR-0008: Add one Expo mobile client over server-owned opaque sessions

Date: 2026-07-20
Status: Proposed
Decision owner: BrainBuddy
Last amended: 2026-07-20 (canonical confirmation, consent recovery, and audio retention)
Related: ADR-0001, ADR-0002, ADR-0006, `docs/auth.md`,
`docs/api-compatibility.md`, `docs/vnext-cloud-design-build-contract.md` §3.3,
`specs/004-expo-mobile-first-slice/`

## Context

BrainBuddy now has a working tasks-first responsive web client, owner-scoped FastAPI Task
and Voice Brain Dump APIs, server-side opaque cookie sessions, and accepted mobile design
frames. It does not have a native application. The first native slice must make Voice Brain
Dump and basic canonical Tasks useful on iOS and Android without creating a second domain,
a parallel identity system, or a permanent mobile-specific backend.

The existing browser session is delivered only as an HTTP-only same-origin cookie. That is
the right browser control, but a React Native client does not share the browser's
same-origin proxy or a reliable application-controlled HTTP-only cookie jar. Returning a
JWT would solve transport by changing ownership semantics: identity and expiry claims
would move into a client-carried self-contained token even though BrainBuddy already has
immediately revocable server sessions. Copying the raw cookie into ordinary mobile storage
would discard the main security benefit of the current browser design.

The accepted mobile frames also contain more capability than a coherent first slice. M-04
shows Subtasks, Comments, and speculative run actions; M-05 assumes proposals while
speaking; M-06 shows optional metadata; M-07 includes Think; M-09 depicts a Weekly Review
placeholder. ADR-0002 requires honest provisional authority and explicit confirmation, but
the shipped backend remains a bounded subset of its complete event, reconciliation,
retention, undo, and live-streaming contract. The native plan must classify rather than
silently implement these exploratory controls.

Expo SDK 57 provides SecureStore, foreground audio recording to the application documents
directory, config plugins, development builds, Continuous Native Generation (CNG), and EAS
Build. `expo-audio` makes a completed recording URI available and can keep the file outside
evictable cache, but it does not establish a product-safe encoded-chunk stream while an
active recording is in progress. Requiring simultaneous record-and-upload now would either
pretend that a completed file is streaming or force a native recorder module before the
bounded user journey proves value.

## Decision

### One application and existing backend

Add exactly one native application at `mobile/`, targeting iOS and Android from one Expo /
React Native codebase. Keep `frontend/` as the Vite web client and `backend/` as the one
FastAPI modular monolith. The mobile app is a presentation, device-integration, and
recovery client; it owns no canonical Identity, Task, Project, Tag, Capture, operation, or
CRT record.

Do not make the repository a universal Expo web app and do not create `mobile-ios/`,
`mobile-android/`, a mobile backend-for-frontend, or a second API. Platform-specific
source files are allowed only behind a narrow interface inside `mobile/` when behavior
actually differs.

### Mobile session establishment without JWT

Identity continues to issue one server-owned `Session` containing only a SHA-256 digest of
an opaque 256-bit random credential, user ID, creation time, and absolute expiry. The raw
credential is never persisted server-side. Browser behavior remains unchanged.

Add an explicit native session-establishment operation:

```text
POST /api/auth/mobile/sessions
Content-Type: application/json

{ "email": "...", "password": "..." }

201
Cache-Control: no-store
Pragma: no-cache
{
  "session_token": "<opaque random value returned once>",
  "token_type": "Bearer",
  "expires_at": "<UTC timestamp>",
  "user": { "id": "...", "email": "..." }
}
```

It uses the existing password verification, generic credential error, source-IP rate
limiter, session repository, and expiry. It does not set the browser cookie. It returns no
refresh token, JWT, owner claim, scopes, provider secret, or device fingerprint.

Native protected requests send:

```text
Authorization: Bearer OPAQUE_SESSION_TOKEN
```

“Bearer” describes possession semantics in the HTTP header; the value is not a JWT and has
no client-readable claims. `get_current_user` resolves either the existing session cookie
or this header through the same `AuthService.get_user_for_token`. A request with both
credential sources is rejected as ambiguous; the server never silently prefers one.
Missing, malformed, expired, revoked, or unknown credentials return the existing
correlation-bearing `401` envelope and do not reveal a user or session.

`POST /api/auth/logout` revokes the current cookie or Bearer session and remains idempotent
when no credential is present. Ambiguous credential input is the only new `400` case. The
mobile client deletes its local credential and owner-scoped caches even if logout cannot
reach the server; it reports remote revocation as unresolved rather than retaining the
local secret.

The mobile app stores only `session_token` in `expo-secure-store`, using an app-specific
service and an iOS this-device-only accessibility class. It never stores the password.
Query caches are memory-only. Session values never
enter Zustand persistence, AsyncStorage, FileSystem, URLs, Redux/React Query devtools,
telemetry, crash reports, screenshots, fixtures, or test artifacts.

Because iOS Keychain values can survive uninstall/reinstall with the same bundle ID, the
app maintains a non-secret installation marker in application files. On a launch where the
marker is absent, it deletes any residual SecureStore session before creating the marker.
This marker is not identity, authorization, analytics, or a stable fingerprint.

### API contract and compatibility ownership

Before a mobile build consumes `/api`, separate API semantic version from persisted-data
schema version:

- `AppConfig.api.semantic_version` owns OpenAPI `info.version`, starting at `1.0.0`;
- `/health.schema_version` continues to report storage schema version;
- a pinned OpenAPI v1 snapshot is generated from the ephemeral test app and committed for
  mobile contract generation/drift review;
- additions within `/api` v1 are backward-compatible only when existing field meanings,
  requiredness, enum sets, and statuses remain compatible;
- a breaking change requires a versioned route/contract, a documented migration window,
  and support for the current and immediately previous released mobile contract until the
  prior app version is outside the published support window.

The backend Pydantic/OpenAPI contract remains source of truth. Generate transport DTOs and
client method signatures into `mobile/src/api/generated/`; do not hand-copy backend domain
models into a “shared” package. Mobile-owned view models map generated DTOs to UI state but
may not add domain states or infer server authority.

The pinned snapshot may still describe deprecated web-compatibility aliases during their
bounded overlap window, but mobile generation uses an explicit operation allowlist. Direct
proposal `PATCH`, `/finish`, and `/commit` are marked deprecated and excluded from the mobile
adapter. Their removal is not a mobile breaking change because no released mobile contract
may consume them.

Do not introduce a root JavaScript workspace or runtime `packages/` layer in the first
slice. Extract a package later only after two real consumers need the same platform-neutral
code. Such a package may contain generated DTOs, pure parsing/formatting, or token constants;
it must not contain React DOM or React Native components, navigation, SecureStore,
FileSystem, fetch credential policy, Zustand stores, repositories, or domain transitions.
Design values remain governed by `.claude/skills/brain-buddy-design/`; mobile mirrors the
required values in a native token module with drift/adherence tests rather than importing
CSS.

### ADR precedence and scoped mobile refinement

ADR-0002 remains authoritative for the shared operation state machine, append-only proposal
patches, persisted `ProposalBatch`, freeze/invalidation/confirmation, deterministic action
keys, consent, retention, owner scope, and the long-term live-proposal product target. This
ADR refines only the first Expo client's capture timing: M-05 records durably in the
foreground and uploads after Stop because the accepted Expo primitive does not expose a
proven safe encoded-chunk stream while recording.

For this first mobile slice, this ADR therefore controls the mobile capture UI and transport
timing where ADR-0002 rejects batch-only-after-recording as the general primary UX. It does
not supersede ADR-0002 for the backend, web/live clients, confirmation authority, or future
mobile slices. Post-stop upload is a bounded fallback with an explicit native-escape trigger,
not a new canonical operation model; any broader or permanent change requires amending both
records.

### Task and Voice Brain Dump integration

Mobile calls the owner-scoped Task, Project, Tag, and canonical operation endpoints. The
confirmation/consent/retention prerequisites below are additive backend work, not a mobile
BFF. It preserves server pagination, expected revisions, `Idempotency-Key`, correlation IDs,
wrong-owner `404`, stale `409`, and the accepted Task transition matrix. Task writes are not
queued as an offline second store; the app requires a server result before reporting
success.

The first slice builds:

- M-01 Next actions, M-02 drawer, and M-03 Inbox;
- the same list projection for Waiting and Someday;
- bounded M-04 detail: canonical fields plus lifecycle actions, without metadata editing,
  Subtasks, Comments, or Execution controls;
- bounded M-07 Project and M-08 Tag task projections, read-only as classifications;
- M-05 foreground Voice Brain Dump with durable local audio and post-stop resumable upload;
- M-06 proposal review/edit/remove/cancel/confirm with explicit authority language.

M-09 Weekly Review remains non-interactive `coming later`. CRT/Think, AI/Execution,
external routing, Smart Add, task metadata editing, Project/Tag management, reminders,
notifications, live proposals while speaking, background recording, and general offline
Task sync are non-goals.

For the bounded voice path:

1. request microphone permission;
2. fetch the non-secret processing policy and record external-processing consent separately,
   bound to its policy version, required provider categories, decision time, and expiry;
3. atomically initialize an owner-bound local recovery manifest and persist the operation-
   start idempotency key;
4. create the owner-scoped operation as soon as the network permits and record in the
   foreground to `expo-audio` document storage; local recording may proceed offline, but
   upload cannot begin before operation creation succeeds;
5. after Stop, split/read the completed file into bounded numbered chunks, hash locally,
   upload idempotently, and seal only after every chunk is acknowledged;
6. poll the persisted operation projection through processing/retry states;
7. append user edit/remove proposal patches using expected operation/proposal revisions and
   durable command keys; any accepted patch supersedes a previously frozen batch;
8. freeze the selected active proposals into a persisted immutable `ProposalBatch` and then
   explicitly confirm that exact batch; the server derives one action key as
   `H(operation_id, batch_id, action_id)` and persists the action receipt with its Task;
9. show the server's raw-audio deletion state and `retained_until`, allow delete-now after
   processing, and delete the local audio as soon as upload recovery no longer needs it while
   retaining only the non-content command/recovery pointer still needed for confirmation.

The server exposes the current policy version and required provider-category identifiers
without vendor credentials. A consent grant is current only while unexpired, not withdrawn,
and valid for that exact policy/category set. Recovery after restart must refetch the owner-
scoped operation/policy and compare those fields before upload, seal, retry, or provider work.
A category-set/policy change fails closed and requires a new visible grant. Withdrawal immediately
stops local upload attempts, appends an idempotent server decision when reachable, prevents
new provider claims, and schedules uncommitted server audio/working transcripts plus the
local recording for deletion. Offline withdrawal is shown as remotely pending rather than
claiming a provider was stopped.

An involuntary `401` clears the credential and in-memory owner projections but quarantines
an unconfirmed recording. It becomes visible again only when the same opaque owner ID
reauthenticates, or can be explicitly discarded without exposing content to another owner.
Voluntary logout with active recovery requires a cancel-sign-out or discard-and-sign-out
decision; logout never silently destroys a recording.

No live transcript or proposal is promised while speaking in this slice. The UI says the
recording is local and unconfirmed, then shows upload/processing before Review. This is more
honest than simulating live extraction. A later native streaming recorder may satisfy the
full simultaneous record/upload target without changing operation, chunk, seal, proposal,
batch, confirmation, consent, or retention contracts.

### Expo and native escape boundary

Use Expo SDK 57 with development builds and CNG. Commit `app.config.ts`, config plugins,
`eas.json`, JavaScript/TypeScript sources, tests, and lockfile; do not commit generated
`ios/` or `android/` directories initially. Use `expo-audio`, `expo-file-system`,
`expo-secure-store`, and other Expo modules through supported config plugins. Expo Go is a
convenience, not release evidence.

A native Swift/Kotlin or checked-in native-project escape requires all of:

1. a written capability gap with a reproducible Expo-managed spike;
2. a user-visible requirement that cannot be met by an existing supported module/config
   plugin (likely continuous encoded-audio chunks, robust background recording, or a
   platform security primitive);
3. a narrow TypeScript interface and deterministic fake before native implementation;
4. iOS and Android parity or an explicit product exception;
5. native unit/instrumentation tests, lifecycle/interruption/device evidence, and a rollback
   path;
6. an ADR amendment if native directories become canonical or the build boundary changes.

Prefer an Expo Module plus config plugin under `mobile/modules/` / `mobile/plugins/` before
abandoning CNG. Do not eject merely to adjust plist/manifest entries that a plugin can own.

### Build, signing, and release authority

`mobile/app.config.ts` owns public bundle/package identifiers, version metadata, required
permissions, and public API origin per profile. It contains no secret. `mobile/eas.json`
defines development, preview/internal, and production profiles with separate update/runtime
channels only when OTA updates are later accepted.

- PR CI owns lint, typecheck, unit/component tests, generated-contract drift, privacy scans,
  backend contract tests, Expo Doctor, and reproducible native configuration generation.
- Simulator/emulator builds use non-production credentials and run the critical session,
  list, task, and deterministic voice-fixture journeys.
- Preview EAS builds use internal distribution and project-scoped EAS access. They are
  acceptance artifacts, not production releases.
- The BrainBuddy app-store account owner controls Apple/Google memberships, bundle/package
  registration, production certificates/profiles/keystore, and store submission. EAS may
  manage signing material, but repository workers never print, download, commit, rotate,
  or broaden access to it.
- Production build/submit is a separately approved release action after PR merge, green
  gates, device evidence, privacy review, and rollback readiness. This ADR does not
  authorize automatic store submission or public rollout.

## Rationale

One mobile app preserves product coherence and keeps the modular monolith's ownership
valuable. The app can deliver the mobile-first workflow without creating synchronization
between native and web stores.

Returning the existing opaque credential through an explicit non-cookie operation is the
smallest mobile-safe auth change. SecureStore protects possession on-device while the
server retains immediate revocation and ownership resolution. No JWT claims, refresh-token
family, signing key, claim migration, or dual identity semantics are needed.

Foreground recording plus post-stop chunk upload is deliberately narrower than the leading
“stream everything live” design. It proves native permission, local durability, upload,
processing, review, and confirmation with supported Expo primitives. It also exposes the
actual capability gap before paying for native recorder code. The cost is delayed proposals,
which the UI must state honestly.

Generated transport contracts keep the second client aligned without prematurely sharing
framework code. React DOM and React Native have different rendering, navigation,
accessibility, storage, and lifecycle requirements; a universal component library now would
hide rather than remove those differences.

## Alternatives considered

### Reuse browser cookies unchanged

Rejected. Native cookie behavior is not the accepted same-origin browser proxy, does not
provide a clear SecureStore boundary, and complicates deterministic revocation/testing.
The browser keeps its stronger HTTP-only cookie; mobile receives the same server session
through an explicit transport.

### Add JWT access and refresh tokens

Rejected. This introduces self-contained claims, signing/rotation policy, refresh-token
reuse detection, and two session ownership models without a product need. Opaque server
sessions already provide entropy, expiry, digest-at-rest, and instant revocation.

### Build a universal Expo web/native client

Rejected. It would replace a working Vite shell and force DOM/native abstractions into the
first mobile slice. API and product contracts are shared; presentation is not.

### Create a shared domain package first

Rejected. Backend Pydantic/domain code is authoritative and Python-owned. A handwritten
TypeScript domain package would become another source of truth. Generate transport DTOs;
extract pure packages only after real duplication is observed.

### Require simultaneous upload and live proposals in the first slice

Rejected. Supported Expo recording yields a durable completed file, not a demonstrated
safe encoded-chunk stream while recording. Native code before validating the bounded flow
adds lifecycle, codec, background, build, and platform risk. Live behavior remains an
explicit later capability with an escape criterion.

### Check in native projects immediately

Rejected. CNG and config plugins own the current requirements. Canonical native directories
would increase drift and upgrade cost before custom native code exists.

### Ship only iOS because the design mirror says “Mobile (iOS)”

Rejected. The chosen framework and product contract are cross-platform; session, Task, and
operation semantics must not fork. Internal evidence may sequence platforms, but the slice
is not complete until both pass.

## Consequences

Positive:

- one canonical backend and one native client boundary;
- immediate session revocation without JWT complexity;
- credentials stay out of ordinary storage and browser behavior remains unchanged;
- a dogfoodable task/voice slice can ship with supported Expo primitives;
- native escape criteria are explicit rather than ideological;
- generated contract drift and device evidence become release gates.

Tradeoffs and risks:

- a raw opaque session credential is still a bearer secret; a compromised unlocked device
  can use it until revocation/expiry;
- iOS Keychain reinstall persistence needs explicit first-launch cleanup and device testing;
- post-stop upload delays provisional proposals and does not fulfill the complete live
  ADR-0002 target;
- local audio/recovery files require careful protection, redaction, cleanup, and low-storage
  behavior;
- a second long-lived mobile release constrains API changes and requires a real compatibility
  window;
- EAS introduces account, credential, quota, and hosted-build dependencies;
- a future streaming/background requirement may trigger native module and build complexity.

Future agents must preserve:

- Identity owns opaque sessions and owner resolution; no mobile JWT or client-owned owner ID;
- exactly one `mobile/` app, no mobile BFF or second canonical store;
- backend OpenAPI/Pydantic as the transport source of truth;
- SecureStore-only session token handling and privacy-safe evidence;
- explicit confirmation before title-only Inbox Task creation;
- canonical proposal-patch → frozen-batch → confirm sequencing, immutable frozen snapshots,
  and deterministic action receipts; deprecated direct PATCH and `/commit` aliases are not a
  mobile contract;
- current provider-category-bound consent across restart/configuration change, fail-closed
  withdrawal, visible raw-audio retention, and user-triggered delete-now after processing;
- honest bounded recording/upload states and no invented live proposals;
- M-09 Weekly Review, Execution, CRT/Think, Subtasks/Comments, metadata inference, and other
  first-slice non-goals until separately accepted;
- CNG by default and evidence-based native escape;
- production signing/submission as human-controlled release authority.

## Migration and rollback

1. Add API semantic-version ownership while retaining storage version in health output.
2. Add the mobile session endpoint and dual-source resolver additively; all existing cookie
   routes/tests remain unchanged.
3. Before generating the mobile voice adapter, add canonical proposal-patch, freeze, confirm,
   consent-decision, retention projection, and raw-audio delete commands. Existing operation
   payloads missing these additive fields load with empty batches/receipts and derive their
   initial proposal revision deterministically; completed/cancelled operations remain
   immutable.
4. During the existing web overlap window, direct proposal `PATCH` and `/commit` delegate to
   the same patch/freeze/confirm service and persisted records. A legacy `/commit` with no
   batch atomically freezes the current conflict-free active proposals before confirm. Mixed
   canonical/alias retries and races share action receipts and can create at most one Task per
   action. Mark aliases deprecated, exclude them from mobile generation, migrate web, and
   remove them only after no deployed client or active stored operation depends on them.
5. Generate/pin the v1 contract and mobile operation allowlist, then build mobile session and
   read-only Task projections.
6. Add idempotent Task actions, then the bounded canonical voice operation.
7. Release internal builds only after both platform gates pass.

Rollback can remove or disable the mobile session endpoint and stop distributing native
builds. Existing browser cookies, users, Tasks, and operations remain valid. Revoking all
mobile credentials requires deleting server session records issued during the mobile
window; because records do not currently distinguish transport, a global session reset
would also sign browser sessions out. If selective emergency revocation becomes an
operational requirement before release, add a backward-compatible `channel` field with
legacy default `browser` and issue mobile sessions as `mobile`; this is not needed for core
authorization.

Mobile rollback deletes local session/recovery state and installs the prior internal build.
Completed canonical Tasks are never removed automatically. Unconfirmed local audio and
remote draft operations follow explicit discard/retention cleanup; rollback must not commit
them.

## Verification / tests

Conformance requires:

1. backend tests for mobile session creation, no cookie, no-cache headers, generic auth
   failure/rate limit, cookie-or-Bearer resolution, ambiguity rejection, expiry, revocation,
   wrong owner, error envelopes, correlation IDs, and unchanged browser behavior;
2. OpenAPI semantic-version and generated-snapshot drift checks;
3. mobile tests proving SecureStore-only token handling, first-install cleanup, 401 clearing,
   logout clearing, no secret in state/log/error serialization, and owner-cache separation;
4. Task list/detail/pagination/create/complete/reopen parity against the existing API and web
   client, including stale revisions and idempotent retries;
5. device/simulator tests for permission denial, audio-route interruption, durable document
   recording, low storage, process kill, resumable chunk upload, hash conflict, seal,
   processing retry, provider-category/policy change, consent expiry/withdrawal, proposal
   edits/removal, frozen-batch invalidation, canonical confirmation timeout, retained-until,
   raw-audio delete-now, and exact-once Tasks;
6. backend migration/overlap tests proving legacy payload defaults, alias delegation,
   canonical/alias races, process restart, immutable completed operations, and deterministic
   `H(operation_id,batch_id,action_id)` action receipts;
7. a privacy scan of logs, Allure, screenshots, crash artifacts, bundles, source maps, and
   build output for credentials, emails, audio/transcript/task content, paths, and hashes;
8. `expo-doctor`, lint, typecheck, unit/component suites, deterministic native config
   generation, Android and iOS internal builds, and one real-device smoke per platform;
9. an inventory proving every enabled control maps to an accepted command/client action and
   every deferred design affordance is absent or explicitly non-interactive.

## Related files

- `specs/004-expo-mobile-first-slice/spec.md`
- `specs/004-expo-mobile-first-slice/plan.md`
- `specs/004-expo-mobile-first-slice/contracts/mobile-api.md`
- `docs/auth.md`
- `docs/api-compatibility.md`
- `backend/app/api/auth.py`
- `backend/app/api/dependencies.py`
- `backend/app/services/auth_service.py`
- `backend/app/schemas/auth.py`
- `backend/app/api/tasks.py`
- `.claude/skills/brain-buddy-design/README.md`
