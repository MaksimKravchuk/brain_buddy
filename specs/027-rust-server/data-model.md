# Data model: Rust server (027)

The product entities do not change (spec Key Entities). What changes is where
they live: seven SQLite files plus JSON tree files become one PostgreSQL
database with one schema per owning module (research R2). No row is migrated:
production starts empty (FR-019).

## Ownership map

| Schema | Owner module (ADR-0001) | Holds | Today |
| --- | --- | --- | --- |
| `identity` | Identity (ADR-0028) | users, password hashes (Argon2id), sessions (hashed tokens), invites, email codes, external identities (Apple/Google), browser and device grants (ADR-0029), pending signups awaiting an invite (contracts/invite-handoff.md). Login rate limits stay in process memory (not stored) | `auth.sqlite3` |
| `flags` | Feature flags (ADR-0019) | flag modes, selected owners (changes logged to stdout only, as today; no stored audit) | `feature_flags.sqlite3` |
| `tasks` | Tasks | tasks, projects, Tags, children, archive, Review sessions/decisions/formulations, navigator state | `tasks.sqlite3` |
| `sync` | Tasks (026 sync) | command receipts, change feed (per-scope commit sequence), snapshots/transfers, hints cursor, generations | `tasks.sqlite3` |
| `jobs` | Tasks (026 durable jobs) | job ledger, leases, fencing tokens, dead letters, owner generations | `tasks.sqlite3` |
| `control` + object store (bucket `control`) | Control (026 PR-52, cross-cutting) | `control_applied` (applied ledger sequence numbers) and maintenance state in PostgreSQL; the append-only control ledger itself (deletions, purges, revocations, credential epochs, flag changes) lives in the object store, **outside** PostgreSQL, so a point-in-time restore cannot roll it back (research R11) | `sync_control_ledger.sqlite3` |
| `crt` | CRT | trees, nodes (`text` payload), relations, versions, index, command receipts (ADR-0026), exposure | `tree.json` files + `crt_commands.sqlite3` |
| `voice` | Capture / voice workflow (ADR-0002) | voice operations, stages, object keys of stored audio (bytes in the object store, bucket `voice`, research R11), provisional items | `voice_operations.sqlite3` |
| `agents` | Agents (spec 007/014) | agents, sealed credentials, relay exchanges, observations | `agents.sqlite3` |

Payload encoding (tasks, review, navigator; 1:1 port): the `payload` columns
are `text` holding canonical JSON, not `jsonb`, and `normalized_name` is
`bytea`, because PostgreSQL cannot store U+0000 in `jsonb` or `text` while the
Python API accepts it and SQLite round-trips it. Length limits are enforced in
`bb-domain`, not by CHECKs over the payload; a field a query needs becomes a
column. (`crt` nodes keep `jsonb` until the same audit is done for them.)

Rules:

- A module's repository queries only its own schemas. Cross-module reads go
  through application ports, as today. A test in `bb-store` parses every
  `sqlx` query and fails when it touches another module's schema.
- The Tasks owner group is one module for these rules: the application
  modules `tasks`, `review`, `sync` and `jobs` all use `bb_store::tasks`, which
  owns the `tasks`, `sync` and `jobs` schemas and the one unit of work that
  commits them together (ADR-0031, "task + review atomicity"); the navigator
  is part of this group. Job adapters for other modules reach those modules
  only through their ports.
- Control exception: a decision's effect and its `control_applied` row must
  commit together, and effects live in several modules. So every
  `bb_store::<module>` may call `bb_store::control::mark_applied(&mut tx, seq)`
  inside its own transaction — the only allowed cross-module store call,
  enforced and tested by the module-boundary check; application modules reach
  Control only through `bb_app::ports::control`.
- Every owner-scoped table carries `owner_id` and every query filters on it
  (FR-008); a foreign row is indistinguishable from a missing one.
- Account purge deletes across all schemas through the existing purge port,
  including receipts, feed, jobs, snapshots and restore points (FR-009,
  ADR-0031 amendment 3).
- Retention limits are unchanged (FR-010) and per module, as today:
  task/Review/sync full command responses 24 h, then content-free command
  metadata until account purge; 7-day Review recovery content; CRT command
  receipts (ADR-0026) keep the response body exactly 30 days, then are
  redacted to a content-free tombstone kept until account purge; voice audio
  and transcripts per `docs/data-retention.md`. Each module's retention sweep
  is a job-test row in the capability dispositions.
- Account deletion: live data erased when the 14-day grace ends; reported
  complete only after the last restore point holding the owner expires
  (≤ 7 days later) and every object-store item for the owner is gone
  (research R11).
- Timestamps are `timestamptz` in UTC; identifiers keep their current wire
  format (prefix + random), so sync v1 and the web DTOs are unchanged.

## Migrations

- `sqlx` versioned migrations in `rust/crates/bb-store/migrations/`, applied
  by `bb-server migrate` as the Fly `release_command`, never implicitly at
  request time.
- Migrations are forward-only and, after cutover, expand/contract compatible
  with the previous release (research R12); a failed migration aborts the
  release.

## New configuration entities

- **Client release epoch**: `BRAIN_BUDDY_MIN_CLIENT_EPOCH` and the server's
  own epoch exposed by `GET /api/meta` and `X-Server-Epoch`
  ([contracts/release-epoch.md](contracts/release-epoch.md)).
- **Cutover record**: not stored in the database; a committed evidence file
  `specs/027-rust-server/evidence/cutover.md` with non-personal operational
  fields only (authorizer role and timestamp, candidate SHA and image digest,
  stop/start timestamps, smoke result counters, rollback or erase outcome,
  correlation IDs). Kept indefinitely in the repository; not part of any
  account's export or purge (owner decision, 2026-10-14).

## Device stores (Apple)

- The shared runtime's SQLite (bb-client) is the only local store.
- **Legacy artifact inventory** (deleted by the reset; the Phase D slice
  commits the exact path list as `ios/BrainBuddyKit/Sources/BrainBuddyWorkspace/LegacyArtifacts.swift`
  and a test asserts every listed artifact is absent afterwards and that the
  list covers every path the removed legacy code wrote): the legacy document
  store and its upgrade backups; outbox and replay journal; conflict drafts
  and drafts; quarantine files; 026 import reports and import markers; the
  pre-Rust and Rust client SQLite created against the old server; sync cursor
  and hint state; recent searches; `URLCache`/HTTP caches; UserDefaults keys
  of the legacy runtime and pilot switch; Keychain items for the old session;
  the App Group widget snapshot; on macOS additionally the legacy importer
  folders and cookie state (`LegacyCookieCleanup`).
- **Trigger**: the app calls `GET /api/meta` before any sign-in or sync. With
  `server_epoch ≥ 1` and legacy artifacts containing tasks, waiting changes or
  drafts, it shows the confirmation (FR-021, design M-02/D-03 .01) and deletes
  only after "Delete and continue". Without such content it deletes without
  asking (.08). Against the old server (`/api/meta` 404) or offline it deletes
  nothing (.00), so a build that lands on TestFlight before cutover is safe.
- **Ordering and recovery** (all-or-nothing is not achievable across
  SQLite/files, Keychain, UserDefaults and the App Group): a durable marker
  `reset=confirmed` is written first; artifacts are deleted in a fixed order,
  each step idempotent; `reset=done` is written last. While the marker is
  `confirmed`, the app makes no network request, shows .02/.05, and on next
  launch resumes the remaining steps without asking again (.06).

## Payload encoding (all schemas, 1:1 port)

No column in any schema is `jsonb`. Every document, value, metadata, result,
snapshot or response column is `text` holding canonical JSON, because
PostgreSQL cannot store U+0000 in `jsonb` or `text`, while the Python API
accepts it and SQLite round-trips it: a NUL is stored as the six ASCII
characters `\u0000` and never cast to `jsonb`. Idempotency `response_body`
columns hold the exact stored response text, so replay is byte-identical.
Raw-character columns that can carry user text (for example tasks
`normalized_name`) are `bytea`. Consequently no CHECK, index or generated
column may reach into a payload; a field a query or constraint needs is
promoted to a real column, and length limits live in `bb-domain`.
No merged module needed a promotion: none of 0210, 0220, 0230, 0300, 0400 or
0500 had a CHECK, index or generated column over a JSON field.
