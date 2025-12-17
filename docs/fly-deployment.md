# Fly.io Deployment Runbook

Deploy the Brain Buddy backend and frontend as separate Fly.io apps. The backend is private and reachable only over Flycast from apps in the same organization; the frontend remains public and proxies `/api` requests to the private backend. The steps below cover prerequisites, persistent storage, secret wiring, deployment, validation, and rollback.

## Prerequisites
- Install the Fly CLI (`flyctl`) from https://fly.io/docs/hands-on/install/ and run `flyctl auth login`.
- Ensure Docker is available locally or enable Fly's remote builder (`flyctl deploy --remote-only`).
- Decide on two app names: one for the backend API and one for the frontend (e.g., `brain-buddy-api` and `brain-buddy-web`).
- Confirm the GitHub Actions CI workflow is green before deploying (see "CI guardrails" below) so the images you ship match what was tested.

## CI guardrails
- **Workflow location:** `.github/workflows/ci.yml` runs on pushes/PRs to `main`. It lints and type-checks the backend (Ruff + mypy), runs backend pytest with coverage, executes frontend unit tests with coverage, builds the frontend bundle, and performs Docker image builds for both services.
- **Run locally:** `make test-backend` and `make test-frontend` mirror the CI steps. Optionally, `docker compose build` validates the Dockerfiles locally.
- **Deploy only after green:** Wait for the CI badge in the README or the Actions tab to go green. If CI is red, fix the failures locally before running any Fly deploys.

## Backend setup (API)
1. **Create the app (once):**
   ```bash
   flyctl apps create <backend-app>
   ```
2. **Provision persistent storage for tree data:**
   ```bash
   flyctl volumes create brain-buddy-data \
     --size 1 \
     --region <fly-region> \
     -a <backend-app>
   ```
   Mount the volume at `/app/data` (the backend's default data path) in your `fly.toml`:
   ```toml
   [mounts]
   source="brain-buddy-data"
   destination="/app/data"
   ```
3. **Configure secrets:** set any API key protection and optional prefix overrides **before** the first deploy.
   ```bash
   flyctl secrets set \
     BRAIN_BUDDY_API_KEY=<optional-static-key> \
     BRAIN_BUDDY_API_KEY_HEADER=X-API-Key \
     BRAIN_BUDDY_API_PREFIX=/api \
     -a <backend-app>
   ```

## Deploy the backend
Run the deployment from the repository root so the Dockerfile path resolves correctly. The resulting app has no public `fly.dev` hostname; it listens on `http://<backend-app>.flycast:8000` for in-organization callers such as the frontend.
```bash
flyctl deploy \
  --dockerfile backend/Dockerfile \
  --app <backend-app> \
  --remote-only
```
When prompted for a volume, select `brain-buddy-data` to mount at `/app/data`.

## Deploy the frontend
1. **Create the app (once):**
   ```bash
   flyctl apps create <frontend-app>
   ```
2. **Point the client at the backend (Flycast) and forward API key settings (if any):**
   ```bash
   flyctl secrets set \
     BACKEND_ORIGIN="http://<backend-app>.flycast:8000" \
     VITE_API_BASE_URL="/api" \
     VITE_API_KEY=<optional-static-key> \
     VITE_API_KEY_HEADER=X-API-Key \
     -a <frontend-app>
   ```
3. **Deploy:**
  ```bash
  flyctl deploy \
    --dockerfile frontend/Dockerfile \
    --app <frontend-app> \
    --remote-only
  ```

## Smoke verification
- **Backend health (via Fly SSH into the private app):**
  ```bash
  flyctl ssh console -a <backend-app> -C "curl -f http://127.0.0.1:8000/health"
  ```
- **Frontend reachability and backend wiring:**
  ```bash
  curl -I https://<frontend-app>.fly.dev
  curl -f "https://<frontend-app>.fly.dev/api/health"  # proxied to backend via Flycast
  ```
  Expect an HTTP 200 from Nginx and the compiled React bundle. Open the URL in a browser to confirm the canvas loads and can fetch data from the private backend.

## Rollback guidance
- List recent releases for either app:
  ```bash
  flyctl releases -a <app-name>
  ```
- Revert to a previous release number if needed:
  ```bash
  flyctl release revert <release-version> -a <app-name>
  ```
  After a rollback, re-run the smoke checks above to confirm the restored version is healthy.
