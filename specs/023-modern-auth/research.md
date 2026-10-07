# Research: modern authentication

Completed 2026-10-06 at base `c1576c6`; Mac reference PR #265 `b83d367b30434d1d2448eefdef7043e95dbd9ff6`. Three read-only research agents inspected persistence, provider standards and native integration. Root made the decisions below; these are findings, not approval verdicts.

## R1 — one transactional authority

**Decision**: Identity-owned auth.sqlite3 behind existing user/session APIs; preserve account IDs and other-module owners.
**Rationale**: user.py uses process-local RLock; create writes user/index separately; only profile updates have journal recovery. session.py has no coordinated lock. sqlite.py provides reusable WAL/foreign-key/BEGIN IMMEDIATE machinery. ADR-0001 allows incremental persistence within current Identity ownership.
**Alternatives**: JSON+SQLite sidecar requires cross-store recovery for every authority transition; external SaaS adds fees/another authority; separate service is unnecessary.

## R2 — explicit migration/rollback

**Decision**: stopped old writers, validated journal recovery, independent record/index comparison, encrypted <=24-hour verified backup, one import commit and original-copy cleanup before readiness. Never infer legacy email verification or fall back to JSON.
**Rationale**: old rolling instances ignore new locks; stale source files/backups could resurrect purged credentials. Existing purge is marker-first/user-last. Preserve unknown legacy fields, not just typed projections.
**Alternatives**: rolling auto-import/dual-write creates split authority. Old-image rollback after new writes loses state; ordinary rollback must use SQLite-capable code.

## R3 — maintained free JOSE

**Decision**: existing httpx/cryptography plus narrowly scoped joserfc; fixed endpoints/JWKS, exact RS256 login claim profiles. Google upstream S256; Apple confidential code exchange with ES256 client-secret and RS256 assertion.
**Rationale**: Authlib JOSE is deprecated in favor of joserfc. Application-owned durable attempts remain necessary. Apple current discovery/docs omit PKCE; claiming it works would be inaccurate.
**Alternatives**: Authlib OAuth helpers remain free BSD-3-Clause but do not replace attempt/session policy; deprecated authlib.jose or handwritten JWT crypto are unnecessary.
**Sources**: https://docs.authlib.org/en/latest/upgrades/jose.html ; https://jose.authlib.org/en/guide/jwt/ ; https://authlib.org/pricing/ ; https://appleid.apple.com/.well-known/openid-configuration ; https://developer.apple.com/documentation/signinwithapplerestapi/generate-and-validate-tokens .

## R4 — callback evidence plus initiating-client verifier

**Decision**: web callback requires original short-lived HttpOnly/Secure/SameSite=None binder; application cookie stays Lax. Native Google broker uses web client/server upstream verifier, app completion verifier and callback-delivered one-use <=60-second grant. No poll-only completion. Native Apple submits its returned assertion/code over POST.
**Rationale**: attacker can start an attempt and induce another browser to approve it; ready status+original verifier lets attacker finish. Additional artifact delivered only through returning callback prevents this. Apple form_post cannot rely on the Lax app cookie.
**Alternatives**: direct Google public iOS client is possible but adds registration/scheme and current redirect-smoke requirements. Broker with grant is compatible with already registered HTTPS callback and BrainBuddy scheme. A later bridge checking only original binder lacks returning-browser evidence.
**Sources**: https://developers.google.com/identity/protocols/oauth2/native-app ; https://developers.google.com/identity/openid-connect/openid-connect ; https://developer.apple.com/documentation/authenticationservices/aswebauthenticationsession .

## R5 — mailbox authority differs from stable subject

**Decision**: stable provider subject resolves existing binding; email never auto-links/rewrites account. New verified Gmail/signed valid Workspace hd may establish mailbox; external Google addresses require actual mailbox code before any durable claim. Legacy addresses require current password authority plus proof.
**Rationale**: Google explicitly warns email_verified alone does not prove current third-party mailbox ownership. Creating a durable unverified provider claim can squat another person's address. Retroactive legacy verification introduces access through possible typos.
**Alternatives**: email-match linking and blanket verified=true migration create takeover routes.
**Source**: https://developers.google.com/identity/sign-in/ios/backend-auth .

## R6 — durable bounded mail/budgets

**Decision**: neutral public acceptance + separate sealed once-only dispatch; keyed code HMAC; high-entropy proof hashes; persistent challenge/address/client/network budgets. Commit failed guesses before raising; do not reset/refund on resend/restart/failure.
**Rationale**: six-digit plain hash is offline-enumerable; transaction rollback can undo counters; eligible-only synchronous SMTP exposes timing/errors. Uncertain dispatch must not create usable proof or automatic duplicate mail.
**Alternatives**: in-memory/IP-only limits reset and fail distributed guesses; blindly retried SMTP can spam. Owner SMTP/free quota avoids auth SaaS.

## R7 — additive isolated native finalizer

**Decision**: new modern attempt methods with fail-closed protocol defaults; in-memory candidates, current attempt+immutable owner/server validation before live Keychain/document commit. Preserve Mac legacy password method; iOS modern password alternative uses stricter finalizer.
**Rationale**: APIClient.exchange installs Set-Cookie before status/body validation. SyncEngineSessionTests.switchesAccountsWhenNothingWaits deliberately permits legacy empty-outbox switching, whereas new iOS attempts require explicit sign-out. Apple-only APIs stay in host for Linux builds.
**Alternatives**: breaking shared signature conflicts with Mac021; using live token store for candidates risks wrong-owner sync and cancellation overwrite.

## R8 — owner-bound native account links

**Decision**: configured web-origin `/settings/account` and `/settings/account/delete`, nonsecret expected_owner, explicit same-account browser proof before action. No credential transfer; keep native outbox.
**Rationale**: browser B/native A otherwise acts on B; sessions cannot be in URL. Apple permits direct deletion completion-page link, not generic homepage/support.
**Source**: https://developer.apple.com/support/offering-account-deletion-in-your-app/ .

## R9 — bounded Apple grant/notification lifecycle

**Decision**: AEAD minimum per-client revocation grant, fixed retry/purge expiry, local authority independent of remote success. Atomic notification replay/effect, separate notification profile, current account-deleted spelling; optional exp. Compare authorization generation/event time; no automatic BrainBuddy erasure.
**Rationale**: returning Apple may omit email/name; issuer/client grouping matters. Old cleanup or delayed notices cannot destroy a newer grant. Unavailable Apple cannot justify indefinite personal-data retention.
**Alternatives**: ID-token-only verification cannot support grant revocation; unconditional notification exp rejects documented examples; broad subject-only delayed revocation ignores new consent.
**Sources**: https://developer.apple.com/documentation/signinwithapplerestapi/revoke-tokens ; https://developer.apple.com/documentation/technotes/tn3194-handling-account-deletions-and-revoking-tokens-for-sign-in-with-apple ; https://developer.apple.com/documentation/signinwithapple/processing-changes-for-sign-in-with-apple-accounts ; https://developer.apple.com/help/account/capabilities/configure-private-email-relay-service/ .

## R10 — compatibility/logging/operators

**Decision**: additive modern endpoints; old password/session/management shapes preserved, email updates clear mailbox authority. Update stale API compatibility document's native-client facts and own API version independently of storage. Redact actual uvicorn/nginx callback logs. Reserved configuration cannot elevate old social/email session.
**Rationale**: middleware logs path only, but access logs still include query codes/state. Existing tests count JSON files or edit already-constructed index; unchanged tests could pass vacuously after migration.
**Alternatives**: silent legacy status changes break consumers; middleware-only redaction misses actual leakage; mock provider smoke cannot prove configured launch.
