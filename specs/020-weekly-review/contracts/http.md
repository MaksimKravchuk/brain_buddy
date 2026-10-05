# HTTP contract: Weekly Review (020)

**Base**: every path is under `config.api_prefix` (`/api`), session-cookie
authenticated (`Depends(get_current_user)`, 401 without a session), owner-scoped.
**Router**: new `backend/app/api/review.py` (`APIRouter(tags=["review"])`), mounted in
`backend/app/api/__init__.py` beside `task_router`. Services come from
`Depends(get_task_service)` / `Depends(get_review_service)` (new provider in
`backend/app/api/dependencies.py`). No route touches a repository.

**Gate**: every route below depends on `require_weekly_review_enabled` (new, in
`dependencies.py`, modelled on `require_voice_brain_dump_enabled` at line 361): when
`weekly_review` is not effective for the caller → **404**
`{"message": "Not found", "detail": {"reason": "weekly_review_disabled"}}`. The first
gated call for an owner also performs activation (data-model E2, FR-016).

**Envelope** (unchanged, `backend/app/schemas/api.py` `ErrorResponse`):
`{"message": str, "detail": object | null, "reference_id": "<correlation id>"}` plus
the `X-Correlation-ID` header on every response, success or failure (FR-045).

**Mutations** require `Idempotency-Key` (400 without it, as today). A replay with the
same key and body returns the original response; a different body → 409
`{"reason": "idempotency_conflict"}`. Concurrency uses `expected_revision` in the body.

**Ownership**: an id that does not exist **or belongs to another owner** → 404 with
`{"resource": "...", "id": "..."}` (existing `NotFoundError` mapping). Never 403.

**Logs** (FR-044): one structured line per request on logger `app.modules.tasks.review`
or `app.api.review` with `owner_id`, ids, decision type, reason code, counts,
`duration_ms`, outcome code. Never titles, notes, waiting-for text, extension reason,
clarifying answers, proposal text or navigator input.

## 1. Existing contract preserved

- `GET/POST/PATCH /tasks…`, `/projects…`, `/tags…` keep their paths, methods, request
  bodies and status codes. Old clients that never send the new fields keep working.
- `TaskResponse` gains two nullable fields (§2). Older iOS builds decode with
  synthesized `Codable`, which ignores unknown keys; older web code ignores them.
- `PATCH /tasks/{id}` and `POST /tasks/{id}/transitions` additionally maintain the
  formulation clock (`contracts/formulation-clock.md` §3). No new request field is
  required. Optional `client_occurred_at` (RFC 3339) is accepted on both; it is used
  only by the auto-park yield rule (research R9) and is never trusted for ordering
  anything else.

## 2. Task response additions (`backend/app/schemas/tasks.py`)

```json
"formulation": {
  "id": "form_…",
  "started_at": "2026-09-24T09:14:00Z",
  "extended_at": null,
  "extension_reason": null,
  "park_floor_at": null,
  "consecutive_stalled": 0,
  "ask_at": "2026-10-08T09:14:00Z",
  "park_due_at": "2026-10-15T09:14:00Z",
  "paused_until": null
},
"parked": {"at": "2026-10-08T09:14:03Z", "by": "auto", "formulation_id": "form_…"}
```

`formulation` is `null` unless the task is in Next with a started clock. `ask_at`,
`park_due_at`, `paused_until` are derived with the owner's settings at response time
and are **advisory for display**; clients never send them back. Mapping is in
`_to_response` (`backend/app/api/tasks.py:1189`).

## 3. Decisions

### `POST /tasks/{task_id}/decisions` → 200 `DecisionResponse`

```json
{
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
  "client_decided_at": "2026-10-09T14:05:12Z"
}
```

| `type` | allowed when task is | required fields | task effect |
|---|---|---|---|
| `complete` | open | — | `transition complete` |
| `reformulate` | next | `title` | title update; new formulation iff substantive |
| `first_step` | next | `title` | title = new; details = `"Was: <old title>"` + (`"\n\n"` + old details if any); always a new formulation (FR-008) |
| `waiting` | next | `waiting_for` | move to waiting |
| `someday` | next | — | move to someday (`parked = null`; a person's release is not a park) |
| `cancel` | open | — | cancel |
| `extend` | next, class `asks`/`moves_tomorrow`, not yet extended | `reason` (1..500) | sets extension (FR-009) |
| `keep_waiting` | waiting | — | none; writes receipt (+7 d) |
| `follow_up` | waiting | `title` | creates a Next task in the same project; writes receipt on the original |
| `return_to_next` | waiting or someday | `title` | move to next (+ title if changed) |
| `keep_someday` | someday | — | none; writes receipt (+30 d) |

`formulation_id` is required for the Next-only types and must equal the task's
current formulation, otherwise the decision is stale.

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
| 400 | `decision_not_allowed` | type not allowed for the task's state | generic error + Ref |
| 400 | `extension_already_used` / `extension_not_due` | FR-009 | card hides the option; server is the backstop |
| 400 | `project_archived` | `follow_up`/`return_to_next` into an archived project | M-18 archived, M-09 partial |
| 404 | `{resource, id}` | task, session not found or not owned | |
| 422 | (validation) | missing/oversized fields | |

**Auto-park yield rule** (spec edge case "Offline for a long time"): if the request is
stale only because the task was auto-parked from exactly `expected_revision`
(`parked.by == "auto"`, `parked.from_revision == expected_revision`,
`parked.formulation_id == formulation_id`) and `client_decided_at < parked.at`, the
server reverses the park and applies the decision in the same transaction. The
response is a normal 200; the decision carries `"yielded_auto_park": true`.

### `POST /review/decisions/{decision_id}/undo` → 200

Body `{"expected_task_revision": 8}`. Response `{"task": TaskResponse,
"undone_decision_id": "decision_…", "deleted_task_id": null, "session_counts": {…}}`.
409 `{"reason": "undo_unavailable"}` when the task changed since the decision or the
undo snapshot was already purged (7 days). 404 when not owned or already undone.

## 4. Auto-park

### `POST /tasks/{task_id}/auto-park` → 200

Body `{"formulation_id": "form_…"}`. Used by iOS for parks observed on the device.
The server re-evaluates with its own clock and settings under the owner lock and parks
**iff** the task is in Next, its classification is `park_due`, and it is not already
parked for its current formulation. Response `{"applied": bool, "task": TaskResponse}`.
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
  "last_counted_review_at": "2026-09-30T15:40:00Z",
  "next_review_at": "2026-10-09T14:00:00Z",
  "restart_mode": false,
  "open_session": null,
  "unseen_parks": [{"task_id": "task_…", "formulation_id": "form_…", "parked_at": "…"}],
  "counts": {"asks": 3, "moves_tomorrow": 1},
  "receipts": [{"task_id": "…", "kind": "waiting", "hidden_until": "…", "task_revision": 4}],
  "server_now": "2026-10-09T14:02:00Z"
}
```

`server_now` lets clients detect clock skew (R9).

### `PUT /review/settings` → 200 settings

Body: any of `threshold_days`, `review_weekday`, `review_time`, `time_zone`,
`onboarded: true`, plus `expected_revision`. 409 on revision mismatch. 400
`{"reason": "invalid_time_zone"}` for a non-IANA zone. A threshold change sets
`owner_park_floor_at = now + 7 d` (FR-039).

### `POST /review/parks/acknowledge` → 204

Body `{"items": [{"task_id": "…", "formulation_id": "…"}]}` (≤ 200). Idempotent;
unknown or foreign ids are ignored (no existence leak).

## 6. Sessions and queues (increment 3)

| method | path | body | response |
|---|---|---|---|
| POST | `/review/sessions` | `{mode, entry, origin, skip_steps?: [step], replace_open: bool}` | 201 session; with `replace_open` an open session is finished as partial/abandoned first; without it and an open session exists → 409 `{"reason": "open_session_exists", "session_id": …}` |
| GET | `/review/sessions/{id}` | — | session |
| PATCH | `/review/sessions/{id}` | `{expected_revision, current_step?, step?: {code, status}, set_aside_task_id?, inbox_processed_delta?, snapshot_decision_queue?: true}` | session |
| POST | `/review/sessions/{id}/finish` | `{outcome: completed \| left, clear_start?: yes \| not_really}` | session (status computed per data-model E3) |
| GET | `/review/queues/{step}` | query `session_id` | `{items: TaskResponse[], meta}`; `meta` per step: `wins` `{count}`; `rest_of_next` `{next_count, weekly_average_4w, weeks_of_history, implied_weeks}`; `someday` `{eligible_total, shown ≤ 7}`; `dates` grouped by local day for 14 days |

Session shape: data-model E3 (`id, mode, status, origin, started_at,
last_activity_at, current_step, steps, counts, set_aside_count, clear_start,
revision`). `decision_queue` items are returned through the `decisions` queue.

### Bulk release (FR-017 restart, FR-030 Inbox remainder)

`POST /review/bulk-releases` body `{kind: "restart" | "inbox_remainder", session_id?,
items: [{task_id, expected_revision}]}` (≤ 500) → 200
`{"id": "bulk_…", "released": [{task_id, revision_after}], "skipped": [{task_id,
reason: "stale" | "not_eligible"}]}`. Partial success is a 200 (M-10 / M-15 partial
failure). `POST /review/bulk-releases/{id}/undo` → 200 `{restored: […], skipped:
[…]}`; 409 `{"reason": "undo_unavailable"}` once already undone.

## 7. Navigator (increment 2)

### `GET /review/navigator` → 200

`{"provider": "openai" | null, "consent": {"granted_at": …, "revoked_at": …} | null,
"available": bool}`. `provider` is the configured category name shown in consent
copy; `null` when disabled.

### `POST /review/navigator/consent` → 200 / `DELETE /review/navigator/consent` → 204

Grant body `{"provider": "openai", "consent_text_version": 1}`; 400
`{"reason": "provider_mismatch"}` if it is not the configured provider. Revoke takes
effect for every subsequent request immediately.

### `POST /review/navigator/suggestions` → 200

Request (strict schema, `extra="forbid"` — nothing else can be sent, FR-019):

```json
{
  "kind": "first_step",
  "consent": {"external_processing_allowed": true, "provider": "openai"},
  "task": {"title": "Renovate the bathroom", "notes": "…", "stall_reason": "too_big"},
  "project": {"name": "Flat", "open_task_titles": ["…", "… up to 20"]},
  "language_hint": "ru"
}
```

`kind` ∈ `first_step | reformulate | project_next_action`; for
`project_next_action`, `task` is absent. Limits: title ≤ 500, notes ≤ 20 000,
project name ≤ 500, ≤ 20 titles each ≤ 500. Response:

```json
{"request_id": "uuid", "provider": "openai",
 "proposals": ["…", "…"], "clarifying_question": null}
```

Exactly one of `proposals` (1..3, deduplicated against `open_task_titles` and each
other by `formulation_key`) or `clarifying_question` is non-null. Prompt and output
validation: `contracts/navigator.md`.

| status | `detail.reason` | when | design state |
|---|---|---|---|
| 400 | `navigator_consent_required` | no current consent row for the configured provider, or request consent mismatch | M-07 consent / consent after revoke |
| 404 | `weekly_review_disabled` | flag off | — |
| 429 | `navigator_rate_limited` (+ `Retry-After`) | per-owner rate limit | M-07 timeout-style copy |
| 429 | `navigator_cost_cap` | per-call or daily cost cap | M-07 "usage limit", no retry |
| 503 | `navigator_disabled` | provider `disabled` | Suggest hidden on web |
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

`backend/app/main.py` gains `_run_review_maintenance_sweep(container)`, called from
`_run_privacy_maintenance_sweep`'s thread loop (`_start_privacy_maintenance_thread`,
interval `BRAIN_BUDDY_AGENT_RETENTION_SWEEP_INTERVAL_SECONDS`, default 60 s) and from
`_run_maintenance_sweep` at startup, in its own `try/except` so a failure cannot stop
purge or relay retention. Per run, for activated owners whose flag is effective:
auto-park due tasks; repair missing clocks; close sessions idle ≥ 7 days; null decision
undo snapshots older than 7 days; delete `navigator_usage` rows older than 35 days.
Each owner is processed under its own `command_lock`, re-reading before writing, as the
voice sweeps do. Log line: `review_sweep owners=%d parked=%d repaired=%d closed=%d
duration_ms=%d`.
