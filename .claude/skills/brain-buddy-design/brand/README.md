# Carry On brand

Carry On is the approved next brand for the app. It replaces the Brain Buddy name,
the Sprout mark and the sky palette, but **production has not migrated yet**: the
web frontend and the iOS app still ship the system described in `../README.md`.
Use this folder for brand work, new mockups and the migration itself; do not mix
the two systems on one screen.

The working boards live on the design canvas "BrainBuddy visual language"
(boards *Carry On · brand kit* and *Carry On · stair icon*).

## The idea

The product helps a person carry what life puts on them and keep walking: take the
heavy, stuck thing, find one step you can take now, take it. The attitude is stoic:
*do what you must, come what may.* Nothing in the brand celebrates productivity or
speed; it shows a person with a load, on steep steps, taking the next one.

Tagline: **Do what you must. Come what may.**

## Marks

| File | Use |
|---|---|
| `mark.svg` | The hiker on steps, ink with a terracotta head. On limestone or paper. |
| `mark-on-dark.svg` | The same in limestone, for basalt backgrounds. |
| `app-icon.svg` | The app icon ("closer" sunset): a terracotta sun behind the hiker, limestone stairs across the whole icon, basalt sky. Square; the platform applies the corner mask. |

Construction, on a 64 grid: the head is a separate circle (r 4.8) and is the only
part that may change colour; the body is built from thick round-capped strokes; the
stick is planted on the next step; steps run 10 across and rise 8. Never outline the
figure, never add a face, never redraw it at a gentler slope. Below 40px drop the
stick-and-steps mark in favour of the app icon.

The "you are here" mark (steps with a single dot) is kept in reserve and is not part
of the current system.

The wordmark is "Carry On" set in Instrument Serif, regular, tight tracking
(−0.02em). It is never set in capitals.

## Colour

Four colours, used in proportion: mostly limestone, then basalt, a little dust, and
one touch of terracotta.

| Token | Hex | Meaning |
|---|---|---|
| Limestone | `#E9E5DD` | The ground. Default background. |
| Basalt | `#1C1B19` | Ink, and the dark theme's ground. |
| Dust | `#8A8478` | What is not in your control: done, later, waiting on others. |
| Terracotta | `#C4472A` | You and your next step. **One per screen.** |

Contrast rules: basalt on limestone is 13.7:1. Terracotta on limestone is 3.9:1, so
use it for shapes, large text and buttons (white on terracotta is 4.9:1); for small
terracotta text use `--co-terracotta-text` `#A8432A`. Dust on limestone is 2.96:1
and is never used for text; use `--co-dust-text` `#6B665C`. On basalt, dust text
passes (4.6:1).

`tokens.css` holds these as CSS custom properties (prefix `--co-`) with light and
dark roles; `tokens.json` holds the same values for the iOS app.

## Type

Two typefaces, no more.

- **Instrument Serif** is the voice: the wordmark, screen titles, the tagline,
  empty states. Regular weight only (it has no bold).
- **Instrument Sans** is the action: steps, buttons, lists, metadata.

The next step is the biggest sans text on the screen (`--co-text-step`, 26/600).
Body text is 17px; nothing that must be read is smaller than 15px.

## Components

- **The next step** sits on a paper card (radius 14) on limestone: the project in
  muted text above, the step itself in `step` type below.
- **Buttons** are pills. Primary "Done" is terracotta with white text; secondary
  "Not now" is stone with basalt text. One primary per screen.
- **Step lists**: finished steps are dust and struck through; the current step is
  a limestone row with a terracotta dot; future steps are dust with a hollow dot.
- Phone sheets use a 34px top radius.

## House rules

From the taste-skill review of the brand kit:

- No gradients, glows, glass, or resting shadows. Depth comes from whole fields of
  colour (limestone, paper, basalt), not from shadow.
- No thin rules or hairline grids; separate things with space or a change of field.
- No tiny uppercase labels, no eyebrows above headings, no monospace.
- Imagery is drawn in the brand's flat colours (sun, stepped mountains, the hiker)
  until real photography exists; never stock people.
- The palette knowingly breaks one taste-skill rule (terracotta on a warm light
  ground). It stays because limestone and terracotta are the stone and the road of
  the idea, not a template choice.

## Migration notes

- Rename and re-skin together; a Carry On name over sky-blue screens is worse than
  either system alone.
- Map product roles, not hex values: sky-500 "primary" becomes terracotta only
  where it marks the user's next step; elsewhere it becomes basalt.
- The voice and copy rules in `../README.md` (sentence case, no emoji, calm second
  person, GTD vocabulary and the brain-dump authority copy) carry over unchanged.
