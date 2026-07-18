# ADR-0006: Fix the native GTD lifecycle and capability baseline

Date: 2026-07-18
Status: Accepted
Decision owner: BrainBuddy
Related: ADR-0001, ADR-0002, `docs/vnext-cloud-design-build-contract.md`,
`docs/e2e-acceptance-charter.md`, origin `main` at
`ac60a7352e8f44156f32bd35ef2c515c1416a1f1`, Kanban task `t_4a32f54d`

## Context

ADR-0001 authorizes BrainBuddy-owned native Tasks and Projects. The accepted CloudDesign
v2 build contract fixes the responsive information architecture around Inbox, Next,
Waiting, Someday, Projects, task classification, task detail, and Voice Brain Dump. Since
that contract was written, `main` has shipped a task backend, a responsive shell, first-class
Tags, SQLite persistence, and a bounded Voice Brain Dump flow.

The shipped slice is not yet the complete baseline represented by the design and current
product acceptance tasks. Some capabilities are backend-only, some controls are visibly
disabled, and some controls invoke the wrong contextual command. The old build contract's
"Current repository" inventory is therefore historical, not a current implementation
status report.

This record does two things:

1. audits the exact current capability from route to persistence and tests; and
2. fixes the lifecycle and query semantics needed by the next implementation slices.

It does not redesign the approved information architecture. The four open GTD lists remain
the primary navigation; Projects and Tags remain secondary organization; date views are
derived queries, not new lifecycle states; Weekly Review remains explicitly deferred; and
the CRT remains isolated under `/crt`.

## Decision

Adopt the lifecycle, field, query, error, and UI-control contracts in this record as the
native GTD baseline. This record supersedes only these narrower parts of ADR-0001 and the
CloudDesign build contract:

- the product term and public API are now **Tag** / `/tags`, not Context / `/contexts`;
- entering Waiting requires a non-blank `waiting_for`; `waiting_since` is server-generated
  metadata and is not an alternative supplied by the client;
- Priority is admitted to the baseline as an explicit Task field;
- task-only search, date views, and named sort modes are admitted without creating the
  previously deferred federated task-and-tree search;
- the terminal-state recovery and invalid-transition rules below are normative.

All other module ownership, provenance, owner isolation, idempotency, CRT separation, and
Voice Brain Dump operation boundaries from ADR-0001/0002 remain unchanged.

## Audit method and status legend

The audit traced CloudDesign v2 source, accepted contracts, frontend routes/components/API
calls, backend schemas/routes/service/repository code, and task tests. It uses these labels:

- **Working** — the user-visible path is backed by the real owner-scoped API, persists, and
  has relevant automated evidence.
- **Partial** — meaningful layers exist, but the end-to-end acceptance path or part of its
  contract is missing.
- **Absent** — no usable implementation exists in the relevant product layers.
- **Broken** — a visible control or supported-looking path fails, acts on the wrong context,
  omits data, or contradicts an accepted contract.

"Working" is not a claim that all future ADR-0002 operation capabilities are complete; it
is scoped to the named row.

## Capability matrix

### Shell, navigation, and projections

| ID | Baseline capability | Status | Evidence and current behavior | Implementation gap / acceptance consequence |
|---|---|---|---|---|
| B-01 | Authenticated task landing | **Working** | `/` redirects to `/tasks/next`; task, project, tag, Brain Dump, and CRT routes are protected in `frontend/src/app/AppRoutes.tsx:16-76`. Route evidence is in `frontend/src/app/AppRoutes.test.tsx:110-148`. | Preserve `/tasks/next` as the signed-in landing and `/crt/*` as the existing Thinking/CRT boundary. |
| B-02 | Responsive desktop sidebar and mobile drawer | **Working** | One shell renders desktop sidebar and mobile drawer in `frontend/src/components/shell/AppShell.tsx:29-69,121-159`. | Preserve current responsive IA and add capabilities inside it rather than adding a parallel shell. |
| B-03 | Inbox, Next, Waiting, and Someday navigation | **Working** | The four open states are the only primary GTD list items in `AppShell.tsx:20-25,162-188`; routes resolve through `TaskListPage` in `AppRoutes.tsx:24-31`. Compose E2E navigates real state rows in `frontend/tests/native-tasks-voice-brain-dump.compose.spec.ts:180-224`. | Do not add Overdue/Today/Upcoming as Task states. They are derived views defined below. |
| B-04 | Open counts by state | **Working** | API returns `counts_by_state` in `backend/app/api/tasks.py:482-513`; service counts honor project/tag filters while ignoring state in `backend/app/modules/tasks/service.py:836-841,1428-1447`; shell renders them at `AppShell.tsx:178-184`. | New search/date/priority filters must also scope counts; state remains the only ignored filter. |
| B-05 | Project navigation/filter | **Working** | `/projects/:projectId` uses the same list page in `AppRoutes.tsx:32-39`; the client sends `project_id` in `frontend/src/api/client.ts:177-193`; the backend validates and filters it in `service.py:802-826`. | Keep project pages as task projections, not separate task stores or CRT trees. |
| B-06 | Tag navigation/filter | **Working** | `/tags/:tagId`, the sidebar tag cloud, and `tag_id` query are wired in `AppRoutes.tsx:40-47`, `AppShell.tsx:207-220`, and `client.ts:185-192`. Tag-first API behavior and retired `/contexts` are tested in `backend/tests/test_task_tag_project_mvp_api.py:18-49`. | Tag is canonical product terminology. Historical Context aliases remain migration input only. |
| B-07 | Complete result pagination in the UI | **Broken** | Backend supports opaque cursor pages with limit 50/200 in `backend/app/api/tasks.py:487-507` and `service.py:818-842`. Frontend request/filter types have no cursor or limit and render only `items` from the first response in `frontend/src/api/taskTypes.ts:55-60`, `client.ts:177-193`, and `TaskListPage.tsx:78-81`. | Implement load-more/infinite retrieval or a server aggregate. Project/tag/date/search views and counts must never present the first 50 rows as the complete result. |
| B-08 | Loading, empty, error, and retry states | **Working** | `TaskListPage.tsx:97-170,392-427` renders explicit loading, empty, error, and retry states for tasks/projects/tags. | Preserve these states in detail, search, and management surfaces. |
| B-09 | Weekly Review honesty | **Working** | The sidebar says `coming later` and exposes no fake workflow at `AppShell.tsx:222-224`, matching the accepted deferral. | Do not turn the CloudDesign `due Sun` mock value into product state until Weekly Review cadence is separately accepted. |
| B-10 | CRT boundary | **Working** | `/crt/*` renders the existing `TreeWorkspace` in `AppRoutes.tsx:64-71`; the task shell links to it as legacy CRT at `AppShell.tsx:225-227`; route isolation is tested in `AppRoutes.test.tsx:140-148`. | Do not make Projects trees or Tasks nodes. Naming can improve separately without changing ownership. |

### Capture, task detail, and lifecycle

| ID | Baseline capability | Status | Evidence and current behavior | Implementation gap / acceptance consequence |
|---|---|---|---|---|
| B-11 | Fast Inbox capture | **Working** | The title form creates the selected state or Inbox in `TaskListPage.tsx:46-54,344-388`; Inbox create/edit/move/complete/reopen persistence is exercised in compose E2E at `native-tasks-voice-brain-dump.compose.spec.ts:226-264`. | Keep one-step title capture. Rich metadata belongs in task detail and contextual create. |
| B-12 | Contextual create in an open state | **Broken** | `TaskListPage.tsx:46-48` sends the current state. Next/Someday work, but `/tasks/waiting` sends no `waiting_for`, while the service rejects it in `backend/app/modules/tasks/service.py:189-205,1241-1246`. | Waiting creation must collect `waiting_for` before submit. The UI must not offer a command guaranteed to fail. |
| B-13 | Contextual create in a Project or Tag view | **Broken** | On project/tag pages `state` is undefined and create sends only `{title, state: "inbox"}` in `TaskListPage.tsx:28-48`; it ignores `projectId` and `tagId`. The new task is unassigned and usually disappears from the current view. | Project create sends `project_id`; Tag create sends `tag_ids` including the active tag. Both default to Inbox unless the user explicitly chooses another open state. |
| B-14 | Inline title edit | **Working** | UI patches title with `expected_revision` in `TaskListPage.tsx:56-66,292-312`; backend validates and persists it in `service.py:644-695`. | Keep as a fast action; stale conflicts must reload or merge rather than silently overwrite. |
| B-15 | Task detail surface | **Absent** | A detail API exists at `backend/app/api/tasks.py:356-369`, but there is no task-detail route/panel; rows expose title edit and Move to Next only in `TaskListPage.tsx:268-340`. | Add one responsive detail route/panel using `GET /tasks/{id}`. Do not use the CRT node inspector. |
| B-16 | Editable details | **Partial** | `details` exists in domain/schema and PATCH at `backend/app/modules/tasks/domain.py:85-105`, `schemas/tasks.py:78-84`, and `service.py:676-685`; frontend request type declares it but has no UI in `frontend/src/api/taskTypes.ts:70-76`. | Persist detail edits with revision checks from the task detail surface. |
| B-17 | Editable due date | **Partial** | Date-only `due_date` exists and is persisted by create/PATCH in `schemas/tasks.py:57-67,78-84` and `service.py:195-212,676-685`; the UI only renders a formatted date at `TaskListPage.tsx:316-320,430-439`. Frontend request types omit due date at `taskTypes.ts:62-76`. | Add typed create/update fields and a date editor; use the date semantics below. |
| B-18 | Editable Priority | **Absent** | No priority field appears in `TaskDocument`, task request/response schemas, TypeScript task types, repository projections, or tests. | Add the explicit enum and semantics below through domain, storage, API, UI, filters, sort, migration, and tests. |
| B-19 | Editable Project and Tags | **Partial** | Backend create/PATCH validates same-owner active references in `service.py:184-188,669-685,1377-1395`; UI renders assignments at `TaskListPage.tsx:205-218,321-327` but has no assignment controls. | Detail UI must assign/remove one active Project and zero or more active Tags. |
| B-20 | Waiting metadata | **Partial** | Backend requires and trims `waiting_for`, generates `waiting_since`, and clears both on exit in `service.py:189-205,697-769,1241-1246`; UI types can read both but cannot send `waiting_for` in create/transition or edit it in `taskTypes.ts:62-82`. | Implement waiting entry/edit UX and exact field rules below. Display both who/what and waiting age/date. |
| B-21 | Complete open task | **Working** | UI completion calls the transition endpoint at `TaskListPage.tsx:68-76,273-290`; service accepts only open states and sets `completed_at` in `service.py:720-729`. | Completion must preserve non-waiting metadata and remain a transition, not deletion. |
| B-22 | Reopen completed task | **Partial** | `Show completed tasks` plus Reopen works in `TaskListPage.tsx:265-281,384-387` and compose E2E `:248-263`. The UI silently chooses the current state or Next at `TaskListPage.tsx:156,266`, contrary to explicit-destination recovery. | Reopen must expose/require the open destination; Waiting additionally requires `waiting_for`. |
| B-23 | Cancel and recover cancelled task | **Partial** | Backend supports cancel and reopen in `schemas/tasks.py:95-99` and `service.py:730-756`; API tests cover it at `backend/tests/test_task_api.py:203-236`. No task UI issues cancel, lists cancelled history, or reopens a cancelled task. | Add cancel to detail with clear terminal meaning and a recovery surface that names the reopen destination. Do not add Cancelled to the four primary open lists. |
| B-24 | Invalid-transition prevention/explanation | **Partial** | Service rejects complete/cancel from terminal states and move/reopen from invalid states in `service.py:720-769`; API maps semantic validation to 400 and revision conflicts to 409 in `backend/app/api/errors.py:87-119`. UI exposes only a narrow action subset and reports raw mutation messages at `TaskListPage.tsx:68-76,124`. | Detail UI must hide/disable impossible actions, explain required input, and refresh on 409. Server remains authoritative. |
| B-25 | Subtasks | **Partial** | Documents, SQLite table, create endpoint, and detail read exist at `domain.py:59-70`, `repository.py:190-199,519-552`, and `api/tasks.py:372-391`. There is no frontend API/UI and no update/complete/cancel endpoint. | Add create/edit/complete/reopen/cancel ordering behavior and persistence tests; detail is the only product surface. |
| B-26 | Comments | **Partial** | Documents, SQLite table, create endpoint, and detail read exist at `domain.py:73-82`, `repository.py:200-209,554-587`, and `api/tasks.py:394-414`. There is no frontend API/UI or owner-edit endpoint. | Add owner-authored append/read and optional owner edit preserving `edited_at`; no collaboration/mentions are implied. |
| B-27 | Reload/relogin persistence | **Working** | Task records live in SQLite with owner-scoped keys and WAL in `repository.py:85-124,145-242`; compose E2E proves state/project/tag and lifecycle persistence across reload/relogin at `native-tasks-voice-brain-dump.compose.spec.ts:180-264`. | New fields and nested mutations must persist through the same store and evidence path. |

### Projects, Tags, dates, search, filters, and sort

| ID | Baseline capability | Status | Evidence and current behavior | Implementation gap / acceptance consequence |
|---|---|---|---|---|
| B-28 | Project create/rename/color/archive | **Partial** | Backend routes and services exist at `backend/app/api/tasks.py:174-263` and `service.py:82-123,882-964`; shell only lists active projects in `AppShell.tsx:190-205`. | Add UI management with optimistic-concurrency errors and post-mutation count refresh. |
| B-29 | Project archive assignment cleanup | **Broken** | Archive unassigns every task except Cancelled at `service.py:941-963`. This makes Completed lose its project while Cancelled retains an inactive project, an unexplained terminal-state inconsistency. | Archive must atomically clear `project_id` from **all** member tasks without changing their lifecycle state. Add open/completed/cancelled coverage. |
| B-30 | Tag create/rename/delete | **Partial** | Backend routes/services exist at `api/tasks.py:266-353` and `service.py:966-1048`; delete removes the tag from all tasks. The shell only lists/navigates tags in `AppShell.tsx:207-220`. | Add UI management and explain that delete removes the classification, not the Task. |
| B-31 | Date views: Overdue, Today, Upcoming | **Absent** | Backend list route has no due-date query in `api/tasks.py:487-507`; frontend has no route/filter for date buckets. | Implement derived views with the date semantics and server-side filters below so pagination is accurate. |
| B-32 | Task search | **Broken** | A visible input says `Search tasks and trees` but is disabled in `AppShell.tsx:94-103`; neither list API nor frontend filters carry a query. | Implement task-only search and relabel it `Search tasks`, or remove the control. Federated tree search remains out of scope. |
| B-33 | State/Project/Tag filtering | **Working** | Routes and client map to backend filters in `AppRoutes.tsx:24-47`, `client.ts:177-193`, and `service.py:790-842,1397-1426`; owner/filter behavior is tested in `backend/tests/test_task_api.py:377-467,485-548`. | Extend the same query contract for date/priority/search. Do not replace server filtering with first-page client filtering. |
| B-34 | Sorting | **Broken** | A visible disabled `Sort by tag` button is rendered in `TaskListPage.tsx:114-121`. Backend only has canonical `order_key, created_at, id` order in `service.py:1484-1515`. | Remove `Sort by tag`; Tags are multi-valued filters. Implement only the named sort modes below and bind sort to the cursor. |
| B-35 | Post-mutation rows and counts | **Working** for current mutations | All task mutations invalidate the `tasks` query root in `TaskListPage.tsx:44-75`; Project/Tag query keys also live under that root in `frontend/src/api/taskHooks.ts:6-31`. Compose E2E observes rows/count changes. | New task/project/tag/date/priority mutations must preserve this refresh behavior and update all affected views. |

### Voice capture and control honesty

| ID | Baseline capability | Status | Evidence and current behavior | Implementation gap / acceptance consequence |
|---|---|---|---|---|
| B-36 | Voice Brain Dump entry to native Inbox | **Working** for the shipped bounded flow | The task shell opens `/brain-dump/new` at `AppShell.tsx:105-112`. Recording, provisional extraction, pause/resume, review edits/deletes, explicit save, idempotent commit, reload, relogin, failures, and owner isolation are exercised in `native-tasks-voice-brain-dump.compose.spec.ts:266-488`. | Task detail/organization changes must not break this entry path or create tasks before confirmation. |
| B-37 | Brain Dump authority language | **Broken** | Recording still says `Headed to inbox` at `frontend/src/features/brain-dump/BrainDumpRoute.tsx:352-357`, although the accepted contract requires provisional language until confirmation. Review says `Save ... to inbox` at `:466-473` rather than an explicit confirmation label. | Use `Provisional · N`, `Stop & review`, and `Confirm N additions`; no copy may imply canonical writes before commit succeeds. |
| B-38 | Full ADR-0002 async/privacy substrate | **Partial** | The shipped operation persists recording/paused/review/commit/cancel and handles stale revisions, but the schema at `backend/app/schemas/tasks.py:162-241` has no offline chunks, event sequence, reconciliation stage, partial action results, consent withdrawal, raw-audio retention/deletion, or bounded undo. | Preserve the current flow; do not claim full ADR-0002 conformance. Those gaps remain separate voice-operation work unless explicitly added to a child scope. |
| B-39 | Visible task-control audit | **Broken** | Search and Sort are decorative disabled controls; Waiting/Project/Tag create invoke incomplete payloads; task rows cannot open detail; project/tag management is absent. Weekly Review is correctly reframed and CRT/Brain Dump controls are real. | Every visible enabled task control must issue its supported command. Unsupported controls must be removed or clearly presented as non-interactive status, not disabled promises. |

## Canonical task lifecycle

### State meanings

| State | Canonical meaning | Included in normal open queries/counts? |
|---|---|---|
| `inbox` | Captured but not yet clarified or committed to execution. It may still have metadata, but the user has not promoted it to another open list. | Yes |
| `next` | A concrete next action the user may act on. It does not imply a due date, priority, or agent execution. | Yes |
| `waiting` | The next progress depends on a named person, organization, event, or condition recorded in `waiting_for`. | Yes |
| `someday` | Intentionally deferred with no current commitment. It is not Completed and remains reviewable. | Yes |
| `completed` | The intended task outcome was finished. This is terminal history until explicit reopen. | No |
| `cancelled` | The task will not be done or is no longer wanted. This is terminal history, distinct from success and from privacy deletion. | No |

Completed and Cancelled are not soft-delete aliases. The terminal transition itself
retains title, details, Project, Tags, due date, priority, source links, subtasks, comments,
and audit/revision history. A later explicit Project archive or Tag delete may clear that
classification under the organization rules below; content erasure still requires a
separately authorized privacy deletion.

### Allowed transitions

`move` must name a **different** open destination. A same-state move is invalid; ordinary
field changes use PATCH.

| From | Allowed state-changing commands | Forbidden examples |
|---|---|---|
| Inbox | move to Next/Waiting/Someday; complete; cancel | reopen; move to Inbox |
| Next | move to Inbox/Waiting/Someday; complete; cancel | reopen; move to Next |
| Waiting | move to Inbox/Next/Someday; complete; cancel | reopen; move to Waiting |
| Someday | move to Inbox/Next/Waiting; complete; cancel | reopen; move to Someday |
| Completed | reopen to an explicitly named Inbox/Next/Waiting/Someday | move, complete, cancel |
| Cancelled | reopen to an explicitly named Inbox/Next/Waiting/Someday | move, complete, cancel |

Idempotency is command-level, not permission for an otherwise invalid transition:

- replaying the same `Idempotency-Key` with the same command/body returns the original
  successful result;
- a new key attempting complete on Completed remains invalid;
- reusing a key for another command/body is a conflict.

### Transition field effects

| Command | State/timestamps | Waiting metadata | Other Task fields |
|---|---|---|---|
| move to Waiting | state=`waiting`; terminal timestamps null | non-blank `waiting_for` required; server sets `waiting_since=now` | preserved |
| move between other open states | destination state; terminal timestamps null | clear `waiting_for` and `waiting_since` | preserved |
| complete | state=`completed`; set `completed_at=now`; clear `cancelled_at` | clear both waiting fields | preserved |
| cancel | state=`cancelled`; set `cancelled_at=now`; clear `completed_at` | clear both waiting fields | preserved |
| reopen to Waiting | state=`waiting`; clear both terminal timestamps | non-blank `waiting_for` required; server sets `waiting_since=now` | preserved |
| reopen to another open state | destination state; clear both terminal timestamps | clear both waiting fields | preserved |

Every successful transition increments `revision`, updates `updated_at`, receives an
idempotency key, and is owner-scoped.

### Waiting behavior

- `waiting_for` is required, trimmed, and must contain at least one non-whitespace
  character whenever state is Waiting.
- It is free text up to 500 characters. It does not create a Person, Task, or dependency
  record.
- `waiting_since` is server-generated on entry/re-entry and cannot be supplied by clients.
- Editing `waiting_for` while already Waiting is a metadata PATCH and preserves
  `waiting_since`; it does not create a same-state transition.
- A non-Waiting task cannot carry either waiting field. Leaving, completing, or cancelling
  Waiting clears both active fields.
- The UI must collect `waiting_for` before enabling a move/create/reopen to Waiting and
  explain the requirement inline.

### Completion and cancellation recovery

- Terminal history must be retrievable through explicit API filters and reachable from the
  current list/detail context without adding terminal states to the four primary GTD
  navigation items.
- Reopen always presents and submits the destination. The server and UI never infer the
  old state or silently default to Next.
- Reopening to Waiting collects `waiting_for` before submission.
- Reopen clears the relevant terminal timestamp and retains all non-waiting metadata.
- A stale recovery attempt returns 409 and leaves the terminal task unchanged.

### Invalid-transition and error handling

The API contract is:

- `400` for a semantically invalid command: wrong source state, same-state move, missing
  destination, missing/blank `waiting_for`, or a field/state invariant violation;
- `404` for absent or other-owner Task/Project/Tag IDs;
- `409` for stale `expected_revision` or conflicting idempotency-key reuse;
- `422` for an invalid request shape or enum value;
- no mutation on any rejected command.

The UI prevents known-invalid commands, displays the actionable server message for
unexpected validation failures, and on 409 refetches the Task while preserving unsaved
user input for an explicit retry. It must not convert a failure into optimistic success.

## Field and query semantics

### Due date

- `due_date` is an ISO `YYYY-MM-DD` local calendar date. It carries no time-of-day,
  timezone, reminder, recurrence, or notification promise.
- The browser derives the user's current local date and sends explicit ISO boundaries to
  the server; the server must not classify dates using its own timezone.
- Derived date views include open tasks only by default:
  - **Overdue:** `due_date < local_today`;
  - **Today:** `due_date = local_today`;
  - **Upcoming:** `due_date > local_today` (all future dated open tasks; no hidden horizon).
- Undated tasks appear in none of the three date views.
- Completion/cancellation does not clear `due_date`. Terminal rows appear only when the
  caller explicitly includes that terminal state.
- Date filtering is server-side and cursor-bound so results beyond the first page are not
  lost.

Implementation-ready list parameters are `due_before`, `due_on`, and `due_after`, each an
ISO date and mutually constrained so one bucket is unambiguous. The UI may expose friendly
routes, but the API operates on explicit date values.

### Priority

Add one Task-owned field:

```text
priority: none | low | medium | high   # default: none
```

Priority is user classification, not urgency derived from due date and not permission to
reorder silently. It persists through move, complete, cancel, and reopen. API requests and
responses use the explicit string `none`, not null and not a missing-value distinction.

Priority filtering accepts one or more exact values. Priority sort order is
`high, medium, low, none`, then the canonical tie-breakers.

### Search

The baseline adds **task-only** search. It does not revive the deferred federated
`Search tasks and trees` promise.

- Query parameter: `q`.
- Match: trimmed, Unicode-normalized, case-insensitive substring over Task `title` and
  `details`.
- Project and Tag classification remain explicit filters; their names are not implicit
  full-text matches.
- Search composes with state, project, tag, date, priority, and terminal inclusion.
- Empty/whitespace query is equivalent to no search.
- Search is server-side, owner-scoped, and bound into the opaque cursor.
- The browser keeps the query in the URL so reload/back navigation reproduce the result.

### Filters, counts, sorting, and pagination

The flat list remains canonical. The service applies all selected filters before ordering
and pagination.

Named sort modes for this baseline are:

1. `manual` (default): `order_key ASC, created_at ASC, id ASC`;
2. `due`: dated first by `due_date ASC`, then undated, then manual tie-breakers;
3. `priority`: `high, medium, low, none`, then manual tie-breakers;
4. `title`: Unicode-normalized case-insensitive title ASC, then `id`.

There is no `tag` sort. Tags are multi-valued; the current `Sort by tag` control must be
removed or reframed as the already-supported Tag filter.

The cursor binds normalized state/project/tag/search/date/priority/terminal filters plus
sort mode and last sort tuple. Counts by open state ignore only the state filter and honor
all other active filters. The frontend consumes every requested page or visibly offers
continuation; it never describes `items.length` from page one as a complete total.

## Organization semantics

- A Task has zero or one active Project and zero or more active Tags.
- Project/Tag IDs are owner-scoped; inactive or other-owner assignments are rejected.
- Project archive does not complete, cancel, or delete tasks. It atomically clears that
  `project_id` from every member Task, including Completed and Cancelled history.
- Tag delete does not complete, cancel, or delete tasks. It atomically removes that tag ID
  from every Task.
- Project/Tag rename updates the classification record; tasks keep stable IDs and render
  the new name without per-task rewrites.
- Project and Tag management mutations refresh list rows, navigation entries, filtered
  counts, and detail options.

## Visible-control acceptance

The current information architecture is preserved, but controls must be truthful:

| Current control | Accepted disposition |
|---|---|
| `Search tasks and trees` disabled input | Implement and relabel `Search tasks`, or remove until implemented. Do not imply tree federation. |
| `Sort by tag` disabled button | Remove/reframe as Tag filtering. Use only named sort modes above. |
| Add task on Inbox/Next/Someday | Keep fast title capture with selected open state. |
| Add task on Waiting | Collect `waiting_for` before submit. |
| Add task on Project/Tag page | Include the selected classification in the create command. |
| Task row title/edit/checkbox | Keep quick title and Complete; row/title also opens real detail without stealing button clicks. |
| `Move to Next` | May remain a shortcut; detail exposes the complete valid lifecycle set. |
| `Show completed tasks` | Scope to the current filters, label its effect clearly, and reopen only after destination selection. Provide equivalent Cancelled recovery without adding a primary list. |
| Project and Tag labels in navigation | Add management affordances only when their create/rename/archive/delete commands are wired. |
| Weekly Review coming later | Keep visibly non-interactive until its accepted workflow exists. |
| Brain Dump recording/review labels | Use provisional/confirm language; every action remains backed by the persisted operation. |
| Account avatar | Make it a real account/sign-out control or render it as non-interactive identity, not a button-shaped dead end. |

## Implementation-ready API/UI gaps

### Backend

1. Add `priority` to domain, storage migration/default, create/update/response contracts,
   filters, sort, and tests.
2. Allow PATCH of `waiting_for` only for Waiting tasks; preserve `waiting_since`; reject the
   field for other states.
3. Reject same-state move and enforce the full transition matrix.
4. Add task-only `q`, due-boundary, priority, sort, and explicit terminal filters; bind all
   of them into cursors and counts.
5. Make project archive clear assignments from all lifecycle states atomically.
6. Complete Subtask commands (edit and lifecycle) and owner Comment edit if the UI ships
   those controls.
7. Preserve owner isolation, `expected_revision`, `Idempotency-Key`, correlation IDs, and
   SQLite transaction boundaries for every mutation.

### Frontend

1. Add a responsive task detail route/panel with editable title, details, state, Project,
   Tags, due date, Priority, and `waiting_for` plus Subtasks and Comments.
2. Fix contextual create payloads for Waiting, Project, and Tag views.
3. Add Project and Tag management using existing backend commands.
4. Add URL-backed task search, date views, priority/date/tag/state filters, named sorts, and
   pagination/continuation.
5. Add explicit Completed/Cancelled recovery with destination selection and stale-conflict
   recovery.
6. Remove/reframe every decorative task control and correct Brain Dump authority language.
7. Preserve Voice Brain Dump task-cache invalidation and reload/relogin behavior.

### Automated acceptance evidence

At minimum, implementation tests must cover:

- every allowed and forbidden transition from every lifecycle state;
- create/move/reopen to Waiting with blank, trimmed, and valid `waiting_for`;
- waiting field clearing and preservation rules;
- complete/cancel/reopen timestamp and metadata preservation;
- stale revisions, idempotent replay, conflicting key reuse, and wrong-owner IDs;
- Priority create/edit/filter/sort/persistence;
- Overdue/Today/Upcoming at local-date boundaries, including month/year boundaries;
- search composition with state/project/tag/date/priority and cursor replay;
- pagination beyond 50 rows in state, Project, Tag, date, and search views;
- Project archive cleanup for open, Completed, and Cancelled tasks;
- Tag deletion cleanup and post-mutation counts;
- contextual create from Waiting, Project, and Tag pages;
- task detail edits, Subtasks, Comments, terminal recovery, reload, and relogin;
- an automated inventory asserting every visible task-related button/input/menu/toggle is
  enabled and wired, or intentionally absent/non-interactive;
- the existing compose Voice Brain Dump path still creates exactly the confirmed native
  Inbox tasks and no task before confirmation.

## Consequences

Positive consequences:

- downstream implementation has one explicit lifecycle and field contract instead of
  inferring behavior from partial UI and backend code;
- date and priority features compose with existing states rather than fragmenting the IA;
- terminal history remains recoverable without polluting the four open GTD lists;
- Tags, current SQLite persistence, and the existing Voice Brain Dump path are preserved;
- decorative controls become testable product commitments or disappear.

Tradeoffs and risks:

- the list API and cursor payload must evolve for search/date/priority/sort;
- adding Priority requires a stored-data migration/default;
- fixing project archive affects terminal records and needs transaction/replay coverage;
- the old accepted build contract retains historical Context terminology and baseline
  snapshots; readers must use this later, narrower record for current GTD semantics.

Future agents must preserve:

- the four open states versus two terminal states distinction;
- explicit reopen destinations and required `waiting_for` on Waiting entry;
- date views as queries and due date as a date without reminder/timezone promises;
- explicit Priority independent of due date and lifecycle;
- task-only search rather than an unimplemented federated promise;
- Tags as the current public classification surface;
- Tasks as canonical native records, separate from Capture/Organize, Execution, and CRT;
- no visible task control without real behavior or explicit non-interactive framing.

## Verification references

- `backend/tests/test_task_api.py`
- `backend/tests/test_task_branch_coverage.py`
- `backend/tests/test_task_repository.py`
- `backend/tests/test_task_tag_project_mvp_api.py`
- `frontend/src/app/AppRoutes.test.tsx`
- `frontend/src/features/brain-dump/BrainDumpRoute.test.tsx`
- `frontend/tests/native-tasks-voice-brain-dump.compose.spec.ts`
- `docs/e2e-acceptance-charter.md`
