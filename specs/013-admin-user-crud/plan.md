# Implementation Plan: Admin Users CRUD and two-tab portal

**Feature**: `specs/013-admin-user-crud/` · **Spec**: [spec.md](spec.md) · **Design**: [design.md](design.md)
**Base audited**: `github/main` @ `dd9348136843af4c299942a077ff8e7cd79ebf45`
**Risk**: implementation and release are **ASK (high)**; this planning-only commit is documentation.

## Goal and architecture

Extend the existing modular-monolith admin vertical rather than create a user-directory subsystem. `backend/app/api/admin.py` owns strict HTTP contracts; `AdminService` owns cross-account lifecycle rules and content-free audit; `UserRepository` remains account persistence; `AuthService` remains the only password policy/hash path; `AccountService.purge_account` remains the only full erasure orchestration. The frontend extends the existing admin API/hooks/page and mounts the current feature-flag section under a tab.

ADR-0021 expands ADR-0017 for account-record list/create/update/purge only. Member content remains inaccessible to operators. ADR-0019 keeps `/admin` operator-only and always available; feature-flag behavior is unchanged. ADR-0008 makes implementation ASK because it changes auth/privacy and performs destructive erasure.

## Contract

| Method/path | Request | Success | Errors/invariants |
|---|---|---|---|
| `GET /api/admin/accounts` | none | `200 {accounts: AdminAccountResponse[]}` sorted by `(email,id)` | 401/403 before list read; no pagination/search |
| `POST /api/admin/accounts` | `{email, display_name?, password}` | `201 AdminAccountResponse` | existing policy/hash path; generic 409 for taken/reserved; no session/invite |
| `PUT /api/admin/accounts/{id}` | `{email, display_name}` | `200 AdminAccountResponse` | exact id; 403 operator-email change; generic 409; marker/hash preserved |
| `DELETE /api/admin/accounts/{id}` | none | `200 {account_id, deleted:true}` | 403 self/operator; 404 absent; calls `purge_account`; failure never claims delete |
| existing lookup/revoke/feature-flag routes | unchanged | unchanged | preserved compatibility and behavior |

`AdminAccountResponse` stays the single safe projection. Add `AdminAccountsResponse`, `AdminCreateAccountRequest`, `AdminUpdateAccountRequest`, and `AdminDeleteAccountResponse` as strict schemas. Display name is normalized using the existing profile rule (strip; empty/null stores null). Stable ordering is canonical email then id, independent of file order.

## Service and persistence boundary

- Add an internal `AuthService.create_account_without_invite`-style operation (final name may follow neighboring naming) that validates with the existing password policy, normalizes/reserves email, generates the existing `user_<uuid>` id, hashes with `hash_password`, and calls `UserRepository.create`; it creates neither invite nor session and logs no email/password. `signup` and `seed_admin` behavior stay unchanged.
- Inject `AuthService` and `AccountService` into `AdminService`; reorder container construction without changing singleton ownership. Do not instantiate services inside routes.
- `AdminService.list_accounts` sorts a fresh `UserRepository.list_users()` projection. `create_account`, `update_account`, and `delete_account` enforce admin-specific rules and each terminate in one audit outcome.
- Update uses `UserRepository.update_email` plus `mutate` while preserving `password_hash`, timestamps and `deletion_requested_at`. Tests must cover a failure between email and profile operations; if the current two-write repository contract cannot provide an atomic combined update, add one narrow repository method under `_write_lock` that writes a coherent email index/user record. Do not add a database or migration.
- Delete resolves exact safe id, rejects self/configured operators, then delegates to `AccountService.purge_account`. Preserve marker-before-scrub, degraded-store halt/retry, cohort scrub, and user-last deletion ordering. Do not copy the erasure inventory into `AdminService`.
- Pending deletion is visible, never silently cleared by create/update/revoke, and deliberately bypassed only by confirmed admin purge.

## Changed surfaces

| Path | Planned change |
|---|---|
| `docs/decisions/0021-operator-account-lifecycle-administration.md` | accepted bounded supersession of ADR-0017 |
| `backend/app/schemas/admin.py` | list/create/update/delete strict contracts |
| `backend/app/services/auth_service.py` | reusable no-invite/no-session account creation through existing password path |
| `backend/app/services/admin_service.py` | list/create/update/delete policy + content-free audit |
| `backend/app/repositories/user.py` | only if required for atomic email+display update; no new persistence |
| `backend/app/api/admin.py` | four routes, all `Depends(require_operator)` |
| `backend/app/container.py` | dependency construction/injection order |
| `backend/tests/test_admin_service.py` | service RED→GREEN policy/audit tests |
| `backend/tests/test_admin_api.py` | authz, wire contracts, conflicts and lifecycle matrix |
| `backend/tests/test_account_service.py` | reuse/extend purge evidence only for admin delegation/degraded outcome |
| `frontend/src/api/adminTypes.ts` | request/list/delete types |
| `frontend/src/api/client.ts` | four typed calls |
| `frontend/src/api/adminHooks.ts` | owner-scoped users query + mutation invalidation |
| `frontend/src/features/admin/AdminPage.tsx` | accessible tabs and Users tab composition |
| `frontend/src/features/admin/AdminUsersSection.tsx` | new bounded table/forms/dialogs |
| `frontend/src/features/admin/__tests__/AdminPage.test.tsx` | tab/access/revoke regression |
| `frontend/src/features/admin/__tests__/AdminUsersSection.test.tsx` | list/create/edit/delete/a11y states |
| `frontend/src/features/admin/__tests__/AdminFeatureFlagsSection.test.tsx` | unchanged behavior; mount-under-tab regression if needed |
| `frontend/tests/admin-users.spec.ts` | synthetic full-stack browser journey with Allure taxonomy |
| `docs/auth.md`, `docs/data-retention.md` | describe bounded lifecycle administration and content-free operation logs; no new store |

No mobile, workflow/deploy, feature-flag store/registry, role, audit-store or self-service account screen change is planned.

## Threat and privacy assumptions

- The operator session is already admin-grade. `require_operator` is the sole authorization gate and runs before account data access.
- Account records are personal data but explicitly authorized by ADR-0021; owned content remains unreachable.
- Email is necessary UI/API data but prohibited from audit logs. Password is secret and prohibited from every output/evidence path.
- IDs from paths pass the existing exact charset/post-fetch identity checks before repository path construction.
- UI-disabled operator actions are convenience only; server rules are tested directly.
- Create/update races fail through repository uniqueness/locking. Delete races converge through marker-first idempotent purge. A failed purge remains visibly not complete.

## Verification strategy

Every behavior follows focused RED→GREEN with `013-FR-nnn` names and Allure taxonomy.

1. Backend targeted: `cd backend && pytest tests/test_admin_service.py tests/test_admin_api.py tests/test_account_service.py -q --alluredir=allure-results`.
2. Frontend targeted: `cd frontend && npm test -- --run src/features/admin/__tests__/AdminPage.test.tsx src/features/admin/__tests__/AdminUsersSection.test.tsx src/features/admin/__tests__/AdminFeatureFlagsSection.test.tsx`.
3. Full-stack browser: `./scripts/run_playwright_e2e.sh frontend/tests/admin-users.spec.ts` (or the runner's supported file filter), using synthetic `@example.com` data only.
4. Regression/build: `make check-specs`, `make verify-backend`, `make verify-frontend`, and existing 009/010 suites; mobile is unchanged but final required CI remains authoritative.
5. Privacy: captured logger/response/Allure attachments planted with password/email/display-name sentinels; assert prohibited values absent. Do not print the initial password in RED/GREEN logs.
6. Independent review and QA bind to one immutable candidate SHA; any SHA change invalidates their evidence.
7. ASK landing requires Max's recorded approval, exact-SHA green required CI and ADR-0008's audited landing path.
8. Production DoD: after deploy proof shows production at that exact SHA, Max/operator performs `spec.md` SC-009 in a real browser. Record synthetic/redacted screenshots and a concise criterion/result matrix; local UI evidence cannot satisfy this gate.

## Rollback and failure posture

Stop further use first by clearing the server-owned operator allow-list through the authorized production configuration path if containment is necessary. Code rollback removes the UI/routes but cannot restore an account already hard-purged or sessions already revoked. Therefore release starts with a synthetic account and the production check deletes only that purpose-created account. Feature-flag state is untouched by rollback. A failed create/update/delete reports failure, refetches authoritative users, and never fabricates local success.

## Unsupported behavior and backlog

Pagination if account scale grows, fuzzy search, bulk actions, password reset, role assignment, impersonation, mobile admin, audit history, and generalized directory/query infrastructure are backlog candidates only. Runtime flag-name CRUD remains code-owned and unsupported.
