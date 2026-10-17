# Feature Specification: iPhone first run

**Feature Branch**: `032-iphone-first-run`

**Created**: 2026-10-16

**Status**: Clarified (no open question). Intake: [intake.md](intake.md).
Design: [design.md](design.md). Plan: [plan.md](plan.md). Tasks: [tasks.md](tasks.md).

**Input**: "Build the iPhone first-run flow per Carry On boards 01–04." The Mac builds the
same flow as feature 029; this feature follows its rules where the iPhone allows.

## Context

The iPhone app works without an account. A fresh install opens straight on the Inbox; there
is no first run. The board draws one in four screens: Welcome (01), First capture (02),
First step (03), Landing (04). This feature builds them with real behaviour only.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Welcome and first capture

A person opens Carry On on an iPhone that has never held tasks or an account. They see the
mark, "Carry On", "Say what weighs on you. Take the next step.", "No account needed. Your
tasks stay on this iPhone until you sign in.", Start and I have an account. Start asks
"What feels heaviest?" with the keyboard up; Add to Inbox saves exactly what they wrote.

**Independent Test**: delete the app, install, tap Start, type a sentence, tap Add to Inbox;
the Inbox holds one item with exactly that text.

**Acceptance Scenarios**:

1. **Given** a clean device, **When** the app opens, **Then** the welcome covers the screen.
2. **Given** the welcome, **When** the person taps Start, **Then** the capture screen shows
   with the field focused and Add to Inbox unavailable while the field is empty.
3. **Given** typed text, **When** they tap Add to Inbox, **Then** one Inbox item exists with
   that text unchanged (no project, tag or date parsed) and the first-step question shows.
4. **Given** the capture screen, **When** they tap Skip, **Then** nothing is added and the
   app opens on the Inbox; the first run never returns.
5. **Given** the welcome, **When** they tap I have an account and sign in, **Then** the
   first run ends and the app opens as usual.
6. **Given** a device with any task, project, tag or account, **Then** no welcome shows.

### User Story 2 - First step and landing

**Independent Test**: capture "the garage is a mess and Sam needs the van back", write "Call
Sam about the van", tap Make it my next step; Next actions shows that step on top with the
tip, its note holds the sentence, and no project exists.

**Acceptance Scenarios**:

1. **Given** the capture was added, **Then** the screen shows "From your Inbox", the words,
   "What is the first step you could take?", a focused field, the helper line, Not yet and
   Make it my next step.
2. **Given** the step written, **When** they tap Make it my next step (or Return), **Then**
   the item's text is the step, its note holds the captured words, it is in Next actions,
   and the app shows Next actions with the step on top and one tip with Got it.
3. **Given** the tip, **When** they tap Got it, **Then** it disappears for good.
4. **Given** the question, **When** they tap Not yet, **Then** the item stays in the Inbox
   unchanged and the app opens.
5. **Given** the app was closed after the capture, **When** it opens again, **Then** the
   item is in the Inbox and the first run does not resume.

### Edge Cases

- The record cannot be saved: the welcome is skipped rather than shown on every launch.
- A save fails: the existing error toast shows, nothing changes, and a retry is the same
  command.
- Closed on the welcome or before adding: the welcome shows again (nothing was written).
- Closed on the landing before Got it: the tip shows again on Next actions.

## Requirements *(mandatory)*

- **FR-001**: The first run shows once per device, only when the loaded workspace has no
  account, no task in any state, no project and no tag, and is not on the Rust runtime; the
  decision is remembered on the device.
- **FR-002**: The welcome (board 01) shows the mark, "Carry On", the two-line promise, the
  no-account line, Start and I have an account.
- **FR-003**: I have an account opens the existing sign-in sheet; an account linked at any
  step ends the first run.
- **FR-004**: The capture screen (board 02) shows the heading, the subline, a focused field,
  "It goes to your Inbox, as you wrote it.", Skip and Add to Inbox; Add to Inbox is
  unavailable while the trimmed text is empty.
- **FR-005**: Add to Inbox creates one Inbox item whose title is the trimmed text, with no
  Smart Add parse.
- **FR-006**: Skip ends the first run without adding anything.
- **FR-007**: The first-step screen (board 03) shows "From your Inbox", the captured words,
  the question, a focused field, the helper line, Not yet and Make it my next step (the only
  terracotta); the move is unavailable while the step is empty.
- **FR-008**: Make it my next step sets the step as the title, puts the captured words first
  in the note (unless equal to the step), and moves the item to Next actions in one save; no
  project is created.
- **FR-009**: Not yet ends the first run and leaves the item unchanged in the Inbox.
- **FR-010**: After the move the app shows Next actions with the step as the next-step card
  and one tip (board 04); Got it hides it for good; until then it shows on every launch.
- **FR-011**: The first run never resumes after the capture; before it, the welcome shows
  again.
- **FR-012**: The device keeps only when the run was decided, its outcome and when the tip
  was dismissed; the first run makes no network request, asks no permission and uses no AI.
- **FR-013**: A failed save shows the existing error toast and changes nothing.
- **FR-014**: Copy, colours and sizes are the board's; sizes off the type scale come from
  design tokens.

## Success Criteria *(mandatory)*

- **SC-001**: From a fresh install a person reaches Next actions with their own step in
  three taps plus typing.
- **SC-002**: An install that already holds anything never shows the first run.

## Dependencies

The existing `Workspace` commands (`createTask`, `updateTask`, `transitionTask`), the
sign-in sheet, the Next actions card, the capture bar and the toast host. Mac counterpart:
`specs/029-mac-first-run-sign-in` (US1–US2).
