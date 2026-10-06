# Contract: BrainBuddyKit records, commands, sync and client identity (021)

Applies to `ios/BrainBuddyKit` and binds both the iPhone app and the Mac app. Slices:

- **PR-04**: §1 – §3, §4 "Pull" and "Push", §5, §6, §7, §8 and §9's `GTDCommand` and `GTDValidationError` rows (including the iPhone app's `SyncIssuesScreen.swift`).
- **PR-05**: §4 "Triggers", "Periodic ticker", "Foreground in one call", "Configuration", "Failing clock", "Sign-out order", "Session token store on macOS", "Keychain write failure at sign-in", "Account-switch refusal text" and "First upload", and §9's `SyncTrigger` row, together with contracts/sync-status.md.

Rules live in `BrainBuddyCore`; the apps never re-check a rule (`ios/AGENTS.md`). Every target keeps building and testing on Linux.

## 1. Records (`BrainBuddyCore/Records.swift`)

```swift
// shape only
public struct ProjectRecord {
    // existing: id, serverID, serverRevision, name, color, state, createdAt
    public var desiredOutcome: String?          // ≤ 1000, trimmed, blank → nil
    public var archivedAt: Date?
    public var archivedBeforeLossless: Bool     // from the server only; default false
}
```

New keys decode with `decodeIfPresent`. `StoreDocument.currentVersion` stays 1, and `StoreDocumentCoding.migrationStep` gains no case. A test decodes a v1 document written before 021 (fixture in `BrainBuddyPersistenceTests/StoreDocumentCodingTests.swift`).

## 2. Commands (`BrainBuddyCore/Commands.swift`)

| case | payload | validation (interactive) | request (`BrainBuddySync/GTDCommand+Sync.swift`, `BrainBuddyAPI/RequestBodies.swift`) |
|---|---|---|---|
| `createProject` | + `desiredOutcome: String?` | outcome ≤ 1000 → else `.outcomeTooLong` | `POST /projects` `{name, color?, desired_outcome?}` |
| `setProjectOutcome(project, outcome: String?)` | new | project exists (any state); ≤ 1000 | `PATCH /projects/{id}` `{expected_revision, desired_outcome}` |
| `archiveProject(project)` | unchanged | project active | `POST /projects/{id}/archive` |
| `unarchiveProject(project)` | new | project archived; no **active** project with the same normalized name → else `.unarchiveNameInUse(name)` | `POST /projects/{id}/unarchive` `{expected_revision}` |

**These cases are source-breaking** (review c2, blocking G01). Adding them is additive for `Codable`, but every exhaustive `switch` over `GTDCommand`, in the kit and in the apps, stops compiling until it handles them. §9 lists every such file and the slice that carries it; the iPhone app's `SyncIssuesScreen.describe` (`ios/BrainBuddy/Screens/Settings/SyncIssuesScreen.swift:104-142`, no `default`) is one of them and is edited in PR-04, not PR-07.

New `GTDValidationError` cases carry user copy in the existing catalogue (`Commands.swift` messages). They are new cases, so the same rule applies; no app switches over `GTDValidationError` exhaustively today (apps read `.message`; checked 2026-10-06):

- `.outcomeTooLong`: "Keep the desired outcome under 1,000 characters."
- `.unarchiveNameInUse(String)`: "Another active project is already called “<name>”. Rename one first." A **distinct** case: the existing `.duplicateProjectName` ("A project named … already exists.", `Commands.swift:278`) keeps its copy for create, rename and merge, so iPhone copy does not change (review c2, G43).
- `.archiveNotMerged(String)`: the merge issue of §3 (copy in §5).

`Workspace` gains the matching methods:

- `setProjectOutcome(_:outcome:)`
- `unarchiveProject(_:)`
- `apply(_ commands: [GTDCommand])`: validates the whole sequence on a scratch state and appends all of it in **one** document write, or none of it. It serves the Mac's composite flows: Inbox "clarify as project", Waiting "create follow-up", Someday "move to Next with a new title". The server still receives one request per command, in order. Each is idempotent, and a rejected one becomes a sync issue like any other.

## 3. Reducer rules (`Reducer+Organize.swift`, `Reducer+Validation.swift`, `Reducer+Replay.swift`)

| rule | today | after PR-04 (ADR-0020) |
|---|---|---|
| `archiveProject` | clears `projectID` on every task (l.56 – 70) | keeps every task's `projectID`; sets `archivedAt = issuedAt`; changes no task |
| `archiveProject` on a project already archived | goal already holds | unchanged: `alreadySatisfied`; `archivedAt` and `archivedBeforeLossless` are never touched (mirrors http.md §4 "Repeat archive") |
| `unarchiveProject` | — | `state = .active`, `archivedAt = nil`; `archivedBeforeLossless` unchanged; no task changes |
| `createTask` / Smart Add naming an archived project | `.projectNotActive` | unchanged. The Mac/iPhone copy for an archived project changes to "Unarchive “<name>” before adding a task to it." (design X-06) |
| `updateTask` with `projectID: .set(p)`, `p` archived | `.projectNotActive` | `.projectNotActive` **only if** `p ≠ task.projectID`; repeating the current archived project is accepted |
| `updateTask` omitting `projectID` on a task in an archived project | accepted | accepted (unchanged) |
| `replayable` (replay mode) | drops any reference to an archived project | drops only a **new** reference; a carried archived membership is kept |
| `renameProject` / `setProjectColor` / `setProjectOutcome` on an archived project | allowed | allowed |

**Merge by name at first sign-in** (review c1, F03, F15, F37). Merging still happens where it happens today: by replay when a local `createProject` meets an **active** project of the same normalized name (`Reducer+Organize.swift:22-25`), and by sync when the server answers the creation with 409 duplicate name (`Replay.swift:101-139`). The server's uniqueness check is active-only too. What changes is how the rest of the outbox is rewritten, because the old rule assumed clearing archive.

Today `OutboxReplayer.rewritingAfterMerge(_:project:into:)` calls `withdrawing(project:from:)` whenever the outbox also archives the local project. That creates the project's tasks **without a project**, "as the local archive left them". Under lossless archive (FR-024) the local archive left them attached, so this would silently strip the membership of, for example, the legacy import's archived "Old flat" (mac-legacy-import §2) when the account has an active "Old flat". After PR-04:

| local project (in the outbox) | account project with the same normalized name | result |
|---|---|---|
| active | active | merged, as today: references follow the survivor; the local rename or recolour is dropped |
| **archived** by the outbox | active | **merged; membership kept**: every reference follows the survivor, so the tasks are in the account's project and are never created without one. The local `archiveProject` is not applied to the account's project, which other devices use; it is reported as a `RejectedOperation` with the new error `.archiveNotMerged(name)`, which becomes a sync issue (§5). `withdrawing(project:)` is no longer used for projects (it stays for tag deletion, which is a real deletion) |
| active or archived | archived only | not merged: the server creates a separate project (uniqueness is active-only, and ADR-0020 forbids new assignments to an archived project, so joining it is not possible). An archived Mac project therefore stays a separate archived project beside the account's. Documented limit (spec edge case "Same-named archived projects"); not counted as a duplicate under SC-003 |

The stale doc comments on `rewritingAfterMerge` and `withdrawing` are rewritten in the same slice.

**Desired outcome at the merge**: when a merged local project carries a `desiredOutcome`, its `createProject` is dropped as today.

- **Survivor has no outcome**: the local outcome is re-issued as `setProjectOutcome` on the survivor, so it is not lost (FR-003, FR-028).
- **Survivor already has an outcome**: the account's outcome wins, and the local one becomes a sync issue (§5) that carries the **full local outcome text**. The issue's command holds it, the describer never clips it, and X-02 shows it selectable with "Copy outcome" before "Discard outcome" (design X-02 "outcome kept on account"; review c1 F04, F34; review c2, G32). This keeps "nothing is silently dropped" (US2-5, FR-003).
- **A separate `setProjectOutcome(old)` in the outbox** (review c2, G12): `rewritingAfterMerge` would otherwise retarget it onto the survivor through `replacing(project:with:)` and overwrite the account's outcome. After a merge, every `setProjectOutcome(old)` is **dropped** from the rewritten outbox, and the last value among the merged creation's outcome and those commands is the "local outcome" fed into the two rules above. This also covers an outcome edited after a local archive, which compaction never folds across.
- **Compaction**: `setProjectOutcome` folds into an unsent `createProject` of the same project (its `desiredOutcome`), exactly as `updateProject` folds today (`Compaction.swift` `foldProjectEdit`), and never across an `archiveProject`.

**Tests** (`BrainBuddyCoreTests/ReplayTests.swift`, `BrainBuddyWorkspaceTests/FirstSignInMergeTests.swift`, failing first):

- `021-FR-003` / `021-SC-003`: local archived "Old flat" with three tasks (the import's outbox shape) against an account with an active "Old flat": after sign-in, no task has lost its project, all three are in the account's "Old flat", it stays active, and one issue says the archive was not applied. The same through the 409 path.
- `021-FR-003`: local active "Old flat" against an account with only an archived "Old flat": two projects, the local one active.
- `021-SC-003`: local archived "Old flat" against an account with only an archived "Old flat": two archived projects; the duplicate assertion counts active names only, and this case is asserted explicitly.
- `021-FR-003` / `021-FR-028`: both sides have an outcome: the account's stays, and the issue's description contains the local outcome in full (1,000 characters, not clipped).
- `021-FR-003` / `021-FR-028` (G12): a local project created, archived, then given an outcome by a separate `setProjectOutcome`, against an active account project with an outcome: the account's outcome is unchanged after sign-in, no `PATCH` carries the local outcome, and the issue holds the later local value. The same with a survivor without an outcome: the survivor gets the later local value once.
- `021-FR-028` (`CompactionTests`): `setProjectOutcome` after an unsent `createProject` folds into it; after an `archiveProject` it does not.
- `021-SC-003` (G21): the golden `StoreDocument` produced by the real importer from `legacy-populated.json` (`Resources/legacy-import-golden.json`, written in PR-08, contracts/mac-legacy-import.md §6) signs in against overlapping names with 0 duplicate active projects or tags and 0 missing records.

## 4. Sync engine (`BrainBuddySync/*`)

**Pull** (`SyncEngine+Pull.swift`):

- `GET /projects?state=all` replaces the per-id fetch of referenced archived projects (`docs/native-ios-app.md:183-185`).
- Deleted tags keep the per-id fetch, because the tag endpoint gains no filter.
- Against a server without PR-02, the parameter is ignored (FastAPI ignores unknown query parameters) and the per-id fallback stays for referenced archived projects that are missing from the list.

**Push**:

- `unarchiveProject` 409 duplicate name: becomes a sync issue with the description in §5. It is not adopted the way a create is: the record exists, and only its activation is refused. The interactive command already refuses a local name clash at once (`.unarchiveNameInUse`), so this path is reached only when the clash appeared while offline.
- **A server that still clears on archive** (review c2, G62): if an archive the kit pushed returns `archived_before_lossless: true` or `archived_at: null`, the server is older than PR-03 (a rollback). The engine then raises one sync issue ("Your account's server is out of date, so archiving “<name>” removed its tasks from the project.") instead of letting the next pull strip memberships silently. The runbook rule (http.md §8) is to roll PR-03 forward, never back, once PR-04 has shipped.
- **Immediate local revert on that 409** (review c1, F60): the engine re-applies the archived state locally at once instead of waiting for the next pull, and rewrites the operations queued behind the unarchive that newly assign a task to that project: those tasks are created or kept without the project, under their own keys. The one unarchive issue then says how many tasks it affected ("2 tasks you added to it were kept without a project"), instead of one 400 issue per task. Test in `ProjectArchiveSyncTests` (`021-FR-011`, `021-FR-026`): a capture queued behind a refused unarchive produces one issue and no 400.
- `setProjectOutcome` 409 stale revision: the existing refetch, replay and resend path.

**Triggers** (`BrainBuddySync.swift`):

- `SyncTrigger.periodic` is added.
- `.foreground`, `.manual` and `.networkRestored` request a pull through the existing `pullRequested` and kick a cycle, as `.launch` does today. `.manual` also cancels a scheduled retry and runs at once (existing `kick()` behaviour).
- **`.periodic` never sets `pullRequested`** (review c1, F12). It is a no-op (no cycle, no `.status` event, no `.documentChanged`) unless the last pull is at least `pullInterval` old **or** sendable operations wait with no debounce scheduled; and it is always a no-op while a retry is scheduled, so it never shortens the backoff (review c1, F16). When it does run, the cycle decides the pull by age, as every cycle does. A tick with nothing to do therefore causes no status flip, so the iPhone's `WidgetReloadAfterSync` (reload on syncing → idle) fires only on real cycles.

**Periodic ticker** (`BrainBuddySync/PeriodicSyncTicker.swift`, new; review c1, F18): the repeating "while active" timer lives in the kit, not in the apps, so both apps share one tested implementation.

- `PeriodicSyncTicker(interval: SyncTiming.periodicTick, scheduler: SyncScheduler, fire: @Sendable () async -> Void)` with `setActive(_ active: Bool)`. While active it fires every 15 s; inactive, it schedules nothing.
- The Mac sets it active for the life of the process (FR-006); the iPhone sets it active only while the scene is `.active` (FR-032).
- Tests (`BrainBuddySyncTests/PeriodicSyncTickerTests.swift`, `ManualSyncScheduler`, Linux): `021-FR-006`, `021-FR-032`: fires at 15 s, 30 s, 45 s while active; stops when set inactive and fires nothing while inactive; restarts on reactivation; a tick reaches the engine as `.periodic`.

**Foreground in one call** (`Workspace.setForegroundActive(_:)`, new; review c2, G46): the iPhone app has no test target, so the decision "foreground → ticker on and one forced pull; background → ticker off" lives in the kit behind one call that `BrainBuddyApp` makes from its scene-phase handler. `WorkspaceSyncTests` (`021-FR-032`, `021-FR-006`) assert that `true` starts the ticker and requests `.foreground` once, `false` stops the ticker, and repeated calls are idempotent. The iPhone manual line then covers only the one-line wiring. The Mac calls `setForegroundActive(true)` on activation with its ticker kept active for the whole process (contracts/mac-app-host.md §5).

**"Sync now" is single-flight** (FR-019 as amended in `b83d367`; design X-02 "loading (a sync is running)"). The engine already behaves this way (`SyncEngine.syncNow`, `SyncEngine.swift:254-275`: it joins a running cycle or sets `rerunRequested`); 021 keeps it and adds tests (review c2, G43):

- `Workspace.syncNow()` never fails or is refused because a cycle is running. A press while a cycle runs either joins that cycle (when it has not yet passed its pull decision) or queues exactly one follow-up cycle with `pullRequested`. Further presses while that follow-up is queued are no-ops.
- Neither app disables "Sync now" because of a running sync. It is disabled only where no sync can run: account-less, offline or session ended (`SyncStatusDescription.syncNowEnabled`, contracts/sync-status.md §2). This also changes the iPhone Settings › Sync button, which is disabled while syncing today (PR-07).

**Configuration** (`SyncConfiguration.swift`):

- `pullInterval` defaults to 60 s, unchanged for callers that do not set it.
- The Mac and iPhone apps pass `SyncTiming.pullAge` (**30 s**, contracts/sync-status.md §1; review c1, F07, F17). With the 15 s tick, the longest gap between two pulls is under 45 s plus one pull's duration, so a change pushed by the other client shows within about 50 s (research R8).

**Failing clock** (`SyncEngine.swift`; review c1, F13, F16):

- The engine maintains `SyncMetadata.failingSince`, `lastFailedAttemptAt` and `lastFailureReferenceID` (data-model E5).
- A cycle blocked by a server-side failure sets `failingSince` if it is nil, and sets `lastFailedAttemptAt` to the cycle's start. Server-side failures are 5xx, 429, a redirect, an unreadable 2xx, or a timeout or connection error while the path monitor reports a network.
- **Retry cadence in the first minute**: retries keep the existing backoff (2 s, 4 s, 8 s … ±20 %, `SyncConfiguration.retryDelay`), so attempts land at about 2, 6, 14 and 30 s. The engine caps the delay so that one attempt starts at exactly `failingSince + 60 s`. "Couldn't sync" surfaces only if that attempt (or any later one) also fails; a server that recovered within 60 s is found by it, and nothing is shown (SC-005). After that the normal backoff continues up to 300 s.
- A cycle that completes clears all three.
- A network-unreachable error (path monitor offline) does not start the clock: that state is "offline". Going offline **keeps** `failingSince`, so the 60 s clock does not restart when the network returns; the describer shows "offline" while offline (sync-status §3).
- 401 sets `needsSignIn`, as today.

**Sign-out order** (`Workspace.swift`, `SyncEngine.swift`, `BrainBuddySync.swift`; review c1, F59; mechanism fixed in review c2, G11, G61): today `Workspace.signOut` ends the server session and removes the token (`sync.signOut()`, `Workspace.swift:407`) **before** `store.destroy` (l.412), so a local removal failure leaves the account linked with no session, contradicting the approved X-04 error copy ("you're still signed in"). `SyncService` has no pause or resume, so the new order is **one protocol change**, stated here:

- `SyncService.signOut()` is replaced by `signOut(removingLocalDataWith remove: @Sendable () async throws -> Void) async throws`. Its conformers are `SyncEngine` and the test double `Tests/BrainBuddyWorkspaceTests/Support/FakeSyncService.swift` (the only two, `grep ": SyncService"` on 2026-10-06), both in PR-05.
- Inside the engine, in order:
  1. stop scheduling and wait for a running cycle to finish, with the session and token untouched;
  2. **record the current token as a pending logout** (durable, Keychain `<service>.pending-logout`);
  3. run `remove()` (the workspace's `store.destroy` with its unsent-changes check under the store's lock);
  4. on success: remove the token, then send the logout now or leave it pending for the network;
  5. on failure: delete the pending logout recorded in step 2, resume scheduling, rethrow; the person is still signed in and nothing was removed, so the X-04 error copy is true.
- **Crash window**: a crash after step 3 and before step 4 leaves the pending logout of step 2. The next launch has no linked account, removes leftover tokens as today, and `retryPendingLogouts()` ends the server session, so no session outlives the sign-out (FR-005).

Tests in `WorkspaceSyncTests` (`021-FR-018`, `021-FR-005`): a failing removal leaves the token, sends no logout, leaves no pending logout, and the status is not `needsSignIn`; a successful one removes the token and sends or queues the logout; a crash injected between removal and token removal, then a relaunch, sends exactly one logout.

**Session token store on macOS** (`BrainBuddyAPI/SessionTokenStore.swift`; review c1, F25, F39; review c2, G34): `KeychainSessionTokenStore` has never run on macOS. On macOS it no longer sets `kSecAttrAccessible` (on the login keychain it cannot deliver "this device only"), and it sets `kSecAttrSynchronizable = false` explicitly; iOS is unchanged. It gains an `interactive: Bool` option per call: reads by the engine and by launch cleanup are **non-interactive** (`kSecUseAuthenticationUI` = fail, or an `LAContext` with `interactionNotAllowed`), so after a rebuild they return `errSecInteractionNotAllowed` instead of showing a system prompt during routine sync (FR-017); only the sign-in path is interactive. At an interactive sign-in, an access-denied or interaction-not-allowed status on the existing item deletes and re-adds it. A read failure other than "not found" is reported as `keychain_read_failed` to the host's log and treated as no token. For tests, a macOS-only initializer takes a `SecKeychain` to search (contracts/mac-app-host.md §8).

**Keychain write failure at sign-in** (`BrainBuddyAPIClient.swift`, `APIError.swift`, `SyncEngine.swift`, all in PR-05; review c2, G14): today the token is written inside `BrainBuddyAPIClient.exchange` (l.346-356); a failure throws `APIError.tokenStorage` with no reference id and the copy "couldn't read your sign-in … Unlock the device", and the new token is lost, so nobody can end that session. After PR-05:

- when the `Set-Cookie` of a response carries a new token and `setToken` fails, `exchange` first ends that session itself (a `POST /auth/logout` with the issued token, best effort, no retry loop), then throws `APIError.tokenStorage` with `referenceID` = the request's correlation id and the copy "Brain Buddy couldn't save your sign-in on this device. Try again." No new `APIError.Kind` case is added, so no switch changes (§9);
- `SyncEngine.linkAccount` maps it to `SignInFailure` with that reference id, which `Workspace` already surfaces as `WorkspaceError.signInFailed(message, referenceID)`; the Mac sheet shows X-03 "couldn't save sign-in" with "this Mac" from the copy catalogue;
- test in `SyncEngineSessionTests` (`021-FR-005`, `021-FR-015`): a token store whose `setToken` throws gives a sign-in failure with a non-empty reference id, one logout request carrying the issued token, and no linked account.

**Account-switch refusal text**: moves from `SyncEngine.swift:195` to the copy catalogue (contracts/sync-status.md §3) with the device noun. `AccountSwitchRefused` carries no text.

**First upload** (review c1, F33): `syncSnapshot` derives `oldestPendingAt` from `max(issuedAt, account.linkedAt)` and `initialUploadRemaining` from the operations issued before `account.linkedAt`, using the existing `LinkedAccount.linkedAt` (data-model E5, E6; review c2, G43).

## 5. Sync issue descriptions (shared)

The iPhone's `SyncIssuesScreen.describe` (`ios/BrainBuddy/Screens/Settings/SyncIssuesScreen.swift:104-143`) moves into `BrainBuddyCore/SyncIssueDescriber.swift` so the Mac popover (X-02) and the iPhone Sync issues screen use one description. It keeps the existing cases and adds:

| command | "what was attempted" | example "why" |
|---|---|---|
| `unarchiveProject` | "Unarchive project “<name>”" | 409 name: "Another active project is already called “<name>”." plus, when §4's revert rewrote queued captures, "N tasks you added to it were kept without a project." · repeated rejection: "Brain Buddy couldn't unarchive it, so it's still archived. Try Unarchive again later." (review c2, G57) |
| `archiveProject` (repeated rejection) | "Archive project “<name>”" | "Brain Buddy couldn't archive it, so it's still active. Try again later." (review c2, G57). Other commands keep the existing `keptRejectingMessage` ("The server kept rejecting this change.", `SyncEngine+Push.swift:190`) |
| `setProjectOutcome` | "Change the desired outcome of “<name>”" | server message |
| `setProjectOutcome` re-issued at a merge whose survivor already has an outcome (§3) | "Desired outcome for “<name>”" | "Kept the desired outcome already on your account. Yours is below, so you can copy it." + the **full local outcome**, never clipped; X-02 adds "Copy outcome" (review c1, F04, F34) |
| `archiveProject` not applied at a merge (`.archiveNotMerged`, §3) | "Archive project “<name>”" | "Your account already has an active project called “<name>”. This Mac's tasks were added to it, and it stays active." |
| `createTask` dropped from an archived project (edge case) | "Add “<title>” to <List>" | "Project “<name>” was archived on another device, so the task was added without a project." |
| `updateTask` on a task deleted elsewhere, or other 404 | existing | "Couldn't save your change to “<title>”: it was deleted on another device." **Defensive path**: no client deletes a task and the server has no project delete route (only `DELETE /tags/{id}`, `backend/app/api/tasks.py:691`), so for tasks and projects it is reachable only through a foreign or purged record. It is kept for completeness and is not used as an example (review c1, F41, F63) |

Quoting stays curly quotes, clipped at 60 characters (`SyncIssuesScreen.swift:238-243`), except the desired outcome above, which is shown in full. Every description carries the issue's non-empty reference id (`SyncIssueDescriberTests`, `021-FR-015`, `021-SC-004`).

## 6. Client identity (`BrainBuddyAPI/BrainBuddyAPI.swift`, `BrainBuddyAPIClient.swift`)

```swift
public struct ClientIdentity: Sendable, Equatable {
    public var name: String      // "brainbuddy-ios" | "brainbuddy-macos"
    public var version: String   // CFBundleShortVersionString, or "dev"
    public static let iOS: ClientIdentity
    public static func macOS(version: String) -> ClientIdentity
}
```

- `BrainBuddyAPIClient.init` takes `identity: ClientIdentity = .iOS` and sends `X-Client: <name>/<version>`. The constant `clientName` (`BrainBuddyAPI.swift:14`) becomes `ClientIdentity.iOS.name`.
- `X-Correlation-ID` stays one fresh lower-cased UUID per request.
- `APIError` carries that id as `referenceID` when no response arrived, so a timeout has a reference id that server logs can match (FR-015). This already exists (`APIError.transport(_:sentCorrelationID:)`); 021 keeps it and names it in a test (review c2, G43).
- `SyncEngine.init` and `Workspace.live` gain the identity parameter, defaulting to `.iOS`.

**Document compatibility**: a document written by a 021 build contains the new command cases. An older build reading it fails to decode `GTDCommand` and reports the document unreadable rather than overwriting it (existing rule). That only happens if the person downgrades the app, which no supported path does: the iPhone app and its widget extension ship together, and the Mac's store is its own file.

## 7. Fake server (`BrainBuddyFakeServer/FakeServer+Organize.swift`, `ServerState.swift`)

The fake server mirrors §1 – §5 of contracts/http.md:

- lossless archive, with `archived_at`;
- unarchive, with the duplicate-name 409 and the active no-op;
- `?state=active|archived|all`;
- `desired_outcome` (omit keeps, null clears);
- the `archived_before_lossless` field, settable by a test helper to seed pre-feature archives;
- a repeat archive that changes only the revision (http.md §4);
- tolerant `PATCH /tasks/{id}` validation.

**Parity** (review c1, F21, F45, F61): golden traces in `backend/tests/fixtures/project_archive_traces.json`. Each trace is a request sequence plus the expected status and response. They pin:

- archive (lossless after PR-03), and repeat archive of an archived project, including a seeded pre-feature archive (marker stays true, `archived_at` stays null);
- unarchive: 200, active no-op, 409 stale revision, 409 duplicate name, 404 foreign;
- `GET /projects?state=` with `active`, `archived`, `all` and an invalid value (422);
- tolerant `PATCH /tasks/{id}`: omitted, same archived, different archived (400), `null`, active;
- `desired_outcome`: omitted keeps, `null` clears, blank clears.

They pass in pytest against the real API (`backend/tests/test_project_archive_traces.py`, PR-02 and PR-03) and are replayed against the fake server (`ProjectArchiveTraceReplayTests.swift`). The kit copy in `Tests/BrainBuddySyncTests/Resources/` and its `resources:` declaration in `ios/BrainBuddyKit/Package.swift` first appear in **PR-04**, the slice that reads them, so the backend slices write nothing under `ios/` and trigger no TestFlight build. PR-04 also adds a pytest case to `test_project_archive_traces.py` that reads both files from the checkout and asserts byte equality. The landing path runs every stack whatever the diff (`.github/workflows/ci.yml`, "landing path; exercising every stack"), so a drift on either side fails the landing.

## 8. Pure helpers for the Mac views (`BrainBuddyCore`, PR-04)

These keep view logic out of the 4,000-line `ContentView.swift` and make it testable on Linux (review c1, F19, F20, F23).

| helper | does | tests (`BrainBuddyCoreTests`) |
|---|---|---|
| `TaskEditDraft` (`TaskEditDraft.swift`) | holds the editor's baseline and draft; `changes()` returns a `TaskChanges` with only the fields where draft ≠ baseline (omit / `null` / value); `rebased(onto: TaskRecord)` shows incoming values for untouched fields and keeps touched ones | `TaskEditDraftTests` (`021-FR-009`): untouched fields omitted; a touched field sent; an incoming change to an untouched field shown in the draft; an incoming change to a touched field not applied to the draft |
| `SelectionAnchor` (in `TaskEditDraft.swift`) | resolves a selection or scroll anchor by `EntityID` in a new query result, falling back to the nearest surviving neighbour when the record left the list | same file (`021-FR-009`) |
| `RecordContentForm` (`RecordContentForm.swift`) | the canonical, length-prefixed bytes of a task's (or a project's tasks') user-visible fields, never ids or server times (data-model E7.2). No hashing: the Mac target makes the HMAC with CryptoKit (research R23; review c2, G13) | `RecordContentFormTests` (`021-FR-023`): bytes unchanged by a pull that changes only `updatedAt` or `serverID`, by re-keying, and by sign-out and sign-in; changed by an edit of any listed field; no two different field sets give the same bytes (length prefixes) |
| `ListPresentationHold` (`ListPresentationHold.swift`) | FR-009's pointer clause (review c2, G04, G17): given the order on screen, a new query result and a **held** row (the row under the pointer, or the row being edited), returns an order in which the held row keeps its position and every other row takes its new place; the full new order applies when the hold is released (pointer leaves the row, edit ends). Content changes to the held row show in place; a held row that left the list stays, dimmed, until release | `ListPresentationHoldTests` (`021-FR-009`): a pull that moves the hovered row keeps it at its index; release applies the new order; a removed held row stays until release; no hold gives the new order unchanged |
| `ImportCanonicalizer` (`ImportCanonicalizer.swift`) | the import's total field transform (contracts/mac-legacy-import.md §2a), built on `NameNormalizer` and `FieldRules` so it cannot disagree with the reducer | `ImportCanonicalizerTests` (`021-FR-020`): the examples of contracts/mac-legacy-import.md §6, including "Квартира №5", "™" and double spaces |
| `GTDQueries.projectDisplay(_:)` (`Queries+ProjectDisplay.swift`) | for a project: `isArchived`, `acceptsNewTasks` (false when archived), `showsPreLosslessLine` (FR-027: marker true **and** no task in any state), and the "<name> · archived" label | `ProjectDisplayTests` (`021-FR-025`, `021-FR-027`): each combination of state, marker and task count |

The Mac (X-06) and the iPhone (M-02) render `projectDisplay` and never re-derive the rule. The web implements the same rule in `ArchivedProjectNotice.tsx` with the same cases in Vitest. A `Workspace` test against the fake server (`BrainBuddyWorkspaceTests/FirstSignInMergeTests.swift`, `021-FR-023`) takes the canonical bytes behind a valid Waiting, Someday and Project mark, signs in with upload, pulls, and asserts the stamps are unchanged; then signs out and in to the same account and asserts the same. Another (`WorkspaceCommandTests`, `021-FR-009`) edits field A locally while a pull changes A and B, saves, and asserts that only A was sent, B shows the incoming value and A the local one, and that every `EntityID` is unchanged across the pull.

## 9. Adding a case to a public kit enum (review c2, blocking G01)

**Rule**: a slice that adds a case to a public enum of the kit carries, in its own path list, **every file that switches over that enum exhaustively**, in the kit (sources and tests), in the iPhone app (`ios/BrainBuddy`), the widgets (`ios/BrainBuddyWidgets`), the shared intents (`ios/Shared`) and the Mac (`macos/`), and makes each compile in the same slice. The Linux `ios-kit` lane never compiles the app targets; the `ios-app` lane does, on every `^ios/` change and on every landing, so a missed app switch fails the slice's exact-SHA CI. This is what broke 020 PR-03's Xcode build on `SyncIssuesScreen.swift`. `/speckit-tasks` re-runs the search below for every new case and adds what it finds to the manifest.

**How to find them**: `grep -rn "switch" --include=*.swift ios/BrainBuddyKit ios/BrainBuddy ios/BrainBuddyWidgets ios/Shared macos` narrowed to the enum's values, then checking each switch for a `default`; equivalently, every file that matches one existing case label of the enum (for `GTDCommand`, `case .archiveProject`).

**The new cases in 021 and their consumers** (searched 2026-10-06 at `95ce8de`):

| enum (slice) | new cases | files with an exhaustive or case-listing switch, all carried by that slice |
|---|---|---|
| `GTDCommand` (PR-04) | `setProjectOutcome`, `unarchiveProject` | kit: `BrainBuddyCore/Commands.swift`, `Reducer.swift` (dispatch, l.24), `Reducer+Replay.swift` (l.32), `Compaction.swift` (fold and barrier switches, l.42 – 328), `Replay.swift` (l.108 – 253); `BrainBuddySync/GTDCommand+Sync.swift` (l.17 – 140), `PushPlanner.swift` (l.97), `SyncEngine+Push.swift` (l.352), `SyncEngine+Pull.swift` (l.180), `StoreDocument+Merge.swift` (l.263); `BrainBuddyAPI/RequestBodies.swift`. Fake server: `ServerState.swift`, `FakeServer+Organize.swift`, `FakeServerRecords.swift` (`ProjectRow` / `projectDTO` gain the three fields), `FakeServer+Tasks.swift` (tolerant PATCH). Kit tests: `Tests/BrainBuddySyncTests/Support/RandomCommands.swift` (has a `default`; new cases added to the generator so the property tests exercise them). **iPhone app: `ios/BrainBuddy/Screens/Settings/SyncIssuesScreen.swift`** (`describe`, l.104-142, no `default`): PR-04 makes it delegate to the kit's `SyncIssueDescriber`, which PR-04 adds. Widgets, `ios/Shared`, `macos/`: none (the Mac uses its own types until PR-08) |
| `GTDValidationError` (PR-04) | `outcomeTooLong`, `unarchiveNameInUse`, `archiveNotMerged` | kit: `BrainBuddyCore/Commands.swift` (`message`). Apps: none switch over it (they read `.message`: `TaskCommandRunner.swift:43`, `SharedWorkspace.swift:109`) |
| `SyncTrigger` (PR-05) | `periodic` | kit: `BrainBuddySync/SyncEngine.swift` (`request`, l.241). Apps: none |
| `APIError.Kind` | none added: the Keychain write failure reuses `.tokenStorage` (§4) | — |
| `SyncStatus` | none added (research R7 keeps it unchanged; `SyncStatusLabel.swift:40` and `SettingsScreen.swift:177` switch over it) | — |

New stored properties on public structs (`ProjectRecord`, `SyncMetadata`, `CreateProject`) get defaulted initializer parameters and `decodeIfPresent`, so constructors in the apps compile unchanged; they are additive, unlike the cases above.
