---
name: "speckit-implement"
description: "Implement a feature directly from its approved tasks.md via an isolated worktree and TDD, preserving the repository's review, CI and landing gates."
argument-hint: "Feature slug and explicit PR-NN slice when tasks.md has PR-срезы"
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
5. If `tasks.md` has a `## PR-срезы` section, the request names exactly one `PR-NN`
   slice. Run `python3 scripts/check_spec_kit_specs.py`, read its task IDs,
   dependencies, paths, tests and acceptance evidence, and stop if that slice
   is absent, unapproved or blocked by an unfinished dependency. **Never**
   interpret empty arguments as permission to implement all of `tasks.md`.
   The user-approved slice map fixes the scope; do not edit it to make a
   worker's changed files fit.

## Route

Implement in an isolated git worktree and a dedicated task session. An agent
may delegate to another implementation worker, but no named agent runtime or
subagent facility is required. Keep long build/test transcripts out of the
planning session; report verified results and file paths back to it.

For a multi-PR feature, give each slice its **own session, worktree, branch,
and PR**. Pass only that slice's tasks and allowed write paths to the worker.
Before opening the PR, compare the actual diff to its path scope and run the
slice's tests; a cross-slice file or task requires a revised, reapproved plan.
The PR body links the same feature spec, slice id, FR/SC IDs, dependency PRs,
test evidence, and exact head SHA. Verify review and CI for that SHA. Never
open one PR containing the whole spec in place of the agreed slices. Integrate
dependent slices sequentially from the accepted base; independent slices can
run concurrently only when code and test resources really are isolated.
Keep only a short parent ledger: slice, owner, branch/worktree, PR URL, exact
SHA, CI, review, next action. Do not paste each worker's build logs into the
parent session. Dependent slices start from an updated `origin/main` after
their prerequisite lands, as required by BrainBuddy's current-base landing
rules. Full feature acceptance follows integration of **all** slices.

Per ADR-0008, a PR is review evidence, not implicit merge/deploy authority:
SHIP/SHOW still use verified candidate landing; ASK needs explicit approval
and the audited landing procedure. Do not merge, push to `main`, or deploy
merely because slice CI is green.

For tasks marked `[P]`, prefer independent worktrees and short-lived sessions
over unbounded in-process parallel subagents. Two constraints make fan-out
counterproductive here:

- Landing is serial by construction. `scripts/submit_to_trunk.sh` requires
  exactly one non-merge commit whose parent equals current `origin/main`, so N
  parallel lanes must funnel through a rebase-and-resubmit queue anyway.
- `scripts/run_playwright_e2e.sh` deletes shared Playwright artifact
  directories on start, destroying a concurrent agent's in-flight evidence.

When lanes do run in parallel, each needs a distinct `BRAIN_BUDDY_DATA_DIR`,
backend port, frontend port, `BRAIN_BUDDY_MOBILE_IT_PORT` and
`BRAIN_BUDDY_E2E_PROJECT`. A worktree isolates none of those.

## Gates that survive this change

Direct implementation removes a routing hop. It removes no gate:

- **Isolated worktree and feature branch** — never implement on the primary
  worktree.
- **Tests before implementation** — Constitution Principle II. Write the
  failing test, watch it fail for the right reason, then implement.
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
feature:  specs/NNN-<slug>     branch: feat/<slug>
slice:    PR-NN (or single-PR)   PR: <URL or not opened>
tasks:    <n>/<n>              commits: <shas>
tests added: <n>

SELF-VERIFY: backend <pass|fail> frontend <pass|fail> mobile <pass|fail> e2e <pass|fail|n/a>
LANDING CLASS: SHIP | SHOW | ASK  (per classify_path_risk.py)

DEVIATIONS
- <what differed from plan.md, and why>

NEXT: slice review/CI; then next dependent slice, and /speckit-accept after integration
```
