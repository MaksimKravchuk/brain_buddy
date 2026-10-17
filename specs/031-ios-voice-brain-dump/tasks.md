# Tasks: iPhone voice brain dump

**Input**: [spec.md](spec.md), [design.md](design.md), [plan.md](plan.md)

Tests carry the feature-qualified id (`031-FR-005` in a test name, `031_FR_005` in a
Swift function name) so `scripts/check_requirement_coverage.py` can trace them.

## Format: `[ID] [P?] [Story] Description`

## Phase 1 — Spec (PR-01)

- [x] T001 [US1] Write intake, spec, design, plan, tasks and the requirements checklist in `specs/031-ios-voice-brain-dump/`

## Phase 2 — Kit model (PR-02)

- [x] T002 [US1] Add `HeardStep`, `StepExtracting`, `SentenceStepExtractor`, `SpeechCapturing`, `SpeechCaptureError`, `BrainDumpCapturePort`, `BrainDumpProject`, `VoiceLanguage` and `VoiceBrainDumpCopy` in `ios/BrainBuddyKit/Sources/BrainBuddyWorkspace/VoiceBrainDump/`, and make `Workspace` conform to `BrainDumpCapturePort`
- [x] T003 [US1] Implement `VoiceBrainDumpModel` (start, live debounced reads, fallback, merge with edits and removals, project match, stop, add with partial failure, cancel, close confirmation) per plan.md
- [x] T004 [P] [US1] Test every phase and rule with a fake speech capture, a fake extractor and a fake port in `ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/VoiceBrainDumpModelTests.swift`

## Phase 3 — App: speech and steps (PR-03), sheet (PR-04)

- [x] T005 [US1] Add `AppleSpeechCapture` (AVAudioEngine tap, on-device `SFSpeechRecognizer`, permissions, no file) in `ios/BrainBuddy/Screens/Capture/Voice/`
- [x] T006 [US1] Add `AppleStepExtractor` (Foundation Models, `@Generable` steps, throws when unavailable) in `ios/BrainBuddy/Screens/Capture/Voice/`
- [x] T007 [US1] Declare `NSMicrophoneUsageDescription` and `NSSpeechRecognitionUsageDescription` in `ios/project.yml`
- [x] T008 [US1] Add `VoiceCaptureSheet` per design.md (states V-02.1 to V-02.9, language menu, close confirmation, toast on add), its rows and the voice button face in `VoiceCaptureParts.swift`
- [x] T009 [US1] Show the voice button in the capture glass bar's leading slot, presenting the sheet, in `ios/BrainBuddy/Screens/Capture/CaptureSheet.swift`

## Phase 4 — Close (PR-05)

- [ ] T010 Write `acceptance.md`, `traceability.md` and `report.md` after Max's device check

## PR-срезы

```json
{
  "schema_version": "brainbuddy-pr-slices/v2",
  "slices": [
    {
      "id": "PR-01",
      "outcome": "The on-device brain dump is specified: intake, spec, design, plan and tasks",
      "tasks": ["T001"],
      "requirements": ["031-FR-001", "031-FR-002", "031-FR-003", "031-FR-004", "031-FR-005", "031-FR-006", "031-FR-007", "031-FR-008", "031-FR-009", "031-FR-010", "031-FR-011", "031-FR-012", "031-FR-013"],
      "paths": ["specs/031-ios-voice-brain-dump"],
      "depends_on": [],
      "tests": ["python3 scripts/check_spec_kit_specs.py"],
      "acceptance": ["The spec validator passes and every requirement maps to a later slice"],
      "budget": {"product_loc": 1, "files": 6},
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-02",
      "outcome": "A platform-neutral model turns heard text into editable steps and adds them to the Inbox, tested on Linux",
      "tasks": ["T002", "T003", "T004"],
      "requirements": ["031-FR-003", "031-FR-004", "031-FR-005", "031-FR-006", "031-FR-007", "031-FR-008", "031-FR-009", "031-FR-010", "031-FR-011", "031-FR-012", "031-SC-003", "031-SC-004"],
      "paths": [
        "ios/BrainBuddyKit/Sources/BrainBuddyWorkspace/VoiceBrainDump",
        "ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/VoiceBrainDumpModelTests.swift"
      ],
      "depends_on": ["PR-01"],
      "tests": ["sh ios/scripts/swift-linux.sh test --filter VoiceBrainDumpModelTests"],
      "acceptance": [
        "Every phase is reached with fakes; an edited or removed step survives later reads",
        "A failed model read falls back to sentences; a partial save keeps only the unsaved steps"
      ],
      "budget": {"product_loc": 400, "files": 6},
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-03",
      "outcome": "The app recognises speech on the device and reads steps with Apple's on-device model, behind the kit's protocols",
      "tasks": ["T005", "T006", "T007"],
      "requirements": ["031-FR-003", "031-FR-005", "031-FR-013"],
      "paths": [
        "ios/BrainBuddy/Screens/Capture/Voice/AppleSpeechCapture.swift",
        "ios/BrainBuddy/Screens/Capture/Voice/AppleStepExtractor.swift",
        "ios/project.yml"
      ],
      "depends_on": ["PR-02"],
      "tests": ["CI ios-app lane: xcodebuild -project ios/BrainBuddy.xcodeproj -scheme BrainBuddy -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build"],
      "acceptance": [
        "The app builds and declares the microphone and speech usage descriptions",
        "Recognition is on-device only and no audio file is written"
      ],
      "budget": {"product_loc": 300, "files": 3},
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-04",
      "outcome": "iPhone shows screen 11: the voice button in capture opens the voice sheet, steps appear while talking and are added to the Inbox",
      "tasks": ["T008", "T009"],
      "requirements": ["031-FR-001", "031-FR-002", "031-FR-011", "031-FR-012", "031-SC-001", "031-SC-002"],
      "paths": [
        "ios/BrainBuddy/Screens/Capture/Voice/VoiceCaptureSheet.swift",
        "ios/BrainBuddy/Screens/Capture/Voice/VoiceCaptureParts.swift",
        "ios/BrainBuddy/Screens/Capture/CaptureSheet.swift"
      ],
      "depends_on": ["PR-02", "PR-03"],
      "tests": ["CI ios-app lane: xcodebuild -project ios/BrainBuddy.xcodeproj -scheme BrainBuddy -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build"],
      "acceptance": [
        "The app builds; the sheet uses only Carry On tokens and matches cell M11 apart from the deviations in design.md",
        "On a device, three spoken actions become three Inbox tasks offline and signed out"
      ],
      "budget": {"product_loc": 400, "files": 3},
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-05",
      "outcome": "The feature is closed with acceptance, traceability and the delivery report",
      "tasks": ["T010"],
      "requirements": ["031-SC-001"],
      "paths": ["specs/031-ios-voice-brain-dump"],
      "depends_on": ["PR-01", "PR-02", "PR-03", "PR-04"],
      "tests": ["python3 scripts/check_spec_kit_specs.py", "python3 scripts/check_requirement_coverage.py"],
      "acceptance": ["Every requirement maps to a named test or to the device check"],
      "budget": {"product_loc": 50, "files": 3},
      "implementer": "mechanical-implementer"
    }
  ]
}
```
