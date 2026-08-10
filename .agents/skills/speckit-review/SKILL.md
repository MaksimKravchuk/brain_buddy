---
name: "speckit-review"
description: "Run the portable five-lens spec review gate: deterministic preflight, parallel reviewer fan-out, and one aggregated verdict that decides whether the feature may enter implementation."
argument-hint: "Optional run id; defaults to a generated one"
compatibility: "Requires spec-kit project structure with .specify/ directory"
metadata:
  author: "brainbuddy"
  source: "brainbuddy pipeline stage 5, ADR-0011 (Codex twin)"
user-invocable: true
disable-model-invocation: false
---

## User Input

```text
$ARGUMENTS
```

# Spec review gate (Codex)

Codex twin of `.claude/skills/speckit-review/SKILL.md`.
`.specify/extensions.yml` registers this as a **mandatory** `after_plan` hook
in a file shared by both agent trees, so it must exist here.

ADR-0011 governs this stage: a portable gate that runs for every feature,
managed outcome or not. The former "never run the legacy workflow.yml
campaign" rule was superseded.

This is the single front door. Do not invoke
`scripts/spec_kit_planning_review.py` ad hoc.

## Step 1 — deterministic preflight

```bash
python3 scripts/spec_kit_planning_review.py preflight --run-id "<run-id>"
```

Hard-fails **before any model runs** on unresolved NEEDS CLARIFICATION
markers, missing mandatory spec sections, duplicate or malformed
`FR-###`/`SC-###` ids, unchecked `checklists/requirements.md` items, and
unfilled placeholders. Fix the spec and rerun; do not skip it.

It also records `derived_risk` from `scripts/classify_path_risk.py`, which
may only **raise** the class: an ASK-class surface derives `high`,
everything else derives nothing and the campaign runs at the declared
class (default `medium`).

## Step 2 — fan out

Five lenses, `max_concurrency: 5`:

| role | runtime |
|---|---|
| `requirements-consistency` | codex |
| `architecture-consistency` | claude |
| `testability-evidence` | codex |
| `privacy-consent-security` | claude |
| `ux-accessibility-mobile` | claude |

Plus `adversarial-high-risk` when risk is `high`.

**Runtime asymmetry cuts both ways.** On a Claude-only machine the two codex
lenses cannot run. In a Codex-only session the three Claude lenses cannot run —
`build_review_command` shells out to the `claude` CLI and fails closed via
`shutil.which`. Their rubrics live in `.claude/agents/architecture-consistency-reviewer.md`,
`security-privacy-reviewer.md` and `ux-a11y-reviewer.md`; those are plain
markdown, so when the `claude` CLI is absent you may apply the three rubrics
yourself and write the resulting JSON to
`.specify/workflows/runs/<run-id>/reviews/<role>.json`.

Whichever lenses could not run independently, **say so by name in the report**.
A partial campaign is never reported as a clean one.

## Step 3 — aggregate

```bash
python3 scripts/spec_kit_planning_review.py summarize --run-id "<run-id>"
```

Gate rule, in order (ADR-0012):

1. Any configured lens produced no review → **`escalated`**. Missing mandatory
   evidence never resolves to a pass.
2. Any `product_decisions`, or a `product-decision-required` verdict →
   **`product-decision-required`**. Needs the human.
3. Any `changes-required` verdict, or any `blocking` finding →
   **`technical-changes-required`**.
4. Risk `high` with no recorded human sign-off → **`escalated`**.
5. Otherwise → **`approved`**.

A reviewer's verdict blocks on its own; the aggregator does not re-derive it
from severities. A malformed review still raises — absence and corruption are
different.

Risk classes are `low | medium | high`. Unknown risk is **medium**, never low.
`low` is an operator declaration; derivation never produces it, because at
review time there is no diff and a *mentioned* path is not a changed one.
Risk escalates and never de-escalates.

## Step 4 — campaign cap

**Hard cap: two campaigns.** Fresh reviewer sessions re-litigate from scratch,
so counts diverge between runs even as every verified defect is fixed. Carry
campaign 1's findings forward into campaign 2. After campaign 2: land the
fixes, defer the residue into explicit open lanes, or close by founder
acceptance with the full record: `accepted_by`, `accepted_on`, `expires_on`,
at least one concrete `compensating_measures` entry, a substantive rationale of
at least 120 characters, and the complete `campaign_history`. The acceptance
expires — validation fails once `expires_on` has passed, because an acceptance
with no end date is a permanent hole in the gate. Fabricating `approved` is
prohibited.

## Step 5 — report

```
REVIEW VERDICT: approved | escalated | technical-changes-required | product-decision-required | founder-accepted
run id: <run-id>   campaign: <1|2>   risk: low | medium | high (derived | operator-set)
lenses: <n>/<n> ran     MISSING: <roles + why>

BLOCKING (<n>) / IMPORTANT (<n>) / ADVISORY (<n>)
PRODUCT DECISIONS FOR THE HUMAN (<n>)

summary: .specify/workflows/runs/<run-id>/planning-review-summary.json
```

Product decisions are not yours to answer — put them to the human, write the
answers back into `spec.md`, and rerun.

Implementation must not start unless the verdict is `approved` or
`founder-accepted`.
