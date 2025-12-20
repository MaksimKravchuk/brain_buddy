# Tasks: Flexible Relation Linking

**Input**: Design documents from `/specs/001-relation-linking-refactor/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Tests are optional; spec did not request new tests. Consider adding focused coverage during implementation.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story. Include consent/observability/performance safeguards where relevant.

## Format: `[ID] [P?] [Story] Description`

## Phase 1: Setup (Shared Infrastructure)

- [ ] T001 Ensure environment configuration aligns with feature (copy `.env.example` to `.env` if needed) in repo root
- [ ] T002 Verify relation contract baseline against plan in `specs/001-relation-linking-refactor/contracts/relations.md`

---

## Phase 2: Foundational (Blocking Prerequisites)

- [ ] T003 Update relation schema to enforce source/target fields and cause→effect direction in `backend/app/schemas/relation.py`
- [ ] T004 Add relation validation utilities for self/duplicate/cycle checks in `backend/app/services/relations.py`
- [ ] T005 Wire backend relation routes to new validation flow in `backend/app/api/routes/relations.py`
- [ ] T006 Propagate correlation/reference id support for relation errors in `backend/app/api/routes/relations.py`
- [ ] T007 Add frontend relation request typings and client helper for create/delete in `frontend/src/services/relations.ts`

---

## Phase 3: User Story 1 - Link nodes across chains (Priority: P1) 🎯 MVP

**Goal**: Create directed relations between nodes across branches without parent/child terminology.

**Independent Test**: Link Node2 to Node5 across chains; relation renders with correct direction and highlight.

### Implementation for User Story 1

- [ ] T008 [US1] Add UI affordance for selecting source/target without parent/child wording in `frontend/src/components/Canvas/RelationCreate.tsx`
- [ ] T009 [P] [US1] Ensure link rendering shows direction and highlights with endpoints in `frontend/src/components/Canvas/RelationEdge.tsx`
- [ ] T010 [US1] Persist new relation via API call and update local store in `frontend/src/store/relations.ts`
- [ ] T011 [US1] Confirm backend creates relation per contract and returns ids in `backend/app/api/routes/relations.py`

**Checkpoint**: User Story 1 independently delivers cross-branch linking with correct direction.

---

## Phase 4: User Story 2 - Preserve new relations (Priority: P2)

**Goal**: Cross-branch relations survive save/reload and export/import.

**Independent Test**: Create relation, save/reload, export/import, and verify direction persists.

### Implementation for User Story 2

- [ ] T012 [US2] Include relations in tree save/load pipelines in `backend/app/services/trees.py`
- [ ] T013 [US2] Serialize/deserialize relations in export/import logic in `backend/app/services/export.py`
- [ ] T014 [US2] Update frontend import/export handling to include relations in `frontend/src/services/io/exportImport.ts`
- [ ] T015 [P] [US2] Ensure UI refresh applies restored relations and highlights in `frontend/src/store/relations.ts`

**Checkpoint**: User Story 2 independently proves persistence across save/reload/export/import.

---

## Phase 5: User Story 3 - Protect graph integrity (Priority: P3)

**Goal**: Block invalid links (self, duplicate, cycle) with actionable, accessible inline errors.

**Independent Test**: Attempt invalid links; inline message focuses/announces, includes correlation ref, and preserves responsiveness on ~200-node canvas.

### Implementation for User Story 3

- [ ] T016 [US3] Implement cycle detection hook for relation creation in `backend/app/services/relations.py`
- [ ] T017 [US3] Return structured human-readable error with correlation reference in `backend/app/api/routes/relations.py`
- [ ] T018 [US3] Handle relation errors inline with focus + live region announcement in `frontend/src/components/Canvas/RelationCreate.tsx`
- [ ] T019 [P] [US3] Maintain canvas responsiveness and highlight behavior on large graphs in `frontend/src/components/Canvas/RelationEdge.tsx`

**Checkpoint**: User Story 3 independently validates integrity safeguards and accessible feedback.

---

## Phase N: Polish & Cross-Cutting Concerns

- [ ] T020 Document linking/persistence/validation flow in `specs/001-relation-linking-refactor/quickstart.md`
- [ ] T021 Update release notes or changelog entry for relations in `docs/` (add appropriate file)
- [ ] T022 Run full backend/frontend test suites and fix regressions in `backend/` and `frontend/`

---

## Dependencies & Execution Order

- Foundational (Phase 2) blocks all user stories.
- User Story 1 (P1) is MVP and should complete before P2/P3 validation.
- User Story 2 depends on relation creation from US1.
- User Story 3 depends on validation hooks from Foundational and creation flow from US1.

### Parallel Opportunities

- T009 and T010 can run in parallel after T008 setup.
- T012 and T013 can run in parallel once backend relation schema/validation is ready.
- T018 and T019 can run in parallel after API error contract (T017) is defined.

---

## Implementation Strategy

### MVP First (User Story 1 Only)
1. Complete Foundational (Phase 2).
2. Deliver User Story 1 linking flow.
3. Validate linking end-to-end.

### Incremental Delivery
1. Finish Foundational.
2. Add User Story 1 → validate.
3. Add User Story 2 → validate persistence/export/import.
4. Add User Story 3 → validate integrity and accessibility.

### Parallel Team Strategy
1. After Foundational, split:
   - Developer A: US1 front-end flow (T008–T010).
   - Developer B: US1/US3 backend validation and error handling (T011, T016–T017).
   - Developer C: US2 persistence/export/import (T012–T015).
