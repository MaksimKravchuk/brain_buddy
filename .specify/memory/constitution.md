<!--
Sync Impact Report:
- Version change: unversioned -> 1.0.0
- Modified principles: New -> I. Data Consent & Safety; II. Tested Delivery Across Stack; III. Contract-First Interfaces; IV. Traceable & Actionable Observability; V. Responsive, Resilient Experience
- Added sections: Operational Guardrails; Development Workflow & Quality Gates
- Removed sections: None
- Templates requiring updates: ✅ .specify/templates/plan-template.md; ✅ .specify/templates/spec-template.md; ✅ .specify/templates/tasks-template.md; ⚠ .specify/templates/commands (directory absent)
- Follow-up TODOs: None
-->
# Brain Buddy Constitution

## Core Principles

### I. Data Consent & Safety
Protect user trust by defaulting to local control and explicit consent before sending data anywhere.
- AI or remote processing MUST require per-request consent and API key pairing (`BRAIN_BUDDY_API_KEY` + `VITE_API_KEY` when enforced); decline requests if consent or keys are missing.
- Data remains local-first with 5s autosave and exit warnings; cloud sync only when signed in and confirmed.
- Never commit real user data or secrets; use `.env.example`, local volumes under `backend/data`, and scrub logs to avoid sensitive payloads.

### II. Tested Delivery Across Stack
Changes ship only with targeted, automated validation covering both backend and frontend.
- New or changed behavior MUST include failing-then-passing tests (pytest/FastAPI TestClient, Vitest + Testing Library); run `make test-backend` and `make test-frontend` before merge.
- AI or persistence flows MUST carry contract/edge-case coverage (invalid payloads, timeouts, consent required).
- Refactors without behavior change still require guardrails (smoke/contract tests) proving parity.

### III. Contract-First Interfaces
Shared JSON payloads and schemas are the source of truth and cannot drift across tiers.
- Define and evolve schemas in `backend/app/schemas`; any breaking change requires migration notes, frontend alignment, and backwards-compatibility strategy.
- APIs MUST return actionable errors with correlation IDs; client handling MUST preserve these for reporting and retries.
- Exports/imports MUST round-trip node types, relations, and colors without loss.

### IV. Traceable & Actionable Observability
Every request and client action must be traceable, diagnosable, and recoverable.
- Emit structured logs with `X-Correlation-ID` through backend and surface the ID in user-facing errors/toasts.
- Add progress and retry affordances for networked/AI actions; failures MUST not drop user work.
- Profiling and debug hooks (e.g., canvas render timings) stay available in development without polluting production UX.

### V. Responsive, Resilient Experience
The canvas and API must remain responsive for large trees and never trade speed for data safety.
- Interactions (zoom, select, highlight) MUST remain perceptually responsive on ~200-node trees; regressions require remediation before release.
- Long-running actions (AI, import/export, saves) MUST stream or signal status and be cancellable or safely retryable.
- Local drafts and cloud saves MUST avoid data loss; warnings are mandatory before any destructive navigation.

## Operational Guardrails
Security, configuration, and data-handling constraints that apply to all work.
- Follow `.env.example` for environment setup; never hardcode secrets. Compose and Fly deployments MUST respect API key pair enforcement when enabled.
- Backend data persists under `backend/data` with an LRU cache; treat the volume as sensitive and keep it out of version control.
- Frontend defaults to `/api`; configure `VITE_API_BASE_URL` when pointing to remote stacks and ensure matching CORS/API key headers.
- CI gates (lint/type/test/build) are required before deploys; smoke tests via `./scripts/smoke_test.sh` or compose MUST pass for release candidates.

## Development Workflow & Quality Gates
How features are specified, planned, implemented, and reviewed.
- Specs MUST define independently testable user stories and acceptance scenarios; plans/tasks MUST keep stories deliverable in isolation.
- Tasks and commits MUST reference real file paths and group work by user story; tests for each story are expected unless explicitly waived in the spec.
- Reviews MUST block on constitution compliance: consent enforcement, contract alignment, dual-stack tests, observability hooks, and performance budgets.
- Use `make dev-backend` / `make dev-frontend` for local work; run backend/frontend test suites plus targeted smoke checks before merge or deploy.

## Governance
This constitution supersedes other practices where conflicts exist and guides all reviews.
- Amendments require a documented proposal referencing affected principles, impact analysis, and updated templates; maintain change history in this file.
- Versioning follows semantic rules: MAJOR for breaking governance changes, MINOR for new principles/sections, PATCH for clarifications.
- Compliance reviews occur on every PR and before releases; violations need documented justification plus a remediation plan and timeline.

**Version**: 1.0.0 | **Ratified**: 2025-12-20 | **Last Amended**: 2025-12-20
