---
description: "Task list for Current Reality Tree UI (docker-compose-ready local stack)"
---

# Tasks: Current Reality Tree UI

**Input**: Design documents from `/specs/001-reality-tree-ui/`
**Prerequisites**: plan.md (required), spec.md (user stories), research.md, data-model.md, contracts/

**Tests**: Tests are optional per instructions; validation relies on existing smoke script and manual verification steps.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Compose-ready local stack and env parity

- [ ] T001 Update `.env.example` with compose defaults for API base URLs and ports to mirror dockerized backend/frontend.
- [ ] T002 Add `docker-compose.local.yml` orchestrating backend (port 8000, data volume) and frontend (port 8080) with optional API key wiring.
- [ ] T003 Update `Makefile` targets (`compose-up`, `compose-down`) to use `docker-compose.local.yml` and align with existing `compose-smoke` targets.
- [ ] T004 Align `scripts/smoke_test.sh` to target compose hosts/ports and document usage comments for local stack.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared contracts and client wiring required by all stories

- [ ] T005 Sync backend tree JSON schema and routes with contracts in `backend/app/schemas/api.py` and `backend/app/api/routes.py`.
- [ ] T006 Update frontend API client/types to match tree schema and base URLs in `frontend/src/api/client.ts` and `frontend/src/api/types.ts`.
- [ ] T007 Establish tree store scaffolding for local state, selection, and hotkey plumbing in `frontend/src/stores/treeStore.ts` and `frontend/src/stores/uiStore.ts`.
- [ ] T008 Add cycle/direction validation helper for relations in `backend/app/services/tree_service.py` and `backend/app/utils/identifiers.py`.

---

## Phase 3: User Story 1 - Build and navigate a current reality tree (Priority: P1) 🎯 MVP

**Goal**: Create/navigate trees with keyboard-friendly controls and visual cues

**Independent Test**: Create nodes of each type, link bottom-to-top relations, zoom/center, and see highlights without relying on persistence or AI.

- [ ] T009 [US1] Implement keyboard shortcuts for node create/link/zoom/center in `frontend/src/stores/uiStore.ts` and `frontend/src/components/canvas/TreeCanvas.tsx`.
- [ ] T010 [P] [US1] Add node creation/edit UI with type-specific colors in `frontend/src/components/BrainNode.tsx` and `frontend/src/components/CreateNodeButton.tsx`.
- [ ] T011 [US1] Render directional "why" relations bottom-to-top with selection highlighting in `frontend/src/components/canvas/TreeCanvas.tsx`.
- [ ] T012 [P] [US1] Add zoom and recenter controls that keep selection in view in `frontend/src/components/layout/CanvasShell.tsx`.
- [ ] T013 [US1] Apply cause/effect-spanning highlighting rules (>=3 upstream, all undesired effects) in `frontend/src/stores/treeStore.ts` and `frontend/src/components/BrainNode.tsx`.
- [ ] T014 [US1] Implement auto-save drafts (local, cloud stub) and exit warning on unsynced changes in `frontend/src/stores/treeStore.ts` and `frontend/src/components/layout/Layout.tsx`.

---

## Phase 4: User Story 2 - Persist and share trees (Priority: P2)

**Goal**: Save, re-open, export/import trees with full fidelity

**Independent Test**: Save a tree, download JSON, import into a new session, and reopen after sign-in without AI features.

- [ ] T015 [US2] Implement tree CRUD endpoints per contracts in `backend/app/api/routes.py`, `backend/app/services/tree_service.py`, and `backend/app/repositories/tree.py`.
- [ ] T016 [P] [US2] Add backend import/export validation and JSON schema enforcement in `backend/app/schemas/api.py` and `backend/app/api/routes.py`.
- [ ] T017 [US2] Wire tree management menu (new/save/open) to backend API in `frontend/src/components/topbar/TreeSelector.tsx` and `frontend/src/components/modals/CreateTreeModal.tsx`.
- [ ] T018 [US2] Add download/import flows with error toasts in `frontend/src/components/topbar/TreeSelector.tsx`, `frontend/src/api/hooks.ts`, and `frontend/src/utils/error.ts`.
- [ ] T019 [US2] Ensure signed-in persistence with API key forwarding in `frontend/src/api/client.ts` and `frontend/src/stores/treeStore.ts`.

---

## Phase 5: User Story 3 - Receive AI feedback on reasoning chains (Priority: P3)

**Goal**: Provide AI summaries and recommendations with explicit consent

**Independent Test**: Request AI analysis on a populated tree while signed in, receive summary/recommendations, handle failures without data loss.

- [ ] T020 [US3] Implement AI feedback endpoint `/api/trees/{id}/ai-feedback` using provider abstraction in `backend/app/api/routes.py`, `backend/app/ai/providers`, and `backend/app/services/tree_service.py`.
- [ ] T021 [US3] Add AI feedback request UI with confirmation prompt in `frontend/src/components/panels/NodeInspector.tsx` and `frontend/src/stores/uiStore.ts`.
- [ ] T022 [US3] Surface AI progress/error toasts and preserve tree state on failure in `frontend/src/api/hooks.ts` and `frontend/src/utils/error.ts`.

---

## Phase N: Polish & Cross-Cutting Concerns

**Purpose**: Performance, docs, and observability

- [ ] T023 Update docs (`README.md`, `specs/001-reality-tree-ui/quickstart.md`) with compose usage, env vars, and AI consent behavior.
- [ ] T024 Validate compose stack via `make compose-smoke-up` and `./scripts/smoke_test.sh`; capture fixes in `docker-compose.local.yml` or `scripts/smoke_test.sh`.
- [ ] T025 Review accessibility and performance (focus/ARIA, 200-node canvas ~0.2s) in `frontend/src/components/canvas/TreeCanvas.tsx` and `frontend/src/hooks/useGraphProfiler.ts`.

---

## Dependencies & Execution Order

- Phase 1 (Setup) → Phase 2 (Foundational) → User Stories (3 → 4 → 5) → Polish.
- User story dependencies: US1 is independent once foundational is done; US2 depends on API/schema readiness; US3 depends on saved trees and API client wiring.

### Parallel Opportunities

- In US1, T010 (node UI) and T012 (navigation controls) can proceed in parallel after T009 scaffolding.
- In US2, T016 (import/export validation) can run in parallel with T015 core CRUD.
- In US3, T021 UI work can parallel T020 backend endpoint once contract is agreed.

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Setup + Foundational.
2. Deliver US1 (canvas creation, relations, highlighting, auto-save warning).
3. Validate locally via compose and manual UI checks.

### Incremental Delivery

1. US1 → 2 → 3 in priority order, running compose smoke after each milestone.
2. Ship persistence (US2) once API and import/export stabilize.
3. Add AI feedback (US3) after consent flow and error handling are in place.

### Parallel Team Strategy

- Developer A: Backend schemas/routes (T005, T015, T016, T020).
- Developer B: Frontend canvas + shortcuts (T009–T014).
- Developer C: Persistence UI flows (T017–T019) then AI UI (T021–T022).
- Shared: Docs/perf/accessibility (T023–T025) after core stories land.
