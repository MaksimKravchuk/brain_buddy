# Design: iPhone first run

Source: canvas "Carry On" (https://claude.ai/artifact/1bwKiw15U2jpZqwu5pTMg6), cells
M01–M04 iPhone and the page "Carry On · first run" (board version `1792165683-83f3`).
Built from the board's CSS; no mockup of our own.

## Screen inventory

| Id | Board | Screen | Where |
|---|---|---|---|
| I-01 | 01 Welcome | Full screen over the app | `Screens/FirstRun/FirstRunView.swift` |
| I-02 | 02 First capture | Full screen, keyboard up | `Screens/FirstRun/FirstCaptureScreen.swift` |
| I-03 | 03 First step | Full screen, keyboard up | `Screens/FirstRun/FirstStepScreen.swift` |
| I-04 | 04 Landing | The Next actions tab with one tip row | `Screens/FirstRun/LandingTip.swift` in `TaskListScreen` |

## Layout (from the board)

- Ground `bg-ground`; all text `text-primary` or `text-secondary`; no new colour.
- I-01: mark 132 pt; "Carry On" Instrument Serif 56/1.05, 28 pt under the mark; the
  promise 19/1.4 secondary, 12 pt under; the no-account line `meta` secondary, 38 pt above
  the glass bar; bar: Start (`strong`, fills) and I have an account (`quiet`).
- I-02: 36 pt below the safe area, 24 pt sides. "What feels heaviest?" `display`;
  subline `body` secondary 10 pt under; field 28 pt under: `surface-card`, radius 14,
  padding 16, min height 96, text 19/1.4, basalt focus ring 2 pt at 2 pt offset; hint `meta`
  secondary 12 pt under. Glass bar above the keyboard: Skip (`quiet`), Add to Inbox
  (`strong`, fills).
- I-03: "From your Inbox" `meta` secondary; the words 19/1.4, 6 pt under; question
  Instrument Serif 30/1.05, 26 pt under; field 20 pt under with the step in Instrument Sans
  SemiBold 22/1.25; helper `meta` 12 pt under. Bar: Not yet (`quiet`), Make it my next step
  (`glassPrimary`, fills): the only terracotta.
- I-04: the tip under the Next actions card: `control-quiet`, radius 14, padding 16 × 18,
  `body`, "Got it" `body-strong` 10 pt under (44 pt tap target).

Sizes off the type scale are tokens: `layout.first-run.*`, `layout.landing-tip.*`.

## State inventory

| Screen | States |
|---|---|
| I-01 | default; sign-in sheet open |
| I-02 | empty (Add to Inbox unavailable); typed; saving; save failed (toast) |
| I-03 | empty step (move unavailable); typed; saving; save failed (toast) |
| I-04 | tip shown; tip dismissed (normal Next actions) |

## Copy

Exactly the board: "Carry On", "Say what weighs on you.\nTake the next step.", "No account
needed. Your tasks stay on this iPhone until you sign in.", "Start", "I have an account",
"What feels heaviest?", "Say it as it is. You sort it in a moment.", "It goes to your Inbox,
as you wrote it.", "Skip", "Add to Inbox", "From your Inbox", "What is the first step you
could take?", "Small enough to start today. Not sure yet? Leave it in the Inbox.", "Not yet",
"Make it my next step", "This is your next step. When it is done, tap Done. Anything else
on your mind goes in the bar below.", "Got it".

## Deviations from the board

- The welcome's bar uses the app's shared glass action bar geometry (the board draws it
  8 pt from the sides and 20 pt from the bottom; the shared bar is the one the sheets use).
- I-04 keeps the existing Next actions card ("Next actions" label, Done only). The board's
  "Now" label and "Not now" button belong to the lists wave (intake T5).

## Keyboard and focus

The field takes focus when I-02 and I-03 appear. In I-03 Return submits the step. VoiceOver
reads the headings as headers; the mark is decorative.

## Mobile viability

This is the iPhone surface itself; it also runs on iPad, full screen per window.
