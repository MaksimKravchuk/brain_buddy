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

The `--requirements` filter and the Swift test trees come from 020 PR-01. The unfiltered `python3 scripts/check_requirement_coverage.py specs/021-mac-sync` fails until every requirement has a test, so it joins `make check-specs` only in PR-10.

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

## Scenario 2 — desired outcome survives other clients (US5-5; FR-028)

1. `POST /projects {"name": "Garden", "desired_outcome": "Beds ready for spring"}`. **Expect**: 201 with the outcome.
2. PATCH `{"name": "Garden 2026", "expected_revision": n}` without the outcome, as the iPhone and web do. **Expect**: the outcome is unchanged.
3. PATCH `{"desired_outcome": "   "}`. **Expect**: the outcome is null. PATCH with 1001 characters. **Expect**: 422.
4. `GET /api/account/export`. **Expect**: `tasks/projects.json` holds `desired_outcome`, `archived_at` and `archived_before_lossless`.
   Purge the account. **Expect**: no project row remains.
5. Log capture across steps 1 – 4. **Expect**: no outcome text and no project name in any log line (FR-030).

## Scenario 3 — client attribution (FR-031)

Send requests with `X-Client: brainbuddy-macos/0.1.0`, `brainbuddy-ios/1.4`, no header, and `evil\nvalue`. **Expect**: the `api_request` lines carry `client=macos client_version=0.1.0`, `client=ios client_version=1.4`, `client=web client_version=-` and `client=other client_version=-`. The raw bad value never appears. Responses are identical in every case.

## Scenario 4 — two clients converge (US1, US2; FR-006 – FR-011; SC-001, SC-002)

These run as kit tests (`BrainBuddyWorkspaceTests/MacIPhoneConvergenceTests.swift`): two `Workspace`s, identities `.macOS` and `.iOS`, one `BrainBuddyFakeServer`, and an injected clock.

1. **Sign-in with local data**: the Mac holds account-less "Garden" (with an outcome) and three tasks. The account already has "garden" and the tag "Calls". Sign in.
   **Expect**: one "Garden" with the outcome kept, one tag, three tasks added, and nothing merged by title (FR-003, SC-003).
2. **Capture**: capture on the Mac. Advance 2 s (debounce), then up to 60 s of `.periodic` ticks on the iPhone. **Expect**: the task is present on the iPhone. Repeat for every FR-007 record type in both directions (SC-001).
3. **Offline matrix**: the Mac goes offline; it makes 20 mixed changes; the store is reopened (relaunch); a response is dropped mid-push (`FakeServerTransport` fault); it reconnects.
   **Expect**: every change is on the server exactly once, and the iPhone shows the same set (SC-002).
4. **Same field offline on both**: both edit the same field offline. **Expect**: the last to reach the server wins per field, and different fields both survive (FR-011).
5. **Archive meets offline capture**: the iPhone archives "Garden" while the Mac, offline, captures into it. **Expect**: the Mac's task lands without the project, with a sync issue: "Project “Garden” was archived on another device, so the task was added without a project."
6. **Account switch**: the Mac signs in as account B with changes waiting for A. **Expect**: "Sign out first to use another account." with "… waiting on this Mac.", and nothing from A sent to B (FR-004, US4-5).
7. **Archive and unarchive across clients**: archive on the iPhone, unarchive on the Mac. **Expect**: memberships are intact on both and on the server (SC-006).

## Scenario 5 — status line (US3; FR-012 – FR-016, FR-019; SC-004, SC-005)

These run as kit tests (contracts/sync-status.md §5) and as host checks.

1. **Snapshot table**: drive every snapshot row of sync-status §3. **Expect**: the exact text, for both `.mac` and `.iPhone`.
2. **Transient failure** (`FakeServerTransport`): fail with 503 for 45 s, then recover. **Expect**: the indicator only, no warning (SC-005).
   Fail for 61 s. **Expect**: "Couldn't sync · Retry" with a reference id in the tooltip. One success later, **expect** "Synced just now".
3. **Session ended**: return 401. **Expect**: "Sign in again to sync" at once, and the waiting changes are kept.
   **Single-flight**: press "Sync now" three times during a running cycle. **Expect**: one follow-up cycle at most, and the button never disabled (FR-019).
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

   **Expect**: no sheet, alert or notification appears and focus never moves (SC-004), and every failure shows a reference id. Recorded in `specs/021-mac-sync/evidence/manual-macos-status.md` (labelled manual): VoiceOver reading of X-01 and X-02, keyboard order, Reduce Motion glyph, and Large sidebar text wrapping after " · ".
5. **iPhone host check** (M-01): the same states on list screens, with Settings › Sync using the same words. Recorded in `specs/021-mac-sync/evidence/manual-ios-status.md`.

## Scenario 6 — upgrade the Mac (US4; FR-020 – FR-023; SC-003)

1. Run `macos/Tests/BrainBuddyMacTests/LegacyStoreImporterTests.swift` (contracts/mac-legacy-import.md §6).
2. **Host check**:
   1. With a pre-021 build, create the design's example data, including review marks and an archived project with tasks, then quit.
   2. Install the 021 build and launch.
      **Expect**: no notice, every record present, the footer reads "On this Mac · Sign in to sync", and `local-gtd.backup-*.json` sits beside `store.json` with the original bytes (compare `shasum`).
   3. Sign in to an account with an overlapping project name.
      **Expect**: one merged project, all tasks on the web, and review marks still present.
   4. Corrupt a copy of `local-gtd.json` and relaunch on a fresh folder.
      **Expect**: X-05, the file unchanged, and an empty workspace only after "Continue".

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
- **iPhone**: package tests cover the reducer and sync. The host check of M-02 (swipe Unarchive, toolbar Unarchive, non-destructive archive confirmation, VoiceOver custom action) is recorded in `specs/021-mac-sync/evidence/manual-ios-archive.md`.

## Scenario 8 — two copies of the Mac app (edge case)

1. Launch the app twice from Finder. **Expect**: the second launch brings the first window forward and exits.
2. Run `swift run BrainBuddyMac` while the bundled app is open. **Expect**: the alert "Brain Buddy is already open." with "Quit", and the store unchanged.

`SingleInstanceGuardTests` covers the lock logic in CI.

## Scenario 9 — owner week (SC-007)

The owner uses Mac, iPhone and web on one account for one week. Each day the owner records in `specs/021-mac-sync/evidence/owner-week.md`:

- "needed Sync now: yes/no";
- "saw Mac and iPhone disagree after a minute online: yes/no";
- the count of sync issues seen.

This is post-release acceptance, not a slice gate.
