# Fly.io Frontend Review Apps

This repo currently ships a GitHub Actions workflow that deploys a frontend preview app on
every same-repository pull request and destroys it when the PR closes. This is legacy
behavior, not the approved target policy. [ADR-0003](decisions/0003-autonomous-delivery-guardrails.md)
and the [autonomous delivery runbook](autonomous-delivery-runbook.md) require the explicit
`preview:visual` label, visual-path eligibility, one-preview-per-PR race controls, auditable
URL reporting, and guarded cleanup before this automation is conformant.

Do not use direct `flyctl` commands to work around the policy. Workflow remediation belongs
in a separate reviewed implementation PR.

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

## Notes
- The workflow skips forks because Fly secrets are not available to them.
- If `FLY_REVIEW_BACKEND_ORIGIN` is unset, the workflow uses the `BACKEND_ORIGIN` value in `fly.frontend.toml`.
