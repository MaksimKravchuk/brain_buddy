# HTTP and UI Contracts: Miro-like CRT Canvas

**Feature**: `019-miro-like-crt-canvas`
**Base URL**: `/api`
**Auth**: existing same-origin session cookie; every response retains `X-Correlation-ID`.

This contract distinguishes the current API (reused baseline) from the planned compatibility additions. It is not an OpenAPI replacement; implementation must update the Pydantic schemas and route tests named in `plan.md`.

## 1. Current API surface preserved for compatibility

All current routes are implemented in `backend/app/api/routes.py` and are owner-checked through `get_current_user` plus service calls. They remain unchanged and ungated for compatibility with existing consumers. The new canvas never calls these legacy paths directly.

| Method | Path | Current purpose | Compatibility rule |
|---|---|---|---|
| `POST` | `/trees` | Create owner-scoped tree; `201 TreeDetailResponse` | Remains available to existing consumers; not the CRT canvas boundary. |
| `GET` | `/trees` | List owner-scoped trees; `200 TreeListItem[]` | Remains available to existing consumers. |
| `GET` | `/trees/{tree_id}` | Read owner-scoped tree; `200 TreeDetailResponse` | Remains available to existing consumers. |
| `PUT` | `/trees/{tree_id}` | Replace tree using the legacy timestamp token | Retained only for compatibility during the migration window. |
| `DELETE` | `/trees/{tree_id}` | Delete owner-scoped tree; `204` | Remains available to existing consumers. |
| `POST` | `/trees/import` | Import a tree as a fresh tree ID | Remains available to existing consumers. |
| `POST` | `/trees/{tree_id}/export` | Export owner-scoped tree | Remains available to existing consumers. |
| `POST/PATCH/DELETE` | `/trees/{tree_id}/nodes*`, `/relations*` | Legacy low-level graph mutations | Preserved, but the CRT canvas does not mix these with snapshot autosave. |

The existing `/trees/{tree_id}/versions*`, `/validate/*`, and `/ai-feedback` routes are not part of the first-release UI. Do not add client calls for them.

## 2. CRT-specific gated route boundary

The first-release canvas uses a thin `/api/crt/trees` facade over the existing owner-scoped tree services. Every route first requires the authenticated session and an effective ADR-0025 `crt_canvas` flag, then delegates to the existing service/owner checks. This prevents flag gating from changing any legacy `/api/trees` consumer.

| Method | Path | Canvas purpose |
|---|---|---|
| `GET` | `/crt/exposure` | Content-free probe: `204` effective, `404 crt_canvas_disabled`, or `503 feature_flag_unavailable`. |
| `GET` / `POST` | `/crt/trees` | List or create owner-scoped trees. |
| `GET` / `PUT` / `DELETE` | `/crt/trees/{tree_id}` | Load, revision-checked full-snapshot save, or confirmed delete. |
| `POST` | `/crt/trees/import` | Validated import with a fresh tree ID. |
| `POST` | `/crt/trees/{tree_id}/export` | Canonical export/local-backup source. |

All card edits, drag/layout changes, manual Connector operations, Enter/Tab links, relation deletion, and confirmed cascade deletion mutate the local graph first and persist through one debounced full-snapshot `PUT`. The canvas does not call low-level node/relation mutation routes, so one revision token and one canonical response govern every graph edit.

New CRT cards and relations use stable `node_<uuid-v4>` / `relation_<uuid-v4>` IDs generated with `crypto.randomUUID()` before local insertion. The snapshot endpoint validates exact form, uniqueness and base-entity continuity. Existing legacy IDs are accepted only when present in the accepted base revision. Stable IDs make refetch/rebase deterministic after a lost response; they are references, not authorization.

Every mutating CRT facade request requires a canonical UUID `Idempotency-Key`, scoped by authenticated owner, method and normalized route. After authentication, flag/header/request-shape validation and owner-scope derivation, the server fingerprints the request and consults the receipt before live-resource ownership/revision checks. A matching committed receipt returns the original status/body without a second mutation even when the live revision advanced or the tree was deleted; a matching pending receipt reconciles first. Reusing a scoped key with a different route/resource/fingerprint returns `409 idempotency_conflict`. Only an unseen key proceeds to owner-safe resource and revision validation, so idempotency replay/conflict takes precedence over `404`/`stale_revision`. Create, import, snapshot save, rename and delete all use this contract. Durable delete replay uses a content-free owner-scoped tombstone receipt.

## 3. Planned tree contract additions

### `TreeDocument` / `TreeDetailResponse`

Keep all existing fields and add:

```json
{"id": "tree-opaque-id", "name": "Current reality", "revision": 7, "schema_version": 1, "metadata": {}}
```

- `revision` is a positive integer and is the preferred optimistic-concurrency token.
- `schema_version` is the import/export envelope version. Existing payloads that omit it are treated as version 1 during the compatibility window.
- Top-level `schema_version` is authoritative. If both it and legacy `metadata.version` are present they must match; a missing top-level value inherits a supported `metadata.version`, or version 1 when both are absent. Conflicting or unsupported values are rejected before mutation.
- Both fields are top-level in storage, API responses, import/export and local canonical snapshots; they are not nested in `metadata`.
- Internal `last_command_id` is never part of `TreeDetailResponse`, tree export/import, account export, logs or metrics. API/export serializers use explicit public projections rather than dumping the complete `TreeDocument`.
- `metadata.updated_at` remains present and is not removed.
- `metadata.layout` remains an object, but CRT-written fields use the `ViewportState` shape in `data-model.md`; owner/origin-scoped `LastTreePreference` remains browser-local.

### `PUT /crt/trees/{tree_id}`

Extend `TreeUpdateRequest` with:

```json
{
  "expected_revision": 7,
  "schema_version": 1,
  "name": "Current reality",
  "metadata": {
    "version": 1,
    "created_at": "2026-09-19T10:00:00Z",
    "updated_at": "2026-09-19T10:05:00Z",
    "layout": {"zoom": 1, "center": {"x": 0, "y": 0}},
    "owner_id": null
  },
  "nodes": [],
  "relations": [],
  "owner_id": null
}
```

Contract rules:

- The authenticated owner is authoritative; `owner_id` in the body is ignored/rejected as it is today for import/create paths.
- `expected_revision` is required on the CRT facade and must equal the server's top-level revision. Only the legacy `/trees/{tree_id}` route keeps timestamp fallback during the compatibility window.
- `schema_version` and `metadata.version` must both be `1` and match on CRT writes during this release.
- Every card label is trimmed and must remain non-empty. A whitespace-only snapshot returns `400 detail.reason = "empty_card_label"` with correction guidance and no mutation; the client keeps that card in edit mode.
- Success returns the complete canonical `TreeDetailResponse` with the incremented revision.
- Stale revision returns `409` and the existing error envelope:

```json
{
  "message": "This tree has newer changes; review the conflict before saving.",
  "detail": {
    "reason": "stale_revision",
    "tree_id": "tree-opaque-id",
    "current_revision": 8,
    "current_updated_at": "2026-09-19T10:06:00Z"
  },
  "reference_id": "correlation-uuid"
}
```

The server does not return the other owner's content in an error. The frontend refetches the owner-scoped canonical tree separately for D-03 comparison.

## 4. Exposure contract

The existing `/api/auth/me` response already returns `feature_flags: Record<string, boolean>`. Add the server-owned key:

```json
{"feature_flags": {"crt_canvas": false}}
```

Rules:

- Missing `crt_canvas` is OFF in the frontend.
- Effective `false` hides navigation. A direct `/crt` entry or an already-open canvas performs the content-free `/crt/exposure` probe so normal disabled and degraded service remain distinguishable without requesting tree content; no CRT mutation is sent.
- Effective `true` is still not authorization; session authentication and owner checks remain mandatory.
- Normal OFF/not-selected resolution returns `404` with `detail.reason = "crt_canvas_disabled"` and `X-Correlation-ID` on every `/api/crt/*` route. Degraded/unreadable runtime flag storage returns `503` with `detail.reason = "feature_flag_unavailable"`; it never collapses to an ordinary disabled decision. Neither response contains tree content. The client preserves pending work locally, transitions to the appropriate unavailable state, stops further mutation attempts, and waits for a successful refreshed `/auth/me` exposure before retrying. Once admitted by the flag, wrong-owner tree IDs remain indistinguishable `404` responses without either flag reason.
- Generic admin endpoints remain the existing contracts: `GET /admin/feature-flags`, `PUT /admin/feature-flags/{flag}/mode`, `POST /admin/feature-flags/{flag}/selected-users`, and `DELETE /admin/feature-flags/{flag}/selected-users/{account_id}`. Adding the flag to the managed allow-list is sufficient to make it appear there; no new operator endpoint is planned.

## 5. Import/export contract

`POST /crt/trees/import` keeps the current fresh-tree-ID behavior and owner stamping. Before the current tree changes, the frontend must pass the pending-work barrier: successfully save/retry or explicitly discard after named-loss confirmation; backup download is offered but optional. Import is disabled while a save or canonical refetch is unresolved.

Import validation is atomic and ordered:

1. Parse JSON and validate `schema_version`.
2. Validate non-empty tree name/card labels and supported field shapes.
3. Validate every relation endpoint exists.
4. Reject self-links, duplicate ordered pairs, and cycles.
5. Allocate fresh `node_<uuid-v4>` / `relation_<uuid-v4>` IDs for every validated imported entity and rewrite relation endpoints through that complete mapping.
6. Only then call the existing import service.

A rejection leaves the current visible graph and local draft unchanged. Existing legacy exports therefore round-trip by content/topology/direction into a fresh tree even though imported entity IDs change. Export uses the canonical owner-scoped server response; a local conflict backup uses the same envelope but is explicitly labeled local and is never auto-applied.

## 6. Client API shape

Extend `frontend/src/api/client.ts` with typed operations rather than ad hoc `fetch` calls:

```text
listCrtTrees(signal?)
probeCrtExposure(signal?)
getCrtTree(treeId, signal?)
createCrtTree(payload, { idempotencyKey })
updateCrtTree(treeId, { expected_revision, schema_version, ...snapshot }, { idempotencyKey })
deleteCrtTree(treeId, { expectedRevision, idempotencyKey })
importCrtTree(payload, { idempotencyKey })
exportCrtTree(treeId, signal?)
```

`DELETE /crt/trees/{tree_id}` additionally requires `expected_revision` as a query parameter. A stale value returns `409 stale_revision` and leaves the tree intact. List, get and export are reads: they use correlation/timeout handling but no idempotency key or revision precondition. Rename is a revision-checked full-snapshot `PUT`, not a separate unguarded route.

These names are planned client methods, not current APIs. Their tests must prove same-origin credentials, JSON headers and correlation-ID propagation through `ApiError`. React Query hooks must scope query keys by authenticated owner ID and API origin so account changes cannot reuse another account's cache.

Every CRT request generates a UUID correlation value before `fetch`, sends it as `X-Correlation-ID`, and retains it in `ApiError` even when no response arrives. ADR-0026 validates this at the CRT facade without changing legacy non-CRT callers: absent input uses the middleware-generated canonical UUID, a canonical caller UUID is retained, and malformed `X-Correlation-ID`/`X-Request-ID` returns `400` before CRT handler mutation. Every mutation separately generates a UUID `Idempotency-Key` and, when browser storage is available, durably retains its captured request until the outcome is resolved. If storage is unavailable/full, the exact request/key and newer commands remain in memory only: online save and same-page retry continue, while the UI states that reload/close/crash recovery is unavailable and never claims protection. CRT reads use a bounded 15-second timeout and mutations a bounded 30-second timeout by composing the caller signal with an internal `AbortController`; timeout is a retryable save/load failure, not a silent cancellation. This makes the support reference available for network failures and timeouts as well as HTTP error responses.

Controls are disabled while create/import/delete is in flight. Snapshot editing remains responsive: each request captures an immutable generation while newer domain commands queue locally. Retry sends the exact captured body and key; the original replay response is installed as the canonical base, then queued commands are replayed by stable IDs and saved under a new key. Refetch is diagnostic and conflict input, never a reason to discard queued edits. Tests cover commit-success/response-loss and new edits during the in-flight request.

Under ADR-0026, idempotency receipts are Thinking/CRT-owned records in `crt_commands.sqlite3`. Pending → tree/index → committed writes use a persisted tree command marker and deterministic crash reconciliation rather than claiming a cross-store transaction. Committed receipts guarantee exact replay for 30 days, then are swept; after expiry the client must refetch and explicitly reconcile instead of blindly repeating a mutation. Normal confirmed deletion scrubs prior content-bearing receipts for that tree, commits and retains only the new content-free delete tombstone for its replay window; account purge removes all owner receipts including tombstones. Receipts are excluded from account/tree export as transient duplicates and never log raw graph text. Replayed response bodies receive canonical-tree access controls; delete tombstones contain only owner/key/route/fingerprint/status/timestamps and no deleted graph content.

## 7. Error and observability contract

- All failed requests preserve `X-Correlation-ID`; the UI exposes it as copyable support reference when a request occurred.
- `400` is used for invalid graph/import input; `404` for missing/wrong-owner resources or normal ineffective exposure; `409` for stale canonical revision/idempotency conflict; `401` for missing/expired session; `503 feature_flag_unavailable` for degraded runtime flag storage.
- No response, log, metric, or test fixture contains credentials, cookies, raw audio, transcript content, or content fingerprints.
- Logs/metrics use tree ID, operation, revision, outcome, retryable/error code, duration, and correlation ID; never card labels or graph text.
- CRT observability records inherit the hosting platform's log retention, are excluded from account export, and cannot be erased by application account purge. After purge, opaque tree/account references no longer resolve in application storage. Logs never contain owner email/display name, card labels, graph text, request/response bodies, request hashes, idempotency keys, content fingerprints, credentials, or local paths.

## 8. Keyboard and accessibility UI contract

The rendered route must realize the signed-off design states and preserve the following interaction contract:

- Canvas shortcut mode is explicit and composite. Enter creates a cause below the selected effect; Tab creates a same-level sibling only when shortcut mode is active; Escape leaves shortcut mode so ordinary browser Tab navigation resumes.
- While a text field, menu, dialog, or native control is focused, Enter/Tab/Delete/arrows/plus/minus/zero/Space retain native behavior.
- Manual Connector remains available in the tool rail and by card handles.
- Controls have accessible names, visible focus, live-region announcements, and dialog semantics (`role=dialog`, `aria-modal`, labelled heading, trapped focus, safe initial focus).
- Root/effect/intermediate meaning, selection, warning, offline, error, and partial states use text/icon/border/announcement in addition to color.

Screen/state trace: D-01 loaded canvas; D-02 first run/menu; D-03 conflict review; D-04 keyboard/inspector; D-05 system states; D-06 destructive confirmation.
