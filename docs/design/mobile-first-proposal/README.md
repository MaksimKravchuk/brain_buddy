# Brain Dump founder-review artifacts

Open `prototype.html` directly in a modern browser. No backend, build, or network access is required.

Public PR preview: https://brain-buddy-frontend-pr-62.fly.dev/design/mobile-first-proposal.html?screen=recording

The prototype is intentionally limited to one flat Brain Dump session: capture, edit/delete, add by voice or text, and save all remaining drafts to RTM Inbox.

## Files

- `design-brief.md` — the narrow product flow, states, responsive rules, and scope guardrail.
- `decision-log.md` — founder reset, accepted decisions, and explicitly removed concepts.
- `prototype.html` — self-contained responsive HTML/CSS/JS prototype.
- `capture-screenshots.mjs` — deterministic Playwright exports and end-to-end interaction checks.
- `screenshots/` — 375px and 430px exports for every prototype state.

## Screenshot set

| File | Viewport | State |
|---|---:|---|
| `01-brain-dump-active-375.png` | 375×812 | Voice capture and flat provisional list |
| `02-brain-dump-active-430.png` | 430×932 | Voice capture at the wider required phone width |
| `03-brain-dump-review-375.png` | 375×812 | Plain edit/delete list and three outcomes |
| `04-brain-dump-review-430.png` | 430×932 | Review at the wider required phone width |
| `05-brain-dump-add-text-375.png` | 375×812 | Append one draft by text |
| `06-brain-dump-add-text-430.png` | 430×932 | Add-text state at the wider required phone width |
| `07-brain-dump-saved-375.png` | 375×812 | Session saved to RTM Inbox |
| `08-brain-dump-saved-430.png` | 430×932 | Saved state at the wider required phone width |

## Reproduce and verify

From the repository root, after `npm ci` in `frontend/` and `npx playwright install chromium`:

```sh
node docs/design/mobile-first-proposal/capture-screenshots.mjs
```

The script checks every state and viewport for console errors and horizontal overflow, verifies the required draft labels and Cancel / Stop / Review controls, and exercises:

`capture → edit wording → delete draft → add text → add voice → save session to RTM Inbox`

It also rejects Brain Dump copy containing planning, analysis, hierarchy, routing, promotion, or destination concepts.

## Visual self-audit

Surface choice: **Operate**. The flat session list and plain editor dominate; there is no secondary planning composition.

Slop diagnostic: **0/10**.

- No gradient, generic violet accent, feature-tile grid, accent rail, monument stat, icon topper, or decorative blur.
- Centering is reserved for the terminal saved state.
- The existing slate/sky visual vocabulary and native productivity typography are retained.
- Composition follows the work: capture list, editor, single text form, completion.
