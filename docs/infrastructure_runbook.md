# Infrastructure Runbook

This runbook covers how to deploy, operate, and recover the Brain Buddy stack as we onboard the pilot program. It complements `docs/deployment_smoke.md`, which focuses on local smoke testing.

## Environments

- **Development** – engineers run services via `make dev-backend` and `make dev-frontend`. Data persists under `backend/data/`.
- **Pilot (Compose)** – the reference environment brought up with `docker-compose.smoke.yml`. The backend container mounts a named Docker volume for persistence.
- **CI** – GitHub Actions workflow `CI` runs on every push / PR to `main`, executing linting, tests, coverage, and Docker builds.

All environments draw configuration from `.env.example`. Copy it to `.env` for compose deployments and keep real API keys in your secret manager.

## Deploy the Pilot Stack

1. **Configure environment**
   - Copy `.env.example` to `.env`.
   - Set `BRAIN_BUDDY_API_KEY` and `VITE_API_KEY` if pilot access should be gated.
   - Adjust `VITE_API_BASE_URL` if the frontend will proxy through another host.
2. **Build & start containers**
   ```bash
   make compose-smoke-up
   ```
   This runs `docker compose -f docker-compose.smoke.yml up --build`, producing backend and frontend images from the repo Dockerfiles.
3. **Load pilot dataset (optional but recommended)**
   ```bash
   python scripts/load_dataset.py docs/pilot_dataset.json --data-dir backend/data
   ```
   For remote hosts, point `--data-dir` at the mounted volume path (e.g. `/var/lib/docker/volumes/brain-buddy_backend-data/_data`).
4. **Run smoke test**
   ```bash
   scripts/smoke_test.sh
   ```
   Confirm all requests succeed before inviting pilot users.

## Updating & Rolling Back

1. Stop the stack:
   ```bash
   make compose-smoke-down
   ```
2. Pull the desired Git commit and rebuild images with `make compose-smoke-up`.
3. To revert to a clean state, remove the data volume:
   ```bash
   docker volume rm brain-buddy_backend-data
   ```
   Reload the pilot dataset afterwards if needed.

## Monitoring & Observability

- `/health` is exposed without auth and wired into the compose health check.
- Every response includes `X-Correlation-ID`; use it to correlate frontend errors with backend logs.
- `useGraphProfiler` logs `[perf] TreeCanvas` messages (dev mode) when rendering large graphs—watch for regressions beyond 20 ms.
- CI uploads coverage artifacts (`backend-coverage`, `frontend-coverage`) on each run; inspect them when planning releases.

## Operational Tips

- Keep `.env` under source control only as the template; real secrets should be injected at runtime.
- Prefer rebuilding images over editing files inside containers to maintain reproducibility.
- If API latency rises, inspect backend logs for cache churn and consider raising `TREE_CACHE_MAXSIZE` via environment variable.

