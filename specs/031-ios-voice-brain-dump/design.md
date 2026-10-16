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

- Sheet: large detent, grabber, the app's sheet background (as the capture sheet).
- Header: Close on the leading edge; the language ("Russian" / "English") as a quiet menu
  on the trailing edge.
- Title: Instrument Serif 28 (`CarryOnTypeScale.title`), `text-primary`, "What feels
  heaviest?".
- Heard text: Instrument Sans 15, `text-secondary`, in “quotes”, with a 2 × 16 pt caret in
  `text-primary` while listening.
- "Steps I heard" (15 semibold, `text-primary`) and, trailing, "Not saved yet" (15,
  `text-secondary`).
- Step row: `control-quiet` fill, radius 14, padding 12 × 14, open circle 22 pt with a
  2 pt `step-dot-open` ring, title 17 `text-primary`, meta line 15 `text-secondary`
  ("Garage · by Friday", "Taxes"), × in `text-secondary` (44 pt hit target). Rows 8 pt
  apart. The newest row fades in.
- Footer: 15, `text-secondary`, centred: "Tap a step to edit it. Nothing reaches your
  lists until you add it."
- Glass bar: `BBGlassActionBar` (16 pt sides, 28 pt bottom, 62 pt tall). Leading: the voice
  button, 50 pt circle `voice-bg` with the mic in `voice-fg`; while listening a 3 pt
  `voice-live-ring` inset 2 pt and six bars (8, 18, 26, 14, 22, 10 pt tall, 4 pt wide,
  radius 2) instead of the mic. Then the status word (15, `text-secondary`). Trailing: "Add
  {n} to Inbox", `surface-card` fill, `text-primary` label, 50 tall, pill.

## State inventory

| State | Body | Status word | Add button |
| --- | --- | --- | --- |
| V-02.1 Starting | Title | "Starting…" | disabled |
| V-02.2 Listening | Title, heard text with caret, steps as they appear | "Listening" | enabled when n > 0 (stops, then adds) |
| V-02.3 Finishing | As V-02.2, no caret | "Finishing…" | disabled |
| V-02.4 Review | Title, heard text, steps, footer | "Tap to talk again" | enabled when n > 0 |
| V-02.5 Nothing heard | Title, "Nothing to add yet." | "Tap to talk again" | disabled |
| V-02.6 Saving | Review, dimmed | "Adding…" | disabled |
| V-02.7 Permission denied | "Allow the microphone and speech recognition for Brain Buddy in Settings." and "Open Settings" | — | hidden |
| V-02.8 Unavailable | "Speech recognition for {language} isn't available on this iPhone." and "Try {other language}" | — | hidden |
| V-02.9 Save failed | Review with the error above the steps | "Tap to talk again" | enabled |

Tapping the voice button in V-02.4/5/9 listens again; new words add to the heard text and
the steps are read from all of it.

## Copy

English, as the app. Sentence case.

| Key | Text |
| --- | --- |
| Title | What feels heaviest? |
| Steps header | Steps I heard · Not saved yet |
| Footer | Tap a step to edit it. Nothing reaches your lists until you add it. |
| Add | Add {n} to Inbox |
| Empty | Nothing to add yet. |
| Toast | Added {n} to Inbox |
| Close confirmation | Discard what you said? · Discard · Keep talking; message "Nothing has been added to your lists." |
| Remove | Remove {title} (VoiceOver) |

## Deviations from the canvas

1. **A language menu in the header.** The canvas has none; recognition needs to know the
   language, and the Mac's voice sheet offers the same choice.
2. **Fallback steps carry no project or day** when the on-device model is unavailable (D4).

## Affordance → requirement map

| Affordance | Requirement |
| --- | --- |
| Voice button in the capture bar | 031-FR-001 |
| Sheet layout | 031-FR-002 |
| Language menu | 031-FR-003 |
| Steps while talking | 031-FR-004, 031-FR-005 |
| Project and day line | 031-FR-006 |
| Edit, × | 031-FR-007 |
| Add button | 031-FR-008, 031-FR-009, 031-FR-010 |
| Live voice button (stop) | 031-FR-011 |
| Close confirmation | 031-FR-012 |

## Accessibility

- The voice button is one element: "Talk" / "Stop listening"; the bars are decorative.
- Each step row: label is the title and its meta line; actions "Edit" and "Remove"; × is
  labelled "Remove {title}".
- New steps and the saved result are announced; Reduce Motion drops the fade.
- Dynamic Type: the body scrolls; the bar stays.

## Primary loop impact

Adds a faster way to fill the Inbox; it does not change processing or Next actions.

## Mobile viability

This is the mobile surface.
