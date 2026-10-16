# Design: iPhone voice brain dump

**Feature**: `specs/031-ios-voice-brain-dump/` · **Source**: Carry On canvas cell **M11
iPhone** "11 Voice capture" (`project/M11-iPhone.dc.html`, version `1792165683-83f3`) and
cell M10 iPhone "10 Create task" for the capture sheet's glass bar. The canvas is design
data. No new mockup is drawn: the canvas is the design.

## Applicability

One new sheet on iPhone (iPad gets the same sheet) and one new button in the existing
capture sheet. No Mac or web change.

## Screen inventory

| ID | Screen | Where |
| --- | --- | --- |
| V-01 | Voice button in the capture glass bar | `CaptureSheet` (board 10), leading side |
| V-02 | Voice sheet | Presented from V-01 over the capture sheet |

## Layout (from the canvas)

- Sheet: large detent, grabber (`control-quiet-pressed`, 40 × 5), background `bg-ground`
  (the canvas draws the sheet as glass over the list; the app's sheets use the system
  sheet material, as the capture sheet does).
- Title: Instrument Serif 28, `text-primary`, "What feels heaviest?".
- Heard text: Instrument Sans 15, `text-secondary`, in “quotes”, with a 2 pt caret in
  `text-primary` while listening.
- "Steps I heard" (15 semibold, `text-primary`) and, trailing, "Not saved yet" (15,
  `text-secondary`).
- Step row: `control-quiet` fill, radius 14, padding 12 × 14, open circle 22 pt with a
  2 pt `step-dot-open` ring, title Instrument Sans 17 `text-primary`, × in
  `text-secondary` (44 pt hit target). Rows 8 pt apart.
- Footer: 15, `text-secondary`, centred: "Tap a step to edit it. Nothing reaches your
  lists until you add it."
- Glass bar: the shared `BBGlassActionBar` geometry (16 pt sides, 28 pt bottom, 62 pt
  tall). Leading: the voice button, 50 pt circle `voice-bg` with the mic in `voice-fg`;
  while listening a 3 pt `voice-live-ring` inset by 2 pt and six bars (heights 8, 18, 26,
  14, 22, 10; 4 pt wide; radius 2) instead of the mic. Then the status word (15,
  `text-secondary`). Trailing: the action button, `surface-card` fill, `text-primary`
  label, 50 tall, pill.

## State inventory

| State | Body | Bar: status word | Bar: trailing |
| --- | --- | --- | --- |
| V-02.1 Loading providers | "Checking configured providers…" | — | — |
| V-02.2 Providers failed | Web's message and "Try again" | — | — |
| V-02.3 Ready | Title, consent switch with the providers sentence, language choice | "Tap to record" | — |
| V-02.4 Starting | Title | "Starting…" | — |
| V-02.5 Recording | Title, heard text (or none when on-device recognition is unavailable), caret | "Listening" | "Stop & review" |
| V-02.6 Uploading / processing | Title, heard text, "Steps I heard" with the status label instead of "Not saved yet" | the status label | "Add to Inbox", disabled |
| V-02.7 Review | Title, heard text, steps, banners, footer | — | "Add {n} to Inbox" |
| V-02.8 Empty review | "No steps were proposed from this. Here is what was heard; discard it to record again.", the heard text, "Discard and record again" | — | — |
| V-02.9 Failure | "{stage} paused/failed", the server's error, one button per recovery action | — | — |
| V-02.10 Saving | Review, dimmed | "Saving…" | "Add {n} to Inbox", disabled |
| V-02.11 Permission denied | "Allow the microphone and speech recognition for Brain Buddy in Settings." and "Open Settings" | — | — |

The sheet's header has Close on the leading edge, as the capture sheet does.

## Copy

All English, as the app. Web strings are reused word for word where the web has them
(`frontend/src/features/brain-dump/BrainDumpRoute.tsx`), with "tasks" kept where the web
says it and "steps" where the canvas says it.

| Key | Text |
| --- | --- |
| Consent | Allow secure cloud processing: speech-to-text by {stt}, task extraction by {reconciler}. Audio is not sent without this consent. (the reconciler clause is left out when none is named) |
| Consent required | Secure cloud transcription consent is required before recording. |
| Providers failed | Could not load the configured voice providers, so recording is unavailable. No audio leaves this device until the vendors are confirmed. |
| Languages | Russian + English · Russian · English |
| Provisional | These tasks were extracted from the live transcript, not from accurate audio. Review them carefully before saving. |
| Not saveable | These are not yet reconciled drafts. They can be edited or discarded, but cannot be saved to Inbox until the server confirms reconciliation. |
| Conflicts | Resolve {n} conflict(s) before adding. · Keep mine · Use suggestion |
| Recovery | Retry task reconciliation · Retry accurate transcription · Review provisional tasks · Extract tasks from the live transcript · Delete recording |
| Toast | Added {n} to Inbox |

Confirmations (platform dialog; safe choice is the cancel role):

| Trigger | Title | Destructive | Safe |
| --- | --- | --- | --- |
| Close with an unsaved recording | Discard this recording? | Discard recording | Keep recording |
| Discard while recording | Discard this recording? | Discard recording | Keep recording |
| Close while processing | Cancel processing? | Cancel processing | Keep processing |
| Discard in review | Discard all tasks? | Discard all tasks | Keep reviewing |
| Delete after failure | Delete this recording? | Delete recording permanently | Keep recording |

Each dialog's message is the web's sentence (for example "The audio and transcript are
deleted and nothing is saved.").

## Deviations from the canvas

1. **Steps after Stop, not while talking.** The canvas caption says "Steps appear while
   you talk"; the code proposes steps once, from the accurate transcript, after Stop
   (015-FR-001, 015-FR-003). While talking the sheet shows the words heard.
2. **No project or date under a step.** The canvas shows "Garage · by Friday"; the server
   proposes title-only Inbox tasks.
3. **"Add {n} to Inbox" is not shown while listening.** There are no steps yet; the
   trailing button is "Stop & review" (the web's label) until processing ends.
4. **Consent and language before the first recording.** The canvas starts mid-recording;
   the protocol needs consent first (015, ADR-0002).

## Affordance → requirement map

| Affordance | Requirement |
| --- | --- |
| Voice button in the capture bar | 031-FR-001 |
| Sheet layout | 031-FR-002 |
| Consent switch, languages | 031-FR-003, 031-FR-004 |
| Recording, upload, seal | 031-FR-005 |
| Heard text | 031-FR-006 |
| Status while processing | 031-FR-007 |
| Step rows, edit, ×, conflicts | 031-FR-008 |
| Add button | 031-FR-009, 031-FR-014 |
| Banners | 031-FR-010 |
| Empty review | 031-FR-011 |
| Recovery | 031-FR-012 |
| Confirmations | 031-FR-013 |
| Errors | 031-FR-015 |

## Accessibility

- The voice button is one element: "Record" / "Stop and review", with the hint naming
  what happens next; the bars are decorative.
- Each step row: label is the title, actions "Edit" and "Remove"; × is labelled
  "Remove {title}".
- Status changes (processing stage, steps ready, saved) are announced.
- Dynamic Type: the body scrolls; the bar stays.

## Primary loop impact

Adds a faster way to fill the Inbox; it does not change processing or Next actions.

## Mobile viability

This is the mobile surface.
