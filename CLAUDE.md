# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Targets live in the `Makefile`; per-package scripts in `frontend/package.json`
and `mobile/package.json`. Only the things those files don't tell you:

- `make test-backend` runs pytest locally, then the coverage floor and the
  Allure taxonomy validator. For the bare test loop use `cd backend && pytest`;
  it skips both gates, so run the make target before reporting anything green.
- `make dev-frontend` serves Vite on `localhost:5173`; the compose stack serves
  the frontend on `8080` instead.
- Full frontend Stryker is ~20 min locally (ADR-0013, report-only nightly);
  scope it with `cd frontend && npx stryker run --mutate '<path>'`.
- `cp .env.example .env` before `docker compose up --build`. **`.env.example` is
  the authoritative environment-variable reference** — it documents the voice/STT
  provider, feature-flag, cost-cap and retention variables, not just the basics.
- Mobile has its own notes in `mobile/CLAUDE.md`.
- Spec Kit CLI installs with isolated `uv` tooling, never inside the application
  backend/frontend environments — see the `speckit-pipeline` skill.

Coverage floors live in `frontend/coverage-floor.json` and may only ratchet
upward. There is no per-file escape hatch: `scripts/validate_ci_artifacts.py
coverage-suppressions` rejects `istanbul ignore file` and every range form in
`frontend/src` and `mobile/src`, because an excluded file is reported as neither
covered nor uncovered — it silently leaves the measurement.

## Spec Kit and the delivery pipeline

Use GitHub Spec Kit v0.15.0 for every new or materially changed feature spec.
The stage-by-stage chain, its human gates and the `assess` front door are in the
**`speckit-pipeline`** skill. Read `docs/spec-kit-workflow.md` before authoring
specs; versioned artifacts live under `specs/`.

Non-negotiables, whether or not that skill is loaded:

- `/verify-live` is **approval-gated and spends real provider money** — never run
  it unattended, from a subagent, or from a scheduled session. `/self-verify`
  (free, deterministic, `make verify-all`) is the everyday equivalent.
- Tests carry the feature-qualified requirement id (`006-FR-001`, or
  `006_FR_001` in a Python name) so `scripts/check_requirement_coverage.py` can
  trace them; a bare `FR-001` is rejected because every feature restarts at 001.
- The interview cannot be a subagent: `AskUserQuestion` is stripped from every
  subagent, so human elicitation must run in the main session.
- The `architecture-consistency-reviewer`, `security-privacy-reviewer` and
  `ux-a11y-reviewer` agent files under `.claude/agents/` are the **single source
  of rubric truth** for their lenses — `spec_kit_planning_review.py` points at
  them rather than restating the rubric. Only the rubric body is used: the
  reviewers run as headless `claude -p` processes, so the agents' `model:` and
  `tools:` frontmatter is inert and `ROLE_CONFIGS` decides both.
- Feature numbers are reserved across every git ref, not just the checked-out
  `specs/` tree — two branches claiming one `NNN-` merge without a conflict and
  then satisfy each other's requirement-coverage gate. `check_spec_kit_specs.py`
  rejects duplicates; `create-new-feature.sh` avoids creating them.
- `/speckit-implement` is a preserved override guarded by
  `scripts/check_speckit_manifests.py`; `specify integration upgrade --force`
  must not revert it.
- Do not assume Hermes or a Kanban runtime is present. If Claude Code is
  explicitly launched inside an opt-in Hermes-managed outcome, the invoking task
  supplies the additional signed scope and `docs/spec-driven-kanban.md` becomes
  authoritative for that managed run only.

## Architecture

The backend is layered `app/api/` → `app/services/` → `app/repositories/`, wired
in `app/container.py`. **All routes receive services via FastAPI `Depends()`;
never instantiate services directly in route handlers.**

### Cross-cutting behavior

- **Session auth** — users sign in with email + password; the backend sets an opaque session token in an `HttpOnly`, `SameSite=Lax`, `Secure`-in-prod cookie. Every `/api/trees/*`, `/api/tasks`, `/api/projects`, `/api/tags`, and `/api/brain-dump-operations` route requires the cookie and enforces per-owner filtering. Signup is gated by an invite code minted via `python -m app.cli create-invite`. See `docs/auth.md`.
- **Same-origin fetch** — the frontend hits the backend via `/api` on the same origin. In production the Fly frontend app proxies. In dev, Vite proxies `/api` and `/health` to `http://localhost:8000`. This keeps cookies usable and eliminates CORS.
- **AI consent gating** — AI validation requires an explicit consent toggle in the inspector. Declining consent short-circuits with a validation error rather than calling the provider.
- **GDPR account management** — `AccountService` (profile/email/password, ZIP data export, 14-day-grace deletion + purge) is **always on and must never be feature-flagged**. See `docs/data-retention.md`.
- **Task module commands** — `app/modules/tasks/` commands are idempotent and owner-serialized; preserve both properties when adding operations.
- **Correlation IDs** — every response carries `X-Correlation-ID`. Error toasts surface it for retry/report flows, and backend logs key off the same ID.
- **Autosave** — the canvas debounces a 5s local autosave to `localStorage` and warns on page exit when unsaved changes exist.

## Deployment & CI

Wait for CI green before deploying. The CI job graph and the rules governing
which edges are allowed, the backend mutation-gate thresholds, and the Fly.io
topology are in the **`deploy-and-ci`** skill. Architecture, API, troubleshooting,
performance and infra runbooks live under `docs/`.

## Conventions

- **Commits:** conventional prefix style — `feat:`, `fix:`, `docs:`, `refactor:`, etc.
- **Style:** enforced mechanically by `.pre-commit-config.yaml` and CI (black, ruff, mypy, import-linter, eslint, tsc). Read `backend/pyproject.toml` for the active ruff rule set and complexity ceilings rather than assuming a subset.
- **Backend tests:** mirror module name (`test_tree_service.py`); use the `api_client` / service fixtures from `conftest.py`; clear `TreeService`'s 16-entry LRU cache between tests.
- **Frontend tests:** Vitest + Testing Library in `src/**/__tests__/`; Playwright e2e in `frontend/tests/`.
- **Allure taxonomy:** every pytest, Vitest, Jest and Playwright product test must emit non-empty `epic`, `feature`, `story`, a human-readable title, and at least one named step. Central defaults live in `backend/tests/allure_taxonomy.py`, `frontend/src/test/allureTaxonomy.ts`, `mobile/src/test/allureTaxonomy.ts`, and `frontend/tests/allure.fixtures.ts`; use explicit Allure decorators/helpers only for narrower overrides. See `docs/test-allure-taxonomy.md`.
  Mobile is the one runner whose steps cannot come from a hook: in `allure-jest` a step follows the executing scope, and during `beforeEach`/`afterEach` that scope is the fixture, not the test. Labels bind from a hook, the step does not — so `mobile/src/test/allureTaxonomy.ts` sets the labels in `beforeEach` and wraps each test body in a step instead.
