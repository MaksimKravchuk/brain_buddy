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
archived ──archive──▶ archived   (as today: revision bump, members unchanged)
active ──unarchive──▶ active     (200, unchanged, no bump)
```

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
| `failingSince` | `Date?` | first failure of the current continuous run of server-blocked cycles; cleared by the next successful cycle; persisted so a relaunch keeps the 60 s clock (FR-014) |
| `lastFailureReferenceID` | `String?` | the `X-Correlation-ID` of the last failed request: the server's `reference_id` when a reply arrived, otherwise the id the client sent (FR-015) |

Both are optional, so v1 documents decode unchanged. `lastFailure` (existing) keeps the reason text, and its wording is mapped by contracts/sync-status.md §4.

The Mac document lives at `~/Library/Application Support/BrainBuddyMac/store.json`, using the kit's `FileDocumentStore(fileURL:)` in the Mac's existing folder, chmod 0700. Its lock file is `.store.json.lock`.

## E6. `SyncSnapshot` (in memory, `BrainBuddyCore/SyncPresentation.swift`)

```text
SyncSnapshot {
  account: none | linked(email)
  sessionEnded: Bool             // engine status needsSignIn
  isOnline: Bool                 // path monitor (Mac NWPathMonitor; iPhone existing)
  isSyncing: Bool                // a cycle is running (feeds SyncActivityIndicator only)
  lastSyncedAt: Date?            // max(lastPullAt, lastPushAt), existing
  pendingCount: Int              // outbox.count
  oldestPendingAt: Date?         // min(outbox.issuedAt)
  issueCount: Int                // issues.count
  failingSince: Date?            // E5
  lastFailureReferenceID: String?
  lastFailureReason: FailureReason?   // unreachable | serverError | rateLimited | redirected | unreadable
}
```

Validation:

- `pendingCount ≥ 0`, and `oldestPendingAt` is nil iff `pendingCount == 0`;
- `account == none` ⇒ `pendingCount` is reported as 0 to the describer, because account-less, the outbox *is* the data and nothing "waits".

## E7. Mac sidecar `mac-local.json` (Mac target only, `MacLocalState.swift`)

Path: `~/Library/Application Support/BrainBuddyMac/mac-local.json`, mode 0600. It is written atomically (temp file, `fsync`, rename) under its own `flock` (`.mac-local.json.lock`). It is never sent, and it holds **no titles, names, notes, outcomes or email**: only ids, instants, enums and hashes.

```text
MacLocalState {
  version: 1
  legacyImport: {
    state: notStarted | completed | unreadable
    importedAt: Date?
    backupFileName: String?        // "local-gtd.backup-20261006T143400Z.json"
    unreadableReason: corrupt | newerVersion | verificationFailed | nil
    noticeSeenAt: Date?            // X-05 "Continue" / "Show in Finder"
    signedOutSinceImport: Bool     // FR-021 retention
  }
  waitingReviews:  [RecordKey: TaskReviewMark]
  somedayReviews:  [RecordKey: TaskReviewMark]
  projectReviews:  [RecordKey: ProjectReviewMark]
  sidebar: { archivedProjectsExpanded: Bool }   // X-06 "state remembered"
}
RecordKey        = "s:<serverID>" when the record has a server id, else "c:<client EntityID>"
TaskReviewMark   = { reviewedAt: Date, stamp: String }      // stamp = task.updatedAt ISO-8601
ProjectReviewMark= { reviewedAt: Date, decision: keep | actionUpdated | deferred,
                     taskSignature: String }                 // SHA-256 over sorted "<RecordKey>:<updatedAt>" of the project's tasks
```

Rules:

- **Validity**: a mark is valid while the record's current stamp or signature equals the stored one and `reviewedAt + 7 days > now`. That is the Mac's existing cadence and invalidation rule (`ContentView.swift` l.416, 581, 626; `LocalGTDStore.swift:321-334`), with `revision` replaced by the kit's `updatedAt`.
- **Accepted imprecision**: a mark taken while the task has an unsent edit returns to the review queue once after that edit syncs, because `updatedAt` becomes the server's. It is harmless and documented.
- **Re-keying**: when a record gains a `serverID` (upload acknowledged), its `c:` key is re-keyed to `s:` on the next sidecar write. Marks therefore survive sign-in (FR-023).
- **Sign-out**: the sidecar is kept, because it holds ids only. After the next sign-in to the **same** account, `s:` keys match again, so marks survive sign-out (FR-023).
- **Pruning**: after the first full pull of any account, keys that match no record are pruned, and so are marks older than 30 days.
- **Reviewed-mark changes**: they never touch `StoreDocument`, so they are never an outbox operation (FR-023, FR-029).

## E8. Previous store backup (FR-021)

`local-gtd.json` is renamed, with its content unchanged, to `local-gtd.backup-<UTC yyyyMMdd'T'HHmmss'Z'>.json` after the import is verified. It is deleted at a launch or sign-out when `importedAt + 30 days ≤ now` **and** `signedOutSinceImport == true`.

An unreadable legacy file is never renamed or deleted (FR-022).

`docs/data-retention.md` gains rows for the Mac store, the backup, the sidecar and the keychain item (PR-08 and PR-09).

## E9. Keychain item (FR-005)

| attribute | value |
|---|---|
| class | generic password |
| service | `app.brainbuddy.mac.session` |
| account | lower-cased server host (kit `KeychainSessionTokenStore`) |
| pending logouts | `<service>.pending-logout` (kit) |

It is removed on sign-out and on a 401 (kit behaviour). On launch with no linked account, any token left over from earlier is removed (kit `Workspace.live` behaviour, reproduced by `WorkspaceHost`).

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
| Mac `store.json` (account data + outbox) | n/a (device) | sign-out removes the account's data (kit `signOut`), after the X-04 confirmation |
| Mac `mac-local.json` | n/a | kept across sign-out (ids only); pruned per E7 |
| Mac backup `local-gtd.backup-*.json` | n/a | E8 rule |
| Keychain item | n/a | sign-out, 401 |
