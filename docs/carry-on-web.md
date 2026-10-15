# Carry On on the web

The web frontend is moving to the Carry On design system screen by screen. The
brand guide is `.claude/skills/brain-buddy-design/brand/README.md`; the screens
are the Web row of the design canvas (cells `M01-Web` to `M30-Web`), which
follows the Mac app.

## How a screen migrates

Production keeps today's look until every screen is done, then switches at once.
To make that possible, a migrated component keeps its current classes and adds
the Carry On look behind the `co:` variant:

```tsx
className="rounded-lg bg-sky-700 text-white co:rounded-control co:bg-accent co:text-on-accent"
```

`co:` applies only under `<html data-brand="carry-on">`. Layout changes go behind
`co:` too (`co:gap-4`, `co:text-co-step`), so nothing a slice changes reaches
production before the switch.

- Preview: open any page with `?brand=carry-on` (remembered in this browser;
  `?brand=legacy` returns). A build with `VITE_BRAND=carry-on` defaults to it.
- Role utilities (`bg-ground`, `text-ink-muted`, `bg-accent`…) are used only
  behind `co:`. They are defined in `frontend/src/styles/carryOn.css`, light and
  dark.
- Under `carry-on` the body font becomes Instrument Sans, resting shadows
  (`shadow-soft`, `shadow-raised`, `shadow-inset`, `shadow-glow`) disappear and
  the focus ring turns basalt, everywhere and without per-component work.

## Roles

| Utility | Light | Use |
|---|---|---|
| `ground` | limestone `#E9E5DD` | page background |
| `sunken` | stone `#DCD7CD` | sidebar, sunken areas |
| `card` | paper `#FFFFFF` | cards, rows, the next step |
| `selected` | stone | selected row |
| `ink` | basalt `#1C1B19` | primary text |
| `ink-muted` | `#6B665C` | secondary text, metadata |
| `ink-done` | `#6B665C` | done steps, with `line-through` |
| `ink-accent` | `#A8432A` | small terracotta text |
| `accent` / `accent-pressed` | terracotta `#C4472A` / `#A8432A` | the one next step, the one primary button |
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

- Terracotta marks the user's next step and the one primary button. Everything
  else that is blue today becomes basalt or quiet.
- Done is `ink-done` with a strikethrough. An AI suggestion is a quiet card until
  it is accepted.
- No shadows, gradients or glass on content; no hairline borders (use
  `co:border-transparent` and a change of field instead); no tiny uppercase
  labels.
- Show only behaviour the web has. If a board shows something the code lacks,
  leave it out and list it in the PR.
- There are no task priorities.

## The switch

When every screen is migrated: delete the plain classes that have a `co:`
twin, drop the `co:` prefixes, set `data-brand` permanently, rename the app to
Carry On, and remove `styles/tokens.css` and the old theme values.
