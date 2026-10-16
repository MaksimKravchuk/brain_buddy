# Design: Mac agents

**Feature**: `specs/030-mac-agents/`
**Spec**: [spec.md](spec.md) (Clarifications settled with Max: 2026-10-16; pending (a) –
(c) carry recommended defaults)
**Screen source**: Mac design board, version `1792138611-15e1` — cells **M21** (Hand off),
**M22** (Agent runs), **M23** (Needs you), **M24** (Result), **M29** (Agent details),
**M30** (Add agent), and the design-system page **DSAgents** ("Carry On · agents") for the
sidebar's per-agent rows, the run-state words and the colour rules. No separate HTML
mockup is produced: the cells are the approved renders, and every deviation is listed in
[Deviations from the board](#deviations-from-the-board).
**Human sign-off**: pending — Max to confirm this state inventory before
`/speckit-review`.

<!-- Ids are stable once written; never renumber. ADR-0006: the term is Tag. -->

## Applicability

New Mac UI in the main window (a sidebar section, a canvas, a Waiting for group, an
inspector section, a sheet) and in the 028 Settings window (the Agents tab content and its
sheets). Everything else is reused unchanged: the main window's sidebar, list and
inspector frames (021), the Settings window and tab bar (028 S-01), 028's flag-off Agents
content (028 S-03), and the sign-in-again path (021 X-03).

G- ids are this feature's agent surfaces. State keys combine screen id and suffix, for
example `G-05.03`.

## Screen inventory

| id | surface | screen | purpose | FR refs |
|---|---|---|---|---|
| G-01 | Main window › sidebar | Agents section | "All runs N", one row per agent; "Add new agent" on the canvas | 030-FR-001, 030-FR-004 |
| G-02 | Main window › canvas (from G-01) | All runs canvas | Every listed run grouped by what it needs (M22); per-agent filter | 030-FR-005 – 030-FR-008, 030-FR-011 |
| G-03 | Main window › Waiting for | Agents group | Runs above People (M23, M24) | 030-FR-009 – 030-FR-011 |
| G-04 | Main window › inspector › sheet | Hand to an agent | Choose agent, see what it gets, send (M21) | 030-FR-013 – 030-FR-018 |
| G-05 | Main window › inspector | Run section | Timeline and state block of the step's latest run (M23, M24) | 030-FR-019 – 030-FR-023 |
| G-06 | Settings › Agents | Agents tab | List with + / −, details, Test again, Replace credential…, Edit… (M29) | 030-FR-029, 030-FR-030, 030-FR-036, 030-FR-037 |
| G-07 | Settings › Agents › sheet | Add new agent | Name, Address, Credential, Current password (M30) | 030-FR-031, 030-FR-034, 030-FR-035 |
| G-08 | Settings › Agents › sheet | Replace credential, Edit, Delete | The other agent mutations (not drawn) | 030-FR-032 – 030-FR-035 |

## Layout (from the board)

- **Sidebar** (G-01, M22 and DSAgents): a section headed "Agents" between Lists and
  Dates, in the existing sidebar row style. Rows: "All runs" with the trailing count;
  each agent with its trailing count or status word ("Stale"). "Add new agent" is not in
  the sidebar: DSAgents draws it as a glass pill with + at the top right of the All runs
  canvas. Glyphs from `CarryOnMacIcons`, copied from the board's SVG: the agent-run glyph
  (rounded rect, two dots, antenna) for All runs and every agent row, and +.
- **All runs canvas** (G-02, M22): the canvas header pattern of the task lists — title
  "All runs", meta "5 runs", and the line "Every step you handed off, by what it needs
  from you." in `text-secondary`. Groups use the list's section header style ("Needs you ·
  1"). Rows use the existing task row frame: step title in `text-primary`, second line in
  13 pt meta: agent name, " · ", detail.
- **Waiting for** (G-03, M23): header meta "2 people, 4 agents"; section headers "Agents",
  then "People". Agent rows: step title; meta "Hermes · " followed by the compact state,
  whose word takes the state's colour role, and " · 4 min" in `text-secondary`.
- **Run section** (G-05, M23, M24): in the inspector under the step's fields; the
  project chip and agent name on top ("Garage · Hermes"), the step title, then the
  timeline as rows of state word (semibold) and "10:02 · Guaranteed single start" meta.
  The state block follows: "Hermes asks" + question on a `surface-card`; the reply field
  (`field-bg`); buttons in a row, primary first.
- **Hand-off sheet** (G-04, M21): a sheet attached to the main window, 460 pt wide. Title
  "Hand to an agent", the line under it, agent rows as selectable cards (selected card
  `surface-selected` with the focus treatment), "What it will get" label and a
  `surface-card` box with title, note and project lines, the disclosure line, then
  buttons "Send to Hermes" (`.carryOnPrimary`) and "Cancel" (`.carryOnSecondary`),
  right-aligned.
- **Agents tab** (G-06, M29): inside 028's Settings window; left a 200 pt bordered list
  with + and − (`.carryOnQuiet`, glyph buttons) under it; right the details grid in 028's
  row style (150 pt right-aligned `text-secondary` label, value, no trailing control), and
  the button row Test again / Replace credential… / Edit… (`.carryOnSecondary`).
- **Add new agent** (G-07, M30): a sheet over Settings, 440 pt wide, 028 row grid. The
  credential type is a two-segment control (Bearer token | API key); the secret a secure
  field; helpers in 12 pt `text-secondary`. Buttons "Cancel" and "Add and test"
  (`.carryOnPrimary`).
- **Colour** (DSAgents "Only your moves get colour"): Needs you uses `text-accent`
  (terracotta); Running and Queued `text-secondary` (dust); Lost contact
  `status-warning` (ochre); Failed `status-danger` (oxblood) with the agent's words.
  Every state is also in words. Only `CarryOnColorStyle` roles; the shared buttons
  `.carryOnPrimary`, `.carryOnSecondary`, `.carryOnQuiet`, `.carryOnStrong` and
  `CarryOnChip` for the project chip. No new colour or control is added to
  `BrainBuddyDesign`.

## State inventory

### G-01 — Sidebar Agents section

| key | state | what shows | FR |
|---|---|---|---|
| G-01.01 | Signed out or local-only | No Agents section | 030-FR-001 |
| G-01.02 | Signed in, flag on, no agents, no runs | "Agents" with "All runs" (no count); canvas shows "Add new agent" | 030-FR-004 |
| G-01.03 | Runs listed (M22) | "All runs 5"; one row per agent: "Hermes 1", "Claude 1", "Home server Stale"; canvas shows "Add new agent" | 030-FR-004 |
| G-01.04 | Flag off, agents or runs exist | As G-01.03, canvas without "Add new agent" | 030-FR-002, 030-FR-004 |
| G-01.05 | Flag off, no agents, no runs | No Agents section | 030-FR-004 |
| G-01.06 | Account has no password | As G-01.03, canvas without "Add new agent" | 030-FR-036 |
| G-01.07 | Loading the first time | "All runs" with a small progress indicator in place of the count (static under Reduce Motion) | 030-FR-005 |

### G-02 — All runs canvas

| key | state | what shows | FR |
|---|---|---|---|
| G-02.01 | Loaded (M22) | Title, "5 runs", line; groups in order with "· N"; rows "Compare van hire prices / Hermes · asks about card holds" etc. | 030-FR-006, 030-FR-007 |
| G-02.02 | One agent chosen | Title = agent name; same groups over that agent's runs | 030-FR-008 |
| G-02.03 | No runs | Title, "0 runs", the line, and "Nothing handed off yet. Choose Hand off… on a step's card." | 030-FR-007 |
| G-02.04 | Loading | Header shows; groups replaced by "Loading runs…" | 030-FR-005 |
| G-02.05 | Offline / stale | Last-read groups; under the header "Last updated 10:21. This may be out of date." | 030-FR-025 |
| G-02.06 | Read failed | Last-read groups (or none); "Runs couldn't be loaded." with Try again and "Reference: <id>" | 030-FR-038 |
| G-02.07 | Row selected | The step selected; inspector shows G-05 for its run | 030-FR-011 |

### G-03 — Waiting for with agents

| key | state | what shows | FR |
|---|---|---|---|
| G-03.01 | Runs listed (M23) | Header "2 people, 4 agents"; "Agents" group with rows; "People" group with the existing content | 030-FR-009, 030-FR-010 |
| G-03.02 | No runs | Waiting for exactly as today | 030-FR-009 |
| G-03.03 | Runs, no people | "0 people, 2 agents"; "Agents" group; "People" group shows the list's existing empty text | 030-FR-009 |
| G-03.04 | Agent row selected | Step selected; inspector shows G-05 (M23) | 030-FR-011 |

Compact states: "Needs you" (accent), "Running · 4 min", "Queued", "Reported · today",
"Lost contact · 2 days" (warning), "Failed" (danger), every other label verbatim.

### G-04 — Hand to an agent

| key | state | what shows | FR |
|---|---|---|---|
| G-04.01 | Previewing | Agent rows; "What it will get" box with a progress indicator; Send disabled | 030-FR-014, 030-FR-015 |
| G-04.02 | Ready (M21) | Agent rows (Hermes selected), "What it will get" with "Compare van hire prices", "Note: For Saturday, local firms, under £80.", "Project: Garage"; "Cancellation depends on the agent."; external-copy notice; "Send to Hermes", "Cancel" | 030-FR-014, 030-FR-015 |
| G-04.03 | Password required | G-04.02 plus "Current password" secure field; Send disabled until filled | 030-FR-016 |
| G-04.04 | Acknowledgement required | G-04.02 plus the checkbox "I understand that a duplicate task is possible with this agent"; Send disabled until checked | 030-FR-016 |
| G-04.05 | Sending | Buttons disabled; "Sending…" | 030-FR-017 |
| G-04.06 | Wrong password | G-04.03 with "That password isn't right." under the field; field cleared and focused | 030-FR-018 |
| G-04.07 | Failed | Box stays; error line in `status-danger` with "Reference: <id>"; Try again | 030-FR-018 |
| G-04.08 | No ready agent | "No agent is ready to receive a hand-off." and "Open Settings…"; no Send | 030-FR-014 |
| G-04.09 | Offline | "Handing off needs a connection."; Send disabled | 030-FR-018, 030-FR-025 |
| G-04.10 | Flag turned off | Sheet closes; inspector shows "Handing off isn't available right now." once | 030-FR-002 |
| G-04.11 | Step not synced | Inspector's Hand off… disabled with "This step hasn't reached your account yet." | 030-FR-013 |

### G-05 — Run section in the inspector

| key | state | what shows | FR |
|---|---|---|---|
| G-05.01 | Needs you (M23) | Timeline; "Hermes asks"; question; reply field "Your answer"; Reply (`.carryOnPrimary`), Stop run (`.carryOnSecondary`) | 030-FR-019, 030-FR-020 |
| G-05.02 | Reply sent | Question stays; "Reply sent. Waiting for the agent."; Reply disabled | 030-FR-020 |
| G-05.03 | Running / Sent / Accepted | Timeline; progress text; "Last contact <time>"; Stop run when offered | 030-FR-023 |
| G-05.04 | Queued | "Waiting for a free connection slot; nothing has been sent yet"; Stop run when offered | 030-FR-023 |
| G-05.05 | Cancellation requested | "Cancellation requested"; no controls | 030-FR-023 |
| G-05.06 | Agent reported complete (M24) | "Agent reported complete · 11:40"; "Result"; text; link as text; "The agent finishing does not finish your step. You decide."; "Then"; "Make the next step" field; Mark step done (`.carryOnPrimary`), Hand off again (`.carryOnSecondary`) | 030-FR-021, 030-FR-022 |
| G-05.07 | Result too large | G-05.06 with "The result is too large to show here." in place of the text | 030-FR-021 |
| G-05.08 | Failed | "Failed"; the agent's words in `status-danger`; Hand off again | 030-FR-023 |
| G-05.09 | Stopped reporting | "Stopped reporting · last contact 2 days ago" (warning); Stop run when offered; Hand off again | 030-FR-023 |
| G-05.10 | Other ended labels | Cancelled / Agent no longer reports this run / Connection disconnected, verbatim; Hand off again | 030-FR-023 |
| G-05.11 | Content expired | "Content expired under retention policy" only | 030-FR-027 |
| G-05.12 | Delivery unconfirmed | Label; Check again; Current password field when the server needs it | 030-FR-023 |
| G-05.13 | Offline | Last-read run; "Last updated <time>. This may be out of date."; Reply, Stop run, Check again disabled with "Needs a connection." | 030-FR-025 |
| G-05.14 | Earlier runs | Under the section, "Earlier runs" with "Claude · Failed · 12 Oct" lines; choosing one shows it | 030-FR-019 |
| G-05.15 | Continued in a new task | Timeline line "The agent continued this run in a new task" | 030-FR-019 |
| G-05.16 | Flag off | Same blocks without Hand off… and Hand off again | 030-FR-002 |

### G-06 — Settings › Agents tab

| key | state | what shows | FR |
|---|---|---|---|
| G-06.01 | Loaded (M29) | List: "Hermes Tested ready", "Claude Tested ready", "Home server Stale"; + −; details for Hermes: "Tested ready · Ready to receive a hand-off.", Address "hermes.myhost.dev", Credential "Bearer token · stored sealed", Last contact "Today 10:21", Agent card "2.3 · protocol 1.0", Skills "Web research, bookings, email drafts", Updates "Streaming · no push", Guarantee "Guaranteed single start"; Test again, Replace credential…, Edit… | 030-FR-029 |
| G-06.02 | Testing | Test again shows "Testing…" and is disabled | 030-FR-030 |
| G-06.03 | No agents | Empty list; right side "No agents yet." and "Add new agent…" | 030-FR-029 |
| G-06.04 | No password on the account | List and details (read-only); line "Set a password to connect an agent." with "Open account on the web…"; no +, −, Replace credential…; Edit… changes the name only | 030-FR-036 |
| G-06.05 | Flag off | 028 S-03 content unchanged | 030-FR-037 |
| G-06.06 | Offline | Last-read list and details; every button disabled with "Needs a connection." | 030-FR-025 |
| G-06.07 | Read failed | "Agents couldn't be loaded." with Try again and "Reference: <id>" | 030-FR-038 |
| G-06.08 | Signed out | 028 signed-out content | 030-FR-001 |

### G-07 — Add new agent

| key | state | what shows | FR |
|---|---|---|---|
| G-07.01 | Empty (M30) | Name, Address + helper, Credential [Bearer token | API key] + secret + helper, Current password; Cancel, Add and test (disabled until all filled) | 030-FR-031 |
| G-07.02 | Adding / testing | "Adding…", then "Testing…"; fields disabled | 030-FR-031 |
| G-07.03 | Added, test failed | Sheet closes; the new agent selected with its status sentence (for example "Unreachable") | 030-FR-031 |
| G-07.04 | Wrong password | "That password isn't right."; password cleared and focused; other fields kept | 030-FR-034 |
| G-07.05 | Rejected address or name | The server's message under the field | 030-FR-034 |

### G-08 — Replace credential, Edit, Delete

| key | state | what shows | FR |
|---|---|---|---|
| G-08.01 | Replace credential | "Replace credential for <name>"; secret + helper; Current password; Cancel, Replace | 030-FR-032 |
| G-08.02 | Edit, name only | Name, Address, Credential type; no password; Cancel, Save | 030-FR-032 |
| G-08.03 | Edit, destination changed | G-08.02 plus Current password and "Confirm your password to change this agent's destination." | 030-FR-032 |
| G-08.04 | Delete (−) | "Delete <name>?"; "Its credential is destroyed. Runs already sent keep their history."; Current password; "Cancel" (default), "Delete" | 030-FR-033 |
| G-08.05 | Stale revision | "This agent changed elsewhere. Check and try again."; details re-read | 030-FR-034 |

## Copy

| key | text |
|---|---|
| Sidebar | Agents · All runs |
| All runs canvas | Add new agent |
| All runs | All runs · `<n>` runs / 1 run · Every step you handed off, by what it needs from you. · Nothing handed off yet. Choose Hand off… on a step's card. · Loading runs… · Runs couldn't be loaded. |
| Groups | Needs you · Running · Queued · To review · Lost contact |
| Waiting for | Agents · People · `<n>` people / 1 person, `<m>` agents / 1 agent |
| Compact states | Needs you · Running · `<t>` · Queued · Reported · `<day>` · Lost contact · `<t>` · (other labels verbatim) |
| Queued | Waiting for a free connection slot; nothing has been sent yet |
| Hand-off | Hand off… · Hand to an agent · It works on its own and comes back with a result. The step stays yours. · What it will get · Note: `<details>` · Project: `<name>` · Send to `<agent>` · Cancel · Sending… · Current password · I understand that a duplicate task is possible with this agent · No agent is ready to receive a hand-off. · Open Settings… · This step hasn't reached your account yet. · Handing off needs a connection. · Handing off isn't available right now. |
| Tiers | Guaranteed single start · Best-effort single start |
| Run | `<agent>` asks · Your answer · Reply · Stop run · Reply sent. Waiting for the agent. · Last contact `<time>` · Check again · The agent continued this run in a new task · Earlier runs |
| Result | Agent reported complete · Result · The result is too large to show here. · The agent finishing does not finish your step. You decide. · Then · Make the next step · Mark step done · Hand off again |
| Stopped | Stopped reporting · last contact `<t>` ago |
| Expired | Content expired under retention policy |
| Offline | Last updated `<time>`. This may be out of date. · Needs a connection. |
| Settings list | `<status>` words as the web (`agentCopy.ts:23-48`): Tested ready · Stale · Not tested · Invalid credentials · Unreachable · Unsupported · Agent changed · Rate limited |
| Details | Address · Credential · Last contact · Agent card · Skills · Updates · Guarantee · Bearer token · stored sealed · API key · stored sealed · `<v>` · protocol `<v>` · Streaming · no push / Streaming · push / No streaming · push / No streaming · no push · Ready to receive a hand-off. · Test again · Testing… · Replace credential… · Edit… · No agents yet. · Add new agent… · Agents couldn't be loaded. |
| Add | Add new agent · Name · Address · Its agent card is read from there when you test. · Credential · Bearer token · API key · Stored sealed. It is never shown again. · Current password · Add and test · Adding… |
| Other sheets | Replace credential for `<name>` · Replace · Save · Confirm your password to change this agent's destination. · Delete `<name>`? · Its credential is destroyed. Runs already sent keep their history. · Delete |
| No password | Set a password to connect an agent. · Open account on the web… |
| Errors | That password isn't right. · Too many attempts. Try again in a few minutes. · This agent changed elsewhere. Check and try again. · Try again · Reference: `<id>` |

## Deviations from the board

| board element | 030 | reason |
|---|---|---|
| M21, M30: no password field | Current password where the server requires it (G-04.03, G-07.01, G-08) | Max, D2 |
| M21: "What it will get" title differs from the step ("Compare van hire prices" under "Call Sam about the van") | The manifest's title, which is the step's own title | The server sends the step's title; mock data differ |
| M21: no acknowledgement, no external-copy notice | Shown when the server returns them (G-04.04, G-04.02) | The server requires the acknowledgement; the notice is part of the manifest (spec 007) |
| M22: "Hermes · asks about card holds" | "Hermes · " + the question's first line | No server field summarises a question; nothing is invented |
| M23 and M29: Waiting for count 5 vs header "2 people, 4 agents"; M29/M30 show "Waiting for 3" and no Agents section | Count and header computed from the same rows: people + agents | Cells use different mock data |
| M23: Agents group omits the Queued and second Running runs that M22 lists | Waiting for's Agents group lists the same runs as All runs | One run set for both surfaces (D1) |
| States not drawn (Failed, Cancelled, Delivery unconfirmed, Sent, Accepted, Cancellation requested, Not sent, disconnected, expired, no longer reports) | Grouped per 030-FR-006 and shown verbatim | Pending (a) default |
| Hand-off entry not drawn ("A sheet from the step's card") | "Hand off…" in the inspector's action row | Smallest entry on the step's card |
| M29: − copy, Replace credential and Edit sheets not drawn | G-08 | Needed for real server actions; wording from the web and DSAgents ("Delete Hermes…") |
| Loading, offline, error, password-less, flag-off states | G-01.07, G-02.03 – G-02.06, G-04.05 – G-04.11, G-05.13, G-06.02 – G-06.08, G-07.02 – G-07.05 | Not drawn |

## Affordance → requirement map

| affordance | state | requirement |
|---|---|---|
| All runs / agent row / Add new agent (sidebar) | G-01.02 – G-01.06 | 030-FR-004, 030-FR-008 |
| Run row (canvas, Waiting for) | G-02.07, G-03.04 | 030-FR-011 |
| Hand off… / Hand off again | G-04, G-05.06 | 030-FR-013, 030-FR-022 |
| Agent choice, Send to `<agent>`, Cancel | G-04.02 – G-04.07 | 030-FR-014 – 030-FR-018 |
| Reply / Stop run / Check again | G-05.01, G-05.03, G-05.12 | 030-FR-020, 030-FR-023 |
| Mark step done / Make the next step | G-05.06 | 030-FR-022 |
| Earlier runs | G-05.14 | 030-FR-019 |
| + / − / Test again / Replace credential… / Edit… | G-06.01 | 030-FR-029 – 030-FR-033 |
| Add and test | G-07.01 | 030-FR-031 |
| Open account on the web… | G-06.04 | 030-FR-036 |
| Try again | G-02.06, G-04.07, G-06.07 | 030-FR-038 |

Requirements with no affordance: 030-FR-003 (no invented values), 030-FR-012 (steps never
changed by runs), 030-FR-024 (polling), 030-FR-026 (memory-only), 030-FR-027 (expiry),
030-FR-028 (inert text), 030-FR-035 (secrets), 030-FR-039 (logs), 030-FR-042 (boundaries).

## Keyboard and focus

- Sidebar: the Agents rows are in the sidebar's arrow-key order; Return opens.
- All runs and Waiting for: run rows take ↑/↓ like task rows; Return selects the step and
  moves focus to the inspector's run section.
- Hand-off sheet: focus starts on the selected agent row; ↑/↓ change the agent; Tab moves
  to the password field or acknowledgement when shown, then to Send; Return sends when
  enabled; Esc cancels.
- Run section: Tab reaches the reply field, Reply, Stop run, the Make the next step field,
  Mark step done, Hand off again; ⌘Return in the reply field sends the reply.
- Settings › Agents: the list takes ↑/↓; + and − are tab stops with names "Add agent" and
  "Delete agent"; sheets as above, with Esc cancelling and Delete never the default button.
- VoiceOver reads a run row as "Compare van hire prices, Hermes, Needs you"; a timeline row
  as "Running, 10:03, checked 6 firms"; states are words, never colour alone.
- Focus ring: `focus-ring` role in both appearances.

## Primary loop impact

Handing off is delegating: the step stays in its list (often Next actions) and its run
shows in Waiting for next to people, as the DSAgents page says. Capture, clarify/approve,
routing, CRT and evidence are unchanged. The Mac's weekly review row stays deferred
(spec 020), so runs do not appear in a review here.

## Mobile viability

Not applicable to this feature's screens (macOS only). The kit wrappers are
platform-neutral so the iPhone can build its own screens later.
