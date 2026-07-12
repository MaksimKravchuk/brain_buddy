# BrainBuddy mobile-first proposal artifacts

Open `prototype.html` directly in a modern browser. No backend, build, or network access is required.

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
| `01-brain-dump-recording-375.png` | 375×812 | Recording, uploaded chunks, live transcript, stop/review action |
| `02-brain-dump-confirm-430.png` | 430×932 | Frozen proposal review and separate CRT promotion |
| `03-brain-dump-error-retry-375.png` | 375×812 | Partial commit, unknown route status, idempotent retry |
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

`idle → recording → processing → drafts → confirmation → partial result`

## Visual self-audit

Surface choice: **Operate** for Brain Dump and Weekly Review; **Explore / Inspect** for CRT.

Initial slop diagnostic: **0/10**.

- No decorative tech gradient or generic violet accent; sky is inherited from the existing BrainBuddy palette.
- No equal-weight feature tile grid, accent rails, monument stats, icon toppers, or unearned glass treatment.
- Composition follows active work: recording feedback, actionable queue, focused item, and desktop panes.
- Centering is limited to the record control and true empty/completion states.
- Typography follows the existing product’s precise sans posture with native fallbacks for a fully offline artifact.

Post-verification score: **0/10**. Visual inspection found one screenshot-export issue (fixed browser chrome over full-page captures) and one half-visible CRT action; exports now use viewport capture and the redundant inline CRT save control was removed from the overview state.
