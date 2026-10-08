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

This plan answers the design's "Notes for the plan" and gap G-7 (G-1 – G-6 were resolved at sign-off; G-8 by X-08). Planning review campaign `021-mac-sync-c1` (63 findings) is dispositioned in [review-c1-disposition.md](review-c1-disposition.md); its fixes are in this plan, the contracts, data-model, research, quickstart, design.md (states added under "Planning review c1 additions") and a minimal spec amendment (FR-003, FR-017, FR-018, FR-021 sentences, new FR-033, two edge cases, Assumptions). Campaign `021-mac-sync-c2` (65 findings, the last allowed) is dispositioned in [review-c2-disposition.md](review-c2-disposition.md); its fixes are in the same artifacts (design.md "Planning review c2 additions", new screen X-09) and a second minimal spec amendment (US1-1, US4-5, FR-006, FR-007, FR-015, FR-020, FR-029, SC-004, two edge-case sentences, Assumptions). The feature then goes to founder acceptance; the residual risks to name there are in [Risks](#risks).

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
- **Kit**: the document gains only optional `Codable` fields, so 021 needs no `StoreDocument` version step. **But the kit's public enums gain cases** (`GTDCommand.setProjectOutcome` and `.unarchiveProject`, three `GTDValidationError` cases, `SyncTrigger.periodic`), which is **source-breaking** for every exhaustive `switch` over them, in the kit and in the apps; the slice that adds a case carries every such file (rule in [Delivery slices](#delivery-slices), list in contracts/kit-commands.md §9; review c2, blocking G01). The version note: 021 does not change the version and does not collide with 020's v2.
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
  - `local-gtd.backup-<UTC>.json` and, only when the import adjusted something, `local-gtd.import-report-<UTC>.txt` (E8);
  - transient `store.import-<attemptID>.json` staging files, and `store.unreadable-<UTC>.json` files set aside by X-09 (E5; review c2, G15, G26);
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
- The legacy import of 2,000 tasks is a **goal** of under 2 s on an M-series Mac, checked as a host-check line; CI gates only a generous 10 s budget on the hosted runner (`legacy-large.json`, contracts/mac-legacy-import.md §6). Kit replay of 2,000 operations takes about 45 ms (`docs/native-ios-app.md:328-331`); placeholders show after 300 ms (a host-check line; review c2, G22).
- The first load of a large account does not block the window (edge case): the pull runs off the main actor and local commands answer at once (a `Workspace` test holds the pull open). It is **not** progressive: `listAllTasks` collects every page and the pull applies once (`BrainBuddyAPIClient.swift:167-183`), so lists fill when it lands; the X-01 "first load, empty list" line says the tasks are still arriving (review c2, G22, G56).

**Constraints**:

- Offline-first on the Mac and iPhone.
- Nothing is sent before sign-in (FR-029), except ending a session the person opened earlier (a queued logout that carries no user data, sent only to that session's own host).
- No content in logs (FR-030).
- No modal for routine sync (FR-017).
- Idempotent, owner-serialized task commands.
- The ADR-0006 four open lists stay.
- No third-party Swift dependency.
- Swift 6 strict concurrency, checked and not suppressed.

**Scale/Scope**:

- Invite-gated beta: tens of owners, hundreds to low thousands of tasks each.
- One new endpoint, one new query parameter and three new project fields.
- 12 designed screens (X-01 – X-09, M-01, M-02, D-01); X-08 is a system alert without a mockup, and X-09 (added in review c2, G15) is specified in design.md and mac-app-host.md §9.
- Three clients.

## Constitution Check (pre-design)

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Spec workflow** — PASS.
  - `intake.md`, `spec.md` (Clarifications for 2026-10-06 and the design sign-off), `checklists/requirements.md` (all checked) and the signed-off `design.md` exist. There are no NEEDS CLARIFICATION markers.
  - Inconsistencies found while planning are listed below, with their resolutions (spec commit `0b9fffe` and review c1). None blocks planning. The earlier owner question is answered in spec Assumptions; review c1's two questions were decided under the owner's delegation (spec Clarifications, "after planning-review campaign c1"; see [Decided product choices](#decided-product-choices-delegated)).
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
| `contracts/api-client-parity.json` | wire inventory read only by `frontend/src/api/__tests__/clientParity.test.ts`, which asserts exactly 42 operations and adapter keys equal to the manifest's (l.96-103); `TaskListQueryTests.swift` only names it in a test title (c2) | `unarchiveProject`, `listProjects(state)`, **in PR-06** with the web adapters (G09) |
| `backend/app/api/tasks.py:1238-1250`, `backend/app/modules/tasks/service.py:896-900` (c2) | each `ProjectResponse` computes `open_task_count` by loading every task of the owner | one-pass counts for the list route (PR-02; http.md §1) |
| `backend/app/modules/tasks/service.py:962-981` (c2) | `archive_project` checks `expected_revision` first and has no state guard | unarchive checks "already active" before the revision (http.md §3); repeat archive keeps the marker (http.md §4) |
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
| `…/BrainBuddyWorkspace/Workspace.swift` | `@MainActor @Observable`; `archiveProject` doc says there is no unarchive (320 – 324); `signIn` / `signOut(discardUnsyncedChanges:)` / `syncNow` / `networkAvailabilityChanged`; `signOut` counts only outbox operations, ends the session (`sync.signOut()`, l.407) **before** `store.destroy` (l.412) (c1) | `unarchiveProject`, `setProjectOutcome`, `apply([…])`, `syncSnapshot`, `setForegroundActive(_:)`, device kind; sign-out order through `SyncService.signOut(removingLocalDataWith:)`: record the pending logout, remove local data, then end the session (kit-commands §4; c2, G11) |
| `…/BrainBuddyFakeServer/FakeServer+Organize.swift` (75 – 89) | archive clears membership; no unarchive | mirrors http.md |
| `ios/BrainBuddy/Components/SyncStatusLabel.swift` (37 – 68) | iPhone wording with em dashes, "Syncing…", immediate "Sync failed — …" | renders `SyncStatusDescriber` (M-01) |
| `ios/BrainBuddy/Screens/Settings/SyncIssuesScreen.swift` (104 – 244) | issue descriptions; `describe` is an **exhaustive `switch` over `GTDCommand` with no `default`** (l.104-142) (c2) | delegates to `SyncIssueDescriber` (kit) **in PR-04**, the slice that adds the command cases (G01) |
| `ios/BrainBuddy/App/RootView.swift` (142 – 190) (c2) | the iPhone's load-error view: "We couldn't open your tasks", "Try again", confirmed "Start fresh" (`Workspace.resetUnreadableStore`) | mirrored on the Mac as X-09 (mac-app-host §9) |
| `…/BrainBuddyCore/NameNormalizer.swift`, `Reducer+Validation.swift:1-64`, `Vocabulary.swift:84-91` (c2) | names stored in NFKC + Python-whitespace display form, tags lose one "@"; lengths in Unicode scalars; notes ≤ 20,000; uniqueness by casefold + NFKC | the legacy import's canonical transform builds on them (`ImportCanonicalizer`, contracts/mac-legacy-import.md §2a) |
| `…/BrainBuddyAPI/BrainBuddyAPIClient.swift:167-183, 346-356` (c2) | `listAllTasks` collects every page, then the pull applies once; a token write failure in `exchange` throws `.tokenStorage` with no reference id and loses the new token | first-load wording corrected; the write failure ends that session and carries the reference id (PR-05) |
| `…/BrainBuddySync/SyncEngine+Session.swift:10-20` (c2) | with no account, `discardStaleSessions` removes all tokens without ending their server sessions | sign-out records the pending logout before removing local data (kit-commands §4) |
| `ios/BrainBuddy/Screens/Browse/ProjectsScreen.swift` (76 – 86, 126 – 145, 193 – 220) | destructive archive confirmation; read-only Archived projects list | M-02 copy, swipe and toolbar Unarchive |
| `ios/BrainBuddy/Screens/Lists/TaskListScreen.swift` (280 – 287) | "This project is archived / … read-only" | M-02 archived project screen |
| `ios/BrainBuddy/App/BrainBuddyApp.swift` | foreground `syncNow`, NWPathMonitor, BGAppRefresh (58 – 166); `WidgetReloadAfterSync` reloads every widget timeline on each syncing → idle change (l.124 – 135) (c1) | toggles the kit `PeriodicSyncTicker` with the scene phase |

### Mac

| file | current responsibility | planned use |
|---|---|---|
| `macos/Package.swift` | tools 5.10, WhisperKit, XCTest target | tools 6.2, kit products, test resources |
| `macos/Sources/BrainBuddyMac/LocalGTDStore.swift` (1363 lines) | its field rules (c2): `text()` trims Foundation whitespace and counts grapheme clusters (l.268-274); notes are unlimited (l.628-631); names unique by `localizedCaseInsensitiveCompare` (l.526-550); colours never set. JSON snapshot store, rules, review receipts, archive/restore; `init` never writes (l.194 – 206), but `mutate` creates `local-gtd.json` on the first write when it is missing and the in-memory generation is 0 (l.214 – 262), so a pre-021 copy launched after the update writes a fresh file (c1) | **deleted** after import code reads its format (`LegacySnapshot.swift`); the FR-033 rule handles the fresh file |
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
├── review-c2-disposition.md     # planning review campaign 2 dispositions
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

ios/BrainBuddyKit/
├── Package.swift                             # test resources: BrainBuddySyncTests trace copy (PR-04),
│                                             # BrainBuddyWorkspaceTests import golden (PR-08)
├── Sources/BrainBuddyCore/   Records.swift, Commands.swift, Reducer.swift, Reducer+Organize.swift,
│                             Reducer+Validation.swift, Reducer+Replay.swift, Replay.swift,
│                             Compaction.swift, Outbox.swift, SmartAdd+Resolution.swift,
│                             SyncPresentation.swift (new), SyncActivityIndicator.swift (new),
│                             SyncIssueDescriber.swift (new), TaskEditDraft.swift (new),
│                             RecordContentForm.swift (new), ListPresentationHold.swift (new),
│                             ImportCanonicalizer.swift (new), Queries+ProjectDisplay.swift (new)
├── Sources/BrainBuddyAPI/    BrainBuddyAPI.swift, BrainBuddyAPIClient.swift, APIError.swift,
│                             WireModels.swift, RequestBodies.swift, SessionTokenStore.swift (ASK)
├── Sources/BrainBuddySync/   BrainBuddySync.swift, SyncConfiguration.swift, SyncEngine.swift,
│                             SyncEngine+Cycle.swift, SyncEngine+Pull.swift, SyncEngine+Push.swift,
│                             SyncEngine+Session.swift, GTDCommand+Sync.swift, PushPlanner.swift,
│                             StoreDocument+Merge.swift, PeriodicSyncTicker.swift (new)
├── Sources/BrainBuddyWorkspace/Workspace.swift
├── Sources/BrainBuddyFakeServer/ FakeServer+Organize.swift, FakeServer+Tasks.swift,
│                                 FakeServerRecords.swift, ServerState.swift
└── Tests/  BrainBuddyCoreTests/{ReducerOrganizeTests.swift, ReducerArchiveTests.swift (new),
            ReplayTests.swift, CompactionTests.swift, SmartAddParserTests.swift,
            SyncPresentationTests.swift (new), SyncActivityIndicatorTests.swift (new),
            SyncIssueDescriberTests.swift (new), TaskEditDraftTests.swift (new),
            RecordContentFormTests.swift (new), ListPresentationHoldTests.swift (new),
            ImportCanonicalizerTests.swift (new), ProjectDisplayTests.swift (new),
            TestSupport/CoreFixtures.swift}
            BrainBuddyPersistenceTests/StoreDocumentCodingTests.swift
            BrainBuddyAPITests/{EndpointRequestTests.swift, WireDecodingTests.swift,
            ClientIdentityTests.swift (new)}
            BrainBuddySyncTests/{SyncEnginePullTests.swift, SyncEngineSchedulingTests.swift,
            SyncEngineSessionTests.swift (ASK), ProjectArchiveSyncTests.swift (new),
            SyncEngineFailingClockTests.swift (new), ProjectArchiveTraceReplayTests.swift (new),
            PeriodicSyncTickerTests.swift (new), Resources/project_archive_traces.json (new copy),
            Support/RandomCommands.swift}
            BrainBuddyWorkspaceTests/{WorkspaceCommandTests.swift, WorkspaceSyncTests.swift,
            MacIPhoneConvergenceTests.swift (new), FirstSignInMergeTests.swift (new),
            Support/FakeSyncService.swift, Resources/legacy-import-golden.json (new, PR-08)}

ios/BrainBuddy/
├── App/BrainBuddyApp.swift                   # Workspace.setForegroundActive from the scene phase
├── Components/SyncStatusLabel.swift          # renders SyncStatusDescriber (M-01)
├── Screens/Lists/TaskListScreen.swift        # M-01 status row; M-02 archived project
├── Screens/Browse/ListsHubScreen.swift, ProjectsScreen.swift   # M-01 hub row; M-02
├── Screens/Settings/SyncIssuesScreen.swift   # delegates to SyncIssueDescriber in PR-04 (exhaustive switch)
└── Screens/Settings/SettingsScreen.swift, SignInSheet.swift
ios/AGENTS.md, docs/native-ios-app.md

macos/
├── Package.swift, Package.resolved, README.md
├── Sources/BrainBuddyMac/
│   ├── BrainBuddyMacApp.swift, ContentView.swift, ProjectReviewView.swift,
│   │   QuickCaptureView.swift, QuickOpenView.swift, VoiceCapture.swift
│   ├── WorkspaceHost.swift (new), SingleInstanceGuard.swift (new), MacLocalState.swift (new),
│   │   LegacySnapshot.swift (new), LegacyStoreImporter.swift (new), UpgradeNotice.swift (new),
│   │   LegacyImportDecision.swift (new), LegacyCookieCleanup.swift (new),
│   │   ProjectMenuCommands.swift (new), UnreadableWorkspaceView.swift (new, X-09),
│   │   SyncTriggerSource.swift (new), SyncStatusLine.swift (new), SyncStatusPopover.swift (new),
│   │   SignInSheet.swift (new), SignOutConfirmation.swift (new), SyncMenuCommands.swift (new),
│   │   MacPresentationRouter.swift (new)
│   └── LocalGTDStore.swift, APIClient.swift, SmartAddParser.swift (deleted)
└── Tests/BrainBuddyMacTests/
    ├── OfflineWorkspaceTests.swift            # rewritten against the kit, Swift Testing
    ├── LegacyStoreImporterTests.swift (new), MacLocalStateTests.swift (new),
    │   SingleInstanceGuardTests.swift (new), LegacyCookieCleanupTests.swift (new),
    │   UnreadableWorkspaceTests.swift (new), SyncTriggerSourceTests.swift (new),
    │   MacSyncFlowTests.swift (new), MacPresentationRouterTests.swift (new),
    │   MacPresentationGuardTests.swift (new), SyncStatusLineModelTests.swift (new),
    │   MacKeychainTests.swift (new), MacPrivacyGuardTests.swift (new)
    ├── Resources/legacy-populated.json, legacy-awkward.json, legacy-corrupt.json,
    │   legacy-newer.json (new, synthetic; legacy-large is generated by the test)
    └── APIClientTests.swift, LocalGTDStoreTests.swift, SmartAddParserTests.swift (deleted)

frontend/
├── src/api/client.ts, taskTypes.ts, taskHooks.ts, __tests__/client.test.ts, __tests__/clientParity.test.ts,
│   __tests__/taskHooks.test.ts
├── src/components/shell/AppShell.tsx, __tests__/AppShell.test.tsx
├── src/features/tasks/TaskListPage.tsx, TaskDetailPanel.tsx, ArchivedProjectNotice.tsx (new),
│   __tests__/TaskListPage.test.tsx, __tests__/ArchivedProjectNotice.test.tsx (new),
│   __tests__/TaskDetailAutosaveUI.contract.test.tsx, __tests__/TaskDetailPanel.test.tsx
├── src/pages/PrivacyPolicyPage.tsx, __tests__/PrivacyPolicyPage.test.tsx   # PR-08: device copies (G23)
└── tests/e2e/archived-projects.spec.ts (new), tests/e2e/cross-client-refresh.spec.ts (new)
contracts/api-client-parity.json             # PR-06

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

### US1 — Sign in on the Mac and stay in sync (P1) — design X-03 (default, loading, errors incl. "no answer" and "couldn't save sign-in", after sign-in: first load), X-01 (first load, first load empty list, first upload, synced, syncing), X-02 (default, loading, first upload), X-04 (nothing unsent, unsent changes, open sync issues, backup kept, backup removed, unsaved edit or capture draft, changes arrived while open, during the first upload, error, after sign-out), X-07 (default, app menu), X-08 (default, unreachable), X-09 (every state), M-01 (synced, first sync, first upload, Settings › Sync running, sign-out with open issues)

**Mac**

- **Store**: `WorkspaceHost` builds the kit `Workspace` over `~/Library/Application Support/BrainBuddyMac/store.json` with the Mac keychain service, the macOS client identity and a 30 s pull age (contracts/mac-app-host.md §1).
- **Single instance (X-08)**: a second copy brings the running window forward and quits; only when that is impossible it shows X-08 ("Brain Buddy is already open." / "Switch to the open window to keep working.", "OK") and quits (research R6).
- **Sign-in (X-03)**: the sheet replaces the full-window sign-in and the session overlay. It calls `Workspace.signIn` (FR-001). After success the sheet closes with no toast, and X-01 reads "Not synced yet", with the indicator once the pull lasts longer than 1 s (FR-013), while the first pull runs off the main actor; lists fill when it lands, and an empty list meanwhile reads "Your tasks are still arriving." (US1-1; X-01 "first load, empty list"; review c2, G22, G36, G56). The kit's `pullFirst` makes the first cycle pull before it pushes, so account-less data merges by name (FR-003). Cancel and Esc stay enabled while "Signing in…" waits for the login reply, and are disabled from the moment the kit commits the link (`SignInCancellation.commit()`, `SignInFlow.Phase.finishing`: the first sync runs and the sheet closes signed in; as delivered 2026-10-08, PR-09). A second "Sign in…" while a flow's sheet is shown or its request is on its way does nothing, and the app menu items are disabled meanwhile (`MacSyncController.isSignInOpen`); focus returns to the status words when the opener is gone (contracts/mac-app-host.md §7).
- **Cancelled deletion (X-03)**: when signing in cancelled a pending account deletion, the sheet shows its "signed in, account deletion cancelled" note before closing (FR-017).
- **Triggers (FR-006)**: `SyncTriggerSource` drives launch, activation (forced pull, US1-4), the 2 s local-change debounce, network return and the kit's `PeriodicSyncTicker` (15 s), plus "Sync now" ⌘R from File and from the popover (X-07). The toolbar "Refresh" is removed. A tick with nothing to do runs no cycle and changes no status (kit-commands §4). The ticker runs while the app is running, also when its window is not frontmost or is covered (FR-006 as amended in review c2, G07); while signed in the host holds a `ProcessInfo` activity (`.userInitiatedAllowingIdleSystemSleep`) so App Nap does not stretch the timers, and ends it at sign-out (research R8; G64). Foreground and background go through one kit call, `Workspace.setForegroundActive(_:)`, which the iPhone uses too (G46).
- **"Sync now" is single-flight**: it is never disabled by a running sync. A press during a sync joins it or queues one follow-up (FR-019 as amended; contracts/kit-commands.md §4).
- **Selection, scroll and editing (FR-009, US1-5)**: selection, scroll and focus are keyed by `EntityID` through the kit's `SelectionAnchor`. The inline editor holds a kit `TaskEditDraft` and sends only changed fields, so incoming changes to other fields survive and the person's fields win (research R18; kit-commands §8). The pointer clause is the kit's `ListPresentationHold`: an incoming change that would move the row under the pointer, or the row being edited, leaves that row in place, takes effect for every other row, and applies to the held row when the pointer leaves it or the edit ends (contracts/mac-app-host.md §4; review c2, G04, G17). All three are Linux-tested pure helpers, not view code.
- **Sign-out (X-04, US1-6, FR-005, FR-018)**:
  - An unsaved task edit or a non-empty capture draft is guarded first by today's discard confirmation, then X-04 opens (review c2, G28).
  - The confirmation shows `signOutNothingUnsent` (decision 3) or the unsent-changes variants, with "Cancel" as the default, followed by `signOutIssues(n)` when sync issues are open (they never reached the account), `signOutBackup(until)` while the pre-upgrade backup is kept beyond this sign-out, and `signOutBackupRemoved` last when this sign-out will delete it (review c2, G24, G39, G63).
  - If the unsent count changed while X-04 was open, or the kit refuses a plain "Sign out" because a change arrived, X-04 is shown again with the new count; "Sign out and remove" discards only the count it showed (G28). As delivered (2026-10-08, PR-09) it removes only the changes X-04 named, identified by operation id and content (`Workspace.pendingChanges`, `signOut(removing:)`): any other pending change (queued in place of an acknowledged one, or an edit compacted into a named one) refuses with `unsyncedChanges`, nothing is removed, and X-04 asks again with the real count. Edits are refused while the sign-out runs (`Workspace.isSigningOut`, `GTDValidationError.signingOut`); Quick Capture and the main window keep the typed text.
  - The kit records a pending logout, removes the account's data, and only then ends the session and removes the token, queueing the logout when offline; a crash in between leaves the pending logout for the next launch (kit-commands §4 "Sign-out order"; G11, G61).
  - The sidecar marks and the backup follow E7 and E8.
  - A local removal failure shows "Couldn't sign out", removes nothing, and leaves the person signed in, as the copy says.
- **Unreadable workspace (X-09; review c2, G15, G26)**: when `Workspace.load()` reports `loadError`, the window shows X-09 instead of the lists, nothing syncs, "Try again" reloads, and a confirmed "Start fresh…" sets the file aside with `resetUnreadableStore` (kept as `store.unreadable-<UTC>.json` until sign-out). The import decision treats the workspace as in use, so a set-aside never triggers an import (contracts/mac-app-host.md §9; data-model E7.1).
- **Keychain prompt (R17; G34)**: only a person-started sign-in may show the system Keychain prompt after a rebuild; background reads are non-interactive and every Keychain call runs off the main actor (spec Assumptions; kit-commands §4). As delivered (2026-10-08, PR-09) no prompt is raised at all: macOS refuses to let a build read or delete another build's item, so after a rebuild the sign-in saves the session as the next numbered item (`<host>#1`, `#2`, …) and the highest number wins (R17, data-model E9).

**Kit**

- `ClientIdentity.macOS(version:)` is used (FR-031).
- The `.periodic` trigger, the `PeriodicSyncTicker`, `Workspace.setForegroundActive(_:)` (ticker plus forced pull on foreground, Linux-tested), the sign-out order and the Keychain write-failure path are added (contracts/kit-commands.md §4).

**iPhone (FR-032)**

- **Periodic pull**: the iPhone calls `Workspace.setForegroundActive(_:)` from the scene phase (`ios/BrainBuddy/App/BrainBuddyApp.swift`), so Mac changes reach an open iPhone within SC-001's 60 s (research R8). The decision is tested in the kit; the manual line covers only the one-line wiring (G46). `WidgetReloadAfterSync` keeps firing only on real cycles, because an idle tick changes no status.
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

### US3 — Compact status, errors only when something is wrong (P2) — design X-01 (every state incl. "error, then offline", "sidebar hidden", hover tooltip with "Last tried", long text, dark, keyboard focus), X-02 (every state incl. issue dismissal focus, the complete Tab order and the kept-outcome issue with "Discard outcome"), X-07 (unavailable), M-01 (every state incl. "error, then offline", Lists hub and Settings › Sync)

- **One describer**: `SyncStatusDescriber`, `SyncActivityIndicator` and `SyncTiming` in `BrainBuddyCore` (contracts/sync-status.md) decide the words, precedence, tone, glyph, action, tooltip and the 1 s / 0.5 s / 10 s / 60 s thresholds for both devices (FR-012 – FR-014, FR-019). The apps only render.
- **Mac X-01** (`SyncStatusLine.swift`): one line of 11 pt secondary text. It has a reserved indicator slot (a static glyph under Reduce Motion), at most one trailing action ("Sign in to sync" / "Retry"), and wraps after " · " for large sidebar text. Its accessibility name is "Sync status: … Show details". Entering an attention state is announced once, politely. It never opens a sheet or takes focus (FR-017, SC-004).
- **Mac X-02** (`SyncStatusPopover.swift`): a non-modal popover. It shows:
  - the last sync time and the waiting count with the oldest age;
  - issues, from `SyncIssueDescriber`, with "Copy" and "Dismiss";
  - "Sync now";
  - the email with "Sign out…".

  Focus order and focus on open follow design X-02 as completed in review c2 (G27): attention action (Sign in again, Sign in… when account-less, or the failing notice's Copy) → each issue's Copy → Copy outcome → Dismiss / Discard outcome → Sync now (skipped when disabled) → the offline notice's last-failure Copy → Sign out… → the "Show in Finder" links. Esc or a click outside closes it and focus returns to the words (FR-015, FR-016). It is at most 480 pt tall.
- **Sidebar hidden (X-01; review c2, G29)**: with the sidebar collapsed, calm states show nothing; an attention state shows one compact toolbar item with the same words and glyph, which opens X-02 and takes no focus. `SyncStatusLineModel` drives both the footer and this item.
- **Failing clock**: `failingSince` and `lastFailedAttemptAt` are persisted (E5). The engine keeps its backoff but schedules one attempt at exactly `failingSince + 60 s`; "Couldn't sync · Retry" appears only if that attempt fails, so an outage that ends within 60 s never shows (FR-014, SC-005). It survives a relaunch, clears on the next success, and yields to "Offline" while offline without restarting the clock. "Last tried" updates after every attempt, Retry included (FR-013's quiet indicator otherwise hides a fast failing Retry). An ended session shows at once (US3-5).
- **No dialog by construction (SC-004)**: `MacPresentationRouter` is the only presenter and takes only user intents; a macOS-lane test sweeps every status state and transition and asserts no presentation and no focus request, as a positive control. Because the router has no sync input, that sweep alone cannot fail, so `MacPresentationGuardTests` scans the Mac sources and fails when a presenting or focus API (`.sheet`, `.alert`, `.confirmationDialog`, `.popover(isPresented:`, `NSAlert`, `NSSound`, `UNUserNotificationCenter`, `NSApp.activate`, `makeFirstResponder`, focus assignment) appears outside the router and the listed user-initiated views; `SyncStatusLineModelTests` cover the 30 s re-describe, announce-once and the stable indicator slot (contracts/mac-app-host.md §6, §8; review c2, G16).
- **iPhone M-01**:
  - The list screens' status uses `SyncStatusLabel`, which renders the describer: words plus the indicator, with "Syncing…" and immediate failures gone. The attention rows become buttons: Retry runs Sync now; "Sign in again" opens the sign-in sheet with the email locked; "N changes couldn't sync" opens Sync issues. The "Couldn't sync" row's long-press, and a VoiceOver custom action, offer "Copy reference ID", and Settings › Sync shows the Reference ID from the first failure on (SC-004). The account-less "Sign in to sync" row is at least 44 pt tall (G58).
  - M-01 lists "first upload" and "error, then offline", both produced by the shared describer (G55).
  - Settings › Sync keeps its detailed section with the same words (US3-8). Its "Sync now" button stops being disabled while a sync runs, because it is single-flight on both platforms (FR-019 as amended).
  - `ios/AGENTS.md`'s copy example becomes "Offline · 3 changes waiting".

### US4 — Upgrade the Mac without losing anything (P2) — design X-05 (every state incl. "couldn't carry over", "partly carried over" and "later file"), X-01 (account-less, first upload), X-02 (empty: signed out, first upload, outcome kept on account, archive not applied at merge, pre-upgrade backup, details changed during the update, earlier-version file kept), X-03 (first sign-in with local tasks, account switch refused, partial failure)

- **Import (FR-020 – FR-022, FR-033)**: `LegacyStoreImporter` (contracts/mac-legacy-import.md) runs before the workspace opens. It first passes every legacy value through the kit's `ImportCanonicalizer` (Core, Linux-tested; review c2, blocking G02): names take the form the kit and server store (NFKC, whitespace, one "@" off tags), kit-only collisions get " (2)", over-long text is cut with the full text carried in notes or comments, and each adjustment goes to a local import report. It then turns every canonical record into kit commands at their original instants, in one global order per list, without compaction, into a staging file; verifies it field by field against the canonical expectation; records completion; only then moves it to `store.json` with an exclusive rename and renames the old file to a backup, also exclusively.
  - A normal upgrade is silent (X-05 default), also when values were adjusted (X-02 then shows "Some details changed during the update"); placeholders show after 300 ms.
  - An undecodable or newer file leaves the old file untouched and shows the X-05 alert once; a verification failure has its own "couldn't carry over" copy, because the file is fine.
  - A record that still cannot be carried is listed in the report, the backup is then never deleted by the app, and X-05 "partly carried over" shows once. This revises the c1 plan's "partial read = unreadable", which was the plan's interpretation, not a sign-off decision (design.md "Planning review c2 additions").
  - **Import state** (review c1, blocking F02): explicit and durable (`none`, `inProgress`, `completed`, `unreadable`, `laterFileKept`; data-model E7.1, whose decision table ends in a fail-closed row and covers a signed-out Mac with no `store.json`; review c2, G06, G10, G33). The importer never writes into or replaces a workspace in use, even when `mac-local.json` is lost, because it creates `store.json` only by an exclusive rename. A `local-gtd.json` that appears after the workspace exists (an older copy run after the update, a restore, a moved file) is kept untouched and surfaced once (X-05 "later file") and then by a quiet X-02 line, never imported, merged or overwritten (FR-033).
- **Review marks (FR-023)**: they move to `mac-local.json`, keep their meaning, and survive sign-in and sign-out (E7.2). Their stamp is an HMAC-SHA-256, keyed by the Mac's `installSalt` and computed with CryptoKit in the Mac target, over the kit's `RecordContentForm` (canonical bytes of the user-visible fields, Linux-tested in Core), so the upload's server-minted times and the `c:` → `s:` re-keying do not invalidate them (research R23; review c2, G13).
- **Legacy session** (review c1, F36; c2, G25, G52, G60): every `brainbuddy_session` cookie in the app's own cookie storage is removed at the first launch, whatever its host, and each one's server session is ended at its own https host, or queued for logout; the pre-021 HTTP response cache is cleared at the same time (contracts/mac-app-host.md §1).
- **Account-less use (US4-2)**: the account-less Mac shows "On this Mac · Sign in to sync" and works fully offline (FR-002). Nothing is sent except those logouts, which carry no user data (FR-029 as amended in review c2); a counting-transport test proves exactly that.
- **First sign-in (US4-3, FR-003, SC-003)**:
  - X-03 shows the one-time info box when the outbox holds account-less data.
  - The kit merges projects and tags by name and appends tasks. Merging joins **active** projects only. An archived Mac project that meets an active account project joins it with its membership kept, and its archive becomes a sync issue; one that meets only an archived account project stays a separate archived project, a documented limit not counted under SC-003 (kit-commands §3; spec edge case "Same-named archived projects").
  - A merged project's desired outcome is kept, or, when the account already has one, shown in full in a sync issue with "Copy outcome" and "Discard outcome" (5 s Undo) (FR-003). A separate `setProjectOutcome` on the merged project is dropped from the rewritten outbox and fed into the same rule, never re-targeted onto the account's project (kit-commands §3; review c2, G12, G32).
  - The real importer's output is pinned by a golden artifact that the kit's `FirstSignInMergeTests` sign in with against overlapping account names (review c2, G21).
  - The first upload reads "Not synced yet" and, in X-02, "Adding your tasks to your account · N left"; waiting ages count from the account link (`LinkedAccount.linkedAt`), not from the records' original dates (data-model E6).
  - Rejected records become sync issues (X-03 partial failure).
- **Account switch (US4-5, FR-004)**: refused while the outbox or issues are non-empty, with the device-neutral copy and the "Mac" noun. Reached when a sign-in, such as "Sign in again", resolves to a different account (review c2, G40); a stub-transport case in `MacSyncFlowTests` and a host-check line cover it.
- **Known limit**: after the first sign-in, server-minted timestamps replace local creation, completion, cancellation and waiting-since times, so a Waiting age restarts; review marks are unaffected because they key on content (research R5; spec Assumptions, extended in review c2, G41).

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
- An unarchive refused because an active project has the same name shows "Another active project is already called “Old flat”. Rename one first." with "Rename…" and no Retry. "Rename…" opens the existing rename sheet for the archived project (design X-06 "rename archived project"; review c2, G30): name selected, an inline clash error keeps focus in the field, and success clears the refusal and returns focus to "Unarchive"; there is no automatic unarchive.
- A local write error moves focus to Retry and is announced (G31). A repeated rejection says where the project stands: "Brain Buddy couldn't unarchive it, so it's still archived. Try Unarchive again later." (kit-commands §5; G57).
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
- A name clash refuses the unarchive at once with "Rename…" (M-02 "unarchive refused: name in use"), which opens the existing `ProjectEditorSheet` for the archived project (M-02 "rename archived project"; G30).
- The archived project screen renders the kit's `projectDisplay`.
- `SyncIssueDescriber` has the unarchive case.

**Web D-01**:

- The "Archived projects" disclosure under Projects (`AppShell.tsx`) is hidden when there are none.
- The archived project page has the chip, a secondary "Unarchive" button, no composer and the info line. While the request runs the button stays focusable (`aria-disabled`, busy label "Unarchiving…" announced in a polite status region), and errors use the existing notice with Ref and Retry, announced, with focus on Retry. A 409 name clash shows "Another active project is already called “Old flat”. Rename one first." with Ref and "Rename…", announced, focus kept on Unarchive, and no Retry; "Rename…" opens the options popover's name field for the archived project, and Escape returns focus to the options button (D-01; review c2, G30, G31). When offline the button is disabled.
- The task detail's project picker lists active projects, plus a task's current archived project labelled "· archived" and selected; an archived project is never a new choice (FR-025; D-01 "task project picker"; G65). `AppShell`, the only consumer of `useProjects` on the account, agent and admin pages, splits active from archived.
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
| Merged project with outcomes on both sides | the account's wins; the local one becomes a sync issue that shows it in full with "Copy outcome" and "Discard outcome" (5 s Undo), never silently dropped; a later `setProjectOutcome` on the merged project is folded into the same rule, never re-targeted | kit §3 |
| Server still clearing memberships on archive (rolled back below PR-03 after a 021 client shipped) | the kit treats an archive reply with `archived_before_lossless: true` or no `archived_at` as a clearing server and raises a sync issue instead of letting the pull strip memberships silently; the runbook forbids that rollback | kit §4, http §8 |
| Server failing (5xx, 429, timeout while online) | backoff 2 → 300 s with one attempt at exactly 60 s; indicator only until that attempt fails; then "Couldn't sync · Retry" with Ref and "Last tried"; clears on success; `failingSince` survives relaunch | sync-status §3, kit §4 |
| Server failing, then the device goes offline | "Offline …" while offline (Retry could not act); `failingSince` kept, so back online one failed attempt shows "Couldn't sync" at once | sync-status §3 |
| Session ended or revoked (401) | "Sign in again to sync" at once; work continues; the outbox is kept; the token is removed | kit, sync-status §3 |
| Offline for days | "Offline · N changes waiting"; no repeated alerts; X-02 shows the oldest age | sync-status §3 |
| Sign in as another account with pending work | refused, nothing sent (FR-004) | kit `AccountSwitchRefused` |
| Sign-out with unsent changes or open issues | X-04 warning with the count, and a sentence naming open issues; "Sign out and remove" discards only the changes it named (by id and content; any other refuses and X-04 asks again with the real count); Cancel keeps; edits are refused while it runs | mac-app-host §7, kit §4 |
| Sign-out when the local removal fails | "Couldn't sign out"; the pending logout recorded before the removal is withdrawn; the session was not ended yet, so the person is still signed in | kit §4 "Sign-out order" |
| Crash after the local removal, before the session is ended | the pending logout recorded first ends the session at the next launch; no token is left without a logout | kit §4, data-model E9 |
| Changes arrive while X-04 is open | X-04 is shown again with the new count; "Sign out and remove" discards only what it showed | mac-app-host §7 |
| The Mac's own `store.json` cannot be read | X-09 instead of the lists, nothing syncs; "Try again"; confirmed "Start fresh…" sets the file aside until sign-out; never an import | mac-app-host §9 |
| Second Mac process | brings the first forward, or shows X-08 "Brain Buddy is already open." / "Switch to the open window to keep working." with "OK"; exits; the store is untouched | research R6, design X-08 |
| Old pre-021 Mac copy running during the upgrade | the import holds its `lockf`; after the rename its writes fail with its existing 409 | mac-legacy-import §6 |
| Old pre-021 Mac copy launched after the upgrade, a restored folder, a deleted `mac-local.json`, or any of these after a sign-out emptied the workspace | the `local-gtd.json` it brings is kept untouched and never imported; X-05 "later file" once; X-02 quiet line; a restored original is never renamed or deleted, because the legacy rename is taken only when `legacyRenamedAt` is unset | data-model E7.1, FR-033 |
| Crash during the import | the next launch resumes from the recorded state; `store.json` never holds an unverified import; the legacy bytes are untouched until the rename; orphaned staging files are deleted after the decision | data-model E7.1 |
| Any state the decision table does not name | fail closed: never import, never touch a file | data-model E7.1 |
| Legacy names or lengths the kit stores differently ("Квартира №5", "™", double spaces, "@home" beside "home", long notes) | the canonical transform adjusts them by rule, keeps the full text, lists each in the import report; the upgrade stays silent | mac-legacy-import §2a |
| Legacy store undecodable or newer | never touched; X-05 once; empty workspace after Continue | mac-legacy-import §5 |
| A legacy record the transform cannot carry | the rest imports; the record is listed in the report; X-05 "partly carried over"; the backup is never deleted by the app | mac-legacy-import §2a, §5 |
| Import verification fails (an importer defect) | X-05 "couldn't carry over"; the file is kept untouched; a later build retries only while the workspace is not in use, so this is guarded before release by the property test and the dry run | mac-legacy-import §5, data-model E7.1 |
| Wrong Mac clock | relative time clamps to "just now"; ordering uses the server and outbox order, not the Mac clock | sync-status §3 |
| Keychain write fails at sign-in | X-03 "couldn't save sign-in" with Ref; the server session just opened is ended; nothing linked | kit §4, data-model E9 |
| Keychain item unreadable (rebuilt ad-hoc binary refused access) | background reads are non-interactive, so no prompt appears during sync: treated as no token → "Sign in again to sync"; logged as `keychain_read_failed`; the outbox is kept. The next person-started sign-in raises no prompt: it saves the session as the next numbered item beside the earlier build's (`<host>#1`, …) and the highest number wins (as delivered 2026-10-08; the earlier "deletes and re-adds the item" is refused by macOS with -25244) | research R17, kit §4 |
| A sign-in that hangs | Cancel and Esc stay enabled until the kit commits the link (then "Signing in…" finishes and the sheet closes signed in); a reply after cancel has its session ended; "Brain Buddy didn't answer. Try again." on timeout | mac-app-host §7 |
| Very large account | the first pull runs off the main actor and the window stays usable; it fetches every page of 200 and applies once, so lists fill when it lands, and empty lists read "Your tasks are still arriving." meanwhile | kit (existing), design X-01 |
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
- **PR-06 follows PR-03 closely** (review c2, G45): between the PR-03 deploy and the PR-06 deploy, the web served from `main` is the pre-021 bundle, so a task in a project archived in that window shows as "No project" on the web, whatever the person reloads. Nothing is lost (memberships are kept on the server); PR-06 is deployed right after PR-03 to keep the window short, and the gap is accepted.
- **TestFlight**: kit and iPhone slices land only after PR-03 is deployed, because `ios.yml` uploads every `ios/` change on `main` to TestFlight. Each of PR-04, PR-05, PR-07 and PR-08 (its kit golden artifact and `FirstSignInMergeTests` case are under `ios/`) therefore produces one TestFlight build when it lands; the ASK landings run the same push CI on `main`. PR-02 and PR-03 write nothing under `ios/` (the trace copy moved to PR-04), so they produce no build.
- The Mac is built locally, so its slices reach the owner when they rebuild.

**Rollback**:

- **Image rollback (one release back) is safe at every step until a 021 client ships** (contracts/http.md §8). PR-03 → PR-02 restores clearing for future archives only. PR-02 → previous image is safe because no retained memberships exist yet.
- **Once PR-04 has landed, PR-03 is rolled forward, never back** (review c2, G62): 021 clients apply lossless archive locally, so a clearing server would strip memberships at the next pull, which ADR-0020 cannot reconstruct. The kit's clearing-server guard turns that case into a sync issue instead of a silent loss, and `docs/api-compatibility.md` states the rule.
- **Rolling back below PR-02 after PR-03 has run** makes tasks in projects archived meanwhile reject edits until roll-forward. The runbook note in `docs/api-compatibility.md` says to roll forward.
- **Older code re-saving a project** drops `desired_outcome` and `archived_at` (stated limit, http.md §8).
- **Client rollback**: a 021 kit document holds new command cases that an older build cannot decode, so an older build reports the store unreadable rather than overwriting it. Downgrade is not a supported path (contracts/kit-commands.md §6).

**Mac data**: the import is reversible for 30 days or longer, because the backup is the untouched original (E8). An unreadable legacy store, and a previous-version file that appears later, are never touched (FR-022, FR-033). An unreadable `store.json` is only set aside after the person confirms X-09, and the set-aside file is kept until sign-out.

**Irreversible**: nothing on the server. On the Mac, sign-out with "Sign out and remove" discards unsent changes after an explicit warning (FR-018). The backup's deletion after 30 days and a sign-out is irreversible by design (FR-021); X-04 says so in the sign-out that does it, and it never happens while the import left a record not carried or at a sign-out that discards part of the first upload (E8; review c2, G24, G63).

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
  - Failures shown to the person are the attention states with Ref; SC-004 is the `MacPresentationGuardTests` source guard, the `MacPresentationRouterTests` sweep as its positive control, and the host checklist.
  - There is no new server metric, so no new alert is required (AGENTS.md "Monitoring requirements").

## Test strategy

**Ids and taxonomy**:

- Each slice starts with failing tests carrying `021-FR-…` or `021-SC-…` ids: `test_021_FR_024_…` in Python, `@Test("021-FR-012 …")` in Swift, and the id in the Vitest or Playwright title.
- **Allure**: new rules in `backend/tests/allure_taxonomy.py` for the three new test modules (epic Tasks, feature "Projects", stories "Lossless archive", "Desired outcome", "Client attribution"). Web tests live in existing folders whose rules apply. The Playwright spec gets a path rule in `frontend/tests/allure.fixtures.ts` if the existing default does not cover it.
- **Coverage floors**: `backend/coverage-floor.json` and `frontend/coverage-floor.json` may only rise, and there are no coverage suppressions in `frontend/src`.

| layer | what | key cases |
|---|---|---|
| pytest — archive | `test_project_archive_lossless_api.py` | all-state membership kept after PR-03, cleared plus marker under PR-02 (test parametrised by slice behaviour, the PR-02 cases replaced in PR-03); no task revision bump; tolerant PATCH (omit, same, different archived → 400, null, active); create and Smart Add into archived → 400; `?state=` active / archived / all / 422, and the default returning the same project set and order as today with the three new fields on each object; repeat archive changes only revision and `updated_at` (marker and `archived_at` kept; `test_021_FR_027_repeat_archive_keeps_marker`, PR-03); unarchive 200 / active no-op (checked before the revision, so a stale `expected_revision` on an active project still gets 200) / 409 stale / 409 name / 404 foreign (`second_api_client`) / idempotent replay / missing key 400; `?state=archived` and `all` never return another owner's projects and an owner with none gets `[]` (`test_021_FR_026_list_projects_state_is_owner_scoped`); startup step marks only `archived_at`-less archives, without a bump, idempotently; marker survives unarchive and is cleared by lossless archive; `open_task_count` for archived |
| pytest — outcome | `test_project_desired_outcome_api.py` | create, patch omit / null / blank / 1000 / 1001; a rename keeps it; export contains the three fields; purge removes them; log capture: no sentinel name or outcome in any line |
| pytest — attribution | `test_client_attribution_logging.py` | ios / macos / absent / malformed (newline) → fields; the raw value never logged; responses identical; `X-Correlation-ID` with a newline → a fresh UUID in the response and no raw value in any log line, a lower-cased UUID echoed unchanged (`021-FR-015`, `021-FR-030`) |
| pytest — traces | `test_project_archive_traces.py` | every trace in `fixtures/project_archive_traces.json` passes against the real API (archive, repeat archive, unarchive 200 / no-op / 409 / 404, `?state=`, tolerant PATCH, outcome omit / null / blank); from PR-04, the kit copy is byte-identical to the fixture |
| pytest — existing | `test_task_api.py`, `test_task_lifecycle_detail_api.py`, `test_task_tag_project_mvp_api.py`, `test_task_branch_coverage.py`, `test_api_contract.py`, `test_account_export.py`, `test_account_deletion.py` | clearing assertions flipped (PR-03); unarchive in the contract map, and `GET /projects` → `{"401", "422"}` (PR-02); Schemathesis stays green |
| Swift Testing (Linux) — Core | `ReducerArchiveTests`, `ReducerOrganizeTests`, `ReplayTests`, `CompactionTests`, `SmartAddParserTests`, `SyncPresentationTests`, `SyncActivityIndicatorTests`, `SyncIssueDescriberTests`, `TaskEditDraftTests`, `RecordContentFormTests`, `ListPresentationHoldTests`, `ImportCanonicalizerTests`, `ProjectDisplayTests` | ADR-0020 reducer table (kit §3) incl. repeat archive; outcome limits; the merge table (an archived local project keeps its membership in the active survivor, `.archiveNotMerged` issue; archived meets archived stays separate); a `setProjectOutcome` after a local archive is dropped at merge and fed into the outcome rule, and folds into an unsent `createProject` (`021-FR-003`, G12); Mac parser cases ported; every sync-status §5 case incl. the verbatim catalogue (with `signOutBackupRemoved`, `popoverFirstLoadEmpty`, the three backup forms), tooltips, age formatter and the failing + offline pair; issue copy for unarchive (with the rewritten-capture count) and the state-plus-next-step repeated rejection, the kept outcome in full, the archive not applied, archived-elsewhere, and a non-empty reference id on every issue; changed-fields-only diff, `EntityID` anchors and the pointer hold (`021-FR-009`); `RecordContentForm` bytes unchanged by server times and re-keying (`021-FR-023`); the canonical import transform with the reviewer's examples ("Квартира №5", "™", double spaces, "@home" beside "home", 500 emoji, 25,000-character notes) and a 500-seed property test that every value the old store accepted becomes a valid kit value (`021-FR-020`, G02); the FR-027 display rule and "accepts no new task" (`021-FR-025`, `021-FR-027`) |
| Swift Testing — Persistence, API | `StoreDocumentCodingTests`, `EndpointRequestTests`, `WireDecodingTests`, `ClientIdentityTests` | a v1 document from before 021 decodes; new fields round-trip; `X-Client: brainbuddy-macos/x`; unarchive and `?state=all` requests; a timeout `APIError` carries the sent correlation id |
| Swift Testing — Sync | `ProjectArchiveSyncTests`, `SyncEngineFailingClockTests`, `SyncEnginePullTests`, `SyncEngineSchedulingTests`, `SyncEngineSessionTests`, `ProjectArchiveTraceReplayTests`, `PeriodicSyncTickerTests` | pull with `?state=all` includes taskless archived projects, with a fallback per id against an old server; unarchive 409 → immediate local revert and one issue for a capture queued behind it; `failingSince` and `lastFailedAttemptAt` set and cleared, persisted, kept offline, not started by offline; with the real `retryDelay` (jitter at both extremes) an outage ending at 59 s shows nothing and one ending at 61 s shows "Couldn't sync" after the 60 s attempt (`021-FR-014`, `021-SC-005`); `.periodic` honours the 30 s age, never sets `pullRequested`, runs no cycle and emits no status for 29 s of idle ticks, and does nothing while a retry is scheduled, while `.manual` runs at once (`021-FR-006`); the ticker fires every 15 s while active and stops while inactive (`021-FR-006`, `021-FR-032`); foreground forces a pull; a press of "Sync now" during a cycle joins it or queues one follow-up (kept, now tested); refusal copy has the device noun; an archive reply from a clearing server raises a sync issue (G62); a Keychain write failure at sign-in ends the new session and carries its reference id (G14); traces replay against the fake server |
| Swift Testing — Workspace | `MacIPhoneConvergenceTests`, `FirstSignInMergeTests`, `WorkspaceCommandTests`, `WorkspaceSyncTests` | quickstart Scenario 4 steps 1 – 9: SC-001 at logic level for every FR-007 record type in both directions, at the worst tick phase with a 1.5 s pull, every case ≤ 60 s (`021-SC-001`, `021-FR-032`); SC-002 offline matrix, 0 lost and 0 applied twice; SC-003 merge incl. both outcomes, archived meets active, archived meets archived (duplicates counted on active names); SC-006; first-upload age from the account link (`021-FR-012`); review-mark stamps unchanged by upload and by sign-out and sign-in (`021-FR-023`); a local edit of field A while a pull changes A and B sends only A (`021-FR-009`); sign-out order: a failing removal keeps the token and sends no logout, and a crash between the removal and the session end leaves a pending logout that the next launch sends (`021-FR-018`, `021-FR-005`; G11, G61); `apply([…])` all-or-nothing; `setForegroundActive` toggles the ticker and forces one pull (`021-FR-032`; G46); with the first pull held open (`HoldingTransport`), local commands and queries answer at once and the status reads "Not synced yet" (G22); the golden import artifact signs in against overlapping account names with SC-003's 0 duplicates and 0 missing (`021-SC-003`; G21) |
| Swift Testing (macOS lane) — Mac | `LegacyStoreImporterTests`, `MacLocalStateTests`, `SingleInstanceGuardTests`, `LegacyCookieCleanupTests`, `UnreadableWorkspaceTests`, `SyncTriggerSourceTests`, `OfflineWorkspaceTests`, `MacSyncFlowTests`, `MacPresentationRouterTests`, `MacPresentationGuardTests`, `SyncStatusLineModelTests`, `MacKeychainTests`, `MacPrivacyGuardTests` | mac-legacy-import §6, including the awkward fixture, the golden artifact reproduced byte for byte, the 10 s budget for 2,000 tasks, the import state machine and the FR-033 cases (legacy file after a fresh install, an unwritten fresh workspace that imports, `mac-local.json` removed, a new file after the rename, sign-out then an older copy writes a new file, the backup deleted by retention then the original restored, an `inProgress` record with a foreign `store.json`, a staging file orphaned by a lost sidecar), each asserting unchanged bytes where FR-033 requires it; X-09 on an unreadable `store.json` with no import and no sync; no compaction (`waitingSince ≠ createdAt` exact); cross-project list order; sentinel-home log privacy; sidecar rekeying, survival across sign-out, launch-time 30-day pruning and 7-day validity; lock held or released or stale after a crash; the legacy cookie removed and its logout queued; trigger table (mac-app-host §5) with a fake clock and a fake path monitor; offline journeys ported from the deleted XCTest suite (capture, quick capture, Waiting, Someday and Project reviews, clarify as project, archived browse, archive by File menu, unarchive and its name-clash refusal); mac-app-host §8: zero requests account-less, except exactly one bodiless logout per legacy cookie to its own host (`021-FR-029`), sync log privacy (`021-FR-030`), the source-level presentation guard and the status sweep with no presentation or focus (`021-SC-004`, `021-FR-017`), the status-line model's 30 s re-describe, announce-once and stable indicator slot (`021-FR-012`), the login-keychain round trip in a temporary keychain that fails rather than skips, not synchronizable, non-interactive reads, delete-and-re-add after a denial (`021-FR-005`), voice sources without network APIs; sign-in, sign-out (unsaved-edit guard, changes arriving while X-04 is open) and the account-switch refusal (`021-FR-004`, US4-5) against a stub `HTTPTransport` |
| Vitest | `client.test.ts`, `clientParity.test.ts`, `taskHooks.test.ts`, `AppShell.test.tsx`, `TaskListPage.test.tsx`, `ArchivedProjectNotice.test.tsx`, `TaskDetailAutosaveUI.contract.test.tsx`, `TaskDetailPanel.test.tsx`, `PrivacyPolicyPage.test.tsx` | every D-01 state (disclosure count and hidden, archived page, unarchiving with `aria-disabled` and focus kept, unarchived focus and toast, archived just now with focus and toast, error with Ref and Retry announced and focused, refused with "Rename…", focus on Unarchive and no Retry, rename archived project incl. its clash error, Escape returning focus to the options button, offline disabled, pre-feature empty line, filtered empty, "· archived" labels, archive hint); the project picker offers no archived project except the task's own (`021-FR-025`); the parity manifest with `unarchiveProject` and `listProjects(state)`; the privacy policy's device-copy and erasure sentences (G23); `refetchInterval: 45_000` and `refetchIntervalInBackground: false` on the task list, projects, tags and task detail queries (`021-FR-032`, `021-SC-001`); a detail refetch while typing keeps the typed text and takes the untouched field's new value |
| Playwright | `frontend/tests/e2e/archived-projects.spec.ts`, `frontend/tests/e2e/cross-client-refresh.spec.ts` | quickstart Scenario 7: archive keeps tasks, unarchive from the page, no overflow at 390 × 851, 44 px button, axe scan; with a fake clock, a subtask, a comment and a tag rename made through the API while the page is open appear within 45 s of fake time, scroll and selection unchanged (`021-SC-001`, `021-FR-032`) |
| macOS host (manual) | `specs/021-mac-sync/evidence/manual-macos-status.md`, `manual-macos-upgrade.md`, `manual-macos-archive.md` | SC-004 state sweep on screen (no dialog, no focus change), VoiceOver for X-01, X-02, X-03, X-04, X-05, keyboard order incl. X-02 Dismiss and X-03 focus return, X-03 Cancel while signing in, scroll and focus during an incoming change, Reduce Motion, large sidebar text, the Keychain item present and no token in files, the Keychain prompt after a rebuild only at sign-in, the full Keychain round trip when the CI test was skipped, sleep and wake reconnect, a web change appearing within 60 s with the window not frontmost and covered (`021-FR-006`), the row under the pointer not moving (`021-FR-009`), the sidebar hidden with an attention state, X-04 "backup removed" and "changes arrived while open", X-02 "Discard outcome" with Undo, X-09, the account-switch refusal, the 300 ms import placeholders, the dry run on a copy of the owner's folder, real upgrade from a pre-021 build and the "later file" path; every X-06 state incl. the rename sheet, the remembered disclosure, the strings, focus after archive and unarchive |
| iPhone host (manual) | `specs/021-mac-sync/evidence/manual-ios-status.md`, `manual-ios-archive.md` | M-01 and M-02 states at Dynamic Type AX5, VoiceOver custom action Unarchive, 44 pt rows; a web change appears on the open iPhone within 60 s with no touch and nothing is fetched in the background (`021-FR-032`); long-press and VoiceOver "Copy reference ID"; the 44 pt account-less row; "first upload" and "error, then offline"; the rename sheet after a refused unarchive; Settings "Sync now" enabled while syncing; sign-out with open issues |

**Requirement coverage**:

- Every FR-001 … FR-033 and SC-001 … SC-006 is named by at least one test. FR-032 is named by `PeriodicSyncTickerTests`, the convergence test, `taskHooks.test.ts` and the Playwright check; FR-033 by `LegacyStoreImporterTests`.
- **SC-007** is post-release acceptance (quickstart Scenario 9). It is reported as **manual-pending**, not covered, until `evidence/owner-week.md` holds seven dated entries; the template never counts.
- **Gates in PR-10**: `make check-specs` runs `scripts/check_requirement_coverage.py specs/021-mac-sync --requirements <every id except SC-007>` and the new `scripts/check_manual_evidence.py` under the [Evidence protocol](#evidence-protocol), instead of the `test -f` first planned; it prints SC-007's pending status.
- **Before 020 PR-01 lands** (review c1, F48): the coverage script on this branch scans no Swift and has no `--requirements` flag. Each Swift slice (PR-04, PR-05, PR-07, PR-08, PR-09) then records its requirement → test-name list (`grep -rn "021-\(FR\|SC\)-"` over its test files) and its `swift test` output in its PR body or landing record.

### Evidence protocol

Review c2 (G18, G47, G54) replaced the c1 rule, which compared a commit SHA by ancestry: a squashed landing never contains the SHA a pre-squash record names, and ancestry does not notice a later change.

- **Identity by content**: each manual evidence file's header records, besides build, OS and date, the git **tree hashes** of the code it evidences at that build (`git rev-parse <commit>:macos` and so on): `macos/` and `ios/BrainBuddyKit/` for the Mac records, `ios/BrainBuddy/` and `ios/BrainBuddyKit/` for the iPhone records. `check_manual_evidence.py` recomputes them at the release commit and fails when they differ, until the record is re-made on the new build. A tree hash is the same before and after a squash, so a record made on the slice's candidate build stays valid after landing.
- **When evidence lands**: host records are made on the landed build (or the candidate with identical trees) and committed afterwards in a docs-only commit under `specs/021-mac-sync/evidence/`, which changes no tree it names. An ASK PR carries its automated evidence and references its candidate build by tree hashes; its host records follow under this rule. PR-10's gate is the point where every required record must be present and current.
- **Content-free guard**: the script fails on any of `/Users/`, `~/Library`, `Keychains/`, a run of 32 or more hexadecimal characters outside the header's tree-hash fields, an email not ending in `@example.com`, or any non-Markdown file under `specs/021-mac-sync/evidence/`.
- **Skipped Keychain test**: `MacKeychainTests` uses a temporary keychain and fails rather than skips. If a hosted runner ever cannot create one, the test must be disabled with a visible, reasoned trait, and the gate then demands the full round-trip line (set, update, remove, pending logout, not synchronizable) in `manual-macos-status.md`.
- `scripts/test_check_manual_evidence.py` covers each rule: matching and differing trees, a squash-equivalent record, each forbidden pattern, and the skipped-test line.

## Delivery slices

These are the proposed PR-sized slices. `/speckit-tasks` turns this table into the `## PR-срезы` manifest with file-level paths: no globs and no bare "tests", with each slice's own test files named.

Classes follow ADR-0008 and `scripts/classify_path_risk.py` ("mech." = the classifier result; the final class is the stricter of mechanical and semantic). ASK means a PR plus the owner's recorded approval (see [Migration, deploy order and rollback](#migration-deploy-order-and-rollback)).

**Rescope, 2026-10-07 (owner decision, applied in `tasks.md`):** the minimal path to Mac sync is PR-02, PR-03, PR-04, PR-05, PR-08 and PR-09 (PR-01 is merged) plus PR-10 reduced to the minimum release gate. PR-06 (web) and PR-07 (iPhone) are deferred to a follow-up feature, and so are PR-10's manual-evidence checker and coverage-floor raise. The table, deploy order and lanes below stay as planned; read them with those slices removed. No contract changes.

**Mechanical classification, re-run for review c2** (c1 blocking F01; c2 blocking G01): every slice's full path list below was fed as `printf '%s\0' <paths> | python3 scripts/classify_path_risk.py --null` on 2026-10-06 at `a2f4827` (first run for c1 at `0b9fffe`). Review c2 changed paths in PR-02, PR-04 to PR-09; no class changed.

| slice | paths | mech. | ASK paths (classifier reason) | final class |
|---|---|---|---|---|
| PR-01 | 5 | ASK | all five (`.github/`, `scripts/`) | ASK |
| PR-02 | 18 | ASK | `backend/app/api/tasks.py`, `backend/app/api/middleware.py` (explicit API paths) | ASK |
| PR-03 | 6 | SHIP | — | SHOW (semantic) |
| PR-04 | 56 | SHIP | — | SHOW (semantic) |
| PR-05 | 22 | **ASK** | `ios/BrainBuddyKit/Tests/BrainBuddySyncTests/SyncEngineSessionTests.swift`, `ios/BrainBuddyKit/Sources/BrainBuddyAPI/SessionTokenStore.swift` (token `session`) | **ASK** (was SHOW; corrected in c1) |
| PR-06 | 19 | SHIP | — | SHOW (semantic) |
| PR-07 | 11 | SHIP | — | SHOW (semantic) |
| PR-08 | 43 | SHIP | — | ASK (semantic) |
| PR-09 | 22 | SHIP | — | ASK (semantic) |
| PR-10 | 8 | ASK | `Makefile`, `scripts/check_manual_evidence.py`, `scripts/test_check_manual_evidence.py` | ASK |

Path changes in review c2: PR-02 drops `contracts/api-client-parity.json` (to PR-06, G09). PR-04 gains `Reducer.swift`, `Compaction.swift`, `RecordContentForm.swift` (was `RecordContentStamp`), `ListPresentationHold.swift`, `ImportCanonicalizer.swift`, `FakeServer+Tasks.swift`, `FakeServerRecords.swift`, `CompactionTests`, `ListPresentationHoldTests`, `ImportCanonicalizerTests`, `Support/RandomCommands.swift` and the iPhone app's `SyncIssuesScreen.swift` (moved from PR-07; G01, G02, G04, G13). PR-05 gains `BrainBuddyAPIClient.swift`, `APIError.swift` and `Support/FakeSyncService.swift` (G11, G14). PR-06 gains the parity manifest and `TaskDetailPanel.test.tsx` (G09, G65). PR-08 gains `LegacyImportDecision.swift`, `UnreadableWorkspaceView.swift`, `UnreadableWorkspaceTests`, `legacy-awkward.json`, the kit's `Package.swift`, `FirstSignInMergeTests.swift` and `Resources/legacy-import-golden.json` (G21), and the privacy policy page and its test (G23). PR-09 gains `MacPresentationGuardTests` and `SyncStatusLineModelTests` (G16).

Path change at `/speckit-analyze` (2026-10-06): PR-04 gains `ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/TestSupport/CoreFixtures.swift`, the Core property-test command generator, so `CompactionPropertyTests` exercise the new `setProjectOutcome` fold (56 paths; the classifier re-run over every slice of tasks.md's manifest changed no class).

**Enum-case rule** (review c2, blocking G01): a slice that adds a case to a public kit enum carries, in its own paths, every file that switches exhaustively over that enum, in the kit and in the apps. They are found with a search for `switch` over the type in `ios/BrainBuddyKit`, `ios/BrainBuddy`, `ios/BrainBuddyWidgets`, `ios/Shared` and `macos/` (contracts/kit-commands.md §9 holds the list for 021's cases). The kit's `Codable` additions are not the only compatibility question: a new enum case is source-breaking for every exhaustive switch, and any `^ios/` diff builds the iPhone app on the landing path. `/speckit-tasks` re-runs the search over the manifest, and implementers re-run it before landing.

PR-05 was declared "SHOW (mech. SHIP)" in the first plan although its existing test file `SyncEngineSessionTests.swift` already classified ASK (the classifier camel-splits it into `sync`, `engine`, `session`, `tests`); `SyncEngine+Session.swift` tokenizes as `engine+session` and stays SHIP. It is now ASK, and the deploy order and lanes below follow. `/speckit-tasks` must re-run the classifier over the manifest's final paths, and a manifest path that changes a slice's mechanical class changes the slice's class.

| id | outcome | depends on | main paths | class |
|---|---|---|---|---|
| PR-01 | `macos-app` CI lane with the `macos` change output (also true for `ios/BrainBuddyKit/`); validator registration (lane limits, path-filter list, `full-ci` / `allure-report` needs) with tests; `SCREEN_ID_RE` widened to `X-` with a test (G-7) | — | `.github/workflows/ci.yml`, `scripts/validate_ci_artifacts.py`, `scripts/test_validate_ci_artifacts.py`, `scripts/render_feature_report.py`, `scripts/test_render_feature_report.py` | **ASK** (mech.: `.github/`, `scripts/`) |
| PR-02 | Backend tolerant contract: PATCH accepts carried archived membership; `GET /projects?state=`; `POST /projects/{id}/unarchive`; `desired_outcome`; `archived_at` + `archived_before_lossless` with the startup step; archive still clears and sets the marker; `X-Client` log fields; incoming correlation id validated; `GET /projects` 422 in the route and the contract map; `?state=` owner-scoped (`test_021_FR_026_list_projects_state_is_owner_scoped`) with open counts in one pass; unarchive checks "already active" before the revision; repeat archive keeps the marker; API contract map; golden traces (PR-02 behaviour), backend only; Allure rules; `docs/api-compatibility.md` client note and the forward-only rollback rule; data-retention wording for the outcome. The parity manifest moves to PR-06 (review c2, G09) | 020 PR-02 landed (external) | `backend/app/api/tasks.py`, `backend/app/api/middleware.py`, `backend/app/schemas/tasks.py`, `backend/app/modules/tasks/{domain.py,repository.py,service.py}`, `backend/tests/test_project_archive_lossless_api.py`, `backend/tests/test_project_desired_outcome_api.py`, `backend/tests/test_client_attribution_logging.py`, `backend/tests/test_project_archive_traces.py`, `backend/tests/fixtures/project_archive_traces.json`, `backend/tests/{test_task_branch_coverage.py,test_api_contract.py,test_account_export.py,test_account_deletion.py,allure_taxonomy.py}`, `docs/api-compatibility.md`, `docs/data-retention.md` | **ASK** (mech.: `api/tasks.py`, `api/middleware.py`) |
| PR-03 | Lossless archive (ADR-0020): memberships kept, `archived_at`, marker cleared; repeat archive pytest; clearing tests flipped; traces updated to lossless (backend only) | PR-02 | `backend/app/modules/tasks/service.py`, `backend/tests/{test_task_api.py,test_task_lifecycle_detail_api.py,test_task_tag_project_mvp_api.py,test_project_archive_lossless_api.py}`, `backend/tests/fixtures/project_archive_traces.json` | **SHOW** (mech. SHIP; cross-client behaviour change) |
| PR-04 | Kit contract: records E3; commands; ADR-0020 reducer rules incl. repeat archive; the merge table (archived local project keeps its membership in an active survivor; `.archiveNotMerged`); outcome merge rule with the full outcome in the issue; Smart Add copy; `SyncIssueDescriber`; `ClientIdentity`; `listProjects(state:)` pull with fallback; unarchive push with the immediate revert on 409; `Workspace.unarchiveProject` / `setProjectOutcome` / `apply([…])`; the post-merge `setProjectOutcome` rule and its compaction fold; the clearing-server guard; pure helpers `TaskEditDraft`, `SelectionAnchor`, `RecordContentForm`, `ListPresentationHold`, `ImportCanonicalizer`, `projectDisplay`; every exhaustive switch over the new cases, including the iPhone `SyncIssuesScreen` delegating to `SyncIssueDescriber` (review c2, blocking G01); fake server mirroring http.md, with the three project fields; the kit trace copy, its `resources:` declaration and the byte-equality pytest; trace replay; Mac parser cases ported | PR-03 | `ios/BrainBuddyKit/Package.swift`, `ios/BrainBuddyKit/Sources/BrainBuddyCore/{Records,Commands,Reducer,Reducer+Organize,Reducer+Validation,Reducer+Replay,Replay,Compaction,SmartAdd+Resolution,SyncIssueDescriber,TaskEditDraft,RecordContentForm,ListPresentationHold,ImportCanonicalizer,Queries+ProjectDisplay}.swift`, `…/BrainBuddyAPI/{BrainBuddyAPI,BrainBuddyAPIClient,APIError,WireModels,RequestBodies}.swift`, `…/BrainBuddySync/{GTDCommand+Sync,PushPlanner,SyncEngine+Pull,SyncEngine+Push,StoreDocument+Merge}.swift`, `…/BrainBuddyWorkspace/Workspace.swift`, `…/BrainBuddyFakeServer/{FakeServer+Organize,FakeServer+Tasks,FakeServerRecords,ServerState}.swift`, `…/Tests/BrainBuddyCoreTests/{ReducerOrganizeTests,ReducerArchiveTests,ReplayTests,CompactionTests,SmartAddParserTests,SyncIssueDescriberTests,TaskEditDraftTests,RecordContentFormTests,ListPresentationHoldTests,ImportCanonicalizerTests,ProjectDisplayTests}.swift`, `…/Tests/BrainBuddyCoreTests/TestSupport/CoreFixtures.swift`, `…/Tests/BrainBuddyPersistenceTests/StoreDocumentCodingTests.swift`, `…/Tests/BrainBuddyAPITests/{EndpointRequestTests,WireDecodingTests,ClientIdentityTests}.swift`, `…/Tests/BrainBuddySyncTests/{ProjectArchiveSyncTests,SyncEnginePullTests,ProjectArchiveTraceReplayTests}.swift`, `…/Tests/BrainBuddySyncTests/Resources/project_archive_traces.json`, `…/Tests/BrainBuddySyncTests/Support/RandomCommands.swift`, `…/Tests/BrainBuddyWorkspaceTests/{WorkspaceCommandTests,FirstSignInMergeTests}.swift`, `backend/tests/test_project_archive_traces.py`, `ios/BrainBuddy/Screens/Settings/SyncIssuesScreen.swift` | **SHOW** (mech. SHIP; ships to TestFlight; changes iPhone archive behaviour) |
| PR-05 | Kit status, cadence and session: `SyncPresentation` (snapshot, describer, timing, copy catalogue incl. sign-out issue and backup sentences), `SyncActivityIndicator`, `failingSince`, `lastFailedAttemptAt` and reference id in `SyncMetadata` (the first-upload age uses the existing `LinkedAccount.linkedAt`), the 60 s confirmation attempt, `.periodic` (no-op when idle) and `PeriodicSyncTicker`, `Workspace.setForegroundActive(_:)`, single-flight `syncNow` kept and now tested, device-neutral refusal, sign-out order through `SyncService.signOut(removingLocalDataWith:)` with the pending logout recorded first, the Keychain write failure at sign-in (session ended, reference id kept), macOS token-store attributes with non-interactive background reads, `Workspace.syncSnapshot`; convergence and offline matrix (SC-001, SC-002); first pull held open (review c2, G11, G14, G22, G34, G43, G46) | PR-04 | `…/BrainBuddyCore/{SyncPresentation,SyncActivityIndicator,Outbox}.swift`, `…/BrainBuddySync/{BrainBuddySync,SyncConfiguration,SyncEngine,SyncEngine+Cycle,SyncEngine+Session,PeriodicSyncTicker}.swift`, `…/BrainBuddyAPI/{SessionTokenStore,BrainBuddyAPIClient,APIError}.swift`, `…/BrainBuddyWorkspace/Workspace.swift`, `…/Tests/BrainBuddyCoreTests/{SyncPresentationTests,SyncActivityIndicatorTests}.swift`, `…/Tests/BrainBuddySyncTests/{SyncEngineFailingClockTests,SyncEngineSchedulingTests,SyncEngineSessionTests,PeriodicSyncTickerTests}.swift`, `…/Tests/BrainBuddyWorkspaceTests/{MacIPhoneConvergenceTests,WorkspaceSyncTests}.swift`, `…/Tests/BrainBuddyWorkspaceTests/Support/FakeSyncService.swift` | **ASK** (mech.: `SyncEngineSessionTests.swift`, `SessionTokenStore.swift`; semantic: session end, account switch, sign-out order, token store) |
| PR-06 | Web D-01: archived disclosure, archived project page, Unarchive with every state incl. the name-clash refusal, its "Rename…" and the focus rules, archive hint, archived-just-now, "· archived" names, the task project picker (active plus the task's own archived project), FR-027 line, 45 s visible refetch on the list, projects, tags and open task detail, type drift fix, the parity manifest with its adapters and count (review c2, G09), Playwright (archive and cross-client refresh) and axe. Deployed right after PR-03 (http.md §7) | PR-03 | `frontend/src/api/{client.ts,taskTypes.ts,taskHooks.ts}`, `frontend/src/api/__tests__/{client.test.ts,clientParity.test.ts,taskHooks.test.ts}`, `contracts/api-client-parity.json`, `frontend/src/components/shell/AppShell.tsx`, `frontend/src/components/shell/__tests__/AppShell.test.tsx`, `frontend/src/features/tasks/{TaskListPage.tsx,TaskDetailPanel.tsx,ArchivedProjectNotice.tsx}`, `frontend/src/features/tasks/__tests__/{TaskListPage.test.tsx,ArchivedProjectNotice.test.tsx,TaskDetailAutosaveUI.contract.test.tsx,TaskDetailPanel.test.tsx}`, `frontend/tests/e2e/{archived-projects.spec.ts,cross-client-refresh.spec.ts}`, `frontend/tests/allure.fixtures.ts` | **SHOW** (mech. SHIP) |
| PR-07 | iPhone M-01 and M-02: status row via the describer (lists, Lists hub, Settings › Sync), attention rows as buttons, long-press and VoiceOver "Copy reference ID", 44 pt account-less row, "first upload" and "error, then offline" rows, Settings "Sync now" enabled during a sync, `Workspace.setForegroundActive(_:)` called from the scene phase, sign-out confirmation naming open issues, archive copy, archived project screen via `projectDisplay`, the name-clash refusal with "Rename…" through `ProjectEditorSheet`, Unarchive swipe / toolbar / VoiceOver action; `ios/AGENTS.md` copy; `docs/native-ios-app.md` (archive, backend asks 5 and 7 done, `X-Client` macOS); manual evidence (host lane). Sync issues already delegate to `SyncIssueDescriber` from PR-04 | PR-05 | `ios/BrainBuddy/App/BrainBuddyApp.swift`, `ios/BrainBuddy/Components/SyncStatusLabel.swift`, `ios/BrainBuddy/Screens/Lists/TaskListScreen.swift`, `ios/BrainBuddy/Screens/Browse/{ListsHubScreen,ProjectsScreen}.swift`, `ios/BrainBuddy/Screens/Settings/{SettingsScreen,SignInSheet}.swift`, `ios/AGENTS.md`, `docs/native-ios-app.md`, `specs/021-mac-sync/evidence/{manual-ios-status.md,manual-ios-archive.md}` | **SHOW** (mech. SHIP) |
| PR-08 | Mac adoption, account-less: tools 6.2 / Swift 6, kit dependency, `WorkspaceHost`, `SingleInstanceGuard` with X-08, X-09 for an unreadable workspace, legacy import through `ImportCanonicalizer` with its durable state machine (`LegacyImportDecision`, fail-closed), staging file and its cleanup, verification against the canonical expectation, import report, exclusive backup rename and every X-05 state incl. "partly carried over" and "later file" (FR-033), the golden import artifact and the kit's `FirstSignInMergeTests` case that signs in with it (G21), `MacLocalState` review marks with HMAC stamps over `RecordContentForm`, legacy cookie and HTTP-cache cleanup, model replaced by `Workspace` with `ListPresentationHold` in the list views, X-06 incl. the File-menu keyboard path, the refused state and its rename sheet, removals, account-less X-01 line, Mac tests in Swift Testing with the XCTest ledger, data-retention rows as written in data-model E5, E7, E8 (Mac store, sidecar, backup, import report, staging and set-aside files, kept files, legacy cookie and cache) and the export sentence, the privacy policy paragraph (data-model "Privacy policy"; G23), upgrade and archive evidence (host lane) | PR-01, PR-05; 020 PR-06 landed (external) | `macos/Package.swift`, `macos/Package.resolved`, `macos/Sources/BrainBuddyMac/{BrainBuddyMacApp,ContentView,ProjectReviewView,QuickCaptureView,QuickOpenView,VoiceCapture,WorkspaceHost,SingleInstanceGuard,MacLocalState,LegacySnapshot,LegacyStoreImporter,UpgradeNotice,LegacyImportDecision,LegacyCookieCleanup,ProjectMenuCommands,UnreadableWorkspaceView,LocalGTDStore,APIClient,SmartAddParser}.swift`, `macos/Tests/BrainBuddyMacTests/{OfflineWorkspaceTests,LegacyStoreImporterTests,MacLocalStateTests,SingleInstanceGuardTests,LegacyCookieCleanupTests,UnreadableWorkspaceTests,APIClientTests,LocalGTDStoreTests,SmartAddParserTests}.swift`, `macos/Tests/BrainBuddyMacTests/Resources/{legacy-populated,legacy-awkward,legacy-corrupt,legacy-newer}.json`, `ios/BrainBuddyKit/Package.swift`, `ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/FirstSignInMergeTests.swift`, `ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/Resources/legacy-import-golden.json`, `frontend/src/pages/PrivacyPolicyPage.tsx`, `frontend/src/pages/__tests__/PrivacyPolicyPage.test.tsx`, `macos/README.md`, `docs/data-retention.md`, `specs/021-mac-sync/evidence/{manual-macos-upgrade.md,manual-macos-archive.md}` | **ASK** (semantic: one-time migration of real user data, legacy session removal; mech. SHIP; its `ios/` paths produce one TestFlight build on landing) |
| PR-09 | Mac sync: X-03 sign-in sheet incl. Cancel while loading, "no answer" and "couldn't save sign-in", X-04 sign-out with the issue and backup sentences (incl. "backup removed"), the unsaved-edit guard and "changes arrived while open", X-01 every state incl. "first load, empty list" and "sidebar hidden", X-02 popover incl. the complete focus order, "Discard outcome" with Undo, backup, report and later-file lines, X-07 menus and ⌘R, `MacPresentationRouter`, the source-level presentation guard, `SyncStatusLineModel`, `SyncTriggerSource` (activation, occlusion, path monitor, the kit ticker, the App Nap activity, flush), Keychain service (numbered session items after a rebuild and no access prompt, as delivered 2026-10-08; calls off the main actor), macOS client identity; `docs/native-macos-app.md` (incl. the login-keychain disposition); AGENTS.md line; data-retention Keychain row as written in data-model E9; status evidence (host lane) | PR-08 | `macos/Sources/BrainBuddyMac/{BrainBuddyMacApp,ContentView,WorkspaceHost,SyncTriggerSource,SyncStatusLine,SyncStatusPopover,SignInSheet,SignOutConfirmation,SyncMenuCommands,MacPresentationRouter}.swift`, `macos/Tests/BrainBuddyMacTests/{SyncTriggerSourceTests,MacSyncFlowTests,MacPresentationRouterTests,MacPresentationGuardTests,SyncStatusLineModelTests,MacKeychainTests,MacPrivacyGuardTests}.swift`, `docs/native-macos-app.md`, `AGENTS.md`, `macos/README.md`, `docs/data-retention.md`, `specs/021-mac-sync/evidence/manual-macos-status.md` | **ASK** (semantic: session credential, first egress of Mac data; mech. SHIP) |
| PR-10 | Release gates: 021 requirement coverage (every id except SC-007) and `scripts/check_manual_evidence.py` (headers, per-state checklists, tree-hash identity against the release commit, the content-free guard, the Keychain round-trip line when the CI test was skipped, SC-007 pending; see [Evidence protocol](#evidence-protocol)) in `make check-specs` (gate integrity re-recorded); coverage floors raised; evidence README (content-free rule) and owner-week template | PR-06, PR-07, PR-09; 020 PR-01 landed (external) | `Makefile`, `.specify/gate-integrity.json`, `backend/coverage-floor.json`, `frontend/coverage-floor.json`, `scripts/check_manual_evidence.py`, `scripts/test_check_manual_evidence.py`, `specs/021-mac-sync/evidence/{README.md,owner-week.md}` | **ASK** (mech.: `Makefile`, `scripts/`) |

**PR-04 task lanes** (review c2, G20): PR-04 stays one slice (its enum cases and their switches must land together, G01), but `/speckit-tasks` splits it into file-disjoint lanes. (a) Rules: `Records`, `Commands`, `Reducer`, `Reducer+*`, `Replay`, `Compaction`, `SmartAdd+Resolution`, their Core tests and `RandomCommands.swift`. (b) API: `BrainBuddyAPI`, `BrainBuddyAPIClient`, `APIError`, `WireModels`, `RequestBodies` with `EndpointRequestTests`, `WireDecodingTests`, `ClientIdentityTests`. (c) Fake server and traces: the four fake-server files, `Package.swift` resources, the trace copy, the byte-equality pytest and `ProjectArchiveTraceReplayTests`. (d) Pure helpers: `TaskEditDraft`, `SelectionAnchor`, `RecordContentForm`, `ListPresentationHold`, `ImportCanonicalizer`, `projectDisplay` and their tests. (e) Integration, after (a) – (c): `SyncIssueDescriber` and the iPhone `SyncIssuesScreen` (they need the new cases), `GTDCommand+Sync`, `PushPlanner`, `SyncEngine+Pull`, `SyncEngine+Push`, `StoreDocument+Merge`, `Workspace.swift`, `StoreDocumentCodingTests`, `ProjectArchiveSyncTests`, `SyncEnginePullTests`, `WorkspaceCommandTests` and `FirstSignInMergeTests`. Lanes (a) – (d) start in parallel; (e) owns `Workspace.swift`; the slice compiles only when (a) and (e) are both in, so CI runs on the assembled slice. PR-05 keeps landing after PR-04.

**PR-08 task lanes** (review c1, F47): PR-08 stays one slice, but `/speckit-tasks` splits it into two task lanes: (a) importer and host: `LegacySnapshot`, `LegacyStoreImporter`, `LegacyImportDecision`, `UpgradeNotice`, `MacLocalState`, `SingleInstanceGuard`, `LegacyCookieCleanup`, `UnreadableWorkspaceView`, `WorkspaceHost`, their tests and fixtures, the golden artifact and the kit's `FirstSignInMergeTests` case, mostly new files; (b) rebinding: `ContentView` and the other views onto `Workspace`, `ProjectMenuCommands`, the removals, the privacy policy page. The importer is wired into the launch order only by the last task, after the rebinding: until then the old `BrainBuddyModel` still reads `local-gtd.json`, and an importer that renamed it would break the running build. Placing the importer and its state machine in a Foundation-only library target that Linux can build (logger injected) is allowed and left to the implementer (review c2, G48); the plan's tests and paths assume the executable target, and a library target adds its paths to the manifest and re-runs the classifier.

**XCTest ledger** (review c2, G49): PR-08 deletes or rewrites the 71 XCTest cases in `macos/Tests/BrainBuddyMacTests`. `tasks.md` carries a ledger with one row per old test: its new Swift Testing test, or a retirement reason that names where the rule now lives (for example "kit `ReducerOrganizeTests` covers name uniqueness" or "the REST paging layer no longer exists"). Rules with no obvious successor, such as rejecting a project-review action after the project changed, the editor's comment and collection length limits, and never replacing a corrupt snapshot, get an explicit row.

**Automated and host-evidence lanes** (review c2, G19): PR-07, PR-08 and PR-09 each split into an **automated lane** an agent can finish (code, tests, CI green on the exact SHA; Mac and iPhone app tests run only on the `macos-app` / `ios-app` lanes or on a Mac, so red-then-green is observed there, not in a Linux worktree) and a **host-evidence lane** that needs a person: a macOS GUI session, VoiceOver, a real pre-021 build (PR-08), an iPhone (PR-07). The owner (Max) runs the host lane on the build the automated lane produced. Ordering: for the ASK slices PR-08 and PR-09, the PR carries the automated evidence and the owner's approval may be recorded before the host lane; the host records land afterwards in a docs-only commit and are checked by PR-10's gate against the release commit (see [Evidence protocol](#evidence-protocol)). PR-08's upgrade host check, and the dry run on a copy of the owner's real folder (quickstart Scenario 6, step 0), happen **before** the owner upgrades their own Mac. `tasks.md` marks each task Linux or macOS runtime.

**Lanes inside 021**:

```text
PR-01 ───────────────────────────────────────────────────────┐
PR-02 → PR-03 → PR-06 (web)                                   │
              → PR-04 → PR-05 (ASK) → PR-07 (iPhone)          │
                                    → PR-08 (Mac, ASK) ←──────┘ → PR-09 (Mac sync UI, ASK)
PR-06 + PR-07 + PR-09 → PR-10 (ASK)
```

PR-05's development may start beside PR-04 (its pure status files share nothing with PR-04), but it lands after PR-04 and through the ASK procedure.

Independent slices with no edge between them share no write path:

- PR-06 is frontend only.
- PR-07 owns `docs/native-ios-app.md` and `ios/AGENTS.md`.
- `docs/data-retention.md` is written by PR-02, PR-08 and PR-09, which form a dependency chain.
- `AGENTS.md` is written by PR-09 only (research R22).
- `backend/tests/test_project_archive_traces.py` is written by PR-02 and PR-04, and the backend fixture by PR-02 and PR-03 (chains through PR-03).
- The trace copy under `ios/BrainBuddyKit/Tests/…/Resources/` is written by PR-04 only; PR-02 and PR-03 write nothing under `ios/`.

**Parallelism with 020's waves** (research R20; 020 lanes from `specs/020-weekly-review/tasks.md:511-524`):

| 021 slice | can run in parallel with | must be serialized with |
|---|---|---|
| PR-01 | every 020 slice | — |
| PR-02, PR-03 | 020 PR-01, PR-03 – PR-14 except PR-15 (and, for PR-02, except PR-07 and PR-09) | 020 PR-02 (land first; landed on `main` at `afaa820`), 020 PR-15 (either order; the second rebases); for PR-02 also 020 PR-07 and PR-09 (`docs/data-retention.md`; either order) |
| PR-04, PR-05 | 020 backend and web slices, PR-06 | 020 PR-03, PR-04, PR-08, PR-12 (shared kit files) |
| PR-06 | 020 backend, iOS and Mac slices | 020 PR-05, PR-10, PR-13 |
| PR-07 | 020 backend and web slices | 020 PR-04, PR-08, PR-12; PR-09 (`ios/AGENTS.md`; either order) |
| PR-08, PR-09 | every 020 slice except PR-06, PR-07, PR-09 and PR-15 | after 020 PR-06 (sidebar row; kept by PR-08); 020 PR-07, PR-09 and PR-15 (`docs/data-retention.md`, and for PR-08 `frontend/src/pages/PrivacyPolicyPage.tsx`; either order, the second rebases) |
| PR-10 | — | 020 PR-14 (both edit `Makefile` `check-specs`) |

The 020 lane that 021 leans on most is iOS core (020 PR-03 → PR-04). Recommended order: let 020 PR-03 land first. It is approved and already sequenced, and it bumps `StoreDocument` to v2. 021's kit slices add only optional fields on top. 021 needs no version step either way.

## ASK-class surfaces (summary)

- **ASK paths**: `backend/app/api/tasks.py` and `backend/app/api/middleware.py` (explicit ASK paths), PR-02.
- **Session token paths** (token `session`): `ios/BrainBuddyKit/Sources/BrainBuddyAPI/SessionTokenStore.swift` and `ios/BrainBuddyKit/Tests/BrainBuddySyncTests/SyncEngineSessionTests.swift`, PR-05 (review c1, F01).
- **`.github/workflows/ci.yml`** (`.github/`), PR-01. It is protected by invariants only, and no invariant is touched.
- **`scripts/validate_ci_artifacts.py`, `scripts/render_feature_report.py` and their tests** (`scripts/`), PR-01; **`scripts/check_manual_evidence.py` and its test**, PR-10.
- **`Makefile`** (guarded), PR-10. Re-record `.specify/gate-integrity.json` with `python3 scripts/check_gate_integrity.py --update` in the same commit. The `check-specs` invariant keeps the 019 line, and 021 is added beside it and beside 020's.
- **Semantic ASK**: PR-05 (session end, account switch, sign-out order, token store), PR-08 (one-time migration of real local data; legacy session removal) and PR-09 (session credential; first egress of Mac data).
- **Review risk**: `plan.md` names ASK `.py` and `.yml` paths, so `scripts/spec_kit_planning_review.py` derives risk **high** for this feature, and the review run needs the recorded human sign-off (ADR-0012).

## Inconsistencies found while planning

These were found in spec.md, design.md and repository docs while planning. Items 1 – 5 are now **resolved**: the spec amendment `0b9fffe` settled 1 – 4, the FR-019 amendment `b83d367` settled 5, and review c1 brought the plan, research, contracts and design.md in line (review c1, F11, F40).

1. **Task deletion and manual reorder do not exist anywhere** — resolved by `0b9fffe` (FR-007, FR-009 and the edge case no longer mention them).
   - No client and no server route deletes a task or reorders one: there is no `DELETE /tasks`, the kit has no delete or reorder command, and the Mac has no drag (`ContentView.swift` has no `onMove`).
   - **Project deletion does not exist either** (review c1, F63): the server's only DELETE is `/tags/{tag_id}` (`backend/app/api/tasks.py:691`), and no client deletes a project. ADR-0020's "List deletion remains a separate, confirmed, irreversible operation" names a future operation. US2-5's example now uses a project archived elsewhere.
   - **Plan**: "manual order" is the create-time `order_key`, carried as is and preserved by the import. The "deleted elsewhere" sync-issue copy is kept, labelled as a defensive path, for the 404 that a foreign or purged record can still produce (kit-commands §5); no test or example assumes a delete route.
2. **SC-001 needs the iPhone and the web to poll** — resolved by `0b9fffe` (FR-032). **Plan**: the kit's `PeriodicSyncTicker` (15 s, pull age 30 s) on the iPhone while active, and a 45 s visible-tab refetch on the web task list, projects, tags and open task detail (research R8).
3. **The backup outlives sign-out** — resolved by `0b9fffe` (Assumptions) and review c1 (FR-021 states that without a sign-out the backup is kept). **Plan**: implemented as written (E8), listed in `docs/data-retention.md` with the row text of data-model E8, and stated in the X-04 confirmation with its date (review c1, F27, F42).
4. **Design gap G-8, "already open"** — resolved by design X-08 and FR-017 (`0b9fffe`). **Plan**: bring the running copy forward; otherwise X-08: "Brain Buddy is already open." / "Switch to the open window to keep working." with "OK" (research R6). The copy first proposed here ("Close the other copy …" with "Quit") is withdrawn.
5. **iPhone "Sync now" parity** — resolved by the FR-019 amendment (`b83d367`). **Plan**: follows FR-019 (PR-07). design.md's superseded note is corrected and M-01 has the "Settings › Sync, sync running" row.
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
- **G-8** ("already open"): resolved by design X-08 (`0b9fffe`); realised in `SingleInstanceGuard` (research R6).

## Decided product choices (delegated)

There is no open product question. The planning question about completion and creation dates after the first sign-in is **answered**: spec Assumptions (`0b9fffe`, extended in review c2 to cancellation and waiting-since times) accept the limit, as the iPhone's account-less upload does, and `docs/native-macos-app.md` records it.

Review c1 raised two product choices. Both were **decided** under the owner's delegation, with the recommended default (spec Clarifications, "Session 2026-10-06 (after planning-review campaign c1)", commit `95ce8de`); the plan follows them:

1. **OQ-1 — Removing the pre-upgrade backup on request** (review c1, F27, F42, F62): no deletion control and no cap in 021. The X-04 confirmation states until when the backup stays, or that this sign-out removes it (review c2), X-02 shows it with "Show in Finder", and `docs/data-retention.md` and the privacy policy list it, so the person is told and can remove the file.
2. **OQ-2 — Adding a kept previous-version file into a workspace in use** (review c1, F02, F38): not in 021. The file is kept and surfaced; nothing is lost. Review c2 narrowed the cases that reach it: an ordinary legacy file now always imports (canonical transform, records that cannot be carried are reported), so only a later file or an importer defect leaves a kept file.

Review c2 raised no product decision. It added states and copy to the signed-off design without changing any decision (design.md "Planning review c2 additions"); the ones the founder should see at acceptance are listed under [Risks](#risks) "Founder acceptance notes". All other technical choices were made in research.md, as the owner asked.

## Risks

| risk | likelihood / impact | mitigation |
|---|---|---|
| PR-08 is large: it rebinds about 4,000 lines of SwiftUI from `BrainBuddyModel` to `Workspace` | high / medium | the views stay and only bindings change; `/speckit-tasks` splits PR-08 into the "importer and host" and "rebinding" task lanes, the importer wired at launch only by the last task; view logic that needs tests (draft diff, anchors, pointer hold, project display, content form, canonical transform) lives in kit pure helpers; the macOS lane (PR-01) lands first so every step is compiled and tested in CI |
| The legacy file reappears after the update (older copy, restore, deleted sidecar, after a sign-out) | medium / high | the import state machine, its fail-closed last row and the exclusive renames never touch a workspace in use (FR-033, data-model E7.1); the named FR-033 tests |
| Realistic legacy data the kit stores differently (normalisation, lengths, uniqueness) | high / high before c2 | `ImportCanonicalizer` is total over what the old store accepted, Linux-tested with the reviewer's examples and a property test; verification against the canonical expectation; nothing dropped silently (review c2, blocking G02) |
| New enum cases break app-side exhaustive switches | high / medium before c2 | the enum-case rule and kit-commands §9's consumer list; PR-04 carries the iPhone `SyncIssuesScreen` (review c2, blocking G01) |
| `KeychainSessionTokenStore` has never run on macOS | medium / high | PR-05 drops the iOS-only accessibility attribute on macOS; a macOS-lane round trip in a temporary keychain that fails rather than skips; a write failure is a visible sign-in error that ends the new session |
| Swift 6 diagnostics in `VoiceCapture.swift` / WhisperKit | medium / low | confine WhisperKit to one actor; a documented `@preconcurrency import` only if WhisperKit's declarations force it (R2) |
| Keychain access refused after each ad-hoc rebuild | high / low | background reads never prompt, so routine sync shows no dialog; the Mac shows "Sign in again to sync" and the person-started sign-in saves the new session as the next numbered item (as delivered 2026-10-08: no prompt, nothing deleted and re-added; R17). Residual: the earlier build's orphaned item lingers until its session expires (30 days) |
| Collisions with 020 in shared kit and backend files | high / medium | the serialization table above; optional `Codable` fields and additive enum cases, so no `StoreDocument` version race; a 020 slice that adds a switch over `GTDCommand` after PR-04 handles the new cases |
| App Nap stretches the Mac's timers when the window is hidden | medium / medium | a `ProcessInfo` activity while signed in keeps the 15 s tick; a host-check line with the window covered (G64) |
| Fake server drifting from the backend on archive semantics | medium / high | golden traces run against both, and a pytest asserts the kit copy is byte-identical; the landing path runs every stack (R19) |
| Full pull every 30 s per open Mac or iPhone, and a 45 s web refetch, on a large account | low / low at today's scale | an idle tick sends nothing; paged by 200; the `client` log field lets the cost be watched per client; a change feed stays a backend ask |
| Image rollback below PR-02 after PR-03, or of PR-03 after PR-04 | low / high | two-step deploy; one-step rollback is safe until a 021 client ships, then PR-03 rolls forward only; the clearing-server guard makes a mistaken rollback visible |
| Older code drops `desired_outcome` on re-save during a rollback | low / medium | stated limit (http.md §8); the outcome editor exists only on the Mac, so the window is short |
| macOS runner availability or minutes, or a slow WhisperKit fetch in CI | medium / low | the lane runs only when `macos/` or the kit changes; `Package.resolved` pins versions |
| A real legacy file has a shape the fixtures miss | low / high | the canonical transform carries and reports what it can; verification fails closed (X-05, file untouched); the dry run on a copy of the owner's folder (quickstart Scenario 6, step 0) comes before the owner's own upgrade |

### Residual risks (compensating measures for founder acceptance)

After two review campaigns these remain, by design or by limit. Each has the compensating measure the founder accepts with it.

1. **An importer defect strands the legacy data in practice.** A `verificationFailed` import leaves the file untouched, but the person then uses the empty workspace, and FR-033 forbids importing into a workspace in use; OQ-2 deferred a person-started "Add these tasks". *Measures*: the total, Linux-tested canonical transform and its property test; verification failure is the only path left; the mandatory dry run on a copy of the owner's real folder before their own upgrade; X-05 tells the person the file is fine and kept.
2. **Visible names change at the upgrade.** "Квартира №5" becomes "Квартира No5", "™" becomes "TM", double spaces collapse, a kit-only clash gets " (2)", over-long text is cut with the full text kept in notes or comments. This is the form the server already stores, so it would happen at the first sign-in anyway. *Measures*: the import report and the X-02 "Some details changed" line; nothing is lost.
3. **Losing every trace of the import at once**: if `mac-local.json` is gone, no backup or set-aside file is left (the person deleted them, or the E8 rule removed the backup after a sign-out) and `store.json` is absent after a sign-out, nothing on the Mac shows that the import happened. A restored original is then imported again, and the next sign-in uploads its tasks a second time (tasks are not merged by title). *Measures*: invariant 2 keeps the workspace in use whenever any one trace remains; the sidecar-lost fallback reads the import date from the backup's file name; duplicates are visible and removable, nothing is lost.
4. **Every ad-hoc rebuild asks the owner to sign in again**, because background Keychain reads never prompt (FR-017). *Measures*: no data loss, the outbox is kept; one sign-in at the person-started sheet (no access prompt, as delivered 2026-10-08); documented in `docs/native-macos-app.md`.
5. **Energy cost of the App Nap activity** while the Mac app is open and signed in (a pull at most every 30 s). *Measures*: idle ticks send nothing; the activity ends at sign-out; the owner week watches it.
6. **Several behaviours are proven only by a person on real hardware**: VoiceOver, Reduce Motion, Dynamic Type AX5, the Keychain items after a rebuild (no prompt, as delivered 2026-10-08), sleep and wake, the covered-window cadence, the real pre-021 upgrade. *Measures*: the host-evidence lanes, tree-hash identity so stale records fail PR-10's gate, and the owner week (SC-007).
7. **Hosted macOS runner and a temporary keychain**: if a runner cannot create one, the credential test cannot run there. *Measures*: the test fails rather than skips; a deliberate disable is visible and makes the manual round-trip line mandatory.
8. **The first pull of a large account is not progressive**: lists fill at once when it lands. *Measures*: the window stays usable, empty lists say the tasks are still arriving, and a test holds the pull open.
9. **The web shows "No project" for tasks of projects archived between the PR-03 and PR-06 deploys.** *Measures*: memberships are kept on the server; PR-06 deploys right after PR-03.
10. **Rollback is forward-only once a 021 client has shipped** (PR-03 after PR-04; client downgrade is unsupported). *Measures*: the runbook rule, the clearing-server guard, and the unreadable-store paths (X-09 on the Mac).
11. **Dependencies outside 021**: 020 PR-01 (Swift requirement coverage), PR-02 and PR-06 must land; until 020 PR-01 lands, Swift coverage is recorded per slice by hand. *Measures*: the interim rule in the Test strategy and the serialization table.
12. **Six ASK slices on one serial chain** (PR-01, PR-02, PR-05, PR-08, PR-09, PR-10) each need the owner's recorded approval. *Measures*: the automated lanes finish without a person; the deploy order lets SHOW slices proceed in parallel.

**Founder acceptance notes** (decided under delegation in review c2, no product decision raised): X-09 is a new screen id mirroring the iPhone's load-error view; the sidebar-hidden toolbar item appears only in attention states; "partial read" now imports what decodes instead of refusing the whole file; the App Nap activity trades energy for SC-001 on a covered window; X-02 "Discard outcome" with a 5 s Undo replaces "Dismiss" for a kept outcome; X-04 gains "backup removed", the unsaved-edit guard and "changes arrived while open"; FR-006, FR-007, FR-015, FR-020, FR-029, SC-004, US1-1, US4-5 and the Assumptions were reworded to match the existing system (spec changes listed in review-c2-disposition.md).

## Planning review

The `after_plan` hook (`/speckit-review`) is run by the owner. Campaign `021-mac-sync-c1` (`.specify/workflows/runs/021-mac-sync-c1/`) returned 63 technical findings (2 blocking, 37 important, 24 advisory) and no product decision; every finding is dispositioned in [review-c1-disposition.md](review-c1-disposition.md). Campaign `021-mac-sync-c2`, the last allowed (cap 2), returned 65 technical findings (2 blocking, 32 important, 31 advisory) and no product decision; every finding is dispositioned in [review-c2-disposition.md](review-c2-disposition.md). The feature then goes to founder acceptance with the residual risks above.

## Constitution Check (post-design)

- **Spec workflow** — PASS. Inconsistencies 1 – 5 are resolved (`0b9fffe`, `b83d367`, review c1); 6 – 8 are handled in the plan. Gap G-8 is resolved by X-08. The two product choices from review c1 were decided under delegation (`95ce8de`); review c2 raised none, and its spec rewordings keep FR/SC numbering.
- **Consent & Safety** — PASS:
  - no egress before sign-in except ending a session opened earlier, to its own host and with no user data (FR-029 as amended), tested with a counting transport;
  - the credential only in the login keychain, never synchronizable, with its real at-rest disposition documented;
  - the pre-021 cookie session ended and its cookie removed;
  - content-free logs with tests on server and Mac, and an incoming correlation id that cannot inject log text;
  - the import is non-destructive, total over realistic data, fails closed, and never touches a workspace in use;
  - the server field is exported and purged;
  - the device files are listed in `docs/data-retention.md` with the row text written in data-model, and the privacy policy says that device copies outlive the server's erasure until sign-out.
- **Tests** — PASS: failing-first tests per slice, covering idempotency, retries, partial failure, crash recovery, offline replay, rollback-safe validation and every design state id.
- **Contracts** — PASS:
  - the five contract files, `data-model.md` and this plan agree: E1 ↔ http §2, E3 / E4 ↔ kit §1 – §3, E5 / E6 ↔ sync-status, E7 / E8 / E10 ↔ mac-legacy-import and mac-app-host;
  - the backend lands before its clients;
  - the compatibility story for older iPhone and web builds is in http §7.
- **Observability** — PASS: Ref on every surfaced failure, including timeouts; client attribution in the request log; Mac logs content-free.
- **Mobile/resilience** — PASS: offline-first Mac and iPhone, the durable outbox, single instance, a crash-safe import, and no blocking first load.
- **Delivery boundary** — PASS: slices with classes re-derived from the classifier; ASK slices named; cross-feature serialization stated.
- **Design citation** — PASS: every user-story section cites its X-, M- and D- ids and states, X-08 and X-09 included.

Delivery risk: **HIGH / ASK** remains for the feature (PR-01, PR-02, PR-05, PR-08, PR-09, PR-10).

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| A second local file on the Mac (`mac-local.json`) beside the kit's `StoreDocument` | FR-023 keeps the review marks device-local and surviving sign-out; `StoreDocument` mirrors the account and is shared with the iPhone and widgets | putting Mac-only marks in `StoreDocument` forces a document version bump that collides with 020's v2 and leaks a Mac concept into the iPhone's core (R4) |
| Polling on three clients (15 s tick, 30 s pull age; web 45 s refetch) instead of a change feed | SC-001's 60 s bound in both directions with both clients open | a change feed or push is out of scope (intake §4); a 60 s age with a 60 s tick misses SC-001, and a 45 s age leaves a worst case just over 60 s (R8) |
| A staging file and an exclusive rename for the one-time import | the import must never write over a workspace in use, even when its own record is lost (FR-033) | writing `store.json` in place and trusting the sidecar record replaces a used workspace when `mac-local.json` is deleted or an older copy brings the legacy file back (review c1, F02) |
| A process activity that keeps App Nap from stretching the Mac's timers while signed in | SC-001's 60 s with the Mac window covered or not frontmost (FR-006 as amended) | accepting throttling would make SC-001 hold only for a visible window, which the spec does not say (research R8; review c2, G64) |
| One ADR change (lossless archive) split over two backend slices | a safe one-step image rollback at every point | a single slice makes rollback leave every task in a newly archived project uneditable (R9) |
| A startup step runs at every backend boot instead of a one-time ledger row | marks archives made by older code during any rollback window | a ledger row runs once and misses them (R12) |
