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
| Server logs (correlation IDs, no content) | process stdout / Fly logs | Fly's log retention | Platform |
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
5. `purge_account` deletes in a crash-safe, idempotent order — sessions →
   voice (SQLite rows, JSON mirrors, raw audio) → tasks (SQLite rows, JSON
   mirrors) → trees (directories incl. versions + validation, index entries)
   → invite scrub → **user record last**. If the process dies mid-purge the
   account is still past-due and the next pass re-runs everything.

Nothing user-identifiable survives a purge; consumed invites keep only the
`"deleted-user"` sentinel so they stay burned.

## Export contents

`GET /api/account/export` → one ZIP (`export_manifest.json`, `account.json`,
`trees/…`, `tasks/…`, `voice/operations.json`, `voice/audio/…`).
Deliberately excluded, and documented in the manifest: the password hash
(secret, not portable personal data), session records (revoked secrets), and
idempotency records (transient duplicates of exported data). Raw audio
appears only while it is inside its 24-hour retention window.

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
