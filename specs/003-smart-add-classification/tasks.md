# Tasks: Smart Add task classification

**Input**: `specs/003-smart-add-classification/spec.md`, `plan.md`, `research.md`, and
`contracts/smart-add.md`
**Tests**: Required and written failing-first for every behavior slice.
**Execution**: Hermes Kanban owns implementation/review; this file is planning input only.

## Phase 1: Contract and parser foundation

- [ ] T001 [P] Add table-driven failing grammar/cleanup fixtures in
  `frontend/src/features/tasks/__tests__/smartAdd.test.ts` for every contract example,
  escaped/incomplete forms, punctuation, wrappers, duplicates, contextual defaults, and
  last-Project-wins.
- [ ] T002 Implement the pure parser, cleaner, classification merge, canonical serializer,
  active-token lookup, and suggestion ranking in `frontend/src/features/tasks/smartAdd.ts`.
- [ ] T003 Run the focused parser tests and verify all fixtures pass without React or API
  dependencies.

**Checkpoint**: Raw text deterministically produces clean title, ordered Tags, and final
Project with no durable side effect.

## Phase 2: Atomic backend command

- [ ] T004 [P] Add failing schema/API tests for strict classification-ref XOR, existing ID,
  existing normalized name, unknown creation, duplicate Tags, wrong owner/inactive refs,
  Waiting validation, and literal `POST /tasks` compatibility in
  `backend/tests/test_task_smart_add_api.py` (or the existing task API module).
- [ ] T005 [P] Add failing service/repository tests for atomic rollback, archived/deleted
  same-name behavior, same-key replay, key/body conflict, and composite result repair.
- [ ] T006 Add Smart Add request/response schemas in `backend/app/schemas/tasks.py`.
- [ ] T007 Add active normalized-name lookup methods to
  `backend/app/modules/tasks/repository.py`, reusing existing normalization helpers.
- [ ] T008 Implement `TaskService.smart_add_task` and minimal private constructors/resolvers
  in `backend/app/modules/tasks/service.py` under one serialized transaction.
- [ ] T009 Extend idempotency request hashing/reconciliation for the composite Smart Add
  result in `backend/app/modules/tasks/service.py`.
- [ ] T010 Add authenticated `POST /tasks/smart-add` with existing error/correlation handling
  in `backend/app/api/tasks.py`.
- [ ] T011 Register any new backend test module in `backend/tests/allure_taxonomy.py`, then run
  the focused backend tests.

**Checkpoint**: One idempotent API call resolves/creates classifications and Task atomically;
existing literal APIs are unchanged.

## Phase 3: Accessible suggestions in the existing composer

- [ ] T012 [P] Add failing API client tests for the Smart Add request/response and required
  idempotency key in `frontend/src/api/__tests__/client.test.ts`.
- [ ] T013 Add Smart Add TypeScript contracts in `frontend/src/api/taskTypes.ts` and
  `apiClient.smartAddTask` in `frontend/src/api/client.ts`.
- [ ] T014 [P] Add failing listbox tests for Tag/Project filtering, ranking, max-eight,
  ArrowUp/ArrowDown, Enter/Tab, Escape, Ctrl/Cmd+Enter, mouse selection, and ARIA wiring in
  `frontend/src/features/tasks/__tests__/SmartAddSuggestions.test.tsx`.
- [ ] T015 Implement `frontend/src/features/tasks/SmartAddSuggestions.tsx` as an anchored
  accessible listbox with no network behavior.
- [ ] T016 Integrate caret tracking, parser output, canonical suggestion replacement, inline
  empty-title validation, and keyboard submission into the existing `TaskCreator` in
  `frontend/src/features/tasks/TaskListPage.tsx`.

**Checkpoint**: Existing input supports discoverable keyboard/mouse suggestions without a
new composer or durable action while typing.

## Phase 4: Classified submit and compatibility

- [ ] T017 [P] Add failing route tests in `frontend/src/app/AppRoutes.test.tsx` for existing
  selection, unknown references, contextual Project/Tag composition, duplicate Tags,
  repeated Project replacement, clean title, draft preservation on failure, and no-token
  literal create.
- [ ] T018 Route completed-token submissions through `smartAddTask` and no-token submissions
  through existing `createTask` in `frontend/src/features/tasks/TaskListPage.tsx`; invalidate
  the complete Tasks query root after success.
- [ ] T019 Keep row/detail title edits literal and verify current Project/Tag assignment
  selects/checkboxes still send ID-based task patches.
- [ ] T020 Add regression cases for email, `C#`, escaped sigils, bare sigils, unclosed quotes,
  Waiting requirements, and Project/Tag view defaults.

**Checkpoint**: Smart Add is opt-in by completed syntax; existing capture/edit flows retain
literal behavior.

## Phase 5: Classification rendering

- [ ] T021 [P] Add failing rendering assertions for `#tag`, `@project`, legacy-prefix
  stripping, Tag view headings/options, and truthful chips in
  `frontend/src/app/AppRoutes.test.tsx`.
- [ ] T022 Add one shared presentation helper and update task row/detail Tag rendering in
  `frontend/src/features/tasks/TaskListPage.tsx` plus Tag navigation in
  `frontend/src/components/shell/AppShell.tsx`.
- [ ] T023 Render assigned Project as `@project` on the Task row without removing the current
  post-create Project select; keep Project navigation headings unprefixed.
- [ ] T024 Run focused frontend tests and update only intentional Claude Design desktop
  screenshot expectations.

**Checkpoint**: Persisted stable IDs render with the new `#tag`/`@project` classification
language while existing controls remain wired.

## Phase 6: End-to-end and release gates

- [ ] T025 Add Compose Playwright coverage in
  `frontend/tests/native-tasks-voice-brain-dump.compose.spec.ts` for partial suggestion,
  unknown creation, many Tags, second Project replacement, clean persistence, keyboard and
  mouse, contextual views, reload/relogin, and literal-title regressions.
- [ ] T026 Run `python3 scripts/check_spec_kit_specs.py` and the focused backend/frontend
  suites from `plan.md`.
- [ ] T027 Run full `make test-backend`, `make test-frontend`, frontend build, and relevant
  Compose Playwright tests; preserve existing Voice Brain Dump exact-task evidence.
- [ ] T028 Inspect changed-file scope, request independent review, and deliver through the
  repository PR -> CI -> main -> automatic Fly path.

## Dependencies and parallel work

- T001 blocks T002/T003 and frontend integration behavior.
- T004/T005 may run in parallel with T001-T003; they block T006-T011.
- T012-T015 may run after the API contract is fixed and in parallel with backend internals.
- T016-T020 require parser and client contracts.
- T021-T024 may begin after fixture responses include both Project and Tags.
- T025 requires the complete backend/frontend slice; T026-T028 are final gates.

## Implementation guardrails

- Do not parse Smart Add syntax in existing `POST /tasks`, PATCH, title edit, Voice Brain
  Dump, import, or CRT paths.
- Do not create a Project/Tag on suggestion selection or any event before Task submit.
- Do not create superseded Project candidates.
- Do not remove current post-create Project/Tag controls in this slice.
- Do not add a rich/contenteditable composer, remote fuzzy search, mobile redesign, or AI
  classifier.
- Do not refresh visual baselines to hide unrelated regressions.
