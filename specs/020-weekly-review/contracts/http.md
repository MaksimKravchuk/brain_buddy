# HTTP contract: Weekly Review (020)

**Base**: every path is under `config.api_prefix` (`/api`), session-cookie
authenticated (`Depends(get_current_user)`, 401 without a session), owner-scoped.
**Routers**: three new routers, all `APIRouter(tags=["review"])`:
`backend/app/api/review.py` (§3 – §5), `backend/app/api/review_navigator.py` (§7) and
`backend/app/api/review_flow.py` (§6). All three are mounted in
`backend/app/api/__init__.py` beside `task_router` by slice PR-02 (each mounting an
empty router until its own slice fills it), so later slices add only their own files.
Services come from
`Depends(get_task_service)` / `Depends(get_review_service)` (new provider in
`backend/app/api/dependencies.py`). No route touches a repository.

**Gate** (exposure control is not authorization — the rule of
`require_voice_brain_dump_enabled`, `dependencies.py:361-385`): the new
`require_weekly_review_enabled` dependency gates **exposure only**. When `weekly_review`
is not effective for the caller, a gated route returns **404**
`{"message": "Not found", "detail": {"reason": "weekly_review_disabled"}}`. Routes fall
in three groups:

| group | routes | flag OFF |
|---|---|---|
| exposure (gated) | `GET /review/state`, `GET /review/queues/{step}`, `GET /review/sessions/{id}`, `POST /review/navigator/suggestions`, `POST /review/navigator/consent` (grant) | 404 `weekly_review_disabled` |
| finishing work a client already started (not gated; `get_current_user` only) | `POST /tasks/{id}/decisions`, `POST /review/decisions/{id}/undo`, `POST /tasks/{id}/auto-park`, `POST /review/explainer/acknowledge`, `PUT /review/settings`, `POST /review/parks/acknowledge`, `POST /review/sessions`, `PATCH /review/sessions/{id}`, `POST /review/sessions/{id}/finish`, `POST /review/bulk-releases`, `POST /review/bulk-releases/{id}/undo` | accepted as when ON, except `POST /tasks/{id}/auto-park`, which answers `200 {"applied": false}` and parks nothing while the flag is off |
| privacy authority (never gated) | `GET /review/navigator`, `DELETE /review/navigator/consent` | work as when ON, so a stored cloud consent can always be seen and revoked (FR-024) |

So turning the flag off for rollback hides the feature (clients read the flag and show
"coming later"; the sweep's exposure part is inert) but never makes a device's queued
decisions, sessions or acknowledgements fail and be set aside (constitution: confirmed
records must avoid data loss). Each not-gated route only changes the caller's own
records, exactly as the equivalent task commands do. Activation (data-model E2,
FR-016) happens only through `POST /review/explainer/acknowledge` (§5, FR-051), never
as a side effect of another call or of the sweep; an acknowledgement that arrives while
the flag is off still records `activated_at`, and the sweep-gap floor (§9) covers the
time until the flag is on again.

**Envelope** (unchanged, `backend/app/schemas/api.py` `ErrorResponse`):
`{"message": str, "detail": object | null, "reference_id": "<correlation id>"}` plus
the `X-Correlation-ID` header on every response, success or failure (FR-045).

**Mutations** require `Idempotency-Key` (400 without it, as today), except
`POST /review/navigator/suggestions`, which is a read-like call (§7). A replay with the
same key and body returns the original response; a different body → 409
`{"reason": "idempotency_conflict"}`. The Idempotency-Key is the **only** replay input;
a client-supplied record id never is (below). Concurrency uses `expected_revision` in
the body.

**Ownership**: an id in the path that does not exist **or belongs to another owner** →
404 with `{"resource": "...", "id": "..."}` (existing `NotFoundError` mapping). Never
403. The same holds for an id in a **query parameter** (`session_id` on
`GET /review/queues/{step}`): unknown and foreign give the same 404
`{"resource": "review_session", "id": …}` body. **Task ids inside a request body**
(bulk-release `items`, `set_aside_task_id`, park acknowledgements) never produce a
404: an id that does not exist and an id of another owner are treated identically
(reported as `not_eligible`, or ignored), so the response is byte-identical for both
and cannot be used as an existence oracle across owners. `second_api_client` tests
assert this per endpoint, including the queue endpoint.

**Client-supplied ids** (new with this feature: no existing task route accepts a
client id today — `TaskCreateRequest`, `backend/app/schemas/tasks.py:99-118`, has
none and `create_task` mints `generate_id("task")`): offline iOS creates sessions,
decisions, bulk releases, follow-up tasks and formulations before the server sees
them, so those requests carry the client's id (`id`, `decision_id`,
`follow_up_task_id`, `new_formulation_id`). Every such id is an opaque label of one
fixed shape, validated by the Pydantic schema (422 on mismatch):
`^(review|decision|bulk|form|task)_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`
with the prefix fixed per field (`id` of a session `review_`, `decision_id`
`decision_`, bulk `id` `bulk_`, `new_formulation_id` `form_`, `follow_up_task_id`
`task_`), at most 64 characters, so no free text can travel in an id into tables,
exports or logs (iOS lowercases `UUID().uuidString`). Fields that refer to an existing
record (`session_id`, `formulation_id`, task ids in bodies) accept either that shape or
a server-minted id (`<prefix>_<12 hex>`, `app/utils/identifiers.py`), and nothing else. `navigator_request_id` on a decision is either null or exactly the
36-character UUID the server returned as `request_id` (the
`TitleCompletionAcceptedRequest.request_id` pattern, `schemas/tasks.py:49`). The
server adopts a supplied id when it creates the record. Ids are labels only, never
authorization or idempotency inputs (constitution IV): a request that reuses an id
already held by a record of the same owner, under a different Idempotency-Key, is 409
`{"reason": "id_conflict"}` and changes nothing, unless the stored record matches the
request (below); only the same Idempotency-Key with the same body replays. When no id is supplied (web, older clients), the server mints one
(`generate_id`).

**Retry after the idempotency retention** (owner decision 2026-10-06, offline-sync
checklist CHK023): the server keeps idempotency records for 24 h
(`IDEMPOTENCY_RETENTION`, `backend/app/modules/tasks/repository.py:39`). A device whose
response was lost and that stays offline longer retries with the same
Idempotency-Key, which the server no longer knows, and an id the earlier delivery
already stored. When the stored record **matches** the retry, the server treats the
retry as already applied: it changes nothing and answers with the success status and
response shape of a first delivery, built from the stored record and the task as it
now is. A match means the same owner, the same record kind and the same identifying
fields: a decision (`decision_id`) with the same `task_id`, `type` and decided-on
`formulation_id`; a session (`id`) with the same `mode` and `origin`; a bulk release
(`id`) with the same `kind` and the same set of task ids. Only a record that does not
match is `id_conflict`. A record that no longer exists (for example a decision undone
since) is not matched; the request is then processed as new, and its own preconditions
(`expected_revision`, eligibility) decide the outcome. Within the 24 h the ordinary
Idempotency-Key replay applies, as before. A pytest case sends a content-bearing id (sentinel text) and asserts
422 and that the sentinel reaches no log record.

**Logs** (FR-044): one structured line per request on logger `app.modules.tasks.review`
or `app.api.review` with `owner_id`, ids, decision type, counts, `duration_ms`, outcome
code. Never titles, notes, waiting-for text, extension reason, clarifying answers,
proposal text or navigator input. The stall reason is **not** logged either (one reason
is behaviourally sensitive and platform logs outlive account purge); its distribution is
computed from `review_decisions`, which purge removes. Errors are logged as
`type(exc).__name__` plus a reason code, never `str(exc)`, `repr(exc)` or a validation
error's `errors()` (a Pydantic or SQLite error renders input values such as a title or
an extension reason); this applies to routes and to the sweep (§9).

## 1. Existing contract preserved

- `GET/POST/PATCH /tasks…`, `/projects…`, `/tags…` keep their paths, methods, request
  bodies and status codes. Old clients that never send the new fields keep working.
- `TaskResponse` gains two nullable fields (§2). Older iOS builds decode `TaskDTO`
  with its hand-written `init(from:)` (`ios/BrainBuddyKit/Sources/BrainBuddyAPI/WireModels.swift:227-248`),
  which reads only known keys and so ignores unknown ones; older web code ignores them.
- `POST /tasks`, `PATCH /tasks/{id}` and `POST /tasks/{id}/transitions` additionally
  maintain the formulation clock (`contracts/formulation-clock.md` §3). No new request
  field is required. One optional field is added to all three: `new_formulation_id`
  (`form_…`), used only when the request starts a formulation (create in Next, move or
  reopen into Next, substantive title change in Next); otherwise it is ignored. iOS
  sends the id its reducer minted so device and server agree; the web omits it.
- There is **no** `client_occurred_at` and no yield rule on these endpoints: only a
  card decision (§3) yields to an auto-park. A plain edit or move queued offline
  against a task the server has since parked gets the ordinary 409, and the iOS
  refetch/replay path re-applies it to the task as it now is (a notes edit lands on the
  parked task, which stays parked; a move to Waiting moves it out of Someday). Nothing
  is set aside and no park is reversed by a non-decision edit.

## 2. Task response additions (`backend/app/schemas/tasks.py`)

```json
"formulation": {
  "id": "form_…",
  "started_at": "2026-09-24T09:14:00Z",
  "extended_at": null,
  "extension_reason": null,
  "park_floor_at": null,
  "consecutive_stalled": 0,
  "ageing_at": "2026-10-01T09:14:00Z",
  "ask_at": "2026-10-08T09:14:00Z",
  "park_due_at": "2026-10-15T09:14:00Z",
  "paused_until": null
},
"parked": {"at": "2026-10-08T09:14:03Z", "formulation_id": "form_…"}
```

`formulation` is `null` unless the task is in Next with a started clock. `ageing_at`,
`ask_at`, `park_due_at`, `paused_until` are derived with the owner's settings at
response time and are **advisory for display**; clients never send them back. They are
`null` while the owner is not activated (formulation-clock §2), so no client shows a
marker before the explainer was seen. The web classifies with
`classifyFromInstants(now, instants)` and needs no other rule. `parked` is set only by
auto-park; its `clock_before` snapshot stays server-side and is not in the response.

**Where the projection is computed**: the pure `formulation.derive_instants(task,
settings, now)` produces the instants; `TaskService.formulation_views(owner_id, tasks)`
reads the owner's `review_settings` once per request (through the review repository
mixin) and returns one `TaskFormulationView` per task. The document → schema mapping
moves from the router-private `_to_response` (`backend/app/api/tasks.py:1183`) to a
public `task_response(task, *, subtasks, comments, formulation)` in a new
`backend/app/api/task_mapping.py`, used by both `api/tasks.py` and `api/review.py`
(which returns `TaskResponse` inside `DecisionResponse`), so no router imports
another router's private symbol. The `api/tasks.py` (ASK) diff is therefore limited to
importing that mapper, passing the views, and accepting `new_formulation_id`.

## 3. Decisions

### `POST /tasks/{task_id}/decisions` → 200 `DecisionResponse`

```json
{
  "decision_id": "decision_6b1e…",
  "type": "first_step",
  "expected_revision": 7,
  "formulation_id": "form_…",
  "stall_reason": "too_big",
  "title": "Measure the bathroom wall",
  "waiting_for": null,
  "reason": null,
  "session_id": "review_…",
  "ai_use": "edited",
  "navigator_request_id": "4f0c…",
  "client_decided_at": "2026-10-09T14:05:12Z",
  "new_formulation_id": "form_9d2a…",
  "follow_up_task_id": null
}
```

`decision_id` is the client's id (optional; minted by the server when absent; §
"Client-supplied ids"). `new_formulation_id` names the formulation the decision starts
(`reformulate` when substantive, `first_step`, `return_to_next`, and the follow-up
task of `follow_up`). `follow_up_task_id` is the client id of the task `follow_up`
creates.

| `type` | allowed when task is | required fields | task effect | summary counter (`review_counts_as`) |
|---|---|---|---|---|
| `complete` | open | — | `transition complete` | `done` |
| `reformulate` | next | `title` | title update; new formulation iff substantive; a cosmetic-only save ("Save anyway") is still a recorded decision with `substantive: false` and no clock change (FR-002) | `reformulated` |
| `first_step` | next | `title` | title = new; details = `"Was: <old title>"` + (`"\n\n"` + old details if any); always a new formulation (FR-008) | `first_step` |
| `waiting` | next | `waiting_for` | move to waiting | `waiting` |
| `someday` | next | — | move to someday (`parked = null`; a person's release is not a park); writes a Someday receipt (+30 d, `source: release`, FR-032) | `someday` |
| `cancel` | open | — | cancel | `cancelled` |
| `extend` | next, class `asks`, `moves_tomorrow` or `park_due` (park not yet applied), not yet extended | `reason` (1..500) | sets extension (FR-009); the reason is also kept on the decision (data-model E4) | `extended` |
| `keep_waiting` | waiting | — | none; writes receipt (+7 d) | `kept` |
| `follow_up` | waiting | `title` | creates a Next task in the same project; writes receipt on the original | `moved_to_next` |
| `return_to_next` | waiting or someday | `title` | move to next (+ title if changed) | `moved_to_next` |
| `keep_someday` | someday | — | none; writes receipt (+30 d) | `kept` |

Inbox items processed in the review are ordinary task commands (as Process inbox
does today) and count as `inbox_processed` through the session's
`inbox_processed_delta` (§6). Session counts are the ten summary counters of FR-033:
`done, reformulated, first_step, waiting, someday, cancelled, extended,
inbox_processed, kept, moved_to_next`.

`formulation_id` is required for the Next-only types and must equal the task's
current formulation, otherwise the decision is stale.

`session_id`: a decision naming a session that exists for the owner is linked to it and
counted, whether the session is open or already finished (an offline review's decisions
can arrive after another device finished it). A decision naming a session id the server
does not know for this owner is recorded **without** a session (200, `session_id: null`
in the response), never 404, so an offline decision is never lost (SC-007).

Response:

```json
{
  "decision": {"id": "decision_…", "type": "first_step", "task_id": "task_…",
               "session_id": "review_…", "decided_at": "…", "substantive": true,
               "stall_reason": "too_big", "ai_use": "edited"},
  "task": {"…": "TaskResponse"},
  "created_task": null,
  "receipt": null,
  "session_counts": {"done": 0, "reformulated": 0, "first_step": 1, "…": 0}
}
```

Errors:

| status | `detail.reason` | when | user-visible (design) |
|---|---|---|---|
| 409 | (existing `ConflictError`, message "…has newer changes; reload before saving.") | revision or formulation mismatch, unless the yield rule applies | M-03 stale, D-02 stale "Task changed elsewhere" |
| 400 | `decision_not_allowed` | type not allowed for the task's state | "This decision isn't available for this task's current list. Nothing was changed." + Ref (M-03 / D-02 "decision not allowed") |
| 400 | `extension_already_used` / `extension_not_due` | FR-009 | card hides the option; server is the backstop |
| 400 | `project_archived` | `follow_up`/`return_to_next` into an archived project | M-18 archived, M-09 partial |
| 404 | `{resource, id}` | task not found or not owned (path id) | |
| 409 | `id_conflict` | a supplied client id is already used by a record that does not match this request ("Retry after the idempotency retention": a matching record answers 200 as already applied) | iOS sets aside with Ref (cannot happen with UUIDs in practice) |
| 422 | (validation) | missing/oversized fields | |

**Auto-park yield rule** (spec edge case "Offline for a long time"): the precondition is
formulation-based, not revision-equal, because iOS sends `expected_revision` from the
base record at push time and replays queued plain edits onto a parked task first (a
notes edit queued before the decision 409s, is replayed onto the parked task and
raises its revision, `SyncEngine+Push.swift` `refetch`). The rule applies when the task
is currently parked for the decision's formulation (`parked` set,
`parked.formulation_id == formulation_id`), `parked.from_revision <= expected_revision
<= task.revision` (every revision above `from_revision` on a parked task comes from the
park itself or from clock-free edits, because the formulation is closed), and
`client_decided_at < parked.at`. Then the server reverses the park by restoring
`parked.clock_before` exactly
(formulation-clock §3 "yield reversal": same formulation id, stalled count restored, the
formulation is not closed a second time) and applies the decision in the same
transaction. The decision is then evaluated against the restored task, so an `extend`
made offline before the park is accepted although the restored class is `park_due`.
The response is a normal 200; the decision carries `"yielded_auto_park": true`. Edits
replayed onto the parked task in between (notes, tags) are kept, because the decision
applies to the task as it now is. `client_decided_at` is used for nothing else. Test:
offline notes edit → offline card decision → server park between them → push: notes
kept, decision applied with `yielded_auto_park: true`, zero sync issues
(`test_review_auto_park.py`, `ReviewSyncTests`).

### `POST /review/decisions/{decision_id}/undo` → 200

Body `{"expected_task_revision": 8}`. Response `{"task": TaskResponse,
"undone_decision_id": "decision_…", "deleted_task_id": null, "session_counts": {…}}`.
409 `{"reason": "undo_unavailable"}` when the task changed since the decision, when a
follow-up task created by the decision changed since it was created (its revision is
stored on the decision, data-model E4), or when the undo snapshot was already purged
(7 days). Clients show "Couldn't undo: "<title>" changed on another device. It's in
<list> now." + Ref (design "Undo didn't apply" states). 404 when not owned or already
undone.

## 4. Auto-park

### `POST /tasks/{task_id}/auto-park` → 200

Body `{"formulation_id": "form_…"}`. Used by iOS for parks observed on the device.
The server re-evaluates with its own clock and settings under the owner lock and parks
**iff** the flag is effective for the owner (otherwise `applied: false`, see "Gate"),
the owner is activated, the task is in Next, its classification is `park_due`,
and it is not already parked for its current formulation. Response `{"applied": bool, "task": TaskResponse}`.
`applied: false` is a success, never a conflict (FR-013, US2-6). No
`expected_revision` is taken. FR-013's "applying it twice has no effect" is a **state**
rule (re-checked under the lock), not an idempotency-record rule.

Server sweep: `ReviewService.run_auto_park_sweep(now)` applies the same command with
the deterministic idempotency key `auto-park:<task_id>:<formulation_id>:<from_revision>`
(§9), where `from_revision` is the task revision the park is applied from. A yield
reversal keeps the formulation id, so a formulation can legitimately become `park_due`
again within the 24 h idempotency retention (yield followed by a cosmetic "Save
anyway", or by a decision and its Undo); the revision in the key makes that second
park a new command instead of a replay of the first (which would leave the task in Next
showing "Moves to Someday tomorrow", or raise an idempotency conflict on every run).
The `auto-park:` result reconstructor re-applies a stored parked task only while the
current task is still in Next at `from_revision`; otherwise it does nothing (it never
writes the stored Someday snapshot over a restored task).

## 5. Review state and settings

### `GET /review/state` → 200

```json
{
  "settings": {"threshold_days": 14, "review_weekday": 5, "review_time": "16:00",
               "time_zone": "Europe/Berlin", "onboarded_at": null,
               "activated_at": "…", "owner_park_floor_at": null, "revision": 3},
  "explainer_seen": true,
  "grace_until": "2026-10-19T08:00:00Z",
  "last_counted_review_at": "2026-09-30T15:40:00Z",
  "last_counted_review": {"session_id": "review_…", "status": "completed",
                          "origin": "ios", "ended_at": "2026-09-30T15:40:00Z",
                          "counts": {"done": 3, "…": 0}, "clear_start": "yes"},
  "next_review_at": "2026-10-09T14:00:00Z",
  "restart_mode": false,
  "open_session": null,
  "unseen_parks": [{"task_id": "task_…", "formulation_id": "form_…", "parked_at": "…"}],
  "counts": {"asks_for_decision": 4, "moves_tomorrow": 1},
  "receipts": [{"task_id": "…", "kind": "waiting", "hidden_until": "…", "task_revision": 4}],
  "server_now": "2026-10-09T14:02:00Z"
}
```

`server_now` lets clients detect clock skew (R9). `explainer_seen` is
`activated_at != null`; while it is false clients show the explainer (M-26 / D-05)
at app or web open and no markers. `grace_until` = `activated_at + 14 d` (copy in
M-26, D-05 and M-12). `counts.asks_for_decision` is the aggregate of
formulation-clock §5 (it includes `moves_tomorrow` and not-yet-applied `park_due`);
`moves_tomorrow` is the subset. `last_counted_review_at` considers only counted
reviews (completed and partial, and an open session with qualifying activity,
data-model E3). `last_counted_review` is the summary of the most recent completed or
partial session (null when there is none); the web shows it on the `/review` entry
(design D-03 "entry: last review summary"), which is how a review completed offline on
iOS becomes visible on the web (SC-007). `restart_mode` is
`onboarded_at != null and now - coalesce(last_counted_review_at, onboarded_at) >= 21 d`
(FR-017): a person who has not onboarded gets onboarding first and no restart mode, and
one who onboarded but never had a counted review counts from onboarding.

`server_now` has one consumer: signed-in iOS keeps the last observed offset between
`server_now` and its own clock and evaluates due parks with the adjusted clock
(ios-commands §5).

### `POST /review/explainer/acknowledge` → 200 state (FR-051)

Body `{"time_zone"?: IANA name}`. Idempotent and first-wins: when `activated_at` is
null it is set to the server's `now` and the activation transition of
formulation-clock §3 runs under the owner lock in the same transaction; when it is
already set nothing changes. Either way the response is the current
`GET /review/state` body. Clients call it when the person dismisses the explainer and
send the device's zone with it, so due-dated tasks are classified in the person's zone
from activation on rather than in `UTC` until onboarding (weeks later). The supplied
zone is stored by the activating acknowledgement only (400 `invalid_time_zone` for a
non-IANA name); a later or duplicate acknowledgement changes nothing, its zone
included (FR-051). **Zone changes afterwards** (owner decision 2026-10-06, offline-sync
checklist CHK016): a client sends a `PUT /review/settings` zone change only when **its
own** zone changes, i.e. the device's current zone differs from the zone that device
last observed (iOS `local.lastObservedTimeZone`, web
`bb.reviewLastZone.v1.<origin>.<account>`; data-model E10, E11). A device whose zone
merely differs from the stored one (another device elsewhere set it) sends nothing, so
two signed-in devices in different zones never alternate the setting and never raise
the FR-046 floor repeatedly. Onboarding sends the onboarding device's zone (FR-035).
iOS queues the acknowledgement offline like any other command. It is the only way an owner becomes
activated. Not gated by the flag (see "Gate").

### `PUT /review/settings` → 200 settings

Body: any of `threshold_days`, `review_weekday`, `review_time`, `time_zone`,
`onboarded: true`, plus `expected_revision`. 409 on revision mismatch (iOS: refetch
`GET /review/state`, re-apply only the fields this change set, resend; see
ios-commands §4). 400 `{"reason": "invalid_time_zone"}` for a non-IANA zone. A
threshold change sets `owner_park_floor_at = now + 7 d` (FR-039). A `time_zone` change
applies the due-date floor to due-dated Next tasks (formulation-clock §3).

### `POST /review/parks/acknowledge` → 204

Body `{"items": [{"task_id": "…", "formulation_id": "…"}]}` (≤ 200). Idempotent;
unknown or foreign ids are ignored (no existence leak). Closing M-09 / the web dialog
without "Continue" sends nothing (the parks stay unseen).

## 6. Sessions and queues (increment 3)

| method | path | body | response |
|---|---|---|---|
| POST | `/review/sessions` | `{id?, mode, entry, origin, skip_steps?: [step], replace_open: bool}` | 201 session; with `replace_open` an open session is finished first (partial or abandoned by the E3 rule; the device that had it shows "review ended elsewhere"); without it and an open session exists → 409 `{"reason": "open_session_exists", "session_id": …}`. Replay is by Idempotency-Key only ("Mutations"); an `id` already used under another key → 409 `id_conflict`, unless the stored session matches (same `mode` and `origin`), which answers as already applied ("Retry after the idempotency retention"). iOS always pushes an offline-started session with `replace_open: true` (ios-commands §4) and keeps its key until the request succeeds, so a queued review is never set aside |
| GET | `/review/sessions/{id}` | — | session |
| PATCH | `/review/sessions/{id}` | `{current_step?, step?: {code, status}, active_seconds?: {code, seconds}, set_aside_task_id?, inbox_processed_delta?, snapshot_decision_queue?: true}` | merged session (rules below); never 409 |
| POST | `/review/sessions/{id}/finish` | `{clear_start?: yes \| not_really}` | the person tapped Done on the summary: status `completed` or `completed_empty` per data-model E3. There is no "left" outcome: leaving only pauses a review (FR-029); it ends without Done only by replacement or the 7-day idle close. Idempotent: finishing an already finished session returns it unchanged (200) |
| GET | `/review/queues/{step}` | query `session_id` | `{items: TaskResponse[], meta}`; `meta` per step: `wins` `{count}`; `rest_of_next` `{next_count, weekly_average_4w, weeks_of_history, implied_weeks}` (`weekly_average_4w` and `implied_weeks` are `null` when `weeks_of_history < 4` or there were no completions in them, FR-031); `someday` `{eligible_total, shown ≤ 7}`; `dates` grouped by local day for 14 days. Unknown or foreign `session_id` → the same 404 ("Ownership") |

**Session progress is merged, not version-checked**, so two devices moving the same
review never conflict: `step` statuses merge monotonically (`finished` > `skipped` >
`pending`); `current_step` is last-writer-wins by server arrival; `set_aside_task_id`
is added to a set; `inbox_processed_delta` (may be negative, for an Inbox Undo) and
`active_seconds` are added. The response is the merged session; a client whose local
step differs from the merged `current_step` shows "review moved on elsewhere" (design
M-13/D-03). A `set_aside_task_id` that is not an open task of this owner is ignored
(identical response for unknown and foreign ids). Progress on a finished session is
accepted and ignored (200, the finished session).

**Queues**: `decisions` = the session's `decision_queue` snapshot (ids of tasks that
`asks_for_decision`, formulation-clock §5 order), taken when the step first opens.
`waiting` = Waiting tasks whose `waiting_since` is more than 7 days ago and that no
current receipt hides, oldest `waiting_since` first. `someday` = Someday tasks that no
current receipt hides (a person's own release writes a `source: release` Someday
receipt, data-model E5, so tasks released by the person in the last 30 days are left
out, FR-032), excluding tasks with `parked.at` in the last 30 days; order:
never-reviewed first, then oldest receipt `reviewed_at`, then oldest `updated_at`, then
task id; at most 7 shown (FR-032).

**`SessionResponse`** (the exact wire shape, `schemas/review.py`, pinned by the golden
wire fixtures): `id, mode, entry, origin, status, started_at, last_activity_at,
ended_at, current_step, steps` (map step code → `pending | finished | skipped`)`,
active_seconds_by_step, counts` (the ten counters)`, set_aside_count` (the length of
E3 `set_aside_task_ids`)`, qualifying_activity, clear_start, revision`. `status` ∈
`open | completed | completed_empty | partial | abandoned`. Server-internal and not
on the wire: `set_aside_task_ids` (ids only; the count is enough for the client, which
keeps its own set-aside list for the session it runs), `decision_queue` (its items are
returned through the `decisions` queue), and the per-step `finished_empty` flags (they
only feed `qualifying_activity`).

### Bulk release (FR-017 restart, FR-030 Inbox remainder)

`POST /review/bulk-releases` body `{id?, kind: "restart" | "inbox_remainder",
session_id?, items: [{task_id, expected_revision}]}` (≤ 500) → 200
`{"id": "bulk_…", "released": [{task_id, revision_after}], "skipped": [{task_id,
reason: "stale" | "not_eligible"}]}`. The server is the authority for eligibility and
computes it per item at request time, under the owner lock: `restart` → the task is in
Next and `restart_eligible` (formulation-clock §5) under the owner's current settings
and clock; `inbox_remainder` → the task is in Inbox and, when `session_id` names a
session of this owner, was not processed in it. Everything else — wrong list, too
young, a task that does not exist or belongs to another owner — is `not_eligible`
(identical responses for unknown and foreign ids). So a stale or buggy client (or the
widget's quick-start entry) cannot release arbitrary Next tasks. Partial success is a
200 (M-10 / M-15 partial failure). The record keeps each released task's previous list
and, for Next tasks, its pre-release clock (data-model E7), and each released task gets
a Someday receipt (`source: release`, FR-032).

`POST /review/bulk-releases/{id}/undo` → 200 `{restored: […], skipped: […]}`: each
released task whose revision is still `revision_after` returns to its previous list with
its clock restored exactly (formulation-clock §3) and its release receipt deleted;
others are `skipped` with reason `stale` (M-10 / M-15 "undone, some skipped"). 409 `{"reason": "undo_unavailable"}` once
already undone, or after 7 days, when the snapshot is purged. The server keeps no
shorter window: when Undo stops being offered is a client rule (until the person moves
on from the restart screen or leaves the Inbox step, FR-017, FR-030).

## 7. Navigator (increment 2)

### `GET /review/navigator` → 200

`{"provider": "openai" | null, "consent": {"granted_at": …, "revoked_at": …,
"consent_text_version": 1} | null, "consent_current": bool, "consent_text_version": 1,
"available": bool}`. `provider` is the configured category name shown in consent
copy; `null` when the operator configured `disabled`. `consent_text_version` (top
level) is the server's current version; `consent_current` is false when there is no
grant, it is revoked, or it was given for an older version or another provider.

**Adapter location** (ADR-0001 rule 9, `docs/decisions/0001-…md:85-86`: "Network
clients are only concrete adapters in Execution or Capture" — not in Tasks; the
existing title-completion adapter already sits outside the modules tree): the OpenAI
HTTP adapter lives beside the title-completion adapter
in `backend/app/ai/review_navigator.py`, is built by `container.py` and is injected into
`ReviewService` through a `NavigatorProvider` protocol (a port) declared in
`backend/app/modules/tasks/navigator.py`. That module keeps only the request schema,
`reduce_notes`, output validation and the consent rules, and imports no HTTP client;
the import-linter contracts of PR-02 forbid `app.modules.tasks` from importing
`httpx` and `app.ai`.

**Provider configuration** (research R13): the navigator differs from title completion
on purpose. `BRAIN_BUDDY_REVIEW_NAVIGATOR_PROVIDER=openai` with the variable named by
`…_API_KEY_ENV` unset or empty makes the container build **raise** at startup, naming
the variable (never its value), so a misconfigured deploy fails its health check and
never serves (constitution I: required configuration must fail visibly, not degrade
silently). `deterministic` outside TEST and any unknown provider name raise the same
way. Only an explicit `disabled` yields `provider: null`, `available: false` and
`503 navigator_disabled`; clients then show the cloud choice as unavailable with a
reason instead of hiding it (M-06 "cloud unavailable", D-02 "suggestions unavailable").
Blast radius (kept deliberately, campaign-1 decision AC-01): a restart of an
already-serving machine with the key missing also fails, which takes every route down,
not only the navigator. The runbook line in plan "Migration, deploy order and
rollback" and in `.env.example` therefore says: set
`BRAIN_BUDDY_REVIEW_NAVIGATOR_PROVIDER=disabled` before rotating or removing the key,
and set it back after the new key is in place.

### `POST /review/navigator/consent` → 200 / `DELETE /review/navigator/consent` → 204

Grant body `{"provider": "openai", "consent_text_version": 1}`; 400
`{"reason": "provider_mismatch"}` if it is not the configured provider, 400
`{"reason": "consent_text_outdated"}` if the version is not the current one. Revoke
takes effect for every subsequent request immediately. The current version is a
constant in `navigator.py`, bumped whenever the FR-019 data list or the provider
changes; a stored grant with a lower version counts as absent.

### `POST /review/navigator/suggestions` → 200

Request (strict schema, `extra="forbid"` — nothing else can be sent, FR-019):

```json
{
  "kind": "first_step",
  "consent": {"external_processing_allowed": true, "provider": "openai"},
  "task": {"title": "Renovate the bathroom", "notes": "…", "stall_reason": "too_big"},
  "project": {"name": "Flat", "open_task_titles": ["…", "… up to 20"]}
}
```

`kind` ∈ `first_step | reformulate | project_next_action`; for
`project_next_action`, `task` is absent. There is no language field: the detected
task language is used only on the device for model routing and is not sent
(FR-019); the prompt tells the model to answer in the language of the task text.
Limits: title ≤ 500, notes ≤ the shared notes budget of contracts/navigator.md §1
(clients send already-reduced notes; the server applies the same reduction as a
backstop, which leaves reduced notes unchanged), project name ≤ 500, ≤ 20 titles each
≤ 500. Response:

```json
{"request_id": "uuid", "provider": "openai", "notes_truncated": false,
 "proposals": ["…", "…"], "clarifying_question": null}
```

Exactly one of `proposals` (1..3, deduplicated against `open_task_titles` and each
other by `formulation_key`) or `clarifying_question` is non-null. The server sees at
most 20 sibling titles, so the full FR-019 "no duplicates" guarantee is completed by the
client, which drops any proposal whose `formulation_key` equals that of **any** open
task of the project it holds, before showing them (contracts/navigator.md §2 rule 5).
Prompt and output validation: `contracts/navigator.md`.

**Not an idempotent mutation, and nothing is persisted**: this endpoint takes no
`Idempotency-Key`, goes through no `_serialized_write`, and stores no idempotency
record and nothing under the `task-commands/` mirror, because its response is AI output
derived from the person's notes (contracts/navigator.md §6). The only writes are the
content-free `navigator_usage` admission counters (below) and one log line. A test
asserts that after a suggestion call the owner's `idempotency_records` and the
`task-commands/` mirror hold no new row and no sentinel text.

**Cost admission and the task lock**: `TaskRepository.command_lock` is one
process-wide `RLock` (`repository.py:67-87`), so the provider call must never run under
it. The sequence is: (1) under `command_lock(owner_id)`, read the owner's
`navigator_usage` row for today, reject on the per-call estimate or the daily cap
(429 `navigator_cost_cap`), and write a reservation (`calls + 1`,
`reserved_cost_usd += estimate`); release the lock; (2) call the provider with no lock
held (8 s timeout); (3) under the lock again, settle: replace the reservation with the
actual token cost, or release it on timeout or failure. A reservation never settled
(process crash) is released by the next day's row. Test: a provider stub that itself
takes `command_lock` for another owner neither deadlocks nor waits (the
`test_review_navigator.py` lock case).

| status | `detail.reason` | when | design state |
|---|---|---|---|
| 400 | `navigator_consent_required` | no current consent row for the configured provider and current consent text version, or request consent mismatch | M-07 consent / consent after revoke |
| 400 | `navigator_input_too_large` | estimated input above `BRAIN_BUDDY_REVIEW_NAVIGATOR_MAX_INPUT_TOKENS` even after the shared reduction (contracts/navigator.md §1) | "These notes are too long for suggestions. Write your own step, or shorten the notes and try again." + Ref (M-07 / D-02 "input too large") |
| 404 | `weekly_review_disabled` | flag off | — |
| 429 | `navigator_rate_limited` (+ `Retry-After`) | per-owner rate limit | M-07 timeout-style copy |
| 429 | `navigator_cost_cap` | per-call or daily cost cap | M-07 "usage limit", no retry |
| 503 | `navigator_disabled` | operator configured provider `disabled` | web: "Suggestions aren't available right now." in place of Suggest (D-02); iOS: cloud choice shown unavailable (M-06) |
| 503 | `navigator_timeout` | provider timeout | M-07 timeout |
| 503 | `navigator_provider_error` | transport/provider error | M-07 provider |
| 503 | `navigator_malformed_output` | nothing usable after validation | M-07 / M-05 error |

No retry happens server-side; the client offers "Try again".

## 8. Compatibility and versioning

All additions are new paths or nullable fields: no breaking change for any shipped
client. Deploy order: backend first (flag OFF), then iOS and web. Rolling the backend
back to a pre-020 build loses no data (new tables are ignored; the tasks payload
fields are ignored and possibly dropped on re-save; the sweep repairs missing clocks
after roll-forward, formulation-clock §3), with two stated limits:

- **Retention pauses**: the retention part of the sweep (§9) does not exist in the old
  build, so content-bearing undo and bulk-release snapshots can outlive their 7-day
  bound during the rollback window; the first sweep after roll-forward nulls every
  snapshot older than 7 days. `docs/data-retention.md` states the bound as "7 days;
  longer only while the backend is rolled back to a build without the review sweep".
- **Park marker**: old code re-saving a parked Someday task drops `TaskDocument.parked`.
  The park itself is also recorded in `review_park_acks` at park time (data-model E6),
  so the park stays in the export and the metrics, but such a task no longer shows on
  "While you were away" or as auto-parked in the Someday step after roll-forward.

## 9. Maintenance sweep

`backend/app/main.py` gains `_run_review_maintenance_sweep(container)`. It is wired as
its own `try/except` block inside `_run_privacy_maintenance_sweep` (so the privacy
thread loop, `_start_privacy_maintenance_thread`, interval
`BRAIN_BUDDY_AGENT_RETENTION_SWEEP_INTERVAL_SECONDS`, default 60 s, runs it) **without
changing that function's 3-tuple return value**, which
`backend/tests/test_crt_receipt_retention.py:364` asserts; it is also called from
`_run_maintenance_sweep` at startup. A failure cannot stop purge or relay retention.

It has two parts:

1. **Retention** — for **every** owner with review rows, whatever the flag state
   (a flag turned off for rollback must not stop retention, FR-043): null decision undo
   snapshots older than 7 days; purge bulk-release clock snapshots older than 7 days;
   close sessions idle ≥ 7 days (partial or abandoned, E3); delete `navigator_usage`
   rows older than 35 days.
2. **Exposure** — only for owners that are **activated** (`activated_at` set, FR-051)
   **and** whose flag is effective: apply the sweep-gap floor when the owner's
   `last_effective_sweep_at` is ≥ 24 h old (formulation-clock §3), then set
   `last_effective_sweep_at = now`; repair missing clocks; auto-park due tasks with the
   idempotency key `auto-park:<task_id>:<formulation_id>:<from_revision>` (§4), writing
   the `review_park_acks` row (`parked_at`, `from_revision`) in the same transaction
   (data-model E6). The flag check uses `FeatureFlagService.is_effective(name, user)`
   (`backend/app/services/feature_flag_service.py:145`), which takes a `User`, so the
   sweep resolves each candidate owner's `User` through the user repository first (an
   owner that no longer resolves is skipped for exposure; retention still runs).

**Locking**: `TaskRepository.command_lock` is built on one process-wide `RLock`
(`repository.py:66-87`), so any owner's sweep transaction blocks all task writes for
all owners while it runs. Candidate ids are therefore selected **outside** the lock,
each owner is then processed under `command_lock(owner_id)` in short transactions of at
most 50 tasks that re-read before writing, and no provider or other network I/O ever
happens under the lock. Log line:
`review_sweep owners=%d parked=%d repaired=%d closed=%d gap_floors=%d
snapshots_nulled=%d duration_ms=%d`.

**Scan cost, stated honestly**: the clock fields live only in the JSON payload (no SQL
column, data-model E1) and `idx_tasks_owner_state` leads with `owner_id`, so the
candidate query cannot select park-due tasks; each run loads and classifies in Python
every Next task of every activated owner with the flag effective — O(Next tasks) per
minute. That is acceptable at the beta scale (tens of owners, hundreds of open tasks
each), and it grows linearly with the Next backlog. The implementing slice may add a
mitigation without a contract change, for example a per-owner `next_park_due_at`
watermark in `review_settings` maintained by every clock write, letting the sweep skip
owners with nothing due. The retention part likewise scans `review_decisions` and
`review_bulk_releases` by owner (no index on `decided_at` / `created_at`); an index may
be added in the same way.

**Errors**: a failure for one owner is logged as `review_sweep_owner_failed
owner_id=%s error=%s reason=%s` with `error = type(exc).__name__`, never `str(exc)` or
a validation error's `errors()` ("Logs" above), and the sweep continues with the next
owner. The log-capture test runs the sweep over a deliberately invalid task payload
containing a sentinel string and asserts the sentinel is in no captured record.

**Idempotency command prefixes** (one spelling everywhere, research R7):
`decide_task:`, `undo_decision:`, `auto-park:`, `bulk_release:`, `undo_bulk_release:`,
`review_session:`, `review_settings:`, `explainer_ack:`. They are registered in
`ReviewService`'s own `_apply_idempotent_record`, each with its own result
reconstructor, not in `TaskService._apply_idempotent_record` (`service.py:1142`), whose
default branch validates the stored response as a `TaskDocument`. The existing
`_serialized_write` (`service.py:64-79`) is bound to `TaskService` (it reads
`service.task_repo` and calls `service._reconcile_idempotent_result`); PR-02
generalises it to a small `SerializedWriter` protocol (`task_repo`,
`_reconcile_idempotent_result`) that both services implement, each reconciling only
the keys it issues. `ReviewService` composes `TaskService` and calls its undecorated
internal task-change helpers (create the follow-up, transitions, the clock rules)
inside its own serialized write, so one decision is still one transaction under one
lock with one idempotency record; the dependency direction is
`api → review_service → service → repository` and the tasks layers contract in
`backend/pyproject.toml` is extended exactly that way. A test reconciles one record of
each prefix.
