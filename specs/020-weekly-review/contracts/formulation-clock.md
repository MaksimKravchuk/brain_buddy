# Contract: Formulation clock and marker classification (shared rule)

**Feature**: `specs/020-weekly-review/` · **Requirements**: FR-001, FR-002, FR-003,
FR-046, FR-004, FR-005, FR-009, FR-012, FR-013, FR-016, FR-017, FR-039, FR-048, FR-051 · **Design**:
marker system table in `design.md` (M-01, M-02, D-01, M-17, M-24)

This file is normative for all three implementations:

| implementation | file (created by this feature) |
|---|---|
| backend | `backend/app/modules/tasks/formulation.py` |
| iOS core (Linux-testable) | `ios/BrainBuddyKit/Sources/BrainBuddyCore/Formulation.swift` |
| web | `frontend/src/features/review/formulation.ts` (formulation key for the M-04/D-02 "cosmetic edit" note; `classifyFromInstants`, which classifies from the server's derived instants `ageing_at`, `ask_at`, `park_due_at`, `paused_until` — http §2 — and is run against the classification vectors) |

A change to any rule below changes the vector file in the same commit (see §6).

## 1. Substantive title change (FR-002)

`formulation_key(title)` is computed as:

1. Unicode **NFKC** normalisation.
2. Every scalar whose General Category is punctuation (`Pc Pd Ps Pe Pi Pf Po`) is
   replaced by one U+0020 SPACE. Symbols (`S*`), digits, letters, marks and emoji are
   kept. `ё` and `е` stay distinct (no diacritic folding).
3. Whitespace is collapsed exactly as Python `" ".join(value.split())` does (the
   rule `normalize_task_name` in `backend/app/modules/tasks/repository.py:43` already
   uses, and `NameNormalizer.collapsed` already reproduces in Swift).
4. Full Unicode case folding exactly as Python `str.casefold()`, with no
   re-normalisation afterwards. Swift reuses `NameNormalizer.caseFolded`
   (`ios/BrainBuddyKit/Sources/BrainBuddyCore/NameNormalizer.swift:91`), which
   reproduces it scalar for scalar. The web ports the same exception table (research R3).

This is `normalize_task_name` with one extra step (punctuation → space), so the
backend implements it as a sibling of that function, not a new algorithm.

A title change is **substantive** iff `formulation_key(old) != formulation_key(new)`.
Examples (all in the vector file): `"Call Bob"` → `"call bob."` cosmetic;
`"Follow-up with Ann"` → `"follow up with ann"` cosmetic; `"e-mail Ann"` →
`"email Ann"` substantive; `"Straße"` → `"STRASSE"` cosmetic; `"Ёлка"` → `"Елка"`
substantive; `"Купить хлеб"` → `"купить  хлеб!"` cosmetic.

## 2. Clock fields on a task

| field | meaning |
|---|---|
| `formulation_id` | opaque id of the current formulation; `null` when not in Next |
| `formulation_started_at` | UTC instant the current formulation started; `null` when not in Next |
| `formulation_extended_at` | UTC instant of the one-time "keep 7 more days", or `null` |
| `formulation_extension_reason` | the required reason text (≤ 500 chars), or `null` |
| `formulation_park_floor_at` | UTC instant before which this task must not be parked, or `null` |
| `consecutive_stalled_formulations` | integer ≥ 0 (FR-005) |
| `parked` | `null`, or `{at, formulation_id, from_revision, clock_before}`; written **only by auto-park** (a person's release to Someday, single or bulk, is not a park). `clock_before` = `{started_at, extended_at, extension_reason, park_floor_at, stalled_before}`, the clock as it was immediately before the park closed it, so the yield rule can restore it exactly |

Owner-level inputs: `threshold_days` T ∈ {7, 14, 21, 28}; `time_zone` (IANA);
`owner_park_floor_at` (set to change instant + 7 days on every threshold change,
FR-039, and on a sweep gap, §3); `activated_at` (FR-016, FR-051): the instant the owner
first acknowledged the auto-park explainer on any device (server time of the first
acknowledgement that reached the server; on account-less iOS the device instant).
While `activated_at` is null the owner is **not activated**: every task classifies as
`none` and nothing parks.

**Revision rule for clock bookkeeping**: the activation clamp, a clock repair, the
sweep-gap floor and the time-zone floor (§3) write clock fields only and are stored
**without** incrementing the task's `revision` or `updated_at`. They are outside
optimistic concurrency, so a queued edit or a pending Undo made against the previous
revision stays valid; clients receive the new values on their next pull. Every other
row of §3 is part of a normal task write and bumps `revision`.

## 3. Transitions (applied by every writer)

| event | effect |
|---|---|
| task created in Next; moved, reopened or returned into Next | new `formulation_id`; `formulation_started_at = now`; extension and floor cleared; `parked = null` |
| title changed while in Next, substantive | close current formulation (§4), then start a new one as above |
| title changed while in Next, cosmetic | no clock change |
| notes, tags, project, priority, subtasks, comments, waiting_for edited | no clock change (FR-003) |
| due date set, moved or removed while in Next | `formulation_park_floor_at = max(existing, now + 7 d)` (FR-046); start unchanged |
| task leaves Next (any destination, any actor) | close current formulation (§4); all formulation fields `null` except `consecutive_stalled_formulations` |
| decision `extend` | `formulation_extended_at = now`, reason stored; allowed only when the task is still in Next, its class is `asks`, `moves_tomorrow` or `park_due` (the park is due but not yet applied, FR-009, FR-013), and no extension exists |
| auto-park | as "leaves Next" to Someday, plus `parked = {at: now, formulation_id, from_revision, clock_before}` where `clock_before` is captured before closing |
| person release to Someday: decision `someday`, restart bulk release (FR-017) | as "leaves Next"; `parked` stays `null`. A bulk release stores each task's pre-release clock (the `clock_before` shape, plus `consecutive_stalled_formulations` before closing) in its bulk-release record (data-model E7). Every person release also writes a Someday receipt (`source: release`, data-model E5), so the task stays out of the Someday step for 30 days (FR-032); that is not a clock change |
| Inbox-remainder release (FR-030) | an Inbox task moves to Someday; Inbox tasks have no clock, so nothing changes on the clock; `parked` stays `null`; the bulk-release record stores the previous state `inbox`; a Someday receipt is written as for any person release |
| undo of a bulk release (per task still at `revision_after`) | the task returns to its previous list; a task returning to Next gets its stored clock back exactly (same `formulation_id`, `started_at`, extension, floor, stalled count); no new formulation starts |
| decision undo (FR-048) | the task is restored field-for-field from the decision's snapshot, clock included; no new formulation starts. When the decision yielded an auto-park, the snapshot is taken **after** the yield reversal, so Undo restores the task in Next with the restored clock and `parked = null`, and the next sweep may park it again (vectors T-044 – T-046) |
| auto-park yield reversal (http §3) | the park is reversed by restoring `clock_before` exactly (same `formulation_id`, stalled count restored to `stalled_before`, so the formulation is not closed twice) and `parked = null`; then the yielding decision applies normally |
| task leaves Someday, or is completed/cancelled from Someday | `parked = null` |
| activation for an owner (FR-016, FR-051): `activated_at` is set | every task in Next: if `formulation_started_at` is `null`, start a formulation at `activated_at`; otherwise `formulation_started_at = max(formulation_started_at, activated_at)` (same `formulation_id`, the **activation clamp**); in all cases `formulation_park_floor_at = max(existing, activated_at + 14 d)`. So nothing asks before `activated_at + T` and nothing parks before `activated_at + 14 d` |
| sweep finds a Next task with `formulation_started_at = null` after activation (old-client save or rollback repair) | start a formulation at `now` with `formulation_park_floor_at = now + 14 d` |
| the sweep runs for an owner after a gap of ≥ 24 h since its last effective run for that owner (flag off then on, outage) | `owner_park_floor_at = max(existing, now + 7 d)`, so a visible "moves to Someday tomorrow" marker precedes every park that the gap made due (SC-006) |
| owner `time_zone` changes (the new value differs from the stored one; a `time_zone` equal to the stored zone is no change and raises no floor, http §5) | every Next task with a due date: `formulation_park_floor_at = max(existing, now + 7 d)` (the FR-046 floor), because `due_start` moves with the zone |

**Closing a formulation** (§4): the formulation **reached "asks for a decision"**
(FR-005) iff `formulation_extended_at` is set (an extension is only allowed once the
formulation asks, so an extended formulation has asked even if it closes before its
extended `ask_at`) **or** `now >= ask_at` at that moment. If it reached it,
`consecutive_stalled_formulations += 1`, else `consecutive_stalled_formulations = 0`
(spec FR-005). So extending on day 18 and reformulating on day 20, before the
extended `ask_at` of day 25, still counts the closed formulation as stalled.

**Where clocks start on the server**: a formulation started by a request starts at the
instant the server applies it. A task created or moved offline on iOS therefore gets
its server clock at push time, later than the device's own clock and never earlier, so
offline work can delay asking but can never cause an early park. Formulation ids are
adopted from the client when supplied (http §1), so device and server agree.

## 4. Derived instants

```
start      = formulation_started_at
if due_date is set:
    due_start = start of due_date in time_zone, as a UTC instant
    start     = max(start, due_start)
ageing_at  = start + T/2 days
ask_at     = start + T days
if formulation_extended_at is set:
    ask_at = max(ask_at, formulation_extended_at) + 7 days
park_due_at = max(ask_at + 7 days,
                  formulation_park_floor_at or -inf,
                  owner_park_floor_at or -inf)
tomorrow_at = park_due_at - 24 hours
paused_until = due_start if due_date is set and due_start > formulation_started_at
               else null
```

`paused_until` is reported as is, even once it is in the past. The class is `paused` iff
`paused_until` is set and `now < paused_until` (§5 row 1). A due date on or before the
formulation's start never pauses it (vectors C-061, C-062).

"days" are exact 86 400-second spans in UTC; only `due_start` uses the local
calendar. With no extension and no floors this gives ask at T and park at T + 7
(FR-004, FR-012). With an extension made on the threshold day it gives ask at T + 7 and
park at T + 14 (FR-009, FR-012); see research R6 for extensions made later.

## 5. Classification at instant `now`

Evaluated only for tasks in Next with `formulation_started_at` set, for an activated
owner (`activated_at` set); every other task is `none`.

| order | condition | class | list marker | detail marker |
|---|---|---|---|---|
| 1 | `paused_until` set and `now < paused_until` (§4) | `paused` | none | "Paused until the due date" |
| 2 | `now >= park_due_at` | `park_due` | "Moves to Someday tomorrow" (until applied) | same |
| 3 | `now >= tomorrow_at` | `moves_tomorrow` | "Moves to Someday tomorrow" | same |
| 4 | `now >= ask_at` | `asks` | "Asks for a decision" | same |
| 5 | `now >= ageing_at` | `ageing` | none (owner decision 2) | "Ageing" |
| 6 | otherwise | `fresh` | none | days only |

**Asks for a decision (aggregate)**: `asks_for_decision` = class ∈ {`asks`,
`moves_tomorrow`, `park_due`}. This one set is what the spec means by "tasks that ask
for a decision" wherever they are counted or listed (FR-004): the review decision
queue, the widget `askCount`, `GET /review/state` `counts.asks_for_decision`, the
summary and SC-002. **Queue order** ("earliest-asking first", the wording used in
spec US4-3 and design M-16): ascending `ask_at`, then
ascending `formulation_started_at`, then task id. An extended or due-date-paused task
therefore sorts by when it actually started asking, not by its original start.

`restart_eligible` (FR-017): class is not `paused` and `now - start >= 28 days`.
In practice auto-park moves an undecided formulation at most T + 7 ≤ 35 days after its
start, and the device applies due parks before the review opens, so for thresholds up
to 21 days the restart offer mostly finds tasks kept in Next by an extension, a floor
(activation grace, threshold change, sweep gap), or a due-date pause that has ended;
for T = 28 the window is days 28–35. Restart mode is the safety net for those and for
a long gap before parks were applied; tests seed such tasks explicitly (quickstart
Scenario 5 step 6).
`third_stall` (FR-005): `asks_for_decision` and
`consecutive_stalled_formulations >= 2`.

A writer may apply auto-park only when its own evaluation yields `park_due`. The
server additionally requires its own clock to agree (research R9).

## 6. Shared test vectors

Canonical file: `backend/tests/fixtures/review_formulation_vectors.json`. Byte-identical
copies: `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/Resources/review_formulation_vectors.json`
and `frontend/src/features/review/__tests__/review_formulation_vectors.json`.

- **Who lands the copies**: slice PR-02 writes the canonical file **and** both copies
  (the only `ios/` and `frontend/` files PR-02 writes), so the drift guard is live
  from the first slice. PR-03 and PR-05 only read their copy. PR-02 also executes
  every section of `review_flow_vectors.json` once, against the pure rule module
  `backend/app/modules/tasks/review_rules.py` (wins window, capacity, queue membership
  and order, session status, regularity and restart anchor, notification skip,
  stall-reason recommendation, active-time accumulation), so no consumer lane relies
  on a vector that has never run; PR-11 builds the flow service on those functions.
- **Drift guard**: `backend/tests/test_review_formulation_vectors.py` fails if either
  copy is missing or differs. Because CI path filtering can skip the backend lane on
  an `ios/`-only or `frontend/`-only change, PR-14 also adds the same byte comparison
  to `make check-specs` (which runs on every change).
- **Sections each implementation must pass**: Python — all sections; Swift — all
  sections; TypeScript — `normalisation`, plus `classification` through
  `classifyFromInstants` (the vector's `expect` instants are its input, the class its
  output). The same guard covers the review-flow vector file
  (`review_flow_vectors.json`, plan Test strategy).

```json
{
  "schema": "brainbuddy-formulation-vectors/v1",
  "normalisation": [
    {"id": "N-001", "old": "Call Bob", "new": "call bob.", "substantive": false}
  ],
  "classification": [
    {
      "id": "C-001",
      "settings": {"threshold_days": 14, "time_zone": "Europe/Berlin",
                   "owner_park_floor_at": null},
      "task": {"state": "next", "formulation_started_at": "2026-09-24T09:14:00Z",
               "formulation_extended_at": null, "formulation_park_floor_at": null,
               "due_date": null, "consecutive_stalled_formulations": 0},
      "now": "2026-10-09T14:02:00Z",
      "expect": {"class": "asks", "ageing_at": "2026-10-01T09:14:00Z",
                 "ask_at": "2026-10-08T09:14:00Z",
                 "park_due_at": "2026-10-15T09:14:00Z", "paused_until": null,
                 "asks_for_decision": true,
                 "restart_eligible": false, "third_stall": false}
    }
  ],
  "transitions": [
    {
      "id": "T-001",
      "settings": {"threshold_days": 14, "time_zone": "Europe/Berlin",
                   "owner_park_floor_at": null, "activated_at": "2026-09-01T08:00:00Z"},
      "before": {"state": "next", "title": "Call Bob", "revision": 3,
                 "formulation_id": "form_a", "formulation_started_at": "2026-09-24T09:14:00Z",
                 "formulation_extended_at": null, "formulation_extension_reason": null,
                 "formulation_park_floor_at": null, "consecutive_stalled_formulations": 0,
                 "due_date": null, "parked": null},
      "event": {"type": "update_title", "title": "Email Bob the quote",
                "new_formulation_id": "form_b"},
      "now": "2026-10-09T14:02:00Z",
      "expect": {"state": "next", "revision": 4, "formulation_id": "form_b",
                 "formulation_started_at": "2026-10-09T14:02:00Z",
                 "consecutive_stalled_formulations": 1, "parked": null}
    }
  ]
}
```

**Transition vector schema**: `before` holds the task's state, title, revision, every
§2 clock field, `due_date` and `parked`; `settings` holds the owner inputs including
`activated_at`; `event.type` ∈ `create_in_next | update_title | update_due_date |
update_other | transition{to} | decide{decision_type, …} | undo_decision |
auto_park | yield_reversal | bulk_release | undo_bulk_release | activate{at, time_zone?} |
repair | sweep_gap | threshold_change{to} | time_zone_change{to}`; events that start a
formulation carry `new_formulation_id` so ids are deterministic; `expect` lists every
field that must hold afterwards (fields not listed must equal `before`), including
whether `revision` was bumped (§2 revision rule).

Required coverage: every row of §1 examples; every class in §5 at its exact boundary
(one second before and at); DST start/end in `Europe/Berlin` and `America/New_York`
for `due_start`; due date today/tomorrow/yesterday; extension at T, T + 3, T + 6 and at
`park_due` before the park is applied; each floor dominating (activation, threshold
change, due-date change, sweep gap, time-zone change); not activated → `none`;
activation clamp and null-clock start; the third-stall count across leave and return;
yield reversal followed by `extend`, and by `reformulate` (stalled count incremented
once, not twice); `extend` followed by a substantive `reformulate` before the extended
`ask_at` (stalled count incremented, FR-005); park → yield + cosmetic `reformulate`
("Save anyway") → the next sweep parks again (new `from_revision`, so a new
auto-park key, contracts/http.md §4); park → yield + decision + `undo_decision` → the
next sweep parks again; bulk-release undo restores the clock exactly; queue order with
an extended and a due-paused task; activation with `time_zone: "Pacific/Honolulu"` and
a due date today (`due_start` in that zone, not UTC).

**Changing a vector after PR-02**: the canonical file and both copies are edited in the
same commit by one slice whose `depends_on` includes every slice that already consumes
that vector file (so the change cannot race an independent consumer); the drift guard
fails otherwise. The same rule applies to `review_flow_vectors.json` and the golden
wire and trace fixtures (plan Test strategy).
