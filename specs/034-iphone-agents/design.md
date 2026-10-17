# Design: iPhone agents

Source: Carry On canvas https://claude.ai/artifact/1bwKiw15U2jpZqwu5pTMg6, version `1792165683-83f3`,
iPhone row cells M21 – M25, M29, M30, and the "Carry On · agents" page (`project/DSAgents.dc.html`).
The canvas is the design: this file numbers its screens and states and names what each control
does. Behaviour comes from [030 design.md](../030-mac-agents/design.md).

## Applicability

iPhone only (393 × 852 frame, iOS 26). The Mac surfaces are 030's.

## Screen inventory

| Id | Screen | Canvas | Presented as |
|---|---|---|---|
| I-01 | Waiting for with Agents group | M22 | the list screen |
| I-02 | Run sheet: Needs you | M23 | half sheet over the list (glass, 44 pt corners) |
| I-03 | Run sheet: Result | M24 | same sheet |
| I-04 | Run sheet: other states | — (030 G-05) | same sheet |
| I-05 | Hand to an agent | M21 | sheet from the step's card |
| I-06 | Account › Agents section | M25 | section of the Account / Settings screen |
| I-07 | Agent details | M29 | pushed from I-06 ("‹ Account") |
| I-08 | Add new agent | M30 | pushed from I-06 ("‹ Settings") |
| I-09 | Replace credential, Delete | — (030 G-08) | sheet / confirmation from I-07 |

## Layout (from the canvas)

- Title "Waiting for" serif 34, subtitle 15 secondary "2 people, 2 agents". Section labels "Agents",
  "People" 15/600 secondary, 20 pt inset.
- Run row: card row (surface-card, 12 pt radius, 14/16 padding, 8 pt gap), 24 pt robot glyph in
  mark-open, title 17, second line 15 secondary "<agent> · ● <state>" with an 8 pt dot: accent-fill
  dot + text-accent for Needs you, status-warning for Lost contact, mark-open otherwise; " · 4 min"
  after the state where 030's compact state adds it.
- Sheets: grabber 40 × 5 control-quiet-pressed; 22 pt side padding; meta line 15 secondary with a
  10 pt project dot; title 24/600; bottom glass bar 62 pt with the primary as tinted glass and the
  secondary as plain glass text (the shared bottom-bar geometry: 8 pt sides, 20 pt bottom).
- Timeline: 12 pt dots (text-done for passed, accent-fill for the current Needs you), 2 pt
  control-quiet-pressed connector, word 17 and meta 15 secondary.
- "<agent> asks" card: surface-card, 14 pt radius, 16 padding. "Your answer" field: control-quiet,
  14 pt radius.
- Result card: surface-card 14 pt radius, text 17/1.45; link row control-quiet 10 pt radius with
  the copy glyph. "Then" row: surface-card 14 pt radius with the Next glyph, "Make the next step"
  and a chevron.
- Hand off: serif 28 title, intro 15 secondary, "Choose agent" label, agent cards (surface-card,
  14 pt radius; selected = 2 pt text-primary inset ring), "What it will get" on control-quiet, the
  cancellation line 15 secondary, bar "Send to <agent>" / "Cancel".
- Account › Agents: grouped card rows (44 pt min) with robot glyph 20, name 17, status word 15
  with its dot, chevron; last row "+ Add new agent".
- Details: back "‹ Account", 64 pt glyph tile, name serif, status line; grouped sections
  "Connection" and "Read from its agent card"; skills as chips; guarantee line 15 secondary;
  buttons "Test again" (secondary), "Replace credential" (secondary), "Delete Hermes…" (danger
  text).
- Add: back "‹ Settings", title serif "Add new agent", fields Name, Address (+ helper), Credential
  segmented Bearer token / API key, secret (+ helper), Current password; bar "Add and test" /
  "Cancel".

## State inventory

- I-01: hidden (signed out, no runs) · loading (last list kept) · loaded · stale/offline ("Last
  updated … This may be out of date.").
- I-02/I-03/I-04: one per 030 label group; working (buttons disabled); failed (danger line with
  reference); offline ("Needs a connection."); reply pending ("Reply sent. Waiting for the agent.").
- I-05: loading agents · no ready agent · previewing · ready · needs password · needs
  acknowledgement · sending · failed · sent (sheet closes).
- I-06: not signed in (hidden) · loading · loaded · empty ("No agents yet.") · passwordless · flag
  off (rows only, no Add) · failed with Try again.
- I-07: loaded · testing · notice.
- I-08: idle · adding · testing · failed · done (pops back, agent selected).

## Copy

All strings come from `AgentsCopy` (030 design § Copy); the iPhone adds none.

## Deviations from the canvas

None planned. The canvas row M22 shows four agent rows under "2 people, 2 agents"; the header counts
what is listed.

## Affordance → requirement map

| Affordance | Requirement |
|---|---|
| Agents group, header, rows | 034-FR-004 |
| Row → run sheet | 034-FR-005 |
| Reply, Stop run, Your answer | 034-FR-006 |
| Mark step done, Make the next step, Hand off again, copy link | 034-FR-007 |
| Check again, other labels | 034-FR-008 |
| Hand off…, Send to, Cancel | 034-FR-009 |
| Account › Agents rows, Add new agent | 034-FR-010 |
| Test again, Replace credential, Delete | 034-FR-011 |
| Add and test | 034-FR-012 |
