# Data model: modern Identity authentication

One Identity-owned auth.sqlite3; account IDs remain all other-module owners. User/session indexed columns and preserved model JSON are derived/validated together in one row transaction, never separate authorities.

| record | fields and constraints | lifecycle/retention |
|---|---|---|
| users | immutable id PK; unique normalized email; preserved fields/JSON; password_hash string (empty means unset); nullable email_verified_at; monotonic auth_version | existing active → requested 14-day grace → irreversible past-due → purged; new explicit login cancels only in-grace |
| sessions | SHA-256 opaque token PK, user FK, created/expires, auth_version/method/confirmation time, optional provider binding | imported digest/expiry preserved as password session; invalidate on expiry/authority revoke; raw token only in issuing response/client store |
| provider_identities | binding ID/user FK; provider/recognized issuer/group namespace/stable subject UNIQUE; per-user provider constraint; state/times/generation; safe optional mail/relay metadata | no email auto-link; active/revoked; unlink/purge cleanup; new explicit consent may restore same owner's binding only |
| auth_attempts | random id, provider/intent/action/channel, expected owner/version/acting-session hash, client S256, hashed state/nonce/binder, configured audience/redirect label; minimal sealed upstream verifier/pending grant | <=10-minute outer cap; started → exchange lease → callback-delivered/mailbox-required → consumed, or failed/cancelled/expired |
| handoff | attempt FK, 256-bit grant digest, expiry, consumed flag | <=60 seconds; callback delivery only; requires initiating verifier; no grant/status polling |
| auth_challenges | random id, exact purpose/destination, related owner/version/session/action/attempt, client S256, keyed code HMAC/key ID, expiry/resend/failures/delivery/terminal state | <=10 minutes, <=5 guesses; inert public ineligible challenge indistinguishable but cannot authorize; resend does not extend outer cap/reset counters |
| auth_mail_jobs | challenge FK; sealed recipient/code/template payload with key ID/AAD; pending/leased/delivered/failed and deadline | once-only dispatch; activate code only on acknowledgment; uncertain crash fails, never auto-replays; erase payload immediately terminal or expired |
| auth_proofs | 256-bit proof digest; owner/version/session/client/action/provider generation, issued/expires/consume state | recent <=5 minutes; reset <=10 minutes; exact one-use purpose; consume with mutation/session changes in same transaction |
| auth_budgets | keyed address/client/network fingerprints; counter/window/resend/key ID/expiry | dispatch 5/20/50 per hour, failed guesses 10/30/100 per hour; >=60-second address resend; <=24-hour retention; old-key windows survive rotation |
| apple grants/jobs | account/binding/issuing-client/generation, sealed minimum refresh/access grant with AAD/key ID; bounded cleanup lease/retries/reason/expiry | active grant until unlink/purge; jobs <=5 attempts/24 hours and capped by purge; terminal deletes credential even if remote unavailable |
| apple_notification_receipts | hashed bounded jti+namespace, event/subject fingerprint/generation/time, expiry | atomic replay receipt+effect; <=7-day event acceptance/future tolerance, optional exp; <=8-day receipt retention; no raw payload |
| migration ledger | schema/import/cleanup checkpoints/counts/nonsecret validation digests | import once; never reimport originals after commit; encrypted backup <=24 hours or immediately erased on any account purge |

## Authority invariants

- Normalization remains strip/lower, not dot/plus/provider rewriting. Preserve unknown legacy model fields; import mailbox verification as null, version zero. Do not store known dummy password hash for passwordless accounts.
- Shared store is injected into user/session/metadata facades; nested calls reuse the transaction. BEGIN IMMEDIATE, unique constraints and foreign keys handle real two-connection/process races. Network never runs under writes.
- Fresh-check account/version/session/deletion/current reserved configuration, consume proof, mutate intended authority and create/revoke sessions atomically. Stale known-account proof never falls through to signup after purge. Invalid guesses commit increments before error response.
- Unset/invalid password hashes execute the same Argon2 dummy-cost verification work as an unknown account, then reject unconditionally. Dummy hash/password is never stored as a usable account credential; deterministic hasher-call/session assertions cover the comparison.
- Password verify/hash runs outside lock; commit confirms exact checked credential/version. `save` updates existing accounts only. Name edits preserve verification; email/credential changes advance version/invalidate affected proofs. Legacy/admin email update clears verification; admin cannot remove last usable method.
- Returning subject is authority; mutable provider mail/name is metadata. New third-party Google mail has no durable address claim until mailbox proof. Subject/email collision requires existing-account login plus a fresh explicit link.
- Application session lookup denies external methods for currently reserved operators; their password path remains. Unlink/revocation invalidates originating provider sessions. Recent proof must remain current through final action.
- Apple jobs bind issuing client and generation. New generation waits for active cleanup lease and cancels obsolete queued work; stale notifications cannot end newer consent. Signed revocation disables affected authority, not BrainBuddy content. Relay delivery events affect only matching subject/address.

Mailbox-required attempts consume the original handoff once at staging, then retain only bounded validated claims and their original client challenge. The provider_mailbox challenge verifies that exact destination; successful verification consumes both records and atomically returns signed_in, or a safe fresh collision outcome. No expired/consumed handoff is reused and the original attempt deadline is not extended.

## Email/queue details

Purposes are immutable: login, recover, verify_email, change_email, reauth, provider_mailbox. Public eligibility/delivery is never exposed through response/status. Authenticated own-address failures may be shown. Resend retains challenge/shared guesses, supersedes previous code and cannot let an old dispatch activate its replacement. Actual server expiry is displayed.

Legacy verification requires current password authority plus code. Modern destination change keeps old address until both current-account and new-mailbox proofs commit. Recovery emits a client-bound reset grant and never bypasses native owner finalization. Action-specific grants cannot become login or another sensitive purpose.

## Export/erasure

Export safe account, verification and binding personal metadata, including stored non-authorizing provider subject identifiers in the owner's archive; these are not public method-discovery fields. Exclude passwords/hashes/session tokens, code/proof/PKCE/nonce/binder material, sealed credentials and budget fingerprints. Marker-first/user-last purge removes all account-owned new records/jobs, source credential copies and entire temporary backup. Unknown/public abuse fingerprints expire on their bounded schedule.

Enable SQLite secure_delete and bounded WAL checkpoint/truncation after credential/privacy cleanup, retrying busy checkpoint. This reduces DB remnants; it is not a promise of forensic deletion from platform snapshots, other module stores, logs or native caches. New source directories never become a fallback authority.
