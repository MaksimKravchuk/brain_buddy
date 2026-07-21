# Fly.io Frontend Review Apps

The frontend review-app workflow follows
[ADR-0003](decisions/0003-autonomous-delivery-guardrails.md) and the
[autonomous delivery runbook](autonomous-delivery-runbook.md). A preview is opt-in: an open,
same-repository PR targeting `main` must have the explicit `preview:visual` label and an
eligible rendered frontend change. Backend-only, docs-only, CI-only, spec-only, and test-only
changes do not qualify.

Each PR has one stable Fly app. Per-PR concurrency cancels superseded deployments, the
workflow re-verifies the live PR head immediately before mutation, runs a frontend build and
post-deploy smoke check, and upserts one auditable PR comment. Removing `preview:visual` or
closing the PR performs fail-closed cleanup of only that derived preview app.

Do not use direct `flyctl` commands to work around this policy.

## Workflow
- **Workflow:** `.github/workflows/fly-review-frontend.yml`
- **Deploy trigger:** `preview:visual` added, or a labeled PR opened, synchronized, or reopened
- **Cleanup trigger:** `preview:visual` removed or the PR closed
- **App name format:** `<FLY_APP_PREFIX>-<PR number>`
- **Review URL:** `https://<app-name>.fly.dev`

## Required GitHub Secrets
Add these secrets in the repository settings before using review apps:

| Secret | Purpose |
| --- | --- |
| `FLY_PREVIEW_API_TOKEN` | Preview-only Fly API token with deploy/destroy permissions |
| `FLY_ORG` | Fly organization slug used to create apps |

## Optional GitHub Secrets

| Secret | Purpose |
| --- | --- |
| `FLY_APP_PREFIX` | Prefix for review apps (default: `brain-buddy-frontend-pr`) |
| `FLY_REVIEW_BACKEND_ORIGIN` | Backend origin for the Nginx proxy (e.g., `http://<backend-app>.flycast:8000`) |

## Notes
- The workflow skips forks because Fly secrets are not available to them.
- If `FLY_REVIEW_BACKEND_ORIGIN` is unset, the workflow uses the `BACKEND_ORIGIN` value in `fly.frontend.toml`.
- Production app names are explicitly rejected before create, deploy, or cleanup.
