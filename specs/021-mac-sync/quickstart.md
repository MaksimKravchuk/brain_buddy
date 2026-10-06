# Quickstart: validating Mac ↔ backend sync (021)

This file holds validation scenarios only. Shapes and rules are in [contracts/](contracts/) and [data-model.md](data-model.md); this file says how to prove the feature works. Nothing here spends provider money: no AI or paid provider is involved.

## Prerequisites

- **Environment**: `cp .env.example .env` for development.
- **Backend tests**: they use `BRAIN_BUDDY_ENV=test` through `backend/tests/conftest.py`. Two owners come from `api_client` and `second_api_client`.
- **Kit**: Docker for `sh ios/scripts/swift-linux.sh` on Linux, or `(cd ios/BrainBuddyKit && swift test)` on macOS.
- **Mac**: macOS 26 with Xcode 26. `cd macos && swift test` runs locally and in the `macos-app` CI lane (PR-01). The launchable app needs the Whisper assets (`macos/README.md`), but only manual checks need it.
- **Web**: `make dev-frontend` (Vite on `localhost:5173`) against a local backend, or the compose stack on `8080`.
- **Evidence rule**: screenshots, recordings and Allure attachments come only from seeded synthetic accounts using the design's example data:
  - account `alex@example.com`;
  - projects "Garden", "Move flat", "Old flat" (archived, 3 open tasks) and "Tax return 2024" (archived before the feature, no tasks);
  - tags calls, errands, deep-work.

  The owner's own week of use (SC-007) is recorded as a dated yes/no plus counts, never content.
- **Manual evidence files** (review c1, F22, F51): each `specs/021-mac-sync/evidence/manual-*.md` starts with a header naming the commit SHA, the build, the OS version and the date, then one checklist line per state with yes/no. Records carry counts, durations and yes/no only: never a path, a digest, a title or a screenshot of a real account. A byte comparison is written as "bytes identical: yes/no". PR-10's `scripts/check_manual_evidence.py` rejects a file without the header, with an empty checklist, or whose SHA is not an ancestor of the release commit; it reports SC-007 as **pending** until `owner-week.md` holds seven dated entries, and never counts the template as coverage.

## Fast checks (per slice)

```bash
cd backend && pytest tests/test_project_archive_lossless_api.py tests/test_project_desired_outcome_api.py tests/test_client_attribution_logging.py tests/test_project_archive_traces.py -q
make test-backend            # coverage floor + Allure taxonomy validator, before reporting green
sh ios/scripts/swift-linux.sh test --filter BrainBuddyCoreTests
sh ios/scripts/swift-linux.sh test --filter BrainBuddySyncTests
sh ios/scripts/swift-linux.sh test --filter BrainBuddyWorkspaceTests
cd macos && swift test       # macOS only
cd frontend && npx vitest run src/features/tasks src/components/shell src/api
cd frontend && npx playwright test tests/e2e/archived-projects.spec.ts
python3 scripts/check_requirement_coverage.py specs/021-mac-sync --requirements <the slice's ids>
python3 scripts/check_spec_kit_specs.py
python3 -m unittest scripts/test_validate_ci_artifacts.py scripts/test_render_feature_report.py
```

The `--requirements` filter and the Swift test trees come from 020 PR-01. Until it lands, a Swift slice records its requirement → test-name list in its PR body or landing record instead (research R19; review c1, F48). The coverage line for 021 joins `make check-specs` only in PR-10; it runs with `--requirements` listing every id except SC-007, which `scripts/check_manual_evidence.py` reports as pending until the owner week is filled.

## Scenario 1 — lossless archive and unarchive on the server (US5; FR-024 – FR-027; SC-006)

1. Create "Old flat" with three tasks: one in Next, one completed, one cancelled. Archive it.
   **Expect** (after PR-03): 200; every task keeps `project_id`, with `revision` and list unchanged; the project has `archived_at` set and `archived_before_lossless: false`.
2. `GET /projects`. **Expect**: "Old flat" is absent.
   `GET /projects?state=archived` and `?state=all`. **Expect**: it is present with `open_task_count: 1`.
   `?state=bogus`. **Expect**: 422.
3. PATCH the Next task's title only, then with `project_id` equal to "Old flat". **Expect**: 200 both times, membership kept.
   PATCH another task to `project_id` = "Old flat". **Expect**: 400 "Task project must be active."
   `POST /tasks` into it. **Expect**: 400.
4. `POST /projects/{id}/unarchive` with the right revision. **Expect**: 200, `state: active`, `archived_at: null`, the tasks unchanged.
   Repeat with the same key. **Expect**: the same response.
   Repeat with a new key. **Expect**: 200 unchanged, no revision bump.
5. Create an active "Old flat 2", rename it "Old flat" while the first is archived again, then unarchive the first. **Expect**: 409 with the duplicate-name body.
6. Seed a project archived the old way: an archived payload with no `archived_at`. Restart the repository. **Expect**: `archived_before_lossless: true`, revision unchanged. Unarchive it. **Expect**: the marker is still true, and it has no tasks (the client shows the FR-027 line).
7. With PR-02 deployed and PR-03 not yet: archive. **Expect**: memberships cleared as before, marker true.
8. Second owner: unarchive the first owner's project. **Expect**: 404.
9. **Repeat archive** (review c1, F14): seed a pre-feature archive (marker true, `archived_at` null) and archive it again. **Expect**: 200, revision bumped, marker still true, `archived_at` still null. Archive an already lossless-archived project again. **Expect**: `archived_at` unchanged.
10. `GET /projects?state=bogus` is listed with 422 in the API contract map (`test_api_contract.py`), and the default `GET /projects` returns the same projects in the same order as before, each with the three new fields.

## Scenario 2 — desired outcome survives other clients (US5-5; FR-028)

1. `POST /projects {"name": "Garden", "desired_outcome": "Beds ready for spring"}`. **Expect**: 201 with the outcome.
2. PATCH `{"name": "Garden 2026", "expected_revision": n}` without the outcome, as the iPhone and web do. **Expect**: the outcome is unchanged.
3. PATCH `{"desired_outcome": "   "}`. **Expect**: the outcome is null. PATCH with 1001 characters. **Expect**: 422.
4. `GET /api/account/export`. **Expect**: `tasks/projects.json` holds `desired_outcome`, `archived_at` and `archived_before_lossless`.
   Purge the account. **Expect**: no project row remains.
5. Log capture across steps 1 – 4. **Expect**: no outcome text and no project name in any log line (FR-030).

## Scenario 3 — client attribution (FR-031)

Send requests with `X-Client: brainbuddy-macos/0.1.0`, `brainbuddy-ios/1.4`, no header, and `evil\nvalue`. **Expect**: the `api_request` lines carry `client=macos client_version=0.1.0`, `client=ios client_version=1.4`, `client=web client_version=-` and `client=other client_version=-`. The raw bad value never appears. Responses are identical in every case.

Then send `X-Correlation-ID: abc\nforged=1` (review c1, F50, F57). **Expect**: the response's `X-Correlation-ID` is a fresh UUID, and no captured log line contains `forged`. A lower-cased UUID is echoed unchanged.

## Scenario 4 — two clients converge (US1, US2; FR-006 – FR-011; SC-001, SC-002)

These run as kit tests (`BrainBuddyWorkspaceTests/MacIPhoneConvergenceTests.swift`): two `Workspace`s, identities `.macOS` and `.iOS`, one `BrainBuddyFakeServer`, and an injected clock.

1. **Sign-in with local data**: the Mac holds account-less "Garden" (with an outcome) and three tasks. The account already has "garden" and the tag "Calls". Sign in.
   **Expect**: one "Garden" with the outcome kept, one tag, three tasks added, and nothing merged by title (FR-003, SC-003).
   - **Both sides have an outcome** (review c1, F04): the account's "garden" already has one. **Expect**: the account's outcome stays, and one sync issue holds the Mac's outcome in full (not clipped), with "Copy outcome".
   - **Archived local project meets an active account project** (review c1, F03, F37): the Mac holds the import's shape, an archived "Old flat" with three tasks (`createProject`, three `createTask`, `archiveProject`); the account has an active "Old flat". **Expect**: no task loses its project; all three are in the account's "Old flat", which stays active; one sync issue says the archive was not applied. The same when the merge comes from a 409 on the create.
   - **Archived meets archived** (review c1, F15): the account has only an archived "Old flat". **Expect**: two archived "Old flat"s on both sides, explicitly; the SC-003 duplicate check counts active names only.
   - **First upload** (review c1, F33): the imported operations are 213 days old. **Expect**: the line reads "Not synced yet" until they are sent, X-02 reads "Adding your tasks to your account · N left", and no "oldest 213 days" appears.
   - **Review marks** (review c1, F20): the Waiting, Someday and Project marks' content stamps are unchanged after the upload and pull, and after sign-out and sign-in to the same account (FR-023).
2. **Capture** (review c1, F07, F17): capture on the Mac at the worst phase, just after the iPhone's pull completed, with a 1.5 s pull duration on the fake transport. Advance 2 s (debounce), then `.periodic` ticks every 15 s on the iPhone (pull age 30 s). **Expect**: the task is present on the iPhone within 60 s of the capture, in every case. Repeat for every FR-007 record type in both directions (SC-001). A check starts when the change is applied on the sender and ends when the receiver's state holds it.
3. **Offline matrix**: the Mac goes offline; it makes 20 mixed changes; the store is reopened (relaunch); a response is dropped mid-push (`FakeServerTransport` fault); it reconnects.
   **Expect**: every change is on the server exactly once, and the iPhone shows the same set (SC-002).
4. **Same field offline on both**: both edit the same field offline. **Expect**: the last to reach the server wins per field, and different fields both survive (FR-011).
5. **Archive meets offline capture**: the iPhone archives "Garden" while the Mac, offline, captures into it. **Expect**: the Mac's task lands without the project, with a sync issue: "Project “Garden” was archived on another device, so the task was added without a project."
6. **Account switch**: the Mac signs in as account B with changes waiting for A. **Expect**: "Sign out first to use another account." with "… waiting on this Mac.", and nothing from A sent to B (FR-004, US4-5).
7. **Archive and unarchive across clients**: archive on the iPhone, unarchive on the Mac. **Expect**: memberships are intact on both and on the server (SC-006).
8. **Refused unarchive with a capture behind it** (review c1, F60): offline, the Mac unarchives "Old flat" and captures two tasks into it; meanwhile the web created an active "Old flat". Reconnect. **Expect**: one sync issue ("… 2 tasks you added to it were kept without a project."), no 400 per task, and the project archived again locally at once.
9. **Incoming change while editing** (review c1, F19; FR-009): the Mac edits a task's title while a pull changes its title and due date, then saves. **Expect**: only the title was sent, the due date shows the incoming value, the title shows the Mac's, and every `EntityID` is unchanged.

## Scenario 5 — status line (US3; FR-012 – FR-016, FR-019; SC-004, SC-005)

These run as kit tests (contracts/sync-status.md §5) and as host checks.

1. **Snapshot table**: drive every snapshot row of sync-status §3. **Expect**: the exact text, for both `.mac` and `.iPhone`.
2. **Transient failure** (`FakeServerTransport`, `ManualSyncScheduler`, the real `retryDelay` with jitter pinned at both extremes; review c1, F16): fail with 503 until just under 60 s (59 s), then recover. **Expect**: attempts at about 2, 6, 14 and 30 s and one at exactly 60 s, which succeeds: the indicator only, never a warning (SC-005).
   Fail until 61 s. **Expect**: the 60 s attempt fails and "Couldn't sync · Retry" appears, with a reference id and "Last tried" in the tooltip. One success later, **expect** "Synced just now".
   During a pending backoff: a `.periodic` tick runs no cycle; "Retry" (`.manual`) runs one at once.
   **Failing, then offline** (review c1, F13): after "Couldn't sync", the path monitor goes offline. **Expect**: "Offline · N changes waiting", Sync now disabled, and X-02 keeps the last failure's reference id in its details. Back online with the server still failing: **expect** "Couldn't sync · Retry" after the first failed attempt, without a new 60 s wait.
   **Quiet ticks** (review c1, F12): 15 s ticks for 29 s after a pull with an empty outbox. **Expect**: zero status transitions and zero requests; the tick at 30 s pulls.
3. **Session ended**: return 401. **Expect**: "Sign in again to sync" at once, and the waiting changes are kept.
   **Single-flight**: press "Sync now" three times during a running cycle. **Expect**: one follow-up cycle at most, and the button never disabled (FR-019).
   **Sign-out wording** (review c1, F06, F27): with nothing unsent and two open issues, **expect** "Sign out?" plus "2 changes that couldn't sync will also be removed from this Mac."; with the pre-upgrade backup present, plus "A copy of your tasks from before the update stays on this Mac until <date>." The same issue sentence on the iPhone with "iPhone".
   **Sign-out failure** (review c1, F59): the store's removal fails. **Expect**: "Couldn't sign out", the token still stored, no logout sent, and the line not "Sign in again to sync".
4. **Mac host check**: run through every state in sequence:
   - account-less;
   - first load;
   - synced;
   - syncing longer than 1 s;
   - waiting;
   - offline (Wi-Fi off);
   - session ended (sign out on the web to revoke);
   - failing (point the server address at a closed port on `localhost` for more than 60 s);
   - rejected (unarchive a name that clashes).

   **Expect**: no sheet, alert or notification appears and focus never moves (SC-004), and every failure shows a reference id. The automated guard is `MacPresentationRouterTests` (mac-app-host §8); this host run confirms it on screen. Recorded in `specs/021-mac-sync/evidence/manual-macos-status.md` (labelled manual): VoiceOver reading of X-01 and X-02, keyboard order, Reduce Motion glyph, Large sidebar text wrapping after " · ", and also (review c1):
   - scroll position, selection and keyboard focus unchanged while an incoming change arrives from the web (FR-009, F19);
   - after X-03 closes, focus is on the status words when the opener is gone (a closed popover, a menu item, the vanished "Sign in to sync"), and on the trailing action after Cancel (F29);
   - Cancel and Esc work during "Signing in…" and leave the typed values (F28);
   - after Dismiss in X-02, focus is on the next issue's Copy, then Sync now (F30);
   - the Keychain item exists after sign-in and "token found in files: no" for `store.json`, `mac-local.json` and the app's defaults (F24).
5. **iPhone host check** (M-01): the same states on list screens, with Settings › Sync using the same words. Recorded in `specs/021-mac-sync/evidence/manual-ios-status.md`, which also records (review c1, F18, F55, F56): with the app open, a change made on the web appears within 60 s without touching the phone, and nothing is fetched while the app is in the background; the "Couldn't sync · Retry" row's long-press "Copy reference ID"; Settings › Sync "Sync now" enabled while a sync runs. The tick itself is tested in the kit (`PeriodicSyncTickerTests`).

## Scenario 6 — upgrade the Mac (US4; FR-020 – FR-023; SC-003)

1. Run `macos/Tests/BrainBuddyMacTests/LegacyStoreImporterTests.swift` (contracts/mac-legacy-import.md §6).
2. **Host check**:
   1. With a pre-021 build, create the design's example data, including review marks and an archived project with tasks, then quit.
   2. Install the 021 build and launch.
      **Expect**: no notice, every record present, the footer reads "On this Mac · Sign in to sync", and `local-gtd.backup-*.json` sits beside `store.json` with the original bytes (compare `shasum`; record only "bytes identical: yes/no").
   3. Sign in to an account with an overlapping project name.
      **Expect**: one merged project, all tasks on the web, and review marks still present.
   4. Corrupt a copy of `local-gtd.json` and relaunch on a fresh folder.
      **Expect**: X-05, the file unchanged, and an empty workspace only after "Continue".
   5. **A previous-version file comes back** (FR-033; review c1, blocking F02): after step 3, quit, launch the pre-021 build once and add one task (it writes a new `local-gtd.json`), quit it, then launch the 021 build.
      **Expect**: X-05 "Brain Buddy found tasks from the previous version" once; the workspace unchanged (same task count, "bytes identical: yes" for `store.json` before and after); the new `local-gtd.json` left in place; X-02 shows the quiet line with "Show in Finder". A second launch shows no notice.
   6. Repeat step 5 after deleting `mac-local.json`. **Expect**: the same, and no import.

   Recorded in `specs/021-mac-sync/evidence/manual-macos-upgrade.md` with counts only.

## Scenario 7 — iPhone and web archive UI (M-02, D-01)

- **Web** (`frontend/tests/e2e/archived-projects.spec.ts`):
  - the sidebar "Archived projects 2" disclosure;
  - opening "Old flat" lists 3 tasks with no composer;
  - "Unarchive" returns it to Projects with focus on the heading and a toast;
  - "Tax return 2024" shows "No tasks in this project" plus the FR-027 line;
  - at 390 × 851 there is no horizontal overflow and the Unarchive button is 44 px;
  - an axe scan finds no violations.
- **Web, offline**: the Unarchive button is disabled with the offline copy (Vitest).
- **Web, unarchive refused** (review c1, F32): the server answers 409 duplicate name. **Expect**: "Another active project is already called “Old flat”. Rename one first." with Ref and "Rename…", no Retry, focus on Unarchive (Vitest).
- **Web, archive the open project** (review c1, F31): the page becomes the archived page, focus on the heading, toast "Archived “Old flat”" (Vitest).
- **Web, changes from another client** (FR-032, SC-001; review c1, F05): `taskHooks.test.ts` asserts a 45 s `refetchInterval` with `refetchIntervalInBackground: false` on the task list, projects, tags and open task detail queries. `TaskDetailAutosaveUI.contract.test.tsx` asserts that a refetch while typing keeps the typed text and takes the incoming value of an untouched field. `frontend/tests/e2e/cross-client-refresh.spec.ts` (Playwright, fake clock) changes a subtask, a comment and a tag name through the API while the page is open and expects each on screen after at most 45 s of fake time, with scroll and selection unchanged.
- **iPhone**: package tests cover the reducer and sync. The host check of M-02 (swipe Unarchive, toolbar Unarchive, non-destructive archive confirmation, VoiceOver custom action) is recorded in `specs/021-mac-sync/evidence/manual-ios-archive.md`.

## Scenario 8 — two copies of the Mac app (edge case; design X-08)

1. Launch the app twice from Finder. **Expect**: the second launch brings the first window forward and exits (X-08 "default").
2. Run `swift run BrainBuddyMac` while the bundled app is open. **Expect**: design X-08 "unreachable": the alert "Brain Buddy is already open." / "Switch to the open window to keep working." with the default button "OK", then the copy exits, and the store is unchanged.

`SingleInstanceGuardTests` covers the lock logic in CI.

## Scenario 9 — owner week (SC-007)

The owner uses Mac, iPhone and web on one account for one week. Each day the owner records in `specs/021-mac-sync/evidence/owner-week.md`:

- "needed Sync now: yes/no";
- "saw Mac and iPhone disagree after a minute online: yes/no";
- the count of sync issues seen.

This is post-release acceptance, not a slice gate.
