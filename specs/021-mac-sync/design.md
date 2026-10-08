# Design: Mac ↔ backend sync

**Feature**: `specs/021-mac-sync/`
**Spec**: `spec.md` (Clarifications settled: 2026-10-06)
**Screens**: `design/*.html`: self-contained static HTML, inline CSS, inline SVG icons, no CDN, no external fonts, no script
**Human sign-off**: approved by Max on 2026-10-06 (see Sign-off).

<!--
  Produced by /speckit-design via the design-architect subagent, after
  /speckit-clarify and before /speckit-plan. This file is load-bearing: the
  plan must cite it, and acceptance-auditor traces criteria through the screen
  and state ids assigned here. Ids are stable forever once written — never
  renumber.

  ADR-0006: the term is Tag. The design CI validator hard-fails on the retired
  term and its at-prefixed form; neither appears in this file or in design/.
-->

## Applicability

This feature has a user-visible surface on three clients, designed below:

- **macOS** (primary): `X-` ids.
- **iPhone**: `M-` ids. Status alignment and archive only; no new iPhone screens beyond the archive changes.
- **Web**: `D-` ids. Archive and unarchive only; the web gets no sync status (spec Assumptions).

The `X-` prefix for Mac surfaces was asked for by the caller of this stage. It
is new to the pipeline. `scripts/render_feature_report.py` (`SCREEN_ID_RE =
[DM]-\d{2}`) does not count `X-` ids yet, so the plan must widen it or the
feature report will under-count screens (see Notes for the plan).

The owner's intent governs every screen: sync runs in the background "as in
other GTD apps". The person hears about it only when something is actually
wrong, in one compact message. Activity is a small indicator that never
interrupts. Nearby a quiet "synced N minutes ago". Nothing should catch the
eye.

### Example data used in every mockup

- Today is Tue 6 Oct 2026, 14:34 local.
- Account `alex@example.com`. Projects "Garden" and "Move flat" are active; "Old flat" (3 open tasks) and "Tax return 2024" (no tasks, archived before this feature) are archived. Tags: calls, errands, deep-work.
- Reference IDs are illustrative UUIDs in the `X-Correlation-ID` format. The Mac sends its own ID on every request (the backend middleware accepts an incoming one), so even a timeout with no reply has an ID that the server logs can match (FR-015).
- The Mac sidebar already contains the 020 PR-06 "Weekly review · coming later" row, which lands first (spec Assumptions).

### The status line, one table for both platforms

FR-012 fixes the wording; FR-019 makes the iPhone use the same wording, with
"iPhone" for "Mac". This table is the single source the X-01 and M-01 screens
draw from.

| state | Mac (X-01) | iPhone (M-01) | shows when | interactive |
|---|---|---|---|---|
| account-less | "On this Mac · Sign in to sync" | "On this iPhone · Sign in to sync" | no account linked | "Sign in to sync" opens sign-in |
| first load | "Not synced yet" + indicator | same | signed in, no sync has finished yet (FR-012) | Mac: words open popover |
| synced | "Synced just now" / "Synced N min ago" / "Synced N h ago" / "Synced yesterday" / "Synced N days ago" (2–6 days) / "Synced on 28 Sep" | same | last sync succeeded | Mac: words open popover |
| syncing | the line unchanged + indicator | same | a sync has run longer than 1 s; the indicator then stays at least 0.5 s (FR-013) | — |
| changes waiting, online | synced line + " · N changes waiting" | same | a change has waited longer than 10 s (FR-012) | Mac: words open popover |
| offline | "Offline · N changes waiting" / "Offline" | same | no network path | Mac: words open popover |
| session ended | "Sign in again to sync" | same | the server refused the session (at once) | Mac: popover with "Sign in again" first; iPhone: row opens sign-in |
| failing | "Couldn't sync · Retry" | same | sending or loading has kept failing for 60 s | "Retry" runs Sync now |
| rejected changes | "N changes couldn't sync" ("1 change couldn't sync") | same | the account rejected one or more changes | Mac: popover lists them; iPhone: row opens Sync issues |

Rules shared by both platforms:

- **Precedence**, when several states hold: session ended → rejected changes → failing → offline → changes waiting → synced. The most actionable state wins. The Mac popover always shows all of them.
- **No flicker**: the words change only when the state changes, never because a sync started or stopped. The indicator has a reserved slot.
- **Relative time** refreshes at least once a minute. It never shows a negative or future time ("just now" instead).
- **Failures clear themselves** after the next successful sync. Nothing says "back online".
- **Colour is never the only signal**: attention states use amber words plus a glyph. Offline is a calm state and stays slate.
- **Nothing is disabled by a running sync** (FR-013). "Sync now" stays enabled while a sync runs. A press during a sync joins the running sync, or queues one follow-up sync (single-flight), and shows no extra state. "Sync now" is disabled only when no sync can run: account-less, offline, or session ended.
- The timing constants (1 s, 0.5 s, 10 s, 60 s) belong in shared code so the two apps cannot drift (Notes for the plan).

## Screen inventory

| id | surface | screen | purpose | FR refs |
|---|---|---|---|---|
| X-01 | macOS sidebar footer | Sync status line | Replaces "Stored on this Mac" / "Sign out" with one short line of words, a reserved indicator slot, a hover tooltip with the reference ID, and at most one trailing action | FR-002, FR-012, FR-013, FR-014, FR-015, FR-017, FR-001 |
| X-02 | macOS popover from X-01 | Sync status popover | Exact last-sync time, waiting count and oldest age, sync issues with reference ID, Copy and Dismiss, "Sync now", account email and "Sign out…"; non-modal, Esc/click outside | FR-016, FR-006, FR-011, FR-015, FR-001, FR-029 |
| X-03 | macOS window sheet | Sign-in sheet | Sign in; the one-time "Your tasks on this Mac will be added to your account" explanation; sign-in errors; re-sign-in locked to the account; account switch refused | FR-001, FR-003, FR-004, FR-017 |
| X-04 | macOS alert sheet | Sign-out confirmation | Warns with the count of unsent changes: keep them (Cancel) or sign out and remove them | FR-018, FR-001, FR-005, FR-017 |
| X-05 | macOS app-modal alert at launch | One-time upgrade notice | Only when the old local store can't be read or carried over, when a few records could not be carried ("partly carried over"), or when a previous-version file appears later ("later file"): says so once and says where the file is. The normal upgrade is silent | FR-020, FR-021, FR-022, FR-033, FR-017 |
| X-06 | macOS sidebar + project view | Archived project | Archive keeps tasks; the "Archived projects" section works signed in; the archived project view with "Unarchive"; Mac copy changes from "restore" to "unarchive" | FR-024, FR-025, FR-026, FR-027, FR-028 |
| X-07 | macOS menu bar + toolbar | "Sync now" and account menu items | File › "Sync now" ⌘R; app menu "Sign in…" / "Sign in again…" / "Sign out…"; toolbar "Refresh" removed | FR-006, FR-001 |
| X-08 | macOS system alert | Second copy of the app | Brings the open window forward; alert only if unreachable | edge case "two copies" |
| X-09 | macOS main window content | Tasks couldn't be opened | The Mac's own workspace file cannot be read (damaged, or written by a newer version): explains, offers "Try again" and a confirmed "Start fresh…"; nothing syncs meanwhile (added in planning review c2) | FR-008, FR-017, FR-022 |
| M-01 | iPhone list screens, Lists hub, Settings › Sync | List-screen sync status, aligned | Same states and wording as X-01; indicator instead of "Syncing…"; failure only after 60 s; attention rows act (Retry, Sign in again, open Sync issues); before/after | FR-019, FR-012, FR-013, FR-014, FR-015, FR-017 |
| M-02 | iPhone Projects, Archived projects, project screen | Archived projects with unarchive | Archive copy no longer says tasks lose the project; archived projects open and list their tasks; "Unarchive" by swipe and toolbar | FR-024, FR-025, FR-026, FR-027 |
| D-01 | web sidebar + project page | Archived projects with unarchive | A collapsed "Archived projects" disclosure under Projects; the archived project page with "Unarchive"; archive hint line | FR-024, FR-025, FR-026, FR-027 |

Files:

| file | screens |
|---|---|
| `design/X-01-sidebar-status-line.html` | X-01 (window, every state light and dark, tooltips, the 60 s timeline) |
| `design/X-02-status-popover.html` | X-02 |
| `design/X-03-sign-in-sheet.html` | X-03 (including the first-load window after sign-in) |
| `design/X-04-sign-out-confirmation.html` | X-04 |
| `design/X-05-upgrade-notice.html` | X-05 |
| `design/X-06-archived-project.html` | X-06 |
| `design/X-07-menu-bar-sync-now.html` | X-07 |
| `design/M-01-list-sync-status.html` | M-01 (before and after) |
| `design/M-02-archived-projects.html` | M-02 |
| `design/D-01-archived-projects-web.html` | D-01 |

## State inventory

Rows marked **n/a** say why the state cannot occur. Loading placeholders
appear after 300 ms and are static. "Offline" on Mac and iPhone means the
offline-first behaviour: changes apply locally and wait. On the web, which is
online-only, it means the existing "You're offline" pattern with the action
disabled.

### X-01 — Sidebar footer status line (macOS)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default (synced) | last sync succeeded 1–59 min ago, nothing waiting | One line of 11 pt secondary text, no glyph; empty indicator slot at the trailing edge | "Synced 3 min ago" | FR-012, US3-1 |
| synced: just now | under a minute, or the server time is ahead of the Mac clock | As default | "Synced just now" | FR-012, edge case "clock" |
| synced: hours / days / date | 1–23 h; the previous calendar day; 2–6 days; older | As default. Days and dates show mainly at launch after the Mac was closed, until the first sync ends | "Synced 2 h ago" / "Synced yesterday" / "Synced 4 days ago" / "Synced on 28 Sep" | FR-012 |
| loading (first load) | just signed in; no sync finished yet | Indicator in the slot when the load runs longer than 1 s (FR-013; during a first upload it follows each cycle the same way); the window is usable at once and lists fill in | "Not synced yet" | US1-1, FR-012, FR-013 |
| first load, empty list | just signed in; a list is still empty because the account's tasks have not arrived | Instead of the list's celebratory empty copy, one static neutral line; no spinner over content (planning review c2) | "Your tasks are still arriving." | US1-1, edge case "very large account" |
| sidebar hidden | the sidebar is collapsed (toggle or divider) | Calm states: nothing about sync anywhere. Attention states (session ended, couldn't sync, changes couldn't sync): one compact toolbar item with the same words and glyph, which opens X-02; it appears without taking focus. Nothing in the toolbar whenever all is well (X-07 rule) (planning review c2) | "Sign in again to sync" / "Couldn't sync · Retry" / "2 changes couldn't sync" | FR-012, FR-014, FR-017, US3-4, US3-5 |
| syncing | a sync has run > 1 s | Words unchanged, small indicator appears in the reserved slot and stays at least 0.5 s; shorter syncs show nothing; no control disabled, no focus change | (unchanged line) | FR-013, SC-004 |
| syncing, Reduce Motion | the same, with Reduce Motion on | A static sync glyph instead of the rotating indicator | (unchanged line) | FR-013 |
| empty (first run): account-less | never signed in, or signed out | "On this Mac" opens the popover; "Sign in to sync" in sky opens X-03 | "On this Mac · Sign in to sync" | FR-002, FR-012, US4-2 |
| empty (filtered to nothing) | **n/a**: the line has no filter | — | — | — |
| changes waiting (online) | a change has waited > 10 s (a retry pending) | The synced line gains a suffix | "Synced 3 min ago · 2 changes waiting" | FR-008, FR-012 |
| offline / interrupted | no network path; also after quit and relaunch with waiting changes | Calm slate text, no dialog | "Offline · 3 changes waiting" / "Offline" | US2-1, US2-2, FR-008, FR-010 |
| offline, session expired meanwhile | session expired while offline | Nothing about the session until the server refuses it online | "Offline · N changes waiting" | edge case |
| session ended | the server refused the session | Amber words + person glyph, at once; work continues locally | "Sign in again to sync" | FR-012, FR-014, US3-5 |
| transient failure (< 60 s) | server error, timeout, rate limit that recovers | Only the indicator during each attempt; words unchanged | (unchanged line) | FR-014, SC-005, US3-3 |
| error | sending or loading kept failing for 60 s (the attempt at the 60 s mark failed too) | Amber words + warning glyph; "Retry" in sky | "Couldn't sync · Retry" | FR-012, FR-014, US3-4 |
| error, then offline | the network drops after "Couldn't sync" | Offline wins: calm slate words, no "Retry" (it could not act); the failure's start is kept, so back online a failed attempt shows "Couldn't sync" at once | "Offline · 3 changes waiting" | FR-012, FR-014 |
| first upload | just signed in with local or imported tasks still being sent | Stays "Not synced yet" with the indicator until they are all sent; no waiting suffix and no "oldest" age for them | "Not synced yet" | FR-003, FR-012, US4-3 |
| error, retrying | "Retry" pressed or an automatic retry running | Words stay, indicator shows; success goes straight to "Synced just now" | "Couldn't sync · Retry" | FR-013, FR-014 |
| partial failure | the account rejected some changes; the rest synced | Amber words + warning glyph; the words open X-02 with the list | "2 changes couldn't sync" / "1 change couldn't sync" | FR-011, FR-012, US3-6 |
| hover tooltip | pointer rests on the line | Exact time; for failures the reason, start time, the last attempt's time (updated after every attempt, Retry included) and reference ID (copy happens in X-02) | "Last synced today at 14:31. Click for details." / "Couldn't reach Brain Buddy since 14:02. Last tried 14:35. It keeps trying. Reference ID 4e5d9a20-…" | FR-013, FR-015, FR-016 |
| long text / large sidebar text | "Large" sidebar size or a narrow sidebar | Wraps after " · " to a second line; never truncated | "Synced yesterday · 1,284 changes waiting" | FR-012 |
| dark mode | system appearance Dark | Slate-400 words, amber-300 attention, sky-300 action | as light | FR-012 |
| keyboard focus | Tab into the footer | Brand double ring on the words; Space/Return opens X-02 | — | FR-016 |

### X-02 — Sync status popover (macOS)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default (no issues) | click the status words when synced | Last synced, waiting "Nothing", "Sync now" (plain button), email + "Sign out…"; no issues section | "Last synced · Today at 14:31", "Waiting to sync · Nothing" | FR-016 |
| changes waiting | changes waiting | Count and age of the oldest | "Waiting to sync · 2 changes · oldest 40 s" | FR-016, FR-008 |
| loading (a sync is running) | "Sync now" pressed, or any sync running with the popover open | Nothing in the popover changes. "Sync now" stays enabled; pressing it again joins the running sync or queues one follow-up sync (single-flight), with no extra state. The only activity sign is the footer indicator. Times and counts update in place when the run ends | "Sync now" | FR-006, FR-013 |
| empty (first run): signed out | account-less | One explanation and "Sign in…" (primary); no times, no counts, no "Sync now" | "Your tasks are stored on this Mac" / "Nothing is sent anywhere until you sign in. Sign in to use the same tasks on your iPhone and the web." | FR-002, FR-029, FR-001 |
| empty (filtered to nothing) | **n/a**: no filter in the popover | — | — | — |
| partial failure (with issues) | rejected changes exist | A section with the count; each issue: what was attempted, why, reference ID + Copy, time, Dismiss | "Rename “Call the landlord”" / "Couldn't save your change to “Call the landlord”: it was deleted on another device." ; "Add “Order soil” to Next actions" / "Project “Garden” was archived on another device, so the task was added without a project." | FR-011, FR-015, FR-016, US3-6, edge cases |
| error (couldn't sync) | 60 s of failure | Amber notice with start time, plain reason, the last attempt's time, reference ID + Copy; "Sync now" is the retry. A Retry that fails within a second still updates "Last tried", so the person sees it ran | "Couldn't sync since 14:02" / "Brain Buddy didn't answer. Your changes are safe on this Mac, and it keeps trying." / "Last tried 14:35" | FR-013, FR-014, FR-015, FR-016 |
| error, unreachable for days | server unreachable for days | Same notice; only the oldest-age figure grows; no repeated alerts | "Couldn't sync since Sat 3 Oct" / "41 changes · oldest 3 days" | edge case "server unreachable" |
| session ended | session refused | Amber notice, "Sign in again" primary and first in focus; "Sync now" shown **disabled** (as in offline and X-07), never hidden | "Your session ended" / "Sign in again to keep syncing. Your changes stay on this Mac until then." | US3-5, FR-001 |
| offline / interrupted | no network | Neutral notice; "Sync now" disabled, because no sync can run (it is never disabled because a sync is running). After an earlier failure, the details keep its time and reference ID with Copy | "You're offline. Changes are saved on this Mac and sync when you're back online." / "Last failed 14:35 · Reference ID …" | FR-008, FR-010, FR-015 |
| first upload | just signed in; local or imported tasks are being sent | Instead of the waiting line, a calm progress line; no "oldest" age for them | "Adding your tasks to your account · 1,284 left" | FR-003, FR-016, US4-3 |
| outcome kept on account | a merged project already had a desired outcome on the account | An issue row: what happened, then the Mac's own outcome **in full**, selectable, never shortened; "Copy outcome", then a visible **"Discard outcome"** (not "Dismiss"; accessible name "Discard your outcome for “Garden”"). After Discard the row reads "Outcome discarded · Undo" for 5 s, announced politely; Undo restores it; then it goes (planning review c2) | "Desired outcome for “Garden”" / "Kept the desired outcome already on your account. Yours is below, so you can copy it." / (the full outcome) · "Copy outcome" · "Discard outcome" · "Outcome discarded · Undo" | FR-003, FR-015, FR-028 |
| archive not applied at merge | an archived Mac project met an active account project of the same name at first sign-in | An issue row like the others | "Archive project “Old flat”" / "Your account already has an active project called “Old flat”. This Mac's tasks were added to it, and it stays active." | FR-003, FR-024 |
| pre-upgrade backup | the backup from before the update still exists | One quiet line under the account section; "Show in Finder" reveals the file. The date is never in the past: once it has passed the line says when the backup goes (planning review c2) | "Backup from before the update · kept until 5 Nov" / "Backup from before the update · removed when you sign out" / "Backup from before the update · kept because some records couldn't be carried over" · "Show in Finder" | FR-021 |
| details changed during the update | the upgrade adjusted names or long text (an import report exists) | One quiet line; "Show in Finder" reveals the report beside the backup (planning review c2) | "Some details changed during the update." · "Show in Finder" | FR-020 |
| earlier-version file kept | a previous-version file appeared after the update (FR-033) | One quiet line; "Show in Finder" reveals the file; it stays while the file exists | "A file from the previous version is on this Mac. It was not added." · "Show in Finder" | FR-033 |
| long text, many issues | > 3 issues; long titles; long email | Titles quoted on one line, shortened past 60 characters (a kept outcome is the exception, shown in full); the list scrolls inside; popover ≤ 480 pt tall; the email wraps | "7 changes couldn't sync" | FR-016 |
| issue dismissed (not last) | Dismiss on an issue while others remain | The row goes; focus moves to the next issue's Copy, or to the previous issue's when the last row was dismissed; announced politely | — | FR-016 |
| last issue dismissed | Dismiss on the last issue | Section disappears; VoiceOver says "No sync issues"; focus moves to "Sync now", or to "Sign out…" when Sync now is disabled; the footer returns to the synced line | — | FR-016 |
| reference ID copied | Copy | The button reads "Copied" for 2 s, announced politely | "Copied" | FR-015 |
| new issue while open | an issue arrives with the popover open | Appended and announced politely; focus does not move | — | FR-009, FR-016 |
| dark mode + focus order | Dark; Tab | Numbered order (completed in planning review c2): attention action → each issue's Copy → Copy outcome → Dismiss / Discard outcome → Sync now (skipped when disabled) → offline last-failure Copy → Sign out… → the "Show in Finder" links (backup, report, earlier-version file) | — | FR-016 |

The "partial failure" example "it was deleted on another device" is a defensive path: no client deletes a task and the server has no project delete route, so it occurs only for a foreign or purged record (contracts/kit-commands.md §5). The copy stays for that path; the archived-elsewhere example is the reachable one. The rows "error, then offline", "first upload", "outcome kept on account", "archive not applied at merge", "pre-upgrade backup", "earlier-version file kept" and "issue dismissed (not last)" were added by planning review c1 and have no mockup: they reuse the layout of the rows above.

### X-03 — Sign-in sheet (macOS)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | "Sign in to sync" / "Sign in…" with no tasks on this Mac | Title, one line, Email, Password, collapsed "Advanced"; "Sign in" default, disabled until filled | "Sign in to Brain Buddy" / "Use the same tasks on this Mac, your iPhone and the web." | FR-001 |
| first sign-in with local tasks | the Mac holds account-less tasks | A sky info box above the fields, shown only in this case | "Your tasks on this Mac will be added to your account. Projects and tags with the same name become one. Tasks are never merged by title, so nothing is lost or doubled." | FR-003, US4-3, SC-003 |
| loading (signing in) | Sign in | Fields read-only; button "Signing in…" with the indicator; **Cancel and Esc stay enabled until the account is linked**: cancelling stops the request, keeps the typed values, puts focus in Password and changes nothing. From the moment the kit links the account (a decision made once, in `commit()`, just before the link is written) Cancel and Esc are disabled, the sheet still reads "Signing in…" while the first sync runs, and it closes signed in (as delivered 2026-10-08). Other windows and the quick-capture panel stay usable | "Signing in…" | FR-001 |
| error: no answer | online, but the request got no reply in time | Amber message above the fields with the reference ID; focus to Password | "Brain Buddy didn't answer. Try again." | FR-001, FR-015 |
| error: couldn't save sign-in | the sign-in succeeded but this Mac could not store it in the Keychain | Amber message with the reference ID; nothing is linked | "Brain Buddy couldn't save your sign-in on this Mac. Try again." | FR-001, FR-005, FR-015 |
| error: wrong password | 401 | Amber message above the fields with the reference ID; focus to Password with its text selected | "Check your email and password." | FR-001, FR-015 |
| error: too many attempts / server | 429 / 5xx | Server's plain reason + reference ID | "Too many attempts. Try again in a few minutes." | FR-001, FR-015 |
| offline | no network | Reason, no reference ID, and the reassurance | "Can't reach the server. Check your connection." / "Signing in is the only thing that needs a connection. Everything else keeps working on this Mac." | FR-001, FR-010 |
| sign in again (session ended) | "Sign in again" | Email and server shown read-only; focus in Password; footer line | "Sign in again" / "Your session ended. Sign in again to keep syncing. Your changes are kept on this Mac until then." / "Sign out first to use another account." | US3-5, FR-004 |
| account switch refused | credentials belong to another account while this Mac holds unsent changes or open issues | Amber message; sheet stays open; nothing sent | "Sign out first to use another account." / "Changes from the other account are still waiting on this Mac." | FR-004, US4-5 |
| long text / invalid server address | Advanced expanded; long values; bad URL | Fields scroll horizontally; the rule is stated; "Use the default server" | "Use an https server address. http works only for localhost." | FR-001 |
| dark mode | Dark | As light | as light | — |
| signed in, account deletion cancelled | the sign-in succeeded and cancelled a pending account deletion | Before closing, the same sheet replaces its form with a sky note (not a separate dialog). Focus moves to the note and VoiceOver reads it. "OK" is the only button; Return or Esc closes the sheet. Sync has already started behind it | "Your account deletion was cancelled" / "Signing in cancels a deletion you requested in the last 14 days. Delete your account again on the web if you still want to." · "OK" | FR-017 |
| after sign-in: first load | success | Sheet closes, no toast; window usable at once; lists fill in when the first load lands (all at once, not page by page; planning review c2); an empty list meanwhile reads "Your tasks are still arriving." (X-01 "first load, empty list"); X-01 shows "Not synced yet", with the indicator once the load lasts longer than 1 s (FR-013); a very large account never blocks the window | — | US1-1, edge case "very large account" |
| partial failure | some local records rejected during the first upload | Those become sync issues (X-02); everything else is on the account | (X-02 copy) | FR-003, FR-011 |
| empty (filtered to nothing) | **n/a** | — | — | — |

### X-04 — Sign-out confirmation (macOS)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default: unsent changes | "Sign out…" with N > 1 waiting | Alert sheet; "Cancel" default; "Sign out and remove" destructive (rose text) | "3 changes haven't synced yet." / "Sign out and remove them from this Mac? They haven't reached your account." | FR-018, US1-6 |
| one change, offline | N = 1, offline | Singular; one extra sentence | "1 change hasn't synced yet." / "Sign out and remove it from this Mac? It hasn't reached your account. You're offline, so it can't be sent now." | FR-018 |
| session ended with unsent changes | session refused, N waiting | Says how to send them first, without a third button | "5 changes haven't synced yet." / "Sign out and remove them from this Mac? To send them first, choose Cancel and sign in again." | FR-018, US3-5 |
| nothing unsent | "Sign out…" with nothing waiting | Confirmed, as on the iPhone, because the account's data leaves this Mac (approved) | "Sign out?" / "Your tasks are removed from this Mac. They stay in your account." · "Cancel" · "Sign out" | US1-6, FR-017 |
| open sync issues | any of the variants above while issues are open | One more sentence after the variant's text, same buttons; the iPhone confirmation adds the same sentence with "iPhone" | "2 changes that couldn't sync will also be removed from this Mac." / "1 change that couldn't sync will also be removed from this Mac." | FR-011, FR-018 |
| backup kept | any variant while the pre-upgrade backup exists and this sign-out does not delete it | One more sentence, last, with the date it can be deleted; once that date has passed but the backup is still kept (a record not carried, or a sign-out during the first upload), the same sentence without a date (added after `/speckit-analyze`) | "A copy of your tasks from before the update stays on this Mac until 5 Nov." / "A copy of your tasks from before the update stays on this Mac." | FR-021 |
| backup removed | this sign-out will delete the backup (its date has passed, nothing unsent from the first upload, every record carried) | One more sentence, last, instead of "backup kept"; the deletion is never silent (planning review c2) | "The copy of your tasks from before the update will also be removed from this Mac." | FR-021 |
| unsaved edit or capture draft | "Sign out…" while a task edit is unsaved or the capture draft is not empty | First the existing discard confirmation for that draft (today's guard); X-04 opens only after "Discard" or when there is nothing to discard. Cancel there cancels the sign-out (planning review c2) | (the existing discard confirmation copy) | FR-018, constitution V |
| changes arrived while open | a capture or other change, or a new sync issue, appeared while X-04 was showing | At confirm nothing is signed out; X-04 shows again with the new count, focus on "Cancel". "Sign out and remove" removes only what the dialog named (planning review c2); as delivered (2026-10-08) "named" is by operation id and content, so a different change with the same count, or an edit folded into a named change, also shows X-04 again with the real count and nothing is removed. Edits made while a confirmed sign-out runs are refused with words and the typed text is kept | "4 changes haven't synced yet." (the count updated) | FR-018 |
| during the first upload | signed in moments ago; local or imported tasks are still being sent | The unsent-changes variant with their count, since they have not reached the account | "1,284 changes haven't synced yet." / "Sign out and remove them from this Mac? They haven't reached your account." | FR-018, US4-3 |
| error | local data couldn't be removed | Stays signed in; nothing removed; no reference ID | "Couldn't sign out" / "Brain Buddy couldn't remove your tasks from this Mac, so you're still signed in. Nothing was removed." | US1-6 |
| empty (first run) after sign-out | confirmed | Immediate: empty account-less workspace; selection resets to Inbox; footer account-less; the logout is queued if offline | "On this Mac · Sign in to sync" | US1-6, FR-005, FR-002 |
| loading | **n/a**: sign-out is local and immediate (FR-005) | — | — | — |
| empty (filtered) / partial failure | **n/a**: a single local action | — | — | — |

### X-05 — One-time upgrade notice (macOS)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default: normal upgrade | first launch after the update, store readable | **No notice.** Tasks as before, account-less footer | "On this Mac · Sign in to sync" | FR-020, FR-021, US4-1, US4-2, SC-003 |
| loading | carrying over a large store takes > 300 ms | Static list placeholders; no progress text | — | FR-020 |
| error: corrupt | old file unreadable | App-modal alert before the workspace opens; selectable path; "Continue" default, "Show in Finder" | "Brain Buddy couldn't read your earlier tasks" / "The file from the previous version was left exactly as it was. It's here:" / "~/Library/Application Support/BrainBuddyMac/local-gtd.json" / "Brain Buddy will start with an empty workspace. Keep the file if you'd like help recovering it." | FR-022, US4-4 |
| error: newer version | file written by a newer build | Same alert, other reason | "They were saved by a newer version of Brain Buddy, so this version left the file exactly as it was." / "Install the newer version to open the file again." | FR-022 |
| error: couldn't carry over | the file was read, but the carried-over copy did not match it (a fault in Brain Buddy, not in the file) | Same alert; it says the file is fine | "Brain Buddy couldn't carry over your earlier tasks" / "Your file is fine and was left exactly as it was. It's here:" / path / "This is a problem in Brain Buddy. Brain Buddy will start with an empty workspace. Keep the file: it still has all your earlier tasks." (planning review c2: no promise that a later version carries it over) | FR-021, FR-022 |
| partly carried over | the file was read and imported, but a few records could not be carried | Same alert, once; the workspace opens with everything else; the report and the untouched previous file stay on this Mac (planning review c2) | "Brain Buddy carried over your earlier tasks, except a few it couldn't read" / "They're listed in a report next to the file from the previous version, which stays on this Mac. It's here:" / path · "Continue" · "Show in Finder" | FR-020, FR-022 |
| later file | a file from the previous version appears after the new workspace exists (an older copy ran, a restore, a moved file) | Same alert, once per Mac, before the window opens; the workspace is unchanged; afterwards X-02 keeps a quiet line | "Brain Buddy found tasks from the previous version" / "An older copy of Brain Buddy saved tasks on this Mac after the update. They were not added here, and the file was left exactly as it was. It's here:" / path / "Your current tasks are unchanged." · "Continue" · "Show in Finder" | FR-033, FR-017 |
| long text / dark | long home path; Dark | The path wraps anywhere; the alert grows in height only | as above | FR-022 |
| empty (first run) after Continue | Continue or Show in Finder | Only now the empty workspace starts; notice recorded as seen | — | FR-022 |
| interrupted | app quit while the notice is open | Not seen: shown again at next launch | — | FR-022 |
| partial read | some records readable, some not | Revised in planning review c2 (this interpretation was the plan's, not a sign-off decision): a file that decodes is imported; values the new workspace cannot hold as they were are adjusted by rule and listed in the import report (silent, X-02 line); a record that still cannot be carried makes the "partly carried over" notice. Only a file that does not decode is "corrupt". Nothing is half-imported silently and nothing is stranded | see "partly carried over" | FR-020, FR-022 |
| empty (filtered) | **n/a** | — | — | — |

### X-06 — Archived project (macOS)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default: archived project open | an archived project selected | Title + "Archived" chip + "Unarchive" button; its tasks (editable); outcome read-only; no "Add a task"; quiet line | "Archived project · 3 open tasks" / "Unarchive this project to add tasks to it." | FR-024, FR-025, FR-026, FR-028 |
| sidebar section | any archived projects | "Archived projects · 2", collapsible, starts collapsed, state remembered; now shown signed in too; right-click → "Unarchive project" | "Archived projects · 2" / "Unarchive project" | FR-025, FR-026 |
| archiving (sidebar) | right-click active project → "Archive project", or File › "Archive project" | No confirmation (reversible); the project moves to Archived projects; tasks keep it. Disabled, with the existing help text, while a task edit is unsaved or the capture draft is not empty | "Archive project" / "Add or clear the current task draft before archiving" | FR-024, SC-006 |
| archived (just now) | the open project was archived | Selection stays on it; the view becomes the archived view with chip and "Unarchive"; the Archived section expands to show its row; focus to the title | — | FR-024, FR-025 |
| unarchive refused: name in use | "Unarchive" while another active project has the same name | Inline message under the title; no Retry; "Rename…" renames the archived project; focus stays on "Unarchive". Refused at once on this Mac; it becomes an X-02 issue only if the clash appeared while offline | "Another active project is already called “Old flat”. Rename one first." · "Rename…" | FR-026 |
| rename archived project | "Rename…" in the refusal | The existing rename sheet (the sidebar's "Rename…") for the archived project, current name selected. Saving: the sheet's button reads "Saving…" while the local write runs. Error: the sheet's existing duplicate-name error under the field (the kit's copy, unchanged), focus kept in the field. Success: the sheet closes, the refusal message clears, focus returns to "Unarchive"; the person presses Unarchive again (no automatic unarchive) (planning review c2; error copy aligned with the kit after `/speckit-checklist`) | "Rename project" / "A project named Old flat 2 already exists." | FR-026 |
| archiving (project review) | "Archive completed project…" | Existing confirmation, copy unchanged | "Archive this completed project?" / "The project and its tasks remain available in Archived projects." | FR-024 |
| task of an archived project elsewhere | a Next action whose project is archived | Stays in its list; group header, row label and picker entry say "archived", as the kit's `projectDisplay` label | "Old flat · archived" | FR-024, FR-025 |
| capture into an archived project | Smart Add names an archived project | Existing block, new verb | "Unarchive “Old flat” before adding a task to it." | FR-025 |
| unarchived | "Unarchive" | Chip and button go; "Add a task" and "Edit outcome" return; project back in Projects; focus to the title; no toast | — | FR-026, US5-3 |
| empty: archived before this change | archived pre-feature, no tasks (also after unarchiving, until it gets a task) | Empty state with one neutral grey line; nothing says tasks were lost | "No tasks in this project" / "Unarchive this project to add tasks to it." / "Archived before projects kept their tasks, so none are listed here. Those tasks are still in their lists." | FR-027, US5-4, ADR-0020 |
| empty (filtered to nothing) | search or priority filter matches nothing | Existing filtered empty state | "No matching tasks" / "Clear the search or priority filter to see this project's tasks." | — |
| offline / interrupted | offline, or quit before sending | Applies at once; waits like any change | "Offline · 1 change waiting" | FR-008, FR-010 |
| error | local write failed | Existing inline error with Retry; focus moves to "Retry" and the message is announced (planning review c2) | "Couldn't unarchive “Old flat”. Try again." | FR-026 |
| partial failure | the account rejected the archive or unarchive | Returns to the account's state; issue in X-02 with reference ID; the copy says where the project stands and what to do (planning review c2) | "Unarchive project “Old flat”" / "Brain Buddy couldn't unarchive it, so it's still archived. Try Unarchive again later." (archive: "Brain Buddy couldn't archive it, so it's still active. Try again later.") | FR-011, FR-015 |
| loading | > 300 ms (local) | Static placeholders | — | — |
| dark mode | Dark | As light | — | — |

### X-07 — Menu bar "Sync now" and account items (macOS)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | signed in, online | File › "Sync now ⌘R" enabled (also while syncing, and as the retry while failing) | "Sync now" | FR-006 |
| unavailable | account-less, offline, or session ended | "Sync now" disabled, never hidden | "Sync now" (dimmed) | FR-006 |
| app menu, signed in | — | "Sign out…" opens X-04 | "Sign out…" | FR-001, FR-018 |
| app menu, account-less / session ended | — | "Sign in…" opens X-03; after a session ended "Sign in again…" and "Sign out…" | "Sign in…" / "Sign in again…" | FR-001, US3-5 |
| toolbar | always | Today's "Refresh" button removed; nothing about sync in the toolbar | — | FR-006, SC-007 |
| keyboard | ⌘R anywhere in the main window, also while typing | Same as "Sync now" in the popover; the popover does not open | — | FR-006 |
| dark mode | Dark | System menus | — | — |
| loading / empty / error / partial / offline | **n/a**: the menu reflects X-01 and shows no message of its own | — | — | — |

### X-08 — Second copy of the app (macOS, added 2026-10-06 from plan gap G-8)

There is no mockup: it is a standard system alert.

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | a second copy launches while one is running | Nothing new: the running window comes to the front and the second copy quits | — | edge case "two copies" |
| unreachable | the running copy cannot be brought forward | One standard alert, default button "OK", then the second copy quits | "Brain Buddy is already open." / "Switch to the open window to keep working." | edge case "two copies", FR-017 |
| loading / empty / error / partial / offline / dark | **n/a**: system alert | — | — | — |

### X-09 — Tasks couldn't be opened (macOS, added in planning review c2)

There is no mockup: it follows the iPhone's existing load-error view (`ios/BrainBuddy/App/RootView.swift`, "We couldn't open your tasks") in the Mac's main window, in place of the lists.

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | `store.json` cannot be read, or was written by a newer version | The lists are replaced by one calm panel; the sidebar footer shows nothing about sync; nothing is sent; "Try again" is the default button | "We couldn't open your tasks" / "Your tasks are still on this Mac and nothing was changed." + the reason · "Try again" · "Start fresh…" | FR-008, FR-022 |
| loading | "Try again" pressed | The button reads "Trying again…" and is not pressable twice | "Trying again…" | — |
| confirm start fresh | "Start fresh…" | A person-started confirmation; "Keep trying" is the default | "Set the file aside and start fresh?" / "The unreadable file stays on this Mac, set aside where Brain Buddy won't use it. You start with empty lists; tasks you synced come back when you sign in." · "Keep trying" · "Set aside and start fresh" | FR-017 |
| after start fresh | confirmed | Empty account-less workspace; footer account-less; the set-aside file is removed by the next sign-out | "On this Mac · Sign in to sync" | FR-002 |
| error | setting the file aside failed | The panel stays with the reason | (the kit's message) | FR-022 |
| empty / partial / offline / dark | **n/a** beyond the above: nothing loads, nothing syncs; dark follows the system | — | — | — |

### M-01 — List-screen sync status, aligned (iPhone)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| before (today, reference only) | — | "Syncing…" text during every sync; "Sync failed — reason" + "Reference ID: …" at once; em dash; cloud glyphs | "Syncing…", "Offline — 3 changes waiting", "Sync failed — The server had a problem (HTTP 503). Try again later." | — |
| default (synced) | last sync succeeded | One centred 13 pt line at the end of the list; not interactive | "Synced 3 min ago" | FR-019 |
| loading: first sync after sign-in | signed in, nothing synced | Line with the indicator | "Not synced yet" | FR-019, FR-012, US1-1 |
| syncing | sync running > 1 s | Words unchanged + indicator, kept at least 0.5 s | (unchanged line) | FR-019, FR-013 |
| syncing, Reduce Motion / Dynamic Type AX5 | settings | Static glyph; line wraps after " · ", centred, never truncated | "Synced 3 min ago · 2 changes waiting" | FR-019 |
| changes waiting (online) | a change waited > 10 s | Suffix | "Synced 3 min ago · 2 changes waiting" | FR-019, FR-012 |
| offline / interrupted | no network | Calm line | "Offline · 3 changes waiting" | FR-019 |
| session ended | session refused | Amber row button with glyph; opens the existing sign-in sheet with the email locked | "Sign in again to sync" | FR-019, US3-5 |
| transient failure (< 60 s) | failure that recovers | Indicator only | (unchanged line) | FR-014, FR-019, SC-005 |
| error | 60 s of failure | Amber row button: Retry runs Sync now. Long-press on the row offers "Copy reference ID", also a VoiceOver custom action on the row (planning review c2); Settings › Sync shows the Reference ID from the first failure on, not only after 60 s | "Couldn't sync · Retry" | FR-014, FR-015, FR-019 |
| error, then offline | the network drops after "Couldn't sync" | Calm offline line, no Retry; Settings › Sync keeps the earlier failure's time and Reference ID with Copy (planning review c2) | "Offline · 3 changes waiting" / Settings: "Last failed 14:35 · Reference ID …" | FR-014, FR-015, FR-019 |
| first upload | just signed in with local tasks still being sent | "Not synced yet" + indicator (FR-013); Settings › Sync shows the progress line (planning review c2) | "Not synced yet" / Settings: "Adding your tasks to your account · 1,284 left" | FR-003, FR-019 |
| partial failure | rejected changes | Amber row button opening the existing Sync issues screen (new on list screens) | "2 changes couldn't sync" | FR-011, FR-019, US3-6, US3-8 |
| empty (first run) | list empty; account-less | Existing empty state, status under it; "Sign in to sync" opens sign-in; that target is at least 44 pt tall (planning review c2) | "Inbox zero" / "On this iPhone · Sign in to sync" | FR-019 |
| empty (filtered to nothing) | filters match nothing | Existing filtered copy, status under it | "No tasks match these filters" | FR-019 |
| Lists hub and Settings › Sync | Lists tab; Settings | Settings row subtitle and the Sync section's status line use the new words; every other Settings row unchanged | "Synced 3 min ago · 2 changes waiting" | FR-019, US3-8 |
| Settings › Sync, sync running | a sync is running with Settings open | "Sync now" stays enabled (FR-019 as amended); a press joins the running sync or queues one follow-up, with no extra state | "Sync now" | FR-019 |
| sign-out with open issues | Settings › Sign out while sync issues are open | The existing confirmation gains the same sentence as X-04 "open sync issues" | "2 changes that couldn't sync will also be removed from this iPhone." | FR-018 |

### M-02 — Archived projects with unarchive (iPhone)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| archive confirmation | Projects › swipe or long-press › Archive | Action sheet; button no longer destructive (not red); existing toast after | "Archive “Old flat”?" / "It leaves your project lists. Its tasks keep the project, and you can unarchive it any time from Archived projects." / toast "Archived “Old flat”" | FR-024 |
| default: Archived projects | Lists hub › Archived | Rows open the project and show counts; swipe "Unarchive" (sky, full swipe allowed); footer | "Archived projects keep their tasks. Unarchive one to add tasks to it again." | FR-025, FR-026 |
| archived project opened | tap a row | Tasks listed and editable; toolbar "Unarchive"; status row; capture files nothing here (as today) | "Archived project · it doesn't take new tasks" | FR-025, FR-026 |
| unarchived | Unarchive | Becomes active; toolbar button and status row gone; toast | "Unarchived “Old flat”" | FR-026, US5-3 |
| empty: archived before this change | pre-feature archived, no tasks (also after unarchiving, until it gets a task) | Empty state with one neutral grey line | "No tasks in this project" / "Unarchive it to add tasks." / "Archived before projects kept their tasks, so none are listed here. Those tasks are still in their lists." | FR-027, US5-4 |
| empty (first run): none archived | all unarchived | Existing screen, new copy; the hub row is hidden when none | "No archived projects" / "Projects you archive are listed here. Unarchive one to bring it back." | FR-026 |
| empty (filtered to nothing) | list filter on the project | Existing filtered copy | "No tasks match these filters" | — |
| offline / interrupted | offline | Applies locally, waits | "Offline · 1 change waiting" | FR-008 |
| error / partial failure | account rejected it | Back to archived; issue in Sync issues with a new description (copy revised in planning review c2) | "Unarchive project “Old flat”" / "Brain Buddy couldn't unarchive it, so it's still archived. Try Unarchive again later." | FR-011, FR-015 |
| unarchive refused: name in use | Unarchive while another active project has the same name | Refused at once, on the device; a short message with "Rename…" for the archived project, no Retry; VoiceOver focus stays on Unarchive. A Sync issue only if the clash appeared while offline | "Another active project is already called “Old flat”. Rename one first." | FR-026 |
| rename archived project | "Rename…" in the refusal | The existing project editor sheet (`ProjectEditorSheet`) for the archived project, name selected; saving disables Save; the sheet's existing duplicate-name error (the kit's copy, unchanged) with VoiceOver focus kept in the field; success closes the sheet, clears the refusal and returns VoiceOver focus to Unarchive; no automatic unarchive (planning review c2; error copy aligned with the kit after `/speckit-checklist`) | "A project named Old flat 2 already exists." | FR-026 |
| task of an archived project elsewhere | Next actions | Group header "Old flat · archived" | "Old flat · archived" | FR-024, FR-025 |
| loading | **n/a**: local store | — | — | — |

### D-01 — Archived projects with unarchive (web)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default: archived project page | archived row clicked | Heading + "Archived" chip + "Unarchive" (secondary); tasks listed (editable); no composer; info line | "Archived projects don't take new tasks. Unarchive it to add tasks." | FR-025, FR-026 |
| sidebar collapsed (default) | page load | Disclosure under Projects with count; hidden when none | "Archived projects 2" | FR-025 |
| archive action | project options on an active project | Existing "Rename" / "Archive" plus one hint line | "Archiving keeps its tasks. You can unarchive it from Archived projects." | FR-024 |
| archived project options | options on an archived row | Only "Unarchive" | "Unarchive" | FR-026 |
| loading | projects query pending > 300 ms | Static skeleton rows | — | — |
| unarchiving | Unarchive clicked | The button stays focusable: `aria-disabled` and a busy label, not `disabled`, so focus does not fall to the page; "Unarchiving…" is announced through a polite status region (planning review c2) | "Unarchiving…" | FR-026 |
| unarchived | success | Page becomes active; project back in Projects; focus to heading; toast | "Unarchived “Old flat”" | FR-026, US5-3 |
| error | request failed | Existing notice pattern with Ref and Retry; the notice is announced (`role=alert`) and focus moves to Retry (planning review c2) | "Couldn't unarchive “Old flat”. It's still archived." + Ref | FR-026, FR-015 |
| unarchive refused: name in use | the server answers 409 because another active project has the name | Notice with Ref and "Rename…" for the archived project; no Retry (it would fail the same way); the notice is announced (`role=alert`) and focus stays on Unarchive | "Another active project is already called “Old flat”. Rename one first." + Ref | FR-026, FR-015 |
| rename archived project | "Rename…" in the refusal | The project options popover opens for the archived project with its name field (the same field active projects use), name selected; Save shows "Saving…"; a clash (another active project has the name: the server answers 409 with the message "Project '<name>' already exists." and `detail` `{"resource": "Project", "id": "<name>"}`) shows that server message with Ref in the popover, focus kept in the field; success closes the popover, clears the refusal and returns focus to Unarchive; no automatic unarchive. Escape closes the popover and returns focus to its trigger (planning review c2; error copy after `/speckit-checklist`, corrected at the targeted review: the web has no rename error string of its own. Today the popover closes on Save and a clash appears only in the page's `role="alert"` notice as "Project 'Old flat 2' already exists. (ref: …)"; this state keeps the same server message and shows it in the popover instead) | "Project 'Old flat 2' already exists." + Ref (the server's message, shown as is) | FR-026 |
| options popover closed with Escape | Escape in any project options popover | Focus returns to the options button that opened it (planning review c2) | — | FR-026 |
| task project picker | the project field of a task in the detail panel | Lists active projects only; for a task already in an archived project, that one project too, labelled "Old flat · archived" and selected. Archived projects never appear as a new choice (FR-025) (planning review c2) | "Old flat · archived" | FR-025 |
| archived (just now) | the open project was archived from its options | The page becomes the archived page; focus to the heading; toast | "Archived “Old flat”" | FR-024, FR-025 |
| offline / interrupted | no connection; request cut off | Offline banner, Unarchive disabled; a cut-off request retries with the same idempotency key | "You're offline. Unarchive is available when you're back online." | FR-026 |
| partial failure | **n/a**: one project command, its tasks unchanged | — | — | — |
| empty: none archived | no archived projects | Disclosure not shown | — | — |
| empty: archived before this change | pre-feature archived, no tasks (also after unarchiving, until it gets a task) | Empty state with one neutral line | "No tasks in this project" / "Unarchive it to add tasks." / "Archived before projects kept their tasks, so none are listed here. Those tasks are still in their lists." | FR-027, US5-4 |
| empty (filtered to nothing) | filter on the project page | Filtered empty copy | "No tasks match this filter" / "Clear the filter to see this project's tasks." | — |
| task of an archived project in Next | Next actions | Project column and group read "archived" | "Old flat · archived" | FR-024, FR-025 |
| narrow (390 px) | drawer layout | Disclosure in the drawer; Unarchive full-width 44 px under the title; no horizontal scroll | as default | FR-026 |

## Affordance → requirement map

Existing controls this feature leaves unchanged (task rows, editors, filters,
Smart Add, pull-to-refresh on iPhone, the iPhone Settings Sync rows) are not
listed.

| screen | affordance | what it does | FR ref |
|---|---|---|---|
| X-01 | Status words (button) | Opens the X-02 popover in every state | FR-016, FR-012 |
| X-01 | Toolbar status item (sidebar hidden, attention states only) | Opens the X-02 popover | FR-012, FR-016 |
| X-01, M-01 | "Sign in to sync" (account-less) | Opens sign-in (X-03 / the iPhone sheet) | FR-001, FR-012, FR-019 |
| X-01, M-01 | "Retry" (failing) | Runs Sync now | FR-012, FR-014, FR-006, FR-019 |
| M-01 | "Sign in again to sync" row | Opens the iPhone sign-in sheet, email locked | FR-019, US3-5 |
| M-01 | "N changes couldn't sync" row | Opens the existing Sync issues screen | FR-019, US3-6 |
| X-02 | "Sign in again" | Opens X-03 locked to the account | FR-001, US3-5 |
| X-02 | "Sign in…" (account-less) | Opens X-03 | FR-001 |
| X-02 | "Copy" beside a reference ID | Copies the ID | FR-015 |
| X-02 | "Copy outcome" (outcome kept on account) | Copies the Mac's own desired outcome before it is discarded | FR-003, FR-028 |
| X-02 | "Discard outcome" and its 5 s "Undo" (outcome kept on account) | Removes the issue and its outcome text; Undo restores it | FR-003, FR-016, FR-028 |
| X-02 | "Dismiss" per issue | Removes the issue once read | FR-016, FR-011 |
| X-02 | "Show in Finder" (pre-upgrade backup; import report; earlier-version file kept) | Reveals the file | FR-020, FR-021, FR-033 |
| X-02 | "Sync now" | Runs a sync now | FR-006, FR-016 |
| X-02 | "Sign out…" | Opens X-04 ("Sign out?", or the unsent-changes warning) | FR-001, FR-016, FR-018 |
| X-02 | Esc / click outside | Closes the popover, focus back to the status words | FR-016 |
| X-03 | Email, Password, "Sign in" | Signs in; first sign-in merges local tasks | FR-001, FR-003 |
| X-03 | "Cancel" / Esc | Closes without change, also while "Signing in…" waits for the login reply (stops the request); disabled once the account is linked and the first sync runs (as delivered 2026-10-08) | FR-001 |
| X-03 | "Advanced" › Server address, "Use the default server" | Chooses the server (today's "API URL", renamed as on the iPhone) | FR-001 |
| X-04 | "Cancel" (default) | Keeps the changes; no sign-out | FR-018 |
| X-04 | "Sign out and remove" | Signs out and removes unsent changes from this Mac | FR-018 |
| X-04 | "Sign out" (nothing unsent) | Signs out after the "Sign out?" confirmation | FR-001, FR-017, US1-6 |
| X-04 | "OK" (error) | Closes; still signed in | US1-6 |
| X-05 | "Continue" | Records the notice as seen; starts the empty workspace (or, for "later file", opens the unchanged workspace) | FR-022, FR-033 |
| X-05 | "Show in Finder" | Reveals the untouched old file; then as Continue | FR-022, FR-033 |
| X-06 | "Archived projects" section (disclosure) | Shows or hides archived projects; in the tab order | FR-025, FR-026 |
| X-06 | "Unarchive" (header) / "Unarchive project" (right-click, File menu) | Unarchives with its tasks | FR-026 |
| X-06 | "Archive project" (right-click; File menu; review sheet) | Archives, keeping tasks | FR-024 |
| X-06, M-02, D-01 | "Rename…" (unarchive refused: name in use) | Renames the archived project so it can be unarchived | FR-026 |
| X-08 | "OK" (unreachable) | Closes the alert; the second copy quits | FR-017, edge case "two copies" |
| X-03 | "OK" (account deletion cancelled) | Closes the sheet; sync is already running | FR-017 |
| X-09 | "Try again" | Reloads the workspace file | FR-022 |
| X-09 | "Start fresh…" → "Set aside and start fresh" | Sets the unreadable file aside (kept until sign-out) and starts an empty workspace | FR-017, FR-022 |
| D-01 | Task project picker | Assigns a task to an active project; shows a task's current archived project, labelled | FR-025 |
| M-01 | Long-press "Copy reference ID" on the "Couldn't sync · Retry" row | Copies the ID | FR-015, FR-019 |
| X-07 | File › "Sync now" ⌘R | Runs a sync now | FR-006 |
| X-07 | App menu "Sign in…" / "Sign in again…" / "Sign out…" | Opens X-03 / X-04 | FR-001 |
| M-02 | "Archive project" (confirmation, existing) | Archives, keeping tasks | FR-024 |
| M-02 | Archived row (tap) | Opens the archived project with its tasks | FR-025 |
| M-02 | "Unarchive" swipe action / VoiceOver custom action / toolbar button | Unarchives | FR-026 |
| D-01 | "Archived projects" disclosure | Shows or hides archived projects | FR-025, FR-026 |
| D-01 | Archived project link | Opens `/projects/:id` with its tasks | FR-025 |
| D-01 | "Unarchive" (page) / options › "Unarchive" | Unarchives | FR-026 |
| D-01 | "Retry" (error) | Retries the unarchive | FR-026, FR-015 |
| D-01 | "Archive" (existing popover) | Archives, keeping tasks | FR-024 |

**Removed** by this design (no requirement keeps them):

- The Mac toolbar "Refresh" button (X-07).
- The Mac full-window sign-in view and the full-window overlay shown when a session expired (X-03, US3-5).
- The Mac "Try local voice capture" button (voice works account-less).

Display-only surfaces carrying requirements:

- The status words (FR-012, FR-019), indicator (FR-013), tooltip (FR-015).
- The waiting count and oldest age (FR-008, FR-016).
- "Nothing is sent anywhere until you sign in" (FR-029).
- The read-only desired outcome on archived projects (FR-028).
- "Old flat · archived" labels (FR-024, FR-025).

### Requirements with no affordance

- **FR-005** (Keychain; logout queued offline): no control. Visible only as X-04 "after sign-out" being immediate.
- **FR-007** (what syncs): behaviour, no UI.
- **FR-008** (durable until confirmed): no control. Visible as the waiting count (X-01, X-02, M-01).
- **FR-009** (incoming changes never move selection, scroll, focus or unsaved text): behaviour. The design adds no surface that could move focus; X-02 "new issue while open" keeps focus.
- **FR-010** (never wait on the network): behaviour. X-03 offline copy states it.
- **FR-011** (conflict rules): behaviour. Rejections surface as X-02 / M-01 issues.
- **FR-017** (no routine dialogs): a constraint, met by the absence of any dialog outside X-03 (including its refusal and deletion-cancelled states), X-04 (including its "Couldn't sign out" error), X-05 (including "later file" and "partly carried over"), X-08 (only when the running copy cannot be brought forward) and X-09's person-started "Start fresh" confirmation. The sidebar-hidden toolbar item is not a dialog and takes no focus.
- **FR-020, FR-021** (lossless upgrade, backup kept): silent by design; X-05 only for FR-022.
- **FR-023** (Mac review marks stay local): no UI change; the Mac's Waiting / Someday / Project review buttons must keep working signed in (Notes for the plan).
- **FR-027** (old archives stay detached): display only (the neutral line in the empty archived project on X-06, M-02 and D-01).
- **FR-028** (desired outcome synced): display only on Mac (X-06). Not shown on iPhone or web by scope.
- **FR-029, FR-030, FR-031** (privacy, logs, client identification): no UI beyond the X-02 account-less line.
- **FR-032** (the iPhone in the foreground and the web's visible tab fetch at least every 60 s): behaviour, no UI. Visible only as M-01 and D-01 showing changes from other devices without a pull or a reload.

FR-033 (a previous-version file appearing later is kept, never imported) maps to X-05 "later file" and X-02 "earlier-version file kept". Every other FR-001 … FR-033 maps to at least one affordance or display surface above.

### Affordances with no requirement

None. Borderline items, each traced:

- "Show in Finder" (X-05): FR-022 "tell the person where the old file is".
- "Copy" (X-02): FR-015 "see and copy".
- App menu account items (X-07): FR-001.
- The web archive hint line (D-01) and the iPhone/web "Unarchived" toast are copy and feedback, not controls.

### Requirements gaps found while designing

G-1 to G-6 were resolved on 2026-10-06 by the owner's sign-off and the spec amendment in commit e50b144. G-7 is a tooling task for the plan. G-8 was found by the plan and resolved by X-08 (spec commit 0b9fffe).

| id | gap | resolution | status |
|---|---|---|---|
| G-1 | FR-012 had no wording for "signed in, first sync not finished". | "Not synced yet" is in FR-012 (X-01, M-01). | resolved |
| G-2 | FR-012 stopped at "Synced yesterday". | "Synced N days ago" (2–6 days), then "Synced on <date>", are in FR-012 (X-01, M-01). | resolved |
| G-3 | Signing in can cancel a pending account deletion, and the Mac had no requirement to say so. | FR-017: the X-03 sheet shows the iPhone's note before closing ("signed in, account deletion cancelled" state). | resolved |
| G-4 | ADR-0020 says state the limit for old archives; US5-4 says never say tasks were lost. | Sign-off 2: one neutral line on every client (FR-027, US5-4). | resolved |
| G-5 | A literal FR-012 and FR-013 would flicker. | Sign-off 1: the indicator shows only after 1 s and stays at least 0.5 s; the waiting count shows after 10 s (FR-012, FR-013). | resolved |
| G-6 | FR-017 listed only sign-out with unsent changes. | Sign-off 3: "Sign out?" confirmation (FR-017). | resolved |
| G-7 | Pipeline tooling recognises only `D-`/`M-` screen ids. | `X-` used as asked. | open: the plan widens `SCREEN_ID_RE` |
| G-8 | The edge case "a second copy … is told in plain words" had no screen (found by the plan). | X-08 added on 2026-10-06 and listed in FR-017: "Brain Buddy is already open." / "Switch to the open window to keep working." with "OK". | resolved |

## Primary loop impact

This feature makes the Mac a full capture and organise client of the same
trusted system. It changes no rule of the loop itself (spec, "Primary-loop
impact"):

- **Capture**: Mac captures (quick-capture hotkey, voice-to-draft, Smart Add) now reach the account and every device. They never wait for the network (FR-010), so capture is unchanged in feel.
- **Atomic items / clarify / approve**: Inbox processing on any device sees Mac captures within 60 s (SC-001).
- **Route or CRT candidate**: organising (lists, projects, tags) syncs. Archive no longer strips a project from its tasks on any client, so routing decisions survive archive (FR-024).
- **Smart Weekly Review**: this is the prerequisite for weekly review on the Mac (020 US6, FR-041). The Mac's local review marks stay local until then (FR-023).
- **Evidence / results**: unchanged.

The design keeps the loop calm. No sync surface interrupts capture or review,
and failures appear only after 60 s, in one place.

## Mobile viability

- **Viewport**: M-01 and M-02 frames are drawn at 390 × 851 with no horizontal scroll. D-01 has a narrow (390 px) state: the disclosure in the drawer and a full-width Unarchive button. Playwright should check no horizontal overflow at 390 × 851 on an archived `/projects/:id`.
- **Tap targets**: the iPhone attention status rows are single buttons at least 44 pt tall across the row. Calm rows are not interactive. Swipe actions and toolbar "Unarchive" are 44 pt. The web's narrow Unarchive is 44 px tall.
- **One-handed reach**: the iPhone status line sits at the end of the list, where the thumb scrolls to. Unarchive is a swipe or the top-right toolbar button, as other iOS list actions are.
- **Dynamic Type**: the status line wraps after " · " up to AX5 and is never truncated (M-01).
- **Reduce Motion**: the indicator becomes a static glyph on both platforms.
- **Destructive actions**:
  - X-04 "Sign out and remove". It names what is lost: "N changes haven't synced yet … They haven't reached your account", and, when this sign-out also deletes the pre-upgrade backup, says so.
  - X-02 "Discard outcome" (added in planning review c2): it deletes text the person wrote that exists nowhere else, so its visible label says "Discard", and a 5 s Undo follows.
  - X-09 "Set aside and start fresh" (planning review c2): behind a confirmation; the file is kept, set aside, until sign-out.
  - iPhone archive is no longer destructive: it loses the rose tint and destructive role, and says it can be undone.
  - Unarchive needs no confirmation, because archiving again reverses it.
- **Contrast** (WCAG 2.2 AA):
  - Mac footer: slate-600 on the light sidebar 6.6:1; amber-800 6.5:1; sky-700 5.3:1. Dark: slate-400 5.6:1; amber-300 10:1; sky-300 9.5:1.
  - iPhone: slate-500 on white 4.8:1; amber-800 7.1:1; sky-700 5.9:1.
  - Web: muted archived rows, slate-500 on slate-50, 4.5:1.

## Keyboard and focus

- **Tab order**:
  - X-01: the status words, then the trailing action when present, are the last stops in the sidebar.
  - X-02 (completed in planning review c2): attention action (Sign in again, Sign in… when account-less, or the failing notice's Copy) → each issue's Copy → Copy outcome → Dismiss / Discard outcome → Sync now (skipped when disabled) → the offline notice's last-failure Copy → Sign out… → backup "Show in Finder" → import report "Show in Finder" → earlier-version "Show in Finder".
  - X-03: Email → Password → Advanced → (Server address → Use the default server) → Cancel → Sign in.
  - X-06: title → Unarchive → task rows. In the sidebar, the "Archived projects · N" disclosure is a tab stop, named "Archived projects, 2, collapsed" or "…, expanded".
  - D-01: heading → Unarchive → task rows.
- **Focus on open**:
  - X-02 focuses the attention action if any; otherwise "Sync now" when enabled; otherwise "Sign in…" when account-less; otherwise the first enabled control (planning review c2). VoiceOver reads the content first. "Show in Finder" brings Finder forward, which closes the transient popover; when the person returns, focus is on the status words.
  - X-09 focuses "Try again"; its confirmation focuses "Keep trying", and Escape in the confirmation is "Keep trying" (added after `/speckit-checklist`).
  - X-03 focuses Email, or Password when the email is known or locked. After an error, focus goes to Password with its text selected.
  - X-04 focuses "Cancel".
  - X-05 focuses "Continue".
- **Focus restored on close to**:
  - X-02, X-04: the status words.
  - X-03: the control that opened it, when it still exists. When it does not (the X-02 popover has closed, the trailing "Sign in to sync" vanished because sign-in succeeded, or a menu item opened the sheet), the X-01 status words. On Cancel, the X-01 trailing action when it still exists.
  - After an unarchive or an archive of the open project (X-06, D-01): the project title / heading.
- **Focus inside X-02 after Dismiss**: the next issue's Copy, or the previous issue's when the last row was dismissed; after the last issue, "Sync now", or "Sign out…" when Sync now is disabled.
  - iPhone: VoiceOver focus stays on the row that was acted on, or moves to the navigation title if the row disappeared.
- **Escape**:
  - Closes X-02 and X-03 (Cancel), X-03 also while "Signing in…" waits for the login reply; not once the account is linked (2026-10-08, as delivered).
  - Cancels X-04.
  - Is not mapped in X-05 (the notice must be read once; Return continues).
  - Closes the D-01 options popover.
- **Shortcuts**: ⌘R = Sync now (X-07). "Archive project" and "Unarchive project" have a keyboard path through the File menu (no shortcut).
- **Accessible names**:
  - Status words: "Sync status: <state>. Show details". The toolbar status item shown while the sidebar is hidden has the same name (added after `/speckit-checklist`).
  - Trailing actions: "Sign in to sync", "Retry sync".
  - Indicator: "Syncing" (not announced on appearance).
  - Copy: "Copy reference ID".
  - Dismiss: "Dismiss: <issue>". A kept outcome has no "Dismiss": its button reads "Discard outcome", named "Discard your outcome for “<project>”" (planning review c2).
  - Unarchive: "Unarchive <project>".
  - Web disclosure: "Archived projects, 2".
- **Announcements**:
  - Entering an attention state (session ended, couldn't sync, changes couldn't sync) is announced once, politely, on Mac and iPhone. Calm changes (minutes ticking, syncing, waiting) are not announced.
  - Sign-in errors are announced (alert role).
- **State communicated by colour alone**: none. Attention states carry words and a glyph. Archived rows carry the archive icon and "archived". Offline is words only.

## Design authority

- Tokens, colours and type come from the `brain-buddy-design` skill: slate neutrals, sky accent, amber warning semantic, rose only for the one destructive control (X-04), radii 6/8/12/14/16/20, the soft/raised/floating shadows and the double-ring focus.
- Filled controls and brand text use sky-700, as both shipped apps already do (`docs/native-ios-app.md` deviation 5).
- **macOS** mockups use the system font stack and derive dark mode from the slate/sky scale. This extends the documented iOS deviations 2 and 3 to the Mac. The Mac app already uses system styling; no new deviation from the iOS set.
- Web mockups name Inter with system fallbacks. No font is downloaded.
- Icons are inline SVG copies of Lucide shapes. The native apps map them to SF Symbols:
  - `refresh-cw` → `arrow.triangle.2.circlepath`;
  - `triangle-alert` → `exclamationmark.triangle`;
  - user-with-alert → `person.crop.circle.badge.exclamationmark`;
  - `archive` → `archivebox`;
  - unarchive → `tray.and.arrow.up`.
- The logo path in X-04 and X-05 is an inline copy of `assets/logo.svg`.
- **Activity indicator vs "ambient loops only in brain dump"**: reconciled.
  - The indicator is the platform's own small progress control, shown only while work actually runs, and only past 1 s, then for at least 0.5 s (FR-013).
  - It is static under Reduce Motion.
  - It is not a brand ambient loop, and no brand animation is added.
- **Menu casing**: Mac menu items we own use sentence case ("Sync now", "Sign out…"), per the product's casing rule, deliberately unlike the macOS title-case habit. System items keep macOS wording.
- Vocabulary check (ADR-0006: Tag, never the retired term or its at-prefixed form): pass (case-insensitive grep, zero hits in `design.md` and `design/`).
- `python3 -m unittest scripts/test_validate_brain_buddy_design_skill.py`: pass.

## Notes for the plan

- **Shared status logic**. Put the state machine, the precedence and the thresholds in `BrainBuddyKit` (Core, Linux-testable): 1 s indicator delay, 0.5 s minimum, 10 s waiting suffix, 60 s failure (FR-012 – FR-014). Also the single-flight rule for "Sync now" during a running sync. The Mac and iPhone then render one description and cannot drift. Today `SyncStatusLabel.describe` holds the iPhone's copy; it moves or is shared.
- **Mac removals**:
  - the full-window `signIn` view and the `sessionExpired` overlay;
  - the "Sync needs attention" banner (`syncConflictTaskID`), because conflicts become FR-011 issues;
  - the toolbar "Refresh";
  - "Try local voice capture";
  - the "Desired outcome is not available in this workspace yet." line.
- **Mac `isLocalWorkspace` gates**:
  - The "Archived projects" section, "Set outcome" and the Waiting / Someday / Project review entry points are gated on `isLocalWorkspace` today.
  - They must work signed in: FR-023 keeps the review marks working, and FR-026 / FR-028 need archive and outcome.
- **Mac copy**: "Restore" becomes "Unarchive" in every string listed in X-06.
- **iPhone copy**:
  - the archive strings in M-02;
  - `SyncIssuesScreen.describe` gains an unarchive case;
  - `SyncStatusLabel` wording per M-01;
  - `ios/AGENTS.md`'s copy example "Offline — 3 changes waiting" becomes "Offline · 3 changes waiting".
  - 020's design copy that shows the em-dash form (M-01, M-09 offline rows) follows the same change when both land.
- **Web**:
  - The projects API must return archived projects (with their tasks reachable at `/projects/:id`).
  - An unarchive endpoint is needed.
  - The FR-027 neutral line needs the server to know which projects were archived before this change (for example, archived before the cutover). This applies to every client.
- **Upgrade**: confirm the X-05 "partial read = unreadable" interpretation (planning confirmed it; planning review c2 revised it, see "Planning review c2 additions").
- **Tooling**: widen `SCREEN_ID_RE` in `scripts/render_feature_report.py` to include `X-`.
- **Gaps G-1 … G-6** are resolved (spec commit e50b144). Only G-7, the tooling item above, is left.
- **iPhone Settings › Sync** keeps its existing behaviour (FR-019, "stay as they are"), with one exception: superseded by the FR-019 amendment (`b83d367`), its "Sync now" stays enabled while a sync runs and is single-flight, as on the Mac (M-01 "Settings › Sync, sync running"). The earlier note that it may stay disabled no longer applies.

## Planning review c1 additions (2026-10-06)

Planning review campaign `021-mac-sync-c1` added states and copy without changing any signed-off decision; each addition reuses an existing layout and has no new mockup unless stated. Dispositions are in `review-c1-disposition.md`.

- X-01: "error, then offline", "first upload", "Last tried" in the failure tooltip.
- X-02: "first upload", "outcome kept on account", "archive not applied at merge", "pre-upgrade backup", "earlier-version file kept", "issue dismissed (not last)", focus after the last Dismiss, "Last tried" in the error notice, and "Sync now" shown disabled (not hidden) when the session ended.
- X-03: Cancel and Esc enabled while signing in (the loading mockup is updated), "error: no answer", "error: couldn't save sign-in", focus fallback on close.
- X-04: "open sync issues", "backup kept", "during the first upload". The approved "Sign out?" copy is unchanged; the new sentences are appended only in those conditions.
- X-05: "error: couldn't carry over", "later file" (FR-033).
- X-06: File menu keyboard path, "archived (just now)", "unarchive refused: name in use", the disclosure in the tab order.
- M-01: the reference ID path from the list row, "Settings › Sync, sync running", sign-out with open issues. M-02 and D-01: "unarchive refused: name in use"; D-01: "archived (just now)".

## Planning review c2 additions (2026-10-06)

Planning review campaign `021-mac-sync-c2` added the following, again without changing any signed-off decision; each reuses an existing layout and has no new mockup unless stated. Dispositions are in `review-c2-disposition.md`.

- **X-01**: "first load, empty list" ("Your tasks are still arriving."); "sidebar hidden" (a toolbar item only in attention states, so the toolbar shows nothing about sync whenever all is well); the first-load indicator follows FR-013's 1 s rule.
- **X-02**: "Discard outcome" with a 5 s Undo instead of "Dismiss" for a kept outcome; the backup line never shows a past date; "details changed during the update" with the import report; the complete Tab order and focus on open.
- **X-04**: "backup removed" (the sentence when this sign-out deletes the backup), "unsaved edit or capture draft", "changes arrived while open".
- **X-05**: "partly carried over"; the "couldn't carry over" copy no longer promises that a later version carries the file over; "partial read" now imports what decodes (it was the plan's interpretation, not a sign-off decision).
- **X-06, M-02, D-01**: "rename archived project"; error and refusal focus; the partial-failure copy says where the project stands; D-01's task project picker and Escape focus return.
- **X-09** (new screen id): tasks couldn't be opened.
- **M-01**: "first upload", "error, then offline", the VoiceOver action for "Copy reference ID", 44 pt for the account-less "Sign in to sync".

## As delivered, PR-09 (2026-10-08)

Implementation of X-03 and X-04 differs from the signed-off wording in three places; each keeps the screens and copy and only narrows when a control applies. Contracts: `contracts/mac-app-host.md` §7, `contracts/kit-commands.md` §4.

- **X-03 Cancel ends at the link.** Cancel and Esc are enabled while "Signing in…" waits for the login reply. The kit decides Cancel against the link exactly once, immediately before it writes the durable link: Cancel before that links nothing and ends the session the server opened; after it, Cancel and Esc are disabled, the sheet still reads "Signing in…" while the first sync runs, and it closes signed in (after the "account deletion cancelled" note when there is one). The loading mockup describes the first part. A Cancel after the link would otherwise have reported "cancelled" for a sign-in that stuck.
- **X-03 is single flight.** While the sheet is shown or its request is on its way, a second "Sign in…" or "Sign in again…" does nothing and the app menu's two items are disabled.
- **X-04 removes only what it named.** "Sign out and remove" removes the changes the dialog named, identified by operation id and content. Any other pending change (queued in place of an acknowledged one, or an edit folded into a named one) refuses, removes nothing and shows X-04 again with the real count. Edits made while a confirmed sign-out runs are refused ("Brain Buddy is signing out. This wasn't saved; try again in a moment."): Quick Capture and the main window keep the typed text.

## Sign-off

**Approved by Max on 2026-10-06** ("Утверждаю"), with all three recommendations accepted: quiet thresholds (1), one neutral line for pre-feature archives (2), and confirming plain sign-out (3). The choices left as designed stand. Gaps G-1 – G-3 are resolved by the spec amendment of the same day:
- G-1: "Not synced yet" goes into FR-012.
- G-2: "Synced N days ago" (2–6 days) and then "Synced on <date>" go into FR-012.
- G-3: the X-03 sign-in sheet says that signing in cancelled a pending account deletion before it closes (FR-017).

Every screen and state table above shows only the accepted options; the alternatives are not designed. Review fixes after sign-off (Codex review on PR #265):
- X-03 gained the "signed in, account deletion cancelled" state.
- The pre-feature archive empty state shows only the approved line on X-06, M-02 and D-01.
- "Sync now" stays enabled while a sync runs (FR-013, single-flight).

The three choices as they were put to the owner (kept for the record; in each, the **Recommended** option was accepted):

1. **Quiet thresholds** (X-01, M-01; FR-012, FR-013).
   - Taken literally, the indicator would blink at every 60 s pull and every edit, and "· 1 change waiting" would appear and vanish after every edit. That is the opposite of "не должно бросаться в глаза".
   - **Recommended**: show the indicator only for a sync that has run longer than 1 s (then keep it at least 0.5 s), and show "· N changes waiting" while online only after a change has waited 10 s.
   - Alternative: literal behaviour.
   - Accepting means a one-line amendment to FR-013 ("while a sync runs longer than 1 s").
2. **Projects archived before this feature** (X-06, M-02, D-01; FR-027, US5-4 vs ADR-0020).
   - **Recommended: option B.** When such a project is empty, add one neutral line: "Archived before projects kept their tasks, so none are listed here. Those tasks are still in their lists."
   - It satisfies ADR-0020 ("the UI must state that limit"), and it never says anything was lost, so US5-4 holds.
   - Option A: say nothing.
   - B needs the server to mark pre-feature archives.
3. **Sign-out with nothing unsent on the Mac** (X-04; FR-017, US1-6).
   - **Recommended**: confirm ("Sign out?" / "Your tasks are removed from this Mac. They stay in your account."), exactly as the iPhone does, because it removes the account's data from this Mac.
   - Alternative: sign out at once.
   - Accepting adds plain sign-out to FR-017's list of person-started dialogs.

Choices left as designed (no action needed unless the owner objects):

- The Mac footer shows only the status line. The email and "Sign out…" live in the popover.
- "Unarchive" is the verb on every client, and the Mac's "Restore" strings change.
- Placement of unarchive:
  - iPhone: the existing Archived projects screen (swipe + toolbar);
  - web: a collapsed "Archived projects" disclosure under Projects in the sidebar;
  - Mac: the existing sidebar section, now collapsible and collapsed by default.
- File › "Sync now" ⌘R, account items in the app menu, toolbar "Refresh" removed.
- iPhone attention rows become buttons; cloud glyphs dropped from calm states.
- Offline stays calm (slate), not amber.
