# Voice-only Brain Dump review artifacts

Open `prototype.html` directly in a modern browser. No backend, build, or network access is required.

The prototype is intentionally limited to voice capture, inline wording correction/deletion, return to voice capture, and plain RTM Inbox export.

## Files

- `design-brief.md` — locked flow, states, responsive rules, and scope guardrail.
- `prototype.html` — self-contained responsive HTML/CSS/JS prototype.
- `capture-screenshots.mjs` — deterministic Playwright exports and interaction checks.
- `screenshots/` — 375px and 430px exports for every screen.

## Screenshot set

| File | Viewport | State |
|---|---:|---|
| `01-brain-dump-active-375.png` | 375×812 | Active voice capture and flat provisional list |
| `02-brain-dump-active-430.png` | 430×932 | Active voice capture at the wider phone width |
| `03-brain-dump-review-375.png` | 375×812 | Inline wording edit/delete and two outcomes |
| `04-brain-dump-review-430.png` | 430×932 | Review at the wider phone width |
| `05-brain-dump-saved-375.png` | 375×812 | Saved RTM Inbox result |
| `06-brain-dump-saved-430.png` | 430×932 | Saved result at the wider phone width |

## Reproduce and verify

From the repository root, after `npm ci` in `frontend/` and `npx playwright install chromium`:

```sh
node docs/design/voice-only-brain-dump-review/capture-screenshots.mjs
```

The script checks all screens and viewports for console errors and horizontal overflow, verifies the required draft markers and capture controls, rejects forbidden capture/planning copy, and exercises:

`voice capture → inline wording edit/delete → return to voice capture → save to RTM Inbox`

## Visual self-audit

Surface choice: **Operate**. The flat draft list and inline editor dominate; there is no secondary capture or planning composition.

Slop diagnostic: **0/10**.

- No tech gradient, generic violet accent, feature-tile grid, accent rail, monument stat, icon topper, or decorative blur.
- Centering is reserved for the terminal saved result.
- The slate/sky visual vocabulary and native productivity typography are retained.
- Composition follows the work: voice capture list, inline review, completion.
