# Implementation Plan: Minimum Admin Portal

**Spec**: [spec.md](spec.md) · **Design**: [design.md](design.md) · **Tasks**: [tasks.md](tasks.md)

**Risk class: ASK (high).** See [Landing](#landing-adr-0008-ask) below — this
is not a footnote, it decides how the feature reaches `main`.

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

The cross-owner reach is not a silent exception: it is authorized by
[ADR-0017](../../docs/decisions/0017-operator-account-administration-narrow-owner-scoping-exception.md),
which narrows ADR-0001's owner-scoping assumption to account-record reads and
session revocation, and restates that member content stays owner-scoped.

Two properties the first implementation pass assumed rather than enforced are
now planned work, not commentary:

- **Operator identity must not be self-claimable.** The allow-list matches on
  `user.email`, which a member can change through `POST /api/account/email`
  without any ownership verification (`docs/auth.md` records that email
  changes are unverified). Any allow-listed address without a live account is
  therefore claimable, and claiming it confers full operator power. The fix
  that fits the frozen slice is to reserve the configured addresses:
  `AuthService.signup` and `AccountService.change_email` refuse them, while
  `AuthService.seed_admin` — the only provisioning path — may still create or
  rotate the configured identity (009-FR-012).
- **The portal ships behind a default-OFF rollout flag** (`admin_portal`),
  using the existing `KNOWN_FEATURE_FLAGS` mechanism. ADR-0008 is explicit
  that flags are exposure control and never authorization, so the flag sits
  *in addition to* `require_operator`, never in place of it (009-FR-013).

## Changed surfaces

Rows marked **(repair)** describe work still outstanding after campaign 1;
the rest are already present on this branch and are listed because the table
must describe the delivered surface, not the intended one.

| File | Change |
| --- | --- |
| `backend/app/core/config.py` | `AdminSettings.operator_emails` (mirrors `FeatureFlagSettings.internal_users`); wired into `AppConfig` and `_build_config` from `BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS` (009-FR-001). **(repair)** `admin_portal` declared in a new `PRIVATE_FEATURE_FLAGS` tuple, default OFF, read via `private_flag_effective` — **not** in `KNOWN_FEATURE_FLAGS`, which `effective_flags` projects into every member's `/api/auth/me` payload (009-FR-010, 009-FR-013) |
| `backend/app/schemas/admin.py` | `AdminAccountLookupRequest` (exactly one of `account_id`/`email`), `AdminAccountResponse` (009-FR-004), `AdminRevokeSessionsResponse`, `AdminStatusResponse` (009-FR-011) |
| `backend/app/services/admin_service.py` | `AdminService`: `is_operator`, `find_account`, `revoke_sessions`; content-free `logger.info`/`logger.warning` (009-FR-003, 007, 008). **(repair)** the lookup record must carry the *resolved* account id, never the raw query. **(repair)** exact-match semantics: an `ACCOUNT_ID_PATTERN` charset guard *before* any repository read (so a traversal id never reaches `_user_path`), plus a post-fetch identity check — `user.id == account_id`, `user.email == email` — because `get_by_email` normalizes and a case-insensitive filesystem would otherwise resolve a variant (009-FR-003) |
| `backend/app/api/admin.py` | router: `GET /admin/status` (009-FR-011), `POST /admin/accounts/lookup`, `POST /admin/accounts/{account_id}/revoke-sessions`, all behind `require_operator` (009-FR-002) |
| `backend/app/api/dependencies.py` | `get_admin_service`, `require_operator` — resolves the session cookie itself rather than composing `get_current_user`, so the 401 can carry one generic content-free warning (key decision 7). **(repair)** distinguish the capability-probe denial from a data-route denial in the log level/message (009-FR-008); **(repair)** `require_admin_portal_enabled` for the rollout flag (009-FR-013) |
| `backend/app/services/auth_service.py` | **(repair)** `signup` refuses an address on the operator allow-list; `seed_admin` deliberately still may provision it (009-FR-012) |
| `backend/app/services/account_service.py` | **(repair)** `change_email` refuses an address on the operator allow-list, with the existing conflict behavior and no disclosure that the address is reserved (009-FR-012) |
| `backend/app/container.py` | `AdminService` wired into `Container` (container.py:384) |
| `backend/app/main.py` | admin router mounted at `{api_prefix}/admin` (main.py:244) |
| `frontend/src/api/adminTypes.ts` | `AdminAccountLookupRequest`, `AdminAccountResponse`, `AdminRevokeSessionsResponse`, `AdminStatusResponse` |
| `frontend/src/api/client.ts` | `getAdminStatus`, `lookupAdminAccount`, `revokeAdminAccountSessions` (client.ts:580-590) |
| `frontend/src/api/adminHooks.ts` | `adminKeys`, `useAdminStatus`. **(repair)** the query must be scoped to `/admin` and cached for the session (no shell-wide enablement, no refetch-on-focus storm) (009-FR-010, 011) |
| `frontend/src/features/admin/AdminPage.tsx` | the page: lookup form, D-01…D-09 states, confirm-then-revoke dialog (reuses `Overlay`, `Button`, `Field`, `Feedback`, `SectionCard`) (009-FR-005, 006). **(repair)** split D-08 (confirmed denial) from D-09 (capability check failed, retryable); self-revoke warning; focus restoration on dialog close, held **locally** in `AdminPage` rather than in the shared `Overlay` |
| `frontend/src/components/shell/AppShell.tsx` | **(repair — removal)** the `useAdminStatus()` call in `AccountMenu` and the "Admin portal" menu item are out of intended scope under PD-1 and must be removed (009-FR-010) |
| `frontend/src/app/AppRoutes.tsx` | `/admin` route behind `ProtectedRoute` (AppRoutes.tsx:75-78) |
| `frontend/src/components/shell/__tests__/AppShell.test.tsx` | **(repair — rewrite)** the three menu-item tests are inverted, not deleted, and the shared `getAdminStatus` spy now asserts the call never happens (PD-1, 009-FR-010) |
| `frontend/src/pages/PrivacyPolicyPage.tsx` | **(repair)** the user-facing summary `docs/data-retention.md` requires to stay in sync: operator/support account administration as a purpose, its Art. 6(1)(f) basis, content-free platform-log retention, and exclusion from export and purge; `LAST_UPDATED` bumped. Text only (PD-4, 009-SC-005) |
| `.github/workflows/deploy-fly-production.yml` | stages `BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS="${BRAIN_BUDDY_ADMIN_EMAIL}"` on every deploy. This is the PD-2 decision made concrete, and it is an ASK-class file. **(repair)** the authoritative `BRAIN_BUDDY_FEATURE_FLAGS` value deliberately **does not name `admin_portal` on this release**: Fly secrets are app-scoped and survive an image swap, so a staged `admin_portal=off` would still be pending when a rollback restores the captured pre-009 image — whose allow-list has no such flag and which fails startup on an unknown name. Omission *is* OFF for both images. The ASK-class edit-and-deploy requirement for enabling it later, and the emergency `BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS=` lever, are recorded in place. Pinned by `scripts/validate_trunk_delivery.py` (rollback-parseability check plus its mutation test) and `backend/tests/test_admin_deploy_contract.py` |
| `.env.example` | **(repair)** document `BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS` — the claim that this was done was false, see tasks.md |
| `docs/auth.md` | **(repair)** the seeded admin account is no longer privilege-free; `BRAIN_BUDDY_ADMIN_PASSWORD` is an admin-grade credential (PD-2, PD-5) |
| `docs/data-retention.md` | **(repair)** admin access records as their own processing category: platform log retention, excluded from export, not reached by purge (PD-4, 009-SC-005) |
| `docs/decisions/0017-operator-account-administration-narrow-owner-scoping-exception.md` | new ADR narrowing ADR-0001's owner-scoping assumption |

## Key decisions

1. **Operator = existing member account on an allow-list, not a new
   credential.** `BRAIN_BUDDY_ADMIN_EMAIL`/`_PASSWORD` already seed one
   account; operators sign in the same way. This avoids a second auth
   system entirely, per the frozen slice. PD-2 fixes production to exactly
   that seeded identity.
2. **A separate allow-list from feature-flag `internal_users`.** Feature
   flags gate exposure; the operator list gates a real authorization
   decision. Reusing one list for both would let a feature-flag testing
   cohort silently gain session-revoke power — same *pattern*, different
   *list*. The `admin_portal` flag (decision 9) does not change this: it can
   only take capability away, never grant it.
3. **Deny before touch.** `require_operator` runs before any account lookup
   or mutation, so a denial can never vary with whether the target account
   exists (009-FR-002); the lookup's own "not found" is a separate, later
   check reachable only by an already-authorized operator. Acceptance proves
   this by effect (no repository read, sessions still valid), not only by
   comparing two response bodies.
4. **No audit subsystem.** `logger.info`/`logger.warning` through the
   existing stdlib logger, content-free (operator id, resolved account id,
   outcome only) — matching `AccountService.change_password`/
   `request_deletion`, not the agent-relay module's SQLite audit table. Their
   retention, export and purge disposition is PD-4, recorded in
   `docs/data-retention.md`.
5. **No new CSRF/same-origin mechanism.** The backend has no CORS
   middleware anywhere and the session cookie is already `SameSite=Lax`;
   adding a token or header check would be a second enforcement of a
   property the repository already has. Because the whole of 009-FR-009 rests
   on those two properties, they get a pinning test rather than a promise.
6. **Idempotent revoke for an existing account; 404 for an unknown one.**
   `SessionRepository.delete_all_for_user` already returns a count and treats
   "nothing to delete" as success, so the endpoint surfaces that count — but
   the service checks account existence first, because a typo and a real
   zero-session account must not read alike (PD-3, 009-FR-007).
7. **`require_operator` resolves the session itself, deliberately.** It does
   not compose `get_current_user`, because the 401 branch must emit one
   generic content-free warning that `get_current_user` does not produce.
   The cost is two session-resolution paths in one ASK-class module, so a
   test pins both to identical cookie/expiry behavior; without that test this
   duplication is a latent divergence, not a design.
8. **Input classification lives in the client, and is stated once** in
   [design.md](design.md). The server accepts exactly one of two fields and
   matches each exactly; it does not sniff. The client's email pattern must
   be at least as permissive as what `AdminSettings` and `seed_admin` accept,
   or a real account becomes unfindable.
9. **Default-OFF `admin_portal` rollout flag.** Every `/admin` route and the
   screen are gated by the existing allow-listed flag mechanism, OFF by
   default (ADR-0008 SHIP-with-OFF-flag posture). This does not lower the
   landing class — the authorization boundary itself is still ASK — but it
   means the surface is inert until deliberately enabled.
10. **Operator addresses are reserved.** Signup and self-serve email change
    refuse them; only `seed_admin` may bind the configured identity. This
    closes the self-claim path without adding email verification, a new
    subsystem, or an account-ID-keyed allow-list format change.

## Constitution check

- Contract-first: new request/response schemas are `StrictBaseModel`s with
  explicit fields, matching every other route in the repository.
- Tested delivery: backend service + route tests and frontend page and route
  tests, TDD (RED before GREEN) — see [tasks.md](tasks.md), which is ordered
  that way and grouped into independently acceptable lanes.
- Privacy (Principle I): no real user data in evidence; the manual acceptance
  check uses a purpose-seeded `@example.com` account and requires redaction.
- No new dependency, no new background job, no new data store.
- ADR alignment: ADR-0001 owner scoping is narrowed by ADR-0017 for exactly
  two operations; ADR-0008 classification is recorded below; ADR-0010/0011
  runtime neutrality is respected — nothing here requires Hermes.

## Landing (ADR-0008 ASK)

**Class: ASK (high risk).** Three independent triggers, any one of which is
sufficient:

- it creates an authorization boundary and changes authentication/privacy
  enforcement;
- it edits `backend/app/api/dependencies.py`, an explicit ASK exact path in
  `scripts/classify_path_risk.py` and ADR-0008;
- it edits `.github/workflows/deploy-fly-production.yml`, and `.github/` is an
  ASK prefix.

ADR-0012 additionally derives high risk from any ASK surface, and the campaign
classifier escalated this feature to high independently.

Consequences, all mandatory:

- **No automatic promotion.** This must not land through the PR-less
  verified-trunk deploy-key path reserved for SHIP/SHOW.
- **Explicit recorded approval** from the maintainer before landing.
- **Green required CI on the exact SHA being landed** — not on an ancestor,
  not on a rebased equivalent.
- **A short, audited, temporary ruleset intervention**, recording who, why,
  and when the ruleset was re-enabled. The PR carries the review evidence;
  the audited intervention performs the landing.

**Rollback.** Ordered, and each step is independently safe:

1. The `admin_portal` flag is the first lever, **with the same restaging
   caveat as lever 2**: `BRAIN_BUDDY_FEATURE_FLAGS` is pinned in
   `.github/workflows/deploy-fly-production.yml` (which now stages
   `admin_portal` is deliberately unnamed there on this release, which is OFF)
   and restaged on every release, so an out-of-band
   `flyctl secrets set` acts immediately but is reverted by the next deploy.
   The durable levers are editing that ASK-class workflow line plus a deploy,
   or a code revert. Turning the portal **on** in production is the same
   workflow edit — it is not reachable from the code default at all.
2. Clearing `BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS` fails closed — the portal
   becomes unreachable for everyone. Note that the production deploy restages
   this value from `BRAIN_BUDDY_ADMIN_EMAIL` on the next release, so a secrets
   edit alone is not durable; the flag or a code revert is.
3. A backend revert leaves the staged secret inert — an unread environment
   variable, not a dangling grant.
4. A frontend deployed ahead of the backend degrades to `/admin` rendering
   D-09/D-08 rather than breaking any existing screen.
5. **Session revoke is not rollback-able.** A member whose sessions were
   revoked must sign in again on every device; no revert restores them. This
   is the feature's only irreversible external effect and is part of why the
   class is ASK.

## Risks

- **Operator allow-list left empty in a self-hosted deployment.** Fails
  closed: an empty list means `is_operator` is `False` for everyone, so the
  portal is simply unreachable rather than open — an operations gap, not a
  security one. `.env.example` must say so, or the failure is silent.
- **Production operator power is derived from the CI-held smoke secret.**
  Accepted deliberately (PD-2/PD-5): `BRAIN_BUDDY_ADMIN_EMAIL` is both the
  deploy smoke identity and the sole operator, so a leak of that GitHub
  Actions secret is a leak of cross-account lookup and session revoke, and
  rotating the smoke identity silently transfers operator power. Mitigation
  is documentation and the default-OFF flag, not a second identity.
- **The allow-list is restaged on every deploy.** An operator added
  out-of-band with `fly secrets set` is reverted by the next release, with no
  warning. Adding a second operator means editing an ASK-class workflow file.
- **Denial-log noise.** If the capability check runs anywhere but `/admin`,
  ordinary member navigation manufactures a continuous stream of admin-denial
  warnings and the FR-008 record stops being a signal. PD-1 plus 009-FR-011
  are what keep it legible.
- **Scope creep from reviewer speculation.** The frozen slice and explicit
  non-goals in [spec.md](spec.md) are the boundary; a finding that proposes
  new infrastructure (rate limiter, audit platform, state machine, dedicated
  operator account, audit UI) is out of scope unless current `origin/main`
  already has it and a failing test proves it necessary here.
