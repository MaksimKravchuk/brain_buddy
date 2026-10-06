# Research: Mac ↔ backend sync (021)

**Feature**: `specs/021-mac-sync/` · **Date**: 2026-10-06 · **Plan**: [plan.md](plan.md)

Each decision is given as Decision / Rationale / Alternatives considered. Facts are
cited to the repository as of commit `e50b144` on `claude/mac-sync-spec`. Spec and
design are inputs; nothing here changes them. Where this file settles something the
spec or design left open, it says so.

## Facts this research rests on (verified 2026-10-06)

- **Mac app**:
  - `macos/Package.swift` uses `swift-tools-version: 5.10` with no `swiftSettings` (Swift 5 mode). It declares `.macOS("26.0")`, one executable target `BrainBuddyMac` depending on WhisperKit (`argmax-oss-swift` from 0.18.0, pinned in `macos/Package.resolved`), and one XCTest target `BrainBuddyMacTests` (71 tests in four files).
  - `macos/Sources/BrainBuddyMac/ContentView.swift` (4201 lines) holds `@MainActor final class BrainBuddyModel: ObservableObject` (l.14 – 1379) and every view.
  - **Store**: `LocalGTDStore.swift` writes one `Snapshot`:
    - `version 1` and `generation`;
    - `tasks`, `projects` and `tags`;
    - `idempotency`, `idempotencyReceipts`, `waitingReviews` and `somedayReviews`.

    It writes `~/Library/Application Support/BrainBuddyMac/local-gtd.json` under `lockf` on `.local-gtd.json.lock`, with a generation check, a temp file, `fsync` and `rename` (l.188 – 264). Ids are `<prefix>_<lowercased UUID>` (l.266). A corrupt file or one whose `version ≠ 1` sets `loadError` and is never overwritten (l.194 – 212).
  - **Archive**: the store keeps membership on archive and has `unarchiveProject` (l.1313 – 1362). The UI calls it "Restore".
  - **Review marks**:
    - Waiting and Someday receipts are `{taskRevision, reviewedAt}` keyed by task id.
    - Project review marks live on the project record as `lastReviewedAt`, `lastReviewDecision` and `lastReviewedTaskSignature`, a SHA-256 over the sorted `id:revision` pairs of the project's tasks (l.147 – 157, 321 – 334).
  - **API client**: `APIClient.swift` is online-only. It uses the shared cookie jar, sends no `X-Client` and no correlation id, and has no archive, unarchive or outcome endpoint.
  - **Single instance**: there is no single-instance mechanism. `BrainBuddyMacApp.swift` declares one `Window` scene, but a second process is only refused at its first write (409 "Reopen Brain Buddy before editing").
  - **CI**: no CI lane builds or tests `macos/`. The `changes` job's `ios` flag matches only `^ios/` (`.github/workflows/ci.yml:179`).
- **`ios/BrainBuddyKit`**:
  - **Package**: `swift-tools-version: 6.2` (Swift 6 mode), platforms `.iOS("26.0"), .macOS("26.0")`, no dependencies. Its products are Core, Persistence, API, Sync and Workspace. `BrainBuddyFakeServer` is a target, **not a product**.
  - **Records**:
    - `TaskRecord` already has `orderKey`, `createdAt`, `updatedAt`, `lastOpenList`, subtasks and comments.
    - `ProjectRecord` has no `desiredOutcome` and no `archivedAt`.
    - There is no task delete and no reorder command.
  - **Reducer**: `archiveProject` clears `projectID` on every task (`Reducer+Organize.swift:56-70`). There is no unarchive. Interactive assignment to an archived project throws `.projectNotActive`, and replay drops the reference (`Reducer+Replay.swift:31-75`).
  - **Persistence**: `FileDocumentStore(fileURL:)` is injectable. `DocumentFile` locks with `flock` on a sibling `.lock` file and writes atomically with `F_FULLFSYNC` on Darwin. A newer or corrupt document is never overwritten.
  - **API client**: `BrainBuddyAPIClient` sends `X-Client: brainbuddy-ios/<version>` from the constant `BrainBuddyAPI.clientName` (`BrainBuddyAPI.swift:14`) and a fresh `X-Correlation-ID`. `KeychainSessionTokenStore(service:accessGroup:)` sits behind `#if canImport(Security)`.
  - **SyncEngine**:
    - Triggers are `launch`, `foreground`, `localChange` (2 s), `networkRestored`, `manual` and `backgroundRefresh`.
    - `pullInterval` is 60 s and is checked only when a cycle runs; there is **no periodic timer**.
    - Backoff runs 2 → 300 s.
    - `.failing` follows two consecutive failed cycles; there is no time threshold.
    - The account-switch refusal text hard-codes "iPhone" (`SyncEngine.swift:195`).
  - **Status**: `SyncStatus` (`Outbox.swift:156-166`) has no outbox count, oldest age or failing-since. The iPhone's wording lives in the app (`ios/BrainBuddy/Components/SyncStatusLabel.swift:37-68`) and uses the em-dash forms.
- **Backend**:
  - **Project routes** are in `backend/app/api/tasks.py` (ASK path):
    - `GET /projects` (active only, no query parameters);
    - `POST /projects`;
    - `PATCH /projects/{id}`;
    - `POST /projects/{id}/archive`;
    - `GET /projects/{id}` (any state).

    There is no unarchive.
  - **Archive** (`backend/app/modules/tasks/service.py:958-1013`) sets `project_id = None` on every member task.
  - **Update validation**: `update_task` validates the task's *current* project when `project_id` is not in the PATCH (l.649 – 655). With membership retained, any edit of a task in an archived project would therefore fail with 400.
  - **`ProjectDocument`** (`domain.py:31-43`) has no `archived_at` and no `desired_outcome`. It is stored as a JSON `payload` plus the `state` and `normalized_name` columns (`repository.py:102-109`). One-time steps use the `migration_ledger` table (l.174 – 238).
  - **Export and purge**: export writes every project with `model_dump` (`account_service.py:265-273`); purge calls `delete_all_for_owner`.
  - **Middleware**: `CorrelationIdMiddleware` (`backend/app/api/middleware.py:22-75`, ASK path) accepts an incoming `X-Correlation-ID` and logs `api_request method path status duration_ms`. Nothing reads `X-Client`.
- **Web**:
  - **Projects**: the web lists active projects only (`frontend/src/api/taskHooks.ts:71-76`, `frontend/src/components/shell/AppShell.tsx:568-649`) and resolves names only from that list.
  - **Archive** is triggered from `frontend/src/features/tasks/TaskListPage.tsx:411-434`.
  - **Polling**: no task query has a `refetchInterval`.

## R1. How the Mac adopts the shared sync behaviour

- **Decision**: the Mac package depends on the local package `ios/BrainBuddyKit` through `.package(path: "../ios/BrainBuddyKit")` and uses its products `BrainBuddyCore`, `BrainBuddyPersistence`, `BrainBuddyAPI`, `BrainBuddySync` and `BrainBuddyWorkspace`.
  - **What it replaces**: the Mac's own GTD and sync stack is removed:
    - `LocalGTDStore.swift`, `APIClient.swift` and the Mac's `SmartAddParser.swift` are deleted;
    - `BrainBuddyModel`'s inline rules (ContentView l.403 – 406, 922 – 929, 995 – 998, 1046 – 1054, 1158 – 1167, 1213 – 1216, 1245 – 1248) are deleted;
    - the views bind to `Workspace` (`@MainActor @Observable`) and render `GTDQueries`.
  - **Rules location**: every GTD rule is decided by `GTDReducer` (the `ios/AGENTS.md` "Rules live in `BrainBuddyCore`" rule now binds the Mac too).
  - **Mac target contents**: the Mac app target keeps only presentation, AppKit glue (hotkey, voice, path monitor, timers, single instance), the legacy-store import and the Mac-only review marks.
- **Rationale**:
  - FR-011 requires conflicts to resolve "exactly as they do on the iPhone today", and spec Assumptions call the iPhone the reference. One implementation is the only way that holds without a parity test suite that would itself need maintaining.
  - The kit already compiles for macOS 26 (`Package.swift:9`), has no Apple-only API outside `#if canImport`, and needs no UIKit (no `canImport(UIKit)` anywhere in the kit).
  - The Mac POC was the origin of the kit's rules and parser (`docs/native-ios-app.md:57`), so behaviour is already close.
  - The missing pieces (lossless archive, unarchive, desired outcome) are needed by the server and the iPhone anyway (FR-024 – FR-028).
- **Alternatives considered**:
  - **Port a second sync engine into `macos/`**: rejected. There would be two outbox, replay and merge implementations, and the merge-by-name rule (FR-003) and the conflict table would drift.
  - **Move the kit to a neutral path** (for example `apple/BrainBuddyKit` or a root `BrainBuddyKit/`): considered and **rejected for this feature**.
    - It touches many places:
      - `ios/project.yml` package reference;
      - `ios/scripts/swift-linux.sh`;
      - the `ios-kit` and `ios-app` working directories in `.github/workflows/ci.yml`;
      - the `^ios/` filter in `.github/workflows/ios.yml` (TestFlight `decide` job);
      - `ios/AGENTS.md`, `docs/native-ios-app.md`;
      - and every `ios/BrainBuddyKit/...` write path in 020's approved `## PR-срезы` manifest (`specs/020-weekly-review/tasks.md:770`), which is mid-delivery (`.worktrees/020-pr-01-governance`, `.worktrees/020-pr-02-foundation`).
    - The gain is cosmetic. A rename can be its own SHIP change after 020 and 021 land.
  - **Ship the kit as a binary or XCFramework**: rejected. It adds build artefacts and signing for no benefit in a monorepo.
  - **Keep `LocalGTDStore` for account-less use and the kit only when signed in**: rejected. Account-less data must become the outbox that sign-in uploads (FR-003, "as the iPhone does"), so there must be one store.

## R2. Toolchain, Swift 6 and name clashes

- **Decision**: `macos/Package.swift` moves to `swift-tools-version: 6.2`, which defaults the `BrainBuddyMac` target to the Swift 6 language mode with complete strict concurrency, as the kit and `ios/` use (`ios/AGENTS.md` "Swift 6 language mode").
  - **Model and views**: the replaced `BrainBuddyModel` (an `ObservableObject` holding a non-Sendable `APIClient`) disappears with the adoption, and views bind to the `@MainActor` `Workspace`.
  - **WhisperKit**: the remaining Swift 6 hazards are known (`VoiceCapture.swift:84` passes a non-Sendable `WhisperKit` across isolation; `QuickCaptureView.swift:8-23` has a C hot-key callback). They are fixed by confining WhisperKit to one `actor VoiceTranscriber`; the type is non-Sendable but never leaves the actor. Only if WhisperKit's own declarations force it does the import become `@preconcurrency import WhisperKit`, with the comment `ios/AGENTS.md` requires.
  - **Hot-key callback**: it keeps hopping to the main actor.
  - **Name clashes**: the kit exports `APIError`, `FieldChange`, `TaskChanges`, `TaskPriority`, `TaskSort`, `TaskTransitionAction`, `SubtaskTransitionAction`, `SmartAddParser`, `TaskUpdateBody` and `TaskTransitionBody`, which the Mac target also declares. They disappear because the Mac declarations are deleted with `APIClient.swift`, `LocalGTDStore.swift` and `SmartAddParser.swift`.
  - **Tests**: new Mac tests use Swift Testing, as the kit does. The four existing XCTest files are deleted or rewritten with the code they test (plan "Test strategy").
- **Rationale**:
  - The new code is mostly sync glue between an actor (`SyncEngine`), a `@MainActor` model and AppKit callbacks. That is exactly where Swift 5 mode would hide a data race.
  - Removing the model first leaves few Swift 6 diagnostics, and the remaining ones are in two known files.
  - A root package may depend on a package with a higher tools version as long as the toolchain supports it. Raising the Mac manifest to 6.2 is therefore a choice made for the language mode, not a SwiftPM requirement.
- **Alternatives considered**:
  - **Keep tools 5.10, or set `swiftLanguageModes: [.v5]`**: rejected. It builds, but the glue to `SyncEngine` and `Workspace` would compile with minimal checking, contrary to "Concurrency is checked, not suppressed" (`ios/AGENTS.md`).
  - **Qualify kit names (`BrainBuddyAPI.APIError`) and keep the Mac types**: rejected. The Mac types belong to the code being removed.

## R3. CI for the shared kit and the Mac

- **Decision** (slice PR-01, **ASK**: `.github/` and `scripts/`):
  - **Kit lanes**: the kit keeps its two existing lanes: `ios-kit` (Linux, `swift:6.2-noble`) and `ios-app` (macOS 26, Xcode).
  - **New `macos` output** on the `changes` job: it is true when the diff touches `^macos/` or `^ios/BrainBuddyKit/`, or a shared surface (`.github/`, `scripts/`, `Makefile`, Compose), and always on the landing path. This mirrors the existing rule at `ci.yml:169-185`.
  - **New `macos-app` lane** ("Mac app on macOS (Xcode 26)"):
    - `runs-on: ${{ needs.changes.outputs.macos == 'true' && 'macos-26' || 'ubuntu-latest' }}`, `needs: changes`.
    - Steps are gated with `if: env.RUN == 'true'` and never with a job-level `if`, which `scripts/validate_ci_artifacts.py:597-636` rejects.
    - It runs `bash ios/scripts/select-xcode.sh`, then `swift build` and `swift test --parallel` in `macos/`.
    - It does not run `build_app.sh`: the Whisper model assets are not in the repository, and the `.app` bundle is not what the tests need.
    - It uploads build logs on failure, like `ios-app`.
  - **Graph wiring**: `macos-app` is added to `full-ci` and `allure-report` `needs` and to `LANE_DEPENDENCY_LIMITS` (`{"changes"}`) and the path-filter job list in `scripts/validate_ci_artifacts.py`, with fixtures in `scripts/test_validate_ci_artifacts.py`.
  - **Report generator**: the same slice widens `SCREEN_ID_RE` in `scripts/render_feature_report.py:53` to `[DMX]-\d{2}` (design gap G-7) with a test in `scripts/test_render_feature_report.py`.
  - **Other files**: `ci.yml` is protected by invariants only, not hashed, so no gate-integrity re-record is needed for it. `scripts/validate_ci_artifacts.py` and `render_feature_report.py` are not in `GUARDED_FILES`.
- **Rationale**:
  - Without a lane, every Mac slice would land on a green `Full CI` that never compiled `macos/`. A PR touching only `macos/` turns every stack off (`ci.yml:173-179`).
  - Kit changes must rebuild the Mac because the Mac now depends on the kit.
  - The lane follows the flat-graph rules of the `deploy-and-ci` skill (one edge, to `changes`, which it consumes).
  - macOS runners are already used by `ios-app` (`ci.yml:549`).
- **Alternatives considered**:
  - **Add Mac steps to `ios-app`**: rejected. A Mac-only change would have to flip the `ios` flag and pay for an iOS simulator build, and a failure would be attributed to the wrong client.
  - **Recorded host runs only, as 020 PR-06 does** (`specs/020-weekly-review/plan.md:793`): rejected for 021. The Mac becomes a syncing client of real data, and a host record is evidence for one SHA that the next change silently invalidates. Manual host evidence remains only for what CI cannot see (plan "Test strategy").
  - **Build the `.app` in CI**: rejected. It needs about 140 MB of model assets that are deliberately kept out of git (`macos/README.md:57-62`).

## R4. Mac-only fields the kit lacks

| Mac field (`LocalGTDStore`) | Decision | Where |
|---|---|---|
| `StoredProject.desiredOutcome` (≤ 1000) | **Synced** project field: backend `desired_outcome` (R13) and kit `ProjectRecord.desiredOutcome` with the commands `createProject(… desiredOutcome:)` and `setProjectOutcome` | data-model E1, E4; contracts/kit-commands.md §1 – §2 |
| `StoredProject.state` archived + membership kept, `unarchiveProject` | The kit follows ADR-0020: archive keeps membership; new command `unarchiveProject` | contracts/kit-commands.md §3 |
| `StoredTask.orderKey`, `createdAt` | Already on `TaskRecord` (`orderKey: Int`, `createdAt`). The importer sets them from the legacy values. No reorder command exists on any client or the server, so "manual order" is the create-time `order_key` carried as is (spec inconsistency 1 in the plan) | contracts/mac-legacy-import.md §3 |
| `StoredTask.lastOpenState` | `TaskRecord.lastOpenList` (local only, same meaning) | import mapping |
| `waitingReviews`, `somedayReviews` (task receipts) and `StoredProject.lastReviewedAt / lastReviewDecision / lastReviewedTaskSignature` | **Device-local, never synced (FR-023)**. They move to a Mac-only sidecar file `mac-local.json`, keyed by the server id when the record has one and by the client id otherwise (R5 and data-model E7). They are not kept in `StoreDocument`, whose `base` mirrors the account and whose `outbox` is sent | data-model E7; contracts/mac-app-host.md §4 |
| `idempotency`, `idempotencyReceipts` | Dropped at import. They de-duplicate local retries of commands that already happened; the kit outbox has its own keys | import mapping |
| `StoredTag.state = deleted` | Not imported: a deleted tag has no members and no visible trace. Counted in the import report | import mapping |
| `StoredComment.actorID = "local"` | `CommentRecord.authorID = nil` (the server fills its own on upload) | import mapping |

- **Rationale**:
  - Only the desired outcome must survive sign-in on other clients (FR-028).
  - The review marks are explicitly device-local until 020 replaces them (FR-023, owner-confirmed).
  - Putting device-local marks in the kit's `StoreDocument` would put Mac-only concepts into the shared core used by the iPhone and its widgets, and would collide with 020's planned `StoreDocument` v2 `local` section (`specs/020-weekly-review/contracts/ios-commands.md` §7).
- **Alternatives considered**:
  - **Store review marks in `StoreDocument` under a new `local` key**: rejected for the reasons above, and because it forces a document version bump.
  - **Sync the review marks as task fields**: rejected by FR-023.
  - **Keep the desired outcome device-local**: rejected by the owner's "complete the server" choice (intake §4).

## R5. Migration of `local-gtd.json` into a `StoreDocument`

- **Decision**: a one-time import in the Mac target (`macos/Sources/BrainBuddyMac/LegacyStoreImporter.swift`) runs at launch **before** the workspace opens:
  1. **Lock and read**: take the legacy lock (`lockf` on `.local-gtd.json.lock`, the protocol a pre-021 build uses) and hold it for the whole import, so an older copy still running cannot write midway. Read the file.
  2. **Unreadable or newer file**: if the file is missing, nothing happens. If it does not decode, `version > 1`, or **any** record cannot be converted ("partial read"), the file is unreadable. The design's interpretation of X-05 "partial read" is **confirmed**: nothing is half-imported. Then:
     - the file is left exactly where it is, untouched;
     - the **X-05** alert is shown, with the "corrupt" or "newer version" copy;
     - only after "Continue" or "Show in Finder" does the empty workspace start;
     - the notice is recorded as seen in `mac-local.json`, and an interrupted notice is shown again at the next launch (FR-022).
  3. **Build the document**: otherwise, build the account-less `StoreDocument` in memory. `base` is empty and `account` is nil. The data becomes **outbox operations**, as on the iPhone without an account (`docs/native-ios-app.md:85-90`): every legacy record becomes the `GTDCommand`s that create it, issued at its original instants and applied through `GTDReducer` in interactive mode in a valid order (contracts/mac-legacy-import.md §2), then compacted by `OutboxCompactor`.
  4. **Write**: write `store.json` with `FileDocumentStore` (create, or replace a leftover from an interrupted import: the workspace has never opened on it, see below).
  5. **Verify (FR-021)**: re-read `store.json`, replay it to a `GTDState`, and compare it to the legacy snapshot with the field mapping of contracts/mac-legacy-import.md §3. Every task, project, tag, subtask and comment, plus state, lists, order, dates, priority, membership, outcome and archive state, must match, with exact counts. On a mismatch, `store.json` is deleted, the legacy file stays untouched, and the X-05 "corrupt" path runs with the same copy. This never happens silently.
  6. **Record and back up**: write the review marks to `mac-local.json` and record `legacyImport.state = completed` with the backup name. Only then rename `local-gtd.json` to `local-gtd.backup-<UTC yyyyMMdd'T'HHmmss'Z'>.json` in the same folder. Its content stays untouched.
  7. **Backup retention**: at each launch and after each sign-out, the backup is deleted once **both** are true: 30 days have passed since the import, and a sign-out has happened since the import. FR-021 says "at least 30 days, or until the person signs out, whichever is later". Without a sign-out it is kept.
  - **Idempotent re-runs** (state in `mac-local.json`):

    | state found at launch | action |
    |---|---|
    | no legacy file, no record | nothing (fresh install) |
    | legacy file, no `completed` record | (re)run the import; a leftover `store.json` from an interrupted run is replaced, because the workspace never opens before `completed` is recorded |
    | `completed`, legacy file still at its original name (crash between record and rename) | rename only |
    | `completed`, backup present | retention check only |
    | `unreadable` recorded, notice seen | start normally; the legacy file is never touched again; a later build that can read it may import it only while `store.json` holds no data and no account |

- **Rationale**:
  - **Outbox as the data**: account-less data as outbox operations is exactly the iPhone model. First sign-in then uploads and merges by name with no Mac-specific code (FR-003, US4-3).
  - **Order**: issuing commands at the original instants keeps `createdAt`, `completedAt`, `cancelledAt` and `waitingSince` locally (FR-020).
  - **No silent fallback**: verification before the rename satisfies FR-021's "untouched until verified", and "nothing half-imported" satisfies FR-022.
- **Alternatives considered**:
  - **Write records directly into `base`**: rejected. `base` means "confirmed by the server", so sign-in would never upload them.
  - **Import lazily at first sign-in**: rejected. The account-less Mac must run on the kit too (FR-002).
  - **Delete the legacy file after verification**: rejected by FR-021.
  - **Import the readable records of a partly bad file**: rejected by design X-05 and FR-022 ("must not overwrite"). A half-import would also make the later "recover the file" path ambiguous.
- **Known limit**: the server mints its own `created_at`, `completed_at`, `cancelled_at` and `waiting_since` at upload time; no create or transition accepts a client time (`TaskCreateRequest`, `backend/app/schemas/tasks.py:99-118`).
  - **After the first sign-in**: the pulled base replaces the local times, so the Mac's History shows the sign-in day as the completion day of tasks completed before it. Due dates, order and every other field are kept.
  - The iPhone's account-less upload has the same limit today.
  - Preserving the times would need client-supplied timestamps on the server, which intake §4 lists as out of scope ("changing … how the server stores tasks").
  - This is recorded as an open question for the owner (plan "Open questions"); the default is to accept the limit.

## R6. Two processes and a single instance

- **Decision**:
  - **Store file**: the kit's `DocumentFile` already makes concurrent writers safe, using `flock` on `.store.json.lock`, read-modify-write and a generation bump (`ios/BrainBuddyKit/Sources/BrainBuddyPersistence/DocumentFile.swift:14-19, 64-108`). The legacy file uses its own `lockf` protocol only during the import (R5).
  - **Single instance**: one Brain Buddy Mac process at a time, enforced in `macos/Sources/BrainBuddyMac/SingleInstanceGuard.swift`:
    1. At launch the app takes an exclusive, non-blocking `flock` on `~/Library/Application Support/BrainBuddyMac/.instance.lock` and holds it for the life of the process.
    2. If the lock is held, it looks for the other process with `NSRunningApplication.runningApplications(withBundleIdentifier:)` (bundle id `com.brainbuddy.mac.prototype`, `macos/AppInfo.plist`). If one is found, it activates that window and exits at once.
    3. Otherwise (for example an unbundled `swift run` copy holds the lock) it shows one alert, "Brain Buddy is already open." / "Close the other copy of Brain Buddy, then open it again." with "Quit", and exits.
- **Rationale**:
  - Two processes could share the document safely, but each would run its own `SyncEngine` over one outbox. Both would push the same operations; idempotency keys make that safe on the server, but the result is duplicated traffic and duplicated issues.
  - The spec allows "refuses to start" with the person told in plain words.
  - Bringing the open window forward is the macOS convention and needs no words. The alert covers the case where no window can be brought forward.
  - The lock is released by the kernel on crash, so a stale lock cannot block a launch.
- **Alternatives considered**:
  - **Share safely, with one engine elected through the lock**: rejected. It needs leader hand-over on quit for no user benefit.
  - **`NSRunningApplication` only**: rejected. It misses unbundled copies and races at simultaneous launch.
  - **No guard, relying on the document lock**: rejected for the duplicate-engine reason above.
- **Design gap**: the "already open" alert has no design id. It is a plain system alert with the copy above and is listed as design gap G-8 in the plan for the design owner to confirm.

## R7. Status presentation: one description in the kit

- **Decision**: a pure, Linux-tested presentation in `BrainBuddyCore`, `ios/BrainBuddyKit/Sources/BrainBuddyCore/SyncPresentation.swift` (contracts/sync-status.md). It has four parts:
  - **`SyncSnapshot`**, a value with:
    - account presence and email;
    - `sessionEnded`, `isOnline` and `lastSyncedAt`;
    - `pendingCount` and `oldestPendingAt`;
    - `issueCount` and `failingSince`;
    - `lastFailureReferenceID` and `lastFailureReason`.

    `Workspace` publishes it, built from `StoreDocument`, the engine status and the path monitor.
  - **`SyncStatusDescriber.describe(_:now:device:calendar:)`**: one function returning the line's words, tone (calm or attention), glyph, trailing action (sign in, retry, open issues or none), accessibility label and tooltip. It applies the precedence from design.md ("session ended → rejected changes → failing → offline → changes waiting → synced"), the 10 s waiting rule, the 60 s failing rule, FR-012's relative-time ladder and the "never negative" clock rule.
  - **`SyncActivityIndicator`**: a pure state machine fed `started(at:)` and `finished(at:)`. It answers `isVisible(at:)` and `nextChange(after:)`, with the 1 s show delay and the 0.5 s minimum.
  - **`SyncTiming`**: the constants 1 s, 0.5 s, 10 s, 60 s, the ≤ 60 s refresh, the Mac 15 s tick and the 45 s pull age (R8).

  The apps only render. The Mac renders in `SyncStatusLine.swift` and `SyncStatusPopover.swift` (X-01, X-02). The iPhone renders in `SyncStatusLabel.swift`, which keeps its name but delegates the words (M-01).
  - **Device noun**: `device: .mac | .iPhone` picks "Mac" or "iPhone" for the account-less line and the account-switch refusal. That refusal moves from the engine's hard-coded string (`SyncEngine.swift:195`) to the same copy catalogue.
  - **Failing since**: the engine records `failingSince` (the first failure of the current continuous failure streak of a cycle blocked by the server: 5xx, 429, a redirect, an unreadable 2xx, or a timeout while the path monitor reports a network). It is persisted in `SyncMetadata` so a relaunch does not reset the 60 s clock, and cleared by the next successful cycle.
  - **Engine status**: the engine's existing `.failing` (two failed cycles) stays for Settings detail and back-off only. The line uses `failingSince + 60 s` (FR-014).
- **Rationale**:
  - FR-019 requires identical states and wording on both devices, and design.md "Notes for the plan" asks for the thresholds in shared code.
  - A pure function of a snapshot and `now` is deterministic under Swift Testing on Linux (`ios/AGENTS.md` "Tests").
  - Core is the only module both apps already import that holds no Apple API.
  - `SyncStatus` is declared in Core (`Outbox.swift:156`), so the presentation lives beside it.
- **Alternatives considered**:
  - **Keep wording per app** (today's `SyncStatusLabel.describe` plus a Mac copy): rejected. The two would drift, which is FR-019's failure mode.
  - **Put it in `BrainBuddyWorkspace`**: rejected. It would be the same code, but Workspace is `@MainActor` and harder to drive with a fake clock.
  - **Make `SyncStatus` richer instead of adding a snapshot**: rejected. `SyncStatus` is decoded nowhere but switched over in the iPhone app, and widening its cases would break every switch at once for no gain.

## R8. Sync cadence on Mac, iPhone and web (FR-006, SC-001)

- **Decision**:
  - **Mac**: `macos/Sources/BrainBuddyMac/SyncTriggerSource.swift` drives the workspace with:
    - `.launch`;
    - `.foreground` on `NSApplication.didBecomeActiveNotification`;
    - `localChange` through the workspace's existing 2 s debounce;
    - `networkRestored` from `NWPathMonitor`;
    - `.manual` from "Sync now" / ⌘R;
    - a new `.periodic` trigger fired by a 15 s timer while the app runs.

    The Mac's `SyncConfiguration.pullInterval` is **45 s**. `.foreground`, `.manual` and `.networkRestored` request a pull regardless of age (the engine's existing `pullRequested`, `SyncEngine.swift:119-263`). On `NSApplication.willResignActive` and `willTerminate` it calls `Workspace.flush()`. A periodic cycle with nothing to push and a pull younger than 45 s does no network I/O.
  - **iPhone**: the same `.periodic` tick runs while the scene is active (`ios/BrainBuddy/App/BrainBuddyApp.swift`), with pull age 45 s. Background behaviour is unchanged.
  - **Web**: `useTaskList` and `useProjects` (`frontend/src/api/taskHooks.ts:35, 71`) get `refetchInterval: 45_000` with `refetchIntervalInBackground: false`. The detail query keeps its current focus refetch and autosave conflict handling.
- **Rationale**:
  - SC-001 requires a change to show on the *other open* client within 60 s, in both directions, for Mac ↔ iPhone and Mac ↔ web.
  - The kit has no timer (it checks pull age only when a cycle runs), and the iPhone today pulls only on foreground and a 30-minute background refresh. The web never polls.
  - A 15 s tick with a 45 s pull age bounds staleness at about 60 s (45 + 15), plus the sender's 2 s debounce. A 60 s age with a 60 s tick would allow about 120 s.
  - At today's scale (tens of owners, hundreds of tasks; 020 plan "Scale/Scope") one full pull per client per 45 s is a few requests.
- **Alternatives considered**:
  - **A change feed or push channel**: rejected by intake §4 and spec Assumptions.
  - **Polling only while the Mac is frontmost**: rejected. US1-3 says "the open Mac", and SC-001 is measured with both open, not frontmost.
  - **Leave the iPhone and web untouched**: rejected. SC-001 cannot then be met in the Mac → iPhone and Mac → web directions (spec inconsistency 2 in the plan).

## R9. Backend: ADR-0020 lossless archive, deployed in two steps

- **Decision**:
  - **Two slices**: the archive change ships in two backend slices so that an image rollback is always safe:
    - **PR-02 (tolerant contract)**: `update_task` validates `project_id` only when the PATCH sets it to a *different* project; an unchanged or omitted archived membership is accepted (ADR-0020 "An unrelated Task PATCH may retain its existing archived List membership"). Unarchive, archived listing, `desired_outcome`, the pre-feature marker and `X-Client` logging are additive (R10 – R14). Archive still clears membership in this slice, and it now also sets the pre-feature marker on the project (R12).
    - **PR-03 (lossless archive)**: `archive_project` keeps every member task's `project_id` (all states), changes no task revision, stamps `archived_at` and clears the marker. Tests that assert clearing are flipped (plan "Current repository trace"). ADR-0006 B-29's clearing fix was superseded by ADR-0020.
  - **Assignment rules**: create, Smart Add and assignment to an archived project stay rejected (400 "Task project must be active."). Explicitly clearing membership, or moving to an active project, stays valid.
- **Rationale**:
  - The pre-ADR-0020 `update_task` rejects every edit of a task whose project is archived (`service.py:649-655`). If lossless archive and tolerant validation landed together and the image were rolled back, every task archived meanwhile would become uneditable until roll-forward.
  - With the tolerant reader deployed first, rolling PR-03 back to PR-02 only changes what *future* archives do. Rolling PR-02 back finds no retained memberships, because PR-03 had not shipped.
  - This is the deploy-order rule the architecture rubric treats as blocking when unstated.
- **Alternatives considered**:
  - **One slice**: rejected for the rollback hazard above.
  - **Backfill memberships for old archives**: rejected by ADR-0020 ("cannot be reconstructed and receive no speculative backfill").

## R10. Unarchive endpoint

- **Decision**: `POST /api/projects/{id}/unarchive` (contracts/http.md §3).
  - **Request**: body `{"expected_revision": int}` (`ExpectedRevisionRequest`) and a required `Idempotency-Key`.
  - **Effect**: owner-serialized through `_serialized_write` with the new idempotency command prefix `unarchive_project:` (added to `_apply_idempotent_record` and `_project_result`, `service.py:1145-1203`, and the request to `_request_hash`).
  - **Responses**:
    - **200** `ProjectResponse` with `state: "active"`, `archived_at: null`, the revision bumped and memberships untouched.
    - A project already active → **200** with the project unchanged (no bump).
    - Stale revision → **409** (existing `ConflictError` shape).
    - An active project with the same normalized name → **409** `ConflictError("Project", name)`, the same shape `create_project` returns (`_assert_unique_project_name`, `service.py:1523-1534`).
    - Unknown or foreign id → **404**.
- **Rationale**:
  - It mirrors the archive route's shape, so every client reuses its body, idempotency and conflict handling.
  - Archived names may clash with active ones (uniqueness is among active projects only), so the 409 is reachable and must be explicit.
- **Alternatives considered**:
  - **`PATCH /projects/{id} {"state": "active"}`**: rejected. It turns a field edit into a lifecycle transition, and old clients PATCH name and colour on archived projects.
  - **Auto-rename on clash**: rejected. It is a silent edit of user text.

## R11. Listing archived projects

- **Decision**: `GET /api/projects?state=active|archived|all`.
  - **Default**: `active`, so today's response is unchanged for old clients.
  - **Invalid value**: 422.
  - **Sort order**: unchanged (case-folded name, then id).
  - **Who uses `all`**: the kit's pull uses `state=all`, replacing per-record `GET /projects/{id}` fetches of archived projects (backend ask 7, `docs/native-ios-app.md:346-347`). The web uses `all` too.
- **Rationale**:
  - An archived project with no tasks is referenced by nothing. Without a list, the pull never learns it exists, yet the Mac and iPhone "Archived projects" sections must show it (design example "Tax return 2024"; X-06, M-02, D-01).
  - A query parameter is additive (`docs/api-compatibility.md` "Backward-compatible changes").
- **Alternatives considered**:
  - **A separate `GET /projects/archived`**: rejected. It duplicates the response model and route.
  - **Make the default `all`**: rejected. It is a breaking change for old iPhone builds, which treat every listed project as active.

## R12. Pre-feature archive marker (FR-027)

- **Decision**:
  - **Fields**: `ProjectDocument` gains `archived_at: datetime | None = None` and `archived_before_lossless: bool = False`, both in the JSON payload with no DDL (`extra="ignore"` storage model, `backend/app/schemas/common.py:17-20`).
  - **Writes**:

    | command | `archived_at` | `archived_before_lossless` |
    |---|---|---|
    | archive under PR-02 (still clearing) | stays null | set true (its tasks are detached) |
    | archive under PR-03 (lossless) | set to now | cleared |
    | unarchive | cleared | unchanged, so US5-4 can still say why the unarchived project is empty |
  - **Startup step**: the repository runs an idempotent step at each start, `TaskRepository._mark_detached_archives()` in `backend/app/modules/tasks/repository.py`. It runs in one `BEGIN IMMEDIATE` transaction and sets the marker on every project with `state = 'archived'`, `archived_at` null and the marker false.
    - It needs no ledger row, because it only ever matches archives made by code older than PR-03.
    - It covers every project archived before the feature, and any archived by an older image during a rollback window.
    - Neither the step nor the marker bumps `revision` or `updated_at`, so no client sees a stale-revision 409 because of it.
  - **Display rule** (every client): show the neutral line only when the marker is true **and** the project has no tasks in any state. The copy is the design's decision-2 option B.
- **Rationale**: FR-027 requires the System to know which projects were archived before the feature. The archive instant and the marker together tell the two kinds apart without a schema migration.
- **Alternatives considered**:
  - **A cut-over timestamp in config**: rejected. It is unknowable for projects archived during a rollback, and it is not per project.
  - **Mark only through a one-time ledger step**: rejected for the rollback-window case above.

## R13. Project `desired_outcome`

- **Decision**:
  - **Model**: `desired_outcome: str | None` on `ProjectDocument`, `ProjectCreateRequest`, `ProjectUpdateRequest` and `ProjectResponse`.
  - **Validation**: trimmed; blank becomes null; `max_length=1000`, the Mac's existing limit (`LocalGTDStore.swift:1060, 1201`).
  - **Update semantics**: `update_project` keeps the stored value when the field is omitted, using `model_fields_set` (`service.py:931-941`), so iPhone and web PATCHes of name or colour keep it (FR-028, US5-5). Null clears it.
  - **Export**: automatic, since `account_service.py:265-273` dumps the whole document.
  - **Purge**: automatic, through `delete_all_for_owner`.
  - **Logs**: never logged. The project routes log nothing today, and a pytest log-capture test makes sure it stays that way (FR-030).
- **Rationale**: it is the owner's "complete the server" choice (intake §4), it is additive, and it reuses the existing PATCH and its omit-means-keep semantics.
- **Alternatives considered**:
  - **A separate `PUT /projects/{id}/outcome`**: rejected. It is a second write path and a second revision rule for one optional field.

## R14. Client attribution (FR-031)

- **Decision**:
  - **Header parsing**: `CorrelationIdMiddleware` reads `X-Client` and validates it against `^brainbuddy-(ios|macos)/[0-9A-Za-z.+-]{1,32}$`.
    - The `api_request` and `api_request_failed` log lines gain `client=<ios|macos|web|other>` and `client_version=<value|->`.
    - An absent header logs `web`. A malformed one logs `other` without echoing it.
  - **Kit identity**: the kit's client name becomes injectable as `ClientIdentity(name:version:)` in `BrainBuddyAPI`, with defaults `brainbuddy-ios` and `CFBundleShortVersionString`. The Mac passes `brainbuddy-macos` with its own bundle version, or `dev` when unbundled.
  - **Correlation ids**: the Mac keeps the kit's per-request `X-Correlation-ID`, so a timeout with no reply still has an id that the server log can match (design "Example data"; FR-015).
- **Rationale**:
  - The iPhone already sends `X-Client` (`BrainBuddyAPIClient.swift:308-314`) but the server ignores it.
  - Logging only a closed set of values keeps logs content-free (FR-030, constitution IV).
  - The middleware is the one place every request passes through.
- **Alternatives considered**:
  - **`User-Agent`**: rejected. URLSession's default is unstable and verbose.
  - **A per-route dependency**: rejected. Failures before routing would miss it.

## R15. Feature flag (ADR-0022)

- **Decision**: **no flag**, neither for the archive semantics nor for Mac sync.
- **Rationale**:
  - **Archive semantics**:
    - ADR-0022 requires flags for "significant new capabilities", while "corrections to expected existing behavior do not require a new flag". Lossless archive is an accepted product decision that the Mac already implements and the server has owed since 2026-08-15 (ADR-0020). It is not a new capability.
    - A per-user flag would also be unenforceable offline: an account-less or offline client's reducer must decide alone whether archive keeps membership, and two semantics would make the outbox replay depend on a flag value the device may not know. Replay is deterministic today (`docs/native-ios-app.md:80-84`).
    - Rollback safety comes from the two-step deploy (R9), not from a flag.
  - **Mac sync**:
    - Exposure is already opt-in twice over: the Mac is a locally built app with no distribution channel (spec Assumptions), and nothing is sent until the person signs in (FR-002, FR-029).
    - There is no server surface to gate. The Mac uses the same endpoints as the iPhone, plus unarchive, which every client gets.
  - **iPhone wording and status alignment**: a presentation correction.
- **Alternatives considered**:
  - **A `lossless_project_archive` flag**: rejected for the offline-determinism reason above.
  - **A `mac_sync` server flag**: rejected. It is unenforceable for a client that could simply not ask, and it would gate nothing on the server.

## R16. API compatibility for older iPhone builds

- **Decision**: all server changes are additive under `docs/api-compatibility.md`:
  - a new route (unarchive);
  - a new optional query parameter with an unchanged default;
  - new optional response fields (`desired_outcome`, `archived_at`, `archived_before_lossless`);
  - a new optional request field (`desired_outcome`);
  - a relaxed validation (an unchanged archived membership is accepted where it was rejected).

  The archive endpoint keeps its request, response and statuses; only its side effect changes, as ADR-0020 decided.

  **What an iPhone build without 021 sees**:
  - **Its own archive**: its reducer still clears memberships locally on archive (`Reducer+Organize.swift:56-70`). The next pull's base restores them, because current state = replay(outbox, base).
  - **Archived projects**: pulled one by one by reference, as today. Archived projects without tasks stay invisible to it.
  - **Editing a task in an archived project**: accepted. Its reducer rejects only a *new* assignment (`checkReferences` on `.set`), and the server now accepts the unchanged one.
  - **A project unarchived elsewhere**: appears in `GET /projects` as active, with its tasks.
  - **Its "Archived projects" footer** ("Their tasks stayed in their lists.") becomes imprecise until it updates. Nothing crashes and nothing is dropped (spec edge case "Old iPhone build").

  `docs/api-compatibility.md` is amended in PR-02: its "There is no mobile/iOS client contract yet" (l.5 – 6) is stale, and it gains a dated note naming the iPhone and Mac clients, `X-Client`, and the ADR-0020 behaviour change. A separately versioned API semantic version stays out of scope, because every change here is additive.
- **Rationale**: the ADR-0020 change is the only non-additive effect, and the compatibility rules above show it degrades gracefully.
- **Alternatives considered**:
  - **A versioned `/api/v2` for archive**: rejected. Old clients would then still clear memberships through v1, defeating FR-024 on every client.

## R17. Session credential on macOS (FR-005)

- **Decision**:
  - **Store**: the Mac uses `KeychainSessionTokenStore(service: "app.brainbuddy.mac.session")`, a service of its own (`ios/BrainBuddyKit/Sources/BrainBuddyAPI/SessionTokenStore.swift:130`).
  - **Keychain flavour**: on macOS without `kSecUseDataProtectionKeychain`, the item lives in the login keychain. The data-protection keychain needs a signed application-identifier entitlement, which the ad-hoc-signed local build (`macos/build_app.sh`) does not have.
  - **Rebuild prompt**: after a rebuild changes the ad-hoc signature, macOS may ask once to allow access to the item. That is acceptable for a locally built app (spec Assumptions) and is recorded in `docs/native-macos-app.md`.
  - **Defaults**: the server address uses the iPhone's default and https rule. It is stored in `UserDefaults` key `BrainBuddyAPIURL` as today (ContentView l.18, 219) and edited under X-03 "Advanced".
  - **Sign-out**: sign-out and queued logout are the kit's (`SyncEngine.swift:217-233`, `SyncEngine+Session.swift:34-43`).
- **Rationale**: it satisfies FR-005 (never a plain file or preferences) with no signing work, which the spec excludes.
- **Alternatives considered**:
  - **The data-protection keychain**: rejected. It needs a provisioning profile.
  - **Reuse the iPhone service name**: rejected. A Mac running the iPhone app (iPad-on-Mac) could otherwise share an item.

## R18. Incoming changes never disturb the person (FR-009, US1-5)

- **Decision**:
  - **Stable identity**: rows are identified by kit `EntityID`s, which stay stable across pulls because server records are matched by `serverID` (`docs/native-ios-app.md:91-98`). Selection, scroll anchors and focus are keyed by them, so a pull re-renders in place.
  - **Inline editor**:
    - The editor (explicit Save/Discard) keeps a *baseline* copy of the fields when editing starts and a *draft*.
    - On save it sends a `TaskChanges` containing only the fields where draft ≠ baseline (omit / `null` / value). Fields the person did not touch are omitted, so changes that arrived meanwhile survive, and their own edits win for the fields they changed (per field, FR-011).
    - While editing, incoming values for untouched fields are shown live. Incoming values for touched fields are not applied to the draft.
  - **Drag**: no drag reordering exists on the Mac, so the drag clause of FR-009 has nothing to protect.
- **Rationale**: this is the same per-field rule the outbox already implements (omit / null / value, `docs/native-ios-app.md:114`), and it needs no new sync concept.
- **Alternatives considered**:
  - **Lock the task while editing**: rejected. Offline-first has no lock to take.
  - **Send the whole form**: rejected. It would overwrite fields edited elsewhere, which is the lost-update bug FR-011 forbids.

## R19. Tests, requirement ids and evidence

- **Decision**:
  - **Requirement ids**: every product test names a `021-FR-…` or `021-SC-…` id. Swift tests name it in the `@Test("021-FR-012 …")` display name; Python tests use `test_021_FR_024_…`.
  - **Swift coverage scanning**: the Swift test trees (`ios/BrainBuddyKit/Tests`, `macos/Tests`) are scanned by `scripts/check_requirement_coverage.py` once 020 PR-01 lands. That slice adds `.swift` and both trees (in flight on `claude/020-pr-01-governance`). 021 depends on it rather than editing the guarded script a second time.
  - **Allure**: Allure taxonomy applies to pytest, Vitest and Playwright only. Swift Testing output is not in the Allure report (`ios/README.md` "Known gaps"; `docs/test-allure-taxonomy.md`).
  - **Convergence tests**: SC-001 and SC-002 are proven at logic level by two `Workspace`s, configured as Mac and iPhone clients, against one `BrainBuddyFakeServer` in `BrainBuddyWorkspaceTests`, on Linux. The fake server is not a product, so the Mac package cannot host this test. Both clients run the same kit code, so the logic test is exact for every rule except the Mac's AppKit glue, which the macOS lane tests separately.
  - **Fake-server parity**: the fake server's archive, unarchive, outcome and listing behaviour is pinned to the backend by golden traces. `backend/tests/fixtures/project_archive_traces.json` is run by pytest against the real API and replayed against the fake server in `ios/BrainBuddyKit/Tests/BrainBuddySyncTests/ProjectArchiveTraceReplayTests.swift`, the same technique as 020's traces (`specs/020-weekly-review/plan.md:787`).
- **Rationale**: the CLAUDE.md id rule; the Linux-first test rule of `ios/AGENTS.md`; and a parity mechanism that fails mechanically instead of by review.
- **Alternatives considered**:
  - **Expose the fake server as a product for Mac tests**: rejected. It ships test code to app targets, and it is unnecessary given the above.

## R20. Sequencing with feature 020

020's approved manifest (`specs/020-weekly-review/tasks.md:770-1422`) and the two
in-flight worktrees define what 021 must not collide with. Write-path overlaps:

| 021 slice | 020 slices sharing write paths | rule |
|---|---|---|
| PR-01 CI | none (020 PR-01 edits `scripts/check_requirement_coverage.py` and others, not `ci.yml`, `validate_ci_artifacts.py` or `render_feature_report.py`) | parallel with any 020 wave |
| PR-02, PR-03 backend | PR-02 (in flight: `service.py`, `schemas/tasks.py`, `container.py`, `pyproject.toml`) and PR-15 (`domain.py`, `repository.py`, `service.py`, `api/tasks.py`, `schemas/tasks.py`, `docs/data-retention.md`, `backend/tests/allure_taxonomy.py`) | start after 020 PR-02 lands. Never in flight at the same time as 020 PR-15: whichever is ready first lands first, and the other rebases. Conflicts are confined to `update_task`, `archive_project`, the idempotency prefix tables and `ProjectResponse` / `TaskResponse`, which 020 does not change semantically |
| PR-04, PR-05 kit | PR-03 (`Records.swift`, `Commands.swift`, `Reducer.swift`, `Outbox.swift`, `StoreDocumentCoding.swift`, `WireModels.swift`, `RequestBodies.swift`, `BrainBuddyAPIClient.swift`, `SyncEngine+Pull.swift`, `StoreDocument+Merge.swift`, `Workspace.swift`, fake server), PR-04, PR-08, PR-12 (single kit files) | serialized with each of them; 021 adds only optional `Codable` fields, so it needs **no `StoreDocument` version bump** and does not compete with 020's v1 → v2 step |
| PR-06 web | PR-05, PR-10, PR-13 (`AppShell.tsx`, `TaskListPage.tsx`, `api/taskTypes.ts`, `frontend/tests/allure.fixtures.ts`) | serialized |
| PR-07 iPhone app | PR-04, PR-08, PR-12 (`TaskListScreen.swift`, `SettingsScreen.swift`, `ListsHubScreen.swift`, `BrainBuddyApp.swift`, `docs/native-ios-app.md`, `ios/AGENTS.md`) | serialized |
| PR-08, PR-09 Mac | PR-06 (`ContentView.swift` sidebar, `SidebarEntries.swift`, `macos/Tests/BrainBuddyMacTests/WeeklyReviewRowTests.swift`) | after 020 PR-06 lands (spec Assumptions); PR-08 keeps 020's row and its test |

The validator for `## PR-срезы` checks overlaps only within one feature's manifest,
so this cross-feature rule is a delivery rule in plan.md, not a mechanical one.

## R21. Logging and privacy on the Mac (FR-029, FR-030)

- **Decision**:
  - **No content in logs**: the Mac target never logs or prints task, project or tag text, comments, outcomes or the email. Its only log points are an `os.Logger` (subsystem `com.brainbuddy.mac`) with the import counts, sync trigger names, cycle durations, error classes and reference ids.
  - **No egress before sign-in**: the kit sends nothing without an account (`SyncEngine.runCycle` guards on `account`).
  - **Voice stays local**: voice audio and transcripts never leave `VoiceCapture.swift`, which has no network path (`macos/README.md:128-131`).
  - **Test**: a Mac test asserts that the legacy import's log line for a seeded sentinel title contains only counts.
- **Rationale**: constitution I and IV; FR-029 and FR-030.

## R22. Agent context script

- **Decision**: `.specify/scripts/bash/update-agent-context.sh` is **not run**.
- **Rationale**:
  - `.specify/agent-commands/speckit-plan/SKILL.md` has no agent-context step.
  - `docs/spec-kit-workflow.md` records the `agent-context` extension as not installed because `CLAUDE.md` is hand-maintained.
  - `AGENTS.md:123-128` asks for pruning, not appending.
  - The one line `AGENTS.md` should gain ("macOS app depends on BrainBuddyKit") is written by hand in PR-08.
