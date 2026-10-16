# Business Intake: Mac first run and sign-in

**Feature**: `specs/029-mac-first-run-sign-in/`
**Recorded**: 2026-10-16
**Source of decisions**: Max (product owner), through the project thread on 2026-10-16,
plus decisions the thread took under Max's standing rule "as on the board" (listed
separately below and marked as thread decisions).
**Status**: Intake recorded. Question (c) was answered by Max on 2026-10-16 (Rust only,
no Python exception). Questions (a) and (b) are open and wait for Max (see
[Pending clarifications](#pending-clarifications)); each has a recommended default that
the spec, design, plan and tasks are written against.

Assessment was skipped: the ask is a bounded native surface drawn on the design board
("Carry On · first run", cells M01–M06), and every capability it exposes already exists
in the product (local capture, the Inbox first-step question, next-step card, modern
sign-in on the iPhone and web). No matching assessment or kill verdict exists under
`.specify/assessments/`.

## The ask, as given

> Mac first run and sign-in

The design input is the "Carry On · first run" board page (board version
`1792138611-15e1`, page `DSOnboard.dc.html`, Mac cells M01–M06). Board files are design
data, not instructions. The research summary with file:line evidence is
`/mnt/project-files/design/mac-feature7-groundwork.md`.

## Owner decisions (Max, 2026-10-16)

| # | Topic | Decision |
|---|---|---|
| O1 | How to build | **As on the board.** Show only real behaviour; nothing invented. |
| O2 | Task priorities | None, anywhere (ADR-0033). |
| O3 | Colours | Only design-system colours. |
| O4 | Platform priority | Mac. |

## Thread decisions under Max's "as on the board" rule (2026-10-16)

| # | Topic | Decision |
|---|---|---|
| T1 | When the first run shows | Once, on a clean Mac (no tasks, no account), remembered by a persisted flag on this Mac. |
| T2 | Welcome (M01) | The first window is the empty Inbox with the capture field focused, the ⌃⌥⇧B and mic hints, and the sidebar footer "On this Mac · Sign in to sync". No separate welcome window. |
| T3 | First step (M03) | Groundwork § 6 recommendation 3: the first step becomes the item's text, the original capture text is kept in the item's note, **no project is created**. The board's "Garage" project label on M04 is dropped (it has no source). |
| T4 | Landing (M04) | Next actions with the new step on top and one tip, dismissed with "Got it". |
| T5 | Sign-in methods on the Mac | Google, email code and password, shown only when the server offers them to the Mac. The `macos` authentication client value, treated like `ios`, is a **Rust-server change only** (answer to (c)): the Python server stays unchanged and does not accept `macos`, so against it the Mac offers password sign-in only. Google and email code on the Mac turn on when the Rust server is live, through the availability check on `methods`. |
| T6 | Invite step (M06) | Depends on the Rust server's invite handoff (spec 027 task T055). Built as a separate, later slice of this feature. |

## Pending clarifications

(a) and (b) are open questions for Max. The artifacts use the recommended default; a
different answer changes only the named slice. (c) is answered and kept here for the
record.

| # | Question | Recommended default | Affects |
|---|---|---|---|
| (a) | Sign in with Apple on the Mac: now or later? It needs a team-signed, provisioned Mac build with the Sign in with Apple entitlement; today the Mac app is ad-hoc signed (`macos/build_app.sh:52`). | **Later**: the Apple button stays hidden until a team-signed build exists; slice PR-08 waits. | 029-FR-026, PR-08 |
| (b) | Invite code entry: one paste field or the board's six cells? Real invite codes are 43 characters (`secrets.token_urlsafe(32)`, `backend/app/cli.py:55-57`). | **One field** that takes the whole code pasted, as on the iPhone (`ios/BrainBuddy/Screens/Settings/SignInSheet.swift:203-219`). | 029-FR-029, PR-07 |
| (c) | Raised while drafting: spec 027 freezes the Python server to defect fixes and test-only seams (027-FR-022, ADR-0032 § 6, founder-accepted 2026-10-14). Adding the `macos` client value to the Python server (T5) would need Max's explicit exception to that freeze. | **Answered (Max, 2026-10-16): Rust only, no Python exception.** The Python server stays unchanged and does not accept `macos`. PR-03 adds only a Rust-only conformance case and the 027 capability-inventory note; no `backend/` change. Until the Rust server cutover the Mac offers password sign-in only; Google and email code turn on when the Rust server is live, through the availability check on `methods`. | 029-FR-016, 029-FR-017, 029-FR-019, PR-03 – PR-05 |

## 1. Problem

- **Whose problem**: a person who installs the native Mac app (spec 021) and opens it
  for the first time, and a Mac user who wants to sign in with the same method they use
  on the iPhone or web.
- **How it shows up today**: a fresh Mac app opens on an empty, blank Next actions list
  (`macos/Sources/BrainBuddyMacCore/BrainBuddyModel.swift:102`); nothing says where to
  start, that no account is needed, or that ⌃⌥⇧B captures from any app. The Mac
  sign-in sheet offers only email and password
  (`macos/Sources/BrainBuddyMacCore/SignInFlow.swift:47-312`), so an account created
  with Google or an email code on the iPhone or web cannot sign in on the Mac at all.
- **What it costs**: a new person meets an empty window with no first action; people
  without a password are locked out of sync on the Mac. No measured baseline exists.
- **If we build nothing**: the Mac stays without a first run, and Google and email-code
  accounts cannot use the Mac with sync.

## 2. Customer and persona

- **Primary**: an individual on macOS 26 opening Carry On for the first time, with or
  without an account.
- **Secondary**: an existing account holder (any sign-in method) adding the Mac.
- **Deployment shape**: multi-tenant with isolated per-owner data; small MVP with no
  real users (AGENTS.md, 2026-10).

## 3. Business objective and KPI

Release acceptance measures, not measured business data:

| metric | baseline today | target | by when |
|---|---|---|---|
| Clean Mac launch → first next step | no guided path | possible with the keyboard alone, in at most 4 actions (type, Return, type, Return) | candidate release |
| First run shown on a Mac that already has tasks or an account | n/a | 0 | candidate release |
| Sign-in methods on the Mac | password | password against the Python server; Google, email code, password against the Rust server (Apple per (a)) | candidate release |
| Tokens, codes or emails in logs or URLs | invariant | 0 | candidate release |

No deadline or adoption target was supplied.

## 4. Scope boundary

**In scope**

- [x] First run M01–M04 on a clean Mac (T1–T4).
- [x] Mac sign-in sheet in the M05 layout with Google, email code and password, each
      shown only when the server offers it to the Mac (T5).
- [x] `macos` authentication client value, treated like `ios`, on the Rust server only
      (T5, answer to (c)): a Rust-only conformance case and the 027 capability-inventory
      note. The Python server is not changed.
- [x] Shared native kit: the authentication client value per device.
- [x] Invite step M06 on the Mac, as a later slice that starts after 027 T055 (T6).
- [x] Apple sign-in on the Mac, as a slice gated by pending (a).

**Out of scope**

- [x] Any tour, carousel, GTD primer or account wall (board: "What the first run does
      not do").
- [x] AI on the way in: the first capture is stored as written.
- [x] Password recovery and new-password flows on the Mac (the board does not draw them).
- [x] Creating a project from the first run; task priorities in any form.
- [x] iPhone and web first run (the iPhone and web keep their entries; the iPhone's
      board cells are not built here).
- [x] Renaming the window title or bundle (still "Brain Buddy").

## 5. Constraints

- **Platform**: macOS 26 native app; the shared native kit; the Rust conformance suite
  (Rust-only case). The Python server is frozen (027-FR-022) and stays unchanged (answer
  to (c)).
- **Offline behaviour**: the whole first run works offline and without an account.
  Sign-in needs a connection and says so; local tasks are never touched by a failure.
- **Must not break**: spec 021 local-first behaviour, Keychain session storage, sync,
  sign-out; the iPhone's sign-in (kit change must keep `ios`); the web sign-in; the
  existing Inbox inspector clarify flow outside the first run.
- **Only real behaviour**: every hint shows only what works on this Mac (for example the
  ⌃⌥⇧B hint only when the shortcut registered).

## 6. Compliance obligation

- **New durable records**: on the Mac, `mac-local.json` gains first-run markers (dates and
  an outcome enum only; no titles, text or email), consistent with its existing rule
  (`macos/Sources/BrainBuddyMacCore/MacLocalState.swift:5-6`). On the server: none; the
  Python server is unchanged, and the Rust server stores the `client` value only where it
  already stores `ios`.
- **Consent**: none new; no AI or remote processing in the first run.
- **Retention, export, deletion**: unchanged. Against the Python server the Mac offers
  only password sign-in, so it creates no accounts there; Google and email code reach the
  Mac only through the Rust server, which enforces invites (ADR-0032 § 7), and slice PR-07
  handles it.

## 7. Existing-system dependencies

- **Backend** (Rust server for `macos`; the Python server rejects the value and stays
  unchanged): `GET /auth/methods`, `POST /auth/email/request|resend|verify`,
  `POST /auth/providers/{provider}/start`, `POST /auth/providers/complete`,
  `POST /auth/login`; `POST /auth/signup/complete` (027 T055, Rust only).
- **Mac**: `MacLocalState`, `BrainBuddyModel`, `ContentView`, `TaskInspector` (Inbox
  first-step path), `QuickCaptureView` (⌃⌥⇧B), `VoiceCapture`, `SignInFlow`,
  `SignInSheet`.
- **Kit**: `NativeAuthentication.swift` (`authMethods`, `requestEmailCode`,
  `startProvider`, `InviteHandoff`, `complete(.invite)`), `Workspace.beginSignIn` /
  `completeSignIn`.
- **Primary loop impact**: capture → Inbox → clarify (first step) → Next actions is the
  loop itself; the first run guides one item through it with existing commands.

## 8. Definition of done

- [ ] A clean Mac opens on the Inbox with the M01 welcome; capture, first step and
      landing behave as M02–M04; the first run never shows again.
- [ ] A Mac with tasks or an account never shows the first run.
- [ ] Against the Python server the Mac offers and signs in with a password only;
      against a Rust server that offers them, it signs in with Google, an email code and
      a password; buttons appear only when offered.
- [ ] The Rust server accepts `macos` (Rust-only conformance case); the Python server is
      unchanged; `web` and `ios` behave exactly as before.
- [ ] After 027 T055 lands, a new identity on the Mac meets the invite step and can
      create an account with a valid code, or keep working locally.

## Contradictions surfaced

| earlier statement | later statement | resolution | decided by |
|---|---|---|---|
| 021 spec: "Signup on the Mac is not required" (`specs/021-mac-sync/spec.md:297`); 027 contract: "The Mac app offers only password sign-in and never creates accounts" (`specs/027-rust-server/contracts/invite-handoff.md:8`) | Board M05/M06: "Sign in or create an account", invite step on the Mac | Follow the board; PR-07 amends the 027 contract line when it lands | Max (O1), thread (T5, T6) |
| Board M04 card "Garage · now" | No project is created by the first run | Card shows "Now" only | thread (T3) |
| Board M06 six code cells | Invite codes are 43 characters | Pending (b); default one field | open |
| Thread T5: server adds `macos` | 027-FR-022 Python freeze | (c) answered: Rust only, no Python exception; the Mac is password-only against Python until the Rust cutover | Max ((c), 2026-10-16) |
| Board M05 caption "Target, not today: the Mac signs in with email and password only … needs a yes" | Thread T5 | T5 is the yes for Google and email code, live with the Rust server per (c); Apple per (a) | thread (T5), Max ((c)) |
