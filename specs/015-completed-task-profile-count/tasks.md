# Tasks: Completed Task Profile Count

**Input**: [intake.md](intake.md), [spec.md](spec.md), [design.md](design.md), [plan.md](plan.md), [requirements checklist](checklists/requirements.md)

## Phase 1 — Ratification and executable baseline

- [ ] T001 Record exact owner ratification and planning-review verdict for `specs/015-completed-task-profile-count/` before product implementation.
- [ ] T002 Reproduce the missing `Completed tasks: N` line on base `040f1de82e0b122bdcbb62f92db34fcde1d53bbd` and preserve bounded evidence in the harness run.

## Phase 2 — User Story 1 backend contract (P1)

- [ ] T003 [US1] Write RED indexed count cases in `backend/tests/test_task_repository.py`, public Tasks query cases in `backend/tests/test_task_service.py`, and Account projection cases in `backend/tests/test_account_api.py` for zero, nonzero, cancelled exclusion, completed-subtask exclusion, another owner, complete +1, reopen -1, and forced count failure before profile/email mutation. Put every applicable `015-FR-001`…`015-FR-012` marker in the covering test name/docstring or Allure story; put `015-SC-001` on lifecycle evidence, `015-SC-002` on owner isolation and `015-SC-003` on exclusion evidence. *(015-FR-001…012, 015-SC-001…003)*
- [ ] T004 [US1] Add the non-negative `completed_task_count` contract to `backend/app/schemas/account.py`. *(015-FR-001, 015-FR-002)*
- [ ] T005 [US1] Add private indexed `TaskRepository.count_for_owner_by_state` and public `TaskService.completed_task_count`; compose it with `AccountService` in `backend/app/api/account.py`, obtaining the count before profile/email writes so a failed query cannot produce ambiguous mutation success. *(015-FR-002…010, 015-FR-012)*
- [ ] T006 [US1] Observe the new tests fail for the intended missing behavior, then run `backend/tests/test_task_repository.py`, `backend/tests/test_task_service.py` and `backend/tests/test_account_api.py` GREEN; record Allure evidence. *(015-SC-001…003)*

## Phase 3 — User Story 1 Web Profile (P1)

- [ ] T007 [US1] Write RED exact-copy, zero/nonzero, immediate-loading, authenticated non-401 initial-error and failed-refetch honesty cases in `frontend/src/features/account/__tests__/AccountSettingsPage.test.tsx`; verify the unchanged 401 session-clear/redirect boundary in the existing route/client tests. Put `015-SC-004` in the covering test title or Allure story. *(015-FR-001, 015-FR-007, 015-FR-009…011, 015-SC-004)*
- [ ] T008 [US1] Mirror the additive field in `frontend/src/api/accountTypes.ts` and render D-01-S01…D-01-S06 in `frontend/src/features/account/AccountSettingsPage.tsx` without a second request or client-side delta. *(015-FR-001…010)*
- [ ] T009 [US1] Prove the default stale Account query refetches when Profile is next opened; only if that focused evidence fails, invalidate `accountKeys.detail()` after successful complete/reopen in the existing task mutation boundary. Never retain cached count data on a failed refetch. *(015-FR-007, 015-FR-009, 015-FR-010)*
- [ ] T010 [US1] Run the focused Account page and `frontend/src/api/__tests__/accountHooks.test.tsx` Vitest tests; record GREEN Allure evidence. *(015-SC-001, 015-SC-004)*

## Phase 4 — Integrated evidence and review

- [ ] T011 [US1] Extend `frontend/tests/e2e/account.spec.ts` with a title or Allure story carrying `015-SC-001`, `015-SC-002`, `015-SC-004` and the mechanical `015-SC-005` link. Use synthetic D-01-S01…S07 observations at 390×851 and 1280×780: loading, zero/nonzero, complete/reopen/isolation, authenticated correlation-aware failure, refresh recovery, unchanged 401 redirect, no stale number and no horizontal overflow. Capture bounded screenshots of the changed Profile surface; do not treat the `015-SC-005` marker as evidence that `make verify-all` ran. *(015-SC-001, 015-SC-002, 015-SC-004, 015-SC-005)*
- [ ] T012 Run `make check-specs`, focused backend/frontend tests, `make test-e2e`, `git diff --check` and `make verify-all` on one final workspace/environment snapshot. *(015-SC-005)*
- [ ] T013 Run independent code review and Product Owner evaluation against the same approved spec and final snapshot; repair and rerun stale or failed evidence within bounded harness budgets.
- [ ] T014 Present the visible criterion to the owner for explicit verification and result acceptance; do not commit, push, land or deploy.
- [ ] T015 Produce `acceptance.md`, `traceability.md` and `report.md` from the immutable accepted outcome and content-grounded retro.

## Dependencies and MVP

T001–T002 gate implementation. Backend RED→GREEN T003→T006 precedes frontend contract use T007→T010. Browser evidence T011 follows both, then T012→T015 is serial. There is one user story and it is the MVP; no parallel product lane is justified for this small cross-tier contract.

## Completion rule

Unchecked tasks are deliberate planning state. Mark a task complete only from current, hash-bound evidence; completing code without final owner acceptance and report artifacts is not delivery.
