# Feature Specification: Mac voice on Apple speech, Whisper on request

**Feature Branch**: `037-mac-voice-apple-speech`

**Created**: 2026-10-17

**Status**: Direction decided by Max on 2026-10-17. Three detail questions (D1–D3 below) were
put to him with a recommended answer each; this spec follows the recommendations until he
answers. Intake: [intake.md](intake.md). Design: [design.md](design.md). Plan:
[plan.md](plan.md). Tasks: [tasks.md](tasks.md).

**Input**: Max, 2026-10-17: «Выходим на встроенную и даем пользователю возможность скачивать
Whisper, если он захочет. Потому что Whisper нужен для распознавания других языков, кроме
там, тех, которые Mac распознает.»

## Context

The Mac voice sheet (board 11, Mac; spec 021) records speech, turns it into one editable
transcript on the Mac and offers "Use as task draft". Today the transcription is WhisperKit
with the `openai_whisper-base` model copied into the app bundle by `macos/build_app.sh`,
≈145 MB of the app's size. The iPhone already uses Apple's built-in on-device recognition.

This feature makes Apple's on-device speech recognition the Mac's default and turns Whisper
into an optional download, kept for the languages Apple does not recognise on that Mac and for
automatic language detection. The sheet's flow (record, stop & transcribe, edit, use as task
draft) does not change. Audio and text still never leave the Mac; the only network request is
the model download the person starts.

Primary-loop impact: capture by voice on the Mac keeps working as before, in more languages,
with a much smaller app. No rule of clarify → organise → review changes.

## Clarifications

### Session 2026-10-17

- Q: Keep Whisper bundled or switch? → A: **Apple's built-in recognition by default; the
  person may download Whisper for other languages.** *Max.*
- Q (D1): Which Whisper model is offered? → A: **Pending; recommended and built: only
  `openai_whisper-base` (≈145 MB).**
- Q (D2): Where is the download offered? → A: **Pending; recommended and built: in Settings →
  Voice, and from the voice sheet when the chosen language needs Whisper.**
- Q (D3): Which engine runs once Whisper is downloaded? → A: **Pending; recommended and built:
  Apple for every language it recognises on this Mac, Whisper for the rest and for "Auto".**
- Q: Is a recording kept? → A: **No**, as today: the temporary recording is deleted once it is
  transcribed or discarded.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Dictate in my language with nothing to download (Priority: P1)

A person whose Mac is set to English and Russian opens the voice sheet, records, stops, and
gets the transcript.

**Independent Test**: on a fresh install with no Whisper downloaded, record in English and in
Russian; both transcribe on the Mac with the network off.

**Acceptance Scenarios**:

1. **Given** no Whisper is downloaded, **When** the voice sheet opens, **Then** its language
   chips are the person's preferred languages (at most three, plus English when it is not
   among them) and the chip of the first one Apple recognises on this Mac is chosen.
2. **Given** a chosen language that Apple recognises on this Mac, **When** the person records
   and presses "Stop & transcribe", **Then** the transcript appears from Apple's on-device
   recognition, with the network off.
3. **Given** the person has not yet allowed speech recognition, **When** they first start a
   recording, **Then** macOS asks once; if they decline, the sheet says speech recognition is
   off and names where to turn it on, and keeps no recording.

### User Story 2 - Download Whisper for another language (Priority: P2)

A person who speaks a language Apple does not recognise on this Mac, or who wants automatic
language detection, downloads Whisper once.

**Independent Test**: choose a language without Apple support, follow "Download in Settings",
download, return, transcribe in that language.

**Acceptance Scenarios**:

1. **Given** no Whisper and a chosen language Apple does not recognise here, **Then** the sheet
   says that language needs Whisper, offers "Download in Settings…", and Record is unavailable.
2. **Given** Settings → Voice with no Whisper, **Then** it shows the model, its size (about
   145 MB), that it comes from Hugging Face and that speech never leaves the Mac, and a
   Download button.
3. **When** the person presses Download, **Then** progress is shown with Cancel; on success the
   row reads Downloaded with Remove; on failure it shows what went wrong and Try again; Cancel
   leaves nothing half-downloaded behind.
4. **Given** Whisper is downloaded, **Then** the voice sheet adds "Auto", the language that
   needed it becomes recordable, and recording in it transcribes with Whisper on the Mac.

### User Story 3 - Take the space back (Priority: P3)

**Acceptance Scenarios**:

1. **Given** Whisper is downloaded, **When** the person presses Remove in Settings → Voice,
   **Then** the model files are deleted, the row returns to Download, and the voice sheet drops
   "Auto" and the Whisper-only languages.

### Edge Cases

- Apple's recogniser is temporarily unavailable for a supported language (for example its
  on-device assets are still being installed by macOS): the sheet shows the error from the
  system and keeps the recording out of the way; it never silently falls back to the network.
- The downloaded model is damaged or partly deleted outside the app: it counts as not
  downloaded; the person can download it again.
- The Mac goes offline during the download: the download fails with Try again; recognition with
  Apple keeps working.
- "Auto" is chosen and Whisper is later removed: the sheet chooses the first Apple language.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The Mac app bundle MUST NOT contain a speech model; `macos/build_app.sh` MUST
  NOT copy one.
- **FR-002**: By default, voice transcription on the Mac MUST use Apple's speech
  recognition with on-device recognition required, so no audio is sent to Apple or anyone else.
- **FR-003**: The voice sheet's language chips MUST be the person's preferred system
  languages (at most three, plus English when absent), followed by "Auto" only while Whisper is
  downloaded. The initially chosen chip MUST be the first one that can be transcribed now.
- **FR-004**: A language MUST be transcribed by Apple when Apple recognises it on device on
  this Mac; otherwise by Whisper when Whisper is downloaded; "Auto" MUST use Whisper.
- **FR-005**: When the chosen language can be transcribed by neither, the sheet MUST say so,
  MUST offer to open Settings → Voice, and MUST NOT start a recording.
- **FR-006**: Settings MUST have a Voice tab showing the speech engine in use and the
  Whisper model's state: not downloaded, downloading with progress, downloaded, or failed.
- **FR-007**: The Whisper download MUST start only from the person pressing Download, MUST
  be cancellable, and MUST leave no partial model behind on cancel or failure.
- **FR-008**: Remove MUST delete the downloaded model files.
- **FR-009**: The only network access added by this feature MUST be the model download from
  Hugging Face (`argmaxinc/whisperkit-coreml`, `openai/whisper-base`); the transcription sources
  MUST have no network API (keeps 021-FR-029 and 021-FR-010).
- **FR-010**: The temporary recording MUST be deleted after transcription, discard or
  close, whichever engine ran.

### Key Entities

- **Whisper model state**: not downloaded | downloading(fraction) | downloaded | failed(message).
  Stored only as files on disk; nothing else is persisted.

## Success Criteria *(mandatory)*

- **SC-001**: The app built by `macos/build_app.sh` has no `.mlmodelc` and no `Whisper`
  resource folder (≈145 MB less).
- **SC-002**: With Whisper not downloaded and the network off, English dictation produces a
  transcript on a Mac where Apple recognises English on device.
- **SC-003**: After the download, "Auto" transcribes with Whisper; after Remove, the model
  folder no longer exists.
