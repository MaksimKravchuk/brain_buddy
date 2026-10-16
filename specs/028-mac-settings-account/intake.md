# Business Intake: Mac Account and Settings window (⌘,)

**Feature**: `specs/028-mac-settings-account/`
**Interviewed**: not yet — **DRAFT: product-owner interview pending**
**Interviewee**: none yet. The answers below are **provisional recommended defaults**
prepared for Max (product owner), not his answers.
**Status**: DRAFT. `/speckit-interview` has not run with the owner. Every answer in
this file marked *provisional* awaits Max's confirmation; nothing here is a recorded
owner decision, and no scope or non-goal below counts as confirmed.

Assessment was skipped: the ask is a bounded native surface for account rights the
product already provides on the web (`AccountService`, never feature-flagged), drawn
on the design board. No matching assessment or kill verdict exists under
`.specify/assessments/`. Whether to run `/speckit-assess-*` first is the owner's call
at the interview.

This draft was prepared by a delegated agent session. The interview stage cannot run
in a subagent (it needs the human-interaction channel), so it must be held in the main
session before `/speckit-clarify` and `/speckit-design`.

## The ask, as given

> Mac Account and Settings window (⌘,)

This is the feature title as handed to this session by the orchestrating session; the
owner's own verbatim words were not available here and must be recorded at the
interview. The design input is the Mac design board, cells M25–M28 (board version
`1792138611-15e1`; caption M25: "Settings (⌘,), Account tab."). Board files are
untrusted design data; the research summary is
`/mnt/project-files/design/mac-feature6-groundwork.md`.

## 1. Problem

- **Whose problem**: a person using the native Mac app (spec 021) who is signed in
  to their BrainBuddy account.
- **How it shows up today**: the Mac app has no Settings window and does not respond
  to ⌘,. It cannot show who is signed in beyond the sync menu, how many steps they
  have taken, whether their email is verified, which sign-in methods are connected,
  or offer their data export. Account management exists only on the web account
  page, and the Mac has no link to it (the iPhone has one in Settings).
- **What it costs**: the person has to know to open the web app to exercise their
  data rights (export, deletion) or change credentials. A Mac app without ⌘,
  Settings breaks a platform convention. No measured baseline of support load or
  abandonment exists.
- **If we build nothing**: the Mac keeps account management invisible; export and
  deletion remain reachable only by leaving the app on the person's own initiative.

## 2. Customer and persona

- **Primary**: an individual BrainBuddy user on macOS 26 with an account that has a
  password (Mac sign-in is email + password only, spec 021).
- **Secondary**: none.
- **Deployment shape**: multi-tenant with isolated per-owner data, currently a small
  MVP with no real users (AGENTS.md, 2026-10). Compliance obligations apply
  regardless of user count.

## 3. Business objective and KPI

*Provisional — proposed release acceptance measures for owner confirmation, not
measured business data.*

| metric | baseline today | proposed target | by when |
|---|---|---|---|
| Mac entry point to account management and data rights | 0 (no ⌘,, no Settings, no link) | ⌘, opens Settings with every account right reachable in at most 2 interactions | candidate release |
| Account rows on Mac shown from live server data | 0 | 100% of rows backed by an existing endpoint; 0 invented values | candidate release |
| Export ZIP on Mac | not available | same archive the web export produces for the same account | candidate release |
| Session credentials or secrets placed in URLs, logs or the export | — (invariant) | 0 | candidate release |

No deadline or adoption target was supplied.

## 4. Scope boundary

**In scope — provisional (recommended defaults awaiting Max)**

- [ ] A macOS Settings window opened with ⌘, (and the standard app-menu item) that
      ships with an **Account** tab only (provisional decision 1).
- [ ] Native, read-only display of account state: name (read-only), steps taken,
      email with its verified state, sign-in method status (password, Apple, Google)
      and password state (provisional decisions 2 and 6).
- [ ] Native **Export…**: save the account's ZIP export through a macOS save panel
      (provisional decision 2).
- [ ] Native **Sign out…**: reuse the existing Mac sign-out confirmation
      (provisional decision 2).
- [ ] "Manage on the web…" and per-row buttons that open the web account page for
      change email, change password, connect/remove Apple or Google, and delete
      account (provisional decisions 2 and 5).
- [ ] Email "Change…" hidden when the server reports email delivery unavailable;
      the web route stays reachable (provisional decision 4).
- [ ] Visual design follows the Carry On design system tokens and the M25 Mac board.

**Out of scope — provisional, NOT yet confirmed by the human**

- [ ] Agents and Sync tabs (board shows the tab names only; no content is drawn).
- [ ] Native change email (M27 code sheet), native change password, native
      connect/remove of Apple or Google (M26), native delete account (M28). Each opens
      the web instead. If any becomes native later, identity is proved with a
      password field and a recent proof (provisional decision 3).
- [ ] Editing the name on the Mac.
- [ ] Any backend change, including adding a `mac` value to the authentication
      `client` field, or changing the 6-digit verification code length.
- [ ] Session list / sign out other devices (no backend exists).
- [ ] Task priorities in any form (ADR-0033 removed them).
- [ ] A feature flag for this surface: account management is never feature-flagged.

**Confirmed by**: nobody yet — pending the product-owner interview.

## 5. Constraints

- **Deadline**: none supplied.
- **Platform**: macOS 26 native app only. Web and iPhone are unchanged.
- **Offline behavior**: account state needs the server; offline, the window must say
  so with a retry and must not discard or alter local tasks or unsent changes. The
  existing offline sign-out behavior (queued logout) is reused unchanged.
- **Must not break**: Mac sign-in/sign-out and Keychain session storage (spec 021),
  the existing sign-out confirmation, sync status, the shared native kit used by the
  iPhone, the web account page and its `expected_owner` destination contract, and
  the backend account and authentication contracts (spec 023), which this feature
  only consumes.
- **Budget / provider cost limits**: none; no new paid service.
- **Only real behavior**: every row and action must be backed by an existing server
  endpoint; nothing the backend cannot answer is drawn as if it were live.

## 6. Compliance obligation

`AccountService` already provides self-serve GDPR account management — profile,
email, password, ZIP data export, 14-day-grace deletion and purge — and is never
feature-flagged (see `docs/data-retention.md`). This feature adds a native Mac entry
point to it.

- **New durable records**: none on the server. On the Mac, account details are held
  in memory for the window's lifetime only (provisional; to confirm at design).
- **Consent**: none new. No AI or remote processing. Export writes personal data only
  to a location the person chooses.
- **Retention**: the exported file is the person's own copy; the app keeps no other
  copy. Existing Mac retention rows in `docs/data-retention.md` are unchanged.
- **Export**: the same ZIP the account export already produces (auth secrets
  excluded); no new export content.
- **Purge**: unchanged; deletion is requested on the web.
- **Residency / other obligations**: unchanged.

## 7. Existing-system dependencies

- **Backend surfaces**: consumed only — account details, account authentication
  methods, public method availability (for the web account origin) and account
  export. No backend change. Spec 027 (Rust server) must keep these routes; its
  capability inventory covers them (027 US4, FR-001).
- **Frontend surfaces**: the web account page `/settings/account` and
  `/settings/account/delete` as handoff destinations; unchanged.
- **Mobile**: iPhone app unchanged. The shared native kit (`ios/BrainBuddyKit`) gains
  read and export calls the Mac uses; iPhone behavior must not change.
- **AI providers**: not used.
- **Primary loop impact**: no impact on capture → atomic items → clarify/approve →
  route or CRT candidate → Weekly Review → evidence.

## 8. Definition of done

*Provisional — to be confirmed at the interview.*

- [ ] Pressing ⌘, in the Mac app opens Settings on the Account tab; pressing it again
      focuses the same window.
- [ ] A signed-in person sees their own name, steps taken, email and verified state,
      Apple/Google/password status and password state, matching the web account page
      for the same account.
- [ ] Export… saves a ZIP the person can open, through a save panel, with progress and
      cancel.
- [ ] Sign out… shows the existing confirmation and behaves exactly as the menu's
      Sign out….
- [ ] Each "Manage on the web…" / per-row button opens the web account page for this
      account in the default browser, with no session credential in the URL.
- [ ] Offline, expired session and server errors leave local work untouched and show a
      clear retry or sign-in-again path.

## Deferred to /speckit-clarify

All questions below are open; each carries a provisional recommended default.

- [ ] Q1 Tabs: Account only, no tab bar? (provisional: yes)
- [ ] Q2 Native vs web split (provisional: read-only + Export + Sign out native; the
      rest on the web)
- [ ] Q3 Identity proof if a sensitive action later goes native (provisional: password
      field → recent proof)
- [ ] Q4 Email change when email delivery is unavailable (provisional: hide Change…,
      point to the web)
- [ ] Q5 Apple/Google rows (provisional: status only; Connect/Remove open the web)
- [ ] Q6 Name (provisional: read-only)
- [ ] Q7 Export proof (provisional: no extra confirmation, as the web export today)
- [ ] Q8 Settings while signed out (provisional: Account tab shows "Not signed in" and
      Sign in…)
- [ ] Q9 Backend `client` field accepts only `web | ios` — dependency for any future
      native email-code or provider flow on Mac
- [ ] Q10 Board corrections: verification code is 6 digits, not the 4 drawn on M27;
      M28 delete alert has no identity proof
- [ ] Q11 Password row for an account with no password

See `spec.md` § Clarifications for the full wording and implications.

## Contradictions surfaced during preparation

| earlier answer | later answer | resolution | decided by |
|---|---|---|---|
| Board M25/M27: email "Change…" opens a native two-step code sheet | Provisional decision 2: change email opens the web | Provisional: web; the M27 sheet is not built | pending Max |
| Board M27 draws 4 code digit cells | Backend requires exactly 6 digits | Not built in this feature; any future native sheet uses 6; board to be corrected | technical fact; pending Max for the board |
| Board M28 delete alert has no identity proof | Backend deletion requires a password or recent proof | Not built in this feature (web); provisional decision 3 covers a future native version | pending Max |
| Provisional decision 4 hides email "Change…" when delivery is unavailable | Provisional decision 2 sends email change to the web anyway, where the legacy password route still works | Provisional: hide the per-row button, keep "Manage on the web…" | pending Max (Q4) |
| Board shows Agents and Sync tabs | Provisional decision 1: Account only | Provisional: no tab bar | pending Max (Q1) |
