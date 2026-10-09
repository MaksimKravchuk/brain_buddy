# HTTP API compatibility policy

## Scope and source of truth

Brain Buddy currently exposes one HTTP API under `/api`, used by the browser and,
since the client note below, by the iPhone and Mac apps. The live OpenAPI document at `/api/openapi.json` is
the machine-readable source of truth for future consumers; `/api/docs` is its human
view. Consumers must generate or validate clients from a pinned OpenAPI snapshot,
not from frontend implementation details or persisted JSON files.

`info.version` currently reports the persisted-data schema version for operational
visibility. It is **not yet an independently versioned mobile-client semantic version**.
Before adding a second client, add a separately owned API semantic-version setting and
publish its compatibility window; do not infer client compatibility from a storage
migration alone.

## Client note: iPhone and Mac apps (spec 021, 2026-10-07)

The iPhone and Mac apps call the same `/api` routes as the browser. Every spec 021
change is additive (`desired_outcome`, `archived_at` and `archived_before_lossless` on
projects, `GET /projects?state=`, `POST /projects/{id}/unarchive`, the `X-Client`
header, which only labels log lines) except one: ADR-0020 makes archiving a project
keep its tasks' project membership (PR-03), which older clients did not expect.

Spec 026 adds one more additive field (2026-10-09): `created_at` on `ProjectResponse`
and `TagResponse`. It is the creation instant that orders same-name Smart Add ties
(oldest wins, by `(created_at, id)`). The OpenAPI schema declares it optional, so the
addition stays backward-compatible for generated clients during a rollout or
rollback, but this server always sends it. Clients that ignore unknown response
fields need no change.

**Rollback is forward-only.** Once a build of the shared kit that applies lossless
archive locally exists (PR-04 onward), roll PR-03 forward, never back: a server that
clears memberships again would have the next pull strip them from the apps for good.
Rolling back below PR-02 after PR-03 has run is unsafe too: every task in a project
archived meanwhile would reject edits with 400 until the roll-forward. The release
workflow's automatic rollback goes back only one image, so do not rely on it for
these slices. Details: `specs/021-mac-sync/contracts/http.md` sections 7 and 8.

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

Web password-account controls may send `X-BrainBuddy-Expected-Owner` on the
compatible `/api/account` routes. When present, it must equal the authenticated
session owner; a mismatch returns the generic 404 error before any account
read, export or mutation. Requests without the header retain the existing
password/native wire contract. No client API version bump is required.

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
