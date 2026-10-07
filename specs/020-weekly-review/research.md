# Research: Weekly Review (020)

**Feature**: `specs/020-weekly-review/` · **Date**: 2026-10-05 · **Plan**: [plan.md](plan.md)

Format per decision: Decision / Rationale / Alternatives considered. Facts are cited to
the current repository; where a fact could not be verified it says so.

## Owner decisions (formerly open questions NC-1 – NC-4)

Resolved by the owner (Max) on 2026-10-05; spec.md updated accordingly.

- **NC-1 — late extension**: measured from the extension day. `ask_at = extended_at + 7 d`,
  `park_due_at = extended_at + 14 d` (FR-009, FR-012, US1-7). Example: extended on
  day 18 of a 14-day threshold → asks again on day 25, parked on day 32. The design
  frame M-04 "Keep until Thu 15 Oct" (with today Fri 9 Oct) was a copy slip: it must
  read Fri 16 Oct (corrected in design.md and the M-04 mockup on 2026-10-06).
- **NC-2 — downloadable on-device model**: approved as a **late slice** (PR-09). The
  owner approves the iOS third-party dependency exception (to be recorded in its own ADR
  with PR-09) and a download of roughly 1–2.6 GB; the final model (Qwen3-1.7B 4-bit vs
  Gemma 4 E2B) is chosen by the offline SC-005 evaluation
  (`research-on-device-model.md` §3). Until PR-09 lands, and on iOS/macOS 26, Russian
  tasks use the consented cloud choice (FR-023 (b)). If no candidate passes the
  evaluation, the fallback in `research-on-device-model.md` §3.5 needs an owner spec
  amendment.
- **NC-3 — input larger than the context window**: drop the **middle** of the notes,
  keep the beginning and the most recently added lines, keep every other field intact,
  and show "part of the notes was not considered" (FR-019). Budget with
  `tokenCount(for:)` (iOS 26.4+; a 3-characters-per-token estimate before that). The
  cloud path receives exactly the same reduced input.
  *Planning refinement (campaign 1, 2026-10-06; the owner decision itself is unchanged)*:
  to make "exactly the same reduced input" literally true, the reduction uses one shared
  character budget for every model (contracts/navigator.md §1 `reduce_notes`); token
  counting is kept only as a guard.
- **NC-4 — Apple Private Cloud Compute**: counts as a cloud provider under FR-024
  (consent naming "Apple Private Cloud Compute"); not built in this feature
  (FR-023 note). The `NavigatorModel` protocol admits it later without changes elsewhere.

### Owner decisions of 2026-10-06 (planning-review campaign 1 product decisions)

Recorded in spec.md Clarifications "Session 2026-10-06".

- **PD-1 — summary counts**: two new counters, "Kept as is" (keep waiting, keep in
  Someday) and "Moved to Next" (follow-up, return to Next from Waiting or Someday); ten
  counts in all (FR-033, US4-9, data-model E4 `review_counts_as`, design M-22).
- **PD-2 — skip-everything review**: shown as "Review done", recorded as
  `completed_empty`; it does not count toward regularity, restart postponement or
  notification suppression (FR-029, data-model E3). Derived by planning, for
  consistency: "Last review" (FR-038) uses the same counted-review instant.
- **PD-3 — first exposure**: a one-time auto-park explainer at the first app or web
  open after the flag is switched on (FR-051, design M-26 / D-05), independent of the
  onboarding; the 14-day grace starts then; first acknowledgement on any device wins and
  is stored on the server (account-less iOS: on the device); auto-park never runs for an
  owner who has not seen it. Ships in increment 1 with auto-park (plan PR-02/PR-04/PR-05).

## R1. Where Weekly Review lives in the backend

- **Decision**: inside the Tasks module. New files
  `backend/app/modules/tasks/formulation.py` (pure rules),
  `review_domain.py` (records), `review_repository.py` (SQL for the new tables, a
  mixin composed into `TaskRepository` so it shares `command_lock`, connection and
  `migration_ledger`), `review_service.py` (`ReviewService`: decisions, undo,
  auto-park, sessions, queues, bulk release, settings), `navigator.py` (provider
  adapter + validation). Three new routers, `backend/app/api/review.py`,
  `review_navigator.py` and `review_flow.py`, all mounted (with the container wiring
  and the flag) by slice PR-02 so later slices only add their own files
  (contracts/http.md header).
- **Rationale**: a decision changes a task and records itself atomically under one
  owner lock and one idempotency record (`_serialized_write`,
  `backend/app/modules/tasks/service.py:64`). Undo needs the pre-decision snapshot in
  the same transaction. The architecture rubric expects task-tracker behaviour in
  `app/modules/tasks/`; import-linter already layers
  `app.modules.tasks.service → app.modules.tasks.repository`
  (`backend/pyproject.toml` import-linter contracts).
- **Alternatives**: ADR-0001's separate `review/` module with its own store
  (no atomicity, Undo needs compensation, second purge/export path); a
  `weekly_review/` package (trips the forward guard in
  `backend/tests/test_voice_workflow_architecture.py:250`, which requires every file
  under such a path to import `app.workflows.voice_brain_dump`; this text review has no
  voice operation, ADR-0002's `weekly_review_voice` stays out of scope).
- **Naming constraint**: no path token `weekly_review` in non-voice code, and no file
  name containing the ASK tokens of `scripts/classify_path_risk.py` (`session`, `user`,
  `permission`, `migration`, …): e.g. `review_service.py` not `review_session.py`,
  `ReviewReminderScheduler.swift` not `NotificationPermission.swift`.

## R2. Formulation clock storage

- **Decision**: explicit fields on `TaskDocument` / `TaskRecord`
  (data-model E1), maintained by every writer.
- **Rationale**: there is no state-changed-at or title history today
  (`backend/app/modules/tasks/domain.py:86-107`). `updated_at` moves on notes, tags,
  project and priority edits (FR-003 forbids that restarting the clock), and iOS Undo
  re-stamps `updatedAt`/`waitingSince` with the new issue time
  (`ios/BrainBuddy/Screens/Process/ProcessInboxScreen.swift` `undo`), so neither can be
  the clock.
- **Alternatives**: an event log of title/state changes (more storage, still needs a
  derived current value); clock only on the server (iOS must work offline and
  account-less, FR-040).

## R3. Shared normalisation and parity oracle

- **Decision**: `formulation_key` = NFKC → punctuation (P*) to space → Python
  `split/join` whitespace → Python `casefold` (contracts/formulation-clock.md §1). It
  is `normalize_task_name` (`backend/app/modules/tasks/repository.py:43`) plus one
  step. Swift reuses `NameNormalizer.nfkc/collapsed/caseFolded`
  (`ios/BrainBuddyKit/Sources/BrainBuddyCore/NameNormalizer.swift`), which already
  reproduces Python casefold scalar for scalar on Linux and Apple platforms. The web
  ports the same exception table from that file into
  `frontend/src/features/review/formulation.ts` (JS has no casefold;
  `toLowerCase` differs for `ß`, final sigma and others).
- **Parity**: one JSON vector file, three byte-identical copies, drift test in pytest
  (contract §6). The repo's existing parity pattern is inline vectors with a lockstep
  comment (`NameNormalizerTests.swift`, `SmartAddWebParityTests.swift`); a shared file
  is stronger because drift fails CI mechanically.
- **Alternatives**: server-only key with a "preview" endpoint for the web note
  (an extra round-trip per keystroke; offline iOS still needs its own); ignoring symbols
  as well as punctuation (would make "C++" vs "C" cosmetic).

## R4. Backend activation, grace and backfill (FR-016)

- **Decision** (revised after owner decision PD-3, 2026-10-06): per-owner activation
  happens when the owner first acknowledges the auto-park explainer (FR-051) on any
  device: `POST /review/explainer/acknowledge` sets `review_settings.activated_at` to
  the server's `now` if it is null (first wins). In the same transaction, under that
  owner's lock, every Next task gets the **activation clamp**: a null clock starts at
  `activated_at`; an existing clock keeps its formulation id but
  `formulation_started_at = max(started_at, activated_at)`; and every Next task gets
  `formulation_park_floor_at ≥ activated_at + 14 d` (formulation-clock §3). These are
  clock-bookkeeping writes that do not bump `revision`. Neither the sweep nor any other
  endpoint activates an owner, and nothing parks and no marker shows before activation.
  Account-less iOS applies the same transition as a post-replay step keyed on
  `local.activatedAt`.
- **Rationale**: the flag is per user (ADR-0019 SELECTED_USERS), so activation is per
  owner. Clocks are maintained while the flag is off (R5), so without the clamp a user
  enabled weeks after the backend deploy would see every old task ask on day one — the
  contradiction campaign 1 found between this record and R5. With the clamp nothing asks
  before `activated_at + T` and nothing parks before `activated_at + 14 d` (FR-016, spec
  edge case "Huge backlog on first use"). Keeping the formulation id (rather than
  minting new ones) means device and server agree without exchanging ids. Restart mode
  (FR-017) still handles a stale Next later.
- **Alternatives**: activation at the first gated call or sweep (the original plan:
  auto-park could run for an owner who never saw the rule, rejected by the owner);
  activation at onboarding completion (owner chose the earlier, independent explainer);
  backfill from `created_at` (dozens ask on day one); restarting every formulation with
  a new id (forces id exchange with offline devices for no benefit); a global
  deploy-time migration (wrong for a per-user flag).

## R5. Server clock maintenance even while the flag is off

- **Decision**: the clock fields are maintained by every task command regardless of
  the flag; only exposure (routes, markers, sweep effects) is gated.
- **Rationale**: keeps one code path; turning the flag on later finds a clock on every
  task, which the activation clamp (R4) then re-anchors so nothing asks on day one; the
  FR-016 floor prevents early parks. A flag turned off and on again later is covered by
  the sweep-gap floor (formulation-clock §3), so parks that became due while the flag
  was off are preceded by a visible marker.
- **Alternatives**: gate maintenance too (two code paths, mass backfill at enable).

## R6. Extension arithmetic

- **Decision**: `ask_at = max(start + T, extended_at) + 7 d`;
  `park_due_at = max(ask_at + 7 d, floors)` (NC-1, owner decision).
- **Rationale**: matches US1-7 ("clears for 7 days") and M-02's dates; equals FR-012's
  "+14" when extended on the threshold day.
- **Alternatives**: threshold-relative (FR-012 literal): an extension made on day 20
  would clear the marker for one day only, which reads as broken.

## R7. Decisions as one composite task command

- **Decision**: `POST /tasks/{id}/decisions` (`ReviewService.decide`, under the
  existing serialized-write discipline) validates, applies the task change, writes the
  decision (and receipt / follow-up task), and stores one idempotency record whose
  response is the whole `DecisionResponse`. `_serialized_write`
  (`service.py:64-79`) is typed for `TaskService` (it reads `service.task_repo` and
  calls `service._reconcile_idempotent_result`), so PR-02 generalises it to a small
  `SerializedWriter` protocol that `TaskService` and `ReviewService` both implement;
  `ReviewService` composes `TaskService` (calling its undecorated task-change
  helpers inside its own write, so a decision stays one transaction) and has its own
  `_apply_idempotent_record` for the new prefixes, spelled exactly as in
  contracts/http.md §9 (`decide_task:`, `undo_decision:`, `auto-park:`,
  `bulk_release:`, `undo_bulk_release:`, `review_session:`, `review_settings:`,
  `explainer_ack:`, `park_ack:`), each with its own result reconstructor (the task service's default
  branch validates the stored body as a `TaskDocument` and would raise on a composite
  response), so the repair-on-replay guarantee covers them; one test reconciles a
  record of each prefix. Dependency direction `review_service → service → repository`,
  extended so in the import-linter layers contract. Client-supplied ids
  (`decision_id`, session `id`, bulk `id`, `follow_up_task_id`, `new_formulation_id`)
  are **new with this feature** (no existing task route takes a client id:
  `TaskCreateRequest`, `schemas/tasks.py:99-118`, has none; campaign 1 cited
  `schemas/tasks.py:122` wrongly, which is `SmartAddClassificationRef.id`). They are
  fixed-shape opaque labels (`<prefix>_<uuid>`, ≤ 64 chars, contracts/http.md
  "Client-supplied ids") so offline iOS records and their server copies share ids; the
  Idempotency-Key stays the only replay input (constitution IV).
- **Rationale**: FR-011 requires the existing idempotent, owner-serialized
  operations; one request per iOS command (the `GTDCommand` invariant); atomic Undo.
- **Alternatives**: client issues the plain task command then a separate "record
  decision" call (two requests, can half-fail, Undo cannot be exact).

## R8. Undo (FR-048)

- **Decision**: server-side undo by snapshot (`review_decisions.undo.task_before`),
  allowed while the task revision is unchanged; the decision row is deleted. Clients
  show it ~5 s. iOS compaction cancels an unsent decision + undo pair. Snapshots are
  nulled after 7 days.
- **Rationale**: "restores the task's previous state, title and formulation clock"
  cannot be expressed with existing inverse commands (moving back to Next would start a
  *new* formulation). The iOS Process inbox inverse-command Undo stays as is; Inbox
  items are not decision rows, so their Undo is that inverse command plus an
  `inbox_processed_delta: -1` on the session. The web Inbox step (new UI, D-03 "Inbox
  step") offers the same inverse-command Undo. A follow-up created by a decision is
  deleted by Undo only while its own revision is unchanged (its revision is stored on
  the decision), so an edit made to it elsewhere is never lost.
- **Alternatives**: inverse commands (loses the clock); time-limited server undo
  (an offline iOS undo may be pushed late; revision equality is the real guard).

## R9. Auto-park authority, idempotency and clock skew

- **Decision**: the server sweep parks with deterministic key
  `auto-park:<task_id>:<formulation_id>:<from_revision>` and re-checks under the owner
  lock; FR-013's "no additional effect" is the state re-check, and the revision in the
  key keeps a second, legitimate park of the same formulation (after a yield reversal
  followed by a cosmetic reformulation, or by a decision and its Undo) from being
  swallowed as a replay within the 24 h idempotency retention
  (`repository.py:39`; campaign 2). Devices
  may send `POST /tasks/{id}/auto-park`; the server parks only if **its own** evaluation
  is `park_due`, otherwise returns `applied: false` (200). Devices record issued parks
  per formulation and never re-issue; signed in and online, a device applies a park
  locally only after `applied: true`, and evaluates due parks with the last observed
  server clock offset (`server_now`), so a skewed device clock causes no visible early
  park (ios-commands §5). A **card decision** whose `client_decided_at`
  precedes `parked.at`, made on the same formulation with an `expected_revision`
  between `parked.from_revision` and the current revision, reverses the park (yield
  rule) by restoring the clock snapshot the park stored (`parked.clock_before`), so the
  formulation is not closed twice and an offline `extend` is still accepted. The
  revision range (not equality) is needed because iOS takes `expected_revision` from the
  base at push time and replays earlier queued plain edits onto the parked task first
  (`PushPlanner.swift:131-140`, `SyncEngine+Push.swift:270-291`). Plain edits and moves
  never yield: there is no `client_occurred_at` on `PATCH`/transitions; they 409 and are
  replayed onto the parked task by the existing iOS refetch path (contracts/http.md §1).
- **Rationale**: US2-6 (exactly once, no conflict), edge case "Clock skew" (server
  authoritative), edge case "Offline for a long time" (explicit earlier decision wins).
  `client_decided_at` is only compared against a park the server itself made, so a
  wrong device clock can at worst let one explicit decision win over a park, never
  cause one.
- **Alternatives**: last-writer-wins (sync conflict prompt, violates FR-013);
  expected-revision on auto-park (two devices' parks would 409 each other).

## R10. Where the sweep runs

- **Decision**: `_run_review_maintenance_sweep(container)` in `backend/app/main.py`,
  invoked from the existing privacy-maintenance thread loop
  (`_start_privacy_maintenance_thread`, `main.py:156`, 60 s default via
  `BRAIN_BUDDY_AGENT_RETENTION_SWEEP_INTERVAL_SECONDS`) and at startup from
  `_run_maintenance_sweep` (`main.py:85`). It is wired as its own `try/except` block
  inside `_run_privacy_maintenance_sweep` without changing that function's 3-tuple
  return (asserted by `tests/test_crt_receipt_retention.py:364`). Candidates come from
  one query over Next tasks (`tasks.state = 'next'`) run **outside** the lock and
  grouped by owner; because the clock fields are payload-only, that query cannot select
  park-due tasks, so every Next task of every exposed owner is parsed and classified in
  Python each run — O(Next tasks) per minute, fine at beta scale, with an optional
  per-owner watermark left to the implementer (contracts/http.md §9 "Scan cost"); each owner is then processed under
  `command_lock(owner_id)` in short transactions of at most 50 tasks, re-reading first
  (the voice sweep pattern, `workflows/voice_brain_dump/service.py:560-590`). The lock is
  one process-wide `RLock` (`repository.py:66-87`), so it blocks every owner's task
  writes while held: no provider or network I/O ever runs under it. The sweep has a
  retention part that runs for every owner with review rows regardless of the flag, and
  an exposure part (auto-park, repair, gap floor) for activated owners whose flag is
  effective. `FeatureFlagService.is_effective(name, user)`
  (`backend/app/services/feature_flag_service.py:145`) takes a `User`, so the sweep
  resolves each owner id to its `User` before asking (contracts/http.md §9). Owner
  failures are logged with `type(exc).__name__` and a reason code only.
- **Rationale**: no new thread, no new env var; threads are already disabled in tests
  unless `BRAIN_BUDDY_ENABLE_VOICE_SWEEP_IN_TEST=1`, and tests call the sweep function
  directly, as `tests/test_crt_receipt_retention.py:364` does. A 60 s cadence parks
  within a minute of `park_due_at`; SC-006 depends on the 24 h marker, not on sweep
  latency.
- **Alternatives**: a new thread and interval variable (more config, same effect); park
  lazily on read (FR-014 requires parking with no client open).

## R11. Time zone

- **Decision**: store the owner's IANA zone in `review_settings.time_zone`; clients
  send the device zone with the explainer acknowledgement (activation), at onboarding,
  and afterwards only when the device's **own** zone changes (its last observed zone,
  data-model E10 / E11), never because it differs from the pulled one (US5-5; owner
  decision 2026-10-06: the earlier "whenever it differs" rule let two signed-in devices
  in different zones alternate the setting, each change raising every due-dated Next
  task's park floor). Sending it at
  activation matters: activation can precede onboarding by weeks, and until a zone
  arrives the server would compute `due_start` at UTC midnight while the device uses
  its own zone (campaign 2). Backend uses `zoneinfo` for
  `due_start` and the review slot. iOS uses `TimeZone.current` for display, and the
  stored zone (signed in) or the device zone (account-less) for markers
  (ios-commands §6); web uses `Intl.DateTimeFormat().resolvedOptions().timeZone` for
  display and the server's derived instants for markers.
- **Rationale**: no user time zone exists anywhere today (`backend/app/schemas/auth.py`
  `User` has none; all backend times are UTC). A device in another zone than the stored
  one keeps classifying with the stored zone, so its markers agree with server parks. A zone change moves `due_start` and so
  can bring a due-anchored park forward by up to a day; every `time_zone` change
  therefore applies the FR-046 7-day floor to due-dated Next tasks
  (formulation-clock §3), keeping the 24-hour marker of SC-006 intact.

## R12. Feature flag and exposure

- **Decision**: runtime-managed flag `weekly_review`, default OFF: add to
  `KNOWN_FEATURE_FLAGS` (`backend/app/core/config.py:86`), `MANAGED_FLAGS` and
  `_POST_ADR_0019_DEFAULT_OFF_FLAGS` (`backend/app/repositories/feature_flag.py:83,100`)
  and the `_upgrade_adr_0019_store` whitelist (line 426). Web reads it with
  `hasFeatureFlag(user, "weekly_review")` (`frontend/src/api/auth.ts:21`); iOS with
  `MeDTO.featureFlags`. Account-less iOS uses the build switch `BBWeeklyReviewLocal`,
  `NO` in Release until the synced path has run clean for one threshold cycle
  (contracts/ios-commands.md §8), because account-less parks have no remote kill
  switch.
- **Rationale**: ADR-0022 requires a flag for a significant capability; ADR-0019 and
  `docs/decisions/0021-runtime-managed-task-title-autocomplete.md` require an ADR for a
  new managed flag (ADR-0027 draft §6). (Two files carry the number 0021, so it is
  cited by file name.)

## R13. AI navigator: models and providers

### Cloud provider

- **Decision**: OpenAI chat completions, model `gpt-4o-mini`, through a new adapter
  `backend/app/ai/review_navigator.py` beside and modelled on
  `backend/app/ai/title_completion.py` (official API origin, key read from the env var
  named by `*_API_KEY_ENV`, `disabled` default, `deterministic` only in TEST), built by
  `container.py` and injected into `ReviewService` through a `NavigatorProvider`
  protocol declared in `backend/app/modules/tasks/navigator.py`, which keeps only the
  schema, `reduce_notes`, validation and consent rules. Reason (campaign 2): ADR-0001
  rule 9 (`docs/decisions/0001-…md:85-86`) allows network clients only as concrete
  adapters in Execution or Capture, and the repository's precedent keeps the OpenAI
  adapter outside the modules tree; keeping egress out of the module that owns
  canonical task records also keeps its blast radius small.
- **Cost admission and the process-wide lock**: the per-call and daily caps are
  admitted in three steps — reserve under `command_lock` (read `navigator_usage`,
  reject or write `calls + 1` and the estimated cost), call the provider with **no**
  lock held, settle the actual cost (or release the reservation on failure) under the
  lock again — because `command_lock` is one process-wide `RLock`
  (`repository.py:67-87`) and an 8 s call under it would stall every owner's task
  writes (contracts/http.md §7). The voice reconciler reserves before its provider call
  in the same way (`workflows/voice_brain_dump/service.py:1378`). New env
  vars (documented in `.env.example`):
  `BRAIN_BUDDY_REVIEW_NAVIGATOR_PROVIDER=disabled`,
  `_MODEL=gpt-4o-mini`, `_API_KEY_ENV=OPENAI_API_KEY`, `_TIMEOUT_SECONDS=8`,
  `_MAX_INPUT_TOKENS=6000`, `_MAX_OUTPUT_TOKENS=300`, `_MAX_COST_USD=0.01` (per-call admission from token
  estimate, the reconciler's admission pattern), `_MAX_DAILY_COST_USD=0.20` (per owner,
  table `navigator_usage`). Rate limit: 20 calls / 10 min per owner via
  `backend/app/core/rate_limit.py`.
- **Missing credentials — corrected in campaign 1**: title completion does **not**
  fail at startup without a key. `build_title_completion_provider`
  (`backend/app/ai/title_completion.py:241-259`) falls through to
  `DisabledTitleCompletionProvider.from_settings` (reason "provider credentials
  missing"), which raises only when `complete()` is called; the container
  (`backend/app/container.py:384-392`) wires it without a check, and
  `TaskTitleAutocompleteSettings` (`backend/app/core/config.py:475`) has no validator.
  The STT and reconciler builders degrade the same way. The navigator deliberately
  differs: `_build_review_navigator_provider(config)` in the container **raises**
  (naming the variable, never its value) when the provider is `openai` and the key
  variable is unset or empty, when it is `deterministic` outside TEST, or when it is
  unknown. Only `disabled` produces the disabled provider, which the API reports as
  `available: false` / `503 navigator_disabled` and the clients show visibly. Reason:
  constitution I requires that remote processing without required configuration
  "fail visibly instead of silently ... degrading"; a deploy that fails its health
  check never reaches users, while a silently disabled navigator would look like a
  product bug. The first failing test of PR-07 is "container build raises without the
  key". Blast radius (campaign 2, kept): the same raise also stops an already-serving
  machine that restarts during a secrets change, taking every route down; the runbook
  therefore sets the provider to `disabled` before any key rotation or removal and back
  afterwards (plan rollback section, `.env.example`, ADR-0027 draft §5).
- **Rationale**: spec Assumptions: reuse the existing provider and cost-cap conventions;
  `gpt-4o-mini` is already configured for title autocomplete; the design's
  illustrative provider name is OpenAI. Per-owner daily cap bounds spend for the
  multi-tenant beta.
- **Alternatives**: reuse `BRAIN_BUDDY_TASK_TITLE_AUTOCOMPLETE_*` settings (couples two
  features' rollouts and caps); the voice reconciler's `gpt-4o` (higher cost for a
  1–3 line output).

### Consent

- **Decision**: per-owner, per-provider consent record (`navigator_consents`, E8),
  re-checked at request time **and** echoed in the request body (the title-completion
  pattern, `TitleCompletionConsent` in `backend/app/schemas/tasks.py:19`). Revocation
  is a `DELETE` that takes effect for the next request; iOS also blocks locally at once
  (offline revoke), and other devices stop once the revoke syncs (stated in the M-23 /
  D-04 offline copy). On the web the switch blocks the tab at once but shows "Turning
  off…" until the `DELETE` succeeds. A grant stored with a `consent_text_version` lower
  than the server's current one counts as absent, and the version is bumped whenever the
  FR-019 data list or the provider changes, so a changed data list always re-asks.
- **Rationale**: FR-024 needs "one-time" consent (so persisted, unlike title
  completion's per-request checkbox) and immediate revocation (so re-checked per
  request). No per-owner AI consent store exists today.

### Apple on-device model and the downloadable model (summary)

Full research, evidence flags and sources: `research-on-device-model.md` (separate
document; not repeated here).

- **Decision**: route per task, never per device. Classify the task text's language
  with `NLLanguageRecognizer` (first-party NaturalLanguage, app target); use
  `SystemLanguageModel` only when it is `.available` **and** the detected language is in
  `supportedLanguages`; keep the thrown `unsupportedLanguageOrLocale` as a backstop;
  otherwise show the FR-023 choice with the reason from `UnavailableReason` or
  "language not supported". **Russian is not listed as supported by Apple's model on
  iOS 26.x or iOS 27; this is unverified** (16 languages; secondary sources, primary
  pages blocked), so it is treated as unsupported and for the owner's Russian tasks the
  FR-023 choice is the designed path, not an edge case. The per-task routing works
  either way.
- **Decision (option (a), slice PR-09)**: as recommended in that file §3: Core AI +
  `CoreAILanguageModel` behind the iOS 27 `LanguageModel` protocol, Qwen3-1.7B 4-bit
  (Apache-2.0) in an Apple-hosted Background Assets pack downloaded on explicit request,
  gated by `#available(iOS 27, macOS 27, *)` and a memory check (with the
  `increased-memory-limit` entitlement); Gemma 4 E2B as the evaluation contender; MLX
  Swift as plan B. Deployment target stays iOS 26. A separate ADR (drafted with PR-09)
  amends `ios/AGENTS.md` "No third-party dependencies" for that one package, app target
  only, never `BrainBuddyCore`. Approved as a late slice (NC-2).
- **Why this does not block anything else**: the plan depends only on the
  `NavigatorModel` protocol (contracts/navigator.md §4) and on Core-side input
  assembly and output validation, which stay Linux-testable; PR-09 adds one
  implementation.
- **What this stage itself verified (2026-10-05)**, consistent with that file:
  - Apple documentation for `SystemLanguageModel` (fetched from developer.apple.com):
    iOS/iPadOS/macOS 26.0+; availability via `availability` with
    `.unavailable(.deviceNotEligible | .modelNotReady | …)`;
    `supportedLanguages: Set<Locale.Language>` and `supportsLocale(_:)`;
    `contextSize`; model versions for 26.0–26.3, 26.4 and 27.0; conforms to a
    `LanguageModel` protocol.
  - Apple Developer Forums thread 805378 (Nov 2025, Apple reply): the framework also
    requires the device/Siri language to be supported; Apple listed newly added
    languages (Danish, Dutch, Norwegian, Portuguese (Portugal), Swedish, Turkish,
    Chinese (Traditional), Vietnamese). Russian is not mentioned.
  - Search results attribute to WWDC 2026 coverage a statement that iOS 27's Apple
    Intelligence does not support Russian; the source pages (ukranews.com, 3dnews.ru)
    were **blocked by the egress proxy** and could not be read. Russian support therefore
    remains **unverified, likely unsupported**; the FR-023 choice path is mandatory for
    Russian tasks.
  - The navigator checks the **task's** language (`supportsLocale` with the detected
    language), not only the device language, before using Apple's model.

## R14. Logging and metrics (FR-044)

- **Decision**: logger `app.modules.tasks.review` (the tasks module has no logger today)
  emitting only ids, codes, counts and timings, and **not** the stall reason (one reason
  is behaviourally sensitive and platform logs outlive account purge). Supporting
  metrics and their sources: decision mix and stall reasons from `review_decisions`
  (purged with the account); re-stall rate from `consecutive_stalled_formulations`;
  returns from auto-park from `review_park_acks.returned_at` (data-model E6); due-date
  moves on Next tasks from a content-free log event `review_due_date_moved owner_id=…
  task_id=…` (no persisted counter, so nothing new to export or purge); median active
  review time from `review_sessions.active_seconds_by_step` (SC-004). Route and sweep
  errors log `type(exc).__name__` plus a reason code, never `str(exc)` or a validation
  error's `errors()`, which would render input values. A unit test asserts that a
  decision with sentinel strings in title, notes, waiting-for, extension reason and
  navigator I/O, and with a stall reason set, never shows any of them in captured log
  records, and the same test runs the sweep over a deliberately invalid task payload
  holding a sentinel string.
- **Alternatives**: event bus (none exists for tasks; ADR-0001 events are unbuilt).

## R15. Retention of content-bearing review data

- **Decision**: decision `undo` snapshots (they contain the old title/notes) and
  bulk-release clock snapshots are nulled 7 days after they were written, by the
  retention part of the sweep, which runs for every owner with review rows whether or
  not the flag is on for them (a rollback or cohort removal must not suspend the bound;
  test: decide, flag OFF, advance 8 days, sweep, snapshot null). `navigator_usage` rows
  go after 35 days on the same basis. Everything else lives for the account's life
  (intake §6 "same as tasks") and is exported and purged with the tasks store. The
  device copy follows the same 7-day bounds (`runLocalReviewMaintenance`,
  contracts/ios-commands.md §5), including account-less use, with one device-only
  exception: an unsent decision or bulk release that a queued Undo names keeps its
  `undoRetained` flag past 7 days (no snapshot is stored; data-model E10, ios-commands
  §5). Device-local model and
  navigator preference are deleted with the app.
- **Rationale**: Undo is a seconds-long affordance; keeping old content indefinitely in a
  second place has no purpose.
- **Limit (campaign 2)**: a *code* rollback to a build without the review sweep pauses
  this retention for the rollback window; the first sweep after roll-forward nulls
  every snapshot older than 7 days. `docs/data-retention.md` states the bound as
  "7 days; longer only while the backend is rolled back to a build without the review
  sweep" (contracts/http.md §8).

## R16. iOS persistence and sync

- **Decision**: `StoreDocument` v2 with a migration step from v1
  (`StoreDocumentCoding.swift:117`), review state pulled with
  `GET /api/review/state` after the existing full task pull
  (`SyncEngine+Pull.swift`), new commands per contracts/ios-commands.md.
- **Rationale**: the outbox already gives offline, ordered, idempotent replay. Campaign 1
  found that sessions created offline (SC-007) do need two additions, now in the
  contracts: client-supplied ids on sessions, decisions, bulk releases, follow-ups and
  formulations, so device and server name the same records; and a stated rule per
  review command (a `.review` conflict target, merged session progress, field-level
  settings retry, `replace_open: true` for offline-started sessions, session-less
  recording of a decision whose session is unknown) so nothing falls into the generic
  set-aside path (contracts/ios-commands.md §4).

## R17. iOS notification and widget

- **Decision**: one `UNCalendarNotificationTrigger` request with a stable identifier,
  rescheduled on settings change, review recorded, pull, and background refresh; skipped
  when `lastCountedReview` is within 6 days of the slot. Permission is requested once
  after onboarding "Continue" (M-12). Code lives in the app target
  (`ios/BrainBuddy/Review/ReviewReminderScheduler.swift`), not the package (Linux has no
  `UserNotifications`). Widget: `NextActionsEntry` gains `askCount`; medium/large
  chip uses `Link(destination: brainbuddy://review/decisions)`; small keeps
  `widgetURL` Next (design owner decision 3). `AppRouter.handle`
  (`ios/BrainBuddy/App/AppRouter.swift:141`) learns the `review` host.
- **Limitation (stated)**: a review done on the web is only seen by the phone after a
  pull; the existing background refresh (`BGAppRefreshTask`, ~30 min earliest) usually
  cancels the notification in time but cannot guarantee it.

## R18. Web structure

- **Decision**: new feature folder `frontend/src/features/review/` (route `/review`
  in `frontend/src/app/AppRoutes.tsx` behind a `ReviewGate` like `CrtGate`;
  `reviewHooks.ts` in `frontend/src/api/`; client functions in a new
  `frontend/src/api/review.ts` rather than `client.ts`, which is in the frontend
  mutation enforced tier list `frontend/mutation-enforced-scope.txt`). Markers render in
  `TaskRow` (`frontend/src/features/tasks/TaskListPage.tsx:1196`) via the existing
  `Chip`. Undo needs an action-capable toast: extend `ShellToastContext`
  (`frontend/src/components/shell/shellToast.ts`) with an optional action, keeping the
  current text-only call signature. A new Allure taxonomy rule for `/features/review/`
  is added to `frontend/src/test/allureTaxonomy.ts` (today tasks fall to the generic
  fallback).
- **Note**: the web has no Process-inbox flow or Undo toast today; the Inbox step on
  the web is new UI built from existing task commands (design D-03 "Inbox step").
- **Undo by keyboard**: while an Undo toast is visible, Ctrl+Z / Cmd+Z triggers it
  (outside text inputs), and the toast's accessible description names the shortcut, so
  keyboard users need not tab across the list (design "Keyboard and focus").
- **Form drafts** (FR-052): unsaved decision-form text is kept in `localStorage` under
  `bb.reviewFormDraft.v1.…` with the origin/account/task namespacing and lifecycle of
  the existing task-detail and CRT drafts, plus a `beforeunload` warning as
  `crtDraftCoordinator.ts` does (data-model E11).

## R19. Requirement-coverage gate for Swift-only requirements

- **Fact**: `scripts/check_requirement_coverage.py` scans only `backend/tests`,
  `frontend/tests`, `frontend/src` and suffixes `.py .ts .tsx .js .jsx` (lines 53-64).
  FR-047, FR-022, FR-023, FR-049, FR-036, FR-037 and the Mac part of FR-041 are
  satisfied only in Swift.
- **Decision**: extend the script to scan `ios/BrainBuddyKit/Tests` and `macos/Tests`
  with `.swift` (the iOS app target has no test target today; `ios/project.yml:181-185`
  runs only the package test targets), in slice PR-01 (ASK: `scripts/` and a
  `GUARDED_FILES` member; re-record `.specify/gate-integrity.json` with
  `python3 scripts/check_gate_integrity.py --update`). Add
  `python3 scripts/check_requirement_coverage.py specs/020-weekly-review` to the
  `check-specs` recipe in `Makefile` (ASK, guarded) in **PR-14**, the one landing
  point of the full-feature gate (it exits non-zero while any requirement is untested,
  so it cannot be on before the last slice; campaign 2 aligned this with the plan and
  quickstart). Per-slice tracing before that: PR-01 also adds a
  `--requirements 020-FR-001,020-SC-002,…` filter to the script, and each slice's
  verification runs it with that slice's `requirements` list from the PR-срезы
  manifest. For FR-041 (and any other requirement whose only lane is a recorded manual
  or macOS-host run) the slice's evidence file is required in addition to the name
  match, because no CI lane executes `macos/`.
- **Alternatives**: contrived backend/web tests naming iOS-only requirements (evidence
  that does not test the behaviour).
- **Ids are all gate-enforced**: the former lettered ids were renumbered FR-046 –
  FR-050, and campaign 1 added FR-051 and FR-052. Every FR-001 … FR-052 and
  SC-001 … SC-007 matches `DEFINITION_RE` (`check_requirement_coverage.py:44`) and the
  PR-срезы validator, so each must be named by a test (`020-FR-046`,
  `test_020_FR_046_…`) and listed in the `requirements` of the slices that realize it.
  Where the only honest evidence is a manual device check (app-target glue for FR-036,
  FR-037, FR-047), the test names the id and the evidence file says "manual" (plan
  Test strategy). PR-01 also updates `scripts/test_check_requirement_coverage.py` with a
  case proving that a Swift test naming an id satisfies the gate.

## R20. Mutation testing

- **Decision**: add `app/modules/tasks/formulation.py` and `review_service.py` to the
  observed backend scope (`[tool.mutmut] only_mutate` in `backend/pyproject.toml`) in
  PR-02; propose promotion of `formulation.py` to the enforced list
  (`backend/mutation-enforced-scope.txt`, guarded, ASK) after two clean nightly runs per
  the deploy-and-ci rules. Add `frontend/src/features/review/formulation.ts` to the
  Stryker observed `mutate` list (`frontend/stryker.config.json`). No Swift mutation
  tooling exists (ADR-0015 superseded); Swift parity relies on the shared vectors.

## R21. Time control in tests and the end-to-end route

- **Decision**: one clock seam. `TaskService`, `ReviewService` and the review sweep take
  an injected `clock: Callable[[], datetime]` from the container (default
  `app.utils.time.utcnow`), and every time-based pytest case uses one `frozen_clock`
  fixture that sets it, so no module reads its own `utcnow` binding. For Playwright,
  the compose stack runs on a real clock, and no test-only HTTP route is added (it would
  be a production-exposed surface). Instead PR-02 adds two `app.cli` commands that refuse
  to run unless `BRAIN_BUDDY_ENV=test`: `review-seed-aged-task` (creates a Next task
  for a user with a formulation started N days ago, and activates the owner) and
  `review-run-sweep` (runs `_run_review_maintenance_sweep` once). Playwright calls them
  through the existing `docker compose exec backend python -m app.cli …` seam
  (`frontend/tests/native-tasks-voice-brain-dump.compose.spec.ts`). The sweep logic
  itself is proven in pytest.
- **Alternatives**: a TEST-only clock offset header (touches every request path); a
  test HTTP endpoint (ASK surface in production builds); mocking the API in Playwright
  (does not exercise the sweep or the real markers).

## R22. Unsaved text and interruptions (constitution Principle V)

- **Decision**: FR-052. Forms keep a dirty flag per field; Close, swipe-down, Escape,
  Back, Leave and card or step changes confirm before discarding ("Keep editing" is the
  default). iOS blocks interactive sheet dismissal while dirty
  (`interactiveDismissDisabled`) and stores the text in `local.formDrafts`; the web warns
  on `beforeunload` and stores it in `localStorage` (R18). Drafts are keyed by task and
  formulation, so a draft never reappears on a newer wording, and expire after 7 days.
- **Rationale**: constitution Principle V ("Local drafts … MUST avoid data loss and warn
  before destructive navigation", and tolerate UI closure); the signed-off design
  discarded killed forms, which campaign 1 flagged as blocking.
- **Alternatives**: warning only, no persistence (loses text on an app kill); syncing
  drafts (sends unconfirmed text to the server for no user benefit).
