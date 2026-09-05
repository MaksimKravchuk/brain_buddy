# Design: Transcript-first voice brain dump

**Feature**: `specs/015-transcript-first-brain-dump/`
**Spec**: `spec.md` (Clarifications settled: 2026-09-05)
**Screens**: `design/*.html` — open `design/index.html` first
**Human sign-off**: waived by the founder («просто доделай», recorded in `intake.md`). The
decisions a person would otherwise have made are listed under
[Open decisions for the human](#open-decisions-for-the-human). Five of the six the
first pass left there have since been answered in code, and the FR-006-on-mobile
question it raised separately was answered by a scope decision in `spec.md`; each is
recorded under [Closed since the first pass](#closed-since-the-first-pass) with the
behaviour or the decision that answered it.

<!--
  Retro design. The screens in this document already ship on branch
  claude/brain-dump-mechanics-t35ab7 (PR #194). Copy is quoted from
  frontend/src/features/brain-dump/BrainDumpRoute.tsx and
  mobile/src/app/brain-dump/[operationId].tsx as delivered; where a shipped
  screen does not satisfy a requirement the divergence is recorded as a
  finding rather than designed away.

  Revision, 2026-09-05 (second pass). Findings of the first pass were fixed in
  code and spec.md was amended to match. In code: the three mobile destructive
  exits now confirm through the platform dialog and the two misnamed mobile
  controls were renamed (FR-007, SC-004 now web 4 of 4 and mobile 3 of 3); the
  mobile empty review says nothing was proposed, shows what was heard and drops
  its confirm control (FR-005); every web banner prints the server's reason and
  the request's reference id (FR-009); the web empty review names the exit it
  actually has; and the web review says in words why Send is disabled with an
  open conflict. By decision rather than code: FR-006 is web-only, so the mobile
  processing screen's missing transcript and cancel are a recorded deferral
  rather than a defect. New states: M-01.f, M-02.i. Revised: M-02.e. Ids already
  written were not renumbered; the inventory grew from 55 states to 57.

  ADR-0006: the term is Tag. The two retired synonyms it replaced are forbidden
  strings and the design CI validator hard-fails on them, so they appear
  nowhere in this document or in design/.
-->

## Applicability

This feature has a user-visible surface, designed below. It is the whole of the
web brain-dump overlay (recording, processing, review, recovery, loading) plus
the Expo brain-dump operation screen. Mobile *capture*
(`mobile/src/app/brain-dump/index.tsx`) is unchanged by this feature and is
deliberately outside the inventory: mobile has no browser-preview lane and this
feature adds no capture behaviour to it.

**Authority applied, in order:** ADR-0006 (`Tag` is canonical; neither retired
synonym appears in this document or in `design/`), the ADR-0002
amendment of 2026-09-05 (browser preview is a transcript readout, not a task
source; `reconcile_preview` is the one owner-chosen recovery), the
`brain-buddy-design` skill for colors, type, radii, shadows and voice, and
constitution Principle V for the mobile-first primary loop.
`docs/vnext-cloud-design-build-contract.md` was not used as a vocabulary source.

## Screen inventory

| id | surface | screen | purpose | FR refs |
|---|---|---|---|---|
| D-01 | web (390 primary, ≥640 two-pane) | Recording | Show what has been heard as a status — settled utterances in a labelled readout, the forming hypothesis beside the microphone — while capture runs, and expose Pause/Resume, Stop and a confirmed Discard | FR-001, FR-002, FR-007, FR-008 |
| D-02 | web (390 primary, ≥640 narrow dialog) | Processing | Name the stage in plain words, keep the transcript readable, and offer one confirmed exit while the server works | FR-002, FR-006, FR-007, FR-010 |
| D-03 | web (390 primary, ≥640 wide dialog) | Review | Review clean next actions, edit or delete them, save them to Inbox, or leave with nothing saved; refuse to save a review with no surviving task | FR-003, FR-004, FR-005, FR-007, FR-010, FR-011 |
| D-04 | web (390 primary, ≥640 narrow dialog) | Recovery (failure) | Offer the exits a failed recording actually has: retry, review provisional, the one-shot browser-transcript extraction, or a confirmed delete | FR-007, FR-009, FR-010 |
| D-05 | web (390 primary, ≥640 narrow dialog) | Loading | Say the recording is being fetched instead of flashing the wrong surface when a persisted recording is opened cold | FR-008 |
| M-01 | mobile (Expo, 390×851) | Recovery (failure) | Render the same server-advertised recovery actions on the phone, including the browser-transcript extraction for a recording started on the web, and confirm before the one exit that destroys the recording | FR-007, FR-009, FR-010 |
| M-02 | mobile (Expo, 390×851) | Review | Review and confirm on the phone, with the provisional label on every provisional result, an honest empty review, and a confirmation on both discard paths | FR-005, FR-007, FR-010, FR-011 |
| M-03 | mobile (Expo, 390×851) | Loading and processing | Cover the first fetch, the server-side stages and a failed load | FR-006 (mobile clause: names the stage), FR-008 (poll/resume half) |

`design/index.html` is a contact sheet, not a screen: it carries no id and no
requirement.

## State inventory

Ids are stable forever. `D-01.a` … `M-03.c` are what the acceptance
traceability matrix keys off.

### D-01 — Recording (`design/D-01-recording.html`)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| D-01.a default (ready, first run) | `/brain-dump/new` opened, provider discovery resolved | Idle microphone, "Ready" with no timer, dashed empty readout, pre-flight card (speech languages, key terms, consent), enabled Record, ghost Discard. Zero task cards | "Brain dump" · "Speak freely — tasks are proposed after you stop" · "Transcript preview appears while you talk" · "Browser preview · provisional" · "Your words appear here as you speak. Tasks are proposed after you stop." · "Allow secure cloud processing: speech-to-text by {vendor}, task extraction by {vendor}. Audio is not sent without this consent." · "Nothing is saved until you stop" | FR-001, SC-002 |
| D-01.b loading | `GET /api/brain-dump-providers` unresolved | Pre-flight card with a status line instead of the consent control; Record disabled; no microphone touched | "Checking configured providers…" | FR-001 |
| D-01.c empty (first run) | Record pressed; first hypothesis still forming | Live microphone, "Recording 0:03", the forming hypothesis beside the microphone, dashed empty readout | "Your words appear here as you speak. Tasks are proposed after you stop." | FR-001, SC-002 |
| D-01.d default (recording) | The reference utterance is being spoken | Two settled utterances in the readout, the third still a hypothesis beside the microphone with a blinking caret, live waveform, "Recording 0:18", Stop & review / Pause / Discard / Stop cloud processing. **Zero task cards** | "What you've said · browser preview" · «Так, надо купить молоко.» «Сходить в магазин.» · tail «Покрасить комн» | FR-001, FR-002, SC-002 |
| D-01.e paused | Pause pressed | Idle microphone and still waveform, "Paused 0:18" frozen at the captured duration, Resume replaces Pause | "Paused" | FR-008 |
| D-01.f offline / interrupted (resume) | Page reloaded or app reopened mid-recording | On the **first** render: the last utterance the server holds sits beside the microphone, the timer reads the captured audio duration with pauses excluded, the readout carries every settled utterance. No task cards | tail «Покрасить комнату.» · "Recording 0:42" | FR-008, SC-005 |
| D-01.g destructive confirmation | Discard pressed | The question replaces its own trigger in place; focus on the safe answer (drawn with the double focus ring); recording continues untouched | "Discard this recording? The audio and transcript are deleted and nothing is saved." / "Keep recording" / "Discard recording" | FR-007, SC-004 |
| D-01.h partial failure (consent withdrawn mid-capture) | "Stop cloud processing" pressed | Microphone, recognizer and pending uploads stopped locally before the server round trip; the state chip replaces Pause/Resume; timer gone; Stop & review and Discard remain | "Cloud processing stopped" | FR-001 (inherited consent constraint) |
| D-01.i error | Provider discovery failed, or named no accurate-STT vendor | Fail-closed amber alert in place of the consent control, Record disabled, in-place Retry | "Could not load the configured voice providers, so recording is unavailable. No audio leaves this device until the vendors are confirmed." / "Retry" | FR-001 (inherited consent constraint) |
| D-01.j partial failure (upload) | One audio chunk or transcript append rejected | Rose banner above the readout; the utterances that did land stay readable; capture keeps running; Stop & review and Discard stay reachable | The server's reason then the reference id — "Transcript can only be appended while recording or paused. Ref: corr-9f3c1d2a-…"; the bare sentences "Original audio upload failed." / "Transcript upload failed." are the fallback for a throw carrying no server answer | FR-002 |
| empty (filtered to nothing) | — | Not applicable: the readout has no filter. The *unfiltered* empty case is D-01.c | — | — |

### D-02 — Processing (`design/D-02-processing.html`)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| D-02.a loading | Stop & review pressed | Stage title and machine status, the browser-preview transcript still readable, cancel offered. The stage appears immediately — there is no spinner-only interval | "Sealing audio" · "Sealing audio. Your tasks appear for review once the accurate transcript has been turned into next actions." | FR-006 |
| D-02.b default (transcribing) | Accurate speech-to-text running | Same shape, readout labelled as the browser preview so it can never be mistaken for the accurate transcript. No task cards | "Improving transcript" · "Browser preview · provisional" | FR-006, FR-010, SC-002 |
| D-02.c default (reconciling) | Accurate transcription succeeded | Accurate utterances supersede the preview ones and the readout relabels itself | "Reconciling tasks" · "Accurate transcript" | FR-006, FR-010 |
| D-02.d empty (first run) | Browser with no speech preview, or no settled preview segment | Dashed readout that promises no preview | "The transcript appears here once processing catches up." | FR-006 |
| D-02.e error | A cancel or retry command was refused | Rose banner above the status line; the stage keeps advancing; nothing is destroyed | The server's reason then the reference id — "Brain dump operation 'op_9f31' has newer changes; reload before saving. Ref: corr-9f3c1d2a-…" — never the HTTP status text | FR-006 |
| D-02.f destructive confirmation | Cancel processing pressed | The question replaces its trigger; focus on the safe answer; processing continues undisturbed on the server while it is open | "Cancel processing? The recording and its transcript are discarded and no tasks are created." / "Keep processing" / "Cancel processing" | FR-007, SC-004 |
| D-02.g offline / interrupted | Panel closed, device offline, or app backgrounded | Processing continued server-side; reopening `/brain-dump/{id}` resumes on whatever stage the server reached; the poll backs off 1.5 s → 8 s. No leave-and-return control exists, by decision | "Processing continues on the server while this panel is open." · "Saving tasks" | FR-006 |
| empty (filtered to nothing) | — | Not applicable | — | — |
| partial failure | — | Covered by D-02.e; a stage failure leaves the processing surface for D-04 | — | — |

### D-03 — Review (`design/D-03-review.html`)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| D-03.a default (committable) | Reconciliation over the accurate transcript finished | Exactly three next-action cards, each with an Inbox pill, a status pill and the utterances it cites; the raw-audio retention row; Send enabled with nothing deleted | "Review 3 tasks" · "Edit before they land in your inbox" · «Купить молоко» «Сходить в магазин» «Покрасить комнату» · "Cited from what you said" · "Send 3 to inbox" · "Discard all" · "Raw audio is retained until {date}." / "Delete audio now" | FR-003, FR-005, SC-001 |
| D-03.b default (folded duplicate) | The same action was restated | One task survives; its citation block carries the evidence of both utterances | "Cited from what you said" with two quoted utterances | FR-004 |
| D-03.c default (editing) | Title field focused | Sky 1.5 px border on the field; the change commits on blur and the status pill becomes "Edited" | "Edited" | FR-003 |
| D-03.d provisional (saveable) | The browser-transcript extraction succeeded (`reconciliation_quality = provisional_only`) | Amber banner above the cards; Send enabled | "These tasks were extracted from the browser transcript, not from accurate audio. Review them carefully before saving." | FR-009, FR-010, SC-006, SC-007 |
| D-03.e provisional (not saveable) | Provisional drafts the server has not cleared for commit | Same banner plus the reason; Send disabled. The two banners never stack | …"They can be edited or discarded, but cannot be saved to Inbox until the server confirms reconciliation." | FR-010, SC-007 |
| D-03.f partial failure (not reconciled) | Legacy recording, or a finish taken without external-processing consent | Amber banner; editing and deleting work; Send disabled | "These are not yet reconciled drafts. They can be edited or discarded, but cannot be saved to Inbox until the server confirms reconciliation." | FR-011 |
| D-03.g partial failure (conflict) | A re-proposed title clashes with one the owner edited | The conflicting card takes an amber border and an inline conflict block; the other cards are untouched; Send disabled, and a live `role="status"` line under it says why — the button points at that line with `aria-describedby`, so the reason is not carried by dimming alone | "Conflict: title" · "Mine: …" · "Suggestion: …" · "Keep mine" / "Use suggestion" · "Resolve 1 conflict before sending." / "Resolve N conflicts before sending." | FR-011 |
| D-03.h empty (first run) | Filler-only dump — every candidate title carried no action or object | "No tasks to review", a status box, the transcript of what was heard. **No Send button exists** — not a disabled one. The copy names the exit the screen actually has: discard, which returns the owner to a fresh recording | "No tasks to review" · "Nothing actionable came out of this dump" · "No tasks were proposed from this dump. Here is what was heard; discard it to record again." · empty readout: "No transcript was captured for this recording." | FR-004, FR-005, SC-003 |
| D-03.i empty (filtered to nothing) | The owner deleted every proposed task | Identical surface, different history: the transcript still shows what was heard and Send is gone rather than disabled. A deleted task is never revived under a punctuation variant | as D-03.h | FR-004, FR-005, SC-003 |
| D-03.j loading (saving) | Send pressed | The button reads "Sending…" and is inert; a second press cannot start a second commit; a retried request is idempotent | "Sending…" | FR-005 |
| D-03.k saved | Commit succeeded | Narrow panel; the only dismissible screen in the flow; each saved task records whether it came from the accurate or the browser transcript | "Saved 3 tasks to Inbox" · "No duplicate tasks are created if this save is retried." · "View inbox" | FR-005, FR-010, SC-001 |
| D-03.l destructive confirmation | Discard all pressed | The question replaces its trigger in the footer; focus on the safe answer; nothing saved and nothing deleted until the explicit confirm | "Discard all tasks? Nothing is saved to Inbox and the recording is deleted." / "Keep reviewing" / "Discard all tasks" | FR-007, SC-004 |
| D-03.m error (stale screen) | The recording was saved or discarded in another tab | Rose banner; the command applies to the recording's current state — saved Inbox tasks are never removed, an already-discarded recording reports as discarded — and the question closes rather than sitting over the error | The server's reason then the reference id — "Brain dump operation 'op_9f31' has newer changes; reload before saving. Ref: corr-9f3c1d2a-…" — never the HTTP status text. The same banner reports a failed edit, delete, conflict resolution and save | FR-007 |
| loading (fetch) | — | Not applicable here: a cold open of `/brain-dump/{id}/review` renders D-05 first | — | FR-008 |
| offline / interrupted | — | The review is server-held; reopening the URL re-renders the same review from D-05 | — | FR-008 |

### D-04 — Recovery, failure (`design/D-04-recovery.html`)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| D-04.a default (retryable, STT) | Retryable speech-to-text failure, audio intact | Stage-named title, the provider's reason, a primary retry that re-reads the sealed recording, and a confirmed delete | "Accurate transcription paused" · "The transcription provider can be retried from the sealed recording." · "Retry accurate transcription" · "Delete recording" | FR-007 |
| D-04.b default (retryable, reconciler) | Retryable task-extraction failure, accurate transcript stands | Retry over the accurate transcript. No browser-transcript recovery while a better source exists | "Task reconciliation paused" · "The task reconciler can be retried from the accurate transcript." · "Retry task reconciliation" | FR-007, FR-009 |
| D-04.c partial failure (terminal, proposals survived) | Terminal failure with undeleted proposals | "Review provisional tasks" opens the normal review, labelled provisional. Mutually exclusive with the browser-transcript recovery | "Task reconciliation failed" · "Review provisional tasks" | FR-010 |
| D-04.d default (terminal, recovery offered) | Terminal failure, no surviving task, ≥1 settled browser-preview utterance, consent standing, spend ceiling not reached | One extra action with a helper sentence naming the destination; one attempt per recording; never chosen automatically | "Accurate transcription failed" · "Extract tasks from the browser transcript" · "Sends the browser transcript to the consented task-extraction provider. The result is provisional and is reviewed before anything is saved." | FR-009, SC-006 |
| D-04.e empty (no recovery available) | No browser transcript; or consent withdrawn; or spend ceiling reached; or the one attempt already spent, success or failure | Delete is the only exit; the recovery is not offered again | "Delete recording" | FR-009 |
| D-04.f destructive confirmation | Delete recording pressed | The question replaces its trigger; audio and transcript are removed only after the explicit confirm | "Delete this recording? Its audio and transcript are removed and nothing is saved." / "Keep recording" / "Delete recording permanently" | FR-007, SC-004 |
| D-04.g error (refusal) | The recovery was requested anyway after withdrawal, or over the ceiling, or a second time | Refused before any external call; a second line above the actions; delete remains | The server's refusal in words then the reference id: "RECONCILER_CONSENT_REQUIRED: external-processing consent naming the configured task reconciler is required before preview text may leave the device. Ref: corr-9f3c1d2a-…" · "OPERATION_COST_BUDGET_EXCEEDED: this recording has no cost budget left for another reconciler call." · "BRAIN_DUMP_PREVIEW_RECOVERY_UNAVAILABLE: …" — never a bare status word | FR-009, SC-006 |
| loading | — | Not applicable: this surface is only reached with a resolved failure status | — | — |
| offline / interrupted | — | The failure is server-held; reopening `/brain-dump/{id}` re-renders this surface from D-05 | — | FR-008 |

### D-05 — Loading (`design/D-05-loading.html`)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| D-05.a loading | `/brain-dump/{id}` or `/review` opened cold — reload, shared link, or app reopened | A named loading panel rather than a flash of Record or an empty review; hands off to D-01, D-02, D-03 or D-04 by status | "Loading your brain dump" · "Fetching the recording and anything already proposed from it…" | FR-008, SC-005 |
| D-05.b error | The fetch failed | The route falls through to the recording surface carrying the error, so the owner is not stranded on a spinner. Nothing has been destroyed | "Could not resume brain dump." | FR-008 |
| every other state | — | Not applicable: this surface exists only until the recording arrives | — | — |

### M-01 — Mobile recovery, failure (`design/M-01-mobile-recovery.html`)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| M-01.a default (retryable) | Retryable provider failure on a recording opened on the phone | Rose card with the stage-agnostic title and the provider's reason, primary retry, ghost discard. "Discard everything" raises M-01.f, never a one-tap delete | "Processing hit a snag" · "Try again" · "Discard everything" | FR-007, FR-009 |
| M-01.b partial failure (terminal, proposals survived) | Terminal failure with undeleted proposals | Secondary "Review provisional tasks"; the server decides which recoveries appear, so mobile renders exactly what the web renders | "Couldn't finish" · "The audio was kept — choose one of the options below, or discard everything." · "Review provisional tasks" | FR-009, FR-010 |
| M-01.c default (terminal, recovery offered) | A recording **started on the web** and reopened here after a terminal failure | The same action and the same helper sentence as D-04.d. Mobile has no preview lane, so this can only be text the server already holds | "Extract tasks from the browser transcript" · "Sends the browser transcript to the consented task-extraction provider. The result is provisional and is reviewed before anything is saved." | FR-009, SC-006 |
| M-01.d empty (no recovery available) | Mobile-only capture; or the recovery already used; or consent withdrawn; or the spend ceiling reached | Discard is the only exit, and it asks first (M-01.f) | "Discard everything" | FR-007, FR-009 |
| M-01.e error (refusal) | A recovery command was refused | The server message plus the correlation reference, above the remaining actions | server message · "ref: {correlation id}" — the same two facts the web now prints, in a lower-case `ref:` rather than the web's `Ref:` | FR-009 |
| M-01.f destructive confirmation | "Discard everything" pressed | The platform dialog over the failure screen; the safe answer is the `cancel` one and the destructive answer is the only path to `cancel`; the Android back gesture and a tap outside both keep everything (`cancelable: true`). The screen underneath is untouched while it is open | "Discard this recording?" / "The audio and transcript are deleted and nothing is saved." / "Keep" · "Discard recording" | FR-007, SC-004 |
| loading | — | Rendered by M-03.a | — | — |
| offline / interrupted | — | The poll pauses when the app backgrounds and refreshes on return (M-03.b) | — | FR-008 |

### M-02 — Mobile review (`design/M-02-mobile-review.html`)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| M-02.a default (accurate, committable) | A reconciled recording opened on the phone | Pane head, a header control named for what it does, editable cards, the raw-audio row, a sticky confirm sheet | "Review 3 tasks" · "Edit before they land in your inbox. Nothing is saved until you confirm." · "Confirm 3 additions" · "Discard all" · header control accessible name "Discard recording" (Trash2) · "Recording kept until {date}" / visible "Delete now", accessible name "Delete retained audio" | FR-003, FR-005, FR-007 |
| M-02.b provisional (saveable) | `reconciliation_quality = provisional_only` | The amber badge above the cards | "Provisional only — the accurate transcript wasn't available, so these come from the live preview. Review them carefully." | FR-010, SC-007 |
| M-02.c provisional (not saveable) | The server has not cleared the drafts for commit | The badge is present whether or not the result can be saved; Confirm is inert | as M-02.b | FR-010, SC-007 |
| M-02.d partial failure (conflict) | A re-proposed title clashes with one the owner edited | Amber card, an inline suggestion with two answers, and a count of what is outstanding. The web now carries the same line (D-03.g), worded "… before sending." | "Needs a decision" · "Suggested title: …" · "Keep mine" / "Use suggestion" · "Resolve 1 conflict before confirming." | FR-011 |
| M-02.e empty | `awaiting_confirmation` with zero active proposals — a filler-only dump, or every task deleted | It stops counting tasks it does not have: the heading is "No tasks to review" and the meta line replaces the edit instruction. One card states nothing was proposed and names the exit; a "What was heard" list follows, holding the stable segments no later segment supersedes (`heardTranscript` — the same projection the web readout uses, so an interim hypothesis and a superseded preview line are both left out). **Confirm is absent, not disabled**; "Discard all" stays and still asks (M-02.i) | "No tasks to review" · "Nothing actionable came out of this dump" · "No tasks were proposed from this dump. Discard it to record again." · "What was heard" · with no such segment: "No transcript was captured for this recording." | FR-005, SC-003 |
| M-02.f loading (saving) | Confirm pressed | Spinner inside the button; all three controls inert — Confirm, "Discard all" and the header's "Discard recording" — so a destructive tap cannot race a commit already on the wire | — | FR-005, FR-007 |
| M-02.g settled (saved) | Commit succeeded, or a completed recording opened cold | Display-size confirmation and a single exit | "Saved 3 to inbox" · "Clarify them into next actions when you're ready." · "Done" | FR-005 |
| M-02.h settled (discarded) | A cancelled recording opened cold | The outcome is confirmed rather than reported as an error | "Dump discarded" · "Nothing was saved and the recording was deleted." · "Done" | FR-007 |
| M-02.i destructive confirmation | Either discard path — "Discard all" in the sheet or the header's "Discard recording" | One platform dialog for both, because both run the same `cancel` and the reviewed tasks go with the recording. The review underneath is untouched, nothing is posted until the destructive answer, and the safe answer, the Android back gesture and a tap outside all return to the review with every edit intact | "Discard all tasks?" / "Nothing is saved to Inbox and the recording is deleted." / "Keep reviewing" · "Discard all tasks" | FR-007, SC-004 |
| error | — | An action failure renders the same banner shape as M-01.e above the list | server message · "ref: {correlation id}" | — |
| offline / interrupted | — | The poll pauses on background and refreshes on return; edits are serialized so each PATCH carries the revision the previous one produced | — | FR-008 |

### M-03 — Mobile loading and processing (`design/M-03-mobile-loading-processing.html`)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| M-03.a loading | The screen mounted; the first fetch is in flight | A spinner only — no title and no status text, where D-05.a names what it is fetching. No requirement asks for the title, so the divergence is a judgement call, listed below | — | FR-008 |
| M-03.b default (processing) | The recording is in a stage that advances without the client | Spinner, the stage in plain words, and a reassurance line. No transcript readout and no "Cancel processing" — **by decision, not by defect**: FR-006 binds the web processing screen, and mobile's transcript and cancel are recorded in the spec's Out of Scope and Clarifications of 2026-09-05. Cancelling stays reachable on the phone from M-02.i and M-01.f | "Finishing upload…" / "Catching up on your audio…" / "Improving transcript…" / "Reconciling tasks…" / "Saving to inbox…" · "You can keep the app open — this usually takes a few seconds." | FR-006 (mobile clause: names the stage) |
| M-03.c error | The fetch failed | The server message, the correlation reference, and an in-place Retry. Nothing is destroyed | server message · "ref: {correlation id}" · "Retry" | FR-008 |
| empty / partial failure / destructive | — | Not applicable: this surface is pre-interactive | — | — |

## Affordance → requirement map

Regions are included where the requirement's subject is a display rather than a
control; they are marked *(region)*.

| screen | affordance | what it does | FR ref |
|---|---|---|---|
| D-01 | Transcript readout *(region)* — "What you've said · browser preview" | Shows each settled utterance once, in spoken order, superseded ones dropped | FR-001, FR-002 |
| D-01 | Live tail beside the microphone *(region)* | Shows the still-forming hypothesis, with a blinking caret; never persisted as a task | FR-001 |
| D-01 | Absence of any task card before Stop *(region)* | The designed absence that SC-002 measures | FR-001, FR-002 |
| D-01 | "Browser preview · provisional" label *(region)* | Names the readout's source so preview text is never read as accurate | FR-002, FR-010 |
| D-01 | Record | Starts capture; enabled only once the configured vendors are named | FR-001 |
| D-01 | Stop & review | Ends capture and seals the audio; the only path to task extraction | FR-003 |
| D-01 | Pause / Resume | Suspends and resumes capture; the timer holds while paused | FR-008 |
| D-01 | Timer *(region)* | Counts the captured audio duration, pauses excluded; seeded from the server on resume | FR-008 |
| D-01 | Discard → "Keep recording" / "Discard recording" | Destroys the recording only after an explicit second confirmation, focus on the safe choice | FR-007 |
| D-02 | Stage title and status line *(region)* | Names the current stage in plain words | FR-006 |
| D-02 | Transcript readout *(region)* | Shows the transcript so far and relabels itself when accurate utterances supersede the preview | FR-006, FR-010 |
| D-02 | Cancel processing → "Keep processing" / "Cancel processing" | Cancels only after an explicit second confirmation; processing continues while the question is open | FR-006, FR-007 |
| D-03 | Next-action cards *(region)* | One card per distinct action, verb first, in the language spoken | FR-003 |
| D-03 | "Cited from what you said" block *(region)* | Shows the utterances each task is grounded in, including both utterances of a folded duplicate | FR-004 |
| D-03 | Title field | Edits a proposed title; commits on blur; marks the proposal as the owner's | FR-003, FR-011 |
| D-03 | Delete (X) on a card | Removes a proposal from the review; the deletion is not undone by a punctuation variant | FR-004, FR-005 |
| D-03 | "Send N to inbox" | Saves the reviewed tasks; enabled with zero manual cleanup on a fresh accurate result; absent when no task survives | FR-005 |
| D-03 | Empty-review status box and transcript *(region)* | States that nothing was proposed and shows what was heard, in place of an empty save | FR-005 |
| D-03 | Provisional banner *(region)* | Labels a browser-transcript result wherever it is shown, saveable or not | FR-010 |
| D-03 | Not-reconciled banner *(region)* | Keeps today's rules for pre-existing provisional proposals: edit or delete before saving | FR-011 |
| D-03 | "Keep mine" / "Use suggestion" | Resolves a conflict on a pre-existing proposal; Send stays disabled until every conflict is answered | FR-011 |
| D-03 | Conflict-count status line under Send *(region)* — "Resolve N conflicts before sending." | Says in words why Send is inert while a conflict is open, and is bound to the button with `aria-describedby` so the reason is not carried by dimming alone | FR-011 |
| D-03 | "Discard all" → "Keep reviewing" / "Discard all tasks" | Destroys the review and the recording only after an explicit second confirmation | FR-007 |
| D-03 | Saved panel *(region)* | Confirms the count actually saved and that a retried save creates no duplicate | FR-005 |
| D-04 | "Retry accurate transcription" / "Retry task reconciliation" | Re-runs the failed stage from the sealed audio or the accurate transcript — never from preview text | FR-009 (the rule it preserves) |
| D-04 | "Review provisional tasks" | Opens the normal review for surviving proposals, labelled provisional | FR-010 |
| D-04 | "Extract tasks from the browser transcript" + helper sentence | The one owner-chosen, one-per-recording, consent- and ceiling-bounded recovery; the point of choice names where the text is sent | FR-009 |
| D-04 | Absence of that action *(region)* | The designed absence after withdrawal, over the ceiling, or once the attempt is spent | FR-009 |
| D-04 | "Delete recording" → "Keep recording" / "Delete recording permanently" | Removes audio and transcript only after an explicit second confirmation | FR-007 |
| D-01–D-05 | Error banner *(region)* — the server's reason then "Ref: {correlation id}" | States why a request was refused in the server's own words with the id the owner can quote, on every web brain-dump surface; a refused recovery is the case FR-009 names | FR-009 |
| D-05 | Named loading panel *(region)* | Says the recording is being fetched instead of guessing a surface | FR-008 |
| M-01 | "Try again" | Retries the failed stage the server says is retryable | FR-009 (the rule it preserves) |
| M-01 | "Review provisional tasks" | Opens the provisional review on the phone | FR-010 |
| M-01 | "Extract tasks from the browser transcript" + helper sentence | Renders the recovery when the server advertises it, with the same copy as the web | FR-009 |
| M-01 | "Discard everything" → platform dialog "Keep" / "Discard recording" | Destroys the recording only after the destructive answer; the safe answer is the platform's `cancel`, and a back gesture or an outside tap keeps everything | FR-007 |
| M-01/M-02 | Error banner *(region)* — server message + "ref: {correlation id}" | States a refusal's reason and its reference on the phone, as the web banner does | FR-009 |
| M-02 | "Provisional only —" badge *(region)* | Labels a provisional result on mobile, saveable or not | FR-010 |
| M-02 | Title field / remove (X) on a card | Edits or removes a proposal, serialized against the recording revision | FR-003, FR-005, FR-011 |
| M-02 | "Confirm N additions" | Saves the reviewed tasks; inert while a conflict is open or the drafts are not cleared | FR-005 |
| M-02 | "Keep mine" / "Use suggestion" and the outstanding-conflict count | Resolves a conflict and says how many remain | FR-011 |
| M-02 | Empty-review card and the "What was heard" list *(region)* | States that nothing was proposed and shows the stable, non-superseded segments, in place of counting tasks that do not exist; the confirm control is absent rather than disabled | FR-005 |
| M-02 | "Discard all" → platform dialog "Keep reviewing" / "Discard all tasks" | Destroys the review and the recording only after the destructive answer | FR-007 |
| M-02 | Header control, accessible name "Discard recording" (Trash2) | The review's second discard path, named for what it does rather than for a dismissal, disabled while a command is pending, and confirmed through the same dialog | FR-007 |
| M-02 | Retained-audio control, visible "Delete now", accessible name "Delete retained audio" | Deletes only the retained raw audio and says so, so it cannot be read as deleting the recording | FR-007 (its last sentence) |
| M-03 | Stage label *(region)* | Names the current stage in plain words on the phone | FR-006 |

### Requirements with no affordance

- **FR-004, second sentence** — "Dropped items MUST be recorded by reason, never
  by content." Deliberately has no UI: it is an observability record on the
  recording, and rendering it would put transcript text back on screen. The
  owner-visible half of FR-004 (folded duplicates keep the evidence of both
  utterances) is the D-03 citation block. **No action needed.**
- **FR-006 on the mobile processing screen (M-03.b)** — kept here only because
  the first pass listed it as a gap. It is **not** a requirement without an
  affordance: FR-006's second sentence makes the transcript readout and "Cancel
  processing" a web requirement, and the clause that does bind mobile — the
  screen names the stage — is the M-03 stage label in the map above. The absence
  is a **recorded scope decision**: `spec.md` Out of Scope lists "a transcript
  readout and a 'Cancel processing' affordance on the mobile processing screen",
  and the Clarifications of 2026-09-05 name who decided it and why (half-building
  it was the worse option). Cancelling stays reachable on the phone from M-02.i
  and M-01.f. Whether the deferral is the right call is question 1 under *Open decisions for the human*.

Every other functional requirement has at least one affordance in the map above.
FR-001, FR-002, FR-003, FR-005, FR-006, FR-007, FR-008, FR-009, FR-010 and
FR-011 are each covered on every surface that renders them.

### Affordances with no requirement

**None.** Every control and labelled region in the map above traces to an
`FR-###`. The list below is the inherited furniture the screens carry, each
named with the record it comes from; none of it is new in this feature and none
of it is unaccounted for.

- D-01 pre-flight: **Speech languages**, **Key terms**, the **cloud-processing
  consent** checkbox, **Record**, the ready-state **Discard** (dismiss) and the
  **Close brain dump** X — inherited capture and consent affordances
  (`002-async-voice-workflows`, ADR-0002).
- D-01 **Stop cloud processing** and the "Cloud processing stopped" chip —
  inherited consent-withdrawal path (ADR-0002: withdrawal is not cancel).
- D-01/D-02 **waveform** and **pulsing microphone** — ambient capture feedback
  from the `brain-buddy-design` skill; no requirement, no state.
- D-03 **raw-audio retention row** and **"Delete audio now"**, M-02 "Recording
  kept until…" / **"Delete now"** — inherited retention controls
  (`docs/data-retention.md`); this feature adds no durable record of a new kind.
  M-02's is the one this feature touched, and only to name it: FR-007's last
  sentence is why its accessible name is now "Delete retained audio".
- D-03 **back arrow**, D-03.k **"View inbox"**, M-02.g/h **"Done"** — navigation.
- M-03.c **"Retry"** on a failed load — inherited error recovery.

The two naming defects the first pass listed here — a mobile control named
"Close" that discarded the recording, and a mobile control named "Delete
recording" that deleted only retained audio — are gone. Both are now named for
what they do and both appear in the map above under FR-007.

### Closed since the first pass

Kept here because the plan and the acceptance auditor cite these ids; each names
the behaviour that closed it.

- **FR-007 on mobile — closed.** All three mobile destructive exits now confirm
  through the platform dialog (`Alert.alert`, safe answer first with
  `style: "cancel"`, destructive second, `cancelable: true`): M-01.f for
  "Discard everything", M-02.i for both "Discard all" and the review header
  control. The header control is renamed from "Close" to **"Discard recording"**
  with a Trash2 icon and is disabled while a command is pending, and the
  retained-audio control's accessible name is **"Delete retained audio"** against
  its visible "Delete now". SC-004 now counts web 4 of 4 and mobile 3 of 3, and
  `spec.md` FR-007 binds both clients including the naming rules.
- **FR-005 on the mobile empty review (M-02.e) — closed.** The screen no longer
  counts tasks it does not have: heading "No tasks to review", meta "Nothing
  actionable came out of this dump", the card copy names the exit, the confirm
  control is **absent rather than disabled**, and a "What was heard" list shows
  the stable non-superseded segments (or says none were captured). It matches
  D-03.h/D-03.i on every point but the last clause of one sentence.
- **FR-009's "state its reason" on the web — closed.** Every web banner is built
  by one `describeError`, which prints the server's own reason and then
  `Ref: {correlation id}` — for example "RECONCILER_CONSENT_REQUIRED:
  external-processing consent naming the configured task reconciler is required
  before preview text may leave the device. Ref: corr-…". The bare HTTP status
  text ("Conflict", "Forbidden") no longer reaches any of D-01.j, D-02.e,
  D-03.m, D-04.g or D-05.b.
- **FR-005's "record again" copy on D-03.h/D-03.i — closed by copy, not by a new
  control.** The line now reads "…discard it **to** record again", which is what
  the screen offers: discarding an `awaiting_confirmation` recording returns the
  owner to a fresh recording. No control was added, and the copy no longer
  promises one.
- **The reason Send is disabled with an open conflict (D-03.g) — closed.** A
  live `role="status"` line under the button reads "Resolve N conflicts before
  sending.", and the button names it with `aria-describedby`. Disabled state is
  no longer communicated by dimming alone on any web surface.
- **Whether FR-006 binds mobile — closed by decision, not by code.** FR-006's
  second sentence now reads "The mobile processing screen names the stage
  (existing behaviour); its transcript readout and cancel affordance are out of
  scope here", `spec.md` Out of Scope repeats it, and the Clarifications of
  2026-09-05 record the decision and its author. M-03.b is therefore a recorded
  deferral, not a half-built screen; the question of whether to defer at all is
  the one item this pass hands back to a person.

## Primary loop impact

Constitution Principle V, stated explicitly: this feature lives in **capture →
atomic items** and nowhere else.

- **Capture** changes shape. Browser-preview text stops being a task source and
  becomes a status readout (D-01, D-02), so the capture step now ends with an
  accurate transcript rather than a pile of interim fragments.
- **Atomic items** change quality. Tasks are minted once, from the accurate
  transcript, as GTD next actions (D-03). The reference dump goes from 9 review
  entries with 6 deletions to exactly 3 saveable next actions with 0.
- **Clarify / approve** starts from the owner's intent instead of from cleanup.
  The step is unchanged; its input improves.
- **Route or CRT candidate**: no impact. Saved tasks land in Inbox exactly as
  before and carry no new routing signal.
- **Weekly Review**: no impact. It remains visibly deferred; nothing here adds a
  cadence, a due state or a fifth primary list.
- **Evidence / results**: no impact of a new kind. The saved-task receipt already
  records whether a task came from the accurate or the browser transcript; the
  recovery reuses that field rather than adding one.

Interruption tolerance per ADR-0002 is designed, not assumed: D-01.f restores the
tail and the timer on the first render after a reload; D-02.g keeps processing on
the server while the panel is closed and resumes on whatever stage the server
reached; M-03.b pauses the poll in the background and refreshes on return.

The confirmations added this pass do not move the feature within the loop; they
protect the capture step's only irreversible edge. Every path that ends a
recording — four on the web, three on the phone — now asks once and names what
is lost, on the surface Principle V calls primary. Nothing reaches Inbox without
an explicit Save, and nothing leaves it without an explicit answer.

## Mobile viability

- **Viewport**: verified at 390×851. Every frame in `design/*.html` is exactly
  390 px wide with `overflow:hidden`, so any horizontal overflow would be
  visible; there is none. **No horizontal scroll.**
- **Tap targets**: 44 pt honored on mobile (`minHitTarget = 44`; the M-02 header
  "Discard recording" control and the "Delete retained audio" control both carry
  a 44 px box around a 16–18 px icon). **Exceptions on the web surface**, which is
  a browser viewport rather than a native one and inherits the shipped 36–40 px
  control heights: D-01's Pause/Resume/Discard/"Stop cloud processing" and D-02's
  "Cancel processing" are 36–40 px tall; D-03's card delete (X) is 32×32; M-02's
  "Discard all" ghost is 32 px tall (`minHitTarget - 12`). The destructive ones
  are the concerning members of that list — though every one of them now opens a
  confirmation rather than acting, so a mis-tap costs a dismissal, not a
  recording.
- **One-handed reach**: the primary action sits at the bottom of the panel on
  every screen — "Stop & review" above the secondary row on D-01, "Send N to
  inbox" in the D-03 footer, "Confirm N additions" in the M-02 sticky sheet. The
  transcript readout, which is read and not touched, takes the upper half. The
  D-03 back arrow and the M-02 header control are the two top-edge targets.
- **Destructive actions**: **seven, and every one confirms.** Four on the web,
  each with an inline confirmation whose copy names what is lost — "Discard this
  recording? The audio and transcript are deleted and nothing is saved.", "Cancel
  processing? The recording and its transcript are discarded and no tasks are
  created.", "Discard all tasks? Nothing is saved to Inbox and the recording is
  deleted.", "Delete this recording? Its audio and transcript are removed and
  nothing is saved." Three on mobile, through the platform dialog: M-01
  "Discard everything" → M-01.f, M-02 "Discard all" and the M-02 header
  "Discard recording" → M-02.i. That is SC-004's web 4 of 4 and mobile 3 of 3.
- **What the platform owns on mobile**: the dialog's box, type, hairlines and the
  placement of the answers are `Alert.alert`'s, not ours. The app supplies the
  title, the message and two answers with their roles — `cancel` first,
  `destructive` second — and `cancelable: true`, so an Android back gesture or an
  outside tap is a keep. The frames draw iOS: two short answers sit across
  (M-01.f), long ones stack with the cancel answer in its platform position last
  (M-02.i).

## Keyboard and focus

- **Tab order**: the panel is a focus trap. Tab cycles inside it and never
  reaches the workspace behind. D-01: pre-flight controls → Record → Discard →
  transcript readout; once capture is live: Stop & review → Pause/Resume →
  Discard → Stop cloud processing. D-03: back arrow → each card's title field
  then its delete → Send → Discard all.
- **Focus on open**: the panel itself takes focus on mount (programmatic, so no
  focus ring is drawn around the whole dialog). **Focus restored on close to**:
  the control that opened the panel, via the router state the overlay carries
  forward; an inline confirmation restores focus to its own trigger.
- **Inline confirmation**: opening it removes the trigger and puts focus on the
  **safe** answer — "Keep recording", "Keep processing", "Keep reviewing",
  "Keep recording" (delete). **Escape** inside the confirmation closes it,
  restores the trigger and returns focus to it; the handler stops propagation so
  the same Escape cannot also dismiss the panel. Choosing the safe answer does
  the same. Confirming closes the question immediately and hands off, so a
  failure (a stale revision) reports in the surface's alert rather than under an
  open question.
- **Escape at panel level**: only closes the panel where a close exists — the
  pre-capture recording screen and the saved panel. Processing, review and
  recovery are deliberately not dismissible: a live capture would leave the
  microphone open behind an invisible dialog, and unreviewed drafts or retained
  audio need an explicit choice.
- **Accessible names for icon-only controls**: "Close brain dump" (X), "Back to
  recording" (chevron), "Delete {title}" (card X), mobile "Remove proposal"
  (card X), mobile **"Discard recording"** (header Trash2) and mobile **"Delete
  retained audio"** (raw-audio Trash2, visible label "Delete now"). Every name
  now describes what the control does; the two that did not — a "Close" that
  discarded and a "Delete recording" that removed only retained audio — were
  renamed, and mobile's tests assert that neither old name is present.
- **State communicated by color alone**: **none.** "Ready", "Recording",
  "Paused" and "Cloud processing stopped" are words next to the dot; the
  provisional and not-reconciled banners carry their full sentence; a conflict is
  labelled "Conflict: title". The one former exception is closed: when Send is
  disabled purely because a conflict is open (D-03.g), a `role="status"` line
  under the button now reads "Resolve N conflicts before sending." and the button
  points at it with `aria-describedby`, so the reason reaches a screen reader
  that lands on the disabled control. Mobile carries the same sentence worded
  "… before confirming." (M-02.d) — one word apart, listed below.
- **Announcement on mobile**: the platform dialog is the platform's own
  alert, so focus, the announcement and the dismissal gesture are VoiceOver's and
  TalkBack's rather than ours. That is the reason FR-007 asks for a platform
  dialog on mobile and an inline confirmation on the web, where a dialog inside
  an overlay would have to trap focus itself (Clarifications, fifth decision).

## Design authority

- Tokens, colors, type, radii, shadows and voice from the `brain-buddy-design`
  skill (`colors_and_type.css`, `README.md`). Screens are self-contained: inline
  CSS, no CDN, no external font (Inter is named with a system fallback and never
  fetched), and no script is required to render. Ambient motion is confined to
  the brain-dump loops the skill allows — mic pulse, caret blink, waveform — and
  is disabled under `prefers-reduced-motion`.
- The four open GTD primary lists, Tag vocabulary and the deferred Weekly Review
  are untouched by this feature; the only GTD surface it reaches is Inbox, via
  the card pill and "Send N to inbox".
- The mobile confirmation is the one place a screen in `design/` is not drawn
  from the skill: `Alert.alert` renders the platform's own alert, so M-01.f and
  M-02.i draw the OS chrome (iOS system alert: 270 px box, 14 px radius, 17 px
  title, hairline-separated answers, blue default and red destructive) and label
  it as the platform's. Only the strings and the two roles are the product's.
  Everything around the dialog is skill tokens as before.
- Vocabulary check (ADR-0006, `Tag` is the only term for the concept): **pass**
  — the grep for the two retired synonyms over `design.md` and `design/`
  returns nothing, and so does a case-insensitive search for the bare word.
- `python3 -m unittest scripts/test_validate_brain_buddy_design_skill.py`:
  **pass** (6 tests).
- State-id parity: 57 ids in the tables above, the same 57 across `design/*.html`
  — no id in one and not the other.

## Open decisions for the human

The founder waived sign-off. Five of the six choices the first pass listed here
have since been answered in code, and the FR-006-on-mobile question it raised
under *Requirements with no affordance* was answered by a scope decision written
into `spec.md`. All six are recorded under
[Closed since the first pass](#closed-since-the-first-pass) with the behaviour or
the decision that answered them. What is left is below, most consequential
first: one of the six (tap targets), the scope decision itself, and four smaller
splits between the two clients.

### Still open

1. **The mobile processing screen stays short, by decision (M-03.b).** FR-006 is
   now web-only, and `spec.md` records the transcript readout and "Cancel
   processing" on mobile as out of scope. That decision was taken by the agent,
   not by the founder, and it is the one on this list worth a person's attention:
   the phone is the capture surface Principle V is written for, and a person
   waiting on a mobile recording sees a stage label and no way out until it
   settles — their only cancel is the one the review (M-02.i) or the failure
   screen (M-01.f) offers afterwards. *Recommended: keep it deferred for this
   feature and raise it as its own; half-building it here is the worse option,
   which is what the clarification says.*
2. **Tap targets on the web overlay.** The destructive controls that ship at
   32–40 px — the card delete X (32), D-01's Discard (36), D-02's "Cancel
   processing" (40) — are below the 44 pt the skill sets for mobile, on a surface
   whose primary frame is a 390 px phone viewport. Every one of them now opens a
   confirmation rather than acting, so a mis-tap costs a dismissal rather than a
   recording; that lowers the stakes without answering the question. Accept the
   browser exception, or raise them. *This is the one item the first pass left
   open and this pass did not answer.*
3. **`Ref:` on the web against `ref:` on mobile.** Both clients now print the
   server's reason and the request's correlation id. The web renders it as
   `… Ref: {id}` appended to the banner sentence (`describeError`); mobile
   renders it as a separate monospace line reading `ref: {id}` (`ErrorBanner`).
   The owner quotes the same id either way, so this is a consistency call, not a
   defect. *Cheapest option: leave it.*
4. **"before sending" on the web against "before confirming" on mobile
   (D-03.g / M-02.d).** Each client names its own commit control — "Send N to
   inbox" and "Confirm N additions" — so the sentences differ by one word on
   purpose. Confirm that, or unify the wording and accept that one client's
   sentence then names a button it does not have.
5. **M-03.a shows a spinner with no title**, where D-05.a says "Loading your
   brain dump". No requirement asks for the title. Adopt the web's named panel on
   the phone, or accept the difference.
6. **D-05.b has no retry control**: a failed cold fetch falls through to the
   recording surface carrying the error, and the owner reloads the page. M-03.c
   offers Retry in place. Add one, or accept the reload.

### Answered, for the record

FR-007 on mobile, built — with the two renames · the mobile empty review
(M-02.e) · the web error copy (D-01.j, D-02.e, D-03.m, D-04.g, D-05.b) ·
"record again" on the web empty review (copy, not a control) · the reason Send
is disabled with an open conflict (D-03.g) · FR-006's reach, settled as web-only
in `spec.md`. Each is described under
[Closed since the first pass](#closed-since-the-first-pass).
