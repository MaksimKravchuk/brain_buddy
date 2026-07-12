# BrainBuddy mobile-first proposal artifacts

Open `prototype.html` directly in a modern browser. No backend, build, or network access is required.

Public PR preview: https://brain-buddy-frontend-pr-62.fly.dev/design/mobile-first-proposal.html?screen=recording

Use the scenario selector in the top-right corner to jump between representative states, or follow the clickable paths from Brain Dump and Weekly Review. Stable screenshot routes use `?screen=<name>`.

## Files

- `design-brief.md` — hierarchy, navigation, responsive rules, component principles, critical journeys, and whole-product screen inventory.
- `decision-log.md` — deliberate inclusions, exclusions/deferred scope, and ten founder questions.
- `prototype.html` — self-contained responsive HTML/CSS/JS prototype.
- `capture-screenshots.mjs` — deterministic Playwright export and click-journey verification.
- `screenshots/` — compact 1× PNG review exports.

## Screenshot set

| File | Viewport | State |
|---|---:|---|
| `01-brain-dump-active-375.png` | 375×812 | Active capture with chronological session task list and compact recorder |
| `02-brain-dump-active-430.png` | 430×932 | Active capture at the wider required phone viewport |
| `03-brain-dump-paused-375.png` | 375×812 | Stable task list with compact paused / resume / finish state |
| `08-brain-dump-finished-430.png` | 430×932 | Finished session with compact next-step control state |
| `04-weekly-review-queue-375.png` | 375×812 | Bounded queue and real progress |
| `05-weekly-review-crt-promotion-430.png` | 430×932 | Item detail and keep/edit/delete/defer/route/promote actions |
| `06-crt-focused-tree-430.png` | 430×932 | Focused mobile CRT subtree and selected-node form |
| `07-desktop-brain-dump-1440.png` | 1440×960 | Three-pane desktop comparison |

## Reproduce screenshots

From the repository root, after `npm ci` in `frontend/` and `npx playwright install chromium`:

```sh
node docs/design/mobile-first-proposal/capture-screenshots.mjs
```

The script checks each viewport for console/page errors and horizontal overflow, then exercises:

`empty session → recording → paused → resumed → finished → review → partial result`

## Visual self-audit

Surface choice: **Operate** for Brain Dump and Weekly Review; **Explore / Inspect** for CRT.

Initial slop diagnostic: **0/10**.

- No decorative tech gradient or generic violet accent; sky is inherited from the existing BrainBuddy palette.
- No equal-weight feature tile grid, accent rails, monument stats, icon toppers, or unearned glass treatment.
- Composition follows active work: the session task list, actionable review queue, focused item, and desktop panes.
- Centering is limited to true empty/completion states; the recorder is a compact dock utility.
- Typography follows the existing product’s precise sans posture with native fallbacks for a fully offline artifact.

Post-verification score: **0/10**. The 375px and 430px active views keep all four task cards dominant and readable, including the long-text case. The paused view communicates state through text and static bars, and the 430px finished view keeps next steps compact without reintroducing capture diagnostics.
