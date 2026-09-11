# UX Requirement Quality Checklist: Compact Task Rows

**Purpose**: Validate that the accepted interaction and evidence requirements are
complete, unambiguous, and mutually consistent before task generation.

## Density and content

- [x] CHK001 Is the exact collapsed-row height defined independently from expanded detail?
- [x] CHK002 Are mandatory versus progressively hidden row elements explicitly distinguished?
- [x] CHK003 Are Project/List and Delete exclusions stated for every collapsed row?
- [x] CHK004 Are fixed assigned-control bounds and comparable internal alignment measurable?

## Inline interaction

- [x] CHK005 Is route state the sole open/closed authority with no second local panel state?
- [x] CHK006 Is non-control row activation bounded to the 44 px header rather than expanded detail?
- [x] CHK007 Are Close, same-row, Escape, shortcut, completion, and unavailable-row focus outcomes defined?
- [x] CHK008 Does the Escape contract protect portaled modal review as well as nested controls?
- [x] CHK009 Is canonical recovery total across current context, Project, lifecycle, terminal, cancelled, 404, pagination failure, and interruption?
- [x] CHK010 Is autosave ownership across inline unmount explicit without inventing a second editor?

## Agent control and consent

- [x] CHK011 Are shortcut and chooser separate controls with Task-disambiguated accessible names?
- [x] CHK012 Is offline behavior frozen as inspectable review with disabled confirmation and nothing queued?
- [x] CHK013 Is confirmed-dispatch focus transfer defined when the split trigger is replaced?
- [x] CHK014 Are visible compact state, exact server state, tier/cancellation disclosure, and Task completion authority kept distinct?
- [x] CHK015 Is rollout-OFF behavior specified separately for new hand-offs and existing runs?

## Privacy, resilience, and evidence

- [x] CHK016 Is the browser record shape, owner/API scope, update point, expiry eligibility, cleanup actors, and rollback limitation explicit?
- [x] CHK017 Is the privacy-policy/retention disclosure a numbered acceptance requirement with tests?
- [x] CHK018 Are in-memory cached summaries distinguished from persisted browser preference data?
- [x] CHK019 Are missing/another-owner errors non-leaking without requiring an originating row?
- [x] CHK020 Is the accessibility threshold assigned to an executable discovered browser check?
- [x] CHK021 Are exact-SHA production journey evidence and synthetic-data constraints explicit?

## Notes

- All items pass against the founder-accepted artifacts dated 2026-09-11.
- This checklist validates requirement quality only; implementation evidence is created
  by `/speckit-implement` and `/speckit-accept`.
