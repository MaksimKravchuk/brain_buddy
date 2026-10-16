# Feature Specification: iPhone voice brain dump

**Feature Branch**: `031-ios-voice-brain-dump`

**Created**: 2026-10-16

**Status**: Clarified on the recommended answer to D2 (see [intake.md](intake.md)); updated
when Max answers the decision card. Design: [design.md](design.md). Plan:
[plan.md](plan.md). Tasks: [tasks.md](tasks.md).

**Input**: "Build iPhone voice capture per Carry On board 11 (today voice exists only on
Mac; reuse its logic where it fits)." Design input: canvas cell M11 iPhone, "11 Voice
capture" (design data).

## Context

The web already has a voice brain dump (specs 002, 005, 015). The person consents to cloud
processing, speaks, and stops. The server transcribes the audio accurately and turns it
into GTD next actions ("proposals"): verb first, in the language spoken, fillers and
duplicates dropped. The person keeps, edits or drops each one, then saves them; each
becomes a native Inbox task. Nothing reaches the lists before that save.

Screen 11 on the canvas draws the same flow on iPhone as a sheet over the current list:
"What feels heaviest?", the words being heard, "Steps I heard · Not saved yet" with one row
per step (tap to edit, × to drop), "Tap a step to edit it. Nothing reaches your lists until
you add it.", and the floating glass bar with the live voice button, "Listening" and
"Add 3 to Inbox".

This feature builds that sheet on iPhone against the existing protocol, with no backend
change. The Mac keeps its own on-device draft (spec 021).

## Clarifications

### Session 2026-10-16

- Q: Which voice behaviour on iPhone? → A: **The server brain dump**, as screen 11 draws
  and the web does (recommended answer on the decision card, D2; pending Max).
- Q: Steps while talking, and a project and date under each step, as the canvas draws? →
  A: **No.** The code proposes title-only Inbox tasks once, after Stop (015-FR-001,
  015-FR-003). While talking the sheet shows the words heard. *Agent, from Max's rule
  "don't invent behaviour" (D1, D3).*
- Q: Where does the live text come from? → A: **On-device speech recognition only**, the
  native counterpart of the web's browser preview. It is a readout and a recovery source,
  never a task source; it is never sent to Apple's servers. *Agent.*
- Q: Is consent remembered between recordings? → A: **No.** As on the web, the consent
  switch starts off every time the sheet opens, and the start request carries it.
  *Agent.*
- Q: What happens to an unsaved recording when the sheet closes? → A: **It is discarded
  after a confirmation**, because the iPhone has no screen that lists recordings to return
  to (as 015 decided for the web's processing screen). *Agent.*

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Dump what is on my mind and keep the steps (Priority: P1)

Signed in, with voice brain dump on for the account, the person opens capture, taps the
voice button, allows cloud processing, says «the garage is a mess, Sam needs the van back
by Friday, and I still haven't found the tax letter», and taps the voice button again.

- **Given** the capture sheet is open and the account has voice brain dump, **Then** the
  glass bar shows the voice button on its leading side.
- **Given** the voice sheet is open, **When** cloud processing is not allowed, **Then**
  recording cannot start and the sheet says why.
- **Given** recording, **Then** the words heard appear under the title and the bar says
  "Listening"; no step exists yet.
- **Given** the person stops, **When** processing finishes, **Then** "Steps I heard"
  lists each proposed step, "Not saved yet" shows, and "Add 3 to Inbox" is enabled when
  the server says the steps can be saved.
- **When** the person taps "Add 3 to Inbox", **Then** the steps become Inbox tasks, the
  sheet closes and a toast says "Added 3 to Inbox".

### User Story 2 - Fix the steps before they land (Priority: P2)

- **When** the person taps a step and changes its words, **Then** the new title is saved
  to the recording when editing ends, and the row shows it.
- **When** the person taps × on a step, **Then** it disappears and the count on the add
  button drops.
- **Given** a step has a conflict, **Then** it shows the person's text and the suggestion
  with "Keep mine" and "Use suggestion", and adding waits until every conflict is settled.

### User Story 3 - Nothing useful was said, or processing failed (Priority: P3)

- **Given** no step survived, **Then** the sheet says nothing was proposed, shows what
  was heard, offers no add button, and discarding returns to a fresh recording.
- **Given** processing failed, **Then** the sheet names the stage and offers exactly the
  recovery actions the server allows (retry, review provisional steps, extract steps from
  the live transcript, delete the recording).

### User Story 4 - Leave safely (Priority: P4)

- **Given** a recording exists that is not saved, **When** the person closes the sheet or
  chooses a discard action, **Then** a confirmation asks first; its safe choice keeps
  everything as it was, and its destructive choice discards the recording on the server.

### Edge Cases

- On-device recognition is unavailable for the language: recording works, the sheet shows
  "Listening" without live text, and no live-transcript recovery is offered.
- The microphone or speech permission is denied: nothing is sent; the sheet says how to
  allow it in Settings.
- Network fails during upload or a command: the sheet shows the error with its reference
  id; retrying sends the same bytes or the same command again.
- A newer operation revision exists (409): the sheet reloads the operation and shows the
  server's message.
- The recording reaches 30 minutes: recording stops on its own and processing starts.
- The account signs out while the sheet is open: the next request fails as unauthorized
  and the sheet says so; nothing is kept on the device.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The capture sheet MUST show the voice button only when an account is signed
  in and its `/auth/me` answer has `feature_flags.voice_brain_dump` true. Otherwise the
  bar looks as it does today; there is no account wall.
- **FR-002**: The voice sheet MUST follow canvas cell M11 iPhone: a large sheet with a
  grabber over the current list, the serif title "What feels heaviest?", the heard text,
  "Steps I heard" with "Not saved yet", step rows on `control-quiet` with an open circle
  and ×, the footer "Tap a step to edit it. Nothing reaches your lists until you add it.",
  and the floating glass bar (voice button, status word, trailing action). Colours are the
  Carry On tokens only.
- **FR-003**: Before recording, the sheet MUST load the configured providers; recording
  is possible only when an accurate speech-to-text provider is named. A switch "Allow
  secure cloud processing: speech-to-text by {stt}, task extraction by {reconciler}.
  Audio is not sent without this consent." starts off each time the sheet opens, and a
  language choice offers "Russian + English" (default), "Russian" and "English".
- **FR-004**: Starting MUST send the consent (microphone, external processing, the
  provider and the providers, the language hints) with an Idempotency-Key and receive an
  operation in `recording`.
- **FR-005**: The device MUST record mono AAC audio for at most 30 minutes and, after
  Stop, upload it as numbered chunks starting at 0, each with its SHA-256 in
  `X-Content-SHA256`, then seal with `expected_chunks` and the manifest hash computed from
  the server's chunk list (sorted by number; compact JSON objects `chunk_number`,
  `sha256`, `size_bytes` in that order; SHA-256 of the UTF-8 bytes, lowercase hex).
- **FR-006**: While recording, the heard text MUST come from on-device recognition only.
  Each result is appended to the operation as a transcript segment: interim results reuse
  the open sequence number, a final result closes it. No step exists before Stop.
- **FR-007**: While the server processes, the sheet MUST show the status in words
  (Sealing audio, Processing audio, Improving transcript, Reconciling tasks, Saving tasks)
  and poll the operation after 1.5 s, doubling the delay up to 8 s, until the status
  leaves processing.
- **FR-008**: The review MUST list the operation's non-deleted proposals in server order.
  Editing a title sends it when editing ends, trimmed, only if it changed and is not
  empty; × sends `deleted`; a conflict offers "Keep mine" and "Use suggestion". Proposal
  edits are sent one at a time, each with the latest revision.
- **FR-009**: The add button MUST read "Add {n} to Inbox" for the {n} listed steps and be
  enabled only when the operation is `committable` and no listed step has a conflict;
  with conflicts the sheet says "Resolve {n} conflict(s) before adding."
- **FR-010**: When steps are provisional or not yet saveable, the sheet MUST say so in
  the web's words (015-FR-010).
- **FR-011**: A review with no step MUST say "No steps were proposed from this. Here is
  what was heard; discard it to record again.", show the heard text and offer no add
  button; discarding returns to a fresh recording.
- **FR-012**: After a failure the sheet MUST name the stage ("Accurate transcription" or
  "Task reconciliation", "paused" when retry is allowed, otherwise "failed"), show the
  server's error, and offer only the actions in `available_recovery_actions`.
- **FR-013**: Every destructive exit (closing with an unsaved recording, discard while
  recording, cancel processing, discard all steps, delete the recording) MUST ask first
  with the platform dialog; the safe choice keeps everything; the destructive choice
  sends `cancel`.
- **FR-014**: Adding MUST send `commit`; on success the sheet closes, a toast says "Added
  {n} to Inbox" and the workspace syncs so the new Inbox tasks appear.
- **FR-015**: Errors MUST show the server's message and its reference id. A stale
  revision (409) reloads the operation before the message shows. A response older than
  the operation already held is ignored.
- **FR-016**: The recorded audio MUST exist only as a temporary file that is deleted after
  upload, discard or close; no audio, transcript or step text is logged. The app declares
  microphone and speech-recognition usage descriptions.

### Key Entities

- **Recording** (server operation): status, consent, transcript segments, proposals,
  audio chunks, revision, `committable`, `available_recovery_actions`.
- **Step** (proposal): ordinal, title, status, conflicts, deleted.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A dump of three distinct actions becomes three Inbox tasks with one tap
  after processing and no edit.
- **SC-002**: No request leaves the device before consent is on and Record is tapped,
  apart from reading the flag and the providers.
- **SC-003**: Every state of the sheet (consent, recording, processing, review, empty,
  failure) is reachable in the model's tests with a fake server.
- **SC-004**: Closing the sheet never leaves an unsaved recording on the server without
  the person confirming its discard.

## Dependencies

- Backend voice brain dump routes (`backend/app/api/tasks.py`), unchanged.
- iOS sign-in (spec 021 sync, `Workspace.account`) and the session token in the Keychain.
- The capture sheet (board 10, PR #439) and the shared glass bar `BBGlassActionBar`.

## Follow-ups (not in scope)

- Pause and resume, the privacy-controls screen, resuming a recording after closing.
- Voice without an account (D2 option "both"), if Max chooses it.
- Steps while talking, and a project or date per step, if the backend ever proposes them.

## Assumptions

- The backend accepts `audio/mp4` (AAC in MP4) chunks; a whole recording of at most 30
  minutes at 32 kbit/s fits the 10 MiB chunk limit, so it uploads as chunk 0.
- The flag answer of `/auth/me` is read when the capture sheet opens; a change during the
  sheet's life applies the next time.
