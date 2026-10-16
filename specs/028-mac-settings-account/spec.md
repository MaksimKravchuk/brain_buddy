# Feature Specification: Mac Account and Settings window (⌘,)

**Feature Branch**: `028-mac-settings-account`

**Created**: 2026-10-16

**Status**: Clarified — product-owner interview held 2026-10-16 (interviewee: Max).
Design: [design.md](design.md). Plan: [plan.md](plan.md). Tasks: [tasks.md](tasks.md).

**Input**: User description: "Mac Account and Settings window (⌘,)". Design input: Mac
board cells M25–M28 (board version `1792138611-15e1`, design data). Business
requirements: [intake.md](intake.md).

## Context

The native Mac app (spec 021) signs in with email and password, keeps its session in
the login Keychain and syncs through the shared native kit. It has no Settings window
and does not answer ⌘,. Account management — profile, email, password, sign-in
methods, ZIP export and 14-day-grace deletion — exists on the server (`AccountService`,
spec 023 modern authentication) and on the web account page.

The board (M25) draws a Settings window with tabs Account | Agents | Sync and an
Account tab listing Name, Steps taken, Email (verified), Apple, Google, Password, Your
data (Export…), deletion (Delete account…) and a footer with sync status and Sign out….
M26–M28 draw native sheets for removing a method, changing email and deleting the
account.

This feature delivers the board's Settings window with its three tabs. The Account
tab shows account state natively and offers native Export… and Sign out…. Changing
email or password, connecting or removing Apple or Google, and deleting the account
are built natively in a separate follow-up feature (see
[Follow-up feature (backlog)](#follow-up-feature-backlog)); in 028 their buttons do
not appear.

## Clarifications

### Session 2026-10-16 (interview with Max, product owner)

Max's answer, verbatim: "Так, делаем все как по борде. Первое по борде. Второе. Так,
второе подразумевает еще, видимо, какие-то правки в самом приложении, не только
интерфейс. Поэтому, видимо, его надо как-то в бэклог положить и сделать второе
нормально. Оно, соответственно, с собой тянет и третье, и четвертое, и пятое. Как
будто бы." The full rendering is in [intake.md](intake.md#interview-2026-10-16).

- Q1: Which Settings tabs ship? → A (Max): as the board — a tab bar with **Account,
  Agents, Sync**. Account follows M25. Sync shows the Mac's existing sync status
  content with no new behaviour. Agents shows a short empty state with a button that
  opens the web agents page `/settings/agents` until the Mac agents feature (feature 8)
  ships. Affects 028-FR-002, 028-FR-019, 028-FR-020.
- Q2: Native or web for change email, change password, connect/remove Apple or
  Google, and delete account? → A (Max): native, as the board draws them, but in a
  **separate follow-up feature**, because they need backend and app changes, not only
  interface. In 028 none of these buttons is shown — no web handoff button and no
  disabled placeholder. Affects 028-FR-011 and the follow-up section.
- Q3: A password field before deleting the account (M28 draws none)? → A (Max):
  follows Q2 — the follow-up builds M28 as drawn, which needs a backend change. Nothing
  in 028.
- Q4: Connect Apple / Google in the app or on the web? → A (Max): follows Q2 — native,
  in the follow-up. In 028 the rows show status only. Affects 028-FR-009.
- Q5: Is the name editable? → A (Max): as the board — read-only. Affects 028-FR-006.
- Recorded technical facts for the follow-up (not owner questions): verification codes
  are **6 digits** on the backend while M27 draws 4 cells, so the follow-up's code
  sheet uses 6; the backend authentication `client` field accepts only `web` or `ios`.

## User Scenarios & Testing *(mandatory)*

Stories are numbered in delivery order; no story carries a priority.

### User Story 1 - Open Settings and see my account

A signed-in person presses ⌘, (or chooses the app menu's Settings…). A Settings window
opens with the tab bar Account | Agents | Sync and shows the Account tab: their name,
the number of steps they have taken, their email with its verified state, whether
Apple and Google are connected, whether a password is set, and the sync status.

**Independent Test**: sign in on the Mac with an account whose state is known (name,
completed steps, verified email, one connected provider, a password), press ⌘,, and
compare each row with the web account page for the same account.

**Acceptance Scenarios**:

1. **Given** a running Mac app, **When** the person presses ⌘, for the first time in
   this app session, **Then** one Settings window opens on the Account tab with the
   tab bar Account, Agents, Sync; pressing ⌘, again brings the same window forward.
2. **Given** the account has a name, 214 completed steps and a verified email,
   **When** the Account tab loads, **Then** it shows the name as read-only text, "214"
   as steps taken, and the email followed by "Verified".
3. **Given** Apple is connected and Google is not, **When** the tab loads, **Then** the
   Apple row reads "Connected" and the Google row "Not connected", with no button on
   either row.
4. **Given** the account has a password, **When** the tab loads, **Then** the password
   row reads "Set · also used for Mac sign-in", with no button.
5. **Given** any account state, **When** the tab is shown, **Then** no Change…,
   Connect…, Remove… or Delete account… control and no deletion row appear.
6. **Given** the server is slow, **When** the tab is loading, **Then** each row shows a
   loading state rather than empty or stale values.

---

### User Story 2 - Export my data from the Mac

The person chooses Export… on the "Your data" row; the app prepares the export, then a
macOS save panel asks where to put it, and the person receives the same ZIP archive of
their account data the web export produces, without secrets.

**Independent Test**: export from the Mac and from the web for the same account; both
archives contain the same entries and neither contains auth secrets.

**Acceptance Scenarios**:

1. **Given** a signed-in Mac, **When** the person chooses Export…, **Then** the row shows
   "Exporting…" with progress and a Cancel control, and when the export is ready a save
   panel opens prefilled with the server-suggested file name.
2. **Given** the save panel, **When** the person confirms it, **Then** the ZIP is written
   to the chosen location under that name (or the name the person typed).
3. **Given** an export in progress or the save panel open, **When** the person chooses
   Cancel (or closes Settings), **Then** nothing is written and the app keeps no copy.
4. **Given** the export request fails (offline, server error, expired session),
   **When** it fails, **Then** no file is written, and the row shows an actionable
   message with Try again and, when the server returned one, a support reference.

---

### User Story 3 - Sign out from Settings

The Account tab's footer shows the sync status and a Sign out… button. Choosing it
shows the existing Mac sign-out confirmation, with the same wording, default button and
outcome as the menu's Sign out….

**Independent Test**: with unsent changes on the Mac, choose Sign out… in Settings and
in the menu; the confirmation and the result are identical.

**Acceptance Scenarios**:

1. **Given** a signed-in Mac, **When** the person chooses Sign out… in Settings, **Then**
   the main window comes forward and shows the existing sign-out confirmation with
   "Cancel" as the default button, after the main window's existing unsaved-edit guard.
2. **Given** unsent changes, **When** the confirmation appears, **Then** it states what
   would be removed exactly as the menu's sign-out does.
3. **Given** the person confirms and sign-out completes, **Then** the Account tab
   switches to the signed-out state; when sign-out fails, the existing "Couldn't sign
   out" alert appears and the person is still signed in.

---

### User Story 4 - Sync and Agents tabs

The Sync tab shows what the sync status popover shows today: last sync, what waits,
notices, issues and their actions, "Sync now", the account email and "Sign out…". The
Agents tab says agents are managed on the web for now and offers one button that
opens the web agents page.

**Independent Test**: open the sync popover and the Sync tab in the same state and
compare them; press the Agents tab's button and check the browser opens the web
agents page.

**Acceptance Scenarios**:

1. **Given** any sync state, **When** the person opens the Sync tab, **Then** it shows
   the same words, issues and enabled actions as the sync popover in that state, and
   each action does what it does in the popover.
2. **Given** the server reports a web origin, **When** the person chooses "Open agents
   on the web…", **Then** the default browser opens `<web origin>/settings/agents`, and
   the URL carries no session credential.
3. **Given** the web origin cannot be read or is not https (or http on localhost),
   **When** the Agents tab is shown, **Then** the button is unavailable and a short line
   says the agents page can't be opened right now, with Try again.

---

### User Story 5 - Settings stays honest when signed out, offline or expired

Settings never shows another account's data, never invents values, and never touches
local work. Signed out, it says so and offers Sign in…. Offline, it says the account
details need a connection and offers Try again. When the session has ended, it shows a
"Sign in again" state while unsent changes stay on this Mac.

**Independent Test**: open Settings signed out, offline, and after ending the session
from the web (password change); confirm the shown state, the offered action, and that
local tasks and unsent changes are unchanged.

**Acceptance Scenarios**:

1. **Given** no account on this Mac, **When** Settings opens, **Then** the Account tab
   reads "Not signed in" and offers Sign in…, which opens the existing sign-in sheet on
   the main window.
2. **Given** no connection, **When** the Account tab loads, **Then** the account rows
   are replaced by "Your account details need a connection." with Try again; Sign out…
   remains available and behaves as the menu's Sign out… does offline.
3. **Given** the session ended elsewhere, **When** a request returns "not signed in",
   **Then** the tab shows "Your session ended." with Sign in again…, local tasks and
   unsent changes are kept, and no account data from the previous load stays on screen.
4. **Given** the signed-in account changes on this Mac while Settings is open, **When**
   the tab reloads, **Then** it never shows the previous account's details.

### Edge Cases

- The sign-in-methods read fails while the account read succeeds: name, steps and email
  show; the verified state and the Apple, Google and Password rows show "Unavailable"
  with Try again rather than a guessed "Unverified" or "Not connected".
- A provider is connected but unusable (method state disabled or not usable): the row
  reads "Connected · unavailable", matching the web wording.
- The account has no name: the Name row shows "Not set" as read-only text.
- The account has no password (it was removed elsewhere while this Mac's session
  lives): the Password row reads "Not set", with no button.
- Rate-limited (429) or server error with a correlation ID: an actionable message with a
  support reference; nothing retries automatically.
- Slow export: progress stays visible and cancellable; closing Settings cancels the
  export and leaves no file.
- The chosen save location is not writable or the disk is full: the export fails with a
  message naming the problem; no partial file remains.
- Password changed on the web: the server ends other sessions, so this Mac reaches the
  "Your session ended." state (User Story 5); local work is kept.
- Account deleted on the web: all sessions end; the Mac shows "Your session ended.";
  unsent changes stay on this Mac until the person signs out (`docs/data-retention.md`).
- Settings is open during a sign-out started from the menu: the Account tab follows to
  the signed-out state; no second confirmation appears.
- Reduce Motion, increased contrast and dark appearance: the window follows the Carry On
  tokens in both appearances and respects Reduce Motion.

## Requirements *(mandatory)*

Requirement ids are feature-qualified. Each definition shows the bare id the
repository's checkers parse (`- **FR-001**`) followed by its feature-qualified id
(`028-FR-001`); tests and other artifacts MUST cite the qualified form
(`028-FR-001`, or `028_FR_001` in a Swift test name).

### Functional Requirements

- **FR-001**: (`028-FR-001`) The Mac app MUST provide a Settings window opened by ⌘,
  and by the app menu's standard Settings… item. Only one Settings window exists; ⌘,
  while it is open brings it forward; ⌘W and the close button close it.
- **FR-002**: (`028-FR-002`) The Settings window MUST show the board's tab bar with
  exactly three tabs in this order: **Account**, **Agents**, **Sync**, each with its
  board glyph and the selected tab's name as the window title. It opens on the Account
  tab the first time in an app session and on the last chosen tab after that.
- **FR-003**: (`028-FR-003`) Every value and action in Settings MUST be backed by an
  existing server endpoint or existing Mac behavior (see Dependencies). Settings MUST
  NOT show a placeholder or guessed value as if it were live, and MUST NOT show task
  priority in any form.
- **FR-004**: (`028-FR-004`) When the Account tab is shown, and again whenever the
  Settings window becomes active, it MUST load the signed-in account's details and
  sign-in methods, showing a loading state per row until each answer arrives.
- **FR-005**: (`028-FR-005`) Account details MUST be held in memory for the window only;
  the feature MUST NOT write the name, email, method list or counts to disk, and MUST
  clear them from the window on sign-out, session end or account change. A response
  for an account other than the one now signed in on this Mac MUST be discarded.
- **FR-006**: (`028-FR-006`) The Name row MUST show the account's display name as
  read-only text, or "Not set" when it has none.
- **FR-007**: (`028-FR-007`) The Steps taken row MUST show the account's completed-step
  count as reported by the server.
- **FR-008**: (`028-FR-008`) The Email row MUST show the account email followed by
  "Verified" or "Unverified" as the server reports it. When the verification state
  cannot be loaded, it MUST show "Unavailable", never "Unverified".
- **FR-009**: (`028-FR-009`) The Apple and Google rows MUST show "Connected",
  "Connected · unavailable" or "Not connected" from the server's method list, or
  "Unavailable" when the list cannot be loaded. They MUST NOT offer any control.
- **FR-010**: (`028-FR-010`) The Password row MUST show "Set · also used for Mac
  sign-in" when the account has a password and "Not set" when it has none, or
  "Unavailable" when that cannot be loaded. It MUST NOT offer any control.
- **FR-011**: (`028-FR-011`) Settings MUST NOT show any control to change the email,
  change or set the password, connect or remove Apple or Google, or delete the
  account — neither a native flow, nor a button that opens the web, nor a disabled
  placeholder — and MUST NOT show the board's deletion row. These belong to the
  follow-up feature.
- **FR-012**: (`028-FR-012`) The "Your data" row MUST read "A ZIP of everything, without
  secrets" and offer Export…, which fetches the account's ZIP export (showing
  "Exporting…" with progress and Cancel), then opens a macOS save panel prefilled with
  the server-suggested file name and writes the archive to the chosen location. It MUST
  be the same archive the web account export returns.
- **FR-013**: (`028-FR-013`) A cancelled or failed export, or one interrupted by closing
  Settings, MUST leave no file at the chosen location and no copy elsewhere; the app
  MUST NOT retain the export after it is written.
- **FR-014**: (`028-FR-014`) The Account tab's footer MUST show the existing sync status
  words and a Sign out… button that runs the existing Mac sign-out request — the main
  window's unsaved-edit guard, then the existing confirmation — unchanged (same
  wording, default button, unsent-change disclosure and failure alert).
- **FR-015**: (`028-FR-015`) With no account on this Mac, the Account tab MUST read "Not
  signed in" and offer Sign in…, opening the existing sign-in sheet on the main window.
- **FR-016**: (`028-FR-016`) Offline, the Account tab MUST say "Your account details
  need a connection." and offer Try again; when the session has ended, it MUST say
  "Your session ended." and offer Sign in again…, opening the existing sign-in-again
  sheet. Neither case may discard, alter or upload local tasks or unsent changes.
- **FR-017**: (`028-FR-017`) Errors MUST be actionable: a short message, Try again where
  retrying can help, and, when the server returned a correlation ID, that ID as a
  support reference. Rate-limited responses MUST NOT be retried automatically.
- **FR-018**: (`028-FR-018`) Logs and diagnostics for this feature MUST record only
  outcome, stage, timing and correlation ID; they MUST NOT contain the name, email,
  method identities, export contents, file paths or session credentials.
- **FR-019**: (`028-FR-019`) The Agents tab MUST show the text "Agents are managed on
  the web for now." and one button, "Open agents on the web…", which opens the default
  browser at `/settings/agents` on the web origin the server reports (the signed-in
  account's server, or this Mac's default server when signed out). The URL MUST carry
  no session credential. When the origin cannot be read or is not https (or http on
  localhost), the button MUST be unavailable with "The agents page can't be opened
  right now." and Try again.
- **FR-020**: (`028-FR-020`) The Sync tab MUST show the existing sync status popover
  content of the main window's sync controller — the same words, issues, notices and
  actions, which behave as they do in the popover. It MUST NOT add any sync behavior.
- **FR-021**: (`028-FR-021`) The Settings window and its account surface MUST NOT be
  behind a feature flag: account management and data rights are always on.
- **FR-022**: (`028-FR-022`) The window MUST follow the Carry On design tokens and the
  M25 Mac board in light and dark appearance, use only design-system colors, use
  sentence-case English copy, show states in words (never color alone) and respect
  Reduce Motion.
- **FR-023**: (`028-FR-023`) Every control MUST be reachable and operable from the
  keyboard with visible focus, and MUST have an accessible name (and value, where it
  has one) for VoiceOver; the tabs are reachable with the keyboard.
- **FR-024**: (`028-FR-024`) The feature MUST NOT change backend contracts, the web
  pages, the iPhone app's behavior, or the Mac sign-in, sign-out, Keychain and sync
  behavior defined by spec 021. Additions to the shared native kit MUST be additive.

### Key Entities

- **Account summary**: the signed-in account's id, display name, email and
  completed-step count, read from the server; held in memory only.
- **Sign-in methods**: the account's email verification state, password presence and
  the list of methods (password, email, Apple, Google) with state and usability; read
  from the server.
- **Web agents destination**: the server-reported web origin plus `/settings/agents`;
  carries no credential.
- **Export archive**: the ZIP of the account's data the server produces; written once to
  a location the person chooses.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: (`028-SC-001`) On the reference MacBook Air M1, ⌘, shows the Settings
  window within 0.5 s and every Account row's live value (or its error state) within
  2 s on a normal connection.
- **SC-002**: (`028-SC-002`) For a set of test accounts covering verified/unverified
  email, each provider connected/not connected/unavailable, with and without a password
  and name, 100% of Account rows match the web account page for the same account.
- **SC-003**: (`028-SC-003`) Export and Sign out are each reachable in at most 2
  interactions after ⌘,.
- **SC-004**: (`028-SC-004`) A Mac export and a web export of the same account contain
  the same set of entries; both contain 0 auth secrets.
- **SC-005**: (`028-SC-005`) In every failure case of User Stories 2 and 5 (offline,
  expired session, server error, cancelled export, unwritable location), 0 local tasks
  or unsent changes are lost or altered and 0 partial export files remain.
- **SC-006**: (`028-SC-006`) 0 session credentials or secrets appear in any URL the app
  opens or in any log line the feature writes, checked over the full acceptance run.
- **SC-007**: (`028-SC-007`) Every Settings action can be completed with the keyboard
  alone, and every control has an accessible name, in light and dark appearance.
- **SC-008**: (`028-SC-008`) Across every Account tab state in design.md, 0 controls for
  changing email or password, connecting or removing a provider, or deleting the
  account are present.

## Dependencies

Existing contracts this feature consumes (paths under `/api`; session cookie auth; no
change made by this feature):

| Need | Existing endpoint | Notes |
|---|---|---|
| Name, steps taken, email, account id | `GET /account` | `id`, `display_name`, `completed_task_count`, `email` |
| Verified email, password, methods | `GET /account/auth-methods` | may return 404/503 when modern auth is unavailable → rows "Unavailable" |
| Web origin for the Agents button | `GET /auth/methods` | `web_account_origin`; the kit's existing call sends `client=ios`, the only value besides `web` the backend accepts |
| Export | `GET /account/export` | ZIP with `Content-Disposition` file name; auth secrets excluded |
| Sign in, sign in again, sign out | existing Mac flows | spec 021; unchanged |
| Sync status content | existing Mac sync popover | spec 021 X-02; unchanged |
| Web agents page | `/settings/agents` (frontend `AppRoutes.tsx`, "Connected agents") | existing, sign-in protected |

- Spec 027 (Rust server) MUST carry these routes unchanged; this feature adds no server
  capability.
- Shared native kit (`ios/BrainBuddyKit`): it has the method-list and public-methods
  calls but no calls for the account summary or export and no agents destination; the
  plan adds them additively.

## Follow-up feature (backlog)

Owner decision 2026-10-16 (Q2–Q4): the credential and deletion actions are built
natively, as the board draws them, in a separate feature that is not numbered yet.
This section records its scope so it can be specified later; it is not part of 028
and nothing in it is implemented here.

**Covers**

1. **Change email** — M25 Email row "Change…" and the M27 two-step sheet ("Change your
   email": confirm yourself, then a code sent to the new address; "Your current email
   stays in use until both steps succeed."). The code field has **6** digit cells, not
   the 4 drawn on M27. Behavior when the server reports email delivery `disabled` or
   `unconfigured` is decided there.
2. **Change password** — M25 Password row "Change…" (and "Set" for an account without a
   password). The sheet is not drawn on the board yet; a board cell is needed first.
3. **Connect Apple / Google** — M25 "Connect…" on a provider row, linking the provider
   from the Mac app.
4. **Remove Apple / Google** — M25 "Remove…" and the M26 confirmation sheet ("Remove
   Apple?", "First, confirm it is you.", "Current password", "Keep method" / "Remove").
5. **Delete account** — the M25 deletion row ("Removed for good after 14 days; signing in
   cancels it", "Delete account…") and the M28 alert as drawn ("Delete your account?",
   "Changes not yet sent from this Mac stay here until you sign out.", "Keep account" as
   the default button), with **no password field** (Q3).

**Backend and app changes it needs** (none made in 028)

- Authentication `client` identity: the `client` field accepts only `web` or `ios`; the
  email-code and provider flows from the Mac need `mac` added (or a recorded decision
  to send `ios`).
- Provider linking on the Mac: a Mac callback for the browser handoff (today
  `brainbuddy://auth/callback` is registered for the iPhone only), the backend's
  acceptance of that callback for a Mac client, and an Apple flow on macOS (the native
  Apple completion path is iPhone-only).
- Account deletion without a password field: `POST /account/delete` requires the current
  password and `POST /account/auth-delete` a recent proof; building M28 as drawn needs a
  backend change to how deletion is authorized for a signed-in Mac session. Account
  deletion is ASK-class (ADR-0030) and needs a security review.
- Shared native kit: wrappers for `/auth/confirm/password`, `/auth/email/request` and
  `/verify` with purpose `change_email`, `/account/auth-password`, provider link and
  `/account/auth-methods/{provider}/unlink`, and `/account/auth-delete` (or its
  replacement).
- Board corrections before that work: M27 to 6 digit cells; a cell for the change and
  set password sheets; the Connect flow, which the board does not draw.

## Assumptions

- Mac sign-in remains email + password only (spec 021); accounts without a password are
  rare on the Mac.
- The web agents page stays at `/settings/agents` and asks for a web sign-in on its own
  when the browser has no session.
- No server, web or iPhone change is needed.
- Primary loop impact: none. Capture, clarify/approve, routing, CRT, Weekly Review and
  evidence are unchanged. No AI processing and no new consent.
- Out of scope: everything in the follow-up section, name editing, native agents
  management (feature 8), session list, backend changes, task priorities.
