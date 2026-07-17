# Fly.io Deployment Runbook

> **Production release policy:** [ADR-0003](decisions/0003-autonomous-delivery-guardrails.md)
> requires production deployment only through the reviewed PR -> green CI -> merge to
> `main` -> successful `main` CI -> production workflow path. The setup commands below are
> bootstrap/reference material, not authority for an agent or operator to perform an ad-hoc
> production deploy. Follow the
> [autonomous delivery runbook](autonomous-delivery-runbook.md) for release, incident, and
> rollback controls.

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
2. **Provision persistent storage for tree and task data:**
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
3. **Configure secrets:** session auth needs no signing secret, but you almost certainly want to seed your own admin account so you can sign in without SSHing in to mint an invite.
   ```bash
   flyctl secrets set \
     BRAIN_BUDDY_ADMIN_EMAIL=you@yourdomain.com \
     BRAIN_BUDDY_ADMIN_PASSWORD='<a-long-random-password>' \
     BRAIN_BUDDY_API_PREFIX=/api \
     -a <backend-app>
   ```
   On startup the backend will create that account (or rotate its password to match the env var if it already exists). Rotate later by updating the secret and redeploying. See `docs/auth.md` for the full model.

## Data storage, backups, and seeding
The data directory (`BRAIN_BUDDY_DATA_DIR`, mounted at `/app/data` in production) holds two distinct stores:

- **Trees** — one JSON file per tree plus an index file. Tree version snapshots, export/import, and `scripts/load_dataset.py` operate on these JSON files only.
- **Tasks, projects, tags, and brain-dump operations** — a single SQLite database, `tasks.sqlite3`, managed by the task module (`backend/app/modules/tasks/repository.py`).

`tasks.sqlite3` is **not** covered by tree JSON snapshots, tree export/import, or `scripts/load_dataset.py`. Any backup, restore, or seeding procedure that copies tree JSON files must also include `tasks.sqlite3` (plus its `-wal`/`-shm` sidecar files when copying a live database), or all task-tracker data is silently dropped. Prefer backing up the entire data directory — e.g. a Fly volume snapshot (`flyctl volumes snapshots create <volume-id> -a <backend-app>`) or copying the whole mount via `flyctl ssh sftp` — over cherry-picking individual files.

## Bootstrap/reference: deploy the backend
Run the deployment from the repository root so the Dockerfile path resolves correctly. The resulting app has no public `fly.dev` hostname; it listens on `http://<backend-app>.flycast:8000` for in-organization callers such as the frontend.
```bash
flyctl deploy \
  --dockerfile backend/Dockerfile \
  --app <backend-app> \
  --remote-only
```
When prompted for a volume, select `brain-buddy-data` to mount at `/app/data`.

## Bootstrap/reference: deploy the frontend
1. **Create the app (once):**
   ```bash
   flyctl apps create <frontend-app>
   ```
2. **Point the client at the backend (Flycast):**
   ```bash
   flyctl secrets set \
     BACKEND_ORIGIN="http://<backend-app>.flycast:8000" \
     VITE_API_BASE_URL="/api" \
     -a <frontend-app>
   ```
   The frontend proxies `/api/*` requests (including `Cookie` and `Set-Cookie` headers) to the private backend, preserving the session cookie end-to-end.
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
- **Mint an invite for yourself:**
  ```bash
  flyctl ssh console -a <backend-app> -C "python -m app.cli create-invite"
  ```
- **Frontend reachability and backend wiring:**
  ```bash
  curl -I https://<frontend-app>.fly.dev
  curl -f "https://<frontend-app>.fly.dev/api/health"  # proxied to backend via Flycast
  ```
  Expect an HTTP 200 from Nginx. Open the URL in a browser, sign up with your invite on `/signup`, and confirm the canvas loads after authentication.

## Rollback guidance
- For normal changes, use a reviewed revert PR and the standard `main` release path. Use a
  Fly release revert only to contain an active incident under explicit, exact-target human
  authority, then reconcile `main` immediately. See the autonomous delivery runbook.
- List recent releases for either app:
  ```bash
  flyctl releases -a <app-name>
  ```
- Revert to a previous release number if needed:
  ```bash
  flyctl release revert <release-version> -a <app-name>
  ```
  After a rollback, re-run the smoke checks above to confirm the restored version is healthy.
