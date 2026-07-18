# Implementation Plan: Smart Add task classification

**Branch**: `wt/t_fe52d630` | **Date**: 2026-07-18 | **Spec**: `specs/003-smart-add-classification/spec.md`
**Input**: Feature specification and normative contract under `specs/003-smart-add-classification/`

## Summary

Add RTM-style `#tag` and `@project` classification to the existing desktop/web task title
input. Keep suggestions and syntax parsing in the browser, preserve literal title APIs, and
submit classified tasks through one new Tasks-module atomic resolve-or-create command.
Render task classification as `#tag` and `@project` while retaining current post-create
Project/Tag controls and the established Claude/Cloud Design shell.

## Technical Context

**Language/Version**: Python 3.11; TypeScript strict + React 18
**Primary Dependencies**: FastAPI, Pydantic, SQLite repository, pytest/TestClient; React,
React Query, Vite, Vitest/Testing Library, Playwright
**Storage**: Existing Tasks-module SQLite database plus compatibility JSON sidecars; no new
store or schema-owned entity
**Testing**: Focused parser Vitest, frontend route/component tests, backend service/API
pytest, Compose Playwright desktop E2E, existing build/spec checks
**Target Platform**: Existing responsive web app; feature interaction scope is desktop/web
**Project Type**: FastAPI + React modular monolith
**Performance Goals**: Suggestion filtering is synchronous over loaded Project/Tag arrays
and remains perceptually immediate; no request per keystroke
**Constraints**: Preserve plain-title behavior, owner isolation, correlation IDs, one
Project maximum, multiple distinct Tags, command idempotency/atomicity, current Waiting and
contextual-create rules, established shell layout
**Scale/Scope**: Complete active Project/Tag lists already loaded by the shell; maximum eight
visible suggestions; names and clean title retain existing 500-character limits

## Constitution Check

*GATE: Passed before design and re-checked after contract definition.*

- **Consent & Safety**: No remote AI, voice, media, or new logging. Unknown classification
  creation happens only on explicit Task submit and is atomic with Task creation.
- **Tested Delivery**: Parser, backend compound command, frontend integration, accessibility,
  rendering, and desktop E2E each have failing-first tasks. Plain title and Voice Brain Dump
  remain regression gates.
- **Contract First**: ADR-0007 and `contracts/smart-add.md` define grammar, request/response,
  normalization, atomicity, compatibility, and error behavior before implementation.
- **Observability**: Existing error envelope and `X-Correlation-ID` remain; no raw title or
  classification names enter logs/metrics.
- **Responsive/Mobile**: The feature does not redesign mobile. It changes the existing
  responsive input only by anchoring a popup; desktop screenshots and overflow checks guard
  the shared shell. Voice capture is unaffected.
- **Complexity**: One compound endpoint is justified to avoid partial durable side effects.
  No new module, service, database, broker, or contenteditable composer is introduced.

## Architecture

### 1. Browser parser and draft projection

Create a pure utility at `frontend/src/features/tasks/smartAdd.ts` with no React or API
imports. It returns ordered token spans, active token at a caret, cleaned title, contextual
classification projection, and ranked suggestions. Export types used by the composer and
its tests. The normative behavior is `contracts/smart-add.md`; keep one table-driven fixture
set for grammar cases so cleanup and replacement cannot drift across handlers.

The utility performs no durable action. Existing/unknown is determined from the active
Project/Tag arrays supplied by the caller. A selected multi-word suggestion rewrites the
plain input to canonical quoted syntax, preserving the single existing `<input>`.

### 2. Suggestion popup inside the existing creator

Add `frontend/src/features/tasks/SmartAddSuggestions.tsx` as a small accessible listbox
anchored below the title input. Integrate it into `TaskCreator` in
`frontend/src/features/tasks/TaskListPage.tsx`; do not introduce another page, modal,
contenteditable, or mobile layout.

`TaskCreator` owns caret tracking and highlighted option state. Parser output drives the
popup and submit button. Keyboard behavior follows the contract. An empty cleaned title is
an inline validation state and cannot call the backend.

### 3. Explicit compound API

Add strict `SmartAddClassificationRef`, `SmartAddTaskCreateRequest`,
`SmartAddCreatedResources`, and `SmartAddTaskResponse` schemas in
`backend/app/schemas/tasks.py` and corresponding TypeScript types in
`frontend/src/api/taskTypes.ts`.

Add `POST /tasks/smart-add` to `backend/app/api/tasks.py` and
`apiClient.smartAddTask(...)` to `frontend/src/api/client.ts`. Keep existing `POST /tasks`
and all task update contracts unchanged. The route uses the standard session dependency,
required `Idempotency-Key`, error mapping, and correlation middleware.

### 4. Atomic resolve-or-create service command

Add `TaskService.smart_add_task(...)` under the existing `_serialized_write` boundary.
Refactor only the minimum internal Project/Tag/Task construction helpers needed to avoid
calling decorated public commands recursively. Resolution order:

1. validate request and contextual ID refs;
2. resolve Project ID/name and ordered Tag ID/name refs to same-owner active records;
3. create missing active normalized names;
4. deduplicate resolved Tags in request order;
5. create the Task using existing active-reference, state, Waiting, order, and title rules;
6. save one composite idempotency response and return complete projections.

Add repository lookup methods for active normalized Project/Tag names rather than teaching
HTTP routes about normalization. Keep normalization in
`backend/app/modules/tasks/repository.py` and reuse the current helpers.

Extend `_apply_idempotent_record` with a `smart_add_task` composite repair path. The
composite result must reconcile the Task and all returned Project/Tag sidecars if a stored
idempotency result exists. Do not weaken same-key/different-body conflicts.

### 5. Frontend submission and cache behavior

In `TaskListPage.tsx`, preserve the existing `createMutation` path when the parser finds no
completed classification token. Add a classified mutation that sends:

- the cleaned title and current state/Waiting fields;
- the active Project/Tag contextual defaults as ID refs;
- only the final inline Project ref;
- distinct ordered inline Tag refs.

On success clear the title/Waiting draft and invalidate `taskKeys.all`, including list,
detail, Project, and Tag queries. On failure preserve the raw input and existing mutation
error surface. Do not optimistically add a Project/Tag before the compound response.

### 6. Rendering and compatibility

Update task-row classification rendering in `TaskListPage.tsx`:

- Tag chips/removal labels use `#tag`;
- render the assigned Project as `@project` using its existing ID;
- existing Project select, Add Tag select, removal behavior, and detail controls remain
  available and keep ID-based `PATCH /tasks/{id}` behavior.

Update Tag presentation in `TaskListPage.tsx` and `AppShell.tsx` from historical `@tag` to
`#tag`, including Tag view headings/options/checkboxes. Project navigation headings remain
ordinary names. Use one small presentation helper to strip one legacy leading `@`/`#`
before adding the required sigil.

Row and detail title edit remain literal. Voice Brain Dump remains on its current explicit
confirmation and literal Task-create path.

## Data and API Contracts

No canonical entity or database table is added. The only new durable behavior is a compound
command over existing Project, Tag, Task, and Idempotency records.

Normative request/response, status, normalization, transaction, grammar, cleanup, and
rendering rules live in:

- `specs/003-smart-add-classification/contracts/smart-add.md`
- `docs/decisions/0007-smart-add-is-an-explicit-atomic-task-command.md`

The endpoint response embeds complete existing `TaskResponse`, optional `ProjectResponse`,
ordered `TagResponse[]`, and created IDs. This lets clients invalidate/refetch while still
making the exact composite result auditable and idempotently replayable.

## Affected Files

### Create

- `frontend/src/features/tasks/smartAdd.ts`
- `frontend/src/features/tasks/__tests__/smartAdd.test.ts`
- `frontend/src/features/tasks/SmartAddSuggestions.tsx`
- `frontend/src/features/tasks/__tests__/SmartAddSuggestions.test.tsx`

### Modify

- `frontend/src/features/tasks/TaskListPage.tsx`
- `frontend/src/components/shell/AppShell.tsx`
- `frontend/src/api/taskTypes.ts`
- `frontend/src/api/client.ts`
- `frontend/src/api/__tests__/client.test.ts`
- `frontend/src/app/AppRoutes.test.tsx`
- `frontend/tests/native-tasks-voice-brain-dump.compose.spec.ts`
- `frontend/tests/claude-design-shell.spec.ts` and its desktop screenshot only if the popup
  or chip correction legitimately changes the source-faithful frame
- `backend/app/schemas/tasks.py`
- `backend/app/api/tasks.py`
- `backend/app/modules/tasks/service.py`
- `backend/app/modules/tasks/repository.py`
- `backend/tests/test_task_api.py` or a focused `backend/tests/test_task_smart_add_api.py`
- `backend/tests/allure_taxonomy.py` if a new backend test module is created

No other module, voice contract, CRT schema, route family, or persistence owner should
change.

## Test Strategy

### Parser unit tests

Use table-driven Vitest cases for every recognition/cleanup example in the contract plus:
Unicode NFKC/casing, multi-word quoting/escapes, punctuation boundaries, bare/unclosed
forms, escaped literals, duplicate Tags, last Project wins, contextual defaults, wrappers,
empty clean title, caret-local active token, ranking, and deterministic limit.

### Component and route tests

Testing Library verifies listbox ARIA, correct entity type, keyboard/mouse acceptance,
direct submit, draft preservation on error, no-token literal `createTask`, classified
`smartAddTask`, Waiting/context payload composition, cache invalidation, and `#tag`/
`@project` display while current selects still work.

### Backend service/API tests

Pytest/TestClient verifies:

- strict reference XOR and existing request invariants;
- existing-ID and normalized-name resolution;
- missing-name creation and ordered deduplication;
- same key replay and key/body conflict;
- wrong-owner/inactive IDs;
- archived/deleted same-name behavior;
- one Project and many Tags;
- atomic rollback when a later Task write is forced to fail;
- composite idempotency repair;
- literal `POST /tasks` titles remain unchanged.

### Browser/integration regression

Compose Playwright verifies existing partial suggestions, unknown creation, multiple Tags,
second Project replacement, contextual Tag/Project views, clean persisted title, keyboard
and mouse flows, reload/relogin, and ordinary email/C#/escaped titles. Existing Voice Brain
Dump exact-one-task behavior remains green. Run the desktop visual shell test at 1280x780;
do not refresh snapshots for unrelated drift.

## Verification Commands

```bash
python3 scripts/check_spec_kit_specs.py
(cd backend && uv run pytest tests/test_task_smart_add_api.py -q)
(cd frontend && npm test -- src/features/tasks/__tests__/smartAdd.test.ts src/features/tasks/__tests__/SmartAddSuggestions.test.tsx src/app/AppRoutes.test.tsx)
(cd frontend && npm run build)
make test-backend
make test-frontend
./scripts/run_playwright_e2e.sh tests/native-tasks-voice-brain-dump.compose.spec.ts
```

If the backend implementation adds cases to an existing test module, use that exact path
instead of the proposed new file. Full CI and review-app checks remain the PR merge gate.

## Release and Rollback

This is a backward-compatible additive API and frontend affordance. No data migration is
required. Rollback removes the Smart Add frontend call and endpoint; already created normal
Project/Tag/Task records remain valid. Release through the normal PR -> CI -> main -> Fly
path. Production smoke must include literal Task create and classified Task create under an
authenticated test owner without logging user-entered text.

## Complexity Tracking

| Complexity | Why needed | Simpler alternative rejected because |
|---|---|---|
| Compound Smart Add endpoint and composite idempotency result | One submit may create Project, Tags, and Task | Client choreography permits partial durable side effects and fragmented retry |
| Quoted token form | Existing Projects can contain spaces and punctuation | Unquoted-only syntax cannot select canonical existing multi-word names |

No constitution waiver is required.
