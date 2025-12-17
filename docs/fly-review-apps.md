# Fly.io Frontend Review Apps

This repo ships a GitHub Actions workflow that deploys a frontend preview app on every pull request and destroys it when the PR closes.

## Workflow
- **Workflow:** `.github/workflows/fly-review-frontend.yml`
- **Trigger:** pull requests opened, synchronized, reopened, and closed
- **App name format:** `<FLY_APP_PREFIX>-<PR number>`
- **Review URL:** `https://<app-name>.fly.dev`

## Required GitHub Secrets
Add these secrets in the repository settings before using review apps:

| Secret | Purpose |
| --- | --- |
| `FLY_API_TOKEN` | Fly API token with deploy permissions (`flyctl auth token`) |
| `FLY_ORG` | Fly organization slug used to create apps |

## Optional GitHub Secrets

| Secret | Purpose |
| --- | --- |
| `FLY_APP_PREFIX` | Prefix for review apps (default: `brain-buddy-frontend-pr`) |
| `FLY_REVIEW_BACKEND_ORIGIN` | Backend origin for the Nginx proxy (e.g., `http://<backend-app>.flycast:8000`) |
| `VITE_API_KEY` | API key injected at build time if the backend requires it |
| `VITE_API_KEY_HEADER` | Header name for the API key (default from `fly.frontend.toml`) |

## Notes
- The workflow skips forks because Fly secrets are not available to them.
- If `FLY_REVIEW_BACKEND_ORIGIN` is unset, the workflow uses the `BACKEND_ORIGIN` value in `fly.frontend.toml`.
