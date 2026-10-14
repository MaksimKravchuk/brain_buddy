# Design: Rust server

**Feature**: `specs/027-rust-server/`
**Spec**: `spec.md` (Clarifications settled: 2026-10-14)
**Screens**: [design/update-required.html](design/update-required.html), [design/fresh-start.html](design/fresh-start.html), [design/invite-step.html](design/invite-step.html), all self-contained static HTML (inline CSS, system fonts, no script, no external resources)
**Human sign-off**: owner (Max) approved this design for planning on 2026-10-14, with the decisions recorded in [Owner decisions](#owner-decisions-2026-10-14) (confirmation before the fresh-start deletion, superseding the earlier silent reset; one imprecise refusal at cutover accepted; release epoch carried in `X-Client-Epoch`, remaining detection details left to `/speckit-plan`). Revised the same day after spec review campaigns 1 and 2 (campaign 2 added the invite step for new identities, the persistent web refusal toast, the `/api/meta` epoch signal and CLI exit code 12)

<!--
  Produced by /speckit-design via the design-architect subagent. Ids are stable
  forever once written; never renumber. ADR-0006: the term is Tag.
-->

## Applicability

This feature is a server rewrite with no intended change to user-visible
behavior (FR-005, FR-020). It has three user-visible surfaces, designed
below:

1. **Update required** (FR-018): an older client build is refused with an
   actionable error and nothing is written. No new screen: the refusal reuses
   the 026 "Update needed to sync" state on iPhone and Mac, the existing native
   error alert, and on the web a persistent variant of the shell toast. CLI and
   MCP get fixed plain text, specified below.
2. **Fresh start after update** (FR-021): once the updated iPhone or Mac app
   learns that its server runs the new release epoch, and only if earlier local
   data exists, it asks before deleting that data (owner decision, 2026-10-14;
   Constitution I and V: destructive actions are visible and confirmed). The
   flow is confirm → delete → existing sign-in / create-account sheet →
   existing empty Inbox.
3. **Invite step for a new identity** (FR-007, amended 2026-10-14): creating an
   account by any method needs an invite. When email-code, Apple or Google
   sign-in completes for an identity that has no account, the
   existing sign-in surface asks for an invite code before anything is
   created. Password signup keeps its existing invite field.

New UI in this feature is limited to: the fresh-start confirmation and its
failure state, the invite step, and the persistent web refusal toast.

M- ids are iPhone, D- ids are Mac and web. State keys combine screen id and
suffix, for example `M-02.01`. Suffixes are shared within a screen pair.

## Screen inventory

| id | surface | screen | purpose | FR refs |
|---|---|---|---|---|
| M-01 | iPhone, existing sync row + Settings › Sync + existing error alert | Update required | Tell the person this build can no longer reach their account, and send them to the update; keep local editing | FR-018, FR-016 |
| D-01 | Mac, existing sync row + sync popover + existing error alert | Update required | Same as M-01 on Mac | FR-018, FR-016 |
| D-02 | Web, persistent alert variant of the shell toast + existing sign-in form error line | Update required | A tab opened before a release is told to reload | FR-018, FR-016, FR-020 |
| M-02 | iPhone, full screen when the new server is first seen, then existing sign-in sheet + existing Inbox | Fresh start (confirmed) | Ask before deleting earlier local data, delete it, then the existing signed-out flow. History: notice (first draft) → silent reset → confirmation (2026-10-14); id kept | FR-021 |
| D-03 | Mac, window-modal sheet when the new server is first seen, then existing sign-in sheet + existing Inbox | Fresh start (confirmed) | Same as M-02 on Mac | FR-021 |
| D-04 | Web, a step on the existing sign-in / provider-completion page | Invite step | Ask a new identity for an invite code before an account is created | FR-007 |
| M-03 | iPhone, a step in the existing sign-in sheet | Invite step | Same as D-04 on iPhone (email code, Apple, Google) | FR-007 |
| D-05 | Mac, existing sign-in sheet | Invite step: not applicable today | The Mac offers password sign-in only (`SignInFlow.swift`), which never creates an account, so it cannot receive `INVITE_REQUIRED`. Id reserved; if the Mac gains a provider or email-code method, it reuses M-03's states and copy | FR-007 |

CLI and MCP have no screen and no id; their exact text is in
[CLI and MCP wording](#cli-and-mcp-wording).

## State inventory

### Shared rule for M-01 / D-01 / D-02: when the refusal is shown

**Release epoch signal.** Every first-party client of this release sends a
dedicated integer header, `X-Client-Epoch`, on every request. Older builds do
not send it. The server refuses a request on a gated route whose epoch is
missing or lower than its minimum. In the other direction, the server reports
its own epoch through `GET /api/meta` (unauthenticated, exempt from the gate,
returning `{ "server_epoch": n, "min_client_epoch": n }`; the old server answers
404, read as epoch 0) and through the `X-Server-Epoch` header on every
response. Detection does not use the marketing version in `X-Client`. Details,
exemptions and the MCP rule live in `contracts/release-epoch.md`.

The refusal is shown **only** after the server answers with the explicit
version refusal (HTTP 426, code `UPGRADE_REQUIRED`). It is never inferred from no network, a timeout, a 5xx, a redirect
or an unreadable body; those keep their existing error states. Once a refusal
has arrived, the native apps keep showing it, including while offline. It
clears when the app is updated **or** a later request succeeds, whichever comes
first (as in `contracts/release-epoch.md`). 026's status priority is unchanged: unsupported
version → session ended → issues → persistent failure → offline → waiting →
synced.

**Server message** (the `message` field of the existing
`{message, detail, reference_id}` envelope; the native `APIError` and the web
error helper in `frontend/src/utils/error.ts` already display the server message, so older builds show it
without a client change):

| client | message |
|---|---|
| iPhone, Mac | `This version of Brain Buddy is out of date. Update it to continue. Nothing in your account was changed.` |
| web | `Brain Buddy has been updated. Reload this page to continue. Nothing in your account was changed.` |
| CLI | see below |
| MCP | see below |

The response also carries `X-Correlation-ID` and `reference_id` (FR-016).

### M-01 / D-01 — Update required (iPhone, Mac)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| .01 default (refused, sync) | sync handshake or push answered `UPGRADE_REQUIRED` | Existing sync row turns to the 026 update state; details show waiting count, reference ID, Update app, Copy reference ID; Sync now disabled with reason; local editing continues; no command is sent | Row: "Update needed to sync". Heading: "Update Brain Buddy to keep syncing". Body (this release and later): "This version can't sync with your account anymore. Update Brain Buddy to keep syncing." "Reference ID: …". Disabled reason: "Sync now is unavailable until you update." **Old builds only, at this cutover:** they show their shipped 026 body, "Your saved tasks and waiting changes stay on this device." (owner decision 2). New builds do not repeat that promise, because a later fresh start could delete that data | FR-018, FR-016 |
| .02 loading (checking) | first sync or handshake in flight | Existing "Syncing" indicator after 1 s (021 timing); previous status kept; no refusal shown | "Synced 3 min ago · Syncing" / "Not synced yet · Syncing" (existing) | FR-018 |
| .03 offline / interrupted | no network, or relaunch before the server answered | Existing offline status. Must **not** say an update is needed: the app cannot tell yet. A refusal already received (.01) stays shown | "Offline · 3 changes waiting" / "Your changes are saved on this device." (existing) | FR-018 |
| .04 error (direct request refused) | a non-sync request (sign-in, account, voice, AI, Review) answered `UPGRADE_REQUIRED` | Existing error alert with the server message and reference ID; Update app, OK. Focus behavior: see [Keyboard and focus](#keyboard-and-focus) | Server message + " Reference ID: …." | FR-018, FR-016 |
| .05 empty (first run, not signed in) | account-less use, no server call | Unchanged "On this iPhone" / "On this Mac" status; no refusal until a request is made (signing in leads to .04) | "Sign in to sync" (existing) | FR-018 |
| .06 empty (filtered to nothing) | N/A | No filter on this surface | — | — |
| .07 partial failure | N/A by contract | The server refuses before any write: a refused push applies no command; the whole outbox stays local and waiting. There is no half-applied batch to show | — | FR-018 |
| .08 other failure (not a refusal) | timeout, 5xx, unreadable answer | Existing 026 `.07` error; never "Update needed" | "Couldn't sync" / "Couldn't reach Brain Buddy. Your changes are saved here." + Reference ID (existing) | FR-016, FR-018 |

### D-02 — Update required (web)

The web app ships with the server, so only a tab loaded before a release can be
older. The shell's text toast (`shellToast.ts`) is `role="status"` and
auto-dismisses after 2.6 s, so it cannot carry a refusal the person must act
on. D-02 adds one **persistent alert variant** of that toast. It keeps the
shell toast's tokens (white/95, slate-200 border, 12 px radius,
shadow-floating) and sits fixed at top centre, under the top bar, so its DOM
order matches its position.

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| .01 default (refused) | any request answered with the version refusal | Persistent alert toast: `role="alert"`, no auto-dismiss, a "Reload" button that reloads the page, a "Dismiss" button, and the existing `(ref: …)` suffix. Only one is shown at a time; a later refusal after Dismiss shows it again. Focus rules: see [Keyboard and focus](#keyboard-and-focus) | "Brain Buddy has been updated. Reload this page to continue. Nothing in your account was changed. (ref: …)" Buttons: "Reload", "Dismiss" | FR-018, FR-016, FR-020 |
| .02 loading (checking) | request in flight | The existing `Spinner` (role status, label "Loading"), shown only if the request is still pending after **300 ms**. The web app has no shared onset rule today, so this threshold is set here for the stale-tab journey. Nothing else changes until the server answers | — | FR-018 |
| .03 offline / interrupted | network failure | Existing network error with its reference; no update message | (existing) | FR-016, FR-018 |
| .04 error (signed out) | sign-in or signup refused | Same message on the existing sign-in form error line | Same message + "(ref: …)" | FR-018, FR-016 |
| .05 empty (first run) | N/A | The refusal does not depend on list contents | — | — |
| .06 empty (filtered) | N/A | — | — | — |
| .07 partial failure | N/A by contract | Refused before any write | — | FR-018 |

### M-02 / D-03 — Fresh start, confirmed (iPhone, Mac)

**Activation.** The fresh start is triggered only when the app's configured
server reports the new release epoch. A new build alone does not trigger it. A
TestFlight build installed before cutover therefore keeps working against the
old server and deletes nothing (.00). The check is `GET /api/meta`, made
**before any sign-in, session use or sync push**: on launch, on reconnect, on
return to the foreground and before each sync cycle. A response with
`server_epoch >= 1` (or an `X-Server-Epoch >= 1` header seen on any response)
moves the app from .00 to .01. No further request is sent, and sync stops. A
404 from the old server means epoch 0 and leaves the app in .00. No earlier
data ever reaches the new server.

**What is deleted** after confirmation: every legacy artifact in the
inventory in `data-model.md` (Device stores) — among them the local store and
its backups, outbox, drafts, quarantine files, import reports, sync cursor,
recent searches, HTTP caches, the earlier session credential and the iPhone
widget snapshot. Steps run in a fixed order, each idempotent, between a
durable "confirmed" and "done" marker (data-model).

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| .00 waiting for new server | new build, and `/api/meta` returned 404 (old server, epoch 0) or has not answered yet (offline) | The app works normally: existing screens, sync with the old server. Nothing is deleted or asked | (existing) | FR-021, FR-019 |
| .01 confirm fresh start | `server_epoch >= 1` **and** the earlier store holds tasks, waiting changes or drafts | iPhone: full screen. Mac: window-modal sheet. Nothing behind it is reachable. Nothing is deleted yet. Secondary action "Not now", which has initial focus, and destructive action "Delete and continue", which is not the default | Title: "A fresh start". Body: "This version of Brain Buddy starts with an empty workspace." Detail with counts known: "The 12 tasks and 3 waiting changes on this iPhone from the earlier version will be deleted. They can't be recovered." (Mac: "…on this Mac…"). Singular forms are "1 task" and "1 waiting change"; a zero part is dropped ("The 12 tasks on this iPhone…"); if drafts exist, the list ends with "and your drafts". Counts unknown: "The tasks and waiting changes on this iPhone from the earlier version will be deleted. They can't be recovered." Buttons: "Not now", "Delete and continue" | FR-021 |
| .11 not now | "Not now" on .01 | The same screen stays. Earlier data is untouched; no sync, no sign-in, no network. Shown again on next launch | Adds: "Your earlier data is untouched. Brain Buddy can't sync or sign in until you continue." | FR-021 |
| .02 loading (deleting) | "Delete and continue" | The same screen with both buttons disabled; the destructive button reads "Deleting…", shown after 1 s (021 timing); announced once, politely. No network | "Deleting…" | FR-021 |
| .03 signed out after reset | deletion finished | The existing sign-in sheet, unchanged (iPhone: "Sign in or create an account"; Mac: "Sign in to Brain Buddy"). The new server starts empty, so the owner first creates the account with an invite, on the web or iPhone (M-03, D-04); the Mac cannot create accounts (D-05). Cancel leaves the empty account-less workspace | (existing) | FR-021, FR-007 |
| .04 empty (first run) | after sign-in, or Cancel | The existing empty Inbox | iPhone: "Inbox zero" / "Capture anything on your mind with the bar below." Mac: "Inbox is clear" / "Capture new items without classifying them first." (existing) | FR-021 |
| .05 error | deletion could not complete (disk error, locked file) | Blocking message; sync and sign-in stay off so no earlier data can be sent | "Brain Buddy couldn't finish deleting the earlier data." / "Nothing was sent. Try again, or restart your iPhone and open Brain Buddy again." (Mac: "…your Mac…") Button: "Try again". No reference ID: no server request was made | FR-021 |
| .06 interrupted | app quit or killed | After confirmation, the next launch resumes the deletion **without asking again**; it is recorded as done only after every part is gone. Before confirmation, nothing was deleted and .01 is shown again | — | FR-021 |
| .07 offline | no network | At launch the epoch is unknown, so the app stays in .00. After confirmation, deletion needs no network; the existing sign-in sheet then shows its existing offline line. That line, "Your local tasks are kept", refers to tasks created since the fresh start | iPhone: "Your local tasks are kept. Connect to the internet to sign in." Mac: "Can't reach the server. Check your connection." (existing) | FR-021 |
| .08 fresh install or nothing to lose | `server_epoch >= 1` and the earlier store holds **no** tasks, waiting changes or drafts (including a fresh install with no earlier store) | .01 is skipped. Leftover files and the old session are removed without asking, because nothing the person wrote is lost (owner-approved). Then .03 | — | FR-021 |
| .09 empty (filtered) | N/A | — | — | — |
| .10 partial failure | some steps done when an error or kill happens | Deletion is not atomic across files, Keychain, settings and the App Group; the app stays blocked (.05 or resume via .06) until every step is done, and never starts sync before | — | FR-021 |

### D-04 / M-03 — Invite step for a new identity (web, iPhone)

**Trigger.** The server answers the completion of email-code, Apple or Google
sign-in with code `INVITE_REQUIRED` when the identity has no account
(`contracts/invite-handoff.md`). The answer carries an opaque, single-use,
short-lived pending handoff. (The CLI browser grant, ADR-0029, only binds an
existing browser session and never creates an account.) Nothing has
been created yet. The client shows this step and resubmits the handoff
together with the invite code. Password signup is unchanged: it keeps its
existing "Invite code" field on the signup page (web), and this step never
appears for it. D-05 (Mac) is not applicable; see the screen inventory.

Copy follows the existing auth surfaces. The field label "Invite code" is
reused from `SignupPage.tsx` (monospace, autocomplete off). Web auth errors use
the existing `Reference: …` suffix (`authOperation.ts`); iPhone uses
"Reference ID: …".

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| .01 default | `INVITE_REQUIRED` | The existing sign-in card (web) or sheet (iPhone) shows a heading, one line of explanation, the "Invite code" field, "Continue" (primary) and "Cancel" | Heading: "Enter your invite code". Body: "Brain Buddy is invite-only. No account uses this sign-in yet. Enter your invite code to create one." Field: "Invite code". Buttons: "Continue", "Cancel" | FR-007 |
| .02 submitting | Continue | Continue shows the existing busy label; the field is read-only. Web: the existing `Spinner` appears only after **300 ms**. iPhone: the existing busy indicator | Web: "Please wait…" (existing). iPhone: existing busy state | FR-007 |
| .03 invalid or used code | server rejects the code | Inline error under the field (web `role="alert"`); the code stays in the field; focus returns to the field. Invalid and used codes get the same wording, so the reply does not reveal which codes exist | "That invite code isn't valid or has already been used. Check it and try again." + web " Reference: …" / iPhone "Reference ID: …" | FR-007, FR-016 |
| .04 handoff expired | pending handoff expired or already used | Field and Continue hidden; one action back to the start. Nothing was created; the invite is not consumed | "This sign-in has expired. Start again to create your account." Button: "Back to sign in" (existing label) | FR-007 |
| .05 offline | no network on Continue | Existing network error; code kept; Continue available again. If the handoff expires meanwhile, the next attempt shows .04 | Web: existing network error + " Reference: …" if any. iPhone: "Your local tasks are kept. Connect to the internet to sign in." (existing) | FR-007 |
| .06 existing account | identity already has an account | No invite step; sign-in completes as today | (existing) | FR-007 |
| .07 too many attempts | server rate-limits invite attempts | Inline error; Continue disabled until retry is allowed | "Too many requests. Try again in a few minutes." (existing iPhone wording, reused on web) | FR-007 |
| .08 update required | 426 at completion | D-02.04 on web, M-01.04 on iPhone | (see those states) | FR-018 |
| .09 empty (filtered) | N/A | — | — | — |
| .10 partial failure | N/A by contract | The account and the invite consumption happen together or not at all; a failure leaves no account and the code unused | — | FR-007 |

## CLI and MCP wording

**CLI** (`bb`): the existing JSON error envelope on stderr (`cli/src/error.rs`),
new code `update_required`:

```
{"error":{"code":"update_required","message":"This version of bb is out of date. Install the latest release, then try again. Nothing in your account was changed.","http_status":426,"reference_id":"<correlation id>"}}
```

Exit code **12** (11 is already used for authorization denied, expired or
consumed), per `contracts/release-epoch.md`.

**Pre-cutover CLI builds** send no epoch header. By owner decision they show
their existing generic "Server rejected the request." and exit 2, with nothing
written.

**MCP**: the old path `/api/mcp/` stays mounted only to refuse. Every
request there (initialize, list, call) gets this text, as a tool result with
`isError: true` for tool calls and as the JSON-RPC error message otherwise. No
tool executes:

```
Brain Buddy refused this request: this MCP address is out of date. Connect to the new Brain Buddy MCP address (/api/mcp/v2/), then try again. Nothing in your account was changed. Reference ID: <correlation id>
```

## Affordance → requirement map

| screen | affordance | what it does | FR ref |
|---|---|---|---|
| M-01, D-01 | Update app (existing, 026 `.updateApp`) | Opens the platform update route (App Store / TestFlight) | FR-018 |
| M-01, D-01 | Copy reference ID (existing) | Copies the correlation ID only | FR-016 |
| M-01, D-01 | Sync now, disabled with reason (existing) | Prevents any write from the refused build | FR-018 |
| M-01, D-01 | OK on the error alert (existing) | Dismisses; nothing was written | FR-018 |
| D-02 | Persistent alert toast (new variant): Reload | Reloads the page so the current web build loads | FR-018 |
| D-02 | Persistent alert toast: Dismiss / Escape | Hides the toast; nothing else changes; the next refusal shows it again | FR-018 |
| D-02 | Existing sign-in error line, server message | Tells the person to reload; carries `(ref: …)` | FR-018, FR-016 |
| D-04, M-03 | Invite code field + Continue (new step) | Resubmits the pending handoff with the code; creates the account only if the code is valid and unused | FR-007 |
| D-04, M-03 | Cancel (new step) | Abandons the pending handoff; nothing is created; back to sign-in | FR-007 |
| D-04, M-03 | Back to sign in (existing label, state .04) | Restarts sign-in after the handoff expired | FR-007 |
| M-02, D-03 | Delete and continue (new, destructive) | Deletes every legacy artifact in the data-model inventory; then the existing sign-in | FR-021 |
| M-02, D-03 | Not now (new) | Leaves earlier data untouched; the app stays on .01/.11 with no sync, no sign-in and no network; asks again on next launch | FR-021 |
| M-02, D-03 | Try again (new, error state .05 only) | Retries the deletion; sync and sign-in stay off until it succeeds | FR-021 |
| M-02, D-03 | Existing sign-in sheet and its Cancel | Presented after the deletion; Cancel stays in the empty workspace | FR-007, FR-021 |
| ~~M-02, D-03~~ | ~~Continue~~ | Retired with the first-draft notice | — |

### Requirements with no affordance

FR-018 and FR-021 are covered above. Every other requirement has **no new UI**,
because user-visible behavior is unchanged (FR-005) and the web UI is kept
(FR-020):

- FR-001, FR-002, FR-003, FR-006, FR-010, FR-017, FR-022: server
  implementation, capability inventory, retention, jobs and the port freeze;
  invisible to the person.
- FR-004: the native apps lose the legacy runtime; no runtime selector exists
  to remove from view.
- FR-005, FR-020: the requirement *is* "no UI change".
- FR-011, CRT node validation: the owner decision says the existing
  inspector consent toggle's state is sent with every validation request and
  the server refuses without it, with no new UI. **No such toggle ships
  today.** The CRT inspector, including the consent checkbox, was removed from
  the web app on 2026-09-25 (#236, `e5e94e06`). No shipped web, iPhone, Mac or
  CLI code calls `POST /trees/{id}/validate/{node}`, and the consent checkbox
  survives only in the design-skill UI kit (`ui_kits/workspace/components.jsx`),
  which is pre-pivot reference material. There is therefore no inspector error
  line to design. The server refusal is specified at the API: the existing
  error envelope (400, "Valid provider consent is required", as in
  `backend/app/api/tasks.py`), with `reference_id` and `X-Correlation-ID`, and
  no provider call. If a client ever re-introduces CRT validation, it must
  show that message with its reference in its error line. Owner decision
  recorded in spec.md Clarifications (campaign 2): API-level rule, no UI.
- FR-007: sign-in to an existing account is unchanged; the new invite step is
  mapped above (D-04, M-03).
- FR-008, FR-009, FR-011 (other AI paths), FR-012, FR-013, FR-014, FR-015, FR-016:
  existing owner isolation, account, consent, voice, canvas, A2A,
  admin and correlation-ID surfaces carry over unchanged. FR-016's existing
  reference-ID display is reused by M-01/D-01/D-02.
- FR-019: cutover is an operator procedure; the person sees only its effects,
  which are M-01/D-01/D-02 (old builds) and M-02/D-03 (updated builds).

### Affordances with no requirement

- None. The confirmation (.01, .11) goes beyond FR-021's wording but is
  required by the owner decision and Constitution I and V.

## Primary loop impact

No impact on capture → atomic items → clarify/approve → route or CRT candidate
→ Weekly Review → evidence. The loop's screens and rules are unchanged. Two
one-time edges touch it: a refused older build can still capture locally on
iPhone and Mac but cannot sync until updated (M-01/D-01), and the first
time the updated app sees the new server, it asks before deleting earlier
local data, then starts the loop from an empty Inbox (M-02/D-03 .01 → .04).

## Mobile viability

- **Viewport**: both mocks use the 390 px column and a single-column layout
  below 760 px; text wraps, no fixed widths beyond 390. Not runtime-verified at
  390×851; no rendering was performed.
- **Tap targets**: every control is min 44 px in CSS; native implementation
  must keep 44 pt.
- **Invite step (M-03)**: one field and one primary action fit above the
  keyboard at 390×851; the field uses no auto-capitalisation or
  auto-correction, so a pasted code is not altered.
- **One-handed reach**: Update app is the first full-width action in M-01.
  On M-02.01 both actions are full-width at the bottom; "Not now" is on top,
  and "Delete and continue" is last, so it is not under the resting thumb by
  default.
- **Destructive actions**: "Delete and continue" names what is lost, with
  counts when known ("The 12 tasks and 3 waiting changes on this iPhone from
  the earlier version will be deleted. They can't be recovered."). There is no
  export, because no earlier data may reach the new server and the old server
  is gone. Rose destructive styling; never the default button.

## Keyboard and focus

- **M-01.04 / D-01.04, direct-request alert (existing system alert).**
  - On open: VoiceOver reads the alert title and message first. The initial
    focused control is OK (iPhone: the cancel-role button; Mac: the default
    button, Return).
  - Containment: the alert is modal, and focus stays inside it.
  - Dismissal: OK, or Escape on Mac. Update app also dismisses it and opens the
    platform update route.
  - Afterwards: focus returns to the control that started the refused request.
- **D-01, Mac sync popover.**
  - Opens from the existing sync status control.
  - On open: focus goes to the "Update needed to sync" heading, then Tab order
    Update app → Copy reference ID → Close.
  - Containment: the popover is transient, and Tab cycles inside it while it is
    open.
  - Dismissal: Escape, Close, or a click outside.
  - Afterwards: focus returns to the sync status control.
- **M-01, iPhone Settings › Sync.**
  - A pushed screen. VoiceOver focus goes to the screen title, then the
    heading.
  - Back returns focus to the "Sync" row in Settings.
- **M-02.01 / D-03.01, confirmation.**
  - Containment: full screen on iPhone, and on Mac a window-modal sheet with
    no other reachable controls.
  - On open: VoiceOver announces the screen and reads the title and detail
    first. The initial focused control is **"Not now"**. On Mac, "Not now" is
    the default button (Return) and Escape also means "Not now"; "Delete and
    continue" is never default and needs an explicit activation.
  - VoiceOver: "Delete and continue" is a destructive-role button, label
    "Delete and continue", hint "Deletes 12 tasks and 3 waiting changes from
    the earlier version. This can't be undone." (counts omitted when unknown).
    "Not now" has the hint "Keeps your earlier data. Brain Buddy stays on this
    screen." Counts are read as words.
  - After "Not now": focus stays on "Not now", and the added .11 line is
    announced once.
  - After deletion: focus moves to the existing sign-in sheet's first field.
    After that sheet's Cancel, focus moves to the Inbox heading.
- **M-02.05 / D-03.05, deletion failed.** Focus goes to the heading, then Try
  again. Escape does nothing, because there is no safe state behind it.
- **D-02, web persistent alert toast.**
  - Announcement: `role="alert"`, read once on appearance. It does **not** take
    focus.
  - Keyboard reach: it sits right after the top bar in DOM order, which
    matches its visual position at top centre, so Tab from the top bar reaches
    "Reload" and then "Dismiss".
  - Dismissal: Escape dismisses it when focus is inside the toast, or on the
    page outside any text field or open dialog.
  - After dismissal: if focus was inside the toast, it moves to the top bar's
    first control.
  - "Dismiss" is a text button. If it is drawn as an `X` icon, its accessible
    name is "Dismiss update notice".
- **D-04, web invite step.**
  - On entering the step, focus goes to the "Invite code" field, and the
    heading and explanation are linked to it with `aria-describedby`.
  - Enter submits. Tab order: field → Continue → Cancel.
  - On error (.03, .07): the message is `role="alert"`, linked to the field;
    focus stays on or returns to the field.
  - On .04: focus moves to "Back to sign in".
  - Escape does nothing, because this is a page step, not a dialog.
- **M-03, iPhone invite step.**
  - VoiceOver reads the step heading, then focus lands on the "Invite code"
    field. The return key is "Continue". The field uses no auto-capitalisation
    or auto-correction.
  - On error: the error row is announced once and focus returns to the field.
  - On .04: focus moves to "Back to sign in".
  - The existing toolbar Cancel abandons the handoff.
- **Accessible names**: no icon-only controls. "Copy reference ID" has a text
  label.
- **State communicated by color alone**: none. The refusal and the destructive
  action are always worded; rose styling is reinforcement only.

## Design authority

- Tokens, colors and type follow the `brain-buddy-design` skill and the 026
  native mock style (system font on native surfaces, slate/sky, amber warning,
  double-ring focus, flat slate-50 background, 8 px buttons, 20 px panels).
- Existing copy is reused verbatim from `RuntimeIssuePresentation.swift`,
  `EmptyStateView`/`TaskListScreen.swift`, `ContentView.swift` (Mac Inbox),
  `SignInFlow.swift` (Mac), `SignInSheet.swift` (iPhone) and the web
  `utils/error.ts` `(ref: …)` format.
- Vocabulary check (ADR-0006): pass, see the verification run in the hand-off.
- `python3 -m unittest scripts/test_validate_brain_buddy_design_skill.py`: see
  the verification run in the hand-off.

## Owner decisions (2026-10-14)

The owner approved this design for planning on 2026-10-14 with these decisions,
revised the same day after spec review campaign 1:

1. **Confirm before the fresh-start deletion (FR-021; Constitution I and V).**
   This supersedes the earlier silent reset, which superseded the first-draft
   notice.
   - M-02/D-03 .01 is re-activated as "Confirm fresh start". It is shown only
     when earlier tasks, waiting changes or drafts exist; a fresh install skips
     it (.08).
   - Deletion starts only after "Delete and continue".
   - "Not now" leaves the data untouched, keeps the app on that screen with no
     sync, sign-in or network, and asks again on next launch.
   - An interrupted deletion after confirmation resumes without asking again.
2. **Imprecise refusal at cutover accepted.** At this one cutover, older builds
   show the shipped 026 copy "Your saved tasks and waiting changes stay on this
   device", and the updated app then asks to delete that data. No extra
   pre-cutover build is shipped. New builds no longer make that promise
   (M-01.01).
3. **Reset activation by server epoch.** The fresh start triggers only when the
   app's server reports the new release epoch, not because the build changed. A
   build that lands before cutover deletes nothing (.00).
4. **Release epoch header.** The epoch is a dedicated integer header,
   `X-Client-Epoch`, sent by every first-party client of this release; old
   builds don't send it. Detection does not use the version string. The
   refusal clears when the app is updated or a later request succeeds.
5. **Epoch signal from server to client (campaign 2).** `GET /api/meta`
   (unauthenticated, exempt) returns `{ "server_epoch": n, "min_client_epoch": n }`,
   and every response carries `X-Server-Epoch`. Native apps call `/api/meta`
   before any sign-in or sync, and `server_epoch >= 1` drives M-02/D-03
   .00 → .01.
6. **Invite for every new account (FR-007, campaign 2).** Every
   account-creation method needs an invite. A new identity gets the invite step
   (D-04 web, M-03 iPhone; D-05 Mac not applicable). Password signup keeps its
   existing field.
7. **CLI (campaign 2).** Updated builds exit with code 12 on update required.
   Old CLI builds show the generic "Server rejected the request." and exit 2,
   with nothing written; accepted.
8. **CRT AI validation consent (campaign 2).** The consent state is sent with
   every validation request and the server refuses without it, with no new UI.
   See the FR-011 note: the inspector toggle this decision assumes was removed
   on 2026-09-25, so only the API refusal is specified.
9. **Remaining detection details stay with `/speckit-plan`.** This covers the
   web and CLI header plumbing and how third-party MCP clients are versioned.
   Older builds still on the legacy runtime show the HTTP-path alert (M-01 .04)
   with the server message, not the sync-row state (.01).

## Open decisions for the human

- None. (FR-011 / decision 8 was settled in spec.md Clarifications: CRT
  consent is an API-level rule with no UI.)
- Item 9 above is open for the plan.
