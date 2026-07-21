# HTTP API compatibility policy

## Scope and source of truth

Brain Buddy exposes one HTTP API under `/api`, consumed by the browser and the bounded
Expo mobile client. The backend Pydantic/OpenAPI contract is the source of truth; the
live `/api/openapi.json` and `/api/docs` are views of it. Consumers generate or validate
from the committed `openapi/brainbuddy-v1.json` snapshot, never frontend implementation
details or persisted JSON files. `scripts/generate_openapi.py` deterministically builds
that snapshot from an ephemeral test app and temporary data root; `--check` verifies the
committed bytes without writing them.

`info.version` is the independently owned API semantic version (`1.0.0`), while
`/health.schema_version` reports persisted-data schema version. Do not infer mobile
compatibility from a storage migration alone.

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

`mobile/scripts/generate-api.sh` regenerates and checks the pinned committed
snapshot, then copies it to `mobile/api/openapi.json` as the committed audit/drift copy.
Before `openapi-typescript` runs, `mobile/scripts/filter-mobile-openapi.mjs` derives the
generation-only `mobile/api/openapi.mobile.json` using an explicit bounded
`(method, path)` allowlist. A new non-deprecated backend route is therefore not exposed
to mobile accidentally. The filter also hard-excludes the deprecated direct proposal
`PATCH`, `/finish`, `/commit`, `/transcript`, the untyped action dispatcher, and Smart
Add even if a future change tries to allowlist one. Deprecated operations are excluded,
but "drop deprecated" is not the mobile contract or its enforcement mechanism.
