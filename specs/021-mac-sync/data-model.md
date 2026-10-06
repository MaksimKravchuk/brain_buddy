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

They are decoded with `decodeIfPresent`, so v1 documents written by builds without 021 load unchanged. `StoreDocument.currentVersion` stays **1**: there is no migration step, and no conflict with 020's v1 → v2 step (research R20).

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

`PendingOperation` and `SyncIssue` encode `GTDCommand`. An older build that meets a document with the new cases cannot decode it, but the Mac and iPhone never share a document file, and an iPhone downgrade is not supported (existing `.unsupportedVersion` behaviour covers only the version header). This is stated in contracts/kit-commands.md §6.

## E5. Kit `SyncMetadata` additions (`ios/BrainBuddyKit/Sources/BrainBuddyCore/Outbox.swift`)

| field | type | meaning |
|---|---|---|
| `failingSince` | `Date?` | first failure of the current continuous run of server-blocked cycles; cleared by the next successful cycle; persisted so a relaunch keeps the 60 s clock (FR-014). Kept, not cleared, while the device is offline |
| `lastFailedAttemptAt` | `Date?` | start time of the most recent server-blocked cycle of the current run; cleared with `failingSince`. The line turns to "Couldn't sync" only once an attempt that started at or after `failingSince + 60 s` has failed (FR-014, SC-005), and X-02 / the X-01 tooltip show it as "Last tried 14:35" |
| `lastFailureReferenceID` | `String?` | the `X-Correlation-ID` of the last failed request: the server's `reference_id` when a reply arrived, otherwise the id the client sent (FR-015) |
| `accountLinkedAt` | `Date?` | when the current account was linked on this device. An outbox operation issued earlier (account-less or imported data) became sendable only then (E6 `oldestPendingAt`, `initialUploadRemaining`) |

All four are optional, so v1 documents decode unchanged. `lastFailure` (existing) keeps the reason text, and its wording is mapped by contracts/sync-status.md §4.

The Mac document lives at `~/Library/Application Support/BrainBuddyMac/store.json`, using the kit's `FileDocumentStore(fileURL:)` in the Mac's existing folder, chmod 0700. Its lock file is `.store.json.lock`.

**Data-retention row** (written by PR-08 into `docs/data-retention.md` as given here):

| what | where and protection | kept until | removed by |
|---|---|---|---|
| **macOS app store document** (the working copy: tasks with notes, due dates, waiting-for, subtasks and comments; projects with their desired outcome; tags; pending changes not yet sent, with their idempotency keys; sync issues with the server's message text and reference id, including a merged project's own desired outcome when the account kept another; the linked account's id, email and server address) | Mac, `~/Library/Application Support/BrainBuddyMac/store.json`, folder 0700 and file 0600; protected at rest only by FileVault when the person has it on; included in Time Machine backups; not in iCloud Drive | Until sign-out deletes it. **Kept through a 401** ("Sign in again to sync"). With no account ("On this Mac"), until the person removes the folder: deleting the app does **not** remove it, because the folder is in the person's Library, unlike the iPhone's App Group container | macOS client sign-out (`docs/native-macos-app.md`) |

## E6. `SyncSnapshot` (in memory, `BrainBuddyCore/SyncPresentation.swift`)

```text
SyncSnapshot {
  account: none | linked(email)
  sessionEnded: Bool             // engine status needsSignIn
  isOnline: Bool                 // path monitor (Mac NWPathMonitor; iPhone existing)
  isSyncing: Bool                // a cycle is running (feeds SyncActivityIndicator only)
  lastSyncedAt: Date?            // max(lastPullAt, lastPushAt), existing
  pendingCount: Int              // outbox.count
  oldestPendingAt: Date?         // min over the outbox of max(issuedAt, accountLinkedAt): when a change became sendable
  initialUploadRemaining: Int    // outbox operations issued before accountLinkedAt still unsent (first upload)
  issueCount: Int                // issues.count
  failingSince: Date?            // E5
  lastFailedAttemptAt: Date?     // E5
  lastFailureReferenceID: String?
  lastFailureReason: FailureReason?   // unreachable | serverError | rateLimited | redirected | unreadable
  backupKeptUntil: Date?         // Mac only: importedAt + 30 days while the pre-upgrade backup exists (E8)
  laterLegacyFilePresent: Bool   // Mac only: a kept previous-version file (E7 `laterFile`, FR-033)
}
```

Validation:

- `pendingCount ≥ 0`, and `oldestPendingAt` is nil iff `pendingCount == 0`;
- `0 ≤ initialUploadRemaining ≤ pendingCount`;
- `account == none` ⇒ `pendingCount` and `initialUploadRemaining` are reported as 0 to the describer, because account-less, the outbox *is* the data and nothing "waits".

**Why the sendable time** (review c1, F33): the legacy import issues its commands at the records' original dates, and account-less work can be months old. Measured from `issuedAt`, the first sign-in would show "Waiting to sync · 1,284 changes · oldest 213 days" at once, which reads like days of failure. Measured from `max(issuedAt, accountLinkedAt)`, the age starts when the account was linked.

## E7. Mac sidecar `mac-local.json` (Mac target only, `MacLocalState.swift`)

Path: `~/Library/Application Support/BrainBuddyMac/mac-local.json`, mode 0600. It is written atomically (temp file, `fsync` of the file and the folder, rename) under its own `flock` (`.mac-local.json.lock`). It is never sent, and it holds **no titles, names, notes, outcomes or email**: only ids, instants, enums, file names and salted digests.

```text
MacLocalState {
  version: 1
  installSalt: 32 random bytes        // created with the file; never leaves this Mac
  legacyImport: LegacyImportRecord?   // nil only before the first 021 launch decided anything
  waitingReviews:  [RecordKey: TaskReviewMark]
  somedayReviews:  [RecordKey: TaskReviewMark]
  projectReviews:  [RecordKey: ProjectReviewMark]
  sidebar: { archivedProjectsExpanded: Bool }   // X-06 "state remembered"
}
LegacyImportRecord {
  state: none | inProgress | completed | unreadable | laterFileKept
  decidedAt: Date                     // when this state was recorded
  attemptID: UUID?                    // inProgress / completed: names the staging file store.import-<attemptID>.json
  importedLegacyDigest: String?       // inProgress / completed / unreadable: SHA-256 of the local-gtd.json bytes read
  importedAt: Date?                   // completed
  backupFileName: String?             // completed: "local-gtd.backup-20261006T143400Z.json"
  unreadableReason: corrupt | newerVersion | verificationFailed | nil
  noticeSeenAt: Date?                 // X-05 "Continue" / "Show in Finder"
  signedOutSinceImport: Bool          // FR-021 retention
  laterFile: { digest: String, detectedAt: Date, noticeSeenAt: Date? }?   // FR-033
}
RecordKey        = "s:<serverID>" when the record has a server id, else "c:<client EntityID>"
TaskReviewMark   = { reviewedAt: Date, stamp: String }      // stamp = RecordContentStamp.task (below)
ProjectReviewMark= { reviewedAt: Date, decision: keep | actionUpdated | deferred,
                     taskSignature: String }                 // RecordContentStamp.project (below)
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

**Invariants**:

1. **`store.json` is created by the importer only through the exclusive rename of its verified staging file, and only when `store.json` does not exist.** The importer never writes into, merges with or replaces an existing `store.json`, empty or not.
2. **A workspace is "in use" once `store.json` exists.** An import never targets a workspace in use. This holds even when `mac-local.json` is lost, because the check reads the folder, not the record.
3. **The importer renames only the file it imported** (identified by `importedLegacyDigest`), and only after `completed` is durably recorded and `store.json` exists. It never renames, rewrites or deletes any other `local-gtd.json`.
4. **Every first 021 launch ends in a terminal state** (`none`, `completed`, `unreadable` or `laterFileKept`) before the workspace opens. `inProgress` is never terminal.
5. **A staging file is deleted only by its own attempt** (the `attemptID` in its name) when that attempt is resumed or fails verification.
6. The decision is taken while holding the single-instance lock and the legacy `lockf` (contracts/mac-legacy-import.md §1), so no other 021 process and no pre-021 process can write meanwhile.

**Decision table at launch** (first matching row wins):

| record | `local-gtd.json` | `store.json` | action |
|---|---|---|---|
| no record | absent | any | record `none`; open the workspace |
| no record | present | absent | run the import: record `inProgress`, write and verify the staging file, record `completed`, rename staging → `store.json` (exclusive), rename the legacy file to the backup |
| no record | present | exists | **workspace in use** (for example `mac-local.json` was deleted, or the folder was restored): record `laterFileKept`; leave both files untouched; X-05 "later file" |
| `inProgress` | present, digest = `importedLegacyDigest` | absent | resume: delete this attempt's staging file and run the import again from the start |
| `inProgress` | present, digest ≠ `importedLegacyDigest` | absent | delete this attempt's staging file and run the import for the file now present (new `attemptID`) |
| `inProgress` | absent | absent | delete this attempt's staging file; record `none` |
| `inProgress` | any | exists | fail closed: `store.json` did not come from this attempt; delete this attempt's staging file; never touch `store.json`; if a legacy file is present, record `laterFileKept` and show X-05 "later file", otherwise record `none` |
| `completed` | any | absent, staging file present | finish: rename staging → `store.json` (exclusive), then the legacy rename if the imported file is still at its name |
| `completed` | present, digest = `importedLegacyDigest`, no backup file | exists | crash between the two renames: legacy rename only |
| `completed` | present, any other case (a backup exists, or the digest differs) | exists | an older copy wrote a new file after the rename: record `laterFile`; leave it untouched; X-05 "later file" unless already seen; the record stays `completed` |
| `completed` | absent | exists | retention check only (E8) |
| `unreadable` | present, digest = `importedLegacyDigest` | any | nothing: the unreadable file stays where it is (FR-022) |
| `none`, `unreadable` or `laterFileKept` | present, any other file | any | record `laterFile` if none is recorded; X-05 "later file" unless already seen; never import |
| any terminal state | absent | any | nothing |

The "later file" notice is shown once per Mac, not once per file version, so an older copy that keeps writing does not bring it back. While a kept file exists, X-02 shows a quiet line with "Show in Finder" (design X-02 "earlier-version file kept"). A kept file is never renamed or deleted by the app.

A later build that can read a file recorded `unreadable` may import it only under invariant 1, that is while `store.json` does not exist. Otherwise the file stays kept and surfaced. A person-started "add these tasks" import into a workspace in use is not part of 021 (owner question OQ-2 in `review-c1-disposition.md`).

### E7.2 Review marks

Rules:

- **Stamp** (review c1, F20): `RecordContentStamp` in `BrainBuddyCore` (pure, Linux-tested) computes `task` as an HMAC-SHA-256, keyed by `installSalt`, over the task's user-visible fields: title, notes, state and list, waiting-for, due date, priority, its project's and tags' normalized names, and its subtasks' titles and states. It never includes an id, a `RecordKey`, `updatedAt` or any other server-minted time. `project` is the same HMAC over the sorted task stamps of the project's tasks. The stamp therefore survives the upload at first sign-in, the `c:` → `s:` re-keying, pulls that change nothing visible, and sign-out followed by sign-in to the same account. The salt makes a stamp meaningless off this Mac.
- **Validity**: a mark is valid while the record's current stamp or signature equals the stored one and `reviewedAt + 7 days > now`. That is the Mac's existing cadence and invalidation rule (`ContentView.swift` l.416, 581, 626; `LocalGTDStore.swift:321-334`), with `revision` replaced by the content stamp.
- **Accepted imprecision**: an edit made elsewhere and then reverted leaves the stamp unchanged, so the mark stays valid. It is harmless.
- **Re-keying**: when a record gains a `serverID` (upload acknowledged), its `c:` key is re-keyed to `s:` on the next sidecar write. Marks therefore survive sign-in (FR-023).
- **Sign-out**: the sidecar is kept. After the next sign-in to the **same** account, `s:` keys and stamps match again, so marks survive sign-out (FR-023).
- **Pruning**: at every launch, marks older than 30 days are pruned, whether or not anyone signed in again. After the first full pull of any account, keys that match no record are pruned too. A signed-out account's `s:` keys therefore leave the sidecar within 30 days.
- **Reviewed-mark changes**: they never touch `StoreDocument`, so they are never an outbox operation (FR-023, FR-029).

**Data-retention row** (PR-08):

| what | where and protection | kept until | removed by |
|---|---|---|---|
| **macOS device state** (`mac-local.json`: review marks keyed by record id with salted content digests, the upgrade record with backup and file names, the Archived-projects disclosure state; no titles, names, notes, outcomes or email) | same folder, 0600, FileVault only, in Time Machine | Kept across sign-out. Marks older than 30 days are pruned at each launch; marks of records that no longer exist after a full pull. Until the person removes the folder | macOS client (`MacLocalState`) |

## E8. Previous store backup (FR-021)

`local-gtd.json` is renamed, with its content unchanged, to `local-gtd.backup-<UTC yyyyMMdd'T'HHmmss'Z'>.json` after the import is verified. It is deleted at a launch or sign-out when `importedAt + 30 days ≤ now` **and** `signedOutSinceImport == true`. Without a sign-out it is kept (FR-021).

While it exists, `SyncSnapshot.backupKeptUntil` is `importedAt + 30 days` (E6). The X-04 sign-out confirmation then adds one sentence with that date, and X-02 shows a quiet line with "Show in Finder" (design X-04 "backup kept", X-02 "pre-upgrade backup"; review c1 F27, F62).

An unreadable legacy file, and a previous-version file kept under FR-033, are never renamed or deleted (FR-022, FR-033).

**Data-retention rows** (PR-08 writes them into `docs/data-retention.md` as given here):

| what | where and protection | kept until | removed by |
|---|---|---|---|
| **macOS pre-upgrade backup** (`local-gtd.backup-<UTC>.json`: the untouched pre-021 store, with every task, note, comment, project desired outcome and tag the person had before the update) | same folder, 0600, FileVault only, in Time Machine | At least 30 days after the update. Deleted at the first launch or sign-out once 30 days have passed **and** the person has signed out since the update; **kept without a sign-out**. Deleting the app does not remove it | macOS client (E8 rule) |
| **macOS previous-version files kept as found** (an unreadable `local-gtd.json`, or one an older copy wrote after the update) | same folder, as the older copy left it | Until the person removes it; the app never renames or deletes it (FR-022, FR-033) | the person |
| **macOS legacy session cookie** (the pre-021 app's `brainbuddy_session` cookie in `~/Library/HTTPStorages/<bundle id>/`) | macOS shared cookie storage, a plain file | Removed at the first 021 launch; its server session is ended then, or by the queued logout when offline (review c1 F36) | macOS client (`LegacyCookieCleanup`) |

## E9. Keychain item (FR-005)

| attribute | value |
|---|---|
| class | generic password |
| keychain | the person's **login keychain** (file-based). The data-protection keychain needs a signed application-identifier entitlement that the ad-hoc-signed local build lacks (research R17) |
| service | `app.brainbuddy.mac.session` |
| account | lower-cased server host (kit `KeychainSessionTokenStore`) |
| `kSecAttrSynchronizable` | false, set explicitly and asserted by a macOS-lane test: never in iCloud Keychain |
| `kSecAttrAccessible` | not set on macOS: on the login keychain it cannot deliver "this device only", so the store does not claim it. iOS keeps `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` |
| pending logouts | `<service>.pending-logout` (kit). Each holds the raw token until its logout is delivered |

**Disposition** (review c1, F25, F39):

- Protected by the login password and FileVault. Unlike the iPhone item, it **is** carried by Time Machine and Migration Assistant to a restored or migrated Mac.
- Removed on sign-out and on the first 401 (kit behaviour). A pending-logout item keeps the token until the logout reaches the server, then it is removed.
- On launch with no linked account, any token left over from earlier is removed (kit `Workspace.live` behaviour, reproduced by `WorkspaceHost`).
- A Keychain **write** failure at sign-in is a sign-in error with a reference id (design X-03 "error: couldn't save sign-in"); the session the server just opened is ended at once. It is never a silent "Sign in again".
- A Keychain **read** failure other than "not found" (for example access refused after an ad-hoc rebuild) shows "Sign in again to sync" and is logged as the error class `keychain_read_failed`, never with the token or the host.

**Data-retention row** (PR-09):

| what | where and protection | kept until | removed by |
|---|---|---|---|
| **macOS session token** (the opaque `brainbuddy_session` value, one per server host, and any pending-logout copies) | login keychain generic password, service `app.brainbuddy.mac.session`; not synchronizable; protected by the login password and FileVault; **carried by Time Machine and Migration Assistant** to another Mac | Until sign-out or the first 401; a pending-logout copy until its logout is delivered. A launch with no linked account removes any left over | macOS client (`KeychainSessionTokenStore`); the server-side session follows the Sessions row |

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
| Keychain item | n/a | sign-out, 401; pending logout when delivered |

**Export sentence** (PR-08 adds it to `docs/data-retention.md` "Export contents", beside the iOS one): "Also excluded: **macOS changes that have not reached the server yet**, and everything a Mac holds while it has never been signed in ("On this Mac"). The controller does not hold them. The Mac says so in words ("Offline · 3 changes waiting", "On this Mac · Sign in to sync")."
