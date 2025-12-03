# Implementation Plan: Local Deployment Setup

**Branch**: `001-local-deploy-setup` | **Date**: 2025-12-03 | **Spec**: specs/001-local-deploy-setup/spec.md
**Input**: Feature specification from `/specs/001-local-deploy-setup/spec.md`

## Summary

Document and script a repeatable local deployment that runs against the current branch, including env templates, health checks, refresh workflow, and troubleshooting to keep iteration under the defined time budgets.

## Technical Context

<!--
  ACTION REQUIRED: Replace the content in this section with the technical details
  for the project. The structure here is presented in advisory capacity to guide
  the iteration process.
-->

**Language/Version**: Python 3.11; TypeScript (strict) + React (Vite).  
**Primary Dependencies**: FastAPI + Pydantic backend; React + Zustand + React Query frontend; Docker/Compose for local stack.  
**Storage**: File-backed tree data under `backend/data` with LRU cache (local volume).  
**Testing**: pytest + FastAPI TestClient (`make test-backend`); Vitest + Testing Library (`make test-frontend`); smoke via `./scripts/smoke_test.sh`.  
**Target Platform**: Local developer machines (macOS/Linux) running Docker/Compose and node/python toolchains.  
**Project Type**: Web full-stack (backend + frontend).  
**Performance Goals**: Initial setup <15 minutes; refresh after code change <5 minutes; health checks pass post-refresh.  
**Constraints**: Avoid port conflicts on standard services (e.g., 3000/5173/8000/5432); no production secrets in local configs.  
**Scale/Scope**: Single-developer local stack; mirrors compose stack used for smoke tests.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- Code quality: Use existing commands (`make test-backend`, `make test-frontend`) plus formatter/linter expectations (Black/Ruff/mypy; ESLint/Prettier/TS) for any touched scripts or docs that include commands/env updates. No contract drift expected; document any compose/env changes in `.env.example` and runbooks.
- Testing: User stories validated by (1) running setup per quickstart until services healthy, (2) applying a code change and using refresh workflow, (3) invoking `./scripts/smoke_test.sh` against the local stack to mirror CI smoke; no new automated tests planned unless new scripts added (then add unit coverage where feasible).
- UX consistency: No UI changes planned; docs will follow existing tone and structure. Any UI references will align with current patterns; accessibility unchanged.
- Performance: Honor setup budgets (initial <15m, refresh <5m) and preserve existing backend/frontend performance by using current compose and dev servers; no hot-path code changes expected. Validate via timing the documented steps and ensuring smoke tests stay green.

Gate status: PASS (no constitution exceptions required at this stage).

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
backend/
├── app/
│   ├── repositories/
│   ├── services/
│   └── ...
└── tests/

frontend/
├── src/
│   ├── components/
│   ├── pages/
│   └── services/
└── src/**/__tests__/

docs/
deploy/
scripts/
```

**Structure Decision**: Web application with backend (FastAPI) and frontend (React/Vite); supporting docs, deploy assets, and scripts directories already in place.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |
