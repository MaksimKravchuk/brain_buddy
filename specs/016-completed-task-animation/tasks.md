# Tasks — completed task animation

## Foundation

- [x] T001 Close planning review by bounded founder acceptance following the owner's 2026-09-08 instruction to continue until the feature is ready; preserve original campaign verdicts in `planning-review-closure.json`. The owner's no-flag decision is recorded in ADR-0022.
- [x] T002 Validate the compatibility repair in `frontend/package.json` and `frontend/package-lock.json`, audit comparison, unchanged Node20 baseline, Docker build and independent repair review (016-SC-004 prerequisite).

## US1 — visible completion (all RED tasks precede implementation)

- [x] T003 [US1] Add RED partition/filter/counter/account-isolation tests in `frontend/src/features/tasks/__tests__/TaskListPage.test.tsx` and `frontend/src/api/__tests__/taskHooks.test.ts`, including the same task's completion/reopen across overlapping project/tag/search views, exclusion from nonmatching results, disabled pending control and exactly one request on repeated activation (016-FR-001, 016-FR-003, 016-SC-001, 016-SC-003).
- [x] T004 [US1] Add RED motion/overlap/reduced-motion/focus tests in `frontend/src/features/tasks/__tests__/useTaskCompletionAnimation.test.ts` (016-FR-002, 016-FR-003, 016-SC-002).
- [x] T005 [US1] Add RED real-stack timing, transformed-control hit test, failure, filtered reload, keyboard and mobile/desktop evidence in `frontend/tests/e2e/completed-tasks.spec.ts`; update only superseded completion and toolbar expectations in `frontend/tests/native-tasks-voice-brain-dump.compose.spec.ts` and `frontend/tests/claude-design-shell.spec.ts` (016-FR-001, 016-FR-002, 016-FR-003, 016-SC-001, 016-SC-002, 016-SC-003, 016-SC-004).
- [x] T006 [US1] After RED evidence, implement partition, scoped cache, open counts and pending/focus behavior in `frontend/src/features/tasks/TaskListPage.tsx` and `frontend/src/api/taskHooks.ts`, preserve pending detail completion in `frontend/src/features/tasks/TaskDetailPanel.tsx`, plus movement in `frontend/src/features/tasks/useTaskCompletionAnimation.ts`; bring T003-T005 GREEN.

## Verification and release

- [ ] T007 Run feature requirement-coverage validation and `make verify-all`, freeze one candidate, obtain independent exact-SHA review/QA and record writer receipt/path classification. All seven feature-qualified FR/SC markers must map to meaningful tests.
- [ ] T008 Submit verified trunk, wait for exact-SHA CI and production release, observe the synthetic journey and guardrail, restore its original open state and record bounded acceptance evidence. Do not mark complete before actual release and restoration.

## RED evidence (2026-09-08)

T003/T004 produced 16 expected assertion failures before runtime implementation (partition, scope, pending, motion and focus); the no-replay case already passed. A separate detail-completion assertion also failed at the missing pending disabled state. T005 failed against the baseline real Compose stack at the enabled completion button while its request was held; API setup and smoke passed. Evidence is retained outside the candidate in `work/feature-implementation-unit-red.log`, `work/feature-implementation-detail-red.log` and `work/linux-e2e-completion-red/`. These failures establish RED, not acceptance or release readiness.

## Implementation evidence (2026-09-08)

T006 is implemented. The initial full frontend run passed 1,008 tests with all current coverage floors, lint, typecheck and production build. Four real-stack browser cases passed: 380ms movement at 1240px and 390px, pending protection, failure/retry, reduced motion and shared project/tag/search completion/reopening. Visual review then corrected the pre-existing red Saved notice to a subdued accessible status; its targeted RED/GREEN check and 83 TaskListPage tests pass. The final candidate still requires T007/T008; earlier runs are not presented as exact-SHA release evidence.

The full suite also exposed an ordinary agent-run fixture whose fixed expiration elapsed on 2026-09-08. Only that helper now uses a relative future expiration; deliberate expiry tests and production retention behavior are unchanged.
