# Business Intake: iPhone voice brain dump

**Feature**: `specs/031-ios-voice-brain-dump/`
**Created**: 2026-10-16
**Interviewee**: Max (product owner), through the project's coordinator and the decision
card in the thread "Голосовой ввод на iPhone (экран 11)"
**Status**: The ask is approved (Max, 2026-10-16: build the remaining Carry On screens on
iPhone). One product question is open on the thread's decision card (D2 below); work
proceeds on the recommended answer and this file is updated when Max answers.

Assessment was skipped: the ask is a bounded native surface drawn on the Carry On design
canvas (cell **M11 iPhone**, "11 Voice capture"), and every capability it exposes already
exists on the server and on the web (specs 002, 005, 015: the voice brain dump). No
matching assessment or kill verdict exists under `.specify/assessments/`.

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
| Backend (`backend/app/api/tasks.py`, `/brain-dump-operations`) | The brain dump protocol the web uses; frozen, unchanged by this feature. |
| iPhone | No voice. The capture sheet's glass bar leaves the board's voice button unbuilt. |

## Decisions

- **D1** (Max, 2026-10-16): build the canvas screens that need new iPhone features; the
  coordinator starts one thread per feature. Colours exactly as the canvas; do not invent
  behaviour that the code does not have; ask Max when unsure.
- **D2** (open, decision card 2026-10-16): which behaviour iPhone voice has. Options:
  brain dump from the server (recommended: it is what screen 11 draws and it already
  exists on the web and backend), the Mac's one-task draft on device, or both. Work
  proceeds on the recommendation.
- **D3** (agent, from D1's "don't invent behaviour"): the canvas shows steps appearing
  while the person talks and a project and date under each step. The code produces
  title-only Inbox tasks, once, after Stop (spec 015, 015-FR-001 and 015-FR-003). The
  iPhone follows the code: the live transcript shows while talking, steps after Stop,
  and a step shows its title only. Recorded in `design.md` § Deviations.

## Out of scope

- Any backend or web change (the Python backend is frozen; the protocol is used as is).
- Pause and resume while recording, the privacy-controls screen for a recording started
  elsewhere, and resuming an earlier recording after the sheet is closed: the web has
  them, the canvas does not draw them. Recorded as follow-ups.
- Voice without an account (D2 option "both").
- Mac changes.
