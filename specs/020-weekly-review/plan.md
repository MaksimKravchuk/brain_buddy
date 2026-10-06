# Implementation Plan: Weekly Review

**Branch**: `020-weekly-review` (work branch `claude/weekly-review-concept`) | **Date**: 2026-10-05 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/020-weekly-review/spec.md`

**Design authority**: [design.md](design.md), iOS screens M-01 – M-26 and web screens
D-01 – D-06 (32 screens), with their state tables. Signed off by Max on 2026-10-05
for M-01 – M-25 and D-01 – D-04 with sign-off decisions 1–6; amended on 2026-10-06 by
the owner's decision PD-3 (new M-26 and D-05), the campaign-1 fixes (states, copy,
focus) and the campaign-2 fixes (new D-06 and the states listed in design
"Amendments 2026-10-06 (campaign 2)"). Sign-off decisions 1–6 are unchanged.

**Risk**: **High / ASK** for the feature as a whole. It introduces the first automatic
GTD state change (auto-park), new per-owner persistence holding user content, a new
cloud-AI egress path with consent and provider credentials, and it must change ASK paths
`backend/app/api/tasks.py`, `backend/app/api/dependencies.py`, `scripts/`, `Makefile` and
`.env.example`. Per-slice landing classes are in [Delivery slices](#delivery-slices);
several slices are SHOW. The `weekly_review` flag (default OFF) does not lower any
slice's path-risk class (ADR-0008).

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.
Amend the spec first when implementation intent changes.

## Summary

Add a **formulation clock** to native tasks (when the current wording of a Next task
started, its one-time extension, a park floor and a stalled-formulation count), derive
"asks for a decision" / "moves to Someday tomorrow" markers from it with one shared rule,
let the person resolve a stalled task with a **decision card** from the task on any day,
and **auto-park** undecided formulations to Someday 7 days after the threshold — on the
server for synced accounts and on the device for account-less iOS — with a "while you
were away" return path. Then add an **AI navigator** (Apple on-device model first,
consented cloud fallback), and finally the **guided weekly review** (quick/full, resume,
restart mode, onboarding, schedule, one iOS notification, widget count) on iOS and web.
macOS gets a "coming later" row now and the full feature after Mac↔backend sync.

Technical approach (research R1, R7, R9): the review lives **inside the Tasks module**
(`backend/app/modules/tasks/`), its records live in `tasks.sqlite3`, and every decision is
one owner-serialized, idempotent composite task command that changes the task and records
the decision atomically, so Undo restores the exact prior task including its clock. On
iOS the clock is maintained by `GTDReducer`; new `GTDCommand` cases map one-to-one onto the
new endpoints, so offline outbox/replay sync works unchanged. A new ADR (draft:
[adr-draft.md](adr-draft.md), number 0027) supersedes ADR-0006's deferral and amends
ADR-0001's capture-based review model.

## Technical Context

**Language/Version**: Backend Python 3.11, FastAPI, Pydantic v2; web strict TypeScript,
React 19, Vite, react-router-dom 7; iOS Swift 6.2 package (`ios/BrainBuddyKit`,
`swift-tools-version: 6.2`) + SwiftUI app on iOS 26 (`ios/project.yml`, Swift 6 strict
concurrency); macOS POC Swift (`macos/Package.swift`, macOS 26).

**Primary Dependencies**: existing only for increments 1 and 3. Increment 2 uses Apple
`FoundationModels` (system framework, app target only, `#if canImport`) and the existing
OpenAI HTTP adapter style (`httpx`), and `NaturalLanguage` (`NLLanguageRecognizer`,
first-party) for task-language routing. A downloadable on-device model runtime
(recommended Core AI `coreai-models` package, iOS 27+) would be the first third-party iOS
dependency; it is isolated in slice PR-09 and approved by the owner as a late slice (NC-2) and gated by its own ADR
(research.md R13; `research-on-device-model.md`).

**Storage**: backend `<data_dir>/tasks.sqlite3` (Tasks module): new optional task payload
fields plus new tables `review_settings`, `review_sessions`, `review_decisions`,
`review_receipts`, `review_park_acks`, `review_bulk_releases`, `navigator_consents`,
`navigator_usage` ([data-model.md](data-model.md)). Feature flag in the existing ADR-0019
SQLite flag store. iOS: App Group `store.json` (`StoreDocument` v1 → v2). Device-local
model file in app Application Support. Web: only form drafts in `localStorage` (FR-052).

**Testing**: pytest + FastAPI TestClient (`api_client`, `second_api_client`); Vitest +
Testing Library; Playwright (`frontend/tests/allure.fixtures.ts`); Swift Testing in the
package on Linux (`sh ios/scripts/swift-linux.sh test`) and Xcode (`ios-app` lane). Every
product test names a feature-qualified id (`020-FR-001`, `test_020_FR_001_…`) and emits
the Allure taxonomy for pytest, Vitest and Playwright. Swift tests emit none:
`ios/README.md:340-341` ("Known gaps") states that iOS results are Swift Testing and
`xcodebuild` output that gate Full CI but are not in the Allure report, and
`docs/test-allure-taxonomy.md` covers only the three web/backend runners.

**Target Platform**: Linux server (Fly.io); iPhone iOS 26 (iPhone 390 × 851 design
frame), widgets; desktop web; macOS 26 POC (row only until Mac sync).

**Project Type**: modular-monolith web service + native iOS app + web SPA.

**Performance Goals**: markers computed in O(1) per task from stored fields; list
endpoints add one settings read per request; iOS marker computation inside the existing
`GTDQueries.list` pass without extra store reads; the maintenance sweep runs one query
over Next tasks (outside the lock) plus short owner-locked transactions per affected
owner every 60 s, and — because the clock lives in the JSON payload — parses and
classifies every Next task of every exposed owner each run, O(Next tasks) per minute
(acceptable at this scale; an optional per-owner watermark is the stated mitigation,
contracts/http.md §9). Navigator: cloud
p95 ≤ 8 s (timeout), on-device first token visible ≤ 2 s on an Apple-Intelligence device
(placeholder lines shown after 300 ms per design).

**Constraints**: iOS offline-first and account-less (FR-040, FR-014); no task content in
logs/metrics (FR-044); consent re-checked per cloud request (FR-024); auto-park is the
only automatic state change (FR-018); idempotent owner-serialized commands (FR-011);
ADR-0006 four open lists unchanged; no Swift third-party dependency without an
explicit exception (`ios/AGENTS.md`).

**Scale/Scope**: invite-gated multi-tenant beta; tens of owners, hundreds of open tasks
each; ~40 new endpoints-or-fields across 3 clients; 32 designed screens (M-01 – M-26,
D-01 – D-06).

## Constitution Check (pre-design)

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Spec workflow** — PASS. `intake.md`, `spec.md` (Clarifications session 2026-10-05,
  no NEEDS CLARIFICATION markers), `checklists/requirements.md` and the signed-off
  `design.md` exist. Four owner questions found during planning are recorded in
  research.md (NC-1 – NC-4), resolved by the owner on 2026-10-05; NC-1 changed the
  clock contract's extension arithmetic. The owner's answers to planning-review
  campaign 1's three product decisions (PD-1 – PD-3, 2026-10-06) are in spec.md
  Clarifications "Session 2026-10-06" and research.md "Owner decisions of 2026-10-06".
- **Consent & Safety** — PASS with design. On-device navigator needs no consent and sends
  nothing (FR-022). Cloud requires a persisted per-owner per-provider consent that the
  server re-checks on every request; revocation stops the next request; no silent
  fallback from on-device to cloud (contracts/navigator.md §4). Navigator input is a
  strict schema of exactly the FR-019 fields. No titles, notes, reason text or AI I/O in
  logs/metrics/fixtures; navigator evaluation set is synthetic. New durable records are
  exported and purged (data-model "Export and purge"). New provider key is read from an
  env var named by `BRAIN_BUDDY_REVIEW_NAVIGATOR_API_KEY_ENV`. Unlike title completion
  (which degrades to a disabled provider without its key, research R13), the
  navigator's container build **raises** at startup when the provider is `openai` and
  that variable is unset, so the deploy fails visibly (constitution I); the first
  failing test of PR-07 asserts it. Auto-park never runs before the owner has seen the
  explainer (FR-051).
- **Tests** — PASS with the strategy in [Test strategy](#test-strategy). Failing tests
  first per slice: formulation vectors, transition tables, decision/undo/stale/idempotency,
  sweep and yield rule, export/purge, flag-off 404, consent denial/revocation,
  timeout/cost cap/malformed, offline replay and compaction, UI states per design id.
- **Contracts** — PASS. [contracts/http.md](contracts/http.md),
  [contracts/formulation-clock.md](contracts/formulation-clock.md),
  [contracts/ios-commands.md](contracts/ios-commands.md),
  [contracts/navigator.md](contracts/navigator.md). All changes are additive (new
  paths, nullable fields); backend lands before clients; `StoreDocument` v2 has a
  migration step.
- **Observability** — PASS. Existing `CorrelationIdMiddleware` and `ErrorResponse`
  envelope; every new failure path returns `detail.reason` + `reference_id`; clients show
  "Ref" on every server failure (design M-03 error, M-07, D-02, D-03, D-04). New logger
  `app.modules.tasks.review` with ids/codes/counts/timings only; sweep summary line.
- **Mobile/resilience/performance** — PASS. iOS: all of US1, US2, US4, US5 work offline
  through the outbox; decisions made offline before a server park win (yield rule);
  duplicate parks are no-ops; review progress persists per decision; interrupted forms
  apply nothing to the task but keep typed text as a local draft and warn before
  discarding it (FR-052, constitution Principle V; design M-03/M-04 rows). Web is
  online-only with the existing "You're offline" pattern, plus browser-local drafts
  and a leave warning. No canvas impact.
- **Delivery boundary** — PASS. Spec Kit artifacts are planning input only; each slice
  runs in its own worktree with TDD, independent verification, exact-SHA CI and the
  ADR-0008 class stated per slice; ASK slices need recorded approval.
- **Design citation** — PASS. Each user story section below names the M-/D- ids and
  states it realizes; FR-013, FR-014, FR-016, FR-018, FR-026, FR-043, FR-044 have no UI
  surface (design "Requirements with no affordance") and are covered by backend/core tests.

## Current repository trace

Facts this plan builds on (verified 2026-10-05).

### Backend

| file | current responsibility | planned use |
|---|---|---|
| `backend/app/modules/tasks/domain.py` | `TaskDocument` (state inbox/next/waiting/someday/completed/cancelled, title, details, project_id, tag_ids, due_date, priority, waiting_for/since, order_key, timestamps, revision); no clock or title history | add E1 fields |
| `backend/app/modules/tasks/service.py` | `TaskService` commands under `_serialized_write` (l.64): owner `command_lock`, idempotency purge + reconcile; `update_task` (l.615), `transition_task` (l.680), `archive_project` (l.959, clears `project_id` on member tasks), `_apply_idempotent_record` (l.1142), `_assert_current` (l.1317, 409 `ConflictError`) | maintain the clock in create/update/transition/smart-add; new prefixes in `_apply_idempotent_record` |
| `backend/app/modules/tasks/repository.py` | `tasks.sqlite3`, JSON payload + indexed columns, `migration_ledger`, process-wide `command_lock`, `delete_all_for_owner` (l.644), `normalize_task_name` (l.43) | review tables via a mixin; purge review tables first |
| `backend/app/api/tasks.py` (**ASK**) | task routes; router-private `_to_response` (l.1183) builds `TaskResponse` with no settings input; title-completion routes and log line | `_to_response` moves to the public `api/task_mapping.py` (shared with `api/review.py`); the router passes `TaskService.formulation_views(…)` and accepts `new_formulation_id` (contracts/http.md §2) |
| `backend/app/api/dependencies.py` (**ASK**) | `get_task_service` (l.111), `require_voice_brain_dump_enabled` (l.361) | `get_review_service`, `require_weekly_review_enabled` |
| `backend/app/api/__init__.py` | mounts `task_router` into `api_router` | mount review routers |
| `backend/app/main.py` | `_run_privacy_maintenance_sweep` (l.26, returns a 3-tuple asserted by `tests/test_crt_receipt_retention.py:364`), `_run_maintenance_sweep` (l.85), `_start_privacy_maintenance_thread` (l.156); threads off in TEST unless `BRAIN_BUDDY_ENABLE_VOICE_SWEEP_IN_TEST=1` | `_run_review_maintenance_sweep` as its own try/except block inside the privacy sweep, return shape unchanged |
| `backend/app/container.py` | builds providers; title completion, STT and reconciler all degrade to a disabled provider without a key (l.184-272, 384-392) | `ReviewService` with injected clock; `_build_review_navigator_provider` (adapter in `app/ai/review_navigator.py`) that raises without a key |
| `backend/app/cli.py` | `python -m app.cli create-invite` and other operator commands | TEST-only `review-seed-aged-task`, `review-run-sweep` (research R21) |
| `backend/pyproject.toml` | import-linter: routes may not import `app.modules.tasks.repository`; tasks layers `service → repository` (l.131-148) | add `app.modules.tasks.review_repository` to the forbidden modules; extend the tasks layers to the review modules |
| `backend/app/services/account_service.py` | ZIP export (l.207, `tasks/*.json`, manifest `excluded`), `purge_account` (l.416) ordered and idempotent | `review/*.json` export; purge unchanged (covered by task repo) |
| `backend/app/ai/title_completion.py` | provider build (`disabled`/`deterministic`/`openai`), timeouts, candidate validation; per-request consent echo; the only OpenAI adapter, outside the modules tree (ADR-0001 rule 9, `0001-…md:85-86`) | pattern for the navigator adapter, which lives beside it in `app/ai/review_navigator.py` |
| `backend/app/services/feature_flag_service.py` | `is_effective(name, user: User)` (l.145) | the sweep resolves each owner's `User` before asking |
| `backend/app/core/config.py` | `KNOWN_FEATURE_FLAGS` (l.86), provider settings | `weekly_review`; navigator settings |
| `backend/app/repositories/feature_flag.py` | `MANAGED_FLAGS` (l.83), `_POST_ADR_0019_DEFAULT_OFF_FLAGS` (l.100), upgrade whitelist (l.426) | register `weekly_review` OFF |
| `backend/app/core/rate_limit.py` | `title_completion_rate_limiter` (l.257) | `navigator_rate_limiter` |
| `backend/tests/test_voice_workflow_architecture.py` | l.250 forward guard: any `app/**` path containing `weekly_review` must import `app.workflows.voice_brain_dump` | kept; docstring clarified; non-voice code avoids the token (R1) |

### iOS and macOS

| file | current responsibility | planned use |
|---|---|---|
| `ios/BrainBuddyKit/Sources/BrainBuddyCore/Records.swift` | `TaskRecord`, `ProjectRecord` | clock, park marker, `GTDState.review` |
| `ios/BrainBuddyKit/Sources/BrainBuddyCore/Commands.swift` | `GTDCommand` (one request per case), `GTDValidationError` | new cases (contracts/ios-commands.md §2) |
| `ios/BrainBuddyKit/Sources/BrainBuddyCore/Reducer.swift` (+`Reducer+*.swift`) | the only GTD rules; `apply(_:at:to:mode:)` | clock maintenance, decisions, auto-park |
| `ios/BrainBuddyKit/Sources/BrainBuddyCore/Queries.swift` | `GTDQueries`, `ProjectSummary.needsNextAction` (l.183) | new `Queries+Review.swift` |
| `ios/BrainBuddyKit/Sources/BrainBuddyCore/NameNormalizer.swift` | Python-parity NFKC/collapse/casefold | reused by `FormulationKey` |
| `ios/BrainBuddyKit/Sources/BrainBuddyCore/Outbox.swift`, `BrainBuddyPersistence/StoreDocumentCoding.swift` | `StoreDocument` v1, migration hook (l.117, no steps yet) | v2 + step |
| `ios/BrainBuddyKit/Sources/BrainBuddySync/*` | push planner, 409 refetch/replay, full pull (no delta) | new request mapping; review state pull |
| `ios/BrainBuddyKit/Sources/BrainBuddyAPI/BrainBuddyAPIClient.swift`, `WireModels.swift`, `RequestBodies.swift` | REST client, DTOs, `APIError` with `referenceID` | new endpoints and DTO fields |
| `ios/BrainBuddyKit/Sources/BrainBuddyWorkspace/Workspace.swift` | `@Observable` app state; private `perform(_:)` (l.483) | public decision/review/auto-park methods |
| `ios/BrainBuddy/Screens/Browse/ListsHubScreen.swift` | `DeferredRow` "Weekly review · coming later" (l.47-53, 171-185) | working entry when exposed (M-11) |
| `ios/BrainBuddy/Components/TaskRow.swift`, `Chips.swift`, `Toasts.swift` | row metadata flow layout, chips, toasts with ~5 s action | marker chips, Undo toasts |
| `ios/BrainBuddy/Screens/Process/ProcessInboxScreen.swift` | Process inbox with inverse-command Undo | reused by the Inbox step (M-15) |
| `ios/BrainBuddy/App/AppRouter.swift` | `AppRoute`, `handle(_ url:)` (l.141) | `review` host and routes |
| `ios/BrainBuddyWidgets/NextActionsWidget.swift` | small/medium/large, `widgetURL`, `CompleteTaskIntent` | "N ask" chip (M-24) |
| `macos/Sources/BrainBuddyMac/ContentView.swift` | sidebar (l.1958-2066); local Waiting/Someday review POC | "Weekly review · coming later" row |

### Web

| file | current responsibility | planned use |
|---|---|---|
| `frontend/src/components/shell/AppShell.tsx` | disabled "Weekly review — Coming soon" (l.520-531); flag-gated Thinking Mode pattern (l.532-551) | flag-gated working link + "Last review" line (D-01) |
| `frontend/src/app/AppRoutes.tsx` | all routes; `CrtGate` pattern | `/review` behind `ReviewGate` |
| `frontend/src/features/tasks/TaskListPage.tsx` | `TaskRow` (l.1196), `Chip` (l.1100), conflict copy "Task changed elsewhere" | markers, Decide action |
| `frontend/src/features/tasks/TaskDetailPanel.tsx` | inline detail, `AutosaveRecovery` | "This wording" block |
| `frontend/src/components/shell/shellToast.ts` | text-only toast, 2.6 s | optional action (Undo ~5 s) |
| `frontend/src/features/account/AccountSettingsPage.tsx`, `frontend/src/components/ui/SettingsSection.tsx` | settings sections | D-04 section |
| `frontend/src/api/client.ts`, `frontend/src/utils/error.ts` | `ApiError.correlationId`, `getErrorContext` | reused; new `frontend/src/api/review.ts` |

### Governance

| file | fact | planned use |
|---|---|---|
| `docs/decisions/0006-native-gtd-lifecycle-and-capability-baseline.md` | l.29-31 "Weekly Review remains explicitly deferred"; B-09 (l.81); l.322 | superseded in part by ADR-0027 |
| `docs/decisions/0001-vnext-modular-monolith-and-workflow-contracts.md` | Review module row (l.61), capture-based `WeeklyReview` (l.266-293), endpoints (l.468-470) | amended for native tasks |
| `docs/vnext-cloud-design-build-contract.md` | D-11 (l.757) cadence/timezone open item | closed by ADR-0027 |
| `.claude/skills/brain-buddy-design/README.md` (l.42), `SKILL.md` (l.7), `preview/components-gtd-nav.html` (l.35) | "Weekly Review remains visibly deferred" | reworded in PR-01 |
| `scripts/test_validate_brain_buddy_design_skill.py` (**ASK**) | asserts that string (l.29, l.32) and "coming later" (l.33) | updated with the skill in PR-01 |
| `scripts/check_requirement_coverage.py` (**ASK**, guarded) | scans only backend/frontend trees, no `.swift` (l.53-64) | add Swift test trees (R19) |
| `Makefile` (**ASK**, guarded) | `check-specs` runs requirement coverage for 019 only | add 020 (PR-14) |

## Project Structure

### Documentation (this feature)

```text
specs/020-weekly-review/
├── intake.md, spec.md, design.md, design/*.html, checklists/requirements.md   (existing)
├── plan.md                         # this file
├── research.md                     # Phase 0
├── research-on-device-model.md     # separate on-device model research (exists, 2026-10-05)
├── review-c1-disposition.md        # planning-review campaign 1: every finding and its disposition
├── review-c2-disposition.md        # planning-review campaign 2 (last): every finding and its disposition
├── data-model.md                   # Phase 1
├── contracts/
│   ├── http.md                     # backend HTTP API
│   ├── formulation-clock.md        # shared normative rule + vector format
│   ├── ios-commands.md             # GTDCommand / outbox / StoreDocument v2
│   └── navigator.md                # prompt, output, NavigatorModel protocol
├── adr-draft.md                    # ADR-0027 draft (copied to docs/decisions/ in PR-01)
├── quickstart.md                   # validation scenarios
└── tasks.md                        # /speckit-tasks (not created here)
```

### Source Code (repository root)

New files are marked `(new)`; everything else exists today.

```text
backend/
├── app/
│   ├── api/
│   │   ├── __init__.py                       # mount review routers
│   │   ├── dependencies.py                   # ASK: get_review_service, require_weekly_review_enabled
│   │   ├── tasks.py                          # ASK: uses task_mapping; accepts new_formulation_id
│   │   ├── task_mapping.py                   (new) public task_response() mapper (was _to_response), shared by tasks and review routers
│   │   ├── review.py                         (new) decisions, undo, auto-park, state, settings, park acks, explainer ack
│   │   ├── review_navigator.py               (new; mounted empty in PR-02) navigator consent + suggestions
│   │   └── review_flow.py                    (new; mounted empty in PR-02) review runs, queues, bulk release
│   ├── ai/review_navigator.py                (new, PR-07) OpenAI adapter beside title_completion.py, behind the NavigatorProvider port
│   ├── cli.py                                # TEST-only review seed and sweep commands (R21); review-metrics read-out
│   ├── core/config.py                        # weekly_review flag; navigator settings
│   ├── core/rate_limit.py                    # navigator limiter
│   ├── repositories/feature_flag.py          # register weekly_review (default OFF)
│   ├── schemas/tasks.py                      # TaskResponse.formulation / parked
│   ├── schemas/review.py                     (new) request/response models
│   ├── modules/tasks/
│   │   ├── domain.py                         # E1 fields
│   │   ├── service.py                        # clock maintenance in existing commands
│   │   ├── repository.py                     # composes the review mixin; purge
│   │   ├── formulation.py                    (new) pure rule (contract)
│   │   ├── review_rules.py                   (new, PR-02) pure review-flow rules executed by review_flow_vectors.json
│   │   ├── review_domain.py                  (new) E2–E9 records
│   │   ├── review_repository.py              (new) SQL mixin for review tables
│   │   ├── review_service.py                 (new) decisions, undo, auto-park sweep, settings, state
│   │   ├── review_flow.py                    (new) runs, queues, capacity, bulk release (increment 3)
│   │   └── navigator.py                      (new) NavigatorProvider port, request schema, reduce_notes, output validation, consent rules (no HTTP client)
│   ├── services/account_service.py           # review/*.json export
│   ├── container.py                          # ReviewService, navigator provider
│   └── main.py                               # _run_review_maintenance_sweep
└── tests/
    ├── fixtures/review_formulation_vectors.json   (new, canonical)
    ├── fixtures/review_flow_vectors.json          (new, canonical review-flow vectors)
    ├── fixtures/review_wire/*.json                (new, golden wire fixtures validated against schemas/review.py)
    ├── fixtures/review_traces/*.json              (new, golden operation traces: request sequence + expected responses, verified by pytest against the real API and replayed against BrainBuddyFakeServer)
    ├── fixtures/navigator/eval_v1.json            (new in PR-07, synthetic SC-005 eval set)
    ├── allure_taxonomy.py                         # rules for the new modules
    ├── test_review_formulation.py                 (new)
    ├── test_review_formulation_vectors.py         (new, incl. copy-drift check)
    ├── test_review_decisions_api.py               (new)
    ├── test_review_auto_park.py                   (new)
    ├── test_review_export_purge.py                (new)
    ├── test_review_navigator.py                   (new)
    ├── test_review_flow_api.py                    (new)
    └── test_voice_workflow_architecture.py        # docstring clarification only

frontend/src/
├── api/review.ts, api/reviewHooks.ts, api/taskTypes.ts       (review*.ts new)
├── components/shell/AppShell.tsx, shellToast.ts
├── app/AppRoutes.tsx
├── features/tasks/TaskListPage.tsx, TaskDetailPanel.tsx
├── features/account/AccountSettingsPage.tsx
├── features/review/ (new)  formulation.ts, ReviewGate.tsx, DecisionDialog.tsx,
│                            WhileYouWereAway.tsx, AutoParkExplainer.tsx (D-05),
│                            reviewFormDrafts.ts (FR-052), ReviewShell.tsx, steps/*.tsx,
│                            ReviewSettingsSection.tsx, navigatorInput.ts (incl. the
│                            project-wide duplicate filter), activeTime.ts (SC-004),
│                            stallRecommendation.ts (FR-007), wywaPresentation.ts
│                            (FR-015 once a day), FormulationBlock.tsx (D-06), __tests__/
├── pages/PrivacyPolicyPage.tsx                # retention/export wording
└── test/allureTaxonomy.ts                     # /features/review/ rule
frontend/tests/e2e/weekly-review.spec.ts (new); frontend/tests/allure.fixtures.ts (path rule)

ios/BrainBuddyKit/Sources/
├── BrainBuddyCore/   Records.swift, Commands.swift, Reducer*.swift, Replay.swift,
│                     Compaction.swift, Outbox.swift, Queries.swift,
│                     Formulation.swift (new), Queries+Review.swift (new),
│                     Review.swift (new: ReviewState, decisions, runs), Navigator.swift (new),
│                     ReviewPlanners.swift (new: ReviewReminderPlanner, ReviewEntryPlanner,
│                     ActiveTimeAccumulator, StallReasonRecommendation, UndoWindowPolicy,
│                     WhileAwayPresentation), ReviewCopy.swift (new: review-surface copy catalog)
├── BrainBuddyPersistence/StoreDocumentCoding.swift
├── BrainBuddyAPI/    BrainBuddyAPIClient.swift, WireModels.swift, RequestBodies.swift,
│                     ReviewAPI.swift (new), NavigatorAPI.swift (new)
├── BrainBuddySync/   GTDCommand+Sync.swift, PushPlanner.swift, SyncEngine+Push.swift,
│                     SyncEngine+Pull.swift, StoreDocument+Merge.swift
├── BrainBuddyWorkspace/Workspace.swift
└── BrainBuddyFakeServer/  (review endpoints, StubNavigatorModel)
ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/  FormulationTests.swift, ReducerReviewTests.swift,
                     QueriesReviewTests.swift, NavigatorValidatorTests.swift,
                     ReviewPlannersTests.swift (new),
                     Resources/review_formulation_vectors.json, review_flow_vectors.json,
                     review_wire/*.json, review_traces/*.json (new copies, written by PR-02)
ios/BrainBuddyKit/Tests/BrainBuddySyncTests/  ReviewSyncTests.swift (new)
ios/BrainBuddyKit/Package.swift               # test resources for the vector, wire and trace copies (PR-03, the first slice that loads them)
ios/BrainBuddy/
├── Screens/Review/ (new)  DecisionCardSheet, DecisionForms, WhileYouWereAwaySheet,
│                          AutoParkExplainerSheet (M-26), RestartScreen, ReviewEntry,
│                          OnboardingScreen, steps…
├── Screens/Lists/TaskListScreen.swift, Screens/Detail/TaskDetailScreen.swift,
│   Screens/Browse/ListsHubScreen.swift, Screens/Settings/SettingsScreen.swift
├── Components/TaskRow.swift, Chips.swift
├── Navigator/ (new)  AppleNavigatorModel.swift, NavigatorPanel.swift
├── Review/ReviewReminderScheduler.swift (new)
└── App/AppRouter.swift, BrainBuddyApp.swift
ios/BrainBuddyWidgets/NextActionsWidget.swift
ios/project.yml                               # BBWeeklyReviewLocal Info.plist key
docs/native-ios-app.md                        # deferred → flag-gated

macos/Sources/BrainBuddyMac/ContentView.swift # non-interactive row (FR-041)

docs/decisions/0027-native-task-weekly-review-and-auto-park.md (new, PR-01)
docs/data-retention.md, .env.example, .claude/skills/brain-buddy-design/{README.md,SKILL.md}
scripts/test_validate_brain_buddy_design_skill.py, scripts/check_requirement_coverage.py,
.specify/gate-integrity.json, Makefile
```

**Structure Decision**: backend work stays in `app/modules/tasks/` (data ownership:
task records are SQLite and owned by Tasks; nothing touches CRT JSON trees) with thin
routers in `app/api/`; the iOS rules live in `BrainBuddyCore` (Linux-testable) with
Apple-only APIs (FoundationModels, UserNotifications, WidgetKit) confined to the app and
widget targets; the web gets one feature folder. Router and module file names avoid the
`weekly_review` token (architecture guard) and the classifier's ASK tokens (R1).

## Architecture by user story

### US1 — A stalled task asks for a decision (P1) — design M-01, M-02, M-03, M-04, M-23 (threshold row), D-01, D-02 (no navigator), D-04 (threshold), D-06

**Backend**
- `formulation.py` implements `formulation_key`, `derive_instants`, `classify`,
  `close_formulation`, `start_formulation` exactly per
  [contracts/formulation-clock.md](contracts/formulation-clock.md). `TaskService`
  calls them inside `create_task`, `smart_add_task`, `update_task`, `transition_task`
  (FR-001 – FR-003, FR-046). Notes, tags, project, priority, subtask and comment edits
  pass through untouched (FR-003).
- `ReviewService.decide` (`POST /tasks/{id}/decisions`, http §3) under
  `_serialized_write`: checks `expected_revision` and `formulation_id` (FR-011),
  applies the type table (FR-006, FR-008, FR-009), records the decision with stall
  reason code (FR-007), `ai_use` (FR-026), undo snapshot, and session counter when in a
  review (FR-010: same path in and out of a review).
- `ReviewService.undo_decision` (FR-048), allowed while the task revision (and a
  created follow-up's revision) is unchanged.
- `TaskResponse.formulation` carries raw fields plus derived `ageing_at` / `ask_at` /
  `park_due_at` / `paused_until` and `consecutive_stalled` (FR-004, FR-005); all
  derived instants are null before activation (FR-051). Computed by the pure
  `formulation.derive_instants`, with one settings read per request in
  `TaskService.formulation_views`, and mapped by the shared public
  `api/task_mapping.py` (contracts/http.md §2), so the ASK diff in `api/tasks.py` stays
  small and `api/review.py` imports no private router symbol.
- A cosmetic-only reformulation saved with "Save anyway" is a recorded `reformulate`
  decision with `substantive: false` (FR-002); the decision step moves on.
- Client-supplied ids (`decision_id`, `new_formulation_id`, `follow_up_task_id`) are
  adopted (contracts/http.md "Client-supplied ids").
- Settings `PUT /review/settings` threshold change sets the owner park floor (FR-039).

**iOS** (`BrainBuddyCore` rules; app UI)
- Reducer maintains the clock for every existing command (contracts/ios-commands.md §3)
  and applies `decideTask` / `undoDecision`.
- M-01: `TaskRow` metadata shows only `asks` and `moves_tomorrow` chips (indigo
  `questionmark.circle` / amber `archivebox`, text + icon, 44 pt hit area); tapping opens
  M-03 as a `.large` detent sheet (FR-047). States: default, loading (static rows after
  300 ms), empty first-run/filtered (existing copy), error (store unreadable, no Ref),
  offline ("Offline — 2 changes waiting"), threshold-changed note.
- M-02: "This wording" section in `TaskDetailScreen` with every M-02 state (asks,
  ageing/fresh, paused, moves-tomorrow with exact park time, kept 7 more days with the
  quoted reason, parked automatically, parked/project archived — see Inconsistencies).
- M-03/M-04: decision card + forms (reformulate with the cosmetic-edit note from
  `FormulationKey`, first step with "Was:" preview, Waiting for, keep 7 more days with
  required reason and computed date), stall-reason → recommendation mapping (Core
  `StallReasonRecommendation`, checked against the shared `stall_recommendation`
  vectors, FR-007), third-stall
  offer (iOS has no canvas, so the offer shows "Release to Someday" only; design M-03
  amended), stale (was/now), error with Ref, decision-not-allowed and
  undo-didn't-apply copy, Undo toast ~5 s via `ToastCenter` (≥ 10 s and announced under
  VoiceOver / Switch Control).
- FR-052: forms track dirty fields; `interactiveDismissDisabled` while dirty; the
  "unsaved text — leave?" confirmation; drafts in `local.formDrafts` keyed by task and
  formulation, restored on reopen, deleted on save/discard/formulation change/7 days.
- M-23: threshold picker (7/14/21/28) with the floor note (FR-039).

**Web**
- D-01: `TaskRow` gets a marker `Chip` button (accessible name "Asks for a decision.
  Open decision for <title>"; offline it stays focusable with `aria-disabled` and the
  reason). D-06: the inline detail gets the "This wording" block (`FormulationBlock`,
  ageing only there, "Decide" opens D-02 and receives focus back). Classification uses
  server instants and the browser clock, re-evaluated every minute without refetch.
  The stall-reason recommendation is one constant (`stallRecommendation.ts`) checked
  against the same `stall_recommendation` vectors as iOS.
- D-02: `DecisionDialog` (560 px, full-height sheet at 390 px, focus on title, focus
  trap, Esc closes with no change unless a form is dirty, keys 1–7 shown as numerals and
  inactive in text fields, per-row "Saving…", stale heading "Task changed elsewhere",
  save-failed banner with Ref, offline disabled state, third-stall "Think it through"
  only when `crt_canvas` is effective), Undo toast via the extended `shellToast`
  (role="status", timer pauses on focus/hover, Ctrl/Cmd+Z while visible, focus to next
  row). FR-052 drafts via `reviewFormDrafts.ts` (`localStorage`, data-model E11), a
  `beforeunload` warning for tab close and reload, and a history guard for browser
  Back and in-app navigation, which `beforeunload` does not cover: the dialog pushes a
  history entry when it opens, a `popstate` handler treats Back as Close (asking first
  when a field is dirty, and re-pushing the entry on "Keep editing"), and in-app links
  go through the same check. react-router's `useBlocker` is not available because the
  app uses the declarative `BrowserRouter` (`frontend/src/App.tsx:24`) (design D-02
  "browser Back / route change").
- D-04: threshold control in a new `ReviewSettingsSection` on `/settings/account`.

### US2 — Auto-park and a shame-free return (P1) — design M-26, D-05 (explainer, increment 1), M-01/M-02 (moves tomorrow, parked), M-09, D-01 (WYWA dialog), D-03 (M-09 content); restart mode M-10 ships with US4

**Backend**
- `POST /review/explainer/acknowledge` (FR-051, http §5): first acknowledgement on any
  device sets `activated_at` and runs the activation clamp and floors (FR-016, R4) in
  one owner-locked transaction, without bumping task revisions. Nothing else activates
  an owner.
- `ReviewService.run_auto_park_sweep(now)` from `_run_review_maintenance_sweep`
  (http §9): retention part for every owner with review rows; exposure part per
  **activated** owner with the flag effective (owner resolved to a `User` for
  `is_effective`): sweep-gap floor, clock repair, then park tasks whose class is
  `park_due` with key `auto-park:<task>:<formulation>:<from_revision>`, storing
  `parked.clock_before` and writing the E6 park row in the same transaction; re-check
  under lock (FR-012, FR-013, FR-014); keep project, tags, notes, due date, priority.
  Short transactions; no I/O under the process-wide lock; owner failures logged with
  the exception type only.
- `POST /tasks/{id}/auto-park` for device-observed parks; `applied: false` is success
  (US2-6), and is also the answer while the flag is off.
- Yield rule for earlier offline card decisions only (R9), restoring `clock_before`;
  formulation-based (`from_revision ≤ expected_revision ≤ revision`), so plain edits
  queued before the decision do not defeat it.
- `GET /review/state.unseen_parks` + `POST /review/parks/acknowledge` (FR-015).
  Returning uses the existing `transition move → next`, which starts a new formulation
  (US2-4), clears `parked` and records `returned_at` on the park ack (metrics).

**iOS**
- M-26 explainer sheet at the first app open after exposure, before anything else
  (`GTDQueries.explainerNeeded`); "Got it"/Close queues `acknowledgeExplainer`;
  account-less records `local.activatedAt`; the reducer's post-replay activation step
  (contracts/ios-commands.md §3). Ships in PR-04 with the markers and M-09.
- `Workspace.applyDueAutoParks()` on load/foreground/pull/background refresh;
  nothing before activation; at most 10 parks per call (safety valve); account-less
  parks are final; signed in, due parks are evaluated with the last observed server
  clock offset, applied locally only after `applied: true` when online, optimistic only
  when offline, and never re-issued per formulation (contracts/ios-commands.md §5).
- `acknowledgeExplainer` carries the device time zone (http §5), so due-dated tasks
  classify in the person's zone from activation on. `runLocalReviewMaintenance()` keeps the local 7-day
  bounds.
- Clock-aware compaction for account-less correctness (ios-commands §3).
- M-09 sheet at app open when unseen parks exist: per-row "Return to Next", "Return all
  N", "Continue" (acknowledges); swipe-down does not acknowledge and the sheet shows
  again at most once a day (Core `WhileAwayPresentation` with
  `local.wywaLastShownDay`, FR-015). Partial failures: archived project (row disabled
  with reason) and changed elsewhere (named). Offline: works locally, shows again until
  Continue. VoiceOver focus moves to the sheet heading when it appears and to the tab's
  navigation title when it closes (design "Keyboard and focus").

**Web**
- D-05 explainer dialog at the first web open when `explainer_seen` is false.
- M-09 content as a modal dialog at app open (design D-01 "While you were away
  (dialog at app open)" states: focus trap, Esc does not acknowledge, per-row
  "Returning…", failure with Ref, "continue not saved", offline; once a day via
  `wywaPresentation.ts` and the E11 last-shown key) and as the first screen of
  `/review` (D-03, the same rows).

### US3 — The AI navigator proposes a first step (P2) — design M-04 ("Suggest"), M-05, M-06, M-07, M-08, M-19 (AI states), M-23 (Suggestions section), D-02 (navigator states), D-03 (M-19 on the web), D-04 (cloud consent)

- Contract: [contracts/navigator.md](contracts/navigator.md) (input exactly FR-019,
  validator for FR-019/FR-021, `NavigatorModel` protocol, prompt v1).
- **Backend**: adapter `app/ai/review_navigator.py` (`disabled`/`deterministic`/`openai`)
  beside the title-completion adapter, behind the `NavigatorProvider` port declared in
  `modules/tasks/navigator.py` (schema, `reduce_notes`, validation, consent rules; no
  HTTP client in the Tasks module, ADR-0001 rule 9), with
  `_build_review_navigator_provider` raising at container build when `openai` lacks its
  key (or `deterministic` outside TEST, or an unknown provider; research R13), consent
  table and endpoints with `consent_text_version` currency (`GET /review/navigator` and
  the revoke never gated by the flag), per-owner rate limit, per-call and daily cost
  caps admitted as reserve → call with no lock held → settle (contracts/http.md §7),
  the shared `reduce_notes` backstop, error reasons mapped to 400/429/503 with Ref
  (FR-024, FR-025, FR-045). No language field in the request. No Idempotency-Key, no
  idempotency record, no text persisted; one log line of codes/counts.
- **iOS**: `NavigatorRouter` chooses Apple on-device when `available` for the task's
  language (FR-022), else M-06 choice (FR-023) with the remembered preference (M-23);
  cloud path requires consent (M-07) and an account ("Cloud suggestions need a Brain
  Buddy account" state); proposals fill the field, the task changes only on Save
  (FR-020); proposals that duplicate **any** open task of the project in the local
  store are dropped before display (`NavigatorProposalFilter`, contracts/navigator.md
  §2 rule 5, FR-019); a clarifying question — on-device (M-05) or cloud (M-07) —
  appends the answer to notes via a normal `updateTask` (no clock change) and re-runs
  (FR-021); "Stop" cancels the `Task`; backgrounding or dismissal cancels quietly and
  keeps arrived proposals (design M-05/M-07 "interrupted"). The Suggest control shows
  its resolved route before the tap ("· on this iPhone" / "· OpenAI").
  M-08: project without a next action uses `kind: project_next_action`; confirm creates
  the task in Next in that project (`createTask`); a model question on a project is
  answered in the next-action field itself (M-08 "model question", FR-021). The web
  offers this only in the full review's projects step (design note under M-08; spec
  Out of Scope), so the web part of US3-8 is verified with PR-13, not PR-10.
  Focus: when M-06 or M-07 closes, VoiceOver focus returns to Suggest or the first
  proposal (design "Keyboard and focus").
- **Language routing**: Russian is not listed as supported by Apple's model on iOS
  26.x or 27 (unverified; treated as unsupported, so the FR-023 choice is the designed
  path; `research-on-device-model.md` §1). The router classifies the task text with
  `NLLanguageRecognizer` first and goes straight to the M-06 choice for unsupported
  languages; `unsupportedLanguageOrLocale` thrown at `respond` is the backstop. The
  detected language stays on the device. Input: one shared `reduce_notes` with a fixed
  6 000-character notes budget for every model, so on-device and cloud receive exactly
  the same reduced input, with a visible note when anything was dropped (owner decision
  NC-3; contracts/navigator.md §1); token counts are only a guard.
- **Downloadable model** (FR-023 (a), FR-049): slice PR-09, behind the same protocol;
  recommended Core AI + Qwen3-1.7B 4-bit in an Apple-hosted Background Assets pack,
  iOS/macOS 27+ with a memory check and the `increased-memory-limit` entitlement
  (`ios/project.yml`), free-space check declared in `ios/Shared/PrivacyInfo.xcprivacy`;
  needs a dependency-exception ADR; the owner approved it as a late slice (NC-2). M-06 download states
  (progress, interrupted, storage, installed, resumed after reopen, finished while away,
  cancelled), the M-23 "model downloading" and "download interrupted" rows and M-23
  delete-with-confirmation are built in PR-09, all driven by `ModelDownloadMachine`
  (its state survives an app kill in `LocalReviewState`). Apple Private Cloud Compute is not built (owner decision NC-4: it would count as a
  cloud provider).
- **Web**: D-02 navigator states (consent dialog focusing "Not now", proposals radio
  group, timeout/cost cap/malformed banners with Ref, the cloud clarifying question with
  its two-stage "adding answer" / "answer not saved" / "answer saved, suggestion
  failed" rows, the card adopting its own notes edit's revision); proposals filtered
  against all of the project's open tasks (`GET /tasks?project_id=…`, all pages); D-04
  cloud consent switch naming the provider, still shown when the flag is off and a
  consent exists; revoke takes effect at once in the tab.

### US4 — The guided weekly review (P2) — design M-10, M-11, M-13 – M-22, D-03

- **Backend** `review_flow.py` (on the pure `review_rules.py` of PR-02) +
  `api/review_flow.py`: start/resume/progress/finish
  runs with client-supplied session ids, `replace_open`, merged (never-409) progress,
  idempotent finish meaning Done only (no "left" outcome: leaving pauses; partial or
  abandoned only by replacement or the 7-day idle close; FR-027, FR-029, data-model E3
  transitions including `completed_empty`), active seconds per step (SC-004), the exact
  `SessionResponse` of contracts/http.md §6, restart mode anchored on
  `coalesce(last_counted_review_at, onboarded_at)` (FR-017), `last_counted_review`
  summary in `GET /review/state` (SC-007 on the web), queues per step with a
  server-side snapshot of the `asks_for_decision` aggregate in formulation-clock §5 order
  (edge case "threshold changed during an open review"), wins (FR-028), capacity mirror
  with the < 4-weeks rule (FR-031), Waiting > 7 days and Someday ≤ 7 by the FR-032
  eligibility and order, projects without a next action, dates in 14 days, the ten
  summary counts and "clear start" (FR-033), bulk release with client ids,
  server-computed eligibility per kind (restart: in Next and `restart_eligible`;
  Inbox remainder: in Inbox and not processed in the session), partial results and
  clock-exact undo for restart (FR-017) and Inbox remainder (FR-030), a `release`
  Someday receipt for every person release (decision `someday` and both bulk kinds) so
  the Someday step leaves them out for 30 days (FR-032), regularity instant from counted
  reviews only. Foreign and unknown task ids in bodies
  are indistinguishable. Restart candidates interact with auto-park: because parks move
  undecided formulations by T + 7 ≤ 35 days, the 4-week offer mostly finds tasks held in
  Next by an extension, a floor or an ended due-date pause (formulation-clock §5); its
  tests seed exactly those.
- **iOS**: review cover with shared step chrome (Leave/Skip at top, primary action at
  bottom, "N of M"), each step's states as designed, including "review ended / moved on
  elsewhere" and "leave with unsaved text"; decision step reuses M-03 full-screen with
  "Not now" (FR-050) and Undo status line; Inbox step reuses `ProcessInboxScreen` item
  view (its Undo also sends `inbox_processed_delta: -1`); one item at a time in the
  Inbox, decision, Waiting and Someday steps (FR-034). M-10 and M-15 reopen on the
  released state with Undo after an interruption (FR-017, FR-030). M-16 shows "all
  decided, one kept its wording" after a "Save anyway". M-11 / M-13 show "closed after
  a week" for an idle-closed review. VoiceOver focus moves to the heading of M-10, M-11
  and M-12 when they appear. Offline: everything local via outbox; cross-device resume
  after sync (M-11 offline).
- **Web**: `/review` route (`ReviewShell`, 240 px non-focusable rail, 600 px column,
  collapsed to "Step N of M" at 390 px, focus to step heading on change, Esc never
  closes the review), same steps, plus the web-only states of design D-03: the new
  Inbox step (one item at a time, Undo, saving/failed, release and undo pending/failed),
  "step loading" / "step load failed" for each step's `GET /review/queues/{step}`,
  per-step "step action saving / failed" and "skip not saved", restart releasing /
  release failed / undo failed, the D-01 While-you-were-away rows inside the review,
  the entry's last-review summary (SC-007), "closed after a week", the inline-card Esc
  order, and browser Back / route change acting as "Leave" through the same history
  guard as D-02 (unsaved-text confirmation first); 390 px reflow of the Waiting buttons
  and the summary grid; offline per D-03.

### US5 — Schedule, cue, onboarding and settings (P3) — design M-11 (Lists row), M-12, M-23, M-24, M-25, D-01 (sidebar recap), D-03 (onboarding dialog), D-04

- **Backend**: settings fields and `next_review_at`/`last_counted_review_at` in
  `GET /review/state` (FR-035, FR-038); time zone follows the client (US5-5), first
  sent with the explainer acknowledgement.
- **iOS**: onboarding once (M-12) then notification permission prompt; one weekly local
  notification, skipped per FR-036 (R17), with the decision in Core
  (`ReviewReminderPlanner`); widget "N ask" chip (the `asks_for_decision` aggregate)
  with deep link in medium/large following the entry order (`ReviewEntryPlanner`),
  display-only in small, none for a Today widget (FR-037); neutral "Last review: N days
  ago" from counted reviews, no streak anywhere (FR-038), with every review-surface
  string — notification and widget included — read from the Core `ReviewCopy` catalog
  that a Linux test checks against the banned terms (US5-6); Lists row replaces
  `DeferredRow` when exposed (FR-042).
- **Web**: sidebar link replaces the disabled entry when the flag is on, with the
  "Last review" line (and its loading / failed / never-reviewed states, design D-01),
  also in the 390 px mobile drawer (FR-036 web has no notification, FR-042); onboarding dialog (focus on its heading, Esc saves nothing). E2E-MOBILE-02
  (`frontend/tests/e2e/mobile.spec.ts`) keeps asserting the disabled entry with the flag
  off; a flag-on variant in `weekly-review.spec.ts` expects the working link and no
  overflow at 390 px.

### US6 — The same review on Mac (P3) — no mockups (design "Applicability")

- **Now (FR-041 pre-sync)**: a non-interactive "Weekly review · coming later" row in
  the Mac sidebar after "Lists" in `ContentView.sidebar(account:)`, same pattern as iOS
  `DeferredRow`. No local-only review.
- **After Mac↔backend sync (separate spec)**: the Mac reuses `BrainBuddyKit`'s rules
  and contracts; its slices are planned when that dependency exists. The fate of the
  POC "Review Waiting for"/"Review Someday" sheets is decided then.

## Failure handling and concurrency

| situation | behaviour | where |
|---|---|---|
| Decision on a task changed elsewhere | 409, nothing applied; client shows was/now (M-03 stale, D-02 stale) | http §3 |
| Decision made offline before a server park | server restores `parked.clock_before` and applies the decision (yield rule; card decisions only, `extend` allowed; formulation-based, so plain edits queued before it and replayed onto the parked task do not defeat it) | R9, http §3 |
| Decision rejected after sync because the formulation changed | set aside with copy naming the task's current list (never "still in Next"); the "parked before the decision synced" variant lists the task on While you were away | ios-commands §4, design M-03 |
| Same formulation due again after a yield (cosmetic "Save anyway", or decision + Undo) | parked again by the next sweep: the auto-park key includes `from_revision`, so it is a new command, not a replay | http §4 |
| Flag turned OFF (rollback) with queued device commands | writes that finish started work are accepted, `autoParkTask` gets `applied: false`, nothing is set aside or reverted; gated reads answer 404 `weekly_review_disabled`, which iOS treats as "back off, keep" | http "Gate", ios-commands §4 |
| Plain edit or move made offline before a server park | ordinary 409 → iOS refetch/replay re-applies it to the parked task; the park stands | http §1 |
| Offline-started review while another device has one open | client session id + `replace_open: true`; the other session is closed by the E3 rule and shows "review ended elsewhere"; no decision lost | http §6, ios-commands §4 |
| Decision naming an unknown session | recorded without a session (200) | http §3 |
| Settings edited on two devices | 409 → refetch, re-apply only the changed fields, resend | ios-commands §4 |
| Navigator configured `openai` without its key | container build raises at startup; the deploy fails its health check. A serving machine restarted with the key missing also stops, so key rotation follows the runbook (provider `disabled` first) | R13, rollback section |
| Navigator call slow or hanging | the cost reservation is written and the lock released before the provider call; the call runs with no lock held, so other owners' task writes never wait on it | http §7 |
| Flag turned off then on again, or sweep outage ≥ 24 h | owner park floor = now + 7 d, so every park is preceded by a visible marker | formulation-clock §3 |
| Account-less clock defect | Release ships the account-less switch off until the synced path is clean; ≤ 10 device parks per call, then M-09 | ios-commands §5, §8 |
| Two devices park the same formulation | one park; the other gets `applied: false` (200) | http §4 |
| Device clock ahead of server | due parks evaluated with the last observed server offset; online, the device parks locally only after `applied: true`; offline, the optimistic park gets `applied: false` on push and is not re-issued | R9, ios-commands §5 |
| Review idle for 7 days | the sweep closes it as partial or abandoned; the device that had it shows "closed after a week" with its decisions kept | http §9, design M-11 / M-13 / D-03 |
| Idempotent replay / lost write after record | existing `_reconcile_idempotent_result` with new prefixes | R7 |
| Undo after another change (task or created follow-up) | 409 `undo_unavailable`; design "undo didn't apply": "Couldn't undo: "<title>" changed on another device. It's in <list> now." + Ref | R8, design M-03/D-02 |
| Bulk release with stale items | 200 with `skipped`; M-10/M-15 partial-failure copy; undo restores clocks exactly and names skipped ones | http §6 |
| Sweep fails for one owner | logged with owner id, `type(exc).__name__` and a reason code (never `str(exc)`); other owners and other sweeps continue | http §9 |
| Cloud timeout / provider error / malformed / cost cap / rate limit / consent missing / flag off | 503 / 503 / 503 / 429 / 429 / 400 / 404 with reasons; card stays usable | http §7 |
| On-device model becomes unavailable mid-session | `unavailable(reason)` → M-06 | navigator §4 |
| App killed mid-form or mid-review | nothing applied to the task; typed text kept as a local draft and restored on reopen (FR-052); review progress persisted per decision/progress command; M-10 reopens on the released state with Undo | design M-04, M-10, M-13 |
| Old client saves a task (drops clock) | sweep restarts the clock with a 14-day floor | formulation-clock §3 |

## Migration, deploy order and rollback

- **Backend schema**: new tables are `CREATE TABLE IF NOT EXISTS` in
  `_initialize_database` plus a `migration_ledger` row `review-v1`; task fields live in
  the JSON payload. Additive and safe to run alongside the old code. No data is rewritten
  at deploy; activation backfill is per owner and only adds fields.
- **Deploy order**: backend (flag OFF) → iOS and web builds that understand the fields →
  flag `weekly_review` SELECTED_USERS (owner) → ON. Clients tolerate the backend
  without the feature (flag absent → old UI).
- **Rollback**: turn the flag OFF (immediate: the gated reads and the navigator return
  404, the sweep's exposure part is inert, device auto-parks get `applied: false`,
  clients show "coming later"). Writes that finish work a device already queued
  (decisions, undo, sessions, acknowledgements, settings, bulk releases) keep being
  accepted, and `GET /review/navigator` and the consent revoke stay reachable, so a
  rollback strands no queued work and no consent (contracts/http.md "Gate"). The sweep's
  retention part keeps running for every owner with review rows, so the 7-day snapshot
  and 35-day usage bounds hold while the feature is off (stated in
  `docs/data-retention.md`). Turning the flag on again triggers the sweep-gap floor (no
  park for 7 days, markers first). **Code rollback** loses no data: old code ignores
  the tables and the payload fields; on roll-forward the sweep repairs clocks dropped by
  old-code saves with a 14-day floor, so no early park can result. Two stated limits
  (contracts/http.md §8): the review retention is paused while the old build runs (the
  first sweep after roll-forward nulls every snapshot older than 7 days;
  `docs/data-retention.md` states the bound as "7 days; longer only while the backend
  is rolled back to a build without the review sweep"), and a parked Someday task
  re-saved by old code loses its `parked` marker (the park stays in E6 and the export,
  but the task no longer appears on While you were away). Nothing is irreversible
  except an auto-park that already happened, which the person can undo in one tap
  (M-09).
- **Navigator key rotation (runbook)**: because a missing key makes the backend refuse
  to start (R13), set `BRAIN_BUDDY_REVIEW_NAVIGATOR_PROVIDER=disabled` before rotating
  or removing the key and set it back after the new key is in place; PR-07 writes this
  next to the variables in `.env.example`.
- **Account-less iOS** has no remote switch: `BBWeeklyReviewLocal` stays `NO` in Release
  until the synced path has run clean for one threshold cycle (owner decision recorded
  at PR-14); the device caps parks per call (ios-commands §5, §8). The spec records
  this staged exposure (edge case "Account-less iOS use", FR-042); the owner confirms
  it when approving the slice map at `/speckit-tasks`.
- **iOS store**: v1 → v2 migration is additive; a downgraded app reports
  `.unsupportedVersion` and asks to update (existing behaviour).

## Observability

- Correlation: existing middleware; clients send `X-Correlation-ID` (iOS already does)
  and show `Ref` from `ApiError.correlationId` / `APIError.referenceID` on every
  failure state named in design.
- Logs (ids/codes/counts/timings only; never the stall reason): `review_decision`,
  `review_undo`, `review_auto_park` (`applied`, `source=sweep|device`, `yielded`),
  `review_sweep`, `review_settings_changed` (threshold old/new), `review_activated`,
  `review_run` (mode, status, counts), `review_due_date_moved` (owner and task ids
  only), `navigator` (outcome, provider, kind, tokens, proposals count,
  notes_truncated). A pytest log-capture test proves sentinel content and stall-reason
  values never appear (FR-044).
- Supporting metrics (intake §3) and their sources: decision/stall-reason distribution
  from `review_decisions`; re-stall rate from the consecutive count; parks returned from
  `review_park_acks.returned_at`; due-date moves on Next tasks from the
  `review_due_date_moved` log event (no persisted counter); median formulation age from
  task clocks; median active review time from `active_seconds_by_step`; SC-005
  real-use acceptance from decisions' `ai_use` over `navigator_usage.shown`
  (contracts/navigator.md §5; on-device use reported separately as an upper bound). The
  read-out is `python -m app.cli review-metrics` (content-free aggregates; Test
  strategy and "Post-release acceptance").

## Test strategy

Each slice starts with failing tests carrying `020-FR-…` / `020-SC-…` ids
(`test_020_FR_012_…` in Python). Allure: new module rules in
`backend/tests/allure_taxonomy.py` (epic Tasks, features "Formulation clock", "Review
decisions", "Auto-park", "Review flow", "Navigator") and `frontend/src/test/allureTaxonomy.ts`
(`/features/review/`), Playwright path rule in `frontend/tests/allure.fixtures.ts`.
Coverage floors (`backend/coverage-floor.json`, `frontend/coverage-floor.json`) may only
rise; no coverage suppressions in `frontend/src`.

| layer | what | key cases |
|---|---|---|
| pytest — pure rule | `test_review_formulation.py`, `test_review_formulation_vectors.py`, `test_review_flow_vectors.py` | every vector incl. the transitions schema (formulation-clock §6); boundaries ±1 s; DST; floors (activation, threshold, due date, sweep gap, time zone); extension at T/T+3/T+6 and at `park_due`; not activated → `none`; third stall; extend then reformulate before the extended ask → stalled (FR-005); yield reversal + extend / + reformulate; park → yield + cosmetic reformulate / + decision + undo → parked again; activation with a `Pacific/Honolulu` zone and a due date today; bulk undo clock equality; every `review_flow_vectors.json` section run against `review_rules.py` in PR-02 (incl. `stall_recommendation`, `active_time`, restart anchor from onboarding); copies present and byte-identical |
| pytest — service/API | `test_review_decisions_api.py` | each decision type and its `review_counts_as`; cosmetic "Save anyway" recorded as `reformulate`, `substantive: false`, clock unchanged; `someday` writes a `release` receipt and its Undo removes it; stale revision; stale formulation; idempotent replay and mismatch; client ids adopted, wrong id shape → 422 (a sentinel-text id never reaches a log), reused id under another key → `id_conflict`; `navigator_request_id` not a 36-char UUID → 422; unknown session → session-less 200; first-step "Was:"; extension once; `extend` keeps `reason_text`; follow-up in archived project; undo exact restore incl. clock; undo after change (task or follow-up) → 409; owner isolation → 404; **flag off**: decisions, undo, settings, park acks and the explainer ack accepted, gated reads → 404 `weekly_review_disabled`; FR-003 non-restarting edits through PATCH; `TaskResponse` built by the shared `task_mapping` for both routers; reconcile one idempotency record of every new prefix through `ReviewService`'s reconciler |
| pytest — activation and sweep | `test_review_auto_park.py` | explainer ack first-wins, clamp, floors, no revision bump; no park and no derived instants before activation (FR-051); due/not due; 24 h marker precedes park (SC-006: every park in the matrix is checked for a preceding `moves_tomorrow` window and for appearing in `unseen_parks`); FR-039, FR-046, time-zone and sweep-gap floors; skip after reformulate/move/extend; double park no-op; device park with server not due → `applied:false`; device park with the flag off → `applied:false`; yield rule both sides of `parked.at`; **offline notes edit, then offline card decision, server park between them → notes kept, decision applied with `yielded_auto_park: true`**; park → yield + cosmetic reformulate → next sweep parks again, no idempotency conflict logged; E6 row written at park time; notes-only PATCH before a park → 409, park stands; archived project; retention runs with the flag OFF (snapshot nulled after 8 days); sweep failure isolation, and the sweep over an invalid payload holding a sentinel logs only the exception type; the sweep resolves a `User` per owner for `is_effective`; return shape of `_run_privacy_maintenance_sweep` unchanged; driven by calling `_run_review_maintenance_sweep(container)` with `frozen_clock` |
| pytest — privacy | `test_review_export_purge.py`, log-capture test | every new table exported/excluded per data-model; purge removes all; purge idempotent; no sentinel text and no stall-reason value in logs; foreign vs unknown task ids in batch bodies, and foreign vs unknown `session_id` on `GET /review/queues/{step}`, give byte-identical responses (`second_api_client`) |
| pytest — navigator | `test_review_navigator.py` | **first failing test of PR-07: container build raises without the key** (and for `deterministic` outside TEST); the adapter is `app/ai/review_navigator.py` and `app.modules.tasks` imports no HTTP client (import-linter); strict input schema rejects extra fields incl. a language field; consent missing/revoked/provider mismatch/outdated version; **flag off: `GET /review/navigator` and the revoke work, suggestions and grant → 404, and the next flag-on suggestion after a flag-off revoke → 400 `navigator_consent_required`**; rate limit; per-call and daily cap; **provider stub that takes `command_lock` for another owner neither deadlocks nor waits** (reserve → call unlocked → settle; reservation released on timeout); timeout; malformed; duplicate filtering; grounding filter; `reduce_notes` vectors; **after a suggestion call, no idempotency record and no `task-commands/` entry or sentinel text exist**; `navigator_usage.shown` counted; deterministic provider in TEST; SC-005 screen runner over recorded outputs (`eval_v1.json`) |
| pytest — flow | `test_review_flow_api.py` | quick/full steps; completed / completed_empty / partial / abandoned and which count (FR-029): leaving keeps the session open and counted once it has qualifying activity, replacement and the 7-day idle close make it partial or abandoned, finish means Done only; resume; replace open; merged progress from two clients; finish idempotent; `SessionResponse` has exactly the http §6 fields; queue snapshot stable after threshold change and holding the aggregate in §5 order; **SC-002**: after a completed review with no set-aside, every task of the session's decision queue that still asks has a decision recorded on its current formulation in this session (a cosmetic "Save anyway" counts), and no other `asks_for_decision` task is left undecided; capacity numbers (41 / 9 per week) and < 4 weeks; Waiting and Someday eligibility/order (FR-032), incl. tasks released by the person in the last 30 days left out; receipts 7/30 days and revision invalidation; bulk release partial + clock-exact undo; **a 20-day Next task in a restart list → `not_eligible`**, an Inbox item processed in the session in an `inbox_remainder` list → `not_eligible`; restart mode at 21 days from the last counted review, and from `onboarded_at` for onboarded-never-reviewed, never before onboarding; `last_counted_review` summary in `GET /review/state`; `review_flow_vectors.json`; golden wire fixtures validate against `schemas/review.py` |
| pytest — read-out | `test_review_metrics_readout.py` | `python -m app.cli review-metrics` over seeded synthetic sessions computes weeks with a counted review (SC-001), share of "yes" (SC-003), median active minutes per mode (SC-004), the SC-005 real-use rate (decisions with `ai_use` `as_is`/`edited` over `navigator_usage.shown`, incl. a shown-then-abandoned request in the denominator) and the on-device `ai_use` share reported separately as an upper bound, parks returned; each figure printed with its sample size; output is aggregates only |
| pytest — traces | `test_review_traces.py` | each golden operation trace in `fixtures/review_traces/` (request sequence + expected status and response) passes against the real API: decide, decide stale, auto-park `applied:false`, yield after a queued notes edit, session start / replace / merged progress / finish, settings 409, flag off with queued writes. The same files are replayed against `BrainBuddyFakeServer` in Swift, so the fake server cannot drift from the backend on the offline and two-device paths (`020-SC-007`, `020-FR-013`) |
| Swift Testing (Linux) | `FormulationTests`, `ReducerReviewTests`, `QueriesReviewTests`, `NavigatorValidatorTests`, `ReviewPlannersTests`, `ReviewSyncTests` | shared formulation and review-flow vectors; reducer clock on every command; post-replay activation step; replay determinism; **compacted vs uncompacted outbox give identical clocks** (title edit / move after a Next entry); compaction of decision+undo; drafts keyed by formulation; 409 refetch path; `.review` conflict target and every ReviewCommand rule; two devices start a review offline → 0 decisions lost; queued edit survives activation; `applied:false` no re-issue loop; park cap per call; local 7-day maintenance; StoreDocument v1→v2; account-less parks; golden wire fixtures decode into DTOs and `BrainBuddyFakeServer`; golden operation traces replayed against `BrainBuddyFakeServer` give the recorded responses; `ReviewReminderPlanner`, `ReviewRoute`/`ReviewEntryPlanner`, `MarkerStyle` (no error role); `ReviewCopy` entries contain no banned term (US5-6, incl. notification and widget strings); `StallReasonRecommendation` against the `stall_recommendation` vectors, every decision still enabled, clearing the reason clears it (`020-FR-007`, US1-6); `ActiveTimeAccumulator` against the `active_time` vectors (gap > 2 min, background, resume, per-step; `020-SC-004`); `UndoWindowPolicy` (~5 s, ≥ 10 s with VoiceOver or Switch Control; `020-FR-048`); `WhileAwayPresentation` (dismissed today → not again today, shown tomorrow, always first in the review; `020-FR-015`); `NavigatorProposalFilter` drops a duplicate of the 21st (unsent) sibling (`020-FR-019`); **offline notes edit + offline card decision with a server park between → 0 sync issues, decision applied**; **flag turned off with 3 queued review commands → 0 set-asides, 0 reverted decisions**; **device clock 2 days ahead, online → no local park, no M-09 entry**; a rejected decision's sync issue names the current list; offline review synced with 0 lost decisions (SC-007) |
| Swift Testing (Linux), PR-09 | `ModelDownloadMachineTests` | request-only start; progress; interruption and resume (incl. after an app kill, from persisted state); finished while away; cancel removes the partial file; insufficient storage; retry; switch to cloud; delete; never required for non-AI parts; the router never falls back silently to cloud (FR-049, US3-4a/4b), with injected `ModelDownloader` / `StorageProbe` |
| Xcode (`ios-app` lane) + manual | app/widget targets compile; previews per design state | AppleNavigatorModel behind `#if canImport(FoundationModels)`; widget families. App-target glue that no package test can reach is checked on a simulator or device and recorded in `specs/020-weekly-review/evidence/manual-ios-*.md`, labelled **manual**, one entry per id: notification registration (`020-FR-036`), widget `Link` (`020-FR-037`), `.presentationDetents([.large])` (`020-FR-047`), `interactiveDismissDisabled` (`020-FR-052`), the Undo toast's VoiceOver announcement and its ≥ 10 s window in use (`020-FR-048`), one decision per screen in the Inbox, decision, Waiting and Someday steps (`020-FR-034`), 44 pt targets on markers, chips and Undo (design "Mobile viability"), the Lists row replacing `DeferredRow` (`020-FR-042`), and VoiceOver focus on M-26, M-09, M-10, M-11, M-12 and after M-06 / M-07 close (design "Keyboard and focus"); the requirement ids are also named by the Core tests of the decisions behind them |
| Vitest | `features/review/__tests__/*` | `formulation.ts` normalisation vectors and `classifyFromInstants` over the classification vectors; `stallRecommendation.ts`, `activeTime.ts` and `wywaPresentation.ts` against the same `review_flow_vectors.json` sections as Swift; the navigator duplicate filter drops a duplicate of an unsent sibling; markers only for the aggregate in lists; offline marker buttons stay focusable with `aria-disabled`; D-02 focus/trap/Esc/keys-in-text-fields/stale/save-failed/Ref, the cloud clarifying question and its two-stage failures (answer not saved; answer saved, suggestion failed) with no stale error after the own notes edit; unsaved-text confirmation, draft restore, `beforeunload` and the history guard (browser Back on D-02 and on `/review`); Undo toast incl. Ctrl/Cmd+Z; WYWA dialog states incl. "continue not saved"; D-05; D-06 states and focus return to "Decide"; D-03 Inbox step, step loading / load failed, step-action failures, restart and Inbox release pending / failed / undo failed, last-review summary, "closed after a week", inline-card Esc order; sidebar recap loading / failed / never reviewed; settings floor note and the consent switch shown with the flag off; golden wire fixtures; **string and token guard**: review-feature strings and rendered markers contain no "overdue", streak wording or rose/red tokens; **client telemetry guard**: every `recordTelemetry` event the review feature emits carries ids, codes, counts and timings only, with sentinel title, notes, reason and AI text absent from its payload (`020-FR-044`); AppShell flag-off keeps "Weekly review — Coming soon" (existing test unchanged), flag-on link + "Last review" |
| Playwright | `frontend/tests/e2e/weekly-review.spec.ts` | stalled task seeded through `python -m app.cli review-seed-aged-task` (TEST only) → D-05 → decide → Undo; auto-park via `python -m app.cli review-run-sweep` → WYWA → return; quick review end-to-end; a session finished through the API as an iOS client would (offline then synced) shows its summary on the `/review` entry (`020-SC-007`); consent decline path with deterministic provider; **keyboard-only story** (E2E-A11Y-01): Tab to a marker, Enter, 2, type, Esc → "Keep editing", Esc again → Discard, focus back on the marker chip; decide with 5, then Ctrl+Z; start `/review`, step heading focused after "Skip step", Esc on the inline card does nothing; browser Back on `/review` shows the Leave confirmation; **axe scans** (`@axe-core/playwright`, already a dependency) of D-01 with the WYWA dialog, D-02, D-03, D-04, D-05 and D-06 at desktop and 390 px; no horizontal overflow at 390 × 851 for `/tasks/next` with markers, the decision dialog, `/review` (Waiting step and summary), the review section of `/settings/account` and D-05; flag-on drawer link at 390 px |
| macOS (manual host run) | `macos/Tests/BrainBuddyMacTests` | the FR-041 "coming later" row only; no CI lane runs `macos/`, so PR-06 evidence is a recorded `swift test --disable-sandbox` run on a macOS host; US6-1 is not verified until the Mac-sync spec exists |

Time control: one injected clock (`frozen_clock` fixture) for every time-based pytest
case (research R21). Shared vectors: the formulation vector file and a second
`review_flow_vectors.json` (wins window, capacity incl. < 4 weeks, Waiting/Someday
queue membership and order, restart eligibility and its anchor, session status and
counted-review rules, regularity instant, notification skip, decision-queue order,
`stall_recommendation`, `active_time`, the While-you-were-away once-a-day rule, the
navigator project-wide duplicate filter) are canonical in `backend/tests/fixtures/`,
copied byte-identically by PR-02 into the Swift and web test trees, with the drift
guard of formulation-clock §6. **Fixture ownership**: PR-02 also executes every flow
section once against the pure `backend/app/modules/tasks/review_rules.py`, so no lane
consumes a vector that has never run; PR-11 builds the flow service on those
functions. A vector change after PR-02 follows formulation-clock §6 "Changing a vector
after PR-02": one slice edits the canonical file and both copies, and depends on
every slice that already consumes it. Golden wire fixtures
(`backend/tests/fixtures/review_wire/*.json`, validated by pytest against
`schemas/review.py`) are copied the same way and decoded by the Swift DTO /
`BrainBuddyFakeServer` tests and Vitest, so wire drift fails mechanically.

**Evidence rule** (constitution I): every screenshot, recording or Allure attachment in
`specs/020-weekly-review/evidence/` and in slice PRs comes from a seeded synthetic
account using the design's example data (the Playwright seed in `weekly-review.spec.ts`).
Results from the owner's real use (SC-001, SC-003, SC-004, SC-005, the definition of
done) are recorded only as the numbers the `review-metrics` read-out prints — never
titles, notes, reasons or summaries. PR-14 adds `evidence/README.md` stating this rule.

**Slice acceptance vs post-release acceptance**. A slice is accepted on automated
evidence only: the tests named above on synthetic data, including the automated
outcomes SC-002 (flow test), SC-006 (sweep matrix) and SC-007 (offline sync, trace
replay, web summary), plus the read-out tooling proven on seeded sessions. SC-001,
SC-003, SC-004 and the real-use half of SC-005 are "measured per active user over the
first 8 weeks after their first review" (spec), which is after every merge, so they are
**post-release acceptance**, not slice gates. SC-007's "loses 0 decisions" means no
decision made offline is silently dropped: each one is applied on the server or, when
the task changed elsewhere first (spec edge case "Concurrent edits"), rejected
visibly as a Sync issue with its Ref and the task's current list; the automated SC-007
cases seed no concurrent change, so every decision in them must apply.

Post-release acceptance:

| item | rule |
|---|---|
| owner | Max (the product owner) runs and records it |
| window | 8 weeks from the owner's first counted review after the flag is ON for them |
| procedure | weekly, the owner runs `python -m app.cli review-metrics --owner <id> --since <date>` in the production backend container (read-only, aggregates only); weekly, because `navigator_usage` rows live 35 days |
| record | numbers only, appended to `specs/020-weekly-review/evidence/real-use-readout.md` (evidence rule); the 8-week figures are computed from the weekly records |
| minimum sample (proposed; the owner confirms these numbers with the slice map at `/speckit-tasks`) | SC-001: all 8 weeks; SC-003: at least 6 answered reviews; SC-004: at least 4 reviews per mode before a median is reported (otherwise "insufficient"); SC-005: at least 20 shown cloud suggestion requests |
| flag stages | SELECTED_USERS (owner) → wider stages: the cloud navigator source opens only after its SC-005 evaluation cell passed (PR-14); widening beyond the owner waits for the 8-week read-out, and a miss is reported to the owner as a product signal, not reverted automatically |

Requirement coverage: once PR-01 extends the scanner to Swift test trees, every
FR-001 … FR-052 and SC-001 … SC-007 is gate-enforced and must be named by at least one
test (`020-FR-046`, `test_020_FR_046_…`) and listed in the `requirements` of its slices
(research R19). The full-feature gate (`check_requirement_coverage.py
specs/020-weekly-review` in `make check-specs`) lands in PR-14, because it fails while
any requirement is still untested; before that, each slice runs the scanner with the
`--requirements` filter PR-01 adds, limited to the slice's own `requirements`. For
FR-041 the recorded macOS-host run file is required in addition to the name match. Live
provider evaluation (SC-005) is approval-gated and never runs unattended.

## Delivery slices

Proposed PR-sized slices; they become `## PR-срезы` at `/speckit-tasks` and need the
owner's approval there. Classes per ADR-0008 / `scripts/classify_path_risk.py`
("mech." = the classifier result; final class = the stricter of mechanical and semantic).

| id | increment | outcome | depends on | main paths | class |
|---|---|---|---|---|---|
| PR-01 | 1 | ADR-0027 accepted; design skill reworded to "flag-gated, deferred while off" with its test; Swift test trees in requirement coverage (with a test that a Swift test naming an id satisfies the gate) and a `--requirements` filter for per-slice tracing; architecture-guard docstring | — | `docs/decisions/0027-…md`, `.claude/skills/brain-buddy-design/{README.md,SKILL.md}`, `scripts/test_validate_brain_buddy_design_skill.py`, `scripts/check_requirement_coverage.py`, `scripts/test_check_requirement_coverage.py`, `.specify/gate-integrity.json`, `backend/tests/test_voice_workflow_architecture.py` | **ASK** (mech.: `scripts/`, guarded files) |
| PR-02 | 1 | Backend clock (with client formulation ids), decisions, undo, auto-park sweep (retention + exposure parts) and device endpoint, **explainer acknowledgement and activation (FR-051)**, settings/state, park acks, all review tables, export/purge, flag (exposure-only gate); the shared `task_mapping` mapper; the generalised serialized-write protocol; mounts all three routers and wires the container (navigator and flow routers empty until their slices); injected clock; TEST-only CLI seed/sweep; import-linter contracts for the review modules (incl. no HTTP client in `app.modules.tasks`); canonical formulation and review-flow vectors executed against `review_rules.py`, golden wire fixtures and the decision / park traces **plus their iOS and web copies**; every Allure taxonomy rule for the review modules (`backend/tests/allure_taxonomy.py`, so later backend slices do not edit it); data-retention rows for the server tables (with the rollback wording), the iOS store v2 contents and web form drafts; privacy-policy wording naming review day, time and time zone | PR-01 | `backend/app/modules/tasks/*`, `backend/app/api/{review.py,review_navigator.py,review_flow.py,tasks.py,task_mapping.py,dependencies.py,__init__.py}`, `backend/app/schemas/{tasks.py,review.py}`, `backend/app/core/config.py`, `backend/app/repositories/feature_flag.py`, `backend/app/services/account_service.py`, `backend/app/container.py`, `backend/app/main.py`, `backend/app/cli.py`, `backend/pyproject.toml`, `docs/data-retention.md`, `frontend/src/pages/PrivacyPolicyPage.tsx`, backend tests and fixtures, `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/Resources/{review_formulation_vectors.json,review_flow_vectors.json,review_wire/*}`, `frontend/src/features/review/__tests__/{review_formulation_vectors.json,review_flow_vectors.json,review_wire/*}` | **ASK** (mech.: `api/tasks.py`, `api/dependencies.py`; sem.: privacy export/purge, first automatic state change) |
| PR-03 | 1 | iOS core: records, clock in reducer (client formulation ids, post-replay activation step, clock-aware compaction), new commands incl. `acknowledgeExplainer`, `.review` conflict rules, queries and Core planners, drafts in `local`, local maintenance and park cap, StoreDocument v2, API/sync mapping, fake server | PR-02 (vector and wire-fixture copies; can be developed in parallel against the frozen contracts and rebased) | `ios/BrainBuddyKit/**` except the PR-02 resource copies | SHOW (mech. SHIP; persistence format change) |
| PR-04 | 1 | iOS UI for US1/US2: **M-26 explainer**, M-01, M-02, M-03, M-04 (no Suggest; unsaved-text states and drafts), M-09, M-23 threshold | PR-03 | `ios/BrainBuddy/Screens/{Lists,Detail,Settings,Review}/*`, `ios/BrainBuddy/Components/*`, `ios/BrainBuddy/App/*`, `ios/project.yml` (`BBWeeklyReviewLocal` NO in Release) | SHOW |
| PR-05 | 1 | Web US1/US2: **D-05 explainer**, D-01 markers and WYWA dialog states, inline "This wording", D-02 without navigator (unsaved-text states, drafts, `beforeunload`), D-04 threshold, action toast with Ctrl/Cmd+Z, 390 px states | PR-02 | `frontend/src/features/{tasks,review,account}/*` except the PR-02 test copies, `frontend/src/api/{review.ts,reviewHooks.ts,taskTypes.ts}`, `frontend/src/components/shell/shellToast.ts`, `frontend/src/test/allureTaxonomy.ts` | SHOW |
| PR-06 | 1 | Mac "Weekly review · coming later" row; evidence is a recorded macOS-host run | — | `macos/Sources/BrainBuddyMac/ContentView.swift`, `macos/Tests/BrainBuddyMacTests/*` | SHIP |
| PR-07 | 2 | Backend navigator: adapter in `app/ai/` behind the port (startup raises without key; key-rotation runbook in `.env.example`), consent with text versions (read and revoke never gated), usage caps admitted outside the lock, `shown` counter, routes, env; `eval_v1.json`, deterministic screen runner and recorded-output format (SC-005, before any cloud exposure); privacy policy and data-retention rows for the navigator purpose and data set, including that the provider keeps its copy beyond account purge | PR-02 | `backend/app/ai/review_navigator.py`, `backend/app/modules/tasks/navigator.py`, `backend/app/api/review_navigator.py`, `backend/app/core/{config.py,rate_limit.py}`, `backend/app/container.py`, `.env.example`, `backend/tests/fixtures/navigator/*`, `frontend/src/pages/PrivacyPolicyPage.tsx`, `docs/data-retention.md`, tests | **ASK** (mech.: `.env.example`; sem.: provider credentials, new egress, consent, privacy disclosure) |
| PR-08 | 2 | iOS navigator: protocol, router (route caption, quiet cancellation), validator and `reduce_notes`, Apple model, cloud client, M-05, M-06 (cloud choice, cloud unavailable), M-07, M-08, M-19 AI states, M-23 Suggestions | PR-04, PR-07 | `ios/BrainBuddyKit/Sources/BrainBuddyCore/Navigator.swift`, `…/BrainBuddyAPI/NavigatorAPI.swift`, `ios/BrainBuddy/Navigator/*`, `ios/BrainBuddy/Screens/Review/*` | SHOW |
| PR-09 | 2 (late; may slip) | Downloadable on-device model: dependency-exception ADR, Core AI runtime + model pack, `ModelDownloadMachine` with its tests, M-06 download states, M-23 delete (FR-023 (a), FR-049); its SC-005 evaluation cells; data-retention and privacy-policy rows for the model file and the device-local preference | PR-08 | `ios/BrainBuddy/Navigator/DownloadedNavigatorModel.swift` (new), `ios/BrainBuddyKit/Sources/BrainBuddyCore/ModelDownloadMachine.swift` (new), `ios/project.yml`, `ios/Shared/PrivacyInfo.xcprivacy`, `docs/decisions/` (new ADR), `docs/data-retention.md`, `frontend/src/pages/PrivacyPolicyPage.tsx` | **ASK** (third-party dependency exception, external model download, new entitlement) |
| PR-10 | 2 | Web navigator in D-02 (notes-shortened, input-too-large, suggestions-unavailable states); D-04 consent switch (pending until the DELETE succeeds) | PR-05, PR-07 | `frontend/src/features/review/*`, `frontend/src/api/review.ts` | SHOW |
| PR-11 | 3 | Backend review flow: runs (client ids, merged progress, `completed_empty`, no "left" outcome, idle close, active time), queues, capacity, receipts (incl. `release` receipts), bulk release with server-side eligibility and clock snapshots, restart (anchor from onboarding), regularity, last counted review summary, next review; session traces; `review-metrics` read-out | PR-02 | `backend/app/modules/tasks/review_flow.py`, `backend/app/api/review_flow.py`, `backend/app/cli.py`, tests | SHOW |
| PR-12 | 3 | iOS review: M-10, M-11, M-12, M-13 – M-22, M-23 schedule, M-24 widget, M-25 notification, Lists entry | PR-08, PR-11 | `ios/BrainBuddy/Screens/{Review,Browse,Settings}/*`, `ios/BrainBuddy/Review/*`, `ios/BrainBuddyWidgets/*`, `ios/BrainBuddy/App/*`, `docs/native-ios-app.md` | SHOW |
| PR-13 | 3 | Web review: D-03 shell and steps (incl. the Inbox step, step loading and step-action states, restart and release states, last-review summary, browser Back, 390 px), onboarding dialog, sidebar and drawer link + "Last review", D-04 schedule; the web part of US3-8 (M-19 in D-03); e2e incl. the keyboard-only story and axe scans | PR-10, PR-11 | `frontend/src/features/review/*`, `frontend/src/app/AppRoutes.tsx`, `frontend/src/components/shell/AppShell.tsx`, `frontend/tests/e2e/weekly-review.spec.ts`, `frontend/tests/allure.fixtures.ts` | SHOW |
| PR-14 | 3 | Release: requirement coverage for 020 in `check-specs`, plus the vector-copy byte check in `check-specs`; `evidence/README.md` (evidence rule) and the recorded read-out; manual iOS evidence files; flag stages, each opened only for navigator sources whose SC-005 cell passed; the owner's recorded decision on `BBWeeklyReviewLocal` for Release | PR-12, PR-13 | `Makefile`, `.specify/gate-integrity.json`, `backend/coverage-floor.json`, `frontend/coverage-floor.json`, `specs/020-weekly-review/evidence/*` | **ASK** (mech.: `Makefile`) |
| (US6) | 4 | Mac review after Mac↔backend sync | Mac sync spec | planned when that spec exists | — |

Write-path notes: slices with no dependency between them do not share write paths.
PR-06 is disjoint from all. PR-02 writes the router mounts, container wiring and flag
for all three routers, so PR-07 and PR-11 are **siblings** after PR-02 (the guided
review no longer waits for the navigator backend); they share no file except
`backend/app/container.py`, which PR-07 edits (navigator provider) and PR-11 does not,
and `backend/app/cli.py`, which only PR-02 and PR-11 edit. PR-02 also writes the
vector and wire-fixture copies under `ios/` and `frontend/`; PR-03 and PR-05 read them
and depend on PR-02. `docs/data-retention.md` and `PrivacyPolicyPage.tsx` are written
by PR-02, PR-07 and PR-09, which form a dependency chain. Lanes: backend PR-02 → PR-07
‖ PR-11; iOS PR-03 → PR-04 → PR-08 → PR-12, with PR-09 off PR-08; web PR-05 → PR-10 →
PR-13; Mac PR-06; governance PR-01 first and PR-14 last. Increment boundaries match the
owner's increments: (1) rule + card + auto-park + markers + the one-time explainer on
backend, iOS, web; (2) navigator; (3) full guided review +
schedule/notification/onboarding; (4) macOS after Mac sync. User Story 2's
review-dependent parts (While you were away as the first review screen, restart mode)
verify with increment 3.

Rules `/speckit-tasks` applies when it turns this table into the PR-срезы manifest
(campaign 2):

- **Split PR-02** into a behaviour-neutral first slice (the injected clock seam in
  `TaskService`, which calls `utcnow()` directly today, the `frozen_clock` fixture,
  `formulation.py`, `review_rules.py`, the vector files and their copies, the Allure
  taxonomy rules) and the behaviour slice (decisions, undo, activation, sweep, tables,
  routes). The vector consumers (PR-03, PR-05) then depend on the first part only, and
  the ASK behaviour change is reviewed and rolled back on its own.
- **File-level write paths only**: no globs, brace sets or bare "tests"
  (`check_spec_kit_specs.py:217-235` rejects glob characters and overlapping paths of
  independent slices); each slice lists its own test and fixture files by name, so
  sibling slices (PR-07 and PR-11) never share `backend/tests`.
- **Single owners for shared files**: `backend/tests/allure_taxonomy.py` → PR-02 (all
  review rules at once); `frontend/src/test/allureTaxonomy.ts` → PR-05;
  `frontend/tests/allure.fixtures.ts` → PR-13; `backend/coverage-floor.json` and
  `frontend/coverage-floor.json` → raised only in PR-14 (after every lane), so no two
  independent slices edit them; `ios/BrainBuddyKit/Package.swift` (test-resource
  declarations) → PR-03, the first slice that loads the copies.
- **Traces**: the decision and park traces and their iOS copies land in PR-02; the
  session traces in PR-11 (backend only); their Swift replay test lands in PR-12, which
  depends on PR-11.
- **Vector changes** after the first slice follow formulation-clock §6.

## ASK-class surfaces (summary)

- `backend/app/api/tasks.py`, `backend/app/api/dependencies.py` (explicit ASK paths).
- `scripts/test_validate_brain_buddy_design_skill.py`, `scripts/check_requirement_coverage.py`
  (`scripts/` prefix; the latter is in `GUARDED_FILES` → re-record
  `.specify/gate-integrity.json` with `python3 scripts/check_gate_integrity.py --update`).
- `Makefile` (guarded; `check-specs` invariant keeps the 019 line, 020 is added beside it).
- `.env.example` (env file pattern).
- Semantic ASK: account export/purge of new personal data (privacy), the first automatic
  GTD state change, cloud-provider credentials and egress, a third-party iOS dependency and
  model download.
- Because `plan.md` names ASK `.py` paths, `scripts/spec_kit_planning_review.py`
  derives risk **high** for this feature: the review run needs the recorded human sign-off
  (ADR-0012).

## Inconsistencies found while planning

Status after the owner's decisions and the spec amendments of 2026-10-05:
- **Resolved in spec.md**: items 1 (edge-case note), 2 (NC-1: measured from the
  extension day), 3 (renumbered FR-046 – FR-050), 4 (D-11 attribution) and 5 (FR-005:
  canvas only where it exists).
- **Remaining work in this plan**:
  - item 2: the M-04 date copy — corrected in design.md and the M-04 mockup on
    2026-10-06 ("Keep until Fri 16 Oct");
  - item 6: new web UI in PR-13, now designed (design D-03 "Inbox step" rows);
  - item 7: no impact.

1. **Archived-project states are unreachable today.** Archiving a project clears
   `project_id` on its tasks on the backend (`service.py:989-1012`) and on iOS
   (`Reducer+Organize.swift:58-70`); ADR-0020's lossless archive is accepted but not
   implemented. So the spec edge case "Task in an archived project", M-02 "parked,
   project archived", M-09 "partial failure: archived project" and M-18 "archived project"
   cannot occur until spec 011's archive change lands. The plan implements the guard
   (`project_archived` reason) defensively and tests it with a fixture, nothing more.
2. **Extension arithmetic** FR-009/FR-012 vs US1-7 and M-02 (NC-1). Also M-04 "Keep until
   Thu 15 Oct" with today Fri 9 Oct is 6 days, matching neither reading.
3. **Lettered requirement ids** (formerly the lettered variants of FR-003, FR-010, FR-011, FR-023 and FR-034)
   were not recognised by `scripts/check_requirement_coverage.py:44` or the PR-срезы
   validator in `scripts/check_spec_kit_specs.py:165-166, 212-214`. Resolved: they were
   renumbered FR-046 – FR-050 (R19).
4. **D-11 attribution**: spec Assumptions and intake cite "ADR-0006 (… D-11)"; D-11 is in
   `docs/vnext-cloud-design-build-contract.md:757`, not ADR-0006.
5. **Third-stall "Think it through" on iOS**: FR-005/M-03 offer the thinking canvas, but
   the iOS app has no CRT canvas (CRT is web-only, `/crt`, flag `crt_canvas`). Plan: on
   iOS the offer shows only "Release to Someday" plus the reassurance copy; on web it links
   to `/crt` when `crt_canvas` is effective. Settled by FR-005; design M-03, D-02 and the
   affordance map were amended accordingly on 2026-10-06.
6. **"Process inbox Undo" on web**: design D-03/M-15 assume the existing Process inbox
   and its Undo; the web has neither (`frontend/src` has no Process-inbox flow and a
   text-only toast). The web Inbox step is new UI (PR-13), not reuse.
7. **ADR-0002 status**: the spec calls ADR-0002 binding; its header says
   `Status: Proposed`. No impact here (voice review is out of scope).

## Planning review

Campaign 1 (`020-weekly-review-c1`) dispositions, finding by finding, are in [review-c1-disposition.md](review-c1-disposition.md).
Campaign 2 (`020-weekly-review-c2`, the last allowed campaign) dispositions are in [review-c2-disposition.md](review-c2-disposition.md).

## Constitution Check (post-design)

- Spec workflow — PASS (NC-1 – NC-4 resolved by the owner on 2026-10-05; PD-1 – PD-3
  resolved on 2026-10-06 and applied to spec, design, contracts and this plan; campaign 1
  findings dispositioned in review-c1-disposition.md, campaign 2 findings in
  review-c2-disposition.md, with no owner decision reversed).
- Consent & Safety — PASS: strict navigator input, per-request consent re-check,
  no silent fallback, content-free logs with a test, export + purge of every new record,
  undo snapshots time-limited.
- Tests — PASS: failing-first tests per slice; edge cases for idempotency, stale,
  timeouts, consent denial, partial failure, offline replay.
- Contracts — PASS after campaign 1: the first version's claim that the four contract
  files agreed was wrong (client-created ids were missing from the HTTP bodies, the
  extension precondition excluded `park_due`, bulk-release undo had no clock to restore,
  `client_occurred_at` had no defined rule). Those are now aligned with `data-model.md`
  (E-numbers referenced from http and ios contracts); additive changes; backend before
  clients.
- Observability — PASS: Ref on every failure; reason codes; sweep and decision logs.
- Mobile/resilience — PASS: offline outbox for all task/review commands with a stated
  conflict rule per review command; yield rule; idempotent parks; resumable review;
  unsaved text kept as drafts with a leave warning (FR-052); narrow 390 px web states.
- Delivery boundary — PASS: slices with classes; ASK slices named; owner approves the
  slice map at `/speckit-tasks`.
- Design citation — PASS: every user story section cites its M-/D- ids.

Delivery risk: **HIGH / ASK** remains for the feature (PR-01, PR-02, PR-07, PR-09, PR-14).

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Review records stored in the Tasks module's SQLite file instead of ADR-0001's separate Review module | atomic decision + task write, exact Undo, one idempotency record per decision | separate store needs a saga for every decision and a second export/purge path (R1); recorded by ADR-0027 |
| Clock rule implemented three times (Python, Swift, TS key only) | iOS must work offline/account-less; web shows the cosmetic-edit note | server-only rule cannot serve offline iOS; mitigated by one byte-identical vector file with a drift test (R3) |
| Possible first third-party iOS dependency (PR-09) | FR-023 (a) downloadable on-device model; Russian is not listed as supported by Apple's model (unverified, treated as unsupported) | isolated behind `NavigatorModel`, app target only, approved by the owner (NC-2), gated by a dependency-exception ADR and its own ASK slice; Core AI's raw framework without the package would need a hand-written tokenizer/decoder (`research-on-device-model.md` §2) |
