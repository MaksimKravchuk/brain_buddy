# Brain Buddy macOS prototype

Native SwiftUI proof of concept with a durable local GTD store. It opens without
web sign-in or network access and supports Inbox / Next actions / Waiting for /
Someday, date views, projects and tags, Completed / Cancelled history, search, pagination, task
completion and reopening, quick moves between the four GTD lists, and an inline
editor with explicit Save and Discard for task fields.
Inbox has a one-item-at-a-time clarification flow. A captured item can become
a concrete Next action, a Waiting item with an explicit reason, a new project
with a desired outcome and first Next action, Someday, or Cancelled. Clear
actions can move to Next in one click; more ambiguous choices ask one question
at a time. Reference-only material remains in Inbox until a separate reference
space is designed. The project conversion is one atomic local write that keeps
the source item's task ID and details while using its original title as the
proposed project name. No AI classification is performed.
The POC uses one main window so separate window snapshots cannot overwrite each
other's local changes. Switching to another capture context with an unfinished
task draft asks whether to keep editing or discard it.
Quick capture recognizes `#tag` and `@project` tokens and saves the task with its classification in one local
write. The voice sheet records and transcribes locally with WhisperKit, then
places one editable transcript into the task draft. It does not extract multiple
actions or run the brain dump operation; agent workflows are outside this POC.
The capture preview shows the effective Project and Tags after interpreting
tokens. New task from a date or History view asks which open GTD list to use.
The current view shows filtered open task totals; sidebar list badges keep
global counts while browsing a project, tag, date, or search. When more pages
exist the window also shows how many rows have been loaded so far.
The toolbar filters by priority through the local task query.
Adding a project token from Inbox retains the Inbox state. After capture the
project view opens so the new task remains visible. Capture in a project or tag
view also defaults to Inbox.
Projects and tags can be renamed from their sidebar context menus. Tags can
also be deleted with confirmation; deletion removes the tag from tasks, while
the tasks remain. Projects can be archived and restored locally without changing
the project membership of open, completed, or cancelled tasks. Archived projects
remain browsable but cannot receive new assignments; the archive view hides
quick capture, while the global New task action opens Next actions. The current
web archive operation clears task membership and needs a contract fix before sync.
Archiving waits until a pending quick-capture draft is added or cleared, so its
project classification cannot silently change.
Active local projects can store a separate desired outcome. The project view
shows that outcome beside the first Next action, fetched independently of the
current search or task page. When no Next action exists, it points to Inbox,
Waiting, Someday, or an empty project according to its open task counts. The
outcome is stored only in the local POC; web synchronization has no corresponding
project outcome contract yet.
The Projects sidebar has a local, one-project-at-a-time review. It shows why a
project needs attention, its desired outcome, all linked open actions, and up to
three recent closures. Reviewing requires an explicit decision; a project with
only unclarified Inbox items needs a Next action before it can be marked
reviewed. Completed projects with no open actions can be archived from the
review. The decision and review time survive restart. Projects return to the
queue after seven days or when a linked task changes. Reviewing never changes
a task due date or GTD state automatically.

Build a launchable `.app` on macOS 26+ with Xcode installed. The build includes
the local Whisper base model and tokenizer. By default it reads the model from
`~/Documents/huggingface/models/argmaxinc/whisperkit-coreml/openai_whisper-base`
and the tokenizer from `~/Documents/huggingface/models/openai/whisper-base`.
Set `WHISPERKIT_MODEL_SOURCE` and `WHISPERKIT_TOKENIZER_SOURCE` to other complete
local folders when needed; the build stops if either asset is missing.

```sh
cd macos
sh build_app.sh
open .build/BrainBuddyMac.app
```

Run the local store, API client, and Smart Add parser tests with
`swift test --disable-sandbox` from `macos/`. In a restricted workspace, set
`CLANG_MODULE_CACHE_PATH` and
`SWIFT_MODULE_CACHE_PATH` to directories under `macos/.build` first.
The [offline QA record](offline-qa-2026-09-26.md) describes the live journeys
checked with network access denied to the app process.

The local snapshot is stored under the user's Application Support directory and
is written atomically before a change is reported as saved. It survives a quit
and restart. Repeated commands return their original saved result only when the
payload matches; a changed payload with the same key is rejected. A second app
process with an older snapshot cannot overwrite newer local tasks. The existing
API client remains in the package for future optional
web synchronization and its contract tests, but the visible Mac workspace does
not require a web session. Bidirectional synchronization is not yet enabled.

Opening a task loads its full detail from the local store, including subtasks
and comments. The editor keeps the task in its list, gives notes the main area,
shows the GTD list and project directly, and reveals date, priority, and tags
on request. The task-row move menu changes open GTD states without opening the
editor; moving to Waiting asks who or what is awaited before saving. The editor
can add, rename, complete, and reopen subtasks; add and edit comments; and
cancel a task. Subtask and comment operations save immediately, while task
fields use explicit Save and Discard. The UI states that discarding task edits
keeps already saved subtask and comment changes. Unsaved edits
require confirmation before switching tasks or lists. A stale revision keeps
edited fields in the editor until the current task is loaded and the user
chooses to retry. Voice transcription asks before
replacing an existing quick-capture draft.

The Waiting for list has a one-item-at-a-time review. It loads every Waiting
page, shows the awaited person/event and the date waiting began, then asks for
an explicit decision: keep waiting, create a separate Next
follow-up in the same project, return the task to Next with an editable action
title, or cancel it. Follow-up creation leaves the original Waiting task in
place. Returning it to Next clears the active waiting fields. The review does
not send messages or schedule a due date. In the local workspace, Keep waiting
and Create follow-up store a review receipt separately from the Waiting task:
the item returns to the review after seven days or immediately when its task
revision changes, while its GTD state and waiting date remain intact. Follow-up
creation and its review receipt are one atomic local write.

Completed and cancelled tasks reopen into a chosen open list; Waiting for
requires a person, event, or condition. The local store records the last open
list on terminal transitions, so each list shows its own history. This POC has
no background sync process.

Completed and cancelled rows open a read-only detail with description,
classification, subtasks, and comments; Reopen remains a separate action.

WhisperKit loads the model and tokenizer bundled in the `.app`, with model
downloads disabled. A local Russian speech sample was transcribed from the
bundled assets. If the bundled tokenizer becomes corrupt, WhisperKit's internal
fallback may still try to fetch it. The recorded WAV is kept only in a temporary
file and removed after transcription or discard. Local multi-action extraction
is deferred: the on-device Foundation Models check on this Mac reported
`appleIntelligenceNotEnabled`, and no other local language model was available
for a quality and latency experiment. See
[the local extraction check](local-extraction-feasibility.md) for conditions and
the exact result.
