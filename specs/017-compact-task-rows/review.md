# Review record: feature 017 — Compact Task Rows

This is the durable record of the portable Spec Kit planning review. Machine outputs
remain under the gitignored `.specify/workflows/runs/` directory.

**Gate verdict**: `founder-accepted` (never represented as `approved`)

**Planning risk**: medium

**Landing class**: ASK, because persistent browser personal data and privacy copy change

**Acceptance expiry**: 2026-10-10

## Campaigns

| campaign | exact reviewed digest | true automated status | panel |
|---|---|---|---|
| `017-compact-task-rows-c1` | `e80bba222f45f335127b86230748ab063848c5915f13c47dd29deedae6e7669c` | `product-decision-required` | five lenses, two providers, no degradation, uncorrelated |
| `017-compact-task-rows-c2` | `08a991549b9917e35ae64cda579036e03557576c584e858acbdfea381283bec8` | `product-decision-required` | five lenses, two providers, no degradation, uncorrelated |

The post-campaign amended artifact digest accepted by the owner is
`fa8ae16ddb538f7934327c1c363da350a810fda65f067d72cd93c9e98d9806c9`;
this includes the mechanically derived `tasks.md` generated after acceptance and adds
no product decision.
No third campaign is permitted by ADR-0011.

## Owner decisions

Max approved all four recommended options in the task conversation:

1. A valid out-of-projection Task navigates to its canonical context and expands only
   below its real row.
2. Desktop collapsed rows keep visible agent/status copy short; full tier and
   cancellation disclosure remains in the accessible name and inline detail, while
   native iOS remains unchanged.
3. Canonical precedence is current matching context after filter clearing, then a
   resolvable Project, then open lifecycle state, then Next actions for terminal or
   no-Project Tasks; cancelled fallback includes `showCancelled=1`.
4. Offline split controls remain operable to inspect review; confirmation is disabled
   and review says nothing is queued.

## Closure

All verified blocking and important findings were resolved in the amended artifacts:
header-bounded activation, sibling-modal Escape protection, collapse-only shortcut,
one-redirect/ten-page canonical recovery, non-leaking 404, auth/global preference
cleanup, honest local-retention/rollback language, ASK landing, executable Axe evidence,
discovered Playwright coverage, production journey evidence, and focus transfer after
confirmed hand-off. Two advisory cleanup lanes remain explicit in
`planning-review-closure.json`.

The owner accepted the bounded residual on 2026-09-11 after it was disclosed. The full
rationale, campaign history, expiry, residual lanes, and compensating measures are in
`planning-review-closure.json`. This opens implementation; it does not authorize ASK
landing or a production release.
