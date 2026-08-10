# ADR-0012: Risk classes, escalation, bounded risk acceptance, and gate integrity

- **Status**: Accepted
- **Date**: 2026-08-10
- **Amends**: ADR-0011 (portable spec review stage) — does not replace it
- **Relates to**: ADR-0008 (verified trunk serial landing)
- **Source**: the team Definition of Ready/Done agreement and the normative
  quality, delivery and product-risk guidance (Consensus Candidate v2)

## Context

ADR-0011 made the review campaign a portable stage and fixed two defects in it.
It is not rewritten here: per the governing policy, *history is not rewritten —
decisions change by creating a new version, not by retroactively editing the
original*. This record amends it.

Reconciling the pipeline against the two governing documents surfaced five
non-conformances. Four were introduced by ADR-0011's own implementation, which
makes them worth stating plainly rather than folding into a changelog:

1. **The risk default was inverted.** The policy requires that an unknown risk
   takes class `Medium`, and that lowering it requires objective rules to fire.
   `derive_risk()` returned `standard` — effectively the lowest class — whenever
   it could not classify. Silence was treated as evidence of safety, so exactly
   the work nobody could classify took the cheapest path through the gate.

2. **Risk acceptance was unbounded.** `founder-accepted` required an owner, a
   date, a substantive rationale and the full campaign history — but no expiry
   and no compensating measures. The policy permits out-of-policy risk
   acceptance only with *owner, rationale, expiry and compensating measures*. An
   acceptance that never expires is not an acceptance; it is the rule being
   permanently rewritten by whoever happened to be blocked that day.

3. **There was no `Escalated` state.** The policy is explicit that unavailable
   mandatory evidence, conflict between independent checks, or uncertainty above
   threshold yields `Escalated` — *never* majority-green. The aggregator knew
   only `approved`, `technical-changes-required` and `product-decision-required`,
   and a missing reviewer raised an exception rather than producing a recorded
   verdict.

4. **The panel's oracles were correlated.** Three of five lenses ran the same
   model. The policy states that a second actor is insufficient if it repeats
   the author's reasoning, tests or data. Three lenses on one model are one
   opinion counted three times, and the aggregation rule read that as
   corroboration.

5. **Nothing prevented an actor weakening its own gate.** Both documents forbid
   silently weakening one's own acceptance conditions, mandatory checks or
   permissions. `check_speckit_manifests.py` guarded the Spec Kit overrides;
   nothing guarded the aggregation logic, the permission allowlist, or the
   Makefile gate targets. An agent could edit `aggregate_reviews` and make
   itself pass.

## Decision

### Three risk classes, defaulting to medium

`low | medium | high`, replacing `standard | high`.

- `high` — any ASK-class surface per ADR-0008's classifier.
- `low` — every path named in the planning artifacts is inert (`docs/`,
  `specs/`, `requirements/`, `*.md`) **and at least one path was found**. This
  is the only branch that lowers the class, and it fires only on positive
  evidence.
- `medium` — everything else, explicitly including "no paths could be
  extracted".

Risk escalates and never de-escalates: an operator may raise the class, but the
classifier's finding cannot be argued down.

`high` additionally requires a recorded human sign-off. At that class an
uncorrelated automated mechanism alone is not sufficient evidence, so a clean
panel with no sign-off returns `escalated`, not `approved`.

`low` does not currently shrink the reviewer panel. Being stricter than the
policy's minimum is not a non-conformance, and a smaller panel is a change we
would want calibration data for first.

### `escalated` as a first-class gate status

Emitted when:

- a configured lens produced no review — missing mandatory evidence; or
- the class is `high` and no human sign-off is recorded.

A missing review no longer raises. It is recorded in
`planning-review-summary.json` alongside `missing_reviewers`, so an incomplete
campaign becomes an auditable fact rather than a stack trace someone can rerun
away. A malformed review still raises: absence and corruption are different,
one is a gap and the other is a defect in evidence that was produced.

`escalated` outranks everything except nothing — it is evaluated first, because
a campaign that did not fully run cannot be trusted to have surfaced the
product decisions either.

### Bounded risk acceptance

`founder_acceptance` now additionally requires:

- `expires_on` — an ISO date strictly after `accepted_on`. Validation fails
  once it has passed: an expired acceptance no longer closes the review.
- `compensating_measures` — at least one concrete mitigation. Entries under 20
  characters are rejected as placeholders.

### A de-correlated panel

`architecture-consistency` moves from `codex/gpt-5.6-sol` to `claude/opus`,
with its rubric in `.claude/agents/architecture-consistency-reviewer.md`. No
model now covers a majority of the panel and the panel spans two providers,
both asserted by tests rather than left to convention.

A side benefit: three of five lenses now run without the `codex` CLI, which is
what a single-runtime machine actually has.

### Gate integrity

`scripts/check_gate_integrity.py` runs in `make check-specs` and works in two
layers, because either alone is defeated:

- **Invariants** — properties that must hold regardless of how a file changes:
  the aggregator reads reviewer verdicts, `changes-required` blocks,
  `DEFAULT_RISK` is `medium`, missing evidence escalates, acceptance is
  time-bounded, the permission allowlist has no blanket `Bash` grant and never
  pre-approves `git push`, `check-specs` runs its validators, and both mandatory
  lenses remain in the role enum. **These are not waivable by `--update`.**
- **A hash manifest** of twelve guarded files, including the guard's own
  source. Any edit fails until re-recorded, which puts the new hash in the diff
  where a reviewer sees it.

The guard cannot prevent these edits — the files must stay editable. It removes
the word *silently*. Layer two alone would be defeated by updating the hash in
the same commit; that is precisely why layer one exists and cannot be waived.

Eight mutation tests assert each invariant actually fires when its property is
removed, so the guard cannot rot into a no-op.

## Consequences

**Positive.** The default now costs strictness rather than saving it. An
incomplete campaign is visible instead of fatal. Risk acceptance has an end
date. The panel's plurality is real rather than formal. The class of defect
where an actor quietly relaxes its own gate is now mechanically visible.

**Costs, accepted.** More changes land in `medium` than previously landed in
`standard`, so more work draws the fuller treatment — that is the intended
direction, but it is a real throughput cost. Every edit to a guarded file now
requires re-recording the manifest in the same commit; that friction is the
mechanism, not a side effect. Existing `founder-accepted` records without an
expiry become invalid and must be re-recorded with bounds.

**Still non-conformant, deliberately deferred.** Naming these is itself a
policy requirement — the Minimum Operating Baseline demands an explicit
`Pending` per missing capability rather than a general claim of compliance:

- No pull-time Ready gate on individual work items (DoR §3, G2).
- No unified `Pass | Fail | Pending | Escalated` vocabulary across all gates;
  only the review gate has `escalated`.
- No exact `candidate identity + run identity` binding for pre-integration
  evidence (§7.2).
- No invalidation of stale evidence when base, schema, flags or policy change
  (§6.3).
- No Quality-Risk Profile as versioned policy-as-code; the rules remain spread
  across skills, agents and scripts (§4).
- No flaky/quarantine policy with owner, expiry and cap (§11.1).
- No Bug / Hotfix / Spike fast paths (§11.2–11.4).
- No `Measuring` state or outcome decision; the pipeline ends at the report,
  so delivery is still implicitly treated as outcome (§1, G6).
- No sampling audit or calibration metrics (§13).
- Requirement-to-test coverage proves a test *names* a requirement, not that it
  was authored independently of the implementation (DoD §3). Independence
  still rests on the acceptance auditor's judgement.

## Alternatives rejected

**Amend ADR-0011 in place.** The governing policy forbids retroactive editing
of decisions; a superseding record is the prescribed mechanism.

**Keep two risk classes and rename `standard` to `medium`.** Cosmetic. Without
a `low` class there is no objective-rules branch to lower into, so the policy's
"exception only after objective rules apply" has nothing to apply.

**Guard the gates with hashes only.** Defeated by updating the hash in the same
commit, which is exactly what a self-weakening actor would do.

**Make `low` shrink the reviewer panel.** Proportionality argues for it, but
reducing coverage without calibration data trades a known cost for an unmeasured
risk. Revisit once the sampling audit exists.
