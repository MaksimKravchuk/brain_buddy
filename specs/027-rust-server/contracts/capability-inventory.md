# Capability inventory: current Python/FastAPI server (027-FR-001)

> **Superseded in part (2026-10-15)**: [ADR-0033](../../../docs/decisions/0033-remove-task-priority.md) removes task priority. Every
> task-priority field, value, filter, sort and control in this document is withdrawn.

Derived from code at commit `3764dfc6`. Every row cites the code that defines the
behavior; docs were not used as a source. Paths are relative to `backend/` unless
they start with `../`. The API prefix is `BRAIN_BUDDY_API_PREFIX`, default `/api`
(`app/core/config.py:1242`), written as `/api` below.

Mount order (`app/main.py:590-622`), which is also FastAPI's match order:

1. `CorrelationIdMiddleware` wraps the whole app, MCP mount included (`main.py:590`).
2. Exception handlers (`main.py:591`, `app/api/errors.py:133`), then review handler (`main.py:602`, `app/api/review.py:61`).
3. `modern_auth_router` at `/api` (`main.py:600`).
4. `cli_auth_router` at `/api` with its own prefix `/auth/device` (`main.py:601`, `app/api/cli_auth.py:17`).
5. `auth_router` at `/api/auth` (`main.py:603`).
6. `account_router` at `/api/account` (`main.py:604`).
7. `admin_router` at `/api/admin` (`main.py:605`).
8. `api_router` at `/api` (`main.py:606`). This is `app/api/routes.py:54` (trees and CRT, registered first) with `tasks`, `review`, `review_navigator`, `review_flow`, `agents` routers appended in that order (`app/api/__init__.py:12-18`).
9. Sync routers at `/api`, each with prefix `/sync/v1`, `include_in_schema=False`, `route_class=SyncRoute`: `sync`, `sync_delta`, `sync_snapshots`, `sync_hints` (`main.py:607-610`).
10. MCP Starlette sub-app mounted at `/api/mcp`, only when `BRAIN_BUDDY_MCP_ENABLED=1` (`main.py:621-622`, `app/api/mcp.py:248`).
11. `/health` and `/api/health` (`main.py:624-632`).

## Legend

**Auth**

| Code | Meaning | Source |
|---|---|---|
| `S` | Session cookie `brainbuddy_session` resolved by `get_current_user`. Missing, unknown or expired gives 401 `Authentication required.` A session is also rejected (and deleted) when `auth_version` changed, deletion is pending, an operator email used a non-password method, or a Google/Apple binding is not active. | `app/api/dependencies.py:160-177`, `app/services/auth_service.py:179-212` |
| `S+lock` | `S`, then hold the per-owner CRT command lock and re-read the account. A missing account or pending deletion gives 404 `NotFoundError("Account")`. | `dependencies.py:180-197` |
| `S/svc` | The session cookie is passed raw to `ModernAuthService`, which decides whether it is required. It may be optional (login flows) or mandatory (account methods). | `app/api/modern_auth.py:70-71` |
| `OP` | Operator: valid session **and** email in `BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS`. Gives 401, then 403 `Not authorized.` Denials are logged with the route template only. | `dependencies.py:304-359` |
| `BEARER` | `Authorization: Bearer <session token>` (the same opaque session token), MCP only. Cookies are never read. | `app/api/mcp.py:54-75` |
| `PUSH` | Per-run capability token in the URL path, compared in constant time. No session. | `app/api/agents.py:477-523` |
| `DEVICE` | CLI device-flow `device_code` in the body. No session. | `app/api/cli_auth.py:143-165` |
| `none` | Unauthenticated. | |

**Owner scope.** `owner` means every service call passes `owner_id=current_user.id` and
foreign ids resolve as 404. `owner(assert)` means `tree_service.assert_owner(tree_id, owner)`
runs before a tree-scoped service call (`app/api/routes.py:349-560`).

**Flag gates.** Unless stated otherwise these are runtime-managed flags resolved per user by
`FeatureFlagService.is_effective` (SQLite store; `app/repositories/feature_flag.py:83-93`).
Each gate gives a fail-closed 404 to an authenticated user without the flag, after the 401
check.

**Idempotency.** `Idem` means the `Idempotency-Key` header is required. If it is missing
the response is 400 `ValidationFailure` (`app/api/tasks.py:241`, `app/api/review.py:164`,
`app/api/agents.py:107`). On CRT routes it must be a canonical UUID
(`app/api/routes.py:573-591`).

## 1. HTTP routes

### 1.1 Platform, health, docs, MCP mount

| ID | Method | Full path | Handler | Auth | Owner scope | Gate | Surface | Notes |
|---|---|---|---|---|---|---|---|---|
| CAP-HTTP-001 | GET | `/health` | `app/main.py:624` | none | n/a | none | health | `{"status":"ok","environment":<env>,"schema_version":<data/schema_version>}`. Fly and compose health checks probe this path (`../fly.backend.toml`, `../compose.yaml`). Outside `/api`. |
| CAP-HTTP-002 | GET | `/api/health` | `app/main.py:625` | none | n/a | none | health | The same handler and payload. |
| CAP-HTTP-003 | GET | `/api/openapi.json` | `app/main.py:452` | none | n/a | none | docs / version | FastAPI-generated. `info.version` = schema_version (`main.py:451`). Sync routes are excluded (`include_in_schema=False`). Exposed in every environment. |
| CAP-HTTP-004 | GET | `/api/docs` | `app/main.py:453` | none | n/a | none | docs | Swagger UI. |
| CAP-HTTP-005 | GET | `/api/docs/oauth2-redirect` | `app/main.py:453` (FastAPI default) | none | n/a | none | docs | Implicit when `docs_url` is set. |
| CAP-HTTP-006 | GET | `/api/redoc` | `app/main.py:454` | none | n/a | none | docs | ReDoc. |
| CAP-HTTP-007 | POST, GET, DELETE | `/api/mcp/` (sub-app root; `streamable_http_path="/"`) | `app/api/mcp.py:238-256` | BEARER, scope `tasks` | owner | env `BRAIN_BUDDY_MCP_ENABLED=1`; flag `task_mcp` (no flag gives an empty scope, so `RequireAuthMiddleware` refuses) | MCP | Stateless streamable HTTP with JSON responses (`mcp.py:87-94`). Host allow-list is `BRAIN_BUDDY_MCP_ALLOWED_HOSTS`; `allowed_origins=[]`. App exception handlers do not apply inside the mount. Tools are in section 2. |

### 1.2 Modern auth (email links, Google, Apple) and account auth methods (`app/api/modern_auth.py`)

All POST routes marked `JO` carry `dependencies=[Depends(json_origin)]`. If `Origin` is present
and not equal to `BRAIN_BUDDY_AUTH_PUBLIC_ORIGIN`, or `Sec-Fetch-Site` is not `same-origin` or
`none`, the response is 403 `invalid_proof`. If `Content-Type` is not `application/json`, it is
400 (`modern_auth.py:55-67`). Errors use `{message, detail:{code}}` (`errors.py:101-112`).
Availability comes from config, not flags (`app/services/modern_auth_service.py:147-155`).

| ID | Method | Full path | Handler | Auth | Owner scope | Gate | Surface | Notes |
|---|---|---|---|---|---|---|---|---|
| CAP-HTTP-010 | GET | `/api/auth/methods?client=` | `modern_auth.py:102` | none | n/a | config | auth | Reports Google, Apple (web or native per `client`) and email availability. |
| CAP-HTTP-011 | POST | `/api/auth/email/request` | `modern_auth.py:111` | S/svc (optional) | n/a | JO; email configured | auth | 202 `ChallengeResponse`. Keyed by client IP. Queues an `auth_mail_jobs` row that the auth-delivery thread sends (CAP-JOB-016). |
| CAP-HTTP-012 | POST | `/api/auth/email/resend` | `modern_auth.py:126` | S/svc (optional) | n/a | JO | auth | 202. |
| CAP-HTTP-013 | POST | `/api/auth/email/verify` | `modern_auth.py:143` | S/svc (optional) | n/a | JO | auth | Can set the session cookie. Returns `AuthCompletion` with `user` as `MeResponse` (`modern_auth.py:78-99`). |
| CAP-HTTP-014 | POST | `/api/auth/recovery/reset` | `modern_auth.py:167` | none | n/a | JO | auth | 204. Password reset. |
| CAP-HTTP-015 | POST | `/api/auth/confirm/password` | `modern_auth.py:179` | S/svc (required; `expected_account_id`) | caller | JO; sensitive rate limit | auth | Re-authentication proof. |
| CAP-HTTP-016 | POST | `/api/auth/providers/{provider}/start` | `modern_auth.py:196` | S/svc (optional) | n/a | JO; provider configured | auth | `provider` is `google` or `apple`. Sets the binder cookie `brainbuddy_auth_binder` (HttpOnly, Secure, SameSite=None, path `/api/auth/providers`, max-age 600) at `modern_auth.py:212-221`. |
| CAP-HTTP-017 | GET | `/api/auth/providers/google/callback?code&state&error` | `modern_auth.py:250` | binder cookie | n/a | input-shape check (`modern_auth.py:237-247`) | auth | 303 redirect. Deletes the binder cookie. |
| CAP-HTTP-018 | POST | `/api/auth/providers/apple/callback` | `modern_auth.py:274` | binder cookie | n/a | form `application/x-www-form-urlencoded`, at most 32768 bytes, at most 5 fields, `id_token` at most 16384 | auth | Apple `form_post`. 303. |
| CAP-HTTP-019 | POST | `/api/auth/providers/complete` | `modern_auth.py:315` | S/svc (optional) | n/a | JO | auth | Exchanges the handoff and sets the session cookie. |
| CAP-HTTP-020 | POST | `/api/auth/providers/apple/native/complete` | `modern_auth.py:339` | S/svc (optional) | n/a | JO; Apple native configured | auth | iOS/macOS Sign in with Apple. Sets the session cookie. |
| CAP-HTTP-021 | POST | `/api/auth/providers/apple/notifications` | `modern_auth.py:363` | none (Apple-signed payload) | n/a | none (not JO) | auth | 204. Apple server-to-server events (`process_apple_notification`, `modern_auth_service.py:1712`). |
| CAP-HTTP-022 | GET | `/api/account/auth-methods` | `modern_auth.py:374` | S/svc (required) | owner | none | account | Linked methods. |
| CAP-HTTP-023 | POST | `/api/account/auth-methods/{provider}/unlink` | `modern_auth.py:385` | S/svc (required) | owner | JO | account | Clears the session cookie when `signed_out`. |
| CAP-HTTP-024 | POST | `/api/account/auth-password` | `modern_auth.py:404` | S/svc (required) | owner | JO | account | 204. Set or replace the password. |
| CAP-HTTP-025 | POST | `/api/account/auth-export` | `modern_auth.py:418` | S/svc (required) | owner | JO | account | `application/zip` stream with `Content-Disposition: attachment`. |
| CAP-HTTP-026 | POST | `/api/account/auth-delete` | `modern_auth.py:443` | S/svc (required) | owner | JO | account | 202 `{deletion_requested_at, purge_at}`. Clears the cookie. |

### 1.3 CLI device authorization (`app/api/cli_auth.py`, prefix `/api/auth/device`)

The route is available only when `BRAIN_BUDDY_CLI_VERIFICATION_ORIGIN` is set **and** the
optional managed flag `cli_auth` is not `off` and the flag store is not degraded. Otherwise
the response is 404 `cli_auth_unavailable` (`app/services/cli_auth.py:67-79`). The body must
be `Content-Type: application/json` (else 415), at most 1024 bytes (else 413) and valid JSON
(else 422) (`cli_auth.py:21-35`). Errors use `{message, detail:{code}}` with
`Cache-Control: no-store` and `Retry-After` on 429 (`errors.py:80-99`).

| ID | Method | Full path | Handler | Auth | Owner scope | Gate | Surface | Notes |
|---|---|---|---|---|---|---|---|---|
| CAP-HTTP-030 | POST | `/api/auth/device/start` | `cli_auth.py:95` | none | n/a | `cli_auth` (global mode); per IP 10/60 s; global 120/60 s (`app/services/cli_auth.py:51-62`) | CLI auth | Mints `device_code` and `user_code`. |
| CAP-HTTP-031 | POST | `/api/auth/device/request` | `cli_auth.py:109` | S + `Origin` equal to the CLI verification origin (else 403 `invalid_origin`) | caller | `cli_auth` effective for the user; 10/600 s per `ip:user`; global 120/60 s | CLI auth | Browser looks up a `user_code`. |
| CAP-HTTP-032 | POST | `/api/auth/device/decision` | `cli_auth.py:122` | as above | caller (`expected_owner`) | as above | CLI auth | Approve or deny. 409 on a state conflict. |
| CAP-HTTP-033 | POST | `/api/auth/device/token` | `cli_auth.py:143` | DEVICE | n/a | `cli_auth` | CLI auth | Sets the session cookie and returns `{account, credential_type:"session_cookie", cookie_name, expires_at}`. |

### 1.4 Password auth (`app/api/auth.py`, prefix `/api/auth`)

| ID | Method | Full path | Handler | Auth | Owner scope | Gate | Surface | Notes |
|---|---|---|---|---|---|---|---|---|
| CAP-HTTP-040 | POST | `/api/auth/signup` | `auth.py:85` | none | n/a | invite code required | auth | 201 `MeResponse`. Sets the cookie. 400 on a bad invite, 409 on a duplicate email. |
| CAP-HTTP-041 | POST | `/api/auth/login` | `auth.py:118` | none | n/a | login limiter: 10 failures per 10 min per client IP, reservation-based (`app/core/rate_limit.py:264-270`) | auth | Sets the cookie. A login during the grace period cancels deletion (`deletion_cancelled`). |
| CAP-HTTP-042 | POST | `/api/auth/logout` | `auth.py:151` | cookie optional | n/a | none | auth | 204. Deletes the session row and clears the cookie. |
| CAP-HTTP-043 | GET | `/api/auth/me` | `auth.py:164` | S | self | none | auth | `MeResponse` with `feature_flags` = effective map over all known flags (`auth.py:60-82`). |

### 1.5 Account / GDPR (`app/api/account.py`, prefix `/api/account`; never flag-gated)

Every route depends on `get_account_user`. If the optional header `X-BrainBuddy-Expected-Owner`
does not equal the caller's id, the response is 404 (`account.py:39-46`). Sensitive actions
share the per-user limiter, 10 per 10 min (`rate_limit.py:272-282`).

| ID | Method | Full path | Handler | Auth | Owner scope | Gate | Surface | Notes |
|---|---|---|---|---|---|---|---|---|
| CAP-HTTP-050 | GET | `/api/account` | `account.py:74` | S | self | none | account | Includes `completed_task_count` and `purge_at`. |
| CAP-HTTP-051 | PATCH | `/api/account/profile` | `account.py:89` | S | self | none | account | Updates `display_name`. |
| CAP-HTTP-052 | POST | `/api/account/email` | `account.py:111` | S | self | sensitive limiter | account | Requires `current_password`. Keeps the caller's session and revokes the others. |
| CAP-HTTP-053 | POST | `/api/account/password` | `account.py:143` | S | self | sensitive limiter | account | 204. Keeps the caller's session. |
| CAP-HTTP-054 | GET | `/api/account/export` | `account.py:167` | S | self | none | account | ZIP of every owned record (`app/services/account_service.py`). |
| CAP-HTTP-055 | POST | `/api/account/delete` | `account.py:189` | S | self | sensitive limiter | account | 202 `{deletion_requested_at, purge_at}`. Revokes all sessions and clears the cookie. Purge happens after the grace period (CAP-JOB-006). |

### 1.6 Admin / operator (`app/api/admin.py`, prefix `/api/admin`)

| ID | Method | Full path | Handler | Auth | Owner scope | Gate | Surface | Notes |
|---|---|---|---|---|---|---|---|---|
| CAP-HTTP-060 | GET | `/api/admin/accounts` | `admin.py:94` | OP | cross-account | none | admin | List accounts. |
| CAP-HTTP-061 | POST | `/api/admin/accounts` | `admin.py:109` | OP | cross-account | none | admin | 201. Create an account. |
| CAP-HTTP-062 | PUT | `/api/admin/accounts/{account_id}` | `admin.py:125` | OP | cross-account | none | admin | |
| CAP-HTTP-063 | DELETE | `/api/admin/accounts/{account_id}` | `admin.py:143` | OP | cross-account | none | admin | 200. |
| CAP-HTTP-064 | GET | `/api/admin/status` | `admin.py:158` | OP | n/a | none | admin | Capability probe. Logged as `admin_capability_probe` (`dependencies.py:247`). |
| CAP-HTTP-065 | POST | `/api/admin/accounts/lookup` | `admin.py:174` | OP | cross-account | none | admin | Exact lookup. 404 `No account found.` |
| CAP-HTTP-066 | POST | `/api/admin/accounts/{account_id}/revoke-sessions` | `admin.py:194` | OP | cross-account | none | admin | |
| CAP-HTTP-067 | GET | `/api/admin/feature-flags` | `admin.py:210` | OP | n/a | none | admin / flags | Mode and cohort of every managed flag (`feature_flag.py:83-93`). |
| CAP-HTTP-068 | PUT | `/api/admin/feature-flags/{flag}/mode` | `admin.py:229` | OP | n/a | none | admin / flags | `OFF`, `ON` or `SELECTED_USERS`. Degraded store returns an error via `_degraded()`. |
| CAP-HTTP-069 | POST | `/api/admin/feature-flags/{flag}/selected-users` | `admin.py:249` | OP | n/a | none | admin / flags | Adds an exact-match account. 404 if not found. |
| CAP-HTTP-070 | DELETE | `/api/admin/feature-flags/{flag}/selected-users/{account_id}` | `admin.py:283` | OP | n/a | none | admin / flags | Idempotent by id. |

### 1.7 CRT canvas, command path (`app/api/routes.py`)

Every route depends on `require_crt_exposure` (`dependencies.py:208-244`). If `X-Correlation-ID`
or `X-Request-ID` is present and not a canonical UUID, the response is 400
`{"reason":"invalid_correlation_id"}`. Flag `crt_canvas` not effective gives 404
`{"reason":"crt_canvas_disabled"}`. A flag store failure gives 503
`{"reason":"feature_flag_unavailable"}`.

| ID | Method | Full path | Handler | Auth | Owner scope | Gate | Surface | Notes |
|---|---|---|---|---|---|---|---|---|
| CAP-HTTP-080 | GET | `/api/crt/exposure` | `routes.py:57` | S | n/a | `crt_canvas` | CRT trees | 204, no body. |
| CAP-HTTP-081 | GET | `/api/crt/trees` | `routes.py:71` | S | owner | `crt_canvas` | CRT trees | |
| CAP-HTTP-082 | POST | `/api/crt/trees` | `routes.py:95` | S | owner | `crt_canvas`; Idem (UUID) | CRT trees | 201. Goes through `CrtCommandService` with receipts in `crt_commands.sqlite3`. |
| CAP-HTTP-083 | POST | `/api/crt/trees/import` | `routes.py:121` | S | owner | `crt_canvas`; Idem (UUID) | CRT trees | 201. |
| CAP-HTTP-084 | GET | `/api/crt/trees/{tree_id}` | `routes.py:145` | S | owner | `crt_canvas` | CRT trees | |
| CAP-HTTP-085 | PUT | `/api/crt/trees/{tree_id}` | `routes.py:162` | S | owner | `crt_canvas`; Idem (UUID) | CRT trees | |
| CAP-HTTP-086 | DELETE | `/api/crt/trees/{tree_id}` | `routes.py:189` | S | owner | `crt_canvas`; Idem (UUID) | CRT trees | 204. |
| CAP-HTTP-087 | POST | `/api/crt/trees/{tree_id}/export` | `routes.py:214` | S | owner | `crt_canvas` | CRT trees | |

### 1.8 Legacy trees, nodes, relations, versions, validation (`app/api/routes.py`)

| ID | Method | Full path | Handler | Auth | Owner scope | Gate | Surface | Notes |
|---|---|---|---|---|---|---|---|---|
| CAP-HTTP-090 | POST | `/api/trees` | `routes.py:229` | S+lock | owner | none | trees | 201. |
| CAP-HTTP-091 | GET | `/api/trees` | `routes.py:244` | S | owner | none | trees | List of `{id,name,updated_at,owner_id}`. |
| CAP-HTTP-092 | GET | `/api/trees/{tree_id}` | `routes.py:263` | S | owner | none | trees | |
| CAP-HTTP-093 | PUT | `/api/trees/{tree_id}` | `routes.py:277` | S+lock | owner | none | trees | 409 possible. |
| CAP-HTTP-094 | DELETE | `/api/trees/{tree_id}` | `routes.py:292` | S+lock | owner | none | trees | 204. |
| CAP-HTTP-095 | POST | `/api/trees/import` | `routes.py:305` | S+lock | owner | none | trees | 201. |
| CAP-HTTP-096 | POST | `/api/trees/{tree_id}/export` | `routes.py:320` | S | owner | none | trees | |
| CAP-HTTP-097 | POST | `/api/trees/{tree_id}/ai-feedback` | `routes.py:334` | S | owner | body `consent` must be true (400) | trees | Deterministic local summary. No provider call (`app/services/tree_service.py:406-431`). |
| CAP-HTTP-098 | POST | `/api/trees/{tree_id}/nodes` | `routes.py:349` | S+lock | owner(assert) | none | nodes | 201. |
| CAP-HTTP-099 | PATCH | `/api/trees/{tree_id}/nodes/{node_id}` | `routes.py:367` | S+lock | owner(assert) | none | nodes | |
| CAP-HTTP-100 | DELETE | `/api/trees/{tree_id}/nodes/{node_id}?cascade=` | `routes.py:385` | S+lock | owner(assert) | none | nodes | 204. |
| CAP-HTTP-101 | POST | `/api/trees/{tree_id}/relations` | `routes.py:402` | S+lock | owner(assert) | none | relations | 201. |
| CAP-HTTP-102 | PATCH | `/api/trees/{tree_id}/relations/{relation_id}` | `routes.py:420` | S+lock | owner(assert) | none | relations | |
| CAP-HTTP-103 | DELETE | `/api/trees/{tree_id}/relations/{relation_id}` | `routes.py:438` | S+lock | owner(assert) | none | relations | 204. |
| CAP-HTTP-104 | POST | `/api/trees/{tree_id}/versions` | `routes.py:454` | S+lock | owner(assert) | none | versions | 201. |
| CAP-HTTP-105 | GET | `/api/trees/{tree_id}/versions` | `routes.py:480` | S | owner(assert) | none | versions | |
| CAP-HTTP-106 | POST | `/api/trees/{tree_id}/versions/{version_id}/restore` | `routes.py:495` | S+lock | owner(assert) | none | versions | |
| CAP-HTTP-107 | DELETE | `/api/trees/{tree_id}/versions/{version_id}` | `routes.py:512` | S+lock | owner(assert) | none | versions | 204. |
| CAP-HTTP-108 | POST | `/api/trees/{tree_id}/validate/{node_id}` | `routes.py:528` | S+lock | owner(assert) | provider config | validation | Runs a `mock` or `openai` provider (CAP-EXT-003). History is stored under `<tree>/validation/`. |
| CAP-HTTP-109 | GET | `/api/trees/{tree_id}/nodes/{node_id}/validation-history` | `routes.py:546` | S | owner(assert) | none | validation | |

### 1.9 Tasks, projects, tags, title completion (`app/api/tasks.py`)

Every task and organization write requires Idem (21 call sites). Task writes route through the
Rust core when `rust_core_sync` is effective for the owner (`app/container.py:483-505`).

| ID | Method | Full path | Handler | Auth | Owner scope | Gate | Surface | Notes |
|---|---|---|---|---|---|---|---|---|
| CAP-HTTP-110 | GET | `/api/tasks/title-completion-provider` | `tasks.py:117` | S | n/a | `task_title_autocomplete` | tasks / AI | Provider category or null. Registered before `/tasks/{task_id}`. |
| CAP-HTTP-111 | POST | `/api/tasks/title-completions` | `tasks.py:139` | S | owner | `task_title_autocomplete`; provider configured (else 503); consent matches the provider (else 400); limit 20/60 s per user with 429 and `Retry-After: 60` (`rate_limit.py:284-289`) | tasks / AI | Calls CAP-EXT-001. |
| CAP-HTTP-112 | POST | `/api/tasks/title-completions/accepted` | `tasks.py:214` | S | owner | `task_title_autocomplete` | tasks / AI | 204. Writes a log line only. `request_id` must be a UUID (422). |
| CAP-HTTP-113 | POST | `/api/brain-dump-operations` | `tasks.py:248` | S | owner | `voice_brain_dump`; Idem | voice | 201. Start an operation with consent. |
| CAP-HTTP-114 | GET | `/api/brain-dump-providers` | `tasks.py:272` | S | n/a | `voice_brain_dump` | voice | Provider category per pipeline role, from config. |
| CAP-HTTP-115 | GET | `/api/brain-dump-operations/{operation_id}` | `tasks.py:304` | S | owner | none (privacy authority) | voice | |
| CAP-HTTP-116 | POST | `/api/brain-dump-operations/{operation_id}/transcript` | `tasks.py:327` | S | owner | `voice_brain_dump`; Idem | voice | Appends a client transcript. |
| CAP-HTTP-117 | PUT | `/api/brain-dump-operations/{operation_id}/audio/{chunk_number}` | `tasks.py:352` | S | owner | `voice_brain_dump`; `X-Content-SHA256` required; `Content-Type` must be an allowed audio MIME; body capped at `BRAIN_BUDDY_VOICE_AUDIO_MAX_CHUNK_BYTES` (stream-checked) | voice | Raw audio chunk written to `brain-dump-media/`. |
| CAP-HTTP-118 | POST | `/api/brain-dump-operations/{operation_id}/seal` | `tasks.py:420` | S | owner | `voice_brain_dump`; Idem | voice | Wakes the voice runner (`main.py:468-470`). |
| CAP-HTTP-119 | PATCH | `/api/brain-dump-operations/{operation_id}/proposals/{proposal_id}` | `tasks.py:445` | S | owner | `voice_brain_dump`; Idem | voice | |
| CAP-HTTP-120 | POST | `/api/brain-dump-operations/{operation_id}/{action}` | `tasks.py:472` | S | owner | Idem. `voice_brain_dump` is required except for `withdraw_consent`, `cancel` and `delete_raw_audio` (`tasks.py:112-114, 494-500`) | voice | `action` is one of `commit`, `retry`, `review_provisional`, `reconcile_preview` (vendor call), `withdraw_consent`, `delete_raw_audio`, `pause`, `resume`, `finish`, `cancel`. Anything else gives 400. Registered after the literal sub-paths. |
| CAP-HTTP-121 | POST | `/api/projects` | `tasks.py:542` | S | owner | Idem | projects | 201. |
| CAP-HTTP-122 | GET | `/api/projects` | `tasks.py:564` | S | owner | none | projects | Includes open-task counts. |
| CAP-HTTP-123 | PATCH | `/api/projects/{project_id}` | `tasks.py:586` | S | owner | Idem | projects | |
| CAP-HTTP-124 | POST | `/api/projects/{project_id}/archive` | `tasks.py:609` | S | owner | Idem | projects | |
| CAP-HTTP-125 | POST | `/api/projects/{project_id}/unarchive` | `tasks.py:632` | S | owner | Idem | projects | |
| CAP-HTTP-126 | GET | `/api/projects/{project_id}` | `tasks.py:655` | S | owner | none | projects | |
| CAP-HTTP-127 | POST | `/api/tags` | `tasks.py:672` | S | owner | Idem | tags | 201. |
| CAP-HTTP-128 | GET | `/api/tags` | `tasks.py:692` | S | owner | none | tags | |
| CAP-HTTP-129 | PATCH | `/api/tags/{tag_id}` | `tasks.py:703` | S | owner | Idem | tags | |
| CAP-HTTP-130 | DELETE | `/api/tags/{tag_id}` | `tasks.py:724` | S | owner | Idem | tags | 200 with a body (no 204 declared). |
| CAP-HTTP-131 | GET | `/api/tags/{tag_id}` | `tasks.py:745` | S | owner | none | tags | |
| CAP-HTTP-132 | POST | `/api/tasks/smart-add` | `tasks.py:762` | S | owner | Idem | tasks | 201. |
| CAP-HTTP-133 | GET | `/api/tasks/{task_id}` | `tasks.py:786` | S | owner | none | tasks | Task detail with subtasks and comments. |
| CAP-HTTP-134 | POST | `/api/tasks/{task_id}/subtasks` | `tasks.py:807` | S | owner | Idem | tasks | 201. |
| CAP-HTTP-135 | PATCH | `/api/tasks/{task_id}/subtasks/{subtask_id}` | `tasks.py:829` | S | owner | Idem | tasks | |
| CAP-HTTP-136 | POST | `/api/tasks/{task_id}/subtasks/{subtask_id}/transitions` | `tasks.py:853` | S | owner | Idem | tasks | |
| CAP-HTTP-137 | POST | `/api/tasks/{task_id}/comments` | `tasks.py:877` | S | owner | Idem | tasks | 201. |
| CAP-HTTP-138 | PATCH | `/api/tasks/{task_id}/comments/{comment_id}` | `tasks.py:900` | S | owner | Idem | tasks | |
| CAP-HTTP-139 | PATCH | `/api/tasks/{task_id}` | `tasks.py:924` | S | owner | Idem | tasks | Stale revision gives 409 with `StaleRevisionDetail` (`errors.py:184-214`). |
| CAP-HTTP-140 | POST | `/api/tasks/{task_id}/transitions` | `tasks.py:948` | S | owner | Idem | tasks | |
| CAP-HTTP-141 | POST | `/api/tasks` | `tasks.py:972` | S | owner | Idem | tasks | 201. |
| CAP-HTTP-142 | GET | `/api/tasks` | `tasks.py:995` | S | owner | none | tasks | Query parameters: `state`, `project_id`, `tag_id`, `unassigned_project`, `include_completed`, `include_cancelled`, `q`, `due_before`, `due_on`, `due_after`, `sort`, `cursor`, `limit` (1-200, default 50). |

### 1.10 Weekly review, navigator, flow (`app/api/review.py`, `review_navigator.py`, `review_flow.py`)

Errors use `{message, detail:{reason}}` (`review.py:61-79`). The flag-off refusal is 404
`weekly_review_disabled` (`dependencies.py:407-425`). All writes require Idem.

| ID | Method | Full path | Handler | Auth | Owner scope | Gate | Surface | Notes |
|---|---|---|---|---|---|---|---|---|
| CAP-HTTP-150 | POST | `/api/tasks/{task_id}/decisions` | `review.py:171` | S | owner | Idem; not gated | review | Decision-card choice. |
| CAP-HTTP-151 | POST | `/api/review/decisions/{decision_id}/undo` | `review.py:194` | S | owner | Idem | review | |
| CAP-HTTP-152 | POST | `/api/tasks/{task_id}/auto-park` | `review.py:217` | S | owner | Idem. Route is not gated, but with `weekly_review` off the response is `applied:false` (`review.py:237`) | review | |
| CAP-HTTP-153 | POST | `/api/review/parks/acknowledge` | `review.py:242` | S | owner | Idem | review | 204. |
| CAP-HTTP-154 | PUT | `/api/review/settings` | `review.py:262` | S | owner | Idem | review | |
| CAP-HTTP-155 | POST | `/api/review/explainer/acknowledge` | `review.py:284` | S | owner | Idem | review | Activates the owner. |
| CAP-HTTP-156 | GET | `/api/review/state` | `review.py:305` | S | owner | `weekly_review` | review | |
| CAP-HTTP-157 | GET | `/api/review/navigator` | `review_navigator.py:91` | S | owner | none | review / AI | Provider, consent and availability. |
| CAP-HTTP-158 | POST | `/api/review/navigator/consent` | `review_navigator.py:105` | S | owner | `weekly_review`; Idem (replays for 24 h) | review / AI | |
| CAP-HTTP-159 | DELETE | `/api/review/navigator/consent` | `review_navigator.py:127` | S | owner | Idem; not gated | review / AI | 204. |
| CAP-HTTP-160 | POST | `/api/review/navigator/suggestions` | `review_navigator.py:148` | S | owner | `weekly_review`; navigator limiter 20 per 10 min per owner gives 429 with `Retry-After` (`review_navigator.py:74, 164`; `app/modules/tasks/navigator.py:1241-1243`); per-call and daily cost caps | review / AI | Calls CAP-EXT-002 on a per-call worker thread (`app/ai/review_navigator.py:234`). |
| CAP-HTTP-161 | POST | `/api/review/sessions` | `review_flow.py:120` | S | owner | Idem; not gated | review | 201. |
| CAP-HTTP-162 | GET | `/api/review/sessions/{session_id}` | `review_flow.py:146` | S | owner | `weekly_review` | review | |
| CAP-HTTP-163 | PATCH | `/api/review/sessions/{session_id}` | `review_flow.py:159` | S | owner | Idem | review | Replay-safe by `progress_id`. |
| CAP-HTTP-164 | POST | `/api/review/sessions/{session_id}/finish` | `review_flow.py:197` | S | owner | Idem | review | |
| CAP-HTTP-165 | GET | `/api/review/queues/{step}` | `review_flow.py:221` | S | owner | `weekly_review` | review | |
| CAP-HTTP-166 | POST | `/api/review/bulk-releases` | `review_flow.py:246` | S | owner | Idem | review | A partial result is still 200. |
| CAP-HTTP-167 | POST | `/api/review/bulk-releases/{bulk_id}/undo` | `review_flow.py:268` | S | owner | Idem | review | |

### 1.11 External agents / A2A relay (`app/api/agents.py`)

`relay` here means `require_external_agent_relay_enabled`, which needs flag
`external_agent_relay` (ANDed with the secret box being constructible,
`app/container.py:207-237`). `pw` means a `current_password` re-check that shares the sensitive
limiter and returns 403 `ReauthFailedError` (`agents.py:127-147`).

| ID | Method | Full path | Handler | Auth | Owner scope | Gate | Surface | Notes |
|---|---|---|---|---|---|---|---|---|
| CAP-HTTP-170 | GET | `/api/agent-connections` | `agents.py:152` | S | owner | none | agents | |
| CAP-HTTP-171 | POST | `/api/agent-connections` | `agents.py:164` | S | owner | relay; Idem; pw | agents | 201 with no secret. Fetches the agent card (CAP-EXT-010). |
| CAP-HTTP-172 | GET | `/api/agent-connections/{connection_id}` | `agents.py:195` | S | owner | none | agents | |
| CAP-HTTP-173 | PUT | `/api/agent-connections/{connection_id}` | `agents.py:208` | S | owner | relay; Idem; pw (conditional, `agents.py:222`) | agents | |
| CAP-HTTP-174 | POST | `/api/agent-connections/{connection_id}/test` | `agents.py:235` | S | owner | relay | agents | Egress test. |
| CAP-HTTP-175 | POST | `/api/agent-connections/{connection_id}/credential` | `agents.py:248` | S | owner | relay; Idem; pw | agents | Rotates the credential. |
| CAP-HTTP-176 | POST | `/api/agent-connections/{connection_id}/disconnect` | `agents.py:274` | S | owner | Idem; pw; not gated | agents | |
| CAP-HTTP-177 | POST | `/api/tasks/{task_id}/agent-runs/preview` | `agents.py:305` | S | owner | relay | agents | Hand-off preview. |
| CAP-HTTP-178 | POST | `/api/tasks/{task_id}/agent-runs` | `agents.py:319` | S | owner | relay; Idem; pw (conditional, `agents.py:338`) | agents | 201. A2A `SendMessage` on the exchange pool. The response waits at most `dispatch_wait_seconds` (CAP-JOB-019). |
| CAP-HTTP-179 | GET | `/api/tasks/{task_id}/agent-runs` | `agents.py:351` | S | owner | none | agents | |
| CAP-HTTP-180 | GET | `/api/agent-run-summaries` | `agents.py:364` | S | owner | none | agents | Latest run per task. |
| CAP-HTTP-181 | GET | `/api/agent-runs/{run_id}` | `agents.py:384` | S | owner | none | agents | |
| CAP-HTTP-182 | POST | `/api/agent-runs/{run_id}/reply` | `agents.py:397` | S | owner | Idem; not gated | agents | |
| CAP-HTTP-183 | POST | `/api/agent-runs/{run_id}/check-delivery` | `agents.py:417` | S | owner | Idem; pw (conditional, `agents.py:442`); resend only when relay is effective (`agents.py:452`) | agents | Lookup, then a rules-bound resend. |
| CAP-HTTP-184 | POST | `/api/agent-runs/{run_id}/cancel` | `agents.py:456` | S | owner | Idem; not gated | agents | A2A `CancelTask`. |
| CAP-HTTP-185 | POST | `/api/a2a/push/{run_id}/{token}` | `agents.py:477` | PUSH | run's owner | not gated. Body capped at 64 000 bytes (declared and streamed; 413). Global limit 600/min before any DB read, then per run 30/min with 1024 keys; 429 (`agents.py:68-85, 503-523`) | A2A inbound | 204. The body is discarded. Unknown run, bad token and closed run all get an identical 403 `Notification rejected.` On success it only wakes the observer. The token is redacted from logs (`app/core/logging.py:43-104`). |

### 1.12 Sync v1 (`app/api/sync*.py`; prefix `/api/sync/v1`; not in OpenAPI)

Auth is `S` via `sync_user`. Every route requires `scope_id` to match the caller
(`require_scope`) and admits through `ReceiptStore.admit` under the caller's `auth_version`.
`ACCESS_DENIED` (flag `rust_core_sync` off) is returned where marked. Failures are rendered as
`ErrorBody` with `Cache-Control: no-store` by `SyncRoute` (`sync.py:60-90`). Validation and
`ValidationFailure` map to `INVALID_REQUEST`. A 401 maps to `AUTH_REQUIRED`. A `RustBridgeError`
or an unknown code maps to `TEMPORARILY_UNAVAILABLE`.

| ID | Method | Full path | Handler | Auth | Owner scope | Gate | Surface | Notes |
|---|---|---|---|---|---|---|---|---|
| CAP-HTTP-190 | POST | `/api/sync/v1/devices` | `sync.py:171` | S | scope = owner | `rust_core_sync`; body at most 64 KiB | sync | Registers a device and its epoch. |
| CAP-HTTP-191 | POST | `/api/sync/v1/commands` | `sync.py:196` | S | scope = owner | Body at most 16 MiB (`STABLE_REPLAY_BYTES`, `receipts.py:32`), strict JSON object. A replay is answered **before** the flag check. Then `rust_core_sync`, then command at most 4 MiB (`wire.py:28`), then version policy, giving `UPGRADE_REQUIRED` | sync | Executes a device command through the family executors (`app/modules/tasks/sync/device_executor*.py`). |
| CAP-HTTP-192 | GET | `/api/sync/v1/commands/{command_id}?scope_id=` | `sync.py:238` | S | scope = owner | **no flag check** | sync | Receipt lookup. |
| CAP-HTTP-193 | GET | `/api/sync/v1/capabilities?scope_id=` | `sync.py:253` | S | scope = owner | none (reports `enabled`) | sync | Protocol versions `(1,)` (`wire.py:24`), supported commands, policy. |
| CAP-HTTP-194 | GET | `/api/sync/v1/changes?scope_id&cursor&limit` | `sync_delta.py:30` | S | scope = owner | `rust_core_sync` | sync | Delta feed. |
| CAP-HTTP-195 | GET | `/api/sync/v1/transactions/{transfer_id}?page_token=` | `sync_delta.py:54` | S | owner | `rust_core_sync` | sync | Paging of an oversized transaction. |
| CAP-HTTP-196 | POST | `/api/sync/v1/snapshots` | `sync_snapshots.py:37` | S | scope = owner | `rust_core_sync`; body at most 64 KiB | sync | Creates a snapshot. |
| CAP-HTTP-197 | GET | `/api/sync/v1/snapshots/{snapshot_id}?scope_id&page_token` | `sync_snapshots.py:57` | S | scope = owner | `rust_core_sync` | sync | Snapshot page. |
| CAP-HTTP-198 | GET | `/api/sync/v1/hints?scope_id=` | `sync_hints.py:95` | S | scope = owner | `rust_core_sync`, re-checked during the stream | sync | SSE `text/event-stream` with headers `Cache-Control: no-store` and `X-Accel-Buffering: no`. Emits `event: scope_changed`. Polls every 0.25 s, heartbeat 15 s, maximum age 15 min (`app/modules/tasks/sync/hints.py:32-37, 126`). `Last-Event-ID` is ignored. The hub is closed on shutdown (`main.py:612-619`). |

## 2. MCP tools and resources (`app/api/mcp.py`)

The server is `FastMCP("BrainBuddy Tasks")`, stateless streamable HTTP with JSON responses
(`mcp.py:79-94`). It exposes **tools only**: no resources and no prompts are registered.
Standard protocol methods (`initialize`, `tools/list`, `tools/call`, `ping`) come from the SDK.

Auth for the whole MCP surface works in these steps:

1. `AuthenticationMiddleware(BearerAuthBackend(SessionTokenVerifier))` reads
   `Authorization: Bearer <session token>`.
2. The verifier maps the token to the user and grants scope `["tasks"]` only if `task_mcp` is
   effective (`mcp.py:54-75`).
3. `RequireAuthMiddleware(required_scopes=["tasks"])` enforces the scope (`mcp.py:242-247`).
4. Each tool call re-validates the token and `task_mcp` in the worker thread immediately before
   executing (`mcp.py:96-124`).

Domain errors become `ToolError(str(exc))`. Unexpected errors become a generic retry message.
Tool outcomes are logged by name only.

| ID | Tool | Annotations | Handler | Behavior | Auth |
|---|---|---|---|---|---|
| CAP-MCP-001 | `list_tasks(q?, state?, include_completed=false, include_cancelled=false, cursor?, limit 1-200 =50)` | readOnly | `mcp.py:126` | Calls `TaskService.list_tasks` for the owner. Returns `TaskListResponse` (items, `next_cursor`, `has_more`, `counts_by_state`). | BEARER + `task_mcp` |
| CAP-MCP-002 | `get_task(task_id)` | readOnly | `mcp.py:159` | Task detail with revision, subtasks and comments. | BEARER + `task_mcp` |
| CAP-MCP-003 | `create_task(title 1-500, idempotency_key 1-200, details? up to 20000, state=inbox, due_date?, priority=none, project_id?, tag_ids?, waiting_for? up to 500)` | write, idempotent | `mcp.py:171` | `TaskService.create_task` with the idempotency key. A waiting task requires `waiting_for`. | BEARER + `task_mcp` |
| CAP-MCP-004 | `delete_task(task_id, expected_revision >=1, idempotency_key)` | destructive, idempotent | `mcp.py:203` | Soft delete: transitions with action `cancel`. A stale revision fails. | BEARER + `task_mcp` |
| CAP-MCP-005 | server `instructions` string | n/a | `mcp.py:81-86` | Fixed guidance text returned at initialize. | n/a |
| CAP-MCP-006 | transport security | n/a | `mcp.py:90-93` | DNS-rebinding guard. `Host` must match `BRAIN_BUDDY_MCP_ALLOWED_HOSTS` (default `localhost:*,127.0.0.1:*,[::1]:*`). `allowed_origins=[]`. | n/a |
| CAP-MCP-007 | lifespan | n/a | `mcp.py:249-256` | The MCP session manager runs inside the app lifespan. | n/a |

## 3. Background jobs, schedulers, workers, boot and shutdown work

Background loops start only outside `BRAIN_BUDDY_ENV=test`, unless
`BRAIN_BUDDY_ENABLE_VOICE_SWEEP_IN_TEST=1` (`main.py:459-464`). Two modes exist:

* **Legacy mode** (default): the threads below own every responsibility.
* **Durable mode** (`BRAIN_BUDDY_DURABLE_SCHEDULER` in `1`, `true`, `yes`, `on`): the job ledger
  takes over `REVIEW_SWEEP`, `PRIVACY_RETENTION`, `AGENT_OBSERVATION`, `AGENT_RECOVERY` and
  `VOICE_SWEEP`, and the legacy loops skip them. The assignment is
  `main.py:363-441, 475-485`, with `Responsibility` defined at
  `app/modules/tasks/jobs/worker.py:381-397`.

| ID | Name | Trigger and cadence | Code | What it reads and writes |
|---|---|---|---|---|
| CAP-JOB-001 | Boot maintenance sweep | Once in `create_app`, **always**, tests included | `main.py:486-491, 210-261` | Runs CAP-JOB-002 to CAP-JOB-012 (privacy steps) and CAP-JOB-013 (voice) once synchronously, skipping responsibilities the durable worker owns. Logs counts. |
| CAP-JOB-002 | `privacy-maintenance-sweep` thread | Every `BRAIN_BUDDY_AGENT_RETENTION_SWEEP_INTERVAL_SECONDS` (default 60; clamped 1-3600, `app/modules/tasks/jobs/privacy_adapter.py:55-58`); first run after one interval | `main.py:287-308, 555-560` | Runs steps CAP-JOB-003 to CAP-JOB-012 in order. Each step is isolated so one failure does not stop the rest. |
| CAP-JOB-003 | step: modern-auth metadata cleanup | in CAP-JOB-002 (always legacy-owned) | `main.py:76-79`; `app/services/modern_auth_service.py:1721-1730` | `auth.sqlite3`: fails `auth_attempts` stuck in `exchanging` past their lease and expires auth metadata (limit 100). |
| CAP-JOB-004 | step: auth migration backup cleanup | in CAP-JOB-002 (legacy) | `main.py:81-84`; `app/services/auth_migration.py` | Deletes the expired legacy-auth backup in the data dir. |
| CAP-JOB-005 | step: CLI device-grant cleanup | in CAP-JOB-002 (legacy) | `main.py:85-88`; `app/services/cli_auth.py:285-286` | `auth.sqlite3` `cli_device_grants`: deletes expired grants. |
| CAP-JOB-006 | step: account purge | in CAP-JOB-002, or durable `privacy.maintenance` | `main.py:90-98`; `AccountService.purge_due_accounts` | Hard-deletes accounts past grace (14 days, `app/services/auth_service.py:38`; override `BRAIN_BUDDY_ACCOUNT_PURGE_GRACE_SECONDS`, `app/container.py:703-706`) across every store. Writes a purge marker into the control ledger. |
| CAP-JOB-007 | step: external-agent relay retention | in CAP-JOB-002, or durable `privacy.maintenance` | `main.py:99-106`; `app/modules/agents/service.py:4696-4710` | `agents.sqlite3`: prunes undispatched runs older than 1 h (`service.py:210`), expires relayed content (`BRAIN_BUDDY_AGENT_CONTENT_RETENTION_SECONDS`, default 30 days), expires identifier-tier runs, bounds the audit log. |
| CAP-JOB-008 | step: CRT command reconciliation | in CAP-JOB-002 (always legacy) | `main.py:108-111`; `app/services/crt_command_service.py:512-` | `crt_commands.sqlite3`: settles pending command receipts whose durable marker proves the write. |
| CAP-JOB-009 | step: CRT receipt retention | in CAP-JOB-002, or durable | `main.py:113-120`; `app/repositories/crt_command.py:22, 286` | After 30 days redacts each CRT receipt's response body to a content-free tombstone (`UPDATE`, `crt_command.py:286-325`), kept until account purge (ADR-0026). Corrected 2026-10-14 after planning review. |
| CAP-JOB-010 | step: sync retention | in CAP-JOB-002 (when it owns privacy), or durable step `sync_retention` | `main.py:122-128`; `app/modules/tasks/sync/retention.py:62, 187-200` | `tasks.sqlite3` sync tables: per owner, expires feed rows older than 90 days, plus receipt, snapshot and transfer copies. |
| CAP-JOB-011 | step: control-ledger prune | in CAP-JOB-002 (legacy only; **not** in the durable privacy adapter) | `main.py:130-140`; `app/modules/tasks/sync/control_ledger.py:23, 149-` | `sync_control_ledger.sqlite3`: retires purge markers older than the 7-day horizon whose account is gone. |
| CAP-JOB-012 | step: weekly-review maintenance sweep | in CAP-JOB-002, or durable `tasks.review_maintenance` | `main.py:142-176`; `app/modules/tasks/review_service.py:1685` | `tasks.sqlite3` review tables. Retention: idempotency records past 24 h, 7-day snapshots, idle runs, 35-day navigator usage. Exposure, for activated owners with `weekly_review`: sweep-gap floor, clock repair, auto-park. Errors are logged by type only. |
| CAP-JOB-013 | `voice-operation-sweep` thread | Every `BRAIN_BUDDY_VOICE_SWEEP_INTERVAL_SECONDS` (default 60; 0 disables), or early when `runner_wake` is set by seal/commit paths | `main.py:179-207, 264-284, 503-518` | `voice_operations.sqlite3` and `brain-dump-media/`, in order: recover expired provider leases; advance due provider runs (STT and reconciler calls, CAP-EXT-004 to CAP-EXT-006); resume operations frozen mid-commit (writes tasks); purge raw audio past `BRAIN_BUDDY_VOICE_RAW_AUDIO_RETENTION_SECONDS` (default 86400); purge working artifacts past `BRAIN_BUDDY_VOICE_WORKING_ARTIFACT_RETENTION_SECONDS` (default 604800). The first failure aborts the pass. |
| CAP-JOB-014 | `agent-observer` scheduler thread | Every `BRAIN_BUDDY_AGENT_OBSERVATION_INTERVAL_SECONDS` (default 60), or early via `wake(run_id)` from CAP-HTTP-185 | `main.py:544-545`; `app/modules/agents/observer.py:611-643, 395-398` | Claims due runs, groups them by owner and connection, and runs A2A `GetTask` (falling back to `ListTasks`) on the observation pool (`BRAIN_BUDDY_AGENT_OBSERVER_WORKERS`, default 4). Writes run state and events to `agents.sqlite3`. |
| CAP-JOB-015 | Boot interrupted-exchange recovery | Once at boot, before serving (marking), then lookups on the observer pool | `main.py:519-554`; `observer.py:276-336` | Marks queued exchanges *Not sent* and started ones *interrupted*, then resolves each with a lookup and never a resend. In durable mode: `AgentRecoveryAdapter.boot_sweep` plus `agent.recover` jobs. |
| CAP-JOB-016 | `auth-delivery` thread | Loop with a 1 s sleep. Only if `modern_auth.crypto_ready` (`BRAIN_BUDDY_AUTH_KEYRING` and `BRAIN_BUDDY_AUTH_CURRENT_KEY_ID`) | `main.py:327-342, 498-501`; `modern_auth_service.py:1715-1719` | Sends one leased `auth_mail_jobs` email via SMTP (CAP-EXT-007). Dispatches one `auth_apple_cleanup_jobs` Apple token revocation (CAP-EXT-009). Then runs CAP-JOB-003. |
| CAP-JOB-017 | Durable job worker lanes | `BRAIN_BUDDY_DURABLE_SCHEDULER` on. Idle poll 1 s, reconcile 30 s, shutdown grace 5 s (`app/modules/tasks/jobs/worker.py:32-37`). `ensure_schedules(due_now=True)` at boot | `main.py:363-441, 561-565`; `app/modules/tasks/jobs/repository.py:42-68` | Ledger tables `jobs` and `job_fence_counter` in `tasks.sqlite3`: leased, fenced, bounded retry with jittered backoff. Lanes and job types: maintenance (`tasks.review_maintenance`, `privacy.maintenance`); agent (`agent.observe`, `agent.recover`); voice (`voice.maintenance`, registered only if the voice interval is above 0). Adapters live in `app/modules/tasks/jobs/*_adapter.py`. |
| CAP-JOB-018 | Durable job wake hooks | On push (observer) and voice runner wake | `main.py:351-360, 436-440` | `lanes.wake(job_type)` and never fails the caller. |
| CAP-JOB-019 | Agent exchange, observation and control pools | Request-initiated, completing after the response | `app/container.py:633-650`; `app/modules/agents/service.py:2219` | `SendMessage` and `CreateTaskPushNotificationConfig` run on the exchange pool (`BRAIN_BUDDY_AGENT_EXCHANGE_WORKERS` default 8, at most `..._MAX_EXCHANGES_PER_CONNECTION` default 2). The HTTP response waits at most `BRAIN_BUDDY_AGENT_DISPATCH_WAIT_SECONDS` (default 5). Cancel runs on the control pool (`..._CONTROL_WORKERS` default 2). |
| CAP-JOB-020 | Admin seed | Once at boot, if `BRAIN_BUDDY_ADMIN_EMAIL` and `BRAIN_BUDDY_ADMIN_PASSWORD` are both set | `main.py:311-324, 458` | Creates or updates the admin account in `auth.sqlite3`. Startup fails if the password violates policy. |
| CAP-JOB-021 | Container-build auth migration cleanup | Every `build_container` (web and CLI) | `app/container.py:404-406` | `AuthMigration.resume_cleanup()` and `cleanup_expired_backup()` on legacy JSON auth files. |
| CAP-JOB-022 | Feature-flag one-time migration | First open of `feature_flags.sqlite3` on a never-migrated volume | `app/repositories/feature_flag.py:404-430` | Seeds managed flags from `BRAIN_BUDDY_FEATURE_FLAGS` and `..._INTERNAL_USERS` (emails resolved to ids), or writes all-`OFF`. Writes the `feature-flags/sqlite-migration-complete.json` marker. |
| CAP-JOB-023 | Store schema migrations on open | Each repository constructor | `tasks/repository.py:78-130, 302-394`; `voice_brain_dump/repository.py:54-166`; `agents/repository.py:242`; `auth_store.py:237-243` | `CREATE TABLE IF NOT EXISTS` and `migration_ledger`. Imports legacy per-owner JSON into SQLite. |
| CAP-JOB-024 | Sync hint hub poller | Per open SSE stream (CAP-HTTP-198) | `app/modules/tasks/sync/hints.py:32-150` | Polls the `tasks.sqlite3` commit counter and re-checks admission. Read-only. |
| CAP-JOB-025 | Navigator call thread | Per suggestion request | `app/ai/review_navigator.py:225-245` | A short-lived daemon thread enforces the provider deadline (`BRAIN_BUDDY_REVIEW_NAVIGATOR_TIMEOUT_SECONDS`). |
| CAP-JOB-026 | Shutdown hooks | Process shutdown | `main.py:567-598, 612-619` | Sets the stop events; stops the observer (cancels unstarted pool work only), the durable worker, and the voice and privacy threads (join 5 s each); stops the auth-dispatch thread (join 12 s) and closes the provider HTTP client; closes the SSE hub. |

## 4. Operator CLIs

| ID | Command | Code | Purpose |
|---|---|---|---|
| CAP-CLI-001 | `uvicorn app.main:app --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 10` | `Dockerfile` (runtime CMD); `app/main.py:637` | Server entry point. Importing `app.main` builds the app and runs the boot work (CAP-JOB-001, CAP-JOB-020 to CAP-JOB-023). |
| CAP-CLI-002 | `python -m app.cli create-invite` | `app/cli.py:60` | Mints a 256-bit URL-safe invite code into `invites/` and prints it. |
| CAP-CLI-003 | `python -m app.cli purge-due-accounts` | `app/cli.py:73` | Manual CAP-JOB-006. Prints `Purged N account(s).` |
| CAP-CLI-004 | `python -m app.cli migrate-auth [--writers-stopped]` | `app/cli.py:84` | Validates and imports legacy JSON accounts and sessions into `auth.sqlite3` and resumes cleanup. Prints a JSON result. Exit code 1 on error. |
| CAP-CLI-005 | `python -m app.cli sync-restore-control-plane --writers-stopped (--backup-taken-at ISO8601+offset or --reopen [--external-effects-reconciled])` | `app/cli.py:120` | Replays the control ledger over a restored `tasks.sqlite3` (purges and session revocations), or reopens access. Exit code 2 on bad arguments, 1 when the ledger is incomplete or not ready. |
| CAP-CLI-006 | `python -m app.cli review-seed-aged-task --email --days [--title]` | `app/cli.py:189` | Test environment only (`BRAIN_BUDDY_ENV=test`, else exit 2). Seeds a Next task with a back-dated formulation. |
| CAP-CLI-007 | `python -m app.cli review-run-sweep` | `app/cli.py:233` | Test environment only. Runs one CAP-JOB-012 pass and prints the counts. |
| CAP-CLI-008 | `python -m app.cli review-metrics --owner <id> --since YYYY-MM-DD` | `app/cli.py:327` | Read-only, content-free weekly-review aggregates (SC-001, SC-003 to SC-005, parks) with minimum sample sizes. |

## 5. Cross-cutting middleware and HTTP behaviors

| ID | Behavior | Code | Detail |
|---|---|---|---|
| CAP-MW-001 | Correlation ID | `app/api/middleware.py:65-119` | Takes `X-Correlation-ID`, else `X-Request-ID`. Accepted only if it matches `^[0-9A-Za-z._-]{1,64}$`; otherwise a fresh uuid4 is used. Stored in a context var and `request.state`. Echoed as `X-Correlation-ID` on every response that passes through the middleware, MCP included. Error handlers also set it and put it in `reference_id`. |
| CAP-MW-002 | `X-Client` parsing | `middleware.py:24-40, 96` | `brainbuddy-(ios or macos)/<ver up to 32>` becomes `(client, version)`. Absent means `web`; anything else means `other`. Used in logs only, never echoed. |
| CAP-MW-003 | Request log line | `middleware.py:95-138`; `app/core/logging.py:43-104` | `api_request method path status client client_version duration_ms`. Warning level for 400 and above. The path is sanitized: auth and account paths are normalized with no query, and the A2A push token is replaced by `[redacted]`. Unhandled exceptions log `api_request_failed`; under `/api/review/navigator` the exception is replaced by a content-free class name. |
| CAP-MW-004 | Uvicorn access-log filter | `app/core/logging.py:107-` (`PushCallbackAccessFilter`) | Applies the same path sanitization to `uvicorn.access`. Structured log output is configured by `configure_logging` (`logging.py:338`) at `BRAIN_BUDDY_LOG_LEVEL`. |
| CAP-MW-005 | Privacy headers | `middleware.py:120-126` | For paths starting `/api/auth/` or `/api/account/`: `Cache-Control: no-store` and `Referrer-Policy: no-referrer`. |
| CAP-MW-006 | CORS and same origin | (absence) | No `CORSMiddleware`, `TrustedHostMiddleware`, HSTS, CSP or X-Frame-Options anywhere in `app/`. Same-origin is assumed (the frontend nginx proxies `/api`: `../deploy/nginx/default.conf:33-46`). Origin checks exist only on modern-auth POSTs (`modern_auth.py:55-67`), CLI browser routes (`cli_auth.py:38-43`) and MCP hosts (`mcp.py:90-93`). |
| CAP-MW-007 | Standard error envelope | `app/schemas/api.py:19-34`; `app/api/errors.py:133-327` | `{"message": str, "detail": any or null, "reference_id": str or null}`. Mapping: `HTTPException` gives its status (`detail` set only when not a string); `NotFoundError` 404 `{resource,id}`; `ConflictError` 409 (stale revision gives `StaleRevisionDetail`; idempotency and pending errors give their detail); `ReauthFailedError` 403; `AdminAuthorizationError` 403; `ValidationFailure` **400**; `StorageUnavailableError` 503; `RustBridgeError` 503 if the code is `WORKSPACE_CLOSED` or `CANCELLED`, else 500; `RepositoryError` 500; `BrainBuddyError` 400. |
| CAP-MW-008 | Request validation | `errors.py:38-49, 115-130` | 422 `{message:"Request validation failed.", detail:[errors without "input"]}`. For `/api/auth/device/*` it is instead 422 `{detail:{code:"invalid_request"}}` with `no-store` (`errors.py:52-76`). |
| CAP-MW-009 | Review error envelope | `app/api/review.py:61-79` | `ReviewRequestError` gives `{message, detail:{reason}}`. |
| CAP-MW-010 | Auth error envelopes | `errors.py:79-112` | `CliAuthError`: `{detail:{code}}`, `no-store`, optional `Retry-After`. `ModernAuthError` and `AuthAppleLifecycleError`: `{message:"Authentication could not be completed.", detail:{code}}`. |
| CAP-MW-011 | Sync `ErrorBody` | `app/api/sync.py:60-90`; `app/modules/tasks/sync/wire.py` | Protocol codes (`AUTH_REQUIRED`, `ACCESS_DENIED`, `INVALID_REQUEST`, `COMMAND_TOO_LARGE`, `UPGRADE_REQUIRED`, `TEMPORARILY_UNAVAILABLE`, and others) with `Cache-Control: no-store`. |
| CAP-MW-012 | Session cookie | `app/api/auth.py:39-57`; `app/core/config.py:376-392, 1262` | Name `brainbuddy_session`, max-age 30 days, `HttpOnly`, `SameSite=Lax`, `Path=/`, `Secure` only when `BRAIN_BUDDY_ENV=production`. Cleared with `delete_cookie(path="/")`. Opaque token, stored hashed. |
| CAP-MW-013 | Provider binder cookie | `modern_auth.py:212-234` | `brainbuddy_auth_binder`, `HttpOnly`, `Secure`, `SameSite=None`, path `/api/auth/providers`, max-age 600. Deleted on callback. |
| CAP-MW-014 | Rate limits (in-memory, per process) | `app/core/rate_limit.py:264-298`; `app/api/agents.py:68-85`; `app/services/cli_auth.py:51-62`; `app/modules/tasks/navigator.py:1241` | Login: 10 failures per 10 min per IP. Sensitive account and relay actions: 10 per 10 min per user. Title completion: 20 per 60 s per user. Navigator: 20 per 10 min per owner. Push: 600/min global and 30/min per run (1024 keys). CLI start: 10/60 s per IP, 120/60 s global. CLI browser: 10/600 s per `ip:user`, 120/60 s global. |
| CAP-MW-015 | Body size caps | as cited | Push 64 000 bytes. CLI 1024 bytes. Apple callback 32 768 bytes. Sync device and snapshot 64 KiB. Sync command 16 MiB read, 4 MiB executable. Audio chunk `BRAIN_BUDDY_VOICE_AUDIO_MAX_CHUNK_BYTES` (default 10 MiB); total, count and duration caps are enforced in the voice service. |
| CAP-MW-016 | Idempotency-Key | `tasks.py:241`; `review.py:164`; `agents.py:107`; `routes.py:573-591` | Required on every task, organization, review, agent, voice and CRT write. CRT writes require a canonical UUID with `detail.reason` `missing_idempotency_key` or `invalid_idempotency_key`. |
| CAP-MW-017 | Expected-owner binding | `app/api/account.py:39-46` | `X-BrainBuddy-Expected-Owner` on `/api/account*`: a mismatch gives 404. |
| CAP-MW-018 | CRT correlation strictness | `dependencies.py:215-230` | On `/api/crt/*`, the correlation headers must be canonical UUIDs (400). This is stricter than CAP-MW-001. |
| CAP-MW-019 | Session validity rules | `app/services/auth_service.py:179-212` | Rejects and deletes the session on `auth_version` mismatch, pending deletion, operator email with a non-password method, or an inactive provider binding. |
| CAP-MW-020 | Operator denial audit | `dependencies.py:247-359` | Logs the event (`admin_capability_probe` or `admin_data_route`), the canonical route template (never the raw path), correlation id, and outcome; on 403 also the caller id. |
| CAP-MW-021 | Sync admission | `app/api/sync.py:104-133`; `app/modules/tasks/sync/authority.py` | `scope_id` must equal the owner scope. Admission is bound to the caller's `auth_version`. The sync gateway, executor and hint hub are built lazily once per app. |

## 6. External integrations

| ID | Integration | Selection (config keys) | Code | Notes |
|---|---|---|---|---|
| CAP-EXT-001 | OpenAI Chat Completions: task title completion | `BRAIN_BUDDY_TASK_TITLE_AUTOCOMPLETE_PROVIDER` (`openai`, `deterministic` (test only, refused in production) or `disabled`; default `disabled`, or `deterministic` in test), `..._MODEL` (gpt-4o-mini), `..._API_KEY_ENV` (OPENAI_API_KEY) | `app/ai/title_completion.py:135-253`; `app/core/config.py:1407-1422` | Uses `httpx.post` with a bearer key and a JSON-object response. |
| CAP-EXT-002 | OpenAI Chat Completions: review navigator | `BRAIN_BUDDY_REVIEW_NAVIGATOR_PROVIDER` (`disabled`, `deterministic` or `openai`), `_MODEL`, `_API_KEY_ENV`, `_TIMEOUT_SECONDS`, `_MAX_INPUT_TOKENS`, `_MAX_OUTPUT_TOKENS`, `_MAX_COST_USD`, `_MAX_DAILY_COST_USD` | `app/ai/review_navigator.py:46-47, 191, 339-349`; `config.py:1424-1446` | A misconfiguration fails the web app build (`container.py:395-402`). |
| CAP-EXT-003 | OpenAI Chat Completions: CRT node validation | Per-provider `config.json` in the data dir (`api_key_ref`, `model`); fallback `OPENAI_API_KEY`; providers `mock` or `openai` | `app/ai/providers/openai_provider.py:17-60`; `app/container.py:470-479` | |
| CAP-EXT-004 | OpenAI audio transcription (accurate STT) | `BRAIN_BUDDY_VOICE_ACCURATE_STT_PROVIDER=openai` (the default when `OPENAI_API_KEY` is set), `_MODEL` (gpt-4o-mini-transcribe), `_API_KEY_ENV`, `_TIMEOUT_SECONDS`, `_MAX_RETRIES`, `_RETRY_BACKOFF_SECONDS`, `_MAX_COST_USD`, `_ESTIMATED_COST_USD_PER_MB` | `app/workflows/voice_brain_dump/adapters/openai_stt.py:20`; `container.py:241-276`; `config.py:1269-1320` | A missing key degrades the role to `disabled`. |
| CAP-EXT-005 | Deepgram `/v1/listen` (accurate STT) | `..._ACCURATE_STT_PROVIDER=deepgram` (production per `../fly.backend.toml`), model nova-3, `DEEPGRAM_API_KEY` | `app/workflows/voice_brain_dump/adapters/deepgram_stt.py:21`; `container.py:260-270` | |
| CAP-EXT-006 | OpenAI Chat Completions: voice text reconciler | `BRAIN_BUDDY_VOICE_RECONCILER_PROVIDER` (`disabled`, `deterministic` or `openai`), `_MODEL` (gpt-4o), `_ENDPOINT`, `_API_KEY_ENV`, timeouts, retries, costs | `app/workflows/voice_brain_dump/adapters/reconciler.py:38, 360`; `container.py:311-329` | |
| CAP-EXT-007 | SMTP (email sign-in and recovery links) | `BRAIN_BUDDY_AUTH_SMTP_HOST`, `_PORT` (587), `_SENDER`, `_USERNAME`, `_PASSWORD`, `_TLS` (`starttls` or `tls`), plus `PUBLIC_ORIGIN`, `API_ORIGIN` and the keyring | `app/services/auth_mail_service.py:13, 500-507`; `config.py:984-995` | `smtplib.SMTP` or `SMTP_SSL`, sent from CAP-JOB-016. |
| CAP-EXT-008 | Google OAuth / OIDC | `BRAIN_BUDDY_AUTH_GOOGLE_CLIENT_ID`, `_GOOGLE_CLIENT_SECRET`, plus origins and keyring | `app/services/auth_provider_service.py:37-43` | Authorize, token and JWKS endpoints. |
| CAP-EXT-009 | Sign in with Apple (web and native), token revoke, server notifications | `BRAIN_BUDDY_AUTH_APPLE_TEAM_ID`, `_KEY_ID`, `_PRIVATE_KEY` (P-256), `_SERVICES_ID` (web), `_NATIVE_APP_ID` (native) | `auth_provider_service.py:38-51`; `app/services/auth_apple_lifecycle.py:341-`; `config.py:946-981` | Authorize, token, keys and revoke endpoints. Inbound CAP-HTTP-021. |
| CAP-EXT-010 | A2A agent card fetch | per connection address; `BRAIN_BUDDY_AGENT_CONNECTOR_TIMEOUT_SECONDS`, `_CONNECTOR_MAX_RESPONSE_BYTES`, `_ALLOW_PRIVATE_DESTINATIONS` (`1` only, never in production) | `app/modules/agents/a2a/card.py:56, 224-226, 614`; `app/modules/agents/egress.py` | `GET <addr>/.well-known/agent-card.json` with pinned DNS, no redirects and a bounded body. |
| CAP-EXT-011 | A2A JSON-RPC egress | `SendMessage`, `GetTask`, `ListTasks`, `CancelTask`, `CreateTaskPushNotificationConfig`; `_REPLY_WINDOW_SECONDS` (300), `_A2A_TASK_MAX_RESPONSE_BYTES` (262144); credentials sealed with `BRAIN_BUDDY_AGENT_RELAY_KEYS` | `app/modules/agents/a2a/client.py:352-480, 541-626`; `app/modules/agents/secrets.py` | Correlation ids are minted by the server. The push URL is built from `BRAIN_BUDDY_PUBLIC_BASE_URL` + `/api/a2a/push/{run}/{token}` (`config.py:528`). |
| CAP-EXT-012 | A2A push inbound | n/a | CAP-HTTP-185 | Only wakes the observer. |
| CAP-EXT-013 | `bb_core` Rust core (PyO3, in-process) | flag `rust_core_sync` per owner | `app/modules/tasks/rust_adapter.py:24-28`; `../backend/bb_core.pyi`; `../rust/` | Task, review and sync decisions, persistence projection and command decoding. A port links the crate directly. |

## 7. Configuration (environment variables read by the server)

Default means the code default, read at `app/core/config.py` unless cited otherwise.
`.env.example` column: Y = documented, N = missing.

| ID | Variable | Default | Purpose | Code | .env.example |
|---|---|---|---|---|---|
| CAP-CFG-001 | `BRAIN_BUDDY_ENV` | `development` (`production` and `test` set by the Dockerfile) | development, test or production. Production enables `Secure` cookies and forbids deterministic providers. Test disables loops. | `:1241` | Y |
| CAP-CFG-002 | `BRAIN_BUDDY_API_PREFIX` | `/api` | Prefix for every router, docs and MCP. | `:1242` | Y |
| CAP-CFG-003 | `BRAIN_BUDDY_LOG_LEVEL` | `INFO` | Log level. | `:1243` | Y |
| CAP-CFG-004 | `BRAIN_BUDDY_DATA_DIR` | `backend/data` (container `/app/data`) | Root of every store. Falls back to the default if not writable. | `:1244-1258` | Y |
| CAP-CFG-005 | `BRAIN_BUDDY_FEATURE_FLAGS` | `""` | `name=state,...`. Only `delivery_canary` is runtime; the others are one-time migration seed. | `:1203` | Y |
| CAP-CFG-006 | `BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS` | `""` | Cohort emails (runtime only for `delivery_canary=internal`; otherwise migration seed). | `:1204` | Y |
| CAP-CFG-007 | `BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS` | `""` | Operator allow-list; also reserved emails. | `:1227` | Y |
| CAP-CFG-008 | `BRAIN_BUDDY_ADMIN_EMAIL` | unset | Boot admin seed (CAP-JOB-020). | `main.py:320` | Y |
| CAP-CFG-009 | `BRAIN_BUDDY_ADMIN_PASSWORD` | unset | Boot admin seed. | `main.py:321` | Y |
| CAP-CFG-010 | `BRAIN_BUDDY_ACCOUNT_PURGE_GRACE_SECONDS` | unset (14 days) | Deletion grace override. | `container.py:703` | **N** |
| CAP-CFG-011 | `BRAIN_BUDDY_DURABLE_SCHEDULER` | off | Durable job ledger takeover. | `main.py:57-62` | Y |
| CAP-CFG-012 | `BRAIN_BUDDY_ENABLE_VOICE_SWEEP_IN_TEST` | unset | `1` runs the loops under `ENV=test`. | `main.py:460` | Y |
| CAP-CFG-013 | `BRAIN_BUDDY_VOICE_SWEEP_INTERVAL_SECONDS` | `60` | Voice sweep cadence; 0 disables. | `main.py:51-53` | Y |
| CAP-CFG-014 | `BRAIN_BUDDY_MCP_ENABLED` | off (`1` only) | Mount MCP. | `:1502` | Y |
| CAP-CFG-015 | `BRAIN_BUDDY_MCP_ALLOWED_HOSTS` | `localhost:*,127.0.0.1:*,[::1]:*` | MCP Host allow-list. | `:1506` | Y |
| CAP-CFG-016 | `BRAIN_BUDDY_CLI_VERIFICATION_ORIGIN` | `""` | CLI device-flow browser origin; empty disables CLI auth. Validated as a bare HTTPS origin (http only for localhost). | `:1501, 1027-` | Y |
| CAP-CFG-017 | `BRAIN_BUDDY_PUBLIC_BASE_URL` | `http://localhost:8000` | A2A push callback origin (canonicalized per environment). | `:1449` | Y |
| CAP-CFG-018 | `BRAIN_BUDDY_AUTH_PUBLIC_ORIGIN` | `""` | Web origin for modern auth (`json_origin`, redirects). | `:1016-1019` (field `public_origin`) | Y |
| CAP-CFG-019 | `BRAIN_BUDDY_AUTH_API_ORIGIN` | `""` | API origin for provider callbacks. | same (`api_origin`) | Y |
| CAP-CFG-020 | `BRAIN_BUDDY_AUTH_GOOGLE_CLIENT_ID` | `""` | Google sign-in. | same | Y |
| CAP-CFG-021 | `BRAIN_BUDDY_AUTH_GOOGLE_CLIENT_SECRET` | `""` | Google secret. | `:1021-1022` | Y |
| CAP-CFG-022 | `BRAIN_BUDDY_AUTH_APPLE_TEAM_ID` | `""` | Apple. | `:1016-1019` | Y |
| CAP-CFG-023 | `BRAIN_BUDDY_AUTH_APPLE_KEY_ID` | `""` | Apple. | same | Y |
| CAP-CFG-024 | `BRAIN_BUDDY_AUTH_APPLE_PRIVATE_KEY` | `""` | Apple P-256 key (secret). | `:1021-1022` | Y |
| CAP-CFG-025 | `BRAIN_BUDDY_AUTH_APPLE_SERVICES_ID` | `""` | Apple web client id. | `:1016-1019` | Y |
| CAP-CFG-026 | `BRAIN_BUDDY_AUTH_APPLE_NATIVE_APP_ID` | `""` | Apple native bundle id. | same | Y |
| CAP-CFG-027 | `BRAIN_BUDDY_AUTH_SMTP_HOST` | `""` | SMTP. | same | Y |
| CAP-CFG-028 | `BRAIN_BUDDY_AUTH_SMTP_PORT` | `587` | SMTP. | same | Y |
| CAP-CFG-029 | `BRAIN_BUDDY_AUTH_SMTP_SENDER` | `""` | From address. | same | Y |
| CAP-CFG-030 | `BRAIN_BUDDY_AUTH_SMTP_USERNAME` | `""` | SMTP user. | same | Y |
| CAP-CFG-031 | `BRAIN_BUDDY_AUTH_SMTP_PASSWORD` | `""` | SMTP secret. | `:1021-1022` | Y |
| CAP-CFG-032 | `BRAIN_BUDDY_AUTH_SMTP_TLS` | `starttls` | `starttls` or `tls`. | `:1016-1019` | Y |
| CAP-CFG-033 | `BRAIN_BUDDY_AUTH_CURRENT_KEY_ID` | `""` | Active keyring key; needed for `crypto_ready`. | same | Y |
| CAP-CFG-034 | `BRAIN_BUDDY_AUTH_KEYRING` | `{}` | JSON `{key_id: secret}`. Duplicate keys or malformed input make it unusable (`{}`). | `:1010-1015` | Y |
| CAP-CFG-035 | `BRAIN_BUDDY_AGENT_RELAY_KEYS` | unset | Relay secret-box keys. Required in production once relay data exists or the relay is not OFF. | `container.py:225-237` | **N** |
| CAP-CFG-036 | `BRAIN_BUDDY_AGENT_STALE_AFTER_SECONDS` | `604800` | Run "stopped reporting" threshold. | `:1453` | Y |
| CAP-CFG-037 | `BRAIN_BUDDY_AGENT_REPORTING_WINDOW_SECONDS` | `3600` | Reporting window. | `:1456` | Y |
| CAP-CFG-038 | `BRAIN_BUDDY_AGENT_CONTENT_RETENTION_SECONDS` | `2592000` | Relay content retention. | `:1460` | Y |
| CAP-CFG-039 | `BRAIN_BUDDY_AGENT_RETENTION_SWEEP_INTERVAL_SECONDS` | `60` | Privacy sweep cadence (CAP-JOB-002). | `:1464` | Y |
| CAP-CFG-040 | `BRAIN_BUDDY_AGENT_CONNECTOR_TIMEOUT_SECONDS` | `10` | A2A call timeout. | `:1467` | Y |
| CAP-CFG-041 | `BRAIN_BUDDY_AGENT_CONNECTOR_MAX_RESPONSE_BYTES` | `64000` | Card and response cap. | `:1470` | Y |
| CAP-CFG-042 | `BRAIN_BUDDY_AGENT_ALLOW_PRIVATE_DESTINATIONS` | off (`1` only, never in production) | Private-IP egress opt-in. | `:1475` | Y |
| CAP-CFG-043 | `BRAIN_BUDDY_AGENT_OBSERVATION_INTERVAL_SECONDS` | `60` | Observer cadence. | `:1479` | Y |
| CAP-CFG-044 | `BRAIN_BUDDY_AGENT_REPLY_WINDOW_SECONDS` | `300` | Held `SendMessage` window. | `:1482` | Y |
| CAP-CFG-045 | `BRAIN_BUDDY_AGENT_DISPATCH_WAIT_SECONDS` | `5` | Dispatch response wait. | `:1485` | Y |
| CAP-CFG-046 | `BRAIN_BUDDY_AGENT_EXCHANGE_WORKERS` | `8` | Exchange pool size. | `:1487` | Y |
| CAP-CFG-047 | `BRAIN_BUDDY_AGENT_MAX_EXCHANGES_PER_CONNECTION` | `2` | Per-connection concurrency. | `:1489` | Y |
| CAP-CFG-048 | `BRAIN_BUDDY_AGENT_OBSERVER_WORKERS` | `4` | Observation pool size. | `:1491` | Y |
| CAP-CFG-049 | `BRAIN_BUDDY_AGENT_CONTROL_WORKERS` | `2` | Control pool size. | `:1492` | Y |
| CAP-CFG-050 | `BRAIN_BUDDY_AGENT_A2A_TASK_MAX_RESPONSE_BYTES` | `262144` | `GetTask` body cap. | `:1494` | Y |
| CAP-CFG-051 | `BRAIN_BUDDY_TASK_TITLE_AUTOCOMPLETE_PROVIDER` | `disabled` (test: `deterministic`) | CAP-EXT-001. | `:1408` | Y |
| CAP-CFG-052 | `BRAIN_BUDDY_TASK_TITLE_AUTOCOMPLETE_MODEL` | `gpt-4o-mini` | | `:1418` | Y |
| CAP-CFG-053 | `BRAIN_BUDDY_TASK_TITLE_AUTOCOMPLETE_API_KEY_ENV` | `OPENAI_API_KEY` | Name of the key variable. | `:1420` | Y |
| CAP-CFG-054 | `BRAIN_BUDDY_REVIEW_NAVIGATOR_PROVIDER` | `disabled` | CAP-EXT-002. | `:1425` | Y |
| CAP-CFG-055 | `BRAIN_BUDDY_REVIEW_NAVIGATOR_MODEL` | `gpt-4o-mini` | | `:1426` | Y |
| CAP-CFG-056 | `BRAIN_BUDDY_REVIEW_NAVIGATOR_API_KEY_ENV` | `OPENAI_API_KEY` | | `:1428` | Y |
| CAP-CFG-057 | `BRAIN_BUDDY_REVIEW_NAVIGATOR_TIMEOUT_SECONDS` | `8` | | `:1431` | Y |
| CAP-CFG-058 | `BRAIN_BUDDY_REVIEW_NAVIGATOR_MAX_INPUT_TOKENS` | `6000` | | `:1434` | Y |
| CAP-CFG-059 | `BRAIN_BUDDY_REVIEW_NAVIGATOR_MAX_OUTPUT_TOKENS` | `300` | | `:1437` | Y |
| CAP-CFG-060 | `BRAIN_BUDDY_REVIEW_NAVIGATOR_MAX_COST_USD` | `0.01` | Per-call cap. | `:1440` | Y |
| CAP-CFG-061 | `BRAIN_BUDDY_REVIEW_NAVIGATOR_MAX_DAILY_COST_USD` | `0.20` | Daily cap. | `:1443` | Y |
| CAP-CFG-062 | `BRAIN_BUDDY_VOICE_ACCURATE_STT_PROVIDER` | test: `deterministic`; else `openai` if `OPENAI_API_KEY` is set, else `disabled` | CAP-EXT-004 and CAP-EXT-005. | `:1270-1281` | Y |
| CAP-CFG-063 | `BRAIN_BUDDY_VOICE_ACCURATE_STT_MODEL` | `nova-3` (deepgram) or `gpt-4o-mini-transcribe` | | `:1303` | Y |
| CAP-CFG-064 | `BRAIN_BUDDY_VOICE_ACCURATE_STT_API_KEY_ENV` | `DEEPGRAM_API_KEY` or `OPENAI_API_KEY` | | `:1305` | Y |
| CAP-CFG-065 | `BRAIN_BUDDY_VOICE_ACCURATE_STT_TIMEOUT_SECONDS` | `180` | | `:1308` | Y |
| CAP-CFG-066 | `BRAIN_BUDDY_VOICE_ACCURATE_STT_MAX_RETRIES` | `2` | | `:1310` | Y |
| CAP-CFG-067 | `BRAIN_BUDDY_VOICE_ACCURATE_STT_RETRY_BACKOFF_SECONDS` | `1,2` | | `:1286` | Y |
| CAP-CFG-068 | `BRAIN_BUDDY_VOICE_ACCURATE_STT_MAX_COST_USD` | `0.50` | | `:1313` | Y |
| CAP-CFG-069 | `BRAIN_BUDDY_VOICE_ACCURATE_STT_ESTIMATED_COST_USD_PER_MB` | `0.01` | | `:1317` | Y |
| CAP-CFG-070 | `BRAIN_BUDDY_VOICE_RECONCILER_PROVIDER` | `disabled` | CAP-EXT-006. | `:1332` | Y |
| CAP-CFG-071 | `BRAIN_BUDDY_VOICE_RECONCILER_MODEL` | `gpt-4o` | | `:1333` | Y |
| CAP-CFG-072 | `BRAIN_BUDDY_VOICE_RECONCILER_API_KEY_ENV` | `OPENAI_API_KEY` | | `:1335` | Y |
| CAP-CFG-073 | `BRAIN_BUDDY_VOICE_RECONCILER_ENDPOINT` | `https://api.openai.com/v1/chat/completions` | | `:1338` | Y |
| CAP-CFG-074 | `BRAIN_BUDDY_VOICE_RECONCILER_TIMEOUT_SECONDS` | `30` | | `:1342` | Y |
| CAP-CFG-075 | `BRAIN_BUDDY_VOICE_RECONCILER_MAX_RETRIES` | `2` | | `:1344` | Y |
| CAP-CFG-076 | `BRAIN_BUDDY_VOICE_RECONCILER_RETRY_BACKOFF_SECONDS` | `1,2` | | `:1324` | Y |
| CAP-CFG-077 | `BRAIN_BUDDY_VOICE_RECONCILER_MAX_COST_USD` | `0.50` | | `:1347` | Y |
| CAP-CFG-078 | `BRAIN_BUDDY_VOICE_RECONCILER_ESTIMATED_COST_USD_PER_MB` | `0.01` | | `:1351` | Y |
| CAP-CFG-079 | `BRAIN_BUDDY_VOICE_RAW_AUDIO_RETENTION_SECONDS` | `86400` | | `:1357` | Y |
| CAP-CFG-080 | `BRAIN_BUDDY_VOICE_WORKING_ARTIFACT_RETENTION_SECONDS` | `604800` | | `:1361` | Y |
| CAP-CFG-081 | `BRAIN_BUDDY_VOICE_AUDIO_ALLOWED_MIME_TYPES` | `audio/wav,audio/wave,audio/x-wav,audio/ogg,audio/webm,audio/mp4,audio/aac` (+`audio/x-brain-buddy-test-text` in test) | | `:1369` | Y |
| CAP-CFG-082 | `BRAIN_BUDDY_VOICE_AUDIO_MAX_CHUNK_BYTES` | `10485760` | | `:1381` | Y |
| CAP-CFG-083 | `BRAIN_BUDDY_VOICE_AUDIO_MAX_TOTAL_BYTES` | `104857600` | | `:1384` | Y |
| CAP-CFG-084 | `BRAIN_BUDDY_VOICE_AUDIO_MAX_CHUNK_COUNT` | `1024` | | `:1387` | Y |
| CAP-CFG-085 | `BRAIN_BUDDY_VOICE_AUDIO_MAX_DURATION_SECONDS` | `1800` | | `:1390` | Y |
| CAP-CFG-086 | `BRAIN_BUDDY_VOICE_AUDIO_ASSUMED_CHUNK_DURATION_SECONDS` | `5` | | `:1393` | Y |
| CAP-CFG-087 | `BRAIN_BUDDY_VOICE_MAX_OPERATION_RECOVERIES` | `2` | | `:1397` | Y |
| CAP-CFG-088 | `BRAIN_BUDDY_VOICE_MAX_CUMULATIVE_COST_USD` | `1.00` | | `:1400` | Y |
| CAP-CFG-089 | `BRAIN_BUDDY_VOICE_LEASE_RECOVERY_MARGIN_SECONDS` | `30` | | `:1403` | Y |
| CAP-CFG-090 | `OPENAI_API_KEY` | unset | Default key for every OpenAI role. Its presence changes the STT default. | `:1275`; `openai_provider.py:32` | Y |
| CAP-CFG-091 | `DEEPGRAM_API_KEY` | unset | Default Deepgram key. | `:1299` (via `_API_KEY_ENV`) | Y |
| CAP-CFG-092 | *indirect*: any variable named by `*_API_KEY_ENV` or by a provider `config.json` `api_key_ref` | n/a | Key indirection. | `container.py:248, 261, 316`; `openai_provider.py:29` | n/a |

Constants that are not configurable (a port must keep them): cookie name and max age
(`config.py:376-392`), rate limits (`rate_limit.py:264-298`), and retention horizons (CRT 30 d,
sync feed 90 d, control ledger 7 d, account grace 14 d). The schema version is read from
`<data>/schema_version` (default `0.1.0`, `config.py:39-41, 1229-1233`).

`.env.example` entries the server does **not** read: `BRAIN_BUDDY_PORT`,
`BRAIN_BUDDY_HERMES_A2A_PORT`, `API_BASE_URL`, `API_PREFIX`, `VITE_API_BASE_URL`,
`FRONTEND_*`, `COMPOSE_PROJECT_NAME` (compose and frontend only). `../fly.backend.toml` sets
`BRAIN_BUDDY_API_KEY_HEADER`, which no code reads.

## 8. Persistent stores (all under `BRAIN_BUDDY_DATA_DIR`)

| ID | Store | Tables / layout | Owning surface | Code |
|---|---|---|---|---|
| CAP-STORE-001 | `tasks.sqlite3` | Tasks: `tasks`, `projects`, `tags`, `task_tags`, `subtasks`, `comments`, `idempotency_records`, `migration_ledger` | tasks, MCP, review writes | `app/modules/tasks/repository.py:78` |
| CAP-STORE-002 | `tasks.sqlite3` (same file) | Review: `review_settings`, `review_sessions`, `review_decisions`, `review_receipts`, `review_park_acks`, `review_bulk_releases`, `navigator_consents`, `navigator_usage` | review, navigator | `app/modules/tasks/review_repository.py:1-6, 135-150` |
| CAP-STORE-003 | `tasks.sqlite3` (same file) | Sync: `sync_scopes`, `sync_devices`, `sync_device_epochs`, `sync_command_receipts`, `sync_change_transactions`, `sync_change_records`, `sync_record_versions`, `sync_legacy_keys`, `sync_snapshots`, `sync_snapshot_pages`, `sync_transfers`, `sync_transfer_pages` | sync v1 | `app/modules/tasks/sync/change_log.py:41-98`; initialized from `tasks/repository.py:38` |
| CAP-STORE-004 | `tasks.sqlite3` (same file) | Job ledger: `jobs`, `job_fence_counter` | durable scheduler | `app/modules/tasks/jobs/repository.py:42-68`; `container.py:153, 512` |
| CAP-STORE-005 | `auth.sqlite3` | `users`, `sessions`, `auth_attempts`, `auth_budgets`, `auth_challenges`, `auth_handoffs`, `auth_identity_bindings`, `auth_mail_jobs`, `auth_proofs`, `auth_migration_ledger`, `auth_apple_grants`, `auth_apple_cleanup_jobs`, `auth_apple_notification_receipts`, `cli_device_grants` | auth, account, admin, CLI auth | `app/repositories/auth_store.py:237`; `app/repositories/cli_auth.py:49` |
| CAP-STORE-006 | `voice_operations.sqlite3` | `brain_dump_operations`, `idempotency_records`, `migration_ledger` | voice | `app/workflows/voice_brain_dump/repository.py:54` |
| CAP-STORE-007 | `brain-dump-media/<owner>/<operation>/` | Raw audio chunk files | voice (purged by CAP-JOB-013) | `voice_brain_dump/repository.py:151-162, 299-330, 508` |
| CAP-STORE-008 | `agents.sqlite3` | `agent_connections`, `agent_runs`, `agent_run_events`, `agent_run_commands`, `agent_idempotency`, `agent_audit`, `agent_audit_buckets`, `agent_schema_migrations` | agents / A2A | `app/modules/agents/repository.py:242` |
| CAP-STORE-009 | `crt_commands.sqlite3` + `.crt-command.lock` | `crt_command_receipts`. The lock file is a process- and worker-global per-owner lock, also used by legacy tree writes and the purge. | CRT | `app/repositories/crt_command.py:22, 53-67` |
| CAP-STORE-010 | `feature_flags.sqlite3` | `feature_flags`, `migration_ledger`, plus legacy `feature-flags/runtime.json` and marker `feature-flags/sqlite-migration-complete.json` | admin / flags | `app/repositories/feature_flag.py:60-66, 266-269` |
| CAP-STORE-011 | `sync_control_ledger.sqlite3` | `control_entries`, `control_meta` | sync restore, account purge | `app/container.py:766-768`; `app/modules/tasks/sync/control_ledger.py` |
| CAP-STORE-012 | Tree JSON files | `<tree_id>/tree.json`, `<tree_id>/versions/`, `<tree_id>/validation/`, `.locks/`, `index.json` + `.index.lock` | legacy trees and CRT | `app/repositories/tree.py:18-28, 145`; `version.py:13-26`; `validation.py:12-19`; `index.py:16, 59` |
| CAP-STORE-013 | `config.json` | Validation provider registry | validation | `app/repositories/provider.py:11-19` |
| CAP-STORE-014 | `invites/` + `.invite-repository.lock` | Invite JSON files | auth signup, CLI | `app/repositories/invite.py:19-30, 67` |
| CAP-STORE-015 | Legacy JSON (import sources and migration journals) | `users/` (`_by_email.json`, `_profile_transaction.json`), `sessions/`, `.auth-migration.lock`, auth backup; `tasks/`, `projects/`, `contexts/`, `task-subtasks/`, `task-comments/`, `task-commands/`; `brain-dump-operations/`, `voice-operation-commands/` | auth migration, task and voice import | `app/repositories/user.py:21-35`; `session.py:20-29`; `app/services/auth_migration.py:36-39, 148`; `tasks/repository.py:302-394`; `voice_brain_dump/repository.py:128-166` |
| CAP-STORE-016 | `schema_version` | Single-line version | health, OpenAPI | `config.py:40, 1229-1233` |
| CAP-STORE-017 | In-memory (non-persistent) | Rate-limit buckets; sync gateway, executor and hint hub on `app.state`; observer wake set; `TreeService` LRU cache (16) | various | `rate_limit.py`; `sync.py:115-133`; `sync_hints.py:56-68` |

## Counts

| Section | Rows |
|---|---|
| 1. HTTP routes | 153: 146 decorated handlers, 2 health, 4 docs/OpenAPI, 1 MCP mount |
| 2. MCP | 7 rows (4 tools, 0 resources, 0 prompts, 3 server-level behaviors) |
| 3. Background jobs | 26 |
| 4. CLIs | 8 (1 server entry point + 7 `app.cli` commands) |
| 5. Middleware / cross-cutting | 21 |
| 6. External integrations | 13 |
| 7. Config | 92 (91 named variables + 1 indirect row) |
| 8. Stores | 17 |

The 146 decorated handlers break down as: account 6, admin 11, agents 16, auth 4, cli_auth 4,
modern_auth 17, review 7, review_flow 7, review_navigator 4, routes (CRT 8 + legacy 20) 28,
sync 4, sync_delta 2, sync_snapshots 2, sync_hints 1, tasks 33.

## Ambiguities and open questions for the port

1. **No-store gap.** `GET /api/account` (no trailing slash) does not get `Cache-Control: no-store` or `Referrer-Policy`, because the check is `startswith("/api/account/")` (`middleware.py:122-126`). It is unclear whether to preserve this.
2. **Two correlation-id rules.** The middleware accepts `[0-9A-Za-z._-]{1,64}`, but `/api/crt/*` returns 400 unless the value is a canonical UUID (`dependencies.py:215-230`).
3. **Inconsistent sync flag gating.** `GET /sync/v1/commands/{id}` never checks `rust_core_sync`, `capabilities` reports it, and `POST commands` answers replays before the flag check. This may or may not be intentional.
4. **MCP edge cases.**
   * Behavior of `/api/mcp` without the trailing slash, and the GET/DELETE semantics under `stateless_http`, are SDK-defined.
   * App exception handlers do not apply inside the mount, but the correlation middleware does.
   * The default allowed hosts are localhost only, which looks unusable in production unless `BRAIN_BUDDY_MCP_ALLOWED_HOSTS` is set.
5. **OpenAPI and docs are public in production** (`/api/docs`, `/api/redoc`, `/api/openapi.json`), unauthenticated. It is unclear whether this is part of the contract.
6. **`BRAIN_BUDDY_API_KEY_HEADER`** is set in `fly.backend.toml` but not read anywhere.
7. **Undocumented variables.** `BRAIN_BUDDY_AGENT_RELAY_KEYS` and `BRAIN_BUDDY_ACCOUNT_PURGE_GRACE_SECONDS` are read but missing from `.env.example`.
8. **Legacy JSON import paths** (CAP-STORE-015) are read at open and migration time. A 1:1 port must decide whether it still needs to import pre-SQLite volumes or can require an already-migrated volume.
9. **Durable vs legacy privacy step sets differ.** Control-ledger prune (CAP-JOB-011) runs only in the legacy loop. Auth cleanup, CLI cleanup and CRT reconciliation always stay on the legacy thread even in durable mode.
10. **`cli_auth`** is an "optional managed" flag in `feature_flag.py:93`. It is not in `KNOWN_FEATURE_FLAGS`, so it never appears in `/me` `feature_flags`.
11. **Rate limits are per process and in memory.** Multi-worker or multi-machine behavior is undefined today (single Fly machine).
12. **`bb_core` (PyO3)** carries the task, review and sync rules. "1:1" for those surfaces means linking the same crate, not re-porting the Python facades (`rust_task_facade.py`, `rust_review_facade.py`). The Python fallback path is still live while `rust_core_sync` is off.
13. **CAP-HTTP-097 `ai-feedback`** looks like an AI call but is a deterministic local summary.
14. **`DELETE /api/tags/{id}`** returns 200 with a body, unlike the other deletes (204).
15. **`ValidationFailure` maps to 400**, not 422, while request-schema errors are 422. Both must be preserved.
16. **FastAPI `on_event("shutdown")`** ordering (several hooks) and the MCP lifespan composition decide shutdown order. Join timeouts are 5 s and 12 s.
17. **`/health` vs `/api/health`.** The frontend nginx proxies only `/api/` (`../deploy/nginx/default.conf:33-46`), while Fly checks the backend directly at `/health`. Both must stay.
