# Feature Specification: Mac first run and sign-in

**Feature Branch**: `029-mac-first-run-sign-in`

**Created**: 2026-10-16

**Status**: Clarified, with three pending clarifications for Max ((a), (b), (c)); every
artifact is written against their recommended defaults. Design: [design.md](design.md).
Plan: [plan.md](plan.md). Tasks: [tasks.md](tasks.md).

**Input**: User description: "Mac first run and sign-in". Design input: the "Carry On ·
first run" board page, Mac cells M01–M06 (board version `1792138611-15e1`, design data).
Business requirements: [intake.md](intake.md). Research with file:line evidence:
`/mnt/project-files/design/mac-feature7-groundwork.md`.

## Context

The native Mac app (spec 021) works without an account: tasks stay on this Mac until the
person signs in. A fresh install opens on an empty, blank Next actions list
(`BrainBuddyModel.swift:102`); there is no first run. The global capture shortcut ⌃⌥⇧B
(`QuickCaptureView.swift:60-68`) and on-device speech (`VoiceCapture.swift:23,77`) exist
but nothing teaches them. The Inbox inspector already asks for a first step
(`TaskInspector.swift:174-183,455`).

Mac sign-in is email and password only (`SignInFlow.swift:47-312`). The iPhone and web
already sign in with Google and an email code (spec 023), through kit calls that
hard-code the `ios` client (`NativeAuthentication.swift:139,149,163`); the server accepts
only `web` and `ios` (`backend/app/schemas/modern_auth.py:13`).

The board draws a first run in four steps — Welcome (M01), First capture (M02), First
step (M03), Landing (M04) — and a sign-in sheet (M05) and invite step (M06) for the Mac.
This feature builds them with real behaviour only.

## Clarifications

### Session 2026-10-16 (owner decisions and thread decisions)

Owner decisions (Max): build as on the board, show only real behaviour, nothing invented;
no task priorities; only design-system colours; Mac first. Thread decisions under that
rule are recorded in [intake.md](intake.md#thread-decisions-under-maxs-as-on-the-board-rule-2026-10-16).

- Q1: When does the first run show? → A (thread, T1): once, on a clean Mac — no tasks and
  no account — remembered by a flag persisted on this Mac. Affects 029-FR-001,
  029-FR-002, 029-FR-015.
- Q2: What is the welcome? → A (thread, T2): the empty Inbox with the capture field
  focused, the ⌃⌥⇧B and mic hints and the sidebar footer "On this Mac · Sign in to sync".
  Affects 029-FR-003 – 029-FR-005, 029-FR-012.
- Q3: What happens to the captured item at the first step? → A (thread, T3): the step
  text becomes the item's text, the original capture text is kept in the item's note, no
  project is created; the board's "Garage" label is dropped. Affects 029-FR-009,
  029-FR-011.
- Q4: Where does the first run end? → A (thread, T4): on Next actions with the new step
  on top and one tip with "Got it". Affects 029-FR-011.
- Q5: Which sign-in methods does the Mac get now? → A (thread, T5): Google, email code and
  password; the server adds a `macos` client value treated like `ios`. Affects
  029-FR-016 – 029-FR-025.
- Q6: Invite step? → A (thread, T6): depends on the Rust server's invite handoff (027
  T055); a separate, later slice. Affects 029-FR-028 – 029-FR-030.

### Pending clarifications (awaiting Max)

- **(a)** Sign in with Apple on the Mac needs a team-signed build with the Sign in with
  Apple entitlement; the Mac app is ad-hoc signed today. **Recommended: later.** Until a
  team-signed build exists, no Apple button appears (029-FR-026) and slice PR-08 does not
  start.
- **(b)** Invite code entry. Real codes are 43 characters; the board draws six cells.
  **Recommended: one field that takes the whole code pasted** (029-FR-029).
- **(c)** Raised while drafting: the Python server is frozen to defect fixes by 027-FR-022
  (ADR-0032 § 6). **Recommended: a one-value exception** for `macos`, added to the Python
  server, the Rust conformance suite and the 027 capability inventory together
  (029-FR-017). If declined, Google and email code on the Mac wait for the Rust cutover,
  and the Mac keeps password sign-in until then.

## User Scenarios & Testing *(mandatory)*

Stories are numbered in delivery order; no story carries a priority.

### User Story 1 - Welcome and first capture on a clean Mac

A person opens Carry On on a Mac that has never held tasks or an account. The window
opens on the Inbox, which shows the welcome: the logo and "Carry On", "What feels
heaviest?", a line saying where things go, a focused capture field, hints for ⌃⌥⇧B and
the mic, and "No account needed. Your tasks stay on this Mac until you sign in." They
type what is on their mind and press Return; it goes to the Inbox exactly as written.

**Independent Test**: delete the app's data folder, launch, type a sentence, press Return;
the Inbox holds one item with exactly that text, and no network request was made.

**Acceptance Scenarios**:

1. **Given** a clean Mac, **When** the app launches, **Then** the main window shows the
   Inbox with the welcome block and the capture field has keyboard focus.
2. **Given** the welcome, **When** the person types, **Then** "Goes to Inbox, as you
   wrote it" and "Return to add · Esc to skip" appear under the field.
3. **Given** typed text, **When** the person presses Return, **Then** one Inbox item is
   created with that text unchanged, and the first-step question appears (User Story 2).
4. **Given** the welcome with or without typed text, **When** the person presses Esc,
   **Then** nothing is added, the first run ends, and the Inbox stays open without the
   welcome; the welcome never returns.
5. **Given** the global shortcut could not be registered, **When** the welcome shows,
   **Then** the ⌃⌥⇧B hint is replaced by the existing words "⌃⌥⇧B is unavailable. Use
   Quick Capture in the toolbar."
6. **Given** a Mac that already has tasks, an account, or a recorded first run, **When**
   the app launches, **Then** no welcome appears and the app opens as it does today.

---

### User Story 2 - First step and landing

After the first capture, the Inbox lists "1 thing to sort" with the item selected, and
the inspector asks "What is the first step you could take?" with a focused field. The
person writes a step and chooses "Make it my next step": the step becomes the item's
text, the original words are kept in its note, and it moves to Next actions. The window
shows Next actions with the step on top and one tip about Done, ⌘N, ⌃⌥⇧B and ⌘O.
"Got it" dismisses the tip for good.

**Independent Test**: on a clean Mac capture "the garage is a mess and Sam needs the van
back", write "Call Sam about the van", press Return; Next actions shows that step with
the note holding the original sentence, no project exists, and the tip shows once.

**Acceptance Scenarios**:

1. **Given** the first capture, **When** it is added, **Then** the Inbox shows "1 thing to
   sort", the item is selected, and the inspector shows "Inbox · 1 of 1", the item text,
   the question, a focused empty field, "Small enough to start today. Not sure yet? Leave
   it in the Inbox.", "Make it my next step" and "Not yet".
2. **Given** an empty or whitespace-only step field, **Then** "Make it my next step" is
   unavailable.
3. **Given** a step written, **When** the person chooses "Make it my next step" (or
   presses Return), **Then** the item's text becomes the step, its note holds the original
   capture text, it is in Next actions, and no project was created.
4. **Given** the move succeeded, **Then** the window shows Next actions with the step as
   the next-step card labelled "Now" (no project label), its existing "Done" and "Not now"
   actions, and one tip with "Got it".
5. **Given** the tip, **When** the person chooses "Got it", **Then** the tip disappears and
   never shows again, and the sidebar shows its normal sections.
6. **Given** the question, **When** the person chooses "Not yet" (or presses Esc),
   **Then** the item stays in the Inbox unchanged, the first run ends, and no tip shows.
7. **Given** the app quits during the first run after the capture, **When** it launches
   again, **Then** the item is still in the Inbox and the first run does not resume.

---

### User Story 3 - Sign in on the Mac with Google, an email code or a password

From the sidebar footer "On this Mac · Sign in to sync" (or the menu), the person opens
the sign-in sheet: "Sign in or create an account", "The tasks on this Mac are kept.
Signing in adds them to your account.", "Continue with Google", "or", an email field with
"Send me a code", "Cancel", "Use a password instead" and "Advanced". Buttons appear only
for the methods the server offers to the Mac.

**Independent Test**: against a server offering Google and email, sign in once with each
of Google, an email code and a password on a clean Mac with local tasks; each ends signed
in to the expected account with the local tasks added.

**Acceptance Scenarios**:

1. **Given** the server offers Google and email, **When** the sheet opens, **Then** it
   shows the M05 layout without an Apple button (029-FR-026) and with the email field
   focused.
2. **Given** an email entered, **When** the person chooses "Send me a code", **Then** the
   sheet asks for the 6-digit code with Verify, a resend countdown and the expiry time;
   a correct code signs in.
3. **Given** "Continue with Google", **When** the person completes Google in the system
   sign-in window, **Then** the Mac is signed in; when they cancel it, the sheet is back on
   its first step and nothing changed.
4. **Given** "Use a password instead", **Then** the existing email and password form
   appears and behaves as today, including Advanced → server address.
5. **Given** the server's method list cannot be read, **Then** the sheet says "Couldn't
   load sign-in methods. Try again or use your password." with Try again, and the
   password path stays available.
6. **Given** a sign-in completes, **Then** the existing spec 021 behaviour follows: local
   tasks are added to the account, sync starts, and a cancelled account deletion is
   announced as today.

---

### User Story 4 - Sign in again keeps the same account

When the session ended, "Sign in again" offers the same methods. Signing in to a
different account than the one linked to this Mac is refused, and nothing changes.

**Independent Test**: link account A, end its session from the web, sign in again on the
Mac with Google identity B; the Mac refuses, stays linked to A, and keeps unsent changes.

**Acceptance Scenarios**:

1. **Given** an ended session, **When** the sheet opens, **Then** it reads "Sign in again"
   with the existing subtitle and footer, and offers the methods the server offers.
2. **Given** a completion for another account, **Then** the Mac shows "Sign out first to
   use another account.", links nothing, and keeps local tasks and unsent changes.

---

### User Story 5 - Invite step for a new identity (after 027 T055)

When the server answers that a new identity needs an invite, the Mac shows the M06 step:
"New account · <email>", "Enter your invite code", why, one code field, "No code? Keep
using Carry On on this Mac; nothing is lost.", "Create account" and "Back".

**Independent Test**: against the Rust server with the invite handoff, sign in with an
email code for an address without an account; enter a valid invite; the account is
created and the Mac is signed in. Repeat with no code and "Back"; nothing is created and
local tasks are untouched.

**Acceptance Scenarios**:

1. **Given** `INVITE_REQUIRED`, **Then** the invite step appears with the field focused.
2. **Given** a pasted 43-character code, **When** "Create account" is chosen, **Then** the
   account is created and the Mac is signed in as in User Story 3.
3. **Given** an invalid code, expired step, or too many tries, **Then** the step says so in
   words; an expired step offers only "Back to sign in".
4. **Given** "Back" or closing the sheet, **Then** nothing is created and the Mac keeps
   working locally.

### Edge Cases

- A clean Mac where the one-time import of the old `local-gtd.json` brings tasks: not
  clean; no first run.
- The person signs in from the footer during the first run: the first run ends when the
  account is linked; a captured item is kept and synced like any local task.
- Esc in the first-step field: equals "Not yet".
- The ⌃⌥⇧B registration fails after the welcome shows (another app takes it): the hint
  reflects the state at the time the welcome is shown; the landing tip omits the
  ⌃⌥⇧B clause when it is unavailable.
- Speech is unavailable on this Mac: no mic button and no mic hint.
- The microphone was denied earlier by the system: pressing the mic shows the existing
  voice-capture message; the welcome does not ask in advance.
- The step text equals the original text: the note is not written twice; the item keeps
  the text.
- Saving the first step fails (store write error): the existing save error appears, the
  item stays in the Inbox unchanged, and the first run stays on the question.
- Email delivery is unavailable on the server (`email: false`): no email field; Google
  and the password path remain.
- A Google identity whose email belongs to another account: the iPhone's collision words
  ("Connect to your existing account" …); nothing is linked.
- Before 027 T055 (or on the Python server), a new identity simply gets an account (the
  server's current behaviour); on a Rust server before PR-07, `INVITE_REQUIRED` shows the
  interim message of 029-FR-023.
- Reduce Motion, increased contrast, dark appearance: tokens in both appearances, no
  motion when reduced.

## Requirements *(mandatory)*

Requirement ids are feature-qualified. Each definition shows the bare id the
repository's checkers parse (`- **FR-001**`) followed by its feature-qualified id
(`029-FR-001`); tests and other artifacts MUST cite the qualified form (`029-FR-001`, or
`029_FR_001` in a Swift or Python test name).

### Functional Requirements

**First run (M01–M04)**

- **FR-001**: (`029-FR-001`) On launch the Mac app MUST show the first run only when this
  Mac has no recorded first run, no linked account, and a workspace with no tasks and no
  projects (after any legacy import). Otherwise it MUST record the first run as not
  needed, without showing anything. A recorded first run MUST persist on this Mac across
  launches and is never shown again.
- **FR-002**: (`029-FR-002`) When the first run shows, the main window MUST open on the
  Inbox. Every other launch MUST open as today (Next actions).
- **FR-003**: (`029-FR-003`) The empty Inbox during the first run MUST show the welcome
  (M01): the Carry On mark and "Carry On", "What feels heaviest?", "Write it as it is and
  press Return. It goes to the Inbox; you sort it in a moment.", the capture field
  (placeholder "Type, or press the mic to speak") with keyboard focus, the hints of
  029-FR-004 and 029-FR-005, and "No account needed. Your tasks stay on this Mac until you
  sign in." There MUST be no separate welcome window, tour, carousel or account wall.
- **FR-004**: (`029-FR-004`) The ⌃⌥⇧B hint ("Capture from any app, without switching to
  Carry On.") MUST appear only when the global capture shortcut is registered; otherwise
  the hint MUST show the existing words "⌃⌥⇧B is unavailable. Use Quick Capture in the
  toolbar."
- **FR-005**: (`029-FR-005`) The mic button and hint ("Speech becomes text on this Mac. It
  asks for the microphone the first time.") MUST appear only when on-device speech capture
  is available on this Mac. The microphone permission MUST be requested only when the
  person first presses the mic (existing behaviour).
- **FR-006**: (`029-FR-006`) While text is in the welcome's field, it MUST show "Goes to
  Inbox, as you wrote it" and "Return to add · Esc to skip". Return MUST add one Inbox
  item whose text is exactly what was typed (trimmed of surrounding whitespace; no
  splitting, parsing or AI). Return with no text MUST do nothing.
- **FR-007**: (`029-FR-007`) Esc in the welcome MUST end the first run without adding
  anything; the Inbox stays open without the welcome.
- **FR-008**: (`029-FR-008`) After the first capture, the Inbox MUST show "1 thing to
  sort" with the item selected, and the inspector MUST show the first-step question (M03):
  "Inbox · 1 of 1", the item text, "What is the first step you could take?", an empty
  focused step field, "Small enough to start today. Not sure yet? Leave it in the Inbox.",
  "Make it my next step" (the only accent button) and "Not yet".
- **FR-009**: (`029-FR-009`) "Make it my next step" (and Return in the step field) MUST be
  unavailable while the step field is empty or whitespace. When chosen, it MUST set the
  item's text to the step, keep the original capture text in the item's note (unless it
  equals the step), move the item to Next actions, and create no project, using the
  existing task commands. A failed save MUST leave the item unchanged in the Inbox with
  the existing save error.
- **FR-010**: (`029-FR-010`) "Not yet" (and Esc in the step field) MUST leave the item in
  the Inbox unchanged and end the first run without a tip.
- **FR-011**: (`029-FR-011`) After "Make it my next step", the window MUST show Next
  actions with the step as the next-step card labelled "Now" (no project label) with its
  existing "Done" and "Not now", and one tip: "This is your next step. When it is done,
  press Done. Anything else on your mind: ⌘N here, or ⌃⌥⇧B from any app. ⌘O finds any
  step." with "Got it" (the ⌃⌥⇧B clause omitted when the shortcut is unavailable). The tip
  MUST show until "Got it" is chosen, including after a relaunch, and never after.
- **FR-012**: (`029-FR-012`) While the first run is shown (welcome through tip), the
  sidebar MUST show only Lists (Inbox, Next actions, Waiting for, Someday / maybe) and
  Dates (Overdue, Today, Upcoming) without counts, and the footer "On this Mac · Sign in
  to sync". When the first run ends, the sidebar MUST return to its normal content.
- **FR-013**: (`029-FR-013`) A sign-in that links an account at any first-run step MUST
  end the first run; nothing captured is lost.
- **FR-014**: (`029-FR-014`) The first run MUST work offline and without an account; it
  MUST make no network request, no AI call and no permission request of its own.
- **FR-015**: (`029-FR-015`) The first-run record MUST hold only dates and an outcome
  (shown and how it ended, or not needed; tip dismissed); it MUST NOT hold any text the
  person typed.

**Sign-in (M05)**

- **FR-016**: (`029-FR-016`) The shared native kit MUST send the authentication client
  value of the device it runs on — `ios` on the iPhone (unchanged) and `macos` on the Mac —
  on the methods, email-code request and resend, and provider start calls.
- **FR-017**: (`029-FR-017`) The server MUST accept `macos` as an authentication client
  value and treat it like `ios` (native session, no browser binder, the `brainbuddy://`
  return, the native channel), except that it MUST report Apple as not offered and refuse
  an Apple start for `macos` until a Mac Apple audience is configured (PR-08). Behaviour
  for `web` and `ios` MUST NOT change. (Python server per pending (c); the Rust server
  through the conformance suite.)
- **FR-018**: (`029-FR-018`) The Mac sign-in sheet MUST follow M05: "Sign in or create an
  account", "The tasks on this Mac are kept. Signing in adds them to your account.", the
  provider buttons the server offers, "or", the email field and "Send me a code" when
  email is offered, "Cancel", "Use a password instead" and "Advanced" (server address,
  existing behaviour).
- **FR-019**: (`029-FR-019`) The sheet MUST read the offered methods from the chosen
  server with the `macos` client, show "Loading sign-in methods…" meanwhile, and on failure
  show "Couldn't load sign-in methods. Try again or use your password." with Try again,
  keeping the password path available.
- **FR-020**: (`029-FR-020`) "Send me a code" MUST request an email code and show the code
  step: "Check your email", "If this address can be used, you will receive a code. Use
  another email or method if it doesn't arrive.", a 6-digit field (digits only), "Verify
  code", the expiry time, "Resend in Ns" / "Resend code", and "Use another method". A wrong,
  expired or rate-limited code MUST be reported in words without signing in.
- **FR-021**: (`029-FR-021`) "Continue with Google" MUST run Google in the system's
  authentication session (ephemeral, returning through `brainbuddy://`), then complete the
  sign-in. Cancelling MUST return to the sheet's first step with nothing changed.
- **FR-022**: (`029-FR-022`) "Use a password instead" MUST show the existing email and
  password sign-in with its existing words and errors, completed through the kit's native
  sign-in attempt (`Workspace.beginSignIn` / `completeSignIn`).
- **FR-023**: (`029-FR-023`) Every sign-in outcome MUST be handled in words: signed in
  (spec 021 local-task merge and the account-deletion-cancelled note, unchanged); an
  identity whose email belongs to another account ("Connect to your existing account" /
  "Sign in to your existing account, then explicitly connect this method in account
  settings. Matching email doesn't merge accounts."); and, until PR-07, an invite required
  ("This sign-in has no account yet. Carry On is invite-only for now." / "No code? Keep
  using Carry On on this Mac; nothing is lost." / "Back"). None of them may touch local
  tasks.
- **FR-024**: (`029-FR-024`) "Sign in again" MUST offer the same methods, and a completion
  for an account other than the one linked to this Mac MUST be refused with "Sign out first
  to use another account.", linking nothing and keeping local tasks and unsent changes.
- **FR-025**: (`029-FR-025`) Offline, the sheet MUST say "Can't reach the server. Check
  your connection." and "Signing in is the only thing that needs a connection. Everything
  else keeps working on this Mac."; server errors MUST show a short message and, when the
  server returned one, the correlation id as a support reference. Rate-limited requests
  MUST NOT be retried automatically.
- **FR-026**: (`029-FR-026`) "Continue with Apple" MUST appear only when the server offers
  Apple for `macos` and this build carries the Sign in with Apple capability (pending (a);
  with the recommended default it does not appear in 029's builds).
- **FR-027**: (`029-FR-027`) The session token MUST stay in the login Keychain as today;
  codes, tokens, verifiers, invite codes and email addresses MUST NOT appear in logs, URLs
  the app opens, or `mac-local.json`.

**Invite step (M06, after 027 T055)**

- **FR-028**: (`029-FR-028`) When a sign-in completion answers `INVITE_REQUIRED`, the sheet
  MUST show the invite step: "New account · <email>" (the email the person entered, or
  none for Google), "Enter your invite code", "Carry On is invite-only for now. No account
  uses this sign-in yet, so a code creates one.", the code field, "No code? Keep using
  Carry On on this Mac; nothing is lost.", "Create account" (ink, not the accent colour)
  and "Back".
- **FR-029**: (`029-FR-029`) The invite code field MUST accept the whole code pasted or
  typed in one field (pending (b)); "Create account" MUST be unavailable while it is empty.
  It MUST submit the handoff with the code (`POST /auth/signup/complete`) and, on success,
  continue as a signed-in outcome (029-FR-023).
- **FR-030**: (`029-FR-030`) An invalid code, an expired step and too many tries MUST be
  reported in words (expired offers only "Back to sign in"; too many tries waits for the
  server's retry time); "Back" and closing the sheet MUST create nothing and keep local
  work.

**Across the feature**

- **FR-031**: (`029-FR-031`) New surfaces MUST follow the board and the Carry On tokens in
  light and dark appearance, use only design-system colours (the accent only for the one
  primary action), sentence-case English, states in words, keyboard operation with visible
  focus, VoiceOver names, and respect Reduce Motion.
- **FR-032**: (`029-FR-032`) Nothing in the feature may show a value or action that is not
  backed by real behaviour, and nothing may show task priority. The first run and sign-in
  are not behind a feature flag.
- **FR-033**: (`029-FR-033`) The feature MUST NOT change the iPhone's or the web's sign-in
  behaviour, sync, sign-out, the Keychain storage, or the Inbox inspector outside the first
  run. Kit changes MUST keep the iPhone's requests byte-identical.

### Key Entities

- **First-run record** (`mac-local.json`, device-only): when the first run was decided,
  its outcome (`notNeeded`, `skipped`, `notYet`, `firstStep`, `signedIn`), and when the
  landing tip was dismissed. No text.
- **First capture**: an ordinary Inbox task; after the first step its title is the step
  and its note (details) the original text.
- **Authentication client value**: `web`, `ios` or `macos`, sent by each client on the
  modern authentication calls.
- **Sign-in attempt**: the kit's native attempt (challenge and verifier), which the Mac
  completes with a password, an email code or a provider result.
- **Invite handoff**: the server's opaque, single-use pending token of `INVITE_REQUIRED`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: (`029-SC-001`) On a clean Mac, a person reaches Next actions with their
  first step in at most 4 keyboard actions after launch (type, Return, type, Return).
- **SC-002**: (`029-SC-002`) Over a launch matrix (clean; with tasks; with legacy import;
  with an account; after skip; after not yet; after first step; after relaunch mid-run),
  the welcome appears in 100% of clean launches with no record and 0% of the others.
- **SC-003**: (`029-SC-003`) During the first run, 0 network requests and 0 permission
  prompts occur unless the person presses the mic or opens sign-in.
- **SC-004**: (`029-SC-004`) After "Make it my next step", 100% of first captures keep their
  original text in the note, and 0 projects are created.
- **SC-005**: (`029-SC-005`) Against a server offering Google and email, the Mac signs in
  with each of Google, an email code and a password, landing in the same account the
  iPhone reaches for the same identity.
- **SC-006**: (`029-SC-006`) Server: every existing modern-authentication test for `web`
  and `ios` passes unchanged, and the `macos` cases pass on the Python server and in the
  Rust conformance suite.
- **SC-007**: (`029-SC-007`) In every failure case (offline, cancel, wrong code, collision,
  invite required, another account on sign-in again, failed first-step save), 0 local
  tasks or unsent changes are lost or altered.
- **SC-008**: (`029-SC-008`) 0 codes, tokens, verifiers, invite codes or email addresses
  appear in any log line, opened URL or `mac-local.json` over the acceptance run.
- **SC-009**: (`029-SC-009`) Every first-run and sign-in action can be done with the
  keyboard alone, every control has an accessible name, in light and dark appearance.

## Dependencies

| Need | Existing contract | Change |
|---|---|---|
| Offered methods | `GET /auth/methods?client=` | accepts `macos` (029-FR-017) |
| Email code | `POST /auth/email/request`, `/resend`, `/verify` | accepts `macos` |
| Google | `POST /auth/providers/{provider}/start`, `/providers/complete` | accepts `macos`; Apple refused for `macos` until PR-08 |
| Password | `POST /auth/login` through the native attempt | none |
| Invite step | `403 INVITE_REQUIRED` + `POST /auth/signup/complete` | none here; 027 T055 (Rust) |
| Local capture, move, notes | kit `GTDCommand` `createTask`, `updateTask` (title, details), `transitionTask` | none |
| Global shortcut, voice | `QuickCaptureView`, `VoiceCapture` | read their availability |

- Spec 027 (Rust server) must carry the `macos` value; this feature adds the conformance
  case and the capability-inventory row (PR-03). PR-07 amends
  `specs/027-rust-server/contracts/invite-handoff.md:8`, which says the Mac never creates
  accounts.

## Assumptions

- The Google OAuth client that serves the web and the iPhone serves the Mac (one web
  client, `brainbuddy://` return through the system authentication session).
- On the Python server, a new identity by Google or email code creates an account without
  an invite, as it does for the iPhone today; the Rust server's invite rule (ADR-0032 § 7)
  is handled by PR-07.
- Primary loop impact: the first run guides one item through capture → Inbox → clarify →
  Next actions with existing commands; Weekly Review, CRT and evidence are unchanged. No AI
  and no new consent.
- Out of scope: password recovery on the Mac, Apple before (a) is answered, the iPhone and
  web first run, the window title, task priorities.
