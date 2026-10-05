# Research: Weekly Review (020)

**Feature**: `specs/020-weekly-review/` · **Date**: 2026-10-05 · **Plan**: [plan.md](plan.md)

Format per decision: Decision / Rationale / Alternatives considered. Facts are cited to
the current repository; where a fact could not be verified it says so.

## Open owner questions

Four product-level items. The plan proceeds on the stated defaults; none blocks
increment 1 (US1/US2) on any platform. NC-2 – NC-4 affect only increment 2.

- **NEEDS CLARIFICATION (owner) NC-1 — when does an extension made late end?**
  FR-009/FR-012 say an extension moves "the threshold and the auto-park point" 7 days
  later ("+14 days if extended", i.e. relative to the threshold). US1-7 says "the
  marker clears for 7 days", and design M-02 shows dates relative to the extension day
  ("Kept on Mon 5 Oct. Asks again on Mon 12 Oct; moves to Someday on Mon 19 Oct").
  The two agree only when the extension is made on the threshold day. Question:
  *If someone extends on day 19 of a 14-day threshold, should it ask again on day 26
  (7 days after the extension, design) or day 21 (threshold + 7, FR-012)?* **Default
  used by this plan**: relative to the extension day, `ask_at = max(threshold instant,
  extended_at) + 7 d`, `park_due_at = ask_at + 7 d` (R6). If the owner chooses the
  other reading, only `formulation.py`/`Formulation.swift` and the vectors change.
- **NEEDS CLARIFICATION (owner) NC-2 — the downloadable on-device model.** Shipping
  one (FR-023 (a), FR-023a) means the first third-party runtime dependency in the iOS
  app, against `ios/AGENTS.md` ("No third-party dependencies"), a ~1 GB download, and
  (per the recommendation in `research-on-device-model.md` §3: Core AI +
  Qwen3-1.7B 4-bit via an Apple-hosted Background Assets pack, Gemma 4 E2B as eval
  contender, MLX Swift as plan B) availability only on iOS/macOS 27 with enough memory
  while the app keeps targeting iOS 26. Questions for the owner (that file's §3.6
  (iii), (iv)): *approve the dependency exception and a ~1 GB (Qwen3-1.7B) or ~2.6 GB
  (Gemma 4 E2B) download; accept that iOS 26.x users get only the cloud choice for
  Russian tasks?* **Default**: PR-08 ships Apple's model
  and the cloud choice (FR-022, FR-023 (b), FR-024 – FR-026); while PR-09 has not
  landed, M-06 offers only the cloud choice and "Not now". FR-023 (a) and FR-023a are
  satisfied only by PR-09, so increment 2 is not accepted against those two
  requirements until it lands or the owner amends the spec. If no candidate clears the
  SC-005 evaluation gate, the fallback in `research-on-device-model.md` §3.5 applies
  (cloud-only for unsupported languages; amend FR-023 (a) to "when a qualifying model
  is available") — a spec change only the owner can make.
- **NEEDS CLARIFICATION (owner) NC-3 — navigator input larger than the on-device
  context window.** FR-019 says the input is *exactly* title, notes, stall reason,
  project name and up to 20 sibling titles. Apple's on-device model has a 4,096-token
  window on iOS 26.x (8,192 on iOS 27) shared by instructions, schema, input and output
  (`research-on-device-model.md` §1 "Context window"), which leaves roughly 2,500
  tokens for notes on iOS 26. Question: *when the notes do not fit, should the
  navigator (a) use the most recent part of the notes and say so, (b) send fewer
  sibling titles first, or (c) refuse and offer the cloud/download choice?*
  **Default**: (a) — budget with `tokenCount(for:)` (iOS 26.4+; a 3-characters-per-token
  estimate before that), keep all fields except notes intact, truncate notes
  oldest-first, and show "Used the latest part of your notes." The cloud path uses the
  same budget rule with its own limit so both paths see the same input shape.
- **NEEDS CLARIFICATION (owner) NC-4 — is Apple Private Cloud Compute a "cloud
  provider"?** iOS 27 offers `PrivateCloudComputeLanguageModel` behind the same
  `LanguageModel` protocol (`research-on-device-model.md` §1 "iOS 27 additions"). Task
  content leaves the device, so it cannot satisfy FR-022; it would be a variant of
  FR-023 (b). It also needs a managed entitlement, Small Business Program enrolment and
  < 2M first-time downloads, and its Russian support is unverified. **Default**: treat
  PCC as a cloud provider requiring FR-024 consent naming "Apple Private Cloud
  Compute", and do not build it in this feature unless the owner asks; the
  `NavigatorModel` protocol admits it later without changes elsewhere.

## R1. Where Weekly Review lives in the backend

- **Decision**: inside the Tasks module. New files
  `backend/app/modules/tasks/formulation.py` (pure rules),
  `review_domain.py` (records), `review_repository.py` (SQL for the new tables, a
  mixin composed into `TaskRepository` so it shares `command_lock`, connection and
  `migration_ledger`), `review_service.py` (`ReviewService`: decisions, undo,
  auto-park, sessions, queues, bulk release, settings), `navigator.py` (provider
  adapter + validation). One new router `backend/app/api/review.py`.
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

- **Decision**: lazy per-owner activation. `review_settings.activated_at` is set the
  first time the `weekly_review` flag is effective for the owner and either a gated
  endpoint or the sweep sees it. Under that owner's lock, every Next task without a
  clock gets one started at `activated_at`, and every Next task gets
  `formulation_park_floor_at ≥ activated_at + 14 d`.
- **Rationale**: the flag is per user (ADR-0019 SELECTED_USERS), so "first becomes
  active" is per owner. Starting unknown clocks at activation means nothing "asks" on
  day one (spec edge case "Huge backlog on first use"); the floor guarantees FR-016 even
  for clocks maintained before activation. Restart mode (FR-017) still handles a truly
  stale Next after 21 days without a review.
- **Alternatives**: backfill from `created_at` (dozens ask on day one, contradicting
  the edge case; overstates age since titles may have changed); a global deploy-time
  migration (wrong for a per-user flag; makes flag-off users' data change).

## R5. Server clock maintenance even while the flag is off

- **Decision**: the clock fields are maintained by every task command regardless of
  the flag; only exposure (routes, markers, sweep effects) is gated.
- **Rationale**: keeps one code path; turning the flag on later finds mostly correct
  clocks; the FR-016 floor still prevents early parks.
- **Alternatives**: gate maintenance too (two code paths, mass backfill at enable).

## R6. Extension arithmetic

- **Decision**: `ask_at = max(start + T, extended_at) + 7 d`;
  `park_due_at = max(ask_at + 7 d, floors)` (NC-1 default).
- **Rationale**: matches US1-7 ("clears for 7 days") and M-02's dates; equals FR-012's
  "+14" when extended on the threshold day.
- **Alternatives**: threshold-relative (FR-012 literal): an extension made on day 20
  would clear the marker for one day only, which reads as broken.

## R7. Decisions as one composite task command

- **Decision**: `POST /tasks/{id}/decisions` (`ReviewService.decide`, decorated with
  the existing `_serialized_write`) validates, applies the task change, writes the
  decision (and receipt / follow-up task), and stores one idempotency record whose
  response is the whole `DecisionResponse`. `_apply_idempotent_record`
  (`service.py:1142`) learns the new command prefixes (`decide_task:`,
  `undo_decision:`, `auto_park:`, `bulk_release:`, `undo_bulk_release:`) so the
  repair-on-replay guarantee covers them.
- **Rationale**: FR-011 requires the existing idempotent, owner-serialized
  operations; one request per iOS command (the `GTDCommand` invariant); atomic Undo.
- **Alternatives**: client issues the plain task command then a separate "record
  decision" call (two requests, can half-fail, Undo cannot be exact).

## R8. Undo (FR-011a)

- **Decision**: server-side undo by snapshot (`review_decisions.undo.task_before`),
  allowed while the task revision is unchanged; the decision row is deleted. Clients
  show it ~5 s. iOS compaction cancels an unsent decision + undo pair. Snapshots are
  nulled after 7 days.
- **Rationale**: "restores the task's previous state, title and formulation clock"
  cannot be expressed with existing inverse commands (moving back to Next would start a
  *new* formulation). The iOS Process inbox inverse-command Undo stays as is.
- **Alternatives**: inverse commands (loses the clock); time-limited server undo
  (an offline iOS undo may be pushed late; revision equality is the real guard).

## R9. Auto-park authority, idempotency and clock skew

- **Decision**: the server sweep parks with deterministic key
  `auto-park:<task_id>:<formulation_id>` and re-checks under the owner lock. Devices
  may send `POST /tasks/{id}/auto-park`; the server parks only if **its own** evaluation
  is `park_due`, otherwise returns `applied: false` (200). Devices record issued parks
  per formulation and never re-issue. A decision whose `client_decided_at` precedes
  `parked.at`, made on the exact pre-park revision of the same formulation, reverses the
  park (yield rule).
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
  `_run_maintenance_sweep` (`main.py:85`). Candidates come from one indexed query
  (`tasks.state = 'next'`, index `idx_tasks_owner_state`) grouped by owner; each owner is
  processed under its own `command_lock`, re-reading first (the voice sweep pattern,
  `workflows/voice_brain_dump/service.py:560-590`). Flag effectiveness is checked per
  owner via `FeatureFlagService.is_effective`.
- **Rationale**: no new thread, no new env var; threads are already disabled in tests
  unless `BRAIN_BUDDY_ENABLE_VOICE_SWEEP_IN_TEST=1`, and tests call the sweep function
  directly, as `tests/test_crt_receipt_retention.py:364` does. A 60 s cadence parks
  within a minute of `park_due_at`; SC-006 depends on the 24 h marker, not on sweep
  latency.
- **Alternatives**: a new thread and interval variable (more config, same effect); park
  lazily on read (FR-014 requires parking with no client open).

## R11. Time zone

- **Decision**: store the owner's IANA zone in `review_settings.time_zone`; clients
  send the device zone at onboarding and on change (US5-5). Backend uses `zoneinfo` for
  `due_start` and the review slot. iOS uses `TimeZone.current` for display and markers;
  web uses `Intl.DateTimeFormat().resolvedOptions().timeZone`.
- **Rationale**: no user time zone exists anywhere today (`backend/app/schemas/auth.py`
  `User` has none; all backend times are UTC). Differences between device zone and stored
  zone last only until the next settings sync and never cause an early park (floors are
  instants).

## R12. Feature flag and exposure

- **Decision**: runtime-managed flag `weekly_review`, default OFF: add to
  `KNOWN_FEATURE_FLAGS` (`backend/app/core/config.py:86`), `MANAGED_FLAGS` and
  `_POST_ADR_0019_DEFAULT_OFF_FLAGS` (`backend/app/repositories/feature_flag.py:83,100`)
  and the `_upgrade_adr_0019_store` whitelist (line 426). Web reads it with
  `hasFeatureFlag(user, "weekly_review")` (`frontend/src/api/auth.ts:21`); iOS with
  `MeDTO.featureFlags`. Account-less iOS uses the build switch `BBWeeklyReviewLocal`.
- **Rationale**: ADR-0022 requires a flag for a significant capability; ADR-0019/0021
  require an ADR for a new managed flag (ADR-0027 draft §6).

## R13. AI navigator: models and providers

### Cloud provider

- **Decision**: OpenAI chat completions, model `gpt-4o-mini`, through a new adapter in
  `backend/app/modules/tasks/navigator.py` modelled on
  `backend/app/ai/title_completion.py` (official API origin, key read from the env var
  named by `*_API_KEY_ENV`, `disabled` default, `deterministic` only in TEST). New env
  vars (documented in `.env.example`):
  `BRAIN_BUDDY_REVIEW_NAVIGATOR_PROVIDER=disabled`,
  `_MODEL=gpt-4o-mini`, `_API_KEY_ENV=OPENAI_API_KEY`, `_TIMEOUT_SECONDS=8`,
  `_MAX_INPUT_TOKENS=6000`, `_MAX_OUTPUT_TOKENS=300`, `_MAX_COST_USD=0.01` (per-call admission from token
  estimate, the reconciler's admission pattern), `_MAX_DAILY_COST_USD=0.20` (per owner,
  table `navigator_usage`). Rate limit: 20 calls / 10 min per owner via
  `backend/app/core/rate_limit.py`. Startup fails loudly when the provider is
  `openai` and the named key variable is unset (as title completion does).
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
  (offline revoke).
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
  "language not supported". **Apple's model does not support Russian on iOS 26.x or
  iOS 27** (16 languages; secondary sources, primary pages blocked), so for the owner's
  Russian tasks the FR-023 choice is the normal path, not an edge case.
- **Decision (option (a), slice PR-09)**: as recommended in that file §3: Core AI +
  `CoreAILanguageModel` behind the iOS 27 `LanguageModel` protocol, Qwen3-1.7B 4-bit
  (Apache-2.0) in an Apple-hosted Background Assets pack downloaded on explicit request,
  gated by `#available(iOS 27, macOS 27, *)` and a memory check (with the
  `increased-memory-limit` entitlement); Gemma 4 E2B as the evaluation contender; MLX
  Swift as plan B. Deployment target stays iOS 26. A separate ADR (drafted with PR-09)
  amends `ios/AGENTS.md` "No third-party dependencies" for that one package, app target
  only, never `BrainBuddyCore`. Subject to NC-2.
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
  emitting only ids, codes, counts and timings; supporting metrics (decision mix, stall
  reasons, re-stall rate, returns from auto-park, due-date moves on Next tasks) are
  derived from stored codes, never from text. A unit test asserts that a decision with
  sentinel strings in title, notes, waiting-for, extension reason and navigator I/O never
  appears in captured log records.
- **Alternatives**: event bus (none exists for tasks; ADR-0001 events are unbuilt).

## R15. Retention of content-bearing review data

- **Decision**: decision `undo` snapshots (they contain the old title/notes) are nulled
  7 days after the decision; everything else lives for the account's life (intake §6
  "same as tasks") and is exported and purged with the tasks store. Device-local model
  and navigator preference are deleted with the app.
- **Rationale**: Undo is a seconds-long affordance; keeping old content indefinitely in a
  second place has no purpose.

## R16. iOS persistence and sync

- **Decision**: `StoreDocument` v2 with a migration step from v1
  (`StoreDocumentCoding.swift:117`), review state pulled with
  `GET /api/review/state` after the existing full task pull
  (`SyncEngine+Pull.swift`), new commands per contracts/ios-commands.md.
- **Rationale**: the outbox already gives offline, ordered, idempotent replay;
  sessions created offline (SC-007) need no new mechanism.

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
  the web is new UI built from existing task commands.

## R19. Requirement-coverage gate for Swift-only requirements

- **Fact**: `scripts/check_requirement_coverage.py` scans only `backend/tests`,
  `frontend/tests`, `frontend/src` and suffixes `.py .ts .tsx .js .jsx` (lines 53-64).
  FR-010a, FR-022, FR-023, FR-023a, FR-036, FR-037 and the Mac part of FR-041 are
  satisfied only in Swift.
- **Decision**: extend the script to scan `ios/BrainBuddyKit/Tests` and `macos/Tests`
  with `.swift` (the iOS app target has no test target today; `ios/project.yml:181-185`
  runs only the package test targets), in slice PR-01 (ASK: `scripts/` and a
  `GUARDED_FILES` member; re-record `.specify/gate-integrity.json` with
  `python3 scripts/check_gate_integrity.py --update`). Add
  `python3 scripts/check_requirement_coverage.py specs/020-weekly-review` to the
  `check-specs` recipe in `Makefile` (ASK, guarded) when increment 1 lands.
- **Alternatives**: contrived backend/web tests naming iOS-only requirements (evidence
  that does not test the behaviour).
- **Lettered ids**: FR-003a, FR-010a, FR-011a, FR-023a and FR-034a do not match the
  definition regex `((?:FR|SC)-\d+)\*\*` in either `check_requirement_coverage.py:44`
  or `check_spec_kit_specs.py:165-166`, so the gate cannot enforce them and they cannot
  be listed in `## PR-срезы` `requirements`. Tests still name them (`020_FR_003a_…`);
  slices cite their parent id. Reported to the main session as a spec-format issue.

## R20. Mutation testing

- **Decision**: add `app/modules/tasks/formulation.py` and `review_service.py` to the
  observed backend scope (`[tool.mutmut] only_mutate` in `backend/pyproject.toml`) in
  PR-02; propose promotion of `formulation.py` to the enforced list
  (`backend/mutation-enforced-scope.txt`, guarded, ASK) after two clean nightly runs per
  the deploy-and-ci rules. Add `frontend/src/features/review/formulation.ts` to the
  Stryker observed `mutate` list (`frontend/stryker.config.json`). No Swift mutation
  tooling exists (ADR-0015 superseded); Swift parity relies on the shared vectors.
