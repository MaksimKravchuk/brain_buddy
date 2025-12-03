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
- `npm run build` (frontend) / `docker compose -f docker-compose.smoke.yml up --build`: produce production bundles and compose stack.
- `./scripts/smoke_test.sh`: call core API endpoints against the compose stack.

## Coding Style & Naming Conventions
- Python: Black (88-col) + Ruff enforced; prefer descriptive snake_case for functions/vars.
- TypeScript/React: follow existing component naming (`PascalCase` files), use TypeScript strict types.
- Keep comments purposeful; leverage existing store/service patterns when extending features.

## Testing Guidelines
- Backend uses pytest with FastAPI TestClient; mirror test names after module under test (`test_tree_service.py`).
- Frontend leverages Vitest + Testing Library; place component specs beside feature folders.
- Ensure new features include targeted tests; run both test suites before pushing.

## Commit & Pull Request Guidelines
- Commit messages follow conventional prefix style (`feat:`, `fix:`, `docs:`, etc.).
- Keep commits focused; include smoke-test or manual verification notes in body when relevant.
- PRs should describe scope, testing performed, and link to requirements or issues; add screenshots/GIFs for UI-visible changes.

## Security & Configuration Tips
- Use `.env.example` as the baseline—copy to `.env` for local compose runs.
- API key protection is optional; set `BRAIN_BUDDY_API_KEY` (backend) and `VITE_API_KEY` (frontend) together when enabling.
- Do not commit real data under `backend/data/`; compose mounts a named volume for local persistence.

## Active Technologies
- Python 3.11 (backend), TypeScript (strict) + React (frontend) + FastAPI, Pydantic, pytest; React, Vite, Zustand, React Query, React Flow-like canvas, Vitest/Testing Library (001-reality-tree-ui)
- File-backed tree data under backend/data with LRU caching; cloud persistence for signed-in users (reuse existing storage path) (001-reality-tree-ui)
- Python 3.11 (backend), TypeScript (strict) + React (frontend), Compose v2 + FastAPI, Pydantic, pytest; Vite/React/Tailwind/TypeScript; Nginx (deploy), Docker/Compose (001-reality-tree-ui)
- File-backed tree data volume (`backend/data`) with LRU cache; optional persisted volume in Compose (001-reality-tree-ui)

## Recent Changes
- 001-reality-tree-ui: Added Python 3.11 (backend), TypeScript (strict) + React (frontend) + FastAPI, Pydantic, pytest; React, Vite, Zustand, React Query, React Flow-like canvas, Vitest/Testing Library
