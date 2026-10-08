---

description: "Task list for 020 Weekly Review"
---

# Tasks: Weekly Review

<!--
  BrainBuddy override: delivery gates. Upstream treats tasks.md as an
  execution script; here it is portable planning input that never bypasses
  isolated worktrees, tests-before-implementation, independent acceptance,
  ADR-0008 landing classification, or CI. Those gates are restated below and
  must survive any upstream refresh.
-->

**Input**: Design documents from `/specs/020-weekly-review/` — [intake.md](intake.md), [spec.md](spec.md), [design.md](design.md), [plan.md](plan.md), [research.md](research.md), [research-on-device-model.md](research-on-device-model.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md), [adr-draft.md](adr-draft.md), [review-c1-disposition.md](review-c1-disposition.md), [review-c2-disposition.md](review-c2-disposition.md), [checklists/](checklists/)

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
feature-qualified id — `020-FR-012` / `020-SC-007` in Vitest, Playwright and Swift test
names, `test_020_FR_012_…` in Python — and the Allure taxonomy (`epic`, `feature`,
`story`, a readable title, at least one named step) through the central defaults in
`backend/tests/allure_taxonomy.py`, `frontend/src/test/allureTaxonomy.ts` and
`frontend/tests/allure.fixtures.ts`. Swift tests carry the ids but emit no Allure
results (`ios/README.md:340-341`). Every time-based pytest case uses the one
`frozen_clock` fixture. Evidence comes only from seeded synthetic accounts.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story. Include consent enforcement, mobile/resilience handling, observability (correlation IDs, actionable errors/progress), release/smoke validation, and data-safety safeguards where relevant.

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

**PR slice map status**: **approved by the owner on 2026-10-06** (15 slices, spec
Clarifications "Session 2026-10-06 (after /speckit-tasks)"); the map is the
`## PR-срезы` section at the end of this file, which is its only source of truth (the
earlier draft file was removed). PR-14 does not depend on the late PR-09: the clauses of
FR-023 (a) and FR-049 that only PR-09 can show are accepted when PR-09 lands. The
approval is a delivery boundary, not an authorization to merge or deploy.

**Rescope 2026-10-07** (owner decision, Notes "Deferred to a follow-up feature"): the
not-started slices PR-08, PR-09 and PR-10 left the manifest and PR-12, PR-13 and PR-14
shrank, so 12 slices remain. Deferred tasks are marked `DEFERRED`, keep their text as
input for the follow-up feature, and are not checklist items.

**Owner decisions applied after approval** (same session): tasks T091 (account
linking), T107 (privacy-policy sentence) and T163 (web device time zone) are new, and
existing tasks were extended for the consent line, the time-zone rule, the retry after
the idempotency retention and Dynamic Type up to AX5 (table "Owner decisions
2026-10-06 (after /speckit-tasks)" at the end). Tasks from the old T091 on were
renumbered to keep the ids sequential in execution order (168 → 171 tasks).

**Targeted re-review fixes** (2026-10-06, after founder acceptance; T-ids kept stable):
T172 (web `reviewSlot.ts`: the next review in the browser's own zone) is appended in
Phase 7 and slice PR-13; T042 – T044, T046, T055, T057, T091, T093, T126, T129, T131,
T133, T135, T146, T151, T154 and T159 were extended for the matching-record check
before revisions, replay-safe session progress (`progress_id`), undo retries, the
equal-zone no-op, the notification zone and the account-linking `extend` rule (172
tasks).

**`/speckit-analyze` remediation** (2026-10-06; T-ids kept stable): T173 (the Swift
replay of the decision and park traces, split out of T136) is appended in Phase 4 and
slice PR-04, which now also depends on PR-15; T136 keeps the run traces in PR-12. T021,
T022, T020 (required `progress_id`), T042, T126 (`id_conflict` vs matching record),
T113, T124 (`ai_use` on the wire; web Stop), T147, T149 (first-review and
completed-without-activity copy), T079, T116 (performance evidence), T166 (FR-041 run
file), T169 ("clean cycle" counts) were extended; T049 lost its `[P]`; the manifest's
`tests` now hold literal commands (173 tasks).

**Slice naming**: the plan's PR-01 – PR-14 keep their ids. The plan's rule "split
PR-02" is applied as **PR-02** (behaviour-neutral: clock seam, pure rules, vectors,
wire schemas and fixtures, their copies, the backend Allure rules) and **PR-15** (the
behaviour: flag, tables, decisions, undo, activation, sweep, routes, export — every
plan statement that says "PR-02" about behaviour now means PR-15). PR-15 is listed
third in the manifest because the order there is the dependency order.

**Deviations from the plan's file lists** (each keeps the plan's rules; none changes
a contract):

- Golden wire fixtures and operation traces are single files
  (`review_wire_fixtures.json`, `review_traces_tasks.json`, `review_traces_runs.json`)
  instead of `review_wire/*.json` and `review_traces/*.json`, so every slice lists
  file-level write paths (plan rule "file-level write paths only").
- iOS copies live in the test target that loads them: vectors in
  `BrainBuddyCoreTests/Resources/`, wire fixtures in `BrainBuddyAPITests/Resources/`,
  traces in `BrainBuddySyncTests/Resources/`; PR-03 declares all three in
  `ios/BrainBuddyKit/Package.swift` (still its single owner).
- Each UI slice records its own manual iOS evidence file (PR-04, PR-08, PR-09, PR-12)
  so it can be accepted on its own; PR-14 keeps the evidence README, the read-out and
  the rollout decisions.
- `ios/AGENTS.md` (PR-01) and `ios/README.md` (PR-12) carry the same "Weekly review
  stays deferred" rule as the design skill and are reworded with it (found by
  `/speckit-checklist`).
- The navigator consent commands are PR-03 (all `ReviewCommand` cases live in
  `Commands.swift`, PR-03's file), and the Mac sidebar entries move into a testable
  `macos/Sources/BrainBuddyMac/SidebarEntries.swift`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Web app**: `backend/app/`, `backend/tests/`, `frontend/src/`, `frontend/tests/`
- **Mobile**: `ios/BrainBuddyKit/` (Linux-testable package), `ios/BrainBuddy/` (app), `ios/BrainBuddyWidgets/`
- **macOS**: `macos/Sources/BrainBuddyMac/`, `macos/Tests/BrainBuddyMacTests/`

---

## Phase 1: Setup — governance (ADR, design skill, coverage gate)

**Purpose**: Record the decision and make the gates able to trace this feature before any product code.

- [x] T001 [P] Accept ADR-0027: copy `specs/020-weekly-review/adr-draft.md` to `docs/decisions/0027-native-task-weekly-review-and-auto-park.md`, set `Status: Accepted` with the owner's sign-off date, re-check that 0027 is still unused, and drop the draft comment block. *(020-FR-018)*
- [x] T002 [P] Record the ADR's effects at the cited lines: "Superseded in part by ADR-0027" in `docs/decisions/0006-native-gtd-lifecycle-and-capability-baseline.md` (l.29-31, B-09 l.81, l.322); "Amended by ADR-0027 for native tasks" in `docs/decisions/0001-vnext-modular-monolith-and-workflow-contracts.md` (l.61, l.266-293, l.468-470, l.619); close D-11 in `docs/vnext-cloud-design-build-contract.md` (l.757) with a link to ADR-0027. *(020-FR-018)*
- [x] T003 Write and observe RED: `scripts/test_validate_brain_buddy_design_skill.py` asserts the new wording "Weekly Review is flag-gated: a non-interactive `coming later` entry while the `weekly_review` flag is off" in README and SKILL (replacing l.29 and l.32) and keeps the "coming later" assertion for the flag-off nav card (l.33). *(020-FR-042)*
- [x] T004 Make T003 GREEN: reword `.claude/skills/brain-buddy-design/README.md` (l.42), `.claude/skills/brain-buddy-design/SKILL.md` (l.7) and `.claude/skills/brain-buddy-design/preview/components-gtd-nav.html` (l.35); run `python3 -m unittest scripts/test_validate_brain_buddy_design_skill.py`. *(020-FR-042)*
- [x] T005 [P] Reword the copy rule "Weekly review stays visibly deferred" in `ios/AGENTS.md` ("Design and copy") to the T004 wording (found by `/speckit-checklist`; not in the plan's PR-01 paths). *(020-FR-042)*
- [x] T006 Write and observe RED: `scripts/test_check_requirement_coverage.py` gains cases where a Swift test under `ios/BrainBuddyKit/Tests` naming `020-FR-047` and one under `macos/Tests` naming `020-FR-041` satisfy the gate, and where `--requirements 020-FR-001,020-SC-002` checks only those ids and rejects an id that `spec.md` does not define (research R19).
- [x] T007 Make T006 GREEN in `scripts/check_requirement_coverage.py`: add `ios/BrainBuddyKit/Tests` and `macos/Tests` to `DEDICATED_TEST_TREES`, `.swift` to `TEST_SUFFIXES`, and the `--requirements` filter.
- [x] T008 Re-record the gate-integrity manifest in the same commit as T007 (`scripts/check_requirement_coverage.py` is in `GUARDED_FILES`): `python3 scripts/check_gate_integrity.py --update` rewrites `.specify/gate-integrity.json`; then `python3 scripts/check_gate_integrity.py` passes with every invariant intact.
- [x] T009 [P] Clarify the docstring of the forward guard in `backend/tests/test_voice_workflow_architecture.py` (l.250): the `weekly_review` path token stays reserved for voice-led review (ADR-0002); native-task review code avoids it (research R1). No assertion changes.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The clock seam, the shared rules and fixtures every lane consumes, and the backend core (flag, tables, services, routers, export) that every story builds on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete (the iOS core and web lanes need only the PR-02 part).

### Behaviour-neutral foundation (slice PR-02)

- [x] T010 Add the Allure taxonomy rules for every review test module at once to `backend/tests/allure_taxonomy.py` (epic "Tasks"; features "Formulation clock", "Review decisions", "Auto-park", "Review flow", "Navigator"; matching `test_review_*.py`), so no later backend slice edits this file (plan rule "single owners").
- [x] T011 Write and observe RED `backend/tests/test_review_clock_seam.py`: `TaskService` built by the container takes an injected `clock: Callable[[], datetime]`; under the `frozen_clock` fixture a created task's `created_at`/`updated_at` and the idempotency purge use the frozen instant; no test patches a module's `utcnow` (research R21).
- [x] T012 Add the `frozen_clock` fixture to `backend/tests/conftest.py`; it sets the clock injected into `TaskService` now, and into `ReviewService` and the review sweep once they exist.
- [x] T013 Make T011 GREEN: inject `clock` into `TaskService` in `backend/app/modules/tasks/service.py` (replacing the direct `utcnow()` calls, l.75, 107, 149, 200, 261 and the rest) and pass `app.utils.time.utcnow` from `backend/app/container.py`. Behaviour-neutral: the existing task suites stay green.
- [x] T014 [P] Write the canonical vectors `backend/tests/fixtures/review_formulation_vectors.json` (`"schema": "brainbuddy-formulation-vectors/v1"`; sections `normalisation`, `classification`, `transitions` with the transition schema of contracts/formulation-clock.md §6) covering every "Required coverage" item there: every §1 example; every §5 class one second before and at its boundary; DST start/end in `Europe/Berlin` and `America/New_York`; due date today/tomorrow/yesterday; extension at T, T + 3, T + 6 and at `park_due`; each floor dominating (activation, threshold change, due-date change, sweep gap, time-zone change); not activated → `none`; activation clamp and null-clock start; the third stall across leave and return; yield + `extend` and yield + `reformulate` (stalled count once); `extend` then a substantive `reformulate` before the extended `ask_at`; park → yield + cosmetic save → parked again; park → yield + decision + undo → parked again; bulk-release undo restoring the clock; queue order with an extended and a due-paused task; activation with `"Pacific/Honolulu"` and a due date today.
- [x] T015 [P] Write the canonical `backend/tests/fixtures/review_flow_vectors.json` with sections: wins window (last 7 days); capacity mirror (41 Next, 9 a week; fewer than 4 full weeks or no completions → Next count only); Waiting (older than 7 days, oldest `waiting_since` first) and Someday (no current receipt, not auto-parked in the last 30 days, never-reviewed first, at most 7) membership and order; restart eligibility and its anchor ("`onboarded_at` set and `now - coalesce(last_counted_review_at, onboarded_at) ≥ 21 d`"); run status and counted-review rules (FR-029 incl. `completed_empty`); regularity instant; notification skip (preceding 6 days); decision-queue order; `stall_recommendation`; `active_time` (a gap over 2 minutes counts 0, background never counts, per-step, resume); the While-you-were-away once-a-day rule; the navigator project-wide duplicate filter (a 25-task project whose only proposal equals the 21st, unsent title).
- [x] T016 Write and observe RED `backend/tests/test_review_formulation.py` (unit, ±1 s boundaries) and `backend/tests/test_review_formulation_vectors.py` (every section of both vector files, plus the drift guard that fails when any byte-identical copy listed in T023 is missing or differs). Names carry ids, e.g. `test_020_FR_002_cosmetic_title_change_keeps_formulation`. *(020-FR-001, 020-FR-002, 020-FR-003, 020-FR-004, 020-FR-005, 020-FR-009, 020-FR-012, 020-FR-016, 020-FR-039, 020-FR-046, 020-FR-051)*
- [x] T017 Make T016 GREEN in `backend/app/modules/tasks/formulation.py`: `formulation_key` (NFKC; punctuation `Pc Pd Ps Pe Pi Pf Po` → one space; Python whitespace collapse; `str.casefold()`; a sibling of `normalize_task_name`), `derive_instants`, `classify`, `close_formulation`, `start_formulation`, the `asks_for_decision` aggregate, `restart_eligible` and `third_stall`, exactly per contracts/formulation-clock.md §1–§5. *(020-FR-001, 020-FR-002, 020-FR-004, 020-FR-005, 020-FR-046)*
- [x] T018 Write and observe RED `backend/tests/test_review_flow_vectors.py`: every section of `review_flow_vectors.json` runs once against the pure rules, so no consumer lane relies on a vector that has never run (c2 TE-06). *(020-FR-007, 020-FR-015, 020-FR-017, 020-FR-019, 020-FR-028, 020-FR-029, 020-FR-031, 020-FR-032, 020-FR-036, 020-SC-004)*
- [x] T019 Make T018 GREEN in `backend/app/modules/tasks/review_rules.py` (pure functions, no I/O): wins window, capacity mirror, Waiting/Someday eligibility and order, restart anchor, run status and counted-review rules, regularity instant, notification skip, decision-queue order, stall-reason recommendation (unclear → reformulate; too big, missing information, no energy → first step; waiting on someone → Waiting for; no longer matters → cancel), active-time accumulation, the once-a-day rule, the duplicate filter by `formulation_key`.
- [x] T020 [P] Write and observe RED `backend/tests/test_review_wire_fixtures.py`: every entry of the golden wire fixtures validates against the wire schemas; a client id carrying free text instead of `decision_<uuid>`, a session `PATCH` progress body without `progress_id` and an extra `language` field in a navigator request are rejected. *(020-FR-019, 020-FR-045)*
- [x] T021 Make T020 GREEN in `backend/app/schemas/review.py` — every request and response model of contracts/http.md §2–§7: client ids matching `^(review|decision|bulk|form|task|progress)_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$` "with the prefix fixed per field", "at most 64 characters"; the session `PATCH` body with a **required** `progress_id` (`progress_<uuid>`; missing → 422, another prefix → 422, contracts/http.md §6); references accepting that shape or a server-minted `<prefix>_<12 hex>`; `navigator_request_id` "either null or exactly the 36-character UUID the server returned"; `reason` "(1..500)"; `stall_reason` ∈ `unclear | too_big | missing_info | waiting_on_someone | no_energy | no_longer_matters | null`; `ai_use` ∈ `none | as_is | edited | not_used`; `status` ∈ `open | completed | completed_empty | partial | abandoned`; step codes `wins, mind_sweep, inbox, decisions, rest_of_next, waiting, projects, someday, dates, summary`; the exact `SessionResponse` field list; `NavigatorSuggestionRequest` with `extra="forbid"` — and the nullable `formulation` and `parked` response fields in `backend/app/schemas/tasks.py` (always `null` until PR-15). *(020-FR-019, 020-FR-045)*
- [x] T022 [P] Write the golden wire fixtures `backend/tests/fixtures/review_wire_fixtures.json`: one entry per request and response shape of contracts/http.md §2–§7 and the error envelope with `reference_id`, including a session `PATCH` progress body carrying `progress_id` (`progress_<uuid>`) and a rejected entry for the same body without it (422, asserted by T020).
- [x] T023 Copy byte-identically (contracts/formulation-clock.md §6 "Who lands the copies"): `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/Resources/review_formulation_vectors.json`, `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/Resources/review_flow_vectors.json`, `ios/BrainBuddyKit/Tests/BrainBuddyAPITests/Resources/review_wire_fixtures.json`, `frontend/src/features/review/__tests__/review_formulation_vectors.json`, `frontend/src/features/review/__tests__/review_flow_vectors.json`, `frontend/src/features/review/__tests__/review_wire_fixtures.json`; the T016 drift guard turns GREEN.
- [x] T024 Add `app/modules/tasks/formulation.py` and `app/modules/tasks/review_rules.py` to the observed mutation scope (`[tool.mutmut] only_mutate`) in `backend/pyproject.toml` (research R20); run `make test-backend` (coverage floor and Allure taxonomy validator).

### Backend core (slice PR-15)

- [x] T025 Write and observe RED in `backend/tests/test_feature_flags.py` and `backend/tests/test_feature_flag_repository.py`: `weekly_review` is runtime-managed, default OFF, resolves for selected users, and survives the ADR-0019 store upgrade. *(020-FR-042)*
- [x] T026 Make T025 GREEN: register `weekly_review` in `KNOWN_FEATURE_FLAGS` (`backend/app/core/config.py` l.86), `MANAGED_FLAGS`, `_POST_ADR_0019_DEFAULT_OFF_FLAGS` and the upgrade whitelist (`backend/app/repositories/feature_flag.py` l.83, 100, 426). *(020-FR-042)*
- [x] T027 Write and observe RED `backend/tests/test_review_repository.py`: the eight review tables exist after `_initialize_database` (`CREATE TABLE IF NOT EXISTS`) with the ledger row `review-v1`; every read filters by `owner_id`; another owner's record reads as absent; `delete_all_for_owner` removes the review tables first inside its lock and is idempotent. *(020-FR-043)*
- [x] T028 Make T027 GREEN with the records in `backend/app/modules/tasks/review_domain.py`, the TaskDocument fields in `backend/app/modules/tasks/domain.py`, and the SQL mixin `backend/app/modules/tasks/review_repository.py` composed into `backend/app/modules/tasks/repository.py`, quoting the data-model constraints: E1 `formulation_extension_reason` "`str | None` (1..500)", `consecutive_stalled_formulations` "`int ≥ 0`", `parked` "non-null only while `state == "someday"`" and "written **only by auto-park**"; E2 `threshold_days` "7 \| 14 \| 21 \| 28" default 14, `review_weekday` "1..7 (ISO, Monday = 1)" default 5, `review_time` "`HH:MM`" default `16:00`, `time_zone` "IANA name" default `UTC`, `activated_at` "immutable once set; first acknowledgement wins", `revision` "int ≥ 1"; E3 `mode` `quick | full`, `entry` `list | notification | widget_decisions | sidebar | restart`, `origin` `ios | web | macos`, `counts` "`{done, reformulated, first_step, waiting, someday, cancelled, extended, inbox_processed, kept, moved_to_next}`"; E4 `type` ∈ "`complete, reformulate, first_step, waiting, someday, cancel, extend, keep_waiting, follow_up, return_to_next, keep_someday`", `reason_text` "str (1..500) \| null … only for `extend`"; E5 `kind` "`waiting | someday`", `source` `keep | release`, `hidden_until` "`+7 d` waiting, `+30 d` someday"; E6 `source` "`sweep | device`"; E7 `kind (restart | inbox_remainder)`, `skipped` `reason: stale | not_eligible`; E8 `consent_text_version` and `history[]`; E9 `calls`, `estimated_cost_usd`, `reserved_cost_usd`, `shown`. *(020-FR-043)*
- [x] T029 Generalise `_serialized_write` (`backend/app/modules/tasks/service.py` l.64-79) into a `SerializedWriter` protocol (`task_repo`, `_reconcile_idempotent_result`) with no behaviour change; `backend/tests/test_tasks_idempotency_repair.py` and the task suites stay green (c2 AC-05).
- [x] T030 Create `ReviewService` in `backend/app/modules/tasks/review_service.py` (composes `TaskService` and calls its undecorated helpers inside its own serialized write; injected clock; its own `_apply_idempotent_record` registry for `decide_task:`, `undo_decision:`, `auto-park:`, `bulk_release:`, `undo_bulk_release:`, `review_session:`, `review_settings:`, `explainer_ack:`, `park_ack:`; logger `app.modules.tasks.review`), an empty `ReviewFlowService` in `backend/app/modules/tasks/review_flow.py` (filled by PR-11), and wire both in `backend/app/container.py`; `frozen_clock` now sets their clock too.
- [x] T031 Write and observe RED `backend/tests/test_review_gate_api.py`: with `weekly_review` not effective, `GET /review/state` returns 404 `{"message": "Not found", "detail": {"reason": "weekly_review_disabled"}}`; with it effective the route answers; every response carries `X-Correlation-ID`. *(020-FR-042, 020-FR-045)*
- [x] T032 Make T031 GREEN: `get_review_service`, `get_review_flow_service` and `require_weekly_review_enabled` (exposure only, the `require_voice_brain_dump_enabled` rule, l.361-385) in `backend/app/api/dependencies.py`; the routers `backend/app/api/review.py`, `backend/app/api/review_navigator.py` (empty) and `backend/app/api/review_flow.py` (empty), all mounted in `backend/app/api/__init__.py`. *(020-FR-042, 020-FR-045)*
- [x] T033 Move the router-private `_to_response` (`backend/app/api/tasks.py` l.1183) to a public `task_response(task, *, subtasks, comments, formulation)` in `backend/app/api/task_mapping.py`, used by `backend/app/api/tasks.py`; `backend/tests/test_task_api.py` stays green (c2 AC-04).
- [x] T034 Extend the import-linter contracts in `backend/pyproject.toml`: routes may not import `app.modules.tasks.review_repository`; layers `review_service → service → repository`; `app.modules.tasks` may not import `httpx` or `app.ai`; add `app/modules/tasks/review_service.py` to `[tool.mutmut] only_mutate` (c1 AC-09, c2 AC-01, research R20).
- [x] T035 Write and observe RED `backend/tests/test_review_export_purge.py`: the ZIP holds `review/settings.json`, `review/sessions.json`, `review/decisions.json` (with an `extend` decision's `reason_text`), `review/receipts.json`, `review/park_acknowledgements.json`, `review/bulk_releases.json`, `review/navigator_consents.json`; `export_manifest.json` lists `navigator_usage` under `excluded`; purge leaves every review table empty for the owner and a second purge is a no-op. *(020-FR-043)*
- [x] T036 Make T035 GREEN in `backend/app/services/account_service.py` (export `review/*.json`; purge order unchanged, covered by `delete_all_for_owner`). *(020-FR-043)*
- [x] T037 Write and observe RED `backend/tests/test_review_log_privacy.py`: decisions, undo, settings, the explainer acknowledgement, auto-park and the sweep run with sentinel strings in title, notes, waiting-for and extension reason and with a stall reason set; no captured log record holds a sentinel or a stall-reason value; a decision whose `decision_id` carries the sentinel instead of `decision_<uuid>` gets 422 and the sentinel reaches no log; the sweep over a deliberately invalid task payload holding a sentinel logs only `type(exc).__name__` and a reason code. Stays RED until T043 and T080. *(020-FR-044)*
- [x] T038 [P] Write and observe RED in `frontend/src/pages/__tests__/PrivacyPolicyPage.test.tsx`, then update `frontend/src/pages/PrivacyPolicyPage.tsx`: review day, time and time zone are named as stored review settings; review records are kept for the account's life, exported and purged; undo copies last 7 days. *(020-FR-043)*
- [x] T039 [P] Add rows to `docs/data-retention.md`: the server review tables (undo and bulk-release snapshots "7 days; longer only while the backend is rolled back to a build without the review sweep"; `navigator_usage` 35 days; everything else the account's life), the iOS store document's review state (decisions with 7-day undo snapshots, extension reasons, sessions, consent state, form drafts, the last observed time zone) and the web form drafts, last-shown key and last observed time-zone key `bb.reviewLastZone.v1.<origin>.<account>` (data-model E10, E11). *(020-FR-043)*

**Checkpoint**: Foundation ready — the backend answers the gated state route, the shared rules and fixtures exist in every lane.

---

## Phase 3: User Story 1 — A stalled task asks for a decision (Priority: P1) 🎯 MVP (with US2)

**Goal**: Markers from the formulation clock, and a decision card reachable from the task on any day, with Undo and stale protection, on backend, iOS and web.

**Independent Test**: Seed a task whose formulation is older than the threshold (owner activated). Verify the marker, open the card, exercise each decision and verify the resulting task state and clock — without any review run, schedule or AI (quickstart Scenario 1).

### Backend (slice PR-15)

- [x] T040 [US1] Write and observe RED `backend/tests/test_review_clock_api.py`: create in Next (with and without `new_formulation_id` `form_…`), move or reopen into Next, substantive vs cosmetic title PATCH, notes/tags/project/priority/subtask/comment edits that leave the clock alone, due-date set/move/remove raising `formulation_park_floor_at` to `max(existing, now + 7 d)`, leaving Next closing the formulation with the stalled-count rule, `create_native_inbox_task` never starting a clock, and `TaskResponse.formulation` carrying `ageing_at`, `ask_at`, `park_due_at`, `paused_until` (all `null` before activation) built by the shared `task_mapping` for both routers. *(020-FR-001, 020-FR-002, 020-FR-003, 020-FR-004, 020-FR-005, 020-FR-046, 020-FR-051)*
- [x] T041 [US1] Make T040 GREEN: maintain the clock in `create_task`, `smart_add_task`, `update_task` and `transition_task` and add `TaskService.formulation_views(owner_id, tasks)` (one settings read per request) in `backend/app/modules/tasks/service.py`; accept the optional `new_formulation_id` on create, PATCH and transition requests in `backend/app/schemas/tasks.py`; pass the views through `task_response` in `backend/app/api/tasks.py` (the whole ASK diff there: import the mapper, pass the views, accept the field). No `client_occurred_at`. *(020-FR-001, 020-FR-002, 020-FR-003, 020-FR-046)*
- [x] T042 [US1] Write and observe RED `backend/tests/test_review_decisions_api.py` for `POST /tasks/{task_id}/decisions`: every row of the contracts/http.md §3 type table with its `review_counts_as` counter; a cosmetic "Save anyway" recorded as `reformulate` with `substantive: false` and the clock unchanged; `first_step` details `"Was: <old title>"` (+ `"\n\n"` + old details); `extend` requires `reason` (1..500), is allowed only at `asks`, `moves_tomorrow` or not-yet-applied `park_due`, once per formulation (`extension_already_used`, `extension_not_due`), and keeps `reason_text` on the decision; `someday` leaves `parked` null and writes a `source: release` Someday receipt (+30 d); `follow_up`/`return_to_next` into an archived project → 400 `project_archived` (fixture only: the state cannot occur today); stale revision or formulation → 409 with nothing applied; `decision_not_allowed`; same key and body replay, another body → 409 `idempotency_conflict`; client ids adopted, a wrong shape → 422, a reused `decision_id` under another key with different identifying fields (`task_id`, `type`, `formulation_id`) → 409 `id_conflict`, and a reused `decision_id` under another key whose stored decision matches → 200 with the stored outcome and nothing applied (no second decision row, task unchanged); **retry after the 24 h idempotency retention** (`frozen_clock` advanced past `IDEMPOTENCY_RETENTION`, contracts/http.md "Retry after the idempotency retention"): the same request with the same key, the now-stale `expected_revision` of its first delivery and a stored decision that matches (same owner, `decision_id`, `task_id`, `type`, `formulation_id`) → 200 with the stored outcome (the matching-record check runs before the revision, formulation and eligibility checks), the task changed once and one decision row, while the same `decision_id` with another task or type → 409 `id_conflict` and the same `decision_id` under another owner → processed as unknown (never matched across owners); an unknown `session_id` → recorded without a session (200, `session_id: null`); another owner's task → 404; with the flag off the decision is still accepted; one idempotency record of every new prefix reconciles through `ReviewService`. *(020-FR-002, 020-FR-005, 020-FR-006, 020-FR-007, 020-FR-008, 020-FR-009, 020-FR-010, 020-FR-011, 020-FR-026, 020-FR-032, 020-FR-033, 020-FR-045)*
- [x] T043 [US1] Make T042 GREEN: `ReviewService.decide` in `backend/app/modules/tasks/review_service.py` (one transaction under the owner lock: the task change, the decision row with the stall-reason code, `ai_use`, `navigator_request_id`, the undo snapshot, any receipt, and the run counter and `qualifying_activity` when linked), the matching-record check that answers a retry after the retention as already applied, run first under the owner lock before `expected_revision` and eligibility (a shared helper `ReviewService` also uses for sessions, bulk releases and session progress), and the route in `backend/app/api/review.py` returning `DecisionResponse` with `TaskResponse` from `task_mapping`; log `review_decision` with ids and codes only (never the stall reason). *(020-FR-006, 020-FR-010, 020-FR-011, 020-FR-044)*
- [x] T044 [US1] Write and observe RED in `backend/tests/test_review_decisions_api.py` for `POST /review/decisions/{decision_id}/undo`: field-for-field restore with `revision + 1`, clock included; the follow-up created by the decision is deleted only while its revision equals `created_task_revision`; the decision's receipt is deleted; the run counter goes down; the decision row is deleted; 409 `undo_unavailable` after any change to the task or follow-up, or once the snapshot was purged; 404 when already undone or not owned (a retried undo whose first delivery was applied, after the 24 h retention, gets that 404 and nothing changes). *(020-FR-011, 020-FR-048)*
- [x] T045 [US1] Make T044 GREEN: `ReviewService.undo_decision` in `backend/app/modules/tasks/review_service.py` and the route in `backend/app/api/review.py`; log `review_undo`. *(020-FR-048)*
- [x] T046 [US1] Write and observe RED `backend/tests/test_review_settings_api.py`: `PUT /review/settings` validates `threshold_days` "7 \| 14 \| 21 \| 28", `review_weekday` "1..7", `review_time` `HH:MM`, an IANA `time_zone` (400 `invalid_time_zone`), `onboarded: true` and `expected_revision` (409 on mismatch); a threshold change sets `owner_park_floor_at = now + 7 d` and updates the derived instants at once; a time-zone change floors every due-dated Next task (`max(existing, now + 7 d)`); a `time_zone` equal to the stored one raises no floor, a threshold equal to the stored one sets no `owner_park_floor_at`, and a body whose every field equals the stored values leaves `revision` unchanged (200, still 409 on a stale `expected_revision`); `next_review_at` is the slot in the stored zone with the 6-day skip; `GET /review/state` returns the contracts/http.md §5 shape: `counts.asks_for_decision` (asks + moves tomorrow + not-yet-applied park due) and `moves_tomorrow`, `next_review_at`, `last_counted_review_at` and `last_counted_review` from counted reviews only, `restart_mode` per FR-017, `open_session`, `server_now`. *(020-FR-004, 020-FR-017, 020-FR-035, 020-FR-038, 020-FR-039, 020-FR-046, 020-SC-007)*
- [x] T047 [US1] Make T046 GREEN in `backend/app/modules/tasks/review_service.py` and `backend/app/api/review.py` (state computed with the pure functions of `review_rules.py`); log `review_settings_changed` (threshold old/new) and the content-free `review_due_date_moved` (owner and task ids only) from `backend/app/modules/tasks/service.py` when a Next task's due date changes. *(020-FR-035, 020-FR-039, 020-FR-044)*

### iOS core (slice PR-03)

- [x] T048 [US1] Declare test resources in `ios/BrainBuddyKit/Package.swift` for `BrainBuddyCoreTests`, `BrainBuddyAPITests` and `BrainBuddySyncTests` (the last starts with `ios/BrainBuddyKit/Tests/BrainBuddySyncTests/Resources/README.md`, so the declaration holds before the trace copies arrive); `Package.swift` keeps zero dependencies.
- [x] T049 [US1] Write and observe RED `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/FormulationTests.swift`: every section of the copied vectors (normalisation through `FormulationKey` reusing `NameNormalizer.collapsed`/`caseFolded`; classification; transitions incl. the revision rule). *(020-FR-001, 020-FR-002, 020-FR-004, 020-FR-005, 020-FR-009, 020-FR-012, 020-FR-016, 020-FR-039, 020-FR-046)*
- [x] T050 [US1] Make T049 GREEN in `ios/BrainBuddyKit/Sources/BrainBuddyCore/Formulation.swift`.
- [x] T051 [US1] Write and observe RED `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ReducerReviewTests.swift`: the reducer maintains the clock for every existing command per contracts/ios-commands.md §3, with form ids minted in the command as `form_<lowercased UUID>` (deterministic replay); `decideTask` applies the http §3 table and records the decision with an undo snapshot and the follow-up's revision; `undoDecision` restores it and deletes an unchanged follow-up; the new `GTDValidationError` cases; an unsent `decideTask` + `undoDecision` cancel in compaction; once exposed, a title change or a move is never folded into an unsent `createTask`, and compacted vs uncompacted replays give identical `formulation` fields for every transition vector. *(020-FR-001, 020-FR-002, 020-FR-003, 020-FR-006, 020-FR-008, 020-FR-009, 020-FR-011, 020-FR-048)*
- [x] T052 [US1] Make T051 GREEN: `FormulationClock`, `ParkMarker`, `consecutiveStalledFormulations` (decoded with `decodeIfPresent`) and `GTDState.review` in `ios/BrainBuddyKit/Sources/BrainBuddyCore/Records.swift`; `decideTask`/`undoDecision` in `ios/BrainBuddyKit/Sources/BrainBuddyCore/Commands.swift`; the clock rules in `ios/BrainBuddyKit/Sources/BrainBuddyCore/Reducer.swift` and the new `ios/BrainBuddyKit/Sources/BrainBuddyCore/Reducer+Review.swift`; `ios/BrainBuddyKit/Sources/BrainBuddyCore/Replay.swift`; clock-aware `ios/BrainBuddyKit/Sources/BrainBuddyCore/Compaction.swift`.
- [x] T053 [US1] Write and observe RED `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/QueriesReviewTests.swift` (`formulationClass`, `decisionQueue` = the `asks_for_decision` aggregate in earliest-asking order, `askCount`) and `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ReviewPlannersTests.swift` (`MarkerStyle` never maps an age class to an error role; `StallReasonRecommendation` against the `stall_recommendation` vectors, every decision still enabled, clearing the reason clears it; `UndoWindowPolicy` about 5 s and at least 10 s under VoiceOver or Switch Control; `ReviewPresentation.decisionCard(inReview:)` → large sheet outside a review, full screen inside; every `ReviewCopy` entry free of "overdue" and streak wording). *(020-FR-004, 020-FR-007, 020-FR-038, 020-FR-047, 020-FR-048)*
- [x] T054 [US1] Make T053 GREEN in the new `ios/BrainBuddyKit/Sources/BrainBuddyCore/Queries+Review.swift`, `ios/BrainBuddyKit/Sources/BrainBuddyCore/ReviewPlanners.swift` (`MarkerStyle`, `StallReasonRecommendation`, `UndoWindowPolicy`, `ReviewPresentation`) and `ios/BrainBuddyKit/Sources/BrainBuddyCore/ReviewCopy.swift` (M-02 "This wording" lines, markers, decision toasts).
- [x] T055 [US1] Write and observe RED `ios/BrainBuddyKit/Tests/BrainBuddyAPITests/ReviewWireTests.swift` (every entry of the copied `review_wire_fixtures.json` decodes into the DTOs, `TaskDTO.formulation`/`parked` via `decodeIfPresent`; request bodies carry `decision_id`, `new_formulation_id`, `follow_up_task_id`; a 404 whose `detail.reason` is `weekly_review_disabled` maps to `APIError.Kind.featureDisabled`) and `ios/BrainBuddyKit/Tests/BrainBuddySyncTests/ReviewSyncTests.swift` (a `decideTask` 409 goes through the existing refetch/replay; the `.review` conflict target; a decision is set aside only when its formulation changed, with copy naming the task's current list and the Ref; a decision whose response was lost and that is retried after the fake server's 24 h idempotency retention, with its stale `expected_revision`, is answered as already applied and acknowledged as success, 0 sync issues, applied once; an `undoDecision` retried after its first delivery was applied gets 404 and is acknowledged as success, never set aside). *(020-FR-011, 020-FR-045)*
- [x] T056 [US1] Make T055 GREEN: `ios/BrainBuddyKit/Sources/BrainBuddyAPI/WireModels.swift`, `ios/BrainBuddyKit/Sources/BrainBuddyAPI/RequestBodies.swift`, `ios/BrainBuddyKit/Sources/BrainBuddyAPI/APIError.swift`, `ios/BrainBuddyKit/Sources/BrainBuddyAPI/BrainBuddyAPIClient.swift` and the new `ios/BrainBuddyKit/Sources/BrainBuddyAPI/ReviewAPI.swift`; `ios/BrainBuddyKit/Sources/BrainBuddySync/GTDCommand+Sync.swift`, `ios/BrainBuddyKit/Sources/BrainBuddySync/PushPlanner.swift`, `ios/BrainBuddyKit/Sources/BrainBuddySync/SyncEngine+Push.swift` (`.featureDisabled` handled like `.rateLimited`: keep, back off, never set aside) and `ios/BrainBuddyKit/Sources/BrainBuddySync/StoreDocument+Merge.swift`; decisions (including the matching-record answer to a retry after the retention), undo, settings and state in the new `ios/BrainBuddyKit/Sources/BrainBuddyFakeServer/FakeServer+Review.swift`.
- [x] T057 [US1] Write and observe RED in `ios/BrainBuddyKit/Tests/BrainBuddyPersistenceTests/StoreDocumentCodingTests.swift`: a v1 store fixture decodes to v2 with an empty `base.review`/`local`, `local.activatedAt = nil`, `local.formDrafts = [:]`, `local.lastObservedTimeZone == nil`, `local.linkedExtensionNotices == []` (contracts/ios-commands.md §7) and no data loss; then GREEN in `ios/BrainBuddyKit/Sources/BrainBuddyPersistence/StoreDocumentCoding.swift` (`migrationStep(from: 1)`) and `ios/BrainBuddyKit/Sources/BrainBuddyCore/Outbox.swift` (`currentVersion = 2`). *(020-FR-040)*
- [x] T058 [US1] Write and observe RED `ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/WorkspaceReviewTests.swift`: decide and undo through the workspace; form drafts keyed by form kind + task id + formulation id (or run id + step item, or project id) are stored, restored, and deleted on save, discard, formulation change, sign-out or after 7 days, and never enter an outbox operation; then GREEN with public review methods in `ios/BrainBuddyKit/Sources/BrainBuddyWorkspace/Workspace.swift` (every later Workspace review method also lands in this slice). *(020-FR-010, 020-FR-048, 020-FR-052)*

### iOS app (slice PR-04)

- [x] T059 [US1] Add `BBWeeklyReviewLocal` (`YES` in Debug, `NO` in Release) to `ios/project.yml` and read it, together with `MeDTO.featureFlags["weekly_review"]` when signed in, in `ios/BrainBuddy/App/RootView.swift`; the existing `DeferredRow` stays while not exposed. *(020-FR-042)*
- [x] T060 [US1] M-01 in `ios/BrainBuddy/Components/TaskRow.swift`, `ios/BrainBuddy/Components/Chips.swift` and `ios/BrainBuddy/Screens/Lists/TaskListScreen.swift`: only the "Asks for a decision" (indigo, `questionmark.circle`) and "Moves to Someday tomorrow" (amber, `archivebox`) chips from `MarkerStyle`, text plus icon, a 44 pt hit area; tapping opens M-03 with `.presentationDetents([.large])`; the threshold-just-changed note; no marker before activation; every M-01 state. *(020-FR-004, 020-FR-010, 020-FR-039, 020-FR-047, 020-FR-051)*
- [x] T061 [US1] M-02 "This wording" in the new `ios/BrainBuddy/Screens/Review/FormulationSection.swift`, placed in `ios/BrainBuddy/Screens/Detail/TaskDetailScreen.swift`: asks, ageing/fresh ("Ageing" only here), paused, moves tomorrow with the exact park time, kept 7 more days with the quoted reason, parked automatically, parked with an archived project; copy from `ReviewCopy`; "Decide". *(020-FR-001, 020-FR-003, 020-FR-004, 020-FR-009, 020-FR-012, 020-FR-046)*
- [x] T062 [US1] M-03 in the new `ios/BrainBuddy/Screens/Review/DecisionCardSheet.swift`: seven decisions in fixed order, optional stall reasons with "Recommended" from `StallReasonRecommendation` (all decisions enabled), the extension-used line, the third-stall offer with only "Release to Someday" (no canvas on iOS), stale was/now, decision not allowed, the error routed to Sync issues with Ref and the Next note "1 decision couldn't be saved", VoiceOver focus on the card title. *(020-FR-005, 020-FR-006, 020-FR-007, 020-FR-009, 020-FR-010, 020-FR-011, 020-FR-045, 020-FR-047)*
- [x] T063 [US1] M-04 in the new `ios/BrainBuddy/Screens/Review/DecisionForms.swift`: reformulate with the cosmetic-edit note from `FormulationKey` and "Save anyway", first step with the "Was:" preview, Waiting for, keep 7 more days with the required reason and the computed date ("Keep until Fri 16 Oct" on Fri 9 Oct); dirty tracking, the "Discard your new wording?" confirmation with "Keep editing" as default, `interactiveDismissDisabled` while dirty, "Your unsaved text is back." on reopen. No Suggest yet. *(020-FR-001, 020-FR-002, 020-FR-006, 020-FR-008, 020-FR-009, 020-FR-052)*
- [x] T064 [US1] Undo in `ios/BrainBuddy/Components/Toasts.swift`: duration from `UndoWindowPolicy`, the VoiceOver announcement "<decision>. Undo available.", a 44 × 44 pt Undo, "undo didn't apply" copy naming the current list. *(020-FR-048)*
- [x] T065 [US1] M-23 threshold picker (7/14/21/28) with the floor note in the new `ios/BrainBuddy/Screens/Settings/ReviewSettingsSection.swift`, placed in `ios/BrainBuddy/Screens/Settings/SettingsScreen.swift`. *(020-FR-039)*

### Web (slice PR-05)

- [x] T066 [US1] Add the `/features/review/` rule to `frontend/src/test/allureTaxonomy.ts` before the first review Vitest file (single owner of this file).
- [x] T067 [P] [US1] Write and observe RED `frontend/src/features/review/__tests__/formulation.test.ts` (the `normalisation` vectors; `classifyFromInstants` over the `classification` vectors); then GREEN `frontend/src/features/review/formulation.ts`, added to the Stryker observed `mutate` list in `frontend/stryker.config.json` (research R20). *(020-FR-002, 020-FR-004, 020-FR-046)*
- [x] T068 [P] [US1] Write and observe RED `frontend/src/api/__tests__/review.test.ts` (the copied wire fixtures parse; decide, undo, settings and state calls send an `Idempotency-Key` on mutations; failures expose the correlation id); then GREEN `frontend/src/api/review.ts`, `frontend/src/api/reviewHooks.ts` and `frontend/src/api/taskTypes.ts` (`formulation`, `parked`). *(020-FR-045)*
- [x] T069 [P] [US1] Write and observe RED `frontend/src/features/review/__tests__/stallRecommendation.test.ts` against the `stall_recommendation` vectors; then GREEN `frontend/src/features/review/stallRecommendation.ts`. *(020-FR-007)*
- [x] T070 [US1] Write and observe RED in `frontend/src/components/shell/__tests__/shellToast.test.tsx` and `frontend/src/components/shell/__tests__/AppShell.test.tsx` (toast part): an optional action, about 5 s, `role="status"`, the timer paused on focus or hover, Ctrl/Cmd+Z triggering Undo outside text fields and named in the accessible description, the text-only call signature unchanged; then GREEN `frontend/src/components/shell/shellToast.ts` and the renderer in `frontend/src/components/shell/AppShell.tsx`. *(020-FR-048)*
- [x] T071 [US1] Write and observe RED in `frontend/src/features/tasks/__tests__/TaskListPage.test.tsx`: marker chips only for the aggregate (asks, moves tomorrow, not-yet-applied park due), never "Ageing" in the list; accessible name "Asks for a decision. Open decision for <title>"; offline chips stay focusable with `aria-disabled="true"` and the offline reason; re-classified every minute without a refetch; none before activation; then GREEN `frontend/src/features/tasks/TaskListPage.tsx` (D-01). *(020-FR-004, 020-FR-010, 020-FR-040, 020-FR-051)*
- [x] T072 [US1] Write and observe RED `frontend/src/features/review/__tests__/FormulationBlock.test.tsx` (every D-06 state; "Decide" opens D-02 and focus returns to it, or to the panel heading when the task left Next); then GREEN `frontend/src/features/review/FormulationBlock.tsx`, placed in `frontend/src/features/tasks/TaskDetailPanel.tsx`. *(020-FR-001, 020-FR-003, 020-FR-004, 020-FR-009, 020-FR-010, 020-FR-012, 020-FR-046)*
- [x] T073 [US1] Write and observe RED `frontend/src/features/review/__tests__/DecisionDialog.test.tsx` (no navigator yet): a 560 px dialog with focus on the title and a trap; Esc closes with no change unless a form is dirty; keys 1–7 shown as numerals and inactive in text fields; per-row "Saving…"; stale "Task changed elsewhere"; save failed with Ref and Retry; decision not allowed; offline disabled with the reason; the third-stall "Think it through" only when `crt_canvas` is effective; the Undo toast and focus to the next row; a full-height sheet at 390 px; then GREEN `frontend/src/features/review/DecisionDialog.tsx`. *(020-FR-005, 020-FR-006, 020-FR-007, 020-FR-009, 020-FR-011, 020-FR-045, 020-FR-048)*
- [x] T074 [US1] Write and observe RED `frontend/src/features/review/__tests__/reviewFormDrafts.test.ts` and `frontend/src/features/review/__tests__/useLeaveGuard.test.tsx`: drafts under `bb.reviewFormDraft.v1.<origin>.<account>.<task>.<formulation>` (`project.<project id>` for a project's next action), removed on save, discard, formulation change, sign-out or account switch and by a startup/focus sweep after 7 days, never sent or logged; `beforeunload` while dirty; a history entry pushed when the dialog opens, `popstate` treating Back as Close (asking first when dirty, re-pushing on "Keep editing"), in-app links through the same check (no `useBlocker` under the declarative `BrowserRouter`); then GREEN `frontend/src/features/review/reviewFormDrafts.ts` and `frontend/src/features/review/useLeaveGuard.ts`, used by `frontend/src/features/review/DecisionDialog.tsx`. *(020-FR-052)*
- [x] T075 [US1] Write and observe RED `frontend/src/features/review/__tests__/ReviewSettingsSection.test.tsx` and in `frontend/src/features/account/__tests__/AccountSettingsPage.test.tsx` (the threshold control with the floor note; a failed save keeps the old value with Ref); then GREEN `frontend/src/features/review/ReviewSettingsSection.tsx` in `frontend/src/features/account/AccountSettingsPage.tsx` (D-04). *(020-FR-039, 020-FR-045)*
- [x] T076 [US1] Write and observe RED `frontend/src/features/review/__tests__/copyGuard.test.ts`: review-feature strings and rendered markers contain no "overdue", streak wording or rose/red tokens; every `recordTelemetry` event the review feature emits carries ids, codes, counts and timings only, with sentinel title, notes, reason and AI text absent (checklist privacy CHK022); make it GREEN by fixing any offender. *(020-FR-004, 020-FR-038, 020-FR-044)*

**Checkpoint**: US1 works on each platform with an activated owner (activation itself is US2's explainer; tests activate through the API or the CLI seed).

---

## Phase 4: User Story 2 — Auto-park and a shame-free return (Priority: P1) 🎯 MVP (with US1)

**Goal**: The one-time explainer activates the owner; undecided formulations park 7 days after the threshold, server-side and on device, exactly once; "While you were away" returns them.

**Independent Test**: Seed tasks at various ages with no review, acknowledge the explainer, advance time past the "tomorrow" marker and the park point; verify the parked state, the markers, "While you were away" at app open and single and bulk return (quickstart Scenarios 2, 3, 7). Restart mode and "While you were away" as the first review screen are verified with US4.

### Backend (slice PR-15)

- [x] T077 [US2] Write and observe RED `backend/tests/test_review_auto_park.py` (activation): the first `POST /review/explainer/acknowledge` sets `activated_at` to server now, runs the activation clamp and the `activated_at + 14 d` floor in one owner-locked transaction without bumping any task `revision`/`updated_at`, stores a supplied IANA `time_zone` (400 `invalid_time_zone` otherwise) and returns the state body; later or duplicate acknowledgements change nothing, a different `time_zone` on them included (only the activating acknowledgement stores a zone, contracts/http.md §5); an acknowledgement with the flag off still activates; no derived instants and no park before activation. *(020-FR-014, 020-FR-016, 020-FR-018, 020-FR-051)*
- [x] T078 [US2] Make T077 GREEN in `backend/app/modules/tasks/review_service.py` and `backend/app/api/review.py`; log `review_activated`. *(020-FR-016, 020-FR-051)*
- [x] T079 [US2] Write and observe RED in `backend/tests/test_review_auto_park.py` (sweep, driven by `_run_review_maintenance_sweep(container)` with `frozen_clock`): due vs not due; every park in the matrix preceded by a ≥ 24 h `moves_tomorrow` window and listed in `unseen_parks`; the FR-039, FR-046, time-zone and sweep-gap floors; skipped after reformulate, move or extend; a second park of the same formulation is a no-op; the park keeps project, tags, notes, due date and priority and writes `parked` with `clock_before` and the `review_park_acks` row (`parked_at`, `from_revision`, `source: sweep`) in the same transaction; key `auto-park:<task_id>:<formulation_id>:<from_revision>`, so park → yield + cosmetic save → parked again by the next run with no idempotency conflict; clock repair with a 14-day floor; retention with the flag OFF (a decision undo snapshot null after 8 days, a bulk-release `clock_before` null after 7 days, `navigator_usage` rows older than 35 days deleted); one owner's failure isolated and logged with `type(exc).__name__`; a `User` resolved per owner for `is_effective`; the return shape of `_run_privacy_maintenance_sweep` unchanged (`backend/tests/test_crt_receipt_retention.py:364`); optionally, a sweep-duration bound: one case seeds 20 activated owners × 200 Next tasks and asserts the run's measured `duration_ms` stays below the 60 s sweep interval (plan "Performance Goals"; a generous ceiling against an accidental per-task query, not a benchmark). *(020-FR-012, 020-FR-013, 020-FR-014, 020-FR-016, 020-FR-018, 020-FR-039, 020-FR-043, 020-FR-046, 020-SC-006)*
- [x] T080 [US2] Make T079 GREEN: `ReviewService.run_auto_park_sweep(now)` and `run_review_retention(now)` in `backend/app/modules/tasks/review_service.py` (candidates selected outside the lock, owner-locked transactions of at most 50 tasks that re-read before writing, no I/O under the lock; the idle-run close delegated to `ReviewFlowService`, a no-op until PR-11); `_run_review_maintenance_sweep(container)` as its own `try/except` inside `_run_privacy_maintenance_sweep` and called from `_run_maintenance_sweep` in `backend/app/main.py`; the log line `review_sweep owners=%d parked=%d repaired=%d closed=%d gap_floors=%d snapshots_nulled=%d duration_ms=%d`. *(020-FR-012, 020-FR-014, 020-FR-043)*
- [x] T081 [US2] Write and observe RED in `backend/tests/test_review_auto_park.py` (device parks and the yield rule): `POST /tasks/{task_id}/auto-park` parks iff the flag is effective, the owner is activated, the task is in Next with class `park_due` and not already parked for its formulation, otherwise `200 {"applied": false}`; two devices → one park, both 200; the yield applies when `parked.formulation_id == formulation_id`, `parked.from_revision <= expected_revision <= task.revision` and `client_decided_at < parked.at` (restore `clock_before` exactly, apply the decision, `"yielded_auto_park": true`), including an `extend` made offline before the park; an offline notes edit then an offline card decision with the park between → notes kept, decision applied; a notes-only PATCH queued before the park → 409 and the park stands. *(020-FR-011, 020-FR-013, 020-SC-007)*
- [x] T082 [US2] Make T081 GREEN: the auto-park route in `backend/app/api/review.py` and the yield rule in `ReviewService.decide` (`backend/app/modules/tasks/review_service.py`); log `review_auto_park applied=… source=sweep|device yielded=…`. *(020-FR-013)*
- [x] T083 [US2] Write and observe RED in `backend/tests/test_review_auto_park.py` (park acknowledgements): `unseen_parks` in `GET /review/state`; `POST /review/parks/acknowledge` (at most 200 items) is idempotent and ignores unknown and foreign ids with byte-identical responses; returning a parked task through the existing `transition move → next` starts a new formulation, clears `parked` and upserts `returned_at` on its park acknowledgement in the same transaction. *(020-FR-015)*
- [x] T084 [US2] Make T083 GREEN in `backend/app/modules/tasks/review_service.py`, `backend/app/api/review.py` and the transition hook in `backend/app/modules/tasks/service.py`. *(020-FR-015)*
- [x] T085 [US2] Write and observe RED `backend/tests/test_review_cli.py`: `python -m app.cli review-seed-aged-task` (a Next task whose formulation started N days ago; the owner activated) and `review-run-sweep` (one `_run_review_maintenance_sweep` run) refuse to run unless `BRAIN_BUDDY_ENV=test`; then GREEN in `backend/app/cli.py` (research R21).
- [x] T086 [US2] Write the golden operation traces `backend/tests/fixtures/review_traces_tasks.json` (decide, decide stale, auto-park `applied: false`, yield after a queued notes edit, settings 409, flag off with queued writes, a decision retried after the 24 h idempotency retention answered as already applied); observe RED, then GREEN, `backend/tests/test_review_traces.py` against the real API; copy the file byte-identically to `ios/BrainBuddyKit/Tests/BrainBuddySyncTests/Resources/review_traces_tasks.json` and add both to the drift guard in `backend/tests/test_review_formulation_vectors.py`. *(020-FR-013, 020-SC-007)*

### iOS core (slice PR-03)

- [x] T087 [US2] Write and observe RED in `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ReducerReviewTests.swift`, `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/QueriesReviewTests.swift` and `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ReviewPlannersTests.swift`: `acknowledgeExplainer(timeZone)` writes only the activation instant (`local.activatedAt` when account-less) and changes no task's list, title, notes or organisation (clock bookkeeping only); `explainerSeenLocally` suppresses the explainer until the pulled `activated_at` arrives; linking an account-less install sends `acknowledgeExplainer` when the device had seen it and the account has no activation; the post-replay activation step clamps every Next clock to the activation instant and raises its floor to `activatedAt + 14 d` whatever the fold order; `autoParkTask` parks iff activated and `park_due`, storing `clockBefore`; `dueAutoParks` is empty before activation; `unseenParks`; `explainerNeeded`; `WhileAwayPresentation.shouldShowAtAppOpen` (dismissed today → not again today, shown tomorrow, always first in the review). *(020-FR-012, 020-FR-014, 020-FR-015, 020-FR-016, 020-FR-018, 020-FR-051)*
- [x] T088 [US2] Make T087 GREEN: `autoParkTask` and `review(.acknowledgeExplainer)` / `review(.acknowledgeParks)` in `ios/BrainBuddyKit/Sources/BrainBuddyCore/Commands.swift`; `ios/BrainBuddyKit/Sources/BrainBuddyCore/Reducer+Review.swift`; `ios/BrainBuddyKit/Sources/BrainBuddyCore/Queries+Review.swift`; `WhileAwayPresentation` in `ios/BrainBuddyKit/Sources/BrainBuddyCore/ReviewPlanners.swift`.
- [x] T089 [US2] Write and observe RED in `ios/BrainBuddyKit/Tests/BrainBuddySyncTests/ReviewSyncTests.swift` and `ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/WorkspaceReviewTests.swift`: two workspaces offline past the park instant both park, then sync → one server park and no `SyncIssue`; `applied: false` is acknowledged and never re-issued for that formulation (`issuedAutoParks`); a device clock 2 days ahead, online → no local park, no M-09 entry, no "Return to Next" on a Next task; an offline notes edit and an offline card decision with a server park between → decision applied, 0 sync issues; the flag turned off with 3 queued review commands → 0 set-asides, 0 reverted decisions; a queued edit survives activation; `applyDueAutoParks()` applies at most 10 parks per call and never parks a task that was not classified `moves_tomorrow` for at least the preceding 24 hours; account-less parks are final; `runLocalReviewMaintenance()` nulls undo and bulk snapshots, closes idle runs and deletes drafts after 7 days. *(020-FR-012, 020-FR-013, 020-FR-014, 020-FR-040, 020-FR-043, 020-FR-051, 020-SC-006, 020-SC-007)*
- [x] T090 [US2] Make T089 GREEN: `applyDueAutoParks()`, `runLocalReviewMaintenance()` and the `serverClockOffset` handling in `ios/BrainBuddyKit/Sources/BrainBuddyWorkspace/Workspace.swift`; the `GET /review/state` pull after the task pull in `ios/BrainBuddyKit/Sources/BrainBuddySync/SyncEngine+Pull.swift`; auto-park, explainer, park acknowledgements and the yield rule in `ios/BrainBuddyKit/Sources/BrainBuddyFakeServer/FakeServer+Review.swift`.
- [x] T091 [US2] Write and observe RED `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ReviewAccountLinkingTests.swift` and, in `ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/WorkspaceReviewTests.swift`, the linking case (contracts/ios-commands.md §7 "Account linking and local auto-parks", owner decision 2026-10-06): `ReviewAccountLinking.convertLocalAutoParks(_:)` turns every unsent `autoParkTask` into an ordinary `transitionTask` move to Someday at the same outbox position and `issuedAt` (no park marker, no `clockBefore`), drops the local park markers and any unsent `acknowledgeParks` entries for those tasks, removes every unsent `decideTask` of type `extend` (and its queued `undoDecision`) and records its task id in `local.linkedExtensionNotices`, keeps every other operation (other `decideTask` types, `undoDecision`, sessions, bulk releases, settings, consent) unchanged and in order, and is deterministic; an account-less workspace with 3 local parks (one seen on M-09), 2 unsent decisions of type `reformulate` and `waiting`, and 1 unsent `extend` on another Next task signs in against `BrainBuddyFakeServer` → the 3 tasks are in Someday on the server with `parked` null, none is back in Next, M-09 lists none of them, the `reformulate` and `waiting` decisions are applied, the `extend` is never sent (no `extension_not_due`), its task stays in Next and M-09 lists it once as the "account linked: extension restarted" information row, 0 sync issues; then GREEN in the new `ios/BrainBuddyKit/Sources/BrainBuddyCore/ReviewAccountLinking.swift` (with `local.linkedExtensionNotices` decoded with `decodeIfPresent`) and `Workspace.signIn` in `ios/BrainBuddyKit/Sources/BrainBuddyWorkspace/Workspace.swift` (the step runs after `flush()` and before the store is uploaded). *(020-FR-014, 020-FR-040, 020-SC-007)*

### iOS app (slice PR-04)

- [x] T092 [US2] M-26 in the new `ios/BrainBuddy/Screens/Review/AutoParkExplainerSheet.swift`, presented before anything else (also before a widget deep link and M-09) from `ios/BrainBuddy/App/RootView.swift`: three points and the grace date; "Change the number of days" (inline 7/14/21/28 with the floor note); "Got it" or Close queue `acknowledgeExplainer` with the device zone; an app kill shows it again; account-less records on the device; VoiceOver focus to its heading on appear and to the tab's navigation title on close; the sheet body scrolls up to Dynamic Type AX5 with "Got it" reachable (design "Mobile viability"). *(020-FR-016, 020-FR-018, 020-FR-039, 020-FR-051)*
- [x] T093 [US2] M-09 in the new `ios/BrainBuddy/Screens/Review/WhileYouWereAwaySheet.swift`: per-row "Return to Next", "Return all N", "Continue" (acknowledges); swipe-down does not acknowledge and the sheet shows again at most once per calendar day (`WhileAwayPresentation`); archived-project and changed-elsewhere partial failures; "more parks waiting"; the "account linked: extension restarted" information row (no Return button, shown once from `local.linkedExtensionNotices`, cleared on Continue or Close); offline; the focus rules; rows and buttons wrap and the list scrolls up to Dynamic Type AX5 (design "Mobile viability"). Call `applyDueAutoParks()` and `runLocalReviewMaintenance()` on load, foreground and background refresh in `ios/BrainBuddy/App/BrainBuddyApp.swift`. *(020-FR-012, 020-FR-014, 020-FR-015, 020-SC-006)*
- [ ] T094 [US2] Record `specs/020-weekly-review/evidence/manual-ios-increment1.md` from a simulator or device run on synthetic data (labelled manual, one entry per id): `.presentationDetents([.large])` (`020-FR-047`), `interactiveDismissDisabled` (`020-FR-052`), the Undo announcement and its ≥ 10 s window (`020-FR-048`), 44 pt targets and AA contrast on markers and Undo, VoiceOver focus on M-26 and M-09, and M-01 – M-04, M-09 and M-26 at Dynamic Type AX5 with no clipped or truncated control and every body scrolling (design "Mobile viability"); plus the Xcode-lane build of the app target.
- [x] T173 [US2] Write and observe RED, then GREEN, `ios/BrainBuddyKit/Tests/BrainBuddySyncTests/ReviewTaskTraceReplayTests.swift` (the decision and park part of the trace replay, moved out of T136 so increment 1 has its fake-server parity check; `/speckit-analyze` G4): the copied `review_traces_tasks.json` (T086, slice PR-15) replays against `BrainBuddyFakeServer` with the recorded statuses and responses — decide, decide stale, auto-park `applied: false`, yield after a queued notes edit, settings 409, flag off with queued writes, and a decision retried after the 24 h idempotency retention answered as already applied; fix any fake-server drift in `ios/BrainBuddyKit/Sources/BrainBuddyFakeServer/FakeServer+Review.swift`. Names carry `020-FR-013` and `020-SC-007`. *(020-FR-011, 020-FR-013, 020-SC-007)*

### Web (slice PR-05)

- [x] T095 [P] [US2] Write and observe RED `frontend/src/features/review/__tests__/AutoParkExplainer.test.tsx` (D-05: focus on the heading and trapped; "Got it", Close and Esc acknowledge with the browser's time zone; "Change the number of days"; saving failed with Ref and Retry; "Got it" disabled offline; a full-height sheet at 390 px; never shown once `explainer_seen`); then GREEN `frontend/src/features/review/AutoParkExplainer.tsx`. *(020-FR-016, 020-FR-018, 020-FR-045, 020-FR-051)*
- [x] T096 [P] [US2] Write and observe RED `frontend/src/features/review/__tests__/WhileYouWereAway.test.tsx` and `frontend/src/features/review/__tests__/wywaPresentation.test.ts` (the once-a-day vectors; key `bb.reviewWywaLastShown.v1.<origin>.<account>` removed on sign-out; Esc and Close do not acknowledge; per-row "Returning…", return failed with Ref, partial failure, offline, "continue not saved", focus to the main list heading); then GREEN `frontend/src/features/review/WhileYouWereAway.tsx` and `frontend/src/features/review/wywaPresentation.ts`. *(020-FR-011, 020-FR-015, 020-FR-045)*
- [x] T097 [US2] Mount D-05, then the While-you-were-away dialog, at web open through the new `frontend/src/features/review/ReviewStartupDialogs.tsx` in `frontend/src/components/shell/AppShell.tsx`, only when the flag is effective; extend `frontend/src/components/shell/__tests__/AppShell.test.tsx` (RED first) with the order and the flag-off case, keeping the existing "Weekly review — Coming soon" assertions unchanged. *(020-FR-015, 020-FR-042, 020-FR-051)*

**Checkpoint**: Increment 1 (US1 + US2) is complete on backend, iOS and web; the flag can go to SELECTED_USERS for the owner.

---

## Phase 5: User Story 3 — The AI navigator proposes a first step (Priority: P2)

**Rescope 2026-10-07**: only the backend (slice PR-07, in flight) and the already merged iOS consent commands (T108) stay in this feature. The iOS, downloadable-model and web client tasks (T109 – T125, former slices PR-08, PR-09, PR-10) are `DEFERRED` to a follow-up feature (Notes).

**Goal**: 1–3 grounded first steps from Apple's on-device model, a separately downloaded model, or the consented cloud provider; nothing written without confirmation.

**Independent Test**: With a stubbed on-device model and the deterministic cloud provider, request suggestions for seeded stalled tasks; verify 1–3 proposals, no write before confirmation, the consent flow, the fallback messaging, offline behaviour, and no task content in logs (quickstart Scenario 4).

### Backend navigator (slice PR-07)

- [x] T098 [US3] Write and observe RED, as the first test of the slice, `backend/tests/test_review_navigator.py` case `test_020_FR_025_container_build_raises_without_key`: the container build raises when `BRAIN_BUDDY_REVIEW_NAVIGATOR_PROVIDER=openai` and the variable named by `BRAIN_BUDDY_REVIEW_NAVIGATOR_API_KEY_ENV` is unset or empty (the message names the variable, never its value), for `deterministic` outside TEST and for an unknown provider; `disabled` builds and yields `available: false` / 503 `navigator_disabled`. *(020-FR-025)*
- [x] T099 [US3] Make T098 GREEN: the navigator settings in `backend/app/core/config.py` (`…_PROVIDER=disabled`, `…_MODEL=gpt-4o-mini`, `…_API_KEY_ENV=OPENAI_API_KEY`, `…_TIMEOUT_SECONDS=8`, `…_MAX_INPUT_TOKENS=6000`, `…_MAX_OUTPUT_TOKENS=300`, `…_MAX_COST_USD=0.01`, `…_MAX_DAILY_COST_USD=0.20`), the adapter `backend/app/ai/review_navigator.py` beside `title_completion.py` (`disabled`/`deterministic`/`openai`, JSON-schema response format, temperature 0.4) and `_build_review_navigator_provider` in `backend/app/container.py`. *(020-FR-025)*
- [x] T100 [US3] Write and observe RED in `backend/tests/test_review_navigator.py`: `reduce_notes` against the shared vectors (at most 6 000 characters unchanged, else the first lines up to 2 000 + `…` + the last lines up to 4 000, whole lines, `truncated = true`); the output rules 1–4 of contracts/navigator.md §2 (Smart Add tokens, over 200 characters, multi-line, duplicates of the title or `open_task_titles` by `formulation_key`, the grounding check, the clarifying-question fallback, `malformed`); the strict request schema rejects any extra field including a language field. *(020-FR-019, 020-FR-020, 020-FR-021)*
- [x] T101 [US3] Make T100 GREEN in `backend/app/modules/tasks/navigator.py`: the `NavigatorProvider` port, `NavigatorInput`, `reduce_notes`, `validate_navigator_output`, the consent rules with the constant `CONSENT_TEXT_VERSION`, and `NavigatorService` (no HTTP client; the import-linter contract of T034 holds). *(020-FR-019, 020-FR-021)*
- [x] T102 [US3] Write and observe RED in `backend/tests/test_review_navigator.py` (endpoints): `GET /review/navigator` and `DELETE /review/navigator/consent` work with the flag off (revoke → 204, the next flag-on suggestion → 400 `navigator_consent_required`); grant → 400 `provider_mismatch` / `consent_text_outdated`; a revoked or older-version consent → 400 `navigator_consent_required`; suggestions and grant → 404 with the flag off; rate limit → 429 `navigator_rate_limited` with `Retry-After`; per-call and daily caps → 429 `navigator_cost_cap`; timeout, provider error and malformed output → 503 with `reference_id`; input too large → 400; a provider stub that takes `command_lock` for another owner neither deadlocks nor waits (reserve → call with no lock → settle; the reservation released on timeout); after a suggestion there is no idempotency record, no `task-commands/` entry and no sentinel text; `navigator_usage.shown` counted; a later decision stores `ai_use` and `navigator_request_id` and no proposal text; one log line of codes and counts. *(020-FR-024, 020-FR-025, 020-FR-026, 020-FR-044, 020-FR-045)*
- [x] T103 [US3] Make T102 GREEN: the routes and a local `get_navigator_service` dependency in `backend/app/api/review_navigator.py`, `navigator_rate_limiter` (20 calls / 10 min per owner) in `backend/app/core/rate_limit.py`, and the `NavigatorService` wiring in `backend/app/container.py`. *(020-FR-024, 020-FR-025)*
- [x] T104 [US3] Write the synthetic evaluation set `backend/tests/fixtures/navigator/eval_v1.json` (about 48 cases: 24 RU, 12 EN, 12 RU/EN code-switched; every stall reason and none; about 25 % expecting one question; notes with and without people, places and amounts; 0/5/20 sibling titles; each with `expected_kind`, `allowed_entities`, `sibling_titles`) and a synthetic recorded-output sample `backend/tests/fixtures/navigator/recorded_v1_sample.json`; observe RED, then GREEN, `backend/tests/test_review_navigator_eval.py`, the deterministic screen runner over recorded outputs. No real user data; generating real outputs is owner-run and approval-gated, never unattended or from a subagent (`/verify-live` rules). *(020-SC-005, 020-FR-021)*
- [x] T105 [US3] Document the navigator variables in `.env.example` with the runbook line "set `BRAIN_BUDDY_REVIEW_NAVIGATOR_PROVIDER=disabled` before rotating or removing the key, and set it back after the new key is in place" (c2 AH-05).
- [x] T106 [US3] Extend `frontend/src/pages/__tests__/PrivacyPolicyPage.test.tsx` (RED first), `frontend/src/pages/PrivacyPolicyPage.tsx` and `docs/data-retention.md`: the navigator's purpose, the five data items sent, the per-owner consent and its revocation, and that the provider keeps its copy under its own policy (30 days for OpenAI API data) beyond account purge (c2 PC-05). *(020-FR-024, 020-FR-043)*
- [x] T107 [US3] Write and observe RED in `frontend/src/pages/__tests__/PrivacyPolicyPage.test.tsx` a case named for `020-FR-024`: the navigator section says that notes and task titles are sent to the provider as written, including any names or details of other people in them, only under the person's own consent and with nothing redacted (owner decision 2026-10-06, privacy checklist CHK011, contracts/navigator.md §6); then GREEN by adding that sentence to the navigator section of `frontend/src/pages/PrivacyPolicyPage.tsx`. *(020-FR-024)*

### iOS core consent commands (slice PR-03)

- [x] T108 [US3] Write and observe RED in `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ReducerReviewTests.swift` and `ios/BrainBuddyKit/Tests/BrainBuddySyncTests/ReviewSyncTests.swift` (`grantNavigatorConsent` / `revokeNavigatorConsent` are idempotent, a revoke blocks cloud use locally at once, offline); then GREEN in `ios/BrainBuddyKit/Sources/BrainBuddyCore/Commands.swift`, `ios/BrainBuddyKit/Sources/BrainBuddyCore/Reducer+Review.swift` and `ios/BrainBuddyKit/Sources/BrainBuddySync/GTDCommand+Sync.swift`. *(020-FR-024)*

### iOS navigator (slice PR-08)

- DEFERRED T109 [US3] Write and observe RED `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/NavigatorValidatorTests.swift`: `NavigatorInputBuilder` builds exactly the FR-019 input with the shared `reduce_notes` vectors; `NavigatorOutputValidator` rules 1–4; `NavigatorProposalFilter.dropDuplicates` drops a duplicate of the 21st (unsent) sibling; `NavigatorRouter` picks Apple on-device when available for the task language, else the remembered fallback (`downloaded` if installed, `cloud` only with current consent, an account and `available: true`), else `unavailable(reason)`, never cloud silently; account-less cloud → `noAccount`; the route caption resolved before the tap; cancellation reported as `.cancelled`; with no downloadable model available the choice shows the download row unavailable and no non-AI path depends on it (the FR-049 clause that holds before PR-09; its other clauses are PR-09's). *(020-FR-019, 020-FR-020, 020-FR-021, 020-FR-022, 020-FR-023, 020-FR-024, 020-FR-049)*
- DEFERRED T110 [US3] Make T109 GREEN in the new `ios/BrainBuddyKit/Sources/BrainBuddyCore/Navigator.swift` (`NavigatorInput`, `NavigatorInputBuilder`, `NavigatorOutputValidator`, `NavigatorProposalFilter`, `NavigatorRouter`, the `NavigatorModel` protocol and its availability and error enums) and `ios/BrainBuddyKit/Sources/BrainBuddyFakeServer/StubNavigatorModel.swift`.
- DEFERRED T111 [US3] Write and observe RED `ios/BrainBuddyKit/Tests/BrainBuddyAPITests/NavigatorAPITests.swift` (requests carry no language field and echo the consent; 400/429/503/404 reasons map to `NavigatorError` with the reference id); then GREEN `ios/BrainBuddyKit/Sources/BrainBuddyAPI/NavigatorAPI.swift` (`CloudNavigatorModel`). *(020-FR-024, 020-FR-025, 020-FR-045)*
- DEFERRED T112 [US3] Implement `ios/BrainBuddy/Navigator/AppleNavigatorModel.swift` behind `#if canImport(FoundationModels)`: `SystemLanguageModel.default.availability` → reasons; the task language from `NLLanguageRecognizer` must be in `supportedLanguages`; `unsupportedLanguageOrLocale` → `unavailable(.unsupportedLanguage)`; a `@Generable` `NavigatorReply` with `@Guide(.maximumCount(3))`; the locale pin ("The person's locale is <id>." / "You MUST respond in <language>."); the §2 validation still runs. *(020-FR-022, 020-FR-023)*
- DEFERRED T113 [US3] Write and observe RED first, named for `020-FR-026`: in `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/NavigatorValidatorTests.swift`, `NavigatorAIUse.resolve(shownProposals:pickedProposal:savedText:requestID:)` gives `as_is` when a picked proposal is confirmed unedited, `edited` when it was picked and then edited, `not_used` when proposals were shown and the person saved their own text, `none` when no proposal was shown, and carries the server `request_id` only for a cloud route (on-device → `navigatorRequestID == nil`); in `ios/BrainBuddyKit/Tests/BrainBuddyAPITests/NavigatorAPITests.swift`, the `decideTask` built from each case is encoded through the PR-03 request body and the wire JSON is asserted (`"ai_use": "as_is" | "edited" | "not_used"`, `"navigator_request_id"` equal to the UUID the stubbed cloud response returned, `null` on device; no proposal text anywhere in the body). Then GREEN with `NavigatorAIUse` in `ios/BrainBuddyKit/Sources/BrainBuddyCore/Navigator.swift` and its use in `ios/BrainBuddy/Screens/Review/DecisionForms.swift`, and build the navigator UI: the new `ios/BrainBuddy/Navigator/NavigatorPanel.swift` (M-05 states incl. notes shortened, interrupted "Suggestion stopped." · "Suggest again", the clarifying question appending the answer to notes through a normal `updateTask` and re-running), `ios/BrainBuddy/Navigator/ModelChoiceSheet.swift` (M-06 choice per reason, cloud unavailable; the download row shown unavailable until PR-09) and `ios/BrainBuddy/Navigator/CloudConsentSheet.swift` (M-07: the provider and the five items, "Nothing else is sent." and "Notes are sent as written, including any names in them." (owner decision 2026-10-06), consent after revoke, consent text changed, declined, errors with Ref, offline, no account, the clarifying question (cloud)); "Suggest · on this iPhone" / "Suggest · OpenAI" in `ios/BrainBuddy/Screens/Review/DecisionForms.swift`; focus returns to Suggest or the first proposal when M-06 or M-07 closes. *(020-FR-019, 020-FR-020, 020-FR-021, 020-FR-022, 020-FR-023, 020-FR-024, 020-FR-025, 020-FR-026, 020-FR-045, 020-FR-052)*
- DEFERRED T114 [US3] M-08 in the new `ios/BrainBuddy/Navigator/ProjectNextActionBlock.swift`, shown where `ios/BrainBuddy/Screens/Lists/TaskListScreen.swift` says "This project needs a next action": proposals, "Add to Next actions" creating the task in Next in that project with `createTask`, the "model question" and empty-project states whose answer field is the next action itself, the typed next action kept as a draft. *(020-FR-019, 020-FR-020, 020-FR-021, 020-FR-052)*
- DEFERRED T115 [US3] M-23 "Suggestions" in the new `ios/BrainBuddy/Screens/Settings/SuggestionsSettingsSection.swift`, placed in `ios/BrainBuddy/Screens/Settings/SettingsScreen.swift`: on-device status, the fallback choice (Ask me / Downloaded / Cloud), the cloud consent switch naming the provider with an immediate local revoke and the offline note, and the "feature switched off, consent stored" state. *(020-FR-023, 020-FR-024)*
- DEFERRED T116 [US3] Record `specs/020-weekly-review/evidence/manual-ios-navigator.md` (labelled manual, synthetic data): `AppleNavigatorModel` on an Apple-Intelligence device (EN), with the time from tapping Suggest to the first visible proposal text measured over 5 runs on that device (each run and the median recorded; plan "Performance Goals": on-device first token visible ≤ 2 s, placeholder lines after 300 ms; a miss is recorded as a finding for the owner, not hidden), the unsupported-language path to M-06, VoiceOver focus after M-06 / M-07 close, the M-07 consent line about notes (`020-FR-024`), M-05 – M-08 at Dynamic Type AX5 with every sheet body scrolling and no clipped control (design "Mobile viability"), and the Xcode-lane build.

### Downloadable on-device model (slice PR-09, late; may slip)

- DEFERRED T117 [US3] Write `docs/decisions/0028-ios-downloadable-navigator-model-dependency.md` (re-check the number when the slice starts): the dependency exception for the Core AI `coreai-models` package (app target only, never `BrainBuddyCore`), the model chosen by the offline SC-005 evaluation (Qwen3-1.7B 4-bit vs Gemma 4 E2B; MLX Swift as plan B), an Apple-hosted Background Assets pack, `#available(iOS 27, macOS 27, *)` with a memory check and `increased-memory-limit`; amend "No third-party dependencies" in `ios/AGENTS.md` for that one package. Needs the owner's recorded approval (ASK). *(020-FR-023)*
- DEFERRED T118 [US3] Write and observe RED `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ModelDownloadMachineTests.swift` with injected `ModelDownloader` and `StorageProbe`: request-only start; progress; interruption and resume, including after an app kill from persisted state; finished while away; cancel removes the partial file; insufficient storage; retry; switch to cloud; delete; never required for non-AI parts; the router never falls back silently to cloud. *(020-FR-023, 020-FR-049)*
- DEFERRED T119 [US3] Make T118 GREEN in the new `ios/BrainBuddyKit/Sources/BrainBuddyCore/ModelDownloadMachine.swift` and route the downloaded model in `ios/BrainBuddyKit/Sources/BrainBuddyCore/Navigator.swift`. *(020-FR-023, 020-FR-049)*
- DEFERRED T120 [US3] Implement `ios/BrainBuddy/Navigator/DownloadedNavigatorModel.swift` (`#available(iOS 27, macOS 27, *)`, memory check, `.notDownloaded` / `.deviceNotEligible` otherwise; the same prompt, `@Generable` reply and validation); add the M-06 download states to `ios/BrainBuddy/Navigator/ModelChoiceSheet.swift` and the M-23 downloading, interrupted and delete-with-confirmation rows to `ios/BrainBuddy/Screens/Settings/SuggestionsSettingsSection.swift`; the entitlement and the Background Assets pack in `ios/project.yml`; the disk-space required-reason entry in `ios/Shared/PrivacyInfo.xcprivacy`. *(020-FR-023, 020-FR-049)*
- DEFERRED T121 [US3] Extend `frontend/src/pages/__tests__/PrivacyPolicyPage.test.tsx` (RED first), `frontend/src/pages/PrivacyPolicyPage.tsx` and `docs/data-retention.md` with the downloaded model file, the device-local navigator preference, and the download request to Apple's asset hosting, which carries no task content (data-model E10). *(020-FR-049, 020-FR-043)*
- DEFERRED T122 [US3] Record the downloaded-model SC-005 evaluation cell as aggregate scores only in `specs/020-weekly-review/evidence/navigator-eval-downloaded.md` (owner-generated, blind-graded; gate ≥ 50 % accepted overall and in the Russian subset, 0 confirmed invented facts) and the device checks in `specs/020-weekly-review/evidence/manual-ios-downloaded-model.md`. *(020-SC-005)*

### Web navigator (slice PR-10)

- DEFERRED T123 [US3] Write and observe RED `frontend/src/features/review/__tests__/navigatorInput.test.ts`: the shared `reduce_notes` vectors; the exact FR-019 input with no language field; the project-wide duplicate filter over every page of `GET /tasks?project_id=…` drops a duplicate of the 21st (unsent) title; then GREEN `frontend/src/features/review/navigatorInput.ts`. *(020-FR-019)*
- DEFERRED T124 [US3] Write and observe RED `frontend/src/features/review/__tests__/NavigatorPanel.test.tsx` (the D-02 navigator states: the consent dialog focusing "Not now" and showing "Notes are sent as written, including any names in them." below "Nothing else is sent." (owner decision 2026-10-06); proposals as a radio group; notes shortened; input too large; timeout, cost cap and malformed banners with Ref; suggestions unavailable; the cloud clarifying question with "adding answer", "answer not saved" (draft kept), "answer saved, suggestion failed" and "answer saved, card current" adopting its own notes edit's revision; a revoke stops the tab at once; the D-02 "loading (suggesting)" state with "Stop", and "Stop" aborting the in-flight fetch through its `AbortController` (the mocked fetch observes the abort signal), leaving the form field and the card unchanged and showing "Suggestion stopped." with "Suggest again", which re-runs the request; the D-02 "interrupted (suggesting)" state: closing the dialog while "Asking OpenAI…" aborts the request and applies nothing; and, named for `020-FR-026`, the decision request body asserted on the wire: confirming a picked proposal unedited sends `"ai_use": "as_is"`, editing it first sends `"edited"`, saving the person's own text after proposals were shown sends `"not_used"`, and each echoes the server's `request_id` as `navigator_request_id` (no proposal text in the body), while a decision with no suggestion requested sends `"ai_use": "none"` and `navigator_request_id: null`); then GREEN `frontend/src/features/review/NavigatorPanel.tsx`, `frontend/src/features/review/CloudConsentDialog.tsx`, the Suggest entry and the `ai_use` / `navigator_request_id` fields of the decision in `frontend/src/features/review/DecisionDialog.tsx` and the abortable navigator calls in `frontend/src/api/review.ts`. *(020-FR-019, 020-FR-020, 020-FR-021, 020-FR-024, 020-FR-025, 020-FR-026, 020-FR-045, 020-FR-052)*
- DEFERRED T125 [US3] Write and observe RED in `frontend/src/features/review/__tests__/ReviewSettingsSection.test.tsx` and `frontend/src/features/account/__tests__/AccountSettingsPage.test.tsx`: the D-04 cloud consent switch names the provider, shows "Turning off…" until the `DELETE` succeeds, and is still shown when the flag is off and a consent exists; then GREEN `frontend/src/features/review/ReviewSettingsSection.tsx` and `frontend/src/features/account/AccountSettingsPage.tsx`. *(020-FR-024)*

**Checkpoint**: Increment 2 (US3) is the PR-07 backend only; no client calls it until the follow-up feature, and it stays behind the flag.

---

## Phase 6: User Story 4 — The guided weekly review (Priority: P2)

**Goal**: Quick and full reviews with skip, leave-and-resume on any device, restart mode, the capacity mirror, Waiting/Someday passes and the ten-count summary.

**Independent Test**: Seed a realistic task set and run both modes end-to-end; verify each step's content, skip/resume, partial completion, the capacity mirror numbers, and the stored summary and answer (quickstart Scenario 5).

### Backend review flow (slice PR-11)

- [x] T126 [US4] Write and observe RED `backend/tests/test_review_flow_api.py` (runs): `POST /review/sessions` with a client `id` (`review_<uuid>`), mode, entry, origin and `skip_steps`; without `replace_open` and an open run → 409 `open_session_exists`; with it the open run ends `partial` or `abandoned` by the E3 rule; replay only by Idempotency-Key; a reused `id` under another key with different identifying fields (`mode` or `origin`) → 409 `id_conflict`, and a reused `id` under another key whose stored session matches → 201 with the stored session and nothing applied (no second run, nothing replaced); a start retried after the 24 h idempotency retention (`frozen_clock`) whose stored run matches (same `mode` and `origin`) → success with the stored run and nothing replaced again, even though another run was opened since and the retry carries `replace_open: true` (the match is checked first), a non-matching one → `id_conflict` (contracts/http.md "Retry after the idempotency retention"); `PATCH` merges monotonically (`finished` > `skipped` > `pending`, last-writer `current_step`, additive `inbox_processed_delta` incl. −1 and `active_seconds`, a set-aside set, no version conflict, ignored after finish); `PATCH` without `progress_id` → 422; the same `progress_id` and body resent within and after the 24 h retention → 200 with the merged session, `active_seconds_by_step` and `counts.inbox_processed` grown once, `current_step` not rewound by the late retry; the same `progress_id` with another body → 409 `id_conflict` and nothing merged; `applied_progress` is not in `SessionResponse` and is dropped when the run ends (contracts/http.md §6 "Progress is replay-safe"); `finish` means Done only → `completed` with qualifying activity, otherwise `completed_empty`, idempotent; leaving keeps the run `open` and counted once it has qualifying activity; the 7-day idle close (through the sweep hook of T080) makes it `partial` or `abandoned`; the response carries exactly the `SessionResponse` fields; unknown and foreign `session_id` on `GET /review/queues/{step}` give the same 404 body (`second_api_client`); with the flag off `GET /review/sessions/{id}` and the queues → 404 while the writes are accepted. *(020-FR-011, 020-FR-027, 020-FR-029, 020-FR-033, 020-FR-045, 020-SC-001, 020-SC-004)*
- [x] T127 [US4] Write and observe RED in `backend/tests/test_review_flow_api.py` (queues): `wins` (completed in the last 7 days, with the count); `decisions` = a snapshot of the aggregate in formulation-clock §5 order, stable after a threshold change; `rest_of_next` meta (41 Next and 36 completions in 4 weeks → `weekly_average_4w` 9, `implied_weeks` about 4.5; `null` with fewer than 4 weeks or no completions); `waiting` (older than 7 days, no current receipt, oldest first); `someday` (no current receipt including `release` receipts, not auto-parked in the last 30 days, never-reviewed first, then oldest review, oldest `updated_at`, id; at most 7; `eligible_total`); `projects` without a next action; `dates` for 14 days grouped by local day; SC-002: after a completed run with no set-aside, every queued task that still asks has a decision on its current formulation in this run (a cosmetic save counts) and no other `asks_for_decision` task is undecided; restart mode at 21 days from the last counted review, from `onboarded_at` when never reviewed, never before onboarding, with seeds held in Next by an extension, a floor or an ended due-date pause. *(020-FR-017, 020-FR-028, 020-FR-031, 020-FR-032, 020-FR-034, 020-FR-050, 020-SC-002)*
- [x] T128 [US4] Make T126 and T127 GREEN: `ReviewFlowService` in `backend/app/modules/tasks/review_flow.py` (on `review_rules.py`), the routes in `backend/app/api/review_flow.py`, the `review_session:` reconstructor and the idle-close hook in `backend/app/modules/tasks/review_service.py`, and the run queries in `backend/app/modules/tasks/review_repository.py`; log `review_run` (mode, status, counts). *(020-FR-027, 020-FR-028, 020-FR-029)*
- [x] T129 [US4] Write and observe RED in `backend/tests/test_review_flow_api.py` (bulk release): `kind` "restart \| inbox_remainder", at most 500 items; eligibility computed by the server under the owner lock (restart: in Next and `restart_eligible`, so a 20-day Next task → `not_eligible`; Inbox remainder: in Inbox and not processed in the named run); unknown and foreign ids → identical `not_eligible`; partial success is 200; every released task gets a `source: release` Someday receipt; the record keeps `previous_state` and, for Next tasks, `clock_before`; undo restores each task still at `revision_after` with its clock exactly (same `formulation_id`, `started_at`, extension, floor, stalled count) and deletes its receipt, the others `skipped: stale`; an undo of an already undone release (a retry whose response was lost, also after the 24 h retention) → 200 with the stored `undo_result` and nothing changed; 409 `undo_unavailable` only when never undone and the snapshot was purged (7 days); a bulk release retried after the 24 h idempotency retention with the stale per-item `expected_revision` of its first delivery, whose stored record matches (same `kind` and task set) → 200 with the stored result and nothing released twice (the match is checked before per-item revisions and eligibility), a non-matching one → `id_conflict`. *(020-FR-011, 020-FR-017, 020-FR-030, 020-FR-032)*
- [x] T130 [US4] Make T129 GREEN in `backend/app/modules/tasks/review_flow.py`, `backend/app/api/review_flow.py` and the `bulk_release:` / `undo_bulk_release:` reconstructors in `backend/app/modules/tasks/review_service.py`. *(020-FR-017, 020-FR-030)*
- [x] T131 [US4] Write the run traces `backend/tests/fixtures/review_traces_runs.json` (start, replace, merged progress from two clients, a progress change retried after the 24 h retention merged once, finish) and add them to `backend/tests/test_review_traces.py` (RED, then GREEN against the real API); copy the file byte-identically to `ios/BrainBuddyKit/Tests/BrainBuddySyncTests/Resources/review_traces_runs.json` and add both to the drift guard in `backend/tests/test_review_formulation_vectors.py`. *(020-FR-029, 020-SC-007)*
- [x] T132 [US4] Write and observe RED `backend/tests/test_review_metrics_readout.py`: `python -m app.cli review-metrics --owner <id> --since <date>` over seeded synthetic runs prints the weeks with a counted review (SC-001), the share of "yes" (SC-003), the median active minutes per mode (SC-004), the SC-005 real-use rate (decisions with `ai_use` `as_is`/`edited` and a server request id over `navigator_usage.shown`, a shown-then-abandoned request in the denominator) and the on-device share labelled as an upper bound, and the parks returned — each with its sample size, aggregates only; then GREEN in `backend/app/cli.py`. *(020-SC-001, 020-SC-003, 020-SC-004, 020-SC-005)*

### iOS core (slice PR-03)

- [x] T133 [US4] Write and observe RED in `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/QueriesReviewTests.swift`, `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ReviewPlannersTests.swift` and `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ReducerReviewTests.swift`: `wins`, `capacityMirror` (`nil` average with fewer than 4 full weeks or no completions), `waitingDue`, `somedayDue(limit: 7)`, `projectsNeedingNextAction`, `datesAhead(days: 14)`, `restartCandidates` and `lastCountedReview` against the flow vectors; `ActiveTimeAccumulator` against the `active_time` vectors; `ReviewLayout.summaryColumns(isAccessibilitySize:)` is 1 at accessibility text sizes and 2 otherwise and `ReviewLayout.stepBarScrolls(isAccessibilitySize:)` is true exactly at accessibility sizes (owner decision 2026-10-06, design "Mobile viability"); the run commands, with `progressSession` carrying a `progressID` (`progress_<lowercased UUID>`) minted in the command and never folded into another `progressSession` by compaction; `bulkRelease` / `undoBulkRelease` restoring clocks exactly; an unsent bulk release and its undo cancel in compaction. *(020-FR-017, 020-FR-028, 020-FR-029, 020-FR-030, 020-FR-031, 020-FR-032, 020-SC-004)*
- [x] T134 [US4] Make T133 GREEN in the new `ios/BrainBuddyKit/Sources/BrainBuddyCore/Review.swift` (`ReviewState`, runs, decisions, receipts, bulk releases), `ios/BrainBuddyKit/Sources/BrainBuddyCore/Queries+Review.swift`, `ios/BrainBuddyKit/Sources/BrainBuddyCore/ReviewPlanners.swift` (`ActiveTimeAccumulator`, `ReviewLayout`), `ios/BrainBuddyKit/Sources/BrainBuddyCore/Commands.swift` (`bulkRelease`, `undoBulkRelease`, `startSession` … `finishSession`) and `ios/BrainBuddyKit/Sources/BrainBuddyCore/Reducer+Review.swift`.
- [x] T135 [US4] Write and observe RED in `ios/BrainBuddyKit/Tests/BrainBuddySyncTests/ReviewSyncTests.swift` and `ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/WorkspaceReviewTests.swift`: two devices start a review offline and both sync → 0 decisions lost (the later push replaces with `replace_open: true`; the other device sees "review ended elsewhere"); merged progress → "review moved on elsewhere"; finish is idempotent; an offline quick review with 3 decisions syncs with its counts on the server (SC-007); a decision naming an unknown run is kept without a run; a progress change whose response was lost and that is retried after the fake server's 24 h retention is merged once (active time and "Inbox processed" not doubled) and acknowledged as success; a retried `undoBulkRelease` answered with the stored result is a success; then GREEN in `ios/BrainBuddyKit/Sources/BrainBuddySync/GTDCommand+Sync.swift`, `ios/BrainBuddyKit/Sources/BrainBuddySync/PushPlanner.swift`, `ios/BrainBuddyKit/Sources/BrainBuddySync/SyncEngine+Push.swift`, `ios/BrainBuddyKit/Sources/BrainBuddyFakeServer/FakeServer+Review.swift` (runs, queues, bulk releases, `progress_id` replay protection) and `ios/BrainBuddyKit/Sources/BrainBuddyWorkspace/Workspace.swift`. *(020-FR-011, 020-FR-029, 020-FR-040, 020-SC-007)*

### iOS app (slice PR-12)

- [x] T136 [US4] Write and observe RED, then GREEN, `ios/BrainBuddyKit/Tests/BrainBuddySyncTests/ReviewTraceReplayTests.swift`: the copied run traces `review_traces_runs.json` (T131: start, replace, merged progress from two clients, a progress change retried after the 24 h retention merged once, finish) replay against `BrainBuddyFakeServer` with the recorded statuses and responses; fix any fake-server drift in `ios/BrainBuddyKit/Sources/BrainBuddyFakeServer/FakeServer+Review.swift`. The decision and park traces replay earlier, in T173 (slice PR-04). *(020-FR-029, 020-SC-007)*
- [x] T137 [US4] The review cover and shared step chrome in the new `ios/BrainBuddy/Screens/Review/ReviewCover.swift`, presented from `ios/BrainBuddy/App/AppRouteView.swift`: Leave and Skip at the top, the primary action at the bottom, "N of M", the leave sheet ("Take a break? …"), leave with unsaved text first, review ended elsewhere, closed after a week, moved on elsewhere, VoiceOver focus to the step title on every change and to the next item's title after each decision, instant transitions under Reduce Motion; up to Dynamic Type AX5 every step body scrolls above the bottom bar and the step bar ("N of M" and the step segments) scrolls sideways at accessibility sizes per `ReviewLayout`, with Leave and Skip keeping 44 pt targets (owner decision 2026-10-06, design "Mobile viability"). *(020-FR-029, 020-FR-034, 020-FR-052)*
- [x] T138 [US4] M-11 in the new `ios/BrainBuddy/Screens/Review/ReviewEntryScreen.swift`: Quick (~5) / Full (~20) with their contents, the resume card from any device, "offline review replaced another", "earlier review closed after a week", the check failure with Ref, VoiceOver focus to the heading. *(020-FR-027, 020-FR-028, 020-FR-029, 020-FR-045)*
- [x] T139 [US4] M-10 in the new `ios/BrainBuddy/Screens/Review/RestartScreen.swift`: the neutral welcome or "Your first review" copy, "See which ones", Release (bulk release), Undo until "Start the review" or Close, "released, resumed after interruption" after an app kill, "undone, some skipped", partial failure, empty; VoiceOver focus to the heading. *(020-FR-017, 020-FR-038)*
- [x] T140 [US4] M-13, M-14 and M-15 in the new `ios/BrainBuddy/Screens/Review/WinsStep.swift`, `ios/BrainBuddy/Screens/Review/MindSweepStep.swift` (an unsaved line kept as a draft) and `ios/BrainBuddy/Screens/Review/InboxStep.swift` (the three choices over 15 items; one item at a time reusing the item view extracted from `ios/BrainBuddy/Screens/Process/ProcessInboxScreen.swift`, whose Undo also sends `inbox_processed_delta: -1`; the release with Undo until the step is left, also after an interruption). *(020-FR-028, 020-FR-030, 020-FR-034, 020-FR-048, 020-FR-052)*
- [x] T141 [US4] M-16 in the new `ios/BrainBuddy/Screens/Review/DecisionsStep.swift`: M-03 full-screen, "1 of N · earliest-asking first", "Not now" (progress `set_aside_task_id`), the Undo status line, "all decided", "all decided, one kept its wording", "some left", threshold changed mid-review. *(020-FR-002, 020-FR-006, 020-FR-034, 020-FR-048, 020-FR-050, 020-SC-002)*
- [x] T142 [US4] M-17 – M-21 in the new `ios/BrainBuddy/Screens/Review/RestOfNextStep.swift`, `ios/BrainBuddy/Screens/Review/WaitingStep.swift`, `ios/BrainBuddy/Screens/Review/ProjectsStep.swift` (lists the projects without a next action; the M-08 navigator block of the deferred PR-08 is not built, Notes), `ios/BrainBuddy/Screens/Review/SomedayStep.swift` and `ios/BrainBuddy/Screens/Review/DatesStep.swift`: the capacity mirror without a limit; Waiting keep / follow-up / return / cancel with Undo and the archived-project block; Someday keep / move to Next / cancel with Undo; unsaved titles kept as drafts. *(020-FR-028, 020-FR-031, 020-FR-032, 020-FR-034, 020-FR-048, 020-FR-052)*
- [x] T143 [US4] M-22 in the new `ios/BrainBuddy/Screens/Review/SummaryStep.swift`: ten counts in fixed order (zero dimmed), in two columns, one column at accessibility text sizes per `ReviewLayout` (M-22 "accessibility text size"), the calm all-zero line, "done without any step", the next review date, the optional "Clear how to start the week?", Done → `finishSession`; the restart, summary and step strings added to `ios/BrainBuddyKit/Sources/BrainBuddyCore/ReviewCopy.swift` (the banned-term test stays green). *(020-FR-029, 020-FR-033, 020-SC-003)*

### Device decision Undo keeps the server's clock bookkeeping (slice PR-12, follow-up from PR-15)

- [x] T174 [US1] Align the device's decision Undo with the server's (contracts/formulation-clock.md §3 "decision undo", today scoped "Server only"). Write and observe RED first: add transition vectors to `backend/tests/fixtures/review_formulation_vectors.json` and, in the same commit, its byte-identical copies `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/Resources/review_formulation_vectors.json` and `frontend/src/features/review/__tests__/review_formulation_vectors.json` (formulation-clock §6 "Changing a vector after PR-02": this slice depends on every consumer, PR-03, PR-05, PR-15 and PR-11) for **floor kept** (a time-zone floor or an activation floor written after the decision survives an Undo back into Next: `formulation_park_floor_at = max(snapshot's, the current task's while it is in Next)`) and **clamp on restore** (a decision made before activation and undone after it gets the activation clamp on the restored clock), with the `undo_decision` event carrying the current task and the settings. Then GREEN: give the pure restore the current task and the settings (`formulation.restore` in `backend/app/modules/tasks/formulation.py`, its runner in `backend/tests/test_review_formulation_vectors.py`, and the restore in `ios/BrainBuddyKit/Sources/BrainBuddyCore/Formulation.swift`), make `ReviewService._restored_task` in `backend/app/modules/tasks/review_service.py` delegate to it so the server keeps one rule, and apply it in the reducer's `undoDecision` in `ios/BrainBuddyKit/Sources/BrainBuddyCore/Reducer+Review.swift` (tests in `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/FormulationTests.swift` and `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ReducerReviewTests.swift`, names carrying `020-FR-048`); update `specs/020-weekly-review/contracts/ios-commands.md` §2 `undoDecision` (restores the snapshot, keeping the clock bookkeeping written since the decision) and drop the "Server only" scoping from formulation-clock §3, so an account-less device restores as the server does. *(020-FR-016, 020-FR-046, 020-FR-048)*
- [x] T175 [US5] Repair the device's bulk-release Undo for restart items the server released but this device's replay did not (ios-commands §4 "Known deviation … `undoBulkRelease`", FR-017, formulation-clock §3 "undo of a bulk release"), and drop retained pre-release clocks once a bulk release is undone. Write and observe RED first in `ios/BrainBuddyKit/Tests/BrainBuddySyncTests/ReviewSyncTests.swift` and `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ReducerReviewReplayTests.swift` (names carrying `020-FR-017` and `020-FR-043`): (a) a restart item released by the server's answer but not by local replay, then undone, ends in Next with the server's pre-release clock (the bulk-release answer or the next pull supplies it; `StoreDocument+Merge.swift` keeps `clockBefore` from the answer instead of `nil`), never a Next task without a clock; (b) once `undoneAt` is set, every released item's `clockBefore` (which carries `extension_reason`) is nulled in the replayed record, so no pre-release copy survives an undo (FR-043, data-model E10). Then GREEN in `ios/BrainBuddyKit/Sources/BrainBuddySync/StoreDocument+Merge.swift` and `ios/BrainBuddyKit/Sources/BrainBuddyCore/Reducer+Review.swift`; relabel the ios-commands §4 deviation as resolved. *(020-FR-017, 020-FR-043)*
- [x] T176 [US4] Keep device progress inside the review's mode (follow-up from PR-11; http §6 PATCH row: a `step` or `active_seconds` code outside the session's steps is 422). Write and observe RED first in `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ReducerReviewTests.swift` (names carrying `020-FR-028`): `progressSession` on a quick review naming a full-only `step` or `activeStep` (for example `dates`, `restOfNext`) throws a `GTDValidationError`, leaves the session unchanged and appends nothing to the outbox, whatever the session's status; a step of the mode is still merged. Then GREEN in `progressSession` in `ios/BrainBuddyKit/Sources/BrainBuddyCore/Reducer+Review.swift` (a new case in `ios/BrainBuddyKit/Sources/BrainBuddyCore/Commands.swift` when no existing one fits), so the device never queues a change the server refuses (the ios-commands §4 `progressSession` row states the rule). *(020-FR-028)*

### Web review (slice PR-13)

- [x] T144 [US4] Add the path rule for `frontend/tests/e2e/weekly-review.spec.ts` to `frontend/tests/allure.fixtures.ts` (single owner of this file).
- DEFERRED T145 [US4] Write and observe RED `frontend/src/features/review/__tests__/activeTime.test.ts` against the `active_time` vectors; then GREEN `frontend/src/features/review/activeTime.ts`. *(020-SC-004)*
- [x] T146 [US4] Write and observe RED `frontend/src/features/review/__tests__/ReviewShell.test.tsx` and extend `frontend/src/app/AppRoutes.test.tsx`: `/review` behind `ReviewGate`; a 240 px non-focusable rail and a 600 px column, "Step N of M" at 390 px; focus to the step heading on every change; Esc never closes the review; browser Back acts as Leave (the unsaved-text confirmation first; "Keep going" restores the history entry); the entry with the resume card, the last review summary card (SC-007) and "closed after a week"; step loading and step load failed; skip not saved; step action saving and failed; review ended or moved on elsewhere; the While-you-were-away rows inside the review; then GREEN `frontend/src/features/review/ReviewGate.tsx`, `frontend/src/features/review/ReviewShell.tsx`, `frontend/src/features/review/ReviewEntry.tsx`, `frontend/src/app/AppRoutes.tsx`, and the run, queue and bulk-release calls in `frontend/src/api/review.ts` and `frontend/src/api/reviewHooks.ts` (every session `PATCH` carries a `progress_<crypto.randomUUID()>` `progress_id` minted once per progress change and reused on its retries, contracts/http.md §6; a test asserts a retried PATCH resends the same id). *(020-FR-015, 020-FR-027, 020-FR-029, 020-FR-033, 020-FR-045, 020-FR-052, 020-SC-007)*
- [x] T147 [US4] Write and observe RED `frontend/src/features/review/__tests__/InboxStep.test.tsx` and `frontend/src/features/review/__tests__/RestartStep.test.tsx` (the new web Inbox step: over 15 → the three choices; one item at a time with the web choices; Undo returning the item and sending `inbox_processed_delta: -1`; saving and failed; partial failure; the release and "Undo the release" until the step is left, restored after a tab reload; releasing / release failed / undo failed. Restart: releasing / release failed / undoing / undo failed, Undo until moving on, "released, resumed after interruption"; the "set up but never reviewed" state (onboarded 21+ days ago, no counted review) shows the same offer under "Your first review / Let's make Next fit the week ahead." with no "Welcome back" or any wording implying the person was away, named for `020-FR-017`); then GREEN `frontend/src/features/review/steps/InboxStep.tsx` and `frontend/src/features/review/steps/RestartStep.tsx`. *(020-FR-017, 020-FR-030, 020-FR-034, 020-FR-045, 020-FR-048)*
- [x] T148 [US4] Write and observe RED `frontend/src/features/review/__tests__/DecisionsStep.test.tsx` (the inline card: Esc on the card does nothing, inside a form it returns to the card after the unsaved-text confirmation; keys 1–7; "Not now"; the Undo status line with Ctrl/Cmd+Z; "all decided, one kept its wording"); then GREEN `frontend/src/features/review/steps/DecisionsStep.tsx`. *(020-FR-002, 020-FR-034, 020-FR-048, 020-FR-050, 020-FR-052, 020-SC-002)*
- [x] T149 [US4] Write and observe RED `frontend/src/features/review/__tests__/ReviewSteps.test.tsx` for the other steps; then GREEN `frontend/src/features/review/steps/WinsStep.tsx`, `frontend/src/features/review/steps/MindSweepStep.tsx` (unsaved line), `frontend/src/features/review/steps/RestOfNextStep.tsx`, `frontend/src/features/review/steps/WaitingStep.tsx` (buttons stack at 390 px), `frontend/src/features/review/steps/ProjectsStep.tsx` (lists the projects without a next action; the navigator part of US3-8 is deferred, Notes), `frontend/src/features/review/steps/SomedayStep.tsx`, `frontend/src/features/review/steps/DatesStep.tsx` and `frontend/src/features/review/steps/SummaryStep.tsx` (ten counts, 4 columns, 2 at 390 px; the calm line; clear start; Done; the "done without any step" state — every step skipped, then Done, status `completed_empty` — shows the same calm "Review done" screen with the next review and the question, with no reproach and no mention that it does not count, a test named for `020-FR-029` asserting the absence of any such wording). *(020-FR-028, 020-FR-029, 020-FR-031, 020-FR-032, 020-FR-033, 020-FR-034, 020-FR-052)*
- [x] T150 [US4] Write the Playwright journeys in `frontend/tests/e2e/weekly-review.spec.ts` on synthetic data: a stalled task seeded with `python -m app.cli review-seed-aged-task` → D-05 → decide → Undo; auto-park through `review-run-sweep` → While you were away → return; a quick review end-to-end; a run finished through the API as an iOS client would shows its summary on the `/review` entry (`020-SC-007`); the keyboard-only story E2E-A11Y-01; axe scans of D-01 (with the dialog), D-02, D-03, D-04, D-05 and D-06 at desktop and 390 px; no horizontal overflow at 390 × 851 for `/tasks/next`, the decision dialog, `/review` (Waiting step and summary), `/settings/account` and D-05; the flag-on drawer link at 390 px. *(020-FR-004, 020-FR-015, 020-FR-040, 020-FR-048, 020-FR-052, 020-SC-006, 020-SC-007)*

**Checkpoint**: US4 (Quick and Full) runs end-to-end on iOS and web; US2's review-dependent scenarios (While you were away as the first review screen, restart mode) are now verifiable.

---

## Phase 7: User Story 5 — Schedule, cue, onboarding and settings (Priority: P3)

**Goal**: One onboarding screen, the weekly slot, one iOS notification, the widget count, a neutral "Last review", and settings — no streaks.

**Independent Test**: Complete onboarding, change settings, advance time to the review slot; verify exactly one notification, the widget count, the neutral wording, and the effect of a threshold change on markers (quickstart Scenario 5 steps 1, 7, 8).

### iOS core (slice PR-03)

- [x] T151 [US5] Write and observe RED in `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ReviewPlannersTests.swift`, `ios/BrainBuddyKit/Tests/BrainBuddySyncTests/ReviewSyncTests.swift` and `ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/WorkspaceReviewTests.swift`: `ReviewReminderPlanner.nextFireDate` (one a week at the local day and time, skipped after a counted review in the preceding 6 days, not after a `completed_empty` run, following a time-zone change of the device; two zones, named for `020-FR-036`: with the stored `time_zone` `Europe/Berlin` and the device in `America/New_York`, the fire date is Friday 16:00 New York time — the planner gets `TimeZone.current` and ignores `settings.time_zone` — and it equals the server's `next_review_at` only when the device sits in the stored zone); `ReviewRoute.parse` and `ReviewEntryPlanner.start(for: .widgetDecisions, …)` (M-26, M-12, M-09, M-10 before M-16; an open run resumes at its decision step, otherwise a quick review with Wins and Inbox skipped); notification and widget strings in `ReviewCopy` free of banned terms; `updateSettings` 409 → refetch, re-apply only the changed fields, resend; the device time zone (owner decision 2026-10-06, contracts/http.md §5 and ios-commands.md §2): `DeviceZoneTracker.change(lastObserved:current:)` returns a zone change only when the device's current zone differs from `local.lastObservedTimeZone`, and `nil` when only the pulled `time_zone` differs; `Workspace.sendDeviceTimeZoneIfChanged()` queues exactly one `updateSettings(timeZone:)` after the device's own zone changed and then records it, queues nothing for a second workspace in another zone that never changed (two workspaces in different zones syncing repeatedly → the stored zone changes once and the due-dated task's `park_floor_at` is raised once), records the zone sent with `acknowledgeExplainer` and at onboarding as `lastObservedTimeZone`, and on a device that sent neither records its zone at the first state load without sending; signed in, classification uses the stored zone while the notification and the shown next review use the device's current zone (ios-commands §6 "Which zone, for what"). *(020-FR-035, 020-FR-036, 020-FR-037, 020-FR-038, 020-FR-046)*
- [x] T152 [US5] Make T151 GREEN in `ios/BrainBuddyKit/Sources/BrainBuddyCore/ReviewPlanners.swift` (`DeviceZoneTracker`), `ios/BrainBuddyKit/Sources/BrainBuddyCore/ReviewCopy.swift`, `ios/BrainBuddyKit/Sources/BrainBuddyCore/Commands.swift` (`updateSettings`), `ios/BrainBuddyKit/Sources/BrainBuddySync/GTDCommand+Sync.swift` and `ios/BrainBuddyKit/Sources/BrainBuddyWorkspace/Workspace.swift` (`sendDeviceTimeZoneIfChanged()`, `local.lastObservedTimeZone` decoded with `decodeIfPresent`).

### iOS app (slice PR-12)

- [x] T153 [US5] M-12 in the new `ios/BrainBuddy/Screens/Review/OnboardingScreen.swift`: three points, the grace date, Day/Time (default Friday 16:00 local) and threshold (7/14/21/28, default 14) saved with `onboarded: true` and the device zone (no notification prompt: the scheduler is deferred, Notes); the error with Ref; VoiceOver focus to the heading. *(020-FR-016, 020-FR-018, 020-FR-035)*
- DEFERRED T154 [US5] M-25 in the new `ios/BrainBuddy/Review/ReviewReminderScheduler.swift`: registers what `ReviewReminderPlanner` returns (called with `TimeZone.current`, never the stored zone; contracts/ios-commands.md §6) as one `UNCalendarNotificationTrigger` with a stable identifier, rescheduled on a settings change, a recorded review, pull, background refresh and the system time-zone-change notification (`ios/BrainBuddy/App/BrainBuddyApp.swift`); `BrainBuddyApp.swift` also calls `Workspace.sendDeviceTimeZoneIfChanged()` on load, on foreground and on the system time-zone-change notification, so the slot follows a zone change of this device only (US5-5). *(020-FR-035, 020-FR-036)*
- DEFERRED T155 [US5] M-24 in `ios/BrainBuddyWidgets/NextActionsWidget.swift`: `askCount` (the same aggregate); the "N ask ›" chip as a `Link` to `brainbuddy://review/decisions` with a 44 × 44 pt area in medium and large, display-only in small, none for a Today widget or before activation; the VoiceOver label "3 tasks ask for a decision. Open the review's decision step"; at accessibility text sizes the chip's label may wrap under the count while its link area stays at least 44 × 44 pt (design "Mobile viability"); the `review` host in `ios/BrainBuddy/App/AppRouter.swift` following `ReviewEntryPlanner`. *(020-FR-037, 020-FR-051)*
- [x] T156 [US5] M-11 Lists row in `ios/BrainBuddy/Screens/Browse/ListsHubScreen.swift`: it replaces `DeferredRow` when exposed; "Last review: N days ago" from counted reviews only, "Set up in a minute" when never reviewed. *(020-FR-038, 020-FR-042)*
- DEFERRED T157 [US5] M-23 schedule rows (day, time, "Last review") in `ios/BrainBuddy/Screens/Settings/ReviewSettingsSection.swift`; the error with Ref and the offline note. *(020-FR-035, 020-FR-038, 020-FR-045)*
- [x] T158 [US5] Update `docs/native-ios-app.md` (l.19 "Weekly review stays visibly deferred" → flag-gated; the "Ids" section noting that review records, follow-up tasks and formulations carry client-supplied ids) and `ios/README.md` (l.356) (found by `/speckit-checklist`; `ios/README.md` was not in the plan's paths).
- [ ] T159 [US5] Record `specs/020-weekly-review/evidence/manual-ios-increment3.md` (labelled manual, synthetic data): one decision per screen in the Inbox, decision, Waiting and Someday steps (`020-FR-034`), the Lists row replacing `DeferredRow` (`020-FR-042`), 44 pt targets, VoiceOver focus on M-10, M-11 and M-12, every shipped screen (M-10 – M-22) at Dynamic Type AX5 (bodies scroll, the M-22 counts in one column, the step bar scrolling sideways; design "Mobile viability"); plus the Xcode-lane build.

### Web (slice PR-13)

- [x] T160 [US5] Write and observe RED in `frontend/src/components/shell/__tests__/AppShell.test.tsx`: with the flag on, a working "Weekly review" link with "Last review: N days ago" (no line while loading or after a failure; "Set up in a minute" when never reviewed), also in the 390 px drawer; with the flag off, the existing "Weekly review — Coming soon" assertions unchanged; then GREEN `frontend/src/components/shell/AppShell.tsx`. *(020-FR-036, 020-FR-038, 020-FR-042)*
- [x] T161 [US5] Write and observe RED `frontend/src/features/review/__tests__/OnboardingDialog.test.tsx` (focus on "A weekly reset"; Esc saves nothing; defaults Friday 16:00 and 14; "The web doesn't send reminders; the sidebar shows when your last review was."; the grace date); then GREEN `frontend/src/features/review/OnboardingDialog.tsx`, opened from `frontend/src/features/review/ReviewEntry.tsx`. *(020-FR-016, 020-FR-035, 020-FR-036)*
- DEFERRED T162 [US5] Write and observe RED in `frontend/src/features/review/__tests__/ReviewSettingsSection.test.tsx`: review day and time, "Last review", a failed save keeps the old value with Ref, offline, one column at 390 px; then GREEN `frontend/src/features/review/ReviewSettingsSection.tsx`. *(020-FR-035, 020-FR-038, 020-FR-045)*
- DEFERRED T163 [US5] Write and observe RED `frontend/src/features/review/__tests__/deviceZone.test.ts` (owner decision 2026-10-06, contracts/http.md §5, data-model E11; names carry `020-FR-035`): with no `bb.reviewLastZone.v1.<origin>.<account>` key the browser's zone is recorded and nothing is sent; when the browser's zone (`Intl.DateTimeFormat().resolvedOptions().timeZone`, injected) differs from the recorded one, exactly one `PUT /review/settings` with `time_zone` and the current `expected_revision` is sent, a 409 refetches the state and resends only the zone, and the key is updated after success; when only the pulled `time_zone` differs (another device set it), nothing is sent; checked at web open and on window focus; the key is removed on sign-out or account switch and holds no content; then GREEN `frontend/src/features/review/deviceZone.ts`, started from `frontend/src/features/review/ReviewStartupDialogs.tsx` while the flag is effective and the owner is activated. *(020-FR-035, 020-FR-046)*
- DEFERRED T172 [US5] Write and observe RED `frontend/src/features/review/__tests__/reviewSlot.test.ts` (targeted re-review 2026-10-06, contracts/http.md §5; names carry `020-FR-033` and `020-FR-036`): `nextReviewSlot(settings, lastCountedReviewAt, now, zone)` returns the next `review_weekday` at `review_time` in the injected browser zone, skips a slot with a counted review in the preceding 6 days (not after a `completed_empty` run), and with the stored `time_zone` `Europe/Berlin` and the browser in `America/New_York` returns Friday 16:00 New York time (it ignores `settings.time_zone`; it equals `next_review_at` only when the browser sits in the stored zone); then GREEN `frontend/src/features/review/reviewSlot.ts` and show its result as "Next review" in `frontend/src/features/review/steps/SummaryStep.tsx` (D-03 summary) instead of `next_review_at`. *(020-FR-033, 020-FR-036)*

**Checkpoint**: Increment 3 (US4 Quick and Full review + the US5 onboarding and "Last review") is complete on iOS and web; the notification, widget count, schedule settings and device-zone follow are deferred.

---

## Phase 8: User Story 6 — The same review on Mac (Priority: P3)

**Goal (this feature)**: only the pre-sync "Weekly review · coming later" row (FR-041). No local-only review ships.

**Independent Test**: Launch the Mac app on a macOS host: the non-interactive row is shown after Lists and offers no action (quickstart Scenario 6).

### Mac pre-sync row (slice PR-06)

- [x] T164 [US6] Write and observe RED `macos/Tests/BrainBuddyMacTests/WeeklyReviewRowTests.swift` (`020-FR-041`): the sidebar entries, extracted into the new testable `macos/Sources/BrainBuddyMac/SidebarEntries.swift`, include a non-interactive "Weekly review · coming later" row right after Lists, with no action. *(020-FR-041)*
- [ ] T165 [US6] Make T164 GREEN in `macos/Sources/BrainBuddyMac/ContentView.swift` (`sidebar(account:)` renders `SidebarEntries`; the iOS `DeferredRow` pattern; no local-only review) and record the `swift test --disable-sandbox` run on a macOS host in `specs/020-weekly-review/evidence/macos-host-run.md` (no CI lane runs `macos/`). *(020-FR-041)*

### Deferred — blocked on the Mac↔backend sync spec (not tasks of this feature)

The full Mac review is **blocked** until a separate Mac↔backend sync feature spec exists
and is delivered (spec Assumptions; FR-041; plan "US6"). It is planned in that spec's own
tasks, not here, so no open checkbox in this file waits on it and delivery accounting
for 020 is not blocked by it. What it will cover, for that spec to pick up:

- US6-1: markers as D-01, the decision card as D-02, the review as D-03 with the Mac's
  one-item-at-a-time layout for M-18 / M-20, and the on-device navigator states of
  M-05 / M-06, all reusing `BrainBuddyKit`'s rules and contracts.
- The fate of the POC "Review Waiting for" / "Review Someday" sheets.
- Replacing the FR-041 "coming later" row with the working entry.

`/speckit-accept` records US6-1 as **deferred by scope**, not as a failure; FR-041 is
accepted on the pre-sync row and its recorded macOS-host run.

---

## Phase 9: Polish & Cross-Cutting Concerns (slice PR-14)

**Purpose**: Turn on the full-feature gates and record the release decisions.

- [ ] T166 Add `python3 scripts/check_requirement_coverage.py specs/020-weekly-review --requirements <every id except 020-FR-022, 020-FR-023 and 020-FR-049, as listed in PR-14's `tests`>` beside the 019 line (the three deferred ids have no remaining task, Notes; the follow-up feature drops the filter), and a byte comparison (`cmp`) of every vector, wire-fixture and trace copy against its canonical file, to the `check-specs` recipe in `Makefile`, plus a file-exists check (`test -f specs/020-weekly-review/evidence/macos-host-run.md`) for the FR-041 macOS-host run that the name-matching gate cannot see (plan "Test strategy": for FR-041 the recorded run file is required in addition to the name match; PR-06 writes it, and PR-14 depends on PR-06); re-record `.specify/gate-integrity.json` with `python3 scripts/check_gate_integrity.py --update` in the same commit (`Makefile` is guarded); `python3 scripts/check_gate_integrity.py` and `make check-specs` pass.
- [x] T167 Raise `backend/coverage-floor.json` and `frontend/coverage-floor.json` to the measured values (ratchet only; no coverage suppression in `frontend/src`).
- [x] T168 [P] Write `specs/020-weekly-review/evidence/README.md` (the evidence rule: seeded synthetic accounts and the design's example data only; real use as numbers only) and `specs/020-weekly-review/evidence/real-use-readout.md` (weekly `review-metrics` numbers with sample sizes; minimum samples as the owner confirmed them on 2026-10-06: SC-001 all 8 weeks, SC-003 ≥ 6 answered reviews, SC-004 ≥ 4 reviews per mode; SC-005 is not read out while the navigator clients are deferred, Notes). *(020-SC-001, 020-SC-003, 020-SC-004)*
- [ ] T169 [P] Record the owner's rollout decisions in `specs/020-weekly-review/evidence/rollout-decisions.md`: the stages (backend with the flag OFF → iOS and web builds → SELECTED_USERS (owner) → wider after the 8-week read-out); and the `BBWeeklyReviewLocal` Release decision — the switch itself flips later, after one clean threshold cycle, in its own change. "Clean" is measured, not judged: over one full cycle of the synced path for the owner (from the flag reaching SELECTED_USERS, at least the owner's `threshold_days` + 7 days, so at least one formulation can pass its ask and park points), the read-out in `specs/020-weekly-review/evidence/real-use-readout.md` records **0 early parks** (no park without a preceding ≥ 24 h `moves_tomorrow` window, none before its `park_due_at` or any floor; checked against the `review_park_acks` rows and the `review_auto_park` log lines), **0 park-related sync issues** (no `SyncIssue` for `autoParkTask`, a yielding `decideTask` or a park acknowledgement on any of the owner's devices), **0 yield failures** (no card decision made before the park instant that lost to the park) and **0 duplicate parks** (one `review_park_acks` row per parked formulation); any non-zero count restarts the cycle after its fix. The decision file names the cycle's dates and these four counts. *(020-FR-042)*
- DEFERRED T170 Promote `app/modules/tasks/formulation.py` to `backend/mutation-enforced-scope.txt` only if two clean nightly mutation runs exist (deploy-and-ci rules), re-recording `.specify/gate-integrity.json`; otherwise note it as pending in `specs/020-weekly-review/evidence/rollout-decisions.md` (research R20).
- [ ] T171 Run the full verification on the frozen candidate: `make check-specs`, `make test-backend`, `make test-frontend`, `sh ios/scripts/swift-linux.sh test`, `make test-e2e`, `make verify-all`, the requirement-coverage gate over every id except the deferred 020-FR-022, 020-FR-023 and 020-FR-049, and the quickstart.md scenarios that the kept slices implement (Scenario 4, the navigator, is deferred); the Allure quality gate (`maxFailures: 0`) stays unchanged.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1, PR-01)**: no dependencies; first.
- **Foundational (Phase 2)**: PR-02 depends on PR-01; PR-15 depends on PR-02. The iOS core (PR-03) and web (PR-05) lanes need only PR-02; the backend story work needs PR-15, and so does the iOS app slice PR-04 (it replays PR-15's decision and park traces, T173).
- **US1 and US2 (Phases 3–4, P1)**: one increment. Activation (US2's explainer) is what makes US1's markers appear (FR-004 "Before activation"), so they ship together.
- **US3 (Phase 5, P2)**: backend PR-07 after PR-15; the client slices (former PR-08, PR-09, PR-10) are deferred (Notes).
- **US4 and US5 (Phases 6–7)**: backend PR-11 after PR-15 (a sibling of PR-07); iOS PR-12 after PR-04, PR-05 and PR-11 (PR-05 because T174 changes the formulation vectors that PR-05 consumes, formulation-clock §6); web PR-13 after PR-05 and PR-11.
- **US6 (Phase 8)**: PR-06 after PR-01 only; the full Mac review is blocked on the Mac-sync spec.
- **Polish (Phase 9, PR-14)**: after PR-06, PR-12 and PR-13 (and therefore every kept lane; with the navigator clients deferred, FR-022, FR-023 and FR-049 are accepted as deferred by scope, owner decision 2026-10-07).

### User Story Dependencies

- **US1 (P1)**: after Foundational; independent of the other stories except that its markers need an activated owner (tests activate through the API or the CLI seed).
- **US2 (P1)**: after Foundational; reuses US1's clock and card (a yielding decision is a card decision).
- **US3 (P2)**: needs US1's card (the navigator lives in its forms).
- **US4 (P2)**: needs US1's card (decision step) and US2's parks (While you were away, restart).
- **US5 (P3)**: needs US4's runs for "Last review", the notification skip and the widget's deep link.
- **US6 (P3)**: the pre-sync row is independent; the full story waits for the Mac-sync spec.

### Lanes (slice graph)

```text
PR-01                  → PR-02, PR-06
PR-02                  → PR-15 (backend), PR-03 (iOS core), PR-05 (web)
PR-15                  → PR-07 (navigator backend), PR-11 (review-flow backend)   # siblings
PR-03 + PR-15          → PR-04   # PR-15's decision/park traces replayed in Swift (T173)
PR-04 + PR-05 + PR-11  → PR-12   # PR-05: T174 changes the formulation vectors (formulation-clock §6)
PR-05 + PR-11          → PR-13
PR-06 + PR-12 + PR-13  → PR-14
# deferred 2026-10-07: PR-08 (iOS navigator), PR-09 (downloadable model), PR-10 (web navigator)
```

### Within Each User Story

- Tests MUST be written and observed failing before implementation
- Models before services
- Services before endpoints
- Core implementation before integration
- Story complete before moving to next priority

### Parallel Opportunities

- Phase 1: T001, T002, T005, T009 in parallel; the coverage-gate pair is serial (T006 → T007 → T008).
- Phase 2 (PR-02): T014, T015, T020, T022 in parallel; PR-15's T038 and T039 in parallel with its backend tasks.
- After PR-02: the iOS core lane (PR-03) and the web lane (PR-05) run in parallel with the backend core (PR-15) — disjoint write paths.
- After PR-15: PR-07 (navigator backend) and PR-11 (review-flow backend) are siblings with disjoint paths.
- PR-06 (Mac row) can run any time after PR-01.
- Within a slice, test files marked [P] are written in parallel.

---

## Parallel Example: User Story 1

```bash
# Three lanes after PR-02 lands (different worktrees, disjoint write paths):
Task: "T040 backend/tests/test_review_clock_api.py"            # PR-15
Task: "T049 ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/FormulationTests.swift"  # PR-03
Task: "T067 frontend/src/features/review/__tests__/formulation.test.ts"           # PR-05

# Inside the web lane, independent RED tests together:
Task: "T068 frontend/src/api/__tests__/review.test.ts"
Task: "T069 frontend/src/features/review/__tests__/stallRecommendation.test.ts"
```

## Parallel Example: User Story 3 and User Story 4 backends

```bash
# Siblings after PR-15 (no shared file: container.py is PR-07's, cli.py and review_service.py PR-11's):
Task: "T098 backend/tests/test_review_navigator.py"   # PR-07
Task: "T126 backend/tests/test_review_flow_api.py"       # PR-11
```

---

## Implementation Strategy

### MVP First (increment 1 = User Stories 1 + 2)

1. Complete Phase 1 (PR-01) and Phase 2 (PR-02, PR-15).
2. Complete Phases 3–4 across the lanes (PR-03, PR-04, PR-05).
3. **STOP and VALIDATE**: quickstart Scenarios 1, 2, 3 and 7 on synthetic data; manual iOS evidence for increment 1.
4. Deploy backend with the flag OFF, then the iOS and web builds, then the flag to SELECTED_USERS (owner). US1 alone is not a usable MVP: no marker shows before the explainer (US2) activates the owner.

### Incremental Delivery

1. Increment 1: US1 + US2 (rule, card, markers, explainer, auto-park, While you were away) → owner on TestFlight and web.
2. Increment 2: US3 is deferred beyond the PR-07 backend (Notes).
3. Increment 3: US4 (Quick and Full review) + the US5 onboarding and "Last review" → PR-14 turns on the full-feature gates.
4. Increment 4: US6 after the Mac-sync spec (outside this task list).

### Parallel Team Strategy

1. One worker per lane after PR-02: backend (PR-15 → PR-07 ‖ PR-11), iOS (PR-03 → PR-04, which also waits for PR-15, → PR-12), web (PR-05 → PR-13), Mac (PR-06).
2. A dependent slice starts from an accepted base, never from a speculative parallel branch.

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
- Per the founder acceptance's compensating measures (`planning-review.json`), each
  slice's PR description lists the review-c1/c2 dispositions it implements (table
  below), and a slice that changes spec.md, plan.md or a contract beyond the
  dispositions re-runs the planning review for that change.
- Live provider calls (`/verify-live`, the SC-005 cloud cell) are approval-gated and
  never run unattended, from a subagent or from a scheduled session.
- The founder acceptance of the planning review **expires on 2026-11-05**
  (`planning-review.json` `founder_acceptance.expires_on`). If slices remain after that
  date, work on them does not continue on the expired acceptance: first either the
  owner re-accepts (a new dated `founder_acceptance` record with its own expiry) or a
  targeted planning review is re-run over the artifacts the remaining slices rely on.
- **Deferred review findings (PR-12).** From 2026-10-07, by the owner's decision, open
  slices take only P1 review findings before merge. The P2s below are not lost; PR-12
  triages each one into a task or drops it with a reason:
  - web (#277): wrap a malformed JSON body from a review endpoint in `ApiError` with
    its correlation id; block decision-dialog dismissal (Close, scrim, Escape) until a
    save settles; While-you-were-away freshness tracks a post-mount settle rather than
    comparing millisecond timestamps; a Return whose 409 re-read also fails shows an
    unknown state with Retry, not "Now in Someday / maybe";
    fixed in PR-13: the malformed JSON body, the dialog dismissal and the Return whose
    re-read fails; the freshness item was already fixed in #277 (`26da2da`);
  - backend (#278): replay repair in `_complete_session` keeps the recorded activity
    time for `last_activity_at` instead of the retry time;
  - backend (#272): reject a blank `BRAIN_BUDDY_REVIEW_NAVIGATOR_MODEL` at startup so
    the navigator fails fast instead of reporting itself available;
  - carried over: the iOS visible-content staleness check (done in PR-12: `ShownTask`
    compares the task's visible content, not its revision), the design.md M-02 copy
    amendment, a PR-04 deviations line, the TR-005 message, and the
    `/review/decisions/{id}/undo` path parameter taking the reference shape.
- **Manual checks follow the merge (owner decision 2026-10-08).** A slice whose only
  remaining checks are manual (a simulator, device or Mac run) merges once CI is
  green. It carries its manual test plan as an evidence file under `evidence/`.
  - **Who runs the plans:** later, the owner's agent runs them on the owner's
    hardware and fills in the Results. A failed check is fixed in a separate PR.
  - **What stays open:** the manual-run part of each task (T094, T159, T165's host
    record, T169, T171) stays unchecked until its Results are recorded.
    `/speckit-accept` does not accept a requirement on a PENDING plan.
- **Deferred review findings recorded for the follow-up feature (owner P1-only rule,
  2026-10-08).** The P2s below were found in review of slices that merge on P1 fixes
  only. None is listed in "Deferred review findings (PR-12)" above.
  - web (#290):
    - `ReviewGate`: refresh a resumed session before returning to entry;
    - `InboxStep`: release the remainder when the batch-ending item is stale;
    - `ReviewEntry`: clear the restart Undo when Close moves on (fix together with
      iOS #287);
    - `SummaryStep`: refresh `next_review_at` before showing the summary;
    - `RestartStep`: use the effective formulation start for restart eligibility;
    - the shell's Discard does not clear the inline `DecisionDialog` draft;
    - the inline "Think it through" CRT link bypasses the review leave guard;
    - `InboxStep.saveTitle` 409 has no stale branch (the retry reuses the old
      revision);
    - only one count-failure banner is shown at a time;
    - set-aside is per task per run (a reworded task stays set aside within the run);
    - `DecisionDialog` (inline): a stale answer whose reload fails clears the form
      and shows "no longer asks" with no Retry (the step forms already keep the
      card, the draft and a Retry);
    - `ItemDecisionStep`: a deduplicated decision's notice and Undo label follow the
      attempted item, not `response.decision` / `response.created_task`;
    - `OnboardingDialog`: Close and Escape stay enabled while Continue saves.
  - Review backlog (owner decision 2026-10-08): #290 merged once Codex's
    review was clean and CI green, without further narrowing its scope. Any later
    finding on the web review is a backlog item for the follow-up feature rather than
    a fix in PR-13.
  - iOS: optionally read the new `meta.decided_task_ids` / `meta.set_aside_task_ids`
    of `GET /review/queues/decisions` to resume the decisions step across devices.
  - Mac (#276): the evidence file cites the CI run of the previous SHA; the owner's
    host run records the candidate SHA.
  - owner decision 2026-10-08 (was an open question): retained members of an
    archived project keep getting 400 `project_archived` on Return to Next in the
    weekly review until the project is restored, as the "restore project first"
    design says. No change.
  - owner decision 2026-10-08: the sign-out confirmation names unsaved
    weekly-review drafts that sign-out would remove (feature 021 follow-up PR).
- **Deferred to a follow-up feature (owner decision 2026-10-07).** The work is bloated
  (about 98k lines so far), so the not-started slices keep only what ships a usable weekly
  review on the surfaces already built (backend, iOS, web): US1 and US2, the Quick and
  Full review (US4; the owner kept Full the same day) and the onboarding. PR-05, PR-06
  and PR-07 are in flight and unchanged. Deferred
  tasks keep their text in the phases above as input for the follow-up feature, are marked
  `DEFERRED`, belong to no slice, and no open checkbox waits on them (the rule of the Mac
  section). `/speckit-accept` records them as deferred by scope, not as failures.
  - Navigator clients (US3), former slices PR-08, PR-09, PR-10: T109 – T125. Only the
    PR-07 backend and the merged consent commands (T108) remain; the endpoints stay
    behind the flag with no caller.
  - The navigator block of the projects step (US3-8, M-08): the Full review's Projects
    step (T142, T149) only lists the projects without a next action.
  - Cues and schedule (US5): T154 (iOS notification scheduler and device time-zone
    hook), T155 (widget chip), T157 and T162 (day and time settings), T163 (web device
    zone), T172 (web next-review slot). The summary shows the server's `next_review_at`.
    Onboarding (T153, T161), the Lists and sidebar "Last review" (T156, T160) stay.
  - T145 (web active time) and T170 (mutation-scope promotion).
  - Requirements left without a task: FR-022, FR-023, FR-049. T166 and PR-14 gate the
    other 56 ids with an explicit `--requirements` list instead of the unfiltered form;
    the follow-up feature restores the unfiltered gate. The client halves of FR-019 –
    FR-021, FR-024 – FR-026 and FR-035 – FR-037, and SC-005's real-use bar, are
    deferred too; their ids stay covered by the backend and core tests.

## Disposition traceability

Every disposition in [review-c1-disposition.md](review-c1-disposition.md) and
[review-c2-disposition.md](review-c2-disposition.md) marked "fixed" that requires code
or test work maps to at least one task. Dispositions that were fully discharged in the
planning artifacts themselves (spec, design, plan, contracts wording) are listed as
"artifacts".

**Campaign 1**

| ids | tasks |
|---|---|
| PD-1 (ten counters) | T042, T043, T126, T143, T149 |
| PD-2 (`completed_empty`) | T015, T126, T128, T143, T149, T151 |
| PD-3 (explainer, activation) | T077, T078, T087, T088, T092, T095, T097 |
| RC-01 (extend at `park_due`) | T014, T042, T081 |
| RC-02, AH-05 (client ids, `replace_open`) | T021, T041, T042, T051, T126, T135 |
| RC-03, AH-02 (clock snapshots for bulk undo and yield) | T129, T130, T133, T079, T081 |
| RC-04, PC-05, RC-17(e) (shared `reduce_notes`, no language field) | T100, T101, T109, T123, T020 |
| RC-05 (aggregate and queue order) | T017, T046, T053, T127 |
| RC-06, UX-14 (Inbox Undo, remainder release) | T126, T129, T140, T147 |
| RC-07 (extension reason in history) | T028, T042, T035 |
| RC-08, AC-05 (activation, clamp, post-replay step) | T014, T077, T087 |
| RC-09 (Someday eligibility) | T015, T127, T133 |
| RC-10 (`parked` only by auto-park) | T042, T079 |
| RC-12 (no canvas offer on iOS) | T062, T073 |
| RC-13 (restart seeds) | T127 |
| RC-14 (web US3-8 in the projects step) | T149 |
| RC-15 (< 4 weeks) | T015, T127, T133, T142, T149 |
| RC-16, PC-09 (active time, `returned_at`, due-date log) | T126, T083, T047, T132 |
| RC-17(d) (Today widget) | T155 |
| RC-11, RC-18, AC-06, AC-10, AC-11 | artifacts |
| AC-01 (startup raise) | T098, T099 |
| AC-02 (review conflict rules) | T055, T135, T151 |
| AC-03 (no revision bump) | T077, T079, T089 |
| AC-04, AH-03 (no `client_occurred_at`) | T041, T081 |
| AC-07 (sweep wiring) | T079, T080 |
| AC-08 (three routers) | T032 |
| AC-09 (import-linter) | T034 |
| AC-12, PC-07 (device retention) | T089, T090 |
| TE-01 (read-out, SC-002, SC-006 cases) | T132, T127, T079 |
| TE-02 (Core planners, manual evidence) | T053, T151, T094, T159 |
| TE-03 (clock seam, TEST-only CLI) | T011, T012, T013, T085 |
| TE-04 (copies, byte check, `ageing_at`) | T023, T166, T040 |
| TE-05 (flow vectors, wire fixtures) | T015, T022, T023 |
| TE-06 (PR-07 / PR-11 siblings) | slice map |
| TE-07 (eval set in PR-07; PR-09 machine tests) | T104, T118 |
| TE-08 (Mac evidence) | T165 |
| TE-09 (string guard, `MarkerStyle`) | T076, T053 |
| TE-10 (coverage-script test) | T006 |
| PC-01 (retention with the flag off) | T079, T080 |
| PC-02 (evidence rule) | T168 |
| PC-03 (no existence oracle) | T083, T129, T126 |
| PC-04 (privacy rows per slice) | T038, T039, T106, T121 |
| PC-06 (stall reason not logged) | T037, T043 |
| PC-08 (consent version, pending switch) | T102, T125 |
| PC-10 (route caption) | T109, T113 |
| UX-01 (unsaved text, FR-052) | T058, T063, T074, T140, T142, T149 |
| UX-02 (restart Undo after interruption) | T139, T147 |
| UX-03, UX-11 (c2) (390 px) | T073, T095, T146, T150 |
| UX-04, UX-05 (web step states, web Inbox step) | T146, T147 |
| UX-06, UX-16 (web WYWA dialog, swipe-down) | T096, T093 |
| UX-07 (focus, traps, Esc) | T073, T095, T096, T146 |
| UX-08 (Undo by keyboard and VoiceOver) | T070, T064, T053 |
| UX-09 (ended / moved on elsewhere) | T137, T146 |
| UX-10, UX-11 (navigator and undo copy) | T113, T124, T062, T073, T064, T139 |
| UX-12 (navigator interrupted) | T109, T113, T124 |
| UX-13 (widget entry order) | T151, T155 |
| UX-15 (keys 1–7) | T073 |
| AH-01 (clock-aware compaction) | T051, T052 |
| AH-04 (sweep-gap floor) | T014, T079 |
| AH-06 (`created_task_revision`) | T044 |
| AH-07 (account-less switch, park cap) | T059, T089, T169 |
| AH-08 (one prefix list, consent version) | T030, T042, T102 |
| AH-09 (time-zone floor) | T046 |

**Campaign 2**

| ids | tasks |
|---|---|
| RC-01 (leaving pauses; finish = Done) | T126, T137, T146 |
| RC-02 (client-side duplicate filter) | T015, T109, T123 |
| RC-03 (FR-005 close rule) | T014, T016, T017 |
| RC-04 (web last-review summary) | T046, T146, T150 |
| RC-05 (restart anchor) | T015, T127 |
| RC-06 (cosmetic save is a decision) | T042, T141, T148 |
| RC-07 (account-less staged exposure) | T059, T169 |
| RC-12 (earliest-asking copy) | T141, T148 |
| RC-14 (release receipts) | T042, T129 |
| RC-15 (once a day; copy names the current list) | T093, T096, T055 |
| RC-16 (project model question) | T100, T114 |
| RC-08 – RC-11, RC-13, AC-06, UX-09 | artifacts |
| AC-01 (adapter in `app/ai`, port, import-linter) | T034, T099, T101 |
| AC-02 (cost admission outside the lock) | T102, T101 |
| AC-03 (exact `SessionResponse`) | T021, T126 |
| AC-04 (`task_mapping`, `derive_instants`) | T033, T041 |
| AC-05 (`SerializedWriter`) | T029, T030 |
| AC-07 (retention pause wording) | T039 |
| AC-08 (a `User` per owner) | T079 |
| TE-01 (active time) | T133, T145 |
| TE-02 (SC-005 denominator) | T102, T132 |
| TE-03 (stall recommendation) | T053, T069 |
| TE-04 (`ReviewCopy`) | T053, T151, T143 |
| TE-05 (golden traces) | T086, T131, T136, T173 |
| TE-06 (flow vectors run in PR-02) | T018, T019 |
| TE-07 (post-release read-out) | T132, T168 |
| TE-08 (`--requirements` filter) | T006, T007, T166 |
| TE-09 (WYWA once a day) | T087, T096 |
| TE-10 (axe, `UndoWindowPolicy`, manual list) | T150, T053, T094, T159 |
| TE-11, TE-12 (split PR-02, path hygiene) | slice map |
| PC-01 (id shapes) | T021, T042, T037 |
| PC-02 (privacy routes never gated) | T102 |
| PC-03 (suggestions not idempotent, nothing stored) | T102 |
| PC-04 (no exception text in logs) | T037, T079 |
| PC-05 (provider retention, time zone) | T038, T106 |
| PC-06 (query-parameter `session_id`) | T126 |
| UX-01, UX-02 (web pending and step-loading states) | T146, T147 |
| UX-03 (cloud clarifying question) | T113, T124 |
| UX-04 (model download lifecycle) | T118, T120 |
| UX-05 (browser Back) | T074, T146, T150 |
| UX-06 (D-06) | T072 |
| UX-07 (iOS VoiceOver focus) | T092, T093, T139, T138, T153, T113, T094 |
| UX-08 (affordance controls) | T062, T073, T113, T120, T072 |
| UX-10 (focusable offline markers; recap states) | T071, T160 |
| UX-11 (390 px reflow) | T149, T150 |
| UX-12 (keyboard-only story) | T150 |
| UX-13 (Inbox release Undo after interruption) | T140, T147 |
| UX-14 (closed after a week) | T137, T138, T146 |
| UX-15 (Esc on the inline card) | T148 |
| AH-01 (formulation-based yield) | T081, T082 |
| AH-02 (flag-off writes accepted; `.featureDisabled`) | T042, T055, T089 |
| AH-03 (park key with `from_revision`) | T079 |
| AH-04 (E6 row at park time) | T079 |
| AH-05 (key-rotation runbook) | T105 |
| AH-06 (server-side bulk eligibility) | T129 |
| AH-07 (zone with the explainer acknowledgement) | T077, T092, T095 |
| AH-08 (server clock offset) | T089, T090 |

**Owner decisions 2026-10-06 (after /speckit-tasks)**

These are not review dispositions: they are owner decisions recorded in spec
Clarifications "Session 2026-10-06 (after /speckit-tasks)". Per the founder
acceptance's compensating measures, the spec, plan and contract changes they made are
listed for a targeted planning re-review; each slice's PR description names the rows
it implements.

| decision | where specified | tasks |
|---|---|---|
| PR slice map approved (15 slices; PR-14 not after PR-09) | plan "Delivery slices"; "PR-срезы" below | slice map |
| Consent line and privacy-policy sentence (privacy CHK011) | spec FR-024; contracts/navigator.md §6; data-model "Export and purge"; design M-07, D-02 | T107, T113, T116, T124 |
| Account linking turns unsent device parks into seen moves to Someday (offline-sync CHK006); unsent `extend` decisions dropped and listed on M-09 (targeted re-review) | spec FR-014, edge case "Account-less iOS use"; contracts/ios-commands.md §6, §7; data-model E10; design M-09 "account linked: extension restarted" | T057, T091, T093 |
| A device sends a zone change only when its own zone changes (offline-sync CHK016); a zone equal to the stored one is a no-op; the notification and shown next review use the device's current zone (targeted re-review) | spec FR-035, FR-036, US5-5, edge case "Two devices in different time zones"; contracts/http.md §5, formulation-clock.md §3, ios-commands.md §2, §6, §7; data-model E2, E10, E11; research R11; design "Amendments … (after /speckit-tasks)" | T039, T046, T057, T077, T151, T152, T154, T159, T163, T172 |
| A matching retry after the 24 h idempotency retention is success (offline-sync CHK023), checked before revisions; progress replay-safe by `progress_id`; undo retries succeed; constitution IV exception justified | spec FR-011, edge case "Retry long after a lost response"; contracts/http.md "Mutations", "Client-supplied ids", "Retry after the idempotency retention", §3, §6; ios-commands.md §2, §4; data-model E3, E7; plan "Complexity Tracking"; ADR-0027 §7 | T042, T043, T044, T055, T056, T086, T126, T129, T131, T133, T135, T136, T146, T173 |
| Dynamic Type up to AX5 everywhere (ux-a11y CHK008) | design "Mobile viability", M-22 "accessibility text size" | T092, T093, T094, T116, T133, T134, T137, T143, T155, T159 |
| Campaign-2 owner notes 1–6 accepted as recommended | spec Clarifications; plan "Migration, deploy order and rollback", "Post-release acceptance" | note 1: T059, T169; note 2: T042, T129; note 3: T014, T016, T017; note 4: T132, T168, T169; note 5: T126, T137, T146; note 6: T098, T105 |

## PR-срезы

Approved by the owner on 2026-10-06. A delivery boundary only: each slice still needs
its own worktree, failing tests first, independent review, CI and ADR-0008 landing;
approval is not authorization to merge or deploy. Each slice's landing class is the
last `acceptance` entry.

```json
{
  "schema_version": "brainbuddy-pr-slices/v1",
  "slices": [
    {
      "id": "PR-01",
      "outcome": "Governance: ADR-0027 accepted (ADR-0006/0001 notes, D-11 closed); the design skill, its validator test and ios/AGENTS.md say 'flag-gated, coming later while off'; the requirement-coverage gate scans Swift test trees and takes a --requirements filter; gate integrity re-recorded; architecture-guard docstring clarified.",
      "tasks": ["T001", "T002", "T003", "T004", "T005", "T006", "T007", "T008", "T009"],
      "requirements": ["020-FR-018", "020-FR-042"],
      "paths": [
        "docs/decisions/0027-native-task-weekly-review-and-auto-park.md",
        "docs/decisions/0006-native-gtd-lifecycle-and-capability-baseline.md",
        "docs/decisions/0001-vnext-modular-monolith-and-workflow-contracts.md",
        "docs/vnext-cloud-design-build-contract.md",
        "scripts/test_validate_brain_buddy_design_skill.py",
        ".claude/skills/brain-buddy-design/README.md",
        ".claude/skills/brain-buddy-design/SKILL.md",
        ".claude/skills/brain-buddy-design/preview/components-gtd-nav.html",
        "ios/AGENTS.md",
        "scripts/test_check_requirement_coverage.py",
        "scripts/check_requirement_coverage.py",
        ".specify/gate-integrity.json",
        "backend/tests/test_voice_workflow_architecture.py"
      ],
      "depends_on": [],
      "tests": [
        "python3 -m unittest scripts/test_validate_brain_buddy_design_skill.py scripts/test_check_requirement_coverage.py",
        "python3 scripts/check_gate_integrity.py",
        "cd backend && pytest tests/test_voice_workflow_architecture.py -q",
        "python3 scripts/check_spec_kit_specs.py"
      ],
      "acceptance": [
        "docs/decisions/0027-native-task-weekly-review-and-auto-park.md has Status: Accepted with the owner's sign-off date",
        "the coverage-script unit test proves a Swift test naming an id satisfies the gate and the --requirements filter",
        "check_gate_integrity.py passes with the new hash and every invariant intact",
        "owner's recorded ASK approval on the PR (scripts/ and guarded files); per-slice requirement scan not applicable (no product test in this slice)",
        "landing class ASK (scripts/classify_path_risk.py: ASK)"
      ]
    },
    {
      "id": "PR-02",
      "outcome": "Behaviour-neutral foundation (first half of the plan's PR-02): injected clock seam and frozen_clock, pure formulation.py and review_rules.py, canonical formulation and review-flow vectors executed once, wire schemas (TaskResponse fields always null) and golden wire fixtures, byte-identical iOS and web copies with a drift guard, every backend Allure rule for the review modules.",
      "tasks": ["T010", "T011", "T012", "T013", "T014", "T015", "T016", "T017", "T018", "T019", "T020", "T021", "T022", "T023", "T024"],
      "requirements": ["020-FR-001", "020-FR-002", "020-FR-003", "020-FR-004", "020-FR-005", "020-FR-007", "020-FR-009", "020-FR-012", "020-FR-015", "020-FR-016", "020-FR-017", "020-FR-019", "020-FR-028", "020-FR-029", "020-FR-031", "020-FR-032", "020-FR-036", "020-FR-039", "020-FR-045", "020-FR-046", "020-FR-051", "020-SC-004"],
      "paths": [
        "backend/tests/allure_taxonomy.py",
        "backend/tests/test_review_clock_seam.py",
        "backend/tests/conftest.py",
        "backend/app/modules/tasks/service.py",
        "backend/app/container.py",
        "backend/tests/fixtures/review_formulation_vectors.json",
        "backend/tests/fixtures/review_flow_vectors.json",
        "backend/tests/test_review_formulation.py",
        "backend/tests/test_review_formulation_vectors.py",
        "backend/app/modules/tasks/formulation.py",
        "backend/tests/test_review_flow_vectors.py",
        "backend/app/modules/tasks/review_rules.py",
        "backend/tests/test_review_wire_fixtures.py",
        "backend/app/schemas/review.py",
        "backend/app/schemas/tasks.py",
        "backend/tests/fixtures/review_wire_fixtures.json",
        "ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/Resources/review_formulation_vectors.json",
        "ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/Resources/review_flow_vectors.json",
        "ios/BrainBuddyKit/Tests/BrainBuddyAPITests/Resources/review_wire_fixtures.json",
        "frontend/src/features/review/__tests__/review_formulation_vectors.json",
        "frontend/src/features/review/__tests__/review_flow_vectors.json",
        "frontend/src/features/review/__tests__/review_wire_fixtures.json",
        "backend/pyproject.toml"
      ],
      "depends_on": ["PR-01"],
      "tests": [
        "cd backend && pytest tests/test_review_clock_seam.py tests/test_review_formulation.py tests/test_review_formulation_vectors.py tests/test_review_flow_vectors.py tests/test_review_wire_fixtures.py -q --no-cov",
        "cd backend && pytest -q",
        "make test-backend",
        "python3 scripts/check_requirement_coverage.py specs/020-weekly-review --requirements 020-FR-001,020-FR-002,020-FR-003,020-FR-004,020-FR-005,020-FR-007,020-FR-009,020-FR-012,020-FR-015,020-FR-016,020-FR-017,020-FR-019,020-FR-028,020-FR-029,020-FR-031,020-FR-032,020-FR-036,020-FR-039,020-FR-045,020-FR-046,020-FR-051,020-SC-004"
      ],
      "acceptance": [
        "every vector section passes in pytest; the drift guard fails on a deliberately edited copy and passes on byte-identical copies",
        "existing task suites unchanged and green (behaviour-neutral seam); TaskResponse formulation/parked always null",
        "make test-backend green (coverage floor, Allure taxonomy validator)",
        "landing class SHOW (scripts/classify_path_risk.py: SHIP; shared contract for every lane)"
      ]
    },
    {
      "id": "PR-15",
      "outcome": "Backend behaviour (second half of the plan's PR-02): weekly_review flag (exposure-only gate), all review tables, ReviewService and the generalised serialized writer, shared task_mapping, clock maintenance in task commands, decisions (including the matching-record answer to a retry after the 24 h idempotency retention), undo, settings and state, explainer acknowledgement and activation (only the activating acknowledgement stores a zone), the maintenance sweep (retention + exposure) and device auto-park with the yield rule, park acknowledgements, export/purge, TEST-only CLI, decision/park traces, data-retention and privacy-policy rows; routers for navigator and flow mounted empty.",
      "tasks": ["T025", "T026", "T027", "T028", "T029", "T030", "T031", "T032", "T033", "T034", "T035", "T036", "T037", "T038", "T039", "T040", "T041", "T042", "T043", "T044", "T045", "T046", "T047", "T077", "T078", "T079", "T080", "T081", "T082", "T083", "T084", "T085", "T086"],
      "requirements": ["020-FR-001", "020-FR-002", "020-FR-003", "020-FR-004", "020-FR-005", "020-FR-006", "020-FR-007", "020-FR-008", "020-FR-009", "020-FR-010", "020-FR-011", "020-FR-012", "020-FR-013", "020-FR-014", "020-FR-015", "020-FR-016", "020-FR-017", "020-FR-018", "020-FR-026", "020-FR-032", "020-FR-033", "020-FR-035", "020-FR-038", "020-FR-039", "020-FR-042", "020-FR-043", "020-FR-044", "020-FR-045", "020-FR-046", "020-FR-048", "020-FR-051", "020-SC-006", "020-SC-007"],
      "paths": [
        "backend/tests/test_feature_flags.py",
        "backend/tests/test_feature_flag_repository.py",
        "backend/app/core/config.py",
        "backend/app/repositories/feature_flag.py",
        "backend/tests/test_review_repository.py",
        "backend/app/modules/tasks/review_domain.py",
        "backend/app/modules/tasks/domain.py",
        "backend/app/modules/tasks/review_repository.py",
        "backend/app/modules/tasks/repository.py",
        "backend/app/modules/tasks/service.py",
        "backend/app/modules/tasks/review_service.py",
        "backend/app/modules/tasks/review_flow.py",
        "backend/app/container.py",
        "backend/tests/test_review_gate_api.py",
        "backend/app/api/dependencies.py",
        "backend/app/api/review.py",
        "backend/app/api/review_navigator.py",
        "backend/app/api/review_flow.py",
        "backend/app/api/__init__.py",
        "backend/app/api/task_mapping.py",
        "backend/app/api/tasks.py",
        "backend/pyproject.toml",
        "backend/tests/test_review_export_purge.py",
        "backend/app/services/account_service.py",
        "backend/tests/test_review_log_privacy.py",
        "frontend/src/pages/PrivacyPolicyPage.tsx",
        "frontend/src/pages/__tests__/PrivacyPolicyPage.test.tsx",
        "docs/data-retention.md",
        "backend/tests/test_review_clock_api.py",
        "backend/app/schemas/tasks.py",
        "backend/tests/test_review_decisions_api.py",
        "backend/tests/test_review_settings_api.py",
        "backend/tests/test_review_auto_park.py",
        "backend/app/main.py",
        "backend/tests/test_review_cli.py",
        "backend/app/cli.py",
        "backend/tests/fixtures/review_traces_tasks.json",
        "backend/tests/test_review_traces.py",
        "ios/BrainBuddyKit/Tests/BrainBuddySyncTests/Resources/review_traces_tasks.json",
        "backend/tests/test_review_formulation_vectors.py"
      ],
      "depends_on": ["PR-02"],
      "tests": [
        "cd backend && pytest tests/test_feature_flags.py tests/test_feature_flag_repository.py tests/test_review_repository.py tests/test_review_gate_api.py tests/test_review_clock_api.py tests/test_review_decisions_api.py tests/test_review_settings_api.py tests/test_review_auto_park.py tests/test_review_export_purge.py tests/test_review_log_privacy.py tests/test_review_cli.py tests/test_review_traces.py tests/test_crt_receipt_retention.py -q",
        "cd frontend && npx vitest run src/pages/__tests__/PrivacyPolicyPage.test.tsx",
        "make test-backend",
        "python3 scripts/check_requirement_coverage.py specs/020-weekly-review --requirements 020-FR-001,020-FR-002,020-FR-003,020-FR-004,020-FR-005,020-FR-006,020-FR-007,020-FR-008,020-FR-009,020-FR-010,020-FR-011,020-FR-012,020-FR-013,020-FR-014,020-FR-015,020-FR-016,020-FR-017,020-FR-018,020-FR-026,020-FR-032,020-FR-033,020-FR-035,020-FR-038,020-FR-039,020-FR-042,020-FR-043,020-FR-044,020-FR-045,020-FR-046,020-FR-048,020-FR-051,020-SC-006,020-SC-007"
      ],
      "acceptance": [
        "quickstart Scenarios 1 (backend steps), 2 (steps 1-3, 5-10), 7 (backend), Privacy read-back and Rollout read-back pass on synthetic data",
        "log-capture test: no sentinel text and no stall-reason value in any log; sweep failure logs the exception type only",
        "flag OFF: gated reads 404 weekly_review_disabled, queued writes accepted, auto-park applied:false, retention still runs",
        "a decision retried after the 24 h idempotency retention with a matching stored record answers 200 and is applied once; a non-matching reuse is id_conflict; a later explainer acknowledgement with another zone changes nothing",
        "owner's recorded ASK approval (api/tasks.py, api/dependencies.py; privacy export/purge; first automatic GTD state change)",
        "landing class ASK (scripts/classify_path_risk.py: ASK)"
      ]
    },
    {
      "id": "PR-03",
      "outcome": "iOS core (BrainBuddyKit): records, the clock in the reducer with client form ids, clock-aware compaction, the post-replay activation step, every new GTDCommand and ReviewCommand with its conflict rule, review queries and Core planners (MarkerStyle, StallReasonRecommendation, UndoWindowPolicy, ReviewPresentation, WhileAwayPresentation, ActiveTimeAccumulator, ReviewLayout, ReviewReminderPlanner, ReviewEntryPlanner, DeviceZoneTracker), the ReviewCopy catalog, form drafts, device auto-park and local retention, account linking that turns unsent local auto-parks into seen moves to Someday, the device time-zone rule, StoreDocument v2, API/sync mapping with .featureDisabled back-off and success on a matching retry after the retention, and the fake server.",
      "tasks": ["T048", "T049", "T050", "T051", "T052", "T053", "T054", "T055", "T056", "T057", "T058", "T087", "T088", "T089", "T090", "T091", "T108", "T133", "T134", "T135", "T151", "T152"],
      "requirements": ["020-FR-001", "020-FR-002", "020-FR-003", "020-FR-004", "020-FR-005", "020-FR-006", "020-FR-007", "020-FR-008", "020-FR-009", "020-FR-010", "020-FR-011", "020-FR-012", "020-FR-013", "020-FR-014", "020-FR-015", "020-FR-016", "020-FR-017", "020-FR-018", "020-FR-024", "020-FR-028", "020-FR-029", "020-FR-030", "020-FR-031", "020-FR-032", "020-FR-035", "020-FR-036", "020-FR-037", "020-FR-038", "020-FR-039", "020-FR-040", "020-FR-043", "020-FR-045", "020-FR-046", "020-FR-047", "020-FR-048", "020-FR-051", "020-FR-052", "020-SC-004", "020-SC-006", "020-SC-007"],
      "paths": [
        "ios/BrainBuddyKit/Package.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddySyncTests/Resources/README.md",
        "ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/FormulationTests.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/Formulation.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ReducerReviewTests.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/Records.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/Commands.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/Reducer.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/Reducer+Review.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/Replay.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/Compaction.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/QueriesReviewTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ReviewPlannersTests.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/Queries+Review.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/ReviewPlanners.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/ReviewCopy.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/Review.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ReviewAccountLinkingTests.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/ReviewAccountLinking.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyAPITests/ReviewWireTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddySyncTests/ReviewSyncTests.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyAPI/WireModels.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyAPI/RequestBodies.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyAPI/APIError.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyAPI/BrainBuddyAPIClient.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyAPI/ReviewAPI.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddySync/GTDCommand+Sync.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddySync/PushPlanner.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddySync/SyncEngine+Push.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddySync/SyncEngine+Pull.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddySync/StoreDocument+Merge.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyFakeServer/FakeServer+Review.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyPersistenceTests/StoreDocumentCodingTests.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyPersistence/StoreDocumentCoding.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/Outbox.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/WorkspaceReviewTests.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyWorkspace/Workspace.swift"
      ],
      "depends_on": ["PR-02"],
      "tests": [
        "sh ios/scripts/swift-linux.sh test",
        "sh ios/scripts/swift-linux.sh test --filter BrainBuddyCoreTests",
        "sh ios/scripts/swift-linux.sh test --filter BrainBuddySyncTests",
        "sh ios/scripts/swift-linux.sh test --filter BrainBuddyWorkspaceTests",
        "python3 scripts/check_requirement_coverage.py specs/020-weekly-review --requirements 020-FR-001,020-FR-002,020-FR-003,020-FR-004,020-FR-005,020-FR-006,020-FR-007,020-FR-008,020-FR-009,020-FR-010,020-FR-011,020-FR-012,020-FR-013,020-FR-014,020-FR-015,020-FR-016,020-FR-017,020-FR-018,020-FR-024,020-FR-028,020-FR-029,020-FR-030,020-FR-031,020-FR-032,020-FR-035,020-FR-036,020-FR-037,020-FR-038,020-FR-039,020-FR-040,020-FR-043,020-FR-045,020-FR-046,020-FR-047,020-FR-048,020-FR-051,020-FR-052,020-SC-004,020-SC-006,020-SC-007"
      ],
      "acceptance": [
        "all shared vector sections pass in Swift; compacted and uncompacted replays give identical clocks",
        "quickstart Scenario 3 steps 1-8 pass as package tests against BrainBuddyFakeServer",
        "ReviewSyncTests: flag off with 3 queued review commands -> 0 set-asides; two devices park -> one server park, 0 sync issues; device clock 2 days ahead online -> no local park; a decision retried after the retention -> success, 0 sync issues",
        "account linking: unsent account-less parks become seen moves to Someday, none back in Next, an unsent extend is dropped and listed on M-09, 0 sync issues; a zone change is queued only after the device's own zone changed; the reminder fires in the device's current zone",
        "ReviewCopy and MarkerStyle tests prove no banned term and no error role; ReviewLayout gives one summary column and a scrolling step bar exactly at accessibility sizes",
        "landing class SHOW (scripts/classify_path_risk.py: SHIP; persistence format change)"
      ]
    },
    {
      "id": "PR-04",
      "outcome": "iOS app increment 1: exposure switch (BBWeeklyReviewLocal NO in Release), M-26 explainer, M-01 markers, M-02 'This wording', M-03 card as a large sheet, M-04 forms with unsaved-text guard and drafts (no Suggest), Undo toasts, M-09 While you were away, M-23 threshold; Dynamic Type up to AX5; the decision and park golden traces (from PR-15) replayed against the fake server; manual evidence for increment 1.",
      "tasks": ["T059", "T060", "T061", "T062", "T063", "T064", "T065", "T092", "T093", "T094", "T173"],
      "requirements": ["020-FR-001", "020-FR-002", "020-FR-003", "020-FR-004", "020-FR-005", "020-FR-006", "020-FR-007", "020-FR-008", "020-FR-009", "020-FR-010", "020-FR-011", "020-FR-012", "020-FR-013", "020-FR-014", "020-FR-015", "020-FR-016", "020-FR-018", "020-FR-039", "020-FR-042", "020-FR-045", "020-FR-046", "020-FR-047", "020-FR-048", "020-FR-051", "020-FR-052", "020-SC-006", "020-SC-007"],
      "paths": [
        "ios/project.yml",
        "ios/BrainBuddy/App/RootView.swift",
        "ios/BrainBuddy/App/BrainBuddyApp.swift",
        "ios/BrainBuddy/Components/TaskRow.swift",
        "ios/BrainBuddy/Components/Chips.swift",
        "ios/BrainBuddy/Components/Toasts.swift",
        "ios/BrainBuddy/Screens/Lists/TaskListScreen.swift",
        "ios/BrainBuddy/Screens/Detail/TaskDetailScreen.swift",
        "ios/BrainBuddy/Screens/Review/FormulationSection.swift",
        "ios/BrainBuddy/Screens/Review/DecisionCardSheet.swift",
        "ios/BrainBuddy/Screens/Review/DecisionForms.swift",
        "ios/BrainBuddy/Screens/Review/AutoParkExplainerSheet.swift",
        "ios/BrainBuddy/Screens/Review/WhileYouWereAwaySheet.swift",
        "ios/BrainBuddy/Screens/Settings/ReviewSettingsSection.swift",
        "ios/BrainBuddy/Screens/Settings/SettingsScreen.swift",
        "specs/020-weekly-review/evidence/manual-ios-increment1.md",
        "ios/BrainBuddyKit/Tests/BrainBuddySyncTests/ReviewTaskTraceReplayTests.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyFakeServer/FakeServer+Review.swift"
      ],
      "depends_on": ["PR-03", "PR-15"],
      "tests": [
        "sh ios/scripts/swift-linux.sh test",
        "sh ios/scripts/swift-linux.sh test --filter ReviewTaskTraceReplayTests",
        "(cd ios && xcodegen generate) && xcodebuild -project ios/BrainBuddy.xcodeproj -scheme BrainBuddy -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build",
        "python3 scripts/check_requirement_coverage.py specs/020-weekly-review --requirements 020-FR-001,020-FR-002,020-FR-003,020-FR-004,020-FR-005,020-FR-006,020-FR-007,020-FR-008,020-FR-009,020-FR-010,020-FR-011,020-FR-012,020-FR-013,020-FR-014,020-FR-015,020-FR-016,020-FR-018,020-FR-039,020-FR-042,020-FR-045,020-FR-046,020-FR-047,020-FR-048,020-FR-051,020-FR-052,020-SC-006,020-SC-007"
      ],
      "acceptance": [
        "ios-app lane green on the exact SHA; previews for every M-01, M-02, M-03, M-04, M-09, M-26 state",
        "ReviewTaskTraceReplayTests: review_traces_tasks.json (PR-15) replays against BrainBuddyFakeServer with the recorded statuses and responses, incl. the decision retried after the 24 h retention answered as already applied",
        "specs/020-weekly-review/evidence/manual-ios-increment1.md (labelled manual): large detent, interactiveDismissDisabled, Undo announcement >= 10 s, 44 pt targets, VoiceOver focus on M-26 and M-09, M-01 - M-04, M-09 and M-26 at Dynamic Type AX5",
        "Release configuration keeps BBWeeklyReviewLocal = NO and the DeferredRow when not exposed",
        "landing class SHOW (scripts/classify_path_risk.py: SHIP)"
      ]
    },
    {
      "id": "PR-05",
      "outcome": "Web increment 1: review API client, formulation.ts and stall recommendation against the shared vectors, D-01 markers, D-06 'This wording', D-02 dialog without navigator (drafts, beforeunload, history guard), action toast with Ctrl/Cmd+Z, D-04 threshold, D-05 explainer, While-you-were-away dialog at web open, the string/token and client-telemetry guard, the /features/review/ Allure rule.",
      "tasks": ["T066", "T067", "T068", "T069", "T070", "T071", "T072", "T073", "T074", "T075", "T076", "T095", "T096", "T097"],
      "requirements": ["020-FR-001", "020-FR-002", "020-FR-003", "020-FR-004", "020-FR-005", "020-FR-006", "020-FR-007", "020-FR-009", "020-FR-010", "020-FR-011", "020-FR-012", "020-FR-015", "020-FR-016", "020-FR-018", "020-FR-038", "020-FR-039", "020-FR-040", "020-FR-042", "020-FR-044", "020-FR-045", "020-FR-046", "020-FR-048", "020-FR-051", "020-FR-052"],
      "paths": [
        "frontend/src/test/allureTaxonomy.ts",
        "frontend/src/features/review/__tests__/formulation.test.ts",
        "frontend/src/features/review/formulation.ts",
        "frontend/stryker.config.json",
        "frontend/src/api/__tests__/review.test.ts",
        "frontend/src/api/review.ts",
        "frontend/src/api/reviewHooks.ts",
        "frontend/src/api/taskTypes.ts",
        "frontend/src/features/review/__tests__/stallRecommendation.test.ts",
        "frontend/src/features/review/stallRecommendation.ts",
        "frontend/src/components/shell/__tests__/shellToast.test.tsx",
        "frontend/src/components/shell/__tests__/AppShell.test.tsx",
        "frontend/src/components/shell/shellToast.ts",
        "frontend/src/components/shell/AppShell.tsx",
        "frontend/src/features/tasks/__tests__/TaskListPage.test.tsx",
        "frontend/src/features/tasks/TaskListPage.tsx",
        "frontend/src/features/review/__tests__/FormulationBlock.test.tsx",
        "frontend/src/features/review/FormulationBlock.tsx",
        "frontend/src/features/tasks/TaskDetailPanel.tsx",
        "frontend/src/features/review/__tests__/DecisionDialog.test.tsx",
        "frontend/src/features/review/DecisionDialog.tsx",
        "frontend/src/features/review/__tests__/reviewFormDrafts.test.ts",
        "frontend/src/features/review/__tests__/useLeaveGuard.test.tsx",
        "frontend/src/features/review/reviewFormDrafts.ts",
        "frontend/src/features/review/useLeaveGuard.ts",
        "frontend/src/features/review/__tests__/ReviewSettingsSection.test.tsx",
        "frontend/src/features/account/__tests__/AccountSettingsPage.test.tsx",
        "frontend/src/features/review/ReviewSettingsSection.tsx",
        "frontend/src/features/account/AccountSettingsPage.tsx",
        "frontend/src/features/review/__tests__/copyGuard.test.ts",
        "frontend/src/features/review/__tests__/AutoParkExplainer.test.tsx",
        "frontend/src/features/review/AutoParkExplainer.tsx",
        "frontend/src/features/review/__tests__/WhileYouWereAway.test.tsx",
        "frontend/src/features/review/__tests__/wywaPresentation.test.ts",
        "frontend/src/features/review/WhileYouWereAway.tsx",
        "frontend/src/features/review/wywaPresentation.ts",
        "frontend/src/features/review/ReviewStartupDialogs.tsx"
      ],
      "depends_on": ["PR-02"],
      "tests": [
        "cd frontend && npx vitest run src/features/review src/features/tasks src/features/account src/components/shell src/api",
        "make test-frontend",
        "cd frontend && npx tsc --noEmit && npx eslint src",
        "python3 scripts/check_requirement_coverage.py specs/020-weekly-review --requirements 020-FR-001,020-FR-002,020-FR-003,020-FR-004,020-FR-005,020-FR-006,020-FR-007,020-FR-009,020-FR-010,020-FR-011,020-FR-012,020-FR-015,020-FR-016,020-FR-018,020-FR-038,020-FR-039,020-FR-040,020-FR-042,020-FR-044,020-FR-045,020-FR-046,020-FR-048,020-FR-051,020-FR-052"
      ],
      "acceptance": [
        "Vitest proves every D-01, D-02 (no navigator), D-04 threshold, D-05, D-06 and WYWA-dialog state, focus and Esc rule named in design.md",
        "AppShell flag-off test still asserts 'Weekly review — Coming soon' unchanged",
        "copy/telemetry guard green; frontend coverage floor unchanged or higher",
        "landing class SHOW (scripts/classify_path_risk.py: SHIP)"
      ]
    },
    {
      "id": "PR-06",
      "outcome": "Mac pre-sync 'Weekly review · coming later' non-interactive sidebar row (FR-041), with sidebar entries extracted into a testable value; evidence is a recorded macOS-host run.",
      "tasks": ["T164", "T165"],
      "requirements": ["020-FR-041"],
      "paths": [
        "macos/Tests/BrainBuddyMacTests/WeeklyReviewRowTests.swift",
        "macos/Sources/BrainBuddyMac/SidebarEntries.swift",
        "macos/Sources/BrainBuddyMac/ContentView.swift",
        "specs/020-weekly-review/evidence/macos-host-run.md"
      ],
      "depends_on": ["PR-01"],
      "tests": [
        "cd macos && swift test --disable-sandbox  # macOS host only; no CI lane runs macos/",
        "python3 scripts/check_requirement_coverage.py specs/020-weekly-review --requirements 020-FR-041"
      ],
      "acceptance": [
        "specs/020-weekly-review/evidence/macos-host-run.md records the passing host run",
        "the row is non-interactive and sits right after Lists; no local-only review ships",
        "landing class SHIP (scripts/classify_path_risk.py: SHIP)"
      ]
    },
    {
      "id": "PR-07",
      "outcome": "Backend navigator: OpenAI adapter in app/ai behind the NavigatorProvider port (startup raises without the key; key-rotation runbook in .env.example), navigator domain (reduce_notes, validation, consent rules), consent with text versions (read and revoke never gated), cost admission outside the task lock, rate limit, shown counter, routes; synthetic SC-005 eval set and deterministic screen runner; privacy-policy and data-retention rows for the navigator, including the sentence that notes and titles go to the provider as written, names of other people included.",
      "tasks": ["T098", "T099", "T100", "T101", "T102", "T103", "T104", "T105", "T106", "T107"],
      "requirements": ["020-FR-019", "020-FR-020", "020-FR-021", "020-FR-024", "020-FR-025", "020-FR-026", "020-FR-043", "020-FR-044", "020-FR-045", "020-SC-005"],
      "paths": [
        "backend/tests/test_review_navigator.py",
        "backend/app/core/config.py",
        "backend/app/ai/review_navigator.py",
        "backend/app/container.py",
        "backend/app/modules/tasks/navigator.py",
        "backend/app/api/review_navigator.py",
        "backend/app/core/rate_limit.py",
        "backend/tests/fixtures/navigator/eval_v1.json",
        "backend/tests/fixtures/navigator/recorded_v1_sample.json",
        "backend/tests/test_review_navigator_eval.py",
        ".env.example",
        "frontend/src/pages/PrivacyPolicyPage.tsx",
        "frontend/src/pages/__tests__/PrivacyPolicyPage.test.tsx",
        "docs/data-retention.md"
      ],
      "depends_on": ["PR-15"],
      "tests": [
        "cd backend && pytest tests/test_review_navigator.py tests/test_review_navigator_eval.py -q",
        "cd frontend && npx vitest run src/pages/__tests__/PrivacyPolicyPage.test.tsx",
        "make test-backend",
        "python3 scripts/check_requirement_coverage.py specs/020-weekly-review --requirements 020-FR-019,020-FR-020,020-FR-021,020-FR-024,020-FR-025,020-FR-026,020-FR-043,020-FR-044,020-FR-045,020-SC-005"
      ],
      "acceptance": [
        "first failing test of the slice: container build raises without the key (observed RED in the PR)",
        "quickstart Scenario 4 steps 0-5, 7-9 pass with the deterministic provider; no live provider call in CI",
        "lock test: a provider stub taking command_lock for another owner neither deadlocks nor waits",
        "PrivacyPolicyPage test proves the navigator section states that notes and titles are sent as written, names of other people included, under the person's consent",
        "owner's recorded ASK approval (provider credentials, new egress, consent, privacy disclosure)",
        "landing class ASK (scripts/classify_path_risk.py: ASK)"
      ]
    },
    {
      "id": "PR-11",
      "outcome": "Backend review flow: runs (client ids, replace_open, merged progress, Done-only finish with completed_empty, idle close, active time), queues incl. capacity mirror and Waiting/Someday eligibility, bulk release with server-side eligibility and clock-exact undo, success on a matching retry after the 24 h retention for runs and bulk releases, replay-safe progress (progress_id), idempotent bulk-release undo, restart anchor, SC-002 rule, run traces with their iOS copy, the review-metrics read-out.",
      "tasks": ["T126", "T127", "T128", "T129", "T130", "T131", "T132"],
      "requirements": ["020-FR-011", "020-FR-017", "020-FR-027", "020-FR-028", "020-FR-029", "020-FR-030", "020-FR-031", "020-FR-032", "020-FR-033", "020-FR-034", "020-FR-045", "020-FR-050", "020-SC-001", "020-SC-002", "020-SC-003", "020-SC-004", "020-SC-005", "020-SC-007"],
      "paths": [
        "backend/tests/test_review_flow_api.py",
        "backend/app/modules/tasks/review_flow.py",
        "backend/app/api/review_flow.py",
        "backend/app/modules/tasks/review_service.py",
        "backend/app/modules/tasks/review_repository.py",
        "backend/tests/fixtures/review_traces_runs.json",
        "backend/tests/test_review_traces.py",
        "ios/BrainBuddyKit/Tests/BrainBuddySyncTests/Resources/review_traces_runs.json",
        "backend/tests/test_review_formulation_vectors.py",
        "backend/tests/test_review_metrics_readout.py",
        "backend/app/cli.py"
      ],
      "depends_on": ["PR-15"],
      "tests": [
        "cd backend && pytest tests/test_review_flow_api.py tests/test_review_traces.py tests/test_review_metrics_readout.py tests/test_review_formulation_vectors.py -q",
        "make test-backend",
        "python3 scripts/check_requirement_coverage.py specs/020-weekly-review --requirements 020-FR-011,020-FR-017,020-FR-027,020-FR-028,020-FR-029,020-FR-030,020-FR-031,020-FR-032,020-FR-033,020-FR-034,020-FR-045,020-FR-050,020-SC-001,020-SC-002,020-SC-003,020-SC-004,020-SC-005,020-SC-007"
      ],
      "acceptance": [
        "quickstart Scenario 5 steps 2-6, 9 pass at the API level on synthetic data; SC-002 flow test green",
        "byte-identical responses for unknown vs foreign ids in bulk bodies and the queue session_id (second_api_client)",
        "a session start and a bulk release retried after the 24 h retention with a matching stored record succeed and are applied once (the match checked before revisions and replace_open); a progress change resent with the same progress_id is merged once; an already undone bulk release answers its stored undo result",
        "review-metrics read-out prints aggregates with sample sizes only",
        "landing class SHOW (scripts/classify_path_risk.py: SHIP)"
      ]
    },
    {
      "id": "PR-12",
      "outcome": "iOS app increment 3 (rescoped 2026-10-07: no navigator block, notification, widget chip or day/time settings): run-trace replay against the fake server (the decision and park traces replay in PR-04), review cover and step chrome, M-10 restart, M-11 entry/resume, M-12 onboarding, M-13 - M-22 steps, Lists entry replacing DeferredRow, Dynamic Type up to AX5, iOS docs; manual evidence; and the follow-up from PR-15: the device decision Undo keeps the server's clock bookkeeping (floor kept, clamp on restore) through a shared pure restore with new vectors.",
      "tasks": ["T136", "T137", "T138", "T139", "T140", "T141", "T142", "T143", "T153", "T156", "T158", "T159", "T174", "T175", "T176"],
      "requirements": ["020-FR-002", "020-FR-006", "020-FR-016", "020-FR-017", "020-FR-043", "020-FR-018", "020-FR-027", "020-FR-028", "020-FR-029", "020-FR-030", "020-FR-031", "020-FR-032", "020-FR-033", "020-FR-034", "020-FR-035", "020-FR-038", "020-FR-042", "020-FR-045", "020-FR-046", "020-FR-048", "020-FR-050", "020-FR-052", "020-SC-002", "020-SC-003", "020-SC-007"],
      "paths": [
        "ios/BrainBuddyKit/Tests/BrainBuddySyncTests/ReviewTraceReplayTests.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyFakeServer/FakeServer+Review.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/ReviewCopy.swift",
        "ios/BrainBuddy/App/AppRouteView.swift",
        "ios/BrainBuddy/Screens/Review/ReviewCover.swift",
        "ios/BrainBuddy/Screens/Review/ReviewEntryScreen.swift",
        "ios/BrainBuddy/Screens/Review/RestartScreen.swift",
        "ios/BrainBuddy/Screens/Review/WinsStep.swift",
        "ios/BrainBuddy/Screens/Review/MindSweepStep.swift",
        "ios/BrainBuddy/Screens/Review/InboxStep.swift",
        "ios/BrainBuddy/Screens/Process/ProcessInboxScreen.swift",
        "ios/BrainBuddy/Screens/Review/DecisionsStep.swift",
        "ios/BrainBuddy/Screens/Review/RestOfNextStep.swift",
        "ios/BrainBuddy/Screens/Review/WaitingStep.swift",
        "ios/BrainBuddy/Screens/Review/ProjectsStep.swift",
        "ios/BrainBuddy/Screens/Review/SomedayStep.swift",
        "ios/BrainBuddy/Screens/Review/DatesStep.swift",
        "ios/BrainBuddy/Screens/Review/SummaryStep.swift",
        "ios/BrainBuddy/Screens/Review/OnboardingScreen.swift",
        "ios/BrainBuddy/Screens/Browse/ListsHubScreen.swift",
        "docs/native-ios-app.md",
        "ios/README.md",
        "specs/020-weekly-review/evidence/manual-ios-increment3.md",
        "backend/tests/fixtures/review_formulation_vectors.json",
        "ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/Resources/review_formulation_vectors.json",
        "frontend/src/features/review/__tests__/review_formulation_vectors.json",
        "backend/app/modules/tasks/formulation.py",
        "backend/tests/test_review_formulation_vectors.py",
        "backend/app/modules/tasks/review_service.py",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/Formulation.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/Reducer+Review.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/Commands.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/FormulationTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ReducerReviewTests.swift", "ios/BrainBuddyKit/Sources/BrainBuddySync/StoreDocument+Merge.swift", "ios/BrainBuddyKit/Tests/BrainBuddySyncTests/ReviewSyncTests.swift", "ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/ReducerReviewReplayTests.swift",
        "specs/020-weekly-review/contracts/ios-commands.md",
        "specs/020-weekly-review/contracts/formulation-clock.md"
      ],
      "depends_on": ["PR-04", "PR-05", "PR-11"],
      "tests": [
        "sh ios/scripts/swift-linux.sh test",
        "sh ios/scripts/swift-linux.sh test --filter ReviewTraceReplayTests",
        "cd backend && pytest tests/test_review_formulation_vectors.py tests/test_review_decisions_api.py -q --no-cov",
        "make test-backend",
        "(cd ios && xcodegen generate) && xcodebuild -project ios/BrainBuddy.xcodeproj -scheme BrainBuddy -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build",
        "python3 scripts/check_requirement_coverage.py specs/020-weekly-review --requirements 020-FR-002,020-FR-006,020-FR-016,020-FR-017,020-FR-018,020-FR-027,020-FR-028,020-FR-029,020-FR-030,020-FR-031,020-FR-032,020-FR-033,020-FR-034,020-FR-035,020-FR-038,020-FR-042,020-FR-045,020-FR-046,020-FR-048,020-FR-050,020-FR-052,020-SC-002,020-SC-003,020-SC-007"
      ],
      "acceptance": [
        "ReviewTraceReplayTests: review_traces_runs.json (PR-11) replays against BrainBuddyFakeServer with the recorded responses, incl. a progress change retried after the retention merged once",
        "previews for every shipped M-10 - M-22 state, incl. M-22 'accessibility text size'; ios-app lane green on the exact SHA",
        "specs/020-weekly-review/evidence/manual-ios-increment3.md (labelled manual): one decision per screen, Lists row, VoiceOver focus M-10/M-11/M-12, every shipped screen at Dynamic Type AX5",
        "T175: an undone bulk release never leaves a Next task without a clock on the device, and no released item keeps its pre-release clock after the undo",
        "T176: the reducer refuses a progress step or active-seconds code outside the session's mode, so the server's out-of-mode 422 is never produced by a queued command",
        "T174: the floor-kept and clamp-on-restore vectors pass in Python and Swift, the three vector copies stay byte-identical, and a decision Undo gives the same clock on the server, a signed-in device and an account-less device",
        "landing class SHOW (scripts/classify_path_risk.py: SHIP)"
      ]
    },
    {
      "id": "PR-13",
      "outcome": "Web increment 3 (rescoped 2026-10-07: no navigator, day/time settings, device zone, next-review slot or active time): /review route (ReviewGate, ReviewShell, entry with resume and last-review summary), every step incl. the new web Inbox step and restart states, onboarding dialog, sidebar and drawer link with 'Last review', session progress with a replay-safe progress_id, the Playwright suite with the keyboard-only story and axe scans.",
      "tasks": ["T144", "T146", "T147", "T148", "T149", "T150", "T160", "T161"],
      "requirements": ["020-FR-002", "020-FR-004", "020-FR-015", "020-FR-016", "020-FR-017", "020-FR-027", "020-FR-028", "020-FR-029", "020-FR-030", "020-FR-031", "020-FR-032", "020-FR-033", "020-FR-034", "020-FR-035", "020-FR-036", "020-FR-038", "020-FR-040", "020-FR-042", "020-FR-045", "020-FR-048", "020-FR-050", "020-FR-052", "020-SC-002", "020-SC-006", "020-SC-007"],
      "paths": [
        "frontend/tests/allure.fixtures.ts",
        "frontend/src/features/review/__tests__/ReviewShell.test.tsx",
        "frontend/src/app/AppRoutes.test.tsx",
        "frontend/src/features/review/ReviewGate.tsx",
        "frontend/src/features/review/ReviewShell.tsx",
        "frontend/src/features/review/ReviewEntry.tsx",
        "frontend/src/app/AppRoutes.tsx",
        "frontend/src/api/review.ts",
        "frontend/src/api/reviewHooks.ts",
        "frontend/src/features/review/__tests__/InboxStep.test.tsx",
        "frontend/src/features/review/__tests__/RestartStep.test.tsx",
        "frontend/src/features/review/steps/InboxStep.tsx",
        "frontend/src/features/review/steps/RestartStep.tsx",
        "frontend/src/features/review/__tests__/DecisionsStep.test.tsx",
        "frontend/src/features/review/steps/DecisionsStep.tsx",
        "frontend/src/features/review/__tests__/ReviewSteps.test.tsx",
        "frontend/src/features/review/steps/WinsStep.tsx",
        "frontend/src/features/review/steps/MindSweepStep.tsx",
        "frontend/src/features/review/steps/RestOfNextStep.tsx",
        "frontend/src/features/review/steps/WaitingStep.tsx",
        "frontend/src/features/review/steps/ProjectsStep.tsx",
        "frontend/src/features/review/steps/SomedayStep.tsx",
        "frontend/src/features/review/steps/DatesStep.tsx",
        "frontend/src/features/review/steps/SummaryStep.tsx",
        "frontend/tests/e2e/weekly-review.spec.ts",
        "frontend/src/components/shell/__tests__/AppShell.test.tsx",
        "frontend/src/components/shell/AppShell.tsx",
        "frontend/src/features/review/__tests__/OnboardingDialog.test.tsx",
        "frontend/src/features/review/OnboardingDialog.tsx"
      ],
      "depends_on": ["PR-05", "PR-11"],
      "tests": [
        "cd frontend && npx vitest run src/features/review src/components/shell src/app",
        "cd frontend && npx playwright test tests/e2e/weekly-review.spec.ts",
        "make test-frontend",
        "make test-e2e",
        "python3 scripts/check_requirement_coverage.py specs/020-weekly-review --requirements 020-FR-002,020-FR-004,020-FR-015,020-FR-016,020-FR-017,020-FR-027,020-FR-028,020-FR-029,020-FR-030,020-FR-031,020-FR-032,020-FR-033,020-FR-034,020-FR-035,020-FR-036,020-FR-038,020-FR-040,020-FR-042,020-FR-045,020-FR-048,020-FR-050,020-FR-052,020-SC-002,020-SC-006,020-SC-007"
      ],
      "acceptance": [
        "Playwright: quick review end-to-end, SC-007 summary on /review, keyboard-only story E2E-A11Y-01, axe scans with no violations at desktop and 390 px, no horizontal overflow at 390 x 851",
        "E2E-MOBILE-02 (flag off) still asserts the disabled 'Weekly review — Coming soon' entry",
        "Allure report for the run with every new test carrying epic/feature/story and a 020 id",
        "landing class SHOW (scripts/classify_path_risk.py: SHIP)"
      ]
    },
    {
      "id": "PR-14",
      "outcome": "Release: the full-feature requirement-coverage gate and the copy byte check in make check-specs (gate integrity re-recorded), coverage floors raised, evidence README and the real-use read-out template with the owner-confirmed minimum samples, the owner's recorded rollout decisions (flag stages, widening beyond the owner only after the 8-week read-out, BBWeeklyReviewLocal decision), full verification. Rescoped 2026-10-07: the requirement-coverage gate lists every id except the deferred FR-022, FR-023 and FR-049; no mutation-scope promotion; no cloud navigator rollout.",
      "tasks": ["T166", "T167", "T168", "T169", "T171"],
      "requirements": ["020-FR-042", "020-SC-001", "020-SC-003", "020-SC-004"],
      "paths": [
        "Makefile",
        ".specify/gate-integrity.json",
        "backend/coverage-floor.json",
        "frontend/coverage-floor.json",
        "specs/020-weekly-review/evidence/README.md",
        "specs/020-weekly-review/evidence/real-use-readout.md",
        "specs/020-weekly-review/evidence/rollout-decisions.md"
      ],
      "depends_on": ["PR-06", "PR-12", "PR-13"],
      "tests": [
        "make check-specs",
        "python3 scripts/check_requirement_coverage.py specs/020-weekly-review --requirements 020-FR-001,020-FR-002,020-FR-003,020-FR-004,020-FR-005,020-FR-006,020-FR-007,020-FR-008,020-FR-009,020-FR-010,020-FR-011,020-FR-012,020-FR-013,020-FR-014,020-FR-015,020-FR-016,020-FR-017,020-FR-018,020-FR-019,020-FR-020,020-FR-021,020-FR-024,020-FR-025,020-FR-026,020-FR-027,020-FR-028,020-FR-029,020-FR-030,020-FR-031,020-FR-032,020-FR-033,020-FR-034,020-FR-035,020-FR-036,020-FR-037,020-FR-038,020-FR-039,020-FR-040,020-FR-041,020-FR-042,020-FR-043,020-FR-044,020-FR-045,020-FR-046,020-FR-047,020-FR-048,020-FR-050,020-FR-051,020-FR-052,020-SC-001,020-SC-002,020-SC-003,020-SC-004,020-SC-005,020-SC-006,020-SC-007",
        "python3 scripts/check_gate_integrity.py",
        "make test-backend && make test-frontend && make test-e2e",
        "sh ios/scripts/swift-linux.sh test",
        "make verify-all"
      ],
      "acceptance": [
        "the requirement-coverage gate passes for FR-001 ... FR-052 and SC-001 ... SC-007 except FR-022, FR-023 and FR-049, which the owner deferred with the navigator clients (decision 2026-10-07; /speckit-accept records them as deferred by scope)",
        "gate-integrity manifest re-recorded in the same commit as the Makefile change; invariants intact",
        "owner's recorded ASK approval and rollout decisions in specs/020-weekly-review/evidence/rollout-decisions.md",
        "independent /speckit-accept verdict before any flag stage beyond the owner",
        "landing class ASK (scripts/classify_path_risk.py: ASK)"
      ]
    }
  ]
}
```
