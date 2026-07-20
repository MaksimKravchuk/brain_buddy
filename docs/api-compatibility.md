# HTTP API compatibility policy

## Scope and source of truth

Brain Buddy currently exposes one browser-facing HTTP API under `/api`. There is no
mobile/iOS client contract yet. The live OpenAPI document at `/api/openapi.json` is
the machine-readable source of truth for future consumers; `/api/docs` is its human
view. Consumers must generate or validate clients from a pinned OpenAPI snapshot,
not from frontend implementation details or persisted JSON files.

`info.version` currently reports the persisted-data schema version for operational
visibility. It is **not yet an independently versioned mobile-client semantic version**.
Before adding a second client, add a separately owned API semantic-version setting and
publish its compatibility window; do not infer client compatibility from a storage
migration alone.

## Compatibility rules for the current `/api` contract

- Backward-compatible changes add a new endpoint or an optional response/request field.
  Existing fields retain their JSON name, meaning, type, nullability, and constraints.
- An enum value, required field, removed or renamed field, changed validation rule, or
  changed success/error status is a breaking change for generated and strict clients.
  Treat it as a new API version and support the prior version during a documented
  migration window.
- Public operation responses list their intentional failure statuses individually in
  OpenAPI. Do not use a catch-all/default response or broad test exclusion to hide a
  new status.
- Every documented JSON error uses `ErrorResponse`: `message` is required; `detail`
  and `reference_id` are optional. All API responses carry `X-Correlation-ID`, and the
  error `reference_id` equals that response header.
- Auth remains an opaque, HTTP-only cookie session. Future clients must use the
  supported authentication flow rather than assuming bearer-token compatibility.

## Contract change checklist

1. Update route response declarations and Pydantic schemas so `/api/openapi.json`
   describes the new operation and every intentional status.
2. Add a TestClient contract test for the externally observable success/error behavior,
   including `X-Correlation-ID` where applicable.
3. Run the isolated Schemathesis contract test. It calls only an ephemeral ASGI
   `TestClient` app configured with `BRAIN_BUDDY_ENV=test` and a temporary data root;
   it must never target Fly, production, or an arbitrary URL.
4. For a breaking change, publish a migration date, support window, and a versioned
   OpenAPI snapshot before enabling the new behavior for another client.

## Verification ownership

The backend suite treats undocumented statuses, response-schema mismatches,
non-`ErrorResponse` errors, and unhandled `5xx` responses as contract failures.
Allure results attach fuzzed response artifacts under the `Quality spine` / `API
contract` labels so CI keeps contract evidence alongside the normal backend test
artifacts.

## Voice Brain Dump: canonical routes and the mobile operation allowlist

ADR-0002 and ADR-0008 require a canonical proposal-patch → frozen-batch →
confirm sequence with current consent and visible raw-audio retention, plus a
bounded web-compatibility overlap that a second (mobile) client must never
depend on. The canonical routes under `/api/brain-dump-operations/{operation_id}`:

| Method/path | Purpose |
|---|---|
| `GET /brain-dump-processing-policy` | Non-secret, `Cache-Control: no-store` current consent policy version, required provider categories, chunk/operation size limits, and accepted audio formats. |
| `POST .../consent-decisions` | Append-only owner-scoped `grant`/`withdraw` consent decision, bound to an exact policy-version/category-set match and an expiry (`valid_until`). |
| `POST .../proposals/{proposal_id}/patches` | Canonical user proposal `update`/`remove`, checked against the proposal's own `base_proposal_revision` (never silently overwritten) and the operation's `expected_operation_revision`. Supersedes any currently frozen batch. |
| `POST .../proposal-batches` | Freezes the current conflict-free active proposals into an immutable `ProposalBatch` snapshot (target, before/after summary, source cue, confidence/warnings, destination — never a result field). |
| `POST .../confirm` | Idempotently confirms the current frozen batch. Each action derives `H(operation_id, batch_id, action_id)`, persists an append-only immutable receipt, and folds receipts into a separate per-action result projection. No Task exists before this command. |
| `POST .../audio/delete` | Idempotent, restart-safe raw-audio deletion (`deletion_pending` → `deleted`) after processing reaches review or a terminal/cancelled state. Preserves confirmed Tasks, action receipts, and the committed batch snapshot. |

`GET /brain-dump-operations/{operation_id}` additionally projects
`proposal_revision`, `active_proposal_batch`/`committed_proposal_batch`,
`import_mode` (`native_v2` | `legacy_preview_only`),
`accurate_reconciliation_available`, `operation_warning_codes` (for example
`provisional_only`), `provisional_review_accepted_at`, an extended `consent`
object (`status`, `consent_policy_version`, `allowed_provider_categories`,
`valid_until`, `withdrawn_at`), and a `raw_audio` object (`state`,
`retained_until`, `delete_now_available`, `deleted_at`).

### Deprecated web-compatibility aliases

Three routes remain in the full OpenAPI document, `deprecated: true`, and
delegate to the same canonical persisted records above with no bypass of the
provisional-review or freeze/confirm gates:

- `PATCH /brain-dump-operations/{operation_id}/proposals/{proposal_id}` — direct
  proposal edit; use `POST .../proposals/{proposal_id}/patches`.
- `POST /brain-dump-operations/{operation_id}/finish` — transitions to review
  without a canonical seal; use `POST .../seal`.
- `POST /brain-dump-operations/{operation_id}/commit` — atomically freezes the
  current conflict-free active proposals and confirms them in one step (still
  gated by the same explicit `review-provisional` requirement for a
  `legacy_preview_only` import); use `POST .../proposal-batches` then
  `POST .../confirm`.

An active schema-v1 operation is imported once as `legacy_preview_only`
(preserved operation/segment/proposal IDs, `title` locks, and `remove`
tombstones via deterministic synthetic patches). It cannot claim accurate
reconciliation and must go through the explicit `review_provisional` command
before either the canonical `proposal-batches` route or the deprecated
`commit` alias will freeze/confirm it — `manual_review`/
`provisional_review_accepted_at` gates both paths identically. Completed and
cancelled v1 operations are read-only and are never migrated or replayed.

### Mobile operation allowlist

`mobile/scripts/generate-api.sh` fetches the full OpenAPI document to
`mobile/api/openapi.json` (the committed audit/drift copy), then
`mobile/scripts/filter-mobile-openapi.mjs` derives a generation-only
allowlisted subset by dropping every operation the backend marks
`deprecated: true` before `openapi-typescript` ever sees it. This keeps the
mobile client generation allowlist a direct, low-maintenance function of the
same `deprecated` flag used above, rather than a hand-maintained duplicate
list that can drift from the backend's actual routes.
