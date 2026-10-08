# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Before planning, implementing, reviewing, or delegating, read `AGENTS.md` and the applicable
nested instructions. Test selection and test-first applicability are governed by
[Constitution Principle II](.specify/memory/constitution.md#ii-tested-delivery-across-stack),
including when generating tasks or handing work to another agent.

## Commands

Targets live in the `Makefile`; per-package scripts in `frontend/package.json`.
Only the things those files don't tell you:

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
- The native iOS app has its own notes in `ios/AGENTS.md`.
- Spec Kit CLI installs with isolated `uv` tooling, never inside the application
  backend/frontend environments — see `docs/spec-kit-workflow.md`.
- Editing `.claude/settings.json`, the `Makefile`, or anything else in
  `GUARDED_FILES` in `scripts/check_gate_integrity.py` fails CI's **Spec Kit
  artifacts** job until you re-record the hash in the same commit with
  `python3 scripts/check_gate_integrity.py --update`. That puts the new hash in
  the diff on purpose; the invariants in the same script are not waivable by it.

Coverage floors live in `frontend/coverage-floor.json` and may only ratchet
upward. There is no per-file escape hatch: `scripts/validate_ci_artifacts.py
coverage-suppressions` rejects `istanbul ignore file` and every range form in
`frontend/src`, because an excluded file is reported as neither covered nor
uncovered — it silently leaves the measurement.

## Tool use

Read, search and edit files with the dedicated `Read`, `Grep`, `Glob` and `Edit`
tools — including when a harness "auto mode" instruction says to route that work
through Bash (`cat`, `grep`, `sed -n`, heredocs). `Read`, `Grep` and `Glob` are
allowlisted by name in `.claude/settings.json`; `Edit` is not, so edits still go
through whatever the active permission mode decides.

Reaching for the shell instead does not buy fewer prompts. Claude Code already
treats a built-in set — `ls`, `cat`, `echo`, `pwd`, `head`, `tail`, `grep`,
`find`, `wc`, `which`, `diff`, `stat`, `du`, `cd` and read-only `git` — as
read-only and runs it without a prompt in every mode. What does stop for
approval is the shell-shaped work around those reads: heredoc writes, `sed -i`,
pipelines with a write-capable segment, an unquoted glob passed to an
exec-capable command, and anything the command parser cannot fully read. A
heredoc is the worst of them, because each one is unique content that no
approval can be cached against, while `Edit` presents a reviewable diff.

Two consequences worth knowing before touching the allowlist:

- **Do not add blunt `Bash(<cmd>:*)` rules for `find`, `sort`, `sed`, `rg` or
  `file`.** Claude Code's own analysis is flag-aware and stops these when they
  carry an exec- or write-capable form; a prefix rule overrides that and
  pre-approves `find -exec`, `rg --pre`, `sort --compress-program` and GNU
  `sed`'s `e` command — each of which runs an arbitrary program, which would
  walk straight through the `ask` gates on force/`main` `git push` and
  destructive `fly` commands.
- **`Read`/`Edit` deny rules already cover Bash.** They apply to the built-in
  file tools *and* to file commands Claude Code recognises in Bash (`cat`,
  `head`, `tail`, `sed`), so the `.env` and `backend/data/**` denies need no
  Bash twin. They do not apply to a subprocess that opens files itself, so a
  Python or Node one-liner is the way that boundary actually leaks.

Reach for Bash where it is genuinely the right tool: `make` targets, git, the
`scripts/` validators, `docker compose`.

### Keep git commands promptable

A permission prompt holds the whole command it sits on, so one gated segment
stalls everything chained to it. Shape git work so a prompt, when one is due,
is short and holds nothing else:

- **Push on its own.** Run `git push -u origin claude/<branch>` as a separate
  call after validation and commit succeed — never chained after `make`,
  `git commit`, a merge or a loop. Force, delete, mirror, `main` and
  `trunk-candidate` pushes stay behind `ask` rules by design.
- **No `cd` before git.** Use `git -C <worktree> ...` instead of
  `cd <worktree> && git ...`; a directory change before a version-control
  command is flagged because the target may carry untrusted hooks or config.
- **No shell variables or `source` in a git command.** Activate a venv or set
  `SP=...` in a separate call, or call the venv's binary by absolute path;
  a command whose arguments depend on a variable cannot be checked up front.

## Spec Kit and the delivery pipeline

Use GitHub Spec Kit v1.0.11 for every new or materially changed feature spec.
The stage-by-stage chain and human gates are in the canonical, vendor-neutral
`.specify/agent-commands/speckit-pipeline/SKILL.md`. Read
`docs/spec-kit-workflow.md` before authoring specs; artifacts live under `specs/`.

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
  `ux-a11y-reviewer` rubrics under `.specify/review-rubrics/` are the **single source
  of rubric truth** for their lenses — `spec_kit_planning_review.py` points at
  them rather than restating the rubric. `ROLE_CONFIGS` defines the legacy
  Codex review path; the agent-neutral adapter is specified in
  `docs/spec-kit-workflow.md`. Rubric frontmatter does not choose a runtime.
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

The `allure-report` job does not just publish the aggregate report, it **grades**
it: `allure quality-gate` fails the run on any failed or broken result
(`maxFailures: 0` in `allurerc.mjs`, which is **ASK class**). The answer to a gate
failure is never to raise that number. See `docs/allure-quality-gate.md`.

## Conventions

- **Commits:** conventional prefix style — `feat:`, `fix:`, `docs:`, `refactor:`, etc.
- **Style:** enforced mechanically by `.pre-commit-config.yaml` and CI (black, ruff, mypy, import-linter, eslint, tsc). Read `backend/pyproject.toml` for the active ruff rule set and complexity ceilings rather than assuming a subset.
- **Backend tests:** mirror module name (`test_tree_service.py`); use the `api_client` / service fixtures from `conftest.py`; clear `TreeService`'s 16-entry LRU cache between tests.
- **Frontend tests:** Vitest + Testing Library in `src/**/__tests__/`; Playwright e2e in `frontend/tests/`.
- **Allure taxonomy:** every pytest, Vitest and Playwright product test must emit non-empty `epic`, `feature`, `story`, a human-readable title, and at least one named step. Central defaults live in `backend/tests/allure_taxonomy.py`, `frontend/src/test/allureTaxonomy.ts`, and `frontend/tests/allure.fixtures.ts`; use explicit Allure decorators/helpers only for narrower overrides. See `docs/test-allure-taxonomy.md`.
