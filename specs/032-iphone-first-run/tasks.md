# Tasks: iPhone first run

**Input**: [spec.md](spec.md), [design.md](design.md), [plan.md](plan.md).
T007 needs an iPhone or simulator.

## Delivery

One PR carries T001–T006 (single-PR feature, so no slice map). It is over the 400-line
slice ceiling: the model and the four board screens only work together; about a third is
the model, the rest is SwiftUI layout with no rules plus the generated token file.
UI-only requirements (032-FR-002, 032-FR-004, 032-FR-007, 032-FR-013, 032-FR-014) and
032-SC-001 are checked on a device in T007; the app target has no screen tests yet.

## Phase 1 — Model

- [x] T001 [US1] Test-first: `PhoneFirstRunFlowTests` for the decision (clean device, anything
  held, unsaved record, finished outcomes, leaving before and after the capture, landing).
  032-FR-001, 032-FR-011, 032-FR-012, 032-SC-002.
- [x] T002 [US1][US2] Implement `PhoneFirstRunFlow`, `PhoneFirstRunRecord`,
  `UserDefaultsPhoneFirstRunRecordStore` and `PhoneFirstRunLaunchFacts` in
  `ios/BrainBuddyKit/Sources/BrainBuddyWorkspace/PhoneFirstRunFlow.swift`; tests for the capture,
  Skip, Not yet, the first step, Got it and a linked account. 032-FR-003, 032-FR-005,
  032-FR-006, 032-FR-008 – 032-FR-010.

## Phase 2 — Screens

- [x] T003 [US1] Add `layout.first-run` and `layout.landing-tip` tokens and regenerate.
  032-FR-014.
- [x] T004 [US1] Boards 01–03: `FirstRunView`, `FirstCaptureScreen`, `FirstStepScreen`,
  `FirstRunField`, `CarryOnMarkView` under `ios/BrainBuddy/Screens/FirstRun/`.
  032-FR-002, 032-FR-004, 032-FR-007, 032-FR-013.
- [x] T005 [US2] Board 04: `LandingTip` under the Next actions card. 032-FR-010.
- [x] T006 [US1] Wire the flow in `BrainBuddyApp` and `RootView`; UI test driver skips the
  first run. 032-FR-001, 032-FR-003.

## Phase 3 — Host evidence

- [ ] T007 Walk a fresh install on an iPhone or simulator (light and dark, VoiceOver, a
  large Dynamic Type size) and compare with boards 01–04. SC-001.
