# Manual iOS evidence — weekly review increment 1 (slice PR-04)

**Status: PENDING (owner run).** Nothing below has been run yet. This file was
written by the implementer of slice PR-04 in a Linux session, which can neither
build the app target nor run a simulator or device. Every result cell says
`PENDING` until the owner (or a session with Xcode) runs the steps and replaces it
with what was observed. Do not mark a row passed without running it.

- **Kind**: manual (tasks.md T094; plan "Test strategy", Xcode + manual row)
- **Data**: synthetic only (a fresh install or the `-BBUsePreviewData` launch
  argument, plus tasks created for the run; no real account data)
- **Build under test**: `<commit SHA>` (fill in) — Debug configuration, so
  `BBWeeklyReviewLocal` is `YES` for the account-less checks
- **Device / simulator**: `<model, iOS version>` (fill in)
- **Run by / date**: `<name>`, `<date>` (fill in)

## 0. Xcode-lane build of the app target

| check | how | result |
|---|---|---|
| App and widget targets compile | `(cd ios && xcodegen generate) && xcodebuild -project ios/BrainBuddy.xcodeproj -scheme BrainBuddy -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build`, or the `ios-app` lane of `.github/workflows/ci.yml` on the slice's SHA | PENDING |
| Release keeps the switch off | build the Release configuration and read `BBWeeklyReviewLocal` from the built `Info.plist` (`/usr/libexec/PlistBuddy -c 'Print :BBWeeklyReviewLocal' …/BrainBuddy.app/Info.plist`); expect `NO`, and an account-less Release build shows the Lists "Weekly review · coming later" row and no markers | PENDING |
| Previews render | open each `#Preview` in `Screens/Review/*.swift`, `Components/Chips.swift` and `Screens/Settings/ReviewSettingsSection.swift` (one per M-01, M-02, M-03, M-04, M-09, M-23, M-26 state) | PENDING |

## Setup for the device checks

1. Debug build, account-less, fresh install (or Settings › Sign out first).
2. Capture three tasks into Next actions. To make one ask for a decision without
   waiting 14 days, either sign in to a local test backend and seed it with
   `BRAIN_BUDDY_ENV=test python -m app.cli review-seed-aged-task` (an aged Next
   task, owner activated), or move the simulator clock forward 15 days after the
   explainer was acknowledged (Settings › General › Date & Time on a simulator).
3. For M-09: with a seeded park (`review-run-sweep` after `review-seed-aged-task`
   with an age past the park point) or by moving the clock 22 days forward.

## 1. Entries, one per id

| id | what to check | steps | result |
|---|---|---|---|
| `020-FR-047` | The decision card is a sheet at the **large** detent outside a review (`.presentationDetents([.large])`) | Next tab → tap the "Asks for a decision" chip on a row; the card opens as a full-height sheet over Next, not a medium one; drag the grabber: it does not stop at a medium height. Repeat from task detail › "This wording" › Decide | PENDING |
| `020-FR-052` | `interactiveDismissDisabled` while a form holds unsaved text; "Keep editing" is the default; the draft comes back | Card › Reformulate › change the wording › swipe the sheet down: it does not close. Tap Back: the alert "Discard your new wording? It hasn't been saved." appears with "Keep editing" bold (default). Keep editing; kill the app from the app switcher; reopen the card for the same task › Reformulate: the text is back with "Your unsaved text is back." and Clear | PENDING |
| `020-FR-048` | Undo toast: VoiceOver announces "<decision>. Undo available."; about 5 s without VoiceOver; at least 10 s with VoiceOver or Switch Control and until focus leaves it; the Undo button is 44 × 44 pt | Without VoiceOver: card › Release to Someday; time the toast (≈ 5 s). With VoiceOver on: repeat; hear "Released to Someday. Undo available."; the toast stays ≥ 10 s; move VoiceOver focus onto Undo and wait 15 s: it stays; move focus away: it leaves about a second later (or at 10 s). Undo restores the task to Next with its marker. Accessibility Inspector: the Undo hit area is ≥ 44 × 44 pt and its label reads "Undo: Released to Someday <title>" | PENDING |
| 44 pt targets | Marker chips, reason chips, decision rows, Undo, "Return to Next", "Got it" | Accessibility Inspector › hit-test each on M-01, M-03, M-04, M-09, M-26; every target ≥ 44 × 44 pt (the marker chip's hit area extends past the drawn chip) | PENDING |
| AA contrast | Marker chips and Undo meet WCAG 2.2 AA (4.5:1 text) in light and dark mode | Accessibility Inspector › Color contrast on the indigo "Asks for a decision" chip, the amber "Moves to Someday tomorrow" chip, the slate "Ageing" chip (task detail) and the toast's Undo, in light and dark appearance | PENDING |
| VoiceOver focus, M-26 | Focus goes to the heading when the explainer appears, and to the tab's navigation title when it closes | Fresh install with VoiceOver on: open the app; the first thing read is "How Next stays fresh, heading". Tap "Got it"; focus lands on the Next actions (or current tab's) navigation title | PENDING |
| VoiceOver focus, M-09 | Focus goes to the heading when "While you were away" appears, and to the tab's navigation title when it closes | With an unseen park and VoiceOver on: open the app; "While you were away, heading" is read first. Continue; focus returns to the tab's navigation title | PENDING |
| `020-FR-051` | No marker before the explainer is acknowledged; the explainer shows before anything else; an app kill shows it again | Fresh install: Next shows no marker even for old tasks; the explainer shows at first open; kill the app while it shows; reopen: it shows again; "Got it": markers can now appear | PENDING |
| `020-FR-015` | M-09 at most once a calendar day; swipe-down does not acknowledge; Continue does | Unseen park: open app → M-09; swipe down; background and reopen the same day: not shown again; next day: shown again; Continue: not shown again | PENDING |

## 2. Dynamic Type at AX5 (design "Mobile viability")

Settings › Accessibility › Display & Text Size › Larger Text › the largest size
(AX5). For each screen: no control is clipped or truncated, every body scrolls,
and the primary action ("Got it", "Continue", Save) stays reachable.

| screen | state(s) to open | result |
|---|---|---|
| M-01 Next list | rows with "Asks for a decision" and "Moves to Someday tomorrow" chips; the "threshold just changed" note; the "1 decision couldn't be saved" note | PENDING |
| M-02 This wording | asks, ageing, paused, moves tomorrow, kept 7 more days, parked automatically | PENDING |
| M-03 Decision card | default, a reason chosen (Recommended badge stacks under the title), extension used, third stall, stale, offline | PENDING |
| M-04 Forms | Reformulate (and the cosmetic note), First step, Waiting for, Keep 7 more days (empty and ready) | PENDING |
| M-09 While you were away | four rows, one returned, return all, project archived, offline, more parks waiting, linked-extension notice | PENDING |
| M-26 Explainer | default, "Change the number of days" open, offline; "Got it" reachable by scrolling | PENDING |

## Findings

(none recorded yet)
