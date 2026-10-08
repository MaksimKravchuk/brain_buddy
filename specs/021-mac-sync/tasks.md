---

description: "Task list for 021 Mac ↔ backend sync"
---

# Tasks: Mac ↔ backend sync

<!--
  BrainBuddy override: delivery gates. Upstream treats tasks.md as an
  execution script; here it is portable planning input that never bypasses
  isolated worktrees, tests-before-implementation, independent acceptance,
  ADR-0008 landing classification, or CI. Those gates are restated below and
  must survive any upstream refresh.
-->

**Input**: Design documents from `/specs/021-mac-sync/`: [intake.md](intake.md), [spec.md](spec.md), [design.md](design.md), [plan.md](plan.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md), [review-c1-disposition.md](review-c1-disposition.md), [review-c2-disposition.md](review-c2-disposition.md), [planning-review.json](planning-review.json), [checklists/](checklists/)

**Prerequisites**: plan.md (required), spec.md (required for user stories), design.md (required when the feature has a user-visible surface), research.md, data-model.md, contracts/

**Delivery gates** (non-negotiable, regardless of who executes these tasks):
isolated worktree and feature branch; failing test written and observed failing
before the implementation that satisfies it; Allure taxonomy on every product
test with the covering feature-qualified id (`NNN-FR-###`/`NNN-SC-###`) in
the test name or story; acceptance
graded by an agent that did not write the code; landing class decided by
`scripts/classify_path_risk.py`, with SHIP and SHOW landing PR-less through
verified trunk and ASK-class changes never landing automatically — a PR carries
their review evidence, but merging it does not by itself update `main` (ADR-0008;
ADR-0008; see `AGENTS.md` and `docs/autonomous-delivery-runbook.md` for the recorded
approval and ruleset requirements).

Before freeze, the implementation writer MUST produce a typed receipt using
`.specify/templates/pre-freeze-receipt.schema.json` and run
`python3 scripts/validate_pre_freeze_receipt.py <receipt> --sha <full-lowercase-sha>`.
<!-- BrainBuddy pre-freeze receipt contract: tasks. Preserve this section. -->
The receipt covers only writer-owned pre-freeze gates. Independent review, QA,
CI, landing, deploy, and production smoke remain post-freeze obligations under
ADR-0008 and must never be represented as writer PASS evidence.

**Tests**: Tests are expected for behavior changes; include backend pytest/FastAPI
TestClient, frontend Vitest/Testing Library, operation-state, or deterministic
repository checks unless the spec explicitly waives tests for a docs/tooling-only
change. For this feature tests are **required** (constitution II, plan "Test
strategy"): every "Write and observe RED" task comes before the task that makes it
GREEN, and the failure is observed, not assumed. Product tests carry the
feature-qualified id: `021-FR-012` / `021-SC-001` in Vitest, Playwright and Swift test
names (`@Test("021-FR-012 …")`), `test_021_FR_024_…` in Python. pytest, Vitest and
Playwright tests carry the Allure taxonomy (`epic`, `feature`, `story`, a readable title,
at least one named step) through the central defaults in `backend/tests/allure_taxonomy.py`,
`frontend/src/test/allureTaxonomy.ts` and `frontend/tests/allure.fixtures.ts`; Swift tests
carry the ids but emit no Allure results (`ios/README.md` "Known gaps"). A subset pytest
run uses `--no-cov` (the repository-wide coverage floor in `addopts` fails any subset);
`make test-backend` runs the floor and the taxonomy validator before anything is reported
green. Evidence comes only from seeded synthetic accounts with the design's example data.

**Runtime of each Swift task** (plan "Automated and host-evidence lanes"): *(Linux)* runs in
`sh ios/scripts/swift-linux.sh test`; *(macOS lane)* compiles and runs only on the
`macos-app` / `ios-app` CI lanes or on a Mac, so red-then-green is observed there, not in a
Linux worktree; *(host)* needs a person on real hardware (the owner, Max) and records
evidence under `specs/021-mac-sync/evidence/` by the plan's "Evidence protocol".

**Organization**: Tasks are grouped by PR slice in dependency order, because the plan's
slices cut across stories (the backend contract serves US5 and the attribution of US3; the
kit contract serves US1 – US5). Each phase names its story focus and every task carries the
story it serves. Include consent enforcement, mobile/resilience handling, observability
(correlation IDs, actionable errors/progress), release/smoke validation, and data-safety
safeguards where relevant.

**Multiple PRs for one spec (opt-in)**: After `spec.md` and `plan.md` are
approved, and before implementation, propose PR-sized slices and obtain the
human's agreement on boundaries. Add a `## PR-срезы` section to this very
`tasks.md` containing one fenced `json` block with `schema_version` set to
`brainbuddy-pr-slices/v1` and at least two ordered `slices`. Each slice has a
unique `id` (`PR-01`, `PR-02`), a reviewable `outcome`, nonempty `tasks`
(`T001`), `requirements` (`NNN-FR-001` or `NNN-SC-001`), repository-relative
write `paths`, runnable `tests`, `acceptance` evidence, and `depends_on`
(previous slice ids, or `[]`). Assign every checklist task **exactly once**;
shared setup and polish tasks also need an owner. Do not split into a backend
PR followed by a frontend PR unless the first has an independently testable
contract. Do not claim the same write path in independent parallel slices.
`python3 scripts/check_spec_kit_specs.py` validates the section; approve it
before an implementation worker begins. It is a delivery boundary, not
authorization to merge or deploy.

A slice must stand on its own as a reviewable contract (or safely disabled
scaffold). Preserve one feature's spec/plan/tasks as the product contract;
record slice outcomes and exact test evidence in each PR, then run the full
feature acceptance after all dependent slices integrate.

**PR slice map status**: **draft, awaiting the owner's approval of the file-level map.**
The slice boundaries, classes and order are the plan's (PR-01 – PR-10, "Delivery slices",
founder-accepted with the planning review on 2026-10-06). The `## PR-срезы` manifest at the
end of this file turns them into file-level write paths; no implementation worker starts
until the owner approves it. Approval is a delivery boundary, not an authorization to merge
or deploy.

**Cross-feature fields in the manifest**: `depends_on` may name only slices of this
manifest (`scripts/check_spec_kit_specs.py`), so each slice also carries
`external_depends_on` (020 slices that must have landed first, plan "Delivery slices") and
`serialize_with` (020 slices that write a path this slice writes, or share its kit or web
surface, plan "Parallelism with 020's waves"; either order, the second rebases). The validator ignores both fields; they are
for the implementer and the landing reviewer. State on 2026-10-06: 020 PR-01 (`54a7169`) and
020 PR-02 (`afaa820`) have landed on `main`, so 021 PR-02's and PR-10's external
dependencies hold; 020 PR-06 has not, so PR-08 waits for it.

**Deviations from the plan's file lists** (each keeps the plan's rules; none changes a
contract):

- PR-04 also writes `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/TestSupport/CoreFixtures.swift`,
  the Core property-test command generator (it builds every `GTDCommand` case by hand, like
  `Support/RandomCommands.swift`), so `CompactionPropertyTests` exercise the new
  `setProjectOutcome` fold. It is not an exhaustive switch, so the enum-case rule does not
  require it; plan.md's PR-04 row lists it (56 paths, still SHIP).
- PR-08's `serialize_with` also names 020 PR-03, which the plan's "Parallelism with 020's
  waves" row for PR-08 omits: both write `ios/BrainBuddyKit/Package.swift` (T104 declares the
  `BrainBuddyWorkspaceTests` resources). Found by comparing the two manifests at the targeted
  review; either order, the second rebases.
- Line references into `backend/app/modules/tasks/service.py` predate 020 PR-02, which moved
  them by about 11 lines on `main`; tasks name the symbol (`archive_project`,
  `update_task`, …), not the line.
- The plan's interim rule for Swift requirement evidence ("before 020 PR-01 lands") no
  longer applies to slices built from `main`: its `scripts/check_requirement_coverage.py`
  scans `ios/BrainBuddyKit/Tests` and `macos/Tests` and takes `--requirements`. The iPhone
  app target has no test target, so PR-07's ids are proven by the kit tests of PR-04 and
  PR-05 plus its host evidence.

**`/speckit-checklist` and `/speckit-analyze` remediation** (2026-10-06): the fixes those two
stages made in the planning artifacts are already reflected in the tasks above. They are
listed for the targeted review (founder-acceptance measure 6) in the three checklists'
"Notes" and in the run report. Here they are T096, T102, T103 and T119 (the dry run skips
the cookie and the Keychain cleanup and makes no Keychain call; the Keychain part corrected
at the targeted review), T117 (the guard's allow-list), T069, T082 and T106 (the rename error), T052 and
T126 (the undated backup sentence), T029 (`CoreFixtures.swift`) and the per-story index below.

## Tasks by user story

The phases below follow the slices; this index groups the same tasks by user story
(constitution "Tasks MUST be grouped by independently shippable user story"; found by
`/speckit-analyze`), with each story's independent test and the slices that complete it.
Setup and polish (T001 – T005, T134 – T139) carry no story. T066 – T089, T134, T135 and T138 are deferred (Notes, 2026-10-07).

| story | tasks | complete after | independent test |
|---|---|---|---|
| US1 (P1) sign in and stay in sync | T027, T036 – T037, T041, T056 – T057, T059, T062, T064 – T065, T068, T073, T086, T095, T101, T118 – T120, T125 – T132 | PR-09 (kit logic from PR-05; web refetch PR-06; iPhone cadence PR-07) | quickstart Scenario 4 steps 2 and 9 (kit); a Mac and an iPhone or web on one account converge within 60 s (host) |
| US2 (P1) offline, nothing lost | T060, T105, T107, T109, T121 | PR-09 (offline matrix in the kit from PR-05; Mac offline journeys in PR-08) | quickstart Scenario 4 step 3 (SC-002); offline journeys in `OfflineWorkspaceTests` |
| US3 (P2) compact status, errors only when wrong | T009, T017, T030, T052 – T055, T061, T080 – T081, T083, T085, T087 – T089, T115 – T117, T122 – T124, T133 | PR-07 (iPhone), PR-09 (Mac) | quickstart Scenario 5 |
| US4 (P2) upgrade without losing anything | T025, T038 – T039, T042, T048, T058, T063, T090 – T094, T096 – T100, T102 – T104, T110 – T114 | PR-08 (upgrade, account-less), PR-09 (first sign-in) | quickstart Scenario 6 |
| US5 (P3) lossless archive and unarchive | T006 – T008, T010 – T016, T018 – T024, T026, T028 – T029, T031 – T035, T040, T043 – T047, T049 – T051, T066 – T067, T069 – T072, T074 – T079, T082, T084, T106, T108 | PR-03 (server), PR-06 (web), PR-07 (iPhone), PR-08 (Mac) | quickstart Scenarios 1, 2 and 7 |

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Web app**: `backend/app/`, `backend/tests/`, `frontend/src/`, `frontend/tests/`
- **Shared kit**: `ios/BrainBuddyKit/` (Linux-testable package; Core, Persistence, API, Sync, Workspace, FakeServer)
- **iPhone app**: `ios/BrainBuddy/` (no test target)
- **macOS**: `macos/Sources/BrainBuddyMac/`, `macos/Tests/BrainBuddyMacTests/`

---

## Phase 1: Setup — macOS CI lane and report tooling (slice PR-01, ASK)

**Purpose**: Every later Mac slice is compiled and tested in CI on the exact SHA (research R3); the feature report counts `X-` screens (design gap G-7).

- [ ] T001 Write and observe RED in `scripts/test_validate_ci_artifacts.py`: workflow fixtures where `macos-app` is missing, carries a job-level `if`, needs anything other than `changes`, is absent from the `full-ci` or `allure-report` `needs`, or where the `changes` job has no `macos` output, are each rejected; the complete fixture passes. *(tooling: enables the macOS-lane evidence for 021-FR-005 and 021-SC-004; no product behaviour)*
- [ ] T002 Make T001 GREEN in `scripts/validate_ci_artifacts.py`: `LANE_DEPENDENCY_LIMITS["macos-app"] = {"changes"}`, `macos-app` in the path-filter job list, and in the `full-ci` / `allure-report` completeness checks (research R3).
- [ ] T003 Add the lane to `.github/workflows/ci.yml`: a `macos` output on `changes` that is true for `^macos/`, `^ios/BrainBuddyKit/` and the shared surfaces, and always on the landing path (mirroring `ios`); the job `macos-app` "Mac app on macOS (Xcode 26)" with `needs: changes`, `runs-on: ${{ needs.changes.outputs.macos == 'true' && 'macos-26' || 'ubuntu-latest' }}`, every step gated `if: env.RUN == 'true'` (never a job-level `if`), `bash ios/scripts/select-xcode.sh`, `swift build` and `swift test --parallel` in `macos/`, no `build_app.sh`, build logs uploaded on failure; `macos-app` added to `full-ci` and `allure-report` `needs`. `make validate-ci` passes; the lane runs today's 71 XCTest cases green.
- [ ] T004 [P] Write and observe RED in `scripts/test_render_feature_report.py`: a `design.md` naming `X-01`, `X-09`, `M-01` and `D-01` yields four screen ids (G-7). *(tooling: no 021 requirement; design gap G-7)*
- [ ] T005 Make T004 GREEN in `scripts/render_feature_report.py`: `SCREEN_ID_RE = re.compile(r"\b([DMX]-\d{2})\b")`.

**Checkpoint**: every Mac change from here on is built and tested on the exact SHA.

---

## Phase 2: Backend tolerant contract — US5 server side, client attribution (slice PR-02, ASK) 🎯 first product slice

**Goal**: The server accepts carried archived memberships, lists archived projects, unarchives, stores a desired outcome, marks pre-feature archives, and attributes requests by client, while archive still clears memberships (rollback-safe first step, research R9).

**Independent Test**: quickstart Scenarios 1 (steps 2 – 8, 10 – 12 with PR-02 behaviour), 2 and 3 against `api_client` / `second_api_client`.

- [x] T006 [US5] Add Allure taxonomy rules for the new modules to `backend/tests/allure_taxonomy.py`: epic "Tasks", feature "Projects", story "Lossless archive" for `test_project_archive_lossless_api.py` and `test_project_archive_traces.py`, "Desired outcome" for `test_project_desired_outcome_api.py`, "Client attribution" for `test_client_attribution_logging.py` (plan "Test strategy"), so no later slice edits this file.
- [x] T007 [US5] Write and observe RED `backend/tests/test_project_archive_lossless_api.py` with the PR-02 behaviour: the tolerant PATCH table (omit while the current project is archived → 200; the same archived project → 200; a different archived project → 400 "Task project must be active."; `null` → 200; an active project → 200); create and Smart Add into an archived project → 400; `GET /projects` default returns the same projects in the same order as before with `desired_outcome`, `archived_at`, `archived_before_lossless` on each, `?state=active|archived|all`, `?state=bogus` → 422; `test_021_FR_026_list_projects_state_is_owner_scoped` (a second owner's projects never appear; an owner with none gets 200 `[]`); unarchive 200 (`state: active`, `archived_at: null`, revision + 1, marker unchanged, no task change) / already active → 200 unchanged even with a stale `expected_revision` (checked before the revision, http.md §3) / 409 stale / 409 active name clash with the duplicate-name body / 404 foreign via `second_api_client` / replay with the same key → stored response / missing `Idempotency-Key` → 400 / 422 body; archive under PR-02 still clears every member's `project_id` and sets `archived_before_lossless: true` (cases marked for replacement in PR-03); a repeat archive changes only `revision` and `updated_at`; `_mark_detached_archives` marks only archives without `archived_at`, with no revision bump, idempotently; the marker survives unarchive; `open_task_count` of an archived project; list counts equal the per-project counts with one task load per list request. *(021-FR-025, 021-FR-026, 021-FR-027)*
- [x] T008 [P] [US5] Write and observe RED `backend/tests/test_project_desired_outcome_api.py`: create with an outcome → 201; PATCH omitted keeps, `null` clears, blank → `null`, 1,000 characters kept, 1,001 → 422; a PATCH changing only the outcome bumps `revision`; a rename without the field keeps it (US5-5); log capture across create, PATCH, archive, unarchive and export with sentinel project names and outcomes: no sentinel in any record. *(021-FR-028, 021-FR-030)*
- [x] T009 [P] [US3] Write and observe RED `backend/tests/test_client_attribution_logging.py`: `X-Client: brainbuddy-macos/0.1.0`, `brainbuddy-ios/1.4`, absent and `evil\nvalue` give `client=macos client_version=0.1.0`, `client=ios client_version=1.4`, `client=web client_version=-`, `client=other client_version=-` on `api_request` and `api_request_failed`; the raw bad value is never logged; responses are identical; `X-Correlation-ID: abc\nforged=1` gives a fresh UUID in the response and no `forged` in any log line; a lower-cased UUID is echoed unchanged. *(021-FR-031, 021-FR-015, 021-FR-030)*
- [x] T010 [P] [US5] Write the canonical golden traces `backend/tests/fixtures/project_archive_traces.json` (PR-02 behaviour; contracts/kit-commands.md §7): archive (clearing plus marker), repeat archive including a seeded pre-feature archive (marker stays true, `archived_at` stays null), unarchive 200 / active no-op / stale revision on an active project → 200 / 409 stale / 409 duplicate name / 404 foreign, `GET /projects?state=` active / archived / all / invalid → 422, the five tolerant-PATCH rows, `desired_outcome` omitted keeps / `null` clears / blank clears.
- [x] T011 [US5] Write and observe RED `backend/tests/test_project_archive_traces.py`: every trace of the fixture passes against the real API through `api_client` and `second_api_client`. *(021-FR-025, 021-FR-026, 021-FR-027, 021-FR-028)*
- [x] T012 [US5] Write and observe RED in the existing suites: `backend/tests/test_api_contract.py` (`("/api/projects", "get"): {"401", "422"}`; the unarchive operation with `{"400", "401", "404", "409", "422"}`), `backend/tests/test_task_branch_coverage.py` (unchanged-membership PATCH cases beside `test_update_task_rejects_inactive_project_on_reassignment`; `?state=` beside `test_list_projects_filters_inactive_records`), `backend/tests/test_account_export.py` (`tasks/projects.json` holds the three fields), `backend/tests/test_account_deletion.py` (purge leaves no project row). *(021-FR-026, 021-FR-028)*
- [x] T013 [US5] Make the model part GREEN: `ProjectDocument` in `backend/app/modules/tasks/domain.py` gains `desired_outcome` "`str | None` (trimmed, 1..1000; blank → `None`)" default `None`, `archived_at` "`datetime | None`" default `None` with "non-null ⇒ `state == "archived"`", `archived_before_lossless` "`bool`" default `False` ("true only for a project whose memberships were cleared by an archive"); in `backend/app/schemas/tasks.py` `ProjectCreateRequest` gains "`desired_outcome: str | None = None`, `max_length=1000`", `ProjectUpdateRequest` gains "`desired_outcome: str | None` (optional; omitted = keep, `null` = clear)", `ProjectResponse` gains the three fields; every model stays `StrictBaseModel` (`extra="forbid"`) (data-model E1, E2). *(021-FR-027, 021-FR-028)*
- [x] T014 [US5] Make the service part GREEN in `backend/app/modules/tasks/service.py` (locate by symbol): `update_task` validates the project only when `project_id` is present and differs from the current one; `list_projects` takes `state`; `open_task_counts_by_project(owner_id) -> dict[str, int]` from one `list_for_owner`; `unarchive_project` decorated `@_serialized_write`, idempotency command `unarchive_project:{project_id}` registered in `_apply_idempotent_record` / `_project_result` and its request model in `_request_hash`, checks in the order idempotency record → load (404) → already active (200 unchanged) → stale revision (409) → active name clash (`ConflictError("Project", name)`); `archive_project` still clears members but sets `archived_before_lossless = True`, and on an already archived project changes only `revision` and `updated_at`; `desired_outcome` on create and update. `_assert_active_references` and `_resolve_smart_add_project` stay unchanged (http.md §3 – §5). *(021-FR-025, 021-FR-026, 021-FR-027, 021-FR-028)*
- [x] T015 [US5] Make the startup step GREEN in `backend/app/modules/tasks/repository.py`: `_mark_detached_archives()` runs at each start and sets `archived_before_lossless = true` on archived projects without `archived_at`, without a revision or `updated_at` bump, idempotently (data-model E1; research R12). *(021-FR-027)*
- [x] T016 [US5] Make T007, T011 and T012 GREEN in `backend/app/api/tasks.py` (ASK path): `GET /projects` takes `state: active | archived | all` (default `active`, `error_responses(401, 422)`) and uses the one-pass counts; `POST /projects/{project_id}/unarchive` requires `Idempotency-Key`, takes `ExpectedRevisionRequest`, gets the service via `Depends(get_task_service)`; `_to_project_response` adds the three fields. *(021-FR-026, 021-FR-027, 021-FR-028)*
- [x] T017 [US3] Make T009 GREEN in `backend/app/api/middleware.py` (ASK path): `CorrelationIdMiddleware` parses `X-Client` once against `^brainbuddy-(ios|macos)/[0-9A-Za-z.+-]{1,32}$` into `client` / `client_version` on the existing request log lines, and accepts an incoming `X-Correlation-ID` or `X-Request-ID` only when it matches `^[0-9A-Za-z._-]{1,64}$`, else mints a UUID (http.md §6). No route reads the header. *(021-FR-031, 021-FR-015, 021-FR-030)*
- [x] T018 [P] [US5] Write the docs: in `docs/api-compatibility.md` replace "There is no mobile/iOS client contract yet" with a dated client note (iPhone and Mac clients; every 021 change additive except ADR-0020's archive side effect; the forward-only rule: once a PR-04 kit build exists PR-03 rolls forward, never back; rolling back below PR-02 after PR-03 makes edits in archived projects fail; research R16, http.md §8); in `docs/data-retention.md` the row "Tasks, projects, tags, subtasks, comments" gains "(including a project's desired outcome)". *(021-FR-028)*
- [x] T019 [US5] Verify the slice: `cd backend && pytest --no-cov` over the eight test modules of T007 – T012, then `make test-backend` (coverage floor, Allure taxonomy validator), then `python3 scripts/check_requirement_coverage.py specs/021-mac-sync --requirements` with the slice's ids.

**Checkpoint**: the server's contract for every 021 client exists; archive behaviour is unchanged for people.

---

## Phase 3: Lossless archive — US5 (slice PR-03, SHOW)

**Goal**: ADR-0020: archiving keeps every task's project membership on the server.

**Independent Test**: quickstart Scenario 1 steps 1 and 9 after PR-03.

- [x] T020 [US5] Write and observe RED: flip the clearing assertions to lossless in `backend/tests/test_task_api.py` (the archive cases near l.470, 556 – 566 and 753), `backend/tests/test_task_lifecycle_detail_api.py` (near l.367) and `backend/tests/test_task_tag_project_mvp_api.py` (near l.52); in `backend/tests/test_project_archive_lossless_api.py` replace the PR-02 archive cases: every member task (open, completed, cancelled) keeps `project_id` with no revision or `updated_at` change, the project gets `archived_at` = now and `archived_before_lossless: false`; `test_021_FR_027_repeat_archive_keeps_marker` (a seeded pre-feature archive archived again keeps the marker true and `archived_at` null); a lossless archive of a marked, unarchived project clears the marker; `test_021_SC_006_archive_and_unarchive_keep_every_membership`. *(021-FR-024, 021-FR-027, 021-SC-006)*
- [x] T021 [US5] Update `backend/tests/fixtures/project_archive_traces.json` to lossless archive (members kept, `archived_at` set, marker false; repeat archive as before) and observe `backend/tests/test_project_archive_traces.py` RED against the PR-02 service. *(021-FR-024)*
- [x] T022 [US5] Make T020 and T021 GREEN in `backend/app/modules/tasks/service.py`: `archive_project` changes no task, sets `archived_at = now` and `archived_before_lossless = False`, and keeps the repeat-archive guard; then `cd backend && pytest --no-cov tests/test_project_archive_lossless_api.py tests/test_project_archive_traces.py tests/test_task_api.py tests/test_task_lifecycle_detail_api.py tests/test_task_tag_project_mvp_api.py -q` and `make test-backend`. The web page for archived projects (PR-06) is deferred: until the follow-up the web shows a task in a project archived from now on as "No project" (review c2, G45). *(021-FR-024, 021-SC-006)*

**Checkpoint**: the server keeps memberships; older clients see what http.md §7 states.

---

## Phase 4: Kit contract — archive, outcome, merge, pure helpers (slice PR-04, SHOW)

**Goal**: The shared kit applies lossless archive, unarchive and the desired outcome, merges archived projects without losing memberships, describes sync issues in one place, identifies the client, and provides the pure helpers the Mac views need, with every exhaustive switch over the new cases in the same slice (enum-case rule, kit-commands §9).

**Independent Test**: `sh ios/scripts/swift-linux.sh test` green with every new test; the iPhone app builds on the `ios-app` lane; the trace copy is byte-identical; quickstart Scenario 4 steps 1, 5, 7, 8, 9 and 11 pass against the fake server.

**Lanes** (plan "PR-04 task lanes"): (a) rules T023 – T029, (b) API T030 – T032, (c) fake server and traces T033 – T035 and (d) pure helpers T036 – T042 start in parallel; (e) integration T043 – T051 starts after (a) – (c) and owns `Workspace.swift`. The slice compiles only with (a) and (e) in, so CI runs on the assembled slice.

### Lane (a): rules

- [x] T023 [P] [US5] Write and observe RED `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ReducerArchiveTests.swift` (new), the ADR-0020 table of kit-commands §3: archive keeps every task's `projectID`, sets `archivedAt` to the command's issue time and changes no task; a repeat archive is `alreadySatisfied` with `archivedAt` and `archivedBeforeLossless` untouched; unarchive sets `state = .active`, `archivedAt = nil`, leaves the marker and changes no task; unarchive while an **active** project has the same normalized name → `.unarchiveNameInUse(name)` ("Another active project is already called “<name>”. Rename one first."); `createTask` / Smart Add into an archived project → `.projectNotActive`; `updateTask` with `.set(p)`, `p` archived, rejected only when `p ≠ task.projectID`; omitting `projectID` accepted; `replayable` keeps a carried archived membership and drops only a new one; rename, recolour and `setProjectOutcome` allowed on an archived project. *(runtime: Linux)* *(021-FR-024, 021-FR-025, 021-FR-026)*
- [x] T024 [P] [US5] Write and observe RED in `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ReducerOrganizeTests.swift`: `createProject` with `desiredOutcome` "≤ 1000, trimmed, blank → nil"; 1,001 → `.outcomeTooLong` ("Keep the desired outcome under 1,000 characters."); `setProjectOutcome` on an active and an archived project; `.duplicateProjectName` keeps "A project named … already exists."; the existing archive-clears case flipped to lossless. *(runtime: Linux)* *(021-FR-028, 021-FR-024)*
- [x] T025 [US4] Write and observe RED in `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ReplayTests.swift`, the merge table of kit-commands §3: an archived local "Old flat" with three tasks against an active account "Old flat" → every reference follows the survivor, no task is created without a project, and the local `archiveProject` becomes a `RejectedOperation` with `.archiveNotMerged("Old flat")`; the same through the 409 duplicate-name path; active local against an archived-only account project → two projects; archived against archived-only → two archived projects; both sides with an outcome → the account's kept and the issue carries the full 1,000-character local outcome; a survivor without one gets the local outcome re-issued as `setProjectOutcome`; a separate `setProjectOutcome` after a local archive is dropped from the rewritten outbox and its value fed into the outcome rule (G12); `withdrawing(project:)` no longer used for projects. *(runtime: Linux)* *(021-FR-003, 021-FR-028, 021-SC-003)*
- [x] T026 [P] [US5] Write and observe RED in `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/CompactionTests.swift`: `setProjectOutcome` after an unsent `createProject` folds into its `desiredOutcome`; after an `archiveProject` it does not fold. *(runtime: Linux)* *(021-FR-028)*
- [x] T027 [P] [US1] Write and observe RED in `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/SmartAddParserTests.swift`: port the Mac's `macos/Tests/BrainBuddyMacTests/SmartAddParserTests.swift` cases the kit lacks (completed tokens and the selected context; literal sigils and incomplete tokens kept in the title; quoted escapes, Unicode names and punctuation cleanup; an archived project name shown and refused with "Unarchive “<name>” before adding a task to it."; non-empty, bounded titles and names), so the Mac file can be deleted in PR-08. *(runtime: Linux)* *(021-FR-010, 021-FR-025)*
- [x] T028 [US5] Make T023 – T027 GREEN in Core: `Records.swift` (`ProjectRecord.desiredOutcome` "`String?` (≤ 1000, trimmed, blank → nil)", `archivedAt` "`Date?`", `archivedBeforeLossless` "`Bool`" default false, "pull only (the server decides it)", all `decodeIfPresent`, defaulted initializer parameters); `Commands.swift` (`createProject.desiredOutcome`, `setProjectOutcome(project:outcome:)`, `unarchiveProject(project:)`, `GTDValidationError.outcomeTooLong`, `.unarchiveNameInUse(String)`, `.archiveNotMerged(String)` with their messages); `Reducer.swift` (dispatch); `Reducer+Organize.swift` (lossless archive, unarchive, outcome); `Reducer+Validation.swift` (`checkReferences`); `Reducer+Replay.swift` (`replayable`); `Replay.swift` (`rewritingAfterMerge` and the outcome rule, stale doc comments of `rewritingAfterMerge` and `withdrawing` rewritten); `Compaction.swift` (the fold and the barriers for the two new cases); `SmartAdd+Resolution.swift` (the "Unarchive … before adding a task to it." copy). All under `ios/BrainBuddyKit/Sources/BrainBuddyCore/`. *(runtime: Linux)* *(021-FR-003, 021-FR-024, 021-FR-025, 021-FR-026, 021-FR-028)*
- [x] T029 [P] [US5] Teach the property-test generators the two new commands: `ios/BrainBuddyKit/Tests/BrainBuddySyncTests/Support/RandomCommands.swift` and `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/TestSupport/CoreFixtures.swift` emit `setProjectOutcome` and `unarchiveProject`, so `CompactionPropertyTests` and the convergence properties exercise them. *(runtime: Linux)* *(021-FR-028, 021-FR-026)*

### Lane (b): API

- [x] T030 [P] [US3] Write and observe RED `ios/BrainBuddyKit/Tests/BrainBuddyAPITests/ClientIdentityTests.swift` (new): `ClientIdentity.iOS.name == "brainbuddy-ios"`, `.macOS(version:)`; requests send `X-Client: brainbuddy-macos/<v>` for a macOS identity and the iOS value by default; one fresh lower-cased UUID `X-Correlation-ID` per request; a timeout `APIError` carries the sent correlation id as `referenceID` (kept, now tested). *(runtime: Linux)* *(021-FR-031, 021-FR-015)*
- [x] T031 [P] [US5] Write and observe RED in `ios/BrainBuddyKit/Tests/BrainBuddyAPITests/EndpointRequestTests.swift`: `unarchiveProject(id:expectedRevision:idempotencyKey:)` → `POST /projects/{id}/unarchive` with `{expected_revision}` and the key; `listProjects(state: .all)` → `GET /projects?state=all`; `POST /projects` with `desired_outcome`; `PATCH /projects/{id}` with `desired_outcome` (`null` clears); and in `ios/BrainBuddyKit/Tests/BrainBuddyAPITests/WireDecodingTests.swift`: a `ProjectResponse` with and without the three fields decodes. *(runtime: Linux)* *(021-FR-026, 021-FR-028, 021-FR-027)*
- [x] T032 [US5] Make T030 – T031 GREEN in `ios/BrainBuddyKit/Sources/BrainBuddyAPI/`: `BrainBuddyAPI.swift` (`ClientIdentity`; `clientName` becomes `ClientIdentity.iOS.name`), `BrainBuddyAPIClient.swift` (`identity: ClientIdentity = .iOS`, the `X-Client` header, `listProjects(state:)`, `unarchiveProject`, the outcome bodies), `APIError.swift` (no new `Kind`), `WireModels.swift` (project DTO fields, `decodeIfPresent`), `RequestBodies.swift`. *(runtime: Linux)* *(021-FR-031, 021-FR-026, 021-FR-028)*

### Lane (c): fake server and traces

- [x] T033 [US5] Copy `backend/tests/fixtures/project_archive_traces.json` as PR-03 left it, byte for byte, to `ios/BrainBuddyKit/Tests/BrainBuddySyncTests/Resources/project_archive_traces.json`; declare `resources: [.copy("Resources")]` on `BrainBuddySyncTests` in `ios/BrainBuddyKit/Package.swift`; add to `backend/tests/test_project_archive_traces.py` a case that reads both files from the checkout and asserts byte equality (it runs on every landing). *(021-FR-024)*
- [x] T034 [US5] Write and observe RED `ios/BrainBuddyKit/Tests/BrainBuddySyncTests/ProjectArchiveTraceReplayTests.swift` (new): every trace replays against `BrainBuddyFakeServer` with the same statuses and bodies. *(runtime: Linux)* *(021-FR-024, 021-FR-026, 021-FR-027, 021-FR-028)*
- [x] T035 [US5] Make T034 GREEN in `ios/BrainBuddyKit/Sources/BrainBuddyFakeServer/`: `FakeServer+Organize.swift` (lossless archive with `archived_at`; repeat archive changes only the revision; unarchive with the 409 duplicate name and the active no-op checked before the revision; `?state=`), `ServerState.swift` (a test helper seeding `archived_before_lossless`), `FakeServerRecords.swift` (`ProjectRow` / `projectDTO` gain the three fields), `FakeServer+Tasks.swift` (tolerant `PATCH /tasks/{id}`). *(runtime: Linux)* *(021-FR-024, 021-FR-025, 021-FR-026, 021-FR-027)*

### Lane (d): pure helpers

- [x] T036 [P] [US1] Write and observe RED `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/TaskEditDraftTests.swift` (new): `changes()` omits untouched fields and sends touched ones (omit / `null` / value); `rebased(onto:)` shows an incoming change to an untouched field and keeps a touched one; `SelectionAnchor` resolves by `EntityID` in a new query result and falls back to the nearest surviving neighbour. *(runtime: Linux)* *(021-FR-009)*
- [x] T037 [P] [US1] Write and observe RED `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ListPresentationHoldTests.swift` (new): a pull that moves the hovered or edited row keeps it at its index while every other row takes its new place; release applies the full new order; a held row that left the list stays until release; no hold gives the new order unchanged. *(runtime: Linux)* *(021-FR-009)*
- [x] T038 [P] [US4] Write and observe RED `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/RecordContentFormTests.swift` (new): the bytes are unchanged by a pull that changes only `updatedAt` or `serverID`, by `c:` → `s:` re-keying, and by sign-out and sign-in; changed by an edit of any listed field (title, notes, state and list, waiting-for, due date, priority, project and tag names, subtask titles and states); length prefixes make different field sets give different bytes; a project's bytes are the sorted bytes of its tasks. *(runtime: Linux)* *(021-FR-023)*
- [x] T039 [P] [US4] Write and observe RED `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ImportCanonicalizerTests.swift` (new), each case with its exact value and report entry (mac-legacy-import §6): "Квартира №5" → "Квартира No5"; "™ Ideas" → "TM Ideas"; "Home  Repair" → "Home Repair"; active "Home  Repair" and "Home Repair" → "Home Repair" and "Home Repair (2)", an archived "Home Repair" beside them unchanged; tags "@home" and "home" → "home" and "home (2)"; "Errands " → "Errands"; a 500-emoji "👍🏽" title (1,000 scalars) → within 500 scalars ending "…", the full title first in the notes, no grapheme split; "Call  mom" unchanged; 25,000-character notes → at most 20,000 scalars plus one "Notes, continued (1 of 1):" comment, together the original; a 30,000-character comment → two comments; a 1,200-character outcome → 1,000 scalars ending "…"; a 100-character colour dropped; a missing project reference dropped; the same snapshot twice gives byte-identical output. *(runtime: Linux)* *(021-FR-020)*
- [x] T040 [P] [US5] Write and observe RED `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ProjectDisplayTests.swift` (new): `GTDQueries.projectDisplay` for each combination of state, marker and task count: `isArchived`, `acceptsNewTasks` (false when archived), `showsPreLosslessLine` (marker true **and** no task in any state), label "<name> · archived". *(runtime: Linux)* *(021-FR-025, 021-FR-027)*
- [x] T041 [US1] Make T036, T037, T038 and T040 GREEN in `ios/BrainBuddyKit/Sources/BrainBuddyCore/`: `TaskEditDraft.swift` (with `SelectionAnchor`), `ListPresentationHold.swift`, `RecordContentForm.swift` (canonical, length-prefixed bytes of the user-visible fields in a fixed order; never an id, a `RecordKey`, `updatedAt` or a server time; no hashing, data-model E7.2), `Queries+ProjectDisplay.swift`. *(runtime: Linux)* *(021-FR-009, 021-FR-023, 021-FR-025, 021-FR-027)*
- [x] T042 [US4] Make T039 GREEN in `ios/BrainBuddyKit/Sources/BrainBuddyCore/ImportCanonicalizer.swift`, built on `NameNormalizer` and `FieldRules` and following the mac-legacy-import §2a table in its order: project names `NameNormalizer.display`, "1…500 scalars, unique among active projects by `NameNormalizer.project`", empty → "Untitled project", cut with "…" at a grapheme boundary, an active duplicate key gets the smallest free " (2)", " (3)" (archived projects get no suffix); tags the same with `tagDisplay` and "Untitled tag"; titles `stripped`, empty → "Untitled task", over 500 scalars cut and "Full title: <original>" put before the notes; subtask titles likewise into the parent's notes; waiting-for "stripped, 1…500 scalars, required in Waiting", empty in Waiting → "(not recorded)"; notes "≤ 20,000 scalars", the rest as "Notes, continued (k of n):" comments; comment bodies "1…20,000 scalars", split with "(continued)"; outcome "trimmed, blank → nil, ≤ 1,000 scalars"; colour "≤ 64 scalars" else dropped; unparseable dates dropped; an unknown state → open in Inbox; missing references dropped; one adjustment entry per change. *(runtime: Linux)* *(021-FR-020)*

### Lane (e): integration (after lanes a – c)

- [x] T043 [US5] Write and observe RED `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/SyncIssueDescriberTests.swift` (new): every description the iPhone's `SyncIssuesScreen.describe` produces today, verbatim; plus kit-commands §5: unarchive 409 name with and without "N tasks you added to it were kept without a project."; the repeated-rejection copy for unarchive ("Brain Buddy couldn't unarchive it, so it's still archived. Try Unarchive again later.") and archive; `setProjectOutcome`; the kept outcome in full, never clipped; `.archiveNotMerged`; a task added without a project because it was archived elsewhere; the defensive deleted-elsewhere copy; curly quotes clipped at 60 characters; every description carries the issue's non-empty reference id. *(runtime: Linux)* *(021-FR-011, 021-FR-015, 021-SC-004)*
- [x] T044 [US5] Write and observe RED `ios/BrainBuddyKit/Tests/BrainBuddySyncTests/ProjectArchiveSyncTests.swift` (new): a pull includes archived projects without tasks; against a server that ignores `?state=` the per-id fallback still fetches referenced archived projects; an unarchive answered 409 duplicate name reverts the project to archived at once and rewrites a capture queued behind it to no project, under one issue that counts it and no 400; an archive reply with `archived_before_lossless: true` or `archived_at: null` raises one "server is out of date" issue (G62); `setProjectOutcome` answered 409 stale goes through refetch, replay and resend. *(runtime: Linux)* *(021-FR-011, 021-FR-024, 021-FR-026)*
- [x] T045 [US5] Write and observe RED in `ios/BrainBuddyKit/Tests/BrainBuddySyncTests/SyncEnginePullTests.swift`: the pull lists projects with `?state=all` instead of fetching archived ones per id; deleted tags keep the per-id fetch. *(runtime: Linux)* *(021-FR-024, 021-FR-026)*
- [x] T046 [P] [US5] Write and observe RED in `ios/BrainBuddyKit/Tests/BrainBuddyPersistenceTests/StoreDocumentCodingTests.swift`: a v1 document written before 021 decodes; `ProjectRecord`'s new fields and the two new command cases round-trip inside `PendingOperation` and `SyncIssue`; `StoreDocument.currentVersion` and `migrationStep` are unchanged by 021. *(runtime: Linux)* *(021-FR-008, 021-FR-028)*
- [x] T047 [US5] Write and observe RED in `ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/WorkspaceCommandTests.swift`: `Workspace.unarchiveProject`, `setProjectOutcome`, and `apply([…])` validating the whole sequence on a scratch state and appending it in one document write or not at all (Inbox "clarify as project", Waiting follow-up + keep waiting, Someday → Next with a new title); a local edit of field A while a pull changes A and B sends only A, shows B's incoming value and keeps every `EntityID`. *(runtime: Linux)* *(021-FR-009, 021-FR-026, 021-FR-028)*
- [x] T048 [US4] Write and observe RED `ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/FirstSignInMergeTests.swift` (new), through `Workspace` and the fake server: the merge cases of T025 end to end (archived local "Old flat" against an active account "Old flat", also through 409; active against archived-only; archived against archived-only, asserted explicitly with duplicates counted on active names only); outcomes on both sides; an outcome set after a local archive leaves the account's unchanged and no `PATCH` carries the local one; the `RecordContentForm` bytes behind valid Waiting, Someday and Project marks are unchanged by the upload, the pull, and sign-out then sign-in to the same account. *(runtime: Linux)* *(021-FR-003, 021-FR-023, 021-FR-028, 021-SC-003)*
- [x] T049 [US5] Make T043 GREEN in `ios/BrainBuddyKit/Sources/BrainBuddyCore/SyncIssueDescriber.swift` (new) and make `ios/BrainBuddy/Screens/Settings/SyncIssuesScreen.swift` delegate `describe` to it (its exhaustive `switch` over `GTDCommand` goes; iPhone copy unchanged). The iPhone app builds: `cd ios && xcodegen generate --spec project.yml && xcodebuild -project BrainBuddy.xcodeproj -scheme BrainBuddy -destination 'generic/platform=iOS Simulator' -configuration Debug CODE_SIGNING_ALLOWED=NO build`. *(runtime: Linux for the kit test; macOS lane for the app build)* *(021-FR-011, 021-FR-015)*
- [x] T050 [US5] Make T044 – T048 GREEN: `ios/BrainBuddyKit/Sources/BrainBuddySync/GTDCommand+Sync.swift` (requests, conflict keys and revisions for the two new cases), `PushPlanner.swift` (unarchive push; `PATCH` with `desired_outcome`), `SyncEngine+Push.swift` (the 409 unarchive revert and capture rewrite; the clearing-server guard), `SyncEngine+Pull.swift` (`listProjects(state: .all)` with the per-id fallback), `StoreDocument+Merge.swift` (acknowledgements for the new cases), and `ios/BrainBuddyKit/Sources/BrainBuddyWorkspace/Workspace.swift` (`unarchiveProject`, `setProjectOutcome`, `apply(_:)`; the `archiveProject` doc comment no longer says there is no unarchive). *(runtime: Linux)* *(021-FR-003, 021-FR-011, 021-FR-024, 021-FR-026, 021-FR-028, 021-SC-003)*
- [x] T051 [US5] Verify the slice: re-run the enum-case search of kit-commands §9 (`grep -rn "case \.archiveProject" --include=*.swift ios/BrainBuddyKit ios/BrainBuddy ios/BrainBuddyWidgets ios/Shared macos`, then each `switch` over `GTDCommand` or `GTDValidationError` checked for a `default`) and confirm every file it finds is in this slice's paths; `sh ios/scripts/swift-linux.sh test`; `cd backend && pytest --no-cov tests/test_project_archive_traces.py -q`; the iPhone build of T049 on the `ios-app` lane; the requirement scan with `--requirements`. The landing produces one TestFlight build (plan "TestFlight").

**Checkpoint**: both Apple clients share lossless archive, unarchive, outcome and merge rules; the iPhone app still builds.

---

## Phase 5: Kit status, cadence and session — US1, US2, US3 shared logic (slice PR-05, ASK)

**Goal**: One shared, Linux-tested status description with the quiet thresholds; the failing clock; the periodic ticker and the foreground call; single-flight "Sync now"; the sign-out order with a pending logout recorded first; the Keychain write failure at sign-in; the macOS token-store attributes; the convergence and offline matrix (SC-001, SC-002).

**Independent Test**: `sh ios/scripts/swift-linux.sh test` green with quickstart Scenario 4 steps 2 – 4, 6, 12 – 14 and Scenario 5 steps 1 – 3 as kit tests.

**Note**: the pure status files (T052 – T054) share nothing with PR-04 and may be developed beside it; the slice lands after PR-04, through the ASK procedure (plan "Migration, deploy order and rollback").

- [x] T052 [P] [US3] Write and observe RED `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/SyncPresentationTests.swift` (new), every case of sync-status §5 for `.mac` and `.iPhone`: each §3 row; every precedence pair, with failing + offline → offline and the return online with `failingSince` kept; the ladder boundaries (59 / 60 s, 59 / 60 min, midnight, 6 / 7 days, the year change, a future time → "Synced just now"); the waiting suffix at 10 s and 10.001 s from the sendable time (an operation issued 213 days ago and linked 5 s ago shows none); `initialUploadRemaining > 0` → "Not synced yet" and `popoverFirstUpload`; failing at 59.999 s and 60 s, surviving a decoded relaunch; offline with 0, 1, 2 waiting; singular and plural; `syncNowEnabled` false exactly for `accountLess`, `sessionEnded`, `offline` and true while syncing otherwise; the copy catalogue verbatim, including `accountSwitchRefused`, every `popover*` key and the three `popoverBackup` forms, every `signOutUnsent` variant, `signOutNothingUnsent`, `signOutIssues` (1 and N), `signOutBackup` (dated, and undated once the date has passed while the backup is kept), `signOutBackupRemoved` (never with `signOutBackup`), `popoverImportAdjusted`, `popoverFirstLoadEmpty` and the sentence order; the tooltip table verbatim including "Last tried"; the oldest-age formatter boundaries; non-empty reference ids in the failing tooltip and `popoverFailing`; no "—" anywhere. The snapshot's validation is asserted as data-model E6 states it: "`pendingCount ≥ 0`, and `oldestPendingAt` is nil iff `pendingCount == 0`", "`0 ≤ initialUploadRemaining ≤ pendingCount`", and with no account both are reported as 0. *(runtime: Linux)* *(021-FR-004, 021-FR-012, 021-FR-014, 021-FR-015, 021-FR-016, 021-FR-018, 021-FR-019, 021-FR-021, 021-SC-004)*
- [x] T053 [P] [US3] Write and observe RED `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/SyncActivityIndicatorTests.swift` (new): a 0.9 s cycle shows nothing; a 1.1 s cycle shows the indicator for at least 0.5 s; back-to-back cycles give one continuous span; `nextChange(after:)` names the next re-evaluation. *(runtime: Linux)* *(021-FR-013)*
- [x] T054 [US3] Make T052 – T053 GREEN in `ios/BrainBuddyKit/Sources/BrainBuddyCore/SyncPresentation.swift` (new: `SyncTiming` with `indicatorDelay` 1 s, `indicatorMinimum` 0.5 s, `waitingSuffixAfter` 10 s, `failureSurfacesAfter` 60 s, `relativeRefresh` 30 s, `periodicTick` 15 s, `pullAge` 30 s, `webRefetch` 45 s; `DeviceKind`; `SyncSnapshot` per data-model E6; `SyncStatusDescription`; `SyncStatusDescriber`; the copy catalogue) and `SyncActivityIndicator.swift` (new, a value type with no timers). *(runtime: Linux)* *(021-FR-012, 021-FR-013, 021-FR-016, 021-FR-019)*
- [x] T055 [US3] Write and observe RED `ios/BrainBuddyKit/Tests/BrainBuddySyncTests/SyncEngineFailingClockTests.swift` (new): `failingSince`, `lastFailedAttemptAt` and `lastFailureReferenceID` are set by a server-blocked cycle (5xx, 429, redirect, unreadable 2xx, timeout with a network), persisted and decoded after a relaunch, cleared by a completed cycle, kept while offline and never started by an offline error; with the real `retryDelay` and jitter pinned at both extremes, attempts land at about 2, 6, 14 and 30 s and one at exactly 60 s; an outage ending at 59 s never yields `failing`; one ending at 61 s yields it after the 60 s attempt; 401 sets `needsSignIn`. *(runtime: Linux)* *(021-FR-014, 021-FR-015, 021-SC-005)*
- [x] T056 [P] [US1] Write and observe RED `ios/BrainBuddyKit/Tests/BrainBuddySyncTests/PeriodicSyncTickerTests.swift` (new), with `ManualSyncScheduler`: fires at 15, 30 and 45 s while active; fires nothing while inactive; restarts on reactivation; a tick reaches the engine as `.periodic`. *(runtime: Linux)* *(021-FR-006, 021-FR-032)*
- [x] T057 [US1] Write and observe RED in `ios/BrainBuddyKit/Tests/BrainBuddySyncTests/SyncEngineSchedulingTests.swift`: `.periodic` honours the 30 s pull age, never sets `pullRequested`, and for 29 s of idle ticks runs no cycle and emits no `.status` or `.documentChanged`; it is a no-op while a retry is scheduled, while `.manual` runs at once; "Sync now" pressed three times during a cycle joins it or queues exactly one follow-up and is never refused. *(runtime: Linux)* *(021-FR-006, 021-FR-019)*
- [x] T058 [US4] Write and observe RED in `ios/BrainBuddyKit/Tests/BrainBuddySyncTests/SyncEngineSessionTests.swift` (ASK path): the account-switch refusal carries no device text (`AccountSwitchRefused` has none; the copy comes from the catalogue with the device noun); a token store whose `setToken` throws gives a sign-in failure with a non-empty reference id, exactly one logout request carrying the issued token, and no linked account; a spy store records that engine reads are non-interactive and the sign-in path is interactive. *(runtime: Linux)* *(021-FR-004, 021-FR-005, 021-FR-015)*
- [x] T059 [US1] Write and observe RED in `ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/WorkspaceSyncTests.swift`: the sign-out order (a failing removal leaves the token, sends no logout, leaves no pending logout, and the status is not `needsSignIn`; a successful one removes the token and sends or queues the logout; a crash injected between removal and token removal, then a relaunch, sends exactly one logout); `setForegroundActive(true)` starts the ticker and requests `.foreground` once, `false` stops it, repeats are idempotent; `syncSnapshot` derives `oldestPendingAt` from `max(issuedAt, account.linkedAt)` and `initialUploadRemaining` from operations issued before `linkedAt`; with the first pull held open (`HoldingTransport`) local commands and queries answer at once and the snapshot reads "Not synced yet". *(runtime: Linux)* *(021-FR-005, 021-FR-006, 021-FR-012, 021-FR-018, 021-FR-032)*
- [x] T060 [US2] Write and observe RED `ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/MacIPhoneConvergenceTests.swift` (new), quickstart Scenario 4 with two `Workspace`s (`.macOS` and `.iOS` identities), one fake server and an injected clock: for every FR-007 record type in both directions, a change applied at the worst tick phase (just after the receiver's pull, 1.5 s pull duration, 2 s debounce, 15 s ticks, 30 s pull age) is held by the receiver within 60 s in every case; the offline matrix (20 mixed changes offline, store reopened, a response dropped mid-push, reconnect) puts every change on the server exactly once and the same set on the iPhone; the same field edited offline on both resolves last-to-reach-the-server per field and different fields both survive; an offline capture into a project archived elsewhere lands without it under the archived-elsewhere issue; the account switch is refused with nothing sent; archive on one and unarchive on the other keep every membership. *(runtime: Linux)* *(021-SC-001, 021-SC-002, 021-SC-006, 021-FR-004, 021-FR-007, 021-FR-008, 021-FR-011, 021-FR-032)*
- [x] T061 [US3] Make T055 GREEN: `SyncMetadata` in `ios/BrainBuddyKit/Sources/BrainBuddyCore/Outbox.swift` gains `failingSince`, `lastFailedAttemptAt`, `lastFailureReferenceID` (all optional, `decodeIfPresent`; data-model E5); `ios/BrainBuddyKit/Sources/BrainBuddySync/SyncEngine.swift` and `SyncEngine+Cycle.swift` maintain them and cap the backoff so one attempt starts at exactly `failingSince + 60 s`. *(runtime: Linux)* *(021-FR-014, 021-SC-005)*
- [x] T062 [US1] Make T056 and T057 GREEN: `SyncTrigger.periodic` in `ios/BrainBuddyKit/Sources/BrainBuddySync/BrainBuddySync.swift` and its rule in `SyncEngine.swift` (`request`, the switch over `SyncTrigger`: no-op unless the pull is due or sendable operations wait with no debounce scheduled, always while a retry is scheduled); `PeriodicSyncTicker.swift` (new; `PeriodicSyncTicker(interval:scheduler:fire:)` with `setActive(_:)`); `SyncConfiguration.swift` (`pullInterval` default 60 s kept for other callers); single-flight `syncNow` kept. *(runtime: Linux)* *(021-FR-006, 021-FR-019, 021-FR-032)*
- [x] T063 [US4] Make T058 and the sign-out part of T059 GREEN: in `ios/BrainBuddyKit/Sources/BrainBuddySync/BrainBuddySync.swift` replace `SyncService.signOut()` with `signOut(removingLocalDataWith:)` and implement it in `SyncEngine.swift` and `SyncEngine+Session.swift` (stop and wait for a running cycle; record the token as a pending logout; run the removal; on success remove the token and log out now or later; on failure withdraw the pending logout, resume, rethrow); conform `ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/Support/FakeSyncService.swift`; move the refusal text to the catalogue. In `ios/BrainBuddyKit/Sources/BrainBuddyAPI/SessionTokenStore.swift` (ASK path): on macOS no `kSecAttrAccessible`, `kSecAttrSynchronizable = false` explicitly, an `interactive` option added as a requirement with a default in the protocol extension (so the test conformers in `Tests/BrainBuddyAPITests/TestSupport.swift` and `SessionTokenStoreTests.swift` compile unchanged), non-interactive reads (`kSecUseAuthenticationUI` fail or an `LAContext` with `interactionNotAllowed`), delete-and-re-add after access denied at an interactive sign-in, a macOS-only initializer taking a `SecKeychain` for tests; iOS unchanged. In `BrainBuddyAPIClient.swift` `exchange` ends the session it just opened when `setToken` fails and throws `.tokenStorage` with the request's reference id; `APIError.swift` carries "Brain Buddy couldn't save your sign-in on this device. Try again." (no new `Kind`). *(runtime: Linux; the macOS attributes compile on the macOS lane)* *(021-FR-004, 021-FR-005, 021-FR-015, 021-FR-018)*
- [x] T064 [US1] Make the rest of T059 and T060 GREEN in `ios/BrainBuddyKit/Sources/BrainBuddyWorkspace/Workspace.swift`: `setForegroundActive(_:)` (ticker on and one forced pull; off), `syncSnapshot`, the `device: DeviceKind` and `identity: ClientIdentity` parameters defaulting to `.iPhone` / `.iOS`, sign-out through the new protocol call. *(runtime: Linux)* *(021-FR-006, 021-FR-012, 021-FR-032, 021-SC-001, 021-SC-002)*
- [x] T065 [US1] Verify the slice: the enum-case search for `SyncTrigger` finds only `SyncEngine.swift` (`request`), and no app file switches over `SyncStatus` newly; `sh ios/scripts/swift-linux.sh test`; the iPhone app build of T049 on the `ios-app` lane (public defaults keep it compiling); the requirement scan. The landing produces one TestFlight build.

**Checkpoint**: the shared logic of the status line, the cadence and the session is done and tested on Linux.

---

## Phase 6: Web archived projects and refetch — US5, FR-032 (DEFERRED, no slice; owner decision 2026-10-07)

**Goal**: Design D-01 on the web, the 45 s visible-tab refetch (SC-001 Mac → web), the parity manifest. Kept for the follow-up feature; not in the manifest.

**Independent Test**: quickstart Scenario 7 (web) with Vitest and Playwright.

- (deferred) T066 [P] [US5] Write and observe RED in `frontend/src/api/__tests__/client.test.ts`: `listProjects(state)` sends `?state=`; `unarchiveProject` posts `/projects/{id}/unarchive` with `Idempotency-Key` and `expected_revision`; project responses carry `desired_outcome`, `archived_at`, `archived_before_lossless`. *(021-FR-026, 021-FR-027)*
- (deferred) T067 [P] [US5] Write and observe RED in `frontend/src/api/__tests__/clientParity.test.ts`: the manifest `contracts/api-client-parity.json` lists `unarchiveProject` and `listProjects(state)`, the operation count follows the manifest, and adapter keys equal it (review c2, G09). *(021-FR-026)*
- (deferred) T068 [P] [US1] Write and observe RED in `frontend/src/api/__tests__/taskHooks.test.ts`: `useTaskList`, `useProjects` (with `state: "all"`), `useTags` and the open task's `useTaskDetail` set `refetchInterval: 45_000` and `refetchIntervalInBackground: false`. *(021-FR-032, 021-SC-001)*
- (deferred) T069 [P] [US5] Write and observe RED in `frontend/src/components/shell/__tests__/AppShell.test.tsx`: the "Archived projects 2" disclosure (accessible name "Archived projects, 2"), hidden when none; active projects only under Projects on every page that renders the shell; the archive hint line "Archiving keeps its tasks. You can unarchive it from Archived projects."; archived options offer only "Unarchive"; "Rename…" opens the options popover's name field for an archived project, a clash (409 from the server) shows its message "Project 'Old flat 2' already exists." with Ref in the popover, focus kept in the field; Escape returns focus to the options button. *(021-FR-024, 021-FR-025, 021-FR-026)*
- (deferred) T070 [P] [US5] Write and observe RED in `frontend/src/features/tasks/__tests__/TaskListPage.test.tsx`, every D-01 state: the archived project page (chip, secondary "Unarchive", no composer, "Archived projects don't take new tasks. Unarchive it to add tasks."); "Unarchiving…" with `aria-disabled` and a polite status, focus kept; unarchived → focus to the heading and toast "Unarchived “Old flat”"; archived just now → archived page, focus to the heading, toast "Archived “Old flat”"; error → notice with Ref and Retry (`role=alert`), focus on Retry; 409 refusal → "Another active project is already called “Old flat”. Rename one first." with Ref and "Rename…", no Retry, focus on Unarchive; offline → Unarchive disabled with "You're offline. Unarchive is available when you're back online."; "Old flat · archived" in groupings; filtered empty copy. *(021-FR-015, 021-FR-024, 021-FR-025, 021-FR-026)*
- (deferred) T071 [P] [US5] Write and observe RED `frontend/src/features/tasks/__tests__/ArchivedProjectNotice.test.tsx` (new): the FR-027 line ("Archived before projects kept their tasks, so none are listed here. Those tasks are still in their lists.") shows only when `archived_before_lossless` is true and the project has no task in any state, with the same cases as the kit's `ProjectDisplayTests`. *(021-FR-027)*
- (deferred) T072 [P] [US5] Write and observe RED in `frontend/src/features/tasks/__tests__/TaskDetailPanel.test.tsx`: the project picker lists active projects only, plus a task's own archived project labelled "Old flat · archived" and selected; an archived project is never offered as a new choice; archived names resolve. *(021-FR-025)*
- (deferred) T073 [P] [US1] Write and observe RED in `frontend/src/features/tasks/__tests__/TaskDetailAutosaveUI.contract.test.tsx`: a detail refetch while typing keeps the typed text and shows the untouched field's incoming value; scroll and selection do not move. *(021-FR-009, 021-FR-032)*
- (deferred) T074 [US5] Make T066 – T068 GREEN in `frontend/src/api/client.ts` (`listProjects(state)`, `unarchiveProject`), `frontend/src/api/taskTypes.ts` (`ProjectResponse.state: "active" | "archived"`, the three fields), `frontend/src/api/taskHooks.ts` (the refetch on the four queries) and `contracts/api-client-parity.json`. *(021-FR-026, 021-FR-032)*
- (deferred) T075 [P] [US5] Make T071 GREEN in `frontend/src/features/tasks/ArchivedProjectNotice.tsx` (new). *(021-FR-027)*
- (deferred) T076 [US5] Make T069 GREEN in `frontend/src/components/shell/AppShell.tsx`: split active from archived projects, the disclosure, the archive hint, the archived options. *(021-FR-024, 021-FR-025, 021-FR-026)*
- (deferred) T077 [US5] Make T070, T072 and T073 GREEN in `frontend/src/features/tasks/TaskListPage.tsx` (archived page, Unarchive states and focus rules, "· archived" groupings, the 390 px full-width 44 px button) and `frontend/src/features/tasks/TaskDetailPanel.tsx` (picker; archived names). *(021-FR-025, 021-FR-026, 021-FR-032)*
- (deferred) T078 [US5] Write and observe RED, then GREEN, the Playwright specs `frontend/tests/e2e/archived-projects.spec.ts` (new; disclosure, opening "Old flat" lists 3 tasks with no composer, Unarchive with focus and toast, "Tax return 2024" shows the FR-027 line, no horizontal overflow at 390 × 851, a 44 px button, an axe scan with no violations) and `frontend/tests/e2e/cross-client-refresh.spec.ts` (new; with a fake clock, a subtask, a comment and a tag rename made through the API appear within 45 s, scroll and selection unchanged); add a path rule to `frontend/tests/allure.fixtures.ts` if the default does not cover them. *(021-FR-024, 021-FR-026, 021-FR-027, 021-FR-032, 021-SC-001, 021-SC-006)*
- (deferred) T079 [US5] Verify the slice: `cd frontend && npx vitest run src/api src/components/shell src/features/tasks`, `make test-frontend` (coverage floor; no coverage suppression in `frontend/src`), `cd frontend && npm run lint && npm run typecheck`, `make test-e2e`, the requirement scan.

**Checkpoint**: the web shows archived projects with their tasks and refreshes changes from other clients.

---

## Phase 7: iPhone status line and archive — US3, US5 (DEFERRED, no slice; owner decision 2026-10-07)

**Goal** (kept for the follow-up feature; not in the manifest): Design M-01 and M-02 on the iPhone: the shared status words, actionable attention rows, single-flight Settings "Sync now", the foreground ticker, unarchive.

**Independent Test**: the `ios-app` lane builds; quickstart Scenario 5 step 5 and Scenario 7 (iPhone) as host checks.

**Note**: the iPhone app has no test target; its rules are the kit's (PR-04, PR-05 tests). Tests-first here means the host checklists are written before the code, and the automated lane's evidence is the build plus the kit tests. Every task below is *(runtime: macOS lane)* except T080 and T089.

- (deferred) T080 [US3] Write the host checklists first, unfilled, with the evidence header (tree hashes of `ios/BrainBuddy/` and `ios/BrainBuddyKit/`, iOS version, date): `specs/021-mac-sync/evidence/manual-ios-status.md` (every M-01 state at Dynamic Type AX5, Reduce Motion, "first upload", "error, then offline", long-press and VoiceOver "Copy reference ID", the 44 pt account-less row, Settings "Sync now" enabled while syncing, sign-out with open issues, a web change appearing within 60 s with no touch and nothing fetched in the background) and `specs/021-mac-sync/evidence/manual-ios-archive.md` (every M-02 state, the non-destructive archive confirmation, swipe, toolbar and VoiceOver Unarchive, the rename sheet after a refusal). *(runtime: host)* *(021-FR-019, 021-FR-032, 021-FR-026)*
- (deferred) T081 [US3] Render the describer in `ios/BrainBuddy/Components/SyncStatusLabel.swift`: words plus the indicator (static glyph under Reduce Motion), re-described at least every 30 s, wrapping after " · " up to AX5; "Syncing…", the em dash and the immediate "Sync failed — …" go; attention rows become buttons at least 44 pt tall (Retry → Sync now; "Sign in again to sync" → the sign-in sheet with the email locked; "N changes couldn't sync" → Sync issues); the "Couldn't sync" row's long-press and a VoiceOver custom action offer "Copy reference ID"; the account-less "Sign in to sync" target is at least 44 pt; attention states announced once. *(021-FR-012, 021-FR-013, 021-FR-014, 021-FR-015, 021-FR-019)*
- (deferred) T082 [US5] Update `ios/BrainBuddy/Screens/Lists/TaskListScreen.swift`: the M-01 status row; the M-02 archived project screen rendered from `GTDQueries.projectDisplay` (tasks listed and editable, toolbar "Unarchive", "Archived project · it doesn't take new tasks", the FR-027 empty line), the name-clash refusal with "Rename…" opening the existing `ProjectEditorSheet`, VoiceOver focus kept on Unarchive. *(021-FR-019, 021-FR-025, 021-FR-026, 021-FR-027)*
- (deferred) T083 [US3] Update `ios/BrainBuddy/Screens/Browse/ListsHubScreen.swift`: the hub row subtitle in the new words; the Archived projects row hidden when there is none. *(021-FR-019, 021-FR-026)*
- (deferred) T084 [US5] Update `ios/BrainBuddy/Screens/Browse/ProjectsScreen.swift`: the archive confirmation loses its destructive role and reads "Archive “Old flat”?" / "It leaves your project lists. Its tasks keep the project, and you can unarchive it any time from Archived projects."; Archived projects rows open the project; swipe "Unarchive" (full swipe allowed) and a VoiceOver custom action; toast "Unarchived “Old flat”"; the refusal with "Rename…"; empty copy "No archived projects". *(021-FR-024, 021-FR-026)*
- (deferred) T085 [US3] Update `ios/BrainBuddy/Screens/Settings/SettingsScreen.swift` (the Sync section's words from the describer; "Sync now" no longer disabled by a running sync; the Reference ID shown from the first failure; the first-upload progress line; the earlier failure's time and Reference ID while offline; the sign-out confirmation appends `signOutIssues(n)` with "iPhone") and `ios/BrainBuddy/Screens/Settings/SignInSheet.swift` (opened locked to the email from the status row; the account-switch refusal from the catalogue with "iPhone"). *(021-FR-004, 021-FR-015, 021-FR-018, 021-FR-019)*
- (deferred) T086 [US1] In `ios/BrainBuddy/App/BrainBuddyApp.swift`, call `Workspace.setForegroundActive(_:)` from the scene phase and pass `SyncTiming.pullAge` as the pull interval; the old foreground `syncNow` call goes; `WidgetReloadAfterSync` keeps firing only on real cycles. *(021-FR-032, 021-FR-006)*
- (deferred) T087 [P] [US3] Update `ios/AGENTS.md` (the copy example becomes "Offline · 3 changes waiting") and `docs/native-ios-app.md` (lossless archive and unarchive; backend asks 5 and 7 done; `X-Client` with the macOS identity; the 15 s tick and 30 s pull age). *(021-FR-019, 021-FR-024)*
- (deferred) T088 [US3] Verify the automated lane: `sh ios/scripts/swift-linux.sh test` and the iPhone build of T049 on the `ios-app` lane, both on the exact SHA; the requirement scan. The landing produces one TestFlight build.
- (deferred) T089 [US3] Host lane (the owner): fill `specs/021-mac-sync/evidence/manual-ios-status.md` and `manual-ios-archive.md` on the landed build (or a candidate with identical trees), committed afterwards in a docs-only commit (plan "Evidence protocol"). *(runtime: host)* *(021-FR-019, 021-FR-032)*

**Checkpoint**: the iPhone speaks the same status language as the Mac will, and unarchives.

---

## Phase 8: Mac adoption, account-less — US4, US2, US5 on the Mac (slice PR-08, ASK)

**Goal**: The Mac runs on the shared kit, account-less: the one-time import of `local-gtd.json` with its durable state machine, review marks in the sidecar, single instance, the pre-021 cookie and cache cleanup, X-05, X-06, X-08, X-09, and the old store and REST client removed.

**Independent Test**: on the `macos-app` lane, `LegacyStoreImporterTests` and the rewritten `OfflineWorkspaceTests` pass; quickstart Scenario 6 (steps 0 – 2, 4 – 6, 8) and Scenario 8 on a host.

**Lanes** (plan "PR-08 task lanes"): (a) importer and host T090 – T104, mostly new files; (b) rebinding T105 – T110. The importer is wired into the launch order only by T110, after the rebinding: until then the old `BrainBuddyModel` still reads `local-gtd.json`. A Foundation-only library target for the importer is allowed (review c2, G48); taking it adds its paths to the manifest and re-runs the classifier. Every Mac task is *(runtime: macOS lane)* unless marked.

### Lane (a): importer and host

- [x] T090 [US4] Move `macos/Package.swift` to `swift-tools-version: 6.2` with the Swift 6 language mode, add `.package(path: "../ios/BrainBuddyKit")` and the products `BrainBuddyCore`, `BrainBuddyPersistence`, `BrainBuddyAPI`, `BrainBuddySync`, `BrainBuddyWorkspace`, and `resources: [.copy("Resources")]` on the test target (mac-app-host §2); refresh `macos/Package.resolved` (WhisperKit stays `argmax-oss-swift` 0.18.0). Fix Swift 6 diagnostics in place, confining WhisperKit to a `VoiceTranscriber` actor in `macos/Sources/BrainBuddyMac/VoiceCapture.swift`, with a documented `@preconcurrency import` only if WhisperKit's declarations force it (research R2). No `unsafeFlags`; no uncommented `@unchecked Sendable`.
- [x] T091 [P] [US4] Write the synthetic fixtures (design example data only) in `macos/Tests/BrainBuddyMacTests/Resources/`: `legacy-populated.json` (archived projects with tasks, an archived project whose name equals an active one, desired outcomes, Waiting, Someday and project review marks, subtasks in three states, edited comments, completed and cancelled tasks with `lastOpenState`, a deleted tag, a Waiting task whose `waitingSince` differs from `createdAt`, a Next list interleaving three projects and no project by `orderKey`), `legacy-awkward.json` (every T039 example in one store), `legacy-corrupt.json`, `legacy-newer.json` (`version > 1`). `legacy-large.json` (2,000 tasks) is generated by the test.
- [x] T092 [US4] Write and observe RED `macos/Tests/BrainBuddyMacTests/LegacyStoreImporterTests.swift`, the import and verification cases of mac-legacy-import §6: the populated fixture with every §3 equality; the awkward fixture (exact report entries, nothing "not carried", the upgrade silent apart from the X-02 line); the 500-seed property test whose generator encodes the old store's own rules read from `macos/Sources/BrainBuddyMac/LocalGTDStore.swift` before T109 deletes it; the golden artifact (seeded `EntityID` generator, fixed clock, sorted keys) equal byte for byte to `ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/Resources/legacy-import-golden.json`; the outbox shape for the archived "Old flat" (`createProject`, three `createTask`, `archiveProject`, nothing compacted); corrupt and newer fixtures leave the legacy bytes unchanged with no staging file and no `store.json`; "partly carried" through a test-only hook; an injected verification failure records `verificationFailed`; the 10 s budget for 2,000 tasks; with a sentinel home folder, no sentinel title, `/Users/`, `local-gtd`, file name or 32-hex run in any captured `os.Logger` line, `unreadableReason` logged by enum name. *(021-FR-020, 021-FR-022, 021-FR-030, 021-SC-003, 021-FR-003)*
- [x] T093 [US4] Write and observe RED, in the same `macos/Tests/BrainBuddyMacTests/LegacyStoreImporterTests.swift`, the state-machine cases: the import state explicit (`none` recorded before the workspace opens; `inProgress` on disk before the staging file; `completed` with the keyed digest, the backup name and `legacyRenamedAt`; `workspaceFirstWrittenAt` on the first write); each FR-033 case of §6 (a file after a fresh install; `mac-local.json` removed; a new file after the rename; sign-out then an older copy writes a file; signed out without an import then a file appears; the backup deleted by retention then the original restored; an `inProgress` record with a foreign `store.json`; an older copy that keeps writing shows no second notice), each asserting unchanged bytes and one "later file" notice; an unwritten fresh workspace still imports (row 2); crashes injected after each step recover with no duplicate; a crash between the record and the rename finishes only the rename; staging cleanup with a sidecar deleted mid-attempt and at sign-out; the backup retention table (29 / 31 days, with and without a sign-out, during the first upload, with a record not carried, with the sidecar lost); a second process holding the legacy `lockf` blocks the import, and after the rename its write fails with its existing 409; review marks survive the import and a due mark stays due. *(021-FR-021, 021-FR-023, 021-FR-033)*
- [x] T094 [P] [US4] Write and observe RED `macos/Tests/BrainBuddyMacTests/MacLocalStateTests.swift` (new): `mac-local.json` written atomically under its own `flock`, mode 0600, holding "no titles, names, notes, outcomes or email" (scanned with sentinels); `RecordKey` "`s:<serverID>` when the record has a server id, else `c:<client EntityID>`", re-keyed `c:` → `s:` on the next write; stamps are CryptoKit `HMAC<SHA256>` keyed by `installSalt` over `RecordContentForm`; a mark is valid while the stamp matches and `reviewedAt + 7 days > now`; marks older than 30 days pruned at launch and unmatched keys after a full pull; marks kept across sign-out; the Archived-projects disclosure state remembered. *(021-FR-023)*
- [x] T095 [P] [US1] Write and observe RED `macos/Tests/BrainBuddyMacTests/SingleInstanceGuardTests.swift` (new): `.instance.lock` taken with an exclusive non-blocking `flock` for the process lifetime; a second process fails to take it; a stale lock after a crash is free; the second copy asks the first to come forward and only when that fails presents X-08 ("Brain Buddy is already open." / "Switch to the open window to keep working.", "OK"). *(021-FR-017)*
- [x] T096 [P] [US4] Write and observe RED `macos/Tests/BrainBuddyMacTests/LegacyCookieCleanupTests.swift` (new): seeded `brainbuddy_session` cookies for three hosts in an injected cookie storage are all gone after launch, each in the pending-logout list bound to its own host, an `http://` non-localhost cookie deleted without a logout; a response seeded in an injected `URLCache` is gone; a second launch does nothing; with `BRAINBUDDY_MAC_DATA_DIR` set the cookies and cache entry stay, nothing is queued and nothing is sent, and a spy token store seeded with a token and a pending logout records no call during launch steps 3 and 4 (`LegacyCookieCleanup`, then `WorkspaceHost.make()` with its launch-time token cleanup), so both items stay (mac-app-host §1). *(021-FR-005, 021-FR-029)*
- [x] T097 [P] [US4] Write and observe RED `macos/Tests/BrainBuddyMacTests/UnreadableWorkspaceTests.swift` (new): a `store.json` that does not decode shows X-09, starts no sync and sends nothing; "Try again" reloads; "Start fresh" after its confirmation sets the file aside as `store.unreadable-<UTC>.json` and opens an empty workspace; the import decision then treats the workspace as in use and imports no `local-gtd.json`. *(021-FR-022, 021-FR-017)*
- [x] T098 [US4] Make T092 GREEN in `macos/Sources/BrainBuddyMac/LegacySnapshot.swift` (new; the data-model E10 decoder, never written) and `macos/Sources/BrainBuddyMac/LegacyStoreImporter.swift` (new): every value through `ImportCanonicalizer`; the command plan of §2 in its order without compaction and with fresh `EntityID`s from an injectable generator; the staging file `store.import-<attemptID>.json`; verification against the canonical expectation (§3); the import report `local-gtd.import-report-<UTC>.txt` only when something was adjusted or not carried; the exclusive staging → `store.json` and legacy → backup renames (`renamex_np` with `RENAME_EXCL`); review marks to the sidecar (§4); counts-only `os.Logger` (subsystem `com.brainbuddy.mac`, category `import`). *(021-FR-020, 021-FR-021, 021-FR-030)*
- [x] T099 [US4] Make T093 GREEN in `macos/Sources/BrainBuddyMac/LegacyImportDecision.swift` (new; data-model E7.1 rows 1 – 16 and invariants 1 – 7, held under the single-instance lock and the legacy `lockf`; `LegacyImportRecord.state` "`none | inProgress | completed | unreadable | laterFileKept`"; orphaned staging files deleted after each terminal decision) and `macos/Sources/BrainBuddyMac/UpgradeNotice.swift` (new; the X-05 alert in every state with the copy of mac-legacy-import §5, "Continue" default, "Show in Finder", Esc not mapped, `noticeSeenAt` recorded, shown again after a quit). *(021-FR-021, 021-FR-022, 021-FR-033)*
- [x] T100 [US4] Make T094 GREEN in `macos/Sources/BrainBuddyMac/MacLocalState.swift` (new; data-model E7 `MacLocalState` and `LegacyImportRecord` as specified, `installSalt` of 32 random bytes, every digest a keyed HMAC, the E8 backup deletion rule with its four conditions and `backupDeletedAt`, the backup date read from its file name when the sidecar is lost). *(021-FR-021, 021-FR-023)*
- [x] T101 [P] [US1] Make T095 GREEN in `macos/Sources/BrainBuddyMac/SingleInstanceGuard.swift` (new; research R6). *(021-FR-017)*
- [x] T102 [P] [US4] Make the cookie and cache part of T096 GREEN (its Keychain part is T103) in `macos/Sources/BrainBuddyMac/LegacyCookieCleanup.swift` (new; once, recorded as `legacyCleanupDoneAt`; every `brainbuddy_session` cookie of `HTTPCookieStorage.shared` handed to the kit's pending logouts bound to its own https host, or `http://localhost`, then deleted; `URLCache.shared.removeAllCachedResponses()` and `~/Library/Caches/com.brainbuddy.mac.prototype/Cache.db*` and `fsCachedData` removed; skipped while `BRAINBUDDY_MAC_DATA_DIR` is set). *(021-FR-005, 021-FR-029)*
- [x] T103 [US4] Make T097 GREEN in `macos/Sources/BrainBuddyMac/UnreadableWorkspaceView.swift` (new; X-09: "We couldn't open your tasks" / "Your tasks are still on this Mac and nothing was changed." + the kit's message, "Try again" default, "Start fresh…" behind "Set the file aside and start fresh?" with "Keep trying" default and on Escape) and `macos/Sources/BrainBuddyMac/WorkspaceHost.swift` (new; `FileDocumentStore(fileURL: …/store.json)` in `~/Library/Application Support/BrainBuddyMac/` (0700) or `BRAINBUDDY_MAC_DATA_DIR`, `SyncEngine` with `KeychainSessionTokenStore(service: "app.brainbuddy.mac.session")`, `pullInterval: SyncTiming.pullAge`, `identity: .macOS(version:)`, `device: .mac`, the `didPersist` hook recording `workspaceFirstWrittenAt`, launch-time token cleanup off the main actor; while `BRAINBUDDY_MAC_DATA_DIR` is set the cleanup does not run and the engine's token store answers no token and no pending logouts without calling the Keychain until a person-started sign-in, which makes the Keychain part of T096 GREEN; mac-app-host §1 step 4). *(021-FR-005, 021-FR-022, 021-FR-031)*
- [x] T104 [US4] Write the golden artifact `ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/Resources/legacy-import-golden.json` from the importer over `legacy-populated.json` (T092's generator and clock), declare `resources: [.copy("Resources")]` on `BrainBuddyWorkspaceTests` in `ios/BrainBuddyKit/Package.swift`, and add to `ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/FirstSignInMergeTests.swift` the case that loads it and signs in against an account with an active "Old flat", "garden" and the tag "Calls": 0 duplicate active projects or tags and 0 missing records (review c2, G21). *(runtime: Linux for the kit case)* *(021-FR-003, 021-SC-003)*

### Lane (b): rebinding

- [x] T105 [US2] Write and observe RED the rewritten `macos/Tests/BrainBuddyMacTests/OfflineWorkspaceTests.swift` in Swift Testing against `Workspace` and `MacLocalState`, porting every case the XCTest ledger below maps to it: capture and quick capture offline, Quick Open by type, account-less restart, quick move with a Waiting reason, Waiting / Someday / Project reviews resuming across restart and task change, follow-up and Someday activation through `apply([…])`, an archived project's membership kept through activation, sidebar counts, project overview, a project-review action rejected after the project changed (now by its content stamp), Inbox clarification into a new project, project capture, archived browse, archive by the File menu, unarchive and its name-clash refusal with "Rename…", tag deletion, the hidden-capture explanation, the editor's length limits equal to the kit's `FieldRules`. *(021-FR-002, 021-FR-010, 021-FR-023, 021-FR-024, 021-FR-025, 021-FR-026, 021-FR-028)*
- [x] T106 [US5] Make T105 GREEN in `macos/Sources/BrainBuddyMac/ContentView.swift`: `BrainBuddyModel`'s rules, store calls and pending-key maps replaced by `Workspace`; selection, scroll and focus keyed by `EntityID` through `SelectionAnchor`; the inline editor holding a `TaskEditDraft`; each list view holding the hovered and edited row in `ListPresentationHold`; every `isLocalWorkspace` gate removed; the removals of mac-app-host §3 (full-window sign-in, session overlay, "Sync needs attention" banner, toolbar "Refresh", "Try local voice capture", the "Desired outcome is not available …" line); X-06 in every state from `GTDQueries.projectDisplay` (the collapsible "Archived projects · N" disclosure as a tab stop, "Archive project" / "Unarchive project", "archived (just now)", the refusal, "Rename…" through the existing rename sheet with the kit's duplicate-name error, error focus on Retry, "Old flat · archived" labels and picker entries, every "Restore" string as "Unarchive"); the footer shows the account-less line from `SyncStatusDescriber` (its "Sign in to sync" action arrives with X-03 in PR-09); 020 PR-06's "Weekly review · coming later" row kept after Lists (if `SidebarEntries.swift` needs an edit, add it to the manifest and re-run the classifier). *(021-FR-002, 021-FR-009, 021-FR-010, 021-FR-024, 021-FR-025, 021-FR-026, 021-FR-027, 021-FR-028)*
- [x] T107 [US2] Rebind `macos/Sources/BrainBuddyMac/ProjectReviewView.swift`, `QuickCaptureView.swift`, `QuickOpenView.swift` and `VoiceCapture.swift` to `Workspace` and `MacLocalState` (reviews read due state from the sidecar and write marks only there; capture through `Workspace.capture`, never waiting on the network; Smart Add through the kit). *(021-FR-010, 021-FR-023)*
- [x] T108 [US5] Add `macos/Sources/BrainBuddyMac/ProjectMenuCommands.swift` (new): File › "Archive project" for the selected active project, disabled with "Add or clear the current task draft before archiving" while an edit is unsaved or the capture draft is not empty; File › "Unarchive project" for the selected archived project; no shortcut. *(021-FR-024, 021-FR-026)*
- [x] T109 [US2] Delete `macos/Sources/BrainBuddyMac/LocalGTDStore.swift`, `APIClient.swift` and `SmartAddParser.swift` and the tests `macos/Tests/BrainBuddyMacTests/APIClientTests.swift`, `LocalGTDStoreTests.swift` and `SmartAddParserTests.swift`, after checking every row of the XCTest ledger below has its successor in place. *(021-FR-010)*
- [x] T110 [US4] Wire the launch order in `macos/Sources/BrainBuddyMac/BrainBuddyMacApp.swift`, the last code task of the slice (mac-app-host §1 steps 1 – 5): `SingleInstanceGuard` → `LegacyStoreImporter` → `LegacyCookieCleanup` → `WorkspaceHost.make()` → `workspace.load()` (X-09 on `loadError`). Sync triggers come in PR-09. *(021-FR-020, 021-FR-033, 021-FR-029)*
- [x] T111 [P] [US4] Write and observe RED in `frontend/src/pages/__tests__/PrivacyPolicyPage.test.tsx` both new sentences of data-model "Privacy policy" verbatim and the new `LAST_UPDATED`, then make it GREEN in `frontend/src/pages/PrivacyPolicyPage.tsx` (the paragraph under "How long we keep it" after the account-deletion paragraph; the Erasure sentence under "Your rights"). *(021-FR-021, 021-FR-029)*
- [x] T112 [P] [US4] Write the docs: `docs/data-retention.md` gains the rows of data-model E5 (store document, quarantined files, staging file), E7.2 (device state) and E8 (backup, kept previous-version files, import report, legacy cookie, legacy HTTP cache) as written there, the export sentence, and line 40 reads "(mobile, web, CRT, iOS and macOS)"; `macos/README.md` covers Swift 6.2, the kit dependency, `swift test`, and the `BRAINBUDDY_MAC_DATA_DIR` dry run. *(021-FR-021)*
- [ ] T113 [US4] Verify the automated lane: `cd macos && swift build && swift test` on the `macos-app` lane on the exact SHA; `sh ios/scripts/swift-linux.sh test`; the iPhone build of T049 on the `ios-app` lane; `cd frontend && npx vitest run src/pages`; the requirement scan. The landing produces one TestFlight build (its `ios/` paths).
- [ ] T114 [US4] Host lane (the owner), before the owner's own upgrade: quickstart Scenario 6 step 0, the dry run of this build on a copy of the owner's real folder with `BRAINBUDDY_MAC_DATA_DIR`, never signing in; then steps 2.1, 2.2, 2.4 – 2.6 and 2.8 from a real pre-021 build, and Scenario 8; record `specs/021-mac-sync/evidence/manual-macos-upgrade.md` (counts, "adjusted: N", "not carried: 0", yes/no) and every X-06 state with the remembered disclosure, the strings, focus after archive and unarchive and the rename sheet in `specs/021-mac-sync/evidence/manual-macos-archive.md`, committed in a docs-only commit. *(runtime: host)* *(021-FR-020, 021-FR-033, 021-SC-003)*

**Checkpoint**: an upgraded Mac keeps every record, works fully account-less on the kit, and never touches a workspace in use.

---

## Phase 9: Mac sync UI — US1, US3 on the Mac (slice PR-09, ASK)

**Goal**: Sign-in and sign-out (X-03, X-04), the status line and popover (X-01, X-02), the menus (X-07), the trigger source and App Nap activity, the presentation router and its source guard, the Keychain and macOS client identity checks.

**Independent Test**: on the `macos-app` lane the PR-09 test files pass; quickstart Scenario 5 step 4 and Scenario 6 step 2.3 on a host.

Every task here is *(runtime: macOS lane)* except the docs tasks T130 – T131 and the host task T133.

- [x] T115 [P] [US3] Write and observe RED `macos/Tests/BrainBuddyMacTests/SyncStatusLineModelTests.swift` (new): `SyncStatusLineModel` re-describes after 30 s with no snapshot change; the indicator slot keeps its width whether the indicator shows or not; entering an attention state yields exactly one announcement and staying in it none; calm changes are never announced; the sidebar-hidden toolbar item appears only in attention states, carries the status words' accessible name and requests no focus. *(021-FR-012, 021-FR-013, 021-FR-017)*
- [x] T116 [P] [US3] Write and observe RED `macos/Tests/BrainBuddyMacTests/MacPresentationRouterTests.swift` (new), the positive control: each `UserIntent` presents exactly its own surface (X-02, X-03, X-04, the launch notices X-05, X-08, X-09); a sweep of every `SyncLineState` and transition through the status-line model leaves the router untouched. *(021-SC-004, 021-FR-017)*
- [x] T117 [P] [US3] Write and observe RED `macos/Tests/BrainBuddyMacTests/MacPresentationGuardTests.swift` (new): reads the Mac target's sources via `#filePath` and fails when `.sheet(`, `.alert(`, `.confirmationDialog(`, `.popover(isPresented`, `NSAlert`, `NSSound`, `UNUserNotificationCenter`, `NSApp.activate`, `makeFirstResponder` or a `@FocusState` assignment appears outside `MacPresentationRouter.swift` and the allow-list of mac-app-host §8, which the test spells out file by file and region by region (`SignInSheet.swift`, `SignOutConfirmation.swift`, `UpgradeNotice.swift`, the X-08 and X-09 views, `ProjectReviewView.swift`, `QuickCaptureView.swift`, `QuickOpenView.swift`, the marked regions of `ContentView.swift`), and when any allow-listed call's condition reads `SyncSnapshot` or `syncStatus`; a seeded violation in a scratch copy makes it fail. *(021-SC-004, 021-FR-017)*
- [x] T118 [P] [US1] Write and observe RED `macos/Tests/BrainBuddyMacTests/SyncTriggerSourceTests.swift` (new), with a fake clock and a fake path monitor, the mac-app-host §5 table: launch → `start()`; activation → `reloadIfChangedExternally()` then `setForegroundActive(true)`; occlusion to visible → `.foreground`; network back → `networkAvailabilityChanged(true)`; network gone → offline; the kit ticker active for the life of the process; File › "Sync now", popover "Sync now" and "Retry" → `syncNow()`; resign and terminate → `flush()`; the App Nap activity held exactly while an account is linked. *(021-FR-006)*
- [x] T119 [US1] Write and observe RED `macos/Tests/BrainBuddyMacTests/MacSyncFlowTests.swift` (new), against a counting stub `HTTPTransport`: account-less, launch, foreground, 15 s ticks, network-restored and local-change triggers send **zero** requests; after a sign-out the only request is the queued logout; an upgraded account-less host with a seeded pre-021 cookie for `https://api.example.com` sends exactly one bodiless `POST /auth/logout` there and nothing else; sync-category `os.Logger` lines with sentinel titles hold no sentinel, email or host; sign-in; the account-switch refusal when "Sign in again" resolves to a different account id while changes wait, and when the same owner id is on another server, nothing sent (US4-5); sign-out with 3 unsent changes where a quick capture arrives before confirm signs nothing out and re-presents X-04 with 4, and a plain "Sign out" refused by the kit re-presents it; with an unsaved task edit, "Sign out…" first shows the existing discard confirmation; `WorkspaceHost` uses the service `app.brainbuddy.mac.session` and a spy store sees every token-store call off the main thread; with `BRAINBUDDY_MAC_DATA_DIR` set and the spy store seeded with a token and a pending logout, launch, foreground, 15 s ticks and network-restored triggers make no token-store call and send nothing, and a sign-in started in the dry run is the first call (mac-app-host §1); requests carry `X-Client: brainbuddy-macos/<version>`. *(021-FR-001, 021-FR-004, 021-FR-005, 021-FR-018, 021-FR-029, 021-FR-030, 021-FR-031)*
- [x] T120 [P] [US1] Write and observe RED `macos/Tests/BrainBuddyMacTests/MacKeychainTests.swift` (new): each test creates and unlocks a temporary keychain (`SecKeychainCreate` in the test's temporary folder, random password) and fails, never skips, if it cannot; via the macOS-only initializer: set, read, update, remove, add and remove a pending logout; the item is not synchronizable; a non-interactive read of an item whose access is refused is treated as no token with no prompt; delete-and-re-add after a refused interactive write; the login keychain is never touched. *(021-FR-005)*
- [x] T121 [P] [US2] Write and observe RED `macos/Tests/BrainBuddyMacTests/MacPrivacyGuardTests.swift` (new): the voice sources (`VoiceCapture.swift` and the `VoiceTranscriber` actor) contain no `URLSession`, `import Network` or `BrainBuddyAPI`. *(021-FR-029, 021-FR-010)*
- [x] T122 [US3] Make T115 GREEN in `macos/Sources/BrainBuddyMac/SyncStatusLine.swift` (new; `SyncStatusLineModel` over `SyncStatusDescriber` and `SyncActivityIndicator`; X-01 in every state: one line of 11 pt secondary text, the reserved indicator slot with a static glyph under Reduce Motion, at most one trailing action, wrapping after " · ", accessible name "Sync status: … Show details", the tooltip, one polite announcement on entering an attention state, the sidebar-hidden toolbar item in attention states only). *(021-FR-012, 021-FR-013, 021-FR-014, 021-FR-015)*
- [x] T123 [US3] Make the X-02 popover in `macos/Sources/BrainBuddyMac/SyncStatusPopover.swift` (new): non-modal, at most 480 pt tall with an internal scroll; last sync, waiting count and oldest age or the first-upload line; issues from `SyncIssueDescriber` with "Copy" and "Dismiss" (`Workspace.dismissIssue`), the kept outcome in full with "Copy outcome" and "Discard outcome" ("Discard your outcome for “<project>”") then "Outcome discarded · Undo" for 5 s; "Sync now" (shown disabled, never hidden, when the session ended or offline); the email and "Sign out…"; the backup, import-report and earlier-version lines with "Show in Finder"; the Tab order, focus on open, focus after Dismiss and Esc / click-outside of mac-app-host §6. *(021-FR-015, 021-FR-016, 021-FR-021, 021-FR-033)*
- [x] T124 [US3] Make T116 GREEN in `macos/Sources/BrainBuddyMac/MacPresentationRouter.swift` (new): the only presenter, taking `UserIntent` values only, with no `SyncSnapshot` input. *(021-SC-004, 021-FR-017)*
- [x] T125 [US1] Make the sign-in part of T119 GREEN in `macos/Sources/BrainBuddyMac/SignInSheet.swift` (new; X-03 in every state: the first-sign-in info box when the outbox holds account-less data, wrong password, 429 / 5xx, offline, "sign in again" with the email locked, account switch refused with `accountSwitchRefused` and `.mac`, "no answer", "couldn't save sign-in" with Ref; fields read-only while "Signing in…" with Cancel and Esc enabled, a late reply's session ended; the Keychain prompt allowed only here; focus on close to the opener or the X-01 words; the "account deletion cancelled" note before closing). *(021-FR-001, 021-FR-003, 021-FR-004, 021-FR-005, 021-FR-015, 021-FR-017)*
- [x] T126 [US1] Make the sign-out part of T119 GREEN in `macos/Sources/BrainBuddyMac/SignOutConfirmation.swift` (new; X-04 in every state: `signOutUnsent` or `signOutNothingUnsent`, then `signOutIssues(n)`, then `signOutBackup` (dated, or undated after the date while this sign-out keeps the backup) or `signOutBackupRemoved`; "Cancel" default; the unsaved-edit guard first; re-presented when the count changed; "Couldn't sign out" when the removal fails; afterwards selection to Inbox, the account-less footer, `signedOutSinceImport = true` and the backup retention check). *(021-FR-005, 021-FR-018, 021-FR-021)*
- [x] T127 [US1] Add `macos/Sources/BrainBuddyMac/SyncMenuCommands.swift` (new; X-07: File › "Sync now" ⌘R following `syncNowEnabled`, single-flight, also while typing; app menu "Sign in…", "Sign in again…", "Sign out…"). *(021-FR-006, 021-FR-001)*
- [x] T128 [US1] Make T118 GREEN in `macos/Sources/BrainBuddyMac/SyncTriggerSource.swift` (new; the §5 table, `NWPathMonitor`, the kit `PeriodicSyncTicker` active for the life of the process, `ProcessInfo.beginActivity(options: .userInitiatedAllowingIdleSystemSleep, reason: "Keeping Brain Buddy in sync")` while an account is linked, ended at sign-out). *(021-FR-006)*
- [x] T129 [US1] Make T119 – T121 GREEN across `macos/Sources/BrainBuddyMac/WorkspaceHost.swift` (non-interactive background Keychain reads, every Keychain call off the main actor, the macOS client identity version), `macos/Sources/BrainBuddyMac/ContentView.swift` (the footer becomes `SyncStatusLine`, the sidebar-hidden toolbar item, an empty list reads "Your tasks are still arriving." while "Not synced yet" holds after a sign-in instead of its celebratory empty copy (`popoverFirstLoadEmpty`), the person-started presentations inside the marked regions the guard allows) and `macos/Sources/BrainBuddyMac/BrainBuddyMacApp.swift` (`SyncMenuCommands`, `ProjectMenuCommands`, launch step 6 `SyncTriggerSource.start()`). *(021-FR-001, 021-FR-005, 021-FR-006, 021-FR-012, 021-FR-017, 021-FR-031)*
- [x] T130 [P] [US1] Write `docs/native-macos-app.md` (new): the kit adoption, the files and their lifetimes, the login-keychain disposition (Time Machine and Migration Assistant carry it; removing `app.brainbuddy.mac.session` in Keychain Access after a refused prompt), "Sign in again" after an ad-hoc rebuild, the timestamp limit after the first sign-in, the App Nap activity, the dry run. *(021-FR-005)*
- [x] T131 [P] [US1] Update `AGENTS.md` (one line: the Mac app is a kit client; research R22), `macos/README.md` (signing in, the Keychain prompt) and `docs/data-retention.md` (the macOS session-token row of data-model E9 as written there). *(021-FR-005)*
- [ ] T132 [US1] Verify the automated lane: `cd macos && swift test` on the `macos-app` lane on the exact SHA (`MacKeychainTests` must run, not skip); `sh ios/scripts/swift-linux.sh test`; the requirement scan.
- [ ] T133 [US3] Host lane (the owner): quickstart Scenario 5 step 4 and Scenario 6 step 2.3 on the landed build, recorded in `specs/021-mac-sync/evidence/manual-macos-status.md` (the SC-004 sweep with no dialog and no focus change; VoiceOver for X-01 – X-05; keyboard order; Reduce Motion; large sidebar text; scroll, selection and focus kept during an incoming change; the row under the pointer; the covered-window cadence; the sidebar-hidden item; the Keychain item present and no token in files; the rebuild prompt only at sign-in; X-02 Tab order in three states; "Discard outcome" and Undo; X-09; the account switch refusal; sleep and wake), committed in a docs-only commit. *(runtime: host)* *(021-SC-004, 021-FR-009, 021-FR-006)*

**Checkpoint**: the Mac signs in and syncs in the background, and speaks only when something is wrong.

---

## Phase 10: Polish — release gates (slice PR-10, ASK)

**Purpose**: Turn on the minimum gate: requirement coverage, the owner week, the full verification. T134, T135 and T138 are deferred (owner decision 2026-10-07).

- (deferred) T134 Write and observe RED `scripts/test_check_manual_evidence.py` (new): matching and differing tree hashes; a squash-equivalent record passes; each forbidden pattern (`/Users/`, `~/Library`, `Keychains/`, a 32-hex run outside the header's tree-hash fields, an email not ending in `@example.com`, a non-Markdown file under `specs/021-mac-sync/evidence/`) fails; a missing header or per-state checklist fails; the full Keychain round-trip line is demanded when `MacKeychainTests` is disabled by a visible trait; SC-007 reported as pending until `owner-week.md` holds seven dated entries, the template never counting. *(021-SC-007)*
- (deferred) T135 Make T134 GREEN in `scripts/check_manual_evidence.py` (new; plan "Evidence protocol"). *(021-SC-007)*
- [ ] T136 Add to the `check-specs` recipe in `Makefile`, beside the 019 line and 020's: `python3 scripts/check_requirement_coverage.py specs/021-mac-sync --requirements` with every FR and SC id except SC-007 (no manual-evidence checker: T134 and T135 are deferred); re-record `.specify/gate-integrity.json` with `python3 scripts/check_gate_integrity.py --update` in the same commit (`Makefile` is guarded); `python3 scripts/check_gate_integrity.py` and `make check-specs` pass.
- [x] T137 [P] Write `specs/021-mac-sync/evidence/README.md` (the content-free rule and the header format) and `specs/021-mac-sync/evidence/owner-week.md` (the template of quickstart Scenario 9: per day "needed Sync now: yes/no", "saw Mac and iPhone disagree after a minute online: yes/no", the count of sync issues). *(021-SC-007)*
- (deferred) T138 Raise `backend/coverage-floor.json` and `frontend/coverage-floor.json` to the measured values (ratchet only; no coverage suppression in `frontend/src`).
- [ ] T139 Run the full verification on the frozen candidate: `make check-specs`, `make validate-ci`, `make test-backend`, `make test-frontend`, `make test-e2e`, `sh ios/scripts/swift-linux.sh test`, `cd macos && swift test` on the `macos-app` lane, `make verify-all`, and the quickstart scenarios; the Allure quality gate (`maxFailures: 0`) stays unchanged. *(021-SC-001, 021-SC-002, 021-SC-003, 021-SC-004, 021-SC-005, 021-SC-006)*

---

## XCTest ledger (PR-08; plan "XCTest ledger", review c2, G49)

Every one of the 71 XCTest cases in `macos/Tests/BrainBuddyMacTests` at `1092334` gets a
successor or a retirement reason naming where the rule now lives. "Port" means the case is
rewritten in Swift Testing in `OfflineWorkspaceTests.swift` (T105) against `Workspace` and
`MacLocalState`, minus REST paging, which no longer exists (the Mac reads its local
document). Rows the reviewer named are marked **(named)**. T109 deletes the old files only
when every row's successor exists.

| old test (file) | successor or reason |
|---|---|
| `testTerminalDetailDecodesOriginAndTimestamp` (APIClient) | retired: kit `WireDecodingTests` decodes task DTOs with their timestamps |
| `testTaskDetailAndClassificationDecode` (APIClient) | retired: kit `WireDecodingTests` |
| `testTaskDetailDecodesSubtasksAndComments` (APIClient) | retired: kit `WireDecodingTests` |
| `testSubtaskWritesUseSubtaskRevisionAndIdempotency` (APIClient) | retired: kit `GTDCommandSyncTests`, `EndpointRequestTests` |
| `testCommentWritesUseCommentRevisionAndIdempotency` (APIClient) | retired: kit `GTDCommandSyncTests`, `EndpointRequestTests` |
| `testTaskQueryUsesServerFiltersAndDecodesCounts` (APIClient) | retired: lists come from `GTDQueries` over the local document (kit `QueriesListTests`, `QueriesSummaryTests`) |
| `testPriorityFilterReloadsThroughExistingTaskQuery` (APIClient) | retired: filters are local (kit `QueriesListTests`) |
| `testTerminalHistoryQueriesItsOwnState` (APIClient) | retired: kit `QueriesHistoryTests` |
| `testPagingKeepsSubmittedSearchAndDeduplicatesRows` (APIClient) | retired: the REST paging layer no longer exists; search is local (kit `QueriesSearchTests`), the pull pages in the kit (`SyncEnginePullTests`) |
| `testTaskPatchOmitsUnchangedFieldsAndClearsNullableFields` (APIClient) | kit `TaskEditDraftTests` (T036: changed fields only, `null` clears) and `GTDCommandSyncTests` |
| `testTransitionAndClassificationCreationIncludeRevisionAndIdempotency` (APIClient) | retired: kit `SyncEnginePushTests`, `GTDCommandSyncTests` |
| `testCollectionRenameAndTagDeleteSendRevisionsAndIdempotency` (APIClient) | retired: kit `SyncEnginePushTests` |
| `testProjectRenameConflictRefreshesRevisionAndKeepsRequestedName` (APIClient) | retired: kit `SyncEngineConflictTests` (stale revision → refetch, replay, resend) |
| `testSmartAddSendsAtomicClassificationReferences` (APIClient) | retired: Smart Add resolves locally (kit `CapturePlannerTests`, `SmartAddParserTests`); the server gets ordinary creates |
| `testProjectCaptureUsesOneAtomicSmartAddRequest` (APIClient) | kit `WorkspaceCommandTests` `apply([…])` (T047) and port of `testProjectCaptureStaysInInboxAndVisibleInProjectOffline` |
| `testEditorPatchesFieldsBeforeMovingState` (APIClient) | kit `WorkspaceCommandTests` `apply([…])` keeps the order edit → move (T047) |
| `testRevisionConflictLoadsCurrentTaskAndRetriesWithNewRevisionAndKey` (APIClient) | retired: kit `SyncEngineConflictTests` |
| `testUncertainSaveReusesKeyOnlyWhilePayloadIsUnchanged` (APIClient) | retired: the kit outbox owns idempotency keys (`SyncEnginePushTests`, `CompactionPropertyTests`) |
| `testUncertainNestedEditReusesIdempotencyKey` (APIClient) | retired: as above |
| `testReopenRequiresDestinationAndWaitingValueAndKeysFollowPayload` (APIClient) | retired: kit `ReducerTaskTests` (reopen destination and waiting-for validation) |
| `testSmartAddKeyChangesWithDestinationContext` (APIClient) | retired: keys are per outbox operation (kit) |
| `testSubtaskConflictFetchesCurrentRevisionForRetry` (APIClient) | retired: kit `SyncEngineConflictTests` |
| `testCommentConflictLoadsCurrentRevisionWithoutDroppingDraft` (APIClient) | kit `SyncEngineConflictTests` and `TaskEditDraftTests` (the draft survives an incoming change) |
| `testInboxCaptureWithProjectRetainsInboxStateAndOpensProject` (APIClient) | port (T105) |
| `testStructuredValidationErrorRetainsMessageAndReference` (APIClient) | kit `SyncIssueDescriberTests` (T043; non-empty reference id) and `ErrorMappingTests` |
| `testExpiredSessionRetainsDraftUntilSameOwnerSignsIn` (APIClient) | `MacSyncFlowTests` (T119: session ended keeps the outbox; "Sign in again" to the same account sends it) and kit `WorkspaceSessionEndToEndTests` |
| `testOtherAccountDoesNotReceiveSuspendedDraft` (APIClient) | `MacSyncFlowTests` account-switch refusal (T119) and kit `SyncEngineSessionTests` |
| `testSameOwnerIDOnAnotherServerDoesNotReceiveDraft` (APIClient) | `MacSyncFlowTests` "same owner id on another server" (T119); the kit's `isSameAccount` compares id and server |
| `testSignInIsSingleFlight` (APIClient) | `MacSyncFlowTests` sign-in (T119; one request, the sheet read-only while signing in) |
| `testLateSessionRestoreCannotEraseSuccessfulSignIn` (APIClient) | retired: no session-restore path exists (the kit links once); the late-reply rule is `MacSyncFlowTests` / X-03 "a reply after cancel has its session ended" (T125) |
| `testLocalCRUDAndHistorySurviveRestart` (LocalGTDStore) | port (T105; store reopened) |
| `testWaitingCompletionAndReopenSurviveOfflineRestart` (LocalGTDStore) | port (T105) |
| `testSmartAddReplayAndConflictingKeyAfterOfflineRestart` (LocalGTDStore) | retired: the local store's API emulation is gone; the kit outbox persists operations (`WorkspacePersistenceTests`) |
| `testEditedTaskAndNestedCommandReplayOriginalResultAfterRestart` (LocalGTDStore) | retired: as above |
| `testCollectionReplayRetainsOriginalResponseAndRejectsChangedName` (LocalGTDStore) | retired: as above; name uniqueness is kit `ReducerOrganizeTests` |
| `testProjectOutcomePersistsAndRejectsStaleOrReusedCommands` (LocalGTDStore) | kit `ReducerOrganizeTests` (T024) and port of the outcome in `testProjectOverviewShowsOutcomeAndNextOutsideFilteredFirstPage` |
| `testProjectReviewDecisionPersistsAndRejectsStaleOrChangedReplay` (LocalGTDStore) | `MacLocalStateTests` (T094: the mark persists and is invalid once the content stamp changes) |
| `testInboxProjectClarificationIsAtomicAndReplaySafe` (LocalGTDStore) | kit `WorkspaceCommandTests` `apply([…])` (T047) and port of `testInboxClarificationLoadsEveryUnassignedPageAndCreatesProject` |
| `testLocalCollectionAndCommentLengthsMatchEditorLimits` (LocalGTDStore) **(named)** | the limits are the kit's `FieldRules` (kit `ReducerOrganizeTests`, `ReducerChildrenTests`); `OfflineWorkspaceTests` asserts the editor limits equal `FieldRules` (T105); legacy values over them are carried by `ImportCanonicalizerTests` (T039) |
| `testSecondOpenStoreCannotOverwriteNewerOfflineTasks` (LocalGTDStore) | kit `FileDocumentStoreTests` (`flock`) and `SingleInstanceGuardTests` (T095) |
| `testTransitionReplayRejectsChangedWaitingTarget` (LocalGTDStore) | retired: API-emulation replay is gone; kit `ReplayTests` |
| `testCorruptSnapshotIsNeverReplacedByNewWrites` (LocalGTDStore) **(named)** | `UnreadableWorkspaceTests` (T097: an unreadable `store.json` is never overwritten), `LegacyStoreImporterTests` corrupt fixture (T092: legacy bytes unchanged) and kit `WorkspaceLoadTests` |
| `testFailedDiskWriteDoesNotChangeInMemoryState` (LocalGTDStore) | retired: kit `WorkspacePersistenceTests` (a failed write leaves the state) |
| `testProjectArchiveAndRestoreKeepEveryTaskMembership` (LocalGTDStore) | kit `ReducerArchiveTests` (T023) and port of `testArchivedProjectRemainsBrowsableAndCanBeRestoredOffline` |
| `testQuickTitleRenamePreservesTaskContentAndRejectsStaleRevision` (OfflineWorkspace) | port (T105); "stale revision" becomes the `TaskEditDraft` rebase (T036) |
| `testQuickCaptureSavesInboxOfflineWithoutChangingMainDraft` (OfflineWorkspace) | port |
| `testQuickOpenDistinguishesTypesAndFindsTaskBeyondFirstPage` (OfflineWorkspace) | port (no pages) |
| `testLocalWorkspaceOpensAndKeepsTaskAfterRestartWithoutWebSession` (OfflineWorkspace) | port (account-less) |
| `testQuickMoveRequiresWaitingReasonAndPreservesTaskAfterRestart` (OfflineWorkspace) | port |
| `testWaitingReviewLoadsEveryPageAndKeepsFollowUpSeparate` (OfflineWorkspace) | port (no pages) |
| `testReviewedFollowUpIsAtomicAndReplaySafe` (OfflineWorkspace) | port through `apply([…])` |
| `testWaitingReviewReturnAndCancelPersistAcrossRestart` (OfflineWorkspace) | port |
| `testKeepWaitingResumesAfterRestartOrTaskChange` (OfflineWorkspace) | port with `MacLocalState` marks |
| `testSomedayReviewResumesAcrossPagesRestartAndTaskChange` (OfflineWorkspace) | port |
| `testSomedayActivationIsAtomicAndReplaySafe` (OfflineWorkspace) | port through `apply([…])` |
| `testSomedayActivationRetainsArchivedProjectMembership` (OfflineWorkspace) | port (carried membership, kit-commands §3) |
| `testSidebarCountsStayGlobalWhileBrowsingOneProject` (OfflineWorkspace) | port |
| `testProjectOverviewShowsOutcomeAndNextOutsideFilteredFirstPage` (OfflineWorkspace) | port |
| `testProjectReviewLoadsAllActionsAndResumesAfterRestart` (OfflineWorkspace) | port |
| `testProjectReviewRejectsActionsChangedAfterReviewOpened` (OfflineWorkspace) **(named)** | port: the review compares the project's content stamp (`RecordContentForm` + HMAC, T094) taken when the review opened |
| `testInboxClarificationLoadsEveryUnassignedPageAndCreatesProject` (OfflineWorkspace) | port |
| `testProjectCaptureStaysInInboxAndVisibleInProjectOffline` (OfflineWorkspace) | port |
| `testAssigningProjectToInboxTaskOpensProjectAfterSave` (OfflineWorkspace) | port |
| `testArchivedProjectRemainsBrowsableAndCanBeRestoredOffline` (OfflineWorkspace) | port as unarchive, with the "Unarchive" strings and the name-clash refusal |
| `testDeletingViewedTagKeepsQuickCaptureInNextActions` (OfflineWorkspace) | port |
| `testCaptureExplainsWhenSavedTaskIsHiddenByCurrentResults` (OfflineWorkspace) | port |
| `testResolvesCompletedTokensAndSelectedContext` (SmartAddParser) | kit `SmartAddParserTests` (T027, PR-04) |
| `testKeepsLiteralSigilsAndIncompleteTokensInTitle` (SmartAddParser) | kit `SmartAddParserTests` (T027) |
| `testQuotedEscapesUnicodeNamesAndPunctuationCleanup` (SmartAddParser) | kit `SmartAddParserTests` (T027) |
| `testArchivedProjectNameIsShownAndRejectedBeforeCapture` (SmartAddParser) | kit `SmartAddParserTests` (T027, with the "Unarchive … before adding a task to it." copy) |
| `testRequiresNonemptyBoundedTitleAndNames` (SmartAddParser) | kit `SmartAddParserTests` (T027) |

Totals: 30 `APIClientTests`, 14 `LocalGTDStoreTests`, 22 `OfflineWorkspaceTests`, 5 `SmartAddParserTests` = 71.

## Enum-case rule and classifier, re-run for this task list (2026-10-06)

**Enum-case search** (plan "Enum-case rule"; kit-commands §9), run at `1092334` over
`ios/BrainBuddyKit`, `ios/BrainBuddy`, `ios/BrainBuddyWidgets`, `ios/Shared` and `macos`:

- `GTDCommand` (cases added in PR-04): `case .archiveProject` appears in `Reducer.swift`,
  `Compaction.swift`, `Replay.swift`, `Reducer+Replay.swift`, `GTDCommand+Sync.swift`,
  `PushPlanner.swift` and the iPhone app's `ios/BrainBuddy/Screens/Settings/SyncIssuesScreen.swift`
  (exhaustive, no `default`); the other switches of §9 (`SyncEngine+Push.swift`,
  `SyncEngine+Pull.swift`, `StoreDocument+Merge.swift`) have a `default`. Every one is in
  PR-04's paths. The two command generators that build each case by hand,
  `Tests/BrainBuddySyncTests/Support/RandomCommands.swift` and
  `Tests/BrainBuddyCoreTests/TestSupport/CoreFixtures.swift`, are in PR-04 too (T029). No file
  under `ios/BrainBuddyWidgets`, `ios/Shared` or `macos/` switches over `GTDCommand`.
- `GTDValidationError` (PR-04): only `Commands.swift` (`message`); the apps read `.message`
  and the one app `switch` over an error (`SignInSheet.swift:272`) is over `WorkspaceError`
  with a `default`.
- `SyncTrigger.periodic` (PR-05): only `SyncEngine.swift` (`request`).
- `SessionTokenStore` (protocol, PR-05): conformers in `Tests/BrainBuddyAPITests/TestSupport.swift`
  and `SessionTokenStoreTests.swift`; the `interactive` option is added with a default in the
  protocol extension (T063), so neither file changes.

**Classifier**: every slice's full path list below was fed as
`printf '%s\0' <paths> | python3 scripts/classify_path_risk.py --null`; the results are in
the manifest's last `acceptance` line and match the plan.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1, PR-01)**: no dependency; it must land before PR-08.
- **Backend (Phases 2 – 3)**: PR-02 needs 020 PR-02 (landed); PR-03 needs PR-02.
- **Kit (Phases 4 – 5)**: PR-04 needs PR-03 deployed (its traces and TestFlight build); PR-05 lands after PR-04 (its pure status files may be developed beside it).
- **Web, iPhone (Phases 6 – 7)**: deferred (owner decision 2026-10-07); no slice.
- **Mac (Phases 8 – 9)**: PR-08 needs PR-01, PR-05 and 020 PR-06; PR-09 needs PR-08.
- **Polish (Phase 10, PR-10)**: needs PR-09; 020 PR-01 (landed).

### User Story Dependencies

- **US5 (P3, archive)** comes first in delivery because every client needs the server's lossless archive and the kit's rules before the Mac can sync without changing archive behaviour (spec US5 "Why this priority").
- **US1 (P1, sign in and stay in sync)** and **US2 (P1, offline)** are complete on the Mac only with PR-09; their shared logic is tested in the kit by PR-05 (SC-001, SC-002).
- **US3 (P2, compact status)**: the describer in PR-05; the iPhone in PR-07; the Mac in PR-09.
- **US4 (P2, upgrade)**: the import and account-less Mac in PR-08; the first sign-in in PR-09 on rules from PR-04.

### Lanes (slice graph)

```text
PR-01 ───────────────────────────────────────────────┐
PR-02 → PR-03 → PR-04 → PR-05                         │
                              → PR-08 (Mac) ←─────────┘ → PR-09 (Mac sync UI)
PR-09 → PR-10          (PR-06 web and PR-07 iPhone: deferred)
```

### Within Each Slice

- Tests MUST be written and observed failing before implementation
- Models before services; services before endpoints; core before integration
- Host evidence is made on the landed build (or a candidate with identical trees) and committed afterwards in a docs-only commit

### Parallel Opportunities

- PR-01 runs beside every other slice until PR-08.
- Inside PR-02: T008, T009, T010 and T018 in parallel.
- Inside PR-04: lanes (a) – (d) in parallel; (e) after (a) – (c).
- Inside PR-05: T052, T053 and T056 in parallel; T052 – T054 may start beside PR-04.
- Inside PR-08: lane (a) tests T094 – T097 in parallel; lane (b) after lane (a)'s host types exist; T111 and T112 in parallel with both.
- Inside PR-09: T115 – T118, T120 and T121 in parallel.
- Across features: see each slice's `serialize_with` (020 slices writing the same paths).

---

## Parallel Example: PR-04 lanes

```bash
# Four lanes at once (disjoint files; lane (e) waits for (a) – (c)):
Task: "T023 ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ReducerArchiveTests.swift"        # (a) rules
Task: "T030 ios/BrainBuddyKit/Tests/BrainBuddyAPITests/ClientIdentityTests.swift"          # (b) API
Task: "T034 ios/BrainBuddyKit/Tests/BrainBuddySyncTests/ProjectArchiveTraceReplayTests.swift" # (c) traces
Task: "T039 ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ImportCanonicalizerTests.swift"   # (d) helpers
```

---

## Implementation Strategy

### MVP first

The person-visible MVP is US1 + US2 on the Mac, which needs PR-01 – PR-05, PR-08 and PR-09.
Earlier increments are each independently useful and safe:

1. PR-02 → PR-03: lossless archive and unarchive on the server (US5), which the Mac merge needs.
2. PR-04 → PR-05: the shared kit rules and sync logic (US1 – US3, US5); the iPhone keeps building on it.
3. PR-08: the upgraded Mac on the kit, account-less, with nothing lost (US4-1, US4-2, US4-4); the dry run on a copy of the owner's folder before the owner upgrades.
4. PR-09: the Mac signs in and syncs (US1, US2, US3, US4-3, US4-5). **STOP and VALIDATE**: quickstart Scenarios 4 – 6 on hosts.
5. PR-10: the minimum gate on; then the owner week (SC-007, quickstart Scenario 9).

### Parallel Team Strategy

1. One worker per lane: backend (PR-02 → PR-03), CI (PR-01), kit (PR-04 → PR-05), Mac (PR-08 → PR-09).
2. A dependent slice starts from an accepted base, never from a speculative parallel branch.
3. ASK slices (PR-01, PR-02, PR-05, PR-08, PR-09, PR-10) go as PRs with the owner's recorded approval; their automated lanes finish without a person.

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Verify tests fail before implementing
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Avoid: vague tasks, same file conflicts, cross-story dependencies that break independence
- Generated tasks.md is portable planning input only. Do not use it to bypass
  isolated worktrees, TDD, independent review, CI, landing, or release gates.
- Per the founder acceptance's compensating measures (`planning-review.json`), each slice's
  PR description lists the review-c1/c2 dispositions it implements (table below), and a slice
  that changes spec.md, plan.md or a contract beyond the dispositions gets a targeted review
  for that change.
- The founder acceptance of the planning review **expires on 2026-11-05**
  (`planning-review.json` `founder_acceptance.expires_on`). Work on slices left after that
  date continues only after the owner re-accepts or a targeted planning review is re-run
  over the artifacts those slices rely on.
- No AI or paid provider is involved; `/verify-live` is not part of this feature.
- **Rescope, 2026-10-07 (owner decision): the minimal path to "the Mac syncs with the backend".**
  Slices left: PR-01 (merged), PR-02, PR-03, PR-04, PR-05, PR-08, PR-09 and PR-10 reduced to
  the minimum release gate. Slice ids are kept so the review dispositions stay traceable.
  PR-02 and PR-03 stay whole: the Mac's archived projects, outcomes and edits of tasks in
  archived projects cannot sync without the tolerant PATCH, unarchive, `desired_outcome` and
  lossless archive (FR-024 – FR-028; spec US5 "Why this priority"; SC-003, SC-006).
- **Deferred to a follow-up feature (owner decision 2026-10-07)**: PR-06 web archived projects
  and refetch (T066 – T079); PR-07 iPhone status line and archive (T080 – T089); from PR-10 the
  manual-evidence checker (T134, T135) and the coverage-floor raise (T138). The manifest has
  no deferral field, so their text stays in Phases 6, 7 and 10 as "(deferred)" entries instead
  of checklist items: the slice validator then needs no owner for them. `spec.md` is unchanged
  and every requirement still has a kit test, so the coverage scan passes, but the web and
  iPhone halves of FR-019, FR-024 – FR-027, FR-032, SC-001 (Mac ↔ web) and SC-006 wait for the
  follow-up. Dispositions F05, F55, G09, G55, G58 and G65 were discharged only by deferred tasks.

- **PR-08 implementation notes (2026-10-08)**, read with the PR description:
  - **Foundation-only target taken** (review c2, G48): the importer, `mac-local.json`, the
    single-instance lock, `WorkspaceHost`, the launch (`MacLaunch`) and the window's
    `BrainBuddyModel` live in `macos/Sources/BrainBuddyMacCore/` (with `MacFileSystem.swift`
    and `MacLog.swift`), not `BrainBuddyMac/` as T098 – T103 name them; `SidebarEntries.swift`
    moved there too. The manifest lists the paths, the classifier still says SHIP, and PR-09's
    `WorkspaceHost.swift` path follows the move.
  - **Kit change**: `ImportCanonicalizer` (T039, PR-04) gained three fixes found by the
    importer's tests (a closed task that passed through Waiting is reported only when its raw
    waiting value was non-empty; tag display names reach a fixed point; a fast path that keeps
    the 2,000-task import inside its 10 s budget).
  - **Not compiled before CI**: the `BrainBuddyMac` app target (SwiftUI, AppKit, WhisperKit)
    cannot be built on Linux. T090 and T106 – T110 are ticked as written, parse-checked with
    `swiftc -parse` only; their first type-check is the `macos-app` lane of T113.
    `BrainBuddyMacCore` and every Mac test suite ran on Linux in a scratch package
    (`evidence/manual-macos-upgrade.md`, "Agent pre-check on Linux").
  - **`Package.resolved`**: the pins are unchanged; `originHash` was re-recorded by hand as the
    SHA-256 of the new `Package.swift` (the old value matched no committed manifest, and
    `--only-use-versions-from-resolved-file` does not check it).
  - **X-08**: the running copy writes its process id into `.instance.lock`; a second copy brings
    that process forward and falls back to research R6's bundle-id lookup. Quickstart
    Scenario 8 step 2 (a `swift run` copy beside the bundled app shows X-08) does not follow
    from R6 either; the host plan reaches "unreachable" with a lock held by another process.
  - **Rename of an archived project** (X-06): the kit renames an archived project without a
    uniqueness check, so a name another active project has is saved and the next Unarchive is
    refused again, where the design expects the duplicate-name error in the sheet. Left to the
    kit's rule (the Mac re-implements none); recorded in `OfflineWorkspaceTests` and the host
    plan.
  - **A failed import blocks the launch** (Codex review of PR #297): when the import step throws
    (a full disk, a folder that refuses a write), `MacLaunch` stops at an import-failed panel
    with only "Try again" instead of opening an empty workspace, which would turn
    `local-gtd.json` into a "later file" with its first change (E7.1 invariant 4). Housekeeping
    after a terminal decision (first-write record, backup retention) is best effort and repeated
    at the next launch, so it never keeps the workspace closed. `MacLaunchTests` injects the
    failures through `MacFileFaults`.
  - **XCTest ledger**: the rows whose successor is `MacSyncFlowTests` (T119) describe sign-in
    behaviour the account-less Mac no longer has; their kit successors exist and the Mac case
    arrives with sign-in in PR-09.

- **PR-09 implementation notes (2026-10-08)**, read with the PR description:
  - **Logic in the core, views in the app.** As in PR-08, everything the PR-09 tests need is
    Foundation-only in `macos/Sources/BrainBuddyMacCore/`: `SyncStatusLineModel` (T122's model),
    `SyncPopoverModel` (X-02's lines, Tab order, focus rules, the 5 s Undo of "Discard outcome"),
    `SignInFlow` (X-03), `SignOutFlow` (X-04), `SyncTriggerSource` (T128's §5 table, with the
    path monitor and the App Nap activity behind protocols), `MacPresentationRouter` (T124) and
    `MacSyncController`, which the views bind to. The app target keeps the SwiftUI and AppKit
    side: `SyncStatusLine.swift`, `SyncStatusPopover.swift`, `SignInSheet.swift`,
    `SignOutConfirmation.swift`, `SyncMenuCommands.swift`, `MacPresentationRouter+SwiftUI.swift`
    (where the router's state is attached as the popover, sheet and alert, and where routed focus
    requests reach a `@FocusState`) and `SyncTriggerSource+Live.swift` (`NWPathMonitor`, the
    `ProcessInfo` activity, the notifications, termination after `flush()`). The manifest lists
    the paths; the guard's allow-list names the router's two files.
  - **Kit changes** (PR-05's files, Linux-tested): `SyncEngine.linkAccount` ends a session whose
    reply arrives after the sign-in was cancelled and links nothing (X-03 "a reply after cancel has
    its session ended", which the kit did not do), and a sign-in with no answer now carries the
    reference id its request was sent with (X-03 "no answer"); both in `SyncEngineSessionTests`,
    observed RED on the base engine first. `KeychainSessionTokenStore.token(for:)` on macOS also
    reads `errSecAuthFailed` as `accessDenied` ("Sign in again to sync"), as the interactive write
    already did. `Workspace.waitForNetworkUpdates()` is public, for the Mac's trigger tests.
  - **"Sync now" offline with rejected changes**: the kit's `syncNowEnabled` follows the line's
    state, so with issues and no network it is true. X-02, X-07 and Retry also require a network
    and a live session (`SyncPopoverModel.syncNowAvailable`), since X-02 shows every state that
    holds.
  - **Sign-out keeps typed text until it happens**: the window's discard confirmation comes first
    (G28), but the drafts are cleared only once the sign-out succeeded
    (`BrainBuddyModel.didSignOut`), so Cancel in X-04 loses nothing.
  - **Found by `MacKeychainTests` on the `macos-app` lane** (kit fixes, both production bugs on the
    Mac's file-based login keychain): `pendingLogouts()` asked for `kSecReturnData` with
    `kSecMatchLimitAll`, which that keychain refuses with `errSecParam` (-50), so no queued logout
    (offline sign-out, crash recovery, the pre-021 cookie sessions) could ever be listed and sent;
    it now lists the items' attributes and reads each item's data. And a sign-in after a rebuild
    updated the earlier build's item in place (writing data is allowed to any app) but could not
    read it back (its access list trusts the earlier build), so every routine read asked to sign in
    again. The test models "an earlier build's item" as one `/usr/bin/security` created.
  - **Deviation: no delete-and-re-add after a rebuild** (contracts/mac-app-host.md §7 "The Keychain
    prompt" and §8, data-model E9 "Recovery after Deny", kit-commands §4, plan, research R17 still
    describe it). The `macos-app` lane showed macOS refuses to let a build delete an item another
    program created: `errSecInvalidOwnerEdit` (-25244), with no prompt. So on macOS the store
    writes past the earlier build's item instead: a server's session items are accounts `<host>`,
    `<host>#1`, `<host>#2`, …; the highest generation is the session. A routine read of a highest
    item this build may not read is `accessDenied` ("Sign in again to sync", unchanged); a routine
    write never goes past it (`accessDenied`); the person's sign-in adds the next generation (this
    build created it, so it reads back without a prompt; checked, and a failure is "couldn't save
    sign-in") and never writes into the earlier build's item. Removals delete every item this build
    may delete and leave, without failing, an item it may neither read nor delete. The earlier
    build's item stays, unread, until the person deletes it in Keychain Access; its server session
    ends at expiry (FR-005 residual, recorded in `docs/native-macos-app.md` and the data-retention
    row). Pending logouts already follow this: one item per logout, an unreadable one skipped. No
    access prompt is ever raised, so the spec's "may ask once" assumption holds trivially. iOS is
    unchanged (one item per server). `MacKeychainTests` gains "the newest item decides", seven
    tests in all (manual plan K2 and its count updated).
  - **Deviation: X-03 Cancel ends at the link** (design X-03 "loading" and mac-app-host §7 say
    Cancel and Esc stay enabled while "Signing in…" runs). Review P1: the kit checked Cancel only
    in the instant after the login reply, but "Signing in…" also covers the link's write and the
    first sync; a Cancel there sent the sheet back to the form ("sign-in cancelled") while the
    account stayed linked and the first sync uploaded the Mac's tasks. Now the kit's
    `SignInCancellation` decides Cancel against the link exactly once, at the last moment before
    the link's write: a Cancel that comes first links nothing and ends the session the server
    opened (as before); once the link wins, `cancel()` is refused, the sheet stays in
    "Signing in…" with Cancel and Esc disabled (`SignInFlow.Phase.finishing`), the first sync runs
    as a normal signed-in sync, and the sheet closes signed in. So no task is uploaded for a sign-in
    the sheet reports as cancelled, and the sheet never reports as cancelled a link that stuck.
    `Workspace.signIn(serverURL:email:password:cancellation:)` and the new `SyncService`
    requirement default to the previous behaviour; the iPhone's sign-in (the native attempt path)
    is untouched. Tests: `MacSyncFlowTests` "once the account is linked, Cancel never says
    cancelled" (red before the fix: the sheet went back to `.editing` and logged "sign-in
    cancelled"), and in `SyncEngineSessionTests` the Cancel-before-the-link and
    Cancel-during-the-link's-write cases.
  - **Sign-out removes only what X-04 counted** (review P1; kit, so the iPhone too). After the
    count check, `Workspace.signOut` suspends (writer, engine stop, removal, logout) while
    `writesSuspended` blocked only persistence: a command made meanwhile (the Mac's global Quick
    Capture) was accepted into `unpersisted`, never counted, and erased by
    `resetToEmptyLocalWorkspace()`. Now `Workspace.isSigningOut` is set before the first suspension
    and `perform` refuses every command until the sign-out returns, with
    `GTDValidationError.signingOut` ("Brain Buddy is signing out. This wasn't saved; try again in a
    moment."): Quick Capture and the main window show it and keep the typed text, and the same
    capture is taken once signed out. And "Sign out and remove" removes no more than the count it
    was called with: a change another process (an iPhone widget or App Intent) queues meanwhile
    fails the removal check under the store's lock with `unsyncedChanges` and the real count, so
    X-04 (and the iPhone's confirmation) asks again and nothing is removed. Chosen over "abort and
    re-present on any in-process change" because a change after the removal can't re-present
    anything; refusing it is the one way it can't be lost. Tests (`WorkspaceSyncTests`, red before
    the fix): a capture before the removal (both choices) and after it is refused, never silently
    removed; Sign out and remove keeps a change another process queued meanwhile; a failed
    sign-out takes changes again. `MacSyncFlowTests`: a Quick Capture while a confirmed sign-out
    commits (logout held) is refused with words (red before the fix: taken, then erased).
  - **Sign-out removes only the changes X-04 named, by identity** (review P1; kit, so the iPhone
    too). The count bound let a change another process queued pass when one of the counted changes
    was acknowledged meanwhile (same count, different change). The confirmation now captures
    `Workspace.pendingChangeIDs` (Mac `SignOutFlow.Prompt.changes`, the iPhone's Settings dialog)
    and `Workspace.signOut(removing:)` refuses with `unsyncedChanges` whenever a pending change,
    found up front or under the store's lock, is not among them; the count words are unchanged.
    `WorkspaceSyncTests` (red before the fix: the widget's change was removed): confirm {A}, A
    acknowledged and B queued meanwhile, refused, B kept. Follow-up: an edit folded into a named
    unsent change (`OutboxCompactor`) keeps its id, so the identity is now `PendingChange` (id and
    command; `Workspace.pendingChanges`) and such an edit is refused and kept the same way (test red
    before: the folded edit was removed).
  - **X-03 is single-flight across entries** (review P1). The app menu's "Sign in…" while the
    sheet waited for its login replaced the flow without cancelling its request, so two logins
    could race. `MacSyncController.beginSignIn` now keeps an open flow (sheet shown or request on
    its way) and the menu items are disabled meanwhile (`isSignInOpen`). `MacSyncFlowTests` (red
    before the fix: the flow was replaced and a second sheet presented): the first flow, its one
    login, signed in.
  - **Not compiled before CI**: the `BrainBuddyMac` views and `MacKeychainTests` (macOS-only) are
    parse-checked only; their first type-check and run are the `macos-app` lane of T132. T120 and
    T122 – T129 are ticked as written on that basis. The host checks are the PENDING plan
    `evidence/manual-macos-status.md` (T133).

- **PR-10 implementation notes (2026-10-08)**, read with the PR description:
  - **Planning docs brought in line with PR-09 as delivered** (docs only): plan, research R17, data-model E9, contracts (mac-app-host §7/§8, kit-commands §4), design X-03/X-04, quickstart and `docs/native-macos-app.md` now describe the numbered Keychain items, Cancel decided once at the link, single-flight sign-in and sign-out by identity; the PR-09 notes above record the deviations.
  - **T136 is not wired and stays unchecked.** The non-waivable invariant "no slice-filtered
    requirement coverage in the gates" in `scripts/check_gate_integrity.py` (a `MustNotMatch`
    for `--requirements\b` in `Makefile`, and a twin for `.github/workflows/ci.yml`) forbids the
    line as T136 words it, so `Makefile` and `.specify/gate-integrity.json` are untouched. The
    same block blocked 020's T166, which also stays partial. No allowed form achieves the intent
    either: the unfiltered `python3 scripts/check_requirement_coverage.py specs/021-mac-sync`
    (run on the base `3b76fb0`) reports 39 of 40 ids traced and fails on `021-SC-007` alone, the
    owner's week, which no test can name honestly. Tracing it with a placeholder test, editing
    an invariant, or hiding the id would each defeat the gate. **Owner decision needed**: (a)
    skip the 021 gate for now, as for 020; (b) amend the invariant in an ASK change that allows
    `--requirements` with an exhaustive id list, with its own tests; or (c) land
    `scripts/check_manual_evidence.py` (T134, T135, deferred) so that the unfiltered gate can
    pass with SC-007 reported pending.
  - **T137 done.** `evidence/README.md` indexes the three manual plans
    (`manual-macos-upgrade.md`, `manual-macos-archive.md`, `manual-macos-status.md`) and
    `owner-week.md`, states the content-free rule and the header format, and records the owner's
    decision of 2026-10-08 (manual checks follow the merge, the owner's agent runs them on the
    owner's Mac, a failure is fixed in a separate PR). `evidence/owner-week.md` is the PENDING
    template of Scenario 9: seven dated rows, "needed Sync now", "saw Mac and iPhone disagree
    after a minute online" and the count of sync issues.
  - **T139 stays unchecked: the Linux part is green, the rest is pending.** Run on the PR-10
    candidate (the tree of `3b76fb0` plus these docs), Linux worktree, no live provider:

    | Command | Result |
    |---|---|
    | `make check-specs` | exit 0; `Requirement coverage passed: 33/33 traced` (019) and `20/20 traced` (024); gate integrity passes |
    | `make validate-ci` | exit 0; 14 unittest modules `OK`; `mutation-scope: 5 enforced file(s) within 10 observed file(s)`; `trunk-ci validation passed` |
    | `PATH=/usr/local/bin:$PATH make test-backend` | exit 0; `5037 passed, 2074 warnings in 2383.93s`; `backend coverage meets its floor: branch 95.96%, line 98.76%`; `backend-pytest: taxonomy OK for 5037 Allure result file(s)` |
    | `make test-frontend` | exit 0; `Test Files 90 passed (90)`, `Tests 2248 passed (2248)`; `frontend coverage meets its floor: branches 97.84%, functions 98.94%, lines 99.51%, statements 99.01%`; `frontend-vitest: taxonomy OK for 2248 Allure result file(s)` |
    | `sh ios/scripts/swift-linux.sh test` | exit 0; `Test run with 994 tests in 95 suites passed after 82.048 seconds` (Swift 6.2 Linux image) |
    | `python3 scripts/check_requirement_coverage.py specs/021-mac-sync` | exit 1: `Requirement coverage FAILED: 1 of 40 requirements have no test naming them: 021-SC-007`; the other 39 ids ok (see T136) |
    | `make test-e2e` | not run: it builds a compose stack with Playwright browsers and the modern-auth server, which this worktree cannot start |
    | `make verify-all` | not run: it includes `test-e2e` and the macOS lanes |
    | `cd macos && swift test`, the `macos-app` job (including `MacKeychainTests`, which must run, not skip) | CI lane on the candidate SHA, pending |
    | Quickstart scenarios that need a Mac (5 step 4, 6, 8) and the iPhone | host plans `evidence/manual-macos-*.md`, PENDING; they follow the merge (owner's decision of 2026-10-08) |
    | Scenario 9, the owner's week (021-SC-007) | `evidence/owner-week.md`, PENDING |

    The Allure quality gate (`maxFailures: 0` in `allurerc.mjs`) and the coverage floors are
    unchanged. T139 is ticked when the CI lanes are green on the final SHA and the e2e run is
    recorded.

## Disposition traceability

Every disposition of [review-c1-disposition.md](review-c1-disposition.md) and
[review-c2-disposition.md](review-c2-disposition.md) that needs code, test or doc work maps
to at least one task; "artifacts" means it was discharged in the planning artifacts
themselves.

**Campaign 1**

| ids | tasks |
|---|---|
| F01 (PR-05 is ASK) | manifest classes (PR-05 ASK) |
| F02 (import never overwrites a workspace in use) | T093, T099, T110 |
| F03, F37 (merge keeps memberships) | T025, T048, T050 |
| F04, F34 (kept outcome in full) | T025, T043, T123 |
| F05 (web refetch of tags and detail) | T068, T073, T074 |
| F06, F54 (sign-out names open issues) | T052, T085, T126 |
| F07, F17 (30 s pull age, worst-phase SC-001) | T054, T060, T086, T103 |
| F08, F10, F35 (X-08 copy) | T095, T101 |
| F09 (FR-032 tested) | T056, T068, T078, T086 |
| F12 (`.periodic` no-op) | T057, T062 |
| F13 (failing vs offline) | T052, T055 |
| F14 (repeat archive keeps the marker) | T007, T020, T023, T035 |
| F15 (archived meets archived) | T025, T048 |
| F16 (the 60 s attempt) | T055, T061 |
| F18 (kit ticker) | T056, T062 |
| F19 (draft, anchors) | T036, T047, T106 |
| F20 (review-mark stamps) | T038, T048, T094, T100 |
| F21, F45, F61 (trace copy in PR-04, byte equality) | T033 |
| F22 (presentation router) | T116, T124 |
| F23 (`projectDisplay`, archive evidence) | T040, T041, T114 |
| F24 (`MacSyncFlowTests`) | T119 |
| F25, F39 (Keychain on macOS) | T063, T120, T125 |
| F26, F42 (retention rows) | T112, T131 |
| F27, F62 (backup sentence and line) | T052, T123, T126 |
| F28, F29 (sign-in Cancel, no answer, focus return) | T125 |
| F30 (focus after Dismiss) | T123 |
| F31 (File-menu archive, disclosure tab stop) | T106, T108 |
| F32 (unarchive refused: name in use) | T023, T070, T082, T106 |
| F33 (first-upload age) | T052, T059 |
| F36 (legacy cookie) | T096, T102 |
| F38, F43, F49, F58 (no compaction, skipped records, global order) | T091, T092, T098, T099 |
| F44 (422 on `GET /projects`) | T012, T016 |
| F46 (verbatim catalogue) | T052 |
| F47 (PR-08 lanes) | Phase 8 lanes, T110 |
| F48 (Swift ids before 020 PR-01) | moot on `main` (see "Deviations"); manifest scans |
| F50, F57 (correlation id shape) | T009, T017 |
| F51 (privacy sentinel over the import) | T092 |
| F52, F53 (Sync now disabled not hidden; "Last tried") | T052, T123 |
| F55 (iPhone reference id path) | T081, T085 |
| F59 (sign-out order) | T059, T063 |
| F60 (refused unarchive reverts at once) | T044, T050 |
| F11, F40, F41, F56, F63 | artifacts |

**Campaign 2**

| ids | tasks |
|---|---|
| G01 (enum cases and their switches) | T028, T043, T049, T051 |
| G02 (canonical import) | T039, T042, T091, T092, T098 |
| G03 (FR-007 list) | T060 |
| G04, G17 (pointer hold) | T037, T041, T106, T133 |
| G05 ("couldn't carry over" copy) | T099 |
| G06, G10, G33 (decision table) | T093, T099 |
| G07, G64 (cadence while hidden, App Nap) | T118, T128, T133 |
| G08 (the one accepted reorder) | T092 |
| G09 (parity manifest in PR-06) | T067, T074 |
| G11, G61 (sign-out order, crash window) | T059, T063 |
| G12, G32 (outcome after merge; Discard outcome) | T025, T026, T048, T123 |
| G13, G50 (content form, keyed digests) | T038, T041, T094, T100 |
| G14 (Keychain write failure) | T058, T063 |
| G15, G26 (X-09, staging and quarantined files) | T093, T097, T103 |
| G16 (source guard) | T115, T117 |
| G18, G19, G47, G54 (evidence protocol, lanes) | T080, T089, T114, T133, T134, T135 |
| G20 (PR-04 lanes) | Phase 4 lanes |
| G21 (golden import artifact) | T092, T104 |
| G22 (first load, budgets) | T059, T092, T114 |
| G23 (privacy policy) | T111 |
| G24, G39, G63 (backup removal never silent) | T052, T093, T100, T126 |
| G25, G52, G60 (cookie hosts, HTTP cache, one logout) | T096, T102, T119 |
| G27 (X-02 Tab order) | T123, T133 |
| G28 (unsaved-edit guard, count changed) | T119, T126 |
| G29 (sidebar hidden) | T115, T122, T129 |
| G30 (rename archived project) | T069, T082, T106 |
| G31 (D-01 and X-06 focus) | T070, T106 |
| G34 (Keychain prompt) | T063, T120, T125 |
| G40 (account switch trigger) | T119 |
| G42, G44, G53 (one-pass counts, check order, owner scope) | T007, T010, T014 |
| G45 (web window) | T022 |
| G46 (foreground in one call) | T059, T064, T086 |
| G48 (importer target) | Phase 8 note |
| G49 (XCTest ledger) | ledger above, T105, T109 |
| G51 (retention doc gaps) | T112 |
| G55, G58 (M-01 rows, 44 pt, VoiceOver copy) | T081, T085 |
| G56 (first-load empty list) | T129 |
| G57 (partial-failure copy) | T043 |
| G59 (X-03 "OK") | T125 |
| G62 (forward-only rollback, clearing-server guard) | T018, T044, T050 |
| G65 (web picker) | T072, T077 |
| G35, G36, G37, G38, G41, G43 | artifacts (G43's "kept, now tested" cases: T030, T057) |

**`/speckit-checklist` fixes (2026-10-06)**

| checklist item | tasks |
|---|---|
| privacy CHK004 (Keychain item outlives the app) | T131 |
| privacy CHK016 (backup retention row) | T112 |
| privacy CHK026 (dry run touches nothing outside its copy) | T096, T102, T103, T119 |
| offline-sync CHK032 (020 serialization) | manifest `serialize_with` |
| ux-a11y CHK004 (X-09 Escape) | T103 |
| ux-a11y CHK005 (toolbar item name) | T115, T122 |
| ux-a11y CHK016 (guard allow-list) | T117 |
| ux-a11y CHK017 ("· archived" label) | T106, T072 |
| ux-a11y CHK018 (rename error copy) | T069, T082, T106 |

## PR-срезы

**Draft, awaiting the owner's approval of the file-level map** ("PR slice map status"
above). A delivery boundary only: each slice still needs its own worktree, failing tests
first, independent review, CI and ADR-0008 landing; approval is not authorization to merge
or deploy. Each slice's landing class is the last `acceptance` entry, with the classifier's
result over the slice's full `paths` list in parentheses (`printf '%s\0' <paths> | python3
scripts/classify_path_risk.py --null`, run on 2026-10-06 over this manifest); the final class
is the stricter of the mechanical and the semantic class (plan "Delivery slices").
`depends_on` follows plan "Delivery slices" and the lane graph above. `external_depends_on`
names the 020 slices that must have landed first (`020-weekly-review/PR-NN`; 020 PR-01 and
PR-02 have, 020 PR-06 has not), and `serialize_with` names the 020 slices the plan orders
against this one: those that write a path this slice writes, plus the further 020 kit and web
slices the plan's table lists for PR-04, PR-05 and PR-06 (plan "Parallelism with 020's
waves"; either order, the second rebases). `scripts/check_spec_kit_specs.py` ignores those two fields.

```json
{
  "schema_version": "brainbuddy-pr-slices/v1",
  "slices": [
    {
      "id": "PR-01",
      "outcome": "macOS CI lane and report tooling: the macos-app job (needs only changes, every step gated on the macos change output, never a job-level if) in full-ci and allure-report, registered in the CI-artifact validator with tests; SCREEN_ID_RE widened to X- screens with a test (design gap G-7).",
      "tasks": ["T001", "T002", "T003", "T004", "T005"],
      "requirements": ["021-FR-005", "021-SC-004"],
      "paths": [
        "scripts/test_validate_ci_artifacts.py",
        "scripts/validate_ci_artifacts.py",
        ".github/workflows/ci.yml",
        "scripts/test_render_feature_report.py",
        "scripts/render_feature_report.py"
      ],
      "depends_on": [],
      "external_depends_on": [],
      "serialize_with": [],
      "tests": [
        "python3 -m unittest scripts/test_validate_ci_artifacts.py scripts/test_render_feature_report.py",
        "make validate-ci",
        "python3 scripts/check_spec_kit_specs.py"
      ],
      "acceptance": [
        "each malformed macos-app workflow fixture of T001 is rejected and the complete one passes",
        "the macos-app lane runs today's 71 XCTest cases green on the exact SHA; full-ci and allure-report need it",
        "render_feature_report counts X-01, X-09, M-01 and D-01 as four screen ids",
        "owner's recorded ASK approval on the PR (.github/ and scripts/); per-slice requirement scan not applicable (no product test in this slice: it carries the macOS-lane evidence for 021-FR-005 and 021-SC-004)",
        "landing class ASK (scripts/classify_path_risk.py: ASK)"
      ]
    },
    {
      "id": "PR-02",
      "outcome": "Backend tolerant contract: PATCH accepts a carried archived membership; GET /projects?state= (owner-scoped, open counts in one pass, 422 on a bad state); POST /projects/{id}/unarchive (already active checked before the revision); desired_outcome; archived_at and archived_before_lossless with the startup step; archive still clears memberships and sets the marker, a repeat archive keeps it; X-Client log fields and the validated incoming correlation id; API contract map; golden traces (PR-02 behaviour); Allure rules; the api-compatibility client note with the forward-only rollback rule; the data-retention outcome wording.",
      "tasks": ["T006", "T007", "T008", "T009", "T010", "T011", "T012", "T013", "T014", "T015", "T016", "T017", "T018", "T019"],
      "requirements": ["021-FR-015", "021-FR-025", "021-FR-026", "021-FR-027", "021-FR-028", "021-FR-030", "021-FR-031"],
      "paths": [
        "backend/tests/allure_taxonomy.py",
        "backend/tests/test_project_archive_lossless_api.py",
        "backend/tests/test_project_desired_outcome_api.py",
        "backend/tests/test_client_attribution_logging.py",
        "backend/tests/fixtures/project_archive_traces.json",
        "backend/tests/test_project_archive_traces.py",
        "backend/tests/test_api_contract.py",
        "backend/tests/test_task_branch_coverage.py",
        "backend/tests/test_account_export.py",
        "backend/tests/test_account_deletion.py",
        "backend/app/modules/tasks/domain.py",
        "backend/app/schemas/tasks.py",
        "backend/app/modules/tasks/service.py",
        "backend/app/modules/tasks/repository.py",
        "backend/app/api/tasks.py",
        "backend/app/api/middleware.py",
        "docs/api-compatibility.md",
        "docs/data-retention.md"
      ],
      "depends_on": [],
      "external_depends_on": ["020-weekly-review/PR-02"],
      "serialize_with": ["020-weekly-review/PR-07", "020-weekly-review/PR-09", "020-weekly-review/PR-15"],
      "tests": [
        "cd backend && pytest --no-cov tests/test_project_archive_lossless_api.py tests/test_project_desired_outcome_api.py tests/test_client_attribution_logging.py tests/test_project_archive_traces.py tests/test_api_contract.py tests/test_task_branch_coverage.py tests/test_account_export.py tests/test_account_deletion.py -q",
        "make test-backend",
        "python3 scripts/check_requirement_coverage.py specs/021-mac-sync --requirements 021-FR-015,021-FR-025,021-FR-026,021-FR-027,021-FR-028,021-FR-030,021-FR-031"
      ],
      "acceptance": [
        "quickstart Scenarios 1 (steps 2 - 8 and 10 - 12 with PR-02 behaviour), 2 and 3 pass against api_client and second_api_client",
        "archive still clears every member's project_id and sets archived_before_lossless: true; GET /projects without state returns the same projects in the same order as before",
        "log capture: no raw X-Client value, no forged correlation field, no sentinel project name or outcome in any record",
        "make test-backend green (coverage floor, Allure taxonomy validator)",
        "owner's recorded ASK approval (backend/app/api/tasks.py, backend/app/api/middleware.py)",
        "landing class ASK (scripts/classify_path_risk.py: ASK)"
      ]
    },
    {
      "id": "PR-03",
      "outcome": "Lossless archive (ADR-0020): archiving keeps every task's project membership, sets archived_at and clears the marker; repeat archive unchanged; the clearing assertions flipped; the golden traces updated to lossless (backend only).",
      "tasks": ["T020", "T021", "T022"],
      "requirements": ["021-FR-024", "021-FR-027", "021-SC-006"],
      "paths": [
        "backend/tests/test_task_api.py",
        "backend/tests/test_task_lifecycle_detail_api.py",
        "backend/tests/test_task_tag_project_mvp_api.py",
        "backend/tests/test_project_archive_lossless_api.py",
        "backend/tests/fixtures/project_archive_traces.json",
        "backend/app/modules/tasks/service.py"
      ],
      "depends_on": ["PR-02"],
      "external_depends_on": [],
      "serialize_with": ["020-weekly-review/PR-15"],
      "tests": [
        "cd backend && pytest --no-cov tests/test_project_archive_lossless_api.py tests/test_project_archive_traces.py tests/test_task_api.py tests/test_task_lifecycle_detail_api.py tests/test_task_tag_project_mvp_api.py -q",
        "make test-backend",
        "python3 scripts/check_requirement_coverage.py specs/021-mac-sync --requirements 021-FR-024,021-FR-027,021-SC-006"
      ],
      "acceptance": [
        "quickstart Scenario 1 steps 1 and 9: every member task (open, completed, cancelled) keeps project_id with no revision or updated_at change; the project gets archived_at and archived_before_lossless: false",
        "test_021_SC_006_archive_and_unarchive_keep_every_membership green; the golden traces are lossless and pass against the real API",
        "the web page for archived projects (former PR-06) is deferred, so the web shows a task in a project archived from now on as \"No project\" until the follow-up (review c2, G45); no membership is lost",
        "landing class SHOW (scripts/classify_path_risk.py: SHIP; semantic SHOW: cross-client behaviour change)"
      ]
    },
    {
      "id": "PR-04",
      "outcome": "Kit contract: project records and commands (desired outcome, unarchive), the ADR-0020 reducer rules incl. repeat archive, the merge table and the outcome rule, Smart Add copy, SyncIssueDescriber with the iPhone SyncIssuesScreen delegating to it, ClientIdentity, the listProjects(state:) pull with its fallback, the unarchive push with the immediate revert on 409, the clearing-server guard, Workspace.unarchiveProject / setProjectOutcome / apply([...]), the pure helpers TaskEditDraft, SelectionAnchor, RecordContentForm, ListPresentationHold, ImportCanonicalizer and projectDisplay, the fake server and the byte-identical trace copy with its replay, the Mac Smart Add parser cases ported, and every exhaustive switch over the new cases (enum-case rule).",
      "tasks": ["T023", "T024", "T025", "T026", "T027", "T028", "T029", "T030", "T031", "T032", "T033", "T034", "T035", "T036", "T037", "T038", "T039", "T040", "T041", "T042", "T043", "T044", "T045", "T046", "T047", "T048", "T049", "T050", "T051"],
      "requirements": ["021-FR-003", "021-FR-008", "021-FR-009", "021-FR-010", "021-FR-011", "021-FR-015", "021-FR-020", "021-FR-023", "021-FR-024", "021-FR-025", "021-FR-026", "021-FR-027", "021-FR-028", "021-FR-031", "021-SC-003", "021-SC-004"],
      "paths": [
        "ios/BrainBuddyKit/Package.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/Records.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/Commands.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/Reducer.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/Reducer+Organize.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/Reducer+Validation.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/Reducer+Replay.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/Replay.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/Compaction.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/SmartAdd+Resolution.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/SyncIssueDescriber.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/TaskEditDraft.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/RecordContentForm.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/ListPresentationHold.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/ImportCanonicalizer.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/Queries+ProjectDisplay.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyAPI/BrainBuddyAPI.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyAPI/BrainBuddyAPIClient.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyAPI/APIError.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyAPI/WireModels.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyAPI/RequestBodies.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddySync/GTDCommand+Sync.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddySync/PushPlanner.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddySync/SyncEngine+Pull.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddySync/SyncEngine+Push.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddySync/StoreDocument+Merge.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyWorkspace/Workspace.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyFakeServer/FakeServer+Organize.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyFakeServer/FakeServer+Tasks.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyFakeServer/FakeServerRecords.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyFakeServer/ServerState.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ReducerOrganizeTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ReducerArchiveTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ReplayTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/CompactionTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/SmartAddParserTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/SyncIssueDescriberTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/TaskEditDraftTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/RecordContentFormTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ListPresentationHoldTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ImportCanonicalizerTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ProjectDisplayTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/TestSupport/CoreFixtures.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyPersistenceTests/StoreDocumentCodingTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyAPITests/EndpointRequestTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyAPITests/WireDecodingTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyAPITests/ClientIdentityTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddySyncTests/ProjectArchiveSyncTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddySyncTests/SyncEnginePullTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddySyncTests/ProjectArchiveTraceReplayTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddySyncTests/Resources/project_archive_traces.json",
        "ios/BrainBuddyKit/Tests/BrainBuddySyncTests/Support/RandomCommands.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/WorkspaceCommandTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/FirstSignInMergeTests.swift",
        "backend/tests/test_project_archive_traces.py",
        "ios/BrainBuddy/Screens/Settings/SyncIssuesScreen.swift"
      ],
      "depends_on": ["PR-03"],
      "external_depends_on": [],
      "serialize_with": ["020-weekly-review/PR-03", "020-weekly-review/PR-04", "020-weekly-review/PR-08", "020-weekly-review/PR-12"],
      "tests": [
        "sh ios/scripts/swift-linux.sh test",
        "cd backend && pytest --no-cov tests/test_project_archive_traces.py -q",
        "cd ios && xcodegen generate --spec project.yml && xcodebuild -project BrainBuddy.xcodeproj -scheme BrainBuddy -destination 'generic/platform=iOS Simulator' -configuration Debug CODE_SIGNING_ALLOWED=NO build  # ios-app lane",
        "grep -rn 'case .archiveProject' --include=*.swift ios/BrainBuddyKit ios/BrainBuddy ios/BrainBuddyWidgets ios/Shared macos",
        "python3 scripts/check_requirement_coverage.py specs/021-mac-sync --requirements 021-FR-003,021-FR-008,021-FR-009,021-FR-010,021-FR-011,021-FR-015,021-FR-020,021-FR-023,021-FR-024,021-FR-025,021-FR-026,021-FR-027,021-FR-028,021-FR-031,021-SC-003,021-SC-004"
      ],
      "acceptance": [
        "the kit trace copy is byte-identical to backend/tests/fixtures/project_archive_traces.json (pytest) and every trace replays against BrainBuddyFakeServer with the same statuses and bodies",
        "quickstart Scenario 4 steps 1, 5, 7, 8, 9 and 11 pass against the fake server",
        "the enum-case search finds only files in this slice's paths; the iPhone app builds on the ios-app lane on the exact SHA",
        "the landing produces one TestFlight build",
        "landing class SHOW (scripts/classify_path_risk.py: SHIP; semantic SHOW: ships to TestFlight and changes iPhone archive behaviour)"
      ]
    },
    {
      "id": "PR-05",
      "outcome": "Kit status, cadence and session: SyncPresentation (snapshot, describer, timing, copy catalogue incl. the sign-out issue and backup sentences) and SyncActivityIndicator; failingSince, lastFailedAttemptAt and the reference id in SyncMetadata with the 60 s confirmation attempt; .periodic (a no-op when idle) and PeriodicSyncTicker; Workspace.setForegroundActive and syncSnapshot; single-flight syncNow tested; the device-neutral account-switch refusal; the sign-out order through signOut(removingLocalDataWith:) with the pending logout recorded first; the Keychain write failure at sign-in; macOS token-store attributes with non-interactive background reads; the convergence and offline matrix (SC-001, SC-002).",
      "tasks": ["T052", "T053", "T054", "T055", "T056", "T057", "T058", "T059", "T060", "T061", "T062", "T063", "T064", "T065"],
      "requirements": ["021-FR-004", "021-FR-005", "021-FR-006", "021-FR-007", "021-FR-008", "021-FR-011", "021-FR-012", "021-FR-013", "021-FR-014", "021-FR-015", "021-FR-016", "021-FR-018", "021-FR-019", "021-FR-021", "021-FR-032", "021-SC-001", "021-SC-002", "021-SC-004", "021-SC-005", "021-SC-006"],
      "paths": [
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/SyncPresentation.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/SyncActivityIndicator.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/Outbox.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddySync/BrainBuddySync.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddySync/SyncConfiguration.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddySync/SyncEngine.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddySync/SyncEngine+Cycle.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddySync/SyncEngine+Session.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddySync/PeriodicSyncTicker.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyAPI/SessionTokenStore.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyAPI/BrainBuddyAPIClient.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyAPI/APIError.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyWorkspace/Workspace.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/SyncPresentationTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/SyncActivityIndicatorTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddySyncTests/SyncEngineFailingClockTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddySyncTests/SyncEngineSchedulingTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddySyncTests/SyncEngineSessionTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddySyncTests/PeriodicSyncTickerTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/MacIPhoneConvergenceTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/WorkspaceSyncTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/Support/FakeSyncService.swift"
      ],
      "depends_on": ["PR-04"],
      "external_depends_on": [],
      "serialize_with": ["020-weekly-review/PR-03", "020-weekly-review/PR-04", "020-weekly-review/PR-08", "020-weekly-review/PR-12"],
      "tests": [
        "sh ios/scripts/swift-linux.sh test",
        "sh ios/scripts/swift-linux.sh test --filter BrainBuddyWorkspaceTests",
        "cd ios && xcodegen generate --spec project.yml && xcodebuild -project BrainBuddy.xcodeproj -scheme BrainBuddy -destination 'generic/platform=iOS Simulator' -configuration Debug CODE_SIGNING_ALLOWED=NO build  # ios-app lane",
        "python3 scripts/check_requirement_coverage.py specs/021-mac-sync --requirements 021-FR-004,021-FR-005,021-FR-006,021-FR-007,021-FR-008,021-FR-011,021-FR-012,021-FR-013,021-FR-014,021-FR-015,021-FR-016,021-FR-018,021-FR-019,021-FR-021,021-FR-032,021-SC-001,021-SC-002,021-SC-004,021-SC-005,021-SC-006"
      ],
      "acceptance": [
        "quickstart Scenario 4 steps 2 - 4, 6 and 12 - 14 and Scenario 5 steps 1 - 3 pass as kit tests",
        "MacIPhoneConvergenceTests: every FR-007 record type held by the receiver within 60 s at the worst tick phase; the offline matrix puts every change on the server exactly once (021-SC-001, 021-SC-002)",
        "the SyncTrigger enum-case search finds only SyncEngine.swift; the iPhone app builds on the ios-app lane on the exact SHA; the landing produces one TestFlight build",
        "owner's recorded ASK approval (session token store, sign-out order, account-switch refusal)",
        "landing class ASK (scripts/classify_path_risk.py: ASK)"
      ]
    },
    {
      "id": "PR-08",
      "outcome": "Mac adoption, account-less: Swift 6.2 and the kit dependency; WorkspaceHost; SingleInstanceGuard with X-08; X-09 for an unreadable workspace; the one-time legacy import through ImportCanonicalizer with its durable state machine, staging, verification, report, exclusive backup rename and every X-05 state; the golden import artifact and the kit case that signs in with it; MacLocalState review marks; the legacy cookie and HTTP-cache cleanup; a dry run (BRAINBUDDY_MAC_DATA_DIR) that touches no cookie, cache or Keychain item; the views rebound to Workspace with X-06 and the File-menu archive; the old store, REST client and parser removed with the XCTest ledger; data-retention rows, the privacy-policy paragraph; upgrade and archive host evidence.",
      "tasks": ["T090", "T091", "T092", "T093", "T094", "T095", "T096", "T097", "T098", "T099", "T100", "T101", "T102", "T103", "T104", "T105", "T106", "T107", "T108", "T109", "T110", "T111", "T112", "T113", "T114"],
      "requirements": ["021-FR-002", "021-FR-003", "021-FR-005", "021-FR-009", "021-FR-010", "021-FR-017", "021-FR-020", "021-FR-021", "021-FR-022", "021-FR-023", "021-FR-024", "021-FR-025", "021-FR-026", "021-FR-027", "021-FR-028", "021-FR-029", "021-FR-030", "021-FR-031", "021-FR-033", "021-SC-003"],
      "paths": [
        "macos/Package.swift",
        "macos/Package.resolved",
        "macos/Sources/BrainBuddyMac/BrainBuddyMacApp.swift",
        "macos/Sources/BrainBuddyMac/ContentView.swift",
        "macos/Sources/BrainBuddyMac/ProjectReviewView.swift",
        "macos/Sources/BrainBuddyMac/QuickCaptureView.swift",
        "macos/Sources/BrainBuddyMac/QuickOpenView.swift",
        "macos/Sources/BrainBuddyMac/VoiceCapture.swift",
        "macos/Sources/BrainBuddyMac/UpgradeNotice.swift",
        "macos/Sources/BrainBuddyMac/ProjectMenuCommands.swift",
        "macos/Sources/BrainBuddyMac/UnreadableWorkspaceView.swift",
        "macos/Sources/BrainBuddyMac/SidebarEntries.swift",
        "macos/Sources/BrainBuddyMac/LocalGTDStore.swift",
        "macos/Sources/BrainBuddyMac/APIClient.swift",
        "macos/Sources/BrainBuddyMac/SmartAddParser.swift",
        "macos/Sources/BrainBuddyMacCore/BrainBuddyModel.swift",
        "macos/Sources/BrainBuddyMacCore/SidebarEntries.swift",
        "macos/Sources/BrainBuddyMacCore/WorkspaceHost.swift",
        "macos/Sources/BrainBuddyMacCore/SingleInstanceGuard.swift",
        "macos/Sources/BrainBuddyMacCore/MacLocalState.swift",
        "macos/Sources/BrainBuddyMacCore/MacFileSystem.swift",
        "macos/Sources/BrainBuddyMacCore/MacLog.swift",
        "macos/Sources/BrainBuddyMacCore/LegacySnapshot.swift",
        "macos/Sources/BrainBuddyMacCore/LegacyStoreImporter.swift",
        "macos/Sources/BrainBuddyMacCore/LegacyImportDecision.swift",
        "macos/Sources/BrainBuddyMacCore/LegacyCookieCleanup.swift",
        "macos/Tests/BrainBuddyMacTests/OfflineWorkspaceTests.swift",
        "macos/Tests/BrainBuddyMacTests/LegacyStoreImporterTests.swift",
        "macos/Tests/BrainBuddyMacTests/MacLocalStateTests.swift",
        "macos/Tests/BrainBuddyMacTests/SingleInstanceGuardTests.swift",
        "macos/Tests/BrainBuddyMacTests/LegacyCookieCleanupTests.swift",
        "macos/Tests/BrainBuddyMacTests/UnreadableWorkspaceTests.swift",
        "macos/Tests/BrainBuddyMacTests/MacTestSupport.swift",
        "macos/Tests/BrainBuddyMacTests/MacLaunchTests.swift",
        "macos/Tests/BrainBuddyMacTests/WeeklyReviewRowTests.swift",
        "macos/Tests/BrainBuddyMacTests/APIClientTests.swift",
        "macos/Tests/BrainBuddyMacTests/LocalGTDStoreTests.swift",
        "macos/Tests/BrainBuddyMacTests/SmartAddParserTests.swift",
        "macos/Tests/BrainBuddyMacTests/Resources/legacy-populated.json",
        "macos/Tests/BrainBuddyMacTests/Resources/legacy-awkward.json",
        "macos/Tests/BrainBuddyMacTests/Resources/legacy-corrupt.json",
        "macos/Tests/BrainBuddyMacTests/Resources/legacy-newer.json",
        "ios/BrainBuddyKit/Package.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/ImportCanonicalizer.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ImportCanonicalizerTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/FirstSignInMergeTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/Resources/legacy-import-golden.json",
        "frontend/src/pages/PrivacyPolicyPage.tsx",
        "frontend/src/pages/__tests__/PrivacyPolicyPage.test.tsx",
        "macos/README.md",
        "docs/data-retention.md",
        "specs/021-mac-sync/evidence/manual-macos-upgrade.md",
        "specs/021-mac-sync/evidence/manual-macos-archive.md"
      ],
      "depends_on": ["PR-01", "PR-05"],
      "external_depends_on": ["020-weekly-review/PR-06"],
      "serialize_with": ["020-weekly-review/PR-03", "020-weekly-review/PR-07", "020-weekly-review/PR-09", "020-weekly-review/PR-15"],
      "tests": [
        "cd macos && swift build && swift test  # macos-app lane",
        "sh ios/scripts/swift-linux.sh test",
        "cd ios && xcodegen generate --spec project.yml && xcodebuild -project BrainBuddy.xcodeproj -scheme BrainBuddy -destination 'generic/platform=iOS Simulator' -configuration Debug CODE_SIGNING_ALLOWED=NO build  # ios-app lane",
        "cd frontend && npx vitest run src/pages",
        "python3 scripts/check_requirement_coverage.py specs/021-mac-sync --requirements 021-FR-002,021-FR-003,021-FR-005,021-FR-009,021-FR-010,021-FR-017,021-FR-020,021-FR-021,021-FR-022,021-FR-023,021-FR-024,021-FR-025,021-FR-026,021-FR-027,021-FR-028,021-FR-029,021-FR-030,021-FR-031,021-FR-033,021-SC-003"
      ],
      "acceptance": [
        "LegacyStoreImporterTests: every mac-legacy-import §6 case, the golden artifact byte for byte and the 500-seed property test; the rewritten OfflineWorkspaceTests pass on the macos-app lane on the exact SHA",
        "every row of the XCTest ledger has its successor in place before T109 deletes the old files",
        "LegacyCookieCleanupTests: with BRAINBUDDY_MAC_DATA_DIR set, the cookies and the cache entry stay, nothing is queued or sent, and a spy token store records no call during launch steps 3 and 4",
        "host lane before the owner's own upgrade: quickstart Scenario 6 step 0 (the dry run, never signing in), then steps 2.1, 2.2, 2.4 - 2.6 and 2.8 from a real pre-021 build and Scenario 8, recorded in manual-macos-upgrade.md and manual-macos-archive.md in a docs-only commit",
        "owner's recorded ASK approval (one-time migration of real user data, legacy session removal); its ios/ paths produce one TestFlight build",
        "landing class ASK (scripts/classify_path_risk.py: SHIP; semantic ASK)"
      ]
    },
    {
      "id": "PR-09",
      "outcome": "Mac sync UI: X-03 sign-in, X-04 sign-out with the issue and backup sentences and the unsaved-edit guard, X-01 status line in every state, X-02 popover with its focus order and Discard outcome with Undo, X-07 menus and Cmd-R, MacPresentationRouter and the source-level presentation guard, SyncStatusLineModel, SyncTriggerSource with the kit ticker and the App Nap activity, the Keychain service (prompt only at sign-in, calls off the main actor), the macOS client identity; docs/native-macos-app.md, the AGENTS.md line, the Keychain data-retention row; status host evidence.",
      "tasks": ["T115", "T116", "T117", "T118", "T119", "T120", "T121", "T122", "T123", "T124", "T125", "T126", "T127", "T128", "T129", "T130", "T131", "T132", "T133"],
      "requirements": ["021-FR-001", "021-FR-003", "021-FR-004", "021-FR-005", "021-FR-006", "021-FR-009", "021-FR-010", "021-FR-012", "021-FR-013", "021-FR-014", "021-FR-015", "021-FR-016", "021-FR-017", "021-FR-018", "021-FR-021", "021-FR-029", "021-FR-030", "021-FR-031", "021-FR-033", "021-SC-004"],
      "paths": [
        "macos/Tests/BrainBuddyMacTests/SyncStatusLineModelTests.swift",
        "macos/Tests/BrainBuddyMacTests/MacPresentationRouterTests.swift",
        "macos/Tests/BrainBuddyMacTests/MacPresentationGuardTests.swift",
        "macos/Tests/BrainBuddyMacTests/SyncTriggerSourceTests.swift",
        "macos/Tests/BrainBuddyMacTests/MacSyncFlowTests.swift",
        "macos/Tests/BrainBuddyMacTests/MacKeychainTests.swift",
        "macos/Tests/BrainBuddyMacTests/MacPrivacyGuardTests.swift",
        "macos/Tests/BrainBuddyMacTests/SyncStatusPopoverModelTests.swift",
        "macos/Tests/BrainBuddyMacTests/MacTestSupport.swift",
        "macos/Sources/BrainBuddyMac/SyncStatusLine.swift",
        "macos/Sources/BrainBuddyMac/SyncStatusPopover.swift",
        "macos/Sources/BrainBuddyMac/MacPresentationRouter+SwiftUI.swift",
        "macos/Sources/BrainBuddyMac/SignInSheet.swift",
        "macos/Sources/BrainBuddyMac/SignOutConfirmation.swift",
        "macos/Sources/BrainBuddyMac/SyncMenuCommands.swift",
        "macos/Sources/BrainBuddyMac/SyncTriggerSource+Live.swift",
        "macos/Sources/BrainBuddyMacCore/SyncStatusLineModel.swift",
        "macos/Sources/BrainBuddyMacCore/SyncPopoverModel.swift",
        "macos/Sources/BrainBuddyMacCore/MacPresentationRouter.swift",
        "macos/Sources/BrainBuddyMacCore/SignInFlow.swift",
        "macos/Sources/BrainBuddyMacCore/SignOutFlow.swift",
        "macos/Sources/BrainBuddyMacCore/SyncTriggerSource.swift",
        "macos/Sources/BrainBuddyMacCore/MacSyncController.swift",
        "macos/Sources/BrainBuddyMacCore/BrainBuddyModel.swift",
        "macos/Sources/BrainBuddyMacCore/WorkspaceHost.swift",
        "macos/Sources/BrainBuddyMac/ContentView.swift",
        "macos/Sources/BrainBuddyMac/BrainBuddyMacApp.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddySync/SyncEngine.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyAPI/SessionTokenStore.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyWorkspace/Workspace.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddySyncTests/SyncEngineSessionTests.swift",
        "docs/native-macos-app.md",
        "AGENTS.md",
        "macos/README.md",
        "docs/data-retention.md",
        "specs/021-mac-sync/evidence/manual-macos-status.md",
        "specs/021-mac-sync/evidence/manual-macos-upgrade.md"
      ],
      "depends_on": ["PR-08"],
      "external_depends_on": [],
      "serialize_with": ["020-weekly-review/PR-07", "020-weekly-review/PR-09", "020-weekly-review/PR-15"],
      "tests": [
        "cd macos && swift test  # macos-app lane; MacKeychainTests must run, not skip",
        "sh ios/scripts/swift-linux.sh test",
        "python3 scripts/check_requirement_coverage.py specs/021-mac-sync --requirements 021-FR-001,021-FR-003,021-FR-004,021-FR-005,021-FR-006,021-FR-009,021-FR-010,021-FR-012,021-FR-013,021-FR-014,021-FR-015,021-FR-016,021-FR-017,021-FR-018,021-FR-021,021-FR-029,021-FR-030,021-FR-031,021-FR-033,021-SC-004"
      ],
      "acceptance": [
        "MacSyncFlowTests: account-less triggers send zero requests; an upgraded host sends exactly one bodiless POST /auth/logout to the cookie's own host; a dry run makes no token-store call until a sign-in; every token-store call is off the main thread",
        "MacPresentationGuardTests fails on a seeded violation in a scratch copy and passes on the slice; MacKeychainTests run, not skip",
        "host lane: quickstart Scenario 5 step 4 and Scenario 6 step 2.3 on the landed build, recorded in manual-macos-status.md in a docs-only commit",
        "owner's recorded ASK approval (session credential, first egress of Mac data)",
        "landing class ASK (scripts/classify_path_risk.py: SHIP; semantic ASK)"
      ]
    },
    {
      "id": "PR-10",
      "outcome": "Minimum release gate: the 021 requirement scan (every id except SC-007) in make check-specs with gate integrity re-recorded; the evidence README and the owner-week template; the full verification on the frozen candidate. The manual-evidence checker and the coverage-floor raise are deferred.",
      "tasks": ["T136", "T137", "T139"],
      "requirements": ["021-SC-001", "021-SC-002", "021-SC-003", "021-SC-004", "021-SC-005", "021-SC-006", "021-SC-007"],
      "paths": [
        "Makefile",
        ".specify/gate-integrity.json",
        "specs/021-mac-sync/evidence/README.md",
        "specs/021-mac-sync/evidence/owner-week.md"
      ],
      "depends_on": ["PR-09"],
      "external_depends_on": ["020-weekly-review/PR-01"],
      "serialize_with": ["020-weekly-review/PR-14"],
      "tests": [
        "python3 scripts/check_gate_integrity.py",
        "make check-specs",
        "make validate-ci && make test-backend && make test-frontend && make test-e2e",
        "sh ios/scripts/swift-linux.sh test",
        "make verify-all"
      ],
      "acceptance": [
        "the requirement scan in make check-specs passes for every 021 FR and SC except SC-007; SC-007 is the owner's week, logged in owner-week.md",
        "gate-integrity manifest re-recorded in the same commit as the Makefile change; invariants intact; the Allure quality gate (maxFailures: 0) unchanged",
        "owner's recorded ASK approval (Makefile)",
        "landing class ASK (scripts/classify_path_risk.py: ASK)"
      ]
    }
  ]
}
```
