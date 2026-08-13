# Requirements Checklist

Quality gate for [spec.md](spec.md) itself: is it written well enough to build
from and to accept against? Ticked at authoring time; re-checked at acceptance.

## Clarity

- [x] Every requirement is testable by a mechanical check or a real command.
- [x] No requirement names a solution the spec has not justified.
- [x] Out-of-scope items are enumerated rather than implied — a later reader can
      tell "declined" from "forgotten".
- [x] The absence of a product surface is stated explicitly, not left to
      inference ([design.md](design.md)).

## Coverage

- [x] Every requirement has a task in [tasks.md](tasks.md).
- [x] Every success criterion has a way to observe it: 008-SC-001 the canary and
      008-SC-002 workflow ordering assertions. Browser usability and diff-only
      capability counts are explicitly manual acceptance checks.
- [x] The failure mode that motivated the feature — a red test in a green run —
      is covered by an executable check, not only by review.

## Consistency

- [x] Retention copy in the comment matches the retention expression in the
      workflow (7 PR / 30 push), which is unchanged by this feature.
- [x] "Additional, not a replacement" holds: `allure-report-html` keeps its name,
      path and content.
- [x] No requirement contradicts an existing repository gate; none is weakened.

## Risk

- [x] The gate cannot be silently disabled: warn-only and ruleset-replacing
      arguments are rejected, the config is ASK class, and the canary would fail
      loudly if the CLI stopped enforcing the rule.
- [x] A red gate cannot destroy its own evidence: the diagnostics precede it.
