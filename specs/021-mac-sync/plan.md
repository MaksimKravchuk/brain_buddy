# Implementation Plan: Mac ↔ backend sync

**Branch**: `021-mac-sync` (work branch `claude/mac-sync-spec`) | **Date**: 2026-10-06 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/021-mac-sync/spec.md`

**Design authority**: [design.md](design.md), signed off by Max on 2026-10-06 with decisions 1 – 3 accepted and gaps G-1 – G-3 resolved by the spec amendment of the same day. It covers:

- **macOS**: screens X-01 – X-08 (X-08 "Second copy of the app" was added on 2026-10-06 from this plan's gap G-8 and is cited by FR-017);
- **iPhone**: M-01, M-02;
- **web**: D-01.

The design's post-sign-off review fixes (commit `20b3451`), the FR-019 amendment (commit `b83d367`) and the spec amendment that resolved this plan's first findings (commit `0b9fffe`: FR-007, FR-009, FR-017, FR-032, X-08, Assumptions) are included:

- the X-03 "signed in, account deletion cancelled" state;
- the approved FR-027 line only;
- "Sync now" stays enabled during a sync (single-flight) on Mac and iPhone.

This plan answers the design's "Notes for the plan" and gap G-7 (G-1 – G-6 were resolved at sign-off; G-8 by X-08). Planning review campaign `021-mac-sync-c1` (63 findings) is dispositioned in [review-c1-disposition.md](review-c1-disposition.md); its fixes are in this plan, the contracts, data-model, research, quickstart, design.md (states added under "Planning review c1 additions") and a minimal spec amendment (FR-003, FR-017, FR-018, FR-021 sentences, new FR-033, two edge cases, Assumptions).

**Risk**: **High / ASK** for the feature as a whole:

- the Mac's first network egress of user data;
- a session credential in the macOS Keychain;
- a one-time import of real local data;
- a behaviour change of an existing endpoint (ADR-0020);
- the ASK paths `backend/app/api/tasks.py`, `backend/app/api/middleware.py`, `.github/workflows/ci.yml`, `scripts/validate_ci_artifacts.py`, `scripts/render_feature_report.py`, `scripts/check_manual_evidence.py`, `Makefile`, `ios/BrainBuddyKit/Sources/BrainBuddyAPI/SessionTokenStore.swift` and `ios/BrainBuddyKit/Tests/BrainBuddySyncTests/SyncEngineSessionTests.swift` (the last two by the classifier's `session` token).

Per-slice classes are in [Delivery slices](#delivery-slices). There is no feature flag (research R15).

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.
Amend the spec first when implementation intent changes.

## Summary

The Mac app stops keeping its own store and rules. It adopts the iPhone's offline-first stack, the local package `ios/BrainBuddyKit` (Core, Persistence, API, Sync, Workspace), so sign-in, the outbox, replay, merge by name, the conflict table and sync issues are the iPhone's own code (FR-011).

- **Upgrade**: the existing `local-gtd.json` is imported once into a kit `StoreDocument` as account-less outbox data, verified, and then kept as a backup (FR-020 – FR-022).
- **Mac-only review marks**: they move to a Mac-only sidecar (FR-023).
- **Status line**: one shared, Linux-tested status description in the kit gives the Mac sidebar footer and the iPhone list screens the same words, thresholds and precedence (FR-012 – FR-019).
- **Server completion**:
  - ADR-0020's lossless archive with unarchive and a list of archived projects;
  - a pre-feature archive marker (FR-027);
  - a project `desired_outcome`;
  - `X-Client` attribution.
- **Other clients**: the iPhone and web get unarchive and the aligned archive copy. The iPhone and web also poll while open, which SC-001 requires.
- **CI**: the Mac app gets its first CI lane.

Technical approach (research R1, R5, R7, R9):

- **Backend**: two backend slices make the archive change rollback-safe: a tolerant validator first, lossless archive second.
- **Kit**: optional `Codable` fields only, so `StoreDocument` stays v1 and does not collide with 020's v2.
- **Mac target**: it shrinks to presentation plus AppKit glue: hot-key, voice, path monitor, timers, single instance, import and review marks.

## Technical Context

**Language/Version**:

- Backend: Python 3.11, FastAPI, Pydantic v2.
- Web: strict TypeScript, React, Vite, React Query.
- `ios/BrainBuddyKit`: Swift 6.2 (`swift-tools-version: 6.2`, Swift 6 mode).
- iPhone app: SwiftUI on iOS 26 (`ios/project.yml`).
- Mac app: SwiftUI on macOS 26. `macos/Package.swift` moves from tools 5.10 to **6.2** with the Swift 6 language mode (research R2).

**Primary Dependencies**: existing only.

- Mac: WhisperKit (`argmax-oss-swift` 0.18.0, unchanged) plus the local `../ios/BrainBuddyKit`.
- First-party frameworks: `Network` (`NWPathMonitor`) and `Security` (Keychain).
- No new third-party dependency anywhere.

**Storage**:

- **Backend**: `<data_dir>/tasks.sqlite3`. Three optional fields go in the `projects.payload` JSON (data-model E1); there is no DDL and no new table.
- **Kit**: `StoreDocument` v1 gains optional fields (E3, E5).
- **Mac** (`~/Library/Application Support/BrainBuddyMac/`):
  - `store.json` (kit);
  - `mac-local.json` (sidecar, E7);
  - `local-gtd.backup-<UTC>.json` (E8);
  - the login-keychain item `app.brainbuddy.mac.session` (E9).
- **Web**: nothing new.

**Testing**:

- pytest with FastAPI TestClient (`api_client`, `second_api_client`).
- Vitest with Testing Library, and Playwright (`frontend/tests/allure.fixtures.ts`).
- Swift Testing in the kit on Linux (`sh ios/scripts/swift-linux.sh test`, CI `ios-kit`) and on macOS (`ios-app`).
- Swift Testing in `macos/Tests/BrainBuddyMacTests` on the new `macos-app` lane.

Every product test names a `021-FR-…` / `021-SC-…` id. pytest, Vitest and Playwright tests emit the Allure taxonomy; Swift tests do not (`ios/README.md` "Known gaps").

**Target Platform**: Linux server (Fly.io); macOS 26 (locally built, ad-hoc signed); iPhone iOS 26; desktop and mobile web.

**Project Type**: modular-monolith web service + native iPhone app + native Mac app sharing one Swift package + web SPA.

**Performance Goals**:

- A change appears on the other open client within 60 s (SC-001). The 15 s tick and 30 s pull age keep the gap between pulls under 45 s plus one pull, so the worst case is about 50 s; the web refetches every 45 s while visible (research R8).
- Local commands apply synchronously; no UI waits on the network (FR-010).
- The legacy import of 2,000 tasks finishes in under 2 s on an M-series Mac. Kit replay of 2,000 operations takes about 45 ms (`docs/native-ios-app.md:328-331`); placeholders show after 300 ms.
- The first load of a large account does not block the window (edge case).

**Constraints**:

- Offline-first on the Mac and iPhone.
- Nothing is sent before sign-in (FR-029).
- No content in logs (FR-030).
- No modal for routine sync (FR-017).
- Idempotent, owner-serialized task commands.
- The ADR-0006 four open lists stay.
- No third-party Swift dependency.
- Swift 6 strict concurrency, checked and not suppressed.

**Scale/Scope**:

- Invite-gated beta: tens of owners, hundreds to low thousands of tasks each.
- One new endpoint, one new query parameter and four new fields.
- 11 designed screens (X-01 – X-08, M-01, M-02, D-01); X-08 is a system alert without a mockup.
- Three clients.

## Constitution Check (pre-design)

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Spec workflow** — PASS.
  - `intake.md`, `spec.md` (Clarifications for 2026-10-06 and the design sign-off), `checklists/requirements.md` (all checked) and the signed-off `design.md` exist. There are no NEEDS CLARIFICATION markers.
  - Inconsistencies found while planning are listed below, with their resolutions (spec commit `0b9fffe` and review c1). None blocks planning. The earlier owner question is answered in spec Assumptions; review c1 adds two owner questions with recommended defaults, neither blocking (see [Open questions](#open-questions-for-the-product-owner)).
- **Consent & Safety** — PASS with design.
  - Nothing leaves the Mac until the person signs in (kit `runCycle` guards on `account`, FR-029). Voice stays local.
  - The session token goes only in the Keychain (E9).
  - No title, note, outcome or email appears in any log, on the server (log-capture test) or the Mac (import report test).
  - The import never overwrites or deletes the old store before verification, and never deletes an unreadable one (FR-021, FR-022). It never writes into or replaces a workspace in use: `store.json` is created only by the exclusive rename of a verified staging file, and a previous-version file that appears later is kept and surfaced (FR-033, data-model E7.1).
  - The Mac's device files, their protection and their lifetime after the app is deleted are written out in data-model E5, E7, E8 and E9 for `docs/data-retention.md`; the pre-021 cookie session is ended and its cookie removed at the first launch.
  - The new server field is exported and purged (E1).
  - Evidence comes from synthetic data only.
  - No AI and no provider.
- **Tests** — PASS with the [Test strategy](#test-strategy). Each slice starts from failing tests: lossless archive, tolerant PATCH, unarchive, outcome, attribution, the import matrix, the status vectors, the convergence and offline matrix, and the UI states per design id.
- **Contracts** — PASS:
  - [contracts/http.md](contracts/http.md), [contracts/kit-commands.md](contracts/kit-commands.md), [contracts/sync-status.md](contracts/sync-status.md), [contracts/mac-legacy-import.md](contracts/mac-legacy-import.md) and [contracts/mac-app-host.md](contracts/mac-app-host.md).
  - Changes are additive except the ADR-0020 archive side effect, whose compatibility story is in http.md §7 – §8.
  - The backend lands before the clients that use it.
  - The kit document version is unchanged.
- **Observability** — PASS:
  - The existing `CorrelationIdMiddleware` gains `client` and `client_version`.
  - The kit sends one `X-Correlation-ID` per request. It is shown as the reference id on every surfaced failure and sync issue (X-01 tooltip, X-02 Copy, X-03 errors, M-01 via Settings), including timeouts (FR-015).
  - The Mac's `os.Logger` lines are counts and classes only.
- **Mobile/resilience/performance** — PASS:
  - Offline everything except sign-in.
  - The outbox survives quit, crash and relaunch (kit).
  - Lost responses are replayed by idempotency key; uncertain creates older than 23 h are matched (kit).
  - The import is crash-safe at every step (mac-legacy-import §6).
  - Single instance.
  - There is no canvas impact.
- **Delivery boundary** — PASS. Spec Kit artifacts are planning input only. Each slice uses its own worktree, TDD, independent verification and exact-SHA CI, and carries the ADR-0008 class stated per slice, re-derived from `scripts/classify_path_risk.py --null` over every slice's full path list (see [Delivery slices](#delivery-slices)); ASK slices need a PR plus the owner's recorded approval.
- **Design citation** — PASS. Each user-story section below names the design ids and states it realizes. Requirements with no affordance (design "Requirements with no affordance": FR-005, FR-007 – FR-011, FR-017, FR-020, FR-021, FR-023, FR-027 – FR-032) are covered by backend, kit, web and Mac tests named in the Test strategy.

## Current repository trace

Facts this plan builds on, verified 2026-10-06 at `e50b144` and re-checked at `0b9fffe`: every commit since `e50b144` changes only `specs/`, so the code facts hold. Review c1 re-read the files it cites (rows marked c1).

### Backend

| file | current responsibility | planned use |
|---|---|---|
| `backend/app/api/tasks.py` (**ASK**) | project routes: `POST/GET /projects` (l.539 – 573, `GET` active only, no params), `PATCH /projects/{id}` (576), `POST /projects/{id}/archive` (599), `GET /projects/{id}` (622, any state); `_to_project_response` (l.1238 – 1250) | `?state=`; `POST /projects/{id}/unarchive`; three new response fields |
| `backend/app/modules/tasks/service.py` | `archive_project` (l.958 – 1013, clears `project_id` on all member tasks); `update_task` validates the current project when `project_id` is absent (l.649 – 655); `_assert_active_references` (1344 – 1364); `_assert_unique_project_name` (1523 – 1534, active only); idempotency prefixes in `_apply_idempotent_record` / `_project_result` (1145 – 1203); `_request_hash` (1294 – 1314); `list_projects` active-only (870 – 878) | tolerant validation (PR-02); lossless archive (PR-03); `unarchive_project`; state filter; outcome |
| `backend/app/modules/tasks/domain.py` | `ProjectDocument` (l.31 – 43: no `archived_at`, no outcome) | E1 fields |
| `backend/app/modules/tasks/repository.py` | `projects` table with JSON payload (l.102 – 109); `migration_ledger` (174 – 238); `delete_all_for_owner` (644 – 680) | `_mark_detached_archives()` startup step |
| `backend/app/schemas/tasks.py` | `ProjectCreateRequest` (53 – 55), `ProjectUpdateRequest` (58 – 61), `ExpectedRevisionRequest` (64 – 65), `ProjectResponse` (82 – 88); `StrictBaseModel` `extra="forbid"` | E2 |
| `backend/app/api/middleware.py` (**ASK**) | `CorrelationIdMiddleware` (l.22 – 75): incoming `X-Correlation-ID` or `X-Request-ID` accepted verbatim (l.38 – 41), bound into every log line and echoed (l.65) (c1) | `client` / `client_version` fields; incoming id accepted only when it matches `^[0-9A-Za-z._-]{1,64}$` |
| `backend/app/api/tasks.py:562`, `backend/tests/test_api_contract.py:247` (c1) | `GET /projects` declares `error_responses(401)`; the contract map asserts `{"401"}` by exact set equality | `(401, 422)` for `?state=` |
| `backend/app/services/account_service.py` | export writes every project with `model_dump` (l.265 – 273); purge (416 – 493) | unchanged; covered by tests |
| `backend/tests/test_task_api.py:753`, `test_task_lifecycle_detail_api.py:367`, `test_task_tag_project_mvp_api.py:52`, `test_task_api.py:470` (556 – 566) | assert archive **clears** memberships | flipped in PR-03 |
| `backend/tests/test_task_branch_coverage.py` (~326 `test_update_task_rejects_inactive_project_on_reassignment`, 1513 `test_list_projects_filters_inactive_records`) | reassignment rejection; active-only list | kept; extended for the unchanged-membership case and `?state=` in PR-02 |
| `backend/tests/test_api_contract.py` | exact set of operations → error statuses (l.32 – 411) | add unarchive |
| `contracts/api-client-parity.json` | wire inventory read by `frontend/src/api/__tests__/clientParity.test.ts` and `ios/BrainBuddyKit/Tests/BrainBuddyAPITests/TaskListQueryTests.swift` | `unarchiveProject`, `listProjects(state)` |
| `docs/api-compatibility.md` | "There is no mobile/iOS client contract yet" (stale) | dated client note (R16) |

### Kit and iPhone

| file | current responsibility | planned use |
|---|---|---|
| `ios/BrainBuddyKit/Sources/BrainBuddyCore/Records.swift` | `ProjectRecord` (122 – 144) without outcome or archive instant | E3 |
| `…/BrainBuddyCore/Commands.swift` | `GTDCommand` (60 – 74), validation copy (`.projectNotActive` l.280) | `setProjectOutcome`, `unarchiveProject`, `createProject.desiredOutcome`, new errors |
| `…/BrainBuddyCore/Reducer+Organize.swift` | archive clears membership (56 – 70); merge by name (22 – 25, 89 – 92) | lossless archive, unarchive, outcome merge rule |
| `…/BrainBuddyCore/Reducer+Validation.swift`, `Reducer+Replay.swift` | `checkReferences` (78 – 89); `replayable` drops archived refs (31 – 75) | carried-membership rule |
| `…/BrainBuddyCore/Replay.swift` (c1) | `rewritingAfterMerge(_:project:into:)` (l.101 – 118) calls `withdrawing(project:from:)` (l.145 – 159) when the outbox archives the merged project, creating its tasks without a project | membership follows the survivor; the archive becomes a sync issue (kit-commands §3) |
| `…/BrainBuddyCore/Compaction.swift` (c1) | `foldMove` folds a move into an unsent creation (l.100 – 112); compaction changes `waitingSince`, `orderKey`, `editedAt` (l.24 – 28) | not used by the legacy import |
| `…/BrainBuddyCore/Outbox.swift` | `StoreDocument` v1 (127 – 152), `SyncMetadata` (112 – 121), `SyncStatus` (156 – 166) | E5 fields |
| `…/BrainBuddyCore/SmartAdd+Resolution.swift` | archived project refusal copy (96 – 101) | "Unarchive … before adding a task to it." |
| `…/BrainBuddyAPI/BrainBuddyAPI.swift`, `BrainBuddyAPIClient.swift` | constant `clientName = "brainbuddy-ios"` (l.14), headers (308 – 321), per-id archived fetch (l.90) | `ClientIdentity`; `listProjects(state:)`; `unarchiveProject` |
| `…/BrainBuddyAPI/SessionTokenStore.swift` (**ASK** by token) | `KeychainSessionTokenStore(service:accessGroup:)` (130); sets `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` on add and update (l.168, 224) (c1) | reused by the Mac with its own service; on macOS no `kSecAttrAccessible`, explicit non-synchronizable (PR-05) |
| `…/BrainBuddySync/SyncEngine.swift`, `SyncEngine+Cycle.swift`, `SyncEngine+Pull.swift`, `SyncEngine+Push.swift`, `SyncConfiguration.swift`, `BrainBuddySync.swift` | triggers without `.periodic`; every non-`localChange` trigger sets `pullRequested` and kicks a cycle (`SyncEngine.swift:235-250`), every cycle starts with `.syncing` (`+Cycle.swift:16`); `kick()` cancels a scheduled retry (l.320 – 345); `retryDelay` 2 s, 4 s, 8 s … ±20 % (`SyncConfiguration.swift:76`); `pullInterval` 60 s checked per cycle (`+Cycle.swift:34`); account-switch text with "iPhone" (`SyncEngine.swift:195`); `.failing` after 2 cycles (c1) | `.periodic` (no-op when idle); `failingSince` and `lastFailedAttemptAt`; one attempt at the 60 s mark; device-neutral refusal; `?state=all` pull; immediate revert on a refused unarchive |
| `…/BrainBuddySync/SyncScheduler.swift` | `SyncScheduler` and `ManualSyncScheduler` | used by the new `PeriodicSyncTicker` |
| `…/BrainBuddyPersistence/FileDocumentStore.swift`, `DocumentFile.swift` | injectable `fileURL`; `flock` lock; atomic write with `F_FULLFSYNC` | used by the Mac unchanged |
| `…/BrainBuddyWorkspace/Workspace.swift` | `@MainActor @Observable`; `archiveProject` doc says there is no unarchive (320 – 324); `signIn` / `signOut(discardUnsyncedChanges:)` / `syncNow` / `networkAvailabilityChanged`; `signOut` counts only outbox operations, ends the session (`sync.signOut()`, l.407) **before** `store.destroy` (l.412) (c1) | `unarchiveProject`, `setProjectOutcome`, `apply([…])`, `syncSnapshot`, device kind; sign-out order: destroy first, end the session after |
| `…/BrainBuddyFakeServer/FakeServer+Organize.swift` (75 – 89) | archive clears membership; no unarchive | mirrors http.md |
| `ios/BrainBuddy/Components/SyncStatusLabel.swift` (37 – 68) | iPhone wording with em dashes, "Syncing…", immediate "Sync failed — …" | renders `SyncStatusDescriber` (M-01) |
| `ios/BrainBuddy/Screens/Settings/SyncIssuesScreen.swift` (104 – 244) | issue descriptions | delegates to `SyncIssueDescriber` (kit) |
| `ios/BrainBuddy/Screens/Browse/ProjectsScreen.swift` (76 – 86, 126 – 145, 193 – 220) | destructive archive confirmation; read-only Archived projects list | M-02 copy, swipe and toolbar Unarchive |
| `ios/BrainBuddy/Screens/Lists/TaskListScreen.swift` (280 – 287) | "This project is archived / … read-only" | M-02 archived project screen |
| `ios/BrainBuddy/App/BrainBuddyApp.swift` | foreground `syncNow`, NWPathMonitor, BGAppRefresh (58 – 166); `WidgetReloadAfterSync` reloads every widget timeline on each syncing → idle change (l.124 – 135) (c1) | toggles the kit `PeriodicSyncTicker` with the scene phase |

### Mac

| file | current responsibility | planned use |
|---|---|---|
| `macos/Package.swift` | tools 5.10, WhisperKit, XCTest target | tools 6.2, kit products, test resources |
| `macos/Sources/BrainBuddyMac/LocalGTDStore.swift` (1363 lines) | JSON snapshot store, rules, review receipts, archive/restore; `init` never writes (l.194 – 206), but `mutate` creates `local-gtd.json` on the first write when it is missing and the in-memory generation is 0 (l.214 – 262), so a pre-021 copy launched after the update writes a fresh file (c1) | **deleted** after import code reads its format (`LegacySnapshot.swift`); the FR-033 rule handles the fresh file |
| `macos/Sources/BrainBuddyMac/APIClient.swift` (731) | online-only REST client, `httpCookieStorage = .shared` (l.431 – 432) (c1) | **deleted**; its cookie is removed and its session ended by `LegacyCookieCleanup` |
| `macos/Sources/BrainBuddyMac/SmartAddParser.swift` (270) | Smart Add | **deleted**; kit `CapturePlanner` |
| `macos/Sources/BrainBuddyMac/ContentView.swift` (4201) | `BrainBuddyModel` (14 – 1379) + all views; sidebar (1958 – 2083); `isLocalWorkspace` gates; sign-in view, session overlay, conflict banner, toolbar Refresh | binds to `Workspace`; removals per contracts/mac-app-host.md §3; footer → X-01 |
| `macos/Sources/BrainBuddyMac/ProjectReviewView.swift`, `QuickCaptureView.swift`, `QuickOpenView.swift`, `VoiceCapture.swift` | project review, ⌃⌥⇧B capture panel, Quick Open, WhisperKit | rebind to `Workspace` and the sidecar; `VoiceTranscriber` actor (R2) |
| `macos/Sources/BrainBuddyMac/BrainBuddyMacApp.swift` | single `Window` scene | launch order (mac-app-host §1), `SyncMenuCommands` |
| `macos/Tests/BrainBuddyMacTests/*` (XCTest, 71 tests) | store, API client, parser, offline journeys | rewritten in Swift Testing (Test strategy) |
| `macos/AppInfo.plist`, `macos/build_app.sh` | bundle id `com.brainbuddy.mac.prototype`; ad-hoc signed `.app` | unchanged |

### Web

| file | current responsibility | planned use |
|---|---|---|
| `frontend/src/api/client.ts` (343 – 369) | `listProjects`, `createProject`, `updateProject`, `archiveProject` | `listProjects(state)`, `unarchiveProject` |
| `frontend/src/api/taskTypes.ts` (59 – 66) | `ProjectResponse.state: "active" \| "completed" \| "archived"` (drifted) | `"active" \| "archived"`; new fields |
| `frontend/src/api/taskHooks.ts` (35, 62, 71, 78) | `useTaskList`, `useTaskDetail`, `useProjects`, `useTags`, none polling; the list items carry no subtasks or comments (`backend/app/api/tasks.py:766`, only the detail route fills them) (c1) | `state: "all"`; `refetchInterval: 45_000` while visible on all four |
| `frontend/src/components/shell/AppShell.tsx` (568 – 649) | Projects section, active only, archive button | "Archived projects" disclosure (D-01) |
| `frontend/src/features/tasks/TaskListPage.tsx` (411 – 434, 475, 1073 – 1095) | archive mutation; project title fallback "Project"; grouping fallback "No project" | archived project page, Unarchive, "· archived" labels |
| `frontend/src/features/tasks/TaskDetailPanel.tsx` (349) | project name from the active list | resolves archived names |

### CI and governance

| file | fact | planned use |
|---|---|---|
| `.github/workflows/ci.yml` (**ASK**) | `changes` outputs `backend`, `frontend`, `ios` (`^ios/` only, l.179); `ios-kit` (515), `ios-app` (547, `macos-26` when iOS changed); no `macos/` lane | `macos` output and `macos-app` lane (research R3) |
| `scripts/validate_ci_artifacts.py` (**ASK**) | `LANE_DEPENDENCY_LIMITS` (702 – 731), path-filter job list (602 – 611), `full-ci` / `allure-report` completeness (757 – 790) | register `macos-app` |
| `scripts/render_feature_report.py` (**ASK**) | `SCREEN_ID_RE = [DM]-\d{2}` (l.53) | `[DMX]-\d{2}` (G-7) |
| `scripts/check_requirement_coverage.py` (**ASK**, guarded) | scans only `.py .ts .tsx .js .jsx` under `backend/tests`, `frontend/tests`, `frontend/src`; no `--requirements` flag (l.54 – 63, 141) (c1) | 020 PR-01 adds `.swift` + `ios/BrainBuddyKit/Tests` + `macos/Tests` and `--requirements` (in flight); 021 consumes it, no edit; interim evidence rule in the Test strategy |
| `Makefile` (**ASK**, guarded) | `check-specs` runs coverage for 019 only | add 021 in PR-10 |
| `.github/workflows/ci.yml` `changes` (l.160 – 190), `.github/workflows/ios.yml:86` (c1) | the landing path exercises every stack whatever the diff; `ios.yml` uploads to TestFlight on any `^ios/` change on `main` | the trace-equality pytest runs on every landing; backend slices write nothing under `ios/` |

## Project Structure

### Documentation (this feature)

```text
specs/021-mac-sync/
├── intake.md, spec.md, design.md, design/*.html, checklists/requirements.md   (existing)
├── plan.md                      # this file
├── research.md                  # Phase 0
├── data-model.md                # Phase 1
├── contracts/
│   ├── http.md                  # backend API changes
│   ├── kit-commands.md          # BrainBuddyKit records, commands, reducer, sync, identity
│   ├── sync-status.md           # shared status presentation (X-01, X-02, M-01)
│   ├── mac-legacy-import.md     # local-gtd.json → StoreDocument
│   └── mac-app-host.md          # Mac process, files, triggers, sign-in, UI binding
├── quickstart.md                # validation scenarios
├── review-c1-disposition.md     # planning review campaign 1 dispositions
├── evidence/                    (new, during delivery; manual host records, owner week)
└── tasks.md                     # /speckit-tasks (not created here)
```

### Source Code (repository root)

New files are marked `(new)`, deleted files `(deleted)`; everything else exists today.

```text
backend/
├── app/
│   ├── api/tasks.py                          # ASK: ?state=, unarchive route, response fields
│   ├── api/middleware.py                     # ASK: X-Client parsing in log lines
│   ├── schemas/tasks.py                      # desired_outcome, ProjectResponse fields
│   └── modules/tasks/
│       ├── domain.py                         # E1 fields
│       ├── repository.py                     # _mark_detached_archives()
│       └── service.py                        # tolerant update_task; unarchive_project; lossless archive (PR-03)
└── tests/
    ├── test_project_archive_lossless_api.py  (new)
    ├── test_project_desired_outcome_api.py   (new)
    ├── test_client_attribution_logging.py    (new)
    ├── test_project_archive_traces.py        (new)
    ├── fixtures/project_archive_traces.json  (new, canonical; copied to the kit)
    ├── test_task_api.py, test_task_lifecycle_detail_api.py, test_task_tag_project_mvp_api.py,
    │   test_task_branch_coverage.py, test_api_contract.py, test_account_export.py,
    │   test_account_deletion.py              # updated
    └── allure_taxonomy.py                    # rules for the new test modules
contracts/api-client-parity.json

ios/BrainBuddyKit/
├── Package.swift                             # test resources for BrainBuddySyncTests (trace copy, PR-04)
├── Sources/BrainBuddyCore/   Records.swift, Commands.swift, Reducer+Organize.swift,
│                             Reducer+Validation.swift, Reducer+Replay.swift, Replay.swift,
│                             Outbox.swift, SmartAdd+Resolution.swift,
│                             SyncPresentation.swift (new), SyncActivityIndicator.swift (new),
│                             SyncIssueDescriber.swift (new), TaskEditDraft.swift (new),
│                             RecordContentStamp.swift (new), Queries+ProjectDisplay.swift (new)
├── Sources/BrainBuddyAPI/    BrainBuddyAPI.swift, BrainBuddyAPIClient.swift, APIError.swift,
│                             WireModels.swift, RequestBodies.swift, SessionTokenStore.swift (ASK)
├── Sources/BrainBuddySync/   BrainBuddySync.swift, SyncConfiguration.swift, SyncEngine.swift,
│                             SyncEngine+Cycle.swift, SyncEngine+Pull.swift, SyncEngine+Push.swift,
│                             SyncEngine+Session.swift, GTDCommand+Sync.swift, PushPlanner.swift,
│                             StoreDocument+Merge.swift, PeriodicSyncTicker.swift (new)
├── Sources/BrainBuddyWorkspace/Workspace.swift
├── Sources/BrainBuddyFakeServer/ FakeServer+Organize.swift, ServerState.swift
└── Tests/  BrainBuddyCoreTests/{ReducerOrganizeTests.swift, ReducerArchiveTests.swift (new),
            ReplayTests.swift, SmartAddParserTests.swift, SyncPresentationTests.swift (new),
            SyncActivityIndicatorTests.swift (new), SyncIssueDescriberTests.swift (new),
            TaskEditDraftTests.swift (new), RecordContentStampTests.swift (new),
            ProjectDisplayTests.swift (new)}
            BrainBuddyPersistenceTests/StoreDocumentCodingTests.swift
            BrainBuddyAPITests/{EndpointRequestTests.swift, WireDecodingTests.swift,
            ClientIdentityTests.swift (new)}
            BrainBuddySyncTests/{SyncEnginePullTests.swift, SyncEngineSchedulingTests.swift,
            SyncEngineSessionTests.swift (ASK), ProjectArchiveSyncTests.swift (new),
            SyncEngineFailingClockTests.swift (new), ProjectArchiveTraceReplayTests.swift (new),
            PeriodicSyncTickerTests.swift (new), Resources/project_archive_traces.json (new copy)}
            BrainBuddyWorkspaceTests/{WorkspaceCommandTests.swift, WorkspaceSyncTests.swift,
            MacIPhoneConvergenceTests.swift (new), FirstSignInMergeTests.swift (new)}

ios/BrainBuddy/
├── App/BrainBuddyApp.swift                   # .periodic tick while active
├── Components/SyncStatusLabel.swift          # renders SyncStatusDescriber (M-01)
├── Screens/Lists/TaskListScreen.swift        # M-01 status row; M-02 archived project
├── Screens/Browse/ListsHubScreen.swift, ProjectsScreen.swift   # M-01 hub row; M-02
└── Screens/Settings/SettingsScreen.swift, SyncIssuesScreen.swift, SignInSheet.swift
ios/AGENTS.md, docs/native-ios-app.md

macos/
├── Package.swift, Package.resolved, README.md
├── Sources/BrainBuddyMac/
│   ├── BrainBuddyMacApp.swift, ContentView.swift, ProjectReviewView.swift,
│   │   QuickCaptureView.swift, QuickOpenView.swift, VoiceCapture.swift
│   ├── WorkspaceHost.swift (new), SingleInstanceGuard.swift (new), MacLocalState.swift (new),
│   │   LegacySnapshot.swift (new), LegacyStoreImporter.swift (new), UpgradeNotice.swift (new),
│   │   LegacyCookieCleanup.swift (new), ProjectMenuCommands.swift (new),
│   │   SyncTriggerSource.swift (new), SyncStatusLine.swift (new), SyncStatusPopover.swift (new),
│   │   SignInSheet.swift (new), SignOutConfirmation.swift (new), SyncMenuCommands.swift (new),
│   │   MacPresentationRouter.swift (new)
│   └── LocalGTDStore.swift, APIClient.swift, SmartAddParser.swift (deleted)
└── Tests/BrainBuddyMacTests/
    ├── OfflineWorkspaceTests.swift            # rewritten against the kit, Swift Testing
    ├── LegacyStoreImporterTests.swift (new), MacLocalStateTests.swift (new),
    │   SingleInstanceGuardTests.swift (new), LegacyCookieCleanupTests.swift (new),
    │   SyncTriggerSourceTests.swift (new), MacSyncFlowTests.swift (new),
    │   MacPresentationRouterTests.swift (new), MacKeychainTests.swift (new),
    │   MacPrivacyGuardTests.swift (new)
    ├── Resources/legacy-populated.json, legacy-corrupt.json, legacy-newer.json (new, synthetic)
    └── APIClientTests.swift, LocalGTDStoreTests.swift, SmartAddParserTests.swift (deleted)

frontend/
├── src/api/client.ts, taskTypes.ts, taskHooks.ts, __tests__/client.test.ts, __tests__/clientParity.test.ts,
│   __tests__/taskHooks.test.ts
├── src/components/shell/AppShell.tsx, __tests__/AppShell.test.tsx
├── src/features/tasks/TaskListPage.tsx, TaskDetailPanel.tsx, ArchivedProjectNotice.tsx (new),
│   __tests__/TaskListPage.test.tsx, __tests__/ArchivedProjectNotice.test.tsx (new),
│   __tests__/TaskDetailAutosaveUI.contract.test.tsx
└── tests/e2e/archived-projects.spec.ts (new), tests/e2e/cross-client-refresh.spec.ts (new)

.github/workflows/ci.yml, scripts/validate_ci_artifacts.py, scripts/test_validate_ci_artifacts.py,
scripts/render_feature_report.py, scripts/test_render_feature_report.py, Makefile,
scripts/check_manual_evidence.py (new), scripts/test_check_manual_evidence.py (new),
.specify/gate-integrity.json
docs/native-macos-app.md (new), docs/api-compatibility.md, docs/data-retention.md, AGENTS.md
```

**Structure Decision**:

- **Backend**: the work stays inside the Tasks module (`backend/app/modules/tasks/`), which owns projects and tasks (ADR-0001). Thin route changes live in the existing `backend/app/api/tasks.py`, and nothing touches CRT trees or another module's data.
- **Rules**: every GTD rule stays in `BrainBuddyCore`, and both Apple apps render its queries. The kit stays at `ios/BrainBuddyKit` (research R1 rejects the rename).
- **Mac target**: it gains only AppKit glue and Mac-only device state. New Mac file names avoid the classifier's ASK tokens only where the content is not an ASK surface. The ASK classes of PR-08 and PR-09 are stated semantically below, not hidden by naming.
- **No renaming around the gate** (review c1, F01): PR-05's session-end, account-switch, sign-out-order and token-store changes are a session surface, so its existing `SyncEngineSessionTests.swift` and `SessionTokenStore.swift` keep their names and PR-05 is ASK, rather than moving the tests to a file whose name carries no token.

## Architecture by user story

### US1 — Sign in on the Mac and stay in sync (P1) — design X-03 (default, loading, errors incl. "no answer" and "couldn't save sign-in", after sign-in: first load), X-01 (first load, first upload, synced, syncing), X-02 (default, loading, first upload), X-04 (nothing unsent, unsent changes, open sync issues, backup kept, during the first upload, error, after sign-out), X-07 (default, app menu), X-08 (default, unreachable), M-01 (synced, first sync, Settings › Sync running, sign-out with open issues)

**Mac**

- **Store**: `WorkspaceHost` builds the kit `Workspace` over `~/Library/Application Support/BrainBuddyMac/store.json` with the Mac keychain service, the macOS client identity and a 30 s pull age (contracts/mac-app-host.md §1).
- **Single instance (X-08)**: a second copy brings the running window forward and quits; only when that is impossible it shows X-08 ("Brain Buddy is already open." / "Switch to the open window to keep working.", "OK") and quits (research R6).
- **Sign-in (X-03)**: the sheet replaces the full-window sign-in and the session overlay. It calls `Workspace.signIn` (FR-001). After success the sheet closes with no toast, and X-01 reads "Not synced yet" with the indicator while the first pull fills lists progressively (US1-1). The kit's `pullFirst` makes the first cycle pull before it pushes, so account-less data merges by name (FR-003). Cancel and Esc stay enabled while "Signing in…" runs; focus returns to the status words when the opener is gone (contracts/mac-app-host.md §7).
- **Cancelled deletion (X-03)**: when signing in cancelled a pending account deletion, the sheet shows its "signed in, account deletion cancelled" note before closing (FR-017).
- **Triggers (FR-006)**: `SyncTriggerSource` drives launch, activation (forced pull, US1-4), the 2 s local-change debounce, network return and the kit's `PeriodicSyncTicker` (15 s), plus "Sync now" ⌘R from File and from the popover (X-07). The toolbar "Refresh" is removed. A tick with nothing to do runs no cycle and changes no status (kit-commands §4).
- **"Sync now" is single-flight**: it is never disabled by a running sync. A press during a sync joins it or queues one follow-up (FR-019 as amended; contracts/kit-commands.md §4).
- **Selection, scroll and editing (FR-009, US1-5)**: selection, scroll and focus are keyed by `EntityID` through the kit's `SelectionAnchor`. The inline editor holds a kit `TaskEditDraft` and sends only changed fields, so incoming changes to other fields survive and the person's fields win (research R18; kit-commands §8). Both are Linux-tested pure helpers, not view code.
- **Sign-out (X-04, US1-6, FR-005, FR-018)**:
  - The confirmation shows `signOutNothingUnsent` (decision 3) or the unsent-changes variants, with "Cancel" as the default, followed by `signOutIssues(n)` when sync issues are open (they never reached the account) and `signOutBackup(until)` while the pre-upgrade backup exists.
  - The kit removes the account's data first and only then ends the session and removes the token, queueing the logout when offline (kit-commands §4 "Sign-out order").
  - The sidecar marks and the backup follow E7 and E8.
  - A local removal failure shows "Couldn't sign out", removes nothing, and leaves the person signed in, as the copy says.

**Kit**

- `ClientIdentity.macOS(version:)` is used (FR-031).
- The `.periodic` trigger, the `PeriodicSyncTicker`, the forced pull on foreground and the sign-out order are added (contracts/kit-commands.md §4).

**iPhone (FR-032)**

- **Periodic pull**: the iPhone toggles the kit's `PeriodicSyncTicker` with the scene phase (`ios/BrainBuddy/App/BrainBuddyApp.swift`), so Mac changes reach an open iPhone within SC-001's 60 s (research R8). `WidgetReloadAfterSync` keeps firing only on real cycles, because an idle tick changes no status.
- **Sign-out**: the Settings sign-out confirmation names open sync issues with the same catalogue sentence (FR-018).

**Web (FR-032)**

- **Polling**: `useTaskList`, `useProjects`, `useTags` and the open task's `useTaskDetail` refetch every 45 s while the tab is visible (SC-001 Mac → web; research R8). The detail refetch goes through the panel's existing autosave conflict handling, so typed text is never overwritten and scroll and selection do not move.

### US2 — Keep working offline; nothing is lost (P1) — design X-01 (offline / interrupted, changes waiting), X-02 (changes waiting, offline), X-06 (offline / interrupted), M-01 (offline)

- **Offline-first**: every Mac command applies locally at once through `GTDReducer` and is appended to the outbox in the same atomic document write, before the UI returns (FR-008, FR-010). Quick capture, voice to draft and Smart Add never touch the network.
- **Network state**: `NWPathMonitor` feeds `networkAvailabilityChanged`. Offline, the line reads "Offline · N changes waiting" (calm; US2-1).
- **Relaunch and reconnect**: after a relaunch the outbox is reloaded from `store.json` (US2-2). On reconnect `.networkRestored` forces a cycle (US2-3, within 60 s).
- **Lost replies**: retries reuse the operation's `Idempotency-Key`. Creates whose first uncertain send is older than 23 h are matched before resending (kit, US2-4, FR-011).
- **Conflicts**: per field, the last change to reach the server wins. A rejected change becomes a sync issue with its reference id (US2-5). The archived-elsewhere case is resent without the project and listed (contracts/kit-commands.md §5).
- **Proof**: SC-002 is proven by the kit's offline matrix (quickstart Scenario 4).

### US3 — Compact status, errors only when something is wrong (P2) — design X-01 (every state incl. "error, then offline", hover tooltip with "Last tried", long text, dark, keyboard focus), X-02 (every state incl. issue dismissal focus and the kept-outcome issue), X-07 (unavailable), M-01 (every state, Lists hub and Settings › Sync)

- **One describer**: `SyncStatusDescriber`, `SyncActivityIndicator` and `SyncTiming` in `BrainBuddyCore` (contracts/sync-status.md) decide the words, precedence, tone, glyph, action, tooltip and the 1 s / 0.5 s / 10 s / 60 s thresholds for both devices (FR-012 – FR-014, FR-019). The apps only render.
- **Mac X-01** (`SyncStatusLine.swift`): one line of 11 pt secondary text. It has a reserved indicator slot (a static glyph under Reduce Motion), at most one trailing action ("Sign in to sync" / "Retry"), and wraps after " · " for large sidebar text. Its accessibility name is "Sync status: … Show details". Entering an attention state is announced once, politely. It never opens a sheet or takes focus (FR-017, SC-004).
- **Mac X-02** (`SyncStatusPopover.swift`): a non-modal popover. It shows:
  - the last sync time and the waiting count with the oldest age;
  - issues, from `SyncIssueDescriber`, with "Copy" and "Dismiss";
  - "Sync now";
  - the email with "Sign out…".

  Focus order: attention action → Copy → Dismiss → Sync now → Sign out…. Esc or a click outside closes it and focus returns to the words (FR-015, FR-016). It is at most 480 pt tall.
- **Failing clock**: `failingSince` and `lastFailedAttemptAt` are persisted (E5). The engine keeps its backoff but schedules one attempt at exactly `failingSince + 60 s`; "Couldn't sync · Retry" appears only if that attempt fails, so an outage that ends within 60 s never shows (FR-014, SC-005). It survives a relaunch, clears on the next success, and yields to "Offline" while offline without restarting the clock. "Last tried" updates after every attempt, Retry included (FR-013's quiet indicator otherwise hides a fast failing Retry). An ended session shows at once (US3-5).
- **No dialog by construction (SC-004)**: `MacPresentationRouter` is the only presenter and takes only user intents; a macOS-lane test sweeps every status state and transition and asserts no presentation and no focus request (contracts/mac-app-host.md §6, §8).
- **iPhone M-01**:
  - The list screens' status uses `SyncStatusLabel`, which renders the describer: words plus the indicator, with "Syncing…" and immediate failures gone. The attention rows become buttons: Retry runs Sync now; "Sign in again" opens the sign-in sheet with the email locked; "N changes couldn't sync" opens Sync issues. The "Couldn't sync" row's long-press offers "Copy reference ID", and Settings › Sync shows the Reference ID from the first failure on (SC-004).
  - Settings › Sync keeps its detailed section with the same words (US3-8). Its "Sync now" button stops being disabled while a sync runs, because it is single-flight on both platforms (FR-019 as amended).
  - `ios/AGENTS.md`'s copy example becomes "Offline · 3 changes waiting".

### US4 — Upgrade the Mac without losing anything (P2) — design X-05 (every state incl. "couldn't carry over" and "later file"), X-01 (account-less, first upload), X-02 (empty: signed out, first upload, outcome kept on account, archive not applied at merge, pre-upgrade backup, earlier-version file kept), X-03 (first sign-in with local tasks, account switch refused, partial failure)

- **Import (FR-020 – FR-022, FR-033)**: `LegacyStoreImporter` (contracts/mac-legacy-import.md) runs before the workspace opens. It turns every legacy record into kit commands at their original instants, in one global order per list, without compaction, into a staging file; verifies it field by field; records completion; only then moves it to `store.json` with an exclusive rename and renames the old file to a backup.
  - A normal upgrade is silent (X-05 default), and placeholders show after 300 ms.
  - An unreadable, newer or partly bad file leaves the old file untouched and shows the X-05 alert once; a verification failure has its own "couldn't carry over" copy, because the file is fine.
  - The interpretation "partial read = unreadable" is confirmed.
  - **Import state** (review c1, blocking F02): explicit and durable (`none`, `inProgress`, `completed`, `unreadable`, `laterFileKept`; data-model E7.1). The importer never writes into or replaces a workspace in use, even when `mac-local.json` is lost, because it creates `store.json` only by an exclusive rename. A `local-gtd.json` that appears after the workspace exists (an older copy run after the update, a restore, a moved file) is kept untouched and surfaced once (X-05 "later file") and then by a quiet X-02 line, never imported, merged or overwritten (FR-033).
- **Review marks (FR-023)**: they move to `mac-local.json`, keep their meaning, and survive sign-in and sign-out (E7.2). Their stamp is the kit's `RecordContentStamp`, a salted digest of user-visible fields, so the upload's server-minted times and the `c:` → `s:` re-keying do not invalidate them.
- **Legacy session** (review c1, F36): the pre-021 app's session cookie is removed from the shared cookie storage at the first launch and its server session is ended, or queued for logout (contracts/mac-app-host.md §1).
- **Account-less use (US4-2)**: the account-less Mac shows "On this Mac · Sign in to sync" and works fully offline (FR-002). Nothing is sent (FR-029); a counting-transport test proves it.
- **First sign-in (US4-3, FR-003, SC-003)**:
  - X-03 shows the one-time info box when the outbox holds account-less data.
  - The kit merges projects and tags by name and appends tasks. Merging joins **active** projects only. An archived Mac project that meets an active account project joins it with its membership kept, and its archive becomes a sync issue; one that meets only an archived account project stays a separate archived project, a documented limit not counted under SC-003 (kit-commands §3; spec edge case "Same-named archived projects").
  - A merged project's desired outcome is kept, or, when the account already has one, shown in full in a sync issue with "Copy outcome" (FR-003).
  - The first upload reads "Not synced yet" and, in X-02, "Adding your tasks to your account · N left"; waiting ages count from the account link, not from the records' original dates (data-model E6).
  - Rejected records become sync issues (X-03 partial failure).
- **Account switch (US4-5, FR-004)**: refused while the outbox or issues are non-empty, with the device-neutral copy and the "Mac" noun.
- **Known limit**: after the first sign-in, server-minted timestamps replace local `createdAt` and `completedAt` (research R5). Resolved in spec Assumptions (`0b9fffe`).

### US5 — Archive without losing tasks, and unarchive (P3) — design X-06 (every state), M-02 (every state), D-01 (every state)

**Backend**

- **PR-02 (tolerant contract)**: tolerant PATCH validation; `GET /projects?state=`; `POST /projects/{id}/unarchive`; `desired_outcome`; the pre-feature marker with its startup step (contracts/http.md §1 – §5).
- **PR-03**: lossless archive (FR-024, SC-006).
- **Rules (FR-025)**: archived projects take no new tasks, and tasks already in them keep membership on edit.

**Kit**: archive keeps membership; `unarchiveProject` and `setProjectOutcome`; pull with `?state=all`, so archived projects without tasks ("Tax return 2024") reach the Archived sections (contracts/kit-commands.md §1 – §4).

**Mac X-06**:

- "Archived projects · N" is collapsible, collapsed by default and remembered; the disclosure is a tab stop with its state in its accessible name.
- Right-click offers "Archive project" (no confirmation) or "Unarchive project"; File › "Archive project" / "Unarchive project" (`ProjectMenuCommands.swift`) gives both a keyboard path. Today's guard stays: archiving is disabled while a task edit is unsaved or the capture draft is not empty.
- Archiving the open project keeps it selected, re-renders it as the archived view, expands the Archived section and focuses the title ("archived (just now)").
- The archived project view has the "Archived" chip and "Unarchive"; the outcome is read-only; there is no "Add a task"; focus goes to the title after unarchive.
- An unarchive refused because an active project has the same name shows "Another active project is already called “Old flat”. Rename one first." with "Rename…" and no Retry.
- "<name> · archived" labels and picker entries.
- Smart Add's block reads "Unarchive “Old flat” before adding a task to it."
- Every "Restore" string becomes "Unarchive".
- The FR-027 line (decision 2, option B) shows for a marked, empty project. The rule, "accepts no new task" and the label come from the kit's `GTDQueries.projectDisplay`, Linux-tested, so the Mac and iPhone render one rule.
- Evidence: `manual-macos-archive.md` (contracts/mac-app-host.md §4).

**iPhone M-02**:

- The archive confirmation is no longer destructive and has the new copy.
- Archived projects can be opened and their tasks edited.
- Unarchive is available by swipe, by a VoiceOver custom action and from the toolbar.
- The toast reads "Unarchived “Old flat”".
- A name clash refuses the unarchive at once with "Rename…" (M-02 "unarchive refused: name in use").
- The archived project screen renders the kit's `projectDisplay`.
- `SyncIssueDescriber` has the unarchive case.

**Web D-01**:

- The "Archived projects" disclosure under Projects (`AppShell.tsx`) is hidden when there are none.
- The archived project page has the chip, a secondary "Unarchive" button, no composer and the info line. While the request runs it shows "Unarchiving…", and errors use the existing notice with Ref and Retry. A 409 name clash shows "Another active project is already called “Old flat”. Rename one first." with Ref and "Rename…", and no Retry. When offline the button is disabled.
- Archiving the open project turns the page into the archived page, focuses the heading and shows the toast "Archived “Old flat”".
- The archive popover gets the hint line.
- Archived names resolve to "Old flat · archived" in groupings and in the detail panel.
- The empty pre-feature project shows the FR-027 line (`ArchivedProjectNotice.tsx`).
- At 390 px the Unarchive button is full width and 44 px tall.

**Desired outcome (FR-028)**: synced, kept by other clients' edits, exported and purged; shown only on the Mac.

## Failure handling and concurrency

| situation | behaviour | where |
|---|---|---|
| Edit of a task in a project archived on another device | accepted; membership kept (server tolerant PATCH, kit carried-membership rule) | http §5, kit §3 |
| Offline capture into a project archived elsewhere | resent without the project under a new key; sync issue "…was archived on another device, so the task was added without a project." | kit §5 (existing engine path) |
| Unarchive clashing with an active name | locally: refused at once, with "Rename…" (X-06, M-02); on the server (clash made while offline): 409 → the engine reverts the project to archived **at once** and rewrites captures queued into it to no project, under one sync issue that counts them | http §3, kit §4 |
| Archived Mac project meets an active account project of the same name at first sign-in | merged with membership kept; the archive is not applied to the account's project and becomes a sync issue | kit §3 |
| Archived Mac project meets only an archived account project | stays a separate archived project (documented limit) | kit §3, spec edge case |
| Repeat archive of an archived project | only revision and `updated_at` change; `archived_at` and the FR-027 marker are kept | http §4 |
| Unarchive retried after a lost reply | same `Idempotency-Key` → stored response; after 24 h → already active → 200 unchanged | http §3 |
| Two devices archive or unarchive the same project offline | the second gets a stale-revision 409 → refetch → replay drops it if the goal already holds | kit (existing) |
| Merged project with outcomes on both sides | the account's wins; the local one becomes a sync issue that shows it in full with "Copy outcome", never silently dropped | kit §3 |
| Server failing (5xx, 429, timeout while online) | backoff 2 → 300 s with one attempt at exactly 60 s; indicator only until that attempt fails; then "Couldn't sync · Retry" with Ref and "Last tried"; clears on success; `failingSince` survives relaunch | sync-status §3, kit §4 |
| Server failing, then the device goes offline | "Offline …" while offline (Retry could not act); `failingSince` kept, so back online one failed attempt shows "Couldn't sync" at once | sync-status §3 |
| Session ended or revoked (401) | "Sign in again to sync" at once; work continues; the outbox is kept; the token is removed | kit, sync-status §3 |
| Offline for days | "Offline · N changes waiting"; no repeated alerts; X-02 shows the oldest age | sync-status §3 |
| Sign in as another account with pending work | refused, nothing sent (FR-004) | kit `AccountSwitchRefused` |
| Sign-out with unsent changes or open issues | X-04 warning with the count, and a sentence naming open issues; "Sign out and remove" discards; Cancel keeps | mac-app-host §7 |
| Sign-out when the local removal fails | "Couldn't sign out"; the session was not ended yet, so the person is still signed in | kit §4 "Sign-out order" |
| Second Mac process | brings the first forward, or shows X-08 "Brain Buddy is already open." / "Switch to the open window to keep working." with "OK"; exits; the store is untouched | research R6, design X-08 |
| Old pre-021 Mac copy running during the upgrade | the import holds its `lockf`; after the rename its writes fail with its existing 409 | mac-legacy-import §6 |
| Old pre-021 Mac copy launched after the upgrade, a restored folder, a deleted `mac-local.json` | the `local-gtd.json` it brings is kept untouched and never imported; X-05 "later file" once; X-02 quiet line | data-model E7.1, FR-033 |
| Crash during the import | the next launch resumes from the recorded state; `store.json` never holds an unverified import; the legacy bytes are untouched until the rename | data-model E7.1 |
| Legacy store unreadable, newer or partly bad | never touched; X-05 once; empty workspace after Continue | mac-legacy-import §5 |
| Import verification fails | X-05 "couldn't carry over"; the file is kept for a later build | mac-legacy-import §5 |
| Wrong Mac clock | relative time clamps to "just now"; ordering uses the server and outbox order, not the Mac clock | sync-status §3 |
| Keychain write fails at sign-in | X-03 "couldn't save sign-in" with Ref; the server session just opened is ended; nothing linked | kit §4, data-model E9 |
| Keychain item unreadable (rebuilt ad-hoc binary refused access) | treated as no token → "Sign in again to sync"; logged as `keychain_read_failed`; the outbox is kept | research R17 |
| A sign-in that hangs | Cancel and Esc stay enabled; a reply after cancel has its session ended; "Brain Buddy didn't answer. Try again." on timeout | mac-app-host §7 |
| Very large account | the first pull fills progressively and the window stays usable; the full pull is paged by 200 | kit (existing) |
| Old iPhone build archives | its local clearing is undone by the next pull; nothing is dropped | http §7 |

## Migration, deploy order and rollback

**Server data**: no DDL. The three project fields are optional payload keys. `_mark_detached_archives()` runs at each start and marks only archives without `archived_at`, without a revision bump. It is idempotent and safe alongside old code.

**Deploy order**:

```text
PR-01 (CI lane; any time; ASK)
PR-02 backend tolerant contract (ASK)  →  PR-03 lossless archive (SHOW)
   →  PR-06 web (SHOW)  ‖  PR-04 kit contract (SHOW) → PR-05 kit status and session (ASK)
         → (PR-07 iPhone (SHOW) ‖ PR-08 Mac adoption (ASK) → PR-09 Mac sync UI (ASK))
   →  PR-10 release gates (ASK)
```

- **Landing mechanics** (ADR-0008; review c1, F01): SHIP and SHOW slices land through verified trunk. ASK slices (PR-01, PR-02, PR-05, PR-08, PR-09, PR-10) never land automatically: `scripts/submit_to_trunk.sh` refuses a mechanically ASK diff in preflight and the release workflow's `land` job re-checks it. Each goes as a PR carrying the evidence, the owner's recorded approval, green required CI on the exact SHA, and the audited temporary ruleset intervention.
- **PR-05 is ASK** (mechanical: `SyncEngineSessionTests.swift` and `SessionTokenStore.swift` carry the `session` token; semantic: session end, account-switch refusal, sign-out order and the macOS token store). So PR-07 and PR-08 wait for PR-05's approved landing, not for an automatic one. Its development can start in parallel with PR-04: the pure status files (`SyncPresentation`, `SyncActivityIndicator` and their tests) touch nothing PR-04 writes; `Workspace.swift` is owned by PR-04's tasks first, and PR-05 lands after PR-04.
- **TestFlight**: kit and iPhone slices land only after PR-03 is deployed, because `ios.yml` uploads every `ios/` change on `main` to TestFlight. Each of PR-04, PR-05 and PR-07 therefore produces one TestFlight build when it lands; PR-05's comes from its ASK landing, which runs the same push CI on `main`. PR-02 and PR-03 now write nothing under `ios/` (the trace copy moved to PR-04), so they produce no build.
- The Mac is built locally, so its slices reach the owner when they rebuild.

**Rollback**:

- **Image rollback (one release back) is safe at every step** (contracts/http.md §8). PR-03 → PR-02 restores clearing for future archives only. PR-02 → previous image is safe because no retained memberships exist yet.
- **Rolling back below PR-02 after PR-03 has run** makes tasks in projects archived meanwhile reject edits until roll-forward. The runbook note in `docs/api-compatibility.md` says to roll forward.
- **Older code re-saving a project** drops `desired_outcome` and `archived_at` (stated limit, http.md §8).
- **Client rollback**: a 021 kit document holds new command cases that an older build cannot decode, so an older build reports the store unreadable rather than overwriting it. Downgrade is not a supported path (contracts/kit-commands.md §6).

**Mac data**: the import is reversible for 30 days or longer, because the backup is the untouched original (E8). An unreadable store, and a previous-version file that appears later, are never touched (FR-022, FR-033).

**Irreversible**: nothing on the server. On the Mac, sign-out with "Sign out and remove" discards unsent changes after an explicit warning (FR-018). The backup's deletion after 30 days and a sign-out is irreversible by design (FR-021).

## Observability

- **Server**:
  - `api_request` and `api_request_failed` gain `client` and `client_version` (contracts/http.md §6), so Mac failures can be filtered (FR-031).
  - No project or task route logs content. A pytest log-capture test seeds sentinel names and outcomes and asserts their absence (FR-030).
- **Correlation**:
  - The kit mints a lower-cased UUID `X-Correlation-ID` per request. The server echoes it, or the server's own id, as `reference_id`. The server accepts an incoming id only when it matches `^[0-9A-Za-z._-]{1,64}$`, so a client cannot inject text into log lines (http.md §6).
  - `SyncMetadata.lastFailureReferenceID` keeps it for the X-01 tooltip and X-02, and `SyncIssue.referenceID` keeps it per issue. A timeout keeps the id the client sent (FR-015).
- **Mac**: an `os.Logger` with subsystem `com.brainbuddy.mac` and categories `import`, `sync` and `instance`. It logs counts, durations, trigger names, error classes and reference ids, never content, paths, file names or digests (research R21). Tests cover the import and sync categories.
- **iPhone and kit**: neither logs today (no `Logger`, `os_log` or `print` outside the fake server, re-checked 2026-10-06), and 021 adds none.
- **Supporting signals** (intake KPI table):
  - SC-001 is measured by the kit convergence test at the worst tick phase, the web polling tests and the Playwright fake-clock check, then the owner week.
  - Failures shown to the person are the attention states with Ref; SC-004 is the `MacPresentationRouterTests` sweep plus the host checklist.
  - There is no new server metric, so no new alert is required (AGENTS.md "Monitoring requirements").

## Test strategy

**Ids and taxonomy**:

- Each slice starts with failing tests carrying `021-FR-…` or `021-SC-…` ids: `test_021_FR_024_…` in Python, `@Test("021-FR-012 …")` in Swift, and the id in the Vitest or Playwright title.
- **Allure**: new rules in `backend/tests/allure_taxonomy.py` for the three new test modules (epic Tasks, feature "Projects", stories "Lossless archive", "Desired outcome", "Client attribution"). Web tests live in existing folders whose rules apply. The Playwright spec gets a path rule in `frontend/tests/allure.fixtures.ts` if the existing default does not cover it.
- **Coverage floors**: `backend/coverage-floor.json` and `frontend/coverage-floor.json` may only rise, and there are no coverage suppressions in `frontend/src`.

| layer | what | key cases |
|---|---|---|
| pytest — archive | `test_project_archive_lossless_api.py` | all-state membership kept after PR-03, cleared plus marker under PR-02 (test parametrised by slice behaviour, the PR-02 cases replaced in PR-03); no task revision bump; tolerant PATCH (omit, same, different archived → 400, null, active); create and Smart Add into archived → 400; `?state=` active / archived / all / 422, and the default returning the same project set and order as today with the three new fields on each object; repeat archive changes only revision and `updated_at` (marker and `archived_at` kept; `test_021_FR_027_repeat_archive_keeps_marker`, PR-03); unarchive 200 / active no-op / 409 stale / 409 name / 404 foreign (`second_api_client`) / idempotent replay / missing key 400; startup step marks only `archived_at`-less archives, without a bump, idempotently; marker survives unarchive and is cleared by lossless archive; `open_task_count` for archived |
| pytest — outcome | `test_project_desired_outcome_api.py` | create, patch omit / null / blank / 1000 / 1001; a rename keeps it; export contains the three fields; purge removes them; log capture: no sentinel name or outcome in any line |
| pytest — attribution | `test_client_attribution_logging.py` | ios / macos / absent / malformed (newline) → fields; the raw value never logged; responses identical; `X-Correlation-ID` with a newline → a fresh UUID in the response and no raw value in any log line, a lower-cased UUID echoed unchanged (`021-FR-015`, `021-FR-030`) |
| pytest — traces | `test_project_archive_traces.py` | every trace in `fixtures/project_archive_traces.json` passes against the real API (archive, repeat archive, unarchive 200 / no-op / 409 / 404, `?state=`, tolerant PATCH, outcome omit / null / blank); from PR-04, the kit copy is byte-identical to the fixture |
| pytest — existing | `test_task_api.py`, `test_task_lifecycle_detail_api.py`, `test_task_tag_project_mvp_api.py`, `test_task_branch_coverage.py`, `test_api_contract.py`, `test_account_export.py`, `test_account_deletion.py` | clearing assertions flipped (PR-03); unarchive in the contract map, and `GET /projects` → `{"401", "422"}` (PR-02); Schemathesis stays green |
| Swift Testing (Linux) — Core | `ReducerArchiveTests`, `ReducerOrganizeTests`, `ReplayTests`, `SmartAddParserTests`, `SyncPresentationTests`, `SyncActivityIndicatorTests`, `SyncIssueDescriberTests`, `TaskEditDraftTests`, `RecordContentStampTests`, `ProjectDisplayTests` | ADR-0020 reducer table (kit §3) incl. repeat archive; outcome limits; the merge table (an archived local project keeps its membership in the active survivor, `.archiveNotMerged` issue; archived meets archived stays separate); Mac parser cases ported; every sync-status §5 case incl. the verbatim catalogue, tooltips, age formatter and the failing + offline pair; issue copy for unarchive (with the rewritten-capture count), the kept outcome in full, the archive not applied, archived-elsewhere, and a non-empty reference id on every issue; changed-fields-only diff and `EntityID` anchors (`021-FR-009`); content stamps unchanged by server times and re-keying (`021-FR-023`); the FR-027 display rule and "accepts no new task" (`021-FR-025`, `021-FR-027`) |
| Swift Testing — Persistence, API | `StoreDocumentCodingTests`, `EndpointRequestTests`, `WireDecodingTests`, `ClientIdentityTests` | a v1 document from before 021 decodes; new fields round-trip; `X-Client: brainbuddy-macos/x`; unarchive and `?state=all` requests; a timeout `APIError` carries the sent correlation id |
| Swift Testing — Sync | `ProjectArchiveSyncTests`, `SyncEngineFailingClockTests`, `SyncEnginePullTests`, `SyncEngineSchedulingTests`, `SyncEngineSessionTests`, `ProjectArchiveTraceReplayTests`, `PeriodicSyncTickerTests` | pull with `?state=all` includes taskless archived projects, with a fallback per id against an old server; unarchive 409 → immediate local revert and one issue for a capture queued behind it; `failingSince` and `lastFailedAttemptAt` set and cleared, persisted, kept offline, not started by offline; with the real `retryDelay` (jitter at both extremes) an outage ending at 59 s shows nothing and one ending at 61 s shows "Couldn't sync" after the 60 s attempt (`021-FR-014`, `021-SC-005`); `.periodic` honours the 30 s age, never sets `pullRequested`, runs no cycle and emits no status for 29 s of idle ticks, and does nothing while a retry is scheduled, while `.manual` runs at once (`021-FR-006`); the ticker fires every 15 s while active and stops while inactive (`021-FR-006`, `021-FR-032`); foreground forces a pull; refusal copy has the device noun; traces replay against the fake server |
| Swift Testing — Workspace | `MacIPhoneConvergenceTests`, `FirstSignInMergeTests`, `WorkspaceCommandTests`, `WorkspaceSyncTests` | quickstart Scenario 4 steps 1 – 9: SC-001 at logic level for every FR-007 record type in both directions, at the worst tick phase with a 1.5 s pull, every case ≤ 60 s (`021-SC-001`, `021-FR-032`); SC-002 offline matrix, 0 lost and 0 applied twice; SC-003 merge incl. both outcomes, archived meets active, archived meets archived (duplicates counted on active names); SC-006; first-upload age from the account link (`021-FR-012`); review-mark stamps unchanged by upload and by sign-out and sign-in (`021-FR-023`); a local edit of field A while a pull changes A and B sends only A (`021-FR-009`); sign-out order: a failing removal keeps the token and sends no logout (`021-FR-018`, `021-FR-005`); `apply([…])` all-or-nothing |
| Swift Testing (macOS lane) — Mac | `LegacyStoreImporterTests`, `MacLocalStateTests`, `SingleInstanceGuardTests`, `LegacyCookieCleanupTests`, `SyncTriggerSourceTests`, `OfflineWorkspaceTests`, `MacSyncFlowTests`, `MacPresentationRouterTests`, `MacKeychainTests`, `MacPrivacyGuardTests` | mac-legacy-import §6, including the import state machine and the FR-033 cases (legacy file after a fresh install, `mac-local.json` removed, a new file after the rename, an `inProgress` record with a foreign `store.json`), each asserting unchanged `store.json` bytes; no compaction (`waitingSince ≠ createdAt` exact); cross-project list order; sentinel-home log privacy; sidecar rekeying, survival across sign-out, launch-time 30-day pruning and 7-day validity; lock held or released or stale after a crash; the legacy cookie removed and its logout queued; trigger table (mac-app-host §5) with a fake clock and a fake path monitor; offline journeys ported from the deleted XCTest suite (capture, quick capture, Waiting, Someday and Project reviews, clarify as project, archived browse, archive by File menu, unarchive and its name-clash refusal); mac-app-host §8: zero requests account-less (`021-FR-029`), sync log privacy (`021-FR-030`), the status sweep with no presentation or focus (`021-SC-004`, `021-FR-017`), the login-keychain round trip, not synchronizable (`021-FR-005`), voice sources without network APIs; sign-in, sign-out and switch-refusal flows against a stub `HTTPTransport` |
| Vitest | `client.test.ts`, `clientParity.test.ts`, `taskHooks.test.ts`, `AppShell.test.tsx`, `TaskListPage.test.tsx`, `ArchivedProjectNotice.test.tsx`, `TaskDetailAutosaveUI.contract.test.tsx` | every D-01 state (disclosure count and hidden, archived page, unarchiving, unarchived focus and toast, archived just now with focus and toast, error with Ref and Retry, refused with "Rename…" and no Retry, offline disabled, pre-feature empty line, filtered empty, "· archived" labels, archive hint); `refetchInterval: 45_000` and `refetchIntervalInBackground: false` on the task list, projects, tags and task detail queries (`021-FR-032`, `021-SC-001`); a detail refetch while typing keeps the typed text and takes the untouched field's new value |
| Playwright | `frontend/tests/e2e/archived-projects.spec.ts`, `frontend/tests/e2e/cross-client-refresh.spec.ts` | quickstart Scenario 7: archive keeps tasks, unarchive from the page, no overflow at 390 × 851, 44 px button, axe scan; with a fake clock, a subtask, a comment and a tag rename made through the API while the page is open appear within 45 s of fake time, scroll and selection unchanged (`021-SC-001`, `021-FR-032`) |
| macOS host (manual) | `specs/021-mac-sync/evidence/manual-macos-status.md`, `manual-macos-upgrade.md`, `manual-macos-archive.md` | SC-004 state sweep on screen (no dialog, no focus change), VoiceOver for X-01, X-02, X-03, X-04, X-05, keyboard order incl. X-02 Dismiss and X-03 focus return, X-03 Cancel while signing in, scroll and focus during an incoming change, Reduce Motion, large sidebar text, the Keychain item present and no token in files, the Keychain prompt after a rebuild, sleep and wake reconnect, real upgrade from a pre-021 build and the "later file" path; every X-06 state, the remembered disclosure, the strings, focus after archive and unarchive |
| iPhone host (manual) | `specs/021-mac-sync/evidence/manual-ios-status.md`, `manual-ios-archive.md` | M-01 and M-02 states at Dynamic Type AX5, VoiceOver custom action Unarchive, 44 pt rows; a web change appears on the open iPhone within 60 s with no touch and nothing is fetched in the background (`021-FR-032`); long-press "Copy reference ID"; Settings "Sync now" enabled while syncing; sign-out with open issues |

**Requirement coverage**:

- Every FR-001 … FR-033 and SC-001 … SC-006 is named by at least one test. FR-032 is named by `PeriodicSyncTickerTests`, the convergence test, `taskHooks.test.ts` and the Playwright check; FR-033 by `LegacyStoreImporterTests`.
- **SC-007** is post-release acceptance (quickstart Scenario 9). It is reported as **manual-pending**, not covered, until `evidence/owner-week.md` holds seven dated entries; the template never counts.
- **Gates in PR-10**: `make check-specs` runs `scripts/check_requirement_coverage.py specs/021-mac-sync --requirements <every id except SC-007>` and the new `scripts/check_manual_evidence.py`. The latter fails on a manual evidence file without its header (commit SHA, build, OS, date), with an empty per-state checklist, or whose SHA is not an ancestor of the release commit (`git merge-base --is-ancestor`), instead of the `test -f` first planned; it prints SC-007's pending status.
- **Before 020 PR-01 lands** (review c1, F48): the coverage script on this branch scans no Swift and has no `--requirements` flag. Each Swift slice (PR-04, PR-05, PR-07, PR-08, PR-09) then records its requirement → test-name list (`grep -rn "021-\(FR\|SC\)-"` over its test files) and its `swift test` output in its PR body or landing record.

## Delivery slices

These are the proposed PR-sized slices. `/speckit-tasks` turns this table into the `## PR-срезы` manifest with file-level paths: no globs and no bare "tests", with each slice's own test files named.

Classes follow ADR-0008 and `scripts/classify_path_risk.py` ("mech." = the classifier result; the final class is the stricter of mechanical and semantic). ASK means a PR plus the owner's recorded approval (see [Migration, deploy order and rollback](#migration-deploy-order-and-rollback)).

**Mechanical classification, re-run for review c1** (blocking F01): every slice's full path list below was fed as `printf '%s\0' <paths> | python3 scripts/classify_path_risk.py --null` on 2026-10-06 at `0b9fffe`.

| slice | paths | mech. | ASK paths (classifier reason) | final class |
|---|---|---|---|---|
| PR-01 | 5 | ASK | all five (`.github/`, `scripts/`) | ASK |
| PR-02 | 19 | ASK | `backend/app/api/tasks.py`, `backend/app/api/middleware.py` (explicit API paths) | ASK |
| PR-03 | 6 | SHIP | — | SHOW (semantic) |
| PR-04 | 44 | SHIP | — | SHOW (semantic) |
| PR-05 | 19 | **ASK** | `ios/BrainBuddyKit/Tests/BrainBuddySyncTests/SyncEngineSessionTests.swift`, `ios/BrainBuddyKit/Sources/BrainBuddyAPI/SessionTokenStore.swift` (token `session`) | **ASK** (was SHOW; corrected) |
| PR-06 | 17 | SHIP | — | SHOW (semantic) |
| PR-07 | 12 | SHIP | — | SHOW (semantic) |
| PR-08 | 34 | SHIP | — | ASK (semantic) |
| PR-09 | 20 | SHIP | — | ASK (semantic) |
| PR-10 | 8 | ASK | `Makefile`, `scripts/check_manual_evidence.py`, `scripts/test_check_manual_evidence.py` | ASK |

PR-05 was declared "SHOW (mech. SHIP)" in the first plan although its existing test file `SyncEngineSessionTests.swift` already classified ASK (the classifier camel-splits it into `sync`, `engine`, `session`, `tests`); `SyncEngine+Session.swift` tokenizes as `engine+session` and stays SHIP. It is now ASK, and the deploy order and lanes below follow. `/speckit-tasks` must re-run the classifier over the manifest's final paths, and a manifest path that changes a slice's mechanical class changes the slice's class.

| id | outcome | depends on | main paths | class |
|---|---|---|---|---|
| PR-01 | `macos-app` CI lane with the `macos` change output (also true for `ios/BrainBuddyKit/`); validator registration (lane limits, path-filter list, `full-ci` / `allure-report` needs) with tests; `SCREEN_ID_RE` widened to `X-` with a test (G-7) | — | `.github/workflows/ci.yml`, `scripts/validate_ci_artifacts.py`, `scripts/test_validate_ci_artifacts.py`, `scripts/render_feature_report.py`, `scripts/test_render_feature_report.py` | **ASK** (mech.: `.github/`, `scripts/`) |
| PR-02 | Backend tolerant contract: PATCH accepts carried archived membership; `GET /projects?state=`; `POST /projects/{id}/unarchive`; `desired_outcome`; `archived_at` + `archived_before_lossless` with the startup step; archive still clears and sets the marker; `X-Client` log fields; incoming correlation id validated; `GET /projects` 422 in the route and the contract map; repeat archive keeps the marker; API contract map; parity inventory; golden traces (PR-02 behaviour), backend only; Allure rules; `docs/api-compatibility.md` client note; data-retention wording for the outcome | 020 PR-02 landed (external) | `backend/app/api/tasks.py`, `backend/app/api/middleware.py`, `backend/app/schemas/tasks.py`, `backend/app/modules/tasks/{domain.py,repository.py,service.py}`, `backend/tests/test_project_archive_lossless_api.py`, `backend/tests/test_project_desired_outcome_api.py`, `backend/tests/test_client_attribution_logging.py`, `backend/tests/test_project_archive_traces.py`, `backend/tests/fixtures/project_archive_traces.json`, `backend/tests/{test_task_branch_coverage.py,test_api_contract.py,test_account_export.py,test_account_deletion.py,allure_taxonomy.py}`, `contracts/api-client-parity.json`, `docs/api-compatibility.md`, `docs/data-retention.md` | **ASK** (mech.: `api/tasks.py`, `api/middleware.py`) |
| PR-03 | Lossless archive (ADR-0020): memberships kept, `archived_at`, marker cleared; repeat archive pytest; clearing tests flipped; traces updated to lossless (backend only) | PR-02 | `backend/app/modules/tasks/service.py`, `backend/tests/{test_task_api.py,test_task_lifecycle_detail_api.py,test_task_tag_project_mvp_api.py,test_project_archive_lossless_api.py}`, `backend/tests/fixtures/project_archive_traces.json` | **SHOW** (mech. SHIP; cross-client behaviour change) |
| PR-04 | Kit contract: records E3; commands; ADR-0020 reducer rules incl. repeat archive; the merge table (archived local project keeps its membership in an active survivor; `.archiveNotMerged`); outcome merge rule with the full outcome in the issue; Smart Add copy; `SyncIssueDescriber`; `ClientIdentity`; `listProjects(state:)` pull with fallback; unarchive push with the immediate revert on 409; `Workspace.unarchiveProject` / `setProjectOutcome` / `apply([…])`; pure helpers `TaskEditDraft`, `SelectionAnchor`, `RecordContentStamp`, `projectDisplay`; fake server mirroring http.md; the kit trace copy, its `resources:` declaration and the byte-equality pytest; trace replay; Mac parser cases ported | PR-03 | `ios/BrainBuddyKit/Package.swift`, `ios/BrainBuddyKit/Sources/BrainBuddyCore/{Records,Commands,Reducer+Organize,Reducer+Validation,Reducer+Replay,Replay,SmartAdd+Resolution,SyncIssueDescriber,TaskEditDraft,RecordContentStamp,Queries+ProjectDisplay}.swift`, `…/BrainBuddyAPI/{BrainBuddyAPI,BrainBuddyAPIClient,APIError,WireModels,RequestBodies}.swift`, `…/BrainBuddySync/{GTDCommand+Sync,PushPlanner,SyncEngine+Pull,SyncEngine+Push,StoreDocument+Merge}.swift`, `…/BrainBuddyWorkspace/Workspace.swift`, `…/BrainBuddyFakeServer/{FakeServer+Organize,ServerState}.swift`, `…/Tests/BrainBuddyCoreTests/{ReducerOrganizeTests,ReducerArchiveTests,ReplayTests,SmartAddParserTests,SyncIssueDescriberTests,TaskEditDraftTests,RecordContentStampTests,ProjectDisplayTests}.swift`, `…/Tests/BrainBuddyPersistenceTests/StoreDocumentCodingTests.swift`, `…/Tests/BrainBuddyAPITests/{EndpointRequestTests,WireDecodingTests,ClientIdentityTests}.swift`, `…/Tests/BrainBuddySyncTests/{ProjectArchiveSyncTests,SyncEnginePullTests,ProjectArchiveTraceReplayTests}.swift`, `…/Tests/BrainBuddySyncTests/Resources/project_archive_traces.json`, `…/Tests/BrainBuddyWorkspaceTests/{WorkspaceCommandTests,FirstSignInMergeTests}.swift`, `backend/tests/test_project_archive_traces.py` | **SHOW** (mech. SHIP; ships to TestFlight; changes iPhone archive behaviour) |
| PR-05 | Kit status, cadence and session: `SyncPresentation` (snapshot, describer, timing, copy catalogue incl. sign-out issue and backup sentences), `SyncActivityIndicator`, `failingSince`, `lastFailedAttemptAt`, `accountLinkedAt` and reference id in `SyncMetadata`, the 60 s confirmation attempt, `.periodic` (no-op when idle) and `PeriodicSyncTicker`, forced pull on foreground, single-flight `syncNow`, device-neutral refusal, sign-out order, macOS token-store attributes, `Workspace.syncSnapshot`; convergence and offline matrix (SC-001, SC-002) | PR-04 | `…/BrainBuddyCore/{SyncPresentation,SyncActivityIndicator,Outbox}.swift`, `…/BrainBuddySync/{BrainBuddySync,SyncConfiguration,SyncEngine,SyncEngine+Cycle,SyncEngine+Session,PeriodicSyncTicker}.swift`, `…/BrainBuddyAPI/SessionTokenStore.swift`, `…/BrainBuddyWorkspace/Workspace.swift`, `…/Tests/BrainBuddyCoreTests/{SyncPresentationTests,SyncActivityIndicatorTests}.swift`, `…/Tests/BrainBuddySyncTests/{SyncEngineFailingClockTests,SyncEngineSchedulingTests,SyncEngineSessionTests,PeriodicSyncTickerTests}.swift`, `…/Tests/BrainBuddyWorkspaceTests/{MacIPhoneConvergenceTests,WorkspaceSyncTests}.swift` | **ASK** (mech.: `SyncEngineSessionTests.swift`, `SessionTokenStore.swift`; semantic: session end, account switch, sign-out order, token store) |
| PR-06 | Web D-01: archived disclosure, archived project page, Unarchive with every state incl. the name-clash refusal, archive hint, archived-just-now, "· archived" names, FR-027 line, 45 s visible refetch on the list, projects, tags and open task detail, type drift fix, Playwright (archive and cross-client refresh) and axe | PR-03 | `frontend/src/api/{client.ts,taskTypes.ts,taskHooks.ts}`, `frontend/src/api/__tests__/{client.test.ts,clientParity.test.ts,taskHooks.test.ts}`, `frontend/src/components/shell/AppShell.tsx`, `frontend/src/components/shell/__tests__/AppShell.test.tsx`, `frontend/src/features/tasks/{TaskListPage.tsx,TaskDetailPanel.tsx,ArchivedProjectNotice.tsx}`, `frontend/src/features/tasks/__tests__/{TaskListPage.test.tsx,ArchivedProjectNotice.test.tsx,TaskDetailAutosaveUI.contract.test.tsx}`, `frontend/tests/e2e/{archived-projects.spec.ts,cross-client-refresh.spec.ts}`, `frontend/tests/allure.fixtures.ts` | **SHOW** (mech. SHIP) |
| PR-07 | iPhone M-01 and M-02: status row via the describer (lists, Lists hub, Settings › Sync), attention rows as buttons, long-press "Copy reference ID", Settings "Sync now" enabled during a sync, `PeriodicSyncTicker` toggled by the scene phase, Sync issues via `SyncIssueDescriber`, sign-out confirmation naming open issues, archive copy, archived project screen via `projectDisplay`, the name-clash refusal, Unarchive swipe / toolbar / VoiceOver action; `ios/AGENTS.md` copy; `docs/native-ios-app.md` (archive, backend asks 5 and 7 done, `X-Client` macOS); manual evidence | PR-05 | `ios/BrainBuddy/App/BrainBuddyApp.swift`, `ios/BrainBuddy/Components/SyncStatusLabel.swift`, `ios/BrainBuddy/Screens/Lists/TaskListScreen.swift`, `ios/BrainBuddy/Screens/Browse/{ListsHubScreen,ProjectsScreen}.swift`, `ios/BrainBuddy/Screens/Settings/{SettingsScreen,SyncIssuesScreen,SignInSheet}.swift`, `ios/AGENTS.md`, `docs/native-ios-app.md`, `specs/021-mac-sync/evidence/{manual-ios-status.md,manual-ios-archive.md}` | **SHOW** (mech. SHIP) |
| PR-08 | Mac adoption, account-less: tools 6.2 / Swift 6, kit dependency, `WorkspaceHost`, `SingleInstanceGuard`, legacy import with verification, backup and X-05, `MacLocalState` review marks, model replaced by `Workspace`, X-06, removals, account-less X-01 line, Mac tests in Swift Testing, data-retention rows (Mac store, backup, sidecar), upgrade evidence | PR-01, PR-05; 020 PR-06 landed (external) | `macos/Package.swift`, `macos/Package.resolved`, `macos/Sources/BrainBuddyMac/{BrainBuddyMacApp,ContentView,ProjectReviewView,QuickCaptureView,QuickOpenView,VoiceCapture,WorkspaceHost,SingleInstanceGuard,MacLocalState,LegacySnapshot,LegacyStoreImporter,UpgradeNotice,LocalGTDStore,APIClient,SmartAddParser}.swift`, `macos/Tests/BrainBuddyMacTests/{OfflineWorkspaceTests,LegacyStoreImporterTests,MacLocalStateTests,SingleInstanceGuardTests,APIClientTests,LocalGTDStoreTests,SmartAddParserTests}.swift`, `macos/Tests/BrainBuddyMacTests/Resources/{legacy-populated,legacy-corrupt,legacy-newer}.json`, `macos/README.md`, `docs/data-retention.md`, `specs/021-mac-sync/evidence/manual-macos-upgrade.md` | **ASK** (semantic: one-time migration of real user data; mech. SHIP) |
| PR-09 | Mac sync: X-03 sign-in sheet, X-04 sign-out, X-01 every state, X-02 popover, X-07 menus and ⌘R, `SyncTriggerSource` (activation, path monitor, 15 s tick, flush), Keychain service, macOS client identity; `docs/native-macos-app.md`; AGENTS.md line; data-retention Keychain row; status evidence | PR-08 | `macos/Sources/BrainBuddyMac/{BrainBuddyMacApp,ContentView,WorkspaceHost,SyncTriggerSource,SyncStatusLine,SyncStatusPopover,SignInSheet,SignOutConfirmation,SyncMenuCommands}.swift`, `macos/Tests/BrainBuddyMacTests/{SyncTriggerSourceTests,MacSyncFlowTests}.swift`, `docs/native-macos-app.md`, `AGENTS.md`, `macos/README.md`, `docs/data-retention.md`, `specs/021-mac-sync/evidence/manual-macos-status.md` | **ASK** (semantic: session credential, first egress of Mac data; mech. SHIP) |
| PR-10 | Release gates: 021 requirement coverage and the evidence-file checks in `make check-specs` (gate integrity re-recorded); coverage floors raised; evidence README and owner-week template | PR-06, PR-07, PR-09; 020 PR-01 landed (external) | `Makefile`, `.specify/gate-integrity.json`, `backend/coverage-floor.json`, `frontend/coverage-floor.json`, `specs/021-mac-sync/evidence/{README.md,owner-week.md}` | **ASK** (mech.: `Makefile`) |

**Lanes inside 021**:

```text
PR-01 ─────────────────────────────────────────────┐
PR-02 → PR-03 → PR-06 (web)                         │
              → PR-04 → PR-05 → PR-07 (iPhone)      │
                              → PR-08 (Mac) ←───────┘ → PR-09 (Mac sync UI)
PR-06 + PR-07 + PR-09 → PR-10
```

Independent slices with no edge between them share no write path:

- PR-06 is frontend only.
- PR-07 owns `docs/native-ios-app.md` and `ios/AGENTS.md`.
- `docs/data-retention.md` is written by PR-02, PR-08 and PR-09, which form a dependency chain.
- The trace copy under `ios/BrainBuddyKit/Tests/…/Resources/` is written by PR-02 and PR-03 (a chain), and is read but not written by PR-04.

**Parallelism with 020's waves** (research R20; 020 lanes from `specs/020-weekly-review/tasks.md:511-524`):

| 021 slice | can run in parallel with | must be serialized with |
|---|---|---|
| PR-01 | every 020 slice | — |
| PR-02, PR-03 | 020 PR-01, PR-03 – PR-14 except PR-15 | 020 PR-02 (in flight; land first), 020 PR-15 (either order; the second rebases) |
| PR-04, PR-05 | 020 backend and web slices, PR-06 | 020 PR-03, PR-04, PR-08, PR-12 (shared kit files) |
| PR-06 | 020 backend, iOS and Mac slices | 020 PR-05, PR-10, PR-13 |
| PR-07 | 020 backend and web slices | 020 PR-04, PR-08, PR-12 |
| PR-08, PR-09 | every 020 slice except PR-06 | after 020 PR-06 (sidebar row; kept by PR-08) |
| PR-10 | — | 020 PR-14 (both edit `Makefile` `check-specs`) |

The 020 lane that 021 leans on most is iOS core (020 PR-03 → PR-04). Recommended order: let 020 PR-03 land first. It is approved and already sequenced, and it bumps `StoreDocument` to v2. 021's kit slices add only optional fields on top. 021 needs no version step either way.

## ASK-class surfaces (summary)

- **ASK paths**: `backend/app/api/tasks.py` and `backend/app/api/middleware.py` (explicit ASK paths).
- **`.github/workflows/ci.yml`** (`.github/`). It is protected by invariants only, and no invariant is touched.
- **`scripts/validate_ci_artifacts.py`, `scripts/render_feature_report.py` and their tests** (`scripts/`).
- **`Makefile`** (guarded). Re-record `.specify/gate-integrity.json` with `python3 scripts/check_gate_integrity.py --update` in the same commit. The `check-specs` invariant keeps the 019 line, and 021 is added beside it and beside 020's.
- **Semantic ASK**: PR-08 (one-time migration of real local data) and PR-09 (session credential; first egress of Mac data).
- **Review risk**: `plan.md` names ASK `.py` and `.yml` paths, so `scripts/spec_kit_planning_review.py` derives risk **high** for this feature, and the review run needs the recorded human sign-off (ADR-0012).

## Inconsistencies found while planning

These were found in spec.md, design.md and repository docs. Neither spec.md nor design.md was edited; the plan's handling is stated for each.

1. **Task deletion and manual reorder do not exist anywhere.**
   - FR-007 lists a task's "manual order" and "deletion"; FR-009 protects "dragging"; the edge case "Same task deleted on one device and edited on another" assumes task deletion.
   - In fact no client and no server route deletes a task or reorders one: there is no `DELETE /tasks`, the kit has no delete or reorder command, and the Mac has no drag (`ContentView.swift` has no `onMove`).
   - **Plan**: "manual order" is the create-time `order_key`, carried as is and preserved by the import. Task deletion is not applicable (cancel is the terminal action). The "deleted elsewhere" sync-issue copy is kept for the 404 path that a foreign or purged record can still produce. The spec should drop "deletion" and "dragging" for tasks, or a later feature adds them.
2. **SC-001 needs the iPhone and the web to poll; no FR says so.**
   - SC-001 measures Mac ↔ iPhone and Mac ↔ web in both directions within 60 s with both clients open, but FR-006 gives periodic fetching to the Mac only.
   - Today the iPhone pulls only on foreground and a 30-minute background refresh, and the web never polls.
   - **Plan**: a 15 s `.periodic` tick on the iPhone while active, and a 45 s visible-tab refetch on the web task list and projects (research R8). A one-line FR addition would make this explicit.
3. **The backup outlives sign-out.** FR-021 keeps the pre-upgrade backup "at least 30 days, or until the person signs out, whichever is later". US1-6 and FR-018 say signing out removes the account's data from the Mac. The backup holds pre-upgrade Mac data that was uploaded into the account at sign-in, so after sign-out a copy stays on disk for up to 30 days. **Plan**: implemented as written (E8) and listed in `docs/data-retention.md`.
4. **Design gap G-8, "already open".** The edge case "a second copy … refuses to start … and the person is told in plain words" has no design screen. **Plan**: bring the running copy forward; otherwise a system alert "Brain Buddy is already open." / "Close the other copy of Brain Buddy, then open it again." with "Quit" (research R6). The design owner should confirm the copy.
5. **iPhone "Sync now" parity.** design.md "Notes for the plan" says that FR-013 governs the Mac only and that the iPhone Settings "Sync now" may stay disabled during a sync. The FR-019 amendment (`b83d367`) makes the single-flight rule apply "on both platforms". **Plan**: follows FR-019 (PR-07). The design note is superseded and needs no screen change.
6. **`docs/api-compatibility.md` is stale.** It says "There is no mobile/iOS client contract yet" and asks for an API semantic version before a second client. The iPhone already exists, and the Mac is a third. **Plan**: PR-02 updates the doc. A versioned API stays out of scope, because every change is additive.
7. **ADR-0020 mentions "trashed Tasks".** No trash state exists in the backend or the kit. There is no impact.
8. **Brief versus code.**
   - The kit locks its store with `flock`, not `lockf` (`DocumentFile.swift:14-19`).
   - The kit has no periodic timer, no failing-since and no `desiredOutcome` or `archivedAt`.
   - `BrainBuddyFakeServer` is not a package product.

   The plan is built on the code.

## Design gaps (from design.md)

G-1 – G-3 were resolved by the spec amendment of 2026-10-06, and G-4 – G-6 at sign-off. Their realisation in this plan:

- **G-1** ("Not synced yet") and **G-2** (days and date): sync-status §3 rows 6 – 7 and the ladder.
- **G-3** (cancelled deletion): mac-app-host §7.
- **G-4** (ADR-0020 "state that limit" vs US5-4 "don't say lost"): resolved by sign-off decision 2, option B. The plan provides the marker (R12) and the display rule (http.md §2).
- **G-5** (flicker): resolved by decision 1. The thresholds live in `SyncTiming` (sync-status §1).
- **G-6** (plain sign-out confirmation): resolved by decision 3. The copy is `signOutNothingUnsent`.
- **G-7** (`SCREEN_ID_RE`): widened to `[DMX]-\d{2}` in PR-01.

## Open questions for the product owner

1. **Completion and creation dates after the first sign-in** (research R5, "Known limit").
   - The server sets `created_at`, `completed_at` and `waiting_since` itself, and accepts no client time. After the Mac's first sign-in, the History of tasks completed before the upgrade shows the sign-in day as their completion day. Order, due dates and everything else are kept.
   - The iPhone's account-less upload behaves the same today.
   - Keeping the original dates would need the server to accept client timestamps on create and transitions, which intake §4 lists as out of scope.
   - **Default if no answer**: accept the limit, and record it in `docs/native-macos-app.md`.

All other technical choices were made in research.md, as the owner asked.

## Risks

| risk | likelihood / impact | mitigation |
|---|---|---|
| PR-08 is large: it rebinds about 4,000 lines of SwiftUI from `BrainBuddyModel` to `Workspace` | high / medium | the views stay and only bindings change; `/speckit-tasks` may split PR-08 into "import and host" and "rebinding"; the macOS lane (PR-01) lands first so every step is compiled and tested in CI |
| Swift 6 diagnostics in `VoiceCapture.swift` / WhisperKit | medium / low | confine WhisperKit to one actor; a documented `@preconcurrency import` only if WhisperKit's declarations force it (R2) |
| Keychain access prompt after each ad-hoc rebuild | high / low | a separate Mac service; documented in `docs/native-macos-app.md`; "Always allow" persists until the next signature change (R17) |
| Collisions with 020 in shared kit and backend files | high / medium | the serialization table above; optional fields only, so no `StoreDocument` version race |
| Fake server drifting from the backend on archive semantics | medium / high | golden traces run against both (R19) |
| Full pull every 45 s per open client on a large account | low / low at today's scale | paged by 200; the `client` log field lets the cost be watched per client; a change feed stays a backend ask |
| Image rollback below PR-02 after PR-03 | low / high | two-step deploy; one-step automatic rollback is always safe; the runbook says to roll forward |
| Older code drops `desired_outcome` on re-save during a rollback | low / medium | stated limit (http.md §8); the outcome editor exists only on the Mac, so the window is short |
| macOS runner availability or minutes, or a slow WhisperKit fetch in CI | medium / low | the lane runs only when `macos/` or the kit changes; `Package.resolved` pins versions |
| A real legacy file has a shape the fixtures miss | low / high | verification fails closed (X-05, file untouched); the owner's real upgrade is a recorded host check before the backup can expire |

## Planning review

The `after_plan` hook (`/speckit-review`) is run by the owner and was not run by this stage.

## Constitution Check (post-design)

- **Spec workflow** — PASS. Inconsistencies 1 – 8 and gap G-8 are recorded above for a spec or design touch-up; one owner question has a stated default.
- **Consent & Safety** — PASS:
  - no egress before sign-in;
  - the credential only in the Keychain;
  - content-free logs with tests on both server and Mac;
  - the import is non-destructive and fails closed;
  - the server field is exported and purged;
  - the device files are listed in `docs/data-retention.md`.
- **Tests** — PASS: failing-first tests per slice, covering idempotency, retries, partial failure, crash recovery, offline replay, rollback-safe validation and every design state id.
- **Contracts** — PASS:
  - the five contract files, `data-model.md` and this plan agree: E1 ↔ http §2, E3 / E4 ↔ kit §1 – §3, E5 / E6 ↔ sync-status, E7 / E8 / E10 ↔ mac-legacy-import and mac-app-host;
  - the backend lands before its clients;
  - the compatibility story for older iPhone and web builds is in http §7.
- **Observability** — PASS: Ref on every surfaced failure, including timeouts; client attribution in the request log; Mac logs content-free.
- **Mobile/resilience** — PASS: offline-first Mac and iPhone, the durable outbox, single instance, a crash-safe import, and no blocking first load.
- **Delivery boundary** — PASS: slices with classes; ASK slices named; cross-feature serialization stated.
- **Design citation** — PASS: every user-story section cites its X-, M- and D- ids and states.

Delivery risk: **HIGH / ASK** remains for the feature (PR-01, PR-02, PR-08, PR-09, PR-10).

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| A second local file on the Mac (`mac-local.json`) beside the kit's `StoreDocument` | FR-023 keeps the review marks device-local and surviving sign-out; `StoreDocument` mirrors the account and is shared with the iPhone and widgets | putting Mac-only marks in `StoreDocument` forces a document version bump that collides with 020's v2 and leaks a Mac concept into the iPhone's core (R4) |
| Polling on three clients (15 s tick, 45 s pull age; web 45 s refetch) instead of a change feed | SC-001's 60 s bound in both directions with both clients open | a change feed or push is out of scope (intake §4); a 60 s age with a 60 s tick misses SC-001 (R8) |
| One ADR change (lossless archive) split over two backend slices | a safe one-step image rollback at every point | a single slice makes rollback leave every task in a newly archived project uneditable (R9) |
| A startup step runs at every backend boot instead of a one-time ledger row | marks archives made by older code during any rollback window | a ledger row runs once and misses them (R12) |
