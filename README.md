# Brain Buddy

[![CI](https://github.com/MVkravchuk/brain_buddy/actions/workflows/ci.yml/badge.svg)](https://github.com/MVkravchuk/brain_buddy/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-artifacts-blue)](https://github.com/MVkravchuk/brain_buddy/actions/workflows/ci.yml)

Brain Buddy is a collaborative knowledge-graph workspace that helps product teams capture research trees, validate assumptions with AI guidance, and preserve historical versions of their thinking.

## Highlights
- **Interactive canvas** powered by React Flow with undo/redo, optimistic updates, and large-graph tuning for 200+ nodes.
- **FastAPI backend** persisting trees on the filesystem with LRU caching and version history snapshots.
- **AI validation pipeline** with provider abstraction and mock provider for offline workflows.
- **Operational polish** including correlation-ID tracing, optional API key guardrails, and expanded troubleshooting guides.
- **Data safety by default** with 5s local autosave, exit warnings, and explicit consent gating before any AI request.

## Architecture Snapshot
- **Backend**: FastAPI, Pydantic, pytest. Data persisted under `backend/data/` with schema versioning. See `docs/architecture_overview.md`.
- **Frontend**: Vite + React + TypeScript, TailwindCSS, Zustand, React Query. Canvas profiling hook surfaces render timings during dev.
- **Data contracts**: Shared JSON payloads defined in `backend/app/schemas` and referenced by the React client.

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+
- Optional: `make`, `uvicorn`, `npm` scripts available on your PATH

### Backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e .[dev]

# Optional: require API key by exporting BRAIN_BUDDY_API_KEY=<your-key>
uvicorn app.main:app --reload
```

### Frontend
```bash
cd frontend
npm install

# If the backend enforces an API key, export
# VITE_API_KEY=<your-key> (and VITE_API_KEY_HEADER if customised)
npm run dev
```

By default the frontend expects the backend at `http://localhost:8000/api`. Configure `VITE_API_BASE_URL` to point elsewhere.

### Autosave & AI Consent
- The canvas autosaves locally every ~5s (debounced) and warns on exit if unsaved changes exist; signed-in saves still run on-demand.
- AI feedback requires an API key and explicit consent toggle in the inspector; decline consent to keep data local and receive a validation error instead of sending content.
- Failures return correlation IDs in error toasts so you can retry or report with context.

### Smoke Test via Docker Compose

Prefer containers for manual verification or stakeholder demos? Copy `.env.example` to `.env`, then run:

```bash
docker compose up --build
```

The backend will listen on `http://localhost:8000`, and the frontend will be available at `http://localhost:8080`. When finished, tear everything down with `docker compose down --volumes`. See `docs/deployment_smoke.md` for the full runbook, including optional API key wiring and automated smoke checks.

Looking for a local-first workflow with refresh/troubleshooting steps? See `docs/runbooks/local-deployment.md`.

**API keys in compose**: set `BRAIN_BUDDY_API_KEY` and `VITE_API_KEY` together in `.env` to require a key end-to-end. The compose stack forwards these into backend/frontend containers and the smoke test will include them automatically.

## Deployment

- **Fly.io**: Follow `docs/fly-deployment.md` for provisioning volumes, wiring secrets, deploying backend and frontend apps, and running curl smoke checks with rollback guidance.
- **CI before deploys**: GitHub Actions (`.github/workflows/ci.yml`) runs backend lint/type/test + coverage, frontend unit tests + build, and Docker image builds on every push/PR to `main`. Wait for CI to go green (see the badge above) before deploying to Fly.

## Environment & Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `BRAIN_BUDDY_API_PREFIX` | `/api` | Route prefix for FastAPI routers |
| `BRAIN_BUDDY_DATA_DIR` | `<repo>/backend/data` | Root directory for tree storage |
| `BRAIN_BUDDY_API_KEY` | _unset_ | When set, requests must include the configured API key |
| `BRAIN_BUDDY_API_KEY_HEADER` | `X-API-Key` | Header expected to carry the static API key |
| `VITE_API_BASE_URL` | `/api` | Frontend API base path (proxied in dev) |
| `VITE_API_KEY` | _unset_ | Optional API key forwarded with every fetch |
| `VITE_API_KEY_HEADER` | `X-API-Key` | Header name used when forwarding the API key |

See `docs/api_usage.md` for request/response details and examples.

## Testing & Tooling
- Backend: `cd backend && pytest`
- Frontend unit tests: `cd frontend && npm test`
- Linting/formatting: Black, Ruff, and Mypy on the backend; ESLint/Prettier via Vite on the frontend.
- Continuous improvement scripts live in the root `Makefile` (`make test-backend`, `make test-frontend`).

## Performance & Observability
- File-backed caches reduce repeated tree loads during read-heavy sessions.
- `useGraphProfiler` logs render timings in development once node/edge counts change.
- Every response includes `X-Correlation-ID`, making it easy to trace requests through backend logs.
- Error toasts now surface retry actions and show correlation references when failures occur.

## Documentation
- `docs/architecture_overview.md`
- `docs/api_usage.md`
- `docs/troubleshooting.md`
- `docs/contributing.md`
- `docs/performance_report_phase5.md`
- `docs/deployment_smoke.md`
- `docs/infrastructure_runbook.md`
- `docs/release_checklist.md`
- `docs/pilot_dataset.json`

Historical requirements, contracts, and the phased roadmap remain under `requirements/`.

## Contributing
Guidelines, branching strategy, and review expectations are documented in `docs/contributing.md`. We welcome issue reports captured via `docs/troubleshooting.md#reporting`.
