# Feature Specification: iPhone voice brain dump

**Feature Branch**: `031-ios-voice-brain-dump`

**Created**: 2026-10-16

**Status**: Clarified by Max on 2026-10-16 (D2: the brain dump runs on the iPhone, on local
models; cloud processing is a later opt-in, not built now). One question is open on the
thread's decision card (D4, step extraction for languages Apple's model does not support);
the spec follows its recommended answer. Design: [design.md](design.md). Plan:
[plan.md](plan.md). Tasks: [tasks.md](tasks.md).

**Input**: "Build iPhone voice capture per Carry On board 11." Max, 2026-10-16: «мы делаем
брейндамп, как на холсте, но работает он локально, на локальных моделях. Если у
пользователя есть желание, он может включить облако … Но облако мы пока не добавляем.»
Design input: canvas cell M11 iPhone, "11 Voice capture" (design data).

## Context

Screen 11 draws a brain dump on iPhone as a sheet over the current list: "What feels
heaviest?", the words being heard, "Steps I heard · Not saved yet" with one row per step
(its project and day underneath, tap to edit, × to drop), "Tap a step to edit it. Nothing
reaches your lists until you add it.", and the floating glass bar with the live voice
button, "Listening" and "Add 3 to Inbox". Its caption: "Steps appear while you talk; you
keep, edit or drop each one."

The iPhone builds this entirely on the device: Apple's on-device speech recognition turns
speech into text, and Apple's on-device language model (Foundation Models) turns the text
into steps. Nothing is sent anywhere and no account is needed. The steps become ordinary
captured tasks through the same path as the capture sheet, so they work offline and sync
like any other task. The web's server brain dump and a cloud option are not part of this
feature.

## Clarifications

### Session 2026-10-16

- Q: Which voice behaviour on iPhone? → A: **The brain dump on the canvas, on local models;
  no cloud for now.** *Max (D2).*
- Q: Steps while talking, and a project and day under each step? → A: **Yes, as the
  canvas.** The steps are re-read from the words heard while the person talks; a project is
  shown only when it names an existing project, a day only when one was said. *Agent, from
  D2 ("как на холсте").*
- Q: What if the on-device model is unavailable (older iPhone, Apple Intelligence off) or
  the language is not one it supports? → A: **Pending (D4).** Recommended and built: give
  the text to the model anyway when it is available; when it is not, each sentence becomes
  a step without a project or day, for the person to edit.
- Q: Where do added steps go? → A: **The Inbox**, through ordinary capture. A step with a
  project lands in that project, as a capture with a project does today.
- Q: Is any audio kept? → A: **No.** Recognition streams from the microphone; no recording
  is written.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Dump what is on my mind and keep the steps (Priority: P1)

The person opens capture, taps the voice button, says «the garage is a mess, Sam needs the
van back by Friday, and I still haven't found the tax letter», and taps "Add 3 to Inbox".

- **Given** the capture sheet is open, **Then** the glass bar shows the voice button on its
  leading side, and tapping it opens the voice sheet already listening.
- **Given** the person is talking, **Then** the words heard appear under the title, the bar
  says "Listening", and steps appear and update under "Steps I heard · Not saved yet".
- **When** the person taps "Add 3 to Inbox", **Then** listening stops, each kept step is
  captured, the sheet closes and a toast says "Added 3 to Inbox".

### User Story 2 - Fix the steps before they land (Priority: P2)

- **When** the person taps a step and changes its words, **Then** the row keeps the new
  words, and later updates from speech never overwrite it.
- **When** the person taps × on a step, **Then** it disappears, does not come back as the
  person keeps talking, and the count on the add button drops.

### User Story 3 - Stop and look before adding (Priority: P3)

- **When** the person taps the live voice button, **Then** listening stops, the steps are
  read once more from everything heard, and the sheet stays open for review.
- **Given** nothing actionable was heard, **Then** the sheet says so and the add button is
  disabled.

### User Story 4 - Leave safely (Priority: P4)

- **Given** words were heard and not added, **When** the person closes the sheet, **Then**
  a confirmation asks first; its safe choice keeps everything.

### Edge Cases

- Microphone or speech permission denied: nothing is recorded; the sheet says how to allow
  it in Settings.
- On-device recognition unavailable for the chosen language: the sheet says so and offers
  the other language.
- The model fails or is unavailable: the steps come from sentences (D4) and the sheet keeps
  working.
- A step names a project that does not exist: the step has no project (capture never
  creates one from speech).
- A save fails part way: the saved steps leave the list, the rest stay with the error.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The capture sheet's glass bar MUST show the voice button on its leading side;
  tapping it opens the voice sheet, which starts listening at once.
- **FR-002**: The voice sheet MUST follow canvas cell M11 iPhone: a large sheet over the
  current list, the serif title "What feels heaviest?", the heard text with a caret while
  listening, "Steps I heard" with "Not saved yet", step rows on `control-quiet` with an
  open circle, the title, a meta line "{project} · {day}" when either exists, and ×, the
  footer "Tap a step to edit it. Nothing reaches your lists until you add it.", and the
  floating glass bar (voice button, status word, "Add {n} to Inbox"). Colours are the Carry
  On tokens only.
- **FR-003**: Speech MUST be recognised on the device only; the sheet offers Russian and
  English, starting with the device language when it is one of them, else English.
- **FR-004**: While listening, the steps MUST be read again from the whole heard text after
  each pause in new words (debounced), replacing the steps the person has not edited, and
  keeping the order said.
- **FR-005**: Steps MUST come from the on-device language model when it is available, and
  from one step per sentence otherwise or when the model fails (D4).
- **FR-006**: A step's project MUST be shown and used only when it matches an existing
  active project's name (case-insensitive); a step's day only when the model gives one.
- **FR-007**: An edited step MUST keep its words; a removed step MUST not reappear while the
  person keeps talking (matched by its normalised words).
- **FR-008**: The add button MUST read "Add {n} to Inbox" for the {n} listed steps and be
  enabled when {n} > 0 and nothing is being saved; while listening it stops listening first.
- **FR-009**: Adding MUST capture each step as its own task (Inbox, its project, its day),
  in order, with a stable editor id per step so a retry never adds a step twice; on success
  the sheet closes and a toast says "Added {n} to Inbox".
- **FR-010**: If a capture fails, the steps already captured MUST leave the list and the
  rest stay with the error shown.
- **FR-011**: Tapping the live voice button MUST stop listening and read the steps once
  more from the whole text; with no step the sheet says "Nothing to add yet." and the add
  button is disabled.
- **FR-012**: Closing with heard words or steps not added MUST ask "Discard what you said?"
  first; the safe choice keeps everything.
- **FR-013**: No audio file is written and no heard text or step is logged or sent off the
  device. The app declares microphone and speech-recognition usage descriptions.

### Key Entities

- **Heard step**: words, an optional project (an existing project), an optional day, and
  whether the person edited it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A dump of three distinct actions becomes three Inbox tasks with one tap and no
  edit, offline and signed out.
- **SC-002**: No network request is made by the voice sheet.
- **SC-003**: Every state of the sheet (listening, review, empty, saving, saved, permission
  denied, unavailable) is reached in the model's tests with fakes.
- **SC-004**: An edited or removed step is never overwritten or revived by later speech.

## Dependencies

- Apple Speech (on-device recognition) and Foundation Models (iOS 26, Apple Intelligence).
- The capture path (`Workspace.capture(_:editorID:)`), the capture sheet (board 10, PR
  #439) and the shared glass bar.

## Follow-ups (not in scope)

- Cloud processing as an opt-in (the server brain dump the web uses), when Max asks.
- Other languages, and a downloaded model for languages Apple's model lacks (D4).
- Routing the model call through the shared AI policy (spec 026) if it must cover
  on-device-only uses too.

## Assumptions

- Apple's on-device recognition supports Russian and English on current iPhones.
- iOS 26 is the deployment target, so Foundation Models is always linkable; availability
  is checked at run time.
