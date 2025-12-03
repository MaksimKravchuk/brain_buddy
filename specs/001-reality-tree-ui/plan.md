# Implementation Plan: Current Reality Tree UI

**Branch**: `001-reality-tree-ui` | **Date**: 2025-12-03 | **Spec**: `/specs/001-reality-tree-ui/spec.md`  
**Input**: Feature specification for building, persisting, and analyzing Current Reality Trees.

## Summary

Deliver a canvas-first Current Reality Tree experience with FastAPI (backend) and Vite/React (frontend). Users create nodes (undesired effect, cause, regular), connect bottom-to-top “why” relations, navigate via keyboard/zoom, persist trees (local download/import and signed-in save/load), and request AI feedback with explicit consent. Contracts remain synchronized between backend schemas and frontend clients/types; performance, accessibility, and quality gates from the spec and constitution are enforced.

## Technical Context

**Language/Version**: Python 3.11 (backend), TypeScript (strict) + React (frontend)  
**Primary Dependencies**: FastAPI, Pydantic, pytest/FastAPI TestClient; Vite, React, Zustand, React Query, Vitest/Testing Library  
**Storage**: File-backed tree data under `backend/data` with LRU cache; optional cloud persistence for signed-in users (API key gated)  
**Testing**: `make test-backend` (pytest), `make test-frontend` (Vitest/Testing Library); smoke via `./scripts/smoke_test.sh` and compose targets  
**Target Platform**: Web UI served by Vite/React; FastAPI JSON API; local dev via make/compose  
**Project Type**: Web application (backend + frontend)  
**Performance Goals**: Canvas interactions stay near ≤0.2s perceived on ~200 nodes; backend tree reads/writes local p95 <200 ms; AI/save flows target p95 ≤5s with visible progress/error surfaces  
**Constraints**: Keyboard-first UX, accessibility (focus/ARIA), schema parity across surfaces, contract-aligned import/export; optional API key protection; preserve existing make/compose dev flows  
**Scale/Scope**: Single-user sessions with trees of a few hundred nodes/relations; AI feedback scoped to signed-in users

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- Code quality: Run Black/Ruff/mypy for backend; ESLint/Prettier/TypeScript strict for frontend. Enforce contract sync between backend schemas and frontend clients/types; update `.env.example` and docs alongside config changes.
- Testing: US1 (canvas/build): unit tests for stores, canvas rendering/shortcuts, relation validation. US2 (persistence): API contract tests, import/export round-trip tests, error handling. US3 (AI): endpoint contract tests/stubs and UI progress/error handling. Gates: `make test-backend`, `make test-frontend`, and smoke (`./scripts/smoke_test.sh`/compose) before delivery.
- UX consistency: Follow existing layout/top bar/panels/canvas patterns; keep keyboard navigation and ARIA/focus states; ensure tablet-responsiveness.
- Performance: Canvas rendering profile near ≤20 ms per render step on ~200 nodes using `useGraphProfiler`; backend tree read/write p95 <200 ms; AI/save flows p95 ≤5s with visible progress and retry guidance.

## Project Structure

### Documentation (this feature)

```text
specs/001-reality-tree-ui/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
└── tasks.md
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── api/
│   ├── schemas/
│   ├── services/
│   ├── repositories/
│   └── utils/
└── tests/

frontend/
├── src/
│   ├── components/
│   ├── hooks/
│   ├── stores/
│   ├── api/
│   └── styles/
└── src/**/__tests__/ (Vitest)

deploy/
└── nginx/default.conf

scripts/
└── smoke_test.sh
```

**Structure Decision**: Standard backend + frontend web application with FastAPI API and Vite/React UI; docs live under `specs/001-reality-tree-ui/`; compose/make targets orchestrate services for local dev and smoke.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|---------------------------------------|
| None | — | — |
