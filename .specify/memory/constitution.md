<!--
Sync Impact Report:
- Version change: 1.1.0 -> 1.1.1
- Modified principles: I. Data Consent & Safety; II. Tested Delivery Across Stack; III. Contract-First Interfaces; IV. Traceable & Actionable Observability; V. Responsive, Resilient Experience -> Responsive, Resilient, Mobile-First Experience
- Added sections: Spec-Driven Development Workflow; Historical Spec Grandfathering
- Removed sections: None
- Templates requiring updates: ✅ .specify/templates/plan-template.md; ✅ .specify/templates/spec-template.md; ✅ .specify/templates/tasks-template.md; ✅ .specify/templates/checklist-template.md; ✅ .claude/skills/speckit-* and .agents/skills/speckit-* refreshed from github/spec-kit v0.15.0
- Follow-up TODOs: None
-->
# BrainBuddy Constitution

## Core Principles

### I. Data Consent & Safety
Protect user trust by defaulting to local control, explicit consent, and reversible user authority before data leaves the device or becomes a durable side effect.
- AI, transcription, or other remote processing MUST require current user consent and configured provider credentials; requests without consent or required configuration MUST fail visibly instead of silently uploading or degrading.
- Voice brain dumps and voice-led Weekly Review MUST preserve the ADR-0002 operation contract: provisional model output stays in the operation workspace until explicit confirmation applies frozen actions through domain ports.
- Raw audio, transcripts, credentials, local file paths, content hashes usable as fingerprints, and real user data MUST NOT enter logs, metrics, committed fixtures, or PR evidence.
- Cloud persistence, external task routing, CRT promotion, destructive edits, and delete/undo behavior MUST be user-visible, idempotent where applicable, and auditable.

### II. Tested Delivery Across Stack
Changes ship only with targeted automated validation covering the affected backend, frontend, workflow, and documentation gates.
- New or changed behavior MUST include failing-then-passing tests or an explicitly documented non-code verification path when the change is docs/tooling only.
- Backend behavior uses pytest/FastAPI TestClient; frontend behavior uses Vitest + Testing Library; CI coverage, lint, type, build, and smoke gates MUST be kept green before merge.
- AI, persistence, voice, routing, and operation flows MUST cover edge cases for invalid payloads, timeouts, consent denial, idempotency, retries, cancellation, and partial failure.
- Refactors without behavior change still require deterministic guardrails proving parity.

### III. Contract-First Interfaces
Shared contracts are the source of truth and cannot drift across tiers, agents, or planning artifacts.
- Backend schemas and API contracts MUST be updated before frontend/client code depends on changed shapes; breaking changes require migration notes and compatibility strategy.
- ADR-0001 module ownership and ADR-0002 async-operation contracts are binding until superseded by a new accepted decision record.
- Specs, plans, and tasks MUST reference real file paths and explicit contracts rather than vague placeholders once a feature moves past specification.
- APIs and client-visible failures MUST return actionable errors with correlation IDs that remain usable for retry and reporting.

### IV. Traceable & Actionable Observability
Every request, operation, route, and review action must be diagnosable without exposing user content.
- Backend responses MUST include `X-Correlation-ID`; accepted client-supplied IDs are observability labels only and never authorization or idempotency inputs.
- Long-running capture, review, AI, import/export, and save flows MUST expose progress, retry state, cancellation state, and partial-failure evidence.
- Logs, metrics, and operation events MUST contain IDs, timings, coarse confidence/error bands, and stage names rather than raw user text or media.
- Debug/profiling hooks may exist in development, but production UX must remain clean and privacy-preserving.

### V. Responsive, Resilient, Mobile-First Experience
BrainBuddy vNext is optimized for fast capture and review from mobile-first voice workflows while preserving the existing responsive CRT canvas.
- The primary product loop is voice/text capture -> atomic items -> clarify/approve -> route or CRT candidate -> smart Weekly Review -> evidence/results. Feature specs MUST state how they affect this loop or declare no impact.
- Recording, upload, provisional transcript/candidate display, confirmation, cancellation, and resume behavior MUST tolerate mobile interruptions, offline windows, and UI closure per ADR-0002.
- Canvas interactions MUST remain perceptually responsive on approximately 200-node trees; regressions require remediation before release.
- Local drafts, operation checkpoints, and confirmed domain records MUST avoid data loss and warn before destructive navigation or side effects.

## Spec-Driven Development Workflow
GitHub Spec Kit is the mandatory authoring workflow for every new or materially changed BrainBuddy feature spec.
- The canonical artifact flow is constitution -> `/speckit-specify` (what/why) -> `/speckit-clarify` -> `/speckit-plan` (how/architecture) -> `/speckit-checklist` -> `/speckit-tasks` -> `/speckit-analyze`.
- Use the official `github/spec-kit` CLI pinned to the repository-documented version through isolated `uv tool`/`uvx`; do not install it into application backend/frontend environments.
- `specs/` contains the versioned Spec Kit artifacts. Implementation intent changes MUST amend the relevant spec/plan/tasks before product code proceeds.
- Generated `tasks.md` is portable planning input organized by user story, dependency, and concrete file path. It does not bypass isolated worktrees, TDD, independent review, CI, landing, or release gates.
- Spec Kit is not an execution orchestrator for BrainBuddy. Implementation may be performed by a developer or standalone agent. An explicitly activated managed outcome may add a separate control-plane overlay without changing these repository-wide rules.

## Historical Spec Grandfathering
The repository contains pre-adoption specs and requirements that must remain readable without forcing unsafe regeneration.
- `specs/001-relation-linking-refactor/` is already a complete historical Spec Kit-style directory and remains valid.
- `specs/002-async-voice-workflows/` predates this v0.12.17 adoption and is grandfathered with `spec.md` plus `acceptance-tests.md`; do not fabricate missing generated artifacts unless the feature is materially changed.
- Historical `requirements/` documents are background context only where they conflict with ADR-0001, ADR-0002, the current constitution, or current specs.
- New `specs/[NNN-feature]/` directories after this adoption MUST include the documented minimum Spec Kit artifacts and pass the repository spec check.

## Operational Guardrails
Security, configuration, delivery, and release constraints apply to all work.
- Follow `.env.example` for environment setup; never hardcode secrets. Compose and Fly deployments MUST respect API key and session-auth controls.
- Backend data persists under `backend/data` with an LRU cache and optional volumes; treat stored data as sensitive and keep it out of version control.
- Frontend defaults to `/api`; remote stacks require explicit proxy/origin configuration that preserves cookies and same-origin behavior where expected.
- PRs are the merge gate: work happens in isolated branches/worktrees, CI must pass, review must complete, and `main` deploys through the normal Fly release path.

## Development Workflow & Quality Gates
How features are specified, planned, implemented, reviewed, and released.
- Start feature work by inspecting `.specify/memory/constitution.md`, `docs/decisions/`, and the relevant `specs/` directory before editing code.
- Specs MUST define independently testable user stories, acceptance scenarios, edge cases, consent/privacy impact, observability impact, and success criteria.
- Plans MUST document architecture, contract changes, persistence ownership, test strategy, release/smoke validation, and any justified constitution complexity.
- Tasks MUST be grouped by independently shippable user story, include concrete file paths, and preserve tests-before-implementation ordering unless the spec explicitly waives tests.
- Reviews MUST block on constitution compliance, Spec Kit artifact completeness, ADR alignment, consent enforcement, contract alignment, dual-stack validation, observability, and performance/mobile resilience.

## Governance
This constitution supersedes conflicting local practices and guides all reviews.
- Amendments require a documented proposal or PR rationale referencing affected principles, impact analysis, updated dependent templates/docs, and preserved history in this file.
- Versioning follows semantic rules: MAJOR for breaking governance changes, MINOR for new principles/sections or materially expanded requirements, PATCH for clarifications.
- Compliance reviews occur on every PR and before releases; violations need documented justification plus a remediation plan and owner.
- Accepted ADRs under `docs/decisions/` may refine this constitution for their decision scope, but broad governance changes belong here.

**Version**: 1.1.1 | **Ratified**: 2025-12-20 | **Last Amended**: 2026-08-08
