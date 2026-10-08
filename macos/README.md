# Brain Buddy for Mac

A native SwiftUI app over the shared `BrainBuddyKit` package (`../ios/BrainBuddyKit`), the
same GTD rules, store file and sync engine as the iPhone app (spec 021). It opens without a
sign-in or a network connection: every change applies at once on this Mac and is kept in
`store.json`. The account-less footer reads "On this Mac · Sign in to sync"; signing in and the
sync status line arrive in the next slice (021 PR-09).

It supports Inbox / Next actions / Waiting for / Someday, date views, projects and tags,
Completed / Cancelled history, search, task completion and reopening, quick moves between the
four GTD lists, and an inline editor with explicit Save and Discard for task fields. Inbox has a
one-item-at-a-time clarification flow: an item can become a Next action, a Waiting item with a
reason, a new project with its desired outcome and first Next action (one change), Someday, or
Cancelled. Quick capture (⌃⌥⇧B) and Smart Add (`#tag`, `@project`) use the kit's capture, so a
capture never waits for the network. Quick Open (⌘O) finds lists, projects, tags and tasks.

Projects are archived and unarchived without changing any task's project: an archived project
stays browsable under the collapsible "Archived projects · N" sidebar section, shows "Archived"
and "Unarchive", refuses new tasks, and its tasks elsewhere read "Old flat · archived". Archive
and unarchive are also in the File menu. Unarchive is refused while another active project has
the same name, with "Rename…" for the archived one.

The Waiting, Someday and Project reviews keep their "reviewed" marks only on this Mac, in
`mac-local.json`; an item returns after seven days or when its task changes, and a project
review decision is refused once the project's actions changed since the review opened.

The voice sheet records and transcribes locally with WhisperKit, then places one editable
transcript into the task draft. WhisperKit runs only inside the `VoiceTranscriber` actor.

## Toolchain and package

- Swift 6.2 (`swift-tools-version: 6.2`, Swift 6 language mode), macOS 26 and Xcode 26.
- `Package.swift` depends on WhisperKit (`argmax-oss-swift`, pinned in `Package.resolved`) and on
  the local kit by path. Three targets: `BrainBuddyMacCore` (Foundation only: the upgrade
  import, `mac-local.json`, the single-instance lock, `WorkspaceHost` and the window's model),
  the `BrainBuddyMac` app, and `BrainBuddyMacTests`.
- `swift build` also builds the kit. CI builds and tests with
  `--only-use-versions-from-resolved-file`, so a change to the remote dependencies needs a
  matching `Package.resolved`.

## Build and run

Build a launchable `.app` on macOS 26+ with Xcode installed. The build includes the local Whisper
base model and tokenizer. By default it reads the model from
`~/Documents/huggingface/models/argmaxinc/whisperkit-coreml/openai_whisper-base` and the
tokenizer from `~/Documents/huggingface/models/openai/whisper-base`. Set
`WHISPERKIT_MODEL_SOURCE` and `WHISPERKIT_TOKENIZER_SOURCE` to other complete local folders
when needed; the build stops if either asset is missing.

```sh
cd macos
sh build_app.sh
open .build/BrainBuddyMac.app
```

## Tests

```sh
cd macos
swift test
```

The suites are Swift Testing (`OfflineWorkspaceTests`, `LegacyStoreImporterTests`,
`MacLocalStateTests`, `SingleInstanceGuardTests`, `LegacyCookieCleanupTests`,
`UnreadableWorkspaceTests`) plus the XCTest `WeeklyReviewRowTests`. Their fixtures are synthetic
legacy stores in `Tests/BrainBuddyMacTests/Resources/`. In a restricted workspace, add
`--disable-sandbox` and set `CLANG_MODULE_CACHE_PATH` and `SWIFT_MODULE_CACHE_PATH` to folders
under `macos/.build` first. The kit's own tests run with `sh ios/scripts/swift-linux.sh test`.

## Files on this Mac

Everything lives in `~/Library/Application Support/BrainBuddyMac/` (mode 0700):
`store.json` (the workspace), `mac-local.json` (review marks, the import record, the sidebar's
disclosure state; no titles, names or notes), `.instance.lock` (one running copy per folder) and,
after an upgrade, the previous version's file renamed to `local-gtd.backup-<UTC>.json`.
See `docs/data-retention.md` for how long each is kept.

### Upgrading from the pre-sync app

On the first launch after the update, `local-gtd.json` is carried over into `store.json`
(contracts/mac-legacy-import.md): read, written to a staging file, verified against the
original, and only then renamed into place; the original is renamed to the dated backup, never
edited or deleted. A file that cannot be read, a file from a newer version, or a carry-over that
does not match leaves the original exactly as it was and says so once (design X-05). A
`store.json` that cannot be read shows "We couldn't open your tasks" with "Try again" and
"Start fresh…"; it is never overwritten.

### Dry run on a copy (`BRAINBUDDY_MAC_DATA_DIR`)

To try a build on a copy of real data without touching it, copy the folder and point the app at
the copy:

```sh
cp -Rp ~/Library/Application\ Support/BrainBuddyMac /tmp/bb-dry-run
BRAINBUDDY_MAC_DATA_DIR=/tmp/bb-dry-run .build/BrainBuddyMac.app/Contents/MacOS/BrainBuddyMac
```

While the variable is set the app uses only that folder (an absolute path to an existing folder;
anything else stops the launch instead of falling back to the real folder), leaves the old
browser cookies and HTTP cache alone, and makes no Keychain call until a sign-in the person
starts. Do not sign in during a dry run.

The [offline QA record](offline-qa-2026-09-26.md) describes the pre-sync live journeys checked
with network access denied to the app process; the [local extraction
check](local-extraction-feasibility.md) records why multi-action voice extraction is deferred.
