# Fly.io Deployment Runbook

Deploy the Brain Buddy backend and frontend as separate Fly.io apps. The steps below cover prerequisites, persistent storage, secret wiring, deployment, validation, and rollback.

## Prerequisites
- Install the Fly CLI (`flyctl`) from https://fly.io/docs/hands-on/install/ and run `flyctl auth login`.
- Ensure Docker is available locally or enable Fly's remote builder (`flyctl deploy --remote-only`).
- Decide on two app names: one for the backend API and one for the frontend (e.g., `brain-buddy-api` and `brain-buddy-web`).

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
Run the deployment from the repository root so the Dockerfile path resolves correctly:
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
2. **Point the client at the backend and forward API key settings (if any):**
   ```bash
  flyctl secrets set \
    VITE_API_BASE_URL="https://<backend-app>.fly.dev/api" \
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
- **Backend health:**
  ```bash
  curl -f https://<backend-app>.fly.dev/health
  ```
- **Backend API prefix check (optional):**
  ```bash
  curl -f https://<backend-app>.fly.dev/api/trees
  ```
- **Frontend reachability and backend wiring:**
  ```bash
  curl -I https://<frontend-app>.fly.dev
  curl -f "https://<frontend-app>.fly.dev/api/health"  # proxied to backend via VITE_API_BASE_URL
  ```
  Expect an HTTP 200 from Nginx and the compiled React bundle. Open the URL in a browser to confirm the canvas loads and can fetch data from the backend.

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
