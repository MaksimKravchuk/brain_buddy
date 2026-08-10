# ADR-0011: The spec review campaign is a portable stage, not a managed-outcome overlay

- **Status**: Accepted
- **Date**: 2026-08-10
- **Supersedes in part**: ADR-0009 (Architect planning review control plane)
- **Relates to**: ADR-0008 (verified trunk serial landing), ADR-0010 (spec-driven Kanban control plane)

## Context

`.specify/workflows/speckit/workflow.yml` and `scripts/spec_kit_planning_review.py`
implement a working review campaign: bounded fan-out with `max_concurrency`,
read-only sandboxing, strict JSON schema validation, fail-closed error
handling, deterministic fan-in, run-state persistence, and a test file.

It was also, in practice, unreachable. Three things put it out of use:

1. `workflow.yml` described itself as "Historical bounded planning review
   retained for compatibility".
2. `docs/spec-driven-kanban.md` instructed readers never to run it.
3. `docs/spec-kit-workflow.md` declared review out of Spec Kit's scope.

So the repository owned a review gate and simultaneously forbade running it.
Every feature since has been specified with no independent review stage unless
it happened to be enrolled in a managed outcome — which is the minority path.

Two defects made the gate unsafe to reintroduce as-is, both since fixed:

- `aggregate_reviews` decided the campaign status purely from finding
  severity. A reviewer returning `changes-required` with only `important`
  findings was aggregated to `approved`. The verdict a reviewer was
  specifically asked to produce was read for display and then discarded.
- `validate_handoff` hardcoded `status: "approved"` and dropped the
  `founder_acceptance` record, converting an honest unconverged review into a
  clean approval and destroying the campaign history that makes
  `founder-accepted` defensible.

Separately, the panel had structural gaps. All three standard roles ran the
same model (`gpt-5.6-sol`), so their blind spots were correlated, and their
prompts saw only `spec.md` and `plan.md` — design, tasks, contracts and the
data model were invisible to review. No role covered consent, retention,
purge, export disposition or owner scoping, despite Constitution Principle I
being the repository's most binding rule. No role covered UI state
completeness, keyboard/focus behavior or mobile viability, despite Principle V.

## Decision

The review campaign is a **portable stage of the standard feature workflow**.
It runs for every new or materially changed feature, in Claude Code or Codex,
with or without a managed outcome. It is not a Hermes overlay and does not
require one.

Concretely:

1. **The gate honors reviewer verdicts.** Any reviewer verdict of
   `changes-required` blocks, on its own, independent of finding severity. Any
   `product_decisions` or a `product-decision-required` verdict blocks and
   escalates to the human.

2. **`founder-accepted` survives validation intact**, carrying its full
   `founder_acceptance` record. It is never rendered as `approved`.

3. **Five lenses, not three.** Added: `privacy-consent-security` (Principle I)
   and `ux-accessibility-mobile` (Principle V). Both run as Claude Code
   subagents, which also removes the single-runtime failure: the three
   original lenses shell out to the `codex` CLI and cannot run where it is not
   installed. The reviewer agent files under `.claude/agents/` are the single
   source of rubric truth; the driver points at them rather than restating the
   rubric, so the two cannot drift.

4. **A deterministic preflight runs before any model.** Unresolved
   NEEDS CLARIFICATION markers, missing mandatory spec sections, duplicate or
   malformed `FR-###`/`SC-###` ids, unchecked checklist items and unfilled
   placeholders hard-fail for free. Spending a reviewer round on a defect a
   regex can find is waste.

5. **Reviewers see the whole package** — spec, design, plan, tasks, contracts,
   data model, research, checklists — not just spec and plan.

6. **Risk is derived, not defaulted.** Planning artifacts are scanned for file
   paths and classified by `scripts/classify_path_risk.py` (ADR-0008). An
   ASK-class surface derives `high` and adds the adversarial reviewer. Risk
   escalates and never de-escalates: an operator may raise a standard feature,
   but may not talk the classifier out of an ASK-class surface. When the
   classifier derives `high` and the campaign was launched `standard`,
   `summarize` fails closed rather than reporting a standard-panel result.

7. **Hard cap of two campaigns.** Fresh reviewer sessions re-litigate
   artifacts from scratch, so blocking-finding counts diverge between runs even
   as every verified defect is fixed. Spec 005 demonstrated this: five
   campaigns, nine product decisions, and `founder-accepted` invented
   mid-flight. Campaign 1 findings carry forward into campaign 2 prompts. After
   campaign 2 the options are: land the fixes, defer the residue into explicit
   open lanes, or close by founder acceptance with the full record.

## Consequences

**Positive.** Every feature gets an independent review stage. Two constitutional
principles that no reviewer covered are now covered. The gate stops laundering
verdicts. The campaign runs on a Claude-only machine, in degraded form,
reporting exactly which lenses did not run rather than presenting a partial
campaign as a clean one.

**Costs, accepted.** Five reviewers cost more per campaign than three, and more
reviewers mean more findings — which is why the two-campaign cap and
carry-forward are mandatory rather than advisory. The correlated-blind-spot
problem improves but does not vanish: three of five lenses still share a model,
so the aggregation rule must not treat them as five independent votes.

**Documentation that had to change with this decision**, because leaving any of
it in place would recreate the contradiction that made the gate unusable:

- `docs/spec-driven-kanban.md` no longer forbids running the campaign.
- `docs/spec-kit-workflow.md` documents review as an in-scope stage and records
  the aggregation rule and the campaign cap.
- `workflow.yml` no longer describes itself as historical.

**Adding or removing a role touches five places atomically.** The role enum in
`review.schema.json`, `STANDARD_ROLES`/`ROLE_CONFIGS`, the `workflow.yml`
fan-out items and `max_concurrency`, the `missing_standard` check in
`validate_handoff`, and `handoff.schema.json`'s `reviewers.minItems`. A partial
change fails the campaign closed — which is the correct direction, but the
error is opaque, so change all five together.

## Alternatives rejected

**Leave it managed-outcome-only.** Keeps the contradiction and leaves the
majority path with no review stage at all.

**Build a new review engine.** The existing one already implements bounded
fan-out, sandboxing, schema validation, fail-closed handling, deterministic
fan-in and run persistence, with tests. Only the role list, artifact scope and
risk default were wrong. Rewriting would discard working, tested machinery to
re-earn the same properties.

**Make every lens a Claude subagent.** Would lose the deliberate model
diversity of the codex roles and make the whole panel share one provider's
blind spots.
