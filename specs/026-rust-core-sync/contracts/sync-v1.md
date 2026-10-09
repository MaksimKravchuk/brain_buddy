# Proposed Sync v1 Contract

Status: Draft. This is a new protocol for the Tasks aggregate and native-task Review only. “v1” means the first version of the new protocol, not the current REST API. Neither CRT nor Identity nor raw audio is placed in the task change feed. [Data model](../data-model.md), [command catalog](command-catalog.md), and [runtime/FFI contract](runtime-ffi.md) supply the concrete record, writer and binding definitions. The endpoint names below are proposed; these routes do not yet exist.

## 1. Core Guarantees

The device immediately saves an allowed local intent. The server determines the final accepted order and checks current permissions. Command and change delivery may be retried. Exactly-once internal mutation is provided by a durable command receipt and one server transaction, not by a promise that the network delivers a packet exactly once.

The client stores `confirmed_base`, `outbox`, `sync_issues`, `drafts`, and derived `visible_state`. The latter is the result of replaying allowed pending commands over the confirmed base. A rejected command no longer appears as confirmed state, but its payload and local text are retained in an issue. An unsent editor is not replaced by an incoming server version.

## 2. Identity and Versions

`owner_id` remains the existing immutable account ID. `scope_id` is the server identifier for that owner's private task scope. Its existence does not create sharing. Every requested scope is checked against current authority. The server derives an external actor from Identity or binds an internal job to its trusted owner/scope execution context; the request body cannot set that authority.

New device-originated sync `command_id` values are random UUIDs assigned on the client before their first write. Entity IDs are assigned before local creation using the accepted per-entity wire shape, not a universal bare UUID. Under ADR-0027 §7 and the [Review HTTP contract](../../020-weekly-review/contracts/http.md), client-created Review session `id`, `decision_id`, bulk release `id`, `new_formulation_id`, `follow_up_task_id`, and `progress_id` use, respectively, `review_`, `decision_`, `bulk_`, `form_`, `task_`, and `progress_` followed by a lowercase UUID (at most 64 characters total). References preserve the corresponding accepted prefixed UUID or legacy server-minted `<prefix>_<12 hex>` shape; `navigator_request_id` remains the bare UUID returned by the server. Old IDs are not renumbered, and neither entity IDs nor command IDs are used as time or order. `device_id` is registered to the account; `device_epoch` identifies a durable queue generation. An ordinary cursor/snapshot reset preserves an active device epoch; only explicit server invalidation or retirement closes it. An epoch is an additional barrier, not a credential.

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

An envelope is immutable after durable enqueue. If a later offline command depends on creation/editing, its `depends_on` contains the previous command ID. For a command whose accepted domain contract requires a revision match, `after_command: {command_id, entity_type, entity_id}` is allowed as a precondition instead of inventing a future server revision: the server substitutes that command's **edit_revision from its receipt**, then compares it with the current revision. If another command intervened, the result is a conflict. Apply the accepted command-specific concurrency checks to every affected entity, not a universal compare-and-swap gate. Review session progress retains its merge/deduplication rules without a version conflict; Review bulk release retains per-item stale/ineligible skips and atomically publishes the resulting accepted subset.

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
  "has_changes": true,
  "result_redacted": false,
  "result": null,
  "error": null,
  "id_bindings": [],
  "scope_id": "scope-example",
  "server_now": "2026-10-08T10:00:01Z",
  "server_generation": "generation-example",
  "commit_seq": "908",
  "result_versions": [
    {"entity_type": "task", "record_key": ["task-existing-id"], "edit_revision": "18", "record_version": "24"}
  ],
  "correlation_id": "opaque-support-reference"
}
```

Terminal outcomes: `accepted`, `rejected`. Accepted includes an allowed domain no-op with a result but no extra effect. Rejected contains a code, safe details, and the latest available version. `pending` from a result lookup means processing is unfinished; `not_found` means no record was found **at lookup time**, not proof that a previously sent request will never commit.

Timeout, connection loss, and 5xx leave the command in `sending/unknown`. The client retries the same envelope or reads the receipt. Before retrying, it uses exponential backoff with jitter; 429 honors Retry-After. 401 pauses until reauthentication; 403/a closed epoch require separate recovery. These transport/policy failures do not destroy the outbox.

Content-bearing task and Review response bodies retain the existing maximum of 24 hours from commit under the accepted data-retention policy and ADR-0027; this protocol does not extend them to 30 days. Expiry redacts the full response, including titles, notes, and extension reasons, while retaining only the content-free record `(scope, command ID, fingerprint, outcome/code, commit_seq, result_versions)` until account purge. Expiry is enforced even if the owner never writes again or the Review flag is off. After redaction, the new sync response reports `result_redacted` and requires reading current state, but never repeats the mutation. Deleting an entity removes its text earlier from all retained receipt payloads. Fingerprints/IDs remain only in protected service storage and are removed at purge; they are not included in a safe export of user content. Existing Capture `create_native_inbox_task` commit records retain their original until-purge response/recovery exception; CRT's separate receipt policy also remains unchanged. Neither exception extends ordinary task/Review response retention.

Legacy Review adapters preserve ADR-0027 §7's matching-record recovery after 24 hours for decisions, sessions, bulk releases, and progress: under the owner lock, match the accepted identifying fields before revision/eligibility checks and return the documented success status/response built from the stored record and current task/session. Mismatches retain the documented `id_conflict` behavior. The new protocol's `result_redacted` envelope does not replace those legacy endpoint responses, and no extra copy of expired response content is kept to reconstruct them.

After a device epoch is closed, unknown commands from that epoch are not accepted as new. An authorized retry of a known command with the same envelope, or a result lookup, still returns its retained receipt under the current server generation and redaction policy. Preserve the old immutable envelopes for outcome lookup and reconciliation; never automatically rekey or copy uncertain old commands into a fresh epoch. Replacing an affected old intent requires its own reconciliation, not resolution of every issue in the account. A new installation by itself does not erase deduplication history. A restored backup cannot replay old effects.

Epoch closure does not block genuinely new local gestures while existing workspace/security policy permits local work. Under the existing cross-process DB lock, atomically persist a fresh client-allocated intake epoch in `pending_registration` state with the first new command and projection. Further new commands, app restarts, widget writes, and snapshot retries reuse that durable epoch. Its local existence grants no server authority. An ordinary `RESET_REQUIRED` advances `local_sync_generation` but does not itself close the device epoch; server responses must distinguish that reset from explicit epoch invalidation.

Before sending from a fresh epoch, authenticated registration must confirm that same epoch ID for the current owner/device/server generation, and the current recovery base must be activated. Registration is idempotent after a lost response, never reopens a closed epoch, and its ACK follows the same request-generation fences as other responses. No queued envelope is rewritten to insert a different epoch after registration. Old unresolved dependencies remain blocked, but independent fresh commands may proceed once registration and base recovery succeed. Revoked access, sign-out, account switching, and incompatible-store restrictions remain in force; a new intake epoch cannot bypass them.

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

The cursor is an opaque token bound to scope, access generation, and feed generation. `has_more` and `next_cursor` are required. A response contains transaction ID, commit sequence, source command ID, and typed upsert/tombstone public after-images with record versions. A transaction contains every changed client-visible projection of the Tasks and native Review aggregate: tasks with formulation clocks, projects/tags and membership, children, and all Review projections below. Snapshot bootstrap contains the same complete set at its watermark; it is not limited to the earlier clocks/settings/receipts shorthand.

| Review projection type | Required synchronized state |
| --- | --- |
| `review_settings` | Threshold, review schedule/time zone, onboarding/activation, owner park floor, and revision |
| `review_session` | Public session identity/status, mode/entry/origin, times, current step and step statuses, active seconds, counts, qualifying activity, clear-start, and revision |
| `review_decision_queue` | Ordered public decision-step queue items and decided/set-aside IDs, preserving captured-empty versus not-yet-captured state |
| `review_decision` | Decision identity, task/session/formulation/history links, type/time, substantive/stall/AI-use/yield metadata, and public Undo availability |
| `review_receipt` | Keep/release receipt identity, task/kind, review/hidden-until times, revision, and decision/bulk source links; distinct from command receipts |
| `review_park_ack` | Task/formulation/park identity and public seen/returned/unseen state |
| `review_bulk_release` | Identity/kind/session/time, released task IDs and revisions, skipped reasons, undone state, and the public content-free Undo result |
| `review_navigator_consent` | Current per-provider consent status, grant/revoke times, and consent-text version; server authority is still rechecked before use |
| `review_state` | Public explainer/grace, latest counted review, next-review/restart, open-session and queue-count facts; derived consistently from the complete synchronized records as fixed in data-model.md |

Records use stable entity identities, or stable scope/session keys for singleton projections, and record versions. Updates/tombstones and any materialized derived projections commit atomically with the domain change. Use the accepted public Task/Review DTOs and queue projections as the field baseline, not raw storage documents. Exclude session `applied_progress` fingerprints and private bookkeeping, server-only Undo/park clock-before snapshots, navigator usage/cost reservations, protected command deduplication/reconciliation data, secrets, and raw media. Clients retain the existing deferred behavior for Undo requiring a server-only snapshot; device-local drafts/preferences remain local. None of these exclusions permits omitting the public resume/decision/receipt/consent state above.

A logical transaction is never partially applied or exposed. Inline feed pages target ≤1 MiB and ≤100 complete transactions with a 4 MiB hard transport limit. Larger existing atomic effects use the immutable paged transaction body in §11 and are activated only when complete. There is no 500-changed-record ceiling: the accepted 500-item bulk release also changes receipts/session metadata, and archive/tag deletion/activation can affect more tasks. New sync command ingress initially permits ≤4 MiB JSON bodies, preserving the canonical ≤500 bulk items/≤200 park keys and field limits. Requests above that execution ceiling are refused before writing; supported legacy ingress retains its accepted limits. The stable replay transport ceiling cannot shrink below any previously accepted envelope. This transport mechanism does not split a domain command or introduce a new batch product contract.

A snapshot is built from one consistent DB snapshot with watermark H and materialized as a temporary owner-scoped object. All pages refer to one version; TTL is 30 minutes, and a continuation token does not replace authorization. The client writes pages to a staging DB, checks completeness and checksum, then atomically activates the confirmed base and cursor H while preserving outbox/issues/drafts. Activation takes the cross-process writer lock and incorporates the latest live queue, intake-epoch state, issues, and drafts, including edits made after download began; an earlier copied queue cannot replace them. Until activation, the app reads the old database. The checksum is for integrity, not for finding similar tasks, and is not logged.

After the snapshot, the client reads deltas strictly after H. If a snapshot expires before completion, it is started again without deleting pending work. Proposed delta retention is 90 days. A cursor outside the window, a feed-generation change, or a server backup restore returns `RESET_REQUIRED`. The client does not treat an empty response as recovery.

Tombstones contain ID, type, and final record version. Full after-images in the feed are available only to the current owner. When an entity is deleted, prior retained payloads containing its deleted content are redacted/removed under the deletion policy, and snapshots containing that content are invalidated; the tombstone and minimal deduplication data remain. Account purge removes the feed, snapshots, receipts, and jobs for that scope. A cursor is never carried over to a new account.

The 90-day feed horizon and 30-minute snapshot TTL do not extend any source content's retention. Apply the original absolute expiry to every retained receipt, feed after-image, and materialized snapshot copy; in particular, Review decision undo/task-before and bulk-release clock-before content expires after its accepted seven days even though the decision/release record survives. Retention runs independently of owner activity and feature flags, and expired content is unavailable on reads. Redact expired fields from retained feed payloads, publish the canonical retention change through the common transaction, and invalidate affected immutable snapshots rather than changing their pages. If a retained transaction cannot remain valid after redaction, require reset instead of serving an incomplete transaction or expired content.

## 7. Applying Changes on Device

In one local transaction, the runtime applies the **entire** change transaction to the confirmed base, matches source command IDs to the outbox, stores the receipt, replays the remaining allowed intents, and stores the cursor. The confirmed base changes only through sequential feed transactions or full activation of a consistent snapshot. An ACK does not write after-images into the confirmed base: a late ACK across a skipped transaction could otherwise break consistency among multiple records, even with a record-version guard. The cursor does not jump to an ACK's commit_seq across unknown intermediate records.

ACK moves a command to `accepted_awaiting_feed`: it no longer needs resending, but its durable intent and optimistic projection are preserved. It is removed from pending only in a transaction that proves the result is part of the confirmed base: either a feed with that source command ID is applied, or a snapshot from the same server generation has watermark ≥ `receipt.commit_seq`. A no-op/rejected receipt with no domain changes may be completed from the receipt itself; an accepted command cannot be turned into a local conflict just because the feed has not caught up with the ACK. Snapshot recovery separately checks **all** unknown command IDs through receipt lookup. An ACK newer than the snapshot watermark remains pending until a later delta; the absence of a command from a delta does not by itself prove its outcome.

Each request captures `(workspace_generation, session_generation, local_sync_generation, server_generation)`. All command/registration ACKs, receipt, feed, and snapshot responses include the server generation. On reset/restore, before preparing a new snapshot, the runtime increments local sync generation and cancels old requests; late responses with the previous set of generations are ignored, even if the account/session is unchanged. Pending work is preserved and checked against the current server generation. A result from an old generation cannot remove an intent or prove it exists after restore. An ordinary client restart by itself does not change server generation. A response already received for an old account is not delivered to a new workspace. Revoking access stops sync and closes display of the account cache under the existing sign-out/security policy; unsent work is not uploaded to a new owner. The server cannot physically revoke data from a device that never reconnects.

APNs, WebSocket/SSE, and network callbacks only wake a pull. An active client starts fallback polls at most 30 seconds apart, including any scheduling jitter; jitter must shorten this interval rather than extend it. Schedule from the previous poll's start, not its completion, and also pull immediately on foreground and when the network returns. Coalesce a wake-up with an in-flight pull without postponing the next due catch-up. Under SC-004's workload and network conditions, requests, catch-up and local application must fit the remaining 30-second budget: an update committed immediately after a completed poll must be applied and visible within 60 seconds of its commit even when every hint is dropped. Merely starting a poll does not satisfy that deadline. A mobile OS is not required to wake the app exactly on schedule. “Synced” means the queue is empty, there are no issues, and the latest received watermark has been applied; the last-synced label shows the time of the last successful pass, not a guarantee of perpetual freshness.

## 8. Conflicts

| Case | Required v1 behavior |
| --- | --- |
| Expected edit revision changed for a command requiring a revision match | Terminal `REVISION_CONFLICT`; preserve the local intent and show the latest available record |
| Different fields of one task changed | An explicit conflict is allowed in v1; automatic field merge is a separate improvement requiring validation of all invariants |
| Retry with the same command ID | Replay receipt regardless of how far state has since advanced |
| Different ID for “complete again” | No-op only if the accepted domain rule proves the same result; do not mask an intervening reopen/cancel |
| Delete versus Edit | `ENTITY_DELETED`, no upsert; copying into a new entity must be explicit |
| Project archive versus membership edit | Apply ADR-0020 under lock; create an issue if its precondition fails |
| Auto-park versus timely review decision | Specialized reducer under ADR-0027; generic stale rejection does not cancel the right to yield |
| Review session progress or bulk release | Preserve the accepted progress merge/deduplication and per-item bulk eligibility/skip rules; generic entity CAS must not replace them |
| Tag membership | Explicit add/remove operations on the relation; do not replace the whole collection with another device's stale snapshot |
| Dependent command after rejection | `blocked_dependency`; never blindly replay over changed meaning |

“Keep my version” creates a command against the current version **shown** to the user. If it changes again, new approval is required; no force overwrite. “Use server version” explicitly drops the local intent and asks about dependent actions. Bulk “last write always wins” is absent from the first version. Existing Mac last-push-wins changes only after separate acceptance of new conflict UX and an ADR.

## 9. Compatibility

Protocol, command schema, domain rules, local DB schema, and server storage epoch are versioned separately. The server accepts the current and previous published major command versions for execution for at least 180 days from replacement; capabilities returns the exact supported versions and deadline. Older clients receive `UPGRADE_REQUIRED` for unseen commands or unsupported synchronization operations, and their data/queue are preserved. Retiring a version does not disable authorized replay or lookup of retained receipts through the stable recovery envelope. This rule prevents an old client from losing unknown fields through full-object PUT.

The REST adapter translates legacy requests into the shared command handler and feed in the same transaction, preserving prior preconditions and response shapes. This does not give old clients the new conflict UI: legacy writes remain serialized events, and a new client can conflict with them. The new explicit-conflict guarantee applies to new clients; it cannot be promised for old last-writer clients. The compatibility window ends with a managed minimum-version gate before incompatible invariants change.

The feature is enabled by scope capabilities, not only a local UI flag. After new storage is activated, flag OFF stops rollout and new connections but does not return an old writer to the new DB. Each storage epoch has an oldest compatible image. Server restore changes server/feed generation, closes unsafe epochs, and reconciles external effects; rolling back the DB separately from receipts/effects is prohibited.

Restore runs with access closed. Before reads and writes are allowed, **all** later purge/deletion and credential/session revocation decisions from the durable control ledger, which is not rolled back with the task backup, must be reapplied. Otherwise an old backup could resurrect deleted data or previously revoked access. On restore, uncertain Identity sessions are revoked and fresh authentication is required; closing device epochs alone is insufficient. If ledger completeness cannot be proven, the service remains closed until reconciliation. The control ledger itself contains only minimal IDs/generations and is retained only while affected restore points remain recoverable (proposed maximum backup/WAL horizon seven days). Retire/remove affected backup/WAL/transfer artifacts before account purge reports completion, then erase the owner-linked purge marker. This preserves `docs/data-retention.md` rather than introducing indefinite personal metadata after purge; failed artifact cleanup keeps purge incomplete. Other deletion/revocation entries expire when every affected restore point is retired. A restored image cannot authorize its own completeness proof.

Backup/WAL policy must define a verified RPO/RTO before production cutover. Lost confirmed commits after disaster restore cannot be declared “successful sync”: restoring to an older point requires an explicit incident/reconciliation, closed epochs, and reconciliation of surviving client intents/receipts. An already-lost receipt cannot provide exactly-once retroactively; a new ID does not restore that proof.

## 10. Required Validation Scenarios

During an interrupted/expired snapshot, save a new local capture and restart the app: its epoch, immutable command, and projection survive. After explicit epoch closure, preserve an uncertain old command while accepting new independent work into a pending-registration epoch. Retry a lost registration ACK without changing IDs; ignore a stale pre-reset ACK; never register/send for revoked authority. Recovered independent work must progress while a dependent old issue stays blocked.

From both snapshot bootstrap and an existing cursor, verify that another device's session start/progress/finish, decision/Undo, bulk release/Undo, park acknowledgment, receipt, and consent change update the complete public Review state atomically. Verify queue captured-empty semantics, required history/source links, and absence of server-only snapshots, usage reservations, and protected fingerprints.

Also verify a legacy REST/CLI/MCP mutation and an internal auto-park/job mutation without device fields: each must publish its changes through the common transaction, and a retry must return its original outcome without a second effect. A forged writer-origin field cannot bypass a closed device epoch; revoked caller authority and a stale worker fence cannot authorize a new write. A lost-response retry after command-version retirement or a tighter execution schema/size limit must still return a matching retained receipt; an unseen command must satisfy the current execution rules.

Verify 24-hour response redaction with an inactive owner and Review flag off, legacy matching-record replay after that deadline, and the scoped Capture exception. Pull after seven-day Review snapshot expiry and paginate a materialized snapshot across that deadline: neither may return expired content. Exercise concurrent Review progress without a version conflict and a bulk release with both eligible and stale items, preserving the existing accepted subset and one atomic feed transaction.

Check crashes before/after every transaction boundary; new-runtime Review IDs and references accepted by legacy body/path validators; duplicate and reordered delivery; response lost after commit, epoch closed, and authorized retry returns the retained receipt without executing again; unknown command from a closed epoch is rejected and revoked access cannot read a receipt; ACK after a newer delta; ACK before a skipped intermediate multi-record delta; ACK beyond snapshot watermark; two offline commands after create; another device intervening between dependent commands; independent queue progress after rejection; snapshot pagination during concurrent writes; delete/redaction during snapshot; 90 days offline; receipt after 30 days; purge/revocation after the date of a restored backup; late pre-restore ACK in the same session; stale session response; unsupported command; lock/commit race; concurrent app/widget writes; auto-park yield and bookkeeping without edit revision. Invariant: `visible = confirmed + replay(allowed pending)` and a terminal receipt never permits repeating an internal effect.

## 11. Concrete envelope and pagination rules

The following shapes use `T?` for nullable fields and `T[]` for arrays. Fields are required unless marked optional. `counter` is a nonnegative canonical decimal string (no sign/leading zeros except `"0"`); domain revisions start at one. Opaque tokens and IDs are not counters. Current authority is checked for **every** page/lookup; tokens never authorize access. Every response carries `X-Correlation-ID`, and JSON contains `correlation_id`, `scope_id`, `server_generation`, and `server_now`. A response with a different generation triggers recovery, never automatic base mutation.

### Registration and capabilities

`POST devices` body is `{scope_id, device_id, device_epoch, protocol_version}` with random client-allocated device/epoch UUIDs. Authenticated success returns `{device_id, device_epoch, epoch_status:"active", server_generation}` plus common response fields. Repeated registration of the same active tuple returns it unchanged; a closed ID returns `EPOCH_CLOSED`. On first registration, device ownership is bound under current Identity authority; an existing device cannot be rebound by changing owner fields.

Capabilities returns `{protocol_versions, command_versions:[{type, supported_versions, retire_at_by_version}], rule_version, projection_schema_version, storage_epoch, server_generation, feed_generation, scope_enabled, limits, recovery}`. Limits include command bytes, stable replay bytes, inline page bytes/transactions, transfer page bytes, snapshot/transfer TTL and feed retention. Recovery names snapshot support and the current device epoch status when authenticated with one. Server policy/capability availability does not override Identity authorization or ongoing-Review flag-off completion rules.

### Receipts and errors

A terminal receipt contains `{command_id, outcome:"accepted"|"rejected", has_changes, commit_seq:counter|null, result_versions:Version[], id_bindings:Binding[], result_redacted:boolean, result:object|null, error:Error|null}` plus common response fields. `Version` is `{entity_type, record_key, record_version, edit_revision?}`; `Binding` is `{entity_type, alias_id, entity_id}` for Smart Add resolutions. Accepted with changes requires a commit sequence; rejection and accepted no-op have `has_changes:false`, `commit_seq:null`. A no-op may still reference unchanged result versions. There is no ambiguity between a no-op and an ACK whose feed is delayed. Rejection has an error, accepted has none. `result_redacted:true` means content is unavailable, **not** that acceptance is uncertain.

Command POST returns HTTP 200 with a terminal receipt, including domain rejections; legacy endpoints keep their original statuses. Lookup is scope-selected (`GET commands/{id}?scope_id=...`) and returns HTTP 200 `{status:"terminal", receipt}` or `{status:"pending"|"not_found", command_id}` plus common response fields. It does not expose another owner's command existence. Pending/not-found are observations only; no automatic new command ID follows either.

`Error` is `{code, retryable, message, details:{reason?, current_versions?, dependency_ids?, epoch_status?, reset_reason?, retry_after_seconds?}}`; detail keys are allowlisted and content-free. Current task text is obtained from an authorized projection, not copied into diagnostics. Protocol/transport failures have `{error}` plus available common fields and appropriate HTTP status; they do not create a terminal command receipt. Once an unseen supported command enters adjudication, domain rejection writes a receipt.

| Code / HTTP when outside a receipt | Meaning and required action |
| --- | --- |
| `AUTH_REQUIRED` / 401; `ACCESS_DENIED` / 403 | Pause; retain workspace intent and reauthenticate/recover authority. Never retry as another owner. |
| `EPOCH_CLOSED` / 409 | Unknown command cannot execute; preserve old envelope, reconcile receipts and register fresh intake for new gestures. |
| `RESET_REQUIRED` / 409 | `reset_reason` is cursor expired/feed changed/restore/redacted transfer; `epoch_status` explicitly says active/closed. Advance local sync generation and recover base. |
| `UPGRADE_REQUIRED` / 426 | Unsupported execution/projection version. Keep store/queue; known receipt replay still works. |
| `IDEMPOTENCY_KEY_REUSED` / 409 | Same ID with changed semantics; no execution, actionable issue. |
| `DEPENDENCY_PENDING` / 409 | Retryable; predecessor not terminal yet. |
| `REVISION_CONFLICT`, `ENTITY_DELETED`, `DEPENDENCY_REJECTED`, canonical validation reason / terminal receipt | Keep rejected intent as issue; block dependent actions only. |
| `INVALID_REQUEST` / 400 or 422; `COMMAND_TOO_LARGE` / 413 | Fix request compatibility/validation, never partially execute. |
| `RATE_LIMITED` / 429; `TEMPORARILY_UNAVAILABLE` / 503 | Backoff; honor Retry-After, preserve same ID. Transport timeout/5xx means unknown outcome. |

### Feed and oversized atomic effects

`GET changes?scope_id=...&cursor=...&limit=...` returns `{from_cursor, transactions:Transaction[], has_more, next_cursor, high_watermark}`. A cursor is required after bootstrap. `high_watermark` is the latest committed scope sequence observed by this read; an empty page at a valid cursor is not reset. `next_cursor` names the position after complete transactions in this page; it remains the input cursor on an empty page. Applying a valid empty page can confirm catch-up without inventing a domain write. `has_more` is true when this read has further committed transactions after that position.

`Transaction` is `{transaction_id, commit_seq, source_command_id, changes:Change[]}`. `Change` is `{entity_type, record_key, record_version, edit_revision?, operation:"upsert"|"tombstone", value:object|null}`. A tombstone has no value; an upsert uses [data-model.md](../data-model.md). Array order is transport order, not relational apply order: validate/apply the entire transaction before exposing it. Every changed key appears once with its final after-image. Derived views recompute after all rows are installed. Receipt lookup resolves outcome metadata when a feed source ID matches an unknown local command.

When the next complete transaction would exceed 4 MiB, return HTTP 200 with `transactions:[]`, `has_more:true`, unchanged `next_cursor`, and `transaction_manifest:{transfer_id, transaction_id, commit_seq, source_command_id, page_count, record_count, total_bytes, sha256, expires_at, first_page_token, after_cursor}`. Any earlier inline transactions are served in a previous response, so the manifest always describes the immediate next transaction. The transfer is immutable and scope/generation-bound. Proposed `GET /api/sync/v1/transactions/{transfer_id}?page_token=...` returns bounded byte pages as `{transfer_id, page_index, payload_base64, page_sha256, has_more, next_page_token}`. Decoded bytes are consecutive chunks (≤1 MiB each, complete JSON response ≤4 MiB) of the RFC 8785 canonical JSON Change array. A chunk may cross a record boundary: it is staged bytes, never independently parsed/applied domain state. This also handles existing unbounded session queues or membership arrays without inventing a domain size restriction. Parse/validate the completed stream with a streaming decoder into staging rows before activation.

Client downloads to staging, checks all indices/counts/digests, then applies the **whole transaction**, source-command reconciliation, replay and `after_cursor` in one local write transaction. It may stream staged records during that transaction, but never expose a partial result. Expiry, generation change, deletion or content expiry invalidates the transfer and returns `RESET_REQUIRED`; staging can be discarded without discarding live work. Retention runs independent of these transfers. Missing a hint has no effect on correctness. This is transport pagination, not multiple domain commits.

### Snapshot manifest and pages

`POST snapshots` body `{scope_id, projection_schema_version}` returns `{snapshot_id, watermark, cursor, page_count, record_count, total_bytes, sha256, expires_at, first_page_token}`. Proposed snapshot page GET adds `scope_id` and `page_token` (the earlier `page=...` spelling is illustrative). A page returns `{snapshot_id, watermark, page_index, payload_base64, page_sha256, has_more, next_page_token}` using the same bounded byte-stream encoding as transaction transfers. The decoded stream is a canonical JSON Change array of current upserts plus required deletion-version metadata, not a replay of historic receipts. Snapshot records use deterministic `(entity_type, record_key)` ordering. The final page has `has_more:false`, `next_page_token:null`; every preceding page has both true/non-null. Resume tokens bind the immutable manifest and index.

A page digest is SHA-256 of its decoded bytes. Manifest digest is SHA-256 of the complete decoded canonical stream, assembled in page-index order. `record_count` counts Change objects; `total_bytes` counts decoded stream bytes, so retries are verifiable independent of base64 or HTTP compression. Digests are integrity metadata and never logged. Verify page indices, counts, total bytes, digest, generation and unexpired authorization before activation. Fresh activation uses manifest cursor/watermark and the latest live queue as §6 requires; it never treats an earlier copied outbox as current.

Validation additions for these shapes: exercise a 500-item bulk release whose total changes exceed 500, a multi-page archive/tag deletion, a byte chunk crossing a record boundary, a corrupted/missing transfer page, transfer expiry/deletion while downloading, a Smart Add classification alias resolved to an existing record, stalled-count preservation on a non-Next task, and a no-op receipt with no feed transaction. Each must preserve the same domain outcome and atomic visible state as the ordinary path.
