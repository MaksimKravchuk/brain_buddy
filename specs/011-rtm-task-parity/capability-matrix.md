# Capability matrix: RTM task management vs BrainBuddy today

**Feature**: `specs/011-rtm-task-parity/`
**Audited base**: `origin/main` @ `87a93739573679f56f495e8722c620f0ec97ae22`
**Audit date**: 2026-08-15
**RTM reference**: portable 2026-08-15 source ledger and capability-group summary embedded
in `research.md` §Portable RTM reference provenance.

This file is the **single authoritative home** for "what BrainBuddy does today".
`spec.md`, `plan.md`, `tasks.md` and `analysis.md` cite row ids (`C-nn`) instead of
restating current behavior.

## How the audit was performed

Source-first read of `backend/app/api/tasks.py`, `backend/app/modules/tasks/`,
`backend/app/schemas/tasks.py`, `frontend/src/api/`, `frontend/src/features/tasks/`,
`mobile/src/api/`, `mobile/src/features/tasks/`, `mobile/src/app/`, plus two kinds of
executed evidence:

1. **Regression run** — `backend/.venv/bin/pytest tests/test_task_api.py
   tests/test_task_tag_project_mvp_api.py tests/test_task_lifecycle_detail_api.py
   tests/test_task_owner_isolation.py tests/test_task_smart_add_api.py -q`
   → **41 passed** (2026-08-15). The narrow-subset coverage floor failure is expected and
   not a behavior signal.
2. **Behavior probe** — a throwaway `TestClient` probe, never committed, that exercised
   each contested capability against the real app and recorded the observed
   status code / payload. Probe observations are quoted below as
   `probe: <observation>`. Every `PASS` row is backed by either a named existing test or a
   probe observation, never by reading code alone.

## Status vocabulary

- **PASS** — RTM-equivalent capability exists today and was observed working.
- **PARTIAL** — a usable path exists but diverges from the P0 target contract.
- **ABSENT** — no supported path; the probe observed a hard rejection.
- **DIVERGENT** — a path exists and works, but its semantics contradict the P0 target and
  changing it is a behavior change, not an addition.

`Slice` values are defined in `plan.md` (S1 core entities, S2 fields/lifecycle,
S3 search/history, P1 backlog, P2 decision).

## A. Task create and read

| ID | RTM capability | BrainBuddy evidence now | Status | Target parity | Slice | Acceptance evidence | Decision |
|---|---|---|---|---|---|---|---|
| C-01 | Create task (`rtm_add_task`) | `POST /api/tasks`, `backend/app/api/tasks.py:782`; `TaskService.create_task` `service.py:168`; requires `Idempotency-Key`. probe: `201` | PASS | keep | — | `backend/tests/test_task_api.py` (in the 41-passed run) | adopt as-is |
| C-02 | Create into a chosen List | `TaskCreateRequest.project_id`, `schemas/tasks.py:65`. probe: created task echoed `project_id` of the selected Project | PASS | keep | — | same run | adopt as-is |
| C-03 | Create via natural-language Smart Add | `POST /api/tasks/smart-add`, `api/tasks.py:581`; ADR-0007 makes it an explicit atomic command | PASS | keep, must not regress | S1–S3 | `backend/tests/test_task_smart_add_api.py` (in the run) | preserve; RTM Smart Add's `~ start`, `= estimate`, `* repeat` tokens stay P1 |
| C-04 | Read one task with full detail | `GET /api/tasks/{id}`, `api/tasks.py:604`; response embeds `subtasks` and `comments`, `schemas/tasks.py:185` | PASS | keep | — | `backend/tests/test_task_lifecycle_detail_api.py` (in the run) | adopt as-is |
| C-05 | Unknown / other-owner task is not disclosed | probe: `GET /api/tasks/task_does_not_exist` → `404` | PASS | keep | — | `backend/tests/test_task_owner_isolation.py` (in the run) | adopt as-is; 404-not-403 is the standing contract |

## B. Task field editing

| ID | RTM capability | BrainBuddy evidence now | Status | Target parity | Slice | Acceptance evidence | Decision |
|---|---|---|---|---|---|---|---|
| C-06 | Edit name | `PATCH /api/tasks/{id}` with `expected_revision`, `api/tasks.py:737`, `service.py:611` | PASS | keep | — | run above | adopt as-is |
| C-07 | Edit notes/details body | `TaskUpdateRequest.details`, `schemas/tasks.py:119` | PASS | keep | — | run above | adopt as-is |
| C-08 | Set/clear due **date** | `due_date: date`, `schemas/tasks.py:65,119`. probe: stored and echoed `2026-09-01` | PASS | keep | — | run above | adopt as-is |
| C-09 | Set/clear due **time** | probe: `POST /api/tasks` with `due_time` → **422** (strict schema rejects unknown field) | ABSENT | optional floating local time | S2 | new: `011-FR-004` backend + web + mobile tests | adopt, floating local time only |
| C-10 | Set/clear **start** date | probe: `start_date` → **422** | ABSENT | local calendar date | S2 | new: `011-FR-005` | adopt |
| C-11 | Set/clear **start** time | not modelled; follows C-10 | ABSENT | optional floating local time | S2 | new: `011-FR-005` | adopt |
| C-12 | Priority `1 \| 2 \| 3 \| N` | `TaskPriority = Literal["none","low","medium","high"]`, `schemas/tasks.py:15`. probe: `priority:"1"` → **422**; `priority:"high"` → accepted | DIVERGENT | public `1\|2\|3\|none` with negotiated rollout | S2 | new: `011-FR-006` + payload/mirror migration + installed-build gate | Max selected numeric priority on 2026-08-15; ADR-0020 supersedes ADR-0006 narrowly |
| C-13 | Replace the whole tag set | `TaskUpdateRequest.tag_ids`, full replace. probe: patching `tag_ids` to one id dropped the other | PASS | keep as the explicit replace verb | — | run above | adopt as-is |
| C-14 | Incremental add/remove of one tag | probe: `POST /api/tasks/{id}/tags` → **404**; only whole-set replace exists | ABSENT | add/remove preserving unrelated tags | S1 | new: `011-FR-009` | adopt; a client that only has replace will clobber concurrent edits |
| C-15 | Move task between Lists | `TaskUpdateRequest.project_id`, `service.py:645` | PASS | keep | — | run above | adopt as-is |
| C-16 | Estimate, URL | probe: `estimate` / `url` on create → **422** | ABSENT | P1 | P1 | `tasks.md` P1-01 | defer to P1 |
| C-17 | Repeat / recurrence | probe: `recurrence` on create → **422** | ABSENT | P1 | P1 | `tasks.md` P1-02 | defer to P1 |
| C-18 | Parent / subtask | `POST /api/tasks/{id}/subtasks` exists. probe: **201**. Flat one-level list, no `parent_task_id` on Task | PARTIAL | RTM-like nesting is P1 | P1 | `tasks.md` P1-03 | keep the existing flat subtask list in P0; nesting deferred |
| C-19 | Location | not modelled | ABSENT | P1 | P1 | `tasks.md` P1-08 | defer to P1 |
| C-20 | Assignee | not modelled | ABSENT | P2 decision | P2 | `p2-decisions.md` P2-03 | product decision, not a P0 gap |

## C. Task lifecycle

| ID | RTM capability | BrainBuddy evidence now | Status | Target parity | Slice | Acceptance evidence | Decision |
|---|---|---|---|---|---|---|---|
| C-21 | Complete | `POST /api/tasks/{id}/transitions {action:"complete"}`, `service.py:676`. probe: `200`, `state:"completed"` | PASS | keep | — | run above | adopt as-is |
| C-22 | Uncomplete / reopen | probe: `{action:"reopen", to_state:"next"}` → `200`, `state:"next"`; omitting `to_state` → `400` "Reopen requires a terminal task and an open destination." | PASS | keep the explicit destination | — | run above | adopt as-is; explicit destination is an ADR-0006 requirement and better than RTM's implicit restore |
| C-23 | Idempotent client retry of a lifecycle command | probe: replaying one `Idempotency-Key` with the same body returned a byte-identical `200` payload | PASS | keep, extend to new commands | S1–S3 | run above + new commands' own tests | adopt as-is |
| C-24 | Explicit invalid-transition behavior | probe: reopen on an open task → `400` with an actionable message; stale `expected_revision` → `409` | PASS | keep, extend to trash/restore | S2 | run above | adopt as-is |
| C-25 | **Trash** (soft delete) | probe: `{action:"trash"}` → **422** (not in the action enum); `DELETE /api/tasks/{id}` → **405** | ABSENT | orthogonal soft-deletion lifecycle, no automatic purge, explicit erasure only | S1 substrate, S2 guards | new: `011-FR-011`, `011-FR-012`, `011-FR-038` | adopt; **must not** reuse `cancelled` |
| C-26 | **Untrash** (restore) | follows C-25 | ABSENT | clear only Trash; preserve legitimate later List/Tag cleanup | S1/S2 | new: `011-FR-013`, `011-FR-039` | Max selected current-facts restore on 2026-08-15 |
| C-27 | Cancel (no RTM equivalent) | probe: `{action:"cancel"}` → `200`, `state:"cancelled"` | PASS | keep unchanged | — | run above | preserve; `cancelled` is a commitment outcome, not deletion |
| C-28 | Postpone + postponed count | probe: `POST /api/tasks/{id}/postpone` → **404** | ABSENT | P1 | P1 | `tasks.md` P1-05 | defer to P1 |
| C-29 | Undo a write by transaction id | not modelled; idempotency records exist but are not an undo log | ABSENT | not adopted | — | — | deliberately omit; restore (C-26) covers the destructive case users actually hit |
| C-30 | Task lifecycle must stay distinct from agent execution | `POST /api/tasks/{id}/agent-runs` is a separate resource, `mobile/src/api/client.ts:689`; no transition writes run state | PASS | keep as an invariant | S1–S3 | new: `011-FR-032` guard test | adopt as-is; this is the product's core separation |

## D. Lists (internally Projects)

| ID | RTM capability | BrainBuddy evidence now | Status | Target parity | Slice | Acceptance evidence | Decision |
|---|---|---|---|---|---|---|---|
| C-31 | Create list | `POST /api/projects`, `api/tasks.py:391` | PASS | keep | — | `backend/tests/test_task_tag_project_mvp_api.py` (in the run) | adopt as-is |
| C-32 | List all lists | `GET /api/projects`, `api/tasks.py:410`; returns **active only** (`service.py:859`) | PASS | keep, add an archived view | S1 | new: `011-FR-019` | adopt; archived Lists must be reachable to be unarchivable |
| C-33 | Read one list | `GET /api/projects/{id}`. probe: archived Project still returns `200` | PASS | keep | — | run above | adopt as-is |
| C-34 | Rename list | `PATCH /api/projects/{id}` | PASS | keep | — | run above | adopt as-is |
| C-35 | Archive list | `POST /api/projects/{id}/archive` → `200`, `state:"archived"` | PARTIAL | archive must retain membership | S1 | new: `011-FR-018` | see C-36 |
| C-36 | Archive **retains** membership | probe: after archiving, the member task's `project_id` was **`null`** — archive unassigns every member | DIVERGENT | retain `project_id`; hide from active navigation only | S1 | new: `011-FR-018` + archived PATCH/name tests | Max selected retained membership on 2026-08-15; ADR-0020 supersedes ADR-0006 narrowly |
| C-37 | Archived list blocks new assignment | probe: creating a task with an archived `project_id` → `400` "Task project must be active." | PASS | keep | — | run above | adopt as-is; matches the target contract already |
| C-38 | **Unarchive** list | probe: `POST /api/projects/{id}/unarchive` → **404** | ABSENT | restore to active navigation | S1 | new: `011-FR-017` | adopt |
| C-39 | **Delete** list | probe: `DELETE /api/projects/{id}` → **405** | ABSENT | confirmed/idempotent hard erase, atomically unassigns all members, redacted audit | S1 | new: `011-FR-020`, `011-FR-037` | adopt; erase name, never complete/trash/delete member tasks, never resurrect on replay |
| C-40 | Inbox is a system container, not a deletable list | `docs/projectless-inbox-contract.md`; server projection `state=inbox AND project_id IS NULL`. probe: `GET /api/tasks?state=inbox&unassigned_project=true` → `200` with `counts_by_state` | PASS | keep as a virtual view | — | `docs/projectless-inbox-contract.md` + run above | adopt as-is; there is no Inbox row to delete, so C-39 cannot reach it |
| C-41 | Smart Lists (saved searches) | not modelled | ABSENT | P1 | P1 | `tasks.md` P1-06 | defer to P1 |
| C-42 | Share a list / permissions | not modelled | ABSENT | P2 decision | P2 | `p2-decisions.md` P2-03 | product decision |

## E. Tags

| ID | RTM capability | BrainBuddy evidence now | Status | Target parity | Slice | Acceptance evidence | Decision |
|---|---|---|---|---|---|---|---|
| C-43 | Create tag | `POST /api/tags`, `api/tasks.py:491` | PASS | keep | — | run above | adopt as-is |
| C-44 | List tags with usage count | `GET /api/tags`; `TagResponse.open_task_count`, `schemas/tasks.py:57`. probe: a tag on one open task reported `open_task_count: 1` | PASS | keep; explicitly exclude Trash from open usage and distinguish delete-impact count | S1 | existing run + `011-FR-012` predicate tests | adopt and harden for Trash |
| C-45 | Rename tag | `PATCH /api/tags/{id}`. probe: `200` | PASS | keep | — | run above | adopt as-is |
| C-46 | Global delete removes the classification everywhere | `DELETE /api/tags/{id}?expected_revision=`, `service.py:1052`. probe: `200`, `state:"deleted"`, and the member task's `tag_ids` became `[]` while the task itself survived; the deleted row/payload still retains the name and replay can reconstruct it | PARTIAL | keep cleanup but hard-erase name/row/mirror and emit redacted audit receipt without resurrection | S1 | existing classification test + new `011-FR-023`, `011-FR-037` privacy/replay evidence | cleanup works; HD-06 makes retained-name deletion incomplete, but this does not add a canonical RTM gap |
| C-47 | Add/remove one tag on a task without disturbing others | see C-14 | ABSENT | incremental verb | S1 | new: `011-FR-009` | adopt |
| C-48 | Tag color / favourite | `ProjectDocument.color` exists; `TagDocument` has no color | ABSENT | not adopted in P0 | P1 | — | deliberately omit from P0 |

## F. Search, filters, history, ordering

| ID | RTM capability | BrainBuddy evidence now | Status | Target parity | Slice | Acceptance evidence | Decision |
|---|---|---|---|---|---|---|---|
| C-49 | Search by task name and details | `q` param, `api/tasks.py:802`; matched over `title` + `details` at `service.py:1562`. probe: a token present only in `details` returned exactly that task | PASS | keep | — | run above | adopt as-is |
| C-50 | Filter by List | `project_id`; `unassigned_project` for the Inbox projection | PASS | keep | — | run above | adopt as-is |
| C-51 | Filter by Tag | `tag_id` — **single** tag only | PARTIAL | OR within repeated `tag_id` | S3 | new: `011-FR-025` | adopt repeated-value OR |
| C-52 | Filter by status | `state`, `include_completed`, `include_cancelled` | PASS | keep, extend for trashed | S3 | run above + `011-FR-029` | adopt |
| C-53 | Filter by priority, OR within the field | `priority` is a repeatable query param, `api/tasks.py:802`. probe: `?priority=high&priority=medium` → `200` | PASS | keep under the new vocabulary | S2 | run above | adopt as-is |
| C-54 | Due today / overdue / range | `due_before`, `due_on`, `due_after` exist, but probe: sending two at once → `400` "Use only one due date filter at a time." A closed range is therefore not expressible | PARTIAL | today, overdue, and a closed range | S3 | new: `011-FR-025` | adopt a range; keep single-bucket shortcuts working |
| C-55 | "No due date" filter | probe: `?has_due=false` → `200` but **unfiltered** — the strict body schema does not apply to query params, so an unknown filter is silently ignored | ABSENT | explicit no-due filter | S3 | new: `011-FR-025, 011-FR-027` | adopt; silent-ignore is the worst failure mode here and the tests must assert rejection of unknown filters |
| C-56 | Start available / start in future | probe: `?start_before=…` → `200` unfiltered (same silent-ignore) | ABSENT | depends on C-10 | S3 | new: `011-FR-025` | adopt after start dates land |
| C-57 | Completed history | probe: `?include_completed=true&state=completed` → `200` with the completed task | PASS | keep, add trashed history | S3 | run above + `011-FR-029` | adopt |
| C-58 | Stable, documented order | `_sort_key`, `service.py:1585`; every mode ends in an `id` tie-break so order is total | PASS | keep, document publicly | S3 | run above | adopt as-is |
| C-59 | Pagination | probe: `?limit=1` returned `has_more:true` and a `next_cursor`; page two → `200` | PASS | keep | — | run above | adopt as-is |
| C-60 | Cursor bound to its filter set | probe: replaying a cursor under a changed `state` filter → **400** | PASS | keep, extend to new filters | S3 | run above | adopt as-is; new filters must join the cursor fingerprint or paging silently corrupts |
| C-61 | Typed filters compose with AND | `_filter_tasks`, `service.py:1440`, ANDs every predicate. probe: `?tag_id=…&priority=high` → `200` | PASS | keep and **document** | S3 | new: `011-FR-026` doc + test | adopt; today the semantics are true but unpublished |
| C-62 | Negation, grouping, saved queries | not modelled | ABSENT | P1 | P1 | `tasks.md` P1-06 | defer to P1 |

## G. Batch, notes, reminders

| ID | RTM capability | BrainBuddy evidence now | Status | Target parity | Slice | Acceptance evidence | Decision |
|---|---|---|---|---|---|---|---|
| C-63 | Batch complete / delete / move / tag / update (≤20) | probe: `POST /api/tasks/batch/complete`, `/batch/move`, `/batch/tag` all → **404** | ABSENT | P1 | P1 | `tasks.md` P1-04 | defer to P1; the partial-result contract is the hard part, not the loop |
| C-64 | Notes as a distinct container | probe: `POST /api/tasks/{id}/notes` → **404**; `POST /api/tasks/{id}/comments` → **201** | ABSENT | P1 | P1 | `tasks.md` P1-07 | defer to P1; comments exist and are not the same thing |
| C-65 | Reminders | not modelled | ABSENT | P1 | P1 | `tasks.md` P1-09 | defer to P1; this is where timezone/DST becomes real |

## H. Cross-tier parity

| ID | RTM capability | BrainBuddy evidence now | Status | Target parity | Slice | Acceptance evidence | Decision |
|---|---|---|---|---|---|---|---|
| C-66 | Owner isolation on every task surface | session cookie + per-owner filtering on all task routes; `backend/tests/test_task_owner_isolation.py` passed in the run | PASS | keep | S1–S3 | run above | adopt as-is |
| C-67 | Web can manage Lists and Tags | `frontend/src/features/tasks/TaskListPage.tsx` calls `createProject`, `updateProject`, `archiveProject`, `createTag`, `updateTag`, `deleteTag` | PASS | extend for unarchive/delete | S1 | new web tests per FR | adopt |
| C-68 | Mobile can manage Lists and Tags | `mobile/src/api/client.ts:424-482` has the endpoints, but `mobile/src/api/hooks.ts` exports **no** project/tag mutation hook; the only wired mutations are inline `createProject`/`createTag` in `mobile/src/app/task/[id].tsx:410-420` | PARTIAL | rename/archive/unarchive/delete reachable on mobile | S1 | new mobile tests per FR | adopt; this is the single largest tier-parity gap |
| C-69 | Same supported contract across the three tiers | web `frontend/src/api/taskTypes.ts:21` and mobile `mobile/src/api/types.ts:31` both mirror the backend's `low\|medium\|high\|none` and date-only `due_date` | PASS (consistent) | must migrate together | S2 | new: `011-FR-030` cross-tier tests | adopt; the vocabulary change is a three-tier lockstep change |
| C-70 | Voice Brain Dump / Smart Add / idempotency recovery unaffected | ADR-0002 substrate and `backend/tests/test_tasks_idempotency_repair.py`; Smart Add tests passed in the run | PASS | must not regress | S1–S3 | existing suites re-run per slice | preserve; regression here blocks the slice |

## Summary

| Status | Count | Rows |
|---|---|---|
| PASS | 38 | C-01…C-08, C-13, C-15, C-21…C-24, C-27, C-30…C-34, C-37, C-40, C-43…C-45, C-49, C-50, C-52, C-53, C-57…C-61, C-66, C-67, C-69, C-70 |
| PARTIAL | 6 | C-18, C-35, C-46, C-51, C-54, C-68 |
| DIVERGENT | 2 | C-12, C-36 |
| ABSENT | 24 | the rest |

Of the 24 ABSENT rows, **11 are P0** (C-09, C-10, C-11, C-14, C-25, C-26, C-38, C-39, C-47,
 C-55, C-56), 9 are P1, 2 are P2 decisions, and 2 are deliberate omissions (C-29
undo-by-transaction, C-48 tag color). Add the 2 P0 DIVERGENT rows (C-12, C-36) and the P0
total is **13 matrix rows**.

**Canonical P0 gap count is 12, not 13**, because C-14 and C-47 name the identical
capability — incremental tag add/remove — under two different RTM taxonomy sections (B and
E) and are one gap, not two. `spec.md` SC-001 enumerates the 12 explicitly: C-09, C-10,
C-11, C-12, C-14, C-25, C-26, C-36, C-38, C-39, C-55, C-56. `tasks.md` §Evidence map and
T-038 use that same 12-item list as their denominator. An earlier draft of this matrix and
of `spec.md` stated "11" without reconciling the DIVERGENT rows into the count; that
planning-analysis defect is corrected here.

No P0 gap is recorded as out of scope.

C-46's reclassification from PASS to PARTIAL does not change the frozen 12-gap RTM parity
denominator: its classification-removal capability already works, while Max's HD-06 adds
the privacy/audit completion criteria required for this feature's destructive semantics.
It is implemented and evidenced in Slice 1, not hidden or counted as a thirteenth RTM gap.
