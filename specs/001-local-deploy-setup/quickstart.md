# Quickstart: Local Deployment Setup

1) **Install prerequisites**: Docker/Compose, Node (per package.json engines), Python 3.11.
2) **Configure env**: Copy `.env.example` → `.env`; fill required values (API key optional as documented); ensure ports 5173/3000/8000 are free or adjust in env/compose overrides.
3) **Initial deploy**: Run `docker compose up --build` to start backend + frontend from the current branch; wait for services to report healthy.
4) **Validate**: Hit backend health/smoke (`./scripts/smoke_test.sh`) and load frontend URL; confirm data volume mounted and responses succeed.
5) **Refresh after changes**: Pull/apply code changes, run `docker compose up --build --detach` (or restart dev servers via `make dev-backend` / `make dev-frontend`), then rerun validation; target under 5 minutes.
6) **Recover**: If failures occur, consult troubleshooting steps for env mismatches, port conflicts, or stale volumes/caches; reset and retry.
