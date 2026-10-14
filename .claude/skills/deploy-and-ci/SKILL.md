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
lint/type/unit/integration — the native apps' `ios-kit`, `ios-app` and
`macos-app`, the `rust` core and the five `cli-native` targets, all path
filtered by the `changes` job), plus `workflow-lint`, `spec-kit`, the
mutation gate, `docker` and `e2e`. A filtered lane still runs and skips its
steps, so `full-ci` never sees "skipped"; a macOS or Windows lane with nothing
to do takes the Linux no-op runner. Only `.github/`, `scripts/` and the
`Makefile` widen a pull request to every lane; `compose.yaml` is exercised by
`e2e` alone. Landing pushes always run everything. `ios.yml` only uploads to TestFlight, after
CI has passed on `main`.

An edge earns its place for one of three reasons only:

1. the job consumes the other's output;
2. the other is a *genuinely* cheap check that should fail the run before an
   expensive one spends runner minutes;
3. the two build byte-identical artifacts and ordering them lets the second
   reuse the first's cache.

Wall clock wins ties: `e2e`, `docker` and the mutation measurements are
independent lanes. Each used to wait (on the ~20-minute backend lane, or on
`e2e`), which made the critical path backend → E2E → Docker → Allure, about 37
minutes. A red unit test still fails the run; mutmut stops on a failing clean
suite by itself.

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
enforces on the whole suite. Whatever runs is spread over every core with
`pytest -n auto --dist loadgroup`; a module bound to a fixed port carries
`pytest.mark.xdist_group` so it stays on one worker, and `tests/__init__.py`
gives each worker its own data directory.

The Swift lanes (`ios-kit`, `ios-app`, `macos-app`) cache the built Rust bridge
under the git tree id of `rust/`, the build script, the target list and the
linking toolchain, so it rebuilds only when one of those changes.

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
