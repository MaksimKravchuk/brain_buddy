# Feature Specification: iPhone agents

**Feature Branch**: `034-iphone-agents`

**Created**: 2026-10-16

**Status**: Ready — behaviour decided in the 030 interview (D1 – D9, Max, 2026-10-16); iPhone
placements drawn on the canvas. Design: [design.md](design.md). Plan: [plan.md](plan.md).
Tasks: [tasks.md](tasks.md). Business requirements: [intake.md](intake.md).

**Input**: "Build the iPhone agent screens per Carry On canvas screens 21 – 24 and 29 – 30;
agents exist on the web, and the Mac just shipped feature 030; reuse its logic." Design input:
iPhone row of canvas cells M21 – M24, M25 (Agents section) and M29 – M30 (version `1792165683-83f3`).

## Context

Feature 030 gave the Mac every agent surface over the existing relay API (specs 007, 014): hand-off,
the listed runs, Needs you, the result, and Settings › Agents. Its rules live in Foundation-only
models. The iPhone has none of it. The canvas draws the iPhone surfaces: runs in **Waiting for**
above the people (M22), a half sheet with the run's timeline and the agent's question (M23) or its
result (M24), a "Hand to an agent" sheet (M21), an **Agents** section on the Account screen (M25)
with agent details (M29) and **Add new agent** (M30). The iPhone has no sidebar and no All runs
canvas.

## Clarifications

- Behaviour questions were answered for 030 and hold here unchanged: grouping and Lost contact (D1,
  D5), the Current password fields (D2), the runs list built from summaries (D3), passwordless
  accounts (D4), the flag off (D6), polling only with memory-only content (D7), exact visuals (D8),
  no priorities (D9), and the defaults (a) – (c) of 030.
- Where hand-off starts on the iPhone: the canvas draws the sheet, not its entry. **Default**: the
  step's card offers **Hand off…** beside its other actions, as the Mac's inspector does
  (030-FR-013).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See and answer my agents from Waiting for (Priority: P1)

**Acceptance Scenarios**:

1. **Given** two steps handed off, one asking a question, **When** I open Waiting for, **Then** an
   **Agents** group lists both above **People**, the asking one first with "Needs you" in
   terracotta, and the header reads "N people, 2 agents".
2. **Given** that row, **When** I tap it, **Then** a half sheet shows the project and agent, the
   step, the run's timeline, "<agent> asks" with the question, a "Your answer" field and
   **Reply** / **Stop run**.

### User Story 2 - Decide on a result (Priority: P1)

1. **Given** a run that reported complete, **When** I open it, **Then** I see the result, a link I
   can copy, "The agent finishing does not finish your step. You decide.", **Make the next step**,
   and **Mark step done** / **Hand off again**; the step stays open until I mark it done.

### User Story 3 - Hand a step to an agent (Priority: P2)

1. **Given** an open, synced step and a ready agent, **When** I choose **Hand off…** on its card,
   **Then** "Hand to an agent" lists the ready agents, shows exactly what the agent will get, and
   **Send to <agent>** dispatches it; the run appears in Waiting for.

### User Story 4 - Manage my agents (Priority: P2)

1. **Given** a signed-in account, **When** I open Account, **Then** an **Agents** section lists each
   agent with its status and **Add new agent**; tapping an agent shows its details with **Test
   again**, **Replace credential** and **Delete <name>…**.

### Edge Cases

- Signed out, local only: no agent surface anywhere.
- Flag off: no Hand off…, no Add new agent, runs stay readable (030-FR-002).
- Offline: last-read runs stay with "Last updated …"; Reply, Stop run and hand-off refuse.
- Account switch or sign-out: every listed run, draft and cached content is dropped.
- A step completed elsewhere leaves Waiting for's Agents group.

## Requirements *(mandatory)*

Requirement ids are feature-qualified. Each definition shows the bare id the repository's checkers
parse (`- **FR-001**`) followed by its qualified id; tests cite the qualified form (`034-FR-001`, or
`034_FR_001` in a Swift test name).

### Functional Requirements

- **FR-001**: (`034-FR-001`) The iPhone MUST use the same agent models as the Mac — availability,
  memory cache, listed runs, hand-off, run actions, run content and agent settings — from one shared
  kit module, so every 030 rule (030-FR-002 – 030-FR-039) holds on the iPhone without a second copy.
  Logs carry no title, agent name, address, question or secret (030-FR-039).
- **FR-002**: (`034-FR-002`) Every agent surface MUST require a signed-in account; a signed-out
  iPhone shows none and reads nothing. An account change or sign-out MUST drop every listed run,
  draft and cached agent content (030-FR-026).
- **FR-003**: (`034-FR-003`) The iPhone MUST read the relay flag and password state at sign-in,
  when the app comes to the foreground (at most once every 5 minutes) and after a relay-unavailable
  answer; the flag gates Hand off… and Add new agent, the password state gates adding (030-FR-002,
  030-FR-036). Runs are polled only while the app is in the foreground and online (030-FR-024,
  030-FR-025).
- **FR-004**: (`034-FR-004`) When at least one run is listed, Waiting for MUST show an **Agents**
  group above **People** (M22) with the latest run of every open step, Needs you first
  (030-FR-006), and the header "N people, M agents". Each row shows the agent glyph, the step's
  title and "<agent> · <state>" with a state dot: Needs you in terracotta, Lost contact in ochre,
  others grey (030-FR-010).
- **FR-005**: (`034-FR-005`) Tapping an Agents row MUST open the step's run in a half sheet over the
  list (M23, M24) showing its latest run; earlier runs are reachable below it (030-FR-019).
- **FR-006**: (`034-FR-006`) For **Needs you** the sheet MUST show the project dot and name ·
  agent, the step title, the run's timeline, "<agent> asks" with the question, a "Your answer"
  field, and **Reply** / **Stop run** in the glass bar (M23, 030-FR-020).
- **FR-007**: (`034-FR-007`) For **Agent reported complete** the sheet MUST show "Agent reported
  complete · <time>", the result and its link with a copy control, the line "The agent finishing
  does not finish your step. You decide.", **Then › Make the next step**, and **Mark step done** /
  **Hand off again** (M24, 030-FR-021, 030-FR-022). Only the person's Mark step done completes the
  step (030-FR-012).
- **FR-008**: (`034-FR-008`) Every other label MUST show verbatim with only the controls the run
  allows — Stop run, Check again (with Current password when asked), Hand off again — and content
  past its expiry shows only "Content expired under retention policy" (030-FR-023, 030-FR-027).
- **FR-009**: (`034-FR-009`) With the flag on, the card of an open step with a server id MUST offer
  **Hand off…**, opening "Hand to an agent" (M21): the intro line, **Choose agent** with each ready
  agent's skills and start guarantee, **What it will get** from the preview, the cancellation
  disclosure, Current password and the duplicate acknowledgement only when the preview asks, and
  **Send to <agent>** / **Cancel** (030-FR-013 – 030-FR-018). With no ready agent it says so and
  offers to open Account.
- **FR-010**: (`034-FR-010`) The Account screen MUST show an **Agents** section (M25) listing each
  connected agent with its status word and dot, and **Add new agent** when adding is allowed; with
  no password it shows "Set a password to connect an agent." (030-FR-029, 030-FR-036).
- **FR-011**: (`034-FR-011`) An agent's details (M29) MUST show its status and sentence,
  **Connection** (Address, Credential, Last contact, Last tested), **Read from its agent card**
  (Version, Streaming updates, Push notifications, skills), the start guarantee and cancellation
  line, and **Test again**, **Replace credential** and **Delete <name>…** (030-FR-030, 030-FR-032,
  030-FR-033).
- **FR-012**: (`034-FR-012`) **Add new agent** (M30) MUST ask for Name, Address (with "Its agent
  card is read from there when you test."), Credential type (Bearer token / API key), the secret
  (with "Stored sealed. It is never shown again.") and Current password, with **Add and test** /
  **Cancel**; secrets are typed in secure fields and cleared after every outcome (030-FR-031,
  030-FR-035).
- **FR-013**: (`034-FR-013`) The surfaces MUST match the canvas cells in layout, copy and colour,
  built from the `BrainBuddyDesign` tokens and components, with 44 pt targets, Dynamic Type and
  VoiceOver labels; agent text is shown verbatim, never as Markdown or a live link (030-FR-028).
- **FR-014**: (`034-FR-014`) The feature MUST NOT change anything under `backend/` or the relay
  wire contract.

### Key Entities

- **AgentsSession**: one window's availability, cache and listed runs over the open steps.
- **AgentStepRef**: an open step's local id, server id and title.

## Success Criteria *(mandatory)*

- **SC-001**: (`034-SC-001`) The shared module's tests pass on Linux and macOS, and the Mac's 030
  tests pass unchanged against the moved models.
- **SC-002**: (`034-SC-002`) With a run in each of the five groups, Waiting for lists them in group
  order above People with the right header, and each opens its sheet.
- **SC-003**: (`034-SC-003`) `git diff origin/main -- backend/` is empty for every slice.

## Assumptions

- The Account screen of feature 033 hosts the Agents section when it lands; until then the existing
  Settings screen hosts it in the same place in the order.
