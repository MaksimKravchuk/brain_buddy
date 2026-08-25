# Implementation Plan: Web Task Title Autocomplete

**Branch**: `wt/t_6fca39aa` | **Date**: 2026-08-25
**Spec**: [spec.md](spec.md) · **Design**: [design.md](design.md) · **Contract**: [contracts/title-completions.md](contracts/title-completions.md)

## Summary

Add a web-only, default-OFF AI completion experiment to the existing new-Task input. The browser owns debounce, cancellation, stale-response rejection, Smart Add coexistence, and the three-option listbox. An authenticated Tasks API owns flag/consent/provider gates, owner-scoped bounded context assembly, rate limiting, provider validation, privacy-safe observations, and safe unavailable errors. No Task or suggestion data is written before normal Task submit.

**Implementation risk: ASK/high.** The eventual code changes authenticated Tasks routing (`backend/app/api/tasks.py`, an explicit ASK path), remote owner-content egress, provider configuration, and the runtime flag persistence set. ADR-0008 requires explicit recorded approval and green exact-SHA CI; it never auto-lands. This planning-only commit does not mutate runtime flags or production.

## Technical Context

**Language/Version**: Python 3.11; TypeScript strict + React 18

**Primary Dependencies**: Existing FastAPI/Pydantic/httpx/SQLite/pytest; React/TanStack Query/Vitest/Testing Library/Playwright. No new package.

**Storage**: Existing Tasks SQLite is read-only for context; existing feature-flags SQLite gains one OFF rollout row. No autocomplete/memory/result/consent store.

**Testing**: pytest/FastAPI TestClient with deterministic provider spies; Vitest/Testing Library fake timers and abort signals; Playwright web journey; existing Smart Add, auth, runtime-flag, Task, and voice regressions.

**Target Platform**: Responsive web shell and Linux backend only. No mobile source change.

**Performance Goals**: 350 ms client debounce; one current request; 3-second provider timeout/no retry; 20 owner requests/60 s; internal-pilot p95 successful response ≤2.5 s.

**Constraints**: Exactly three full titles or none; current consent; same-owner bounded history; no task text in observations; acceptance cannot submit; OFF rollback leaves Tasks and drafts untouched.

**Scale/Scope**: One configured provider category in v0; maximum 50 distinct prior titles; maximum 500 characters per draft/candidate; three options.

## Constitution Check

- **Spec workflow**: `intake.md`, `spec.md`, `design.md`, this plan, contract, checklist, and tasks form ordinary portable Spec Kit artifacts. No managed-outcome overlay is active.
- **Consent & Safety**: Discovery names the actual provider before a session-local unchecked consent control appears. Backend rechecks provider, consent, flag, owner, Project, and rate before egress. No text-bearing logs, caches, fixtures, or evidence.
- **Tests**: Every implementation lane is RED→GREEN. Failure tests include consent, credentials, owner isolation, flag degradation/OFF, timeout, 429, abort, stale response, malformed output, Smart Add ownership, and zero pre-submit writes.
- **Contracts**: Backend schemas precede frontend types. `contracts/title-completions.md` is normative; existing Task/Smart Add endpoints remain unchanged.
- **Observability**: Existing correlation middleware/error envelope stays. Only content-free request outcome/duration/token counts and acceptance request ID/rank are observed.
- **Mobile/resilience/performance**: No mobile code. Responsive web states A-01…A-12 are tested at 390×851/1280×780. Provider failure never blocks ordinary capture.
- **Delivery boundary**: Implementation is ASK/high and requires isolated worktree, one writer, TDD, independent exact-SHA review/QA, CI, explicit owner approval, and ADR-0008 landing. No push/merge/deploy/flag mutation is authorized by these artifacts.
- **Design citation**: UI work implements [design.md](design.md) states A-01…A-12; tests grade each state and keyboard owner.

No constitution waiver is required.

## Architecture

### 1. Runtime exposure and provider capability

Update `backend/app/core/config.py` and `backend/app/repositories/feature_flag.py` per ADR-0021. `task_title_autocomplete` joins the known/runtime-managed sets. Fresh or existing post-marker stores initialize its missing row OFF without consulting legacy JSON. `FeatureFlagService.effective_flags` naturally projects the fourth row; update exact-key/count tests and the existing generic Admin Feature Flags section/labels as needed.

Add frozen `TaskTitleAutocompleteSettings` to `AppConfig`: provider (`disabled|openai`, default `disabled`), model (default `gpt-4o-mini`), API-key environment variable name, timeout fixed/default 3 seconds, max history 50, and max output tokens 120. The adapter uses the fixed official OpenAI API origin; v0 exposes no arbitrary endpoint. `_build_config` reads `BRAIN_BUDDY_TASK_TITLE_AUTOCOMPLETE_*`; `.env.example` documents disabled defaults without credentials. Provider construction checks supported category and key presence once and returns a disabled capability otherwise. Runtime rollout and provider capability remain separate AND gates.

### 2. Narrow provider port and adapter

Create `backend/app/modules/tasks/autocomplete.py` with immutable context/result types, a `TaskTitleCompletionPort`, and `TaskTitleAutocompleteService`. Create `backend/app/ai/title_completion.py` with disabled, deterministic-test, and OpenAI-compatible adapters using existing `httpx`; do not coerce validation or Voice result types.

The service validates consent/provider/threshold, verifies same-owner active Project, reads `TaskRepository.list_for_owner`, deduplicates titles, sorts selected-Project matches first then `updated_at` descending, caps at 50, and calls the provider. Provider output is strict JSON and passes every candidate invariant before response. Prompt/output live only in local variables. No retry/cache/persistence.

### 3. Authenticated API and bounded rate

Extend strict schemas in `backend/app/schemas/tasks.py`. Add provider discovery, generation, and acceptance-observation routes to `backend/app/api/tasks.py`; register the static `/tasks/title-*` routes before the existing dynamic `GET /tasks/{task_id}` route so FastAPI cannot consume `title-completion-provider` as a Task ID. Inject the autocomplete service and feature-flag service through existing dependency/container patterns. Generation uses a dedicated `InMemoryRateLimiter(max_attempts=20, window_seconds=60)` keyed by authenticated user ID and returns `Retry-After` on 429.

Route precedence: session → effective flag (404) → request validation/consent/provider capability → Project/owner context → rate check → remote call. This minimizes both information disclosure and unnecessary egress. Acceptance observation validates UUID/rank and emits one content-free record only; it never calls `TaskService.create_task` or a repository write.

Map provider disabled/timeout/transport/invalid output to generic 503 reason bands. Do not include exception strings from providers when they may contain response bodies. Logs contain correlation/request/owner IDs, provider category, outcome, duration/token counts/rank only.

### 4. Web interaction and Smart Add arbitration

Add typed contracts/client methods with `AbortSignal` in `frontend/src/api/taskTypes.ts` and `frontend/src/api/client.ts`. Create `frontend/src/features/tasks/useTaskTitleAutocomplete.ts` for pure eligibility, 350 ms timing, AbortController lifecycle, monotonic sequence/snapshot checks, consent/provider state, dismiss-until-change, and best-effort acceptance observation. Create `TaskTitleAutocompleteSuggestions.tsx` for A-02…A-10 accessible UI.

Integrate only at `TaskCreator` inside `TaskListPage.tsx`. Feed it the existing input, context Project ID, and `parseSmartAdd` state. Arbitration order:

1. active/open Smart Add owns keyboard and suppresses/cancels autocomplete (A-11);
2. otherwise open autocomplete owns Arrow/Enter/Escape (A-12);
3. otherwise the existing form owns ordinary submit.

Enter acceptance calls `preventDefault`, replaces the complete input, keeps focus, clears the menu, and asynchronously records rank. It never invokes `onCreate`. Tab does not accept. A second Enter after closure is ordinary existing submit. Flag OFF renders no new surface and performs no discovery.

### 5. Cancellation and stale safety

Every eligible draft/Project snapshot gets a client sequence. New input clears options synchronously, cancels debounce/fetch, increments sequence, then schedules 350 ms. Render only when sequence, draft, Project, consent, provider, flag, and Smart Add ownership still match. Consent withdrawal/provider/flag change/unmount aborts and clears all ephemeral state. Server timeout/no retry bounds work that outlives a best-effort browser abort.

### 6. Rollout, success, and rollback

Implementation ships with the SQLite row OFF and provider disabled by default. No task text fixture or live provider call enters CI. Internal rollout requires configured credentials and existing Admin Feature Flags action; neither is part of implementation execution. Content-free outcome/latency/token/rank observations support SC-004/005. Stop triggers from `spec.md` require flag OFF; code rollback is secondary and never rewrites Tasks.

## Affected Files

### Create

- `backend/app/modules/tasks/autocomplete.py`
- `backend/app/ai/title_completion.py`
- `backend/tests/test_task_title_autocomplete_service.py`
- `backend/tests/test_task_title_autocomplete_api.py`
- `backend/tests/test_title_completion_provider.py`
- `frontend/src/features/tasks/useTaskTitleAutocomplete.ts`
- `frontend/src/features/tasks/TaskTitleAutocompleteSuggestions.tsx`
- `frontend/src/features/tasks/__tests__/useTaskTitleAutocomplete.test.tsx`
- `frontend/src/features/tasks/__tests__/TaskTitleAutocompleteSuggestions.test.tsx`

### Modify

- `backend/app/core/config.py`
- `backend/app/repositories/feature_flag.py`
- `backend/app/services/feature_flag_service.py` only if fourth-flag projection is not already generic
- `backend/app/schemas/tasks.py`
- `backend/app/api/tasks.py`
- `backend/app/api/dependencies.py` for service injection/gate only if the existing generic dependency cannot be reused
- `backend/app/container.py`
- `backend/app/modules/tasks/repository.py` only for a bounded owner-title projection if `list_for_owner` proves too broad; no schema change
- `backend/app/core/rate_limit.py`
- `backend/tests/test_feature_flags.py`
- `backend/tests/test_feature_flag_repository.py`
- `backend/tests/test_feature_flag_service.py`
- `backend/tests/test_admin_feature_flags_api.py`
- `backend/tests/test_auth_routes.py`
- `backend/tests/allure_taxonomy.py` for new product-test modules
- `frontend/src/api/taskTypes.ts`
- `frontend/src/api/client.ts`
- `frontend/src/api/__tests__/client.test.ts`
- `frontend/src/features/tasks/TaskListPage.tsx`
- `frontend/src/app/AppRoutes.test.tsx`
- `frontend/src/features/admin/AdminFeatureFlagsSection.tsx` and test only if labels are not generic
- `frontend/src/pages/PrivacyPolicyPage.tsx` and `frontend/src/pages/__tests__/PrivacyPolicyPage.test.tsx` to disclose that consented title suggestions send the current draft, selected Project name, and bounded prior Task titles to OpenAI; no new retention claim beyond the existing provider disclosure
- `frontend/tests/native-tasks-voice-brain-dump.compose.spec.ts`
- `.env.example`

No mobile, Voice, Task domain/schema, Task storage migration, deployment workflow, or production setting changes are planned.

## Test Strategy

### Backend

- Flag/store tests: fourth OFF row on fresh and post-marker existing store; exact four-row health; no legacy seed; degraded missing/malformed row; selected-user purge; effective `/auth/me` key.
- Config/provider tests: disabled default, unsupported/missing-key disabled capability, fixed official OpenAI origin, strict payload/timeout/no retry, body-safe errors, token usage metadata, invalid JSON/schema/output.
- Service tests: thresholds/Unicode, Project ownership/activity, history scope/order/dedup/cap, no details/other-owner content, consent/provider mismatch, candidate invariants, no persistence.
- API tests: 401/404 precedence, flag OFF, 400/422, 20-per-60s 429 + Retry-After, 503 bands, correlation ID, content-free logs, acceptance 204/rank, repository/provider spies proving zero prohibited calls.

### Frontend

- Fake-timer hook tests for 350 ms, one request, abort triggers, sequence/snapshot stale drops, dismiss-until-change, consent lifecycle, safe failures, and best-effort metric.
- Component tests for exactly three options, ARIA, wrap, Enter draft-only, Escape, mouse, Tab, focus, no `onCreate`, unavailable states.
- `TaskListPage` integration tests for A-01…A-12, Project/unscoped thresholds, flag refresh OFF, Smart Add arbitration/no stacked listboxes, second-Enter ordinary submit, and no generated Smart Add tokens.
- Playwright at 390×851 and 1280×780 using deterministic backend provider; no live calls.

All product tests carry Allure epic/feature/story/title/step and requirement qualifiers `012-FR-###` / `012-SC-###`.

## Verification Commands

```text
make check-specs
cd backend && pytest tests/test_feature_flags.py tests/test_feature_flag_repository.py tests/test_feature_flag_service.py tests/test_task_title_autocomplete_service.py tests/test_task_title_autocomplete_api.py tests/test_title_completion_provider.py -q
cd frontend && npm test -- src/features/tasks/__tests__/useTaskTitleAutocomplete.test.tsx src/features/tasks/__tests__/TaskTitleAutocompleteSuggestions.test.tsx src/app/AppRoutes.test.tsx src/api/__tests__/client.test.ts
make lint-backend
make typecheck-frontend
make lint-frontend
make build-frontend
make test-backend
make test-frontend
./scripts/run_playwright_e2e.sh tests/native-tasks-voice-brain-dump.compose.spec.ts
python3 scripts/check_requirement_coverage.py specs/012-task-title-autocomplete
git diff --check
```

Do not omit requirement coverage. Full CI and independent exact-SHA review remain required.

## Risks and Unsupported Behavior

- Remote latency can make an interactive aid distracting; bounded timeout and stop bars contain it, but do not make network latency local.
- Browser abort cannot guarantee cancellation after provider acceptance; no retry and timeout bound residual cost.
- Owner title history is intentionally broad across lifecycle states but bounded to 50; semantic retrieval/embeddings are unsupported.
- In-memory rate limiting assumes the accepted single-process topology; multi-machine rollout requires a separate decision.
- Runtime-flag persistence and authenticated Tasks API make implementation ASK/high even though the feature starts OFF.
- Unsupported: mobile/voice/edit autocomplete, streaming, ghost text, suffix insertion, durable consent, result cache, local fallback, provider selector or arbitrary endpoint, history/memory entity, percent rollout, generated Smart Add tokens.

## Complexity Tracking

| Complexity | Why needed | Simpler alternative rejected because |
|---|---|---|
| Narrow title-completion provider port | Existing provider contracts return validation/voice-specific shapes | Coercion would couple Tasks to unrelated semantics and weaken strict output validation |
| Two read/generation routes plus content-free acceptance observation | Consent must name configured provider and the pilot needs privacy-safe usefulness evidence | Blind consent is invalid; logging titles is prohibited; no event would make SC-005 unmeasurable |
| Fourth SQLite-managed flag row | Fixed runtime-managed default-OFF rollback | Environment-only rollback requires a deploy and contradicts the frozen decision |
