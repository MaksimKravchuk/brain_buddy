# Implementation Plan: Flexible Relation Linking

**Branch**: `001-relation-linking-refactor` | **Date**: 2025-12-20 | **Spec**: specs/001-relation-linking-refactor/spec.md
**Input**: Feature specification from `/specs/001-relation-linking-refactor/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

Enable linking any two nodes within the same tree (across branches) with consistent cause→effect direction, block self/duplicate/cycle relations, and keep links persisted and observable with inline, accessible, human-readable errors and correlation references.

## Technical Context

<!--
  ACTION REQUIRED: Replace the content in this section with the technical details
  for the project. The structure here is presented in advisory capacity to guide
  the iteration process.
-->

**Language/Version**: Python 3.11 (backend), TypeScript (strict) + React (frontend)  
**Primary Dependencies**: FastAPI, Pydantic, pytest/FastAPI TestClient; React, Vite, Zustand, React Query, React Flow-like canvas, Vitest + Testing Library  
**Storage**: File-backed tree data under `backend/data` with LRU cache (local volume)  
**Testing**: `make test-backend` (pytest) and `make test-frontend` (Vitest/Testing Library); add focused tests for relation creation/validation and persistence  
**Target Platform**: Web (backend API + frontend client)  
**Project Type**: web (backend + frontend)  
**Performance Goals**: Canvas interactions and relation creation/selection responsive within ~0.2s on ~200-node trees; relation creation feedback within ~2s including validation  
**Constraints**: Local-first autosave with exit warnings; no parent/child terminology; consent/API key pairing optional but supported; inline accessible errors with correlation refs; avoid data loss  
**Scale/Scope**: Single-tree operations, typical graphs up to ~200 nodes; no cross-tree linking

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- Consent & Safety: Keep local-first saves with autosave/exit warnings; respect API key pairing when enabled; do not ship real data. No remote AI added.
- Tests: Add failing-first pytest tests for relation validation (self/duplicate/cycle) and persistence; Vitest tests for UI link flow, inline errors, accessibility focus/announcement; run `make test-backend` and `make test-frontend`.
- Contracts: Update schemas/contracts for relation creation payloads/validation; keep direction semantics stable and ensure export/import parity across backend/frontend.
- Observability: Ensure correlation IDs propagate to relation failures; inline errors include copyable reference; structured logging covers validation failures.
- Performance/Resilience: Maintain ~0.2s interaction on ~200-node trees; keep autosave intact; non-blocking inline errors with retry paths; avoid data loss on failure.

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)
<!--
  ACTION REQUIRED: Replace the placeholder tree below with the concrete layout
  for this feature. Delete unused options and expand the chosen structure with
  real paths (e.g., apps/admin, packages/something). The delivered plan must
  not include Option labels.
-->

backend/
├── app/               # FastAPI app, schemas, services
├── tests/             # pytest (unit/integration)
└── data/              # file-backed storage

frontend/
├── src/
│   ├── components/
│   ├── pages/
│   ├── services/
│   └── store/
└── src/**/__tests__/   # Vitest/Testing Library
```

**Structure Decision**: Web application with backend (FastAPI under `backend/app`) and frontend (React under `frontend/src`), tests in `backend/tests` and `frontend/src/**/__tests__/`.

## Complexity Tracking

No Constitution violations identified; no waivers required.
