# Cross-artifact analysis: Admin Users CRUD and two-tab portal

**Feature**: `specs/013-admin-user-crud/` · **Date**: 2026-08-23
**Scope**: planning only; no product code, tests, runtime or production state changed.

## Mechanical trace

| Contract | Design | Tasks | Evidence |
|---|---|---|---|
| FR-001 authorization | U-01 | T-006/T-007 | SC-002 |
| FR-002 tabs/direct web | U-01/U-12 | T-011/T-012 | SC-007 |
| FR-003/004 list/projection | U-02…U-05 | T-001/T-002/T-006/T-011 | SC-001 |
| FR-005/006 create/password | U-06/U-07 | T-001/T-002/T-006/T-014 | SC-003 |
| FR-007/008 update/operator email | U-08 | T-003/T-006/T-011/T-014 | SC-004 |
| FR-009…011 hard delete/pending | U-10/U-11 | T-004…T-007/T-011/T-014 | SC-005 |
| FR-012 revoke | U-09 | T-006/T-011/T-014 | SC-006 |
| FR-013/014 audit/errors | all mutation/error states | T-001/T-003/T-004/T-006 | SC-002…SC-006 |
| FR-015 flags unchanged | U-12 | T-011…T-013 | SC-008 |
| FR-016 lookup compatibility | no new affordance | T-007/T-008 | SC-008 |
| FR-017 taxonomy | all tested states | T-001…T-015 | validation gates |
| SC-009 production DoD | production evidence section | T-016/T-017 | deployed exact SHA only |

Counts: 17 FR definitions and 9 SC definitions, unique and contiguous. Every FR and SC has a forward task. All implementation tasks remain unchecked.

## ADR and historical consistency

- Feature 009 remains unchanged. Its out-of-scope list is superseded prospectively by feature 013 only for all-account listing and account create/update/delete.
- ADR-0017 explicitly authorized only account-record lookup and session revoke. ADR-0021 is therefore required and narrowly adds account-record list/create/update plus purge orchestration while preserving the member-content prohibition.
- ADR-0019 already removed the `admin_portal` flag and requires direct `require_operator`; this package does not reintroduce a flag.
- ADR-0008 classifies auth/privacy and destructive erasure as ASK. Planning docs alone do not satisfy approval, CI, landing, deploy or production acceptance.

## Source-grounded boundaries

- `UserRepository.list_users`, `create`, `update_email`, `mutate`, and `delete` are the existing account persistence primitives.
- `AuthService.validate_password_format`/`hash_password` are the existing password path; signup's invite/session side effects are intentionally not reused.
- `AccountService.purge_account` already owns marker-before-scrub, sessions, voice, relay, tasks, trees, invites and user-last deletion; admin delete delegates to it.
- `AdminService` already owns operator checks, exact lookup, session revoke and content-free records.
- `AdminPage`, `adminHooks`, `adminTypes` and `AdminFeatureFlagsSection` are the existing frontend vertical; no new framework is needed.

## Residual risks and mitigations

1. **Irreversible wrong-target delete** — exact id resolution, server self/operator refusal, explicit confirmation, synthetic production acceptance, ASK approval.
2. **Password leakage** — one-way existing hash path; sentinels across response/log/cache/evidence; password never printed.
3. **Email index/user record drift during combined update** — T-003 failure/concurrency tests require one coherent repository-lock boundary if existing calls are insufficient.
4. **Purge blocked by degraded flag store** — preserve fail-closed retry and never remove the UI row/claim success until the server confirms.
5. **Existing flag regression from page refactor** — component remains unchanged; 010 suites and tab-mount regression are mandatory.
6. **Unbounded list growth** — accepted at current scale; pagination is backlog and requires a future spec when needed.

## Readiness

The package is implementation-ready for the bounded child task after this planning commit. It is not delivery-complete: independent review/QA, explicit ASK approval, exact-SHA CI/landing/deploy, and production browser T-017 remain separate evidence gates.
