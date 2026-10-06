# ADR-0027: Native-task Weekly Review, the formulation clock, and auto-park

- **Status**: Accepted
- **Date**: 2026-10-05 (drafted); accepted 2026-10-06
- **Decision owner**: Max (founder)
- **Sign-off**: Max (product owner), 2026-10-06. The owner approved the design on
  2026-10-05 and accepted the planning review on 2026-10-06
  (`specs/020-weekly-review/planning-review.json`, `founder-accepted`).
- **Landing**: this record lands in slice PR-01 of `specs/020-weekly-review/`, an
  ASK-class change (ADR-0008, ADR-0012: `scripts/` and gate-integrity guarded files).
  Its acceptance still rides on the owner's recorded ASK approval of that PR.
- **Source**: `specs/020-weekly-review/adr-draft.md`, copied without changes to the
  decision text except the validator wording quoted in Decision §6, aligned to the
  design-skill test this slice adds.
- **Supersedes in part**: ADR-0006, only "Weekly Review remains explicitly deferred"
  (Context), audit row B-09's "do not turn `due Sun` into product state until Weekly
  Review cadence is separately accepted", and the UI-control row "Weekly review
  coming later — keep visibly non-interactive until its accepted workflow exists".
  Build-contract open item D-11 (`docs/vnext-cloud-design-build-contract.md`, "Define
  cadence, timezone, and due calculation before showing a badge") is closed by this
  record.
- **Amends**: ADR-0001, only the **Review** module row, the
  `WeeklyReview`/`WeeklyReviewOutcome` model, the `/weekly-reviews` endpoints and the
  `reviews/{owner_id}/…json` storage line, for **native tasks**. The capture-based review model stays
  reserved for the Organize/Capture tranche and is not built here.
- **Narrows**: ADR-0019/ADR-0021 flag rule: adds one runtime-managed flag,
  `weekly_review`, default OFF. Implementation note (slice PR-15): the post-marker
  upgrade now accepts any store that holds every ADR-0019 row and no unknown row, and
  adds each missing post-ADR-0019 row (`task_title_autocomplete`, `crt_canvas`,
  `task_mcp` from feature 022, `weekly_review`) as OFF with no cohort. Before, only the exact earlier row sets were
  upgraded, so a store that had lost one of those later rows stayed degraded until an
  operator repaired it; now the next start re-creates it OFF. A missing ADR-0019 row
  still leaves the store degraded.
- **Related**: spec `specs/020-weekly-review/` (spec, design, plan), ADR-0002
  (`weekly_review_voice` stays a later phase), ADR-0008, ADR-0012, ADR-0020,
  ADR-0022, constitution Principle I.

## Context

The constitution's primary loop names a "smart Weekly Review" stage. Every accepted
record so far deferred it: ADR-0006 keeps it visibly "coming later", ADR-0001 models a
review over **captures** (atomic items in `proposed / needs_clarification / approved /
deferred`) that the product never built, and the macOS POC's local Waiting/Someday
review is explicitly read-only with respect to GTD state.

The owner has decided (intake D1-D4, spec Clarifications 2026-10-05) that:

1. a Next action may not keep the same wording ("formulation") past a user-chosen
   threshold (7/14/21/28 days, default 14) without a decision;
2. a formulation still undecided 7 days after the threshold is moved from Next to
   Someday automatically ("auto-park"), visibly and reversibly;
3. the review runs over native tasks on iOS and web (macOS after Mac sync), with a
   schedule, one notification on iOS, and an AI navigator that only proposes.

None of that fits the capture-based model, and point 2 contradicts the standing
principle that nothing changes a task's GTD state without the person.

## Decision

### 1. Native-task review lives in the Tasks module

Weekly Review for native tasks is part of `backend/app/modules/tasks/`. Its records
(review settings, review sessions, review decisions, receipts, park
acknowledgements, bulk releases, navigator consent and usage) are stored in the
Tasks module's own SQLite file `tasks.sqlite3`, beside the tasks they refer to,
written under the same owner command lock (`TaskRepository.command_lock`) and the
same idempotency machinery (`_serialized_write`, `idempotency_records`).

Reason: every review decision changes a task and records the decision in **one**
owner-serialized transaction. Splitting the records into a separate module and store
would make "task changed but decision not recorded" (and the reverse) possible,
break Undo (FR-048), and require a cross-store saga the product does not need.

ADR-0001's separate **Review** module remains the home for a future capture-based or
cross-module review. This record does not create it.

The non-voice review code does not use the path token `weekly_review`: the forward
guard `test_weekly_review_modules_reuse_the_shared_voice_workflow_if_present`
(`backend/tests/test_voice_workflow_architecture.py:250`) is kept and its docstring
is clarified to say it guards the ADR-0002 `weekly_review_voice` operation.
Voice-led review, when built, still reuses `app.workflows.voice_brain_dump`.

### 2. The formulation clock is task data; the rule is shared and normative

Each task carries a formulation clock while it is in Next: a formulation id, its start
instant, the one-time extension (instant and reason), a park floor, and a count of
consecutive stalled formulations. A new formulation starts when a task enters Next
(create, move, reopen, return from Someday) and when its title changes
substantively while in Next. The substantive-change rule and the classification rule
(fresh / ageing / asks for a decision / moves to Someday tomorrow / paused by a
future due date) are specified once in
`specs/020-weekly-review/contracts/formulation-clock.md` and implemented
identically by the backend (`app/modules/tasks/formulation.py`), the iOS core
(`BrainBuddyCore`) and the web (derived instants only). One JSON vector file,
copied byte-for-byte into each test tree and checked for drift, is the parity oracle.

Markers are **derived**. ADR-0006's four open lists are unchanged; there is no fifth
list and no new lifecycle state. "Asks for a decision" is not a state.

### 3. Auto-park is the single automatic GTD state change

The system may move a task from Next to Someday without the person's action in
exactly one case: its current formulation is undecided at its park-due instant
(threshold + 7 days, later if extended or floored). No other automatic change to any
task's GTD state, title, notes or organization is allowed by this feature, and the
AI navigator never writes without confirmation.

Auto-park:

- runs server-side in the existing maintenance thread for activated owners with
  server sync, and on-device for account-less iOS;
- is idempotent per formulation: a second park of the same formulation, from any
  device or the server, has no effect and produces no sync conflict;
- is skipped when the formulation, state or extension changed after the park
  became due (re-checked under the owner lock);
- never runs for an owner who has not seen the one-time auto-park explainer shown at
  the first app or web open after the flag is switched on (FR-051; the first
  acknowledgement on any device is recorded on the server, account-less iOS records it
  on the device);
- never fires earlier than: 14 days after that acknowledgement (FR-016), 7 days after
  a threshold change (FR-039), 7 days after a due-date change on that task or a
  time-zone change (FR-046), 7 days after the sweep resumes from a gap of 24 hours or
  more (flag off and on again, outage); and never without the "moves to Someday
  tomorrow" marker having been derivable for the preceding 24 hours (SC-006);
- keeps project, tags, notes, due date and priority, and records the park instant
  and its origin on the task;
- yields to an explicit card decision the person made, on another device, on the same
  formulation before the park instant (spec edge case "Offline for a long time"),
  restoring the clock the park recorded; plain edits never reverse a park, and plain
  edits queued before such a decision do not defeat the yield;
- is keyed per park attempt (`auto-park:<task>:<formulation>:<from_revision>`), so a
  formulation that becomes due again after a yield is parked again instead of being
  swallowed as an idempotent replay.

Clock bookkeeping that is not a GTD state change — re-anchoring clocks at activation,
repairing a missing clock, the floors above — does not bump a task's revision, so it
never conflicts with a person's pending edits.

The server's park time is authoritative once synced. A device whose clock runs ahead
never causes an early server park.

### 4. Cadence, time zone and the review notification are product state

ADR-0006 B-09 is lifted: review day/time (default Friday 16:00), IANA time zone and
threshold are stored per owner. iOS schedules at most one local notification per
week, skipped when a counted review (FR-029) happened in the preceding 6 days;
the web sends none. No streaks, no escalation, no follow-up reminders.

The stored zone changes only when a device's own zone changes, so two signed-in
devices may sit in different zones. The stored zone then governs classification
(markers and parks agree with the server); the review slot is a local wall-clock day
and time that each device evaluates in its **own current zone**, so a device's
notification fires, and its "next review" reads, at the chosen time where that device
is.

### 5. AI navigator: on-device first, cloud only under per-owner consent

On Apple platforms the navigator uses Apple's on-device model when available. When
it is unavailable the person chooses between a separately downloaded on-device
model and the cloud provider. Every cloud request requires a current, per-owner,
per-provider consent that the server re-checks at request time; revocation stops
requests immediately; the person can see and revoke a stored consent even while the
flag is off. The cloud path follows the existing provider-adapter and cost-admission
conventions (`BRAIN_BUDDY_*_PROVIDER/_MODEL/_API_KEY_ENV`, per-call cost admission,
rate limiting) under its own `BRAIN_BUDDY_REVIEW_NAVIGATOR_*` settings and limits. The
HTTP adapter lives with the existing one in `backend/app/ai/`, outside the Tasks module,
and reaches `ReviewService` through a port, so ADR-0001 rule 9 ("network clients are
only concrete adapters in Execution or Capture") holds without an amendment; the
Tasks module keeps only the request schema, validation and consent rules. The provider
call never runs under the process-wide task command lock (reserve, call, settle).
The exact navigator input set is fixed by spec FR-019 and enforced by a strict request
schema. Proposal text never enters logs, metrics or events.

Russian is not listed as supported by Apple's on-device model (16 languages on iOS
26.x and 27, per secondary sources; unverified, see the feature's
`research-on-device-model.md`); it is treated as unsupported, so the choice in FR-023
is the designed path for Russian tasks. Routing is per task language, never silently
to the cloud.

A cloud provider configured without its credentials fails the backend's startup
rather than degrading silently (constitution I); unlike title completion, the
navigator never runs as a quietly disabled provider unless the operator chose
`disabled`. Because that also stops a serving machine restarted during a secrets
change, the operating rule is: set the navigator provider to `disabled` before rotating
or removing its key, and back afterwards (`.env.example`, deploy runbook).

A downloadable on-device model (recommended: Core AI + Qwen3-1.7B 4-bit in an
Apple-hosted Background Assets pack, iOS/macOS 27+ only) would be the first third-party
runtime dependency in the iOS app (`ios/AGENTS.md`: "No third-party dependencies").
**This record does not grant that exception.** A second ADR, drafted with the slice
that adds the model (PR-09) and approved by the owner as a late slice (research NC-2), amends
that rule for one vetted package in the app target only (never `BrainBuddyCore`),
records the license review (model Apache-2.0, runtime BSD/MIT), pinned versions and
asset-pack provenance. Until then the navigator ships with Apple's model and the
consented cloud provider behind the `NavigatorModel` protocol. Apple Private Cloud
Compute, if ever used, counts as a cloud provider requiring FR-024 consent (research
owner decision NC-4).

### 6. Rollout

All of the above is behind the runtime-managed flag `weekly_review` (default OFF,
ADR-0019 store). As for voice, exposure control is not authorization: the flag gates
reads, the navigator and the exposure part of the sweep, while writes that finish work
a client already started (queued decisions, sessions, acknowledgements) and consent
revocation keep working when it is off, so a rollback never strands a device's queued
work. While the flag is off, web and iOS keep today's non-interactive
"coming later" entry and the design skill keeps describing that state; the skill text
and its validator test change to "Weekly Review is flag-gated: a non-interactive
`coming later` entry while the `weekly_review` flag is off" in the same
slice that accepts this record. The Mac shows a non-interactive "Weekly review ·
coming later" row until Mac↔backend sync exists (separate spec).

### 7. Client-supplied record ids: one bounded exception to constitution IV

Constitution IV says accepted client-supplied ids are "observability labels only and
never authorization or idempotency inputs". Offline iOS must create review sessions,
decisions, bulk releases, follow-up tasks and formulations before the server sees them,
so the server adopts the client's id (fixed `<prefix>_<uuid>` shape, validated, owner-
scoped). Replay stays keyed on the Idempotency-Key. The owner decided on 2026-10-06
(offline-sync CHK023) that a retry arriving after the server's 24 h idempotency
retention — a lost response followed by a long offline period — is a success when the
stored record matches it. After the retention the Idempotency-Key is gone, so the
client id is then the only thing that identifies the retry: it becomes a
**de-duplication** input. This record accepts that as a bounded exception, and only
in this form:

- it applies to four records only — review decisions, review sessions, bulk releases
  and session progress (`progress_id`) — listed in
  `specs/020-weekly-review/contracts/http.md` "Retry after the idempotency retention";
- the lookup is `(owner_id, id)`; a client id is never an authorization input, and an
  id of another owner behaves as unknown;
- it matches only when the request's identifying fields equal the stored record's
  (for progress, the SHA-256 of the canonical body); a match writes nothing and
  returns the stored result, and it is checked before revision and eligibility;
- any mismatch is 409 `id_conflict` and writes nothing;
- the id keeps its fixed UUID shape, so no content travels in it.

Rejected alternative: a longer idempotency retention. It only moves the window (a
device can stay offline for weeks), keeps response bodies with content longer, and
grows `idempotency_records` for every owner. The constitution's wording is not
changed by this record; if a later feature needs the same rule, the constitution
should be amended instead of repeating this exception.

## Consequences

**Positive.** The core rule ("no formulation sits in Next unexamined") holds even
when reviews are missed. Decisions, Undo and auto-park are atomic with the task
change. The review works offline on iOS and account-less. Parity is testable from one
rule and one vector file.

**Negative.** The Tasks module grows (formulation clock, review records, navigator
schema, validation and consent rules; the HTTP adapter stays in `backend/app/ai/`). `TaskResponse` and the iOS `TaskDTO`/`TaskRecord` gain fields; the iOS
`StoreDocument` moves to version 2. The maintenance thread gains a per-owner sweep.
A due date that keeps moving forward defers the rule (accepted; measured, not
blocked).

**Risks.** Clock skew between devices and server (bounded by server authority);
the first automatic state change could surprise people (mitigated by the one-time
explainer before any park, the 24-hour marker, the "while you were away" screen,
one-tap return, the 14-day grace and onboarding copy); on-device model language
coverage (Russian unverified); account-less parks have no remote kill switch
(mitigated by shipping the account-less switch off in Release until the synced path
has run clean, and a per-launch cap on device parks).

## Alternatives considered

- **Separate Review module and store (ADR-0001 as written).** Rejected: no atomic
  decision + task write, no Undo without compensation, a cross-store purge/export.
- **Derive the clock from `updated_at` / `waiting_since`.** Rejected: notes, tags and
  project edits bump `updated_at`, and iOS Undo re-stamps `updatedAt` with a new
  issue time, so the clock would restart on edits FR-003 says must not restart it.
- **No auto-park, markers only.** Rejected by owner decision D1: the rule must hold
  when reviews collapse.
- **Auto-park client-side only.** Rejected: FR-014 requires parking with no client
  open for synced accounts, and two clients would race.
- **A fifth "Stalled" list.** Rejected: ADR-0006 four open lists; markers are derived.
