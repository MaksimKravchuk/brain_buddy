# Tasks: Local Deployment Setup

**Input**: Design documents from `/specs/001-local-deploy-setup/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/, quickstart.md

**Tests**: No new automated tests requested; validation relies on documented health checks and smoke script runs.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions (absolute paths used below)

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish baseline docs and configs needed by all stories

- [x] T001 Create deployment runbook scaffold in /Users/max/Code/brain_buddy/docs/runbooks/local-deployment.md
- [x] T002 [P] Ensure required local env variables are listed with safe defaults in /Users/max/Code/brain_buddy/.env.example
- [x] T003 [P] Verify compose stack references expected env/volumes and note overrides in /Users/max/Code/brain_buddy/compose.yaml

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core setup steps that must precede story work

- [x] T004 Add compose entry (or confirm existing) for local stack startup notes in /Users/max/Code/brain_buddy/Makefile
- [x] T005 [P] Document smoke test usage for local validation in /Users/max/Code/brain_buddy/docs/runbooks/local-deployment.md
- [x] T006 [P] Add port/resource matrix for local stack to /Users/max/Code/brain_buddy/docs/runbooks/local-deployment.md

**Checkpoint**: Foundation ready - user story implementation can now begin

---

## Phase 3: User Story 1 - Spin up local deployment quickly (Priority: P1) 🎯 MVP

**Goal**: A clean machine can follow one path to running backend/frontend locally.
**Independent Test**: Follow the documented steps on a clean environment and reach a healthy stack at the documented endpoints.

### Implementation for User Story 1

- [x] T007 [US1] Write step-by-step initial deploy instructions using compose in /Users/max/Code/brain_buddy/docs/runbooks/local-deployment.md
- [x] T008 [P] [US1] Add env variable descriptions and sample values for first-time setup in /Users/max/Code/brain_buddy/docs/runbooks/local-deployment.md
- [x] T009 [P] [US1] Document health check procedure including ./scripts/smoke_test.sh and frontend URL in /Users/max/Code/brain_buddy/docs/runbooks/local-deployment.md
- [x] T010 [US1] Add verification checklist for ready state in /Users/max/Code/brain_buddy/docs/runbooks/local-deployment.md

**Checkpoint**: US1 independently testable via quickstart + health checks

---

## Phase 4: User Story 2 - Redeploy after code changes (Priority: P2)

**Goal**: Apply new commits locally with a short, predictable refresh flow.
**Independent Test**: Modify code, run refresh workflow, and observe updated behavior within target time.

### Implementation for User Story 2

- [x] T011 [US2] Document refresh workflow using compose rebuild/restart and dev server alternatives in /Users/max/Code/brain_buddy/docs/runbooks/local-deployment.md
- [x] T012 [P] [US2] Add timing guidance and cache reuse tips to meet <5 minute refresh in /Users/max/Code/brain_buddy/docs/runbooks/local-deployment.md
- [x] T013 [P] [US2] Note branch/current-code expectations and avoidance of manual file copy in /Users/max/Code/brain_buddy/docs/runbooks/local-deployment.md
- [x] T014 [US2] Add post-refresh validation steps (smoke + UI) in /Users/max/Code/brain_buddy/docs/runbooks/local-deployment.md

**Checkpoint**: US2 independently testable by running refresh steps and re-validating

---

## Phase 5: User Story 3 - Diagnose and recover (Priority: P3)

**Goal**: Troubleshoot local deployment failures quickly and restore to known-good state.
**Independent Test**: Introduce a common failure (e.g., missing env), apply playbook, and confirm recovery.

### Implementation for User Story 3

- [x] T015 [US3] Document port conflict detection and resolution steps in /Users/max/Code/brain_buddy/docs/runbooks/local-deployment.md
- [x] T016 [P] [US3] Add stale volume/cache reset steps (compose down -v, npm/yarn cache guidance) in /Users/max/Code/brain_buddy/docs/runbooks/local-deployment.md
- [x] T017 [P] [US3] Add env mismatch diagnostics and log inspection pointers in /Users/max/Code/brain_buddy/docs/runbooks/local-deployment.md
- [x] T018 [US3] Provide recovery checklist to return to known-good state in /Users/max/Code/brain_buddy/docs/runbooks/local-deployment.md

**Checkpoint**: US3 independently testable by resolving simulated failures via documented steps

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Improve discoverability and alignment

- [x] T019 [P] Link local deployment runbook from /Users/max/Code/brain_buddy/README.md for discoverability
- [ ] T020 Validate quickstart end-to-end timings and record results in /Users/max/Code/brain_buddy/docs/runbooks/local-deployment.md
- [x] T021 [P] Reconcile /Users/max/Code/brain_buddy/.env.example with runbook to ensure no drift

---

## Dependencies & Execution Order

- Setup → Foundational → US1 → US2 → US3 → Polish
- US2 depends on completion of US1 quickstart path; US3 depends on US1 health checks (needs baseline state). US2 and US3 can proceed in parallel after US1 if capacity allows.

## Parallel Opportunities

- T002/T003 can run parallel to T001; T005/T006 can run parallel to T004.
- Within US1: T008 and T009 parallel after T007 scaffold.
- Within US2: T012 and T013 parallel after T011.
- Within US3: T016 and T017 parallel after T015.
- Polish: T019 and T021 parallel to T020 measurement.

## Independent Test Criteria per User Story

- **US1**: Follow runbook from clean env; stack reachable at documented endpoints; health checks pass.
- **US2**: After code change, run refresh steps; updated behavior visible; completion under 5 minutes.
- **US3**: Induce failure (missing env/port conflict); apply playbook; stack returns to healthy state.

## Suggested MVP Scope

- Deliver Phase 3 (US1) as MVP: one-path local setup with health validation.

## Format Validation

- All tasks follow `- [ ] T### [P?] [Story?] Description with file path`.
