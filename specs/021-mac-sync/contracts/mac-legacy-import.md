# Contract: importing the pre-021 Mac store (FR-020 – FR-023, US4-1, US4-2, US4-4, SC-003)

**Files**: `macos/Sources/BrainBuddyMac/LegacySnapshot.swift` (decoder of data-model E10), `macos/Sources/BrainBuddyMac/LegacyStoreImporter.swift` (plan, apply, verify, rename) and the X-05 alert in `macos/Sources/BrainBuddyMac/UpgradeNotice.swift`.

**Slice**: PR-08.

**Tests**: `macos/Tests/BrainBuddyMacTests/LegacyStoreImporterTests.swift`, with synthetic fixtures under `macos/Tests/BrainBuddyMacTests/Resources/`:

- `legacy-populated.json`, using the design's example data;
- `legacy-corrupt.json`;
- `legacy-newer.json`.

No real data is used (constitution I).

## 1. When it runs

At launch, after `SingleInstanceGuard` (contracts/mac-app-host.md §1) and **before** `Workspace.load()`. The workspace never opens on a `store.json` produced by an unfinished import. The state machine and its idempotent re-runs are in research R5 and data-model E7.

While the import runs for longer than 300 ms, the window shows static list placeholders (X-05 "loading"). No progress text is shown.

## 2. Command plan (legacy records → kit commands)

The import builds the account-less document by applying `GTDCommand`s through `GTDReducer` in **interactive** mode, with `issuedAt` set to the original instants. Interactive mode means any rule violation fails the import, which is then treated as unreadable. The result is then `OutboxCompactor`-compacted. The order is chosen so that every command is valid when applied:

1. **Tags**: `createTag` for each `state == active` tag, issued at the import time, because the legacy tag has no timestamp.
2. **Archived projects**, one at a time, in legacy order:
   1. `createProject(name, color, desiredOutcome)`, issued at the earliest `createdAt` among its tasks, or the import time when it has none;
   2. that project's tasks (step 4);
   3. `archiveProject`, issued at the import time. It is lossless under §3 of kit-commands, so the tasks keep it.

   An archived name may equal an active one, so archived projects are created and archived before any active project with the same name exists.
3. **Active projects**: `createProject(name, color, desiredOutcome)`.
4. **Tasks** of each project, then the projectless tasks, sorted by `(state group, orderKey, createdAt, id)` so that the reducer's create-time `orderKey` (end of list) reproduces the legacy order:
   1. `createTask` into `lastOpenState ?? state` (an open list), with title, details, projectID, tagIDs (active tags only), dueDate, priority and waitingFor (when Waiting), issued at `createdAt`;
   2. when the legacy `waitingSince` differs from `createdAt`: `createTask` into Inbox at `createdAt`, then `transitionTask(.move(.waiting, waitingFor))` at `waitingSince`;
   3. `createSubtask` per subtask in `orderKey` order, then `transitionSubtask` for completed and cancelled ones;
   4. `createComment(body)` at `createdAt`. The edited text is the stored body; `editedAt` is not reproduced, because the kit has no command that sets it;
   5. terminal tasks: `transitionTask(.complete)` at `completedAt`, or `.cancel` at `cancelledAt`.
5. **Records not imported**:
   - deleted tags;
   - `idempotency` and `idempotencyReceipts`.

   They are counted in the import report. The review marks go to the sidecar (§4), not to the document.

A legacy id is never sent. Kit records get fresh `EntityID`s, and the importer keeps a legacy id → client id map in memory, used for §3 and §4.

## 3. Verification (FR-021 "verified")

After writing, the importer re-reads `store.json`, replays its outbox to a `GTDState`, and checks every pair through the id map. Any mismatch fails the import (research R5 step 5).

| legacy | kit current state | equality |
|---|---|---|
| task count by state | `GTDState.tasks` | exact |
| `title`, `details`, `state`, `lastOpenState` | `title`, `details`, `state`, `lastOpenList` | exact |
| `projectID`, `tagIDs` (active tags) | mapped `projectID`, `tagIDs` | exact through the map |
| `dueDate`, `priority`, `waitingFor`, `waitingSince` | same | exact (dates to the second) |
| `completedAt`, `cancelledAt`, `createdAt` | same | to the second |
| order within each list and project | `GTDQueries` manual sort | identical sequence |
| subtasks (title, state, order) | `subtasks` | exact |
| comments (body, order) | `comments` | exact |
| projects (name, colour, state, `desiredOutcome`) | `ProjectRecord` | exact |
| active tags (name) | `TagRecord` | exact |

The report holds counts only and is logged with `os.Logger`: tasks, projects, tags, subtasks, comments, skipped deleted tags, review marks and duration. It never holds a title (FR-030, research R21).

## 4. Review marks → sidecar (FR-023)

| legacy | sidecar (data-model E7) |
|---|---|
| `waitingReviews[taskID] = {taskRevision, reviewedAt}` | `waitingReviews["c:<clientID>"] = {reviewedAt, stamp: <imported task updatedAt>}`, only when the legacy receipt was still valid (its `taskRevision` equals the task's revision); an invalid receipt is dropped, which is exactly what the Mac would have shown |
| `somedayReviews[...]` | same rule |
| project `lastReviewedAt`, `lastReviewDecision`, `lastReviewedTaskSignature` | `projectReviews["c:<clientID>"] = {reviewedAt, decision, taskSignature: <recomputed over the imported tasks>}`, only when the legacy signature matched the legacy tasks (the project was not "changed since review") |

So a mark that was valid before the upgrade is valid after it, and a mark that was due is still due (US4-1 "review marks are also present").

## 5. Unreadable store (FR-022, design X-05)

| cause | `unreadableReason` | X-05 copy |
|---|---|---|
| JSON does not decode, a required field is missing, or any record fails §2 or §3 ("partial read", design interpretation **confirmed**) | `corrupt` / `verificationFailed` | "Brain Buddy couldn't read your earlier tasks" / "The file from the previous version was left exactly as it was. It's here:" / path / "Brain Buddy will start with an empty workspace. Keep the file if you'd like help recovering it." |
| `version > 1` | `newerVersion` | "They were saved by a newer version of Brain Buddy, so this version left the file exactly as it was." / "Install the newer version to open the file again." |

**How the alert behaves**:

- App-modal alert before the workspace opens. The path is selectable.
- "Continue" is the default; "Show in Finder" reveals the file, then behaves like Continue. Esc is not mapped.
- `noticeSeenAt` is recorded on either button.
- A quit while the alert is open records nothing, so it shows again next launch.

**What happens to the file**:

- It is never renamed, rewritten or deleted.
- A `store.json` written by a failed verification is deleted before the alert.

## 6. Tests (named with requirement ids)

- **Populated fixture** (`021-FR-020`, `021-SC-003`): imports with every §3 equality. It contains archived projects with tasks, an archived project whose name equals an active one, desired outcomes, Waiting, Someday and project review marks, subtasks in three states, edited comments, completed and cancelled tasks with `lastOpenState`, and a deleted tag.
- **Corrupt, newer and partial fixtures** (`021-FR-022`): the legacy file's bytes are unchanged after the run, and no `store.json` remains. The "partial" fixture has one task referencing a missing project.
- **Crashes** (`021-FR-021`): injected failures after write, after verification and after the sidecar record each recover on the next run with no duplicate records and the legacy bytes unchanged until the rename.
- **Backup retention** (`021-FR-021`):

  | days since import | sign-out since import | backup |
  |---|---|---|
  | 29 | yes | kept |
  | 31 | no | kept |
  | 31 | yes | deleted |

- **Old copy still running** (`021-FR-020`): a second process holding the legacy `lockf` blocks the import until it releases. After the rename, that process's next write fails with its existing 409 and writes nothing.
- **Review marks** (`021-FR-023`): marks survive import, and a due mark is still due.
- **Privacy** (`021-FR-030`): the log for a sentinel-titled fixture holds counts only.
