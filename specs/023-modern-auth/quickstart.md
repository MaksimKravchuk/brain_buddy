# Validation guide: modern authentication

Planning-stage guide for the implementation. Commands below become acceptance evidence only when run against actual product changes. No provider account, mail sender, migration, native compile or live authentication is claimed configured by this guide.

## Prerequisites and setup

Use the isolated feature worktree. Backend Python >=3.11/uv, Node/frontend lockfile, Docker for Linux Swift; macOS/Xcode for native UI. Provider/network tests use fake transports and synthetic accounts only. No secrets in chat, CLI arguments, fixtures or commits.

Owner deployment inputs: exact HTTPS public frontend origin (existing Fly app can serve callbacks/privacy), Google web client ID/secret + registered callback, Apple Team/Key IDs/private p8/Services ID/native App ID and primary grouping, Apple signed notification audience/URL, SMTP TLS account/from/envelope sources, persistent versioned auth keyring. Register Apple relay sender sources and verify SPF/DKIM. Actual values go into deployment secrets; .env.example documents names only. No new paid auth plan or provider purchase.

Expected availability: missing configuration hides only affected new methods; password remains. Native Google broker reuses Google web registration; Apple native capability goes into project.yml. Privacy/controller contact/DPA/transfer facts must be supplied truthfully before public launch.

## Automated commands

Run relevant new auth/account/provider/migration tests red first, then green. Raw targeted runners are iteration evidence only. From the repository root, with the pinned backend environment on PATH and frontend dependencies installed, the final local candidate runs the existing gate targets:

```bash
make verify-all
sh ios/scripts/swift-linux.sh test
python3 scripts/check_requirement_coverage.py specs/023-modern-auth
python3 scripts/check_gate_integrity.py
python3 -m unittest scripts/test_validate_brain_buddy_design_skill.py
```

`make verify-all` includes full backend/frontend/Playwright suites, freshness, Allure taxonomy, product-E2E and ratcheted coverage validators; raw pytest's 95% floor and frontend runner thresholds do not substitute for repository floors. Required macOS ios-kit/ios-app and exact-SHA CI remain separate gates.

Run Allure taxonomy validation on actual backend results; maintain feature-qualified 022 requirement markers in meaningful Python/TS/Swift tests. Native host build uses existing ios-app macOS CI lane; project.yml/XcodeGen is source, generated files stay ignored. Baseline prior to implementation: 73 existing auth/account tests; static design after review correction: 154 combinations/18 axe checks and no JS errors. Neither is new auth completion evidence.

## Browser journeys

With synthetic mail/provider transports: create/login via each method without invite; return with same ID/data; retain password alternative and Add password for Mac; legacy address cannot use code/recovery before password+mail verification. Check neutral unknown/ineligible send responses, expiry/resend/failed attempts, invalid/replayed/parallel proofs and recovery revoking all earlier sessions.

Attempt provider email collision and wrong subject/issuer/audience/nonce/state; require existing login+explicit fresh link. New third-party Google email stages mailbox proof with no durable claim. Link/unlink/reconfirm/add password/new-email/export/delete uses intended same owner/purpose; last-method removal refused. Lose the fresh-link completion response after server commit: show completion-unknown, refresh same-account methods and obtain fresh proof only if linking is still needed; never claim nothing changed or replay the consumed proof. Change browser cookie in another tab between confirmation/action: no different-account mutation.

At widths 390/1440, keyboard/200% zoom/reduced motion: D-01–06 error/loading/partial/offline/default plus code focus/paste/autofill, focus restoration/cancel, 44px targets and axe. Full-stack web e2e executes real backend endpoints with fake upstreams; DOM-only button demos are not auth evidence. Assert foreign/nonexistent owner-restricted IDs yield identical 404 and zero mutation; own-account expired confirmation yields 403. Inspect seeded-operator creation/rotation/current outcomes at INFO and DEBUG, plus actual app/uvicorn/nginx access records for forbidden codes/tokens/email/callback query and ZIP for secrets.

## SC-007 feedback timing evidence

Web reference: headed Chromium on the candidate build, 1440×1000 and 390×851, record browser/OS/CPU and animation preferences; no CPU throttle. Hold each changed submit/action's completion with the test transport. Mark the user action with performance.now and observe the first animation frame where the visible busy label/aria-busy and disabled submit are rendered. For email request/verify, recovery save, provider start and account mutation, assert elapsed <=200 ms, duplicate dispatch count one and focus remains reachable. Retain sanitized candidate SHA, environment, action and elapsed milliseconds in the acceptance artifact; screenshots alone do not prove timing.

Native reference: supported iOS 26 iPhone simulator (record model, OS, host and candidate build) with completion held pending. Use XCUITest action timestamps and recorded frames/accessibility busy/disabled state to measure the first visible feedback at normal speed; assert <=200 ms and one request while preserving focus/input/local tasks. Add one supported physical-device check before native production acceptance. These are actual client measurements, not static HTML prototype evidence.

## Native journeys and Mac compatibility

Linux tests: all credential variants, local-task first merge, same ID/new email, B/server mismatch with pending and empty outbox, malformed body/error cookie isolation, overlapping/cancelled/sign-out/late responses and candidate-only offline logout. Existing legacy switch/password tests remain. M-07 native A/browser B links block until A proof; opening browser never discards native work.

On actual iOS simulator/device after macOS CI: ASWebAuthenticationSession return to originating sheet; Apple controller capability/state/cancel; code autofill/keyboard/Dynamic Type; offline/cancelled login while capturing local tasks. No SwiftUI compile claim from Linux tests. Recheck latest PR265 and integrate its client-identity defaults without Mac UI edits; exercise its actual password candidate when available, not only its specification.

## Migration/retention rehearsal

Use only synthetic JSON data to rehearse explicit stopped-writer CLI migrate-auth command. Assert IDs/hash/cookie expiry and task owner parity, malformed/journal/index abort, encrypted backup, interrupted import/cleanup restart and readiness block. Race claims/reset/purge on separate DB connections/processes. Verify source files cannot resurrect deleted account and the actual release failure handler re-reads the import ledger and refuses JSON/unverified captured images after commit, cleanup and resumed writes. Assert unreachable/malformed probe evidence fails closed; verify safe selected-image restore and first-transition containment/forward-repair procedures against the workflow command path. A contained failed deploy is not production acceptance.

Assert unknown/passwordless/invalid-hash password login all perform dummy Argon2 verification work and never accept the dummy password or issue passwordless sessions.

Use injected clocks/transport to test expiry/cleanup, failed mail activation, guesses across restart/resend, Apple revoke failure/five attempts/24-hour bound/new grant generation, signed stale/replayed/invalid notices, purge unchanged deadline and backup removal on any purge. Validate safe export and key rotation/missing-key failure with synthetic values only.

## Configured-provider and production evidence

After implementation/local checks, owner-configured Google/Apple/mail smoke is still required: real new/returning accounts, Gmail/external mailbox, Apple relay/returning missing-name, native/browser state/cancel, signed notifications and remote grant cleanup. Record sanitized IDs/outcome/timing, never tokens or user content. Check provider/email free quotas before rollout; errors never silently purchase a tier.

Prepare ASK PR with exact-SHA CI and review evidence. Named-owner approval/audited landing and existing release workflow remain mandatory; no ad-hoc deployment. Rehearse compatible rollback before credential migration. Only report production-complete when the exact deployment/provider smoke and required authenticated primary journey/cleanup pass; otherwise name the remaining setup/environment evidence.
