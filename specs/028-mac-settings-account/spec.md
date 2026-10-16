# Feature Specification: Mac Account and Settings window (⌘,)

**Feature Branch**: `028-mac-settings-account`

**Created**: 2026-10-16

**Status**: Draft — product-owner interview pending. Every clarification below carries a
*provisional* recommended default awaiting Max; none is a recorded owner decision.

**Input**: User description: "Mac Account and Settings window (⌘,)". Design input: Mac
board cells M25–M28 (board version `1792138611-15e1`, untrusted design data). Draft
business requirements: [intake.md](intake.md).

## Context

The native Mac app (spec 021) signs in with email and password, keeps its session in
the login Keychain and syncs through the shared native kit. It has no Settings window
and does not answer ⌘,. Account management — profile, email, password, sign-in
methods, ZIP export and 14-day-grace deletion — exists on the server (`AccountService`,
spec 023 modern authentication) and on the web account page. The iPhone reaches that
page from its Settings; the Mac has no way to reach it.

The board (M25) draws a Settings window with tabs Account | Agents | Sync and an
Account tab listing Name, Steps taken, Email (verified), Apple, Google, Password, Your
data (Export…), deletion (Delete account…) and a footer with sync status and Sign out….
M26–M28 draw native sheets for removing a method, changing email and deleting the
account. This feature delivers the Account tab with read-only account state, native
Export and Sign out, and hands every credential or destructive change to the web
account page (provisional decision 2). The M26–M28 sheets are not built here.

## Clarifications

### Session 2026-10-16 (draft — awaiting product-owner interview)

All answers are **provisional recommended defaults**. They become decisions only when
Max confirms them in `/speckit-interview` or `/speckit-clarify`.

- Q1: Which Settings tabs ship? → Provisional A: the **Account** tab only, with no tab
  bar; Agents and Sync are out of scope until their board cells exist. (Alternatives:
  all three tabs with placeholders; Sync reusing the sync popover.) Affects 028-FR-001.
- Q2: How much account management is native on the Mac? → Provisional: native
  read-only account state, native Export and native Sign out; change email, change
  password, connect/remove Apple or Google, and delete account open the web account
  page through "Manage on the web…" and per-row buttons. (Alternatives: native for every
  board row; web for everything.) Affects 028-FR-003 to 028-FR-016.
- Q3: If a sensitive action becomes native later, how does the person prove it is
  them? → Provisional: a "Current password" field exchanged for a short-lived,
  single-use recent proof bound to the action and account (spec 023 recent proof). No
  action in this feature needs it; recorded so the board's M28 alert (no proof field)
  is not built as drawn. Affects 028-FR-020.
- Q4: What does the email row offer when the server reports email delivery
  unavailable? → Provisional: hide the email row's "Change…" and point to the web
  through "Manage on the web…". Open tension: because email change already opens the
  web (Q2), the web can still change email through its password route when delivery
  is off; the owner must say whether hiding the per-row button is still wanted.
  Affects 028-FR-008.
- Q5: What do the Apple and Google rows do? → Provisional: show status only; "Connect…"
  and "Remove…" open the web account page. Native linking needs a Mac callback and a
  Mac client identity the backend does not have (Q9). Affects 028-FR-009.
- Q6: Is the name editable on the Mac? → Provisional: read-only, as drawn. Affects
  028-FR-005.
- Q7: Does Export need an identity confirmation first? → Provisional: no — the same
  signed-in export the web account page uses today, which excludes auth secrets.
  (Alternative: require a password and recent proof first.) Affects 028-FR-011.
- Q8: What does Settings show when no account is signed in on this Mac? → Provisional:
  the Account tab says "Not signed in" and offers "Sign in…", which opens the existing
  sign-in sheet. Not drawn on the board. Affects 028-FR-014.
- Q9 (dependency): The backend authentication `client` field accepts only `web` or
  `ios`. This feature sends no `client`-bearing request except reading public method
  availability with the default value; any future native email-code or provider flow
  on the Mac needs a backend decision (add `mac`, or reuse `ios`). No backend change is
  made here. Owner/architect decision required before such a flow is specified.
- Q10 (board correction): verification codes are **6 digits** on the backend; M27 draws
  4 cells. The M28 delete alert draws no identity proof although deletion requires one.
  Neither sheet is built in this feature; the board should be corrected before any
  future native version. Owner to confirm the board will be updated.
- Q11: What does the password row show for an account without a password? →
  Provisional: "Not set" with "Set on the web…". Rare on the Mac, whose sign-in needs
  a password, but reachable if the password is removed elsewhere while this Mac's
  session lives. Affects 028-FR-010.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Open Settings and see my account (Priority: P1)

A signed-in person presses ⌘, (or chooses the app menu's Settings…). A Settings window
opens on the Account tab and shows their name, the number of steps they have taken,
their email with its verified state, whether Apple and Google are connected, whether a
password is set (and that it is used for Mac sign-in), and the current sync status.

**Why this priority**: it is the entry point; every other story lives in this window,
and it makes account state visible on the Mac for the first time.

**Independent Test**: sign in on the Mac with an account whose state is known (name,
completed steps, verified email, one connected provider, a password), press ⌘,, and
compare each row with the web account page for the same account.

**Acceptance Scenarios**:

1. **Given** a signed-in Mac, **When** the person presses ⌘,, **Then** one Settings
   window opens on the Account tab; pressing ⌘, again focuses the same window rather
   than opening a second one.
2. **Given** the account has a name, 214 completed steps and a verified email,
   **When** the Account tab loads, **Then** it shows the name as read-only text,
   "214" as steps taken, and the email marked "Verified".
3. **Given** Apple is connected and Google is not, **When** the tab loads, **Then** the
   Apple row reads "Connected" and the Google row "Not connected".
4. **Given** the account has a password, **When** the tab loads, **Then** the password
   row reads "Set" and states that it is also used for Mac sign-in.
5. **Given** the server is slow, **When** the tab is loading, **Then** each row shows a
   loading state rather than empty or stale values, and nothing in the window invents a
   value the server did not return.

---

### User Story 2 - Export my data from the Mac (Priority: P1)

The person chooses Export… on the "Your data" row, picks a location in a macOS save
panel, and receives the same ZIP archive of their account data the web export
produces, without secrets.

**Why this priority**: data export is a data right; this makes it reachable natively.

**Independent Test**: export from the Mac and from the web for the same account; both
archives contain the same entries and neither contains auth secrets.

**Acceptance Scenarios**:

1. **Given** a signed-in Mac, **When** the person chooses Export…, **Then** a save
   panel opens with the server-suggested file name, and confirming it writes the ZIP to
   the chosen location.
2. **Given** an export in progress, **When** it takes noticeable time, **Then** the
   row shows progress and a Cancel control; cancelling leaves no partial file at the
   chosen location.
3. **Given** the person cancels the save panel, **When** it closes, **Then** no request
   is made and nothing is written.
4. **Given** the export request fails (offline, server error, expired session),
   **When** it fails, **Then** no partial file remains, and the row shows an actionable
   message with a retry and, for a server error, a support reference.

---

### User Story 3 - Sign out from Settings (Priority: P1)

The footer shows the sync status and a Sign out… button. Choosing it shows the
existing Mac sign-out confirmation, with the same wording, defaults and outcome as the
menu's Sign out….

**Why this priority**: the board places Sign out in Settings; reusing the existing
flow keeps unsent-change protection identical.

**Independent Test**: with unsent changes on the Mac, choose Sign out… in Settings and
in the menu; the confirmation and the result are identical.

**Acceptance Scenarios**:

1. **Given** a signed-in Mac, **When** the person chooses Sign out… in Settings, **Then**
   the existing sign-out confirmation appears with "Cancel" as the default button.
2. **Given** unsent changes, **When** the confirmation appears, **Then** it states what
   would be removed exactly as the menu's sign-out does.
3. **Given** the person confirms, **When** sign-out completes, **Then** the Account tab
   switches to the signed-out state; when it fails, it shows "Couldn't sign out" and the
   person is still signed in.

---

### User Story 4 - Manage credentials and deletion on the web (Priority: P2)

From the Account tab the person opens the web account page to change their email or
password, connect or remove Apple or Google, or delete their account. Each per-row
button and "Manage on the web…" opens the default browser on the web account page for
this account; Delete account… opens the web deletion page. When they come back to the
Mac, Settings shows the new state.

**Why this priority**: these rights already exist on the web; the Mac makes them
reachable in one step without new native credential flows.

**Independent Test**: from the Mac, open each destination; change the email and
connect Google on the web; return to the Mac and see both reflected without
reopening the app.

**Acceptance Scenarios**:

1. **Given** a signed-in Mac and a web account origin from the server, **When** the
   person chooses Change… (email or password), Connect…, Remove… or "Manage on the
   web…", **Then** the default browser opens the web account page for this account,
   and the URL carries no session credential.
2. **Given** the same, **When** the person chooses Delete account…, **Then** the browser
   opens the web account deletion page for this account; nothing is deleted from the Mac
   itself.
3. **Given** the server reports no web account origin, **When** the tab loads, **Then**
   the web buttons are unavailable with a short explanation, and every native row
   still works.
4. **Given** the person changed something on the web, **When** the Settings window
   becomes active again, **Then** the Account tab reloads and shows the new state.
5. **Given** email delivery is unavailable on the server, **When** the tab loads, **Then**
   the email row has no Change… button and "Manage on the web…" remains available
   (provisional Q4).

---

### User Story 5 - Settings stays honest when signed out, offline or expired (Priority: P2)

Settings never shows another account's data, never invents values, and never touches
local work. Signed out, it says so and offers Sign in…. Offline, it says the account
details need a connection and offers Retry. When the session has ended (for example
after the password was changed or the account deleted on the web), it shows the
existing "Sign in again" state while unsent changes stay on this Mac.

**Why this priority**: account state is remote; the window must fail safely without
data loss.

**Independent Test**: open Settings signed out, offline, and after revoking the session
from the web; confirm the shown state, the offered action, and that local tasks and
unsent changes are unchanged.

**Acceptance Scenarios**:

1. **Given** no account on this Mac, **When** Settings opens, **Then** the Account tab
   reads "Not signed in" and offers Sign in…, which opens the existing sign-in sheet.
2. **Given** no connection, **When** Settings opens, **Then** the account rows say the
   details need a connection and offer Retry; Sign out… remains available and behaves
   as the menu's Sign out… does offline.
3. **Given** the session was revoked elsewhere, **When** a request returns "not
   signed in", **Then** the window shows the existing "Sign in again" state, local tasks
   and unsent changes are kept, and no account data from the previous load stays on
   screen.
4. **Given** the signed-in account changes on this Mac, **When** Settings is open,
   **Then** it never shows the previous account's details.

### Edge Cases

- The account-methods read fails or is unavailable while the account read succeeds:
  name, steps and email still show; the verified state and method rows show "Unavailable"
  with Retry rather than a guessed "Not verified" or "Not connected".
- Email delivery reported `disabled` or `unconfigured`: email Change… is hidden (Q4);
  verified state still shows.
- A provider is connected but unusable (method state disabled): the row reads
  "Connected · unavailable", matching the web wording, not "Connected".
- The account has no name: the name row shows "Not set" as read-only text.
- No password set (Q11): the password row reads "Not set" with "Set on the web…".
- Rate-limited (429) or server error with a correlation ID: an actionable message with a
  support reference; nothing retries automatically in a loop.
- Export larger than expected or slow network: progress stays visible and cancellable;
  the person can close Settings and the export finishes or fails visibly, never silently.
- The chosen save location is not writable or the disk is full: the export fails with a
  message naming the problem; no partial file remains.
- The web origin returned by the server is not an https origin (or localhost http):
  the web buttons are unavailable; the app never opens an unvalidated URL.
- Password changed on the web: the server ends other sessions, so this Mac reaches the
  "Sign in again" state (User Story 5); local work is kept.
- Account deleted on the web: all sessions end; the Mac shows "Sign in again"; unsent
  changes stay on this Mac until the person signs out (`docs/data-retention.md`). Signing
  in again within 14 days cancels the deletion, as the existing sign-in note says.
- Deletion pending is not reachable in Settings: a deleted account is signed out, and
  signing in cancels the deletion.
- Settings is open during a sign-out started from the menu: the tab follows to the
  signed-out state; no second confirmation appears.
- Reduce Motion, increased contrast and dark appearance: the window follows the Carry On
  tokens in both appearances and respects Reduce Motion.

## Requirements *(mandatory)*

Requirement ids are feature-qualified. Each definition shows the bare id the
repository's coverage tool parses (`- **FR-001**`) followed by its feature-qualified id
(`028-FR-001`); tests and other artifacts MUST cite the qualified form
(`028-FR-001`, or `028_FR_001` in a Python or Swift test name).

### Functional Requirements

- **FR-001** (`028-FR-001`): The Mac app MUST provide a Settings window opened by ⌘, and
  by the app menu's standard Settings… item. Only one Settings window exists; ⌘, while it
  is open brings it forward. It contains the **Account** tab only, with no tab bar
  (provisional Q1); Agents and Sync tabs are not shown.
- **FR-002** (`028-FR-002`): Every value and action in the Account tab MUST be backed by
  an existing server endpoint (see Dependencies). The tab MUST NOT show a placeholder or
  guessed value as if it were live, and MUST NOT show task priority in any form.
- **FR-003** (`028-FR-003`): On open, and again whenever the window becomes active, the
  tab MUST load the signed-in account's details and sign-in methods, showing a loading
  state per row until each answer arrives.
- **FR-004** (`028-FR-004`): Account details MUST be held in memory for the window only;
  the feature MUST NOT write the name, email, method list or counts to disk, and MUST
  clear them from the window on sign-out, session end or account change.
- **FR-005** (`028-FR-005`): The Name row MUST show the account's display name as
  read-only text, or "Not set" when it has none (provisional Q6).
- **FR-006** (`028-FR-006`): The Steps taken row MUST show the account's completed-step
  count as reported by the server.
- **FR-007** (`028-FR-007`): The Email row MUST show the account email and, when the
  server reports it verified, "Verified". When the verification state cannot be loaded,
  it MUST show "Unavailable", never "Not verified".
- **FR-008** (`028-FR-008`): The Email row MUST offer Change…, opening the web account
  page, only when the server reports email delivery available; otherwise Change… is
  hidden and "Manage on the web…" remains (provisional Q4).
- **FR-009** (`028-FR-009`): The Apple and Google rows MUST show "Connected",
  "Connected · unavailable" or "Not connected" from the server's method list. "Remove…"
  (connected) and "Connect…" (not connected) MUST open the web account page; the Mac MUST
  NOT link or unlink a provider itself (provisional Q5).
- **FR-010** (`028-FR-010`): The Password row MUST show "Set · also used for Mac sign-in"
  when the account has a password, with Change… opening the web account page; without
  one it MUST show "Not set" with "Set on the web…" (provisional Q11).
- **FR-011** (`028-FR-011`): The "Your data" row MUST offer Export…, which opens a macOS
  save panel with the server-suggested file name and writes the account's ZIP export to
  the chosen location. It MUST be the same archive the web account export returns, with
  no additional confirmation step (provisional Q7), and MUST show progress with Cancel.
- **FR-012** (`028-FR-012`): A cancelled or failed export MUST leave no partial file at
  the chosen location and no copy elsewhere; the export file MUST NOT be retained by the
  app after it is written.
- **FR-013** (`028-FR-013`): The footer MUST show the existing sync status text and a
  Sign out… button that runs the existing Mac sign-out confirmation and flow unchanged
  (same wording, default button, unsent-change disclosure and failure state).
- **FR-014** (`028-FR-014`): With no account on this Mac, the Account tab MUST read "Not
  signed in" and offer Sign in…, opening the existing sign-in sheet (provisional Q8).
- **FR-015** (`028-FR-015`): Delete account… MUST open the web account deletion page for
  this account, with the 14-day text "Removed for good after 14 days; signing in cancels
  it." The Mac MUST NOT request deletion itself in this feature.
- **FR-016** (`028-FR-016`): Every web handoff MUST open the default browser on the web
  account origin reported by the server, at the account page (or its deletion page) for
  this account using the existing expected-owner destination, and MUST NOT place a
  session credential or secret in the URL. When the origin is absent or not https (or
  http on localhost), web buttons MUST be unavailable with an explanation.
- **FR-017** (`028-FR-017`): Offline, the tab MUST say the account details need a
  connection and offer Retry; when the session has ended, it MUST show the existing
  "Sign in again" state. Neither case may discard, alter or upload local tasks or
  unsent changes.
- **FR-018** (`028-FR-018`): Errors MUST be actionable: a short message, a Retry where
  retrying can help, and, when the server returned a correlation ID, that ID as a
  support reference. Rate-limited responses MUST NOT be retried automatically.
- **FR-019** (`028-FR-019`): Logs and diagnostics for this feature MUST record only
  outcome, stage, timing and correlation ID; they MUST NOT contain the name, email, method
  identities, export contents, file paths or session credentials.
- **FR-020** (`028-FR-020`): This feature MUST NOT add a native email-change, password,
  provider link/unlink or account-deletion flow. Any later native version MUST prove
  identity with a password exchanged for a short-lived, single-use recent proof bound to
  the action and account (provisional Q3), and any native code entry MUST accept 6 digits.
- **FR-021** (`028-FR-021`): The Settings window and its account surface MUST NOT be
  behind a feature flag: account management and data rights are always on.
- **FR-022** (`028-FR-022`): The window MUST follow the Carry On design tokens and the
  M25 Mac board in light and dark appearance, use sentence-case English copy, show sync
  and error states in words (never colour alone) and respect Reduce Motion.
- **FR-023** (`028-FR-023`): Every control MUST be reachable and operable from the
  keyboard with visible focus, and MUST have an accessible name and value for VoiceOver;
  ⌘W and the window close button close Settings.
- **FR-024** (`028-FR-024`): The feature MUST NOT change backend contracts, the web
  account page, the iPhone app's behavior, or the Mac sign-in, sign-out, Keychain and
  sync behavior defined by spec 021. Additions to the shared native kit MUST be additive.

### Key Entities

- **Account summary**: the signed-in account's display name, email, completed-step
  count and creation time, read from the server; held in memory only.
- **Sign-in methods**: the account's email verification state, email-delivery
  availability, password presence and the list of methods (password, email, Apple,
  Google) with state and usability; read from the server.
- **Web account destination**: the server-reported web origin plus this account's id,
  forming the account page or deletion page URL; carries no credential.
- **Export archive**: the ZIP of the account's data the server produces; written once to
  a location the person chooses.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001** (`028-SC-001`): On the reference MacBook Air M1, ⌘, shows the Settings
  window within 0.5 s and every row's live value (or its error state) within 2 s on a
  normal connection.
- **SC-002** (`028-SC-002`): For a set of test accounts covering verified/unverified
  email, each provider connected/not connected/unavailable, with and without a password
  and name, 100% of rows match the web account page for the same account.
- **SC-003** (`028-SC-003`): Each account right on the board — export, sign out, change
  email, change password, connect/remove Apple, connect/remove Google, delete account —
  is reachable from the Account tab in at most 2 interactions.
- **SC-004** (`028-SC-004`): A Mac export and a web export of the same account contain
  the same set of entries; both contain 0 auth secrets.
- **SC-005** (`028-SC-005`): In every failure case of User Stories 2 and 5 (offline,
  expired session, server error, cancelled export, unwritable location), 0 local tasks
  or unsent changes are lost or altered and 0 partial export files remain.
- **SC-006** (`028-SC-006`): 0 session credentials or secrets appear in any URL the app
  opens or in any log line the feature writes, checked over the full acceptance run.
- **SC-007** (`028-SC-007`): All Account tab actions can be completed with the keyboard
  alone, and every control has an accessible name, in light and dark appearance.

## Dependencies

Existing contracts this feature consumes (paths under `/api`; session cookie auth; no
change made by this feature):

| Need | Existing endpoint | Notes |
|---|---|---|
| Name, steps taken, email | `GET /account` | `display_name`, `completed_task_count`, `email` |
| Verified email, email delivery, password, methods | `GET /account/auth-methods` | may return 404/503 when modern auth is unavailable → rows "Unavailable" |
| Web account origin | `GET /auth/methods` | `web_account_origin`; `client` accepts only `web` or `ios` (Q9) |
| Export | `GET /account/export` | ZIP with `Content-Disposition` file name; auth secrets excluded |
| Sign out | existing Mac sign-out flow | spec 021; unchanged |
| Web destinations | `/settings/account?expected_owner=…`, `/settings/account/delete?expected_owner=…` | existing web routes and shared-kit destination builder used by the iPhone |

- Spec 027 (Rust server) MUST carry these routes unchanged; this feature relies on its
  capability inventory and adds no new server capability.
- Shared native kit (`ios/BrainBuddyKit`): today it has a method-list call but no calls
  for the account summary or export; the plan adds them additively.
- Design: `/speckit-design` produces `design.md` from the M25 Mac board and the Carry On
  tokens; M26–M28 sheets are recorded there as not built.

## Assumptions

- The provisional answers in Clarifications hold; any change by Max is applied to this
  spec before design.
- Mac sign-in remains email + password only (spec 021); accounts without a password are
  rare on the Mac.
- The web account page remains the place for credential changes and deletion, and
  accepts the existing expected-owner destination; the browser may ask the person to
  sign in on the web separately.
- No server, web or iPhone change is needed; the backend `client` limitation (Q9) does
  not block this feature because it builds no native email-code or provider flow.
- Primary loop impact: none. Capture, clarify/approve, routing, CRT, Weekly Review and
  evidence are unchanged. No AI processing and no new consent.
- Out of scope: Agents and Sync tabs, native M26–M28 sheets, name editing, session list,
  backend changes, task priorities.
