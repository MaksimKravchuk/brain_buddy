# Tasks: Agent-friendly BrainBuddy CLI

Input: specs/023-agent-cli/{spec,design,plan,research,data-model}.md and contracts/.
Status: Approved portable execution list, owner founder acceptance2026-10-06. UX approved2026-10-06. The owner rejected a second Codex login and directed use of the current agent runtime. Second planning campaign uses native read-only reviewer sessions with explicit unverified/correlated provenance; no external Codex login is required. This list does not bypass the planning verdict or authorize production. One serial candidate, no multi-PR split.

Delivery gates: isolated feat/agent-cli worktree; observe failing behavioral tests before implementation; qualify requirement IDs023-FR/SC in test names/stories; central Allure taxonomy for pytest/Vitest/Playwright; mandatory approved/founder-accepted planning verdict and proposed ADR0029 acceptance. Independent exact-SHA review/QA, required CI, recorded ASK landing approval and normal Fly release remain separate obligations. Before freeze produce .specify/templates/pre-freeze-receipt.schema.json receipt and run scripts/validate_pre_freeze_receipt.py with exact SHA. Writer receipts never claim independent or release evidence.

## Phase 1: Setup

- [ ] T001 Initialize cli/Cargo.toml, cli/Cargo.lock and cli/rust-toolchain.toml with one bb package and tested target dependencies; reconcile published shared-auth/flag changes before freezing.
- [ ] T002 Extend scripts/check_requirement_coverage.py and its tests for cli/tests .rs IDs; add unfiltered `python3 scripts/check_requirement_coverage.py specs/023-agent-cli` to Makefile check-specs, pin its gate-integrity invariant/test, then regenerate hashes with scripts/check_gate_integrity.py --update; preserve all existing gates/floors.

## Phase 2: Foundation

- [ ] T003 Write failing bounded parsing/transport/security tests in cli/tests/contract.rs and cli/tests/transport.rs for1MiB input,8MiB response,10s connect/30s request, zero redirects/retries, unsafe paths, excluded public/auth/account/admin paths, generic-write selector rejection before dispatch, confirmed-write response-processing failure, and structured exits.
- [ ] T004 Implement cli/src/{command,request,error,config,main}.rs shared clap compiler, canonical origin/prefix, stdin/file bounds and HTTP/error contract; preview/discovery must bypass network/store.

## Phase 3: US1 — Terminal task journey (P1)

Goal: capture/search/read/edit/complete without prompting. Independent test: disposable account final-state readback, create replay one ID, stale edit preserves work.

- [ ] T005 [US1] Write failing cli/tests/task_journey.rs against disposable backend/HTTP fixtures for023-FR-001/005/006 and023-SC-001/003, explicit key/revision and uncertain delivery.
- [ ] T006 [US1] Implement task add/list/get/update/transition mapping in cli/src/command.rs and cli/src/request.rs using current Task schemas and lifecycle; no implicit read-modify-write.

## Phase 4: US2 — Efficient discovery and generic JSON (P1)

Goal: bounded concise operation discovery/output. Independent test: offline commands/preview, scoped schema, cursor/field/full parity and byte reduction.

- [ ] T007 [US2] Write failing cli/tests/output.rs and cli/tests/discovery.rs for023-FR-002/003/004/008 and023-SC-002; twenty rich synthetic tasks default≤40% full bytes with required fields/cursor preserved.
- [ ] T008 [US2] Implement cli/src/output.rs projection/list bounds and command/schema/preview/project/tag/tree/api in cli/src/command.rs; remove unsupported project restore, redact all preview input values, preserve opaque cursor/no implicit pages.

## Phase 5: US4 — Convenient shared-account connection (P1)

Goal: approve once through common login, protected reusable separate session. Independent test: browser/headless connection, prompt-free task read, failures and separate revoke.

- [ ] T009 [US4] Write failing backend/tests/test_cli_auth.py for256-bit private proof, eight-character normalized code,600s expiry/max1024 records,5s poll/slowdown, Origin/owner/final exposure+expiry checks, pre-JSON1KiB streamed bodies (chunked/false length), and no code reflection/export.
- [ ] T010 [US4] Add barrier-controlled independent-process/restart tests in backend/tests/test_cli_auth.py proving shared AuthStore conditional-consume/session atomicity, exactly-one committed issuance, source/bulk/provider revoke and auth_version/purge races, commit rollback with no session or consumption, restart/lost-response replay refusal and SQLite lock release after termination.
- [ ] T011 [US4] Implement backend/app/{schemas,repositories,services,api}/cli_auth.py, shared AuthStore device table/index migration and auth_metadata lifecycle, DI/container, narrow device validation branch in backend/app/api/errors.py, and existing session minting within one transaction. Inherit source auth_version/auth_method/provider_binding_id and check provider generation; commit before returning secrets, rollback consumption plus mint together; no JSON/flock sidecar or cross-module repositories.
- [ ] T012 [US4] Implement compatible optional cli_auth inventory in backend/app/{core/config,repositories/feature_flag,services/feature_flag_service}.py per ADR0029/contracts/rollout.md; add rollback/absence-preserving-write tests to backend/tests/test_feature_flag_repository.py.
- [ ] T013 [US4] Integrate backend/app/services/account_service.py grant purge/export exclusion and backend/app/main.py startup/periodic privacy cleanup; update docs/auth.md, docs/data-retention.md and export manifest; tests cover idle/OFF cleanup and account deletion.
- [ ] T014 [US4] Write failing frontend approval/return-route Vitest tests for signed-out password/email/Google/Apple entry, early fragment capture, tab-retained-code expiry/refresh/manual fallback and hostile destinations, plus collected frontend/tests/e2e/cli-auth.spec.ts plus mobile scenarios in frontend/tests/e2e/mobile.spec.ts using central Allure labels/named steps; prove Playwright --list collection.
- [ ] T015 [US4] Implement frontend/src/features/cli-auth/{CliAuthorizePage.tsx,api.ts}, AppRoutes.tsx (capture before authentication redirect) and auth/authFlow.ts safeAuthDestination allowlist; verify ProtectedRoute, LoginPage, AuthEntry and ProviderCompletionPage return seams, with <=600s tab-scoped short-code retention/terminal erasure and no private proof in browser storage; bounded30s browser requests, explicit B02–B09 focus/copy/recovery/mobile states.
- [ ] T016 [US4] Pass trusted origin through compose.yaml/.env.example; provision per-run origin/exposure/readback in scripts/run_playwright_e2e.sh; add reviewed nonsecret origin to fly.backend.toml for normal release only.
- [ ] T017 [US4] Write failing cli/tests/auth.rs/native-store checks for headless/browser polling, denial/expiry/cancel, Set-Cookie validation, origin/account isolation, save failure/new-session cleanup, status/logout and no secret output.
- [ ] T018 [US4] Implement cli/src/auth.rs/credential.rs/config.rs and native adapters: noninteractive native reads, explicit Unix0700/0600 owner/no-symlink fallback, Windows file mode unsupported, stage/read-back/atomic metadata and source-aware logout.

## Phase 6: US3 — Native release and installation (P1)

Goal: compiler/admin-free verified installation. Independent test: five native executable jobs plus installer preservation and actual fixed published Linux/macOS15-both-architectures/Windows install.

- [ ] T019 [US3] Write installer/archive fixtures in cli/tests/installers/ and scripts/test_build_cli_release.py for exact target/version/manifest, corrupt/interrupted/unsafe downloads and old-binary preservation.
- [ ] T020 [US3] Implement cli/install.sh and cli/install.ps1 user-owned staged verified installers; no PATH edits, unsafe symlinks, integrity bypass or silent version fallback.
- [ ] T021 [US3] Integrate five native read-only jobs, macOS15 minimum link/run/installer evidence on both architectures, and required aggregate into .github/workflows/ci.yml/Makefile; implement scripts/build_cli_release.py SOURCE.json/SHA256SUMS with exact SHA and native evidence.
- [ ] T022 [US3] Implement scripts/publish_cli_release.py explicit approved-actor publication evidence checks and cli/README.md installation/platform/agent/auth/recovery docs; candidate jobs receive no write identity.

## Phase 7: Verification, freeze and authorized release

- [ ] T023 Run targeted and full applicable suites/make verify-all, spec/gate/Allure/coverage checks; record writer-only pre-freeze receipt and exact candidate SHA in specs/023-agent-cli/verification.md.
- [ ] T024 Obtain independent exact-SHA code review/QA and required CI, prepare concrete ASK PR/landing/release decision with artifacts; record evidence in specs/023-agent-cli/review-status.md, never claim merge/production approval from UX approval.
- [ ] T025 After recorded authority, verify prerequisite modern-auth release/import and SQLite-capable predecessor; normal main/Fly CLI release then establishes the CLI-compatible rollback floor, then explicit runtime cli_auth activation/readback and binary publication; execute actual released installers/authenticated journey/cleanup and record specs/023-agent-cli/{acceptance,traceability,report}.md via speckit-accept/report.

## Dependencies and execution

All tasks remain blocked on the mandatory planning verdict/ADR acceptance. Backend integration must use the published modern-auth authority after it lands with unique feature reservation; release requires its completed import and SQLite-capable rollback baseline. Rust wire-fixture development need not wait for production auth activation. T001–T004 precede story code; T005 beforeT006, T007 beforeT008; auth tests before matching implementation, with backend contract before frontend/client polling. US1/US2 can be tested with external synthetic credentials independently of browser auth. US3 depends on complete client for native evidence. US4 is required for final owner journey; T023–T025 follow all stories.

Use one serial writer. Independent read-only reviews may run in parallel, but no [P] task implies another PR or unrestricted agent. Story-specific disjoint tests could be prepared in parallel if explicitly staffed; no parallel implementation is requested. MVP checkpoint is US1/US2 with external test session; final publication includes all four accepted P1 stories and full auth/install evidence.
