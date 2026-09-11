# Design: Transcript-first voice brain dump

**Feature**: `specs/015-transcript-first-brain-dump/` · **Date**: 2026-09-05

Retro design: it documents the screens as shipped in `frontend/src/features/brain-dump/BrainDumpRoute.tsx` (web) and `mobile/src/app/brain-dump/[operationId].tsx` (mobile). Authority order: accepted ADRs (ADR-0006 makes `Tag` canonical), the `brain-buddy-design` skill, constitution Principle V (mobile-first). Primary frame 390 px wide; the web panel also has a two-pane layout from 640 px.

## Screen inventory

| Id | Client | Screen | Purpose | Requirements |
|---|---|---|---|---|
| D-01 | web | Recording | Show what has been heard as a status while capture runs; Pause, Resume, Stop, confirmed Discard | FR-001, FR-002, FR-007, FR-008 |
| D-02 | web | Processing | Name the stage, keep the transcript readable, offer one confirmed exit | FR-006, FR-007, FR-010 |
| D-03 | web | Review | Edit, delete and send clean next actions; refuse to save an empty review | FR-003, FR-004, FR-005, FR-007, FR-010, FR-011 |
| D-04 | web | Recovery (failure) | Retry, review provisional, one-shot browser-transcript extraction, confirmed delete | FR-007, FR-009, FR-010 |
| D-05 | web | Loading | Name the fetch of a persisted recording instead of flashing the wrong surface | FR-008 |
| M-01 | mobile | Recovery (failure) | The same server-advertised recovery actions on the phone, confirmed discard | FR-007, FR-009, FR-010 |
| M-02 | mobile | Review | Confirm additions with the provisional badge; honest empty review; confirmed discards | FR-005, FR-007, FR-010, FR-011 |
| M-03 | mobile | Loading and processing | First fetch, server stages (stage label only), failed load | FR-006 (stage only), FR-008 |

## States

- **D-01 Recording**: a ready (first run) · b loading providers · c empty readout · d recording · e paused · f resumed (tail and timer seeded) · g Discard confirmation · h consent withdrawn mid-capture · i providers error · j upload failure banner.
- **D-02 Processing**: a sealing · b transcribing (preview readout) · c reconciling (accurate readout) · d no transcript yet · e error banner (reason and reference) · f Cancel processing confirmation · g interrupted, resumed by polling.
- **D-03 Review**: a committable · b folded duplicate · c editing · d provisional, saveable · e provisional, not saveable · f not reconciled · g conflict with "Resolve N conflicts before sending." · h empty (filler-only) · i empty (everything deleted) · j saving · k saved · l Discard all confirmation · m stale-screen error.
- **D-04 Recovery**: a retryable transcription · b retryable reconciliation · c terminal with surviving proposals · d terminal with browser-transcript recovery · e no recovery available · f Delete recording confirmation · g refusal (reason and reference).
- **D-05 Loading**: a loading · b fetch error.
- **M-01 Mobile recovery**: a retryable · b terminal with proposals · c terminal with browser-transcript recovery · d none available · e refusal (message and reference) · f Discard everything dialog.
- **M-02 Mobile review**: a committable · b provisional, saveable · c provisional, not saveable · d conflict · e empty (no Confirm, "What was heard") · f saving · g saved · h discarded · i Discard all / header discard dialog.
- **M-03 Mobile loading and processing**: a loading · b processing (stage label only) · c fetch error.

## Copy that tests depend on

- Readout heading "What you've said · browser preview"; processing heading "Browser preview · provisional" or "Accurate transcript"; empty readout "Your words appear here as you speak. Tasks are proposed after you stop."
- Web confirmations: Discard → "Discard this recording? The audio and transcript are deleted and nothing is saved." / "Keep recording" / "Discard recording". Discard all → "Discard all tasks? Nothing is saved to Inbox and the recording is deleted." / "Keep reviewing" / "Discard all tasks". Delete recording → "Delete this recording? Its audio and transcript are removed and nothing is saved." / "Keep recording" / "Delete recording permanently". Cancel processing → "Cancel processing? The recording and its transcript are discarded and no tasks are created." / "Keep processing" / "Cancel processing".
- Mobile dialogs: "Discard this recording?" / "Keep" · "Discard recording"; "Discard all tasks?" / "Keep reviewing" · "Discard all tasks". Header control "Discard recording"; retained-audio control "Delete retained audio".
- Recovery: "Extract tasks from the browser transcript" with "Sends the browser transcript to the consented task-extraction provider. The result is provisional and is reviewed before anything is saved."
- Provisional banner (web): "These tasks were extracted from the browser transcript, not from accurate audio. Review them carefully before saving." Mobile badge: "Provisional only — the accurate transcript wasn't available, so these come from the live preview. Review them carefully."
- Empty review: web "No tasks to review" / "No tasks were proposed from this dump. Here is what was heard; discard it to record again."; mobile "No tasks to review" / "No tasks were proposed from this dump. Discard it to record again."
- Errors: the server message followed by "Ref: <correlation id>" (web); message plus a "ref:" line (mobile).

## Affordance → requirement

- Transcript readout, live tail, absence of task cards before Stop → FR-001, FR-002.
- Clean task cards with citations, folded duplicate → FR-003, FR-004.
- Send enabled with nothing deleted; empty review without a save control → FR-005.
- Stage label, transcript, Cancel processing (web) → FR-006.
- Every confirmation above; renamed mobile controls → FR-007.
- Seeded tail and timer on resume; loading screen → FR-008.
- Recovery button and helper; refusal with reason → FR-009.
- Provisional banner and badge, saveable or not → FR-010.
- Not-reconciled banner and edit-or-delete rule for legacy provisional drafts → FR-011.

## Keyboard, focus, mobile

Web confirmations open in place of their trigger, focus the safe choice, close on Escape or the safe choice, and return focus to the trigger. Mobile confirmations are the platform dialog with the cancel choice marked `cancel` and the destructive one `destructive`. No state is carried by colour alone; the review footer explains a disabled Send. At 390 px nothing overflows horizontally.

## Open decisions

1. Mobile processing screen: no transcript readout and no cancel (recorded scope decision; open for the founder).
2. Raw-audio deletion ("Delete audio now" / "Delete retained audio") deletes on one tap.
3. Web overlay destructive controls are 32–40 px against the 44 pt mobile target.
4. Wording splits: "Ref:" (web) vs "ref:" (mobile); "before sending" vs "before confirming".
