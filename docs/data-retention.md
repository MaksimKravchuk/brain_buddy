# Data retention & GDPR operations

What Brain Buddy stores per user, how long it keeps it, how the self-serve
data rights work mechanically, and the small manual checklist that keeps the
operation GDPR-compliant. The user-facing summary of all of this is the
in-app privacy policy (`frontend/src/pages/PrivacyPolicyPage.tsx`, served at
`/privacy`) — keep the two in sync.

## Retention schedule

| Data | Where | Retention | Enforced by |
|---|---|---|---|
| Account record (email, display name, Argon2id password hash, mailbox verification) | `data/auth.sqlite3` for new or explicitly migrated roots; legacy user JSON/index only before the stopped-writer migration | Life of account + 14-day deletion grace | Account purge (below) |
| Sessions (opaque token hashes, never the raw cookie) | `data/auth.sqlite3`; legacy session JSON only before migration | 30 days, or logout / revocation | Lazy delete on read; bulk revoke on password change & deletion |
| Connected Google/Apple identities (stable provider identifier, minimal email/profile metadata and connection state) | Identity-owned `auth.sqlite3` tables | Active connection lifetime. Explicit Remove ends its authority and erases profile metadata; Google mapping is deleted immediately. Apple retains only minimal disconnected linkage while bounded revocation settles, at most 24 hours and never beyond account purge | Explicit unlink / Apple cleanup / metadata expiry sweep / account purge (spec 023) |
| Sign-in attempts, email challenges and pending mailbox addresses | Identity-owned `auth.sqlite3` tables | At most 10 minutes; consumed records cannot grant authority | Single-use consume / expiry sweep / owner invalidation and purge |
| Recent-confirmation, password-reset and callback proofs | Identity-owned `auth.sqlite3` tables | Recent confirmation 5 minutes; reset 10 minutes; handoff 60 seconds; single use and bound to owner/session/action or client proof | Atomic consume / expiry sweep / owner invalidation and purge |
| Sealed email-delivery payload (recipient and code) | Identity-owned `auth.sqlite3` mail jobs, encrypted at rest | Pending only within the challenge's 10-minute lifetime; erased after confirmed delivery, terminal failure or expiry | Delivery worker / metadata expiry sweep |
| Abuse-prevention fingerprints (keyed digests of address/source, counters; no raw address in the budget table) | Identity-owned `auth.sqlite3` budgets | At most 24 hours | Metadata expiry sweep |
| Protected Apple revocation credential and cleanup linkage | Identity-owned `auth.sqlite3`, encrypted at rest | Minimum revocation credential while connected; after unlink/deletion, at most 5 attempts within 24 hours, capped by account purge. Explicitly unlinked personal mappings and associated receipts are erased when cleanup settles or expires | Apple cleanup lease/generation checks / metadata expiry sweep / account purge |
| Verified Apple notification replay receipts (event ID digest, subject fingerprint and coarse event/time; no signed notification body) | Identity-owned `auth.sqlite3` receipts | At most 8 days; associated receipts also removed with explicit unlink cleanup or account purge | Replay expiry sweep / binding cleanup / account purge |
| Encrypted legacy-auth migration backup | Identity migration artifacts, restricted file permissions | At most 24 hours; any account purge removes the entire backup, so it cannot restore erased accounts | Stopped-writer migration cleanup / startup expiry / account purge |
| Trees, versions, AI validation history | `data/<tree_id>/…` + `data/index.json` | Life of account | Account purge |
| Tasks, projects, tags, subtasks, comments | `data/tasks.sqlite3` + JSON mirrors (`tasks/`, `projects/`, `contexts/`, `task-subtasks/`, `task-comments/`) | Life of account | Account purge |
| Task idempotency records | `tasks.sqlite3` + `task-commands/` mirrors | 24h rolling (`purge_expired_idempotency`), all on account purge | Maintenance sweep / purge |
| **Weekly review records** (spec 020): review settings (threshold, review day, review time and the IANA **time zone**, the activation instant), review sessions (counts, active seconds per step, ids only), decisions (type, stall-reason code, AI-use code, and the **reason text** of a "keep 7 more days"), receipts, park acknowledgements, bulk releases (ids and codes), navigator consents; plus the formulation-clock fields on each task (inside the task row, incl. an open extension's reason) | `tasks.sqlite3` tables `review_settings`, `review_sessions`, `review_decisions`, `review_receipts`, `review_park_acks`, `review_bulk_releases`, `navigator_consents` (SQLite only, no JSON mirror) | Life of account | Account purge (`TaskRepository.delete_all_for_owner` deletes the review tables first, in its lock) |
| **Weekly review undo and bulk-release snapshots** (a decision's `undo` copy of the task as it was — title, notes, clock — and a bulk release's per-task `clock_before`, which can hold an extension reason) | Inside the `review_decisions` / `review_bulk_releases` rows | 7 days; longer only while the backend is rolled back to a build without the review sweep (the first sweep after roll-forward nulls every snapshot older than 7 days). The retention runs for every owner with review rows whatever the `weekly_review` flag state | Review maintenance sweep (`ReviewService.run_review_retention`) / purge |
| Weekly review navigator usage counters (per owner and UTC day: calls, estimated and reserved cost, requests that showed a proposal; no content) | `tasks.sqlite3` table `navigator_usage` | 35 days, whatever the flag state | Review maintenance sweep / purge |
| **Weekly review navigator input as received by the cloud provider** (spec 020, one copy per suggestion request: the task title, its notes reduced to at most 6 000 characters, the stall-reason code, the project name and up to 20 other open task titles of that project — sent **as written**, so names or other details of other people in notes and titles are included; nothing is redacted) | The provider (OpenAI API), not Brain Buddy. Brain Buddy keeps neither the input nor the proposals: no idempotency record, no `task-commands/` entry, no log text — only the usage counters above, the owner's consent row, and on a later decision the `ai_use` code and `navigator_request_id` | The provider's own policy: up to 30 days for OpenAI API data (abuse monitoring) | **Not reachable by account purge**: see "The navigator's provider copy" below |
| CRT mutation idempotency receipts (owner/key, route/request fingerprint/status plus the canonical response needed for replay; no raw key) | `data/crt_commands.sqlite3` | Canonical response body exactly 30 days after commit; after expiry, the body and pending snapshot are redacted but an owner-scoped, content-free key/route/request-fingerprint tombstone remains until account purge. Normal tree deletion redacts prior content-bearing receipts and retains the content-free delete tombstone; account purge physically removes every receipt; pending commands reconcile before the 30-day response clock starts | CRT command maintenance sweep / confirmed-delete cleanup / account purge (ADR-0026) |
| Voice operations (transcripts, consent records) | `data/voice_operations.sqlite3` + `brain-dump-operations/` mirrors | Life of account; uncommitted working artifacts 7 days | Sweep (`purge_expired_working_artifacts`) / purge |
| Raw voice audio | `data/brain-dump-media/<owner>/…` | 24 hours after processing (`BRAIN_BUDDY_VOICE_RAW_AUDIO_RETENTION_SECONDS`), or immediate user deletion | Sweep (`purge_expired_raw_audio`) / in-app "Delete raw audio" |
| **External-agent relay content** (the hand-off manifest the user confirmed — Task title, details and the supporting items they kept — plus the agent's progress, question, result and failure text, the blocked reason, artifact summaries, result availability and status text, reply/cancel command bodies, and timeline event summaries) | `data/agents.sqlite3` (SQLite only: this module deliberately writes no JSON mirror) | 30 days from dispatch (`BRAIN_BUDDY_AGENT_CONTENT_RETENTION_SECONDS`, which the settings model refuses to raise above 30 days) | Sweep (`expire_due_content`) / purge. Every read projects a due run as expired first, so the content is already unreachable when the sweep gets to it |
| **External-agent relay identifiers** (the agent's task ids, Brain Buddy's message ids, the interface address recorded at dispatch, the agent-card fingerprint, the push-token fingerprint, and the run's observation event rows) | `data/agents.sqlite3` | 90 days from dispatch. **Not** the run id: the run id *is* the run's correlation ID — the conversation identifier on the wire and part of the push callback address the agent holds — so it stays with the run row as coarse metadata until account purge. We say that rather than pretend to erase it | Sweep (`expire_due_identifiers`) / purge |
| **External-agent relay audit entries** (connect, test, hand-off, observation, push and disconnect outcomes: ids and coarse outcome codes, never relayed content, never a credential or token) | `data/agents.sqlite3` | 90 days | Sweep (`purge_expired_audit`) / purge |
| **A connected agent's discovered card summary and its fingerprint** (the agent's name, version, description, skill names and descriptions, offered authentication schemes, and interface address) | `data/agents.sqlite3`, on the connection row | The connection's lifetime. This is connection configuration, not run content, so no sweep touches it | `disconnect_connection` erases it together with the credential, so a disconnected connection no longer describes where it pointed / purge |
| Invites | `data/invites/<code>.json` | Indefinite, but `used_by_user_id` is scrubbed to `"deleted-user"` on account purge | Purge (`InviteRepository.scrub_user`) |
| Runtime feature-flag rollout store (flag modes plus the **account ids** an operator selected — no email, display name, credential or member content) | `data/feature_flags.sqlite3` | Life of the deployment; an account's id is removed from every cohort on account purge | Purge (`FeatureFlagOverrideRepository.scrub_user`) |
| Server logs (correlation IDs and bounded content-free operation metadata; CRT may include opaque tree id, revision, outcome, error code and duration; never graph text or request/response bodies) | process stdout / Fly logs | Fly's log retention | Platform; application purge cannot erase platform logs |
| **Admin access records** (an operator looked up, or revoked sessions for, one account; or changed a runtime feature flag's mode, cleared its override, or added or removed one selected account; or read the flag list, resolving its cohorts: operator account id, resolved target account id where the operation names one, flag name, action, outcome, and per-read flag and resolved-account counts — no email, display name, or request body) | process stdout / Fly logs | Fly's log retention | Platform |
| Mobile pending classification queue (task, project and tag **ids**; Expo client, removed 2026-10 — builds already installed only) | device `AsyncStorage`, key `bb.pendingClassification.<server>.<account>` | 30 days from last edit, or immediately on a deliberate identity transition | Mobile client sweep across all stored identities (spec 006, FR-011/FR-018) |
| Mobile cached project and Tag lists (user-authored **names**; Expo client, removed 2026-10 — builds already installed only) | device `AsyncStorage`, key `bb.classificationCache.<server>.<account>` | 30 days from last fetch, or immediately on a deliberate identity transition — including when the queue is empty | Mobile client sweep (spec 006, FR-011/FR-018) |
| Web last-used agent preference (connection **id** and confirmation timestamp only; no Task content, address, or credential) | browser `localStorage`, key `bb.taskAgent.lastUsed.v1.<server>.<account>` | Eligible for 30 days from last confirmed hand-off; removed on sign-out/identity transition, invalid eligibility, and by a cross-identity startup/focus/interval sweep after expiry | Web preference lifecycle binding (spec 017, FR-008/FR-017) |
| CRT unsynchronized drafts (user-authored graph/layout content, immutable in-flight save snapshot, queued commands and idempotency-key UUID) | browser `localStorage`, namespaced by origin/account/tree or pre-canonical create attempt | Eligible for 30 days from last edit/use; on next startup/focus/interval after expiry the stale draft stays outside the canvas and offers backup, recover (resetting the clock), or discard; all departing-owner keys on the active origin are removed after the pending-work decision on sign-out/account switch/account deletion | Web CRT recovery lifecycle (spec 019, FR-018–FR-020) |
| Weekly review web form drafts (unsaved decision-form text: new wording, first step, waiting-for, extension reason) | browser `localStorage`, key `bb.reviewFormDraft.v1.<origin>.<account>.<task>.<formulation>` (`project.<project id>` for a project's next action) | Removed on save, discard, formulation change, sign-out or account switch, and by a startup/focus sweep after 7 days; never sent to the server or logged | Web review draft lifecycle (spec 020, FR-052, data-model E11) |
| Weekly review web keys without content (`bb.reviewWywaLastShown.v1.<origin>.<account>`: the local day "While you were away" was last shown; `bb.reviewLastZone.v1.<origin>.<account>`: the IANA zone this browser last observed) | browser `localStorage` | Removed on sign-out or account switch | Web review lifecycle (spec 020, data-model E11) |
| CRT last-tree preference (owner id, tree id, origin and last-use timestamp; no graph content) | browser `localStorage`, namespaced by origin/account | 30 days from last use; removed by startup/focus/interval expiry sweep and with all departing-owner CRT keys on same-browser identity transition | Web CRT preference lifecycle (spec 019, FR-003/FR-020) |
| **iOS app store document** (the user's working copy: tasks with notes, due dates, waiting-for, subtasks and comments; projects and tags; pending changes not yet sent, with their idempotency keys; sync issues with the server's message and reference id; the linked account's id, email, display name and server address) | iPhone/iPad, one JSON file in the app's App Group container (`BrainBuddyPersistence`), file protection `completeUntilFirstUserAuthentication`; included in device backups | Until sign-out deletes it, or "Start fresh" sets an unreadable one aside (next row). **Kept through a 401** ("Sign in again to sync"), so an expired or revoked session never loses unsent changes. With no account ("On this iPhone"), until the app is deleted | iOS client sign-out (`docs/native-ios-app.md`) |
| **iOS quarantined store files** (a store document the app could not read, set aside as `<name>.unreadable-<UTC timestamp>.json` with whatever it held) | Same App Group folder, same file protection; included in device backups | Until sign-out removes them, or the app is deleted | iOS client sign-out |
| **iOS recent searches** (up to 8 search queries, which can quote words from tasks) | app `UserDefaults.standard`, key `search.recentQueries`; included in device backups | Until sign-out clears them, or the app is deleted | iOS client sign-out |
| **iOS store document: weekly review state** (spec 020, inside the store document above: review settings incl. the time zone, decisions with their 7-day undo snapshots, extension reasons, review sessions, navigator consent state, unsaved decision-form drafts, the last observed device time zone, auto-park bookkeeping) | Same App Group store document (`StoreDocument` v2) | Undo and bulk-release snapshots, idle sessions and form drafts 7 days (`runLocalReviewMaintenance`, signed in or account-less); the rest as the store document; drafts and the last observed zone also go on sign-out | iOS client local review maintenance / sign-out |
| iOS list display options (sort, grouping, completed/cancelled visibility, priority and tag filters; keyed by list or by a local project/tag id; no names or task text) | app `UserDefaults.standard`, keys `listOptions.*` | Until the app is deleted; not tied to an account | None needed: preferences without content |
| **iOS session token** (the opaque `brainbuddy_session` cookie value, one per server host) | Keychain generic password, service `app.brainbuddy.session`, `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`: never restored to another device from a backup or synced through iCloud Keychain; the app's own, no keychain sharing with the widgets | Until sign-out or the first 401 (session expired or revoked server-side), whichever comes first. Keychain items can outlive deleting the app, so a launch with no linked account removes any left over | iOS client (`KeychainSessionTokenStore`); the server-side session follows the Sessions row |

Apart from the navigator's provider copy (below), the device and browser rows (mobile,
web, CRT and iOS) are the only entries in this table an account purge cannot reach: the
server can revoke every session, but it cannot delete bytes on a phone or in a browser. The Expo mobile client's native sweep provides its
device stores' 30-day physical bound as specified by feature 006; that client's source
was removed from the repository in 2026-10, so its rows describe only builds that were
already installed. The web preference becomes unusable at 30 days and its
cross-identity sweep removes expired bytes whenever BrainBuddy next starts, regains
focus, or reaches its sweep interval. CRT drafts likewise become ineligible for automatic
application at 30 days and require the one stale-recovery decision when the app next runs.
If BrainBuddy is never run again, the user must
clear BrainBuddy site data in the browser to remove those residual local bytes; the
server cannot honestly do that. The mobile and browser stores are unencrypted at rest
and may be captured by device backups — see spec 006's Assumptions for the native stores.

The iOS rows have no 30-day bound, on purpose: the app is offline-first, so its store is
the user's working copy, not a cache. Once an account deletion revokes its sessions, the
app's next request gets a 401 and its token is removed, but the store stays until the
user signs out, so changes made offline are never silently dropped. Deleting the app
removes the App Group files and its `UserDefaults`; only the Keychain token can outlive
that, and it stops working when its 30-day server session ends (a reinstalled app
removes it at launch). The store is encrypted at rest by iOS Data Protection, but
readable from the first unlock after a restart, and it is part of the device's iCloud or
computer backups.

One external-agent artifact is missing from the table because it is not ours to
delete: the **push callback address Brain Buddy registered with the agent**. It
embeds the run id and a per-run token, and the agent keeps its own copy. On
disconnect the credential that a deregistration call would need is destroyed
first, and on purge the run the registration names is gone, so neither can
recall it — it survives both by design and is disclosed rather than hidden. The
token stops verifying immediately in either case (after purge it verifies
against nothing, and the route answers one opaque rejection without creating a
durable row), and the hand-off review shows the external-copy notice before the
user confirms.

**The navigator's provider copy** (spec 020, contracts/navigator.md §6). The weekly
review's cloud suggestions exist to propose 1–3 next steps for a stalled task or a project
without a next action; nothing is written to a task until the person confirms. Each
request sends exactly the five FR-019 items above (title, notes, stall reason, project
name, up to 20 sibling titles) and nothing else, and only while the owner holds a current
consent: one row per owner and provider in `navigator_consents`, for the configured
provider and the current `CONSENT_TEXT_VERSION`, revocable at any time with
`DELETE /api/review/navigator/consent` (never gated by the `weekly_review` flag; the next
request is refused at once). Notes and titles go as written, including names of other
people (owner decision 2026-10-06). The provider keeps what it received under its own
policy — up to 30 days for OpenAI API data — and an account purge cannot reach that
copy; it is the one copy of this feature's content that survives purge by design, and
the privacy policy ("Weekly review suggestions") says so. On iOS, suggestions from
Apple's on-device model never leave the device.

## Account deletion lifecycle

1. `POST /api/account/delete` (password re-check) stamps
   `deletion_requested_at`, revokes every session, clears the cookie, and
   returns `purge_at = requested + grace`.
2. Grace period: **14 days** by default; override with
   `BRAIN_BUDDY_ACCOUNT_PURGE_GRACE_SECONDS` (used by the compose E2E stack).
3. A login inside the grace period clears the flag and reports
   `deletion_cancelled: true`; a login after it fails with the generic
   credential error — a past-due account is never resurrected.
4. The **maintenance sweep** (`_run_maintenance_sweep` in
   `backend/app/main.py`: one synchronous pass at startup plus a 60-second
   daemon-thread loop outside tests) calls
   `AccountService.purge_due_accounts()`. Manual/ops entrypoint:
   `python -m app.cli purge-due-accounts`.
5. `purge_account` first durably stamps `deletion_requested_at` (a
   non-destructive marker write that never overwrites an existing timestamp),
   then deletes in a crash-safe, idempotent order — runtime feature-flag
   cohort scrub → sessions → voice (SQLite rows, JSON mirrors, raw audio) →
   external-agent connections/runs → tasks (SQLite rows, JSON mirrors) →
   CRT command receipts → trees (directories incl. versions + validation, index entries) → invite
   scrub → **user record last**. The cohort scrub runs before every other
   destructive step, not after: it deliberately raises rather than skipping
   when the runtime flag store is degraded, so erasure is always
   complete-or-not-yet-started rather than silently partial. If the process
   dies mid-purge the marker and the rest of the account survive, the account
   stays past-due, and the next pass re-runs everything. One such account
   never blocks another's due purge.

   The authoritative runtime store is `feature_flags.sqlite3`; the legacy
   `feature-flags/runtime.json` document is retained on the volume only so an
   older image can still be rolled back onto it, and once the PII-free
   `feature-flags/sqlite-migration-complete.json` marker exists that document
   is never read again as a migration or runtime source, even if the SQLite
   file is deleted or recreated (the marker records only a migration id and
   timestamp — no account, email or environment value). Because a retained
   rollback artifact that still names a purged account would be a privacy
   leak, the cohort scrub also removes the account ID from that legacy
   document; failing to do so halts the purge before the user record is
   deleted, the same as a degraded SQLite store. A degraded SQLite store —
   unreadable, a missing row, or a row whose mode is invalid — likewise
   leaves every managed flag fail-closed OFF and blocks the destructive part
   of purge until an operator repairs it, retrying on every subsequent sweep
   pass.

Nothing user-identifiable survives a purge **in the data store**; consumed
invites keep only the `"deleted-user"` sentinel so they stay burned. The one
record about a person that a purge deliberately does not reach is the admin
access record described below — it is a log line, not a stored object, and
`purge_account` touches no logs.

### Admin access records (spec 009)

When an operator uses the `/admin` portal, the application logs that it
happened: the operator's account id, the resolved target account id, and the
outcome. Nothing else — no email, no display name, no credential, token or
session hash, no member content, and no raw request input. Spec 010 adds this
feature's own records under the identical disposition: one record per runtime
feature-flag mutation (set mode, add selected account, remove selected
account) carrying the operator id, flag name, action, the target
account id when the operation names one, and the outcome; plus one aggregate
record per flag-list read carrying the operator id, the flag count and the
resolved-account count. The disposition below is a deliberate controller
decision, not an omission:

- **Retention:** whatever window the platform applies to stdout (Fly's log
  retention). There is no application-side store, so there is no
  application-side lifecycle to enforce.
- **Purge:** an account purge does **not** reach these records. They are
  accountability records about an operator's action, held by the controller
  for security purposes, and they identify the member only by an account id
  that no longer resolves to anything after the purge.
- **Export:** they are **excluded** from `GET /api/account/export` (see
  below), alongside the other categories that are secrets or controller-side
  security records rather than the member's own content.

Anything beyond this — an append-only audit store, an admin-access history
UI, or a bounded application-enforced retention window — is explicitly out of
scope for spec 009 and would need its own decision.

### CRT observability records (spec 019)

CRT operational log lines may contain only correlation id, opaque tree id, operation,
revision, coarse outcome/retryable error code, and duration. They never contain owner
email/display name, card labels, graph text, request or response bodies, request hashes,
idempotency keys, content fingerprints, credentials, cookies, or local paths.

- **Retention:** the hosting platform's stdout/Fly log window; there is no application-side
  CRT log store.
- **Purge:** account/tree purge cannot erase platform logs. After purge, opaque identifiers
  in a retained line no longer resolve to application data.
- **Export:** excluded from `GET /api/account/export` as controller-side operational and
  security records, not canonical member content.

## Export contents

`GET /api/account/export` → one ZIP (`export_manifest.json`, `account.json`,
`trees/…`, `tasks/…`, `review/…`, `relay/relay.json`, `voice/operations.json`,
`voice/audio/…`). The `review/` members (spec 020) are `settings.json`,
`sessions.json`, `decisions.json` (with any extension reason text and any undo
snapshot still inside its 7 days), `receipts.json`, `park_acknowledgements.json`,
`bulk_releases.json` and `navigator_consents.json`; the content-free
`navigator_usage` counters are operational and listed under `excluded` in the
manifest. The `relay/relay.json` member carries your external-agent
connections, runs, observations, commands and audit entries, with the same
exclusions the rest of the export uses: the sealed **credential** never travels,
and neither does the **agent-card fingerprint** or the **push-token
fingerprint** — a fingerprint is a verifier, so anyone holding the export and a
candidate token could confirm a match, and none of the three is content you
asked for. Runs are exported through the same expiry projection the app reads
through (due content is already absent) and audit entries older than their
90-day bound are left out.
Modern auth also exports `connected-methods.json`: safe linked provider identifiers,
email/verification state and connection dates. It excludes codes, proofs, raw session
tokens, provider credentials, sealed mail/grant payloads, budget/replay fingerprints,
cleanup internals and migration backups. Changes still pending on a native device
are outside the server export.

Deliberately excluded, and documented in the manifest: the password hash
(secret, not portable personal data), session records (revoked secrets), and
idempotency records (transient duplicates of exported data). Also excluded:
**admin access records** — content-free platform log lines recording that an
operator looked up or revoked sessions for an account, or changed a runtime
feature flag (see above). Also excluded: the **runtime feature-flag rollout
store** — controller-side rollout configuration recording only whether an
operator selected your account id for a flag, never any content of yours. Raw
audio appears only while it is inside its 24-hour retention window.

CRT mutation receipts are included in the idempotency-record exclusion above: canonical response bodies are transient replay copies retained exactly 30 days, then redacted into content-free owner tombstones. Tree cleanup retains those tombstones to prevent old-key reuse; account purge physically erases them. CRT platform observability lines are also excluded under the disposition documented above.

Also excluded: **mobile pending classification changes that have not yet
reached the server** (the removed Expo client; builds already installed only). The controller does not hold them, so the export is
complete with respect to what the server has. The consequence is worth naming
rather than burying: an export taken while a phone holds unsent changes will
not match what that phone displays, and the mobile client shows no per-change
marker that would explain the difference (spec 006, FR-007).

Also excluded: **iOS changes that have not reached the server yet**, and everything an
iOS device holds while it has never been signed in ("On this iPhone"). The controller
does not hold them. Unlike the removed Expo mobile client, the iOS app says so in words ("Offline —
3 changes waiting"), so a difference between an export and the phone is visible there.

Also excluded: the **web last-used agent preference**. The controller never receives
this connection ID/timestamp pair, so the export is complete with respect to what the
server holds. The web client erases it on identity transition or invalid eligibility;
after 30 days it is unusable and is physically swept the next time BrainBuddy runs or
regains focus. Clearing BrainBuddy site data removes it without reopening the app
(spec 017, FR-008/FR-017).

Also excluded: **CRT browser-local drafts and last-tree preferences**. The controller does
not hold them. Both become stale after 30 days without edit/use and are swept when the web
app next starts, regains focus, or reaches its cleanup interval. A stale draft is not loaded
into the canvas: the app first offers backup, explicit recovery (which starts a new 30-day
window), or discard. Same-browser identity transitions remove every departing-owner CRT
record on the active origin after pending-work decisions. Another browser/device can only
clean its own bytes when the app runs or the user clears BrainBuddy site data; browser or
device backups may retain residual unencrypted copies.

## Maintainer checklist (manual, one-time / periodic)

- [ ] **Sign the OpenAI DPA** — platform.openai.com → Settings →
      Organization → Compliance (self-serve; countersigned PDF arrives by
      email). Do the same with Deepgram if that STT provider is enabled in
      production. Subscribe to OpenAI's sub-processor change notifications.
- [ ] **Get the Fly.io DPA** — email compliance@fly.io for their pre-signed
      DPA and counter-sign; keep the PDF.
- [ ] **Keep a one-page ROPA** (Art. 30 record of processing activities) —
      the retention table above plus purposes and legal bases is 90% of it.
- [ ] **Review the privacy policy before deploying** — confirm the contact
      email constant in `PrivacyPolicyPage.tsx` and bump `LAST_UPDATED` when
      the text changes.
- [ ] **Art. 27 EU representative** — only required if the controller entity
      is established outside the EU while targeting EU users.
- [ ] **DSARs by email** — anything not covered by the self-serve endpoints
      must be answered within one month (Art. 12(3)).
