# Tasks: Flexible Relation Linking

**Input**: Design documents from `/specs/001-relation-linking-refactor/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Tests are required for behavior changes (backend pytest/FastAPI TestClient and frontend Vitest/Testing Library).

**Organization**: Tasks are grouped by user story to enable independent implementation and testing. Include observability (correlation IDs), accessibility for inline errors, and responsiveness/data-safety safeguards.

## Format: `[ID] [P?] [Story] Description`

---

## Phase 1: Setup (Shared Infrastructure)

- [X] T001 Verify environment and sample tree fixtures for relation scenarios in repo root (`.env.example` → `.env` if needed)
- [X] T002 Align relation contract and data model references with `contracts/relations.md` and `data-model.md` (document any gaps)

---

## Phase 2: Foundational (Blocking Prerequisites)

- [X] T003 Update relation schema aliases and error payload fields (source_node_id/target_node_id, reference id) in `backend/app/schemas/api.py`
- [X] T004 Harden relation validation utilities for self/duplicate/cycle checks in `backend/app/services/relation_service.py`
- [X] T005 Ensure error handler emits human-readable detail with correlation/reference header/body fields in `backend/app/api/errors.py`
- [X] T006 Align frontend relation typings and API client payload mapping with source_node_id/target_node_id in `frontend/src/api/types.ts`
- [X] T007 Update store mapping for relation load/save, including fallback to legacy keys, in `frontend/src/stores/treeStore.ts`

---

## Phase 3: User Story 1 - Link nodes across chains (Priority: P1) 🎯 MVP

**Goal**: Create directed relations between any two nodes without parent/child terminology; direction must remain exactly as chosen.

**Independent Test**: In a tree with two chains, link Node2 → Node5; move nodes around and verify the arrow direction stays unchanged and selectable.

### Tests for User Story 1

- [X] T008 [P] [US1] Add backend test verifying create relation returns chosen source/target and stores direction in `backend/tests/test_api_trees.py`
- [X] T009 [P] [US1] Add frontend test ensuring relation orientation persists after node drag in `frontend/src/stores/__tests__/treeStore.test.ts` (or new canvas-focused test)
- [X] T010 [P] [US1] Validate canvas interactions remain responsive (<0.2s highlight/selection) on ~200-node mocked graph in `frontend/src/components/canvas/__tests__/TreeCanvas.perf.test.tsx`

### Implementation for User Story 1

- [X] T011 [US1] Keep relation rendering and creation source→target stable regardless of canvas position in `frontend/src/components/canvas/TreeCanvas.tsx`
- [X] T012 [US1] Ensure neutral upstream/downstream labels (no parent/child) on node handles and controls in `frontend/src/components/canvas/BrainNode.tsx`
- [X] T013 [P] [US1] Confirm relation creation uses explicit source/target ids and updates store consistently in `frontend/src/stores/treeStore.ts`

**Checkpoint**: User Story 1 independently delivers cross-branch linking with stable direction.

---

## Phase 4: User Story 2 - Preserve new relations (Priority: P2)

**Goal**: Cross-branch relations survive save/reload and export/import with direction intact.

**Independent Test**: Create a relation, save/reload, export/import; verify the relation and its source/target orientation remain identical.

### Tests for User Story 2

- [X] T014 [P] [US2] Add backend import/export test covering relation ids and direction in `backend/tests/api/test_tree_import_export.py`
- [X] T015 [P] [US2] Add frontend store test ensuring loaded relations keep source/target ids in `frontend/src/stores/__tests__/treeStore.test.ts`

### Implementation for User Story 2

- [X] T016 [US2] Preserve relations in save/load and version persistence pipelines in `backend/app/services/relation_service.py` and related tree services
- [X] T017 [US2] Serialize/deserialize relations with source_node_id/target_node_id in export/import flow in `backend/app/services` (tree export/import modules)
- [X] T018 [US2] Refresh client state after import/export to render restored relations in `frontend/src/stores/treeStore.ts`

**Checkpoint**: User Story 2 proves relations persist through save/reload/export/import.

---

## Phase 5: User Story 3 - Protect graph integrity (Priority: P3)

**Goal**: Block invalid links (self, duplicate, cycle) with actionable, accessible inline errors and correlation references.

**Independent Test**: Attempt invalid links on a ~200-node tree; errors appear inline, focus and announce via live region, include correlation/reference id, and the canvas stays responsive.

### Tests for User Story 3

- [X] T019 [P] [US3] Add backend tests covering self/duplicate/cycle rejection and correlation reference exposure in `backend/tests/test_api_trees.py`
- [X] T020 [P] [US3] Add frontend test for inline relation error focus + live-region announcement in `frontend/src/components/canvas/__tests__/TreeCanvas.a11y.test.tsx` (or equivalent)
- [X] T021 [P] [US3] Add backend test ensuring correlation/reference id is copyable in error payload and header in `backend/tests/test_api_trees.py`
- [X] T022 [P] [US3] Add frontend test asserting inline error banner shows correlation reference with copy affordance and live-region announcement in `frontend/src/components/canvas/__tests__/TreeCanvas.a11y.test.tsx`

### Implementation for User Story 3

- [X] T023 [US3] Enforce duplicate/self/cycle detection with conflict responses in `backend/app/services/relation_service.py`
- [X] T024 [US3] Return human-readable errors with correlation/reference id in body and headers for relation failures in `backend/app/api/errors.py`
- [X] T025 [US3] Surface inline, accessible error banner with focus management and retry affordance in `frontend/src/components/canvas/TreeCanvas.tsx`
- [X] T026 [P] [US3] Keep canvas interactions responsive and highlights intact during error states in `frontend/src/components/canvas/TreeCanvas.tsx`

**Checkpoint**: User Story 3 validates integrity safeguards and accessible feedback.

---

## Phase N: Polish & Cross-Cutting Concerns

- [ ] T027 Document relation direction, validation, and import/export flow in `specs/001-relation-linking-refactor/quickstart.md`
- [ ] T028 Update release notes/changelog entry for relation direction + error references in `docs/` (add or amend appropriate file)
- [ ] T029 Run `make test-backend` and fix regressions in `backend/`
- [ ] T030 Run `make test-frontend` and fix regressions in `frontend/`
- [ ] T031 Run perf smoke (backend relation latency + frontend large-graph interaction) and document results in `specs/001-relation-linking-refactor/quickstart.md`

---

## Dependencies & Execution Order

- Foundational (Phase 2) blocks all user stories.
- User Story 1 (P1) is MVP and must complete before P2/P3 validation.
- User Story 2 depends on creation flow and schema alignment from Phase 2/US1.
- User Story 3 depends on validation utilities and error contract from Phase 2.

### Parallel Opportunities

- T003–T007 can run in parallel where files do not overlap (frontend vs backend).
- T008–T010 can run in parallel once foundational schema alignment is done.
- T014–T015 can run in parallel after US1 completes.
- T019–T022 can run in parallel once error contract is defined (T024).
