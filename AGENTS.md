# Repository Guidelines

## Project Structure & Module Organization
- `backend/`: FastAPI app under `app/` with repositories, services, and `tests/` (pytest).
- `frontend/`: Vite React client under `src/`; Vitest specs live in `src/**/__tests__/`.
- `docs/`: Architecture, API, troubleshooting, performance, and smoke runbooks.
- `deploy/`: Container assets (nginx config).
- `scripts/`: Utility scripts such as `smoke_test.sh`.

## Build, Test, and Development Commands
- `make dev-backend` / `make dev-frontend`: run backend with uvicorn reload and Vite dev server.
- `make test-backend`: execute pytest suite (`backend/tests`).
- `make test-frontend`: run Vitest unit tests.
- `npm run build` (frontend) / `docker compose up --build`: produce production bundles and compose stack.
- `./scripts/smoke_test.sh`: call core API endpoints against the compose stack.

## Coding Style & Naming Conventions
- Python: Black (88-col) + Ruff enforced; prefer descriptive snake_case for functions/vars.
- TypeScript/React: follow existing component naming (`PascalCase` files), use TypeScript strict types.
- Keep comments purposeful; leverage existing store/service patterns when extending features.

## Testing Guidelines
- Backend uses pytest with FastAPI TestClient; mirror test names after module under test (`test_tree_service.py`).
- Frontend leverages Vitest + Testing Library; place component specs beside feature folders.
- Every pytest, Vitest, and Playwright product test must emit Allure Report 3 taxonomy: non-empty `epic`, `feature`, `story`, a human-readable title, and at least one named step. Use the central helpers in `backend/tests/allure_taxonomy.py`, `frontend/src/test/allureTaxonomy.ts`, and `frontend/tests/allure.fixtures.ts`; override explicitly only when a test needs narrower labels. See `docs/test-allure-taxonomy.md`.
- Ensure new features include targeted tests; run both test suites before pushing.

## Commit & Pull Request Guidelines
- Commit messages follow conventional prefix style (`feat:`, `fix:`, `docs:`, etc.).
- Keep commits focused; include smoke-test or manual verification notes in body when relevant.
- PRs should describe scope, testing performed, and link to requirements or issues; add screenshots/GIFs for UI-visible changes.

## Security & Configuration Tips
- Use `.env.example` as the baseline—copy to `.env` for local compose runs.
- Auth is session-based (HTTP-only cookie) and invite-gated. Mint invites with `python -m app.cli create-invite`. See `docs/auth.md` for the threat model and recommended controls.
- Do not commit real data under `backend/data/`; compose mounts a named volume for local persistence.

## Architecture Decisions
- Before changing module boundaries, persistence ownership, workflow state machines, authentication assumptions, or deployment boundaries, inspect accepted/proposed records under `docs/decisions/`.
- BrainBuddy vNext's modular-monolith boundaries and capture-to-result contracts are defined in `docs/decisions/0001-vnext-modular-monolith-and-workflow-contracts.md`; preserve them unless a new ADR explicitly supersedes the decision.
- Async voice brain dumps and voice-led Weekly Review share the operation, patch, confirmation, privacy, and idempotency contract in `docs/decisions/0002-async-voice-operation-substrate.md`.
- Native GTD capability status, Task lifecycle transitions, Waiting/recovery behavior, date and Priority semantics, and implementation-ready UI/API gaps are fixed in `docs/decisions/0006-native-gtd-lifecycle-and-capability-baseline.md`.
- Autonomous delivery, visual preview eligibility, and production release/rollback authority are governed by `docs/decisions/0003-autonomous-delivery-guardrails.md` and `docs/autonomous-delivery-runbook.md`.

## Mandatory Spec Kit Workflow
- GitHub Spec Kit is the canonical authoring workflow for every new or materially changed BrainBuddy feature spec; use the repo-pinned official CLI version documented in `docs/spec-kit-workflow.md`. The architect profile uses the official Hermes planning skills; `speckit-implement` and `speckit-taskstoissues` are not part of the Kanban path.
- The required sequence is constitution → `/speckit-specify` (what/why) → `/speckit-clarify` → `/speckit-plan` (how/architecture) → `/speckit-checklist` → `/speckit-tasks` → `/speckit-analyze` → one compact Hermes Kanban handoff. Upstream v0.12.17 checklist setup requires `plan.md`, so run checklist after planning. Amend the spec first whenever implementation intent changes; never publish one Kanban card per `tasks.md` line.
- Spec Kit owns versioned planning artifacts under `specs/` plus `.specify/`; Hermes Kanban remains the execution/orchestration and PR-review system. Generated `tasks.md` is planning input, not permission to bypass isolated worktrees, TDD, review, CI, merge, or release gates. `/speckit-implement` is disabled for BrainBuddy.
- Architect-profile agents own Spec Kit technical planning, module boundaries, ADR alignment, and architecture handoff for new/materially changed architecture or feature specs. Implementation agents consume those artifacts from their Kanban cards rather than inventing architecture.
- Before adding or changing a feature spec, run `python3 scripts/check_spec_kit_specs.py` (or `make check-specs`) and preserve documented grandfathering for historical specs.

## Agent Delivery Workflow
- Work in an isolated git worktree and feature branch. Never leave product changes uncommitted in the primary worktree.
- Every useful product change must be committed, pushed, and opened as a PR against `main`. Review and green CI are the merge gate.
- A successful push to `main` deploys to Fly automatically and runs production smoke checks. Do not perform an ad-hoc production deploy instead of this release path.
- There are currently no customer or valuable production data: prioritize MVP velocity, but preserve the PR → CI → deploy traceability.

## Active Technologies
- Python 3.11 (backend), TypeScript (strict) + React (frontend) + FastAPI, Pydantic, pytest; React, Vite, Zustand, React Query, React Flow-like canvas, Vitest/Testing Library (001-reality-tree-ui)
- File-backed tree data under backend/data with LRU caching; cloud persistence for signed-in users (reuse existing storage path) (001-reality-tree-ui)
- Python 3.11 (backend), TypeScript (strict) + React (frontend), Compose v2 + FastAPI, Pydantic, pytest; Vite/React/Tailwind/TypeScript; Nginx (deploy), Docker/Compose (001-reality-tree-ui)
- File-backed tree data volume (`backend/data`) with LRU cache; optional persisted volume in Compose (001-reality-tree-ui)
- Python 3.11 (backend), TypeScript (strict) + React (frontend) + FastAPI, Pydantic, pytest/FastAPI TestClient; Vite, React, Zustand, React Query, Vitest/Testing Library (001-reality-tree-ui)
- File-backed tree data under `backend/data` with LRU cache; optional cloud persistence for signed-in users (API key gated) (001-reality-tree-ui)
- Python 3.11 (backend), TypeScript (strict) + React (frontend) + FastAPI, Pydantic; React, Vite, Zustand, React Query, Testing Library/Vites (001-remove-ui-minimize)
- Existing file-backed tree data (unchanged for this feature) (001-remove-ui-minimize)
- Python 3.11 (backend), TypeScript strict + React (frontend) + FastAPI, Pydantic, pytest; Vite, React, Zustand, React Query, Tailwind, Vitest/Testing Library (001-remove-ui-minimize)
- File-backed tree data in `backend/data` with LRU cache; optional compose volume for persistence (no new data added for this feature) (001-remove-ui-minimize)
- Python 3.11; TypeScript (strict) + React (Vite). + FastAPI + Pydantic backend; React + Zustand + React Query frontend; Docker/Compose for local stack. (001-local-deploy-setup)
- File-backed tree data under `backend/data` with LRU cache (local volume). (001-local-deploy-setup)
- Python 3.11 (backend), TypeScript (strict) + React (frontend) + FastAPI, Pydantic, pytest; Vite, React, Zustand, React Query, Vitest/Testing Library (001-refactor-node-relations)
- File-backed node data with LRU caching; optional compose volume (001-refactor-node-relations)
- Python 3.11 (backend), TypeScript (strict) + React (frontend) + FastAPI, Pydantic, pytest/FastAPI TestClient; React, Vite, Zustand, React Query, React Flow-like canvas, Vitest + Testing Library (001-relation-linking-refactor)

## Recent Changes
- 001-reality-tree-ui: Added Python 3.11 (backend), TypeScript (strict) + React (frontend) + FastAPI, Pydantic, pytest; React, Vite, Zustand, React Query, React Flow-like canvas, Vitest/Testing Library
