# Contract: BrainBuddyKit records, commands, sync and client identity (021)

Applies to `ios/BrainBuddyKit` and binds both the iPhone app and the Mac app. Slices:

- **PR-04**: §1 – §3, §4 "Pull" and "Push", §5, §6 and §7.
- **PR-05**: §4 "Triggers", "Configuration", "Failing clock" and "Account-switch refusal text", together with contracts/sync-status.md. Rules live in `BrainBuddyCore`; the apps never re-check a rule (`ios/AGENTS.md`). Every target keeps building and testing on Linux.

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
| `unarchiveProject(project)` | new | project archived; no **active** project with the same normalized name → else `.duplicateProjectName` | `POST /projects/{id}/unarchive` `{expected_revision}` |

New `GTDValidationError` cases carry user copy in the existing catalogue (`Commands.swift` messages):

- `.outcomeTooLong`: "Keep the desired outcome under 1,000 characters."
- `.duplicateProjectName` (when unarchiving): "Another active project is already called “<name>”. Rename one first."

`Workspace` gains the matching methods:

- `setProjectOutcome(_:outcome:)`
- `unarchiveProject(_:)`
- `apply(_ commands: [GTDCommand])`: validates the whole sequence on a scratch state and appends all of it in **one** document write, or none of it. It serves the Mac's composite flows: Inbox "clarify as project", Waiting "create follow-up", Someday "move to Next with a new title". The server still receives one request per command, in order. Each is idempotent, and a rejected one becomes a sync issue like any other.

## 3. Reducer rules (`Reducer+Organize.swift`, `Reducer+Validation.swift`, `Reducer+Replay.swift`)

| rule | today | after PR-04 (ADR-0020) |
|---|---|---|
| `archiveProject` | clears `projectID` on every task (l.56 – 70) | keeps every task's `projectID`; sets `archivedAt = issuedAt`; changes no task |
| `unarchiveProject` | — | `state = .active`, `archivedAt = nil`; `archivedBeforeLossless` unchanged; no task changes |
| `createTask` / Smart Add naming an archived project | `.projectNotActive` | unchanged. The Mac/iPhone copy for an archived project changes to "Unarchive “<name>” before adding a task to it." (design X-06) |
| `updateTask` with `projectID: .set(p)`, `p` archived | `.projectNotActive` | `.projectNotActive` **only if** `p ≠ task.projectID`; repeating the current archived project is accepted |
| `updateTask` omitting `projectID` on a task in an archived project | accepted | accepted (unchanged) |
| `replayable` (replay mode) | drops any reference to an archived project | drops only a **new** reference; a carried archived membership is kept |
| `renameProject` / `setProjectColor` / `setProjectOutcome` on an archived project | allowed | allowed |

**Merge by name at first sign-in** is unchanged (`Reducer+Organize.swift:22-25`, `Replay.swift:101-139`). When a merged local project carries a `desiredOutcome`, its `createProject` is dropped as today.

- **Survivor has no outcome**: the local outcome is re-issued as `setProjectOutcome` on the survivor, so it is not lost (FR-003, FR-028).
- **Survivor already has an outcome**: the account's outcome wins, and the local one becomes a sync issue: "Kept the desired outcome already on your account for “<name>”." This keeps "nothing is silently dropped" (US2-5).

## 4. Sync engine (`BrainBuddySync/*`)

**Pull** (`SyncEngine+Pull.swift`):

- `GET /projects?state=all` replaces the per-id fetch of referenced archived projects (`docs/native-ios-app.md:183-185`).
- Deleted tags keep the per-id fetch, because the tag endpoint gains no filter.
- Against a server without PR-02, the parameter is ignored (FastAPI ignores unknown query parameters) and the per-id fallback stays for referenced archived projects that are missing from the list.

**Push**:

- `unarchiveProject` 409 duplicate name: becomes a sync issue with the description in §5. It is not adopted the way a create is: the record exists, and only its activation is refused.
- `setProjectOutcome` 409 stale revision: the existing refetch, replay and resend path.

**Triggers** (`BrainBuddySync.swift`):

- `SyncTrigger.periodic` is added.
- `.foreground`, `.manual`, `.networkRestored` and `.periodic` request a pull through the existing `pullRequested`, except that `.periodic` requests one only when the last pull is older than `configuration.pullInterval`.

**"Sync now" is single-flight** (FR-019 as amended in `b83d367`; design X-02 "loading (a sync is running)"):

- `Workspace.syncNow()` never fails or is refused because a cycle is running. A press while a cycle runs either joins that cycle (when it has not yet passed its pull decision) or queues exactly one follow-up cycle with `pullRequested`. Further presses while that follow-up is queued are no-ops.
- Neither app disables "Sync now" because of a running sync. It is disabled only where no sync can run: account-less, offline or session ended (`SyncStatusDescription.syncNowEnabled`, contracts/sync-status.md §2). This also changes the iPhone Settings › Sync button, which is disabled while syncing today (PR-07).

**Configuration** (`SyncConfiguration.swift`):

- `pullInterval` defaults to 60 s, unchanged for callers that do not set it.
- The Mac and iPhone apps pass `SyncTiming.pullAge` (45 s, contracts/sync-status.md §1).

**Failing clock** (`SyncEngine.swift`):

- The engine maintains `SyncMetadata.failingSince` and `lastFailureReferenceID` (data-model E5).
- A cycle blocked by a server-side failure sets `failingSince` if it is nil. Server-side failures are 5xx, 429, a redirect, an unreadable 2xx, or a timeout or connection error while the path monitor reports a network.
- A cycle that completes clears both.
- A network-unreachable error (path monitor offline) does not start the clock: that state is "offline".
- 401 sets `needsSignIn`, as today.

**Account-switch refusal text**: moves from `SyncEngine.swift:195` to the copy catalogue (contracts/sync-status.md §3) with the device noun. `AccountSwitchRefused` carries no text.

## 5. Sync issue descriptions (shared)

The iPhone's `SyncIssuesScreen.describe` (`ios/BrainBuddy/Screens/Settings/SyncIssuesScreen.swift:104-143`) moves into `BrainBuddyCore/SyncIssueDescriber.swift` so the Mac popover (X-02) and the iPhone Sync issues screen use one description. It keeps the existing cases and adds:

| command | "what was attempted" | example "why" |
|---|---|---|
| `unarchiveProject` | "Unarchive project “<name>”" | 409 name: "Another active project is already called “<name>”." · repeated 5xx: "The server kept rejecting this change." |
| `setProjectOutcome` | "Change the desired outcome of “<name>”" | server message |
| `createTask` dropped from an archived project (edge case) | "Add “<title>” to <List>" | "Project “<name>” was archived on another device, so the task was added without a project." |
| `updateTask` on a task deleted elsewhere, or other 404 | existing | "Couldn't save your change to “<title>”: it was deleted on another device." (spec edge case; for tasks the case is unreachable today because no client deletes tasks, see plan "Inconsistencies") |

Quoting stays curly quotes, clipped at 60 characters (`SyncIssuesScreen.swift:238-243`).

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
- `APIError` carries that id as `referenceID` when no response arrived, so a timeout has a reference id that server logs can match (FR-015).
- `SyncEngine.init` and `Workspace.live` gain the identity parameter, defaulting to `.iOS`.

**Document compatibility**: a document written by a 021 build contains the new command cases. An older build reading it fails to decode `GTDCommand` and reports the document unreadable rather than overwriting it (existing rule). That only happens if the person downgrades the app, which no supported path does: the iPhone app and its widget extension ship together, and the Mac's store is its own file.

## 7. Fake server (`BrainBuddyFakeServer/FakeServer+Organize.swift`, `ServerState.swift`)

The fake server mirrors §1 – §5 of contracts/http.md:

- lossless archive, with `archived_at`;
- unarchive, with the duplicate-name 409 and the active no-op;
- `?state=active|archived|all`;
- `desired_outcome` (omit keeps, null clears);
- the `archived_before_lossless` field, settable by a test helper to seed pre-feature archives;
- tolerant `PATCH /tasks/{id}` validation.

**Parity**: golden traces in `backend/tests/fixtures/project_archive_traces.json`. Each trace is a request sequence plus the expected status and response. They pass in pytest against the real API (`backend/tests/test_project_archive_traces.py`) and are replayed against the fake server (`ios/BrainBuddyKit/Tests/BrainBuddySyncTests/ProjectArchiveTraceReplayTests.swift`, a byte-identical copy in `Tests/BrainBuddySyncTests/Resources/`). The fake server therefore cannot drift from the backend on these paths.
