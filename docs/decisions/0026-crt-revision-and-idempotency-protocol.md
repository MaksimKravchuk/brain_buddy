# ADR-0026: Stage CRT revisions and reconcile idempotent tree commands

Date: 2026-09-19
Status: Accepted
Decision owner: BrainBuddy
Related: ADR-0001, ADR-0008, ADR-0025, `specs/019-miro-like-crt-canvas/`

## Context

Feature 019 adds integer optimistic concurrency and ADR-0001 `Idempotency-Key` support to the existing file-backed Thinking/CRT aggregate. The current tree model ignores unknown top-level fields and rewrites parsed models. If a revision-writing image were rolled back directly to the current image, a legacy mutation could erase `revision`/`schema_version`; a later roll-forward would read revision 1 and could accept a stale browser draft.

The canonical tree, global tree index, and any new replay receipt cannot share one filesystem/SQLite transaction. A client may also lose a response after the mutation commits. Exact replay therefore needs an explicit command record and deterministic crash reconciliation, not a best-effort cache.

## Decision

### 1. Ship the persistence evolution in two compatible stages

**Stage A — compatibility writer** lands and is deployed before any CRT canvas schema write or exposure:

- apply ADR-0025's fifth managed-flag expansion, create `crt_canvas=OFF`, and make the Stage A reader healthy against the exact five-row set while exposing no CRT route;
- add top-level `revision` and `schema_version` to `TreeDocument`, API responses, import and export with legacy read defaults of 1;
- make every successful persisted tree-aggregate mutation increment revision exactly once, including legacy tree/node/relation writes, validation-state writes, version-reference changes and version restore;
- add/preserve the optional internal `last_command_id` field but clear it on every Stage A legacy mutation, so a later Stage B reconciliation never mistakes that mutation for its own command;
- preserve the schema fields through every read/write path and prove legacy payload compatibility;
- add no `/api/crt/trees` mutation exposure and keep `crt_canvas` OFF.

Stage A becomes the oldest permitted rollback image after Stage B writes the new fields. Release evidence records its exact deployed SHA. Before rollback, Stage B disables exposure and reconciles every pending command; an unresolved pending receipt blocks image rollback. A rollback from Stage B may return to that Stage A SHA, never to a pre-Stage-A writer. If Stage A itself cannot run, use flag OFF plus a forward fix or restore a pre-migration backup; do not run an older writer against migrated live data.

**Stage B — CRT command facade and canvas** may deploy only after Stage A production smoke and read-back prove revision monotonicity on a disposable tree. Stage B adds the gated facade, receipts, local recovery and UI. `crt_canvas` remains OFF until Stage B's exact-SHA evidence is approved.

### 2. Thinking/CRT owns a SQLite command-receipt store

Add one Thinking/CRT-owned SQLite database/repository, `crt_commands.sqlite3`, wired through the existing container and account service. This is not a second graph store. It contains command/replay metadata and, for committed receipts during their replay window, the canonical response needed for exact replay.

A receipt is owner scoped and records:

```text
key_digest, owner_id, command, normalized_route, request_hash
state: pending | committed | expired (content-free tombstone)
resource/tree id, base_revision?, target_revision?
response_status?, response_json?, pending_target_snapshot?
created_at, committed_at?, expires_at?
```

Raw idempotency keys are never persisted or logged; only their SHA-256 digest is stored. The request body is not duplicated in the receipt. `response_json` receives the same access controls as the canonical tree and is excluded from account export as a transient duplicate. It is retained exactly for 30 days after commit; expiry or confirmed tree deletion redacts the response status/body and pending snapshot in place, retaining only the owner-scoped key digest, command, normalized route, request fingerprint, and opaque resource/revision metadata as a content-free tombstone until account purge. A pending receipt is reconciled before the 30-day response clock starts.

### 3. Canonical tree writes carry a command marker

`TreeDocument` gains an internal `last_command_id` digest marker, not exposed in member API/export. Create/import precompute the complete canonical target (including all resulting IDs and timestamps) before writing the pending receipt; update precomputes its canonical target at the base revision. The receipt stores this dedicated target snapshot, not a duplicate raw request body. Under the command/tree/index locks, each mutation follows:

1. Validate authentication, effective flag, UUID headers and request shape; derive the authenticated owner/method/normalized-route/key scope and request fingerprint without trusting body owner fields.
2. Consult the owner-scoped receipt before reading the live resource. A matching committed receipt replays its exact stored response even if the tree revision advanced or a deleted tree is now absent; a matching pending receipt is reconciled first. A same scoped key with another route/resource/fingerprint returns `409 idempotency_conflict`.
3. Only for a previously unseen key, validate resource ownership/existence and `expected_revision`, then persist a `pending` receipt with deterministic resource ID and target revision. Thus receipt collision/replay precedence is resolved before live-resource `404`/`stale_revision`; an unseen key receives the normal owner-safe `404` or `409 stale_revision`.
4. Atomically write the tree carrying `last_command_id` and target revision, or remove it for delete.
5. Repair/publish the global index.
6. Mark the receipt `committed` with exact status/response and 30-day expiry.

Commands for the same tree/resource serialize behind the existing repository locks plus the receipt-store command guard. A pending command blocks a later command until reconciliation finishes.

### 4. Reconciliation is deterministic at every crash point

Startup maintenance and receipt lookup reconcile pending rows:

- **create/import**: if the precomputed target tree exists with the matching marker, repair the index and commit the reconstructed response; if absent, validate and apply the dedicated pending target snapshot safely.
- **update/rename**: if the tree has the matching marker and target revision, repair the index and commit the response; if it remains at the base revision without that marker, apply the dedicated target snapshot; any other state fails closed as a conflict for operator/forward-fix handling.
- **delete**: the pending row records that owner/revision checks completed. If the tree still exists at that revision, complete deletion and index removal; if absent, repair index absence and commit the content-free tombstone response.
- A malformed receipt store or unreconcilable marker never guesses, widens owner access, or reports success.

Crash-point tests cover failure after pending receipt, tree write/delete, index publication, and receipt commit for every mutation class.

### 5. Correlation IDs are validated at the CRT boundary without breaking legacy callers

Before Stage B relies on caller-generated support references, the CRT facade dependency enforces ADR-0001: absent means use the middleware-generated canonical UUID, valid canonical UUID means retain it, and malformed caller `X-Correlation-ID`/`X-Request-ID` means `400` before CRT handler mutation. Existing non-CRT routes keep their current compatibility behavior in this feature; globally changing their accepted header vocabulary requires a separate caller inventory/migration decision. Tests cover absent, valid and malformed inputs across the CRT facade and unchanged correlation in its error responses.

### 6. Retention and purge

Committed CRT receipts guarantee exact replay of the canonical response body for 30 days and are then redacted in place. The owner-scoped key digest, route, request fingerprint, command and opaque resource/revision metadata remain as a content-free tombstone until account purge, so an old key always fails closed even after a sweep. Normal confirmed deletion redacts earlier receipts for that tree, then commits and retains only its content-free delete tombstone; account purge physically removes every receipt and tombstone.

## Consequences

- Feature delivery has two release checkpoints. Stage B cannot use a pre-Stage-A image as rollback.
- One new SQLite persistence category and maintenance sweep are required, with container, account-purge, backup/restore and test coverage.
- Exact replay duplicates canonical response content for at most 30 days; it is owner scoped, export-excluded and purge-covered.
- File/SQLite writes are not falsely described as atomic. The persisted command marker and deterministic reconciliation close each partial-write state.
- Existing legacy `/api/trees` consumers remain available; Stage A strengthens their revision behavior without exposing the new canvas.
- This persistence/authenticated-route work remains ASK/high and follows ADR-0008's explicit approval and exact-SHA release path.

## Verification

- Downgrade/roll-forward tests mutate a real tree through the Stage A-compatible legacy path and prove revision/schema preservation and monotonicity.
- Crash-point tests prove exactly-once visible mutation and exact replay across tree/index/receipt boundaries.
- Retention tests prove 30-day expiry, confirmed-delete cleanup with tombstone retention, account purge, export exclusion and post-expiry explicit reconciliation.
- CRT-facade dependency tests prove generated, retained valid and rejected malformed correlation IDs while legacy non-CRT caller compatibility remains unchanged.
- Release evidence records Stage A and Stage B SHAs, Stage A production read-back, the permitted rollback image, flag state and recovery drill.
