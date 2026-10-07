# Data model: Weekly Review (020)

**Feature**: `specs/020-weekly-review/` · **Plan**: [plan.md](plan.md) · **Rules**:
[contracts/formulation-clock.md](contracts/formulation-clock.md) · **HTTP**:
[contracts/http.md](contracts/http.md) · **iOS**: [contracts/ios-commands.md](contracts/ios-commands.md)

Ownership (ADR-0027 draft §1): every record below is owned by the Tasks module
(`backend/app/modules/tasks/`) and stored in its SQLite file
`<data_dir>/tasks.sqlite3`, written only under `TaskRepository.command_lock(owner_id)`.
Every table is keyed by `owner_id` first; every read filters by owner; a record of
another owner is reported as **404**, never 403.

Spec entity → storage map:

| spec "Key Entity" | stored as |
|---|---|
| Formulation clock | fields on `TaskDocument` (E1) |
| Park marker | `TaskDocument.parked` (E1) + `review_park_acks` (E6) for "seen" |
| Review session | `review_sessions` (E3) |
| Review decision | `review_decisions` (E4) |
| Review receipt | `review_receipts` (E5) |
| Review settings | `review_settings` (E2) |
| AI navigator consent | `navigator_consents` (E8) |
| Navigator preference (per device) | iOS/macOS device-local only (E10); never on the server |
| Form draft (per device, FR-052) | iOS `local.formDrafts` (E10); web `localStorage` (E11); never on the server |
| Activation moment (FR-016, FR-051) | `review_settings.activated_at` (E2); account-less iOS `local.activatedAt` (E10) |

## E1. TaskDocument additions (`backend/app/modules/tasks/domain.py`)

All fields are optional with defaults, so existing JSON payloads load unchanged
(`StorageBaseModel`, payload column) and no SQL column is added.

| field | type | default | invariant |
|---|---|---|---|
| `formulation_id` | `str \| None` | `None` | non-null iff `state == "next"` and the clock is started |
| `formulation_started_at` | `datetime \| None` | `None` | non-null iff `formulation_id` non-null |
| `formulation_extended_at` | `datetime \| None` | `None` | only while in Next; ≥ the instant the formulation first asked |
| `formulation_extension_reason` | `str \| None` (1..500) | `None` | non-null iff `formulation_extended_at` non-null |
| `formulation_park_floor_at` | `datetime \| None` | `None` | only while in Next |
| `consecutive_stalled_formulations` | `int ≥ 0` | `0` | survives leaving Next (FR-005) |
| `parked` | `TaskParkDocument \| None` | `None` | non-null only while `state == "someday"` |

`TaskParkDocument` (written **only by auto-park**; a person's release, single or bulk,
leaves `parked = null`): `at: datetime`, `formulation_id: str`,
`from_revision: int ≥ 1`, `clock_before: {started_at, extended_at, extension_reason,
park_floor_at, stalled_before}` — the clock immediately before the park closed it, so
the yield rule restores it exactly (contracts/http.md §3). `extension_reason` is the
text already on the task, so `parked` adds no new kind of content; it is exported
with the task and purged with it, and `clock_before` is not part of `TaskResponse`.

**Revision rule**: activation clamp, clock repair, the sweep-gap floor and the
time-zone floor write clock fields without bumping `revision` or `updated_at`
(contracts/formulation-clock.md §2), so they never invalidate a queued edit or an Undo.

Transitions are the table in `contracts/formulation-clock.md` §3. They are applied
inside the existing commands (`create_task`, `smart_add_task`, `update_task`,
`transition_task`, `archive_project` only bumps revision) and the new commands
below. `create_native_inbox_task` creates Inbox tasks and never starts a clock.

**Response** (`backend/app/schemas/tasks.py` `TaskResponse`): adds
`formulation: TaskFormulationResponse | null` and `parked: TaskParkResponse | null`
(shapes in `contracts/http.md` §2). `TaskFormulationResponse` also carries the
server-derived `ageing_at`, `ask_at`, `park_due_at` and `paused_until` computed with the
owner's current settings, so the web classifies with its own clock without
re-implementing the instant arithmetic. Where they are computed (pure
`formulation.derive_instants`, one settings read per request in
`TaskService.formulation_views`, the shared public mapper in
`backend/app/api/task_mapping.py`): contracts/http.md §2.

**Migration / compatibility**: additive. Old code reading new payloads ignores the
fields (`extra="ignore"`, `backend/app/schemas/common.py:20`); old code re-saving a
task drops them. The sweep repairs a dropped clock on a Next task
(formulation-clock §3). A dropped `parked` on a Someday task is not repaired: the park
stays recorded in E6 (written at park time), but the task no longer shows on "While
you were away" (contracts/http.md §8 "Park marker"). No backfill runs at deploy; the per-owner
activation transition (E2) runs once, when the owner first acknowledges the
explainer.

## E2. Review settings — table `review_settings`

One row per owner. Columns: `owner_id PK`, `revision`, `payload` (JSON).

| field | type | default | rule |
|---|---|---|---|
| `activated_at` | datetime \| null | null; set to server `now` by the first `POST /review/explainer/acknowledge` from any device (FR-051) | immutable once set; first acknowledgement wins; the activation transition (formulation-clock §3) runs in the same transaction; the 14-day grace (FR-016) is `activated_at + 14 d`; while null the owner is not activated (no markers, no parks) |
| `last_effective_sweep_at` | datetime \| null | set to `activated_at` at activation | updated by every exposure sweep run and by every device auto-park evaluated while the flag is effective (http §4); a gap ≥ 24 h triggers the sweep-gap floor (formulation-clock §3), applied by whichever of the two runs first, before it evaluates any park |
| `onboarded_at` | datetime \| null | null | set by the onboarding save (FR-035) |
| `threshold_days` | 7 \| 14 \| 21 \| 28 | 14 | |
| `threshold_changed_at` | datetime \| null | null | |
| `owner_park_floor_at` | datetime \| null | null | `threshold_changed_at + 7 d` on every change (FR-039) |
| `review_weekday` | 1..7 (ISO, Monday = 1) | 5 (Friday) | |
| `review_time` | `HH:MM` | `16:00` | local wall time |
| `time_zone` | IANA name | `UTC` until a client sends one | validated with `zoneinfo`; set from the device zone by the activating explainer acknowledgement (http §5) and on onboarding; afterwards changed only when a device's **own** zone changes (that device's last observed zone, E10 / E11), never because a device's zone merely differs from the stored one (FR-035, US5-5; owner decision 2026-10-06); a PUT with the stored value is no change (no FR-046 floor, no `revision` bump, http §5). Used for classification and `next_review_at`; the notification and the "next review" a client shows use that client's current zone (http §5) |
| `revision` | int ≥ 1 | 1 | optimistic concurrency for PUT. The activating acknowledgement increments `revision`; a later one does not; sweep bookkeeping (`last_effective_sweep_at`, gap `owner_park_floor_at`) never does |

## E3. Review session — table `review_sessions`

Columns: `owner_id`, `id` (`review_…`), `status`, `started_at`, `payload`;
PK `(owner_id, id)`; index `(owner_id, status, started_at)`.

| field | type | rule |
|---|---|---|
| `mode` | `quick \| full` | |
| `entry` | `list \| notification \| widget_decisions \| sidebar \| restart` | for metrics only |
| `id` | `review_…` | client-supplied when started on iOS (http "Client-supplied ids"), else server-minted |
| `status` | `open \| completed \| completed_empty \| partial \| abandoned` | see transitions (FR-029) |
| `started_at`, `last_activity_at`, `ended_at?` | datetime | |
| `origin` | `ios \| web \| macos` | shown on the resume card (M-11) |
| `current_step` | step code | resume point (US4-7); last writer wins (http §6) |
| `steps` | map step code → `pending \| finished \| skipped`, plus `finished_empty: bool` | keys are exactly the mode's steps, set at start (FR-028: quick four, full ten); merged monotonically (`finished` > `skipped` > `pending`); progress naming another step is refused (http §6) |
| `active_seconds_by_step` | map step code → int seconds | SC-004: clients add the seconds a step was on screen and in use, counting a gap of more than 2 minutes without interaction as 0, and never counting time in the background; the server adds the reported deltas, each once (`applied_progress` below). Content-free. The client rule is one pure accumulator per client with an injected clock (Core `ActiveTimeAccumulator`, web `features/review/activeTime.ts`), checked against the `active_time` section of `review_flow_vectors.json` (plan Test strategy) |
| `decision_queue` | list of task ids, in formulation-clock §5 queue order | snapshot of the `asks_for_decision` aggregate taken when the decision step first opens; ids only (edge case "threshold changed during an open review"); `null` until taken, and once taken (an empty list included) never taken again |
| `set_aside_task_ids` | list of task ids | "Not now" (FR-050); non-empty excludes the session from SC-002 |
| `applied_progress` | map `progress_…` id → SHA-256 hex of the canonical progress body | server-internal replay protection for `PATCH /review/sessions/{id}` (http §6 "Progress is replay-safe"): a known id with the same digest is not merged again, at any age; ids and digests only, no content; kept while the session is `open`, dropped when it ends; not on the wire |
| `counts` | `{done, reformulated, first_step, waiting, someday, cancelled, extended, inbox_processed, kept, moved_to_next}` | the ten FR-033 counters; maintained from E4 `review_counts_as` inside the same transaction; `inbox_processed` from progress deltas (an Inbox Undo sends −1), each applied once per `progress_id` |
| `qualifying_activity` | bool | true after ≥ 1 item decision or ≥ 1 step other than `summary` finished (not skipped) with nothing to decide (FR-029) |
| `clear_start` | `yes \| not_really \| null` | FR-033 |
| `revision` | int | bumped on every change; informative only (progress is merged, http §6) |

Step codes: `wins, mind_sweep, inbox, decisions, rest_of_next, waiting, projects,
someday, dates, summary`. Quick = `wins, inbox, decisions, summary` (FR-028).

A finished step has **nothing to decide** when its queue is empty at that moment
(inbox: no Inbox task; decisions: no `asks_for_decision` task; waiting and someday: the
queue rules of http §6; projects: no active project without a next action), as
design.md states (FR-029). Wins, the mind sweep, the rest of Next and Dates always have
nothing to decide; the summary never qualifies (FR-029, owner decision 2026-10-07, as
the iOS kit's `ReviewRules.hasNothingToDecide` does, `Queries+Review.swift:116`). The
server side of this rule arrives with PR-11.

**Status transitions** (FR-029, owner decision 2026-10-06)

```
open --finish (Done on the summary)--> completed        if qualifying_activity
open --finish (Done on the summary)--> completed_empty  otherwise ("Review done" is still shown)
open --another session started (replace_open)--> partial if qualifying_activity, else abandoned
open --no activity for 7 days (sweep)--> partial if qualifying_activity, else abandoned
```

There is no "left" transition: "Leave for now" (M-13), closing the app or the tab
only pause a session; it stays `open` and resumable on any device (FR-029, US4-8,
US4-8a). **Counted reviews** are `completed` and `partial`, and an `open` session once
it has qualifying activity. **Regularity instant**
`last_counted_review_at` = latest of `completed.ended_at`, `partial.last_activity_at`,
and `open.last_activity_at` where `qualifying_activity`; `completed_empty` and
`abandoned` sessions never contribute. It drives restart mode (FR-017:
`onboarded_at` set and `now - coalesce(last_counted_review_at, onboarded_at) ≥ 21 d`,
so a never-reviewed person counts from onboarding and a not-yet-onboarded person gets
onboarding first), the notification skip (preceding 6 days, FR-036), "Last review: N
days ago" (FR-038) and the SC-001 weekly read-out.

**Wire subset**: `SessionResponse` carries every field above except
`set_aside_task_ids` (sent as `set_aside_count`), `decision_queue` (served through the
`decisions` queue), the per-step `finished_empty` flags and `applied_progress`; the
exact list is in contracts/http.md §6.

## E4. Review decision — table `review_decisions`

Columns: `owner_id`, `id` (`decision_<uuid>` when client-supplied on iOS, else server-minted; the id shapes are in http "Client-supplied ids"), `task_id`,
`session_id?`, `decided_at`, `payload`; PK `(owner_id, id)`; index
`(owner_id, task_id)`, `(owner_id, session_id)`. `session_id` is null when the
decision was made outside a review or named a session the server does not know
(http §3).

| field | type | rule |
|---|---|---|
| `type` | see below | |
| `stall_reason` | `unclear \| too_big \| missing_info \| waiting_on_someone \| no_energy \| no_longer_matters \| null` | FR-007 |
| `substantive` | bool \| null | for `reformulate`: false when only a cosmetic edit was saved ("Save anyway") |
| `ai_use` | `none \| as_is \| edited \| not_used` | FR-026; `not_used` = proposals shown, own text saved |
| `navigator_request_id` | str (exactly the 36-character UUID the server returned as `request_id`) \| null | correlates with navigator usage (E9), never with text; any other value is 422 (http "Client-supplied ids") |
| `formulation_id` | str \| null | the formulation decided on |
| `task_revision_before`, `task_revision_after` | int | Undo precondition |
| `reason_text` | str (1..500) \| null | only for `extend`: the "keep 7 more days" reason, kept as decision history (FR-043, intake "decisions and reasons stored"); content-bearing; exported in `review/decisions.json`, purged with the account, never logged |
| `undo` | `{task_before: TaskDocument snapshot, created_task_id?, created_task_revision?, receipt_id?} \| null` | content-bearing; nulled 7 days after `decided_at` by the retention part of the sweep, whatever the flag state (R15, http §9) |
| `client_decided_at` | datetime \| null | device time; used only for the auto-park yield rule (R9) |
| `review_counts_as` | count bucket | which session counter it incremented (table below) |

`type` ∈ `complete, reformulate, first_step, waiting, someday, cancel, extend,
keep_waiting, follow_up, return_to_next, keep_someday`.

**`review_counts_as` mapping** (FR-033, owner decision 2026-10-06):

| decision `type` | counter |
|---|---|
| `complete` | `done` |
| `reformulate` | `reformulated` |
| `first_step` | `first_step` |
| `waiting` | `waiting` |
| `someday` | `someday` |
| `cancel` (from Next, Waiting or Someday) | `cancelled` |
| `extend` | `extended` |
| `keep_waiting`, `keep_someday` | `kept` ("Kept as is") |
| `follow_up`, `return_to_next` | `moved_to_next` ("Moved to Next") |
| (Inbox item processed; not a decision row) | `inbox_processed` via session progress |

The task keeps the open formulation's extension reason (E1) for display while the
formulation is open; the decision row keeps it as history after the formulation
closes. Stall reason is a code, never free text.

**Undo** (FR-048): allowed while `task.revision == task_revision_after` (no change
since) **and**, when the decision created a follow-up task, that task's revision still
equals `created_task_revision` **and** it has no tag link, subtask or comment (the rows
that `ON DELETE CASCADE` with a task; adding a subtask or comment does not bump the
revision, and Undo never deletes a row the person added). It restores
`undo.task_before` field-for-field with `revision + 1`, except for clock bookkeeping
written since the decision (formulation-clock §3 "decision undo"), deletes the
follow-up task created by the decision, deletes any receipt
it created, decrements the session counter, and **deletes the decision row**.
Otherwise 409 `undo_unavailable` and nothing changes.

## E5. Review receipt — table `review_receipts`

Columns: `owner_id`, `task_id`, `kind` (`waiting \| someday`), `payload`;
PK `(owner_id, task_id, kind)` (one current receipt per task and kind).
Payload: `task_revision`, `reviewed_at`, `hidden_until` (`+7 d` waiting, `+30 d`
someday; FR-032), `source` (`keep` for keep waiting / keep in Someday; `release` for a
person's own release to Someday: decision `someday`, restart or Inbox-remainder bulk
release, FR-032), and `decision_id` or `bulk_id`. A `release` receipt only hides the
task from the Someday step; it is not counted as "Kept as is". Undo of the decision or
of the bulk release deletes the receipt it wrote. A receipt hides the task from its step while
`now < hidden_until` **and** `task.revision == task_revision` (macOS POC rule,
`macos/Sources/BrainBuddyMac/LocalGTDStore.swift` `waitingReviewDue`).

## E6. Park acknowledgement — table `review_park_acks`

PK `(owner_id, task_id, formulation_id)`; payload `parked_at`, `from_revision`,
`source` (`sweep | device`), `seen_at?`, `returned_at?`. The row is written **at park
time**, in the same transaction as the park, so the park stays in the export and the
metrics even if old code later drops `TaskDocument.parked` (http §8).
"Unseen parks" = tasks with `parked` set and no `seen_at` for `parked.formulation_id`.
A repeat park of the same formulation, e.g. after a decision was undone (formulation-clock
§3, T-046), upserts the row with the new `parked_at`, `from_revision` and `source`, and
**resets `seen_at` and `returned_at` to null**, so the task appears again in "While you
were away".
Kept out of the task so marking parks seen never bumps a task revision (no stale
conflicts with pending edits on other devices). When a parked task is moved back to
Next, the server upserts the row with `returned_at` in the same transaction, so the
supporting metric "share of auto-parked tasks later returned" is derivable from stored
ids and instants. If the row is missing at that moment, nothing is written (its
`source` is unknown) and a content-free warning is logged. A yield reversal (http §3)
is not a return: it reverses the park itself, so the row keeps `parked_at`,
`from_revision`, `source` and `seen_at` and `returned_at` is null afterwards, whatever
the yielding decision does. An Undo that puts a task back into its park (for example of
`return_to_next` from Someday) sets `returned_at` back to null, its value while the task
was parked. Content-free.

## E7. Bulk release — table `review_bulk_releases`

PK `(owner_id, id)` (`bulk_…`, client-supplied when made on iOS); payload
`kind (restart | inbox_remainder)`, `session_id?`, `released: [{task_id,
revision_after, previous_state, clock_before?}]`, `skipped: [{task_id, reason: stale |
not_eligible}]`, `created_at`, `undone_at?`, `undo_result?: {restored: [task_id],
skipped: [{task_id, reason: stale}]}` (ids and codes only; returned unchanged when the
undo is retried, http §6). `previous_state` is `next` (restart) or
`inbox` (Inbox remainder). `clock_before` is set for Next tasks: `{formulation_id,
started_at, extended_at, extension_reason, park_floor_at, stalled_before}`, so Undo
puts each task back "as it was, including its clock" (M-10, FR-017) without starting a
new formulation. Undo restores each released task whose revision is still
`revision_after`; others are reported as `skipped` (M-10 / M-15 "undone, some
skipped"). Ids, instants and codes only, **except** `extension_reason`, which is
content-bearing: every `clock_before` is nulled 7 days after `created_at` by the
retention part of the sweep (as E4 `undo`), after which an Undo that never happened
returns `undo_unavailable` (an already applied Undo still returns its `undo_result`).

## E8. Navigator consent — table `navigator_consents`

PK `(owner_id, provider)`; payload `granted_at`, `revoked_at?`, `consent_text_version`.
Current consent = row exists with `revoked_at is null` for the configured provider
**and** `consent_text_version` equal to the server's current version (bumped whenever
the FR-019 data list or the provider changes); an older version counts as absent
(400 `navigator_consent_required`).
Re-granting after revoke sets a new `granted_at` and clears `revoked_at` (history of
the previous grant is kept in `history[]` for audit; content-free).

## E9. Navigator usage — table `navigator_usage`

PK `(owner_id, day)` (UTC date); payload `calls`, `estimated_cost_usd`,
`reserved_cost_usd` (admission reservations not yet settled, http §7 "Cost admission
and the task lock"), `shown` (requests that returned at least one proposal). Admission
control for the per-owner daily cap, and the server-visible denominator of the SC-005
real-use acceptance rate (plan Test strategy, read-out). Content-free. Rows older than
35 days are deleted by the retention part of the sweep, whatever the flag state
(http §9); the post-release read-out is therefore run and recorded weekly (plan
"Post-release acceptance").

## E10. Device-local records (iOS / macOS; not on the server)

`StoreDocument` v2 (`ios/BrainBuddyKit/Sources/BrainBuddyCore/Outbox.swift`) gains
`base.review: ReviewState` and `local: LocalReviewState`:

- `ReviewState` mirrors E2-E8 for the signed-in owner (pulled from
  `GET /api/review/state`) or is the only copy for account-less use.
- `LocalReviewState`: `activatedAt` (account-less FR-016/FR-051 anchor: the instant the
  person first dismissed the explainer on this device), `explainerSeenLocally`
  (signed-in: suppresses the explainer until the pulled `activated_at` arrives),
  `issuedAutoParks: [taskID: formulationID]` (R9 loop guard), navigator preference
  `fallbackChoice: ask | downloaded | cloud`, downloaded-model status
  (`notDownloaded | downloading(bytes) | interrupted(bytes, reason) | installed(version, bytes)`), last
  notification scheduled instant, `formDrafts` (FR-052; never synced, removed on
  save/discard/formulation change/sign-out or after 7 days), `wywaLastShownDay` (the
  local calendar day "While you were away" was last shown at app open, for the
  once-per-day rule of FR-015), `serverClockOffset` (last observed `server_now` minus
  device time, signed in only; ios-commands §5), `lastObservedTimeZone` (the IANA zone
  this device last observed; a zone change is sent only when the device's current zone
  differs from it, ios-commands §2; removed with the store on sign-out),
`linkedExtensionNotices` (task ids only: tasks whose unsent "Keep 7 more days" was
dropped when an account-less install was linked, shown once on M-09; ios-commands §7).

Device-local retention mirrors the server's snapshot bound (contracts/ios-commands.md §5
`runLocalReviewMaintenance`): local decision undo snapshots and bulk-release clock
snapshots are nulled after 7 days, idle local sessions are closed after 7 days, drafts
expire after 7 days — signed in or account-less. The server only nulls snapshots; the
rest is device cache eviction with no server counterpart: signed in, the device also
drops decisions and bulk releases once their snapshots are nulled, and ended runs after
35 days; ended runs keep no progress ids. Exception (device only): an unsent
`decideTask` or `bulkRelease` that a queued Undo names keeps `undoRetained`, so replay
still derives its snapshot; no snapshot is stored (the outbox holds the flag and the
task fields). It lasts until the pair is sent or removed. After an undone bulk release
the replayed record keeps `clockBefore` in memory only. Signed in, the record is
dropped once it reaches `base` and the next maintenance run sees it is 7 days old or
more.

The downloaded model file lives in the app's Application Support (not the App Group,
so the widget never maps it). Both are removed with the app and are **not** in the
account export. The download itself is an ordinary request to Apple's asset hosting
(Background Assets), which sees the device's request as it would an App Store
download and receives no task content; the PR-09 privacy-policy row says so.

`formDrafts` keys: form kind + task id + formulation id; or session id + step item for
review-step forms; or project id for the first next action typed for a project
without one (M-08, M-19; FR-052). `docs/data-retention.md` gets device-local rows: the iOS store
document row is extended to list review state (decisions with 7-day undo snapshots,
extension reasons, sessions, consent state, form drafts) in PR-02; the model file and
navigator preference rows come with PR-09.

## E11. Web form drafts (browser-local; not on the server)

Unsaved decision-form text on the web (FR-052) is kept in `localStorage` under
`bb.reviewFormDraft.v1.<origin>.<account>.<task>.<formulation>` (the namespacing of
the existing task-detail and CRT drafts, `frontend/src/features/tasks/taskDetailAutosave.ts`,
`docs/data-retention.md` CRT rows); the next-action field of the review's projects step
uses `project.<project id>` in place of `<task>.<formulation>`. It is removed on save, discard, formulation change,
sign-out or account switch, and by a startup/focus sweep after 7 days. Never sent or
logged. `docs/data-retention.md` gets a row in PR-02.

The web also keeps `bb.reviewWywaLastShown.v1.<origin>.<account>` (a local calendar
day, no content) for the once-per-day rule of the While-you-were-away dialog (FR-015),
removed on sign-out, and `bb.reviewLastZone.v1.<origin>.<account>` (the IANA zone this
browser last observed; a zone change is sent only when the browser's current zone
differs from it, http §5), removed on sign-out or account switch.

## Export and purge (FR-043)

| record | export file in the account ZIP | purge |
|---|---|---|
| E1 task fields | inside existing `tasks/tasks.json` | existing `task_repo.delete_all_for_owner` |
| E2 | `review/settings.json` | same call, extended |
| E3 | `review/sessions.json` | same |
| E4 (including `reason_text` and any `undo` snapshot still retained) | `review/decisions.json` | same |
| E5 | `review/receipts.json` | same |
| E6 | `review/park_acknowledgements.json` | same |
| E7 (including any `clock_before` still retained) | `review/bulk_releases.json` | same |
| E8 | `review/navigator_consents.json` | same |
| E9 | excluded (operational cost counters), listed in `export_manifest.json` `excluded` | same |
| navigator cloud input (title, notes, stall reason, project name, sibling titles) as received by the cloud provider | not exportable (held by the provider, not by Brain Buddy) | **not reachable by account purge**: the provider processes it under its data-processing terms and keeps it per its own policy (the privacy policy already states 30 days for OpenAI API data, `frontend/src/pages/PrivacyPolicyPage.tsx:176-181`). This is the one copy of this feature's content that survives purge by design; PR-07 states it in `docs/data-retention.md` and the privacy policy. Notes and titles are sent as written, so names of other people in them are included: the consent copy (M-07, D-02) says "Notes are sent as written, including any names in them." and the privacy policy says the same (owner decision 2026-10-06) |

`review_settings` holds the review day, time and **IANA time zone** (coarse location)
for the account's life; the PR-02 privacy-policy wording for review settings names all
three explicitly.

`TaskRepository.delete_all_for_owner` (`backend/app/modules/tasks/repository.py:644`)
deletes the review tables first, inside its existing lock, so the account purge order
in `AccountService.purge_account` (`backend/app/services/account_service.py:416`) is
unchanged and stays idempotent.
