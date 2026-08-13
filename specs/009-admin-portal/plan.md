# Implementation Plan: Minimum Admin Portal

**Spec**: [spec.md](spec.md) · **Design**: [design.md](design.md) · **Tasks**: [tasks.md](tasks.md)

## Approach

Reuse, don't invent. Operator authorization is one more allow-list config
model shaped exactly like `FeatureFlagSettings.internal_users` (backend/app/
core/config.py) — a separate list, because feature-flag rollout cohort and
admin authorization are different trust boundaries, but the same pattern:
env-driven, normalized, validated, fail-closed. Account lookup and session
revoke reuse `UserRepository.get_by_id` / `get_by_email` and the existing
`SessionRepository.delete_all_for_user` bulk-delete, exactly as
`AccountService` already does for self-serve deletion. The mutation's
same-origin protection is the repository's existing posture: no CORS
allow-list is configured anywhere in the backend, and the session cookie is
already `HttpOnly` + `SameSite=Lax` — nothing new is added for this.
"Content-free security audit" is `logger.info`/`logger.warning` calls through
the stdlib `logging` module already used by `AccountService`, not a new
audit table (the agent-relay module's SQLite `agent_audit` table is a
heavier, general-purpose audit platform the spec explicitly rules out).

## Changed surfaces

| File | Change |
| --- | --- |
| `backend/app/core/config.py` | new `AdminSettings.operator_emails` (mirrors `FeatureFlagSettings.internal_users`); wired into `AppConfig` and `_build_config` from `BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS` (009-FR-001) |
| `backend/app/schemas/admin.py` | new: `AdminAccountLookupRequest` (exactly one of `account_id`/`email`), `AdminAccountResponse` (009-FR-004), `AdminRevokeSessionsResponse` |
| `backend/app/services/admin_service.py` | new `AdminService`: `is_operator`, `find_account`, `revoke_sessions`; content-free `logger.info`/`logger.warning` (009-FR-003, 007, 008) |
| `backend/app/api/admin.py` | new router: `POST /admin/accounts/lookup`, `POST /admin/accounts/{account_id}/revoke-sessions`, both behind a `require_operator` dependency (009-FR-002) |
| `backend/app/api/dependencies.py` | `get_admin_service`, `require_operator` (401 via existing `get_current_user`, then 403 if not an operator) |
| `backend/app/container.py` | wire `AdminService` into `Container` |
| `backend/app/main.py` | mount the admin router at `{api_prefix}/admin` |
| `frontend/src/api/adminTypes.ts`, `frontend/src/api/client.ts` | typed request/response, `adminLookupAccount` / `adminRevokeSessions` methods |
| `frontend/src/features/admin/AdminPage.tsx` | new page: lookup form, found/not-found/denied states, confirm-then-revoke dialog (reuses `Overlay`, `Button`, `Field`, `Feedback`, `SectionCard`) (009-FR-005, 006) |
| `frontend/src/app/AppRoutes.tsx` | new `/admin` route behind `ProtectedRoute` |
| `.env.example` | document `BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS` |

## Key decisions

1. **Operator = existing member account on an allow-list, not a new
   credential.** `BRAIN_BUDDY_ADMIN_EMAIL`/`_PASSWORD` already seed one
   account; operators sign in the same way. This avoids a second auth
   system entirely, per the frozen slice.
2. **A separate allow-list from feature-flag `internal_users`.** Feature
   flags gate exposure; the operator list gates a real authorization
   decision. Reusing one list for both would let a feature-flag testing
   cohort silently gain session-revoke power, which is exactly the kind of
   scope-widening the founder ruled out — same *pattern*, different *list*.
3. **Deny before touch.** `require_operator` runs before any account lookup
   or mutation, so a denial can never vary with whether the target account
   exists (009-FR-002); the lookup's own "not found" is a separate, later
   check reachable only by an already-authorized operator.
4. **No audit subsystem.** `logger.info`/`logger.warning` through the
   existing stdlib logger, content-free (operator id, account id, outcome
   only) — matching `AccountService.change_password`/`request_deletion`,
   not the agent-relay module's SQLite audit table.
5. **No new CSRF/same-origin mechanism.** The backend has no CORS
   middleware anywhere and the session cookie is already `SameSite=Lax`;
   adding a token or header check would be a second enforcement of a
   property the repository already has.
6. **Idempotent revoke.** `SessionRepository.delete_all_for_user` already
   returns a count and treats "nothing to delete" as success — the admin
   endpoint just surfaces that count, no new idempotency-key machinery.

## Constitution check

- Contract-first: new request/response schemas are `StrictBaseModel`s with
  explicit fields, matching every other route in the repository.
- Tested delivery: backend service + route tests and a frontend page test,
  TDD (RED before GREEN).
- No new dependency, no new background job, no new data store.

## Risks

- **Operator allow-list left empty in production.** Fails closed: an empty
  list means `is_operator` is `False` for everyone, so the portal is simply
  unreachable rather than open — an operations gap, not a security one.
- **Scope creep from reviewer speculation.** The frozen slice and explicit
  non-goals in [spec.md](spec.md) are the boundary; a finding that proposes
  new infrastructure (rate limiter, audit platform, state machine) is
  out of scope unless current `origin/main` already has it and a failing
  test proves it necessary here.
