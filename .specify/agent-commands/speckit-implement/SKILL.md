---
name: "speckit-implement"
description: "Implement a feature directly from its approved tasks.md via an isolated worktree and Constitution Principle II's proportionate testing policy, preserving the repository's review, CI and landing gates."
argument-hint: "Feature slug and, when tasks.md has PR-срезы, one PR-NN slice or all (conductor mode)"
compatibility: "Requires spec-kit project structure with .specify/ directory"
metadata:
  author: "github-spec-kit + brainbuddy"
  source: "templates/commands/implement.md (brainbuddy override — see docs/spec-kit-workflow.md preserved overrides)"
user-invocable: true
disable-model-invocation: false
---

## User Input

```text
$ARGUMENTS
```

# Implementation stage

> **This file is a preserved BrainBuddy override.** It intentionally diverges
> from upstream `github/spec-kit` v1.0.11 and is listed in the preserved-overrides
> table in `docs/spec-kit-workflow.md`. `scripts/check_speckit_manifests.py`
> guards it. `specify integration upgrade generic --force` must not silently
> revert it. This is the canonical, runtime-neutral implementation policy.

Implementation runs **directly** from the validated Spec Kit artifacts. This
matches `CLAUDE.md`, `.specify/memory/constitution.md` and
`docs/spec-kit-workflow.md`, all three of which say the artifacts may be
implemented by a developer or a standalone agent.

An earlier version of this file said the opposite — stop, route everything
through Hermes Kanban — which contradicted those three authorities and stalled
any agent that read skills before docs. That contradiction is resolved in
favour of direct implementation. Hermes remains available as an **explicitly
activated** branch, never an inferred default.

## Preconditions — verify, do not assume

Stop and report instead of starting if any fails:

1. `specs/NNN-<slug>/tasks.md` exists, is non-empty, and its tasks name real
   file paths.
2. The review gate returned `approved` or `founder-accepted`. Read
   `.specify/workflows/runs/<run-id>/planning-review-summary.json`. A status of
   `technical-changes-required` or `product-decision-required` blocks the
   stage. You never overrule the gate.
3. `/speckit-analyze` reported zero CRITICAL findings.
4. `plan.md` cites `design.md` when the feature has a user-visible surface.
5. If `tasks.md` has a `## PR-срезы` section, the request names either exactly
   one `PR-NN` slice (**worker mode**) or `all` (**conductor mode**, below).
   Run `python3 scripts/check_spec_kit_specs.py`, read the task IDs,
   dependencies, paths, budgets, tests and acceptance evidence, and stop if a
   named slice is absent, unapproved or blocked by an unfinished dependency.
   **Never** interpret empty arguments as permission to
   implement all of `tasks.md`, and never put more than one slice in one PR. The user-approved
   slice map fixes the scope; do not edit it to make a worker's changed files
   fit.

## Route

Implement in an isolated git worktree and a dedicated task session. Keep long
build/test transcripts out of the planning session; report verified results
and file paths back to it.

Every slice gets its **own worker, worktree, branch and PR**. Pass a worker
only its slice's tasks, write paths and budget. Before opening the PR, compare
the actual diff to the slice's path scope, run
`python3 scripts/check_slice_budget.py specs/NNN-<slug>/tasks.md PR-NN` and the
slice's tests; a cross-slice file, a missed budget or a cross-slice task needs
a revised, reapproved map, not a bigger PR. The PR body links the feature spec,
slice id, FR/SC IDs, dependency PRs, test evidence and exact head SHA. Never
open one PR containing the whole spec in place of the agreed slices.

### Conductor mode: parallel by default

Like upstream Spec Kit, which runs `[P]` tasks together, independent work runs
**in parallel by default**. With `all`, the session that holds the slice map is
the conductor:

1. Compute the ready set: slices whose `depends_on` have all merged.
2. Launch one worker per ready slice **at the same time**, each in its own
   worktree, choosing the agent by the slice's `implementer` field:

   | Work | Agent | Model |
   |---|---|---|
   | Slice that changes behavior or a contract | `feature-implementer` | Sonnet |
   | Mechanical slice (rename, fixtures, pattern-following tests, docs) | `mechanical-implementer` | Haiku |
   | Reading a long CI or test log | `ci-log-triage` | Haiku |
   | Full-suite verification | `delivery-verifier` | Sonnet |
   | Feature acceptance after all slices | `acceptance-auditor` | Opus |

   The conductor itself plans, reviews diffs against the slice map and
   resolves cross-slice questions; it does not write slice code. Runtimes
   without named agents use the same split with whatever model choice they
   offer.
3. Push each finished slice and open its PR; route CI failures through
   `ci-log-triage` and fix them in the slice's own branch.
4. As slices merge, recompute the ready set and launch the next wave.
   Dependent slices start from an updated `origin/main` after their
   prerequisite merges, never from a speculative sibling branch.
5. Keep only a short ledger: slice, agent, branch/worktree, PR URL, exact SHA,
   CI, review, next action. Never paste a worker's logs into it.

Parallel workers collide on what a worktree does not isolate. Give each a
distinct `BRAIN_BUDDY_DATA_DIR`, backend port, frontend port and
`BRAIN_BUDDY_E2E_PROJECT` (`scripts/run_playwright_e2e.sh` deletes the shared
Playwright artifact directories otherwise). Independent slices already have
disjoint write paths — `check_spec_kit_specs.py` rejects overlap — so parallel
PRs merge one after another without conflicts in their own files.

Full feature acceptance follows integration of **all** slices.

Per ADR-0008, a PR is review evidence, not implicit merge/deploy authority:
SHIP/SHOW still use verified candidate landing; ASK needs explicit approval
and the audited landing procedure. Do not merge, push to `main`, or deploy
merely because slice CI is green.

## Gates that survive this change

Direct implementation removes a routing hop. It removes no gate:

- **Isolated worktree and feature branch** — never implement on the primary
  worktree.
- **Proportionate testing** — read and apply
  [Constitution Principle II](../../memory/constitution.md#ii-tested-delivery-across-stack)
  for test selection, reuse, test-first applicability, and verification order.
  Sufficient existing checks count; technical tasks do not each need a new test.
- **Independent review** — the implementer does not grade its own work;
  `/speckit-accept` obtains a separate acceptance audit.
- **CI** — `make verify-all` green before landing.
- **ADR-0008 landing** — `scripts/classify_path_risk.py` decides SHIP/SHOW vs
  ASK. ASK-class changes land through a reviewed PR, never automatic trunk
  promotion.
- **Allure taxonomy** on every product test, with the covering `FR-###` /
  `SC-###` in the test name or story.

## Optional Hermes managed outcome

Only when the invoking task carries explicit signed scope enrolling this
outcome under ADR-0010. In that case `docs/spec-driven-kanban.md` becomes
authoritative for that run: create or update Kanban cards from `tasks.md`,
each naming its specialist profile, worktree, review gate and required checks.

Do **not** infer managed mode from the presence of plugin files, a Hermes
installation, or `.hermes.md`. Absent explicit activation, implement directly.

## Completion report

```
IMPLEMENTATION: complete | blocked
feature:  specs/NNN-<slug>     mode: worker PR-NN | conductor all | single-PR
slices:   <per slice: id, agent, branch, PR URL or not opened, budget used>
tasks:    <n>/<n>              commits: <shas>
test evidence: <reused checks and any necessary additions>

SELF-VERIFY: backend <pass|fail> frontend <pass|fail> e2e <pass|fail|n/a>
LANDING CLASS: SHIP | SHOW | ASK  (per classify_path_risk.py)

DEVIATIONS
- <what differed from plan.md, and why>

NEXT: slice review/CI; then next dependent slice, and /speckit-accept after integration
```
