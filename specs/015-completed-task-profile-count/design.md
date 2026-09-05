# Design: Completed Task Profile Count

**Feature**: `specs/015-completed-task-profile-count/`
**Spec**: `spec.md` (clarifications settled: 2026-09-05)
**Screens**: no new mockup; this is one line inside the existing Profile card
**Human sign-off**: pending exact-package approval

## Applicability

This feature changes one existing user-visible surface. It does not add a page, control, dialog, navigation item or mobile surface.

## Screen inventory

| id | surface | screen | purpose | FR refs |
|---|---|---|---|---|
| D-01 | desktop and responsive web | Account settings — Profile card | Show the authenticated owner's current completed top-level task total beside existing profile information | FR-001…FR-012 |

## State inventory

### D-01 — Account settings Profile card

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| D-01-S01 loading | account request pending | an immediate plain-text polite status in the counter's final position; no spinner delay and no invented number; the existing form remains available | `Completed tasks: …` | FR-010 |
| D-01-S02 zero | authoritative count is 0 | a stable line below the Profile description and before the editable name field | `Completed tasks: 0` | FR-001…FR-006, SC-001 |
| D-01-S03 nonzero | authoritative count is greater than 0 | the same line with the exact integer | `Completed tasks: N` | FR-001…FR-006, SC-001…SC-003 |
| D-01-S04 refreshed after complete | a top-level task moves from an open state to completed and account data is observed again | the value is one higher than the prior authoritative value | `Completed tasks: N` | FR-007, SC-001 |
| D-01-S05 refreshed after reopen | a completed top-level task returns to an open state and account data is observed again | the value is one lower than the prior authoritative value | `Completed tasks: N` | FR-007, SC-001 |
| D-01-S06 unavailable | an authenticated non-401 account request fails, including a failed refetch with cached data | the counter is replaced by an alert; no cached or fallback number remains visible; the existing form remains available | `Completed tasks unavailable. Refresh the page to try again.` followed by `(ref: <correlation-id>)` when present | FR-010 |
| D-01-S07 unauthorized | the account request returns 401 | the existing global auth boundary clears the session, unmounts Profile and redirects to `/login`; no counter or retained form remains | existing login screen | FR-009, FR-010 |

Empty filtered results, partial failure and offline/interrupted states do not apply independently: this is a scalar field on the existing authenticated account request. Zero is the explicit empty state; authenticated non-401 initial/refetch failures use D-01-S06, while 401 uses D-01-S07. Recovery from D-01-S06 is a normal page refresh: it returns through D-01-S01 and reaches D-01-S02 or D-01-S03 on success. No counter-specific Retry control is added.

## Affordance → requirement map

The counter has no affordance. Page refresh is the existing recovery action. Existing display-name form, Save profile control and account actions remain available and unchanged.

### Requirements with no affordance

- FR-001…FR-012 are display, derivation, isolation, module-ownership and compatibility behavior with no new interaction.

### Affordances with no requirement

- None added by this feature.

## Primary loop impact

No impact. Capture → atomic items → clarify/approve → route or CRT candidate → smart Weekly Review → evidence/results remains unchanged. The profile line reads the current result of the existing Task lifecycle.

## Mobile viability

- Native mobile is out of scope.
- Responsive Web Profile keeps the existing single-column card and adds wrapping-safe plain text; acceptance checks 390×851 and 1280×780 with no horizontal scroll.
- No tap target, one-handed reach or destructive action is added.

## Keyboard and focus

- The line is ordinary readable text and is not added to the tab order.
- Existing form focus order and focus restoration are unchanged.
- No icon-only control, color-only state or keyboard interaction is introduced.

## Design authority

- Reuse the existing Account settings typography, spacing and `SectionCard`; no new visual token or component is justified.
- Vocabulary check: pass — the canonical term Tag is unchanged and no forbidden legacy product term is introduced.
- Existing design-skill validator remains part of `make check-specs`.

## Open decisions for the human

1. Approve or reject this exact package; there are no remaining copy, placement or behavior choices inside the agreed scope.
