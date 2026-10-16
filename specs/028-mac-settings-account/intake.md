# Business Intake: Mac Account and Settings window (⌘,)

**Feature**: `specs/028-mac-settings-account/`
**Interviewed**: 2026-10-16
**Interviewee**: Max (product owner)
**Status**: Interview done. Max answered the five interview questions on 2026-10-16;
his answers are recorded verbatim below and are the source of every scope decision in
this file and in `spec.md` § Clarifications.

Assessment was skipped: the ask is a bounded native surface for account rights the
product already provides on the web (`AccountService`, never feature-flagged), drawn
on the design board. No matching assessment or kill verdict exists under
`.specify/assessments/`.

## The ask, as given

> Mac Account and Settings window (⌘,)

The design input is the Mac design board, cells M25–M28 (board version
`1792138611-15e1`; caption M25: "Settings (⌘,), Account tab."). Board files are design
data; the research summary is `/mnt/project-files/design/mac-feature6-groundwork.md`.

## Interview (2026-10-16)

Questions put to Max:

1. Tabs: the board shows Account | Agents | Sync. Which ship?
2. Change email, change password, delete account, connect/remove Apple and Google:
   native on the Mac, or open the web account page?
3. Password field before deleting the account (the board's M28 alert has none)?
4. Connect Apple / Google: in the app or on the web?
5. Name: editable or read-only (the board draws it read-only)?

Max's answer, verbatim (Russian):

> Так, делаем все как по борде. Первое по борде. Второе. Так, второе подразумевает
> еще, видимо, какие-то правки в самом приложении, не только интерфейс. Поэтому,
> видимо, его надо как-то в бэклог положить и сделать второе нормально. Оно,
> соответственно, с собой тянет и третье, и четвертое, и пятое. Как будто бы.

English rendering: "So, we do everything as on the board. The first one — as on the
board. The second: the second apparently also implies some changes in the app itself,
not only the interface. So it should apparently go to the backlog, and the second
should be done properly. It correspondingly pulls the third, the fourth and the fifth
along with it. Seemingly."

Resulting decisions (recorded as Max's answers):

| # | Question | Decision |
|---|---|---|
| 1 | Tabs | As the board: a tab bar with **Account, Agents, Sync**. Account per M25. Sync shows the Mac's existing sync status content. Agents shows a short empty state with a button that opens the web agents page until the Mac agents feature (feature 8) ships. |
| 2 | Native vs web for credential changes and deletion | Done **natively, as the board draws them**, but in a **separate follow-up feature** (backlog), because they need backend and app changes, not only interface. In 028 these buttons are **not shown at all**: no web handoff buttons for them and no dead buttons. |
| 3 | Password field before delete | Follows decision 2: the follow-up builds M28 as drawn (no password field), which needs a backend change. Not in 028. |
| 4 | Connect Apple / Google | Follows decision 2: native, in the follow-up. In 028 the Apple and Google rows show status only. |
| 5 | Name | As the board: read-only in 028. |

## 1. Problem

- **Whose problem**: a person using the native Mac app (spec 021) who is signed in
  to their BrainBuddy account.
- **How it shows up today**: the Mac app has no Settings window and does not respond
  to ⌘,. It cannot show who is signed in beyond the sync menu, how many steps they
  have taken, whether their email is verified, which sign-in methods are connected,
  or offer their data export.
- **What it costs**: a Mac app without ⌘, Settings breaks a platform convention, and
  the data export is reachable only by leaving the app on the person's own
  initiative. No measured baseline of support load or abandonment exists.
- **If we build nothing**: account state stays invisible on the Mac and export stays
  web-only.

## 2. Customer and persona

- **Primary**: an individual BrainBuddy user on macOS 26 with an account that has a
  password (Mac sign-in is email + password only, spec 021).
- **Secondary**: none.
- **Deployment shape**: multi-tenant with isolated per-owner data, currently a small
  MVP with no real users (AGENTS.md, 2026-10). Compliance obligations apply
  regardless of user count.

## 3. Business objective and KPI

Release acceptance measures, not measured business data:

| metric | baseline today | target | by when |
|---|---|---|---|
| Mac Settings window | none (no ⌘,) | ⌘, opens Settings with the board's three tabs | candidate release |
| Account rows on Mac shown from live server data | 0 | 100% of rows backed by an existing endpoint; 0 invented values | candidate release |
| Export ZIP on Mac | not available | same archive the web export produces for the same account | candidate release |
| Session credentials or secrets placed in URLs, logs or the export | — (invariant) | 0 | candidate release |

No deadline or adoption target was supplied.

## 4. Scope boundary

**In scope (confirmed by Max, 2026-10-16)**

- [x] A macOS Settings window opened with ⌘, (and the standard app-menu item) with the
      board's tab bar: Account, Agents, Sync (decision 1).
- [x] Account tab, natively: name (read-only), steps taken, email with its verified
      state, Apple and Google status, password state (decisions 1, 4, 5).
- [x] Native **Export…**: save the account's ZIP export through a macOS save panel.
- [x] Native **Sign out…**: the existing Mac sign-out confirmation.
- [x] Sync tab: the Mac's existing sync status content, no new behaviour.
- [x] Agents tab: a short empty state and one button opening the web agents page
      (`/settings/agents`) until the Mac agents feature (feature 8) ships.
- [x] Visual design follows the Carry On design system tokens and the M25 board.

**Out of scope (confirmed by Max, 2026-10-16)** — moved to a follow-up feature in
the backlog (see `spec.md` § Follow-up feature (backlog)):

- [x] Change email (M27 two-step code sheet), change password, connect/remove Apple
      and Google (M26), delete account (M28 as drawn). None of their buttons appears in
      028, neither native nor as a web handoff.
- [x] The backend and app changes those need (Mac `client` identity, Mac provider
      callback, deletion without a password field).

Also out of scope:

- [x] Name editing (the board draws the name read-only).
- [x] Native agents management (feature 8).
- [x] Session list / sign out other devices (no backend exists).
- [x] Task priorities in any form (ADR-0033 removed them).
- [x] A feature flag for this surface: account management is never feature-flagged.

**Confirmed by**: Max (product owner), 2026-10-16.

## 5. Constraints

- **Deadline**: none supplied.
- **Platform**: macOS 26 native app only. Web, iPhone and backend are unchanged.
- **Offline behavior**: account state needs the server; offline, the window says so
  with a retry and does not discard or alter local tasks or unsent changes. The
  existing offline sign-out behavior is reused unchanged.
- **Must not break**: Mac sign-in/sign-out and Keychain session storage (spec 021),
  the existing sign-out confirmation, sync status, the shared native kit used by the
  iPhone, the web account and agents pages, and the backend account and
  authentication contracts (spec 023), which this feature only consumes.
- **Budget / provider cost limits**: none; no new paid service.
- **Only real behavior**: every row and action is backed by an existing server
  endpoint or existing Mac code; nothing is drawn as if it were live.

## 6. Compliance obligation

`AccountService` already provides self-serve GDPR account management — profile,
email, password, ZIP data export, 14-day-grace deletion and purge — and is never
feature-flagged (see `docs/data-retention.md`). This feature adds a native Mac view of
account state and a native export.

- **New durable records**: none on the server. On the Mac, account details are held
  in memory for the window's lifetime only.
- **Consent**: none new. No AI or remote processing. Export writes personal data only
  to a location the person chooses.
- **Retention**: the exported file is the person's own copy; the app keeps no other
  copy. Existing Mac retention rows in `docs/data-retention.md` are unchanged.
- **Export**: the same ZIP the account export already produces (auth secrets
  excluded); no new export content.
- **Deletion and purge**: unchanged; deletion stays on the web until the follow-up.

## 7. Existing-system dependencies

- **Backend surfaces**: consumed only — `GET /account`, `GET /account/auth-methods`,
  `GET /auth/methods` (web origin for the Agents button) and `GET /account/export`.
  No backend change. Spec 027 (Rust server) keeps these routes (027 US4, FR-001).
- **Frontend surfaces**: the web agents page `/settings/agents` as the Agents tab's
  destination; unchanged.
- **Mobile**: iPhone app unchanged. The shared native kit (`ios/BrainBuddyKit`) gains
  additive account-summary, export and agents-destination calls.
- **AI providers**: not used.
- **Primary loop impact**: none on capture → atomic items → clarify/approve → route
  or CRT candidate → Weekly Review → evidence.

## 8. Definition of done

- [ ] Pressing ⌘, in the Mac app opens Settings with the Account, Agents and Sync tabs;
      pressing it again focuses the same window.
- [ ] A signed-in person sees their own name, steps taken, email and verified state,
      Apple/Google status and password state, matching the web account page for the
      same account.
- [ ] No Change…, Connect…, Remove… or Delete account… control appears anywhere in
      Settings.
- [ ] Export… saves a ZIP the person can open, through a save panel, with progress and
      cancel.
- [ ] Sign out… shows the existing confirmation and behaves exactly as the menu's
      Sign out….
- [ ] The Sync tab shows the same status, words and actions as the sync popover.
- [ ] The Agents tab's button opens the web agents page in the default browser, with
      no session credential in the URL.
- [ ] Offline, expired session and server errors leave local work untouched and show a
      clear retry or sign-in-again path.

## Contradictions surfaced

| earlier answer | later answer | resolution | decided by |
|---|---|---|---|
| Draft: Account tab only, no tab bar | Max: tabs as on the board | Tab bar with Account, Agents, Sync | Max, 2026-10-16 |
| Draft: credential changes and deletion open the web account page | Max: native as on the board, in a backlog follow-up | 028 shows none of those buttons; follow-up builds them natively | Max, 2026-10-16 |
| Board M27 draws 4 code digit cells | Backend requires exactly 6 digits | The follow-up's code sheet uses 6 digits | technical fact; recorded for the follow-up |
| Board M28 delete alert has no identity proof | Backend deletion requires a password or recent proof | The follow-up builds M28 as drawn and needs a backend change | Max, 2026-10-16 (decision 3) |
