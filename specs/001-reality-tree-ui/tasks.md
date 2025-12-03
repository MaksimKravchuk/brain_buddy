---
description: "Task list for Current Reality Tree UI"
---

# Tasks: Current Reality Tree UI

**Input**: Spec `/specs/001-reality-tree-ui/spec.md` and plan `/specs/001-reality-tree-ui/plan.md`  
**Prerequisites**: research.md, data-model.md, contracts/, quickstart.md  
**Tests**: Required per constitution and NFR-001 (backend pytest, frontend Vitest; smoke for compose stack)  
**Organization**: Tasks are grouped by user story (P1–P3) to keep each slice independently testable.

## Format: `[ID] [P?] [Story] Description`

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Ensure local/compose environments and tooling are aligned with spec/plan.

 - [X] T001 Update `.env.example` with API base URLs/ports and optional `BRAIN_BUDDY_API_KEY`/`VITE_API_KEY` for local/compose.
 - [X] T002 Create/align `docker-compose.local.yml` to run FastAPI (8000, data volume) and Vite/React (8080) with env wiring.
 - [X] T003 Update `Makefile` compose targets (`compose-up`, `compose-down`, `compose-smoke`) to reference `docker-compose.local.yml`.
 - [X] T004 Align `scripts/smoke_test.sh` to compose hosts/ports and document usage comments.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Contract parity and core state scaffolding required by all stories.

 - [X] T005 Sync backend tree schemas/routes to `contracts/tree-api.md` in `backend/app/schemas/api.py` and `backend/app/api/routes.py`.
 - [X] T006 Add backend contract tests for tree list/detail/import/export in `backend/tests/api/test_trees.py`.
 - [X] T007 Update frontend API types/clients to contract in `frontend/src/api/types.ts` and `frontend/src/api/client.ts`.
 - [X] T008 Add frontend API hook tests for import/export/list in `frontend/src/api/__tests__/hooks.test.ts`.
 - [X] T009 Implement relation cycle/direction validation helper in `backend/app/utils/identifiers.py` and `backend/app/services/tree_service.py`.
 - [X] T010 Scaffold tree/UI stores for state, selection, and hotkey plumbing in `frontend/src/stores/treeStore.ts` and `frontend/src/stores/uiStore.ts`.

---

## Phase 3: User Story 1 – Build and navigate a current reality tree (Priority: P1) 🎯 MVP

**Goal**: Create nodes, link bottom-to-top "why" relations, navigate via keyboard/zoom, highlight paths.  
**Independent Test**: Create nodes of each type, link directional relations, zoom/center, observe highlighting rules without persistence or AI.

- [X] T011 [US1] Add Vitest coverage for node highlighting/selection and relation counts in `frontend/src/stores/__tests__/treeStore.test.ts`.
- [X] T012 [P] [US1] Implement keyboard shortcuts (create node, link, zoom, center) in `frontend/src/stores/uiStore.ts` and `frontend/src/components/canvas/TreeCanvas.tsx`.
- [X] T013 [P] [US1] Implement node create/edit UI with type-specific colors in `frontend/src/components/BrainNode.tsx` and `frontend/src/components/CreateNodeButton.tsx`.
- [X] T014 [US1] Render directional "why" relations with selection highlighting in `frontend/src/components/canvas/TreeCanvas.tsx`.
- [X] T015 [P] [US1] Add zoom and recenter controls keeping selection in view in `frontend/src/components/layout/CanvasShell.tsx`.
- [X] T016 [US1] Apply cause/effect-spanning highlighting rules (>=3 upstream, all undesired effects) in `frontend/src/stores/treeStore.ts` and `frontend/src/components/BrainNode.tsx`.
- [X] T017 [US1] Implement auto-save (local ~5s debounce) and exit warning + cloud sync cadence in `frontend/src/stores/treeStore.ts` and `frontend/src/components/layout/Layout.tsx`.

---

## Phase 4: User Story 2 – Persist and share trees (Priority: P2)

**Goal**: Save/reopen trees, download/import JSON with full fidelity for signed-in and signed-out users.  
**Independent Test**: Save a tree, download JSON, import into a new session, reopen after sign-in with identical structure/colors.

- [X] T018 [US2] Implement backend tree CRUD and import/export per contract in `backend/app/api/routes.py` and `backend/app/services/tree_service.py`.
- [X] T019 [P] [US2] Add backend import/export validation tests in `backend/tests/api/test_tree_import_export.py`.
- [X] T020 [US2] Wire tree management menu (new/save/open) to backend API in `frontend/src/components/topbar/TreeSelector.tsx` and `frontend/src/components/modals/CreateTreeModal.tsx`.
- [X] T021 [P] [US2] Add download/import flows with toasts and error handling in `frontend/src/api/hooks.ts` and `frontend/src/utils/error.ts`.
- [X] T022 [US2] Implement signed-in persistence (API key forwarding/owner mapping) in `frontend/src/api/client.ts` and `frontend/src/stores/treeStore.ts`.

---

## Phase 5: User Story 3 – Receive AI feedback on reasoning chains (Priority: P3)

**Goal**: Provide AI summaries/recommendations with consent prompts and reliable error handling.  
**Independent Test**: Request AI analysis on a populated tree while signed in; receive summary/recommendations within budget; failures show retry path without data loss.

- [ ] T023 [US3] Implement AI feedback endpoint `/api/trees/{id}/ai-feedback` with provider stub in `backend/app/api/routes.py` and `backend/app/services/tree_service.py`.
- [ ] T024 [P] [US3] Add backend AI feedback contract tests (success/failure/consent) in `backend/tests/api/test_tree_ai_feedback.py`.
- [ ] T025 [US3] Add AI feedback UI with confirmation, progress, retry handling in `frontend/src/components/panels/NodeInspector.tsx` and `frontend/src/stores/uiStore.ts`.
- [ ] T026 [P] [US3] Add frontend AI feedback hook/error tests in `frontend/src/api/__tests__/aiHooks.test.ts`.

---

## Phase N: Polish & Cross-Cutting

**Purpose**: Docs, performance/accessibility, and smoke validation across surfaces.

- [ ] T027 Update docs (README.md, `specs/001-reality-tree-ui/quickstart.md`) with autosave cadence, AI consent flow, compose usage.
- [ ] T028 Review accessibility and performance (200-node canvas, `useGraphProfiler`) and tune `frontend/src/components/canvas/TreeCanvas.tsx` and `frontend/src/hooks/useGraphProfiler.ts`.
- [ ] T029 Validate compose stack via `make compose-smoke-up` and `./scripts/smoke_test.sh`; apply fixes in `docker-compose.local.yml` or `scripts/smoke_test.sh`.
- [ ] T030 Run backend quality gates (Black/Ruff/mypy) per `backend/pyproject.toml` and fix findings in `backend/app/**`.
- [ ] T031 Run frontend quality gates (ESLint/Prettier/tsc/Vitest) per `frontend/package.json` scripts and fix findings in `frontend/src/**`.

---

## Dependencies & Execution Order

- Phase 1 → Phase 2 → Phase 3 (US1) → Phase 4 (US2) → Phase 5 (US3) → Phase N.  
- User story order: US1 is MVP and prerequisite for US2/US3. US2 should complete before US3 to ensure saved trees exist.

### Parallel Opportunities

- In Phase 3, T012 and T015 can proceed in parallel; T013 can parallelize once UI store scaffolding (T010) lands.  
- In Phase 4, T019 can run in parallel with T018; T021 can parallelize with T020 after contracts are stable.  
- In Phase 5, T024 can parallelize with T023; T026 can parallelize with T025.

---

## Implementation Strategy

1. Deliver MVP (US1) after Setup/Foundational to unlock end-to-end canvas interactions.  
2. Add persistence/import-export (US2) to enable sharing and fidelity checks.  
3. Layer AI feedback (US3) with consent/error handling.  
4. Close with docs, accessibility, performance, and smoke validation.
