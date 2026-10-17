# Business Intake: Mac voice on Apple speech, Whisper on request

**Feature**: `specs/037-mac-voice-apple-speech/`
**Interviewed**: 2026-10-17
**Interviewee**: Max (project owner), in the project thread "Размер приложений"

Assessment (stage 0) skipped: the owner decided the direction himself after a size
investigation in the same thread; the change is small and wanted.

## The ask, as given

> «Слушай, а мы можем как-то уменьшить размер наших приложений? … Какой там сейчас размер на
> айфоне и на макосе?»
>
> «Выходим на встроенную и даем пользователю возможность скачивать Whisper, если он захочет.
> Потому что Whisper нужен для распознавания других языков, кроме там, тех, которые Mac
> распознает.»

## 1. Problem

- **Whose problem**: anyone installing the Mac app.
- **How it shows up today**: the Mac app carries the WhisperKit `openai_whisper-base` model
  (≈145 MB) inside its bundle (`macos/build_app.sh`), so the app is ≈150 MB or more, while
  the iPhone app, which uses Apple's built-in on-device recognition, is a fraction of that.
- **What it costs**: a heavy download and install for a task app; most people only need the
  languages Apple already recognises on their Mac.
- **If we build nothing**: the Mac app stays ≈6× larger than it needs to be.

## 2. Customer and persona

- **Primary**: a person capturing tasks by voice on the Mac.
- **Secondary**: a person who speaks a language Apple does not recognise on device.
- **Deployment shape**: single-user per Mac; no server involvement.

## 3. Business objective and KPI

| metric | baseline today | target | by when |
|---|---|---|---|
| Speech model bytes inside the Mac app bundle | ≈145 MB (whisper-base) | 0 | this feature |
| Languages a person can dictate in on the Mac | Russian, English, Auto | every language Apple recognises on that Mac, plus Whisper's languages after the optional download | this feature |

## 4. Scope boundary

**In scope**

- [x] Voice on the Mac uses Apple's built-in on-device speech recognition by default.
- [x] The voice sheet offers the languages that can be recognised on this Mac.
- [x] Settings gains a Voice tab where the person can download Whisper, see progress, cancel,
      retry and remove it.
- [x] The voice sheet points to that download when the chosen language needs Whisper.
- [x] With Whisper downloaded: Apple for the languages it recognises, Whisper for the rest
      and for automatic language detection.
- [x] The Whisper model is no longer bundled.

**Out of scope — explicitly confirmed by the human**

- [x] Cloud recognition of any kind.
- [x] Any change to the iPhone app.
- [x] Splitting speech into several tasks (the Mac keeps one editable transcript).
- [x] Any model other than Whisper base.

**Confirmed by**: Max on 2026-10-17 for the direction (Apple by default, Whisper on request,
no cloud). The read-back of this scope, the non-goals and the three detail questions (model
size, where the download is offered, engine choice) was posted in the thread on 2026-10-17
and is **pending his reply**; spec.md follows the recommended answers until then.

## 5. Constraints

- **Deadline**: none.
- **Platform**: macOS 26 Mac app only.
- **Offline behavior**: required. Recognition never waits for the network; only the optional
  download needs it.
- **Must not break**: 021-FR-010 (the Mac never waits on the network), 021-FR-029 (voice audio
  and transcription stay on the Mac), the voice sheet's design (board 11, Mac).
- **Budget / provider cost limits**: none; no paid provider.

## 6. Compliance obligation

- **New durable records**: the downloaded model files under the app's Application Support
  folder. No audio, no transcript is stored.
- **Consent**: the download starts only when the person presses Download. Apple's speech
  recognition asks the system permission once.
- **Retention**: the model stays until the person removes it in Settings.
- **Export**: not included (it is a public model, not the person's data).
- **Purge**: not account data; removed by the Remove button or with the app's folder.
- **Residency / other obligations**: the model comes from Hugging Face
  (`argmaxinc/whisperkit-coreml`, MIT; tokenizer `openai/whisper-base`, Apache 2.0). The
  request carries no personal data.

## 7. Existing-system dependencies

- Mac app voice sheet (`macos/Sources/BrainBuddyMac/VoiceCapture.swift`), Settings window,
  `macos/build_app.sh`, the privacy guard tests. No backend, no kit, no iPhone change.

## 8. Definition of done

- The Mac app built by `macos/build_app.sh` contains no Whisper model and dictation in English
  and Russian works out of the box (where Apple supports it on that Mac).
- Settings → Voice downloads Whisper with visible progress; after that, "Auto" and other
  languages work in the voice sheet; Remove frees the space.
