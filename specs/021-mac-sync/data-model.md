# Data model: Mac ↔ backend sync (021)

**Feature**: `specs/021-mac-sync/` · **Plan**: [plan.md](plan.md) · **HTTP**:
[contracts/http.md](contracts/http.md) · **Kit**: [contracts/kit-commands.md](contracts/kit-commands.md)
· **Status**: [contracts/sync-status.md](contracts/sync-status.md) · **Import**:
[contracts/mac-legacy-import.md](contracts/mac-legacy-import.md) · **Mac host**:
[contracts/mac-app-host.md](contracts/mac-app-host.md)

## Ownership

- **Server records**: owned by the Tasks module (`backend/app/modules/tasks/`, ADR-0001). They are stored in `<data_dir>/tasks.sqlite3`, `projects` table, JSON `payload` column, and written only under `TaskRepository.command_lock(owner_id)`.
- **Kit records**: owned by `BrainBuddyCore` (`ios/BrainBuddyKit`), and changed only by `GTDReducer`.
- **Mac-only device records**: owned by the Mac app target (`macos/Sources/BrainBuddyMac/`). They are never sent.

No new server table is added. Nothing in this feature adds a column.

## Spec entity → storage map

| spec "Key Entity" | stored as |
|---|---|
| Mac local workspace | kit `StoreDocument` (v1, unchanged version) at `~/Library/Application Support/BrainBuddyMac/store.json` (E5) |
| Waiting change | kit `PendingOperation` in `StoreDocument.outbox` (existing) |
| Sync issue | kit `SyncIssue` in `StoreDocument.issues` (existing) |
| Sync status | kit `SyncSnapshot` (E6, in memory) derived from `StoreDocument.sync` (E5 additions) + engine + path monitor |
| Project (changed) | server `ProjectDocument` (E1) + kit `ProjectRecord` (E3) |
| Mac review marks | Mac sidecar `mac-local.json` (E7) |
| Previous Mac store backup | `~/Library/Application Support/BrainBuddyMac/local-gtd.backup-<UTC>.json` (E8) |
| Session credential (FR-005) | macOS login keychain item, service `app.brainbuddy.mac.session` (E9) |

## E1. `ProjectDocument` additions (`backend/app/modules/tasks/domain.py`)

All fields are optional with defaults, so existing payloads load unchanged (`StorageBaseModel`, `extra="ignore"`). No SQL column is added and no `schema_version` changes.

| field | type | default | written by | invariant |
|---|---|---|---|---|
| `desired_outcome` | `str \| None` (trimmed, 1..1000; blank → `None`) | `None` | create, update (only when present in the request) | never logged |
| `archived_at` | `datetime \| None` | `None` | lossless archive (PR-03) sets it; unarchive clears it | non-null ⇒ `state == "archived"` |
| `archived_before_lossless` | `bool` | `False` | archive while it still clears memberships (PR-02) sets it; the startup step `_mark_detached_archives` sets it; lossless archive (PR-03) clears it; unarchive leaves it | true only for a project whose memberships were cleared by an archive |

`revision` and `updated_at`:

- create, update, archive and unarchive bump them, as today.
- `_mark_detached_archives` does not bump them, because it records history and does not change the project as a person sees it. It never causes a stale-revision 409.

**State transitions** (project):

```text
active ──archive (PR-03: keep members, archived_at=now, marker=false)──▶ archived
archived ──unarchive (archived_at=null, marker unchanged)──▶ active
archived ──archive──▶ archived   (revision and updated_at bump only; archived_at, the marker and members unchanged)
active ──unarchive──▶ active     (200, unchanged, no bump)
```

**Repeat archive** (review c1, F14): archiving a project that is already archived changes only `revision` and `updated_at`, under PR-02 and PR-03 alike. It never stamps `archived_at` and never clears `archived_before_lossless`, so a pre-feature archive keeps the only signal FR-027 relies on. The service checks the current state before it writes the two fields; the server and the fake server have no such guard today.

Task invariants (ADR-0020):

- a task's `project_id` may reference an archived project only if it already referenced it when the project was archived;
- `create_task`, Smart Add and a PATCH that sets `project_id` to an archived project other than the current one are rejected with 400 "Task project must be active.";
- a PATCH that omits `project_id`, or repeats the current archived one, is accepted;
- clearing it (`null`) or moving it to an active project is accepted;
- archive and unarchive change no task's state, list, completion, trash state or revision.

**Response** (`backend/app/schemas/tasks.py` `ProjectResponse`) adds `desired_outcome`, `archived_at` and `archived_before_lossless`. Shapes are in contracts/http.md §2.

**Export and purge**:

- `GET /api/account/export` already writes `tasks/projects.json` as `model_dump(mode="json")` of every project (`backend/app/services/account_service.py:265-273`), so the three fields are exported automatically. A test asserts it (`backend/tests/test_account_export.py`).
- Purge deletes the projects table rows (`repository.py:644-680`; `backend/tests/test_account_deletion.py`).
- `docs/data-retention.md` row "Tasks, projects, tags, subtasks, comments" gains "(including a project's desired outcome)".

## E2. Request models (`backend/app/schemas/tasks.py`)

| model | change |
|---|---|
| `ProjectCreateRequest` | `desired_outcome: str \| None = None`, `max_length=1000` |
| `ProjectUpdateRequest` | `desired_outcome: str \| None` (optional; omitted = keep, `null` = clear) |
| `ExpectedRevisionRequest` | reused unchanged by `POST /projects/{id}/unarchive` |

All of them stay `StrictBaseModel` (`extra="forbid"`), so a client-supplied `id` is still rejected with 422.

## E3. Kit `ProjectRecord` additions (`ios/BrainBuddyKit/Sources/BrainBuddyCore/Records.swift`)

| field | type | default when absent in JSON | source |
|---|---|---|---|
| `desiredOutcome` | `String?` (≤ 1000, trimmed, blank → nil) | nil | reducer (`createProject`, `setProjectOutcome`), pull |
| `archivedAt` | `Date?` | nil | reducer (`archiveProject` stamps the command's issue time; `unarchiveProject` clears it), pull |
| `archivedBeforeLossless` | `Bool` | false | pull only (the server decides it) |

They are decoded with `decodeIfPresent`, so v1 documents written by builds without 021 load unchanged. 021 leaves `StoreDocument.currentVersion` **unchanged**: it is 1 today and becomes 2 if 020 PR-03 lands first, as recommended; 021 adds no migration step either way, and does not compete with 020's v1 → v2 step (research R20; review c2, G43).

Kit invariants (mirroring E1):

- `archiveProject` keeps every task's `projectID`, whereas today the reducer clears it (`Reducer+Organize.swift:56-70`).
- `checkReferences` rejects `.set(archivedProject)` only when it differs from the task's current `projectID`.
- `replayable` downgrades only a *new* reference to an archived project.

Details are in contracts/kit-commands.md §3.

## E4. Kit commands (`ios/BrainBuddyKit/Sources/BrainBuddyCore/Commands.swift`)

| case | change | request |
|---|---|---|
| `createProject` | gains `desiredOutcome: String?` (optional in `Codable`) | `POST /projects` with `desired_outcome` |
| `setProjectOutcome(project:outcome:)` | new | `PATCH /projects/{id}` `{expected_revision, desired_outcome}` |
| `archiveProject` | semantics change (keep membership) | unchanged request |
| `unarchiveProject(project:)` | new | `POST /projects/{id}/unarchive` |

**Source compatibility** (review c2, blocking G01): the two new cases are additive in `Codable` but **source-breaking** for every exhaustive `switch` over `GTDCommand`, in the kit and in the apps. PR-04 therefore carries each such file (contracts/kit-commands.md §9 lists them, including the iPhone app's `ios/BrainBuddy/Screens/Settings/SyncIssuesScreen.swift`). The same holds for the new `GTDValidationError` cases.

`PendingOperation` and `SyncIssue` encode `GTDCommand`. An older build that meets a document with the new cases cannot decode it, but the Mac and iPhone never share a document file, and an iPhone downgrade is not supported (existing `.unsupportedVersion` behaviour covers only the version header). This is stated in contracts/kit-commands.md §6.

## E5. Kit `SyncMetadata` additions (`ios/BrainBuddyKit/Sources/BrainBuddyCore/Outbox.swift`)

| field | type | meaning |
|---|---|---|
| `failingSince` | `Date?` | first failure of the current continuous run of server-blocked cycles; cleared by the next successful cycle; persisted so a relaunch keeps the 60 s clock (FR-014). Kept, not cleared, while the device is offline |
| `lastFailedAttemptAt` | `Date?` | start time of the most recent server-blocked cycle of the current run; cleared with `failingSince`. The line turns to "Couldn't sync" only once an attempt that started at or after `failingSince + 60 s` has failed (FR-014, SC-005), and X-02 / the X-01 tooltip show it as "Last tried 14:35" |
| `lastFailureReferenceID` | `String?` | the `X-Correlation-ID` of the last failed request: the server's `reference_id` when a reply arrived, otherwise the id the client sent (FR-015) |

All three are optional, so existing documents decode unchanged. The time the account was linked is not a new field: the existing `LinkedAccount.linkedAt` (`Outbox.swift:101`, set by the engine at link time, `SyncEngine.swift:173`) is used (review c2, G43). `lastFailure` (existing) keeps the reason text, and its wording is mapped by contracts/sync-status.md §4.

The Mac document lives at `~/Library/Application Support/BrainBuddyMac/store.json`, using the kit's `FileDocumentStore(fileURL:)` in the Mac's existing folder, chmod 0700. Its lock file is `.store.json.lock`.

**Data-retention row** (written by PR-08 into `docs/data-retention.md` as given here):

| what | where and protection | kept until | removed by |
|---|---|---|---|
| **macOS app store document** (the working copy: tasks with notes, due dates, waiting-for, subtasks and comments; projects with their desired outcome; tags; pending changes not yet sent, with their idempotency keys; sync issues with the server's message text and reference id, including a merged project's own desired outcome when the account kept another; the linked account's id, email, display name and server address) | Mac, `~/Library/Application Support/BrainBuddyMac/store.json`, folder 0700 and file 0600; protected at rest only by FileVault when the person has it on; included in Time Machine backups; not in iCloud Drive | Until sign-out deletes it. **Kept through a 401** ("Sign in again to sync"). With no account ("On this Mac"), until the person removes the folder: deleting the app does **not** remove it, because the folder is in the person's Library, unlike the iPhone's App Group container | macOS client sign-out (`docs/native-macos-app.md`) |
| **macOS quarantined store files** (a `store.json` the app could not read, set aside after the person confirmed "Start fresh" in X-09 as `store.unreadable-<UTC>.json` with whatever it held) | same folder, same protection, in Time Machine | Until sign-out removes them (the kit's `removeAll` deletes `store.unreadable-*`), or the person removes the folder | macOS client sign-out (review c2, G15, G26) |
| **macOS import staging file** (`store.import-<attemptID>.json`: a full working copy built from the previous version's file during the one-time import) | same folder, same protection | Exists only during the import: moved to `store.json` once verified, deleted when its attempt resumes or fails, and any other staging file is deleted at the next launch and at sign-out (E7.1 invariant 5) | macOS client (`LegacyStoreImporter`) |

The last sentence of the `docs/data-retention.md` paragraph after the table becomes "The device and browser rows (mobile, web, CRT, iOS and macOS) are the only entries in this table an account purge cannot reach" (`docs/data-retention.md:40`; review c2, G51).

## E6. `SyncSnapshot` (in memory, `BrainBuddyCore/SyncPresentation.swift`)

```text
SyncSnapshot {
  account: none | linked(email)
  sessionEnded: Bool             // engine status needsSignIn
  isOnline: Bool                 // path monitor (Mac NWPathMonitor; iPhone existing)
  isSyncing: Bool                // a cycle is running (feeds SyncActivityIndicator only)
  lastSyncedAt: Date?            // max(lastPullAt, lastPushAt), existing
  pendingCount: Int              // outbox.count
  oldestPendingAt: Date?         // min over the outbox of max(issuedAt, account.linkedAt): when a change became sendable
  initialUploadRemaining: Int    // outbox operations issued before account.linkedAt still unsent (first upload)
  issueCount: Int                // issues.count
  failingSince: Date?            // E5
  lastFailedAttemptAt: Date?     // E5
  lastFailureReferenceID: String?
  lastFailureReason: FailureReason?   // unreachable | serverError | rateLimited | redirected | unreadable
}
```

The Mac-only facts that X-02 and X-04 also show (the pre-upgrade backup's "kept until" date, E8, and a kept previous-version file, E7.1) are not in the shared snapshot: the Mac host reads them from `MacLocalState` and the folder and passes them to the copy catalogue's `popoverBackup`, `popoverLaterFile` and `signOutBackup` (contracts/sync-status.md §3).

Validation:

- `pendingCount ≥ 0`, and `oldestPendingAt` is nil iff `pendingCount == 0`;
- `0 ≤ initialUploadRemaining ≤ pendingCount`;
- `account == none` ⇒ `pendingCount` and `initialUploadRemaining` are reported as 0 to the describer, because account-less, the outbox *is* the data and nothing "waits".

**Why the sendable time** (review c1, F33): the legacy import issues its commands at the records' original dates, and account-less work can be months old. Measured from `issuedAt`, the first sign-in would show "Waiting to sync · 1,284 changes · oldest 213 days" at once, which reads like days of failure. Measured from `max(issuedAt, account.linkedAt)`, the age starts when the account was linked.

## E7. Mac sidecar `mac-local.json` (Mac target only, `MacLocalState.swift`)

Path: `~/Library/Application Support/BrainBuddyMac/mac-local.json`, mode 0600. It is written atomically (temp file, `fsync` of the file and the folder, rename) under its own `flock` (`.mac-local.json.lock`). It is never sent, and it holds **no titles, names, notes, outcomes or email**: only ids, instants, enums, counts, file names and digests keyed by `installSalt` (every digest in this file is an HMAC-SHA-256 with that key, computed in the Mac target with CryptoKit, so none is a fingerprint usable off this Mac; review c2, G50).

```text
MacLocalState {
  version: 1
  installSalt: 32 random bytes        // created with the file; never leaves this Mac
  workspaceFirstWrittenAt: Date?      // set on the first successful write of store.json (WorkspaceHost, Workspace.didPersist)
                                      // and at any launch that finds store.json; never cleared (E7.1 "in use")
  legacyImport: LegacyImportRecord?   // nil only before the first 021 launch decided anything
  legacyCleanupDoneAt: Date?          // LegacyCookieCleanup ran (contracts/mac-app-host.md §1)
  waitingReviews:  [RecordKey: TaskReviewMark]
  somedayReviews:  [RecordKey: TaskReviewMark]
  projectReviews:  [RecordKey: ProjectReviewMark]
  sidebar: { archivedProjectsExpanded: Bool }   // X-06 "state remembered"
}
LegacyImportRecord {
  state: none | inProgress | completed | unreadable | laterFileKept
  decidedAt: Date                     // when this state was recorded
  importerVersion: Int                // the importer's rule version; a later build with a higher one may retry `unreadable`
  attemptID: UUID?                    // inProgress / completed: names the staging file store.import-<attemptID>.json
  importedLegacyDigest: String?       // inProgress / completed / unreadable: keyed digest of the local-gtd.json bytes read
  importedAt: Date?                   // completed
  backupFileName: String?             // completed: "local-gtd.backup-20261006T143400Z.json"
  legacyRenamedAt: Date?              // completed: the imported file was renamed to the backup (review c2, G33)
  backupDeletedAt: Date?              // the E8 rule deleted the backup
  report: { fileName: String, adjustedCount: Int, notCarriedCount: Int }?   // completed: mac-legacy-import §2a
  unreadableReason: corrupt | newerVersion | verificationFailed | nil
  noticeSeenAt: Date?                 // X-05 "Continue" / "Show in Finder"
  signedOutSinceImport: Bool          // FR-021 retention
  laterFile: { digest: String, detectedAt: Date, noticeSeenAt: Date? }?   // FR-033
}
RecordKey        = "s:<serverID>" when the record has a server id, else "c:<client EntityID>"
TaskReviewMark   = { reviewedAt: Date, stamp: String }      // stamp = keyed HMAC of RecordContentForm(task) (below)
ProjectReviewMark= { reviewedAt: Date, decision: keep | actionUpdated | deferred,
                     taskSignature: String }                 // keyed HMAC of RecordContentForm(project's tasks) (below)
```

### E7.1 Import state machine (FR-020 – FR-022, FR-033; review c1 blocking F02)

The import state is explicit and durable, so that a fresh install, a finished import and an interrupted one can be told apart. The importer never writes `store.json` in place: it builds a **staging file** `store.import-<attemptID>.json` in the same folder, verifies it, and only then moves it to `store.json` with an exclusive rename that fails if `store.json` exists. So `store.json` never holds an unverified import, and nothing the importer did not create is ever replaced.

| state | meaning | recorded when |
|---|---|---|
| (no record) | no 021 launch has decided anything yet | — |
| `none` | the first 021 launch found no `local-gtd.json`: a fresh install | at that launch, before the workspace opens |
| `inProgress` | an import attempt (`attemptID`) started | durably (file and folder `fsync`) **before** the staging file is written |
| `completed` | the staging file was verified (FR-021) | before the staging file becomes `store.json` and before the legacy file is renamed |
| `unreadable` | the legacy file could not be imported (FR-022) | before the X-05 notice |
| `laterFileKept` | a previous-version file appeared after the workspace existed (FR-033) | before the X-05 "later file" notice |

**Invariants** (revised in review c2, G06, G10, G26, G33):

1. **`store.json` is created by the importer only through the exclusive rename of its verified staging file, and only when `store.json` does not exist.** The importer never writes into, merges with or replaces an existing `store.json`, empty or not.
2. **A workspace is "in use"** when any of these holds: `store.json` exists; `workspaceFirstWrittenAt` is recorded (so a workspace emptied by a sign-out, whose `store.json` the kit's `destroy` removed, stays in use); the record is `completed` or `laterFileKept`; or the folder holds a backup (`local-gtd.backup-*.json`) or a quarantined `store.unreadable-*` file. The folder checks keep it true when `mac-local.json` is lost. **An import never targets a workspace in use.**
3. **The importer renames only the file it imported** (identified by `importedLegacyDigest`), only after `completed` is durably recorded and `store.json` exists, and with an exclusive rename (`renamex_np` with `RENAME_EXCL`) that never overwrites a file of the backup's name. It records `legacyRenamedAt` right after. It never renames, rewrites or deletes any other `local-gtd.json`.
4. **Every first 021 launch ends in a terminal state** (`none`, `completed`, `unreadable` or `laterFileKept`) before the workspace opens. `inProgress` is never terminal.
5. **Staging files never outlive their purpose.** An attempt deletes its own staging file when it resumes or fails verification. After the terminal decision of every launch, every `store.import-*.json` whose `attemptID` is not the recorded `inProgress` or `completed` attempt is deleted, and sign-out deletes every staging file. This is safe: a staging file only ever copies a legacy file that, by invariant 3, is still in place.
6. The decision is taken while holding the single-instance lock and the legacy `lockf` (contracts/mac-legacy-import.md §1), so no other 021 process and no pre-021 process can write meanwhile.
7. **Fail closed**: a state the table does not name never imports and never renames; a legacy file present in it is treated as a later file.

**Decision table at launch** (first matching row wins; "in use" is invariant 2):

| # | record | `local-gtd.json` | workspace | action |
|---|---|---|---|---|
| 1 | no record, or `none` | absent | any | record `none` if there is no record; open the workspace |
| 2 | no record, or `none` | present | **not** in use | run the import: record `inProgress`, write and verify the staging file, record `completed`, rename staging → `store.json` (exclusive), rename the legacy file to the backup (exclusive), record `legacyRenamedAt`. This also covers a fresh install that was never written to, into which an older folder's file was copied (for example on a new Mac): nothing can be overwritten and the data never reached an account from this Mac |
| 3 | no record, or `none` | present | in use | **later file**: record `laterFileKept` with the file's digest; leave every file untouched; X-05 "later file" unless already seen; never import |
| 4 | `inProgress` | present, digest = `importedLegacyDigest` | `store.json` absent | resume: delete this attempt's staging file and run the import again from the start |
| 5 | `inProgress` | present, digest ≠ `importedLegacyDigest` | `store.json` absent | delete this attempt's staging file; run the import for the file now present (new `attemptID`) |
| 6 | `inProgress` | absent | `store.json` absent | delete this attempt's staging file; record `none` |
| 7 | `inProgress` | any | `store.json` exists | fail closed: `store.json` did not come from this attempt; delete this attempt's staging file; never touch `store.json`; a legacy file present → record `laterFileKept` and show X-05 "later file", otherwise record `none` |
| 8 | `completed`, `legacyRenamedAt` nil | any | `store.json` absent, this attempt's staging file present | finish: rename staging → `store.json` (exclusive), then row 9 |
| 9 | `completed`, `legacyRenamedAt` nil | present, digest = `importedLegacyDigest` | `store.json` exists | crash between the two renames: legacy rename only (exclusive), record `legacyRenamedAt` |
| 10 | `completed` | present, any other case (`legacyRenamedAt` set, or the digest differs) | any: `store.json` present, or absent after a sign-out | **later file**: record `laterFile`; never import, never rename; X-05 "later file" unless already seen; the record stays `completed`. A restored original whose backup the E8 rule deleted lands here, because `legacyRenamedAt` is set |
| 11 | `completed` | absent | any | retention check only (E8) |
| 12 | `unreadable` | present, digest = `importedLegacyDigest` | not in use, and this build's `importerVersion` is higher than the recorded one | retry the import (row 2): a build that fixed the importer can carry the file over while the person has not used the empty workspace |
| 13 | `unreadable` | present, digest = `importedLegacyDigest` | otherwise | nothing: the file stays where it is (FR-022) |
| 14 | `unreadable` or `laterFileKept` | present, any other file | any | record `laterFile` if none is recorded; X-05 "later file" unless already seen; never import |
| 15 | any terminal state | absent | any | nothing |
| 16 | anything else | — | — | invariant 7: never import, never rename; a legacy file present is a later file |

The "later file" notice is shown once per Mac, not once per file version, so an older copy that keeps writing does not bring it back. While a kept file exists, X-02 shows a quiet line with "Show in Finder" (design X-02 "earlier-version file kept"). A kept file is never renamed or deleted by the app.

**Recovery, stated honestly** (review c2, G05): a file that could not be carried over (`unreadable`) stays untouched where it is. A later build with a higher `importerVersion` retries it only while the workspace is not in use (row 12); once the person has written to the empty workspace, carrying it over needs a person-started import, which 021 does not add (spec Clarifications, OQ-2). That is why the importer is made total over every file the old app could write (contracts/mac-legacy-import.md §2a): `unreadable` is left for files that do not decode or come from a newer version, and `verificationFailed` for an importer defect that the tests in §6 guard against. Before the owner's own upgrade, the importer is run on a copy of the real folder (quickstart Scenario 6, step 0).

### E7.2 Review marks

Rules:

- **Stamp** (review c1, F20; split in review c2, G13): `RecordContentForm` in `BrainBuddyCore` (pure, Linux-tested) produces only the **canonical bytes** of a task's user-visible fields: title, notes, state and list, waiting-for, due date, priority, its project's and tags' normalized names, and its subtasks' titles and states, in a fixed, length-prefixed order. It never includes an id, a `RecordKey`, `updatedAt` or any other server-minted time; for a project, the canonical bytes are the sorted canonical bytes of its tasks. The Mac target's `MacLocalState` turns them into the stamp with CryptoKit `HMAC<SHA256>` keyed by `installSalt`. The kit therefore stays dependency-free and Linux-tested, holds no review-mark concept (research R4), and no hashing code is hand-written (research R23). The stamp therefore survives the upload at first sign-in, the `c:` → `s:` re-keying, pulls that change nothing visible, and sign-out followed by sign-in to the same account. The salt makes a stamp meaningless off this Mac.
- **Validity**: a mark is valid while the record's current stamp or signature equals the stored one and `reviewedAt + 7 days > now`. That is the Mac's existing cadence and invalidation rule (`ContentView.swift` l.416, 581, 626; `LocalGTDStore.swift:321-334`), with `revision` replaced by the content stamp.
- **Accepted imprecision**: an edit made elsewhere and then reverted leaves the stamp unchanged, so the mark stays valid. It is harmless.
- **Re-keying**: when a record gains a `serverID` (upload acknowledged), its `c:` key is re-keyed to `s:` on the next sidecar write. Marks therefore survive sign-in (FR-023).
- **Sign-out**: the sidecar is kept. After the next sign-in to the **same** account, `s:` keys and stamps match again, so marks survive sign-out (FR-023).
- **Pruning**: at every launch, marks older than 30 days are pruned, whether or not anyone signed in again. After the first full pull of any account, keys that match no record are pruned too. A signed-out account's `s:` keys therefore leave the sidecar within 30 days.
- **Reviewed-mark changes**: they never touch `StoreDocument`, so they are never an outbox operation (FR-023, FR-029).

**Data-retention row** (PR-08):

| what | where and protection | kept until | removed by |
|---|---|---|---|
| **macOS device state** (`mac-local.json`: review marks keyed by record id with salted content digests, the upgrade record with backup, report and file names and salted digests of the previous-version files it saw, the Archived-projects disclosure state; no titles, names, notes, outcomes or email) | same folder, 0600, FileVault only, in Time Machine | Kept across sign-out. Marks older than 30 days are pruned at each launch; marks of records that no longer exist after a full pull. Until the person removes the folder | macOS client (`MacLocalState`) |

## E8. Previous store backup (FR-021)

`local-gtd.json` is renamed, with its content unchanged, to `local-gtd.backup-<UTC yyyyMMdd'T'HHmmss'Z'>.json` after the import is verified, with an exclusive rename that never overwrites a file of that name (E7.1 invariant 3).

**Deletion rule** (FR-021; revised in review c2, G24, G39, G63). The backup is deleted at a launch or sign-out only when **all** of these hold:

1. `importedAt + 30 days ≤ now`;
2. `signedOutSinceImport == true`;
3. the import report lists no record that could not be carried (`report.notCarriedCount == 0`); otherwise the backup holds the only copy of those records and is never deleted by the app;
4. at a sign-out: the sign-out does not discard operations issued before `account.linkedAt` (`initialUploadRemaining == 0`); a sign-out during the first upload keeps the backup, which is then the only copy of what did not reach the account, until a later qualifying launch or sign-out.

Without a sign-out it is kept (FR-021). The deletion records `backupDeletedAt`, and the import report file is deleted with it.

**What the person is told**:

- While the backup exists and the date `importedAt + 30 days` is in the future, X-04 appends `signOutBackup(until)` and X-02 shows "Backup from before the update · kept until 5 Nov" with "Show in Finder". After that date, a sign-out that keeps the backup (condition 3 or 4) appends the undated form, "A copy of your tasks from before the update stays on this Mac." (added after `/speckit-analyze`).
- When this sign-out will delete it (all four conditions hold at confirm time), X-04 appends `signOutBackupRemoved` ("The copy of your tasks from before the update will also be removed from this Mac."), so the irreversible deletion is never silent.
- Once the date has passed but the backup is kept (no sign-out yet, or condition 3 or 4), X-02 reads "Backup from before the update · removed when you sign out" (or, under condition 3, "kept because some records could not be carried over").
- The Mac host computes these from `MacLocalState` and the folder (E6 note).

**Without the sidecar** (review c2, G63): if `mac-local.json` is lost, the backup's import date is read from the UTC timestamp in its file name, `signedOutSinceImport` is taken as false (so it is kept), and X-02 keeps surfacing it.

An unreadable legacy file, and a previous-version file kept under FR-033, are never renamed or deleted (FR-022, FR-033).

**Import report** (mac-legacy-import §2a): `local-gtd.import-report-<UTC>.txt`, same timestamp as the backup, written only when the import adjusted a value or could not carry a record. It lists each one with its original and resulting value. X-02 shows "Some details changed during the update" with "Show in Finder" while it exists.

**Data-retention rows** (PR-08 writes them into `docs/data-retention.md` as given here):

| what | where and protection | kept until | removed by |
|---|---|---|---|
| **macOS pre-upgrade backup** (`local-gtd.backup-<UTC>.json`: the untouched pre-021 store, with every task, note, comment, project desired outcome and tag the person had before the update) | same folder, 0600, FileVault only, in Time Machine | At least 30 days after the update. Deleted at the first launch or sign-out once 30 days have passed **and** the person has signed out since the update; **kept without a sign-out**, kept while the import report lists a record that could not be carried over, and kept at a sign-out that discards part of the first upload. Deleting the app does not remove it | macOS client (E8 rule) |
| **macOS previous-version files kept as found** (an unreadable `local-gtd.json`, or one an older copy wrote after the update) | same folder, as the older copy left it | Until the person removes it; the app never renames or deletes it (FR-022, FR-033) | the person |
| **macOS import report** (`local-gtd.import-report-<UTC>.txt`: for each value the upgrade adjusted or record it could not carry, the original text and what it became, so it quotes task, project and tag text) | same folder, 0600, FileVault only, in Time Machine | Deleted together with the pre-upgrade backup, under the same rule. Never logged or sent | macOS client (E8 rule) |
| **macOS legacy session cookie** (every `brainbuddy_session` cookie of the pre-021 app, for any host, in `~/Library/HTTPStorages/<bundle id>/`) | macOS shared cookie storage, a plain file | Removed at the first 021 launch, whatever its host; each host's server session is ended then, or by the queued logout when offline (review c1 F36; review c2, G52) | macOS client (`LegacyCookieCleanup`) |
| **macOS legacy HTTP response cache** (responses the pre-021 online mode cached, for example `/auth/me` with the email and task lists, in `~/Library/Caches/com.brainbuddy.mac.prototype/Cache.db*` and `fsCachedData`) | macOS `URLCache.shared`, plain files | Removed at the first 021 launch (`URLCache.shared.removeAllCachedResponses()` plus the files). The 021 transport is ephemeral and caches nothing (review c2, G25) | macOS client (`LegacyCookieCleanup`) |

## E9. Keychain item (FR-005)

| attribute | value |
|---|---|
| class | generic password |
| keychain | the person's **login keychain** (file-based). The data-protection keychain needs a signed application-identifier entitlement that the ad-hoc-signed local build lacks (research R17) |
| service | `app.brainbuddy.mac.session` |
| account | lower-cased server host (kit `KeychainSessionTokenStore`). On macOS the session is stored as numbered items, `<host>`, `<host>#1`, `<host>#2`, … and the **highest-numbered item is the session** (see "Recovery after a rebuild", as delivered 2026-10-08). iOS keeps the one item `<host>` |
| `kSecAttrSynchronizable` | false, set explicitly and asserted by a macOS-lane test: never in iCloud Keychain |
| `kSecAttrAccessible` | not set on macOS: on the login keychain it cannot deliver "this device only", so the store does not claim it. iOS keeps `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` |
| pending logouts | `<service>.pending-logout` (kit). Each holds the raw token until its logout is delivered |

**Disposition** (review c1, F25, F39):

- Protected by the login password and FileVault. Unlike the iPhone item, it **is** carried by Time Machine and Migration Assistant to a restored or migrated Mac.
- Removed on sign-out and on the first 401 (kit behaviour). A pending-logout item keeps the token until the logout reaches the server, then it is removed.
- Deleting the app does not remove it: the login keychain belongs to the person, as Keychain items outlive the iPhone app too. The server session it names still ends at its 30-day expiry or a revocation (data-retention "Sessions" row), and if the app is installed again, its first launch with no linked account removes the item.
- On launch with no linked account, any token left over from earlier is removed (kit `Workspace.live` behaviour, reproduced by `WorkspaceHost`). The one exception is a dry run (`BRAINBUDDY_MAC_DATA_DIR` set, contracts/mac-app-host.md §1): the host then skips this removal and makes no Keychain call until the person signs in inside the dry run, so the real item is never read or removed by a dry run. A sign-out records the token as a pending logout **before** it removes local data, so a crash between the two still ends the server session (contracts/kit-commands.md §4 "Sign-out order"; review c2, G11, G61).
- A Keychain **write** failure at sign-in is a sign-in error with a reference id (design X-03 "error: couldn't save sign-in"); the session the server just opened is ended at once. It is never a silent "Sign in again".
- A Keychain **read** failure other than "not found" (for example access refused after an ad-hoc rebuild) shows "Sign in again to sync" and is logged as the error class `keychain_read_failed`, never with the token or the host.
- **No prompt during routine sync** (review c2, G34): every read by the sync engine and the launch cleanup is **non-interactive** (`kSecUseAuthenticationUI` set to fail, or an `LAContext` with `interactionNotAllowed`), so a rebuilt binary gets `errSecInteractionNotAllowed` instead of a system prompt; that is treated as "Sign in again to sync". Only a sign-in the person started may let macOS show its access prompt. All Keychain calls run off the main actor (the engine is an actor; `WorkspaceHost` runs its launch cleanup in a detached task).
- **Recovery after a rebuild, as delivered** (2026-10-08, PR-09; replaces the earlier "delete and re-add" recovery, which macOS refuses): the file-based login keychain lets another build overwrite an item's data but neither read nor delete it (`errSecInvalidOwnerEdit`, -25244, with no prompt), and refuses a listing that asks for data of all matches (`errSecParam`, -50). So the store never deletes and re-adds an item it did not create:
  - a routine read, or a routine write, of a highest item this build may not read is "Sign in again to sync" (above); nothing is written into it;
  - the person-started sign-in saves the new session as the next number (`<host>#1`, then `#2`, …) when the highest item is one this build may not read: an item this build created and so reads back without a prompt; if that read-back fails the sign-in shows "couldn't save sign-in";
  - sign-out and the launch cleanup delete every item this build may delete, and leave without failing an item it may neither read nor delete;
  - pending logouts are one item each, found by listing attributes and read one by one; an unreadable one is skipped.
  - **Known residual**: an orphaned older item stays in the login keychain, unread and unused, until its server session expires (30 days) or the person deletes it in Keychain Access. No access prompt is ever raised.
- **Recovery after "Deny"**: at a person-started sign-in, an access-denied or interaction-not-allowed status on the existing item deletes that item and adds it again; if macOS refuses the deletion too, X-03 shows "couldn't save sign-in" and `docs/native-macos-app.md` tells the person how to remove the `app.brainbuddy.mac.session` item in Keychain Access.

**Data-retention row** (PR-09):

| what | where and protection | kept until | removed by |
|---|---|---|---|
| **macOS session token** (the opaque `brainbuddy_session` value, one per server host, and any pending-logout copies) | login keychain generic password, service `app.brainbuddy.mac.session`; not synchronizable; protected by the login password and FileVault; **carried by Time Machine and Migration Assistant** to another Mac | Until sign-out or the first 401; a pending-logout copy until its logout is delivered. Deleting the app does not remove it, so a launch with no linked account removes any left over | macOS client (`KeychainSessionTokenStore`); the server-side session follows the Sessions row |

## E10. Legacy snapshot v1 (input only)

This is the shape read by `LegacySnapshot.swift`. It is never written. The field-by-field mapping to kit commands is in contracts/mac-legacy-import.md §3.

```text
Snapshot { version: 1, generation, tasks: [StoredTask], projects: [StoredProject],
           tags: [StoredTag], idempotency, idempotencyReceipts?, waitingReviews?, somedayReviews? }
StoredTask    { id, title, details?, state, lastOpenState?, revision, projectID?, tagIDs,
                dueDate?, priority, waitingFor?, waitingSince?, completedAt?, cancelledAt?,
                orderKey, createdAt, subtasks: [StoredSubtask], comments: [StoredComment] }
StoredSubtask { id, title, state: open|completed|cancelled, orderKey, revision }
StoredComment { id, body, actorID, createdAt, editedAt?, revision }
StoredProject { id, name, color?, state: active|archived, revision, desiredOutcome?,
                lastReviewedAt?, lastReviewDecision?, lastReviewedTaskSignature? }
StoredTag     { id, name, state: active|deleted, revision }
```

## Export and purge summary

| record | export | purge / removal |
|---|---|---|
| `desired_outcome`, `archived_at`, `archived_before_lossless` (server) | `tasks/projects.json` (automatic) | account purge (automatic) |
| Mac `store.json` (account data + outbox) | not in the export (device); see below | sign-out removes the account's data (kit `signOut`), after the X-04 confirmation |
| Mac `mac-local.json` | n/a | kept across sign-out (ids, salted digests); pruned per E7.2 |
| Mac backup `local-gtd.backup-*.json` | n/a | E8 rule |
| Mac previous-version files kept as found | n/a | never by the app (FR-022, FR-033) |
| Mac import report | n/a | with the backup (E8) |
| Mac import staging files, quarantined `store.unreadable-*` | n/a | staging: E7.1 invariant 5; quarantined: sign-out |
| Mac legacy cookie and HTTP cache | n/a | first 021 launch |
| Keychain item | n/a | sign-out, 401; pending logout when delivered |

**Export sentence** (PR-08 adds it to `docs/data-retention.md` "Export contents", beside the iOS one): "Also excluded: **macOS changes that have not reached the server yet**, and everything a Mac holds while it has never been signed in ("On this Mac"). The controller does not hold them. The Mac says so in words ("Offline · 3 changes waiting", "On this Mac · Sign in to sync"). Also excluded: the Mac's device-only records — review marks in `mac-local.json`, the backup from before the update, its import report, and previous-version files kept as found — which are never sent, so the controller does not hold them." (review c2, G51)

**Privacy policy** (review c2, G23): `docs/data-retention.md` requires the user-facing policy to stay in sync with it, so PR-08 also edits `frontend/src/pages/PrivacyPolicyPage.tsx` and its test, as feature 020 did.

- Under "How long we keep it", one new paragraph after the account-deletion paragraph: "The Brain Buddy apps for Mac and iPhone keep a working copy of your tasks on the device until you sign out there, including after a session ends or your account is deleted. On a Mac, deleting the app does not remove that copy. The copy of your tasks from before the Mac update is kept for at least 30 days and until you sign out on that Mac. We cannot erase copies on your devices or in their backups, such as Time Machine; signing out removes the app's copy from that device."
- Under "Your rights", the Erasure line gains: "Erasure covers everything our servers hold. Copies on your devices are removed by signing out on each device."
- `LAST_UPDATED` moves to the PR-08 landing date.
- `PrivacyPolicyPage.test.tsx` asserts both new sentences verbatim and the new date.
