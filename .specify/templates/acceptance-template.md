# Acceptance: [FEATURE NAME]

**VERDICT**: [accept | reject]
**Feature**: `specs/[###-feature-name]/`
**Graded**: [date]  **Implementation SHA**: [sha]
**Auditor**: `acceptance-auditor` (did not write the code under grade)

<!--
  Produced by /speckit-accept. This grades whether the tests that pass actually
  cover what the spec promised — a different question from "is the suite
  green", which delivery-verifier already answered.

  An acceptance gate that never rejects is not a gate. Reject without hedging
  when the evidence does not hold.
-->

## Tally

| | count |
|---|---|
| criteria total | [n] |
| covered | [n] |
| weak (test exists but does not exercise it) | [n] |
| missing | [n] |
| hollow tests found | [n] |

Full matrix: `traceability.md`

## Blockers

<!-- Empty when accepted. One entry per criterion that fails. -->

1. **[FR-### / SC-###]** — [what is missing]
   - would satisfy it: [the specific test, at the specific layer]

## Evidence

| check | command | result |
|---|---|---|
| product-e2e stories | `validate_ci_artifacts.py product-e2e-results --path frontend/allure-results/playwright` | [pass/fail] |
| result freshness | `validate_ci_artifacts.py results --since-file …/.run-started-at` | [pass/fail] |
| allure taxonomy | `validate_allure_taxonomy.py --path … --label …` | [pass/fail] |
| requirement coverage | `check_requirement_coverage.py specs/[###-feature-name]` | [pass/fail] |
| backend coverage | line [n]% / branch [n]% (floor 95/95) | [pass/fail] |
| frontend coverage | [n]/[n]/[n]/[n] (floor 95×4) | [pass/fail] |

## Measured criteria

For every `SC-###` that states a number, cite the measurement — not an opinion.

| criterion | target | measured | source | tier |
|---|---|---|---|---|
| SC-001 | [—] | [—] | [report path, SHA] | [INTERNAL floor \| PUBLIC-ON] |

Voice-related measurements cite a `scripts/voice_evidence_report.py` run whose
SHA equals the implementation SHA above. State the tier per criterion, not once
for the feature.

## Design state coverage

| design state id | tested by | status |
|---|---|---|
| D-01 error | [file::name] | [covered / waived, because …] |

## Spot-checked for hollowness

Three tests most likely to be hollow were read in full:

| test | would it still pass with the feature deleted? |
|---|---|
| [file::name] | [no — asserts real behavior \| YES, hollow] |

## Waivers

| criterion | why it is not tested | approved by |
|---|---|---|
| [—] | [—] | [—] |

<!-- A waiver needs a human. An auditor cannot waive its own finding. -->
