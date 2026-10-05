# Design: Weekly Review

**Feature**: `specs/020-weekly-review/`
**Spec**: `spec.md` (Clarifications settled: 2026-10-05)
**Screens**: `design/*.html` — self-contained static HTML, inline CSS, inline SVG icons, no CDN, no external fonts, no script
**Human sign-off**: approved by Max on 2026-10-05, with decisions 1–6 (see Sign-off)

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
web (desktop), designed below. iOS screens are `M-` ids; web screens are `D-`
ids. Where the web shows the same content as an iOS screen in a different
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
change the plan must schedule (see Unresolved).

### Example data used in every mockup

Today is Fri 9 Oct 2026, 16:02 local. Threshold 14 days (auto-park at 21).
Review slot Friday 16:00. Last review Wed 30 Sep ("9 days ago"). Provider name
"OpenAI" and model size "1.1 GB" are **illustrative**: the cloud provider and
the downloadable model are planning decisions (spec Assumptions).

### Entry order of the review

Entry (M-11 row, D-01 sidebar link, or M-25 notification) → onboarding M-12
(first time only) → While you were away M-09 (only if unseen parks exist) →
restart mode M-10 (only if no complete/partial review for 21+ days) → resume
or mode picker M-11 → steps M-13 … M-22.

## Screen inventory

| id | surface | screen | purpose | FR refs |
|---|---|---|---|---|
| M-01 | mobile (iOS Next tab) | Next actions with age markers | Shows "asks for a decision" and "moves to Someday tomorrow" per task (ageing is detail-only); the marker opens the card as a sheet | FR-003a, FR-004, FR-010, FR-012, FR-038, FR-039, FR-040 |
| M-02 | mobile (iOS task detail) | "This wording" section in task detail | States formulation age in words, including the ageing marker (shown only here), the due-date pause, extension and park facts; "Decide" from the task on any day | FR-001, FR-003, FR-003a, FR-004, FR-009, FR-010, FR-012 |
| M-03 | mobile (iOS sheet) | Decision card | One task, one decision: seven decisions, optional stall reason with a recommendation, third-stall offer, stale handling | FR-005, FR-006, FR-007, FR-009, FR-010, FR-011, FR-040, FR-045 |
| M-04 | mobile (inside M-03) | Decision card follow-up forms | Reformulate, find a first step ("Was: …"), Waiting for (who/what), keep 7 more days (reason required) | FR-001, FR-002, FR-006, FR-008, FR-009, FR-019 |
| M-05 | mobile (inside M-04) | AI navigator, on-device | 1–3 proposals from Apple's on-device model; pick fills, confirm writes; clarifying question; offline | FR-019, FR-020, FR-021, FR-022 |
| M-06 | mobile (inside M-04) | On-device model unavailable: choice and download | Says why; offers downloadable on-device model (size shown) or cloud; download progress, interruption, storage | FR-023, FR-023a |
| M-07 | mobile (inside M-04) | Cloud consent and cloud failures | One-time consent naming provider and exact data; revoked re-consent; timeout/cap/offline with correlation ID | FR-024, FR-025, FR-045 |
| M-08 | mobile (iOS project screen) | Project without a next action — AI first next action | Proposes a first next action and creates it in Next on confirm | FR-019, FR-020, FR-021 |
| M-09 | mobile (sheet / first review screen) | While you were away | Lists unseen auto-parked tasks; one-tap return each; return all | FR-012, FR-015 |
| M-10 | mobile (review cover) | Restart mode | After 21+ days without a review: neutral welcome, one reversible bulk release of Next tasks older than 4 weeks | FR-017, FR-038 |
| M-11 | mobile (Lists hub + review cover) | Review entry, mode picker, resume | Replaces the deferred row; quick/full choice; resume an open review from any device | FR-027, FR-028, FR-029, FR-038, FR-042 |
| M-12 | mobile (review cover) | Onboarding | Why, threshold rule, auto-park; collects day/time (Fri 16:00) and threshold (7/14/21/28, 14) | FR-016, FR-018, FR-035, FR-036 |
| M-13 | mobile (review step) | Wins of the week (+ shared step chrome, leave) | First step, before any backlog: completed tasks and their count | FR-028, FR-029 |
| M-14 | mobile (review step, full) | Mind sweep | Capture anything on the mind into Inbox | FR-028, FR-029 |
| M-15 | mobile (review step) | Inbox to zero | ">15 items" choice; one item at a time via Process inbox | FR-028, FR-030, FR-034 |
| M-16 | mobile (review step) | Tasks that ask for a decision | The M-03 card one at a time, oldest first; "Not now" passes a card; Undo after each decision | FR-028, FR-034, FR-034a, FR-006 |
| M-17 | mobile (review step, full) | The rest of Next with capacity mirror | Count, 4-week weekly average, implied weeks; no limit | FR-028, FR-031 |
| M-18 | mobile (review step, full) | Waiting for, older than 7 days | One at a time: keep waiting / follow-up / return to Next / cancel | FR-028, FR-032, FR-034 |
| M-19 | mobile (review step, full) | Projects without a next action | Add or suggest a next action per project | FR-019, FR-028 |
| M-20 | mobile (review step, full) | Someday pass | Max 7 items not reviewed in 30 days; keep / move to Next with a concrete title / cancel | FR-028, FR-032, FR-034 |
| M-21 | mobile (review step, full) | Dates in the next 14 days | Read-only look ahead | FR-028 |
| M-22 | mobile (review step) | Summary | Counts per decision type, next review date, optional "Clear how to start the week?" | FR-033, FR-038, SC-003, SC-007 |
| M-23 | mobile (iOS Settings) | Weekly review and Suggestions settings | Day, time, threshold, last review; on-device status, fallback choice, delete model, cloud consent revoke | FR-023, FR-023a, FR-024, FR-035, FR-038, FR-039 |
| M-24 | mobile (iOS widget) | Next actions widget with "N ask" | Shows how many tasks ask for a decision; in medium and large the chip deep-links into the review's decision step | FR-037 |
| M-25 | mobile (iOS notification) | Weekly review notification | The single weekly cue, skipped if a complete or partial review happened in the preceding 6 days; iOS only | FR-036, FR-038 |
| D-01 | desktop (web) | Next actions with age markers + Weekly review sidebar entry | Web markers (as M-01, no ageing in the list) and the working entry replacing "Coming soon"; the sidebar "Last review" line is the web's only review cue | FR-003a, FR-004, FR-010, FR-012, FR-038, FR-039, FR-042, FR-045 |
| D-02 | desktop (web dialog) | Decision dialog with the AI navigator | M-03/M-04/M-05/M-07 content in a 560 px dialog; cloud-only navigator | FR-005 – FR-011, FR-019 – FR-021, FR-024, FR-025, FR-045 |
| D-03 | desktop (web route) | Weekly review shell | Focused route with step rail; hosts M-09 … M-22 content; onboarding dialog | FR-015, FR-017, FR-027 – FR-035, FR-045 |
| D-04 | desktop (web settings) | Weekly review and Suggestions settings | M-23 minus on-device rows | FR-024, FR-035, FR-038, FR-039, FR-045 |

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
| default | Next tab open | Rows grouped by project. Only asking and moves-tomorrow rows carry a marker; fresh and ageing rows have none. A future-due task shows only its due chip. Tapping a marker opens the M-03 sheet. | "Asks for a decision", "Moves to Someday tomorrow" | FR-003a, FR-004, FR-010, SC-006 |
| loading | cold launch while the local store opens, > 300 ms | Four static placeholder rows; markers arrive with the rows | — | — |
| empty (first run) | no next actions | Today's empty state, nothing about age | "No next actions" / "Process your inbox to choose what comes next." | — |
| empty (filtered to nothing) | Tag/priority filter matches nothing | Different copy, count of hidden tasks, "Clear filter" | "No next actions tagged errands" / "7 next actions are hidden by this filter." | — |
| error | local store unreadable (e.g. before first unlock) | Reason and "Try again"; no correlation ID because nothing reached a server | "We couldn't open your tasks" / "Unlock your iPhone and try again. Nothing was changed." | — |
| partial failure | **n/a** — one local read; markers are computed per task from local data, so there is no per-item failure path | — | — | — |
| offline / interrupted | no connection | Markers keep working from the device clock; sync state in words | "Offline — 2 changes waiting" | FR-040, FR-013 |
| threshold just changed | threshold changed in M-23 | One-time dismissible note; markers already updated | "Your threshold is now 7 days. 4 tasks ask for a decision. Nothing moves to Someday before Fri 16 Oct." | FR-039 |

### M-02 — Task detail, "This wording" section

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default (asks) | task asks for a decision | Marker, age in days, reassurance, what doesn't restart the clock, "Decide" | "The wording hasn't moved for a while. That's feedback on the wording, not on you. Changing notes, Tags, project or priority doesn't restart the clock." | FR-001, FR-003, FR-010 |
| ageing / fresh | age < T | Ageing: the "Ageing" chip (its only place on iOS) and the date it will ask. Fresh: days only. No Decide. | "Asks for a decision from Wed 14 Oct if the wording stays the same." | FR-004 |
| clock paused | future due date | Paused chip and date | "The clock starts on Fri 16 Oct. Until then this task won't ask for a decision or move to Someday." | FR-003a |
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
| third stalled wording | 3rd consecutive formulation reached the threshold | Gentle offer above reasons: "Think it through" (canvas) / "Release to Someday"; nothing blocked | "This is the third wording in a row that has stalled. Sometimes the task isn't the problem…" | FR-005 |
| stale | task changed elsewhere since the card opened | Nothing applied; was/now diff; current state; Close | "This task changed on another device, so nothing was applied. Here's the current version." | FR-011 |
| decision applied, with Undo | any decision confirmed | Sheet closes and the row updates. A toast names the decision and offers Undo for about 5 s, like Process inbox. Undo restores the task exactly, including clock, extension and receipts. | ""Renovate the bathroom" released to Someday" · "Undo" | FR-006, FR-010, owner decision 4 |
| undo window expired | ~5 s pass | Toast fades. The decision stands and is changeable later through ordinary task moves. | — | owner decision 4 |
| error | offline decision rejected by the server after sync (non-stale) | Reason, correlation ID, "Try again" / "Choose again" | "Your decision "Move to Waiting for" couldn't be saved to your account. The task is still in Next." + Ref | FR-011, FR-045 |
| offline / interrupted | no connection; or app killed with the card open | Works offline, queued; killed before a choice → nothing applied, card opens fresh | "Offline. Decisions are saved on this iPhone and sync later." | FR-040 |
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
| keep 7 more days, ready | reason typed | Button enabled with the new date | "Keep until Thu 15 Oct" | FR-009 |
| loading | **n/a** on iOS (local); web in D-02 | — | — | — |
| error | as M-03 error | — | — | FR-045 |
| partial failure | **n/a** — single command | — | — | — |
| offline / interrupted | no connection; app killed mid-form | Works offline; a killed form is discarded and the task is unchanged | — | FR-040 |

### M-05 — AI navigator, on-device

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| loading | "Suggest" | Static placeholder lines, "Stop" | "Suggesting on this iPhone…" | FR-022 |
| default: proposals | model returns | 1–3 radio proposals, on-device note, "None of these" | "Suggested on this iPhone. Nothing left the device." | FR-019, FR-022, SC-005 |
| picked, editing | a proposal tapped | Field filled and editable; Save enabled; "Was:" kept | "Pick one to edit" | FR-020 |
| dismissed | "None of these" or "Stop" | Back to the M-04 form, field and task unchanged | — | FR-020 |
| clarifying question | input too thin to ground a step | One question, an answer field, "Add to notes and suggest again", "I'll write my own step" | "What does "things" mean here? Which part of your life or home is this about?" | FR-021 (see Unresolved) |
| partial failure | some proposals dropped (duplicate of an open task, or malformed) | Fewer than 3 proposals shown, no message | — | FR-019 |
| error | nothing usable returned | Plain reason, "Try again"; no correlation ID (no server) | "No useful suggestion this time. You can try again, or write your own step." | FR-021 |
| offline | airplane mode | Same as default; note says it works offline | "Suggested on this iPhone. Works offline." | FR-022, FR-040 |
| empty (first run / filtered) | **n/a** — the panel exists only after "Suggest" | — | — | — |

### M-06 — On-device model unavailable: choice and download

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default: choice (language) | Apple's model doesn't support the task's language | Reason; two choices (download with size, cloud); "Not now"; remembered | "Apple's on-device model doesn't support Russian yet." / "Download 1.1 GB" / "Continue with cloud" | FR-023, FR-023a |
| choice (Apple Intelligence off / model not ready) | other unavailability reasons | Same layout, reason line differs | "Apple Intelligence is turned off on this iPhone." / "Apple's model is still getting ready." | FR-023 |
| choice (device can't run models) | unsupported device | Download shown unavailable with reason; cloud and Not now | "Not available on this iPhone." | FR-023 |
| loading: downloading | "Download" | Progress bar in bytes, time estimate, "Cancel download", card stays usable | "420 MB of 1.1 GB · about 3 minutes on Wi-Fi" | FR-023a |
| offline / interrupted | connection lost mid-download | Why, "Retry download" (resumes), cloud alternative | "The connection dropped at 420 MB of 1.1 GB." | FR-023a |
| error: not enough storage | before or during download | Numbers, "Try again", cloud alternative; nothing deleted for the person | "The model needs 1.1 GB. This iPhone has 640 MB free." | FR-023a |
| installed → suggestions | download complete | Proposals in the task's language, on-device note, offline OK | "Suggested on this iPhone by the downloaded model. Works offline." | FR-023 (a), FR-022 |
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
| offline / interrupted | no connection | On-device as M-05 offline; cloud as M-07 offline | — | FR-022, FR-040 |

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

### M-10 — Restart mode

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | no complete/partial review for 21+ days | Neutral welcome; count; Release / Keep; "See which ones" | "Your last review was 26 days ago. Gaps happen. Let's make Next fit the week ahead." | FR-017, FR-038 |
| list expanded | "See which ones" | Read-only titles with age | "17 next actions are older than 4 weeks" | FR-017 |
| released | Release | Confirmation, new Next count, and Undo, which lasts until the person leaves this screen (owner default) | "17 tasks released to Someday / maybe. Next now holds 12 tasks." | FR-017, US2-7 |
| set up but never reviewed | onboarded 21+ days ago, no review yet | Same offer; heading without "Welcome back" or any wording implying the person was away | "Your first review / Let's make Next fit the week ahead." | FR-017, FR-038 |
| undone | Undo | Everything restored including clocks | "Undone. All 17 are back in Next as they were." | FR-017 |
| partial failure | some tasks changed elsewhere meanwhile | Named; Undo covers only the released | "2 tasks changed on another device in the meantime, so they stayed in Next…" | FR-011, FR-017 |
| empty | nothing older than 4 weeks | Welcome without an offer | "Nothing in Next is older than 4 weeks, so let's go straight in." | FR-017 |
| offline / interrupted | offline; app closed after release | Applies locally; resumes past this screen; tasks movable back one by one | "Offline. Changes are saved on this iPhone and sync later." | FR-040 |
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
| error | server check failed | Ref, Try again; can still start | "We couldn't check for a review in progress on your other devices." | FR-045 |
| empty (filtered) | **n/a** | — | — | — |
| partial failure | **n/a** | — | — | — |

### M-12 — Onboarding

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | first review open | Three points; Day/Time rows; threshold segmented; Continue | "A weekly reset" / "It's the only thing the app moves on its own. Tasks you already have get at least 14 days." | FR-016, FR-018, FR-035 |
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
| skipped, all steps | "Skip" | Next step; rail/progress shows the step as skipped | — | FR-029 |
| offline | no connection | Identical (local) | — | FR-040 |
| loading / error / partial / filtered | **n/a** — local read-only list | — | — | — |

### M-14 — Mind sweep (full)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | step opens | Prompts, one-line capture to Inbox, list added this step | "What's on your mind? Get it out of your head. Don't sort it yet." | FR-028 |
| empty | nothing captured yet | Same screen with an empty list; "Next" finishes the step | — | FR-028, FR-029 |
| offline | no connection | Captures go to the local Inbox | — | FR-040 |
| loading / error / partial / filtered | **n/a** | — | — | — |

### M-15 — Inbox to zero

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| > 15 items | Inbox > 15 | Three choices | "Process 10 now" / "Process all 23" / "Process 10, release the rest to Someday" | FR-030, US4-2 |
| default: one at a time | processing | Existing Process inbox item view with its existing Undo toast | "Item 3 of 10" / "Is it actionable? Choose where it belongs." | FR-034 |
| empty | Inbox empty | Finishes as a step with nothing to decide | "Inbox is empty / Nothing to process." | FR-029 |
| done (with release) | queue finished | Processed and released counts | "10 items processed · 12 released to Someday / maybe" | FR-030 |
| partial failure | an item changed elsewhere | Named; stays in Inbox | ""Buy printer paper" was changed on another device, so it stayed in Inbox." | FR-011 |
| offline | no connection | Works locally | — | FR-040 |
| loading / error / filtered | **n/a** (local) | — | — | — |

### M-16 — Tasks that ask for a decision (step)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | step opens | M-03 card full-screen, "1 of 5 · oldest first", "Not now" | — | FR-034, US4-3 |
| next card | a decision made | One status line, next card | ""Update the CV" released to Someday" | FR-034 |
| all decided | queue empty | Count | "All 5 decided / Nothing in Next is waiting for a decision now." | SC-002 |
| some left | "Not now" used | Neutral count; they keep asking | "3 of 5 decided / 2 still ask for a decision. They'll be in Next whenever you're ready." | FR-029 |
| empty | nothing asks | Finishes with nothing to decide | "Nothing asks for a decision" | FR-029 |
| threshold changed mid-review | change on another device | Queue unchanged; note | "Your threshold changed to 21 days. This list stays as it is…" | FR-039, edge case |
| stale | a card's task changed elsewhere | M-03 stale pattern in place | — | FR-011 |
| offline | no connection | Works locally | — | FR-040 |
| loading / error / filtered | **n/a** (local) | — | — | — |

### M-17 — The rest of Next with capacity mirror

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | step opens | Three figures + "no limit" line + scannable list with markers | "41 next actions · 9 done per week, last 4 weeks · ~4½ weeks of work at that pace / No limit. Just a mirror…" | FR-031, US4-4 |
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
| default | step opens | One of at most 7; keep / move to Next / cancel; auto-park label where relevant | "Keep in Someday · Looks again in 30 days" | FR-032, FR-034, US4-6 |
| move to Next | "Move to Next" | Required concrete title | "What's the first concrete action?" | US4-6 |
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
| default | last step | Eight counts in fixed order (zero dimmed), next review date, optional question, Done | "Review done" / "Next review: Fri 16 Oct, 16:00" / "Clear how to start the week? optional" | FR-033, US4-9 |
| answered | Yes / Not really | Selection and a neutral acknowledgement | "Thanks. Noted for this review." | FR-033, SC-003 |
| empty | nothing changed | One calm line instead of a zero grid | "Nothing needed changing this time." | FR-033 |
| offline | completed offline | Saved locally; syncs; visible on web after sync | "Offline. This review is saved on this iPhone and syncs when you're back online." | SC-007 |
| partial failure | a decision rejected on sync | Named, Ref, counts reflect applied only | ""Book a dentist appointment" changed on another device before your decision synced…" | FR-011, FR-045 |
| loading / filtered | **n/a** | — | — | — |

### M-23 — Settings

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | Settings | Weekly review and Suggestions sections | "Last review: 9 days ago" / "Cloud suggestions · OpenAI · allowed since Sat 3 Oct" | FR-023, FR-023a, FR-024, FR-035, FR-038 |
| threshold changed | new threshold | Note with the earliest possible park date | "Markers in Next update now. Because of this change, nothing moves to Someday before Fri 16 Oct." | FR-039 |
| delete model (confirm) | Delete downloaded model | Alert stating what is freed and what changes | "Delete the downloaded model? Frees 1.1 GB…" | FR-023a |
| empty (first run) | nothing set up | Defaults; "Not yet"; "Not downloaded"; "Ask me"; consent off | "Last review: Not yet" | FR-023, FR-038 |
| revoked | toggle off | Immediate stop, note | "Cloud suggestions are off. Nothing will be sent to OpenAI." | FR-024 |
| offline | no connection | Editable; sync later; revoke effective at once | "Offline — 2 changes waiting." | FR-024, FR-040 |
| error | account rejected change | Kept locally, retried, Ref | "Your new review day couldn't be saved to your account yet." | FR-045 |
| loading / filtered / partial | **n/a** (local) | — | — | — |

### M-24 — Next actions widget

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | N > 0 tasks ask | Indigo "N ask" chip beside the count in small/medium/large | "3 ask" (VoiceOver: "3 tasks ask for a decision") | FR-037, US5-3 |
| empty | N = 0 | No chip | — | FR-037 |
| configured for Today | widget list = Today | No chip | — | FR-037 |
| error | store unreadable | Existing "Open Brain Buddy" state, unchanged | "Your lists show here once the app can read them." | — |
| offline | no connection | Identical (reads the shared local store; never syncs) | — | FR-040 |
| loading / partial / filtered | **n/a** — WidgetKit placeholder is the existing sample entry | — | — | — |

### M-25 — Weekly notification

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | chosen local day/time | One banner; tap → M-11 | "Weekly review / Your review time. The quick one takes about 5 minutes." | FR-036, US5-2 |
| permission declined | iOS permission off | Nothing sent, nothing nags (M-12 note) | — | FR-036 |
| offline | no connection | Fires anyway (local notification) | — | FR-040 |
| loading / empty / error / partial / filtered | **n/a** | — | — | — |

### D-01 — Next actions with age markers + sidebar entry (web)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | Next actions route | 44 px rows with marker chips; enabled "Weekly review" sidebar link with recap line | "Last review: 9 days ago" | FR-004, FR-010, FR-042 |
| loading | list fetch > 300 ms | Static placeholder rows | — | — |
| empty (first run) | no next actions | Existing empty state | "No next actions" | — |
| empty (filtered to nothing) | filter matches nothing | Copy + Clear filter | "No next actions tagged errands" | — |
| error | list fetch failed | Reason, Ref, Retry | "We couldn't load your next actions" + Ref | FR-045 |
| partial failure | **n/a** — one list response | — | — | — |
| offline / interrupted | offline | Banner; markers still shown; marker buttons disabled | "You're offline. Decisions need a connection. Retry when you're back online." | FR-040 |
| threshold just changed | D-04 change | One-time note | as M-01 | FR-039 |

### D-02 — Decision dialog with the AI navigator (web)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default / recommendation | opened | 560 px dialog, M-03 content, keyboard hints 1–7 | as M-03 | FR-006, FR-007 |
| third stalled wording | FR-005 | Offer above decisions | as M-03 | FR-005 |
| loading (saving) | decision clicked | Pending on the chosen row only; others disabled | "Saving…" | FR-011 |
| cloud consent | first Suggest | Consent dialog; focus starts on "Not now" | as M-07 | FR-024 |
| proposals (cloud) | allowed | M-05 layout with provider line; Save first step | "Suggested by OpenAI from this task's details." | FR-019, FR-020 |
| error: provider timeout / malformed | provider fails | Banner, Ref, Try again | as M-07 | FR-025, FR-045 |
| error: cost cap | cap reached | Banner, Ref, no retry | as M-07 | FR-025, FR-045 |
| error: save failed | decision request failed (non-stale) | Banner in the dialog, Ref, Retry; nothing changed | "Couldn't save your decision. Nothing was changed." + Ref | FR-045 |
| stale | 409/stale | Existing web heading "Task changed elsewhere"; diff; Close | "Task changed elsewhere / Nothing was applied." | FR-011 |
| offline / interrupted | offline; tab closed mid-dialog | Decisions disabled with reason; closing applies nothing | "You're offline. Decisions need a connection on the web." | FR-040 |
| empty (first run / filtered) | **n/a** | — | — | — |
| partial failure | **n/a** — single command (as M-03) | — | — | — |

### D-03 — Weekly review shell (web)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default: entry / resume | /review | Resume card first if open; Quick / Full | as M-11 | FR-027, FR-029 |
| onboarding | first time | M-12 as a dialog with selects and segmented threshold | as M-12 | FR-035 |
| While you were away | unseen parks | M-09 as a list | as M-09 | FR-015 |
| restart mode | 21+ days | M-10 with Undo | as M-10 | FR-017 |
| step with rail | any step | 240 px rail (done / skipped / current, not jumpable); single 600 px column | — | FR-028, FR-029, FR-034 |
| Waiting / capacity mirror | full steps | Wider layouts of M-17 and M-18 | as M-17, M-18 | FR-031, FR-032 |
| summary | last step | 4-column counts grid, next review, question | as M-22 | FR-033 |
| loading | route load > 300 ms | Static placeholders | — | — |
| error | review load failed | Reason, Ref, Retry; progress safe | "We couldn't load your review. Your progress is safe." | FR-045 |
| offline / interrupted | offline; tab closed | Progress saved server-side as of the last decision; Retry; resume anywhere | "You're offline. Decisions made so far are saved. Retry when you're back online, here or on another device." | FR-029, FR-040 |
| empty / partial | per-step as the matching M- screen | — | — | — |

### D-04 — Settings (web)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | settings page | Two sections; save on change | as M-23 | FR-024, FR-035, FR-038 |
| threshold changed | new value | Inline note | as M-23 | FR-039 |
| revoked | toggle off | Immediate stop, note | "Cloud suggestions are off." | FR-024 |
| empty (first run) | never reviewed, no consent | "Last review: Not yet"; toggle off | — | FR-038 |
| loading | > 300 ms | Static placeholders | — | — |
| error | save failed | Old value kept, Ref, Retry | "Your review day couldn't be saved. It's still Friday." | FR-045 |
| offline / interrupted | offline | Saving disabled; revoke still stops this tab at once | "You're offline. Changes can't be saved…" | FR-024, FR-040 |
| partial failure / filtered | **n/a** — each control saves independently | — | — | — |

## Affordance → requirement map

Existing controls that this feature leaves unchanged (filters, list rows,
completion circles, Process inbox decisions and its Undo toast, the widget's
completion buttons, project/Tag pickers) are not listed.

| screen | affordance | what it does | FR ref |
|---|---|---|---|
| M-01, D-01 | "Asks for a decision" marker button | Opens the decision card for that task | FR-004, FR-010 |
| M-01, D-01 | "Moves to Someday tomorrow" marker button | Opens the decision card | FR-004, FR-010, FR-012 |
| M-01, D-01 | "Ageing" marker (not interactive) | Shows the ageing state | FR-004 |
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
| M-03, D-02 | "Think it through" (third stall) | Opens the thinking canvas from this task | FR-005 |
| M-03, D-02 | "Release to Someday" in the third-stall offer | Same as the decision | FR-005 |
| M-03, D-02 | Close / Esc / swipe down | Closes with no change | FR-010 |
| M-03, D-02 | Stale "Close" | Dismisses after a rejected stale decision | FR-011 |
| M-03 | Error "Try again" / "Choose again" | Retries the rejected decision / reopens the choices | FR-011, FR-045 |
| D-02 | Number keys 1–7 | Keyboard shortcut for the seven decisions | FR-006 |
| M-04, D-02 | Title field + "Save new wording" / "Save anyway" | Applies a reformulation | FR-001, FR-002, FR-006 |
| M-04, D-02 | First-step field + "Save first step" | New title; old title to notes as "Was: …" | FR-008 |
| M-04 | Waiting for field + "Move to Waiting for" | Moves to Waiting with who/what | FR-006 |
| M-04 | Reason field + "Keep until <date>" (disabled until filled) | One-time extension | FR-009 |
| M-04, M-05, D-02 | Back | Returns to the card with the reason kept | FR-006 |
| M-04, D-02 | "Suggest wording" / "Suggest a first step" | Starts the navigator | FR-019 |
| M-05, M-07, M-08, D-02 | Stop | Cancels a running suggestion | FR-020 |
| M-05, M-06, M-07, M-08, D-02 | Proposal radio | Fills the field for editing | FR-020 |
| M-05, M-06, M-07, M-08, D-02 | None of these | Discards proposals, task unchanged | FR-020 |
| M-05 | Clarifying answer field + "Add to notes and suggest again" | Appends the answer to notes, re-runs | FR-021 (see Unresolved) |
| M-05 | "I'll write my own step" | Closes the question | FR-021 |
| M-05 | Try again (on-device error) | Re-runs on device | FR-022 |
| M-06 | "Download 1.1 GB" | Starts the explicit model download | FR-023, FR-023a |
| M-06 | "Continue with cloud" / "Use OpenAI in the cloud instead" | Goes to consent (M-07) | FR-023, FR-024 |
| M-06, M-07 | Not now | Closes; card usable without AI | FR-023, FR-024 |
| M-06 | Cancel download | Stops and discards the partial download | FR-023a |
| M-06 | Retry download / Try again (storage) | Retries the download | FR-023a |
| M-06 | Back to the card | Leaves the download running | FR-023a |
| M-07, D-02 | Allow and suggest | Grants one-time consent, sends the request | FR-024 |
| M-07, M-08, D-02 | Try again (cloud) | Retries after a provider failure | FR-025 |
| M-08, M-19 | "Suggest a next action" / "Suggest" | Runs the navigator for a project | FR-019 |
| M-08 | "Add to Next actions" | Creates the confirmed next action in the project | FR-020 |
| M-08 | Empty-project answer field + "Add to Next actions" | Creates the next action typed in answer to the question | FR-021 |
| M-09, D-03 | Return to Next (per row) | Returns one parked task with a fresh formulation | FR-015 |
| M-09, D-03 | Return all N / the other N | Returns every unreturned parked task | FR-015 |
| M-09, D-03 | Continue | Marks parks as seen, proceeds | FR-015 |
| M-10, D-03 | Release N to Someday | Bulk release of Next tasks older than 4 weeks | FR-017 |
| M-10, D-03 | See which ones / Hide the list | Shows what the release would move | FR-017 |
| M-10, D-03 | Keep them and start the review | Declines the offer | FR-017 |
| M-10, D-03 | Undo / Undo the N | Reverses the bulk release | FR-017 |
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
| M-16, D-03 | Not now (single card) | Leaves this task undecided and moves on | **none explicit** (see below) |
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
| M-23 | Delete downloaded model → Delete / Cancel | Removes the downloaded model | FR-023a |
| M-23, D-04 | Cloud suggestions switch | Grants (via consent) or revokes cloud consent | FR-024 |
| M-23, D-04 | Retry (settings error) | Retries saving | FR-045 |
| M-24 | "N ask" chip (not a separate tap target) | Shows the count | FR-037 |
| M-25 | Notification tap | Opens the review entry | FR-036 |

Display-only surfaces carrying requirements: "N days in Next" and help line
(M-02: FR-001, FR-003), paused line (M-02: FR-003a), parked facts (M-02, M-09,
M-20: FR-012), "Last review: N days ago" (M-11, M-23, D-01, D-04: FR-038),
onboarding promises (M-12: FR-016, FR-018), capacity mirror (M-17: FR-031),
on-device note (M-05: FR-022), correlation IDs on every failure (FR-045).

### Requirements with no affordance

- **FR-013** (auto-park idempotent, skipped after changes, no sync conflict): no UI surface (backend/behaviour). Its visible consequence is the absence of a conflict prompt (M-01 offline row).
- **FR-014** (auto-park runs without a client; on-device for account-less iOS): no UI surface (backend/behaviour).
- **FR-016** (14-day grace for pre-existing tasks): no control; stated as copy in M-12.
- **FR-018** (auto-park is the only automatic change): no control; stated as copy in M-12.
- **FR-026** (record whether an AI proposal was used): no UI surface (backend/behaviour).
- **FR-040** (iOS/web parity; iOS offline): no single affordance; satisfied by the M-/D- pairs and every screen's offline row.
- **FR-041** (Mac): no mockup by scope; the Mac shows a non-interactive "Weekly review · coming later" row until Mac sync, then follows D-01/D-02/D-03 and M-05/M-06.
- **FR-043** (storage, export, purge): no UI surface (backend/behaviour); the existing ZIP export and purge cover it without new controls.
- **FR-044** (logs and metrics content): no UI surface (backend/behaviour).

All other FR-001 … FR-045, including FR-003a and FR-023a, map to at least one
affordance or display surface above.

### Affordances with no requirement

- **"Not now" on a single decision card (M-16, D-03).** It leaves one task undecided and moves to the next card. The spec makes steps skippable (FR-029) and presents one item at a time (FR-034), but does not say an individual item can be passed over without a decision. Without it, the only way past a hard card is to skip the whole step, which drops the remaining cards. It mirrors Process inbox's existing "Skip". The plan must confirm it. Note that it interacts with SC-002: a completed review can then leave a task over the threshold undecided.

## Primary loop impact

This feature **is** the "smart Weekly Review" stage of the constitution's
primary loop (capture → atomic items → clarify/approve → route or CRT candidate
→ smart Weekly Review → evidence/results) for native tasks:

- **Capture**: the mind sweep (M-14) feeds the Inbox.
- **Clarify/approve**: the Inbox step reuses Process inbox (M-15). Reformulate and "Find a first step" (M-04, with the M-05 navigator) send stalled tasks back through clarification. Nothing AI-proposed is written without confirmation (FR-020).
- **Route / organize**: decisions move tasks to Waiting, Someday or Cancelled. Auto-park is the only automatic routing (FR-018).
- **CRT candidate**: the third-stall offer (FR-005) opens the thinking canvas from the task. This is the review's bridge to CRT.
- **Weekly Review**: M-09 … M-22 and D-03.
- **Evidence/results**: wins first (M-13), per-decision counts, and the "clear start" answer (M-22) are the review's evidence.

Voice-led review and review of agent-delegated work are out of scope.

## Mobile viability

- **Viewport**: every M- frame is drawn at 390 × 851 with no horizontal scroll. Long sheets (M-03, M-12) scroll vertically. The decision list sits in the lower half for thumb reach.
- **Tap targets**: 44 pt minimum everywhere. Reason chips and decision rows are 44–54 pt. Marker chips are about 22 pt tall but have a 44 × 44 pt hit area through an invisible inset (`button.mk::after`), and the whole row also opens the task. Widget chips are not tap targets.
- **One-handed reach**: primary actions are in the bottom bar (review steps) or the lower half of the sheet (card). "Leave" / "Skip" are at the top, deliberately harder to hit by accident.
- **Destructive actions**:
  - "Delete downloaded model" asks first: "Frees 1.1 GB. Suggestions for languages Apple's model doesn't support will need the download again, or the cloud. Your tasks aren't affected."
  - "Cancel task" has no confirmation (one or two taps per FR-006) and says "Stays findable under Cancelled".
  - Bulk release (M-10) is undoable in place.
  - "Process 10, release the rest" states "Nothing is deleted".
- **Dynamic Type**: at accessibility sizes the card's decision list scrolls with the content instead of being pinned, as Process inbox does today.
- **Reduce Motion**: card-to-card transitions in M-16 are instant. No ambient animation anywhere in this feature.

## Keyboard and focus

- **Tab order**:
  - D-01: marker buttons in row order after each row's title.
  - D-02: title → reasons → decisions → (forms) field → Suggest → proposals → Back → Save.
  - D-03: Skip step → Leave → step content → primary action. The rail is not focusable because it is not interactive.
- **Focus on open**:
  - D-02 focuses the dialog title; the consent dialog focuses "Not now".
  - D-03 focuses the step heading on every step change.
  - iOS: VoiceOver focus goes to the card title (as Process inbox does).
- **Focus restored on close to**: the marker chip or "Decide" button that opened the card. After a decision removes that row, focus goes to the next row's title.
- **Escape**: closes D-02 with no change. Inside a form it returns to the card first. In D-03, Escape closes nested dialogs only, never the review.
- **Accessible names**:
  - Marker buttons: "Asks for a decision. Open decision for <title>".
  - Widget chip: "3 tasks ask for a decision".
  - "Return to Next" rows: "Return <title> to Next".
  - Disabled archived row: "Return unavailable: project <name> is archived".
  - Close icon: "Close".
  - Settings switches name the provider.
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

## Unresolved

Spec gaps found while designing. Each one is designed conservatively as
described, and none goes beyond the spec.

1. **Clarifying-question answer path (FR-021 vs FR-019).** The navigator's input is fixed to title, notes, reason, project name and other open titles, so the spec gives no channel for an answer. The design appends the answer to the task's notes as a visible, ordinary notes edit (no clock change), then re-runs. For an empty project it skips the re-run: the answer is typed straight in as the next action. The plan or spec must confirm this.
2. **FR-030 "release the rest to Someday".** Interpreted as "process 10, then release the remaining N to Someday". Another reading is "release everything beyond 10 without processing". Needs confirmation.
3. **Undo for decision-card decisions.** The spec does not require it, so no Undo is drawn (only a confirmation toast). Process inbox and completion have Undo today. If Undo is wanted, it becomes a new affordance with no FR.
4. **Reversibility window for the restart bulk release (FR-017).** Designed as Undo on the restart screen until the person moves on, then per-task moves from Someday. The spec does not say how long "reversible" lasts.
5. **Weekly notification on web and skip rule (FR-036).** The web has no notification channel in the product today. The spec also does not say whether the week's notification is suppressed when a review already happened since the previous slot.
6. **"This week" for wins.** Interpreted as the last 7 days. The alternatives are "since the last review" and "calendar week".
7. **Restart mode for someone who set up the review 21+ days ago but never reviewed.** Copy variant needed ("since you set up the review"). FR-017's trigger for this case is ambiguous.
8. **Mac "coming later" row.** FR-041 needs a visibly deferred entry on Mac, but the Mac app has none today, so a small pre-sync Mac change is required. Separately, its existing POC "Review Waiting for" / "Review Someday" sheets overlap M-18/M-20, and their fate after Mac sync is a planning call.
9. **Design-skill deferral string** (see Design authority). The skill update and the ADR must land with or before implementation.

## Open decisions for the human

1. **Where the decision card lives on iPhone.** The design uses a large-detent sheet over Next: the list stays visible behind it, swipe down means "no change", and it matches the existing Waiting-for prompt. The alternative is a full-screen pushed view, which gives more room for the AI states and reads more like a "mode". Inside the review the card is full-screen either way (M-16).
2. **How prominent the markers are in Next.** The design shows all three non-fresh states as chips: quiet slate "Ageing", indigo "Asks for a decision", amber "Moves to Someday tomorrow". For someone with ADHD and a long Next list, many "Ageing" chips could read as nagging. Options:
   - keep as designed;
   - show "Ageing" only in task detail;
   - render "Ageing" as plain grey text with no chip.
3. **Widget layout for the count (FR-037).** The design adds an indigo "N ask" chip next to the existing count in the header of all three sizes, with no new tap target. Alternatives:
   - a second line under the count in the small widget only;
   - a dedicated small "Decisions" widget;
   - making the chip a deep link straight into the review's decision step.

Other choices made here that the owner may override without re-design:

- "While you were away" opens as a sheet on app open (not a banner).
- The reason → recommendation mapping (M-03 header).
- Indigo for "asks" and amber for "tomorrow".
- Compass as the navigator icon.
