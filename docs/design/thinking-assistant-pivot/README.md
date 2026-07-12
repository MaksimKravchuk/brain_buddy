# BrainBuddy thinking-assistant pivot review

Founder-review package for the task-first / thinking-assistant pivot. This directory is documentation only and does not change the production React application or backend contracts.

## Review

Open `prototype.html` directly, or use its stable states:

- `?screen=workspace` — task/GTD workspace
- `?screen=task` — selected-task detail with task-scoped Thinking entry
- `?screen=thinking` — bounded placeholder proving task-scoped entry
- `?screen=capture` — task-list-first Brain Dump capture
- `?screen=review` — separate edit and explicit-confirmation state
- `?screen=confirmed` — confirmation-safe completion
- `?screen=weekly` — lightweight Weekly Review overview

Read `design-brief.md` for the interaction rationale and `decision-log.md` for accepted decisions, architecture adaptations, open questions, and non-goals.

## Deterministic verification

From the repository root:

```bash
node docs/design/thinking-assistant-pivot/capture-screenshots.mjs
```

The script:

- renders all seven stable states at 1440×900, 375×812, and 430×932;
- writes deterministic screenshots under `screenshots/`;
- rejects console/page errors and horizontal overflow;
- checks 44px visible interactive targets at both phone widths;
- checks required semantic landmarks and the `aria-live` state announcer;
- verifies the clickable workspace → capture → review → explicit confirmation → workspace path;
- verifies the Weekly Review entry and task → Thinking/CRT entry;
- rejects forbidden timer/transcript/pipeline/analysis/tree language in the capture main surface.

The draft PR review workflow exposes the artifact at:

`https://brain-buddy-frontend-pr-<PR>.fly.dev/design/thinking-assistant-pivot.html`

## Gate

This is review evidence, not production implementation. Founder sign-off is required before a separate implementation card begins.
