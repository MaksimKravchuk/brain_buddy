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

`TaskParkDocument`: `at: datetime`, `by: Literal["auto", "person"]`,
`formulation_id: str`, `from_revision: int ≥ 1`, `bulk_release_id: str | None`.

Transitions are the table in `contracts/formulation-clock.md` §3. They are applied
inside the existing commands (`create_task`, `smart_add_task`, `update_task`,
`transition_task`, `archive_project` only bumps revision) and the new commands
below. `create_native_inbox_task` creates Inbox tasks and never starts a clock.

**Response** (`backend/app/schemas/tasks.py` `TaskResponse`): adds
`formulation: TaskFormulationResponse | null` and `parked: TaskParkResponse | null`
(shapes in `contracts/http.md` §2). `TaskFormulationResponse` also carries the
server-derived `ask_at`, `park_due_at` and `paused_until` computed with the owner's
current settings, so the web classifies with its own clock without re-implementing
the instant arithmetic.

**Migration / compatibility**: additive. Old code reading new payloads ignores the
fields (`extra="ignore"`); old code re-saving a task drops them, which the auto-park
sweep repairs (formulation-clock §3 last row). No backfill runs at deploy; per-owner
activation (E2) backfills lazily.

## E2. Review settings — table `review_settings`

One row per owner. Columns: `owner_id PK`, `revision`, `payload` (JSON).

| field | type | default | rule |
|---|---|---|---|
| `activated_at` | datetime | first time the `weekly_review` flag is effective for the owner and any review endpoint or the sweep sees it | immutable once set (FR-016) |
| `onboarded_at` | datetime \| null | null | set by the onboarding save (FR-035) |
| `threshold_days` | 7 \| 14 \| 21 \| 28 | 14 | |
| `threshold_changed_at` | datetime \| null | null | |
| `owner_park_floor_at` | datetime \| null | null | `threshold_changed_at + 7 d` on every change (FR-039) |
| `review_weekday` | 1..7 (ISO, Monday = 1) | 5 (Friday) | |
| `review_time` | `HH:MM` | `16:00` | local wall time |
| `time_zone` | IANA name | `UTC` until a client sends one | validated with `zoneinfo`; clients send the device zone on onboarding and when it changes (US5-5) |
| `revision` | int ≥ 1 | 1 | optimistic concurrency for PUT |

## E3. Review session — table `review_sessions`

Columns: `owner_id`, `id` (`review_…`), `status`, `started_at`, `payload`;
PK `(owner_id, id)`; index `(owner_id, status, started_at)`.

| field | type | rule |
|---|---|---|
| `mode` | `quick \| full` | |
| `entry` | `list \| notification \| widget_decisions \| sidebar \| restart` | for metrics only |
| `status` | `open \| completed \| partial \| abandoned` | see transitions |
| `started_at`, `last_activity_at`, `ended_at?` | datetime | |
| `origin` | `ios \| web \| macos` | shown on the resume card (M-11) |
| `current_step` | step code | resume point (US4-7) |
| `steps` | map step code → `pending \| finished \| skipped`, plus `finished_empty: bool` | |
| `decision_queue` | list of task ids, oldest first | snapshot taken when the decision step first opens; ids only (edge case "threshold changed during an open review") |
| `set_aside_task_ids` | list of task ids | "Not now" (FR-050); non-empty excludes the session from SC-002 |
| `counts` | `{done, reformulated, first_step, waiting, someday, cancelled, extended, inbox_processed}` | maintained from E4 inside the same transaction; `inbox_processed` from progress events |
| `qualifying_activity` | bool | true after ≥ 1 item decision or ≥ 1 step finished with nothing to decide (FR-029) |
| `clear_start` | `yes \| not_really \| null` | FR-033 |
| `revision` | int | |

Step codes: `wins, mind_sweep, inbox, decisions, rest_of_next, waiting, projects,
someday, dates, summary`. Quick = `wins, inbox, decisions, summary` (FR-028).

**Status transitions**

```
open --finish(completed)--> completed
open --finish(left)--> partial      if qualifying_activity
open --finish(left)--> abandoned    otherwise
open --another session started by the person--> partial | abandoned (same rule)
open --no activity for 7 days (sweep)--> partial | abandoned (same rule)
```

"Leave for now" (M-13) does **not** finish a session; it stays `open` and resumable
on any device. **Regularity instant** `last_counted_review_at` = latest of
`completed.ended_at`, `partial.last_activity_at`, and `open.last_activity_at` where
`qualifying_activity`. It drives restart mode (≥ 21 days, FR-017), the notification
skip (preceding 6 days, FR-036) and "Last review: N days ago" (FR-038).

## E4. Review decision — table `review_decisions`

Columns: `owner_id`, `id` (`decision_…`), `task_id`, `session_id?`, `decided_at`,
`payload`; PK `(owner_id, id)`; index `(owner_id, task_id)`, `(owner_id, session_id)`.

| field | type | rule |
|---|---|---|
| `type` | see below | |
| `stall_reason` | `unclear \| too_big \| missing_info \| waiting_on_someone \| no_energy \| no_longer_matters \| null` | FR-007 |
| `substantive` | bool \| null | for `reformulate`: false when only a cosmetic edit was saved ("Save anyway") |
| `ai_use` | `none \| as_is \| edited \| not_used` | FR-026; `not_used` = proposals shown, own text saved |
| `navigator_request_id` | str \| null | correlates with navigator usage (E9), never with text |
| `formulation_id` | str \| null | the formulation decided on |
| `task_revision_before`, `task_revision_after` | int | Undo precondition |
| `undo` | `{task_before: TaskDocument snapshot, created_task_id?, receipt_id?} \| null` | content-bearing; nulled 7 days after `decided_at` by the sweep (R15) |
| `client_decided_at` | datetime \| null | device time; used only for the auto-park yield rule (R9) |
| `review_counts_as` | count bucket | which session counter it incremented |

`type` ∈ `complete, reformulate, first_step, waiting, someday, cancel, extend,
keep_waiting, follow_up, return_to_next, keep_someday`.

Extension reason text lives on the task (E1), not here, so it has one source and is
exported with the task. Stall reason is a code, never free text.

**Undo** (FR-048): allowed while `task.revision == task_revision_after` (no change
since). It restores `undo.task_before` field-for-field with `revision + 1`, deletes
any follow-up task created by the decision, deletes any receipt it created,
decrements the session counter, and **deletes the decision row**. Otherwise 409.

## E5. Review receipt — table `review_receipts`

Columns: `owner_id`, `task_id`, `kind` (`waiting \| someday`), `payload`;
PK `(owner_id, task_id, kind)` (one current receipt per task and kind).
Payload: `task_revision`, `reviewed_at`, `hidden_until` (`+7 d` waiting, `+30 d`
someday; FR-032), `decision_id`. A receipt hides the task from its step while
`now < hidden_until` **and** `task.revision == task_revision` (macOS POC rule,
`macos/Sources/BrainBuddyMac/LocalGTDStore.swift` `waitingReviewDue`).

## E6. Park acknowledgement — table `review_park_acks`

PK `(owner_id, task_id, formulation_id)`; payload `seen_at`. "Unseen parks" =
tasks with `parked.by == "auto"` and no ack for `parked.formulation_id`. Kept out of
the task so marking parks seen never bumps a task revision (no stale conflicts with
pending edits on other devices).

## E7. Bulk release — table `review_bulk_releases`

PK `(owner_id, id)`; payload `kind (restart | inbox_remainder)`, `session_id?`,
`released: [{task_id, revision_after}]`, `skipped: [{task_id, reason: stale |
not_eligible}]`, `created_at`, `undone_at?`. Undo restores each released task whose
revision is still `revision_after`; others are reported as partial failure (M-10
partial). Content-free.

## E8. Navigator consent — table `navigator_consents`

PK `(owner_id, provider)`; payload `granted_at`, `revoked_at?`, `consent_text_version`.
Current consent = row exists with `revoked_at is null` for the configured provider.
Re-granting after revoke sets a new `granted_at` and clears `revoked_at` (history of
the previous grant is kept in `history[]` for audit; content-free).

## E9. Navigator usage — table `navigator_usage`

PK `(owner_id, day)` (UTC date); payload `calls`, `estimated_cost_usd`. Admission
control for the per-owner daily cap. Content-free. Rows older than 35 days are deleted
by the sweep.

## E10. Device-local records (iOS / macOS; not on the server)

`StoreDocument` v2 (`ios/BrainBuddyKit/Sources/BrainBuddyCore/Outbox.swift`) gains
`base.review: ReviewState` and `local: LocalReviewState`:

- `ReviewState` mirrors E2-E8 for the signed-in owner (pulled from
  `GET /api/review/state`) or is the only copy for account-less use.
- `LocalReviewState`: `activatedAt` (account-less FR-016 anchor),
  `issuedAutoParks: [taskID: formulationID]` (R9 loop guard), navigator preference
  `fallbackChoice: ask | downloaded | cloud`, downloaded-model status
  (`notDownloaded | downloading(bytes) | installed(version, bytes)`), last
  notification scheduled instant.

The downloaded model file lives in the app's Application Support (not the App Group,
so the widget never maps it). Both are removed with the app and are **not** in the
account export (`docs/data-retention.md` gets a device-local row).

## Export and purge (FR-043)

| record | export file in the account ZIP | purge |
|---|---|---|
| E1 task fields | inside existing `tasks/tasks.json` | existing `task_repo.delete_all_for_owner` |
| E2 | `review/settings.json` | same call, extended |
| E3 | `review/sessions.json` | same |
| E4 (including any `undo` snapshot still retained) | `review/decisions.json` | same |
| E5 | `review/receipts.json` | same |
| E6 | `review/park_acknowledgements.json` | same |
| E7 | `review/bulk_releases.json` | same |
| E8 | `review/navigator_consents.json` | same |
| E9 | excluded (operational cost counters), listed in `export_manifest.json` `excluded` | same |

`TaskRepository.delete_all_for_owner` (`backend/app/modules/tasks/repository.py:644`)
deletes the review tables first, inside its existing lock, so the account purge order
in `AccountService.purge_account` (`backend/app/services/account_service.py:416`) is
unchanged and stays idempotent.
