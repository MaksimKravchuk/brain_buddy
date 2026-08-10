---
name: "speckit-accept"
description: "Grade a delivered feature against its spec: build the criterion-to-test traceability matrix, validate the evidence is fresh and meaningful, and issue an accept or reject verdict."
argument-hint: "Optional feature slug; defaults to the current feature branch"
compatibility: "Requires spec-kit project structure with .specify/ directory"
metadata:
  author: "brainbuddy"
  source: "brainbuddy pipeline stage 9"
user-invocable: true
disable-model-invocation: false
---

## User Input

```text
$ARGUMENTS
```

# Acceptance stage

Grades the built feature against the spec that authorized it. This is a
different question from "do the tests pass" — that question was already
answered by `delivery-verifier`. This stage asks whether the tests that pass
actually cover what was promised.

## Preconditions

Stop and say so if any is unmet:

1. Implementation is complete — every task in `tasks.md` checked off.
2. `delivery-verifier` reported green, or the equivalent chain was run.
3. The review gate returned `approved` or `founder-accepted`.

Refuse to grade an unimplemented feature. `hooks.after_tasks` registers this
skill as **optional** precisely because tasks existing does not mean code
exists.

## Procedure

Delegate to the `acceptance-auditor` subagent. It is deliberately a different
agent from `feature-implementer`: an implementer grading its own work
rationalizes, and this is the gate where that costs the most. If the same
session wrote the code, delegating is not optional.

The auditor writes two files:

- `specs/NNN-<slug>/traceability.md` — one row per criterion:
  `criterion | statement | test (file::name) | layer | evidence | status`,
  where status is `covered`, `weak`, or `missing`.
- `specs/NNN-<slug>/acceptance.md` — from
  `.specify/templates/acceptance-template.md`, carrying an explicit
  `VERDICT: accept | reject`.

## The three anti-fake checks

Run these yourself after the auditor reports. Their entire purpose is that a
green suite can still be hollow, and taking the auditor's summary on trust
defeats the point of the gate.

```bash
# 1. Product E2E stories are present with meaningful nested steps
python3 scripts/validate_ci_artifacts.py product-e2e-results \
  --path frontend/allure-results/playwright

# 2. Results postdate the implementation, not a stale run
python3 scripts/validate_ci_artifacts.py results \
  --path frontend/allure-results/playwright --label playwright-e2e \
  --since-file frontend/allure-results/playwright/.run-started-at

# 3. Taxonomy is real: epic, feature, story, title, named steps
python3 scripts/validate_allure_taxonomy.py \
  --path frontend/allure-results/playwright --label playwright-e2e
```

For voice-related measured criteria, cite a `scripts/voice_evidence_report.py`
run whose SHA equals the implementation SHA, and state the tier — INTERNAL
floor vs PUBLIC-ON — **per criterion**, not once for the feature.

Then close the traceability loop mechanically:

```bash
python3 scripts/check_requirement_coverage.py specs/NNN-<slug>
```

## Rejecting

Reject without hedging when the evidence does not hold. Specifically reject
when any criterion is `missing`, when a user-journey criterion is satisfied
only by a unit test, when results predate the implementation, or when a
spot-checked test would still pass with the feature deleted.

An acceptance gate that never rejects is not a gate. Say what is missing and
what would satisfy it; do not fix it here — fixing is the implementer's job
and grading your own repair reintroduces exactly the bias this stage exists to
remove.

## Completion report

```
ACCEPTANCE: accept | reject
feature: specs/NNN-<slug>

CRITERIA <n>: covered <n> | weak <n> | missing <n>

BLOCKERS
1. <criterion id> — <what is missing> — <what would satisfy it>

EVIDENCE
  product-e2e stories: pass|fail    freshness: pass|fail
  allure taxonomy:     pass|fail    requirement coverage: pass|fail
  hollow tests found:  <n>

files: specs/NNN-<slug>/acceptance.md, specs/NNN-<slug>/traceability.md
NEXT: /speckit-report
```
