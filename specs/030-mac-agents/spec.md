# Feature Specification: Mac agents

**Feature Branch**: `030-mac-agents`

**Created**: 2026-10-16

**Status**: Clarified — product-owner interview held 2026-10-16 (interviewee: Max, in the
main session); three pending clarifications carry recommended defaults (see
[Pending clarifications](#pending-clarifications-awaiting-max)).
Design: [design.md](design.md). Plan: [plan.md](plan.md). Tasks: [tasks.md](tasks.md).

**Input**: User description: "Mac agents: the Mac app's native agent hand-off, runs,
Needs you, result, and Settings › Agents tab with details and add agent." Design input:
Mac board cells M21 – M24 and M29 – M30 and the "Carry On · agents" design-system page
(board version `1792138611-15e1`, design data). Business requirements:
[intake.md](intake.md). Research: `/mnt/project-files/design/mac-feature8-groundwork.md`.

## Context

The server already relays work to the owner's external agents (spec 007, wire contract
spec 014, flag `external_agent_relay`): an owner connects an agent (name, address,
credential), hands a task off after previewing exactly what the agent will get, and
BrainBuddy observes the agent's task on a schedule. A run keeps its dispatch state and the
agent's reported state apart and exposes one `primary_state_label` that clients render
verbatim. The agent can ask a question ("Needs you"), report a result ("Agent reported
complete", never "Complete"), fail, or stop reporting. **The relay never changes the
task**: dispatch does not move it, and completion does not tick it.

The web has an agents settings page, a hand-off overlay and a run section in task detail.
The native Mac app (spec 021) has none of it; spec 028's Settings window has an Agents tab
that only links to the web page.

The board draws the Mac surfaces: a hand-off sheet from the step's card (M21), an
**All runs** canvas reached from an **Agents** sidebar section and grouped by what each
run needs from the person (M22), runs in **Waiting for** next to people with the run's
question and Reply / Stop run in the inspector (M23), the result with **Mark step done**,
**Make the next step** and **Hand off again** (M24), and Settings › Agents with the agent
list, details and an **Add new agent** sheet (M29, M30).

This feature builds those surfaces against the existing relay API, with no backend
change.

## Clarifications

### Session 2026-10-16 (interview with Max, product owner)

Decisions D1 – D9 are recorded in full in
[intake.md](intake.md#interview-2026-10-16).

- Q1: Where do agent runs show? → A (Max, D1): as the board draws — an **Agents** sidebar
  section with "All runs N" and one row per agent; the M22 **All runs** canvas grouped
  **Needs you / Running / Queued / To review / Lost contact**; in **Waiting for**, a
  separate **Agents** group above **People**. The task itself is never moved; this is
  client grouping only. Agent completion never ticks the step (M24: Mark step done, Make
  the next step, Hand off again). Affects 030-FR-004 – 030-FR-012, 030-FR-020 – 030-FR-022.
- Q2: The board draws no password field; the server requires one. → A (Max, D2): the
  Python backend is frozen (bug fixes only) and this feature changes nothing there. The
  Mac shows a **Current password** field in Add agent, Replace credential, Remove, and
  Edit when the destination changes; on hand-off the field shows only when the preview
  returns `reauthentication_required`. Dropping the requirement is decided when the relay
  moves to the Rust server (follow-up, not in scope). Affects 030-FR-016, 030-FR-031 –
  030-FR-035.
- Q3: How is "All runs" built without a list endpoint? → A (Max, D3): on the Mac, from
  `GET /agent-run-summaries` over the owner's task ids, batched at 200 per call, plus
  per-task and per-run reads. No new endpoint; a Rust list endpoint is a follow-up.
  Affects 030-FR-005, 030-SC-007.
- Q4: An account without a password? → A (Max, D4): it cannot add agents. The Agents tab
  shows a short line saying a password is needed to connect an agent, with a button that
  opens the web account page. Native set-password is in the 028 backlog follow-up.
  Affects 030-FR-036.
- Q5: What does "Lost contact" mean? → A (Max, D5): on the Mac, only **Stopped
  reporting**. "Agent no longer reports this run" keeps its full text. Web copy is out of
  scope. Affects 030-FR-006, 030-FR-010.
- Q6: Flag `external_agent_relay` off? → A (Max, D6): hide the hand-off and add controls;
  existing runs stay readable; reply, cancel and disconnect stay available as the server
  allows; the Settings Agents tab falls back to 028's "Agents are managed on the web for
  now." with its web link. With the flag on, this feature replaces that content. Affects
  030-FR-002, 030-FR-037.
- Q7: Updates, offline, cache? → A (Max, D7): polling only, at the run's
  `observation_interval_seconds`; no push notifications. Offline: reply and cancel are
  disabled. Cached run content is owner-scoped and deleted on sign-out. The 30-day
  content expiry is respected. Affects 030-FR-024 – 030-FR-028.
- Q8: Visuals? → A (Max, D8): match the board exactly; only design-system colours and
  the shared `BrainBuddyDesign` controls (`.carryOnPrimary`, `.carryOnSecondary`,
  `.carryOnQuiet`, `.carryOnStrong`, `CarryOnChip`); sidebar glyphs from
  `CarryOnMacIcons`; snapshots through `assertMacSnapshot`. Affects 030-FR-041.
- Q9: Task priorities? → A (Max, D9): none, anywhere. Affects 030-FR-003.

### Pending clarifications (awaiting Max)

Each has a recommended default that the spec, design, plan and tasks are written
against; a different answer changes only the named requirement and slice.

- **(a) Groups for the states the board does not draw.** The board draws five groups;
  the server has fifteen labels. **Recommended**: Needs you also holds "Delivery
  unconfirmed" (the person decides whether to check again); Running holds Sent, Accepted
  and Cancellation requested; Queued holds Not sent; To review holds every ended run
  (Failed, Cancelled, Agent no longer reports this run, Connection disconnected, Content
  expired under retention policy) beside Agent reported complete, each row showing its
  label verbatim. Affects 030-FR-006, PR-04.
- **(b) Remove with the flag off.** D6 keeps disconnect available while the Settings tab
  falls back to the web link. **Recommended**: with the flag off the Mac shows no
  agent list and no − button; disconnect stays reachable through the fallback's web
  page, which the server still allows. Affects 030-FR-037, PR-10.
- **(c) Which steps feed All runs.** **Recommended**: open steps only (not completed or
  cancelled). Marking a step done removes its run from All runs and Waiting for; the run
  stays readable in that step's inspector. Affects 030-FR-005, PR-04.

## User Scenarios & Testing *(mandatory)*

Stories are numbered in delivery order; no story carries a priority.

### User Story 1 - Hand a step to an agent

With the flag on, the person selects a step and chooses **Hand off…** on its card. A sheet
"Hand to an agent" lists the agents ready to receive a hand-off with their skills and
guarantee, shows exactly what the chosen agent will get, and sends it. The step stays in
its list, unchanged; its card now shows the run.

**Independent Test**: with one ready agent connected on the web, hand off a step with a
note and a project from the Mac; the agent receives the title, the note and "Project:
<name>"; the step's list, status and fields are unchanged.

**Acceptance Scenarios**:

1. **Given** a signed-in Mac with the flag on and an open, synced step, **When** the
   person chooses Hand off… on its card, **Then** the sheet "Hand to an agent" opens
   with "It works on its own and comes back with a result. The step stays yours." and
   one row per ready agent: name, then skills and guarantee ("Research, bookings ·
   Guaranteed single start").
2. **Given** an agent is chosen, **When** the preview returns, **Then** "What it will get"
   shows the title, "Note: <details>" when the step has details, "Project: <name>" when it
   has a project, and the agent's cancellation disclosure; the primary button reads
   "Send to <agent>".
3. **Given** the preview reports `reauthentication_required`, **When** the sheet shows,
   **Then** a Current password field appears and Send stays disabled until it is filled;
   otherwise no password field appears.
4. **Given** the preview requires acknowledging the duplicate risk, **When** the sheet
   shows, **Then** the acknowledgement must be checked before Send is enabled.
5. **Given** the person sends, **When** the server accepts, **Then** the sheet closes, the
   step's card shows the run as "Sent" or "Queued", the step is in the same list with the
   same status, and All runs and Waiting for count the new run.
6. **Given** a wrong password, a rate limit, a stale preview or no connection, **When**
   the person sends, **Then** the sheet stays open with the failure in words, nothing is
   sent twice, and the step is unchanged.
7. **Given** no agent is ready, **When** the sheet opens, **Then** it says so and offers
   to open Settings › Agents.

---

### User Story 2 - See every run by what it needs from me

The sidebar shows **Agents** with **All runs N** and one row per agent. All runs shows
every handed-off open step grouped Needs you, Running, Queued, To review, Lost contact.
Waiting for shows the same runs in an **Agents** group above **People**.

**Independent Test**: create runs in each server state for one owner (fixtures or a test
agent); the sidebar count, the M22 groups and the Waiting for Agents group match the
grouping table, and no step has moved.

**Acceptance Scenarios**:

1. **Given** five runs on open steps, **When** the person opens All runs, **Then** the
   canvas reads "All runs", "5 runs", "Every step you handed off, by what it needs from
   you." and shows the non-empty groups in the order Needs you, Running, Queued, To
   review, Lost contact, each titled "<group> · <count>".
2. **Given** a run whose label is "Stopped reporting", **When** it is listed, **Then** it
   is under Lost contact as "<agent> · Stopped reporting · <time since last contact>";
   a run labelled "Agent no longer reports this run" shows that full text and is not
   under Lost contact.
3. **Given** two agents with runs and a third with none and stale, **When** the sidebar
   shows, **Then** it lists "All runs 5", one row per agent with its run count, the third
   with "Stale", and "Add new agent".
4. **Given** the person chooses an agent row, **When** the canvas shows, **Then** it lists
   only that agent's runs under the same groups, titled with the agent's name.
5. **Given** runs exist, **When** the person opens Waiting for, **Then** an **Agents**
   group with one row per run ("<step> / <agent> · <state>") sits above a **People**
   group with the existing waiting steps, the header reads "<n> people, <m> agents",
   and the sidebar's Waiting for count is n + m.
6. **Given** a run row in any of these places, **When** the person selects it, **Then**
   the step's inspector opens with the run; the step itself is in its own list.
7. **Given** no runs, **When** Waiting for shows, **Then** it looks exactly as today (no
   Agents or People header).

---

### User Story 3 - Answer an agent that needs me

A run that needs the person shows, in the step's inspector, the run's timeline, the
agent's question, a reply field, **Reply** and **Stop run**.

**Independent Test**: a test agent reports `blocked` with a question; the Mac shows it
within one observation interval; a reply reaches the agent; Stop run requests
cancellation.

**Acceptance Scenarios**:

1. **Given** a run labelled "Needs you", **When** its step is selected, **Then** the
   inspector shows the agent's name, the timeline ("Sent 10:02 · Guaranteed single
   start", "Running 10:03 · checked 6 firms", "Needs you 10:21"), "<agent> asks", the
   question as plain text, a reply field, Reply and Stop run.
2. **Given** a typed reply, **When** the person chooses Reply, **Then** the reply is sent
   once, the field clears, and the run shows that the reply is waiting for the agent
   until the next observation.
3. **Given** the run's controls withdraw reply or cancel, **When** the inspector shows,
   **Then** the withdrawn control is not shown.
4. **Given** the person chooses Stop run, **When** the server accepts, **Then** the run
   reads "Cancellation requested", then the server's outcome.
5. **Given** the Mac is offline, **When** the inspector shows, **Then** the last-read run
   shows with "This may be out of date.", and Reply and Stop run are disabled with
   "Needs a connection."; nothing is queued.
6. **Given** a run labelled "Delivery unconfirmed", **When** the inspector shows,
   **Then** "Check again" is offered; when the server needs the current password for a
   resend, a Current password field appears.

---

### User Story 4 - Review a result and decide

A run whose agent reported complete shows the result; the step stays open until the
person decides.

**Independent Test**: a test agent reports complete with text and a link; the step is
not completed; Mark step done with a next step completes it and creates the next step.

**Acceptance Scenarios**:

1. **Given** a run labelled "Agent reported complete", **When** its step is selected,
   **Then** the inspector shows "Agent reported complete · <time>", "Result", the result
   text, the link as selectable plain text, "The agent finishing does not finish your
   step. You decide.", "Then", a "Make the next step" field, **Mark step done** and
   **Hand off again**.
2. **Given** the result is shown, **When** nothing is chosen, **Then** the step is still
   open in its list.
3. **Given** text in "Make the next step", **When** the person chooses Mark step done,
   **Then** the step is completed and a new step with that text is created in the same
   project as a Next action; with the field empty, only the step is completed.
4. **Given** the person chooses Hand off again, **When** the sheet opens, **Then** it is
   the hand-off sheet of User Story 1 for the same step.
5. **Given** a failed, cancelled or otherwise ended run, **When** its step is selected,
   **Then** the label shows verbatim (with the agent's failure words for Failed), Mark
   step done is not shown for runs that did not report complete, and Hand off again is
   offered while the flag is on.

---

### User Story 5 - Manage my agents in Settings

Settings › Agents lists the agents on the left with + and −, and the chosen agent's
details on the right: status, address, credential, last contact, agent card, skills,
updates and guarantee, with Test again, Replace credential… and Edit…. + opens **Add new
agent**.

**Independent Test**: add an agent from the Mac, test it, replace its credential, rename
it, change its address, and remove it; each step matches the web page's state for the
same account.

**Acceptance Scenarios**:

1. **Given** connected agents, **When** the Agents tab opens, **Then** the list shows each
   agent with its status word ("Tested ready", "Stale", …) and the first is selected with
   its M29 details.
2. **Given** the person chooses Test again, **When** the test finishes, **Then** the status
   and details update; no password is asked.
3. **Given** the person chooses + (or "Add new agent" in the sidebar), **When** the sheet
   "Add new agent" opens, **Then** it asks for Name, Address, Credential (Bearer token |
   API key) with the secret, and Current password; Add and test creates the agent, tests
   it and selects it.
4. **Given** Replace credential…, Edit… with a changed address or credential type, or −,
   **When** the sheet opens, **Then** it asks for the current password; Edit… with only a
   name change does not.
5. **Given** a wrong password, **When** the person confirms, **Then** the sheet stays
   open with "That password isn't right." and nothing changes.
6. **Given** the account has no password, **When** the tab opens, **Then** it shows
   "Set a password to connect an agent." with "Open account on the web…", and no +.
7. **Given** the flag is off, **When** the tab opens, **Then** it shows 028's "Agents are
   managed on the web for now." and "Open agents on the web…".

### Edge Cases

- A step created offline has no server id yet: Hand off… is disabled with "This step
  hasn't reached your account yet."
- The flag is turned off mid-session (a flagged route answers 404 "not available"): the
  Mac re-reads the flag and hides the hand-off and add controls; open sheets close with
  "Handing off isn't available right now."
- More than 200 open steps: summaries are read in batches of at most 200 ids; a failed
  batch leaves the previous rows for those steps and shows a stale notice.
- A run's step is completed or deleted elsewhere: the run leaves All runs and Waiting
  for at the next refresh (pending (c)).
- The agent continues the run in a new task: the timeline shows "The agent continued
  this run in a new task".
- Content past `content_expires_at`: only "Content expired under retention policy" shows,
  even from the memory cache and offline.
- The result is too large: "The result is too large to show here."
- Agent text contains markup or a URL: shown as plain text; no link is opened.
- Two Macs reply to the same run: the stale revision is reported in words and the run
  is re-read; nothing is sent twice.
- An agent's card changed (`agent_changed`): the status reads "Agent changed" and Test
  again runs without a password; the next hand-off may ask for it, as the server requires.
- Session ended or account changed while an agent sheet is open: the sheet closes, the
  typed secret and password are dropped, and no data of the previous account remains.
- Reduce Motion, increased contrast and dark appearance: follows the Carry On tokens in
  both appearances.

## Requirements *(mandatory)*

Requirement ids are feature-qualified. Each definition shows the bare id the
repository's checkers parse (`- **FR-001**`) followed by its feature-qualified id
(`030-FR-001`); tests and other artifacts MUST cite the qualified form (`030-FR-001`, or
`030_FR_001` in a Swift test name).

### Functional Requirements

**Availability**

- **FR-001**: (`030-FR-001`) Every agent surface MUST require a signed-in account. A
  signed-out or local-only Mac MUST show no Agents sidebar section, no hand-off control
  and no run section; Settings › Agents keeps 028's signed-out content.
- **FR-002**: (`030-FR-002`) The Mac MUST read `external_agent_relay` from the account's
  `feature_flags` (`/auth/me`) at sign-in, when the main window becomes active (at most
  once every 5 minutes) and whenever a flagged route answers "External agent relay is not
  available." With the flag off it MUST hide Hand off…, Hand off again, Add new agent, +,
  Test again, Replace credential… and Edit…, MUST keep existing runs readable, and MUST
  keep Reply, Stop run and Check again where the run's controls allow them.
- **FR-003**: (`030-FR-003`) Every value shown MUST come from an existing endpoint or
  existing Mac data; nothing is invented or guessed, and no surface shows task priority
  in any form.

**Sidebar, All runs and Waiting for**

- **FR-004**: (`030-FR-004`) The sidebar MUST show an **Agents** section, after Lists and
  before Dates, when the account has at least one agent or one listed run, or the flag is
  on. It holds "All runs" with the number of listed runs, one row per agent (not
  disconnected) showing its listed-run count, or its status word when it has none and is
  not "Tested ready", and, with the flag on, "Add new agent", which opens Settings ›
  Agents with the Add new agent sheet. Glyphs come from `CarryOnMacIcons`.
- **FR-005**: (`030-FR-005`) The listed runs MUST be the latest run of every open step
  (pending (c)) of the signed-in account that has a server id, read with `GET
  /agent-run-summaries` in batches of at most 200 task ids, plus `GET /agent-runs/{id}`
  for each listed run (agent id, timeline and controls). The feature MUST NOT need a new
  endpoint.
- **FR-006**: (`030-FR-006`) Runs MUST be grouped from `primary_state_label` by one
  table: **Needs you** = Needs you, Delivery unconfirmed; **Running** = Sent, Accepted,
  Running, Cancellation requested; **Queued** = Queued, Not sent; **To review** = Agent
  reported complete, Failed, Cancelled, Agent no longer reports this run, Connection
  disconnected, Content expired under retention policy; **Lost contact** = Stopped
  reporting only (pending (a)). Groups show in that order; an empty group is hidden.
- **FR-007**: (`030-FR-007`) The All runs canvas MUST show the title "All runs", the
  count "N runs" ("1 run"), the line "Every step you handed off, by what it needs from
  you." and per group "<group> · <count>" with one row per run: the step's title, then
  "<agent> · <detail>", where the detail is the question's first line for Needs you, the
  time since the run was sent for Running, "Waiting for a free connection slot; nothing
  has been sent yet" for Queued, the label for To review, and "Stopped reporting · <time
  since last contact>" for Lost contact. Rows of other labels show the label verbatim.
- **FR-008**: (`030-FR-008`) Choosing an agent row MUST show the same canvas limited to
  that agent's runs, titled with the agent's name.
- **FR-009**: (`030-FR-009`) When at least one run is listed, Waiting for MUST show an
  **Agents** group above a **People** group that holds the list's existing content, and
  the header "<n> people, <m> agents" (singular "person", "agent"). The sidebar's
  Waiting for count MUST be n + m. With no listed runs, Waiting for MUST be unchanged.
- **FR-010**: (`030-FR-010`) An Agents row in Waiting for MUST show the step's title and
  "<agent> · <state>" with the compact state: "Needs you", "Running · <time>", "Queued",
  "Reported · <day>", "Lost contact · <time since last contact>", and every other label
  verbatim, including "Agent no longer reports this run".
- **FR-011**: (`030-FR-011`) Selecting a run row anywhere MUST select its step and show
  the step's inspector with the run. A run row MUST NOT offer the list's task actions
  (move, complete, reorder); those stay on the step.
- **FR-012**: (`030-FR-012`) No agent surface or run state MUST change a step's list,
  status, project or fields. Only the person's explicit Mark step done and Make the next
  step (030-FR-022) change steps, through the existing commands.

**Hand-off**

- **FR-013**: (`030-FR-013`) With the flag on, the inspector of an open step MUST offer
  **Hand off…**. A step with no server id MUST show it disabled with "This step hasn't
  reached your account yet." Completed and cancelled steps MUST NOT offer it.
- **FR-014**: (`030-FR-014`) The sheet "Hand to an agent" MUST show the line "It works on
  its own and comes back with a result. The step stays yours.", one row per agent whose
  `ready_for_handoff` is true (name; skills joined by ", "; " · "; "Guaranteed single
  start" or "Best-effort single start"), the first selected. With none ready it MUST say
  "No agent is ready to receive a hand-off." with "Open Settings…".
- **FR-015**: (`030-FR-015`) For the chosen agent the sheet MUST request a preview with
  the step's details included and, when the step has a project, the supporting item
  "Project: <name>", and MUST show under "What it will get" the manifest's title,
  "Note: <details>", each supporting item as "<label>: <body>", the manifest's cancellation
  disclosure and its external-copy notice.
- **FR-016**: (`030-FR-016`) The sheet MUST show a **Current password** field only when the
  preview reports `reauthentication_required`, and the duplicate-risk acknowledgement
  ("I understand that a duplicate task is possible with this agent") only when the
  preview requires it. Send MUST be disabled until each shown field is satisfied.
- **FR-017**: (`030-FR-017`) "Send to <agent>" MUST dispatch with the manifest token, one
  Idempotency-Key per Send (reused if the same Send is retried), the password if shown,
  and the acknowledgement if shown. On success the sheet closes and the run is added to
  the listed runs at once. A stale or expired preview MUST be re-requested, never sent.
- **FR-018**: (`030-FR-018`) Hand-off failures MUST keep the sheet open and be shown in
  words: wrong password ("That password isn't right."), rate limited ("Too many attempts.
  Try again in a few minutes."), offline ("Handing off needs a connection."), flag off
  (030-FR-002), other errors with "Reference: <id>". Nothing is retried automatically.

**The run in the inspector**

- **FR-019**: (`030-FR-019`) A step with runs MUST show its latest run in the inspector:
  the agent's name, the timeline from the run's events ("<state> <time> · <detail>"),
  "The agent continued this run in a new task" for a succession event, and below it
  "Earlier runs" with one line per older run (agent · label · date) that shows that run
  when chosen. Runs come from `GET /tasks/{id}/agent-runs`.
- **FR-020**: (`030-FR-020`) For **Needs you** the inspector MUST show "<agent> asks", the
  question, a reply field (at most 4,000 characters), **Reply** and **Stop run**, each
  only when the run's controls offer it. A sent reply shows "Reply sent. Waiting for the
  agent." until the server no longer reports it pending.
- **FR-021**: (`030-FR-021`) For **Agent reported complete** the inspector MUST show
  "Agent reported complete · <time>", "Result", the result text, the result link as
  selectable plain text, "The result is too large to show here." when so reported, the
  line "The agent finishing does not finish your step. You decide.", "Then", a "Make the
  next step" field, **Mark step done** and, with the flag on, **Hand off again**.
- **FR-022**: (`030-FR-022`) **Mark step done** MUST complete the step with the existing
  complete command and, when "Make the next step" has text, create a step with that
  title in the same project (or none) in Next actions with the existing create command.
  **Hand off again** MUST open 030-FR-014's sheet for the same step.
- **FR-023**: (`030-FR-023`) Every other label MUST show verbatim with its context:
  Running and Sent with progress and last contact and Stop run when offered; Queued
  with its line; Delivery unconfirmed with **Check again** (and a Current password
  field when the server needs one for the resend); Failed with the agent's failure
  words; Stopped reporting with the time since last contact; Content expired with no
  content. Ended runs offer Hand off again while the flag is on.

**Updates, offline, cache and expiry**

- **FR-024**: (`030-FR-024`) Updates MUST come only from polling: each non-ended run that
  is on screen MUST be re-read at its `observation_interval_seconds`; summaries MUST be
  re-read every 60 seconds while the main window is visible, on Sync now (⌘R) and right
  after a hand-off, reply or stop. Polling MUST pause while the app is hidden or offline.
  The feature MUST NOT post notifications.
- **FR-025**: (`030-FR-025`) Offline, the last-read runs MUST stay readable with "Last
  updated <time>. This may be out of date.", and Reply, Stop run, Check again, Hand off…
  and every Settings › Agents action MUST be disabled with "Needs a connection." Nothing
  is queued for later.
- **FR-026**: (`030-FR-026`) Run content, connection details, reply drafts, secrets and
  passwords MUST be held in memory only, keyed by the signed-in account id, and MUST NOT
  be written to disk (store file, `mac-local.json`, caches, logs). They MUST be cleared on
  sign-out, session end and account change; a response for another account MUST be
  discarded.
- **FR-027**: (`030-FR-027`) Before showing any run content, including from memory and
  offline, the Mac MUST compare `content_expires_at` with now; past it, the content MUST be
  dropped and only "Content expired under retention policy" shown.
- **FR-028**: (`030-FR-028`) Agent text (progress, question, result, failure, link,
  artifact names) MUST render as plain text: no Markdown, HTML, data detectors or
  clickable links; the app never opens or fetches the result link.

**Settings › Agents**

- **FR-029**: (`030-FR-029`) With the flag on and a signed-in account, Settings › Agents
  MUST show the agent list (name and status word, from `GET /agent-connections`, without
  disconnected agents) with + and − below, and the selected agent's details: "<status> ·
  <status sentence>" (for example "Tested ready · Ready to receive a hand-off."), Address,
  Credential ("Bearer token · stored sealed" / "API key · stored sealed"), Last contact,
  Agent card ("<version> · protocol <version>"), Skills, Updates ("Streaming · no push" and
  the other combinations), Guarantee; then Test again, Replace credential…, Edit….
- **FR-030**: (`030-FR-030`) Test again MUST run the server test without a password and
  show the new status; status words and sentences MUST match the web's for the same
  connection.
- **FR-031**: (`030-FR-031`) **Add new agent** (M30) MUST ask for Name, Address (helper
  "Its agent card is read from there when you test."), Credential type Bearer token | API
  key, the secret (helper "Stored sealed. It is never shown again.") and **Current
  password**; **Add and test** creates the agent, then tests it, then selects it.
- **FR-032**: (`030-FR-032`) **Replace credential…** MUST ask for the new secret and the
  Current password. **Edit…** MUST ask for Name, Address and Credential type and show
  Current password only when the address or type differs from the saved one.
- **FR-033**: (`030-FR-033`) **−** MUST ask "Delete <name>?" with the Current password and
  then disconnect the agent; its runs keep their history and read "Connection
  disconnected".
- **FR-034**: (`030-FR-034`) Every agent mutation MUST carry an Idempotency-Key per
  person's action (reused on retry) and the last-read `expected_revision`; a stale
  revision MUST re-read the agent and say "This agent changed elsewhere. Check and try
  again." A wrong password MUST keep the sheet open with "That password isn't right.";
  429 MUST NOT be retried automatically.
- **FR-035**: (`030-FR-035`) Secrets and passwords MUST be typed in secure fields, sent
  only with the request that needs them, cleared when the request ends or the sheet
  closes, and never shown, copied, logged or put in a URL.
- **FR-036**: (`030-FR-036`) When the account has no password, the tab MUST show "Set a
  password to connect an agent." with **Open account on the web…** (the server's web
  account page, no credential in the URL), MUST NOT show + or the sidebar's Add new
  agent, and MUST hide Replace credential…, − and a destination change in Edit…. When
  the password state cannot be read, the controls stay and the server decides.
- **FR-037**: (`030-FR-037`) With the flag off, Settings › Agents MUST show 028's content
  ("Agents are managed on the web for now." and "Open agents on the web…") unchanged
  (pending (b)).

**Errors, logs, presentation and boundaries**

- **FR-038**: (`030-FR-038`) Errors MUST be actionable: a short message, Try again where
  retrying can help, and "Reference: <id>" when the server returned one. A 401 MUST lead
  to the existing "Your session ended" path with local work kept.
- **FR-039**: (`030-FR-039`) Logs MUST record only stage, outcome, status class, duration
  and correlation id; never step titles, details, agent names or addresses, question,
  reply or result text, links, secrets or passwords.
- **FR-040**: (`030-FR-040`) Every control MUST be reachable and operable by keyboard
  with visible focus and have an accessible name (and value); run states are read in
  words; Return sends in the hand-off and Add sheets and Esc cancels.
- **FR-041**: (`030-FR-041`) The surfaces MUST match board cells M21 – M24, M29 and M30 in
  light and dark appearance, use only design-system colour roles (Needs you takes the
  accent; Running and Queued secondary text; Lost contact the warning role; Failed the
  danger role; state always also in words), the shared `BrainBuddyDesign` controls and
  `CarryOnMacIcons` glyphs, sentence-case English, and respect Reduce Motion.
- **FR-042**: (`030-FR-042`) The feature MUST NOT change anything under `backend/`, the
  web pages, the iPhone app's behaviour, or 028's flag-off Agents tab. Kit additions MUST
  be additive and free of Mac-only types so the iPhone app can reuse them.

### Key Entities

- **Agent connection**: an owner's agent — id, name, address, credential scheme (never the
  secret), status and staleness, readiness for hand-off, agent card (version, protocol,
  skills), updates capabilities, guarantee tier, disclosures, last contact, revision.
- **Hand-off manifest**: the preview of what the agent will get — token, title, details,
  supporting items, tier and cancellation disclosures, external-copy notice, whether the
  password and the duplicate-risk acknowledgement are required.
- **Agent run**: one hand-off — step id, agent id and name, primary state label, flags
  (needs you, stopped reporting, reply pending, cancel requested), progress, question,
  result text and link, failure reason, timeline events, controls, observation interval,
  content expiry, revision.
- **Run summary**: the latest run of one step, for listing.
- **Run group**: one of Needs you, Running, Queued, To review, Lost contact; derived on
  the Mac from the label (030-FR-006).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: (`030-SC-001`) From a selected open step, a hand-off to a ready agent takes
  at most 3 interactions (Hand off…, choose agent, Send) when no password is required.
- **SC-002**: (`030-SC-002`) Across hand-off, polling, reply, stop and every run state,
  0 steps change list, status, project or fields except through Mark step done and Make
  the next step.
- **SC-003**: (`030-SC-003`) For fixtures covering all 15 server labels, 100% of runs land
  in the group of 030-FR-006 and show the words of 030-FR-007 and 030-FR-010.
- **SC-004**: (`030-SC-004`) While a run is on screen and the Mac is online, a server
  state change shows within the run's observation interval plus 5 seconds.
- **SC-005**: (`030-SC-005`) After a full acceptance run ending in sign-out, 0 run
  contents, secrets or passwords are found on disk, in logs or in any URL the app opened.
- **SC-006**: (`030-SC-006`) With the flag off, 0 hand-off, add, test, replace or edit
  controls are present, existing runs are readable, and Reply and Stop run work on a
  non-ended run whose controls offer them.
- **SC-007**: (`030-SC-007`) For an owner with 450 open synced steps, All runs is built
  with exactly 3 summary requests (≤ 200 ids each) plus one run read per listed run.
- **SC-008**: (`030-SC-008`) Every action of User Stories 1 – 5 can be completed with
  the keyboard alone, and every control has an accessible name, in light and dark.
- **SC-009**: (`030-SC-009`) Snapshots of the designed states match board cells M21 –
  M24, M29 and M30 in light and dark appearance.
- **SC-010**: (`030-SC-010`) `git diff origin/main -- backend/` is empty for every slice.

## Dependencies

Existing contracts this feature consumes (paths under `/api`; session cookie; no change
made by this feature). Line references are to `backend/app/api/agents.py`.

| Need | Existing endpoint | Gate | Notes |
|---|---|---|---|
| Agent list and details | `GET /agent-connections`, `GET /agent-connections/{id}` (:152, :195) | session | |
| Add | `POST /agent-connections` (:164) | flag; password | never echoes the secret |
| Edit | `PUT /agent-connections/{id}` (:208) | flag; password when address or scheme changes | |
| Test again | `POST /agent-connections/{id}/test` (:235) | flag | |
| Replace credential | `POST /agent-connections/{id}/credential` (:248) | flag; password | |
| Delete (−) | `POST /agent-connections/{id}/disconnect` (:274) | session; password | |
| Preview | `POST /tasks/{task_id}/agent-runs/preview` (:305) | flag | `reauthentication_required`, `acknowledgement_required` |
| Send | `POST /tasks/{task_id}/agent-runs` (:319) | flag; password when required | |
| Runs of a step | `GET /tasks/{task_id}/agent-runs` (:351) | session | |
| Latest run per step | `GET /agent-run-summaries?task_id=…` (:364) | session | at most 200 ids |
| One run | `GET /agent-runs/{run_id}` (:384) | session | |
| Reply | `POST /agent-runs/{run_id}/reply` (:397) | session | |
| Check again | `POST /agent-runs/{run_id}/check-delivery` (:417) | session; resend needs flag | |
| Stop run | `POST /agent-runs/{run_id}/cancel` (:456) | session | |
| Flag | `GET /auth/me` `feature_flags` (`backend/app/api/auth.py:62-80`) | session | decoded by the kit (`WireModels.swift:16`) |
| Password state | `GET /account/auth-methods` (`has_password`) | session | kit `accountAuthMethods()` |
| Web pages | web origin from `GET /auth/methods`; `/settings/account`, `/settings/agents` | — | kit `NativeAccountDestination` |
| Complete a step, create a step | existing workspace commands | — | Mark step done, Make the next step |

- Spec 027 (Rust server) carries these routes (capability inventory CAP-HTTP-170 onward).
- Spec 028 PR-03 (the Settings window and its Agents tab file) must land before this
  feature's Settings slices.
- Shared kit: it has no agent types or calls today; the plan adds them additively.

## Follow-ups (not in scope)

1. **Password re-check on the Rust relay** (D2): decide, when the relay moves to the Rust
   server, whether add, replace, delete, destination edits and first hand-offs keep
   requiring the current password or accept the modern-auth recent proof. The Mac's
   password fields would then change.
2. **Rust list endpoint for runs** (D3): an owner-scoped "all my runs" read on the Rust
   server, replacing the Mac's summaries-plus-reads assembly.
3. **Native set-password** (D4): in the 028 backlog follow-up; then the password-less line
   can open a native sheet instead of the web.
4. **iPhone agent screens**: can reuse this feature's kit wrappers.

## Assumptions

- Run counts per owner are small (tens), so one run read per listed run is acceptable.
- The server's `observation_interval_seconds` is a sensible client poll rate (default 60).
- A step's server id is available from the workspace for synced steps.
- The 028 Settings window lands before the Settings slices of this feature.
- Primary loop impact: a handed-off step stays in its list and is shown in Waiting for
  next to people; capture, clarify/approve, routing, CRT and evidence are unchanged.
- Out of scope: everything in intake.md § 4 "Out of scope".
