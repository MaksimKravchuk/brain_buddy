# Data retention & GDPR operations

What Brain Buddy stores per user, how long it keeps it, how the self-serve
data rights work mechanically, and the small manual checklist that keeps the
operation GDPR-compliant. The user-facing summary of all of this is the
in-app privacy policy (`frontend/src/pages/PrivacyPolicyPage.tsx`, served at
`/privacy`) — keep the two in sync.

## Retention schedule

| Data | Where | Retention | Enforced by |
|---|---|---|---|
| Account record (email, display name, Argon2id password hash) | `data/users/<user_id>.json` + `users/_by_email.json` index | Life of account + 14-day deletion grace | Account purge (below) |
| Sessions | `data/sessions/<sha256>.json` | 30 days, or logout / revocation | Lazy delete on read; bulk revoke on password change & deletion |
| Trees, versions, AI validation history | `data/<tree_id>/…` + `data/index.json` | Life of account | Account purge |
| Tasks, projects, tags, subtasks, comments | `data/tasks.sqlite3` + JSON mirrors (`tasks/`, `projects/`, `contexts/`, `task-subtasks/`, `task-comments/`) | Life of account | Account purge |
| Task idempotency records | `tasks.sqlite3` + `task-commands/` mirrors | 24h rolling (`purge_expired_idempotency`), all on account purge | Maintenance sweep / purge |
| Voice operations (transcripts, consent records) | `data/voice_operations.sqlite3` + `brain-dump-operations/` mirrors | Life of account; uncommitted working artifacts 7 days | Sweep (`purge_expired_working_artifacts`) / purge |
| Raw voice audio | `data/brain-dump-media/<owner>/…` | 24 hours after processing (`BRAIN_BUDDY_VOICE_RAW_AUDIO_RETENTION_SECONDS`), or immediate user deletion | Sweep (`purge_expired_raw_audio`) / in-app "Delete raw audio" |
| Invites | `data/invites/<code>.json` | Indefinite, but `used_by_user_id` is scrubbed to `"deleted-user"` on account purge | Purge (`InviteRepository.scrub_user`) |
| Runtime feature-flag rollout store (flag modes plus the **account ids** an operator selected — no email, display name, credential or member content) | `data/feature_flags.sqlite3` | Life of the deployment; an account's id is removed from every cohort on account purge | Purge (`FeatureFlagOverrideRepository.scrub_user`) |
| Server logs (correlation IDs, no content) | process stdout / Fly logs | Fly's log retention | Platform |
| **Admin access records** (an operator looked up, or revoked sessions for, one account; or changed a runtime feature flag's mode, cleared its override, or added or removed one selected account; or read the flag list, resolving its cohorts: operator account id, resolved target account id where the operation names one, flag name, action, outcome, and per-read flag and resolved-account counts — no email, display name, or request body) | process stdout / Fly logs | Fly's log retention | Platform |
| Mobile pending classification queue (task, project and tag **ids**) | device `AsyncStorage`, key `bb.pendingClassification.<server>.<account>` | 30 days from last edit, or immediately on a deliberate identity transition | Mobile client sweep across all stored identities (spec 006, FR-011/FR-018) |
| Mobile cached project and Tag lists (user-authored **names**) | device `AsyncStorage`, key `bb.classificationCache.<server>.<account>` | 30 days from last fetch, or immediately on a deliberate identity transition — including when the queue is empty | Mobile client sweep (spec 006, FR-011/FR-018) |

The two device rows are the only entries in this table an account purge cannot
reach: the server can revoke every session, but it cannot delete bytes on a
phone. The sweep is the compensating control, so the maximum window in which
erased content survives on a device is 30 days. Both stores are unencrypted at
rest and are captured by device backups — see spec 006's Assumptions for why
that was accepted rather than moved to the Keychain.

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
   trees (directories incl. versions + validation, index entries) → invite
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

## Export contents

`GET /api/account/export` → one ZIP (`export_manifest.json`, `account.json`,
`trees/…`, `tasks/…`, `voice/operations.json`, `voice/audio/…`).
Deliberately excluded, and documented in the manifest: the password hash
(secret, not portable personal data), session records (revoked secrets), and
idempotency records (transient duplicates of exported data). Also excluded:
**admin access records** — content-free platform log lines recording that an
operator looked up or revoked sessions for an account, or changed a runtime
feature flag (see above). Also excluded: the **runtime feature-flag rollout
store** — controller-side rollout configuration recording only whether an
operator selected your account id for a flag, never any content of yours. Raw
audio appears only while it is inside its 24-hour retention window.

Also excluded: **mobile pending classification changes that have not yet
reached the server.** The controller does not hold them, so the export is
complete with respect to what the server has. The consequence is worth naming
rather than burying: an export taken while a phone holds unsent changes will
not match what that phone displays, and the mobile client shows no per-change
marker that would explain the difference (spec 006, FR-007).

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
