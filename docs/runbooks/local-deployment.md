# Local Deployment Runbook

Covers end-to-end local deployment for Brain Buddy using the compose smoke stack and dev server shortcuts. Targets: initial setup under 15 minutes; refresh after code changes under 5 minutes.

## Prerequisites

- Docker Desktop or Docker Engine + Compose v2
- Node.js (per `frontend/package.json` engines) and npm
- Python 3.11
- Network: ports 8000 (backend), 8080 (frontend), 5173/3000 (dev servers) available or remapped

## Environment Setup

1) Copy `.env.example` → `.env` at repo root. Keep real secrets out of this file; optional API key is commented out.
2) Required variables (safe defaults provided):
   - `BRAIN_BUDDY_ENV`, `BRAIN_BUDDY_PORT`, `BRAIN_BUDDY_DATA_DIR`
   - `BRAIN_BUDDY_API_PREFIX`, `BRAIN_BUDDY_API_KEY_HEADER`, optional `BRAIN_BUDDY_API_KEY`
   - `VITE_API_BASE_URL`, `VITE_API_KEY`, `VITE_API_KEY_HEADER`, `FRONTEND_PORT`
   - Host helpers: `API_BASE_URL`, `API_PREFIX`, `COMPOSE_PROJECT_NAME`
3) If a port is in use, adjust the value in `.env` and update compose overrides accordingly.

## Quickstart: Initial Deploy (MVP)

1) `docker compose up --build` (builds from your current branch checkout).
2) Wait for backend healthcheck to pass; frontend depends_on backend.
3) Validate health:
   - Backend: `./scripts/smoke_test.sh` (runs against localhost:8000 via API_PREFIX)
   - Frontend: open http://localhost:8080 and confirm app renders.
4) Verification checklist (pass all):
   - Backend health endpoint returns 200
   - Smoke script exits 0
   - Frontend serves current branch assets
   - Volume `backend-data` is attached (see `docker volume ls`)

## Refresh Workflow (after code changes)

1) Pull or apply code changes on current branch.
2) Restart stack with current code: `docker compose up --build --detach`.
   - This reuses Docker layer cache; keep prior images to stay under the 5-minute budget.
   - Faster iteration: `make dev-backend` and `make dev-frontend` in separate shells if you prefer hot reload (uses local host ports 8000/5173).
   - No manual file copying required; the stack runs from your checked-out branch.
3) Re-run validation:
   - `./scripts/smoke_test.sh`
   - Load http://localhost:8080 (or dev server URL) to confirm updated UI/API.
4) Time budget: aim <5 minutes from pull to healthy stack. If exceeded, review caching and rebuild steps below.

## Port & Resource Matrix

- Backend: host `8000` → container `8000`
- Frontend (compose): host `8080` → container `80`
- Frontend (dev server): host `5173`
- Optional alt frontend host `3000` if 5173 occupied
- Volume: `backend-data` mounted at `/app/data`

## Troubleshooting & Recovery

### Port conflicts (US3)
- Check conflicts: `lsof -i :8000` or `lsof -i :8080`
- Resolve: stop conflicting service or change port in `.env` and rerun compose

### Stale volumes / caches (US3)
- Reset stack: `docker compose down --volumes`
- Clear node cache (optional): `npm cache clean --force`
- Rebuild: `docker compose up --build`

### Env mismatches or failed start (US3)
- Inspect logs: `docker compose logs backend` / `frontend`
- Confirm `.env` values match required list above; ensure `BRAIN_BUDDY_API_PREFIX` aligns with `VITE_API_BASE_URL`
- If API key enforced, set both `BRAIN_BUDDY_API_KEY` and `VITE_API_KEY`

### Recovery checklist
- Compose stack up and healthy
- Smoke script passes
- Frontend reachable and serving current branch
- No unresolved port conflicts; volumes recreated if needed

### Timing log
- Initial setup target: <15 minutes. Record actual duration after first run.
- Refresh target: <5 minutes from pull to healthy stack. Record actual duration after refresh.

## Appendix: Commands Reference

- Start stack: `docker compose up --build`
- Stop stack and clean volumes: `docker compose down --volumes`
- Logs: `docker compose logs -f`
- Dev servers: `make dev-backend` (uvicorn reload), `make dev-frontend` (Vite)
