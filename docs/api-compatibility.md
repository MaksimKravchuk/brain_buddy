# HTTP API compatibility policy

## Scope and source of truth

Brain Buddy exposes one HTTP API under `/api`, consumed by the browser and the bounded
Expo mobile client. The backend Pydantic/OpenAPI document is the machine-readable source
of truth; `/api/docs` is its human view. `mobile/api/openapi.json` is the committed mobile
snapshot and `mobile/src/api/generated/openapi.generated.ts` is its generated transport surface.
Both are generated from an ephemeral in-process test app, never from a live server,
Fly, production, or an arbitrary URL.

`info.version` is the independently owned API semantic version. It is not the persisted
data schema version (which remains available from health/operational reporting). Mobile
compatibility is constrained by the committed snapshot and semantic drift gate; a breaking
change requires a versioned migration/support-window decision rather than an implicit
storage migration.

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
- Browser auth remains an opaque, HTTP-only cookie session. The mobile client establishes
  the same server-owned opaque session through `POST /api/auth/mobile/sessions`, stores
  only its returned token in SecureStore, and sends
  `Authorization: Bearer <opaque-session-token>`. This is not a JWT and does not create
  a second identity model.

## Contract change checklist

1. Update route response declarations and Pydantic schemas so `/api/openapi.json`
   describes the new operation and every intentional status.
2. Add a TestClient contract test for the externally observable success/error behavior,
   including `X-Correlation-ID` where applicable.
3. Run the isolated Schemathesis contract test. It calls only an ephemeral ASGI
   `TestClient` app configured with `BRAIN_BUDDY_ENV=test` and a temporary data root;
   it must never target Fly, production, or an arbitrary URL.
4. First run `cd backend && uv sync --locked --extra dev` so generation uses the exact
   `uv.lock`-pinned FastAPI/Pydantic versions the committed snapshot was generated
   against; an unlocked `pip install` can silently resolve a newer minor version and
   produce a semantically different (but still "valid") OpenAPI document, which is the
   drift this step exists to prevent. Then regenerate with `cd mobile && npm run
   api:generate` (it activates `backend/.venv` automatically when present), and run
   `cd backend && python -m scripts.openapi_snapshot check --snapshot ../mobile/api/openapi.json`.
   The generator creates an ephemeral test-mode app with a temporary data directory;
   it does not make a network request. `git diff --exit-code -- mobile/api/openapi.json
   mobile/src/api/generated/openapi.generated.ts` is the generated-client drift gate. CI enforces
   the same locked install (`.github/workflows/ci.yml`, mobile job) so a fresh runner
   reproduces the committed artifacts deterministically.
5. For a breaking change, publish a migration date, support window, and a versioned
   OpenAPI snapshot before enabling the new behavior for another client.

## Verification ownership

The backend suite treats undocumented statuses, response-schema mismatches,
non-`ErrorResponse` errors, and unhandled `5xx` responses as contract failures.
Allure results attach fuzzed response artifacts under the `Quality spine` / `API
contract` labels so CI keeps contract evidence alongside the normal backend test
artifacts.
