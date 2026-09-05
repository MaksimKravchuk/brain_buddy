# Implementation Plan: Completed Task Profile Count

**Branch**: `015-completed-task-profile-count` | **Date**: 2026-09-05 | **Spec**: [spec.md](spec.md) | **Design**: [design.md](design.md)

**Base audited**: `040f1de82e0b122bdcbb62f92db34fcde1d53bbd`

## Summary

Extend the existing authenticated Account projection with one server-derived `completed_task_count` field and render it as `Completed tasks: N` in design states D-01-S01…D-01-S07. The Tasks module owns the indexed owner-scoped count and exposes it through `TaskService`; it is never stored separately. Add targeted backend, frontend and Playwright evidence before implementation, then run the repository's full verification gate.

## Technical Context

**Language/Version**: Python 3.11; TypeScript with React

**Primary Dependencies**: FastAPI/Pydantic; React, TanStack Query, Vite

**Storage**: existing SQLite-backed native Task repository; no schema or new record

**Testing**: pytest/FastAPI TestClient, Vitest/Testing Library, Playwright, Allure Report 3 taxonomy

**Target Platform**: authenticated responsive Web Profile

**Project Type**: modular-monolith web application

**Performance Goals**: one indexed owner-and-state `COUNT(*)` query per Account projection; no task payload materialization, additional client request or external call

**Constraints**: owner isolation, current-state semantics, no persisted aggregate, no mobile/release work, exact copy

**Scale/Scope**: one response field and one Profile-card line; existing account/task data sizes

## Constitution Check

- **Spec workflow**: `intake.md`, clarified `spec.md` and this design-citing plan are current. Exact owner ratification and review-gate evidence precede implementation.
- **Consent & Safety**: no provider, egress or new persistence. The account request is already authenticated; only the caller's task records may be read. No user data enters fixtures or logs.
- **Tests**: focused backend and frontend tests are written RED first, then Playwright covers D-01 loading/error/recovery plus zero/nonzero/complete/reopen and cross-owner isolation with synthetic users.
- **Contracts**: additive `completed_task_count: int >= 0` on `AccountResponse`; frontend type changes in the same candidate. Existing requests and mutation inputs are unchanged. Account routes compose the public Account and Tasks services; no foreign repository access is added.
- **Observability**: the existing account route/correlation-id/error boundary remains authoritative; the derived scalar adds no log or metric content.
- **Mobile/resilience/performance**: mobile is untouched. Responsive layouts are checked at 390×851 and 1280×780. No local delta cache is introduced; the next account read is authoritative.
- **Delivery boundary**: the work stays in the isolated worktree. Spec tasks do not authorize commit, push, landing or deployment.
- **Design citation**: backend/client/UI sections below implement `design.md` D-01-S01…D-01-S07.

No constitution violation or new ADR is required.

## Architecture and Contract

1. Tasks owns the query. Add `TaskService.completed_task_count(owner_id=...)`, backed by `TaskRepository.count_for_owner_by_state(owner_id=..., state="completed")`; no flat Account service may reach into or filter Tasks records for this feature.
2. Implement the repository operation as `COUNT(*)` over the existing indexed `(owner_id, state, ...)` columns. The query touches only native top-level task rows; subtasks live in a distinct table and are never read. Do not materialize payloads or infer completion from timestamps.
3. `GET /api/account` and account mutation responses use the same `AccountResponse`. The account route composes `AccountService` with the public `TaskService`, injected through existing dependencies, and passes an explicit count into the canonical response builder.
4. For profile and email mutations, obtain the Tasks count before calling the account mutation. A task-store failure therefore fails without changing account data; tests must prove this. The returned scalar is the point-in-time value from that pre-mutation query. A later concurrent task transition becomes visible on the next authoritative `GET /api/account`.
5. Add the field to the strict frontend `AccountResponse` type and render it as plain text in the existing `ProfileSection` using the existing account query. Avoid a second request or new state store.
6. Render an immediate polite `Completed tasks: …` status while the account query is pending. On an authenticated non-401 initial/refetch failure, hide cached count data and expose an alert with `Completed tasks unavailable. Refresh the page to try again.` plus `(ref: <correlation-id>)` when present, using `getErrorContext` only to normalize that optional reference. Leave the existing profile form available; a page refresh is the recovery path, so no new control is added. Preserve the existing global 401 session-clear and `/login` redirect. Do not accumulate client-side increments. Verify whether the default stale Account query already refetches on return to Profile; add mutation invalidation only if focused evidence proves it can retain a stale count.

The API addition is backward-compatible for current in-repository clients. There is no request, persistence, migration, feature flag or rollback data transformation.

## Project Structure

```text
backend/
├── app/schemas/account.py                 # additive response field
├── app/api/account.py                     # compose AccountService + public TaskService
├── app/modules/tasks/service.py            # public completed-count query
├── app/modules/tasks/repository.py         # private indexed owner/state count
├── tests/test_task_repository.py           # repository isolation/count contract
├── tests/test_task_service.py              # public Tasks query contract
└── tests/test_account_api.py               # projection + pre-mutation failure semantics

frontend/
├── src/api/accountTypes.ts                # mirror additive contract
├── src/api/__tests__/accountHooks.test.tsx # typed account-query fixture
├── src/features/account/AccountSettingsPage.tsx
├── src/features/account/__tests__/AccountSettingsPage.test.tsx
└── tests/e2e/account.spec.ts               # synthetic visible journey

specs/015-completed-task-profile-count/    # ratified product contract
```

No task schema, repository schema, mobile, provider, voice, CRT, deployment or CI file is planned.

## Test Strategy

1. Backend RED: add the indexed repository count contract in `backend/tests/test_task_repository.py`, the public query contract in `backend/tests/test_task_service.py`, then extend `backend/tests/test_account_api.py` with zero, exact nonzero, cancelled exclusion, completed subtask exclusion, cross-owner exclusion, complete +1, reopen -1, and forced task-count failure before profile/email mutation. Use the central Allure helper and `015-FR-001…012` qualifiers.
2. Backend GREEN: implement the smallest Tasks-owned query and additive account projection, then rerun the focused files.
3. Frontend RED: extend `frontend/src/features/account/__tests__/AccountSettingsPage.test.tsx` for exact zero/nonzero copy, the immediate loading placeholder, authenticated non-401 initial/refetch failure honesty, and preservation after profile mutation. Cover the unchanged 401 redirect boundary at the existing route/client level.
4. Frontend GREEN: update the strict type and Profile card only; rerun the focused Vitest file.
5. Browser: extend `frontend/tests/e2e/account.spec.ts` with synthetic task setup and D-01-S01…S07 at 390×851 and 1280×780, including a correlation-aware authenticated failed account read, refresh recovery, unchanged 401 redirect, no stale number and no horizontal overflow. Capture bounded screenshots of the changed Profile surface. No real account content enters evidence.
6. Contract/regression: run account API/client tests, `make check-specs`, `make verify-backend`, `make verify-frontend`, `make test-e2e`, `git diff --check`, then `make verify-all` on the final snapshot.
7. Independent code review and Product Owner evaluation must bind to the same final snapshot. Any code or approved environment change invalidates affected evidence and requires a same-attempt rerun.

### Mechanical SC traceability

The qualified marker appears in the named test's title, docstring or Allure story; task-list references alone do not count as evidence.

| marker | executable link | substantive evidence |
|---|---|---|
| `015-SC-001` | Account API lifecycle test and Playwright Profile counter journey | zero, exact nonzero, complete +1 and reopen -1 |
| `015-SC-002` | Account API owner-isolation test and Playwright second-user observation | only the signed-in owner's completed rows contribute |
| `015-SC-003` | Account API exclusion test | cancelled top-level tasks and completed subtasks contribute zero |
| `015-SC-004` | Account page Vitest state test and Playwright responsive journey | the line is readable in place; loading, failure and recovery are distinguishable |
| `015-SC-005` | Playwright Profile counter journey carries the mechanical link | separate hash-bound command evidence in `acceptance.md` proves `make verify-all`; the marker itself is not presented as proof that the aggregate command ran |

## Rollback and Delivery

Before release, rollback is simply discarding the isolated worktree. If separately released later, code rollback removes the additive projection and line; there is no stored aggregate to migrate or reconcile. This acceptance run does not commit, push, land, toggle production configuration or deploy.

## Complexity Tracking

No justified complexity exception. Composing the existing Account service with the public Tasks service is the smallest coherent implementation that preserves module ownership.
