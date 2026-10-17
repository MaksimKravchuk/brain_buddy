# Tasks: Mac voice on Apple speech, Whisper on request

One PR. Paths are under `macos/` unless stated.

## Phase 1 — pure pieces (tests first)

- [x] T001 `VoiceLanguagePlanTests` for chips, initial choice, engine per language and the
      needs-Whisper case (037-FR-003, 037-FR-004, 037-FR-005).
- [x] T002 `BrainBuddyMacCore/VoiceLanguagePlan.swift` to pass T001.
- [x] T003 `WhisperModelFilesTests` for complete/partial detection, staging discard and remove
      (037-FR-007, 037-FR-008).
- [x] T004 `BrainBuddyMacCore/WhisperModelFiles.swift` and `VoiceSettingsCopy.swift`.

## Phase 2 — engines and download

- [x] T005 `AppleSpeechTranscriber` in `VoiceCapture.swift`; the sheet picks the engine from
      the plan; Whisper reads the downloaded folder (037-FR-002, 037-FR-004, 037-FR-010).
- [x] T006 `WhisperDownload.swift`: download into staging, move into place, cancel, remove
      (037-FR-007, 037-FR-008, 037-FR-009).
- [x] T007 `NSSpeechRecognitionUsageDescription` in `AppInfo.plist`.

## Phase 3 — UI

- [x] T008 Voice sheet note V-01c with "Download in Settings…", V-01f message (037-FR-005).
- [x] T009 Settings › Voice tab S-05a–d, tab icon (037-FR-006).

## Phase 4 — build, guards, docs

- [x] T010 `build_app.sh` stops requiring and copying the model (037-FR-001, 037-SC-001).
- [x] T011 Update `MacPrivacyGuardTests` and the Settings tab tests (037-FR-001, 037-FR-009,
      037-FR-006).
- [x] T012 `macos/README.md`, `docs/native-macos-app.md`: Apple speech by default, optional
      Whisper.
- [ ] T013 Live check on Max's Mac (037-SC-001, 037-SC-002, 037-SC-003).
