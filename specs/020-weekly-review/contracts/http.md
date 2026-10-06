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

**Gate**: every route below depends on `require_weekly_review_enabled` (new, in
`dependencies.py`, modelled on `require_voice_brain_dump_enabled` at line 361): when
`weekly_review` is not effective for the caller → **404**
`{"message": "Not found", "detail": {"reason": "weekly_review_disabled"}}`. Activation
(data-model E2, FR-016) happens only through `POST /review/explainer/acknowledge`
(§5, FR-051), never as a side effect of another call or of the sweep.

**Envelope** (unchanged, `backend/app/schemas/api.py` `ErrorResponse`):
`{"message": str, "detail": object | null, "reference_id": "<correlation id>"}` plus
the `X-Correlation-ID` header on every response, success or failure (FR-045).

**Mutations** require `Idempotency-Key` (400 without it, as today). A replay with the
same key and body returns the original response; a different body → 409
`{"reason": "idempotency_conflict"}`. Concurrency uses `expected_revision` in the body.

**Ownership**: an id in the path that does not exist **or belongs to another owner** →
404 with `{"resource": "...", "id": "..."}` (existing `NotFoundError` mapping). Never
403. **Task ids inside a request body** (bulk-release `items`, `set_aside_task_id`,
park acknowledgements) never produce a 404: an id that does not exist and an id of
another owner are treated identically (reported as `not_eligible`, or ignored), so the
response is byte-identical for both and cannot be used as an existence oracle across
owners. `second_api_client` tests assert this per endpoint.

**Client-supplied ids**: offline iOS creates sessions, decisions, bulk releases,
follow-up tasks and formulations before the server sees them. Those requests carry the
client's id (`id`, `decision_id`, `follow_up_task_id`, `new_formulation_id`; the
pattern of the existing optional `id` on `TaskCreateRequest`,
`backend/app/schemas/tasks.py:122`). The server adopts a supplied id when it creates
the record; ids are prefixed (`review_…`, `decision_…`, `bulk_…`, `form_…`, task ids as
today), 1..500 chars, unique per owner; a supplied id already used by a different
record of the same owner → 409 `{"reason": "id_conflict"}`. When no id is supplied (web,
older clients), the server mints one.

**Logs** (FR-044): one structured line per request on logger `app.modules.tasks.review`
or `app.api.review` with `owner_id`, ids, decision type, counts, `duration_ms`, outcome
code. Never titles, notes, waiting-for text, extension reason, clarifying answers,
proposal text or navigator input. The stall reason is **not** logged either (one reason
is behaviourally sensitive and platform logs outlive account purge); its distribution is
computed from `review_decisions`, which purge removes.

## 1. Existing contract preserved

- `GET/POST/PATCH /tasks…`, `/projects…`, `/tags…` keep their paths, methods, request
  bodies and status codes. Old clients that never send the new fields keep working.
- `TaskResponse` gains two nullable fields (§2). Older iOS builds decode with
  synthesized `Codable`, which ignores unknown keys; older web code ignores them.
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
Mapping is in `_to_response` (`backend/app/api/tasks.py:1183`).

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
| `reformulate` | next | `title` | title update; new formulation iff substantive | `reformulated` |
| `first_step` | next | `title` | title = new; details = `"Was: <old title>"` + (`"\n\n"` + old details if any); always a new formulation (FR-008) | `first_step` |
| `waiting` | next | `waiting_for` | move to waiting | `waiting` |
| `someday` | next | — | move to someday (`parked = null`; a person's release is not a park) | `someday` |
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
| 409 | `id_conflict` | a supplied client id is already used by another record | iOS sets aside with Ref (cannot happen with UUIDs in practice) |
| 422 | (validation) | missing/oversized fields | |

**Auto-park yield rule** (spec edge case "Offline for a long time"): if the request is
stale only because the task was auto-parked from exactly `expected_revision`
(`parked` set, `parked.from_revision == expected_revision`,
`parked.formulation_id == formulation_id`) and `client_decided_at < parked.at`, the
server reverses the park by restoring `parked.clock_before` exactly
(formulation-clock §3 "yield reversal": same formulation id, stalled count restored, the
formulation is not closed a second time) and applies the decision in the same
transaction. The decision is then evaluated against the restored task, so an `extend`
made offline before the park is accepted although the restored class is `park_due`.
The response is a normal 200; the decision carries `"yielded_auto_park": true`.
`client_decided_at` is used for nothing else.

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
**iff** the owner is activated, the task is in Next, its classification is `park_due`,
and it is not already parked for its current formulation. Response `{"applied": bool, "task": TaskResponse}`.
`applied: false` is a success, never a conflict (FR-013, US2-6). No
`expected_revision` is taken.

Server sweep: `ReviewService.run_auto_park_sweep(now)` applies the same command with
the deterministic idempotency key `auto-park:<task_id>:<formulation_id>` (§9).

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
reviews (completed and partial, data-model E3).

### `POST /review/explainer/acknowledge` → 200 state (FR-051)

Body `{}`. Idempotent and first-wins: when `activated_at` is null it is set to the
server's `now` and the activation transition of formulation-clock §3 runs under the
owner lock in the same transaction; when it is already set nothing changes. Either way
the response is the current `GET /review/state` body. Clients call it when the person
dismisses the explainer; iOS queues it offline like any other command. It is the only
way an owner becomes activated. The flag gate applies (404 when the flag is off).

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
| POST | `/review/sessions` | `{id?, mode, entry, origin, skip_steps?: [step], replace_open: bool}` | 201 session; with `replace_open` an open session is finished first (partial or abandoned by the E3 rule; the device that had it shows "review ended elsewhere"); without it and an open session exists → 409 `{"reason": "open_session_exists", "session_id": …}`. A replay with the same `id` returns the existing session. iOS always pushes an offline-started session with `replace_open: true` (ios-commands §4), so a queued review is never set aside |
| GET | `/review/sessions/{id}` | — | session |
| PATCH | `/review/sessions/{id}` | `{current_step?, step?: {code, status}, active_seconds?: {code, seconds}, set_aside_task_id?, inbox_processed_delta?, snapshot_decision_queue?: true}` | merged session (rules below); never 409 |
| POST | `/review/sessions/{id}/finish` | `{outcome: completed \| left, clear_start?: yes \| not_really}` | session (status computed per data-model E3). Idempotent: finishing an already finished session returns it unchanged (200) |
| GET | `/review/queues/{step}` | query `session_id` | `{items: TaskResponse[], meta}`; `meta` per step: `wins` `{count}`; `rest_of_next` `{next_count, weekly_average_4w, weeks_of_history, implied_weeks}` (`weekly_average_4w` and `implied_weeks` are `null` when `weeks_of_history < 4` or there were no completions in them, FR-031); `someday` `{eligible_total, shown ≤ 7}`; `dates` grouped by local day for 14 days |

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
current receipt hides, excluding tasks with `parked.at` in the last 30 days; order:
never-reviewed first, then oldest receipt `reviewed_at`, then oldest `updated_at`, then
task id; at most 7 shown (FR-032).

Session shape: data-model E3 (`id, mode, status, origin, started_at,
last_activity_at, current_step, steps, active_seconds_by_step, counts,
set_aside_count, clear_start, revision`). `status` ∈ `open | completed |
completed_empty | partial | abandoned`. `decision_queue` items are returned through the
`decisions` queue.

### Bulk release (FR-017 restart, FR-030 Inbox remainder)

`POST /review/bulk-releases` body `{id?, kind: "restart" | "inbox_remainder",
session_id?, items: [{task_id, expected_revision}]}` (≤ 500) → 200
`{"id": "bulk_…", "released": [{task_id, revision_after}], "skipped": [{task_id,
reason: "stale" | "not_eligible"}]}`. An item whose task does not exist or belongs to
another owner is `not_eligible`, exactly like a task that is not in the right list.
Partial success is a 200 (M-10 / M-15 partial failure). The record keeps each released
task's previous list and, for Next tasks, its pre-release clock (data-model E7).

`POST /review/bulk-releases/{id}/undo` → 200 `{restored: […], skipped: […]}`: each
released task whose revision is still `revision_after` returns to its previous list with
its clock restored exactly (formulation-clock §3); others are `skipped` with reason
`stale` (M-10 / M-15 "undone, some skipped"). 409 `{"reason": "undo_unavailable"}` once
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

**Provider configuration** (research R13): the navigator differs from title completion
on purpose. `BRAIN_BUDDY_REVIEW_NAVIGATOR_PROVIDER=openai` with the variable named by
`…_API_KEY_ENV` unset or empty makes the container build **raise** at startup, naming
the variable (never its value), so a misconfigured deploy fails its health check and
never serves (constitution I: required configuration must fail visibly, not degrade
silently). `deterministic` outside TEST and any unknown provider name raise the same
way. Only an explicit `disabled` yields `provider: null`, `available: false` and
`503 navigator_disabled`; clients then show the cloud choice as unavailable with a
reason instead of hiding it (M-06 "cloud unavailable", D-02 "suggestions unavailable").

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
other by `formulation_key`) or `clarifying_question` is non-null. Prompt and output
validation: `contracts/navigator.md`.

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
back to a pre-020 build is safe for data (new tables are ignored; the tasks payload
fields are ignored and possibly dropped on re-save; the sweep repairs missing clocks
after roll-forward, formulation-clock §3).

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
   idempotency key `auto-park:<task_id>:<formulation_id>`.

**Locking**: `TaskRepository.command_lock` is built on one process-wide `RLock`
(`repository.py:66-87`), so any owner's sweep transaction blocks all task writes for
all owners while it runs. Candidate ids are therefore selected **outside** the lock (one
indexed query on `idx_tasks_owner_state`), each owner is then processed under
`command_lock(owner_id)` in short transactions of at most 50 tasks that re-read before
writing, and no provider or other network I/O ever happens under the lock. Log line:
`review_sweep owners=%d parked=%d repaired=%d closed=%d gap_floors=%d
snapshots_nulled=%d duration_ms=%d`.

**Idempotency command prefixes** (one spelling everywhere, research R7):
`decide_task:`, `undo_decision:`, `auto-park:`, `bulk_release:`, `undo_bulk_release:`,
`review_session:`, `review_settings:`, `explainer_ack:`. Each is registered in
`TaskService._apply_idempotent_record` (`service.py:1142`) with its own result
reconstructor, because the default branch validates the stored response as a
`TaskDocument`; a test reconciles one record of each prefix.
