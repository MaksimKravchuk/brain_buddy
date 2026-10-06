# Quickstart: validating Weekly Review (020)

Validation scenarios only. Shapes and rules are in [contracts/](contracts/) and
[data-model.md](data-model.md); this file says how to prove the feature works.
Nothing here spends provider money: the navigator uses the `deterministic` provider in
TEST. A live provider check is `/verify-live`, approval-gated, never unattended.

## Prerequisites

- `cp .env.example .env` (development); `weekly_review` is OFF by default. Enable it for
  the local test account through the Admin Portal flag page (SELECTED_USERS) or the test
  fixture that seeds flags.
- Backend tests use `BRAIN_BUDDY_ENV=test` via `backend/tests/conftest.py`; maintenance
  threads stay off in TEST, so scenarios drive the sweep by calling
  `_run_review_maintenance_sweep(container)` directly. Time is controlled by the one
  `frozen_clock` fixture, which sets the clock injected into `TaskService`,
  `ReviewService` and the sweep (research R21); no test patches a module's `utcnow`.
- Playwright (compose stack, real clock) seeds aged tasks and runs the sweep only
  through the TEST-only CLI commands `python -m app.cli review-seed-aged-task` and
  `python -m app.cli review-run-sweep` (research R21); there is no test HTTP route.
- Every owner in a scenario is activated first (explainer acknowledged, Scenario 7)
  unless the scenario says otherwise.
- Evidence rule: screenshots, recordings and Allure attachments come only from seeded
  synthetic accounts using the design's example data; results from the owner's real use
  are recorded as numbers only (plan Test strategy "Evidence rule").
- iOS package: Docker for `sh ios/scripts/swift-linux.sh`.
- Web: `make dev-frontend` (Vite on `localhost:5173`) against a local backend, or the
  compose stack on `8080`.

## Fast checks (per slice)

```bash
cd backend && pytest tests/test_review_formulation.py tests/test_review_formulation_vectors.py -q
cd backend && pytest -k "review" -q
sh ios/scripts/swift-linux.sh test --filter BrainBuddyCoreTests
sh ios/scripts/swift-linux.sh test --filter BrainBuddySyncTests
cd frontend && npx vitest run src/features/review src/components/shell
cd frontend && npx playwright test tests/e2e/weekly-review.spec.ts
# per slice: only that slice's requirements (filter added by PR-01)
python3 scripts/check_requirement_coverage.py specs/020-weekly-review --requirements <the slice's ids>
python3 scripts/check_spec_kit_specs.py
make test-backend        # coverage floor + Allure taxonomy validator, before reporting green
```

The unfiltered `python3 scripts/check_requirement_coverage.py specs/020-weekly-review`
fails until every requirement has a test, so it is the full-feature gate and joins
`make check-specs` only in PR-14 (research R19).

## Scenario 1 — the rule and the card (US1; M-01, M-02, M-03, M-04, D-01, D-02)

1. Seed a Next task created 15 days ago, unchanged title, threshold 14.
   **Expect**: list marker "Asks for a decision" (indigo, icon + text), no "overdue", no
   red; `TaskResponse.formulation.ask_at` = start + 14 d.
2. Seed tasks at 9 days and 3 days. **Expect**: no list marker for either; detail shows
   "Ageing" for 9 days only.
3. PATCH the 15-day task's title changing only case/punctuation. **Expect**: same
   `formulation.id`; marker stays. Then change it substantively. **Expect**: new
   `formulation.id`, marker gone.
4. Edit notes, tags, project, priority. **Expect**: `formulation` unchanged (FR-003).
5. Decide `first_step` with a new title. **Expect**: notes start with
   `Was: <old title>`; new formulation; decision row with `type=first_step`.
6. Decide `extend` with a reason; open the card again. **Expect**: marker cleared, ask
   and park dates +7 d (research R6), "Keep 7 more days" absent; a second `extend` →
   400 `extension_already_used`; the decision row carries `reason_text`. Repeat on a
   task whose park is due but not yet applied (`park_due`, sweep not run). **Expect**:
   200, not parked by the next sweep (FR-009, FR-013). Extend on day 18, then
   reformulate substantively on day 20 (before the extended ask on day 25).
   **Expect**: `consecutive_stalled` incremented (FR-005).
7. Decide with a stale `expected_revision`. **Expect**: 409, task unchanged, client
   shows "Task changed elsewhere" / M-03 stale.
8. Undo a decision within the toast window. **Expect**: task restored field-for-field
   including `formulation`, decision row gone; undo after another edit → 409
   `undo_unavailable`. Undo a `follow_up` after editing the created task elsewhere.
   **Expect**: 409 `undo_unavailable`, the follow-up keeps its edit.
9. Task with a due date 10 days ahead and 20 days in Next. **Expect**: no marker,
   detail "Paused until the due date", not parked by the sweep before the due date.
10. Web: type a new wording in D-02, press Esc. **Expect**: "Discard your new
    wording?" with focus on "Keep editing"; reload the tab → browser leave warning;
    reopen the dialog → the draft is back (FR-052). iOS package: a draft stored for a
    formulation is not offered after a substantive title change.

## Scenario 2 — auto-park and return (US2; M-01, M-02, M-09, D-01/D-03)

1. Freeze time at age 20 days (threshold 14). **Expect**: "Moves to Someday tomorrow".
2. Advance to 21 days and run the sweep. **Expect**: task in Someday, `parked` set
   (auto-park only) with `clock_before`, project/tags/notes/due date kept; log line
   `review_auto_park applied=true source=sweep` with ids only.
3. Run the sweep again and POST `/tasks/{id}/auto-park` from a "second device".
   **Expect**: no further change, `applied: false`, no 409 (US2-6).
4. Open the app/web. **Expect**: "While you were away" lists the task; "Return to Next"
   → task in Next with a new formulation; Continue → `review/parks/acknowledge`; the
   screen does not reappear. Close it without Continue instead. **Expect**: not shown
   again at app open the same calendar day, shown the next day, and always first when
   the review opens (FR-015).
5. Reformulate a task after its park became due but before the sweep. **Expect**: sweep
   skips it (FR-013).
6. Offline device decides `someday` on the pre-park revision with
   `client_decided_at` before the server park. **Expect**: on push, 200 with
   `yielded_auto_park: true` (edge case "Offline for a long time"). Repeat with
   `extend`. **Expect**: 200, clock restored exactly from `clock_before`, extension
   set, `consecutive_stalled_formulations` unchanged. Repeat with a notes-only PATCH
   made offline before the park. **Expect**: 409 → replayed onto the parked task, which
   stays parked. Repeat with a notes edit queued **before** a card decision, both
   offline, the park between them. **Expect**: the notes edit is replayed onto the
   parked task, the decision is still accepted with `yielded_auto_park: true`, the
   notes are kept, and no sync issue appears.
6a. After a yield, save a cosmetic-only reformulation ("Save anyway") so the task is
   `park_due` again, and run the sweep. **Expect**: parked again in that run (new key
   `auto-park:<task>:<formulation>:<from_revision>`), no idempotency conflict logged.
7. Turn the flag on for an owner whose Next has 30 tasks aged 60 days, without
   acknowledging the explainer, and run the sweep for 30 days. **Expect**: nothing
   parks, no markers (`formulation.ask_at` null). Acknowledge the explainer. **Expect**:
   none "asks" on day one; nothing asks before acknowledgement + 14 days; no park
   earlier than acknowledgement + 14 days (FR-016, FR-051); no task `revision` changed.
8. Change threshold 28 → 7. **Expect**: markers update now; nothing parks before change
   + 7 days (FR-039; M-01 "threshold just changed" note).
9. Turn the flag OFF for 10 days for an activated owner with tasks that became due
   meanwhile, then ON, and run the sweep. **Expect**: nothing parks for 7 days
   (sweep-gap floor) and "Moves to Someday tomorrow" shows for 24 h before each park.
   During the OFF period, decision undo snapshots older than 7 days are nulled
   (retention runs whatever the flag state).
10. Change the time zone eastward for an owner with a due-dated Next task. **Expect**:
    `park_floor_at` ≥ change + 7 d.

## Scenario 3 — offline and account-less iOS (FR-014, FR-040, SC-007)

1. Package test with `BrainBuddyFakeServer`: two workspaces, both offline past the park
   instant, both park locally, then sync. **Expect**: one server park, no `SyncIssue`.
2. Account-less workspace: create a Next task, advance the clock 21 days, call
   `applyDueAutoParks()`. **Expect**: task in Someday locally; M-09 shows it.
3. Run a quick review offline with 3 decisions, then sync. **Expect**: 0 lost decisions;
   `GET /review/sessions/{id}` (the client's session id) on the server shows the
   summary counts (SC-007). Repeat while another device has an open session on the
   server. **Expect**: the offline session replaces it (the other is closed as partial
   or abandoned), still 0 lost decisions and no `SyncIssue`. Open `/review` on the web.
   **Expect**: the entry's "Last review" card shows that review's ten counts (SC-007).
3a. Golden operation traces: the same trace files pass in pytest against the real API
   and in Swift against `BrainBuddyFakeServer` (plan Test strategy "traces").
3b. Device clock 2 days ahead, signed in and online, a task due in 1 day. **Expect**:
   no local park, nothing on "While you were away", no "Return to Next" on a Next task.
4. Decode a v1 `store.json` fixture. **Expect**: v2 document, no data loss.
5. Account-less: create a Next task, change its title substantively 10 days later, then
   advance 11 more days, all unsent. **Expect**: the compacted outbox replays to the
   same `formulation` as the uncompacted operations (started at the rename, not at
   creation), and nothing parks early. With 25 tasks due at once, one
   `applyDueAutoParks()` parks at most 10 and M-09 says more will follow.
6. Account-less: dismiss the explainer at instant A, replay the store. **Expect**: every
   Next task's clock is clamped to A (post-replay activation step) and nothing parks
   before A + 14 d.

## Scenario 4 — navigator (US3; M-05 – M-08, D-02)

0. Start the backend with `BRAIN_BUDDY_REVIEW_NAVIGATOR_PROVIDER=openai` and the key
   variable unset. **Expect**: startup fails, naming the variable (not a value). With
   `disabled`: `GET /review/navigator` → `available: false`; web shows "Suggestions
   aren't available right now."
1. Web, no consent, Suggest. **Expect**: consent screen names the provider and the five
   data items; Not now → nothing sent (no request in the network log). The request body
   of a later suggestion has no language field.
2. Allow; Suggest. **Expect**: 1–3 proposals (deterministic provider); none equals an
   open task title; picking fills the field; the task changes only on Save; decision
   `ai_use=as_is|edited`.
3. Revoke in D-04; Suggest. **Expect**: no request is sent; consent screen again; a
   direct API call → 400 `navigator_consent_required`.
4. Force timeout / cost cap / malformed in the deterministic provider. **Expect**:
   503/429 with `reference_id`, card usable, Ref shown.
5. Request with an extra field (e.g. `due_date` or `language_hint`). **Expect**: 422
   (strict schema). Notes of 9 000 characters. **Expect**: the client sends the
   `reduce_notes` result (first lines ≤ 2 000 + `…` + last lines ≤ 4 000 characters),
   `notes_truncated: true`, and the card shows "Part of the notes was not considered."
   A stored consent with an older `consent_text_version` → 400
   `navigator_consent_required`.
6. iOS package: `NavigatorRouter` with a stub Apple model reporting
   `unsupportedLanguage("ru")`. **Expect**: `unavailable` → M-06 choice; never cloud
   without consent; account-less → cloud option shows "need a Brain Buddy account".
7. Log capture over all of the above. **Expect**: no title, notes, proposal or question
   text in any record (FR-044). After a suggestion call: no idempotency record and no
   `task-commands/` entry for it; `navigator_usage.shown` incremented.
8. A provider stub that takes `command_lock` for another owner while answering.
   **Expect**: no deadlock and no wait (the provider call runs with no lock held).
9. Flag OFF for the owner with a stored consent. **Expect**: `GET /review/navigator`
   works and `DELETE /review/navigator/consent` → 204; suggestions → 404. Flag ON
   again; Suggest. **Expect**: 400 `navigator_consent_required`, consent screen again.
10. A project with 25 open tasks where the only proposal equals the 21st (unsent)
    title. **Expect**: the client drops it and shows "No useful suggestion this time".

## Scenario 5 — the guided review (US4, US5; M-10 – M-25, D-03, D-04)

1. Never-onboarded user opens the review. **Expect**: onboarding once with Fri 16:00 and
   14; Continue saves settings (iOS then asks for notification permission).
2. Start quick review. **Expect**: Wins first (count of tasks completed in 7 days),
   then Inbox, decisions (earliest-asking first, including "moves tomorrow" tasks; one
   card; "Not now" keeps it asking), summary with ten counts and the next review date.
   In a full review, keep one Waiting item and return one Someday item to Next.
   **Expect**: "Kept as is 1", "Moved to Next 1" (FR-033).
3. Leave at step 4; open on the other client. **Expect**: resume card "step 4 of N",
   decisions kept. Continue to step 6 there, then return to the first client.
   **Expect**: "You continued this review on the web, so it's at step 6 now."
4. Open and leave without decisions. **Expect**: the session stays `open` and does not
   move "Last review"; after 7 days without activity the sweep closes it as
   `abandoned`. Leave after one decision. **Expect**: still `open`, already counted
   ("Last review" moves); after 7 idle days `partial`, and returning shows "closed after
   a week". Open, skip every step and tap Done. **Expect**: "Review done" with no
   reproach; status `completed_empty`; "Last review" unchanged; restart mode not
   postponed; the next notification still scheduled (FR-029).
5. Full review with 41 Next tasks and 36 completions over 4 weeks. **Expect**: "41 next
   actions · 9 done per week · ~4½ weeks"; no limit. With 2 weeks of history:
   **Expect**: count only and the "pace appears after a few weeks" line (FR-031).
6. 21+ days without a counted review, with seeds that make the candidate set non-empty
   (tasks older than 4 weeks kept in Next by an extension, a floor or an ended due-date
   pause; formulation-clock §5). **Expect**: restart mode; release → those tasks in
   Someday with `parked` null; kill the app → the review reopens on the released state
   with Undo; Undo restores all with their clocks unchanged (same `formulation.id`,
   `started_at`, extension); one task changed elsewhere first → "15 are back in Next.
   2 changed on another device…". A restart list naming a 20-day Next task → that item
   `not_eligible`. A person onboarded 22 days ago with no counted review → restart mode;
   a person never onboarded → onboarding, no restart mode (FR-017).
7. iOS: a partial review on Wednesday. **Expect**: Friday's pending notification is
   removed (`ReviewReminderPlanner` in Core, plus a recorded manual device check);
   widget shows "3 ask" (the aggregate, including "moves tomorrow") and its medium-size
   chip opens the decision step after the entry-order screens.
8. Every review screen and string. **Expect**: no streak, no "overdue", no red for age
   (US5-6); checked automatically by the Vitest string and token guard, the Core
   `ReviewCopy` test (every iOS review string, notification and widget included) and
   the Core `MarkerStyle` test, not only by eye.
9. Someday step with 12 eligible items, 2 of them auto-parked 5 days ago. **Expect**:
   those 2 are absent; 7 shown, never-reviewed first, then oldest review. Release 3
   Someday-bound tasks in the same review (restart release or "Release to Someday").
   **Expect**: those 3 are absent from the Someday step for 30 days (FR-032).
10. Web at 390 × 851: `/tasks/next` with markers, the decision dialog, `/review`
    (Waiting step and summary), the review section of `/settings/account`, D-05 and the
    drawer. **Expect**: no horizontal overflow; the Waiting buttons stack and the
    summary grid has 2 columns; the drawer shows a working "Weekly review" link with
    "Last review".
11. Web: on `/review` with a typed mind-sweep line, press browser Back. **Expect**:
    "Discard what you typed?" first, then the Leave confirmation; "Keep going" stays on
    `/review`. A step whose queue request fails shows "We couldn't load this step" with
    Retry and Skip step.

## Scenario 7 — the auto-park explainer (FR-051, FR-016; M-26, D-05)

1. Flag on, owner never activated, open the web. **Expect**: D-05 before anything else;
   focus on its heading; Esc → `POST /review/explainer/acknowledge` with the browser's
   time zone, `activated_at` set, `grace_until` = then + 14 d, `time_zone` stored (a
   due date today classifies in that zone, not UTC).
2. Open the iOS app for the same account (online). **Expect**: M-26 is not shown.
3. A second account: open iOS offline, tap "Got it"; open the web before the phone
   syncs. **Expect**: the web shows D-05 (not yet seen on the server); whichever
   acknowledgement reaches the server first sets `activated_at`; the later one changes
   nothing.
4. Kill the iOS app while M-26 shows. **Expect**: shown again at the next open; nothing
   parks meanwhile.
5. Account-less install: M-26 shown once; `local.activatedAt` set.

## Scenario 6 — Mac pre-sync row (FR-041)

Launch the Mac app. **Expect**: a non-interactive "Weekly review · coming later" row
after Lists; no review action. No CI lane runs `macos/` tests, so the evidence is a
recorded run of `swift test --disable-sandbox` on a macOS host; US6-1 stays unverified
until the Mac-sync spec exists.

## Privacy read-back

`GET /api/account/export` → ZIP contains `review/settings.json`, `review/sessions.json`,
`review/decisions.json`, `review/receipts.json`, `review/park_acknowledgements.json`,
`review/bulk_releases.json`, `review/navigator_consents.json`; manifest lists
`navigator_usage` as excluded; `review/decisions.json` holds the `reason_text` of an
`extend` decision. Account purge → all review tables empty for the owner;
running purge twice is a no-op. A batch request naming another owner's task id and a
random id (bulk release, `set_aside_task_id`) → byte-identical responses
(`not_eligible` / ignored), never 404; another owner's and a random `session_id` on
`GET /review/queues/{step}` → the same 404 body. A decision whose `decision_id` carries
free text instead of `decision_<uuid>` → 422, and the text is in no log. Logs over every
scenario contain no stall-reason value, and a sweep over an invalid payload logs only
the exception type.

## Rollout read-back

Flag OFF: web shows "Weekly review — Coming soon" (existing AppShell test still passes),
iOS shows "coming later"; the gated routes (`GET /review/state`, queues, sessions by
id, navigator suggestions and consent grant) return 404 `weekly_review_disabled`;
writes that finish queued work (decisions, undo, sessions, acknowledgements, settings,
bulk releases) are accepted, so an iOS device with 3 queued review commands drains its
outbox with 0 sync issues; device auto-parks get `applied: false`; `GET
/review/navigator` and the consent revoke still work; the sweep's exposure part changes
nothing (its retention part still nulls old undo snapshots and deletes old usage rows).

## Real-use read-out (post-release, not a slice gate)

After the flag is ON for the owner, the owner runs
`python -m app.cli review-metrics --owner <id> --since <date>` weekly in the production
backend container for 8 weeks from the first counted review and appends the printed
numbers (and their sample sizes) to `specs/020-weekly-review/evidence/real-use-readout.md`
(plan Test strategy "Slice acceptance vs post-release acceptance"). No titles, notes,
reasons or summaries are recorded.
