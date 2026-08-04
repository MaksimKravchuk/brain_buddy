# Tasks: Escape closes the Task menu first

**Input**: `specs/006-escape-task-menu/spec.md` and `plan.md`
**Tests**: Required; one vertical RED → GREEN behavior slice.
**Execution**: Planning input only. Hermes Kanban owns implementation and independent review.

## Phase 1: User Story 1 — nearest-layer Escape behavior (P1)

**Goal**: Escape closes an open Task menu without closing Task detail, restores trigger focus, then retains existing detail-close behavior when the menu is closed.

**Independent Test**: A route-level Testing Library test opens a selected task and its menu, verifies the first Escape dismisses only the menu and restores focus, then verifies a second Escape closes detail.

- [ ] **T001 [US1] RED** — In the established Task route test module, or `frontend/src/features/tasks/__tests__/TaskListPage.test.tsx` if none exists, add one targeted behavioral test with required Allure taxonomy. Verify first-Escape menu dismissal, same route/heading preservation, no mutation, trigger focus restoration, and second-Escape fallback. Run only that test and record the expected failure caused by current parent navigation.
- [ ] **T002 [US1] GREEN** — In `frontend/src/features/tasks/TaskDetailPanel.tsx`, add the minimum menu-owned Escape handling and stable trigger focus restoration needed to pass T001. Prevent the handled keydown from reaching the document-level detail-close behavior. Do not alter menu actions or Task lifecycle behavior.
- [ ] **T003 [US1] VERIFY** — Re-run the targeted test, then the containing frontend test file. Confirm required Allure taxonomy is emitted and no warning/error output is introduced.
- [ ] **T004 [US1] SCOPE** — Review the diff to confirm no backend, API, persistence, route-contract, configuration, CI, security, or unrelated UI changes.

## Dependency Order

`T001 → T002 → T003 → T004`. This is one compact implementation lane; splitting it would create overlapping ownership without independent value.

## Guardrails

- Do not edit production code before T001 fails for the expected route-closing reason.
- Do not change the existing menu-closed focused-field/modal exclusions in `TaskListPage.tsx`.
- Do not add a global keyboard manager, dependency, state store, route, or backend contract.
- Do not treat this planning file as permission to implement outside an assigned isolated Hermes Kanban card.
