# Implementation Plan: iPhone first run

**Branch**: `claude/project-thread-kh08p7` | **Spec**: [spec.md](spec.md)

## Summary

A `PhoneFirstRunFlow` model in `BrainBuddyWorkspace` decides once per device whether the first
run shows, walks it with the existing workspace commands, and records only dates and an
outcome in the app's own `UserDefaults`. The app shows boards 01–03 in place of the tabs
while the flow covers the app, and the board 04 tip on Next actions. Same decision rules as
the Mac's `FirstRunModel` (029), adapted to the iPhone (T2 in intake.md).

## Technical Context

Swift 6, SwiftUI for iOS 26, the local `BrainBuddyKit` package. The model is
Foundation-only and tested on Linux and macOS with Swift Testing; the views compile in the
`ios-app` CI lane. No new dependency, no server change, no new colour.

## Constitution Check

- Principle II (tested delivery): the decision rules, the writes and the record are
  covered by `PhoneFirstRunFlowTests` in the package; the SwiftUI screens hold no rule.
- Rules stay in Core: the flow dispatches existing `GTDCommand`s through `Workspace.apply`
  and never re-checks a transition.
- Design tokens: sizes off the type scale are tokens, regenerated with
  `scripts/generate_design_tokens.py`.

## Architecture

- `BrainBuddyWorkspace/PhoneFirstRunFlow.swift`: `PhoneFirstRunPhase`, `PhoneFirstRunRecord`,
  `PhoneFirstRunRecordStore` (+ `UserDefaultsPhoneFirstRunRecordStore`, key `BBFirstRunRecord`),
  `PhoneFirstRunLaunchFacts` (from a loaded `Workspace`), `PhoneFirstRunFlow`. The `Phone`
  prefix keeps them apart from the Mac's `FirstRunPhase` / `FirstRunRecord` /
  `FirstRunLaunchFacts` in `BrainBuddyMacCore`, which imports the same kit.
- Writes: capture = one `createTask` in the Inbox; first step = `updateTask` (title, note)
  plus `transitionTask` move to Next in one `apply`.
- App: `App/BrainBuddyApp.swift` owns the flow and puts it in the environment;
  `App/RootView.swift` decides after load (suppressed for `-BBUsePreviewData` and
  `-BBSkipFirstRun YES`), shows `FirstRunView` while `coversApp`, ends the run when an
  account links, and selects the Next tab on landing. `TaskListScreen` shows `LandingTip`
  under the Next card while `showsLandingTip`.
- UI test driver passes `-BBSkipFirstRun YES`.

## Verification

- `sh ios/scripts/swift-linux.sh test --filter PhoneFirstRunFlowTests` (or `swift test` on macOS).
- `DesignTokensTests` (generated file matches the JSON).
- `ios-app` lane builds the app.
- Host check on a simulator or device (fresh install walk-through, VoiceOver) by the owner.

## Risks

- A user who closes the app on the welcome sees it again: intended (T2).
- Mac and iPhone hold two copies of the same decision rules; merging them into the kit is a
  follow-up for the Mac thread.
