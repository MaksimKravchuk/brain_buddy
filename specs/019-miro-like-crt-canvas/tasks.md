# Tasks: Miro-like Current Reality Tree Canvas

**Input**: [intake.md](intake.md), [spec.md](spec.md), [design.md](design.md), [plan.md](plan.md), [research.md](research.md), [data-model.md](data-model.md), [HTTP contract](contracts/http.md), [requirements checklist](checklists/requirements.md)

**Execution rule**: Every behavior task is a RED → observed failure → minimal GREEN vertical slice. Product tests carry Allure taxonomy and the applicable `019-FR-###` / `019-SC-###` IDs. Work remains in the `crt` worktree; do not commit, push, land or deploy without separate approval.

## Phase 1 — Ratification and rollout boundary

- [x] T001 Record the repo owner's bounded founder acceptance after two non-converging planning campaigns: all known findings fixed; implementation remains behind default-OFF `crt_canvas`; strict TDD, independent code review, full exact-SHA verification and ASK release controls remain mandatory. Evidence: `planning-review-acceptance.json`.
- [x] T002 [US1] Write and observe RED backend tests for the fifth runtime-managed `crt_canvas` row, default OFF, selected-user resolution, degraded-store fail-closed behavior and `/api/auth/me` projection in `backend/tests/test_feature_flags.py`, `backend/tests/test_feature_flag_repository.py`, and `backend/tests/test_feature_flag_service.py`. *(019-FR-001, 019-SC-006)*
- [x] T003 [US1] Add `crt_canvas` to the managed inventory and migration/repair behavior in `backend/app/core/config.py`, `backend/app/repositories/feature_flag.py`, and `backend/app/services/feature_flag_service.py`; make T002 GREEN. *(019-FR-001, 019-SC-006)*
- [x] T004 [US1] Write and observe RED frontend route/navigation tests in `frontend/src/app/AppRoutes.test.tsx` and shell tests proving OFF hides/disables Thinking Mode, ON links to `/crt`, and direct `/crt` renders the gated workspace rather than the historical placeholder. *(019-FR-001, 019-FR-002)*
- [x] T005 [US1] Implement the minimal `CrtGate`/route and AppShell exposure wiring in `frontend/src/features/crt/`, `frontend/src/app/AppRoutes.tsx`, and `frontend/src/components/shell/AppShell.tsx`; make T004 GREEN. *(019-FR-001, 019-FR-002)*

## Phase 2 — Stage A compatibility and safe CRT facade

- [x] T006 [US1] RED→GREEN legacy-tree fixtures for top-level `revision`/`schema_version`, monotonic writes, internal `last_command_id` exclusion and Stage A downgrade compatibility in `backend/tests/test_tree_repository.py`, `backend/tests/test_tree_service.py`, and import/export/account-export tests. *(019-FR-020, 019-FR-021)*
- [x] T007 [US1] Implement Stage A schema/repository/service compatibility in `backend/app/schemas/domain.py`, `backend/app/schemas/api.py`, `backend/app/repositories/tree.py`, and `backend/app/services/tree_service.py`. *(019-FR-020, 019-FR-021)*
- [x] T008 [US1] RED→GREEN owner-scoped `/api/crt/exposure` and read facade tests for effective, disabled, degraded, unauthenticated, wrong-owner and malformed correlation headers in `backend/tests/test_crt_api.py`. *(019-FR-001, 019-FR-002, 019-FR-020)*
- [x] T009 [US1] Implement CRT dependencies/routes in `backend/app/api/dependencies.py` and `backend/app/api/routes.py`, preserving legacy non-CRT callers. *(019-FR-001, 019-FR-002, 019-FR-020)*
- [x] T010 [US1] RED→GREEN command receipt repository/service tests for create/import/update/delete exact replay, stale-revision precedence, response loss, crash reconciliation, 30-day retention, confirmed-delete tombstones and account purge in `backend/tests/test_crt_command_repository.py` and `backend/tests/test_crt_api.py`. *(019-FR-019…021)*
- [x] T011 [US1] Implement `backend/app/repositories/crt_command.py`, `backend/app/services/crt_command_service.py`, container wiring and purge/backup support per ADR-0026. *(019-FR-019…021)*

## Phase 3 — Tree entry and management MVP

- [x] T012 [US1] RED→GREEN typed CRT API client tests for exposure, list/get/create/rename/delete/import/export, correlation, timeout, revision and idempotency in `frontend/src/api/__tests__/crt.test.ts`. *(019-FR-003, 019-FR-004, 019-FR-019…021)*
- [x] T013 [US1] Implement `frontend/src/api/crt.ts`, CRT types and React Query owner/origin-scoped keys. *(019-FR-003, 019-FR-004, 019-FR-019…021)*
- [x] T014 [US1] RED→GREEN first-run, last-tree fallback and complete tree-menu state tests in `frontend/src/features/crt/__tests__/CrtWorkspace.test.tsx`. *(019-FR-003, 019-FR-004, 019-FR-021)*
- [x] T015 [US1] Implement `CrtWorkspace`, first-run state and create/switch/rename/confirmed-delete/import/export UI in `frontend/src/features/crt/`; install and lock `@xyflow/react`. *(019-FR-003, 019-FR-004)*

## Phase 4 — Keyboard-first graph editor

- [x] T016 [US2] RED→GREEN graph-domain tests for bottom-up cause→effect invariants, Enter child, Tab sibling, manual Connector, duplicate/self/cycle rejection, cascade delete and undo/redo in `frontend/src/features/crt/__tests__/graphModel.test.ts`. *(019-FR-005…010, 019-FR-016)*
- [x] T017 [US2] Implement pure graph commands/layout in `frontend/src/features/crt/graphModel.ts` and `layout.ts`; make T016 GREEN. *(019-FR-005…010, 019-FR-016)*
- [x] T018 [US2] RED→GREEN component tests for canvas cards/arrows, semantic text badges, inline editing, drag, inspector, focus model, connected-card arrows, shortcut mode, pan/zoom/fit and native-control key isolation in `frontend/src/features/crt/__tests__/CrtCanvas.test.tsx`. *(019-FR-005…016, 019-FR-022, 019-FR-023)*
- [x] T019 [US2] Implement `CrtCanvas`, `CrtCardNode`, `CrtInspector`, tool rail, controls and accessible announcements against D-01/D-04. *(019-FR-005…016, 019-FR-022, 019-FR-023)*

## Phase 5 — Autosave, local recovery and concurrency

- [x] T020 [US3] RED→GREEN autosave state-machine tests for immutable in-flight generations, queued commands, exact-key retry, conflicts, online-only fallback and late/cancelled responses in `frontend/src/features/crt/__tests__/autosave.test.ts`. *(019-FR-017…021)*
- [x] T021 [US3] Implement autosave/reconcile controller in `frontend/src/features/crt/autosave.ts`. *(019-FR-017…021)*
- [x] T022 [US3] RED→GREEN local storage tests for owner/origin scoping, Web Locks single-writer behavior, crash-safe pre-canonical rekey, 30-day stale recovery, backup/discard and account-transition cleanup in `frontend/src/features/crt/__tests__/draftStore.test.ts`. *(019-FR-018…020)*
- [x] T023 [US3] Implement `draftStore.ts`, cross-tab coordination and D-03/D-06 recovery surfaces; update `frontend/src/pages/PrivacyPolicyPage.tsx` with tested disclosures. *(019-FR-018…021)*

## Phase 6 — Integrated acceptance and release evidence

- [x] T024 Add Playwright journeys in `frontend/tests/e2e/crt.spec.ts` for 10-card keyboard creation under two minutes, first-run/menu, save/reload, failed-save recovery/conflict, import rejection, normal OFF vs degraded flag states, unsupported width and 200-card responsiveness. Use synthetic data only. *(019-SC-001…007)*
- [x] T025 Run focused backend/frontend suites after every slice, then `make check-specs`, `make test-backend`, `make test-frontend`, `make test-e2e`, `npm run build`, `git diff --check`, and `make verify-all` on the frozen candidate.
- [ ] T026 Obtain one independent code/security review of the final exact SHA, fix findings test-first, and rerun affected/full gates.
- [ ] T027 Produce bounded visual/accessibility evidence against D-01…D-06 and D-05-UW; verify default-OFF/internal rollout and rollback. Do not commit, push, land or deploy without separate ASK approval.

## Dependencies and MVP

T001 closes planning. T002→T005 is the first vertical tracer and starts immediately. T006→T011 establish the safe persistent facade before tree mutation UI. T012→T015 deliver independently usable tree entry/management. T016→T019 deliver the keyboard canvas. T020→T023 complete no-data-loss behavior. T024→T027 are serial acceptance/release gates.
