---
name: deploy-and-ci
description: BrainBuddy CI job-graph rules, the backend mutation gate thresholds, and the Fly.io deployment topology. Use when editing .github/workflows, debugging a CI failure, changing the mutation-enforced scope, or deploying to Fly.
---

# Deployment and CI

Wait for CI green before deploying.

## Local full stack

Docker Compose: `docker compose up --build` → backend `:8000`, frontend `:8080`.
Smoke via `./scripts/smoke_test.sh`. `docker compose down --volumes` to reset.

## Fly.io

Two apps via `fly.backend.toml` and `fly.frontend.toml`. The **backend app is
private (Flycast-only)**; the frontend proxies to it via `BACKEND_ORIGIN`.
Runbooks: `docs/fly-deployment.md`, `docs/fly-review-apps.md`.

## The CI job graph

`.github/workflows/ci.yml` runs as parallel lanes joined only by `full-ci`: one
per service (`backend`, `frontend` — each its own
lint/type/unit/integration — and the native app's `ios-kit` and `ios-app`, all
path filtered by the `changes` job), plus `workflow-lint`, `spec-kit`, the
mutation gate, `docker` and `e2e`. `ios.yml` only uploads to TestFlight, after
CI has passed on `main`.

An edge earns its place for one of three reasons only:

1. the job consumes the other's output;
2. the other is a cheap check that should fail the run before an expensive one
   spends runner minutes (`e2e` and the mutation jobs wait on the service lanes
   for this);
3. the two build byte-identical artifacts and ordering them lets the second
   reuse the first's cache (`docker` waits on `e2e` for this, turning a
   duplicated cold build into a ~20s cache hit).

`scripts/validate_ci_artifacts.py workflow` rejects any other edge — including a
transitive one restated — and rejects a job missing from `full-ci`'s `needs`
(with a flat graph that gate is the only thing making a job required).

`e2e` is never path filtered. It rebuilds only what changed: `main`'s Docker
layers are reused via the shared `stack-*` buildx cache, so an untouched service
starts from main's image.

Inside the `backend` lane a pull request runs only the tests a test-impact
map has on record for the files it changed. Every push to `main` records the
map (`--cov-context=test`) into the Actions cache;
`scripts/select_backend_tests.py select` narrows the run for edits inside
function bodies, imports and signatures of measured `app/*.py` files, and for
`rust/` changes through the `bb_core` bridge, and answers `ALL` for anything
else. A narrowed run skips the coverage floor, which the landing path still
enforces on the whole suite.

`allure-report` closes the run — it is the last job before `full-ci`, so the
aggregate report and the link posted to the pull request always describe a
finished run.

## Mutation gate

The `mutation-gate` job blocks a change that touches any module in
`backend/mutation-enforced-scope.txt` (the ADR-0016 *enforced* tier: the
tree/version/relation services and their repositories). It measures only the
entries you touched and fails below 95%, on zero checked mutants, or on any
regression against the base revision. Touch none of them and it costs nothing.
Reproduce locally with `make mutation-gate-backend`.

The nightly `mutation-quality.yml` stays report-only over the wider *observed*
tier. Frontend Stryker (ADR-0013) is report-only nightly, ~20 min locally.
