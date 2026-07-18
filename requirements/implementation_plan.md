# Brain Buddy Implementation Plan

## Overview
- **Product Vision**: empower product teams to build, validate, and maintain customer research trees collaboratively with AI-assisted guidance.
- **Primary Outcomes**: (1) reliable CRUD backbone for knowledge graphs, (2) intuitive canvas UI for graph editing, (3) AI validation workflow that generates actionable insights, (4) reproducible deployments with documented playbooks.
- **Success Metrics**: >90% API test coverage on core services, ability to manage 200-node tree with <250 ms interaction latency, first validation response <10 s with mock provider, zero-blocker issues in release checklist.
- **Guiding Constraints**: offline-friendly filesystem persistence, minimal external services (OpenAI optional), TypeScript/React on frontend, FastAPI backend, team capacity ~2 engineers + 1 designer.

## Progress Snapshot
- ✅ Phase 1 – Backend MVP Foundations delivered (20 automated tests covering repositories/services/API).
- ✅ Phase 2 – Frontend MVP Foundations running with canvas, inspectors, optimistic CRUD, React Query wiring.
- ✅ Phase 3 – AI Validation Integration live with prompt builder, provider abstraction, mock provider, and UI hooks.
- ✅ Phase 4 – Versioning & Export Completion delivered with diff summaries, export API, and UI integration.
- ⬜ Phase 5 – Hardening & Polish.
- ⬜ Phase 6 – Deployment Readiness.

## Team & Responsibilities
- **Product/Design**: define UX for canvas, inspectors, and validation messaging; deliver wireframes before Phase 2.
- **Backend Engineer**: own API, repository layer, AI pipeline integration, CI tooling.
- **Frontend Engineer**: own Vite React app, React Flow canvas, state management, frontend build pipeline.
- **Shared Support**: engineers collaborate on testing strategy, documentation, and deployment scripts.

## Delivery Approach
- Six sequential phases with explicit demo checkpoints and lightweight design reviews at phase boundaries.
- Each phase closes with regression tests, documentation updates, and a demo to capture feedback before moving forward.
- Milestones (M1–M4) combine multiple phases to align with stakeholder sign-offs.

## Phase 0 – Project Setup (Week 1)
- **Goal**: establish repo scaffolding, coding standards, and local developer ergonomics.
- **Key Tasks**
  - Scaffold FastAPI project under `backend/app` with `pyproject.toml`, dev dependencies (fastapi, uvicorn, pydantic, httpx, python-dotenv, typer, pytest, black, ruff, mypy).
  - Bootstrap Vite + React + TypeScript app under `frontend/`; install React Flow, Zustand, @tanstack/react-query, TailwindCSS with PostCSS/autoprefixer, and class-variance-authority (optional).
  - Configure shared tooling: `.editorconfig`, `.gitignore`, pre-commit hooks (formatting + lint), root Makefile with common targets (`make dev`, `make test-backend`, `make test-frontend`).
  - Draft top-level README outlining architecture, tech stack, and dev setup instructions.
- **Deliverables**: running backend “hello world” endpoint, frontend dev server with placeholder canvas view, lint/test commands wired, README v0.1.
- **Acceptance Criteria**: new dev can clone repo, run `make dev` to start both services, and pass lint/tests locally.
- **Dependencies**: none; unblock backend configuration early to support Phase 1.

## Phase 1 – Backend MVP Foundations (Weeks 2–3)
- **Goal**: deliver validated CRUD API backed by filesystem repositories with automated tests.
- **Scope**
  - Implement configuration utilities (`core/config.py`, `core/logging.py`, `.env` loader) and shared helpers (`utils/file_ops.py`, `utils/time.py`); create `data/` directory scaffold with schema versioning.
  - Define Pydantic schemas for trees, nodes, relations, versions, validation DTOs, pagination, and error payloads; generate OpenAPI docs.
  - Build repositories (`TreeRepository`, `VersionRepository`, `ValidationRepository`, `ProviderRepository`, `IndexRepository`) with atomic write helpers, optimistic locking, and index syncing.
  - Implement services (`TreeService`, `NodeService`, `RelationService`, `VersionService`) with domain validation (ID uniqueness, relation direction, cyclic detection stub) and audit metadata.
  - Expose REST routers for trees/nodes/relations/versions with FastAPI dependency wiring, unified error middleware, and consistent response envelopes.
  - Write pytest suites for repositories (using tmp dirs or pyfakefs), service logic, and API routes via FastAPI TestClient covering happy paths, validation errors, and failure modes.
- **Deliverables**: API contract published at `/docs`, automated tests running in CI, sample seed data under `data/seed/`.
- **Acceptance Criteria**: `make test-backend` passes, readiness checklist ensures schema migrations can bump version without data loss, CRUD endpoints align with `requirements/api_contracts.md`.
- **Dependencies**: Phase 0 tooling; coordinate with frontend to lock API shapes before Phase 2.

## Phase 2 – Frontend MVP Foundations (Weeks 3–5)
- **Goal**: ship interactive canvas MVP wired to backend CRUD with foundational UI states.
- **Scope**
  - Finalize Tailwind theme, global styles, layout shell components (`Layout`, `TopBar`, `SidePanel`, `CanvasShell`).
  - Implement Zustand stores: `treeStore` (graph state, selection, undo/redo queue, optimistic sync hooks) and `uiStore` (panels, modals, toasts).
  - Create API layer (`api/client.ts`) with typed fetch wrapper, React Query hooks (`useTrees`, `useTree`, `useMutateNode`, `useMutateRelation`, `useVersions`) respecting backend contracts and optimistic updates.
  - Integrate React Flow canvas (`CRTCanvas`), custom node/edge renderers, context menu, inline editing, snap-to-grid, keyboard shortcuts for delete/undo.
  - Build inspector panels (`NodeInspector`, `RelationInspector`) with metadata display, relation counts, highlight states, and placeholder validation data slots.
  - Implement version panel UI with stubbed actions pending Phase 4; add notification/toast system surfacing API errors.
  - Testing: Vitest for stores and hooks, React Testing Library for inspectors, Cypress component test for core canvas interactions.
- **Deliverables**: demo video showing create/update/delete nodes & relations synced to backend; design handoff doc annotated with implemented components.
- **Acceptance Criteria**: create/edit/delete flows work offline-first with rollback on API failure, keyboard accessibility validated for primary actions, `make test-frontend` passes.
- **Dependencies**: Phase 1 API stability; design assets for canvas/inspector.

## Phase 3 – AI Validation Integration (Weeks 5–6)
- **Goal**: enable AI-powered validation loop with provider abstraction and frontend UI updates.
- **Status**: ✅ Completed (mock provider running end-to-end via `/api/trees/{tree_id}/validate/{node_id}`).
- **Scope**
  - Implemented prompt builder (`backend/app/ai/prompts/validation_prompt.py`) rendering contextual chain strings per `requirements/ai_validation_prompt.md`.
  - Added provider layer with `MockValidationProvider` and `OpenAIValidationProvider` (`backend/app/ai/providers/`) plus provider config repository wiring.
  - Extended `ValidationService` to orchestrate prompt assembly, provider invocation, node persistence, and history storage (`backend/app/services/validation_service.py`).
  - Activated validation endpoints in FastAPI (`POST /trees/{tree_id}/validate/{node_id}` returns synchronous response, `GET /trees/{tree_id}/nodes/{node_id}/validation-history`).
  - Frontend Node Inspector now exposes “Run Validation” action, live result badges, and history timeline tied to React Query (`frontend/src/components/panels/NodeInspector.tsx`).
  - Testing: added backend unit/api coverage (`backend/tests/test_validation_service.py`, `backend/tests/test_api_validation.py`) and frontend store regression for validation metadata (`frontend/src/stores/__tests__/treeStore.test.ts`).
- **Deliverables**: runnable mock validation demo, provider registry persisted under `data/validation/`, automated tests.
- **Acceptance Criteria**: mock provider completes round-trip under 2 s, failure modes surface actionable errors, synchronous API responses keep UI responsive.
- **Dependencies**: Phase 2 UI scaffolding, Phase 1 services.

## Phase 4 – Versioning & Export Completion (Weeks 6–7)
- **Goal**: finalize snapshot, restore, and export capabilities with end-to-end coverage.
- **Status**: ✅ Delivered Week 7 with backend diff metadata, streaming exports, and refreshed frontend workflows.
- **Scope**
  - Harden `VersionService` for diffing, merge conflict detection, and metadata (author, notes).
  - Add endpoints for create/restore/list/delete snapshots plus JSON export streaming download.
  - Frontend: connect version panel actions (create, rename, restore, delete, view metadata), implement progress feedback and confirmation modals.
  - Provide export download UI with file naming convention and success toast; include skeleton for future PDF export.
  - Testing: regression suite verifying restore accuracy on large graphs, snapshot rollback, export file shape; frontend Cypress flow covering create/restore/export.
- **Kickoff Checklist**
  - **Backend**
    - Extend `VersionDocument` and related Pydantic schemas with author/notes fields plus a diff summary payload.
    - Implement diff + conflict helpers in `VersionService`, persisting metadata and surfacing merge warnings through `VersionRepository`.
    - Wire REST routes in `app/api/routes.py` for list/create/delete/restore plus a streaming export endpoint using FastAPI `StreamingResponse`.
    - Add regression coverage in `tests/test_version_service.py` and a new API suite capturing restore/rollback/export flows.
  - **Frontend**
    - Hook `VersionPanel` actions up to the new API via `api/hooks.ts`, including optimistic updates and loading states.
    - Add confirmation modals for destructive actions and progress toasts in `ToastStack`.
    - Implement export trigger with deterministic filenames and integrate metadata display within `VersionPanel`.
  - **QA & Docs**
    - Generate seed fixtures for large tree restore testing and document the workflow in `/requirements`.
    - Schedule Cypress coverage for snapshot create/restore/export and record evidence in the regression log.
- **Outcome Highlights**
  - Version snapshots now capture author + notes metadata, diff summaries, and conflict signals persisted on disk.
  - REST API exposes JSON exports (live + historic), enriched version listings, and restore/delete confirmations with coverage in `tests/test_api_versions.py`.
  - Frontend version panel upgraded with optimistic React Query flows, confirmation dialogs, diff visualization, and one-click exports aligned with backend filenames.
- **Deliverables**: downloadable JSON export, restore demo, regression documentation for version handling.
- **Acceptance Criteria**: restoring snapshot rehydrates nodes/relations accurately, export passes schema validation, tests cover >80% of versioning module paths.
- **Dependencies**: Phase 1 repositories/services, Phase 2 UI, Phase 3 validation data persistence.

## Phase 5 – Hardening & Polish (Week 8)
- **Goal**: improve reliability, performance, and user experience in preparation for release.
- **Scope**
  - Performance profiling on 100–200 node graphs; optimize React Flow settings, memoization, and repository caching.
  - Enhance error UX with toast retry, fallback messaging, and correlation IDs logged server-side.
  - Introduce lightweight auth middleware placeholder (API key header) to ease future access control.
  - Expand documentation: README v1.0, API usage guide, troubleshooting tips, contribution guide, architecture diagrams.
  - Conduct exploratory testing session; capture bug backlog and address high-severity issues.
  - Use `docs/e2e-acceptance-charter.md` as the executable browser E2E acceptance design for auth, tree, versioning, ownership, mobile, accessibility, fixtures, artifacts, and anti-flake rules.
- **Deliverables**: performance report with tuning notes, updated docs, polished UI/UX per design review.
- **Acceptance Criteria**: interaction latency targets met, no P0/P1 bugs open, docs reviewed by designer/PM.
- **Dependencies**: all prior phases feature-complete.

## Phase 6 – Deployment Readiness (Weeks 9–10)
- **Goal**: produce deployable artifacts, automation, and release checklist for first pilot.
- **Scope**
  - Create Dockerfiles for backend and frontend, docker-compose for local multi-service run, and production-ready env templates (`.env.example`, secrets guidance).
  - Configure CI (GitHub Actions) to run lint/tests/build, publish coverage, and build Docker images; add status badges to README.
  - Draft infrastructure runbook (deployment steps, rollback procedure, monitoring hooks) and initial release checklist (tagging, changelog, smoke tests).
  - Prepare pilot dataset and scripted smoke tests to validate deployment.
- **Deliverables**: CI pipeline green, container images build locally and in CI, release checklist approved.
- **Acceptance Criteria**: one-click deploy to staging via compose, CI gates required on PRs, release checklist executed without issues during dry run.
- **Dependencies**: completed features + documentation from earlier phases.

## Cross-Cutting Workstreams
- **Design Reviews** scheduled before Phase 2 and Phase 3 to validate UI flows.
- **Security & Privacy** review in Phase 5 covering data storage, API keys, and logging.
- **Analytics** placeholder instrumentation (frontend event hooks) scoped but not built; revisit post-M4.

## Risk & Dependency Notes
- **Graph Library**: confirm React Flow license/limits; keep Konva-based fallback spike ready if interactions degrade.
- **AI Provider**: secure API access/budget early; provider registry allows toggling to mock/offline mode without code changes.
- **Filesystem Concurrency**: MVP assumes single-user access; monitor for file locking needs before multi-user rollout.
- **Undo/Redo vs Sync**: implement optimistic updates with rollback on error; add telemetry to highlight failure frequency.
- **Timeline Sensitivity**: AI integration depends on prompt spec stability—lock prompt template by end of Phase 2.

## Suggested Milestones
- **M1 – CRUD Backbone (end Week 3)**: Phases 0–1 complete; backend CRUD + frontend canvas basic editing demo.
- **M2 – Validation Alpha (mid Week 6)**: Phases 0–3 complete; AI validation end-to-end with mock provider; design sign-off on UX.
- **M3 – Versioning Beta (end Week 7)**: Phase 4 complete; snapshot/restore/export functional; pilot testers onboarded.
- **M4 – Release Candidate (end Week 10)**: Phases 5–6 complete; performance tuned, docs finalized, deployment pipeline ready.

## Definition of Done (Project Level)
- All acceptance criteria met per phase with linked test evidence.
- Critical bugs (P0/P1) resolved or mitigated.
- Documentation up to date, including API schema, architecture, and onboarding guides.
- Release checklist executed successfully on staging environment.
