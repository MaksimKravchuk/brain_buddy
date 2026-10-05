# Implementation Plan: Weekly Review

**Branch**: `020-weekly-review` (work branch `claude/weekly-review-concept`) | **Date**: 2026-10-05 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/020-weekly-review/spec.md`

**Design authority**: [design.md](design.md) (signed off by Max 2026-10-05), iOS screens
M-01 – M-25 and web screens D-01 – D-04, with their state tables.

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
dependency; it is isolated in slice PR-09 and gated by NC-2 and its own ADR
(research.md R13; `research-on-device-model.md`).

**Storage**: backend `<data_dir>/tasks.sqlite3` (Tasks module): new optional task payload
fields plus new tables `review_settings`, `review_sessions`, `review_decisions`,
`review_receipts`, `review_park_acks`, `review_bulk_releases`, `navigator_consents`,
`navigator_usage` ([data-model.md](data-model.md)). Feature flag in the existing ADR-0019
SQLite flag store. iOS: App Group `store.json` (`StoreDocument` v1 → v2). Device-local
model file in app Application Support. Web: no new persistent browser storage.

**Testing**: pytest + FastAPI TestClient (`api_client`, `second_api_client`); Vitest +
Testing Library; Playwright (`frontend/tests/allure.fixtures.ts`); Swift Testing in the
package on Linux (`sh ios/scripts/swift-linux.sh test`) and Xcode (`ios-app` lane). Every
product test names a feature-qualified id (`020-FR-001`, `test_020_FR_001_…`) and emits
the Allure taxonomy (pytest/Vitest/Playwright only; Swift tests are not Allure, per
`docs/test-allure-taxonomy.md`).

**Target Platform**: Linux server (Fly.io); iPhone iOS 26 (iPhone 390 × 851 design
frame), widgets; desktop web; macOS 26 POC (row only until Mac sync).

**Project Type**: modular-monolith web service + native iOS app + web SPA.

**Performance Goals**: markers computed in O(1) per task from stored fields; list
endpoints add one settings read per request; iOS marker computation inside the existing
`GTDQueries.list` pass without extra store reads; maintenance sweep ≤ 1 indexed query
plus one owner-locked transaction per affected owner every 60 s. Navigator: cloud
p95 ≤ 8 s (timeout), on-device first token visible ≤ 2 s on an Apple-Intelligence device
(placeholder lines shown after 300 ms per design).

**Constraints**: iOS offline-first and account-less (FR-040, FR-014); no task content in
logs/metrics (FR-044); consent re-checked per cloud request (FR-024); auto-park is the
only automatic state change (FR-018); idempotent owner-serialized commands (FR-011);
ADR-0006 four open lists unchanged; no Swift third-party dependency without an
explicit exception (`ios/AGENTS.md`).

**Scale/Scope**: invite-gated multi-tenant beta; tens of owners, hundreds of open tasks
each; ~40 new endpoints-or-fields across 3 clients; 29 designed screens.

## Constitution Check (pre-design)

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Spec workflow** — PASS. `intake.md`, `spec.md` (Clarifications session 2026-10-05,
  no NEEDS CLARIFICATION markers), `checklists/requirements.md` and the signed-off
  `design.md` exist. Two owner questions found during planning are recorded in
  research.md (NC-1 – NC-4) with defaults; none changes increment 1's contracts.
- **Consent & Safety** — PASS with design. On-device navigator needs no consent and sends
  nothing (FR-022). Cloud requires a persisted per-owner per-provider consent that the
  server re-checks on every request; revocation stops the next request; no silent
  fallback from on-device to cloud (contracts/navigator.md §4). Navigator input is a
  strict schema of exactly the FR-019 fields. No titles, notes, reason text or AI I/O in
  logs/metrics/fixtures; navigator evaluation set is synthetic. New durable records are
  exported and purged (data-model "Export and purge"). New provider key is read from an
  env var named by `BRAIN_BUDDY_REVIEW_NAVIGATOR_API_KEY_ENV`; startup fails loudly when
  the provider is enabled without it.
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
  apply nothing (design M-03/M-04 offline rows). Web is online-only with the existing
  "You're offline" pattern. No canvas impact.
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
| `backend/app/api/tasks.py` (**ASK**) | task routes; `_to_response` (l.1189) builds `TaskResponse`; title-completion routes and log line | map `formulation`/`parked` |
| `backend/app/api/dependencies.py` (**ASK**) | `get_task_service` (l.111), `require_voice_brain_dump_enabled` (l.361) | `get_review_service`, `require_weekly_review_enabled` |
| `backend/app/api/__init__.py` | mounts `task_router` into `api_router` | mount review routers |
| `backend/app/main.py` | `_run_privacy_maintenance_sweep` (l.26), `_run_maintenance_sweep` (l.85), `_start_privacy_maintenance_thread` (l.156); threads off in TEST unless `BRAIN_BUDDY_ENABLE_VOICE_SWEEP_IN_TEST=1` | `_run_review_maintenance_sweep` on the same thread |
| `backend/app/services/account_service.py` | ZIP export (l.207, `tasks/*.json`, manifest `excluded`), `purge_account` (l.416) ordered and idempotent | `review/*.json` export; purge unchanged (covered by task repo) |
| `backend/app/ai/title_completion.py` | provider build (`disabled`/`deterministic`/`openai`), timeouts, candidate validation; per-request consent echo | pattern for the navigator adapter |
| `backend/app/core/config.py` | `KNOWN_FEATURE_FLAGS` (l.86), provider settings | `weekly_review`; navigator settings |
| `backend/app/repositories/feature_flag.py` | `MANAGED_FLAGS` (l.83), `_POST_ADR_0019_DEFAULT_OFF_FLAGS` (l.100), upgrade whitelist (l.426) | register `weekly_review` OFF |
| `backend/app/core/rate_limit.py` | `title_completion_rate_limiter` (l.255) | `navigator_rate_limiter` |
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
├── research-on-device-model.md     # separate on-device model research (not written by this stage)
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
│   │   ├── tasks.py                          # ASK: _to_response maps formulation/parked
│   │   ├── review.py                         (new) decisions, undo, auto-park, state, settings, park acks
│   │   ├── review_navigator.py               (new) navigator consent + suggestions
│   │   └── review_flow.py                    (new) review runs, queues, bulk release
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
│   │   ├── review_domain.py                  (new) E2–E9 records
│   │   ├── review_repository.py              (new) SQL mixin for review tables
│   │   ├── review_service.py                 (new) decisions, undo, auto-park sweep, settings, state
│   │   ├── review_flow.py                    (new) runs, queues, capacity, bulk release (increment 3)
│   │   └── navigator.py                      (new) provider adapter, input/output validation
│   ├── services/account_service.py           # review/*.json export
│   ├── container.py                          # ReviewService, navigator provider
│   └── main.py                               # _run_review_maintenance_sweep
└── tests/
    ├── fixtures/review_formulation_vectors.json   (new, canonical)
    ├── fixtures/navigator/eval_v1.json            (new, synthetic SC-005 eval set)
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
│                            WhileYouWereAway.tsx, ReviewShell.tsx, steps/*.tsx,
│                            ReviewSettingsSection.tsx, navigatorInput.ts, __tests__/
├── pages/PrivacyPolicyPage.tsx                # retention/export wording
└── test/allureTaxonomy.ts                     # /features/review/ rule
frontend/tests/e2e/weekly-review.spec.ts (new); frontend/tests/allure.fixtures.ts (path rule)

ios/BrainBuddyKit/Sources/
├── BrainBuddyCore/   Records.swift, Commands.swift, Reducer*.swift, Replay.swift,
│                     Compaction.swift, Outbox.swift, Queries.swift,
│                     Formulation.swift (new), Queries+Review.swift (new),
│                     Review.swift (new: ReviewState, decisions, runs), Navigator.swift (new)
├── BrainBuddyPersistence/StoreDocumentCoding.swift
├── BrainBuddyAPI/    BrainBuddyAPIClient.swift, WireModels.swift, RequestBodies.swift,
│                     ReviewAPI.swift (new), NavigatorAPI.swift (new)
├── BrainBuddySync/   GTDCommand+Sync.swift, PushPlanner.swift, SyncEngine+Push.swift,
│                     SyncEngine+Pull.swift, StoreDocument+Merge.swift
├── BrainBuddyWorkspace/Workspace.swift
└── BrainBuddyFakeServer/  (review endpoints, StubNavigatorModel)
ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/  FormulationTests.swift, ReducerReviewTests.swift,
                     QueriesReviewTests.swift, NavigatorValidatorTests.swift (new),
                     Resources/review_formulation_vectors.json (new copy)
ios/BrainBuddyKit/Tests/BrainBuddySyncTests/  ReviewSyncTests.swift (new)
ios/BrainBuddyKit/Package.swift               # test resource for the vector copy
ios/BrainBuddy/
├── Screens/Review/ (new)  DecisionCardSheet, DecisionForms, WhileYouWereAwaySheet,
│                          RestartScreen, ReviewEntry, OnboardingScreen, steps…
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

### US1 — A stalled task asks for a decision (P1) — design M-01, M-02, M-03, M-04, M-23 (threshold row), D-01, D-02 (no navigator), D-04 (threshold)

**Backend**
- `formulation.py` implements `formulation_key`, `derive_instants`, `classify`,
  `close_formulation`, `start_formulation` exactly per
  [contracts/formulation-clock.md](contracts/formulation-clock.md). `TaskService`
  calls them inside `create_task`, `smart_add_task`, `update_task`, `transition_task`
  (FR-001 – FR-003, FR-003a). Notes, tags, project, priority, subtask and comment edits
  pass through untouched (FR-003).
- `ReviewService.decide` (`POST /tasks/{id}/decisions`, http §3) under
  `_serialized_write`: checks `expected_revision` and `formulation_id` (FR-011),
  applies the type table (FR-006, FR-008, FR-009), records the decision with stall
  reason code (FR-007), `ai_use` (FR-026), undo snapshot, and session counter when in a
  review (FR-010: same path in and out of a review).
- `ReviewService.undo_decision` (FR-011a), allowed while the task revision is unchanged.
- `TaskResponse.formulation` carries raw fields plus derived `ask_at` / `park_due_at` /
  `paused_until` and `consecutive_stalled` (FR-004, FR-005).
- Settings `PUT /review/settings` threshold change sets the owner park floor (FR-039).

**iOS** (`BrainBuddyCore` rules; app UI)
- Reducer maintains the clock for every existing command (contracts/ios-commands.md §3)
  and applies `decideTask` / `undoDecision`.
- M-01: `TaskRow` metadata shows only `asks` and `moves_tomorrow` chips (indigo
  `questionmark.circle` / amber `archivebox`, text + icon, 44 pt hit area); tapping opens
  M-03 as a `.large` detent sheet (FR-010a). States: default, loading (static rows after
  300 ms), empty first-run/filtered (existing copy), error (store unreadable, no Ref),
  offline ("Offline — 2 changes waiting"), threshold-changed note.
- M-02: "This wording" section in `TaskDetailScreen` with every M-02 state (asks,
  ageing/fresh, paused, moves-tomorrow with exact park time, kept 7 more days with the
  quoted reason, parked automatically, parked/project archived — see Inconsistencies).
- M-03/M-04: decision card + forms (reformulate with the cosmetic-edit note from
  `FormulationKey`, first step with "Was:" preview, Waiting for, keep 7 more days with
  required reason and computed date), stall-reason → recommendation mapping, third-stall
  offer (canvas link opens the existing Thinking entry only where it exists; on iOS
  there is no canvas, so the offer shows "Release to Someday" only — see
  Inconsistencies), stale (was/now), error with Ref, Undo toast ~5 s via
  `ToastCenter`.
- M-23: threshold picker (7/14/21/28) with the floor note (FR-039).

**Web**
- D-01: `TaskRow` gets a marker `Chip` button (accessible name "Asks for a decision.
  Open decision for <title>"); inline detail gets the "This wording" block (ageing only
  there). Classification uses server instants and the browser clock, re-evaluated every
  minute without refetch.
- D-02: `DecisionDialog` (560 px, focus on title, Esc closes with no change, keys 1–7,
  per-row "Saving…", stale heading "Task changed elsewhere", save-failed banner with
  Ref, offline disabled state), Undo toast via the extended `shellToast` (role="status",
  timer pauses on focus/hover, focus to next row).
- D-04: threshold control in a new `ReviewSettingsSection` on `/settings/account`.

### US2 — Auto-park and a shame-free return (P1) — design M-01/M-02 (moves tomorrow, parked), M-09, D-01, D-03 (M-09 content); restart mode M-10 ships with US4

**Backend**
- `ReviewService.run_auto_park_sweep(now)` from `_run_review_maintenance_sweep`
  (http §9): per activated owner with the flag effective, park tasks whose class is
  `park_due` with key `auto-park:<task>:<formulation>`; re-check under lock (FR-012,
  FR-013, FR-014); keep project, tags, notes, due date, priority.
- `POST /tasks/{id}/auto-park` for device-observed parks; `applied: false` is success
  (US2-6).
- Yield rule for earlier offline decisions (R9).
- Activation backfill and floors (FR-016, R4); rollback repair (formulation-clock §3).
- `GET /review/state.unseen_parks` + `POST /review/parks/acknowledge` (FR-015).
  Returning uses the existing `transition move → next`, which starts a new formulation
  (US2-4) and clears `parked`.

**iOS**
- `Workspace.applyDueAutoParks()` on load/foreground/pull/background refresh;
  account-less parks are final; signed-in parks are optimistic and never re-issued per
  formulation (contracts/ios-commands.md §5).
- M-09 sheet at app open when unseen parks exist: per-row "Return to Next", "Return all
  N", "Continue" (acknowledges). Partial failures: archived project (row disabled with
  reason) and changed elsewhere (named). Offline: works locally, shows again until
  Continue.

**Web**
- M-09 content as a dialog at app open (D-01 context) and as the first screen of
  `/review` (D-03); loading/error states per D-03 with Ref.

### US3 — The AI navigator proposes a first step (P2) — design M-04 ("Suggest"), M-05, M-06, M-07, M-08, M-19 (AI states), M-23 (Suggestions section), D-02 (navigator states), D-04 (cloud consent)

- Contract: [contracts/navigator.md](contracts/navigator.md) (input exactly FR-019,
  validator for FR-019/FR-021, `NavigatorModel` protocol, prompt v1).
- **Backend**: `navigator.py` adapter (`disabled`/`deterministic`/`openai`), consent
  table and endpoints, per-owner rate limit, per-call and daily cost caps, error reasons
  mapped to 400/429/503 with Ref (FR-024, FR-025, FR-045). No text persisted; one log
  line of codes/counts.
- **iOS**: `NavigatorRouter` chooses Apple on-device when `available` for the task's
  language (FR-022), else M-06 choice (FR-023) with the remembered preference (M-23);
  cloud path requires consent (M-07) and an account ("Cloud suggestions need a Brain
  Buddy account" state); proposals fill the field, the task changes only on Save
  (FR-020); clarifying question appends the answer to notes via a normal `updateTask`
  (no clock change) and re-runs (FR-021); "Stop" cancels the `Task`.
  M-08: project without a next action uses `kind: project_next_action`; confirm creates
  the task in Next in that project (`createTask`).
- **Language routing**: Apple's model does not support Russian on iOS 26.x or 27
  (`research-on-device-model.md` §1), so the router classifies the task text with
  `NLLanguageRecognizer` first and goes straight to the M-06 choice for unsupported
  languages; `unsupportedLanguageOrLocale` thrown at `respond` is the backstop. Input
  budget: Apple's window is 4,096 tokens on iOS 26.x; notes are truncated oldest-first
  with a visible note (research NC-3 default; contracts/navigator.md §1).
- **Downloadable model** (FR-023 (a), FR-023a): slice PR-09, behind the same protocol;
  recommended Core AI + Qwen3-1.7B 4-bit in an Apple-hosted Background Assets pack,
  iOS/macOS 27+ with a memory check and the `increased-memory-limit` entitlement
  (`ios/project.yml`), free-space check declared in `ios/Shared/PrivacyInfo.xcprivacy`;
  needs a dependency-exception ADR and the owner's answer to NC-2. M-06 download states
  (progress, interrupted, storage, installed) and M-23 delete-with-confirmation are built
  in PR-09. Apple Private Cloud Compute is not built (NC-4 default: it would count as a
  cloud provider).
- **Web**: D-02 navigator states (consent dialog focusing "Not now", proposals radio
  group, timeout/cost cap/malformed banners with Ref); D-04 cloud consent switch naming
  the provider; revoke takes effect at once in the tab.

### US4 — The guided weekly review (P2) — design M-10, M-11, M-13 – M-22, D-03

- **Backend** `review_flow.py` + `api/review_flow.py`: start/resume/progress/finish
  runs (FR-027, FR-029, data-model E3 transitions), queues per step with server-side
  snapshot of the decision queue (edge case "threshold changed during an open review"),
  wins (FR-028), capacity mirror (FR-031), Waiting > 7 days and Someday ≤ 7 not reviewed
  in 30 days with receipts (FR-032), projects without a next action, dates in 14 days,
  summary counts and "clear start" (FR-033), bulk release with partial results and undo
  for restart (FR-017) and Inbox remainder (FR-030), regularity instant for restart mode.
- **iOS**: review cover with shared step chrome (Leave/Skip at top, primary action at
  bottom, "N of M"), each step's states as designed; decision step reuses M-03
  full-screen with "Not now" (FR-034a) and Undo status line; Inbox step reuses
  `ProcessInboxScreen` item view; one item at a time in steps 3, 4, 6, 8 (FR-034).
  Offline: everything local via outbox; cross-device resume after sync (M-11 offline).
- **Web**: `/review` route (`ReviewShell`, 240 px non-focusable rail, 600 px column,
  focus to step heading on change, Esc never closes the review), same steps; offline per
  D-03.

### US5 — Schedule, cue, onboarding and settings (P3) — design M-11 (Lists row), M-12, M-23, M-24, M-25, D-01 (sidebar recap), D-03 (onboarding dialog), D-04

- **Backend**: settings fields and `next_review_at`/`last_counted_review_at` in
  `GET /review/state` (FR-035, FR-038); time zone follows the client (US5-5).
- **iOS**: onboarding once (M-12) then notification permission prompt; one weekly local
  notification, skipped per FR-036 (R17); widget "N ask" chip with deep link in
  medium/large, display-only in small (FR-037); neutral "Last review: N days ago", no
  streak anywhere (FR-038); Lists row replaces `DeferredRow` when exposed (FR-042).
- **Web**: sidebar link replaces the disabled entry when the flag is on, with the
  "Last review" line (FR-036 web has no notification, FR-042); onboarding dialog.

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
| Decision made offline before a server park | server reverses the park and applies the decision (yield rule) | R9 |
| Two devices park the same formulation | one park; the other gets `applied: false` (200) | http §4 |
| Device clock ahead of server | device park is optimistic; server returns `applied: false`; not re-issued | R9 |
| Idempotent replay / lost write after record | existing `_reconcile_idempotent_result` with new prefixes | R7 |
| Undo after another change | 409 `undo_unavailable`; toast copy says the task changed | R8 |
| Bulk release with stale items | 200 with `skipped`; M-10/M-15 partial-failure copy | http §6 |
| Sweep fails for one owner | logged with owner id and code; other owners and other sweeps continue | http §9 |
| Cloud timeout / provider error / malformed / cost cap / rate limit / consent missing / flag off | 503 / 503 / 503 / 429 / 429 / 400 / 404 with reasons; card stays usable | http §7 |
| On-device model becomes unavailable mid-session | `unavailable(reason)` → M-06 | navigator §4 |
| App killed mid-form or mid-review | form discarded; review progress persisted per decision/progress command | design M-04, M-13 |
| Old client saves a task (drops clock) | sweep restarts the clock with a 14-day floor | formulation-clock §3 |

## Migration, deploy order and rollback

- **Backend schema**: new tables are `CREATE TABLE IF NOT EXISTS` in
  `_initialize_database` plus a `migration_ledger` row `review-v1`; task fields live in
  the JSON payload. Additive and safe to run alongside the old code. No data is rewritten
  at deploy; activation backfill is per owner and only adds fields.
- **Deploy order**: backend (flag OFF) → iOS and web builds that understand the fields →
  flag `weekly_review` SELECTED_USERS (owner) → ON. Clients tolerate the backend
  without the feature (flag absent → old UI).
- **Rollback**: turn the flag OFF (immediate: routes 404, sweep inert, clients show
  "coming later"). Code rollback is safe: old code ignores the tables and the payload
  fields; on roll-forward the sweep repairs clocks dropped by old-code saves with a
  14-day floor, so no early park can result. Nothing is irreversible except an auto-park
  that already happened, which the person can undo in one tap (M-09).
- **iOS store**: v1 → v2 migration is additive; a downgraded app reports
  `.unsupportedVersion` and asks to update (existing behaviour).

## Observability

- Correlation: existing middleware; clients send `X-Correlation-ID` (iOS already does)
  and show `Ref` from `ApiError.correlationId` / `APIError.referenceID` on every
  failure state named in design.
- Logs (ids/codes/counts/timings only): `review_decision`, `review_undo`,
  `review_auto_park` (`applied`, `source=sweep|device`, `yielded`), `review_sweep`,
  `review_settings_changed` (threshold old/new), `review_run` (mode, status, counts),
  `navigator` (outcome, provider, kind, tokens, proposals count). A pytest log-capture
  test proves sentinel content never appears (FR-044).
- Supporting metrics (intake §3) are computed from stored codes and counts:
  decision/stall-reason distribution, re-stall rate (consecutive count), parks returned,
  due-date moves on Next tasks (counter on `update_task` when `due_date` changes in
  Next), median formulation age.

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
| pytest — pure rule | `test_review_formulation.py`, `test_review_formulation_vectors.py` | every vector; boundaries ±1 s; DST; floors; extension at T/T+3/T+6; third stall; copies byte-identical |
| pytest — service/API | `test_review_decisions_api.py` | each decision type; stale revision; stale formulation; idempotent replay and mismatch; first-step "Was:"; extension once; follow-up in archived project; undo exact restore incl. clock; undo after change → 409; owner isolation → 404; flag off → 404; FR-003 non-restarting edits through PATCH |
| pytest — sweep | `test_review_auto_park.py` | due/not due; 24 h marker precedes park (SC-006); FR-016 floor at activation; FR-039 floor; FR-003a floor; skip after reformulate/move/extend; double park no-op; device park with server not due → `applied:false`; yield rule both sides of `parked.at`; archived project; sweep failure isolation; driven by calling `_run_review_maintenance_sweep(container)` directly |
| pytest — privacy | `test_review_export_purge.py`, log-capture test | every new table exported/excluded per data-model; purge removes all; purge idempotent; no sentinel text in logs |
| pytest — navigator | `test_review_navigator.py` | strict input schema rejects extra fields; consent missing/revoked/mismatch; rate limit; per-call and daily cap; timeout; malformed; duplicate filtering; grounding filter; deterministic provider in TEST; startup failure without key |
| pytest — flow | `test_review_flow_api.py` | quick/full steps; partial vs abandoned; resume; replace open; queue snapshot stable after threshold change; capacity numbers (41 / 9 per week); receipts 7/30 days and revision invalidation; bulk release partial + undo; restart eligibility at 21 days incl. onboarded-never-reviewed |
| Swift Testing (Linux) | `FormulationTests`, `ReducerReviewTests`, `QueriesReviewTests`, `NavigatorValidatorTests`, `ReviewSyncTests` | shared vectors; reducer clock on every command; replay determinism; compaction of decision+undo; 409 refetch path; `applied:false` no re-issue loop; StoreDocument v1→v2; account-less parks; offline review synced with 0 lost decisions (SC-007) via `BrainBuddyFakeServer` |
| Xcode (`ios-app` lane) | app/widget targets compile; previews per design state | AppleNavigatorModel behind `#if canImport(FoundationModels)`; widget families |
| Vitest | `features/review/__tests__/*` | `formulation.ts` vectors; markers only asks/tomorrow in lists; D-02 focus/Esc/keys/stale/save-failed/Ref; Undo toast; WYWA partial failures; settings floor note; AppShell flag-off keeps "Weekly review — Coming soon" (existing test unchanged), flag-on link + "Last review" |
| Playwright | `frontend/tests/e2e/weekly-review.spec.ts` | seeded stalled task → decide → Undo; auto-park via sweep endpoint in test env → WYWA → return; quick review end-to-end; consent decline path with deterministic provider |

Requirement coverage: once PR-01 extends the scanner to Swift test trees, every FR/SC
is named by at least one test; lettered ids are named but not gate-enforced (research
R19). Live provider evaluation (SC-005) is approval-gated and never runs unattended.

## Delivery slices

Proposed PR-sized slices; they become `## PR-срезы` at `/speckit-tasks` and need the
owner's approval there. Classes per ADR-0008 / `scripts/classify_path_risk.py`
("mech." = the classifier result; final class = the stricter of mechanical and semantic).

| id | increment | outcome | depends on | main paths | class |
|---|---|---|---|---|---|
| PR-01 | 1 | ADR-0027 accepted; design skill reworded to "flag-gated, deferred while off" with its test; Swift test trees in requirement coverage; architecture-guard docstring | — | `docs/decisions/0027-…md`, `.claude/skills/brain-buddy-design/{README.md,SKILL.md}`, `scripts/test_validate_brain_buddy_design_skill.py`, `scripts/check_requirement_coverage.py`, `.specify/gate-integrity.json`, `backend/tests/test_voice_workflow_architecture.py` | **ASK** (mech.: `scripts/`, guarded files) |
| PR-02 | 1 | Backend clock, decisions, undo, auto-park sweep and device endpoint, settings/state, park acks, all review tables, export/purge, flag | PR-01 | `backend/app/modules/tasks/*`, `backend/app/api/{review.py,tasks.py,dependencies.py,__init__.py}`, `backend/app/schemas/{tasks.py,review.py}`, `backend/app/core/config.py`, `backend/app/repositories/feature_flag.py`, `backend/app/services/account_service.py`, `backend/app/container.py`, `backend/app/main.py`, `docs/data-retention.md`, `frontend/src/pages/PrivacyPolicyPage.tsx`, backend tests | **ASK** (mech.: `api/tasks.py`, `api/dependencies.py`; sem.: privacy export/purge, first automatic state change) |
| PR-03 | 1 | iOS core: records, clock in reducer, new commands, queries, StoreDocument v2, API/sync mapping, fake server, vectors | PR-02 | `ios/BrainBuddyKit/**` | SHOW (mech. SHIP; persistence format change) |
| PR-04 | 1 | iOS UI for US1/US2: M-01, M-02, M-03, M-04 (no Suggest), M-09, M-23 threshold | PR-03 | `ios/BrainBuddy/Screens/{Lists,Detail,Settings,Review}/*`, `ios/BrainBuddy/Components/*`, `ios/BrainBuddy/App/*`, `ios/project.yml` | SHOW |
| PR-05 | 1 | Web US1/US2: D-01 markers, inline "This wording", D-02 without navigator, WYWA, D-04 threshold, action toast | PR-02 | `frontend/src/features/{tasks,review,account}/*`, `frontend/src/api/{review.ts,reviewHooks.ts,taskTypes.ts}`, `frontend/src/components/shell/shellToast.ts`, `frontend/src/test/allureTaxonomy.ts` | SHOW |
| PR-06 | 1 | Mac "Weekly review · coming later" row | — | `macos/Sources/BrainBuddyMac/ContentView.swift`, `macos/Tests/BrainBuddyMacTests/*` | SHIP |
| PR-07 | 2 | Backend navigator: adapter, consent, usage caps, routes, env | PR-02 | `backend/app/modules/tasks/navigator.py`, `backend/app/api/review_navigator.py`, `backend/app/core/{config.py,rate_limit.py}`, `backend/app/container.py`, `.env.example`, tests | **ASK** (mech.: `.env.example`; sem.: provider credentials, new egress, consent) |
| PR-08 | 2 | iOS navigator: protocol, router, validator, Apple model, cloud client, M-05, M-06 (cloud choice), M-07, M-08, M-19 AI states, M-23 Suggestions | PR-04, PR-07 | `ios/BrainBuddyKit/Sources/BrainBuddyCore/Navigator.swift`, `…/BrainBuddyAPI/NavigatorAPI.swift`, `ios/BrainBuddy/Navigator/*`, `ios/BrainBuddy/Screens/Review/*` | SHOW |
| PR-09 | 2 (late; may slip) | Downloadable on-device model: dependency-exception ADR, Core AI runtime + model pack, M-06 download states, M-23 delete (FR-023 (a), FR-023a); SC-005 eval gate | PR-08, NC-2 | `ios/BrainBuddy/Navigator/DownloadedNavigatorModel.swift` (new), `ios/project.yml`, `ios/Shared/PrivacyInfo.xcprivacy`, `docs/decisions/` (new ADR), `backend/tests/fixtures/navigator/eval_v1.json` | **ASK** (third-party dependency exception, external model download, new entitlement) |
| PR-10 | 2 | Web navigator in D-02; D-04 consent switch | PR-05, PR-07 | `frontend/src/features/review/*`, `frontend/src/api/review.ts` | SHOW |
| PR-11 | 3 | Backend review flow: runs, queues, capacity, receipts, bulk release, restart, regularity, next review | PR-07 | `backend/app/modules/tasks/review_flow.py`, `backend/app/api/review_flow.py`, `backend/app/api/__init__.py`, tests | SHOW |
| PR-12 | 3 | iOS review: M-10, M-11, M-12, M-13 – M-22, M-23 schedule, M-24 widget, M-25 notification, Lists entry | PR-08, PR-11 | `ios/BrainBuddy/Screens/{Review,Browse,Settings}/*`, `ios/BrainBuddy/Review/*`, `ios/BrainBuddyWidgets/*`, `ios/BrainBuddy/App/*`, `docs/native-ios-app.md` | SHOW |
| PR-13 | 3 | Web review: D-03 shell and steps, onboarding dialog, sidebar link + "Last review", D-04 schedule; e2e | PR-10, PR-11 | `frontend/src/features/review/*`, `frontend/src/app/AppRoutes.tsx`, `frontend/src/components/shell/AppShell.tsx`, `frontend/tests/e2e/weekly-review.spec.ts`, `frontend/tests/allure.fixtures.ts` | SHOW |
| PR-14 | 3 | Release: requirement coverage for 020 in `check-specs`; rollout evidence; flag stages | PR-12, PR-13 | `Makefile`, `.specify/gate-integrity.json`, `specs/020-weekly-review/evidence/*` | **ASK** (mech.: `Makefile`) |
| (US6) | 4 | Mac review after Mac↔backend sync | Mac sync spec | planned when that spec exists | — |

Write-path notes: slices with no dependency between them do not share write paths
(PR-06 is disjoint from all; PR-05 and PR-03/PR-04 are disjoint; PR-07 → PR-11 is
sequenced because both mount routers in `backend/app/api/__init__.py` and extend
`container.py`). Increment boundaries match the owner's increments: (1) rule + card +
auto-park + markers on backend, iOS, web; (2) navigator; (3) full guided review +
schedule/notification/onboarding; (4) macOS after Mac sync.

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

## Inconsistencies found while planning (spec/design not edited)

1. **Archived-project states are unreachable today.** Archiving a project clears
   `project_id` on its tasks on the backend (`service.py:989-1012`) and on iOS
   (`Reducer+Organize.swift:58-70`); ADR-0020's lossless archive is accepted but not
   implemented. So the spec edge case "Task in an archived project", M-02 "parked,
   project archived", M-09 "partial failure: archived project" and M-18 "archived project"
   cannot occur until spec 011's archive change lands. The plan implements the guard
   (`project_archived` reason) defensively and tests it with a fixture, nothing more.
2. **Extension arithmetic** FR-009/FR-012 vs US1-7 and M-02 (NC-1). Also M-04 "Keep until
   Thu 15 Oct" with today Fri 9 Oct is 6 days, matching neither reading.
3. **Lettered requirement ids** (FR-003a, FR-010a, FR-011a, FR-023a, FR-034a) are not
   recognised by `scripts/check_requirement_coverage.py:44` or the PR-срезы validator in
   `scripts/check_spec_kit_specs.py:165-166, 212-214`; they cannot be gate-enforced or
   listed in a slice manifest (R19).
4. **D-11 attribution**: spec Assumptions and intake cite "ADR-0006 (… D-11)"; D-11 is in
   `docs/vnext-cloud-design-build-contract.md:757`, not ADR-0006.
5. **Third-stall "Think it through" on iOS**: FR-005/M-03 offer the thinking canvas, but
   the iOS app has no CRT canvas (CRT is web-only, `/crt`, flag `crt_canvas`). Plan: on
   iOS the offer shows only "Release to Someday" plus the reassurance copy; on web it links
   to `/crt` when `crt_canvas` is effective. Owner may want different copy.
6. **"Process inbox Undo" on web**: design D-03/M-15 assume the existing Process inbox
   and its Undo; the web has neither (`frontend/src` has no Process-inbox flow and a
   text-only toast). The web Inbox step is new UI (PR-13), not reuse.
7. **ADR-0002 status**: the spec calls ADR-0002 binding; its header says
   `Status: Proposed`. No impact here (voice review is out of scope).

## Constitution Check (post-design)

- Spec workflow — PASS (NC-1 – NC-4 recorded with defaults; inconsistencies listed for
  the owner; no spec/design edits by this stage).
- Consent & Safety — PASS: strict navigator input, per-request consent re-check,
  no silent fallback, content-free logs with a test, export + purge of every new record,
  undo snapshots time-limited.
- Tests — PASS: failing-first tests per slice; edge cases for idempotency, stale,
  timeouts, consent denial, partial failure, offline replay.
- Contracts — PASS: four contract files agree with `data-model.md` (E-numbers referenced
  from http and ios contracts); additive changes; backend before clients.
- Observability — PASS: Ref on every failure; reason codes; sweep and decision logs.
- Mobile/resilience — PASS: offline outbox for all task/review commands; yield rule;
  idempotent parks; resumable review.
- Delivery boundary — PASS: slices with classes; ASK slices named; owner approves the
  slice map at `/speckit-tasks`.
- Design citation — PASS: every user story section cites its M-/D- ids.

Delivery risk: **HIGH / ASK** remains for the feature (PR-01, PR-02, PR-07, PR-09, PR-14).

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Review records stored in the Tasks module's SQLite file instead of ADR-0001's separate Review module | atomic decision + task write, exact Undo, one idempotency record per decision | separate store needs a saga for every decision and a second export/purge path (R1); recorded by ADR-0027 |
| Clock rule implemented three times (Python, Swift, TS key only) | iOS must work offline/account-less; web shows the cosmetic-edit note | server-only rule cannot serve offline iOS; mitigated by one byte-identical vector file with a drift test (R3) |
| Possible first third-party iOS dependency (PR-09) | FR-023 (a) downloadable on-device model; Apple's model has no Russian | isolated behind `NavigatorModel`, app target only, gated by NC-2, a dependency-exception ADR and its own ASK slice; Core AI's raw framework without the package would need a hand-written tokenizer/decoder (`research-on-device-model.md` §2) |
