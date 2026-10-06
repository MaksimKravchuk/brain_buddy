# Tasks: Google, Apple and email authentication

**Feature**: [spec.md](spec.md), [plan.md](plan.md), [design.md](design.md)
**Planning gate**: [planning-review.json](planning-review.json), approved c2 after actual corrections; runtime correlation and failed attempts retained in [review-execution.md](review-execution.md).
**Delivery**: single feature PR on feat/modern-auth; no multi-PR slice map. All accepted stories remain in scope. Product code uses an isolated worktree, tests first and existing review/CI/ASK release controls. Mac 021 interfaces and owned work are preserved.

## Phase 1: Setup

- [x] T001 Write failing configuration/key separation tests in backend/tests/test_modern_auth_config.py and backend/tests/test_auth_secret_box.py for unavailable methods, versioned 32-byte keys and secret-free errors. [022-FR-003/021/023]
- [x] T002 Implement modern settings in backend/app/core/config.py, free pinned JOSE in backend/pyproject.toml and backend/uv.lock, and separated HKDF/HMAC/AEAD in backend/app/services/auth_secret_box.py; document Identity decision in docs/decisions/0028-modern-identity-authority.md. [022-FR-003/008/021/023]

## Phase 2: Foundation

**Goal**: one authoritative transactional store and unchanged legacy APIs before new proofs issue authority.

- [x] T003 Write failing real-DB/migration parity, malformed journal/index, unknown fields, cleanup restart, two-connection uniqueness and no-resurrection tests in backend/tests/test_auth_store.py and backend/tests/test_auth_migration.py. [022-FR-002/004/014/018/019, 022-SC-002/003/005]
- [x] T004 Implement shared transaction reuse/schema in backend/app/repositories/auth_store.py and metadata in backend/app/repositories/auth_metadata.py; adapt backend/app/repositories/user.py, session.py and schemas/auth.py, preserving unknown payload fields, empty unset password, normalized uniqueness and update-only save. [022-FR-002/004–019]
- [x] T005 Implement explicit stopped-writer import, encrypted backup <=24 hours, committed-ledger cleanup/readiness and no JSON fallback in backend/app/services/auth_migration.py and backend/app/cli.py; wire one store through backend/app/container.py. [022-FR-002/014/018/019]
- [x] T006 Make legacy credential/session mutations fresh/atomic in backend/app/services/auth_service.py and account_service.py; unset/invalid hashes run dummy cost then reject, operators remain password-only and seed logs omit email. Replace vacuous JSON-count fixtures in backend/tests/test_auth_service.py, test_account_deletion.py and test_account_export.py. [022-FR-002/010/014/017/019/021, 022-SC-002/003]
- [x] T007 Write failing ledger/captured-image/unreachable/commit-after-capture rollback tests in scripts/test_auth_migration_guard.py and relevant scripts/test_validate_trunk_delivery.py. [022-FR-002/019, 022-SC-002/008]
- [x] T008 Implement scripts/auth_migration_guard.py and actual .github/workflows/deploy-fly-production.yml capture/failure guard; block JSON/unverified restore after commit, preserve DB and failed status, document containment/forward repair in docs/autonomous-delivery-runbook.md. [022-FR-002/019, 022-SC-002/008]

## Phase 3: US1 — start and return with each method (P1)

**Independent evidence**: synthetic full-stack new/returning method login, immutable ID/data and legacy password parity; actual providers verified separately before production acceptance.

- [x] T009 [US1] Write failing provider assertion/exchange/broker tests in backend/tests/test_auth_provider_service.py and code/mail/budget/replay tests in backend/tests/test_modern_auth_service.py and test_auth_mail_service.py. [022-FR-001/003/004/008–010/017, 022-SC-001/003]
- [x] T010 [P] [US1] Implement fixed endpoints/JOSE/JWKS/Google S256 and Apple native/web exchange validation in backend/app/services/auth_provider_service.py; 10-second timeout, <=1-hour key cache and throttled refresh. [022-FR-001/003/004/017]
- [x] T011 [US1] Implement neutral enqueue, once-only encrypted mail leases/activation, <=10-minute challenges, >=60-second resend and persistent 5/20/50 send, 10/30/100 failure budgets with <=5 challenge guesses in backend/app/services/auth_mail_service.py and modern_auth_service.py. [022-FR-001/008–010/014]
- [x] T012 [US1] Implement transactional provider attempts, web binder, <=60-second callback grant plus verifier, stable subjects/collisions and direct mailbox-verification finalization in backend/app/services/modern_auth_service.py and repositories/auth_metadata.py. [022-FR-001/004/005/014/015/017]
- [x] T013 [US1] Add strict request/result schemas in backend/app/schemas/modern_auth.py and discovery/email/provider endpoints in backend/app/api/modern_auth.py; exact origin, foreign404/own reauth403, no-store/no-referrer and declared OpenAPI errors. Wire worker/lifecycle in backend/app/container.py and main.py. [022-FR-001/003/008–010/021]
- [x] T014 [US1] Write real endpoint/secret-redaction tests in backend/tests/test_modern_auth_routes.py and extend backend/tests/test_schemathesis_contract.py for ephemeral new-route errors. [022-FR-001/004/008–010/017/021, 022-SC-003]
- [x] T015 [P] [US1] Write failing choice/code/provider-callback tests in frontend/src/features/auth/__tests__/ModernAuth.test.tsx and frontend/src/api/__tests__/modernAuth.test.ts. [022-FR-001/003/008–010/022]
- [x] T016 [US1] Implement typed wire API and client proof state in frontend/src/api/modernAuth.ts and features/auth/, integrate frontend/src/pages/LoginPage.tsx and SignupPage.tsx with password alternative, neutral code request/resend/recovery entry and fixed callback completion. [022-FR-001–003/008–010/014/022]
- [ ] T017 [US1] Add actual-backend fake-upstream browser journeys to frontend/tests/e2e/modern-auth.spec.ts for new/returning methods, mailbox-required Google and password parity. [022-SC-001/002/003]

## Phase 4: US2 — recover and confirm changes (P1)

**Independent evidence**: one-use verified-address recovery revokes old sessions; new email waits for both proofs; passwordless actions use same-account confirmation.

- [x] T018 [US2] Write failing recovery/reauth/new-address/known-owner-purge tests in backend/tests/test_modern_auth_recovery.py and frontend/src/features/auth/__tests__/Recovery.test.tsx. [022-FR-006/011–014/019, 022-SC-004]
- [x] T019 [US2] Implement reset grants <=10 minutes, recent grants <=5 minutes, password confirmation, authenticated legacy verification, pending email commit and add/change password in backend/app/services/modern_auth_service.py. Preserve legacy account wire contracts and clear verification on legacy/admin email changes. [022-FR-002/006/011–014/017/019]
- [x] T020 [US2] Expose recovery/password-confirm/account-password actions in backend/app/api/modern_auth.py, using expected owner/version/session/action and one-use atomic consume. [022-FR-006/011–014]
- [x] T021 [US2] Implement recovery/reset-success, connected-method confirmation and new-email/password states in frontend/src/features/auth/ and frontend/src/features/account/AccountSettingsPage.tsx; uncertain completion checks same-owner state/fresh proof. [022-FR-006/011–014/022]
- [x] T022 [US2] Add full-stack recovery/email-change/passwordless confirmation and another-tab owner-switch journeys in frontend/tests/e2e/modern-auth.spec.ts. [022-SC-003/004]

## Phase 5: US3 — connect/remove methods (P1)

**Independent evidence**: fresh explicit link retains account/data; email collision cannot merge; last method and foreign binding are protected.

- [x] T023 [US3] Write failing link/unlink/last-method/operator/racing-purge tests in backend/tests/test_modern_auth_linking.py and frontend/src/features/account/__tests__/AuthMethods.test.tsx. [022-FR-004–007/013/017/019, 022-SC-003]
- [x] T024 [US3] Implement connected-method metadata, session/action-bound explicit link and transactional last-method unlink/provider-session revoke in backend/app/services/modern_auth_service.py and api/modern_auth.py. [022-FR-004–007/013/017]
- [x] T025 [US3] Implement collision continuation, method statuses/connect/remove consequence confirmation and remaining-method signed-out result in frontend/src/features/auth/ and features/account/AccountSettingsPage.tsx. Preserve owner through allowlisted frontend/src/components/auth/ProtectedRoute.tsx redirects. [022-FR-004–007/015/022]
- [x] T026 [US3] Exercise real link/collision/cancel/last-method/signed-out and lost-link-response flows in frontend/tests/e2e/modern-auth.spec.ts. [022-SC-003/006]

## Phase 6: US4 — iPhone access retains local work (P1)

**Independent evidence**: pure Swift tests preserve outbox/owner/current credentials under wrong account, cancellation, stale results and failures; actual native host/device evidence remains required.

- [x] T027 [US4] Write failing typed-response/strict callback and isolated cookie tests in ios/BrainBuddyKit/Tests/BrainBuddyAPITests/ModernAuthTests.swift. [022-FR-001/008/015/021, 022-SC-003]
- [x] T028 [US4] Add Linux-testable modern attempt/completion API in ios/BrainBuddyKit/Sources/BrainBuddyAPI/; preserve APIClient.login and 021 client identity defaults, with no server secret/native dependencies in pure kit. [022-FR-001/002/015/024]
- [x] T029 [US4] Write failing cancellation/overlap/sign-out/late-success/wrong-owner/server/empty-and-pending-outbox tests in ios/BrainBuddyKit/Tests/BrainBuddySyncTests/ModernAuthSessionTests.swift. [022-FR-015/016/019/024, 022-SC-003/006]
- [x] T030 [US4] Add isolated modern finalizer/generation/candidate-only pending logout in ios/BrainBuddyKit/Sources/BrainBuddySync/ and additive Workspace entry in Sources/BrainBuddyWorkspace/; modern iOS password alternative uses strict path, old Mac shared behavior remains. [022-FR-002/015/016/019/024]
- [x] T031 [US4] Implement ASWebAuthenticationSession Google/ASAuthorizationController Apple coordinator and code/password/recovery sheet in ios/BrainBuddy/Screens/Settings/SignInSheet.swift and ModernAuthCoordinator.swift; capability only in ios/project.yml. [022-FR-001–003/008/011/015/016/022]
- [x] T032 [US4] Add safe expected-owner Manage/Delete web links in ios/BrainBuddy/Screens/Settings/SettingsScreen.swift using discovered configured origin; preserve document/outbox and native Keychain namespaces. [022-FR-013/015/016/018/019]
- [ ] T033 [US4] Run full ios/scripts/swift-linux.sh tests and capture actual ios-kit/ios-app exact-SHA CI; exercise device browser/Apple cancel/return/autofill/Dynamic Type and latest Mac PR265 integration. Record limitations in specs/022-modern-auth/verification.md. [022-SC-001/002/003/006/007/008]

## Phase 7: US5 — privacy rights and provider cleanup (P2)

**Independent evidence**: safe export, passwordless direct deletion and retry-safe purge; signed Apple notice and remote cleanup cannot extend local deletion.

- [x] T034 [US5] Write failing export/purge/key rotation/missing-key/Apple lease-generation-notice tests in backend/tests/test_modern_auth_privacy.py and test_auth_apple_cleanup.py. [022-FR-018–021/025, 022-SC-005]
- [x] T035 [US5] Implement minimum sealed Apple grant jobs, <=5 attempts/24 hours capped by purge, replacement lease serialization and signed nonreplayed notices with <=7-day event/8-day receipt bounds in backend/app/services/auth_provider_service.py and modern_auth_service.py. [022-FR-019/025]
- [x] T036 [US5] Extend backend/app/services/account_service.py safe export/marker-first-user-last purge and new rights endpoints in api/modern_auth.py; remove auth-owned rows and entire migration backup without Apple-dependent delay. [022-FR-013/018/019/025]
- [x] T037 [US5] Implement direct /settings/account/delete route, passwordless export/delete and truthful Apple pending/unconfirmed result in frontend/src/features/account/AccountSettingsPage.tsx and frontend/src/App.tsx routing; test foreign browser owner and local-success/remote-failure. [022-FR-013/018/019/025, 022-SC-004/005]
- [x] T038 [US5] Update actual processor/scope/retention/rights disclosure in docs/data-retention.md and frontend/src/pages/PrivacyPolicyPage.tsx; no invented controller/DPA/residency or legal certification. [022-FR-020, 022-SC-005]

## Phase 8: Candidate verification and delivery

- [x] T039 Update callback/secret-safe application/nginx access logging in backend/app/core/logging.py and deploy/nginx/default.conf; exercise validation input, seed logs and forbidden secret/address/query leakage in backend/tests/test_modern_auth_routes.py. [022-FR-021]
- [x] T040 Document Google/Apple/SMTP/free-quota/key rotation/migration/recovery setup in docs/auth-setup.md, .env.example, docs/auth.md, docs/api-compatibility.md, docs/native-ios-app.md and ios/README.md. [022-FR-002/020/023/024/025]
- [ ] T041 Measure actual web/native <=200 ms pending feedback, focus/duplicate submits, 44pt/mobile/keyboard/uncertain states and retain candidate-bound screenshots/measurements in specs/022-modern-auth/verification.md per quickstart.md. [022-FR-022, 022-SC-007]
- [ ] T042 Run make verify-all, full022 requirement coverage, native gates and meaningful negative suites; fix failures and retain actual fresh results in specs/022-modern-auth/verification.md. [022-SC-001–008]
- [ ] T043 Produce typed writer receipt under specs/022-modern-auth/ for frozen implementation SHA, validate via scripts/validate_pre_freeze_receipt.py and obtain independent acceptance/code/QA review; no writer-certified independent PASS. [022-SC-008]
- [ ] T044 Prepare focused single ASK PR with exact SHA, linked spec/design/reviews and current evidence; run /speckit-accept and /speckit-report into specs/022-modern-auth/acceptance.md and report.md. Distinguish remaining live setup/migration/native/production evidence; no ad-hoc merge/deploy. [022-SC-008]

## Pre-freeze evidence

<!-- BrainBuddy constitution gates: typed writer receipt is required before freeze. -->
<!-- BrainBuddy pre-freeze receipt contract: tasks. Preserve this section. -->

T043 covers writer-owned pre-freeze evidence only. Independent review, CI, landing, deploy and production smoke are post-freeze obligations. Live provider keys, actual device/CI and public disclosure inputs are operational evidence requirements, not passes inferred from mocks.

## Dependencies and execution

Setup precedes foundation; shared store/config/wire contracts precede authority issuance. US1 precedes US2/US3 integration. US4 pure API/isolated finalizer can progress independently after foundation/wire contract, with disjoint writers; its real endpoint journeys join after US1–3. US5 joins common authority and cleanup before full acceptance. US2/US3/US5 often share service/account files and run serially under one writer. No overlapping metadata/container writers.

T010 provider validation and T015 web tests are genuinely disjoint opportunities after shared contracts; they do not create separate PRs. If workers are used, use isolated worktrees, distinct BRAIN_BUDDY_DATA_DIR/ports/E2E project, and serial integration. Never run concurrent shared Playwright output cleanup.

Incremental delivery starts with the legacy-compatible foundation and US1 evidence, then completes every remaining accepted story before feature acceptance. Partial increments do not claim the whole feature or production complete. All product tests emit Allure taxonomy and feature-qualified FR/SC markers. Read-only planning analysis must report zero CRITICAL before coding.

## Explicit requirement-to-task traceability

This maps planned work, not executed acceptance evidence. Shorthand in individual task labels uses the same feature prefix throughout.

| requirement | tasks |
|---|---|
| 022-FR-001 | T009–T017, T027–T031 |
| 022-FR-002 | T003–T008, T016, T019, T028–T030, T040 |
| 022-FR-003 | T001–T002, T010, T013, T015–T016, T031 |
| 022-FR-004 | T003–T004, T009–T012, T014, T023–T026 |
| 022-FR-005 | T004, T012, T023–T026 |
| 022-FR-006 | T018–T026 |
| 022-FR-007 | T023–T026 |
| 022-FR-008 | T001–T002, T009, T011, T013–T016, T027, T031 |
| 022-FR-009 | T009, T011, T013–T016 |
| 022-FR-010 | T006, T009, T011, T013–T016 |
| 022-FR-011 | T018–T022, T031 |
| 022-FR-012 | T018–T022 |
| 022-FR-013 | T018–T025, T032, T036–T037 |
| 022-FR-014 | T003–T006, T011–T012, T016, T018–T021 |
| 022-FR-015 | T012, T025, T027–T032 |
| 022-FR-016 | T029–T032 |
| 022-FR-017 | T006, T009–T010, T012, T014, T019, T023–T024 |
| 022-FR-018 | T003–T005, T032, T034, T036–T037 |
| 022-FR-019 | T003–T008, T018–T019, T023, T029–T030, T032, T034–T037 |
| 022-FR-020 | T034, T038, T040 |
| 022-FR-021 | T001–T002, T006, T013–T014, T027, T034, T039 |
| 022-FR-022 | T015–T016, T021, T025, T031, T041 |
| 022-FR-023 | T001–T002, T040 |
| 022-FR-024 | T028–T030, T040 |
| 022-FR-025 | T034–T037, T040 |
| 022-SC-001 | T009, T017, T033, T042 |
| 022-SC-002 | T003, T006–T008, T017, T033, T042 |
| 022-SC-003 | T003, T006, T009, T014, T017, T022–T023, T026–T027, T029, T033, T042 |
| 022-SC-004 | T018, T022, T037, T042 |
| 022-SC-005 | T003, T034, T037–T038, T042 |
| 022-SC-006 | T026, T029, T033, T042 |
| 022-SC-007 | T033, T041–T042 |
| 022-SC-008 | T007–T008, T033, T042–T044 |
