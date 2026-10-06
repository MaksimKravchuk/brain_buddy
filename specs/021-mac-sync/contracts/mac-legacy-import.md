# Contract: importing the pre-021 Mac store (FR-020 – FR-023, FR-033, US4-1, US4-2, US4-4, SC-003)

**Files**: `macos/Sources/BrainBuddyMac/LegacySnapshot.swift` (decoder of data-model E10), `macos/Sources/BrainBuddyMac/LegacyStoreImporter.swift` (plan, apply, verify, rename) and the X-05 alert in `macos/Sources/BrainBuddyMac/UpgradeNotice.swift`.

**Slice**: PR-08.

**Tests**: `macos/Tests/BrainBuddyMacTests/LegacyStoreImporterTests.swift`, with synthetic fixtures under `macos/Tests/BrainBuddyMacTests/Resources/`:

- `legacy-populated.json`, using the design's example data;
- `legacy-corrupt.json`;
- `legacy-newer.json`.

No real data is used (constitution I).

## 1. When it runs

At launch, after `SingleInstanceGuard` (contracts/mac-app-host.md §1) and **before** `Workspace.load()`, holding the single-instance lock and the legacy `lockf` (on `.local-gtd.json.lock`, the protocol a pre-021 build uses) for the whole decision and import.

**State machine** (review c1, blocking F02): the import state is explicit and durable in `mac-local.json` (`legacyImport`, data-model E7.1), with the states `none`, `inProgress`, `completed`, `unreadable` and `laterFileKept`, and the launch decision table there is normative. In short:

- the import runs only at a first 021 launch, and only when `store.json` does not exist;
- `inProgress` is recorded durably before anything is written;
- the import is built in a staging file `store.import-<attemptID>.json`, verified (§3), recorded `completed`, and only then moved to `store.json` with an exclusive rename that fails if `store.json` exists. So the workspace never opens on an unverified import, and no `store.json` is ever replaced;
- only then is the imported legacy file (identified by its digest) renamed to the backup.

**A previous-version file that appears later** (FR-033): an older copy launched after the update, a Time Machine restore, a moved file or a deleted `mac-local.json` can put a `local-gtd.json` beside a workspace in use. It is never imported, merged or written over, and never renamed or deleted. The person is told once (design X-05 "later file"), and X-02 keeps a quiet line with "Show in Finder" while the file exists (data-model E7.1).

While the import runs for longer than 300 ms, the window shows static list placeholders (X-05 "loading"). No progress text is shown.

## 2. Command plan (legacy records → kit commands)

The import builds the account-less document by applying `GTDCommand`s through `GTDReducer` in **interactive** mode, with `issuedAt` set to the original instants. Interactive mode means any rule violation fails the import, which is then treated as unreadable.

**No compaction** (review c1, F38): the import's outbox is **not** passed through `OutboxCompactor`. Compaction may fold a move into an unsent creation, after which the reducer stamps `waitingSince` with the creation's time (`Compaction.swift:24-28`, `foldMove`), and it changes `orderKey` and a comment's `editedAt`. The importer issues those operations deliberately, and §3 verifies them exactly, so the outbox stays as issued. Edits the person makes later are compacted by the kit as usual.

The order is chosen so that every command is valid when applied and each list keeps the Mac's cross-project order (review c1, F58):

1. **Tags**: `createTag` for each `state == active` tag, issued at the import time, because the legacy tag has no timestamp.
2. **Name-clashing archived projects** (an archived project whose normalized name equals an active project's), one at a time, in legacy order, before their active namesake exists:
   1. `createProject(name, color, desiredOutcome)`, issued at the earliest `createdAt` among its tasks, or the import time when it has none;
   2. that project's tasks (step 4), in their legacy order;
   3. `archiveProject`, issued at the import time. It is lossless under §3 of kit-commands, so the tasks keep it.

   Their tasks therefore lead their lists. This is the one accepted reordering, because two active projects may not share a name, and §3 expects exactly this sequence.
3. **Every other project**, active and archived, in legacy order: `createProject(name, color, desiredOutcome)`.
4. **All remaining tasks in one global order**, sorted by `(list, orderKey, createdAt, id)` across projects, so that the reducer's create-time `orderKey` (end of list) and the server's upload order reproduce the Mac's order within each list:
   1. `createTask` into `lastOpenState ?? state` (an open list), with title, details, projectID, tagIDs (active tags only), dueDate, priority and waitingFor (when Waiting), issued at `createdAt`;
   2. when the legacy `waitingSince` differs from `createdAt`: `createTask` into Inbox at `createdAt`, then `transitionTask(.move(.waiting, waitingFor))` at `waitingSince`;
   3. `createSubtask` per subtask in `orderKey` order, then `transitionSubtask` for completed and cancelled ones;
   4. `createComment(body)` at `createdAt`. The edited text is the stored body; `editedAt` is not reproduced, because the kit has no command that sets it (spec Assumptions);
   5. terminal tasks: `transitionTask(.complete)` at `completedAt`, or `.cancel` at `cancelledAt`.
5. **The other archived projects**: `archiveProject` each, issued at the import time, after all their tasks exist.
6. **Records not imported**:
   - deleted tags;
   - `idempotency` and `idempotencyReceipts`;
   - a comment's `editedAt` marker.

   Each is counted in the import report. The review marks go to the sidecar (§4), not to the document.

A legacy id is never sent. Kit records get fresh `EntityID`s, and the importer keeps a legacy id → client id map in memory, used for §3 and §4.

**At first sign-in**, an archived Mac project whose name matches an active account project merges into it under kit-commands §3 "Merge by name": its tasks keep the account's project and a sync issue says the archive was not applied. One that matches only an archived account project stays separate (spec edge case "Same-named archived projects").

## 3. Verification (FR-021 "verified")

After writing the staging file, the importer re-reads it, replays its outbox to a `GTDState`, and checks every pair through the id map. Any mismatch fails the import with `verificationFailed`: the staging file is deleted, the legacy file stays untouched, and X-05 "couldn't carry over" runs.

| legacy | kit current state | equality |
|---|---|---|
| task count by state | `GTDState.tasks` | exact |
| `title`, `details`, `state`, `lastOpenState` | `title`, `details`, `state`, `lastOpenList` | exact |
| `projectID`, `tagIDs` (active tags) | mapped `projectID`, `tagIDs` | exact through the map |
| `dueDate`, `priority`, `waitingFor`, `waitingSince` | same | exact (dates to the second); holds because the outbox is not compacted |
| `completedAt`, `cancelledAt`, `createdAt` | same | to the second |
| order of each open list **across projects** | `GTDQueries` manual sort of the list | identical sequence, with step 2's clashing archived projects' tasks first |
| order within each project | `GTDQueries` manual sort | identical sequence |
| subtasks (title, state, order) | `subtasks` | exact |
| comments (body, order) | `comments` | exact; `editedAt` is not compared (not carried, spec Assumptions) |
| projects (name, colour, state, `desiredOutcome`) | `ProjectRecord` | exact |
| active tags (name) | `TagRecord` | exact |

The report holds counts only and is logged with `os.Logger`: tasks, projects, tags, subtasks, comments, skipped deleted tags, skipped comment edit markers, review marks and duration. It never holds a title, a path, a file name or a digest (FR-030, research R21; review c1 F51).

## 4. Review marks → sidecar (FR-023)

| legacy | sidecar (data-model E7.2) |
|---|---|
| `waitingReviews[taskID] = {taskRevision, reviewedAt}` | `waitingReviews["c:<clientID>"] = {reviewedAt, stamp: RecordContentStamp.task(<imported task>)}`, only when the legacy receipt was still valid (its `taskRevision` equals the task's revision); an invalid receipt is dropped, which is exactly what the Mac would have shown |
| `somedayReviews[...]` | same rule |
| project `lastReviewedAt`, `lastReviewDecision`, `lastReviewedTaskSignature` | `projectReviews["c:<clientID>"] = {reviewedAt, decision, taskSignature: RecordContentStamp.project(<imported tasks>)}`, only when the legacy signature matched the legacy tasks (the project was not "changed since review") |

So a mark that was valid before the upgrade is valid after it, and a mark that was due is still due (US4-1 "review marks are also present").

## 5. Unreadable store (FR-022, design X-05)

| cause | `unreadableReason` | X-05 copy |
|---|---|---|
| JSON does not decode, a required field is missing, or any record fails §2 ("partial read", design interpretation **confirmed**) | `corrupt` | "Brain Buddy couldn't read your earlier tasks" / "The file from the previous version was left exactly as it was. It's here:" / path / "Brain Buddy will start with an empty workspace. Keep the file if you'd like help recovering it." |
| the file was read but §3 found a difference: an importer defect, not a bad file (review c1, F38) | `verificationFailed` | "Brain Buddy couldn't carry over your earlier tasks" / "Your file is fine and was left exactly as it was. It's here:" / path / "This is a problem in Brain Buddy. Brain Buddy will start with an empty workspace; keep the file so a later version can carry it over." (design X-05 "error: couldn't carry over") |
| `version > 1` | `newerVersion` | "They were saved by a newer version of Brain Buddy, so this version left the file exactly as it was." / "Install the newer version to open the file again." |
| a previous-version file appeared after the workspace existed (FR-033, data-model E7.1) | — (`laterFileKept` / `laterFile`) | "Brain Buddy found tasks from the previous version" / "An older copy of Brain Buddy saved tasks on this Mac after the update. They were not added here, and the file was left exactly as it was. It's here:" / path / "Your current tasks are unchanged." (design X-05 "later file") |

**Recovery** (review c1, F38): an import failure never strands data. The legacy file is kept, and a later build that fixes the importer may import it while `store.json` does not exist (data-model E7.1). Importing it into a workspace already in use needs a person-started action, which 021 does not add (owner question OQ-2).

**How the alert behaves**:

- App-modal alert before the workspace opens. The path is selectable.
- "Continue" is the default; "Show in Finder" reveals the file, then behaves like Continue. Esc is not mapped.
- `noticeSeenAt` is recorded on either button.
- A quit while the alert is open records nothing, so it shows again next launch.

**What happens to the file**:

- It is never renamed, rewritten or deleted.
- The staging file of a failed verification is deleted before the alert; `store.json` was never written.

## 6. Tests (named with requirement ids)

- **Populated fixture** (`021-FR-020`, `021-SC-003`): imports with every §3 equality. It contains archived projects with tasks, an archived project whose name equals an active one, desired outcomes, Waiting, Someday and project review marks, subtasks in three states, edited comments, completed and cancelled tasks with `lastOpenState`, and a deleted tag. It also contains (review c1, F38, F58):
  - a Waiting task whose `waitingSince` differs from its `createdAt` (verified to the second);
  - a comment with `editedAt` (body carried, marker counted as skipped);
  - a Next list whose tasks from three projects and no project interleave by `orderKey` (verified as one sequence across projects).
- **Import outbox shape** (`021-FR-003`, `021-FR-020`): the archived "Old flat" with three tasks produces `createProject`, three `createTask` and `archiveProject` in that order and nothing compacted, which is the input of the kit's first-sign-in merge test (kit-commands §3; the fake server is not a product, so the merge itself is tested in the kit).
- **Corrupt, newer and partial fixtures** (`021-FR-022`): the legacy file's bytes are unchanged after the run, and neither a staging file nor `store.json` remains. The "partial" fixture has one task referencing a missing project.
- **Verification failure** (`021-FR-022`): an injected §3 mismatch records `verificationFailed`, shows the "couldn't carry over" copy, and leaves the legacy bytes unchanged and no `store.json`.
- **Crashes** (`021-FR-021`): injected failures after `inProgress` is recorded, after the staging write, after verification, after `completed` is recorded, and between the two renames each recover on the next run with no duplicate records, the legacy bytes unchanged until the rename, and `store.json` either absent or verified.
- **Import state is explicit** (`021-FR-033`): a first launch with no legacy file records `none` durably before the workspace opens; a completed import records `completed` with the legacy digest and backup name; `inProgress` is on disk before the staging file exists.
- **A previous-version file never overwrites a workspace in use** (`021-FR-033`; each asserts that the bytes of `store.json`, the backup and the found `local-gtd.json` are unchanged, that no import ran, and that the X-05 "later file" notice shows exactly once):
  - **appears after a fresh install**: record `none`, `store.json` with records and a linked account, then a `local-gtd.json` appears;
  - **`mac-local.json` removed**: `store.json` exists, the sidecar is deleted, and a `local-gtd.json` is present;
  - **old build writes a new file after the rename**: record `completed`, the backup present, and a new `local-gtd.json` with a different digest;
  - **`inProgress` record but a `store.json` the attempt did not create** (for example a restored folder): `store.json` untouched, the attempt's staging file deleted;
  - **an older copy keeps writing**: a second, different `local-gtd.json` on the next launch shows no second notice, and X-02's line remains.
- **Crash between record and rename** (`021-FR-021`): record `completed`, `local-gtd.json` with the imported digest, no backup: only the rename happens.
- **Backup retention** (`021-FR-021`):

  | days since import | sign-out since import | backup |
  |---|---|---|
  | 29 | yes | kept |
  | 31 | no | kept |
  | 31 | yes | deleted |

- **Old copy still running** (`021-FR-020`): a second process holding the legacy `lockf` blocks the import until it releases. After the rename, that process's next write fails with its existing 409 and writes nothing.
- **Review marks** (`021-FR-023`): marks survive import, and a due mark is still due. Their survival across the first sign-in's upload and across sign-out and sign-in to the same account is tested in the kit against the fake server (`RecordContentStamp`, kit-commands §3).
- **Privacy** (`021-FR-030`; review c1 F51): with a sentinel home folder (for example `/Users/sentinel-home-7f3a`), the populated, corrupt, newer, verification-failed and later-file paths are driven. The captured `os.Logger` lines hold counts, durations and enum values only: no sentinel title, no `/Users/`, no `local-gtd`, no backup or staging file name, and no run of 32 or more hexadecimal characters. `unreadableReason` is logged as its enum name.
