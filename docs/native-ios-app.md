# Native iOS app (offline-first)

Status: pass 1 in progress (GTD). Owner: BrainBuddy. Code: `ios/`.

Brain Buddy for iPhone and iPad, written in SwiftUI for iOS 26 with Liquid
Glass. The organising principle is autonomy: **every GTD action works without
a network**, and the server is a place to sync to, not a place to ask
permission from. This app is the iPhone client; the earlier Expo client in
`mobile/` was removed in 2026-10.

## Passes

| Pass | Scope | Network needed for |
|---|---|---|
| **1 — GTD** (this document) | Capture, clarify, organise, engage: the four lists, projects, tags, date views, search, history, task detail with subtasks and comments, Smart Add, Process inbox, widgets and App Intents, sync with the account | Signing in; exchanging changes |
| 2 — Brain dump | Voice capture with on-device transcription (SpeechAnalyzer / WhisperKit), recorded offline, uploaded for proposals later | Proposal extraction (server AI) |
| 3 — Everything else | Thinking canvas, agents, account management | Per feature |

The weekly review is flag-gated (spec 020): while the `weekly_review` flag is
off (account-less: the build's release switch) Lists keeps a non-interactive
"coming later" row; once it is on, the row opens the Quick or Full review (full
screen, offline too). Pass 1 adds **Process inbox** — the GTD *clarify* step,
one inbox item at a time, fully offline — which the review's Inbox step reuses.

## What works offline

Everything in pass 1 except signing in and the sync itself:

- capture (with `#tag` / `@project` Smart Add, creating new projects and tags),
- move between lists, complete, cancel, reopen into a chosen list,
- edit title, notes, due date, priority, project, tags, waiting-for,
- subtasks (add, rename, complete, cancel, reopen) and comments (add, edit),
- projects (create, rename, recolour, archive) and tags (create, rename, delete),
- Inbox / Next / Waiting / Someday, Overdue / Today / Upcoming, project and
  tag views, completed and cancelled history, search, sort, group by project,
  priority and tag filters, "project needs a next action",
- widgets, Siri / Shortcuts / Control Center capture and completion.

The app works with **no account at all** ("On this iPhone"). Signing in later
uploads what was captured locally.

## Architecture

```
ios/
  BrainBuddyKit/            Swift package, zero dependencies, builds on Linux
    BrainBuddyCore          models, commands, GTDReducer, replay, queries, Smart Add
    BrainBuddyPersistence   one JSON document, atomic replace, cross-process lock
    BrainBuddyAPI           typed REST client, cookie session, error taxonomy
    BrainBuddySync          outbox push, full pull, merge, backoff
    BrainBuddyWorkspace     @Observable app model the UI binds to
  BrainBuddy/               SwiftUI app (iOS 26)
  BrainBuddyWidgets/        WidgetKit + controls
  project.yml               XcodeGen spec (the .xcodeproj is generated)
```

Everything below the SwiftUI layer compiles and is tested on Linux
(`sh ios/scripts/swift-linux.sh test`), so the GTD rules and the sync
engine are verified without a Mac. The macOS prototype in `macos/` was the
starting point for the rules and the Smart Add parser.

### The data model: base + outbox

```
                ┌──────────── StoreDocument (one file) ─────────────┐
 server ──pull──▶ base: GTDState        outbox: [PendingOperation]  │
   ▲            └───────┬──────────────────────────┬───────────────┘
   │                    └──── OutboxReplayer ──────┘
   │                               │
   │                        current GTDState ──▶ SwiftUI
   │                               ▲
   └──── push (1 op = 1 request) ──┴── user command → GTDReducer (validate + apply)
```

- **`GTDReducer`** is the only place GTD rules live. A user action is a
  `GTDCommand`; the reducer validates it and applies it to the in-memory
  state synchronously, so the UI never waits on disk or network.
- The command is appended to the **outbox** (`PendingOperation`: the
  command, its issue time, an `Idempotency-Key`, attempt bookkeeping) and the
  document is written in the background.
- **`base`** is what the server has confirmed. **Current state is always
  `replay(outbox, onto: base)`** — the same reducer, in replay mode. After a
  pull or an acknowledgement, the current state is recomputed from the new
  base, so local intent is re-applied on top of whatever changed elsewhere.
- Every command carries the ids it creates and replays use the command's
  issue time, so replay is deterministic.
- Without an account `base` is empty and the outbox *is* the data. The
  compactor keeps it proportional to the data, not to the edit history (an
  edit to an unsent task folds into its creation; consecutive unsent edits
  merge; complete-then-reopen of an unsent task cancels out). Sent operations
  are never rewritten.

### Ids

The API mints ids (`task_1a2b3c4d5e6f`) and rejects client-supplied ones.
Records therefore have a permanent client id (`EntityID`, a UUID) used by the
UI, commands and the outbox, plus `serverID` / `serverRevision` once the
server has acknowledged the creation. The push planner resolves client ids
to server ids at send time; the outbox is ordered, so a project's creation is
always sent before a task that references it.

The weekly review is the exception: its records (review sessions, decisions,
bulk releases and progress changes), the follow-up tasks a decision creates
and every formulation carry a **client-supplied id** of the shape
`<prefix>_<lowercased UUID>` (`review_`, `decision_`, `bulk_`, `progress_`,
`form_`, `task_`), minted in the command, so a retry or a replay names the
same record and is applied once (`specs/020-weekly-review/contracts/http.md`).

### Commands and endpoints

Each command is exactly one request, so each carries exactly one
`Idempotency-Key`.

| Command | Request |
|---|---|
| `createProject` | `POST /projects` |
| `updateProject` (name, colour) | `PATCH /projects/{id}` |
| `archiveProject` | `POST /projects/{id}/archive` |
| `createTag` | `POST /tags` |
| `renameTag` | `PATCH /tags/{id}` |
| `deleteTag` | `DELETE /tags/{id}?expected_revision=N` |
| `createTask` (open state) | `POST /tasks` |
| `updateTask` (`TaskChanges`, omit / `null` / value) | `PATCH /tasks/{id}` |
| `transitionTask` (move, complete, cancel, reopen) | `POST /tasks/{id}/transitions` |
| `createSubtask` / `updateSubtask` / `transitionSubtask` | `POST`/`PATCH /tasks/{id}/subtasks[/{sid}[/transitions]]` |
| `createComment` / `updateComment` | `POST`/`PATCH /tasks/{id}/comments[/{cid}]` |

Smart Add runs **on the device**: `CapturePlanner` resolves `#tag` and
`@project` names against active records by normalized name and emits
`createProject` / `createTag` commands for missing ones, then `createTask`.
The server's `/tasks/smart-add` is not used, because the new project must
exist locally before any network.

### Rules the reducer mirrors

From ADR-0006 and `backend/app/modules/tasks`:

- States: open `inbox`, `next`, `waiting`, `someday`; terminal `completed`,
  `cancelled`. `move` needs an open task and a *different* open list;
  `complete` / `cancel` need an open task; `reopen` needs a terminal task and
  an explicit list.
- Waiting needs a trimmed, non-blank `waiting_for` (≤ 500) on entry and sets
  `waiting_since`; leaving Waiting clears both. `waiting_for` can only be
  edited while Waiting.
- Transitions never change order, project, tags, due date, priority or notes.
- Limits: title and names 1–500, notes ≤ 20 000, comments 1–20 000, colour ≤ 64.
- Inbox shows projectless inbox tasks only; assigning a project moves the
  task out of the Inbox view (`docs/projectless-inbox-contract.md`).
- Project names are unique among active projects, tag names among active
  tags, after NFKC + trim + whitespace collapse + case-fold (tags also drop a
  leading `@`).
- Archiving a project **removes it from every task** (current server
  behaviour; the tasks stay in their lists) and cannot be undone — there is no
  unarchive endpoint. ADR-0020 plans archive-keeps-membership and unarchive;
  the reducer will follow when the server does.
- Deleting a tag removes it from every task.
- Subtask transitions need a different target state.

### Sync

The backend has **no change feed** (no `updated_since`, no tombstones), ids
are server-minted, idempotency keys live **24 hours**, and
`expected_revision` must match exactly. The engine is built around that.

**Push** — sequential, in outbox order, one request per operation:

| Response | Action |
|---|---|
| 2xx | Apply the returned record to `base` (server id, revision, server timestamps), drop the operation, replay |
| Network error, timeout, 429, 5xx | Keep the operation *and its key*; retry with exponential backoff (2 s → 5 min, jitter). The outcome may be unknown, so the same key makes the retry safe |
| 5xx (or a 2xx the app can't read) for the same operation 8 times in a row, or twice in a row once it has been failing for 24 h | Set it aside as a sync issue ("The server kept rejecting this change.") so the changes behind it go out |
| 3xx | Never followed (that would resend the session cookie elsewhere). Nothing processed the request: keep the operation and its key, back off, never set it aside. After two failed cycles the status reads "The server redirected the request, which Brain Buddy doesn't follow." |
| 409 stale revision | `GET` the record into `base`, replay (drops the operation if its goal already holds, e.g. already completed elsewhere), then resend with the new revision and a **new** key |
| 409 duplicate name (create project / tag) | Pull, adopt the existing server record for the local id (the outbox is rewritten to it), replay |
| 400 / 422 / other 4xx on a task create or edit | Pull, then re-apply it as replay does (`GTDReducer.replayable`). If that drops a project archived or a tag deleted elsewhere (or a field change the task can no longer take), resend that form under a new key, at most once per body; the task keeps everything else. Otherwise, as the last row |
| 401 | Stop; status "Sign in again to sync"; keep everything |
| 400 / 404 / 422 / other 4xx / 409 idempotency | Move the operation to **sync issues** with the server message and reference id, pull, replay (operations that depend on it, such as a new task's subtasks, follow it) |

A cycle whose push is blocked by the server's side (5xx, 429, a redirect, an
unreadable success) still pulls, so what other devices changed arrives while
the operation waits for its retry; only the network and a 401 stop a cycle
at once.

An operation whose first uncertain send is more than 23 hours old is never
blindly resent: a create first pulls and adopts a matching server record
(same title and list, created after the first attempt) if one exists. A
request that provably never left the device, or that nothing processed (a
redirect), starts no such clock.

**Pull** — full, because there is no delta endpoint:
`GET /tasks?include_completed=true&include_cancelled=true&sort=manual&limit=200`
following `next_cursor`; `GET /projects`, `GET /tags` (active only) plus
`GET /projects/{id}` / `GET /tags/{id}` for referenced archived or deleted
ones. Server records are matched to local ones by `serverID`; the new base
replaces the old; current = replay(outbox, base).

**Subtasks and comments** are not in the list response and their edits do
not bump the parent's revision, so they are hydrated per task: when a task
detail opens (online), after the task's revision changes, and for open tasks
in the background with a small concurrency limit. A detail read runs in the
same single-flight slot as sync cycles (after the running one), so it never
overlaps a push whose acknowledgement it could overwrite with older children.

**Sessions**: signing in as another account (or on another server) is
refused while the linked account still has changes or sync issues on the
device, so one account's changes never reach another; otherwise the old
account's server data is removed before the new one is pulled. A logout the
server could not be told about (offline, or it failed in a way worth
retrying) waits in the Keychain and is sent when the network returns, on the
next launch or foreground, or after the next sign-in.

**When sync runs**: on launch and foreground, 2 s after the last local
change, when connectivity returns (`NWPathMonitor`), on pull-to-refresh, and
opportunistically via `BGAppRefreshTask`.

### Persistence and extensions

One `StoreDocument` JSON file (`base`, `outbox`, `issues`, `account`, sync
metadata, `generation`) in the App Group container, file protection
`completeUntilFirstUserAuthentication` so widgets and intents can read it
after first unlock. Writes are read-modify-write under an advisory lock
(`lockf`), written to a temporary file, `fsync`ed and renamed. A document that
cannot be decoded is never overwritten.

The widget extension and App Intents open the same file with sync disabled
and apply commands through the same reducer. The lock plus replayable
commands make concurrent writers safe: a writer always applies its command to
the latest document. After an external write the app reloads (Darwin
notification and scene activation) and widgets are reloaded after the app's writes.

### Account and session

Signing in uses `POST /auth/login`; the `brainbuddy_session` cookie value is
kept in the Keychain and sent as a `Cookie` header, not left in the shared
cookie jar. Signing in on a device that has local data uploads it; the
account's data is merged by name (projects, tags) and appended (tasks).
Signing out removes the account's data from the device after warning about
unsynced changes. The server address defaults to
`https://brain-buddy-frontend.fly.dev/api` and is editable (https only;
`http://localhost` for development).

### Security and privacy

- **Session token.** The `brainbuddy_session` value lives in the Keychain as
  a generic password, `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`:
  readable after the first unlock so background refresh can sync, never
  restored to another device from a backup. Only the app reads it; widgets
  and intents never sync, and there is no keychain sharing. It is removed on
  sign-out and on a 401, and a launch with no linked account removes any
  token left over from an earlier install.
- **Transport.** https only; plain http is accepted only for the host
  `localhost`, and the app has no App Transport Security exceptions (ATS
  allows unqualified `http://localhost`, but not `http://127.0.0.1` or
  `http://[::1]`, so the address check refuses those too). Redirects are
  never followed: the API never sends one, and following it would resend the
  `Cookie` header (and a login's password) to another address. A 3xx is
  reported as "The server redirected the request, which Brain Buddy doesn't
  follow." and retried like a server failure, without losing any change.
- **Data at rest.** The store document (and any unreadable file set aside by
  "Start fresh") uses file protection `completeUntilFirstUserAuthentication`,
  so widgets and intents can read it after the first unlock. It is in device
  backups. Retention of every on-device record is in
  `docs/data-retention.md`.
- **Lock screen.** App Intents, Siri and Control Center controls that
  *complete* a task require the device to be unlocked; capture is allowed
  from the lock screen, since it only adds to the Inbox.
- **Switching accounts.** Signing in as a different account while changes
  or sync issues are waiting is refused: sign out first (which warns about
  the unsynced changes), so one account's changes are never sent to another.
- **Account deletion.** Signing in during the 14-day deletion grace period
  cancels the deletion, as on the web; the app says so in a notice instead
  of doing it silently.

## Interface

Navigation (iPhone; iPad uses the adaptable sidebar):

| Tab | Content |
|---|---|
| Inbox | projectless inbox, badge count, **Process inbox** |
| Next | Next actions, grouped by project, with tag and priority filters |
| Today | Overdue, Today, Upcoming |
| Lists | Waiting for, Someday / maybe, Projects (with "needs a next action"), Tags, Completed, Cancelled, Settings |
| Search | `Tab(role: .search)` across all tasks |

- **Capture is always one tap away**: a glass capture bar in the tab view's
  bottom accessory opens the capture sheet — Smart Add with highlighted
  tokens and a live preview of the project and tags that will be used or
  created, list picker (Waiting asks who or what), due date, priority, notes.
- Task detail is a pushed screen. Rows swipe to complete (leading) and to
  move (trailing); a context menu offers every transition.
- Completing animates in under 600 ms and respects Reduce Motion (spec 016);
  an undo toast reopens into the previous list.
- Sync state is always words ("Synced 2 minutes ago", "Offline — 3 changes
  waiting", "Sign in again to sync"), never a coloured dot alone.

### Liquid Glass and the design system

The design system (`.claude/skills/brain-buddy-design/`) allows blur only on
floating and sticky surfaces and keeps content flat. On iOS 26 that maps to:
**glass on chrome only** — tab bar, navigation and toolbars, sheets, the
capture accessory, floating action clusters (`GlassEffectContainer`) — and
**flat content**: task rows, cards and lists on the brand surfaces, with the
brand tokens, sentence case, 44 pt targets and brand motion curve
(`cubic-bezier(0.22, 1, 0.36, 1)`) for our own animations.

Deviations that need a product sign-off:

1. **SF Symbols instead of Lucide.** Native tab bars and glass controls are
   built for SF Symbols; the macOS prototype made the same choice. Mapping:
   Inbox `tray`, Next `checklist`, Waiting `clock`, Someday `archivebox`,
   Today `calendar`, Search `magnifyingglass`, Lists `square.stack`.
2. **Dark mode.** The design system has light tokens only; the app derives
   dark ones from the same slate/sky scale.
3. **System font (SF Pro) instead of Inter.** No Inter files are in the repo,
   and SF Pro is what glass controls are tuned for.
4. **System glass motion.** Glass morphing uses system springs; the brand's
   no-spring rule applies to our own animations only.
5. **sky-700 for text and filled controls.** Brand-coloured text and the
   brand fill behind white labels use sky-700 (`#0369A1`) in light mode, the
   `brandText` and `brandFill` tokens, because sky-500 falls short of WCAG AA
   contrast there (white on `#0EA5E9` is about 2.8:1). sky-500 stays for
   large accents: selection highlights, completed checks and the app icon.

## Known limitations of pass 1

- **Children sync late.** A subtask or comment edited on another device
  appears when the task is opened (or its own fields change), because such
  edits do not change the parent's revision (backend ask 2).
- **Lost responses older than a day.** If a create's response was lost, its
  key has expired (24 h) and another device has since changed that task's
  title or list, the retry can create a duplicate (backend ask 3).
- **Last pushed wins per field.** Two devices editing the same field offline
  converge on the one that syncs last; different fields of the same task
  both survive.
- **Archived projects and deleted tags are fetched one by one** on every
  pull, so pulls get slower as archives grow (backend ask 7).
- **Large local-only outboxes** (thousands of offline changes before the
  first sign-in) replay on the main actor at launch: about 45 ms for 2 000
  operations on a release build.

## Backend asks (not blocking pass 1)

1. A change feed (`GET /tasks?updated_since=` including subtasks and
   comments, with tombstones), to replace the full pull.
2. Subtask and comment edits should bump the parent task's revision (or
   expose `children_updated_at`), so hydration can be targeted.
3. Accept a client-generated id on create (or a longer idempotency window);
   a 24-hour key window forces the duplicate-avoidance heuristic above.
4. Include `current_revision` in stale-revision 409s to save a round trip.
5. ADR-0020 archive semantics (keep membership, unarchive).
6. `docs/api-compatibility.md` asks for an API version before a second
   client; the iOS app sends `X-Client: brainbuddy-ios/<version>` so the
   server can tell clients apart once that exists.
7. List archived projects and deleted tags (`GET /projects?state=archived`,
   `GET /tags?state=deleted`) instead of one `GET` per record.

## Verification

- `sh ios/scripts/swift-linux.sh test` — every package target, on Linux via
  Docker (no Xcode needed).
- CI (`.github/workflows/ci.yml`) — the `ios-kit` lane runs the package
  tests on Linux; the `ios-app` lane generates the XcodeGen project on macOS
  and builds the app, widgets and package and tests the package with Xcode 26.
  Both are part of `Full CI`, the verdict a change lands on.
- `.github/workflows/ios.yml` — uploads to TestFlight after CI has passed on
  `main` for a commit that changed `ios/`.
- The SwiftUI layer can only be compiled on macOS; it has no logic of its
  own beyond presentation — rules live in the package.
