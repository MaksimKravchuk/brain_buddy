# Carry On on the web

The web frontend is moving to the Carry On design system screen by screen, and
each screen goes live as soon as its PR lands. The brand guide is
`.claude/skills/brain-buddy-design/brand/README.md`; the screens are the Web row
of the design canvas (cells `M01-Web` to `M30-Web`), which follows the Mac app.

## What is already global

`frontend/src/styles/carryOn.css` applies these app-wide: Instrument Sans as the
body font, the limestone ground, no resting shadows (`shadow-soft`,
`shadow-raised`, `shadow-inset`, `shadow-glow` resolve to none) and a basalt
focus ring. The shared `Button` already uses roles: `primary` is basalt,
`accent` is terracotta, `secondary` and `danger` are quiet stone.

## How a screen migrates

Replace raw palette classes (`text-slate-500`, `bg-white`, `border-slate-200`,
`bg-sky-700`, `bg-brand-primary`…) with the roles below, and follow the board
for layout. A migrated file should hold no raw palette classes.

| Utility | Light | Use |
|---|---|---|
| `ground` | limestone `#E9E5DD` | page background |
| `sunken` | stone `#DCD7CD` | sidebar, sunken areas |
| `card` | paper `#FFFFFF` | cards, rows, the next step |
| `selected` | stone | selected row |
| `ink` | basalt `#1C1B19` | primary text, strong buttons |
| `ink-muted` | `#6B665C` | secondary text, metadata |
| `ink-done` | `#6B665C` | done steps, with `line-through` |
| `ink-accent` | `#A8432A` | small terracotta text |
| `accent` / `accent-pressed` | terracotta `#C4472A` / `#A8432A` | the one next step and its one button |
| `on-accent` | white | text on `accent` |
| `quiet` / `quiet-pressed` | stone / `#CBC5B9` | secondary buttons, chips, fields |
| `mark-open` | dust `#8A8478` | hollow step dots and icons, never text |
| `focus` | basalt | focus ring |
| `warning` | ochre `#74591A` | due soon |
| `danger` | oxblood `#8E2A20` | overdue, destructive actions |

Shape: `rounded-control` (pill), `rounded-card` (14px), `rounded-sheet` (34px).
Type: `font-voice` (Instrument Serif) for titles and empty states;
`text-co-title` 32, `text-co-step` 26 (the next step, weight 600),
`text-co-body` 17, `text-co-meta` 15. Nothing that must be read is under 15px.

## House rules

- Terracotta marks the user's next step and its button, once per screen.
  Everything else that is blue today becomes basalt or quiet.
- Done is `ink-done` with a strikethrough. An AI suggestion is a quiet card until
  it is accepted.
- No shadows, gradients or glass on content; no hairline borders (separate with
  space or a change of field); no tiny uppercase labels.
- Show only behaviour the web has. If a board shows something the code lacks,
  leave it out and list it in the PR.
- There are no task priorities.
- Design-system colours are followed exactly; no invented colours. Text colour
  contrast is not gated by tests (axe `color-contrast` is disabled in Playwright
  specs). Decision: Max, 2026-10-16.
- Resolve every review thread you address; the ruleset blocks merge otherwise.

## Dark mode

Dark role values exist under `:root[data-theme="dark"]`, but nothing sets that
attribute yet: a dark ground under screens that still hard-code white cards
would be unreadable. Turn it on after the last screen migrates, together with
removing `styles/tokens.css` and the old theme values in `styles.css`.
