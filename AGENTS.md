# Repository Guidelines

## Project Structure & Module Organization
- `backend/`: FastAPI app under `app/` with repositories, services, and `tests/` (pytest).
- `frontend/`: Vite React client under `src/`; Vitest specs live in `src/**/__tests__/`.
- `mobile/`: Expo (React Native) iOS-first client; Jest specs in `src/**/__tests__/`, real-backend integration suite in `integration/`. See `mobile/AGENTS.md`.
- `docs/`: Architecture, API, troubleshooting, performance, and smoke runbooks.
- `deploy/`: Container assets (nginx config).
- `scripts/`: Utility scripts such as `smoke_test.sh`.

## Build, Test, and Development Commands
- `make dev-backend` / `make dev-frontend`: run backend with uvicorn reload and Vite dev server.
- `make test-backend` / `make test-frontend` / `make test-mobile` / `make test-e2e`: each runs its suite **plus** the coverage floor and the Allure taxonomy validator. The bare runner (`cd backend && pytest`) skips both gates.
- `make verify-all`: the whole chain in CI order — `check-specs validate-ci verify-backend verify-frontend verify-mobile test-e2e`. Run this before reporting a change done.
- `npm run build` (frontend) / `docker compose up --build`: produce production bundles and compose stack.
- `./scripts/smoke_test.sh`: call core API endpoints against the compose stack.

## Coding Style & Naming Conventions
- Python: Black (88-col) + Ruff enforced; prefer descriptive snake_case for functions/vars.
- TypeScript/React: follow existing component naming (`PascalCase` files), use TypeScript strict types.
- Keep comments purposeful; leverage existing store/service patterns when extending features.

## Testing Guidelines
- Backend uses pytest with FastAPI TestClient; mirror test names after module under test (`test_tree_service.py`).
- Frontend leverages Vitest + Testing Library; place component specs beside feature folders.
- Mobile uses Jest; specs live in `mobile/src/**/__tests__/`. See `mobile/AGENTS.md`.
- Every pytest, Vitest, Jest, and Playwright product test must emit Allure Report 3 taxonomy: non-empty `epic`, `feature`, `story`, a human-readable title, and at least one named step. Use the central helpers in `backend/tests/allure_taxonomy.py`, `frontend/src/test/allureTaxonomy.ts`, `mobile/src/test/allureTaxonomy.ts`, and `frontend/tests/allure.fixtures.ts`; override explicitly only when a test needs narrower labels. See `docs/test-allure-taxonomy.md`.
- Coverage floors (`backend/`, `frontend/`, `mobile/coverage-floor.json`) may only ratchet upward, and there is no per-file escape hatch — `scripts/validate_ci_artifacts.py coverage-suppressions` rejects every `istanbul ignore` form in `frontend/src` and `mobile/src`.
- Ensure new features include targeted tests; run both test suites before pushing.

## Definition of Done

Writing or merging code is not completion. A product change is Done only when its product, design, quality, and production criteria below are satisfied with current evidence for the exact deployed commit SHA. A criterion that does not apply must be marked `N/A` with a reason; required behavior may not be silently deferred.

### Product Outcome

- Every frozen acceptance criterion has current passing evidence against the deployed build.
- A representative intended user can complete the primary in-scope journey in production at the intended feature-flag stage, and the promised user-visible result is observed. Generic health checks and page loads are insufficient.
- The expected user outcome and at least one relevant product signal or guardrail are named. Production evidence confirms that the signal is captured correctly; statistically significant adoption or business impact is not required before Done unless explicitly included in the acceptance criteria.
- The intended feature-flag audience is verified. Where applicable, `OFF`, rollback, and recovery behavior must preserve existing user work and restore the documented safe behavior.

### Design and UX

These criteria apply only when rendered UI, copy, navigation, interaction, responsive layout, accessibility behavior, or another client-visible outcome changes. Backend-only changes mark this section `N/A`.

- Exercise each changed critical path in production at the exact deployed SHA, intended configuration, feature-flag state, and affected supported viewport or device class.
- Verify the materially affected reachable states: success and applicable loading, empty, validation, permission or disabled, error, and recovery states.
- Verify that affected layouts have no blocked controls, clipping, unintended overlap, or horizontal scrolling. Changed interactions must support keyboard operation, visible focus, and accessible names, with no new serious or critical accessibility violations on the affected surface.
- Record production screenshots or recordings of the changed surfaces and compare them with the accepted design, acceptance criteria, or approved baseline. Evidence remains bounded to the changed surfaces and risks.

### Engineering Quality

- All applicable required suites pass on the exact candidate SHA: backend pytest, frontend Vitest, Playwright product E2E, and, when mobile is affected, mobile Jest and real-backend integration tests. Skipped required checks are not passes.
- New or changed behavior has targeted tests. Every applicable pytest, Vitest, Jest, and Playwright product test satisfies the Allure Report 3 taxonomy enforced by `scripts/validate_allure_taxonomy.py`: non-empty `epic`, `feature`, and `story`, a human-readable title, and at least one named step.
- Required Spec Kit artifacts and accepted ADRs match the implemented behavior, and `python3 scripts/check_spec_kit_specs.py` passes when feature artifacts are affected. Hermes-managed outcomes additionally require the receipts and exact-SHA evidence defined by ADR-0010.
- Affected critical operations, errors, and state transitions produce production-safe logs at an appropriate level with a request or correlation identifier where available. Critical-path exceptions must not be silently swallowed, and logs must not contain secrets or sensitive payloads.
- Monitoring requirements must be concrete and proportional to the change. Existing reachability, production-smoke, canary, and structured-log signals must remain healthy. When a change introduces a new metric or alert requirement, its signal, threshold, owner, and response must be defined before it becomes a Done gate.
- No regressions are detected by the full applicable required suite on the exact SHA. Absolute claims such as “no regressions exist” are not acceptable evidence.

### Production and Release Evidence

- SHIP and SHOW changes clear required CI on `trunk-candidate/<sha>`. The release workflow proves that `origin/main` equals the tested SHA, fast-forwards `main`, and re-verifies that same SHA immediately before deployment.
- ASK changes require explicit recorded approval, green required CI on the exact SHA, and evidence of the audited temporary ruleset intervention required by ADR-0008. ASK changes never use automatic candidate promotion.
- The deployed commit SHA matches the tested and independently reviewed SHA. Any SHA change invalidates prior review, QA, and release evidence.
- `scripts/production_smoke.sh` passes against production, including the effective `delivery_canary` assertion, authenticated primary workflow, temporary-data cleanup, and cleanup read-back.
- The release completes without rollback. A failed production smoke, rollback, partial deployment, missing evidence, or successful deployment of a different SHA means the change is not Done.
- Evidence identifies the exact SHA and includes the applicable CI and release workflow runs, independent review and QA verdicts, production-smoke result, feature-flag read-back, and product or UX evidence.

## Commit & Pull Request Guidelines
- Commit messages follow conventional prefix style (`feat:`, `fix:`, `docs:`, etc.).
- Keep commits focused; include smoke-test or manual verification notes in body when relevant.
- PRs should describe scope, testing performed, and link to requirements or issues; add screenshots/GIFs for UI-visible changes.

## Security & Configuration Tips
- Use `.env.example` as the baseline—copy to `.env` for local compose runs.
- Auth is session-based (HTTP-only cookie) and invite-gated. Mint invites with `python -m app.cli create-invite`. See `docs/auth.md` for the threat model and recommended controls.
- Do not commit real data under `backend/data/`; compose mounts a named volume for local persistence.

## Architecture Decisions
- Before changing module boundaries, persistence ownership, workflow state machines, authentication assumptions, or deployment boundaries, inspect accepted/proposed records under `docs/decisions/`.
- BrainBuddy vNext's modular-monolith boundaries and capture-to-result contracts are defined in `docs/decisions/0001-vnext-modular-monolith-and-workflow-contracts.md`; preserve them unless a new ADR explicitly supersedes the decision.
- Async voice brain dumps and voice-led Weekly Review share the operation, patch, confirmation, privacy, and idempotency contract in `docs/decisions/0002-async-voice-operation-substrate.md`.
- Native GTD capability status, Task lifecycle transitions, Waiting/recovery behavior,
  date semantics, and implementation-ready UI/API gaps are fixed in
  `docs/decisions/0006-native-gtd-lifecycle-and-capability-baseline.md`; its public
  Priority vocabulary and Project archive membership rule are narrowly superseded by
  `docs/decisions/0020-rtm-parity-priority-and-archive-semantics.md`.
- Autonomous delivery, visual preview eligibility, and production release/rollback authority are governed by `docs/decisions/0003-autonomous-delivery-guardrails.md` and `docs/autonomous-delivery-runbook.md`.
- Verified trunk serial landing (PR-less SHIP/SHOW delivery, Ship/Show/Ask classification, feature-flag rollout, deploy rollback) is governed by `docs/decisions/0008-verified-trunk-serial-landing.md`, which partially supersedes ADR-0003.
- The spec review gate is ADR-0011 (portable stage), amended by ADR-0012 (risk classes, escalation, gate integrity) and ADR-0014 (hybrid reviewer fallback with recorded degradation).
- Mutation-testing scope is ADR-0004, split into observed and enforced tiers by ADR-0016, extended to the frontend by ADR-0013 and to mobile by ADR-0015. **ADR-0016 was accepted as ADR-0011**: two agents took the same number on 2026-08-10, and it was renumbered on 2026-08-13. Read any older "ADR-0011" reference in context.

## Mandatory Spec Kit Workflow
- GitHub Spec Kit is the canonical authoring workflow for every new or materially changed BrainBuddy feature spec; use the repo-pinned official CLI version documented in `docs/spec-kit-workflow.md`.
- The portable artifact sequence is constitution → `/speckit-interview` (business requirements, human) → `/speckit-specify` (what/why) → `/speckit-clarify` (human) → `/speckit-design` (screens + numbered state inventory) → `/speckit-plan` (how/architecture; MUST cite `design.md`) → `/speckit-review` (five-lens gate, ADR-0011) → `/speckit-checklist` → `/speckit-tasks` → `/speckit-analyze` → `/speckit-implement` → `/speckit-accept` → `/speckit-report`. Amend the spec first whenever implementation intent changes.
- `/speckit-design` and `/speckit-review` are **mandatory**, not advisory: `.specify/extensions.yml` registers them as `optional: false` hooks on `after_clarify` and `after_plan`. Implementation must not start unless the review verdict is `approved` or `founder-accepted`. `/speckit-assess-*` is an optional stage 0 that can kill an idea before any requirement is elicited.
- Feature numbers are reserved across every git ref. Two branches that each claim `specs/NNN-` merge without a git conflict and then satisfy each other's requirement-coverage gate, because `scripts/check_requirement_coverage.py` matches `NNN[-_]FR[-_]nnn` repository-wide. `scripts/check_spec_kit_specs.py` rejects duplicates.
- Spec Kit owns versioned planning artifacts under `specs/` plus `.specify/`. Generated `tasks.md` is planning input, not permission to bypass isolated worktrees, TDD, independent review, CI, landing, or release gates.
- Execution tooling is selected by the work context. Standalone agents may implement from the validated artifacts; opt-in Hermes-managed outcomes additionally follow `.hermes.md`, ADR-0010, and `docs/spec-driven-kanban.md`.
- Before adding or changing a feature spec, run `python3 scripts/check_spec_kit_specs.py` (or `make check-specs`) and preserve documented grandfathering for historical specs.

## Agent Delivery Workflow
- Work in an isolated git worktree and feature branch. Never leave product changes uncommitted in the primary worktree.
- Classify every change as Ship/Show/Ask (ADR-0008). SHIP (low risk) and SHOW (medium risk) land PR-less via verified trunk: one candidate commit on the current `origin/main`, submitted with `scripts/submit_to_trunk.sh` to a `trunk-candidate/<sha>` ref; full CI runs there (with no write permission and no access to the landing identity — candidate-controlled CI can never promote), and the default-branch release workflow's serialized `land` job fast-forwards `main` to the exact tested SHA, authenticating with the dedicated `TRUNK_LANDING_SSH_KEY` SSH deploy key from the GitHub `landing` environment (branch policy `main` only). No workflow holds `GITHUB_TOKEN` write, and the `main` ruleset MUST keep `restrict_updates` with that deploy key as the only bypass actor and `Full CI` + `Docker Images` required for human/PR paths. The GitHub `production` environment MUST likewise restrict deployments to `main` (custom branch policy) and hold `FLY_API_TOKEN` as an environment secret only — no repository-level `FLY_API_TOKEN` exists — plus the admin/cohort secrets; both are bootstrap verification items, and candidate-controlled CI may request neither the `landing` nor the `production` environment (validator-enforced).
- ASK-class changes (auth/privacy, destructive data/schema, billing/provider credentials, CI/CD/security/infra, irreversible external effects) never land automatically. A PR carries the review evidence, but — stated honestly — while the landing deploy key is the sole `restrict_updates` bypass actor, no PR merge and no direct human push can update `main`: an ASK landing requires explicit recorded approval, green required CI on the exact SHA, and a short, audited, temporary ruleset intervention (see the runbook; adding a separately accountable human reviewer in the future would restore a merge-behind-required-checks path without weakening the ruleset). This is enforced mechanically: `scripts/classify_path_risk.py` classifies every changed path from NUL-separated `git diff --no-renames --name-only -z` output (the per-owner privacy-enforcement API modules `backend/app/api/dependencies.py`, `middleware.py`, `routes.py`, and `tasks.py` are explicit ASK paths), `submit_to_trunk.sh` runs it as a non-skippable preflight, and the release workflow's `land` job re-runs the trusted `origin/main` copy before pushing `main` — ASK paths fail automatic promotion closed. A fully green candidate CI run auto-promotes nothing until the default-branch release workflow and the landing identity exist (bootstrap order and the emergency direct-landing audit requirements are in the runbook).
- The default-branch release workflow consumes completed successful push CI runs (`trunk-candidate/<sha>`, or `main` for ASK-class merges): its `land` job (read-only token, `landing` environment, deploy-key push) lands candidates and proves `origin/main` equals the tested SHA for every run, then its `deploy` job (production environment, `contents: read`) re-verifies that proof immediately before any Fly mutation — so stale CI runs can never redeploy an older SHA — checks the smoke admin identity against backend startup rules (email shapes, password policy, internal-cohort membership), then runs reachability plus the authenticated production smoke (which asserts `delivery_canary` is effectively true for the provisioned internal smoke identity, and best-effort cleans up its temporary tree from an EXIT trap, marking cleanup done only after the 404 read-back). Failed smoke rolls back to the captured previous images and the run stays failed. There is no manual production deploy trigger; do not perform an ad-hoc deploy instead of this release path.
- Production exposure of new behavior is controlled by server-owned feature flags (default OFF; rollout OFF → INTERNAL → ON). Flags are never authorization.
- There are currently no customer or valuable production data: prioritize MVP velocity, but preserve the candidate → CI → landing → verified deploy traceability.

## Active Technologies

`.specify/scripts/bash/update-agent-context.sh` appends here on `/speckit-plan`.
It had accumulated fifteen near-identical lines naming four features that no
longer exist under `specs/` — pruned 2026-08-13. Prune again rather than letting
it grow; this is a summary, not an append-only log.

- Backend: Python 3.11, FastAPI, Pydantic, pytest. Layered `app/api/` ->
  `app/services/` -> `app/repositories/`, wired in `app/container.py`.
- Frontend: TypeScript (strict), React, Vite, Zustand, React Query, Tailwind;
  Vitest + Testing Library, Playwright for e2e.
- Mobile: Expo SDK 57 / React Native 0.86 / TypeScript strict / expo-router;
  Jest. See `mobile/AGENTS.md`.
- Persistence: file-backed tree data under `backend/data` with a 16-entry LRU
  cache, plus `tasks.sqlite3` for the task module.
- Deploy: Docker/Compose locally, Nginx in the frontend image, Fly.io in
  production.

## Recent Changes

See `git log` and `docs/decisions/`. One caveat when reading older records:
ADR-0016 was accepted as ADR-0011 and renumbered on 2026-08-13, because two
parallel agents took that number on the same day. A pre-2026-08-13 reference to
"ADR-0011" may mean either the portable spec review stage (which keeps the
number) or the observed/enforced mutation scope tiers (now ADR-0016).
