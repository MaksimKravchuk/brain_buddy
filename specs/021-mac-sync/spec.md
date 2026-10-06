# Feature Specification: Mac ↔ backend sync

**Feature Branch**: `021-mac-sync`

**Created**: 2026-10-06

**Status**: Draft

**Input**: User description: "The Mac app stops being local-only: it signs in to the same account as iPhone and web and syncs in the background, like other GTD apps. The person only hears about sync when something fails (can't send, can't load): a compact error. Sync activity is a small indicator that never interrupts; nearby a quiet 'synced N minutes ago'. Everything compact, nothing to think about. Mac-only project features (lossless archive with unarchive, project desired outcome) get server support so nothing is lost." See `intake.md`.

## Clarifications

### Session 2026-10-06

The owner delegated the detail ("ты сам справишься, особо меня не привлекая") and confirmed scope, non-goals and the "complete the server" choice for Mac-only project features (intake.md). The coverage scan found no question without a reasonable default, so no question was asked. The defaults below are recorded so they can be challenged at design sign-off.

- Q: How often does an open Mac fetch changes made elsewhere? → A: On activation, on network return, and at least every 60 s while active (FR-006). This matches the iPhone's 60 s pull age.
- Q: When does a failure stop being silent? → A: After 60 s of continuous failure, or at once for an ended session or a rejected change (FR-014, FR-012).
- Q: Does signing out remove the account's data from the Mac? → A: Yes. The Mac returns to an empty account-less workspace, and unsent changes are warned about first (US1-6, FR-018). This is the iPhone behaviour.
- Q: Does the pre-upgrade local file survive? → A: It is kept untouched until the new workspace is verified, then kept as a backup for ≥ 30 days (FR-021).
- Q: Do the Mac's Waiting / Someday / Project review marks sync? → A: No. They stay on this Mac until weekly review (020) replaces them (FR-023, owner-confirmed scope).
- Q: Do iPhone and web show the project desired outcome? → A: Not in this feature. It is kept intact and exported (FR-028); showing it elsewhere is a later change.
- Q: Where does unarchive live on iPhone and web? → A: Wherever archived projects are listed on that client; placement is fixed at `/speckit-design`.

### Session 2026-10-06 (design sign-off)

- Q: Should the indicator and the waiting count appear on every sync and every edit? → A: No. The indicator appears only for a sync longer than 1 s and stays at least 0.5 s. The waiting count shows while online only after a change has waited 10 s (FR-012, FR-013). Owner: "Пороги".
- Q: Should a Mac sign-out with nothing unsent be confirmed? → A: Yes, "Sign out?", as on the iPhone, because the account's data leaves this Mac (FR-017). Owner accepted.
- Q: Should a pre-feature archived project that unarchives empty explain itself? → A: Yes, with one neutral line saying its tasks are still in their lists (FR-027, US5-4). Owner accepted.

### Session 2026-10-06 (after /speckit-plan)

The owner delegated these. Each one resolves a contradiction or gap the plan found:

- Task deletion and reorder: no client or server deletes or reorders a task today, so FR-007 and FR-009 no longer mention them. The deleted-task edge case now covers completed or cancelled tasks.
- SC-001 runs in both directions, so FR-032 makes the iPhone (foreground) and the web (visible tab) fetch at least every 60 s.
- Completion dates after the first sign-in use the upload day, as on the iPhone; this is recorded in Assumptions. Keeping the original dates would need client timestamps on the server, which is out of scope.
- The pre-upgrade backup outliving sign-out is intended, since it was never account data (Assumptions).
- A second copy of the app gets design X-08 and is listed in FR-017.

### Session 2026-10-06 (after planning-review campaign c1)

The owner delegated these. Both follow the recommendation in `review-c1-disposition.md`:

- OQ-1: the pre-upgrade backup gets no "remove now" option and no lifetime cap without sign-out in this feature. The sign-out dialog and the status popover state the date it is kept until.
- OQ-2: there is no person-started import of an earlier-version file that appears after the workspace is in use. The file is kept untouched and surfaced with "Show in Finder" (FR-033).

### Session 2026-10-06 (design sign-off, continued)

- Design gaps G-1 – G-3 were resolved as recommended: "Not synced yet" and day/date wording (FR-012), and the deletion-cancelled note inside the sign-in sheet (FR-017).

## User Scenarios & Testing *(mandatory)*

Primary-loop impact: this feature makes the Mac a full capture and organise client of the same trusted system. Captures on the Mac (quick-capture hotkey, voice-to-draft, Smart Add) reach clarify → organise → weekly review on every device. It changes no rule of the loop itself. It is the prerequisite for weekly review on the Mac (020 US6, FR-041).

Platforms: **macOS** gets sync. **iPhone** already syncs; it gets the aligned compact status and the ADR-0020 archive semantics. **Web** is online-only; it gets the ADR-0020 archive semantics (archive keeps tasks, unarchive) and no sync UI.

### User Story 1 - Sign in on the Mac and stay in sync without thinking about it (Priority: P1)

A person who uses the iPhone or web signs in on the Mac with the same email and password. From then on, tasks, projects and tags are the same everywhere. A task captured on the Mac shows up on the iPhone, and an edit on the web shows up on the open Mac. The person never presses a button for it.

**Why this priority**: it is the whole point of the feature; without it the Mac stays a separate, untrusted system.

**Independent Test**: sign in on a Mac and an iPhone (or web) with one account. Create, edit, move and complete across both. Each change appears on the other device within the SC-001 window with no manual action.

**Acceptance Scenarios**:

1. **Given** a signed-out Mac with no local tasks, **When** the person signs in, **Then** the account's tasks, projects and tags appear without another step, and a small indicator shows the first load is in progress when it lasts longer than 1 s (FR-013), while the app stays usable.
2. **Given** a signed-in Mac and iPhone, both open and online, **When** the person adds a task on the Mac (main window, quick-capture hotkey or voice draft), **Then** it appears on the iPhone within 60 s.
3. **Given** the same, **When** the person edits a task on the web (title, list, project, tags, dates, priority, notes, subtasks, comments, completion), **Then** the open Mac shows the change within 60 s, without a reload and without moving the person's selection or scroll position.
4. **Given** the Mac app was in the background, **When** the person brings it to the front, **Then** it fetches changes made elsewhere right away.
5. **Given** the person is typing in an inline editor on the Mac, **When** a change to the same task arrives, **Then** their unsaved text is not overwritten; the incoming change applies to the fields they are not editing. On save, their edit wins for the fields they changed (FR-011).
6. **Given** a signed-in Mac, **When** the person signs out with no unsent changes, **Then** the Mac returns to an empty account-less workspace and the account's data is removed from this Mac.

---

### User Story 2 - Keep working offline; nothing is lost (Priority: P1)

The Mac works with no connection, as it does today: capture, quick capture, voice-to-draft, edits, reviews. Changes wait and send themselves when the connection is back, even if the app was quit in between.

**Why this priority**: a GTD system that loses a capture loses trust permanently. The Mac is offline-first today, and sync must not take that away.

**Independent Test**: with the Mac offline, make a fixed set of changes, quit and relaunch, still offline. Then reconnect. Every change reaches the account, none is duplicated, and the same set is visible on iPhone and web.

**Acceptance Scenarios**:

1. **Given** a signed-in Mac with no connection, **When** the person captures and edits tasks, **Then** everything works as online, and the status shows "Offline · N changes waiting" quietly in the sidebar footer, with no dialog.
2. **Given** unsent changes, **When** the person quits and relaunches the app, **Then** the changes are still there and still waiting.
3. **Given** unsent changes, **When** the connection returns, **Then** they are sent without any action, within 60 s of the network coming back while the app is open.
4. **Given** a change was sent but the reply was lost (connection dropped mid-request), **When** the Mac retries, **Then** the account ends up with the change exactly once.
5. **Given** the Mac was offline for days while the iPhone edited the same task, **When** the Mac reconnects, **Then** each field ends with the change that reached the account last. Nothing is silently dropped: a change the account can no longer accept (for example, a task added to a project archived elsewhere) becomes a sync issue the person can see (US3).

---

### User Story 3 - Compact status, and errors only when something is actually wrong (Priority: P2)

Sync shows itself only as a small, quiet line: "Synced 3 min ago". A tiny activity indicator appears while syncing and never blocks work. When sending or loading fails and does not recover on its own, one short message appears in the same place, with a reference id and a way to retry, or to sign in again when the session expired. Details are there on demand, never in a modal. The iPhone uses the same states and wording.

**Why this priority**: the owner's explicit design requirement. The person, ADHD users first, must not have to think about sync. It ranks below US1/US2 because those are what make the status true.

**Independent Test**: drive each state (account-less, synced, syncing, offline with waiting changes, sign-in expired, server failing, change rejected) on the Mac and the iPhone. Check that each shows the specified compact text in the specified place, that none opens a dialog or steals focus, and that each failure carries a reference id.

**Acceptance Scenarios**:

1. **Given** a signed-in Mac in sync, **Then** the sidebar footer shows "Synced just now" / "Synced N min ago", updated at least every minute, and nothing else about sync is visible.
2. **Given** a sync is running, **Then** a small activity indicator appears next to that line, the text does not flicker, and every control stays usable.
3. **Given** a transient failure (server error, timeout, rate limit), **When** an automatic retry succeeds within 60 s, **Then** the person sees nothing beyond the indicator.
4. **Given** sending or loading keeps failing for 60 s, **Then** the footer line changes to a short warning, for example "Couldn't sync · Retry", with the reference id on hover or in details. It clears itself after the next successful sync.
5. **Given** the session expired or was revoked, **Then** the footer shows "Sign in again to sync" with a sign-in action. Work continues locally and changes keep waiting.
6. **Given** the account rejected a change, **Then** the footer shows "1 change couldn't sync" (or N). Opening it lists each change in plain words with its reference id and lets the person dismiss it once they have read it.
7. **Given** the person clicks the status line, **Then** a small popover shows: the exact last-sync time, changes waiting, any issues, "Sync now", and the account email with "Sign out". It closes on Esc or by clicking outside.
8. **Given** the iPhone in each of the states above, **Then** its list screens show the same wording and the same compact form. Settings keeps the existing detailed Sync section and Sync issues screen.

---

### User Story 4 - Upgrade the Mac without losing anything, signed in or not (Priority: P2)

Someone already using the local-only Mac app updates it. All their tasks, projects, tags, subtasks, comments, project outcomes and review marks are still there. If they never sign in, the Mac keeps working on this Mac only. When they do sign in, their Mac data goes into the account and merges with what is already there.

**Why this priority**: the owner and early users have real data in the local Mac store. Losing it on upgrade would be worse than not shipping sync.

**Independent Test**: take a populated local Mac store, including archived projects, desired outcomes, Waiting/Someday/Project review marks, subtasks and comments. Upgrade and check that every record is present. Then sign in to an account that already has some same-named projects and tags. Check that every Mac record is on the account, same-named projects and tags were merged rather than duplicated, and every iPhone/web record is on the Mac.

**Acceptance Scenarios**:

1. **Given** a populated local Mac store, **When** the updated app first launches, **Then** every task, project, tag, subtask and comment is present with the same lists, order, dates, priority, project/tag membership, project desired outcome and archive state. The Waiting / Someday / Project review marks are also present.
2. **Given** the upgraded Mac, never signed in, **Then** the sidebar footer says "On this Mac · Sign in to sync", and the app works fully offline as before.
3. **Given** the upgraded Mac with local data, **When** the person signs in to an account that already has data, **Then** projects and tags with the same name become one. Mac tasks are added to the account; the person's tasks are not merged by title. Afterwards both sides show the union.
4. **Given** the upgrade could not read the old store (corrupt or newer format), **Then** the app does not overwrite or delete it. It tells the person once, in plain words, keeps the old file where it is, and starts with an empty workspace only after that notice.
5. **Given** the Mac is signed in to account A with unsent changes or open sync issues, **When** a sign-in (for example "Sign in again" after the session ended) resolves to a different account B, such as an account deleted and created again with the same email, **Then** it is refused with "Sign out first to use another account." (as on the iPhone), and nothing from A is sent to B.

---

### User Story 5 - Archive a project without losing its tasks, and bring it back (Priority: P3)

Archiving a project hides it from active navigation but keeps its tasks attached, and it can be unarchived with its tasks intact. This already happens on the Mac today, and after this feature it works the same on Mac, iPhone and web. A project's desired outcome, written on the Mac, is kept with the project on the account.

**Why this priority**: without it, signing in would quietly change how archive behaves on the Mac (tasks would lose their project) and would drop desired outcomes. It is lower priority because few projects are archived at any time.

**Independent Test**: archive a project with tasks on any client and see that its tasks keep their project on every client. Unarchive it on another client and see the project back in active navigation with the same tasks. Set a desired outcome on the Mac, edit the project's name on the web, and see that the outcome is unchanged on the Mac.

**Acceptance Scenarios**:

1. **Given** a project with tasks, **When** it is archived on any client, **Then** it leaves active navigation everywhere, its tasks keep their project membership, and no task changes list, completion or trash state.
2. **Given** an archived project, **Then** no task can be newly added to it on any client; tasks already in it can be edited without losing their membership.
3. **Given** an archived project, **When** the person unarchives it on the Mac, iPhone or web, **Then** it returns to active navigation everywhere with the same tasks.
4. **Given** a project archived before this feature (its tasks were already detached by the old behaviour), **When** it is unarchived, **Then** it returns empty with one neutral line: it was archived before projects kept their tasks, and those tasks are still in their lists (FR-027). Nothing says tasks were lost, because nothing is lost by this change.
5. **Given** a project with a desired outcome set on the Mac, **When** it is renamed or recoloured on the iPhone or web, **Then** the outcome is kept unchanged on the account and on the Mac.

---

### Edge Cases

- **Two Macs, or a Mac and an iPhone, editing the same task offline**: last change to reach the account wins per field (FR-011). Changes to different fields of the same task both survive.
- **Same task completed or cancelled on one device and edited on another**: each field ends with the change that reached the account last (FR-011). An edit the account no longer accepts becomes a sync issue in plain words, with a reference id.
- **A task added on the Mac offline to a project archived elsewhere meanwhile**: when the Mac syncs, the task keeps its other fields and lands without that project. The person sees a sync issue saying the project was archived.
- **Duplicate names**: creating a project or tag on the Mac whose name exists on the account (created elsewhere while offline) merges into the existing one instead of failing or duplicating.
- **Same-named archived projects**: merging by name joins active projects only, because an archived project takes no new tasks (ADR-0020). A Mac project archived before sign-in whose name matches an *active* account project joins it: its tasks keep that project, the account's project stays active, and a sync issue says so. An archived Mac project whose name matches only an *archived* account project stays a separate archived project; this is not counted as a duplicate under SC-003. When the old Mac store held an archived and an active project with the same name, the upgrade keeps the archived project's tasks at the top of their lists, because two active projects may not share a name while the tasks are carried over; this is the one change to manual order the upgrade makes (FR-020).
- **The previous Mac store appears again after the update**: an older copy of the app, a restore from backup or a moved file can bring back `local-gtd.json` after the new workspace exists, including after a sign-out has emptied it. It is never imported into, merged with or written over the new workspace. The file is left untouched, and the person is told once where it is (FR-033).
- **Session expires while offline**: nothing is shown until the Mac is online and the server refuses the session. Then the footer shows "Sign in again to sync", and waiting changes are kept and sent after sign-in.
- **Account deleted or purged elsewhere**: the Mac's session fails and it shows "Sign in again to sync". Local data stays on this Mac until the person signs out (FR-001, FR-018).
- **Sign-out with unsent changes**: the person is warned with the count and can keep waiting, or sign out and remove the unsent changes from this Mac (as on the iPhone). It never happens silently.
- **Very large account** (thousands of tasks): the first load does not block the window. Local data, or an empty state with the indicator, is usable at once, and the rest fills in.
- **Clock on the Mac is wrong**: "Synced N min ago" never shows a negative or future time ("just now" instead). Ordering of changes does not depend on the Mac's clock.
- **App open on two Macs, or two copies on one Mac**: two processes never corrupt local data. A second copy on the same Mac brings the running window to the front and quits. Only if it cannot reach the running copy does it say "Brain Buddy is already open." in a plain alert (design X-08).
- **Server unreachable for days**: changes keep waiting with no repeated alerts. The footer stays at its compact warning with the oldest waiting change's age in details.
- **Old iPhone build still in use while the server moves to lossless archive**: the old build keeps working. Tasks in archived projects stay visible and editable, and nothing crashes or drops the project. The new semantics apply on the server whichever client archives.
- **Voice-to-draft and quick capture offline**: unchanged; they never wait for the network.

## Requirements *(mandatory)*

### Functional Requirements

**Account and sign-in (Mac)**

- **FR-001**: The Mac app MUST let a person sign in with the same email and password as iPhone and web, and sign out. Sign-in is the only Mac action that needs a connection.
- **FR-002**: Without signing in, the Mac app MUST keep working fully on this Mac, as today. Nothing is sent anywhere.
- **FR-003**: On the first sign-in on a Mac that has local data, the System MUST add every local task, project, tag, subtask and comment to the account. Projects and tags with the same name as an existing account record MUST become that record, and tasks MUST NOT be merged by title. Nothing is lost or duplicated by the merge. When both projects have a desired outcome, the account's is kept and the Mac's is shown in full as a sync issue, so the person can read and copy it before dismissing it.
- **FR-004**: The Mac MUST refuse to sign in to a different account while it holds unsent changes or open sync issues for the current account (wording as on the iPhone). It MUST NOT send one account's data to another.
- **FR-005**: The Mac MUST keep the session credential in the macOS Keychain, never in a plain file or app preferences. Signing out MUST remove the credential and end the server session when online, or queue the logout when offline.

**Background sync (Mac)**

- **FR-006**: A signed-in Mac MUST sync with no action from the person:
  - on launch;
  - when the app becomes active;
  - within a few seconds of each local change;
  - when the network comes back;
  - periodically while the app is running, at least once every 60 s, also when its window is not frontmost.
  - A "Sync now" command MUST exist (menu and status popover) but MUST never be needed.
- **FR-007**: The Mac MUST sync all of these:
  - tasks with all their fields: title, notes, list, Waiting's waiting-for, project, tags, dates, priority, completion, cancellation. A task's position in a list is assigned by the account when the task is created or moved; the Mac never sends an order. No client deletes or reorders a task today, so neither is synced;
  - subtasks and comments;
  - projects: name, colour, archive state, desired outcome;
  - tags: name, deletion (tags have no colour on any client).
- **FR-008**: Every Mac change MUST apply locally at once and be kept durably until the account has confirmed it. This holds across quit, relaunch, crash and restart. Retries MUST NOT apply a change twice.
- **FR-009**: Incoming changes MUST NOT do any of the following:
  - move the person's current selection, scroll position or keyboard focus;
  - overwrite text the person is editing and has not saved;
  - move the row under the pointer while the person is pointing at or editing it.
- **FR-010**: Work on the Mac MUST never wait on the network. Capture, quick-capture hotkey, voice-to-draft, Smart Add parsing, edits and the Mac's local Waiting/Someday/Project reviews MUST work identically online and offline.
- **FR-011**: Conflicts MUST resolve exactly as they do on the iPhone today:
  - the change that reaches the account last wins, per field;
  - a change the account rejects becomes a visible sync issue, never a silent drop;
  - a create whose reply was lost MUST NOT produce a duplicate.

**Compact status and errors (Mac and iPhone)**

- **FR-012**: The Mac MUST show sync state as one short line of words in the sidebar footer (where "Stored on this Mac" is today), never a colour alone. The states and wording are:

  | State | Wording |
  |---|---|
  | Account-less | "On this Mac · Sign in to sync" |
  | Signed in, first sync not finished | "Not synced yet" |
  | Synced | "Synced just now" / "Synced N min ago" / "Synced N h ago" / "Synced yesterday" / "Synced N days ago" (2–6 days) / "Synced on <date>" |
  | Changes waiting while online | the synced line plus " · N changes waiting", once a change has waited longer than 10 s |
  | Offline | "Offline · N changes waiting", or "Offline" when nothing is waiting |
  | Session ended | "Sign in again to sync" |
  | Failing | "Couldn't sync · Retry" |
  | Rejected changes | "N changes couldn't sync" |

  The relative time MUST refresh at least once a minute.
- **FR-013**: While a sync runs longer than 1 s, the Mac MUST show only a small activity indicator beside the status line, kept for at least 0.5 s once shown. Shorter syncs show nothing. It MUST NOT change the line's text, open a sheet, dialog or alert, take focus, or disable any control.
- **FR-014**: Transient failures MUST be retried automatically and shown only through the indicator. A failure MUST surface as the compact "Couldn't sync" line only once sending or loading has kept failing for 60 s, and it MUST clear itself after the next successful sync. The exception is an ended session, which surfaces at once (FR-012).
- **FR-015**: Every surfaced failure of a request to the server, and every sync issue, MUST carry a reference id the person can see and copy. The same id identifies the failed request in server logs. A purely local or offline failure (no request reached the server) carries none.
- **FR-016**: Activating the status line MUST open a small, non-modal popover:
  - the exact time of the last sync;
  - the number of changes waiting and the age of the oldest;
  - any sync issues, each in plain words with its reference id and a dismiss action;
  - "Sync now";
  - the signed-in email and "Sign out".
  - It MUST close with Esc or a click outside, MUST be fully keyboard-operable and MUST announce its content to VoiceOver.
- **FR-017**: Routine sync MUST never show a modal dialog, alert, notification, sound or badge on any platform. The only sync dialogs allowed are the ones a person starts or a one-time notice:
  - sign-in;
  - sign-out confirmation: "Sign out?" when nothing is unsent, because the account's data leaves this Mac, or the unsent-changes warning (FR-018), including its "Couldn't sign out" error;
  - account switch refusal (FR-004);
  - the one-time upgrade notices (FR-022, FR-033);
  - the "already open" alert, shown only when a second copy cannot reach the running one (X-08).

  When signing in cancels a pending account deletion, the sign-in sheet says so before it closes, as the iPhone does. This is not a separate dialog.
- **FR-018**: Signing out with unsent changes MUST warn with the count and offer two choices: keep the changes (cancel sign-out) or sign out and remove them from this Mac. This matches the iPhone. Open sync issues never reached the account either, so every sign-out confirmation MUST also name how many of them will be removed, on Mac and iPhone alike.
- **FR-019**: On iPhone, the list-screen sync status MUST use the same states, the same wording (with "iPhone" for "Mac") and the same compact form as the Mac: words, a small activity indicator during sync, and failures only after 60 s. It MUST NOT use a dialog. The iPhone Settings Sync section and Sync issues screen stay as they are, with the same wording. The one exception is "Sync now": on both platforms it is never disabled by a running sync, and a press while one runs joins it or queues a single follow-up (single-flight).

**Upgrade of the local Mac store**

- **FR-020**: On first launch after the update, the Mac MUST carry every record of the existing local store into the new local workspace without loss: tasks, projects, tags, subtasks, comments, manual order, project desired outcomes, archive state, and the Mac's Waiting / Someday / Project review marks. Values are carried in the form the account stores them (for example "№" becomes "No" in a name). A value the new workspace cannot hold as it was (a name that collides only in that form, or text over a length limit) is adjusted by a fixed rule that keeps its full text, and every adjustment and every record that could not be carried is listed in a report on this Mac. Nothing is dropped silently: the previous file keeps the original.
- **FR-021**: The upgrade MUST keep the previous store file untouched until the new workspace has been written and verified. The previous file is then kept as a backup for at least 30 days, or until the person signs out, whichever is later. If the person never signs out, the backup is kept.
- **FR-022**: If the previous store cannot be read, the Mac MUST NOT overwrite or delete it. It MUST tell the person once in plain words where the old file is, and only then start with an empty workspace.
- **FR-023**: The Mac's Waiting / Someday / Project review marks MUST stay on this Mac (not synced), keep working as today, and survive sign-in and sign-out, until weekly review (020) replaces them.

**Lossless project archive and desired outcome (all clients)**

- **FR-024**: Archiving a project MUST keep every task's project membership and change no task's list, completion or trash state, on every client and on the server (ADR-0020).
- **FR-025**: An archived project MUST leave active navigation on every client. No task may be newly assigned to it. A task already in it MUST keep that membership when edited for other fields.
- **FR-026**: A person MUST be able to unarchive a project on Mac, iPhone and web. It returns to active navigation with the membership it had when archived.
- **FR-027**: Projects archived before this feature MUST stay as they are. Their tasks were detached by the old behaviour, and unarchiving them returns an empty project. When such a project is empty, every client MUST show one neutral line saying it was archived before projects kept their tasks and that those tasks are still in their lists. The System therefore MUST know which projects were archived before this feature.
- **FR-028**: A project MUST be able to carry an optional desired outcome, as on the Mac today. It is synced with the project and kept unchanged when another client edits the project's other fields. It is included in the account's ZIP export and removed by account purge. Showing or editing it on iPhone and web is not required by this feature.

**Privacy and observability**

- **FR-029**: The Mac MUST send nothing to the server until the person signs in. The one exception is ending a session the person opened earlier on this Mac (a queued logout, including the session of the previous version's sign-in), which carries no task data. After sign-in it sends only what FR-007 lists. Voice audio and voice transcription stay on the Mac.
- **FR-030**: Logs and metrics from the Mac, the iPhone and the server MUST carry only ids, counts, timings and error classes. They MUST never carry task, project or tag text, comments, desired outcomes or the person's email.
- **FR-031**: Requests from the Mac MUST identify the client type and version, as the iPhone does, so that server-side failures can be attributed to Mac builds.
- **FR-032**: So that SC-001 holds in every direction, the iPhone while it is in the foreground and the web while its tab is visible MUST also fetch changes made elsewhere at least every 60 s, with no action from the person. Neither shows anything for it beyond FR-012/FR-019 on the iPhone.
- **FR-033**: The upgrade of FR-020 MUST happen at most once, into a new workspace that nothing else has written. A previous-version store that appears after the new workspace exists MUST NOT be imported into it, merged with it or written over it, and MUST NOT be renamed or deleted. The Mac MUST tell the person once, in plain words, where that file is.

### Key Entities

- **Mac local workspace**: the Mac's copy of the person's tasks, projects, tags, subtasks and comments, plus the changes not yet confirmed by the account and any sync issues. Account-less, it is the whole data set; signed in, it mirrors the account.
- **Waiting change**: one local change, kept until the account confirms it, with an identity that makes a retry safe.
- **Sync issue**: a change the account would not accept, with its plain-words description, reference id and time; dismissible by the person.
- **Sync status**: the single state the status line shows (FR-012), with the time of the last successful sync.
- **Project** (changed): gains an optional **desired outcome** and lossless archive/unarchive (FR-024 – FR-028).
- **Mac review marks**: the Mac's local Waiting / Someday / Project "reviewed" receipts; device-local, unchanged.
- **Previous Mac store backup**: the pre-upgrade local file, kept per FR-021.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With two signed-in clients open and online, a change made on one appears on the other within 60 s in at least 95% of checks. The check uses Mac ↔ iPhone and Mac ↔ web, in both directions, across all record types of FR-007.
- **SC-002**: In the offline matrix (offline edits, quit and relaunch offline, lost replies, reconnect), 0 changes are lost and 0 are applied twice.
- **SC-003**: Upgrading a populated local Mac store keeps 100% of its records (FR-020). A first sign-in into an account with overlapping names produces 0 duplicate projects or tags and 0 missing records on either side.
- **SC-004**: In a scripted session covering every sync state, routine sync opens 0 dialogs, alerts or sheets and takes focus 0 times. 100% of surfaced failures of a request to the server, and of sync issues, show a reference id (FR-015).
- **SC-005**: Transient failures that recover within 60 s produce 0 visible warnings (only the activity indicator).
- **SC-006**: Archive and unarchive on any client keep 100% of the project's task memberships, on every client.
- **SC-007**: The owner uses Mac, iPhone and web on one account for one week of normal work. They never need "Sync now", and they report no moment where the Mac and iPhone disagreed after both were open and online for a minute.

## Assumptions

- The iPhone's existing sync behaviour (offline queue, safe retries, per-field last-change-wins, sync issues, account linking with merge by name) is the reference. The Mac adopts the same behaviour rather than inventing its own; how it is shared is a planning decision.
- Sync runs only while the Mac app is running. No login item or background agent; a closed app catches up on the next launch.
- Periodic fetching while the app is open is enough at today's scale. No real-time push channel and no backend change feed are added.
- Server-side session auth, invite-gated signup and account management stay as they are. Signup on the Mac is not required, since accounts are created by invite on the web.
- ADR-0020 (accepted) defines the lossless archive. This feature implements it on the server and the clients; it does not re-decide it.
- The web stays online-only and already shows request failures with a reference id. It gets no sync status line.
- No AI, paid provider or new consent is involved. Signing in is the person's explicit act to sync.
- The Mac app stays a locally built app (no App Store, signing or notarisation work), as today.
- The server stamps creation, completion, cancellation and waiting-since times itself. After the Mac's first sign-in, tasks completed on the Mac before the upgrade show the upload day as their completion date in History, and a Waiting task's age, a task's created date and a cancelled date restart at the upload day too, as the iPhone's account-less upload does today. The Mac's review marks do not depend on these times, so they stay valid. Order, due dates and every other field are kept.
- The previous Mac version could sign in to the web account in a hidden online mode. Its session is ended and its stored cookie removed at the first launch of the new version (FR-005, FR-029).
- After a local rebuild, macOS may ask once to allow access to the saved sign-in. Brain Buddy only lets that system prompt appear during a sign-in the person started, never during routine sync (FR-017). Preserving original timestamps would need the server to accept client times, which is out of scope.
- The pre-upgrade backup (FR-021) holds only the person's own pre-upgrade Mac data, a copy of which reaches the account at the first sign-in. It may outlive a sign-out, and without a sign-out it stays; data retention documents it, and the sign-out confirmation says until when it stays.
- The upgrade carries every record a person can see. It does not carry deleted tags, the old store's internal retry receipts, or the time a comment was last edited: the comment's current text is carried. The import report counts what was skipped.
- 020 PR-06 adds a sidebar row to the Mac app before this feature's Mac UI lands. The two are sequenced, not merged.
