# Implementation Plan: Current Reality Tree UI

**Branch**: `001-reality-tree-ui` | **Date**: 2025-12-03 | **Spec**: specs/001-reality-tree-ui/spec.md
**Input**: Feature specification from `/specs/001-reality-tree-ui/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

Enable the full Brain Buddy stack to be deployed locally via Docker Compose so contributors can run the FastAPI backend, Vite/React frontend, and supporting assets with minimal setup. Align compose services, environment variables, and volumes with existing Makefile targets and smoke scripts, ensuring parity with the current UI feature work (Current Reality Tree) and CI expectations.

## Technical Context

<!--
  ACTION REQUIRED: Replace the content in this section with the technical details
  for the project. The structure here is presented in advisory capacity to guide
  the iteration process.
-->

**Language/Version**: Python 3.11 (backend), TypeScript (strict) + React (frontend), Compose v2  
**Primary Dependencies**: FastAPI, Pydantic, pytest; Vite/React/Tailwind/TypeScript; Nginx (deploy), Docker/Compose  
**Storage**: File-backed tree data volume (`backend/data`) with LRU cache; optional persisted volume in Compose  
**Testing**: pytest + FastAPI TestClient; Vitest + Testing Library; smoke via `make compose-smoke-up`/`./scripts/smoke_test.sh`  
**Target Platform**: Local Docker (macOS/Linux) running frontend+backend via Compose; browsers for UI  
**Project Type**: Web application (backend + frontend) containerized for local use  
**Performance Goals**: Compose stack should serve the UI and API without noticeable latency in dev; canvas interactions ~<=0.2s on 200-node trees; backend p95 under 200 ms locally  
**Constraints**: Keep env parity with `.env.example`; optional API key wiring through compose; avoid breaking existing local dev flows (npm/uvicorn) and make targets  
**Scale/Scope**: Local developer usage; single-user sessions with datasets of a few hundred nodes/relations

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- Code quality: identify lint/format/type-check commands for every surface you will touch (backend: Black/Ruff/mypy; frontend: ESLint/Prettier/TypeScript) and plan contract sync between backend schemas and frontend clients/types.
- Testing: enumerate unit/integration/smoke coverage for each user story; confirm how `make test-backend` and `make test-frontend` will validate the change and where new fixtures are needed.
- UX consistency: describe how UI changes align with existing layout/toast/modal patterns, accessibility (focus/ARIA/keyboard), and responsive behavior down to tablet widths.
- Performance: state expected budgets (e.g., canvas interactions on 200+ nodes remain near ≤20 ms renders; backend tree reads/writes target <200 ms local p95) and the profiling/logging you will use to prove no regressions.

Gates:  
- Code quality: Black/Ruff/mypy on backend, ESLint/Prettier/TypeScript on frontend; ensure compose env matches schema contracts and API clients.  
- Testing: Run `make test-backend`, `make test-frontend`, and smoke via `make compose-smoke-up` + `./scripts/smoke_test.sh` after compose changes; add tests for compose env configuration if needed.  
- UX consistency: Compose should surface existing UI unchanged; ensure toasts/errors remain consistent when API key/auth is toggled.  
- Performance: Validate canvas responsiveness (~0.2s on 200-node sample) and backend p95 <200 ms within compose; monitor logs for latency regressions; reuse `useGraphProfiler` during compose runs.

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

```text
# [REMOVE IF UNUSED] Option 1: Single project (DEFAULT)
src/
├── models/
├── services/
├── cli/
└── lib/

tests/
├── contract/
├── integration/
└── unit/

# [REMOVE IF UNUSED] Option 2: Web application (when "frontend" + "backend" detected)
backend/
├── src/
│   ├── models/
│   ├── services/
│   └── api/
└── tests/

frontend/
├── src/
│   ├── components/
│   ├── pages/
│   └── services/
└── tests/

# [REMOVE IF UNUSED] Option 3: Mobile + API (when "iOS/Android" detected)
api/
└── [same as backend above]

ios/ or android/
└── [platform-specific structure: feature modules, UI flows, platform tests]
```

**Structure Decision**: [Document the selected structure and reference the real
directories captured above]
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
└── tests/ (Vitest) and e2e seeds

deploy/
└── nginx/default.conf

scripts/
└── smoke_test.sh

specs/001-reality-tree-ui/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
└── contracts/
```

**Structure Decision**: Standard backend+frontend layout with deploy/nginx assets; Compose will orchestrate backend, frontend, and nginx (if needed) while mounting backend/data as a volume.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |
