# Data Model: Miro-like CRT Canvas

**Feature**: `019-miro-like-crt-canvas`
**Canonical owner**: Thinking/CRT module, using the existing tree aggregate
**Compatibility rule**: Existing stored trees remain readable; new UI semantics do not require `parent`/`child` node types.

## 1. Tree

The existing `TreeDocument` in `backend/app/schemas/domain.py` remains the canonical persisted aggregate. The API-facing form is `TreeDetailResponse` in `backend/app/schemas/api.py`. Both `revision` and `schema_version` are top-level fields on those two models; they are never nested inside `metadata`.

| Field | Type | Required | Rules |
|---|---|---:|---|
| `id` | opaque string | yes | Server-generated; import gets a fresh tree ID. |
| `title` / API `name` | string | yes | Trimmed, non-empty; tree menu rename uses the same validation. |
| `owner_id` | opaque string | yes in persisted record | Derived from the authenticated session; never trusted from create/import input. |
| `created_at` | UTC datetime | yes | Immutable after creation. |
| `updated_at` | UTC datetime | yes | Monotonic server timestamp; retained for compatibility and diagnostics. |
| `revision` | integer | yes for new responses | Starts at 1 and increments exactly once per successful persisted aggregate mutation, including validation/version-reference writes and restore. Old records read as revision 1 until first write. |
| `schema_version` | integer | yes in the canonical envelope | Bumps only for incompatible payload changes; import rejects unsupported versions before mutation. |
| `nodes` | `Card[]` | yes | Current graph members. |
| `relations` | `Relation[]` | yes | Directed acyclic source-to-target links. |
| `metadata.layout` | object | optional | Existing arbitrary layout block remains readable; CRT writes only the versioned viewport/layout fields defined below. |
| `version_refs` | existing `TreeVersionRef[]` | yes in storage | Preserved but not exposed in the first-release UI. |
| `last_command_id` | SHA-256 digest string or null | internal storage only | ADR-0026 crash-reconciliation marker. Explicitly excluded from all member API responses, tree export, account export, logs and metrics. |

### Tree invariants

- Every tree read, mutation, import, export, and delete is authenticated and owner-scoped. A wrong-owner ID remains an indistinguishable 404.
- `source_id`/`source_node_id` is the cause; `target_id`/`target_node_id` is the effect. Position is presentation and never changes relation direction.
- A successful save includes the client `expected_revision`; a stale value returns 409 without changing the tree.
- Deleting a tree is a confirmed user action. Local pending work must be saved/retried or explicitly discarded after a named-loss confirmation; a local backup is offered before discard but is not mandatory.

## 2. Card (existing NodeDocument / NodeResponse)

The product calls nodes **cards**. The existing node schema is reused and narrowed for CRT behavior.

| Field | Type | Required | Rules |
|---|---|---:|---|
| `id` | opaque string | yes | Existing IDs remain opaque. A new CRT card receives `node_<uuid-v4>` from `crypto.randomUUID()` before local insertion; the server validates the exact form and uniqueness. IDs are references, never authorization. |
| `label` | string | yes | Trimmed and non-empty. Whitespace-only labels remain in edit mode and cannot be saved; request-body limits provide the outer bound. |
| `position` | `{x: number, y: number}` | yes | Canvas coordinates; generated placement must avoid overlap using the nearest free grid slot. |
| `metadata.created_at` / `updated_at` | UTC datetime | yes | Server-maintained. |
| `type` | legacy `parent` or `child` wire value | compatibility only | Existing cards retain their stored value through every CRT snapshot. Only newly created CRT cards use the fixed compatibility value `child`. CRT never derives user semantics, layout, or colors from it. |
| `highlight_state` | legacy enum | compatibility only | Existing cards retain their stored value through every snapshot; new CRT cards use `none`. CRT semantic rendering uses topology and explicit text, not this legacy field. |
| `extra` | object | optional | Existing storage extension point; no raw user data is added for this feature. |

### CRT semantic projection

The frontend derives a presentation-only semantic label from graph topology:

- **Effect**: no outgoing relation (red effect treatment plus text label).
- **Root cause**: no incoming cause relation (yellow root-cause treatment plus text label).
- **Intermediate**: both incoming and outgoing relations (white treatment).
- A disconnected card is labeled explicitly as disconnected; if it qualifies as both root and effect, the UI uses text and a non-color marker to explain the state.

This projection does not alter the persisted node type and never changes relation direction.

## 3. Relation

The existing `RelationDocument`/`RelationResponse` and `RelationService` remain the canonical link model.

| Field | Type | Required | Rules |
|---|---|---:|---|
| `id` | opaque string | yes | Existing IDs remain opaque. A new CRT relation receives validated `relation_<uuid-v4>` identity before local insertion. |
| `source_node_id` | opaque string | yes | Existing card in the same owner-scoped tree; semantic cause. |
| `target_node_id` | opaque string | yes | Existing card in the same tree; semantic effect. |
| `kind` | `"why"` | yes | Existing supported kind; no new relation kinds in this release. |
| `created_at` | UTC datetime | yes | Server-maintained. |
| metadata/notes | existing fields | compatibility | Retained on full-tree replacement by `TreeService`. No relation-label editor is added. |

### Relation invariants

- Self-link, duplicate ordered pair, missing endpoint, and cycle are rejected before persistence.
- Manual Connector remains available. Enter/Tab are convenience commands that call the same relation creation path and use the same validation.
- Removing a relation never removes cards. Removing a connected card requires explicit cascade confirmation.
- SVG/graph-library edge geometry is derived from current card positions; geometry is not persisted as a second relation model.

### Stable offline identity protocol

- New CRT cards and relations receive collision-resistant UUID-v4 IDs before local insertion. The same stable IDs are used by offline drafts, relations, selection, history and full snapshots, so a committed save followed by a lost response needs no identity remapping.
- The server accepts a new ID only when it matches the exact CRT UUID form, is unique in the submitted graph, and did not replace a different base entity. Existing legacy IDs remain valid only when they occurred in the accepted base revision. Endpoint and graph invariants are validated before atomic persistence.
- Client-chosen IDs are not trusted for authorization: authentication, owner scope and revision checks remain mandatory. Legacy low-level create routes continue using server-generated IDs.

## 4. Last-tree preference and viewport state

Both are convenience state, not graph ownership. Only last-tree identity is owner/origin-scoped browser preference.

```text
LastTreePreference {
  owner_id: opaque string
  origin: normalized browser origin
  last_tree_id: opaque string | null
  updated_at: UTC datetime
}

ViewportState {
  tree_id: opaque string
  zoom: number          # bounded by the graph library's supported range
  center: { x: number, y: number }
  updated_at: UTC datetime
}
```

`last_tree_id` is stored under the normalized origin and authenticated owner ID. On entry, the client lists owner-scoped trees first, uses the preference only when its ID occurs in that list, otherwise selects the most recently updated tree, and then updates the preference. A missing/deleted/wrong-owner ID is cleared and never causes content to render without an owner-scoped server read.

The preference expires 30 days after `updated_at`. Startup, focus and the bounded cleanup interval remove expired preference bytes without using them. Same-browser sign-out, account switch and account deletion remove every preference for the departing owner on the active origin together with that owner's CRT draft keys. Preferences are browser-local and deliberately absent from server export.

Accepted `ViewportState` is persisted in the existing `TreeMetadata.layout` block and in a local draft. Normal route entry always fits all cards into the unobscured viewport; canonical center/zoom does not override that acceptance rule and is not copied into the owner/origin browser preference. Draft/conflict recovery restores the draft viewport only after the user chooses that draft, retaining the interrupted local context.

## 5. Local pending draft

Local drafts are browser recovery records, not new product records and not an account export substitute.

```text
PendingDraftEnvelope {
  schema_version: 1
  owner_id: opaque string
  origin: normalized browser origin
  tree_id: opaque string | null
  create_idempotency_key: UUID | null
  base_revision: integer | null
  base_updated_at: UTC datetime | null
  local_updated_at: UTC datetime
  writer_session_id: UUID
  generation: integer
  tree: { name, nodes, relations, layout }
  dirty_operations: DraftOperationSummary[]
  in_flight_save: { idempotency_key, base_revision, generation, snapshot } | null
  queued_commands: CrtCommand[]
}
```

Rules:

- Storage key is namespaced by application, origin, owner ID, and canonical tree ID or pre-canonical create idempotency key; use a deterministic key, not a user-content hash.
- One editable tab owns each owner/origin/tree draft through an exclusive Web Lock named from that non-content scope. The owner tab stamps `writer_session_id` and monotonically increasing `generation`, checks generation before write/clear, and broadcasts changes through `BroadcastChannel` plus the `storage` event. A second tab cannot edit or clear the draft: it shows “This tree is open in another tab” and may retry ownership only after the lock releases. If Web Locks are unavailable, durable multi-tab editing fails closed to one in-memory owner tab and the UI makes the no-cross-tab-recovery limitation visible.
- A pre-canonical draft is created only after an online user explicitly requests a new tree. It retains the requested name while `POST /crt/trees` is unresolved or failed; offline first-run creation remains disabled. Retry uses the exact same `Idempotency-Key`. Rekey is a recoverable copy-and-verify protocol, not a false multi-key transaction: write the canonical key with one `migration_id`, read it back, then replace/remove the source. Startup scans both keys, deduplicates by `migration_id`, prefers a valid canonical copy, and preserves the source when quota/write verification fails. Only after verified canonical ownership does graph editing begin.
- Do not read/apply a draft unless its owner ID and origin equal the active authenticated scope.
- Successful canonical save clears the draft only after the response has been accepted and applied to the visible graph.
- Failed or timed-out save retains the draft and records a retryable error/correlation reference in UI state, not in the durable draft content.
- When browser storage is available, starting a save durably records its exact immutable request snapshot, hash, base revision, edit generation and `Idempotency-Key`. Edits made while that request is in flight append replayable domain commands to `queued_commands` and update the visible draft; they are never overwritten by the older response.
- When browser storage is unavailable/full, the same request/key and newer command queue exist in memory for the lifetime of the page only. Online save and same-page retry continue, but the UI persistently states that reload/close or a browser crash can lose unsynchronized work, blocks destructive navigation with that named risk, and never claims durable recovery. A reload cannot reconstruct an unresolved request in this branch.
- A local draft expires after 30 days without `local_updated_at` advancing. On the next startup/focus/cleanup pass it is not auto-applied: a stale-recovery sheet offers local JSON backup, explicit recovery (which resets the 30-day clock), or discard before physical deletion. If BrainBuddy never runs again, browser/site-data backups may retain bytes until the user clears site data; the server cannot erase them.
- Recovery retries the exact in-flight request/key first. Same key and hash returns the original committed response; same key with different content is rejected. The client installs that response as a new base, replays queued commands by stable IDs, preserves selection/history references, writes the rebased draft, and then sends a new keyed save. A replay failure enters conflict with both copies retained.
- Before same-browser sign-out, account switch, or account deletion, enumerate every CRT draft, in-flight request, and pre-canonical draft for the departing owner on the active origin. Resolve each pending-work barrier by successful save/retry or explicit named-loss discard, then remove all of that owner's active-origin CRT keys while preserving other owners/origins. If enumeration or any cleanup fails, cancel/fail closed before the next account can enter CRT and do not claim cleanup. A server-side purge cannot erase storage in another browser/device and this feature makes no such claim. Drafts are excluded from server account export because they are local recovery state; canonical trees retain existing export/purge coverage.
- `dirty_operations` is for human-readable D-06 loss descriptions; it must not be treated as a server merge log.
- `queued_commands` is a bounded client-side rebase journal only for edits newer than an immutable in-flight snapshot; it is never sent as a server merge log and is compacted after each accepted save.

## 6. Save and recovery state

The frontend state machine is separate from the canonical graph:

```text
clean/saved
  -> saving                 local mutation queued
  -> saved                  accepted canonical response
  -> unsaved                local mutation before autosave
  -> offline-local          request unavailable and local draft retained
  -> save-error             request failed; retry available
  -> conflict               server revision newer; both copies retained
  -> recovering             local draft/canonical comparison in progress
```

Allowed recovery choices:

- `keep-local-and-retry`: retain local graph and retry against the latest canonical revision only after explicit review when the server changed.
- `use-server`: require D-06 confirmation, optionally download a local backup, then replace visible graph and clear the draft.
- `defer`: leave both copies preserved and keep the conflict state visible.

No state may render “Saved” until the server response has been applied. A browser reload with a pending draft must not silently replace newer canonical data.

## 7. History snapshot

Undo/redo is a frontend editing-session concern. A history entry contains an immutable graph/layout snapshot and selection context. It is not the existing server version/snapshot entity.

- Track card create, label edit, move, relation create/delete/update, card cascade delete, and other graph/layout commands in the current editing session. Tree create/switch/import establishes a new history session; tree rename is a menu mutation outside graph history.
- Undo/redo changes the visible graph and marks it unsaved; it does not bypass optimistic concurrency or local draft retention.
- View-only pan/zoom changes do not create graph history entries, but accepted viewport state may be stored in canonical layout and a pending draft for recovery.

## 8. Feature exposure

```text
CrtExposure {
  flag: "crt_canvas"
  mode: "off" | "selected_users" | "on"
  effective_for_user: boolean
}
```

This is server-owned control state, not a persisted tree field and not authorization. The member-facing `/api/auth/me` response exposes only the effective boolean. The admin view uses the existing generic runtime feature-flag contract.

## 9. Migration/compatibility rules

1. Existing `TreeDocument` files lacking top-level `revision` or `schema_version` are read in memory as revision 1/schema version 1; the first successful write emits both top-level fields. Every successful persisted aggregate mutation—including legacy node/relation changes, validation-state writes, version-reference changes and version restore—advances revision exactly once. API responses and exports use the same top-level placement.
2. Existing `parent`/`child` node values and legacy highlight fields round-trip unchanged through CRT full-snapshot saves. The server ignores attempted compatibility-field changes for existing cards; only new CRT cards receive `type=child` and `highlight_state=none`. New CRT behavior ignores both fields for semantics.
3. Existing import/export payloads remain valid when they omit the new fields; new exports include them. Import validates the complete legacy graph, then atomically allocates fresh CRT UUID card/relation IDs and rewrites every endpoint through one mapping before creating the fresh tree; user content, topology and direction are preserved, while imported identifiers are not. Unsupported `schema_version`, missing endpoints, duplicate relations, cycles, and malformed JSON are rejected before replacing the current tree.
4. Existing version, validation, and account export/purge records remain owned by their current services. No version UI or AI validation call is added to the CRT surface.
5. The local draft schema is independently versioned. An incompatible draft is preserved as a downloadable backup and not applied automatically.
