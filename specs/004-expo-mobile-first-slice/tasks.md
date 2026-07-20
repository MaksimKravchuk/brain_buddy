# Tasks: Expo mobile first slice

**Input**: `spec.md`, `plan.md`, `research.md`, `data-model.md`, `quickstart.md`,
`contracts/mobile-api.md`, ADR-0008, and the two requirements checklists in this directory

**Tests**: Required and failing-first for every behavior slice. Every pytest, mobile Jest,
and black-box product test emits non-empty Allure epic/feature/story/title plus a named step.

**Execution**: Hermes Kanban owns implementation/review. This file is planning input only;
do not run `/speckit-implement`, merge, deploy, publish, or handle production signing from
these tasks.

## Phase 1: Mobile package and deterministic tooling setup

**Purpose**: Create the single `mobile/` boundary and quality spine without product behavior.

- [ ] T001 Scaffold one Expo SDK 57 TypeScript/Expo Router app in `mobile/package.json`, `mobile/package-lock.json`, `mobile/app/`, and `mobile/tsconfig.json` without adding a root npm workspace or Expo web replacement.
- [ ] T002 Configure public bundle/package IDs, foreground microphone permission, SecureStore plugin, CNG, and public environment values in `mobile/app.config.ts`; keep background recording and secrets disabled.
- [ ] T003 Define development, preview/internal, and non-automatic production profiles in `mobile/eas.json` with no credential material or auto-submit.
- [ ] T004 [P] Configure strict TypeScript, ESLint, formatting, Jest via `jest-expo`, React Native Testing Library, and test scripts in `mobile/tsconfig.json`, `mobile/eslint.config.js`, `mobile/jest.config.js`, and `mobile/package.json`.
- [ ] T005 [P] Add the central mobile Allure adapter/taxonomy helper and a self-test in `mobile/src/test/allureTaxonomy.ts` and `mobile/__tests__/test/allureTaxonomy.test.ts`.
- [ ] T006 [P] Add generated-native/build/EAS/local-audio/credential exclusions to `.gitignore` and a deterministic assertion in `scripts/test_mobile_gitignore.py`.
- [ ] T007 [P] Add mobile install, doctor, lint, typecheck, unit, integration, E2E, API-drift, privacy-scan, and prebuild targets to `Makefile` without changing existing backend/frontend targets.
- [ ] T008 Add PR CI mobile static jobs in `.github/workflows/ci.yml` that run without production signing, store submission, real accounts, or real audio.

**Checkpoint**: `mobile/` installs deterministically and emits an empty but valid Allure test
run; no native directories, secrets, or product behavior exist.

---

## Phase 2: Contract/version and platform-neutral foundations

**Purpose**: Fix the second-client compatibility source and pure local primitives before any
user journey.

- [ ] T009 [P] Add failing backend tests for API semantic version versus storage schema version in `backend/tests/test_api_contract.py` and `backend/tests/test_config.py`.
- [ ] T010 Add `ApiSettings.semantic_version="1.0.0"` in `backend/app/core/config.py`, use it for FastAPI `info.version` in `backend/app/main.py`, and keep `/health.schema_version` unchanged.
- [ ] T011 [P] Add failing tests proving OpenAPI generation uses an ephemeral test app/data root and contains no persisted/user data in `scripts/test_generate_openapi.py`.
- [ ] T012 Implement deterministic OpenAPI v1 generation in `scripts/generate_openapi.py` and commit the generated contract at `openapi/brainbuddy-v1.json`.
- [ ] T013 [P] Configure `openapi-typescript`/`openapi-fetch` generation and drift scripts in `mobile/package.json` and `mobile/scripts/generate-api.mjs`.
- [ ] T014 Generate transport-only DTOs/operations into `mobile/src/api/generated/` and add a drift assertion that never reads production or persisted JSON.
- [ ] T015 [P] Add failing redaction/credential-header/correlation/error-mapping tests for the handwritten transport in `mobile/__tests__/api/client.test.ts`.
- [ ] T016 Implement the generated-client wrapper and redacted `MobileApiError` in `mobile/src/api/client.ts`, with injected credential provider and no body/content telemetry.
- [ ] T017 [P] Add failing atomic-write, replace, corrupt-file quarantine, and no-content-log tests in `mobile/__tests__/storage/atomicJson.test.ts`.
- [ ] T018 Implement atomic local JSON persistence in `mobile/src/storage/atomicJson.ts` without importing auth, API, navigation, or domain modules.
- [ ] T019 [P] Add design-token/adherence tests for brand colors, Inter type, Lucide-only icons, 44-point targets, reduced motion, and authority copy in `mobile/src/design/contract.test.ts`.
- [ ] T020 Implement native design tokens/helpers in `mobile/src/design/tokens.ts` and `mobile/src/design/accessibility.ts` by mirroring the authoritative design skill rather than importing browser CSS.

**Checkpoint**: API/storage version ownership, pinned OpenAPI generation, generated transport,
redacted client foundation, atomic local storage, and design contracts are green.

---

## Phase 3: User Story 1 — Secure mobile session (Priority: P1)

**Goal**: Existing-account sign-in, restart restore, expiry/revocation handling, and logout use
the existing server-owned opaque Session with SecureStore-only client persistence.

**Independent Test**: Clean install → sign in → restart → `/me`/Tasks → sign out → old Bearer
credential is rejected; no credential appears in artifacts.

### Tests for User Story 1

- [ ] T021 [P] [US1] Add failing mobile-session route tests for 201/no-cookie/no-store/expiry, generic 401, 422, 429, and persistence 503 in `backend/tests/test_mobile_session_api.py`.
- [ ] T022 [P] [US1] Add failing cookie-or-Bearer parity, malformed header, dual-source ambiguity, expiry, logout revocation, and wrong-owner tests in `backend/tests/test_mobile_session_api.py` and `backend/tests/test_auth_routes.py`.
- [ ] T023 [P] [US1] Add failing OpenAPI/error-envelope/Schemathesis expectations for the new auth operation and Bearer mode in `backend/tests/test_api_contract.py` and `backend/tests/test_schemathesis_contract.py`.
- [ ] T024 [P] [US1] Add failing SecureStore save/read/delete/error/redaction tests in `mobile/__tests__/auth/secureSession.test.ts`.
- [ ] T025 [P] [US1] Add failing first-install marker, iOS residual credential cleanup, corrupt marker, and owner-recovery cleanup tests in `mobile/__tests__/auth/installMarker.test.ts`.
- [ ] T026 [P] [US1] Add failing auth bootstrap/sign-in/restart/401 quarantine/same-owner recovery/network/logout-discard/account-switch state tests in `mobile/__tests__/auth/AuthProvider.test.tsx`.
- [ ] T027 [P] [US1] Add failing sign-in screen accessibility, generic error, rate-limit, correlation, loading, and retry tests in `mobile/__tests__/auth/SignInScreen.test.tsx`.

### Implementation for User Story 1

- [ ] T028 [US1] Add strict `SessionCredentialResponse` to `backend/app/schemas/auth.py` without adding JWT, refresh, scope, device-owner, or provider fields.
- [ ] T029 [US1] Refactor verified login in `backend/app/services/auth_service.py` to expose the created `Session` expiry once while preserving existing browser `login()` behavior and digest-only persistence.
- [ ] T030 [US1] Implement one cookie/Bearer credential parser and owner resolver in `backend/app/api/dependencies.py` (or narrowly extracted `backend/app/api/session_auth.py`) with ambiguity/malformed rules from the contract.
- [ ] T031 [US1] Implement `POST /api/auth/mobile/sessions` and header-aware idempotent logout in `backend/app/api/auth.py`, including no-store/no-cookie headers and existing rate limiting.
- [ ] T032 [US1] Update `docs/auth.md` and `docs/api-compatibility.md` for opaque mobile transport, SecureStore threat model, API v1 window, and browser regression guarantees.
- [ ] T033 [US1] Regenerate `openapi/brainbuddy-v1.json` and `mobile/src/api/generated/`, then prove T021–T023 and drift tests pass.
- [ ] T034 [US1] Implement app-specific this-device-only SecureStore access in `mobile/src/auth/secureSession.ts` with token-redacted errors and no biometric requirement.
- [ ] T035 [US1] Implement first-install marker and residual credential/recovery cleanup in `mobile/src/auth/installMarker.ts`.
- [ ] T036 [US1] Implement session calls and the narrow API credential provider in `mobile/src/api/auth.ts` without exposing raw token to UI stores.
- [ ] T037 [US1] Implement auth bootstrap, owner-scoped QueryClient lifecycle, 401 recovery quarantine, same-owner restore, explicit logout discard, and unresolved remote revocation state in `mobile/src/auth/AuthProvider.tsx`.
- [ ] T038 [US1] Implement authenticated and signed-out route guards in `mobile/app/_layout.tsx`, `mobile/app/(auth)/_layout.tsx`, and `mobile/app/(app)/_layout.tsx`.
- [ ] T039 [US1] Implement the existing-account sign-in UI in `mobile/app/(auth)/sign-in.tsx` with calm product copy, no signup promise, accessible errors, and correlation reference.
- [ ] T040 [US1] Add deterministic black-box clean-install/restore/logout flow in `mobile/e2e/maestro/auth-and-tasks.yaml` using a synthetic test account and redacted evidence.

**Checkpoint**: User Story 1 is independently usable and all browser cookie behavior remains
green.

---

## Phase 4: User Story 2 — Canonical GTD workspace (Priority: P1)

**Goal**: Mobile renders canonical four-list/Project/Tag projections, bounded detail, plain
Inbox capture, completion, and explicit reopen without becoming a second task store.

**Independent Test**: Mobile plain capture → Inbox → complete → explicit reopen → restart →
web parity, including a list with more than 50 rows.

### Tests for User Story 2

- [ ] T041 [P] [US2] Add failing generated-adapter tests for task/project/tag list/detail/create/transition payloads, filters, cursor, revision, idempotency, and 401/404/409 mapping in `mobile/__tests__/api/tasks.test.ts`.
- [ ] T042 [P] [US2] Add failing infinite-query/count/cache-isolation and post-mutation invalidation tests in `mobile/__tests__/tasks/taskHooks.test.tsx`.
- [ ] T043 [P] [US2] Add failing drawer tests for exactly four open states, Projects, Tags, Brain Dump, and non-interactive Weekly Review with no search/CRT/Execution controls in `mobile/__tests__/tasks/TaskDrawer.test.tsx`.
- [ ] T044 [P] [US2] Add failing list/loading/empty/offline/error/retry/continuation/metadata/completion tests in `mobile/__tests__/tasks/TaskListScreen.test.tsx`.
- [ ] T045 [P] [US2] Add failing plain Inbox creator tests proving literal Smart Add sigils, stable idempotency key on retry, draft preservation, and no inferred metadata in `mobile/__tests__/tasks/TaskCreator.test.tsx`.
- [ ] T046 [P] [US2] Add failing bounded-detail tests for canonical field display, valid lifecycle actions, explicit reopen destination, Waiting input, stale refresh, and absence of metadata edit/Subtask/Comment/Execution/Think controls in `mobile/__tests__/tasks/TaskDetailScreen.test.tsx`.
- [ ] T047 [P] [US2] Add a failing temporary-backend integration test with >50 tasks, Project/Tag filters, wrong owner, timeout replay, restart, and web parity in `mobile/__tests__/integration/tasks.integration.test.ts`.

### Implementation for User Story 2

- [ ] T048 [US2] Implement generated Task/Project/Tag adapters with normalized filter/cursor handling in `mobile/src/api/tasks.ts`.
- [ ] T049 [US2] Implement owner-generation-scoped infinite queries, count handling, and success-only mutation invalidation in `mobile/src/features/tasks/taskHooks.ts`.
- [ ] T050 [US2] Implement `TaskDrawer` in `mobile/src/features/tasks/TaskDrawer.tsx` using the accepted four-state order, current Tag terminology, 44-point targets, and truthful deferred labels.
- [ ] T051 [US2] Implement reusable paginated list/project/tag projections in `mobile/src/features/tasks/TaskListScreen.tsx` and routes under `mobile/app/(app)/tasks/`, `projects/`, and `tags/`.
- [ ] T052 [US2] Implement literal plain Inbox capture in `mobile/src/features/tasks/TaskCreator.tsx`; route only to existing `POST /tasks`, never Smart Add.
- [ ] T053 [US2] Implement bounded detail and lifecycle actions in `mobile/src/features/tasks/TaskDetailScreen.tsx` and `mobile/app/(app)/tasks/detail/[taskId].tsx` without unsupported controls.
- [ ] T054 [US2] Add terminal-history entry/reopen selection without adding Completed/Cancelled to the four primary list items in `mobile/src/features/tasks/TaskDrawer.tsx` and `TaskDetailScreen.tsx`.
- [ ] T055 [US2] Complete the deterministic Maestro task journey in `mobile/e2e/maestro/auth-and-tasks.yaml`, including continuation, capture, complete, reopen, restart, and Project/Tag projections.

**Checkpoint**: User Story 2 delivers a truthful canonical GTD client and remains independently
testable with voice disabled.

---

## Phase 5: User Story 3 — Foreground Voice Brain Dump (Priority: P1)

**Goal**: Durable foreground recording, post-stop resumable upload, persisted processing,
proposal review, and exact-once confirmation survive mobile interruptions without creating a
Task early.

**Independent Test**: Deterministic device audio → interrupt at each local/server checkpoint →
resume → edit/remove → confirm → exact selected title-only Inbox Tasks after timeout replay.

### Tests for User Story 3

- [ ] T056 [P] [US3] Add failing AudioRecorderPort contract tests for permission, document-directory recording, pause/stop, duration, URI, audio-route interruption, and no background claim in `mobile/__tests__/brainDump/AudioRecorderPort.test.ts`.
- [ ] T057 [P] [US3] Add failing atomic recovery-manifest tests for every local state, owner binding, offline start-key replay, persisted-before-send keys, corrupt/401 quarantine, explicit logout discard, and no transcript/proposal/task content in `mobile/__tests__/brainDump/recoveryManifest.test.ts`.
- [ ] T058 [P] [US3] Add failing chunk-boundary/hash/manifest/ack replay/conflict/missing-chunk/off-UI-thread tests in `mobile/__tests__/brainDump/chunkUploader.test.ts`.
- [ ] T059 [P] [US3] Add failing generated operation adapter tests for start/get/upload/seal/pause/resume/cancel/retry/edit/remove/commit with revisions, keys, correlation, and redaction in `mobile/__tests__/api/brainDump.test.ts`.
- [ ] T060 [P] [US3] Add failing reducer tests for every backend Brain Dump status, projection replacement, retry/cancel/partial-result behavior, and unknown-enum rejection in `mobile/__tests__/brainDump/operationReducer.test.ts`.
- [ ] T061 [P] [US3] Add failing recording-screen tests for permission versus consent, local-only copy, waveform/duration, interruption salvage, Stop & review, reduced motion, and no fake live proposals in `mobile/__tests__/brainDump/RecordingScreen.test.tsx`.
- [ ] T062 [P] [US3] Add failing upload/processing-screen tests for acknowledged progress, truthful stage text, no fake percentage, polling/reconnect, retry/cancel, and correlation in `mobile/__tests__/brainDump/ProcessingScreen.test.tsx`.
- [ ] T063 [P] [US3] Add failing review-screen tests for reconciled/provisional/conflicted states, edit/remove persistence, conflict gate, discard, `Confirm N additions`, no Add date/inference, and timeout replay in `mobile/__tests__/brainDump/ReviewScreen.test.tsx`.
- [ ] T064 [P] [US3] Add failing temporary-backend checkpoint integration tests for recorded/upload/sealed/processing/review/commit timeout, chunk conflict, provider exhaustion, cancellation, partial commit, and exact-one Tasks in `mobile/__tests__/integration/brainDump.integration.test.ts`.
- [ ] T065 [P] [US3] Add backend regression assertions for mobile Bearer access to every consumed Brain Dump route and unchanged owner/idempotency/confirmation behavior in `backend/tests/test_mobile_brain_dump_api.py`.

### Implementation for User Story 3

- [ ] T066 [US3] Define the platform-neutral recorder interface and deterministic fixture fake in `mobile/src/features/brainDump/AudioRecorderPort.ts` and `mobile/src/features/brainDump/FakeAudioRecorder.ts`.
- [ ] T067 [US3] Implement foreground `expo-audio` document-directory recording and interruption signals in `mobile/src/features/brainDump/ExpoAudioRecorder.ts`; keep background recording disabled.
- [ ] T068 [US3] Implement the versioned one-active-operation local manifest and cleanup/quarantine rules in `mobile/src/features/brainDump/recoveryManifest.ts`.
- [ ] T069 [US3] Inspect backend/config limits, then implement bounded file chunking, SHA-256 identity, resume, conflict stop, and complete-manifest seal prerequisites in `mobile/src/features/brainDump/chunkUploader.ts`.
- [ ] T070 [US3] Implement generated operation calls and command-key ownership in `mobile/src/api/brainDump.ts`.
- [ ] T071 [US3] Implement strict server-projection state reduction and unknown-state failure in `mobile/src/features/brainDump/operationReducer.ts`.
- [ ] T072 [US3] Implement foreground recording and salvage UI in `mobile/src/features/brainDump/RecordingScreen.tsx` and `mobile/app/(app)/brain-dump/new.tsx`.
- [ ] T073 [US3] Implement post-stop upload/seal/poll/retry/cancel UI in `mobile/src/features/brainDump/ProcessingScreen.tsx` and `mobile/app/(app)/brain-dump/[operationId]/index.tsx`.
- [ ] T074 [US3] Implement proposal edit/remove/conflict/confirm/discard UI in `mobile/src/features/brainDump/ReviewScreen.tsx` and `mobile/app/(app)/brain-dump/[operationId]/review.tsx`.
- [ ] T075 [US3] Implement app-start/focus/network reconciliation between SecureStore owner state, recovery manifest, and owner-scoped operation GET in `mobile/src/features/brainDump/recoverOperation.ts` and `mobile/src/auth/AuthProvider.tsx`.
- [ ] T076 [US3] Complete deterministic Maestro Voice Brain Dump flow in `mobile/e2e/maestro/brain-dump.yaml` with fixture injection and privacy-safe evidence.

**Checkpoint**: User Story 3 proves the bounded mobile-first capture/review/confirm value loop;
no task exists before confirmation and every retry is exact-once.

---

## Phase 6: Cross-cutting resilience, builds, and release evidence

**Purpose**: Prove both-platform safety and prevent planning/design claims from exceeding the
implemented bounded slice.

- [ ] T077 [P] Add deterministic canary privacy-scan tests covering token/password/email/audio/transcript/task/path/hash leakage in `scripts/test_scan_mobile_evidence.py`.
- [ ] T078 Implement source/log/Allure/screenshot/bundle/source-map/generated-native/build-output scanning in `scripts/scan_mobile_evidence.py` and wire `make scan-mobile-evidence`.
- [ ] T079 [P] Add a control-inventory test mapping every enabled mobile control to the M-01..M-09 classification and accepted command in `mobile/__tests__/design/controlInventory.test.tsx`.
- [ ] T080 [P] Add native config-generation assertions for microphone permission, background-recording absence, SecureStore backup exclusion, export compliance, identifiers, and no secrets in `mobile/__tests__/config/appConfig.test.ts`.
- [ ] T081 Run `npx expo prebuild --clean --no-install` and `expo-doctor`; inspect deterministic generated iOS/Android configuration without committing native directories.
- [ ] T082 Run focused backend auth/contract/Schemathesis suites and full `make test-backend`; record exact pass/fail counts without attaching secrets/content.
- [ ] T083 Run mobile lint/typecheck/Jest/Allure/API-drift/integration/privacy gates and existing `make test-frontend`; fix only in-scope regressions.
- [ ] T084 Build and exercise an Android development/internal build on emulator and one real device; record redacted SecureStore/microphone/interruption/network-resume evidence in `specs/004-expo-mobile-first-slice/evidence/android-device.md`.
- [ ] T085 Build and exercise an iOS development/internal build on simulator and one real device; record redacted Keychain/reinstall/microphone/interruption/network-resume evidence in `specs/004-expo-mobile-first-slice/evidence/ios-device.md`.
- [ ] T086 Verify preview EAS builds use least-privilege project access and no production auto-submit; record only build IDs/URLs in `specs/004-expo-mobile-first-slice/evidence/eas-preview.md` through the normal PR evidence channel.
- [ ] T087 Update `docs/e2e-acceptance-charter.md` with native session/task/voice journeys, deterministic fixtures, device matrix, Allure evidence, and privacy constraints.
- [ ] T088 Update `.env.example` and `docs/mobile-development.md` with public API-origin/profile values only; do not add provider, session, EAS, signing, or store secrets.
- [ ] T089 Run `python3 scripts/check_spec_kit_specs.py`, Spec Kit unit checks, Markdown/link scans, and exact task-format validation for `specs/004-expo-mobile-first-slice/`.
- [ ] T090 Inspect final changed-file scope against ADR-0008, record review evidence in `specs/004-expo-mobile-first-slice/checklists/mobile-boundaries.md`, request independent architecture/security and QA reviews, then deliver through PR → CI without store submission or deploy authority.

## Dependencies and execution order

### Phase dependencies

- Phase 1 has no product dependency.
- Phase 2 depends on the mobile package/test spine from Phase 1 and blocks all stories.
- US1 depends on Phase 2 and blocks authenticated US2/US3 device integration.
- US2 and US3 can proceed in parallel after US1 plus generated-client foundation; their
  feature files are separate.
- Phase 6 depends on all selected user stories and is the release-review gate.

### User story dependencies

- **US1**: independent after foundation; yields a useful authenticated shell/session proof.
- **US2**: uses US1 authentication but no Voice code; independently validates canonical Tasks.
- **US3**: uses US1 authentication and existing backend Tasks commit port; it does not depend
  on US2 UI and remains independently testable with API fixtures.

### Parallel opportunities

- Backend T021–T023 and mobile T024–T027 can run in parallel after Phase 2.
- US2 tests/implementation and US3 tests/implementation can be separate Kanban workstreams
  after US1 contract lands.
- Pure recorder, manifest, uploader, reducer, and screen tests are parallel until their
  integration tasks.
- Privacy, control inventory, and config assertions can begin before both device builds.
- Android and iOS build/device evidence can run in parallel after the shared CNG build is
  reproducible.

## Suggested Kanban handoff slices

1. **Backend/API coder**: T009–T014 and T021–T033; independent security/API review required.
2. **Mobile foundation/auth coder**: T001–T008, T015–T020, T024–T027, T034–T040.
3. **Mobile Tasks coder**: T041–T055 after US1 contract.
4. **Mobile Voice coder**: T056–T076 after US1 contract; native escape is not authorized.
5. **QA**: T077–T090 plus independent verification of each story checkpoint.

Do not turn these suggestions into overlapping shared-worktree cards. Each implementation
card must name this spec/plan/ADR, use an isolated worktree, preserve failing-first evidence,
and block for review before merge.

## Implementation strategy

### Smallest MVP checkpoint

1. Complete Phases 1–2.
2. Complete US1.
3. Complete the read-only subset of US2: Next/Inbox/drawer/pagination/detail.
4. Stop and validate internal Android/iOS builds before adding mutations or voice.

### Product first slice

1. Add US2 task capture/complete/reopen and prove web parity.
2. Add US3 bounded foreground recording through exact-once confirmation.
3. Complete Phase 6 evidence.
4. Release only to approved internal testers; production store release is a separate decision.

## Implementation guardrails

- Do not add JWT, refresh tokens, OAuth, mobile owner IDs, or Session claims.
- Do not persist token/password in AsyncStorage, Zustand, FileSystem, logs, snapshots, or
  evidence.
- Do not add a mobile BFF, root JS workspace, shared domain/UI package, or Expo web rewrite.
- Do not parse Smart Add or infer Task metadata in mobile/manual/voice capture.
- Do not show live transcript/proposals while speaking unless the spec/ADR is amended after a
  native capability spike.
- Do not enable background recording or commit generated native projects.
- Do not expose Weekly Review, CRT/Think, Execution, Subtask, Comment, Project/Tag management,
  Add date, search/date/sort, notification, or general offline-sync controls.
- Do not refresh screenshots/baselines to hide unrelated drift.
- Do not run EAS production build/submit, store publication, OTA rollout, Fly deploy, or
  credential operations from implementation cards.
