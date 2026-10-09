# Brain Buddy for Mac

A native SwiftUI app over the shared `BrainBuddyKit` package (`../ios/BrainBuddyKit`), the
same GTD rules, store file and sync engine as the iPhone app (spec 021). It opens without a
sign-in or a network connection: every change applies at once on this Mac and is kept in
`store.json`. The account-less footer reads "On this Mac · Sign in to sync"; nothing is sent
anywhere until you sign in.

It supports Inbox / Next actions / Waiting for / Someday, date views, projects and tags,
Completed / Cancelled history, search, task completion and reopening, quick moves between the
four GTD lists, and an inline editor with explicit Save and Discard for task fields. Inbox has a
one-item-at-a-time clarification flow: an item can first be given a project (an existing one or a
new one made on the spot), then become a Next action, a Waiting item with a reason, Someday, or
Cancelled; or it can become a new project of its own, with an optional desired outcome and a first
Next action (one change). Quick capture (⌃⌥⇧B) and Smart Add (`#tag`, `@project`) use the kit's capture, so a
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
transcript into the task draft. WhisperKit runs only inside the `VoiceTranscriber` actor, and the
voice sources have no network API (`MacPrivacyGuardTests`).

## Signing in and syncing

"Sign in to sync" in the sidebar footer, "Sign in…" in the status popover or the app menu opens
the sign-in sheet (design X-03). The first sign-in adds this Mac's tasks to the account: projects
and tags with the same name become one, tasks are never merged by title. While "Signing in…"
runs, Cancel and Esc still work; a reply that arrives after Cancel has its session ended at once
and links nothing. Signed in, the Mac syncs in the background while it runs: about every 15 s it
checks whether the last pull is 30 s old or changes wait, pulls when the window comes forward or
becomes visible again, and holds an App Nap activity so a covered window keeps that pace. File ›
"Sync now" (⌘R) runs a sync at once.

The footer says how sync is in a few words ("Synced 3 min ago", "Offline · 3 changes waiting",
"Couldn't sync · Retry", "Sign in again to sync") and speaks up only when something needs you.
Clicking it opens the status popover: the last sync, what waits, sync issues with Copy and
Dismiss, "Sync now", the account and "Sign out…". Sign-out asks first, with the count of changes
that would be removed, and removes this Mac's copy of the account's tasks.

**The Keychain prompt.** The session token is kept in your login keychain, service
`app.brainbuddy.mac.session`, never in a file. After a local rebuild macOS may treat the new
binary as another app: routine sync never asks for access (the footer then reads "Sign in again
to sync"), and the only place macOS may ask is the sign-in sheet. If you choose "Deny" there and
the sign-in still can't be saved, remove the `app.brainbuddy.mac.session` item in Keychain Access
and sign in again (`docs/native-macos-app.md`).

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
`UnreadableWorkspaceTests`, `MacLaunchTests`, and for sync `MacSyncFlowTests`,
`SyncStatusLineModelTests`, `SyncStatusPopoverModelTests`, `SyncTriggerSourceTests`,
`MacPresentationRouterTests`, `MacPresentationGuardTests`, `MacPrivacyGuardTests`,
`MacKeychainTests`) plus the XCTest `WeeklyReviewRowTests`. `MacKeychainTests` creates and
deletes a temporary keychain of its own and never touches the login keychain; it fails rather
than skips when it cannot. The legacy-store fixtures are synthetic, in
`Tests/BrainBuddyMacTests/Resources/`. In a restricted workspace, add
`--disable-sandbox` and set `CLANG_MODULE_CACHE_PATH` and `SWIFT_MODULE_CACHE_PATH` to folders
under `macos/.build` first. The kit's own tests run with `sh ios/scripts/swift-linux.sh test`.

## Files on this Mac

Everything lives in `~/Library/Application Support/BrainBuddyMac/` (mode 0700):
`store.json` (the workspace), `mac-local.json` (review marks, the import record, the sidebar's
disclosure state; no titles, names or notes), `.instance.lock` (one running copy per folder) and,
after an upgrade, the previous version's file renamed to `local-gtd.backup-<UTC>.json`. The
session token is in the login keychain (service `app.brainbuddy.mac.session`), not in this folder.
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
