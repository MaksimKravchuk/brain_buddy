# Repository Guidelines

## Project Structure & Module Organization
- `backend/`: FastAPI app under `app/` with repositories, services, and `tests/` (pytest).
- `frontend/`: Vite React client under `src/`; Vitest specs live in `src/**/__tests__/`.
- `ios/`: the iPhone client — a native offline-first SwiftUI app (iOS 26) with an XcodeGen project and the Linux-testable `BrainBuddyKit` package; CI lanes `ios-kit`/`ios-app` in `ci.yml`, TestFlight in `.github/workflows/ios.yml`. See `ios/AGENTS.md` and `docs/native-ios-app.md`.
- `docs/`: Architecture, API, troubleshooting, performance, and smoke runbooks.
- `deploy/`: Container assets (nginx config).
- `scripts/`: Utility scripts such as `smoke_test.sh`.

## Build, Test, and Development Commands
- `make dev-backend` / `make dev-frontend`: run backend with uvicorn reload and Vite dev server.
- `make test-backend` / `make test-frontend` / `make test-e2e`: each runs its suite **plus** the coverage floor and the Allure taxonomy validator. The bare runner (`cd backend && pytest`) skips both gates.
- `make verify-all`: the whole chain in CI order — `check-specs validate-ci verify-backend verify-frontend test-e2e`. Run this before reporting a change done.
- `npm run build` (frontend) / `docker compose up --build`: produce production bundles and compose stack.
- `./scripts/smoke_test.sh`: call core API endpoints against the compose stack.

## Coding Style & Naming Conventions
- Python: Black (88-col) + Ruff enforced; prefer descriptive snake_case for functions/vars.
- TypeScript/React: follow existing component naming (`PascalCase` files), use TypeScript strict types.
- Keep comments purposeful; leverage existing store/service patterns when extending features.

## Testing Guidelines
- Follow [Constitution Principle II](.specify/memory/constitution.md#ii-tested-delivery-across-stack) when planning, implementing, reviewing, or delegating work. Define the outcome before coding, reuse sufficient checks, and add only missing behavior/risk coverage at the least costly reliable level. New tests per task or layer are not required; test-first applies to the cases defined there.
- Backend uses pytest with FastAPI TestClient; mirror test names after module under test (`test_tree_service.py`).
- Frontend leverages Vitest + Testing Library; place component specs beside feature folders.
- Every pytest, Vitest, and Playwright product test must emit Allure Report 3 taxonomy: non-empty `epic`, `feature`, `story`, a human-readable title, and at least one named step. Use the central helpers in `backend/tests/allure_taxonomy.py`, `frontend/src/test/allureTaxonomy.ts`, and `frontend/tests/allure.fixtures.ts`; override explicitly only when a test needs narrower labels. See `docs/test-allure-taxonomy.md`.
- Coverage floors (`backend/`, `frontend/coverage-floor.json`) may only ratchet upward, and there is no per-file escape hatch — `scripts/validate_ci_artifacts.py coverage-suppressions` rejects every `istanbul ignore` form in `frontend/src`.
- Ensure new features include targeted tests; run both test suites before pushing.

## Minimal Sufficient Delivery

- Before changing anything, state the accepted outcome, non-goals, acceptance evidence, and untouched scope.
- Choose the smallest coherent diff that satisfies the accepted requirement. Every new abstraction, dependency, configuration layer, compatibility path, agent, task, or test must be necessary for that requirement or a binding repository gate; otherwise omit it.
- Read the relevant code first and reuse existing mechanisms. Do not create parallel implementations, speculative future-proofing, or unrelated cleanup.
- Default to one bounded serial path. Split work only when independent coordination is genuinely required; make trivial documentation, prompt, and configuration edits directly without creating Kanban work.
- Apply ADR-0023's fast lane to eligible SHIP/SHOW changes: use the lightweight brief above, one risk-selected independent gate, exact-SHA CI, verified landing, and production smoke. Use the full Spec Kit and multi-gate path only when its risk triggers apply.
- Run the smallest relevant existing checks first, following Constitution Principle II. Use affected checks while iterating and full applicable verification on the prepared candidate; do not rerun the whole suite after each technical task without a new reason.
- If code, tests, artifacts, or task count grows without increasing the accepted outcome, stop, remove the extra construction, and return adjacent improvements to backlog.
- Treat review comments as claims to validate against the code and accepted requirements. Fix confirmed defects with the smallest coherent change; a review comment alone does not authorize new functionality or broader scope. Leave optional improvements for a separate owner decision.

## Code Review Rules

- Report consequential defects introduced or newly exposed by the diff. Identify the reachable trigger, the violated acceptance criterion or existing contract, and the concrete impact, supported by code or test evidence. Include realistic boundary, security, and data-loss failures even when they are outside the happy path; do not invent requirements or assume unsupported future consumers.
- Respect the accepted scope and explicit non-goals. Do not request new features, broader platform/API support, speculative hardening, architectural cleanup, style changes, or additional tests unless they are necessary to address a specific consequential defect or an applicable binding repository gate. Reuse sufficient existing test evidence under Constitution Principle II.
- Set priority from demonstrated impact and realistic likelihood. Do not inflate severity to make an optional improvement reportable, repeat mechanical lint/format findings handled by CI, or produce findings to meet a quota. No actionable findings is a valid review result.

## Definition of Done

Writing or merging code is not completion. A product change is Done only when its applicable product, design, quality, and production criteria below are satisfied with current evidence for the exact deployed commit SHA. ADR-0023 makes those criteria risk-proportionate for eligible SHIP/SHOW changes. A criterion that does not apply must be marked `N/A` with a reason; required behavior may not be silently deferred.

### Product Outcome

- Every frozen acceptance criterion has current passing evidence against the deployed build.
- For a user-visible change, a representative intended user can complete the primary in-scope journey in production at the intended feature-flag stage, and the promised result is observed. Docs, tests, refactors, internal changes, and non-user-visible corrections may mark this `N/A`; their green authenticated production smoke remains required.
- The expected user outcome and at least one relevant product signal or guardrail are named. Production evidence confirms that the signal is captured correctly; statistically significant adoption or business impact is not required before Done unless explicitly included in the acceptance criteria.
- The intended feature-flag audience is verified. Where applicable, `OFF`, rollback, and recovery behavior must preserve existing user work and restore the documented safe behavior.

### Design and UX

These criteria apply only when rendered UI, copy, navigation, interaction, responsive layout, accessibility behavior, or another client-visible outcome changes. Backend-only changes mark this section `N/A`.

- Exercise the changed primary path in production at the exact deployed SHA, intended configuration, feature-flag state, and affected supported viewport or device class.
- For an ADR-0023 fast-lane change, verify the changed success path and the highest-risk applicable failure or recovery state. Require the fuller loading, empty, validation, permission/disabled, error, and recovery matrix only when those states are materially changed or explicitly accepted criteria.
- Verify that affected layouts have no blocked controls, clipping, unintended overlap, or horizontal scrolling. Changed interactions must support keyboard operation, visible focus, and accessible names, with no new serious or critical accessibility violations on the affected surface.
- Record production screenshots or recordings of the changed surfaces and compare them with the accepted design, acceptance criteria, or approved baseline. Evidence remains bounded to the changed surfaces and risks.

### Engineering Quality

- All applicable required suites pass on the exact candidate SHA: backend pytest, frontend Vitest, Playwright product E2E, and, when the native iOS app is affected, the `ios-kit` and `ios-app` lanes. Skipped required checks are not passes.
- New or changed behavior has targeted tests. Every applicable pytest, Vitest, and Playwright product test satisfies the Allure Report 3 taxonomy enforced by `scripts/validate_allure_taxonomy.py`: non-empty `epic`, `feature`, and `story`, a human-readable title, and at least one named step.
- Required Spec Kit artifacts and accepted ADRs match the implemented behavior, and `python3 scripts/check_spec_kit_specs.py` passes when feature artifacts are affected. Hermes-managed outcomes additionally require the receipts and exact-SHA evidence defined by ADR-0010.
- Affected critical operations, errors, and state transitions produce production-safe logs at an appropriate level with a request or correlation identifier where available. Critical-path exceptions must not be silently swallowed, and logs must not contain secrets or sensitive payloads.
- Monitoring requirements must be concrete and proportional to the change. Existing reachability, production-smoke, canary, and structured-log signals must remain healthy. When a change introduces a new metric or alert requirement, its signal, threshold, owner, and response must be defined before it becomes a Done gate.
- No regressions are detected by the full applicable required suite on the exact SHA. Absolute claims such as “no regressions exist” are not acceptable evidence.

### Production and Release Evidence

- SHIP and SHOW changes clear required CI on `trunk-candidate/<sha>`. The release workflow proves that `origin/main` equals the tested SHA, fast-forwards `main`, and re-verifies that same SHA immediately before deployment.
- ASK changes require explicit recorded approval, green required CI on the exact SHA, and evidence of the audited temporary ruleset intervention required by ADR-0008. ASK changes never use automatic candidate promotion.
- The deployed commit SHA matches the tested SHA and the SHA covered by ADR-0023's selected independent review or QA gate. Any SHA change invalidates prior independent-gate and release evidence.
- `scripts/production_smoke.sh` passes against production, including the effective `delivery_canary` assertion, authenticated primary workflow, temporary-data cleanup, and cleanup read-back.
- The release completes without rollback. A failed production smoke, rollback, partial deployment, missing evidence, or successful deployment of a different SHA means the change is not Done.
- Evidence identifies the exact SHA and includes the applicable CI and release workflow runs, the risk-selected independent review or QA verdict (both only when triggered), production-smoke result, feature-flag read-back, and bounded product or UX evidence when user-visible behavior changed.

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
- Verified trunk serial landing (PR-less SHIP/SHOW delivery, Ship/Show/Ask classification, feature-flag rollout, deploy rollback) is governed by `docs/decisions/0008-verified-trunk-serial-landing.md`, which partially supersedes ADR-0003. ADR-0023 makes planning and independent evidence proportionate for eligible test-stage SHIP/SHOW slices without changing exact-SHA delivery controls.
- The spec review gate is ADR-0011 (portable stage), amended by ADR-0012 (risk classes, escalation, gate integrity) and ADR-0014 (hybrid reviewer fallback with recorded degradation).
- Mutation-testing scope is ADR-0004, split into observed and enforced tiers by ADR-0016, extended to the frontend by ADR-0013 (and, until the Expo client was removed in 2026-10, to mobile by the now-superseded ADR-0015). **ADR-0016 was accepted as ADR-0011**: two agents took the same number on 2026-08-10, and it was renumbered on 2026-08-13. Read any older "ADR-0011" reference in context.

## Proportionate Spec Kit Workflow
- The canonical Spec Kit instructions are in `.specify/agent-commands/` (generic
  integration). Read the relevant `SKILL.md` directly if your agent does not
  discover that directory; no vendor-specific CLI is required for authoring.
- ADR-0023's lightweight brief is sufficient for an eligible bounded SHIP/SHOW correction, refactor, docs/test change, or single-surface enhancement. The canonical full-path triggers are a significant new capability, a cross-surface contract change, a persistence/schema change, a materially changed workflow/state-machine boundary, or any ASK-class outcome; use the repo-pinned official CLI version documented in `docs/spec-kit-workflow.md`.
- When the full path applies, the portable artifact sequence is constitution → `/speckit-interview` (business requirements, human) → `/speckit-specify` (what/why) → `/speckit-clarify` (human) → `/speckit-design` (screens + numbered state inventory) → `/speckit-plan` (how/architecture; MUST cite `design.md`) → `/speckit-review` (five-lens gate, ADR-0011) → `/speckit-checklist` → `/speckit-tasks` → `/speckit-analyze` → `/speckit-implement` → `/speckit-accept` → `/speckit-report`. Amend an existing spec first whenever implementation intent changes.
- On that full path, `/speckit-design` and `/speckit-review` are **mandatory**, not advisory: `.specify/extensions.yml` registers them as `optional: false` hooks on `after_clarify` and `after_plan`. Implementation must not start unless the review verdict is `approved` or `founder-accepted`. `/speckit-assess-*` is an optional stage 0 that can kill an idea before any requirement is elicited.
- Feature numbers are reserved across every git ref. Two branches that each claim `specs/NNN-` merge without a git conflict and then satisfy each other's requirement-coverage gate, because `scripts/check_requirement_coverage.py` matches `NNN[-_]FR[-_]nnn` repository-wide. `scripts/check_spec_kit_specs.py` rejects duplicates.
- Spec Kit owns versioned planning artifacts under `specs/` plus `.specify/`. Generated `tasks.md` is planning input, not permission to bypass isolated worktrees, Constitution Principle II's testing policy, independent review, CI, landing, or release gates. For a feature deliberately split into several PRs, agree on the `## PR-срезы` section in `specs/NNN-<slug>/tasks.md` before coding; each PR gets only its named tasks, write paths, tests, branch and worktree. See `docs/spec-kit-workflow.md`.
- Execution tooling is selected by the work context. Standalone agents may implement from the validated artifacts; opt-in Hermes-managed outcomes additionally follow `.hermes.md`, ADR-0010, and `docs/spec-driven-kanban.md`.
- Before adding or changing a feature spec, run `python3 scripts/check_spec_kit_specs.py` (or `make check-specs`) and preserve documented grandfathering for historical specs.

## Agent Delivery Workflow
- Work in an isolated git worktree and feature branch. Never leave product changes uncommitted in the primary worktree.
- Deliver large features as many small parallel PRs, not a few large ones. Any feature bigger than one reviewable PR gets an approved `## PR-срезы` map (`brainbuddy-pr-slices/v2`): a contract slice first, then backend, web and iOS slices that consume it independently, each within 400 product lines and 12 product files (`scripts/check_slice_budget.py`; tests, docs and specs do not count) and dark behind its flag until the last slice. The planning session acts as conductor (`/speckit-implement all`): it launches one worker per ready slice at the same time, each in its own worktree with distinct data dir, ports and E2E project, and starts the next wave as dependencies merge. It plans and reviews; it does not write slice code.
- Use the cheapest capable model for each role. Planning, spec review, slicing and feature acceptance: the strongest model (Opus in Claude Code). Implementing a slice that changes behavior or a contract: a mid-tier model (Sonnet, `feature-implementer`). Pattern-following slices (renames, fixtures, tests against a frozen contract, docs) and reading long CI or test logs: the smallest model (Haiku, `mechanical-implementer` and `ci-log-triage`). Runtimes without these named agents, such as Codex, apply the same split with their own model choice.
- Classify every change as Ship/Show/Ask (ADR-0008). SHIP (low risk) and SHOW (medium risk) land PR-less via verified trunk: one candidate commit on the current `origin/main`, submitted with `scripts/submit_to_trunk.sh` to a `trunk-candidate/<sha>` ref; full CI runs there (with no write permission and no access to the landing identity — candidate-controlled CI can never promote), and the default-branch release workflow's serialized `land` job fast-forwards `main` to the exact tested SHA, authenticating with the dedicated `TRUNK_LANDING_SSH_KEY` SSH deploy key from the GitHub `landing` environment (branch policy `main` only). No workflow holds `GITHUB_TOKEN` write, and the `main` ruleset MUST keep `restrict_updates` with that deploy key as the only bypass actor and `Full CI` + `Docker Images` required for human/PR paths. The GitHub `production` environment MUST likewise restrict deployments to `main` (custom branch policy) and hold `FLY_API_TOKEN` as an environment secret only — no repository-level `FLY_API_TOKEN` exists — plus the admin/cohort secrets; both are bootstrap verification items, and candidate-controlled CI may request neither the `landing` nor the `production` environment (validator-enforced).
- For an eligible ADR-0023 fast-lane SHIP/SHOW change, freeze one bounded candidate and obtain exactly one independent exact-SHA gate: code review for correctness/contract risk or QA for user-journey/interaction risk. Material mixed risk or an acceptance contract requiring both disciplines moves the outcome to the full path; if the selected gate cannot evaluate the dominant risk, replace it or escalate instead of accumulating another fast-lane gate. Standard authenticated production smoke completes non-user-visible acceptance; every user-visible change is semantically SHOW and adds one bounded production journey. Do not add a protected-browser gate unless identity, permissions, cohort/flag exposure, browser-only behavior, or the accepted outcome requires it.
- ASK scope (ADR-0030, while there are no real users): persisted data and migrations, secrets, every GitHub workflow under `.github/` (workflows can read repository secrets), GDPR account deletion/export, the Allure gate rules (`allurerc.mjs`), and the landing gate itself (`classify_path_risk.py`, `check_gate_integrity.py` and its manifest). Auth/session code, delivery scripts and Docker/Fly configuration are SHIP until ADR-0030's re-tightening trigger — the first real user or valuable data — restores the ADR-0008 scope.
- ASK-class changes never land automatically. A PR carries the review evidence, but — stated honestly — while the landing deploy key is the sole `restrict_updates` bypass actor, no PR merge and no direct human push can update `main`: an ASK landing requires explicit recorded approval, green required CI on the exact SHA, and a short, audited, temporary ruleset intervention (see the runbook; adding a separately accountable human reviewer in the future would restore a merge-behind-required-checks path without weakening the ruleset). This is enforced mechanically: `scripts/classify_path_risk.py` classifies every changed path from NUL-separated `git diff --no-renames --name-only -z` output, `submit_to_trunk.sh` runs it as a non-skippable preflight, and the release workflow's `land` job re-runs the trusted `origin/main` copy before pushing `main` — ASK paths fail automatic promotion closed. A fully green candidate CI run auto-promotes nothing until the default-branch release workflow and the landing identity exist (bootstrap order and the emergency direct-landing audit requirements are in the runbook).
- The default-branch release workflow consumes completed successful push CI runs (`trunk-candidate/<sha>`, or `main` for ASK-class merges): its `land` job (read-only token, `landing` environment, deploy-key push) lands candidates and proves `origin/main` equals the tested SHA for every run, then its `deploy` job (production environment, `contents: read`) re-verifies that proof immediately before any Fly mutation — so stale CI runs can never redeploy an older SHA — checks the smoke admin identity against backend startup rules (email shapes, password policy, internal-cohort membership), then runs reachability plus the authenticated production smoke (which asserts `delivery_canary` is effectively true for the provisioned internal smoke identity, and best-effort cleans up its temporary tree from an EXIT trap, marking cleanup done only after the 404 read-back). Failed smoke rolls back to the captured previous images and the run stays failed. There is no manual production deploy trigger; do not perform an ad-hoc deploy instead of this release path.
- Feature flags are required for significant new capabilities, such as the agent harness, Brain dump and Current Reality Tree. Corrections to expected existing behavior, including completed-task placement and animation, do not require a new flag. Existing feature gates, tests, review, verified delivery and rollback requirements remain unchanged. Flags are never authorization. Owner decision, 2026-09-06: «Давай мы зафиксируем, что флаг нужен для каких-то значительных новых фич, типа агентского харнеса, брейндампа, current reality 3. Вот там вот будут флаги.»
- There are currently no customer or valuable production data: prioritize MVP velocity, but preserve the candidate → CI → landing → verified deploy traceability.

## Codex Model Routing

For Codex, choose the cheapest capable model for the **decisions still open**
in a task. Simple behavior implementation belongs on Luna when the architecture
and contract are already settled. A behavior change alone does not require Sol.
This applies both to ADR-0023's lightweight brief and to an approved Spec Kit
slice; delegation does not require a new spec or another gate.

| Work / role | Model | Reasoning effort |
| --- | --- | --- |
| `mechanical-implementer`: renames, fixtures, pattern-following tests, docs and copy | `gpt-6-luna` | `low` |
| `feature-implementer`: bounded code against a settled architecture, contract, error behavior and acceptance outcome | `gpt-6-luna` | `medium` |
| `ci-log-triage`: extract failures and reproduction commands from saved logs | `gpt-6-luna` | `low` |
| `delivery-verifier`: run selected deterministic checks and report their actual results | `gpt-6-luna` | `low` |
| Planning, slicing, design/contract authoring, implementation with unresolved design choices or difficult debugging | `gpt-6-sol` | `high` |
| Independent code review or feature acceptance against the accepted scope | `gpt-6-sol` | `high` |
| Novel architecture or adversarial review with material security, privacy, data-loss, concurrency or irreversible-effect risk | `gpt-6-astra` | `high` |

Use the model IDs exposed by the active runtime. Prefer `gpt-6.1-sol` over
`gpt-6-sol` when it is available. If a listed model is unavailable, select the
next available capable tier and report the substitution; never silently
downgrade a contract or review task to Luna. Terra may serve the strongest
role when the runtime exposes it; do not invent a Terra ID or assume a CLI's
bundled catalog proves account access. Increase effort above `high` only for
a specific unresolved problem, rather than using `xhigh`/`max` for every task.

### Handoff and escalation

- Before delegating implementation, give the worker the accepted outcome,
  absolute worktree path and base SHA, owned write paths, the relevant brief
  or spec/slice and settled contracts, the nearest existing implementation
  pattern, and the sufficient checks. A Luna worker can add simple behavior
  and its necessary tests; it does not choose new boundaries, persistence
  semantics, auth rules, API shapes or recovery behavior.
- When a Luna worker discovers an undecided contract, a required out-of-scope
  edit, or a failure it cannot explain from the existing pattern, it stops
  that part and returns the concrete question and evidence. The conductor
  resolves it with Sol (Astra for the material risks above), then resumes the
  bounded implementation with the decision supplied. Do not spend repeated
  Luna attempts guessing at the same problem.
- With `collaboration.spawn_agent`, pass `model` and `reasoning_effort`
  explicitly according to the table and use `fork_turns: "none"` for a
  bounded handoff. A full-history fork inherits the parent model and cannot
  select a cheaper one. Include the instruction to read `AGENTS.md` and any
  applicable nested instructions; a fresh worker has no conversation history.
- `.codex/config.toml` enables model overrides and defaults otherwise
  unspecified subagents to Luna/medium in a trusted Codex CLI project. It
  leaves the parent model and execution permissions to the active session.
  Explicitly select Sol/Astra for the roles above; the Luna default is not
  suitable for independent review or architecture decisions. In a hosted
  runtime, use its spawn controls; project CLI settings alone do not configure
  hosted agents. Without model-selecting subagents, use a dedicated worker
  session with `codex -C <worktree> -m <model> -c 'model_reasoning_effort="<effort>"'`,
  or report that tiered execution is
  unavailable instead of claiming a model switch occurred.
- Give every implementation worker its own branch/worktree. Run independent
  approved slices concurrently only with disjoint write paths and isolated
  data directories, ports and E2E artifacts; dependent slices wait for their
  accepted base. Codex CLI permits up to 12 concurrent agent threads per
  session (the conductor plus up to 11 workers)
  via `features.multi_agent_v2.max_concurrent_threads_per_session`. Launch
  ready independent slices up to the active runtime's available slots,
  starting the next ready slice as a slot becomes free; do not wait for a
  whole wave when another independent slice can start. Finish idle workers
  using the runtime's completion/close controls when available so they do
  not hold open-thread capacity after their handoff is complete.
  Hosted-session limits take precedence and cannot be raised by this file.
  Keep trivial prompt/config/docs edits direct. Return only
  the commit SHA, changed paths, check results, log paths and unresolved
  decisions, keeping long logs in files.
- A verifier running commands does not grade acceptance. The independent
  reviewer must differ from the writer and review the frozen exact SHA.
  ADR-0023 still selects one gate for eligible fast-lane changes. On the full
  planning-review path, use the canonical `/speckit-review` harness and its
  recorded model provenance; this table does not replace its `ROLE_CONFIGS`
  or authorize skipping a required lens. ADR-0030 risk classification,
  exact-SHA CI, verified landing and production smoke still apply.

## Active Technologies

`.specify/scripts/bash/update-agent-context.sh` appends here on `/speckit-plan`.
It had accumulated fifteen near-identical lines naming four features that no
longer exist under `specs/` — pruned 2026-08-13. Prune again rather than letting
it grow; this is a summary, not an append-only log.

- Backend: Python 3.11, FastAPI, Pydantic, pytest. Layered `app/api/` ->
  `app/services/` -> `app/repositories/`, wired in `app/container.py`.
- Frontend: TypeScript (strict), React, Vite, Zustand, React Query, Tailwind;
  Vitest + Testing Library, Playwright for e2e.
- iOS: SwiftUI (iOS 26), XcodeGen, `BrainBuddyKit` Swift package. See
  `ios/AGENTS.md`.
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
