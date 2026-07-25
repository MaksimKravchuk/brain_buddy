# BrainBuddy Spec Kit workflow

BrainBuddy uses the official GitHub Spec Kit as the mandatory authoring workflow
for every new or materially changed feature specification.

- Spec Kit version: `github/spec-kit` `v0.14.2`
- Verified release date: 2026-07-24
- Installed integration: Claude Code skills under `.claude/skills/`
- Scope: feature specification and planning artifacts under `specs/`
- Non-scope: execution orchestration, code review, CI, merge, release, or deploy

## Install and verify prerequisites

Use isolated uv tooling. Do not install Spec Kit with pip inside the Hermes
runtime or the application backend/frontend environments.

```bash
uv tool install specify-cli --force --from git+https://github.com/github/spec-kit.git@v0.14.2
specify --version
specify check
specify integration list
```

Expected version output:

```text
specify 0.14.2
```

`specify check` should show Claude Code as available for the Claude workflow.
If the CLI needs to be refreshed without modifying the global uv tool install,
use the same pinned release through `uvx`:

```bash
uvx --from git+https://github.com/github/spec-kit.git@v0.14.2 specify --version
```

## Refreshing Spec Kit in this repository

This repository is refreshed from the official pinned release with the
manifest-aware upgrade path:

```bash
specify integration status --json
specify integration upgrade claude --force
# If reviewed extensions are installed, update each pinned extension explicitly:
# specify extension update <extension-id>
```

Do not run an unscoped `specify extension update`: community extensions have
independent versions and require their own source review. No extensions were
installed during the v0.14.2 refresh.

Before the forced integration refresh, preserve the BrainBuddy-specific disabled
`speckit-implement` stub and the four customized templates. Restore them after
the refresh, inspect `git diff`, and accept the expected integration-status
warning for those five deliberate overrides. The current refresh installs
v0.14.2 shared assets under `.specify/` and Claude Code skills under
`.claude/skills/`.

After any future refresh:

1. Inspect `git diff` before accepting changes.
2. Preserve `.specify/memory/constitution.md` and project-specific template gates.
3. Confirm `.specify/init-options.json` keeps `speckit_version` at the intended
   version and `ai_skills`/`integration` for Claude.
4. Confirm the local `speckit` workflow remains planning-only and does not call
   `speckit.implement`.
5. Run `python3 scripts/check_spec_kit_specs.py`.
6. Run any affected backend/frontend checks before opening a PR.

## Canonical feature-spec path

For every new or materially changed BrainBuddy feature:

1. Read `.specify/memory/constitution.md`, `AGENTS.md`, `CLAUDE.md`, and relevant
   ADRs under `docs/decisions/`.
2. Use `/speckit-constitution` only when governance principles or dependent
   templates need a real amendment.
3. Use `/speckit-specify` to create or update the feature's `spec.md` with the
   what and why. Do not include implementation design here except as constraints.
4. Use `/speckit-clarify` to resolve ambiguous requirements before planning.
5. Use `/speckit-plan` to describe architecture, module ownership, contracts,
   tests, data handling, observability, mobile/resilience, and release gates.
6. Use `/speckit-checklist` after `/speckit-plan`. Under the pinned v0.14.2
   workflow, checklist setup calls the prerequisites script, which
   requires `plan.md`; do not document or run checklist as a pre-plan command.
7. Use `/speckit-tasks` to generate implementation tasks grouped by independently
   testable user story.
8. Hand the resulting artifacts to Hermes Kanban implementation cards instead of
   executing implementation in Spec Kit.
9. Amend the spec/plan/tasks first whenever implementation intent changes.

For Claude Code and Hermes Agent in this repository, Spec Kit is installed as
skills, so the invocation names use hyphens:

```text
/speckit-constitution
/speckit-specify
/speckit-clarify
/speckit-plan
/speckit-checklist
/speckit-tasks
/speckit-analyze
```

The Claude integration keeps `/speckit-implement` only as a disabled
compatibility stub. The Hermes architect profile receives only the planning
skills listed above through `/speckit-analyze`; it does not receive
`speckit-implement` or `speckit-taskstoissues`. Neither command may run
implementation tasks, publish one issue/card per task line, execute hooks,
commit, or edit product source. Implementation starts only when Hermes Kanban
dispatches the owning specialist profile into an isolated worktree with TDD,
review, CI, PR, and release gates.

## Architect-owned Kanban path

When a BrainBuddy architecture or feature spec is new or materially changed, the
architect profile owns the Spec Kit planning lane before implementation begins.
The runnable Kanban path is:

1. Create or claim an architect-owned Kanban card for spec authoring/planning.
2. In that card's worktree, run the canonical sequence through the official
   Hermes Spec Kit skills: `/speckit-specify`, `/speckit-clarify`,
   `/speckit-plan`, `/speckit-checklist`, `/speckit-tasks`, and
   `/speckit-analyze`. Claude Code may still be delegated bounded architecture
   analysis, but Hermes owns the planning lane and artifact handoff.
3. In `/speckit-plan`, the architect profile owns technical planning,
   architecture boundaries, module ownership, contracts, ADR alignment, data
   handling, observability, and release gates.
4. If an architecture decision changes, update or add the relevant ADR before
   handing implementation to another profile.
5. Hand one compact execution summary to the canonical outcome root with the
   spec, plan, and tasks paths; coarse independent lanes; risk; integration
   evidence; and release policy. Native Hermes decomposition creates 2-6
   execution lanes. Never publish one Kanban card per `tasks.md` line.
6. Implementation agents consume those artifacts; they do not invent module
   boundaries or architecture that conflicts with the architect handoff.

## Artifact minimum for new specs

New non-grandfathered directories under `specs/` must use
`NNN-kebab-case-feature` naming and include at least:

```text
spec.md
checklists/requirements.md
plan.md
tasks.md
```

Additional Spec Kit artifacts such as `research.md`, `data-model.md`,
`quickstart.md`, and `contracts/` should be present when the feature needs them.
Run the deterministic check before opening a PR:

```bash
python3 scripts/check_spec_kit_specs.py
# or
make check-specs
```

## Historical grandfathering

Existing history is preserved rather than regenerated blindly.

- `specs/001-relation-linking-refactor/` already contains a complete historical
  Spec Kit-style artifact set and remains valid.
- `specs/002-async-voice-workflows/` predates the initial v0.12.17 adoption and is
  grandfathered with `spec.md` plus `acceptance-tests.md`. Its acceptance tests
  are normative for ADR-0002. Do not fabricate missing generated files unless
  the feature is materially changed.
- `requirements/` remains historical context. Where it conflicts with the
  current constitution, ADRs, auth docs, live schemas, or `specs/`, the latter
  sources win.

## Boundary with Hermes Kanban

Spec Kit generates and maintains planning artifacts. Hermes Kanban remains the
execution/orchestration and PR-review system.

Generated `tasks.md` is planning input only. It is not permission to bypass:

- assigned Kanban cards and specialist ownership;
- isolated worktrees and branch discipline;
- tests-before-implementation expectations;
- independent review and `review-required` handoffs;
- CI, merge, and Fly release gates.

Spec changes should be committed and reviewed like product code changes.
