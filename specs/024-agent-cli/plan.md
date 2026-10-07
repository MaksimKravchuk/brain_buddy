# Implementation Plan: Agent-friendly BrainBuddy CLI

**Branch:** feat/agent-cli | **Date:** 2026-10-06 | **Spec:** [spec.md](spec.md)

## Summary

Deliver Rust bb, compact agent-facing JSON, explicit browser/headless login using a separate opaque session, five native archives and verified one-command installation. Extend the published transactional Identity authority with device grants/approval; delegate sign-in to the shared login page. No business cache, provider integration, MCP/TUI, new task lifecycle or unrelated UI. One serial ASK candidate follows full planning review, exact-SHA review/QA/CI, recorded landing approval and production/released-installer evidence.

Owner-approved [design.md](design.md) is binding: D-01 S01–S12 for agent work, D-02 S01–S07 for installation and D-03 S01–S12 for connection. The browser approval states are made concrete there and in contracts/device-auth.md.

## Technical Context

**Languages:** available Rust 1.99.0; pin tested toolchain and Cargo.lock. Python3.11 backend; existing strict TypeScript/React frontend. Do not promise a lower Rust MSRV without testing the lockfile.

**Dependencies:** clap/serde/serde_json, blocking reqwest0.12.28 with native-root rustls, keyring3.6.3 with explicit target backends, directories, webbrowser, ctrlc, zeroize. Linux dbus-secret-service4.1.0 and macOS security-framework3.7.0 reuse keyring's native stacks for prompt-free reads. Existing backend/frontend tools suffice; no application async runtime/telemetry framework.

**Storage:** business repositories unchanged; bounded device grants in the shared Identity auth.sqlite3/AuthStore transaction; no JSON grant sidecar or filesystem authorization lock. Native credential stores or explicit Unix private-file fallback; nonsecret connection metadata only. No content/refresh-token store.

**Platforms:** Linux x86_64/aarch64 glibc≥2.35; macOS15+ x86_64/aarch64, requiring native link/run and released-install evidence at15 on each architecture before publication; Windows10/11 x64 MSVC. Backend supported Linux file-volume topology remains authoritative. Windows ARM, signing/notarization and package registries excluded.

**Bounds:** command input1MiB; response8MiB including chunked bodies; error output16KiB; connect10s/business request30s; task list default20/max200. Device body1KiB, grant600s/max1024, initial polling5s with slowdown. See contracts/cli.md and contracts/device-auth.md.

**Performance:** one business request, no implicit pages/revision lookup/retry. SC-002 requires≥60% UTF-8 byte reduction on twenty synthetic rich tasks; token counts need an identified actual tokenizer. Help/discovery requires neither network nor keychain.

## Constitution Check

| Gate | Resolution |
|---|---|
| Current spec/design | Scope/auth/install steering reflected; UX approved2026-10-06; technical review remains mandatory. |
| Consent/privacy | Existing ownership/consent server-enforced. Explicit approval issues separate CLI access. No provider passwords/tokens/real content in fixtures/logs. Preview redacts all input values without credentials/network. |
| Verification | Rust subprocess/HTTP/output tests; backend state/race/purge tests; frontend approval/return tests; real disposable-account journey and native installs. Existing Allure helpers label new pytest/Vitest/Playwright product tests. |
| Compatible interfaces | Additive device endpoints/cli_auth flag only; existing member JSON/cookies unchanged. Generic operations use deployed schema. |
| Observability | Safe status/detail/X-Correlation-ID/reference_id/Retry-After; uncertain write delivery explicit. Device logs include operation/coarse outcome/correlation only. |
| Mobile/resilience | Responsive approval, keyboard/focus/accessibility and offline/expiry/denial recovery. No canvas/voice/native changes. |
| Delivery | Isolated worktree, tests, independent exact-SHA code review and QA, required CI, ASK approval and normal Fly release. No candidate publishing identity. |
| Design citation | Transport/output D-01; installers D-02; grants/storage/approval D-03. Expanded browser state inventory binding. |

Proposed docs/decisions/0029-runtime-managed-cli-authentication.md must be accepted with this plan; it extends accepted modern Identity ADR-0028 with same-transaction device issuance and narrowly extends ADR-0019 for optional pre-activation cli_auth inventory and compatible rollback stages. See contracts/rollout.md. Preserve ADR-0001 Identity/module ownership/opaque sessions, ADR-0002 consent/idempotency, ADR-0006/0020 lifecycle/priority, ADR-0008 ASK, ADR-0011/0012/0014/0024/0025 review provenance, ADR-0019 runtime flag authority and ADR-0022/0023 flags/delivery. No constitution waiver, new authority, bearer scheme/provider store or domain boundary.

## Project Structure

Create cli/Cargo.toml, Cargo.lock, rust-toolchain.toml; cli/src/{main,command,request,output,error,config,credential,auth}.rs; platform adapters under cli/src/credential/; cli/tests/ subprocess/HTTP fixtures; cli/install.sh, cli/install.ps1 and cli/README.md. One executable/package/shared command model.

Extend backend/app/core/config.py, repositories/{auth_store,auth_metadata,feature_flag}.py, services/{auth_service,account_service,feature_flag_service}.py, container.py, api/dependencies.py and main.py; narrow device validation handling in backend/app/api/errors.py. Create backend/app/{schemas,repositories,services,api}/cli_auth.py with existing route→service→repository layering. Identity does not import Tasks/Thinking repositories. Add backend/tests/test_cli_auth.py and narrow existing session/flag regression tests.

Create frontend/src/features/cli-auth/{CliAuthorizePage.tsx,api.ts} and focused tests. Extend frontend/src/app/AppRoutes.tsx and features/auth/authFlow.ts safeAuthDestination for /cli/authorize; verify LoginPage, ProtectedRoute, AuthEntry and ProviderCompletionPage return seams and existing flag types/allow-lists. Reuse shared auth/API/UI primitives. Add frontend/tests/e2e/cli-auth.spec.ts plus approval scenarios in frontend/tests/e2e/mobile.spec.ts; verify collection with Playwright --list for approval.

Integrate read-only native build/package jobs into .github/workflows/ci.yml and required Full CI. Create scripts/build_cli_release.py for five-archive aggregation/SOURCE.json/SHA256SUMS and scripts/publish_cli_release.py for approved-actor publication. Extend Makefile cargo/installer verification; scripts/check_requirement_coverage.py scans cli/tests .rs with unit tests, and Makefile check-specs must run unfiltered `python3 scripts/check_requirement_coverage.py specs/023-agent-cli`. Pin that invocation with the corresponding gate-integrity invariant/test and regenerate hashes via scripts/check_gate_integrity.py --update. Preserve logic/floors. Update .env.example, compose.yaml and scripts/run_playwright_e2e.sh for per-run trusted origin and synthetic account exposure/readback; update fly.backend.toml's nonsecret frontend verification origin through reviewed source configuration only. Update docs/auth.md/docs/data-retention.md/export manifest. No live deploy/main/ruleset changes during implementation.

## Serial implementation and verification

### A. Command contract/transport — D-01 S01–S12

Write failing subprocess tests for parsing/revision/key, projection/cursor, malformed/oversized input, errors/discovery. Separate shared clap request compiler from credentials/network so preview is provably offline. Map tasks/projects/tags to backend/app/api/tasks.py and tree list/get/explicit existing operations to api/routes.py. Generic JSON covers remaining deployed operations. No invented mutation schema.

Reqwest retry::never(), redirect::Policy::none(), system trust, explicit time/byte bounds. Reject unsafe origin/path/header locally. Never print credential-bearing Debug/raw HTTP. Transport after write reports delivery_unknown:true, safe supplied key and deliberate recovery; callers choose retries. Errors keep selected safe details, removing validation input/ctx/secret fields/non-JSON bodies.

### B. Identity extension/approval — D-03 S02–S04/S06/S08/S12

Published dependency: origin/feat/modern-auth@bc7fc72c35b7bf794eff912c07bdd38a1d1f0816, accepted ADR-0028 modern Identity. It is not claimed landed. Reuse its AuthStore/user/session facades; do not ship a duplicate Identity migration. Backend implementation targets the integrated modern-auth baseline; independent Rust work can use compatible wire fixtures. CLI release requires the modern-auth import/release and a verified SQLite-capable predecessor first.

Failing tests cover grant transitions, CSRF/exposure, fresh owner/auth_version/source session/provider generation, source/bulk/provider revoke, deletion and commit failure. Add an additive validated device-grant table/indexes through AuthStore without changing the established Identity storage epoch or legacy import. In one BEGIN IMMEDIATE transaction, recheck current source authority, conditionally consume approved grant, mint a distinct session inheriting auth_method/provider_binding_id and current auth_version, perform final checks, then commit before returning any secret. Mint/commit failure rolls back both consumption and session. A committed exchange with a lost response remains consumed and never reissues. Pending/slow_down counters must commit before their protocol errors are returned.

Separate barrier-controlled connections/processes share a disposable SQLite root: concurrent exchange yields one committed session, revoke/version/provider/purge races prevent later issuance, failed commit preserves approved grant with no session, restart preserves consumed state, and process termination releases SQLite locks. Remove obsolete JSON/flock/parent-directory-fsync tests. Device foreign keys cascade owner/source/provider erasure; explicit purge and the existing startup/periodic metadata sweep erase grants independently of exposure. Export excludes device proof hashes/authority metadata, with an explicit manifest/policy entry. No quarantine or separate provider credential store.

cli_auth uses existing SQLite authority with six required baseline rows plus optional missing→OFF row. No seed/read/upgrade/unrelated mutation/scrub writes its absent row. Existing mutate's all-row upsert must preserve absence. Initial deployment persists neither CLI row nor grants; only after successful compatible release/recorded rollback floor may explicit admin activation create it. Preserve legacy migration markers/cohorts and strict degraded-store purge safety; see ADR0029/contracts/rollout.md. Anonymous starts reveal only capability; browser/exchange recheck owner exposure. OFF blocks unconsumed grants; existing revoke authority handles issued sessions.

Capture and validate the user-code fragment in the CLI entry page before any authentication redirect; clear history immediately. Keep only normalized short user code and bounded <=600s deadline in tab-scoped sessionStorage, never the private device proof. Allowlist only /cli/authorize as shared-login destination, with no arbitrary query/hash retention. Delegate login to existing AuthEntry/provider completion; restore retained code after password/email/Google/Apple entry. Clear retained state on terminal outcome/expiry/cancel; missing, stale or inaccessible storage falls back to B02 manual entry. Test hostile destinations, refresh, provider round trip and focus recovery. Implement load/account/code/approve/deny/invalid/expired/unavailable/error states with no navigation approval. Vitest/Playwright verify 390px/mobile and desktop, keyboard/focus/accessibility and failure recovery. Reconcile published parallel auth changes at this seam before candidate freeze.

### C. Client auth/protected storage — D-03 S01–S12

Implement bounded start/poll/Set-Cookie capture. Linux noninteractive reads downcast SsCredential for exact attributes, connect_with_max_prompt_timeout(Dh,0), reject locked/ambiguous matches, read unlocked Item::get_secret without unlock. macOS holds SecKeychain::disable_user_interaction() guard around entry.get_secret. Windows native CredRead. Operations serial; only explicit login may interact with keychain.

Preflight store; stage new locator/read-back; atomically commit nonsecret metadata; retire old locator after success. Failure/cancellation revokes new session, reports uncertain cleanup and preserves old access. Explicit Unix file fallback checks owned0700/0600 regular directory/file, no symlinks each use; Windows file mode fails unsupported while native/external sources work. Status/logout report source/identity/actual revocation without removing unrelated accounts/origins.

Native tests prove separate-process persistence and locked-store refusal: isolated Linux DBus/Secret Service, disposable macOS Keychain, isolated Windows generic credential. HTTP mocks/external token alone cannot establish native correctness. Clean synthetic credentials after testing.

### D. Builds/install/release — D-02 S01–S07

Native matrix compiles/tests five targets with locked dependencies, fmt/clippy, version/help/discovery and native credential/installer evidence. Both Linux architectures build on Ubuntu22.04 (ARM native host may use22.04 container); macOS/Windows native linkers. Record macOS deployment floor before release. Full CI fails any required matrix/aggregate failure or skip.

Aggregation rejects missing/extra/duplicate targets/version/SHA drift/unsafe archives. SOURCE.json binds exact source and evidence. Installers resolve one version, check exact filename/hash over HTTPS, stage on destination filesystem, validate version before atomic replacement, preserve prior executable on failure, require no admin/compiler/PATH-file edits. See contracts/distribution.md.

Publish via approved actor after exact-SHA CI/review/QA and recorded release decision; no write identity in build workflows. Main/Fly follows ADR-0008 recorded ASK approval/audited intervention. Deploy trusted origin and compatible optional-row/purge reader with no CLI row/grants; verify initial smoke succeeds and record compatible SHA/image rollback floor before explicit operator activation. Then verify OFF→intended cohort exposure, publish fixed binaries and run actual Linux/macOS15-both-architectures/Windows release installation. Required production evidence cannot be waived merely because source is ready.

### E. Acceptance/evidence

SC-001 disposable account create/replay/search/read/edit/complete/readback plus stale/foreign-owner failure. SC-002 twenty rich tasks byte comparison retaining required fields/cursor. SC-003 subprocess failures including429 and accepted-write/lost-response. SC-004 five native jobs plus corrupt/unsupported/interrupted/destination installer fixtures. SC-005 actual released Linux/macOS15-both-architectures/Windows install without compiler/admin. SC-006 browser/headless approval/protected save/read-back/prompt-free business commands, failure states and separate CLI revoke.

Run all required applicable suites and make verify-all on frozen candidate, including unfiltered feature023 requirement coverage, Allure taxonomy/coverage floors unchanged. iOS CI lanes remain repository-required; feature-specific iOS acceptance N/A because no native/domain contract change. Independent exact-SHA review/QA cover auth, transport, installs and changed browser states. Record sourceSHA, CI/release URLs, flag readback, bounded screenshots/synthetic results and cleanup; no real credentials/content. Standard authenticated production smoke plus authorized disposable CLI journey remain required.

## Complexity Tracking

No constitution violation. Native adapters, the Identity transaction and five builds directly serve accepted security/platform outcomes. Keep one candidate; omit provider login, Identity database migration, HA, telemetry and new release authority.
