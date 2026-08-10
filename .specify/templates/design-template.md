# Design: [FEATURE NAME]

**Feature**: `specs/[###-feature-name]/`
**Spec**: `spec.md` (Clarifications settled: [date])
**Screens**: `design/*.html`
**Human sign-off**: [name, date | pending]

<!--
  Produced by /speckit-design via the design-architect subagent, after
  /speckit-clarify and before /speckit-plan. This file is load-bearing: the
  plan must cite it, and acceptance-auditor traces criteria through the screen
  and state ids assigned here. Ids are stable forever once written — never
  renumber.

  ADR-0006: the term is Tag. "Context" and "@context" are forbidden strings and
  the design CI validator hard-fails on them.
-->

## Applicability

[Either: this feature has a user-visible surface, designed below.
Or: this feature has no user-visible surface, because [reason] — and the rest
of this document is intentionally empty.]

## Screen inventory

| id | surface | screen | purpose | FR refs |
|---|---|---|---|---|
| D-01 | desktop | [name] | [why it exists] | FR-001, FR-003 |
| M-01 | mobile | [name] | [why it exists] | FR-002 |

## State inventory

Every screen needs every applicable row. A missing state here becomes an
`important` finding from `ux-a11y-reviewer` two stages later.

### D-01 — [screen name]

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | [—] | [—] | [—] | [—] |
| loading | [—] | [skeleton/spinner, after how long] | [—] | [—] |
| empty (first run) | [—] | [—] | [—] | [—] |
| empty (filtered to nothing) | [—] | [—] | [—] | [—] |
| error | [—] | [retryable? correlation ID surfaced?] | [—] | [—] |
| partial failure | [—] | [which items succeeded, which did not] | [—] | [—] |
| offline / interrupted | [—] | [resume behavior per ADR-0002] | [—] | [—] |

## Affordance → requirement map

| screen | affordance | what it does | FR ref |
|---|---|---|---|
| D-01 | [button/control] | [—] | FR-001 |

### Requirements with no affordance

- [FR-### and why it needs no UI, or "none"]

### Affordances with no requirement

- [control and why it exists, or "none"] — a non-empty list here is scope
  creep and the plan stage must resolve it.

## Primary loop impact

Constitution Principle V requires this section. State how the feature affects
capture → atomic items → clarify/approve → route or CRT candidate → smart
Weekly Review → evidence/results, or declare no impact explicitly.

[—]

## Mobile viability

- **Viewport**: verified at 390×851, no horizontal scroll: [yes | issues]
- **Tap targets**: 44pt minimum honored: [yes | exceptions]
- **One-handed reach**: [—]
- **Destructive actions**: [confirmation copy, and what it says will be lost]

## Keyboard and focus

- **Tab order**: [—]
- **Focus on open**: [—]  **Focus restored on close to**: [—]
- **Escape**: [—]
- **Accessible names**: [any icon-only controls, and their labels]
- **State communicated by color alone**: [none | list]

## Design authority

- Tokens, colors, type and UI kit from the `brain-buddy-design` skill.
- Vocabulary check (ADR-0006, `Tag` not `Context`/`@context`): [pass]
- `python3 -m unittest scripts/test_validate_brain_buddy_design_skill.py`: [pass]

## Open decisions for the human

1. [the two or three choices a person should actually make]
