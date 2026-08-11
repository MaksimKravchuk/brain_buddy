# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Backend (Python / FastAPI)

```bash
# Install
cd backend && pip install -e .[dev]

# Dev server (from repo root)
make dev-backend          # uvicorn app.main:app --reload --app-dir backend

# Tests
make test-backend         # builds Docker test image and runs pytest
cd backend && pytest      # run directly against local venv

# Run a single test
cd backend && pytest tests/test_tree_service.py::test_create_tree -v

# Lint / format / type check
cd backend && ruff check app tests
cd backend && black app tests
cd backend && mypy app
```

### Frontend (TypeScript / React)

```bash
# Install
cd frontend && npm install

# Dev server
make dev-frontend         # Vite at localhost:5173 (compose serves at 8080 instead)

# Tests
make test-frontend        # vitest with coverage, then the coverage floor and Allure taxonomy
cd frontend && npm test   # vitest run (once)
cd frontend && npm run test:watch

# Lint / type check
make lint-frontend        # eslint . --max-warnings=0
make typecheck-frontend   # tsc --noEmit

# Mutation testing (Stryker; ADR-0013). Report-only nightly, ~20 min locally.
cd frontend && npm run test:mutation
cd frontend && npx stryker run --mutate 'src/utils/error.ts'   # one module

# Build
cd frontend && npm run build
```

Coverage floors live in `frontend/coverage-floor.json` and may only ratchet
upward. There is no per-file escape hatch: `scripts/validate_ci_artifacts.py
coverage-suppressions` rejects `istanbul ignore file` and every range form in
`frontend/src` and `mobile/src`, because an excluded file is reported as neither
covered nor uncovered — it silently leaves the measurement.

### Full stack

```bash
cp .env.example .env
docker compose up --build        # backend:8000, frontend:8080
./scripts/smoke_test.sh          # runs core API endpoints against compose stack
docker compose down --volumes
```

### Mobile (Expo / React Native, iOS-first)

```bash
make install-mobile        # npm install in mobile/
make typecheck-mobile      # tsc --noEmit
make test-mobile           # jest unit tests
make integration-mobile    # real api client vs disposable local backend (needs install-backend)
make build-mobile          # expo export --platform ios (Metro bundle check)
cd mobile && npx expo start   # run on an iPhone via Expo Go
```

See `mobile/README.md` for the device runbook and `mobile/AGENTS.md` for the
wire-protocol contracts the client must keep (chunk hashing, manifest hash,
lifecycle guards).

### Spec Kit feature authoring

Use GitHub Spec Kit v0.15.0 for every new or materially changed feature spec.
Install or refresh the CLI with isolated uv tooling, not inside application
backend/frontend environments:

```bash
uv tool install specify-cli --force --from git+https://github.com/github/spec-kit.git@v0.15.0
specify --version          # expect: specify 0.15.0
specify check              # verifies Claude Code and other agent prerequisites
specify integration list   # confirms claude is available/installed
```

Claude Code uses the skills installed under `.claude/skills/`:

```text
/speckit-constitution
/speckit-specify <what and why, not implementation>
/speckit-clarify
/speckit-plan <how and architecture>
/speckit-checklist
/speckit-tasks
/speckit-analyze
```

### The full delivery pipeline

`.specify/extensions.yml` chains five BrainBuddy stages onto the Spec Kit core,
using the `hooks.before_*` / `hooks.after_*` keys the upstream skills already
read — no upstream skill is forked. Front door for an abstract ask:

```text
/speckit-assess-*    should this be built at all? -> decision.md         [human, optional]
/speckit-interview   business requirements from the human -> intake.md   [human]
/speckit-specify     what and why -> spec.md
/speckit-clarify     disambiguate                                        [human]
/speckit-design      screens + numbered state inventory -> design.md     [human sign-off]
/speckit-plan        how and architecture -> plan.md  (MUST cite design.md)
/speckit-review      five-lens review gate (ADR-0011) -> verdict         [human on product decisions]
/speckit-checklist   requirements quality
/speckit-tasks       -> tasks.md
/speckit-analyze     cross-artifact consistency
/speckit-implement   direct implementation in an isolated worktree
/speckit-accept      criterion -> test traceability -> accept | reject
/speckit-report      the end-to-end report for the human                 [human]
```

Stage 0 is the `assess` Spec Kit extension (`spec-kit-core`, installed):
`/speckit-assess-intake` → `research` → `define` → `shape` → `decide`, writing
`.specify/assessments/<slug>/decision.md`. A **kill** verdict stops the
pipeline — `/speckit-interview` refuses to proceed past one without an explicit
human override. Killing an idea there costs one conversation; discovering the
same thing at acceptance costs the whole pipeline.

Tests carry the feature-qualified requirement id (`006-FR-001`, or
`006_FR_001` in a Python name) so `scripts/check_requirement_coverage.py` can
trace them; a bare `FR-001` is rejected because every feature restarts at 001.

Subagents live in `.claude/agents/`: `design-architect`,
`security-privacy-reviewer`, `ux-a11y-reviewer`, `feature-implementer`,
`delivery-verifier`, `acceptance-auditor`. The two reviewer agent files are the
**single source of rubric truth** for their lenses — `spec_kit_planning_review.py`
points at them rather than restating the rubric.

The interview cannot be a subagent: `AskUserQuestion` is stripped from every
subagent, so human elicitation must run in the main session.

Verification: `/self-verify` (free, deterministic, `make verify-all`) versus
`/verify-live` (**approval-gated, spends real provider money**, never run
unattended).

`/speckit-implement` implements directly, matching this file, the constitution
and `docs/spec-kit-workflow.md`. It is a preserved override guarded by
`scripts/check_speckit_manifests.py`; `specify integration upgrade --force`
must not revert it.

Read `docs/spec-kit-workflow.md` before authoring specs. Spec Kit maintains
versioned artifacts under `specs/`. Generated `tasks.md` is portable planning
input: implement it directly when the user's request includes implementation,
while preserving worktree, TDD, review, CI, landing, and release gates. Do not
assume Hermes or a Kanban runtime is present. If Claude Code is explicitly
launched inside an opt-in Hermes-managed outcome, the invoking task supplies the
additional signed scope and `docs/spec-driven-kanban.md` becomes authoritative
for that managed run only.

## Architecture

### Backend — layered design

```
HTTP request
  → app/api/          (FastAPI routes, request/response coercion)
  → app/services/     (business logic, orchestration, LRU cache)
  → app/repositories/ (file I/O under backend/data/)
```

**Key services:**
- `TreeService` — CRUD + 16-entry LRU in-memory cache; also coordinates AI feedback
- `AccountService` — self-serve GDPR account management (profile/email/password, ZIP data export, 14-day-grace deletion + purge); always on, never feature-flagged. See `docs/data-retention.md`
- `NodeService` / `RelationService` — mutations that update the parent tree document
- `ValidationService` — dispatches to an AI provider and records history
- `VersionService` — creates/restores JSON snapshots of a tree
- `app/modules/tasks/` — self-contained GTD task module (`TaskService`, `TaskRepository`, domain models): tasks/projects/tags plus voice brain-dump operations, stored in SQLite (`tasks.sqlite3`) with idempotent, owner-serialized commands

**Dependency injection** lives in `app/container.py`, which wires repositories → services → API routers. All routes use FastAPI `Depends()` to receive services; never instantiate services directly in route handlers.

**Data model:** storage is dual. Each tree is a single JSON file (`backend/data/<tree_id>.json`) containing the full tree document with embedded `nodes` and `relations` arrays; an index file tracks all tree IDs. Task-tracker records (tasks, projects, tags, brain-dump operations) live in one SQLite database (`tasks.sqlite3`) under the same data dir. Pydantic domain models are in `app/schemas/domain.py` and `app/modules/tasks/domain.py`; API contracts are in `app/schemas/api.py` and `app/schemas/tasks.py`.

**AI provider abstraction** (`app/ai/providers/`): `base.py` defines the interface; `mock.py` returns canned responses; `openai.py` calls the real API. The active provider is selected at startup via config.

### Frontend — state and data flow

**Server state** is managed by React Query (`src/api/`). Custom hooks (`useTree`, `useTrees`, etc.) wrap the typed client in `src/api/client.ts`.

**Client state** uses two Zustand stores:
- `useTreeStore` (`src/stores/treeStore.ts`) — active tree, nodes, relations, versions, undo/redo stack, optimistic update queue, 5-second debounced autosave to localStorage
- `useUiStore` (`src/stores/uiStore.ts`) — modal visibility, toasts

**Canvas** is built on React Flow (`reactflow`); styling is TailwindCSS. `TreeCanvas` renders nodes and custom edges. Node/relation details are shown in `InspectorTabs` → `NodeInspector` / `RelationInspector`.

### Cross-cutting behavior

- **Session auth** — users sign in with email + password; the backend sets an opaque session token in an `HttpOnly`, `SameSite=Lax`, `Secure`-in-prod cookie. Every `/api/trees/*`, `/api/tasks`, `/api/projects`, `/api/tags`, and `/api/brain-dump-operations` route requires the cookie and enforces per-owner filtering. Signup is gated by an invite code minted via `python -m app.cli create-invite`. See `docs/auth.md`.
- **Same-origin fetch** — the frontend hits the backend via `/api` on the same origin. In production the Fly frontend app proxies. In dev, Vite proxies `/api` and `/health` to `http://localhost:8000`. This keeps cookies usable and eliminates CORS.
- **AI consent gating** — AI validation requires an explicit consent toggle in the inspector. Declining consent short-circuits with a validation error rather than calling the provider.
- **Correlation IDs** — every response carries `X-Correlation-ID`. Error toasts surface it for retry/report flows, and backend logs key off the same ID.
- **Autosave** — the canvas debounces a 5s local autosave to `localStorage` and warns on page exit when unsaved changes exist.

### Deployment & CI

- **Docker Compose** (local full stack): `docker compose up --build` → backend `:8000`, frontend `:8080`. Smoke via `./scripts/smoke_test.sh`.
- **Fly.io** — two apps via `fly.backend.toml` and `fly.frontend.toml`. The **backend app is private (Flycast-only)**; the frontend proxies to it via `BACKEND_ORIGIN`. Runbooks: `docs/fly-deployment.md`, `docs/fly-review-apps.md`.
- **CI** — `.github/workflows/ci.yml` runs as parallel lanes joined only by
  `full-ci`: one per service (`backend`, `frontend`, `mobile` — each its own
  lint/type/unit/integration, path filtered by the `changes` job), plus
  `workflow-lint`, `spec-kit`, `docker` and `e2e`. A lane may declare `needs`
  only for a job whose output it actually consumes; `scripts/validate_ci_artifacts.py
  workflow` rejects anything else, and rejects a job missing from `full-ci`'s
  `needs` (with a flat graph that gate is the only thing making a job required).
  `e2e` is never path filtered and never queued behind a service lane. It
  rebuilds only what changed: `main`'s Docker layers are reused via the shared
  `stack-*` buildx cache, so an untouched service starts from main's image.
  Wait for CI green before deploying.
- **Deeper docs** — architecture, API, troubleshooting, performance, and infra runbooks live under `docs/`. Feature specs (e.g. `001-relation-linking-refactor`) live under `specs/`.

### Environment variables

| Variable | Default | Notes |
|---|---|---|
| `BRAIN_BUDDY_ENV` | `development` | `development`, `production`, or `test` |
| `BRAIN_BUDDY_DATA_DIR` | `backend/data` | file storage root |
| `BRAIN_BUDDY_API_PREFIX` | `/api` | FastAPI router prefix |
| `BRAIN_BUDDY_ADMIN_EMAIL` | _(unset)_ | If set with `BRAIN_BUDDY_ADMIN_PASSWORD`, seeds an admin account on startup (create-or-rotate-password) |
| `BRAIN_BUDDY_ADMIN_PASSWORD` | _(unset)_ | Password for the seeded admin. Must satisfy the password policy (≥12 chars); startup fails loudly otherwise |
| `VITE_API_BASE_URL` | `/api` | backend URL from frontend; same-origin proxied via Vite in dev |

## Conventions

- **Commits:** conventional prefix style — `feat:`, `fix:`, `docs:`, `refactor:`, etc.
- **Python:** Black 88-col + Ruff (`E`, `F`, `I`, `UP`, `B` rules); snake_case functions/vars.
- **TypeScript:** strict mode; PascalCase component filenames; no `any` except at explicit boundaries.
- **Backend tests:** mirror module name (`test_tree_service.py`); use the `api_client` / service fixtures from `conftest.py`; clear the LRU cache between tests.
- **Frontend tests:** Vitest + Testing Library in `src/**/__tests__/`; Playwright e2e in `frontend/tests/`.
- **Allure taxonomy:** every pytest, Vitest, and Playwright product test must emit non-empty `epic`, `feature`, `story`, a human-readable title, and at least one named step. Central defaults live in `backend/tests/allure_taxonomy.py`, `frontend/src/test/allureTaxonomy.ts`, and `frontend/tests/allure.fixtures.ts`; use explicit Allure decorators/helpers only for narrower overrides. See `docs/test-allure-taxonomy.md`.
