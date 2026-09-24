---
name: "speckit-review"
description: "Run the portable five-lens spec review gate: deterministic preflight, parallel reviewer fan-out, and one aggregated verdict that decides whether the feature may enter implementation."
argument-hint: "Optional run id; defaults to a generated one"
compatibility: "Requires spec-kit project structure with .specify/ directory"
metadata:
  author: "brainbuddy"
  source: "brainbuddy pipeline stage 5 (ADR-0011)"
user-invocable: true
disable-model-invocation: false
---

## User Input

```text
$ARGUMENTS
```

# Spec review gate

This is the single front door to the review campaign. Do not invoke
`scripts/spec_kit_planning_review.py` ad hoc — this skill exists so that the
preflight, the fan-out, the aggregation and the campaign cap always happen
together.

ADR-0011 governs this stage. It is a **portable** gate: it runs for every
feature, with or without a managed outcome. The old "never run the legacy
workflow.yml campaign" rule was superseded.

The campaign is a plain script any agent or developer can run. The historical
Claude/Codex CLI routes remain optional; the external adapter below does not
require either executable. A model adapter must still produce real review
evidence under the same validation and independence reporting rules.

## Preconditions

`spec.md` and `plan.md` must exist. Three of the five lenses cannot judge a
spec without the plan, so running before `/speckit-plan` produces noise.

## Step 1 — deterministic preflight

```bash
python3 scripts/spec_kit_planning_review.py preflight --run-id "<run-id>"
```

This hard-fails **before any model runs** on unresolved NEEDS CLARIFICATION
markers, missing mandatory spec sections, duplicate or malformed `FR-###` /
`SC-###` ids, unchecked `checklists/requirements.md` items, and unfilled
placeholders.

If it fails, fix the spec and rerun. Do not skip the preflight to "save a
round" — every defect it catches is one a regex found for free, and spending a
reviewer round on it is pure waste.

The preflight also records `derived_risk`, computed by running the planning
artifacts' file paths through `scripts/classify_path_risk.py`. An ASK-class
surface — auth, migrations, CI, deploy, secrets — derives `high`.

## Step 2 — independent review lenses

Run the five configured lenses (and `adversarial-high-risk` for high risk).
Each must review the same preflight artifact digest, read only the repository,
and return JSON matching `.specify/workflows/speckit/review.schema.json`.
Use genuinely independent reviewers where available; do not present five
runs of one model as independent agreement. The summary records actual
provider/model correlation.

The gate accepts a reviewer adapter that follows its JSON protocol. External
adapters are **always recorded as unverified and degraded**; caller-supplied
provider/model labels are claims, not proof of independent providers:

```bash
python3 scripts/spec_kit_planning_review.py review \
  --run-id "<run-id>" --role "<role>" \
  --reviewer-command "/path/to/read-only-review-adapter" \
  --provider "<actual-provider>" --model "<actual-model>"
```

The adapter reads the complete prompt on **stdin** and writes **only** review
JSON to stdout. `SPECKIT_REVIEW_ROLE` and `SPECKIT_REVIEW_SCHEMA` plus only a
small allowlist of process environment variables are passed. The adapter must
enforce read-only access itself; the generic subprocess cannot guarantee a
sandbox, and the adapter can still read files accessible to the current user.
Do not fabricate provider/model labels or pass a prewritten generic approval.
The harness stamps the executable, **claimed** provider/model, degraded
provenance and artifact digest, validates the JSON, and rejects missing evidence.

For backwards compatibility, omitting `--reviewer-command` uses the original
Codex/Claude CLI routing with its recorded fallback. Neither CLI is required
when a suitable external adapter is supplied. The three rubric documents
live at `.specify/review-rubrics/` and are shared across runtimes.

## Step 3 — aggregate

```bash
python3 scripts/spec_kit_planning_review.py summarize --run-id "<run-id>"
```

The gate rule, in order (ADR-0012):

1. Any configured lens produced no review → **`escalated`**. Missing mandatory
   evidence never resolves to a pass, and it is checked first: a campaign that
   did not fully run cannot be trusted to have surfaced the product decisions
   either.
2. Any `product_decisions`, or any reviewer verdict of
   `product-decision-required` → **`product-decision-required`**. Needs the
   human.
3. Any reviewer verdict of `changes-required`, or any `blocking` finding →
   **`technical-changes-required`**.
4. Risk class `high` with no valid human sign-off → **`escalated`**. At that
   class an uncorrelated automated mechanism alone is not sufficient evidence;
   a named human must accept the residual risk.

   The sign-off is **not** a flag you can pass to the campaign. It is a record
   at `.specify/workflows/runs/<run-id>/human-signoff.json`:

   ```json
   {
     "approved_by": "name or email of the human",
     "approved_on": "2026-08-10",
     "run_id": "<this campaign's run id>",
     "artifacts_digest": "<from planning-context.json>",
     "rationale": "what residual risk was accepted, and why"
   }
   ```

   It is rejected if the run id does not match (no replaying an approval into
   another campaign) or if the digest does not match the artifacts as they
   stand now (editing the spec invalidates the approval). Write it only when a
   human has actually approved; asserting it yourself is precisely the
   self-certification this gate exists to prevent.
5. Otherwise → **`approved`**.

A reviewer's own verdict is gate-blocking on its own. The aggregator does not
re-derive the verdict from finding severities — doing so used to launder
`changes-required` into `approved`.

A malformed review still raises. Absence and corruption are different: one is a
gap, the other is a defect in evidence that was actually produced.

## Risk classes

`low | medium | high`. The preflight reads the paths the planning artifacts
name, but **it may only raise the class, never lower it**:

- **high** — derived when any ASK-class surface is named (auth, migrations,
  CI, deploy, secrets). Adds `adversarial-high-risk` and requires human
  sign-off.
- **medium** — the default, and what every campaign runs at unless something
  raises or an operator declares otherwise.
- **low** — an operator declaration only. Derivation never produces it.

Why derivation cannot lower a class: at review time **there is no diff**, so
all it can see is which paths are *mentioned*, and a mention is not a change. A
spec rotating session tokens while merely citing `docs/auth.md` as background
reads identically to a documentation edit — an earlier version derived `low`
for exactly that. Lowering a class is an accountable declaration, not an
inference from prose.

Unknown risk is `medium`, never `low`: treating silence as safety would let
exactly the work nobody could classify take the cheapest path.

## Step 4 — the campaign cap

**Hard cap: two campaigns.** Fresh reviewer sessions re-litigate artifacts
from scratch, so blocking-finding counts diverge between runs even as every
verified defect is fixed. Spec 005 proved this: five campaigns, nine product
decisions, and `founder-accepted` had to be invented mid-flight.

- Campaign 1 → fix everything blocking → campaign 2.
- Carry campaign 1's findings forward into campaign 2's prompts so reviewers
  do not re-raise resolved issues.
- After campaign 2, the remaining options are: land the fixes and stop, defer
  the residue into explicit open lanes, or close by **founder acceptance**.
- Founder acceptance requires a full `founder_acceptance` record —
  `accepted_by`, `accepted_on`, `expires_on`, at least one concrete
  `compensating_measures` entry, a substantive rationale of at least 120
  characters, and the complete `campaign_history` with every run id and its
  true status. It documents *more* than an approval, never less. Fabricating
  `approved` is prohibited.
- **The acceptance expires.** Validation fails once `expires_on` has passed —
  an acceptance with no end date is not an acceptance, it is a permanent hole
  in the gate.

## Step 5 — report

```
REVIEW VERDICT: approved | escalated | technical-changes-required | product-decision-required | founder-accepted
run id:    <run-id>       campaign: <1|2>
risk:      low | medium | high   (derived | operator-set)   human sign-off: yes|no|n/a
lenses:    <n>/<n> ran      MISSING: <roles + why>

BLOCKING (<n>)
1. [<role>] <description>
   evidence: <path:line>
   fix:      <recommendation>

IMPORTANT (<n>)   ADVISORY (<n>)

PRODUCT DECISIONS FOR THE HUMAN (<n>)
1. [<category>] <question>
   why: <why_needed>
   options: <a> | <b>
   affects: <affected_acceptance>

summary: .specify/workflows/runs/<run-id>/planning-review-summary.json
```

Surface product decisions through the active human-interaction channel — they are,
by definition, not yours to answer. Then write the answers back into `spec.md`
and rerun.

Implementation must not start unless the verdict is `approved` or
`founder-accepted`.
