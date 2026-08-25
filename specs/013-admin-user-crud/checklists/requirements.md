# Requirements checklist: Admin Users CRUD and two-tab portal

**Feature**: `specs/013-admin-user-crud/` · **Generated**: 2026-08-23

## Requirement quality

- [x] FR-001…FR-017 and SC-001…SC-009 are unique, testable and outcome-oriented.
- [x] Every requirement traces to a user story/constraint and an implementation/evidence task.
- [x] No unresolved clarification or placeholder remains; fixed founder decisions were not re-asked.
- [x] `design.md` enumerates every loading/empty/error/form/confirm/tab state and cites the spec.
- [x] Success criteria distinguish local tests, independent exact-SHA evidence and production browser acceptance.

## Scope and supersession

- [x] Feature 009 history is untouched; this package explicitly supersedes only its list/create/edit/delete out-of-scope boundary.
- [x] Existing 009 direct-route, authorization, exact lookup, revoke, privacy and logging behavior remains supported.
- [x] ADR-0021 explicitly expands ADR-0017 instead of silently contradicting its two-operation cap.
- [x] Feature 010/ADR-0019 behavior and SQLite storage are unchanged; flag-name CRUD remains out of scope.
- [x] Password reset, roles, impersonation, bulk actions, pagination, fuzzy search, mobile admin, audit UI/store and generalized directory infrastructure remain out of scope.

## Security, privacy and deletion

- [x] Every API route requires `require_operator`; UI hiding is explicitly non-authoritative.
- [x] Safe account projection, stable ordering and exact API shapes are explicit.
- [x] Initial password uses only existing validation/hash code and is excluded from persistence, responses, logs, caches, screenshots and evidence.
- [x] Configured-operator email mutation, self-delete and every operator delete are refused server-side.
- [x] Hard delete delegates to marker-first, fail-closed `AccountService.purge_account`; no second erasure inventory is invented.
- [x] Pending-deletion behavior is explicit for list/update/revoke/admin-delete and unchanged self-service paths.
- [x] Content-free audit fields and deliberately absent PII/secret/body fields are explicit for success and failure outcomes.

## Delivery readiness

- [x] Concrete backend/frontend/test/docs paths are named in `plan.md` and `tasks.md`.
- [x] RED→GREEN, Allure taxonomy, regression, build, privacy-sentinel and full-stack evidence are mapped.
- [x] Implementation/release is classified ASK with separate approval, exact-SHA CI, landing and deploy authority.
- [x] Production browser verification on the deployed exact SHA is the final unchecked delivery task, not falsely claimed by planning/local tests.
- [x] Rollback limitations state that hard purge/session revoke cannot be undone and production acceptance deletes only a purpose-created synthetic account.
