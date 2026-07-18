# ADR-0005: Adopt GitHub Spec Kit for feature specification workflow

Date: 2026-07-16
Status: Accepted
Decision owner: BrainBuddy
Related: `.specify/`, `.claude/skills/`, `specs/`, `docs/spec-kit-workflow.md`,
ADR-0001, ADR-0002, Kanban task `t_3b2a9cc9`

## Context

BrainBuddy already had a partial `.specify/` scaffold, a project constitution,
and feature specs. Future agents need a consistent way to author feature specs
without inventing ad-hoc directories, silently skipping clarification, or treating
generated task lists as permission to bypass the repository delivery workflow.

The project is moving toward a voice/text capture -> review -> route/CRT vNext
loop with mobile-first voice interactions, strong consent/privacy guarantees,
and modular-monolith boundaries captured in ADR-0001 and ADR-0002. Those rules
need to be reflected in every new feature specification before implementation
starts.

## Decision

Adopt the official `github/spec-kit` release `v0.12.17` as BrainBuddy's mandatory
feature-spec authoring workflow. Refresh the existing repository scaffold using
the pinned CLI through isolated `uv tool`/`uvx`, install the supported Claude
Code skills integration, and preserve existing specs, ADRs, and constitution
history.

The canonical path for new or materially changed feature specs is:

```text
constitution -> /speckit-specify -> /speckit-clarify -> /speckit-plan -> /speckit-checklist -> /speckit-tasks -> Hermes Kanban handoff
```

Spec Kit owns versioned planning artifacts under `specs/` and project workflow
infrastructure under `.specify/` plus `.claude/skills/`. Hermes Kanban remains
responsible for task routing, implementation ownership, review handoffs, CI/PR
traceability, and release gates. BrainBuddy disables `/speckit-implement` and
keeps the runnable `speckit` workflow planning-only.

Architect-profile agents own Spec Kit technical planning for new or materially
changed architecture/feature specs: module boundaries, contracts, ADR alignment,
data handling, observability, release gates, and implementation handoff. The
implementation profiles consume the architect-owned artifacts from their Kanban
cards rather than inventing architecture during delivery.

## Rationale

Spec Kit gives future agents a repeatable, inspected sequence for turning feature
intent into specifications, architecture plans, and task breakdowns. Pinning the
exact upstream release makes future refreshes reviewable and avoids accidental
template drift.

Preserving the BrainBuddy constitution and ADR history matters because generic
Spec Kit defaults do not know this project's consent, operation, mobile voice,
module ownership, or release constraints. The adopted workflow therefore extends
upstream templates with BrainBuddy-specific gates instead of replacing them.

Keeping Hermes Kanban as the execution/orchestration layer prevents a generated
`tasks.md` file from becoming an unreviewed implementation authority. Specs guide
implementation; they do not replace isolated worktrees, tests, review, CI, PRs,
or releases.

## Alternatives considered

### Continue with ad-hoc specs

This would avoid tool refresh work, but future agents would keep creating mixed
spec formats and could miss clarification, planning, artifact completeness, or
ADR alignment.

### Regenerate all historical specs

Regenerating old specs would make directories visually uniform, but it risks
fabricating history and overwriting accepted ADR/spec intent. Historical specs
are preserved and grandfathered instead.

### Treat Spec Kit as the implementation orchestrator

Spec Kit includes implementation-oriented commands, but using it as the primary
orchestrator would duplicate Kanban and weaken review/release traceability. The
project keeps Spec Kit scoped to authoring and planning.

## Consequences

Positive consequences:
- New feature specs have a single documented workflow and minimum artifact set.
- Claude Code receives first-class Spec Kit skills in the repository.
- BrainBuddy quality gates are encoded in the constitution, templates, docs, and
  CI check rather than relying on memory.
- The installed workflow cannot advance into implementation outside Hermes
  Kanban, PR review, and CI gates.

Tradeoffs / risks:
- Spec Kit refreshes can overwrite templates, so future updates require `git diff`
  review and reapplication of project-specific gates.
- Historical specs are not uniform; the check explicitly documents grandfathering.
- Future Spec Kit refreshes may reinstall implementation commands, so reviews
  must preserve the local disabled `/speckit-implement` stub and planning-only
  workflow.

What future agents must preserve:
- Pin and document the Spec Kit release used for repository refreshes.
- Do not pip-install Spec Kit into Hermes or application environments.
- Amend specs before changing implementation intent.
- Keep generated `tasks.md` subordinate to Kanban, TDD, review, CI, PR, merge,
  and release gates.
- Keep checklist invocation after plan generation unless the checklist skill is
  intentionally customized to work before `plan.md` exists.
- Keep architecture ownership in the architect profile; implementation agents
  should consume spec/plan/task artifacts, not create unreviewed architecture.

## Verification / tests

- `uvx --from git+https://github.com/github/spec-kit.git@v0.12.17 specify --version`
  reports `specify 0.12.17`.
- `specify check` reports Claude Code available.
- `uvx --from git+https://github.com/github/spec-kit.git@v0.12.17 specify init --here --integration claude --force`
  refreshes the repository while preserving the existing constitution.
- The local `.specify/workflows/speckit/workflow.yml` ends at tasks plus Hermes
  Kanban handoff and does not call `speckit.implement`.
- `python3 scripts/check_spec_kit_specs.py` validates required new-spec artifacts,
  regular nonempty files, and documented grandfathering baselines.
- `python3 -m unittest scripts/test_check_spec_kit_specs.py -v` covers missing
  grandfathered normative files, modified grandfathered content, and
  directory-shaped artifact paths.
- CI runs the same deterministic spec check before backend/frontend jobs.

## Related files

- `.specify/memory/constitution.md`
- `.specify/templates/spec-template.md`
- `.specify/templates/plan-template.md`
- `.specify/templates/tasks-template.md`
- `.specify/templates/checklist-template.md`
- `.claude/skills/`
- `docs/spec-kit-workflow.md`
- `scripts/check_spec_kit_specs.py`
- `.github/workflows/ci.yml`
