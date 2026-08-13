# Tasks: Minimum Admin Portal

Vertical RED → GREEN. See [plan.md](plan.md) for why each exists.

## Phase 1 — operator allow-list config

- [x] **T001** GREEN: `AdminSettings.operator_emails` in
  `backend/app/core/config.py`, mirroring `FeatureFlagSettings.internal_users`
  (normalized, validated, fail-closed empty default); wire into `AppConfig`
  and `_build_config` from `BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS`.
  *(009-FR-001)*

## Phase 2 — backend lookup + revoke

- [x] **T002** RED: `backend/tests/test_admin_config.py` — normalization,
  invalid-email fail-closed, empty default. *(009-FR-001)*
- [x] **T003** RED: `backend/tests/test_admin_service.py` — `is_operator`
  true/false, `find_account` exact ID and exact email match / no match,
  `revoke_sessions` idempotent zero-count and real revoke, log records carry
  no email/display name. *(009-FR-003, 007, 008)*
- [x] **T004** RED: `backend/tests/test_admin_api.py` — 401 unauthenticated,
  403 non-operator (identical response whether or not the target account
  exists), lookup by ID, lookup by email, lookup rejects zero/both fields,
  response contains only the four allowed fields, revoke is idempotent,
  existing `/api/account` and `/api/auth/me` behavior unchanged.
  *(009-FR-002, 003, 004, 007, 009, 010)*
- [x] **T005** GREEN: `backend/app/schemas/admin.py`,
  `backend/app/services/admin_service.py`, `backend/app/api/admin.py`,
  `require_operator`/`get_admin_service` in
  `backend/app/api/dependencies.py`, container wiring, router mount in
  `backend/app/main.py`. Make T002–T004 pass.

## Phase 3 — frontend portal

- [x] **T006** RED: `frontend/src/features/admin/__tests__/AdminPortalPage.test.tsx`
  — renders the lookup form, shows found/not-found/denied states, requires
  the explicit confirm step before calling revoke, shows the revoked count.
  *(009-FR-005, 006)*
- [x] **T007** GREEN: `frontend/src/api/adminTypes.ts`, `adminLookupAccount`/
  `adminRevokeSessions` in `frontend/src/api/client.ts`,
  `frontend/src/features/admin/AdminPortalPage.tsx`, `/admin` route in
  `frontend/src/app/AppRoutes.tsx`. Make T006 pass.

## Phase 4 — docs and verification

- [x] **T008** Document `BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS` in `.env.example`.
- [x] **T009** Run focused backend/frontend suites, then
  `make test-backend`, frontend lint/type/build/test,
  `scripts/check_spec_kit_specs.py`, `scripts/check_requirement_coverage.py
  specs/009-admin-portal`, `git diff --check`.
- [ ] **T010** Independent verification and landing (owned by Hermes; not
  done in the authoring session, which does not commit, push, or open a PR).
