# Implementation Plan: [FEATURE]

**Branch**: `[###-feature-name]` | **Date**: [DATE] | **Spec**: [link]

**Input**: Feature specification from `/specs/[###-feature-name]/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.
Amend the spec first when implementation intent changes.

## Summary

[Extract from feature spec: primary requirement + technical approach from research]

## Technical Context

<!--
  ACTION REQUIRED: Replace the content in this section with the technical details
  for the project. The structure here is presented in advisory capacity to guide
  the iteration process.
-->

**Language/Version**: [e.g., Python 3.11, Swift 5.9, Rust 1.75 or NEEDS CLARIFICATION]

**Primary Dependencies**: [e.g., FastAPI, UIKit, LLVM or NEEDS CLARIFICATION]

**Storage**: [if applicable, e.g., PostgreSQL, CoreData, files or N/A]

**Testing**: [e.g., pytest, XCTest, cargo test or NEEDS CLARIFICATION]

**Target Platform**: [e.g., Linux server, iOS 15+, WASM or NEEDS CLARIFICATION]

**Project Type**: [e.g., library/cli/web-service/mobile-app/compiler/desktop-app or NEEDS CLARIFICATION]

**Performance Goals**: [domain-specific, e.g., 1000 req/s, 10k lines/sec, 60 fps or NEEDS CLARIFICATION]

**Constraints**: [domain-specific, e.g., <200ms p95, <100MB memory, offline-capable or NEEDS CLARIFICATION]

**Scale/Scope**: [domain-specific, e.g., 10k users, 1M LOC, 50 screens or NEEDS CLARIFICATION]

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- Spec workflow: Is the relevant `specs/[###-feature]/spec.md` current, and are
  clarification outcomes reflected before planning implementation?
- Consent & Safety: How will data stay local-first, with explicit consent and
  provider/API-key enforcement where needed? Confirm no real data, secrets, raw
  audio/transcripts, paths, or content fingerprints are committed/logged.
- Tests: What backend (pytest/FastAPI TestClient), frontend (Vitest + Testing
  Library), operation, or documentation checks will fail first and then pass?
  Include edge cases for AI/persistence/voice/routing flows.
- Contracts: Which schemas/endpoints/events/state machines change, and how will
  compatibility be preserved across backend, frontend, and generated specs?
- Observability: How will correlation IDs, structured redacted logs, progress,
  retry, cancellation, and actionable errors surface for this work?
- Mobile/resilience/performance: How will mobile capture/review interruptions,
  offline windows, data-loss protections, and ~200-node canvas responsiveness be
  maintained?
- Delivery boundary: Confirm Spec Kit tasks are portable planning input only;
  isolated worktrees, TDD, independent verification, ADR-0008 landing, CI, and
  Fly release gates remain authoritative regardless of execution tooling.
- Design citation: For any feature with a user-visible surface, this plan MUST
  cite `specs/[###-feature]/design.md` and name the specific screen and state
  ids (`D-01`, `M-01`, …) each implementation section realizes. A feature with
  no user-visible surface MUST say so explicitly here. Silence fails the gate:
  the acceptance auditor traces criteria through those ids, and an uncited
  design cannot be graded.

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)
<!--
  BrainBuddy override: real repository layout. Upstream ships a generic
  Option 1/2/3 placeholder tree that matches nothing in this repo; a plan built
  from it names directories that do not exist, which the architecture-consistency
  reviewer then rejects. Delete the branches this feature does not touch and
  expand the ones it does with real file paths.
-->

```text
backend/
├── app/
│   ├── api/            # FastAPI routes, request/response coercion
│   ├── services/       # business logic, orchestration, LRU cache
│   ├── repositories/   # file I/O under backend/data/
│   ├── schemas/        # domain.py (Pydantic domain) + api.py (contracts)
│   ├── ai/providers/   # base.py | mock.py | openai.py
│   ├── modules/tasks/  # self-contained GTD module (service, repo, domain)
│   └── container.py    # dependency injection: repositories -> services -> routers
└── tests/              # pytest, mirrors module name (test_tree_service.py)

frontend/
├── src/
│   ├── api/            # typed client + React Query hooks (useTree, useTrees)
│   ├── stores/         # treeStore.ts, uiStore.ts (Zustand)
│   ├── components/     # TreeCanvas, InspectorTabs, NodeInspector, ...
│   └── **/__tests__/   # Vitest + Testing Library
└── tests/              # Playwright e2e

mobile/
├── src/                # Expo / React Native, iOS-first
│   └── **/__tests__/   # Jest
└── integration/        # real api client vs a disposable local backend

specs/[###-feature]/    # this feature's Spec Kit artifacts
docs/decisions/         # ADRs — accepted records bind the plan
scripts/                # delivery, validation and evidence tooling (ASK class)
```

**Structure Decision**: [Name the directories this feature actually touches and
why. Every path listed must exist or be created by this plan; the
architecture-consistency reviewer verifies them against the repository.]

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |
