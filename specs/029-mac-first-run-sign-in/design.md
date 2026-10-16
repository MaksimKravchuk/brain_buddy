# Design: Mac first run and sign-in

**Feature**: `specs/029-mac-first-run-sign-in/`
**Spec**: [spec.md](spec.md) (thread decisions 2026-10-16; (c) answered 2026-10-16:
Rust only; pending (a), (b))
**Screen source**: the "Carry On · first run" board page, version `1792138611-15e1`
(`DSOnboard.dc.html`), Mac cells **M01** Welcome, **M02** First capture, **M03** First
step, **M04** Landing, **M05** Sign in, **M06** Invite. No separate HTML mockup is
produced: the board cells are the approved renders, and every deviation is listed in
[Deviations from the board](#deviations-from-the-board).
**Human sign-off**: pending — Max to confirm this state inventory before
`/speckit-review`.

<!-- Ids are stable once written; never renumber. ADR-0006: the term is Tag. -->

## Applicability

Two surfaces in the existing main window and one sheet:

- **F-** ids: the first run inside the main window (Inbox welcome, inspector first step,
  Next actions landing, first-run sidebar).
- **A-** ids: the sign-in sheet (choice, code, password, outcomes, invite).

Reused unchanged: the capture field and mic button (`CarryOnMacCapture.swift`), the Mac
inspector panel (`CarryOnMacInspector.swift`), the next-step card and its "Done" / "Not
now" (spec 021 slices 2–3), the sidebar brand and footer (`SyncPresentation.swift:126`),
the password form, Advanced and errors of spec 021 X-03, and the account-deletion-cancelled
alert.

## Screen inventory

| id | surface | screen | board | FR refs |
|---|---|---|---|---|
| F-01 | Main window › Inbox (empty, first run) | Welcome and first capture | M01, M02 | 029-FR-002 – 029-FR-007, 029-FR-014 |
| F-02 | Main window › Inbox list + inspector | First step | M03 | 029-FR-008 – 029-FR-010 |
| F-03 | Main window › Next actions | Landing with one tip | M04 | 029-FR-011 |
| F-04 | Main window › sidebar | First-run sidebar | M01–M04 | 029-FR-012 |
| A-01 | Sheet over the main window | Sign in or create an account | M05 | 029-FR-018, 029-FR-019, 029-FR-021, 029-FR-026 |
| A-02 | A-01 › Send me a code | Check your email | not drawn (iPhone copy) | 029-FR-020 |
| A-03 | A-01 › Use a password instead | Email and password | 021 X-03 | 029-FR-022 |
| A-04 | A-01 after a completion | Outcomes | not drawn | 029-FR-023 – 029-FR-025 |
| A-05 | A-01 after `INVITE_REQUIRED` | Enter your invite code | M06 | 029-FR-028 – 029-FR-030 |

## Layout (from the board)

- **Window**: 1280 × 800 reference; `bg-ground`; glass sidebar as today.
- **F-01 welcome block**: centred in the Inbox content column, max width 560 pt. Mark +
  "Carry On" (serif 44), 28 pt gap, "What feels heaviest?" (serif 36, `text-primary`),
  12 pt gap, the instruction line (`text-secondary`, 15 pt), 24 pt gap, the capture field
  (existing `CarryOnMacCapture` field, focus ring `focus-ring`, mic button inside on the
  trailing edge), 20 pt gap, two hint rows (chip on `surface-token` with the shortcut or
  the mic glyph, then `text-secondary` text), 24 pt gap, the "No account needed" line
  (`text-secondary`). In the typed state (M02) the two lines "Goes to Inbox, as you wrote
  it" (`text-secondary`) and "Return to add · Esc to skip" (`text-secondary`, 12 pt) sit
  4 pt under the field; the hint rows stay.
- **F-02**: the Inbox list header "1 thing to sort"; the row selected (`surface-selected`).
  The inspector is the existing 380 pt panel: caption "Inbox · 1 of 1" (`text-secondary`),
  the item text (`text-primary`), "What is the first step you could take?" (serif 24),
  the step field (`surface-card`, focus ring), the helper line (`text-secondary`), then
  the action bar: "Make it my next step" (`button-primary-bg` / `-fg`, the accent; the only
  one) and "Not yet" (quiet).
- **F-03**: toolbar as today ("New step ⌘N", ⌘O). List header "Next actions · 1 step".
  The next-step card as today with label "Now" (no project). The tip under the card: a
  `surface-card` box with `control-quiet` border, the tip text (`text-primary`, 14 pt) and
  a secondary button "Got it" (`button-secondary-bg` / `-fg`).
- **F-04**: sidebar brand, then "Lists" (Inbox, Next actions, Waiting for, Someday) and
  "Dates" (Overdue, Today, Upcoming), rows without trailing counts; no Projects, Archived
  projects or Tags sections; footer "On this Mac · Sign in to sync" as today.
- **A-01**: sheet 440 pt wide, `surface-card`, 24 pt padding. Title "Sign in or create an
  account" (serif 24), the kept-tasks line (`text-secondary`), the provider button(s) drawn
  as their guidelines require (Google: white/neutral face with the Google mark; Apple per
  (a)), the "or" divider (`control-quiet` rules), the Email field (focused), "Send me a
  code" as drawn — an ink button, 32 pt tall, background `text-primary`, label
  `bg-ground`, full width beside "Cancel" (quiet) — then "Use a password instead" (quiet
  link) and "Advanced" (disclosure, existing).
- **A-05**: same sheet. "New account · <email>" caption (`text-secondary`), "Enter your
  invite code" (serif 24), the explanation (`text-secondary`), one monospaced code field
  (default per (b)), the keep-local line (`text-secondary`), then "Create account" (the
  same ink button as "Send me a code", not the accent) and "Back" (quiet).
- Colours are design-system roles only (`CarryOnColorStyle`), light and dark. The accent
  (`accent-fill`, terracotta) appears only on "Make it my next step" and the next-step
  card's mark, as on the board.

## State inventory

### F-01 — Welcome and first capture

| key | state | what shows | FR |
|---|---|---|---|
| F-01.01 | Welcome, empty field | M01: block above; field focused; hints per F-01.04/.05 | 029-FR-003 |
| F-01.02 | Typing | M02: the two lines under the field | 029-FR-006 |
| F-01.03 | Return with text | Item added as written → F-02.01 | 029-FR-006 |
| F-01.04 | Shortcut registered / unavailable | Chip "⌃⌥⇧B" + "Capture from any app, without switching to Carry On." / no chip, "⌃⌥⇧B is unavailable. Use Quick Capture in the toolbar." | 029-FR-004 |
| F-01.05 | Speech available / unavailable | Mic chip + "Speech becomes text on this Mac. It asks for the microphone the first time." and the mic button / neither | 029-FR-005 |
| F-01.06 | Listening (mic pressed) | Existing voice capture states in the field; text arrives in the field, Return still adds | 029-FR-005 |
| F-01.07 | Esc (empty or typed) | First run ends (outcome `skipped`); empty Inbox without the welcome; F-04 → normal sidebar | 029-FR-007 |
| F-01.08 | Return with no text | Nothing happens | 029-FR-006 |
| F-01.09 | Capture save failed | Existing capture error under the field; text stays in the field | 029-FR-006 |

### F-02 — First step

| key | state | what shows | FR |
|---|---|---|---|
| F-02.01 | Asking, empty field | M03 with "Make it my next step" unavailable | 029-FR-008, 029-FR-009 |
| F-02.02 | Step written | "Make it my next step" available; Return chooses it | 029-FR-009 |
| F-02.03 | Saving | Buttons unavailable; static under Reduce Motion | 029-FR-009 |
| F-02.04 | Saved | → F-03.01 | 029-FR-009, 029-FR-011 |
| F-02.05 | Save failed | Existing inspector save error; item unchanged in the Inbox; question stays | 029-FR-009 |
| F-02.06 | Not yet / Esc | First run ends (outcome `notYet`); Inbox with the item selected in the normal Inbox inspector | 029-FR-010 |

### F-03 — Landing

| key | state | what shows | FR |
|---|---|---|---|
| F-03.01 | Tip shown | M04 without "Garage": card "Now" / step, Done, Not now; the tip and "Got it" | 029-FR-011 |
| F-03.02 | Tip, shortcut unavailable | Tip text without ", or ⌃⌥⇧B from any app" | 029-FR-011 |
| F-03.03 | Got it | Tip gone; first run done; F-04 → normal sidebar | 029-FR-011, 029-FR-012 |
| F-03.04 | Relaunch before Got it | Opens on Next actions with the tip | 029-FR-011 |

### F-04 — First-run sidebar

| key | state | what shows | FR |
|---|---|---|---|
| F-04.01 | During F-01 – F-03 | Lists and Dates only, no counts, footer | 029-FR-012 |
| F-04.02 | First run ended | Today's sidebar (counts, Projects, Tags, History) | 029-FR-012 |

### A-01 — Sign in or create an account

| key | state | what shows | FR |
|---|---|---|---|
| A-01.01 | Loading methods | Title, kept-tasks line, "Loading sign-in methods…", the password link | 029-FR-019 |
| A-01.02 | Methods loaded | M05 with only the offered buttons; Email field focused when email is offered | 029-FR-018 |
| A-01.03 | Methods failed | "Couldn't load sign-in methods. Try again or use your password." + Try again | 029-FR-019 |
| A-01.04 | Google running | System authentication window; sheet buttons unavailable; "Please wait…" | 029-FR-021 |
| A-01.05 | Google cancelled | Back to A-01.02, nothing changed | 029-FR-021 |
| A-01.06 | Offline | Offline words of 029-FR-025; Cancel available | 029-FR-025 |
| A-01.07 | Sign in again | Title "Sign in again", existing subtitle and footer, same methods | 029-FR-024 |
| A-01.08 | Password only (server does not know `macos`, i.e. the Python server until the Rust cutover) | Title, kept-tasks line, the password form of A-03 directly, "Cancel" and "Advanced"; no Google button, no email field, no "or", no "Use another method", no load-failure message | 029-FR-018, 029-FR-019 |

### A-02 — Check your email

| key | state | what shows | FR |
|---|---|---|---|
| A-02.01 | Code sent | "Check your email", the explanation, the 6-digit field focused, "Verify code" (unavailable until 6 digits), "Expires <time>", "Resend in Ns", "Use another method" | 029-FR-020 |
| A-02.02 | Resend available | "Resend code" | 029-FR-020 |
| A-02.03 | Wrong / expired / too many | The server's error in words under the field; field cleared on expired | 029-FR-020, 029-FR-025 |

### A-03 — Password

| key | state | what shows | FR |
|---|---|---|---|
| A-03.01 | Any | 021 X-03 form and errors, completed through the native attempt; "Use another method" returns to A-01 | 029-FR-022 |

### A-04 — Outcomes

| key | state | what shows | FR |
|---|---|---|---|
| A-04.01 | Signed in | Sheet closes; spec 021 behaviour; the deletion-cancelled alert when it applies; first run ends | 029-FR-013, 029-FR-023 |
| A-04.02 | Collision | "Connect to your existing account" + explanation + "Sign in to existing account" (→ A-01) | 029-FR-023 |
| A-04.03 | Invite required, before PR-07 | "This sign-in has no account yet. Carry On is invite-only for now." / "No code? Keep using Carry On on this Mac; nothing is lost." / "Back" | 029-FR-023 |
| A-04.04 | Another account on sign in again | "Sign out first to use another account."; nothing linked | 029-FR-024 |
| A-04.05 | Server error | Message + "Reference: <correlation id>" when present | 029-FR-025 |

### A-05 — Enter your invite code (PR-07)

| key | state | what shows | FR |
|---|---|---|---|
| A-05.01 | Default | M06 with one code field focused (pending (b)); "Create account" unavailable while empty | 029-FR-028, 029-FR-029 |
| A-05.02 | Submitting | Buttons unavailable; "Please wait…" | 029-FR-029 |
| A-05.03 | Invalid code | "That invite code didn't work. Check it and try again." under the field | 029-FR-030 |
| A-05.04 | Expired | The kit's `InviteStepCopy.expired` words and "Back to sign in" only | 029-FR-030 |
| A-05.05 | Too many tries | "Too many tries. Try again in a few minutes."; "Create account" unavailable until the server's retry time | 029-FR-030 |
| A-05.06 | Back / closed | A-01; nothing created | 029-FR-030 |

## Copy

| key | text |
|---|---|
| Welcome | Carry On · What feels heaviest? · Write it as it is and press Return. It goes to the Inbox; you sort it in a moment. |
| Field placeholder | Type, or press the mic to speak |
| Hints | ⌃⌥⇧B — Capture from any app, without switching to Carry On. · [mic] — Speech becomes text on this Mac. It asks for the microphone the first time. |
| Hotkey unavailable | ⌃⌥⇧B is unavailable. Use Quick Capture in the toolbar. (existing) |
| No account | No account needed. Your tasks stay on this Mac until you sign in. |
| Typing | Goes to Inbox, as you wrote it · Return to add · Esc to skip |
| First step | 1 thing to sort · Inbox · 1 of 1 · What is the first step you could take? · Small enough to start today. Not sure yet? Leave it in the Inbox. · Make it my next step · Not yet |
| Landing | Next actions · 1 step · Now · This is your next step. When it is done, press Done. Anything else on your mind: ⌘N here, or ⌃⌥⇧B from any app. ⌘O finds any step. · Got it |
| Footer | On this Mac · Sign in to sync (existing) |
| Sign in | Sign in or create an account · The tasks on this Mac are kept. Signing in adds them to your account. · Continue with Google · or · Email · Send me a code · Cancel · Use a password instead · Advanced |
| Methods | Loading sign-in methods… · Couldn't load sign-in methods. Try again or use your password. · Try again |
| Code | Check your email · If this address can be used, you will receive a code. Use another email or method if it doesn't arrive. · Email code · Verify code · Expires <time> · Resend in <n>s · Resend code · Use another method |
| Collision | Connect to your existing account · Sign in to your existing account, then explicitly connect this method in account settings. Matching email doesn't merge accounts. · Sign in to existing account |
| Invite interim | This sign-in has no account yet. Carry On is invite-only for now. · No code? Keep using Carry On on this Mac; nothing is lost. · Back |
| Invite | New account · <email> · Enter your invite code · Carry On is invite-only for now. No account uses this sign-in yet, so a code creates one. · Invite code · No code? Keep using Carry On on this Mac; nothing is lost. · Create account · Back · That invite code didn't work. Check it and try again. · Too many tries. Try again in a few minutes. · Back to sign in |
| Existing (021) | Sign in again · Sign out first to use another account. · Can't reach the server. Check your connection. · Signing in is the only thing that needs a connection. Everything else keeps working on this Mac. · Reference: <id> · Please wait… |

## Deviations from the board

| board element | 029 | reason |
|---|---|---|
| M04 card label "Garage · now" | "Now" | No project is created (thread T3); matches the iPhone cell |
| M05 "Continue with Apple" | hidden | Pending (a); recommended later (029-FR-026) |
| M06 six code cells in two groups | one field | Pending (b); codes are 43 characters |
| M05 caption "Target, not today …" | built now for Google, email, password; Google and email shown only when `methods` reports them for `macos` (Rust server); password only against the Python server (A-01.08) | Thread T5; Max's answer to (c), Rust only |
| Code step, outcomes, loading and error states | not drawn | A-02, A-04, A-01.01/.03/.06 with the iPhone's and 021's words |
| Password-only sheet | not drawn | A-01.08: M05's title and kept-tasks line over the 021 X-03 form, for a server that does not know `macos` ((c)) |
| "Not yet" landing, Esc on M01 | not drawn | F-02.06, F-01.07 |
| Dark appearance for M02–M06 | not drawn | Tokens' dark values |

## Affordance → requirement map

| affordance | state | requirement |
|---|---|---|
| Welcome field Return / Esc | F-01.02 – F-01.08 | 029-FR-006, 029-FR-007 |
| Mic button | F-01.05, F-01.06 | 029-FR-005 |
| Make it my next step / Not yet | F-02.01 – F-02.06 | 029-FR-009, 029-FR-010 |
| Got it | F-03.03 | 029-FR-011 |
| Footer "Sign in to sync" | F-04.01, A-01 | 029-FR-018 |
| Continue with Google | A-01.04, A-01.05 | 029-FR-021 |
| Send me a code / Verify / Resend | A-02 | 029-FR-020 |
| Use a password instead | A-03 | 029-FR-022 |
| Create account / Back | A-05 | 029-FR-029, 029-FR-030 |

Requirements with no affordance: 029-FR-001 (clean-Mac decision), 029-FR-013,
029-FR-014, 029-FR-015 (record), 029-FR-016 / 029-FR-017 (client value), 029-FR-027
(secrets), 029-FR-032, 029-FR-033.

## Keyboard and focus

- F-01: focus in the capture field on appear; Return adds; Esc skips; Tab reaches the mic
  button, then the sidebar footer's "Sign in to sync".
- F-02: focus moves to the step field when the question appears; Return = "Make it my
  next step" when enabled; Esc = "Not yet"; Tab order field → primary → Not yet.
- F-03: focus on "Got it" when the tip appears; Return or Space dismisses; the card's
  existing keyboard actions are unchanged.
- A-01: focus in the Email field (or the first offered button when email is not offered);
  Esc = Cancel; Return in Email = Send me a code.
- A-02: focus in the code field; Return verifies when 6 digits are entered.
- A-05: focus in the code field; Return = Create account when enabled; Esc = Back.
- VoiceOver: the hints read as "Shortcut, Control Option Shift B, Capture from any app …";
  the tip is announced once politely; errors are announced once.
- Focus ring: `focus-ring` role, visible in both appearances.

## Primary loop impact

The first run takes one item through capture → Inbox → clarify (first step) → Next
actions with existing commands. Weekly Review, CRT and evidence are unchanged.

## Mobile viability

Not applicable: macOS-only surfaces. The iPhone keeps its sign-in sheet; the iPhone's
first-run cells are not built here.
