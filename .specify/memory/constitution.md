<!--
Sync Impact Report:
- Version change: 1.2.0 -> 2.0.0
- Why MAJOR: ADR-0023 deliberately removes the universal full Spec Kit campaign
  and duplicate review-plus-QA expectation for eligible bounded SHIP/SHOW work.
  That is a breaking governance change even though exact-SHA delivery safeguards
  remain unchanged.
- Modified principles: None
- Modified sections: Spec-Driven Development Workflow; Operational Guardrails;
  Development Workflow & Quality Gates; Governance
- Added sections: None
- Removed sections: None
- Dependent docs updated: AGENTS.md, .hermes.md,
  docs/autonomous-delivery-runbook.md, docs/spec-kit-workflow.md,
  docs/spec-driven-kanban.md, docs/fly-deployment.md, README.md,
  .specify/workflows/speckit/workflow.yml, and its synchronized registry entry
- Templates requiring updates: None. Existing templates remain authoritative for
  the full Spec Kit path; the fast lane does not generate partial Spec Kit artifacts.
- Follow-up TODOs: None
- Superseded report preserved in git history: 1.1.1 -> 1.2.0 introduced the
  mandatory design citation and portable five-lens review gate and corrected the
  verified-trunk wording after ADR-0008.
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
GitHub Spec Kit is the mandatory full authoring workflow when any canonical ADR-0023 trigger applies: a significant new capability, a cross-surface contract change, a persistence/schema change, a materially changed workflow/state-machine boundary, or any ASK-class outcome. Eligible bounded SHIP/SHOW changes use ADR-0023's lightweight brief instead.
- When the full path applies, the canonical artifact flow is constitution -> `/speckit-specify` (what/why) -> `/speckit-clarify` -> `/speckit-design` (user-visible surfaces) -> `/speckit-plan` (how/architecture) -> `/speckit-review` -> `/speckit-checklist` -> `/speckit-tasks` -> `/speckit-analyze`. `/speckit-design` and the ADR-0011 `/speckit-review` gate are not optional additions to the upstream core: a plan MUST cite `design.md` when the feature has a user-visible surface, and implementation MUST NOT begin on a review verdict other than `approved` or `founder-accepted`. `docs/spec-kit-workflow.md` carries the full thirteen-stage path including the optional stage 0 assessment.
- Use the official `github/spec-kit` CLI pinned to the repository-documented version through isolated `uv tool`/`uvx`; do not install it into application backend/frontend environments.
- `specs/` contains the versioned Spec Kit artifacts. Implementation intent changes MUST amend the relevant spec/plan/tasks before product code proceeds.
- Generated `tasks.md` is portable planning input organized by user story, dependency, and concrete file path. It does not bypass isolated worktrees, TDD, ADR-0023's applicable independent gate, CI, landing, or release gates.
- Spec Kit is not an execution orchestrator for BrainBuddy. Implementation may be performed by a developer or standalone agent. An explicitly activated managed outcome may add a separate control-plane overlay without changing these repository-wide rules.

## Historical Spec Grandfathering
The repository contains pre-adoption specs and requirements that must remain readable without forcing unsafe regeneration.
- `specs/001-relation-linking-refactor/` is already a complete historical Spec Kit-style directory and remains valid.
- `specs/002-async-voice-workflows/` predates the Spec Kit adoption (ADR-0005) and is grandfathered with `spec.md` plus `acceptance-tests.md`; do not fabricate missing generated artifacts unless the feature is materially changed. The repository pin has moved twice since that adoption and is recorded in `docs/spec-kit-workflow.md`, not here.
- Historical `requirements/` documents are background context only where they conflict with ADR-0001, ADR-0002, the current constitution, or current specs.
- New `specs/[NNN-feature]/` directories after this adoption MUST include the documented minimum Spec Kit artifacts and pass the repository spec check.

## Operational Guardrails
Security, configuration, delivery, and release constraints apply to all work.
- Follow `.env.example` for environment setup; never hardcode secrets. Compose and Fly deployments MUST respect API key and session-auth controls.
- Backend data persists under `backend/data` with an LRU cache and optional volumes; treat stored data as sensitive and keep it out of version control.
- Frontend defaults to `/api`; remote stacks require explicit proxy/origin configuration that preserves cookies and same-origin behavior where expected.
- Verified CI on the exact landed SHA is the merge gate, not a pull request. Work happens in isolated branches/worktrees; every change is classified Ship/Show/Ask under ADR-0008. Eligible SHIP and SHOW work uses ADR-0023's one risk-selected independent gate, then lands PR-less through `scripts/submit_to_trunk.sh` and the default-branch release workflow, which fast-forwards `main` only to a SHA that passed full required CI. ASK-class changes (auth/privacy, destructive data/schema, billing/provider credentials, CI/CD/security/infra, irreversible external effects) never land automatically: a PR carries their review evidence, but merging it does not by itself update `main` — see `AGENTS.md` and `docs/autonomous-delivery-runbook.md` for the recorded-approval and ruleset requirements. `main` deploys through the normal Fly release path in both cases.

## Development Workflow & Quality Gates
How features are specified, planned, implemented, reviewed, and released.
- Start work by inspecting `.specify/memory/constitution.md`, relevant accepted ADRs, and any existing feature artifacts. Create the full Spec Kit set only when ADR-0023's full-path triggers apply.
- Specs MUST define independently testable user stories, acceptance scenarios, edge cases, consent/privacy impact, observability impact, and success criteria.
- Plans MUST document architecture, contract changes, persistence ownership, test strategy, release/smoke validation, and any justified constitution complexity.
- Tasks MUST be grouped by independently shippable user story, include concrete file paths, and preserve tests-before-implementation ordering unless the spec explicitly waives tests.
- The applicable independent gate MUST block on constitution compliance, ADR alignment, consent enforcement, contract alignment, affected-stack validation, observability, and performance/mobile resilience. Full-path reviews additionally block on Spec Kit artifact completeness.

## Governance
This constitution supersedes conflicting local practices and guides all reviews.
- Amendments require a documented proposal or PR rationale referencing affected principles, impact analysis, updated dependent templates/docs, and preserved history in this file.
- Versioning follows semantic rules: MAJOR for breaking governance changes, MINOR for new principles/sections or materially expanded requirements, PATCH for clarifications.
- Compliance is checked by ADR-0023's risk-selected independent gate before SHIP/SHOW release and by the full review path for ineligible or ASK work; violations need documented justification plus a remediation plan and owner.
- Accepted ADRs under `docs/decisions/` may refine this constitution for their decision scope, but broad governance changes belong here.

**Version**: 2.0.0 | **Ratified**: 2025-12-20 | **Last Amended**: 2026-09-16
