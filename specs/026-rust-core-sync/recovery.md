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
