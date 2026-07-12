# Thinking-assistant pivot decision log

Status: proposed for founder review

Scope: self-contained design artifact only; no production UI, API, persistence, deployment, or merge

## Accepted from the supplied handoff

1. **Tasks are the primary workspace.** GTD-style lists and projects replace the CRT canvas as the application’s starting surface.
2. **Thinking is task-scoped.** Thinking/CRT opens from a specific task or problem; it is not a top-level default canvas.
3. **Brain Dump is task-list-first.** Provisional tasks are the dominant capture surface and recording controls stay compact.
4. **Capture and review are separate states.** Stopping recording leads to manual review/edit before any durable effect.
5. **Weekly Review remains an entry point.** It belongs alongside task lists, without committing to detailed interactions in this artifact.
6. **Existing product visual vocabulary remains recognizable.** The proposal reuses the current slate surfaces, sky accent, thin borders, modest elevation, and focus treatment.

## Founder constraints preserved from the later Brain Dump review

1. Every current-session draft keeps stable `#N`, `Wording still changing`, and `Provisional` language.
2. Capture contains no timer, transcript, pipeline panel, hierarchy, planning, analysis, coaching, recommendation, destination picker, or tree UI.
3. Capture has compact Cancel and Stop & review controls; the draft list remains dominant.
4. Wording is corrected only in the separate review state.
5. No output is silently saved. The user must explicitly confirm the reviewed set.

## Necessary adaptations for accepted architecture

1. **Proposal-only authority.** The handoff’s “extracted” or “headed to inbox” language is changed to provisional wording until explicit confirmation, preserving ADR-0002.
2. **No live task writes during recording.** Fast and smart model stages may update the operation workspace only; the UI does not imply canonical Inbox creation before confirmation.
3. **One shared async contract.** Weekly Review copy explicitly reuses Brain Dump’s resumable operation, patch, retry, privacy, and confirmation substrate rather than inventing a second voice flow.
4. **Task tracker stays behind a port.** “Inbox” is user-facing destination language; this artifact does not introduce tracker CRUD or a proprietary BrainBuddy task domain.
5. **Existing CRT survives as a bounded module.** Task-scoped entry opens a placeholder for the current Thinking/CRT capability rather than redesigning or duplicating its graph model.
6. **Responsive shell is newly resolved.** The handoff’s desktop sidebar becomes bottom navigation and a single-column workspace on phones while preserving the same task-first hierarchy.
7. **Review preview delivery is isolated.** CI copies the standalone artifact into the PR review app only; production source routes and components remain unchanged.

## Deferred / open founder questions

1. Should the default task view be Inbox, Next actions, or a Today projection once production requirements are written?
2. Which GTD labels belong in BrainBuddy versus the external task tracker?
3. Should Thinking/CRT open as a full route, drawer, or modal after task selection?
4. Does Brain Dump confirmation always target the configured tracker’s Inbox, or can approved captures remain in BrainBuddy for later organization?
5. What is the minimum useful Weekly Review entry screen before designing its item-by-item voice interaction?
6. Which account/profile controls belong in the final responsive shell?

## Explicit non-goals

- production React components, routes, APIs, repositories, or async runner code
- changing authentication, persistence ownership, state machines, or backend contracts
- detailed Weekly Review scripts, item cards, progress, coaching, or completion flow
- autonomous routing, execution, external-task editing, or silent canonical writes
- redesigning the CRT graph, inventing new analysis methods, or putting a tree in capture
- calendars, recurrence, reminders, priorities, dashboards, fake metrics, or analytics
- deployment or merge from this card

## Gate

The draft PR and HTTPS preview are review evidence only. Production implementation requires explicit founder approval and a separate card.
