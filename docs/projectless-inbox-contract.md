# Projectless Inbox query and API/UI contract

Status: implementation-ready for Kanban task `t_5ec0d5aa`.

## Decision

Inbox is a server-projected view, not an alias for the persisted `inbox` lifecycle
state. Its canonical predicate is:

```text
task.owner_id = current_user.id
AND task.state = "inbox"
AND task.project_id IS NULL
```

The current API already expresses the last clause with
`unassigned_project=true`. Therefore the canonical Inbox request is:

```http
GET /api/tasks?state=inbox&unassigned_project=true
```

Search, priority, due-date, sort, terminal-item visibility, cursor, and limit
parameters compose with that request. `GET /api/tasks?state=inbox` remains a raw
lifecycle-state query and is not the Inbox product projection. Do not filter an
unqualified first page in React.

This distinction is required because assigning a Project changes organization,
not lifecycle. An assigned task may still have `state="inbox"`, but it is no
longer in the Inbox view.

## Existing model and reusable server behavior

- `TaskDocument.project_id` is nullable in
  `backend/app/modules/tasks/domain.py`.
- SQLite persists the same nullable value in `tasks.project_id` and enforces the
  owner-scoped Project foreign key in
  `backend/app/modules/tasks/repository.py`.
- `GET /api/tasks` already accepts `unassigned_project`; `TaskService.list_tasks`
  rejects its use with `project_id`, includes it in the cursor fingerprint, and
  applies `task.project_id is None` in both `_filter_tasks` and `_open_counts`.
- Search is normalized and matched against title/details before sorting and
  pagination. Counts use the same search, Project/Tag, priority, due-date, and
  unassigned predicates.

No new endpoint or response shape is required. The implementation should wire
this existing server capability into every UI query that represents Inbox.

## Query, count, pagination, search, and empty-state rules

1. **Rows:** every page of the Inbox list sends `state=inbox` and
   `unassigned_project=true`. Every returned item must have `project_id=null`.
2. **Count:** the Inbox page count is `counts_by_state.inbox` from that same
   filtered response. It is calculated over all matching open Inbox tasks before
   cursor and limit, never from `items.length` or a filtered first page.
3. **Search and filters:** `q`, priority, due-date, and terminal visibility are
   additive. In particular, an Inbox search count and rows both exclude assigned
   matches. Search normalization remains server-owned.
4. **Pagination:** apply owner, lifecycle state, and projectless predicates before
   sorting, cursor comparison, `limit`, `has_more`, and `next_cursor`. The cursor
   fingerprint must continue to include `unassigned_project`, so a cursor from a
   raw state query or Project query is rejected for Inbox and vice versa.
5. **Mutation refresh:** assigning or clearing a Project invalidates all task-list
   queries. Refetch starts at page one; do not continue a pre-mutation cursor over
   the changed projection.
6. **Empty state:** render `Inbox is clear` only after the canonical server query
   succeeds with no items and no next page. An empty client-filtered first page is
   not an empty Inbox.
7. **Navigation badge:** a badge labelled Inbox must use the canonical projectless
   Inbox count, including while another state, Project, Tag, date, or search view
   is active. The current shell receives query-scoped `counts_by_state`, so the
   implementation must not treat a Project-scoped `counts_by_state.inbox` as the
   global Inbox badge. Reuse/cache a small canonical Inbox query (for example,
   `state=inbox&unassigned_project=true&limit=1`) or otherwise provide that same
   server projection; do not count client-side.

`counts_by_state` on a Project-filtered response remains a Project-local lifecycle
breakdown. Its `inbox` field can legitimately count an assigned task whose
persisted state is `inbox`; it is not the Inbox navigation count.

## Lifecycle and Project behavior

`PATCH /api/tasks/{task_id}` with `project_id` is the organization command. It
must:

- require the existing owner, active-Project, expected-revision, and idempotency
  checks;
- update `project_id`, `updated_at`, and `revision` only as currently appropriate;
- preserve `state`, `waiting_for`, `waiting_since`, `completed_at`, and
  `cancelled_at` unless those fields are changed through their existing dedicated
  lifecycle command;
- return the unchanged lifecycle state in `TaskResponse`.

After assignment:

- the task is absent from the canonical Inbox rows and Inbox count;
- `GET /api/tasks?project_id={id}` still returns it, including when its persisted
  state remains `inbox`;
- `GET /api/tasks/{task_id}` remains directly accessible.

Project routes must send `project_id={id}` without `unassigned_project`. Project
creation from a Project view may continue to create an `inbox`-state task already
assigned to that Project; it appears in the Project and never in Inbox.

Archiving a Project currently clears `project_id` while preserving each task's
state. That behavior remains intentional: formerly assigned `inbox`-state tasks
re-enter Inbox, while `next`, `waiting`, `someday`, completed, and cancelled tasks
remain in their existing lifecycle states.

## Affected implementation surfaces

| Surface | Required implementation |
|---|---|
| `frontend/src/api/taskTypes.ts` | Add an `unassignedProject?: boolean` list-filter field. |
| `frontend/src/api/client.ts` | Serialize it as `unassigned_project=true`; keep cursor and all other filters on every page. |
| `frontend/src/api/taskHooks.ts` | Keep it in the React Query key and page requests through the existing filters object; aggregate only server-returned pages. |
| `frontend/src/features/tasks/TaskListPage.tsx` | Set `unassignedProject` only for the Inbox product view; use server items/count/has-more directly; supply the shell with a canonical Inbox badge count; invalidate task queries after Project assignment. |
| `frontend/src/components/shell/AppShell.tsx` | Preserve the visual language; consume the authoritative Inbox badge count without local filtering. |
| `backend/app/api/tasks.py` | Existing query parameter and response contract are sufficient; optionally clarify its OpenAPI description. |
| `backend/app/modules/tasks/service.py` | Existing predicate/count/cursor behavior is sufficient and must not be weakened. |
| Backend/frontend tests | Add the focused regressions below. |

## Required regression tests

Backend API/service:

- Mixed unassigned and assigned `inbox`-state tasks: canonical query returns and
  counts only unassigned tasks.
- More than one page with assigned tasks interleaved in sort order: pages contain
  only unassigned tasks; `has_more`/cursor are based on that projection; no gaps or
  duplicates.
- Search matching both assigned and unassigned tasks: rows and Inbox count include
  only matching unassigned tasks.
- A cursor minted without `unassigned_project`, or with another filter set, is
  rejected for the canonical Inbox query.
- Assign a Project to an Inbox task: response preserves lifecycle fields; canonical
  Inbox loses it; Project query gains it.
- Archive that Project: the task becomes projectless and re-enters Inbox only if
  its lifecycle state is still `inbox`.
- Owner isolation and the existing `project_id` plus `unassigned_project`
  validation remain intact.

Frontend client/route:

- Inbox requests serialize `state=inbox&unassigned_project=true`, including
  search and subsequent cursor pages.
- Next/Waiting/Someday, Project, Tag, and date requests do not accidentally set
  `unassigned_project`.
- Assigning a Project invalidates/refetches the Inbox and Project/count queries;
  the row and count disappear without a local array filter.
- The Inbox empty state appears only for an empty successful canonical response;
  loading and error states are unchanged.
- A Project route still renders an assigned task whose lifecycle state is
  `inbox`.
- The Inbox navigation badge remains projectless when another view is active.

## Migration and ambiguity notes

No data migration or backfill is needed: `project_id` is already nullable in the
Pydantic document, SQLite column, JSON payload, and legacy JSON import. Missing
legacy values validate as `None`.

The repository currently materializes owner-scoped rows and applies list
predicates in `TaskService`; therefore `project_id IS NULL` is the conceptual
storage predicate and `task.project_id is None` is today's implementation. A
future SQL-backed list query must push the predicate into SQL before pagination
and should add an owner/state/project/order index if profiling justifies it. Do
not add an index-only migration for this outcome.

The only resolved naming ambiguity is that `state=inbox` alone means lifecycle
state, while **Inbox** means the compound projectless projection. Preserve that
separation in tests and documentation.