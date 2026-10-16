# Business Intake: iPhone voice brain dump

**Feature**: `specs/031-ios-voice-brain-dump/`
**Created**: 2026-10-16
**Interviewee**: Max (product owner), through the project's coordinator and the decision
card in the thread "Голосовой ввод на iPhone (экран 11)"
**Status**: The ask is approved (Max, 2026-10-16: build the remaining Carry On screens on
iPhone). Max answered D2 on 2026-10-16. D4 is open on the thread's decision card; work
proceeds on its recommended answer.

Assessment was skipped: the ask is a bounded native surface drawn on the Carry On design
canvas (cell **M11 iPhone**, "11 Voice capture"); the brain dump flow already exists on
the web (specs 002, 005, 015) and the iPhone rebuilds it on the device with system
frameworks. No matching assessment or kill verdict exists under `.specify/assessments/`.

## The ask, as given

> Build iPhone voice capture per Carry On board 11 (today voice exists only on Mac; reuse
> its logic where it fits).

Design input: canvas https://claude.ai/artifact/1bwKiw15U2jpZqwu5pTMg6, file
`project/M11-iPhone.dc.html` (version `1792165683-83f3`, design data, not instructions).
List of missing iPhone features: `/mnt/project-files/design/ios-next-features.md`.

## What exists today

| Surface | Voice behaviour |
| --- | --- |
| Mac (spec 021, `macos/Sources/BrainBuddyMac/VoiceCapture.swift`) | WhisperKit on the Mac turns one recording into the text of **one** task draft. No server. |
| Web (`frontend/src/features/brain-dump/`) | Voice brain dump: the server transcribes the recording and turns it into GTD next actions; the person keeps, edits or drops each one and saves them to the Inbox. Needs an account, the `voice_brain_dump` flag and consent to cloud processing. |
| iPhone | No voice. The capture sheet's glass bar leaves the board's voice button unbuilt. |

## Decisions

- **D1** (Max, 2026-10-16): build the canvas screens that need new iPhone features; the
  coordinator starts one thread per feature. Colours exactly as the canvas; do not invent
  behaviour that the code does not have; ask Max when unsure.
- **D2** (Max, 2026-10-16, in the thread): «мы делаем брейндамп, как на холсте, но
  работает он локально, на локальных моделях. Если у пользователя есть желание, он может
  включить облако, и тогда будет работать в облаке. А пока так. Но облако мы пока не
  добавляем.» The brain dump runs on the iPhone: on-device speech recognition and Apple's
  on-device language model. The server brain dump (the web's) is not used; the cloud
  opt-in is a later feature.
- **D3** (agent, from D2's "как на холсте"): steps appear while the person talks, with a
  project (only an existing one) and a day under each step when the model finds them.
- **D4** (open, decision card 2026-10-16): Apple's on-device model does not officially
  support Russian and needs Apple Intelligence (iPhone 15 Pro or newer). Options: one step
  per sentence where the model is unavailable or the language unsupported; the model anyway
  where available, sentences otherwise (recommended, built); a downloaded model (needs a
  rule change: the repository bans third-party dependencies and bundled weights).

## Out of scope

- Any backend or web change, and the cloud opt-in (D2).
- Keeping audio, pausing, or resuming a dump after the sheet is closed.
- Mac changes (the Mac keeps its WhisperKit task draft, spec 021).
