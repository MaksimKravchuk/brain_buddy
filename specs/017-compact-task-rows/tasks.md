# Tasks — Compact Task Rows

**Input**: Founder-accepted planning artifacts in this directory. Every product test
must use the repository Allure helper, a human-readable title and step, and the named
`017-FR-###` / `017-SC-###` marker.

**Delivery boundary**: Work stays in this isolated worktree. All RED tasks precede the
implementation they specify. Shared `TaskListPage.tsx` work is deliberately serial.
Landing is ASK and is not authorized by implementation approval.

## Phase 1 — Planning and test foundation

- [x] T001 Preserve both true automated campaign verdicts and the owner's bounded founder acceptance in `review.md` and `planning-review-closure.json`; record ASK landing separately from implementation authority.
- [x] T002 Complete requirement-quality checks in `checklists/requirements.md` and `checklists/ux.md` after resolving canonical routing, offline review, focus, privacy, accessibility, and rollback findings.
- [x] T003 Add the test-only `@axe-core/playwright` dependency to `frontend/package.json` and `frontend/package-lock.json`; prove `frontend/tests/e2e/compact-task-rows.spec.ts` is discovered by the existing Chromium project (017-SC-004).

## Phase 2 — User Story 1: scan a dense list (P1)

**Independent test**: Ten representative Tasks render as exact 44 px one-line
hairline rows with Tags, no Project/List/Delete, stable title/control geometry, and no
horizontal overflow at 1440, 768, or 390 px.

- [x] T004 [US1] Add RED component assertions to `frontend/src/features/tasks/__tests__/TaskListPage.test.tsx` for permitted content, compact Waiting-for metadata, one-line header structure, no Project/List/Delete, terminal styling, and batch-summary cache/no-cache behavior (017-FR-001, 017-FR-002, 017-FR-003, 017-FR-016, 017-SC-001, 017-SC-002).
- [x] T005 [US1] Add RED browser geometry/overflow/screenshots and serious/critical Axe assertions to `frontend/tests/e2e/compact-task-rows.spec.ts` at 1440×900, 768×900, and 390×851, using only synthetic data (017-FR-001, 017-FR-002, 017-FR-003, 017-FR-016, 017-SC-001, 017-SC-002, 017-SC-004).
- [x] T006 [US1] After T004–T005 are observed RED, implement the 44 px header/hairline list/progressive metadata projection in `frontend/src/features/tasks/TaskListPage.tsx`; bring the US1 subset GREEN without touching backend or mobile.

## Phase 3 — User Story 2: work inline in list context (P1)

**Independent test**: Route-select a Task, edit and navigate inside detail directly
below its header, then collapse through every supported path with correct autosave,
modal isolation, canonical recovery, and deterministic focus.

- [x] T007 [US2] Add RED tests in `frontend/src/features/tasks/__tests__/TaskListPage.test.tsx` and `frontend/src/features/tasks/__tests__/TaskDetailPanel.test.tsx` for inline layout/no sheet-scrim-inert state, header-bounded activation, inert detail text selection, route-only selection, collapse-only shortcut, sibling-modal Escape, pre-unmount flush/recovery, completion-barrier re-grouping, focus fallbacks, identical 404 handling, and exact current-context→Project→state→terminal/cancelled canonical recovery with one redirect/ten-page/abort/failure bounds (017-FR-004, 017-FR-005, 017-FR-006, 017-FR-016, 017-SC-004, 017-SC-005, 017-SC-007).
- [x] T008 [US2] After T007 is observed RED, add the inline layout variant in `frontend/src/features/tasks/TaskDetailPanel.tsx` and replace Task-side-sheet composition/local panel authority in `frontend/src/features/tasks/TaskListPage.tsx`; preserve the keyed autosave controller and bring T007 GREEN.

## Phase 4 — User Story 3: quiet agent assignment and status (P2)

**Independent test**: The split control opens immutable review for the remembered or
chosen eligible connection without dispatch; confirmed hand-off replaces it with one
fixed 184 × 28 truthful assigned control and transfers focus.

- [x] T009 [US3] Add RED pure/lifecycle/policy tests in `frontend/src/features/tasks/__tests__/taskAgentPreference.test.ts`, `frontend/src/__tests__/queryClient.test.ts`, `frontend/src/pages/__tests__/PrivacyPolicyPage.test.tsx`, and `frontend/src/features/agents/__tests__/agentCopy.test.ts` for `{connectionId, confirmedAt}`, owner/API isolation, confirmed-only updates, 30-day cross-identity startup/focus sweep, logout/401/deletion/A→B cleanup, malformed/ineligible/unavailable storage, full disclosure, all fifteen short states, and `Reported` never `Done` (017-FR-008, 017-FR-010, 017-FR-012, 017-FR-013, 017-FR-017, 017-SC-003, 017-SC-008).
- [x] T010 [US3] Add RED component/integration tests in `frontend/src/features/tasks/__tests__/TaskAgentControl.test.tsx`, `frontend/src/features/tasks/__tests__/TaskListPage.test.tsx`, and `frontend/src/features/tasks/__tests__/TaskDetailPanel.test.tsx` for split semantics, duplicate-name synthetic hostnames, chooser focus/Escape, offline-readable review with disabled confirmation/nothing queued, both seeded entry paths, zero confirm before review, focus transfer after dispatch, fixed aligned assigned geometry/no arrow, inline-run opening, rollout OFF, and cached-summary failure (017-FR-007, 017-FR-009, 017-FR-010, 017-FR-011, 017-FR-012, 017-FR-013, 017-FR-014, 017-FR-015, 017-FR-016, 017-SC-003, 017-SC-004, 017-SC-006, 017-SC-007).
- [x] T011 [US3] After T009 is observed RED, implement `frontend/src/features/tasks/taskAgentPreference.ts`, bind its auth/startup/focus lifecycle from `frontend/src/queryClient.ts`, update confirmed dispatch in the row and existing detail path, and synchronize `frontend/src/pages/PrivacyPolicyPage.tsx` with `docs/data-retention.md`; bring T009 GREEN.
- [x] T012 [US3] After T010 is observed RED, implement `frontend/src/features/tasks/TaskAgentControl.tsx`, the pure visible-state projection in `frontend/src/features/agents/agentCopy.ts`, and serial Task-list/detail integration in `frontend/src/features/tasks/TaskListPage.tsx` and `frontend/src/features/tasks/TaskDetailPanel.tsx`; bring T010 GREEN.

## Phase 5 — Regression, acceptance, and delivery boundary

- [x] T013 Replace only intentionally superseded expectations in `frontend/src/features/tasks/__tests__/TaskListPage.test.tsx` and `frontend/tests/claude-design-shell.spec.ts`: Task sheet/modal/inert state, 402×874 slide-over, two-way local shortcut, and sentence-length desktop compact disclosure; leave native iOS expectations unchanged (017-SC-007).
- [x] T014 Run all targeted suites, `python3 scripts/check_requirement_coverage.py specs/017-compact-task-rows`, `make test-frontend`, the discovered Playwright file, design-skill validation, and `python3 scripts/check_spec_kit_specs.py`; correct only feature-owned failures and keep coverage floors ratcheting upward (017-FR-001–017-FR-017, 017-SC-001–017-SC-008).
- [ ] T015 Run `make verify-all`, create and validate the pre-freeze receipt against the exact candidate SHA, record the classifier's mechanical result plus the binding ASK override, and obtain independent exact-candidate implementation review and UX acceptance before any Done claim.
- [ ] T016 Only after a separate explicit ASK landing approval, use the audited ADR-0008 path; then verify exact-SHA CI/release/smoke and execute the synthetic production journey (ten rows, inline edit/collapse/focus, canonical recovery, rollout-appropriate agent control). Record screenshots and rollback/site-data limitation; otherwise leave this task open and report implementation without production Done.

## Dependencies and serial order

- T003 blocks T005 and T014.
- T004–T005 must fail before T006.
- T007 must fail after the compact header exists and before T008.
- T009–T010 must fail before T011–T012.
- T006, T008, and T012 are serial because all write `TaskListPage.tsx`.
- T013 follows all three stories; T014 follows T013; T015 follows T014; T016 is a
  separately authorized release step.
- No task is marked `[P]`: file ownership converges on the Task list and the bounded
  serial path avoids shared-writer conflicts identified by campaign 2.
