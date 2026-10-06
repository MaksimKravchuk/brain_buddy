# Design: Weekly Review

**Feature**: `specs/020-weekly-review/`
**Spec**: `spec.md` (Clarifications settled: 2026-10-05)
**Screens**: `design/*.html` — self-contained static HTML, inline CSS, inline SVG icons, no CDN, no external fonts, no script
**Human sign-off**: approved by Max on 2026-10-05, with decisions 1–6 (see Sign-off)
**Amended**: 2026-10-06, after planning-review campaign 1 — owner decisions PD-1 – PD-3 (spec Clarifications "Session 2026-10-06") and the review's design findings; see "Amendments 2026-10-06". Sign-off decisions 1–6 are unchanged.

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

This feature has a user-visible surface on iOS (primary, iPhone 390 × 851) and
web (desktop, plus the narrow 390 × 851 layout of the existing responsive web
app, stated per D- screen as a "narrow (390 px)" state), designed below. iOS
screens are `M-` ids; web screens are `D-` ids. Where the web shows the same content as an iOS screen in a different
container (review steps, forms, AI states), the web acceptance cites the `D-`
container together with the `M-` content id; this is stated per screen.

**macOS (US6, FR-041)** has no separate mockups. After Mac↔backend sync exists,
the Mac follows these designs: markers as D-01, the decision card as D-02, the
review as D-03 with the Mac's existing one-item-at-a-time review layout
(`macos/Sources/BrainBuddyMac/ContentView.swift` Waiting/Someday review) for
M-18 and M-20, and the on-device navigator states of M-05/M-06. Until Mac sync
exists, the Mac shows a **non-interactive "Weekly review · coming later" row**
in its sidebar (the same pattern as today's iOS `DeferredRow`) and ships no
local-only review. Note: the Mac app has no such row today, only the POC
"Review Waiting for" / "Review Someday" buttons, so adding it is a small Mac
change the plan must schedule (see Notes for the plan).

### Example data used in every mockup

Today is Fri 9 Oct 2026, 16:02 local. Threshold 14 days (auto-park at 21).
Review slot Friday 16:00. Last review Wed 30 Sep ("9 days ago"). Provider name
"OpenAI" and model size "1.1 GB" are **illustrative**: the cloud provider and
the downloadable model are planning decisions (spec Assumptions).

### Entry order of the review

At the first app open (iOS) or web open after the feature is switched on, before
anything else: the auto-park explainer M-26 / D-05 (once per owner, FR-051).

Entry (M-11 row, D-01 sidebar link, M-25 notification, or the M-24 widget chip) →
onboarding M-12 (first time only) → While you were away M-09 (only if unseen parks
exist) → restart mode M-10 (only if no counted review for 21+ days) → resume or
mode picker M-11 → steps M-13 … M-22. The widget chip follows the same order and
then lands on the decision step M-16 instead of the mode picker (M-24 "chip
tapped").

## Screen inventory

| id | surface | screen | purpose | FR refs |
|---|---|---|---|---|
| M-01 | mobile (iOS Next tab) | Next actions with age markers | Shows "asks for a decision" and "moves to Someday tomorrow" per task (ageing is detail-only); the marker opens the card as a sheet | FR-046, FR-004, FR-010, FR-012, FR-038, FR-039, FR-040 |
| M-02 | mobile (iOS task detail) | "This wording" section in task detail | States formulation age in words, including the ageing marker (shown only here), the due-date pause, extension and park facts; "Decide" from the task on any day | FR-001, FR-003, FR-046, FR-004, FR-009, FR-010, FR-012 |
| M-03 | mobile (iOS large-detent sheet over Next, decided) | Decision card | One task, one decision: seven decisions, optional stall reason with a recommendation, third-stall offer, stale handling, Undo toast after a decision | FR-005, FR-006, FR-007, FR-009, FR-010, FR-011, FR-040, FR-045 |
| M-04 | mobile (inside M-03) | Decision card follow-up forms | Reformulate, find a first step ("Was: …"), Waiting for (who/what), keep 7 more days (reason required) | FR-001, FR-002, FR-006, FR-008, FR-009, FR-019 |
| M-05 | mobile (inside M-04) | AI navigator, on-device | 1–3 proposals from Apple's on-device model; pick fills, confirm writes; clarifying question; offline | FR-019, FR-020, FR-021, FR-022 |
| M-06 | mobile (inside M-04) | On-device model unavailable: choice and download | Says why; offers downloadable on-device model (size shown) or cloud; download progress, interruption, storage | FR-023, FR-049 |
| M-07 | mobile (inside M-04) | Cloud consent and cloud failures | One-time consent naming provider and exact data; revoked re-consent; timeout/cap/offline with correlation ID | FR-024, FR-025, FR-045 |
| M-08 | mobile (iOS project screen) | Project without a next action — AI first next action | Proposes a first next action and creates it in Next on confirm | FR-019, FR-020, FR-021 |
| M-09 | mobile (sheet / first review screen) | While you were away | Lists unseen auto-parked tasks; one-tap return each; return all | FR-012, FR-015 |
| M-10 | mobile (review cover) | Restart mode | After 21+ days without a review: neutral welcome, one reversible bulk release of Next tasks older than 4 weeks | FR-017, FR-038 |
| M-11 | mobile (Lists hub + review cover) | Review entry, mode picker, resume | Replaces the deferred row; quick/full choice; resume an open review from any device | FR-027, FR-028, FR-029, FR-038, FR-042 |
| M-12 | mobile (review cover) | Onboarding | Why, threshold rule, auto-park; collects day/time (Fri 16:00) and threshold (7/14/21/28, 14) | FR-016, FR-018, FR-035, FR-036 |
| M-13 | mobile (review step) | Wins of the week (+ shared step chrome, leave) | First step, before any backlog: completed tasks and their count | FR-028, FR-029 |
| M-14 | mobile (review step, full) | Mind sweep | Capture anything on the mind into Inbox | FR-028, FR-029 |
| M-15 | mobile (review step) | Inbox to zero | ">15 items" choice; one item at a time via Process inbox | FR-028, FR-030, FR-034 |
| M-16 | mobile (review step) | Tasks that ask for a decision | The M-03 card one at a time, oldest first; "Not now" passes a card; Undo after each decision | FR-028, FR-034, FR-050, FR-006 |
| M-17 | mobile (review step, full) | The rest of Next with capacity mirror | Count, 4-week weekly average, implied weeks; no limit | FR-028, FR-031 |
| M-18 | mobile (review step, full) | Waiting for, older than 7 days | One at a time: keep waiting / follow-up / return to Next / cancel | FR-028, FR-032, FR-034 |
| M-19 | mobile (review step, full) | Projects without a next action | Add or suggest a next action per project | FR-019, FR-028 |
| M-20 | mobile (review step, full) | Someday pass | Max 7 items not reviewed in 30 days; keep / move to Next with a concrete title / cancel | FR-028, FR-032, FR-034 |
| M-21 | mobile (review step, full) | Dates in the next 14 days | Read-only look ahead | FR-028 |
| M-22 | mobile (review step) | Summary | Counts per decision type, next review date, optional "Clear how to start the week?" | FR-033, FR-038, SC-003, SC-007 |
| M-23 | mobile (iOS Settings) | Weekly review and Suggestions settings | Day, time, threshold, last review; on-device status, fallback choice, delete model, cloud consent revoke | FR-023, FR-049, FR-024, FR-035, FR-038, FR-039 |
| M-24 | mobile (iOS widget) | Next actions widget with "N ask" | Shows how many tasks ask for a decision; in medium and large the chip deep-links into the review's decision step | FR-037 |
| M-25 | mobile (iOS notification) | Weekly review notification | The single weekly cue, skipped if a complete or partial review happened in the preceding 6 days; iOS only | FR-036, FR-038 |
| M-26 | mobile (iOS sheet at first app open) | Auto-park explainer | One-time, short: the threshold rule, auto-park 7 days later, one-tap return, the only automatic change, the grace date for tasks already in Next; independent of the onboarding | FR-051, FR-016, FR-018, FR-014 |
| D-01 | desktop (web) | Next actions with age markers + Weekly review sidebar entry | Web markers (as M-01, no ageing in the list) and the working entry replacing "Coming soon"; the sidebar "Last review" line is the web's only review cue | FR-046, FR-004, FR-010, FR-012, FR-038, FR-039, FR-042, FR-045 |
| D-02 | desktop (web dialog) | Decision dialog with the AI navigator | M-03/M-04/M-05/M-07 content in a 560 px dialog; cloud-only navigator | FR-005 – FR-011, FR-019 – FR-021, FR-024, FR-025, FR-045 |
| D-03 | desktop (web route) | Weekly review shell | Focused route with step rail; hosts M-09 … M-22 content; onboarding dialog | FR-015, FR-017, FR-027 – FR-035, FR-045 |
| D-04 | desktop (web settings) | Weekly review and Suggestions settings | M-23 minus on-device rows | FR-024, FR-035, FR-038, FR-039, FR-045 |
| D-05 | desktop (web dialog at first web open) | Auto-park explainer | M-26 content as a dialog; once per owner across devices | FR-051, FR-016, FR-018, FR-014 |

Files:

| file | screens |
|---|---|
| `design/M-01-next-list-markers.html` | M-01 |
| `design/M-02-task-detail-formulation.html` | M-02 |
| `design/M-03-decision-card.html` | M-03 |
| `design/M-04-decision-forms.html` | M-04 |
| `design/M-05-ai-navigator.html` | M-05 |
| `design/M-06-ai-model-choice.html` | M-06 |
| `design/M-07-cloud-consent.html` | M-07 |
| `design/M-08-project-first-action.html` | M-08 |
| `design/M-09-while-you-were-away.html` | M-09 |
| `design/M-10-restart-mode.html` | M-10 |
| `design/M-11-review-entry.html` | M-11 |
| `design/M-12-onboarding.html` | M-12 |
| `design/M-13-review-get-clear.html` | M-13, M-14, M-15, shared step chrome |
| `design/M-16-review-decisions.html` | M-16 |
| `design/M-17-review-get-current.html` | M-17, M-18, M-19, M-20, M-21 |
| `design/M-22-review-summary.html` | M-22 |
| `design/M-23-settings.html` | M-23 |
| `design/M-24-widget-notification.html` | M-24, M-25 |
| `design/D-01-next-list-markers.html` | D-01 |
| `design/D-02-decision-dialog.html` | D-02 |
| `design/D-03-review-shell.html` | D-03 |
| `design/D-04-settings.html` | D-04 |
| `design/M-26-auto-park-explainer.html` | M-26 |
| `design/D-05-auto-park-explainer.html` | D-05 |

### Marker system (M-01, M-02, D-01, M-17, M-24)

By owner decision 2 (2026-10-05), list surfaces (M-01, D-01, M-17, and the
widget rows) show **only** "asks for a decision" and "moves to Someday
tomorrow". "Ageing" is shown only in task detail: M-02 on iOS, and the same
"This wording" block in the web task's inline detail.

| state | rule (threshold T) | visual | where shown | interactive |
|---|---|---|---|---|
| fresh | age < T/2 | none | — | — |
| ageing | T/2 ≤ age < T | slate-100 chip, slate-600 text, Lucide `Hourglass`, "Ageing" | task detail only (M-02, web inline detail); **never in lists** | no |
| asks for a decision | age ≥ T (or ≥ T+7 after extension) | indigo-50 chip, indigo-200 border, indigo-700 text, `CircleHelp`, "Asks for a decision" | lists and detail | opens the card |
| moves to Someday tomorrow | within 24 h of auto-park | amber-50 / amber-200 / amber-800 (warning semantic, not the reserved needs-you alias), `Archive`, "Moves to Someday tomorrow" | lists and detail | opens the card |
| future due date | due date after today | no age marker; the existing rose due chip only; detail says "Paused until the due date" | — | — |

Rose stays reserved for real due dates and destructive controls. No age state
uses rose, red, an error icon, or the word for a missed deadline (FR-004,
FR-038). Every marker is text plus icon, so colour is never the only signal.

## State inventory

Rows marked **n/a** state why the state cannot occur. "Offline" on iOS means
the app's offline-first behaviour (outbox/replay); on the web, which is not
offline-first, it means the existing "You're offline" recovery pattern with
mutations disabled. Loading placeholders appear after 300 ms and are static
(ambient motion is reserved for brain dump).

### M-01 — Next actions with age markers

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | Next tab open | Rows grouped by project. Only asking and moves-tomorrow rows carry a marker; fresh and ageing rows have none. A future-due task shows only its due chip. Tapping a marker opens the M-03 sheet. | "Asks for a decision", "Moves to Someday tomorrow" | FR-046, FR-004, FR-010, SC-006 |
| loading | cold launch while the local store opens, > 300 ms | Four static placeholder rows; markers arrive with the rows | — | — |
| empty (first run) | no next actions | Today's empty state, nothing about age | "No next actions" / "Process your inbox to choose what comes next." | — |
| empty (filtered to nothing) | Tag/priority filter matches nothing | Different copy, count of hidden tasks, "Clear filter" | "No next actions tagged errands" / "7 next actions are hidden by this filter." | — |
| error | local store unreadable (e.g. before first unlock) | Reason and "Try again"; no correlation ID because nothing reached a server | "We couldn't open your tasks" / "Unlock your iPhone and try again. Nothing was changed." | — |
| partial failure | **n/a** — one local read; markers are computed per task from local data, so there is no per-item failure path | — | — | — |
| offline / interrupted | no connection | Markers keep working from the device clock; sync state in words | "Offline — 2 changes waiting" | FR-040, FR-013 |
| threshold just changed | threshold changed in M-23 | One-time dismissible note; markers already updated | "Your threshold is now 7 days. 4 tasks ask for a decision. Nothing moves to Someday before Fri 16 Oct." | FR-039 |
| not activated | feature on, explainer (M-26) not yet seen | No markers at all; the explainer sheet comes first at app open | — | FR-051 |

### M-02 — Task detail, "This wording" section

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default (asks) | task asks for a decision | Marker, age in days, reassurance, what doesn't restart the clock, "Decide" | "The wording hasn't moved for a while. That's feedback on the wording, not on you. Changing notes, Tags, project or priority doesn't restart the clock." | FR-001, FR-003, FR-010 |
| ageing / fresh | age < T | Ageing: the "Ageing" chip (its only place on iOS) and the date it will ask. Fresh: days only. No Decide. | "Asks for a decision from Wed 14 Oct if the wording stays the same." | FR-004 |
| clock paused | future due date | Paused chip and date | "The clock starts on Fri 16 Oct. Until then this task won't ask for a decision or move to Someday." | FR-046 |
| moves to Someday tomorrow | within 24 h of park | Exact park time; reassurance; Decide | "If nothing is decided, it moves to Someday / maybe on Sat 10 Oct at 09:14. Nothing is lost, and you can bring it back in one tap." | FR-012, SC-006 |
| kept 7 more days | extension used | Reason quoted back; new ask and park dates; no further extension | "Kept on Mon 5 Oct. Asks again on Mon 12 Oct; moves to Someday on Mon 19 Oct if still undecided." | FR-009 |
| parked automatically | task in Someday via auto-park | Parked chip and facts kept | "Moved here on Thu 8 Oct at 09:14, after 21 days in Next without a decision. Project, Tags, notes and due date were kept." | FR-012 |
| parked, project archived | edge case | Instruction to restore the project first | "Its project "Old flat" is archived, so restore the project before moving this back to Next actions." | FR-012, edge case |
| loading | **n/a** — computed synchronously from the local task already on screen | — | — | — |
| empty (first run / filtered) | **n/a** — a task detail always has a task | — | — | — |
| error | **n/a** — no fetch | — | — | — |
| partial failure | **n/a** | — | — | — |
| offline / interrupted | no connection | Identical: computed on the device | — | FR-040 |

### M-03 — Decision card (iOS sheet)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | opened from M-01, M-02 | Title, age, framing line, optional reasons, seven decisions in fixed order | "This wording hasn't moved. That usually means the wording needs work, not you." | FR-006, FR-007, FR-010 |
| reason → recommendation | a reason chip selected | Sky outline + "Recommended" on the mapped decision; all decisions enabled | "Recommended" | FR-007 |
| extension already used | formulation already extended | "Keep 7 more days" absent; quiet reason line | "You've already kept this wording 7 more days once." | FR-009 |
| third stalled wording | 3rd consecutive formulation reached the threshold | Gentle offer above reasons. iOS has no thinking canvas, so on iOS the offer is only "Release to Someday" with the reassurance line; the web adds "Think it through" only when `crt_canvas` is effective (D-02). Nothing blocked | "This is the third wording in a row that has stalled. Sometimes the task isn't the problem…" | FR-005 |
| stale | task changed elsewhere since the card opened | Nothing applied; was/now diff; current state; Close | "This task changed on another device, so nothing was applied. Here's the current version." | FR-011 |
| decision applied, with Undo | any decision confirmed | Sheet closes and the row updates. A toast names the decision and offers Undo for about 5 s, like Process inbox; with VoiceOver or Switch Control running it stays at least 10 s and until focus leaves it, and VoiceOver announces "Released to Someday. Undo available." Undo restores the task exactly, including clock, extension and receipts. | ""Renovate the bathroom" released to Someday" · "Undo" | FR-006, FR-010, FR-048 |
| undo didn't apply | Undo tapped, but the task (or the follow-up it created) changed elsewhere first, or the undo was rejected on sync | The toast turns into a short message; the task stays as it is now; on sync rejection the reason appears in the existing Sync issues screen with Ref and a non-blocking note on Next | "Couldn't undo: "Renovate the bathroom" changed on another device. It's in Someday / maybe now." | FR-048, FR-045 |
| undo window expired | ~5 s pass | Toast fades. The decision stands and is changeable later through ordinary task moves. | — | FR-048 |
| error | offline decision rejected by the server after sync (non-stale) | Reason, correlation ID, "Try again" / "Choose again". Because the sheet is long closed, it appears in the existing iOS Sync issues screen, with a non-blocking note on Next ("1 decision couldn't be saved") that opens it | "Your decision "Move to Waiting for" couldn't be saved to your account. The task is still in Next." + Ref | FR-011, FR-045 |
| error: decision not allowed | the server says the decision no longer fits the task's list | Reason and Ref; the card shows the current list | "This decision isn't available for this task's current list. Nothing was changed." + Ref | FR-011, FR-045 |
| unsaved text — leave? | Close, swipe-down or Back while a form (M-04, M-05 answer) holds unsaved text | Swipe-down is blocked while text is unsaved; a confirmation asks first; "Keep editing" is the default | "Discard your new wording? It hasn't been saved." · "Keep editing" · "Discard" | FR-052 |
| offline / interrupted | no connection; or app killed with the card open | Works offline, queued; killed before a choice → nothing applied; typed text is restored as a draft when the card for the same wording reopens | "Offline. Decisions are saved on this iPhone and sync later." / "Your unsaved wording is back." | FR-040, FR-052 |
| loading | **n/a** on iOS — decisions apply to the local store immediately (web: D-02 saving) | — | — | — |
| empty (first run / filtered) | **n/a** — the card always has one task | — | — | — |
| partial failure | **n/a** — every decision is one atomic task command; "Find a first step" writes title and notes in one command | — | — | FR-008, FR-011 |

### M-04 — Decision card follow-up forms

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default: reformulate | "Reformulate" | Field prefilled with the current wording; Save disabled until changed; "Suggest wording" | "What will you actually do?" / "A new wording starts a fresh clock." | FR-001, FR-006, FR-019 |
| cosmetic edit only | only case/space/punctuation changed | Neutral note before saving; "Save anyway" | "Only capitals or punctuation changed, so this is still the same wording and the clock keeps running." | FR-002 |
| empty: first step | "Find a first step" | Empty field, "Was:" preview, Save disabled | "What's the very first thing you'd do?" / "Was: Renovate the bathroom" | FR-008 |
| first step saved | Save | Detail shows new title, notes begin with "Was: …", 0 days | "Was: Renovate the bathroom" | FR-008, FR-001 |
| Waiting for | "Move to Waiting for…" | Required who/what field (existing prompt) | "Who or what are you waiting for?" | FR-006 |
| keep 7 more days, empty | "Keep 7 more days" | Reason required; button disabled with the reason; dates shown | "Why does this wording still fit?" / "Add a reason to continue" | FR-009 |
| keep 7 more days, ready | reason typed | Button enabled with the new date (NC-1: 7 days from today) | "Keep until Fri 16 Oct" | FR-009 |
| Suggest shows its route | form opens | The Suggest button carries where the suggestion would run, resolved before the tap | "Suggest · on this iPhone" / "Suggest · OpenAI" | FR-022, FR-024 |
| unsaved text — leave? | Back, Close or swipe-down with a changed field (wording, first step incl. an edited proposal, Waiting for, reason) | As M-03 "unsaved text — leave?" | "Discard your new wording? It hasn't been saved." · "Keep editing" · "Discard" | FR-052 |
| draft restored | the form reopens for the same task and wording after it was left with unsaved text (also after an app kill) | Field prefilled with the draft; a quiet line; "Clear" | "Your unsaved text is back." | FR-052 |
| loading | **n/a** on iOS (local); web in D-02 | — | — | — |
| error | as M-03 error | — | — | FR-045 |
| partial failure | **n/a** — single command | — | — | — |
| offline / interrupted | no connection; app killed mid-form | Works offline; a killed form keeps its typed text as a local draft (restored as above); the task is unchanged until Save | — | FR-040, FR-052 |

### M-05 — AI navigator, on-device

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| loading | "Suggest" | Static placeholder lines, "Stop" | "Suggesting on this iPhone…" | FR-022 |
| default: proposals | model returns | 1–3 radio proposals, on-device note, "None of these" | "Suggested on this iPhone. Nothing left the device." | FR-019, FR-022, SC-005 |
| picked, editing | a proposal tapped | Field filled and editable; Save enabled; "Was:" kept | "Pick one to edit" | FR-020 |
| dismissed | "None of these" or "Stop" | Back to the M-04 form, field and task unchanged | — | FR-020 |
| clarifying question | input too thin to ground a step | One question, an answer field, "Add to notes and suggest again", "I'll write my own step" | "What does "things" mean here? Which part of your life or home is this about?" | FR-021 (resolved: answer goes to notes, navigator re-runs) |
| partial failure | some proposals dropped (duplicate of an open task, or malformed) | Fewer than 3 proposals shown, no message | — | FR-019 |
| error | nothing usable returned | Plain reason, "Try again"; no correlation ID (no server) | "No useful suggestion this time. You can try again, or write your own step." | FR-021 |
| offline | airplane mode | Same as default; note says it works offline | "Suggested on this iPhone. Works offline." | FR-022, FR-040 |
| proposals, notes shortened | the shared notes reduction dropped the middle of long notes | Proposals as default, plus one line under the device note | "Part of the notes was not considered." | FR-019 |
| interrupted | app backgrounded or sheet dismissed while "Suggesting…" | The request is cancelled quietly. On return the form shows its earlier state and any proposals that had already arrived | "Suggestion stopped." · "Suggest again" | FR-020, FR-022 |
| unsaved answer — leave? | Back or Close with a typed clarifying answer | As M-03 "unsaved text — leave?"; the answer is kept as a draft | "Discard your answer? It hasn't been added to the notes." · "Keep editing" · "Discard" | FR-052 |
| empty (first run / filtered) | **n/a** — the panel exists only after "Suggest" | — | — | — |

### M-06 — On-device model unavailable: choice and download

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default: choice (language) | Apple's model doesn't support the task's language | Reason; two choices (download with size, cloud); "Not now"; remembered | "Apple's on-device model doesn't support Russian yet." / "Download 1.1 GB" / "Continue with cloud" | FR-023, FR-049 |
| choice (Apple Intelligence off / model not ready) | other unavailability reasons | Same layout, reason line differs | "Apple Intelligence is turned off on this iPhone." / "Apple's model is still getting ready." | FR-023 |
| choice (device can't run models) | unsupported device | Download shown unavailable with reason; cloud and Not now | "Not available on this iPhone." | FR-023 |
| loading: downloading | "Download" | Progress bar in bytes, time estimate, "Cancel download", card stays usable | "420 MB of 1.1 GB · about 3 minutes on Wi-Fi" | FR-049 |
| offline / interrupted | connection lost mid-download | Why, "Retry download" (resumes), cloud alternative | "The connection dropped at 420 MB of 1.1 GB." | FR-049 |
| error: not enough storage | before or during download | Numbers, "Try again", cloud alternative; nothing deleted for the person | "The model needs 1.1 GB. This iPhone has 640 MB free." | FR-049 |
| installed → suggestions | download complete | Proposals in the task's language, on-device note, offline OK | "Suggested on this iPhone by the downloaded model. Works offline." | FR-023 (a), FR-022 |
| cloud unavailable | the server reports cloud suggestions off (`available: false`) | The cloud choice is shown disabled with its reason; download and Not now stay | "Cloud suggestions aren't available right now." | FR-023, FR-025 |
| empty (first run / filtered) | **n/a** | — | — | — |
| partial failure | **n/a** — a download either completes or is resumable | — | — | — |

### M-07 — Cloud consent and cloud failures (iOS)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default: consent | first cloud "Suggest" | Provider named; exact five data items; "Nothing else is sent"; Allow / Not now | "Send task details to OpenAI for suggestions?" | FR-024 |
| consent after revoke | consent revoked in M-23 | Note that nothing was sent since; consent again | "You turned cloud suggestions off on Wed 7 Oct. Nothing has been sent since." | FR-024, US3-6 |
| declined | "Not now" | Form usable; Suggest still available | "Nothing was sent. Write your own step, or ask for suggestions later." | FR-024, US3-5 |
| loading → proposals | allowed | Placeholder, "Stop"; proposals with provider line | "Asking OpenAI…" / "Suggested by OpenAI from this task's details." | FR-019, FR-020 |
| error: timeout / provider / malformed | provider fails | Reason, correlation ID, "Try again" | "OpenAI didn't answer in time. You can try again or write your own step." + Ref | FR-025, FR-045 |
| error: cost cap | existing cap reached | Reason, correlation ID, no retry | "Cloud suggestions have reached their usage limit for now. Everything else works as usual." + Ref | FR-025, FR-045 |
| offline | no connection | No request attempted; form usable | "You're offline. Cloud suggestions need a connection…" | FR-025, FR-040 |
| no account | account-less iOS | Cloud unavailable, on-device still offered | "Cloud suggestions need a Brain Buddy account. Suggestions on this iPhone don't." | edge case |
| consent text changed | a stored consent was for an earlier list of data or another provider | The consent screen again, with a line saying what changed | "What we send has changed, so we're asking again." | FR-024 |
| proposals, notes shortened | as M-05 | Provider line plus the shortened-notes line | "Suggested by OpenAI from this task's details. Part of the notes was not considered." | FR-019 |
| error: input too large | notes and project still too long after shortening (server 400 `navigator_input_too_large`) | Reason, Ref, no retry; the form stays usable | "These notes are too long for suggestions. Write your own step, or shorten the notes and try again." + Ref | FR-019, FR-045 |
| interrupted | app backgrounded or sheet dismissed while "Asking OpenAI…"; or connection lost mid-request | Backgrounding or dismissal cancels quietly ("Suggestion stopped." · "Suggest again"); a lost connection shows the timeout copy with Ref | as M-07 timeout | FR-025, FR-045 |
| empty (first run / filtered) | **n/a** | — | — | — |
| partial failure | as M-05 partial (fewer proposals) | — | — | FR-019 |

### M-08 — Project without a next action

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | project has no Next task | Existing status row + "Suggest a next action" | "This project needs a next action" | FR-019 |
| loading | Suggest | Inline placeholders, "Stop" | "Suggesting on this iPhone…" | FR-022 |
| proposals → picked | model returns | Field + radios + provider/device line + "Add to Next actions" | "Add to Next actions" | FR-019, FR-020, US3-8 |
| created | confirm | Task in Next in this project; status row gone; toast | "Added to Next actions in Garden" | US3-8 |
| empty (first run) | project with no open tasks | One question; the answer is typed straight in as the next action | "What's the first thing you'd need to find out or decide for "Move abroad"?" | FR-021 |
| empty (filtered to nothing) | **n/a** | — | — | — |
| error | cloud failure | Reason, Ref, Try again | "OpenAI couldn't be reached. Try again, or add a next action yourself." | FR-025, FR-045 |
| partial failure | as M-05 | — | — | FR-019 |
| offline / interrupted | no connection; app backgrounded mid-suggestion | On-device as M-05 offline; cloud as M-07 offline; mid-suggestion as M-05 / M-07 "interrupted"; a typed next action is kept as a draft (FR-052) | — | FR-022, FR-040, FR-052 |
| route caption | block shown | "Suggest" carries its route before the tap | "Suggest · on this iPhone" / "Suggest · OpenAI" | FR-022, FR-024 |

The web has no project-screen equivalent of M-08 in this feature: on the web, "a
first next action for a project without one" (US3-8) is offered only in the full
review's projects step (D-03 hosting M-19). A web project-page entry is out of scope.

### M-09 — While you were away

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | unseen auto-parked tasks at app open or review open | Sheet listing each with park date and project; per-row "Return to Next"; "Return all N"; "Continue" | "These 4 tasks stayed undecided, so they moved to Someday / maybe to keep Next honest. Nothing was deleted." | FR-015, SC-006 |
| one returned | row button | Row confirms in words; "Return the other 3" | "Back in Next with a fresh start" | FR-015, US2-4 |
| all returned | Return all | All rows confirm; one status line | "All 4 are back in Next with a fresh start." | FR-015 |
| partial failure: archived project | Return all with an archived-project task | That row disabled with reason; summary names it | ""Return the old router" stayed in Someday because its project "Old flat" is archived." | FR-015, edge case |
| partial failure: changed elsewhere | a return rejected as stale | Named; row shows current state | ""Update the CV" changed on another device, so it was left as it is there." | FR-011, FR-015 |
| empty | no unseen parks | Screen not shown at all | — | FR-015 |
| loading | **n/a** on iOS (local); web in D-03 | — | — | — |
| error | **n/a** on iOS beyond the partial cases; web in D-03 | — | — | — |
| offline / interrupted | parked locally while offline; app closed before Continue | Works locally; shows again next time with the same tasks | "Offline. Changes are saved on this iPhone and sync later." | FR-014, FR-040 |
| closed without Continue | swipe-down or Close | Means "not acknowledged": the parks stay unseen, and the sheet appears again at the next app open, but at most once per calendar day; it always appears as the first screen of the next review | — | FR-015 |
| more parks waiting (account-less) | more than 10 parks were due at once (device safety valve) | Lists the 10 applied; after Continue the next batch is applied and shown | "These 10 tasks moved to Someday / maybe… More will follow after you continue." | FR-012, FR-014 |

### M-10 — Restart mode

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | no complete/partial review for 21+ days | Neutral welcome; count; Release / Keep; "See which ones" | "Your last review was 26 days ago. Gaps happen. Let's make Next fit the week ahead." | FR-017, FR-038 |
| list expanded | "See which ones" | Read-only titles with age | "17 next actions are older than 4 weeks" | FR-017 |
| released | Release | Confirmation, new Next count, and Undo, which lasts until the person moves on ("Start the review" or Close; owner default, FR-017) | "17 tasks released to Someday / maybe. Next now holds 12 tasks." | FR-017, US2-7 |
| set up but never reviewed | onboarded 21+ days ago, no review yet | Same offer; heading without "Welcome back" or any wording implying the person was away | "Your first review / Let's make Next fit the week ahead." | FR-017, FR-038 |
| undone | Undo | Every released task is back in Next with its own clock (same wording, same age, same extension), from the bulk-release snapshot | "Undone. All 17 are back in Next as they were." | FR-017 |
| undone, some skipped | Undo, but some released tasks changed elsewhere meanwhile | The others are restored; the changed ones are named and stay where they are | "15 are back in Next. 2 changed on another device and stayed in Someday / maybe." | FR-017, FR-011 |
| released, resumed after interruption | app killed or backgrounded after Release, before moving on | The review reopens on the released state, Undo still offered | "17 tasks were released to Someday / maybe." · "Undo the 17" · "Start the review" | FR-017 |
| partial failure | some tasks changed elsewhere meanwhile | Named; Undo covers only the released | "2 tasks changed on another device in the meantime, so they stayed in Next…" | FR-011, FR-017 |
| empty | nothing older than 4 weeks | Welcome without an offer | "Nothing in Next is older than 4 weeks, so let's go straight in." | FR-017 |
| offline / interrupted | offline; app closed after release | Applies locally and syncs later; after a kill, see "released, resumed after interruption" | "Offline. Changes are saved on this iPhone and sync later." | FR-040 |
| loading / error | **n/a** on iOS (local); web in D-03 | — | — | — |
| empty (filtered) | **n/a** | — | — | — |

### M-11 — Review entry, mode picker and resume

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default: Lists row | Lists tab | Working "Weekly review" row in its own section, neutral recap | "Last review: 9 days ago" | FR-038, FR-042 |
| empty (first run): Lists row | never reviewed | Setup prompt instead of days | "Set up in a minute" | FR-035 |
| mode picker | row tapped / notification | Quick (~5) and Full (~20) with contents | "How much time do you have?" | FR-027, FR-028 |
| resume | open review on any device | Resume card with step, origin, decisions so far; "Start a new review" | "Full review · step 4 of 10 / Started today at 12:40 on the web. 6 decisions made so far." | FR-029, US4-7 |
| loading | checking the account for an open review | Placeholders; falls back to offline after 5 s | "Checking for a review in progress…" | — |
| offline | no connection | Can review now; cross-device resume deferred | "Offline. You can review now and it syncs later. A review started on another device can be continued once you're back online." | FR-040 |
| offline review replaced another | a review started offline here synced while another device had one open | The other device's review is closed as partial (decisions kept); this one continues; the resume card on the other device says so | "Your review on the web was closed when this one synced. Its 6 decisions are kept." | FR-029, SC-007 |
| error | server check failed | Ref, Try again; can still start | "We couldn't check for a review in progress on your other devices." | FR-045 |
| empty (filtered) | **n/a** | — | — | — |
| partial failure | **n/a** | — | — | — |

### M-12 — Onboarding

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | first review open | Three points; Day/Time rows; threshold segmented; Continue. The auto-park point repeats M-26 briefly with the grace date from the activation moment | "A weekly reset" / "It's the only thing the app moves on its own. Tasks you had when you first saw this rule won't move before Fri 23 Oct." (explainer first seen today, Fri 9 Oct) | FR-016, FR-018, FR-035, FR-051 |
| values changed | edits | Rule text follows the chosen threshold | "If a next action keeps the same wording for 7 days, it asks for a decision." | FR-035 |
| day picker | Day row | Standard list sheet | "Review day" | FR-035 |
| notifications not allowed | iOS permission declined after Continue | Settings saved; no nagging | "Notifications are off for Brain Buddy, so there won't be a reminder on Friday. The review is always in Lists." | FR-036 |
| offline / interrupted | no connection; closed before Continue | Saved locally; closed → shows again next time | "Offline. Your choices are saved on this iPhone and sync later." | FR-040 |
| error | account rejected settings | Kept on device, retried, Ref | "Your review settings couldn't be saved to your account yet." | FR-045 |
| loading / empty / partial | **n/a** — single local form | — | — | — |

### M-13 — Wins of the week (and shared step chrome)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | review starts | Count and list of tasks completed in the last 7 days; first step, before any backlog | "This week you finished 12 things" | FR-028, US4-1 |
| empty | nothing completed | Kind line, no "0" | "A quiet week… Taking a few minutes now is how next week gets easier." | FR-028 |
| leave (interrupted), all steps | "Leave", app kill, call, device switch | Sheet: progress kept, resume anywhere | "Take a break? Everything you've done is kept. Continue from step 4 any time, on any device." | FR-029, US4-7, US4-8 |
| leave with unsaved text, all steps | "Leave", "Skip" or "Next" while a field in the step holds unsaved text (M-14 line, M-18 follow-up or return title, M-20 concrete title, an M-16 card form) | The M-03 "unsaved text — leave?" confirmation comes first; the text is kept as a draft for that item | "Discard what you typed? It hasn't been saved." · "Keep editing" · "Discard" | FR-052 |
| skipped, all steps | "Skip" | Next step; rail/progress shows the step as skipped | — | FR-029 |
| review ended elsewhere, all steps | this device returns to a review that another device finished or replaced | A full-width notice instead of the step; nothing made here is lost | "This review was finished or replaced on your iPhone. Decisions you made here are kept." · "Open the review" | FR-029, SC-007 |
| review moved on elsewhere, all steps | the merged session's current step differs from this device's (another device continued) | Jumps to the merged step with a one-line note | "You continued this review on the web, so it's at step 6 now." | FR-029, US4-7 |
| VoiceOver focus, all steps | step change; or a decision in M-16, M-18, M-20 | Focus moves to the step title on every step change, and to the next item's title after each decision | — | FR-034 |
| offline | no connection | Identical (local) | — | FR-040 |
| loading / error / partial / filtered | **n/a** — local read-only list | — | — | — |

### M-14 — Mind sweep (full)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | step opens | Prompts, one-line capture to Inbox, list added this step | "What's on your mind? Get it out of your head. Don't sort it yet." | FR-028 |
| empty | nothing captured yet | Same screen with an empty list; "Next" finishes the step | — | FR-028, FR-029 |
| unsaved line | a typed line not yet added when the person taps Next, Skip or Leave | As M-13 "leave with unsaved text"; after an app kill the line is back in the field | ""call the plumber" isn't in your Inbox yet." · "Keep editing" (default) · "Discard" | FR-052 |
| offline | no connection | Captures go to the local Inbox | — | FR-040 |
| loading / error / partial / filtered | **n/a** | — | — | — |

### M-15 — Inbox to zero

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| > 15 items | Inbox > 15 | Three choices. The third processes 10 now, then releases the remainder to Someday (owner default). | "Process 10 now" / "Process all 23" / "Process 10, release the rest to Someday" | FR-030, US4-2 |
| default: one at a time | processing | Existing Process inbox item view with its existing Undo toast | "Item 3 of 10" / "Is it actionable? Choose where it belongs." | FR-034 |
| empty | Inbox empty | Finishes as a step with nothing to decide | "Inbox is empty / Nothing to process." | FR-029 |
| done (with release) | queue finished | Processed and released counts, with Undo for the release until the step is left (as M-10) | "10 items processed · 12 released to Someday / maybe" · "Undo the release" | FR-030 |
| undo of one item | Undo in the existing Process inbox toast | The item returns to Inbox and becomes current again; "Inbox processed" goes down by one | (existing Process inbox copy) | FR-048 |
| partial failure | an item changed elsewhere | Named; stays in Inbox | ""Buy printer paper" was changed on another device, so it stayed in Inbox." | FR-011 |
| offline | no connection | Works locally | — | FR-040 |
| loading / error / filtered | **n/a** (local) | — | — | — |

### M-16 — Tasks that ask for a decision (step)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | step opens, or the widget's "N ask" chip is tapped | M-03 card full-screen, "1 of 5 · oldest first", "Not now". The queue holds every task that asks for a decision, including moves-tomorrow ones, earliest-asking first (FR-004) | — | FR-034, US4-3, FR-037 |
| next card, with Undo | a decision made | One status line with Undo (~5 s; with VoiceOver at least 10 s, announced), then the next card. Undo reverts the task and brings its card back as current. | ""Update the CV" released to Someday" · "Undo" | FR-034, FR-048 |
| undo didn't apply | Undo after the task changed elsewhere | As M-03 "undo didn't apply"; the next card stays | as M-03 | FR-048 |
| all decided | queue empty | Count | "All 5 decided / Nothing in Next is waiting for a decision now." | SC-002 |
| some left | "Not now" used | Neutral count. Those tasks keep asking and auto-park continues on schedule. This review is excluded from the SC-002 measurement. | "3 of 5 decided / 2 still ask for a decision. They stay in Next whenever you're ready, and move to Someday on their usual date if nothing is decided." | FR-050, SC-002 |
| empty | nothing asks | Finishes with nothing to decide | "Nothing asks for a decision" | FR-029 |
| threshold changed mid-review | change on another device | Queue unchanged; note | "Your threshold changed to 21 days. This list stays as it is…" | FR-039, edge case |
| stale | a card's task changed elsewhere | M-03 stale pattern in place | — | FR-011 |
| offline | no connection | Works locally | — | FR-040 |
| loading / error / filtered | **n/a** (local) | — | — | — |

### M-17 — The rest of Next with capacity mirror

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | step opens | Three figures, the "no limit" line, and a scannable list with the list markers only (no ageing) | "41 next actions · 9 done per week, last 4 weeks · ~4½ weeks of work at that pace / No limit. Just a mirror…" | FR-031, US4-4 |
| empty (first run) | < 4 weeks of history or no completions | Count only + honest line | "After a few weeks of finished tasks, this will also show your weekly pace…" | FR-031 |
| empty (Next empty) | no next actions | Count 0, no average | "Next is empty." | FR-031 |
| offline | no connection | Identical (local) | — | FR-040 |
| loading / error / partial / filtered | **n/a** (local) | — | — | — |

### M-18 — Waiting for, older than 7 days

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | step opens | One item: who/what, since; four decisions | "Keep waiting · Checks in again in 7 days" | FR-032, FR-034, US4-5 |
| follow-up | "Create a follow-up" | Required field; creates a Next action in the same project; original keeps a 7-day receipt | "What will you do to follow up?" | US4-5 |
| return to Next | "Return to Next" | Editable prefilled title | "What's the next action now?" | US4-5 |
| next item, with Undo | any Waiting decision applied | Status line with Undo (~5 s) above the next item | ""Pick up the drill from Sam" moved to Next actions" · "Undo" | FR-048 |
| undo didn't apply | Undo after the task, or the follow-up it created, changed elsewhere | As M-03 "undo didn't apply" | "Couldn't undo: the follow-up "Text Sam about the drill" changed on another device." | FR-048 |
| unsaved title | follow-up or return-to-Next title typed, then Skip, Leave or another item | As M-13 "leave with unsaved text" | as M-13 | FR-052 |
| archived project | follow-up in archived project | Follow-up blocked with reason (as macOS POC) | "Restore this archived project before creating a follow-up in it." | edge case |
| empty | nothing older than 7 days | Finishes with nothing to decide | "Nothing to chase" | FR-029 |
| stale | changed elsewhere | M-03 stale pattern | — | FR-011 |
| offline | no connection | Works locally | — | FR-040 |
| loading / error / filtered | **n/a** (local) | — | — | — |

### M-19 — Projects without a next action

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | step opens | Short list, each with "Add next action" and "Suggest" (M-08 block) | "A project moves only when it has something you can do next." | FR-019, FR-028 |
| empty | every active project has a next action | One line | "Every active project has a next action." | FR-029 |
| AI states | Suggest | M-05 / M-06 / M-07 / M-08 states | — | FR-019 – FR-025 |
| offline | no connection | Add works locally; AI per M-05/M-07 | — | FR-040 |
| loading / error / partial / filtered | **n/a** beyond the AI states | — | — | — |

### M-20 — Someday pass

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | step opens | One of at most 7 Someday tasks that no "keep" hides, longest-unreviewed first (never reviewed first); tasks auto-parked in the last 30 days are left out because they were on "While you were away"; keep / move to Next / cancel; auto-park label on older parked tasks | "Keep in Someday · Looks again in 30 days" | FR-032, FR-034, US4-6 |
| undo didn't apply | Undo after the task changed elsewhere | As M-03 "undo didn't apply" | as M-03 | FR-048 |
| unsaved title | concrete title typed, then Skip, Leave or another item | As M-13 "leave with unsaved text" | as M-13 | FR-052 |
| move to Next | "Move to Next" | Required concrete title | "What's the first concrete action?" | US4-6 |
| next item, with Undo | any Someday decision applied | Status line with Undo (~5 s) above the next item | ""Build a raised bed" kept in Someday · looks again in 30 days" · "Undo" | FR-048 |
| empty | nothing due a look | One line | "Nothing in Someday needs a look this week." | FR-029 |
| stale | changed elsewhere | M-03 stale pattern | — | FR-011 |
| offline | no connection | Works locally | — | FR-040 |
| loading / error / filtered | **n/a** (local) | — | — | — |

### M-21 — Dates in the next 14 days

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | step opens | Grouped by day with the list each task is in | "The next 14 days" | FR-028 |
| empty | nothing due | One line | "A clear two weeks / Nothing has a due date in the next 14 days." | FR-028 |
| offline | no connection | Identical (local) | — | FR-040 |
| loading / error / partial / filtered | **n/a** (local) | — | — | — |

### M-22 — Summary

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | last step | Ten counts in fixed order (zero dimmed): Done, Reformulated, First step, Waiting for, Someday / maybe, Cancelled, Kept 7 more days, Inbox processed, **Kept as is**, **Moved to Next**; next review date, optional question, Done (owner decision PD-1, 2026-10-06) | "Review done" / "Next review: Fri 16 Oct, 16:00" / "Clear how to start the week? optional" / "Kept as is" / "Moved to Next" | FR-033, US4-9 |
| answered | Yes / Not really | Selection and a neutral acknowledgement | "Thanks. Noted for this review." | FR-033, SC-003 |
| empty | all ten counts are zero, but a step was finished | One calm line instead of a zero grid | "Nothing needed changing this time." | FR-033 |
| done without any step | every step was skipped, then Done (status `completed_empty`, PD-2) | The same calm "Review done" screen, next review date and question; no reproach and no mention that it doesn't count. It is not a counted review: "Last review" does not move, restart mode is not postponed and the weekly notification still comes | "Review done" / "Next review: Fri 16 Oct, 16:00" | FR-029, FR-033 |
| offline | completed offline | Saved locally; syncs; visible on web after sync | "Offline. This review is saved on this iPhone and syncs when you're back online." | SC-007 |
| partial failure | a decision rejected on sync | Named, Ref, counts reflect applied only | ""Book a dentist appointment" changed on another device before your decision synced…" | FR-011, FR-045 |
| loading / filtered | **n/a** | — | — | — |

### M-23 — Settings

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | Settings | Weekly review and Suggestions sections | "Last review: 9 days ago" / "Cloud suggestions · OpenAI · allowed since Sat 3 Oct" | FR-023, FR-049, FR-024, FR-035, FR-038 |
| threshold changed | new threshold | Note with the earliest possible park date | "Markers in Next update now. Because of this change, nothing moves to Someday before Fri 16 Oct." | FR-039 |
| delete model (confirm) | Delete downloaded model | Alert stating what is freed and what changes | "Delete the downloaded model? Frees 1.1 GB…" | FR-049 |
| empty (first run) | nothing set up | Defaults; "Not yet"; "Not downloaded"; "Ask me"; consent off | "Last review: Not yet" | FR-023, FR-038 |
| revoked | toggle off | Immediate stop, note | "Cloud suggestions are off. Nothing will be sent to OpenAI." | FR-024 |
| offline | no connection | Editable; sync later; revoke effective at once on this iPhone | "Offline — 2 changes waiting. Other devices stop cloud suggestions once this change syncs." | FR-024, FR-040 |
| error | account rejected change | Kept locally, retried, Ref | "Your new review day couldn't be saved to your account yet." | FR-045 |
| loading / filtered / partial | **n/a** (local) | — | — | — |

### M-24 — Next actions widget

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | N > 0 tasks ask | Indigo "N ask" chip beside the count in small, medium and large. In medium and large it is a link ("3 ask ›") with a 44 × 44 pt hit area. WidgetKit gives a small widget only one tap target. Owner decision on 2026-10-05: the small widget only shows the chip, and tapping it opens Next as today. FR-037 scopes the deep link to medium and large. Its completion button still works in place. | "3 ask ›" (VoiceOver: "3 tasks ask for a decision. Open the review's decision step") | FR-037, US5-3 |
| chip tapped | tap on the chip (medium/large) | App opens on the review's decision step at the first card (M-16), following the entry order: M-26 if the explainer was never seen, M-12 if never onboarded, M-09 if unseen parks exist, M-10 if restart mode applies, then M-16. An open review resumes at its decision step; otherwise a quick review starts there with Wins and Inbox marked skipped. | — | FR-037, FR-027 |
| empty | N = 0 | No chip | — | FR-037 |
| not activated | explainer not yet seen | No chip | — | FR-051 |
| configured for Today | widget list = Today | No chip | — | FR-037 |
| error | store unreadable | Existing "Open Brain Buddy" state, unchanged | "Your lists show here once the app can read them." | — |
| offline | no connection | Identical (reads the shared local store; never syncs) | — | FR-040 |
| loading / partial / filtered | **n/a** — WidgetKit placeholder is the existing sample entry | — | — | — |

### M-25 — Weekly notification

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | chosen local day/time | One banner; tap → M-11 | "Weekly review / Your review time. The quick one takes about 5 minutes." | FR-036, US5-2 |
| skipped this week | a complete or partial review happened in the preceding 6 days (any device) | No notification. On iOS the pending one is cancelled when the review is recorded. | — | FR-036 |
| web | — | Never: the web sends no notifications; its only cue is the sidebar "Last review" line (D-01) | — | FR-036, FR-038 |
| permission declined | iOS permission off | Nothing sent, nothing nags (M-12 note) | — | FR-036 |
| offline | no connection | Fires anyway (local notification) | — | FR-040 |
| loading / empty / error / partial / filtered | **n/a** | — | — | — |

### M-26 — Auto-park explainer (new, 2026-10-06, owner decision PD-3)

Shown once per owner, at the first app open after the feature is switched on, before
anything else (also before the widget's deep link and before M-09). Independent of
the review onboarding (M-12). It ships in increment 1 with auto-park.

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | first app open, explainer never seen on any device | A sheet at `.large` detent with three short points and the grace date; "Got it" (primary) and "Change the number of days" | "How Next stays fresh" / "If a next action keeps the same wording for 14 days, it asks for a decision." / "If it's still undecided 7 days later, it moves to Someday / maybe. Nothing is deleted, and you can bring it back in one tap. It's the only thing the app moves on its own." / "Tasks already in Next won't move before Fri 23 Oct." | FR-051, FR-016, FR-018 |
| change the number of days | "Change the number of days" | The 7/14/21/28 picker inline (as M-23, with its floor note); the rule text follows the choice; "Got it" saves both | "If a next action keeps the same wording for 7 days, it asks for a decision." | FR-051, FR-039 |
| seen | "Got it" or Close | The sheet closes; the activation is recorded (queued if offline); markers start appearing from now on as tasks reach the threshold | — | FR-051, FR-016 |
| interrupted | app killed while the sheet is showing | Not recorded as seen; shows again at the next open | — | FR-051 |
| already seen elsewhere | the account's activation arrives on pull | Never shown on this device | — | FR-051 |
| offline | no connection | Works; the acknowledgement syncs later; this device shows the explainer even if another device already saw it (a harmless duplicate) | "Offline. This is saved on this iPhone and syncs later." | FR-051, FR-040 |
| account-less | no account | Same sheet; recorded on this iPhone only | — | FR-051, FR-014 |
| error | the account rejected the acknowledgement | Kept on device and retried; the sheet is not shown again | (no visible error; retried silently, Ref in Sync issues if it keeps failing) | FR-045 |
| loading / empty / partial / filtered | **n/a** — static copy from local settings | — | — | — |

### D-01 — Next actions with age markers + sidebar entry (web)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | Next actions route | 44 px rows; only asking and moves-tomorrow rows carry a marker chip (no ageing in the list). Enabled "Weekly review" sidebar link with the recap line, which is the web's only review cue. | "Last review: 9 days ago" | FR-004, FR-010, FR-036, FR-042 |
| loading | list fetch > 300 ms | Static placeholder rows | — | — |
| empty (first run) | no next actions | Existing empty state | "No next actions" | — |
| empty (filtered to nothing) | filter matches nothing | Copy + Clear filter | "No next actions tagged errands" | — |
| error | list fetch failed | Reason, Ref, Retry | "We couldn't load your next actions" + Ref | FR-045 |
| partial failure | **n/a** — one list response | — | — | — |
| offline / interrupted | offline | Banner; markers still shown; marker buttons disabled | "You're offline. Decisions need a connection. Retry when you're back online." | FR-040 |
| threshold just changed | D-04 change | One-time note | as M-01 | FR-039 |
| not activated | explainer never seen | No markers; D-05 opens first | — | FR-051 |
| While you were away (dialog at app open) | unseen parks at web open | M-09 content in a modal dialog. Focus goes to the dialog heading and is trapped. Esc and Close close **without** acknowledging (as iOS swipe-down: shown again at the next web open, at most once per day); focus returns to the main list heading. "Continue" acknowledges | as M-09 | FR-015 |
| WYWA: returning | a row's "Return to Next" pending | That row shows "Returning…", others stay enabled | "Returning…" | FR-015 |
| WYWA: return failed | non-stale failure | Row message with Ref and Retry | "Couldn't return "Update the CV" to Next. It's still in Someday / maybe." + Ref · "Retry" | FR-015, FR-045 |
| WYWA: partial failure | Return all with stale or archived rows | As M-09 partial-failure rows | as M-09 | FR-011, FR-015 |
| WYWA: offline | offline at web open | List shown; return buttons disabled with reason | "You're offline. Returning tasks needs a connection." | FR-040 |
| narrow (390 px) | viewport ≤ 390 px | Marker chip wraps under the title in the compact row (44 px hit area kept); the mobile navigation drawer shows the working "Weekly review" link with "Last review: 9 days ago" under it; no horizontal scroll | as default | FR-004, FR-038, FR-042 |

### D-02 — Decision dialog with the AI navigator (web)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default / recommendation | opened | 560 px dialog, M-03 content; each decision shows its key numeral beside it (1 … 7, or 1 … 6 when "Keep 7 more days" is hidden, numbered in the order shown) | as M-03 | FR-006, FR-007 |
| third stalled wording | FR-005 | Offer above decisions; "Think it through" (link to `/crt` for this task) only when `crt_canvas` is effective, otherwise only "Release to Someday" | as M-03 | FR-005 |
| unsaved text — leave? | Esc, Close or Back with a changed form field | Confirmation dialog, focus on "Keep editing"; Esc means Keep editing; closing or reloading the tab triggers the browser's leave warning; the text is kept as a browser-local draft and restored when the dialog reopens for the same task and wording | "Discard your new wording? It hasn't been saved." · "Keep editing" · "Discard" | FR-052 |
| proposals, notes shortened | as M-05 | Provider line plus the shortened-notes line | as M-07 | FR-019 |
| error: input too large | as M-07 | Banner, Ref, no retry | as M-07 | FR-019, FR-045 |
| error: decision not allowed | as M-03 | Banner, Ref | as M-03 | FR-011, FR-045 |
| suggestions unavailable | operator turned cloud suggestions off | "Suggest" replaced by a quiet line | "Suggestions aren't available right now." | FR-025 |
| narrow (390 px) | viewport ≤ 390 px | The dialog becomes a full-height sheet; decisions stack full width; the same focus rules | as default | FR-040 |
| loading (saving) | decision clicked | Pending on the chosen row only; others disabled | "Saving…" | FR-011 |
| cloud consent | first Suggest | Consent dialog; focus starts on "Not now" | as M-07 | FR-024 |
| proposals (cloud) | allowed | M-05 layout with provider line; Save first step | "Suggested by OpenAI from this task's details." | FR-019, FR-020 |
| error: provider timeout / malformed | provider fails | Banner, Ref, Try again | as M-07 | FR-025, FR-045 |
| error: cost cap | cap reached | Banner, Ref, no retry | as M-07 | FR-025, FR-045 |
| error: save failed | decision request failed (non-stale) | Banner in the dialog, Ref, Retry; nothing changed | "Couldn't save your decision. Nothing was changed." + Ref | FR-045 |
| stale | 409/stale | Existing web heading "Task changed elsewhere"; diff; Close | "Task changed elsewhere / Nothing was applied." | FR-011 |
| decision applied, with Undo | server confirmed | Dialog closes, row updates, and a bottom-left toast offers Undo for ~5 s. Focus goes to the next row. Ctrl+Z / Cmd+Z triggers Undo while the toast is visible (outside text fields), so keyboard users need not tab to it | ""Renovate the bathroom" released to Someday" · "Undo" | FR-006, FR-048 |
| undo didn't apply | 409 `undo_unavailable` | The toast turns into a message with Ref | "Couldn't undo: "Renovate the bathroom" changed on another device. It's in Someday / maybe now." + Ref | FR-048, FR-045 |
| offline / interrupted | offline; tab closed mid-dialog | Decisions disabled with reason; closing applies nothing to the task; typed text is kept as a browser-local draft (and the browser warns before the tab closes) | "You're offline. Decisions need a connection on the web." | FR-040, FR-052 |
| empty (first run / filtered) | **n/a** | — | — | — |
| partial failure | **n/a** — single command (as M-03) | — | — | — |

### D-03 — Weekly review shell (web)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default: entry / resume | /review | Resume card first if open; Quick / Full | as M-11 | FR-027, FR-029 |
| onboarding | first time | M-12 as a dialog with selects and a segmented threshold. It states that the web sends no reminders. | "The web doesn't send reminders; the sidebar shows when your last review was." | FR-035, FR-036 |
| While you were away | unseen parks | M-09 as a list | as M-09 | FR-015 |
| restart mode | 21+ days | M-10 with Undo, including "undone, some skipped" and, after a tab reload, "released, resumed after interruption" | as M-10 | FR-017 |
| step with rail | any step | 240 px rail (done / skipped / current, not jumpable) and a single 600 px column. The decision, Inbox, Waiting and Someday steps show an Undo status line for ~5 s after each decision (Ctrl+Z / Cmd+Z while visible). "Not now" passes a card. In the decision step the D-02 card is inline: Esc does nothing there (it never closes the review) and keys 1–7 still work; D-02's saving, save-failed, stale, decision-not-allowed and undo-didn't-apply rows apply to the inline card. | — | FR-028, FR-029, FR-034, FR-050, FR-048 |
| Inbox step: over 15 items | Inbox > 15 | The three FR-030 choices as buttons, focus on the heading | as M-15 | FR-030 |
| Inbox step: one at a time | processing | "Item 3 of 10", the item title, and the web choices: Next actions, Waiting for (with who/what), Someday / maybe, Done (2-minute rule), Cancel, Edit title; tab order heading → title → choices; after each choice focus moves to the next item's heading; Undo status line ~5 s returns the item to Inbox (FR-048) | "Item 3 of 10" / "Is it actionable? Choose where it belongs." | FR-030, FR-034, FR-048 |
| Inbox step: saving / failed | a choice pending / failed (non-stale) | Pending on the chosen button only, others disabled, "Saving…" after 300 ms; failure: banner with Ref and Retry, item stays current | "Couldn't save that choice. Nothing was changed." + Ref | FR-045 |
| Inbox step: partial failure | an item changed elsewhere | Named; it stays in Inbox | ""Buy printer paper" was changed on another device, so it stayed in Inbox." | FR-011 |
| Inbox step: done (with release) / empty | queue finished / Inbox empty | As M-15, with "Undo the release" until the step is left | as M-15 | FR-029, FR-030 |
| step action saving | any web step action (M-14 Add, M-15 item, M-18 decision, M-19 Add next action, M-20 decision, M-22 answer or Done) | Pending on the chosen button only, others disabled, "Saving…" after 300 ms | "Saving…" | FR-045 |
| step action failed | that request failed (non-stale) | Banner in the column with Ref and Retry; nothing changed | "Couldn't save "Keep waiting". Nothing was changed." + Ref · "Retry" | FR-045 |
| skip not saved | the session PATCH for Skip failed | Banner; the step stays current | "Couldn't save that you skipped this step. Try again." + Ref | FR-029, FR-045 |
| review ended elsewhere / moved on elsewhere | as M-13 | As M-13, focus to the notice heading | as M-13 | FR-029, SC-007 |
| leave with unsaved text | Leave, Skip or next item with a changed field | As M-13 "leave with unsaved text" (dialog, focus "Keep editing") plus the browser leave warning on tab close | as M-13 | FR-052 |
| narrow (390 px) | viewport ≤ 390 px | The rail collapses into "Step 4 of 10" text above a full-width column; Skip and Leave stay at the top; no horizontal scroll | "Step 4 of 10" | FR-040 |
| Waiting / capacity mirror | full steps | Wider layouts of M-17 and M-18 | as M-17, M-18 | FR-031, FR-032 |
| summary | last step | 4-column counts grid, next review, question | as M-22 | FR-033 |
| loading | route load > 300 ms | Static placeholders | — | — |
| error | review load failed | Reason, Ref, Retry; progress safe | "We couldn't load your review. Your progress is safe." | FR-045 |
| offline / interrupted | offline; tab closed | Progress saved server-side as of the last decision; Retry; resume anywhere | "You're offline. Decisions made so far are saved. Retry when you're back online, here or on another device." | FR-029, FR-040 |
| empty / partial | per-step as the matching M- screen; per-step saving and errors are the "step action" rows above, because on the web every step action is a server request (the M- rows' "n/a (local)" reasons do not apply) | — | — | — |

### D-04 — Settings (web)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | settings page | Two sections; save on change | as M-23 | FR-024, FR-035, FR-038 |
| threshold changed | new value | Inline note | as M-23 | FR-039 |
| revoked | toggle off | Immediate stop in this tab; the switch shows "Turning off…" until the server confirms, then the note | "Cloud suggestions are off." | FR-024 |
| empty (first run) | never reviewed, no consent | "Last review: Not yet"; toggle off | — | FR-038 |
| loading | > 300 ms | Static placeholders | — | — |
| error | save failed | Old value kept, Ref, Retry | "Your review day couldn't be saved. It's still Friday." | FR-045 |
| offline / interrupted | offline | Saving disabled; revoke still stops this tab at once | "You're offline. Changes can't be saved… Other devices keep cloud suggestions until you turn them off while online." | FR-024, FR-040 |
| partial failure / filtered | **n/a** — each control saves independently | — | — | — |
| narrow (390 px) | viewport ≤ 390 px | One column; each row stacks label above control | as default | FR-040 |

### D-05 — Auto-park explainer (web; new, 2026-10-06, owner decision PD-3)

M-26 content as a modal dialog at the first web open after the feature is switched
on, unless the explainer was already seen on any device (`explainer_seen` in
`GET /review/state`).

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | first web open, never seen | Dialog with the M-26 points and grace date; focus on the heading, trapped; "Got it" and "Change the number of days" | as M-26 | FR-051, FR-016, FR-018 |
| change the number of days | button | Inline threshold control (as D-04) | as M-26 | FR-051, FR-039 |
| seen | "Got it", Close or Esc | Dialog closes; `POST /review/explainer/acknowledge`; focus returns to the main heading | — | FR-051 |
| saving failed | the acknowledgement request failed | The dialog stays with a banner, Ref and Retry; it shows again next time if never saved | "Couldn't save that you've seen this. Try again." + Ref | FR-045, FR-051 |
| offline | offline at web open | The dialog shows; "Got it" is disabled with reason; Close shows it again next time | "You're offline. Try again when you're back online." | FR-040 |
| already seen elsewhere | `explainer_seen` is true | Never shown | — | FR-051 |
| narrow (390 px) | viewport ≤ 390 px | Full-height sheet | as default | FR-040 |
| loading / empty / partial / filtered | **n/a** — shown only after the state has loaded | — | — | — |

## Affordance → requirement map

Existing controls that this feature leaves unchanged (filters, list rows,
completion circles, Process inbox decisions and its Undo toast, the widget's
completion buttons, project/Tag pickers) are not listed.

| screen | affordance | what it does | FR ref |
|---|---|---|---|
| M-01, D-01 | "Asks for a decision" marker button | Opens the decision card for that task | FR-004, FR-010 |
| M-01, D-01 | "Moves to Someday tomorrow" marker button | Opens the decision card | FR-004, FR-010, FR-012 |
| M-02, web inline task detail | "Ageing" marker (not interactive; never in lists) | Shows the ageing state in task detail only | FR-004 |
| M-01, D-01 | Threshold-changed note "OK" | Dismisses the one-time note | FR-039 |
| M-02 | "Decide" | Opens the decision card from the task, any day | FR-010 |
| M-03, M-16, D-02, D-03 | Stall reason chips (6, toggle) | Records optional reason; highlights a recommended decision | FR-007 |
| M-03, M-16, D-02, D-03 | Done | Completes the task | FR-006 |
| M-03, M-16, D-02, D-03 | Reformulate | Opens the reformulate form | FR-006 |
| M-03, M-16, D-02, D-03 | Find a first step | Opens the first-step form | FR-006, FR-008 |
| M-03, M-16, D-02, D-03 | Move to Waiting for… | Opens the who/what form | FR-006 |
| M-03, M-16, D-02, D-03 | Release to Someday | Moves to Someday | FR-006 |
| M-03, M-16, D-02, D-03 | Cancel task | Cancels the task | FR-006 |
| M-03, M-16, D-02, D-03 | Keep 7 more days (hidden once used) | Opens the reason form | FR-006, FR-009 |
| D-02 only (web, when `crt_canvas` is effective) | "Think it through" (third stall) | Opens the thinking canvas from this task; iOS has no canvas and shows no such control | FR-005 |
| M-03, D-02 | "Release to Someday" in the third-stall offer | Same as the decision | FR-005 |
| M-03, D-02 | Close / Esc / swipe down | Closes with no change; with unsaved typed text it asks first (swipe-down blocked) | FR-010, FR-052 |
| M-03, M-04, M-05, M-13 – M-20, D-02, D-03 | "Keep editing" / "Discard" in the unsaved-text confirmation | Keeps the form open (default) / drops the typed text and its draft | FR-052 |
| M-04 | "Clear" on a restored draft | Drops the restored draft | FR-052 |
| D-02, D-03 | Ctrl+Z / Cmd+Z while an Undo toast or status line is visible | Same as Undo | FR-048 |
| M-26, D-05 | "Got it" / Close (Esc on the web) | Records that the explainer was seen; activation and the 14-day grace start then | FR-051, FR-016 |
| M-26, D-05 | "Change the number of days" | Shows the threshold control inline | FR-051, FR-039 |
| M-03, D-02 | Stale "Close" | Dismisses after a rejected stale decision | FR-011 |
| M-03 | Error "Try again" / "Choose again" | Retries the rejected decision / reopens the choices | FR-011, FR-045 |
| D-02 | Number keys 1–7 | Keyboard shortcut for the seven decisions | FR-006 |
| M-03, M-16, M-18, M-20, D-02, D-03 | "Undo" in the toast or status line (~5 s) | Reverts the decision just applied, exactly (clock, extension, receipts); in steps the card comes back as current | FR-048 |
| M-04, D-02 | Title field + "Save new wording" / "Save anyway" | Applies a reformulation | FR-001, FR-002, FR-006 |
| M-04, D-02 | First-step field + "Save first step" | New title; old title to notes as "Was: …" | FR-008 |
| M-04 | Waiting for field + "Move to Waiting for" | Moves to Waiting with who/what | FR-006 |
| M-04 | Reason field + "Keep until <date>" (disabled until filled) | One-time extension | FR-009 |
| M-04, M-05, D-02 | Back | Returns to the card with the reason kept | FR-006 |
| M-04, D-02 | "Suggest wording" / "Suggest a first step" (iOS caption shows the route: "· on this iPhone" / "· OpenAI") | Starts the navigator | FR-019, FR-022, FR-024 |
| M-05, M-07, M-08, D-02 | Stop | Cancels a running suggestion | FR-020 |
| M-05, M-06, M-07, M-08, D-02 | Proposal radio | Fills the field for editing | FR-020 |
| M-05, M-06, M-07, M-08, D-02 | None of these | Discards proposals, task unchanged | FR-020 |
| M-05 | Clarifying answer field + "Add to notes and suggest again" | Appends the answer to notes, re-runs | FR-021 |
| M-05 | "I'll write my own step" | Closes the question | FR-021 |
| M-05 | Try again (on-device error) | Re-runs on device | FR-022 |
| M-06 | "Download 1.1 GB" | Starts the explicit model download | FR-023, FR-049 |
| M-06 | "Continue with cloud" / "Use OpenAI in the cloud instead" | Goes to consent (M-07) | FR-023, FR-024 |
| M-06, M-07 | Not now | Closes; card usable without AI | FR-023, FR-024 |
| M-06 | Cancel download | Stops and discards the partial download | FR-049 |
| M-06 | Retry download / Try again (storage) | Retries the download | FR-049 |
| M-06 | Back to the card | Leaves the download running | FR-049 |
| M-07, D-02 | Allow and suggest | Grants one-time consent, sends the request | FR-024 |
| M-07, M-08, D-02 | Try again (cloud) | Retries after a provider failure | FR-025 |
| M-08, M-19 | "Suggest a next action" / "Suggest" | Runs the navigator for a project | FR-019 |
| M-08 | "Add to Next actions" | Creates the confirmed next action in the project | FR-020 |
| M-08 | Empty-project answer field + "Add to Next actions" | Creates the next action typed in answer to the question | FR-021 |
| M-09, D-03 | Return to Next (per row) | Returns one parked task with a fresh formulation | FR-015 |
| M-09, D-03 | Return all N / the other N | Returns every unreturned parked task | FR-015 |
| M-09, D-01, D-03 | Continue | Marks parks as seen, proceeds | FR-015 |
| M-09, D-01 | Close / swipe-down / Esc | Closes without marking the parks seen (shown again, at most once a day) | FR-015 |
| M-15, D-03 | "Undo the release" | Reverses the Inbox-remainder release; until the step is left | FR-030 |
| M-10, D-03 | Release N to Someday | Bulk release of Next tasks older than 4 weeks | FR-017 |
| M-10, D-03 | See which ones / Hide the list | Shows what the release would move | FR-017 |
| M-10, D-03 | Keep them and start the review | Declines the offer | FR-017 |
| M-10, D-03 | Undo / Undo the N | Reverses the bulk release, clocks included; available until the person moves on ("Start the review" or Close), also after an interruption | FR-017 |
| M-10 | Start the review | Proceeds to the mode picker | FR-027 |
| M-11, D-01 | "Weekly review" row / sidebar link | Opens the review (replaces the disabled entry) | FR-027, FR-042 |
| M-11, D-03 | Quick / Full | Starts a review in that mode | FR-027, FR-028 |
| M-11, D-03 | Continue (resume) | Resumes an open review at its step | FR-029 |
| M-11, D-03 | Start a new review | Starts fresh; the open one is closed as partial/abandoned | FR-027, FR-029 |
| M-11, D-03 | Close | Leaves the review entry | FR-029 |
| M-11, M-12, D-01, D-03 | Try again / Retry (server error) | Retries the failed request | FR-045 |
| M-12, D-03 | Day, Time, threshold (7/14/21/28) | Collect review settings | FR-035 |
| M-12, D-03 | Continue | Saves settings; triggers the iOS notification permission prompt | FR-035, FR-036 |
| M-13 – M-21, D-03 | Skip / Skip step | Skips the current step | FR-029 |
| M-13 – M-21, D-03 | Leave → "Leave for now" / "Keep going" | Pauses the review, progress kept | FR-029 |
| M-13 – M-21 | "Next: <step>" | Finishes the step | FR-028 |
| M-14 | Capture field + Add | Adds an item to Inbox | FR-028 |
| M-15 | Process 10 now / Process all / Process 10, release the rest | Inbox overload choice | FR-030 |
| M-16, D-03 | Not now (single card) | Leaves this task asking for a decision and moves on; auto-park continues on schedule | FR-050 |
| M-18, D-03 | Keep waiting | 7-day receipt | FR-032 |
| M-18, D-03 | Create a follow-up + field + Create | New Next action in the same project | FR-028 (US4-5) |
| M-18, D-03 | Return to Next + editable title | Moves to Next with that title | FR-028 (US4-5) |
| M-18, M-20, D-03 | Cancel task | Cancels the item | FR-028 (US4-5, US4-6) |
| M-19 | Add next action | Inline field creating a Next task in the project | FR-028 |
| M-20 | Keep in Someday | 30-day receipt | FR-032 |
| M-20 | Move to Next + concrete title | Moves to Next with that title | FR-028 (US4-6) |
| M-22, D-03 | Yes / Not really | Optional answer stored with the review | FR-033 |
| M-22, D-03 | Done | Closes the completed review | FR-033 |
| M-23, D-04 | Day / Time / "Ask for a decision after" | Change review settings | FR-035, FR-039 |
| M-23 | "When it isn't available" picker | Remembered fallback choice (downloaded model / cloud / ask me) | FR-023 |
| M-23 | Delete downloaded model → Delete / Cancel | Removes the downloaded model | FR-049 |
| M-23, D-04 | Cloud suggestions switch | Grants (via consent) or revokes cloud consent | FR-024 |
| M-23, D-04 | Retry (settings error) | Retries saving | FR-045 |
| M-24 | "N ask ›" chip: a link in medium/large; display-only in small (the small widget opens Next) | Shows the count; opens the review's decision step at the first card | FR-037 |
| M-25 | Notification tap | Opens the review entry | FR-036 |

Display-only surfaces carrying requirements: "N days in Next" and help line
(M-02: FR-001, FR-003), paused line (M-02: FR-046), parked facts (M-02, M-09,
M-20: FR-012), "Last review: N days ago" (M-11, M-23, D-01, D-04: FR-038),
onboarding promises (M-12: FR-016, FR-018), capacity mirror (M-17: FR-031),
on-device note (M-05: FR-022), correlation IDs on every failure (FR-045).

### Requirements with no affordance

- **FR-013** (auto-park idempotent, skipped after changes, no sync conflict): no UI surface (backend/behaviour). Its visible consequence is the absence of a conflict prompt (M-01 offline row).
- **FR-014** (auto-park runs without a client; on-device for account-less iOS): no UI surface (backend/behaviour).
- **FR-016** (14-day grace for pre-existing tasks, from the explainer): no control; stated as copy with its date in M-26, D-05 and M-12.
- **FR-018** (auto-park is the only automatic change): no control; stated as copy in M-26, D-05 and M-12.
- **FR-026** (record whether an AI proposal was used): no UI surface (backend/behaviour).
- **FR-040** (iOS/web parity; iOS offline): no single affordance; satisfied by the M-/D- pairs and every screen's offline row.
- **FR-041** (Mac): no mockup by scope; the Mac shows a non-interactive "Weekly review · coming later" row until Mac sync, then follows D-01/D-02/D-03 and M-05/M-06.
- **FR-043** (storage, export, purge): no UI surface (backend/behaviour); the existing ZIP export and purge cover it without new controls.
- **FR-044** (logs and metrics content): no UI surface (backend/behaviour).

All other FR-001 … FR-052, including FR-046 – FR-050 and the campaign-1 additions
FR-051 (M-26, D-05) and FR-052 (the unsaved-text states and drafts), map to at least
one affordance or display surface above.

### Affordances with no requirement

None. The sign-off decisions are now in spec.md:

- Undo maps to FR-048.
- The widget chip's deep link maps to FR-037.
- "Not now" on a single card maps to FR-050.
- The list-only markers map to FR-004.
- The notification skip rule and the web's no-notification rule map to FR-036.

## Primary loop impact

This feature **is** the "smart Weekly Review" stage of the constitution's
primary loop (capture → atomic items → clarify/approve → route or CRT candidate
→ smart Weekly Review → evidence/results) for native tasks:

- **Capture**: the mind sweep (M-14) feeds the Inbox.
- **Clarify/approve**: the Inbox step reuses Process inbox (M-15). Reformulate and "Find a first step" (M-04, with the M-05 navigator) send stalled tasks back through clarification. Nothing AI-proposed is written without confirmation (FR-020).
- **Route / organize**: decisions move tasks to Waiting, Someday or Cancelled. Auto-park is the only automatic routing (FR-018).
- **CRT candidate**: on the web (when `crt_canvas` is effective), the third-stall offer (FR-005) opens the thinking canvas from the task. This is the review's bridge to CRT; iOS has no canvas.
- **Weekly Review**: M-09 … M-22 and D-03.
- **Evidence/results**: wins first (M-13), per-decision counts, and the "clear start" answer (M-22) are the review's evidence.

Voice-led review and review of agent-delegated work are out of scope.

## Mobile viability

- **Viewport**: every M- frame is drawn at 390 × 851 with no horizontal scroll. Long sheets (M-03, M-12, M-26) scroll vertically. The decision list sits in the lower half for thumb reach.
- **Narrow web**: every D- screen has a "narrow (390 px)" state (D-01 chip wraps and drawer recap, D-02 full-height sheet, D-03 rail collapsed into "Step N of M", D-04 one column, D-05 full-height sheet). Playwright checks no horizontal overflow at 390 px for `/review` and the decision dialog; once the flag is on for the test user, E2E-MOBILE-02 expects a working "Weekly review" link instead of the disabled entry.
- **Unsaved text**: no typed text is lost without a choice (FR-052): sheets holding unsaved text cannot be swiped away, leaving asks first, and drafts survive an app kill.
- **Tap targets**: 44 pt minimum everywhere. Reason chips and decision rows are 44–54 pt. Marker chips are about 22 pt tall but have a 44 × 44 pt hit area through an invisible inset (`button.mk::after`), and the whole row also opens the task. In medium and large widgets, the "N ask ›" chip is a link with a 44 × 44 pt hit area; in the small widget the chip is display-only and the widget opens Next. Undo buttons in toasts and status lines are 44 × 44 pt.
- **One-handed reach**: primary actions are in the bottom bar (review steps) or the lower half of the sheet (card). "Leave" / "Skip" are at the top, deliberately harder to hit by accident.
- **Destructive actions**:
  - "Delete downloaded model" asks first: "Frees 1.1 GB. Suggestions for languages Apple's model doesn't support will need the download again, or the cloud. Your tasks aren't affected."
  - "Cancel task" has no confirmation (one or two taps per FR-006). It says "Stays findable under Cancelled", and like every card, Waiting and Someday decision it can be undone from the toast for about 5 s.
  - Bulk release (M-10) is undoable in place.
  - "Process 10, release the rest" states "Nothing is deleted".
- **Dynamic Type**: at accessibility sizes the card's decision list scrolls with the content instead of being pinned, as Process inbox does today.
- **Reduce Motion**: card-to-card transitions in M-16 are instant. No ambient animation anywhere in this feature.

## Keyboard and focus

- **Tab order**:
  - D-01: marker buttons in row order after each row's title.
  - D-02: title → reasons → decisions → (forms) field → Suggest → proposals → Back → Save.
  - D-03: Skip step → Leave → step content → primary action. The rail is not focusable because it is not interactive.
- **Focus trap**: every web modal traps focus while open: D-02, the consent dialog, the D-03 onboarding dialog, the Leave confirmation, the unsaved-text confirmation, the While-you-were-away dialog (D-01), the D-04 consent dialog and D-05.
- **Focus on open**:
  - D-02 focuses the dialog title; the consent dialog focuses "Not now".
  - D-03 focuses the step heading on every step change.
  - D-03 onboarding focuses its heading "A weekly reset"; Esc / Close saves nothing, onboarding shows again next time, and focus returns to the entry's Close.
  - The Leave confirmation focuses "Keep going"; Esc means Keep going and focus returns to "Leave".
  - The unsaved-text confirmation focuses "Keep editing"; Esc means Keep editing.
  - The While-you-were-away dialog (D-01) and D-05 focus their headings.
  - iOS: VoiceOver focus goes to the card title (as Process inbox does), to the step title on every step change, and to the next item's title after each decision in M-16, M-18 and M-20.
- **Focus restored on close to**: the marker chip or "Decide" button that opened the card. After a decision removes that row, focus goes to the next row's title. Closing the consent dialog returns focus to "Suggest" (D-02) or to the switch (D-04).
- **Escape**: closes D-02 with no change (asking first when a form holds unsaved text). Inside a form it returns to the card first. In D-03, Escape closes nested dialogs only, never the review; on the inline decision card in D-03 it does nothing.
- **Number keys** (D-02 and the inline card): 1 … 7 are inactive while a text field has focus; elsewhere they map to the numerals shown beside the decisions, so the mapping stays visible when only six are offered.
- **Accessible names**:
  - Marker buttons: "Asks for a decision. Open decision for <title>".
  - Widget chip: "3 tasks ask for a decision. Open the review's decision step".
  - Undo: "Undo: <what it reverts> <title>".
  - "Return to Next" rows: "Return <title> to Next".
  - Disabled archived row: "Return unavailable: project <name> is archived".
  - Close icon: "Close".
  - Settings switches name the provider.
- **Undo toasts (web)**: announced with `role="status"`; Ctrl+Z / Cmd+Z triggers Undo while the toast is visible (not inside a text field), and the toast's accessible description names it ("Undo: Released to Someday Renovate the bathroom (Ctrl+Z)"), so keyboard users need not tab across the list; Undo is also reachable with Tab. The timer pauses while the toast has focus or hover.
- **Undo (iOS)**: VoiceOver announces "<decision>. Undo available." With VoiceOver or Switch Control running, the toast or status line stays at least 10 s and until focus leaves it.
- **State communicated by color alone**: none. Markers are text plus icon. The recommendation adds a "Recommended" chip. Selected reasons use `aria-pressed`. Progress segments are paired with "N of M" text. Skipped steps are dashed and labelled "skipped".

## Design authority

- Tokens, colours and type come from the `brain-buddy-design` skill: slate neutrals, sky accent, the indigo secondary used sparingly (here only for the "asks for a decision" marker), amber warning semantic, rose only for due dates and destructive controls, radii of 8/12/14/20, the soft/raised/floating shadows and the double-ring focus.
- Filled controls and brand text use sky-700, as both shipped apps already do (`docs/native-ios-app.md` deviation 5; `bg-sky-700` in the web shell).
- iOS mockups use the system font stack (iOS deviation 3), and web mockups name Inter with system fallbacks. No font is downloaded, so the files stay self-contained.
- Icons are inline SVG copies of Lucide shapes. iOS maps them to SF Symbols per the documented mapping.
- The AI navigator uses a sky `Compass`, not emerald `Sparkles`, because the skill reserves emerald/Sparkles for the speculative Execution exploration. The logo path is an inline copy of `assets/logo.svg`.
- **Conflict to resolve in planning**: the skill's README and SKILL.md still say "Weekly Review remains visibly deferred", and `scripts/test_validate_brain_buddy_design_skill.py` asserts that string and the nav card's "coming later". This design turns the deferred entry into a working one. That needs the ADR the spec already calls for (amending ADR-0006 D-11 and ADR-0001), and then a coordinated skill-and-test change. This stage did not touch the skill or the test.
- Vocabulary check (ADR-0006: Tag, never the retired term or its at-prefixed form): pass (grep, zero hits in `design.md` and `design/`).
- `python3 -m unittest scripts/test_validate_brain_buddy_design_skill.py`: pass.

## Resolved

Spec gaps found while designing, resolved as owner defaults on 2026-10-05 and
reflected in the screens:

1. **Clarifying-question answer path (FR-021 vs FR-019).** The answer is appended to the task's notes as an ordinary, visible notes edit with no clock change, and the navigator runs again (M-05). For an empty project, the answer is typed straight in as the next action (M-08).
2. **FR-030.** "Process 10 now, then release the remainder to Someday" (M-15).
3. **Undo for decisions.** Every card decision shows an Undo toast or status line for about 5 s, like Process inbox. This covers the in-list sheet (M-03), the review decision step (M-16), Waiting (M-18), Someday (M-20) and web (D-02, D-03). Spec: FR-048.
4. **Restart bulk-release Undo (FR-017).** It lasts until the person leaves the restart screen (M-10). Clarified 2026-10-06: leaving means "Start the review" or Close; an app kill, backgrounding or tab reload is not leaving, so the review reopens on the released state with Undo still offered.
5. **Notifications (FR-036).** No notification in a week where a complete or partial review happened in the preceding 6 days. The web sends no notifications; its only cue is the sidebar "Last review" line (M-25, D-01, D-03 onboarding copy).
6. **Wins** means the last 7 days (M-13).
7. **Restart for someone onboarded but never reviewed.** Same neutral restart offer, with no "Welcome back" or "you've been away" wording (M-10, "set up but never reviewed").
8. **"Not now" on a single card** maps to the new FR-050. The task keeps asking and auto-park continues on schedule. SC-002 is measured only over reviews whose decision step finished with no "Not now" (M-16, D-03).

## Amendments 2026-10-06 (planning-review campaign 1)

Owner decisions (spec Clarifications "Session 2026-10-06"):

- **PD-1**: M-22 shows ten counts; "Kept as is" and "Moved to Next" are new.
- **PD-2**: M-22 "done without any step" — "Review done" with no reproach; the review is recorded as completed without activity and does not count.
- **PD-3**: new screens M-26 / D-05, the one-time auto-park explainer at first app or web open; M-12 copy now states the grace date from that moment; M-01, D-01 and M-24 show nothing before it is seen.

Design findings resolved (details in `review-c1-disposition.md`): unsaved-text
confirmation and drafts (FR-052) across M-03 – M-05, M-13 – M-20, D-02, D-03;
restart Undo after an interruption and "undone, some skipped" (M-10); the web
While-you-were-away dialog (D-01); the web Inbox step and per-step saving and error
states (D-03); narrow 390 px web states (D-01 – D-05); "review ended / moved on
elsewhere" (M-13, D-03, M-11); notes-shortened, input-too-large, decision-not-allowed
and undo-didn't-apply copy; navigator "interrupted" rows (M-05, M-07, M-08); route
caption on Suggest; focus traps and Escape rules; keyboard and VoiceOver Undo; widget
entry order (M-24); Undo for the Inbox-remainder release (M-15); M-09 swipe-down
meaning; third-stall offer without a canvas on iOS (M-03); M-04 date copy corrected
to "Fri 16 Oct" (NC-1).

## Notes for the plan

- **Mac (FR-041).** A small pre-sync Mac change is needed: a non-interactive "Weekly review · coming later" row in the Mac sidebar, because the Mac app has none today. Separately, the Mac's existing POC "Review Waiting for" / "Review Someday" sheets overlap M-18/M-20, and their fate after Mac sync is a planning call.
- **Small widget.** WidgetKit gives `systemSmall` a single tap target, so the "N ask" chip can't be a separate link there. **Decided by the owner on 2026-10-05:** the small widget shows the chip as display-only, and its `widgetURL` stays Next actions (today's behaviour). FR-037 was amended to scope the deep link to medium and large. Its in-place completion button is unaffected.
- **Widget deep link with no open review** starts a quick review at the decision step, with Wins and Inbox marked skipped. Decisions made there count as review decisions (FR-029 partial/complete rules apply). The entry order before M-16 is M-26 (explainer, if never seen), M-12, M-09, M-10 (M-24 "chip tapped").
- **Explainer ships with auto-park.** M-26 and D-05 belong to increment 1, because auto-park never runs for an owner who has not seen them (FR-051).
- **Design-skill deferral string** (see Design authority). The ADR, then the skill and validator-test update, must land with or before implementation.

## Sign-off

Approved by **Max** on **2026-10-05**, with these decisions:

1. **Decision card on iPhone outside the review**: a large-detent sheet over Next (M-03). Inside the review it is full-screen (M-16).
2. **Marker prominence**: lists (M-01, D-01, M-17) show only "Asks for a decision" and "Moves to Someday tomorrow". "Ageing" appears only in task detail (M-02 and the web inline task detail).
3. **Widget**: the "N ask" chip in the header is tappable and deep-links straight into the review's decision step at the first card (M-24 → M-16). It is a link in medium and large. In small, the chip is display-only and the widget keeps opening Next (follow-up owner decision; FR-037 scoped to medium and large).
4. **Undo**: every card decision (M-03, M-16, D-02, D-03) and every Waiting/Someday decision (M-18, M-20) shows an Undo toast for a few seconds, like Process inbox.
5. **"Not now"** stays on a single card in the decision step. The task remains "asks for a decision" and auto-park continues on schedule (FR-050). SC-002 is measured only over reviews whose decision step finished with no "Not now".
6. **Notification**: none for a week if a complete or partial review happened in the preceding 6 days. The web has no notifications, only the sidebar "Last review" line.

Choices the owner left as designed:

- "While you were away" opens as a sheet on app open.
- The reason → recommendation mapping (M-03 header).
- Indigo for "asks" and amber for "tomorrow".
- Compass as the navigator icon.
