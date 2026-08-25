# Tasks: Admin Users CRUD and two-tab portal

**Feature**: `specs/013-admin-user-crud/` · **Plan**: [plan.md](plan.md) · **Design**: [design.md](design.md)

Rules: strict observable RED before GREEN; backend contract precedes clients; every product test has `013-FR-nnn` plus Allure epic/feature/story/title/named step; implementation and release are ASK; no production password/email/body is printed or attached.

## Lane A — account contract and safe creation

- [ ] **T-001 RED — safe schemas and create/list service.** In `backend/tests/test_admin_service.py`, prove all-account stable `(email,id)` ordering, safe four-field projections, no-invite/no-session creation, existing password policy/hash verification, generic taken/reserved conflict, and password/email/display sentinels absent from admin logs. (FR-003…FR-006, FR-013)
- [ ] **T-002 GREEN — creation path.** Add schemas in `backend/app/schemas/admin.py`; add the narrow reusable creation operation in `backend/app/services/auth_service.py`; add list/create in `backend/app/services/admin_service.py`. No plaintext field survives the call. (FR-003…FR-006)
- [ ] **T-003 RED→GREEN — coherent update.** Test and implement normalized unique email + nullable display name, exact id, preservation of password hash/timestamps/deletion marker, configured-operator email immutability, generic conflicts and concurrent/failure coherence. Add a narrow `UserRepository` combined mutation only if tests prove existing methods cannot keep index/record coherent. (FR-007, FR-008, FR-011, FR-013)

## Lane B — destructive delegation and routes

- [ ] **T-004 RED — deletion policy/delegation.** Service tests prove 403 self-delete, 403 every configured-operator delete, 404 unsafe/unknown id before purge, pending-account immediate purge, degraded-store false-success prevention, and exactly one call to `AccountService.purge_account` for an eligible target. (FR-009…FR-011, FR-013)
- [ ] **T-005 GREEN — delete through existing purge.** Inject `AuthService`/`AccountService` into `AdminService`, safely reorder `backend/app/container.py`, and implement delete without copying erasure steps. (FR-009, FR-011)
- [ ] **T-006 RED — route matrix.** In `backend/tests/test_admin_api.py`, add 401/403 poison-before-touch tests for all four routes; strict payload/response/status tests; stable list; create/login; update/reload; delete/full purge; conflict/404/403/correlation and content-free audit assertions. (FR-001, FR-003…FR-014)
- [ ] **T-007 GREEN — API routes.** Add GET/POST/PUT/DELETE contracts in `backend/app/api/admin.py`, all directly behind `require_operator`; preserve lookup/revoke/feature-flag routes unchanged. Make T-006 pass. (FR-001, FR-014, FR-016)
- [ ] **T-008 backend regression gate.** Run targeted admin/account tests, the complete 009/010 admin suites, backend lint/type/test/Allure validation and purge privacy tests. Record RED and GREEN commands without secrets. (SC-001…SC-006, SC-008)

## Lane C — two-tab web portal

- [ ] **T-009 RED — typed client/cache.** Test owner-scoped users keys, list/create/update/delete calls, mutation invalidation/refetch, logout/account-switch purge and no password retained in Query cache. (FR-003…FR-010, FR-013)
- [ ] **T-010 GREEN — client/hooks.** Extend `frontend/src/api/adminTypes.ts`, `client.ts`, and `adminHooks.ts`; use server-confirmed updates and broad-enough users invalidation, never optimistic identity/delete success. (FR-003…FR-010)
- [ ] **T-011 RED — tabs and Users states.** Add Vitest tests for U-01…U-12: Users default, native tab keyboard semantics, stable rows, exact zero-account and list-error/retry/recovery states (including correlation copy and last-confirmed-list preservation), create/edit/revoke/delete flows, 390px-safe structure, focus restoration, status/errors, UI suppression of self/operator delete and unchanged feature-flag behavior. (FR-002…FR-014, FR-015, SC-007)
- [ ] **T-012 GREEN — page and section.** Add `AdminUsersSection.tsx`; refactor `AdminPage.tsx` to the two tabs; move the existing `AdminFeatureFlagsSection` under its panel without changing it. Preserve direct-route and access states. (FR-002, FR-015)
- [ ] **T-013 frontend regression gate.** Run targeted admin tests, all frontend tests, lint/type/build and Allure validation; compare existing feature-flag contract assertions before/after. (SC-007, SC-008)

## Lane D — full-stack evidence, review and release

- [ ] **T-014 RED→GREEN Playwright journey.** Add `frontend/tests/admin-users.spec.ts`: purpose-seeded `@example.com` operator/member data; Users default/list; create; target login; edit/reload; revoke invalidates all sessions; explicit delete confirmation; owned-data/list absence; Feature flags tab. Attach no credential or real data. (SC-001, SC-003…SC-009)
- [ ] **T-015 exact-candidate verification.** Run `python3 scripts/check_spec_kit_specs.py`, `make check-specs`, affected full verification and required CI-equivalent checks. Commit one focused candidate. Independent reviewer and QA inspect the same exact SHA; any change invalidates evidence. (FR-017, SC-008)
- [ ] **T-016 ASK approval and landing — owner: Max.** Record explicit approval for the exact green SHA and use ADR-0008's audited ASK landing path. No agent self-approves, pushes, mutates rulesets or deploys. (SC-009)
- [ ] **T-017 production browser acceptance — owner: Max/operator.** After release proof shows production at the exact approved SHA, execute SC-009 with a unique synthetic `@example.com` account and secret password not captured in evidence. Record deployed SHA, criterion/results and redacted/synthetic screenshots; verify deleted target login fails and Feature flags still renders. This is the Definition of Done; local evidence cannot check this task. (SC-009)

## Explicitly unsupported

No task exists for password reset, roles, impersonation, bulk actions, pagination, fuzzy search, mobile admin, audit UI/store, feature-flag name CRUD, new flag service/store, global navigation or deployment redesign.
