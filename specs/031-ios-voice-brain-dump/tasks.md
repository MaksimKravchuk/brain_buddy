# Tasks: iPhone voice brain dump

**Input**: [spec.md](spec.md), [design.md](design.md), [plan.md](plan.md)

Tests carry the feature-qualified id (`031-FR-005` in a test name, `031_FR_005` in a
Swift function name) so `scripts/check_requirement_coverage.py` can trace them.

## Format: `[ID] [P?] [Story] Description`

## Phase 1 — Spec and kit API (PR-01)

- [ ] T001 [US1] Write intake, spec, design, plan, tasks and the requirements checklist in `specs/031-ios-voice-brain-dump/`
- [ ] T002 [US1] Add `BrainDumpAPI.swift` (DTOs, status labels, consent, manifest hash, SHA-256, one method per route) and give `Endpoint` a content type and extra headers in `ios/BrainBuddyKit/Sources/BrainBuddyAPI/`
- [ ] T003 [P] [US1] Test requests, decoding, labels, the manifest hash and SHA-256 vectors in `ios/BrainBuddyKit/Tests/BrainBuddyAPITests/BrainDumpAPITests.swift`

## Phase 2 — Kit model (PR-02)

- [ ] T004 [US1] Add `BrainDumpRemote` (with `BrainBuddyAPIClient` conformance), `VoiceRecording`, `RecordedAudio`, `VoiceLanguage` and `VoiceBrainDumpCopy` in `ios/BrainBuddyKit/Sources/BrainBuddyWorkspace/VoiceBrainDump/`
- [ ] T005 [US1] Implement `VoiceBrainDumpModel` (availability, consent gate, start, live segments, stop, upload, seal, polling, review edits, add, discard, recovery, close) per plan.md
- [ ] T006 [P] [US1] Test every phase and rule with a fake remote and a fake recorder in `ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/VoiceBrainDumpModelTests.swift`

## Phase 3 — App: recorder (PR-03) and sheet (PR-04)

- [ ] T007 [US1] Add `AppleVoiceRecorder` (AVAudioEngine, AAC file, on-device speech) in `ios/BrainBuddy/Screens/Capture/Voice/`
- [ ] T008 [US1] Add `VoiceCaptureSheet` per design.md (states V-02.1 to V-02.11, confirmations, toast and sync on add), its rows and the voice button face in `VoiceCaptureParts.swift`
- [ ] T009 [US1] Show the voice button in the capture glass bar when signed in and the flag is on, presenting the sheet, in `ios/BrainBuddy/Screens/Capture/CaptureSheet.swift`
- [ ] T010 [US1] Declare `NSMicrophoneUsageDescription` and `NSSpeechRecognitionUsageDescription` in `ios/project.yml`

## Phase 4 — Close (PR-05)

- [ ] T011 Write `acceptance.md`, `traceability.md` and `report.md` after Max's device check

## PR-срезы

```json
{
  "schema_version": "brainbuddy-pr-slices/v2",
  "slices": [
    {
      "id": "PR-01",
      "outcome": "The spec is written and the shared kit can drive every brain dump route with typed requests, redacted descriptions and the web's manifest hash",
      "tasks": ["T001", "T002", "T003"],
      "requirements": ["031-FR-003", "031-FR-004", "031-FR-005", "031-FR-006", "031-FR-007", "031-FR-008", "031-FR-013", "031-FR-015"],
      "paths": [
        "specs/031-ios-voice-brain-dump",
        "ios/BrainBuddyKit/Sources/BrainBuddyAPI/BrainDumpAPI.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyAPI/BrainBuddyAPIClient.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyAPITests/BrainDumpAPITests.swift"
      ],
      "depends_on": [],
      "tests": ["sh ios/scripts/swift-linux.sh test --filter BrainDumpAPITests"],
      "acceptance": [
        "Every route sends the documented method, path, body and headers; the upload carries its media type and SHA-256 and no Idempotency-Key",
        "The manifest hash equals the web's for the same chunk list and SHA-256 matches the FIPS vectors"
      ],
      "budget": {"product_loc": 400, "files": 4},
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-02",
      "outcome": "A platform-neutral model runs the whole voice brain dump, from consent to saved Inbox tasks, and is tested on Linux",
      "tasks": ["T004", "T005", "T006"],
      "requirements": ["031-FR-001", "031-FR-003", "031-FR-004", "031-FR-005", "031-FR-006", "031-FR-007", "031-FR-008", "031-FR-009", "031-FR-010", "031-FR-011", "031-FR-012", "031-FR-013", "031-FR-014", "031-FR-015", "031-SC-002", "031-SC-003", "031-SC-004"],
      "paths": [
        "ios/BrainBuddyKit/Sources/BrainBuddyWorkspace/VoiceBrainDump",
        "ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/VoiceBrainDumpModelTests.swift"
      ],
      "depends_on": ["PR-01"],
      "tests": ["sh ios/scripts/swift-linux.sh test --filter VoiceBrainDumpModelTests"],
      "acceptance": [
        "No request leaves before consent and Record, apart from the flag and the providers",
        "Every phase is reached with a fake server; stale responses are ignored and a 409 reloads the operation"
      ],
      "budget": {"product_loc": 400, "files": 5},
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-03",
      "outcome": "The app can record what the person says as AAC audio with an on-device live transcript, behind the kit's recorder protocol",
      "tasks": ["T007", "T010"],
      "requirements": ["031-FR-005", "031-FR-006", "031-FR-016"],
      "paths": [
        "ios/BrainBuddy/Screens/Capture/Voice/AppleVoiceRecorder.swift",
        "ios/project.yml"
      ],
      "depends_on": ["PR-02"],
      "tests": ["CI ios-app lane: xcodebuild -project ios/BrainBuddy.xcodeproj -scheme BrainBuddy -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build"],
      "acceptance": [
        "The app builds with the recorder and declares the microphone and speech usage descriptions",
        "Recognition runs on the device only and the audio file is deleted after stop or cancel"
      ],
      "budget": {"product_loc": 300, "files": 2},
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-04",
      "outcome": "iPhone shows screen 11: the voice button in capture opens the voice sheet, which records, shows the heard words, reviews the steps and adds them to the Inbox",
      "tasks": ["T008", "T009"],
      "requirements": ["031-FR-001", "031-FR-002", "031-FR-013", "031-FR-014", "031-SC-001"],
      "paths": [
        "ios/BrainBuddy/Screens/Capture/Voice/VoiceCaptureSheet.swift",
        "ios/BrainBuddy/Screens/Capture/Voice/VoiceCaptureParts.swift",
        "ios/BrainBuddy/Screens/Capture/CaptureSheet.swift"
      ],
      "depends_on": ["PR-02", "PR-03"],
      "tests": ["CI ios-app lane: xcodebuild -project ios/BrainBuddy.xcodeproj -scheme BrainBuddy -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build"],
      "acceptance": [
        "The app builds; the sheet uses only Carry On tokens and matches cell M11 apart from the deviations in design.md",
        "On a device with the flag on, three spoken actions become three Inbox tasks"
      ],
      "budget": {"product_loc": 400, "files": 3},
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-05",
      "outcome": "The feature is closed with acceptance, traceability and the delivery report",
      "tasks": ["T011"],
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
