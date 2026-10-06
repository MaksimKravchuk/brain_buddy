# Implementation Plan: Google, Apple and email authentication

**Branch**: `feat/modern-auth` | **Date**: 2026-10-06 | **Spec**: [spec.md](spec.md)
**Base**: `c1576c6` (`origin/main`); Mac reference: PR #265 at `b83d367b30434d1d2448eefdef7043e95dbd9ff6`.
**Status**: planning draft for mandatory high-risk review. No implementation, planning-risk sign-off or release approval claimed.

## Summary

Add Google, Apple and email-code registration/login to the existing FastAPI authority, React web app and native iOS app. Preserve immutable account IDs, owned data, opaque cookie sessions and shared password interfaces used by Mac 021. Ordinary onboarding uses no invite/manual approval and requires no auth SaaS subscription.

Use one authoritative `auth.sqlite3` behind existing user/session repository APIs: transactions own account/binding uniqueness, code consumption, recent proofs, budgets and session issuance. Existing JSON credentials require explicit stopped-writer import; task/tree ownership remains unchanged. Mail/token/revocation network work runs outside write transactions. Matching email never auto-links accounts.

UX authority: [design.md](design.md), explicitly approved by the owner with "Да" on 2026-10-06. Realize D-01–D-06 and M-01–M-07 with their numbered state inventories; no Mac UI work.

## Technical Context

**Language/Version**: Python >=3.11; strict TypeScript/React 19; Swift 6 complete strict concurrency, iOS 26.
**Primary Dependencies**: existing FastAPI/Pydantic/httpx/cryptography/argon2-cffi; add free maintained `joserfc==1.7.5` for JWT/JWK and pin via uv (PyPI version/Python compatibility inspected 2026-10-06). Existing React Router/Zustand/React Query/design components. AuthenticationServices/Security/CryptoKit in the iOS host only; no third-party Swift dependencies.
**Storage**: Identity-owned `data/auth.sqlite3`, reusing SQLiteRepositorySupport. Existing task/flag/relay DBs and tree/voice files retain ownership. Explicit verified one-time JSON user/session migration.
**Testing**: pytest/TestClient, Vitest/Testing Library, Playwright/axe, Linux Swift Testing, macOS/Xcode CI, configured-provider smoke. Feature-qualified `022-FR-###` and `022-SC-###` markers; full requirement coverage without `--requirements` filtering.
**Target Platform**: existing Linux/Fly API/nginx web deployment and iOS; compatible existing Mac password consumer.
**Project Type**: modular monolith with web/native clients; no new deployed service.
**Performance Goals**: local input/busy feedback <=200 ms; no network under DB writes; request enqueue does not wait for SMTP; provider HTTP timeout 10 s; existing canvas/task loop unaffected.
**Constraints**: no mandatory new subscription/purchase; six-digit codes, ten-minute outer attempt cap, five guesses/challenge and persistent shared budgets; >=60 s resend; sensitive proofs <=5 min; failure/cancellation preserves local work; existing 14-day grace.
**Scale/Scope**: test-stage single-volume deployment. SQLite coordinates multiple processes on that volume. Multi-volume identity replicas are unsupported and cannot be enabled implicitly.

## Constitution Check

Pre-research/post-contract checks pass for this proposed implementation, subject to actual planning review, migration and release gates.

- Workflow: confirmed intake/spec precede approved numbered screens. Full path is required for auth/privacy/schema/cross-client ASK work. Tasks/checklists/analyze follow the planning gate; no placeholders simulate completion.
- Consent/safety: only chosen `openid email` identity scopes; no contacts/mail/AI access. Same account/session authority; no secrets/user fixtures in commits/logs/exports or application-session/provider credentials in URLs. Upstream authorization codes and bounded verifier-protected handoff codes use only restricted callbacks with no-store/no-referrer and query redaction.
- Tests: failing-first replay/concurrent consume, stale credential/proof, wrong owner, migration/session parity, provider validation, operator boundary, purge/export and cancellation tests. The 73 existing auth/account tests passed before planning; this is baseline evidence, not new-feature/full-CI acceptance.
- Contracts: [HTTP](contracts/http-auth.md), [native](contracts/native-auth.md), [persistence](contracts/persistence-migration.md). Existing password login/logout/me and invite signup retain payload/session meanings. Modern account endpoints are additive; legacy management remains compatible without conferring unverified mailbox authority.
- Observability: correlation IDs and declared ErrorResponse statuses; redact callback query at uvicorn and nginx, not only middleware. Log coarse event/outcome, never addresses/credentials/full callback URLs.
- Mobile/resilience: staged candidate credentials and immutable-owner/attempt checks precede Keychain/sync; M-04/05 use responsive existing web account UI, M-07 adds direct owner-bound links. Offline capture/outbox and accepted task/review/canvas semantics, including ADR-0027, remain unchanged.
- Delivery: isolated worktree, TDD, actual independent review, exact-SHA CI and ASK landing/release remain authoritative. No automatic promotion or ad-hoc Fly deployment.

## Project Structure

### Documentation

`specs/022-modern-auth/`: intake, spec, requirements checklist, approved design/HTML/captures, plan, research, data-model, contracts and quickstart. Later stages add tasks, traceability, acceptance and report. The persistence contract records the proposed identity ADR; promote to `docs/decisions/0028-modern-auth-and-transactional-identity.md` only after its reviewed decision, without rewriting accepted history.

### Intended source ownership

| owner | existing paths extended | new paths |
|---|---|---|
| schemas | `backend/app/schemas/auth.py`, `account.py` | `modern_auth.py` |
| persistence | `backend/app/repositories/user.py`, `session.py`, `__init__.py` | `auth_store.py`, `auth_metadata.py`, `auth_migration.py` |
| services | `backend/app/services/auth_service.py`, `account_service.py`, `__init__.py` | `modern_auth_service.py`, `auth_provider_service.py`, `auth_mail_service.py`, `auth_secret_box.py` |
| composition/routes | `backend/app/api/auth.py`, `account.py`, `dependencies.py`; `app/container.py`, `main.py`, `cli.py`, `core/config.py`, `core/logging.py` | `backend/app/api/modern_auth.py` |
| web | `frontend/src/api/auth.ts`, `stores/authStore.ts`, `pages/LoginPage.tsx`, `SignupPage.tsx`, `PrivacyPolicyPage.tsx`, `app/AppRoutes.tsx`, `features/account/AccountSettingsPage.tsx` | `api/modernAuth.ts`, `features/auth/` choice/code/recovery/callback/confirmation components |
| shared Swift | `ios/BrainBuddyKit/Sources/BrainBuddyAPI/{BrainBuddyAPIClient,WireModels,RequestBodies}.swift`, `BrainBuddySync/{BrainBuddySync,SyncEngine,SyncEngine+Session}.swift`, `BrainBuddyWorkspace/Workspace.swift` | API `NativeAuthentication.swift`, `NativeAuthCallback.swift`; Sync/Workspace authentication extensions |
| iOS host | `ios/BrainBuddy/Screens/Settings/{SignInSheet,SettingsScreen}.swift`, `ios/project.yml` | native coordinator/code/recovery files in Settings |
| migration release | `.github/workflows/deploy-fly-production.yml`, `docs/autonomous-delivery-runbook.md` | `scripts/auth_migration_guard.py`, `scripts/test_auth_migration_guard.py` |
| setup/edge | `.env.example`, `backend/pyproject.toml`, `backend/uv.lock`, `deploy/nginx/default.conf`, `docs/auth.md`, `docs/api-compatibility.md`, `docs/data-retention.md`, `ios/README.md`, `docs/native-ios-app.md` | `docs/auth-setup.md`, proposed ADR |

Tests use existing backend/frontend/Swift targets plus modern-auth suites and web e2e. JSON-file-count/index mutation tests become real DB or pre-import fixture tests. No `macos/`, GTD reducer, generated Xcode or widget credential-sharing edits.

## Phase 0 — research

Three read-only research agents inspected persistence, provider standards and native hazards; root consolidated [research.md](research.md). Decisions: one Identity SQLite authority; maintained JOSE; client verifier plus callback-delivered grant; authenticated mailbox transition; isolated additive native finalizer. No unresolved technical marker remains.

## Phase 1 — implementation design

### A. Transactional authority and migration — FR-002/005–019/025

Preserve UserRepository/SessionRepository signatures and model returns. Keep mandatory string password_hash, with `""` explicitly unset; never assign the known dummy timing hash. Unset/invalid hashes perform comparable dummy Argon2 work then reject unconditionally; deterministic tests assert expensive verification calls and zero passwordless password sessions. Preserve legacy fields/unknown fields on import; never infer email verification. A shared injected store lets nested facade calls reuse one transaction/connection.

Finishing transactions fresh-check account/version/session/deletion/reservation, consume proof conditionally, mutate the intended identity/account, revoke authority and mint allowed sessions together. Password hashing/verifying runs outside writes; final transaction rechecks exact hash/version. Bad guesses commit budget increments before raising. `save` is update-only; stale writes cannot recreate deleted accounts.

Migration: drain every old JSON writer; validate/recover journal; independently validate records/index; encrypted <=24-hour verified backup; one import transaction; integrity/count/content checks; idempotent original-copy cleanup before readiness. No JSON fallback. Ordinary rollback after auth writes resume requires a SQLite-capable binary; backup restoration discards later writes and requires separate recovery review. Extend the actual release capture/pre-mutation/failure handler with scripts/auth_migration_guard.py: independently read import ledger/coarse image capability, match the captured immutable image, and recheck before restore. Committed or unknown epoch refuses JSON/unverified automatic backend rollback. First-transition failure without a compatible target contains writers and requires exact-SHA forward repair through normal ASK release; it is a failed deployment, not restored service. No second JSON execution mode is introduced. Rehearse the actual handler after commit/cleanup/new writes.

Correct existing seed_admin creation/rotation/current logs to content-free outcomes with permitted opaque IDs, including DEBUG; leakage tests exercise these startup paths as well as provider callbacks.

Admin name edits preserve verification. Legacy/admin password-authorized email updates keep old response contracts but clear email verification/old-address proofs; admin cannot remove an email-only account's last method. Current reserved operator accounts use password authority only; old social/email sessions cannot gain operator rights after configuration changes.

### B. Email, recovery and confirmation — D/M-02/03/05, FR-006/008–014

Client retains a random verifier; server stores S256 only. Public requests return identical neutral 202 envelopes for eligible/ineligible addresses and enqueue durable sealed once-only delivery separately, avoiding SMTP timing/error oracles. Ineligible challenges cannot authorize. Public UI uses neutral non-arrival/resend/alternative guidance; authenticated own-address actions may expose safe delivery failures.

Store code HMAC with a secret outside DB, not enumerable plain SHA-256. Temporarily seal queued code/recipient payload; lease once, erase after dispatch/failure. Activate only acknowledged delivery; uncertain/crashed dispatch invalidates proof and never auto-sends again. Resend preserves challenge/shared guesses, replaces current code, respects >=60 s and does not extend the ten-minute outer cap; show actual server expiry. Do not refund send budgets on failure.

Persistent rolling budgets: dispatch <=5/hour/address, 20/client, 50/network; failed guesses <=10/hour/address, 30/client, 100/network and five/challenge. Keyed fingerprints, normally window-expiry cleanup, <=24-hour retention. Rotation retains prior-key budget authority through active windows.

Recovery requires verified address + usable password, excludes operators; code yields one-use client-bound <=10-minute reset grant. Reset fresh-checks version, enforces existing password policy, revokes all prior sessions/proofs atomically and returns to sign-in. Legacy email verification requires current password authority plus mailbox proof.

Modern email change requires same-account recent proof and new-address code; old address remains until atomic commit. Recent proof must still be <=5 minutes at commit; an expired confirmation can be renewed for the same pending action without silently losing the code. Add/change password/export/delete/unlink use one-use account/session/purpose-bound recent grants.

### C. Providers/linking — D/M-01/05/06, FR-001/003–007/015/017/025

Fixed provider endpoints and bounded JWKS cache. Pin recognized issuer/audience/RS256; reject missing/mismatched nonce/state/expiry, unsupported algorithms and header-selected key URLs. Google uses S256 and `openid email`; store no offline Google grant. Apple confidential exchange signs ES256 client secrets, verifies RS256 assertions and uses web form_post; do not invent Apple upstream PKCE support.

Web callback requires ten-minute HttpOnly/Secure/SameSite=None binder scoped to provider routes; app cookie stays Lax. Native Google broker uses the existing web client, separate server-held upstream S256 verifier and app-held completion verifier. Callback alone delivers an unpredictable <=60-second grant; finish requires it plus verifier. No ready-state polling authorizes. Native Apple sends native assertion/code/state/verifier over POST; exchange checks subject/audience/nonce consistency. No server secret enters Swift.

Stable subject resolves returning bindings; provider email/name never rewrites account. Unbound email collision stops at D/M-06 and requires existing-account login then fresh explicit link. New Google third-party addresses without signed mailbox authority need D/M-02 proof before any durable account/address/binding. Completion consumes the handoff and returns a client-bound verify_mailbox challenge; successful email verification directly finalizes the same staged attempt and returns signed_in with its session, or a safe collision result. It never requires replaying the short-lived handoff. Verified Gmail/signed valid Workspace hd or verified Apple mail/relay can establish mailbox directly.

Link/reauth are bound to immutable owner and current acting session, never another user's session. Reauth offers only connected usable methods. Last-method check is transactional. Unlink revokes affected provider-origin sessions; if caller is affected clear its cookie and explain remaining-method sign-in.

### D. Web/native journeys — all approved IDs, FR-001/002/003/013/015/016/019/022

Web login/signup share provider/email choice and password alternative; legacy invite signup API stays compatible. Add code/recovery/callback states and methods inside existing `/settings/account`; add direct `/settings/account/delete`. Preserve expected_owner through allowlisted login redirects. Unknown availability gives retry/password, never guessed provider availability.

Native finalization stages cookies in memory, checks HTTP success/MeDTO/current generation/captured server/immutable owner, then atomically rechecks document owner before Keychain/link/merge. Modern iOS password alternative uses this same stricter path. Shared legacy password interfaces and tested empty-outbox switching behavior remain for Mac 021. Candidate cleanup revokes only its token and queues offline logout; cancellation/overlap/sign-out/late responses cannot overwrite a newer session.

Google ASWebAuthenticationSession and Apple ASAuthorizationController live in the app target; pure API/parsing/state stays Linux-testable. Preserve Keychain namespaces, pending logout and 021 additive client identity/default. M-07 opens owner-bound web destinations without cookie transfer/local cleanup; browser B/native A and another-tab cookie changes cannot authorize the action.

### E. Privacy, Apple cleanup and setup — D/M-04/07, FR-018–025

Export safe binding/verification metadata only. Existing marker-first/user-last purge erases new auth rows/credentials and migration backup; no Apple failure postpones purge. Deletion immediately revokes sessions/proofs and schedules Apple grant cleanup; retain only subject mapping needed for a new valid explicit in-grace login. Past-due login cannot recreate the account.

AEAD seal minimum Apple revocation grant with owner/identity/client/generation AAD/key ID. Retry <=5 times within 24 hours, capped by purge. Active cleanup leases serialize newer same-binding grant commit; cancel obsolete queued work before accepting a new generation. Missing keys/outage cannot delay local erasure; disclose unconfirmed remote revocation. Validate signed notification issuer/audience/RS256/jti/iat/event time, optional exp; atomically record replay/effect. Reject stale-generation notices; never automatically delete BrainBuddy content. Relay events affect only matching delivery methods.

Disclose actual provider/mail categories, scopes/retention/transfers without invented controller details/DPAs/residency/certification. Use existing app origin and deployment secret manager. Google OAuth/free JOSE, existing Apple membership and owner SMTP/free quota avoid a new auth subscription. No purchases/provider-account writes during implementation.

## Verification and release

[quickstart.md](quickstart.md) contains runnable checks and negative matrices. Red tests precede product code. Full backend/frontend/Swift/repository gates must pass on the candidate. OpenAPI declares intended errors; fuzzing uses ephemeral TestClient only. Actual web journeys/a11y and native CI/device cancellation/autofill tests complement mocks.

Before production: configure actual provider IDs/keyring/SMTP through secret storage, verify Apple grouping/relay/notifications, run provider smoke and rehearse migration/rollback with synthetic data. ASK PR carries review and exact-SHA CI; release still needs named-owner approval/audited landing. Until live deployment evidence passes, report implementation/local verification accurately.

## Complexity Tracking

| addition | required for | rejected simpler alternative |
|---|---|---|
| single Identity SQLite/import | atomic proof/account/session and multi-process uniqueness | JSON sidecar needs cross-store sagas everywhere |
| bounded mail/Apple jobs | neutral public requests and failure/restart retention | synchronous SMTP leaks eligibility; endless retry violates cleanup |
| isolated native finalizer | avoid early cookie installation/wrong-owner sync | direct live-Keychain candidate client races cancellation |

All remain within existing Identity/account ownership; no new task owner/service/runtime.
