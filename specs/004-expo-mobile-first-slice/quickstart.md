# Quickstart validation: Expo mobile first slice

**Feature**: `004-expo-mobile-first-slice`
**Purpose**: Runnable validation guide for implementation and review. It does not authorize
`/speckit-implement`, production signing, store submission, or deployment.

## Prerequisites

- Python 3.11 and `uv` for the backend.
- Node/npm versions accepted by Expo SDK 57 and the repository.
- Android emulator plus one Android device for SecureStore/microphone evidence.
- macOS/Xcode iOS simulator plus one iOS device for Keychain/microphone evidence.
- An invite-created or seeded non-production test account.
- A configured deterministic/fake voice provider for automated runs. Never use real user
  audio or credentials in fixtures, Allure, screenshots, logs, or source control.
- EAS project access only for preview/internal build steps. Production credentials are not a
  prerequisite for feature development.

## 1. Validate planning and contract artifacts

From repository root:

```bash
python3 scripts/check_spec_kit_specs.py
python3 -m unittest scripts/test_check_spec_kit_specs.py -v
```

Expected:

- Spec Kit artifact check passes.
- `specs/004-expo-mobile-first-slice/` includes spec, plan, research, data model,
  requirements/mobile-boundary checklists, mobile API contract, quickstart, and tasks.
- No generated implementation has run through Spec Kit.

## 2. Backend mobile-session contract

After implementation:

```bash
cd backend
uv run pytest tests/test_mobile_session_api.py -q
uv run pytest tests/test_auth_routes.py tests/test_api_contract.py tests/test_schemathesis_contract.py -q
```

Required evidence:

1. mobile session returns `201`, `Cache-Control: no-store`, `Pragma: no-cache`, expiry and
   user, no cookie, and one opaque token that does not appear in test attachments;
2. browser login still sets the accepted HTTP-only cookie;
3. cookie and Bearer each resolve `/auth/me` and owner-scoped Tasks;
4. both credential sources are rejected as ambiguous;
5. expiry/logout revoke immediately;
6. invalid credentials remain generic and rate-limited;
7. OpenAPI publishes semantic API version `1.0.0`, while `/health` reports storage schema
   separately;
8. every new intentional status has an `ErrorResponse` plus `X-Correlation-ID`.

## 3. Generated contract drift

From repository root after the backend contract is fixed:

```bash
make generate-openapi
cd mobile
npm ci
npm run generate:api
npm run check:api-drift
```

Expected:

- OpenAPI is generated only from an ephemeral test app/data root.
- The committed v1 snapshot and `mobile/src/api/generated/` are unchanged after regeneration.
- No persisted JSON/storage model is used as client-generation input.
- Tokens, account values, and real content are absent from the snapshot.
- The generated mobile operation allowlist contains canonical proposal patch, batch freeze,
  confirm, consent decision, policy, retention, and audio-delete operations and excludes
  deprecated direct proposal `PATCH`, `/finish`, and `/commit` aliases.

## 3a. Canonical Voice backend prerequisite

Before mobile Voice generation/implementation:

```bash
cd backend
uv run pytest tests/test_brain_dump_confirmation_contract.py \
  tests/test_brain_dump_operation_migration.py \
  tests/test_brain_dump_consent.py \
  tests/test_brain_dump_retention.py -q
```

Required evidence:

1. append-only user patches invalidate frozen batches; conflicts/stale revisions cannot freeze;
2. freeze persists one immutable selected proposal revision and stable ordered action IDs;
3. confirm uses deterministic `H(operation_id,batch_id,action_id)` receipts and process death,
   partial failure, replay, or a new outer key cannot duplicate a Task;
4. legacy stored payloads migrate deterministically, terminal payloads remain immutable, and
   deprecated direct `PATCH`/`commit` adapters delegate to the same records during overlap;
5. canonical/alias races create exactly one Task per action and aliases are excluded from the
   generated mobile adapter;
6. restart, consent expiry/withdrawal/regrant, policy/provider-category change, and upload/
   seal/retry/provider checks fail closed and schedule uncommitted cleanup;
7. projection exposes raw-audio state/`retained_until`, and idempotent delete-now survives
   restart/owner checks while preserving Tasks, receipts, and non-audio provenance.

## 4. Mobile static gates

```bash
cd mobile
npm ci
npx expo-doctor
npm run lint
npm run typecheck
npm test -- --runInBand
```

Expected:

- Expo SDK/dependencies/config plugins are compatible.
- Session transport, SecureStore wrapper, first-install cleanup, Task query/actions, local
  recovery manifest, chunking/hashing, operation reducer, and screen components pass.
- Every mobile test emits Allure epic, feature, story, title, and a named product step through
  `mobile/src/test/allureTaxonomy.ts` (or the implemented central equivalent).
- Test output and Allure attachments contain no passwords, tokens, emails, raw audio,
  transcript/proposal/task text, local paths, or content hashes.

## 5. Deterministic backend/mobile integration

Start the test backend with a temporary data root and fake providers, then run the mobile
integration suite against it. The implementation may provide a Make target or script; the
canonical end state is:

```bash
make test-mobile-integration
```

Required scenarios:

- clean install → login → `/me` → Next actions;
- restart restores a valid session; revoked/expired session returns to sign-in;
- plain Inbox capture, complete, explicit reopen destination, stale revision, timeout retry,
  and parity after web reload;
- pagination beyond 50 rows with truthful counts;
- Project and Tag task projections without management controls;
- permission/consent denial or stale/expired/policy-category-mismatched consent creates no
  upload/provider call; restart revalidates and withdrawal schedules cleanup;
- deterministic local fixture → numbered chunk upload → seal → processing → proposal
  patch edit/remove → freeze selected revision → explicit confirm → exact one Task per action;
- app restart after recorded, midway upload, sealed, processing, awaiting confirmation, and
  frozen/confirmation timeout resumes from the durable checkpoint;
- retained-until appears after processing; local audio cleanup is distinct from idempotent
  server delete-now and remote pending survives restart;
- chunk conflict, provider exhaustion, consent withdrawal, stale batch, cancellation, partial
  confirm, and logout cleanup never create an unconfirmed or duplicate Task.

## 6. Native configuration and local builds

CNG output must be reproducible and remain uncommitted:

```bash
cd mobile
npx expo prebuild --clean --no-install
npx expo run:android
npx expo run:ios
```

Review generated configuration for:

- only required microphone/network permissions;
- background recording disabled;
- SecureStore Android backup exclusion;
- correct iOS Keychain/permission/export-compliance settings;
- no secret, production token, keystore, provisioning profile, or provider credential;
- stable package/bundle identifiers and public API-origin injection.

Delete/regenerate native directories before accepting drift; do not commit them unless
ADR-0008's native escape gate is separately satisfied.

## 7. Simulator/emulator journeys

Run the implemented black-box mobile suite (Maestro or the accepted equivalent) against a
development build:

```bash
make test-mobile-e2e-android
make test-mobile-e2e-ios
```

Use synthetic account/task/audio fixtures. Capture redacted screenshots/video and Allure
results for:

- auth restore/logout;
- exactly four GTD lists and truthful drawer controls;
- list continuation/basic detail/plain capture/complete/reopen;
- foreground Brain Dump → upload/processing → Review → confirmation;
- offline/retry/stale/error states;
- reduced motion and 44-point touch targets.

## 8. Real-device smoke

Run once on one supported iOS device and one supported Android device:

1. Clean install and verify residual credential cleanup.
2. Sign in, lock/unlock, restart, and validate session restore.
3. Deny then grant microphone permission.
4. Record a synthetic phrase; interrupt once by audio-route change/incoming-call simulation or
   background transition; verify explicit recovery.
5. Stop, disable/re-enable network during upload, resume, review, edit/remove, freeze, and
   confirm; change/expire the synthetic consent policy once and prove re-consent blocks upload.
6. Verify exactly the confirmed title-only Inbox Tasks in web.
7. Inspect raw-audio `retained_until`, request delete-now once offline and again online, and
   verify pending/deleted state without losing confirmed Tasks.
8. Sign out offline, verify local content/credential disappears, restore network, and verify
   the remote revocation warning/retry path is honest.

Do not attach raw recordings, transcripts, account email, tokens, hashes, or local paths.
Record only pass/fail, platform/OS/app build, operation IDs if policy allows, state names,
coarse timings, error codes, and redacted correlation IDs.

## 9. Internal builds

After static/integration/device gates:

```bash
cd mobile
eas build --profile preview --platform android
eas build --profile preview --platform ios
```

The release owner verifies the EAS project and credential scope before running these. Save
build URLs/IDs as CI or PR evidence, not credentials. Internal builds do not authorize store
submission.

## 10. Privacy and artifact scan

Run the implemented deterministic scanner against source, generated native config, bundles,
logs, Allure, screenshots, and test output:

```bash
make scan-mobile-evidence
```

Expected: zero raw matches for seeded canary password/token/email, fixture transcript/task
content, local audio paths, or chunk hashes. A scanner failure blocks review; do not “fix” it
by weakening patterns without explaining and replacing the evidence.

## Acceptance gate

The slice is ready for release review only when:

- backend, generated-contract, mobile static, integration, both-platform build, simulator,
  real-device, privacy, and control-inventory evidence are green;
- canonical batch/migration/alias-overlap, current-consent/withdrawal, and retained-until/
  delete-now backend gates are green before the mobile Voice adapter is generated;
- ADR-0008 and the mobile-boundary checklist are reviewed;
- every design frame has the exact Build/Bounded/Deferred disposition in the spec;
- no code or copy claims live proposals, background recording, Weekly Review, Execution,
  CRT, inferred metadata, or general offline sync;
- production signing/store submission remains a separately approved action.
