# ADR-0011: Proportional Spec Kit planning policy

Date: 2026-08-05
Status: Accepted
Decision owner: BrainBuddy
Related: ADR-0009, `AGENTS.md`, `docs/spec-kit-workflow.md`, `.specify/workflows/speckit/`

## Context

ADR-0009 correctly separated read-only planning review from writable Hermes
execution, but the repository still treated Spec Kit as a mandatory gate for
every new or materially changed feature. The first live Paperclip feature exposed
three operational failures in that policy:

1. a custom review process allowed 900 seconds while its workflow shell step used
   an implicit 300-second timeout, so valid reviewers were killed as failures;
2. Paperclip represented review/runtime repair as a separate child blocker,
   creating task and question loops instead of advancing the owning feature; and
3. reversible technical decisions were escalated to the founder even though they
   belonged to the Architect.

The review itself produced useful evidence for genuinely high-risk AI/privacy and
concurrency work. The problem was not independent review; it was applying the
same blocking mechanism to every change and letting planning machinery become a
second runtime.

## Decision

This ADR supersedes the mandatory-gate parts of ADR-0009. ADR-0009's read-only
sandbox, strict response validation, bounded fan-out/fan-in, and Hermes-only
execution boundary remain in force.

Every owning Hermes card is classified by its effects before Spec Kit is
invoked. Any high-risk effect wins even when the work is described as a bug fix,
maintenance, or refactor:

- **Small maintenance:** operational repairs, dependency/tooling
  maintenance, and behavior-preserving refactors with explicit intent that touch
  no high-risk category. Do not invoke Spec Kit.
- **Standard feature:** bounded and reversible feature behavior without a
  high-risk category. Spec Kit planning and review are advisory. Reviewer,
  workflow, timeout, quota, malformed-output, or handoff-generation failure is
  recorded on the owning card and does not block implementation through the
  normal Hermes TDD, review, CI, and release gates.
- **High risk:** auth, privacy, security, destructive data/schema changes, public
  contracts, migrations, concurrency, payments, safety/compliance, or
  irreversible effects. A bounded review and validated handoff remain required
  before implementation. The Architect may perform at most one rerun after
  correcting technical findings; explicit founder acceptance remains the escape
  hatch for a non-converging but fully evidenced campaign.

A Spec Kit failure or finding must not create a separate process-gate card. It
stays on the owning feature card with one technical owner and one next action.
Only genuine scope, UX, priority, privacy/legal posture, permissions, pricing,
safety/compliance, or irreversible authority may put that owning card into
`needs_input`. Missing acceptance behavior with a safe, reversible pilot option
is technical: the Architect selects the safest default and records it as finding
remediation rather than creating a founder question.

The lifecycle boundary is:

```text
Spec Kit artifacts/review = optional standard planning; mandatory high-risk intent evidence
Hermes owning card         = durable scope, decisions, blockers, and user interaction
Hermes runtime             = sole claims, worktrees, implementation, review, CI, landing, deploy
```

A heartbeat must not claim progress merely because it started a child workflow.
It must await terminal success/failure or use an independently tracked process
whose owner and terminal-state reconciliation are explicit. Stale `running`
files without a live process are failed/orphaned evidence, never progress.

The reviewer process timeout is 900 seconds and every containing workflow shell
step must exceed it (currently 960 seconds) so the reviewer can return its own
structured timeout failure. Every reviewer runs in its own process group and
bounded timeout cleanup terminates and reaps that group, preventing orphaned
provider descendants. Review campaigns remain bounded to one initial run
and at most one corrective rerun. Preflight fingerprints every tracked or
unignored worktree file; a mid-campaign edit invalidates the campaign instead of
mixing reviewer evidence from different snapshots. After the corrective run,
unresolved findings remain one factual blocker on the owning card without an
automatic campaign loop.

For standard work with unavailable advisory review, no approval is fabricated.
The owning card carries explicit scope and acceptance evidence, and an incomplete
generated Spec Kit package is not committed. For high-risk work, this fallback is
not permitted.

## Consequences

Positive:

- planning effort is proportional to product and operational risk;
- runtime/tool failures cannot create self-reproducing Kanban blockers;
- founder attention is reserved for authority and product decisions;
- useful adversarial review remains mandatory where defects are expensive or
  irreversible; and
- Hermes remains the single execution runtime.

Tradeoffs:

- standard changes may proceed without independent planning review when tooling
  is unavailable;
- risk classification must be explicit and reviewable on the owning card; and
- high-risk planning can still block implementation, but only with concrete
  findings on the original feature rather than a process-only child task.

## Verification

- `scripts/test_spec_kit_planning_review.py` asserts the proportional policy is
  present in `AGENTS.md`, `README.md`, this ADR, and the workflow runbook.
- Workflow contract tests assert both standard and high-risk reviewer steps have
  a 960-second shell timeout, greater than the 900-second reviewer subprocess
  timeout.
- Reviewer tests reject the broad `acceptance-behavior` escalation category,
  require reversible pilot defaults to remain Architect-owned, and fail a
  campaign when the worktree fingerprint changes.
- `python3 scripts/check_spec_kit_specs.py` continues to validate committed Spec
  Kit packages and rejects fabricated or malformed handoffs.
- Kanban review verifies no Spec Kit timeout, malformed result, quota issue, or
  handoff repair creates a child/process-gate card.
