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
