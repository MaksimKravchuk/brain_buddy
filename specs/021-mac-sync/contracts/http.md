# HTTP contract: Mac ↔ backend sync (021)

**Base**: every path is under `config.api_prefix` (`/api`), authenticated by the session cookie (`Depends(get_current_user)`; 401 without a session) and scoped to the owner. Routes stay in `backend/app/api/tasks.py` (ASK path) beside the existing project routes (l.539 – 636). Services come from `Depends(get_task_service)`, and no route touches a repository.

**Envelope** (unchanged): `ErrorResponse {message, detail?, reference_id}` plus `X-Correlation-ID` on every response. `reference_id` equals the header.

**Mutations** keep requiring `Idempotency-Key`; without it the answer is 400 (`_require_idempotency_key`, `tasks.py:239-242`). A replay with the same key and body returns the stored response. A different body under the same key gives 409.

**Ownership**: an unknown id or one owned by someone else gives 404 `{"resource": "Project", "id": …}`, never 403.

**Compatibility class**: every change below is additive under `docs/api-compatibility.md`, except the side effect of `POST /projects/{id}/archive` (§4), which ADR-0020 decided. §7 states what older clients see.

## 1. `GET /projects` — state filter (PR-02)

| query | values | default | invalid |
|---|---|---|---|
| `state` | `active` \| `archived` \| `all` | `active`: the same project set and order as today; each object gains the §2 fields | 422 |

- The response is `list[ProjectResponse]`, sorted by case-folded name, then id (unchanged).
- Results are the caller's projects only, whatever `state` says; an owner with none gets 200 `[]` (review c2, G53). Test: `test_021_FR_026_list_projects_state_is_owner_scoped` in `test_project_archive_lossless_api.py`: the second owner's archived and active projects never appear in the first owner's `?state=archived` or `?state=all`, and an owner with none gets `[]`.
- `open_task_count` stays per project. With lossless archive, it counts the open tasks still attached to an archived project; X-06 shows "Archived project · 3 open tasks".
- **One pass** (review c2, G42): today `_to_project_response` calls `open_task_count_for_project` for each project, and each call loads every task of the owner (`backend/app/modules/tasks/service.py:896-900`), so a list costs projects × tasks row loads. With 021 the list runs on every Apple-client pull (every 30 s) and every web refetch (45 s), with `state=all`. PR-02 adds `TaskService.open_task_counts_by_project(owner_id) -> dict[str, int]`, computed from one `list_for_owner` call, and the list route uses it; the single-project routes keep the per-project call. A pytest asserts equal counts both ways and one task load per list request.
- Errors: 401, 422. The 422 is new for this operation (review c1, F44): the route's `responses=error_responses(401)` (`backend/app/api/tasks.py:562`) becomes `error_responses(401, 422)`, and `backend/tests/test_api_contract.py` changes `("/api/projects", "get"): {"401"}` (l.247) to `{"401", "422"}` in PR-02, because that test asserts exact set equality.

## 2. `ProjectResponse` and request bodies (PR-02)

```text
ProjectResponse {
  id: str, name: str, color: str | null,
  state: "active" | "archived",
  revision: int ≥ 1, open_task_count: int ≥ 0,
  desired_outcome: str | null,          // new, ≤ 1000
  archived_at: datetime | null,         // new; set by lossless archive only
  archived_before_lossless: bool        // new; FR-027 marker, default false
}
ProjectCreateRequest { name, color?, desired_outcome?: str | null }          // new optional field
ProjectUpdateRequest { name?, color?, desired_outcome?: str | null, expected_revision }
```

**`desired_outcome` rules**:

- It is trimmed; empty or whitespace becomes `null`; it may be at most 1000 characters, otherwise 422.
- In `PATCH`: omitted keeps the stored value (`model_fields_set`), `null` clears it, and a string sets it.
- A PATCH that changes only `desired_outcome` bumps `revision` like any project edit.

**Display rule for the marker** (every client): show the FR-027 line only when `archived_before_lossless` is true **and** the project has no tasks in any state. Clients read task membership from their task data; the web uses `GET /tasks?project_id=<id>&include_completed=true&include_cancelled=true`.

## 3. `POST /projects/{project_id}/unarchive` (new, PR-02)

| | |
|---|---|
| Headers | `Idempotency-Key` (required) |
| Body | `ExpectedRevisionRequest {expected_revision: int ≥ 1}` |
| 200 | `ProjectResponse`; `state: "active"`, `archived_at: null`, `revision + 1`; `archived_before_lossless` unchanged; no task changes |
| 200 (already active) | `ProjectResponse` unchanged, no revision bump (idempotent in effect) |
| 400 | missing `Idempotency-Key` |
| 401 | no session |
| 404 | unknown or foreign project |
| 409 | stale `expected_revision` (existing conflict body); or an active project with the same normalized name exists, giving `ConflictError("Project", name)`, the same body `POST /projects` returns for a duplicate name |
| 422 | body shape |

- **Order of checks** (review c2, G44): (1) the idempotency record for this key, if any, returns its stored response; (2) the project is loaded (404 when unknown or foreign); (3) **a project already active returns 200 unchanged, before** `expected_revision` is checked, so a retry after the key has expired (it carries the old, now stale revision) still gets 200; (4) a stale `expected_revision` gives 409; (5) an active name clash gives 409. `archive_project` checks the revision first today (`service.py:962-981`); unarchive deliberately differs, and the golden traces pin it (an unarchive with a stale revision on an already active project → 200).
- **Service**: `TaskService.unarchive_project`, decorated `@_serialized_write`, with idempotency command `unarchive_project:{project_id}`. The prefix is added to `_apply_idempotent_record` / `_project_result` (`service.py:1145-1203`), and the request model to `_request_hash` (`service.py:1294-1314`).
- **API contract test**: `backend/tests/test_api_contract.py` adds the operation with `{400, 401, 404, 409, 422}` to `expected_error_statuses` (exact set equality, l.411).
- **Parity inventory** (moved to PR-06 in review c2, G09): `contracts/api-client-parity.json` gains `unarchiveProject` and `listProjects(state)` in **PR-06**, together with the web client methods, their adapters and the count in `frontend/src/api/__tests__/clientParity.test.ts` (today "exactly 42 operations", l.96-103, which is the manifest's only reader). Landed in PR-02 without the web adapters, it would turn the frontend lane red on the landing path, which runs every stack.

## 4. `POST /projects/{project_id}/archive` — side effect changes (PR-02, then PR-03)

The request, the response model and the status set are unchanged.

| slice | member tasks (all states: open, completed, cancelled) | project fields |
|---|---|---|
| today | `project_id = null`, `revision + 1` each | `state = archived` |
| after PR-02 | as today (still cleared) | as today, plus `archived_before_lossless = true` |
| after PR-03 (ADR-0020) | **unchanged**: no field, no revision, no `updated_at` change | `state = archived`, `archived_at = now`, `archived_before_lossless = false` |

**Repeat archive** (review c1, F14): archiving an already archived project is accepted, as today, and changes **only** `revision` and `updated_at`. `archived_at` and `archived_before_lossless` are left as they are, under PR-02 and PR-03 alike; members are untouched. Otherwise a repeat archive of a pre-feature project (marker true, `archived_at` null) would stamp `archived_at` and clear the marker, destroying FR-027's only signal. The service reads the current state before writing the two fields (there is no such guard today). Golden trace and a PR-03 pytest case (`test_021_FR_027_repeat_archive_keeps_marker`): seed a pre-feature archive, archive again → 200, marker still true, `archived_at` still null.

## 5. Task routes — validation of archived membership (PR-02)

`PATCH /tasks/{id}` (`TaskService.update_task`, `service.py:649-655`):

| request | today | after PR-02 |
|---|---|---|
| `project_id` omitted, task's current project archived | 400 "Task project must be active." | **200** (membership kept) |
| `project_id` equal to the current, archived project | 400 | **200** |
| `project_id` set to a different archived project | 400 | 400 (unchanged) |
| `project_id: null` or an active project | 200 | 200 |

These routes are unchanged:

- `POST /tasks` and `POST /tasks/smart-add` with an archived project still give 400. `_assert_active_references` and `_resolve_smart_add_project` are not changed.
- `POST /tasks/{id}/transitions`, subtasks and comments never checked the project, and still do not.
- `GET /tasks?project_id=<archived>` already works (existence check only, `service.py:805`). After PR-03 it returns the retained members, and the web's archived project page (D-01) uses it.

## 6. Client attribution — `X-Client` (PR-02, FR-031)

| header | accepted form | logged as |
|---|---|---|
| `X-Client` | `^brainbuddy-(ios\|macos)/[0-9A-Za-z.+-]{1,32}$` | `client=ios\|macos client_version=<v>` |
| absent | — | `client=web client_version=-` |
| any other value | — | `client=other client_version=-` (the raw value is never logged) |

- **Where**: `CorrelationIdMiddleware` (`backend/app/api/middleware.py`, ASK path) parses the header once. It adds the two fields to the existing `api_request` and `api_request_failed` lines.
- **Effect on behaviour**: none. The header is an observability label only (constitution IV), and no route reads it.
- **Correlation id** (review c1, F50, F57): today the middleware accepts any incoming `X-Correlation-ID` or `X-Request-ID` verbatim, binds it into every log line of the request and echoes it in the response (`backend/app/api/middleware.py:38-41, 65`). With 021 the client-minted id becomes the reference id people copy, so PR-02, which already edits this file, accepts an incoming id only when it matches `^[0-9A-Za-z._-]{1,64}$` and otherwise mints a fresh UUID. The kit's lower-cased UUID matches; the web sends none (it reads the header from responses). `test_client_attribution_logging.py` adds a newline-injection case: `X-Correlation-ID: abc\nforged=1` gives a fresh UUID in the response header, and the raw value appears in no captured log line.

## 7. What older clients see

| client | after PR-02 | after PR-03 |
|---|---|---|
| iPhone build without 021 | Unchanged responses for its calls: `GET /projects` default; ignores new fields | Its own archive clears memberships locally, and the next pull restores them. Tasks in archived projects show with the project, which it fetches by id. Edits to them are accepted (§5). Unarchive done elsewhere shows the project active again. Nothing crashes or is dropped. |
| Web bundle before PR-06 | Ignores new fields | Its archive keeps memberships. It shows tasks of archived projects with "No project", because it resolves names from active projects only (`frontend/src/features/tasks/TaskListPage.tsx:1073-1095`). The web is served by the same deploy as the API, so this lasts **from the PR-03 deploy until PR-06 is deployed**, not just until a reload (review c2, G45). It is display-only and accepted; the deploy notes keep the gap short by deploying PR-06 next after PR-03 (plan "Migration, deploy order and rollback"). |
| Mac build without 021 | Local only, never calls the API | — |

## 8. Deploy order and rollback

```text
PR-02 (tolerant validation, unarchive, ?state=, desired_outcome, marker, X-Client)
  → PR-03 (lossless archive)
  → kit/iPhone builds (PR-04, PR-05, PR-07) and web (PR-06) that use unarchive, ?state=all, desired_outcome
  → Mac (PR-08, PR-09)
```

**Rolling back the image**:

- **PR-03 back to PR-02**: safe only **before any 021 kit build (PR-04 onward) has shipped**: future archives clear memberships again, and memberships retained so far stay valid, because PR-02 accepts them. Once a PR-04 client exists it applies lossless archive locally (including the Mac's first-upload `archiveProject` of imported archived projects); against a PR-02 image the server would clear those members and the next pull would strip them, irreversibly (ADR-0020 forbids reconstruction). **From then on PR-03 is rolled forward, never back** (review c2, G62); the `docs/api-compatibility.md` runbook note written in PR-02 says so, and the kit raises a sync issue if an archive reply shows a clearing server (kit-commands §4 "Push").
- **PR-02 back to the previous image**: safe, because no retained memberships exist before PR-03.
- **Rolling back below PR-02 after PR-03 has run**: unsafe. Every task in a project archived meanwhile would reject edits with 400 until roll-forward. The release workflow's automatic rollback only goes one image back, and PR-02 and PR-03 are separate releases, so this needs a manual multi-step rollback. The runbook note in `docs/api-compatibility.md` says to roll forward instead.

**Older code re-saving a project**: such code (`extra="ignore"`) drops `desired_outcome`, `archived_at` and the marker on any project it re-saves. The rollback window is therefore stated as losing outcomes edited by older code, as in the 020 plan's "Code rollback" note. The startup step (data-model E1) re-marks archives that lost `archived_at`; such a project still has its members, so the FR-027 line, which needs an empty project, stays hidden.
