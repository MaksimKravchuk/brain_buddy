# Brain Buddy macOS prototype

Native SwiftUI proof of concept with a durable local GTD store. It opens without
web sign-in or network access and supports Inbox / Next actions / Waiting for /
Someday, date views, projects and tags, Completed / Cancelled history, search, pagination, task
completion and reopening, and an inline editor with explicit Save and Cancel.
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
and comments. The editor can add, rename, complete, and reopen subtasks; add
and edit comments; and cancel a task. Subtask and comment operations save
immediately, while the task fields use explicit Save and Cancel. Unsaved edits
require confirmation before switching tasks or lists. A stale revision keeps
edited fields in the editor until the current task is loaded and the user
chooses to retry. Voice transcription asks before
replacing an existing quick-capture draft.

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
