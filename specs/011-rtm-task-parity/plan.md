# Implementation Plan: RTM task-management parity

**Feature**: `specs/011-rtm-task-parity/`
**Spec**: `spec.md` | **Design**: `design.md` | **Current behavior**: `capability-matrix.md`
**Research/campaign carry-forward**: `research.md`
**Branch**: `feat/011-rtm-task-parity`
**Base audited**: `origin/main` @ `87a93739573679f56f495e8722c620f0ec97ae22`

## Summary and readiness

Close the 12 canonical P0 gaps in `capability-matrix.md` without changing the frozen
P0/P1/P2 boundaries. Extend the existing native task module in three additive slices:
core organization and Trash substrate; fields/lifecycle plus staged priority; then
search/history. ADR-0020 records Max's priority/archive decisions. `design.md` B-01…B-04,
D-01…D-05 and M-01…M-04 are the user-visible authority.

Task-0 planning repair is complete only when campaign 2 is persisted. Product decisions
HD-01…HD-09 are settled, but this high-risk package has no run/digest-bound HD-10 human
sign-off. Therefore **implementation remains prohibited** unless campaign 2 ends
`approved` or valid `founder-accepted`; a technically clean unsigned high-risk campaign is
honestly `escalated` under ADR-0012.

## Technical context

**Runtime**: Python 3.11 / FastAPI / Pydantic / pytest; TypeScript strict / React / Vite /
React Query / Vitest / Playwright; Expo SDK 57 / React Native 0.86 / Jest plus the existing
mobile real-backend integration runner.

**Layering**: unchanged — `backend/app/api/tasks.py` →
`backend/app/modules/tasks/service.py` → `backend/app/modules/tasks/repository.py`, wired in
`backend/app/container.py`; routes receive services through `Depends()`.

**Actual task persistence topology**:

- SQLite `backend/data/tasks.sqlite3` is canonical after migration ledger entry
  `legacy-json-v1`.
- `projects`, `tags`, and `tasks` tables store whole Pydantic documents in a `payload` JSON
  column. Scalar columns (`state`, `project_id`, `order_key`, `created_at`, normalized name)
  are query/constraint compatibility fields, not the complete schema. Due/start, priority,
  and Trash fields belong in `tasks.payload`; this plan does **not** invent task-field
  `ALTER TABLE` columns.
- `task_tags` is the normalized membership mirror inside SQLite.
- `projects/`, `contexts/`, `tasks/`, `task-subtasks/`, `task-comments/`, and
  `task-commands/` are write-through compatibility JSON mirrors. Once `legacy-json-v1`
  exists they are never re-imported as a second authority, but they remain rollback data
  and must be rewritten/erased consistently.
- Feature 011 adds a SQLite `destructive_audit` table and a content-free
  `compatibility_mirror_outbox`/ledger. Audit columns are only `audit_id`, `owner_id`,
  `subject_id`, `action`, `occurred_at`, and `correlation_id`; action encodes the subject
  type. Neither table stores a name, title, request body, idempotency key, or content hash.

**Existing mechanisms reused**: owner command lock; session auth and 404-not-403 owner
filtering; `expected_revision`; owner-scoped `Idempotency-Key`; response
`X-Correlation-ID`; filter-bound opaque cursors. Correlation IDs remain observability
labels only.

## Constitution check

| Principle | Assessment after this repair |
|---|---|
| I. Data Consent & Safety | No provider or egress is added. Trash has no automatic purge. Irreversible task/List/Tag erasure is explicit, confirmed, idempotent and covered by a durable content-free audit that is exported, life-of-account, and purged with the account. Deleted names/content are absent from the audit. |
| II. Tested Delivery Across Stack | Every behavior has RED→GREEN backend/web/mobile ownership, cross-tier journeys, mobile real-backend evidence, mutation-tier-aware checks, and rendered acceptance evidence. |
| III. Contract-First Interfaces | Backend schemas and negotiated compatibility land before clients rely on them. SQLite payload/mirror topology, staged migration, crash recovery and inverse rollback are explicit. |
| IV. Traceable & Actionable Observability | Every success, replay and error carries a correlation ID; clients display it on failures. Audit/log records contain IDs/action/time only and never user text. |
| V. Responsive, Resilient, Mobile-First | `design.md` fixes exact copy, 390×851 behavior, interruption/refetch rules, modal focus/announcements, and SC-015 rendered evidence. |
| Spec-driven workflow | Full planning chain is present. Campaign 2 and HD-10 remain gates, not claims of readiness. |
| Operational guardrails | Implementation is high-risk and ASK-class; no automatic landing. This Task-0 commit is docs-only. |

## Contracts and invariants

### P0 idempotency, ownership and correlation

FR-015's P0 mutation inventory is exhaustive: Task create/update/transition/tag add/tag
remove/tag replace/trash/restore/permanent delete, Empty Trash, List create/rename/archive/
unarchive/delete, and Tag create/rename/delete. Each route requires an idempotency key and
executes the idempotency lookup, ownership check, mutation, response snapshot and transient
record under the owner command lock. The retry guarantee is 24 hours; same key/command/body
returns the identical response, and key reuse with different canonical input is `409`.

Deletion returns `DeletionReceipt`, never a serialized deleted Project/Tag/Task. The replay
path for a delete reads the transient record or durable audit receipt and **must not** call
the current `_project_result`/`_tag_result` reconstruction helpers. After 24 hours, a repeat
delete of the same owner/subject/action is a successful redacted no-op resolved from audit;
it cannot recreate the row or name. Create and ordinary updates retain the documented
24-hour retry boundary.

Every API test matrix includes success, same-key replay, key/body conflict, stale revision,
other-owner ID, absent ID, and correlation-header assertions. Other-owner and absent bodies
are identical `404`s. Web/mobile error states surface the response correlation ID; no route
accepts it as authorization or dedupe input.

### Archived List membership and name resolution

`GET /api/projects` keeps active-only default behavior and gains explicit
`state=active|archived|all`, ordered by normalized name then ID. Clients maintain an
owner/server-scoped all-List name-resolution map for task rendering and a separate
active-only selector. Archived IDs remain filterable and render their names.

Task validation distinguishes **carried** from **new** references:

- create or a PATCH changing to an archived List → `400`;
- PATCH omitting `project_id`, or explicitly repeating the task's same archived ID → valid;
- clearing membership or changing to an active owner List → valid;
- other-owner/absent IDs → indistinguishable `404`.

List archive changes only the List row and associated caches. Unarchive changes it back.
No historical member rewrite occurs. Existing archived Lists whose membership was already
cleared are not backfilled.

### Trash, restore and classification cleanup

Trash writes `trashed_at` in `tasks.payload` and its mirror without changing commitment
state. While trashed, direct PATCH, lifecycle transition, tag add/remove/replace and List
assignment reject with `400`; restore and confirmed permanent deletion are allowed.
List/Tag global deletion remains allowed to clear a reference from trashed tasks. Rename,
archive and unarchive affect name/container resolution without rewriting the Task.

Restore clears only `trashed_at`, increments revision, and returns current stored data. It
does not use a pre-trash snapshot and cannot resurrect a deleted List/Tag. Permanent delete
and Empty Trash remove tasks plus owned subtasks/comments and membership rows/mirrors,
append one audit receipt per erased task, and never run automatically.

### Exact query/count predicates and total orders

| surface | lifecycle/Trash predicate | classification behavior |
|---|---|---|
| default task list, search, filters, pagination | open states and `trashed_at IS NULL` unless an explicit terminal filter is selected | archived List members behave like active List members; Inbox remains `state=inbox AND project_id IS NULL` |
| completed/cancelled history | selected terminal state and `trashed_at IS NULL` | archived List ID/name remains resolvable/filterable |
| Trash | `trashed_at IS NOT NULL`, regardless of commitment state | current surviving List/Tag IDs; archived List names resolve |
| `counts_by_state` | open states and `trashed_at IS NULL`; ignores only the selected state filter | honors every other search/date/priority/List/Tag filter |
| Project open count / Tag open usage | open states and `trashed_at IS NULL` | counts only the named ID |
| List/Tag delete confirmation impact | every owner Task referencing the ID, including open, completed, cancelled and trashed | exactly the records the delete transaction will clear |
| export/internal owner read | no Trash exclusion | includes trashed tasks, archived Lists and audits; excludes permanently deleted content/names |

Task orders are exactly FR-028: manual/default `(order_key, created_at, id)`; due
`(dated-first, due_date, manual...)`; priority `(1,2,3,none, manual...)`; title
`(normalized_title, id)`; Trash `(trashed_at DESC, id ASC)`. Project/Tag collections use
`(normalized_name, id)`. Cursor fingerprints bind owner, normalized filters including all
repeated values, visibility mode, Trash/terminal mode, sort mode and last tuple. Any mismatch
is a sanitized `400`.

### Cache invalidation and interrupted clients

Backend has no new application cache. Web React Query and mobile classification/task
caches invalidate by affected owner/server root:

- Task create/update/transition/tag/List mutation → task list/detail, Inbox, selected
  history, cursor pages, open counts, Project/Tag counts;
- List/Tag rename/archive/unarchive/delete → active/archived/all resolution lists,
  selectors, task rows/details, matching filters and counts;
- Trash/restore/permanent delete/Empty Trash → default, terminal, Trash, Inbox, detail and
  classification counts.

No client waits for a periodic sweep. Offline/interrupted mobile preserves a visibly
pending intent, then refetches all affected roots before re-enabling retry. A server success
with a client refresh failure is a partial-refresh state, not a failed mutation or an
automatic replay.

## Persistence migration and rollback

### Additive task fields and audit schema

Due/start time, start date and `trashed_at` are backward-compatible defaults in the JSON
payload model. Old payloads load with null values; saves write the new schema to SQLite and
the task mirror. The only new SQL tables are the redacted audit and content-free mirror
outbox/ledger. Account export enumerates audit receipts; `TaskRepository.delete_all_for_owner`
deletes audit/outbox rows and their mirrors (if any) before the user record.

### Mirror-safe irreversible deletes

Under the owner command lock, delete calculates affected IDs without copying names into
audit/outbox, records a content-free intent, removes the classification/task mirror that
contains the soon-to-be-erased content, performs one SQLite transaction to clear all
payload/index references, delete the subject row, append audit, and persist the redacted
idempotency result, then regenerates affected Task mirrors from canonical SQLite and marks
the intent complete. Success is not returned until the mirror absence/read-back is verified.

If failure occurs before SQLite commit, the transaction rolls back and the missing mirror
is regenerated from the still-live canonical row. If process death occurs after commit,
startup and same-key retry drain the content-free intent before returning the receipt. No
path reconstructs a deleted resource from an idempotency response.

### Priority stages

1. **Stage 1 — dual compatibility.** Domain/request decoders accept words and numbers;
   storage remains legacy. Default/no-capability responses remain legacy. Web/mobile readers
   handle both, use exact numeric labels, and show `Priority unavailable` for unknown values
   without coercion. Current builds advertise capability for verification only.
2. **Operational gate (owner: Max as release operator).** A dated
   `priority-rollout-evidence.json` records candidate backend SHA/build ID, web build ID,
   every active installed mobile build ID/device slot, verifier, and read/edit/filter/sort
   result. “Active internal” is the explicit inventory Max uses for BrainBuddy; an unknown,
   omitted, merely released, or unverified installed build makes the gate fail closed.
3. **Stage 2 — numeric default.** Set a content-free ledger state `in_progress`; under
   owner locks rewrite every SQLite task payload using the bijection, regenerate all Task
   mirrors from SQLite, compare model values in memory without logging content/hashes, mark
   the ledger complete, then switch default responses to numeric. Legacy request and
   no-capability response fallback remain.
4. **Stage 3 — close compatibility.** After a second complete inventory check, reject
   legacy requests and remove the legacy response fallback.

A crash in stage 2 resumes from the ledger; dual-read code can load either vocabulary.
Rollback first disables the numeric default, runs the inverse rewrite over SQLite, rebuilds
and verifies every mirror, marks the rollback ledger complete, and only then permits an
older backend/client. No image rollback may precede the inverse rewrite. Because the mapping
is bijective, no priority information is lost.

## Project structure

```text
backend/app/
├── schemas/tasks.py                       # negotiated priority + new request/response shapes
├── modules/tasks/domain.py                # JSON-payload fields + redacted receipt/audit models
├── modules/tasks/repository.py            # canonical SQLite, audit/outbox, mirror repair/migrations
├── modules/tasks/service.py               # semantics, predicates, replay without resurrection
├── api/tasks.py                            # strict routes/query negotiation/correlation behavior
└── services/account_service.py            # export audit + archived/trashed data

frontend/src/api/                           # strict contracts, capability negotiation, invalidation
frontend/src/features/tasks/                # D-01…D-05
mobile/src/api/ and mobile/src/features/    # M-01…M-04, resume/refetch, dual reader
mobile/integration/                         # real-backend P0 journeys

docs/api-compatibility.md                   # rollout, filters, order/pagination, divergences
docs/data-retention.md                      # Trash/audit/mirror retention, purge, export
frontend/src/pages/PrivacyPolicyPage.tsx    # synchronized user-facing retention/erasure text
```

## Slice plan and dependencies

`tasks.md` is authoritative for task IDs and exact dependencies.

1. **T-000/T-001/T-002 planning and regression foundations** precede product work. ADR-0020
   already exists; implementation first verifies the preserved-capability baseline and
   writes shared contract/migration tests.
2. **Slice 1 — organization, audit and Trash substrate**: backend contract/repository/
   service first; then web hooks/surfaces; then mobile hooks/surfaces and real-backend
   evidence. It resolves archived PATCH/name behavior, delete-without-resurrection,
   content-free audit/export/purge, cache invalidation and exact counts.
3. **Slice 2 — fields, Trash lifecycle and priority rollout** depends on Slice 1's audit/
   substrate. Stage 1 backend precedes dual-reader clients; the operational evidence gate
   precedes stage 2; stage 3 is separately gated. Date fields and trash/restore/erasure do
   not bypass those stage edges.
4. **Slice 3 — search/history/order/pagination** depends on Slice 2 fields. Backend
   predicates/cursors precede web/mobile controls, then cross-tier and mobile real-backend
   journeys.
5. **Closeout** updates API/retention/privacy docs, captures SC-015 rendered evidence,
   re-walks the 12 gaps, and runs the full repository verification chain.

`[P]` is used only for tests or client work that consumes an already-landed contract and
does not share files/state. Web and mobile implementation are not marked parallel with the
backend contract they consume; Playwright and real-backend journeys wait for both clients.

## Evidence strategy

- **Backend**: FastAPI TestClient plus repository/service tests. Each acceptance test uses
  `011_FR_nnn` naming and the Allure helper. Deletion/migration tests crash at each boundary
  and prove recovery, mirror consistency, no resurrection, export and purge.
- **Web**: Vitest/Testing Library for every D state and cache invalidation; Playwright for
  archive/unarchive, trash/restore/erasure, ordering/pagination and exact focus/copy.
- **Mobile**: Jest for every M state, dual-priority fallback, cache invalidation and
  VoiceOver/TalkBack focus metadata; `mobile/integration/` against the real backend for List/
  Tag management, every task field, lifecycle, Trash, filters, pagination, owner isolation,
  correlation IDs, retry and interrupted-resume read-back.
- **Cross-tier contract**: one fixture table drives backend schema, web decoder and mobile
  decoder for every P0 field/value/error. A separate journey matrix in `tasks.md` covers all
  user-facing FR-001…FR-039 outcomes, not only the 12 gaps.
- **Operational**: Max owns stage-2/stage-3 priority inventory evidence. Local automated
  tests cannot substitute for installed-build verification.
- **Mutation**: only `backend/app/modules/tasks/repository.py` is in ADR-0016's **observed**
  task scope today; no task-module file is in `backend/mutation-enforced-scope.txt`.
  Repository mutations are reported by the nightly observed run; normal coverage/tests gate
  all changed files. This feature does not silently promote or weaken mutation tiers.
- **Regression**: Voice Brain Dump, Smart Add and idempotency-recovery suites run at every
  slice gate. Final verification uses `make verify-all` and keeps local review/CI/landing/
  deploy evidence distinct.
- **Rendered acceptance**: screenshots for D-01…D-05/M-01…M-04 and a keyboard plus
  screen-reader video are required before acceptance, per HD-09/SC-015.

## Risk, delivery and residual human gate

**Risk: high (derived).** The implementation plans destructive erasure, a new SQLite audit
table, payload migration and ASK-class `backend/app/api/tasks.py` changes. Every
implementation slice is ASK-class and cannot land automatically.

The Task-0 docs repair makes no product/runtime/auth/secret/infrastructure change. Campaign
2 must review the repaired digest with all six lenses. If it is technically clean but no
valid `.specify/workflows/runs/<campaign-2>/human-signoff.json` exists, the only honest
terminal verdict is `escalated`; Max must review that exact digest/run and either supply the
record or decline. The HD-01…HD-09 message may not be transformed into HD-10.

## Campaign-1 disposition

`research.md` carries every campaign-1 blocking, important and advisory finding with its
repair location. All 15 blocking findings are resolved in the planning package; all 18
important findings have an explicit resolved or accepted disposition. Campaign 2 receives
that file through the review harness so resolved defects are carried forward rather than
silently forgotten or re-litigated without context.

## Complexity tracking

| Departure | Why necessary | Simpler alternative rejected because |
|---|---|---|
| ADR-0020 narrows ADR-0006 | Founder selected numeric priority and lossless archive | Silent drift would erase decision history; clearing makes unarchive empty |
| Trash is orthogonal | Preserves commitment outcome separately from deletion | Reusing `cancelled` destroys recoverability and meaning |
| Redacted durable audit + mirror outbox | Constitution requires auditable irreversible erasure across a non-transactional mirror topology | 24-hour idempotency alone is not durable; logging names/content violates privacy |
| Negotiated staged priority | Mobile cannot update in lockstep and storage has two representations | One-shot rewrite can strand stale builds and makes rollback a read outage |
| Strict unknown-filter rejection | Silent ignore returns a confident wrong answer | Keeping permissive parsing makes unsupported filters undetectable |
