<!--
Sync Impact Report
- Version change: placeholder -> 1.0.0
- Modified principles: initialized (new)
- Added sections: Quality Gates & Tooling Requirements; Delivery Workflow & Review Expectations
- Removed sections: Placeholder principle slots beyond the four defined pillars
- Templates requiring updates: DONE .specify/templates/plan-template.md; DONE .specify/templates/spec-template.md; DONE .specify/templates/tasks-template.md; REVIEW .specify/templates/checklist-template.md (reviewed, no edits needed); REVIEW .specify/templates/agent-file-template.md (reviewed, no edits needed)
- Follow-up TODOs: TODO(RATIFICATION_DATE): Original ratification date not yet recorded
-->

# Brain Buddy Constitution

## Core Principles

### I. Code Quality & Maintainability

- Every change MUST pass formatters/linters/type checks (Black, Ruff, mypy for backend; ESLint/Prettier/TypeScript strict for frontend) before review, or the break-glass rationale is recorded in the PR.
- Modules MUST follow established patterns (FastAPI repositories/services, shared schemas; React components/hooks/stores) and keep changes scoped with clear ownership; data contracts require synchronized backend schemas and frontend types.
- Comments stay purposeful and focused on intent or edge cases; config/env updates MUST mirror `.env.example` and relevant docs.
Rationale: Consistent patterns and static analysis keep the codebase approachable, reduce regressions, and make cross-surface work predictable.

### II. Test Discipline & Coverage

- New or changed behavior MUST ship with automated tests: pytest + FastAPI TestClient for backend, Vitest + Testing Library for frontend; integration/smoke coverage is required when touching API contracts or cross-surface flows.
- Tests MUST be deterministic, include realistic fixtures, and exercise error handling (e.g., correlation IDs and retry paths). Update or add fixtures when schemas change.
- CI/PR gates MUST run `make test-backend` and `make test-frontend`; red-green cycles are expected for new work, and skipped tests require documented justification.
Rationale: Reliable, repeatable tests are the primary guardrail against regressions across services and UI.

### III. User Experience Consistency

- UI changes MUST align with existing patterns (top bar, side panels, canvas interactions, toast-driven retries, modal flows) and keep copy consistent with current terminology.
- Accessibility and responsiveness are mandatory: focus states, keyboard navigation for interactive controls, sensible ARIA labels for canvas controls, and layouts that work down to tablet widths without overlap.
- Error surfaces MUST include actionable guidance and correlation references when available; new UX flows require acceptance criteria that include success, failure, and empty states.
Rationale: Consistent, accessible UX keeps the canvas usable under load and ensures errors are recoverable without developer intervention.

### IV. Performance & Reliability Budgets

- Large-graph interactions (200+ nodes) MUST avoid regressions against current baselines: aim for <=20 ms average render steps in development (per `useGraphProfiler`) and avoid blocking the main thread with heavy selectors.
- Backend hot paths (tree reads/writes) SHOULD keep local p95 latency under 200 ms; caching (e.g., TreeService LRU) and async I/O should be preserved or improved when modifying these flows.
- New features MUST declare measurable performance expectations in their specs and validate with profiling traces (frontend) or timings/logs (backend) when touching hot paths.
Rationale: Documented budgets prevent silent performance drift and keep the product responsive for large canvases and frequent tree access.

## Quality Gates & Tooling Requirements

- Formatting, linting, and type-checking are mandatory pre-merge steps for all touched surfaces.
- Update documentation and `.env.example` alongside behavior or configuration changes; keep API contract updates synchronized across backend schemas and frontend types/clients.
- Feature work MUST reference the relevant requirements doc and record architecture or performance considerations in the feature spec/plan.

## Delivery Workflow & Review Expectations

- Plans/specs MUST enumerate test coverage (unit/integration/smoke) and expected UX/performance outcomes before implementation starts.
- Code reviews check for constitution alignment: static analysis status, test depth, UX consistency, and stated performance budgets with evidence where applicable.
- Breaking changes or cross-service impacts require migration notes and manual verification steps (e.g., smoke test runbook) attached to the PR.

## Governance

- This constitution supersedes other practice notes; deviations require explicit, time-bound exceptions recorded in PRs or runbooks.
- Amendment procedure: propose a change with rationale, impacted principles/sections, version bump type, and validation plan; maintainers review and approve before adoption.
- Versioning: MAJOR for removals or incompatible redefinitions; MINOR for added/expanded principles; PATCH for clarifications. Last amended date updates with every approved change.
- Compliance review: Each PR owner ensures quality gates, tests, UX acceptance, and performance budgets are addressed; reviewers verify evidence or request follow-up tasks.

**Version**: 1.0.0 | **Ratified**: TODO(RATIFICATION_DATE): Original adoption date not yet recorded | **Last Amended**: 2025-12-03
