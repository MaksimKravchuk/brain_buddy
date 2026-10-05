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
  `_run_review_maintenance_sweep(container)` directly, with a frozen clock.
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
python3 scripts/check_requirement_coverage.py specs/020-weekly-review
python3 scripts/check_spec_kit_specs.py
make test-backend        # coverage floor + Allure taxonomy validator, before reporting green
```

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
   400 `extension_already_used`.
7. Decide with a stale `expected_revision`. **Expect**: 409, task unchanged, client
   shows "Task changed elsewhere" / M-03 stale.
8. Undo a decision within the toast window. **Expect**: task restored field-for-field
   including `formulation`, decision row gone; undo after another edit → 409
   `undo_unavailable`.
9. Task with a due date 10 days ahead and 20 days in Next. **Expect**: no marker,
   detail "Paused until the due date", not parked by the sweep before the due date.

## Scenario 2 — auto-park and return (US2; M-01, M-02, M-09, D-01/D-03)

1. Freeze time at age 20 days (threshold 14). **Expect**: "Moves to Someday tomorrow".
2. Advance to 21 days and run the sweep. **Expect**: task in Someday,
   `parked.by = "auto"`, project/tags/notes/due date kept; log line
   `review_auto_park applied=true source=sweep` with ids only.
3. Run the sweep again and POST `/tasks/{id}/auto-park` from a "second device".
   **Expect**: no further change, `applied: false`, no 409 (US2-6).
4. Open the app/web. **Expect**: "While you were away" lists the task; "Return to Next"
   → task in Next with a new formulation; Continue → `review/parks/acknowledge`; the
   screen does not reappear.
5. Reformulate a task after its park became due but before the sweep. **Expect**: sweep
   skips it (FR-013).
6. Offline device decides `someday` on the pre-park revision with
   `client_decided_at` before the server park. **Expect**: on push, 200 with
   `yielded_auto_park: true` (edge case "Offline for a long time").
7. Activate the flag for an owner whose Next has 30 tasks aged 60 days. **Expect**: no
   park earlier than activation + 14 days (FR-016); none "asks" on day one.
8. Change threshold 28 → 7. **Expect**: markers update now; nothing parks before change
   + 7 days (FR-039; M-01 "threshold just changed" note).

## Scenario 3 — offline and account-less iOS (FR-014, FR-040, SC-007)

1. Package test with `BrainBuddyFakeServer`: two workspaces, both offline past the park
   instant, both park locally, then sync. **Expect**: one server park, no `SyncIssue`.
2. Account-less workspace: create a Next task, advance the clock 21 days, call
   `applyDueAutoParks()`. **Expect**: task in Someday locally; M-09 shows it.
3. Run a quick review offline with 3 decisions, then sync. **Expect**: 0 lost decisions;
   `GET /review/sessions/{id}` on the server shows the summary counts (SC-007).
4. Decode a v1 `store.json` fixture. **Expect**: v2 document, no data loss.

## Scenario 4 — navigator (US3; M-05 – M-08, D-02)

1. Web, no consent, Suggest. **Expect**: consent screen names the provider and the five
   data items; Not now → nothing sent (no request in the network log).
2. Allow; Suggest. **Expect**: 1–3 proposals (deterministic provider); none equals an
   open task title; picking fills the field; the task changes only on Save; decision
   `ai_use=as_is|edited`.
3. Revoke in D-04; Suggest. **Expect**: no request is sent; consent screen again; a
   direct API call → 400 `navigator_consent_required`.
4. Force timeout / cost cap / malformed in the deterministic provider. **Expect**:
   503/429 with `reference_id`, card usable, Ref shown.
5. Request with an extra field (e.g. `due_date`). **Expect**: 422 (strict schema).
6. iOS package: `NavigatorRouter` with a stub Apple model reporting
   `unsupportedLanguage("ru")`. **Expect**: `unavailable` → M-06 choice; never cloud
   without consent; account-less → cloud option shows "need a Brain Buddy account".
7. Log capture over all of the above. **Expect**: no title, notes, proposal or question
   text in any record (FR-044).

## Scenario 5 — the guided review (US4, US5; M-10 – M-25, D-03, D-04)

1. Never-onboarded user opens the review. **Expect**: onboarding once with Fri 16:00 and
   14; Continue saves settings (iOS then asks for notification permission).
2. Start quick review. **Expect**: Wins first (count of tasks completed in 7 days),
   then Inbox, decisions (oldest first, one card, "Not now" keeps it asking), summary
   with eight counts and the next review date.
3. Leave at step 4; open on the other client. **Expect**: resume card "step 4 of N",
   decisions kept.
4. Open and leave without decisions. **Expect**: `abandoned`; does not move "Last review".
5. Full review with 41 Next tasks and 36 completions over 4 weeks. **Expect**: "41 next
   actions · 9 done per week · ~4½ weeks"; no limit.
6. 21+ days without a counted review. **Expect**: restart mode; release → tasks older
   than 4 weeks in Someday (`parked.by = "person"`); Undo restores all; stale ones named.
7. iOS: a partial review on Wednesday. **Expect**: Friday's pending notification is
   removed; widget shows "3 ask" and its medium-size chip opens the decision step.
8. Every review screen and string. **Expect**: no streak, no "overdue", no red for age
   (US5-6).

## Scenario 6 — Mac pre-sync row (FR-041)

Launch the Mac app. **Expect**: a non-interactive "Weekly review · coming later" row
after Lists; no review action.

## Privacy read-back

`GET /api/account/export` → ZIP contains `review/settings.json`, `review/sessions.json`,
`review/decisions.json`, `review/receipts.json`, `review/park_acknowledgements.json`,
`review/bulk_releases.json`, `review/navigator_consents.json`; manifest lists
`navigator_usage` as excluded. Account purge → all review tables empty for the owner;
running purge twice is a no-op.

## Rollout read-back

Flag OFF: web shows "Weekly review — Coming soon" (existing AppShell test still passes),
iOS shows "coming later", every `/api/review/*` and the decision/auto-park routes return
404 `weekly_review_disabled`, the sweep changes nothing.
