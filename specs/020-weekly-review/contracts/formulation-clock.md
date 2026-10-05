# Contract: Formulation clock and marker classification (shared rule)

**Feature**: `specs/020-weekly-review/` · **Requirements**: FR-001, FR-002, FR-003,
FR-046, FR-004, FR-005, FR-009, FR-012, FR-013, FR-016, FR-017, FR-039 · **Design**:
marker system table in `design.md` (M-01, M-02, D-01, M-17, M-24)

This file is normative for all three implementations:

| implementation | file (created by this feature) |
|---|---|
| backend | `backend/app/modules/tasks/formulation.py` |
| iOS core (Linux-testable) | `ios/BrainBuddyKit/Sources/BrainBuddyCore/Formulation.swift` |
| web | `frontend/src/features/review/formulation.ts` (formulation key for the M-04/D-02 "cosmetic edit" note; classification from the server's derived instants) |

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
| `parked` | `null`, or `{at, by: "auto" \| "person", formulation_id, from_revision}` |

Owner-level inputs: `threshold_days` T ∈ {7, 14, 21, 28}; `time_zone` (IANA);
`owner_park_floor_at` (set on every threshold change to change instant + 7 days,
FR-039); `activated_at` (FR-016).

## 3. Transitions (applied by every writer)

| event | effect |
|---|---|
| task created in Next; moved, reopened or returned into Next | new `formulation_id`; `formulation_started_at = now`; extension and floor cleared; `parked = null` |
| title changed while in Next, substantive | close current formulation (§4), then start a new one as above |
| title changed while in Next, cosmetic | no clock change |
| notes, tags, project, priority, subtasks, comments, waiting_for edited | no clock change (FR-003) |
| due date set, moved or removed while in Next | `formulation_park_floor_at = max(existing, now + 7 d)` (FR-046); start unchanged |
| task leaves Next (any destination, any actor) | close current formulation (§4); all formulation fields `null` except `consecutive_stalled_formulations` |
| decision `extend` | `formulation_extended_at = now`, reason stored; allowed only when classification is `asks` or `moves_tomorrow` and no extension exists |
| auto-park | as "leaves Next" to Someday, plus `parked = {at: now, by: "auto", formulation_id, from_revision}` |
| person release to Someday through restart bulk release or Inbox remainder (FR-017, FR-030) | as "leaves Next", plus `parked.by = "person"` |
| task leaves Someday, or is completed/cancelled from Someday | `parked = null` |
| feature activation for an owner (FR-016) | every task in Next: if `formulation_started_at` is `null`, start a formulation at `activated_at`; in all cases `formulation_park_floor_at = max(existing, activated_at + 14 d)` |
| sweep finds a Next task with `formulation_started_at = null` after activation (rollback repair) | start a formulation at `now` with `formulation_park_floor_at = now + 14 d` |

**Closing a formulation** (§4): if `now >= ask_at` at that moment, then
`consecutive_stalled_formulations += 1`, else `consecutive_stalled_formulations = 0`.

## 4. Derived instants

```
start      = formulation_started_at
if due_date is set:
    due_start = start of due_date in time_zone, as a UTC instant
    start     = max(start, due_start)
ask_at     = start + T days
if formulation_extended_at is set:
    ask_at = max(ask_at, formulation_extended_at) + 7 days
park_due_at = max(ask_at + 7 days,
                  formulation_park_floor_at or -inf,
                  owner_park_floor_at or -inf)
tomorrow_at = park_due_at - 24 hours
```

"days" are exact 86 400-second spans in UTC; only `due_start` uses the local
calendar. With no extension and no floors this gives ask at T and park at T + 7
(FR-004, FR-012). With an extension made on the threshold day it gives ask at T + 7 and
park at T + 14 (FR-009, FR-012); see research R6 for extensions made later.

## 5. Classification at instant `now`

Evaluated only for tasks in Next with `formulation_started_at` set; every other task
is `none`.

| order | condition | class | list marker | detail marker |
|---|---|---|---|---|
| 1 | due date set and `now < due_start` | `paused` | none | "Paused until the due date" |
| 2 | `now >= park_due_at` | `park_due` | "Moves to Someday tomorrow" (until applied) | same |
| 3 | `now >= tomorrow_at` | `moves_tomorrow` | "Moves to Someday tomorrow" | same |
| 4 | `now >= ask_at` | `asks` | "Asks for a decision" | same |
| 5 | `now - start >= T/2 days` | `ageing` | none (owner decision 2) | "Ageing" |
| 6 | otherwise | `fresh` | none | days only |

`restart_eligible` (FR-017): class is not `paused` and `now - start >= 28 days`.
`third_stall` (FR-005): class ∈ {`asks`, `moves_tomorrow`, `park_due`} and
`consecutive_stalled_formulations >= 2`.

A writer may apply auto-park only when its own evaluation yields `park_due`. The
server additionally requires its own clock to agree (research R9).

## 6. Shared test vectors

Canonical file: `backend/tests/fixtures/review_formulation_vectors.json`. Byte-identical
copies: `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/Resources/review_formulation_vectors.json`
and `frontend/src/features/review/__tests__/review_formulation_vectors.json`.
`backend/tests/test_review_formulation_vectors.py` fails if the copies differ.

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
      "expect": {"class": "asks", "ask_at": "2026-10-08T09:14:00Z",
                 "park_due_at": "2026-10-15T09:14:00Z",
                 "restart_eligible": false, "third_stall": false}
    }
  ],
  "transitions": [
    {"id": "T-001", "before": {}, "event": {"type": "update_title", "title": "..."},
     "now": "...", "expect": {}}
  ]
}
```

Required coverage: every row of §1 examples; every class in §5 at its exact boundary
(one second before and at); DST start/end in `Europe/Berlin` and `America/New_York`
for `due_start`; due date today/tomorrow/yesterday; extension at T, T + 3 and T + 6;
each floor dominating; activation backfill; the third-stall count across leave and
return.
