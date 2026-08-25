# Tasks: Web Task Title Autocomplete

**Input**: [spec.md](spec.md), [design.md](design.md), [plan.md](plan.md), [research.md](research.md), [contract](contracts/title-completions.md), [ADR-0021](../../docs/decisions/0021-runtime-managed-task-title-autocomplete.md)

This trace records the original local implementation plus the blocker-only replacement authored from authoritative `origin/main` in isolated worktree `t_c0522f2b`. The replacement is one direct-child candidate commit containing the complete Spec 012 slice and seven independently reproduced repairs. The writer recorded focused RED before each repair GREEN; no live/paid provider call, push, merge, deploy, runtime-flag mutation, or production mutation is part of this trace. Exact final-SHA review, QA, CI, approval, landing, rollout, and production evidence remain external gates rather than checked implementation claims.

## Phase 1 — Flag and configuration foundation

- [x] **T001 RED** Extend `backend/tests/test_feature_flags.py`, `test_feature_flag_repository.py`, `test_feature_flag_service.py`, `test_auth_routes.py`, and `test_admin_feature_flags_api.py` to require the fourth `task_title_autocomplete` row/key: fresh OFF, post-marker OFF insertion, no legacy seed, exact-row degradation, selected-user purge, `/auth/me` projection, Admin description/mutation. *(012-FR-009, 012-SC-002, 012-SC-006)*
- [x] **T002 GREEN** Update `backend/app/core/config.py`, `backend/app/repositories/feature_flag.py`, and only the generic projection/Admin labels that T001 proves necessary; keep SQLite sole authority and update stale “three flags” comments. *(012-FR-009, 012-FR-014)*
- [x] **T003 RED** Add configuration/provider-construction cases in `backend/tests/test_title_completion_provider.py`: disabled default, supported OpenAI, unsupported value, missing key, fixed official API origin/no arbitrary endpoint, model/token/history bounds, 3-second timeout, no retry, body-safe errors. *(012-FR-007, 012-FR-010, 012-FR-011)*
- [x] **T004 GREEN** Add `TaskTitleAutocompleteSettings` and `BRAIN_BUDDY_TASK_TITLE_AUTOCOMPLETE_*` parsing to `backend/app/core/config.py`, document disabled defaults in `.env.example`, and wire disabled/real adapters in `backend/app/container.py`. *(012-FR-007, 012-FR-010)*

**Checkpoint**: focused flag/config tests pass; repository has four healthy rows and provider remains disabled without explicit configuration.

## Phase 2 — Owner-scoped completion service and provider

- [x] **T005 RED** Create `backend/tests/test_task_title_autocomplete_service.py` for Unicode thresholds, request-scoped consent/provider match, active same-owner Project, absent/inactive/other-owner rejection, history lifecycle inclusion, Project-first/updated-desc order, normalization/dedup/50 cap, exclusion of details and other-owner data, no repository write. *(012-FR-002, 012-FR-006, 012-FR-007, 012-SC-002)*
- [x] **T006 RED** Extend `backend/tests/test_title_completion_provider.py` with strict JSON exactly-three behavior, normalized uniqueness, full-title prefix extension, length/line validation, completed Smart Add token rejection, malformed/fewer-than-three failure, and OpenAI usage-token extraction without content. *(012-FR-008, 012-FR-011)*
- [x] **T007 GREEN** Create immutable types, `TaskTitleCompletionPort`, and `TaskTitleAutocompleteService` in `backend/app/modules/tasks/autocomplete.py`; use `TaskRepository.list_for_owner` or add only a bounded read projection in `repository.py` if tests demonstrate need. *(012-FR-002, 012-FR-006, 012-FR-007, 012-FR-008)*
- [x] **T008 GREEN** Create disabled, deterministic-test, and OpenAI-compatible adapters in `backend/app/ai/title_completion.py` using existing `httpx`; strict JSON, 120 output-token cap, 3-second timeout, no retry, safe error bands, no content logs. *(012-FR-008, 012-FR-010, 012-FR-011)*

**Checkpoint**: `pytest tests/test_task_title_autocomplete_service.py tests/test_title_completion_provider.py`; provider spies prove no call before every gate and no persistence.

## Phase 3 — Authenticated API, limits, and observations

- [x] **T009 RED** Create `backend/tests/test_task_title_autocomplete_api.py` for discovery/generation/acceptance contracts, static-route precedence over `GET /tasks/{task_id}`, 401→404 precedence, OFF/degraded/provider/consent/Project failures before egress, 400/404/422/503 mapping, exact response, correlation ID, and zero Task writes. *(012-FR-001, 012-FR-004, 012-FR-007, 012-FR-008, 012-FR-012, 012-SC-001, 012-SC-002)*
- [x] **T010 RED** Add API cases for requests 1–20 and request 21 returning 429 + `Retry-After`; add captured-log canaries proving draft/provider-body content is absent on failure and that available input/output token counts are emitted without draft/candidate content on success. *(012-FR-010, 012-FR-011)*
- [x] **T011 GREEN** Add strict request/response models to `backend/app/schemas/tasks.py`, a dedicated owner limiter in `backend/app/core/rate_limit.py`, and provider discovery/generation/acceptance routes in `backend/app/api/tasks.py`; inject through existing dependencies/container. *(012-FR-007…012)*
- [x] **T012 GREEN** Emit content-free generation outcome/duration/token observations and acceptance `request_id`/rank only; sanitize provider exceptions and ensure acceptance returns 204 without Task/repository mutation. These observations must support the valid-set/latency and acceptance pilot measures without Task text. *(012-FR-011, 012-FR-012, 012-SC-004, 012-SC-005)*

**Checkpoint**: focused API tests pass, including repository/provider spies and privacy canaries.

## Phase 4 — Web debounce, cancellation, and listbox

- [x] **T013 RED** Create `frontend/src/features/tasks/__tests__/useTaskTitleAutocomplete.test.tsx` with fake timers for flag/provider/consent gates, three-word/Project-one-word thresholds, 349/350 ms boundary, unmount and superseding-draft cancellation, stale resolve/reject suppression, dismissal reset after draft/context change, discovery/generation correlation references, trimmed-length eligibility, safe failures, and best-effort acceptance observation. *(012-FR-002, 012-FR-003, 012-FR-007, 012-FR-010, 012-FR-012)*
- [x] **T014 GREEN** Add API types/client methods with `AbortSignal` in `frontend/src/api/taskTypes.ts` and `frontend/src/api/client.ts`, then create `useTaskTitleAutocomplete.ts` to satisfy T013 without caching/persisting prompt or candidates. *(012-FR-003, 012-FR-006, 012-FR-007, 012-FR-012)*
- [x] **T015 RED** Create `frontend/src/features/tasks/__tests__/TaskTitleAutocompleteSuggestions.test.tsx` for exactly three options, first active, wrapped arrows, Enter draft-only + preventDefault, Escape unchanged, mouse/focus parity, Tab non-acceptance, ARIA/live status, unavailable states, and no callback that can submit. *(012-FR-001, 012-FR-004, 012-SC-001, 012-SC-003)*
- [x] **T016 GREEN** Create `TaskTitleAutocompleteSuggestions.tsx` implementing design A-02…A-10 with compact two-line options and no ghost text/second editor. *(012-FR-001, 012-FR-004)*

**Checkpoint**: focused hook/component Vitest passes with fake clock and abort assertions.

## Phase 5 — Existing composer integration and Smart Add coexistence

- [x] **T017 RED** Extend `frontend/src/features/tasks/__tests__/TaskListPage.test.tsx` for provider consent, exactly three options, acceptance changing only the input, no Task/Smart Add write before acceptance, subsequent ordinary submit, wrapped keyboard navigation, Escape dismissal, and content-free acceptance observation. *(012-FR-001, 012-FR-004, 012-FR-005, 012-SC-001, 012-SC-003)*
- [x] **T018 RED** Add explicit Smart Add arbitration evidence: a completed Smart Add token suppresses autocomplete after the caret-local popup closes; backend candidate validation rejects generated completed `#`/`@` tokens; existing Smart Add parsing/submission tests remain green. *(012-FR-005, 012-FR-008, 012-FR-013)*
- [x] **T019 GREEN** Integrate the hook/component only into `TaskCreator` in `frontend/src/features/tasks/TaskListPage.tsx`; preserve the input, parser, `onCreate`, waiting/context payloads, and ordinary form submit. Apply the arbitration order from `plan.md`. *(012-FR-001, 012-FR-004, 012-FR-005, 012-FR-013)*
- [x] **T020 GREEN** Update `frontend/src/api/__tests__/client.test.ts` for paths, payloads, status, and AbortSignal; update Admin Feature Flags label/test only if its current generic rendering does not display the fourth row. *(012-FR-009, 012-FR-012)*
- [x] **T020A RED→GREEN** Update `frontend/src/pages/PrivacyPolicyPage.tsx` and `frontend/src/pages/__tests__/PrivacyPolicyPage.test.tsx` to name OpenAI's title-suggestion purpose and the current draft, selected Project name, and bounded prior-title inputs; preserve the current provider-retention wording and make no new retention claim. *(012-FR-007, 012-FR-011)*

**Checkpoint**: focused frontend tests pass and network-call assertions prove candidate acceptance never creates.

## Phase 6 — Integrated evidence and delivery gate

- [x] **T021 RED→GREEN** Extend `frontend/tests/native-tasks-voice-brain-dump.compose.spec.ts` with a deterministic, non-live provider journey at 390×851 and 1280×780: A-01 OFF, A-03 consent, A-07 exact menu, A-08 no-write acceptance then separate submit, A-11 Smart Add ownership, A-10 unavailable, A-01 runtime OFF rollback leaving Task/draft untouched. Preserve existing Voice/Task journeys. *(012-SC-001, 012-SC-003, 012-SC-006)*
- [ ] **T022 FINAL-SHA GATES PENDING** Run the clean installs and canonical backend/frontend/spec/mobile/Playwright commands on the immutable replacement SHA. Record failures, skips, advisories, and environment blocks without converting them to passing claims. *(all requirements)*
- [ ] **T023 FINAL INSPECTION PENDING** Inspect the base-to-final diff for forbidden mobile/voice/Task-domain/schema/deploy-workflow changes, content-bearing observations, live provider calls, new persistence, stacked menus, pre-submit writes, and deleted base paths. Classify the final diff ASK/high and record exact commands/results. *(012-FR-006, 012-FR-011, 012-FR-013, 012-FR-014)*
- [ ] **T024 HANDOFF PENDING** The bounded candidate series is committed on the recorded authoritative `origin/main` base. This item remains open until the implementation card hands off exact final/base SHAs, changed files, RED→GREEN evidence, test output, supported/non-supported behavior, risks, and explicit no-push/no-merge/no-deploy/no-flag-mutation status to independent review/QA. *(012-SC-001…006)*

## Dependency Order

T001→T002; T003→T004; Phase 1 blocks service/API. T005/T006 precede T007/T008. T009/T010 precede T011/T012. T013→T014 and T015→T016 may proceed after client contract, then T017/T018→T019/T020. Integrated evidence waits for all GREEN work. One writer sequences shared files; `[P]` parallel markers are intentionally omitted to avoid collisions in `config.py`, `tasks.py`, `TaskListPage.tsx`, and shared tests.

## Definition of implementation complete

Implementation handoff requires T022–T024 to be evidenced on one immutable SHA. Independent review/QA must then evaluate that exact SHA, and the human owner retains ASK landing and runtime rollout authority. A green local implementation does not itself authorize provider credentials, INTERNAL/ON rollout, merge, deploy, or release.
