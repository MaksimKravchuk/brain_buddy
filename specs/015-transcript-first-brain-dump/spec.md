# Feature Specification: Transcript-first voice brain dump

**Feature**: `specs/015-transcript-first-brain-dump/` · **Branch**: `claude/brain-dump-mechanics-t35ab7` (PR #194) · **Created**: 2026-09-05

**Status**: retro-specification of behaviour already shipped on the branch. Review campaign 1 ran; the second campaign, acceptance and report were not run (founder's call, 2026-09-05). Open items are listed at the end.

**Narrows** `specs/002-async-voice-workflows/` User Story 1, required outcome 2 and `002-SC-004`: the browser preview is a transcript readout, never a task source. Spec 002 stays hash-frozen as delivered history; the architecture record is ADR-0002 (two amendments dated 2026-09-05).

**Input** (founder, verbatim, see [intake.md](intake.md)): «Не надо показывать просто сырой текст как задачи. Сырой текст хорошо, как статус. Задачи уже должны быть очищены от говна и дубликатов. И перефразированны под гайды GTD.» Then: «у нас превью же текст, почему нельзя восстановить?» and «нет отмены на экране обработки, нет подтверждения Discard, при resume не восстанавливаются хвост и таймер. добавь».

## Clarifications

### Session 2026-09-05

Decisions taken instead of asked; the founder waived the interview and the design sign-off («просто доделай»).

- Q: Rewrite spec 002 in place or record the change as a new feature? → A: **New feature number; 002 untouched** ("path A"). *Founder.*
- Q: How does the owner recover a recording after a terminal failure when only browser transcript text exists? → A: **Reconciler-based extraction from the browser transcript**, not manual task entry. *Founder.*
- Q: How often and at what cost? → A: **Once per recording, within the existing spend ceilings, never automatically.** *Agent.*
- Q: A "leave and come back later" control on the processing screen? → A: **No**; nothing in the app lists in-flight recordings to return to. *Agent.*
- Q: Nested dialogs or inline confirmations? → A: **Inline on the web** (the panel is already a modal); **platform dialog on mobile**. *Agent.*
- Q: Where does the resumed timer start? → A: **From the captured audio duration, pauses excluded.** *Agent.*
- Q: Does FR-006 (transcript and cancel on the processing screen) bind mobile? → A: **Web only** for now; mobile keeps naming the stage. *Agent; open for the founder (Open items 1).*
- Q: What does a refused recovery show? → A: **The server's reason and a reference id**, never a bare status word. *Agent.*

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Clean next actions from a natural dump (Priority: P1)

The owner says «Так, надо купить молоко. Сходить в магазин. Покрасить комнату.» and presses Stop.

- **Given** the recording is sealed, **When** processing finishes, **Then** the review shows exactly «Купить молоко», «Сходить в магазин», «Покрасить комнату», and Send is enabled with nothing to delete.
- **Given** the same action was said twice, **When** reviewed, **Then** one task survives and cites both utterances.
- **Given** a fragment carries no action or object («Так», «Надо»), **Then** it never appears as a task.

### User Story 2 - Raw text is a status, never a task (Priority: P2)

- **Given** the owner is speaking, **Then** settled utterances appear in the "What you've said · browser preview" readout, the forming hypothesis appears beside the microphone, and no task card exists before Stop.
- **Given** processing is running, **Then** the screen names the stage and shows the transcript so far.
- **Given** nothing actionable was said, **When** processing finishes, **Then** the review says no tasks were proposed, shows what was heard, and cannot be saved.

### User Story 3 - Recover a failed recording from the browser transcript (Priority: P3)

- **Given** transcription or reconciliation failed terminally, no task survived and browser transcript text exists, **Then** the owner sees "Extract tasks from the browser transcript" with a note naming where the text is sent.
- **When** the owner presses it, **Then** one text-only extraction runs and the result enters review labelled provisional on web and mobile; saving creates Inbox tasks whose receipts record the provisional origin.
- **Given** consent was withdrawn, the spend ceiling is reached, or the attempt was already used, **Then** the action is not offered, and a refused request states its reason and reference id.

### User Story 4 - Safe exits and faithful resume (Priority: P4)

- **Given** any destructive exit (web: Discard, Discard all, Delete recording, Cancel processing; mobile: Discard everything, Discard all, the review header's discard), **When** pressed once, **Then** a confirmation asks first and the safe choice keeps everything as it was.
- **Given** an in-progress recording is reopened, **Then** the last utterance is beside the microphone and the timer continues from the captured duration.

### Edge Cases

- Filler-only dump: no task survives; the review is empty and cannot be saved (FR-004, FR-005).
- Self-correction «Надо купить моло… Купить молоко»: one grounded task (FR-003, FR-004).
- Discard confirmed on a stale revision: applies to the recording's current state; saved Inbox tasks are never removed (FR-007).
- Browser without speech preview: no preview is promised and no browser-transcript recovery is offered (FR-001, FR-009).
- Recording started on the web, reopened on mobile: mobile offers the server-advertised recovery and the provisional label; it has no transcript readout of its own (FR-009, FR-010).
- Accurate transcript exists but reconciliation failed: the better source exists, so the browser-transcript recovery is not offered (FR-009).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: While recording, browser-preview text MUST be shown only as a status readout: settled utterances in a labelled region, the forming hypothesis beside the microphone. No draft task exists before the owner stops.
- **FR-002**: Preview text MUST be persisted as transcript only and never become a task proposal. Edits, locks and lineage rules for proposals that already exist are unchanged.
- **FR-003**: Tasks MUST be produced once, from the accurate transcript, as GTD next actions: verb first, in the language spoken, fillers and modal scaffolding dropped, one task per distinct action, each grounded in the spoken words.
- **FR-004**: Independently of the model, the system MUST drop a title with no action or object, fold restated duplicates into one task keeping both citations, treat a restatement of an existing task as an affirmation, and never revive a deleted task under a case, spacing or punctuation variant. Dropped items are recorded by reason, never by content.
- **FR-005**: A fresh recording MUST be saveable immediately with zero cleanup. A review with no surviving task MUST NOT be saveable: it says nothing was proposed, shows what was heard, hides the save control, and its only exit is discarding, which returns to a fresh recording (web and mobile).
- **FR-006**: The web processing screen MUST name the stage in plain words, show the transcript so far, and offer "Cancel processing". Mobile names the stage only (Open items 1).
- **FR-007**: Every destructive exit MUST require a second, explicit confirmation whose safe choice leaves everything as it was: inline on the web (safe choice focused, Escape keeps), the platform dialog on mobile. No control that discards a recording may be named "Close"; a control that deletes only retained audio must say so.
- **FR-008**: Reopening an in-progress recording MUST restore the last utterance beside the microphone and a timer that continues from the captured duration.
- **FR-009**: After a terminal failure with no surviving task and browser transcript present, the owner MUST be able to request "Extract tasks from the browser transcript": once per recording, only while consent stands, within the existing spend ceilings, never automatically. The result enters review as provisional. A refusal states its reason and reference id.
- **FR-010**: Provisional results MUST be visibly labelled on web and mobile whenever they are shown, saveable or not, and MUST never be presented as accurate.
- **FR-011**: Recordings made before this change that still carry provisional proposals keep today's rule: an untouched provisional proposal must be edited or deleted before saving.

### Key Entities

- **Recording** (operation): status, consent snapshot, transcript segments, task proposals, processing attempts, saved-task receipts.
- **Transcript segment**: preview or accurate; forming or settled; may be superseded by a later segment.
- **Processing attempt**: the stage it resumes from (`sealed`, `accurate_transcribed`, `preview_transcribed`) or froze at (`reconciled`, `preview_reconciled`), its cost reservation and outcome.
- **Saved-task receipt**: records whether the task came from the accurate transcript or the browser transcript.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The reference utterance yields exactly 3 tasks, 0 junk, 0 duplicates and 0 manual deletions before Save (baseline 9 entries, 6 junk, 6 deletions).
- **SC-002**: 0 task cards before Stop in 100% of recordings.
- **SC-003**: A filler-only dump never yields a saveable task.
- **SC-004**: Web 4 of 4 and mobile 3 of 3 destructive exits require a second confirmation (baseline 0).
- **SC-005**: A reopened recording shows the last utterance and the captured duration on first render.
- **SC-006**: From a terminal failure with preview text, one action reaches a provisional review.
- **SC-007**: The provisional label is present in 100% of provisional reviews on both clients.

## Out of Scope

Rewriting spec 002; browser-preview capture on mobile; a transcript readout and cancel on the mobile processing screen; any automatic fallback to preview-text extraction; new providers or spend ceilings; changes to retention, export, purge or the consent model.

## Assumptions

- Single-user deployment today; every surface is owner-scoped and behind the `voice_brain_dump` flag.
- Spend ceilings are unchanged; the recovery is one more extraction attempt counted under them.
- Where spec 002 conflicts with this document, this document and the ADR-0002 amendments win.

## Open items (review campaign 1, 2026-09-05)

Five of six review lenses reported before the campaign was stopped. Decisions for the founder:

1. Should the mobile processing screen get "Cancel processing" and a transcript readout? FR-006 is web-only today.
2. Should "Delete audio now" (web) and "Delete retained audio" (mobile) confirm like the other destructive exits? Today they delete on one tap.
3. Web overlay destructive controls are 32–40 px against the 44 pt mobile tap target.
4. Withdrawing consent restarts the 7-day working-artifact window instead of shortening it; the intended window is unspecified.
5. The browser's own speech-recognition service receives raw microphone audio for the preview lane and is not named in the consent copy.

Technical notes carried into [plan.md](plan.md): rollback is a clean code rollback only while no recording carries a `preview_*` attempt; `available_recovery_actions` is projected without the flag gate the command route enforces; the resume timer's chunk-count heuristic holds for web-captured recordings only.
