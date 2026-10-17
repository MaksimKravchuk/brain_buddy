# Implementation Plan: Mac voice on Apple speech, Whisper on request

**Spec**: [spec.md](spec.md) · **Design**: [design.md](design.md) (V-01a–g, S-05a–d)

## Summary

Swap the Mac's default transcriber from bundled WhisperKit to Apple's `Speech` framework with
on-device recognition required, keep WhisperKit linked for an optional model the person
downloads into Application Support, and add a Settings › Voice tab that owns the download.

## Technical context

- macOS 26, Swift 6, SwiftPM package `macos/` (no Xcode project). Tests: swift-testing in
  `macos/Tests/BrainBuddyMacTests`, run by the CI lane "Mac app on macOS (Xcode 26)".
- Apple speech: `SFSpeechRecognizer(locale:)`, `supportsOnDeviceRecognition`,
  `SFSpeechURLRecognitionRequest` with `requiresOnDeviceRecognition = true` over the existing
  16 kHz mono recording. Authorisation via `SFSpeechRecognizer.requestAuthorization`;
  `NSSpeechRecognitionUsageDescription` added to `macos/AppInfo.plist`.
- Whisper: WhisperKit 0.18.0 (already a dependency). Download with
  `WhisperKit.download(variant: "openai_whisper-base", downloadBase:progressCallback:)` and the
  tokenizer with `ModelUtilities.loadTokenizer(for: .base, tokenizerFolder:)`, both into
  `~/Library/Application Support/BrainBuddyMac/Whisper/` (staging folder, moved into place
  only when complete). Transcription keeps `download: false`.

## Design (module ownership)

| Piece | File | Notes |
|---|---|---|
| Language plan (pure) | `BrainBuddyMacCore/VoiceLanguagePlan.swift` | chips, initial choice, engine per language (037-FR-003/004/005). Foundation only, unit-tested. |
| Copy | `BrainBuddyMacCore/VoiceSettingsCopy.swift` | strings for V-01c/f and S-05. |
| Whisper files (no network) | `BrainBuddyMacCore/WhisperModelFiles.swift` | folder layout, "is complete" check, remove (037-FR-007/008). Unit-tested with a temp folder. |
| Transcribers | `BrainBuddyMac/VoiceCapture.swift` | `AppleSpeechTranscriber` + existing `VoiceTranscriber` (Whisper) reading the downloaded folder; no network API (037-FR-009). |
| Download | `BrainBuddyMac/WhisperDownload.swift` | the only file that calls `WhisperKit.download` / `loadTokenizer`; observable state for S-05. |
| Settings tab | `BrainBuddyMac/Settings/VoiceSettingsTab.swift`, `MacSettingsView.swift`, `CarryOnMacIcons.swift` | S-05, tab + mic icon. |
| Build | `macos/build_app.sh` | stop requiring and copying the model; keep the licence/notice texts. |

## Tests (Constitution Principle II, proportionate)

- `VoiceLanguagePlanTests`: chip list, initial choice, engine per language, "Auto" only with
  Whisper, unavailable language → needs Whisper (037-FR-003/004/005).
- `WhisperModelFilesTests`: complete vs partial folder, remove deletes it, staging is discarded
  (037-FR-007/008).
- `MacPrivacyGuardTests` updated: transcriber sources still have no network API and never set
  `download: true`; `WhisperKit.download` appears only in `WhisperDownload.swift`; build_app.sh
  copies no model (037-FR-001/009/010).
- Settings tab test: Voice is a tab after Sync (037-FR-006).
- Existing voice-sheet snapshots stay byte-identical (V-01a/d/e unchanged).
- Live check on Max's Mac: build_app.sh, dictate English/Russian offline, download, Auto, Remove.

## Risks

- Apple's on-device language list differs per Mac and macOS version → the plan reads it at
  runtime, never hard-codes it.
- Hugging Face layout changes → the download fails visibly with Try again; recognition with
  Apple is unaffected.
