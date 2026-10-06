# HTTP contract: modern authentication

All routes are under the configured `/api` prefix. Existing cookie name, HttpOnly flag, opaque random-token authority, max age, production Secure and SameSite=Lax remain. No bearer-session replacement. Existing login/logout/me and invite signup request/response fields retain meaning/types/statuses. New completion returns an envelope; its `user`, when present, has the existing MeResponse fields.

## Common rules

- Fixed configured HTTPS public app origin, callback destinations and Apple native App/Services IDs; never trust Host/request-provided audience/redirect to choose authority. No wildcard/open redirects.
- JSON state-changing endpoints reject non-JSON and cross-origin browser requests. When Origin is present it must exactly match the configured frontend origin; reject cross-site/same-site foreign Sec-Fetch-Site. Native requests without browser metadata still require their session/proof/verifier. CORS does not allow foreign credentialed/custom-header requests. Apple signed form_post is the narrowly validated exception.
- Client creates a 32-byte random verifier; only S256 challenge persists. Secret verifier/email code/password/recent/reset proof stays in active client memory (web provider verifier may use a ten-minute tab-scoped sessionStorage entry, removed on terminal outcome), never in query/history/logs. Only upstream authorization codes and the <=60-second verifier-protected callback handoff code use the explicitly described callback URLs; clear the web fragment immediately and never log it.
- Errors use ErrorResponse (`message`, optional `detail`, `reference_id`) plus X-Correlation-ID. New safe `detail.code` discriminates invalid_proof, rate_limited, reauth_required, owner_mismatch, last_method, method_unavailable and conflict without public account existence. Validation errors must not echo secret input. Declare every intentional status in OpenAPI.
- Owner-restricted account, attempt, challenge, proof and binding lookups return indistinguishable 404 for nonexistent or foreign resources before disclosure/mutation. An expected_account_id that differs from the acting account also returns this same 404 without looking up the named account. Failed recent confirmation of the caller's own account and browser-origin rejection use 403; they are separate from foreign-resource access. Public invalid credentials remain neutral.
- Auth responses/callbacks: Cache-Control:no-store and Referrer-Policy:no-referrer. User cancellation never mutates local/native ownership. Callback URLs and query code/state/handoff are redacted in nginx and uvicorn as well as application logs.

## Discovery

`GET /auth/methods?client=web|ios` → 200: password available, method availability per channel, safe web_account_origin and public display metadata. No secrets, operator list, internal provider configuration or stored email eligibility. Google iOS uses the configured web broker; Apple native additionally requires approved native audience. Missing/invalid configuration hides that method; existing password remains. Configuration is not a member feature flag or authorization.

## Email and recovery

| endpoint | request | success | declared failures |
|---|---|---|---|
| POST /auth/email/request | email, purpose, client_challenge, client; optional expected_account_id/action/recent_proof/provider_attempt_id as required by purpose | 202 challenge_id/expires_at/resend_at + neutral message | 400,401,403,404,409,422,429,503 |
| POST /auth/email/resend | challenge_id, client_verifier | 202 same challenge + actual current expiry/resend time | 400,401,403,404,422,429,503 |
| POST /auth/email/verify | challenge_id, six-digit code, client_verifier; recent_proof when renewing pending sensitive action | 200 typed completion | 400,401,403,404,409,422,429,503 |
| POST /auth/recovery/reset | reset_grant, client_verifier, new_password | 204; all old sessions/proofs revoked, no automatic login | 400,401,403,404,422,429,503 |
| POST /auth/confirm/password | current_password, intended action, expected_account_id | 200 recent_proof/expires_at | 400,401,403,404,422,429,503 |

Purposes: login/recover/verify_email/change_email/reauth/provider_mailbox. All are immutable and origin/client-bound; protected purposes require the acting cookie session and exact owner/version/action. Recover is only for a verified address with an existing usable password, excluding operator addresses. Verification of a legacy address requires current password authority, then mailbox proof. Change_email binds the intended destination and recent same-account action.

Public login/recover requests use identical 202 shape/timing for eligible/ineligible addresses; request only reserves/enqueues, never waits for SMTP. Ineligible inert challenge cannot issue proof/session or disclose eligibility through polling. Dispatch failure never activates a usable code; public non-arrival guidance is neutral. Global known configuration unavailability may return the same 503 to every address. Authenticated own-address verification may expose safe delivery failure. No plaintext code response, test backdoor or automatic mail retry.

Code <=10-minute outer challenge lifetime, <=5 challenge guesses, >=60-second resend. Persist shared address/client/network budgets described in data-model. Resend invalidates previous code without resetting guesses or extending outer cap; actual expiry is returned. Failed guesses commit before error; delivery budgets are not refunded.

Completion outcomes: signed_in (cookie + user + deletion_cancelled); verified_email/changed_email (same account metadata); reset_ready (one-use client-bound <=10-minute reset_grant); reauthenticated (one-use <=5-minute recent_proof). Only signed_in may create an application session. Provider-mailbox verification finalizes the original staged attempt atomically and returns signed_in, or existing_account_required if a fresh uniqueness check finds a collision; it does not emit an intermediate provider_mailbox_verified result or ask for the consumed handoff again. All finalization fresh-checks account/version/deletion/reservations; absent previously known owner never becomes a signup fallback.

## Providers

| endpoint | request/behavior | success | declared failures |
|---|---|---|---|
| POST /auth/providers/{google|apple}/start | purpose login/link/reauth, client web/ios, client_challenge; optional action/expected owner/recent proof | 200 attempt_id/state/nonce + authorization_url where browser flow applies | 400,401,403,404,409,422,429,503 |
| GET /auth/providers/google/callback | provider code/state; validate exact attempt and web binder when web channel | 303 fixed web/native completion destination | 400,403,404,409,429,503 |
| POST /auth/providers/apple/callback | bounded form_post code/state/id_token; validate exact web binder/attempt | 303 fixed web completion destination | 400,403,404,409,422,429,503 |
| POST /auth/providers/complete | attempt_id/state/handoff_code/client_verifier | 200 typed completion | 400,401,403,404,409,422,429,503 |
| POST /auth/providers/apple/native/complete | attempt_id/state/authorization_code/identity_token/client_verifier | 200 typed completion | 400,401,403,404,409,422,429,503 |
| POST /auth/providers/apple/notifications | bounded JSON payload signed JWS | 204 authentic duplicate/unknown-subject/event ack | 400,401,422,429,503 |

Provider start fixes audience/channel/purpose from server config. Link/reauth record live acting session and immutable owner; link requires fresh intended-action confirmation. Native Apple receives raw random state/nonce for its active controller, which passes them unchanged to Apple; server verifies the same nonce (no undocumented hash transformation). Web response cannot sign in another acting account during linking.

Google: upstream authorization code + server-generated S256 verifier; scope openid email, no access_type=offline. Native broker redirects to registered HTTPS callback then fixed `brainbuddy://auth/callback?attempt=...&state=...&grant=...`. Web goes to fixed `/auth/complete#attempt=...&state=...&grant=...`; clear fragment after parsing. Callback delivers a new 256-bit handoff code, stored only hashed, <=60 seconds; finish requires that code AND original client verifier. No poll/status endpoint returns it or can authorize without it. Interception/sharing alone cannot redeem. Upstream verifier is sealed temporarily until exchange/terminal cleanup.

Web binder is dedicated HttpOnly/Secure/SameSite=None, scoped to provider routes and <=10 minutes. The callback must match it; never weaken the application session's Lax policy. Native broker does not pretend to have a web binder; returning callback grant plus active native state/verifier provides completion binding.

JWT profile: fixed known JWKS URLs; RS256 only; recognized Google issuer aliases normalized to one namespace, exact expected aud/azp, nonempty bounded sub, required exp/iat/nonce, clock skew <=60 seconds. Apple issuer exactly https://appleid.apple.com, audience selected by original web/native channel. Reject none/HS/mismatched key/header URL/malformed booleans. Cache JWKS <=1 hour; unknown kid causes at most one throttled refresh/minute and fails closed, never unbounded attacker-directed fetching. Provider exchange timeout 10 seconds; no blind retry of consumed authorization code.

Apple: server-generated short-lived ES256 client-secret (team iss, issuing client sub, Apple aud, key ID); every native code is exchanged. Native original assertion and exchanged subject/audience/nonce must agree. Web Services and native App ID grouping is deployment evidence before cross-surface namespace linking. No raw assertions/access-token history persists; only minimum AEAD-sealed revocation grant per issuing client/generation. First-login name is optional untrusted profile input; missing email/name on returning bound subject is valid.

Mailbox-required edge: the first valid provider completion consumes the callback handoff (or native Apple proof), records validated provider claims only in the <=10-minute attempt, and enqueues a provider_mailbox challenge bound to that attempt, provider-supplied destination and the original client challenge. verify_mailbox includes challenge_id/expires_at/resend_at, with no durable user/binding/address claim. Email verify checks the same client verifier, original attempt expiry and staged assertion evidence, consumes challenge and attempt once, rechecks uniqueness/operator/purge rules, then creates the account/binding/session together and returns signed_in. The 60-second callback grant is not needed after this transition, cannot be reused and has no polling authority.

Typed outcomes: signed_in; linked (same current account); reauthenticated; verify_mailbox (client-bound challenge, no user/email claim/session yet); existing_account_required (D/M-06, never merge by email). Returning binding uses stable subject only and never changes account email. New Google verified external email without authoritative Gmail/valid signed hd requires actual mailbox proof before durable creation. Reserved operators cannot provision/link/recover/login through these methods, including pre-existing bindings/sessions after configuration changes.

## Additive account management

`GET /account/auth-methods` → verified email/delivery state, usable connected methods and safe connection dates; no raw subject/token/hash or credential. 401/404/503 declared.

| endpoint | body | result |
|---|---|---|
| POST /account/auth-methods/{provider}/unlink | recent_proof, expected_account_id | 200 methods + signed_out flag; revoke affected provider sessions; 409 if last usable method |
| POST /account/auth-password | new_password, recent_proof, expected_account_id | 204 add/change password; keep validated acting session, revoke others |
| POST /account/auth-export | recent_proof, expected_account_id | 200 ZIP safe account-owned data; never put proof in URL |
| POST /account/auth-delete | recent_proof, expected_account_id | existing 202 deletion timestamps, all sessions/proofs revoked and caller cookie cleared |

Each declares 400/401/403/404/409/422/429/503 as appropriate, with specific declarations rather than catch-all; file export lists ZIP success and JSON error content. Current account must equal expected owner and recent grant's owner/session/action/version; another-tab cookie switch fails. Grant consume and mutation/revoke commit together. Email request/verify implements the additive verified destination-change flow.

Legacy /account/email/password/delete/export keep their existing wire contracts. Legacy password-authorized email update remains immediate but marks destination UNVERIFIED, invalidates old-address proofs/code authority and cannot claim reserved email. Modern web/iOS management uses new verified flow. Legacy export stays session-authorized; new sensitive UI uses recent-proof POST export. These compatibility paths confer no mailbox login/recovery authority from an unverified address.

## Apple notices/cleanup

Separate signed notification profile: fixed Apple issuer, configured grouped notification audience, RS256, bounded jti, integer iat/event_time, recognized event structure, <=7-day delivery age/future tolerance; validate exp when supplied (documented examples omit it). Atomic replay receipt+effect; valid duplicates/unknown subjects reveal nothing. Current event `account-deleted`, consent-revoked and relay email-disabled/email-enabled. A stale event cannot override a newer authorization generation; ambiguous equal events fail safely/request fresh authentication.

Revocation disables matching provider authority, originating sessions/proofs and clears grant; it does not erase BrainBuddy content/change email/grant another owner. Forwarding events affect only matching relay destination. Unlink/delete queue <=5 revokes in 24 hours, capped by purge; active cleanup lease serializes grant replacement and obsolete queued work is cancelled. Terminal/purge erases credentials even if Apple is unavailable. A new valid explicit login can cancel in-grace deletion; stale revoked proof cannot. Past-due never restores.

## Required negative evidence

Wrong issuer/aud/alg/key/nonce/state, foreign web binder, no returning grant, grant without verifier, wrong purpose/session/owner, double callback/consume, claim races/purge, external-email authority, legacy unverified recovery, operator configuration elevation, stolen callback URL, late native response, stale Apple notice/cleanup, secret-bearing errors/access logs/export and failed SMTP activation all receive explicit tests. OpenAPI/Schemathesis uses ephemeral app only; real provider configuration/smoke remains separate launch evidence.
