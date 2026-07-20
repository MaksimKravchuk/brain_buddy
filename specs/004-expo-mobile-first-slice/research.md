# Research: Expo mobile first slice

**Feature**: `004-expo-mobile-first-slice`
**Date**: 2026-07-20
**Status**: Complete — no `NEEDS CLARIFICATION` items remain

## Decision 1: One Expo application, not a universal rewrite

**Decision**: Add one independently built Expo/React Native application under `mobile/` for
iOS and Android. Keep `frontend/` as the Vite web client and `backend/` as the single FastAPI
modular monolith.

**Rationale**: The repository already has working task, operation, auth, deployment, and web
behavior. A native app needs device lifecycle, secure storage, audio, and native navigation,
not a second domain or a rewrite of browser presentation.

**Alternatives considered**:

- Universal Expo web/native app: rejected because it replaces a working Vite shell and
  forces DOM/native abstractions before reuse is proven.
- Separate iOS and Android apps: rejected because product/API semantics must not fork.
- Mobile backend-for-frontend: rejected because existing APIs already expose the required
  owner-scoped contracts and a BFF creates a parallel control plane.

## Decision 2: Reuse opaque server sessions through an additive mobile transport

**Decision**: Add `POST /api/auth/mobile/sessions` returning the existing raw opaque Session
credential once in a non-cacheable response. Store it only in Expo SecureStore and send it
as `Authorization: Bearer OPAQUE_SESSION_TOKEN`. Protected routes accept either the existing
cookie or
the header, never both. No refresh token or JWT is added.

**Rationale**: `AuthService` already generates high-entropy tokens, persists only SHA-256
digests, expires them, and revokes immediately. The browser retains its HTTP-only cookie;
mobile gains an application-controlled secure-storage boundary without changing owner
resolution.

**Alternatives considered**:

- Native cookie jar: rejected because it is not the accepted same-origin browser boundary
  and gives the app less explicit control over storage/recovery tests.
- JWT access/refresh tokens: rejected because they add claims, signing/rotation, refresh
  families, and dual identity semantics without product value.
- Persist password and recreate sessions: rejected because passwords must never be stored.

## Decision 3: SecureStore plus first-install cleanup

**Decision**: Store only the opaque session token in `expo-secure-store`, with an app-specific
service and this-device-only iOS accessibility. Keep query caches in memory. Use a non-secret
FileSystem install marker to delete residual Keychain state after reinstall.

**Rationale**: Expo documents SecureStore as Android Keystore-encrypted SharedPreferences
and iOS Keychain storage. It also documents that iOS Keychain entries can survive uninstall;
first-install cleanup prevents surprising automatic sign-in after reinstall. SecureStore is
not used for recordings or large payloads.

**Alternatives considered**:

- AsyncStorage/Zustand persistence: rejected for bearer credentials.
- Biometric-required reads: deferred; it complicates background/lifecycle access and can
  invalidate credentials after biometric changes. It is not sign-in identity.
- Rely on uninstall clearing secrets: rejected because iOS explicitly does not guarantee it.

**Source**: Expo SecureStore documentation,
`https://docs.expo.dev/versions/latest/sdk/securestore` (accessed 2026-07-20).

## Decision 4: Expo SDK 57, development builds, and CNG

**Decision**: Pin Expo SDK 57 and compatible package versions in `mobile/package-lock.json`.
Use Expo development builds and Continuous Native Generation. Do not check in `ios/` or
`android/` initially.

**Rationale**: Expo's current documentation identifies SDK 57 as latest and recommends
development builds for production applications. CNG regenerates native projects from
app/config-plugin inputs and reduces two-platform drift. Expo Go is insufficient release
evidence for SecureStore/device audio behavior.

**Alternatives considered**:

- Bare React Native from day one: rejected; no current requirement needs canonical native
  projects.
- Expo Go as the test/release target: rejected because native configuration and real-device
  security/lifecycle must be exercised in development/internal builds.

**Sources**:

- `https://docs.expo.dev/workflow/upgrading-expo-sdk-walkthrough`
- `https://docs.expo.dev/build/introduction`

(accessed 2026-07-20).

## Decision 5: Foreground durable recording, then resumable chunk upload

**Decision**: Use `expo-audio` foreground recording with the document directory, not cache.
After Stop, read/split the completed file into bounded numbered chunks, hash and upload them
idempotently, then seal the complete manifest. Persist a minimal local recovery manifest.
Do not promise live transcript/proposals while speaking in this first mobile slice.

**Rationale**: Expo Audio documents that recordings otherwise default to cache and can be
stored in the document directory. Its supported recording contract yields the completed URI;
it does not establish safe encoded chunks during an active recording. The bounded path
still exercises local durability, interruption recovery, upload, processing, review, and
explicit confirmation. This is a scoped capture-timing refinement/fallback only: ADR-0002
continues to govern the shared backend and long-term live-proposal primary UX.

**Alternatives considered**:

- One unchunked multipart upload: rejected because it discards existing idempotent
  chunk/manifest/recovery semantics.
- Stop/restart the recorder periodically: rejected because it risks gaps and changes audio
  semantics.
- Custom native streaming recorder immediately: rejected until live extraction is a tested
  first-slice requirement; it remains the explicit escape hatch.
- Background recording: deferred because it changes permissions, battery, lifecycle, and
  platform evidence requirements.

**Source**: Expo Audio documentation,
`https://docs.expo.dev/versions/latest/sdk/audio` (accessed 2026-07-20).

## Decision 6: Generate transport types; do not create a shared domain package

**Decision**: Separate API semantic version from storage schema version, commit a pinned
OpenAPI v1 snapshot, and generate mobile DTOs/client signatures into
`mobile/src/api/generated/`. Keep mobile view models and adapters local. Do not add a root
workspace or `packages/` runtime layer in this slice.

**Rationale**: Pydantic/OpenAPI is already the contract source. A handwritten shared
TypeScript model would duplicate domain authority, while React DOM and React Native UI,
navigation, storage, and lifecycle are not safely shareable. Pure code can be extracted
later after two real consumers exist.

**Alternatives considered**:

- Copy web `taskTypes.ts`: rejected because it already demonstrates additive optional-field
  drift from backend schemas.
- Handwritten `packages/domain`: rejected as a second source of truth.
- Migrate the web client to generated types in this feature: deferred to avoid coupling the
  mobile slice to a broad web refactor.

## Decision 7: Bounded screen classification

**Decision**:

- Build M-01, M-02, M-03, and M-06.
- Bounded-build M-04 (read + lifecycle only), M-05 (foreground recording and post-stop
  upload, no live proposals), M-07 (read-only Project projection), and M-08 (read-only Tag
  projection using current terminology).
- Keep M-09 Weekly Review deferred and visibly non-interactive.

**Rationale**: This is the smallest coherent task-and-voice client. It preserves truthful
controls and explicit confirmation while excluding speculative Execution, CRT/Think,
Subtasks, Comments, inferred metadata, and unsupported live behavior.

**Alternatives considered**:

- Implement every static affordance: rejected because several are explicitly deferred by
  ADR-0006 or speculative design.
- Voice-only app: rejected because canonical Tasks must remain inspectable and manageable.
- Task-only app: rejected because it misses the mobile-first product loop.

## Decision 8: EAS internal builds with human-owned production signing

**Decision**: Use EAS development and preview/internal profiles for build evidence. PR CI
runs deterministic checks and non-production builds. Production signing credentials and
store submission remain with the app-store account owner and require a separate release
approval. No signing material is committed or printed.

**Rationale**: EAS supports managed or supplied credentials and internal distribution, but
build convenience does not grant release authority. This keeps repository automation,
EAS access, signing ownership, and store publication as distinct boundaries.

**Alternatives considered**:

- Automatic store submission on merge: rejected until production rollout and rollback are
  separately authorized.
- Commit `credentials.json` or keystores: rejected; credentials remain outside source.
- Local-only builds: retained as a debugging fallback, not the shared acceptance artifact.

**Sources**:

- `https://docs.expo.dev/build/introduction`
- `https://docs.expo.dev/app-signing/existing-credentials`

(accessed 2026-07-20).

## Decision 9: Close canonical confirmation, consent, and retention gaps before mobile Voice

**Decision**: Implement and consume ADR-0002's canonical append-only proposal patches,
persisted frozen `ProposalBatch`, invalidation, and `/confirm` command before generating the
mobile Voice adapter. Derive every action key as `H(operation_id,batch_id,action_id)`. Keep
direct proposal `PATCH` and `/commit` only as deprecated web-overlap adapters to the same
service/records, excluded from the mobile generation allowlist.

Each frozen action is a complete immutable review snapshot: target, before/after summaries,
source cue, confidence/warnings, and destination. It never stores result status or Task ID.
Execution writes append-only immutable receipts, and the API folds them into a separate batch
and per-action result projection. Active v1 operations import once as `legacy_preview_only`
with IDs, title locks, and remove tombstones preserved through deterministic synthetic patches.
With no original audio they remain visibly `provisional_only`, cannot claim accurate
reconciliation, and require explicit provisional review before separate freeze/confirmation.

Expose a non-secret processing policy. Persist consent policy version, allowed provider
categories, decision time, server expiry/withdrawal state, and revalidate on restart or
configuration change; withdrawal stops future work and schedules uncommitted cleanup. Expose
raw-audio deletion state and `retained_until`, plus an idempotent delete-now command after
processing.

**Rationale**: A frozen immutable batch is the authority boundary that makes user review and
deterministic child idempotency true after edits, partial failure, restart, or old/new-client
overlap. Keeping outcomes in receipts prevents execution from rewriting what the user
reviewed. Marking legacy previews explicitly prevents synthesized lineage from being mistaken
for accurate reconciliation while still allowing deliberate salvage. A local boolean cannot
prove current consent after restart or provider change. Hidden
retention cannot support ADR-0002's user deletion guarantee.

**Alternatives considered**:

- Store `result_status`/`result_task_id` on each frozen action: rejected because partial
  execution would rewrite the exact evidence the user confirmed. Append-only receipts provide
  recovery and results without mutating review authority.
- Treat deterministic v1 synthetic patches as reconciled output: rejected because v1 retained
  no original audio against which accurate transcription or reconciliation can be proven.
- Pin direct `PATCH` and `/commit` into OpenAPI v1: rejected because transitional aliases
  would become a released mobile contract and could not be removed safely.
- Treat consent as valid forever until local deletion: rejected because it is neither
  time-bounded nor bound to current processing categories and cannot represent withdrawal.
- Delete local audio and imply server deletion: rejected because local and server retention
  are separate authorities; pending remote cleanup must remain visible.

## Native escape criteria

A Swift/Kotlin/Expo Module escape is allowed only after a reproducible managed-workflow spike
proves a required capability gap, a narrow TypeScript interface and fake exist, both
platforms have parity or an accepted exception, native/device tests and rollback are
specified, and ADR-0008 is amended if native directories/build ownership become canonical.
Likely triggers are continuous encoded-audio chunks while recording, robust background
recording, or a security primitive unavailable through supported modules/config plugins.
