# Proposed Sync v1 Contract

Status: Draft. This is a new protocol for the Tasks aggregate and native-task Review only. “v1” means the first version of the new protocol, not the current REST API. Neither CRT nor Identity nor raw audio is placed in the task change feed. The endpoint names below are proposed; these routes do not yet exist.

## 1. Core Guarantees

The device immediately saves an allowed local intent. The server determines the final accepted order and checks current permissions. Command and change delivery may be retried. Exactly-once internal mutation is provided by a durable command receipt and one server transaction, not by a promise that the network delivers a packet exactly once.

The client stores `confirmed_base`, `outbox`, `sync_issues`, `drafts`, and derived `visible_state`. The latter is the result of replaying allowed pending commands over the confirmed base. A rejected command no longer appears as confirmed state, but its payload and local text are retained in an issue. An unsent editor is not replaced by an incoming server version.

## 2. Identity and Versions

`owner_id` remains the existing immutable account ID. `scope_id` is the server identifier for that owner's private task scope. Its existence does not create sharing. Every requested scope is checked against current authority. The server derives an external actor from Identity or binds an internal job to its trusted owner/scope execution context; the request body cannot set that authority.

New device-originated sync `command_id` values are random UUIDs assigned on the client before their first write. Entity IDs are assigned before local creation using the accepted per-entity wire shape, not a universal bare UUID. Under ADR-0027 §7 and the [Review HTTP contract](../../020-weekly-review/contracts/http.md), client-created Review session `id`, `decision_id`, bulk release `id`, `new_formulation_id`, `follow_up_task_id`, and `progress_id` use, respectively, `review_`, `decision_`, `bulk_`, `form_`, `task_`, and `progress_` followed by a lowercase UUID (at most 64 characters total). References preserve the corresponding accepted prefixed UUID or legacy server-minted `<prefix>_<12 hex>` shape; `navigator_request_id` remains the bare UUID returned by the server. Old IDs are not renumbered, and neither entity IDs nor command IDs are used as time or order. `device_id` is registered to the account; `device_epoch` is created for an installation/queue generation and closed during a forced reset. It is an additional barrier, not a credential.

An entity has two different counters: `edit_revision` for accepted domain concurrency, and `record_version` for any serialized record change. Clock bookkeeping under ADR-0027 may increment `record_version` without changing `edit_revision`. They are not interchangeable. Each accepted write also receives a `commit_seq` within its scope. All counters are sent as JSON strings to avoid JavaScript's 2^53 limit.

## 3. Local Commands and Dependencies

Example device-originated wire envelope:

```json
{
  "protocol_version": 1,
  "command_id": "01900000-0000-4000-8000-000000000001",
  "scope_id": "scope-example",
  "device_id": "device-example",
  "device_epoch": "epoch-example",
  "local_sequence": "42",
  "type": "task.update",
  "command_version": 1,
  "entity_id": "task-existing-id",
  "preconditions": [
    {"entity_type": "task", "entity_id": "task-existing-id", "edit_revision": "17"}
  ],
  "depends_on": [],
  "issued_at": "2026-10-08T10:00:00Z",
  "payload": {"title": "Prepare the estimate"}
}
```

`issued_at` preserves the original intent time and is needed by existing time-based rules, but it grants no permissions, does not determine commit order, and is not a general conflict-resolution rule. Trust constraints on time for auto-park remain as specified in ADR-0027.

In one SQLite transaction, the runtime reads current local state, validates the command through the core, assigns a local sequence, adds the envelope, and updates the projection. A disk error rolls back everything. A retry of a local API gesture with an unknown result also checks the command ID instead of automatically creating a second ID.

An envelope is immutable after durable enqueue. If a later offline command depends on creation/editing, its `depends_on` contains the previous command ID. Instead of inventing a future server revision, `after_command: {command_id, entity_type, entity_id}` is allowed as a precondition: the server substitutes that command's **edit_revision from its receipt**, then compares it with the current revision. If another command intervened, the result is a conflict. Every other affected entity has its own precondition; it is not only the primary task ID.

The runtime sends one command at a time per scope, preserving dependency order. Rejection blocks its descendants; independent commands continue. `local_sequence` is a unique local-queue order; the server does not require a continuous numeric sequence, so cancelled and blocked records cannot stop a scope forever.

Unsent changes are not compacted in the MVP. After a confirmed rejection or explicit conflict resolution, a new command is created with a new ID and `supersedes_command_id`; descendants are also explicitly rescheduled with new IDs. This rule does not apply to an uncertain outcome.

## 4. Server Transaction

Serialization of writes within a small private scope is sufficient. All write paths take one owner/scope lock, including the REST adapter, MCP, auto-park, and jobs. In PostgreSQL this is a scope row lock held through commit; in transitional SQLite it is the transaction/writer policy of one instance. The order of multiple locks is fixed; arbitrary network work under a lock is prohibited.

Device registration and epoch checks belong to the new device-sync ingress. Legacy REST/web/CLI/MCP adapters and internal auto-park/jobs call the same application write boundary without synthetic device registration. The server entry point supplies a trusted writer origin; request JSON cannot select an origin that bypasses the device check. Legacy adapters map the existing `(owner_id, idempotency_key)` replay identity to one durable command receipt. The command/route and body are compared after lookup; changing the operation, body, or transport must not create a new replay namespace that bypasses the existing key-conflict behavior. Internal jobs use the durable effect identity and current lease/fencing policy from the plan, including the accepted auto-park dedup key. Retries reuse the same command ID and normalized content; a retry attempt or lease renewal does not create a new effect identity. These writers use the same atomic receipt/feed path, not a parallel direct-write path.

1. Check current authority: the existing Identity session/token and granted scope for external callers, or trusted internal execution authority and the current job fence for workers. Check ownership and account/restore generation, then parse the stable outer envelope under bounded transport/JSON safety rules. Reject malformed JSON and duplicate keys, but do not apply mutable execution-version, payload-schema, or execution-size rules yet. An internal job does not impersonate a user session.
2. Find the receipt by `(scope_id, command_id)`. An existing ID with the same normalized content returns the known outcome, even if its device epoch is now closed. The same ID with different content returns `IDEMPOTENCY_KEY_REUSED` and executes nothing. Permissions are checked again before returning any receipt data; closing an epoch does not bypass current authorization or restore-generation checks.
3. For an unseen command, validate the currently supported protocol/command version, execution-size limits, and command-specific request shape. For an unseen device-originated sync command, also require an active device epoch; a closed epoch cannot execute a new device command. All writers then check dependencies, edit revisions, and domain constraints using the shared Rust function on current data. A dependency without a terminal receipt returns retryable `DEPENDENCY_PENDING`; a rejected dependency returns terminal `DEPENDENCY_REJECTED`.
4. For an accepted command, atomically write domain changes, new versions, the receipt, the change transaction, and any required internal job/effect records. For a terminal rejection, write the rejection receipt without a domain mutation.
5. Commit, then respond. Device notification happens after commit and may be lost or duplicated.

The fingerprint is computed on the server from the RFC 8785 canonical JSON of the entire normalized command envelope and its server-derived writer origin, excluding transport observability headers. Current authentication credentials and job lease tokens are execution context, not replay-key inputs. Duplicate JSON keys and non-integer numeric values where a string counter is expected are rejected before execution. The same command ID cannot be reused through another origin or endpoint with changed semantics. The fingerprint is stored as protected service data and is never logged.

The stable replay parser and its bounded transport ceiling must continue to accept previously accepted envelopes for as long as their receipts are retained. Lowering an execution limit or retiring a command version cannot make a matching known command fail before receipt lookup. This preserves parsing/fingerprint compatibility, not permission to execute retired commands. Authorized result lookup by command ID also remains available without resubmitting the old payload; redacted receipts follow section 5.

An ordinary DB sequence does not define a cursor: transaction A may get a number before B and commit after B. The scope counter is incremented **under the same lock and in the same transaction**, so the issued commit order has no such gap. This intentionally limits write throughput within one scope; if measured load proves a need, the mechanism may be replaced with a commit-ordered log while preserving the contract.

## 5. Receipts and Unknown Outcomes

```json
{
  "command_id": "01900000-0000-4000-8000-000000000001",
  "outcome": "accepted",
  "server_generation": "generation-example",
  "commit_seq": "908",
  "result_versions": [
    {"entity_type": "task", "entity_id": "task-existing-id", "edit_revision": "18", "record_version": "24"}
  ],
  "correlation_id": "opaque-support-reference"
}
```

Terminal outcomes: `accepted`, `rejected`. Accepted includes an allowed domain no-op with a result but no extra effect. Rejected contains a code, safe details, and the latest available version. `pending` from a result lookup means processing is unfinished; `not_found` means no record was found **at lookup time**, not proof that a previously sent request will never commit.

Timeout, connection loss, and 5xx leave the command in `sending/unknown`. The client retries the same envelope or reads the receipt. Before retrying, it uses exponential backoff with jitter; 429 honors Retry-After. 401 pauses until reauthentication; 403/a closed epoch require separate recovery. These transport/policy failures do not destroy the outbox.

A receipt cannot simply be deleted after 24 hours. The proposed policy stores the full response for 30 days, then retains a minimal record `(scope, command ID, fingerprint, outcome/code, commit_seq, result_versions)` until account purge. After redaction, the response reports `result_redacted` and requires reading current state, but never repeats the mutation. Deleting an entity removes its text early from all retained receipt payloads. Fingerprints/IDs remain only in protected service storage and are removed at purge; they are not included in a safe export of user content.

After a device epoch is closed, unknown commands from that epoch are not accepted as new. An authorized retry of a known command with the same envelope, or a result lookup, still returns its retained receipt under the current server generation and redaction policy. User reconciliation is completed before creating a new epoch/new intents. A new installation by itself does not erase deduplication history. A restored backup cannot replay old effects.

## 6. Delta Feed and Snapshot

Proposed API:

| Method and path | Purpose |
| --- | --- |
| `POST /api/sync/v1/devices` | Register a device epoch for the current owner |
| `POST /api/sync/v1/commands` | One command; terminal receipt or retryable error |
| `GET /api/sync/v1/commands/{id}` | Owner-scoped result lookup |
| `POST /api/sync/v1/snapshots` | Create a stable snapshot and watermark |
| `GET /api/sync/v1/snapshots/{id}?page=...` | Next page of the immutable snapshot |
| `GET /api/sync/v1/changes?cursor=...&limit=...` | Complete change transactions after the cursor |
| `GET /api/sync/v1/capabilities` | Protocol/schema/command versions, limits, and reset policy |

The cursor is an opaque token bound to scope, access generation, and feed generation. `has_more` and `next_cursor` are required. A response contains transaction ID, commit sequence, source command ID, and typed upsert/tombstone after-images with record versions. A transaction contains all changed records: task, project/tag membership, children, review clocks/settings/receipts. Secrets and raw media are excluded.

A page never splits a logical transaction. Proposed initial limits: request ≤ 256 KiB, ≤ 500 changed records in one domain command, page target ≤ 1 MiB and ≤ 100 transactions; one complete transaction may raise the page to the 4 MiB hard limit. An oversized command is rejected before writing; a large batch/archive/import requires a separately agreed chunk/operation contract, not silent splitting of an atomic command. These limits must be checked against existing maximum sizes before cutover.

A snapshot is built from one consistent DB snapshot with watermark H and materialized as a temporary owner-scoped object. All pages refer to one version; TTL is 30 minutes, and a continuation token does not replace authorization. The client writes pages to a staging DB, checks completeness and checksum, then atomically activates the confirmed base and cursor H while preserving outbox/issues/drafts. Until activation, the app reads the old database. The checksum is for integrity, not for finding similar tasks, and is not logged.

After the snapshot, the client reads deltas strictly after H. If a snapshot expires before completion, it is started again without deleting pending work. Proposed delta retention is 90 days. A cursor outside the window, a feed-generation change, or a server backup restore returns `RESET_REQUIRED`. The client does not treat an empty response as recovery.

Tombstones contain ID, type, and final record version. Full after-images in the feed are available only to the current owner. When an entity is deleted, prior retained payloads containing its deleted content are redacted/removed under the deletion policy, and snapshots containing that content are invalidated; the tombstone and minimal deduplication data remain. Account purge removes the feed, snapshots, receipts, and jobs for that scope. A cursor is never carried over to a new account.

## 7. Applying Changes on Device

In one local transaction, the runtime applies the **entire** change transaction to the confirmed base, matches source command IDs to the outbox, stores the receipt, replays the remaining allowed intents, and stores the cursor. The confirmed base changes only through sequential feed transactions or full activation of a consistent snapshot. An ACK does not write after-images into the confirmed base: a late ACK across a skipped transaction could otherwise break consistency among multiple records, even with a record-version guard. The cursor does not jump to an ACK's commit_seq across unknown intermediate records.

ACK moves a command to `accepted_awaiting_feed`: it no longer needs resending, but its durable intent and optimistic projection are preserved. It is removed from pending only in a transaction that proves the result is part of the confirmed base: either a feed with that source command ID is applied, or a snapshot from the same server generation has watermark ≥ `receipt.commit_seq`. A no-op/rejected receipt with no domain changes may be completed from the receipt itself; an accepted command cannot be turned into a local conflict just because the feed has not caught up with the ACK. Snapshot recovery separately checks **all** unknown command IDs through receipt lookup. An ACK newer than the snapshot watermark remains pending until a later delta; the absence of a command from a delta does not by itself prove its outcome.

Each request captures `(workspace_generation, session_generation, local_sync_generation, server_generation)`. All ACK, receipt, feed, and snapshot responses include the server generation. On reset/restore, before preparing a new snapshot, the runtime increments local sync generation and cancels old requests; late responses with the previous set of generations are ignored, even if the account/session is unchanged. Pending work is preserved and checked against the current server generation. A result from an old generation cannot remove an intent or prove it exists after restore. An ordinary client restart by itself does not change server generation. A response already received for an old account is not delivered to a new workspace. Revoking access stops sync and closes display of the account cache under the existing sign-out/security policy; unsent work is not uploaded to a new owner. The server cannot physically revoke data from a device that never reconnects.

APNs, WebSocket/SSE, and network callbacks only wake a pull. An active client falls back to polling at least every 60 seconds, on foreground, and when the network returns. A mobile OS is not required to wake the app exactly on schedule. “Synced” means the queue is empty, there are no issues, and the latest received watermark has been applied; the last-synced label shows the time of the last successful pass, not a guarantee of perpetual freshness.

## 8. Conflicts

| Case | Required v1 behavior |
| --- | --- |
| Expected edit revision changed | Terminal `REVISION_CONFLICT`; preserve the local intent and show the latest available record |
| Different fields of one task changed | An explicit conflict is allowed in v1; automatic field merge is a separate improvement requiring validation of all invariants |
| Retry with the same command ID | Replay receipt regardless of how far state has since advanced |
| Different ID for “complete again” | No-op only if the accepted domain rule proves the same result; do not mask an intervening reopen/cancel |
| Delete versus Edit | `ENTITY_DELETED`, no upsert; copying into a new entity must be explicit |
| Project archive versus membership edit | Apply ADR-0020 under lock; create an issue if its precondition fails |
| Auto-park versus timely review decision | Specialized reducer under ADR-0027; generic stale rejection does not cancel the right to yield |
| Tag membership | Explicit add/remove operations on the relation; do not replace the whole collection with another device's stale snapshot |
| Dependent command after rejection | `blocked_dependency`; never blindly replay over changed meaning |

“Keep my version” creates a command against the current version **shown** to the user. If it changes again, new approval is required; no force overwrite. “Use server version” explicitly drops the local intent and asks about dependent actions. Bulk “last write always wins” is absent from the first version. Existing Mac last-push-wins changes only after separate acceptance of new conflict UX and an ADR.

## 9. Compatibility

Protocol, command schema, domain rules, local DB schema, and server storage epoch are versioned separately. The server accepts the current and previous published major command versions for execution for at least 180 days from replacement; capabilities returns the exact supported versions and deadline. Older clients receive `UPGRADE_REQUIRED` for unseen commands or unsupported synchronization operations, and their data/queue are preserved. Retiring a version does not disable authorized replay or lookup of retained receipts through the stable recovery envelope. This rule prevents an old client from losing unknown fields through full-object PUT.

The REST adapter translates legacy requests into the shared command handler and feed in the same transaction, preserving prior preconditions and response shapes. This does not give old clients the new conflict UI: legacy writes remain serialized events, and a new client can conflict with them. The new explicit-conflict guarantee applies to new clients; it cannot be promised for old last-writer clients. The compatibility window ends with a managed minimum-version gate before incompatible invariants change.

The feature is enabled by scope capabilities, not only a local UI flag. After new storage is activated, flag OFF stops rollout and new connections but does not return an old writer to the new DB. Each storage epoch has an oldest compatible image. Server restore changes server/feed generation, closes unsafe epochs, and reconciles external effects; rolling back the DB separately from receipts/effects is prohibited.

Restore runs with access closed. Before reads and writes are allowed, **all** later purge/deletion and credential/session revocation decisions from the durable control ledger, which is not rolled back with the task backup, must be reapplied. Otherwise an old backup could resurrect deleted data or previously revoked access. On restore, uncertain Identity sessions are revoked and fresh authentication is required; closing device epochs alone is insufficient. If ledger completeness cannot be proven, the service remains closed until reconciliation. The control ledger itself contains only minimal IDs/generations and has its own protected backup/retention policy.

Backup/WAL policy must define a verified RPO/RTO before production cutover. Lost confirmed commits after disaster restore cannot be declared “successful sync”: restoring to an older point requires an explicit incident/reconciliation, closed epochs, and reconciliation of surviving client intents/receipts. An already-lost receipt cannot provide exactly-once retroactively; a new ID does not restore that proof.

## 10. Required Validation Scenarios

Also verify a legacy REST/CLI/MCP mutation and an internal auto-park/job mutation without device fields: each must publish its changes through the common transaction, and a retry must return its original outcome without a second effect. A forged writer-origin field cannot bypass a closed device epoch; revoked caller authority and a stale worker fence cannot authorize a new write. A lost-response retry after command-version retirement or a tighter execution schema/size limit must still return a matching retained receipt; an unseen command must satisfy the current execution rules.

Check crashes before/after every transaction boundary; new-runtime Review IDs and references accepted by legacy body/path validators; duplicate and reordered delivery; response lost after commit, epoch closed, and authorized retry returns the retained receipt without executing again; unknown command from a closed epoch is rejected and revoked access cannot read a receipt; ACK after a newer delta; ACK before a skipped intermediate multi-record delta; ACK beyond snapshot watermark; two offline commands after create; another device intervening between dependent commands; independent queue progress after rejection; snapshot pagination during concurrent writes; delete/redaction during snapshot; 90 days offline; receipt after 30 days; purge/revocation after the date of a restored backup; late pre-restore ACK in the same session; stale session response; unsupported command; lock/commit race; concurrent app/widget writes; auto-park yield and bookkeeping without edit revision. Invariant: `visible = confirmed + replay(allowed pending)` and a terminal receipt never permits repeating an internal effect.
