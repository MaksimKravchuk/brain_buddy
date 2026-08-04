# Tasks: Escape closes the Task menu first

**Input**: `specs/006-escape-task-menu/spec.md` and `plan.md`
**Tests**: Required; one baseline characterization guard followed by one vertical RED → GREEN behavior slice.
**Execution**: Planning input only. Hermes Kanban owns implementation and independent review.

## Phase 1: User Story 1 — nearest-layer Escape behavior (P1)

**Goal**: Escape closes an open Task menu without closing Task detail, restores trigger focus, then retains existing detail-close behavior when the menu is closed.

**Independent Test**: A route-level Testing Library test opens a selected task and its menu, verifies the first Escape dismisses only the menu and restores focus, then verifies a second Escape closes detail.

- [ ] **T001 [US1] CHARACTERIZE** — In `frontend/src/app/AppRoutes.test.tsx`, extend the existing `keeps terminal recovery explicit in task detail` test to assert `Task menu` is absent for its terminal fixture. Run that test before production edits and record the baseline pass.
- [ ] **T002 [US1] RED** — In the established route fixture `frontend/src/app/AppRoutes.test.tsx`, add one targeted behavioral test with required Allure taxonomy. After setup requests settle, checkpoint the mocked-fetch call count. Verify a non-Escape key keeps the menu open without a request; first Escape dismisses only the menu, preserves route/heading, adds no request of any method, and restores trigger focus; focused-Title Escape preserves detail; and a later eligible Escape closes detail. Run only that test and record the expected failure caused by current parent navigation.
- [ ] **T003 [US1] GREEN** — In `frontend/src/features/tasks/TaskDetailPanel.tsx`, add the minimum menu-owned Escape handling and stable trigger focus restoration needed to pass T002. Prevent the handled keydown from reaching the document-level detail-close behavior. Do not alter menu actions or Task lifecycle behavior.
- [ ] **T004 [US1] VERIFY/SCOPE** — Re-run the targeted test, the terminal characterization, the existing `BrainDumpOverlay.test.tsx` modal Escape-owner test, and the containing route test file. Confirm required Allure taxonomy is emitted, no warning/error output is introduced, `TaskListPage.tsx` remains unchanged, and no backend, API, persistence, route-contract, configuration, CI, security, or unrelated UI change exists.

## Dependency Order

`T001 → T002 → T003 → T004`. This is one compact implementation lane; splitting it would create overlapping ownership without independent value.

## Guardrails

- Do not edit production code before T001 passes as a baseline characterization and T002 fails for the expected route-closing reason.
- Do not change the existing menu-closed focused-field/modal exclusions in `TaskListPage.tsx`.
- Do not add a global keyboard manager, dependency, state store, route, or backend contract.
- Do not treat this planning file as permission to implement outside an assigned isolated Hermes Kanban card.
