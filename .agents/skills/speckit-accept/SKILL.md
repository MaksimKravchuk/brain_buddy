---
name: "speckit-accept"
description: "Grade a delivered feature against its spec: build the criterion-to-test traceability matrix, validate the evidence is fresh and meaningful, and issue an accept or reject verdict."
argument-hint: "Optional feature slug; defaults to the current feature branch"
compatibility: "Requires spec-kit project structure with .specify/ directory"
metadata:
  author: "brainbuddy"
  source: "brainbuddy pipeline stage 9 (Codex twin)"
user-invocable: true
disable-model-invocation: false
---

## User Input

```text
$ARGUMENTS
```

# Acceptance stage (Codex)

Codex twin of `.claude/skills/speckit-accept/SKILL.md`.

Grades whether the tests that pass actually cover what the spec promised — a
different question from "is the suite green".

Codex has no subagent runtime. Apply the contract in
`.claude/agents/acceptance-auditor.md` directly; it is the single source of
truth for the grading procedure. **The independence requirement still holds**:
an agent that wrote the code will rationalize when grading it. If this session
implemented the feature, hand acceptance to a fresh session.

## Preconditions

Refuse and say so unless all hold: every task in `tasks.md` is checked off, the
verification chain is green, and the review gate returned `approved` or
`founder-accepted`. Never grade an unimplemented feature.

## Output

- `specs/NNN-<slug>/traceability.md` — one row per criterion:
  `criterion | statement | test (file::name) | layer | evidence | status`,
  status ∈ `covered` | `weak` | `missing`.
- `specs/NNN-<slug>/acceptance.md` from
  `.specify/templates/acceptance-template.md`, carrying an explicit
  `VERDICT: accept | reject`.

## The anti-fake checks

A green suite can still be hollow. Run these yourself:

```bash
python3 scripts/validate_ci_artifacts.py product-e2e-results \
  --path frontend/allure-results/playwright

python3 scripts/validate_ci_artifacts.py results \
  --path frontend/allure-results/playwright --label playwright-e2e \
  --since-file frontend/allure-results/playwright/.run-started-at

python3 scripts/validate_allure_taxonomy.py \
  --path frontend/allure-results/playwright --label playwright-e2e

python3 scripts/check_requirement_coverage.py specs/NNN-<slug>
```

Coverage matching is **feature-qualified** (`006-FR-001`). A bare `FR-001` does
not count — every feature restarts numbering, so bare ids would let another
feature's tests satisfy this gate.

Then read three tests you would most expect to be hollow. If a test's
assertions would still pass with the feature deleted, say so.

For voice-related measured criteria, cite a `scripts/voice_evidence_report.py`
run whose SHA equals the implementation SHA, and state the tier — INTERNAL
floor vs PUBLIC-ON — **per criterion**.

## Rejecting

Reject without hedging when any criterion is `missing`, when a user-journey
criterion is satisfied only by a unit test, when results predate the
implementation, or when a spot-checked test is hollow. An acceptance gate that
never rejects is not a gate. Say what would satisfy it; do not fix it here.

## Completion report

```
ACCEPTANCE: accept | reject
feature: specs/NNN-<slug>
CRITERIA <n>: covered <n> | weak <n> | missing <n>

BLOCKERS
1. <criterion id> — <what is missing> — <what would satisfy it>

EVIDENCE
  product-e2e stories: pass|fail   freshness: pass|fail
  allure taxonomy:     pass|fail   requirement coverage: pass|fail
  hollow tests found:  <n>

NEXT: $speckit-report
```
