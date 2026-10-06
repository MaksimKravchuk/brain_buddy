# Proposed BrainBuddy CLI authorization contract

Additive endpoints under the configured api_prefix. Identity owns all grants and session creation. Existing login/me/logout cookies and schemas remain compatible. Shared provider sign-in, invite policy, account linking and deletion policy remain unchanged. This is a BrainBuddy device flow with existing session cookies, not a new OAuth token transport.

## Exposure and browser origin

Add runtime-managed cli_auth as optional pre-activation inventory, missing→OFF, preserving all five baseline required rows and migration markers/cohorts. Do not create its row/grants until successful compatible release establishes a recorded rollback floor; see contracts/rollout.md and proposed ADR0028. Unrelated writes/seed/upgrade/scrub must preserve optional absence. Only explicit post-release cli_auth mutation creates it. OFF returns 404 on start/browser routes/exchange. INTERNAL admits anonymous starts but browser request/decision and exchange require the effective flag for the authenticated owner. ON admits existing authenticated accounts. Flag checks never replace authentication/owner checks. Turning OFF blocks unconsumed grants but does not revoke already-issued sessions; existing logout/bulk revocation does that. The approval page reads /auth/me effective flags; no provider menu is duplicated.

Add validated BRAIN_BUDDY_CLI_VERIFICATION_ORIGIN: explicit HTTPS frontend origin (loopback HTTP allowed in development), with no credentials/path/query/fragment. This dedicated setting is the trusted browser Origin allow-list; no existing generic CORS configuration is assumed. Missing configuration makes start unavailable. Do not derive it from Host/Forwarded or reuse BRAIN_BUDDY_PUBLIC_BASE_URL: that currently addresses backend relay callbacks.

Verification URI is that trusted origin plus /cli/authorize. verification_uri_complete appends #user_code=XXXX-XXXX, keeping the code out of browser access-log query strings. Shared login return navigation preserves only a validated local pathname/search/hash; reject protocol-relative/external destinations. ProtectedRoute and the shared LoginPage preserve that local return destination. If parallel auth changes this seam, reconcile with its equivalent rather than implementing another sign-in screen.

## Endpoints

| Operation | Request and authorization | Result |
|---|---|---|
| POST /auth/device/start | Anonymous; empty JSON object only, fixed client label BrainBuddy CLI | 200: device_code, user_code, verification_uri, verification_uri_complete, expires_in:600, interval:5, protocol_version:1 |
| POST /auth/device/request | Existing browser session; JSON {user_code}; effective cli_auth and trusted Origin | 200: user_code in display form, client_name:BrainBuddy CLI, created_at, expires_at, state; identity comes from /auth/me |
| POST /auth/device/decision | Existing browser session; JSON {user_code,decision:approve\|deny}; effective flag and exact trusted Origin | 200: {state:approved\|denied}; repeats of the same decision are harmless, conflicting decisions return 409 |
| POST /auth/device/token | Anonymous private proof; JSON {device_code}; bounded polling | Pending/slow-down/denied/expired errors or 200 identity metadata and Set-Cookie for a distinct session |

Using POST for code lookup avoids access-log URLs with codes. Browser request/decision require Content-Type application/json and Origin exactly matching the configured frontend origin; absent/null/foreign Origin fails 403. SameSite cookies and CORS alone are insufficient CSRF protection. No state mutation occurs via GET/navigation. Never approve merely by opening verification_uri_complete. UI displays the signed-in account, code, fixed client label and expiry, with explicit Approve/Deny controls and warning to approve only a code shown by the user's own CLI.

Success token body: {account: existing MeResponse, credential_type:session_cookie, cookie_name: configured SessionSettings.cookie_name, expires_at: UTC timestamp}. Only Set-Cookie carries the new raw token, using existing HttpOnly/Secure/Path/SameSite policy. The polling response never sets or returns the approving browser's token. No credentials in response JSON, URLs, logs or committed evidence. CLI suppresses cookie headers from output and validates cookie origin/name/path/expiry before saving.

## Poll outcomes

All failures use existing ErrorResponse/correlation middleware with detail.code:

| HTTP | code | CLI action |
|---|---|---|
| 400 | authorization_pending | Wait at least interval; continue until the monotonic ten-minute deadline |
| 400 | slow_down | Add five seconds permanently; respect Retry-After if larger |
| 403 | authorization_denied | Stop; preserve existing local connection |
| 400 | authorization_expired | Stop; start a fresh login explicitly |
| 400 | invalid_device_code | Stop; no record or raw input reflection |
| 409 | authorization_consumed | Stop; new login required after lost response |
| 404 | cli_auth_unavailable | Stop; server capability/flag unavailable |
| 429 | rate_limited | Respect Retry-After within grant deadline |

First eligible poll occurs after the advertised interval. Connection timeout doubles the wait up to 60 seconds; no other automatic HTTP request retries. Ctrl-C stops polling and reports cancellation. Server epoch timestamps use UTC; CLI uses a monotonic bounded timeout from receipt, capped at 600 seconds. Pending/429 cannot extend grant expiry.

## Durability, revocation and bounds

Under SessionRepository.authorization_lock(), use a shared RLock and reentrant thread-local stable .auth-state.lock flock across cooperating processes. Wrap existing session create/delete/bulk revoke/expired-unlink methods. CLI approval and exchange hold the same outer guard over fresh grant/source-session/user checks and durable transition. No password hashing, HTTP, keychain interaction or task/tree handler runs under this guard.

Approve binds approved_user_id and approver_session_hash to the authenticated source session. Exchange rechecks that exact source session, same active user, no deletion marker, effective flag and expiry; durably marks consumed, calls existing session minting, then rechecks the source/user before releasing. If the final check fails, delete the newly issued session. Consume-before-mint means failure can require a fresh login; it guarantees at most one issuance, not replay of a lost secret. Source logout and user/admin/password bulk revoke cooperate through session mutation locking. After any decision binds approved_user_id, browser lookup/replay require that owner and the exact original approver session under the guard; foreign/missing/revoked-session lookups use the same opaque404. Pending grant possession may be approved by the explicitly displayed authenticated account; never change a decided binding. Hard purge removes account-associated grants under the guard, after the existing feature-flag privacy scrub succeeds and before user deletion; a deletion marker already blocks new approval/exchange. Existing signup/password/provider flows remain authoritative.

Private proof: 256 random bits; normalized user code: eight unambiguous Base32 characters. Store only hashes. Grants persist atomic JSON, become unusable at600 seconds in every state, and are removed by the next existing startup/periodic privacy sweep independently of exposure (default60s, configurable1–3600s). Downtime can delay physical deletion until startup, never grant validity. Also prune on start/lookup/exchange; cap 1,024 unexpired grants, fail 429 rather than grow. Scan live rows for code uniqueness/browser lookup under guard. Unknown codes allocate nothing. No second index or grant recovery token.

Start admission uses existing BoundedKeyRateLimiter: ten attempts/minute/source IP, max_keys:1024. Browser lookup/decision bad-code attempts: ten/ten-minutes/source IP plus authenticated user, max_keys:1024. Use the app's trusted source-IP convention; do not trust arbitrary forwarded headers. Also bound total starts to 120/minute/process and browser lookups to 120/minute/process so LRU churn cannot remove all admission protection. Rate state resets on process restart, matching current auth topology; durable grant count and per-grant next_poll_at remain cross-process bounds. Distributed auth storage/rate limits are not claimed.

New endpoints have strict1KiB bodies, never echo codes, and send Cache-Control:no-store. A narrow existing RequestValidationError handler branch for these four configured-prefix device paths emits fixed message/detail.code:invalid_request, correlation and no-store without Pydantic msg/loc/ctx/input; validation occurs before route functions. Other endpoints retain existing behavior. Secret-sentinel tests cover malformed JSON/types/lengths/extra keys/custom validator failures. Success/failure events log correlation ID, operation and coarse code only. No query-code, cookie, token, email or user content logging. Tests cover secret sentinels in persistence/output/errors.

No persistent quarantine: corrupt grant records are deleted safely under the guard, with coarse error/correlation logs only. Existing privacy maintenance/CLI purge cleanup runs even with cli_auth OFF and no new device calls. Export manifest/docs/data-retention.md explicitly exclude grants/verifiers as transient session-authorization security material; local CLI credentials/configuration are outside server export. Account-associated grant purge remains mandatory after flag scrub and before user deletion.

Browser lookup/decision fetches each have AbortController30s timeout; loading text appears immediately (Checking this code…/Sending your decision…). Controls stay disabled through request; expiry/uncertain failure never means approved. Focus/recovery behavior is in design.md D-03 B02–B09.

## Credential lifecycle in bb

Preflight the selected store before starting login. Default native-store login never falls back silently. Unix --store file explicitly selects an owned regular file in a private 0700 directory, 0600 file, no symlinks, ownership/modes checked on every open and atomic same-directory replacement. Windows file mode fails as unsupported until actual owner-only ACL enforcement is implemented/tested; Credential Manager and explicit external secrets remain supported.

Business native reads must be noninteractive: Linux refuses locked collection/item through a native lock-status check and direct read without unlock; macOS suppresses Keychain interaction at the native API; Windows CredRead is noninteractive. A denial, locked store or bus failure returns credential_store_unavailable. Only explicit login can prompt for native-store interaction. Store persistence/read-back is tested across processes, and the keyring mock backend is never selectable.

Connection replacement requires explicit --replace if another account is already configured for that server. Save the new secret under a new locator, verify read-back, then atomically commit nonsecret metadata. Preserve the old locator until metadata is committed. On save/read-back/metadata failure, remove the new local secret and POST existing /auth/logout with the newly issued credential; report cleanup uncertainty if offline. Cancellation after issuance follows the same cleanup path. Never clear a working connection on denial/expiry.

bb auth status checks /auth/me without prompts and reports server/account/source/authenticated/expiry, never a cookie. bb auth logout attempts /auth/logout with only that session, clears the selected local locator/metadata, and reports local_cleared/server_revoked. Offline revoke failure exits nonzero while confirming local clearance; local clear failure is explicit. An environment credential is never claimed to have been removed from its external secret manager.
