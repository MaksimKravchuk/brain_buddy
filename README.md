# Brain Buddy

[![CI](https://github.com/MVkravchuk/brain_buddy/actions/workflows/ci.yml/badge.svg)](https://github.com/MVkravchuk/brain_buddy/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-artifacts-blue)](https://github.com/MVkravchuk/brain_buddy/actions/workflows/ci.yml)

Brain Buddy is a collaborative knowledge-graph workspace that helps product teams capture research trees, validate assumptions with AI guidance, and preserve historical versions of their thinking. It also ships a GTD-style task tracker for turning that thinking into action.

## Highlights
- **Interactive canvas** powered by React Flow with undo/redo, optimistic updates, and large-graph tuning for 200+ nodes.
- **GTD task tracker** with inbox/next/waiting/someday lists, due dates, projects, tags, and voice brain-dump capture that drafts tasks from speech.
- **FastAPI backend** persisting trees on the filesystem with LRU caching and version history snapshots; task data lives in SQLite (`tasks.sqlite3`) under the same data dir.
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

uvicorn app.main:app --reload
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

In dev, Vite proxies `/api` to `http://localhost:8000` so the frontend and backend appear same-origin (required for cookie-based sessions).

### Accounts & invites
Signup is invite-gated. To create an invite:

```bash
# local dev
cd backend && python -m app.cli create-invite

# compose
docker compose exec backend python -m app.cli create-invite
```

Hand the printed code to whoever should sign up. They go to `/signup`, enter their email, a ≥12-character password, and the invite code. See `docs/auth.md` for the security model.

### Autosave & AI Consent
- The canvas autosaves locally every ~5s (debounced) and warns on exit if unsaved changes exist.
- AI feedback requires an explicit consent toggle in the inspector; decline consent to keep data local and receive a validation error instead of sending content.
- Failures return correlation IDs in error toasts so you can retry or report with context.

### Smoke Test via Docker Compose

Prefer containers for manual verification or stakeholder demos? Copy `.env.example` to `.env`, then run:

```bash
docker compose up --build
```

The backend will listen on `http://localhost:8000`, and the frontend will be available at `http://localhost:8080`. When finished, tear everything down with `docker compose down --volumes`. See `docs/deployment_smoke.md` for the full runbook, including optional API key wiring and automated smoke checks.

Looking for a local-first workflow with refresh/troubleshooting steps? See `docs/runbooks/local-deployment.md`.

Auth is cookie-based and invite-gated — mint an invite via `docker compose exec backend python -m app.cli create-invite`, then sign up on `/signup`. The compose smoke test (`scripts/smoke_test.sh`) mints its own throwaway invite and signs up a temporary user automatically.

## Deployment

- **Fly.io**: Follow `docs/fly-deployment.md` for provisioning volumes, wiring secrets, deploying backend and frontend apps, and running curl smoke checks with rollback guidance.
- **Fly.io review apps**: See `docs/fly-review-apps.md` for frontend PR preview deploys and required GitHub secrets.
- **CI before deploys**: GitHub Actions (`.github/workflows/ci.yml`) runs backend lint/type/test + coverage, frontend unit tests + build, and Docker image builds on every push/PR to `main` and on `trunk-candidate/**` refs. Wait for CI to go green (see the badge above) before deploying to Fly.
- **Verified trunk landing**: SHIP/SHOW changes land without a PR — `scripts/submit_to_trunk.sh` pushes one candidate commit to `trunk-candidate/<sha>` and full CI runs there with no write permission (candidate-controlled CI can never promote `main`). The completed successful CI run triggers the default-branch release workflow: its `land` job (read-only token, GitHub `landing` environment) fast-forwards `main` to the exact tested SHA using the dedicated `TRUNK_LANDING_SSH_KEY` SSH deploy key — no workflow holds `GITHUB_TOKEN` write, and the `main` ruleset must keep `restrict_updates` with that deploy key as the only bypass actor — and proves the landing (`origin/main` equals the tested SHA), then its `deploy` job re-verifies that proof before any Fly mutation, runs the authenticated smoke (`scripts/production_smoke.sh`, asserting the `delivery_canary` flag for the internal smoke identity), and rolls back verified on failure. `FLY_API_TOKEN` and the smoke/cohort secrets live only in the GitHub `production` environment (custom `main`-only deployment branch policy; no repository-level `FLY_API_TOKEN`), mirroring the `landing` environment. ASK-class changes (auth/privacy, destructive data/schema, billing credentials, CI/CD/infra, irreversible external effects) never land automatically: a PR carries the review evidence, but it cannot merge while the deploy key is the sole ruleset bypass — landing one requires explicit approval, green exact-SHA CI, and a short audited temporary ruleset intervention. See `docs/decisions/0008-verified-trunk-serial-landing.md` and `docs/autonomous-delivery-runbook.md`.
## Fly.io Deployment (backend)

The backend Fly app is private and only reachable over Flycast from other apps in your organization (no public `fly.dev` address). Use `fly.backend.toml` to deploy the FastAPI service from `backend/Dockerfile` with health checks on `/health` and a volume mounted at `/app/data`.

```bash
# Create or resize the persistent volume
flyctl volumes create brain_buddy_data --size 1 --region iad

# Deploy using the backend config (session auth needs no extra secrets)
flyctl deploy -c fly.backend.toml
```

When pairing the private backend with the public frontend, point the frontend proxy at the Flycast address for your backend app (e.g., `http://<backend-app>.flycast:8000`) via `BACKEND_ORIGIN` in `fly.frontend.toml` or `flyctl secrets set BACKEND_ORIGIN=... -a <frontend-app>`.

## Environment & Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `BRAIN_BUDDY_API_PREFIX` | `/api` | Route prefix for FastAPI routers |
| `BRAIN_BUDDY_DATA_DIR` | `<repo>/backend/data` | Root directory for data storage: tree JSON documents plus the task tracker's `tasks.sqlite3` |
| `VITE_API_BASE_URL` | `/api` | Frontend API base path (proxied in dev) |

See `docs/api_usage.md` for request/response details and examples.

## Testing & Tooling
- Backend: `cd backend && pytest`
- Frontend unit tests: `cd frontend && npm test`
- Spec Kit artifact check: `python3 scripts/check_spec_kit_specs.py` or `make check-specs`
- Linting/formatting: Black, Ruff, and Mypy on the backend; ESLint/Prettier via Vite on the frontend.
- Continuous improvement scripts live in the root `Makefile` (`make test-backend`, `make test-frontend`).

## Feature Specs
GitHub Spec Kit v0.14.2 is the mandatory workflow for new or materially changed
feature specs: constitution → `/speckit-specify` → `/speckit-clarify` →
`/speckit-plan` → bounded read-only planning review → `/speckit-checklist` →
`/speckit-tasks` → `/speckit-analyze` → validated Hermes Kanban handoff. See
`docs/spec-kit-workflow.md` for the exact Claude Code commands, uv/uvx setup,
historical spec grandfathering, and the boundary between Spec Kit planning and
Hermes Kanban execution/review.

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
