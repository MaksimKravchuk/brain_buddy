# 026 Recovery, protected records and backup retention

Scope of this file at PR-51 (T051): which sync records are **protected control or
dedup state**, how long each lives, what export and purge do with them, and the
backup horizon that bounds a purge. PR-56 (T056) appends the stopped-writer
rehearsal results: storage epoch, rollback-compatible image, verified RPO/RTO.

## Protected categories (kept minimal)

| Category | Tables / location | Why it must outlive a request | Ends | Export | Purge |
| --- | --- | --- | --- | --- | --- |
| Command receipt metadata (command ID, writer origin, fingerprint, outcome/code, commit sequence, result versions, typed `id_bindings`) | `sync_command_receipts` | Exactly-once replay; a retried command after a lost response must find its original outcome. Content-free after the 24 h response expiry | Account purge | Never (fingerprints are verifiers) | Deleted |
| Legacy key mapping (`owner`, key digest, command ID) | `sync_legacy_keys` | One idempotency key spans legacy and sync transports | Account purge | Never | Deleted |
| Record versions and tombstones | `sync_record_versions` | Version checks and delete-then-recreate refusal | Account purge | Never (domain exports carry the records) | Deleted |
| Job / effect ledger (dedup key, fence, effect command ID, safe code) | `jobs` (`scope` = owner) | One external effect per dedup key; `reconciliation_required` must survive restarts | Terminal job retention, else account purge | Never (lease tokens, payload references) | Deleted by `scope` |
| Restore control decision (owner/entity IDs, purge or authority-revocation action, effective generation/time) | Protected durable ledger outside task-backup rollback | Replayed before access reopens after a restore, so a restore cannot resurrect a purged or revoked account | Only while an affected restore point is recoverable (backup/WAL horizon, at most 7 days), then erased | Never | Marker erased last, after affected restore points are retired |

Not protected, and therefore removed on their own clocks: change records and
transactions (feed retention, proposed 90 days), snapshots and transfer pages
(30 minutes), content-bearing receipt results (24 hours, or the source deadline
if earlier). All of them are also deleted at purge.

Exportable sync identity is only the owner's scope generations and registered
device epochs (`sync/scope.json`, `sync/devices.json`). Everything else in the
table above is excluded and named in `export_manifest.json` under `excluded`.
On the device, `export.rs` adds visible records, unfinished commands, sync
issues, user-authored drafts and proven identity aliases; it drops digests,
receipts, cursors, fences and any JSON key that names a fingerprint, digest,
token, secret, password or credential.

## Purge order and completeness

`AccountService.purge_account` is unchanged in authority and order. The task
purge (`TaskRepository.delete_all_for_owner`, under the owner command lock)
removes every table in `SYNC_TABLES` (device epochs, devices, change records and
transactions, transfer and snapshot pages and manifests, legacy keys, receipts,
record versions, scope) and every `jobs` row whose `scope` is the owner, in the
same SQLite transaction as the task rows. AI proposals are voice brain-dump
operation rows and are erased by the voice purge step that already precedes it.
A structural test fails if any `sync_*` table with an `owner_id` column keeps a
row for a purged owner, so a table added later cannot escape the purge.

## Backup retention

- Task-store backups and WAL archives are recoverable for at most 7 days (the
  proposed horizon in data-model.md). A purge is complete only when the affected
  restore points are retired or made irrecoverable and the owner-linked restore
  control marker is erased.
- If artifact removal cannot be proved, purge reports incomplete, access stays
  closed, and the next sweep retries. Nothing is reported done early.
- The restore control ledger is not an exception to `docs/data-retention.md`:
  an entry is kept only until the last restore point that predates it expires.

## Logging guarantee

Export and purge log owner IDs, counts, durations and error stages only. No
title, note, comment, media, credential, fingerprint, digest, lease owner or
payload reference is logged. `tests/test_sync_export_purge.py` asserts this on
captured logs; the local export reports counts and elapsed milliseconds and its
errors read `EXPORT_<STAGE>: STORE_<CODE>`.

## Restore and control ledger

PR-52 (T052). Contract: `contracts/sync-v1.md` §9 and §10. Code:
`backend/app/modules/tasks/sync/control_ledger.py`, `restore.py`.

### Ledger

`ControlLedger` is a separate SQLite file (`<data dir>/sync_control_ledger.sqlite3`
by convention) that a task backup or WAL restore never rolls back. An entry is
`(seq, kind, owner_id, auth_version, recorded_at)`: no content, no email, no token.

| Kind | Written by | Lives until |
|---|---|---|
| `purge` | `AccountService.purge_account`, first step, before any erase | `complete_purge`: restore points retired, then the owner is erased from the row |
| `revoke_sessions` | account deletion request, password change, email change (before sessions are deleted) | `prune`: older than `HORIZON` (7 days, the proposed backup/WAL horizon) |
| `retired` | tombstone left by either of the above | kept: only `seq` and time, so the sequence stays gapless |

`complete_purge(owner, retire)` calls the injected `retire` (backup, WAL and
transfer artifacts) first; if it raises, the marker stays and the account purge
raises before the user record is deleted, so the sweep retries. Only then is the
owner-linked marker erased (`secure_delete` on, so no owner ID remains in the
file). `AccountService.attach_control_ledger(ledger, retire)` wires both.

### Restore procedure (`restore_control_plane`, then `reopen`)

1. Close access first: every `sync_scopes.admission_open = 0`; ledger state `closed`.
2. Prove completeness from the ledger file and the backup timestamp only (a
   restored image cannot vouch for itself): the ledger must have existed at
   `backup_taken_at` and not have retired anything newer, and its `seq` must have
   no hole. Otherwise `LedgerIncomplete`; access stays closed until reconciliation.
3. Replay all later `purge` entries (`purge_owner`, i.e. `delete_all_for_owner`).
4. Revoke every session of every owner in the image, plus ledger-recorded
   revocations (uncertain sessions; fresh authentication required).
5. Mint new `server_generation`, `feed_generation`, `access_generation` per scope
   and close every active device epoch with reason `restore`.
6. Ledger state `replayed`; the report outcome is always
   `INCIDENT_RECONCILIATION_REQUIRED`: restoring an older point is never an
   ordinary successful reset. Confirmed commits after the backup are lost and must
   be reconciled with surviving client intents. A lost receipt gives no
   exactly-once proof, and a new command ID does not restore it.
7. External effects (provider calls, mail, Apple cleanup) are reconciled
   separately. `reopen(..., external_effects_reconciled=True)` is refused unless
   state is `replayed`, then admits owners again.

Every step is idempotent; a crash leaves access closed and a rerun completes.
Receipts retained in the backup still replay under their original outcome, so no
internal effect repeats (`test_026_FR_005_restored_receipts_never_repeat_an_internal_effect`).

### Device epochs across a generation change

`devices.register` for an epoch registered under another `server_generation` now
closes it (`close_reason = generation_changed`) and answers `EPOCH_CLOSED` with
`epoch_status: closed`, so the client moves to a fresh epoch instead of looping
on `RESET_REQUIRED` / `epoch_status: active`.

### Operator runbook

Never run against real data without the incident owner's go-ahead. Order:

1. Stop the backend (all writers). Restore `tasks.sqlite3` from the chosen backup.
   Keep `sync_control_ledger.sqlite3` and `auth.sqlite3` as they are; the ledger
   must not be restored from a backup.
2. `python -m app.cli sync-restore-control-plane --writers-stopped --backup-taken-at <ISO time with offset of the backup>`.
   Prints the report (`INCIDENT_RECONCILIATION_REQUIRED`, purged and revoked owners,
   closed epochs). Exit 1 and "Access stays closed" means completeness could not
   be proven (backup older than ledger coverage or a hole in the sequence): do not
   start the backend; reconcile manually.
3. Reconcile external effects (provider calls, mail, Apple cleanup) and surviving
   client intents separately; open the incident record for lost confirmed commits.
4. `python -m app.cli sync-restore-control-plane --writers-stopped --reopen --external-effects-reconciled`,
   then start the backend.

Production wiring: `Container.control_ledger` (`<data dir>/sync_control_ledger.sqlite3`)
is attached to `AccountService` and `DeviceEpochs`; the privacy sweep calls
`prune`. The app cannot delete platform snapshots, so purge markers are not
erased at purge completion: `prune` retires a marker once it is older than the
7-day horizon and the account no longer exists. Deployments that can remove
backup artifacts pass a `retire` hook to `attach_control_ledger` and erase the
marker at purge completion instead.

### Epochs registered after the restore point

Registrations are recorded in the ledger (`epoch` entries, content-free IDs). Restore
inserts each one missing from the image as `closed` (`close_reason = restore`),
so the device's next send is `EPOCH_CLOSED` (`epoch_status: closed`), never a 404.
A 404 is therefore only for a truly foreign or unknown resource. Entries expire
with the horizon, after which no restore point predating the registration exists.

### RPO <= 24 h / RTO <= 4 h

Not claimed here; the pilot measures them on the reference workload. Procedure:
(a) time a full restore drill from the newest backup into an empty data dir with
the production-sized dataset; RTO is the wall clock from "restore started" to
`reopen` accepted, including replay of the whole ledger and session revocation;
(b) RPO is `now - backup_taken_at` of the newest restore point at drill time,
sampled over the pilot, plus the WAL position if WAL shipping is enabled. Record
both with the drill date in `evidence/`. Production cutover requires both numbers
within the bounds and the 7-day backup/WAL retention actually enforced.
