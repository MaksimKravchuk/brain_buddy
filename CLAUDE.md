# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Backend (Python / FastAPI)

```bash
# Install
cd backend && pip install -e .[dev]

# Dev server (from repo root)
make dev-backend          # uvicorn app.main:app --reload --app-dir backend

# Tests
make test-backend         # builds Docker test image and runs pytest
cd backend && pytest      # run directly against local venv

# Run a single test
cd backend && pytest tests/test_tree_service.py::test_create_tree -v

# Lint / format / type check
cd backend && ruff check app tests
cd backend && black app tests
cd backend && mypy app
```

### Frontend (TypeScript / React)

```bash
# Install
cd frontend && npm install

# Dev server
make dev-frontend         # Vite at localhost:5173

# Tests
make test-frontend        # builds Docker test image and runs Vitest
cd frontend && npm test   # vitest run (once)
cd frontend && npm run test:watch

# Build
cd frontend && npm run build
```

### Full stack

```bash
cp .env.example .env
docker compose up --build        # backend:8000, frontend:8080
./scripts/smoke_test.sh          # runs core API endpoints against compose stack
docker compose down --volumes
```

## Architecture

### Backend — layered design

```
HTTP request
  → app/api/          (FastAPI routes, request/response coercion)
  → app/services/     (business logic, orchestration, LRU cache)
  → app/repositories/ (file I/O under backend/data/)
```

**Key services:**
- `TreeService` — CRUD + 16-entry LRU in-memory cache; also coordinates AI feedback
- `NodeService` / `RelationService` — mutations that update the parent tree document
- `ValidationService` — dispatches to an AI provider and records history
- `VersionService` — creates/restores JSON snapshots of a tree

**Dependency injection** lives in `app/container.py`, which wires repositories → services → API routers. All routes use FastAPI `Depends()` to receive services; never instantiate services directly in route handlers.

**Data model:** each tree is a single JSON file (`backend/data/<tree_id>.json`) containing the full tree document with embedded `nodes` and `relations` arrays. An index file tracks all tree IDs. Pydantic domain models are in `app/schemas/domain.py`; API contracts are in `app/schemas/api.py`.

**AI provider abstraction** (`app/ai/providers/`): `base.py` defines the interface; `mock.py` returns canned responses; `openai.py` calls the real API. The active provider is selected at startup via config.

### Frontend — state and data flow

**Server state** is managed by React Query (`src/api/`). Custom hooks (`useTree`, `useTrees`, etc.) wrap the typed client in `src/api/client.ts`.

**Client state** uses two Zustand stores:
- `useTreeStore` (`src/stores/treeStore.ts`) — active tree, nodes, relations, versions, undo/redo stack, optimistic update queue, 5-second debounced autosave to localStorage
- `useUiStore` (`src/stores/uiStore.ts`) — modal visibility, toasts

**Canvas** is built on React Flow (`reactflow`). `TreeCanvas` renders nodes and custom edges. Node/relation details are shown in `InspectorTabs` → `NodeInspector` / `RelationInspector`.

### Environment variables

| Variable | Default | Notes |
|---|---|---|
| `BRAIN_BUDDY_ENV` | `development` | `development`, `production`, or `test` |
| `BRAIN_BUDDY_DATA_DIR` | `backend/data` | file storage root |
| `BRAIN_BUDDY_API_KEY` | _(unset)_ | enables API key auth when set |
| `VITE_API_BASE_URL` | `/api` | backend URL from frontend |
| `VITE_API_KEY` | _(unset)_ | must match backend key when auth is on |

## Conventions

- **Commits:** conventional prefix style — `feat:`, `fix:`, `docs:`, `refactor:`, etc.
- **Python:** Black 88-col + Ruff (`E`, `F`, `I`, `UP`, `B` rules); snake_case functions/vars.
- **TypeScript:** strict mode; PascalCase component filenames; no `any` except at explicit boundaries.
- **Backend tests:** mirror module name (`test_tree_service.py`); use the `api_client` / service fixtures from `conftest.py`; clear the LRU cache between tests.
- **Frontend tests:** Vitest + Testing Library in `src/**/__tests__/`; Playwright e2e in `frontend/tests/`.
