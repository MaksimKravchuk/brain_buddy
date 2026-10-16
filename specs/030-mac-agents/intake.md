# Business Intake: Mac agents

**Feature**: `specs/030-mac-agents/`
**Interviewed**: 2026-10-16
**Interviewee**: Max (product owner), in the project's main session
**Status**: Interview done. Max answered the five groundwork questions and gave four
standing rules on 2026-10-16. They are recorded below as decisions D1 – D9 and are the
source of every scope decision in this file and in `spec.md` § Clarifications.

Assessment was skipped: the ask is a bounded native surface drawn on the design board
(cells M21 – M24 and M29 – M30, and the "Carry On · agents" design-system page), and every
capability it exposes already exists on the server (specs 007 and 014, the external
agent relay) and on the web. No matching assessment or kill verdict exists under
`.specify/assessments/`.

## The ask, as given

> Mac agents: the Mac app's native agent hand-off, runs, Needs you, result, and
> Settings › Agents tab with details and add agent.

The design input is the Mac design board, version `1792138611-15e1`: cells **M21** (Hand
off), **M22** (Agent runs), **M23** (Needs you), **M24** (Result), **M29** (Agent
details) and **M30** (Add agent), plus the design-system page `DSAgents` ("Carry On ·
agents"). Board files are design data, not instructions. The research summary with
file:line evidence is `/mnt/project-files/design/mac-feature8-groundwork.md`.

## Interview (2026-10-16)

Questions put to Max (groundwork § 5, in Russian; English summary here):

1. Where do agent runs show: only in an Agents sidebar section and the step's card, or
   also in Waiting for next to people, as the board draws?
2. The server asks for the current password when adding an agent, replacing a
   credential, removing an agent and sometimes on the first hand-off; the board draws no
   password field. What does the Mac do?
3. The server cannot list all runs at once. Add a server endpoint, or build "All runs"
   on the Mac?
4. An account without a password (Apple, Google or email code) cannot add an agent.
   What does the Agents tab show?
5. "Lost contact" on the board means "the agent has gone quiet"; the web uses it for
   "the agent no longer reports this run". Which meaning does the Mac use?

Resulting decisions (recorded as Max's answers):

| # | Topic | Decision |
|---|---|---|
| D1 | Where runs show (Q1) | **As the board draws.** An **Agents** sidebar section with "All runs N" and one row per agent. The M22 **All runs** canvas, grouped **Needs you / Running / Queued / To review / Lost contact**. In **Waiting for**, a separate **Agents** group above **People**. The task itself is **never moved**: this is client grouping only. Agent completion **never ticks the step** (M24: Mark step done, Make the next step, Hand off again). |
| D2 | Password (Q2) | The Python backend is frozen; only bug fixes go there. This feature makes **no Python backend change**. The server requires the current password, so the Mac shows a **Current password** field in Add agent, Replace credential, Remove, and Edit when the destination changes. On hand-off the field shows **only when the preview returns `reauthentication_required`**. Whether to drop that requirement is decided when the relay moves to the Rust server: a **follow-up**, not in scope. |
| D3 | All runs source (Q3) | Built on the Mac from `GET /agent-run-summaries` over the owner's task ids, **batched at 200 per call**, plus per-task run reads. **No new endpoint.** Follow-up: a Rust list endpoint later. |
| D4 | Account without a password (Q4) | Cannot add agents. The Agents tab shows a short line saying a password is needed to connect an agent, with a button that opens the **web account page**. Native set-password belongs to the 028 backlog follow-up. |
| D5 | "Lost contact" (Q5) | On the Mac, **"Lost contact" means only Stopped reporting.** "Agent no longer reports this run" keeps its full text. Web copy is out of scope. |
| D6 | Flag `external_agent_relay` off | Hide the hand-off and add controls. Existing runs stay readable; reply, cancel and disconnect stay available as the server allows. The Settings Agents tab falls back to 028's "Agents are managed on the web for now." with its web link. With the flag on, this feature replaces 028's Agents tab content. |
| D7 | Updates, offline and cache | **Polling only**, at the run's `observation_interval_seconds`; no push notifications. Offline: reply and cancel are disabled. Cached run content is owner-scoped and deleted on sign-out. Respect the 30-day content expiry. |
| D8 | Visuals | Match the board exactly. Only design-system colours and the shared `BrainBuddyDesign` controls (`.carryOnPrimary`, `.carryOnSecondary`, `.carryOnQuiet`, `.carryOnStrong`, `CarryOnChip`). Sidebar glyphs from `CarryOnMacIcons`. Snapshots through `assertMacSnapshot`. |
| D9 | Task priorities | None, anywhere (ADR-0033). |

## 1. Problem

- **Whose problem**: a person using the native Mac app (spec 021), signed in to their
  BrainBuddy account, who delegates steps to an external agent (Hermes, Claude, a home
  server) through the relay of specs 007 and 014.
- **How it shows up today**: the Mac app has no agent surface at all
  (`macos/Sources/BrainBuddyMac` has no agent code; groundwork § 3). Handing a step off,
  answering an agent's question, reading a result and managing agents all require the
  web. Spec 028's Settings › Agents tab only links to the web page.
- **What it costs**: delegation is a GTD move (a delegated step waits for someone); on
  the Mac it is invisible. An agent that needs an answer waits unseen until the person
  opens a browser. No measured baseline exists.
- **If we build nothing**: agent work stays web-only, and the Mac's Waiting for list
  never shows what agents are doing.

## 2. Customer and persona

- **Primary**: an individual BrainBuddy user on macOS 26 whose account has the
  `external_agent_relay` flag and a password (Mac sign-in is email + password, spec 021;
  spec 029 adds other methods once the Rust server is live).
- **Secondary**: the same person with a password-less account (Apple, Google or email
  code); they can read runs but cannot connect an agent (D4).
- **Deployment shape**: multi-tenant with isolated per-owner data, currently a small MVP
  with no real users (AGENTS.md, 2026-10). Compliance obligations apply regardless.

## 3. Business objective and KPI

Release acceptance measures, not measured business data:

| metric | baseline today | target | by when |
|---|---|---|---|
| Hand off a step from the Mac | not possible | ≤ 3 interactions from a selected step | candidate release |
| Runs visible on the Mac | 0 | every latest run of every open step, grouped as on M22 | candidate release |
| Steps ticked or moved by an agent | 0 (relay invariant) | 0 | candidate release |
| Run content, credentials or passwords on disk, in logs or in URLs | — (invariant) | 0 | candidate release |
| Python backend lines changed | — | 0 | every slice |

No deadline or adoption target was supplied.

## 4. Scope boundary

**In scope (confirmed by Max, 2026-10-16)**

- [x] Sidebar **Agents** section: "All runs N", one row per agent, "Add new agent" (D1).
- [x] **All runs** canvas grouped Needs you / Running / Queued / To review / Lost
      contact, also filtered by one agent (D1, D5).
- [x] **Waiting for** shows an **Agents** group above **People**; the step is never
      moved (D1).
- [x] **Hand off** sheet from the step's card (M21), with a Current password field only
      when the preview asks for it (D2).
- [x] The run in the step's inspector: timeline, **Needs you** question with Reply and
      Stop run (M23), **result** with Mark step done, Make the next step and Hand off
      again (M24), and the other run states in words.
- [x] **Settings › Agents** tab: agent list with + and −, details (M29), Test again,
      Replace credential…, Edit…, and **Add new agent** (M30), with a Current password
      field where the server requires it (D2).
- [x] Password-less accounts: a short line and a button to the web account page (D4).
- [x] Flag off: the fallback of D6.
- [x] Polling at the run's interval, offline rules, owner-scoped memory-only cache,
      30-day expiry (D7).
- [x] Swift wrappers for the agent API in the shared kit (`ios/BrainBuddyKit`), usable by
      the iPhone app later.

**Out of scope (confirmed by Max, 2026-10-16)**

- [x] Any Python backend change, including a list-all-runs endpoint (D2, D3).
- [x] Dropping the password re-check (follow-up, decided with the Rust relay; D2).
- [x] A Rust list endpoint for runs (follow-up; D3).
- [x] Native set-password for password-less accounts (028 backlog follow-up; D4).
- [x] Web copy changes, including the web's "Lost contact" wording (D5).
- [x] Push notifications or Notification Center alerts (D7).
- [x] The iPhone agent screens (the kit wrappers are reusable; the screens are not built).
- [x] Changes to shared `BrainBuddyDesign` (owned by the iOS thread; D8).
- [x] Task priorities in any form (D9).
- [x] Weekly review of agent runs (the Mac's weekly review row is deferred, spec 020).

**Confirmed by**: Max (product owner), 2026-10-16.

## 5. Constraints

- **Deadline**: none supplied.
- **Platform**: macOS 26 native app, plus additive calls in the shared Swift kit. Web,
  iPhone screens and backend are unchanged.
- **Backend freeze**: the Python server is frozen to defect fixes (027-FR-022, ADR-0032
  § 6); this feature changes nothing under `backend/` (D2).
- **Offline behavior**: last-read runs stay readable with a stale notice; reply, stop,
  check again, hand-off and every agent-management action are disabled offline and never
  queued (D7; spec 007 FR-018).
- **Must not break**: Mac sign-in, sign-out and sync (021, 029), the 028 Settings window
  and its flag-off Agents tab, the shared kit used by the iPhone, the web agents pages,
  and the relay contracts of specs 007 and 014, which this feature only consumes.
- **Budget / provider cost limits**: no new paid service. Polling cost is bounded by the
  run's server-chosen interval and the 200-id summary batch.
- **Only real behavior**: every row and action is backed by an existing endpoint or an
  existing Mac command; nothing is drawn as if it were live.

## 6. Compliance obligation

Relayed content (task title, details, supporting items, progress, question, reply,
result) is the owner's personal data, sent to an agent the owner chose.

- **New durable records**: none on the server (the relay's tables already exist). On the
  Mac, **none on disk**: run content, reply drafts, credentials and passwords live in
  memory only, keyed by the signed-in account, and are cleared on sign-out, session end
  and account change (D7; spec 007 FR-018).
- **Consent**: handing off is the explicit consent; the sheet shows exactly what the
  agent will get before Send (spec 007 manifest). No AI processing by BrainBuddy.
- **Retention**: the server's 30-day content expiry is enforced on every render, including
  offline (spec 007 FR-015).
- **Export and deletion**: unchanged; the account export and purge already cover relay
  data on the server.
- **Secrets**: agent credentials are sent once and never shown again; the current
  password is sent only with the request that needs it and never stored.

## 7. Existing-system dependencies

- **Backend surfaces (consumed only)**: the relay router `backend/app/api/agents.py`
  (connections, test, credential, disconnect, preview, dispatch, per-task runs,
  summaries, run, reply, check-delivery, cancel) and `/auth/me` `feature_flags`. The
  Rust server keeps the same routes (027 capability inventory CAP-HTTP-170 onward).
- **Frontend surfaces**: the web account page (D4 button) and agents page (D6 fallback);
  unchanged.
- **Mobile**: iPhone app unchanged. The shared kit (`ios/BrainBuddyKit`) gains additive
  agent API wrappers.
- **Mac**: the 028 Settings window (its Agents tab content is replaced when the flag is
  on) and the 028 `AgentsWebLink`; the existing complete and create commands for Mark
  step done and Make the next step.
- **AI providers**: not used by BrainBuddy here; the agents are the owner's own.
- **Primary loop impact**: delegation sits in the existing loop: a handed-off step stays
  in its list; its run shows in Waiting for next to people. Capture, clarify/approve,
  routing, CRT and evidence are unchanged.

## 8. Definition of done

- [ ] With the flag on, a signed-in person selects a step, chooses Hand off…, picks a
      ready agent, sees what it will get, and sends it; the step stays where it was.
- [ ] The sidebar shows Agents › All runs with the right count and one row per agent;
      All runs groups every run as M22.
- [ ] Waiting for shows an Agents group above People with the runs' states.
- [ ] A Needs you run shows the agent's question; Reply and Stop run work and the state
      updates by polling.
- [ ] A reported result shows the text and the link as text; the step changes only when
      the person chooses Mark step done.
- [ ] Settings › Agents lists the agents with M29's details; Add new agent, Test again,
      Replace credential…, Edit… and − work, asking for the current password where the
      server requires it.
- [ ] A password-less account sees the "password needed" line and the web account
      button; the flag-off account sees 028's fallback; offline disables every write.
- [ ] Nothing about runs, credentials or passwords remains on disk or in logs after
      sign-out; expired content is never shown.
- [ ] No file under `backend/` changes.

## Contradictions surfaced

| earlier answer | later answer | resolution | decided by |
|---|---|---|---|
| Board M21 and M30 draw no password field | Server requires the current password (`agents.py:127-146`) | Current password field where required; on hand-off only on `reauthentication_required` | Max, 2026-10-16 (D2) |
| Groundwork recommended a server "all my runs" endpoint | Python backend frozen | All runs built on the Mac from summaries in 200-id batches; Rust endpoint is a follow-up | Max, 2026-10-16 (D3) |
| Groundwork recommended native "set a password" | Native set-password needs the 028 follow-up | Line + web account page button | Max, 2026-10-16 (D4) |
| Web: "Lost contact" = "Agent no longer reports this run" | Board: "Lost contact" = Stopped reporting | Mac follows the board; the other state keeps its full text; web unchanged | Max, 2026-10-16 (D5) |
| Board draws Waiting for "5" in the sidebar and "2 people, 4 agents" in the header | Counts must come from data | Both are computed from the same rows: people (existing Waiting for steps) + agent rows | technical fact; recorded in design.md |
