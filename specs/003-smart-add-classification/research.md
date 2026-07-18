# Smart Add current-state research

Date: 2026-07-18

## Evidence inspected

### Desktop/web composer and persistence

- `frontend/src/features/tasks/TaskListPage.tsx:35-97` owns `newTitle`, contextual state,
  Waiting input, and the current create mutation.
- `TaskListPage.tsx:835-900` renders the single existing `<input>` composer, trims the title,
  and submits only a string. It has no classification popup or parser.
- Project view currently adds `project_id`; Tag view adds `tag_ids`; Waiting requires the
  separate `waiting_for` field (`TaskListPage.tsx:78-89,856-894`).
- `frontend/src/api/client.ts` already exposes literal `createTask`, Project/Tag list/create,
  and ID-based task update operations. Project/Tag mutations require idempotency keys.
- `frontend/src/api/taskHooks.ts:7-60` loads complete active Project and Tag arrays under the
  shared `tasks` query root, so local suggestion filtering requires no new query endpoint.

### Project/Tag models and APIs

- `backend/app/modules/tasks/domain.py:31-57` defines owner-scoped Project/Tag records with
  stored `normalized_name`, state, revision, and 500-character names.
- `backend/app/modules/tasks/domain.py:86-107` gives each Task zero/one `project_id` and a
  `tag_ids` list.
- `backend/app/modules/tasks/repository.py:65-82` canonicalizes names with Unicode NFKC,
  whitespace collapse, and casefold. Historical Tags may arrive with leading `@`.
- `backend/app/modules/tasks/service.py:87-228` creates Project, Tag, and Task through
  separate idempotent commands. `create_task` validates active references before writing.
- `service.py:1038-1056` lists only active Projects and Tags in deterministic casefolded name
  order. `service.py:1583-1601` rejects inactive refs and duplicate Tag IDs.
- `service.py:1681-1703` enforces owner-scoped uniqueness only among active normalized names;
  archived/deleted names may be recreated as active records.
- `backend/app/api/tasks.py:180-359` exposes Project/Tag create/list/update/lifecycle routes;
  `backend/app/schemas/tasks.py:59-98` keeps Task create/update title fields literal.
- The owner command lock and SQLite transaction in
  `backend/app/modules/tasks/repository.py:97-116` can support one compound Smart Add command.

### Current classification rendering and editing

- `TaskListPage.tsx:549-593` renders Tag removal chips as `@tag`, one Project `<select>`, and
  one available-Tag `<select>`.
- `TaskListPage.tsx:674-717` renders Task detail Project select and Tag checkboxes, also using
  historical `@tag` presentation.
- `frontend/src/components/shell/AppShell.tsx:212-341` renders Project navigation and Tag
  navigation/management; Tag chips currently use `@`.
- `frontend/src/app/AppRoutes.test.tsx:143-159,240-350` asserts current tag copy, contextual
  create, and ID-based row assignment controls.
- `frontend/tests/claude-design-shell.spec.ts:144-176` protects the established desktop
  composition and responsive shell through screenshots.

### Accepted constraints

- ADR-0006 fixes Tag as current product/API terminology and says Tasks have zero/one active
  Project and zero/more active Tags (`docs/decisions/0006-...md:294-305`).
- ADR-0006 preserves one-step fast title capture and requires every visible control to be
  real (`:307-324`).
- The CloudDesign contract treats the prototype as interaction evidence rather than
  executable persistence semantics and preserves the existing shell composition.
- The repository constitution requires contract-first changes, failing-then-passing tests,
  owner/idempotency boundaries, and no unreviewed durable side effect.

## Resolved design questions

### Where does parsing live?

The desktop browser owns caret-local parsing and suggestions. Existing literal API clients
must not acquire new semantics. The server receives explicit clean title and classification
references, not raw inline syntax.

### How are unknown classifications created safely?

Use one new Tasks-module compound command, not a browser sequence of three existing
commands. This gives the submit one transaction and one idempotency key and avoids orphan
classification records after a later failure.

### How are multi-word existing names represented?

The grammar supports quoted tokens such as `@"Onboarding drop-off"`. Selecting a suggestion
serializes the canonical name as unquoted when safe and quoted with escapes otherwise.
This keeps the existing plain input rather than requiring contenteditable inline chips.

### How are partial tokens distinguished from committed tokens?

A candidate under the caret may drive suggestions before it is syntactically complete. On
submission, only a complete unquoted/closed quoted token is classified. Bare sigils,
unsupported bodies, and unclosed quotes remain literal.

### What does the second Project token do?

Process Project tokens left-to-right. Each replaces the current candidate, including a
contextual Project. Remove every Project token from the title, send only the final candidate,
and never create a superseded unknown name.

### How do current dropdowns coexist?

Smart Add applies only to new-task composition. Current task-row/task-detail ID controls
remain post-create editing controls. Row/detail title editing remains literal. This avoids
silently expanding scope into a task-edit mini-language and preserves established behavior.

### Which sigils render after creation?

Tags become `#tag`; Project classification becomes `@project`. Historical Tag names that
may contain leading `@` are presentation-normalized so output never becomes `#@tag`.
Project list headings remain ordinary names; sigils are classification affordances, not a
rename of the Project entity.

## Rejected shortcuts

- Parsing all `POST /tasks.title` values: breaks literal compatibility and voice capture.
- Per-keystroke backend search: duplicates arrays already loaded by the shell and adds
  avoidable latency/failure states.
- Client create-then-create-then-task choreography: exposes partial writes.
- A new contenteditable rich composer: conflicts with the product direction to preserve the
  existing Claude/Cloud Design composition.
- Fuzzy or AI classification: not required and would make creation behavior ambiguous.
